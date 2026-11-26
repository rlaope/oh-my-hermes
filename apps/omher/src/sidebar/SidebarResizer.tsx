import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { t } from "../i18n";
import { clampSide, readSideWidth, saveSideWidth, shownSideWidth, SIDE_DEFAULT, SIDE_MIN, sideMax } from "./sidebarWidth";

const STEP = 16;

const el = (id: string) => document.querySelector<HTMLElement>(`[data-testid=${id}]`);

/** A drag handle on the sidebar's right edge. Dragging (or ←/→ with it focused) sets `--side-w` on the window,
 *  which every rule that sizes the sidebar already reads, within [SIDE_MIN, min(SIDE_MAX, window - panel - CHAT_MIN)];
 *  a double click (or Enter) goes back to the usual width (248px). */
export function SidebarResizer() {
  const [saved, setSaved] = useState<number | null>(readSideWidth);
  const [drag, setDrag] = useState<number | null>(null);
  const [winW, setWinW] = useState(() => window.innerWidth);
  const stopDrag = useRef<(() => void) | null>(null);

  const sideW = () => el("sidebar")?.getBoundingClientRect().width ?? SIDE_DEFAULT;
  const openPanel = () => {
    const win = el("window");
    const panelMax = win?.classList.contains("panel-max") ?? false;
    const panelOpen = win?.classList.contains("panel-open") ?? false;
    const panelW = panelOpen && !panelMax ? (el("details")?.getBoundingClientRect().width ?? 0) : 0;
    return { panelW, panelMax };
  };
  const fit = (w: number) => {
    const { panelW, panelMax } = openPanel();
    return clampSide(w, window.innerWidth, panelW, panelMax);
  };

  const { panelW, panelMax } = openPanel();
  const width = drag ?? shownSideWidth(saved, winW, panelW, panelMax);

  useEffect(() => {
    const on = () => setWinW(window.innerWidth);
    window.addEventListener("resize", on);
    return () => window.removeEventListener("resize", on);
  }, []);

  useEffect(() => () => stopDrag.current?.(), []);

  useEffect(() => {
    const win = el("window");
    if (!win) return;
    if (width === null) win.style.removeProperty("--side-w");
    else win.style.setProperty("--side-w", `${width}px`);
    // while dragging the grid follows the pointer with no easing, and nothing under it selects
    win.classList.toggle("side-dragging", drag !== null);
    window.dispatchEvent(new Event("omher:side-width"));
  }, [width, drag, winW]);

  const set = (w: number | null) => setSaved(saveSideWidth(w));

  return (
    <div
      className={`side-resizer${drag !== null ? " on" : ""}`}
      role="separator"
      aria-orientation="vertical"
      aria-label={t("side.resize")}
      aria-valuemin={SIDE_MIN}
      aria-valuemax={sideMax(winW, panelW, panelMax)}
      aria-valuenow={Math.round(width ?? sideW())}
      title={t("side.resizeTip")}
      tabIndex={0}
      data-testid="sidebar-resizer"
      onPointerDown={(e: PointerEvent<HTMLDivElement>) => {
        if (e.button !== 0) return;
        e.preventDefault();
        stopDrag.current?.();
        const target = e.currentTarget;
        const pid = e.pointerId;
        try {
          target.setPointerCapture?.(pid);
        } catch {
          /* synthetic or detached pointer */
        }
        const x0 = e.clientX;
        const w0 = sideW();
        let last = Math.round(w0);
        let moved = false;
        setDrag(last);
        const onMove = (ev: globalThis.PointerEvent) => {
          moved = true;
          last = fit(w0 + (ev.clientX - x0));
          setDrag(last);
        };
        const end = (commit: boolean) => {
          window.removeEventListener("pointermove", onMove);
          window.removeEventListener("pointerup", onUp);
          window.removeEventListener("pointercancel", onCancel);
          try {
            if (target.hasPointerCapture?.(pid)) target.releasePointerCapture(pid);
          } catch {
            /* already released */
          }
          stopDrag.current = null;
          if (commit && moved) set(last);
          setDrag(null);
        };
        const onUp = () => end(true);
        const onCancel = () => end(false);
        stopDrag.current = () => end(false);
        window.addEventListener("pointermove", onMove);
        window.addEventListener("pointerup", onUp);
        window.addEventListener("pointercancel", onCancel);
      }}
      onDoubleClick={() => set(null)}
      onKeyDown={(e: KeyboardEvent<HTMLDivElement>) => {
        if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
          e.preventDefault();
          const step = e.shiftKey ? STEP * 4 : STEP;
          set(fit(sideW() + (e.key === "ArrowRight" ? step : -step)));
        } else if (e.key === "Enter") {
          e.preventDefault();
          set(null);
        }
      }}
    />
  );
}
