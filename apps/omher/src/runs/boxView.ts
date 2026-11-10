// A run as boxes and lines, after the OMH TUI's box view (src/plugin_bundle/omh/delegation_view.py): the nodes
// stand in frontiers, one frontier to a row, every box one width, and every edge is a line: one down from a
// parent's middle, a bus joining the parents that lead to the same children (the TUI's ╰──┬──╯ and ╭──┴──╮), an
// arrowhead on each child's top. Widths are character cells, as in the TUI; the caller turns them into pixels with
// its font's cell width. Pure: no DOM, no clock.
//
// What it does that the TUI cannot, so that no edge is left undrawn:
// - boxes shrink to put a frontier on one row (down to BOX_MIN cells); a frontier still too wide first lets the
//   nodes that have room below them (their first dependent stands further down) move down a row, and only wraps
//   when that is not enough;
// - an edge that has to pass a row (it skips a frontier, or its end stands in a wrapped row) runs down a lane
//   beside that row's boxes, so there is no "these edges are not drawn" connector at all; a run with more such
//   lines than the space beside its boxes holds gets wider margins (and narrower or fewer boxes to a row);
// - where two parents' lines share the space between two rows, each bus has its own track, and a line that passes
//   over another's bus leaves a small gap in itself, so a crossing never reads as a join;
// - a child several buses lead into takes each at its own point on its top edge.
// Kept from the earlier round: a node stands under the middle of its parents; a node nothing leads to stands just
// above the first node that waits on it; a dependency on a failed node that has repairs is an edge from those
// repairs, which is what the dependent waits on; a duration reads as everywhere else in the app (`span`).
import type { AgentRun, RunNode } from "../lib/runs";
import { cliName, isRepaired, nodeModel, span, type CliAgent } from "../lib/runs";
import { t } from "../i18n";
import { modelName } from "./format";

export const GAP = 2; // cells between two boxes of a row
export const MARGIN = 2; // cells kept free at each side of the drawing: lanes for the lines that pass a row
const MARGIN_MOST = 8; // and as many as a drawing with more passing lines than that holds may take
export const BOX_MIN = 17; // a box is never narrower: about 122px at 12px, three to a row in the 460px panel
export const BOX_COMFORT = 26; // when a frontier wraps anyway, its boxes aim for this width (the TUI's narrowest)
export const BOX_INNER_MAX = 48; // and a box's text is never wider (the TUI's widest)
export const PAD = 3; // cells a box spends on its borders and padding: its text is `box − PAD` cells wide
/** One 14px mark and the space after it, in cells. */
export const MARK_CELLS = 3;
/** A box whose text is narrower than this leaves its parents line out: its lines already say where it comes from. */
export const PARENTS_MIN = 22;
/** The least a duration counts when a box is measured ("23h 59m"), so a ticking clock never resizes the boxes. */
const DURATION_CELLS = 7;
const ELLIPSIS = "…";

/** Pixel sizes of the drawing that do not come from the font. */
export const GEOMETRY = {
  padY: 5, // above a box's first line and under its last
  border: 1,
  rowGap: 12, // between two rows no bus runs between
  moreH: 22, // the "+76 more · Show all 88" line under a capped frontier
  stub: 12, // from a parent's bottom down to the first bus
  track: 7, // between two buses that share the space between two rows
  drop: 20, // from the last bus down to a child's top, arrowhead included
  arrow: 6, // the arrowhead's height; it is 8 wide
  r: 4, // a bus's rounded ends
  port: 10, // between two lines into one child
  lane: 4, // between two lines that pass a row side by side
  hop: 2, // the gap a line leaves, each side, where it passes over another net's bus
  clear: 2, // the least a passing line keeps from a box
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
/** The start of `text` that fits `width` cells (never half a character). */
function head(text: string, width: number): string {
  let kept = "";
  let used = 0;
  for (const ch of text) {
    const size = charCells(ch);
    if (used + size > width) break;
    kept += ch;
    used += size;
  }
  return kept;
}
/** `text` cut to at most `width` cells, ending in "…" when it was cut. */
export function fit(text: string, width: number): string {
  if (width <= 0) return "";
  if (cells(text) <= width) return text;
  if (width <= 1) return ELLIPSIS;
  return head(text, width - 1).trimEnd() + ELLIPSIS;
}
/** `text` on at most `lines` lines of `width` cells, broken between words (a word longer than a line goes on to
 *  the next, after a "/", "-", "_", "." or ":" of its own where it has one); when text is left over, the last line
 *  ends in "…". A title is never cut in its middle. */
export function wrapText(text: string, width: number, lines = 2): string[] {
  const w = Math.max(1, width);
  const words = text.split(/\s+/).filter(Boolean);
  const out: string[] = [];
  let i = 0;
  while (i < words.length && out.length < lines) {
    let line = "";
    while (i < words.length) {
      const next = line ? `${line} ${words[i]}` : words[i];
      if (cells(next) <= w) {
        line = next;
        i++;
        continue;
      }
      if (!line) {
        // one word wider than the line: as much of it as fits, the rest goes on
        line = head(words[i], w) || [...words[i]][0];
        const sep = Math.max(...["/", "-", "_", ".", ":"].map((c) => line.lastIndexOf(c)));
        if (sep >= 2 && sep < line.length - 1) line = line.slice(0, sep + 1);
        words[i] = words[i].slice(line.length);
        if (!words[i]) i++;
      }
      break;
    }
    out.push(line);
  }
  if (i < words.length && out.length) {
    const last = out[out.length - 1];
    out[out.length - 1] = cells(last) + 1 <= w ? `${last}${ELLIPSIS}` : fit(`${last}${ELLIPSIS}${ELLIPSIS}`, w);
  }
  return out.length ? out : [""];
}

// ---- a node's lines ----

const clean = (s: string | undefined) => (s ?? "").replace(/\s+/g, " ").trim();
export const titleOf = (n: Pick<RunNode, "label">) => clean(n.label) || t("graph.untitled");

/** What ran a node, as its second line says it: the marks before the text, then "Opus 5.5 · high ·
 *  visual-engineering" (model, effort, OMH category). The model is what the helper ran on, else the agent CLI the
 *  lane went to, else what its route resolves to, else the bot's own. The category is the one the node went out
 *  under, else the plan's; one OMH left unnamed ("unspecified-high") is shown only by a named one, or not at all. */
export interface Facts {
  /** Agent marks, in order: "hermes" for a Hermes subagent, then the CLI a lane was handed to; a CLI session's own
   *  sub-runs carry that CLI's mark alone. */
  marks: string[];
  text: string;
}
export function factsOf(n: RunNode, run: Pick<AgentRun, "kind"> & { agent?: CliAgent }, bot?: { model: string; provider: string }): Facts {
  const marks = run.agent ? [run.agent] : ["hermes", ...(n.executor ? [n.executor] : [])];
  const m = nodeModel(n, bot);
  const name = !m ? "" : m.source === "executor" ? cliName(m.model as CliAgent) || clean(m.model) : modelName(clean(m.model));
  const effort = n.effort ?? n.planned?.effort;
  const cat = [n.route, n.category].map(clean).find((c) => c && !/^unspecified\b/i.test(c)) ?? "";
  return { marks, text: [name, clean(effort), cat].filter(Boolean).join(" · ") };
}

export interface Status {
  glyph: string;
  word: string;
  /** Whether the line carries the node's duration after the word. */
  timed: boolean;
  /** After the duration, where the line still fits whole (" · repaired"). */
  note: string;
  /** The word as a box too narrow for it says it ("Waits on 3" for "Waits on 3 lanes"). */
  short?: string;
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
      return { glyph: "○", word, timed: false, note: "", short: unmet ? t("graph.waits.short", { n: unmet }) : undefined, tone: "waiting" };
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

/** A node's title as its box sets it: one or two lines, "↻ " first on a node added to repair another. */
export const titleLines = (n: RunNode, shape: Pick<Frontiers, "origin">, inner: number) => wrapText(`${shape.origin.has(n.id) ? "↻ " : ""}${titleOf(n)}`, inner, 2);

/** A node's facts on one line after its marks, or on two when the box is too narrow for them: as many whole parts
 *  as fit on the first ("Opus 5.5 · high"), the rest on the second ("visual-engineering"). The second stands under
 *  the first's text where it fits there, else from the box's left edge, and only then is it cut. */
export function factLines(f: Facts, inner: number): string[] {
  const room = Math.max(1, inner - f.marks.length * MARK_CELLS);
  if (cells(f.text) <= room) return [f.text];
  const parts = f.text.split(" · ");
  let first = parts[0];
  let rest: string;
  if (cells(first) > room) {
    // the name alone is wider than the room after the marks ("GPT-6 Astra" after two): as many of its words as
    // fit, and the others go on with the rest
    const words = first.split(" ");
    let n = 1;
    while (n < words.length && cells(words.slice(0, n + 1).join(" ")) <= room) n++;
    first = words.slice(0, n).join(" ");
    rest = [words.slice(n).join(" "), ...parts.slice(1)].filter(Boolean).join(" · ");
  } else {
    let used = 1;
    while (used < parts.length && cells(`${first} · ${parts[used]}`) <= room) first += ` · ${parts[used++]}`;
    rest = parts.slice(used).join(" · ");
  }
  return rest ? [fit(first, room), fit(rest, cells(rest) <= room ? room : inner)] : [fit(first, room)];
}

export interface BoxText {
  /** One or two lines: the title wraps between words and ends in "…" when it is longer still. */
  title: string[];
  /** The agent marks before the facts. */
  marks: string[];
  /** "Opus 5.5 · high · visual-engineering" after the marks, on one line or two. */
  facts: string[];
  /** The second facts line stands under the first's text, after the marks (it fits there). */
  hang: boolean;
  /** The facts whole, for the tooltip. */
  factsText: string;
  glyph: string;
  /** "Accepted 12s": the word and the duration. */
  status: string;
  /** " · ↓1.2k" or " · repaired", only where the status line fits whole with it. */
  after: string;
  /** "← Export API +2": the first parent and how many more; "Start node" for a node with none. Null in a box too
   *  narrow for it (`PARENTS_MIN`). */
  parents: string | null;
  tone: Tone;
}

/** How many lines of text a node's box holds. */
export function boxLines(n: RunNode, run: Pick<AgentRun, "kind"> & { agent?: CliAgent }, shape: Pick<Frontiers, "origin">, inner: number, bot?: { model: string; provider: string }): number {
  return titleLines(n, shape, inner).length + factLines(factsOf(n, run, bot), inner).length + 1 + (inner >= PARENTS_MIN ? 1 : 0);
}

/** A box's lines, each cut to `inner` cells. */
export function boxText(
  n: RunNode,
  run: Pick<AgentRun, "kind" | "nodes"> & { agent?: CliAgent },
  shape: Frontiers,
  inner: number,
  nowS: number,
  bot?: { model: string; provider: string },
): BoxText {
  const st = statusOf(n, run);
  const f = factsOf(n, run, bot);
  const time = st.timed ? durationOf(n, nowS) : "";
  // whole, else with the duration's first unit alone ("Accepted 1h" for "1h 1m"), else the word's short form
  const forms = [time ? `${st.word} ${time}` : st.word, ...(time.includes(" ") ? [`${st.word} ${time.split(" ")[0]}`] : []), ...(st.short ? [st.short] : [])];
  const status = forms.find((f2) => cells(f2) <= inner - 2) ?? fit(forms[forms.length - 1], inner - 2);
  // whole or not at all: a count or a note never ends in "…"
  const extras = [st.note, n.tokens && n.tokens > 0 ? `↓${compactCount(n.tokens)}` : ""].filter(Boolean);
  let after = "";
  for (const extra of extras) if (2 + cells(status) + cells(after) + 3 + cells(extra) <= inner) after += ` · ${extra}`;
  const byId = new Map(run.nodes.map((m) => [m.id, m]));
  const named = shape.parents.get(n.id) ?? [];
  const more = named.length > 1 ? ` +${named.length - 1}` : "";
  const parents = inner < PARENTS_MIN ? null : named.length ? `← ${fit(titleOf(byId.get(named[0])!), Math.max(1, inner - 2 - cells(more)))}${more}` : t("graph.start");
  const facts = factLines(f, inner);
  return {
    title: titleLines(n, shape, inner),
    marks: f.marks,
    facts,
    hang: facts.length > 1 && cells(facts[1]) <= inner - f.marks.length * MARK_CELLS,
    factsText: f.text,
    glyph: st.glyph,
    status,
    after,
    parents,
    tone: st.tone,
  };
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
  /** Every edge between two nodes, in reading order: each is a line, and a row under Dependencies. */
  edges: EdgeRec[];
  /** A node added mid-run to repair another. */
  origin: Map<string, "repair">;
  /** The recorded edges loop: the edge that closes a loop has no line (it stays in the parents line and under
   *  Dependencies), so the nodes on the loop and below it still stand under what they wait on. */
  looped: boolean;
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

/** The edges that close a loop: walking the edges depth first (from the nodes nothing leads to, then the others,
 *  in the nodes' order), an edge that leads back to a node still being walked. */
function backEdges(ids: string[], pairs: EdgeRec[]): Set<EdgeRec> {
  const out = new Map<string, EdgeRec[]>();
  for (const e of pairs) (out.get(e.from) ?? out.set(e.from, []).get(e.from)!).push(e);
  const has = new Set(pairs.map((e) => e.to));
  const walked = new Map<string, boolean>(); // false: being walked, true: done
  const back = new Set<EdgeRec>();
  const walk = (id: string) => {
    walked.set(id, false);
    for (const e of out.get(id) ?? []) {
      if (walked.get(e.to) === false) back.add(e);
      else if (!walked.has(e.to)) walk(e.to);
    }
    walked.set(id, true);
  };
  for (const id of [...ids.filter((i) => !has.has(i)), ...ids]) if (!walked.has(id)) walk(id);
  return back;
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
 *  none; inside a frontier a node stands under the middle of its parents, so that fewer lines cross. With `cap`
 *  (the most boxes a row holds), a frontier wider than that sends the nodes that have room below them down a
 *  frontier, so that it need not wrap. */
export function frontiers(nodes: RunNode[], cap = Infinity): Frontiers {
  const ids = nodes.map((n) => n.id);
  let pairs = edgesOf(nodes, true);
  let layer = layerOf(ids, pairs);
  if (layer.size < ids.length) {
    // waiting on the repairs would loop: the dependencies as recorded
    pairs = edgesOf(nodes, false);
    layer = layerOf(ids, pairs);
  }
  // a loop in the recorded edges themselves: the edges that close it are left out of the layering
  const looped = layer.size < ids.length;
  if (looped) {
    const back = backEdges(ids, pairs);
    layer = layerOf(ids, pairs.filter((e) => !back.has(e)));
  }
  const last = Math.max(-1, ...layer.values()) + 1;
  for (const id of ids) if (!layer.has(id)) layer.set(id, last);
  // a node nothing leads to stands just above the first node that waits on it, so its lines are short (three
  // independent parts and a closing check are one row over the check)
  const has = new Set(pairs.map((e) => e.to));
  for (const id of ids) {
    if (has.has(id)) continue;
    const kids = pairs.filter((e) => e.from === id).map((e) => layer.get(e.to)!);
    if (kids.length) layer.set(id, Math.min(...kids) - 1);
  }
  // a frontier wider than a row: a node whose first dependent stands more than one frontier below can wait a
  // frontier longer, the one with the most room first
  if (Number.isFinite(cap)) {
    const firstKid = (id: string) => Math.min(...pairs.filter((e) => e.from === id).map((e) => layer.get(e.to)!));
    for (let l = 0; l <= Math.max(...layer.values(), 0); l++) {
      const row = ids.filter((id) => layer.get(id) === l);
      const room = (id: string) => firstKid(id) - 1 - l; // Infinity for a node nothing waits on: it stays
      const movable = row.filter((id) => Number.isFinite(room(id)) && room(id) > 0).sort((a, b) => room(b) - room(a) || ids.indexOf(b) - ids.indexOf(a));
      for (let over = row.length - cap; over > 0 && movable.length; over--) layer.set(movable.shift()!, l + 1);
    }
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
  const origin = new Map<string, "repair">();
  for (const e of edges) if (e.kind === "repair") origin.set(e.to, "repair");
  return { rows, layer, parents, edges, origin, looped };
}

// ---- the layout ----

export interface Metrics {
  /** One character cell's width, px. */
  cw: number;
  /** One text line's height, px. */
  line: number;
}
export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}
export interface BoxAt extends Rect {
  id: string;
  frontier: number;
  /** The row it is drawn on: a frontier is one row, or several when it wraps. */
  row: number;
  /** The order the boxes appear in: row by row, left to right. */
  index: number;
}
/** The edges out of the parents that lead to exactly these children, drawn as one tree of lines. */
export interface Net {
  key: string;
  parents: string[];
  children: string[];
}
export interface EdgeLine {
  key: string;
  net: string;
  d: string;
  /** The nodes this line leaves and the nodes it leads to: hovering any of them lights it. */
  from: string[];
  to: string[];
  /** The parent whose state colours it; null where parents of different states share the line. */
  tone: string | null;
  /** It leads into a running node: the slow dash rides on it. */
  flow: boolean;
}
export interface EdgeHead {
  key: string;
  net: string;
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
export interface BoxLayout {
  /** A box's text width in cells; every box is `inner + PAD` cells wide. */
  inner: number;
  /** The most boxes a row holds. */
  perRow: number;
  boxW: number;
  w: number;
  h: number;
  boxes: BoxAt[];
  at: Map<string, BoxAt>;
  /** A capped frontier's "+76 more · Show all 88" line. */
  more: { frontier: number; hidden: number; total: number; x: number; y: number }[];
  nets: Net[];
  /** Every net's lines and arrowheads, with every box where the layout put it. */
  lines: EdgeLine[];
  heads: EdgeHead[];
  /** The edges that have a line ("from>to"): every edge between two boxes on screen. */
  drawn: Set<string>;
  /** The lines that found no place of their own beside the rows they pass, and share another's: 0, unless the
   *  width is too small for the run's lines even with the widest margins. */
  crowded: number;
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
  /** The bot's own model: what a node with nothing else recorded is taken to run on (it only widens a box). */
  bot?: { model: string; provider: string };
}

const RANK: Record<RunNode["state"], number> = { running: 0, failed: 1, blocked: 1, waiting: 2, parked: 2, done: 3, cancelled: 4 };
/** Lines sit on half pixels, so a 1px stroke is one crisp pixel. */
const snap = (v: number) => Math.round(v) + 0.5;

/** Where every box stands and how every edge runs. The margins are as narrow as the lines that pass the rows
 *  allow: `MARGIN` cells, or more for a run whose passing lines need the room; a run they still do not fit gets
 *  fewer boxes to a row, down to one, until each line has a place of its own. */
export function layoutBoxes(run: Pick<AgentRun, "kind" | "nodes"> & { agent?: CliAgent }, o: LayoutOpts): BoxLayout {
  const W = Math.max(BOX_MIN + 2 * MARGIN, Math.floor(o.cells));
  let best = layoutAt(run, o, W, MARGIN);
  const tryAt = (margin: number, cols?: number) => {
    const lay = layoutAt(run, o, W, margin, cols);
    if (lay.crowded < best.crowded) best = lay;
  };
  const widest = Math.max(MARGIN, Math.min(MARGIN_MOST, Math.floor((W - BOX_MIN) / 2)));
  for (let m = MARGIN + 1; best.crowded && m <= widest; m++) tryAt(m);
  for (let cols = best.perRow - 1; best.crowded && cols >= 1; cols--) tryAt(widest, cols);
  return best;
}

/** One layout: `margin` cells free at each side, and at most `cols` boxes to a row when that is given (the boxes
 *  then stay at the width they wrap to, so the room they leave goes to the passing lines). */
function layoutAt(run: Pick<AgentRun, "kind" | "nodes"> & { agent?: CliAgent }, o: LayoutOpts, W: number, margin: number, cols?: number): BoxLayout {
  const byId = new Map(run.nodes.map((n) => [n.id, n]));
  const { cw, line } = o.metrics;
  const avail = W - 2 * margin;
  const widthFor = (k: number) => Math.floor((avail - (k - 1) * GAP) / k);
  const maxCols = Math.max(1, Math.min(cols ?? Infinity, Math.floor((avail + GAP) / (BOX_MIN + GAP))));
  const shape = frontiers(run.nodes, maxCols);

  // one width for every box: what the widest node would like on one line, narrowed to put the widest frontier on
  // one row; a frontier that would need boxes under BOX_MIN wraps instead, and the boxes are then as narrow as
  // the widest frontier that does fit a row needs (at least three to a row, or the TUI's narrowest box)
  const want = Math.min(
    BOX_INNER_MAX,
    Math.max(
      BOX_MIN - PAD,
      ...run.nodes.map((n) => {
        const st = statusOf(n, run);
        const f = factsOf(n, run, o.bot);
        return Math.max((shape.origin.has(n.id) ? 2 : 0) + cells(titleOf(n)), 2 + cells(st.word) + (st.timed ? 1 + DURATION_CELLS : 0), f.marks.length * MARK_CELLS + cells(f.text));
      }),
    ),
  );
  const sizes = shape.rows.map((r) => r.length);
  const longest = Math.max(1, ...sizes);
  const fits = Math.max(0, ...sizes.filter((n) => n <= maxCols));
  const per = longest <= maxCols ? longest : Math.max(fits, Math.min(maxCols, Math.max(Math.min(3, maxCols), Math.floor((avail + GAP) / (BOX_COMFORT + GAP)))));
  const boxCells = Math.max(BOX_MIN, Math.min(want + PAD, widthFor(per), cols === undefined ? Infinity : BOX_COMFORT));
  const inner = boxCells - PAD;
  const perRow = Math.max(1, Math.min(maxCols, Math.floor((avail + GAP) / (boxCells + GAP))));
  const boxW = boxCells * cw;
  const wPx = W * cw;

  // ---- rows: a frontier is one row; one too long for a row wraps into rows of equal length
  const vrows: { frontier: number; ids: string[] }[] = [];
  const moreAfter = new Map<number, { frontier: number; hidden: number; total: number }>();
  shape.rows.forEach((frontier, fi) => {
    let shown = frontier;
    const capped = !!o.capRows && Math.ceil(frontier.length / perRow) > o.capRows + 2; // "Show all" only when it hides more than a row or two
    if (capped && !o.opened?.has(fi))
      shown = frontier
        .map((id, i) => [id, i] as const)
        .sort((a, b) => RANK[byId.get(a[0])!.state] - RANK[byId.get(b[0])!.state] || a[1] - b[1])
        .slice(0, o.capRows! * perRow)
        .map(([id]) => id);
    // rows as even as they go: seven boxes, three to a row, are 3 + 2 + 2
    const n = Math.ceil(shown.length / perRow);
    for (let i = 0, from = 0; i < n; i++) {
      const size = Math.floor(shown.length / n) + (i < shown.length % n ? 1 : 0);
      vrows.push({ frontier: fi, ids: shown.slice(from, from + size) });
      from += size;
    }
    if (capped) moreAfter.set(vrows.length - 1, { frontier: fi, hidden: frontier.length - shown.length, total: frontier.length });
  });
  // every box of a row is as tall as the row's longest box needs
  const rowH = vrows.map((r) => Math.max(...r.ids.map((id) => boxLines(byId.get(id)!, run, shape, inner, o.bot))) * line + 2 * GEOMETRY.padY + 2 * GEOMETRY.border);
  const rowOf = new Map<string, number>();
  const xOf = new Map<string, number>();
  vrows.forEach((r, v) =>
    r.ids.forEach((id, i) => {
      rowOf.set(id, v);
      xOf.set(id, (margin + (avail - (r.ids.length * boxCells + (r.ids.length - 1) * GAP)) / 2 + i * (boxCells + GAP)) * cw);
    }),
  );
  const mid = (id: string) => xOf.get(id)! + boxW / 2;

  // ---- nets: the parents that lead to the same children share one tree of lines
  const kids = new Map<string, string[]>();
  for (const e of shape.edges) {
    // an edge needs both ends on screen, the child on a later row (edges that loop have no line)
    if (!rowOf.has(e.from) || !rowOf.has(e.to) || rowOf.get(e.to)! <= rowOf.get(e.from)!) continue;
    (kids.get(e.from) ?? kids.set(e.from, []).get(e.from)!).push(e.to);
  }
  const order = (a: string, b: string) => rowOf.get(a)! - rowOf.get(b)! || xOf.get(a)! - xOf.get(b)!;
  const bySet = new Map<string, { parents: string[]; children: string[] }>();
  for (const [parent, children] of kids) {
    const sorted = [...children].sort(order);
    const key = sorted.join("\n");
    (bySet.get(key) ?? bySet.set(key, { parents: [], children: sorted }).get(key)!).parents.push(parent);
  }
  const meanX = (ids: string[]) => ids.reduce((a, id) => a + mid(id), 0) / ids.length;
  const nets = [...bySet.values()]
    .map((n) => ({ ...n, parents: n.parents.sort(order) }))
    .sort((a, b) => order(a.parents[0], b.parents[0]) || meanX(a.children) - meanX(b.children))
    .map((n, i) => ({ key: `n${i}`, ...n }));

  // ---- pins. A parent's line leaves its bottom middle. A child several nets lead into takes each at its own point,
  // left to right in the order of where they come from.
  const into = new Map<string, typeof nets>();
  for (const n of nets) for (const c of n.children) (into.get(c) ?? into.set(c, []).get(c)!).push(n);
  const port = new Map<string, number>(); // `${net}\n${child}` -> x
  for (const [child, ns] of into) {
    const step = Math.min(GEOMETRY.port, (boxW - 24) / Math.max(1, ns.length - 1));
    [...ns].sort((a, b) => meanX(a.parents) - meanX(b.parents) || a.key.localeCompare(b.key)).forEach((n, i) => port.set(`${n.key}\n${child}`, snap(mid(child) + (i - (ns.length - 1) / 2) * step)));
  }
  // The space under row c is channel c. A line from above and a line going below that belong to different nets
  // never share a column there: the one going below steps aside, or the two would read as one line.
  const stubs = new Map<number, { x: number; net: string }[]>(); // channel -> the lines that enter it from above
  for (const n of nets) for (const p of n.parents) (stubs.get(rowOf.get(p)!) ?? stubs.set(rowOf.get(p)!, []).get(rowOf.get(p)!)!).push({ x: snap(mid(p)), net: n.key });
  for (const n of nets)
    for (const c of n.children) {
      const key = `${n.key}\n${c}`;
      const others = (stubs.get(rowOf.get(c)! - 1) ?? []).filter((s) => s.net !== n.key);
      const taken = [...(into.get(c) ?? [])].filter((m) => m.key !== n.key).map((m) => port.get(`${m.key}\n${c}`)!);
      const clash = (x: number) => others.some((s) => Math.abs(s.x - x) < 4) || taken.some((px) => Math.abs(px - x) < 4);
      const x0 = port.get(key)!;
      if (!clash(x0)) continue;
      for (const d of [6, -6, 12, -12, 18, -18]) {
        const x = x0 + d;
        if (x > xOf.get(c)! + 6 && x < xOf.get(c)! + boxW - 6 && !clash(x)) {
          port.set(key, x);
          break;
        }
      }
    }

  // ---- a net whose ends are more than one row apart runs down a lane beside the rows it passes
  const free = (rows: number[]): [number, number][] => {
    let spans: [number, number][] = [[1.5, wPx - 1.5]];
    for (const v of rows)
      for (const id of vrows[v].ids) {
        const [a, b] = [xOf.get(id)! - GEOMETRY.clear, xOf.get(id)! + boxW + GEOMETRY.clear];
        spans = spans.flatMap(([lo, hi]) => (b <= lo || a >= hi ? [[lo, hi]] : ([[lo, Math.min(hi, a)], [Math.max(lo, b), hi]] as [number, number][]).filter(([x, y]) => y - x >= 1)));
      }
    return spans;
  };
  const reach = new Map<string, [number, number]>(); // net -> its first and last channel
  for (const n of nets) {
    const cs = [...n.parents.map((p) => rowOf.get(p)!), ...n.children.map((c) => rowOf.get(c)! - 1)];
    reach.set(n.key, [Math.min(...cs), Math.max(...cs)]);
  }
  const pinsIn = (lo: number, hi: number, but: string) => {
    const xs: number[] = [];
    for (const n of nets) {
      if (n.key === but) continue;
      for (const p of n.parents) if (rowOf.get(p)! >= lo && rowOf.get(p)! <= hi) xs.push(snap(mid(p)));
      for (const c of n.children) if (rowOf.get(c)! - 1 >= lo && rowOf.get(c)! - 1 <= hi) xs.push(port.get(`${n.key}\n${c}`)!);
    }
    return xs;
  };
  const lane = new Map<string, number>(); // net -> the x of its line past the rows between its ends
  const lanes: { x: number; lo: number; hi: number }[] = [];
  let crowded = 0;
  for (const n of nets) {
    const [lo, hi] = reach.get(n.key)!;
    if (lo === hi) continue;
    const xs = [...n.parents.map(mid), ...n.children.map((c) => port.get(`${n.key}\n${c}`)!)].sort((a, b) => a - b);
    const ideal = xs[Math.floor((xs.length - 1) / 2)];
    const pins = pinsIn(lo, hi, n.key);
    const busy = (x: number) => lanes.some((l) => l.lo <= hi && lo <= l.hi && Math.abs(l.x - x) < GEOMETRY.lane) || pins.some((px) => Math.abs(px - x) < 4);
    let best: number | null = null;
    let spare: number | null = null;
    for (const [a, b] of free(Array.from({ length: hi - lo }, (_, i) => lo + 1 + i))) {
      const near = snap(Math.min(Math.max(ideal, a + 1), Math.max(a + 1, b - 1)));
      if (spare === null || Math.abs(near - ideal) < Math.abs(spare - ideal)) spare = near;
      for (let k = 0; k * GEOMETRY.lane <= b - a; k++)
        for (const x of k ? [near + k * GEOMETRY.lane, near - k * GEOMETRY.lane] : [near]) {
          if (x < a + 0.5 || x > b - 0.5 || busy(x)) continue;
          if (best === null || Math.abs(x - ideal) < Math.abs(best - ideal)) best = x;
        }
    }
    if (best === null) crowded++;
    const x = best ?? spare ?? snap(ideal);
    lane.set(n.key, x);
    lanes.push({ x, lo, hi });
  }

  // ---- tracks: the buses of one channel that would overlap each take their own height
  const pinsOf = (n: (typeof nets)[number], c: number) => [...n.parents.filter((p) => rowOf.get(p) === c).map((p) => snap(mid(p))), ...n.children.filter((k) => rowOf.get(k)! - 1 === c).map((k) => port.get(`${n.key}\n${k}`)!)];
  const track = new Map<string, number>(); // `${net}\n${channel}` -> track
  const tracks: number[] = vrows.map(() => 0);
  for (let c = 0; c < vrows.length - 1; c++) {
    const items = nets
      .map((n) => {
        const xs = pinsOf(n, c);
        if (!xs.length) return null;
        if (lane.has(n.key)) xs.push(lane.get(n.key)!);
        return { key: n.key, lo: Math.min(...xs), hi: Math.max(...xs) };
      })
      .filter((x): x is { key: string; lo: number; hi: number } => x !== null)
      .sort((a, b) => a.lo - b.lo || a.hi - b.hi);
    const ends: number[] = [];
    const on = new Map<string, number>();
    for (const it of items) {
      let tr = ends.findIndex((e) => e < it.lo - 4);
      if (tr < 0) tr = ends.length;
      ends[tr] = it.hi;
      on.set(it.key, tr);
    }
    // which track stands above which: the order in which the fewest lines pass over another net's bus. A line
    // from above (a parent's, or a lane coming down) passes the buses over its own; a line going below (into a
    // child, or a lane going on) passes the buses under it.
    const marks = items.map((it) => {
      const n = nets.find((m) => m.key === it.key)!;
      const [lo, hi] = reach.get(n.key)!;
      const lx = lane.get(n.key);
      return {
        ...it,
        tr: on.get(it.key)!,
        down: [...n.parents.filter((q) => rowOf.get(q) === c).map((q) => snap(mid(q))), ...(lx !== undefined && lo < c ? [lx] : [])],
        up: [...n.children.filter((k) => rowOf.get(k)! - 1 === c).map((k) => port.get(`${n.key}\n${k}`)!), ...(lx !== undefined && hi > c ? [lx] : [])],
      };
    });
    const crossings = (place: number[]) => {
      let count = 0;
      for (const a of marks)
        for (const b of marks) {
          if (a === b || place[a.tr] === place[b.tr]) continue;
          const xs = place[b.tr] < place[a.tr] ? a.down : a.up;
          count += xs.filter((x) => b.lo < x && x < b.hi).length;
        }
      return count;
    };
    let place = ends.map((_, i) => i);
    let best = ends.length > 1 && ends.length <= 5 ? crossings(place) : 0; // 120 orders at most
    if (best > 0) {
      const walk = (left: number[], taken: number[]) => {
        if (!left.length) {
          const cost = crossings(taken);
          if (cost < best) [best, place] = [cost, taken];
          return;
        }
        left.forEach((tr, i) => {
          const next = [...taken];
          next[tr] = ends.length - left.length;
          walk([...left.slice(0, i), ...left.slice(i + 1)], next);
        });
      };
      walk(place, []);
    }
    for (const m of marks) track.set(`${m.key}\n${c}`, place[m.tr]);
    tracks[c] = ends.length;
  }

  // ---- heights
  const rowY: number[] = [];
  const chTop: number[] = [];
  const more: BoxLayout["more"] = [];
  let y = 0;
  vrows.forEach((r, v) => {
    rowY[v] = y;
    y += rowH[v];
    const m = moreAfter.get(v);
    if (m) {
      more.push({ ...m, x: margin * cw, y });
      y += GEOMETRY.moreH;
    }
    chTop[v] = y;
    if (v < vrows.length - 1) y += tracks[v] ? GEOMETRY.stub + (tracks[v] - 1) * GEOMETRY.track + GEOMETRY.drop : GEOMETRY.rowGap;
  });
  const boxes: BoxAt[] = [];
  vrows.forEach((r, v) => r.ids.forEach((id) => boxes.push({ id, x: xOf.get(id)!, y: rowY[v], w: boxW, h: rowH[v], frontier: r.frontier, row: v, index: boxes.length })));
  const at = new Map(boxes.map((b) => [b.id, b]));

  // ---- the lines
  const busY = (key: string, c: number) => snap(chTop[c] + GEOMETRY.stub + (track.get(`${key}\n${c}`) ?? 0) * GEOMETRY.track);
  const tone = (id: string) => statusOf(byId.get(id)!, run).tone;
  const running = (id: string) => byId.get(id)!.state === "running";
  type V = { x: number; y1: number; y2: number; role: "stub" | "drop" | "lane"; id?: string };
  type H = { y: number; x1: number; x2: number };
  const drawnNets = nets.map((n) => {
    const [lo, hi] = reach.get(n.key)!;
    const lx = lane.get(n.key);
    const touched = [...new Set([...n.parents.map((p) => rowOf.get(p)!), ...n.children.map((c) => rowOf.get(c)! - 1)])].sort((a, b) => a - b);
    const vs: V[] = [];
    const hs: H[] = [];
    for (const p of n.parents) vs.push({ x: snap(mid(p)), y1: rowY[rowOf.get(p)!] + rowH[rowOf.get(p)!], y2: busY(n.key, rowOf.get(p)!), role: "stub", id: p });
    for (const c of n.children) vs.push({ x: port.get(`${n.key}\n${c}`)!, y1: busY(n.key, rowOf.get(c)! - 1), y2: rowY[rowOf.get(c)!] - GEOMETRY.arrow, role: "drop", id: c });
    if (lx !== undefined) for (let i = 0; i + 1 < touched.length; i++) vs.push({ x: lx, y1: busY(n.key, touched[i]), y2: busY(n.key, touched[i + 1]), role: "lane" });
    for (const c of touched) {
      const xs = [...pinsOf(n, c), ...(lx !== undefined ? [lx] : [])];
      const [x1, x2] = [Math.min(...xs), Math.max(...xs)];
      if (x2 - x1 >= 0.5) hs.push({ y: busY(n.key, c), x1, x2 });
    }
    return { net: n, vs, hs, lo, hi };
  });

  const lines: EdgeLine[] = [];
  const heads: EdgeHead[] = [];
  const drawn = new Set<string>();
  for (const { net, vs, hs } of drawnNets) {
    const tones = new Set(net.parents.map(tone));
    const shared = tones.size === 1 ? [...tones][0] : null;
    for (const p of net.parents) for (const c of net.children) drawn.add(`${p}>${c}`);
    // the buses of the other nets this net's upright lines pass over
    const over = drawnNets.filter((o2) => o2.net.key !== net.key).flatMap((o2) => o2.hs);
    // an upright line from `from` to `to`, with a gap wherever it passes over another net's bus; the path ends at `to`
    const upright = (v: V, from: number, to: number) => {
      const cuts = over.filter((h) => h.x1 - 0.5 < v.x && v.x < h.x2 + 0.5 && h.y > from + 1 && h.y < to - 1).map((h) => h.y).sort((a, b) => a - b);
      let d = "";
      let a = from;
      for (const cut of cuts) {
        if (cut - GEOMETRY.hop > a) d += `M${v.x},${a} V${cut - GEOMETRY.hop} `;
        a = Math.max(a, cut + GEOMETRY.hop);
      }
      return `${d}M${v.x},${Math.min(a, to)} V${to}`;
    };
    // an end of a bus that one line alone meets turns with a rounded corner; where a line arrives and another
    // leaves, or the bus goes on, the join stays square
    const corner = (v: V, end: "top" | "bottom"): number => {
      const yEnd = end === "top" ? v.y1 : v.y2;
      const h = hs.find((b) => Math.abs(b.y - yEnd) < 0.5);
      if (!h) return 0;
      const side = Math.abs(h.x1 - v.x) < 0.5 ? 1 : Math.abs(h.x2 - v.x) < 0.5 ? -1 : 0;
      if (!side || h.x2 - h.x1 < 2 * GEOMETRY.r) return 0;
      const meet = vs.filter((o2) => Math.abs(o2.x - v.x) < 0.5 && (Math.abs(o2.y1 - yEnd) < 0.5 || Math.abs(o2.y2 - yEnd) < 0.5));
      return meet.length === 1 ? side : 0;
    };
    const r = GEOMETRY.r;
    const trims = new Map<H, { x1: number; x2: number }>(hs.map((h) => [h, { x1: h.x1, x2: h.x2 }]));
    const trim = (v: V, yEnd: number, side: number) => {
      const h = hs.find((b) => Math.abs(b.y - yEnd) < 0.5)!;
      if (side > 0) trims.get(h)!.x1 = h.x1 + r;
      else trims.get(h)!.x2 = h.x2 - r;
    };
    const straight = !hs.length && vs.length === 2 && net.parents.length === 1 && net.children.length === 1;
    let body = "";
    for (const v of vs) {
      if (v.role === "stub") {
        if (straight) continue; // drawn with the drop below, as one line
        const side = corner(v, "bottom");
        if (side) trim(v, v.y2, side);
        const d = side ? `${upright(v, v.y1, v.y2 - r)} Q${v.x},${v.y2} ${v.x + side * r},${v.y2}` : upright(v, v.y1, v.y2);
        lines.push({ key: `${net.key}:p:${v.id}`, net: net.key, d, from: [v.id!], to: net.children, tone: tone(v.id!), flow: false });
      } else if (v.role === "drop") {
        const from = straight ? vs.find((s) => s.role === "stub")!.y1 : v.y1;
        const side = straight ? 0 : corner(v, "top");
        if (side) trim(v, v.y1, side);
        const d = side ? `M${v.x + side * r},${v.y1} Q${v.x},${v.y1} ${v.x},${v.y1 + r} ${upright(v, v.y1 + r, v.y2)}` : upright(v, from, v.y2);
        lines.push({ key: `${net.key}:c:${v.id}`, net: net.key, d, from: net.parents, to: [v.id!], tone: shared, flow: running(v.id!) });
        heads.push({ key: `${net.key}:h:${v.id}`, net: net.key, x: v.x, y: v.y2 + GEOMETRY.arrow, up: false, from: net.parents, to: v.id!, tone: shared, flow: running(v.id!) });
      } else {
        const top = corner(v, "top");
        const bottom = corner(v, "bottom");
        if (top) trim(v, v.y1, top);
        if (bottom) trim(v, v.y2, bottom);
        body += `${top ? `M${v.x + top * r},${v.y1} Q${v.x},${v.y1} ${v.x},${v.y1 + r} ` : ""}${upright(v, v.y1 + (top ? r : 0), v.y2 - (bottom ? r : 0))}${bottom ? ` Q${v.x},${v.y2} ${v.x + bottom * r},${v.y2}` : ""} `;
      }
    }
    for (const h of hs) {
      const x = trims.get(h)!;
      if (x.x2 - x.x1 > 0.5) body += `M${x.x1},${h.y} H${x.x2} `;
    }
    if (body) lines.push({ key: `${net.key}:bus`, net: net.key, d: body.trim(), from: net.parents, to: net.children, tone: shared, flow: false });
  }
  return { inner, perRow, boxW, w: wPx, h: y, boxes, at, more, nets: nets.map(({ key, parents, children }) => ({ key, parents, children })), lines, heads, drawn, crowded, shape };
}

/** A net one of whose boxes the person dragged (full view): each edge as its own elbow between the boxes as they
 *  stand now, from the parent's bottom to the child's top (or up into its bottom, when the child was dragged above). */
export function elbowNet(net: Net, rect: (id: string) => Rect, tone: (id: string) => string, running: (id: string) => boolean): { lines: EdgeLine[]; heads: EdgeHead[] } {
  const { arrow } = GEOMETRY;
  const lines: EdgeLine[] = [];
  const heads: EdgeHead[] = [];
  for (const c of net.children) {
    const cr = rect(c);
    const cx = snap(cr.x + cr.w / 2);
    const sides = new Map<boolean, string[]>(); // up or not -> the parents whose lines end there
    for (const p of net.parents) {
      const pr = rect(p);
      const px = snap(pr.x + pr.w / 2);
      // below its parent: bottom to top; dragged above it: top to bottom, with the head pointing up
      const down = cr.y - arrow > pr.y + pr.h + 4;
      const [y1, y2] = down ? [pr.y + pr.h, cr.y - arrow] : [pr.y, cr.y + cr.h + arrow];
      const midY = snap((y1 + y2) / 2);
      (sides.get(!down) ?? sides.set(!down, []).get(!down)!).push(p);
      lines.push({ key: `${net.key}:e:${p}>${c}`, net: net.key, d: Math.abs(px - cx) < 0.5 ? `M${px},${y1} V${y2}` : `M${px},${y1} V${midY} H${cx} V${y2}`, from: [p], to: [c], tone: tone(p), flow: running(c) });
    }
    // a head where lines end: on its top, on its bottom, or one on each when it stands between its parents
    for (const [up, from] of sides) {
      const tones = new Set(from.map(tone));
      heads.push({ key: `${net.key}:h:${c}${up ? ":up" : ""}`, net: net.key, x: cx, y: up ? cr.y + cr.h : cr.y, up, from, to: c, tone: tones.size === 1 ? [...tones][0] : null, flow: running(c) });
    }
  }
  return { lines, heads };
}
