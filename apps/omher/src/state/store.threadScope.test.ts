// With a thread open, "the chat on screen" is that thread: its answers draw no unread, sound or notification, and the
// bot's main chat (now off screen) counts again. A thread's or folder chat's unread key (`fold:<bot>:<id>`, summed
// into the Dock count) clears when that chat is opened or goes away, so the Dock count comes back down.
import { afterEach, describe, expect, it, vi } from "vitest";
import { initialState, reduce, selectUnreadTotal, setSessionKeyLookup, soundOf, type Action, type AppState } from "./store";
import { threadKey } from "../threads/types";
import type { SoundBoard } from "../lib/sounds";
import type { BridgeEvent } from "../lib/protocol";

const T0 = 1_800_000_000_000;
const ev = (s: AppState, e: BridgeEvent) => reduce(s, { type: "event", ev: e, now: T0 } as Action);
const say = (bot: string, id: string, session?: string): BridgeEvent =>
  ({ event: "message", bot, id, text: `answer ${id}`, ...(session ? { session } : {}) }) as BridgeEvent;
const open = (bot: string, thread: string | null) => (s: AppState) => reduce(s, { type: "ui.thread", bot, thread });
const TH = "th-1";

afterEach(() => {
  setSessionKeyLookup(() => null);
  vi.unstubAllGlobals();
});

describe("unread follows the chat on screen", () => {
  it("an open thread's answer is not unread; the bot's main chat answer is", () => {
    let s = reduce(initialState(), { type: "select", bot: "kami" });
    s = open("kami", TH)(s);
    s = ev(s, say("kami", "t1", TH));
    expect(s.unread[threadKey("kami", TH)] ?? 0).toBe(0);
    s = ev(s, say("kami", "m1"));
    expect(s.unread.kami).toBe(1);
    // back on the main chat: read
    s = open("kami", null)(s);
    expect(s.unread.kami).toBe(0);
    expect(selectUnreadTotal(s)).toBe(0);
  });

  it("a thread's unread clears when the thread is opened, so the Dock count comes back down", () => {
    let s = reduce(initialState(), { type: "select", bot: "kami" });
    s = ev(s, say("kami", "t1", TH));
    s = ev(s, say("kami", "t2", TH));
    expect(selectUnreadTotal(s)).toBe(2);
    s = open("kami", TH)(s);
    expect(selectUnreadTotal(s)).toBe(0);
  });

  it("a removed thread's unread goes with it", () => {
    let s = reduce(initialState(), { type: "select", bot: "kami" });
    s = reduce(s, { type: "threads", bot: "kami", threads: [{ thread: TH, title: "t", cwd: "", started_at: 0, running: false, needs: false, message_count: 0, last: 0 }] } as Action);
    s = ev(s, say("kami", "t1", TH));
    expect(selectUnreadTotal(s)).toBe(1);
    s = reduce(s, { type: "thread.gone", bot: "kami", thread: TH });
    expect(selectUnreadTotal(s)).toBe(0);
    s = ev(s, say("kami", "t2", "th-2"));
    s = reduce(s, { type: "chat.forget", bot: threadKey("kami", "th-2") });
    expect(selectUnreadTotal(s)).toBe(0);
  });

  it("a folder chat counts while elsewhere, clears when opened, and counts nothing while on screen", () => {
    setSessionKeyLookup((id) => (id === "s-folder" ? "fold:kami:sess-9" : null));
    let s = reduce(initialState(), { type: "select", bot: "kami" });
    s = ev(s, say("kami", "f1", "sess-9"));
    expect(s.unread["fold:kami:sess-9"]).toBe(1);
    s = reduce(s, { type: "ui.session", id: "s-folder" });
    expect(selectUnreadTotal(s)).toBe(0);
    s = ev(s, say("kami", "f2", "sess-9"));
    expect(selectUnreadTotal(s)).toBe(0);
  });
});

describe("sounds and notifications follow the chat on screen", () => {
  const pops = (s: AppState, e: BridgeEvent) => {
    const offered: string[] = [];
    const board = { offer: (sound: string) => offered.push(sound), opened: () => undefined, unsettle: () => undefined } as unknown as SoundBoard;
    soundOf({ type: "event", ev: e, now: T0 } as Action, s, board);
    return offered;
  };

  it("with a thread open: its own finished turn is watched (quiet), the bot's main chat is not", () => {
    vi.stubGlobal("document", { visibilityState: "visible", hasFocus: () => true });
    let s = reduce(initialState(), { type: "select", bot: "kami" });
    s = open("kami", TH)(s);
    expect(pops(s, { event: "turn.end", bot: "kami", session: TH, outcome: "done" } as BridgeEvent)).toEqual([]);
    expect(pops(s, { event: "turn.end", bot: "kami", outcome: "done" } as BridgeEvent)).toEqual(["pop"]);
    // on the main chat again: the other way round
    s = open("kami", null)(s);
    expect(pops(s, { event: "turn.end", bot: "kami", outcome: "done" } as BridgeEvent)).toEqual([]);
    expect(pops(s, { event: "turn.end", bot: "kami", session: TH, outcome: "done" } as BridgeEvent)).toEqual(["pop"]);
  });
});
