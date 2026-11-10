// The OMH TUI's box view of a run, laid out for the desktop. The spec is the TUI's own drawing
// (src/plugin_bundle/omh/delegation_view.py): the nodes stand in frontiers, every box is one width and four lines
// (title; category · model; glyph, status and time; parents or "Start node"), the edges between two frontiers are
// drawn (a line under each parent's middle, a bus joining a group of parents to its children, a head over each
// child's middle) only when every parent of a group leads to every child, and one centred connector of its own
// marks joins two frontiers whose edges cannot be drawn so (an edge that skips a frontier, a frontier that wraps,
// two groups that would share the bus). Widths are character cells, as in the TUI; the caller turns them into
// pixels with its font's cell width. Pure: no DOM, no clock.
//
// What differs from the TUI, on purpose, so that more of a run's edges are drawn as lines in a 60-cell side panel:
// - a frontier that has to wrap packs as many boxes per row as the minimum box allows (the TUI keeps the widest
//   box and may end with one a row);
// - inside a frontier a node stands under the middle of its parents (the TUI keeps the run's order);
// - an edge another path already implies (A → C beside A → B → C) is not drawn as a line: it stays in the box's
//   parents line and under Dependencies;
// - a dependency on a failed node that has repairs is an edge from those repairs, which is what the dependent
//   waits on;
// - a duration reads as everywhere else in the app (`span`: "38s", "14m", "2h 5m").
import type { AgentRun, RunNode } from "../lib/runs";
import { isRepaired, nodeModel, span } from "../lib/runs";
import { t } from "../i18n";

export const GAP = 2; // cells between two boxes of a row
export const BOX_INNER_MIN = 22; // a box's lines are cut down to this many cells, and no further
export const BOX_INNER_MAX = 48; // and a box is never drawn wider
export const BOX_MIN_WIDTH = BOX_INNER_MIN + 4;
/** The 12px mark before a title and the space after it, in cells. */
export const MARK_CELLS = 3;
/** The least a duration counts when a box is measured ("23h 59m"), so a ticking clock never resizes the boxes. */
const DURATION_CELLS = 7;
const ELLIPSIS = "…";

/** Pixel sizes of the drawing that do not come from the font. */
export const GEOMETRY = {
  padY: 5, // above the first line and under the last
  border: 1,
  rowGap: 10, // between two rows of one wrapped frontier
  labelH: 18, // the "· Same frontier" line under a frontier of several boxes
  moreH: 22, // the "+76 more · Show all 88" line under a capped frontier
  stub: 14, // from a parent's bottom (or its frontier's label) down to the bus
  drop: 22, // from the bus down to a child's top, arrowhead included
  arrow: 6, // the arrowhead's height; it is 8 wide
  r: 4, // the bus's rounded ends
};

export type Tone = "done" | "running" | "out" | "failed" | "repaired" | "retry" | "waiting" | "off";

// ---- text in cells ----

/** 2 for a wide (CJK, Hangul, fullwidth, emoji) character, 1 for any other: how a monospace font sets it. */
export function charCells(ch: string): number {
  const c = ch.codePointAt(0) ?? 0;
  if (c < 0x1100) return 1;
  return c <= 0x115f ||
    (c >= 0x2e80 && c <= 0xa4cf) ||
    (c >= 0xac00 && c <= 0xd7a3) ||
    (c >= 0xf900 && c <= 0xfaff) ||
    (c >= 0xfe30 && c <= 0xfe4f) ||
    (c >= 0xff00 && c <= 0xff60) ||
    (c >= 0xffe0 && c <= 0xffe6) ||
    (c >= 0x1f300 && c <= 0x1faff) ||
    (c >= 0x20000 && c <= 0x3fffd)
    ? 2
    : 1;
}
export function cells(text: string): number {
  let n = 0;
  for (const ch of text) n += charCells(ch);
  return n;
}
/** `text` cut to at most `width` cells, ending in "…" when it was cut. */
export function fit(text: string, width: number): string {
  if (width <= 0) return "";
  if (cells(text) <= width) return text;
  const room = width - 1;
  if (room <= 0) return ELLIPSIS;
  let kept = "";
  let used = 0;
  for (const ch of text) {
    const size = charCells(ch);
    if (used + size > room) break;
    kept += ch;
    used += size;
  }
  return kept.trimEnd() + ELLIPSIS;
}
/** `text` in `width` cells, cut in the middle at word boundaries: its start, " … ", then its end, so the part that
 *  tells two titles apart ("… (Hermes)", "· part 3") stays. Whole when it fits; cut at its end where no word
 *  boundary leaves both halves a word. */
export function middleCut(text: string, width: number): string {
  if (cells(text) <= width) return text;
  const joint = ` ${ELLIPSIS} `;
  const room = width - cells(joint);
  if (room < 8) return fit(text, Math.max(width, 1));
  const headRoom = room - Math.floor((room * 2) / 5);
  const chars = [...text];
  let head = "";
  for (const ch of chars) {
    if (cells(head + ch) > headRoom) break;
    head += ch;
  }
  if (head.slice(Math.floor(head.length / 2)).includes(" ")) head = head.slice(0, head.lastIndexOf(" "));
  let tail = "";
  const rest = [...text.slice(head.length)];
  for (let i = rest.length - 1; i >= 0; i--) {
    if (cells(tail) + cells(rest[i]) > room - cells(head)) break;
    tail = rest[i] + tail;
  }
  if (tail.slice(0, Math.floor(tail.length / 2) + 1).includes(" ")) tail = tail.slice(tail.indexOf(" ") + 1);
  head = head.replace(/[ ,;:·\-—(]+$/, "");
  tail = tail.replace(/^[ ·]+/, "");
  if (!head || !tail) return fit(text, Math.max(width, 1));
  return `${head}${joint}${tail}`;
}

/** The model as a box names it: provider path dropped, a leading "claude-" dropped ("opus-5-5"). */
export function shortModel(model: string): string {
  const name = model.slice(model.lastIndexOf("/") + 1);
  return name.startsWith("claude-") && name.length > "claude-".length ? name.slice("claude-".length) : name;
}

// ---- a node's four lines ----

const clean = (s: string | undefined) => (s ?? "").replace(/\s+/g, " ").trim();
export const titleOf = (n: Pick<RunNode, "label">) => clean(n.label) || t("graph.untitled");

/** "quick" and "glm-5.3-flash:low": the category the node went out under, and what it ran on (or goes to). The
 *  bot's own model is not named here: it is the header's, and the node's mark already falls back to it. */
export function factsOf(n: RunNode): { cat: string; model: string } {
  const cat = clean(n.route ?? n.category);
  const m = nodeModel(n);
  if (!m) return { cat, model: "" };
  const effort = m.source === "ran" ? n.effort : m.source === "route" ? n.planned?.effort : undefined;
  const name = shortModel(clean(m.model));
  return { cat, model: effort && name ? `${name}:${effort}` : name };
}

export interface Status {
  glyph: string;
  word: string;
  /** Whether the line carries the node's duration after the word. */
  timed: boolean;
  /** After the duration, where the line still fits whole (" · repaired"). */
  note: string;
  tone: Tone;
}
const satisfied = (n: RunNode, all: RunNode[]) => n.state === "done" || isRepaired(n, all);

/** The status line's glyph, word and colour. A dag node that is out with no helper seen yet is "Handed out". */
export function statusOf(n: RunNode, run: Pick<AgentRun, "kind" | "nodes">): Status {
  const timed = n.started !== undefined;
  switch (n.state) {
    case "done":
      return { glyph: "✓", word: t(run.kind === "dag" ? "graph.accepted" : "graph.finished"), timed, note: "", tone: "done" };
    case "running":
      return run.kind !== "dag" || n.model || n.executor
        ? { glyph: "●", word: t("graph.running"), timed, note: "", tone: "running" }
        : { glyph: "◌", word: t("graph.handed"), timed: false, note: "", tone: "out" };
    case "failed":
      return isRepaired(n, run.nodes)
        ? { glyph: "✗", word: t("graph.failed"), timed, note: t("graph.repaired"), tone: "repaired" }
        : { glyph: "✗", word: t("graph.failed"), timed, note: "", tone: "failed" };
    case "blocked":
      return isRepaired(n, run.nodes)
        ? { glyph: "!", word: t("graph.blocked"), timed: false, note: t("graph.repaired"), tone: "repaired" }
        : { glyph: "!", word: t("graph.blocked"), timed: false, note: "", tone: "failed" };
    case "parked":
      return { glyph: "○", word: t("graph.parked"), timed: false, note: "", tone: "retry" };
    case "cancelled":
      return { glyph: "▪", word: t("graph.cancelled"), timed: false, note: "", tone: "off" };
    default: {
      if (n.attempts.length) return { glyph: "○", word: t("graph.retry"), timed: false, note: "", tone: "retry" };
      const byId = new Map(run.nodes.map((m) => [m.id, m]));
      const unmet = n.deps.filter((d) => byId.has(d) && !satisfied(byId.get(d)!, run.nodes)).length;
      const word = unmet ? t(unmet === 1 ? "graph.waits.one" : "graph.waits", { n: unmet }) : t("graph.waiting");
      return { glyph: "○", word, timed: false, note: "", tone: "waiting" };
    }
  }
}
export const durationOf = (n: RunNode, nowS: number) => (n.started === undefined ? "" : span((n.ended ?? nowS) - n.started));
/** "1.2k": a token count in at most four characters and a unit. */
export function compactCount(value: number): string {
  for (const [size, suffix] of [
    [1e12, "T"],
    [1e9, "B"],
    [1e6, "M"],
    [1e3, "k"],
  ] as const)
    if (value >= size) return `${(value / size).toFixed(1).replace(/\.0$/, "")}${suffix}`;
  return String(Math.floor(value));
}

export interface BoxText {
  /** "↻ " before the title of a node added to repair another. */
  origin: string;
  title: string;
  cat: string;
  model: string;
  glyph: string;
  /** "Accepted 12s": the word and the duration. */
  status: string;
  /** " · ↓1.2k" or " · repaired", only where the status line fits whole with it. */
  after: string;
  /** "← Export API, Export docs", or "Start node". */
  parents: string;
  tone: Tone;
}

/** A box's four lines, each cut to `inner` cells. */
export function boxText(n: RunNode, run: Pick<AgentRun, "kind" | "nodes">, shape: Frontiers, inner: number, nowS: number): BoxText {
  const st = statusOf(n, run);
  const origin = shape.origin.has(n.id) ? "↻ " : "";
  const title = middleCut(titleOf(n), inner - MARK_CELLS - cells(origin));
  const facts = factsOf(n);
  const cat = fit(facts.cat, inner);
  const sep = cat && facts.model ? " · " : "";
  const model = facts.model ? fit(facts.model, Math.max(0, inner - cells(cat) - cells(sep))) : "";
  const time = st.timed ? durationOf(n, nowS) : "";
  const status = fit(time ? `${st.word} ${time}` : st.word, inner - 2);
  // whole or not at all: a count or a note never ends in "…"
  const extras = [st.note, n.tokens && n.tokens > 0 ? `↓${compactCount(n.tokens)}` : ""].filter(Boolean);
  let after = "";
  for (const extra of extras) if (2 + cells(status) + cells(after) + 3 + cells(extra) <= inner) after += ` · ${extra}`;
  const byId = new Map(run.nodes.map((m) => [m.id, m]));
  const named = (shape.parents.get(n.id) ?? []).map((id) => titleOf(byId.get(id)!));
  const parents = named.length ? fit(`← ${named.join(", ")}`, inner) : t("graph.start");
  return { origin, title, cat, model: model ? `${sep}${model}` : "", glyph: st.glyph, status, after, parents, tone: st.tone };
}

// ---- frontiers ----

export interface EdgeRec {
  from: string;
  to: string;
  /** "dep": a dependency; "repair": from a failed node to the node added to repair it. */
  kind: "dep" | "repair";
}
export interface Frontiers {
  /** The frontiers, first to last, each ordered so that a node stands under its parents. */
  rows: string[][];
  layer: Map<string, number>;
  /** Per node, the nodes it has an edge from, in frontier and drawing order. */
  parents: Map<string, string[]>;
  /** Every edge between two nodes, in reading order: the parents lines and the Dependencies list. */
  edges: EdgeRec[];
  /** The edges the lines draw: `edges` without the ones a longer path already implies. */
  drawn: EdgeRec[];
  /** A node added mid-run to repair another. */
  origin: Map<string, "repair">;
}

/** Each node's layer: the round after the last of its parents was placed (its longest path from a node with no
 *  parent). Nodes on a cycle, or below one, are left out. */
function layerOf(ids: string[], pairs: EdgeRec[]): Map<string, number> {
  const parents = new Map<string, Set<string>>();
  for (const e of pairs) (parents.get(e.to) ?? parents.set(e.to, new Set()).get(e.to)!).add(e.from);
  const placed = new Map<string, number>();
  let remaining = ids;
  for (let depth = 0; remaining.length; depth++) {
    const ready = remaining.filter((id) => [...(parents.get(id) ?? [])].every((p) => placed.has(p)));
    if (!ready.length) break;
    for (const id of ready) placed.set(id, depth);
    remaining = remaining.filter((id) => !placed.has(id));
  }
  return placed;
}

/** The run's edges. A dependency on a failed node that has repairs is an edge from those repairs instead: OMH
 *  counts a failed node whose repairs are done as satisfied, so the repairs are what the dependent waits on
 *  (`reroute` off: the dependencies exactly as recorded). */
function edgesOf(nodes: RunNode[], reroute: boolean): EdgeRec[] {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const repairs = new Map<string, string[]>();
  for (const n of nodes) if (n.repairOf && byId.has(n.repairOf) && n.repairOf !== n.id) (repairs.get(n.repairOf) ?? repairs.set(n.repairOf, []).get(n.repairOf)!).push(n.id);
  const pairs: EdgeRec[] = [];
  const seen = new Set<string>();
  const add = (from: string, to: string, kind: EdgeRec["kind"]) => {
    if (from === to || !byId.has(from) || seen.has(`${from}\n${to}`)) return;
    seen.add(`${from}\n${to}`);
    pairs.push({ from, to, kind });
  };
  for (const n of nodes) {
    if (n.repairOf) add(n.repairOf, n.id, "repair");
    for (const d of n.deps) {
      const src = byId.get(d);
      if (!src) continue;
      const via = reroute && (src.state === "failed" || src.state === "blocked") && n.repairOf !== d ? (repairs.get(d) ?? []).filter((r) => r !== n.id) : [];
      if (via.length) for (const r of via) add(r, n.id, "dep");
      else add(d, n.id, "dep");
    }
  }
  return pairs;
}

/** The nodes by frontier. A node's frontier is its longest path of edges (a dependency, a repair) from a node with
 *  none; inside a frontier a node stands under the middle of its parents, so that the lines between two frontiers
 *  can be drawn without crossing. */
export function frontiers(nodes: RunNode[]): Frontiers {
  const ids = nodes.map((n) => n.id);
  let pairs = edgesOf(nodes, true);
  let layer = layerOf(ids, pairs);
  if (layer.size < ids.length) {
    // waiting on the repairs would loop: the dependencies as recorded
    pairs = edgesOf(nodes, false);
    layer = layerOf(ids, pairs);
  }
  // a loop in the recorded edges themselves: what could not be placed stands in one last frontier
  const last = Math.max(-1, ...layer.values()) + 1;
  for (const id of ids) if (!layer.has(id)) layer.set(id, last);
  // a node nothing leads to stands just above the first node that waits on it, so its edges join two neighbouring
  // frontiers and can be drawn (three independent parts and a closing check are one row over the check)
  const has = new Set(pairs.map((e) => e.to));
  for (const id of ids) {
    if (has.has(id)) continue;
    const kids = pairs.filter((e) => e.from === id).map((e) => layer.get(e.to)!);
    if (kids.length) layer.set(id, Math.min(...kids) - 1);
  }
  let rows: string[][] = [];
  for (const id of ids) (rows[layer.get(id)!] ??= []).push(id);
  rows = Array.from(rows, (r) => r ?? []).filter((r) => r.length);
  rows.forEach((row, l) => row.forEach((id) => layer.set(id, l)));

  const above = new Map<string, string[]>(ids.map((id) => [id, []]));
  const under = new Map<string, string[]>(ids.map((id) => [id, []]));
  for (const e of pairs) {
    above.get(e.to)!.push(e.from);
    under.get(e.from)!.push(e.to);
  }
  // order: each node by the mean position of its neighbours in the frontiers already ordered (down, up, down);
  // a node with none there keeps its place
  const sweep = (down: boolean) => {
    const where = new Map<string, number>();
    const place = (row: string[]) => row.forEach((id, i) => where.set(id, (i + 0.5) / row.length));
    rows.forEach(place);
    const order = down ? rows.map((_, i) => i).slice(1) : rows.map((_, i) => i).reverse().slice(1);
    for (const l of order) {
      const key = new Map<string, number>();
      rows[l].forEach((id, i) => {
        const near = (down ? above : under).get(id)!.map((o) => where.get(o)!);
        key.set(id, near.length ? near.reduce((a, b) => a + b, 0) / near.length : (i + 0.5) / rows[l].length);
      });
      rows[l] = rows[l].map((id, i) => [id, i] as const).sort((a, b) => key.get(a[0])! - key.get(b[0])! || a[1] - b[1]).map(([id]) => id);
      place(rows[l]);
    }
  };
  sweep(true);
  sweep(false);
  sweep(true);

  const rank = new Map<string, number>();
  rows.forEach((row, l) => row.forEach((id, at) => rank.set(id, l * 100000 + at)));
  const parents = new Map<string, string[]>(ids.map((id) => [id, [...above.get(id)!].sort((a, b) => rank.get(a)! - rank.get(b)!)]));
  const edges = [...pairs].sort((a, b) => rank.get(a.from)! - rank.get(b.from)! || rank.get(a.to)! - rank.get(b.to)!);
  // an edge another path already implies (A → C beside A → B → C) is not drawn
  const reaches = (from: string, to: string, seen = new Set<string>()): boolean => {
    if (from === to) return true;
    if (seen.has(from)) return false;
    seen.add(from);
    return under.get(from)!.some((next) => reaches(next, to, seen));
  };
  const drawn = edges.filter((e) => !under.get(e.from)!.some((other) => other !== e.to && reaches(other, e.to)));
  const origin = new Map<string, "repair">();
  for (const e of edges) if (e.kind === "repair") origin.set(e.to, "repair");
  return { rows, layer, parents, edges, drawn, origin };
}

// ---- the layout ----

export interface Metrics {
  /** One character cell's width, px. */
  cw: number;
  /** One text line's height, px. */
  line: number;
}
export interface BoxAt {
  id: string;
  x: number;
  y: number;
  frontier: number;
  /** The order the boxes appear in: frontier by frontier, left to right. */
  index: number;
}
/** Some of the edges of one frontier gap, drawn as one bus: every parent of the group leads to every child. */
export interface Group {
  gap: number;
  parents: string[];
  children: string[];
  /** Where the bus meets a child that several buses lead into: px from the child's middle (0 when it is the only
   *  one). */
  ports: Record<string, number>;
}
/** Cells between two buses' ports on one child. */
const PORT_CELLS = 2;
/** A frontier gap whose edges are not drawn: one centred connector in its own marks (the TUI's "╎" over "▽"). */
export interface Undrawn {
  gap: number;
  x: number;
  y1: number;
  y2: number;
}
export interface BoxLayout {
  /** A box's inner width in cells; every box is `inner + 4` cells wide. */
  inner: number;
  perRow: number;
  boxW: number;
  boxH: number;
  w: number;
  h: number;
  boxes: BoxAt[];
  at: Map<string, BoxAt>;
  /** "· Same frontier", under each frontier of several boxes. */
  labels: { frontier: number; x: number; y: number }[];
  /** A capped frontier's "+76 more · Show all 88" line. */
  more: { frontier: number; hidden: number; total: number; x: number; y: number }[];
  groups: Group[];
  undrawn: Undrawn[];
  shape: Frontiers;
}
export interface LayoutOpts {
  /** The width to draw into, in cells. */
  cells: number;
  metrics: Metrics;
  /** A frontier of more rows than this shows this many (running, then failed, then the rest) and a "Show all" line. */
  capRows?: number;
  /** The frontiers the person opened with "Show all". */
  opened?: Set<number>;
}

const RANK: Record<RunNode["state"], number> = { running: 0, failed: 1, blocked: 1, waiting: 2, parked: 2, done: 3, cancelled: 4 };

/** The inner width a box needs for its title (after its mark), its facts and its status with a duration. */
function natural(n: RunNode, run: Pick<AgentRun, "kind" | "nodes">, shape: Frontiers): number {
  const st = statusOf(n, run);
  const facts = factsOf(n);
  return Math.max(
    MARK_CELLS + (shape.origin.has(n.id) ? 2 : 0) + cells(titleOf(n)),
    2 + cells(st.word) + (st.timed ? 1 + DURATION_CELLS : 0),
    cells(facts.cat) + (facts.cat && facts.model ? 3 : 0) + cells(facts.model),
  );
}

export const boxHeight = (m: Metrics) => 4 * m.line + 2 * GEOMETRY.padY + 2 * GEOMETRY.border;

/** Where every box stands, and which frontier gaps draw their edges. */
export function layoutBoxes(run: Pick<AgentRun, "kind" | "nodes">, o: LayoutOpts): BoxLayout {
  const shape = frontiers(run.nodes);
  const byId = new Map(run.nodes.map((n) => [n.id, n]));
  const W = Math.max(BOX_MIN_WIDTH, Math.floor(o.cells));
  const need = Math.max(BOX_INNER_MIN, ...run.nodes.map((n) => natural(n, run, shape)));
  const oneRow = shape.rows.map((row) => Math.floor((W - (row.length - 1) * GAP) / row.length) - 4);
  let inner = Math.min(need, BOX_INNER_MAX, W - 4, ...oneRow.filter((f) => f >= BOX_INNER_MIN));
  const longest = Math.max(1, ...shape.rows.map((r) => r.length));
  if (longest > Math.max(1, Math.floor((W + GAP) / (inner + 4 + GAP)))) {
    // a frontier wraps: as many boxes per row as the minimum box allows, each as wide as that leaves
    const most = Math.min(longest, Math.max(1, Math.floor((W + GAP) / (BOX_MIN_WIDTH + GAP))));
    inner = Math.min(inner, Math.floor((W - (most - 1) * GAP) / most) - 4);
  }
  const boxCells = inner + 4;
  const perRow = Math.max(1, Math.floor((W + GAP) / (boxCells + GAP)));
  const widest = Math.min(perRow, longest);
  const spanCells = widest * boxCells + (widest - 1) * GAP;
  const { cw } = o.metrics;
  const boxW = boxCells * cw;
  const boxH = boxHeight(o.metrics);

  const boxes: BoxAt[] = [];
  const labels: BoxLayout["labels"] = [];
  const more: BoxLayout["more"] = [];
  const middle = new Map<string, number>(); // the cell under each box's middle, in a frontier drawn on one row
  const top: number[] = []; // each frontier's first row
  const bottom: number[] = []; // under each frontier's last row
  let y = 0;
  shape.rows.forEach((frontier, fi) => {
    let shown = frontier;
    const rowsOf = Math.ceil(frontier.length / perRow);
    // "Show all" only when it hides more than a row or two
    if (o.capRows && rowsOf > o.capRows + 2 && !o.opened?.has(fi)) {
      shown = frontier
        .map((id, i) => [id, i] as const)
        .sort((a, b) => RANK[byId.get(a[0])!.state] - RANK[byId.get(b[0])!.state] || a[1] - b[1])
        .slice(0, o.capRows * perRow)
        .map(([id]) => id);
    }
    // a frontier is centred; one that wraps keeps the column its first row starts at, so it reads as one grid
    const offset = Math.floor((spanCells - Math.min(perRow, shown.length) * (boxCells + GAP) + GAP) / 2);
    if (shown.length <= perRow && shown.length === frontier.length)
      shown.forEach((id, at) => middle.set(id, offset + Math.floor(boxCells / 2) + at * (boxCells + GAP)));
    top[fi] = y;
    for (let start = 0; start < shown.length; start += perRow) {
      if (start) y += GEOMETRY.rowGap;
      shown.slice(start, start + perRow).forEach((id, col) => boxes.push({ id, x: (offset + col * (boxCells + GAP)) * cw, y, frontier: fi, index: boxes.length }));
      y += boxH;
    }
    bottom[fi] = y;
    if (frontier.length > 1) {
      labels.push({ frontier: fi, x: offset * cw, y });
      y += GEOMETRY.labelH;
    }
    if (shown.length < frontier.length || (o.capRows && rowsOf > o.capRows + 2)) {
      more.push({ frontier: fi, hidden: frontier.length - shown.length, total: frontier.length, x: offset * cw, y });
      y += GEOMETRY.moreH;
    }
    if (fi < shape.rows.length - 1) y += GEOMETRY.stub + GEOMETRY.drop;
  });

  const groups: Group[] = [];
  const undrawn: Undrawn[] = [];
  for (let gap = 0; gap < shape.rows.length - 1; gap++) {
    const drawn = gapGroups(shape, gap, middle);
    if (drawn) groups.push(...drawn.map((g) => ({ gap, parents: g.parents, children: g.children, ports: Object.fromEntries(Object.entries(g.ports).map(([id, c]) => [id, c * cw])) })));
    else undrawn.push({ gap, x: (spanCells * cw) / 2, y1: top[gap + 1] - GEOMETRY.stub - GEOMETRY.drop + 4, y2: top[gap + 1] });
  }
  return { inner, perRow, boxW, boxH, w: spanCells * cw, h: y, boxes, at: new Map(boxes.map((b) => [b.id, b])), labels, more, groups, undrawn, shape };
}

/** The edges from frontier `upper` to the next as buses: the parents that lead to the same children share one, and
 *  a child several buses lead into takes each at its own port. Null where the gap cannot be drawn so: it holds no
 *  edge, an edge into or out of it skips a frontier, either frontier wraps, or two buses would share a stretch of
 *  the gap (their lines would cross). */
function gapGroups(shape: Frontiers, upper: number, middle: Map<string, number>): { parents: string[]; children: string[]; ports: Record<string, number> }[] | null {
  const L = (id: string) => shape.layer.get(id)!;
  const at = (id: string) => middle.get(id)!;
  const crossing = shape.drawn.filter((e) => L(e.from) <= upper && upper < L(e.to));
  if (!crossing.length) return null;
  if (crossing.some((e) => L(e.from) !== upper || L(e.to) !== upper + 1 || !middle.has(e.from) || !middle.has(e.to))) return null;
  const kids = new Map<string, string[]>();
  for (const e of crossing) (kids.get(e.from) ?? kids.set(e.from, []).get(e.from)!).push(e.to);
  const bySet = new Map<string, { parents: string[]; children: string[]; ports: Record<string, number> }>();
  for (const [parent, children] of kids) {
    const sorted = [...children].sort((a, b) => at(a) - at(b));
    const key = sorted.join("\n");
    (bySet.get(key) ?? bySet.set(key, { parents: [], children: sorted, ports: {} }).get(key)!).parents.push(parent);
  }
  const mean = (ids: string[]) => ids.reduce((a, id) => a + at(id), 0) / ids.length;
  const groups = [...bySet.values()].sort((a, b) => mean(a.parents) - mean(b.parents) || mean(a.children) - mean(b.children));
  for (const g of groups) g.parents.sort((a, b) => at(a) - at(b));
  // ports: the buses into one child, left to right in the order of where they come from
  const into = new Map<string, (typeof groups)[number][]>();
  for (const g of groups) for (const c of g.children) (into.get(c) ?? into.set(c, []).get(c)!).push(g);
  for (const [child, gs] of into) gs.forEach((g, i) => (g.ports[child] = (i - (gs.length - 1) / 2) * PORT_CELLS));
  const spans = groups
    .map((g) => {
      const xs = [...g.parents.map(at), ...g.children.map((c) => at(c) + g.ports[c])];
      return [Math.min(...xs), Math.max(...xs)] as const;
    })
    .sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  if (spans.some((span, i) => i > 0 && spans[i - 1][1] >= span[0] - 0.5)) return null;
  return groups;
}

// ---- edges as lines ----

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}
export interface EdgeLine {
  key: string;
  d: string;
  /** The nodes this line leaves and the nodes it leads to: hovering any of them lights it. */
  from: string[];
  to: string[];
  /** The parent whose state colours it; null where parents of different states share the line. */
  tone: string | null;
  /** It leads into a running node: the slow dash. */
  flow: boolean;
}
export interface EdgeHead {
  key: string;
  /** The tip, on the child's border. */
  x: number;
  y: number;
  /** Pointing down into the child's top, or up into its bottom (a child dragged above its parents). */
  up: boolean;
  from: string[];
  to: string;
  tone: string | null;
  flow: boolean;
}

/** One group's lines and arrowheads between the boxes as they stand now (dragged ones included): a line from each
 *  parent to the bus, the bus, and a line with a head into each child. One parent over one child is one line. */
export function routeGroup(g: Group, rect: (id: string) => Rect, tone: (id: string) => string, running: (id: string) => boolean): { lines: EdgeLine[]; heads: EdgeHead[] } {
  const { drop, arrow, r } = GEOMETRY;
  const P = g.parents.map((id) => ({ id, ...rect(id) }));
  const C = g.children.map((id) => ({ id, ...rect(id) }));
  // lines sit on half pixels, so a 1px stroke is one crisp pixel
  const snap = (v: number) => Math.round(v) + 0.5;
  const mid = (b: Rect & { id?: string }, port = 0) => snap(b.x + b.w / 2 + port);
  const into = (c: Rect & { id: string }) => mid(c, g.ports[c.id] ?? 0);
  const lowest = Math.max(...P.map((b) => b.y + b.h));
  const highest = Math.min(...C.map((b) => b.y));
  // the bus: a drop above the children; between the two rows when a dragged box leaves no room for that
  const busY = snap(highest - drop > lowest + 2 ? highest - drop : highest > lowest ? (lowest + highest) / 2 : (Math.min(...P.map((b) => b.y)) + Math.max(...C.map((b) => b.y + b.h))) / 2);
  const tones = new Set(g.parents.map(tone));
  const shared = tones.size === 1 ? [...tones][0] : null;
  const lines: EdgeLine[] = [];
  const heads: EdgeHead[] = [];
  const key = `${g.gap}:${g.parents[0]}>${g.children[0]}`;
  const head = (c: (typeof C)[number], t: string | null) => {
    const up = c.y + c.h <= busY;
    heads.push({ key: `${key}:h:${c.id}`, x: into(c), y: up ? c.y + c.h : c.y, up, from: g.parents, to: c.id, tone: t, flow: running(c.id) });
    return up ? c.y + c.h + arrow : c.y - arrow;
  };
  const xs = [...P.map((p) => mid(p)), ...C.map(into)];
  const first = Math.min(...xs);
  const last = Math.max(...xs);
  if (last - first < 0.5) {
    // straight down: no bus to draw
    const flow = C.some((c) => running(c.id));
    for (const c of C) {
      const end = head(c, shared);
      const p = P[0];
      const start = p.y + p.h <= busY ? p.y + p.h : p.y;
      lines.push({ key: `${key}:s:${c.id}`, d: `M${into(c)},${start} V${end}`, from: g.parents, to: [c.id], tone: shared, flow });
    }
    return { lines, heads };
  }
  // a bus end with a single line at it turns with a rounded corner; one with a line each way stays square
  const lone = (x: number, others: number[]) => !others.some((o) => Math.abs(o - x) < 0.5);
  const tops = P.map((p) => mid(p));
  const bottoms = C.map(into);
  for (const p of P) {
    const x = mid(p);
    const start = p.y + p.h <= busY ? p.y + p.h : p.y;
    const dir = start < busY ? 1 : -1;
    const end = Math.abs(x - first) < 0.5 ? 1 : Math.abs(x - last) < 0.5 ? -1 : 0;
    const d = end && lone(x, bottoms) ? `M${x},${start} V${busY - dir * r} Q${x},${busY} ${x + end * r},${busY}` : `M${x},${start} V${busY}`;
    lines.push({ key: `${key}:p:${p.id}`, d, from: [p.id], to: g.children, tone: tone(p.id), flow: false });
  }
  for (const c of C) {
    const x = into(c);
    const stop = head(c, shared);
    const dir = stop > busY ? 1 : -1;
    const end = Math.abs(x - first) < 0.5 ? 1 : Math.abs(x - last) < 0.5 ? -1 : 0;
    const d = end && lone(x, tops) ? `M${x + end * r},${busY} Q${x},${busY} ${x},${busY + dir * r} V${stop}` : `M${x},${busY} V${stop}`;
    lines.push({ key: `${key}:c:${c.id}`, d, from: g.parents, to: [c.id], tone: shared, flow: running(c.id) });
  }
  const round = (x: number) => (lone(x, tops) || lone(x, bottoms) ? r : 0);
  lines.push({ key: `${key}:bus`, d: `M${first + round(first)},${busY} H${last - round(last)}`, from: g.parents, to: g.children, tone: shared, flow: false });
  return { lines, heads };
}
