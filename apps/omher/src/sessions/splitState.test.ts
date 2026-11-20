import { describe, expect, it } from "vitest";
import type { Layout } from "../terminal/layout";
import { groupOf, groupSessions, leaveIn, moveIn, paneKeyIn, paneOf, parseSplits, pruneIn, serializeSplits, splitIn, zoomIn, type SplitGroup } from "./splitState";

const row = (a: Layout, b: Layout, ratio = 0.5): Layout => ({ dir: "row", ratio, a, b });
const col = (a: Layout, b: Layout, ratio = 0.5): Layout => ({ dir: "col", ratio, a, b });
const P = (n: number): Layout => ({ pane: n });

describe("TERMINALS splits", () => {
  it("names panes by session number", () => {
    expect(paneOf("s12")).toBe(12);
    expect(paneOf("x12")).toBeNull();
    expect(paneOf("s")).toBeNull();
  });

  it("splits right and down, any nesting, up to four sessions", () => {
    let g: SplitGroup[] = [];
    g = splitIn(g, "s1", "right", "s2");
    expect(g).toEqual([{ layout: row(P(1), P(2)) }]);
    g = splitIn(g, "s2", "down", "s3");
    expect(g[0].layout).toEqual(row(P(1), col(P(2), P(3))));
    g = splitIn(g, "s1", "down", "s4");
    expect(groupSessions(g[0])).toEqual(["s1", "s4", "s2", "s3"]);
    // a fifth does not fit
    expect(splitIn(g, "s3", "right", "s5")).toBe(g);
    // a session already in the split is not added twice
    expect(splitIn(g, "s1", "right", "s2")).toBe(g);
    // bots and threads have no session number: never in a split
    expect(splitIn([], "s1", "right", "kami")).toEqual([]);
  });

  it("a session moved into another split leaves its old one (which ends when one pane is left)", () => {
    let g = splitIn([], "s1", "right", "s2");
    g = splitIn(g, "s3", "right", "s2");
    expect(g).toEqual([{ layout: row(P(3), P(2)) }]);
    expect(groupOf(g, "s1")).toBeNull();
  });

  it("closing a pane gives its room to the part beside it and the keyboard to the nearest pane", () => {
    const g: SplitGroup[] = [{ layout: row(P(1), col(P(2), P(3))) }];
    const r = leaveIn(g, "s3");
    expect(r.groups).toEqual([{ layout: row(P(1), P(2)) }]);
    expect(r.heir).toBe("s2");
    const last = leaveIn(r.groups, "s1");
    expect(last.groups).toEqual([]);
    expect(last.heir).toBe("s2");
  });

  it("moves a pane by trading places with its neighbour", () => {
    const g: SplitGroup[] = [{ layout: row(P(1), P(2), 0.3) }];
    expect(moveIn(g, "s1", "right")[0].layout).toEqual(row(P(2), P(1), 0.3));
    expect(moveIn(g, "s1", "left")[0].layout).toEqual(row(P(1), P(2), 0.3));
  });

  it("drops panes whose session is gone", () => {
    const g: SplitGroup[] = [{ layout: row(P(1), col(P(2), P(3))) }];
    expect(pruneIn(g, new Set(["s1", "s3"]))).toEqual([{ layout: row(P(1), P(3)) }]);
    expect(pruneIn(g, new Set(["s1"]))).toEqual([]);
  });

  it("reads the pane keys: focus, step, move, zoom, equalize, close; nothing outside a split", () => {
    const g: SplitGroup[] = [{ layout: row(P(1), col(P(2), P(3)), 0.7) }];
    expect(paneKeyIn(g, "s1", { kind: "focus", dir: "right" }).focus).toBe("s2");
    expect(paneKeyIn(g, "s3", { kind: "focus", dir: "up" }).focus).toBe("s2");
    expect(paneKeyIn(g, "s1", { kind: "focus", dir: "left" })).toMatchObject({ focus: null, took: true });
    expect(paneKeyIn(g, "s3", { kind: "step", step: 1 }).focus).toBe("s1");
    expect(paneKeyIn(g, "s1", { kind: "step", step: -1 }).focus).toBe("s3");
    expect(paneKeyIn(g, "s1", { kind: "zoom" }).groups[0].zoom).toBe(true);
    expect(paneKeyIn(g, "s1", { kind: "equalize" }).groups[0].layout).toMatchObject({ ratio: 0.5 });
    expect(paneKeyIn(g, "s2", { kind: "close" })).toMatchObject({ groups: [{ layout: row(P(1), P(3), 0.7) }], focus: "s3", took: true });
    // moving the keyboard out of a zoomed pane shows every pane again
    expect(paneKeyIn(zoomIn(g, "s1", true), "s1", { kind: "focus", dir: "right" }).groups[0].zoom).toBe(false);
    // a session alone: the key is not the split's
    expect(paneKeyIn(g, "s9", { kind: "close" }).took).toBe(false);
  });

  it("is saved and read back, checked", () => {
    const g: SplitGroup[] = [{ layout: row(P(1), col(P(2), P(3), 0.25)), zoom: true }];
    expect(parseSplits(serializeSplits(g))).toEqual(g);
    expect(parseSplits(null)).toEqual([]);
    expect(parseSplits("{oops")).toEqual([]);
    // one pane is no split; a pane twice, five panes or a session in two splits is dropped
    expect(parseSplits(JSON.stringify({ groups: [{ layout: P(1) }] }))).toEqual([]);
    expect(parseSplits(JSON.stringify({ groups: [{ layout: row(P(1), P(1)) }] }))).toEqual([]);
    expect(parseSplits(JSON.stringify({ groups: [{ layout: row(row(P(1), P(2)), row(P(3), row(P(4), P(5)))) }] }))).toEqual([]);
    expect(parseSplits(JSON.stringify({ groups: [{ layout: row(P(1), P(2)) }, { layout: row(P(2), P(3)) }] }))).toEqual([{ layout: row(P(1), P(2)) }]);
    // a ratio out of range is kept inside it
    expect(parseSplits(JSON.stringify({ groups: [{ layout: { dir: "row", ratio: 7, a: P(1), b: P(2) } }] }))[0].layout).toMatchObject({ ratio: 0.95 });
    expect(parseSplits(JSON.stringify({ groups: [{ layout: { dir: "diag", ratio: 0.5, a: P(1), b: P(2) } }] }))).toEqual([]);
  });
});
