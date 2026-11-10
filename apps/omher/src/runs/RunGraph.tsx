// A run drawn as the OMH TUI's box view (boxView.ts holds the layout): frontiers of equal boxes of four text
// lines, connected by 1px lines with ▼ heads, in a monospace font. A box is a 1px outline on the page with one
// 2px state line on its left edge: no fill, gradient, shadow or glow. Under the boxes, "Dependencies" and "Node
// details" are plain text. Two sizes: "panel" flows in the side panel at its width (a frontier too wide for it
// wraps, and a very long one shows its first rows and "Show all"); "full" is the same drawing over the chat
// column, where you can drag a box (its position only, kept per run), pan, zoom and Fit. The only motion is the
// boxes appearing one by one and a slow dash on the lines into a running node. Nothing here changes a run.
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties, type PointerEvent as RPE, type ReactNode } from "react";
import type { AgentRun, RunNode } from "../lib/runs";
import { nodeModel } from "../lib/runs";
import { t } from "../i18n";
import { markFor, ModelIcon } from "../ui";
import { boxText, durationOf, factsOf, GEOMETRY, layoutBoxes, routeGroup, statusOf, titleOf, type BoxLayout, type EdgeHead, type EdgeLine, type Rect } from "./boxView";
import { reducedMotion } from "./format";

export type GraphMode = "panel" | "full";
export interface BotModel {
  model: string;
  provider: string;
}

/** The drawing's type: 12px in the panel, 12.5px in the full view, on 18px lines. */
export const TYPE = { panel: { font: 12, line: 18 }, full: { font: 12.5, line: 18 } };
export const MONO = 'ui-monospace, "SF Mono", Menlo, monospace';
/** The panel shows this many rows of a long frontier before "Show all". */
export const PANEL_CAP_ROWS = 8;
/** The Dependencies list shows this many edges before "Show all". */
export const DEPS_CAP = 12;
const STAGGER = 60;
const MAX_ENTRANCE = 900;
const DRAG_PX = 4;
const DRAWER_W = 392;
const MIN_FIT = 0.4;
/** Full view: the room around the drawing. */
const MARGIN = 28;
const MAX_FIT = 1; // the type is never drawn larger than its own size

const widths = new Map<number, number>();
/** One character cell of the drawing's font at `px`, measured where it is drawn (7.2px at 12px without a DOM). */
function cellWidth(px: number): number {
  if (typeof document === "undefined") return px * 0.6;
  let w = widths.get(px);
  if (w === undefined) {
    const probe = document.createElement("span");
    probe.style.cssText = `position:absolute;visibility:hidden;white-space:pre;font:400 ${px}px ${MONO}`;
    probe.textContent = "0".repeat(100);
    document.body.appendChild(probe);
    w = probe.getBoundingClientRect().width / 100 || px * 0.6;
    probe.remove();
    widths.set(px, w);
  }
  return w;
}

/** The node's 12px mark: what it ran on, the agent CLI it went to, the model its route goes to, else the bot's. */
function Mark({ node, bot }: { node: RunNode; bot?: BotModel }) {
  const m = nodeModel(node, bot);
  const mark = m && markFor(m.model, m.provider);
  return (
    <span className="bx-mk" data-testid="node-mark" data-mark={mark ?? "none"} data-source={m?.source ?? "none"}>
      <ModelIcon model={m?.model} provider={m?.provider} size={12} />
    </span>
  );
}

/** Positions saved for one run in the full view: { nodeId: {x, y} } in drawing coordinates. */
const keyOf = (runId: string) => `omher.plans.pos.${runId}`;
type Pos = Record<string, { x: number; y: number }>;
function loadPos(runId: string): Pos {
  try {
    const v = JSON.parse(localStorage.getItem(keyOf(runId)) ?? "{}");
    return v && typeof v === "object" ? v : {};
  } catch {
    return {};
  }
}
function savePos(runId: string, pos: Pos) {
  try {
    if (Object.keys(pos).length) localStorage.setItem(keyOf(runId), JSON.stringify(pos));
    else localStorage.removeItem(keyOf(runId));
  } catch {
    /* no storage */
  }
}

export function RunGraph({
  run,
  mode,
  width,
  open,
  onOpen,
  nowS,
  bot,
  detail,
}: {
  run: AgentRun;
  mode: GraphMode;
  /** The width to draw into (the box's inner width). */
  width: number;
  open: string | null;
  onOpen: (id: string | null) => void;
  nowS: number;
  /** The bot's own model: the last fallback for a node's mark. */
  bot?: BotModel;
  /** Panel: the open node's detail, first under "Node details" (the full view shows it in a drawer instead). */
  detail?: ReactNode;
}) {
  const type = TYPE[mode];
  const cw = cellWidth(type.font);
  // "Show all" on a long frontier (panel) and on the Dependencies list; both reset with the run
  const [opened, setOpened] = useState<Set<number>>(() => new Set());
  const [allDeps, setAllDeps] = useState(false);
  useEffect(() => {
    setOpened(new Set());
    setAllDeps(false);
  }, [run.id]);
  const lay: BoxLayout = useMemo(
    () =>
      layoutBoxes(run, {
        cells: Math.floor((Math.max(width, 200) - (mode === "full" ? 2 * MARGIN : 0)) / cw),
        metrics: { cw, line: type.line },
        capRows: mode === "panel" ? PANEL_CAP_ROWS : undefined,
        opened,
      }),
    [run, width, cw, type.line, mode, opened],
  );
  const byId = useMemo(() => new Map(run.nodes.map((n) => [n.id, n])), [run.nodes]);

  // full view: dragged positions override the layout's, per run
  const [over, setOver] = useState<Pos>(() => (mode === "full" ? loadPos(run.id) : {}));
  useEffect(() => setOver(mode === "full" ? loadPos(run.id) : {}), [run.id, mode]);
  const rect = useCallback(
    (id: string): Rect => {
      const p = over[id] ?? lay.at.get(id)!;
      return { x: p.x, y: p.y, w: lay.boxW, h: lay.boxH };
    },
    [over, lay],
  );
  const moved = Object.keys(over).some((id) => lay.at.has(id));

  // the lines between the boxes as they stand now
  const edges = useMemo(() => {
    const lines: EdgeLine[] = [];
    const heads: EdgeHead[] = [];
    const tone = (id: string) => statusOf(byId.get(id)!, run).tone;
    const running = (id: string) => byId.get(id)!.state === "running";
    for (const g of lay.groups) {
      const r = routeGroup(g, rect, tone, running);
      lines.push(...r.lines);
      heads.push(...r.heads);
    }
    return { lines, heads };
  }, [lay, rect, byId, run]);

  // entrance: the boxes one by one in frontier order, each gap's lines once the boxes under it are in
  const still = useMemo(reducedMotion, []);
  const step = Math.min(STAGGER, MAX_ENTRANCE / Math.max(1, lay.boxes.length));
  const [played, setPlayed] = useState(false);
  useEffect(() => {
    setPlayed(false);
    const h = setTimeout(() => setPlayed(true), MAX_ENTRANCE + 400);
    return () => clearTimeout(h);
  }, [run.id, mode]);
  const animate = !still && !played;
  const delayOf = (id: string) => Math.round((lay.at.get(id)?.index ?? 0) * step);
  const after = (ids: string[]) => Math.max(0, ...ids.map(delayOf)) + 160;

  // ---- full view: pan / zoom / drag
  const box = useRef<HTMLDivElement>(null);
  const openRef = useRef(open);
  openRef.current = open;
  const [view, setView] = useState({ x: 0, y: 0, k: 1 });
  /** `whole`: the whole run in view (the Fit button). Otherwise the drawing at its own size from its first
   *  frontier, as text starts at the top; only a run wider than the box is scaled down. */
  const fit = useCallback(
    (reserve = 0, whole = false) => {
      const el = box.current;
      if (!el || !lay.boxes.length) return;
      const rs = lay.boxes.map((b) => rect(b.id));
      const minX = Math.min(...rs.map((r) => r.x)) - MARGIN;
      const minY = Math.min(...rs.map((r) => r.y)) - MARGIN;
      const maxX = Math.max(...rs.map((r) => r.x + r.w)) + MARGIN;
      const maxY = Math.max(...rs.map((r) => r.y + r.h)) + MARGIN;
      let W = el.clientWidth - reserve;
      if (reserve) {
        // the drawer only needs room when the run, at the whole width, would reach under it
        const k0 = Math.min(MAX_FIT, el.clientWidth / (maxX - minX));
        if ((el.clientWidth + (maxX - minX) * k0) / 2 <= el.clientWidth - reserve) W = el.clientWidth;
      }
      const want = Math.min(W / (maxX - minX), whole ? el.clientHeight / (maxY - minY) : Infinity);
      const k = Math.min(MAX_FIT, Math.max(MIN_FIT, want));
      const sel = openRef.current && lay.at.has(openRef.current) ? rect(openRef.current) : null;
      if (want >= MIN_FIT || !sel) return setView({ k, x: (W - (maxX - minX) * k) / 2 - minX * k, y: -minY * k });
      // too wide to show whole next to the drawer: keep the open box in view
      setView({ k, x: W / 2 - (sel.x + sel.w / 2) * k, y: Math.min(-minY * k, el.clientHeight / 2 - (sel.y + sel.h / 2) * k) });
    },
    [lay, rect],
  );
  const fitRef = useRef(fit);
  fitRef.current = fit;
  // fit when the run opens and when its drawing changes size (a node was added, the window was resized): a refresh
  // of a live run that moves nothing keeps the view where the person left it
  const shape = `${run.id}|${lay.boxes.length}|${Math.round(lay.w)}|${Math.round(lay.h)}`;
  useLayoutEffect(() => {
    if (mode === "full") fitRef.current(openRef.current ? DRAWER_W : 0);
  }, [shape, mode]);
  // the box grows while the side panel steps aside: refit on resize
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
  // the drawer sits on the right: a box opened under it slides into view; the person's pan and zoom stay otherwise
  const drawerOpen = mode === "full" && !!open;
  useEffect(() => {
    const el = box.current;
    if (mode !== "full" || !el || !open || !lay.at.has(open)) return;
    const r = rect(open);
    setView((v) => {
      const over = (r.x + r.w) * v.k + v.x - (el.clientWidth - DRAWER_W);
      return over > 0 ? { ...v, x: v.x - over - 16 } : v;
    });
    // only when another node is opened
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, mode]);

  const zoomAt = (cx: number, cy: number, f: number) =>
    setView((v) => {
      const k = Math.min(2.5, Math.max(0.25, v.k * f));
      const r = k / v.k;
      return { k, x: cx - (cx - v.x) * r, y: cy - (cy - v.y) * r };
    });
  // ⌘+ / ⌘− / ⌘0
  useEffect(() => {
    if (mode !== "full") return;
    const onKey = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey) || e.altKey) return;
      const el = box.current;
      if (!el) return;
      if (e.key === "=" || e.key === "+") zoomAt(el.clientWidth / 2, el.clientHeight / 2, 1.15);
      else if (e.key === "-") zoomAt(el.clientWidth / 2, el.clientHeight / 2, 1 / 1.15);
      else if (e.key === "0") fitRef.current(openRef.current ? DRAWER_W : 0, true);
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [mode]);
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
    const o = id ? rect(id) : view;
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
    if (d.id && d.moved)
      setOver((p) => {
        savePos(run.id, p);
        return p;
      });
    else if (d.id) onOpen(d.id === open ? null : d.id);
    else if (!d.moved && (e.target as HTMLElement).classList.contains("bv-full")) onOpen(null);
  };
  const reset = () => {
    savePos(run.id, {});
    setOver({});
    requestAnimationFrame(() => fitRef.current(openRef.current ? DRAWER_W : 0));
  };

  // hovering a box lights its own lines and steps the rest back
  const [hover, setHover] = useState<string | null>(null);
  const lit = (from: string[], to: string[] | string) => !!hover && (from.includes(hover) || (Array.isArray(to) ? to.includes(hover) : to === hover));
  const near = useMemo(() => {
    const s = new Set<string>();
    if (hover) for (const e of lay.shape.edges) if (e.from === hover || e.to === hover) s.add(e.from).add(e.to);
    return s;
  }, [hover, lay]);

  const deps = lay.shape.edges;
  const shownDeps = allDeps || deps.length <= DEPS_CAP + 2 ? deps : deps.slice(0, DEPS_CAP);
  const live = lay.boxes.map((b) => byId.get(b.id)!).filter((n) => n.state === "running" && n.id !== open);
  const frontierRuns = (f: number) => lay.shape.rows[f]?.some((id) => byId.get(id)!.state === "running");

  const drawing = (
    <div className="bv-boxes" style={{ width: lay.w, height: lay.h }} data-testid="run-canvas">
      <svg className={`bv-edges${hover ? " focus" : ""}`} width={lay.w} height={lay.h} aria-hidden overflow="visible">
        {edges.lines.map((l) => (
          <path
            key={l.key}
            className={`bv-line t-${l.tone ?? "mixed"}${l.flow ? " flow" : ""}${lit(l.from, l.to) ? " lit" : ""}${animate ? " enter" : ""}`}
            style={animate ? ({ animationDelay: `${after([...l.from, ...l.to])}ms` } as CSSProperties) : undefined}
            d={l.d}
            data-testid="run-edge"
            data-from={l.from.join(" ")}
            data-to={l.to.join(" ")}
          />
        ))}
        {edges.heads.map((h) => (
          <path
            key={h.key}
            className={`bv-head t-${h.tone ?? "mixed"}${h.flow ? " flow" : ""}${lit(h.from, h.to) ? " lit" : ""}${animate ? " enter" : ""}`}
            style={animate ? ({ animationDelay: `${after([...h.from, h.to])}ms` } as CSSProperties) : undefined}
            d={h.up ? `M${h.x},${h.y} l-4,${GEOMETRY.arrow} h8 Z` : `M${h.x},${h.y} l-4,-${GEOMETRY.arrow} h8 Z`}
            data-testid="run-arrow"
            data-to={h.to}
            data-tip={`${h.x},${h.y}`}
          />
        ))}
        {lay.undrawn.map((u) => (
          <g
            key={u.gap}
            className={`bv-undrawn${frontierRuns(u.gap + 1) ? " flow" : ""}${animate ? " enter" : ""}`}
            style={animate ? ({ animationDelay: `${after(lay.shape.rows[u.gap + 1] ?? [])}ms` } as CSSProperties) : undefined}
            data-testid="run-undrawn"
            data-gap={u.gap}
          >
            <path className="bv-dash" d={`M${u.x},${u.y1} V${u.y2 - GEOMETRY.arrow - 3}`} />
            <path className="bv-hollow" d={`M${u.x},${u.y2 - 1} l-4,-${GEOMETRY.arrow} h8 Z`} />
          </g>
        ))}
      </svg>
      {lay.labels.map((l) => (
        <span key={l.frontier} className="bv-frontier" style={{ left: l.x, top: l.y }} data-testid="run-frontier">
          · {t("graph.frontier")}
        </span>
      ))}
      {lay.more.map((m) => (
        <button
          key={m.frontier}
          type="button"
          className="bv-more"
          style={{ left: m.x, top: m.y }}
          data-testid="run-more"
          onPointerDown={(e) => e.stopPropagation()}
          onClick={() => setOpened((o) => (o.has(m.frontier) ? new Set([...o].filter((f) => f !== m.frontier)) : new Set([...o, m.frontier])))}
        >
          {m.hidden > 0 ? `${t("graph.more", { n: m.hidden })} · ${t("graph.all", { n: m.total })}` : t("graph.fewer")}
        </button>
      ))}
      {lay.boxes.map((b) => {
        const n = byId.get(b.id)!;
        const r = rect(b.id);
        const tx = boxText(n, run, lay.shape, lay.inner, nowS);
        const dim = !!hover && hover !== n.id && !near.has(n.id);
        return (
          <button
            key={n.id}
            type="button"
            className={`bx s-${tx.tone}${n.id === open ? " on" : ""}${dim ? " dim" : ""}${animate ? " enter" : ""}`}
            style={{ left: r.x, top: r.y, width: r.w, height: r.h, ...(animate ? { animationDelay: `${delayOf(n.id)}ms` } : {}) }}
            data-testid="run-node"
            data-node={n.id}
            data-frontier={b.frontier}
            data-state={n.state}
            data-tone={tx.tone}
            data-appear={b.index}
            aria-pressed={n.id === open}
            aria-label={`${titleOf(n)}, ${tx.status}`}
            title={titleOf(n)}
            onPointerDown={(e) => {
              e.stopPropagation();
              onDown(e, n.id);
            }}
            onClick={(e) => {
              if (mode === "panel" || e.detail === 0) onOpen(n.id === open ? null : n.id);
            }}
            onMouseEnter={() => setHover(n.id)}
            onMouseLeave={() => setHover(null)}
          >
            <span className="bx-l bx-head">
              <Mark node={n} bot={bot} />
              <span className="bx-t" data-testid="node-title">
                {tx.origin}
                {tx.title}
              </span>
            </span>
            <span className="bx-l" data-testid="node-facts">
              <span className="bx-cat">{tx.cat}</span>
              <span className="bx-dim">{tx.model}</span>
            </span>
            <span className="bx-l bx-status" data-testid="node-status">
              <span className="bx-g">{tx.glyph}</span> {tx.status}
              {tx.after && <span className="bx-dim">{tx.after}</span>}
            </span>
            <span className="bx-l bx-dim" data-testid="node-parents">
              {tx.parents}
            </span>
          </button>
        );
      })}
    </div>
  );

  const sections = (
    <div className="bv-secs" onPointerDown={(e) => e.stopPropagation()}>
      {deps.length > 0 && (
        <section className="bv-sec" data-testid="run-deps" aria-label={t("graph.deps")}>
          <h4>{t("graph.deps")}</h4>
          {shownDeps.map((e) => (
            <div key={`${e.from}>${e.to}`} className="bv-dep" data-testid="run-dep" title={`${titleOf(byId.get(e.from)!)} → ${titleOf(byId.get(e.to)!)}`}>
              {titleOf(byId.get(e.from)!)} <span className="bv-arrow">→</span> {titleOf(byId.get(e.to)!)}
              {e.kind === "repair" && <span className="bx-dim"> ({t("graph.repair")})</span>}
            </div>
          ))}
          {deps.length > DEPS_CAP + 2 && (
            <button type="button" className="bv-more inline" onClick={() => setAllDeps((v) => !v)} data-testid="run-deps-more">
              {allDeps ? t("graph.fewer") : `${t("graph.more", { n: deps.length - DEPS_CAP })} · ${t("graph.all", { n: deps.length })}`}
            </button>
          )}
        </section>
      )}
      {(detail || live.length > 0) && (
        <section className="bv-sec" data-testid="run-details" aria-label={t("graph.details")}>
          <h4>{t("graph.details")}</h4>
          {detail}
          {live.map((n) => {
            const st = statusOf(n, run);
            const facts = factsOf(n);
            const time = st.timed ? durationOf(n, nowS) : "";
            const where = [t("graph.layer", { n: (lay.shape.layer.get(n.id) ?? 0) + 1 }), n.attempts.length > 1 ? t("graph.attempt", { n: n.attempts.length }) : "", n.lane ?? ""].filter(Boolean);
            return (
              <button key={n.id} type="button" className={`bv-card s-${st.tone}`} data-testid="run-detail" data-node={n.id} onClick={() => onOpen(n.id)}>
                <span className="bv-card-t">
                  <span className="bx-g">{st.glyph}</span> {titleOf(n)}
                </span>
                {(facts.cat || facts.model) && (
                  <span className="bv-card-l">
                    <span className="bx-cat">{facts.cat}</span>
                    <span className="bx-dim">{facts.cat && facts.model ? " · " : ""}{facts.model}</span>
                  </span>
                )}
                <span className="bv-card-l">
                  <span className="bv-word">{time ? `${st.word} ${time}` : st.word}</span>
                  <span className="bx-dim"> · {where.join(" · ")}</span>
                </span>
              </button>
            );
          })}
        </section>
      )}
    </div>
  );

  const vars = { "--bv-font": `${type.font}px`, "--bv-line": `${type.line}px`, "--bv-cw": `${cw}px` } as CSSProperties;
  const data = {
    "data-testid": "run-graph",
    "data-frontiers": lay.shape.rows.length,
    "data-per-row": lay.perRow,
    "data-inner": lay.inner,
    "data-drawn": lay.groups.length,
    "data-undrawn": lay.undrawn.length,
  };
  if (mode === "panel")
    return (
      <div className={`bv bv-panel${still ? " still" : ""}`} style={vars} {...data}>
        {drawing}
        {sections}
      </div>
    );
  return (
    <div
      ref={box}
      className={`bv bv-full${still ? " still" : ""}`}
      style={vars}
      {...data}
      data-zoom={view.k.toFixed(2)}
      onPointerDown={(e) => onDown(e, null)}
      onPointerMove={onMove}
      onPointerUp={onUp}
      onPointerCancel={() => (drag.current = null)}
      onScroll={(e) => {
        // focusing a box scrolls an overflow:hidden box; panning is ours, so undo it
        e.currentTarget.scrollLeft = 0;
        e.currentTarget.scrollTop = 0;
      }}
    >
      <div className="bv-canvas" style={{ width: lay.w, transform: `translate(${view.x}px, ${view.y}px) scale(${view.k})` }}>
        {drawing}
        {sections}
      </div>
      <div className="bv-tools" onPointerDown={(e) => e.stopPropagation()}>
        <button type="button" onClick={() => zoomAt((box.current?.clientWidth ?? 0) / 2, (box.current?.clientHeight ?? 0) / 2, 1 / 1.2)} aria-label={t("graph.zoomOut")} title={`${t("graph.zoomOut")} (⌘−)`}>
          −
        </button>
        <span className="bv-zoom" data-testid="run-zoom">
          {Math.round(view.k * 100)}%
        </span>
        <button type="button" onClick={() => zoomAt((box.current?.clientWidth ?? 0) / 2, (box.current?.clientHeight ?? 0) / 2, 1.2)} aria-label={t("graph.zoomIn")} title={`${t("graph.zoomIn")} (⌘+)`}>
          +
        </button>
        <button type="button" onClick={() => fit(drawerOpen ? DRAWER_W : 0, true)} data-testid="run-fit" title="⌘0">
          {t("graph.fit")}
        </button>
        <button type="button" onClick={reset} disabled={!moved} data-testid="run-reset">
          {t("graph.reset")}
        </button>
      </div>
    </div>
  );
}
