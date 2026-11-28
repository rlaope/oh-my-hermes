// The "Handed to <bot>" card as the store's reducer moves it from the target thread's own events (rule 58).
import { describe, expect, it } from "vitest";
import { initialState, reduce, type Action, type AppState, type HandoffItem } from "../state/store";
import type { BridgeEvent, ChatOpenResult } from "../lib/protocol";

const T0 = 1_800_000_000_000;
const opened = (messages: ChatOpenResult["messages"]): ChatOpenResult => ({ session_id: "s", messages, running: false, model: "m", provider: "p", reasoning: "" });

/** Kami's main chat with one answer, handed to Friren's new thread `th1`. */
function handed(): AppState {
  let s = reduce(initialState(), { type: "chat.opened", bot: "kami", res: opened([{ id: "a1", role: "assistant", text: "Retry three times.", ts: T0 / 1000 - 60 }]), now: T0 - 1000 });
  s = reduce(s, { type: "chat.opened", bot: "fold:friren:th1", res: opened([]), now: T0 });
  return reduce(s, { type: "handoff.add", chat: "kami", message: "a1", bot: "friren", thread: "th1", now: T0 });
}
/** One event of Friren's thread `th1` (the fields the event carries besides its bot and session). */
const ev = (s: AppState, e: { event: BridgeEvent["event"] } & Record<string, unknown>, now = T0 + 1000) =>
  reduce(s, { type: "event", ev: { bot: "friren", session: "th1", ...e } as BridgeEvent, now });
const card = (s: AppState) => s.chats.kami.items.find((i): i is HandoffItem => i.kind === "handoff")!;

describe("handoff card", () => {
  it("goes right under the answer, working, and the map points the thread at it", () => {
    const s = handed();
    expect(s.chats.kami.items.map((i) => i.kind)).toEqual(["assistant", "handoff"]);
    expect(card(s)).toMatchObject({ bot: "friren", thread: "th1", phase: "working" });
    expect(s.handoffs["fold:friren:th1"]).toEqual({ chat: "kami", id: card(s).id });
  });

  it("working → waiting → working → done with the turn's answer → given", () => {
    let s = handed();
    s = ev(s, { event: "turn.start" });
    expect(card(s).phase).toBe("working");
    s = ev(s, { event: "approval.request", request_id: "r1", title: "Run", command: "ls", choices: ["once", "deny"] });
    expect(card(s).phase).toBe("waiting");
    s = ev(s, { event: "tool.start", tool_id: "t1", name: "terminal", detail: "ls" });
    expect(card(s).phase).toBe("working");
    s = ev(s, { event: "clarify.request", request_id: "q1", question: "Which docs?" });
    expect(card(s).phase).toBe("waiting");
    s = ev(s, { event: "message", id: "f1", text: "The docs say five seconds." });
    expect(card(s).phase).toBe("working");
    s = ev(s, { event: "turn.end", outcome: "done" });
    expect(card(s)).toMatchObject({ phase: "done", answer: "The docs say five seconds." });
    // a later turn there changes nothing: the first turn settled it
    s = ev(s, { event: "turn.start" });
    s = ev(s, { event: "message", id: "f2", text: "More." });
    s = ev(s, { event: "turn.end", outcome: "interrupted" });
    expect(card(s)).toMatchObject({ phase: "done", answer: "The docs say five seconds." });
    s = reduce(s, { type: "handoff.given", chat: "kami", id: card(s).id, row: "local-9" });
    expect(card(s).given).toBe("local-9");
  });

  it("a turn that streamed its answer without a message still gives it", () => {
    let s = ev(handed(), { event: "turn.start" });
    s = ev(s, { event: "delta", text: "Five seconds." });
    s = ev(s, { event: "turn.end", outcome: "done" });
    expect(card(s)).toMatchObject({ phase: "done", answer: "Five seconds." });
  });

  it("stopped: an interrupted turn, or one that ended with an error, says how", () => {
    let s = ev(ev(handed(), { event: "turn.start" }), { event: "turn.end", outcome: "interrupted" });
    expect(card(s)).toMatchObject({ phase: "stopped", outcome: "interrupted" });
    expect(card(s).error).toBeUndefined();
    s = ev(ev(handed(), { event: "turn.start" }), { event: "turn.end", outcome: "error", error: "rate limited" });
    expect(card(s)).toMatchObject({ phase: "stopped", outcome: "error", error: "rate limited" });
    // given only once done
    s = reduce(s, { type: "handoff.given", chat: "kami", id: card(s).id, row: "local-9" });
    expect(card(s).given).toBeUndefined();
  });

  it("the thread removed: the card says it is gone, whatever came before", () => {
    let s = ev(handed(), { event: "turn.start" });
    s = reduce(s, { type: "thread.upsert", bot: "friren", row: { thread: "th1", title: "From Kami", cwd: "", started_at: 1, running: false, needs: false, message_count: 0 } });
    s = reduce(s, { type: "thread.gone", bot: "friren", thread: "th1" });
    expect(card(s).phase).toBe("gone");
    expect(ev(s, { event: "turn.end", outcome: "done" }).chats.kami).toBe(s.chats.kami);
    // the card said so: nothing can move it now, so its link goes
    expect(s.handoffs).toEqual({});
  });

  it("the chat that holds the card goes: its link goes too", () => {
    let s = handed();
    s = reduce(s, { type: "chat.forget", bot: "kami" });
    expect(s.handoffs).toEqual({});
    // a card in a thread of Kami's, that thread removed
    s = reduce(handed(), { type: "chat.opened", bot: "fold:kami:k1", res: opened([{ id: "b1", role: "assistant", text: "Hi.", ts: T0 / 1000 - 5 }]), now: T0 });
    s = reduce(s, { type: "handoff.add", chat: "fold:kami:k1", message: "b1", bot: "friren", thread: "th2", now: T0 });
    s = reduce(s, { type: "thread.upsert", bot: "kami", row: { thread: "k1", title: "K", cwd: "", started_at: 1, running: false, needs: false, message_count: 0 } });
    s = reduce(s, { type: "thread.gone", bot: "kami", thread: "k1" });
    expect(Object.keys(s.handoffs)).toEqual(["fold:friren:th1"]);
  });

  it("the bridge connection drops: a working or waiting card stops, and the thread's read after it settles it", () => {
    let s = ev(reduce(handed(), { type: "conn", status: "open" }), { event: "turn.start" });
    s = reduce(s, { type: "conn", status: "closed", now: T0 + 2000 });
    expect(card(s)).toMatchObject({ phase: "stopped", outcome: "interrupted", lost: true });
    expect(card(s).error).toBeTruthy();
    // read again after the reconnect: Friren finished meanwhile
    const read = (msgs: ChatOpenResult["messages"], running = false) =>
      reduce(s, { type: "chat.opened", bot: "fold:friren:th1", res: { ...opened(msgs), running }, now: T0 + 5000, since: T0 + 4000 });
    const done = read([
      { id: "u1", role: "user", text: "Handoff from omher: …", ts: T0 / 1000 },
      { id: "f1", role: "assistant", text: "Five seconds.", ts: T0 / 1000 + 3 },
    ]);
    expect(card(done)).toEqual({ ...card(handed()), phase: "done", answer: "Five seconds." });
    // still running: it works on, and its events move it again
    const going = read([{ id: "u1", role: "user", text: "Handoff from omher: …", ts: T0 / 1000 }], true);
    expect(card(going)).toEqual({ ...card(handed()), phase: "working" });
    expect(card(ev(going, { event: "turn.end", outcome: "done" }, T0 + 6000)).phase).toBe("done");
    // nothing came: stopped, no longer waiting for a read
    expect(card(read([{ id: "u1", role: "user", text: "Handoff from omher: …", ts: T0 / 1000 }]))).toMatchObject({ phase: "stopped", outcome: "ended" });
    // a settled card is not touched by the drop
    const settled = ev(ev(reduce(handed(), { type: "conn", status: "open" }), { event: "turn.start" }), { event: "turn.end", outcome: "done" });
    expect(card(reduce(settled, { type: "conn", status: "closed", now: T0 + 2000 }))).toEqual(card(settled));
  });

  it("a read with no drop before it settles nothing: one between the handed text's send and its turn's start leaves it working", () => {
    // the handed text is sent, the thread is read again (the person opens it) before Hermes starts the turn
    let s = reduce(handed(), { type: "local.user", bot: "fold:friren:th1", id: "local-1", text: "Handoff from omher: …", now: T0 + 10 });
    s = reduce(s, { type: "send.ok", bot: "fold:friren:th1", id: "local-1", now: T0 + 20 });
    s = reduce(s, {
      type: "chat.opened",
      bot: "fold:friren:th1",
      res: opened([{ id: "u1", role: "user", text: "Handoff from omher: …", ts: T0 / 1000 }]),
      now: T0 + 30,
      since: T0 + 25,
    });
    expect(card(s)).toEqual(card(handed()));
    // an answer read while the turn's events still come does not settle it either: the turn's end does
    s = ev(s, { event: "turn.start" }, T0 + 40);
    s = reduce(s, {
      type: "chat.opened",
      bot: "fold:friren:th1",
      res: opened([
        { id: "u1", role: "user", text: "Handoff from omher: …", ts: T0 / 1000 },
        { id: "f1", role: "assistant", text: "Done there.", ts: T0 / 1000 + 3 },
      ]),
      now: T0 + 5000,
      since: T0 + 4000,
    });
    expect(card(s).phase).toBe("working");
    s = ev(s, { event: "message", id: "f1", text: "Done there." }, T0 + 5100);
    s = ev(s, { event: "turn.end", outcome: "done" }, T0 + 5200);
    expect(card(s)).toMatchObject({ phase: "done", answer: "Done there." });
  });

  it("the bot's gateway drops before the turn starts: the card stops, and the thread's next read settles it", () => {
    let s = reduce(handed(), { type: "local.user", bot: "fold:friren:th1", id: "local-1", text: "Handoff from omher: …", now: T0 + 10 });
    s = ev(s, { event: "folder.closed", reason: "gateway disconnected" }, T0 + 20);
    expect(card(s)).toMatchObject({ phase: "stopped", outcome: "interrupted", lost: true, error: "gateway disconnected" });
    s = reduce(s, {
      type: "chat.opened",
      bot: "fold:friren:th1",
      res: { ...opened([{ id: "u1", role: "user", text: "Handoff from omher: …", ts: T0 / 1000 }]), running: true },
      now: T0 + 5000,
      since: T0 + 4000,
    });
    expect(card(s)).toEqual({ ...card(handed()), phase: "working" });
  });

  it("the first send into the thread is refused: no turn starts, and the card stops with the error", () => {
    let s = reduce(handed(), { type: "local.user", bot: "fold:friren:th1", id: "local-1", text: "Handoff from omher: …", now: T0 + 10 });
    s = reduce(s, { type: "send.failed", bot: "fold:friren:th1", id: "local-1", error: "bot is offline" });
    expect(card(s)).toMatchObject({ phase: "stopped", outcome: "error", error: "bot is offline" });
    // a refused send while the thread's turn runs is that turn's own matter
    let t = ev(handed(), { event: "turn.start" });
    t = reduce(t, { type: "send.failed", bot: "fold:friren:th1", id: "local-2", error: "no" });
    expect(card(t).phase).toBe("working");
  });

  it("Given lasts only while its row stands: a refused row or one deleted from the waiting queue offers Give again", () => {
    const done = ev(ev(handed(), { event: "turn.start" }), { event: "turn.end", outcome: "done" });
    const id = card(done).id;
    let s = reduce(done, { type: "handoff.given", chat: "kami", id, row: "local-7" });
    s = reduce(s, { type: "local.user", bot: "kami", id: "local-7", text: "Answer from Friren: …", now: T0 + 10 });
    // another row's failure leaves it given
    expect(card(reduce(s, { type: "send.failed", bot: "kami", id: "local-8", error: "x" })).given).toBe("local-7");
    expect(card(reduce(s, { type: "send.failed", bot: "kami", id: "local-7", error: "bot is offline" })).given).toBeUndefined();
    // held in the waiting queue, then deleted, or cleared with the rest
    let h = reduce(done, { type: "handoff.given", chat: "kami", id, row: "local-7" });
    h = reduce(h, { type: "local.user", bot: "kami", id: "local-7", text: "Answer from Friren: …", now: T0 + 10, held: true });
    expect(card(h).given).toBe("local-7");
    expect(card(reduce(h, { type: "queue.drop", bot: "kami", id: "local-7" })).given).toBeUndefined();
    expect(card(reduce(h, { type: "queue.clear", bot: "kami", ids: ["local-7"] })).given).toBeUndefined();
    // it went out: given stays
    expect(card(reduce(h, { type: "queue.take", bot: "kami", id: "local-7", now: T0 + 20 })).given).toBe("local-7");
  });

  it("Given follows its own row only: sent, then the chat read again, deleting another waiting row leaves it given", () => {
    const done = ev(ev(handed(), { event: "turn.start" }), { event: "turn.end", outcome: "done" });
    const id = card(done).id;
    // Give went out (its row local-7), then Kami's chat is read again: Hermes' copy replaces local-7
    let s = reduce(done, { type: "handoff.given", chat: "kami", id, row: "local-7" });
    s = reduce(s, { type: "local.user", bot: "kami", id: "local-7", text: "Answer from Friren: …", now: T0 + 10 });
    s = reduce(s, { type: "send.ok", bot: "kami", id: "local-7", now: T0 + 20 });
    s = reduce(s, {
      type: "chat.opened",
      bot: "kami",
      res: opened([
        { id: "a1", role: "assistant", text: "Retry three times.", ts: T0 / 1000 - 60 },
        { id: "u7", role: "user", text: "Answer from Friren: …", ts: T0 / 1000 + 0.01 },
      ]),
      now: T0 + 30,
    });
    expect(s.chats.kami.items.some((i) => i.kind === "user" && i.id === "local-7")).toBe(false);
    expect(card(s).given).toBe("local-7");
    // a turn runs and the person types two messages, which wait; deleting one, or clearing both, keeps Give given
    s = reduce(s, { type: "event", ev: { event: "turn.start", bot: "kami" }, now: T0 + 40 });
    s = reduce(s, { type: "local.user", bot: "kami", id: "local-8", text: "and then?", now: T0 + 50, held: true });
    s = reduce(s, { type: "local.user", bot: "kami", id: "local-9", text: "also", now: T0 + 60, held: true });
    expect(s.chats.kami.queue).toEqual(["local-8", "local-9"]);
    const dropped = reduce(s, { type: "queue.drop", bot: "kami", id: "local-8" });
    expect(dropped.chats.kami.queue).toEqual(["local-9"]);
    expect(card(dropped).given).toBe("local-7");
    expect(card(reduce(s, { type: "queue.clear", bot: "kami", ids: ["local-8", "local-9"] })).given).toBe("local-7");
    // a drop of the given row itself, which already went out and is no longer there, changes nothing either
    expect(card(reduce(s, { type: "queue.drop", bot: "kami", id: "local-7" })).given).toBe("local-7");
  });

  it("a held Give deleted before it went out offers Give again; deleting a row beside it does not", () => {
    const done = ev(ev(handed(), { event: "turn.start" }), { event: "turn.end", outcome: "done" });
    const id = card(done).id;
    let h = reduce(done, { type: "handoff.given", chat: "kami", id, row: "local-7" });
    h = reduce(h, { type: "local.user", bot: "kami", id: "local-7", text: "Answer from Friren: …", now: T0 + 10, held: true });
    h = reduce(h, { type: "local.user", bot: "kami", id: "local-8", text: "and then?", now: T0 + 20, held: true });
    expect(card(reduce(h, { type: "queue.drop", bot: "kami", id: "local-8" })).given).toBe("local-7");
    expect(card(reduce(h, { type: "queue.clear", bot: "kami", ids: ["local-8"] })).given).toBe("local-7");
    expect(card(reduce(h, { type: "queue.drop", bot: "kami", id: "local-7" })).given).toBeUndefined();
    expect(card(reduce(h, { type: "queue.clear", bot: "kami", ids: ["local-7", "local-8"] })).given).toBeUndefined();
  });

  it("a thread's link line under the answer goes below its handoff card, not above it", () => {
    const s = reduce(handed(), {
      type: "thread.note",
      bot: "kami",
      message: "a1",
      item: { kind: "threadLink", id: "tl-1", ts: T0 / 1000, bot: "kami", thread: "x", title: "X" },
    });
    expect(s.chats.kami.items.map((i) => i.kind)).toEqual(["assistant", "handoff", "threadLink"]);
  });

  it("events of an unrelated thread, the bot's main chat or another bot never touch it", () => {
    const s = handed();
    const others: Action[] = [
      { type: "event", ev: { event: "turn.end", bot: "friren", session: "th2", outcome: "interrupted" }, now: T0 + 1 },
      { type: "event", ev: { event: "approval.request", bot: "friren", request_id: "r9", title: "x", command: "x", choices: ["deny"] } as never, now: T0 + 1 },
      { type: "event", ev: { event: "turn.end", bot: "friren", outcome: "done" }, now: T0 + 1 },
      { type: "event", ev: { event: "turn.end", bot: "kami", session: "th1", outcome: "error", error: "no" }, now: T0 + 1 },
      { type: "thread.gone", bot: "friren", thread: "th2" },
    ];
    let t = s;
    for (const a of others) t = reduce(t, a);
    expect(card(t)).toEqual(card(s));
  });
});
