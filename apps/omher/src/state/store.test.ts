import { describe, expect, it } from "vitest";
import {
  activityText,
  chatRoute,
  createStore,
  folderKey,
  setChatRoute,
  initialState,
  reduce,
  replyChipFor,
  selectTimeline,
  type Action,
  type AppState,
  type BridgeLike,
} from "./store";
import type { Away, BridgeEvent, ChatOpenResult } from "../lib/protocol";
import type { BridgeStatus } from "../lib/bridge";

// The recorded Hermes turn (real-turn-events.json), already converted to protocol events.
const T0 = 1_800_000_000_000;
const realTurn = (bot: string): BridgeEvent[] => [
  { event: "turn.start", bot },
  { event: "status", bot, text: "OMH — recalled 6 memories" },
  { event: "thinking", bot },
  { event: "tool.start", bot, tool_id: "toolu_1", name: "terminal", detail: "echo omher-probe" },
  { event: "tool.end", bot, tool_id: "toolu_1", name: "terminal", ok: true, ms: 420 },
  { event: "delta", bot, text: "`echo omher" },
  { event: "delta", bot, text: "-probe` 결과 `omher-probe`가 출력됐고 exit code는 0입니다." },
  { event: "message", bot, id: "m-1", text: "`echo omher-probe` 결과 `omher-probe`가 출력됐고 exit code는 0입니다." },
  { event: "turn.end", bot, outcome: "done" },
];

function run(state: AppState, evs: BridgeEvent[], t = T0, step = 500): AppState {
  let s = state;
  evs.forEach((ev, i) => {
    s = reduce(s, { type: "event", ev, now: t + i * step } as Action);
  });
  return s;
}

const opened = (over: Partial<ChatOpenResult> = {}): ChatOpenResult => ({
  session_id: "s1",
  messages: [{ id: "h1", role: "user", text: "hi", ts: T0 / 1000 - 100 }],
  running: false,
  model: "Opus 5.5",
  provider: "claude-proxy",
  reasoning: "high",
  ...over,
});

const away = (id: string, last_active: number, over: Partial<Away> = {}): Away => ({
  id,
  source: "slack",
  label: id,
  title: id,
  started_at: last_active - 60,
  last_active,
  message_count: 3,
  running: false,
  ...over,
});

describe("activityText", () => {
  it("maps tool names to verbs", () => {
    expect(activityText("terminal", "ls")).toBe("Running ls");
    expect(activityText("read_file", "a.ts")).toBe("Reading a.ts");
    expect(activityText("search_files", "foo")).toBe("Searching foo");
    expect(activityText("web_search", "x")).toBe("Searching the web x");
    expect(activityText("web_extract", "u")).toBe("Reading u");
    expect(activityText("write_file", "f")).toBe("Editing f");
    expect(activityText("patch", "f")).toBe("Editing f");
    expect(activityText("delegate_task", "t")).toBe("Asking t");
    expect(activityText("skill_view", "plan")).toBe("Using skill plan");
    expect(activityText("custom_tool", "x")).toBe("custom_tool x");
    expect(activityText("terminal", "")).toBe("Running");
  });
});

describe("reducer: a full turn", () => {
  it("builds one activity with steps and the answer after it", () => {
    let s = reduce(initialState(), { type: "chat.opened", bot: "kami", res: opened(), now: T0 - 1000 });
    s = reduce(s, { type: "local.user", bot: "kami", id: "local-1", text: "run it", now: T0 - 500 });
    s = run(s, realTurn("kami"));
    const chat = s.chats.kami;
    const kinds = chat.items.map((i) => i.kind);
    expect(kinds).toEqual(["user", "user", "activity", "assistant"]);
    expect(chat.items.filter((i) => i.kind === "activity")).toHaveLength(1);
    expect(chat.turn).toBeNull();
    const t = chat.lastTurn!;
    expect(t.outcome).toBe("done");
    expect(t.steps).toHaveLength(1);
    expect(t.steps[0]).toMatchObject({ id: "toolu_1", name: "terminal", detail: "echo omher-probe", ok: true });
    expect(t.endedAt! - t.startedAt).toBe(8 * 500);
    expect(t.streaming).toBe("");
    expect(chat.messages.at(-1)).toMatchObject({ role: "assistant", id: "m-1" });
    expect(chat.messages.at(-1)!.text).toContain("omher-probe");
    const act = chat.items.find((i) => i.kind === "activity");
    expect(act && act.kind === "activity" && act.turn.outcome).toBe("done");
  });

  it("shows the latest tool text while running, then status text", () => {
    let s = run(initialState(), realTurn("kami").slice(0, 4));
    expect(s.chats.kami.turn!.status).toBe("Running echo omher-probe");
    s = run(s, [{ event: "status", bot: "kami", text: "Summarising" }]);
    expect(s.chats.kami.turn!.status).toBe("Summarising");
    s = run(s, [{ event: "delta", bot: "kami", text: "ab" }, { event: "delta", bot: "kami", text: "cd" }]);
    expect(s.chats.kami.turn!.streaming).toBe("abcd");
  });

  it("a status, thinking, step or text outside a turn starts none; a status just before turn.start opens it", () => {
    // Hermes says a goal or loop verdict after the turn's message.complete (prompt_turn._goal_followup_after_turn):
    // it must not start a turn nothing ends
    let s = run(initialState(), realTurn("kami"));
    s = run(s, [
      { event: "status", bot: "kami", text: "Goal reached" },
      { event: "thinking", bot: "kami" },
      { event: "tool.start", bot: "kami", tool_id: "x", name: "terminal", detail: "ls" },
      { event: "tool.end", bot: "kami", tool_id: "x", name: "terminal", ok: true, ms: 1 },
      { event: "skill", bot: "kami", name: "plan" },
      { event: "delta", bot: "kami", text: "late" },
    ], T0 + 10_000);
    expect(s.chats.kami.turn).toBeNull();
    expect(s.chats.kami.items.filter((i) => i.kind === "activity")).toHaveLength(1);
    // auto-continue: "Resuming interrupted turn…" comes right before message.start, so the turn opens with it
    s = run(s, [{ event: "status", bot: "kami", text: "Resuming interrupted turn…" }, { event: "turn.start", bot: "kami" }], T0 + 60_000);
    expect(s.chats.kami.turn!.status).toBe("Resuming interrupted turn…");
    s = run(s, [{ event: "turn.end", bot: "kami", outcome: "done" }], T0 + 61_000);
    // a status from long before does not
    s = run(s, [{ event: "status", bot: "kami", text: "old" }], T0 + 70_000);
    s = run(s, [{ event: "turn.start", bot: "kami" }], T0 + 90_000);
    expect(s.chats.kami.turn!.status).toBe("");
  });

  it("a session chat's turn.end after Stop stays ended when the agent's status comes later", () => {
    const key = "agent:s9";
    let s = run(initialState(), [{ event: "turn.start", bot: key }, { event: "status", bot: key, text: "Working on it" }]);
    s = run(s, [{ event: "turn.end", bot: key, outcome: "interrupted" }, { event: "status", bot: key, text: "(😺 OmO Native)" }], T0 + 5_000);
    expect(s.chats[key].turn).toBeNull();
    expect(s.chats[key].lastTurn!.outcome).toBe("interrupted");
  });

  it("an answered card puts the live line back to the turn's work, not \"Waiting for approval\"", () => {
    // audit O7 (claude-A): approve, then the command runs and the answer streams under the old waiting line
    let s = run(initialState(), [
      { event: "turn.start", bot: "kami" },
      { event: "tool.start", bot: "kami", tool_id: "b1", name: "terminal", detail: "echo one > one.txt" },
      { event: "approval.request", bot: "kami", request_id: "r1", title: "Run this command?", command: "echo one > one.txt", choices: ["once", "deny"] },
    ]);
    expect(s.chats.kami.turn!.status).toBe("Waiting for approval");
    s = reduce(s, { type: "approval.resolved", bot: "kami", request_id: "r1", choice: "once" });
    expect(s.chats.kami.turn!.status).toBe(activityText("terminal", "echo one > one.txt"));
    s = run(s, [{ event: "tool.end", bot: "kami", tool_id: "b1", name: "terminal", ok: true, ms: 5 }]);
    // a question with no step running goes back to the plain working line
    s = run(s, [{ event: "clarify.request", bot: "kami", request_id: "q1", question: "Red or blue?", choices: ["Red", "Blue"] }]);
    expect(s.chats.kami.turn!.status).toBe("Waiting for your answer");
    s = reduce(s, { type: "clarify.resolved", bot: "kami", request_id: "q1", answer: "Blue" });
    expect(s.chats.kami.turn!.status).toBe("");
    // two cards: answering one keeps waiting for the other
    s = run(s, [
      { event: "approval.request", bot: "kami", request_id: "r2", title: "Run?", command: "a", choices: ["once", "deny"] },
      { event: "approval.request", bot: "kami", request_id: "r3", title: "Run?", command: "b", choices: ["once", "deny"] },
    ]);
    s = reduce(s, { type: "approval.resolved", bot: "kami", request_id: "r2", choice: "once" });
    expect(s.chats.kami.turn!.status).toBe("Waiting for approval");
    s = reduce(s, { type: "approval.resolved", bot: "kami", request_id: "r3", choice: "deny" });
    expect(s.chats.kami.turn!.status).toBe("");
    // the agent's own status is never rewritten
    s = run(s, [{ event: "status", bot: "kami", text: "Compacting" }]);
    s = reduce(s, { type: "approval.resolved", bot: "kami", request_id: "r3", choice: "deny" });
    expect(s.chats.kami.turn!.status).toBe("Compacting");
  });

  it("collects skill chips once", () => {
    const s = run(initialState(), [
      { event: "turn.start", bot: "kami" },
      { event: "skill", bot: "kami", name: "plan" },
      { event: "skill", bot: "kami", name: "plan" },
      { event: "skill", bot: "kami", name: "docx" },
    ]);
    expect(s.chats.kami.turn!.skills).toEqual(["plan", "docx"]);
  });

  it("keeps streamed text when a done turn never sent a final message", () => {
    const s = run(initialState(), [
      { event: "turn.start", bot: "kami" },
      { event: "delta", bot: "kami", text: "partial answer" },
      { event: "turn.end", bot: "kami", outcome: "done" },
    ]);
    expect(s.chats.kami.messages.at(-1)).toMatchObject({ role: "assistant", text: "partial answer" });
  });

  it("a step still running when the turn is stopped reads as stopped, not finished (a bot's turn too)", () => {
    // audit O11: the bot chat shares this reducer; a step Stop cut short is not ok, and is marked stopped
    const s = run(initialState(), [
      { event: "turn.start", bot: "kami" },
      { event: "tool.start", bot: "kami", tool_id: "a", name: "terminal", detail: "sleep 9" },
      { event: "tool.start", bot: "kami", tool_id: "b", name: "read_file", detail: "a.txt" },
      { event: "tool.end", bot: "kami", tool_id: "b", name: "", ok: true, ms: 10 },
      { event: "turn.end", bot: "kami", outcome: "interrupted" },
    ]);
    const t = s.chats.kami.lastTurn!;
    expect(t.outcome).toBe("interrupted");
    expect(t.steps[0]).toMatchObject({ ok: false, stopped: true });
    expect(t.steps[0].endedAt).toBeDefined();
    // a step that had ended before Stop keeps its own end
    expect(t.steps[1]).toMatchObject({ ok: true });
    expect(t.steps[1].stopped).toBeUndefined();
  });

  it("a stopped turn's time is from its start to the Stop, on the recorded stream's clock (codex-B: 6.1 s)", () => {
    // audit O11 follow-up: "Stopped after 0s" beside a step that ran on. codex-B.events.jsonl: turn.start at 8.684 s,
    // tool.start (sleep 40) at 11.712 s, turn.end interrupted at 14.784 s
    let s = run(initialState(), [{ event: "turn.start", bot: "agent:s1" }], 8_684);
    s = run(s, [{ event: "tool.start", bot: "agent:s1", tool_id: "a", name: "terminal", detail: "sleep 40; echo late" }], 11_712);
    s = run(s, [{ event: "turn.end", bot: "agent:s1", outcome: "interrupted" }], 14_784);
    const t = s.chats["agent:s1"].lastTurn!;
    expect(t.endedAt! - t.startedAt).toBe(6_100);
    expect(t.steps[0].endedAt! - t.steps[0].startedAt).toBe(3_072);
  });

  it("a turn that ends on its own leaves no step marked stopped", () => {
    for (const outcome of ["done", "ended", "error"] as const) {
      const s = run(initialState(), [
        { event: "turn.start", bot: "kami" },
        { event: "tool.start", bot: "kami", tool_id: "a", name: "terminal", detail: "sleep 9" },
        { event: "turn.end", bot: "kami", outcome },
      ]);
      expect(s.chats.kami.lastTurn!.steps[0].stopped, outcome).toBeUndefined();
      expect(s.chats.kami.lastTurn!.steps[0].ok, outcome).toBeUndefined();
    }
  });

  it("the end of a stopped step reported after its turn goes to that step; any other late end is dropped", () => {
    const s0 = run(initialState(), [
      { event: "turn.start", bot: "kami" },
      { event: "tool.start", bot: "kami", tool_id: "a", name: "terminal", detail: "sleep 40; echo late" },
      { event: "turn.end", bot: "kami", outcome: "interrupted" },
      { event: "turn.start", bot: "kami" },
      { event: "turn.end", bot: "kami", outcome: "done" },
    ]);
    const s = run(s0, [{ event: "tool.end", bot: "kami", tool_id: "a", name: "", ok: true, ms: 39_887 }], T0 + 60_000);
    const acts = s.chats.kami.items.filter((i) => i.kind === "activity");
    expect(acts).toHaveLength(2);
    const step = acts[0].kind === "activity" ? acts[0].turn.steps[0] : null;
    expect(step).toMatchObject({ ok: false, stopped: true, late: { ok: true, ms: 39_887, endedAt: T0 + 60_000 } });
    // nothing else moved: no new turn, the later turn untouched
    expect(s.chats.kami.turn).toBeNull();
    expect(acts[1].kind === "activity" && acts[1].turn.steps).toEqual([]);
    // an unknown step's end outside a turn changes nothing
    expect(run(s, [{ event: "tool.end", bot: "kami", tool_id: "zz", name: "", ok: true, ms: 1 }], T0 + 61_000).chats.kami).toBe(s.chats.kami);
  });

  it("the agent's own retry shows on the live line as which try it is", () => {
    const s = run(initialState(), [
      { event: "turn.start", bot: "agent:s1" },
      { event: "status", bot: "agent:s1", text: "Retrying 1 of 5", retry: { attempt: 1, max: 5 } },
    ]);
    expect(s.chats["agent:s1"].turn!.status).toBe("Retrying 1 of 5");
  });

  it("a second turn gets its own activity row", () => {
    let s = run(initialState(), realTurn("kami"));
    s = run(s, [{ event: "turn.start", bot: "kami" }, { event: "turn.end", bot: "kami", outcome: "done" }], T0 + 60_000);
    expect(s.chats.kami.items.filter((i) => i.kind === "activity")).toHaveLength(2);
  });
});

describe("reducer: approvals and clarifications", () => {
  const approval: BridgeEvent = {
    event: "approval.request",
    bot: "kami",
    request_id: "ap1",
    title: "Run command",
    command: "rm -rf build",
    choices: ["once", "session", "always", "deny"],
  };

  it("adds a card, then marks it resolved", () => {
    let s = run(initialState(), [{ event: "turn.start", bot: "kami" }, approval]);
    const card = s.chats.kami.items.find((i) => i.kind === "approval");
    expect(card).toMatchObject({ request_id: "ap1", command: "rm -rf build" });
    expect(s.chats.kami.turn!.status).toBe("Waiting for approval");
    s = reduce(s, { type: "approval.resolved", bot: "kami", request_id: "ap1", choice: "deny" });
    expect(s.chats.kami.items.find((i) => i.kind === "approval")).toMatchObject({ resolved: "deny" });
  });

  it("clarify card records the answer", () => {
    let s = run(initialState(), [{ event: "clarify.request", bot: "kami", request_id: "c1", question: "Which?", choices: ["a", "b"] }]);
    expect(s.chats.kami.items.find((i) => i.kind === "clarify")).toMatchObject({ question: "Which?" });
    s = reduce(s, { type: "clarify.resolved", bot: "kami", request_id: "c1", answer: "a" });
    expect(s.chats.kami.items.find((i) => i.kind === "clarify")).toMatchObject({ answer: "a" });
  });
});

describe("elsewhere ordering", () => {
  it("places away lines by last_active among chat rows, capped to the 2 most recent", () => {
    const base = T0 / 1000;
    let s = reduce(initialState(), {
      type: "chat.opened",
      bot: "kami",
      res: opened({
        messages: [
          { id: "a", role: "user", text: "one", ts: base - 1000 },
          { id: "b", role: "assistant", text: "two", ts: base - 500 },
          { id: "c", role: "user", text: "three", ts: base - 100 },
        ],
      }),
      now: T0,
    });
    s = reduce(s, {
      type: "elsewhere",
      bot: "kami",
      sessions: [away("old", base - 2000), away("mid", base - 300), away("new", base - 50), away("mid2", base - 700)],
    });
    expect(s.elsewhere.kami.map((a) => a.id)).toEqual(["new", "mid", "mid2", "old"]); // newest first
    const tl = selectTimeline(s, "kami");
    expect(tl.map((i) => i.id)).toEqual(["a", "b", "away-mid", "c", "away-new"]);
    expect(selectTimeline(s, "kami")).toBe(tl); // memoised
    expect(selectTimeline(s, "kami", 4).map((i) => i.id)).toContain("away-old");
  });
});

describe("unread", () => {
  it("counts assistant messages and routine lines for unselected bots only", () => {
    let s = reduce(initialState(), { type: "select", bot: "kami" });
    s = run(s, [{ event: "message", bot: "friren", id: "x1", text: "hello" }]);
    s = run(s, [{ event: "routine.ran", bot: "friren", routine_id: "r1", name: "Repo watch", status: "ok", ts: T0 / 1000 }]);
    s = run(s, [{ event: "message", bot: "kami", id: "k1", text: "mine" }]);
    expect(s.unread.friren).toBe(2);
    expect(s.unread.kami ?? 0).toBe(0);
    expect(s.chats.friren.items.some((i) => i.kind === "routine")).toBe(true);
    s = reduce(s, { type: "select", bot: "friren" });
    expect(s.unread.friren).toBe(0);
  });

  it("does not double count a message re-delivered with the same id", () => {
    let s = reduce(initialState(), { type: "select", bot: "kami" });
    const ev: BridgeEvent = { event: "message", bot: "friren", id: "x1", text: "hello" };
    s = run(s, [ev, ev]);
    expect(s.unread.friren).toBe(1);
    expect(s.chats.friren.messages).toHaveLength(1);
  });
});

describe("chat.opened merging", () => {
  it("drops a local user row once the server history has it", () => {
    let s = reduce(initialState(), { type: "local.user", bot: "kami", id: "local-1", text: "ping", now: T0 });
    s = reduce(s, {
      type: "chat.opened",
      bot: "kami",
      res: opened({ messages: [{ id: "srv-1", role: "user", text: "ping", ts: T0 / 1000 + 1 }] }),
      now: T0 + 2000,
    });
    expect(s.chats.kami.messages.map((m) => m.id)).toEqual(["srv-1"]);
  });

  it("running chat starts a turn; idle chat closes a stale one", () => {
    let s = reduce(initialState(), { type: "chat.opened", bot: "kami", res: opened({ running: true }), now: T0 });
    expect(s.chats.kami.turn).not.toBeNull();
    s = reduce(s, { type: "chat.opened", bot: "kami", res: opened({ running: false }), now: T0 + 1000 });
    expect(s.chats.kami.turn).toBeNull();
    expect(s.chats.kami.lastTurn).not.toBeNull();
  });

  it("a chat.open reply older than a live turn changes nothing about it (runs.spec flake: the reply ended a turn that started after it was asked)", () => {
    const ev = (e: Record<string, unknown>, now: number) => ({ type: "event" as const, ev: { bot: "kami", ...e } as never, now });
    // asked at T0; the turn starts at T0+50 and its step comes in; the reply (running:false, read at T0) lands at T0+300
    let s = reduce(initialState(), ev({ event: "turn.start" }, T0 + 50));
    s = reduce(s, ev({ event: "tool.start", tool_id: "d1", name: "delegate_task", detail: "x" }, T0 + 60));
    s = reduce(s, { type: "chat.opened", bot: "kami", res: opened({ running: false }), now: T0 + 300, since: T0 });
    expect(s.chats.kami.turn?.steps.map((x) => x.endedAt)).toEqual([undefined]);
    // and a reply that said running about a turn that ended after the ask does not start a ghost turn
    s = reduce(s, ev({ event: "turn.end", outcome: "done" }, T0 + 400));
    s = reduce(s, { type: "chat.opened", bot: "kami", res: opened({ running: true }), now: T0 + 500, since: T0 + 350 });
    expect(s.chats.kami.turn).toBeNull();
  });
});

// ---- store (reducer + a fake bridge) ----------------------------------------------------------

function fakeBridge() {
  let anyH: ((ev: BridgeEvent) => void) | null = null;
  let statusH: ((s: BridgeStatus) => void) | null = null;
  const calls: { op: string; params: Record<string, unknown> }[] = [];
  let history = [{ id: "h1", role: "user" as const, text: "hi", ts: T0 / 1000 - 10 }];
  const offline = new Set<string>();
  // bots.list status per bot (default online); the real bridge reads "offline" for any profile not yet attached
  const listed = new Map<string, string>();
  let running = false;
  const bridge: BridgeLike = {
    connect: async () => {
      statusH?.("open");
    },
    onAny: (h) => ((anyH = h), () => {}),
    onStatus: (h) => ((statusH = h), () => {}),
    request: (async (op: string, params: Record<string, unknown>) => {
      calls.push({ op, params });
      switch (op) {
        case "hello":
          return { bridge: "mock", version: "0.1.0", hermes: { home: "/h" } };
        case "bots.list":
          return {
            bots: ["kami", "friren"].map((name) => ({
              name, display_name: name, is_default: false, model: "m", provider: "p", description: "", status: listed.get(name) ?? "online", running: false,
            })),
          };
        case "chat.open":
          if (offline.has(String(params.bot))) throw { code: "bot_offline", message: "gateway could not start" };
          return { session_id: `s-${params.bot}`, messages: history, running, model: "Opus 5.5", provider: "claude-proxy", reasoning: "high" };
        case "elsewhere.list":
          return { sessions: [away("e1", T0 / 1000 - 5)] };
        case "routines.list":
          return { routines: [] };
        case "models.options":
          return { providers: [], current: { model: "Opus 5.5", provider: "claude-proxy", reasoning: "high" }, reasoning_levels: ["low"] };
        case "chat.send":
          return { input_id: "i1" };
        case "skills.list":
          if (params.bot === "friren") throw { code: "unknown_op", message: "no such op: skills.list" };
          return { skills: [{ name: "plan", description: "Plan it" }, { name: "review", description: "" }] };
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
    setHistory: (h: typeof history) => (history = h),
    setOffline: (bot: string) => offline.add(bot),
    setListedStatus: (bot: string, status: string) => listed.set(bot, status),
    setRunning: (r: boolean) => (running = r),
  };
}

describe("store", () => {
  it("init loads bots, lists one (the first, no default here), selects it and loads only its chat", async () => {
    const f = fakeBridge();
    const store = createStore(f.bridge, { now: () => T0 });
    await store.actions.init();
    const s = store.getState();
    expect(s.bots.map((b) => b.name)).toEqual(["kami", "friren"]);
    expect(s.ui.roster).toEqual(["kami"]);
    expect(s.selectedBot).toBe("kami");
    expect(s.chats.kami.loaded).toBe(true);
    // a profile outside the list is not opened as a chat (that would make its Bot Chat); it is only asked for the
    // prompts its existing Bot Chat holds
    expect(s.chats.friren).toBeUndefined();
    const opens = f.calls.filter((c) => c.op === "chat.open");
    expect(opens.filter((c) => c.params.existing_only !== true).map((c) => c.params.bot)).toEqual(["kami"]);
    expect(opens.filter((c) => c.params.existing_only === true).map((c) => c.params.bot)).toEqual(["friren"]);
    expect(s.elsewhere.kami).toHaveLength(1);
    expect(s.models.kami.current.model).toBe("Opus 5.5");
  });

  it("a bot outside the list that bots.list reads offline (not attached yet) is still asked for its waiting prompts", async () => {
    const f = fakeBridge();
    f.setListedStatus("friren", "offline");
    const store = createStore(f.bridge, { now: () => T0 });
    await store.actions.init();
    expect(store.getState().ui.roster).toEqual(["kami"]);
    const peeks = f.calls.filter((c) => c.op === "chat.open" && c.params.existing_only === true).map((c) => c.params.bot);
    expect(peeks).toEqual(["friren"]);
    expect(store.getState().chats.friren).toBeUndefined();
  });

  it("roster: the bot saved for resume starts alone; list, open, remove; the last one stays", async () => {
    const f = fakeBridge();
    const resume = { v: 1 as const, at: T0, bot: "friren", view: "chat" as const, session: null, panelOpen: false, panelTab: "details" as const, runsFull: false, runId: null, drafts: {}, sessions: [] };
    const store = createStore(f.bridge, { now: () => T0, resume: () => resume, hiddenBots: () => [] });
    await store.actions.init();
    expect(store.getState().ui.roster).toEqual(["friren"]);
    expect(store.getState().selectedBot).toBe("friren");
    // the last listed bot cannot be removed
    store.actions.listBot("friren", false);
    expect(store.getState().ui.roster).toEqual(["friren"]);
    // opening a bot outside the list (Needs you, an @mention) brings it in
    await store.actions.selectBot("kami");
    expect(store.getState().ui.roster).toEqual(["friren", "kami"]);
    // removing the open bot opens the first one left; its pin goes with it
    store.actions.pinBot("kami", true);
    store.actions.listBot("kami", false);
    const s = store.getState();
    expect(s.ui.roster).toEqual(["friren"]);
    expect(s.ui.pinned).toEqual([]);
    expect(s.selectedBot).toBe("friren");
  });

  it("roster: bots hidden before the roster never enter it", async () => {
    const f = fakeBridge();
    const store = createStore(f.bridge, { now: () => T0, hiddenBots: () => ["kami"] });
    await store.actions.init();
    expect(store.getState().ui.roster).toEqual(["friren"]);
    expect(store.getState().selectedBot).toBe("friren");
  });

  it("send adds the user row and calls chat.send with bot + text only", async () => {
    const f = fakeBridge();
    const store = createStore(f.bridge, { now: () => T0 });
    await store.actions.init();
    await store.actions.send("  hello  ");
    const send = f.calls.find((c) => c.op === "chat.send")!;
    expect(send.params).toEqual({ bot: "kami", text: "hello" });
    expect(store.getState().chats.kami.messages.at(-1)).toMatchObject({ role: "user", text: "hello" });
  });

  it("send hoists skill tokens to the front on the wire; the row keeps the typed text, also after a re-read", async () => {
    const f = fakeBridge();
    const store = createStore(f.bridge, { now: () => T0 });
    await store.actions.init();
    await store.actions.send("before the list $plan"); // names not read yet: sent as typed
    expect(await store.actions.skills("kami")).toHaveLength(2);
    await store.actions.skills("kami");
    expect(f.calls.filter((c) => c.op === "skills.list")).toHaveLength(1); // read once per bot
    await store.actions.send(" fix $review this $plan now ");
    const sends = f.calls.filter((c) => c.op === "chat.send").map((c) => c.params.text);
    expect(sends).toEqual(["before the list $plan", "/review /plan fix this now"]);
    const row = () => store.getState().chats.kami.items.filter((i) => i.kind === "user").at(-1)!;
    expect(row()).toMatchObject({ text: "fix $review this $plan now", sent: "/review /plan fix this now", skills: ["review", "plan"] });

    f.setHistory([{ id: "h9", role: "user", text: "/review /plan fix this now", ts: T0 / 1000 }]);
    f.status("closed");
    f.status("open");
    await new Promise((r) => setTimeout(r, 0));
    const users = store.getState().chats.kami.items.filter((i) => i.kind === "user");
    expect(users.filter((i) => "sent" in i && i.sent === "/review /plan fix this now")).toHaveLength(1);
    expect(users.find((i) => i.id === "h9")).toMatchObject({ text: "fix $review this $plan now", skills: ["review", "plan"] });

    // /name anywhere, ./name and Hermes' own commands go out byte for byte, with no pill
    for (const t of ["say ./plan out loud", "fix /plan now", "/plan fix it", "/new"]) {
      await store.actions.send(t);
      expect(row()).not.toHaveProperty("skills");
    }
    expect(f.calls.filter((c) => c.op === "chat.send").map((c) => c.params.text).slice(-4)).toEqual(["say ./plan out loud", "fix /plan now", "/plan fix it", "/new"]);

    // a bridge without the op: an empty list, no error, asked again next time
    expect(await store.actions.skills("friren")).toEqual([]);
    expect(store.getState().lastError).toBeNull();
    await store.actions.skills("friren");
    expect(f.calls.filter((c) => c.op === "skills.list" && c.params.bot === "friren")).toHaveLength(2);
  });

  it("sendWithFiles attaches each file in order, then sends once; a failed attach sends nothing", async () => {
    const f = fakeBridge();
    const store = createStore(f.bridge, { now: () => T0 });
    await store.actions.init();
    const file = (name: string, attach: "image" | "pdf" | "file", read = async () => "QUJD") =>
      ({ name, size: 3, kind: "file" as const, url: null, attach, read });
    await store.actions.sendWithFiles(" look ", [file("a.png", "image"), file("r.pdf", "pdf")]);
    const ops = f.calls.map((c) => c.op).filter((o) => o === "chat.attach" || o === "chat.send");
    expect(ops).toEqual(["chat.attach", "chat.attach", "chat.send"]);
    expect(f.calls.filter((c) => c.op === "chat.attach").map((c) => c.params)).toEqual([
      { bot: "kami", kind: "image", name: "a.png", data_base64: "QUJD" },
      { bot: "kami", kind: "pdf", name: "r.pdf", data_base64: "QUJD" },
    ]);
    const row = store.getState().chats.kami.items.at(-1)!;
    expect(row).toMatchObject({ kind: "user", text: "look", files: [{ name: "a.png" }, { name: "r.pdf" }] });

    const before = f.calls.length;
    const bad = file("b.png", "image", async () => {
      throw new Error("unreadable");
    });
    await expect(store.actions.sendWithFiles("x", [file("ok.png", "image"), bad])).rejects.toThrow("Couldn't attach b.png");
    expect(f.calls.slice(before).map((c) => c.op)).toEqual(["chat.attach"]); // no chat.send
    expect(store.getState().chats.kami.items.at(-1)).toBe(row); // no new bubble
  });

  it("reconnect keeps state and re-reads the chat without duplicating it", async () => {
    const f = fakeBridge();
    const store = createStore(f.bridge, { now: () => T0 });
    await store.actions.init();
    f.emit({ event: "message", bot: "kami", id: "m-1", text: "answer" });
    await store.actions.selectBot("friren");
    f.emit({ event: "message", bot: "kami", id: "m-2", text: "while away" });
    expect(store.getState().unread.kami).toBe(1);

    f.status("closed");
    expect(store.getState().conn).toBe("closed");
    expect(store.getState().chats.kami.messages.map((m) => m.id)).toEqual(["h1", "m-1", "m-2"]); // kept while down

    f.setHistory([
      { id: "h1", role: "user", text: "hi", ts: T0 / 1000 - 10 },
      { id: "m-1", role: "assistant" as never, text: "answer", ts: T0 / 1000 },
    ]);
    f.status("open");
    await new Promise((r) => setTimeout(r, 0));
    const s = store.getState();
    expect(s.conn).toBe("open");
    expect(s.selectedBot).toBe("friren");
    expect(s.unread.kami).toBe(1);
    expect(s.chats.kami.messages.map((m) => m.id)).toEqual(["h1", "m-1", "m-2"]);
    expect(s.chats.kami.messages.filter((m) => m.id === "m-1")).toHaveLength(1);
  });

  it("approval response calls the bridge and resolves the card", async () => {
    const f = fakeBridge();
    const store = createStore(f.bridge, { now: () => T0 });
    await store.actions.init();
    f.emit({ event: "approval.request", bot: "kami", request_id: "ap1", title: "t", command: "c", choices: ["once", "deny"] });
    await store.actions.respondApproval("ap1", "deny");
    expect(f.calls.find((c) => c.op === "approval.respond")!.params).toEqual({ bot: "kami", request_id: "ap1", choice: "deny" });
    expect(store.getState().chats.kami.items.find((i) => i.kind === "approval")).toMatchObject({ resolved: "deny" });
  });

  it("losing the bridge mid-turn ends the turn as interrupted, not done after reconnect", async () => {
    const f = fakeBridge();
    const store = createStore(f.bridge, { now: () => T0 });
    await store.actions.init();
    f.emit({ event: "turn.start", bot: "kami" });
    f.emit({ event: "tool.start", bot: "kami", tool_id: "t1", name: "terminal", detail: "sleep 30" });
    expect(store.getState().chats.kami.turn).not.toBeNull();
    f.status("closed");
    let s = store.getState();
    expect(s.chats.kami.turn).toBeNull(); // no live activity line / Stop during the outage
    expect(s.chats.kami.lastTurn?.outcome).toBe("interrupted");
    f.setRunning(false);
    f.status("open");
    await new Promise((r) => setTimeout(r, 0));
    s = store.getState();
    expect(s.chats.kami.lastTurn?.outcome).toBe("interrupted"); // reconnect does not rewrite it to "done"
    expect(f.calls.filter((c) => c.op === "chat.send")).toHaveLength(0); // nothing resent
  });

  it("an offline bot's chat stops loading and carries the error", async () => {
    const f = fakeBridge();
    f.setOffline("friren");
    const store = createStore(f.bridge, { now: () => T0 });
    await store.actions.init();
    await store.actions.selectBot("friren");
    const c = store.getState().chats.friren;
    expect(c.loaded).toBe(true);
    expect(c.openError).toMatch(/gateway could not start/);
  });

  it("ui actions", async () => {
    const f = fakeBridge();
    const store = createStore(f.bridge);
    store.actions.togglePanel();
    expect(store.getState().ui.panelOpen).toBe(true);
    store.actions.setTheme("light");
    expect(store.getState().ui.theme).toBe("light");
    store.actions.openSettings("providers");
    expect(store.getState().ui).toMatchObject({ view: "settings", settingsPage: "providers" });
    store.actions.closeSettings();
    expect(store.getState().ui.view).toBe("chat");
    store.actions.openSession("s1");
    expect(store.getState().ui).toMatchObject({ view: "session", session: "s1" });
    await store.actions.selectBot("kami");
    expect(store.getState().ui.view).toBe("chat");
    store.actions.openSession("s1");
    store.actions.openSession(null);
    expect(store.getState().ui).toMatchObject({ view: "chat", session: null });
  });

  it("Reply there: the chip goes along as reply_to once, then clears; a turn end re-reads the places", async () => {
    const f = fakeBridge();
    const store = createStore(f.bridge, { now: () => T0 });
    await store.actions.init();
    const a = away("e1", T0 / 1000 - 5, { place: "#og-dev", reply_target: "slack:C1:1794.5" });
    const chip = replyChipFor(a)!;
    expect(chip).toEqual({ session_id: "e1", source: "slack", place: "#og-dev", kind: "thread" });
    expect(replyChipFor(away("c1", 1, { source: "cron" }))).toBeNull();
    expect(replyChipFor(away("d1", 1, { source: "discord", reply_target: "discord:42" }))!.kind).toBe("channel");

    store.actions.setReplyTo(chip);
    expect(f.calls.filter((c) => c.op === "chat.send")).toHaveLength(0); // the chip alone sends nothing
    await store.actions.send("결과 요약해서 남겨줘");
    const sends = f.calls.filter((c) => c.op === "chat.send");
    expect(sends.map((c) => c.params)).toEqual([{ bot: "kami", text: "결과 요약해서 남겨줘", reply_to: "e1" }]);
    expect(store.getState().replyTo.kami).toBeNull();
    expect(store.getState().chats.kami.items.at(-1)).toMatchObject({ kind: "user", reply: { source: "slack", label: "#og-dev" } });

    const lists = () => f.calls.filter((c) => c.op === "elsewhere.list").length;
    const before = lists();
    f.emit({ event: "turn.end", bot: "kami", outcome: "done" });
    expect(lists()).toBe(before + 1);

    // the next message, without a chip, is plain
    await store.actions.send("there");
    expect(f.calls.filter((c) => c.op === "chat.send").at(-1)!.params).toEqual({ bot: "kami", text: "there" });
    f.emit({ event: "turn.end", bot: "kami", outcome: "done" });
    expect(lists()).toBe(before + 1);
  });
});

describe("SESSIONS chats in the same reducer", () => {
  it("a folder chat's events (tagged session) land under their own key and never move the bot's chat", () => {
    let s = reduce(initialState(), { type: "chat.opened", bot: "kami", res: opened(), now: T0 });
    const key = folderKey("kami", "f1");
    s = run(s, realTurn("kami").map((e) => ({ ...e, session: "f1" }) as BridgeEvent));
    s = reduce(s, { type: "event", ev: { event: "bot.status", bot: "kami", session: "f1", status: "online", running: true }, now: T0 });
    expect(s.chats[key].messages.map((m) => m.text)).toEqual(["`echo omher-probe` 결과 `omher-probe`가 출력됐고 exit code는 0입니다."]);
    expect(s.chats[key].lastTurn?.steps.map((x) => x.detail)).toEqual(["echo omher-probe"]);
    expect(s.chats.kami.items.filter((i) => i.kind !== "user")).toEqual([]); // the bot's own chat is untouched
    expect(s.chats.kami.turn).toBeNull();
  });

  it("answers on a session chat go to its route, not to the bridge's main chat", async () => {
    const f = fakeBridge();
    const store = createStore(f.bridge, { now: () => T0 });
    await store.actions.init();
    const got: string[] = [];
    setChatRoute("agent:s9", {
      label: "Claude Code · app",
      open: () => undefined,
      send: async () => undefined,
      interrupt: async () => undefined,
      approve: async (id, choice) => void got.push(`${id}:${choice}`),
      clarify: async (id, a) => void got.push(`${id}=${a}`),
    });
    store.dispatch({ type: "event", ev: { event: "approval.request", bot: "agent:s9", request_id: "r1", title: "Run this command?", command: "rm -rf build", choices: ["deny", "once", "session"] }, now: T0 });
    await store.actions.respondApproval("r1", "session", "agent:s9");
    expect(got).toEqual(["r1:session"]);
    expect(f.calls.some((c) => c.op === "approval.respond")).toBe(false);
    expect(store.getState().chats["agent:s9"].items.find((i) => i.kind === "approval")).toMatchObject({ resolved: "session" });
    // a closed session refuses instead of answering the bot's main chat
    setChatRoute("agent:s9", null);
    expect(chatRoute("agent:s9")).toBeUndefined();
    store.dispatch({ type: "event", ev: { event: "approval.request", bot: "agent:s9", request_id: "r2", title: "t", command: "c", choices: ["once"] }, now: T0 });
    await store.actions.respondApproval("r2", "once", "agent:s9");
    expect(f.calls.some((c) => c.op === "approval.respond")).toBe(false);
    expect(store.getState().lastError).toMatch(/ended/);
  });

  it("losing the bridge ends Hermes chats' turns but not a shell agent chat's", async () => {
    const f = fakeBridge();
    const store = createStore(f.bridge, { now: () => T0 });
    await store.actions.init();
    store.dispatch({ type: "event", ev: { event: "turn.start", bot: "agent:s1" }, now: T0 });
    f.emit({ event: "turn.start", bot: "kami", session: "f1" });
    f.status("closed");
    const s = store.getState();
    expect(s.chats["agent:s1"].turn).not.toBeNull();
    expect(s.chats[folderKey("kami", "f1")].turn).toBeNull();
  });
});

// The real fan-out turn on kami (bridge/tests/fixtures/real-subagent-turn.json), as the bridge's subagent events:
// the parent's turn ends before the two children report back.
describe("subagent events: one fan-out per delegate_task, one row per subagent", () => {
  const bot = "kami";
  const g0 = "Run the shell command `date +%F` in the terminal exactly once and return its exact stdout";
  const g1 = "Run the shell command `uname -s` in the terminal exactly once and return its exact stdout";
  const sub = (id: string, index: number, goal: string, state: string, extra: Record<string, unknown> = {}) =>
    ({ event: "subagent", bot, id, index, count: 2, goal, model: "claude-fable-5-2", state, ...extra }) as BridgeEvent;
  const d = { delegation: "deleg_40dc82e8" };
  const turn: BridgeEvent[] = [
    { event: "turn.start", bot },
    { event: "tool.start", bot, tool_id: "t1", name: "delegate_task", detail: "2 tasks" },
    sub("sa-0", 0, g0, "queued"),
    sub("sa-1", 1, g1, "queued"),
    sub("sa-0", 0, g0, "running", d),
    sub("sa-1", 1, g1, "running", d),
    { event: "tool.end", bot, tool_id: "t1", name: "delegate_task", ok: true, ms: 98 },
    sub("sa-1", 1, g1, "thinking", d),
    sub("sa-1", 1, g1, "running", { ...d, tool: "terminal", step: "uname -s" }),
    { event: "message", bot, id: "m1", text: "Both are on it." },
    { event: "turn.end", bot, outcome: "done" },
    sub("sa-1", 1, g1, "done", { ...d, summary: "Darwin", seconds: 6.1 }),
    sub("sa-0", 0, g0, "done", { ...d, summary: "2026-11-11", seconds: 8.8 }),
  ];
  const fanouts = (s: AppState) => s.chats[bot].items.flatMap((i) => (i.kind === "activity" ? i.turn.fanouts ?? [] : []));

  it("groups the children into one fan-out of the turn that started them, also after that turn ended", () => {
    const s = run(initialState(), turn);
    const f = fanouts(s);
    expect(f).toHaveLength(1);
    expect(f[0].delegation).toBe("deleg_40dc82e8");
    expect(f[0].subs.map((x) => [x.id, x.state, x.summary, x.seconds])).toEqual([
      ["sa-0", "done", "2026-11-11", 8.8],
      ["sa-1", "done", "Darwin", 6.1],
    ]);
    // the late events open no second turn and touch no new activity row
    expect(s.chats[bot].items.filter((i) => i.kind === "activity")).toHaveLength(1);
    expect(s.chats[bot].turn).toBeNull();
  });

  it("keeps the current step while running and drops it for the result line when done", () => {
    const mid = run(initialState(), turn.slice(0, 9));
    const row = fanouts(mid)[0].subs[1];
    expect([row.state, row.tool, row.step]).toEqual(["running", "terminal", "uname -s"]);
    const end = fanouts(run(initialState(), turn))[0].subs[1];
    expect([end.step, end.tool, end.summary]).toEqual([undefined, undefined, "Darwin"]);
  });

  it("two delegate_task calls in one turn are two fan-outs; a late running event never revives a finished child", () => {
    const second = [
      sub("sb-0", 0, "Second wave A", "queued"),
      sub("sb-1", 1, "Second wave B", "queued"),
      sub("sb-0", 0, "Second wave A", "running", { delegation: "deleg_2" }),
    ];
    const s = run(initialState(), [...turn.slice(0, 9), ...second, sub("sa-1", 1, g1, "done", d), sub("sa-1", 1, g1, "running", d)]);
    const f = fanouts(s);
    expect(f.map((x) => x.subs.map((r) => r.id))).toEqual([["sa-0", "sa-1"], ["sb-0", "sb-1"]]);
    expect(f[0].subs[1].state).toBe("done");
  });

  it("a second turn's fan-out with the same subagent ids lands in that turn, by its delegation id", () => {
    const again: BridgeEvent[] = [
      { event: "turn.start", bot },
      { event: "tool.start", bot, tool_id: "t2", name: "delegate_task", detail: "2 tasks" },
      sub("sa-0", 0, g0, "queued"),
      sub("sa-1", 1, g1, "queued"),
      sub("sa-0", 0, g0, "running", { delegation: "deleg_second" }),
      sub("sa-1", 1, g1, "running", { delegation: "deleg_second" }),
      { event: "turn.end", bot, outcome: "done" },
      sub("sa-0", 0, g0, "done", { delegation: "deleg_second", summary: "again", seconds: 1 }),
    ];
    const s = run(initialState(), [...turn, ...again]);
    const turns = s.chats[bot].items.flatMap((i) => (i.kind === "activity" ? [i.turn] : []));
    expect(turns.map((t) => t.fanouts?.map((f) => [f.delegation, f.subs.map((r) => r.state).join(",")]))).toEqual([
      [["deleg_40dc82e8", "done,done"]],
      [["deleg_second", "done,running"]],
    ]);
  });

  it("a subagent event with no turn to take it (chat opened afterwards) changes nothing", () => {
    const s0 = run(initialState(), [{ event: "message", bot, id: "m0", text: "hi" }]);
    expect(run(s0, [sub("sa-9", 0, "x", "running", d)])).toBe(s0);
  });

  it("a subagent's file edit keeps its change per file; said again when it ran, it takes the final change", () => {
    const file = (lines: string[]) => ({ path: "calc.py", kind: "update" as const, lines, added: lines.filter((l) => l[0] === "+").length, removed: 0 });
    const asked = file(["@@ -6 +6,3 @@", "     return a - b", "+def mul(a, b):"]);
    const ran = file(["@@ -6 +6,5 @@", "     return a - b", "+", "+", "+def mul(a, b):", "+    return a * b"]);
    const s = run(initialState(), [
      ...turn.slice(0, 9),
      sub("sa-1", 1, g1, "running", { ...d, tool: "patch", step: "calc.py +4", diff: [asked] }),
      sub("sa-1", 1, g1, "running", { ...d, tool: "patch", step: "calc.py +4", diff: [ran] }),
    ]);
    const steps = fanouts(s)[0].subs[1].steps ?? [];
    expect(steps.map((x) => [x.text, x.diff?.[0]?.lines.length])).toEqual([
      ["uname -s", undefined],
      ["calc.py +4", 6],
    ]);
  });
});
