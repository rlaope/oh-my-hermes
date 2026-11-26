/** Sidebar width the person dragged, kept on this computer. Nothing saved: tokens.css `--side-w` (248px). */
import { CHAT_MIN, OVERLAY_BELOW, OVERLAY_STRIP, PANEL_MIN } from "../app/panelWidth";

export const SIDE_DEFAULT = 248;
/** Wide enough for the footer's four nav buttons plus two usage rings without overflowing `.side`. */
export const SIDE_MIN = 204;
export const SIDE_MAX = 480;
export const SIDE_KEY = "omher.sideWidth";

/** The widest the sidebar may be in a window this wide alongside an open right panel (0 when closed). */
export function sideMax(windowW: number, panelW = 0, panelMax = false): number {
  if (panelMax) return Math.max(SIDE_MIN, Math.min(SIDE_MAX, Math.round(windowW - PANEL_MIN)));
  const keep =
    windowW < OVERLAY_BELOW
      ? panelW > 0
        ? Math.max(CHAT_MIN, panelW + OVERLAY_STRIP)
        : CHAT_MIN
      : panelW + CHAT_MIN;
  return Math.max(SIDE_MIN, Math.min(SIDE_MAX, Math.round(windowW - keep)));
}

export function clampSide(w: number, windowW: number, panelW = 0, panelMax = false): number {
  return Math.round(Math.min(sideMax(windowW, panelW, panelMax), Math.max(SIDE_MIN, w)));
}

/** The width the sidebar is drawn at, or null for the stylesheet's own. A smaller window shows a saved width
 *  narrower without forgetting it. */
export function shownSideWidth(saved: number | null, windowW: number, panelW = 0, panelMax = false): number | null {
  return saved === null ? null : clampSide(saved, windowW, panelW, panelMax);
}

export function readSideWidth(): number | null {
  try {
    const raw = typeof localStorage !== "undefined" ? localStorage.getItem(SIDE_KEY) : null;
    if (raw === null || raw.trim() === "") return null;
    const n = Number(raw);
    return Number.isFinite(n) && n >= SIDE_MIN && n <= SIDE_MAX ? Math.round(n) : null;
  } catch {
    return null;
  }
}

/** Save the dragged width, or forget it (null: back to the stylesheet's width). */
export function saveSideWidth(w: number | null): number | null {
  const next = w === null ? null : Math.round(w);
  try {
    if (typeof localStorage !== "undefined") {
      if (next === null) localStorage.removeItem(SIDE_KEY);
      else localStorage.setItem(SIDE_KEY, String(next));
    }
  } catch {
    /* no storage */
  }
  return next;
}

// Live target sidebar width shared with PanelResizer so it never reads a pre-mount default or a mid-transition rect.
let liveSideW: number | null = null;
const sideListeners = new Set<() => void>();

export function getLiveSideWidth(): number {
  if (liveSideW !== null) return liveSideW;
  const saved = readSideWidth();
  if (saved === null) return SIDE_DEFAULT;
  const winW = typeof window !== "undefined" ? window.innerWidth : 1280;
  return clampSide(saved, winW);
}

export function setLiveSideWidth(w: number): void {
  const next = Math.round(w);
  if (liveSideW === next) return;
  liveSideW = next;
  for (const fn of sideListeners) fn();
}

export function onSideWidth(fn: () => void): () => void {
  sideListeners.add(fn);
  return () => sideListeners.delete(fn);
}
