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
  it("with no pair of whole-row ends, keeps TERMINALS' first row (a tall split card) whole when it fits", () => {
    // BOTS ends on a whole row only at 150, 250, 350 (tall bot rows); TERMINALS: a 256 px card first, then folder rows.
    // No pair of whole-row ends fits 440 px: an even split (220 each) would cut the card, hidden whole at the top
    const b = { need: 600, stops: [150, 250, 350, 450, 550] };
    const t = { need: 40 + 824, stops: [40 + 258 + 14, 40 + 345 + 14, 40 + 440 + 14] };
    const [hb, ht] = planSplit(440, b, t);
    expect(hb + ht).toBe(440);
    expect(ht).toBeGreaterThanOrEqual(t.stops[0]!);
    expect(hb).toBeGreaterThanOrEqual(96);
  });
  it("gives room the whole-row ends leave unused to the region that still hides rows: no empty band above the footer", () => {
    // BOTS shown whole (300); TERMINALS' next whole-row end after 268 is 400 (an open folder's header is refused in
    // between): the 61 px left would stand empty under TERMINALS while its rows hide behind the chevron
    const b = { need: 300, stops: [100, 200, 300] };
    const t = { need: 700, stops: [140, 268, 400, 520, 640] };
    const [hb, ht] = planSplit(629, b, t);
    expect(hb).toBe(300);
    expect(hb + ht).toBe(629);
    // both fit: the rest stays under them, as before
    expect(planSplit(665, { need: 300, stops: [] }, { need: 250, stops: [] })).toEqual([300, 250]);
    // a few px left over is no band: the whole-row end stays
    expect(planSplit(576, b, t)).toEqual([300, 268]);
  });
  it("keeps each region at least the minimum", () => {
    const [hb, ht] = planSplit(300, rows(30, 200, 3), rows(30, 200, 3));
    expect(hb).toBeGreaterThanOrEqual(96);
    expect(ht).toBeGreaterThanOrEqual(96);
    expect(hb + ht).toBeLessThanOrEqual(300);
  });
});
