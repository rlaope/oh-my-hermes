// Finding, opening and switching sessions: the row menu's items, the sidebar search over sessions, continuing a
// conversation Claude Code or Codex keeps for a folder, the ⌘N / ⌘⇧] / ⌘⇧[ shortcuts and the asks count.
import { describe, expect, it } from "vitest";
import { MockHost, type MockCall, type PastChat } from "./host";
import { createSessions } from "./sessions";
import { ageOf, rowMenuItems, sessionMatches } from "./SessionsSection";
import { createStore, type BridgeLike } from "../state/store";
import { shortcutFor, stepSession } from "../app/shortcuts";
import { badgeCount } from "../app/badge";
import type { SessionRec } from "./agents";

function bridgeStub(): BridgeLike {
  return {
    connect: async () => undefined,
    onAny: () => () => {},
    onStatus: () => () => {},
    request: (async () => ({})) as BridgeLike["request"],
  };
}

function setup(past?: PastChat[]) {
  const g: Record<string, unknown> = { __omherMockAgents: ["claude", "codex", "omh"], ...(past ? { __omherPastChats: past } : {}) };
  const host = new MockHost(g);
  const store = createStore(bridgeStub());
  const storage = new Map<string, string>();
  (globalThis as { localStorage?: unknown }).localStorage = {
    getItem: (k: string) => storage.get(k) ?? null,
    setItem: (k: string, v: string) => void storage.set(k, v),
    removeItem: (k: string) => void storage.delete(k),
  };
  const ss = createSessions(host, () => store);
  const calls = () => (g.__omherSessionCalls as MockCall[] | undefined) ?? [];
  return { ss, store, calls, g, host };
}

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));
const live = (p: Partial<SessionRec>): SessionRec => ({ id: "s1", agent: "claude", cwd: "/w/web-app", startedAt: 1, status: "running", view: "chat", ...p });

describe("the row menu", () => {
  it("lists Rename, Reveal, Terminal, Copy id (only with an id), New session here, Close, in that order", () => {
    expect(rowMenuItems(live({ agentSession: "11111111-2222-4333-8444-555555555555" }))).toEqual(["rename", "reveal", "terminal", "copy", "here", "close"]);
    expect(rowMenuItems(live({}))).toEqual(["rename", "reveal", "terminal", "here", "close"]);
    // no folder (cannot happen for a started session, but never offer to open nothing)
    expect(rowMenuItems(live({ cwd: "" }))).toEqual(["rename", "here", "close"]);
  });

  it("New session here opens a draft with the row's agent and folder; Reveal and Terminal pass the folder only", async () => {
    const { ss, store, calls } = setup();
    ss.restore([{ id: "s4", agent: "codex", cwd: "/w/api", startedAt: 1, view: "chat", running: false, exitCode: 0 }]);
    const d = ss.draftHere("s4")!;
    expect(ss.getState().list.find((r) => r.id === d)).toMatchObject({ status: "draft", agent: "codex", cwd: "/w/api" });
    expect(store.getState().ui).toMatchObject({ view: "session", session: d });
    // the late home look-up does not move the folder picked for it
    await wait(20);
    expect(ss.getState().list.find((r) => r.id === d)?.cwd).toBe("/w/api");
    await ss.revealFolder("s4");
    await ss.openTerminal("s4");
    expect(calls().filter((c) => c.op === "reveal" || c.op === "terminal")).toEqual([
      { op: "reveal", cwd: "/w/api" },
      { op: "terminal", cwd: "/w/api" },
    ]);
    expect(ss.draftHere("nope")).toBeNull();
  });
});

describe("the sidebar search", () => {
  it("matches a session by the name its row shows or by its folder, ignoring case", () => {
    const r = live({ agentTitle: "Fix the login redirect", cwd: "/Users/you/code/Web-App" });
    expect(sessionMatches(r, "")).toBe(true);
    expect(sessionMatches(r, "login")).toBe(true);
    expect(sessionMatches(r, "web-app")).toBe(true);
    expect(sessionMatches(r, "/users/you/code")).toBe(true);
    expect(sessionMatches(r, "codex")).toBe(false);
    // the person's own name wins over the agent's, as on the row
    expect(sessionMatches({ ...r, title: "Auth work" }, "auth")).toBe(true);
    // a draft is \"New session\" over its folder
    expect(sessionMatches(live({ status: "draft", cwd: "/w/api" }), "new session")).toBe(true);
    expect(sessionMatches(live({ status: "draft", cwd: "/w/api" }), "api")).toBe(true);
  });
});

describe("continuing a past conversation", () => {
  const past: PastChat = { agent: "claude", id: "bbbbbbbb-1111-4222-8333-444444444444", cwd: "/Users/you/code/omher", title: "Remember the word MARIGOLD for later", named: false, at: 1 };

  it("opens a session in its folder with the earlier messages and resumes the agent's own conversation", async () => {
    const { ss, store, calls } = setup([past]);
    const id = await ss.continuePast(past);
    const r = ss.getState().list.find((x) => x.id === id)!;
    expect(r).toMatchObject({ agent: "claude", cwd: "/Users/you/code/omher", agentSession: past.id, promptTitle: past.title, view: "chat" });
    expect(store.getState().ui).toMatchObject({ view: "session", session: id });
    const key = ss.chatKey(id)!;
    expect(store.getState().chats[key].messages.slice(0, 2).map((m) => [m.role, m.text])).toEqual([
      ["user", "Remember the word MARIGOLD for later"],
      ["assistant", "Noted: MARIGOLD."],
    ]);
    expect(calls().find((c) => c.op === "chat.start")).toMatchObject({ agent: "claude", cwd: "/Users/you/code/omher", resume: past.id });
    // the folder becomes a recent one
    expect(ss.getState().recent[0]).toMatchObject({ agent: "claude", cwd: "/Users/you/code/omher" });
    // picking it again opens the same session; nothing starts twice
    expect(await ss.continuePast(past)).toBe(id);
    expect(calls().filter((c) => c.op === "chat.start")).toHaveLength(1);
  });

  it("a named conversation keeps its name as the agent's title", async () => {
    const named: PastChat = { agent: "codex", id: "01a1d060-4ab7-72b2-b02b-1dbee1d5f52c", cwd: "/Users/you/code/web-app", title: "Add a dark theme", named: true, at: 1 };
    const { ss, calls } = setup([named]);
    const id = await ss.continuePast(named);
    expect(ss.getState().list.find((x) => x.id === id)).toMatchObject({ agentTitle: "Add a dark theme" });
    expect(calls().find((c) => c.op === "chat.start")).toMatchObject({ agent: "codex", resume: named.id });
  });

  it("the list asks only for the agent's conversations in the folders given", async () => {
    const { host, g } = setup();
    const rows = await host.pastChats("claude", ["/Users/you/code/omher", "/Users/you"]);
    expect(rows.map((r) => r.title)).toEqual(["Remember the word MARIGOLD for later"]);
    expect(g.__omherPastReads).toEqual([{ op: "list", agent: "claude", cwds: ["/Users/you/code/omher", "/Users/you"] }]);
  });

  it("ages read as now, minutes, hours, days", () => {
    const now = 1_000_000_000_000;
    expect(ageOf(now / 1000 - 10, now)).toBe("now");
    expect(ageOf(now / 1000 - 5 * 60, now)).toBe("5m");
    expect(ageOf(now / 1000 - 3 * 3600, now)).toBe("3h");
    expect(ageOf(now / 1000 - 2 * 86_400, now)).toBe("2d");
  });
});

describe("shortcuts", () => {
  const k = (key: string, o: Partial<{ code: string; meta: boolean; ctrl: boolean; shift: boolean; alt: boolean; isComposing: boolean; keyCode: number }> = {}) => ({
    key,
    code: o.code,
    metaKey: !!o.meta,
    ctrlKey: !!o.ctrl,
    shiftKey: !!o.shift,
    altKey: !!o.alt,
    isComposing: o.isComposing,
    keyCode: o.keyCode,
  });

  it("⌘N opens the + menu; ⌘⇧] and ⌘⇧[ move between sessions (Ctrl elsewhere)", () => {
    expect(shortcutFor(k("n", { meta: true }), true)).toEqual({ kind: "new-session" });
    expect(shortcutFor(k("n", { ctrl: true }), false)).toEqual({ kind: "new-session" });
    expect(shortcutFor(k("n", { ctrl: true }), true)).toBeNull();
    // ⇧ turns ] into } on a US layout; the physical key decides
    expect(shortcutFor(k("}", { meta: true, shift: true, code: "BracketRight" }), true)).toEqual({ kind: "session", step: 1 });
    expect(shortcutFor(k("{", { meta: true, shift: true, code: "BracketLeft" }), true)).toEqual({ kind: "session", step: -1 });
    expect(shortcutFor(k("]", { ctrl: true, shift: true }), false)).toEqual({ kind: "session", step: 1 });
    // without ⇧, ⌘] is not ours
    expect(shortcutFor(k("]", { meta: true, code: "BracketRight" }), true)).toBeNull();
  });

  it("nothing fires while an input method is composing", () => {
    expect(shortcutFor(k("n", { meta: true, isComposing: true }), true)).toBeNull();
    expect(shortcutFor(k("}", { meta: true, shift: true, code: "BracketRight", keyCode: 229 }), true)).toBeNull();
    expect(shortcutFor(k("k", { meta: true, isComposing: true }), true)).toBeNull();
  });

  it("stepping wraps around the sidebar order; none open starts at either end", () => {
    const ids = ["s3", "s2", "s1"];
    expect(stepSession(ids, "s3", 1)).toBe("s2");
    expect(stepSession(ids, "s1", 1)).toBe("s3");
    expect(stepSession(ids, "s3", -1)).toBe("s1");
    expect(stepSession(ids, null, 1)).toBe("s3");
    expect(stepSession(ids, null, -1)).toBe("s1");
    expect(stepSession(ids, "gone", 1)).toBe("s3");
    expect(stepSession([], null, 1)).toBeNull();
  });
});

describe("the asks count", () => {
  it("is the number of open asks, at most 99", () => {
    expect([0, 3, 99, 150, -1].map(badgeCount)).toEqual([0, 3, 99, 99, 0]);
  });
});
