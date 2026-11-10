// A run drawn as a graph: one frontier to a row, equal boxes of text joined by lines (boxView.ts holds the layout,
// the structure of the OMH TUI's box view). A box is the title, the mark of the model that ran the node with
// "Opus 5.5 · high · visual-engineering", and a status icon with a word; it is a thin outline on the page with one
// 2px state line on its left edge: no fill, no gradient, no glow, and no shadow at rest. Every edge is a line with
// rounded turns and a small arrowhead. Under the boxes, "Dependencies" and "Node details" are plain text. The font
// is the app's own. Two sizes: "panel" flows in the side panel at its width (boxes shrink to put a frontier on one
// row; a very long one wraps, shows its first rows and "Show all"); "full" is the same drawing over the chat
// column, where you can drag a box (its position only, kept per run), pan, zoom and Fit. The only motion is the
// boxes appearing one by one, a slow dash riding the edges into a running node, and a box answering the pointer.
// Nothing here changes a run.
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties, type PointerEvent as RPE, type ReactNode } from "react";
import type { AgentRun } from "../lib/runs";
import { t } from "../i18n";
import { AgentIcon, ModelIcon } from "../ui";
import { boxText, durationOf, estimate, factsOf, GEOMETRY, layoutBoxes, movedLines, statusOf, titleOf, titleParts, type BoxLayout, type Mark, type Measure, type Rect, type StatusIcon } from "./boxView";
import { reducedMotion } from "./format";

export type GraphMode = "panel" | "full";
export interface BotModel {
  model: string;
  provider: string;
}

/** The drawing's type, in the app's own font: a title in 13px medium, every other line in 12px, on 18px lines.
 *  runs.css sets the same two on `.bx-title` and `.bv`. */
export const FONT = { title: "500 13px var(--font)", text: "400 12px var(--font)" };
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
/** Full view: a frontier up to a quarter too long for the window stays on one row, and the view shows the drawing
 *  that much smaller (never under four fifths of its size for this). */
const FULL_STRETCH = 1.25;

const widths = new Map<string, number>();
let probe: HTMLSpanElement | null = null;
/** A text's width in the drawing's font, measured where it is drawn (estimated without a DOM). */
export const measureText: Measure = (text, font) => {
  if (typeof document === "undefined") return estimate(text, font);
  const key = `${font}\n${text}`;
  let w = widths.get(key);
  if (w === undefined) {
    if (!probe?.isConnected) {
      probe = document.createElement("span");
      probe.setAttribute("aria-hidden", "true");
      document.body.appendChild(probe);
    }
    probe.style.cssText = `position:fixed;left:-9999px;top:0;visibility:hidden;white-space:pre;font:${FONT[font]}`;
    probe.textContent = text;
    w = probe.getBoundingClientRect().width;
    if (widths.size > 5000) widths.clear();
    widths.set(key, w);
  }
  return w;
};

const ICONS: Record<StatusIcon | "repair", ReactNode> = {
  check: <path d="M20 6 9 17l-5-5" />,
  x: <path d="M18 6 6 18M6 6l12 12" />,
  dot: <circle cx="12" cy="12" r="5.5" fill="currentColor" stroke="none" />,
  ring: <circle cx="12" cy="12" r="7.5" />,
  dashed: <circle cx="12" cy="12" r="7.5" strokeDasharray="2.9 3" />,
  alert: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7.5v5M12 16.4h.01" />
    </>
  ),
  pause: <path d="M9 6v12M15 6v12" />,
  retry: <path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8M21 3v5h-5" />,
  off: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="m5.7 5.7 12.6 12.6" />
    </>
  ),
  repair: <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" />,
};
/** A node's status as a 12px line icon (a check, a dot, a ring…), in the state's colour. The word beside it says
 *  the same, so the icon itself is hidden from a screen reader unless it carries a label of its own. */
export function StatusGlyph({ icon, label }: { icon: StatusIcon | "repair"; label?: string }) {
  return (
    <svg className="bx-ic" data-icon={icon} viewBox="0 0 24 24" width={GEOMETRY.icon} height={GEOMETRY.icon} fill="none" stroke="currentColor" strokeWidth={icon === "repair" ? 2 : 2.6} strokeLinecap="round" strokeLinejoin="round" role={label ? "img" : undefined} aria-label={label} aria-hidden={label ? undefined : true}>
      {ICONS[icon]}
    </svg>
  );
}

/** A title that may also break where `titleParts` says (after a "/" or a "_" inside a long word), before the box
 *  falls back to breaking anywhere. */
const breakable = (title: string): ReactNode[] => titleParts(title).flatMap((part, i) => (i ? [<wbr key={i} />, part] : [part]));

/** The one mark before a node's model: the model maker's (Claude, OpenAI, Gemini…), or the agent CLI's when the
 *  lane went to one and no model is known. A node of which neither is known has none. */
export function NodeMark({ mark }: { mark: Mark | null }) {
  if (!mark) return null;
  return (
    <span className="bx-mk" data-testid="node-mark" data-mark={mark.id} data-kind={mark.kind}>
      {mark.kind === "model" ? <ModelIcon model={mark.model} provider={mark.provider} size={GEOMETRY.mark} /> : <AgentIcon id={mark.id} size={GEOMETRY.mark} />}
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
        width: Math.max(width, 200) - (mode === "full" ? 2 * MARGIN : 0),
        measure: measureText,
        capRows: mode === "panel" ? PANEL_CAP_ROWS : undefined,
        opened,
        bot,
        stretch: mode === "full" ? FULL_STRETCH : 1,
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [run, width, mode, opened, bot?.model, bot?.provider],
  );
  const byId = useMemo(() => new Map(run.nodes.map((n) => [n.id, n])), [run.nodes]);

  // full view: dragged positions override the layout's, per run
  const [over, setOver] = useState<Pos>(() => (mode === "full" ? loadPos(run.id) : {}));
  useEffect(() => setOver(mode === "full" ? loadPos(run.id) : {}), [run.id, mode]);
  const rect = useCallback(
    (id: string): Rect => {
      const b = lay.at.get(id)!;
      const p = over[id] ?? b;
      return { x: p.x, y: p.y, w: b.w, h: b.h };
    },
    [over, lay],
  );
  const moved = Object.keys(over).some((id) => lay.at.has(id));

  // the lines: as the layout ran them; an edge of a box the person moved is one elbow between the two boxes as
  // they stand now
  const edges = useMemo(
    () =>
      movedLines(
        lay,
        rect,
        new Set(Object.keys(over).filter((id) => lay.at.has(id))),
        (id) => statusOf(byId.get(id)!, run).tone,
        (id) => byId.get(id)!.state === "running",
      ),
    [lay, rect, over, byId, run],
  );

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
  // the box under the pointer while it is dragged: it lifts
  const [lifted, setLifted] = useState<string | null>(null);

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
    if (!d.moved && d.id) setLifted(d.id);
    d.moved = true;
    if (d.id) {
      const id = d.id;
      setOver((p) => ({ ...p, [id]: { x: Math.round(d.ox + dx / view.k), y: Math.round(d.oy + dy / view.k) } }));
    } else setView((v) => ({ ...v, x: d.ox + dx, y: d.oy + dy }));
  };
  const onUp = (e: RPE) => {
    const d = drag.current;
    drag.current = null;
    setLifted(null);
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
  const lit = (from: string[], to: string) => !!hover && (to === hover || from.includes(hover));
  const near = useMemo(() => {
    const s = new Set<string>();
    if (hover) for (const e of lay.shape.edges) if (e.from === hover || e.to === hover) s.add(e.from).add(e.to);
    return s;
  }, [hover, lay]);

  const deps = lay.shape.edges;
  const shownDeps = allDeps || deps.length <= DEPS_CAP + 2 ? deps : deps.slice(0, DEPS_CAP);
  const live = lay.boxes.map((b) => byId.get(b.id)!).filter((n) => n.state === "running" && n.id !== open);

  const texts = new Map(lay.boxes.map((b) => [b.id, boxText(byId.get(b.id)!, run, lay, lay.inner, nowS, measureText, bot)]));
  // the edges of a net lie on each other where they share a stretch: the lit ones are drawn last, on top
  const lines = hover ? [...edges.lines].sort((a, b) => Number(lit([a.from], a.to)) - Number(lit([b.from], b.to))) : edges.lines;
  const { arrow, arrowW } = GEOMETRY;

  const drawing = (
    <div className="bv-boxes" style={{ width: lay.w, height: lay.h }} data-testid="run-canvas">
      <svg className={`bv-edges${hover ? " focus" : ""}`} width={lay.w} height={lay.h} aria-hidden overflow="visible">
        {lines.map((l) => (
          <path
            key={l.key}
            className={`bv-line${lit([l.from], l.to) ? " lit" : ""}${animate ? " enter" : ""}`}
            style={animate ? ({ animationDelay: `${after([l.from, l.to])}ms` } as CSSProperties) : undefined}
            d={l.d}
            data-testid="run-edge"
            data-net={l.net}
            data-from={l.from}
            data-to={l.to}
            data-tone={l.tone}
          />
        ))}
        {/* the one motion on a line: a slow dash that rides each edge into a running node, once the lines have
            appeared */}
        {(animate ? [] : edges.flows).map((f) => (
          <path key={f.key} className={`bv-flow${hover && !lit([f.from], f.to) ? " back" : ""}`} d={f.d} data-testid="run-flow" data-from={f.from} data-to={f.to} />
        ))}
        {edges.heads.map((h) => (
          <path
            key={h.key}
            className={`bv-head${lit(h.from, h.to) ? " lit" : ""}${animate ? " enter" : ""}`}
            style={animate ? ({ animationDelay: `${after([...h.from, h.to])}ms` } as CSSProperties) : undefined}
            d={`M${h.x},${h.y} l${-arrowW / 2},${-arrow} h${arrowW} Z`}
            data-testid="run-arrow"
            data-to={h.to}
            data-from={h.from.join(" ")}
            data-tip={`${h.x},${h.y}`}
          />
        ))}
      </svg>
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
        const tx = texts.get(b.id)!;
        const dim = !!hover && hover !== n.id && !near.has(n.id);
        const status = [tx.time ? `${tx.word} ${tx.time}` : tx.word, ...tx.extras].join(" · ");
        return (
          <button
            key={n.id}
            type="button"
            className={`bx s-${tx.tone}${n.id === open ? " on" : ""}${dim ? " dim" : ""}${lifted === n.id ? " lift" : ""}${animate ? " enter" : ""}`}
            style={{ left: r.x, top: r.y, width: r.w, height: r.h, ...(animate ? { animationDelay: `${delayOf(n.id)}ms` } : {}) }}
            data-testid="run-node"
            data-node={n.id}
            data-frontier={b.frontier}
            data-row={b.row}
            data-state={n.state}
            data-tone={tx.tone}
            data-appear={b.index}
            aria-pressed={n.id === open}
            aria-label={[tx.title, tx.factsText, status].filter(Boolean).join(", ")}
            title={tx.title}
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
            <span className="bx-title" data-testid="node-title" data-lines={tx.titleLines} style={{ WebkitLineClamp: tx.titleLines, height: tx.titleLines * GEOMETRY.line }}>
              {tx.repair && <StatusGlyph icon="repair" label={t("graph.repairNode")} />}
              {breakable(tx.title)}
            </span>
            {tx.facts.length > 0 && (
              <span className="bx-facts" data-testid="node-facts" title={tx.factsText}>
                {tx.facts.map((line, i) => (
                  <span key={i} className="bx-l bx-fl" style={i > 0 && lay.hang && tx.mark ? { paddingLeft: GEOMETRY.mark + GEOMETRY.markGap } : undefined}>
                    {i === 0 && <NodeMark mark={tx.mark} />}
                    {line && <span className="bx-ft">{line}</span>}
                    {i === tx.facts.length - 1 && tx.via && (
                      <span className="bx-via" data-testid="node-via">
                        {line ? ` · ${tx.via}` : tx.via}
                      </span>
                    )}
                  </span>
                ))}
              </span>
            )}
            <span className="bx-l bx-status" data-testid="node-status">
              <StatusGlyph icon={tx.icon} />
              <span className="bx-w">{tx.word}</span>
              {tx.time && <span className="bx-t"> {tx.time}</span>}
              {tx.extras.map((x) => (
                <span key={x} className="bx-t">
                  {" · "}
                  {x}
                </span>
              ))}
            </span>
          </button>
        );
      })}
    </div>
  );

  // in the full view the text under the drawing starts at the drawing's own left edge (its leftmost box), not the
  // canvas's: the two read as one
  const sections = (
    <div className="bv-secs" style={mode === "full" && lay.boxes.length ? { marginLeft: Math.min(...lay.boxes.map((b) => b.x)) } : undefined} onPointerDown={(e) => e.stopPropagation()}>
      {deps.length > 0 && (
        <section className="bv-sec" data-testid="run-deps" aria-label={t("graph.deps")}>
          <h4>{t("graph.deps")}</h4>
          {shownDeps.map((e) => (
            <div key={`${e.from}>${e.to}`} className="bv-dep" data-testid="run-dep" data-from={e.from} data-to={e.to} title={`${titleOf(byId.get(e.from)!)} → ${titleOf(byId.get(e.to)!)}`}>
              <span className="bv-dep-n">{titleOf(byId.get(e.from)!)}</span>
              <svg className="bv-arrow" viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" role="img" aria-label="→">
                <path d="M5 12h14M13 6l6 6-6 6" />
              </svg>
              <span className="bv-dep-n">{titleOf(byId.get(e.to)!)}</span>
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
            const facts = factsOf(n, run, bot);
            const time = st.timed ? durationOf(n, nowS) : "";
            const where = [t("graph.layer", { n: (lay.shape.layer.get(n.id) ?? 0) + 1 }), n.attempts.length > 1 ? t("graph.attempt", { n: n.attempts.length }) : "", n.lane ?? ""].filter(Boolean);
            return (
              <button key={n.id} type="button" className={`bv-card s-${st.tone}`} data-testid="run-detail" data-node={n.id} onClick={() => onOpen(n.id)}>
                <span className="bv-card-t">
                  <StatusGlyph icon={st.icon} />
                  <span className="bv-card-n">{titleOf(n)}</span>
                </span>
                {facts.text && (
                  <span className="bv-card-l bx-fl">
                    <NodeMark mark={facts.mark} />
                    <span className="bx-ft">{facts.text}</span>
                  </span>
                )}
                <span className="bv-card-l">
                  <span>{time ? `${st.word} ${time}` : st.word}</span>
                  <span className="bx-dim"> · {where.join(" · ")}</span>
                </span>
              </button>
            );
          })}
        </section>
      )}
    </div>
  );

  const vars = { "--bv-line": `${GEOMETRY.line}px` } as CSSProperties;
  const data = {
    "data-testid": "run-graph",
    "data-frontiers": lay.shape.rows.length,
    "data-per-row": lay.perRow,
    "data-box": lay.boxW,
    "data-gap": lay.gap,
    "data-nets": lay.nets.length,
    // every edge between two boxes on screen has a line: these two are equal
    "data-edges": lay.shape.edges.filter((e) => lay.at.has(e.from) && lay.at.has(e.to)).length,
    "data-drawn": lay.drawn.size,
    "data-crowded": lay.crowded,
    "data-tight": lay.tight.length,
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
      onPointerCancel={() => {
        // a drag the system took over ends where the box stands: what is on screen is what is kept
        const d = drag.current;
        drag.current = null;
        setLifted(null);
        if (d?.id && d.moved)
          setOver((p) => {
            savePos(run.id, p);
            return p;
          });
      }}
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
