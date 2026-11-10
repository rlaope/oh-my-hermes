import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { fromDag, type AgentRun, type RunNode } from "../lib/runs";
import {
  BOX_INNER_MAX,
  BOX_MIN,
  boxLines,
  boxText,
  cells,
  elbowNet,
  factLines,
  factsOf,
  fit,
  frontiers,
  GEOMETRY,
  layoutBoxes,
  PAD,
  PARENTS_MIN,
  statusOf,
  wrapText,
  type BoxLayout,
  type Rect,
} from "./boxView";
import { modelName } from "./format";

const node = (id: string, deps: string[] = [], extra: Partial<RunNode> = {}): RunNode => ({ id, label: id, deps, layer: 0, state: "done", attempts: [], ...extra });
const dag = (nodes: RunNode[]): Pick<AgentRun, "kind" | "nodes"> => ({ kind: "dag", nodes });
const M = { cw: 7, line: 18 };
const fixture = (name: string) => JSON.parse(readFileSync(new URL(`../lib/__fixtures__/${name}`, import.meta.url), "utf-8"));

/** The TUI's own sample (docs/CODING-OBSERVABILITY.md): one node, three that wait on it, one that waits on those. */
const sample = () =>
  dag([
    node("api", [], { label: "Export API", route: "quick", model: "z-ai/glm-5.3-flash", effort: "low", started: 0, ended: 12 }),
    node("button", ["api"], { label: "Export button", route: "unspecified-high", model: "claude-opus-5-5", effort: "high", state: "running", started: 100, attempts: [{ n: 1, outcome: "open" }] }),
    node("docs", ["api"], { label: "Export docs", route: "writing", state: "running", attempts: [{ n: 1, outcome: "open" }] }),
    node("cli", ["api"], { label: "Export CLI flag", route: "quick", model: "glm-5.3-flash", effort: "low", state: "failed", started: 100, ended: 108, attempts: [{ n: 1, outcome: "failed" }] }),
    node("verify", ["button", "docs", "cli"], { label: "Verify export", route: "unspecified-high", state: "waiting" }),
  ]);

// ---- the drawing as straight pieces: what the tests below measure ----

interface Seg {
  net: string;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}
/** Every line of a layout as upright and level pieces. A rounded corner counts as its two legs. */
function pieces(lines: BoxLayout["lines"]): Seg[] {
  const out: Seg[] = [];
  for (const l of lines) {
    let [x, y] = [0, 0];
    const to = (nx: number, ny: number) => {
      if (nx !== x || ny !== y) out.push({ net: l.net, x1: Math.min(x, nx), y1: Math.min(y, ny), x2: Math.max(x, nx), y2: Math.max(y, ny) });
      [x, y] = [nx, ny];
    };
    for (const m of l.d.matchAll(/([MVHQ])([^MVHQ]*)/g)) {
      const n = (m[2].match(/-?\d+(\.\d+)?/g) ?? []).map(Number);
      if (m[1] === "M") [x, y] = n;
      else if (m[1] === "V") to(x, n[0]);
      else if (m[1] === "H") to(n[0], y);
      else {
        to(n[0], n[1]);
        to(n[2], n[3]);
      }
    }
  }
  return out;
}
const upright = (s: Seg) => s.x1 === s.x2;
/** Two pieces of one net meet: an end of one lies on the other, or they are the two sides of a gap a line leaves
 *  where it passes over another net's bus. */
function meet(a: Seg, b: Seg): boolean {
  const on = (px: number, py: number, s: Seg) => px >= s.x1 - 0.6 && px <= s.x2 + 0.6 && py >= s.y1 - 0.6 && py <= s.y2 + 0.6;
  if (on(a.x1, a.y1, b) || on(a.x2, a.y2, b) || on(b.x1, b.y1, a) || on(b.x2, b.y2, a)) return true;
  if (!upright(a) || !upright(b) || Math.abs(a.x1 - b.x1) > 0.1) return false;
  const gap = Math.max(a.y1, b.y1) - Math.min(a.y2, b.y2);
  return gap > 0 && gap <= 2 * GEOMETRY.hop + 0.1;
}
/** What is wrong with a drawing, as sentences; [] when every edge is a connected line that crosses no box. */
function faults(lay: BoxLayout): string[] {
  const out: string[] = [];
  const all = pieces(lay.lines);
  for (const net of lay.nets) {
    const mine = all.filter((s) => s.net === net.key);
    // one tree: every piece reaches every other
    const group = mine.map((_, i) => i);
    const find = (i: number): number => (group[i] === i ? i : (group[i] = find(group[i])));
    mine.forEach((a, i) => mine.forEach((b, j) => i < j && meet(a, b) && (group[find(i)] = find(j))));
    if (new Set(mine.map((_, i) => find(i))).size !== 1) out.push(`${net.key}: its lines are not one connected tree`);
    for (const p of net.parents) {
      const b = lay.at.get(p)!;
      if (!mine.some((s) => upright(s) && Math.abs(s.x1 - (b.x + b.w / 2)) <= 1 && Math.abs(s.y1 - (b.y + b.h)) < 0.6)) out.push(`${net.key}: no line leaves the bottom middle of ${p}`);
    }
    for (const c of net.children) {
      const b = lay.at.get(c)!;
      const head = lay.heads.find((h) => h.net === net.key && h.to === c);
      if (!head || head.y !== b.y || head.x <= b.x || head.x >= b.x + b.w) out.push(`${net.key}: no arrowhead on the top of ${c}`);
      else if (!mine.some((s) => upright(s) && Math.abs(s.x1 - head.x) < 0.1 && Math.abs(s.y2 - (b.y - GEOMETRY.arrow)) < 0.6)) out.push(`${net.key}: no line ends in the arrowhead of ${c}`);
    }
  }
  for (const s of all) {
    for (const b of lay.boxes) if (s.x2 > b.x + 0.5 && s.x1 < b.x + b.w - 0.5 && s.y2 > b.y + 0.5 && s.y1 < b.y + b.h - 0.5) out.push(`${s.net}: a line runs through the box of ${b.id}`);
    if (s.x1 < 0 || s.x2 > lay.w || s.y1 < 0 || s.y2 > lay.h) out.push(`${s.net}: a line leaves the drawing`);
  }
  all.forEach((a, i) =>
    all.forEach((b, j) => {
      if (i >= j || a.net === b.net) return;
      // two nets never share a stretch of line, and where they cross the upright one leaves a gap
      if (upright(a) && upright(b) && Math.abs(a.x1 - b.x1) < 1 && Math.min(a.y2, b.y2) - Math.max(a.y1, b.y1) > 1) out.push(`${a.net} and ${b.net} share an upright stretch at x=${a.x1}`);
      if (!upright(a) && !upright(b) && Math.abs(a.y1 - b.y1) < 1 && Math.min(a.x2, b.x2) - Math.max(a.x1, b.x1) > 1) out.push(`${a.net} and ${b.net} share a level stretch at y=${a.y1}`);
      const [v, h] = upright(a) ? [a, b] : [b, a];
      if (upright(v) && !upright(h) && h.x1 < v.x1 - 0.5 && v.x1 < h.x2 + 0.5 && v.y1 < h.y1 - 0.5 && h.y1 < v.y2 - 0.5 && h.x2 - h.x1 > GEOMETRY.r) out.push(`${v.net} crosses the bus of ${h.net} at ${v.x1},${h.y1} without a gap`);
    }),
  );
  return [...new Set(out)];
}
const edgesOf = (lay: BoxLayout) => lay.shape.edges.map((e) => `${e.from}>${e.to}`).sort();

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

  it("wraps a title between words onto two lines, and ends in … only when it is longer still", () => {
    expect(wrapText("Short title", 30)).toEqual(["Short title"]);
    expect(wrapText("Codex skill discovery reads .agents/skills", 22)).toEqual(["Codex skill discovery", "reads .agents/skills"]);
    // never cut in its middle: the start is whole, the end is what goes
    expect(wrapText("Codex skill discovery reads .agents/skills (Hermes)", 22)).toEqual(["Codex skill discovery", "reads .agents/skills…"]);
    expect(wrapText("one two three four five six seven", 10, 3)).toEqual(["one two", "three four", "five six…"]);
    expect(wrapText("one two three four five six", 9, 3)).toEqual(["one two", "three", "four fiv…"]); // the … has to fit too
    for (const w of [8, 14, 17, 22, 40]) for (const l of wrapText("Runs model + dag adapter + Runs tab, and the rest of a long title", w)) expect(cells(l)).toBeLessThanOrEqual(w);
    expect(wrapText("", 10)).toEqual([""]);
  });

  it("breaks a word wider than a line after a separator of its own, else where the line ends", () => {
    expect(wrapText("Claude/Codex/pi/omp/grok session runs", 18)).toEqual(["Claude/Codex/pi/", "omp/grok session…"]);
    expect(wrapText("Supercalifragilistic", 10)).toEqual(["Supercalif", "ragilistic"]);
    expect(wrapText("게이트웨이로그를읽는다", 8)).toEqual(["게이트웨", "이로그…"]);
  });

  it("names a model as people say it", () => {
    expect(modelName("claude-opus-5-5")).toBe("Opus 5.5");
    expect(modelName("anthropic/claude-haiku-5")).toBe("Haiku 5");
    expect(modelName("gpt-5.5")).toBe("GPT-5.5");
    expect(modelName("gpt-6-astra")).toBe("GPT-6 Astra");
    expect(modelName("z-ai/glm-5.3-flash")).toBe("glm-5.3-flash");
    expect(modelName("Opus 5.5")).toBe("Opus 5.5");
    expect(modelName("gpt-5.5-codex")).toBe("GPT-5.5 Codex");
    expect(modelName("claude-opus-5-5-thinking")).toBe("Opus 5.5 Thinking");
  });

  it("drops what a provider puts around a model's id: a date, a context tag, an effort, a revision", () => {
    expect(modelName("claude-sonnet-4-20250514")).toBe("Sonnet 4");
    expect(modelName("claude-haiku-5-20261001")).toBe("Haiku 5");
    expect(modelName("gpt-5.5-2026-08-01")).toBe("GPT-5.5");
    expect(modelName("claude-opus-5-5[1m]")).toBe("Opus 5.5");
    expect(modelName("claude-opus-5-5:high")).toBe("Opus 5.5");
    expect(modelName("us.anthropic.claude-opus-5-5-v1:0")).toBe("Opus 5.5");
    // an id of another shape keeps everything, its tag too
    expect(modelName("llama3:8b")).toBe("llama3:8b");
    expect(modelName("o5-mini")).toBe("o5-mini");
  });
});

describe("what ran a node", () => {
  const bot = { model: "claude-haiku-5", provider: "anthropic" };

  it("is the Hermes mark, then the model, effort and category of the helper that ran it", () => {
    expect(factsOf(node("a", [], { model: "claude-opus-5-5", effort: "high", route: "visual-engineering" }), { kind: "dag" })).toEqual({ marks: ["hermes"], text: "Opus 5.5 · high · visual-engineering" });
    // not run yet: what its route resolves to
    expect(factsOf(node("a", [], { state: "waiting", category: "review", planned: { model: "claude-opus-5-5", provider: "anthropic", effort: "high" } }), { kind: "dag" }, bot).text).toBe("Opus 5.5 · high · review");
    // nothing recorded: the bot's own model, and no effort nobody chose
    expect(factsOf(node("a", [], { state: "waiting", route: "writing" }), { kind: "dag" }, bot)).toEqual({ marks: ["hermes"], text: "Haiku 5 · writing" });
    expect(factsOf(node("a", [], { state: "waiting" }), { kind: "dag" })).toEqual({ marks: ["hermes"], text: "" });
    // a lane handed to a CLI says the effort it reported, whichever way its model is known
    expect(factsOf(node("a", [], { executor: "codex", effort: "xhigh" }), { kind: "dag" }).text).toBe("Codex · xhigh");
  });

  it("hides a category OMH left unnamed, unless the plan names a better one", () => {
    expect(factsOf(node("a", [], { model: "gpt-5.5", effort: "low", route: "unspecified-high" }), { kind: "dag" }).text).toBe("GPT-5.5 · low");
    expect(factsOf(node("a", [], { model: "gpt-5.5", category: "unspecified-low" }), { kind: "dag" }).text).toBe("GPT-5.5");
    // it went out under an unnamed route, but the plan calls it deep
    expect(factsOf(node("a", [], { model: "gpt-5.5", route: "unspecified-high", category: "deep" }), { kind: "dag" }).text).toBe("GPT-5.5 · deep");
    // the route it went out under wins over the plan's
    expect(factsOf(node("a", [], { model: "gpt-5.5", route: "quick", category: "deep" }), { kind: "dag" }).text).toBe("GPT-5.5 · quick");
  });

  it("adds the mark of the agent CLI a lane was handed to, and names it", () => {
    expect(factsOf(node("a", [], { executor: "codex", route: "deep" }), { kind: "dag" }, bot)).toEqual({ marks: ["hermes", "codex"], text: "Codex · deep" });
    // once the lane reports the model it ran on, that is the name
    expect(factsOf(node("a", [], { executor: "claude", model: "claude-opus-5-5", effort: "high" }), { kind: "dag" })).toEqual({ marks: ["hermes", "claude"], text: "Opus 5.5 · high" });
  });

  it("gives a CLI session's own sub-runs that CLI's mark alone, never a model's", () => {
    expect(factsOf(node("a", [], { model: "gpt-6-astra", effort: "low" }), { kind: "codex-sub", agent: "codex" })).toEqual({ marks: ["codex"], text: "GPT-6 Astra · low" });
    expect(factsOf(node("a", [], { model: "claude-opus-5-5" }), { kind: "claude-task", agent: "claude" }).marks).toEqual(["claude"]);
  });

  it("sets the facts on one line, or on two in a narrow box: whole parts first, a cut only at the end", () => {
    const f = { marks: ["hermes"], text: "Opus 5.5 · high · visual-engineering" };
    expect(factLines(f, 40)).toEqual(["Opus 5.5 · high · visual-engineering"]);
    expect(factLines(f, 21)).toEqual(["Opus 5.5 · high", "visual-engineering"]);
    expect(factLines(f, 14)).toEqual(["Opus 5.5", "high · visual…"]);
    expect(factLines({ marks: ["hermes", "codex"], text: "Codex" }, 14)).toEqual(["Codex"]);
    // a name wider than the room after two marks breaks between its words, never inside one
    expect(factLines({ marks: ["hermes", "codex"], text: "GPT-6 Astra · xhigh · visual-engineering" }, 14)).toEqual(["GPT-6", "Astra · xhigh…"]);
    expect(factLines({ marks: ["hermes", "codex"], text: "GPT-6 Astra" }, 14)).toEqual(["GPT-6", "Astra"]);
    expect(factLines({ marks: ["hermes"], text: "" }, 14)).toEqual([""]);
    for (const inner of [14, 18, 21, 28]) {
      const [first, second] = factLines(f, inner);
      expect(cells(first)).toBeLessThanOrEqual(inner - 3); // after the mark
      if (second !== undefined) expect(cells(second)).toBeLessThanOrEqual(inner);
    }
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

describe("a box's lines", () => {
  const run = sample();
  const shape = frontiers(run.nodes);
  const text = (id: string, inner = 28, now = 121) => boxText(run.nodes.find((n) => n.id === id)!, run, shape, inner, now);

  it("is the title, the marks and facts, glyph + status + time, and the first parent or Start node", () => {
    expect(text("api")).toMatchObject({ title: ["Export API"], marks: ["hermes"], facts: ["glm-5.3-flash · low", "quick"], hang: true, glyph: "✓", status: "Accepted 12s", parents: "Start node", tone: "done" });
    expect(text("button")).toMatchObject({ facts: ["Opus 5.5 · high"], glyph: "●", status: "Running 21s", parents: "← Export API", tone: "running" });
    expect(text("docs")).toMatchObject({ facts: ["writing"], glyph: "◌", status: "Handed out", tone: "out" });
    expect(text("cli")).toMatchObject({ glyph: "✗", status: "Failed 8s", tone: "failed" });
    expect(text("verify")).toMatchObject({ facts: [""], glyph: "○", status: "Waits on 3 lanes", parents: "← Export button +2", tone: "waiting" });
  });

  it("names the first parent whole where it fits and counts the rest", () => {
    const r = dag([node("p1", [], { label: "A parent with a rather long name" }), node("p2"), node("p3"), node("c", ["p1", "p2", "p3"], { state: "waiting" })]);
    const s = frontiers(r.nodes);
    expect(boxText(r.nodes[3], r, s, 40, 0).parents).toBe("← A parent with a rather long name +2");
    expect(boxText(r.nodes[3], r, s, 24, 0).parents).toBe("← A parent with a ra… +2");
    // a box too narrow leaves the line out; its lines are drawn, and Node details still name the parents
    expect(boxText(r.nodes[3], r, s, PARENTS_MIN - 1, 0).parents).toBeNull();
  });

  it("says a status a narrow box has no room for in a shorter form, before it cuts it", () => {
    const r = dag([node("a", [], { started: 0, ended: 3660 }), node("b", [], { state: "running" }), node("c", [], { state: "running" }), node("d", ["a", "b", "c"], { state: "waiting" })]);
    const s = frontiers(r.nodes);
    expect(boxText(r.nodes[0], r, s, 20, 0).status).toBe("Accepted 1h 1m");
    expect(boxText(r.nodes[0], r, s, 14, 0).status).toBe("Accepted 1h");
    expect(boxText(r.nodes[3], r, s, 20, 0).status).toBe("Waits on 2 lanes");
    expect(boxText(r.nodes[3], r, s, 14, 0).status).toBe("Waits on 2");
  });

  it("fits every line into the box, down to the narrowest", () => {
    for (const inner of [BOX_MIN - PAD, 18, 23, 28, BOX_INNER_MAX])
      for (const n of run.nodes) {
        const tx = boxText(n, run, shape, inner, 121);
        expect(tx.title.length).toBeLessThanOrEqual(2);
        for (const l of tx.title) expect(cells(l)).toBeLessThanOrEqual(inner);
        expect(cells(tx.facts[0]) + tx.marks.length * 3).toBeLessThanOrEqual(inner);
        if (tx.facts[1] !== undefined) expect(cells(tx.facts[1]) + (tx.hang ? tx.marks.length * 3 : 0)).toBeLessThanOrEqual(inner);
        expect(2 + cells(tx.status + tx.after)).toBeLessThanOrEqual(inner);
        if (tx.parents !== null) expect(cells(tx.parents)).toBeLessThanOrEqual(inner);
        expect(boxLines(n, run, shape, inner)).toBe(tx.title.length + tx.facts.length + 1 + (tx.parents === null ? 0 : 1));
      }
  });

  it("shows a token count whole or not at all, and marks a repair with ↻", () => {
    const r = dag([node("a", [], { state: "failed", started: 0, ended: 8, tokens: 1234 }), node("fix", [], { repairOf: "a", label: "Fix a", started: 10, ended: 20, tokens: 950 })]);
    const s = frontiers(r.nodes);
    expect(boxText(r.nodes[1], r, s, 28, 0)).toMatchObject({ title: ["↻ Fix a"], status: "Accepted 10s", after: " · ↓950" });
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
  });

  it("keeps an edge another path already implies: it is a line like any other", () => {
    const s = frontiers([node("a"), node("b", ["a"]), node("c", ["a", "b"])]);
    expect(s.edges.map((e) => `${e.from}>${e.to}`)).toEqual(["a>b", "a>c", "b>c"]);
    expect(s.parents.get("c")).toEqual(["a", "b"]);
  });

  it("stands a node nothing leads to just above the first node that waits on it", () => {
    // three independent parts of different depth and a closing check: the check's edges all join neighbours
    const s = frontiers([node("t1"), node("t2"), node("t3"), node("t4", ["t1"]), node("verify", ["t1", "t2", "t3", "t4"])]);
    expect(s.rows).toEqual([["t1"], ["t2", "t3", "t4"], ["verify"]]);
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

  it("leaves only the edge that closes a loop out of the frontiers: a node below the loop stands under it", () => {
    // a and b wait on each other; c waits on a
    const s = frontiers([node("a", ["b"]), node("b", ["a"]), node("c", ["a"])]);
    expect(s.rows).toEqual([["a"], ["b", "c"]]);
    expect(s.edges.map((e) => `${e.from}>${e.to}`).sort()).toEqual(["a>b", "a>c", "b>a"]);
    // the walk starts at a node nothing leads to, so the loop is closed by its own last edge, not by listing order
    const t = frontiers([node("c", ["b"]), node("b", ["a", "c"]), node("a")]);
    expect(t.rows).toEqual([["a"], ["b"], ["c"]]);
  });

  it("moves a node with room below it down a frontier, when its own is wider than a row", () => {
    // four under p; d's only dependent stands two frontiers further down, so d can wait one
    const nodes = [node("p"), node("a", ["p"]), node("b", ["p"]), node("c", ["p"]), node("d", ["p"]), node("z1", ["a", "b", "c"]), node("z2", ["z1", "d"])];
    expect(frontiers(nodes).rows).toEqual([["p"], ["a", "b", "c", "d"], ["z1"], ["z2"]]);
    const narrow = frontiers(nodes, 3);
    expect(narrow.rows).toEqual([["p"], ["a", "b", "c"], ["d", "z1"], ["z2"]]);
    // never past the node that waits on it, and a node nothing waits on stays where it is ready
    for (const e of narrow.edges) expect(narrow.layer.get(e.to)!).toBeGreaterThan(narrow.layer.get(e.from)!);
    const leaves = [node("p"), node("a", ["p"]), node("b", ["p"]), node("c", ["p"]), node("d", ["p"])];
    expect(frontiers(leaves, 3).rows).toEqual([["p"], ["a", "b", "c", "d"]]);
  });
});

describe("the layout", () => {
  it("draws the TUI's sample at 100 columns: one frontier to a row, three boxes under one, every edge a line", () => {
    const lay = layoutBoxes(sample(), { cells: 100, metrics: M });
    expect(lay.perRow).toBe(3);
    expect(lay.w).toBe(100 * M.cw);
    expect(lay.boxes.map((b) => [b.id, b.row])).toEqual([["api", 0], ["button", 1], ["docs", 1], ["cli", 1], ["verify", 2]]);
    // the lone boxes stand over and under the middle one
    expect(lay.at.get("api")!.x).toBe(lay.at.get("docs")!.x);
    expect(lay.at.get("verify")!.x).toBe(lay.at.get("docs")!.x);
    expect(lay.nets.map((n) => [n.parents, n.children])).toEqual([
      [["api"], ["button", "docs", "cli"]],
      [["button", "docs", "cli"], ["verify"]],
    ]);
    expect([...lay.drawn].sort()).toEqual(edgesOf(lay));
    expect(faults(lay)).toEqual([]);
  });

  it("shrinks the boxes to keep a frontier on one row in the panel, rather than wrap it", () => {
    const lay = layoutBoxes(sample(), { cells: 60, metrics: M });
    expect(lay.perRow).toBe(3);
    expect(lay.inner).toBe(BOX_MIN - PAD);
    expect(new Set(["button", "docs", "cli"].map((id) => lay.at.get(id)!.y)).size).toBe(1);
    expect(lay.boxes.every((b) => b.w === lay.boxW && b.x >= 0 && b.x + b.w <= lay.w)).toBe(true);
    expect([...lay.drawn].sort()).toEqual(edgesOf(lay));
    expect(faults(lay)).toEqual([]);
  });

  it("makes every box of a row as tall as its longest, and a narrow box leaves its parents line out", () => {
    const run = dag([node("a", [], { label: "A title long enough to take two lines in any box" }), node("b"), node("c", ["a", "b"], { state: "waiting" })]);
    const wide = layoutBoxes(run, { cells: 100, metrics: M });
    expect(wide.at.get("a")!.h).toBe(wide.at.get("b")!.h);
    expect(wide.at.get("a")!.h).toBe(5 * M.line + 2 * GEOMETRY.padY + 2 * GEOMETRY.border); // title ×2, facts, status, parents
    const narrow = layoutBoxes(run, { cells: 44, metrics: M });
    expect(narrow.inner).toBeLessThan(PARENTS_MIN);
    expect(narrow.at.get("c")!.h).toBe(3 * M.line + 2 * GEOMETRY.padY + 2 * GEOMETRY.border); // title, facts, status
  });

  it("never draws a box wider than the TUI's widest, nor past the width", () => {
    const long = dag([node("a", [], { label: "A title that is far longer than any box is ever allowed to be drawn in this view" })]);
    expect(layoutBoxes(long, { cells: 200, metrics: M }).inner).toBe(BOX_INNER_MAX);
    expect(layoutBoxes(long, { cells: 40, metrics: M }).inner).toBe(36 - PAD);
  });

  it("runs an edge that skips a frontier down a lane beside the boxes it passes", () => {
    // d waits on b (two frontiers up) and on c
    const run = dag([node("a"), node("b", ["a"]), node("x", ["a"]), node("c", ["x"]), node("d", ["b", "c"]), node("e", ["d"])]);
    const lay = layoutBoxes(run, { cells: 120, metrics: M });
    expect(lay.shape.rows).toEqual([["a"], ["b", "x"], ["c"], ["d"], ["e"]]);
    expect([...lay.drawn].sort()).toEqual(["a>b", "a>x", "b>d", "c>d", "d>e", "x>c"]);
    expect(faults(lay)).toEqual([]);
    // b and c lead to d alone: one net, whose line passes c's row
    const net = lay.nets.find((n) => n.children.join() === "d")!;
    expect(net.parents).toEqual(["b", "c"]);
    const c = lay.at.get("c")!;
    const lane = pieces(lay.lines).filter((s) => s.net === net.key && upright(s) && s.y1 < c.y && s.y2 > c.y + c.h);
    expect(lane.length).toBeGreaterThan(0);
    for (const s of lane) expect(s.x1 < c.x || s.x1 > c.x + c.w).toBe(true);
  });

  it("draws an edge another path implies as its own line", () => {
    const lay = layoutBoxes(dag([node("a"), node("b", ["a"]), node("c", ["a", "b"])]), { cells: 100, metrics: M });
    expect([...lay.drawn].sort()).toEqual(["a>b", "a>c", "b>c"]);
    expect(faults(lay)).toEqual([]);
    // a leads to b and c, b to c alone: two nets, and c takes each at its own point
    expect(lay.nets.map((n) => [n.parents, n.children])).toEqual([
      [["a"], ["b", "c"]],
      [["b"], ["c"]],
    ]);
    expect(lay.heads.filter((h) => h.to === "c").length).toBe(2);
  });

  it("gives a child of two fans a point on its top for each", () => {
    const run = dag([node("p1"), node("p2"), node("c1", ["p1"]), node("c2", ["p1", "p2"]), node("c3", ["p2"])]);
    const lay = layoutBoxes(run, { cells: 120, metrics: M });
    expect(lay.nets.map((n) => [n.parents, n.children])).toEqual([
      [["p1"], ["c1", "c2"]],
      [["p2"], ["c2", "c3"]],
    ]);
    const [left, right] = lay.heads.filter((h) => h.to === "c2").sort((a, b) => a.x - b.x);
    expect(left.from).toEqual(["p1"]);
    expect(right.from).toEqual(["p2"]);
    expect(right.x - left.x).toBeGreaterThanOrEqual(6);
    expect(faults(lay)).toEqual([]);
  });

  it("gives two buses that would overlap between two rows a height each, and gaps where their lines cross", () => {
    // p1 leads to c1..c3 and p2 to c2..c4: the two buses share the stretch over c2 and c3
    const run = dag([node("p1"), node("p2"), node("c1", ["p1"]), node("c2", ["p1", "p2"]), node("c3", ["p1", "p2"]), node("c4", ["p2"])]);
    const lay = layoutBoxes(run, { cells: 150, metrics: M });
    expect([...lay.drawn].sort()).toEqual(edgesOf(lay));
    expect(faults(lay)).toEqual([]);
    const all = pieces(lay.lines);
    const level = new Set(all.filter((s) => !upright(s) && s.x2 - s.x1 > 2 * GEOMETRY.r).map((s) => s.y1));
    expect(level.size).toBe(2);
    // a line that passes over the other bus is in two pieces there
    const gaps = lay.nets.map((n) => all.filter((s) => s.net === n.key && upright(s)).length - n.parents.length - n.children.length);
    expect(gaps.reduce((a, b) => a + b, 0)).toBeGreaterThan(0);
  });

  it("draws every edge but the one that closes a loop, when the recorded edges loop", () => {
    const run = dag([node("a"), node("b", ["a", "c"]), node("c", ["b"])]);
    const lay = layoutBoxes(run, { cells: 120, metrics: M });
    expect(lay.shape.looped).toBe(true);
    expect(lay.shape.edges.map((e) => `${e.from}>${e.to}`).sort()).toEqual(["a>b", "b>c", "c>b"]);
    expect([...lay.drawn].sort()).toEqual(["a>b", "b>c"]);
    expect(faults(lay)).toEqual([]);
    // a node that only waits on a node of the loop keeps its line
    const below = layoutBoxes(dag([node("a", ["b"]), node("b", ["a"]), node("c", ["a"])]), { cells: 120, metrics: M });
    expect([...below.drawn].sort()).toEqual(["a>b", "a>c"]);
    expect(faults(below)).toEqual([]);
  });

  it("keeps a frontier that fits on one row, also when another frontier has to wrap", () => {
    // twelve start nodes with long titles, and seven nodes that wait on them: 150 cells hold seven boxes
    const starts = Array.from({ length: 12 }, (_, i) => node(`s${i}`, [], { label: `Start node ${i} with a rather long title` }));
    const next = Array.from({ length: 7 }, (_, i) => node(`n${i}`, [`s${i}`, `s${i + 5}`]));
    const lay = layoutBoxes(dag([...starts, ...next]), { cells: 150, metrics: M });
    expect(new Set(next.map((n) => lay.at.get(n.id)!.row)).size).toBe(1);
    expect(lay.perRow).toBe(7);
    // the twelve wrap into two even rows
    expect(lay.boxes.filter((b) => b.frontier === 0).map((b) => b.row)).toEqual([0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1]);
    expect([...lay.drawn].sort()).toEqual(edgesOf(lay));
    expect(lay.crowded).toBe(0);
    expect(faults(lay)).toEqual([]);
  });

  it("gives a dense run fewer boxes to a row rather than two lines one place: no fault at any width", () => {
    // seeded, so the same runs every time: 12 to 50 nodes, each waiting on some of the nodes before it. With the
    // margins alone a dozen of these keep lines that share a place (43 nodes and 231 edges at 60 cells, say)
    let seed = 1;
    const rnd = () => (seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648;
    for (let k = 0; k < 36; k++) {
      const n = 12 + Math.floor(rnd() * 39);
      const p = 0.05 + rnd() * 0.2;
      const nodes = Array.from({ length: n }, (_, i) => node(`n${i}`, Array.from({ length: i }, (_, j) => `n${j}`).filter(() => rnd() < p), { label: `Node ${i} of run ${k}` }));
      for (const width of [60, 64, 77]) {
        const lay = layoutBoxes(dag(nodes), { cells: width, metrics: M });
        const what = `run ${k} (${n} nodes) at ${width} cells`;
        expect(lay.boxes.length, what).toBe(n);
        expect(lay.crowded, what).toBe(0);
        expect([...lay.drawn].sort(), what).toEqual(edgesOf(lay));
        expect(faults(lay), what).toEqual([]);
      }
    }
  });

  it("keeps a line into a child clear of the lines that leave the row above it, however many there are", () => {
    // seeded runs with many start nodes, where every fifth node waits on half of the nodes before it: its top
    // edge takes many lines, right under the stubs of the row above (found by an independent check: a point that
    // stayed on another net's stub once the first six places beside it were taken)
    let seed = 7;
    const rnd = () => (seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648;
    const states: RunNode["state"][] = ["done", "running", "failed", "waiting", "done", "cancelled", "parked"];
    for (let k = 0; k < 30; k++) {
      const roots = 2 + Math.floor(rnd() * 14);
      const n = roots + 3 + Math.floor(rnd() * 30);
      const nodes: RunNode[] = [];
      for (let i = 0; i < n; i++) {
        const deps = i < roots ? [] : Array.from({ length: i }, (_, j) => `n${j}`).filter(() => rnd() < (i % 5 === 0 ? 0.5 : 0.12));
        nodes.push(node(`n${i}`, deps, { label: `Task ${i} with a fairly long title for wrapping`, state: states[Math.floor(rnd() * states.length)] }));
      }
      for (const capRows of [undefined, 8])
        for (const width of [56, 72]) {
          const lay = layoutBoxes(dag(nodes), { cells: width, metrics: M, capRows });
          const what = `run ${k} (${n} nodes) at ${width} cells${capRows ? ", capped" : ""}`;
          expect(lay.crowded, what).toBe(0);
          expect(faults(lay), what).toEqual([]);
        }
    }
  });

  it("wraps only a frontier too wide for the narrowest boxes, and still draws every edge", () => {
    // seven under one parent, one node waiting on all seven: 60 cells hold three boxes
    const mids = ["m1", "m2", "m3", "m4", "m5", "m6", "m7"];
    const run = dag([node("p"), ...mids.map((id) => node(id, ["p"])), node("z", mids, { state: "waiting" })]);
    const lay = layoutBoxes(run, { cells: 60, metrics: M });
    expect(lay.perRow).toBe(3);
    expect(lay.boxes.filter((b) => b.frontier === 1).map((b) => b.row)).toEqual([1, 1, 1, 2, 2, 3, 3]); // as even as they go
    expect([...lay.drawn].sort()).toEqual(edgesOf(lay));
    expect(lay.drawn.size).toBe(14);
    expect(faults(lay)).toEqual([]);
    // wide enough, the same run is one row of seven
    const wide = layoutBoxes(run, { cells: 150, metrics: M });
    expect(new Set(mids.map((id) => wide.at.get(id)!.row)).size).toBe(1);
    expect(faults(wide)).toEqual([]);
  });

  it("shows the first rows of a very long frontier, running then failed first, and how many more there are", () => {
    const nodes = Array.from({ length: 88 }, (_, i) => node(`s${i}`, [], { state: i >= 85 ? "running" : i === 40 ? "failed" : "done" }));
    const run: Pick<AgentRun, "kind" | "nodes"> = { kind: "codex-sub", nodes };
    const capped = layoutBoxes(run, { cells: 60, metrics: M, capRows: 8 });
    expect(capped.perRow).toBe(3);
    expect(capped.boxes.length).toBe(24);
    expect(capped.boxes.slice(0, 5).map((b) => b.id)).toEqual(["s85", "s86", "s87", "s40", "s0"]);
    expect(capped.more).toMatchObject([{ frontier: 0, hidden: 64, total: 88 }]);
    const all = layoutBoxes(run, { cells: 60, metrics: M, capRows: 8, opened: new Set([0]) });
    expect(all.boxes.length).toBe(88);
    expect(all.more).toMatchObject([{ hidden: 0, total: 88 }]); // "Show fewer"
    // the full view has no cap
    expect(layoutBoxes(run, { cells: 150, metrics: M }).boxes.length).toBe(88);
  });

  it("lays the real runs out with every edge a connected line that crosses no box, in the panel and the full view", () => {
    const runs: AgentRun[] = [
      fromDag(fixture("omher-v02.json"), "default"),
      fromDag(fixture("codex-coexist-live.json"), "kami"),
      fromDag(fixture("codex-coexist.json"), "kami"),
      fromDag(fixture("omh-dap.json"), "kami"),
      ...(fixture("runs-cli.json").runs as AgentRun[]),
      fixture("big-run.json") as AgentRun,
    ];
    for (const run of runs)
      for (const width of [60, 72, 150]) {
        const lay = layoutBoxes(run, { cells: width, metrics: M });
        const what = `${run.id} at ${width} cells`;
        expect(lay.boxes.length, what).toBe(run.nodes.length);
        expect(lay.w, what).toBeLessThanOrEqual(width * M.cw);
        for (const a of lay.boxes) {
          expect(a.x >= 0 && a.x + a.w <= lay.w, `${what}: ${a.id} inside the width`).toBe(true);
          for (const b of lay.boxes) if (a.id < b.id) expect(a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h, `${what}: ${a.id} over ${b.id}`).toBe(false);
        }
        if (!lay.shape.looped) expect([...lay.drawn].sort(), what).toEqual(edgesOf(lay));
        expect(lay.crowded, what).toBe(0);
        expect(faults(lay), what).toEqual([]);
      }
  });
});

describe("the lines", () => {
  const lay = layoutBoxes(sample(), { cells: 100, metrics: M });
  const rect = (id: string): Rect => lay.at.get(id)!;
  const nums = (d: string) => (d.match(/-?\d+(\.\d+)?/g) ?? []).map(Number);

  it("leaves each parent's bottom at its middle and ends with a head on each child's top", () => {
    const fan = lay.nets[0].key;
    const stub = lay.lines.find((l) => l.net === fan && l.from.length === 1 && l.to.length === 3)!;
    const [x, y] = nums(stub.d);
    expect(Math.abs(x - (rect("api").x + lay.boxW / 2))).toBeLessThanOrEqual(1);
    expect(y).toBe(rect("api").y + rect("api").h);
    expect(stub.tone).toBe("done");
    const heads = lay.heads.filter((h) => h.net === fan);
    expect(heads.map((h) => h.to)).toEqual(["button", "docs", "cli"]);
    for (const h of heads) {
      expect(h.y).toBe(rect(h.to).y);
      expect(Math.abs(h.x - (rect(h.to).x + lay.boxW / 2))).toBeLessThanOrEqual(1);
      expect(h.up).toBe(false);
    }
    // only the line into the running child carries the slow dash
    expect(lay.lines.filter((l) => l.net === fan && l.flow).map((l) => l.to)).toEqual([["button"], ["docs"]]);
    expect(heads.filter((h) => h.flow).map((h) => h.to)).toEqual(["button", "docs"]);
  });

  it("colours a line by its parent, and a line parents of different states share by none", () => {
    const join = lay.nets[1].key;
    expect(lay.lines.filter((l) => l.net === join && l.from.length === 1).map((l) => [l.from[0], l.tone])).toEqual([
      ["button", "running"],
      ["docs", "out"],
      ["cli", "failed"],
    ]);
    expect(lay.lines.find((l) => l.key === `${join}:bus`)!.tone).toBeNull();
    expect(lay.heads.filter((h) => h.net === join)).toMatchObject([{ to: "verify", y: rect("verify").y, tone: null }]);
    // one parent: its colour all the way, the head included
    expect(lay.heads.filter((h) => h.net === lay.nets[0].key).every((h) => h.tone === "done")).toBe(true);
  });

  it("draws one parent over one child as one straight line", () => {
    const l2 = layoutBoxes(dag([node("a"), node("b", ["a"])]), { cells: 100, metrics: M });
    expect(l2.lines).toHaveLength(1);
    const [x, y1, y2] = nums(l2.lines[0].d);
    expect(y1).toBe(l2.at.get("a")!.y + l2.at.get("a")!.h);
    expect(y2).toBe(l2.at.get("b")!.y - GEOMETRY.arrow);
    expect(Math.abs(x - (l2.at.get("a")!.x + l2.boxW / 2))).toBeLessThanOrEqual(1);
    expect(faults(l2)).toEqual([]);
  });

  it("follows a dragged box with one elbow an edge: the head points up into a child moved above its parents", () => {
    const tone = (id: string) => ({ api: "done", button: "running", docs: "out", cli: "failed", verify: "waiting" })[id]!;
    const moved = (id: string): Rect => (id === "verify" ? { ...rect(id), y: -300 } : rect(id));
    const join = elbowNet(lay.nets[1], moved, tone, () => false);
    expect(join.lines.map((l) => [l.from, l.to, l.tone])).toEqual([
      [["button"], ["verify"], "running"],
      [["docs"], ["verify"], "out"],
      [["cli"], ["verify"], "failed"],
    ]);
    expect(join.heads).toMatchObject([{ to: "verify", up: true, y: -300 + rect("verify").h }]);
    // left where the layout put it, the head points down into its top
    const still = elbowNet(lay.nets[1], rect, tone, (id) => id === "verify");
    expect(still.heads).toMatchObject([{ to: "verify", up: false, y: rect("verify").y, flow: true }]);
    // dragged between its parents, it takes a head on each side: none of its lines ends without one
    const between = (id: string): Rect => (id === "button" ? { ...rect(id), y: rect("verify").y + 400 } : rect(id));
    const split = elbowNet(lay.nets[1], between, tone, () => false);
    expect(split.heads.map((h) => [h.up, h.from, h.y, h.tone])).toEqual([
      [true, ["button"], rect("verify").y + rect("verify").h, "running"],
      [false, ["docs", "cli"], rect("verify").y, null],
    ]);
  });
});
