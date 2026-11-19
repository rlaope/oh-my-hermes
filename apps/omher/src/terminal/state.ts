// The bottom terminal panel's state, kept apart from the panel's UI so the app's shortcut and the thread view can
// reach it without loading xterm: whether it shows, its tabs (one login shell each), which tab is in front, and the
// folder a new tab starts in.
//
// `setTerminalCwd(path | null)` is the hook the thread view calls with the open thread's folder (null: none, the
// shell starts at home). It changes where the NEXT tab starts; a running shell keeps its own folder.
//
// The tabs (each one's folder) are kept on this computer (`omher.termpanel.tabs`) and come back after omher restarts,
// hidden: the next time the panel shows, each starts a fresh login shell in its folder, with what it showed before
// written back first (term/history.ts, key `panel-<n>`).
import { useSyncExternalStore } from "react";

export interface TermTab {
  /** the panel's own key for the tab (not the shell's session id) */
  key: number;
  /** the folder asked for when the tab opened (null: home) */
  want: string | null;
  /** the folder the shell started in, once it has */
  cwd: string | null;
  /** the CLI in the shell's foreground (`session-fg`), null for the shell itself */
  fg?: string | null;
  /** put back after omher restarted: what it showed before is written into it first */
  restored?: boolean;
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
  /** bumped each time the panel opens or a tab is picked: the tab in front takes the keyboard */
  focus: number;
}

export const TABS_KEY = "omher.termpanel.tabs";
const MAX_TABS = 20;

/** The saved tabs: `{tabs: [{key, cwd}], active}`, checked; nothing when it is missing or malformed. */
export function parseSavedTabs(raw: string | null): { tabs: TermTab[]; active: number | null } {
  let v: unknown;
  try {
    v = raw ? JSON.parse(raw) : null;
  } catch {
    v = null;
  }
  const o = v && typeof v === "object" && !Array.isArray(v) ? (v as { tabs?: unknown; active?: unknown }) : {};
  const tabs: TermTab[] = [];
  for (const t of Array.isArray(o.tabs) ? o.tabs : []) {
    const key = (t as { key?: unknown })?.key;
    const cwd = (t as { cwd?: unknown })?.cwd;
    if (typeof key !== "number" || !Number.isInteger(key) || key < 1 || key > 999_999_999 || tabs.some((x) => x.key === key)) continue;
    const want = typeof cwd === "string" && cwd.startsWith("/") && cwd.length <= 4096 ? cwd : typeof cwd === "string" && /^[A-Za-z]:[\\/]/.test(cwd) && cwd.length <= 4096 ? cwd : null;
    tabs.push({ key, want, cwd: null, restored: true });
    if (tabs.length >= MAX_TABS) break;
  }
  const active = typeof o.active === "number" && tabs.some((t) => t.key === o.active) ? o.active : (tabs[0]?.key ?? null);
  return { tabs, active };
}

function readSaved(): { tabs: TermTab[]; active: number | null } {
  try {
    return parseSavedTabs(typeof localStorage !== "undefined" ? localStorage.getItem(TABS_KEY) : null);
  } catch {
    return { tabs: [], active: null };
  }
}

function save(): void {
  try {
    if (typeof localStorage === "undefined") return;
    if (!state.tabs.length) localStorage.removeItem(TABS_KEY);
    else localStorage.setItem(TABS_KEY, JSON.stringify({ tabs: state.tabs.map((t) => ({ key: t.key, cwd: t.cwd ?? t.want })), active: state.active }));
  } catch {
    /* no storage */
  }
}

const saved0 = readSaved();
let state: TermPanelState = { open: false, mounted: false, tabs: saved0.tabs, active: saved0.active, cwd: null, focus: 0 };
let nextKey = saved0.tabs.reduce((m, t) => Math.max(m, t.key), 0);
const listeners = new Set<() => void>();

function set(patch: Partial<TermPanelState>): void {
  const before = state.tabs;
  const was = state.active;
  state = { ...state, ...patch };
  if (state.tabs !== before || state.active !== was) save();
  for (const fn of listeners) fn();
}

/** The history keys of the tabs put back at load (`panel-<n>`): their kept text survives the startup prune. */
export const savedPanelKeys = (): string[] => state.tabs.filter((t) => t.restored).map((t) => `panel-${t.key}`);

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

/** A new tab (a new login shell) in the folder setTerminalCwd last named, in front. */
export function addTerminalTab(): void {
  const tab: TermTab = { key: ++nextKey, want: state.cwd, cwd: null };
  set({ tabs: [...state.tabs, tab], active: tab.key, open: true, mounted: true, focus: state.focus + 1 });
}

/** Close a tab: its shell is stopped. The last one closing hides the panel. */
export function closeTerminalTab(key: number): void {
  const at = state.tabs.findIndex((t) => t.key === key);
  if (at < 0) return;
  const tabs = state.tabs.filter((t) => t.key !== key);
  const active = state.active !== key ? state.active : (tabs[Math.min(at, tabs.length - 1)]?.key ?? null);
  set({ tabs, active, open: tabs.length ? state.open : false, focus: state.focus + 1 });
}

export function pickTerminalTab(key: number): void {
  if (!state.tabs.some((t) => t.key === key)) return;
  set({ active: key, focus: state.focus + 1 });
}

/** The shell of tab `key` started in `cwd`. */
/** The CLI in tab `key`'s foreground (the shell's `session-fg` event), null when the shell itself is in front. */
export function setTabFg(key: number, fg: string | null): void {
  const tab = state.tabs.find((t) => t.key === key);
  if (!tab || (tab.fg ?? null) === fg) return;
  set({ tabs: state.tabs.map((t) => (t.key === key ? { ...t, fg } : t)) });
}

export function setTabCwd(key: number, cwd: string): void {
  if (!state.tabs.some((t) => t.key === key)) return;
  set({ tabs: state.tabs.map((t) => (t.key === key ? { ...t, cwd } : t)) });
}

/** Ctrl+`: show the panel (opening a first tab when there is none) and give it the keyboard, or hide it. Hiding stops
 *  nothing: the shells keep running and keep their scrollback. */
export function toggleTerminal(): void {
  if (state.open) {
    set({ open: false });
    return;
  }
  if (!state.tabs.length) addTerminalTab();
  else set({ open: true, mounted: true, focus: state.focus + 1 });
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
  save();
  for (const fn of listeners) fn();
}
