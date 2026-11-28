// A message typed in a bot's main chat goes out after the bridge dropped and came back (a Mac's sleep and wake),
// even when the reconnect's re-read failed. The drop marks the chat stale (what Hermes runs is unknown until it is
// read again) and a stale chat holds every message; the reconnect's bots.list failing (the socket flapping on wake)
// left it stale for good, so every later message waited behind a re-read that never came: Enter and Send did nothing
// the person could see go out.
import { expect, it } from "vitest";
import { createStore, type BridgeLike } from "./store";
import type { BridgeStatus } from "../lib/bridge";

const T0 = 1_800_000_000_000;
const tick = () => new Promise((r) => setTimeout(r, 0));
const ticks = async (n = 8) => {
  for (let i = 0; i < n; i++) await tick();
};

function fake() {
  let statusH: ((s: BridgeStatus) => void) | null = null;
  const calls: { op: string; params: Record<string, unknown> }[] = [];
  let botsFail = false;
  const bridge: BridgeLike = {
    connect: async () => statusH?.("open"),
    onAny: () => () => {},
    onStatus: (h) => ((statusH = h), () => {}),
    request: (async (op: string, params: Record<string, unknown>) => {
      calls.push({ op, params });
      switch (op) {
        case "hello":
          return { bridge: "mock", version: "0", hermes: { home: "/h" } };
        case "bots.list":
          if (botsFail) throw { code: "disconnected", message: "bridge connection lost" };
          return { bots: [{ name: "kami", display_name: "Kami", is_default: true, model: "m", provider: "p", description: "", status: "online", running: false }] };
        case "chat.open":
          return { session_id: "s-kami", messages: [], running: false, model: "m", provider: "p", reasoning: "high" };
        case "elsewhere.list":
          return { sessions: [] };
        case "routines.list":
          return { routines: [] };
        case "models.options":
          return { providers: [], current: { model: "m", provider: "p", reasoning: "high" }, reasoning_levels: [] };
        case "chat.send":
          return { input_id: "i" };
        default:
          return {};
      }
    }) as BridgeLike["request"],
  };
  return {
    bridge,
    status: (s: BridgeStatus) => statusH!(s),
    setBotsFail: (v: boolean) => (botsFail = v),
    sends: () => calls.filter((c) => c.op === "chat.send").map((c) => c.params.text),
    opens: () => calls.filter((c) => c.op === "chat.open").length,
  };
}

/** Kami idle and read; then sleep and wake, where the reconnect's bots.list is lost with a second flap. */
async function afterFailedWake() {
  const f = fake();
  let clock = T0;
  const store = createStore(f.bridge, { now: () => (clock += 10) });
  await store.actions.init();
  f.setBotsFail(true);
  f.status("closed");
  f.status("open");
  await ticks();
  f.setBotsFail(false);
  return { f, store, chat: () => store.getState().chats.kami };
}

it("after a wake whose re-read failed, a typed message still goes out (no bots.update needed)", async () => {
  const { f, store, chat } = await afterFailedWake();
  expect(chat().stale).toBe(true);
  await store.actions.send("야");
  await ticks();
  expect(f.sends()).toEqual(["야"]);
  expect(chat().stale).toBe(false);
  expect(chat().queue ?? []).toEqual([]);
});

it("the stale chat is read again once for a burst of messages, which then go out in order", async () => {
  const { f, store, chat } = await afterFailedWake();
  const before = f.opens();
  await store.actions.send("one");
  await store.actions.send("two");
  await ticks();
  expect(f.opens() - before).toBe(1);
  // "two" waits behind the turn "one" starts, as any message typed during a turn
  expect(f.sends()).toEqual(["one"]);
  expect(chat().queue?.length).toBe(1);
});

it("while the bridge is still away nothing is re-read; the message waits and goes out once it is back", async () => {
  const { f, store, chat } = await afterFailedWake();
  f.status("closed");
  const before = f.opens();
  await store.actions.send("later");
  await ticks();
  expect(f.opens()).toBe(before);
  expect(f.sends()).toEqual([]);
  expect(chat().queue?.length).toBe(1);
  f.status("open");
  await ticks(12);
  expect(f.sends()).toEqual(["later"]);
});
