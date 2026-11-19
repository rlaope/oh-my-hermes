// The bottom terminal panel (VSCode-style): spans the main column under the open view, toggled by Ctrl+` from
// anywhere (src/app/shortcuts.ts). Tabs (+ adds one in the open thread's folder, x stops it), each split into up to
// four panes, one login shell each: ⌘D splits the focused pane right, ⌘⇧D down, ⌘W closes it, ⌘⌥arrows move between
// panes (layout.ts paneKey; Ctrl+Shift+D, Alt+Shift+D, Ctrl+Shift+W, Ctrl+Alt+arrows off macOS). Dividers drag, a
// double click evens them out. A tab whose shell rang while it was not in front carries a dot. The top edge drags to
// resize, the height is saved on this computer. Hiding it stops nothing: shells keep running and keep their
// scrollback. Esc stays the shell's.
import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from "react";
import "./panel.css";
import { useStore } from "../state/store";
import { useResolvedTheme } from "../app/theme";
import { CloseIcon, PlusIcon, ChevronDown } from "../ui";
import { t } from "../i18n";
import { FindBar } from "../sessions/term/find-bar";
import { FIND_EVENT, type FindRequest } from "../sessions/term/engine-find";
import { addTerminalTab, closePane, closeTerminalTab, equalizePanes, focusPane, getTermPanel, leafName, movePaneFocus, pickTerminalTab, seenTerminalTab, setPaneRatio, splitPane, toggleTerminal, useTermPanel, type TermPane, type TermTab } from "./state";
import { attachTerm, disposeTerm, dropOnPane, focusTerm, relookTerms, showTerm, wireFileDrop } from "./terms";
import { clampRatio, isPane, MAX_PANES, paneKey, PANE_MIN_ROWS, PANE_MIN_W, type Layout } from "./layout";
import { readTermSettings } from "../sessions/term/settings";
import { isMac } from "../app/shortcuts";
import { fgName, TermRowMark } from "../sessions/TermRowMark";

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

/** The least height a pane keeps under a divider: four rows of the terminal's font and its padding. */
const paneMinH = () => {
  const t = readTermSettings();
  return Math.ceil(t.fontSize * t.lineHeight) * PANE_MIN_ROWS + 12;
};

/** The split key named for this platform, for a button's tooltip. */
const splitKeys = () => (isMac() ? "⌘D" : "Ctrl+Shift+D");

type NodeProps = { tab: TermTab; front: boolean; shown: boolean; split: boolean; mode: "dark" | "light"; focus: number };

/** One pane: `front`, its tab is the one in front; `shown`, and the panel shows. */
function PaneBody({ pane, tab, front, shown, split, mode, focus }: NodeProps & { pane: TermPane }) {
  const box = useRef<HTMLDivElement>(null);
  const wrap = useRef<HTMLDivElement>(null);
  const [find, setFind] = useState<FindRequest | null>(null);
  useEffect(() => {
    if (!box.current) return;
    return attachTerm(pane.id, pane.want, box.current, mode, !!pane.restored);
    // made once per pane; theme changes go through relookTerms
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pane.id]);
  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const on = (e: Event) => setFind((e as CustomEvent<FindRequest>).detail);
    el.addEventListener(FIND_EVENT, on);
    // a file dropped on the pane, or a picture pasted there: saved, its path typed at the prompt (as TERMINALS does)
    const undo = wireFileDrop(el, (files) => void dropOnPane(pane.id, files));
    return () => {
      el.removeEventListener(FIND_EVENT, on);
      undo();
    };
  }, [pane.id]);
  const focused = tab.focus === pane.id;
  useEffect(() => showTerm(pane.id, shown), [shown, pane.id]);
  useEffect(() => {
    if (!shown || !focused) return;
    // after the panel is laid out: the terminal is measured, then takes the keyboard
    const r = requestAnimationFrame(() => focusTerm(pane.id));
    return () => cancelAnimationFrame(r);
  }, [shown, focus, focused, pane.id]);
  return (
    <div
      className={`term-wrap termpanel-body${split && focused ? " focused" : ""}`}
      ref={wrap}
      hidden={!front}
      data-testid="termpanel-terminal"
      data-tab={tab.key}
      data-pane={pane.id}
      data-focused={focused ? "true" : "false"}
      onFocusCapture={() => focusPane(pane.id)}
      onPointerDownCapture={() => focusPane(pane.id)}
    >
      <div className="term-box" ref={box} />
      {find && shown && <FindBar req={find} onClose={() => setFind(null)} />}
    </div>
  );
}

function Divider({ tab, path, dir, ratio }: { tab: TermTab; path: string; dir: "row" | "col"; ratio: number }) {
  const drag = useRef(false);
  const move = (e: PointerEvent<HTMLDivElement>) => {
    const box = e.currentTarget.parentElement?.getBoundingClientRect();
    if (!drag.current || !box) return;
    const total = dir === "row" ? box.width : box.height;
    const at = dir === "row" ? e.clientX - box.left : e.clientY - box.top;
    setPaneRatio(tab.key, path, clampRatio(at / total, total, dir === "row" ? PANE_MIN_W : paneMinH()));
  };
  const end = () => {
    drag.current = false;
  };
  return (
    <div
      className={`termpanel-divider ${dir}`}
      role="separator"
      aria-orientation={dir === "row" ? "vertical" : "horizontal"}
      aria-label={t("termpanel.divider")}
      aria-valuenow={Math.round(ratio * 100)}
      tabIndex={0}
      data-testid="termpanel-divider"
      data-path={path}
      onPointerDown={(e) => {
        if (e.button !== 0) return;
        e.preventDefault();
        e.currentTarget.setPointerCapture?.(e.pointerId);
        drag.current = true;
      }}
      onPointerMove={move}
      onPointerUp={end}
      onPointerCancel={end}
      onLostPointerCapture={end}
      onDoubleClick={() => equalizePanes(tab.key)}
      onKeyDown={(e: KeyboardEvent<HTMLDivElement>) => {
        const back = dir === "row" ? "ArrowLeft" : "ArrowUp";
        const fwd = dir === "row" ? "ArrowRight" : "ArrowDown";
        if (e.key !== back && e.key !== fwd) return;
        e.preventDefault();
        const box = e.currentTarget.parentElement?.getBoundingClientRect();
        const total = box ? (dir === "row" ? box.width : box.height) : 0;
        const step = e.key === fwd ? 0.05 : -0.05;
        setPaneRatio(tab.key, path, clampRatio(ratio + step, total, dir === "row" ? PANE_MIN_W : paneMinH()));
      }}
    />
  );
}

function LayoutNode({ l, path, ...props }: NodeProps & { l: Layout; path: string }): ReactNode {
  if (isPane(l)) {
    const pane = props.tab.panes.find((p) => p.id === l.pane);
    return pane ? <PaneBody key={pane.id} pane={pane} {...props} /> : null;
  }
  const part = (share: number, child: Layout, p: string) => (
    <div className="termpanel-part" style={{ flex: `${share} 1 0px` }}>
      <LayoutNode l={child} path={p} {...props} />
    </div>
  );
  return (
    <div className={`termpanel-split ${l.dir}`} data-testid="termpanel-split" data-dir={l.dir}>
      {part(l.ratio, l.a, `${path}a`)}
      <Divider tab={props.tab} path={path} dir={l.dir} ratio={l.ratio} />
      {part(1 - l.ratio, l.b, `${path}b`)}
    </div>
  );
}

function TabBody({ tab, active, open, mode, focus }: { tab: TermTab; active: boolean; open: boolean; mode: "dark" | "light"; focus: number }) {
  return (
    <div className="termpanel-layout" hidden={!active} data-testid="termpanel-layout" data-tab={tab.key} data-panes={tab.panes.length}>
      <LayoutNode l={tab.layout} path="" tab={tab} front={active} shown={open && active} split={tab.panes.length > 1} mode={mode} focus={focus} />
    </div>
  );
}

/** The pane keys, taken on the way down inside the panel (before xterm, which would send ⌘D/Ctrl+Shift+D on). */
function onPaneKey(e: globalThis.KeyboardEvent): void {
  const k = paneKey(e, isMac());
  if (!k) return;
  e.preventDefault();
  e.stopPropagation();
  if (e.repeat) return;
  const s = getTermPanel();
  const tab = s.tabs.find((x) => x.key === s.active);
  if (!tab) return;
  if (k.kind === "split") splitPane(k.dir);
  else if (k.kind === "close") closePane(tab.focus);
  else movePaneFocus(k.dir);
}

const SplitIcon = () => (
  <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" aria-hidden="true">
    <rect x="2" y="2.5" width="12" height="11" rx="1.5" />
    <path d="M8 2.5v11" />
  </svg>
);

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

  // a closed pane's shell is stopped (the tab list is the truth; the terminal goes with its pane or its tab)
  const known = useRef(new Set<number>());
  useEffect(() => {
    const now = new Set(p.tabs.flatMap((x) => x.panes.map((y) => y.id)));
    for (const k of known.current) if (!now.has(k)) disposeTerm(k);
    known.current = now;
  }, [p.tabs]);

  // the pane keys work while the keyboard is in the panel
  const section = useRef<HTMLElement>(null);
  useEffect(() => {
    const el = section.current;
    if (!el) return;
    el.addEventListener("keydown", onPaneKey, true);
    return () => el.removeEventListener("keydown", onPaneKey, true);
  }, []);
  // the tab in front is seen when the window comes back to it
  useEffect(() => {
    const see = () => {
      if (getTermPanel().open && document.hasFocus()) seenTerminalTab();
    };
    window.addEventListener("focus", see);
    document.addEventListener("visibilitychange", see);
    return () => {
      window.removeEventListener("focus", see);
      document.removeEventListener("visibilitychange", see);
    };
  }, []);
  const front = p.tabs.find((x) => x.key === p.active);

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
      ref={section}
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
                  title={tab.fg ? `${t("term.fgRunning", { name: fgName(tab.fg) })}\n${tab.cwd ?? tab.want ?? t("termpanel.home")}` : (tab.cwd ?? tab.want ?? t("termpanel.home"))}
                  onClick={() => pickTerminalTab(tab.key)}
                  data-fg={tab.fg ?? undefined}
                >
                  {tab.fg && <TermRowMark agent={tab.fg} live size={12} />}
                  {name}
                  {tab.panes.length > 1 && <span className="termpanel-tab-n">{tab.panes.length}</span>}
                  {tab.rang && <span className="termpanel-ring" data-testid="termpanel-ring" role="img" aria-label={t("termpanel.rang")} title={t("termpanel.rang")} />}
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
        <button
          type="button"
          className="termpanel-ib"
          aria-label={t("termpanel.splitRight", { keys: splitKeys() })}
          title={t("termpanel.splitRight", { keys: splitKeys() })}
          data-testid="termpanel-split-right"
          disabled={!front || front.panes.length >= MAX_PANES}
          onClick={() => splitPane("right")}
        >
          <SplitIcon />
        </button>
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
