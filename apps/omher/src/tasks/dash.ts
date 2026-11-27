// Tasks › GitHub, the dashboard: what the page does with the shell's answers (src-tauri/src/gh_dash.rs). The pure part
// (which account reads a repository, the filter and the tabs, the runs and releases columns, a run's duration, the
// suggested repositories) and the repositories' answers, read when the dashboard opens, on window focus, on ⟳ and every
// 5 minutes while it is open, with the shell keeping each answer a minute. Read-only (BOUNDARY rule 51): nothing here
// writes to GitHub.
import { useSyncExternalStore } from "react";
import { taskHost, MeFail } from "./host";
import { getTasks } from "./state";
import { accountId, type ChosenAccount, type DashRelease, type DashRepo, type DashRun, type DashTab, type MeFailKind, type MeItem, type TaskRemote } from "./types";

/** The chosen account a pinned repository is read as: the github.com account whose login owns it, else the first
 *  github.com account (an organisation's repository is read as the person's first account). None: no github.com
 *  account is chosen. */
export function dashAccount(accounts: readonly ChosenAccount[], repo: string): string | null {
  const gh = accounts.filter((a) => a.host === "github.com");
  const owner = repo.split("/")[0]?.toLowerCase() ?? "";
  const a = gh.find((x) => x.login.toLowerCase() === owner) ?? gh[0];
  return a ? accountId(a) : null;
}

/** The repositories the columns show: every pin, or the one picked. */
export const shownRepos = (pins: readonly string[], pick: string): string[] => (pick !== "all" && pins.includes(pick) ? [pick] : [...pins]);

/** The open pull requests of `repos`, newest update first. */
export function prsOf(data: Readonly<Record<string, RepoState>>, repos: readonly string[]): MeItem[] {
  return repos
    .flatMap((r) => data[r]?.data?.prs ?? [])
    .sort((a, b) => b.updated - a.updated || a.repo.localeCompare(b.repo) || b.number - a.number);
}

/** The rows a tab shows: all of them, or the ones that ask for my review. */
export const inTab = (prs: readonly MeItem[], tab: DashTab): MeItem[] => (tab === "asked" ? prs.filter((p) => p.asked) : [...prs]);

/** How many rows each tab holds. */
export const tabCounts = (prs: readonly MeItem[]): Record<DashTab, number> => ({ all: prs.length, asked: prs.filter((p) => p.asked).length });

/** A run with the repository it belongs to. */
export interface RunRow extends DashRun {
  repo: string;
}

/** The recent runs of `repos`, newest first, at most `max`. */
export function runsOf(data: Readonly<Record<string, RepoState>>, repos: readonly string[], max = 30): RunRow[] {
  return repos
    .flatMap((repo) => (data[repo]?.data?.runs ?? []).map((r) => ({ ...r, repo })))
    .sort((a, b) => (b.created || b.started) - (a.created || a.started) || b.id - a.id)
    .slice(0, max);
}

/** The release commits are counted from: GitHub's Latest, else the newest that is not a pre-release, else the newest
 *  (gh_dash.rs `base_release`, the same order). */
export function baseRelease(releases: readonly DashRelease[]): DashRelease | null {
  return releases.find((r) => r.latest) ?? releases.find((r) => !r.prerelease) ?? releases[0] ?? null;
}

export interface ReleaseRow {
  repo: string;
  release: DashRelease;
  /** commits the default branch has since it (null: not read) */
  ahead: number | null;
  branch: string;
}

/** Each repository's latest release with the commits since, the newest release first. */
export function releasesOf(data: Readonly<Record<string, RepoState>>, repos: readonly string[]): ReleaseRow[] {
  const out: ReleaseRow[] = [];
  for (const repo of repos) {
    const d = data[repo]?.data;
    const release = d ? baseRelease(d.releases) : null;
    if (d && release) out.push({ repo, release, ahead: d.ahead, branch: d.branch });
  }
  return out.sort((a, b) => b.release.published - a.release.published || a.repo.localeCompare(b.repo));
}

/** How long a run took (or has run so far), in seconds; null when it never started. */
export function runSeconds(r: DashRun, nowMs = Date.now()): number | null {
  if (!r.started) return null;
  const end = r.state === "pending" ? Math.floor(nowMs / 1000) : r.updated;
  return end >= r.started ? end - r.started : null;
}

/** "45s", "8m 14s", "1h 2m". */
export function formatDuration(secs: number): string {
  if (secs < 60) return `${secs}s`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m ${secs % 60}s`;
  return `${Math.floor(secs / 3600)}h ${Math.floor((secs % 3600) / 60)}m`;
}

/** The github.com repositories found in folders omher knows, not pinned yet, each once, in the order found. */
export function suggestions(pins: readonly string[], found: readonly (TaskRemote | null)[], max = 8): string[] {
  const out: string[] = [];
  for (const r of found) if (r && r.source === "github" && !pins.includes(r.repo) && !out.includes(r.repo)) out.push(r.repo);
  return out.slice(0, max);
}

// ---- the repositories' answers ---------------------------------------------------------------------

export interface RepoState {
  data: DashRepo | null;
  loading: boolean;
  /** the last failure that is not the rate limit */
  fail: { kind: Exclude<MeFailKind, "rate">; line: string } | null;
  /** GitHub's rate limit stopped the last read (or one of its parts): "try again soon", what was read stays */
  rate: boolean;
  /** when it was last read (ms) */
  at: number;
}

interface DashData {
  repos: Record<string, RepoState>;
  /** repositories found in folders omher knows (suggestions) */
  found: TaskRemote[];
}

let data: DashData = { repos: {}, found: [] };
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((fn) => fn());

function put(repo: string, patch: Partial<RepoState>) {
  if (!getTasks().pins.includes(repo)) return;
  const was = data.repos[repo] ?? { data: null, loading: false, fail: null, rate: false, at: 0 };
  data = { ...data, repos: { ...data.repos, [repo]: { ...was, ...patch } } };
  emit();
}

export const getDash = () => data;
export function subscribeDash(fn: () => void) {
  listeners.add(fn);
  return () => void listeners.delete(fn);
}
export const useDash = () => useSyncExternalStore(subscribeDash, getDash, getDash);

/** Read one pinned repository as its account. A rate limit keeps what it showed; any other failure shows its line. */
export async function readRepo(repo: string, fresh = false): Promise<void> {
  const tk = getTasks();
  const account = dashAccount(tk.accounts, repo);
  if (!account || data.repos[repo]?.loading) return;
  put(repo, { loading: true });
  try {
    const d = await taskHost().dash(account, repo, fresh);
    put(repo, { data: d, loading: false, fail: null, rate: d.rate, at: Date.now() });
  } catch (e) {
    const f = e instanceof MeFail ? e : new MeFail("other", e instanceof Error ? e.message : String(e));
    if (f.kind === "rate") put(repo, { loading: false, rate: true, at: Date.now() });
    else put(repo, { loading: false, fail: { kind: f.kind, line: f.message }, rate: false, at: Date.now(), ...(f.kind === "auth" ? { data: null } : {}) });
  }
}

/** Read every pinned repository (side by side; the shell keeps each answer a minute). `fresh`: ⟳. */
export async function refreshDash(fresh = false): Promise<void> {
  const tk = getTasks();
  // an unpinned repository's answer goes
  const keep = Object.fromEntries(Object.entries(data.repos).filter(([r]) => tk.pins.includes(r)));
  if (Object.keys(keep).length !== Object.keys(data.repos).length) {
    data = { ...data, repos: keep };
    emit();
  }
  await Promise.all(tk.pins.map((r) => readRepo(r, fresh)));
}

/** Look for github.com repositories in `folders` (each folder's `.git/config`, read as a file by the shell). */
export async function findRepos(folders: readonly string[]): Promise<void> {
  const host = taskHost();
  const got = await Promise.all([...new Set(folders)].slice(0, 24).map((f) => host.remote(f).catch(() => null)));
  const found = got.filter((r): r is TaskRemote => !!r && r.source === "github");
  data = { ...data, found };
  emit();
}

/** How often the dashboard reads again while it is open. */
export const POLL_MS = 5 * 60_000;
/** A window focus reads again only repositories older than this. */
const FOCUS_GAP_MS = 60_000;

/** Keep the pinned repositories read while the dashboard is open: now, every 5 minutes, and on window focus when older
 *  than a minute. Returns the stop. */
export function startDashPolling(): () => void {
  void refreshDash();
  const h = setInterval(() => void refreshDash(), POLL_MS);
  const onFocus = () => {
    for (const r of getTasks().pins) if (Date.now() - (data.repos[r]?.at ?? 0) > FOCUS_GAP_MS) void readRepo(r);
  };
  window.addEventListener("focus", onFocus);
  return () => {
    clearInterval(h);
    window.removeEventListener("focus", onFocus);
  };
}

/** Tests: start from nothing. */
export function resetDash() {
  data = { repos: {}, found: [] };
  emit();
}
