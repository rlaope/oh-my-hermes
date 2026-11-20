import { describe, expect, it } from "vitest";
import { createEdges, working } from "./power";

describe("power busy edges", () => {
  it("sends busy once and idle only after the quiet spell", () => {
    const sent: boolean[] = [];
    const e = createEdges((b) => sent.push(b), 5_000);
    // agent prints for a while: one busy edge, however many readings
    for (let t = 0; t <= 20_000; t += 2_000) e.update(true, t);
    expect(sent).toEqual([true]);
    // a short pause between outputs is no edge
    e.update(false, 22_000);
    e.update(false, 24_000);
    e.update(true, 26_000);
    expect(sent).toEqual([true]);
    // it stops: idle once quiet for 5 s, and only once
    e.update(false, 28_000);
    e.update(false, 30_000);
    expect(sent).toEqual([true]);
    e.update(false, 33_000);
    expect(sent).toEqual([true, false]);
    for (let t = 35_000; t < 60_000; t += 2_000) e.update(false, t);
    expect(sent).toEqual([true, false]);
    e.update(true, 61_000);
    expect(sent).toEqual([true, false, true]);
  });

  it("idle readings with nothing sent send nothing; reset forgets", () => {
    const sent: boolean[] = [];
    const e = createEdges((b) => sent.push(b), 5_000);
    e.update(false, 0);
    e.update(false, 10_000);
    expect(sent).toEqual([]);
    e.update(true, 11_000);
    e.reset();
    e.update(true, 12_000);
    expect(sent).toEqual([true, true]);
  });
});

describe("what counts as work", () => {
  const now = 100_000;
  it("an agent that printed recently, or reports progress, or a bot turn", () => {
    expect(working([{ agent: true, running: true, lastOut: now - 1_000 }], false, now, 5_000)).toBe(true);
    expect(working([{ agent: true, running: true, lastOut: now - 6_000 }], false, now, 5_000)).toBe(false);
    expect(working([{ agent: true, running: true, progress: true }], false, now, 5_000)).toBe(true);
    expect(working([], true, now, 5_000)).toBe(true);
  });
  it("a plain shell printing, or an ended program, is not", () => {
    expect(working([{ agent: false, running: true, lastOut: now }], false, now, 5_000)).toBe(false);
    expect(working([{ agent: true, running: false, lastOut: now }], false, now, 5_000)).toBe(false);
  });
});
