import { describe, expect, it } from "vitest";
import { clampSplit, readSplit, SPLIT_MIN } from "./SideSplit";

describe("BOTS | TERMINALS split", () => {
  it("is BOTS' share of the two regions, each at least the minimum", () => {
    expect(clampSplit(600, 300)).toBe(0.5);
    expect(clampSplit(600, 400)).toBeCloseTo(400 / 600);
    expect(clampSplit(600, 20)).toBe(SPLIT_MIN / 600);
    expect(clampSplit(600, 590)).toBe((600 - SPLIT_MIN) / 600);
  });
  it("splits evenly when there is no room for both minimums", () => {
    expect(clampSplit(200, 30)).toBe(0.5);
    expect(clampSplit(0, 30)).toBe(0.5);
  });
  it("reads only a share between 0 and 1; anything else is auto", () => {
    expect(readSplit("0.42")).toBe(0.42);
    for (const raw of [null, "", "x", "0", "1", "-0.2", "3"]) expect(readSplit(raw)).toBeNull();
  });
});
