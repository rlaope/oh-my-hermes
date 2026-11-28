// Voice (BOUNDARY rule 54), the page's pure parts: which recording type to ask for, where a transcript goes in the
// draft, the first-use memory, and what each failure says. The recording is made in this window; its bytes go to the
// bridge only, which sends them to the bot's own Hermes. Nothing here records, plays or keeps audio.
import type { Key } from "../../i18n";
import type { VoiceWhere } from "../../lib/protocol";

/** MediaRecorder types in the order Hermes' own Desktop tries them (use-mic-recorder.ts); Hermes takes each. */
export const RECORD_TYPES = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus", "audio/ogg", "audio/wav"] as const;

/** A recording stops by itself after 3 minutes or 20 MB, whichever comes first: Opus or AAC speech is well under a
 *  megabyte a minute, but a webview that records uncompressed WAV writes about 11 MB a minute, and Hermes takes at
 *  most 25 MB. Three minutes is a long spoken message and keeps a local transcription short. */
export const RECORD_MAX_MS = 3 * 60_000;
export const RECORD_MAX_BYTES = 20 * 1024 * 1024;

/** The first type the webview records, or "" for its own default (Hermes reads the type the recording reports). */
export function pickMime(supported: (type: string) => boolean): string {
  for (const type of RECORD_TYPES) {
    try {
      if (supported(type)) return type;
    } catch {
      /* a webview that throws on the question supports none of them */
    }
  }
  return "";
}

/** Whether this window can record at all: `getUserMedia` and `MediaRecorder` both present (a Linux WebKitGTK build
 *  without media capture has neither, nor does a page that is not a secure context). */
export function canRecord(w: { navigator?: Navigator; MediaRecorder?: unknown } = globalThis as never): boolean {
  return typeof w.navigator?.mediaDevices?.getUserMedia === "function" && typeof w.MediaRecorder === "function";
}

const CJK = /[぀-ヿ㐀-鿿豈-﫿＀-￯]/;
const NO_SPACE_BEFORE = /[.,!?;:)\]}、。，！？；：）」』]/;

/** Whether a space goes between `a` (the last character before) and `b` (the first after): not beside a space or a
 *  line break, not between two CJK characters (Japanese and Chinese write none), not before closing punctuation. */
function spaced(a: string | undefined, b: string | undefined): boolean {
  if (!a || !b || /\s/.test(a) || /\s/.test(b)) return false;
  if (CJK.test(a) && CJK.test(b)) return false;
  return !NO_SPACE_BEFORE.test(b);
}

/** The transcript put where the caret is (replacing a selection), with a space on either side where the words would
 *  otherwise run together. `insert` is what goes in at `start` (for the textarea's own insert, so undo takes it back);
 *  `text` the draft after, and `caret` where the caret goes. */
export function insertTranscript(text: string, start: number, end: number, words: string): { insert: string; text: string; caret: number } {
  const s = Math.max(0, Math.min(start, text.length));
  const e = Math.max(s, Math.min(end, text.length));
  const w = words.trim();
  const insert = (spaced(text[s - 1], w[0]) ? " " : "") + w + (spaced(w[w.length - 1], text[e]) ? " " : "");
  return { insert, text: text.slice(0, s) + insert + text.slice(e), caret: s + insert.length };
}

/** `m:ss` of a running recording. */
export function clock(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

// The first-use notice, once per bot and use on this computer: a list of bots per use in one localStorage entry.
export const VOICE_OK_KEY = "omher.voice.ok";
export type VoiceUse = "mic" | "read";
type Store = Pick<Storage, "getItem" | "setItem">;
const storage = (): Store | null => {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
};

function readOk(store: Store | null): Record<VoiceUse, string[]> {
  try {
    const raw = JSON.parse(store?.getItem(VOICE_OK_KEY) ?? "{}") as Record<string, unknown>;
    const list = (v: unknown) => (Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : []);
    return { mic: list(raw?.mic), read: list(raw?.read) };
  } catch {
    return { mic: [], read: [] };
  }
}

/** The person has already said Continue to this use for this bot on this computer. */
export function voiceAllowed(use: VoiceUse, bot: string, store: Store | null = storage()): boolean {
  return readOk(store)[use].includes(bot);
}

/** Remember the person's Continue (a storage that refuses keeps nothing: the notice shows again next time). */
export function allowVoice(use: VoiceUse, bot: string, store: Store | null = storage()): void {
  const ok = readOk(store);
  if (ok[use].includes(bot)) return;
  ok[use] = [...ok[use], bot];
  try {
    store?.setItem(VOICE_OK_KEY, JSON.stringify(ok));
  } catch {
    /* no storage */
  }
}

/** What the first-use notice says about where the recording goes, from what the bot's config names. */
export const STT_WHERE: Record<VoiceWhere, Key> = {
  local: "voice.sttLocal",
  auto: "voice.sttAuto",
  online: "voice.sttOnline",
  off: "voice.sttOff",
  other: "voice.sttOther",
  edge: "voice.sttOther",
};
/** And about where an answer's text goes. */
export const TTS_WHERE: Record<VoiceWhere, Key> = {
  edge: "voice.ttsEdge",
  local: "voice.ttsLocal",
  online: "voice.ttsOnline",
  other: "voice.ttsOther",
  auto: "voice.ttsOther",
  off: "voice.ttsOther",
};

/** The headline over Hermes' own words, by the bridge's code. */
const HEADS: Record<string, Key> = {
  voice_not_ready: "voice.errNotReady",
  voice_no_provider: "voice.errNoProvider",
  voice_disabled: "voice.errDisabled",
  voice_too_large: "voice.errTooLarge",
  voice_timeout: "voice.errTimeout",
  voice_unsupported: "voice.errUnsupported",
  voice_https: "voice.errHttps",
  voice_refused: "voice.errRefused",
  voice_empty: "voice.errEmpty",
  bot_offline: "voice.errOffline",
  remote_only: "voice.offRemote",
  remote_bot: "voice.offPeer",
  disconnected: "voice.errBridge",
};

/** A bridge refusal as a headline key and Hermes' (or the bridge's) own words under it. */
export function voiceFailure(e: unknown): { head: Key; said: string } {
  const o = (typeof e === "object" && e ? e : {}) as { code?: unknown; message?: unknown };
  const code = typeof o.code === "string" ? o.code : "";
  return { head: HEADS[code] ?? "voice.errFailed", said: typeof o.message === "string" ? o.message : "" };
}

export type Os = "mac" | "windows" | "linux";
export function osOf(ua: string = typeof navigator === "undefined" ? "" : navigator.userAgent): Os {
  if (/Mac OS X|Macintosh/.test(ua)) return "mac";
  if (/Windows/.test(ua)) return "windows";
  return "linux";
}

/** A microphone that did not open, by the DOMException's name, as Hermes' own Desktop tells them apart (micError). */
export function micFailure(e: unknown, os: Os = osOf()): { head: Key; hint?: Key } {
  const name = typeof e === "object" && e && "name" in e ? String((e as { name: unknown }).name) : "";
  if (name === "NotAllowedError" || name === "SecurityError")
    return { head: "voice.micDenied", hint: os === "mac" ? "voice.micAllowMac" : os === "windows" ? "voice.micAllowWindows" : "voice.micAllowLinux" };
  if (name === "NotFoundError" || name === "DevicesNotFoundError" || name === "OverconstrainedError") return { head: "voice.micNone" };
  if (name === "NotReadableError" || name === "TrackStartError") return { head: "voice.micBusy" };
  if (name === "NotSupportedError") return { head: "voice.noApi" };
  return { head: "voice.micFailed" };
}

/** A Blob's bytes as base64, for the bridge's frame. */
export function blobBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onerror = () => reject(r.error ?? new Error("read failed"));
    r.onload = () => {
      const url = String(r.result ?? "");
      resolve(url.slice(url.indexOf(",") + 1));
    };
    r.readAsDataURL(blob);
  });
}
