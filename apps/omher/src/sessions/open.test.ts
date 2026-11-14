// A New session opens as omher's chat or as the agent's own terminal: which way each agent can open, what the
// person last picked, how a session opened as a terminal runs and comes back, and that a session saved before this
// (no `open`) comes back exactly as it did.
import { describe, expect, it } from "vitest";
import { AGENTS, draftOpen, HERMES_LABEL, opensAs, parseOpens, sessionMode, type AgentId, type AgentInfo } from "./agents";
import { MockHost, type MockCall } from "./host";
import { createSessions } from "./sessions";
import { createStore, type BridgeLike } from "../state/store";
import { buildResume, parseResume, RESUME_KEY, RESUME_VERSION, type SavedSession } from "../app/resume";

const info = (installed: AgentId[], omh: "omh" | "hermes" = "omh"): AgentInfo[] =>
  AGENTS.map((a) =>
    a.id === "omh" && omh === "hermes"
      ? { id: a.id, label: HERMES_LABEL, mode: a.mode, path: "/u/.hermes/hermes-agent/venv/bin/python", via: "hermes" as const }
      : { id: a.id, label: a.label, mode: a.mode, path: installed.includes(a.id) ? `/bin/${a.id}` : null },
  );

describe("sessionMode", () => {
  it("is the agent's own mode when `open` is unset, and a terminal when `open` says so, for a chat agent too", () => {
    const agents = info(["claude", "grok", "omh"]);
    expect(sessionMode(agents, { agent: "claude" })).toBe("chat");
    expect(sessionMode(agents, { agent: "claude", open: "chat" })).toBe("chat");
    expect(sessionMode(agents, { agent: "claude", open: "terminal" })).toBe("terminal");
    expect(sessionMode(agents, { agent: "omh" })).toBe("hermes");
    expect(sessionMode(agents, { agent: "omh", open: "terminal" })).toBe("terminal");
    expect(sessionMode(agents, { agent: "grok" })).toBe("terminal");
    // before the look-up answers, this app's own list stands
    expect(sessionMode(null, { agent: "codex" })).toBe("chat");
    expect(sessionMode(null, { agent: "codex", open: "terminal" })).toBe("terminal");
  });
});

describe("opensAs", () => {
  it("lists the ways each agent can open", () => {
    const table = Object.fromEntries(AGENTS.map((a) => [a.id, opensAs(a.id, info([]))]));
    expect(table).toEqual({
      claude: { chat: true, terminal: true },
      codex: { chat: true, terminal: true },
      omo: { chat: true, terminal: true },
      dsh: { chat: true, terminal: false },
      omh: { chat: true, terminal: true },
      pi: { chat: true, terminal: true },
      omp: { chat: true, terminal: true },
      grok: { chat: false, terminal: true },
      opencode: { chat: true, terminal: true },
    });
    expect(opensAs("claude")).toEqual({ chat: true, terminal: true });
    // a generic ACP agent opens either way
    for (const id of ["gemini", "qwen", "kimi", "copilot", "cline"]) expect(opensAs(id)).toEqual({ chat: true, terminal: true });
  });

  it("gives oh-my-hermes the Hermes chat only for a person who has Hermes and no omh", () => {
    expect(opensAs("omh", info([], "hermes"))).toEqual({ chat: true, terminal: false });
    expect(opensAs("omh", info(["omh"]))).toEqual({ chat: true, terminal: true });
    expect(opensAs("claude", info([], "hermes"))).toEqual({ chat: true, terminal: true });
  });
});

describe("the remembered pick", () => {
  it("defaults to Chat, follows a remembered way, and ignores one the agent no longer has", () => {
    const agents = info(["claude", "dsh", "grok", "omh"]);
    expect(draftOpen("claude", agents, {})).toBe("chat");
    expect(draftOpen("claude", agents, { claude: "terminal" })).toBe("terminal");
    // a remembered Terminal for DSH (no terminal here) is ignored; Grok has no chat, so it is its terminal
    expect(draftOpen("dsh", agents, { dsh: "terminal" })).toBe("chat");
    expect(draftOpen("grok", agents, {})).toBe("terminal");
    expect(draftOpen("grok", agents, { grok: "chat" })).toBe("terminal");
    // oh-my-hermes remembered as Terminal, then omh went away and only Hermes is left
    expect(draftOpen("omh", info([], "hermes"), { omh: "terminal" })).toBe("chat");
  });

  it("is read defensively from storage", () => {
    expect(parseOpens(null)).toEqual({});
    expect(parseOpens("not json")).toEqual({});
    expect(parseOpens("[1]")).toEqual({});
    expect(parseOpens(JSON.stringify({ claude: "terminal", dsh: "terminal", "no pe": "chat", codex: "x", pi: "chat" }))).toEqual({ claude: "terminal", dsh: "terminal", pi: "chat" });
  });
});

// ---- the sessions store with the mock host -----------------------------------------------------

function bridgeStub(): BridgeLike {
  return { connect: async () => undefined, onAny: () => () => {}, onStatus: () => () => {}, request: (async () => ({})) as BridgeLike["request"] };
}

function setup(installed: string[], storedOpens?: Record<string, string>, more: Record<string, unknown> = {}) {
  const g: Record<string, unknown> = { __omherMockAgents: installed, ...more };
  const host = new MockHost(g);
  const store = createStore(bridgeStub());
  const storage = new Map<string, string>();
  if (storedOpens) storage.set("omher.sessions.open", JSON.stringify(storedOpens));
  (globalThis as { localStorage?: unknown }).localStorage = {
    getItem: (k: string) => storage.get(k) ?? null,
    setItem: (k: string, v: string) => void storage.set(k, v),
    removeItem: (k: string) => void storage.delete(k),
  };
  const ss = createSessions(host, () => store);
  const calls = () => ((g.__omherSessionCalls as MockCall[] | undefined) ?? []).filter((c) => c.op !== "reset" && !c.op.startsWith("file."));
  return { ss, calls, storage };
}

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));
const T = 1_800_000_000_000;

describe("starting a New session", () => {
  it("with Terminal picked runs the program in a terminal and never a chat; Chat still opens the chat", async () => {
    const { ss, calls, storage } = setup(["claude", "opencode"]);
    await ss.loadAgents();
    const id = ss.draft("opencode");
    ss.setDraft(id, { cwd: "/w/web-app" });
    ss.setOpen(id, "terminal");
    expect(JSON.parse(storage.get("omher.sessions.open")!)).toEqual({ opencode: "terminal" });
    await ss.start(id);
    expect(ss.getState().list[0]).toMatchObject({ status: "starting", view: "terminal", open: "terminal", agent: "opencode" });
    expect(calls().filter((c) => c.op === "chat.start" || c.op === "chat.input")).toEqual([]);
    expect(ss.chatKey(id)).toBeNull();

    ss.setOpen("s-gone", "terminal"); // an unknown draft changes nothing
    const chat = ss.draft("claude");
    ss.setDraft(chat, { cwd: "/w/web-app" });
    await ss.start(chat, "hello");
    await wait(30);
    expect(calls().filter((c) => c.op === "chat.start").map((c) => c.agent)).toEqual(["claude"]);
    expect(ss.getState().list.find((r) => r.id === chat)).toMatchObject({ view: "chat", status: "running" });
    expect(ss.getState().list.find((r) => r.id === chat)!.open).toBeUndefined();
  });

  it("refuses a way the agent does not have, and ignores a remembered Terminal for DSH", async () => {
    const { ss, calls } = setup(["dsh"], { dsh: "terminal" });
    await ss.loadAgents();
    const id = ss.draft("dsh");
    ss.setDraft(id, { cwd: "/w/bot" });
    ss.setOpen(id, "terminal"); // DSH has no terminal here
    expect(ss.getState().opens.dsh).toBe("terminal"); // what was stored before stays as it was
    await ss.start(id, "hi");
    await wait(60);
    expect(calls().filter((c) => c.op === "start")).toEqual([]);
    expect(calls().find((c) => c.op === "chat.start")).toMatchObject({ agent: "dsh" });
    expect(ss.getState().list[0]).toMatchObject({ view: "chat" });
    expect(ss.getState().list[0].open).toBeUndefined();
  });
});

describe("a session saved before this", () => {
  const saved = (over: Partial<SavedSession>): SavedSession => ({ id: "s2", agent: "claude", cwd: "/w/web-app", startedAt: T, view: "chat", running: true, ...over });

  it("restores the same view as before when it has no `open`, and as a terminal that is not running when it has", async () => {
    const before = setup(["claude"]);
    before.ss.restore([saved({ agentSession: "11111111-2222-4333-8444-555555555555" })]);
    await wait(30);
    expect(before.ss.getState().list[0]).toMatchObject({ view: "chat", status: "running" });
    expect(before.ss.getState().list[0].open).toBeUndefined();
    expect(before.calls().map((c) => c.op)).toEqual(["chat.start"]);

    const after = setup(["claude"]);
    after.ss.restore([saved({ open: "terminal", view: "terminal" })]);
    await wait(30);
    const r = after.ss.getState().list[0];
    expect(r).toMatchObject({ view: "terminal", open: "terminal", status: "exited", paused: true });
    expect(after.calls()).toEqual([]); // nothing starts by itself: no terminal, no chat
    // Resume starts the terminal (the view mounts it), still no chat
    await after.ss.resume("s2");
    expect(after.ss.getState().list[0]).toMatchObject({ status: "starting", view: "terminal", open: "terminal" });
    expect(after.ss.getState().list[0].paused).toBeUndefined();
    expect(after.calls().some((c) => c.op === "chat.start")).toBe(false);
  });

  it("a saved terminal session whose agent has no terminal here any more resumes as the agent opens by itself", async () => {
    // oh-my-hermes was opened as its terminal; since then `omh` was removed and only Hermes is left (no terminal)
    const { ss, calls } = setup(["claude"], undefined, { __omherMockNoOmh: true });
    ss.restore([saved({ agent: "omh", open: "terminal", view: "terminal" })]);
    await ss.loadAgents();
    expect(ss.getState().list[0]).toMatchObject({ view: "terminal", open: "terminal", paused: true });
    await ss.resume("s2");
    await wait(30);
    const r = ss.getState().list[0];
    expect(r.open).toBeUndefined();
    expect(r.view).toBe("chat");
    expect(calls().filter((c) => c.op === "start")).toEqual([]); // the program that is not there is never started

    // an agent that still has its terminal keeps it
    const kept = setup(["claude"]);
    kept.ss.restore([saved({ open: "terminal", view: "terminal" })]);
    await kept.ss.loadAgents();
    await kept.ss.resume("s2");
    expect(kept.ss.getState().list[0]).toMatchObject({ view: "terminal", open: "terminal", status: "starting" });
  });

  it("keeps `open` in the snapshot and reads it back; a snapshot without it has none", () => {
    const snap = (s: SavedSession[]) =>
      buildResume({ bot: null, bots: [], view: "chat", session: null, panelOpen: false, panelTab: "details", runsFull: false, runId: null, drafts: {}, sessions: s, messages: () => undefined }, T);
    const out = snap([saved({ open: "terminal", view: "terminal" }), saved({ id: "s3" })]);
    const back = parseResume(JSON.stringify(out))!;
    expect(back.sessions.map((s) => s.open)).toEqual(["terminal", undefined]);
    expect(back.sessions[1]).not.toHaveProperty("open");
    // an unknown value is dropped
    const odd = parseResume(JSON.stringify({ ...out, sessions: [{ ...out.sessions[0], open: "tui" }] }))!;
    expect(odd.sessions[0].open).toBeUndefined();
    expect(RESUME_KEY).toBe("omher.resume");
    expect(RESUME_VERSION).toBe(1);
  });
});
