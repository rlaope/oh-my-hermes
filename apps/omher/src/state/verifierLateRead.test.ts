// Steer queue (a bot's main chat): a message typed while a turn runs is steered into it at once (chat.steer, no
// interrupt). Where Hermes refuses the steer it is held in omher and goes out with chat.send when the turn ends, in
// order, exactly once; its ↵ buttons send it now (one interrupt), steer it again, edit or delete it. Holds across a
// reconnect, a bot switch and Stop.
import { afterEach, expect, it, vi } from "vitest";
import { CHAT_READ_MS, createStore, STEER_REPLY_MS, TURN_QUIET_MAX_MS, TURN_QUIET_MS, type BridgeLike, type Chat } from "./store";
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


it("a timed-out main chat recovery reply is ignored during the retry backoff, before the next open", async () => {
  const { f, a, chat } = await busy();
  vi.useFakeTimers();
  const original = f.bridge.request.bind(f.bridge);
  let release: (res: unknown) => void = () => { throw new Error("no pending chat.open"); };
  let attempts = 0;
  f.bridge.request = (async (op: string, p: Record<string, unknown>) => {
    if (op === "chat.open" && p.bot === "kami" && ++attempts === 1) return new Promise((r) => { release = r as (res: unknown) => void; });
    return (original as (o: string, p: Record<string, unknown>) => Promise<unknown>)(op, p);
  }) as BridgeLike["request"];
  await a.send("still waiting");
  await vi.advanceTimersByTimeAsync(TURN_QUIET_MS + CHAT_READ_MS + 1);
  expect(attempts).toBe(1);
  expect(f.sends()).toEqual([]);
  const model = chat().model;
  release({ session_id: "s-kami", messages: [], running: true, model: "expired-snapshot", provider: "p", reasoning: "high" });
  await vi.advanceTimersByTimeAsync(0);
  expect(attempts).toBe(1); // reply was delivered during backoff, not after another request
  expect(chat().model).toBe(model);
});
