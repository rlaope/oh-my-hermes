// Read aloud (BOUNDARY rule 54): an answer's parts, spoken by the bot's own Hermes, played in this window one after
// another, one answer at a time. Starting another, Stop, a chat switch or an unmount ends what plays and asks for no
// later part; a part already asked for ahead is still made by Hermes and dropped when it arrives. The audio lives in
// an object URL only while its part plays.
import { useSyncExternalStore } from "react";
import type { VoiceInfo, VoiceSpeech } from "../../lib/protocol";

/** Hermes' own Desktop gives up on audio that neither plays nor fails for this long (voice-playback.ts). */
const STALL_MS = 15_000;

type Playing = { stop(): void };
let current: Playing | null = null;

/** End whatever answer is being read (no-op when none). */
export function stopSpeech(): void {
  const p = current;
  current = null;
  p?.stop();
}

function base64Blob(b64: string, mime: string): Blob {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i += 1) bytes[i] = bin.charCodeAt(i);
  return new Blob([bytes], { type: mime });
}

/** Play one part to its end; resolves early when `stopped` turns true (the element is paused and let go). */
function playPart(r: VoiceSpeech, live: { stopped: boolean; halt?: () => void }): Promise<void> {
  const url = URL.createObjectURL(base64Blob(r.data_base64 ?? "", r.mime ?? "audio/mpeg"));
  const audio = new Audio(url);
  return new Promise<void>((resolve, reject) => {
    let stall: ReturnType<typeof setTimeout> | null = null;
    const done = (err?: Error) => {
      if (stall) clearTimeout(stall);
      audio.removeEventListener("ended", onEnded);
      audio.removeEventListener("error", onError);
      audio.removeEventListener("timeupdate", arm);
      live.halt = undefined;
      audio.pause();
      audio.removeAttribute("src");
      URL.revokeObjectURL(url);
      if (err) reject(err);
      else resolve();
    };
    const arm = () => {
      if (stall) clearTimeout(stall);
      stall = setTimeout(() => done(new Error("playback stalled")), STALL_MS);
    };
    const onEnded = () => done();
    const onError = () => done(new Error("playback failed"));
    live.halt = () => done();
    audio.addEventListener("ended", onEnded);
    audio.addEventListener("error", onError);
    audio.addEventListener("timeupdate", arm);
    arm();
    audio.play().catch(() => done(new Error("playback failed")));
  });
}

export type SpeechState = { kind: "loading" } | { kind: "playing"; part: number; parts: number; cut: boolean; textMax: number; provider: string };

/** Read `text` aloud through `speak` (the bridge's `voice.speak` for one bot), part after part, fetching the next
 *  while one plays. Any answer already being read stops first. Resolves when the last part ends or it is stopped;
 *  rejects with the bridge's refusal or a playback failure. */
export function readAloud(
  text: string,
  speak: (text: string, part: number) => Promise<VoiceSpeech>,
  onState: (s: SpeechState) => void,
): { stop(): void; done: Promise<void> } {
  stopSpeech();
  const live: { stopped: boolean; halt?: () => void } = { stopped: false };
  const me: Playing = {
    stop() {
      live.stopped = true;
      live.halt?.();
    },
  };
  current = me;
  const ask = (part: number) => {
    const p = speak(text, part);
    p.catch(() => undefined); // a part fetched ahead and then not wanted (Stop) fails quietly
    return p;
  };
  const done = (async () => {
    onState({ kind: "loading" });
    let next = ask(0);
    for (let part = 0; ; part += 1) {
      const r = await next;
      if (live.stopped) return;
      if (part + 1 < r.parts) next = ask(part + 1);
      if (!r.empty && r.data_base64) {
        onState({ kind: "playing", part, parts: r.parts, cut: r.cut, textMax: r.text_max, provider: r.provider ?? "" });
        await playPart(r, live);
      }
      if (live.stopped || part + 1 >= r.parts) return;
    }
  })().finally(() => {
    if (current === me) current = null;
  });
  return { stop: () => me.stop(), done };
}

// The composer's microphone is opening, recording or waiting for its transcript. Only one composer is mounted at a
// time (the main column shows one chat), so this is that chat's: while it holds, read aloud is off, since what
// plays would be recorded with the voice; starting a recording stops what plays (stopSpeech).
let micBusy = false;
const micSubs = new Set<() => void>();
export function setMicBusy(on: boolean): void {
  if (micBusy === on) return;
  micBusy = on;
  for (const f of [...micSubs]) f();
}
export function useMicBusy(): boolean {
  return useSyncExternalStore(
    (f) => {
      micSubs.add(f);
      return () => micSubs.delete(f);
    },
    () => micBusy,
    () => micBusy,
  );
}

/** `voice.info` per bot, asked once per window (a failed ask is asked again next time). */
const infos = new Map<string, Promise<VoiceInfo>>();
export function voiceInfoOnce(bot: string, ask: (bot: string) => Promise<VoiceInfo>): Promise<VoiceInfo> {
  let p = infos.get(bot);
  if (!p) {
    p = ask(bot);
    infos.set(bot, p);
    p.catch(() => infos.delete(bot));
  }
  return p;
}
