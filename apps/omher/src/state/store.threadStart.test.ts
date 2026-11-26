// Starting a thread: one press makes one thread, and a refused create says so where the person acted.
import { expect, it } from "vitest";
import { createStore, type BridgeLike } from "./store";
import type { BridgeEvent } from "../lib/protocol";
import type { BridgeStatus } from "../lib/bridge";

function fixture(opts: { refuse?: string } = {}) {
  const calls: { op: string; params: any }[] = [];
  let made = 0;
  const bridge: BridgeLike = {
    connect: async () => {},
    onAny: (_h: (e: BridgeEvent) => void) => () => {},
    onStatus: (_h: (s: BridgeStatus) => void) => () => {},
    request: (async (op: string, params: any) => {
      calls.push({ op, params });
      if (op === "hello") return { bridge: "mock", version: "test", hermes: { home: "/scratch" } };
      if (op === "bots.list")
        return { bots: [{ name: "kami", display_name: "Kami", is_default: false, model: "m", provider: "p", description: "", status: "online", running: false }] };
      if (op === "chat.open") return { session_id: "s-kami", messages: [], running: false, lost: [], model: "m", provider: "p", reasoning: "high" };
      if (op === "thread.create") {
        await new Promise((r) => setTimeout(r, 20));
        if (opts.refuse) throw { code: "thread_limit", message: opts.refuse };
        return { thread: `th${(made += 1)}`, title: "", cwd: "/w", started_at: 1, running: false, needs: false, message_count: 0, model: "m", provider: "p", reasoning: "" };
      }
      if (op === "chat.interrupt" && opts.refuse) throw { code: "failed", message: opts.refuse };
      return {};
    }) as BridgeLike["request"],
  };
  const store = createStore(bridge);
  return { store, sends: () => calls.filter((c) => c.op === "chat.send").map((c) => c.params), creates: () => calls.filter((c) => c.op === "thread.create") };
}
const settle = (ms = 80) => new Promise((r) => setTimeout(r, ms));
const lines = (f: ReturnType<typeof fixture>, key: string) =>
  (f.store.getState().chats[key]?.items ?? []).filter((i) => i.kind === "system").map((i) => (i as { text: string }).text);

it("a second press while the create is out reuses it: one thread", async () => {
  const f = fixture();
  await f.store.actions.init();
  await settle();
  const [a, b] = await Promise.all([f.store.actions.newThread("kami"), f.store.actions.newThread("kami")]);
  expect(f.creates()).toHaveLength(1);
  expect(a).toBe("th1");
  expect(b).toBe("th1");
  expect(f.store.getState().threads.kami).toHaveLength(1);
  // once it landed, the next press is a new thread
  await f.store.actions.newThread("kami");
  expect(f.creates()).toHaveLength(2);
});

it("a refused create shows a line in the bot's chat and returns null", async () => {
  const f = fixture({ refuse: "48 threads are open" });
  await f.store.actions.init();
  await settle();
  expect(await f.store.actions.newThread("kami")).toBeNull();
  await settle();
  expect(lines(f, "kami").some((l) => l.includes("48 threads are open"))).toBe(true);
  // a failed create does not wedge the guard
  expect(await f.store.actions.newThread("kami")).toBeNull();
  expect(f.creates()).toHaveLength(2);
});

it("a refused task thread and a refused Stop show a line too", async () => {
  const f = fixture({ refuse: "gateway down" });
  await f.store.actions.init();
  await settle();
  expect(await f.store.actions.startTaskThread("kami", "Fix", "do it")).toBeNull();
  await f.store.actions.threadInterrupt("kami", "th1");
  await settle();
  expect(lines(f, "kami").filter((l) => l.includes("gateway down"))).toHaveLength(2);
});

it("two newThreadWith calls while the first create is out make two threads, each with its own text", async () => {
  const f = fixture();
  await f.store.actions.init();
  await settle();
  const [a, b] = await Promise.all([f.store.actions.newThreadWith("kami", "A"), f.store.actions.newThreadWith("kami", "B")]);
  expect(f.creates()).toHaveLength(2);
  expect(a).not.toBe(b);
  const sends = f.sends();
  expect(sends).toContainEqual({ bot: "kami", session: a, text: "A" });
  expect(sends).toContainEqual({ bot: "kami", session: b, text: "B" });
});
