import { describe, expect, it } from "vitest";
import type { Layout } from "../terminal/layout";
import { equalizeIn, getSplit, groupOf, groupSessions, leaveIn, mapHeightIn, moveIn, paneKeyIn, paneOf, parseSplits, pruneIn, ratioIn, resetSplit, serializeSplits, setMapHeight, setSplit, splitIn, zoomIn, type SplitGroup } from "./splitState";

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
    // a session already in the split is not added twice: it moves there (a full split still takes it)
    expect(splitIn(g, "s1", "right", "s2")[0].layout).toEqual(row(col(row(P(1), P(2)), P(4)), P(3)));
    // a pane dropped on itself stays
    expect(splitIn(g, "s2", "left", "s2")).toBe(g);
    // bots and threads have no session number: never in a split
    expect(splitIn([], "s1", "right", "kami")).toEqual([]);
  });

  it("splits left and up too: the new pane goes first", () => {
    expect(splitIn([], "s1", "left", "s2")).toEqual([{ layout: row(P(2), P(1)) }]);
    expect(splitIn([], "s1", "up", "s2")).toEqual([{ layout: col(P(2), P(1)) }]);
    // a pane of a two-pane split moved to the other side of its neighbour
    expect(splitIn([{ layout: row(P(1), P(2)) }], "s1", "left", "s2")).toEqual([{ layout: row(P(2), P(1)) }]);
    expect(splitIn([{ layout: row(P(1), P(2)) }], "s1", "down", "s2")).toEqual([{ layout: col(P(1), P(2)) }]);
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
    // moving the keyboard in a zoomed split keeps it zoomed: the zoom goes with the keyboard (SplitView draws the
    // focused pane), on the arrows and on ⌘] / ⌘[
    const z = zoomIn(g, "s1", true);
    expect(paneKeyIn(z, "s1", { kind: "focus", dir: "right" })).toMatchObject({ focus: "s2", took: true });
    expect(paneKeyIn(z, "s1", { kind: "focus", dir: "right" }).groups[0].zoom).toBe(true);
    expect(paneKeyIn(z, "s1", { kind: "step", step: 1 })).toMatchObject({ focus: "s2", took: true });
    expect(paneKeyIn(z, "s1", { kind: "step", step: 1 }).groups[0].zoom).toBe(true);
    expect(paneKeyIn(z, "s1", { kind: "step", step: -1 }).groups[0].zoom).toBe(true);
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

  it("un-zooms when the zoomed split's layout changes: a split, a pane closed or moved (tmux)", () => {
    const z: SplitGroup[] = [{ layout: row(P(1), col(P(2), P(3))), zoom: true }];
    // splitting while zoomed shows every pane, the new one too
    expect(splitIn(z, "s1", "down", "s4")[0].zoom).toBeUndefined();
    // closing the zoomed pane (or any pane of the split): every pane shows again
    expect(leaveIn(z, "s1").groups[0].zoom).toBeUndefined();
    expect(paneKeyIn(z, "s2", { kind: "close" }).groups[0].zoom).toBeUndefined();
    // moving the zoomed pane: seen, not made behind the zoom
    expect(moveIn(z, "s1", "right")[0].zoom).toBeUndefined();
    expect(paneKeyIn(z, "s1", { kind: "move", dir: "right" }).groups[0].zoom).toBeUndefined();
    // a move that goes nowhere changes nothing
    expect(moveIn(z, "s1", "left")[0].zoom).toBe(true);
    // ratios and evening out keep the zoom
    expect(paneKeyIn(z, "s1", { kind: "equalize" }).groups[0].zoom).toBe(true);
  });

  it("keeps the card's dragged height with the split, through restarts and layout changes", () => {
    const at = (mapH: unknown) => parseSplits(JSON.stringify({ groups: [{ layout: row(P(1), P(2)), mapH }] }))[0];
    expect(at(120).mapH).toBe(120);
    expect(at(999).mapH).toBe(240);
    expect(at(3).mapH).toBe(46);
    expect("mapH" in at("x")).toBe(false);
    expect("mapH" in at(null)).toBe(false);
    // NaN serializes as null; a non-finite number never comes back
    expect("mapH" in at(Number.NaN)).toBe(false);
    const g: SplitGroup[] = [{ layout: col(row(P(1), P(2)), row(P(3), P(4))), mapH: 120 }];
    expect(parseSplits(serializeSplits(g))).toEqual(g);
    const left = leaveIn(g, "s4").groups;
    expect(left[0].mapH).toBe(120);
    expect(groupSessions(left[0])).toHaveLength(3);
    const two: SplitGroup[] = [{ layout: row(P(1), P(2)), mapH: 120 }];
    expect(splitIn(two, "s1", "down", "s3")[0].mapH).toBe(120);
    expect(moveIn(g, "s1", "right")[0].mapH).toBe(120);
    expect(ratioIn(g, "s1", "", 0.3)[0].mapH).toBe(120);
    expect(equalizeIn(g, "s1")[0].mapH).toBe(120);
    expect(zoomIn(g, "s1")[0].mapH).toBe(120);
    expect(mapHeightIn(g, "s2", 500)[0].mapH).toBe(240);
    expect("mapH" in mapHeightIn(g, "s2", null)[0]).toBe(false);
    // a session in no split changes nothing
    expect(mapHeightIn(g, "s9", 80)).toBe(g);
  });

  it("a pane moved within its own two-pane split keeps the card's height; a new split starts without one", () => {
    const two: SplitGroup[] = [{ layout: row(P(1), P(2)), mapH: 94 }];
    // s2 dropped below s1: the split ends for a moment (s2 leaves it) and is made again, top and bottom
    const moved = splitIn(two, "s1", "down", "s2");
    expect(moved).toHaveLength(1);
    expect(moved[0].layout).toMatchObject({ dir: "col", a: { pane: 1 }, b: { pane: 2 } });
    expect(moved[0].mapH).toBe(94);
    // a session out of every split joining a lone one makes a new split, at the default height
    expect("mapH" in splitIn([], "s1", "right", "s3")[0]).toBe(false);
    // s3 taken out of another split onto a lone s1 does not carry that split's height
    expect("mapH" in splitIn([{ layout: row(P(3), P(4)), mapH: 94 }], "s1", "right", "s3")[0]).toBe(false);
  });

  it("saves a set card height with the split", () => {
    setSplit({ groups: [{ layout: row(P(1), P(2)) }] });
    setMapHeight("s2", 100);
    expect(getSplit().groups[0].mapH).toBe(100);
    setMapHeight("s1", null);
    expect("mapH" in getSplit().groups[0]).toBe(false);
    resetSplit();
  });
});
