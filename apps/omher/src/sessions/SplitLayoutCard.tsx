// A TERMINALS split drawn as one card in the sidebar (owner's option A, the layout card): one cell per pane at the
// pane's real place and proportions, each with its CLI mark, title and last line, laid out for the cell's own size
// (splitCard.ts cellText). A cell's edge says its state: an accent segment orbits it while output flows, a dashed edge
// flows while it reports background work, an attention edge blinks while it waits on the person (held on the focused
// cell), a danger edge after an error. The motion is CSS keyframes on SVG strokes sized from a ResizeObserver: no
// per-frame script, and under reduced motion nothing moves. A grip under the card sets its height, kept with the
// split (splitState mapH). Ideas from kasaterm's sidebar map (2rami/kasaterm, MIT); written fresh.
//
// Each cell subscribes to its own session's activity (useTermFace, as a TERMINALS row does), so one terminal's output
// re-renders its cell only, never the card, the other cells or the list.
import { memo, useEffect, useLayoutEffect, useReducer, useRef, useState, type ComponentType, type KeyboardEvent, type PointerEvent as ReactPointerEvent } from "react";
import { t } from "../i18n";
import { termActivity, termFallbackName, termMarkAgent, termStatus, splitPaneName, type AgentInfo, type SessionRec, type Unseen } from "./agents";
import { TermRowMark } from "./TermRowMark";
import { focusSplitPane, splitWith } from "./SplitView";
import { pressToSplit } from "./splitDrag";
import { groupSessions, setMapHeight, type SplitGroup } from "./splitState";
import { cellBoxes, cellState, cellText, clampCardHeight, defaultCardHeight, elapsedLabel, GRIP_STEP, type CellState } from "./splitCard";
import { usePendingRequests } from "./termShare";
import { countRender, useTermFace } from "./termActivity";
import { pickTitle } from "./titles";
import { getSessions } from "./sessions";
import type { RowAction } from "./SessionsSection";
import "./splitCard.css";

/** The TERMINALS row menu's parts, handed in by the list so a cell offers exactly what a row does. */
export interface RowMenuKit {
  items: (rec: SessionRec) => RowAction[];
  act: (rec: SessionRec, a: RowAction, rename: () => void, close: (rec: SessionRec) => void) => void;
  spot: (e: { clientX: number; clientY: number }, from: Element | null, rows: number) => { x: number; y: number };
  Menu: ComponentType<{ at: { x: number; y: number }; name: string; actions: RowAction[]; onPick: (a: RowAction) => void; onDismiss: () => void }>;
  Name: ComponentType<{ initial: string; auto: boolean; onDone: (title: string | null | undefined) => void }>;
}

/** The orbit's three strokes, head aligned: [length % of the edge, width px, opacity]. Drawn 1.25 px in, so the 2.5 px
 *  head stays inside the cell's clip. */
const ORBIT: readonly [number, number, number][] = [
  [20, 1.1, 0.35],
  [12, 1.7, 0.65],
  [5, 2.5, 1],
];

/** A rounded rect `inset` px inside a w×h cell, as SVG attributes. */
const inRect = (w: number, h: number, inset: number, r = 6) => ({ x: inset, y: inset, width: Math.max(0, w - 2 * inset), height: Math.max(0, h - 2 * inset), rx: Math.max(0, r - inset) });

/** One pane's cell. Memoised on primitives: a card re-render (a drag of the grip, another cell's state) passes the same
 *  values and skips it. */
const SplitCell = memo(function SplitCell({ rec, x, y, w, h, focused, agents, unseen, ticking, onClose, kit }: { rec: SessionRec; x: number; y: number; w: number; h: number; focused: boolean; agents: AgentInfo[] | null; unseen?: Unseen; ticking: boolean; lang: string; onClose: (rec: SessionRec) => void; kit: RowMenuKit }) {
  countRender(`cell:${rec.id}`);
  const [editing, setEditing] = useState(false);
  const [menu, setMenu] = useState<{ x: number; y: number } | null>(null);
  const wrap = useRef<HTMLDivElement>(null);
  const { act, now } = useTermFace(rec.id, rec.startedAt, ticking);
  const asked = usePendingRequests().some((r) => r.sessionId === rec.id);
  const status = asked ? "bell" : termStatus({ status: rec.status, exitCode: rec.exitCode, lastOut: act.progress ? now : act.lastOut }, unseen, now);
  const state: CellState = cellState({ status, asked, background: rec.background });
  const el = state === "work" ? elapsedLabel(act.busySince, true, now) : null;
  // the corner time steps each minute of the streak while output keeps the rest of the face unchanged
  const [, tick] = useReducer((n: number) => n + 1, 0);
  useEffect(() => {
    if (state !== "work" || act.busySince === undefined) return;
    const ms = now - act.busySince;
    const step = ms < 3_600_000 ? 60_000 : 3_600_000;
    const id = setTimeout(tick, Math.max(0, act.busySince + (Math.floor(ms / step) + 1) * step - now) + 5);
    return () => clearTimeout(id);
  }, [state, act.busySince, now]);
  const title = pickTitle(rec, termFallbackName(rec, agents));
  const line = termActivity({ agent: rec.agent, fgAgent: rec.fgAgent, lastLine: act.lastLine, oscTitle: act.oscTitle }).line;
  const text = cellText(w, h);
  const name = splitPaneName(rec, agents);
  const actions = kit.items(rec);
  const endEdit = (v: string | null | undefined) => {
    setEditing(false);
    if (v !== undefined) getSessions().rename(rec.id, v);
    requestAnimationFrame(() => wrap.current?.querySelector<HTMLElement>(".sc-open")?.focus());
  };
  const markSize = text === "stack" ? 20 : text === "line" ? 12 : 13;
  const body = (
    <span className="sc-body">
      <span className="sc-t">
        <TermRowMark agent={termMarkAgent(rec)} size={markSize} />
        {editing ? <kit.Name initial={title.title} auto={title.source !== "person"} onDone={endEdit} /> : <span className="sc-n" data-testid="split-cell-name">{title.title}</span>}
      </span>
      {text !== "line" && line && <span className="sc-l">{line}</span>}
    </span>
  );
  return (
    <div
      ref={wrap}
      className="sc-cell"
      style={{ left: x, top: y, width: w, height: h }}
      data-testid="split-cell"
      data-session={rec.id}
      data-state={state}
      data-focused={focused ? "true" : "false"}
      data-text={text}
      onPointerDown={(e) => {
        // a cell dragged onto the open terminal moves that pane there, as its row did (a press that stays put clicks)
        if (editing || (e.target as Element).closest("[role=menu], [role=separator]")) return;
        pressToSplit(e, rec.id, (d) => splitWith(d.at, rec.id, d.side));
      }}
      onContextMenu={(e) => {
        if (editing) return;
        e.preventDefault();
        setMenu(kit.spot(e, wrap.current, actions.length));
      }}
    >
      <svg className="sc-svg" width={w} height={h} aria-hidden="true">
        <rect className="sc-edge" {...inRect(w, h, focused ? 0.75 : 0.6)} />
        {state === "work" &&
          ORBIT.map(([len, sw, op]) => (
            <rect key={len} className={`sc-orbit sc-o${len}`} {...inRect(w, h, focused ? 3 : 1.25)} pathLength={100} strokeWidth={sw} opacity={op} strokeDasharray={`${len} ${100 - len}`} />
          ))}
        {state === "bg" && <rect className="sc-dash" {...inRect(w, h, 1)} />}
        {state === "wait" && <rect className="sc-wait" {...inRect(w, h, 0.75)} pathLength={100} />}
      </svg>
      {editing ? (
        <div className={`sc-open sc-editing ${text}`}>{body}</div>
      ) : (
        <button type="button" className={`sc-open ${text}`} aria-label={t("split.mapFocus", { name })} aria-current={focused ? "true" : undefined} title={line ? `${title.title}\n${line}` : title.title} onClick={() => focusSplitPane(rec.id)}>
          {body}
        </button>
      )}
      {el && (
        <span className="sc-el" data-testid="split-cell-elapsed" data-old={el.old ? "true" : undefined} title={t("split.busyFor", { time: el.text })}>
          {el.text}
        </span>
      )}
      {menu && <kit.Menu at={menu} name={title.title} actions={actions} onPick={(a) => kit.act(rec, a, () => setEditing(true), onClose)} onDismiss={() => setMenu(null)} />}
    </div>
  );
});

/** One TERMINALS split as a card: its cells in the split's shape, and the height grip under them. `current` is the
 *  session open in the main column (the focused cell); a split it is not in is drawn dimmer. */
export function SplitCard({ group, current, list, agents, unseen, ticking, lang, onClose, kit }: { group: SplitGroup; current: string | null; list: readonly SessionRec[]; agents: AgentInfo[] | null; unseen: Record<string, Unseen>; ticking: boolean; lang: string; onClose: (rec: SessionRec) => void; kit: RowMenuKit }) {
  const ids = groupSessions(group);
  const away = !current || !ids.includes(current);
  const map = useRef<HTMLDivElement>(null);
  const [mapW, setMapW] = useState(0);
  const [drag, setDrag] = useState<number | null>(null);
  const saved = group.mapH ?? defaultCardHeight(group.layout);
  const mapH = drag ?? saved;
  // the map's width from its own box: cells, their text layout and their edges are sized in px from it
  useLayoutEffect(() => {
    const el = map.current;
    if (!el) return;
    const read = () => setMapW(Math.round(el.getBoundingClientRect().width));
    read();
    const ro = typeof ResizeObserver === "function" ? new ResizeObserver(read) : null;
    ro?.observe(el);
    return () => ro?.disconnect();
  }, []);
  const set = (h: number | null) => setMapHeight(ids[0]!, h);
  const onGripDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    e.preventDefault();
    const grip = e.currentTarget;
    const y0 = e.clientY;
    const h0 = mapH;
    let last = h0;
    grip.setPointerCapture?.(e.pointerId);
    const move = (ev: PointerEvent) => {
      last = clampCardHeight(h0 + ev.clientY - y0);
      setDrag(last);
    };
    // a release, a lost capture or the window losing focus all end the drag where it is
    const end = () => {
      grip.removeEventListener("pointermove", move);
      grip.removeEventListener("pointerup", end);
      grip.removeEventListener("pointercancel", end);
      grip.removeEventListener("lostpointercapture", end);
      window.removeEventListener("blur", end);
      setDrag(null);
      if (last !== h0) set(last);
    };
    grip.addEventListener("pointermove", move);
    grip.addEventListener("pointerup", end);
    grip.addEventListener("pointercancel", end);
    grip.addEventListener("lostpointercapture", end);
    window.addEventListener("blur", end);
  };
  const onGripKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== "ArrowUp" && e.key !== "ArrowDown") return;
    e.preventDefault();
    set(clampCardHeight(mapH + (e.key === "ArrowUp" ? -GRIP_STEP : GRIP_STEP)));
  };
  const boxes = mapW > 0 ? cellBoxes(group.layout, mapW, mapH) : [];
  return (
    <div className="split-card" role="group" aria-label={t("split.card", { n: ids.length })} data-testid="split-card" data-panes={ids.length} data-away={away ? "true" : undefined}>
      <div ref={map} className="sc-map" style={{ height: mapH }}>
        {boxes.map((b) => {
          const rec = list.find((r) => r.id === b.id);
          // a pane whose session just went (the prune runs after this render) draws nothing
          if (!rec) return null;
          return <SplitCell key={b.id} rec={rec} x={b.x} y={b.y} w={b.w} h={b.h} focused={current === b.id} agents={agents} unseen={unseen[b.id]} ticking={ticking} lang={lang} onClose={onClose} kit={kit} />;
        })}
      </div>
      <div
        className={`sc-grip${drag !== null ? " on" : ""}`}
        role="separator"
        aria-orientation="horizontal"
        aria-valuenow={mapH}
        aria-label={t("split.cardGrip")}
        title={t("split.cardGrip")}
        tabIndex={0}
        data-testid="split-card-grip"
        onPointerDown={onGripDown}
        onDoubleClick={() => set(null)}
        onKeyDown={onGripKey}
      >
        <i />
      </div>
    </div>
  );
}
