// Steer queue (a bot's main chat): a message typed while a turn runs is held in omher and goes out with chat.send
// when the turn ends, in order, exactly once; its ↵ menu sends it now (one interrupt), steers it (chat.steer, a
// refusal falls back to a normal send), edits or deletes it. Holds across a reconnect, a bot switch and Stop.
import { describe, expect, it } from "vitest";
import { createStore, initialState, reduce, reduceQueue, type AppState, type BridgeLike, type Chat } from "./store";
import type { BridgeEvent } from "../lib/protocol";
import type { BridgeStatus } from "../lib/bridge";

const T0 = 1_800_000_000_000;
const tick = () => new Promise((r) => setTimeout(r, 0));

function fake() {
  let anyH: ((ev: BridgeEvent) => void) | null = null;
  let statusH: ((s: BridgeStatus) => void) | null = null;
  const calls: { op: string; params: Record<string, unknown> }[] = [];
  let running = false;
  let steer: "queued" | "rejected" | "throw" = "queued";
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
    sends: (bot = "kami") => calls.filter((c) => c.op === "chat.send" && c.params.bot === bot).map((c) => c.params.text),
    count: (op: string) => calls.filter((c) => c.op === op).length,
  };
}

/** A store on kami with a turn running. */
async function busy() {
  const f = fake();
  // a clock that moves: a chat.open asked after a turn ended is newer than that end (applyOpened's `since`)
  let clock = T0;
  const store = createStore(f.bridge, { now: () => (clock += 10) });
  await store.actions.init();
  f.emit({ event: "turn.start", bot: "kami" });
  return { f, store, a: store.actions, chat: () => store.getState().chats.kami };
}
const heldIds = (c: Chat) => c.items.filter((i) => i.kind === "user" && i.held).map((i) => i.id);
const userTexts = (c: Chat) => c.items.flatMap((i) => (i.kind === "user" ? [i.text] : []));
const turn = async (f: ReturnType<typeof fake>, outcome: "done" | "interrupted" = "done") => {
  f.emit({ event: "turn.end", bot: "kami", outcome });
  await tick();
  await tick();
};
const start = async (f: ReturnType<typeof fake>) => {
  f.emit({ event: "turn.start", bot: "kami" });
  await tick();
};

describe("steer queue: FIFO", () => {
  it("holds messages typed during a turn and sends them one per turn end, in order", async () => {
    const { f, a, chat } = await busy();
    await a.send("first");
    await a.send("second");
    expect(f.sends()).toEqual([]);
    expect(chat().queue).toEqual(heldIds(chat()));
    expect(heldIds(chat())).toHaveLength(2);
    await turn(f);
    expect(f.sends()).toEqual(["first"]);
    // the second waits for the first's turn to start and end, not just for the turn.end
    await tick();
    expect(f.sends()).toEqual(["first"]);
    await start(f);
    expect(f.sends()).toEqual(["first"]);
    await turn(f);
    expect(f.sends()).toEqual(["first", "second"]);
    expect(chat().queue).toEqual([]);
    expect(heldIds(chat())).toEqual([]);
  });

  it("a message typed while the queue is not empty joins its end, even with no turn running", async () => {
    const { f, a } = await busy();
    await a.send("one");
    await turn(f); // "one" goes out; its turn has not started yet
    await a.send("two");
    expect(f.sends()).toEqual(["one"]);
    await start(f);
    await turn(f);
    expect(f.sends()).toEqual(["one", "two"]);
  });

  it("with no turn running a message goes out at once", async () => {
    const f = fake();
    const store = createStore(f.bridge, { now: () => T0 });
    await store.actions.init();
    await store.actions.send("hi");
    expect(f.sends()).toEqual(["hi"]);
    expect(store.getState().chats.kami.queue ?? []).toEqual([]);
  });
});

describe("steer queue: the ↵ menu", () => {
  it("Send now: exactly one interrupt, and this one goes out first when the turn ends", async () => {
    const { f, a, chat } = await busy();
    await a.send("a");
    await a.send("b");
    const [, b] = heldIds(chat());
    await Promise.all([a.queueSendNow(b), a.queueSendNow(b)]);
    expect(f.count("chat.interrupt")).toBe(1);
    expect(f.sends()).toEqual([]);
    await turn(f, "interrupted");
    expect(f.sends()).toEqual(["b"]);
    await start(f);
    await turn(f);
    expect(f.sends()).toEqual(["b", "a"]);
  });

  it("Steer: one chat.steer; taken, the row leaves the queue as Steered and is never sent", async () => {
    const { f, a, chat } = await busy();
    await a.send("also check the logs");
    const [id] = heldIds(chat());
    await a.queueSteer(id);
    expect(f.calls.filter((c) => c.op === "chat.steer").map((c) => c.params)).toEqual([{ bot: "kami", text: "also check the logs" }]);
    const row = chat().items.find((i) => i.id === id)!;
    expect(row).toMatchObject({ kind: "user", steered: true });
    expect("held" in row && row.held).toBeFalsy();
    expect(chat().queue).toEqual([]);
    await turn(f);
    expect(f.sends()).toEqual([]);
  });

  it("Steer rejected (or failed): sent normally, first, after the turn", async () => {
    for (const mode of ["rejected", "throw"] as const) {
      const { f, a, chat } = await busy();
      f.setSteer(mode);
      await a.send("x");
      await a.send("y");
      const [, y] = heldIds(chat());
      await a.queueSteer(y);
      expect(f.count("chat.steer")).toBe(1);
      expect(f.sends()).toEqual([]);
      expect(chat().items.find((i) => i.id === y)).toMatchObject({ held: true });
      expect(chat().queue![0]).toBe(y);
      await turn(f);
      expect(f.sends()).toEqual(["y"]);
    }
  });

  it("Steer after the turn already ended: no chat.steer, it goes out as a normal message", async () => {
    const { f, a, chat } = await busy();
    await a.send("late");
    await a.send("later");
    await turn(f); // "late" goes out; "later" waits for its turn
    const [later] = heldIds(chat());
    await a.queueSteer(later);
    expect(f.count("chat.steer")).toBe(0);
    await start(f);
    await turn(f);
    expect(f.sends()).toEqual(["late", "later"]);
  });

  it("Edit: the text goes back to the composer and is never sent", async () => {
    const { f, a, store, chat } = await busy();
    await a.send("typo here");
    const [id] = heldIds(chat());
    a.queueEdit(id);
    expect(store.getState().ui.draft).toMatchObject({ bot: "kami", text: "typo here" });
    expect(userTexts(chat())).not.toContain("typo here");
    await turn(f);
    expect(f.sends()).toEqual([]);
  });

  it("Delete: gone, never sent; the rest keep their order", async () => {
    const { f, a, chat } = await busy();
    await a.send("1");
    await a.send("2");
    await a.send("3");
    a.queueDelete(heldIds(chat())[1]);
    expect(userTexts(chat())).not.toContain("2");
    await turn(f);
    await start(f);
    await turn(f);
    expect(f.sends()).toEqual(["1", "3"]);
  });
});

describe("steer queue: order and exactly-once", () => {
  it("Stop keeps the waiting messages; they go out after the stopped turn", async () => {
    const { f, a, chat } = await busy();
    await a.send("wait for me");
    await a.interrupt();
    expect(f.count("chat.interrupt")).toBe(1);
    expect(heldIds(chat())).toHaveLength(1);
    await turn(f, "interrupted");
    expect(f.sends()).toEqual(["wait for me"]);
  });

  it("reconnect: nothing goes out while the bridge is away; after the chat is read again, once", async () => {
    const { f, a, chat } = await busy();
    await a.send("survive");
    f.status("closed"); // the lost turn ends as interrupted, but omher does not know what Hermes runs
    await tick();
    expect(chat().turn).toBeNull();
    expect(f.sends()).toEqual([]);
    f.setRunning(true);
    f.status("open"); // resync: chat.open says a turn still runs
    for (let i = 0; i < 5; i++) await tick();
    expect(f.sends()).toEqual([]);
    expect(chat().turn).not.toBeNull();
    await turn(f);
    expect(f.sends()).toEqual(["survive"]);
    f.status("closed");
    f.setRunning(false);
    f.status("open");
    for (let i = 0; i < 5; i++) await tick();
    expect(f.sends()).toEqual(["survive"]);
  });

  it("a bot switch: kami's held message still goes to kami when its turn ends", async () => {
    const { f, a } = await busy();
    await a.send("for kami");
    await a.selectBot("friren");
    await turn(f);
    expect(f.calls.filter((c) => c.op === "chat.send").map((c) => c.params)).toEqual([{ bot: "kami", text: "for kami" }]);
  });

  it("a send that fails is marked, and the next one still goes out", async () => {
    const { f, a, chat } = await busy();
    const plain = f.bridge.request;
    let fails = 1;
    f.bridge.request = (async (op: string, p: Record<string, unknown>) => {
      if (op === "chat.send" && fails-- > 0) {
        f.calls.push({ op, params: p });
        throw { code: "bot_offline", message: "gone" };
      }
      return (plain as (o: string, p: Record<string, unknown>) => Promise<unknown>)(op, p);
    }) as BridgeLike["request"];
    await a.send("a");
    await a.send("b");
    await turn(f);
    expect(chat().items.find((i) => i.kind === "user" && i.text === "a")).toMatchObject({ error: "gone" });
    expect(f.sends()).toEqual(["a", "b"]);
  });
});

describe("reduceQueue (pure)", () => {
  const base = (): AppState => {
    let s = reduce(initialState(), { type: "local.user", bot: "kami", id: "a", text: "a", now: T0, held: true });
    s = reduce(s, { type: "local.user", bot: "kami", id: "b", text: "b", now: T0 + 1, held: true });
    return s;
  };
  it("take moves the head to the end, unheld, and waits for its turn", () => {
    const c = reduceQueue(base().chats.kami, { type: "queue.take", bot: "kami", id: "a", now: T0 + 5000 });
    expect(c.queue).toEqual(["b"]);
    expect(c.pendingTurn).toBe("a");
    expect(c.items.map((i) => i.id)).toEqual(["b", "a"]);
    expect(c.items[1]).not.toHaveProperty("held");
  });
  it("front, drop, steered and a stale take", () => {
    const c0 = base().chats.kami;
    expect(reduceQueue(c0, { type: "queue.front", bot: "kami", id: "b" }).queue).toEqual(["b", "a"]);
    expect(reduceQueue(c0, { type: "queue.drop", bot: "kami", id: "a" }).items.map((i) => i.id)).toEqual(["b"]);
    expect(reduceQueue(c0, { type: "queue.steered", bot: "kami", id: "b", ok: false, now: T0 }).queue).toEqual(["b", "a"]);
    const ok = reduceQueue(c0, { type: "queue.steered", bot: "kami", id: "a", ok: true, now: T0 + 9 });
    expect(ok.queue).toEqual(["b"]);
    expect(ok.items.find((i) => i.id === "a")).toMatchObject({ steered: true });
    // a row no longer in the queue is never taken twice
    const once = reduceQueue(c0, { type: "queue.take", bot: "kami", id: "a", now: T0 });
    expect(reduceQueue(once, { type: "queue.take", bot: "kami", id: "a", now: T0 })).toBe(once);
  });
  it("a held row survives a chat re-read; an idle send stops holding the queue", () => {
    let s = base();
    s = reduce(s, { type: "chat.opened", bot: "kami", res: { session_id: "s", messages: [], running: false, model: "", provider: "", reasoning: "" }, now: T0 + 10 });
    expect(s.chats.kami.queue).toEqual(["a", "b"]);
    expect(s.chats.kami.items.map((i) => i.id)).toEqual(["a", "b"]);
    const c = { ...s.chats.kami, pendingTurn: "x" };
    expect(reduceQueue(c, { type: "queue.idle", bot: "kami", id: "x" }).pendingTurn).toBeNull();
    expect(reduceQueue(c, { type: "queue.idle", bot: "kami", id: "y" }).pendingTurn).toBe("x");
  });
});
