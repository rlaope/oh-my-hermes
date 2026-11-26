/** Side panel width the person dragged, per kind of tab: Details reads well narrow, the tool tabs and Plans want
 *  room, so one width for all would undo the others. Nothing saved: the stylesheet's width for that tab. */

export type PanelKind = "details" | "tools" | "runs";

export const PANEL_MIN = 260;
/** The chat column never gets narrower than this while the panel is dragged wider. */
export const CHAT_MIN = 360;
const KEY = "omher.panelWidth";

export function panelKind(tab: string | undefined): PanelKind {
  return tab === "details" ? "details" : tab === "runs" ? "runs" : "tools";
}

/** The widest the panel may be in a window this wide with a sidebar this wide. Under 1100px the panel slides over
 *  the chat instead of taking a column (app.css), so there it leaves at least 300px (and never covers the sidebar). */
export function panelMax(windowW: number, sideW: number): number {
  const keep = windowW < OVERLAY_BELOW ? Math.max(OVERLAY_GAP, sideW + OVERLAY_STRIP) : sideW + CHAT_MIN;
  return Math.max(PANEL_MIN, windowW - keep);
}

/** app.css: `@media (max-width: 1099px)` turns the panel into an overlay. */
export const OVERLAY_BELOW = 1100;
const OVERLAY_GAP = 300;
/** Minimum strip of chat kept clear between the sidebar and an overlay panel under 1100px (248 + 52 = 300). */
export const OVERLAY_STRIP = 52;

/** The stylesheet's default width for a panel tab when the person has not dragged one. */
export function panelDefaultWidth(kind: PanelKind, windowW: number, sideW: number): number {
  if (kind === "details") return 300;
  if (kind === "tools") return 400;
  return Math.round(Math.min(560, Math.max(460, windowW - sideW - 480)));
}

export interface LivePanel {
  open: boolean;
  max: boolean;
  width: number;
}

let livePanel: LivePanel = { open: false, max: false, width: 0 };
const panelListeners = new Set<() => void>();

export function getLivePanel(): LivePanel {
  return livePanel;
}

export function setLivePanel(next: LivePanel): void {
  const width = Math.round(next.width);
  if (livePanel.open === next.open && livePanel.max === next.max && livePanel.width === width) return;
  livePanel = { open: next.open, max: next.max, width };
  for (const fn of panelListeners) fn();
}

export function onPanelLayout(fn: () => void): () => void {
  panelListeners.add(fn);
  return () => panelListeners.delete(fn);
}

export function clampPanel(w: number, windowW: number, sideW: number): number {
  return Math.round(Math.min(panelMax(windowW, sideW), Math.max(PANEL_MIN, w)));
}

/** Maximised in place: every pixel right of the sidebar (the chat column folds to 0; under 1100px the overlay
 *  covers the chat the same way). */
export function maxedPanel(windowW: number, sideW: number): number {
  return Math.max(PANEL_MIN, Math.round(windowW - sideW));
}

/** The width the panel is drawn at, or null for the stylesheet's own. Maximising never saves a width, so restoring
 *  lands on exactly the width the tab had before (its saved one, fitted to the window, or the stylesheet's). */
export function shownPanelWidth(max: boolean, saved: number | undefined, windowW: number, sideW: number): number | null {
  if (max) return maxedPanel(windowW, sideW);
  return saved === undefined ? null : clampPanel(saved, windowW, sideW);
}

export function readPanelWidths(): Partial<Record<PanelKind, number>> {
  try {
    const raw = typeof localStorage !== "undefined" ? localStorage.getItem(KEY) : null;
    const v = raw ? (JSON.parse(raw) as unknown) : null;
    if (!v || typeof v !== "object") return {};
    const out: Partial<Record<PanelKind, number>> = {};
    for (const k of ["details", "tools", "runs"] as const) {
      const n = (v as Record<string, unknown>)[k];
      if (typeof n === "number" && Number.isFinite(n) && n >= PANEL_MIN) out[k] = Math.round(n);
    }
    return out;
  } catch {
    return {};
  }
}

/** Save one kind's width, or forget it (null: back to the stylesheet's width). */
export function savePanelWidth(kind: PanelKind, w: number | null): Partial<Record<PanelKind, number>> {
  const all = readPanelWidths();
  if (w === null) delete all[kind];
  else all[kind] = Math.round(w);
  try {
    if (typeof localStorage !== "undefined") localStorage.setItem(KEY, JSON.stringify(all));
  } catch {
    /* no storage */
  }
  return all;
}
