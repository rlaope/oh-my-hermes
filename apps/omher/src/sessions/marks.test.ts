// The state a session row shows and the notification for what a session did outside its chat: it waits for the
// person, it stopped on an error, or it finished something they have not opened yet.
import { describe, expect, it } from "vitest";
import { rowModel, type SessionRec } from "./agents";
import { sessionNote } from "../lib/notify";
import { MockHost } from "./host";
import { createSessions } from "./sessions";
import { createStore, type BridgeLike } from "../state/store";
import type { SessionNote } from "../lib/notify";

const base: SessionRec = { id: "s1", agent: "claude", cwd: "/Users/k/web-app", startedAt: 1_700_000_000_000, status: "running", view: "chat" };
const idle = { turn: false, needsYou: false };

describe("a session row's state", () => {
  it("is waiting while it waits for the person: an open ask, or its terminal rang", () => {
    expect(rowModel(base, { turn: true, needsYou: true })).toMatchObject({ mark: "needs", needsYou: true, sub: "Claude Code" });
    const term: SessionRec = { ...base, view: "terminal", open: "terminal" };
    expect(rowModel(term, undefined, undefined, "bell")).toMatchObject({ mark: "needs", needsYou: false, sub: "Claude Code", over: false });
    // a ring from a program that has since ended is not a wait: how it ended says more
    expect(rowModel({ ...term, status: "exited", exitCode: 0 }, undefined, undefined, "bell").mark).toBeNull();
  });

  it("is an error when it stopped on an error: could not start, a non-zero exit, an ended-with-reason, a failed turn", () => {
    expect(rowModel({ ...base, status: "failed", error: "no such program" })).toMatchObject({ mark: "error", sub: "Claude Code · Could not start", over: true });
    expect(rowModel({ ...base, status: "exited", exitCode: 2 })).toMatchObject({ mark: "error", sub: "Claude Code · Ended · exit 2" });
    expect(rowModel({ ...base, status: "exited", exitCode: null, error: "Hermes closed this chat" })).toMatchObject({ mark: "error", sub: "Claude Code · Ended" });
    expect(rowModel(base, { ...idle, failed: true })).toMatchObject({ mark: "error", sub: "Claude Code", over: false });
    // an error outranks an unseen finish; an open ask outranks both
    expect(rowModel({ ...base, status: "exited", exitCode: 1 }, undefined, undefined, "end").mark).toBe("error");
    expect(rowModel(base, { turn: true, needsYou: true, failed: true }, undefined, "end").mark).toBe("needs");
  });

  it("is done when it finished unseen, and gone once seen; a clean end the person watched shows none", () => {
    expect(rowModel(base, idle, undefined, "end")).toMatchObject({ mark: "done", sub: "Claude Code", over: false });
    expect(rowModel({ ...base, status: "exited", exitCode: 0 }, undefined, undefined, "end")).toMatchObject({ mark: "done", sub: "Claude Code · Ended", over: true });
    expect(rowModel({ ...base, status: "exited", exitCode: 0 })).toMatchObject({ mark: null, sub: "Claude Code · Ended", over: true });
    expect(rowModel(base, idle)).toMatchObject({ mark: null, sub: "Claude Code", over: false });
    // a session waiting for Resume after a restart is not an error
    expect(rowModel({ ...base, status: "exited", exitCode: null, paused: true })).toMatchObject({ mark: null, sub: "Claude Code · Paused", over: true });
  });
});

describe("the notification for a session's own state", () => {
  it("names the session and says what happened, without the program's own text for a ring", () => {
    const name = "web-app · Claude Code";
    expect(sessionNote("s1", { kind: "ended", name, code: 0 })).toEqual({ title: "web-app · Claude Code ended", body: "Its program finished.", bot: "s1", tag: "s1:ended" });
    expect(sessionNote("s1", { kind: "ended", name, code: 2 }).body).toBe("Ended · exit 2");
    expect(sessionNote("s1", { kind: "ended", name, code: null, error: "Claude Code is not signed in." }).body).toBe("Claude Code is not signed in.");
    expect(sessionNote("s1", { kind: "failed", name, error: "" })).toMatchObject({ title: "web-app · Claude Code could not start", body: "Could not start" });
    expect(sessionNote("s1", { kind: "bell", name })).toEqual({ title: "web-app · Claude Code wants your attention", body: "It rang its terminal's bell.", bot: "s1", tag: "s1:bell" });
  });
});

// ---- the sessions store: what it flags and tells while the person is elsewhere ----------------

const bridge: BridgeLike = { connect: async () => undefined, onAny: () => () => {}, onStatus: () => () => {}, request: (async () => ({})) as BridgeLike["request"] };
const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));

function setup() {
  (globalThis as { localStorage?: unknown }).localStorage = { getItem: () => null, setItem: () => {}, removeItem: () => {} };
  const store = createStore(bridge);
  const ss = createSessions(new MockHost({ __omherMockAgents: ["claude"] }), () => store);
  const told: [string, SessionNote][] = [];
  ss.setNotifyState((id, n) => told.push([id, n]));
  return { ss, store, told };
}

describe("a chat session the person is not looking at", () => {
  it("flags a finished answer, forgets it on the next turn or when opened, and tells when its program ends", async () => {
    const { ss, told } = setup();
    await ss.loadAgents();
    const id = ss.draft("claude");
    ss.setDraft(id, { cwd: "/w/web-app" });
    await ss.start(id, "hello");
    expect(ss.getState().unseen[id]).toBeUndefined();
    await wait(950);
    expect(ss.getState().unseen[id]).toBe("end");
    expect(told).toEqual([]); // the answer's own notification is the chat's, not this one

    // the next turn puts the finished one behind it
    await ss.send(id, "/slow");
    expect(ss.getState().unseen[id]).toBeUndefined();
    await ss.interrupt(id);

    await wait(50);
    await ss.send(id, "again");
    await wait(950);
    expect(ss.getState().unseen[id]).toBe("end");
    ss.seen(id);
    expect(ss.getState().unseen[id]).toBeUndefined();

    // its program dies: the row carries it and one notification names the session
    await ss.send(id, "/die");
    await wait(200);
    expect(ss.getState().list[0].status).toBe("exited");
    expect(ss.getState().unseen[id]).toBe("end");
    expect(told).toEqual([[id, { kind: "ended", name: "web-app · Claude Code", code: null, error: "" }]]);

    // closing the session drops what its row carried
    ss.close(id);
    expect(ss.getState().unseen).toEqual({});
  });
});
