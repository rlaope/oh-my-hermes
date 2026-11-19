// TERMINALS side by side: the open terminal session with a second one beside it. "Split right with…" (the TERMINALS
// background menu) and ⌘D in a TERMINALS terminal (Ctrl+Shift+D off macOS) open a picker of the other TERMINALS
// sessions; the divider between the two drags (each keeps at least 120 px) and a double click evens it; the x on
// either side's bar takes that side away and the other stays open alone. Each side is the session's own terminal
// (sessions.ts attach), so each keeps its own engine: both count as on the page while they show, and a side that
// leaves is parked like any hidden terminal.
import { useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore, type ReactNode, type PointerEvent, type KeyboardEvent } from "react";
import { useStore, getStore } from "../state/store";
import { CloseIcon } from "../ui";
import { t } from "../i18n";
import { getSessions, useSessions } from "./sessions";
import { folderName, isTerminalRec, termFallbackName, termMarkAgent, tildePath, type SessionRec } from "./agents";
import { pickTitle } from "./titles";
import { TermRowMark } from "./TermRowMark";
import { clampRatio, PANE_MIN_W } from "../terminal/layout";

interface SplitState {
  /** the session the split belongs to (the one open in the main column) */
  main: string | null;
  /** the session shown beside it */
  beside: string | null;
  /** the main side's share of the width */
  ratio: number;
  /** the picker is open for this session */
  picking: string | null;
}

let split: SplitState = { main: null, beside: null, ratio: 0.5, picking: null };
const listeners = new Set<() => void>();
function set(patch: Partial<SplitState>): void {
  split = { ...split, ...patch };
  for (const fn of listeners) fn();
}
const subscribe = (fn: () => void) => {
  listeners.add(fn);
  return () => void listeners.delete(fn);
};
export const getSplit = (): SplitState => split;
export const useSplit = (): SplitState => useSyncExternalStore(subscribe, getSplit, getSplit);

/** The other TERMINALS sessions that can show beside `main`: listed, running and not paused. */
export function splitChoices(list: SessionRec[], agents: Parameters<typeof isTerminalRec>[0], main: string): SessionRec[] {
  return list.filter((r) => r.id !== main && isTerminalRec(agents, r) && !r.paused && (r.status === "running" || r.status === "starting"));
}

/** Open the picker for the TERMINALS session open now (no-op elsewhere). */
export function openSplitPicker(main?: string): void {
  const ui = getStore().getState().ui;
  const id = main ?? (ui.view === "session" ? ui.session : null);
  if (id) set({ picking: id });
}
export const closeSplitPicker = (): void => set({ picking: null });

/** Show `beside` right of `main`. */
export function splitWith(main: string, beside: string): void {
  if (main === beside) return;
  set({ main, beside, picking: null, ratio: split.main === main ? split.ratio : 0.5 });
}

/** Take a side away: `keep` stays open alone. */
export function endSplit(keep: "main" | "beside" = "main"): void {
  const other = split.beside;
  set({ main: null, beside: null, picking: null });
  if (keep === "beside" && other) getStore().actions.openSession(other);
}

/** Tests: start from nothing. */
export function resetSplit(): void {
  split = { main: null, beside: null, ratio: 0.5, picking: null };
  for (const fn of listeners) fn();
}

function SideBar({ rec, onClose }: { rec: SessionRec; onClose: () => void }) {
  const ss = useSessions();
  const name = pickTitle(rec, termFallbackName(rec, ss.agents)).title;
  return (
    <div className="ss-split-bar" data-testid="split-bar" data-session={rec.id}>
      <TermRowMark agent={termMarkAgent(rec)} size={13} />
      <span className="ss-split-name" title={rec.cwd}>
        {name}
      </span>
      <span className="ss-split-path">{tildePath(rec.cwd, ss.home)}</span>
      <button type="button" className="ss-split-x" aria-label={t("split.closeSide", { name })} title={t("split.closeSide", { name })} onClick={onClose} data-testid="split-close">
        <CloseIcon />
      </button>
    </div>
  );
}

/** The terminal session `main` with the split's other session beside it, or `main` alone. `pane` draws one session's
 *  terminal. */
export function SplitView({ main, pane }: { main: SessionRec; pane: (rec: SessionRec) => ReactNode }) {
  const sp = useSplit();
  const ss = useSessions();
  const beside = sp.main === main.id && sp.beside ? (ss.list.find((r) => r.id === sp.beside) ?? null) : null;
  const on = !!beside && isTerminalRec(ss.agents, beside);
  // the side shown beside is on the page too: what its row carried (it rang, it finished) is seen
  const unseen = beside ? ss.unseen[beside.id] : undefined;
  useEffect(() => {
    if (on && beside && unseen && document.hasFocus()) getSessions().seen(beside.id);
  }, [on, beside, unseen]);
  // a side that went away (its shell ended and its row closed) leaves the other alone
  useEffect(() => {
    if (sp.main === main.id && sp.beside && !on) set({ main: null, beside: null });
  }, [sp.main, sp.beside, main.id, on]);
  const box = useRef<HTMLDivElement>(null);
  const [drag, setDrag] = useState(false);
  const ratio = (clientX: number) => {
    const r = box.current?.getBoundingClientRect();
    if (!r || !r.width) return split.ratio;
    return clampRatio((clientX - r.left) / r.width, r.width, PANE_MIN_W);
  };
  if (!on || !beside) return <>{pane(main)}</>;
  return (
    <div className={`ss-split${drag ? " dragging" : ""}`} ref={box} data-testid="session-split">
      <div className="ss-split-side" style={{ flex: `${sp.ratio} 1 0px` }} data-side="main">
        <SideBar rec={main} onClose={() => endSplit("beside")} />
        {pane(main)}
      </div>
      <div
        className="ss-split-divider"
        role="separator"
        aria-orientation="vertical"
        aria-label={t("termpanel.divider")}
        aria-valuenow={Math.round(sp.ratio * 100)}
        tabIndex={0}
        data-testid="split-divider"
        onPointerDown={(e: PointerEvent<HTMLDivElement>) => {
          if (e.button !== 0) return;
          e.preventDefault();
          e.currentTarget.setPointerCapture?.(e.pointerId);
          setDrag(true);
        }}
        onPointerMove={(e: PointerEvent<HTMLDivElement>) => {
          if (drag) set({ ratio: ratio(e.clientX) });
        }}
        onPointerUp={() => setDrag(false)}
        onPointerCancel={() => setDrag(false)}
        onLostPointerCapture={() => setDrag(false)}
        onDoubleClick={() => set({ ratio: 0.5 })}
        onKeyDown={(e: KeyboardEvent<HTMLDivElement>) => {
          if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
          e.preventDefault();
          const w = box.current?.getBoundingClientRect().width ?? 0;
          set({ ratio: clampRatio(sp.ratio + (e.key === "ArrowRight" ? 0.05 : -0.05), w, PANE_MIN_W) });
        }}
      />
      <div className="ss-split-side" style={{ flex: `${1 - sp.ratio} 1 0px` }} data-side="beside">
        <SideBar rec={beside} onClose={() => endSplit("main")} />
        {pane(beside)}
      </div>
    </div>
  );
}

/** The picker of the other TERMINALS sessions, for the session open now. */
export function SplitPicker({ main }: { main: SessionRec }) {
  const sp = useSplit();
  const ss = useSessions();
  const s = useStore();
  const ref = useRef<HTMLDivElement>(null);
  const open = sp.picking === main.id && s.ui.view === "session";
  const rows = open ? splitChoices(ss.list, ss.agents, main.id) : [];
  // under the main column's header, at its right edge (the menu is fixed to the window)
  const [at, setAt] = useState<{ left: number; top: number } | null>(null);
  useLayoutEffect(() => {
    if (!open) return;
    const place = () => {
      const m = document.querySelector("main.main")?.getBoundingClientRect();
      const w = ref.current?.offsetWidth ?? 260;
      if (m) setAt({ left: Math.max(6, m.right - w - 16), top: m.top + 56 });
    };
    place();
    addEventListener("resize", place);
    return () => removeEventListener("resize", place);
  }, [open]);
  useEffect(() => {
    if (!open) return;
    ref.current?.querySelector<HTMLElement>("button")?.focus({ preventScroll: true });
    const outside = (e: globalThis.PointerEvent) => {
      if (!ref.current?.contains(e.target as Node)) closeSplitPicker();
    };
    document.addEventListener("pointerdown", outside, true);
    return () => document.removeEventListener("pointerdown", outside, true);
  }, [open]);
  if (!open) return null;
  const move = (e: KeyboardEvent<HTMLDivElement>) => {
    const items = [...(ref.current?.querySelectorAll<HTMLElement>("button") ?? [])];
    const at = items.indexOf(document.activeElement as HTMLElement);
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      closeSplitPicker();
    } else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      items[(at + (e.key === "ArrowDown" ? 1 : items.length - 1)) % items.length]?.focus();
    }
  };
  return (
    <div ref={ref} className="row-menu ss-split-pick" role="menu" aria-label={t("split.pick")} data-testid="split-picker" style={at ?? undefined} onKeyDown={move}>
      <div className="ss-split-pick-h">{t("split.pick")}</div>
      {rows.length === 0 && <div className="ss-split-pick-none">{t("split.none")}</div>}
      {rows.map((r) => (
        <button key={r.id} type="button" role="menuitem" className="row-mi ss-split-pick-row" data-testid="split-pick" data-session={r.id} title={r.cwd} onClick={() => splitWith(main.id, r.id)}>
          <TermRowMark agent={termMarkAgent(r)} size={13} />
          <span className="ss-split-name">{pickTitle(r, termFallbackName(r, ss.agents)).title}</span>
          <span className="ss-split-path">{folderName(r.cwd)}</span>
        </button>
      ))}
    </div>
  );
}
