import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import type { AgentRun, RunNode } from "../lib/runs";
import {
  BOX_INNER_MAX,
  BOX_INNER_MIN,
  boxHeight,
  boxText,
  cells,
  fit,
  frontiers,
  GAP,
  gapGroups,
  GEOMETRY,
  layoutBoxes,
  middleCut,
  routeGroup,
  shortModel,
  statusOf,
  type Rect,
} from "./boxView";

const node = (id: string, deps: string[] = [], extra: Partial<RunNode> = {}): RunNode => ({ id, label: id, deps, layer: 0, state: "done", attempts: [], ...extra });
const dag = (nodes: RunNode[]): Pick<AgentRun, "kind" | "nodes"> => ({ kind: "dag", nodes });
const M = { cw: 7, line: 18 };

/** The TUI's own sample (docs/CODING-OBSERVABILITY.md): one node, three that wait on it, one that waits on those. */
const sample = () =>
  dag([
    node("api", [], { label: "Export API", route: "quick", model: "z-ai/glm-5.3-flash", effort: "low", started: 0, ended: 12 }),
    node("button", ["api"], { label: "Export button", route: "unspecified-high", model: "glm-5.3", effort: "low", state: "running", started: 100, attempts: [{ n: 1, outcome: "open" }] }),
    node("docs", ["api"], { label: "Export docs", route: "writing", state: "running", attempts: [{ n: 1, outcome: "open" }] }),
    node("cli", ["api"], { label: "Export CLI flag", route: "quick", model: "glm-5.3-flash", effort: "low", state: "failed", started: 100, ended: 108, attempts: [{ n: 1, outcome: "failed" }] }),
    node("verify", ["button", "docs", "cli"], { label: "Verify export", route: "unspecified-high", state: "waiting" }),
  ]);

describe("text in cells", () => {
  it("counts a wide character as two cells", () => {
    expect(cells("Export API")).toBe(10);
    expect(cells("계획")).toBe(4);
    expect(cells("計画 ok")).toBe(7);
  });

  it("cuts to a width with an ellipsis, never past it", () => {
    expect(fit("Export button", 20)).toBe("Export button");
    expect(fit("Export button, Export docs", 12)).toBe("Export butt…");
    expect(cells(fit("게이트웨이 로그를 읽는다", 9))).toBeLessThanOrEqual(9);
    expect(fit("abc", 1)).toBe("…");
    expect(fit("abc", 0)).toBe("");
  });

  it("cuts a long title in the middle at word boundaries, keeping what tells two titles apart", () => {
    const a = middleCut("Codex skill discovery reads .agents/skills (Hermes)", 30);
    expect(a).toBe("Codex skill … (Hermes)");
    expect(cells(a)).toBeLessThanOrEqual(30);
    expect(middleCut("Short title", 30)).toBe("Short title");
    // no room for two halves: cut at the end
    expect(middleCut("Supercalifragilistic", 10)).toBe("Supercali…");
  });

  it("names a model as a box does: no provider path, no leading claude-", () => {
    expect(shortModel("anthropic/claude-opus-5-5")).toBe("opus-5-5");
    expect(shortModel("z-ai/glm-5.3-flash")).toBe("glm-5.3-flash");
    expect(shortModel("claude-")).toBe("claude-");
  });
});

describe("a node's status line", () => {
  const run = sample();
  const by = (id: string) => run.nodes.find((n) => n.id === id)!;
  const line = (n: RunNode, r = run) => {
    const s = statusOf(n, r);
    return `${s.glyph} ${s.word}`;
  };

  it("reads as the TUI words it", () => {
    expect(line(by("api"))).toBe("✓ Accepted");
    expect(line(by("button"))).toBe("● Running");
    expect(line(by("docs"))).toBe("◌ Handed out"); // out, and no helper has reported a model yet
    expect(line(by("cli"))).toBe("✗ Failed");
    expect(line(by("verify"))).toBe("○ Waits on 3 lanes");
    expect(statusOf(by("docs"), run).timed).toBe(false);
  });

  it("counts only the lanes still open, and says Waiting when none is", () => {
    const r = dag([node("a"), node("b", [], { state: "running" }), node("c", ["a", "b"], { state: "waiting" }), node("d", ["a"], { state: "waiting" })]);
    expect(line(r.nodes[2], r)).toBe("○ Waits on 1 lane");
    expect(line(r.nodes[3], r)).toBe("○ Waiting");
  });

  it("names retry, parked, blocked, cancelled, and a failure its repairs fixed", () => {
    const r = dag([
      node("a", [], { state: "failed" }),
      node("fix", [], { repairOf: "a" }),
      node("b", [], { state: "waiting", attempts: [{ n: 1, outcome: "retry" }] }),
      node("c", [], { state: "parked" }),
      node("d", [], { state: "blocked" }),
      node("e", [], { state: "cancelled" }),
    ]);
    const [a, , b, c, d, e] = r.nodes;
    expect([statusOf(a, r).tone, statusOf(a, r).note]).toEqual(["repaired", "repaired"]);
    expect(line(b, r)).toBe("○ Retry");
    expect(line(c, r)).toBe("○ Parked");
    expect(line(d, r)).toBe("! Blocked");
    expect(line(e, r)).toBe("▪ Cancelled");
  });

  it("says Done, not Accepted, for a run that is not a dag, and never Handed out there", () => {
    const r: Pick<AgentRun, "kind" | "nodes"> = { kind: "claude-task", nodes: [node("a"), node("b", [], { state: "running" })] };
    expect(line(r.nodes[0], r)).toBe("✓ Done");
    expect(line(r.nodes[1], r)).toBe("● Running");
  });
});

describe("a box's four lines", () => {
  const run = sample();
  const shape = frontiers(run.nodes);
  const text = (id: string, inner = 28, now = 121) => boxText(run.nodes.find((n) => n.id === id)!, run, shape, inner, now);

  it("is the title, category · model, glyph + status + time, and the parents or Start node", () => {
    expect(text("api")).toMatchObject({ title: "Export API", cat: "quick", model: " · glm-5.3-flash:low", glyph: "✓", status: "Accepted 12s", parents: "Start node", tone: "done" });
    expect(text("button")).toMatchObject({ cat: "unspecified-high", glyph: "●", status: "Running 21s", parents: "← Export API", tone: "running" });
    expect(text("docs")).toMatchObject({ cat: "writing", model: "", glyph: "◌", status: "Handed out", tone: "out" });
    expect(text("cli")).toMatchObject({ glyph: "✗", status: "Failed 8s", tone: "failed" });
    expect(text("verify")).toMatchObject({ glyph: "○", status: "Waits on 3 lanes", parents: "← Export button, Export doc…", tone: "waiting" });
  });

  it("cuts every line to the box", () => {
    for (const n of run.nodes) {
      const tx = boxText(n, run, shape, BOX_INNER_MIN, 121);
      expect(cells(tx.origin + tx.title)).toBeLessThanOrEqual(BOX_INNER_MIN - 3); // after the mark
      expect(cells(tx.cat + tx.model)).toBeLessThanOrEqual(BOX_INNER_MIN);
      expect(2 + cells(tx.status + tx.after)).toBeLessThanOrEqual(BOX_INNER_MIN);
      expect(cells(tx.parents)).toBeLessThanOrEqual(BOX_INNER_MIN);
    }
  });

  it("shows a token count whole or not at all, and marks a repair with ↻", () => {
    const r = dag([node("a", [], { state: "failed", started: 0, ended: 8, tokens: 1234 }), node("fix", [], { repairOf: "a", label: "Fix a", started: 10, ended: 20, tokens: 950 })]);
    const s = frontiers(r.nodes);
    expect(boxText(r.nodes[1], r, s, 28, 0)).toMatchObject({ origin: "↻ ", status: "Accepted 10s", after: " · ↓950" });
    expect(boxText(r.nodes[0], r, s, 30, 0)).toMatchObject({ status: "Failed 8s", after: " · repaired · ↓1.2k", tone: "repaired" });
    expect(boxText(r.nodes[0], r, s, 28, 0).after).toBe(" · repaired"); // the count no longer fits: left out, not cut
    expect(boxText(r.nodes[0], r, s, 21, 0).after).toBe(" · ↓1.2k"); // the note does not fit, the shorter count does
    expect(boxText(r.nodes[0], r, s, 18, 0).after).toBe("");
  });
});

describe("frontiers", () => {
  it("puts a node one frontier under the last of its parents", () => {
    const s = frontiers(sample().nodes);
    expect(s.rows).toEqual([["api"], ["button", "docs", "cli"], ["verify"]]);
    expect(s.parents.get("verify")).toEqual(["button", "docs", "cli"]);
    expect(s.edges.map((e) => `${e.from}>${e.to}`)).toEqual(["api>button", "api>docs", "api>cli", "button>verify", "docs>verify", "cli>verify"]);
    expect(s.drawn).toEqual(s.edges);
  });

  it("does not draw an edge another path already implies; it stays in the parents and the edge list", () => {
    const s = frontiers([node("a"), node("b", ["a"]), node("c", ["a", "b"])]);
    expect(s.edges.map((e) => `${e.from}>${e.to}`)).toEqual(["a>b", "a>c", "b>c"]);
    expect(s.drawn.map((e) => `${e.from}>${e.to}`)).toEqual(["a>b", "b>c"]);
    expect(s.parents.get("c")).toEqual(["a", "b"]);
  });

  it("stands a node nothing leads to just above the first node that waits on it", () => {
    // three independent parts of different depth and a closing check: the check's edges all join neighbours
    const s = frontiers([node("t1"), node("t2"), node("t3"), node("t4", ["t1"]), node("verify", ["t1", "t2", "t3", "t4"])]);
    expect(s.rows).toEqual([["t1"], ["t2", "t3", "t4"], ["verify"]]);
    expect(s.drawn.every((e) => s.layer.get(e.to)! - s.layer.get(e.from)! === 1)).toBe(true);
  });

  it("draws a dependency on a failed node from its repairs, which sit one frontier under it", () => {
    const s = frontiers([node("a", [], { state: "failed" }), node("fix1", [], { repairOf: "a" }), node("fix2", [], { repairOf: "a" }), node("b", ["a"], { state: "waiting" })]);
    expect(s.rows).toEqual([["a"], ["fix1", "fix2"], ["b"]]);
    expect(s.edges.map((e) => `${e.from}>${e.to}:${e.kind}`)).toEqual(["a>fix1:repair", "a>fix2:repair", "fix1>b:dep", "fix2>b:dep"]);
    expect([...s.origin.keys()]).toEqual(["fix1", "fix2"]);
  });

  it("orders a frontier under its parents, so two fans do not cross", () => {
    // b's child is listed first, a's children after it
    const s = frontiers([node("a"), node("b"), node("b1", ["b"]), node("a1", ["a"]), node("a2", ["a"])]);
    expect(s.rows).toEqual([["a", "b"], ["a1", "a2", "b1"]]);
  });

  it("keeps every node when the edges loop, and says the run looped", () => {
    const s = frontiers([node("a", ["b"]), node("b", ["a"]), node("c")]);
    expect(s.rows.flat().sort()).toEqual(["a", "b", "c"]);
    expect(s.looped).toBe(true);
    expect(frontiers(sample().nodes).looped).toBe(false);
  });
});

describe("the layout", () => {
  it("draws the TUI's sample as the TUI does at 100 columns: boxes 32 cells wide, three on a row, both gaps drawn", () => {
    const lay = layoutBoxes(sample(), { cells: 100, metrics: M });
    expect(lay.inner).toBe(28);
    expect(lay.perRow).toBe(3);
    expect(lay.w).toBe(100 * M.cw);
    expect(lay.boxH).toBe(boxHeight(M));
    // the lone first box stands over the middle one
    expect(lay.at.get("api")!.x).toBe(34 * M.cw);
    expect(lay.at.get("docs")!.x).toBe(34 * M.cw);
    expect(lay.at.get("verify")!.x).toBe(34 * M.cw);
    expect(lay.groups.map((g) => [g.parents, g.children])).toEqual([
      [["api"], ["button", "docs", "cli"]],
      [["button", "docs", "cli"], ["verify"]],
    ]);
    expect(lay.undrawn).toEqual([]);
    // "· Same frontier" under the row of three only
    expect(lay.labels.map((l) => l.frontier)).toEqual([1]);
  });

  it("wraps a frontier too wide for the panel, two boxes to a row, and joins it with the centred connector", () => {
    const lay = layoutBoxes(sample(), { cells: 60, metrics: M });
    expect(lay.perRow).toBe(2);
    expect(lay.inner).toBe(25);
    expect(lay.inner).toBeGreaterThanOrEqual(BOX_INNER_MIN);
    const rows = new Set(["button", "docs", "cli"].map((id) => lay.at.get(id)!.y));
    expect(rows.size).toBe(2);
    expect(lay.groups).toEqual([]);
    expect(lay.undrawn.map((u) => u.gap)).toEqual([0, 1]);
    expect(lay.undrawn[0].x).toBe(lay.w / 2);
  });

  it("never draws a box wider than the TUI's widest, nor past the width", () => {
    const long = dag([node("a", [], { label: "A title that is far longer than any box is ever allowed to be drawn in this view" })]);
    expect(layoutBoxes(long, { cells: 200, metrics: M }).inner).toBe(BOX_INNER_MAX);
    expect(layoutBoxes(long, { cells: 40, metrics: M }).inner).toBe(36);
  });

  it("leaves a gap undrawn when an edge skips a frontier, and draws the gaps it does not cross", () => {
    // d waits on b (two frontiers up) and on c; nothing implies b>d
    const run = dag([node("a"), node("b", ["a"]), node("x", ["a"]), node("c", ["x"]), node("d", ["b", "c"]), node("e", ["d"])]);
    const lay = layoutBoxes(run, { cells: 120, metrics: M });
    expect(lay.shape.rows).toEqual([["a"], ["b", "x"], ["c"], ["d"], ["e"]]);
    expect(lay.undrawn.map((u) => u.gap)).toEqual([1, 2]);
    expect(lay.groups.map((g) => g.gap)).toEqual([0, 3]);
  });

  it("gives a child of two fans a port for each, and draws them when the buses do not share the gap", () => {
    const run = dag([node("p1"), node("p2"), node("c1", ["p1"]), node("c2", ["p1", "p2"]), node("c3", ["p2"])]);
    const lay = layoutBoxes(run, { cells: 120, metrics: M });
    expect(lay.undrawn).toEqual([]);
    expect(lay.groups.map((g) => [g.parents, g.children])).toEqual([
      [["p1"], ["c1", "c2"]],
      [["p2"], ["c2", "c3"]],
    ]);
    expect(lay.groups[0].ports.c2).toBeLessThan(0);
    expect(lay.groups[1].ports.c2).toBeGreaterThan(0);
    expect(lay.groups[0].ports.c1).toBe(0);
  });

  it("leaves a gap undrawn when two buses would share a stretch of it", () => {
    // p1's fan spans c1..c3, and p2's only child c2 sits inside it: the two buses would cross
    const edge = (from: string, to: string) => ({ from, to, kind: "dep" as const });
    const shape = { layer: new Map([["p1", 0], ["p2", 0], ["c1", 1], ["c2", 1], ["c3", 1]]), drawn: [edge("p1", "c1"), edge("p1", "c3"), edge("p2", "c2")] };
    const crossed = new Map([["p1", 20], ["p2", 50], ["c1", 10], ["c2", 40], ["c3", 70]]);
    expect(gapGroups(shape, 0, crossed)).toBeNull();
    // the same edges with c2 moved out from between c1 and c3: two buses side by side
    const apart = new Map([["p1", 20], ["p2", 75], ["c1", 10], ["c3", 40], ["c2", 70]]);
    expect(gapGroups(shape, 0, apart)!.map((g) => [g.parents, g.children])).toEqual([
      [["p1"], ["c1", "c3"]],
      [["p2"], ["c2"]],
    ]);
    // in a run, a frontier is ordered under its parents first, which untangles this one
    const run = dag([node("p1"), node("p2"), node("c1", ["p1"]), node("c2", ["p2"]), node("c3", ["p1"])]);
    expect(layoutBoxes(run, { cells: 120, metrics: M }).undrawn).toEqual([]);
  });

  it("draws no gap as lines when the edges loop: the nodes on the loop share a frontier no line could show", () => {
    const run = dag([node("a"), node("b", ["a", "c"]), node("c", ["b"])]);
    const lay = layoutBoxes(run, { cells: 120, metrics: M });
    expect(lay.shape.looped).toBe(true);
    expect(lay.groups).toEqual([]);
    expect(lay.undrawn.map((u) => u.gap)).toEqual([0]);
    expect(lay.shape.edges.map((e) => `${e.from}>${e.to}`).sort()).toEqual(["a>b", "b>c", "c>b"]);
  });

  it("puts '· Same frontier' right of the first box's middle, clear of the line that leaves it", () => {
    const lay = layoutBoxes(sample(), { cells: 100, metrics: M });
    const first = lay.at.get("button")!;
    expect(lay.labels[0].x).toBeGreaterThan(first.x + lay.boxW / 2 + M.cw);
    expect(lay.labels[0].x).toBeLessThan(first.x + lay.boxW);
    expect(lay.labels[0].y).toBe(first.y + lay.boxH);
  });

  it("shows the first rows of a very long frontier, running then failed first, and how many more there are", () => {
    const nodes = Array.from({ length: 88 }, (_, i) => node(`s${i}`, [], { state: i >= 85 ? "running" : i === 40 ? "failed" : "done" }));
    const run: Pick<AgentRun, "kind" | "nodes"> = { kind: "codex-sub", nodes };
    const capped = layoutBoxes(run, { cells: 60, metrics: M, capRows: 8 });
    expect(capped.perRow).toBe(2);
    expect(capped.boxes.length).toBe(16);
    expect(capped.boxes.slice(0, 5).map((b) => b.id)).toEqual(["s85", "s86", "s87", "s40", "s0"]);
    expect(capped.more).toMatchObject([{ frontier: 0, hidden: 72, total: 88 }]);
    const all = layoutBoxes(run, { cells: 60, metrics: M, capRows: 8, opened: new Set([0]) });
    expect(all.boxes.length).toBe(88);
    expect(all.more).toMatchObject([{ hidden: 0, total: 88 }]); // "Show fewer"
    // the full view has no cap
    expect(layoutBoxes(run, { cells: 150, metrics: M }).boxes.length).toBe(88);
  });

  it("lays 40 real-shaped nodes out without two boxes overlapping, inside the width", () => {
    const big = JSON.parse(readFileSync(new URL("../lib/__fixtures__/big-run.json", import.meta.url), "utf-8")) as AgentRun;
    for (const width of [60, 150]) {
      const lay = layoutBoxes(big, { cells: width, metrics: M });
      expect(lay.boxes.length).toBe(40);
      expect(lay.w).toBeLessThanOrEqual(width * M.cw);
      for (const a of lay.boxes)
        for (const b of lay.boxes)
          if (a.id < b.id) expect(a.x < b.x + lay.boxW && b.x < a.x + lay.boxW && a.y < b.y + lay.boxH && b.y < a.y + lay.boxH, `${a.id} over ${b.id}`).toBe(false);
      expect(Math.min(...lay.boxes.map((b) => b.x))).toBeGreaterThanOrEqual(0);
    }
  });
});

describe("the lines between two frontiers", () => {
  const lay = layoutBoxes(sample(), { cells: 100, metrics: M });
  const rect = (id: string): Rect => ({ x: lay.at.get(id)!.x, y: lay.at.get(id)!.y, w: lay.boxW, h: lay.boxH });
  const tone = (id: string) => ({ api: "done", button: "running", docs: "out", cli: "failed", verify: "waiting" })[id]!;
  const running = (id: string) => id === "button";
  const nums = (d: string) => (d.match(/-?\d+(\.\d+)?/g) ?? []).map(Number);

  it("leaves each parent's bottom at its middle and ends with a head on each child's top", () => {
    const fan = routeGroup(lay.groups[0], rect, tone, running);
    const stub = fan.lines.find((l) => l.from.length === 1 && l.to.length === 3)!;
    const [x, y] = nums(stub.d);
    expect(Math.abs(x - (rect("api").x + lay.boxW / 2))).toBeLessThanOrEqual(1);
    expect(y).toBe(rect("api").y + lay.boxH);
    expect(stub.tone).toBe("done");
    expect(fan.heads.map((h) => h.to)).toEqual(["button", "docs", "cli"]);
    for (const h of fan.heads) {
      expect(h.y).toBe(rect(h.to).y);
      expect(Math.abs(h.x - (rect(h.to).x + lay.boxW / 2))).toBeLessThanOrEqual(1);
      expect(h.up).toBe(false);
    }
    // the bus runs between the first and the last child, a drop above them
    const bus = fan.lines.find((l) => l.key.endsWith(":bus"))!;
    const [bx1, by, bx2] = nums(bus.d);
    expect(Math.abs(by - (rect("docs").y - GEOMETRY.drop))).toBeLessThanOrEqual(0.5);
    expect(bx1).toBeLessThan(bx2);
    expect(Math.abs(bx2 - bx1 - (2 * (lay.boxW + GAP * M.cw) - 2 * GEOMETRY.r))).toBeLessThanOrEqual(1);
    // only the line into the running child flows
    expect(fan.lines.filter((l) => l.flow).map((l) => l.to)).toEqual([["button"]]);
    expect(fan.heads.filter((h) => h.flow).map((h) => h.to)).toEqual(["button"]);
  });

  it("colours a line by its parent, and a line parents of different states share by none", () => {
    const join = routeGroup(lay.groups[1], rect, tone, running);
    expect(join.lines.filter((l) => l.from.length === 1).map((l) => [l.from[0], l.tone])).toEqual([
      ["button", "running"],
      ["docs", "out"],
      ["cli", "failed"],
    ]);
    expect(join.lines.find((l) => l.key.endsWith(":bus"))!.tone).toBeNull();
    expect(join.heads).toHaveLength(1);
    expect(join.heads[0]).toMatchObject({ to: "verify", y: rect("verify").y });
  });

  it("draws one parent over one child as one straight line", () => {
    const run = dag([node("a"), node("b", ["a"])]);
    const l2 = layoutBoxes(run, { cells: 100, metrics: M });
    const r2 = (id: string): Rect => ({ x: l2.at.get(id)!.x, y: l2.at.get(id)!.y, w: l2.boxW, h: l2.boxH });
    const straight = routeGroup(l2.groups[0], r2, () => "done", () => false);
    expect(straight.lines).toHaveLength(1);
    const [x, y1, y2] = nums(straight.lines[0].d);
    expect(y1).toBe(r2("a").y + l2.boxH);
    expect(y2).toBe(r2("b").y - GEOMETRY.arrow);
    expect(Math.abs(x - (r2("a").x + l2.boxW / 2))).toBeLessThanOrEqual(1);
  });

  it("follows a dragged box: the head points up into a child moved above its parents", () => {
    const moved = (id: string): Rect => (id === "verify" ? { ...rect(id), y: -300 } : rect(id));
    const join = routeGroup(lay.groups[1], moved, tone, running);
    expect(join.heads[0]).toMatchObject({ to: "verify", up: true, y: -300 + lay.boxH });
  });
});
