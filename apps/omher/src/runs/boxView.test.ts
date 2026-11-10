import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { fromDag, type AgentRun, type RunNode } from "../lib/runs";
import {
  BOX_MAX,
  BOX_MIN,
  BOX_OPEN,
  boxHeight,
  boxText,
  estimate,
  factLines,
  factsOf,
  frontiers,
  GEOMETRY,
  innerOf,
  layoutBoxes,
  movedLines,
  roundedPath,
  statusOf,
  titleLines,
  titleParts,
  type BoxLayout,
  type LayoutOpts,
  type Measure,
  type Rect,
} from "./boxView";
import { modelName } from "./format";

const G = GEOMETRY;
const node = (id: string, deps: string[] = [], extra: Partial<RunNode> = {}): RunNode => ({ id, label: id, deps, layer: 0, state: "done", attempts: [], ...extra });
const dag = (nodes: RunNode[]): Pick<AgentRun, "kind" | "nodes"> => ({ kind: "dag", nodes });
/** A measure that needs no font: 7px a character in a line of text, 8px in a title (twice that for a CJK one). */
const M: Measure = (text, font) => [...text].reduce((w, ch) => w + ((ch.codePointAt(0) ?? 0) >= 0x2e80 ? 2 : 1), 0) * (font === "title" ? 8 : 7);
const lay = (run: Parameters<typeof layoutBoxes>[0], width: number, o: Partial<LayoutOpts> = {}) => layoutBoxes(run, { width, measure: M, ...o });
const fixture = (name: string) => JSON.parse(readFileSync(new URL(`../lib/__fixtures__/${name}`, import.meta.url), "utf-8"));

/** The TUI's own sample (docs/CODING-OBSERVABILITY.md): one node, three that wait on it, one that waits on those. */
const sample = () =>
  dag([
    node("api", [], { label: "Export API", route: "quick", model: "z-ai/glm5.3-airx01", effort: "low", started: 0, ended: 12 }),
    node("button", ["api"], { label: "Export button", route: "unspecified-high", model: "claude-opus-5-5", effort: "high", state: "running", started: 100, attempts: [{ n: 1, outcome: "open" }] }),
    node("docs", ["api"], { label: "Export docs", route: "writing", state: "running", attempts: [{ n: 1, outcome: "open" }] }),
    node("cli", ["api"], { label: "Export CLI flag", route: "quick", model: "glm5.3-airx01", effort: "low", state: "failed", started: 100, ended: 108, attempts: [{ n: 1, outcome: "failed" }] }),
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
/** Every line of a layout as upright and level pieces. A rounded turn counts as its two legs. */
function pieces(lines: { net: string; d: string }[]): Seg[] {
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
 *  where it passes over another net's level stretch. */
function meet(a: Seg, b: Seg): boolean {
  const on = (px: number, py: number, s: Seg) => px >= s.x1 - 0.6 && px <= s.x2 + 0.6 && py >= s.y1 - 0.6 && py <= s.y2 + 0.6;
  if (on(a.x1, a.y1, b) || on(a.x2, a.y2, b) || on(b.x1, b.y1, a) || on(b.x2, b.y2, a)) return true;
  if (!upright(a) || !upright(b) || Math.abs(a.x1 - b.x1) > 0.1) return false;
  const gap = Math.max(a.y1, b.y1) - Math.min(a.y2, b.y2);
  return gap > 0 && gap <= 2 * G.hop + 0.1;
}
/** What is wrong with a drawing, as sentences; [] when every edge is a connected line that keeps clear of every
 *  box, no two nets share a stretch, every crossing has its gap, and no two arrowheads stand on each other. */
/** The steps aside in a layout's lines that are too short to turn twice in: each reads as a kink. With `ends`,
 *  only a line's first step (out of its parent) and its last (into its child): between two rows a dense run can
 *  leave a line no other place. */
function kinks(l: BoxLayout, ends = false): string[] {
  const out: string[] = [];
  for (const e of l.lines) {
    const turns = e.pts.filter((pt, i) => i === 0 || pt[0] !== e.pts[i - 1][0] || pt[1] !== e.pts[i - 1][1]); // a point said twice is one
    for (let i = 1; i < turns.length; i++) {
      if (turns[i][1] !== turns[i - 1][1] || Math.abs(turns[i][0] - turns[i - 1][0]) >= 2 * G.r) continue;
      if (!ends || i === 2 || i === turns.length - 2) out.push(`${e.from}>${e.to} steps ${Math.abs(turns[i][0] - turns[i - 1][0])}px aside at y=${turns[i][1]}`);
    }
  }
  return out;
}
/** A panel never stands its boxes in one column: a run so dense that lines still share a place at two boxes to a
 *  row keeps them so (a column of single boxes would be many screens long), and nothing else is wrong with it. */
function sharesOnlyAtTwoToARow(l: BoxLayout, what: string) {
  if (l.shared) expect(l.perRow, what).toBe(2);
  expect(faults(l).filter((f) => !(l.shared && f.includes(" share an upright stretch"))), what).toEqual([]);
}
function faults(l: BoxLayout): string[] {
  const out: string[] = [];
  // a path with a number that is not one (NaN, Infinity) passes every comparison below: say so first
  for (const e of l.lines) if (/NaN|Infinity|undefined/.test(e.d) || e.pts.some((pt) => !pt.every(Number.isFinite))) out.push(`${e.key}: a point of the line is not a number`);
  // the nets that end at one child come into it as one line: they share its arrowhead, and the level stretch and
  // the drop over that child (what two of them share lies below the row above it), nowhere else
  const channel = (id: string) => Math.max(0, ...l.boxes.filter((b) => b.row === l.at.get(id)!.row - 1).map((b) => b.y + b.h));
  // (worked out here from the nets and the rows, not read off the layout's heads: a net ends at a child when that
  // child is the only one in the net's last row)
  const lastRow = (n: { children: string[] }) => Math.max(...n.children.map((k) => l.at.get(k)!.row));
  const endOf = new Map(l.nets.map((n) => [n.key, n.children.filter((k) => l.at.get(k)!.row === lastRow(n))] as const).filter(([, last]) => last.length === 1).map(([key, last]) => [key, last[0]] as const));
  const joined = (a: Seg, b: Seg) => endOf.has(a.net) && endOf.get(a.net) === endOf.get(b.net) && (upright(a) ? Math.max(a.y1, b.y1) : a.y1) >= channel(endOf.get(a.net)!);
  for (const h of l.heads) if (h.nets.length > 1 && h.nets.some((key) => endOf.get(key) !== h.to)) out.push(`the arrowhead on ${h.to} joins a net that does not end there`);
  // the edges of a net lie on each other where they share a stretch: each piece once
  const all = [...new Map(pieces(l.lines).map((s) => [`${s.net} ${s.x1} ${s.y1} ${s.x2} ${s.y2}`, s])).values()];
  for (const net of l.nets) {
    const mine = all.filter((s) => s.net === net.key);
    // one tree: every piece reaches every other
    const group = mine.map((_, i) => i);
    const find = (i: number): number => (group[i] === i ? i : (group[i] = find(group[i])));
    mine.forEach((a, i) => mine.forEach((b, j) => i < j && meet(a, b) && (group[find(i)] = find(j))));
    if (new Set(mine.map((_, i) => find(i))).size !== 1) out.push(`${net.key}: its lines are not one connected tree`);
    for (const p of net.parents) {
      const b = l.at.get(p)!;
      // one way out of the parent's bottom: at its middle, or a step short of two turns beside it (over its lane)
      const leaves = new Set(mine.filter((s) => upright(s) && Math.abs(s.y1 - (b.y + b.h)) < 0.6 && s.x1 > b.x && s.x1 < b.x + b.w).map((s) => s.x1));
      if (leaves.size !== 1 || Math.abs([...leaves][0] - (b.x + b.w / 2)) >= 2 * G.r + 1) out.push(`${net.key}: the line does not leave the bottom of ${p} at one place, at its middle or right beside it (${[...leaves].join()})`);
      // one path an edge
      for (const c of net.children) if (l.lines.filter((e) => e.net === net.key && e.from === p && e.to === c).length !== 1) out.push(`${net.key}: ${p}>${c} is not one line`);
    }
    for (const c of net.children) {
      const b = l.at.get(c)!;
      const head = l.heads.find((h) => h.nets.includes(net.key) && h.to === c);
      if (!head || head.y !== b.y || head.x < b.x + G.portInset - 1 || head.x > b.x + b.w - G.portInset + 1) out.push(`${net.key}: no arrowhead on the top of ${c}, clear of its corners`);
      else if (!mine.some((s) => upright(s) && Math.abs(s.x1 - head.x) < 0.1 && Math.abs(s.y2 - (b.y - G.arrow)) < 0.6)) out.push(`${net.key}: no line ends in the arrowhead of ${c}`);
    }
  }
  for (const s of all) {
    for (const b of l.boxes) {
      if (s.x2 > b.x + 0.5 && s.x1 < b.x + b.w - 0.5 && s.y2 > b.y + 0.5 && s.y1 < b.y + b.h - 0.5) out.push(`${s.net}: a line runs through the box of ${b.id}`);
      // a line that passes a box keeps its distance: nearer than `keep` it reads as part of the outline, and a
      // space between two boxes of `pass` px or less has no room for that
      else if (upright(s) && Math.min(s.y2, b.y + b.h) - Math.max(s.y1, b.y) > 1 && Math.min(Math.abs(s.x1 - b.x), Math.abs(s.x1 - (b.x + b.w))) < G.keep - 0.6) out.push(`${s.net}: a line passes ${b.id} nearer than ${G.keep}px`);
    }
    if (s.x1 < 0 || s.x2 > l.w || s.y1 < 0 || s.y2 > l.h) out.push(`${s.net}: a line leaves the drawing`);
  }
  // two nets never share a stretch of line (the pieces at one x, or one y, among themselves)
  const ups = all.filter(upright);
  const levels = all.filter((s) => !upright(s)).sort((a, b) => a.y1 - b.y1);
  const shared = (pieces: Seg[], at: (s: Seg) => number, lo: (s: Seg) => number, hi: (s: Seg) => number, what: string) => {
    const by = new Map<number, Seg[]>();
    for (const s of pieces) for (const k of [Math.floor(at(s)), Math.floor(at(s)) + 1]) (by.get(k) ?? by.set(k, []).get(k)!).push(s);
    for (const group of by.values())
      group.forEach((a, i) =>
        group.forEach((b, j) => {
          if (i < j && a.net !== b.net && Math.abs(at(a) - at(b)) < 1 && Math.min(hi(a), hi(b)) - Math.max(lo(a), lo(b)) > 1 && !joined(a, b)) out.push(`${a.net} and ${b.net} share ${what}=${at(a)}`);
        }),
      );
  };
  shared(ups, (s) => s.x1, (s) => s.y1, (s) => s.y2, "an upright stretch at x");
  shared(levels, (s) => s.y1, (s) => s.x1, (s) => s.x2, "a level stretch at y");
  // where an upright line passes over another net's level stretch it leaves a gap: a crossing is not a join
  for (const v of ups) {
    let from = 0;
    for (let to = levels.length; from < to; ) {
      const mid = (from + to) >> 1;
      if (levels[mid].y1 <= v.y1 + 0.5) from = mid + 1;
      else to = mid;
    }
    for (let k = from; k < levels.length && levels[k].y1 < v.y2 - 0.5; k++) {
      const h = levels[k];
      if (h.net !== v.net && h.x1 < v.x1 - 0.5 && v.x1 < h.x2 - 0.5 && h.x2 - h.x1 > G.r) out.push(`${v.net} crosses the level stretch of ${h.net} at ${v.x1},${h.y1} without a gap`);
    }
  }
  // the arrowheads on one child stand apart: `portClear` for up to five of them (the narrowest box holds that
  // many, whatever comes down from the row above), and an arrowhead and two px however many there are. Only a
  // child the layout calls tight has them nearer, and it is called so only when its top edge cannot hold them:
  // each of its k lines an arrowhead apart, and 2 * lane more for every line the row above sends down over it
  for (const b of l.boxes) {
    const xs = l.heads.filter((h) => h.to === b.id).map((h) => h.x).sort((p, q) => p - q);
    const tight = l.tight.includes(b.id);
    const least = tight ? 0 : xs.length <= 5 ? G.portClear : G.arrowW + 2;
    for (let i = 1; i < xs.length; i++) if (xs[i] - xs[i - 1] < least) out.push(`two of the ${xs.length} arrowheads on ${b.id} are ${xs[i] - xs[i - 1]}px apart`);
    if (!tight) continue;
    const above = l.boxes.filter((p) => p.row === b.row - 1 && l.lines.some((e) => e.from === p.id) && p.x + p.w / 2 > b.x + G.portInset - G.lane && p.x + p.w / 2 < b.x + b.w - G.portInset + G.lane).length;
    if ((xs.length - 1) * (G.arrowW + 2) + above * 2 * G.lane <= b.w - 2 * G.portInset - 1) out.push(`${b.id} is called tight, with room for its ${xs.length} lines`);
  }
  return [...new Set(out)];
}
const edgesOf = (l: BoxLayout) => l.shape.edges.map((e) => `${e.from}>${e.to}`).sort();

describe("text", () => {
  it("estimates a width without a font: narrow, wide and capital letters differ, a CJK character is one em", () => {
    expect(estimate("iii", "text")).toBeLessThan(estimate("mmm", "text"));
    expect(estimate("abc", "text")).toBeLessThan(estimate("ABC", "text"));
    expect(estimate("계획", "text")).toBe(24);
    expect(estimate("Opus 5.5", "title")).toBeGreaterThan(estimate("Opus 5.5", "text"));
    expect(estimate("", "text")).toBe(0);
  });

  it("gives a title one line when it fits the box's text, else two; a repair's icon counts", () => {
    const n = node("a", [], { label: "Export button" }); // 13 characters: 104px in the test measure
    expect(titleLines(n, false, 104, M)).toBe(1);
    expect(titleLines(n, false, 103, M)).toBe(2);
    expect(titleLines(n, true, 104 + G.icon + G.iconGap, M)).toBe(1);
    expect(titleLines(n, true, 104 + G.icon + G.iconGap - 1, M)).toBe(2);
  });

  it("lets a title break after a / or a _ inside a long word, and nowhere else it would not already", () => {
    expect(titleParts("Claude/Codex/pi/omp/grok session runs")).toEqual(["Claude/", "Codex/", "pi/", "omp/", "grok session runs"]);
    expect(titleParts("test_home_isolation passes")).toEqual(["test_", "home_", "isolation passes"]);
    // a dot or a colon is no place to break (a version, a numbered part), and a separator before a space adds none
    expect(titleParts("omher v0.2: Part 1.1")).toEqual(["omher v0.2: Part 1.1"]);
    expect(titleParts("either / or, a__b, done/")).toEqual(["either / or, a__", "b, done/"]);
    expect(titleParts("")).toEqual([""]);
    // the parts are the title: nothing added, nothing lost
    for (const title of ["Claude/Codex/pi/omp/grok session runs", "a/b_c", "/x", "x/", "계획/計画"]) expect(titleParts(title).join("")).toBe(title);
  });

  it("names a model as people say it", () => {
    expect(modelName("claude-opus-5-5")).toBe("Opus 5.5");
    expect(modelName("anthropic/claude-haiku-5")).toBe("Haiku 5");
    expect(modelName("gpt-6.1-sol")).toBe("GPT-6.1 Sol");
    expect(modelName("gpt-6.1-terra")).toBe("GPT-6.1 Terra");
    expect(modelName("gpt-6-astra")).toBe("GPT-6 Astra");
    expect(modelName("gemini-3-pro")).toBe("Gemini 3 Pro");
    expect(modelName("google/gemini-2.5-flash")).toBe("Gemini 2.5 Flash");
    expect(modelName("Opus 5.5")).toBe("Opus 5.5");
    expect(modelName("gpt-6.1-sol-codex")).toBe("GPT-6.1 Sol Codex");
    expect(modelName("claude-opus-5-5-thinking")).toBe("Opus 5.5 Thinking");
  });

  it("names the open models of a demo plan: GLM, Kimi and DeepSeek, without the provider or the speed tier", () => {
    expect(modelName("glm-5.3-ultrafast")).toBe("GLM-5.3");
    expect(modelName("z-ai/glm-5.3-ultrafast")).toBe("GLM-5.3");
    expect(modelName("z-ai/glm-5.3-flash")).toBe("GLM-5.3");
    expect(modelName("glm-5.3")).toBe("GLM-5.3");
    expect(modelName("kimi-k3-ultrafast")).toBe("Kimi K3");
    expect(modelName("moonshotai/kimi-k3")).toBe("Kimi K3");
    expect(modelName("kimi-k3.1-pro")).toBe("Kimi K3.1 Pro");
    expect(modelName("deepseek/deepseek-v4.1-flash-ultrafast")).toBe("DeepSeek V4.1");
    expect(modelName("deepseek-v4.1")).toBe("DeepSeek V4.1");
    expect(modelName("deepseek-v4.1-reasoner")).toBe("DeepSeek V4.1 Reasoner");
    // a tier is dropped only after a model name: a Gemini Flash is a model, not a tier
    expect(modelName("gemini-2.5-flash")).toBe("Gemini 2.5 Flash");
  });

  it("drops what a provider puts around a model's id: a date, a context tag, an effort, a revision", () => {
    expect(modelName("claude-sonnet-4-20250514")).toBe("Sonnet 4");
    expect(modelName("claude-haiku-5-20261001")).toBe("Haiku 5");
    expect(modelName("gpt-6.1-sol-2026-10-01")).toBe("GPT-6.1 Sol");
    expect(modelName("claude-opus-5-5[1m]")).toBe("Opus 5.5");
    expect(modelName("claude-opus-5-5:high")).toBe("Opus 5.5");
    expect(modelName("us.anthropic.claude-opus-5-5-v1:0")).toBe("Opus 5.5");
    // an id of another shape keeps everything, its tag too
    expect(modelName("llama3:8b")).toBe("llama3:8b");
    expect(modelName("o5-mini")).toBe("o5-mini");
  });

  it("rounds a line's turns with the radius, or as much of it as the stretches at the turn leave", () => {
    // down 40, right 100, down 40: two turns of 8
    expect(roundedPath([[10, 0], [10, 40], [110, 40], [110, 80]])).toBe("M10,0 V32 Q10,40 18,40 H102 Q110,40 110,48 V80");
    // a jog of 6px between two turns: each takes half of it
    expect(roundedPath([[10, 0], [10, 40], [16, 40], [16, 80]])).toBe("M10,0 V37 Q10,40 13,40 Q16,40 16,43 V80");
    // a point repeated, or in the middle of a straight stretch, is no turn
    expect(roundedPath([[10, 0], [10, 40], [10, 40], [10, 80]])).toBe("M10,0 V80");
    expect(roundedPath([[10, 0], [10, 40], [50, 40], [90, 40], [90, 20]])).toBe("M10,0 V32 Q10,40 18,40 H82 Q90,40 90,32 V20");
    // nothing to draw
    expect(roundedPath([])).toBe("");
    expect(roundedPath([[3, 4]])).toBe("M3,4");
    expect(roundedPath([[3, 4], [3, 4]])).toBe("M3,4");
  });

  it("leaves a gap in an upright stretch where it passes over a level stretch, going down or up", () => {
    const at = (ys: number[]) => (_x: number, lo: number, hi: number) => ys.filter((y) => y > lo && y < hi);
    // down past y=30 and y=50: `hop` px open on each side of each
    expect(roundedPath([[10, 0], [10, 80]], G.r, at([50, 30]))).toBe(`M10,0 V${30 - G.hop} M10,${30 + G.hop} V${50 - G.hop} M10,${50 + G.hop} V80`);
    // up: the same gaps, met in the other order
    expect(roundedPath([[10, 80], [10, 0]], G.r, at([30, 50]))).toBe(`M10,80 V${50 + G.hop} M10,${50 - G.hop} V${30 + G.hop} M10,${30 - G.hop} V0`);
    // two crossings nearer than two gaps apart leave one gap over both: no stub of line is drawn between them
    expect(roundedPath([[10, 0], [10, 200]], G.r, () => [100, 100 + G.hop + 1])).toBe(`M10,0 V${100 - G.hop} M10,${100 + 2 * G.hop + 1} V200`);
    // a level stretch has none, and a gap is asked for the straight part of a stretch only, between its turns
    const seen: number[][] = [];
    roundedPath([[10, 0], [10, 40], [110, 40], [110, 80]], G.r, (x, lo, hi) => (seen.push([x, lo, hi]), []));
    expect(seen).toEqual([
      [10, 0, 32],
      [110, 48, 80],
    ]);
  });

});

describe("what ran a node", () => {
  const bot = { model: "claude-haiku-5", provider: "anthropic" };
  const said = (n: RunNode, run: Parameters<typeof factsOf>[1] = { kind: "dag" }, b?: typeof bot) => {
    const f = factsOf(n, run, b);
    return [f.mark ? `${f.mark.kind}:${f.mark.id}` : null, f.text];
  };

  it("is the mark of the model's maker, then the model, effort and category of the helper that ran it", () => {
    expect(factsOf(node("a", [], { model: "claude-opus-5-5", effort: "high", route: "visual-engineering" }), { kind: "dag" })).toEqual({
      mark: { kind: "model", id: "claude", model: "claude-opus-5-5" },
      parts: ["Opus 5.5", "high", "visual-engineering"],
      core: 2,
      via: "",
      text: "Opus 5.5 · high · visual-engineering",
    });
    expect(said(node("a", [], { model: "gpt-6.1", effort: "low", route: "quick" }))).toEqual(["model:openai", "GPT-6.1 · low · quick"]);
    expect(said(node("a", [], { model: "gemini-3-pro", provider: "google", route: "deep" }))).toEqual(["model:gemini", "Gemini 3 Pro · deep"]);
    // not run yet: what its route resolves to
    expect(said(node("a", [], { state: "waiting", category: "review", planned: { model: "claude-opus-5-5", provider: "anthropic", effort: "high" } }), { kind: "dag" }, bot)).toEqual(["model:claude", "Opus 5.5 · high · review"]);
    // nothing recorded: the bot's own model, and no effort nobody chose
    expect(said(node("a", [], { state: "waiting", route: "writing" }), { kind: "dag" }, bot)).toEqual(["model:claude", "Haiku 5 · writing"]);
    // nothing known at all: no mark, no text
    expect(factsOf(node("a", [], { state: "waiting" }), { kind: "dag" })).toEqual({ mark: null, parts: [], core: 0, via: "", text: "" });
    // a model whose maker has no mark carries none (never a stand-in)
    expect(said(node("a", [], { model: "mystery-7b", provider: "og" }))).toEqual([null, "mystery-7b"]);
  });

  it("never carries the Hermes mark, and never two marks", () => {
    for (const n of [node("a", [], { model: "claude-opus-5-5" }), node("b", [], { executor: "codex" }), node("c", [], { executor: "claude", model: "claude-opus-5-5" }), node("d", [], { state: "waiting" })]) {
      const f = factsOf(n, { kind: "dag" }, bot);
      expect(f.mark?.id).not.toBe("hermes");
      expect(f.mark === null || typeof f.mark.id === "string").toBe(true); // one mark, or none
    }
  });

  it("shows the agent CLI's mark only while no model is known; then the model's, with the CLI after the facts", () => {
    expect(factsOf(node("a", [], { executor: "codex", route: "deep" }), { kind: "dag" }, bot)).toEqual({ mark: { kind: "agent", id: "codex" }, parts: ["Codex", "deep"], core: 1, via: "", text: "Codex · deep" });
    // once the lane reports the model it ran on, that is the name and the mark
    expect(factsOf(node("a", [], { executor: "claude", model: "claude-opus-5-5", effort: "high" }), { kind: "dag" })).toEqual({
      mark: { kind: "model", id: "claude", model: "claude-opus-5-5" },
      parts: ["Opus 5.5", "high"],
      core: 2,
      via: "via Claude",
      text: "Opus 5.5 · high · via Claude",
    });
    expect(said(node("a", [], { executor: "codex", model: "gpt-6.1", effort: "high", route: "deep" }))).toEqual(["model:openai", "GPT-6.1 · high · deep · via Codex"]);
  });

  it("still says the effort of a node whose category OMH left unnamed: Codex · high, GPT-6.1 · high", () => {
    // "unspecified-high" is no name to show, but it is how hard the node thinks
    expect(said(node("a", [], { executor: "codex", route: "unspecified-high" }))).toEqual(["agent:codex", "Codex · high"]);
    expect(said(node("a", [], { executor: "codex", category: "unspecified-low" }))).toEqual(["agent:codex", "Codex · low"]);
    expect(said(node("a", [], { model: "gpt-6.1", route: "unspecified-high" }))).toEqual(["model:openai", "GPT-6.1 · high"]);
    // an effort that was recorded wins over the category's
    expect(said(node("a", [], { model: "gpt-6.1", effort: "low", route: "unspecified-high" }))).toEqual(["model:openai", "GPT-6.1 · low"]);
    expect(said(node("a", [], { executor: "codex", effort: "xhigh", route: "unspecified-low" }))).toEqual(["agent:codex", "Codex · xhigh"]);
    expect(said(node("a", [], { state: "waiting", route: "unspecified-high", planned: { model: "claude-opus-5-5", effort: "medium" } }))).toEqual(["model:claude", "Opus 5.5 · medium"]);
    // it went out under an unnamed route, but the plan calls it deep: the name is the plan's, the effort the route's
    expect(said(node("a", [], { model: "gpt-6.1", route: "unspecified-high", category: "deep" }))).toEqual(["model:openai", "GPT-6.1 · high · deep"]);
    // the route it went out under wins over the plan's
    expect(said(node("a", [], { model: "gpt-6.1", route: "quick", category: "deep" }))).toEqual(["model:openai", "GPT-6.1 · quick"]);
    // only a word that is an effort: "unspecified" alone, or another tail, says nothing
    expect(said(node("a", [], { model: "gpt-6.1", route: "unspecified" }))).toEqual(["model:openai", "GPT-6.1"]);
    expect(said(node("a", [], { model: "gpt-6.1", route: "unspecified-misc" }))).toEqual(["model:openai", "GPT-6.1"]);
  });

  it("gives a CLI session's own sub-runs their model's mark, or the session's CLI when none is known: never the bot's model", () => {
    expect(factsOf(node("a", [], { model: "gpt-6-astra", effort: "low" }), { kind: "codex-sub", agent: "codex" }, bot)).toEqual({ mark: { kind: "model", id: "openai", model: "gpt-6-astra" }, parts: ["GPT-6 Astra", "low"], core: 2, via: "", text: "GPT-6 Astra · low" });
    expect(said(node("a", [], { model: "claude-opus-5-5" }), { kind: "claude-task", agent: "claude" }, bot)).toEqual(["model:claude", "Opus 5.5"]);
    expect(said(node("a"), { kind: "codex-sub", agent: "codex" }, bot)).toEqual(["agent:codex", "Codex"]);
  });

  it("sets the facts on one line where the model and its effort fit side by side: the category whole, cut with … or left out, never the effort", () => {
    const f = factsOf(node("a", [], { model: "claude-opus-5-5", effort: "high", route: "visual-engineering" }), { kind: "dag" });
    const lead = G.mark + G.markGap; // the 14px mark and the space after it
    // "Opus 5.5 · high · visual-engineering" is 36 characters: 252px
    expect(factLines(f, 252 + lead, M)).toEqual({ lines: ["Opus 5.5 · high · visual-engineering"], via: "", hang: true });
    // a px less: still one line, which the box cuts at its end ("…visual-engineerin…")
    expect(factLines(f, 252 + lead - 1, M)).toEqual({ lines: ["Opus 5.5 · high · visual-engineering"], via: "", hang: true });
    // "Opus 5.5 · high · visual…" (25 characters, 175px) is the least of the category that says anything: with
    // less room than that it is left out, not cut to a letter or two
    expect(factLines(f, 175 + lead, M).lines).toEqual(["Opus 5.5 · high · visual-engineering"]);
    expect(factLines(f, 175 + lead - 1, M).lines).toEqual(["Opus 5.5 · high"]);
    // a short category is whole or not there: "review" is never "rev…"
    const short = factsOf(node("a", [], { model: "claude-opus-5-5", effort: "high", route: "review" }), { kind: "dag" }); // 24 characters: 168px
    expect(factLines(short, 168 + lead, M).lines).toEqual(["Opus 5.5 · high · review"]);
    expect(factLines(short, 168 + lead - 1, M).lines).toEqual(["Opus 5.5 · high"]);
    // "Opus 5.5 · high" is 105px. A box too narrow for it after the mark says the model, and the rest under it:
    // the effort is never what gets cut
    expect(factLines(f, 105 + lead, M).lines).toEqual(["Opus 5.5 · high"]);
    expect(factLines(f, 104 + lead, M)).toEqual({ lines: ["Opus 5.5", "high · visual-engineering"], via: "", hang: false });
    const plain = factsOf(node("a", [], { model: "claude-opus-5-5", effort: "high" }), { kind: "dag" });
    expect(factLines(plain, 104 + lead, M)).toEqual({ lines: ["Opus 5.5", "high"], via: "", hang: true }); // "high" fits under the model's name
    // a name wider than the box is cut by the box, and its effort still stands under it
    const named = factsOf(node("a", [], { model: "qwen3-coder-480b-a35b", effort: "high", route: "deep" }), { kind: "dag" });
    expect(factLines(named, 75 + lead, M).lines).toEqual([named.parts[0], "high · deep"]);
    expect(factLines({ mark: null, parts: ["A model with a very long name", "deep"], core: 1, via: "", text: "" }, 100, M).lines).toEqual(["A model with a very long name"]);
    // the second line follows the first's rule: whole parts, then a cut where six letters still show, else nothing
    expect(factLines(f, 79 + lead, M).lines).toEqual(["Opus 5.5", "high · visual-engineering"]); // "high · visual…" is 98px: the box's width, from under the mark on
    expect(factLines(f, 78 + lead, M)).toEqual({ lines: ["Opus 5.5", "high"], via: "", hang: true });
    expect(factLines({ mark: null, parts: [], core: 0, via: "", text: "" }, 100, M)).toEqual({ lines: [], via: "", hang: true });
  });

  it("ends the facts in 'via Codex' only where everything before it fits whole; else the tooltip and the node's detail say it", () => {
    const f = factsOf(node("a", [], { executor: "codex", model: "gpt-6.1", effort: "high" }), { kind: "dag" }); // "GPT-6.1 · high" 98px, " · via Codex" 84px
    const lead = G.mark + G.markGap;
    expect(factLines(f, 98 + 84 + lead, M)).toEqual({ lines: ["GPT-6.1 · high"], via: "via Codex", hang: true });
    expect(factLines(f, 98 + 84 + lead - 1, M)).toEqual({ lines: ["GPT-6.1 · high"], via: "", hang: true }); // no second line for it
    // a category that does not fit: neither it nor what follows it is in the box
    const long = factsOf(node("a", [], { executor: "codex", model: "gpt-6.1", effort: "high", route: "visual-engineering" }), { kind: "dag" });
    expect(factLines(long, 130, M)).toEqual({ lines: ["GPT-6.1 · high"], via: "", hang: true });
    expect(long.text).toBe("GPT-6.1 · high · visual-engineering · via Codex");
    // on two lines (the box is too narrow for "GPT-6.1 · high" after the mark) it ends the second where the box holds it
    expect(factLines(f, 96 + lead, M)).toEqual({ lines: ["GPT-6.1", "high"], via: "via Codex", hang: false });
  });

  it("says no effort for 'none', takes the planned effort when none is recorded, and gives a model of no known maker the mark of the CLI that ran it", () => {
    expect(said(node("a", [], { model: "gpt-6.1", effort: "none" }))).toEqual(["model:openai", "GPT-6.1"]);
    expect(said(node("a", [], { model: "gpt-6.1", effort: "none", route: "unspecified-high" }))).toEqual(["model:openai", "GPT-6.1"]);
    expect(said(node("a", [], { model: "gpt-6.1", effort: "", planned: { model: "gpt-6.1", provider: "openai", effort: "low" } }))).toEqual(["model:openai", "GPT-6.1 · low"]);
    // one mark still, and no "via Codex" after it: the mark says it
    expect(factsOf(node("a", [], { model: "mystery-7b", executor: "codex", effort: "high" }), { kind: "dag" })).toMatchObject({ mark: { kind: "agent", id: "codex" }, parts: ["mystery-7b", "high"], via: "" });
    expect(factsOf(node("a", [], { model: "mystery-7b" }), { kind: "dag" }).mark).toBeNull();
  });
});

describe("a node's status line", () => {
  const run = sample();
  const by = (id: string) => run.nodes.find((n) => n.id === id)!;
  const line = (n: RunNode, r = run) => {
    const s = statusOf(n, r);
    return `${s.icon} ${s.word}`;
  };

  it("is an icon and a word: Done, Running, Handed out, Failed, Waiting on 3", () => {
    expect(line(by("api"))).toBe("check Done");
    expect(line(by("button"))).toBe("dot Running");
    expect(line(by("docs"))).toBe("dashed Handed out"); // out, and no helper has reported a model yet
    expect(line(by("cli"))).toBe("x Failed");
    expect(line(by("verify"))).toBe("ring Waiting on 3");
    expect(statusOf(by("docs"), run).timed).toBe(false);
  });

  it("counts only the nodes still open, and says Waiting when none is", () => {
    const r = dag([node("a"), node("b", [], { state: "running" }), node("c", ["a", "b"], { state: "waiting" }), node("d", ["a"], { state: "waiting" })]);
    expect(line(r.nodes[2], r)).toBe("ring Waiting on 1");
    expect(line(r.nodes[3], r)).toBe("ring Waiting");
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
    expect(line(b, r)).toBe("retry Retry");
    expect(line(c, r)).toBe("pause Parked");
    expect(line(d, r)).toBe("alert Blocked");
    expect(line(e, r)).toBe("off Cancelled");
  });

  it("says Done for a dag's node and a CLI's sub-run alike, and never Handed out outside a dag", () => {
    const r: Pick<AgentRun, "kind" | "nodes"> = { kind: "claude-task", nodes: [node("a"), node("b", [], { state: "running" })] };
    expect(line(r.nodes[0], r)).toBe("check Done");
    expect(line(r.nodes[1], r)).toBe("dot Running");
  });

  it("carries no glyph of the terminal's box view in any state", () => {
    const r = dag([node("a", [], { state: "failed" }), node("fix", ["a"], { repairOf: "a" }), node("b", ["fix"], { state: "waiting" }), node("c", [], { state: "running", model: "gpt-6.1" }), node("d", [], { state: "cancelled" }), node("e", [], { state: "parked" })]);
    const l = lay(r, 700);
    for (const n of r.nodes) {
      const tx = boxText(n, r, l, l.inner, 60, M);
      const text = [tx.title, ...tx.facts, tx.via, tx.word, tx.time, ...tx.extras].join(" ");
      expect(text).not.toMatch(/[✓✗●○◌↻←▽╎¦▪▼↓]/);
    }
  });
});

describe("a box's lines", () => {
  const run = sample();
  const l = lay(run, 900);
  const text = (id: string, inner = 240, now = 121) => boxText(run.nodes.find((n) => n.id === id)!, run, l, inner, now, M);

  it("is the title, the mark and facts, and an icon with the status and its time", () => {
    expect(text("api")).toMatchObject({ title: "Export API", titleLines: 1, repair: false, mark: { kind: "model", id: "zhipu" }, facts: ["glm5.3-airx01 · low · quick"], icon: "check", word: "Done", time: "12s", extras: [], tone: "done" });
    // its route is unnamed: the effort that was recorded stays, the category is not shown
    expect(text("button")).toMatchObject({ mark: { kind: "model", id: "claude" }, facts: ["Opus 5.5 · high"], icon: "dot", word: "Running", time: "21s", tone: "running" });
    expect(text("docs")).toMatchObject({ mark: null, facts: ["writing"], icon: "dashed", word: "Handed out", time: "", tone: "out" });
    expect(text("cli")).toMatchObject({ icon: "x", word: "Failed", time: "8s", tone: "failed" });
    // nothing ran it yet and no model is known, but its unnamed category still says the effort
    expect(text("verify")).toMatchObject({ mark: null, facts: ["high"], icon: "ring", word: "Waiting on 3", time: "", tone: "waiting" });
  });

  it("names no parent in the box: every edge is a line, and a line of its own for it only made some boxes taller", () => {
    // c waits on a (two rows up) and on b (the row above); a box is its title, its facts and its status, no more
    const r = dag([node("a", [], { label: "Theme toggle" }), node("b", ["a"]), node("c", ["a", "b"], { state: "waiting" }), node("d", ["c"], { state: "waiting" })]);
    const g = lay(r, 700);
    for (const n of r.nodes) expect(Object.keys(boxText(n, r, g, g.inner, 0, M)).sort()).toEqual(["extras", "facts", "factsText", "hang", "icon", "mark", "repair", "time", "title", "titleLines", "tone", "via", "word"]);
    // so c, whose line from a passes a row, is no taller than d, whose only parent stands right above it
    expect(g.at.get("c")!.h).toBe(g.at.get("d")!.h);
    // the edge itself is drawn, past b's row
    expect(g.lines.some((e) => e.from === "a" && e.to === "c")).toBe(true);
  });

  it("says a duration a narrow box has no room for by its first unit, then not at all, before the word is cut", () => {
    const r = dag([node("a", [], { started: 0, ended: 3660 })]);
    const g = lay(r, 700);
    const at = (inner: number) => boxText(r.nodes[0], r, g, inner, 0, M);
    const room = (chars: number) => G.icon + G.iconGap + chars * 7 + 0.5; // the icon, then that many characters
    expect([at(room(10)).word, at(room(10)).time]).toEqual(["Done", "1h 1m"]); // "Done 1h 1m"
    expect(at(room(9)).time).toBe("1h");
    expect(at(room(6)).time).toBe("");
    expect(at(room(6)).word).toBe("Done");
  });

  it("shows a note and a token count whole or not at all, and marks a repair with an icon, not a glyph", () => {
    const r = dag([node("a", [], { state: "failed", started: 0, ended: 8, tokens: 1234 }), node("fix", [], { repairOf: "a", label: "Fix a", started: 10, ended: 20, tokens: 950 })]);
    const g = lay(r, 700);
    const room = (chars: number) => G.icon + G.iconGap + chars * 7 + 0.5;
    expect(boxText(r.nodes[1], r, g, 240, 0, M)).toMatchObject({ title: "Fix a", repair: true, word: "Done", time: "10s", extras: ["950 tokens"] });
    expect(boxText(r.nodes[0], r, g, room(34), 0, M)).toMatchObject({ repair: false, word: "Failed", time: "8s", extras: ["repaired", "1.2k tokens"], tone: "repaired" });
    // "Failed 8s · repaired" is 20 characters, with the count 34
    expect(boxText(r.nodes[0], r, g, room(33), 0, M).extras).toEqual(["repaired"]); // the count no longer fits: left out, not cut
    // a character less than that: the duration gives way to the note, which says more ("Failed · repaired", 17)
    expect(boxText(r.nodes[0], r, g, room(19), 0, M)).toMatchObject({ time: "", extras: ["repaired"] });
    // and with no room for the note either, the duration is back
    expect(boxText(r.nodes[0], r, g, room(16), 0, M)).toMatchObject({ time: "8s", extras: [] });
  });

  it("is as tall as its lines: the title's one or two, the facts' none to two, and the status", () => {
    const h = (titles: number, facts: number) => boxHeight(titles, facts) - 2 * G.padY - 2 * G.border - G.titleGap;
    expect(h(1, 1)).toBe(3 * G.line);
    expect(h(2, 2)).toBe(5 * G.line);
    expect(h(1, 0)).toBe(2 * G.line);
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
  it("draws the sample at 900px: one frontier to a row, three boxes under one, every edge a line of its own", () => {
    const l = lay(sample(), 900);
    expect(l.perRow).toBe(3);
    expect(l.w).toBe(900);
    expect(l.boxes.map((b) => [b.id, b.row])).toEqual([["api", 0], ["button", 1], ["docs", 1], ["cli", 1], ["verify", 2]]);
    // the lone boxes stand over and under the middle one
    expect(l.at.get("api")!.x).toBe(l.at.get("docs")!.x);
    expect(l.at.get("verify")!.x).toBe(l.at.get("docs")!.x);
    expect(l.nets.map((n) => [n.parents, n.children])).toEqual([
      [["api"], ["button", "docs", "cli"]],
      [["button", "docs", "cli"], ["verify"]],
    ]);
    expect(l.lines.map((e) => `${e.from}>${e.to}`).sort()).toEqual(edgesOf(l));
    expect([...l.drawn].sort()).toEqual(edgesOf(l));
    expect(faults(l)).toEqual([]);
  });

  it("sizes a box in px: as wide as its widest line wants, between BOX_MIN and BOX_MAX, whatever the text's length in characters", () => {
    // the widest line is the title "Export CLI flag" (15 characters, 120px) and the facts "glm5.3-airx01 · low · quick" (27, 189px, after a 17px mark)
    const l = lay(sample(), 900);
    expect(l.boxW).toBe(189 + G.mark + G.markGap + 2 * G.padX + 2 * G.border);
    expect(l.inner).toBe(innerOf(l.boxW));
    // a wider measure, a wider box: nothing is counted in characters
    const wider = layoutBoxes(sample(), { width: 900, measure: (t, f) => M(t, f) * 1.1 });
    expect(wider.boxW).toBeGreaterThan(l.boxW);
    const long = dag([node("a", [], { label: "A title that is far longer than any box is ever allowed to be drawn in this view" })]);
    expect(lay(long, 1400).boxW).toBe(BOX_MAX);
    expect(lay(long, 200).boxW).toBe(200 - 2 * G.margin);
    expect(lay(dag([node("a", [], { label: "ab" })]), 900).boxW).toBe(BOX_MIN);
  });

  it("shrinks the boxes to keep a frontier on one row in the 460px panel, rather than wrap it", () => {
    const l = lay(sample(), 428);
    expect(l.perRow).toBe(3);
    expect(l.boxW).toBe(Math.floor((428 - 2 * G.margin - 2 * G.gap) / 3));
    expect(l.boxW).toBeGreaterThanOrEqual(BOX_MIN);
    expect(new Set(["button", "docs", "cli"].map((id) => l.at.get(id)!.y)).size).toBe(1);
    expect(l.boxes.every((b) => b.w === l.boxW && b.x >= 0 && b.x + b.w <= l.w)).toBe(true);
    expect([...l.drawn].sort()).toEqual(edgesOf(l));
    expect(faults(l)).toEqual([]);
  });

  it("makes every box of a row as tall as its longest: a two-line title, or two lines of facts", () => {
    const run = dag([
      node("a", [], { label: "A title long enough to take two lines in any box of this drawing, and more" }),
      node("b", [], { model: "claude-opus-5-5", effort: "high", route: "visual-engineering" }),
      node("c", ["a", "b"], { state: "waiting" }),
      node("d", ["c", "a"], { state: "waiting" }),
    ]);
    for (const width of [428, 528, 1136]) {
      const l = lay(run, width);
      for (const row of new Set(l.boxes.map((b) => b.row))) expect(new Set(l.boxes.filter((b) => b.row === row).map((b) => b.h)).size, `row ${row} at ${width}`).toBe(1);
      // a's title takes its two lines and no more; b's one
      expect(titleLines(run.nodes[0], false, l.inner, M)).toBe(2);
      expect(l.at.get("a")!.h).toBeGreaterThan(l.at.get("c")!.h);
      expect(l.at.get("a")!.h).toBe(l.at.get("b")!.h);
      // c and d hold the same lines, whatever their lines pass on the way
      expect(l.at.get("d")!.h).toBe(l.at.get("c")!.h);
    }
  });

  it("stands the boxes of a row further apart where they leave the room, up to gapMost", () => {
    const run = dag([node("a"), node("b"), node("c", ["a", "b"])]);
    const wide = lay(run, 1136);
    expect(wide.gap).toBe(G.gapMost);
    expect(wide.at.get("b")!.x - (wide.at.get("a")!.x + wide.boxW)).toBe(G.gapMost);
    const tight = lay(sample(), 428);
    expect(tight.gap).toBe(G.gap);
    expect(tight.at.get("docs")!.x - (tight.at.get("button")!.x + tight.boxW)).toBe(G.gap);
  });

  it("stands the boxes a lane apart in a run whose lines pass rows, where they stay comfortable: the line takes the space between two boxes, not the way round", () => {
    // three boxes fill a row; z waits on p, two rows up, and on the row between
    const mids = ["m1", "m2", "m3"];
    const run = dag([node("p"), ...mids.map((id) => node(id, ["p"], { label: `A part with a title of some length, ${id}` })), node("z", ["p", ...mids], { state: "waiting" })]);
    // the 560px panel: 28px between the boxes, which stay over BOX_OPEN
    const open = lay(run, 528);
    expect(open.passing).toBe(1);
    expect(open.boxW).toBe(Math.floor((528 - 2 * G.margin - 2 * G.gapLane) / 3));
    const spare = Math.floor((528 - 2 * G.margin - 3 * open.boxW) / 2); // 28, and the pixel the boxes' rounding leaves
    expect(open.gap).toBe(spare - ((open.boxW + spare) % 2)); // a box and a gap are an even number of px together
    expect(open.gap).toBeGreaterThanOrEqual(G.gapLane);
    expect(open.boxW).toBeGreaterThanOrEqual(BOX_OPEN);
    expect(open.perRow).toBe(3);
    const row = mids.map((id) => open.at.get(id)!);
    const passing = pieces(open.lines).filter((s) => upright(s) && s.y1 < row[0].y && s.y2 > row[0].y + row[0].h);
    expect(passing.length).toBeGreaterThan(0);
    for (const s of passing) {
      expect(s.x1 > row[0].x + row[0].w && s.x1 < row[2].x, `the passing line at x=${s.x1} stands between two boxes`).toBe(true);
      // in the middle of the space: 14px from the box on either side
      expect(Math.min(...row.map((b) => Math.min(Math.abs(s.x1 - b.x), Math.abs(s.x1 - (b.x + b.w)))))).toBeGreaterThanOrEqual(G.gapLane / 2 - 1);
    }
    expect(faults(open)).toEqual([]);
    // the 460px panel cannot spare a lane's width (the boxes would go under BOX_MIN and the row would wrap): the
    // narrowest boxes, as far apart as three of them to a row allow (24px), and the line still passes between two
    const tight = lay(run, 428);
    expect([tight.boxW, tight.gap, tight.perRow, tight.rows, tight.outer]).toEqual([BOX_MIN, 24, 3, 3, 0]);
    expect(faults(tight)).toEqual([]);
    // a run none of whose lines passes a row keeps its boxes wide: nothing to open the spaces for
    const plain = lay(sample(), 528);
    expect(plain.passing).toBe(0);
    expect(plain.gap).toBeLessThan(2 * G.keep); // 12px, and what the boxes' rounding leaves
    expect(Math.floor((528 - 2 * G.margin - 2 * G.gap) / 3) - plain.boxW).toBeLessThanOrEqual(1);
  });

  it("passes several rows each at a place of its own, stepping across between two rows, rather than round all of them", () => {
    // z waits on a, three rows up. The rows between hold three boxes, two, and three: their spaces do not line up
    const run = dag([
      node("a"),
      ...["b1", "b2", "b3"].map((id) => node(id, ["a"])),
      ...["c1", "c2"].map((id) => node(id, ["b1", "b2", "b3"])),
      ...["d1", "d2", "d3"].map((id) => node(id, ["c1", "c2"])),
      node("z", ["a", "d1", "d2", "d3"], { state: "waiting" }),
    ]);
    for (const width of [528, 740, 1136]) {
      const l = lay(run, width);
      const what = `at ${width}px`;
      expect(l.rows, what).toBe(5);
      expect([l.shared, l.crowded], what).toEqual([0, 0]);
      expect(faults(l), what).toEqual([]);
      const far = pieces([l.lines.find((e) => e.from === "a" && e.to === "z")!]);
      // it passes each of the three rows between two of its boxes, never round the end of a row
      for (const ids of [["b1", "b2", "b3"], ["c1", "c2"], ["d1", "d2", "d3"]]) {
        const row = ids.map((id) => l.at.get(id)!);
        const past = far.filter((p) => upright(p) && p.y1 <= row[0].y && p.y2 >= row[0].y + row[0].h);
        expect(past, `${what}, the row of ${ids[0]}`).toHaveLength(1);
        expect(past[0].x1 > row[0].x + row[0].w && past[0].x1 < row[row.length - 1].x, `${what}: between two boxes of the row of ${ids[0]}`).toBe(true);
      }
      expect(l.outer, what).toBe(0);
      // where two rows' spaces differ it steps across between them: a level stretch in that channel
      expect(far.filter((p) => !upright(p)).length, what).toBeGreaterThanOrEqual(2);
    }
  });

  it("stands a line that goes round a row in a gutter: clear of the row's boxes and of the drawing's edge", () => {
    // three boxes fill the row, each under a parent of its own, and each parent leads on to a node under the row:
    // three lines pass it, and the two spaces between its boxes hold one each
    const run = dag([node("a"), node("b"), node("c"), node("m1", ["a"]), node("m2", ["b"]), node("m3", ["c"]), node("x", ["a", "m1"]), node("y", ["b", "m2"]), node("z", ["c", "m3"])]);
    const l = lay(run, 460);
    expect(l.perRow).toBe(3);
    expect(l.outer).toBeGreaterThan(0);
    const row = ["m1", "m2", "m3"].map((id) => l.at.get(id)!);
    // the margin is the gutter, both sides (the rows stay in the middle)
    expect(row[0].x).toBeGreaterThanOrEqual(G.gutter);
    expect(row[2].x + row[2].w).toBeLessThanOrEqual(460 - G.gutter);
    expect(l.boxW).toBeGreaterThanOrEqual(BOX_MIN);
    const round = pieces(l.lines).filter((p) => upright(p) && p.y1 < row[0].y && p.y2 > row[0].y + row[0].h && (p.x1 < row[0].x || p.x1 > row[2].x + row[2].w));
    expect(round.length).toBeGreaterThan(0);
    for (const p of round) {
      expect(p.x1 < row[0].x ? row[0].x - p.x1 : p.x1 - (row[2].x + row[2].w), `beside the row at x=${p.x1}`).toBeGreaterThanOrEqual(G.keep);
      expect(Math.min(p.x1, 460 - p.x1), `from the edge at x=${p.x1}`).toBeGreaterThanOrEqual(6);
    }
    expect(faults(l)).toEqual([]);
    // a run none of whose lines goes round a row keeps the narrow margin, and its boxes their width
    expect(lay(sample(), 428).at.get("button")!.x).toBe(G.margin);
  });

  it("keeps a passing line `ease` from a box where the space beside it is wide, and never under `keep`", () => {
    // d waits on b (two frontiers up) and on c; c stands alone on its row, with all the width beside it
    const run = dag([node("a"), node("b", ["a"]), node("x", ["a"]), node("c", ["x"]), node("d", ["b", "c"]), node("e", ["d"])]);
    const l = lay(run, 900);
    const c = l.at.get("c")!;
    const lane = pieces(l.lines).filter((s) => upright(s) && s.y1 < c.y && s.y2 > c.y + c.h);
    expect(lane.length).toBeGreaterThan(0);
    for (const s of lane) expect(Math.min(Math.abs(s.x1 - c.x), Math.abs(s.x1 - (c.x + c.w)))).toBeGreaterThanOrEqual(G.ease - 0.5);
  });

  it("runs an edge that skips a frontier down a lane beside the boxes it passes, a lane's keep away from them", () => {
    // d waits on b (two frontiers up) and on c
    const run = dag([node("a"), node("b", ["a"]), node("x", ["a"]), node("c", ["x"]), node("d", ["b", "c"]), node("e", ["d"])]);
    const l = lay(run, 900);
    expect(l.shape.rows).toEqual([["a"], ["b", "x"], ["c"], ["d"], ["e"]]);
    expect([...l.drawn].sort()).toEqual(["a>b", "a>x", "b>d", "c>d", "d>e", "x>c"]);
    expect(faults(l)).toEqual([]);
    // b and c lead to d alone: one net, whose line passes c's row
    const net = l.nets.find((n) => n.children.join() === "d")!;
    expect(net.parents).toEqual(["b", "c"]);
    const c = l.at.get("c")!;
    const lane = pieces(l.lines).filter((s) => s.net === net.key && upright(s) && s.y1 < c.y && s.y2 > c.y + c.h);
    expect(lane.length).toBeGreaterThan(0);
    for (const s of lane) expect(Math.min(Math.abs(s.x1 - c.x), Math.abs(s.x1 - (c.x + c.w)))).toBeGreaterThanOrEqual(G.keep - 0.5);
    // one arrowhead for the two of them
    expect(l.heads.filter((h) => h.to === "d")).toHaveLength(1);
  });

  it("never squeezes a passing line through a gap of 12px or less between two boxes: it goes round", () => {
    // three boxes fill the row at 412px, 12px apart (too narrow a panel to stand even the narrowest boxes further
    // apart); z waits on p, two rows up, and on the row between
    const mids = ["m1", "m2", "m3"];
    const run = dag([node("p"), ...mids.map((id) => node(id, ["p"], { label: `A part with a title of some length, ${id}` })), node("z", ["p", ...mids], { state: "waiting" })]);
    const l = lay(run, 412);
    expect(l.gap).toBeLessThan(2 * G.keep); // 12px, and what the boxes' rounding leaves
    expect(faults(l)).toEqual([]);
    expect(l.crowded).toBe(0);
    const row = mids.map((id) => l.at.get(id)!);
    const [left, right] = [Math.min(...row.map((b) => b.x)), Math.max(...row.map((b) => b.x + b.w))];
    const passing = pieces(l.lines).filter((s) => upright(s) && s.y1 < row[0].y && s.y2 > row[0].y + row[0].h);
    expect(passing.length).toBeGreaterThan(0);
    // p's line to z passes the row outside it, in the margin, not between two of its boxes
    for (const s of passing) expect(s.x1 < left || s.x1 > right, `a passing line at x=${s.x1}`).toBe(true);
    // where the boxes stand far enough apart, the same line takes the space between them
    const wide = lay(run, 1136);
    expect(wide.gap).toBeGreaterThanOrEqual(2 * G.keep);
    const wrow = mids.map((id) => wide.at.get(id)!);
    const through = pieces(wide.lines).filter((s) => upright(s) && s.y1 < wrow[0].y && s.y2 > wrow[0].y + wrow[0].h);
    expect(through.some((s) => s.x1 > wrow[0].x + wrow[0].w && s.x1 < wrow[2].x)).toBe(true);
    expect(faults(wide)).toEqual([]);
  });

  it("draws an edge another path implies as its own line", () => {
    const l = lay(dag([node("a"), node("b", ["a"]), node("c", ["a", "b"])]), 900);
    expect([...l.drawn].sort()).toEqual(["a>b", "a>c", "b>c"]);
    expect(faults(l)).toEqual([]);
    // a leads to b and c, b to c alone: two nets. Both end at c, so they come into it as one line: one arrowhead
    expect(l.nets.map((n) => [n.parents, n.children])).toEqual([
      [["a"], ["b", "c"]],
      [["b"], ["c"]],
    ]);
    expect(l.heads.filter((h) => h.to === "c")).toMatchObject([{ from: ["a", "b"], nets: l.nets.map((n) => n.key) }]);
  });

  it("lands the lines of two fans into one child on points a port apart: no arrowhead stands on another", () => {
    const run = dag([node("p1"), node("p2"), node("c1", ["p1"]), node("c2", ["p1", "p2"]), node("c3", ["p2"])]);
    const l = lay(run, 900);
    expect(l.nets.map((n) => [n.parents, n.children])).toEqual([
      [["p1"], ["c1", "c2"]],
      [["p2"], ["c2", "c3"]],
    ]);
    const [left, right] = l.heads.filter((h) => h.to === "c2").sort((a, b) => a.x - b.x);
    expect(left.from).toEqual(["p1"]);
    expect(right.from).toEqual(["p2"]);
    expect(right.x - left.x).toBe(G.port);
    expect(right.x - left.x).toBeGreaterThan(G.arrowW + G.portClear); // an arrowhead's width and more between the two
    // the two stand either side of the child's middle
    const c2 = l.at.get("c2")!;
    expect(Math.abs((left.x + right.x) / 2 - (c2.x + c2.w / 2))).toBeLessThanOrEqual(1);
    expect(faults(l)).toEqual([]);
  });

  it("brings a line straight down from the parent right over the child; a net that ends there joins it, one that goes on below lands a port beside it", () => {
    // a over b over c, and a leads to c too: b's line into c is straight, and a's comes round b into the same point
    const l = lay(dag([node("a"), node("b", ["a"]), node("c", ["a", "b"])]), 900);
    const c = l.at.get("c")!;
    expect(l.heads.filter((h) => h.to === "c")).toMatchObject([{ x: c.x + c.w / 2 + 0.5, from: ["a", "b"] }]);
    expect(l.lines.find((e) => e.from === "b" && e.to === "c")!.d).toMatch(/^M[\d.]+,[\d.]+ V[\d.]+$/);
    const round = l.lines.find((e) => e.from === "a" && e.to === "c")!;
    expect(round.pts[round.pts.length - 1]).toEqual([c.x + c.w / 2 + 0.5, c.y - G.arrow]);
    expect(faults(l)).toEqual([]);
    // a leads on to d, under c: joined into b's line over c, b would read as leading to d too. a's line keeps a
    // point of its own on c, a port beside the straight one, and ends at d together with c's
    const on = lay(dag([node("a"), node("b", ["a"]), node("c", ["a", "b"]), node("d", ["a", "c"])]), 900);
    const [direct, beside] = [on.heads.find((h) => h.to === "c" && h.from.join() === "b")!, on.heads.find((h) => h.to === "c" && h.from.join() === "a")!];
    expect(direct.x).toBe(on.at.get("c")!.x + on.at.get("c")!.w / 2 + 0.5);
    expect(on.lines.find((e) => e.from === "b" && e.to === "c")!.d).toMatch(/^M[\d.]+,[\d.]+ V[\d.]+$/);
    expect(Math.abs(beside.x - direct.x)).toBe(G.port);
    expect(on.heads.filter((h) => h.to === "d")).toMatchObject([{ from: ["a", "c"] }]);
    expect(faults(on)).toEqual([]);
    // the real 6-node run: the three parents right over the last node come down one straight trunk from the
    // middle one, and the line from further up joins them over it: one arrowhead for the four
    const run = fromDag(fixture("codex-coexist-live.json"), "kami");
    for (const width of [428, 528, 1136]) {
      const g = lay(run, width, { stretch: width > 600 ? 1.25 : 1 });
      const v = g.at.get("t5-verify")!;
      const heads = g.heads.filter((h) => h.to === "t5-verify");
      expect(heads.map((h) => [h.from.length, h.nets.length]), `at ${width}`).toEqual([[4, 2]]);
      expect(heads[0].x, `at ${width}`).toBe(Math.round(v.x + v.w / 2) + 0.5);
      expect(g.lines.find((e) => e.from === "t4-fence" && e.to === "t5-verify")!.d, `at ${width}`).toMatch(/^M[\d.]+,[\d.]+ V[\d.]+$/);
      expect(faults(g), `at ${width}`).toEqual([]);
    }
  });

  it("merges the parents that lead to one child into one line with a single arrowhead", () => {
    // five parents, one child: one net, one head, five lines that end in it
    const ps = ["p1", "p2", "p3", "p4", "p5"];
    const l = lay(dag([...ps.map((id) => node(id)), node("z", ps, { state: "waiting" })]), 1136);
    expect(l.nets).toHaveLength(1);
    expect(l.heads).toHaveLength(1);
    const z = l.at.get("z")!;
    expect(l.heads[0]).toMatchObject({ to: "z", y: z.y, from: ps });
    expect(l.lines).toHaveLength(5);
    const ends = pieces(l.lines).filter((s) => upright(s) && Math.abs(s.y2 - (z.y - G.arrow)) < 0.6);
    expect(new Set(ends.map((s) => s.x1))).toEqual(new Set([l.heads[0].x]));
    expect(faults(l)).toEqual([]);
  });

  it("spreads many fans into one child along its top edge, evenly, and never off its corners", () => {
    // six parents, each with a child of its own too: six nets lead into z
    const ps = Array.from({ length: 6 }, (_, i) => `p${i}`);
    const run = dag([...ps.map((id) => node(id)), ...ps.map((id, i) => node(`k${i}`, [id])), node("z", ps, { state: "waiting" })]);
    for (const width of [528, 1136]) {
      const l = lay(run, width);
      const z = l.at.get("z")!;
      const xs = l.heads.filter((h) => h.to === "z").map((h) => h.x).sort((a, b) => a - b);
      // a fan whose other child stands in z's row keeps a point of its own; the fans that end at z (its row
      // wrapped, and their other child stands in the row above) share one
      const last = (n: { children: string[] }) => Math.max(...n.children.map((k) => l.at.get(k)!.row));
      const ending = l.nets.filter((n) => n.children.filter((k) => l.at.get(k)!.row === last(n)).join() === "z");
      expect(l.nets.filter((n) => n.children.includes("z"))).toHaveLength(6);
      expect(xs).toHaveLength(6 - ending.length + (ending.length ? 1 : 0));
      if (width === 1136) expect(xs).toHaveLength(6);
      for (const x of xs) expect(x >= z.x + G.portInset - 1 && x <= z.x + z.w - G.portInset + 1, `${x} on z's top at ${width}`).toBe(true);
      for (let i = 1; i < xs.length; i++) expect(xs[i] - xs[i - 1], `at ${width}`).toBeGreaterThanOrEqual(G.portClear - 1);
      expect(l.crowded, `at ${width}`).toBe(0);
      expect(faults(l), `at ${width}`).toEqual([]);
    }
  });

  it("gives two level stretches that would overlap between two rows a height each, a track apart", () => {
    // p1 leads to c1..c3 and p2 to c2..c4: the two stretches share the space over c2 and c3
    const run = dag([node("p1"), node("p2"), node("c1", ["p1"]), node("c2", ["p1", "p2"]), node("c3", ["p1", "p2"]), node("c4", ["p2"])]);
    const l = lay(run, 1136);
    expect([...l.drawn].sort()).toEqual(edgesOf(l));
    expect(faults(l)).toEqual([]);
    const level = [...new Set(pieces(l.lines).filter((s) => !upright(s) && s.x2 - s.x1 > 2 * G.r).map((s) => s.y1))].sort((a, b) => a - b);
    expect(level).toHaveLength(2);
    expect(level[1] - level[0]).toBe(G.track);
  });

  it("leaves a gap where a line passes over another net's level stretch: a crossing never reads as a join", () => {
    // p1 leads to c1..c3 and p2 to c2..c4: p2's lines into c2 and c3 pass over p1's stretch, or p1's over p2's
    const run = dag([node("p1"), node("p2"), node("c1", ["p1"]), node("c2", ["p1", "p2"]), node("c3", ["p1", "p2"]), node("c4", ["p2"])]);
    const l = lay(run, 1136);
    expect(faults(l)).toEqual([]);
    // the gaps are in the paths: an upright stretch broken in two, 2 * hop apart
    const gaps = l.lines.flatMap((e) => [...e.d.matchAll(/V([\d.]+) M([\d.]+),([\d.]+)/g)].map((m) => Number(m[3]) - Number(m[1])));
    expect(gaps.length).toBeGreaterThan(0);
    for (const g of gaps) expect(Math.abs(g)).toBe(2 * G.hop);
    // and each is at the height of the other net's stretch
    const level = pieces(l.lines).filter((s) => !upright(s) && s.x2 - s.x1 > 2 * G.r);
    for (const e of l.lines)
      for (const m of e.d.matchAll(/V([\d.]+) M([\d.]+),([\d.]+)/g)) {
        const [x, y] = [Number(m[2]), (Number(m[1]) + Number(m[3])) / 2];
        expect(level.some((s) => s.net !== e.net && Math.abs(s.y1 - y) < 0.1 && s.x1 < x && x < s.x2), `${e.from}>${e.to} at ${x},${y}`).toBe(true);
      }
    // a line of the same net is never broken where it meets its own stretch
    const lone = lay(sample(), 900);
    expect(lone.lines.some((e) => / M/.test(e.d))).toBe(false);
  });

  it("turns every line with a rounded corner: no square elbow, and a straight line where parent stands over child", () => {
    const l = lay(sample(), 900);
    for (const e of l.lines) {
      const turns = (e.d.match(/Q/g) ?? []).length;
      const straight = Math.abs(l.at.get(e.from)!.x - l.at.get(e.to)!.x) < 1;
      expect(turns, `${e.from}>${e.to}`).toBe(straight ? 0 : 2);
      expect(e.d).toMatch(/^M[\d.]+,[\d.]+( [VH][\d.]+| Q[\d.]+,[\d.]+ [\d.]+,[\d.]+| M[\d.]+,[\d.]+)+$/);
    }
    // the turn's legs are the drawing's radius long, where the stretches leave it: a soft elbow, wider than the
    // room the layout keeps for a turn
    const bent = l.lines.find((e) => e.from === "api" && e.to === "button")!;
    const [, cx, cy, ex, ey] = /Q([\d.]+),([\d.]+) ([\d.]+),([\d.]+)/.exec(bent.d)!.map(Number);
    expect(G.curve).toBeGreaterThan(G.r);
    expect(Math.abs(ex - cx) + Math.abs(ey - cy)).toBe(G.curve);
    const l2 = lay(dag([node("a"), node("b", ["a"])]), 900);
    expect(l2.lines).toHaveLength(1);
    const a = l2.at.get("a")!;
    expect(l2.lines[0].d).toBe(`M${a.x + a.w / 2 + 0.5},${a.y + a.h} V${l2.at.get("b")!.y - G.arrow}`);
    expect(faults(l2)).toEqual([]);
    // also where the text asks for a box an odd number of px wide: the parent's line and the child's point stand on the same half pixel
    for (const width of [101, 102, 137, 140]) {
      const odd = layoutBoxes(dag([node("a"), node("b", ["a"]), node("c", ["b"])]), { width: 900, measure: () => width });
      const wants = width + G.icon + G.iconGap + 2 * G.padX + 2 * G.border; // the status line is the widest: 144, 145, 180, 183
      expect(odd.boxW).toBe(wants + (wants % 2)); // a box and a gap are an even number of px together
      for (const e of odd.lines) expect(e.d, `${e.from}>${e.to} in a ${odd.boxW}px box`).toMatch(/^M[\d.]+,[\d.]+ V[\d.]+$/);
    }
  });

  it("draws every edge but the one that closes a loop, when the recorded edges loop", () => {
    const run = dag([node("a"), node("b", ["a", "c"]), node("c", ["b"])]);
    const l = lay(run, 900);
    expect(l.shape.looped).toBe(true);
    expect(l.shape.edges.map((e) => `${e.from}>${e.to}`).sort()).toEqual(["a>b", "b>c", "c>b"]);
    expect([...l.drawn].sort()).toEqual(["a>b", "b>c"]);
    expect(faults(l)).toEqual([]);
    // a node that only waits on a node of the loop keeps its line
    const below = lay(dag([node("a", ["b"]), node("b", ["a"]), node("c", ["a"])]), 900);
    expect([...below.drawn].sort()).toEqual(["a>b", "a>c"]);
    expect(faults(below)).toEqual([]);
  });

  it("keeps a frontier that fits on one row, also when another frontier has to wrap", () => {
    // twelve start nodes with long titles, and seven nodes that wait on them: 1136px hold eight boxes
    const starts = Array.from({ length: 12 }, (_, i) => node(`s${i}`, [], { label: `Start node ${i} with a rather long title` }));
    const next = Array.from({ length: 7 }, (_, i) => node(`n${i}`, [`s${i}`, `s${i + 5}`]));
    const l = lay(dag([...starts, ...next]), 1136);
    expect(new Set(next.map((n) => l.at.get(n.id)!.row)).size).toBe(1);
    expect(l.perRow).toBe(7);
    // the twelve wrap into two even rows
    expect(l.boxes.filter((b) => b.frontier === 0).map((b) => b.row)).toEqual([0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1]);
    expect([...l.drawn].sort()).toEqual(edgesOf(l));
    expect(l.crowded).toBe(0);
    expect(faults(l)).toEqual([]);
  });

  it("keeps a frontier a little too long for the width on one row where the drawing may stretch (the full view), and wraps it where it may not", () => {
    // nine under one parent: at the narrowest boxes they need 9 * 120 + 8 * 12 + 20 = 1196px
    const mids = Array.from({ length: 9 }, (_, i) => `m${i}`);
    const run = dag([node("p"), ...mids.map((id) => node(id, ["p"])), node("z", mids, { state: "waiting" })]);
    const panel = lay(run, 1136);
    expect(panel.w).toBe(1136);
    expect(new Set(mids.map((id) => panel.at.get(id)!.row)).size).toBe(2);
    const full = lay(run, 1136, { stretch: 1.25 });
    expect(full.w).toBe(9 * BOX_MIN + 8 * G.gap + 2 * G.margin);
    expect(new Set(mids.map((id) => full.at.get(id)!.row)).size).toBe(1);
    expect(full.boxW).toBe(BOX_MIN);
    expect(full.passing).toBe(0); // every line joins two neighbouring rows
    expect(faults(full)).toEqual([]);
    // more than a quarter too long: it wraps at the width it was given
    expect(lay(run, 900, { stretch: 1.25 }).w).toBe(900);
    // a run that fits is never wider for it
    expect(lay(sample(), 1136, { stretch: 1.25 }).w).toBe(1136);
  });

  it("gives a dense run fewer boxes to a row rather than two lines one place: no fault at any panel width", () => {
    // seeded, so the same runs every time: 12 to 50 nodes, each waiting on some of the nodes before it
    let seed = 1;
    let shared = 0; // the layouts in which lines share a place
    const rnd = () => (seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648;
    for (let k = 0; k < 36; k++) {
      const n = 12 + Math.floor(rnd() * 39);
      const p = 0.05 + rnd() * 0.2;
      const nodes = Array.from({ length: n }, (_, i) => node(`n${i}`, Array.from({ length: i }, (_, j) => `n${j}`).filter(() => rnd() < p), { label: `Node ${i} of run ${k}` }));
      for (const width of [428, 460, 528]) {
        const l = lay(dag(nodes), width);
        const what = `run ${k} (${n} nodes) at ${width}px`;
        expect(l.boxes.length, what).toBe(n);
        expect(l.crowded - l.shared, what).toBe(l.heads.filter((h) => l.tight.includes(h.to)).length); // what is crowded besides is the lines into a tight child
        expect([...l.drawn].sort(), what).toEqual(edgesOf(l));
        sharesOnlyAtTwoToARow(l, what);
        shared += l.shared ? 1 : 0;
      }
    }
    expect(shared).toBe(0);
  }, 30_000);

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
        for (const [width, stretch] of [
          [428, 1],
          [528, 1],
          [1136, 1.25],
        ]) {
          const l = lay(dag(nodes), width, { capRows, stretch });
          const what = `run ${k} (${n} nodes) at ${width}px${capRows ? ", capped" : ""}`;
          expect(l.shared, what).toBe(0);
        expect(l.crowded, what).toBe(l.heads.filter((h) => l.tight.includes(h.to)).length); // what is crowded besides is the lines into a tight child
          expect(faults(l), what).toEqual([]);
        }
    }
  }, 30_000);

  it("gives every passing line a place of its own in runs up to 60 nodes at the panel's widths (an independent check's generator)", () => {
    // the generator of the check that found two lines on one place in 54-60-node runs at 428px and 460px (its
    // runs 11, 13, 27 and 47): one column of boxes at the comfortable width left the lines too little room beside
    // them. Seeded: 10 to 60 nodes, some with many roots, some with one node that waits on most of the others
    let seed = 12345;
    let shared = 0; // the layouts in which lines share a place
    const rnd = () => (seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648;
    const states: RunNode["state"][] = ["done", "running", "failed", "waiting", "done", "cancelled", "parked", "blocked"];
    for (let k = 0; k < 80; k++) {
      const n = 10 + Math.floor(rnd() * 51);
      const p = 0.05 + rnd() * 0.25;
      const roots = rnd() < 0.4 ? 2 + Math.floor(rnd() * 14) : 1;
      const hub = rnd() < 0.4;
      const nodes: RunNode[] = [];
      for (let i = 0; i < n; i++) {
        let deps = i < roots ? [] : Array.from({ length: i }, (_, j) => `n${j}`).filter(() => rnd() < p);
        if (hub && i === n - 1) deps = Array.from({ length: i }, (_, j) => `n${j}`).filter(() => rnd() < 0.6);
        nodes.push(
          node(`n${i}`, deps, {
            label: `Task ${i} ${rnd() < 0.3 ? "with a fairly long title for wrapping here" : ""}`,
            state: states[Math.floor(rnd() * states.length)],
            model: rnd() < 0.5 ? "claude-opus-5-5" : undefined,
            effort: rnd() < 0.5 ? "high" : undefined,
            route: rnd() < 0.5 ? "visual-engineering" : "unspecified-high",
            executor: rnd() < 0.2 ? "codex" : undefined,
            started: 0,
          }),
        );
      }
      // the two panel widths for every run; the full view for every fourth
      for (const [width, stretch] of [
        [428, 1],
        [460, 1],
        ...(k % 4 ? [] : [[1136, 1.25]]),
      ]) {
        const l = lay(dag(nodes), width, { stretch });
        const what = `run ${k} (${n} nodes${hub ? ", one waits on most" : ""}) at ${width}px`;
        expect(l.crowded - l.shared, what).toBe(l.heads.filter((h) => l.tight.includes(h.to)).length); // what is crowded besides is the lines into a tight child
        if (width > 600) expect(l.shared, what).toBe(0);
        sharesOnlyAtTwoToARow(l, what);
        shared += l.shared ? 1 : 0;
      }
    }
    // of the 160 panel layouts of this generator (its densest runs, 48 nodes and up at two boxes to a row)
    expect(shared).toBeLessThanOrEqual(18);
  }, 120_000);

  it("calls a child tight when more lines lead into it than its top edge holds an arrowhead apart, and only then", () => {
    // each parent has a child of its own too, so each is a net of its own into z. A 120px box holds 92px of points
    const fan = (k: number) => {
      const ps = Array.from({ length: k }, (_, i) => `p${i}`);
      return dag([...ps.map((id) => node(id)), ...ps.map((id, i) => node(`k${i}`, [id])), node("z", ps, { state: "waiting" })]);
    };
    for (const k of [2, 5, 8]) {
      const l = lay(fan(k), 1136, { stretch: 1.25 });
      const xs = l.heads.filter((h) => h.to === "z").map((h) => h.x).sort((a, b) => a - b);
      expect(xs, `${k} lines`).toHaveLength(k);
      expect(l.tight, `${k} lines`).toEqual([]);
      for (let i = 1; i < xs.length; i++) expect(xs[i] - xs[i - 1], `${k} lines`).toBeGreaterThanOrEqual(G.arrowW + 2);
      expect(faults(l), `${k} lines`).toEqual([]);
    }
    // forty fans into one box no wider than 248px (220px of points). The fans that end at z (their other child
    // stands in a row above) share a point; the rest still do not fit an arrowhead apart. The layout says so
    const many = lay(fan(40), 1136);
    const heads = many.heads.filter((h) => h.to === "z");
    expect(many.tight).toEqual(["z"]);
    expect([many.crowded, many.shared]).toEqual([heads.length, 0]);
    expect(heads.reduce((sum, h) => sum + h.nets.length, 0)).toBe(40);
    expect(heads.length).toBeGreaterThan(1);
    expect(faults(many)).toEqual([]);
  });

  it("wraps only a frontier too wide for the narrowest boxes, and still draws every edge", () => {
    // seven under one parent, one node waiting on all seven: 428px hold three boxes
    const mids = ["m1", "m2", "m3", "m4", "m5", "m6", "m7"];
    const run = dag([node("p"), ...mids.map((id) => node(id, ["p"])), node("z", mids, { state: "waiting" })]);
    const l = lay(run, 428);
    expect(l.perRow).toBe(3);
    expect(l.boxes.filter((b) => b.frontier === 1).map((b) => b.row)).toEqual([1, 1, 1, 2, 2, 3, 3]); // as even as they go
    expect([...l.drawn].sort()).toEqual(edgesOf(l));
    expect(l.drawn.size).toBe(14);
    expect(faults(l)).toEqual([]);
    // wide enough, the same run is one row of seven
    const wide = lay(run, 1136);
    expect(new Set(mids.map((id) => wide.at.get(id)!.row)).size).toBe(1);
    expect(faults(wide)).toEqual([]);
  });

  it("shows the first rows of a very long frontier, running then failed first, and how many more there are", () => {
    const nodes = Array.from({ length: 88 }, (_, i) => node(`s${i}`, [], { state: i >= 85 ? "running" : i === 40 ? "failed" : "done" }));
    const run: Pick<AgentRun, "kind" | "nodes"> = { kind: "codex-sub", nodes };
    const capped = lay(run, 428, { capRows: 8 });
    expect(capped.perRow).toBe(3);
    expect(capped.boxes.length).toBe(24);
    expect(capped.boxes.slice(0, 5).map((b) => b.id)).toEqual(["s85", "s86", "s87", "s40", "s0"]);
    expect(capped.more).toMatchObject([{ frontier: 0, hidden: 64, total: 88 }]);
    // the line of text starts at the row's left edge, under its boxes
    expect(capped.more[0].x).toBe(capped.boxes[21].x);
    expect(capped.more[0].y).toBe(capped.boxes[21].y + capped.boxes[21].h);
    const all = lay(run, 428, { capRows: 8, opened: new Set([0]) });
    expect(all.boxes.length).toBe(88);
    expect(all.more).toMatchObject([{ hidden: 0, total: 88 }]); // "Show fewer"
    // the full view has no cap
    expect(lay(run, 1136, { stretch: 1.25 }).boxes.length).toBe(88);
  });

  it("stands every row on the widest row's grid: a line that passes the row under its parent comes straight down, with no step aside", () => {
    // the real 6-node run: two boxes over three. The line from the second of the two to the last node passes the
    // row of three between two of its boxes, right under its parent's middle
    const run = fromDag(fixture("codex-coexist-live.json"), "kami");
    for (const width of [428, 528, 1136]) {
      const g = lay(run, width, { stretch: width > 600 ? 1.25 : 1 });
      const [top, under] = [g.boxes.filter((b) => b.row === 0), g.boxes.filter((b) => b.row === 1)];
      expect([top.length, under.length], `at ${width}`).toEqual([2, 3]);
      // each of the two stands over a space between two of the three
      top.forEach((b, i) => expect(b.x + b.w / 2, `at ${width}`).toBe((under[i].x + under[i].w + under[i + 1].x) / 2));
      expect((g.boxW + g.gap) % 2, `at ${width}`).toBe(0);
      const skip = g.lines.find((e) => e.from === "t2-status-update" && e.to === "t5-verify")!;
      // straight down from its parent to the level stretch over the last node: one x all the way
      expect(new Set(skip.pts.slice(0, -2).map((pt) => pt[0])).size, `at ${width}`).toBe(1);
      expect((skip.d.match(/Q/g) ?? []).length, `at ${width}`).toBe(2);
      expect(kinks(g), `at ${width}`).toEqual([]);
    }
    // the real runs of six and ten nodes have no kink at any width
    for (const name of ["codex-coexist-live.json", "codex-coexist.json", "omher-v02.json", "omh-dap.json"])
      for (const width of [428, 528, 1136]) expect(kinks(lay(fromDag(fixture(name), "kami"), width, { stretch: width > 600 ? 1.25 : 1 })), `${name} at ${width}`).toEqual([]);
  });

  it("moves a point under the lane its line comes down, and a line's start over the lane it leaves for, where the step aside would be a kink", () => {
    // an independent check's run (15 nodes, 560px): n5's line came down a lane 4px beside its point on n13, and
    // turned twice in those 4px
    const deps: Record<string, string[]> = { n5: ["n1"], n6: ["n0", "n4"], n7: ["n2"], n8: ["n3", "n6"], n9: ["n0"], n10: ["n8"], n11: ["n1", "n4", "n9"], n12: ["n5", "n9"], n13: ["n3", "n5", "n7"], n14: ["n1", "n4"] };
    const run = dag(Array.from({ length: 15 }, (_, i) => node(`n${i}`, deps[`n${i}`] ?? [])));
    for (const width of [528, 560]) {
      const l = lay(run, width);
      expect(kinks(l, true), `at ${width}`).toEqual([]);
      expect(faults(l), `at ${width}`).toEqual([]);
      // a line that leaves its box off the middle is over its lane, and still clear of the box's corners
      for (const e of l.lines) {
        const b = l.at.get(e.from)!;
        expect(e.pts[0][0] >= b.x + G.portInset && e.pts[0][0] <= b.x + b.w - G.portInset, `${e.from}>${e.to} at ${width}`).toBe(true);
        if (Math.abs(e.pts[0][0] - (b.x + b.w / 2)) > 1) expect(e.pts[2]?.[0], `${e.from}>${e.to} at ${width}`).toBe(e.pts[0][0]);
      }
    }
  });

  it("stops trying layouts when a run is too large for them, and never goes under two boxes to a row", () => {
    let seed = 5;
    const rnd = () => (seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648;
    const dense = (n: number, p: number) => dag(Array.from({ length: n }, (_, i) => node(`n${i}`, Array.from({ length: i }, (_, j) => `n${j}`).filter(() => rnd() < p))));
    // 250 nodes: the first layout and a trial or two (each costs a quarter of a second here); every one of them
    // took five seconds
    const huge = lay(dense(250, 0.05), 428);
    expect(huge.trials).toBeLessThanOrEqual(2);
    expect(lay(dag([]), 428).trials).toBe(1); // a number, also for a run of no nodes
    expect(huge.boxes).toHaveLength(250);
    expect(huge.perRow).toBeGreaterThanOrEqual(2);
    // 100 nodes: a dozen
    const large = lay(dense(100, 0.1), 428);
    expect(large.trials).toBeLessThanOrEqual(12);
    expect(large.perRow).toBeGreaterThanOrEqual(2);
    // a run of the size people plan is laid out as before: every trial its lines ask for
    expect(lay(dense(40, 0.1), 428).shared).toBe(0);
    // a plan, eight parts, a check a part, one last node: two to a row in the 460px panel, never a column
    const parts = Array.from({ length: 8 }, (_, i) => `p${i}`);
    const plan = dag([node("plan"), ...parts.map((id) => node(id, ["plan"])), ...parts.map((id, i) => node(`c${i}`, [id])), node("verify", parts.map((_, i) => `c${i}`))]);
    const l = lay(plan, 428);
    expect(l.perRow).toBeGreaterThanOrEqual(2);
    expect(faults(l)).toEqual([]);
  }, 30_000);

  it("keeps the line from the parent right over a child straight when the child's other points still fit beside it, each side spaced by its own room", () => {
    // an independent check's run (8 nodes, 428px): n4 stands right over n7, which takes four lines. Spaced a full
    // port from the held point they needed 90 of the 91px its top has, so the held point gave way and n4's line
    // turned twice, 15px aside
    const deps: Record<string, string[]> = { n2: ["n0"], n3: ["n1", "n2"], n4: ["n1", "n2", "n3"], n5: ["n3"], n6: ["n0", "n1", "n2", "n5"], n7: ["n0", "n1", "n3", "n4", "n5"] };
    const l = lay(dag(Array.from({ length: 8 }, (_, i) => node(`n${i}`, deps[`n${i}`] ?? []))), 428);
    const [over, under] = [l.at.get("n4")!, l.at.get("n7")!];
    expect([over.x, over.row + 1], "n4 stands right over n7").toEqual([under.x, under.row]);
    expect(l.lines.find((e) => e.from === "n4" && e.to === "n7")!.d).toMatch(/^M[\d.]+,[\d.]+ V[\d.]+$/);
    expect(l.tight).toEqual([]);
    expect(faults(l)).toEqual([]);
  });

  it("lays the real runs out with every edge a connected line that keeps clear of every box, in the panel and the full view", () => {
    const runs: AgentRun[] = [
      fromDag(fixture("omher-v02.json"), "default"),
      fromDag(fixture("codex-coexist-live.json"), "kami"),
      fromDag(fixture("codex-coexist.json"), "kami"),
      fromDag(fixture("omh-dap.json"), "kami"),
      ...(fixture("runs-cli.json").runs as AgentRun[]),
      fixture("big-run.json") as AgentRun,
    ];
    for (const run of runs)
      for (const [width, stretch] of [
        [428, 1],
        [528, 1],
        [740, 1.25],
        [1136, 1.25],
      ])
        for (const measure of [M, estimate]) {
          const l = layoutBoxes(run, { width, stretch, measure });
          const what = `${run.id} at ${width}px`;
          expect(l.boxes.length, what).toBe(run.nodes.length);
          expect(l.w, what).toBeLessThanOrEqual(width * stretch);
          for (const a of l.boxes) {
            expect(a.x >= 0 && a.x + a.w <= l.w, `${what}: ${a.id} inside the width`).toBe(true);
            for (const b of l.boxes) if (a.id < b.id) expect(a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h, `${what}: ${a.id} over ${b.id}`).toBe(false);
          }
          if (!l.shape.looped) expect([...l.drawn].sort(), what).toEqual(edgesOf(l));
          expect(l.crowded, what).toBe(0);
          expect(faults(l), what).toEqual([]);
          // the points on a child stand in the order its lines come to it: two lines into one node never cross
          // on the last stretch (in a plan of a size people run; the 40-node run has children no order suits).
          // Where a net's line comes from: the far end of its level stretch at the child
          for (const b of run.nodes.length <= 12 ? l.boxes : []) {
            const heads = l.heads.filter((h) => h.to === b.id).sort((p, q) => p.x - q.x);
            if (heads.length < 2) continue;
            const from = heads.map((h) => {
              const ends = l.lines.filter((e) => e.net === h.net && e.to === b.id).map((e) => e.pts[e.pts.length - 3]?.[0] ?? h.x);
              return ends.reduce((a, x) => a + x, 0) / ends.length;
            });
            for (let i = 1; i < from.length; i++) expect(from[i], `${what}: the lines into ${b.id} arrive in the order of their points`).toBeGreaterThanOrEqual(from[i - 1] - 0.5);
          }
        }
  });

  it("keeps the 40-node run's nine-wide frontier on one row in the full view: only its five skipping edges pass a row", () => {
    const run = fixture("big-run.json") as AgentRun;
    const full = lay(run, 1136, { stretch: 1.25 });
    expect(new Set(full.boxes.map((b) => b.row)).size).toBe(full.shape.rows.length); // a frontier, a row
    expect(full.w).toBeGreaterThan(1136);
    const rows = new Map(full.boxes.map((b) => [b.id, b.row]));
    expect(full.lines.filter((e) => rows.get(e.to)! - rows.get(e.from)! > 1)).toHaveLength(5);
    // and each of them passes its rows between two boxes, none round the end of a row
    expect([full.outer, full.shared]).toEqual([0, 0]);
    expect(faults(full)).toEqual([]);
  });
});

describe("the lines", () => {
  const l = lay(sample(), 900);
  const rect = (id: string): Rect => l.at.get(id)!;
  const nums = (d: string) => (d.match(/-?\d+(\.\d+)?/g) ?? []).map(Number);

  it("leaves each parent's bottom at its middle and ends with a head on each child's top", () => {
    const fan = l.nets[0].key;
    const out = l.lines.filter((e) => e.net === fan);
    expect(out.map((e) => [e.from, e.to])).toEqual([
      ["api", "button"],
      ["api", "docs"],
      ["api", "cli"],
    ]);
    for (const e of out) {
      const [x, y] = nums(e.d);
      expect(Math.abs(x - (rect("api").x + l.boxW / 2))).toBeLessThanOrEqual(1);
      expect(y).toBe(rect("api").y + rect("api").h);
      expect(e.tone).toBe("done");
      const end = nums(e.d).slice(-1)[0];
      expect(end).toBe(rect(e.to).y - G.arrow);
    }
    const heads = l.heads.filter((h) => h.net === fan);
    expect(heads.map((h) => h.to)).toEqual(["button", "docs", "cli"]);
    for (const h of heads) {
      expect(h.y).toBe(rect(h.to).y);
      expect(Math.abs(h.x - (rect(h.to).x + l.boxW / 2))).toBeLessThanOrEqual(1);
      expect(h.from).toEqual(["api"]);
    }
  });

  it("carries the slow dash on the edges into a running child, drawn from the child back; two children's dashes never lie on one stretch", () => {
    const key = (p: Seg) => `${p.x1} ${p.y1} ${p.x2} ${p.y2}`;
    expect(l.flows.map((f) => [f.from, f.to])).toEqual([
      ["api", "button"],
      ["api", "docs"],
    ]);
    for (const f of l.flows) {
      const head = l.heads.find((h) => h.to === f.to)!;
      // it starts where the edge ends: an arrowhead short of the child's top
      expect(nums(f.d).slice(0, 2)).toEqual([head.x, rect(f.to).y - G.arrow]);
      // no gaps in it: a dash pattern would start again after each
      expect(f.d).not.toMatch(/ M/);
    }
    // the first running child's dash rides its whole edge, up to the parent's bottom: the same stretches as the
    // edge itself, the other way round
    const [first, second] = l.flows;
    expect(nums(first.d).slice(-1)[0]).toBe(rect("api").y + rect("api").h);
    expect(pieces([first]).map(key).sort()).toEqual(pieces([l.lines.find((e) => e.to === "button")!]).map(key).sort());
    // docs stands right under api: its dash runs up its own line and stops where button's comes in from the
    // side. The two share api's line down, and two dashes out of step never lie on one line
    expect(pieces([second])).toHaveLength(1);
    expect(nums(second.d).slice(-1)[0]).toBeGreaterThan(rect("api").y + rect("api").h);
    const shared = (a: Seg, b: Seg) => (upright(a) && upright(b) && a.x1 === b.x1 ? Math.min(a.y2, b.y2) - Math.max(a.y1, b.y1) : !upright(a) && !upright(b) && a.y1 === b.y1 ? Math.min(a.x2, b.x2) - Math.max(a.x1, b.x1) : 0);
    for (const a of pieces([first])) for (const b of pieces([second])) expect(shared(a, b)).toBeLessThanOrEqual(0.01);
    // no edge into a node that is not running carries it
    expect(l.flows.some((f) => f.to === "cli" || f.to === "verify")).toBe(false);
    // three parents into one running child: three edges, whole, which leave the child as one
    const join = lay(dag([node("a"), node("b"), node("c"), node("z", ["a", "b", "c"], { state: "running", model: "gpt-6.1" })]), 900);
    expect(join.flows).toHaveLength(3);
    expect(new Set(join.flows.map((f) => /^M[\d.]+,[\d.]+/.exec(f.d)![0])).size).toBe(1);
    const starts = join.flows.map((f) => pieces([f])[0]);
    expect(starts.every((p) => upright(p) && p.x1 === starts[0].x1 && p.y2 === starts[0].y2)).toBe(true);
    for (const f of join.flows) expect(nums(f.d).slice(-1)[0]).toBe(join.at.get(f.from)!.y + join.at.get(f.from)!.h);
    // a parent with three running children at any width: no stretch carries two children's dashes
    for (const width of [428, 740, 1136]) {
      const fan = lay(dag([node("p"), ...["x", "y", "z"].map((id) => node(id, ["p"], { state: "running", model: "gpt-6.1" }))]), width);
      expect(fan.flows).toHaveLength(3);
      const by = fan.flows.map((f) => pieces([f]));
      by.forEach((a, i) => by.forEach((b, k) => i < k && a.forEach((p) => b.forEach((q) => expect(shared(p, q), `at ${width}`).toBeLessThanOrEqual(0.01)))));
      // and every one still reaches from its child to the lines of the others: nothing is left without a dash
      for (const f of fan.flows) expect(pieces([f]).length).toBeGreaterThan(0);
    }
  });

  it("says each line's parent's state, one line an edge", () => {
    const join = l.nets[1].key;
    expect(l.lines.filter((e) => e.net === join).map((e) => [e.from, e.to, e.tone])).toEqual([
      ["button", "verify", "running"],
      ["docs", "verify", "out"],
      ["cli", "verify", "failed"],
    ]);
    expect(l.heads.filter((h) => h.net === join)).toMatchObject([{ to: "verify", y: rect("verify").y, from: ["button", "docs", "cli"] }]);
  });

  it("follows a moved box with one elbow an edge, and leaves every other edge where the layout ran it", () => {
    const tone = (id: string) => ({ api: "done", button: "running", docs: "out", cli: "failed", verify: "waiting" })[id]!;
    // nothing moved: the layout's own
    expect(movedLines(l, rect, new Set(), tone, () => false).lines).toBe(l.lines);
    // cli dragged 300px to the right and 10 down: still above verify
    const at = (id: string): Rect => (id === "cli" ? { ...rect(id), x: rect(id).x + 300, y: rect(id).y + 10 } : rect(id));
    const m = movedLines(l, at, new Set(["cli"]), tone, () => false);
    expect(m.lines).toHaveLength(l.lines.length);
    for (const e of l.lines) {
      const now = m.lines.find((x) => x.key === e.key)!;
      if (e.from === "cli" || e.to === "cli") expect(now.d, e.key).not.toBe(e.d);
      else expect(now.d, e.key).toBe(e.d);
    }
    // api > cli ends on cli's top where it stands now, with a head there
    const into = pieces([m.lines.find((e) => e.to === "cli")!]).slice(-1)[0];
    expect([into.x1, into.x2, into.y2]).toEqual([at("cli").x + l.boxW / 2 + 0.5, at("cli").x + l.boxW / 2 + 0.5, at("cli").y - G.arrow]);
    expect(m.heads.filter((h) => h.to === "cli")).toMatchObject([{ x: at("cli").x + l.boxW / 2 + 0.5, y: at("cli").y, from: ["api"] }]);
    // verify did not move: cli's elbow ends where its net ends on verify, in the arrowhead that is there. A moved
    // parent adds no arrowhead
    expect(m.heads.filter((h) => h.to === "verify")).toEqual(l.heads.filter((h) => h.to === "verify"));
    const out = pieces([m.lines.find((e) => e.from === "cli")!]).slice(-1)[0];
    expect([out.x1, out.y2]).toEqual([l.heads.find((h) => h.to === "verify")!.x, rect("verify").y - G.arrow]);
    // its last turn stands nearer verify's top than the level stretch the layout drew there: the two never lie
    // on each other
    const levels = pieces(l.lines.filter((e) => e.to === "verify")).filter((p) => !upright(p)).map((p) => p.y1);
    const turn = pieces([m.lines.find((e) => e.from === "cli")!]).filter((p) => !upright(p)).map((p) => p.y1);
    for (const y of turn) expect(levels.every((at) => Math.abs(at - y) >= 4), `a moved line's level at ${y}`).toBe(true);
    // the heads on the boxes that did not move are where they were
    for (const id of ["button", "docs"]) expect(m.heads.find((h) => h.to === id)).toEqual(l.heads.find((h) => h.to === id));
    expect(m.heads).toHaveLength(l.heads.length);
    // every elbow turns with a rounded corner; one elbow is two turns
    for (const e of m.lines.filter((x) => x.from === "cli" || x.to === "cli")) expect((e.d.match(/Q/g) ?? []).length).toBe(2);
    // the dash into a running child: the layout's for the edges that stayed, one drawn from the child for the moved edge
    const running = (id: string) => id === "verify" || l.flows.some((f) => f.to === id);
    const run = movedLines(l, at, new Set(["cli"]), tone, running);
    expect(run.flows.map((f) => [f.from, f.to]).sort()).toEqual([
      ["api", "button"],
      ["api", "docs"],
      ["button", "verify"],
      ["cli", "verify"],
      ["docs", "verify"],
    ]);
    for (const f of l.flows) expect(run.flows.find((x) => x.key === f.key), f.key).toEqual(f);
    const flow = run.flows.find((f) => f.from === "cli")!;
    expect(nums(flow.d).slice(0, 2)).toEqual([rect("verify").x + l.boxW / 2 + 0.5, rect("verify").y - G.arrow]);
  });

  it("still enters a moved box by its top, coming down into it, wherever it was moved: over from a parent beside it, round the side of one it stands on", () => {
    const tone = () => "done";
    const moved = new Set(["verify"]);
    const into = (r: (id: string) => Rect) => movedLines(l, r, moved, tone, () => false);
    const cases: [string, (id: string) => Rect][] = [
      // above its parents
      ["above", (id) => (id === "verify" ? { ...rect(id), y: -300 } : rect(id))],
      // beside the row of its parents, to their right, and to their left
      ["right", (id) => (id === "verify" ? { ...rect(id), x: rect("cli").x + l.boxW + 120, y: rect("cli").y } : rect(id))],
      ["left", (id) => (id === "verify" ? { ...rect(id), x: rect("button").x - l.boxW - 120, y: rect("button").y } : rect(id))],
      // on top of one of them
      ["over", (id) => (id === "verify" ? { ...rect(id), x: rect("docs").x + 20, y: rect("docs").y + 10 } : rect(id))],
      // right over one of them, 2px above it: no room between the two for a line to turn in
      ["close above", (id) => (id === "verify" ? { ...rect(id), x: rect("docs").x - 40, y: rect("docs").y - rect(id).h - 2 } : rect(id))],
      // just under one of them, 12px below it: too near for a full elbow
      ["close below", (id) => (id === "verify" ? { ...rect(id), x: rect("docs").x + 30, y: rect("docs").y + rect("docs").h + 12 } : rect(id))],
    ];
    for (const [name, r] of cases) {
      const m = into(r);
      const v = r("verify");
      // one head, on its top, for the three of them: every arrowhead points down
      expect(m.heads.filter((h) => h.to === "verify"), name).toMatchObject([{ x: v.x + v.w / 2 + 0.5, y: v.y, from: ["button", "docs", "cli"] }]);
      for (const e of m.lines.filter((x) => x.to === "verify")) {
        const ps = pieces([e]);
        const p = r(e.from);
        const beside = Math.abs(v.x + v.w / 2 - (p.x + p.w / 2)) >= (p.w + v.w) / 2 + 2 * G.keep;
        if (beside || v.y - G.arrow > p.y + p.h) {
          // out of the middle of the parent's bottom, or of its top when the box does not stand below it (just
          // under its parent, with its point under the parent's bottom: straight down from there)
          expect(upright(ps[0]), `${name}: ${e.from} leaves upright`).toBe(true);
          expect([p.x + p.w / 2 + 0.5, v.x + v.w / 2 + 0.5], `${name}: ${e.from}`).toContain(ps[0].x1);
          expect([p.y, p.y + p.h], `${name}: ${e.from} leaves its top or its bottom`).toContain(e.pts[0][1]);
        } else {
          // the box stands over its parent, or on it: out of the parent's side at its middle, and round both
          expect(upright(ps[0]), `${name}: ${e.from} leaves level`).toBe(false);
          expect([p.x, p.x + p.w], `${name}: ${e.from} leaves a side`).toContain(e.pts[0][0]);
          expect(e.pts[0][1], `${name}: ${e.from}`).toBe(Math.round(p.y + p.h / 2 - 0.5) + 0.5);
        }
        // and through neither of its two boxes (two boxes that lie on each other leave no such way)
        if (name !== "over") for (const piece of ps) for (const b of [p, v]) expect(piece.x2 > b.x + 0.5 && piece.x1 < b.x + b.w - 0.5 && piece.y2 > b.y + 0.5 && piece.y1 < b.y + b.h - 0.5, `${name}: ${e.from} runs through a box`).toBe(false);
        // into the child's top from above: the last piece is upright and ends an arrowhead short of it
        const last = ps[ps.length - 1];
        expect(upright(last), `${name}: ${e.from} enters from above`).toBe(true);
        expect([last.x1, last.y2], `${name}: ${e.from}`).toEqual([v.x + v.w / 2 + 0.5, v.y - G.arrow]);
        expect(last.y1, `${name}: ${e.from} comes down into it`).toBeLessThan(v.y - G.arrow);
        expect(e.d).not.toMatch(/NaN/);
      }
    }
    // beside its parents: each line leaves its parent's top and goes over, with two turns and no doubling back
    const beside = into(cases[1][1]);
    for (const e of beside.lines.filter((x) => x.to === "verify")) {
      expect(e.pts[0][1], e.from).toBe(rect(e.from).y);
      expect(e.pts, e.from).toHaveLength(4);
      expect(e.pts[1][1], `${e.from} goes over, above both boxes`).toBeLessThan(Math.min(rect(e.from).y, cases[1][1]("verify").y));
    }
    // beside a parent and a little lower, its top within the parent's height: straight across from the parent's
    // side that faces it, at the height the line comes in at, and down into its top. One turn, no climbing back
    const lower = (id: string): Rect => (id === "verify" ? { ...rect(id), x: rect("cli").x + l.boxW + 120, y: rect("cli").y + 50 } : rect(id));
    const side = into(lower).lines.find((e) => e.from === "cli" && e.to === "verify")!;
    const level = lower("verify").y - (G.arrow + G.r);
    expect(side.pts).toHaveLength(3);
    expect(side.pts[0]).toEqual([rect("cli").x + l.boxW, Math.round(level - 0.5) + 0.5]);
    expect(side.pts[1][1]).toBe(side.pts[0][1]);
    expect(side.pts[2]).toEqual([lower("verify").x + l.boxW / 2 + 0.5, lower("verify").y - G.arrow]);
    expect((side.d.match(/Q/g) ?? []).length).toBe(1);
    // a running child's dash rides each of its edges, from its top back
    const v = cases[1][1]("verify");
    const run = movedLines(l, cases[1][1], moved, tone, (id) => id === "verify");
    expect(run.flows.filter((f) => f.to === "verify")).toHaveLength(3);
    for (const f of run.flows.filter((x) => x.to === "verify")) expect(nums(f.d).slice(0, 2)).toEqual([v.x + v.w / 2 + 0.5, v.y - G.arrow]);
  });

  it("runs the line of a parent dragged beside its child across from the parent's side, whatever point the line ends on; a child moved off a parent keeps the parent's one way out", () => {
    const through = (e: { d: string; net: string }, boxes: Rect[]) => pieces([e]).some((piece) => boxes.some((b) => piece.x2 > b.x + 0.5 && piece.x1 < b.x + b.w - 0.5 && piece.y2 > b.y + 0.5 && piece.y1 < b.y + b.h - 0.5));
    // two fans into one child: c2's two points stand off its middle. p1 dragged down beside c2, 18px left of it
    const fans = lay(dag([node("p1"), node("p2"), node("c1", ["p1"]), node("c2", ["p1", "p2"]), node("c3", ["p2"])]), 528);
    const c2 = fans.at.get("c2")!;
    for (const dy of [-40, -20, 0, 20]) {
      const at = (id: string): Rect => (id === "p1" ? { ...fans.at.get(id)!, x: c2.x - fans.boxW - 18, y: c2.y + dy } : fans.at.get(id)!);
      const m = movedLines(fans, at, new Set(["p1"]), () => "done", () => false);
      const e = m.lines.find((x) => x.from === "p1" && x.to === "c2")!;
      expect(through(e, [at("p1"), at("c2")]), `p1 ${dy}px off c2's top: ${JSON.stringify(e.pts)}`).toBe(false);
      expect(e.pts[e.pts.length - 1]).toEqual([fans.heads.find((h) => h.to === "c2" && h.from.includes("p1"))!.x, c2.y - G.arrow]);
    }
    // a parent whose line leaves off its middle (over its lane): a child of it dragged away still starts there
    const deps: Record<string, string[]> = { n5: ["n1"], n6: ["n0", "n4"], n7: ["n2"], n8: ["n3", "n6"], n9: ["n0"], n10: ["n8"], n11: ["n1", "n4", "n9"], n12: ["n5", "n9"], n13: ["n3", "n5", "n7"], n14: ["n1", "n4"] };
    const l = lay(dag(Array.from({ length: 15 }, (_, i) => node(`n${i}`, deps[`n${i}`] ?? []))), 528);
    const off = l.lines.find((e) => Math.abs(e.pts[0][0] - (l.at.get(e.from)!.x + l.boxW / 2)) > 1)!;
    expect(off, "a line leaves a parent off its middle").toBeDefined();
    const at = (id: string): Rect => (id === off.to ? { ...l.at.get(id)!, x: l.at.get(id)!.x + 40, y: l.at.get(id)!.y + 30 } : l.at.get(id)!);
    const m = movedLines(l, at, new Set([off.to]), () => "done", () => false);
    expect(new Set(m.lines.filter((e) => e.from === off.from).map((e) => e.pts[0][0]))).toEqual(new Set([off.pts[0][0]]));
  });

  it("cuts the dash of a moved line where another child's already rides: two dashes out of step never lie on one stretch, moved or not", () => {
    // a leads to x and y, both running, and with b, c and q to z; a is dragged up: its two elbows share its line down
    const run = dag([node("a"), node("b"), node("c"), node("q"), node("x", ["a"], { state: "running", model: "gpt-6.1" }), node("y", ["a"], { state: "running", model: "gpt-6.1" }), node("z", ["a", "b", "c", "q"], { state: "waiting" })]);
    const g = lay(run, 1100);
    const at = (id: string): Rect => (id === "a" ? { ...g.at.get(id)!, y: g.at.get(id)!.y - 170 } : g.at.get(id)!);
    const m = movedLines(g, at, new Set(["a"]), () => "done", (id) => id === "x" || id === "y");
    const flows = m.flows.filter((f) => f.from === "a");
    expect(flows.map((f) => f.to).sort()).toEqual(["x", "y"]);
    const shared = (a: Seg, b: Seg) => (upright(a) && upright(b) && a.x1 === b.x1 ? Math.min(a.y2, b.y2) - Math.max(a.y1, b.y1) : !upright(a) && !upright(b) && a.y1 === b.y1 ? Math.min(a.x2, b.x2) - Math.max(a.x1, b.x1) : 0);
    const [first, second] = flows.map((f) => pieces([f]));
    first.forEach((p) => second.forEach((q) => expect(shared(p, q)).toBeLessThanOrEqual(0.01)));
    // the two lines themselves do share a's line down: that is what the second dash stops short of
    const [lx, ly] = ["x", "y"].map((id) => pieces([m.lines.find((e) => e.from === "a" && e.to === id)!]));
    expect(lx.some((p) => ly.some((q) => shared(p, q) > 1))).toBe(true);
  });

  it("draws the gaps again where lines cross once a box has moved: none is left where nothing crosses any more", () => {
    // p1 leads to c1..c3 and p2 to c2..c4: a line of the one passes over the other's level stretch, with a gap
    const run = dag([node("p1"), node("p2"), node("c1", ["p1"]), node("c2", ["p1", "p2"]), node("c3", ["p1", "p2"]), node("c4", ["p2"])]);
    const g = lay(run, 1136);
    const at = (id: string): Rect => g.at.get(id)!;
    const gapsIn = (d: string) => [...d.matchAll(/V([\d.]+) M[\d.]+,([\d.]+)/g)].map((m) => (Number(m[1]) + Number(m[2])) / 2);
    const skip = g.lines.find((e) => gapsIn(e.d).length > 0)!;
    const was = gapsIn(skip.d);
    // the other fan's parent dragged far up and to the right: none of its lines runs where it did, and the line
    // that passed over its level stretch has nothing to pass over where its gap was
    const far = new Set(g.nets.find((n) => n.key !== skip.net)!.parents);
    const moved = (id: string): Rect => (far.has(id) ? { ...at(id), x: at(id).x + 700, y: at(id).y - 200 } : at(id));
    const m = movedLines(g, moved, far, () => "done", () => false);
    const now = m.lines.find((e) => e.key === skip.key)!;
    for (const y of was) expect(gapsIn(now.d).some((v) => Math.abs(v - y) < 0.1), `the gap at ${y} is gone`).toBe(false);
    // every gap that is left sits on a level stretch of another net that really crosses there
    const levels = pieces(m.lines).filter((p) => !upright(p));
    for (const e of m.lines)
      for (const m2 of e.d.matchAll(/V([\d.]+) M([\d.]+),([\d.]+)/g)) {
        const [x, y] = [Number(m2[2]), (Number(m2[1]) + Number(m2[3])) / 2];
        expect(levels.some((p) => p.net !== e.net && Math.abs(p.y1 - y) < 0.1 && p.x1 < x && x < p.x2), `${e.key} has a gap at ${x},${y} with nothing crossing`).toBe(true);
      }
    // and every crossing has one: a moved line too
    const ups = pieces(m.lines).filter(upright);
    for (const v of ups)
      for (const h of levels)
        if (h.net !== v.net && h.x1 < v.x1 - 0.5 && v.x1 < h.x2 - 0.5 && v.y1 < h.y1 - 0.5 && h.y1 < v.y2 - 0.5 && h.x2 - h.x1 > G.r) throw new Error(`${v.net} crosses ${h.net} at ${v.x1},${h.y1} without a gap`);
    expect(now.pts).toEqual(skip.pts); // it did not move
  });
});
