// The composer's microphone (BOUNDARY rule 54): press to record in this window, press again (or Enter) to stop,
// Cancel (or Escape) to discard. The recording goes to the bot's own Hermes for its transcript, which lands in the draft
// at the caret and is never sent by omher. The microphone opens only on the press and every track is stopped on stop,
// cancel, an error, a chat switch, the window being hidden and the composer going away.
import { useEffect, useRef, useState, type ReactNode } from "react";
import type { Bot, VoiceInfo } from "../../lib/protocol";
import { useStore } from "../../state/store";
import { useServerMode } from "../../app/remote";
import { t, type Key } from "../../i18n";
import { setMicBusy, stopSpeech, voiceInfoOnce } from "./speech";
import {
  allowVoice,
  blobBase64,
  canRecord,
  clock,
  micFailure,
  osOf,
  pickMime,
  RECORD_MAX_BYTES,
  RECORD_MAX_MS,
  STT_WHERE,
  voiceAllowed,
  voiceFailure,
} from "./voice";
import { VoiceNotice } from "./VoiceNotice";
import "./voice.css";

const MicIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <rect x="9" y="3" width="6" height="11" rx="3" />
    <path d="M5.5 11a6.5 6.5 0 0 0 13 0" />
    <path d="M12 17.5V21" />
  </svg>
);
const StopIcon = () => (
  <svg width="11" height="11" viewBox="0 0 24 24" aria-hidden="true">
    <rect x="5" y="5" width="14" height="14" rx="2.5" fill="currentColor" />
  </svg>
);

type Phase = { kind: "idle" } | { kind: "opening" } | { kind: "recording"; started: number } | { kind: "transcribing" };
type Line =
  | { kind: "done"; provider: string; limit: boolean }
  | { kind: "silent"; limit: boolean }
  | { kind: "fail"; head: Key; said?: string; hint?: Key };
type Take = { stream: MediaStream; recorder: MediaRecorder; chunks: Blob[]; bytes: number; type: string; limit: boolean; timers: ReturnType<typeof setTimeout>[] };

export interface VoiceMic {
  /** The button for the composer's row, or null when this chat has no microphone. */
  button: ReactNode;
  /** The recording's state, the first-use notice or the last outcome, for above the text. */
  line: ReactNode;
  /** A recording runs: Enter stops it instead of sending. */
  recording: boolean;
  /** Something can be cancelled (opening, recording, transcribing): Escape cancels it. */
  busy: boolean;
  stop(): void;
  cancel(): void;
}

export function useVoiceMic({ bot, offline, insert, focusBox }: {
  bot?: Bot;
  offline: boolean;
  insert: (words: string) => void;
  /** Put the keyboard in the composer's text box (after Continue, so Enter stops and Escape cancels the recording). */
  focusBox: () => void;
}): VoiceMic {
  const s = useStore();
  const remote = useServerMode().mode === "remote";
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  const [line, setLine] = useState<Line | null>(null);
  const [ask, setAsk] = useState<VoiceInfo | null>(null);
  const [now, setNow] = useState(0);
  const take = useRef<Take | null>(null);
  const gen = useRef(0);
  const [supported] = useState(() => canRecord());
  const insertRef = useRef(insert);
  insertRef.current = insert;
  const btn = useRef<HTMLButtonElement>(null);
  // read aloud is off while this composer's microphone opens, records or waits for its transcript (speech.ts)
  const busyNow = phase.kind !== "idle";
  useEffect(() => setMicBusy(busyNow), [busyNow]);
  useEffect(() => () => setMicBusy(false), []);

  /** Stop every track and timer of the take and let go of it (its bytes too). */
  const release = () => {
    const k = take.current;
    take.current = null;
    if (!k) return;
    k.timers.forEach((x) => clearTimeout(x));
    k.recorder.ondataavailable = null;
    k.recorder.onstop = null;
    k.recorder.onerror = null;
    if (k.recorder.state !== "inactive") {
      try {
        k.recorder.stop();
      } catch {
        /* already stopped */
      }
    }
    k.stream.getTracks().forEach((tr) => tr.stop());
    k.chunks.length = 0;
  };
  const cancel = () => {
    gen.current += 1;
    release();
    setPhase({ kind: "idle" });
  };
  const releaseRef = useRef(release);
  releaseRef.current = release;
  // the composer goes (a chat switch, Settings): the microphone closes and an answer still on its way is dropped
  useEffect(
    () => () => {
      gen.current += 1;
      releaseRef.current();
    },
    [],
  );
  // the window is hidden or the page unloads: nothing records in the background
  useEffect(() => {
    const away = () => {
      if (document.visibilityState === "hidden" && take.current) {
        gen.current += 1;
        releaseRef.current();
        setPhase({ kind: "idle" });
      }
    };
    const gone = () => {
      gen.current += 1;
      releaseRef.current();
    };
    document.addEventListener("visibilitychange", away);
    window.addEventListener("pagehide", gone);
    return () => {
      document.removeEventListener("visibilitychange", away);
      window.removeEventListener("pagehide", gone);
    };
  }, []);

  if (!bot) return { button: null, line: null, recording: false, busy: false, stop: () => {}, cancel: () => {} };
  const off: Key | null = bot.host ? "voice.offPeer" : remote ? "voice.offRemote" : !supported ? "voice.noApi" : null;

  const finish = async (my: number) => {
    const k = take.current;
    if (!k) return;
    const blob = new Blob(k.chunks, { type: k.recorder.mimeType || k.type || "audio/webm" });
    const limit = k.limit;
    release();
    if (my !== gen.current) return;
    if (!blob.size) {
      setPhase({ kind: "idle" });
      return setLine({ kind: "silent", limit });
    }
    setPhase({ kind: "transcribing" });
    try {
      const data = await blobBase64(blob);
      if (my !== gen.current) return;
      const out = await s.voiceTranscribe(bot.name, data, blob.type);
      if (my !== gen.current) return;
      if (out.transcript.trim()) {
        insertRef.current(out.transcript);
        setLine({ kind: "done", provider: out.provider, limit });
      } else setLine({ kind: "silent", limit });
    } catch (e) {
      if (my === gen.current) setLine({ kind: "fail", ...voiceFailure(e) });
    }
    if (my === gen.current) setPhase({ kind: "idle" });
  };

  const stopTake = (limit = false) => {
    const k = take.current;
    if (!k) return;
    k.limit = k.limit || limit;
    if (k.recorder.state !== "inactive") k.recorder.stop();
  };

  const open = async () => {
    stopSpeech(); // an answer being read aloud would be recorded with the voice
    const my = ++gen.current;
    setLine(null);
    setPhase({ kind: "opening" });
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    } catch (e) {
      if (my === gen.current) {
        setLine({ kind: "fail", ...micFailure(e, osOf()) });
        setPhase({ kind: "idle" });
      }
      return;
    }
    if (my !== gen.current) return stream.getTracks().forEach((tr) => tr.stop());
    const type = pickMime((x) => MediaRecorder.isTypeSupported(x));
    let recorder: MediaRecorder;
    try {
      recorder = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
    } catch (e) {
      stream.getTracks().forEach((tr) => tr.stop());
      setLine({ kind: "fail", ...micFailure(e, osOf()) });
      return setPhase({ kind: "idle" });
    }
    const k: Take = { stream, recorder, chunks: [], bytes: 0, type, limit: false, timers: [] };
    take.current = k;
    recorder.ondataavailable = (ev) => {
      if (take.current !== k || !ev.data.size) return;
      k.chunks.push(ev.data);
      k.bytes += ev.data.size;
      if (k.bytes >= RECORD_MAX_BYTES) stopTake(true);
    };
    recorder.onstop = () => {
      if (take.current === k) void finish(my);
    };
    recorder.onerror = (ev) => {
      if (take.current !== k) return;
      release();
      setLine({ kind: "fail", ...micFailure((ev as Event & { error?: unknown }).error, osOf()) });
      setPhase({ kind: "idle" });
    };
    try {
      recorder.start(1000); // a chunk a second, so the size limit is seen while it records
    } catch (e) {
      release();
      setLine({ kind: "fail", ...micFailure(e, osOf()) });
      return setPhase({ kind: "idle" });
    }
    const started = Date.now();
    k.timers.push(setTimeout(() => stopTake(true), RECORD_MAX_MS));
    const tickEvery = () => {
      setNow(Date.now());
      if (take.current === k) k.timers.push(setTimeout(tickEvery, 500));
    };
    tickEvery();
    setPhase({ kind: "recording", started });
  };

  const press = () => {
    if (off) return setLine({ kind: "fail", head: off, hint: off === "voice.noApi" && osOf() === "linux" ? "voice.noApiLinux" : undefined });
    if (offline) return;
    if (phase.kind === "recording") return stopTake();
    if (phase.kind !== "idle") return cancel();
    if (ask) return setAsk(null);
    setLine(null);
    if (voiceAllowed("mic", bot.name)) return void open();
    voiceInfoOnce(bot.name, s.voiceInfo).then(
      (info) => (info.supported ? setAsk(info) : setLine({ kind: "fail", head: "voice.errUnsupported", said: info.line })),
      (e: unknown) => setLine({ kind: "fail", ...voiceFailure(e) }),
    );
  };

  const recording = phase.kind === "recording";
  const label = off
    ? t(off)
    : recording
      ? t("voice.stopRecording")
      : phase.kind === "transcribing"
        ? t("voice.cancelTranscribing")
        : t("voice.record");
  const button = (
    <button
      ref={btn}
      type="button"
      className={`att-plus voice-mic${recording ? " on" : ""}`}
      aria-label={label}
      title={label}
      aria-pressed={recording}
      aria-disabled={off || offline ? true : undefined}
      onClick={press}
      data-testid="mic"
      data-state={off ? "off" : phase.kind}
    >
      {recording ? <StopIcon /> : <MicIcon />}
    </button>
  );
  const cancelBtn = (
    <button type="button" className="voice-link" onClick={cancel} data-testid="mic-cancel">
      {t("voice.cancel")}
    </button>
  );
  const limitNote = (limit: boolean) => limit && <span className="voice-by">{t("voice.limit", { max: clock(RECORD_MAX_MS) })}</span>;
  const shown: ReactNode = ask ? (
    <VoiceNotice
      testId="mic-notice"
      title={t("voice.micTitle")}
      body={t("voice.micBody", { bot: bot.display_name })}
      where={t(STT_WHERE[ask.stt.where], { provider: ask.stt.provider })}
      onContinue={() => {
        allowVoice("mic", bot.name);
        setAsk(null);
        void open();
        // the keyboard goes to the text box, where Enter stops the recording and Escape cancels it
        requestAnimationFrame(focusBox);
      }}
      onCancel={() => {
        setAsk(null);
        requestAnimationFrame(() => btn.current?.focus());
      }}
    />
  ) : phase.kind === "opening" ? (
    <div className="voice-line" role="status" data-testid="mic-opening">
      {t("voice.opening")} {cancelBtn}
    </div>
  ) : phase.kind === "recording" ? (
    <div className="voice-line rec" data-testid="mic-recording">
      <span className="voice-dot" aria-hidden="true" />
      {/* the live region holds the words only: the clock changes every second and is not read out each time */}
      <span role="status" data-testid="mic-recording-status">
        {t("voice.recording")}
      </span>
      <span className="voice-time" aria-hidden="true" data-testid="mic-elapsed">
        {clock(Math.max(0, now - phase.started))}
      </span>
      <span className="voice-by" aria-hidden="true">
        / {clock(RECORD_MAX_MS)}
      </span>
      <span className="voice-by">{t("voice.stopHint")}</span>
      {cancelBtn}
    </div>
  ) : phase.kind === "transcribing" ? (
    <div className="voice-line" role="status" data-testid="mic-transcribing">
      {t("voice.transcribing")} {cancelBtn}
    </div>
  ) : line?.kind === "done" ? (
    <div className="voice-line quiet" role="status" data-testid="mic-done">
      {line.provider ? t("voice.transcribedBy", { provider: line.provider }) : t("voice.transcribed")}
      {limitNote(line.limit)}
    </div>
  ) : line?.kind === "silent" ? (
    <div className="voice-line" role="status" data-testid="mic-silent">
      {t("voice.noSpeech")}
      {limitNote(line.limit)}
    </div>
  ) : line?.kind === "fail" ? (
    <div className="voice-line err" role="alert" data-testid="mic-error">
      <b>{t(line.head)}</b>
      {line.said && <span className="voice-said">{line.said}</span>}
      {line.hint && <span className="voice-said">{t(line.hint)}</span>}
    </div>
  ) : null;
  return { button, line: shown, recording, busy: phase.kind !== "idle", stop: () => stopTake(), cancel };
}
