// The Runs graph, in two sizes. "panel": compact cards that fit the 440px side panel, no zoom. "full": the whole
// run large over the chat column, with titles in full, model marks, durations, attempts and a handoff snippet on
// hover; there you can drag a card (its position only, kept per run), pan, zoom and Fit. Nothing here changes a
// run: no connecting, deleting, reordering, retrying or cancelling.
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties, type PointerEvent as RPE } from "react";
import type { AgentRun, RunNode } from "../lib/runs";
import { isRepaired, nodeModel, span } from "../lib/runs";
import { markFor, ModelIcon } from "../ui";
import { distinctLabels, layoutRun, routeEdge, type Box, type Lane, type Layout, type Size } from "./layout";
import { clampWords, modelLabel, plainSnippet, reducedMotion, STATE_WORD, textWidth } from "./format";

export type GraphMode = "panel" | "full";

// card heights carry the node's weight: a lead (plans, or unblocks several parts) is tallest, a leaf compact, the
// closing gate sits in a wider column
const SIZE = {
  panel: { cardH: 80, heights: { lead: 90, normal: 80, leaf: 64, gate: 80 }, gateW: 1.15, gutter: 30, rowGap: 14, pad: 12, minCard: 100, maxCard: 168, labelH: 24, mark: 14 },
  full: { cardH: 160, heights: { lead: 180, normal: 160, leaf: 140, gate: 168 }, gateW: 1.2, loose: true, gutter: 88, rowGap: 36, pad: 24, minCard: 220, maxCard: 280, labelH: 32, mark: 18 },
};
const STAGGER = { panel: 50, full: 70 };
const APPEAR = { panel: 260, full: 360 };
const DRAW = { panel: 280, full: 420 };
const MAX_ENTRANCE = { panel: 950, full: 1500 };
const DRAG_PX = 4;
const DRAWER_W = 392;
const MIN_FIT = 0.72; // below this the cards stop being readable: Fit keeps this scale and shows the open card
const PANEL_MIN_FIT = 0.8; // the panel shrinks a run that is a little too large to fit whole; past this it scrolls

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
export function Legend({ run, extra }: { run: AgentRun; extra?: React.ReactNode }) {
  const lay = layoutRun(run.nodes, { width: 400, ...SIZE.panel });
  return (
    <div className="rg-legend row" aria-label="Legend" data-testid="run-legend">
      {legend(run, lay.edges).map(([cls, word]) => (
        <span key={cls} className={cls}>
          {cls.startsWith("t-") ? <i aria-hidden /> : <b aria-hidden />}
          {word}
        </span>
      ))}
      {extra}
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
  maxH,
}: {
  run: AgentRun;
  handoffs: Record<string, string>;
  mode: GraphMode;
  /** Panel: told whether the run is larger than the box (the panel then offers the full view). */
  onOverflow?: (over: boolean) => void;
  /** Panel: the box's height cap (what the side panel has left under the plan card). */
  maxH?: number;
  /** The bot's own model: the last fallback for a node's logo. */
  bot?: BotModel;
  /** Width to lay out into (the box's inner width). */
  width: number;
  open: string | null;
  onOpen: (id: string | null) => void;
  nowS: number;
}) {
  const z = SIZE[mode];
  const lay: Layout = useMemo(() => layoutRun(run.nodes, { width: Math.max(width, 200), ...z }), [run.nodes, width, mode]);
  const byId = useMemo(() => new Map(run.nodes.map((n) => [n.id, n])), [run.nodes]);

  // full view: dragged positions override the layout's, per run
  const [over, setOver] = useState<Record<string, Box>>(() => (mode === "full" ? loadPos(run.id) : {}));
  useEffect(() => setOver(mode === "full" ? loadPos(run.id) : {}), [run.id, mode]);
  const at = (id: string): Box => over[id] ?? lay.pos.get(id)!;
  const sz = (id: string): Size => lay.size.get(id)!;

  // entrance: cards in layer order (top to bottom inside a layer), then each edge once both ends are in
  const appear = useMemo(() => {
    const ids = lay.columns.flatMap((c) => [...lay.pos.entries()].filter(([id]) => byId.get(id)!.layer === c.layer).sort((a, b) => a[1].y - b[1].y).map(([id]) => id));
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

  // ---- panel: the box scrolls both ways when the run is larger; it opens on the first running (else failed)
  // node, and soft fades on the sides that hold more
  const pbox = useRef<HTMLDivElement>(null);
  const [more, setMore] = useState({ l: false, r: false, t: false, b: false });
  const measure = useCallback(() => {
    const el = pbox.current;
    if (!el) return;
    const m = {
      l: el.scrollLeft > 1,
      r: el.scrollLeft + el.clientWidth < el.scrollWidth - 1,
      t: el.scrollTop > 1,
      b: el.scrollTop + el.clientHeight < el.scrollHeight - 1,
    };
    setMore((p) => (p.l === m.l && p.r === m.r && p.t === m.t && p.b === m.b ? p : m));
  }, []);
  // a run only a little larger than the box is shown whole, scaled down (auto-fit); a larger one keeps its size and
  // the box scrolls to its focus node
  const fitK = useMemo(() => {
    if (mode !== "panel") return 1;
    const k = Math.min(1, width / lay.w, (maxH ?? 460) / lay.h);
    return k < 1 && k >= PANEL_MIN_FIT ? Math.floor(k * 1000) / 1000 : 1;
  }, [mode, width, lay, maxH]);
  const focusedFor = useRef<string | null>(null);
  useLayoutEffect(() => {
    const el = pbox.current;
    if (mode !== "panel" || !el) return;
    const key = `${run.id}@${maxH ?? ""}@${fitK}`;
    if (focusedFor.current !== key) {
      // once per run (and box height): later refreshes keep wherever the person scrolled to
      focusedFor.current = key;
      const f = focusNode(run, lay.pos);
      if (f) {
        const p = lay.pos.get(f.id)!;
        const s = lay.size.get(f.id)!;
        // start at a column's left edge (never a sliced card) as far left as still shows the whole focus card
        const maxL = el.scrollWidth - el.clientWidth;
        const starts = lay.columns.map((c) => Math.max(0, c.x - z.pad)).sort((x, y) => x - y);
        const fits = starts.find((x) => x <= p.x && p.x + s.w + z.pad <= x + el.clientWidth);
        el.scrollLeft = Math.min(maxL, fits ?? Math.max(0, p.x + s.w / 2 - el.clientWidth / 2));
        el.scrollTop = Math.max(0, Math.min(el.scrollHeight - el.clientHeight, p.y + s.h / 2 - el.clientHeight / 2));
      } else {
        el.scrollLeft = 0;
        el.scrollTop = 0;
      }
    }
    measure();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run.id, mode, lay, maxH, fitK]);
  const overflows = more.l || more.r || more.t || more.b;
  useEffect(() => {
    if (mode === "panel") onOverflow?.(overflows);
  }, [overflows, mode, onOverflow]);

  const [hover, setHover] = useState<string | null>(null);
  const moved = Object.keys(over).length > 0;
  // keep the click-to-open for the node the person opened in the panel
  // lanes from the drawn positions (dragged cards included): one per distinct card x
  const lanes: Lane[] = [];
  for (const n of run.nodes) {
    const p = at(n.id);
    const s = sz(n.id);
    const lane = lanes.find((l) => Math.abs(l.x - p.x) < lay.cardW / 2);
    if (lane) {
      lane.spans.push([p.y, s.h]);
      lane.w = Math.max(lane.w, s.w);
    } else lanes.push({ x: p.x, w: s.w, spans: [[p.y, s.h]] });
  }
  const edges = moved ? lay.edges.map((e) => ({ ...e, ...edgePath(at(e.from), sz(e.from), at(e.to), sz(e.to), lanes, z.rowGap) })) : lay.edges;
  const labels = useMemo(() => distinctLabels(run.nodes), [run.nodes]);
  // edges meeting at one card share one arrowhead (the last solid one wins, so a dashed edge never colours it)
  const arrowFor = new Map<string, string>();
  for (const e of [...edges].sort((a, b) => Number(!a.broken) - Number(!b.broken))) arrowFor.set(e.to, e.key);
  const mixed = new Set<string>();
  for (const e of edges) if (edges.some((f) => f.to === e.to && f.broken !== e.broken)) mixed.add(e.to);
  const lastIn = (e: { from: string; to: string }) => Math.max(appear.get(e.from)!.delay, appear.get(e.to)!.delay) + APPEAR[mode] * 0.6;

  const canvas = (
    <div
      className="rg-canvas"
      style={mode === "full" ? { width: lay.w, height: lay.h, transform: `translate(${view.x}px, ${view.y}px) scale(${view.k})` } : { width: lay.w, height: lay.h }}
      data-testid="run-canvas"
    >
      {lay.columns.map((c) => (
        <div key={c.layer} className="rg-col" style={{ left: c.x, top: c.y, width: lay.cardW }} data-testid="run-col">
          {c.label}
        </div>
      ))}
      <svg className={`rg-edges${hover ? " focus" : ""}`} width={lay.w} height={lay.h} aria-hidden overflow="visible">
        <defs>
          {edges.map((e) => (
            <linearGradient key={e.key} id={`g-${cssId(run.id)}-${cssId(e.key)}`} gradientUnits="userSpaceOnUse" x1={e.x1} y1={e.y1} x2={e.x2} y2={e.y2}>
              <stop offset="0" className={`rg-stop s-${byId.get(e.from)!.state}`} />
              <stop offset="1" className={`rg-stop s-${byId.get(e.to)!.state}`} />
            </linearGradient>
          ))}
        </defs>
        {edges.map((e) => {
          const into = byId.get(e.to)!.state === "running";
          return (
            <g
              key={e.key}
              className={`rg-edge${e.broken ? " broken" : ""}${e.kind === "repair" ? " repair" : ""}${into ? " flow" : ""}${animate ? " enter" : ""}${hover && (e.from === hover || e.to === hover) ? " lit" : ""}`}
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
          .filter((e) => arrowFor.get(e.to) === e.key)
          .map((e) => (
            <path
              key={`a-${e.key}`}
              className={`rg-arrow${e.broken && !mixed.has(e.to) ? " broken" : ""}${e.kind === "repair" ? " repair" : ""}${byId.get(e.to)!.state === "running" ? " flow" : ""}${animate ? " enter" : ""}${hover && (e.from === hover || e.to === hover) ? " lit" : ""}`}
              style={{ "--d": `${Math.round(lastIn(e) + DRAW[mode])}ms` } as CSSProperties}
              d={mode === "full" ? `M${e.x2},${e.y2} l-9,-6 l0,12 Z` : `M${e.x2},${e.y2} l-7,-4.5 l0,9 Z`}
              data-testid="run-arrow"
            />
          ))}
      </svg>
      {run.nodes.map((n) => {
        const p = at(n.id);
        const a = appear.get(n.id)!;
        return (
          <Card
            key={n.id}
            n={n}
            label={labels.get(n.id)!}
            mode={mode}
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
            hov={mode === "full" && n.id === hover}
            dim={mode === "full" && !!hover && n.id !== hover && !edges.some((e) => (e.from === hover && e.to === n.id) || (e.to === hover && e.from === n.id))}
            appear={a.i}
            delay={animate ? a.delay : null}
            nowS={nowS}
            onPointerDown={(e) => {
              e.stopPropagation();
              onDown(e, n.id);
            }}
            onClick={mode === "panel" ? () => onOpen(n.id === open ? null : n.id) : undefined}
            onHover={mode === "full" ? setHover : undefined}
          />
        );
      })}
    </div>
  );

  if (mode === "panel")
    return (
      <>
        <div
          ref={pbox}
          className={`rg rg-panel${still ? " still" : ""}`}
          data-testid="run-graph"
          data-cols={lay.columns.length}
          data-layout-ms={lay.ms.toFixed(2)}
          data-crossings={lay.crossings}
          data-overflow={overflows ? "true" : "false"}
          data-fit={fitK < 1 ? fitK.toFixed(2) : undefined}
          style={{ height: Math.ceil(lay.h * fitK), ...(maxH ? { maxHeight: maxH } : {}) }}
          onScroll={measure}
        >
          {fitK < 1 ? (
            <div className="rg-fit" style={{ width: Math.floor(lay.w * fitK), height: Math.ceil(lay.h * fitK) }}>
              <div style={{ transform: `scale(${fitK})`, transformOrigin: "0 0" }}>{canvas}</div>
            </div>
          ) : (
            canvas
          )}
        </div>
        {(["l", "r", "t", "b"] as const).map((k) => (
          <i key={k} className={`rg-fade ${k}${more[k] ? " on" : ""}`} aria-hidden data-testid={`run-fade-${k}`} data-on={more[k] ? "true" : "false"} />
        ))}
      </>
    );
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
    const font = mode === "panel" ? `550 11px ${FONT()}` : `600 13px ${FONT()}`;
    const room = mode === "panel" ? w - 16 - 3 - (kind === "gate" ? 16 : 0) : w - 28 - 3 - 18 - 12 - 12 - 6 - (kind === "gate" ? 22 : 0);
    return clampWords(label, room, kind === "leaf" ? 2 : 3, (s) => textWidth(s, font));
  }, [label, mode, w, kind]);
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
  // panel: one meta line, time and tries first, the route pill on the right (pending says so by its outline)
  const meta = [t, tries].filter(Boolean).join(" · ");
  return (
    <button
      type="button"
      className={`rg-card s-${retry ? "retry" : n.state} k-${kind}${n.state === "failed" ? " bad" : ""}${repaired ? " repaired" : ""}${on ? " on" : ""}${hov ? " hov" : ""}${dim ? " dim" : ""}${delay !== null ? " enter" : ""}`}
      style={{ left: p.x, top: p.y, width: w, height: h, ...(delay !== null ? { animationDelay: `${delay}ms` } : {}) }}
      data-testid="run-node"
      data-node={n.id}
      data-layer={n.layer}
      data-state={n.state}
      data-size={kind}
      data-appear={appear}
      aria-pressed={on}
      title={mode === "panel" ? `${n.label}${tries ? ` · ${n.attempts.length} attempts` : ""}` : undefined}
      aria-label={`${n.label}, ${word}`}
      onPointerDown={onPointerDown}
      onClick={onClick}
      onMouseEnter={onHover ? () => onHover(n.id) : undefined}
      onMouseLeave={onHover ? () => onHover(null) : undefined}
    >
      {mode === "panel" ? (
        <>
          <span className="rg-top">
            <span className="rg-t">{title}</span>
            {kind === "gate" && <GateIcon size={13} />}
          </span>
          <span className="rg-meta">
            <Mark node={n} size={mark} bot={bot} />
            {meta && <span className="rg-mt">{meta}</span>}
            {n.route && (
              <span className="rg-route" data-testid="route-pill" title={n.routeWhy ? `route: ${n.route} · ${n.routeWhy}` : `route: ${n.route}`}>
                {n.route.replace(/^unspecified-/, "")}
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
