import { describe, expect, it } from "vitest";
import {
  activityText,
  createStore,
  initialState,
  reduce,
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

  it("closes open steps when a turn is interrupted", () => {
    const s = run(initialState(), [
      { event: "turn.start", bot: "kami" },
      { event: "tool.start", bot: "kami", tool_id: "a", name: "terminal", detail: "sleep 9" },
      { event: "turn.end", bot: "kami", outcome: "interrupted" },
    ]);
    const t = s.chats.kami.lastTurn!;
    expect(t.outcome).toBe("interrupted");
    expect(t.steps[0].endedAt).toBeDefined();
    expect(t.steps[0].ok).toBeUndefined();
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
});

// ---- store (reducer + a fake bridge) ----------------------------------------------------------

function fakeBridge() {
  let anyH: ((ev: BridgeEvent) => void) | null = null;
  let statusH: ((s: BridgeStatus) => void) | null = null;
  const calls: { op: string; params: Record<string, unknown> }[] = [];
  let history = [{ id: "h1", role: "user" as const, text: "hi", ts: T0 / 1000 - 10 }];
  const offline = new Set<string>();
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
              name, display_name: name, is_default: false, model: "m", provider: "p", description: "", status: "online", running: false,
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
    setRunning: (r: boolean) => (running = r),
  };
}

describe("store", () => {
  it("init loads bots, selects the first, and loads its chat", async () => {
    const f = fakeBridge();
    const store = createStore(f.bridge, { now: () => T0 });
    await store.actions.init();
    const s = store.getState();
    expect(s.bots.map((b) => b.name)).toEqual(["kami", "friren"]);
    expect(s.selectedBot).toBe("kami");
    expect(s.chats.kami.loaded).toBe(true);
    expect(s.chats.friren.loaded).toBe(true);
    expect(s.elsewhere.kami).toHaveLength(1);
    expect(s.models.kami.current.model).toBe("Opus 5.5");
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
  });
});
