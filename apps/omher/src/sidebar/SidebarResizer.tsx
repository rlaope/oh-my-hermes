import { useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore, type KeyboardEvent, type PointerEvent } from "react";
import { getLivePanel, onPanelLayout } from "../app/panelWidth";
import { t } from "../i18n";
import { clampSide, readSideWidth, saveSideWidth, setLiveSideWidth, shownSideWidth, SIDE_DEFAULT, SIDE_MIN, sideMax } from "./sidebarWidth";

const STEP = 16;

const el = (id: string) => document.querySelector<HTMLElement>(`[data-testid=${id}]`);

/** A drag handle on the sidebar's right edge. Dragging (or ←/→ with it focused) sets `--side-w` on the window,
 *  which every rule that sizes the sidebar already reads, within [SIDE_MIN, min(SIDE_MAX, window - panel - CHAT_MIN)];
 *  a double click (or Enter) goes back to the usual width (248px). */
export function SidebarResizer() {
  const [saved, setSaved] = useState<number | null>(readSideWidth);
  const [drag, setDrag] = useState<number | null>(null);
  const [winW, setWinW] = useState(() => window.innerWidth);
  const panel = useSyncExternalStore(onPanelLayout, getLivePanel, getLivePanel);
  const stopDrag = useRef<(() => void) | null>(null);

  const panelW = panel.open && !panel.max ? panel.width : 0;
  const maxW = sideMax(winW, panelW, panel.max);
  const fit = (w: number) => {
    const p = getLivePanel();
    return clampSide(w, window.innerWidth, p.open && !p.max ? p.width : 0, p.max);
  };

  const width = drag ?? shownSideWidth(saved, winW, panelW, panel.max);
  // Target width (never a mid-transition DOM rect): used for keyboard stepping, aria-valuenow, and PanelResizer sync.
  const current = width ?? SIDE_DEFAULT;

  useEffect(() => {
    const on = () => setWinW(window.innerWidth);
    window.addEventListener("resize", on);
    return () => window.removeEventListener("resize", on);
  }, []);

  useEffect(() => () => stopDrag.current?.(), []);

  useLayoutEffect(() => {
    const win = el("window");
    if (win) {
      if (width === null) win.style.removeProperty("--side-w");
      else win.style.setProperty("--side-w", `${width}px`);
      // while dragging the grid follows the pointer with no easing, and nothing under it selects
      win.classList.toggle("side-dragging", drag !== null);
    }
    setLiveSideWidth(current);
  }, [width, current, drag, winW]);

  const set = (w: number | null) => setSaved(saveSideWidth(w));

  return (
    <div
      className={`side-resizer${drag !== null ? " on" : ""}`}
      role="separator"
      aria-orientation="vertical"
      aria-label={t("side.resize")}
      aria-valuemin={SIDE_MIN}
      aria-valuemax={maxW}
      aria-valuenow={Math.round(current)}
      title={t("side.resizeTip")}
      tabIndex={0}
      data-testid="sidebar-resizer"
      onPointerDown={(e: PointerEvent<HTMLDivElement>) => {
        if (e.button !== 0) return;
        stopDrag.current?.();
        const target = e.currentTarget;
        const pid = e.pointerId;
        try {
          target.setPointerCapture?.(pid);
        } catch {
          /* synthetic or detached pointer */
        }
        el("window")?.classList.add("side-dragging");
        const x0 = e.clientX;
        const w0 = el("sidebar")?.getBoundingClientRect().width ?? current;
        let last = Math.round(w0);
        let moved = false;
        setDrag(last);
        const end = (commit: boolean) => {
          window.removeEventListener("pointermove", onMove);
          window.removeEventListener("pointerup", onUp);
          window.removeEventListener("pointercancel", onCancel);
          window.removeEventListener("blur", onBlur);
          target.removeEventListener("lostpointercapture", onLost);
          try {
            if (target.hasPointerCapture?.(pid)) target.releasePointerCapture(pid);
          } catch {
            /* already released */
          }
          el("window")?.classList.remove("side-dragging");
          stopDrag.current = null;
          if (commit && moved) set(last);
          setDrag(null);
        };
        const onMove = (ev: globalThis.PointerEvent) => {
          if (ev.pointerId !== pid) return;
          if (ev.pointerType === "mouse" && (ev.buttons & 1) === 0) {
            end(true);
            return;
          }
          moved = true;
          last = fit(w0 + (ev.clientX - x0));
          setDrag(last);
        };
        const onUp = (ev: globalThis.PointerEvent) => {
          if (ev.pointerId === pid) end(true);
        };
        const onCancel = (ev: globalThis.PointerEvent) => {
          if (ev.pointerId === pid) end(false);
        };
        const onBlur = () => end(true);
        const onLost = (ev: globalThis.PointerEvent) => {
          if (ev.pointerId === pid) end(true);
        };
        stopDrag.current = () => end(false);
        window.addEventListener("pointermove", onMove);
        window.addEventListener("pointerup", onUp);
        window.addEventListener("pointercancel", onCancel);
        window.addEventListener("blur", onBlur);
        target.addEventListener("lostpointercapture", onLost);
      }}
      onDoubleClick={() => set(null)}
      onKeyDown={(e: KeyboardEvent<HTMLDivElement>) => {
        if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
          e.preventDefault();
          const step = e.shiftKey ? STEP * 4 : STEP;
          set(fit(current + (e.key === "ArrowRight" ? step : -step)));
        } else if (e.key === "Enter") {
          e.preventDefault();
          set(null);
        }
      }}
    />
  );
}
