// oh-my-hermes comes back by itself after omher restarts: a TERMINALS `omh` terminal that was running starts again
// (with its row's link, OMHER_TERMINAL_LINK, so `omh` reopens the session it dropped there), and an oh-my-hermes folder
// chat that was running is attached again through the bridge's `folder.resume` (by the stored id its row kept), paused
// with the reason when the bridge refuses. The stored id survives the snapshot.
import { describe, expect, it } from "vitest";
import { MockHost, TauriHost, type MockCall } from "./host";
import { createSessions } from "./sessions";
import { createStore, type BridgeLike } from "../state/store";
import { buildResume, parseResume, type SavedSession } from "../app/resume";

const T = 1_800_000_000_000;
const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));
const LINK = "abcdefgh23";

type Req = { op: string; params: Record<string, unknown> };

/** A bridge that answers `folder.open` / `folder.resume` as the real one does, and records every request. */
function bridge(resume: (p: Record<string, unknown>) => unknown): BridgeLike & { reqs: Req[] } {
  const reqs: Req[] = [];
  const request = (async (op: string, params: Record<string, unknown> = {}) => {
    reqs.push({ op, params });
    if (op === "bots.list") return { bots: [] };
    if (op === "models.options") return { providers: [{ slug: "claude-proxy", name: "Claude", models: ["claude-opus-5-5"] }], model: "claude-opus-5-5", provider: "claude-proxy" };
    if (op === "folder.resume") return resume(params);
    if (op === "folder.open") return { session: "f-new", stored: "stored-new", cwd: params.cwd, model: "m", provider: "p", reasoning: "high" };
    return {};
  }) as BridgeLike["request"];
  return { connect: async () => undefined, onAny: () => () => {}, onStatus: () => () => {}, request, reqs };
}

function setup(resume: (p: Record<string, unknown>) => unknown, more: Record<string, unknown> = {}) {
  const g: Record<string, unknown> = { ...more };
  const b = bridge(resume);
  const store = createStore(b);
  const ss = createSessions(new MockHost(g), () => store);
  const calls = () => ((g.__omherSessionCalls as MockCall[] | undefined) ?? []).filter((c) => c.op === "start" || c.op === "chat.start");
  return { ss, store, b, calls };
}

const omhChat = (over: Partial<SavedSession> = {}): SavedSession => ({
  id: "s3",
  linkId: LINK,
  agent: "omh",
  cwd: "/w/web-app",
  startedAt: T,
  view: "chat",
  running: true,
  bot: "kami",
  agentSession: "stored-folder-0",
  messages: [{ id: "m1", role: "user", text: "old picture", ts: 1 }],
  ...over,
});

const omhTerm = (over: Partial<SavedSession> = {}): SavedSession => ({ id: "s2", linkId: LINK, agent: "omh", cwd: "/w/web-app", startedAt: T, view: "terminal", open: "terminal", running: true, ...over });

describe("a TERMINALS oh-my-hermes terminal after a restart", () => {
  it("comes back starting with no conversation id, never paused, and starts no chat", async () => {
    const { ss, calls } = setup(() => ({}));
    ss.restore([omhTerm()]);
    await ss.loadAgents();
    await wait(20);
    const r = ss.getState().list[0];
    expect(r).toMatchObject({ id: "s2", agent: "omh", status: "starting", view: "terminal", open: "terminal", linkId: LINK });
    expect(r.paused).toBeUndefined();
    expect(r.agentSession).toBeUndefined();
    expect(calls().filter((c) => c.op === "chat.start")).toEqual([]);
  });

  it("an ended one stays ended; one whose `omh` is gone from this computer comes back paused", async () => {
    const ended = setup(() => ({}));
    ended.ss.restore([omhTerm({ running: false, exitCode: 0 })]);
    await ended.ss.loadAgents();
    expect(ended.ss.getState().list[0]).toMatchObject({ status: "exited", exitCode: 0 });
    expect(ended.ss.getState().list[0].paused).toBeUndefined();

    const gone = setup(() => ({}), { __omherMockNoOmh: true });
    gone.ss.restore([omhTerm()]);
    await gone.ss.loadAgents();
    await wait(20);
    expect(gone.ss.getState().list[0]).toMatchObject({ status: "exited", paused: true });
    expect(gone.calls()).toEqual([]);
  });

  it("Restart of an ended one starts it again in a fresh terminal (the view mounts it with the link)", async () => {
    const { ss } = setup(() => ({}));
    ss.restore([omhTerm({ running: false, exitCode: 1 })]);
    await ss.loadAgents();
    await ss.restart("s2");
    expect(ss.getState().list[0]).toMatchObject({ status: "starting", view: "terminal", linkId: LINK });
  });

  it("other agents' terminals are unchanged: Grok comes back paused, a Claude Code one with no id paused", async () => {
    const { ss } = setup(() => ({}));
    ss.restore([
      { id: "s4", agent: "grok", cwd: "/w/g", startedAt: T, view: "terminal", running: true },
      { id: "s5", agent: "claude", cwd: "/w/c", startedAt: T, view: "terminal", open: "terminal", running: true },
    ]);
    await ss.loadAgents();
    expect(ss.getState().list.map((r) => [r.id, r.status, !!r.paused])).toEqual([
      ["s4", "exited", true],
      ["s5", "exited", true],
    ]);
  });
});

describe("the link reaches only an oh-my-hermes terminal", () => {
  it("TauriHost sends it to session_start as `link`, null when there is none", async () => {
    const sent: { cmd: string; args: Record<string, unknown> }[] = [];
    class Host extends TauriHost {
      protected override async core() {
        const invoke = async (cmd: string, args: Record<string, unknown>) => {
          sent.push({ cmd, args });
          return 7;
        };
        return { invoke, Channel: class {} } as unknown as Awaited<ReturnType<TauriHost["core"]>>;
      }
    }
    const h = new Host();
    await h.start("omh", "/w", 80, 24, () => {}, () => {}, undefined, undefined, undefined, LINK);
    await h.start("claude", "/w", 80, 24, () => {}, () => {});
    expect(sent.map((s) => [s.cmd, s.args.agent, s.args.link])).toEqual([
      ["session_start", "omh", LINK],
      ["session_start", "claude", null],
    ]);
  });

  it("the mock host refuses it for any other agent, as the shell does", async () => {
    const g: Record<string, unknown> = {};
    const h = new MockHost(g);
    await expect(h.start("claude", "/w", 80, 24, () => {}, () => {}, undefined, undefined, undefined, LINK)).rejects.toThrow("claude sessions are not given a terminal link");
    await h.start("omh", "/w", 80, 24, () => {}, () => {}, undefined, undefined, undefined, LINK);
    expect((g.__omherSessionCalls as MockCall[]).filter((c) => c.op === "start")).toEqual([expect.objectContaining({ agent: "omh", link: LINK })]);
  });
});

describe("an oh-my-hermes folder chat after a restart", () => {
  const answer = (p: Record<string, unknown>) => ({
    session: "f-again",
    stored: p.stored,
    cwd: p.cwd,
    model: "claude-opus-5-5",
    provider: "claude-proxy",
    reasoning: "high",
    messages: [
      { id: "1", role: "user", text: "what is here?", ts: 1 },
      { id: "2", role: "assistant", text: "two files", ts: 2 },
    ],
    running: false,
  });

  it("comes back starting and is attached again through folder.resume with its stored id; messages are Hermes'", async () => {
    const { ss, store, b, calls } = setup(answer);
    ss.restore([omhChat()]);
    expect(ss.getState().list[0]).toMatchObject({ status: "starting", agentSession: "stored-folder-0" });
    expect(ss.getState().list[0].paused).toBeUndefined();
    await store.actions.init();
    await wait(20);
    expect(b.reqs.filter((r) => r.op.startsWith("folder."))).toEqual([{ op: "folder.resume", params: { bot: "kami", cwd: "/w/web-app", stored: "stored-folder-0" } }]);
    const r = ss.getState().list[0];
    expect(r).toMatchObject({ status: "running", agentSession: "stored-folder-0", model: "claude-opus-5-5" });
    expect(r.paused).toBeUndefined();
    const key = ss.chatKey("s3")!;
    expect(key).toBe("fold:kami:f-again");
    expect(store.getState().chats[key].messages.map((m) => m.text)).toEqual(["what is here?", "two files"]);
    expect(store.getState().chats["agent:s3"]).toBeUndefined(); // the snapshot's picture gave way
    // a message goes to the reattached chat, not a new one
    await ss.send("s3", "and now?");
    expect(b.reqs.filter((x) => x.op === "chat.send").map((x) => x.params)).toEqual([{ bot: "kami", session: "f-again", text: "and now?" }]);
    expect(calls()).toEqual([]);
  });

  it("the restore asks folder.resume once per row and once per saved chat, however the restore is poked", async () => {
    let release: () => void = () => {};
    const held = new Promise<void>((r) => (release = r));
    const { ss, store, b } = setup(async (p) => {
      await held;
      return answer(p);
    });
    // two rows that hold the same saved chat (a duplicated snapshot) and one of their own
    ss.restore([omhChat({ id: "s3" }), omhChat({ id: "s4" }), omhChat({ id: "s5", agentSession: "stored-folder-5" })]);
    ss.restore([omhChat({ id: "s3" })]); // a second restore does nothing
    await store.actions.init();
    await wait(20);
    // while the first answers are on their way, Resume and Restart of the row being attached send nothing more
    await ss.resume("s3");
    await ss.restart("s3");
    release();
    await wait(20);
    const asked = b.reqs.filter((r) => r.op === "folder.resume").map((r) => r.params.stored);
    expect(asked).toEqual(["stored-folder-0", "stored-folder-5"]);
    expect(b.reqs.filter((r) => r.op === "folder.open")).toEqual([]);
    const rows = Object.fromEntries(ss.getState().list.map((r) => [r.id, r]));
    expect(rows.s3).toMatchObject({ status: "running" });
    expect(rows.s5).toMatchObject({ status: "running" });
    expect(rows.s4).toMatchObject({ status: "exited", paused: true }); // the second holder waits for the person
  });

  it("a refusal leaves it paused with the reason, and nothing new is opened by itself", async () => {
    const { ss, store, b } = setup(() => {
      throw { code: "not_found", message: "no such folder chat" };
    });
    ss.restore([omhChat()]);
    await store.actions.init();
    await wait(20);
    expect(ss.getState().list[0]).toMatchObject({ status: "exited", paused: true, error: "no such folder chat" });
    expect(b.reqs.filter((r) => r.op === "folder.open")).toEqual([]);
    // the old picture stays until the person resumes
    expect(store.getState().chats["agent:s3"].messages.map((m) => m.text)).toEqual(["old picture"]);
  });

  it("Resume on a paused one tries folder.resume first, and opens a new chat in the folder only when that is refused", async () => {
    let refuse = false;
    const { ss, store, b } = setup((p) => {
      if (refuse) throw { code: "not_found", message: "no such folder chat" };
      return answer(p);
    });
    // saved before the stored id was kept (an older omher): paused, nothing attached by itself
    ss.restore([omhChat({ id: "s3", agentSession: undefined }), omhChat({ id: "s4", running: false, agentSession: "stored-folder-4" })]);
    await store.actions.init();
    await wait(20);
    expect(ss.getState().list.find((r) => r.id === "s3")).toMatchObject({ status: "exited", paused: true });
    expect(b.reqs.filter((r) => r.op.startsWith("folder."))).toEqual([]);
    // the paused one with no stored id: a new chat in the folder, which keeps its stored id now
    await ss.resume("s3");
    expect(b.reqs.filter((r) => r.op.startsWith("folder.")).map((r) => r.op)).toEqual(["folder.open"]);
    expect(ss.getState().list.find((r) => r.id === "s3")).toMatchObject({ status: "running", agentSession: "stored-new" });

    // a paused one with a stored id: folder.resume first; refused, then a new chat
    const two = setup((p) => {
      if (refuse) throw { code: "not_found", message: "no such folder chat" };
      return answer(p);
    });
    refuse = true;
    two.ss.restore([omhChat({ id: "s5", agentSession: "stored-folder-5" })]);
    await two.store.actions.init();
    await wait(20);
    expect(two.ss.getState().list[0]).toMatchObject({ paused: true, error: "no such folder chat" });
    await two.ss.resume("s5");
    expect(two.b.reqs.filter((r) => r.op.startsWith("folder.")).map((r) => r.op)).toEqual(["folder.resume", "folder.resume", "folder.open"]);
    expect(two.ss.getState().list[0]).toMatchObject({ status: "running", agentSession: "stored-new" });
    expect(two.ss.getState().list[0].paused).toBeUndefined();

    // and one the bridge takes back again: no new chat
    refuse = false;
    const three = setup(answer);
    three.ss.restore([omhChat({ id: "s6", running: true, agentSession: "stored-folder-6", bot: undefined })]);
    expect(three.ss.getState().list[0]).toMatchObject({ paused: true }); // no bot: nothing to attach it to
  });
});

describe("the snapshot keeps an oh-my-hermes row's stored id and link", () => {
  it("round-trips agentSession and linkId", () => {
    const snap = buildResume(
      { bot: null, bots: [], view: "chat", session: null, panelOpen: false, panelTab: "details", runsFull: false, runId: null, drafts: {}, sessions: [omhChat(), omhTerm()], messages: () => undefined },
      T,
    );
    const back = parseResume(JSON.stringify(snap))!;
    expect(back.sessions.map((s) => [s.agent, s.agentSession, s.linkId, s.bot])).toEqual([
      ["omh", "stored-folder-0", LINK, "kami"],
      ["omh", undefined, LINK, undefined],
    ]);
  });
});
