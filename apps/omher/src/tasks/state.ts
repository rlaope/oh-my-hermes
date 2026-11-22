// The Tasks page's own state, kept apart from the app store: which source, repository, kind, filter and page it
// shows, whether the sidebar shows the Tasks row, and the repositories the person used (newest first). Saved on this
// computer in `omher.tasks` (no token, no item text: only these words). The GitHub accounts the person chose in
// Settings › Accounts (host, login and a colour: never a token) are kept here too, as omher's own setting; gh's own
// config is never written.
import { useSyncExternalStore } from "react";
import type { ChosenAccount, CliSource, TaskFilter, TaskKind, TaskSource } from "./types";
import { FILTERS, KINDS, SOURCES, accountId, accountIdOk, repoOk } from "./types";

/** The colours an account's dot can take, in the order new accounts get them. */
export const ACCOUNT_COLORS: readonly string[] = ["#4c8dff", "#f2994a", "#3fb68b", "#b07cff", "#e5534b", "#d4a72c"];

export type TaskScope = "repo" | "me";
export type MeGroup = "section" | "repo";

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
  /** "이 저장소" (one repository) or "나" (me, across repositories) */
  scope: TaskScope;
  /** the "나" list grouped by section or by repository */
  group: MeGroup;
  /** the "나" account chip: "all" or one chosen account's id */
  meAccount: string;
  /** the mentions section is open (closed by default) */
  mentionsOpen: boolean;
  /** the GitHub accounts chosen in Settings › Accounts (host, login, colour) */
  accounts: ChosenAccount[];
  /** "이 저장소" on GitHub: the chosen account it reads as (null: picked for the repository, else gh's active one) */
  repoAccount: string | null;
}

const KEY = "omher.tasks";

function fresh(): TasksState {
  return {
    source: "github",
    repo: { github: "", gitlab: "" },
    kind: "issues",
    filter: "open",
    page: 0,
    bar: true,
    recent: { github: [], gitlab: [] },
    folders: {},
    scope: "repo",
    group: "section",
    meAccount: "all",
    mentionsOpen: false,
    accounts: [],
    repoAccount: null,
  };
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
    if (v.scope === "me") s.scope = "me";
    if (v.group === "repo") s.group = "repo";
    if (v.mentionsOpen === true) s.mentionsOpen = true;
    if (Array.isArray(v.accounts))
      for (const a of v.accounts.slice(0, 12)) {
        if (!a || typeof a.host !== "string" || typeof a.login !== "string" || !accountIdOk(accountId(a))) continue;
        if (s.accounts.some((x) => accountId(x) === accountId(a))) continue;
        s.accounts.push({ host: a.host, login: a.login, color: ACCOUNT_COLORS.includes(a.color) ? a.color : ACCOUNT_COLORS[s.accounts.length % ACCOUNT_COLORS.length] });
      }
    const ids = s.accounts.map(accountId);
    if (typeof v.meAccount === "string" && ids.includes(v.meAccount)) s.meAccount = v.meAccount;
    if (typeof v.repoAccount === "string" && ids.includes(v.repoAccount)) s.repoAccount = v.repoAccount;
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

export function setScope(scope: TaskScope) {
  if (scope !== state.scope) set({ scope });
}
export function setGroup(group: MeGroup) {
  set({ group });
}
/** The "나" chip: "all" or one chosen account. */
export function setMeAccount(id: string) {
  if (id === "all" || state.accounts.some((a) => accountId(a) === id)) set({ meAccount: id });
}
export function setMentionsOpen(open: boolean) {
  set({ mentionsOpen: open });
}
/** "이 저장소": read as this chosen account (null: the automatic pick). */
export function setRepoAccount(id: string | null) {
  if (id === null || state.accounts.some((a) => accountId(a) === id)) set({ repoAccount: id, page: 0 });
}

/** Choose a GitHub account gh is signed in to (Settings › Accounts › GitHub "Add"); it gets the next free colour. */
export function chooseAccount(a: { host: string; login: string }) {
  const id = accountId(a);
  if (!accountIdOk(id) || state.accounts.some((x) => accountId(x) === id)) return false;
  const used = new Set(state.accounts.map((x) => x.color));
  const color = ACCOUNT_COLORS.find((c) => !used.has(c)) ?? ACCOUNT_COLORS[state.accounts.length % ACCOUNT_COLORS.length];
  set({ accounts: [...state.accounts, { host: a.host, login: a.login, color }] });
  return true;
}

/** Remove a chosen account (only from omher's list: gh keeps its login). */
export function removeAccount(id: string) {
  const accounts = state.accounts.filter((a) => accountId(a) !== id);
  set({ accounts, meAccount: state.meAccount === id ? "all" : state.meAccount, repoAccount: state.repoAccount === id ? null : state.repoAccount });
}

/** The account's dot takes the next colour. */
export function cycleAccountColor(id: string) {
  set({
    accounts: state.accounts.map((a) => (accountId(a) === id ? { ...a, color: ACCOUNT_COLORS[(ACCOUNT_COLORS.indexOf(a.color) + 1) % ACCOUNT_COLORS.length] } : a)),
  });
}

/** Tests: start from nothing. */
export function resetTasks() {
  state = fresh();
  if (typeof localStorage !== "undefined") localStorage.removeItem(KEY);
  for (const fn of listeners) fn();
}
