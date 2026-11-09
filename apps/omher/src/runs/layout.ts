// Layered layout for the Runs graph, no dependency: columns are layers, rows are ordered to cut edge
// crossings (barycenter of the neighbours' positions, two down/up sweeps, keep the best order seen), cards never
// overlap, and every edge leaves its source's right-middle and enters its target's left-middle.
import type { RunNode } from "../lib/runs";

export interface Box {
  x: number;
  y: number;
}
/** How much a node weighs in the run: a lead (plans, or unblocks two or more parts) is the tallest, a leaf (nothing
 *  waits on it) the most compact, the gate (the closing verify) is wider and marked. */
export type NodeSize = "lead" | "normal" | "leaf" | "gate";
export interface Size {
  w: number;
  h: number;
  kind: NodeSize;
  /** How many nodes wait on this one (dependencies and repair links). */
  unblocks: number;
}
export interface Edge {
  key: string;
  from: string;
  to: string;
  /** "dep" = a dependency; "repair" = a repair node's link back to the node it repairs. */
  kind: "dep" | "repair";
  /** Out of a failed (or blocked) node: drawn dashed. */
  broken: boolean;
  d: string;
  /** Arrowhead, a small triangle whose tip is the edge's end point. */
  arrow: string;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}
export interface Column {
  layer: number;
  x: number;
  /** Top of the label: just above the column's first card. */
  y: number;
  label: string;
  count: number;
}
export interface Layout {
  pos: Map<string, Box>;
  size: Map<string, Size>;
  edges: Edge[];
  columns: Column[];
  w: number;
  h: number;
  cardW: number;
  cardH: number;
  /** Crossings between adjacent layers in the order drawn (for tests and the timing attribute). */
  crossings: number;
  ms: number;
}
export interface LayoutOpts {
  /** Width to fit into; the card width follows from it (clamped to [minCard, maxCard]). */
  width: number;
  cardH: number;
  gutter: number;
  rowGap: number;
  pad: number;
  minCard: number;
  maxCard: number;
  /** Height of the column-label band above the cards (0 = none). */
  labelH: number;
  /** Card heights by size; `cardH` is the normal one and the default for any size left out. */
  heights?: Partial<Record<NodeSize, number>>;
  /** Width of a gate-only column, as a multiple of the card width (default 1.2). */
  gateW?: number;
  /** The graph may be wider than `width` (the full view pans): the gate always gets `gateW`. */
  loose?: boolean;
  /** Several edges into (or out of) one card meet its side at their own points, spread over its middle 70% in the
   *  order of their other ends, instead of all at the middle (the panel's compact cards: traceable edges). */
  ports?: boolean;
}

type N = Pick<RunNode, "id" | "deps" | "layer" | "state" | "label"> & { repairOf?: string; route?: string; role?: string };

/** A node's size from its role and how many nodes wait on it. */
export function sizeKind(n: N, unblocks: number): NodeSize {
  const t = `${n.id} ${n.label}`.toLowerCase();
  if (unblocks === 0 && (n.role === "verify" || /verif|\bgate\b|\bqa\b/.test(t))) return "gate";
  if (n.role === "plan" || n.role === "lead" || unblocks >= 2) return "lead";
  if (unblocks === 0) return "leaf";
  return "normal";
}

const ARROW = 5;

/** One column an edge must cross: its left x, its width and [top, height] of each card in it. */
export interface Lane {
  x: number;
  w: number;
  spans: [number, number][];
}

/** An edge's path. It leaves the source's right-middle and enters the target's left-middle, both with horizontal
 *  tangents. An edge that skips columns crosses each one through the free band nearest its straight line (above,
 *  between or below the cards), never under a card, so it can never seem to enter a card from above or below. */
export function routeEdge(x1: number, y1: number, x2: number, y2: number, lanes: Lane[], rowGap: number): string {
  const seg = (ax: number, ay: number, bx: number, by: number) => {
    const k = Math.max(12, (bx - ax) / 2);
    return ` C${ax + k},${ay} ${bx - k},${by} ${bx},${by}`;
  };
  // straight leads out of and into every card side, sized by the gutter they sit in: all curves in one gutter
  // start and end at the same x, so edges converging on one card nest instead of crossing
  // (a narrow gutter, as in the panel's compact cards, keeps most of its width for the curve)
  const lead = (gap: number) => Math.min(28, Math.max(Math.min(6, gap / 5), gap / 3.5));
  // the gutters the edge passes: [left, right] of each free band between x1, the crossed columns and x2
  const walls = [x1, ...lanes.flatMap((l) => [l.x, l.x + l.w]), x2];
  const leads = walls.flatMap((_, k) => (k % 2 === 0 && k + 1 < walls.length ? [lead(walls[k + 1] - walls[k])] : []));
  let d = `M${x1},${y1} L${x1 + leads[0]},${y1}`;
  let cx = x1 + leads[0];
  let cy = y1;
  lanes.forEach((lane, i) => {
    const t = (lane.x + lane.w / 2 - x1) / Math.max(1, x2 - x1);
    const want = y1 + (y2 - y1) * t;
    const sp = [...lane.spans].sort((a, b) => a[0] - b[0]);
    const blocked = sp.some(([y, h]) => want > y - 3 && want < y + h + 3);
    let gy = want;
    if (blocked) {
      const bands = [sp[0][0] - rowGap / 2, ...sp.map(([y, h], j) => (j + 1 < sp.length ? (y + h + sp[j + 1][0]) / 2 : y + h + rowGap / 2))];
      gy = bands.reduce((a, b) => (Math.abs(b - want) < Math.abs(a - want) ? b : a));
    }
    d += seg(cx, cy, lane.x - leads[i], gy) + ` L${lane.x + lane.w + leads[i + 1]},${gy}`;
    cx = lane.x + lane.w + leads[i + 1];
    cy = gy;
  });
  const into = leads[leads.length - 1];
  return d + seg(cx, cy, x2 - into, y2) + ` L${x2},${y2}`;
}

/** Labels that stay apart when clipped: when two labels share a long start ("Codex skill discovery reads …" and
 *  "Codex skill discovery reads … (Hermes)"), the longer one shows its first words and then what differs. */
export function distinctLabels(nodes: { id: string; label: string }[], keep = 22): Map<string, string> {
  const out = new Map<string, string>();
  for (const n of nodes) {
    let label = n.label;
    for (const o of nodes) {
      if (o.id === n.id || o.label.slice(0, keep) !== n.label.slice(0, keep)) continue;
      let i = 0;
      while (i < n.label.length && n.label[i] === o.label[i]) i++;
      const rest = n.label.slice(i).trim();
      if (rest && n.label.length > o.label.length) {
        // put what differs first: "Codex skill discovery reads .agents/skills (Hermes)" -> "Hermes: Codex skill …"
        label = `${rest.replace(/^[(\[]|[)\]]$/g, "")}: ${n.label.slice(0, i).trim()}`;
      }
    }
    out.set(n.id, label);
  }
  return out;
}

/** All links: deps, plus repair links (failed node -> its repair). A dependency on a failed node that has
 *  repairs is drawn from those repairs instead (OMH counts a failed node whose repairs are done as satisfied, so
 *  the repairs are what the dependent waits on), when they sit in an earlier column than the dependent. */
export function linksOf(nodes: N[]): { from: string; to: string; kind: "dep" | "repair" }[] {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const repairs = new Map<string, N[]>();
  for (const n of nodes) if (n.repairOf && byId.has(n.repairOf)) (repairs.get(n.repairOf) ?? repairs.set(n.repairOf, []).get(n.repairOf)!).push(n);
  const out: { from: string; to: string; kind: "dep" | "repair" }[] = [];
  const seen = new Set<string>();
  const add = (from: string, to: string, kind: "dep" | "repair") => {
    if (seen.has(`${from}>${to}`)) return;
    seen.add(`${from}>${to}`);
    out.push({ from, to, kind });
  };
  for (const n of nodes) {
    for (const d of n.deps) {
      const src = byId.get(d);
      if (!src) continue;
      const via = repairs.get(d)?.filter((r) => r.layer < n.layer && r.id !== n.id) ?? [];
      if ((src.state === "failed" || src.state === "blocked") && via.length) for (const r of via) add(r.id, n.id, "dep");
      else add(d, n.id, "dep");
    }
    if (n.repairOf && byId.has(n.repairOf) && !n.deps.includes(n.repairOf)) add(n.repairOf, n.id, "repair");
  }
  return out;
}

/** Crossings between consecutive layers for a given row order (edges spanning more layers are not counted). */
export function countCrossings(order: string[][], links: { from: string; to: string }[], layerOf: Map<string, number>): number {
  const idx = new Map<string, number>();
  for (const col of order) col.forEach((id, i) => idx.set(id, i));
  let c = 0;
  for (let l = 0; l + 1 < order.length; l++) {
    const es = links
      .filter((e) => layerOf.get(e.from) === l && layerOf.get(e.to) === l + 1)
      .map((e) => [idx.get(e.from)!, idx.get(e.to)!] as const);
    for (let i = 0; i < es.length; i++)
      for (let j = i + 1; j < es.length; j++) if ((es[i][0] - es[j][0]) * (es[i][1] - es[j][1]) < 0) c++;
  }
  return c;
}

/** Row order per layer: the input order, then barycenter sweeps (down by predecessors, up by successors). */
export function orderLayers(nodes: N[]): { order: string[][]; crossings: number; before: number } {
  const layers: string[][] = [];
  for (const n of nodes) (layers[n.layer] ??= []).push(n.id);
  for (let i = 0; i < layers.length; i++) layers[i] ??= [];
  const links = linksOf(nodes);
  const layerOf = new Map(nodes.map((n) => [n.id, n.layer]));
  const preds = new Map<string, string[]>();
  const succs = new Map<string, string[]>();
  for (const e of links) {
    (preds.get(e.to) ?? preds.set(e.to, []).get(e.to)!).push(e.from);
    (succs.get(e.from) ?? succs.set(e.from, []).get(e.from)!).push(e.to);
  }
  // position = index / length, so neighbours in layers of different sizes compare fairly
  const where = (order: string[][]) => {
    const m = new Map<string, number>();
    for (const col of order) col.forEach((id, i) => m.set(id, (i + 0.5) / col.length));
    return m;
  };
  const sweep = (order: string[][], down: boolean) => {
    const next = order.map((c) => [...c]);
    const range = down ? [...next.keys()].slice(1) : [...next.keys()].reverse().slice(1);
    for (const l of range) {
      const pos = where(next);
      const nb = down ? preds : succs;
      const key = new Map<string, number>();
      next[l].forEach((id, i) => {
        const ps = (nb.get(id) ?? []).map((p) => pos.get(p)!).filter((v) => v !== undefined);
        key.set(id, ps.length ? ps.reduce((a, b) => a + b, 0) / ps.length : (i + 0.5) / next[l].length);
      });
      // stable: equal keys keep their current order
      next[l] = next[l].map((id, i) => [id, i] as const).sort((a, b) => key.get(a[0])! - key.get(b[0])! || a[1] - b[1]).map(([id]) => id);
    }
    return next;
  };
  const before = countCrossings(layers, links, layerOf);
  let best = layers;
  let bestC = before;
  let cur = layers;
  for (let i = 0; i < 2 && bestC > 0; i++) {
    for (const down of [true, false]) {
      cur = sweep(cur, down);
      const c = countCrossings(cur, links, layerOf);
      if (c < bestC) {
        best = cur;
        bestC = c;
      }
    }
  }
  return { order: best, crossings: bestC, before };
}

/** A short name for what a column does, from its nodes' ids, labels and routes ("Build · 4", "Verify"). */
export function columnLabel(nodes: N[], layer: number): string {
  const role = (n: N) => {
    const t = `${n.id} ${n.label} ${n.route ?? ""}`.toLowerCase();
    if (n.repairOf) return "Repair";
    if (/verif|\bqa\b|gate/.test(t)) return "Verify";
    if (/review|audit/.test(t)) return "Review";
    if (/\b(check|test|baseline|probe|measure|bench)/.test(t)) return "Check";
    if (/\b(plan|design|discover|research|spec)/.test(t)) return layer === 0 ? "Plan" : "Build";
    return "Build";
  };
  const counts = new Map<string, number>();
  for (const n of nodes) counts.set(role(n), (counts.get(role(n)) ?? 0) + 1);
  const names = [...counts.entries()].sort((a, b) => b[1] - a[1]).map(([k]) => k);
  const name = names.slice(0, 2).join(" + ");
  return `${name} · ${nodes.length}`;
}

/** A layer's one name, the same in the panel's chips and its column labels: "L4 · Verify" (the column label's
 *  leading role, without its count). */
export function layerName(layer: number, label: string): string {
  const role = label.replace(/ · \d+$/, "").split(" + ")[0];
  return role ? `L${layer + 1} · ${role}` : `L${layer + 1}`;
}

export function layoutRun(nodes: N[], o: LayoutOpts): Layout {
  const t0 = performance.now();
  const { order, crossings } = orderLayers(nodes);
  const cols = order.length;
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const links = linksOf(nodes);
  const out = new Map<string, number>();
  for (const e of links) out.set(e.from, (out.get(e.from) ?? 0) + 1);
  const kind = new Map(nodes.map((n) => [n.id, sizeKind(n, out.get(n.id) ?? 0)]));
  const H = (k: NodeSize) => o.heights?.[k] ?? o.cardH;
  // a column holding only the gate is wider; the rest share one width
  const gateCol = order.map((col) => col.length > 0 && col.every((id) => kind.get(id) === "gate"));
  const g = o.gateW ?? 1.2;
  const weight = gateCol.reduce((a, isGate) => a + (isGate ? g : 1), 0);
  const free = o.width - o.pad * 2 - (cols - 1) * o.gutter;
  const cardW = Math.round(Math.min(o.maxCard, Math.max(o.minCard, cols ? free / weight : o.maxCard)));
  // the gate takes what is left of the width, between one card and `gateW` cards
  const plain = gateCol.filter((x) => !x).length;
  const gates = cols - plain;
  const gateW = !gates ? cardW : o.loose ? Math.round(cardW * g) : Math.round(Math.max(cardW, Math.min(cardW * g, (free - plain * cardW) / gates)));
  const colW = gateCol.map((isGate) => (isGate ? gateW : cardW));
  const colH = (col: string[]) => col.reduce((a, id) => a + H(kind.get(id)!), 0) + Math.max(0, col.length - 1) * o.rowGap;
  const top = o.pad + o.labelH;
  const fullH = Math.max(o.cardH, ...order.map(colH));
  const pos = new Map<string, Box>();
  const size = new Map<string, Size>();
  const columns: Column[] = [];
  const used = colW.reduce((a, w) => a + w, 0) + Math.max(0, cols - 1) * o.gutter;
  // centre the whole graph horizontally when it is narrower than the box
  const left = Math.max(o.pad, Math.round((o.width - used) / 2));
  let x = left;
  order.forEach((col, l) => {
    // each column is centred against the tallest one
    let y = top + Math.round((fullH - colH(col)) / 2);
    for (const id of col) {
      const k = kind.get(id)!;
      pos.set(id, { x, y });
      size.set(id, { w: colW[l], h: H(k), kind: k, unblocks: out.get(id) ?? 0 });
      y += H(k) + o.rowGap;
    }
    columns.push({ layer: l, x, y: o.pad, label: columnLabel(col.map((id) => byId.get(id)!), l), count: col.length });
    x += colW[l] + o.gutter;
  });
  const lanes: Lane[] = order.map((col, l) => ({ x: columns[l].x, w: colW[l], spans: col.map((id) => [pos.get(id)!.y, size.get(id)!.h] as [number, number]) }));
  // ports: the k-th of n edges on a card's side meets it at (k + 1) / (n + 1) of its middle 70%
  const port = new Map<string, number>();
  if (o.ports) {
    const mid = (id: string) => pos.get(id)!.y + size.get(id)!.h / 2;
    for (const [side, end, other] of [["in", "to", "from"], ["out", "from", "to"]] as const) {
      const by = new Map<string, typeof links>();
      for (const e of links) (by.get(e[end]) ?? by.set(e[end], []).get(e[end])!).push(e);
      for (const [id, es] of by) {
        if (es.length < 2) continue;
        const h = size.get(id)!.h;
        [...es]
          .sort((p, q) => mid(p[other]) - mid(q[other]))
          .forEach((e, k) => port.set(`${side}:${e.from}>${e.to}`, Math.round(pos.get(id)!.y + h * 0.15 + h * 0.7 * ((k + 1) / (es.length + 1)))));
      }
    }
  }
  const edges: Edge[] = links.map((e) => {
    const a = pos.get(e.from)!;
    const b = pos.get(e.to)!;
    const sa = size.get(e.from)!;
    const sb = size.get(e.to)!;
    const x1 = a.x + sa.w;
    const y1 = port.get(`out:${e.from}>${e.to}`) ?? a.y + sa.h / 2;
    const x2 = b.x;
    const y2 = port.get(`in:${e.from}>${e.to}`) ?? b.y + sb.h / 2;
    const src = byId.get(e.from)!;
    return {
      key: `${e.from}>${e.to}`,
      from: e.from,
      to: e.to,
      kind: e.kind,
      broken: e.kind === "dep" && (src.state === "failed" || src.state === "blocked"),
      d: routeEdge(x1, y1, x2, y2, lanes.slice(src.layer + 1, byId.get(e.to)!.layer), o.rowGap),
      arrow: `M${x2},${y2} L${x2 - ARROW},${y2 - ARROW * 0.7} L${x2 - ARROW},${y2 + ARROW * 0.7} Z`,
      x1,
      y1,
      x2,
      y2,
    };
  });
  const w = Math.max(o.width, left + used + o.pad);
  const h = top + fullH + o.pad;
  return { pos, size, edges, columns, w, h, cardW, cardH: o.cardH, crossings, ms: performance.now() - t0 };
}
