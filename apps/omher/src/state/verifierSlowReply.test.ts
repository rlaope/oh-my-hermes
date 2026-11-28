import { afterEach, expect, it, vi } from "vitest";
// Parent note: the verifier wrote these against CHAT_READ_MS = 20 s. Its scenario is "a valid answer at 25 s, inside
// Hermes' 30 s RPC limit"; the times are pinned to that literal scenario so the test does not move with the constant.
const HERMES_RPC_MS = 30_000;
const VALID_REPLY_MS = 25_000;
import { CHAT_READ_MS, createStore, TURN_QUIET_MS, type BridgeLike } from "./store";
import type { BridgeEvent } from "../lib/protocol";
import type { BridgeStatus } from "../lib/bridge";

const bot = "kami", thread = "th1", key = `fold:${bot}:${thread}`;
const snap = (model: string, running = false) => ({ session_id: "main", messages: [], running, model });
const threadSnap = (model: string) => ({ thread, title: "Listed thread", messages: [], running: false, model, cwd: "/fixture" });
const defer = () => {
  let resolve!: (r: unknown) => void, reject!: (e: unknown) => void;
  const promise = new Promise<unknown>((ok, error) => { resolve = ok; reject = error; });
  return { promise, resolve, reject };
};
afterEach(() => vi.useRealTimers());

async function setup() {
  let status!: (s: BridgeStatus) => void, event!: (e: BridgeEvent) => void;
  const threads: ReturnType<typeof defer>[] = [], mains: ReturnType<typeof defer>[] = [];
  const sends: Record<string, unknown>[] = [];
  let holdMain = false;
  let threadAutoMs: number | undefined;
  let threadAnswers = 0;
  const bridge: BridgeLike = {
    connect: async () => status("open"),
    onStatus: (fn) => { status = fn; return () => {}; },
    onAny: (fn) => { event = fn; return () => {}; },
    request: (async (op: string, p: Record<string, unknown>) => {
      switch (op) {
        case "hello": return { bridge: "mock", version: "0", hermes: { home: "/fixture" } };
        case "bots.list": return { bots: [{ name: bot, display_name: "Mock", model: "initial", is_default: true, status: "online", running: false }] };
        case "chat.open": {
          if (!holdMain) return snap("initial");
          const d = defer(); mains.push(d); return d.promise;
        }
        case "thread.list": return { threads: [{ thread, title: "Listed thread", cwd: "/fixture", started_at: 1, running: false, needs: false, message_count: 1 }] };
        case "thread.open": {
          const d = defer(); threads.push(d);
          if (threadAutoMs !== undefined) setTimeout(() => { threadAnswers++; d.resolve(threadSnap("polled-idle")); }, threadAutoMs);
          return d.promise;
        }
        case "chat.steer": return { status: "rejected" };
        case "chat.send": sends.push(p); return { input_id: "mock-input" };
        case "elsewhere.list": return { sessions: [] };
        case "routines.list": return { routines: [] };
        case "automations.list": return { automations: [] };
        default: return {};
      }
    }) as BridgeLike["request"],
  };
  let now = 1_800_000_000_000;
  const { actions: a, getState } = createStore(bridge, { now: () => (now += 10) });
  await a.init();
  await a.loadThreads(bot);
  vi.useFakeTimers();
  return { a, getState, threads, mains, sends, threadChat: () => getState().chats[key], mainChat: () => getState().chats[bot], busy() { holdMain = true; event({ event: "turn.start", bot }); }, threadBusy(ms: number) { threadAutoMs = ms; event({ event: "turn.start", bot, session: thread } as BridgeEvent); }, threadAnswers: () => threadAnswers };
}

it("a held thread follow-up leaves once valid idle replies arrive at 25s", async () => {
  const f = await setup();
  const first = f.a.openThread(bot, thread);
  f.threads[0].resolve(threadSnap("initial"));
  await first;
  f.threadBusy(VALID_REPLY_MS);
  await f.a.threadSend(bot, thread, "send after quiet turn");
  await vi.advanceTimersByTimeAsync(180_000);
  const c = f.threadChat();
  console.log("slow idle replies", { opens: f.threads.length, validIdleReplies: f.threadAnswers(), sends: f.sends.length, queue: c.queue, turn: !!c.turn });
  expect(f.threadAnswers()).toBeGreaterThan(0);
  expect(f.sends, "valid idle replies are still being dropped").toEqual([expect.objectContaining({ bot, session: thread, text: "send after quiet turn" })]);
});

it("cold click must not leave a thread stuck Loading after a valid answer at 25s", async () => {
  const f = await setup();
  void f.a.openThread(bot, thread);
  expect(f.threads).toHaveLength(1);
  await vi.advanceTimersByTimeAsync(VALID_REPLY_MS);
  f.threads[0].resolve(threadSnap("answered-at-25s"));
  await vi.advanceTimersByTimeAsync(3 * CHAT_READ_MS);
  const c = f.threadChat();
  console.log("cold click", { opens: f.threads.length, loaded: c?.loaded ?? false, error: c?.openError ?? null, model: c?.model ?? null, selected: f.getState().ui.thread });
  expect(f.getState().ui.thread).toBe(thread);
  expect(!!c?.loaded || !!c?.openError, "neither the returned history nor an error is shown").toBe(true);
});

it("retry click still opens after a given-up cold request and a refused retry", async () => {
  const f = await setup();
  const first = f.a.openThread(bot, thread);
  await vi.advanceTimersByTimeAsync(CHAT_READ_MS + 1);
  expect(f.threads).toHaveLength(1);
  await first;
  const second = f.a.openThread(bot, thread);
  expect(f.threads).toHaveLength(2);
  f.threads[1].reject({ code: "timeout", message: "retry refused" });
  await second;
  expect(f.threadChat().openError).toBe("retry refused");
  f.threads[0].resolve(threadSnap("old"));
  await vi.advanceTimersByTimeAsync(0);
  expect(f.threadChat().openError).toBe("retry refused");
  const third = f.a.openThread(bot, thread);
  expect(f.threads).toHaveLength(3);
  f.threads[2].resolve(threadSnap("new"));
  await third;
  expect(f.threadChat()).toMatchObject({ loaded: true, openError: null, model: "new" });
});

it("a reclick before the gateway's 30s reply limit never sends two same-thread opens concurrently", async () => {
  const f = await setup();
  void f.a.openThread(bot, thread);
  await vi.advanceTimersByTimeAsync(HERMES_RPC_MS - 2);
  void f.a.openThread(bot, thread);
  expect(f.threads).toHaveLength(1);
  await vi.advanceTimersByTimeAsync(1);
  void f.a.openThread(bot, thread);
  const overlap = f.threads.length;
  console.log("cold reclick", { elapsedMs: HERMES_RPC_MS - 1, pendingSameThread: overlap });
  for (const x of f.threads) x.resolve(threadSnap("ready"));
  await vi.advanceTimersByTimeAsync(0);
  expect(overlap, "physical wire requests in flight, not just the store's current slot").toBe(1);
});

it.each(["reply", "error"])("expired main read %s is ignored while its newer read is still pending", async (late) => {
  const f = await setup();
  f.busy();
  await f.a.send("follow-up");
  await vi.advanceTimersByTimeAsync(TURN_QUIET_MS + CHAT_READ_MS + TURN_QUIET_MS * 2 + 1);
  expect(f.mains).toHaveLength(2);
  if (late === "reply") f.mains[0].resolve(snap("old", true));
  else f.mains[0].reject({ code: "timeout", message: "expired" });
  await vi.advanceTimersByTimeAsync(0);
  expect(f.mainChat()).toMatchObject({ model: "initial", openError: null });
  expect(f.sends).toEqual([]);
  f.mains[1].resolve(snap("new"));
  await vi.advanceTimersByTimeAsync(0);
  expect(f.mainChat()).toMatchObject({ model: "new", openError: null, turn: null });
  expect(f.sends).toEqual([expect.objectContaining({ text: "follow-up" })]);
});
