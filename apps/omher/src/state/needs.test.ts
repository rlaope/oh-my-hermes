// Needs you: open asks across bots, expiry, interview answers, ⌘J order, the roster and pinned sidebar order.
import { describe, expect, it } from "vitest";
import { askFrom, askOpen, askText, folderKey, initialState, reduce, seedRoster, selectAsks, selectSidebarBots, selectUnlisted, setChatRoute, type Action, type AppState } from "./store";
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

describe("SESSIONS chats in the one ask model", () => {
  it("a session chat's ask (agent or Hermes folder chat) is listed with the bots', named by its route, and leaves with the chat", () => {
    const fold = folderKey("kami", "f1");
    let s = run(initialState(), [
      { event: "turn.start", bot: "friren" },
      approval("friren", "a1"),
      { event: "turn.start", bot: "agent:s1" },
      approval("agent:s1", "req-1"),
      // a folder chat's events arrive tagged with `session` and land under the folder key
      { event: "turn.start", bot: "kami", session: "f1" },
      { event: "clarify.request", bot: "kami", session: "f1", request_id: "iv", question: "Who?", questions: [{ qid: "q1", question: "Who?" }, { qid: "q2", question: "When?" }], timeout_s: 60 },
    ]);
    expect(selectAsks(s).map((a) => [a.bot, a.item.request_id])).toEqual([
      ["friren", "a1"],
      ["agent:s1", "req-1"],
      [fold, "iv"],
    ]);
    expect(s.chats.kami?.items ?? []).toEqual([]); // the bot's own chat never gets a folder chat's ask
    setChatRoute("agent:s1", {
      label: "web-app · Claude Code",
      open: () => undefined,
      send: async () => undefined,
      interrupt: async () => undefined,
      approve: async () => undefined,
      clarify: async () => undefined,
    });
    expect(askFrom(s, "agent:s1")).toBe("web-app · Claude Code");
    expect(askFrom(s, "agent:gone")).toBe("agent:gone");
    setChatRoute("agent:s1", null);
    // expiry of a folder chat's ask (prompt.expired tagged with `session`) closes it like a bot's
    s = run(s, [{ event: "prompt.expired", bot: "kami", session: "f1", request_id: "iv", reason: "timeout" }]);
    expect(selectAsks(s).map((a) => a.bot)).toEqual(["friren", "agent:s1"]);
    // a closed session takes its open asks with it
    s = reduce(s, { type: "chat.forget", bot: "agent:s1" });
    expect(selectAsks(s).map((a) => a.bot)).toEqual(["friren"]);
    expect(s.chats["agent:s1"]).toBeUndefined();
  });

  // Claude Code 2.1.322 runs a subagent in the background: the turn ends (`result`), then the subagent asks
  // (claude-13-late-ask.jsonl), or asks during the turn and the turn ends with the ask open (…-inside.jsonl). Claude
  // Code waits for both answers; the subagent's row is still running.
  const sub = (state: string, extra: Record<string, unknown> = {}): BridgeEvent =>
    ({ event: "subagent", bot: "agent:s1", id: "toolu_1", agent: "claude", name: "general-purpose", goal: "Write gamma to c.txt", delegation: "claude-msg_1", index: 0, count: 1, state, ...extra }) as BridgeEvent;
  const subAsk = (id: string): BridgeEvent => ({ ...approval("agent:s1", id), subagent: { id: "toolu_1", name: "Write gamma to c.txt" } }) as BridgeEvent;
  const started = (): AppState =>
    run(initialState(), [
      { event: "turn.start", bot: "agent:s1" },
      { event: "tool.start", bot: "agent:s1", tool_id: "toolu_1", name: "delegate_task", detail: "Write gamma to c.txt" },
      sub("running"),
      { event: "tool.end", bot: "agent:s1", tool_id: "toolu_1", name: "", ok: true, ms: 0 },
    ]);
  const open = (s: AppState) => selectAsks(s).filter((a) => a.bot === "agent:s1").map((a) => a.item.request_id);

  it("a background subagent's ask that comes after its turn ended is open, in Needs you, until answered", () => {
    let s = run(started(), [{ event: "turn.end", bot: "agent:s1", outcome: "done" }, subAsk("late")], T0 + 10_000);
    expect(s.chats["agent:s1"].turn).toBeNull();
    expect(open(s)).toEqual(["late"]);
    const it = s.chats["agent:s1"].items.find((i) => i.kind === "approval")!;
    expect(askOpen(s.chats["agent:s1"].items, it as never)).toBe(true);
    s = reduce(s, { type: "approval.resolved", bot: "agent:s1", request_id: "late", choice: "once" });
    expect(open(s)).toEqual([]);
  });

  it("a background subagent's ask left open at its turn's end stays open while the subagent runs", () => {
    const s = run(started(), [subAsk("in"), { event: "turn.end", bot: "agent:s1", outcome: "done" }], T0 + 10_000);
    expect(open(s)).toEqual(["in"]);
    // the subagent ended (its notification): what it asked is no longer waited for
    expect(open(run(s, [sub("done", { summary: "WROTE" })], T0 + 20_000))).toEqual([]);
  });

  it("an ask with no subagent still closes with its turn; a late one closes when the agent withdraws it", () => {
    expect(open(run(initialState(), [{ event: "turn.start", bot: "agent:s1" }, approval("agent:s1", "a"), { event: "turn.end", bot: "agent:s1", outcome: "done" }]))).toEqual([]);
    let s = run(started(), [{ event: "turn.end", bot: "agent:s1", outcome: "done" }, approval("agent:s1", "b")], T0 + 10_000);
    expect(open(s)).toEqual(["b"]);
    s = run(s, [{ event: "prompt.expired", bot: "agent:s1", request_id: "b", reason: "cancelled" }], T0 + 20_000);
    expect(open(s)).toEqual([]);
  });

  it("the bot chat keeps its rule: an ask inside a turn closes with it, also after another turn", () => {
    const s = run(initialState(), [{ event: "turn.start", bot: "kami" }, approval("kami", "k1"), { event: "turn.end", bot: "kami", outcome: "done" }, { event: "turn.start", bot: "kami" }]);
    expect(selectAsks(s)).toEqual([]);
  });

  it("⌘J walks bot and session asks in one age order", () => {
    const s = run(initialState(), [approval("friren", "a1"), approval("agent:s1", "req-1")]);
    const asks = selectAsks(s);
    expect(nextAsk(asks, { bot: "friren", id: "approval-a1", seq: 1 })).toMatchObject({ bot: "agent:s1" });
    expect(nextAsk(asks, { bot: "agent:s1", id: "approval-req-1", seq: 2 })).toMatchObject({ bot: "friren" });
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
  it("lists only roster bots Hermes still reports, pinned first in pin order, then in the order they joined", () => {
    let s = reduce(initialState(), { type: "bots", bots: ["kami", "friren", "default", "omh-tui"].map(bot) });
    // no roster yet: nothing listed, everything offered under +
    expect(selectSidebarBots(s)).toEqual([]);
    expect(selectUnlisted(s).map((b) => b.name)).toEqual(["kami", "friren", "default", "omh-tui"]);
    s = reduce(s, { type: "ui.roster", roster: ["default", "kami", "gone"] });
    expect(selectSidebarBots(s).map((b) => b.name)).toEqual(["default", "kami"]);
    expect(selectUnlisted(s).map((b) => b.name)).toEqual(["friren", "omh-tui"]);
    s = reduce(s, { type: "ui.roster", roster: ["default", "kami", "gone", "friren"] });
    s = reduce(s, { type: "ui.pin", bot: "friren", on: true });
    s = reduce(s, { type: "ui.pin", bot: "omh-tui", on: true }); // pinned but not listed: not shown
    expect(selectSidebarBots(s).map((b) => b.name)).toEqual(["friren", "default", "kami"]);
    s = reduce(s, { type: "ui.roster", roster: ["default", "kami"] });
    expect(selectSidebarBots(s).map((b) => b.name)).toEqual(["default", "kami"]);
  });
});

describe("the first roster", () => {
  const bots = ["kami", "friren", "default", "omh-tui"].map(bot).map((b) => (b.name === "default" ? { ...b, is_default: true } : b));
  it("fresh install: the default profile alone (else the first bot)", () => {
    expect(seedRoster(bots, null, [], [])).toEqual(["default"]);
    expect(seedRoster(bots.filter((b) => b.name !== "default"), null, [], [])).toEqual(["kami"]);
    expect(seedRoster([], null, [], [])).toEqual([]);
  });
  it("a person who used omher: the bot saved for resume, then pinned bots that still exist; hidden ones never", () => {
    expect(seedRoster(bots, "kami", [], [])).toEqual(["kami"]);
    expect(seedRoster(bots, "kami", ["friren", "gone", "kami"], [])).toEqual(["kami", "friren"]);
    expect(seedRoster(bots, "gone", ["omh-tui"], [])).toEqual(["omh-tui"]);
    expect(seedRoster(bots, "kami", ["friren"], ["kami"])).toEqual(["friren"]);
    // everything saved is hidden or gone: one bot, the default, as on a fresh install
    expect(seedRoster(bots, "gone", [], [])).toEqual(["default"]);
    expect(seedRoster(bots, "kami", [], ["kami", "default"])).toEqual(["friren"]);
  });
});
