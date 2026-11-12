import { describe, expect, it } from "vitest";
import { initialState, reduce, selectTimeline, type Action, type AppState } from "../../state/store";
import type { BridgeEvent } from "../../lib/protocol";
import { awaitingFirstToken } from "./Typing";
import { liveFaceRow } from "./liveFace";
import { ringDelay } from "../../ui/Live";

const T0 = 1_800_000_000_000;
const at = (s: AppState, ev: BridgeEvent, i: number) => reduce(s, { type: "event", ev, now: T0 + i * 100 } as Action);
const row = (s: AppState) => {
  const chat = s.chats.kami;
  return liveFaceRow(selectTimeline(s, "kami"), chat?.turn, awaitingFirstToken(chat));
};

describe("liveFaceRow: one row of the live run holds the face", () => {
  it("moves typing -> status line -> streaming answer, and is gone once the turn ends", () => {
    let s = reduce(initialState(), { type: "local.user", bot: "kami", id: "l1", text: "why?", now: T0 - 10 });
    const seen: (string | null)[] = [];
    const evs: BridgeEvent[] = [
      { event: "turn.start", bot: "kami" },
      { event: "thinking", bot: "kami" },
      { event: "status", bot: "kami", text: "🧠 OMH — recalled 2 memories" },
      { event: "tool.start", bot: "kami", tool_id: "t1", name: "terminal", detail: "ls" },
      { event: "tool.end", bot: "kami", tool_id: "t1", name: "terminal", ok: true, ms: 40 },
      { event: "thinking", bot: "kami" },
      { event: "delta", bot: "kami", text: "It is" },
      { event: "message", bot: "kami", id: "a1", text: "It is fine." },
      { event: "turn.end", bot: "kami", outcome: "done" },
    ];
    evs.forEach((ev, i) => {
      s = at(s, ev, i);
      seen.push(row(s));
    });
    // the status line takes the face the moment it shows: never a step with none while the bot works
    expect(seen).toEqual(["typing", "typing", "activity", "activity", "activity", "activity", "streaming", null, null]);
  });

  it("leaves the face to a bot bubble that landed after the line; keeps it on the line beside an open ask", () => {
    let s = initialState();
    [
      { event: "turn.start", bot: "kami" },
      { event: "tool.start", bot: "kami", tool_id: "t1", name: "terminal", detail: "ls" },
      { event: "message", bot: "kami", id: "a1", text: "First part." },
    ].forEach((ev, i) => (s = at(s, ev as BridgeEvent, i)));
    expect(row(s)).toBeNull();
    s = initialState();
    [
      { event: "turn.start", bot: "kami" },
      { event: "approval.request", bot: "kami", request_id: "r1", title: "Run", command: "rm -rf x", choices: ["once", "deny"] },
    ].forEach((ev, i) => (s = at(s, ev as BridgeEvent, i)));
    // the line says "Waiting for approval" beside the card, with the face; once the turn is over, no live face
    expect(row(s)).toBe("activity");
    expect(row({ ...s, chats: { ...s.chats, kami: { ...s.chats.kami, turn: null } } })).toBeNull();
  });
});

describe("ringDelay: a ring that moves to another row keeps its angle", () => {
  it("is a negative delay within one 1.2s turn that follows the page clock", () => {
    for (const now of [0, 333, 1199, 50_000.5]) {
      const d = ringDelay("kami", now);
      expect(d).toBeLessThanOrEqual(0);
      expect(d).toBeGreaterThan(-1.2);
    }
    // mounted 400 ms later, its delay is 400 ms further back (mod one turn): the arc is at the same angle
    const a = ringDelay("kami", 1000);
    const b = ringDelay("kami", 1400);
    expect((((a - b) * 1000) % 1200 + 1200) % 1200).toBeCloseTo(400, 6);
    // two bots still start apart
    expect(ringDelay("kami", 0)).not.toBe(ringDelay("friren", 0));
  });
});
