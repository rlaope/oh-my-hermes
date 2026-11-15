// The bottom terminal panel (VSCode-style): spans the main column under the open view, toggled by Ctrl+` from
// anywhere (src/app/shortcuts.ts). Tabs, one login shell each (+ adds one in the open thread's folder, x stops it);
// the top edge drags to resize, the height is saved on this computer. Hiding it stops nothing: shells keep running
// and keep their scrollback. Esc stays the shell's.
import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import "./panel.css";
import { useStore } from "../state/store";
import { useResolvedTheme } from "../app/theme";
import { CloseIcon, PlusIcon, ChevronDown } from "../ui";
import { t } from "../i18n";
import { FindBar } from "../sessions/term/find-bar";
import { FIND_EVENT, type FindRequest } from "../sessions/term/engine-find";
import { addTerminalTab, closeTerminalTab, leafName, pickTerminalTab, toggleTerminal, useTermPanel, type TermTab } from "./state";
import { attachTerm, disposeTerm, focusTerm, relookTerms, showTerm } from "./terms";

/** The thread view's hook (re-exported from ./state, which loads no terminal code): the open thread's folder. */
export { setTerminalCwd } from "./state";

export const PANEL_H_KEY = "omher.termpanel.h";
export const PANEL_H_DEFAULT = 260;
export const PANEL_H_MIN = 120;
/** what the view above keeps at the least */
const ABOVE_MIN = 160;
const STEP = 16;

/** A saved height within [min, window - what the view above keeps]. */
export function clampPanelH(h: number, winH: number): number {
  const max = Math.max(PANEL_H_MIN, winH - ABOVE_MIN);
  return Math.round(Math.min(max, Math.max(PANEL_H_MIN, Number.isFinite(h) ? h : PANEL_H_DEFAULT)));
}

function readH(): number {
  try {
    const v = Number(localStorage.getItem(PANEL_H_KEY));
    return v > 0 ? v : PANEL_H_DEFAULT;
  } catch {
    return PANEL_H_DEFAULT;
  }
}

function saveH(h: number): void {
  try {
    localStorage.setItem(PANEL_H_KEY, String(Math.round(h)));
  } catch {
    /* no storage */
  }
}

function TabBody({ tab, active, open, mode, focus }: { tab: TermTab; active: boolean; open: boolean; mode: "dark" | "light"; focus: number }) {
  const box = useRef<HTMLDivElement>(null);
  const wrap = useRef<HTMLDivElement>(null);
  const [find, setFind] = useState<FindRequest | null>(null);
  useEffect(() => {
    if (!box.current) return;
    return attachTerm(tab.key, tab.want, box.current, mode);
    // made once per tab; theme changes go through relookTerms
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab.key]);
  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const on = (e: Event) => setFind((e as CustomEvent<FindRequest>).detail);
    el.addEventListener(FIND_EVENT, on);
    return () => el.removeEventListener(FIND_EVENT, on);
  }, []);
  const shown = open && active;
  useEffect(() => {
    showTerm(tab.key, shown);
    if (shown) {
      // after the panel is laid out: the terminal is measured, then takes the keyboard
      const r = requestAnimationFrame(() => focusTerm(tab.key));
      return () => cancelAnimationFrame(r);
    }
  }, [shown, focus, tab.key]);
  return (
    <div className="term-wrap termpanel-body" ref={wrap} hidden={!active} data-testid="termpanel-terminal" data-tab={tab.key}>
      <div className="term-box" ref={box} />
      {find && shown && <FindBar req={find} onClose={() => setFind(null)} />}
    </div>
  );
}

export function TerminalPanel() {
  const s = useStore();
  const mode = useResolvedTheme(s.ui.theme);
  const p = useTermPanel();
  const [h, setH] = useState(readH);
  const [winH, setWinH] = useState(() => window.innerHeight);
  const [drag, setDrag] = useState<number | null>(null);
  const start = useRef<{ y: number; h: number } | null>(null);
  const height = clampPanelH(drag ?? h, winH);

  useEffect(() => {
    const on = () => setWinH(window.innerHeight);
    window.addEventListener("resize", on);
    return () => window.removeEventListener("resize", on);
  }, []);
  useEffect(() => relookTerms(mode), [mode]);

  // a closed tab's shell is stopped (the tab list is the truth; the terminal goes with its tab)
  const known = useRef(new Set<number>());
  useEffect(() => {
    const now = new Set(p.tabs.map((x) => x.key));
    for (const k of known.current) if (!now.has(k)) disposeTerm(k);
    known.current = now;
  }, [p.tabs]);

  const set = (v: number) => {
    const c = clampPanelH(v, window.innerHeight);
    setH(c);
    saveH(c);
  };
  const end = () => {
    if (start.current && drag !== null) set(drag);
    start.current = null;
    setDrag(null);
  };

  return (
    <section
      className={`termpanel${drag !== null ? " dragging" : ""}`}
      hidden={!p.open}
      style={{ height }}
      aria-label={t("termpanel.label")}
      data-testid="termpanel"
      data-open={p.open ? "true" : "false"}
    >
      <div
        className="termpanel-resizer"
        role="separator"
        aria-orientation="horizontal"
        aria-label={t("termpanel.resize")}
        aria-valuenow={height}
        tabIndex={0}
        data-testid="termpanel-resizer"
        onPointerDown={(e: PointerEvent<HTMLDivElement>) => {
          if (e.button !== 0) return;
          e.preventDefault();
          e.currentTarget.setPointerCapture?.(e.pointerId);
          start.current = { y: e.clientY, h: height };
          setDrag(height);
        }}
        onPointerMove={(e: PointerEvent<HTMLDivElement>) => {
          const st = start.current;
          // the handle is the panel's top edge: moving up makes it taller
          if (st) setDrag(clampPanelH(st.h + (st.y - e.clientY), window.innerHeight));
        }}
        onPointerUp={end}
        onPointerCancel={end}
        onLostPointerCapture={end}
        onDoubleClick={() => set(PANEL_H_DEFAULT)}
        onKeyDown={(e: KeyboardEvent<HTMLDivElement>) => {
          if (e.key !== "ArrowUp" && e.key !== "ArrowDown") return;
          e.preventDefault();
          const step = e.shiftKey ? STEP * 4 : STEP;
          set(height + (e.key === "ArrowUp" ? step : -step));
        }}
      />
      <div className="termpanel-bar">
        <div className="termpanel-tabs" role="tablist" aria-label={t("termpanel.tabs")}>
          {p.tabs.map((tab) => {
            const name = leafName(tab.cwd ?? tab.want);
            return (
              <div key={tab.key} className={`termpanel-tab${tab.key === p.active ? " on" : ""}`} data-testid="termpanel-tab" data-tab={tab.key}>
                <button
                  type="button"
                  role="tab"
                  aria-selected={tab.key === p.active}
                  className="termpanel-tab-name"
                  title={tab.cwd ?? tab.want ?? t("termpanel.home")}
                  onClick={() => pickTerminalTab(tab.key)}
                >
                  {name}
                </button>
                <button
                  type="button"
                  className="termpanel-tab-x"
                  aria-label={t("termpanel.closeTab", { name })}
                  title={t("termpanel.closeTab", { name })}
                  data-testid="termpanel-tab-close"
                  onClick={() => closeTerminalTab(tab.key)}
                >
                  <CloseIcon />
                </button>
              </div>
            );
          })}
          <button type="button" className="termpanel-ib" aria-label={t("termpanel.newTab")} title={t("termpanel.newTab")} data-testid="termpanel-new" onClick={addTerminalTab}>
            <PlusIcon size={13} />
          </button>
        </div>
        <button type="button" className="termpanel-ib" aria-label={t("termpanel.hide")} title={t("termpanel.hide")} data-testid="termpanel-hide" onClick={toggleTerminal}>
          <ChevronDown size={10} />
        </button>
      </div>
      <div className="termpanel-bodies">
        {p.tabs.map((tab) => (
          <TabBody key={tab.key} tab={tab} active={tab.key === p.active} open={p.open} mode={mode} focus={p.focus} />
        ))}
      </div>
    </section>
  );
}
