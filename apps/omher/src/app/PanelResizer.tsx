import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { clampPanel, panelKind, readPanelWidths, savePanelWidth, shownPanelWidth, type PanelKind } from "./panelWidth";
import { t } from "../i18n";

const STEP = 16;

const el = (id: string) => document.querySelector<HTMLElement>(`[data-testid=${id}]`);

/** A drag handle on the side panel's left edge. Dragging (or ←/→ with it focused) sets `--panel-w` on the window,
 *  every rule that sizes the panel already reads it from there, within [PANEL_MIN, window - sidebar - CHAT_MIN]; a
 *  double click (or Enter) goes back to the tab's own width. Details, the tool tabs and Plans each keep their own
 *  width, saved on this computer. A window made smaller shows a saved width narrower without forgetting it. */
export function PanelResizer({ open, tab, max = false }: { open: boolean; tab: string; max?: boolean }) {
  const [widths, setWidths] = useState(readPanelWidths);
  const [drag, setDrag] = useState<number | null>(null);
  const [winW, setWinW] = useState(() => window.innerWidth);
  const start = useRef<{ x: number; w: number; kind: PanelKind } | null>(null);
  const kind = panelKind(tab);
  const sideW = () => el("sidebar")?.getBoundingClientRect().width ?? 248;
  const fit = (w: number) => clampPanel(w, window.innerWidth, sideW());
  const saved = widths[kind];
  // maximised: everything right of the sidebar, and no handle; restoring goes back to the tab's own width
  const width = drag ?? shownPanelWidth(max, saved, window.innerWidth, sideW());

  useEffect(() => {
    const on = () => setWinW(window.innerWidth);
    window.addEventListener("resize", on);
    return () => window.removeEventListener("resize", on);
  }, []);

  useEffect(() => {
    const win = el("window");
    if (!win) return;
    if (width === null || !open) win.style.removeProperty("--panel-w");
    else win.style.setProperty("--panel-w", `${width}px`);
    // while dragging the grid follows the pointer with no easing, and nothing under it selects
    win.classList.toggle("panel-dragging", drag !== null);
  }, [width, open, drag, winW, max]);

  // maximise and restore ease in 180ms (app.css .panel-maxing); a window resize while maximised follows at once
  const first = useRef(true);
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    const win = el("window");
    if (!win) return;
    win.classList.add("panel-maxing");
    const h = setTimeout(() => win.classList.remove("panel-maxing"), 260);
    return () => clearTimeout(h);
  }, [max]);

  const panelW = () => el("details")?.getBoundingClientRect().width ?? 300;
  const set = (k: PanelKind, w: number | null) => setWidths(savePanelWidth(k, w));

  const end = () => {
    const s = start.current;
    start.current = null;
    if (s && drag !== null) set(s.kind, drag);
    setDrag(null);
  };

  if (!open || max) return null;
  return (
    <div
      className={`panel-resizer${drag !== null ? " on" : ""}`}
      role="separator"
      aria-orientation="vertical"
      aria-label={t("pn.resize")}
      aria-valuenow={Math.round(width ?? panelW())}
      title={t("pn.resizeTip")}
      tabIndex={0}
      data-testid="panel-resizer"
      onPointerDown={(e: PointerEvent<HTMLDivElement>) => {
        if (e.button !== 0) return;
        e.preventDefault();
        e.currentTarget.setPointerCapture?.(e.pointerId);
        start.current = { x: e.clientX, w: panelW(), kind };
        setDrag(Math.round(panelW()));
      }}
      onPointerMove={(e: PointerEvent<HTMLDivElement>) => {
        const s = start.current;
        // the handle is on the panel's left edge: moving left makes the panel wider
        if (s) setDrag(fit(s.w + (s.x - e.clientX)));
      }}
      onPointerUp={end}
      onPointerCancel={end}
      onLostPointerCapture={end}
      onDoubleClick={() => set(kind, null)}
      onKeyDown={(e: KeyboardEvent<HTMLDivElement>) => {
        if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
          e.preventDefault();
          const step = e.shiftKey ? STEP * 4 : STEP;
          set(kind, fit(panelW() + (e.key === "ArrowLeft" ? step : -step)));
        } else if (e.key === "Enter") {
          e.preventDefault();
          set(kind, null);
        }
      }}
    />
  );
}
