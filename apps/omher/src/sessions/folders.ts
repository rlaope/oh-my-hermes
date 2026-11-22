// TERMINALS folder groups, Orca-style (owner, 2026-11-16 "사이드바 세션 쪽에 폴더 orca마냥"): each folder header
// collapses and expands its sessions, the whole list collapses or expands at once, headers reorder by drag, and a
// session opened inside a collapsed folder opens that folder (reveal). A folder the person added from the right-click
// menu ("New folder…") is a group of its own even with no session in it. Kept on this computer (localStorage
// `omher.term.folders`), never in Hermes; omher makes and deletes no folder on disk for it. The pure helpers below carry the rules; `useTermFolders` is the store.
import { useSyncExternalStore } from "react";

export const FOLDERS_KEY = "omher.term.folders";

export interface FolderPrefs {
  /** folders (cwd) whose sessions are hidden under their header */
  collapsed: string[];
  /** folders in the order the person dragged them into; folders not named here follow in their own order */
  order: string[];
  /** folders the person added from the menu: each is listed as a group even while no session runs in it. Absent
   *  while there is none, so a record saved before this field, and one of a person who never adds a folder, read and
   *  save as they always did. Read it through `addedFolders`. */
  added?: string[];
}

const EMPTY: FolderPrefs = { collapsed: [], order: [] };
const NO_ADDED: readonly string[] = [];

/** The folders the person added, newest first (none: the same empty list every time). */
export const addedFolders = (p: FolderPrefs): readonly string[] => p.added ?? NO_ADDED;

/** `p` with `added` as its added folders (no field when there is none). */
function setAdded(p: FolderPrefs, added: string[]): FolderPrefs {
  const { added: _was, ...rest } = p;
  return added.length ? { ...rest, added } : rest;
}
const MAX = 200;

export function parseFolderPrefs(raw: string | null): FolderPrefs {
  try {
    const v = JSON.parse(raw ?? "null") as Partial<FolderPrefs> | null;
    const list = (x: unknown) => (Array.isArray(x) ? [...new Set(x.filter((s): s is string => typeof s === "string"))].slice(0, MAX) : []);
    // `added` is newer than the other two: a record saved before it reads as none added
    return setAdded({ collapsed: list(v?.collapsed), order: list(v?.order) }, list(v?.added).filter((c) => c !== ""));
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

/** The person picked folder `cwd` in "New folder…". A folder already in the list (`listed`: the groups shown now, by
 *  a session or added before) only opens; a new one is added, open, at the top of the saved order. */
export function addFolder(p: FolderPrefs, cwd: string, listed: readonly string[] = []): FolderPrefs {
  if (!cwd) return p;
  const open = p.collapsed.includes(cwd) ? toggleFolder(p, cwd, false) : p;
  if (addedFolders(p).includes(cwd) || listed.includes(cwd)) return open;
  // the folders shown now keep their places under it, named or not
  const order = [...new Set([cwd, ...orderFolders(listed.map((c) => ({ cwd: c })), p.order).map((g) => g.cwd), ...p.order])].slice(0, MAX);
  return setAdded({ ...open, order }, [cwd, ...addedFolders(p)].slice(0, MAX));
}

/** "Remove from list": `cwd` is no longer an added folder. Nothing on disk changes, and while a session runs there
 *  its group stays (sessions make their own group). */
export function removeFolder(p: FolderPrefs, cwd: string): FolderPrefs {
  if (!addedFolders(p).includes(cwd)) return p;
  return setAdded(p, addedFolders(p).filter((c) => c !== cwd));
}

/** `groups` (the folders sessions run in) and, after them, an empty group for each added folder none runs in. */
export function withAdded<T>(groups: readonly { cwd: string; rows: T[] }[], added: readonly string[]): { cwd: string; rows: T[] }[] {
  const have = new Set(groups.map((g) => g.cwd));
  return [...groups, ...added.filter((c) => !have.has(c)).map((cwd) => ({ cwd, rows: [] as T[] }))];
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
