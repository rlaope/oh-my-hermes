// The bottom terminal panel's state, kept apart from the panel's UI so the app's shortcut and the thread view can
// reach it without loading xterm: whether it shows, its tabs (each a layout of up to four panes, one login shell
// each; layout.ts), which tab is in front, and the folder a new tab starts in.
//
// `setTerminalCwd(path | null)` is the hook the thread view calls with the open thread's folder (null: none, the
// shell starts at home). It changes where the NEXT tab starts; a running shell keeps its own folder.
import { useSyncExternalStore } from "react";
import { windowWatched } from "../lib/notify";
import { MAX_PANES, equalize, neighbor, panesOf, removePane, setRatioAt, splitLayout, type FocusDir, type Layout } from "./layout";

/** One pane of a tab: one login shell. */
export interface TermPane {
  /** the panel's own key for the pane (not the shell's session id) */
  id: number;
  /** the folder asked for when the pane opened (null: home) */
  want: string | null;
  /** the folder the shell started in, once it has */
  cwd: string | null;
  /** the CLI in the shell's foreground (`session-fg`), null for the shell itself */
  fg?: string | null;
}

export interface TermTab {
  /** the panel's own key for the tab (not the shell's session id) */
  key: number;
  /** the focused pane's folder asked for (the tab's name and the Tasks page read the tab's) */
  want: string | null;
  /** the focused pane's folder, once its shell started */
  cwd: string | null;
  /** the focused pane's foreground CLI */
  fg?: string | null;
  /** how the tab's panes are laid out (one pane: `{ pane }`) */
  layout: Layout;
  panes: TermPane[];
  /** the pane that has (or gets) the keyboard */
  focus: number;
  /** a shell in it rang (bell, OSC 9 message, OSC 777 notify) while the tab was not in front; no text is kept */
  rang?: boolean;
}

export interface TermPanelState {
  /** shown; a hidden panel keeps its shells running and their scrollback */
  open: boolean;
  /** opened at least once this page load (the panel's code loads then) */
  mounted: boolean;
  tabs: TermTab[];
  active: number | null;
  /** where a new tab starts (setTerminalCwd); null: home */
  cwd: string | null;
  /** bumped each time the panel opens or a tab or pane is picked: the focused pane in front takes the keyboard */
  focus: number;
}

let state: TermPanelState = { open: false, mounted: false, tabs: [], active: null, cwd: null, focus: 0 };
let nextKey = 0;
let nextPane = 0;
const listeners = new Set<() => void>();

function set(patch: Partial<TermPanelState>): void {
  state = { ...state, ...patch };
  for (const fn of listeners) fn();
}

export const getTermPanel = (): TermPanelState => state;

export function subscribeTermPanel(fn: () => void): () => void {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

export function useTermPanel(): TermPanelState {
  return useSyncExternalStore(subscribeTermPanel, getTermPanel, getTermPanel);
}

/** The open thread's folder, for the next tab the panel opens (null: home). Only an absolute path counts here; the
 *  desktop shell checks again that it is an existing folder and starts at home otherwise. */
export function setTerminalCwd(path: string | null): void {
  const p = typeof path === "string" && path.trim() ? path.trim() : null;
  if (p === state.cwd) return;
  set({ cwd: p });
}

/** The tab with its name fields taken from its focused pane. */
function mirror(tab: TermTab): TermTab {
  const f = tab.panes.find((p) => p.id === tab.focus) ?? tab.panes[0];
  return f ? { ...tab, want: f.want, cwd: f.cwd, fg: f.fg } : tab;
}

const tabOfPane = (pane: number) => state.tabs.find((t) => t.panes.some((p) => p.id === pane));

function putTab(tab: TermTab, patch: Partial<TermPanelState> = {}): void {
  set({ tabs: state.tabs.map((t) => (t.key === tab.key ? mirror(tab) : t)), ...patch });
}

/** A new tab (a new login shell) in the folder setTerminalCwd last named, in front. */
export function addTerminalTab(): void {
  const pane: TermPane = { id: ++nextPane, want: state.cwd, cwd: null };
  const tab: TermTab = { key: ++nextKey, want: state.cwd, cwd: null, layout: { pane: pane.id }, panes: [pane], focus: pane.id };
  set({ tabs: [...state.tabs, tab], active: tab.key, open: true, mounted: true, focus: state.focus + 1 });
}

/** Close a tab: its shells are stopped. The last one closing hides the panel. */
export function closeTerminalTab(key: number): void {
  const at = state.tabs.findIndex((t) => t.key === key);
  if (at < 0) return;
  const tabs = state.tabs.filter((t) => t.key !== key);
  const active = state.active !== key ? state.active : (tabs[Math.min(at, tabs.length - 1)]?.key ?? null);
  set({ tabs: clearRing(tabs, active), active, open: tabs.length ? state.open : false, focus: state.focus + 1 });
}

/** The tab in front is seen: its ring goes. */
const clearRing = (tabs: TermTab[], key: number | null) => (tabs.some((t) => t.key === key && t.rang) ? tabs.map((t) => (t.key === key ? { ...t, rang: false } : t)) : tabs);

export function pickTerminalTab(key: number): void {
  if (!state.tabs.some((t) => t.key === key)) return;
  set({ tabs: clearRing(state.tabs, key), active: key, focus: state.focus + 1 });
}

/** Split the active tab's focused pane: a new login shell right of it or under it, in the focused pane's folder (where
 *  its shell started; the folder it asked for until then). False when there is no tab or it has MAX_PANES. */
export function splitPane(dir: "right" | "down"): boolean {
  const tab = state.tabs.find((t) => t.key === state.active);
  if (!tab || tab.panes.length >= MAX_PANES) return false;
  const from = tab.panes.find((p) => p.id === tab.focus) ?? tab.panes[0];
  const pane: TermPane = { id: nextPane + 1, want: from.cwd ?? from.want, cwd: null };
  const layout = splitLayout(tab.layout, from.id, dir === "right" ? "row" : "col", pane.id);
  if (!layout) return false;
  nextPane = pane.id;
  putTab({ ...tab, layout, panes: [...tab.panes, pane], focus: pane.id }, { open: true, focus: state.focus + 1 });
  return true;
}

/** Close pane `id` (its shell is stopped): the part beside it takes its room and the keyboard. The last pane of a tab
 *  closes the tab. */
export function closePane(id: number): void {
  const tab = tabOfPane(id);
  if (!tab) return;
  if (tab.panes.length === 1) return closeTerminalTab(tab.key);
  const { layout, heir } = removePane(tab.layout, id);
  if (!layout) return closeTerminalTab(tab.key);
  const panes = tab.panes.filter((p) => p.id !== id);
  const focus = tab.focus === id ? (heir ?? panesOf(layout)[0]) : tab.focus;
  putTab({ ...tab, layout, panes, focus }, { focus: state.focus + 1 });
}

/** Pane `id` has the keyboard (the person clicked in it). `take`: and give it the keyboard now (a focus key). */
export function focusPane(id: number, take = false): void {
  const tab = tabOfPane(id);
  if (!tab || (tab.focus === id && !take)) return;
  putTab({ ...tab, focus: id }, take ? { focus: state.focus + 1 } : {});
}

/** Move the keyboard to the pane beside the focused one (⌘⌥arrows). False at the edge. */
export function movePaneFocus(dir: FocusDir): boolean {
  const tab = state.tabs.find((t) => t.key === state.active);
  if (!tab) return false;
  const to = neighbor(tab.layout, tab.focus, dir);
  if (to === null) return false;
  focusPane(to, true);
  return true;
}

/** The divider at `path` of tab `key` moved: its first part takes `ratio`. */
export function setPaneRatio(key: number, path: string, ratio: number): void {
  const tab = state.tabs.find((t) => t.key === key);
  if (!tab) return;
  putTab({ ...tab, layout: setRatioAt(tab.layout, path, ratio) });
}

/** Every pane of tab `key` the same size (a double click on a divider). */
export function equalizePanes(key: number): void {
  const tab = state.tabs.find((t) => t.key === key);
  if (!tab) return;
  putTab({ ...tab, layout: equalize(tab.layout) });
}

/** The CLI in pane `id`'s foreground (the shell's `session-fg` event), null when the shell itself is in front. */
export function setPaneFg(id: number, fg: string | null): void {
  const tab = tabOfPane(id);
  const pane = tab?.panes.find((p) => p.id === id);
  if (!tab || !pane || (pane.fg ?? null) === fg) return;
  putTab({ ...tab, panes: tab.panes.map((p) => (p.id === id ? { ...p, fg } : p)) });
}

/** The shell of pane `id` started in `cwd`. */
export function setPaneCwd(id: number, cwd: string): void {
  const tab = tabOfPane(id);
  if (!tab) return;
  putTab({ ...tab, panes: tab.panes.map((p) => (p.id === id ? { ...p, cwd } : p)) });
}

/** The shell in pane `id` rang. Its tab carries a dot until it is picked, unless the person is looking at it now (the
 *  window has focus, the panel shows, the tab is in front), as a TERMINALS row does. Nothing it printed is kept. */
export function ringPane(id: number): void {
  const tab = tabOfPane(id);
  if (!tab || tab.rang) return;
  if (windowWatched() && state.open && state.active === tab.key) return;
  set({ tabs: state.tabs.map((t) => (t.key === tab.key ? { ...t, rang: true } : t)) });
}

/** The tab in front is seen (the panel came back into view, the window got focus again). */
export function seenTerminalTab(): void {
  const tabs = clearRing(state.tabs, state.active);
  if (tabs !== state.tabs) set({ tabs });
}

/** Ctrl+`: show the panel (opening a first tab when there is none) and give it the keyboard, or hide it. Hiding stops
 *  nothing: the shells keep running and keep their scrollback. */
export function toggleTerminal(): void {
  if (state.open) {
    set({ open: false });
    return;
  }
  if (!state.tabs.length) addTerminalTab();
  else set({ open: true, mounted: true, tabs: clearRing(state.tabs, state.active), focus: state.focus + 1 });
}

/** The last part of a folder's path, for a tab's title ("~" for none yet). */
export function leafName(path: string | null): string {
  if (!path) return "~";
  const parts = path.replace(/[\\/]+$/, "").split(/[\\/]/);
  return parts[parts.length - 1] || path;
}

/** Tests: start from nothing. */
export function resetTermPanel(): void {
  state = { open: false, mounted: false, tabs: [], active: null, cwd: null, focus: 0 };
  nextKey = 0;
  nextPane = 0;
  for (const fn of listeners) fn();
}
