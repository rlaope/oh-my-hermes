import { describe, expect, it } from "vitest";
import { THREAD_STATUSES, threadStatus, type ThreadFacts } from "./status";

const f = (p: Partial<ThreadFacts>): ThreadFacts => ({ running: false, asks: 0, lastOutcome: null, ...p });

describe("threadStatus", () => {
  // the state table: every row
  const table: [string, Partial<ThreadFacts>, string][] = [
    ["nothing ran", {}, "idle"],
    ["a turn runs", { running: true }, "running"],
    ["an ask waits while the turn runs: needs you wins", { running: true, asks: 1 }, "needs_you"],
    ["an ask waits with no turn running", { asks: 2 }, "needs_you"],
    ["an ask waits after a failed turn", { asks: 1, lastOutcome: "error" }, "needs_you"],
    ["the last turn ended well", { lastOutcome: "done" }, "done"],
    ["an agent exited cleanly mid-turn", { lastOutcome: "ended" }, "done"],
    ["the last turn ended in an error", { lastOutcome: "error" }, "failed"],
    ["the person stopped the last turn", { lastOutcome: "interrupted" }, "failed"],
    ["a new turn runs after a failed one", { running: true, lastOutcome: "error" }, "running"],
    ["a new turn runs after a done one", { running: true, lastOutcome: "done" }, "running"],
  ];
  for (const [what, facts, want] of table) {
    it(what, () => expect(threadStatus(f(facts))).toBe(want));
  }

  it("answers only the five states", () => {
    expect([...THREAD_STATUSES].sort()).toEqual(["done", "failed", "idle", "needs_you", "running"]);
    const seen = new Set(table.map(([, facts]) => threadStatus(f(facts))));
    expect([...seen].sort()).toEqual([...THREAD_STATUSES].sort());
  });
});
