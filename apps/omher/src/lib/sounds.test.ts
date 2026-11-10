import { describe, expect, it } from "vitest";
import { FLOOR, GAP_MS, RECIPES, SETTLE_MS, SoundBoard, TYPING_MS, play, soundFor, typedKey, type AudioLike, type Sound, type Tone } from "./sounds";
import { createStore, selectAsks, soundOf, type BridgeLike } from "../state/store";
import type { BridgeStatus } from "./bridge";
import type { BridgeEvent } from "./protocol";

// ---- an AudioContext stub that records what would play ------------------------------------------

function fakeAudio(state: AudioContextState = "running") {
  const log = { made: 0, started: [] as number[], resumed: 0, ramps: [] as [string, number, number][], stops: [] as number[] };
  let resolveResume: (() => void) | null = null;
  const param = () => ({
    setValueAtTime: (v: number, t: number) => log.ramps.push(["set", v, t]),
    linearRampToValueAtTime: (v: number, t: number) => log.ramps.push(["lin", v, t]),
    exponentialRampToValueAtTime: (v: number, t: number) => log.ramps.push(["exp", v, t]),
  });
  const ctx = {
    state,
    currentTime: 0,
    destination: {},
    createOscillator: () => ({
      type: "sine",
      frequency: param(),
      connect: () => undefined,
      start: (t: number) => log.started.push(t),
      stop: (t: number) => log.stops.push(t),
    }),
    createGain: () => ({ gain: param(), connect: () => undefined }),
    resume: () => {
      log.resumed += 1;
      return new Promise<void>((r) => (resolveResume = r));
    },
  };
  const factory = () => {
    log.made += 1;
    return ctx as unknown as AudioLike;
  };
  return { log, ctx, factory, resolveResume: () => resolveResume?.() };
}

function board(opts: { on?: boolean; state?: AudioContextState } = {}) {
  const audio = fakeAudio(opts.state);
  const clock = { t: 1_000_000 };
  let on = opts.on ?? true;
  let gesture: (() => void) | null = null;
  const b = new SoundBoard({
    now: () => clock.t,
    enabled: () => on,
    audio: audio.factory,
    onGesture: (fn) => (gesture = fn),
  });
  return {
    b,
    audio,
    clock,
    turn: (v: boolean) => (on = v),
    gesture: () => gesture?.(),
    hasGesture: () => gesture !== null,
    /** Settle the board and let the quiet window after it pass. */
    ready() {
      b.settle();
      clock.t += SETTLE_MS;
    },
  };
}

// ---- recipes ----------------------------------------------------------------------------------

/** The gain play() ramps to at `ms` into the sound: linear up to the peak, exponential down to FLOOR. */
function level(n: Tone, ms: number): number {
  const t = ms - n.at;
  if (t < 0 || t > n.dur) return 0;
  if (t <= n.attack) return FLOOR + (n.gain - FLOOR) * (t / n.attack);
  return n.gain * Math.pow(FLOOR / n.gain, (t - n.attack) / (n.dur - n.attack));
}

describe("sound recipes", () => {
  const all = Object.entries(RECIPES) as [Sound, Tone[]][];

  it("are exactly send, pop, chime and error", () => {
    expect(Object.keys(RECIPES).sort()).toEqual(["chime", "error", "pop", "send"]);
  });

  it("each lasts 60-250 ms, with a few-ms attack", () => {
    for (const [name, tones] of all) {
      const ms = Math.max(...tones.map((n) => n.at + n.dur));
      expect(ms, name).toBeGreaterThanOrEqual(60);
      expect(ms, name).toBeLessThanOrEqual(250);
      for (const n of tones) expect(n.attack, name).toBeGreaterThan(0), expect(n.attack, name).toBeLessThanOrEqual(10);
    }
  });

  it("uses sine and triangle only", () => {
    for (const [, tones] of all) for (const n of tones) expect(["sine", "triangle"]).toContain(n.wave);
  });

  it("peaks at or under 0.126 (-18 dBFS), summing every tone in phase", () => {
    for (const [name, tones] of all) {
      let peak = 0;
      for (let ms = 0; ms <= 260; ms += 0.1) peak = Math.max(peak, tones.reduce((s, n) => s + level(n, ms), 0));
      expect(peak, name).toBeLessThanOrEqual(0.126 * 1.01);
      expect(peak, name).toBeGreaterThan(0.05);
    }
  });

  it("play() ramps each tone back to the floor before it stops", () => {
    const a = fakeAudio();
    play(RECIPES.chime, a.ctx as unknown as AudioLike);
    expect(a.log.started).toHaveLength(2);
    const exps = a.log.ramps.filter((r) => r[0] === "exp");
    expect(exps.map((r) => r[1])).toEqual([FLOOR, FLOOR]);
    exps.forEach((r, i) => expect(a.log.stops[i]).toBeGreaterThan(r[2]));
  });
});

// ---- which sound an event means -------------------------------------------------------------

describe("soundFor", () => {
  const ctx = (watching = false, open = true) => ({ watching: () => watching, open: () => open });
  const bot = "kami";

  it("maps the four", () => {
    expect(soundFor({ event: "approval.request", bot, request_id: "a1", title: "", command: "ls", choices: [] }, ctx())).toEqual({ sound: "chime", ask: "a1" });
    expect(soundFor({ event: "clarify.request", bot, request_id: "c1", question: "?" }, ctx())).toEqual({ sound: "chime", ask: "c1" });
    expect(soundFor({ event: "turn.end", bot, outcome: "error", error: "boom" }, ctx(true))).toEqual({ sound: "error" });
    expect(soundFor({ event: "turn.end", bot, outcome: "done" }, ctx(false))).toEqual({ sound: "pop" });
  });

  it("is quiet for a reply you are watching, an interrupted turn, a closed ask and everything else", () => {
    expect(soundFor({ event: "turn.end", bot, outcome: "done" }, ctx(true))).toBeNull();
    expect(soundFor({ event: "turn.end", bot, outcome: "interrupted" }, ctx(false))).toBeNull();
    expect(soundFor({ event: "clarify.request", bot, request_id: "c1", question: "?" }, ctx(false, false))).toBeNull();
    expect(soundFor({ event: "message", bot, id: "m1", text: "hi" }, ctx())).toBeNull();
    expect(soundFor({ event: "turn.start", bot }, ctx())).toBeNull();
  });
});

describe("typedKey", () => {
  const key = (key: string, tagName = "TEXTAREA", extra: Partial<KeyboardEvent> = {}) =>
    typedKey({ key, metaKey: false, ctrlKey: false, isComposing: false, target: { tagName } as unknown as EventTarget, ...extra });

  it("counts text keys in a text field, including IME input", () => {
    expect(key("a")).toBe(true);
    expect(key("Backspace", "INPUT")).toBe(true);
    expect(key("Process")).toBe(true);
    expect(key("ㅎ", "TEXTAREA", { isComposing: true })).toBe(true);
  });

  it("ignores shortcuts, lone modifiers and keys outside a text field", () => {
    expect(key("j", "TEXTAREA", { metaKey: true })).toBe(false);
    expect(key("Shift")).toBe(false);
    expect(key("a", "BUTTON")).toBe(false);
  });
});

// ---- the board's rules ----------------------------------------------------------------------

describe("SoundBoard", () => {
  it("off: plays nothing and never makes an AudioContext", () => {
    const x = board({ on: false });
    x.ready();
    for (const s of ["send", "pop", "chime", "error"] as Sound[]) {
      expect(x.b.offer(s, s === "chime" ? { chat: "kami", id: `a-${s}` } : undefined)).toBe(false);
      x.clock.t += GAP_MS;
    }
    expect(x.b.preview()).toBe(false);
    expect(x.audio.log.made).toBe(0);
    expect(x.audio.log.resumed).toBe(0);
  });

  it("makes the context once, on the first sound that plays, and starts its oscillators", () => {
    const x = board();
    x.ready();
    expect(x.audio.log.made).toBe(0);
    expect(x.b.offer("pop")).toBe(true);
    x.clock.t += GAP_MS;
    expect(x.b.offer("error")).toBe(true);
    expect(x.audio.log.made).toBe(1);
    expect(x.audio.log.started).toHaveLength(RECIPES.pop.length + RECIPES.error.length);
  });

  it("is silent while the first state loads and just after; the send tick is the person's own and plays", () => {
    const x = board();
    expect(x.b.offer("pop")).toBe(false);
    expect(x.b.offer("chime", { chat: "kami", id: "a1" })).toBe(false);
    x.b.settle();
    x.clock.t += SETTLE_MS - 1;
    expect(x.b.offer("error")).toBe(false);
    expect(x.b.offer("send")).toBe(true);
    x.clock.t += GAP_MS;
    expect(x.b.offer("error")).toBe(true);
  });

  it("drops a second sound inside 1.5 s and plays one after", () => {
    const x = board();
    x.ready();
    expect(x.b.offer("pop")).toBe(true);
    x.clock.t += GAP_MS - 1;
    expect(x.b.offer("error")).toBe(false);
    expect(x.b.offer("send")).toBe(false);
    x.clock.t += 1;
    expect(x.b.offer("error")).toBe(true);
    expect(x.audio.log.started).toHaveLength(RECIPES.pop.length + RECIPES.error.length);
  });

  it("typing holds the pop, the chime and the error, not the send tick", () => {
    const x = board();
    x.ready();
    x.b.typed();
    x.clock.t += TYPING_MS - 1;
    expect(x.b.offer("pop")).toBe(false);
    expect(x.b.offer("chime", { chat: "kami", id: "a1" })).toBe(false);
    expect(x.b.offer("error")).toBe(false);
    expect(x.b.offer("send")).toBe(true);
    x.clock.t += GAP_MS;
    expect(x.b.offer("error")).toBe(true);
  });

  it("chimes once per ask: the same id again (a replay, a reconnect, a re-render) stays silent", () => {
    const x = board();
    x.ready();
    expect(x.b.offer("chime", { chat: "kami", id: "a1" })).toBe(true);
    x.clock.t += GAP_MS;
    expect(x.b.offer("chime", { chat: "kami", id: "a1" })).toBe(false);
    expect(x.b.offer("chime", { chat: "friren", id: "a1" })).toBe(true);
  });

  it("an ask dropped once (typing, first load) never sounds later", () => {
    const x = board();
    expect(x.b.offer("chime", { chat: "kami", id: "a1" })).toBe(false);
    x.ready();
    expect(x.b.offer("chime", { chat: "kami", id: "a1" })).toBe(false);
  });

  it("asks a chat replays right after it (re)loads are not new", () => {
    const x = board();
    x.ready();
    x.b.opened("friren");
    expect(x.b.offer("chime", { chat: "friren", id: "old" })).toBe(false);
    expect(x.b.offer("chime", { chat: "kami", id: "new" })).toBe(true);
    x.clock.t += SETTLE_MS + GAP_MS;
    expect(x.b.offer("chime", { chat: "friren", id: "later" })).toBe(true);
  });

  it("a dropped connection is quiet until the re-read settles", () => {
    const x = board();
    x.ready();
    x.b.unsettle();
    x.clock.t += GAP_MS;
    expect(x.b.offer("error")).toBe(false);
    x.ready();
    expect(x.b.offer("error")).toBe(true);
  });

  it("preview plays the chime without waiting for the first load", () => {
    const x = board();
    expect(x.b.preview()).toBe(true);
    expect(x.audio.log.started).toHaveLength(RECIPES.chime.length);
  });

  it("a context the browser holds is resumed on the next gesture, and the sound is dropped", async () => {
    const x = board({ state: "suspended" });
    x.ready();
    expect(x.b.offer("pop")).toBe(false);
    expect(x.hasGesture()).toBe(true);
    // it started late: still dropped, never queued
    x.clock.t += 500;
    x.audio.resolveResume();
    await Promise.resolve();
    expect(x.audio.log.started).toHaveLength(0);
    const before = x.audio.log.resumed;
    x.gesture();
    expect(x.audio.log.resumed).toBe(before + 1);
    (x.audio.ctx as { state: string }).state = "running";
    x.clock.t += GAP_MS;
    expect(x.b.offer("error")).toBe(true);
  });

  it("a context that starts at once still plays", async () => {
    const x = board({ state: "suspended" });
    x.ready();
    x.b.offer("pop");
    x.audio.resolveResume();
    await Promise.resolve();
    expect(x.audio.log.started).toHaveLength(RECIPES.pop.length);
  });

  it("switched off before the gesture: the context is not resumed", () => {
    const x = board({ state: "suspended" });
    x.ready();
    x.b.offer("pop");
    const before = x.audio.log.resumed;
    x.turn(false);
    x.gesture();
    expect(x.audio.log.resumed).toBe(before);
  });
});

// ---- through the store: first load, replays, reconnects, SESSIONS chats ----------------------------

function liveStore() {
  let anyH: ((ev: BridgeEvent) => void) | null = null;
  let statusH: ((s: BridgeStatus) => void) | null = null;
  const replay: BridgeEvent[] = [];
  /** Events that arrive while the app is still loading its first state. */
  const loading: BridgeEvent[] = [];
  const bridge: BridgeLike = {
    connect: async () => statusH?.("open"),
    onAny: (h) => ((anyH = h), () => {}),
    onStatus: (h) => ((statusH = h), () => {}),
    request: (async (op: string) => {
      switch (op) {
        case "hello":
          return { bridge: "mock", version: "0.1.0", hermes: { home: "/h" } };
        case "bots.list":
          loading.forEach((ev) => anyH?.(ev));
          return { bots: ["kami", "friren"].map((name) => ({ name, display_name: name, is_default: false, model: "m", provider: "p", description: "", status: "online", running: false })) };
        case "chat.open":
          // like the bridge: the asks still waiting follow the reply
          setTimeout(() => replay.forEach((ev) => anyH?.(ev)), 0);
          return { session_id: "s", messages: [], running: true, model: "m", provider: "p", reasoning: "" };
        case "elsewhere.list":
          return { sessions: [] };
        case "routines.list":
          return { routines: [] };
        default:
          return {};
      }
    }) as BridgeLike["request"],
  };
  const x = board();
  const store = createStore(bridge, {
    now: () => x.clock.t,
    onAction: (a, s) => soundOf(a, s, x.b),
    onSettled: () => x.b.settle(),
  });
  const tick = () => new Promise((r) => setTimeout(r, 5));
  return { store, x, replay, loading, emit: (ev: BridgeEvent) => anyH!(ev), status: (s: BridgeStatus) => statusH!(s), tick };
}

const ask = (bot: string, id: string, session?: string): BridgeEvent => ({
  event: "approval.request",
  bot,
  request_id: id,
  title: "Run",
  command: "rm -rf build/",
  choices: ["once", "deny"],
  ...(session ? { session } : {}),
});

describe("sounds through the store", () => {
  it("first load (history and replayed asks) is silent; a new ask after it chimes, once", async () => {
    const l = liveStore();
    l.replay.push(ask("friren", "old"));
    l.loading.push({ event: "turn.end", bot: "kami", outcome: "error", error: "boom" }, { event: "turn.end", bot: "friren", outcome: "done" });
    await l.store.actions.init();
    await l.tick();
    l.x.clock.t += SETTLE_MS;
    expect(selectAsks(l.store.getState()).map((a) => a.item.request_id)).toEqual(["old"]);
    expect(l.x.audio.log.made).toBe(0);
    l.emit(ask("kami", "new"));
    expect(l.x.audio.log.started).toHaveLength(RECIPES.chime.length);
    // the same ask again, after a reconnect's re-read: silent
    l.x.clock.t += GAP_MS;
    l.replay.push(ask("kami", "new"));
    l.status("closed");
    l.status("open");
    await l.tick();
    await l.tick();
    l.x.clock.t += SETTLE_MS;
    l.emit(ask("kami", "new"));
    expect(l.x.audio.log.started).toHaveLength(RECIPES.chime.length);
  });

  it("an error ends a turn with the low note; your send ticks", async () => {
    const l = liveStore();
    await l.store.actions.init();
    await l.tick();
    l.x.clock.t += SETTLE_MS;
    l.emit({ event: "turn.end", bot: "kami", outcome: "error", error: "boom" });
    expect(l.x.audio.log.started).toHaveLength(RECIPES.error.length);
    l.x.clock.t += GAP_MS;
    await l.store.actions.send("hello");
    expect(l.x.audio.log.started).toHaveLength(RECIPES.error.length + RECIPES.send.length);
  });

  it("SESSIONS chats chime too: a folder chat's ask and an agent chat's ask", async () => {
    const l = liveStore();
    await l.store.actions.init();
    await l.tick();
    l.x.clock.t += SETTLE_MS;
    l.emit(ask("kami", "f1", "f-1"));
    expect(l.x.audio.log.started).toHaveLength(RECIPES.chime.length);
    l.x.clock.t += GAP_MS;
    l.store.dispatch({ type: "event", ev: ask("agent:s1", "x1"), now: l.x.clock.t });
    expect(l.x.audio.log.started).toHaveLength(2 * RECIPES.chime.length);
  });
});
