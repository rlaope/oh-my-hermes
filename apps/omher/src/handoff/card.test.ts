// The "Handed to <bot>" card as the store's reducer moves it from the target thread's own events (rule 56).
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
    s = reduce(s, { type: "handoff.given", chat: "kami", id: card(s).id });
    expect(card(s).given).toBe(true);
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
    s = reduce(s, { type: "handoff.given", chat: "kami", id: card(s).id });
    expect(card(s).given).toBeUndefined();
  });

  it("the thread removed: the card says it is gone, whatever came before", () => {
    let s = ev(handed(), { event: "turn.start" });
    s = reduce(s, { type: "thread.upsert", bot: "friren", row: { thread: "th1", title: "From Kami", cwd: "", started_at: 1, running: false, needs: false, message_count: 0 } });
    s = reduce(s, { type: "thread.gone", bot: "friren", thread: "th1" });
    expect(card(s).phase).toBe("gone");
    expect(ev(s, { event: "turn.end", outcome: "done" }).chats.kami).toBe(s.chats.kami);
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
