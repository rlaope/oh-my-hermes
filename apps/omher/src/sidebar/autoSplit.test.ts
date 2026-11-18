import { describe, expect, it } from "vitest";
import { planSplit, type Region } from "./autoSplit";

const rows = (start: number, pitch: number, n: number, band = 14): Region => {
  const stops = Array.from({ length: n }, (_, i) => start + pitch * (i + 1) + band);
  return { need: start + pitch * n, stops };
};

describe("auto BOTS | TERMINALS split", () => {
  it("gives each its rows when both fit; the rest stays under them", () => {
    expect(planSplit(665, { need: 300, stops: [] }, { need: 250, stops: [] })).toEqual([300, 250]);
  });
  it("cuts on a whole row: the room left unused is under half a card", () => {
    // BOTS: a 50px bot row, then six 24px thread rows, twelve times
    const stops: number[] = [];
    let y = 30;
    for (let i = 0; i < 12; i++) for (const h of [50, 24, 24, 24, 24, 24, 24]) stops.push((y += h) + 14);
    const b = { need: y, stops };
    const t = rows(30, 50, 15);
    const [hb, ht] = planSplit(666, b, t);
    expect(hb + ht).toBeLessThanOrEqual(666);
    expect(666 - hb - ht).toBeLessThan(25);
    expect(b.stops).toContain(hb);
    expect(t.stops).toContain(ht);
  });
  it("shows the smaller region whole when it needs at most 60% of the room", () => {
    const b = rows(30, 40, 20);
    const t = { need: 370, stops: [100, 150, 200, 250, 300, 350] };
    const [hb, ht] = planSplit(665, b, t);
    expect(ht).toBe(370);
    expect(b.stops).toContain(hb);
    expect(665 - hb - ht).toBeLessThan(20);
  });
  it("keeps each region at least the minimum", () => {
    const [hb, ht] = planSplit(300, rows(30, 200, 3), rows(30, 200, 3));
    expect(hb).toBeGreaterThanOrEqual(96);
    expect(ht).toBeGreaterThanOrEqual(96);
    expect(hb + ht).toBeLessThanOrEqual(300);
  });
});
