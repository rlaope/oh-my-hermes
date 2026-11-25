import { describe, expect, it } from "vitest";
import type { Layout } from "../terminal/layout";
import { CARD_MAX_H, CARD_MIN_H, cardText, cellBoxes, cellState, cellText, clampCardHeight, defaultCardHeight, elapsedLabel } from "./splitCard";

const row = (a: Layout, b: Layout, ratio = 0.5): Layout => ({ dir: "row", ratio, a, b });
const col = (a: Layout, b: Layout, ratio = 0.5): Layout => ({ dir: "col", ratio, a, b });
const P = (n: number): Layout => ({ pane: n });

describe("split card height", () => {
  it("grows with the panes and keeps the shortest cell 42 px tall", () => {
    expect(defaultCardHeight(row(P(1), P(2)))).toBe(62);
    // two stacked: half each, so 84 for two 42 px cells
    expect(defaultCardHeight(col(P(1), P(2)))).toBe(84);
    expect(defaultCardHeight(row(P(1), col(P(2), P(3))))).toBe(84);
    expect(defaultCardHeight(col(row(P(1), P(2)), row(P(3), P(4))))).toBe(88);
    // one tall pane and three stacked beside it: a third-height cell needs 126
    expect(defaultCardHeight(row(P(1), col(P(2), col(P(3), P(4)), 1 / 3)))).toBe(126);
  });

  it("never passes the cap", () => {
    expect(defaultCardHeight(col(P(1), col(P(2), P(3)), 0.1))).toBe(CARD_MAX_H);
  });

  it("clamps a dragged height to whole px in range", () => {
    expect(clampCardHeight(10)).toBe(CARD_MIN_H);
    expect(clampCardHeight(46)).toBe(46);
    expect(clampCardHeight(120.6)).toBe(121);
    expect(clampCardHeight(240)).toBe(240);
    expect(clampCardHeight(999)).toBe(CARD_MAX_H);
  });
});

describe("cell text placement", () => {
  it("follows a lone cell's size", () => {
    expect(cellText(120, 30)).toBe("line");
    expect(cellText(200, 44)).toBe("beside");
    expect(cellText(100, 120)).toBe("stack");
    expect(cellText(300, 80)).toBe("beside");
  });

  it("is one layout per card, from its smallest cell: never a stacked cell beside cells with text beside the mark", () => {
    // the sidebar's map is 202 px wide (248 px sidebar): side by side, each cell is 99 px
    const W = 202;
    const of = (layout: Layout, h: number) => cardText(cellBoxes(layout, W, h));
    // two side by side at the default 62 px: stacked, with their last lines
    expect(of(row(P(1), P(2)), defaultCardHeight(row(P(1), P(2))))).toEqual({ text: "stack", lines: true });
    // one tall on the left, two stacked on the right (84 px): all stacked; the 40 px right cells hold no last line
    expect(of(row(P(1), col(P(2), P(3))), 84)).toEqual({ text: "stack", lines: false });
    // the same card capped to 46 px (a short window): every cell one line
    expect(of(row(P(1), col(P(2), P(3))), 46)).toEqual({ text: "line", lines: false });
    // 1+3 at its default 126 px: one layout for all four
    expect(of(row(P(1), col(P(2), col(P(3), P(4)), 1 / 3)), 126).text).toBe("stack");
    // two stacked full-width cells: each wide enough for the title beside the mark
    expect(of(col(P(1), P(2)), 84)).toEqual({ text: "beside", lines: true });
  });

  it("gives every cell in a card the same answer, whatever its own size", () => {
    const W = 202;
    for (const [layout, h] of [
      [row(P(1), col(P(2), P(3))), 84],
      [row(P(1), col(P(2), P(3))), 46],
      [row(P(1), col(P(2), P(3))), 140],
      [col(row(P(1), P(2)), row(P(3), P(4))), 88],
      [row(P(1), col(P(2), col(P(3), P(4)), 1 / 3)), 240],
    ] as const) {
      const boxes = cellBoxes(layout, W, h);
      const own = new Set(boxes.map((b) => cellText(b.w, b.h)));
      const card = cardText(boxes).text;
      // a mixed card is what the review found (C1, C5); the card's one answer is that of its tightest cell
      expect([...own]).toContain(card);
    }
  });
});

describe("cell state", () => {
  it("puts waiting first, then errors, work, background", () => {
    expect(cellState({ status: "busy", asked: true })).toBe("wait");
    expect(cellState({ status: "bell", asked: true, background: 2 })).toBe("wait");
    expect(cellState({ status: "err", asked: false, background: 1 })).toBe("err");
    expect(cellState({ status: "busy", asked: false, background: 1 })).toBe("work");
    expect(cellState({ status: "ok", asked: false, background: 1 })).toBe("bg");
    expect(cellState({ status: null, asked: false, background: 1 })).toBe("bg");
    expect(cellState({ status: "ok", asked: false })).toBe("ok");
    expect(cellState({ status: null, asked: false, background: 0 })).toBe("idle");
  });
  it("draws a ring nobody saw as news, never the wait: only a bot's request to type is a wait", () => {
    expect(cellState({ status: "news", asked: false })).toBe("news");
    expect(cellState({ status: "news", asked: false, background: 2 })).toBe("news");
    expect(cellState({ status: "news", asked: true })).toBe("wait");
    expect(cellState({ status: "err", asked: false })).toBe("err");
  });
});

describe("elapsed time", () => {
  const at = 1_000_000;
  it("shows from a minute of one busy streak", () => {
    expect(elapsedLabel(at, true, at + 59_999)).toBeNull();
    expect(elapsedLabel(at, true, at + 60_000)).toEqual({ text: "1m", old: false });
    expect(elapsedLabel(at, true, at + 600_000)).toEqual({ text: "10m", old: true });
    expect(elapsedLabel(at, true, at + 2 * 3_600_000)).toEqual({ text: "2h", old: true });
  });

  it("shows nothing when not busy or with no streak", () => {
    expect(elapsedLabel(at, false, at + 600_000)).toBeNull();
    expect(elapsedLabel(undefined, true, at)).toBeNull();
  });
});

describe("cell boxes", () => {
  it("places a 2×2 split's cells inside the map, 2 px apart", () => {
    const boxes = cellBoxes(col(row(P(1), P(2)), row(P(3), P(4))), 232, 88);
    expect(boxes.map((b) => b.id)).toEqual(["s1", "s2", "s3", "s4"]);
    expect(boxes).toEqual([
      { id: "s1", x: 1, y: 1, w: 114, h: 42 },
      { id: "s2", x: 117, y: 1, w: 114, h: 42 },
      { id: "s3", x: 1, y: 45, w: 114, h: 42 },
      { id: "s4", x: 117, y: 45, w: 114, h: 42 },
    ]);
    for (const b of boxes) {
      expect(b.x).toBeGreaterThanOrEqual(0);
      expect(b.y).toBeGreaterThanOrEqual(0);
      expect(b.x + b.w).toBeLessThanOrEqual(232);
      expect(b.y + b.h).toBeLessThanOrEqual(88);
    }
    // neighbours are exactly the gap apart
    expect(boxes[1].x - (boxes[0].x + boxes[0].w)).toBe(2);
    expect(boxes[2].y - (boxes[0].y + boxes[0].h)).toBe(2);
  });
});
