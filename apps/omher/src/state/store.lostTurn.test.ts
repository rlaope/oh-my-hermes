// #3123: after Hermes' gateway was killed mid-turn, the bot's main chat looked dead. Hermes had recovered the running
// turn as lost (`unknown`) and kept every later message of that chat in its queue until someone acknowledged it; omher
// showed "Read" under the new message, no answer, and lost the message from view after a restart. Now the chat shows
// it is paused (`lost`), a message sent meanwhile reads "Waiting", and Discard lets the waiting message run.
import { expect, it } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createStore, folderKey, selectTimeline, type BridgeLike, type MessageItem } from "./store";
import type { BridgeEvent, LostTurn, Msg } from "../lib/protocol";
import { Bubble } from "../chat/parts/Bubble";

function fixture() {
  let event!: (e: BridgeEvent) => void;
  let lost: LostTurn[] = [{ id: "a1", text: "hello" }];
  let waiting: { id: string; role: "user"; text: string; ts: number; queued: true }[] = [];
  let refuse = false;
  let threads: unknown[] = [];
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
      if (op === "thread.list") return { threads };
      if (op === "models.options") return { providers: [], current: { model: "m", provider: "p", reasoning: "high" }, reasoning_levels: [] };
      return {};
    }) as BridgeLike["request"],
  };
  const store = createStore(bridge);
  return {
    store,
    calls,
    listThreads: (t: unknown[]) => {
      threads = t;
    },
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

// ---- review of #3127: a normal chat with a follow-up in Hermes' queue, the transcript's own times, events ----------

function normalChat() {
  let event!: (e: BridgeEvent) => void;
  let messages: Msg[] = [{ id: "1", role: "user", text: "first", ts: 100 }];
  let running = true;
  const bridge: BridgeLike = {
    connect: async () => {},
    onAny: (h) => {
      event = h;
      return () => {};
    },
    onStatus: () => () => {},
    request: (async (op: string) => {
      if (op === "hello") return { bridge: "mock", version: "test", hermes: { home: "/scratch" } };
      if (op === "bots.list")
        return { bots: [{ name: "kami", display_name: "Kami", is_default: false, model: "m", provider: "p", description: "", status: "online", running: true }] };
      if (op === "chat.open") return { session_id: "s-kami", messages, running, lost: [], model: "m", provider: "p", reasoning: "high" };
      if (op === "chat.send") return { input_id: "i1" };
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
    event: (e: BridgeEvent) => event(e),
    set: (m: Msg[], r: boolean) => {
      messages = m;
      running = r;
    },
  };
}
const userRows = (store: ReturnType<typeof createStore>, key = "kami") =>
  selectTimeline(store.getState(), key).filter((i): i is MessageItem => i.kind === "user");
const shown = (item: MessageItem, paused: boolean) => renderToStaticMarkup(createElement(Bubble, { item, last: true, paused }));

it("a follow-up queued behind a running turn, with nothing lost, says it runs after the current turn and is not Read", async () => {
  const f = normalChat();
  await f.store.actions.init();
  await new Promise((r) => setTimeout(r, 30));
  expect(f.store.getState().chats.kami.lost).toEqual([]);
  // sent with `queued` after the turn it was held for (its send.ok marked it Read), then read again from Hermes
  f.store.dispatch({ type: "local.user", bot: "kami", id: "local-9", text: "second", now: 101_000 });
  f.store.dispatch({ type: "send.ok", bot: "kami", id: "local-9", now: 101_500 });
  f.set([{ id: "1", role: "user", text: "first", ts: 100 }, { id: "q-a2", role: "user", text: "second", ts: 101.2, queued: true }], true);
  f.event({ event: "bot.restarted", bot: "kami", ok: true } as BridgeEvent);
  await new Promise((r) => setTimeout(r, 30));
  const rows = userRows(f.store).filter((i) => i.text === "second");
  expect(rows).toHaveLength(1);
  expect(rows[0].waiting).toBe(true);
  expect(rows[0].readAt).toBeUndefined(); // the local Read never moves onto Hermes' queue row
  const html = shown(rows[0], !!f.store.getState().chats.kami.lost?.length);
  expect(html).toContain("Waiting · runs after the current turn");
  expect(html).not.toContain("lost turn");
  expect(html).not.toContain("Read");
  expect(shown(rows[0], true)).toContain("Waiting · runs after the lost turn is discarded");
});

it("a row still in Hermes' queue does not decide which local rows the transcript holds", async () => {
  const f = normalChat();
  await f.store.actions.init();
  await new Promise((r) => setTimeout(r, 30));
  // an answer that came live after the transcript's last row, and a queue row Hermes stamped later than it
  f.store.dispatch({ type: "event", ev: { event: "message", bot: "kami", id: "live-1", text: "the live answer" } as BridgeEvent, now: 150_000 });
  f.set([{ id: "1", role: "user", text: "first", ts: 100 }, { id: "q-a2", role: "user", text: "second", ts: 900, queued: true }], true);
  f.event({ event: "bot.restarted", bot: "kami", ok: true } as BridgeEvent);
  await new Promise((r) => setTimeout(r, 30));
  expect(selectTimeline(f.store.getState(), "kami").some((i) => i.kind === "assistant" && i.text === "the live answer")).toBe(true);
});

it("Hermes saying the lost turns changed (chat.lost) updates the open chat, a folder chat's too", async () => {
  const f = fixture();
  await f.store.actions.init();
  await settle();
  f.event({ event: "chat.lost", bot: "kami", lost: [] } as BridgeEvent);
  expect(f.store.getState().chats.kami.lost).toEqual([]);
  f.event({ event: "chat.lost", bot: "kami", lost: [{ id: "a5", text: "x" }] } as BridgeEvent);
  expect(f.store.getState().chats.kami.lost).toEqual([{ id: "a5", text: "x" }]);
  // a folder chat (not a thread) is not read again after its Discard: its note goes at once
  f.store.dispatch({ type: "chat.opened", bot: folderKey("kami", "f1"), res: { session_id: "f1", messages: [], running: false, lost: [{ id: "b1", text: "y" }], model: "m", provider: "p", reasoning: "" }, now: 1 });
  await f.store.actions.discardLost("kami", "f1");
  expect(f.calls.filter((c) => c.op === "chat.discard").at(-1)?.params).toEqual({ bot: "kami", session: "f1" });
  expect(f.store.getState().chats[folderKey("kami", "f1")].lost).toEqual([]);
});

it("a bot that comes back re-reads its threads that were open, not only its main chat", async () => {
  const f = fixture();
  await f.store.actions.init();
  await settle();
  const row = { thread: "th1", title: "t", cwd: "/w", started_at: 1, running: false, needs: false, message_count: 0 };
  f.listThreads([row]); // the bridge lists it again first (store.resyncThreads.test.ts)
  f.store.dispatch({ type: "threads", bot: "kami", threads: [row] });
  f.store.dispatch({ type: "chat.opened", bot: "fold:kami:th1", res: { session_id: "th1", messages: [], running: false, model: "m", provider: "p", reasoning: "" }, now: 1 });
  f.event({ event: "bot.restarted", bot: "kami", ok: true } as BridgeEvent);
  await settle();
  expect(f.calls.filter((c) => c.op === "thread.open").map((c) => c.params)).toEqual([{ bot: "kami", thread: "th1" }]);
});
