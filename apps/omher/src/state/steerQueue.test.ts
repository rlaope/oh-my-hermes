// Steer queue (a bot's main chat): a message typed while a turn runs is steered into it at once (chat.steer, no
// interrupt). Where Hermes refuses the steer it is held in omher and goes out with chat.send when the turn ends, in
// order, exactly once; its ↵ buttons send it now (one interrupt), steer it again, edit or delete it. Holds across a
// reconnect, a bot switch and Stop.
import { describe, expect, it } from "vitest";
import { answerSlot, createStore, heldDrafts, initialState, reduce, reduceQueue, type AppState, type BridgeLike, type Chat } from "./store";
import type { BridgeEvent } from "../lib/protocol";
import type { BridgeStatus } from "../lib/bridge";

const T0 = 1_800_000_000_000;

function touch(s: AppState, c: Chat): AppState {
  return { ...s, chats: { ...s.chats, kami: c } };
}
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

describe("typed during a turn: steered in at once (messenger style)", () => {
  /** A store on kami with a turn running that takes steers (Hermes' default). */
  const steering = async () => {
    const b = await busy();
    b.f.setSteer("queued");
    return b;
  };
  it("one chat.steer right away, no interrupt, never sent again; the row reads as a plain sent message", async () => {
    const { f, a, chat } = await steering();
    await a.send("keep the old timeout too");
    expect(f.calls.filter((c) => c.op === "chat.steer").map((c) => c.params)).toEqual([{ bot: "kami", text: "keep the old timeout too" }]);
    const row = chat().items.find((i) => i.kind === "user" && i.text === "keep the old timeout too")!;
    expect(row).toMatchObject({ steered: true, readAt: expect.any(Number) });
    expect(row).not.toHaveProperty("held");
    expect(row).not.toHaveProperty("autoSteer");
    expect(chat().queue).toEqual([]);
    await turn(f);
    expect(f.sends()).toEqual([]);
    expect(f.count("chat.interrupt")).toBe(0);
  });
  it("while it is steering it never shows as waiting, and the answer is not kept above it", async () => {
    const f = fake();
    let release: (v: unknown) => void = () => {};
    const plain = f.bridge.request;
    f.bridge.request = (async (op: string, p: Record<string, unknown>) =>
      op === "chat.steer" ? (f.calls.push({ op, params: p }), new Promise<unknown>((r) => (release = r))) : (plain as (o: string, p: Record<string, unknown>) => Promise<unknown>)(op, p)) as BridgeLike["request"];
    const store = createStore(f.bridge, { now: () => T0 });
    await store.actions.init();
    f.emit({ event: "turn.start", bot: "kami" });
    void store.actions.send("and the docs");
    await tick();
    const c = store.getState().chats.kami;
    const row = c.items.find((i) => i.kind === "user" && i.text === "and the docs")!;
    expect(row).toMatchObject({ held: true, autoSteer: true });
    expect(c.turn?.before).toBeUndefined();
    // the live line (dots, activity) sits under it
    expect(c.items[c.items.length - 1]).toMatchObject({ kind: "activity" });
    release({ status: "queued" });
    await tick();
    expect(store.getState().chats.kami.items.find((i) => i.kind === "user" && i.text === "and the docs")).toMatchObject({ steered: true });
  });
  it("a second message typed while the first is steering is steered next, in order", async () => {
    const f = fake();
    const plain = f.bridge.request;
    const pending: ((v: unknown) => void)[] = [];
    f.bridge.request = (async (op: string, p: Record<string, unknown>) =>
      op === "chat.steer" ? (f.calls.push({ op, params: p }), new Promise<unknown>((r) => pending.push(r))) : (plain as (o: string, p: Record<string, unknown>) => Promise<unknown>)(op, p)) as BridgeLike["request"];
    const store = createStore(f.bridge, { now: () => T0 });
    await store.actions.init();
    f.emit({ event: "turn.start", bot: "kami" });
    void store.actions.send("one");
    void store.actions.send("two");
    await tick();
    expect(f.calls.filter((c) => c.op === "chat.steer").map((c) => c.params.text)).toEqual(["one"]);
    pending.shift()!({ status: "queued" });
    await tick();
    expect(f.calls.filter((c) => c.op === "chat.steer").map((c) => c.params.text)).toEqual(["one", "two"]);
    pending.shift()!({ status: "queued" });
    await tick();
    expect(store.getState().chats.kami.items.filter((i) => i.kind === "user" && i.steered).map((i) => i.kind === "user" && i.text)).toEqual(["one", "two"]);
    expect(f.sends()).toEqual([]);
  });
  it("refused: it and the one behind it wait (↵ ↓ ×) and go out after the turn, in order; nothing is lost", async () => {
    const { f, a, chat } = await busy();
    await a.send("refused");
    await a.send("behind");
    expect(heldIds(chat())).toHaveLength(2);
    expect(chat().items.some((i) => i.kind === "user" && i.autoSteer)).toBe(false);
    expect(chat().turn?.before).toBe(heldIds(chat())[0]);
    await turn(f);
    expect(f.sends()).toEqual(["refused"]);
    await start(f);
    await turn(f);
    expect(f.sends()).toEqual(["refused", "behind"]);
  });
  it("while the bridge comes back (no turn to steer) it waits, and goes out once after the chat is read again", async () => {
    const { f, a, chat } = await steering();
    f.status("closed");
    await tick();
    await a.send("typed while away");
    expect(heldIds(chat())).toHaveLength(1);
    expect(f.count("chat.steer")).toBe(0);
    f.status("open");
    for (let i = 0; i < 6; i++) await tick();
    expect(f.sends()).toEqual(["typed while away"]);
  });
});

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
    await a.send("also check the logs"); // refused at once: it waits
    const [id] = heldIds(chat());
    f.setSteer("queued");
    await a.queueSteer(id);
    expect(f.calls.filter((c) => c.op === "chat.steer").map((c) => c.params)).toEqual([
      { bot: "kami", text: "also check the logs" },
      { bot: "kami", text: "also check the logs" },
    ]);
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
      await a.send("x"); // refused at once: it waits, and "y" waits behind it without a steer of its own
      await a.send("y");
      expect(f.count("chat.steer")).toBe(1);
      const [, y] = heldIds(chat());
      await a.queueSteer(y);
      expect(f.count("chat.steer")).toBe(2);
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
    expect(f.count("chat.steer")).toBe(1); // "late", refused when it was typed
    await a.queueSteer(later);
    expect(f.count("chat.steer")).toBe(1);
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
    expect(f.calls.filter((c) => c.op === "chat.send").map((c) => c.params)).toEqual([{ bot: "kami", text: "for kami", queued: true }]);
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
  it("a message held before any answer shows still reads under that answer", () => {
    const ev = (e: Record<string, unknown>) => ({ bot: "kami", ...e }) as BridgeEvent;
    let s = reduce(initialState(), { type: "local.user", bot: "kami", id: "q", text: "q", now: T0 });
    s = reduce(s, { type: "event", ev: ev({ event: "turn.start" }), now: T0 + 100 });
    s = reduce(s, { type: "local.user", bot: "kami", id: "h", text: "held", now: T0 + 200, held: true });
    for (const e of [ev({ event: "message", id: "a1", text: "Done." }), ev({ event: "turn.end", outcome: "done" })]) s = reduce(s, { type: "event", ev: e, now: T0 + 300 });
    expect(s.chats.kami.items.flatMap((i) => (i.kind === "user" || i.kind === "assistant" ? [i.text] : []))).toEqual(["q", "Done.", "held"]);
  });
  it("with the answer showing: held messages read under it; one steered in moves above it", () => {
    const ev = (e: Record<string, unknown>) => ({ bot: "kami", ...e }) as BridgeEvent;
    const order = (st: AppState) =>
      st.chats.kami.items.flatMap((i) => (i.kind === "user" || i.kind === "assistant" ? [`${i.kind}:${i.text}`] : []));
    let s = reduce(initialState(), { type: "local.user", bot: "kami", id: "q", text: "q", now: T0 });
    for (const e of [ev({ event: "turn.start" }), ev({ event: "delta", text: "Line one.\n" })]) s = reduce(s, { type: "event", ev: e, now: T0 + 100 });
    s = reduce(s, { type: "local.user", bot: "kami", id: "w", text: "wait", now: T0 + 200, held: true });
    s = reduce(s, { type: "local.user", bot: "kami", id: "x", text: "steer", now: T0 + 300, held: true });
    expect(s.chats.kami.turn?.before).toBe("w");
    // steer "w" in: it joined the running turn, so the answer is no longer kept above it
    s = touch(s, reduceQueue(s.chats.kami, { type: "queue.steered", bot: "kami", id: "w", ok: true, now: T0 + 400 }));
    expect(s.chats.kami.turn?.before).toBe("x");
    for (const e of [ev({ event: "message", id: "a1", text: "Line one." }), ev({ event: "turn.end", outcome: "done" })]) s = reduce(s, { type: "event", ev: e, now: T0 + 500 });
    // q, then "wait" (steered into this turn), the answer, and "steer" still waiting under it for the next turn
    expect(order(s)).toEqual(["user:q", "user:wait", "assistant:Line one.", "user:steer"]);
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

describe("steer queue: review fixes", () => {
  const order = (c: Chat) =>
    c.items.flatMap((i) => (i.kind === "user" || i.kind === "assistant" ? [`${i.kind}:${i.text}${i.kind === "user" && i.held ? "(held)" : ""}`] : []));

  it("R1: deleting the first waiting message keeps the answer above the next one", () => {
    const ev = (e: Record<string, unknown>) => ({ type: "event" as const, ev: { bot: "kami", ...e } as BridgeEvent, now: T0 + 100 });
    let s = reduce(initialState(), { type: "local.user", bot: "kami", id: "q", text: "q", now: T0 });
    s = reduce(s, ev({ event: "turn.start" }));
    s = reduce(s, { type: "local.user", bot: "kami", id: "A", text: "A", now: T0 + 200, held: true });
    s = reduce(s, { type: "local.user", bot: "kami", id: "B", text: "B", now: T0 + 300, held: true });
    s = reduce(s, { type: "queue.drop", bot: "kami", id: "A" });
    expect(s.chats.kami.turn?.before).toBe("B");
    expect(s.chats.kami.items[answerSlot(s.chats.kami)]).toMatchObject({ id: "B" });
    s = reduce(s, ev({ event: "message", id: "a1", text: "answer" }));
    s = reduce(s, ev({ event: "turn.end", outcome: "done" }));
    expect(order(s.chats.kami)).toEqual(["user:q", "assistant:answer", "user:B(held)"]);
    // the only waiting one gone: the answer goes back to the end
    let one = reduce(initialState(), { type: "local.user", bot: "kami", id: "q", text: "q", now: T0 });
    one = reduce(one, ev({ event: "turn.start" }));
    one = reduce(one, { type: "local.user", bot: "kami", id: "A", text: "A", now: T0 + 200, held: true });
    one = reduce(one, { type: "queue.drop", bot: "kami", id: "A" });
    expect(one.chats.kami.turn?.before).toBeUndefined();
  });

  it("Edit of the first waiting message moves the answer's place too", async () => {
    const { a, chat } = await busy();
    await a.send("A");
    await a.send("B");
    const [A, B] = heldIds(chat());
    expect(chat().turn?.before).toBe(A);
    a.queueEdit(A);
    expect(chat().turn?.before).toBe(B);
  });

  it("R2: a steer with no answer (disconnect, bot offline, timeout, internal) or an uncertain one is never sent again on its own", async () => {
    for (const mode of ["disconnected", "bot_offline", "timeout", "internal", "uncertain"] as const) {
      const { f, a, chat } = await busy();
      await a.send("also check the docs");
      await a.send("next");
      f.setSteer(mode);
      const [id] = heldIds(chat());
      await a.queueSteer(id);
      expect(f.count("chat.steer"), mode).toBe(2);
      const row = chat().items.find((i) => i.id === id)!;
      expect(row, mode).toMatchObject({ steerUnknown: true });
      expect(chat().queue, mode).not.toContain(id);
      await turn(f);
      await start(f);
      await turn(f);
      // only "next" went out; the unknown one waits for the person
      expect(f.sends(), mode).toEqual(["next"]);
    }
  });

  it("an unknown steer: Send puts it out next as a normal message; Delete drops it", async () => {
    const { f, a, chat } = await busy();
    await a.send("maybe");
    await a.send("gone");
    f.setSteer("disconnected");
    const [m, g] = heldIds(chat());
    await a.queueSteer(m);
    f.setSteer("timeout");
    await a.queueSteer(g);
    a.queueDelete(g);
    expect(userTexts(chat())).not.toContain("gone");
    a.queueResend(m);
    expect(chat().items.find((i) => i.id === m)).toMatchObject({ held: true });
    expect(chat().items.find((i) => i.id === m)).not.toHaveProperty("steerUnknown");
    await turn(f);
    expect(f.sends()).toEqual(["maybe"]);
  });

  it("M2: a held message goes out queued", async () => {
    const { f, a, chat } = await busy();
    await a.send("one");
    await turn(f);
    expect(f.calls.filter((c) => c.op === "chat.send").map((c) => c.params.queued)).toEqual([true]);
    expect(chat().queue).toEqual([]);
  });

  it("M3: Stop or Send now before the turn read a steered message: it is marked not used, never lost or resent", async () => {
    for (const how of ["stop", "now"] as const) {
      const { f, a, chat } = await busy();
      await a.send("A");
      await a.send("B");
      const [A, B] = heldIds(chat());
      f.setSteer("queued");
      await a.queueSteer(A);
      expect(chat().items.find((i) => i.id === A)).toMatchObject({ steered: true });
      if (how === "now") await a.queueSendNow(B);
      else await a.interrupt();
      await turn(f, "interrupted");
      const row = chat().items.find((i) => i.id === A)!;
      expect(row, how).toMatchObject({ steerUnknown: true, steerUnused: true });
      expect(row, how).not.toHaveProperty("steered");
      expect(f.sends(), how).toEqual(["B"]);
      // Send: it goes out as a normal message, once
      a.queueResend(A);
      await start(f);
      await turn(f);
      expect(f.sends(), how).toEqual(["B", "A"]);
    }
  });

  it("M3: a steered message the turn already read (a tool step ended) stays Steered after a Stop", async () => {
    const { f, a, chat } = await busy();
    await a.send("A");
    const [A] = heldIds(chat());
    f.setSteer("queued");
    await a.queueSteer(A);
    f.emit({ event: "tool.start", bot: "kami", tool_id: "t1", name: "read", detail: "" } as BridgeEvent);
    f.emit({ event: "tool.end", bot: "kami", tool_id: "t1", ok: true } as BridgeEvent);
    await a.interrupt();
    await turn(f, "interrupted");
    expect(chat().items.find((i) => i.id === A)).toMatchObject({ steered: true });
    expect(chat().items.find((i) => i.id === A)).not.toHaveProperty("steerUnknown");
    expect(f.sends()).toEqual([]);
  });

  it("a reconnect whose bots.list failed: the next bots.list success reads the chat again and the queue moves", async () => {
    const { f, a, chat } = await busy();
    await a.send("stuck?");
    f.setBotsFail(true);
    f.status("closed");
    f.status("open");
    for (let i = 0; i < 5; i++) await tick();
    expect(chat().stale).toBe(true);
    expect(f.sends()).toEqual([]);
    f.setBotsFail(false);
    f.emit({ event: "bots.update" } as BridgeEvent);
    for (let i = 0; i < 6; i++) await tick();
    expect(chat().stale).toBe(false);
    expect(f.sends()).toEqual(["stuck?"]);
  });

  it("B2: a reload saves held messages (and unknown steers) into their chat's draft, in order, above what was typed", async () => {
    const { f, a, store } = await busy();
    await a.send("first held");
    await a.send("second held");
    f.setSteer("disconnected");
    await a.send("maybe steered");
    await a.queueSteer(store.getState().chats.kami.queue![2]);
    const drafts = heldDrafts(store.getState(), { kami: "typing this", friren: "other" });
    expect(drafts).toEqual({ kami: "first held\nsecond held\nmaybe steered\ntyping this", friren: "other" });
    expect(heldDrafts(store.getState(), {})).toEqual({ kami: "first held\nsecond held\nmaybe steered" });
  });
});
