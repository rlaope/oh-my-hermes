// Steer queue (a bot's main chat): a message typed while a turn runs is steered into it at once (chat.steer, no
// interrupt). Where Hermes refuses the steer it is held in omher and goes out with chat.send when the turn ends, in
// order, exactly once; its ↵ buttons send it now (one interrupt), steer it again, edit or delete it. Holds across a
// reconnect, a bot switch and Stop.
import { afterEach, expect, it, vi } from "vitest";
import { createStore, STEER_REPLY_MS, TURN_QUIET_MAX_MS, TURN_QUIET_MS, type BridgeLike, type Chat } from "./store";
import type { BridgeEvent } from "../lib/protocol";
import type { BridgeStatus } from "../lib/bridge";

const T0 = 1_800_000_000_000;
afterEach(() => vi.useRealTimers());

const tick = () => new Promise((r) => setTimeout(r, 0));

function fake() {
  let anyH: ((ev: BridgeEvent) => void) | null = null;
  let statusH: ((s: BridgeStatus) => void) | null = null;
  const calls: { op: string; params: Record<string, unknown> }[] = [];
  let running = false;
  let steer: "queued" | "rejected" | "uncertain" | "throw" | "disconnected" | "bot_offline" | "timeout" | "internal" = "queued";
  let botsFail = false;
  const bridge: BridgeLike = {
    connect: async () => statusH?.("open"),
    onAny: (h) => ((anyH = h), () => {}),
    onStatus: (h) => ((statusH = h), () => {}),
    request: (async (op: string, params: Record<string, unknown>) => {
      calls.push({ op, params });
      switch (op) {
        case "hello":
          return { bridge: "mock", version: "0", hermes: { home: "/h" } };
        case "bots.list":
          if (botsFail) throw { code: "disconnected", message: "bridge connection lost" };
          return { bots: ["kami", "friren"].map((name) => ({ name, display_name: name, is_default: false, model: "m", provider: "p", description: "", status: "online", running: false })) };
        case "chat.open":
          return { session_id: `s-${params.bot}`, messages: [], running, model: "m", provider: "p", reasoning: "high" };
        case "elsewhere.list":
          return { sessions: [] };
        case "routines.list":
          return { routines: [] };
        case "models.options":
          return { providers: [], current: { model: "m", provider: "p", reasoning: "high" }, reasoning_levels: [] };
        case "chat.send":
          return { input_id: "i" };
        case "chat.steer":
          if (steer === "throw") throw { code: "gateway_error", message: "agent does not support steer" };
          if (steer !== "queued" && steer !== "rejected" && steer !== "uncertain") throw { code: steer, message: "no answer" };
          return { status: steer };
        default:
          return {};
      }
    }) as BridgeLike["request"],
  };
  return {
    bridge,
    calls,
    emit: (ev: BridgeEvent) => anyH!(ev),
    status: (s: BridgeStatus) => statusH!(s),
    setRunning: (r: boolean) => (running = r),
    setSteer: (s: typeof steer) => (steer = s),
    setBotsFail: (v: boolean) => (botsFail = v),
    sends: (bot = "kami") => calls.filter((c) => c.op === "chat.send" && c.params.bot === bot).map((c) => c.params.text),
    count: (op: string) => calls.filter((c) => c.op === op).length,
  };
}

/** A store on kami with a turn running, whose steers Hermes refuses: what is typed waits (the fallback). */
async function busy() {
  const f = fake();
  f.setSteer("rejected");
  // a clock that moves: a chat.open asked after a turn ended is newer than that end (applyOpened's `since`)
  let clock = T0;
  const store = createStore(f.bridge, { now: () => (clock += 10) });
  await store.actions.init();
  f.emit({ event: "turn.start", bot: "kami" });
  return { f, store, a: store.actions, chat: () => store.getState().chats.kami };
}
const heldOf = (c: Chat) => c.items.flatMap((i) => (i.kind === "user" && i.held ? [i.text] : []));
const turn = async (f: ReturnType<typeof fake>, outcome: "done" | "interrupted" = "done") => {
  f.emit({ event: "turn.end", bot: "kami", outcome });
  await tick();
  await tick();
};


it("lost chat.steer reply leaves an auto-steered row with no visible hold/uncertain marker even after turn.end", async () => {
  const { f, a, chat } = await busy();
  const real = f.bridge.request;
  f.bridge.request = ((op: string, p: Record<string, unknown>) => {
    if (op !== "chat.steer") return (real as (o: string, p: Record<string, unknown>) => Promise<unknown>)(op, p);
    f.calls.push({op, params:p});
    return new Promise(() => {});
  }) as BridgeLike["request"];
  await a.send("no ack");
  await turn(f);
  expect(f.count("chat.steer")).toBe(1);
  expect(f.sends()).toEqual([]);
  const row = chat().items.find((i) => i.kind === "user" && i.text === "no ack");
  expect(row).toMatchObject({held:true});
  if (row?.kind !== 'user') throw new Error('missing user row');
  const visiblyHeld = !!row.held && !row.autoSteer;
  expect(visiblyHeld || !!row.steerUnknown || !!row.error, JSON.stringify({autoSteer:row.autoSteer, steering:chat().steering, held:row.held})).toBe(true);
});

it("answered approval then dropped turn.end with the socket still open must not leave the follow-up queued indefinitely", async () => {
  const { f, a, chat } = await busy();
  f.emit({event:"approval.request",bot:"kami",request_id:"a",title:"Test approval",choices:["once","deny"]} as BridgeEvent);
  await a.respondApproval("a", "once", "kami");
  f.setRunning(false);
  vi.useFakeTimers();
  await a.send("after end was dropped");
  // the turn says nothing more: after the quiet time the chat is read again, Hermes runs nothing, the message goes
  await vi.advanceTimersByTimeAsync(TURN_QUIET_MS);
  expect(f.count("approval.respond")).toBe(1);
  expect(f.sends(), JSON.stringify({turn:!!chat().turn, stale:chat().stale, held:chat().queue})).toEqual(["after end was dropped"]);
});

it("nothing held: no re-read however long the turn is quiet (no polling while idle)", async () => {
  const { f } = await busy();
  vi.useFakeTimers();
  const opens = f.count("chat.open");
  await vi.advanceTimersByTimeAsync(TURN_QUIET_MAX_MS * 3);
  expect(f.count("chat.open")).toBe(opens);
});

it("held behind a quiet turn Hermes still runs: it stays held, read again after a doubling quiet time, then goes", async () => {
  const { f, a, chat } = await busy();
  vi.useFakeTimers();
  f.setRunning(true);
  await a.send("wait for it");
  const opens = f.count("chat.open");
  await vi.advanceTimersByTimeAsync(TURN_QUIET_MS - 1);
  expect(f.count("chat.open")).toBe(opens);
  // a turn event starts the wait over
  f.emit({ event: "thinking", bot: "kami", text: "still on it" } as BridgeEvent);
  await vi.advanceTimersByTimeAsync(TURN_QUIET_MS - 1);
  expect(f.count("chat.open")).toBe(opens);
  await vi.advanceTimersByTimeAsync(1);
  expect(f.count("chat.open")).toBe(opens + 1);
  expect(f.sends()).toEqual([]);
  expect(chat().turn).toBeTruthy();
  expect(heldOf(chat())).toEqual(["wait for it"]);
  // still running: the next read waits twice as long
  await vi.advanceTimersByTimeAsync(TURN_QUIET_MS * 2 - 1);
  expect(f.count("chat.open")).toBe(opens + 1);
  f.setRunning(false);
  await vi.advanceTimersByTimeAsync(1);
  expect(f.count("chat.open")).toBe(opens + 2);
  expect(f.sends()).toEqual(["wait for it"]);
  // sent and nothing held: the watch is over
  await vi.advanceTimersByTimeAsync(TURN_QUIET_MAX_MS * 3);
  expect(f.count("chat.open")).toBe(opens + 2);
});

it("a steer with no reply: after its deadline the row is unknown and held, steering is clear, never resent", async () => {
  const { f, a, chat } = await busy();
  vi.useFakeTimers();
  const real = f.bridge.request;
  f.bridge.request = ((op: string, p: Record<string, unknown>) => {
    if (op !== "chat.steer") return (real as (o: string, p: Record<string, unknown>) => Promise<unknown>)(op, p);
    f.calls.push({ op, params: p });
    return new Promise(() => {});
  }) as BridgeLike["request"];
  f.setSteer("queued");
  await a.send("no reply");
  expect(chat().steering).toBeTruthy();
  await vi.advanceTimersByTimeAsync(STEER_REPLY_MS);
  const row = chat().items.find((i) => i.kind === "user" && i.text === "no reply");
  expect(row).toMatchObject({ held: true, steerUnknown: true });
  expect(row && "autoSteer" in row && row.autoSteer).toBeFalsy();
  expect(chat().steering).toBeNull();
  f.emit({ event: "turn.end", bot: "kami", outcome: "done" });
  await vi.advanceTimersByTimeAsync(TURN_QUIET_MS);
  expect(f.sends()).toEqual([]);
  expect(f.count("chat.steer")).toBe(1);
});

it("held when the link drops and the reconnect's re-read is lost: the watch reads the chat again and it goes out", async () => {
  const { f, a } = await busy();
  vi.useFakeTimers();
  await a.send("after the link is back");
  f.status("closed");
  f.setRunning(false);
  const opens = f.count("chat.open");
  await vi.advanceTimersByTimeAsync(TURN_QUIET_MS);
  expect(f.count("chat.open")).toBe(opens);
  // back up, its own re-read lost: the watch still reads the chat and the message goes out
  f.setBotsFail(true);
  f.status("open");
  await vi.advanceTimersByTimeAsync(TURN_QUIET_MAX_MS);
  expect(f.sends()).toEqual(["after the link is back"]);
});
