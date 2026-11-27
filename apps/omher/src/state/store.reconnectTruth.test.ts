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
type Opts = {
  thread?: Thread;
  /** how many listed threads (th1, th2, ...) */ threads?: number;
  /** thread.open takes this long */ openMs?: number;
  /** the bot's name: an SSH bot's is `<peer>:<name>` */ bot?: string;
  /** thread.open is refused this many times first (the 48-open cap, a gateway timeout) */ openFails?: number;
};
type Held = {
  running: boolean;
  messages: { id: string; role: "user" | "assistant"; text: string; ts: number }[];
  ask?: string;
  clarify?: boolean;
  lost?: { id: string; text: string }[];
};

function fixture(o: Opts = {}) {
  let status!: (s: BridgeStatus) => void;
  let event!: (e: BridgeEvent) => void;
  const calls: { op: string; params: any }[] = [];
  // what Hermes holds now: per chat ("kami" or a thread id), whether its turn runs, its rows and a waiting ask
  const B = o.bot ?? "kami";
  let openFails = o.openFails ?? 0;
  const hermes: Record<string, Held> = { [B]: { running: false, messages: [] } };
  const ids = Array.from({ length: o.threads ?? 1 }, (_, n) => `th${n + 1}`);
  for (const t of ids) hermes[t] = { running: false, messages: [] };
  const opens = { now: 0, most: 0 }; // thread.open in flight now, and the most at once
  let listed = false; // a bridge started again knows no thread until thread.list listed it
  const row = (thread: string) => ({ thread, title: "Build", cwd: "/w", started_at: 1, running: false, needs: false, message_count: 1, ...o.thread });
  const replay = (bot: string, session?: string) => {
    const h = hermes[session ?? bot];
    const id = h.ask;
    const where = { bot, ...(session ? { session } : {}), request_id: id };
    // the bridge writes the reply frame first and replays after it: the event is a later frame
    if (id)
      setTimeout(() =>
        event(
          (h.clarify
            ? { event: "clarify.request", ...where, question: "Which environment?", choices: ["staging", "production"] }
            : { event: "approval.request", ...where, title: "Delete", command: "rm -rf build", choices: ["once", "deny"] }) as BridgeEvent,
        ),
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
        return { bots: [{ name: B, display_name: "Kami", is_default: true, model: "m", provider: "p", description: "", status: "online", running: false }] };
      if (op === "chat.open") {
        replay(B);
        return { session_id: "s-kami", messages: hermes[B].messages, running: hermes[B].running, lost: hermes[B].lost ?? [], model: "m", provider: "p", reasoning: "high" };
      }
      if (op === "thread.list") {
        await new Promise((r) => setTimeout(r, 20)); // Hermes' session.list takes a moment
        listed = true;
        return { threads: ids.map(row) };
      }
      if (op === "thread.open") {
        if (!listed) throw { code: "not_found", message: "no such thread" };
        if (openFails > 0) {
          openFails -= 1;
          throw { code: "busy", message: "Too many threads are open (48)" };
        }
        const t = params.thread as string;
        opens.now += 1;
        opens.most = Math.max(opens.most, opens.now);
        await new Promise((r) => setTimeout(r, o.openMs ?? 0));
        opens.now -= 1;
        replay(B, t);
        const h = hermes[t];
        return { thread: t, session_id: t, title: "Build", cwd: "/w", messages: h.messages, running: h.running, lost: h.lost ?? [], model: "m", provider: "p", reasoning: "" };
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
    opens,
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

async function started(o: Opts = {}) {
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
  await f.store.actions.threadSend("kami", "th1", "build it"); // the person's row that starts the turn
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

it("a thread whose transcript ends with an older answer (this turn's message not saved yet) still reads lost", async () => {
  const f = await started();
  await openThread(f);
  f.status("connecting");
  f.hermes.th1 = {
    running: false,
    messages: [
      { id: "u0", role: "user", text: "earlier question", ts: 1 },
      { id: "a0", role: "assistant", text: "earlier answer", ts: 2 },
    ],
  };
  await settle(5);
  f.status("open");
  await settle();
  expect(f.store.getState().chats[TH].lastTurn?.outcome).toBe("interrupted");
});

it("a thread whose turn Hermes recovered as lost still reads lost, though an answer is the last row", async () => {
  const f = await started();
  await openThread(f);
  f.status("connecting");
  f.hermes.th1 = {
    running: false,
    messages: [
      { id: "u1", role: "user", text: "build it", ts: 1 },
      { id: "a1", role: "assistant", text: "built", ts: Date.now() / 1000 },
    ],
    lost: [{ id: "l1", text: "build it" }],
  };
  await settle(5);
  f.status("open");
  await settle();
  expect(f.store.getState().chats[TH].lastTurn?.outcome).toBe("interrupted");
});

it("the main chat's turn that finished while the bridge was away reads done", async () => {
  const f = await started();
  f.event({ event: "turn.start", bot: "kami" } as BridgeEvent);
  f.status("connecting");
  expect(f.store.getState().chats.kami.lastTurn?.outcome).toBe("interrupted");
  await settle(5);
  f.hermes.kami = {
    running: false,
    messages: [
      { id: "u1", role: "user", text: "clean up", ts: Date.now() / 1000 - 1 },
      { id: "a1", role: "assistant", text: "cleaned", ts: Date.now() / 1000 },
    ],
  };
  f.status("open");
  await settle();
  const chat = f.store.getState().chats.kami;
  expect(chat.lastTurn?.outcome).toBe("done");
  expect(chat.lastTurn?.error).toBeUndefined();
});

it("a question still waiting after a reconnect comes back once, with its context row once", async () => {
  const f = await started();
  f.event({ event: "turn.start", bot: "kami" } as BridgeEvent);
  f.event({ event: "delta", bot: "kami", text: "Two places can take this." } as BridgeEvent);
  f.event({ event: "tool.start", bot: "kami", tool_id: "c1", name: "clarify", detail: "" } as BridgeEvent);
  f.event({ event: "clarify.request", bot: "kami", request_id: "cl1", question: "Which environment?", choices: ["staging", "production"] } as BridgeEvent);
  f.status("connecting");
  expect(selectAsks(f.store.getState())).toEqual([]);
  f.hermes.kami = { running: true, messages: [], ask: "cl1", clarify: true };
  await settle(5);
  f.status("open");
  await settle();
  expect(selectAsks(f.store.getState()).map((a) => [a.bot, a.item.request_id])).toEqual([["kami", "cl1"]]);
  const items = f.store.getState().chats.kami.items;
  expect(items.filter((i) => i.kind === "clarify")).toHaveLength(1);
  // the context row comes back with the card, once, right above it
  const notes = items.filter((i) => i.id === "clarify-note-cl1");
  expect(notes.map((i) => i.kind === "assistant" && i.text)).toEqual(["Two places can take this."]);
  expect(items.findIndex((i) => i.kind === "clarify")).toBe(items.indexOf(notes[0]) + 1);
  expect(new Set(items.map((i) => i.id)).size).toBe(items.length);
});

it("an unanswered card of a turn Hermes itself ended is not reopened by a later replay", async () => {
  const f = await started();
  f.event({ event: "turn.start", bot: "kami" } as BridgeEvent);
  f.event({ event: "approval.request", bot: "kami", request_id: "ap1", title: "Delete", command: "rm -rf build", choices: ["once", "deny"] } as BridgeEvent);
  await settle(5);
  f.event({ event: "turn.end", bot: "kami", outcome: "interrupted" } as BridgeEvent);
  await settle(5);
  f.event({ event: "turn.start", bot: "kami" } as BridgeEvent);
  f.event({ event: "approval.request", bot: "kami", request_id: "ap1", title: "Delete", command: "rm -rf build", choices: ["once", "deny"] } as BridgeEvent);
  expect(selectAsks(f.store.getState())).toEqual([]);
});

it("a click on a thread while its automatic open runs waits for it: one thread.open", async () => {
  const f = fixture({ thread: { running: true, needs: false }, openMs: 60 });
  f.hermes.th1 = { running: true, messages: [] };
  await f.store.actions.init();
  await settle(40); // thread.list answered; the automatic open is in flight
  expect(f.calls.filter((c) => c.op === "thread.open")).toHaveLength(1);
  await f.store.actions.openThread("kami", "th1");
  await settle();
  expect(f.calls.filter((c) => c.op === "thread.open")).toHaveLength(1);
  expect(f.store.getState().chats[TH].loaded).toBe(true);
});

it("busy threads are opened at most three at a time", async () => {
  const f = fixture({ thread: { running: true, needs: false }, threads: 7, openMs: 20 });
  await f.store.actions.init();
  await settle(300);
  expect(f.calls.filter((c) => c.op === "thread.open")).toHaveLength(7);
  expect(f.opens.most).toBe(3);
});

// An SSH bot is `<peer>:<name>` (bridge _peer_bots), so its thread's key is `fold:<peer>:<name>:<thread>`
const SSH = "p1:kami";
const SSH_TH = `fold:${SSH}:th1`;

it("an SSH bot's thread chat is read again after a reconnect, its held message after that read", async () => {
  const f = await started({ bot: SSH });
  await f.store.actions.openThread(SSH, "th1");
  await f.store.actions.threadSend(SSH, "th1", "build it");
  f.event({ event: "turn.start", bot: SSH, session: "th1" } as BridgeEvent);
  await f.store.actions.threadSend(SSH, "th1", "and the tests");
  expect(f.store.getState().chats[SSH_TH].queue).toHaveLength(1);
  f.restartBridge();
  f.status("connecting");
  expect(f.store.getState().chats[SSH_TH].stale).toBe(true);
  f.status("open");
  await settle();
  const after = f.calls.slice(f.calls.map((c) => c.op).lastIndexOf("bots.list"));
  const open = after.findIndex((c) => c.op === "thread.open" && c.params.bot === SSH && c.params.thread === "th1");
  expect(open).toBeGreaterThan(-1);
  expect(after.findIndex((c) => c.op === "chat.send" && c.params.session === "th1")).toBeGreaterThan(open);
  expect(f.store.getState().chats[SSH_TH].queue ?? []).toEqual([]);
});

it("an SSH bot's held thread message goes out when the turn ends, and Send now stops that thread", async () => {
  const f = await started({ bot: SSH });
  await f.store.actions.openThread(SSH, "th1");
  await f.store.actions.threadSend(SSH, "th1", "build it");
  f.event({ event: "turn.start", bot: SSH, session: "th1" } as BridgeEvent);
  await f.store.actions.threadSend(SSH, "th1", "and the tests");
  const id = f.store.getState().chats[SSH_TH].queue![0];
  await f.store.actions.queueSendNow(id, SSH_TH);
  expect(f.calls.filter((c) => c.op === "chat.interrupt").map((c) => c.params)).toEqual([{ bot: SSH, session: "th1" }]);
  f.event({ event: "turn.end", bot: SSH, session: "th1", outcome: "interrupted" } as BridgeEvent);
  await settle();
  expect(f.calls.filter((c) => c.op === "chat.send").map((c) => [c.params.bot, c.params.session, c.params.text])).toEqual([
    [SSH, "th1", "build it"],
    [SSH, "th1", "and the tests"],
  ]);
});

it("a thread whose automatic open failed opens again on a click", async () => {
  const f = fixture({ thread: { running: true, needs: false }, openFails: 1 });
  f.hermes.th1 = { running: true, messages: [{ id: "u1", role: "user", text: "build it", ts: 1 }] };
  await f.store.actions.init();
  await settle();
  expect(f.store.getState().chats[TH].openError).toBeTruthy();
  await f.store.actions.openThread("kami", "th1");
  expect(f.calls.filter((c) => c.op === "thread.open")).toHaveLength(2);
  const chat = f.store.getState().chats[TH];
  expect(chat.openError).toBeNull();
  expect(chat.turn).not.toBeNull();
});

it("two re-reads of a bot's threads at once open each read thread once", async () => {
  const f = await started({ openMs: 60 });
  await f.store.actions.openThread("kami", "th1");
  const before = f.calls.filter((c) => c.op === "thread.open").length;
  f.event({ event: "bot.restarted", bot: "kami", ok: true } as BridgeEvent);
  f.event({ event: "bot.restarted", bot: "kami", ok: true } as BridgeEvent);
  await settle(200);
  expect(f.calls.filter((c) => c.op === "thread.list").length).toBeGreaterThanOrEqual(3);
  expect(f.calls.filter((c) => c.op === "thread.open").length - before).toBe(1);
});
