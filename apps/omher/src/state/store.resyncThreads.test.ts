// Follow-up to #3127: after the bridge was started again (a revive), the page reconnects and re-reads its chats. A new
// bridge knows no thread until `thread.list` has listed it and answers `thread.open` of one before then with
// not_found. The re-read of an open thread ran beside `thread.list`, lost that race, and left a false "not reachable"
// line on the thread (and its lost turn unseen). It now waits for `thread.list`.
import { expect, it } from "vitest";
import { createStore, type BridgeLike } from "./store";
import type { BridgeEvent } from "../lib/protocol";
import type { BridgeStatus } from "../lib/bridge";

const THREAD = { thread: "th1", title: "Build", cwd: "/w", started_at: 1, running: false, needs: false, message_count: 0 };

function fixture() {
  let status!: (s: BridgeStatus) => void;
  let event!: (e: BridgeEvent) => void;
  let listed = false; // the bridge has listed the thread (a new bridge process has not, until thread.list answers)
  const calls: string[] = [];
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
    request: (async (op: string) => {
      calls.push(op);
      if (op === "hello") return { bridge: "mock", version: "test", hermes: { home: "/scratch" } };
      if (op === "bots.list")
        return { bots: [{ name: "kami", display_name: "Kami", is_default: false, model: "m", provider: "p", description: "", status: "online", running: false }] };
      if (op === "chat.open") return { session_id: "s-kami", messages: [], running: false, lost: [], model: "m", provider: "p", reasoning: "high" };
      if (op === "thread.list") {
        await new Promise((r) => setTimeout(r, 20)); // Hermes' session.list takes a moment
        listed = true;
        return { threads: [THREAD] };
      }
      if (op === "thread.open") {
        if (!listed) throw { code: "not_found", message: "no such thread" };
        return { thread: "th1", session_id: "th1", title: "Build", cwd: "/w", messages: [], running: false, lost: [{ id: "a1", text: "build it" }], model: "m", provider: "p", reasoning: "" };
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
    status: (s: BridgeStatus) => status(s),
    event: (e: BridgeEvent) => event(e),
    restartBridge: () => {
      listed = false;
    },
  };
}
const settle = (ms = 80) => new Promise((r) => setTimeout(r, ms));

async function withOpenThread() {
  const f = fixture();
  await f.store.actions.init();
  f.status("open");
  await settle();
  await f.store.actions.openThread("kami", "th1");
  expect(f.store.getState().chats["fold:kami:th1"].loaded).toBe(true);
  return f;
}

it("a reconnect to a bridge started again reads the open thread only after thread.list, with no false error", async () => {
  const f = await withOpenThread();
  f.restartBridge();
  f.status("connecting");
  f.status("open"); // resync
  await settle();
  const chat = f.store.getState().chats["fold:kami:th1"];
  expect(chat.openError ?? null).toBeNull();
  expect(chat.lost).toEqual([{ id: "a1", text: "build it" }]);
  const order = f.calls.slice(f.calls.lastIndexOf("bots.list"));
  expect(order.indexOf("thread.list")).toBeLessThan(order.lastIndexOf("thread.open"));
});

it("a restarted bot lists its threads again before it reads the open one", async () => {
  const f = await withOpenThread();
  f.restartBridge();
  const before = f.calls.length;
  f.event({ event: "bot.restarted", bot: "kami", ok: true } as BridgeEvent);
  await settle();
  expect(f.store.getState().chats["fold:kami:th1"].openError ?? null).toBeNull();
  expect(f.calls.slice(before).filter((c) => c.startsWith("thread."))).toEqual(["thread.list", "thread.open"]);
});
