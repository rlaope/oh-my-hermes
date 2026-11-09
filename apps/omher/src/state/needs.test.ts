// Needs you: open asks across bots, expiry, interview answers, ⌘J order, pinned/hidden sidebar order.
import { describe, expect, it } from "vitest";
import { askText, initialState, reduce, selectAsks, selectSidebarBots, type Action, type AppState } from "./store";
import type { Bot, BridgeEvent } from "../lib/protocol";
import { answerOf } from "../chat/cards/answers";
import { nextAsk, shortcutFor } from "../app/shortcuts";

const T0 = 1_800_000_000_000;
const bot = (name: string): Bot => ({
  name,
  display_name: name[0].toUpperCase() + name.slice(1),
  is_default: false,
  model: "m",
  provider: "p",
  description: "",
  status: "online",
  running: false,
});

function run(state: AppState, evs: BridgeEvent[], t = T0): AppState {
  let s = state;
  evs.forEach((ev, i) => {
    s = reduce(s, { type: "event", ev, now: t + i * 1000 } as Action);
  });
  return s;
}

const approval = (b: string, id: string): BridgeEvent => ({
  event: "approval.request",
  bot: b,
  request_id: id,
  title: "Run shell command",
  command: "rm -rf build/",
  choices: ["once", "session", "deny"],
});

describe("selectAsks", () => {
  it("lists open approvals and questions across bots, oldest first, and drops answered or expired ones", () => {
    let s = run(initialState(), [
      { event: "turn.start", bot: "friren" },
      approval("friren", "a1"),
      { event: "turn.start", bot: "default" },
      { event: "clarify.request", bot: "default", request_id: "c1", question: "Which env?", choices: ["a", "b"] },
    ]);
    expect(selectAsks(s).map((a) => [a.bot, a.item.request_id])).toEqual([
      ["friren", "a1"],
      ["default", "c1"],
    ]);
    expect(selectAsks(s)).toBe(selectAsks(s)); // memoised for render
    s = reduce(s, { type: "approval.resolved", bot: "friren", request_id: "a1", choice: "deny" });
    expect(selectAsks(s).map((a) => a.item.request_id)).toEqual(["c1"]);
    s = run(s, [{ event: "prompt.expired", bot: "default", request_id: "c1", reason: "timeout" }]);
    expect(selectAsks(s)).toEqual([]);
    const c1 = s.chats.default.items.find((i) => i.kind === "clarify");
    expect(c1 && c1.kind === "clarify" && c1.expired).toBe("timeout");
  });

  it("an ask whose turn ended unanswered is no longer open; a replayed ask is not added twice", () => {
    let s = run(initialState(), [{ event: "turn.start", bot: "kami" }, approval("kami", "a1"), approval("kami", "a1")]);
    expect(s.chats.kami.items.filter((i) => i.kind === "approval")).toHaveLength(1);
    expect(selectAsks(s)).toHaveLength(1);
    s = run(s, [{ event: "turn.end", bot: "kami", outcome: "interrupted" }], T0 + 10_000);
    expect(selectAsks(s)).toEqual([]);
  });

  it("an interview keeps every question; the sidebar line says how many", () => {
    const s = run(initialState(), [
      {
        event: "clarify.request",
        bot: "friren",
        request_id: "iv",
        question: "Who is it for?",
        questions: [
          { qid: "q1", question: "Who is it for?", choices: ["Users", "Devs"] },
          { qid: "q2", question: "Sections?", choices: ["Fixes", "Thanks"], multi_select: true },
          { qid: "q3", question: "Leave out?" },
        ],
      },
    ]);
    const [a] = selectAsks(s);
    expect(a.item.kind === "clarify" && a.item.questions?.map((q) => q.qid)).toEqual(["q1", "q2", "q3"]);
    expect(askText(a.item)).toBe("3 questions: Who is it for?");
    expect(askText(run(initialState(), [approval("kami", "x")]).chats.kami.items[0] as never)).toBe("Allow `rm -rf build/`?");
  });

  it("an interview answered in one go keeps the per-question answers", () => {
    let s = run(initialState(), [{ event: "clarify.request", bot: "kami", request_id: "iv", question: "q", questions: [{ qid: "a", question: "A" }, { qid: "b", question: "B" }] }]);
    s = reduce(s, { type: "clarify.resolved", bot: "kami", request_id: "iv", answer: "1 of 2", answers: { a: "x", b: null } });
    const it = s.chats.kami.items[0];
    expect(it.kind === "clarify" && [it.answer, it.answers]).toEqual(["1 of 2", { a: "x", b: null }]);
  });
});

describe("answerOf", () => {
  it("single choice, Other text, multi-select as a JSON array, and skipped", () => {
    expect(answerOf({ chosen: ["Users"], other: "" }, false)).toBe("Users");
    expect(answerOf({ chosen: [], other: "  the beta " }, false)).toBe("the beta");
    expect(answerOf({ chosen: ["Fixes", "Thanks"], other: "Docs" }, true)).toBe('["Fixes","Thanks","Docs"]');
    expect(answerOf({ chosen: [], other: " " }, true)).toBeNull();
    expect(answerOf({ chosen: [], other: "" }, false)).toBeNull();
  });
});

describe("⌘J", () => {
  it("is a shortcut, and walks the open asks oldest first, wrapping", () => {
    expect(shortcutFor({ key: "j", metaKey: true, ctrlKey: false, altKey: false, shiftKey: false }, true)).toEqual({ kind: "next-ask" });
    expect(shortcutFor({ key: "1", metaKey: false, ctrlKey: false, altKey: false, shiftKey: false }, true)).toBeNull();
    const s = run(initialState(), [approval("friren", "a1"), approval("default", "a2")]);
    const asks = selectAsks(s);
    expect(nextAsk([], null)).toBeNull();
    expect(nextAsk(asks, null)?.item.request_id).toBe("a1");
    expect(nextAsk(asks, { bot: "friren", id: "approval-a1", seq: 1 })?.item.request_id).toBe("a2");
    expect(nextAsk(asks, { bot: "default", id: "approval-a2", seq: 2 })?.item.request_id).toBe("a1");
  });
});

describe("sidebar order", () => {
  it("pinned bots come first in pin order; hidden bots are left out", () => {
    let s = reduce(initialState(), { type: "bots", bots: ["kami", "friren", "default"].map(bot) });
    expect(selectSidebarBots(s).map((b) => b.name)).toEqual(["kami", "friren", "default"]);
    s = reduce(s, { type: "ui.pin", bot: "default", on: true });
    s = reduce(s, { type: "ui.pin", bot: "friren", on: true });
    expect(selectSidebarBots(s).map((b) => b.name)).toEqual(["default", "friren", "kami"]);
    s = reduce(s, { type: "ui.hide", bot: "friren", on: true });
    expect(selectSidebarBots(s).map((b) => b.name)).toEqual(["default", "kami"]);
    s = reduce(s, { type: "ui.pin", bot: "default", on: false });
    s = reduce(s, { type: "ui.hide", bot: "friren", on: false });
    expect(selectSidebarBots(s).map((b) => b.name)).toEqual(["friren", "kami", "default"]);
  });
});
