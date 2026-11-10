import { describe, expect, it } from "vitest";
import { percent, shortError } from "./updater";

describe("updater helpers", () => {
  it("rounds progress down and caps it at 100", () => {
    expect(percent({ done: 0, total: 1000 })).toBe(0);
    expect(percent({ done: 999, total: 1000 })).toBe(99);
    expect(percent({ done: 2000, total: 1000 })).toBe(100);
    expect(percent({ done: 10, total: null })).toBeNull();
    expect(percent({ done: 10, total: 0 })).toBeNull();
  });

  it("keeps an error to its first line", () => {
    expect(shortError(new Error("signature mismatch\nat x"))).toBe("signature mismatch");
    expect(shortError("offline")).toBe("offline");
    expect(shortError({})).toBe("Update failed");
    expect(shortError("x".repeat(200))).toHaveLength(80);
  });
});
