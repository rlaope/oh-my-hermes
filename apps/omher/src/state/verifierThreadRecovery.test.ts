import { afterEach, expect, it, vi } from "vitest";
import { createStore, TURN_QUIET_MAX_MS, type BridgeLike } from "./store";
import type { BridgeEvent } from "../lib/protocol";
import type { BridgeStatus } from "../lib/bridge";

const KEY = "fold:kami:th1";
afterEach(() => vi.useRealTimers());

async function fixture() {
  let onStatus!: (s: BridgeStatus) => void;
  let onEvent!: (e: BridgeEvent) => void;
  const opened: { calls: number; drop: number | null; running: boolean } = { calls: 0, drop: null, running: false };
  const sends: unknown[] = [];
  let lists = 0;
  const bridge: BridgeLike = {
    connect: async () => onStatus("open"),
    onStatus: (fn) => ((onStatus = fn), () => {}),
    onAny: (fn) => ((onEvent = fn), () => {}),
    request: (async (op: string, p: Record<string, unknown>) => {
      switch (op) {
        case "hello": return { bridge: "mock", version: "0", hermes: { home: "/scratch" } };
        case "bots.list": return { bots: [{ name: "kami", display_name: "Kami", is_default: true, status: "online", running: false }] };
        case "chat.open": return { session_id: "main", messages: [], running: false };
        case "thread.list":
          lists += 1;
          return { threads: [{ thread: "th1", title: "Thread", cwd: "/w", started_at: 1, running: opened.running, needs: false, message_count: 1 }] };
        case "thread.open":
          if (++opened.calls === opened.drop) return new Promise(() => {});
          return { thread: "th1", title: "Thread", messages: [], running: opened.running, cwd: "/w" };
        case "chat.send": sends.push(p); return { input_id: "i" };
        case "chat.steer": return { status: "rejected" };
        case "elsewhere.list": return { sessions: [] };
        case "routines.list": return { routines: [] };
        case "automations.list": return { automations: [] };
        default: return {};
      }
    }) as BridgeLike["request"],
  };
  let stamp = 1_800_000_000_000;
  const { actions, getState } = createStore(bridge, { now: () => (stamp += 10) });
  await actions.init();
  await actions.loadThreads("kami");
  await actions.openThread("kami", "th1");
  expect(getState().chats[KEY].loaded).toBe(true);
  expect(opened.calls).toBe(1);
  onEvent({ event: "turn.start", bot: "kami", session: "th1" } as BridgeEvent);
  expect(getState().chats[KEY].turn).not.toBeNull();
  return { actions, getState, opened, sends, lists: () => lists, onEvent, onStatus };
}

it.each([
  { reconnect: false, drop: false }, { reconnect: false, drop: true },
  { reconnect: true, drop: false }, { reconnect: true, drop: true },
])("a held thread follow-up recovers with reconnect=$reconnect and first recovery reply lost=$drop", async ({ reconnect, drop }) => {
  const f = await fixture();
  vi.useFakeTimers();
  if (drop) f.opened.drop = 2;
  await f.actions.threadSend("kami", "th1", "thread follow-up");
  await vi.advanceTimersByTimeAsync(0);
  expect(f.getState().chats[KEY].queue).toHaveLength(1);
  // Hermes is idle but no turn.end was delivered. With reconnect, the initial read
  // is resync's; without it, the queue's quiet-turn watchdog starts it.
  if (reconnect) {
    f.onStatus("connecting");
    f.onStatus("open");
  }
  await vi.advanceTimersByTimeAsync(TURN_QUIET_MAX_MS * 3);
  const c = f.getState().chats[KEY];
  expect(f.getState().conn).toBe("open");
  expect(f.sends, JSON.stringify({ opens: f.opened.calls, lists: f.lists(), stale: c.stale, turn: !!c.turn, queue: c.queue }))
    .toEqual([expect.objectContaining({ bot: "kami", session: "th1", text: "thread follow-up" })]);
});
