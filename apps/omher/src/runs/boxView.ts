// A run as nodes and lines. The structure is the OMH TUI's box view (src/plugin_bundle/omh/delegation_view.py):
// the nodes stand in frontiers, one frontier to a row, every box one width, and every edge is a line from a
// parent's bottom middle to an arrowhead on a child's top. The look is the desktop's: sizes are pixels and text is
// measured in the app's own font (the caller passes the measure), a line turns with a rounded corner, and a state is
// an icon and a word. Pure: no DOM, no clock.
//
// How the lines run, so that no edge is left undrawn and none is hard to follow:
// - boxes shrink to put a frontier on one row (down to BOX_MIN); a frontier still too wide first lets the nodes
//   that have room below them (their first dependent stands further down) move down a row, and only wraps when that
//   is not enough;
// - the parents that lead to the same children share one tree of lines (a net): a level stretch between the two
//   rows, and where several nets share that space each has its own height;
// - an edge that has to pass a row (it skips a frontier, or its end stands in a wrapped row) runs down a lane
//   beside that row's boxes. A lane keeps `keep` px from a box (`ease` where it has the room) and never takes a
//   space between two boxes of `pass` px or less: it goes round, through a wider space or the margin. A line
//   that passes several rows takes each at a place of its own and steps across between two rows where their
//   free places differ, so it need not go round all of them. A run with such lines stands its boxes a lane's
//   width apart where they stay comfortable for it (`gapLane`), so a passing line takes the space between two
//   boxes near its ends; one with more such lines than the space holds gets wider margins, then fewer boxes to
//   a row;
// - a child several nets lead into takes each at its own point on its top edge, `port` px apart (down to
//   `portClear`, and for more of them than that holds down to an arrowhead and two px), so two arrowheads do not
//   stand on each other. A child with more lines into it than its top edge holds even so is `tight`: the layout
//   counts it as crowded and tries for more room;
// - every edge is its own path with rounded turns. The edges of a net lie on each other along the stretch they
//   share, so where they part there is a curve: a join is always a curve. Where an upright line only passes over
//   another net's level stretch it leaves a small gap, so a crossing never reads as a join.
// Kept from the earlier rounds: a node stands under the middle of its parents; a node nothing leads to stands just
// above the first node that waits on it; a dependency on a failed node that has repairs is an edge from those
// repairs, which is what the dependent waits on; a duration reads as everywhere else in the app (`span`).
import type { AgentRun, RunNode } from "../lib/runs";
import { cliName, isRepaired, nodeModel, span, type CliAgent } from "../lib/runs";
import { t } from "../i18n";
import { markFor } from "../ui/ModelIcon";
import { modelName } from "./format";

export const BOX_MIN = 120; // a box is never narrower: three to a row in the 460px panel
export const BOX_COMFORT = 176; // when a frontier wraps anyway, its boxes aim for this width
export const BOX_MAX = 248; // and a box is never wider: a longer title takes its second line
export const BOX_OPEN = 140; // boxes are not narrowed under this to open the spaces between them for passing lines
/** The least a duration counts when a box is measured, so a ticking clock never resizes the boxes. */
const LONGEST_DURATION = "23h 59m";
const SEP = " · ";

/** Pixel sizes of the drawing. */
export const GEOMETRY = {
  padX: 12, // left and right of a box's text
  padY: 10, // above its first line and under its last
  border: 1,
  line: 18, // one line of text
  titleGap: 2, // between the title and the lines under it
  mark: 14, // the model's mark
  markGap: 5, // and the space after it
  icon: 12, // the status icon
  iconGap: 5,
  gap: 12, // between two boxes of a row, at the least
  gapLane: 28, // and at the least in a run whose lines pass rows, where the boxes can spare it: room for a lane
  gapMost: 48, // and at the most, where the boxes leave the room
  margin: 10, // free at each side of the drawing
  gutter: 20, // and where a line has to pass a row round its end: room for it clear of the boxes and of the edge
  marginMost: 58, // and as much as a drawing with more passing lines than that holds may take
  rowGap: 24, // between two rows no line runs between
  moreH: 24, // the "+76 more · Show all 88" line under a capped frontier
  stub: 24, // from a parent's bottom down to the first level stretch: room for a soft turn onto it
  track: 20, // between two level stretches that share the space between two rows: a line that passes one runs straight on for a while before it turns into its own
  drop: 24, // from the last level stretch down to a child's top, arrowhead included
  arrow: 5, // the arrowhead's height
  arrowW: 7, // and its width
  r: 8, // a turn's radius, as the layout reserves room for it
  curve: 12, // and as a line is drawn, where the stretches at the turn leave it: the lines into a child that several
  // lead into sweep in as soft elbows, not as a square bracket under the row
  port: 32, // between two lines into one child
  portInset: 14, // a line into a child keeps this from the child's corners
  portClear: 12, // two of them are this far apart or more, while the child's top edge holds them so
  lane: 6, // between two lines that pass a row side by side
  laneLeast: 4, // and in a run with more such lines than its rows hold that far apart
  hop: 5, // the gap a line leaves, each side, where it passes over another net's level stretch
  keep: 8, // a passing line keeps this from a box, at the least
  ease: 16, // and this where the space beside the box is wide enough
  edge: 2, // and this from the drawing's edge
  centre: 40, // a space between two boxes that leaves a line no more room than this: the line stands in its middle
};
const G = GEOMETRY;

export type Tone = "done" | "running" | "out" | "failed" | "repaired" | "retry" | "waiting" | "off";

// ---- text ----

/** A text's width in px, in the title's font ("title": 13px medium) or the other lines' ("text": 12px). The view
 *  measures in the DOM; `estimate` is the stand-in where there is none. */
export type Measure = (text: string, font: "title" | "text") => number;

const wide = (c: number) =>
  c >= 0x1100 &&
  (c <= 0x115f ||
    (c >= 0x2e80 && c <= 0xa4cf) ||
    (c >= 0xac00 && c <= 0xd7a3) ||
    (c >= 0xf900 && c <= 0xfaff) ||
    (c >= 0xfe30 && c <= 0xfe4f) ||
    (c >= 0xff00 && c <= 0xff60) ||
    (c >= 0xffe0 && c <= 0xffe6) ||
    (c >= 0x1f300 && c <= 0x1faff) ||
    (c >= 0x20000 && c <= 0x3fffd));
/** A width without a font to measure in: a sans face's usual proportions (narrow, wide, capital and other letters;
 *  a CJK or emoji character is one em). Close to the system font, not equal to it. */
export const estimate: Measure = (text, font) => {
  let em = 0;
  for (const ch of text) {
    if (wide(ch.codePointAt(0) ?? 0)) em += 1;
    else if (/[\s.,:;'|!·ijl]/.test(ch)) em += 0.28;
    else if (/[frt()[\]\/\\-]/.test(ch)) em += 0.36;
    else if (/[mwMW@%]/.test(ch)) em += 0.86;
    else if (/[A-Z0-9#&+=?_]/.test(ch)) em += 0.64;
    else em += 0.54;
  }
  return em * (font === "title" ? 13.4 : 12);
};

// ---- a node's lines ----

const clean = (s: string | undefined) => (s ?? "").replace(/\s+/g, " ").trim();
export const titleOf = (n: Pick<RunNode, "label">) => clean(n.label) || t("graph.untitled");

/** A title in the parts it may be broken between besides its spaces: after a "/" or a "_" inside a word, so that
 *  "Claude/Codex/pi/omp/grok session runs" wraps as "Claude/Codex/pi/" and "omp/grok session runs" and not in the
 *  middle of "omp". (A "-" is a break as it is; a "." or a ":" is not one: "v0.2", "1.1:".) */
export function titleParts(title: string): string[] {
  const out: string[] = [];
  let part = "";
  const chars = [...title];
  chars.forEach((ch, i) => {
    part += ch;
    const next = chars[i + 1];
    if ((ch === "/" || ch === "_") && next !== undefined && !/[\s/_]/.test(next)) {
      out.push(part);
      part = "";
    }
  });
  return part || !out.length ? [...out, part] : out;
}

/** The one mark a node carries: the maker of the model it ran on ("claude", "openai", "gemini"…), or the agent CLI
 *  its lane went to when no model is known. Never two. */
export type Mark = { kind: "model"; id: string; model: string; provider?: string } | { kind: "agent"; id: string };

/** What ran a node, as its second line says it: the model's mark, then "Opus 5.5 · high · visual-engineering"
 *  (model, effort, OMH category). The model is what the helper ran on, else what its route resolves to, else the
 *  bot's own. A lane handed to an agent CLI names the CLI after the facts ("via Codex") once its model is known;
 *  until then the CLI is the name and its mark the mark. A CLI session's own sub-runs never fall back to the bot's
 *  model: the session's CLI ran them. */
export interface Facts {
  mark: Mark | null;
  /** "Opus 5.5", "high", "visual-engineering": the parts that are known, in this order. */
  parts: string[];
  /** How many of the parts a box never cuts short: the name, and the effort when there is one. */
  core: number;
  /** "via Codex", or "". */
  via: string;
  /** The facts whole, for a tooltip and a label. */
  text: string;
}
const UNNAMED = /^unspecified(?:-([a-z]+))?$/i;
const EFFORTS = new Set(["minimal", "low", "medium", "high", "xhigh", "max"]);
export function factsOf(n: RunNode, run: Pick<AgentRun, "kind"> & { agent?: CliAgent }, bot?: { model: string; provider: string }): Facts {
  const m = nodeModel(n, run.agent ? undefined : bot);
  const cli = clean(run.agent ?? n.executor);
  let name = "";
  let mark: Mark | null = null;
  let via = "";
  if (m && m.source !== "executor") {
    name = modelName(clean(m.model));
    const id = markFor(m.model, m.provider);
    // a model whose maker has no mark carries the mark of the CLI that ran it: still one mark, and no "via" after it
    if (id) mark = { kind: "model", id, model: m.model, ...(m.provider ? { provider: m.provider } : {}) };
    else if (cli) mark = { kind: "agent", id: cli };
    if (id && n.executor && !run.agent) via = t("graph.via", { agent: cliName(n.executor as CliAgent) || clean(n.executor) });
  } else if (cli) {
    name = cliName(cli as CliAgent) || cli;
    mark = { kind: "agent", id: cli };
  }
  // the category is the one the node went out under, else the plan's. One OMH left unnamed ("unspecified-high") is
  // not a name to show, but it still says how hard the node thinks: its effort, when none was recorded
  const cats = [n.route, n.category].map(clean).filter(Boolean);
  const cat = cats.find((c) => !UNNAMED.test(c)) ?? "";
  const implied = cats.map((c) => (UNNAMED.exec(c)?.[1] ?? "").toLowerCase()).find((e) => EFFORTS.has(e)) ?? "";
  // the effort the node recorded, else the one it was planned with; "none" (no thinking) is not a word to show
  const recorded = [n.effort, n.planned?.effort].map(clean).find(Boolean) ?? "";
  const effort = recorded.toLowerCase() === "none" ? "" : recorded || implied;
  const parts = [name, effort, cat].filter(Boolean);
  return { mark, parts, core: [name, effort].filter(Boolean).length, via, text: [...parts, via].filter(Boolean).join(SEP) };
}

/** The icon before a node's status word. */
export type StatusIcon = "check" | "dot" | "dashed" | "x" | "alert" | "pause" | "retry" | "ring" | "off";
export interface Status {
  icon: StatusIcon;
  word: string;
  /** Whether the line carries the node's duration after the word. */
  timed: boolean;
  /** After the duration, where the line still fits whole ("repaired"). */
  note: string;
  tone: Tone;
}
const satisfied = (n: RunNode, all: RunNode[]) => n.state === "done" || isRepaired(n, all);

/** The status line's icon, word and colour. A dag node that is out with no helper seen yet is "Handed out". */
export function statusOf(n: RunNode, run: Pick<AgentRun, "kind" | "nodes">): Status {
  const timed = n.started !== undefined;
  switch (n.state) {
    case "done":
      return { icon: "check", word: t("graph.finished"), timed, note: "", tone: "done" };
    case "running":
      return run.kind !== "dag" || n.model || n.executor
        ? { icon: "dot", word: t("graph.running"), timed, note: "", tone: "running" }
        : { icon: "dashed", word: t("graph.handed"), timed: false, note: "", tone: "out" };
    case "failed":
      return isRepaired(n, run.nodes)
        ? { icon: "x", word: t("graph.failed"), timed, note: t("graph.repaired"), tone: "repaired" }
        : { icon: "x", word: t("graph.failed"), timed, note: "", tone: "failed" };
    case "blocked":
      return isRepaired(n, run.nodes)
        ? { icon: "alert", word: t("graph.blocked"), timed: false, note: t("graph.repaired"), tone: "repaired" }
        : { icon: "alert", word: t("graph.blocked"), timed: false, note: "", tone: "failed" };
    case "parked":
      return { icon: "pause", word: t("graph.parked"), timed: false, note: "", tone: "retry" };
    case "cancelled":
      return { icon: "off", word: t("graph.cancelled"), timed: false, note: "", tone: "off" };
    default: {
      if (n.attempts.length) return { icon: "retry", word: t("graph.retry"), timed: false, note: "", tone: "retry" };
      const byId = new Map(run.nodes.map((m) => [m.id, m]));
      const unmet = n.deps.filter((d) => byId.has(d) && !satisfied(byId.get(d)!, run.nodes)).length;
      return { icon: "ring", word: unmet ? t("graph.waits", { n: unmet }) : t("graph.waiting"), timed: false, note: "", tone: "waiting" };
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

/** A box's text width in px. */
export const innerOf = (boxW: number) => boxW - 2 * G.padX - 2 * G.border;

/** How many lines a title takes in a box: one, or two when it is wider than the box's text (the box then cuts it
 *  with "…" at the end of the second). A node added to repair another carries a small icon before its title. */
export function titleLines(n: RunNode, repair: boolean, inner: number, measure: Measure): 1 | 2 {
  return measure(titleOf(n), "title") + (repair ? G.icon + G.iconGap : 0) <= inner ? 1 : 2;
}

/** A node's facts after its mark. One line wherever the model and its effort fit side by side ("Opus 5.5 · high"):
 *  the parts after them follow whole while they fit, the first that does not is cut with "…" when a good piece of
 *  it still shows ("visual-engin…") and left out otherwise, and "via Codex" ends the line only where everything
 *  fits whole. A box too narrow for the model and its effort says the model, and the rest on a second line. What
 *  the box leaves out, the tooltip and the node's detail say. No facts, no line. */
export interface FactLines {
  lines: string[];
  /** "via Codex" at the end of the last line, or "" when it has no room in the box. */
  via: string;
  /** The second line fits under the first's text, after the mark. */
  hang: boolean;
}
/** The letters of a part that have to show for it to be cut rather than left out; a shorter part is never cut. */
const CUT_LEAST = 6;
export function factLines(f: Facts, inner: number, measure: Measure): FactLines {
  if (!f.parts.length) return { lines: [], via: "", hang: true };
  const w = (s: string) => measure(s, "text");
  const lead = f.mark ? G.mark + G.markGap : 0;
  const room = Math.max(1, inner - lead);
  /** `line` and the parts after it that fit `width` whole; the first that does not is added too (the box cuts it
   *  with "…") when a good piece of it still shows, and left out otherwise. `whole`: nothing was cut or left out. */
  const fill = (line: string, parts: string[], width: number) => {
    let used = 0;
    while (used < parts.length && w(`${line}${SEP}${parts[used]}`) <= width) line += `${SEP}${parts[used++]}`;
    if (used === parts.length) return { line, whole: true };
    const next = [...parts[used]];
    const cut = next.length > CUT_LEAST + 2 && w(`${line}${SEP}${next.slice(0, CUT_LEAST).join("")}…`) <= width;
    return { line: cut ? `${line}${SEP}${parts[used]}` : line, whole: false };
  };
  const core = Math.max(1, f.core);
  if (core > 1 && w(f.parts.slice(0, core).join(SEP)) > room) {
    // too narrow for the model and its effort side by side: the model (cut by the box when it is longer still),
    // and under it the effort and what follows. The effort is never what gives way
    const under = fill(f.parts[1], f.parts.slice(2), room);
    const flush = under.whole ? under : fill(f.parts[1], f.parts.slice(2), inner); // under the mark too, when that holds more
    const second = under.whole || flush.line === under.line ? under : flush;
    const viaW = f.via ? w(`${SEP}${f.via}`) : 0; // after the facts it follows a " · " like any of them
    const via = second.whole && !!f.via && w(second.line) + viaW <= inner;
    return { lines: [f.parts[0], second.line], via: via ? f.via : "", hang: second === under && w(second.line) + (via ? viaW : 0) <= room };
  }
  const one = fill(f.parts.slice(0, core).join(SEP), f.parts.slice(core), room);
  return { lines: [one.line], via: one.whole && f.via && w(`${one.line}${SEP}${f.via}`) <= room ? f.via : "", hang: true };
}

export interface BoxText {
  title: string;
  /** The lines the title takes: the box cuts a longer one with "…". */
  titleLines: 1 | 2;
  /** The node was added to repair another: an icon stands before its title. */
  repair: boolean;
  mark: Mark | null;
  /** "Opus 5.5 · high · visual-engineering" after the mark, on one line or two; none when nothing is known. */
  facts: string[];
  /** "via Codex" at the end of the last facts line, where it fits. */
  via: string;
  /** The second facts line stands under the first's text, after the mark (it fits there). */
  hang: boolean;
  /** The facts whole, for the tooltip. */
  factsText: string;
  icon: StatusIcon;
  /** "Done", "Running", "Waiting on 2". */
  word: string;
  /** "7m": the duration after the word, where the node has one. */
  time: string;
  /** "repaired", "1.2k tokens": after the duration, only those that fit whole. */
  extras: string[];
  tone: Tone;
}

/** How tall a node's box is: its title's lines, its facts' lines and its status. (It names no parent: every edge
 *  is a line, and the node's detail lists what it comes after.) */
export function boxHeight(titles: number, facts: number): number {
  return 2 * G.padY + 2 * G.border + titles * G.line + G.titleGap + (facts + 1) * G.line;
}

/** A box's lines, fitted to `inner` px of text. */
export function boxText(
  n: RunNode,
  run: Pick<AgentRun, "kind" | "nodes"> & { agent?: CliAgent },
  lay: Pick<BoxLayout, "shape">,
  inner: number,
  nowS: number,
  measure: Measure = estimate,
  bot?: { model: string; provider: string },
): BoxText {
  const st = statusOf(n, run);
  const f = factsOf(n, run, bot);
  const fl = factLines(f, inner, measure);
  const w = (s: string) => measure(s, "text");
  const room = inner - G.icon - G.iconGap;
  // the duration whole, else its first unit alone ("1h" for "1h 1m"), else none
  const whole = st.timed ? durationOf(n, nowS) : "";
  const fit = (s: string) => w(s) <= room - 0.5;
  const said = (d: string) => (d ? `${st.word} ${d}` : st.word);
  let time = [whole, whole.split(" ")[0], ""].find((d) => fit(said(d))) ?? "";
  // a note says more than how long it took ("Failed · repaired"): where both do not fit, the duration gives way
  if (st.note && time && !fit([said(time), st.note].join(SEP))) time = [whole.split(" ")[0], ""].find((d) => fit([said(d), st.note].join(SEP))) ?? time;
  // whole or not at all: a count or a note never ends in "…"
  const extras: string[] = [];
  for (const extra of [st.note, n.tokens && n.tokens > 0 ? t("graph.tokens", { n: compactCount(n.tokens) }) : ""])
    if (extra && w([time ? `${st.word} ${time}` : st.word, ...extras, extra].join(SEP)) <= room - 0.5) extras.push(extra);
  const repair = lay.shape.origin.has(n.id);
  return {
    title: titleOf(n),
    titleLines: titleLines(n, repair, inner, measure),
    repair,
    mark: f.mark,
    facts: fl.lines,
    via: fl.via,
    hang: fl.hang,
    factsText: f.text,
    icon: st.icon,
    word: st.word,
    time,
    extras,
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
  /** The recorded edges loop: the edge that closes a loop has no line (it stays under Dependencies), so the nodes
   *  on the loop and below it still stand under what they wait on. */
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
/** One edge's line, from its parent's bottom to just above its child's arrowhead. */
export interface EdgeLine {
  key: string;
  net: string;
  d: string;
  /** The points it turns at, first to last: `d` is drawn through them (and drawn again when a box is moved). */
  pts: [number, number][];
  from: string;
  to: string;
  /** Its parent's state. */
  tone: string;
}
export interface EdgeHead {
  key: string;
  net: string;
  /** Every net whose lines end in it: `net`, and the nets that end at the child with it. */
  nets: string[];
  /** The tip, on the child's top edge: every arrowhead points down into its child. */
  x: number;
  y: number;
  /** The parents whose lines end in it. */
  from: string[];
  to: string;
}
/** An edge into a running node, drawn from the child back to its parent: the slow dash rides on it. Drawn from
 *  the child, the dashes of the edges that share a stretch into it lie on each other. */
export interface EdgeFlow {
  key: string;
  net: string;
  d: string;
  from: string;
  to: string;
}
export interface BoxLayout {
  /** A box's text width, px. */
  inner: number;
  /** The most boxes a row holds. */
  perRow: number;
  boxW: number;
  /** Between two boxes of the fullest row, px (a row of fewer boxes may stand wider apart). */
  gap: number;
  /** The rows the boxes stand on: the frontiers, more when one wraps. */
  rows: number;
  /** The nets whose lines pass a row on their way. */
  passing: number;
  /** How many times such a line passes a row round its end, in the drawing's margin, and not between two boxes. */
  outer: number;
  w: number;
  h: number;
  boxes: BoxAt[];
  at: Map<string, BoxAt>;
  /** A capped frontier's "+76 more · Show all 88" line. */
  more: { frontier: number; hidden: number; total: number; x: number; y: number }[];
  nets: Net[];
  /** Every edge's line and every arrowhead, with every box where the layout put it. */
  lines: EdgeLine[];
  heads: EdgeHead[];
  flows: EdgeFlow[];
  /** The edges that have a line ("from>to"): every edge between two boxes on screen. */
  drawn: Set<string>;
  /** The lines that found no place of their own: a line that passes rows and has to share another's place beside
   *  them (`shared`), and every line into a `tight` child. 0, unless the width is too small for the run's lines
   *  even at the fewest boxes the layout puts in a row. */
  crowded: number;
  /** The lines that pass rows on another net's place: two edges on one line, which no reader can tell apart. */
  shared: number;
  /** The children with more lines into them than their top edge holds an arrowhead apart: their arrowheads stand
   *  nearer than that. */
  tight: string[];
  /** How many trial layouts `layoutBoxes` made before it kept this one (a layout made by itself: none). */
  trials?: number;
  /** Every box's second facts line fits under the first's text: they all stand there, or none does. */
  hang: boolean;
  shape: Frontiers;
}
export interface LayoutOpts {
  /** The width to draw into, px. */
  width: number;
  /** How wide a text is in the view's font (`estimate` when the caller has none). */
  measure?: Measure;
  /** A frontier of more rows than this shows this many (running, then failed, then the rest) and a "Show all" line. */
  capRows?: number;
  /** The frontiers the person opened with "Show all". */
  opened?: Set<number>;
  /** The bot's own model: what a node with nothing else recorded is taken to run on (it only widens a box). */
  bot?: { model: string; provider: string };
  /** How much wider than `width` the drawing may be when that keeps its longest frontier on one row: 1.25 is a
   *  quarter wider (the full view then shows it a little smaller). 1, the default, is never wider (the panel). */
  stretch?: number;
}

type Run = Pick<AgentRun, "kind" | "nodes"> & { agent?: CliAgent };
const RANK: Record<RunNode["state"], number> = { running: 0, failed: 1, blocked: 1, waiting: 2, parked: 2, done: 3, cancelled: 4 };
/** Lines sit on half pixels, so a thin stroke stays crisp. */
const snap = (v: number) => Math.round(v) + 0.5;

/** A line through `points` (each step upright or level) whose turns are rounded with radius `r`, or as much of it
 *  as the two stretches at the turn leave. `gaps` says, for an upright stretch at `x` between `lo` and `hi`, the
 *  heights at which it passes over another net's level stretch: it leaves `hop` px open on each side there. Only
 *  M, V, H and Q. */
export function roundedPath(points: [number, number][], r = G.r, gaps?: (x: number, lo: number, hi: number) => number[]): string {
  // a point repeated, or one in the middle of a straight stretch, is no turn
  const p: [number, number][] = [];
  for (const q of points) {
    const last = p[p.length - 1];
    if (last && Math.abs(last[0] - q[0]) < 0.01 && Math.abs(last[1] - q[1]) < 0.01) continue;
    const before = p[p.length - 2];
    if (last && before && ((before[0] === last[0] && last[0] === q[0]) || (before[1] === last[1] && last[1] === q[1]))) p.pop();
    p.push(q);
  }
  if (p.length < 2) return p.length ? `M${p[0][0]},${p[0][1]}` : "";
  let [x, y] = p[0];
  let d = `M${x},${y}`;
  // a straight stretch on to (tx, ty); an upright one leaves its gaps
  const to = (tx: number, ty: number) => {
    if (tx !== x) d += ` H${tx}`;
    else if (ty !== y) {
      const dir = Math.sign(ty - y);
      // (two crossings nearer than two gaps apart leave one gap over both: no stub of line between them)
      const over = (gaps?.(x, Math.min(y, ty), Math.max(y, ty)) ?? []).sort((a, b) => (a - b) * dir);
      for (let i = 0; i < over.length; i++) {
        const from = over[i];
        while (i + 1 < over.length && Math.abs(over[i + 1] - over[i]) < 2 * G.hop) i++;
        d += ` V${from - dir * G.hop} M${x},${over[i] + dir * G.hop}`;
      }
      d += ` V${ty}`;
    }
    [x, y] = [tx, ty];
  };
  for (let i = 1; i < p.length - 1; i++) {
    const [ax, ay] = p[i - 1];
    const [bx, by] = p[i];
    const [cx, cy] = p[i + 1];
    const k = Math.min(r, (Math.abs(bx - ax) + Math.abs(by - ay)) / 2, (Math.abs(cx - bx) + Math.abs(cy - by)) / 2);
    if (ax === bx) to(bx, by - Math.sign(by - ay) * k);
    else to(bx - Math.sign(bx - ax) * k, by);
    [x, y] = bx === cx ? [bx, by + Math.sign(cy - by) * k] : [bx + Math.sign(cx - bx) * k, by];
    d += ` Q${bx},${by} ${x},${y}`;
  }
  to(...p[p.length - 1]);
  return d;
}

/** What the trials of one layout may cost together (see `layoutBoxes`): a third of a second or so. */
const TRIAL_BUDGET = 60;

/** Where every box stands and how every edge runs. The margins are as narrow as the lines that pass the rows
 *  allow: `GEOMETRY.margin`, or more for a run whose passing lines need the room; a run they still do not fit gets
 *  fewer boxes to a row, down to half of them, for each line to have a place of its own. */
export function layoutBoxes(run: Run, o: LayoutOpts): BoxLayout {
  const W = Math.max(BOX_MIN + 2 * G.margin, Math.floor(o.width));
  // a frontier a little too long for the width stays on one row of the narrowest boxes where the drawing may be
  // wider: a wrapped frontier sends every line into its second row round the first
  const longest = Math.max(1, ...frontiers(run.nodes).rows.map((r) => r.length));
  // a trial costs more than the square of the run's size (some 10ms at sixty nodes, a quarter of a second at
  // 250), and the drawing is laid out again whenever a live run changes: a run of sixty nodes gets sixty
  // trials (its ladder is seldom that long), a run of a hundred ten, a run of a few hundred its first layout only
  const cost = (run.nodes.length / 60) ** 3.5;
  let spent = 0;
  let trials = 0;
  const afford = () => spent + cost <= TRIAL_BUDGET;
  /** The layout in which every passing line keeps `clear` px from the other nets' lines, where that can be. */
  const arrange = (clear: number) => {
    // a trial places the boxes and gives every line its place; only the layout that is kept draws its lines
    const at = (margin: number, gap: number, cols?: number, most = BOX_COMFORT, draw = false) => {
      if (!draw) [spent, trials] = [spent + cost, trials + 1];
      const need = longest * BOX_MIN + (longest - 1) * gap + 2 * margin;
      return { margin, gap, cols, most, lay: layoutAt(run, o, need > W && need <= W * (o.stretch ?? 1) ? need : W, { margin, least: gap, cols, most, clear, draw }) };
    };
    let best = at(G.margin, G.gap);
    // lines that pass rows: the boxes stand a lane's width apart, so such a line takes the space between two
    // boxes near its ends. Only where that costs no row and leaves the boxes comfortable (or as wide as they were)
    if (best.lay.passing > 0 && afford()) {
      const open = at(G.margin, G.gapLane);
      if (!worse(open.lay, best.lay) && open.lay.rows <= best.lay.rows && open.lay.boxW >= Math.min(best.lay.boxW, BOX_OPEN)) best = open;
    }
    // where a lane's width would leave the boxes too narrow (the 460px panel) and a line goes round a row: as far
    // apart as the narrowest boxes of that many to a row allow, when the line then passes between two of them
    // with room to spare
    if (best.lay.outer > 0 && best.gap < G.gapLane && best.lay.perRow > 1 && afford()) {
      const room = Math.floor((W - 2 * G.margin - best.lay.perRow * BOX_MIN) / (best.lay.perRow - 1));
      const gap = Math.min(G.gapLane, room - (room % 2));
      if (gap >= 2 * G.keep + 4) {
        const apart = at(G.margin, gap);
        if (!worse(apart.lay, best.lay) && apart.lay.rows <= best.lay.rows && apart.lay.outer < best.lay.outer) best = apart;
      }
    }
    // a line that still goes round a row's end runs in the margin: a gutter there, so it stands clear of the
    // boxes and of the drawing's edge, where that costs no row
    if (best.lay.outer > 0 && afford()) {
      const wide = at(G.gutter, best.gap);
      if (!worse(wide.lay, best.lay) && wide.lay.rows <= best.lay.rows) best = wide;
    }
    const gap = best.gap;
    const tryAt = (margin: number, cols?: number, most?: number) => {
      const trial = at(margin, gap, cols, most);
      if (worse(best.lay, trial.lay)) best = trial;
      return trial.lay;
    };
    const widest = Math.max(G.margin, Math.min(G.marginMost, Math.floor((W - BOX_MIN) / 2)));
    const perRow = best.lay.perRow;
    // lines that share a place: wider margins hold more of them (a tight child gains nothing by a margin)
    for (let m = best.margin + G.lane; best.lay.shared && m <= widest && afford(); m += G.lane) tryAt(m);
    // then fewer boxes to a row: more room beside them for the passing lines, and wider boxes for the lines into
    // a tight child. Once only tight children are left and the boxes grow no wider, fewer still gains nothing.
    // Never under half the boxes a row holds (nor under two): a run whose lines still share a place then is
    // easier read with them than as a column of single boxes many screens long
    const fewest = Math.max(2, Math.ceil(perRow / 2));
    for (let cols = perRow - 1, width = best.lay.boxW; best.lay.crowded && cols >= fewest && afford(); cols--) {
      const trial = tryAt(widest, cols);
      if (!best.lay.shared && trial.boxW <= width) break;
      width = Math.max(width, trial.boxW);
    }
    // lines still share a place: the narrowest boxes, which leave them the most room
    for (let cols = perRow - 1; best.lay.shared && cols >= fewest && afford(); cols--) tryAt(widest, cols, BOX_MIN);
    // and still: that many of the narrowest boxes, and all the width they leave at the sides for the lines
    if (best.lay.shared && fewest < perRow && afford()) tryAt(Math.max(widest, Math.floor((W - fewest * BOX_MIN - (fewest - 1) * gap) / 2)), fewest, BOX_MIN);
    return { ...best, draw: () => at(best.margin, best.gap, best.cols, best.most, true).lay };
  };
  // two lanes clear of each other where the run has the room; a run so dense that lines then have to share a
  // place is laid out again with them one lane clear, which holds twice as many, and then nearer still
  let best = arrange(2 * G.lane);
  for (const clear of [G.lane, G.laneLeast]) {
    if (!best.lay.shared || !afford()) break;
    const denser = arrange(clear);
    if (worse(best.lay, denser.lay)) best = denser;
  }
  return { ...best.draw(), trials };
}

/** Whether layout `a` is more crowded than `b`: two edges on one line first (nobody can tell them apart), then
 *  arrowheads that touch. */
const worse = (a: BoxLayout, b: BoxLayout) => a.shared > b.shared || (a.shared === b.shared && a.crowded > b.crowded);

/** One layout: `margin` px free at each side, the boxes of a row at least `least` px apart, and at most `cols`
 *  boxes to a row when that is given (the boxes are then no wider than `most`, so the room they leave goes to
 *  the passing lines). A passing line keeps `clear` px from the other nets' lines where a place that clear is
 *  free, and `lane` px in any case (`clear` itself, when that is less). With `draw` off it places everything
 *  and counts what is crowded, but draws no line. */
function layoutAt(run: Run, o: LayoutOpts, W: number, { margin, least, cols, most, clear, draw }: { margin: number; least: number; cols: number | undefined; most: number; clear: number; draw: boolean }): BoxLayout {
  const byId = new Map(run.nodes.map((n) => [n.id, n]));
  const measure = o.measure ?? estimate;
  const avail = W - 2 * margin;
  const widthFor = (k: number) => Math.floor((avail - (k - 1) * least) / k);
  const maxCols = Math.max(1, Math.min(cols ?? Infinity, Math.floor((avail + least) / (BOX_MIN + least))));
  const shape = frontiers(run.nodes, maxCols);
  const facts = new Map(run.nodes.map((n) => [n.id, factsOf(n, run, o.bot)]));

  // one width for every box: what the widest node would like on one line, narrowed to put the widest frontier on
  // one row; a frontier that would need boxes under BOX_MIN wraps instead, and the boxes are then as narrow as
  // the widest frontier that does fit a row needs (at least three to a row, or the comfortable width)
  const want = Math.min(
    BOX_MAX,
    Math.max(
      BOX_MIN,
      ...run.nodes.map((n) => {
        const st = statusOf(n, run);
        const f = facts.get(n.id)!;
        const title = measure(titleOf(n), "title") + (shape.origin.has(n.id) ? G.icon + G.iconGap : 0);
        const ran = (f.mark ? G.mark + G.markGap : 0) + measure([...f.parts, f.via].filter(Boolean).join(SEP), "text");
        const status = G.icon + G.iconGap + measure(st.timed ? `${st.word} ${LONGEST_DURATION}` : st.word, "text");
        return Math.ceil(Math.max(title, ran, status)) + 2 * G.padX + 2 * G.border;
      }),
    ),
  );
  const sizes = shape.rows.map((r) => r.length);
  const longest = Math.max(1, ...sizes);
  const fits = Math.max(0, ...sizes.filter((n) => n <= maxCols));
  const per = longest <= maxCols ? longest : Math.max(fits, Math.min(maxCols, Math.max(Math.min(3, maxCols), Math.floor((avail + least) / (BOX_COMFORT + least)))));
  // a box and a gap are an even number of px together (see the rows' gap): a px more where the row has it, else one less
  const cap = Math.min(widthFor(per), cols === undefined ? Infinity : most);
  const wide = Math.max(BOX_MIN, Math.min(want, cap));
  const boxW = (wide + least) % 2 === 0 ? wide : wide < cap ? wide + 1 : Math.max(BOX_MIN, wide - 1);
  const inner = innerOf(boxW);
  const perRow = Math.max(1, Math.min(maxCols, Math.floor((avail + least) / (boxW + least))));

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
  // the room the widest row's boxes leave goes between them, up to `gapMost`, and every row stands its boxes that
  // far apart, in the middle of the width: a row one box shorter than the row under it then has each box over a
  // space between two of that row, so a line that passes the row under it comes straight down from its parent.
  // (A box and a gap are an even number of px together, or half of them would not be a whole px.)
  const widest = Math.max(1, ...vrows.map((r) => r.ids.length));
  let gap = widest > 1 ? Math.max(least, Math.min(G.gapMost, Math.floor((avail - widest * boxW) / (widest - 1)))) : least;
  if ((boxW + gap) % 2 && gap > least) gap -= 1;
  const rowOf = new Map<string, number>();
  const xOf = new Map<string, number>();
  vrows.forEach((r, v) => {
    const k = r.ids.length;
    r.ids.forEach((id, i) => {
      rowOf.set(id, v);
      xOf.set(id, Math.round(margin + (avail - (k * boxW + (k - 1) * gap)) / 2 + i * (boxW + gap)));
    });
  });
  const mid = (id: string) => xOf.get(id)! + boxW / 2;

  // every box of a row is as tall as the row's longest box needs
  const said = new Map(run.nodes.map((n) => [n.id, factLines(facts.get(n.id)!, inner, measure)]));
  const heightOf = (id: string) => boxHeight(titleLines(byId.get(id)!, shape.origin.has(id), inner, measure), said.get(id)!.lines.length);
  const rowH = vrows.map((r) => Math.max(...r.ids.map(heightOf)));
  const hang = [...rowOf.keys()].every((id) => said.get(id)!.hang);

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
  // `port` px apart (less only when its top edge is too short for that), left to right in the order of where they
  // come from: two arrowheads never stand on each other. The space under row c is channel c; a line from above and
  // a line going below that belong to different nets never share a column there, or the two would read as one
  // line: a point keeps `lane` px from the lines the row above sends down.
  const into = new Map<string, typeof nets>();
  for (const n of nets) for (const c of n.children) (into.get(c) ?? into.set(c, []).get(c)!).push(n);
  const stubs = new Map<number, { x: number; net: string }[]>(); // channel -> the lines that enter it from above
  for (const n of nets) for (const p of n.parents) (stubs.get(rowOf.get(p)!) ?? stubs.set(rowOf.get(p)!, []).get(rowOf.get(p)!)!).push({ x: snap(mid(p)), net: n.key });
  // ---- a net whose ends are more than one row apart runs down a lane beside the rows it passes: `keep` px from
  // their boxes (so never through a space between two boxes under twice that: it goes round), `edge` px from the
  // drawing's side
  const wPx = W;
  type Room = [lo: number, hi: number, between: boolean]; // a free space beside a row's boxes; `between` two of them, or at an end of the row
  const free = (rows: number[]): Room[] => {
    const taken = rows.flatMap((v) => vrows[v].ids.map((id) => [xOf.get(id)!, xOf.get(id)! + boxW] as [number, number])).sort((a, b) => a[0] - b[0]);
    const spans: Room[] = [];
    let at = 0;
    let first = true;
    for (const [a, b] of [...taken, [wPx, wPx] as [number, number]]) {
      if (a > at) {
        const last = a === wPx;
        const [lo, hi] = [at + (first ? G.edge : G.keep), a - (last ? G.edge : G.keep)];
        if (hi >= lo) spans.push([lo, hi, !first && !last]);
      }
      at = Math.max(at, b);
      first = false;
    }
    return spans;
  };
  const reach = new Map<string, [number, number]>(); // net -> its first and last channel
  for (const n of nets) {
    const cs = [...n.parents.map((p) => rowOf.get(p)!), ...n.children.map((c) => rowOf.get(c)! - 1)];
    reach.set(n.key, [Math.min(...cs), Math.max(...cs)]);
  }
  // a net ends at a child when that child is the only one in its last row: everything of the net between the row
  // above and the child leads into it and nowhere else. The nets that end at one child come into it as one line:
  // one level stretch over it, one point on its top, one arrowhead. (A net that goes on below, or to a second
  // child of the row, keeps a point of its own: joined, the others' parents would read as leading there too.)
  const endOf = new Map<string, string>(); // net -> the child it ends at
  for (const n of nets) {
    const last = n.children.filter((k) => rowOf.get(k)! - 1 === reach.get(n.key)![1]);
    if (last.length === 1) endOf.set(n.key, last[0]);
  }
  /** The name under which net n's line runs in channel c: its own, or the one it shares with the nets it joins there. */
  const lineOf = (n: (typeof nets)[number], c: number) => (endOf.has(n.key) && rowOf.get(endOf.get(n.key)!)! - 1 === c ? `>${endOf.get(n.key)}` : n.key);
  const extent = (xs: number[]) => (xs.length ? Math.max(...xs) - Math.min(...xs) : 0);
  const beside = vrows.map((_, r) => free([r])); // per row, the free spaces beside its boxes
  const pitch = Math.min(G.lane, clear); // the least two passing lines stand apart in this layout
  /** One pass: every line into a child gets its point on the child's top, then every line that passes rows its
   *  place beside each. `arrive` says, per net and child, where the net's line comes down to the child (from a
   *  pass before): the child's points then stand in that order, so two lines into it do not cross on the way. */
  const route = (arrive?: Map<string, number>) => {
    let crowded = 0; // the lines that found no place of their own
    let shared = 0; // of them, the lines that pass rows on another net's place
    const tight: string[] = []; // the children whose arrowheads stand nearer than an arrowhead apart
    const port = new Map<string, number>(); // `${net}\n${child}` -> x
    for (const [child, ns] of into) {
      const from = (n: (typeof nets)[number]) => arrive?.get(`${n.key}\n${child}`) ?? meanX(n.parents);
      // the nets that end at this child share a point; every other net has its own
      const ending = ns.filter((n) => endOf.get(n.key) === child);
      const lead = (g: typeof nets) => g.reduce((a, n) => a + from(n), 0) / g.length;
      const sorted = [...(ending.length ? [ending] : []), ...ns.filter((n) => endOf.get(n.key) !== child).map((n) => [n])].sort((a, b) => lead(a) - lead(b) || a[0].key.localeCompare(b[0].key));
      const k = sorted.length;
      const [left, right] = [snap(xOf.get(child)! + G.portInset), snap(xOf.get(child)! + boxW - G.portInset - 1)];
      const step = Math.min(G.port, Math.floor((right - left) / Math.max(1, k - 1)));
      // a line one of whose parents stands right over the child comes straight down from it: its point is under that
      // parent's line, and the others' stand beside it. With no such line the points stand either side of the
      // child's middle (one line: the middle itself)
      const over = sorted.map((g) => g.flatMap((n) => n.parents).filter((q) => rowOf.get(q) === rowOf.get(child)! - 1).map((q) => snap(mid(q))).filter((x) => x >= left && x <= right).sort((a, b) => Math.abs(a - mid(child)) - Math.abs(b - mid(child)))[0]);
      const straight = over.map((x, i) => [x, i] as const).filter((e): e is readonly [number, number] => e[0] !== undefined).sort((a, b) => Math.abs(a[0] - mid(child)) - Math.abs(b[0] - mid(child)))[0];
      // the lines of other nets that come down from the row above, per line: its point stays `lane` px off them
      const above = stubs.get(rowOf.get(child)! - 1) ?? [];
      const off = sorted.map((g) => above.filter((st) => g.every((n) => n.key !== st.net) && st.x > left - G.lane && st.x < right + G.lane).map((st) => st.x).sort((a, b) => a - b));
      const right_ = (x: number, zone: number[]) => zone.reduce((at, z) => (Math.abs(at - z) < G.lane ? z + G.lane : at), x);
      const left_ = (x: number, zone: number[]) => [...zone].reverse().reduce((at, z) => (Math.abs(at - z) < G.lane ? z - G.lane : at), x);
      /** The points `apart` px from each other, or null where the top edge does not hold them so. With `held` the
       *  line that comes straight down stays under its parent and the others stand out from it to both sides. */
      const stand = (apart: number, held?: readonly [number, number]): number[] | null => {
        // beside a held point each side is spaced by the room that side has (a full `port` where it has it)
        const [toLeft, toRight] = held ? [held[1] ? Math.min(step, Math.floor((held[0] - left) / held[1])) : step, k - 1 - held[1] ? Math.min(step, Math.floor((right - held[0]) / (k - 1 - held[1]))) : step] : [step, step];
        const want = sorted.map((_, i) => (held ? held[0] + (i - held[1]) * (i < held[1] ? toLeft : toRight) : snap(mid(child) + (i - (k - 1) / 2) * step)));
        const xs: number[] = [];
        if (held) {
          xs[held[1]] = held[0];
          for (let i = held[1] + 1; i < k; i++) xs[i] = right_(Math.max(want[i], xs[i - 1] + apart), off[i]);
          for (let i = held[1] - 1; i >= 0; i--) xs[i] = left_(Math.min(want[i], xs[i + 1] - apart), off[i]);
        } else {
          sorted.forEach((_, i) => xs.push(right_(Math.max(want[i], i ? xs[i - 1] + apart : left), off[i])));
          if (xs[k - 1] > right) {
            xs[k - 1] = left_(right, off[k - 1]);
            for (let i = k - 2; i >= 0; i--) xs[i] = left_(Math.min(xs[i], xs[i + 1] - apart), off[i]);
          }
        }
        return xs[0] >= left && xs[k - 1] <= right && xs.every((x, i) => !i || x - xs[i - 1] >= apart) && xs.every((x, i) => off[i].every((z) => Math.abs(x - z) >= G.lane)) ? xs : null;
      };
      // as far apart as the top edge holds them: `portClear`, or less where that many lines do not fit. At each
      // distance the line that comes straight down stays straight where the others then still fit beside it (a
      // line a few px off its parent's would turn twice on the way), and gives way where they do not. Under an
      // arrowhead and two px apart the arrowheads touch: the child is tight
      let placed: number[] | null = null;
      let spaced = 0;
      for (const apart of [G.portClear, 10, G.arrowW + 2, 7, 5, 4, 3, 2, 1]) {
        placed = (straight && stand(apart, straight)) || stand(apart);
        if (placed) {
          spaced = apart;
          break;
        }
      }
      // more lines than the top edge holds an arrowhead apart: they stand as near as they must, still off the lines
      // the row above sends down (evenly, when not even a pixel apart), and count as crowded, so the layout is
      // tried again with more room
      if (spaced < G.arrowW + 2) {
        crowded += k;
        tight.push(child);
      }
      const xs = placed ?? sorted.map((_, i) => snap(mid(child) + (i - (k - 1) / 2) * step));
      sorted.forEach((g, i) => g.forEach((n) => port.set(`${n.key}\n${child}`, xs[i])));
    }

    /** A net's pins in channel c: its parents' lines down from row c, and its points on the children of row c + 1. */
    const pinsOf = (n: (typeof nets)[number], c: number) => [...n.parents.filter((p) => rowOf.get(p) === c).map((p) => snap(mid(p))), ...n.children.filter((k) => rowOf.get(k)! - 1 === c).map((k) => port.get(`${n.key}\n${k}`)!)];
    // channel -> every net's pins in it, under the name its line runs by there: the nets that end at one child
    // are one line over it, and the lane of one of them may come down right over the point they share
    const pinned = new Map<number, { x: number; net: string }[]>();
    for (const n of nets) for (const c of new Set([...n.parents.map((p) => rowOf.get(p)!), ...n.children.map((k) => rowOf.get(k)! - 1)])) for (const x of pinsOf(n, c)) (pinned.get(c) ?? pinned.set(c, []).get(c)!).push({ x, net: lineOf(n, c) });
    // per row, in order of x: the lines a place beside that row has to keep clear of. The pins of the channel above
    // it and of the one below, and the lines that pass it or a row next to it (they reach into the same channels)
    const lined: { x: number; net: string }[][] = vrows.map(() => []);
    const line = (r: number, at: { x: number; net: string }) => {
      const row = lined[r];
      if (!row) return;
      let [from, to] = [0, row.length];
      while (from < to) {
        const mid = (from + to) >> 1;
        if (row[mid].x < at.x) from = mid + 1;
        else to = mid;
      }
      row.splice(from, 0, at);
    };
    for (const [c, pins] of pinned) for (const pin of pins) for (const r of [c, c + 1]) line(r, pin);
    const lanes = new Map<string, Map<number, number>>(); // net -> per row it passes, the x of its line beside that row's boxes
    let outer = 0; // the times such a line passes a row round its end
    for (const n of nets) {
      const [lo, hi] = reach.get(n.key)!;
      if (lo === hi) continue;
      // the lane joins the net's level stretches, one in each channel it has pins in: the shorter those are, the
      // better. Their length is least for a lane between the pins; among those places, the one nearest the middle pin
      const spans = [...new Set([...n.parents.map((p) => rowOf.get(p)!), ...n.children.map((c) => rowOf.get(c)! - 1)])].map((c) => pinsOf(n, c)).map((xs) => [Math.min(...xs), Math.max(...xs)]);
      const wire = (x: number) => spans.reduce((sum, [a, b]) => sum + Math.max(b, x) - Math.min(a, x), 0);
      const xs = [...n.parents.map(mid), ...n.children.map((c) => port.get(`${n.key}\n${c}`)!)].sort((a, b) => a - b);
      const middle = xs[Math.floor((xs.length - 1) / 2)];
      const ideal = [middle, ...spans.flat()].sort((a, b) => wire(a) - wire(b) || Math.abs(a - middle) - Math.abs(b - middle))[0];
      // a place beside row r is taken when another net's line stands within `lane` of it: one that passes this row
      // or the rows next to it (their lines reach into the same channels), or a pin in the channel above or below.
      // A place twice that far from every such line is better still
      const rows = Array.from({ length: hi - lo }, (_, i) => lo + 1 + i);
      const rooms = rows.map((r) => beside[r]);
      const own = lineOf(n, hi); // the name it shares with the nets it joins over its last child
      /** Whether a place at `x` beside the i-th of these rows is within `apart` of another net's line there. */
      const busy = (x: number, i: number, apart = pitch) => {
        const taken = lined[rows[i]];
        let [from, to] = [0, taken.length]; // the first of them right of x - apart
        while (from < to) {
          const mid = (from + to) >> 1;
          if (taken[mid].x <= x - apart) from = mid + 1;
          else to = mid;
        }
        for (; from < taken.length && taken[from].x < x + apart; from++) if (taken[from].net !== n.key && taken[from].net !== own) return true;
        return false;
      };
      // per row and free space, the places nearest `to` that are not taken: the line stands as near its own ends as
      // it can while keeping `ease` from the boxes, and in the middle of a narrow space between two boxes; on a half
      // pixel. The places beside that one, down to `keep` from a box, are taken only when it is: the nearest free
      // one on either side. A place `clear` of every other line before one that is only a lane clear
      const places = (i: number, [a, b, between]: Room, to: number): number[] => {
        const pad = between && b - a <= G.centre ? (b - a) / 2 : Math.min(G.ease - G.keep, (b - a) / 2);
        const near = snap(Math.min(Math.max(to, a + pad), b - pad) - 0.5);
        // the middle of a narrow space between two boxes is the place for a line there, while it is a lane clear of
        // the others: a line that hugs one of the two boxes to stand further from another line reads worse
        if (between && b - a <= G.centre && !busy(near, i)) return [near];
        for (const apart of clear > pitch ? [clear, pitch] : [pitch]) {
          if (!busy(near, i, apart)) return [near];
          const sides: number[] = [];
          for (let x = near + pitch; x <= b + 0.5; x += pitch)
            if (!busy(x, i, apart)) {
              sides.push(x);
              break;
            }
          for (let x = near - pitch; x >= a - 0.5; x -= pitch)
            if (!busy(x, i, apart)) {
              sides.push(x);
              break;
            }
          if (sides.length) return sides;
        }
        return [];
      };
      let options = rows.map((_, i) => rooms[i].flatMap((room) => places(i, room, ideal)));
      // a place a neighbouring row offers is offered here too where this row is free there: the line then runs
      // straight on from one row to the next (twice, so a straight run can pass three rows)
      for (let round = 0; round < 2; round++)
        options = options.map((own, i) => {
          const more = [...(options[i - 1] ?? []), ...(options[i + 1] ?? [])].filter((x) => !own.includes(x) && rooms[i].some(([a, b]) => x >= a - 0.5 && x <= b + 0.5) && !busy(x, i));
          return [...own, ...new Set(more)];
        });
      // a row with no free place: the line shares one (the nearest it could have had), and the layout is crowded
      const full = options.some((o) => !o.length);
      if (full) {
        crowded++;
        shared++;
        options = options.map((o, i) => (o.length ? o : [rooms[i].length ? rooms[i].map(([a, b]) => snap(Math.min(Math.max(ideal, a), b) - 0.5)).sort((p, q) => wire(p) - wire(q))[0] : snap(ideal)]));
      }
      // the places that make the net's level stretches shortest, row by row: in the channel under row r the stretch
      // reaches over the net's pins there, the line that came down past row r and the line that goes on past row r + 1
      const reaches = new Map(Array.from({ length: hi - lo + 1 }, (_, i) => [lo + i, pinsOf(n, lo + i)] as const).map(([c, pins]) => [c, pins.length ? ([Math.min(...pins), Math.max(...pins)] as const) : null])); // channel -> how far the net's pins there reach
      const stretch = (c: number, above?: number, below?: number) => {
        const at = reaches.get(c);
        const xs = [...(at ?? []), ...(above === undefined ? [] : [above]), ...(below === undefined ? [] : [below])];
        // a step aside between two rows costs a turn's worth; one too short to turn twice in (a kink) four
        return extent(xs) + (above !== undefined && below !== undefined && above !== below ? (Math.abs(above - below) < 2 * G.r ? 4 * G.r : G.r) : 0);
      };
      let costs = options[0].map((x) => stretch(lo, undefined, x) + Math.abs(x - ideal) / 1000);
      const from: number[][] = [];
      for (let i = 1; i < rows.length; i++) {
        const next: number[] = [];
        from[i] = [];
        options[i].forEach((x, j) => {
          const each = options[i - 1].map((prev, q) => costs[q] + stretch(rows[i] - 1, prev, x));
          const at = each.indexOf(Math.min(...each));
          next[j] = each[at] + Math.abs(x - ideal) / 1000;
          from[i][j] = at;
        });
        costs = next;
      }
      const last = options[rows.length - 1].map((x, j) => costs[j] + stretch(hi, x, undefined));
      const chosen = new Map<number, number>();
      for (let i = rows.length - 1, j = last.indexOf(Math.min(...last)); i >= 0; j = from[i]?.[j] ?? 0, i--) chosen.set(rows[i], options[i][j]);
      lanes.set(n.key, chosen);
      for (const [r, x] of chosen) {
        for (const q of [r - 1, r, r + 1]) line(q, { x, net: n.key });
        const xs = vrows[r].ids.map((id) => xOf.get(id)!);
        if (x < Math.min(...xs) || x > Math.max(...xs) + boxW) outer++;
      }
    }
    return { port, pinsOf, lanes, crowded, shared, tight, outer };
  };
  /** Where each net's line comes down to each child in a pass (the mean of where its last level stretch at the
   *  child starts: its parents right above, and its lane), and how many children's points do not stand in the
   *  order their lines arrive: two lines into such a child cross on the way. */
  const arrivals = (pass: ReturnType<typeof route>) => {
    const arrive = new Map<string, number>();
    let crossed = 0;
    for (const [child, ns] of into) {
      if (ns.length < 2) continue;
      const c = rowOf.get(child)! - 1;
      const comes = (n: (typeof nets)[number]) => {
        const xs = [...n.parents.filter((q) => rowOf.get(q) === c).map((q) => snap(mid(q))), ...(pass.lanes.get(n.key)?.has(c) ? [pass.lanes.get(n.key)!.get(c)!] : [])];
        return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : meanX(n.parents);
      };
      for (const n of ns) arrive.set(`${n.key}\n${child}`, comes(n));
      const arriving = [...ns].sort((a, b) => comes(a) - comes(b) || a.key.localeCompare(b.key)).map((n) => pass.port.get(`${n.key}\n${child}`)!);
      if (arriving.some((x, i) => i && x < arriving[i - 1])) crossed++;
    }
    return { arrive, crossed };
  };
  // a child's points stand in the order of its parents at first; a line that comes round by a lane may arrive from
  // the other side. Then once more (twice at most) with the points in the order the lines arrived, and the pass
  // is kept when fewer lines cross for it and none shares a place that had its own
  let plan = route();
  let seen = arrivals(plan);
  for (let pass = 0; pass < 2 && seen.crossed; pass++) {
    const next = route(seen.arrive);
    const then = arrivals(next);
    if (next.shared > plan.shared || then.crossed >= seen.crossed) break;
    [plan, seen] = [next, then];
  }
  const { port, lanes, crowded, shared, tight, outer } = plan;
  // ---- a line that comes down a lane within a port's width of its point on the child gets the point under the
  // lane: straight in, with no turn. A line that leaves for a lane so near its parent's middle that it would
  // turn twice within two radii (a kink) leaves the parent over the lane. Both stay on the box's edge, clear of
  // its corners; a point keeps its place among the child's other points, as far from them as it was (or
  // `portClear`), and `lane` px off the lines from above
  const exit = new Map<string, number>(); // parent -> where its line leaves its bottom, when not at the middle
  const exitOf = (q: string) => exit.get(q) ?? snap(mid(q));
  for (const n of nets) {
    const own = lanes.get(n.key);
    if (!own) continue;
    for (const q of n.parents) {
      const at = own.get(rowOf.get(q)! + 1);
      const from = snap(mid(q));
      if (at === undefined || at === from || Math.abs(at - from) >= 2 * G.r || at < xOf.get(q)! + G.portInset || at > xOf.get(q)! + boxW - G.portInset) continue;
      // not where a child stands right under the parent's middle: that line is straight as it is
      if (n.children.some((k) => rowOf.get(k) === rowOf.get(q)! + 1 && port.get(`${n.key}\n${k}`) === from)) continue;
      exit.set(q, at);
    }
    for (const k of n.children) {
      const c = rowOf.get(k)! - 1;
      const at = own.get(c);
      const was = port.get(`${n.key}\n${k}`)!;
      // only a line that reaches the child by the lane alone. The nets that share its point there move with it,
      // unless one of them comes straight down into that point (from a parent right over it, or by its own lane)
      if (at === undefined || at === was || Math.abs(at - was) > G.port || n.parents.some((q) => rowOf.get(q) === c)) continue;
      if (at < snap(xOf.get(k)! + G.portInset) || at > snap(xOf.get(k)! + boxW - G.portInset - 1)) continue; // the points' own range
      const group = into.get(k)!.filter((m) => port.get(`${m.key}\n${k}`) === was);
      if (group.some((m) => m.parents.some((q) => rowOf.get(q) === c && exitOf(q) === was) || (m !== n && lanes.get(m.key)?.get(c) === was))) continue;
      const others = into.get(k)!.filter((m) => !group.includes(m)).map((m) => port.get(`${m.key}\n${k}`)!);
      if (others.some((x) => (x - was) * (x - at) <= 0 || Math.abs(at - x) < Math.min(G.portClear, Math.abs(was - x)))) continue;
      if ((stubs.get(c) ?? []).some((st) => group.every((m) => m.key !== st.net) && Math.abs(st.x - at) < G.lane)) continue;
      for (const m of group) port.set(`${m.key}\n${k}`, at);
    }
  }
  /** A net's pins in channel c: its parents' lines down from row c, and its points on the children of row c + 1. */
  const pinsOf = (n: (typeof nets)[number], c: number) => [...n.parents.filter((q) => rowOf.get(q) === c).map(exitOf), ...n.children.filter((k) => rowOf.get(k)! - 1 === c).map((k) => port.get(`${n.key}\n${k}`)!)];
  /** Where net n's line stands in channel c besides its pins: where it came down past row c, and where it goes on
   *  past row c + 1. */
  const through = (n: (typeof nets)[number], c: number) => {
    const [lo, hi] = reach.get(n.key)!;
    const own = lanes.get(n.key);
    return { down: own && c > lo && c <= hi ? [own.get(c)!] : [], up: own && c >= lo && c < hi ? [own.get(c + 1)!] : [] };
  };

  // ---- tracks: the level stretches of one channel that would overlap each take their own height
  const track = new Map<string, number>(); // `${net}\n${channel}` -> track
  const tracks: number[] = vrows.map(() => 0);
  for (let c = 0; c < vrows.length - 1; c++) {
    const lines = new Map<string, typeof nets>(); // the nets that run as one line here, by that line's name
    for (const n of nets) (lines.get(lineOf(n, c)) ?? lines.set(lineOf(n, c), []).get(lineOf(n, c))!).push(n);
    const items = [...lines]
      .map(([key, ns]) => {
        const pins = ns.flatMap((n) => pinsOf(n, c));
        const pass = ns.map((n) => through(n, c));
        const xs = [...pins, ...pass.flatMap((p) => [...p.down, ...p.up])];
        // a line that passes straight through, with no pin of its net here, has no level stretch in this channel
        if (!xs.length || (!pins.length && extent(xs) < 0.5)) return null;
        return {
          key,
          ns,
          lo: Math.min(...xs),
          hi: Math.max(...xs),
          down: [...ns.flatMap((n) => n.parents.filter((q) => rowOf.get(q) === c).map(exitOf)), ...pass.flatMap((p) => p.down)],
          up: [...ns.flatMap((n) => n.children.filter((k) => rowOf.get(k)! - 1 === c).map((k) => port.get(`${n.key}\n${k}`)!)), ...pass.flatMap((p) => p.up)],
        };
      })
      .filter((x): x is NonNullable<typeof x> => x !== null)
      .sort((a, b) => a.lo - b.lo || a.hi - b.hi);
    const ends: number[] = [];
    const on = new Map<string, number>();
    for (const it of items) {
      // two stretches at one height keep more than a turn apart, or their rounded ends would read as one line
      let tr = ends.findIndex((e) => e < it.lo - 2 * G.r);
      if (tr < 0) tr = ends.length;
      ends[tr] = it.hi;
      on.set(it.key, tr);
    }
    // which track stands above which: the order in which the fewest lines pass over another net's stretch. A line
    // from above (a parent's, or a lane coming down) passes the stretches over its own; a line going below (into a
    // child, or a lane going on) passes the ones under it.
    const marks = items.map((it) => ({ ...it, tr: on.get(it.key)! }));
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
    for (const m of marks) for (const n of m.ns) track.set(`${n.key}\n${c}`, place[m.tr]);
    tracks[c] = ends.length;
  }

  // ---- heights
  const rowY: number[] = [];
  const chTop: number[] = [];
  const more: BoxLayout["more"] = [];
  let y = 0;
  vrows.forEach((_, v) => {
    rowY[v] = y;
    y += rowH[v];
    const m = moreAfter.get(v);
    if (m) {
      more.push({ ...m, x: xOf.get(vrows[v].ids[0])!, y });
      y += G.moreH;
    }
    chTop[v] = y;
    if (v < vrows.length - 1) y += tracks[v] ? G.stub + (tracks[v] - 1) * G.track + G.drop : G.rowGap;
  });
  const boxes: BoxAt[] = [];
  vrows.forEach((r, v) => r.ids.forEach((id) => boxes.push({ id, x: xOf.get(id)!, y: rowY[v], w: boxW, h: rowH[v], frontier: r.frontier, row: v, index: boxes.length })));
  const at = new Map(boxes.map((b) => [b.id, b]));

  // ---- the lines: one path an edge. From the parent's bottom down to its net's level stretch, along it to the
  // child's point (past the rows between them at the net's place beside each, when the child stands further
  // down), and down to its arrowhead.
  const busY = (key: string, c: number) => snap(chTop[c] + G.stub + (track.get(`${key}\n${c}`) ?? 0) * G.track);
  const tones = new Map(run.nodes.map((n) => [n.id, statusOf(n, run).tone]));
  const tone = (id: string) => tones.get(id)!;
  const routes: { net: string; from: string; to: string; pts: [number, number][] }[] = [];
  const heads: EdgeHead[] = [];
  const headOf = new Map<string, EdgeHead>(); // child and line -> the head the line's nets end in
  const drawn = new Set<string>();
  for (const net of draw ? nets : []) {
    const own = lanes.get(net.key);
    for (const c of net.children) {
      const cc = rowOf.get(c)! - 1;
      const xc = port.get(`${net.key}\n${c}`)!;
      const end = rowY[rowOf.get(c)!] - G.arrow;
      for (const p of net.parents) {
        const cp = rowOf.get(p)!;
        const xp = exitOf(p);
        const pts: [number, number][] = [[xp, rowY[cp] + rowH[cp]]];
        if (cp === cc || !own) pts.push([xp, busY(net.key, cc)]);
        else {
          pts.push([xp, busY(net.key, cp)]);
          for (let r = cp + 1; r <= cc; r++) pts.push([own.get(r)!, busY(net.key, r - 1)], [own.get(r)!, busY(net.key, r)]);
        }
        pts.push([xc, busY(net.key, cc)], [xc, end]);
        drawn.add(`${p}>${c}`);
        routes.push({ net: net.key, from: p, to: c, pts });
      }
      const shared = headOf.get(`${c}\n${lineOf(net, cc)}`);
      if (shared) {
        shared.nets.push(net.key);
        shared.from = [...shared.from, ...net.parents].sort(order);
      } else {
        const head: EdgeHead = { key: `${net.key}:h:${c}`, net: net.key, nets: [net.key], x: xc, y: end + G.arrow, from: [...net.parents], to: c };
        headOf.set(`${c}\n${lineOf(net, cc)}`, head);
        heads.push(head);
      }
    }
  }
  const drawnLines = drawLines(routes.map((rt) => ({ ...rt, key: `${rt.net}:${rt.from}>${rt.to}`, tone: tone(rt.from) })));
  const flows = flowsOf(routes, (id) => byId.get(id)!.state === "running");
  return {
    inner,
    perRow,
    boxW,
    gap,
    rows: vrows.length,
    passing: lanes.size,
    outer,
    w: wPx,
    h: y,
    boxes,
    at,
    more,
    nets: nets.map(({ key, parents, children }) => ({ key, parents, children })),
    lines: drawnLines,
    heads,
    flows,
    drawn,
    crowded,
    shared,
    tight,
    hang,
    shape,
  };
}

/** The lines through their points. Where an upright stretch of one passes over another net's level stretch it
 *  leaves a gap: a crossing is not a join. */
function drawLines(routes: Omit<EdgeLine, "d">[]): EdgeLine[] {
  const level = new Map<string, { net: string; y: number; x1: number; x2: number }>();
  for (const rt of routes)
    for (let i = 1; i < rt.pts.length; i++) {
      const [[ax, ay], [bx, by]] = [rt.pts[i - 1], rt.pts[i]];
      if (ay === by && ax !== bx) level.set(`${rt.net} ${ay} ${Math.min(ax, bx)} ${Math.max(ax, bx)}`, { net: rt.net, y: ay, x1: Math.min(ax, bx), x2: Math.max(ax, bx) });
    }
  const stretches = [...level.values()].sort((a, b) => a.y - b.y);
  const gapsOf = (net: string) => (x: number, lo: number, hi: number) => {
    const ys = new Set<number>();
    let [from, to] = [0, stretches.length]; // the first stretch below lo + hop
    while (from < to) {
      const mid = (from + to) >> 1;
      if (stretches[mid].y <= lo + G.hop) from = mid + 1;
      else to = mid;
    }
    for (let i = from; i < stretches.length && stretches[i].y < hi - G.hop; i++) {
      const h = stretches[i];
      if (h.net !== net && h.x1 < x && x < h.x2) ys.add(h.y);
    }
    return [...ys];
  };
  return routes.map((rt) => ({ ...rt, d: roundedPath(rt.pts, G.curve, gapsOf(rt.net)) }));
}

/** The dash into a running node rides its edges, each drawn from the child back to its parent: the edges into one
 *  child share their last stretch, and drawn from the child their dashes lie on each other there. An edge that
 *  runs onto a stretch another child's dash already rides (the two share a parent) stops there: two dashes out of
 *  step never lie on one line. No gaps: a dash pattern starts again after every gap. */
function flowsOf(routes: { net: string; from: string; to: string; pts: [number, number][] }[], running: (id: string) => boolean): EdgeFlow[] {
  const flows: EdgeFlow[] = [];
  const ridden = new Map<string, { to: string; x1: number; y1: number; x2: number; y2: number }[]>(); // net -> the stretches a dash rides
  for (const rt of routes) {
    if (!running(rt.to)) continue;
    const taken = ridden.get(rt.net) ?? ridden.set(rt.net, []).get(rt.net)!;
    const pts = untilTaken([...rt.pts].reverse(), taken.filter((st) => st.to !== rt.to));
    for (let i = 1; i < pts.length; i++) taken.push({ to: rt.to, x1: Math.min(pts[i - 1][0], pts[i][0]), y1: Math.min(pts[i - 1][1], pts[i][1]), x2: Math.max(pts[i - 1][0], pts[i][0]), y2: Math.max(pts[i - 1][1], pts[i][1]) });
    if (pts.length > 1) flows.push({ key: `${rt.net}:f:${rt.from}>${rt.to}`, net: rt.net, d: roundedPath(pts, G.curve), from: rt.from, to: rt.to });
  }
  return flows;
}

/** `pts` (a line of upright and level steps) up to where it first runs onto one of the `taken` stretches: whole
 *  when it never does. */
function untilTaken(pts: [number, number][], taken: { x1: number; y1: number; x2: number; y2: number }[]): [number, number][] {
  for (let i = 1; i < pts.length; i++) {
    const [[ax, ay], [bx, by]] = [pts[i - 1], pts[i]];
    const upright = Math.abs(ax - bx) < 0.01;
    // how far along this step (from a) the first taken stretch on its line begins
    let first = Infinity;
    for (const st of taken) {
      if (upright ? Math.abs(st.x1 - ax) > 0.01 || Math.abs(st.x2 - ax) > 0.01 : Math.abs(st.y1 - ay) > 0.01 || Math.abs(st.y2 - ay) > 0.01) continue;
      const [a, b, lo, hi] = upright ? [ay, by, st.y1, st.y2] : [ax, bx, st.x1, st.x2];
      if (Math.min(Math.max(a, b), hi) - Math.max(Math.min(a, b), lo) < 0.01) continue; // they only touch, or not even
      first = Math.min(first, b > a ? Math.max(lo - a, 0) : Math.max(a - hi, 0));
    }
    if (first === Infinity) continue;
    const dir = Math.sign(upright ? by - ay : bx - ax);
    const cut: [number, number] = upright ? [ax, ay + dir * first] : [ax + dir * first, ay];
    return first < 0.01 ? pts.slice(0, i) : [...pts.slice(0, i), cut];
  }
  return pts;
}

/** The lines of a drawing in which the person moved boxes (full view). An edge neither of whose ends moved keeps
 *  the way the layout gave it. An edge of a moved box runs between the two boxes as they stand now and still ends
 *  on the child's top, coming down into it: one elbow from the parent's bottom when the child stands below its
 *  parent; when the two stand beside each other, straight across from the parent's side at the height the line
 *  comes in at (the child's top stands within the parent's height), or over from the parent's top (it stands
 *  higher); and round the nearer side of both when one stands over the other. Into a child that did not move it
 *  ends where its net ends on that child, in the arrowhead that is there: a moved parent adds none. Every line
 *  is drawn again, so the gaps stand where lines cross now. No way is sought round the other boxes. */
export function movedLines(
  lay: Pick<BoxLayout, "lines" | "heads" | "flows">,
  rect: (id: string) => Rect,
  moved: Set<string>,
  tone: (id: string) => string,
  running: (id: string) => boolean,
): { lines: EdgeLine[]; heads: EdgeHead[]; flows: EdgeFlow[] } {
  if (!moved.size) return { lines: lay.lines, heads: lay.heads, flows: lay.flows };
  const still = (l: { from: string; to: string }) => !moved.has(l.from) && !moved.has(l.to);
  // the heads on the boxes that did not move stay: a line into such a box still ends in its net's
  const heads: EdgeHead[] = lay.heads.filter((h) => !moved.has(h.to));
  const ends = new Map<string, EdgeHead>(); // a moved child -> the one head its lines end in
  // the last turn before a child stands nearer its top than the layout's level stretches do (`drop` above it): a
  // line drawn here never lies on one of those
  const above = G.arrow + G.r;
  const routes = lay.lines.map((l): Omit<EdgeLine, "d"> => {
    if (still(l)) return l;
    const [pr, cr] = [rect(l.from), rect(l.to)];
    const px = moved.has(l.from) ? snap(pr.x + pr.w / 2) : l.pts[0][0]; // a parent that did not move has one way out: the layout's
    const cx = (moved.has(l.to) ? undefined : lay.heads.find((h) => h.nets.includes(l.net) && h.to === l.to)?.x) ?? snap(cr.x + cr.w / 2);
    const [y1, y2] = [pr.y + pr.h, cr.y - G.arrow];
    const into = snap(cr.y - above);
    let pts: [number, number][];
    if (y2 - y1 >= 2 * G.r) {
      // below its parent: one elbow, nearer the child's top than the layout's level stretches stand (`stub` under
      // the row above), where the parent leaves the room for it; else halfway
      const turn = snap(cr.y - above - y1 >= G.r ? cr.y - above : Math.min((y1 + y2) / 2, cr.y - above));
      pts = [[px, y1], [px, turn], [cx, turn], [cx, y2]];
    } else if (y2 > y1) {
      // just under its parent, too near for that elbow: straight down where the child's point stands under the
      // parent's bottom, else an elbow as flat as the space between the two (a turn rounds as far as it has room)
      pts = cx > pr.x + G.r && cx < pr.x + pr.w - G.r ? [[cx, y1], [cx, y2]] : [[px, y1], [px, (y1 + y2) / 2], [cx, (y1 + y2) / 2], [cx, y2]];
    } else if (Math.max(cr.x - (pr.x + pr.w), pr.x - (cr.x + cr.w)) >= 2 * G.keep) {
      // beside it. The line comes in `above` the child's top: where that height lies within the parent's own,
      // straight across from the parent's side that faces the child; else out of the parent's top and over
      const level = snap(Math.min(cr.y - above, pr.y + pr.h - G.r) - 0.5);
      if (level >= pr.y + G.r) pts = [[cr.x > pr.x ? pr.x + pr.w : pr.x, level], [cx, level], [cx, y2]];
      else {
        const over = snap(Math.min(pr.y, cr.y) - above);
        pts = [[px, pr.y], [px, over], [cx, over], [cx, y2]];
      }
    } else {
      // one over the other: out of the parent's side at its middle and round the nearer side of both. (Out of its
      // top or bottom the line would turn in the space between the two, and a child dropped right over its parent
      // leaves none. A child nearer than an arrowhead under its parent has no clear way in at all.)
      const [left, right] = [Math.min(pr.x, cr.x) - G.ease, Math.max(pr.x + pr.w, cr.x + cr.w) + G.ease];
      const side = snap(right - Math.max(px, cx) <= Math.min(px, cx) - left ? right : left);
      const half = snap(pr.y + pr.h / 2 - 0.5);
      pts = [[side > px ? pr.x + pr.w : pr.x, half], [side, half], [side, into], [cx, into], [cx, y2]];
    }
    if (moved.has(l.to)) {
      const head = ends.get(l.to) ?? ends.set(l.to, { key: `m:h:${l.to}`, net: l.net, nets: [], x: cx, y: cr.y, from: [], to: l.to }).get(l.to)!;
      head.from.push(l.from);
      if (!head.nets.includes(l.net)) head.nets.push(l.net);
    }
    return { ...l, pts, tone: tone(l.from) };
  });
  // the dashes again over every line as it runs now: a moved line may run onto a stretch another child's dash rides
  return { lines: drawLines(routes), heads: [...heads, ...ends.values()], flows: flowsOf(routes, running) };
}
