// A New session chat (draft): which agent and folder it opens on, that nothing starts until the first message,
// that the first message becomes the agent's first prompt in the folder chosen, and that closing a draft starts
// nothing.
import { describe, expect, it } from "vitest";
import { AGENTS, draftAgent, draftFolder, folderChoices, INSTALL, installLine, lastAgent, menuOrder, menuParts, missingNote, registerAcp, rowModel, type AcpRow, type AgentInfo, type Recent, type SessionRec } from "./agents";
import shellList from "./mockAcpAgents.json";
import { MockHost, type MockCall } from "./host";
import { createSessions } from "./sessions";
import { createStore, type BridgeLike } from "../state/store";
import { getDraft, setDraft as setUnsent } from "../app/drafts";

/** The shell's look-up: the built-ins, then the generic ACP agents with their rows (the copy a Rust test pins). */
const ACP: AcpRow[] = shellList;
const info = (installed: string[]): AgentInfo[] => [
  ...AGENTS.map((a) => ({ id: a.id, label: a.label, mode: a.mode, path: installed.includes(a.id) ? `/bin/${a.id}` : null })),
  ...ACP.map((r) => ({ id: r.id, label: r.label, mode: "chat" as const, path: installed.includes(r.id) ? `/bin/${r.id}` : null, acp: r })),
];
registerAcp(info([]));
const rec = (agent: Recent["agent"], cwd: string, at: number): Recent => ({ agent, cwd, at });

describe("draft defaults", () => {
  it("the agent: the last one used if installed, else the first installed in menu order", () => {
    expect(lastAgent([])).toBeNull();
    expect(lastAgent([rec("claude", "/a", 1), rec("codex", "/b", 3), rec("pi", "/c", 2)])).toBe("codex");
    const recent = [rec("codex", "/a", 5), rec("claude", "/b", 2)];
    expect(draftAgent(recent, info(["claude", "codex"]))).toBe("codex");
    // the last one is gone from this computer: the first installed takes over
    expect(draftAgent(recent, info(["omh", "pi"]))).toBe("omh");
    expect(draftAgent([], info(["pi", "grok"]))).toBe("pi");
    // nothing installed: still a choice to show (it is disabled with its install line)
    expect(draftAgent(recent, info([]))).toBe("codex");
    expect(draftAgent([], info([]))).toBe("claude");
    // before the look-up: the last one used, else Claude Code
    expect(draftAgent(recent, null)).toBe("codex");
    expect(draftAgent([], null)).toBe("claude");
  });

  it("the + menu: installed agents first by tier (the last one used leads its own tier), then the missing ones", () => {
    const ids = (l: AgentInfo[]) => l.map((a) => a.id);
    const all = info(["claude", "codex", "omo", "dsh"]);
    expect(ids(menuOrder(all, []))).toEqual(["claude", "codex", "omo", "dsh", "omh", "pi", "omp", "grok", "opencode", "gemini", "qwen", "kimi", "copilot", "cline"]);
    expect(ids(menuOrder(all, [rec("claude", "/a", 1), rec("omo", "/b", 3)]))).toEqual(["omo", "claude", "codex", "dsh", "omh", "pi", "omp", "grok", "opencode", "gemini", "qwen", "kimi", "copilot", "cline"]);
    // the last one used is no longer installed: it stays with the missing ones
    expect(ids(menuOrder(info(["codex", "grok"]), [rec("pi", "/a", 1)]))).toEqual(["codex", "grok", "claude", "omo", "dsh", "omh", "pi", "omp", "opencode", "gemini", "qwen", "kimi", "copilot", "cline"]);
    // the install lines of the two new harnesses
    expect(INSTALL.omo).toBe("npm i -g omo-ai");
    expect(missingNote("omo")).toBe("omo was not found on this computer · install: npm i -g omo-ai");
    // DSH is DeepSeek Harness: its own npm package or its app, never deepseek-bot's install script
    expect(INSTALL.dsh).toBe("npm i -g @deepseek-ai/dsh");
    expect(missingNote("dsh")).toBe("DeepSeek Harness (dsh) was not found on this computer · install: npm i -g @deepseek-ai/dsh (or the DeepSeek Harness app, which carries it)");
    expect(missingNote("dsh")).not.toMatch(/deepseek-bot/);
  });

  it("the + menu folds the agents that are not installed behind one row, and shows every agent when none is", () => {
    const ids = (l: AgentInfo[]) => l.map((a) => a.id);
    // four installed, ten folded: the menu shows the four by tier (the last one used stays in its tier), the rest behind "More"
    const p = menuParts(info(["claude", "codex", "omh", "gemini"]), [rec("gemini", "/a", 2)]);
    expect(ids(p.shown)).toEqual(["claude", "codex", "omh", "gemini"]);
    expect(ids(p.more)).toEqual(["omo", "dsh", "pi", "omp", "grok", "opencode", "qwen", "kimi", "copilot", "cline"]);
    // a new agent that gets installed moves up out of the fold
    expect(ids(menuParts(info(["claude", "gemini"]), []).shown)).toEqual(["claude", "gemini"]);
    // nothing installed: nothing to fold behind, every agent shows with its install line
    const none = menuParts(info([]), []);
    expect(none.shown).toHaveLength(14);
    expect(none.more).toEqual([]);
    // the five generic ACP agents' install lines come from the shell's rows and are 0.2.8's, word for word
    expect(["gemini", "qwen", "kimi", "copilot", "cline"].map(installLine)).toEqual([
      "npm install -g @google/gemini-cli",
      "npm install -g @qwen-code/qwen-code@latest",
      "npm install -g @moonshot-ai/kimi-code",
      "npm install -g @github/copilot",
      "npm install -g cline",
    ]);
    expect(missingNote("gemini")).toBe("gemini was not found on this computer · install: npm install -g @google/gemini-cli");
  });

  it("the folder: the last folder used, else home, else nothing yet", () => {
    expect(draftFolder([rec("claude", "/w/old", 1), rec("codex", "/w/new", 4)], "/Users/k")).toBe("/w/new");
    expect(draftFolder([], "/Users/k")).toBe("/Users/k");
    expect(draftFolder([], null)).toBe("");
  });

  it("the folder menu: the recents in order, then home unless it is one of them", () => {
    const list = [rec("claude", "/w/a", 3), rec("codex", "/w/b", 2)];
    expect(folderChoices(list, "/Users/k")).toEqual({ recent: ["/w/a", "/w/b"], home: "/Users/k" });
    expect(folderChoices([...list, rec("pi", "/Users/k", 1)], "/Users/k")).toEqual({ recent: ["/w/a", "/w/b", "/Users/k"], home: null });
    expect(folderChoices([], null)).toEqual({ recent: [], home: null });
  });

  it("a draft row reads New session over its folder, never live", () => {
    const d: SessionRec = { id: "s1", agent: "codex", cwd: "/Users/k/code/app", startedAt: 1_000, status: "draft", view: "chat" };
    expect(rowModel(d, { turn: true, needsYou: true }, { cwds: [d.cwd], home: "/Users/k" })).toEqual({
      title: "New session",
      titleSource: "folder",
      folder: "app",
      sub: "~/code/app",
      live: false,
      needsYou: false,
      mark: null,
      over: false,
      ts: 1,
    });
    expect(rowModel({ ...d, cwd: "" }).sub).toBe("Codex");
  });
});

// ---- the sessions store with the mock host ------------------------------------------------------

function bridgeStub(): BridgeLike {
  return {
    connect: async () => undefined,
    onAny: () => () => {},
    onStatus: () => () => {},
    request: (async () => ({})) as BridgeLike["request"],
  };
}

function setup(installed = ["claude", "codex", "omh", "grok"], recent: Recent[] = []) {
  const g: Record<string, unknown> = { __omherMockAgents: installed };
  const host = new MockHost(g);
  const store = createStore(bridgeStub());
  const storage = new Map<string, string>([["omher.sessions.recent", JSON.stringify(recent)]]);
  (globalThis as { localStorage?: unknown }).localStorage = {
    getItem: (k: string) => storage.get(k) ?? null,
    setItem: (k: string, v: string) => void storage.set(k, v),
    removeItem: (k: string) => void storage.delete(k),
  };
  const ss = createSessions(host, () => store);
  const calls = () => (g.__omherSessionCalls as MockCall[] | undefined) ?? [];
  return { ss, store, calls, storage, g };
}

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));

describe("a New session chat", () => {
  it("opens at once on the last agent and folder, starts nothing, and is reused while it is open", async () => {
    const { ss, store, calls } = setup(undefined, [rec("codex", "/w/api", 2), rec("claude", "/w/web", 1)]);
    const id = ss.draft();
    expect(store.getState().ui).toMatchObject({ view: "session", session: id });
    expect(ss.getState().list[0]).toMatchObject({ id, status: "draft", agent: "codex", cwd: "/w/api" });
    expect(ss.draft()).toBe(id);
    expect(ss.getState().list).toHaveLength(1);
    await wait(10);
    expect(calls().filter((c) => c.op !== "reset")).toEqual([]);
  });

  it("opens on the agent picked in the + menu; an open draft takes the new pick; a late look-up does not move it", async () => {
    const { ss, calls } = setup(undefined, [rec("codex", "/w/api", 2)]);
    const id = ss.draft("omh");
    expect(ss.getState().list[0]).toMatchObject({ id, status: "draft", agent: "omh", cwd: "/w/api" });
    expect(ss.draft("claude")).toBe(id);
    expect(ss.getState().list).toHaveLength(1);
    expect(ss.getState().list[0].agent).toBe("claude");
    await ss.loadAgents();
    expect(ss.getState().list[0].agent).toBe("claude");
    expect(calls().filter((c) => c.op !== "reset")).toEqual([]);
  });

  it("a DSH session is a DeepSeek Harness chat: no terminal, the harness's own session id, continued by Restart", async () => {
    const { ss, store, calls } = setup(["dsh"]);
    await ss.loadAgents();
    const id = ss.draft("dsh");
    ss.setDraft(id, { cwd: "/w/bot" });
    await ss.start(id, "Remember PLUM-42.");
    await wait(1000);
    const r = ss.getState().list[0];
    expect(r).toMatchObject({ status: "running", view: "chat", cwd: "/w/bot", agentSession: "session-8c11e2bc-9f55-4bcb-a597-19ea472184e8" });
    expect(calls().filter((c) => c.op === "start")).toEqual([]);
    expect(calls().find((c) => c.op === "chat.start")).toMatchObject({ agent: "dsh", cwd: "/w/bot" });
    expect(store.getState().chats[`agent:${id}`].messages.map((m) => m.text)).toEqual(["Remember PLUM-42.", "(mock DSH) You said: Remember PLUM-42."]);
    // another DSH session starts a harness session of its own (no id carried over)
    await ss.close(id);
    const again = ss.draft("dsh");
    ss.setDraft(again, { cwd: "/w/bot" });
    await ss.start(again);
    await wait(60);
    const live = calls().filter((c) => c.op === "chat.start").at(-1)!;
    expect(live.resume).toBeUndefined();
  });

  it("with no recents it opens in home once home is known; a folder the person picked stays", async () => {
    const { ss } = setup();
    const id = ss.draft();
    expect(ss.getState().list[0].cwd).toBe("");
    await ss.loadAgents();
    expect(ss.getState().list[0]).toMatchObject({ cwd: "/Users/you", agent: "claude" });
    ss.setDraft(id, { cwd: "/w/picked" });
    await ss.loadAgents();
    expect(ss.getState().list[0].cwd).toBe("/w/picked");
  });

  it("the first message starts the agent in the chosen folder and is its first prompt; then both are fixed", async () => {
    const { ss, store, calls, storage } = setup(undefined, [rec("claude", "/w/web", 1)]);
    await ss.loadAgents();
    const id = ss.draft();
    ss.setDraft(id, { agent: "codex", cwd: "/w/api" });
    setUnsent(`agent:${id}`, "  run the tests ");
    expect(await ss.start(id, "  run the tests ")).toBe(true);
    expect(getDraft(`agent:${id}`)).toBe(""); // sent, so no longer unsent text
    const start = calls().find((c) => c.op === "chat.start")!;
    expect(start).toMatchObject({ agent: "codex", cwd: "/w/api" });
    const send = calls().find((c) => c.op === "chat.input")!;
    // with the bubble's id, so a message sent while a turn runs can be shown waiting
    expect(send.input).toEqual({ kind: "send", text: "run the tests", id: expect.stringMatching(/^local-/) });
    expect(calls().indexOf(start)).toBeLessThan(calls().indexOf(send));
    const key = ss.chatKey(id)!;
    expect(store.getState().chats[key].items.find((i) => i.kind === "user")).toMatchObject({ text: "run the tests" });
    expect(ss.getState().list[0]).toMatchObject({ status: "running", agent: "codex", cwd: "/w/api", promptTitle: "run the tests" });
    // the folder joins the recents, newest first, once
    expect(JSON.parse(storage.get("omher.sessions.recent")!).map((r: Recent) => r.cwd)).toEqual(["/w/api", "/w/web"]);
    // fixed: a late change and a second start are refused
    ss.setDraft(id, { agent: "claude", cwd: "/elsewhere" });
    expect(await ss.start(id, "again")).toBe(false);
    expect(ss.getState().list[0]).toMatchObject({ agent: "codex", cwd: "/w/api" });
    expect(calls().filter((c) => c.op === "chat.start")).toHaveLength(1);
    // the next New session opens on what was just used
    const next = ss.draft();
    expect(next).not.toBe(id);
    expect(ss.getState().list[0]).toMatchObject({ id: next, agent: "codex", cwd: "/w/api", status: "draft" });
  });

  it("a terminal agent starts in the folder on Start and is sent nothing", async () => {
    const { ss, calls } = setup(["grok"]);
    await ss.loadAgents();
    const id = ss.draft();
    expect(ss.getState().list[0].agent).toBe("grok");
    ss.setDraft(id, { cwd: "/w/tui" });
    await ss.start(id);
    expect(ss.getState().list[0]).toMatchObject({ status: "starting", view: "terminal", cwd: "/w/tui" });
    expect(calls().filter((c) => c.op === "chat.start" || c.op === "chat.input")).toEqual([]);
  });

  it("closing a draft starts nothing and forgets it", async () => {
    const { ss, store, calls } = setup();
    await ss.loadAgents();
    const id = ss.draft();
    ss.close(id);
    await wait(10);
    expect(ss.getState().list).toEqual([]);
    expect(store.getState().ui.view).not.toBe("session");
    // nothing started; only the draft's (empty) attachment folder is let go
    expect(calls().filter((c) => c.op !== "reset")).toEqual([{ op: "file.remove", session: id }]);
    expect(await ss.start(id, "late")).toBe(false);
  });

  it("the folder dialog opens at the draft's folder; cancelling it changes nothing", async () => {
    const { ss, g } = setup(undefined, [rec("claude", "/w/web", 1)]);
    await ss.loadAgents();
    const id = ss.draft();
    g.__omherPickFolder = null;
    expect(await ss.chooseFolder(id)).toBeNull();
    expect(ss.getState().list[0].cwd).toBe("/w/web");
    g.__omherPickFolder = "/w/chosen";
    expect(await ss.chooseFolder(id)).toBe("/w/chosen");
    expect(ss.getState().list[0].cwd).toBe("/w/chosen");
  });
});
