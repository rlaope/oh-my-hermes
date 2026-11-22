import { describe, expect, it } from "vitest";
import { newer, older, onFirstLine, onLastLine, promptsOf, type Recall } from "./promptHistory";

describe("promptsOf", () => {
  it("keeps the person's rows only, oldest first, as typed", () => {
    const items = [
      { kind: "user", text: "fix this $plan now" },
      { kind: "assistant", text: "done" },
      { kind: "activity" },
      { kind: "user", text: "and test it" },
    ];
    expect(promptsOf(items)).toEqual(["fix this $plan now", "and test it"]);
  });

  it("collapses a prompt sent twice in a row, not one sent again later", () => {
    const items = ["a", "a", "b", "a"].map((text) => ({ kind: "user", text }));
    expect(promptsOf(items)).toEqual(["a", "b", "a"]);
  });

  it("skips rows not sent (held in omher's queue, dropped by Stop); keeps a failed send and an uncertain steer", () => {
    const items = [
      { kind: "user", text: "sent" },
      { kind: "user", text: "failed", error: "bridge offline" },
      { kind: "user", text: "dropped", wait: "dropped" },
      { kind: "user", text: "maybe steered", held: true, steerUnknown: true },
      { kind: "user", text: "queued, sent", wait: "queued" },
      { kind: "user", text: "held", held: true },
      { kind: "user", text: "steering in", held: true, autoSteer: true },
    ];
    expect(promptsOf(items)).toEqual(["sent", "failed", "maybe steered", "queued, sent", "steering in"]);
  });

  it("skips files-only sends and an absent chat", () => {
    expect(promptsOf([{ kind: "user", text: "" }, { kind: "user", text: "  " }])).toEqual([]);
    expect(promptsOf(undefined)).toEqual([]);
  });
});

describe("older / newer", () => {
  const history = ["first", "second", "third"];

  it("walks newest first, then stops at the oldest", () => {
    let r: Recall = null;
    const seen: string[] = [];
    for (;;) {
      const s = older(history, r, "my draft");
      if (!s) break;
      seen.push(s.text);
      r = s.recall;
    }
    expect(seen).toEqual(["third", "second", "first"]);
    expect(r).toEqual({ at: 0, draft: "my draft" });
  });

  it("keeps the draft typed before the first ArrowUp, not the recalled text", () => {
    const one = older(history, null, "my draft")!;
    const two = older(history, one.recall, one.text)!;
    expect(two.recall).toEqual({ at: 1, draft: "my draft" });
  });

  it("goes newer, and past the newest gives the draft back and ends the walk", () => {
    expect(newer(history, { at: 1, draft: "d" })).toEqual({ recall: { at: 2, draft: "d" }, text: "third" });
    expect(newer(history, { at: 2, draft: "d" })).toEqual({ recall: null, text: "d" });
  });

  it("does nothing outside a walk or with no history", () => {
    expect(newer(history, null)).toBeNull();
    expect(older([], null, "d")).toBeNull();
  });

  it("stays inside a history that shrank under the walk", () => {
    expect(older(["a"], { at: 4, draft: "d" }, "x")).toEqual({ recall: { at: 0, draft: "d" }, text: "a" });
  });

  it("never changes the history", () => {
    const h = Object.freeze(["a", "b"]);
    older(h, null, "x");
    newer(h, { at: 0, draft: "x" });
    expect(h).toEqual(["a", "b"]);
  });
});

describe("onFirstLine / onLastLine", () => {
  it("reads the caret's line in a multi-line box", () => {
    const t = "one\ntwo\nthree";
    expect(onFirstLine(t, 2)).toBe(true);
    expect(onFirstLine(t, 5)).toBe(false);
    expect(onLastLine(t, 5)).toBe(false);
    expect(onLastLine(t, t.length)).toBe(true);
  });

  it("a single line is both", () => {
    expect(onFirstLine("abc", 1)).toBe(true);
    expect(onLastLine("abc", 1)).toBe(true);
    expect(onFirstLine("", 0) && onLastLine("", 0)).toBe(true);
  });
});
