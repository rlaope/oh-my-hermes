// What a SESSIONS chat keeps of the agent's work: a step's diff, one todo list that changes in place, the thinking
// text (capped), and the agent's own rewind taking the last message back. Pure reducer checks.
import { describe, expect, it } from "vitest";
import { initialState, parsePlan, reduce, turnHasActivity, THINKING_MAX, type Action, type AppState } from "./store";
import type { BridgeEvent } from "../lib/protocol";

const T0 = 1_800_000_000_000;
const key = "agent:s1";

function at(evs: Record<string, unknown>[], s0?: AppState): AppState {
  let s =
    s0 ??
    reduce(initialState(), {
      type: "chat.opened",
      bot: key,
      res: { session_id: key, messages: [], running: false, model: "", provider: "", reasoning: "" },
      now: T0,
    });
  evs.forEach((ev, i) => {
    s = reduce(s, { type: "event", ev: { ...ev, bot: key } as unknown as BridgeEvent, now: T0 + (i + 1) * 100 } as Action);
  });
  return s;
}
const turnOf = (s: AppState) => {
  const c = s.chats[key];
  const items = c.items.filter((i) => i.kind === "activity");
  return items[items.length - 1].kind === "activity" ? items[items.length - 1].turn : null;
};

const file = { path: "calc.py", kind: "update", lines: ["@@ -5,3 +5,7 @@", " def sub(a, b):", "+def mul(a, b):"], added: 1, removed: 0 };

describe("a session turn's work", () => {
  it("puts a file edit's change on its step, the later one replacing the earlier", () => {
    const s = at([
      { event: "turn.start" },
      { event: "tool.start", tool_id: "e1", name: "patch", detail: "calc.py +1" },
      { event: "tool.diff", tool_id: "e1", files: [{ ...file, lines: ["-a", "+b"] }] },
      { event: "tool.diff", tool_id: "e1", files: [file] },
      { event: "tool.end", tool_id: "e1", name: "", ok: true, ms: 0 },
      { event: "tool.diff", tool_id: "nope", files: [file] },
      { event: "tool.diff", tool_id: "e1", files: [{ bad: 1 }] },
      { event: "turn.end", outcome: "done" },
    ]);
    const t = turnOf(s)!;
    expect(t.steps).toHaveLength(1);
    expect(t.steps[0].diff).toEqual([file]);
  });

  it("keeps one todo list per turn that each plan event replaces", () => {
    const s = at([
      { event: "turn.start" },
      { event: "plan", items: [{ text: "a", status: "pending" }, { text: "b", status: "pending" }] },
      { event: "plan", items: [{ text: "a", status: "completed" }, { text: "b", status: "in_progress" }] },
      { event: "turn.end", outcome: "done" },
    ]);
    const t = turnOf(s)!;
    expect(t.plan).toEqual([
      { text: "a", status: "completed" },
      { text: "b", status: "in_progress" },
    ]);
    // no step per update, and the list stays after the turn ended
    expect(t.steps).toHaveLength(0);
    expect(s.chats[key].items.filter((i) => i.kind === "activity")).toHaveLength(1);
    expect(t.endedAt).toBeDefined();
  });

  it("reads an odd plan safely", () => {
    expect(parsePlan([{ text: "x", status: "weird" }, { text: " " }, null, 3, { status: "completed" }])).toEqual([{ text: "x", status: "pending" }]);
    expect(parsePlan("nope")).toEqual([]);
  });

  it("keeps thinking text, up to its cap, and shows the line once there is some", () => {
    let s = at([{ event: "turn.start" }, { event: "thinking" }]);
    expect(turnOf(s)!.thinking).toBeUndefined();
    expect(turnHasActivity(turnOf(s)!)).toBe(false);
    s = at([{ event: "thinking", text: "Two files. " }, { event: "thinking", text: "Start with calc.py." }], s);
    expect(turnOf(s)!.thinking).toBe("Two files. Start with calc.py.");
    expect(turnHasActivity(turnOf(s)!)).toBe(true);
    s = at([{ event: "thinking", text: "x".repeat(THINKING_MAX) }, { event: "thinking", text: "more" }], s);
    expect(turnOf(s)!.thinking!.length).toBe(THINKING_MAX);
    // none outside a turn
    s = at([{ event: "turn.end", outcome: "done" }, { event: "thinking", text: "late" }], s);
    expect(turnOf(s)!.thinking!.endsWith("late")).toBe(false);
  });

  it("takes the last message and what followed it out when the agent rewound", () => {
    let s = at([]);
    s = reduce(s, { type: "local.user", bot: key, id: "u1", text: "first", now: T0 + 10 });
    s = at([{ event: "turn.start" }, { event: "message", id: "m1", text: "one" }, { event: "turn.end", outcome: "done" }], s);
    s = reduce(s, { type: "local.user", bot: key, id: "u2", text: "second", now: T0 + 5000 });
    s = at([{ event: "turn.start" }, { event: "message", id: "m2", text: "two" }, { event: "turn.end", outcome: "done" }], s);
    s = at([{ event: "rewound" }], s);
    const ids = s.chats[key].items.map((i) => i.id);
    expect(ids).toContain("u1");
    expect(ids).toContain("m1");
    expect(ids).not.toContain("u2");
    expect(ids).not.toContain("m2");
    expect(s.chats[key].messages.map((m) => m.text)).toEqual(["first", "one"]);
  });
});
