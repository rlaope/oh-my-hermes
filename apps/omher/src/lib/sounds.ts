// Four short sounds, synthesized with Web Audio (no audio files): a tick when you send, a two-note pop when a
// chat finishes out of sight, a rising chime when an approval or question arrives, and one low note when a turn
// ends with an error. Settings › General turns them off; while off, no AudioContext is made or resumed.
import type { BridgeEvent } from "./protocol";

export type Sound = "send" | "pop" | "chime" | "error";

/** One tone: starts `at` ms into the sound, rises to `gain` in `attack` ms, then decays to near silence at `at + dur`. */
export interface Tone {
  freq: number;
  wave: "sine" | "triangle";
  at: number;
  dur: number;
  attack: number;
  gain: number;
}

/** Peak gains stay at or under 0.126 (-18 dBFS); the tick is quieter, it is your own action. */
export const RECIPES: Record<Sound, Tone[]> = {
  // E6, one short triangle tick
  send: [{ freq: 1318.5, wave: "triangle", at: 0, dur: 60, attack: 2, gain: 0.07 }],
  // E6 then B5: a fourth down
  pop: [
    { freq: 1318.5, wave: "sine", at: 0, dur: 80, attack: 4, gain: 0.11 },
    { freq: 987.77, wave: "sine", at: 80, dur: 120, attack: 4, gain: 0.11 },
  ],
  // E5 then B5: a fifth up
  chime: [
    { freq: 659.25, wave: "sine", at: 0, dur: 120, attack: 5, gain: 0.1 },
    { freq: 987.77, wave: "sine", at: 100, dur: 150, attack: 5, gain: 0.125 },
  ],
  // A3, one low triangle note
  error: [{ freq: 220, wave: "triangle", at: 0, dur: 240, attack: 6, gain: 0.12 }],
};

/** Where every envelope starts and ends (-80 dBFS): an exponential ramp cannot reach 0, and stopping here never clicks. */
export const FLOOR = 0.0001;
/** At most one sound per this many ms; a sound inside the window is dropped, not queued. */
export const GAP_MS = 1500;
/** A key went into a text field this recently: the person is typing. */
export const TYPING_MS = 1000;
/** Quiet this long after the first state (or a chat's history) loads: what arrives then is a replay. */
export const SETTLE_MS = 1000;
/** A context that was not running plays only if it starts within this; otherwise the sound is dropped. */
const START_MS = 100;

export type AudioLike = Pick<AudioContext, "state" | "currentTime" | "destination" | "createOscillator" | "createGain" | "resume">;

/** Schedule `tones` on `ctx`, starting now. */
export function play(tones: Tone[], ctx: AudioLike): void {
  const t0 = ctx.currentTime + 0.005;
  for (const n of tones) {
    const start = t0 + n.at / 1000;
    const end = start + n.dur / 1000;
    const osc = ctx.createOscillator();
    const amp = ctx.createGain();
    osc.type = n.wave;
    osc.frequency.setValueAtTime(n.freq, start);
    amp.gain.setValueAtTime(FLOOR, start);
    amp.gain.linearRampToValueAtTime(n.gain, start + n.attack / 1000);
    amp.gain.exponentialRampToValueAtTime(FLOOR, end);
    osc.connect(amp);
    amp.connect(ctx.destination);
    osc.start(start);
    osc.stop(end + 0.005);
  }
}

/** The sound `ev` means, if any (`ev.bot` is the chat key). Pure: no globals. `ask` is the ask's request id. */
export function soundFor(
  ev: BridgeEvent,
  ctx: { watching: (chat: string) => boolean; open: (chat: string, requestId: string) => boolean },
): { sound: Sound; ask?: string } | null {
  switch (ev.event) {
    case "approval.request":
    case "clarify.request":
      return ctx.open(ev.bot, ev.request_id) ? { sound: "chime", ask: ev.request_id } : null;
    case "turn.end":
      if (ev.outcome === "error") return { sound: "error" };
      return ev.outcome === "done" && !ctx.watching(ev.bot) ? { sound: "pop" } : null;
    default:
      return null;
  }
}

export interface SoundDeps {
  now: () => number;
  enabled: () => boolean;
  /** Make the AudioContext (called once, on the first sound that plays). */
  audio: () => AudioLike | null;
  /** Run `fn` once on the person's next click or key. */
  onGesture: (fn: () => void) => void;
}

/** Decides whether a sound plays: switched on, the first state loaded, not typing, one per GAP_MS, once per ask. */
export class SoundBoard {
  private ctx: AudioLike | null = null;
  private settledAt: number | null = null;
  private openedAt = new Map<string, number>();
  private asked = new Set<string>();
  private last = -Infinity;
  private typedAt = -Infinity;
  private waking = false;

  constructor(private deps: SoundDeps) {}

  /** The first state (or a reconnect's re-read) has loaded: sounds may play SETTLE_MS from now. */
  settle(): void {
    this.settledAt = this.deps.now();
  }
  /** The connection dropped: quiet until the next settle(). */
  unsettle(): void {
    this.settledAt = null;
  }
  /** Chat `chat` (re)loaded its history: asks it replays right after are not new. */
  opened(chat: string): void {
    this.openedAt.set(chat, this.deps.now());
  }
  /** A key went into a text field. */
  typed(): void {
    this.typedAt = this.deps.now();
  }

  /** Play `sound` unless a rule drops it; an ask (`chat` + request id) sounds at most once, ever. */
  offer(sound: Sound, ask?: { chat: string; id: string }): boolean {
    const t = this.deps.now();
    if (ask) {
      const key = `${ask.chat}\n${ask.id}`;
      if (this.asked.has(key)) return false;
      this.asked.add(key);
      if (t - (this.openedAt.get(ask.chat) ?? -Infinity) < SETTLE_MS) return false;
    }
    // the send tick is the person's own action: only the switch and the gap hold it
    if (sound !== "send" && (this.settledAt === null || t - this.settledAt < SETTLE_MS || t - this.typedAt < TYPING_MS)) return false;
    return this.sound(sound, t);
  }

  /** Settings' Play button: the chime. */
  preview(): boolean {
    return this.sound("chime", this.deps.now());
  }

  private sound(s: Sound, t: number): boolean {
    if (!this.deps.enabled() || t - this.last < GAP_MS) return false;
    const ctx = (this.ctx ??= this.deps.audio());
    if (!ctx) return false;
    this.last = t;
    if (ctx.state === "running") {
      play(RECIPES[s], ctx);
      return true;
    }
    // A context made a moment ago may still be starting: play if it starts at once. One the browser holds until
    // a gesture is resumed on the next one, and this sound is dropped, never queued.
    ctx.resume().then(
      () => {
        if (this.deps.now() - t < START_MS && this.deps.enabled()) play(RECIPES[s], ctx);
      },
      () => undefined,
    );
    if (!this.waking) {
      this.waking = true;
      this.deps.onGesture(() => {
        this.waking = false;
        if (this.deps.enabled() && ctx.state !== "running") ctx.resume().catch(() => undefined);
      });
    }
    return false;
  }
}

// ---- the app's board ------------------------------------------------------------------------

/** "Sounds" (Settings › General). On unless turned off; saved on this computer. */
export function soundsEnabled(): boolean {
  try {
    return typeof localStorage === "undefined" || localStorage.getItem("omher.sounds") !== "off";
  } catch {
    return true;
  }
}

export function setSoundsEnabled(on: boolean): void {
  try {
    localStorage.setItem("omher.sounds", on ? "on" : "off");
  } catch {
    /* no storage */
  }
}

/** True for a key that puts text into a text field: not a shortcut, not a lone modifier. */
export function typedKey(e: Pick<KeyboardEvent, "key" | "metaKey" | "ctrlKey" | "isComposing" | "target">): boolean {
  const el = e.target as HTMLElement | null;
  const field = !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable === true);
  if (!field || e.metaKey || e.ctrlKey) return false;
  return e.isComposing || e.key.length === 1 || ["Backspace", "Delete", "Enter", "Process"].includes(e.key);
}

function browserAudio(): AudioLike | null {
  const w = window as unknown as { AudioContext?: typeof AudioContext; webkitAudioContext?: typeof AudioContext };
  const Ctor = w.AudioContext ?? w.webkitAudioContext;
  try {
    return Ctor ? new Ctor() : null;
  } catch {
    return null;
  }
}

function onNextGesture(fn: () => void): void {
  const go = () => {
    document.removeEventListener("pointerdown", go, true);
    document.removeEventListener("keydown", go, true);
    fn();
  };
  document.addEventListener("pointerdown", go, true);
  document.addEventListener("keydown", go, true);
}

let board: SoundBoard | null = null;

/** The app's one board; the first call starts watching for typing. */
export function appSounds(): SoundBoard {
  if (board) return board;
  const b = new SoundBoard({ now: Date.now, enabled: soundsEnabled, audio: browserAudio, onGesture: onNextGesture });
  if (typeof document !== "undefined") document.addEventListener("keydown", (e) => typedKey(e) && b.typed(), true);
  return (board = b);
}
