import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import type { AgentRun } from "../lib/runs";
import { columnLabel, countCrossings, distinctLabels, layerName, layoutRun, linksOf, orderLayers, sizeKind } from "./layout";
import { clampWords } from "./format";

const fx = (name: string) => JSON.parse(readFileSync(fileURLToPath(new URL(`../lib/__fixtures__/${name}`, import.meta.url)), "utf-8"));
const big = fx("big-run.json") as AgentRun;
const OPTS = { width: 440, cardH: 50, gutter: 44, rowGap: 10, pad: 12, minCard: 104, maxCard: 168, labelH: 20 };

describe("layout", () => {
  it("the synthetic run is 40 nodes over 6 layers", () => {
    expect(big.nodes).toHaveLength(40);
    expect(new Set(big.nodes.map((n) => n.layer)).size).toBe(6);
  });
  it("the barycenter sweeps cut crossings on the big run and never add any", () => {
    const { crossings, before } = orderLayers(big.nodes);
    expect(before).toBeGreaterThan(0);
    expect(crossings).toBeLessThan(before);
  });
  it("no two cards overlap, every link becomes an edge, every edge runs right-middle to left-middle", () => {
    const l = layoutRun(big.nodes, OPTS);
    const boxes = big.nodes.map((n) => ({ id: n.id, ...l.pos.get(n.id)! }));
    for (let i = 0; i < boxes.length; i++)
      for (let j = i + 1; j < boxes.length; j++) {
        const a = boxes[i];
        const b = boxes[j];
        const [sa, sb] = [l.size.get(a.id)!, l.size.get(b.id)!];
        const apart = a.x + sa.w <= b.x || b.x + sb.w <= a.x || a.y + sa.h <= b.y || b.y + sb.h <= a.y;
        expect(apart, `${a.id} overlaps ${b.id}`).toBe(true);
      }
    expect(l.edges).toHaveLength(linksOf(big.nodes).length);
    for (const e of l.edges) {
      const a = l.pos.get(e.from)!;
      const b = l.pos.get(e.to)!;
      const [sa, sb] = [l.size.get(e.from)!, l.size.get(e.to)!];
      expect([e.x1, e.y1, e.x2, e.y2]).toEqual([a.x + sa.w, a.y + sa.h / 2, b.x, b.y + sb.h / 2]);
      expect(e.x2).toBeGreaterThan(e.x1); // never enters from below or behind
    }
  });
  it("fits the panel width when it can, and the card width stays in bounds", () => {
    const small = fx("runs-bridge.json").runs.find((r: AgentRun) => r.id.endsWith("/codex-coexist")) as AgentRun;
    const l = layoutRun(small.nodes, OPTS);
    expect(l.w).toBe(440);
    expect(l.cardW).toBeGreaterThanOrEqual(104);
    expect(l.cardW).toBeLessThanOrEqual(168);
    // the repair links are edges too (failed node -> its two repairs)
    expect(l.edges.filter((e) => e.kind === "repair").map((e) => e.key).sort()).toEqual(["t1-discovery>t1-hermes", "t1-discovery>t4-fence"]);
    // verify waited on the failed node; its repairs replaced it, so the links come from them
    expect(l.edges.filter((e) => e.to === "t5-verify").map((e) => e.from).sort()).toEqual(["t1-hermes", "t2-status-update", "t3-doctor", "t4-fence"]);
    expect(l.edges.filter((e) => e.broken)).toEqual([]);
  });
  it("a node's size follows its role: leads tall, leaves compact, the closing verify a wider gate", () => {
    const small = fx("runs-bridge.json").runs.find((r: AgentRun) => r.id.endsWith("/codex-coexist")) as AgentRun;
    const heights = { lead: 80, normal: 70, leaf: 56, gate: 72 };
    const l = layoutRun(small.nodes, { ...OPTS, cardH: 70, heights });
    const k = (id: string) => l.size.get(id)!;
    expect([k("t1-discovery").kind, k("t2-status-update").kind, k("t3-doctor").kind, k("t1-hermes").kind, k("t5-verify").kind]).toEqual([
      "lead",
      "lead",
      "normal",
      "normal",
      "gate",
    ]);
    expect(k("t1-discovery").h).toBeGreaterThan(k("t3-doctor").h);
    expect(k("t5-verify").w).toBeGreaterThan(k("t3-doctor").w);
    expect(k("t1-discovery").unblocks).toBe(2);
    // a part nothing waits on is a compact leaf
    const n0 = (id: string, deps: string[] = []) => ({ id, label: id, deps, layer: deps.length ? 1 : 0, state: "done" as const });
    const ll = layoutRun([n0("a"), n0("b", ["a"]), n0("c", ["a"])], { ...OPTS, cardH: 70, heights });
    expect(ll.size.get("b")!.kind).toBe("leaf");
    expect(ll.size.get("b")!.h).toBeLessThan(ll.size.get("a")!.h);
    // the role from the dag wins over the shape
    const n = (id: string, role?: string) => ({ id, label: id, deps: [], layer: 0, state: "done" as const, role });
    expect(sizeKind(n("a", "plan"), 0)).toBe("lead");
    expect(sizeKind(n("b", "verify"), 0)).toBe("gate");
    expect(sizeKind(n("c", "verify"), 1)).toBe("normal");
  });
  it("lays out 40 nodes in well under 50 ms", () => {
    layoutRun(big.nodes, OPTS);
    const t = performance.now();
    for (let i = 0; i < 10; i++) layoutRun(big.nodes, OPTS);
    expect((performance.now() - t) / 10).toBeLessThan(50);
  });
  it("column labels name what a column does", () => {
    const n = (id: string, label: string, extra = {}) => ({ id, label, deps: [], layer: 0, state: "done" as const, ...extra });
    expect(columnLabel([n("t5-verify", "Independent verify")], 2)).toBe("Verify · 1");
    expect(columnLabel([n("a", "Media in"), n("b", "Runs tab"), n("c", "Usage")], 0)).toBe("Build · 3");
    expect(columnLabel([n("r", "fix", { repairOf: "x" }), n("s", "fix 2", { repairOf: "x" })], 1)).toBe("Repair · 2");
  });
  it("two labels with the same start put what differs first", () => {
    const m = distinctLabels([
      { id: "a", label: "Codex skill discovery reads .agents/skills" },
      { id: "b", label: "Codex skill discovery reads .agents/skills (Hermes)" },
      { id: "c", label: "Something else" },
    ]);
    expect([m.get("a"), m.get("b"), m.get("c")]).toEqual([
      "Codex skill discovery reads .agents/skills",
      "Hermes: Codex skill discovery reads .agents/skills",
      "Something else",
    ]);
  });
  it("countCrossings counts a swapped pair once", () => {
    const layerOf = new Map([
      ["a", 0],
      ["b", 0],
      ["c", 1],
      ["d", 1],
    ]);
    const links = [
      { from: "a", to: "d" },
      { from: "b", to: "c" },
    ];
    expect(countCrossings([["a", "b"], ["c", "d"]], links, layerOf)).toBe(1);
    expect(countCrossings([["a", "b"], ["d", "c"]], links, layerOf)).toBe(0);
  });
});

describe("panel ports and layer names", () => {
  it("with ports, edges into one card meet it at their own points, top to bottom in their sources' order", () => {
    const l = layoutRun(big.nodes, { ...OPTS, ports: true });
    const by = new Map<string, typeof l.edges>();
    for (const e of l.edges) (by.get(e.to) ?? by.set(e.to, []).get(e.to)!).push(e);
    let checked = 0;
    for (const [to, es] of by) {
      if (es.length < 2) continue;
      const p = l.pos.get(to)!;
      const h = l.size.get(to)!.h;
      const ys = es.map((e) => e.y2);
      expect(new Set(ys).size).toBe(es.length);
      for (const y of ys) expect(y > p.y && y < p.y + h).toBe(true);
      const srcY = es.map((e) => l.pos.get(e.from)!.y);
      const order = [...es.keys()].sort((a, b) => ys[a] - ys[b]);
      for (let i = 1; i < order.length; i++) expect(srcY[order[i]]).toBeGreaterThanOrEqual(srcY[order[i - 1]]);
      checked++;
    }
    expect(checked).toBeGreaterThan(0);
    // without ports every edge still meets the middle
    for (const e of layoutRun(big.nodes, OPTS).edges) expect(e.y2).toBe(l.pos.get(e.to)!.y + l.size.get(e.to)!.h / 2);
  });
  it("one layer name for chips and columns: 'L4 · Verify'", () => {
    expect(layerName(3, "Verify · 1")).toBe("L4 · Verify");
    expect(layerName(0, "Plan + Build · 2")).toBe("L1 · Plan");
    expect(layerName(1, "Repair + Check")).toBe("L2 · Repair");
  });
});

describe("clampWords", () => {
  const m = (s: string) => s.length * 6; // a monospace stand-in: 6px a character
  it("wraps between words and ends with a whole word and an ellipsis", () => {
    expect(clampWords("Fence allows zsh heredocs and uv cache", 20 * 6, 2, m)).toBe("Fence allows zsh\nheredocs and uv…");
    expect(clampWords("Doctor check for the Codex pack", 20 * 6, 2, m)).toBe("Doctor check for the\nCodex pack");
  });
  it("never cuts a word unless one word is wider than a line", () => {
    const out = clampWords("Honest pack status + omh update refresh", 12 * 6, 2, m);
    for (const w of out.replace(/…/g, "").split(/\s+/).filter(Boolean)) expect("Honest pack status + omh update refresh".split(" ")).toContain(w);
    expect(clampWords("supercalifragilistic word", 8 * 6, 1, m)).toBe("superca…");
    // a token wider than a line breaks inside itself, after a "/" when one fits; no line is wider than the card
    const slash = clampWords("Claude/Codex/pi session runs", 13 * 6, 3, m);
    expect(slash).toBe("Claude/Codex/\npi session\nruns");
    for (const l of clampWords("abcdefghijklmnopqrstuvwxyz end", 8 * 6, 3, m).split("\n")) expect(m(l)).toBeLessThanOrEqual(8 * 6);
  });
});
