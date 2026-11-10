import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import type { AgentRun, RunNode } from "../lib/runs";
import { GRID_CAP, PANEL_FLOOR, panelPlan, partsNoun, stateCounts } from "./RunGraph";

const fx = (name: string) => JSON.parse(readFileSync(fileURLToPath(new URL(`../lib/__fixtures__/${name}`, import.meta.url)), "utf-8"));
const big = fx("big-run.json") as AgentRun;
const routed = fx("runs-routed.json");
const v02 = routed.default.find((r: AgentRun) => r.id.endsWith("/omher-v02")) as AgentRun;
const W = 438; // the panel graph box's inner width at 1440

const node = (id: string, layer: number, state: RunNode["state"] = "done", deps: string[] = []): RunNode => ({ id, label: `Part ${id}`, deps, layer, state, attempts: [] });

describe("panelPlan: the floor", () => {
  it("never draws a card narrower than the floor, whatever the run", () => {
    for (const run of [big, v02]) {
      for (const maxH of [300, 460, 700]) {
        const p = panelPlan(run.nodes, W, maxH);
        for (const [, s] of p.lay.size) expect(s.w).toBeGreaterThanOrEqual(PANEL_FLOOR.cardW);
        expect(p.lay.w).toBeLessThanOrEqual(W);
      }
    }
  });
  it("a run whose layers fit side by side at the floor (two in the panel) keeps the layered graph and its links", () => {
    const two = [node("a", 0), node("b", 0), node("c", 1, "running", ["a", "b"])];
    const p = panelPlan(two, W, 460);
    expect(p.kind).toBe("graph");
    expect(p.lay.edges).toHaveLength(2);
    expect(p.groups.size).toBe(0);
    // three layers do not fit at 132px in the panel: 3 x 132 + 2 gutters > 406
    const small = fx("runs-bridge.json").runs.find((r: AgentRun) => r.id.endsWith("/codex-coexist")) as AgentRun;
    expect(panelPlan(small.nodes, W, 460).kind).toBe("stack");
  });
  it("a run too wide at the floor stacks its layers in order, every part on screen when the box is tall enough", () => {
    const p = panelPlan(v02.nodes, W, 700);
    expect(p.kind).toBe("stack");
    expect(p.nodes).toHaveLength(v02.nodes.length);
    expect(p.lay.h).toBeLessThanOrEqual(700);
    const ys = p.lay.columns.map((c) => c.y);
    expect(ys).toEqual([...ys].sort((a, b) => a - b));
    // each band's cards sit under its label and above the next band's
    for (const n of v02.nodes) {
      const y = p.lay.pos.get(n.id)!.y;
      const band = p.lay.columns.findIndex((c) => c.layer === n.layer);
      expect(y).toBeGreaterThan(p.lay.columns[band].y);
      if (band + 1 < p.lay.columns.length) expect(y).toBeLessThan(p.lay.columns[band + 1].y);
    }
  });
  it("a stack taller than the box folds its biggest finished layer into one group card; opening it shows every part", () => {
    const p = panelPlan(big.nodes, W, 460);
    expect(p.kind).toBe("stack");
    expect(p.groups.size).toBeGreaterThan(0);
    const [id, g] = [...p.groups][0];
    expect(id).toMatch(/^group:\d+$/);
    expect(g.members.length).toBeGreaterThanOrEqual(2);
    // done layers fold before one that holds a running part
    const order = [...p.groups.values()].map((x) => x.members.some((m) => m.state === "running"));
    expect(order[0]).toBe(false);
    const opened = panelPlan(big.nodes, W, 460, { opened: new Set([g.layer]) });
    expect(opened.groups.has(id)).toBe(false);
    for (const m of g.members) expect(opened.lay.pos.has(m.id)).toBe(true);
    expect(opened.tall.has(g.layer)).toBe(true);
  });
  it("in the graph, a layer taller than the box folds and its links become the group's", () => {
    const nodes = [node("a", 0), node("a2", 0), ...Array.from({ length: 6 }, (_, i) => node(`b${i}`, 1, i === 0 ? "failed" : "done", i < 2 ? ["a"] : ["a2"]))];
    const p = panelPlan(nodes, W, 300);
    expect(p.kind).toBe("graph");
    expect([...p.groups.keys()]).toEqual(["group:1"]);
    expect(p.lay.edges.map((e) => `${e.from}>${e.to}`).sort()).toEqual(["a2>group:1", "a>group:1"]);
    expect(p.nodes.find((n) => n.id === "group:1")!.state).toBe("failed");
    // opened, every part is back with its own link
    expect(panelPlan(nodes, W, 300, { opened: new Set([1]) }).lay.edges).toHaveLength(6);
  });
});

describe("panelPlan: one layer is a grid", () => {
  const many = (n: number, running = 0, failed = 0) =>
    Array.from({ length: n }, (_, i) => node(`s${i}`, 0, i >= n - running ? "running" : i >= n - running - failed ? "failed" : "done"));
  it("fills the width with cards at the floor or wider, running first, then failed", () => {
    const nodes = many(88, 3, 2);
    const p = panelPlan(nodes, W, 600);
    expect(p.kind).toBe("grid");
    const xs = new Set([...p.lay.pos.values()].map((b) => b.x));
    expect(xs.size).toBe(Math.floor((W - 32 + 8) / (PANEL_FLOOR.cardW + 8)));
    const right = Math.max(...[...p.lay.pos].map(([id, b]) => b.x + p.lay.size.get(id)!.w));
    expect(right).toBe(W - 16);
    expect(p.nodes.slice(0, 5).map((n) => n.state)).toEqual(["running", "running", "running", "failed", "failed"]);
  });
  it(`shows ${GRID_CAP} before "Show all", and all of them after`, () => {
    const p = panelPlan(many(88), W, 600);
    expect(p.grid).toMatchObject({ total: 88, shown: GRID_CAP, head: true, foot: true });
    expect(panelPlan(many(88), W, 600, { all: true }).nodes).toHaveLength(88);
    // a few over the cap: no "Show all" for 2 cards
    expect(panelPlan(many(GRID_CAP + 2), W, 600).grid).toMatchObject({ shown: GRID_CAP + 2, foot: false });
    // a short run has no summary line (the plan card says it)
    expect(panelPlan(many(3), W, 600).grid!.head).toBe(false);
  });
  it("the summary counts in the grid's order and names the parts", () => {
    expect(stateCounts(many(88, 3))).toEqual([
      [3, "running"],
      [85, "done"],
    ]);
    expect([partsNoun("dag"), partsNoun("delegate"), partsNoun("claude-task"), partsNoun("codex-sub")]).toEqual(["parts", "helpers", "sub-runs", "sub-runs"]);
  });
});
