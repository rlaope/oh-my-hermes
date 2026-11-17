// The Tasks page's own state, kept apart from the app store: which source, repository, kind, filter and page it
// shows, whether the sidebar shows the Tasks row, and the repositories the person used (newest first). Saved on this
// computer in `omher.tasks` (no token, no item text: only these words).
import { useSyncExternalStore } from "react";
import type { CliSource, TaskFilter, TaskKind, TaskSource } from "./types";
import { FILTERS, KINDS, SOURCES, repoOk } from "./types";

export interface TasksState {
  source: TaskSource;
  /** per CLI source: the repository shown */
  repo: Record<CliSource, string>;
  kind: TaskKind;
  filter: TaskFilter;
  page: number;
  /** the Tasks row in the sidebar (right-click › Hide from sidebar; Settings › General shows it again) */
  bar: boolean;
  /** repositories used, newest first, per CLI source (at most 8) */
  recent: Record<CliSource, string[]>;
  /** repository -> the folder on this computer it was found in (a cloned repository: \"Open terminal here\") */
  folders: Record<string, string>;
}

const KEY = "omher.tasks";

function fresh(): TasksState {
  return { source: "github", repo: { github: "", gitlab: "" }, kind: "issues", filter: "open", page: 0, bar: true, recent: { github: [], gitlab: [] }, folders: {} };
}

function read(): TasksState {
  const s = fresh();
  try {
    const raw = typeof localStorage !== "undefined" ? localStorage.getItem(KEY) : null;
    const v = raw ? (JSON.parse(raw) as Partial<TasksState>) : {};
    if (v.source && SOURCES.includes(v.source)) s.source = v.source;
    if (v.kind && KINDS.includes(v.kind)) s.kind = v.kind;
    if (v.filter && FILTERS.includes(v.filter)) s.filter = v.filter;
    if (v.bar === false) s.bar = false;
    for (const src of ["github", "gitlab"] as const) {
      const r = v.repo?.[src];
      if (typeof r === "string" && repoOk(src, r)) s.repo[src] = r;
      const rec = v.recent?.[src];
      if (Array.isArray(rec)) s.recent[src] = rec.filter((x): x is string => typeof x === "string" && repoOk(src, x)).slice(0, 8);
    }
    if (v.folders && typeof v.folders === "object")
      for (const [k, f] of Object.entries(v.folders)) if (typeof f === "string" && f.startsWith("/")) s.folders[k] = f;
  } catch {
    // a broken record starts fresh
  }
  return s;
}

let state: TasksState = read();
const listeners = new Set<() => void>();

function save() {
  if (typeof localStorage === "undefined") return;
  const { page: _p, ...keep } = state;
  localStorage.setItem(KEY, JSON.stringify(keep));
}

function set(patch: Partial<TasksState>) {
  state = { ...state, ...patch };
  save();
  for (const fn of listeners) fn();
}

export const getTasks = () => state;
export function subscribeTasks(fn: () => void) {
  listeners.add(fn);
  return () => void listeners.delete(fn);
}
export const useTasks = () => useSyncExternalStore(subscribeTasks, getTasks, getTasks);

export function setSource(source: TaskSource) {
  if (source !== state.source) set({ source, page: 0 });
}
export function setKind(kind: TaskKind) {
  set({ kind, page: 0 });
}
export function setFilter(filter: TaskFilter) {
  set({ filter, page: 0 });
}
export function setPage(page: number) {
  set({ page: Math.max(0, page) });
}
export function setBar(bar: boolean) {
  set({ bar });
}

/** Show `repo` for `source` (checked; a bad name is ignored) and keep it first in the recent list. `folder`: where
 *  it is cloned on this computer, when known. */
export function setRepo(source: CliSource, repo: string, folder?: string | null) {
  const r = repo.trim();
  if (!repoOk(source, r)) return false;
  const recent = { ...state.recent, [source]: [r, ...state.recent[source].filter((x) => x !== r)].slice(0, 8) };
  const folders = folder ? { ...state.folders, [`${source}:${r}`]: folder } : state.folders;
  set({ repo: { ...state.repo, [source]: r }, recent, folders, page: state.repo[source] === r ? state.page : 0 });
  return true;
}

/** Tests: start from nothing. */
export function resetTasks() {
  state = fresh();
  if (typeof localStorage !== "undefined") localStorage.removeItem(KEY);
  for (const fn of listeners) fn();
}
