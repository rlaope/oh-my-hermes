// Read aloud on a bot's answer (BOUNDARY rule 54): beside the copy button, a quiet speaker that has the bot's own
// Hermes read the answer's text and plays it in this window, with Stop. One answer plays at a time; a chat switch or
// the bubble going away stops it. Before the first use per bot a notice says where the text goes.
import { useEffect, useRef, useState, type ReactNode } from "react";
import type { Bot, VoiceInfo } from "../../lib/protocol";
import { getStore } from "../../state/store";
import { useServerMode } from "../../app/remote";
import { t, type Key } from "../../i18n";
import { readAloud, useMicBusy, voiceInfoOnce, type SpeechState } from "./speech";
import { allowVoice, TTS_WHERE, voiceAllowed, voiceFailure } from "./voice";
import { VoiceNotice } from "./VoiceNotice";
import "./voice.css";

export const SpeakIcon = () => (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z" />
    <path d="M15.5 9a4 4 0 0 1 0 6" />
    <path d="M18 6.5a7.5 7.5 0 0 1 0 11" />
  </svg>
);
export const SquareIcon = () => (
  <svg width="11" height="11" viewBox="0 0 24 24" aria-hidden="true">
    <rect x="5" y="5" width="14" height="14" rx="2.5" fill="currentColor" />
  </svg>
);

type Fail = { head: Key; said: string };

/** The read-aloud control of one answer: its button (for inside the bubble, beside copy) and its line (under it). With
 *  no `bot` (a SESSIONS chat) there is neither. */
export function useReadAloud(bot: Bot | undefined, text: string): { button: ReactNode; note: ReactNode } {
  // the actions only, read on a press: a bubble does not subscribe to the store (it stays memoized while tokens stream)
  const s = getStore().actions;
  const remote = useServerMode().mode === "remote";
  const [play, setPlay] = useState<SpeechState | null>(null);
  const [ask, setAsk] = useState<VoiceInfo | null>(null);
  const [fail, setFail] = useState<Fail | null>(null);
  const run = useRef<{ stop(): void } | null>(null);
  const btn = useRef<HTMLButtonElement>(null);
  // the composer's microphone runs in this chat: what plays would be recorded with the voice, so read aloud waits
  const recording = useMicBusy();
  // the bubble goes (a chat switch, the chat closing): what it plays stops with it
  useEffect(() => () => run.current?.stop(), []);
  if (!bot) return { button: null, note: null };
  const off: Key | null = bot.host ? "voice.offPeer" : remote ? "voice.offRemote" : recording ? "voice.offRecording" : null;
  /** The notice closed: the keyboard goes back to the button that opened it (Stop, after Continue). */
  const back = () => requestAnimationFrame(() => btn.current?.focus());

  const start = () => {
    setFail(null);
    setAsk(null);
    const r = readAloud(text, (words, part) => s.voiceSpeak(bot.name, words, part), setPlay);
    run.current = r;
    r.done
      .catch((e: unknown) => {
        if (run.current !== r) return;
        const bridge = typeof e === "object" && e !== null && "code" in e;
        setFail(bridge ? voiceFailure(e) : { head: "voice.errPlayback", said: "" });
      })
      .finally(() => {
        if (run.current === r) run.current = null;
        setPlay(null);
      });
  };
  const press = () => {
    if (off) return setFail({ head: off, said: "" });
    if (run.current) return run.current.stop();
    if (ask) return setAsk(null);
    setFail(null);
    if (voiceAllowed("read", bot.name)) return start();
    voiceInfoOnce(bot.name, s.voiceInfo).then(
      (info) => (info.supported ? setAsk(info) : setFail({ head: "voice.errUnsupported", said: info.line })),
      (e: unknown) => setFail(voiceFailure(e)),
    );
  };
  const busy = !!play;
  const label = off ? t(off) : busy ? t("voice.stopReading") : t("voice.readAloud");
  const button = (
    <button
      ref={btn}
      type="button"
      className={`copy-btn msg-speak${busy ? " on" : ""}`}
      aria-label={label}
      title={label}
      aria-pressed={busy}
      aria-disabled={off ? true : undefined}
      onClick={(e) => {
        e.stopPropagation();
        press();
      }}
      data-testid="read-aloud"
      data-state={play?.kind ?? (off ? "off" : "idle")}
    >
      {busy ? <SquareIcon /> : <SpeakIcon />}
    </button>
  );
  const note = ask ? (
    <VoiceNotice
      testId="read-notice"
      title={t("voice.readTitle")}
      body={t("voice.readBody", { bot: bot.display_name })}
      where={t(TTS_WHERE[ask.tts.where], { provider: ask.tts.provider })}
      onContinue={() => {
        allowVoice("read", bot.name);
        start();
        back();
      }}
      onCancel={() => {
        setAsk(null);
        back();
      }}
    />
  ) : fail ? (
    <div className="voice-line err" role="alert" data-testid="read-error">
      <b>{t(fail.head)}</b>
      {fail.said && <span className="voice-said">{fail.said}</span>}
    </div>
  ) : play ? (
    <div className="voice-line" role="status" data-testid="read-status">
      {play.kind === "loading"
        ? t("voice.preparing")
        : play.parts > 1
          ? t("voice.playingPart", { part: play.part + 1, parts: play.parts })
          : t("voice.playing")}
      {play.kind === "playing" && play.provider && <span className="voice-by">{t("voice.readBy", { provider: play.provider })}</span>}
      {play.kind === "playing" && play.cut && <span className="voice-by">{t("voice.cut", { n: play.textMax.toLocaleString() })}</span>}
    </div>
  ) : null;
  return { button, note };
}
