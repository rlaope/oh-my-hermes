// #3123: after Hermes' gateway was killed mid-turn, the bot's main chat looked dead. Hermes had recovered the running
// turn as lost (`unknown`) and kept every later message of that chat in its queue until someone acknowledged it; omher
// showed "Read" under the new message, no answer, and lost the message from view after a restart. Now the chat shows
// it is paused (`lost`), a message sent meanwhile reads "Waiting", and Discard lets the waiting message run.
import { expect, it } from "vitest";
import { createStore, selectTimeline, type BridgeLike, type MessageItem } from "./store";
import type { BridgeEvent, LostTurn } from "../lib/protocol";

function fixture() {
  let event!: (e: BridgeEvent) => void;
  let lost: LostTurn[] = [{ id: "a1", text: "hello" }];
  let waiting: { id: string; role: "user"; text: string; ts: number; queued: true }[] = [];
  let refuse = false;
  const ran: { id: string; role: "user"; text: string; ts: number }[] = [];
  const calls: { op: string; params: any }[] = [];
  const bridge: BridgeLike = {
    connect: async () => {},
    onAny: (h) => {
      event = h;
      return () => {};
    },
    onStatus: () => () => {},
    request: (async (op: string, params: any) => {
      calls.push({ op, params });
      if (op === "hello") return { bridge: "mock", version: "test", hermes: { home: "/scratch" } };
      if (op === "bots.list")
        return { bots: [{ name: "kami", display_name: "Kami", is_default: false, model: "m", provider: "p", description: "", status: "online", running: false }] };
      if (op === "chat.open")
        return {
          session_id: "s-kami",
          messages: [{ id: "1", role: "user", text: "hello", ts: 100 }, ...ran, ...waiting],
          running: false,
          lost,
          model: "m",
          provider: "p",
          reasoning: "high",
        };
      if (op === "chat.send") {
        if (lost.length) waiting.push({ id: `q-a${waiting.length + 2}`, role: "user", text: params.text, ts: Date.now() / 1000, queued: true });
        return { input_id: "i1", ...(lost.length ? { paused: true } : {}) };
      }
      if (op === "chat.discard") {
        if (refuse) throw { code: "gateway_error", message: "session_busy" };
        const n = lost.length;
        lost = [];
        // what waited runs: it is in the transcript now, under its own row id
        ran.push(...waiting.map((w, k) => ({ id: `${10 + k}`, role: "user" as const, text: w.text, ts: w.ts })));
        waiting = [];
        return { discarded: n };
      }
      if (op === "elsewhere.list") return { sessions: [] };
      if (op === "routines.list") return { routines: [] };
      if (op === "automations.list") return { automations: [] };
      if (op === "thread.list") return { threads: [] };
      if (op === "models.options") return { providers: [], current: { model: "m", provider: "p", reasoning: "high" }, reasoning_levels: [] };
      return {};
    }) as BridgeLike["request"],
  };
  const store = createStore(bridge);
  return {
    store,
    calls,
    event: (e: BridgeEvent) => event(e),
    refuse: (r: boolean) => {
      refuse = r;
    },
  };
}
const settle = () => new Promise((r) => setTimeout(r, 30));
const users = (f: ReturnType<typeof fixture>) =>
  selectTimeline(f.store.getState(), "kami").filter((i): i is MessageItem => i.kind === "user");

it("a reopened chat with a lost turn is paused, and a message sent to it waits instead of reading Read", async () => {
  const f = fixture();
  await f.store.actions.init();
  await settle();
  expect(f.store.getState().chats.kami.lost).toEqual([{ id: "a1", text: "hello" }]);
  await f.store.actions.send("you there?");
  const sent = users(f).find((i) => i.text === "you there?")!;
  expect(sent.waiting).toBe(true);
  expect(sent.readAt).toBeUndefined();
});

it("a message still in Hermes' queue comes back on reopen, waiting, and not twice", async () => {
  const f = fixture();
  await f.store.actions.init();
  await settle();
  await f.store.actions.send("you there?");
  await f.store.actions.selectBot("kami");
  f.event({ event: "bot.restarted", bot: "kami", ok: true } as BridgeEvent); // re-read, as after a restart
  await settle();
  const rows = users(f).filter((i) => i.text === "you there?");
  expect(rows).toHaveLength(1);
  expect(rows[0].waiting).toBe(true);
  expect(rows[0].readAt).toBeUndefined();
});

it("Discard asks the bridge for that chat, reads it again, and the waiting message reads Read when its turn starts", async () => {
  const f = fixture();
  await f.store.actions.init();
  await settle();
  await f.store.actions.send("you there?");
  f.event({ event: "bot.restarted", bot: "kami", ok: true } as BridgeEvent); // a reopen first: the row comes from Hermes
  await settle();
  await f.store.actions.discardLost("kami");
  expect(f.calls.filter((c) => c.op === "chat.discard").map((c) => c.params)).toEqual([{ bot: "kami" }]);
  // its turn can start before the re-read answers: the Read copy of Hermes' queue row still goes on the next read
  f.event({ event: "turn.start", bot: "kami" } as BridgeEvent);
  f.event({ event: "turn.end", bot: "kami", outcome: "done" } as BridgeEvent);
  f.event({ event: "bot.restarted", bot: "kami", ok: true } as BridgeEvent);
  await settle();
  expect(f.store.getState().chats.kami.lost).toEqual([]);
  expect(users(f).filter((i) => i.text === "you there?")).toHaveLength(1); // now a transcript row, not twice
  f.event({ event: "turn.start", bot: "kami" } as BridgeEvent);
  const row = users(f).find((i) => i.text === "you there?")!;
  expect(row.waiting).toBeUndefined();
  expect(row.readAt).toBeGreaterThan(0);
  expect(f.store.getState().chats.kami.turn).not.toBeNull();
});

it("a refused Discard rejects and keeps the chat paused", async () => {
  const f = fixture();
  await f.store.actions.init();
  await settle();
  f.refuse(true);
  await expect(f.store.actions.discardLost("kami")).rejects.toMatchObject({ message: "session_busy" });
  expect(f.store.getState().chats.kami.lost).toEqual([{ id: "a1", text: "hello" }]);
});

it("a thread's Discard names that thread", async () => {
  const f = fixture();
  await f.store.actions.init();
  await settle();
  await f.store.actions.discardLost("kami", "stored-th-1").catch(() => {});
  expect(f.calls.filter((c) => c.op === "chat.discard").map((c) => c.params)).toEqual([{ bot: "kami", session: "stored-th-1" }]);
});
