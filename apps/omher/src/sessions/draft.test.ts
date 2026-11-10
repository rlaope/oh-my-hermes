// A New session chat (draft): which agent and folder it opens on, that nothing starts until the first message,
// that the first message becomes the agent's first prompt in the folder chosen, and that closing a draft starts
// nothing.
import { describe, expect, it } from "vitest";
import { AGENTS, draftAgent, draftFolder, folderChoices, lastAgent, rowModel, type AgentInfo, type Recent, type SessionRec } from "./agents";
import { MockHost, type MockCall } from "./host";
import { createSessions } from "./sessions";
import { createStore, type BridgeLike } from "../state/store";
import { getDraft, setDraft as setUnsent } from "../app/drafts";

const info = (installed: string[]): AgentInfo[] => AGENTS.map((a) => ({ id: a.id, label: a.label, mode: a.mode, path: installed.includes(a.id) ? `/bin/${a.id}` : null }));
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
    expect(send.input).toEqual({ kind: "send", text: "run the tests" });
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
    expect(calls().filter((c) => c.op !== "reset")).toEqual([]);
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
