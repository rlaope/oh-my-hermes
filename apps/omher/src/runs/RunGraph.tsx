// The Runs graph, in two sizes. "panel": the 460px side panel. A card there is never narrower than PANEL_FLOOR
// (132px) and its title never set under 11px: the panel never shrinks a run past that. A run with more layers than
// fit side by side at the floor shows whole columns (one width for all) and scrolls sideways, with a "‹ 3 more" cue
// on the clipped side and the edges to it faded; a layer with more parallel parts than the box is tall folds into one
// group card ("9 parallel", "5 done · 2 running · 1 failed", stacked logos) that opens in place; a run of one layer
// (a CLI session's sub-runs, a fan-out) is a grid across the width, running first, with a summary line and "Show
// all" past GRID_CAP. − / Fit / + in the legend row zoom it. "full": the whole run large over the chat column, with
// titles in full, model marks, durations, attempts and a handoff snippet on hover; there you can drag a card (its
// position only, kept per run), pan, zoom and Fit. Nothing here changes a run: no connecting, deleting,
// reordering, retrying or cancelling.
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties, type PointerEvent as RPE } from "react";
import type { AgentRun, RunNode } from "../lib/runs";
import { isRepaired, nodeModel, span } from "../lib/runs";
import { markFor, ModelIcon } from "../ui";
import { columnLabel, distinctLabels, layerName, layoutRun, linksOf, orderLayers, routeEdge, sizeKind, type Box, type Column, type Lane, type Layout, type Size } from "./layout";
import { clampWords, modelLabel, plainSnippet, reducedMotion, STATE_WORD, textWidth } from "./format";

export type GraphMode = "panel" | "full";

// card heights carry the node's weight: a lead (plans, or unblocks several parts) is tallest, a leaf compact, the
// closing gate sits in a wider column
const SIZE = {
  panel: { cardH: 80, heights: { lead: 90, normal: 80, leaf: 64, gate: 80 }, gateW: 1.15, gutter: 30, rowGap: 14, pad: 16, minCard: 132, maxCard: 406, labelH: 24, mark: 14 },
  full: { cardH: 160, heights: { lead: 180, normal: 160, leaf: 140, gate: 168 }, gateW: 1.2, loose: true, gutter: 88, rowGap: 36, pad: 24, minCard: 220, maxCard: 280, labelH: 32, mark: 18 },
};
const STAGGER = { panel: 50, full: 70 };
const APPEAR = { panel: 260, full: 360 };
const DRAW = { panel: 280, full: 420 };
const MAX_ENTRANCE = { panel: 950, full: 1500 };
const DRAG_PX = 4;
const DRAWER_W = 392;
const MIN_FIT = 0.72; // below this the cards stop being readable: Fit keeps this scale and shows the open card
const PANEL_MARGIN = 16; // the panel graph's inner margin, on screen, at any scale
/** The panel's floor: no card narrower, no title type smaller. */
export const PANEL_FLOOR = { cardW: 132, font: 11 };
export const PANEL_ZOOM = { min: 0.4, max: 1.6, step: 1.2 };
/** A one-layer run's grid shows this many cards (running, then failed, then the rest) before "Show all". */
export const GRID_CAP = 24;
const GRID_GAP = 8;
const BAND_LABEL = 22; // a stacked layer's name row
const BAND_GAP = 14;
const GROUP_H = 52;
const GRID_HEAD = 28; // the grid's summary line ("88 sub-runs · 3 running · 85 done")
const GRID_FOOT = 40; // the grid's "Show all 88" row
const ROW_LINE = 15;
const TITLE_FONT = (weight = 550) => `${weight} ${PANEL_FLOOR.font}px ${FONT()}`;
/** A grid card's time slot: one width on every card ("23h 59m", the longest a duration reads under a day), so the
 *  times line up as a column and a title wraps for its own length, never for its neighbour's time. */
export const ROW_TIME_W = () => Math.ceil(textWidth("23h 59m", `400 10.5px ${FONT()}`));
/** A grid card's title, between its logo and its time + state: up to 2 lines at word breaks. The room is the card
 *  less its padding, borders and failed rail (8 + 8, 2, 2), the logo (14), the state (12), the time and the gaps. */
const rowRoom = (w: number, gate: boolean) => w - 20 - 14 - 12 - 3 * 6 - ROW_TIME_W() - 1 - (gate ? 11 + 6 : 0);
const rowTitle = (n: RunNode, label: string, w: number) => clampWords(label, rowRoom(w, sizeKind(n, 0) === "gate"), 2, (s) => textWidth(s, TITLE_FONT()));
const ROW_TITLE_LINE = 14;
const rowH = (lines: number) => lines * ROW_TITLE_LINE + 14; // the title, 6px padding above and below, the borders
const GRID_ROW_GAP = 6;

/** A layer folded into one card in the panel: its parts. */
export interface Group {
  layer: number;
  members: RunNode[];
}
export interface PanelPlan {
  /** "graph": the layered graph (its layers fit side by side at the floor); "stack": its layers top to bottom, each
   *  a grid; "grid": a run of one layer, as a grid across the width. */
  kind: "graph" | "grid" | "stack";
  lay: Layout;
  /** What is drawn: the run's nodes with each folded layer as one stand-in node (`group:<layer>`), or the grid's. */
  nodes: RunNode[];
  groups: Map<string, Group>;
  /** Layers the box is too short for: folded unless the person opened them. */
  tall: Set<number>;
  grid?: { total: number; shown: number; head: boolean; foot: boolean };
}

const RANK: Record<RunNode["state"], number> = { running: 0, failed: 1, blocked: 1, waiting: 2, parked: 2, done: 3, cancelled: 4 };
const openFailure = (n: RunNode, all: RunNode[]) => (n.state === "failed" || n.state === "blocked") && !isRepaired(n, all);
export const GROUP = "group:";

/** The card standing in for a folded layer: running if a part runs, else failed if one failed (and was not
 *  repaired), else waiting if one waits, else done (cancelled when all were). */
function groupNode(layer: number, members: RunNode[], all: RunNode[]): RunNode {
  const state: RunNode["state"] = members.some((m) => m.state === "running")
    ? "running"
    : members.some((m) => openFailure(m, all))
      ? "failed"
      : members.some((m) => m.state === "waiting" || m.state === "parked")
        ? "waiting"
        : members.every((m) => m.state === "cancelled")
          ? "cancelled"
          : "done";
  const node: RunNode = { id: `${GROUP}${layer}`, label: `${members.length} parallel`, deps: [], layer, state, attempts: [] };
  const starts = members.map((m) => m.started).filter((t): t is number => t !== undefined);
  const ends = members.map((m) => m.ended).filter((t): t is number => t !== undefined);
  if (starts.length) node.started = Math.min(...starts);
  if (starts.length && ends.length === members.length && state !== "running") node.ended = Math.max(...ends);
  return node;
}

/** The run with the given layers folded into group cards: a link into or out of a part becomes the group's. */
function foldLayers(nodes: RunNode[], fold: Set<number>): { nodes: RunNode[]; groups: Map<string, Group> } {
  const groups = new Map<string, Group>();
  const gid = new Map<string, string>();
  for (const l of fold) {
    const members = nodes.filter((n) => n.layer === l);
    groups.set(`${GROUP}${l}`, { layer: l, members });
    for (const m of members) gid.set(m.id, `${GROUP}${l}`);
  }
  if (!groups.size) return { nodes, groups };
  const map = (id: string) => gid.get(id) ?? id;
  const out: RunNode[] = [];
  for (const n of nodes) {
    const g = gid.get(n.id);
    if (!g) {
      const m: RunNode = { ...n, deps: [...new Set(n.deps.map(map))] };
      if (n.repairOf !== undefined) m.repairOf = map(n.repairOf);
      out.push(m);
      continue;
    }
    if (out.some((x) => x.id === g)) continue;
    const grp = groups.get(g)!;
    const deps = new Set<string>();
    for (const m of grp.members) for (const d of [...m.deps, ...(m.repairOf ? [m.repairOf] : [])]) if (map(d) !== g) deps.add(map(d));
    out.push({ ...groupNode(grp.layer, grp.members, nodes), deps: [...deps] });
  }
  return { nodes: out, groups };
}

/** How the panel draws a run, at the floor (the person's zoom comes on top of it):
 *  - one layer: a grid across the width (`gridPlan`);
 *  - layers that fit side by side at PANEL_FLOOR: the layered graph with its links, where a layer of 2+ parts whose
 *    column is taller than the box folds into a group card, unless the person opened it;
 *  - wider: the stack (`stackPlan`). Measured on real runs, scrolling whole columns sideways showed 2 of the live
 *    run's 11 parts and 10 of the biggest run's 14; the stack shows all of both. */
export function panelPlan(nodes: RunNode[], width: number, maxH = Infinity, opts: { opened?: Set<number>; all?: boolean } = {}): PanelPlan {
  const M = PANEL_MARGIN;
  if (new Set(nodes.map((n) => n.layer)).size <= 1) return gridPlan(nodes, width, opts.all ?? false);
  const o = { ...SIZE.panel, width, pad: M };
  const first = layoutRun(nodes, o);
  if (first.w > width + 0.5) return stackPlan(nodes, width, maxH, opts.opened ?? new Set());
  // a column taller than the box (its label band and margins aside) folds into a group card
  const room = maxH - 2 * M - o.labelH;
  const tall = new Set<number>();
  for (const c of first.columns) {
    const ids = nodes.filter((n) => n.layer === c.layer).map((n) => n.id);
    if (ids.length < 2) continue;
    const top = Math.min(...ids.map((id) => first.pos.get(id)!.y));
    const bottom = Math.max(...ids.map((id) => first.pos.get(id)!.y + first.size.get(id)!.h));
    if (bottom - top > room + 0.5) tall.add(c.layer);
  }
  const fold = new Set([...tall].filter((l) => !opts.opened?.has(l)));
  if (!fold.size) return { kind: "graph", lay: first, nodes, groups: new Map(), tall };
  const folded = foldLayers(nodes, fold);
  const lay = layoutRun(folded.nodes, o);
  // a folded column keeps the name of what its parts do
  lay.columns = lay.columns.map((c) => {
    const members = nodes.filter((n) => n.layer === c.layer);
    return { ...c, label: columnLabel(members, c.layer), count: members.length };
  });
  return { kind: "graph", lay, nodes: folded.nodes, groups: folded.groups, tall };
}

/** A run too wide for the panel at the floor: its layers top to bottom, each layer a band whose cards wrap into a
 *  grid across the width (a short last row shares the width, so no cell stays empty). While the stack is taller
 *  than the box, its biggest finished layer (then one with a failure, last a running one) folds into a group card,
 *  unless the person opened it. Links are not drawn here: hovering a card lights the parts it waits on and the parts
 *  waiting on it, and the full view draws every edge. */
function stackPlan(nodes: RunNode[], width: number, maxH: number, opened: Set<number>): PanelPlan {
  const t0 = performance.now();
  const M = PANEL_MARGIN;
  const inner = width - 2 * M;
  const most = Math.max(1, Math.floor((inner + GRID_GAP) / (PANEL_FLOOR.cardW + GRID_GAP)));
  const layers: RunNode[][] = [];
  for (const n of nodes) (layers[n.layer] ??= []).push(n);
  const { order } = orderLayers(nodes);
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const out = new Map<string, number>();
  for (const e of linksOf(nodes)) out.set(e.from, (out.get(e.from) ?? 0) + 1);
  const labels = distinctLabels(nodes);
  // a band card is the panel card: a title of up to 2 lines over its meta line
  const tileH = (n: RunNode, w: number, gate: boolean) =>
    clampWords(labels.get(n.id) ?? n.label, w - 16 - 3 - (gate ? 16 : 0), 2, (s) => textWidth(s, TITLE_FONT())).split("\n").length * ROW_LINE + 35;
  const build = (fold: Set<number>) => {
    const pos = new Map<string, Box>();
    const size = new Map<string, Size>();
    const columns: Column[] = [];
    const drawn: RunNode[] = [];
    const groups = new Map<string, Group>();
    let y = M;
    order.forEach((ids, l) => {
      if (!ids.length) return;
      const members = ids.map((id) => byId.get(id)!);
      columns.push({ layer: l, x: M, y, label: columnLabel(members, l), count: members.length });
      y += BAND_LABEL;
      if (fold.has(l)) {
        const g = groupNode(l, members, nodes);
        drawn.push(g);
        groups.set(g.id, { layer: l, members });
        pos.set(g.id, { x: M, y });
        size.set(g.id, { w: inner, h: GROUP_H, kind: "normal", unblocks: 0 });
        y += GROUP_H + BAND_GAP;
        return;
      }
      const cols = Math.min(most, members.length);
      for (let r = 0; r * cols < members.length; r++) {
        const row = members.slice(r * cols, r * cols + cols);
        const cw = Math.floor((inner - (row.length - 1) * GRID_GAP) / row.length);
        const kinds = row.map((n) => sizeKind(n, out.get(n.id) ?? 0));
        const h = Math.max(...row.map((n, i) => tileH(n, cw, kinds[i] === "gate")));
        row.forEach((n, i) => {
          drawn.push(n);
          pos.set(n.id, { x: M + i * (cw + GRID_GAP), y });
          size.set(n.id, { w: cw, h, kind: kinds[i], unblocks: out.get(n.id) ?? 0 });
        });
        y += h + GRID_GAP;
      }
      y += BAND_GAP - GRID_GAP;
    });
    return { pos, size, columns, drawn, groups, h: y - BAND_GAP + M };
  };
  const rank = (ms: RunNode[]) => (ms.some((n) => n.state === "running") ? 2 : ms.some((n) => openFailure(n, nodes)) ? 1 : 0);
  const candidates = layers
    .map((ms, l) => ({ l, n: ms?.length ?? 0, r: rank(ms ?? []) }))
    .filter((c) => c.n >= 2)
    .sort((a, b) => a.r - b.r || b.n - a.n || a.l - b.l);
  const tall = new Set<number>();
  let b = build(tall);
  for (const c of candidates) {
    if (b.h <= maxH + 0.5) break;
    tall.add(c.l);
    b = build(tall);
  }
  const fold = new Set([...tall].filter((l) => !opened.has(l)));
  if (fold.size !== tall.size) b = build(fold);
  const cardW = Math.floor((inner - (most - 1) * GRID_GAP) / most);
  const lay: Layout = { pos: b.pos, size: b.size, edges: [], columns: b.columns, w: width, h: b.h, cardW, cardH: ROW_LINE + 35, crossings: 0, ms: performance.now() - t0 };
  return { kind: "stack", lay, nodes: b.drawn, groups: b.groups, tall };
}

/** One layer as a grid: cards at the floor or wider, as many across as fit, running → failed → waiting → done, each
 *  row as tall as its longest title (at most 2 lines). */
function gridPlan(nodes: RunNode[], width: number, all: boolean): PanelPlan {
  const t0 = performance.now();
  const M = PANEL_MARGIN;
  const inner = width - 2 * M;
  const cols = Math.max(1, Math.min(nodes.length, Math.floor((inner + GRID_GAP) / (PANEL_FLOOR.cardW + GRID_GAP))));
  const cw = Math.floor((inner - (cols - 1) * GRID_GAP) / cols);
  const sorted = nodes
    .map((n, i) => [n, i] as const)
    .sort((a, b) => RANK[a[0].state] - RANK[b[0].state] || a[1] - b[1])
    .map(([n]) => n);
  // "Show all" only when it hides more than a few cards
  const capped = sorted.length > GRID_CAP + 4;
  const shown = capped && !all ? sorted.slice(0, GRID_CAP) : sorted;
  const labels = distinctLabels(nodes);
  const head = nodes.length > 8;
  const pos = new Map<string, Box>();
  const size = new Map<string, Size>();
  let y = M + (head ? GRID_HEAD : 0);
  // one row height for the whole grid (its longest title, at most 2 lines): it reads as a table, not a ragged wall
  const rh = rowH(Math.max(1, ...shown.map((n) => rowTitle(n, labels.get(n.id) ?? n.label, cw).split("\n").length)));
  for (let r = 0; r * cols < shown.length; r++) {
    shown.slice(r * cols, r * cols + cols).forEach((n, i) => {
      pos.set(n.id, { x: M + i * (cw + GRID_GAP), y });
      size.set(n.id, { w: cw, h: rh, kind: sizeKind(n, 0) === "gate" ? "gate" : "leaf", unblocks: 0 });
    });
    y += rh + GRID_ROW_GAP;
  }
  const h = y - GRID_ROW_GAP + (capped ? GRID_FOOT : 0) + M;
  const lay: Layout = { pos, size, edges: [], columns: [], w: width, h, cardW: cw, cardH: rowH(1), crossings: 0, ms: performance.now() - t0 };
  return { kind: "grid", lay, nodes: shown, groups: new Map(), tall: new Set(), grid: { total: nodes.length, shown: shown.length, head, foot: capped } };
}

/** A grid's or a group's counts in the grid's order, zero counts left out: [[3, "running"], [85, "done"]]. */
export function stateCounts(nodes: RunNode[], all: RunNode[] = nodes): [number, string][] {
  const c = (f: (n: RunNode) => boolean) => nodes.filter(f).length;
  const parts: [number, string][] = [
    [c((n) => n.state === "running"), "running"],
    [c((n) => openFailure(n, all)), "failed"],
    [c((n) => n.state === "waiting" || n.state === "parked"), "waiting"],
    [c((n) => n.state === "done" || isRepaired(n, all)), "done"],
    [c((n) => n.state === "cancelled"), "cancelled"],
  ];
  return parts.filter(([n]) => n > 0);
}
/** What a run's parts are called: a dag's "parts", a fan-out's "helpers", a CLI session's "sub-runs". */
export const partsNoun = (kind: AgentRun["kind"]) => (kind === "dag" ? "parts" : kind === "delegate" ? "helpers" : "sub-runs");

const GLYPH: Record<RunNode["state"], string> = {
  done: "✓",
  running: "",
  failed: "✕",
  blocked: "!",
  parked: "‖",
  waiting: "○",
  cancelled: "–",
};
/** A category glyph (hollow outline) for nodes whose model is unknown. */
const CAT: [RegExp, string][] = [
  [/review|audit|verif/, "M12 5c-5 0-8.5 4.5-9.5 7 1 2.5 4.5 7 9.5 7s8.5-4.5 9.5-7c-1-2.5-4.5-7-9.5-7Zm0 4.5a2.5 2.5 0 1 1 0 5 2.5 2.5 0 0 1 0-5Z"],
  [/visual|design/, "M12 3 21 12 12 21 3 12Z"],
  [/quick|low|writing/, "M13 3 5 13h6l-1 8 8-10h-6Z"],
];
const HEX = "M12 3 20 7.5v9L12 21 4 16.5v-9Z";
const catPath = (route?: string) => (route ? CAT.find(([re]) => re.test(route))?.[1] ?? HEX : HEX);

export interface BotModel {
  model: string;
  provider: string;
}

/** The node's logo: what it ran on, the agent CLI it went to, the model its route goes to, else the bot's own. Only
 *  a node with nothing known at all (no bot either) falls back to its category glyph. */
function Mark({ node, size, bot }: { node: RunNode; size: number; bot?: BotModel }) {
  const m = nodeModel(node, bot);
  const mark = m && markFor(m.model, m.provider);
  if (m && mark)
    return (
      <span className={`rg-mk src-${m.source}`} data-testid="node-mark" data-mark={mark} data-source={m.source} title={modelLabel(m)}>
        <ModelIcon model={m.model} provider={m.provider} size={size} />
      </span>
    );
  return (
    <span className="rg-mk cat" data-testid="node-mark" data-mark="category" title={node.route ? `route ${node.route}` : node.label}>
      <svg viewBox="0 0 24 24" width={size - 2} height={size - 2} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round">
        <path d={catPath(node.route)} />
      </svg>
    </span>
  );
}

/** The closing gate's mark: a small shield. */
const GateIcon = ({ size }: { size: number }) => (
  <svg className="rg-gate" viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" aria-label="Gate">
    <path d="M12 3 4.5 6v5.5c0 4.6 3.2 8.2 7.5 9.5 4.3-1.3 7.5-4.9 7.5-9.5V6Z" />
    <path d="m8.8 12 2.3 2.3 4.2-4.6" />
  </svg>
);

/** Positions saved for one run in the full view: { nodeId: {x, y} } in layout coordinates. */
const keyOf = (runId: string) => `omher.runs.pos.${runId}`;
function loadPos(runId: string): Record<string, Box> {
  try {
    const v = JSON.parse(localStorage.getItem(keyOf(runId)) ?? "{}");
    return v && typeof v === "object" ? v : {};
  } catch {
    return {};
  }
}
function savePos(runId: string, pos: Record<string, Box>) {
  try {
    if (Object.keys(pos).length) localStorage.setItem(keyOf(runId), JSON.stringify(pos));
    else localStorage.removeItem(keyOf(runId));
  } catch {
    /* no storage */
  }
}

/** Edge path from a source box to a target box: leaves right-middle, enters left-middle, horizontal tangents,
 *  around any card of a column it crosses. */
function edgePath(a: Box, sa: Size, b: Box, sb: Size, lanes: Lane[], rowGap: number) {
  const x1 = a.x + sa.w;
  const y1 = a.y + sa.h / 2;
  const x2 = b.x;
  const y2 = b.y + sb.h / 2;
  const between = lanes.filter((l) => l.x > x1 && l.x + l.w < x2);
  return { x1, y1, x2, y2, d: routeEdge(x1, y1, x2, y2, between, rowGap) };
}

/** The legend as a slim row (under the panel graph); `extra` sits at its right end (the full-view hint). */
export function Legend({ run, extra, tools, lines = true }: { run: AgentRun; extra?: React.ReactNode; tools?: React.ReactNode; lines?: boolean }) {
  // a panel that draws no links (stacked layers, a grid) names no kinds of line
  const lay = lines ? layoutRun(run.nodes, { width: 400, ...SIZE.panel }) : { edges: [] };
  return (
    <div className="rg-legend row" aria-label="Legend" data-testid="run-legend">
      {legend(run, lay.edges).map(([cls, word]) => (
        <span key={cls} className={cls}>
          {cls.startsWith("t-") ? <i aria-hidden /> : <b aria-hidden />}
          {word}
        </span>
      ))}
      {extra}
      {tools}
    </div>
  );
}

/** The node the panel opens on: the first running one (layer order, top to bottom), else the first open failure. */
export function focusNode(run: AgentRun, pos: Map<string, Box>): RunNode | null {
  const order = [...run.nodes].sort((a, b) => a.layer - b.layer || (pos.get(a.id)?.y ?? 0) - (pos.get(b.id)?.y ?? 0));
  return (
    order.find((n) => n.state === "running") ??
    order.find((n) => (n.state === "failed" || n.state === "blocked") && !isRepaired(n, run.nodes)) ??
    null
  );
}

export function RunGraph({
  run,
  handoffs,
  mode,
  width,
  open,
  onOpen,
  nowS,
  bot,
  onOverflow,
  onMode,
  maxH,
  zoom = 1,
}: {
  run: AgentRun;
  handoffs: Record<string, string>;
  mode: GraphMode;
  /** Panel: told whether the run is larger than the box and how many parts are not whole on screen (the panel
   *  then offers the full view). */
  onOverflow?: (over: boolean, hidden: number) => void;
  /** Panel: told how the run is drawn ("graph" draws its links; "stack" and "grid" do not). */
  onMode?: (mode: PanelPlan["kind"]) => void;
  /** Panel: the box's height cap (what the side panel has left under the plan card). */
  maxH?: number;
  /** Panel: the person's zoom over the fitted scale (1 = Fit; the legend row's − / Fit / +). */
  zoom?: number;
  /** The bot's own model: the last fallback for a node's logo. */
  bot?: BotModel;
  /** Width to lay out into (the box's inner width). */
  width: number;
  open: string | null;
  onOpen: (id: string | null) => void;
  nowS: number;
}) {
  // panel: the run at the floor (panelPlan): the layered graph with tall layers folded, or a grid for one layer. The
  // person opens a folded layer in place, and a long grid with "Show all"; both reset with the run.
  const [opened, setOpened] = useState<Set<number>>(() => new Set());
  const [all, setAll] = useState(false);
  useEffect(() => {
    setOpened(new Set());
    setAll(false);
  }, [run.id]);
  const plan = useMemo(
    () => (mode === "panel" ? panelPlan(run.nodes, Math.max(width, 200), maxH ?? 460, { opened, all }) : null),
    [run.nodes, width, mode, maxH, opened, all],
  );
  const z = mode === "full" ? SIZE.full : SIZE.panel;
  const lay: Layout = useMemo(() => plan?.lay ?? layoutRun(run.nodes, { width: Math.max(width, 200), ...SIZE.full }), [plan, run.nodes, width]);
  // what is drawn: the run's nodes, a folded layer as its group card (panel), the grid's cards
  const drawn = plan?.nodes ?? run.nodes;
  // the panel's scale: the floor, times the person's zoom
  const pk = plan ? Math.min(PANEL_ZOOM.max, Math.max(PANEL_ZOOM.min, Math.round(zoom * 1000) / 1000)) : 1;
  const byId = useMemo(() => new Map(drawn.map((n) => [n.id, n])), [drawn]);
  useEffect(() => {
    if (plan) onMode?.(plan.kind);
  }, [plan, onMode]);
  // what a card waits on and what waits on it (hovering lights them; the stack draws no lines)
  const near = useMemo(() => {
    const m = new Map<string, Set<string>>();
    for (const e of linksOf(drawn)) {
      (m.get(e.from) ?? m.set(e.from, new Set()).get(e.from)!).add(e.to);
      (m.get(e.to) ?? m.set(e.to, new Set()).get(e.to)!).add(e.from);
    }
    return m;
  }, [drawn]);

  // full view: dragged positions override the layout's, per run
  const [over, setOver] = useState<Record<string, Box>>(() => (mode === "full" ? loadPos(run.id) : {}));
  useEffect(() => setOver(mode === "full" ? loadPos(run.id) : {}), [run.id, mode]);
  const at = (id: string): Box => over[id] ?? lay.pos.get(id)!;
  const sz = (id: string): Size => lay.size.get(id)!;

  // entrance: cards in layer order (top to bottom inside a layer), then each edge once both ends are in
  const appear = useMemo(() => {
    const ids = [...lay.pos.entries()].sort((a, b) => byId.get(a[0])!.layer - byId.get(b[0])!.layer || a[1].y - b[1].y || a[1].x - b[1].x).map(([id]) => id);
    const step = Math.min(STAGGER[mode], Math.max(12, (MAX_ENTRANCE[mode] - APPEAR[mode] - DRAW[mode]) / Math.max(1, ids.length)));
    return new Map(ids.map((id, i) => [id, { i, delay: Math.round(i * step) }]));
  }, [lay, byId, mode]);
  const still = useMemo(reducedMotion, []);
  const [played, setPlayed] = useState(false);
  useEffect(() => {
    setPlayed(false);
    const h = setTimeout(() => setPlayed(true), MAX_ENTRANCE[mode] + 100);
    return () => clearTimeout(h);
  }, [run.id, mode]);
  const animate = !still && !played;

  // ---- full view: pan / zoom / drag
  const box = useRef<HTMLDivElement>(null);
  const openRef = useRef(open);
  openRef.current = open;
  const [view, setView] = useState({ x: 0, y: 0, k: 1 });
  const fit = useCallback((reserve = 0) => {
    const el = box.current;
    if (!el) return;
    const xs = run.nodes.map((n) => at(n.id));
    const m = 40;
    const minX = Math.min(...xs.map((p) => p.x)) - m;
    const minY = Math.min(...xs.map((p) => p.y), z.pad + z.labelH) - m - z.labelH;
    const maxX = Math.max(...run.nodes.map((n) => at(n.id).x + sz(n.id).w)) + m;
    const maxY = Math.max(...run.nodes.map((n) => at(n.id).y + sz(n.id).h)) + m;
    let W = el.clientWidth - reserve;
    if (reserve) {
      // the drawer only needs room when the run, fitted to the whole width, would reach under it
      const k0 = Math.min(1.25, el.clientWidth / (maxX - minX), el.clientHeight / (maxY - minY));
      const right = (el.clientWidth + (maxX - minX) * k0) / 2;
      if (right <= el.clientWidth - reserve) W = el.clientWidth;
    }
    const want = Math.min(W / (maxX - minX), el.clientHeight / (maxY - minY));
    const k = Math.min(1.25, Math.max(MIN_FIT, want));
    const y = (el.clientHeight - (maxY - minY) * k) / 2 - minY * k;
    if (want >= MIN_FIT || !openRef.current) {
      // the whole run fits: centre it (when it is wider than the box at MIN_FIT, start from its left edge)
      const x = want >= MIN_FIT ? (W - (maxX - minX) * k) / 2 - minX * k : 24 - minX * k;
      setView({ k, x, y });
      return;
    }
    // too wide to show whole next to the drawer: keep the open card in view, centred in the free width
    const p = at(openRef.current);
    setView({ k, x: W / 2 - (p.x + sz(openRef.current).w / 2) * k, y });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lay, over, run.nodes]);
  useLayoutEffect(() => {
    if (mode === "full") fit();
    // fit once per run when it opens; later drags keep the view where it is
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run.id, mode, lay]);

  // the box grows while the side panel steps aside: refit on resize (the view is the user's after that)
  const fitRef = useRef(fit);
  fitRef.current = fit;
  useEffect(() => {
    const el = box.current;
    if (mode !== "full" || !el || typeof ResizeObserver === "undefined") return;
    let w = el.clientWidth;
    const ro = new ResizeObserver(() => {
      if (Math.abs(el.clientWidth - w) < 2) return;
      w = el.clientWidth;
      fitRef.current(openRef.current ? DRAWER_W : 0);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [mode]);

  // the full view's drawer sits on the right (360px + margins): while it is open the run fits into what is left
  const drawerOpen = mode === "full" && !!open;
  useEffect(() => {
    if (mode === "full") fit(drawerOpen ? DRAWER_W : 0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [drawerOpen]);

  // ⌘+/⌘−/⌘0 zoom in the full view
  useEffect(() => {
    if (mode !== "full") return;
    const onKey = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey) || e.altKey) return;
      const el = box.current;
      if (!el) return;
      const cx = el.clientWidth / 2;
      const cy = el.clientHeight / 2;
      if (e.key === "=" || e.key === "+") zoomAt(cx, cy, 1.15);
      else if (e.key === "-") zoomAt(cx, cy, 1 / 1.15);
      else if (e.key === "0") fit(drawerOpen ? DRAWER_W : 0);
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });
  const zoomAt = (cx: number, cy: number, f: number) =>
    setView((v) => {
      const k = Math.min(2.5, Math.max(0.25, v.k * f));
      const r = k / v.k;
      return { k, x: cx - (cx - v.x) * r, y: cy - (cy - v.y) * r };
    });
  useEffect(() => {
    const el = box.current;
    if (mode !== "full" || !el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const r = el.getBoundingClientRect();
      // pinch arrives as ctrl+wheel; ⌘+wheel zooms too; a plain two-finger scroll pans
      if (e.ctrlKey || e.metaKey) zoomAt(e.clientX - r.left, e.clientY - r.top, Math.exp(-e.deltaY * 0.01));
      else setView((v) => ({ ...v, x: v.x - e.deltaX, y: v.y - e.deltaY }));
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [mode]);

  const drag = useRef<{ id: string | null; sx: number; sy: number; ox: number; oy: number; moved: boolean } | null>(null);
  const onDown = (e: RPE, id: string | null) => {
    if (mode !== "full" || e.button !== 0) return;
    const o = id ? at(id) : { x: view.x, y: view.y };
    drag.current = { id, sx: e.clientX, sy: e.clientY, ox: o.x, oy: o.y, moved: false };
    (e.currentTarget as Element).setPointerCapture?.(e.pointerId);
  };
  const onMove = (e: RPE) => {
    const d = drag.current;
    if (!d) return;
    const dx = e.clientX - d.sx;
    const dy = e.clientY - d.sy;
    if (!d.moved && Math.hypot(dx, dy) < DRAG_PX) return;
    d.moved = true;
    if (d.id) {
      const id = d.id;
      setOver((p) => ({ ...p, [id]: { x: Math.round(d.ox + dx / view.k), y: Math.round(d.oy + dy / view.k) } }));
    } else setView((v) => ({ ...v, x: d.ox + dx, y: d.oy + dy }));
  };
  const onUp = (e: RPE) => {
    const d = drag.current;
    drag.current = null;
    if (!d) return;
    if (d.id && d.moved) {
      setOver((p) => {
        savePos(run.id, p);
        return p;
      });
    } else if (d.id && !d.moved) onOpen(d.id === open ? null : d.id);
    else if (!d.id && !d.moved && (e.target as HTMLElement).classList.contains("rg-box")) onOpen(null);
  };
  const reset = () => {
    savePos(run.id, {});
    setOver({});
    requestAnimationFrame(() => fit(drawerOpen ? DRAWER_W : 0));
  };

  // ---- panel: the run fits the box (panelPlan); zoomed in, or past the smallest scale, the box scrolls both ways.
  // It opens on the first running (else failed) node; a clipped side gets a soft fade and a "‹ 3 more" cue.
  const pbox = useRef<HTMLDivElement>(null);
  const [more, setMore] = useState({ l: 0, r: 0, t: false, b: false });
  // how many parts are not whole on screen: the panel's "Open full view" hint says so ("7 more")
  const [hid, setHid] = useState(0);
  // edges with an end off screen: drawn faint (never a bright stub out of nothing)
  const [offIds, setOffIds] = useState<Set<string>>(() => new Set());
  const [win, setWin] = useState<[number, number] | null>(null);
  const measure = useCallback(() => {
    const el = pbox.current;
    if (!el) return;
    // the window on screen, in layout coordinates
    const [x0, y0, x1, y1] = [el.scrollLeft / pk, el.scrollTop / pk, (el.scrollLeft + el.clientWidth) / pk, (el.scrollTop + el.clientHeight) / pk];
    const e = 1 / pk;
    let h = 0;
    let l = 0;
    let r = 0;
    const off = new Set<string>();
    for (const [id, p] of lay.pos) {
      const s = lay.size.get(id)!;
      const left = p.x < x0 - e;
      const right = p.x + s.w > x1 + e;
      // the side cues count the cards beside the window; a group card spans its band, so it is under, not beside
      const side = !plan?.groups.has(id);
      if (left && side) l++;
      else if (right && side) r++;
      if (left || right || p.y < y0 - e || p.y + s.h > y1 + e) h++;
      if (p.x + s.w < x0 + 8 || p.x > x1 - 8 || p.y + s.h < y0 + 8 || p.y > y1 - 8) off.add(id);
    }
    const m = { l, r, t: el.scrollTop > 1, b: el.scrollTop + el.clientHeight < el.scrollHeight - 1 };
    setMore((p) => (p.l === m.l && p.r === m.r && p.t === m.t && p.b === m.b ? p : m));
    setHid(h);
    setOffIds((p) => (p.size === off.size && [...off].every((id) => p.has(id)) ? p : off));
    setWin((p) => (p && Math.abs(p[0] - x0) < 0.5 && Math.abs(p[1] - x1) < 0.5 ? p : [x0, x1]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lay, pk]);
  const focusedFor = useRef<string | null>(null);
  useLayoutEffect(() => {
    const el = pbox.current;
    if (mode !== "panel" || !el) return;
    const key = `${run.id}@${maxH ?? ""}@${pk}`;
    if (focusedFor.current !== key) {
      // once per run, box height and scale: later refreshes keep wherever the person scrolled to
      focusedFor.current = key;
      const f = focusNode({ ...run, nodes: drawn }, lay.pos);
      if (f && (el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1)) {
        const p = lay.pos.get(f.id)!;
        const s = lay.size.get(f.id)!;
        // start at a column's left edge (less the margin) or at the run's right end: of the starts that show the
        // whole focus card, the one that puts it nearest the middle, so the parts after it (a repair, the closing
        // check) show too
        const [px, pw] = [p.x * pk, s.w * pk];
        const maxL = el.scrollWidth - el.clientWidth;
        const mid = px + pw / 2 - el.clientWidth / 2;
        const starts = [...lay.columns.map((c) => Math.max(0, c.x * pk - PANEL_MARGIN)).filter((x) => x < maxL), maxL];
        const fits = starts.filter((x) => x <= px && px + pw + PANEL_MARGIN <= x + el.clientWidth).sort((a, b) => Math.abs(a - mid) - Math.abs(b - mid))[0];
        el.scrollLeft = Math.min(maxL, fits ?? Math.max(0, mid));
        el.scrollTop = Math.max(0, Math.min(el.scrollHeight - el.clientHeight, (p.y + s.h / 2) * pk - el.clientHeight / 2));
      } else {
        el.scrollLeft = 0;
        el.scrollTop = 0;
      }
    }
    measure();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run.id, mode, lay, maxH, pk]);
  const overflows = more.l > 0 || more.r > 0 || more.t || more.b;
  useEffect(() => {
    if (mode === "panel") onOverflow?.(overflows, overflows ? hid : 0);
  }, [overflows, hid, mode, onOverflow]);

  const [hover, setHover] = useState<string | null>(null);
  const moved = Object.keys(over).length > 0;
  // keep the click-to-open for the node the person opened in the panel
  // lanes from the drawn positions (dragged cards included): one per distinct card x
  const lanes: Lane[] = [];
  for (const n of drawn) {
    const p = at(n.id);
    const s = sz(n.id);
    const lane = lanes.find((l) => Math.abs(l.x - p.x) < lay.cardW / 2);
    if (lane) {
      lane.spans.push([p.y, s.h]);
      lane.w = Math.max(lane.w, s.w);
    } else lanes.push({ x: p.x, w: s.w, spans: [[p.y, s.h]] });
  }
  const edges = moved ? lay.edges.map((e) => ({ ...e, ...edgePath(at(e.from), sz(e.from), at(e.to), sz(e.to), lanes, z.rowGap) })) : lay.edges;
  const labels = useMemo(() => distinctLabels(drawn), [drawn]);
  // a stacked band of repairs names the layer it fixes ("· fixes L4"), since the stack draws no repair links
  const fixes = (layer: number) => {
    const ms = run.nodes.filter((n) => n.layer === layer);
    const of = new Set(ms.map((n) => (n.repairOf ? run.nodes.find((m) => m.id === n.repairOf)?.layer : undefined)));
    return ms.length && !of.has(undefined) && of.size === 1 ? ` · fixes L${[...of][0]! + 1}` : "";
  };
  // edges meeting at one card share one arrowhead (the last solid one wins, so a dashed edge never colours it)
  // (edges meeting a card at their own ports each keep their arrowhead)
  const arrowFor = new Map<string, string>();
  for (const e of [...edges].sort((a, b) => Number(!a.broken) - Number(!b.broken))) arrowFor.set(`${e.to}@${e.y2}`, e.key);
  const mixed = new Set<string>();
  for (const e of edges) if (edges.some((f) => f.to === e.to && f.broken !== e.broken)) mixed.add(e.to);
  // panel: where the box clips the run left or right, edges fade out over the last 24px before its side
  const fadeMask =
    mode === "panel" && win && (more.l > 0 || more.r > 0)
      ? { x0: win[0], x1: win[1], l: more.l > 0, r: more.r > 0, a: Math.min(0.2, 28 / pk / Math.max(1, win[1] - win[0])), f: Math.min(0.35, 84 / pk / Math.max(1, win[1] - win[0])) }
      : null;
  const lastIn = (e: { from: string; to: string }) => Math.max(appear.get(e.from)!.delay, appear.get(e.to)!.delay) + APPEAR[mode] * 0.6;

  const canvas = (
    <div
      className="rg-canvas"
      style={mode === "full" ? { width: lay.w, height: lay.h, transform: `translate(${view.x}px, ${view.y}px) scale(${view.k})` } : { width: lay.w, height: lay.h }}
      data-testid="run-canvas"
    >
      {lay.columns.map((c) => {
        const stack = plan?.kind === "stack";
        const name = mode === "panel" ? (lay.columns.length > 1 ? layerName(c.layer, c.label) : c.label.replace(/ · \d+$/, "")) : c.label;
        // a layer the box is too short for, opened by the person: its label folds it back
        const refold = !!plan?.tall.has(c.layer) && opened.has(c.layer);
        return (
          <div
            key={c.layer}
            className={`rg-col${stack ? " band" : ""}`}
            style={{ left: c.x, top: c.y, width: stack ? lay.w - 2 * PANEL_MARGIN : lay.cardW, ...(mode === "panel" && !stack ? { maxWidth: lay.cardW + z.gutter - 4 } : {}) }}
            title={mode === "panel" ? `${layerName(c.layer, c.label)} · ${c.count} ${c.count === 1 ? "part" : "parts"}` : undefined}
            data-testid="run-col"
          >
            {stack ? (
              <>
                <span className="rg-coln">{name}</span>
                <span className="rg-colc">
                  {` · ${c.count} ${c.count === 1 ? "part" : "parts"}${fixes(c.layer)}`}
                </span>
              </>
            ) : (
              name
            )}
            {refold && (
              <button
                type="button"
                className="rg-refold"
                data-testid="run-group-fold"
                onClick={() => setOpened((o) => new Set([...o].filter((l) => l !== c.layer)))}
                title="Fold this layer back into one card"
              >
                Fold
              </button>
            )}
          </div>
        );
      })}
      {plan?.grid?.head && (
        <div className="rg-gridhead" data-testid="run-sub-summary" style={{ left: PANEL_MARGIN, top: PANEL_MARGIN, width: lay.w - 2 * PANEL_MARGIN }}>
          <b>
            {plan.grid.total} {partsNoun(run.kind)}
          </b>
          {stateCounts(run.nodes).map(([n, w]) => (
            <span key={w} className={`t-${w}`}>
              {" · "}
              {n} {w}
            </span>
          ))}
        </div>
      )}
      {plan?.grid?.foot && (
        <button
          type="button"
          className="rg-gridall"
          data-testid="run-grid-all"
          style={{ left: PANEL_MARGIN, top: lay.h - PANEL_MARGIN - 30, width: lay.w - 2 * PANEL_MARGIN }}
          onClick={() => setAll((v) => !v)}
        >
          {all ? "Show fewer" : `Show all ${plan.grid.total} · ${plan.grid.total - plan.grid.shown} more`}
        </button>
      )}
      <svg className={`rg-edges${hover ? " focus" : ""}`} width={lay.w} height={lay.h} aria-hidden overflow="visible">
        <defs>
          {fadeMask && (
            <>
              <linearGradient id={`mg-${cssId(run.id)}`} gradientUnits="userSpaceOnUse" x1={fadeMask.x0} y1={0} x2={fadeMask.x1} y2={0}>
                <stop offset="0" stopColor="#fff" stopOpacity={fadeMask.l ? 0 : 1} />
                <stop offset={fadeMask.a} stopColor="#fff" stopOpacity={fadeMask.l ? 0 : 1} />
                <stop offset={fadeMask.f} stopColor="#fff" stopOpacity={1} />
                <stop offset={1 - fadeMask.f} stopColor="#fff" stopOpacity={1} />
                <stop offset={1 - fadeMask.a} stopColor="#fff" stopOpacity={fadeMask.r ? 0 : 1} />
                <stop offset="1" stopColor="#fff" stopOpacity={fadeMask.r ? 0 : 1} />
              </linearGradient>
              <mask id={`m-${cssId(run.id)}`} maskUnits="userSpaceOnUse" x={0} y={0} width={lay.w} height={lay.h}>
                <rect x={0} y={0} width={lay.w} height={lay.h} fill={`url(#mg-${cssId(run.id)})`} />
              </mask>
            </>
          )}
          {edges.map((e) => (
            <linearGradient key={e.key} id={`g-${cssId(run.id)}-${cssId(e.key)}`} gradientUnits="userSpaceOnUse" x1={e.x1} y1={e.y1} x2={e.x2} y2={e.y2}>
              <stop offset="0" className={`rg-stop s-${byId.get(e.from)!.state}`} />
              <stop offset="1" className={`rg-stop s-${byId.get(e.to)!.state}`} />
            </linearGradient>
          ))}
        </defs>
        <g mask={fadeMask ? `url(#m-${cssId(run.id)})` : undefined} data-testid="run-edges-clip" data-mask={fadeMask ? "true" : "false"}>
        {edges.map((e) => {
          const into = byId.get(e.to)!.state === "running";
          // panel: an edge with an end off screen is quieter, and the mask fades it out at the box's side
          const off = mode === "panel" && (offIds.has(e.from) || offIds.has(e.to));
          return (
            <g
              key={e.key}
              className={`rg-edge${e.broken ? " broken" : ""}${e.kind === "repair" ? " repair" : ""}${into ? " flow" : ""}${animate ? " enter" : ""}${hover && (e.from === hover || e.to === hover) ? " lit" : ""}${off ? " off" : ""}`}
              style={{ "--d": `${Math.round(lastIn(e))}ms`, "--draw": `${DRAW[mode]}ms` } as CSSProperties}
              data-testid="run-edge"
              data-from={e.from}
              data-to={e.to}
              data-end={`${e.x1},${e.y1},${e.x2},${e.y2}`}
            >
              <path
                className="rg-line"
                d={e.d}
                pathLength={animate && !e.broken && e.kind === "dep" ? 1 : undefined}
                stroke={e.broken ? undefined : `url(#g-${cssId(run.id)}-${cssId(e.key)})`}
              />
              {into && <path className="rg-flowline" d={e.d} />}
            </g>
          );
        })}
        {edges
          .filter((e) => arrowFor.get(`${e.to}@${e.y2}`) === e.key)
          .map((e) => (
            <path
              key={`a-${e.key}`}
              className={`rg-arrow${e.broken && !mixed.has(e.to) ? " broken" : ""}${e.kind === "repair" ? " repair" : ""}${byId.get(e.to)!.state === "running" ? " flow" : ""}${animate ? " enter" : ""}${hover && (e.from === hover || e.to === hover) ? " lit" : ""}`}
              style={{ "--d": `${Math.round(lastIn(e) + DRAW[mode])}ms` } as CSSProperties}
              d={mode === "full" ? `M${e.x2},${e.y2} l-9,-6 l0,12 Z` : `M${e.x2},${e.y2} l-7,-4.5 l0,9 Z`}
              data-testid="run-arrow"
            />
          ))}
        </g>
      </svg>
      {drawn.map((n) => {
        const p = at(n.id);
        const a = appear.get(n.id)!;
        const g = plan?.groups.get(n.id);
        if (g)
          return (
            <GroupCard
              key={n.id}
              n={n}
              group={g}
              all={run.nodes}
              p={p}
              w={sz(n.id).w}
              h={sz(n.id).h}
              bot={bot}
              appear={a.i}
              delay={animate ? a.delay : null}
              nowS={nowS}
              onOpen={() => setOpened((o) => new Set([...o, g.layer]))}
            />
          );
        return (
          <Card
            key={n.id}
            n={n}
            label={labels.get(n.id)!}
            mode={mode}
            row={plan?.kind === "grid"}
            p={p}
            w={sz(n.id).w}
            h={sz(n.id).h}
            kind={sz(n.id).kind}
            unblocks={sz(n.id).unblocks}
            repaired={isRepaired(n, run.nodes)}
            deps={edges.filter((e) => e.to === n.id && e.kind === "dep").map((e) => byId.get(e.from)!)}
            mark={z.mark}
            bot={bot}
            note={mode === "full" ? handoffs[n.id] : undefined}
            on={n.id === open}
            hov={n.id === hover}
            dim={!!hover && n.id !== hover && !edges.some((e) => (e.from === hover && e.to === n.id) || (e.to === hover && e.from === n.id)) && !near.get(hover)?.has(n.id)}
            appear={a.i}
            delay={animate ? a.delay : null}
            nowS={nowS}
            onPointerDown={(e) => {
              e.stopPropagation();
              onDown(e, n.id);
            }}
            onClick={mode === "panel" ? () => onOpen(n.id === open ? null : n.id) : undefined}
            onHover={setHover}
          />
        );
      })}
    </div>
  );

  if (mode === "panel") {
    const [W, H] = [Math.floor(lay.w * pk), Math.ceil(lay.h * pk)];
    return (
      <>
        <div
          ref={pbox}
          className={`rg rg-panel k-${plan!.kind}${still ? " still" : ""}`}
          data-testid="run-graph"
          data-mode={plan!.kind}
          data-cols={plan!.kind === "graph" ? lay.columns.length : plan!.kind === "grid" ? 1 : lay.columns.length}
          data-layout-ms={lay.ms.toFixed(2)}
          data-crossings={lay.crossings}
          data-overflow={overflows ? "true" : "false"}
          data-fit={pk !== 1 ? pk.toFixed(2) : undefined}
          data-groups={plan!.groups.size}
          style={{ height: H, ...(maxH ? { maxHeight: maxH } : {}) }}
          onScroll={measure}
        >
          {pk !== 1 ? (
            <div className="rg-fit" style={{ width: W, height: H }}>
              <div style={{ transform: `scale(${pk})`, transformOrigin: "0 0" }}>{canvas}</div>
            </div>
          ) : (
            canvas
          )}
        </div>
        {(["l", "r", "t", "b"] as const).map((k) => {
          const n = k === "l" ? more.l : k === "r" ? more.r : 0;
          const on = k === "l" || k === "r" ? n > 0 : more[k];
          return (
            <i key={k} className={`rg-fade ${k}${on ? " on" : ""}`} aria-hidden data-testid={`run-fade-${k}`} data-on={on ? "true" : "false"}>
              {n > 0 && (
                <span className="rg-more" data-testid={`run-more-${k}`}>
                  {k === "l" ? `‹ ${n} more` : `${n} more ›`}
                </span>
              )}
            </i>
          );
        })}
      </>
    );
  }
  return (
    <div
      ref={box}
      className={`rg rg-full rg-box${still ? " still" : ""}`}
      data-testid="run-graph"
      data-cols={lay.columns.length}
      data-layout-ms={lay.ms.toFixed(2)}
      data-crossings={lay.crossings}
      data-zoom={view.k.toFixed(2)}
      onPointerDown={(e) => onDown(e, null)}
      onPointerMove={onMove}
      onPointerUp={onUp}
      onPointerCancel={() => (drag.current = null)}
      onScroll={(e) => {
        // focusing a card scrolls an overflow:hidden box; panning is ours, so undo it
        e.currentTarget.scrollLeft = 0;
        e.currentTarget.scrollTop = 0;
      }}
    >
      {canvas}
      {hover && hover !== open && handoffs[hover] && !drag.current && (() => {
        const lines = tipLines(plainSnippet(handoffs[hover], 420));
        const W = 260;
        const H = 30 + lines.reduce((a, l) => a + Math.ceil((l.length * 6.4) / (W - 24)) * 17, 0);
        const p = at(hover);
        const card = { x: p.x * view.k + view.x, y: p.y * view.k + view.y, w: sz(hover).w * view.k, h: sz(hover).h * view.k };
        const bw = box.current?.clientWidth ?? 0;
        const bh = box.current?.clientHeight ?? 0;
        const others = run.nodes
          .filter((n) => n.id !== hover)
          .map((n) => ({ x: at(n.id).x * view.k + view.x, y: at(n.id).y * view.k + view.y, w: sz(n.id).w * view.k, h: sz(n.id).h * view.k }));
        others.push({ x: card.x - z.gutter * view.k, y: 0, w: z.gutter * view.k - 2, h: bh });
        // beside the card when there is room; else the canvas corner that hides the least of the other cards.
        // It never covers the card it describes.
        const top = (z.pad + z.labelH) * view.k + view.y + 4; // below the column labels
        const clampX = (x: number) => Math.min(Math.max(x, 8), bw - W - 8);
        const clampY = (y: number) => Math.min(Math.max(y, top), bh - H - 56);
        // beside the card, slid along each side to the place that hides the least of the other cards
        const spots: { side: string; x: number; y: number }[] = [];
        for (let dy = -H + 28; dy <= card.h - 28; dy += 12) {
          spots.push({ side: "right", x: card.x + card.w + 12, y: card.y + dy });
          spots.push({ side: "left", x: card.x - W - 12, y: card.y + dy });
        }
        for (let dx = -W + 48; dx <= card.w - 48; dx += 12) {
          spots.push({ side: "below", x: card.x + dx, y: card.y + card.h + 12 });
          spots.push({ side: "above", x: card.x + dx, y: card.y - H - 12 });
        }
        // nothing free beside it: the free-est place in the box, named after the card
        for (let y = top; y + H <= bh - 56; y += 24) for (let x = 12; x + W <= bw - 12; x += 24) spots.push({ side: "dock", x, y });
        void clampX;
        const inside = (s: { x: number; y: number }) => s.x >= 8 && s.y >= top && s.x + W <= bw - 8 && s.y + H <= bh - 56;
        const area = (s: { x: number; y: number }, o: { x: number; y: number; w: number; h: number }) =>
          Math.max(0, Math.min(s.x + W, o.x + o.w) - Math.max(s.x, o.x)) * Math.max(0, Math.min(s.y + H, o.y + o.h) - Math.max(s.y, o.y));
        const dist = (s: { x: number; y: number }) => Math.hypot(s.x + W / 2 - (card.x + card.w / 2), s.y + H / 2 - (card.y + card.h / 2));
        // covered card area first (the hovered card counts double), then the distance to the card
        const cost = (s: { side: string; x: number; y: number }) =>
          (4 * area(s, card) + others.reduce((a, o) => a + area(s, o), 0)) * 10 + dist(s) + (s.side === "dock" ? 400 : 0);
        const ok = spots.filter(inside);
        const spot = (ok.length ? ok : spots).reduce((best, s) => (cost(s) < cost(best) ? s : best));
        // the arrow points at the middle of the stretch the tip shares with the card
        const arrow =
          spot.side === "above" || spot.side === "below"
            ? (Math.max(spot.x, card.x) + Math.min(spot.x + W, card.x + card.w)) / 2 - spot.x
            : (Math.max(spot.y, card.y) + Math.min(spot.y + H, card.y + card.h)) / 2 - spot.y;
        return (
          <div
            className={`rg-tip ${spot.side}`}
            style={{ left: spot.x, top: spot.y, width: W, ["--tip-at" as string]: `${Math.max(14, Math.min(arrow, (spot.side === "above" || spot.side === "below" ? W : H) - 14)) - 4}px` }}
            data-testid="run-tip"
            data-side={spot.side}
          >
            <b>{spot.side === "dock" ? `Handoff · ${byId.get(hover)!.label}` : "Handoff"}</b>
            {lines.map((l, i) => {
              const m = /^([A-Z][A-Za-z ]{1,18}):\s(.*)$/.exec(l);
              return (
                <span key={i} className="rg-tip-l">
                  {m ? (
                    <>
                      <em>{m[1]}</em> {m[2]}
                    </>
                  ) : (
                    l
                  )}
                </span>
              );
            })}
          </div>
        );
      })()}
      <div className="rg-legend" aria-label="Legend" data-testid="run-legend">
        {legend(run, edges).map(([cls, word]) => (
          <span key={cls} className={cls}>
            {cls.startsWith("t-") ? <i aria-hidden /> : <b aria-hidden />}
            {word}
          </span>
        ))}
      </div>
      <div className="rg-tools" onPointerDown={(e) => e.stopPropagation()}>
        <button type="button" onClick={() => zoomAt((box.current?.clientWidth ?? 0) / 2, (box.current?.clientHeight ?? 0) / 2, 1 / 1.2)} aria-label="Zoom out" title="Zoom out (⌘−)">
          −
        </button>
        <span className="rg-zoom">{Math.round(view.k * 100)}%</span>
        <button type="button" onClick={() => zoomAt((box.current?.clientWidth ?? 0) / 2, (box.current?.clientHeight ?? 0) / 2, 1.2)} aria-label="Zoom in" title="Zoom in (⌘+)">
          +
        </button>
        <i className="rg-sep" />
        <button type="button" onClick={() => fit(drawerOpen ? DRAWER_W : 0)} data-testid="run-fit" title="Fit the run (⌘0)">
          Fit
        </button>
        <button type="button" onClick={reset} disabled={!moved} data-testid="run-reset" title="Put every card back where the layout puts it">
          Reset layout
        </button>
      </div>
    </div>
  );
}

/** Legend entries for what this run shows: its node states and its kinds of line. */
export function legend(run: AgentRun, edges: { kind: string; broken: boolean; to: string }[]): [string, string][] {
  const has = (f: (n: RunNode) => boolean) => run.nodes.some(f);
  const out: [string, string][] = [];
  if (has((n) => n.state === "done")) out.push(["t-done", "done"]);
  if (has((n) => n.state === "running")) out.push(["t-running", "running"]);
  if (has((n) => (n.state === "failed" || n.state === "blocked") && !isRepaired(n, run.nodes))) out.push(["t-failed", "failed"]);
  if (has((n) => isRepaired(n, run.nodes))) out.push(["t-repaired", "repaired"]);
  if (has((n) => n.state === "waiting" && n.attempts.length > 0)) out.push(["t-retry", "retry"]);
  if (has((n) => n.state === "waiting" && n.attempts.length === 0)) out.push(["t-waiting", "waiting"]);
  if (edges.some((e) => e.kind === "repair")) out.push(["l-repair", "repair"]);
  if (edges.some((e) => e.broken)) out.push(["l-broken", "from a failure"]);
  if (edges.some((e) => run.nodes.find((n) => n.id === e.to)?.state === "running")) out.push(["l-flow", "into running"]);
  return out;
}
const cssId = (s: string) => s.replace(/[^a-zA-Z0-9_-]/g, "_");
/** A handoff snippet as short lines: a break before each "Label:" ("Worktree:", "Commit:", "Files:"). */
const tipLines = (s: string) =>
  s
    .replace(/\S*\/\S{20,}/g, (p) => (p.length > 30 ? `${p.slice(0, 10)}…${p.slice(-16)}` : p))
    .split(/\s(?=[A-Z][A-Za-z ]{1,18}:\s)/)
    .slice(0, 5);
/** A handoff's first line, plain and short: commit hashes cut to 9 characters, paths to their last part. */
const firstLine = (md: string) => {
  const body = md.replace(/^\s*#[^\n]*\n/, "").trim().split("\n")[0] ?? "";
  const t = plainSnippet(body, 400)
    .replace(/\b([0-9a-f]{9})[0-9a-f]{7,31}\b/g, "$1")
    .replace(/\S*\/(\S+\/?)/g, "…/$1")
    .replace(/\s*—\s*/g, " ")
    .replace(/\bfanout (fanout-)/g, "$1");
  const m = /^(.{24,}?[.!?])(\s|$)/.exec(t);
  return (m ? m[1] : t).replace(/\s…$/, "…");
};
const FONT = () => (typeof document !== "undefined" ? getComputedStyle(document.body).fontFamily : "system-ui");

/** A folded layer: "9 parallel", its counts ("5 done · 2 running · 1 failed") and up to 4 stacked logos; a click
 *  opens the layer in place (its label then folds it back). The full view always shows every part. */
function GroupCard({
  n,
  group,
  all,
  p,
  w,
  h,
  bot,
  appear,
  delay,
  nowS,
  onOpen,
}: {
  n: RunNode;
  nowS: number;
  group: Group;
  all: RunNode[];
  p: Box;
  w: number;
  h: number;
  bot?: BotModel;
  appear: number;
  delay: number | null;
  onOpen: () => void;
}) {
  const counts = stateCounts(group.members, all);
  // one logo per distinct model, most used first
  const marks = new Map<string, { node: RunNode; n: number }>();
  for (const m of group.members) {
    const k = nodeModel(m, bot);
    const key = k ? `${k.model}|${k.provider ?? ""}` : m.id;
    const e = marks.get(key);
    if (e) e.n++;
    else marks.set(key, { node: m, n: 1 });
  }
  // a stack of up to 4: each model once (most used first), then more of the same, so the stack says "several"
  const kinds = [...marks.values()].sort((a, b) => b.n - a.n);
  const logos = kinds.slice(0, 4).map((k) => k.node);
  for (let i = 0; logos.length < Math.min(4, group.members.length); i++) {
    const k = kinds[i % kinds.length];
    const more = group.members.filter((m) => m !== k.node && !logos.includes(m) && nodeModel(m, bot)?.model === nodeModel(k.node, bot)?.model);
    if (!more.length) break;
    logos.push(more[0]);
  }
  const word = counts.map(([c, s]) => `${c} ${s}`).join(" · ");
  const t = n.started === undefined ? "" : span((n.ended ?? nowS) - n.started);
  return (
    <button
      type="button"
      className={`rg-card rg-group s-${n.state}${n.state === "failed" ? " bad" : ""}${delay !== null ? " enter" : ""}`}
      style={{ left: p.x, top: p.y, width: w, height: h, ...(delay !== null ? { animationDelay: `${delay}ms` } : {}) }}
      data-testid="run-group"
      data-node={n.id}
      data-layer={n.layer}
      data-state={n.state}
      data-count={group.members.length}
      data-appear={appear}
      title={`${group.members.map((m) => m.label).join("\n")}\n\nClick to show all ${group.members.length}`}
      aria-label={`${group.members.length} parallel parts: ${word}. Show them`}
      aria-expanded={false}
      onClick={onOpen}
    >
      <span className="rg-gt">
        <span className="rg-glogos" aria-hidden data-n={logos.length}>
          {logos.map((l) => (
            <Mark key={l.id} node={l} size={12} bot={bot} />
          ))}
        </span>
        <span className="rg-gn">{group.members.length} parallel</span>
        <span className="rg-gopen" data-testid="run-group-open">
          Show all
          <svg viewBox="0 0 24 24" width="10" height="10" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
            <path d="M6 9l6 6 6-6" />
          </svg>
        </span>
      </span>
      <span className="rg-gc">
        <span data-testid="run-group-counts">
          {counts.map(([c, s], i) => (
            <span key={s} className={`t-${s}`}>
              {i > 0 && " · "}
              {c} {s}
            </span>
          ))}
        </span>
        {t && <span className="rg-mt">{t}</span>}
        <StateMark state={n.state} word={STATE_WORD[n.state]} />
      </span>
    </button>
  );
}

function StateMark({ state, word, fixed }: { state: RunNode["state"]; word: string; fixed?: boolean }) {
  return (
    <i className="rg-st" aria-label={word}>
      {state === "running" ? <span className="rg-live" /> : state === "waiting" ? <span className="rg-wait" /> : fixed ? "↺" : GLYPH[state]}
    </i>
  );
}

function Card({
  n,
  label,
  mode,
  row,
  p,
  w,
  h,
  kind,
  unblocks,
  repaired,
  deps,
  mark,
  bot,
  note,
  on,
  hov,
  dim,
  appear,
  delay,
  nowS,
  onPointerDown,
  onClick,
  onHover,
}: {
  n: RunNode;
  label: string;
  mode: GraphMode;
  /** Panel grid: the row card (logo, a title of up to 2 lines, time, state; no chips). */
  row?: boolean;
  p: Box;
  w: number;
  h: number;
  kind: Size["kind"];
  unblocks: number;
  repaired?: boolean;
  /** The nodes this one waits on, as drawn (a failed node's repairs stand in for it). */
  deps?: RunNode[];
  mark: number;
  bot?: BotModel;
  /** The node's handoff text, when it wrote one. */
  note?: string;
  on: boolean;
  hov?: boolean;
  dim?: boolean;
  appear: number;
  delay: number | null;
  nowS: number;
  onPointerDown: (e: RPE) => void;
  onClick?: () => void;
  onHover?: (id: string | null) => void;
}) {
  const t = n.started === undefined ? "" : span((n.ended ?? nowS) - n.started);
  const title = useMemo(() => {
    // the panel shows two lines of title (the card's height), so the "…" lands on the second; the full view three
    if (row) return rowTitle(n, label, w);
    const font = mode === "panel" ? `550 11px ${FONT()}` : `600 13px ${FONT()}`;
    const room = mode === "panel" ? w - 16 - 3 - (kind === "gate" ? 16 : 0) : w - 28 - 3 - 18 - 12 - 12 - 6 - (kind === "gate" ? 22 : 0);
    return clampWords(label, room, mode === "panel" || kind === "leaf" ? 2 : 3, (s) => textWidth(s, font));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [label, mode, w, kind, row, n.started, n.ended]);
  const tries = n.attempts.length > 1 ? `×${n.attempts.length}` : "";
  const m = nodeModel(n, bot);
  const model = m ? modelLabel(m, n.effort ?? n.planned?.effort) : "";
  // a node waiting for its next try after a failed one reads as a retry, in amber
  const retry = n.state === "waiting" && n.attempts.length > 0;
  const word = retry ? "retry" : repaired ? "repaired" : STATE_WORD[n.state];
  const last = n.attempts[n.attempts.length - 1];
  const attempt = n.attempts.length > 1 ? `attempt ${last!.n} of ${n.attempts.length}` : "";
  const why = (n.state === "failed" || n.state === "blocked" || retry) && last?.reason ? last.reason : "";
  // a finished part says what it handed off, in a line (its handoff's first sentence, else the helper's summary)
  const said = !why && n.state === "done" && kind !== "leaf" ? firstLine(note ?? n.summary ?? "") : "";
  const waitsOn = n.state === "waiting" && !retry ? (deps ?? []) : [];
  const doing =
    n.state === "running"
      ? `Working${n.attempts.length > 1 ? `, try ${n.attempts.length}` : ""}; no handoff yet`
      : waitsOn.length
        ? `Waits on ${waitsOn.length} ${waitsOn.length === 1 ? "part" : "parts"}: ${waitsOn.filter((d) => d.state === "done").length} done`
        : "";
  // panel: one meta line, time and tries first, the route pill on the right (pending says so by its outline). A
  // pill that does not fit whole is left out, never cut to a letter.
  const meta = [t, tries].filter(Boolean).join(" · ");
  const pill = n.route?.replace(/^unspecified-/, "") ?? "";
  // measured where it is drawn: a pill the meta line cuts is dropped (the card's tooltip still names the route)
  const pillRef = useRef<HTMLSpanElement>(null);
  const [pillCut, setPillCut] = useState(false);
  useLayoutEffect(() => {
    setPillCut(false);
  }, [pill, w]);
  useLayoutEffect(() => {
    const el = pillRef.current;
    // exact: a pill one pixel short already shows "visual-engineeri…"
    if (el && !pillCut && el.scrollWidth > el.clientWidth) setPillCut(true);
  });
  const pillFits = mode === "panel" && !row && !!pill && !pillCut;
  return (
    <button
      type="button"
      className={`rg-card${row ? " row" : ""} s-${retry ? "retry" : n.state} k-${kind}${n.state === "failed" ? " bad" : ""}${repaired ? " repaired" : ""}${on ? " on" : ""}${hov ? " hov" : ""}${dim ? " dim" : ""}${delay !== null ? " enter" : ""}`}
      style={{ left: p.x, top: p.y, width: w, height: h, ...(delay !== null ? { animationDelay: `${delay}ms` } : {}) }}
      data-testid="run-node"
      data-node={n.id}
      data-layer={n.layer}
      data-state={n.state}
      data-size={kind}
      data-appear={appear}
      aria-pressed={on}
      title={mode === "panel" ? [n.label, t, tries && `${n.attempts.length} attempts`, n.route && `route: ${n.route}`].filter(Boolean).join(" · ") : undefined}
      aria-label={`${n.label}, ${word}`}
      onPointerDown={onPointerDown}
      onClick={onClick}
      onMouseEnter={onHover ? () => onHover(n.id) : undefined}
      onMouseLeave={onHover ? () => onHover(null) : undefined}
    >
      {row ? (
        <>
          <Mark node={n} size={mark} bot={bot} />
          <span className="rg-t">{title}</span>
          {kind === "gate" && <GateIcon size={11} />}
          <span className="rg-mt" style={{ width: ROW_TIME_W() }}>
            {t}
          </span>
          <StateMark state={n.state} word={word} fixed={repaired} />
        </>
      ) : mode === "panel" ? (
        <>
          <span className="rg-top">
            <span className="rg-t">{title}</span>
            {kind === "gate" && <GateIcon size={13} />}
          </span>
          <span className="rg-meta">
            <Mark node={n} size={mark} bot={bot} />
            {meta && <span className="rg-mt">{meta}</span>}
            {n.route && pillFits && (
              <span ref={pillRef} className="rg-route" data-testid="route-pill" title={n.routeWhy ? `route: ${n.route} · ${n.routeWhy}` : `route: ${n.route}`}>
                {pill}
              </span>
            )}
            <StateMark state={n.state} word={word} fixed={repaired} />
          </span>
        </>
      ) : (
        <>
          <span className="rg-top">
            <Mark node={n} size={mark} bot={bot} />
            <span className="rg-t">{title}</span>
            {kind === "gate" ? <GateIcon size={16} /> : null}
            <StateMark state={n.state} word={word} fixed={repaired} />
          </span>
          <span className="rg-meta">
            <span className="rg-mt">{[model, t && n.state === "running" ? `${t} so far` : t && n.ended !== undefined ? `took ${t}` : t].filter(Boolean).join(" · ")}</span>
            {kind === "lead" && unblocks > 0 && n.state !== "failed" && n.state !== "blocked" && (
              <span className="rg-lead" data-testid="node-lead" title={`${unblocks} parts wait on this one`}>
                unblocks {unblocks}
              </span>
            )}
          </span>
          <span className="rg-meta">
            <span className={`rg-word s-${retry ? "retry" : n.state}`}>{word}</span>
            {attempt && <span className="rg-att">{attempt}</span>}
          </span>
          {why && (
            <span className="rg-why" data-testid="node-why" title={why}>
              {why}
            </span>
          )}
          {said && (
            <span className="rg-why said" data-testid="node-said" title={said}>
              {said}
            </span>
          )}
          {!why && !said && doing && (
            <span className="rg-why said" data-testid="node-doing">
              {doing}
            </span>
          )}
          {n.route && (
            <span className="rg-meta rg-foot">
              <span className="rg-route" data-testid="route-pill" title={n.routeWhy ? `route: ${n.route} · ${n.routeWhy}` : `route: ${n.route}`}>
                route: {n.route.replace(/^unspecified-/, "")}
                {n.routeWhy ? ` · ${n.routeWhy}` : ""}
              </span>
            </span>
          )}
        </>
      )}
    </button>
  );
}
