// A bot's gateway that went away without omher restarting it (`hermes update` pausing it, a crash and relaunch, a
// restart from a terminal) comes back as `bot.restarted`, which the bridge now sends for that too. The open chat
// then reads its history again and drops the error it showed while the gateway was away: the 2026-11-21 run showed
// only the message sent after the update and kept "Kami is not reachable (… Gateway draining: update_paused)".
import { expect, it } from "vitest";
import { createStore, selectTimeline, type BridgeLike } from "./store";
import type { BridgeEvent } from "../lib/protocol";

const HISTORY = [
  { id: "m1", role: "user", text: "earlier question", ts: 100 },
  { id: "m2", role: "assistant", text: "earlier answer", ts: 101 },
];

function fixture() {
  let event!: (e: BridgeEvent) => void;
  let draining = false;
  let messages = HISTORY;
  const calls: string[] = [];
  const bridge: BridgeLike = {
    connect: async () => {},
    onAny: (h) => {
      event = h;
      return () => {};
    },
    onStatus: () => () => {},
    request: (async (op: string, params: any) => {
      calls.push(`${op}:${params?.bot ?? ""}`);
      if (op === "hello") return { bridge: "mock", version: "test", hermes: { home: "/scratch" } };
      if (op === "bots.list")
        return { bots: [{ name: "kami", display_name: "Kami", is_default: false, model: "m", provider: "p", description: "", status: "online", running: false }] };
      if (op === "chat.open") {
        if (draining) throw { code: "bot_offline", message: "kami is offline: Gateway draining: update_paused" };
        return { session_id: "s-kami", messages, running: false, model: "m", provider: "p", reasoning: "high" };
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
    draining: (d: boolean) => {
      draining = d;
    },
    messages: (m: typeof HISTORY) => {
      messages = m;
    },
  };
}
const settle = () => new Promise((r) => setTimeout(r, 30));
const texts = (f: ReturnType<typeof fixture>) =>
  selectTimeline(f.store.getState(), "kami").flatMap((i) => (i.kind === "user" || i.kind === "assistant" ? [i.text] : []));

it("a chat first opened while the gateway drained loads its history and drops the error once the bot is back", async () => {
  const f = fixture();
  f.draining(true);
  await f.store.actions.init();
  await settle();
  expect(f.store.getState().chats.kami.openError).toContain("update_paused");
  expect(texts(f)).toEqual([]);
  f.draining(false);
  f.event({ event: "bot.status", bot: "kami", status: "online", running: false } as BridgeEvent);
  f.event({ event: "bot.restarted", bot: "kami", ok: true } as BridgeEvent);
  await settle();
  expect(f.store.getState().chats.kami.openError).toBeNull();
  expect(texts(f)).toEqual(["earlier question", "earlier answer"]);
});

it("an open chat re-reads after its gateway came back, with no row twice", async () => {
  const f = fixture();
  await f.store.actions.init();
  await settle();
  expect(texts(f)).toEqual(["earlier question", "earlier answer"]);
  f.event({ event: "bot.status", bot: "kami", status: "offline", running: false } as BridgeEvent);
  // what the bot said while omher was not attached is in the history it reads again
  f.messages([...HISTORY, { id: "m3", role: "user", text: "sent from Slack meanwhile", ts: 102 }, { id: "m4", role: "assistant", text: "answered", ts: 103 }]);
  f.event({ event: "bot.status", bot: "kami", status: "online", running: false } as BridgeEvent);
  f.event({ event: "bot.restarted", bot: "kami", ok: true } as BridgeEvent);
  await settle();
  expect(texts(f)).toEqual(["earlier question", "earlier answer", "sent from Slack meanwhile", "answered"]);
});
