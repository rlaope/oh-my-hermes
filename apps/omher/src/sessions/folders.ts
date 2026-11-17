// TERMINALS folder groups, Orca-style (owner, 2026-11-16 "사이드바 세션 쪽에 폴더 orca마냥"): each folder header
// collapses and expands its sessions, the whole list collapses or expands at once, headers reorder by drag, and a
// session opened inside a collapsed folder opens that folder (reveal). Kept on this computer (localStorage
// `omher.term.folders`), never in Hermes. The pure helpers below carry the rules; `useTermFolders` is the store.
import { useSyncExternalStore } from "react";

export const FOLDERS_KEY = "omher.term.folders";

export interface FolderPrefs {
  /** folders (cwd) whose sessions are hidden under their header */
  collapsed: string[];
  /** folders in the order the person dragged them into; folders not named here follow in their own order */
  order: string[];
}

const EMPTY: FolderPrefs = { collapsed: [], order: [] };
const MAX = 200;

export function parseFolderPrefs(raw: string | null): FolderPrefs {
  try {
    const v = JSON.parse(raw ?? "null") as Partial<FolderPrefs> | null;
    const list = (x: unknown) => (Array.isArray(x) ? [...new Set(x.filter((s): s is string => typeof s === "string"))].slice(0, MAX) : []);
    return { collapsed: list(v?.collapsed), order: list(v?.order) };
  } catch {
    return EMPTY;
  }
}

/** `groups` in the saved order: named folders first as saved, the rest after them as they came. */
export function orderFolders<T extends { cwd: string }>(groups: readonly T[], order: readonly string[]): T[] {
  const at = new Map(order.map((c, i) => [c, i]));
  return groups
    .map((g, i) => ({ g, i }))
    .sort((a, b) => (at.get(a.g.cwd) ?? order.length + a.i) - (at.get(b.g.cwd) ?? order.length + b.i))
    .map((x) => x.g);
}

/** Move folder `cwd` to place `to` among `shown` (the folders as the list shows them now). */
export function moveFolder(shown: readonly string[], cwd: string, to: number): string[] {
  const rest = shown.filter((c) => c !== cwd);
  const i = Math.max(0, Math.min(rest.length, to));
  return [...rest.slice(0, i), cwd, ...rest.slice(i)];
}

export function toggleFolder(p: FolderPrefs, cwd: string, collapsed?: boolean): FolderPrefs {
  const on = collapsed ?? !p.collapsed.includes(cwd);
  const rest = p.collapsed.filter((c) => c !== cwd);
  return { ...p, collapsed: on ? [...rest, cwd] : rest };
}

/** Collapse every folder in `all` (true) or open them all (false). */
export function setAllFolders(p: FolderPrefs, all: readonly string[], collapsed: boolean): FolderPrefs {
  return { ...p, collapsed: collapsed ? [...new Set([...p.collapsed, ...all])] : p.collapsed.filter((c) => !all.includes(c)) };
}

/** Every folder of `all` but `keep` collapsed, `keep` open. */
export function collapseOthers(p: FolderPrefs, all: readonly string[], keep: string): FolderPrefs {
  return toggleFolder(setAllFolders(p, all.filter((c) => c !== keep), true), keep, false);
}

export const allCollapsed = (p: FolderPrefs, all: readonly string[]): boolean => all.length > 0 && all.every((c) => p.collapsed.includes(c));

/** A collapsed folder's header summary: how many sessions, whether one prints output now, whether one waits on the
 *  person (it rang), whether one failed. */
export interface FolderSummary {
  count: number;
  busy: boolean;
  needs: boolean;
  failed: boolean;
}
export function folderSummary(statuses: readonly ("busy" | "bell" | "ok" | "err" | null)[]): FolderSummary {
  return { count: statuses.length, busy: statuses.includes("busy"), needs: statuses.includes("bell"), failed: statuses.includes("err") };
}

// ---- the store --------------------------------------------------------------------------------------------------

let prefs: FolderPrefs = EMPTY;
let loaded = false;
const listeners = new Set<() => void>();

function load(): FolderPrefs {
  if (!loaded) {
    loaded = true;
    try {
      prefs = parseFolderPrefs(localStorage.getItem(FOLDERS_KEY));
    } catch {
      prefs = EMPTY;
    }
  }
  return prefs;
}

export function getFolderPrefs(): FolderPrefs {
  return load();
}

export function setFolderPrefs(next: FolderPrefs): void {
  load();
  if (next === prefs) return;
  prefs = next;
  try {
    localStorage.setItem(FOLDERS_KEY, JSON.stringify(prefs));
  } catch {
    /* no storage */
  }
  for (const fn of listeners) fn();
}

/** Open folder `cwd` if it is collapsed (a session in it was opened: reveal its row). */
export function revealFolder(cwd: string): void {
  if (load().collapsed.includes(cwd)) setFolderPrefs(toggleFolder(prefs, cwd, false));
}

const subscribe = (fn: () => void) => {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
};

export function useFolderPrefs(): FolderPrefs {
  return useSyncExternalStore(subscribe, getFolderPrefs, getFolderPrefs);
}
