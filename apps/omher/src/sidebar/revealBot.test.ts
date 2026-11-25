import { describe, expect, it } from "vitest";
import { topFor, wholeTop } from "./revealBot";

// a list box from y=100 to y=300, rows 40px tall from y=60 (scrolled 40px: the first row is above the box)
const box = { top: 100, bottom: 300 };
const rows = (from: number) => Array.from({ length: 10 }, (_, i) => ({ top: from + i * 40, bottom: from + i * 40 + 40 }));

describe("the BOTS list's top edge after a reveal", () => {
  it("is left alone when it already falls between two rows", () => {
    expect(wholeTop(40, 400, box, rows(60))).toBe(40);
  });

  it("scrolls on past a row cut at the top, keeping the revealed row whole", () => {
    // a row from 85 to 125 shows only its lower 25px under the header
    expect(wholeTop(55, 400, box, rows(85), { top: 245, bottom: 285 })).toBe(80);
  });

  it("goes back to the cut row's top where going on would cut the revealed row or pass the list's end", () => {
    // the revealed row sits at the bottom edge: going on 25px would push it past nothing, but the list ends there
    expect(wholeTop(55, 60, box, rows(85), { top: 245, bottom: 285 })).toBe(40);
    // going on would lift the revealed row (the first whole one) above the box
    expect(wholeTop(55, 400, box, rows(85), { top: 110, bottom: 150 })).toBe(40);
  });

  it("stays put when neither way keeps the revealed row whole", () => {
    expect(wholeTop(5, 400, box, rows(85), { top: 110, bottom: 300 })).toBe(5);
  });

  it("topFor still puts the row at the top within what the list can scroll", () => {
    expect(topFor(100, 250, 0, 1000)).toBe(150);
    expect(topFor(100, 250, 0, 90)).toBe(90);
  });
});
