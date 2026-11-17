import { describe, expect, it } from "vitest";
import { ageOf } from "./SessionsSection";
import { BUSY_MS } from "./agents";
import { ageBucket, ageChangeAt, createTermActivity, faceKey, flowing, nextFaceAt } from "./termActivity";

describe("termActivity store", () => {
  it("notifies only the session that changed", () => {
    const s = createTermActivity();
    const heard: string[] = [];
    const offA = s.subscribe("a", () => heard.push("a"));
    s.subscribe("b", () => heard.push("b"));
    s.patch("a", { lastOut: 1 });
    expect(heard).toEqual(["a"]);
    expect(s.get("a")).toEqual({ lastOut: 1 });
    expect(s.get("b")).toEqual({});
    offA();
    s.patch("a", { lastOut: 2 });
    expect(heard).toEqual(["a"]);
    expect(s.get("a").lastOut).toBe(2);
  });

  it("an unchanged value notifies no one and keeps the same object", () => {
    const s = createTermActivity();
    let n = 0;
    s.subscribe("a", () => n++);
    s.patch("a", { lastLine: "Reading src/app.ts", oscTitle: "claude" });
    const before = s.get("a");
    s.patch("a", { lastLine: "Reading src/app.ts" });
    s.patch("a", { oscTitle: "claude", lastLine: "Reading src/app.ts" });
    expect(n).toBe(1);
    expect(s.get("a")).toBe(before);
    // clearing a field is a change
    s.patch("a", { lastLine: undefined });
    expect(n).toBe(2);
    expect(s.get("a")).toEqual({ lastLine: undefined, oscTitle: "claude" });
  });

  it("an unknown session reads as nothing, the same object every time", () => {
    const s = createTermActivity();
    expect(s.get("x")).toBe(s.get("y"));
  });
});

describe("row face timing", () => {
  const at = Date.UTC(2026, 10, 17, 9, 0, 0);
  it("the age bucket changes exactly when ageOf's label does", () => {
    for (const d of [0, 59_999, 60_000, 119_999, 3_599_999, 3_600_000, 86_399_999, 86_400_000, 200_000_000]) {
      const now = at + d;
      const next = ageChangeAt(at, now);
      expect(next).toBeGreaterThan(now);
      // the label is the same until `next` and different at it
      expect(ageOf(at / 1000, next - 1)).toBe(ageOf(at / 1000, now));
      expect(ageOf(at / 1000, next)).not.toBe(ageOf(at / 1000, now));
      expect(ageBucket(at, next - 1)).toBe(ageBucket(at, now));
      expect(ageBucket(at, next)).not.toBe(ageBucket(at, now));
    }
  });

  it("the spinner runs BUSY_MS after the last output; the face changes when it stops", () => {
    const a = { lastOut: at };
    expect(flowing(a, at + BUSY_MS - 1)).toBe(true);
    expect(flowing(a, at + BUSY_MS)).toBe(false);
    expect(nextFaceAt(a, at - 10_000, at + 100)).toBe(at + BUSY_MS);
    expect(faceKey(a, 0, at + BUSY_MS - 1)).not.toBe(faceKey(a, 0, at + BUSY_MS));
    // a new mark within the same age label and line, spinner on both: the same face (no re-render)
    expect(faceKey({ lastOut: at + 500 }, 0, at + 600)).toBe(faceKey({ lastOut: at }, 0, at + 100));
    // the second line is part of the face
    expect(faceKey({ lastOut: at, lastLine: "x" }, 0, at)).not.toBe(faceKey({ lastOut: at, lastLine: "y" }, 0, at));
  });
});
