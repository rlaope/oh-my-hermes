// After the bridge drops and comes back (sleep/wake, a bridge restart), or after omher itself starts again while
// Hermes ran on, every chat and thread shows what Hermes is doing, and what waits on the person can be answered.
// - an approval still waiting in Hermes is answerable again (the bridge's replay of it was dropped as a duplicate)
// - a thread that finished during the outage reads done, not "Connection to Hermes lost"
// - a thread's held message waits for the thread's re-read (it went out before thread.list and failed)
// - a thread Hermes runs or that waits on the person, never opened in this run, is read without a click
import { expect, it } from "vitest";
import { createStore, selectAsks, type BridgeLike } from "./store";
import type { BridgeEvent } from "../lib/protocol";
import type { BridgeStatus } from "../lib/bridge";

type Thread = { running: boolean; needs: boolean };

function fixture(o: { thread?: Thread } = {}) {
  let status!: (s: BridgeStatus) => void;
  let event!: (e: BridgeEvent) => void;
  const calls: { op: string; params: any }[] = [];
  // what Hermes holds now: per chat ("kami" or a thread id), whether its turn runs, its rows and a waiting ask
  const hermes: Record<string, { running: boolean; messages: { id: string; role: "user" | "assistant"; text: string; ts: number }[]; ask?: string }> = {
    kami: { running: false, messages: [] },
    th1: { running: false, messages: [] },
  };
  let listed = false; // a bridge started again knows no thread until thread.list listed it
  const row = () => ({ thread: "th1", title: "Build", cwd: "/w", started_at: 1, running: false, needs: false, message_count: 1, ...o.thread });
  const replay = (bot: string, session?: string) => {
    const id = hermes[session ?? bot].ask;
    // the bridge writes the reply frame first and replays after it: the event is a later frame
    if (id)
      setTimeout(() =>
        event({ event: "approval.request", bot, ...(session ? { session } : {}), request_id: id, title: "Delete", command: "rm -rf build", choices: ["once", "deny"] } as BridgeEvent),
      );
  };
  const bridge: BridgeLike = {
    connect: async () => {},
    onAny: (h) => {
      event = h;
      return () => {};
    },
    onStatus: (h) => {
      status = h;
      return () => {};
    },
    request: (async (op: string, params: any) => {
      calls.push({ op, params });
      if (op === "hello") return { bridge: "mock", version: "test", hermes: { home: "/scratch" } };
      if (op === "bots.list")
        return { bots: [{ name: "kami", display_name: "Kami", is_default: true, model: "m", provider: "p", description: "", status: "online", running: false }] };
      if (op === "chat.open") {
        replay("kami");
        return { session_id: "s-kami", messages: hermes.kami.messages, running: hermes.kami.running, lost: [], model: "m", provider: "p", reasoning: "high" };
      }
      if (op === "thread.list") {
        await new Promise((r) => setTimeout(r, 20)); // Hermes' session.list takes a moment
        listed = true;
        return { threads: [row()] };
      }
      if (op === "thread.open") {
        if (!listed) throw { code: "not_found", message: "no such thread" };
        replay("kami", "th1");
        return { thread: "th1", session_id: "th1", title: "Build", cwd: "/w", messages: hermes.th1.messages, running: hermes.th1.running, lost: [], model: "m", provider: "p", reasoning: "" };
      }
      if (op === "chat.send") {
        if (params.session && !listed) throw { code: "not_found", message: "no such folder chat" };
        return {};
      }
      if (op === "elsewhere.list") return { sessions: [] };
      if (op === "routines.list") return { routines: [] };
      if (op === "automations.list") return { automations: [] };
      if (op === "models.options") return { providers: [], current: { model: "m", provider: "p", reasoning: "high" }, reasoning_levels: [] };
      return {};
    }) as BridgeLike["request"],
  };
  const store = createStore(bridge);
  return {
    store,
    calls,
    hermes,
    status: (s: BridgeStatus) => status(s),
    event: (e: BridgeEvent) => event(e),
    /** The bridge process started again: it has not listed the bot's threads yet. */
    restartBridge: () => {
      listed = false;
    },
  };
}
const settle = (ms = 80) => new Promise((r) => setTimeout(r, ms));
const TH = "fold:kami:th1";

async function started(o: { thread?: Thread } = {}) {
  const f = fixture(o);
  await f.store.actions.init();
  f.status("open");
  await settle();
  return f;
}

it("an approval still waiting in Hermes after a reconnect is answerable again, once", async () => {
  const f = await started();
  f.event({ event: "turn.start", bot: "kami" } as BridgeEvent);
  f.event({ event: "approval.request", bot: "kami", request_id: "ap1", title: "Delete", command: "rm -rf build", choices: ["once", "deny"] } as BridgeEvent);
  expect(selectAsks(f.store.getState()).map((a) => a.item.request_id)).toEqual(["ap1"]);
  f.status("connecting"); // the bridge went away: the turn ends here, the card reads not answered
  expect(selectAsks(f.store.getState())).toEqual([]);
  f.hermes.kami = { running: true, messages: [{ id: "u1", role: "user", text: "clean up", ts: 1 }], ask: "ap1" };
  await settle(5); // the outage lasts a moment
  f.status("open"); // resync: chat.open says the turn runs and replays the same ask
  await settle();
  const asks = selectAsks(f.store.getState());
  expect(asks.map((a) => [a.bot, a.item.request_id])).toEqual([["kami", "ap1"]]);
  expect(f.store.getState().chats.kami.items.filter((i) => i.kind === "approval")).toHaveLength(1);
});

it("an answered card stays answered when the ask is replayed", async () => {
  const f = await started();
  f.event({ event: "turn.start", bot: "kami" } as BridgeEvent);
  f.event({ event: "approval.request", bot: "kami", request_id: "ap1", title: "Delete", command: "rm -rf build", choices: ["once", "deny"] } as BridgeEvent);
  f.store.dispatch({ type: "approval.resolved", bot: "kami", request_id: "ap1", choice: "deny" });
  f.status("connecting");
  f.hermes.kami = { running: true, messages: [], ask: "ap1" };
  await settle(5);
  f.status("open");
  await settle();
  expect(selectAsks(f.store.getState())).toEqual([]);
});

async function openThread(f: Awaited<ReturnType<typeof started>>) {
  await f.store.actions.openThread("kami", "th1");
  expect(f.store.getState().chats[TH].loaded).toBe(true);
  f.event({ event: "turn.start", bot: "kami", session: "th1" } as BridgeEvent);
  expect(f.store.getState().chats[TH].turn).not.toBeNull();
}

it("a thread that finished while the bridge was away reads done, not connection lost", async () => {
  const f = await started();
  await openThread(f);
  f.status("connecting");
  expect(f.store.getState().chats[TH].lastTurn?.outcome).toBe("interrupted");
  f.hermes.th1 = {
    running: false,
    messages: [
      { id: "u1", role: "user", text: "build it", ts: 1 },
      { id: "a1", role: "assistant", text: "built", ts: 2 },
    ],
  };
  f.status("open");
  await settle();
  const chat = f.store.getState().chats[TH];
  expect(chat.turn).toBeNull();
  expect(chat.lastTurn?.outcome).toBe("done");
  expect(chat.lastTurn?.error).toBeUndefined();
  const act = chat.items.find((i) => i.kind === "activity");
  expect(act?.kind === "activity" && act.turn.outcome).toBe("done");
});

it("a thread cut off with no answer since still reads lost", async () => {
  const f = await started();
  await openThread(f);
  f.status("connecting");
  f.hermes.th1 = { running: false, messages: [{ id: "u1", role: "user", text: "build it", ts: 1 }] };
  f.status("open");
  await settle();
  expect(f.store.getState().chats[TH].lastTurn?.outcome).toBe("interrupted");
});

it("a message held in a running thread waits for the thread's re-read after a reconnect", async () => {
  const f = await started();
  await openThread(f);
  await f.store.actions.threadSend("kami", "th1", "and the tests");
  expect(f.store.getState().chats[TH].queue).toHaveLength(1);
  f.restartBridge();
  f.status("connecting");
  expect(f.store.getState().chats[TH].stale).toBe(true);
  f.status("open");
  await settle();
  const after = f.calls.slice(f.calls.map((c) => c.op).lastIndexOf("bots.list"));
  const send = after.findIndex((c) => c.op === "chat.send" && c.params.session === "th1");
  expect(send).toBeGreaterThan(after.findIndex((c) => c.op === "thread.open"));
  const chat = f.store.getState().chats[TH];
  expect(chat.queue ?? []).toEqual([]);
  expect(chat.items.some((i) => i.kind === "user" && i.text === "and the tests" && !!i.error)).toBe(false);
});

it("after omher starts again, a thread waiting on the person is read without a click and reaches Needs you", async () => {
  const f = fixture({ thread: { running: true, needs: true } });
  f.hermes.th1 = { running: true, messages: [{ id: "u1", role: "user", text: "clean up", ts: 1 }], ask: "ap9" };
  await f.store.actions.init();
  await settle();
  const chat = f.store.getState().chats[TH];
  expect(chat?.loaded).toBe(true);
  expect(chat.turn).not.toBeNull();
  expect(selectAsks(f.store.getState()).map((a) => [a.bot, a.item.request_id])).toEqual([[TH, "ap9"]]);
  expect(f.calls.filter((c) => c.op === "thread.open")).toHaveLength(1);
});

it("an idle thread is not read until it is opened", async () => {
  const f = await started();
  expect(f.calls.filter((c) => c.op === "thread.open")).toEqual([]);
  expect(f.store.getState().chats[TH]).toBeUndefined();
});
