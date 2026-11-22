// Tasks › 나 (Me): what the page does with the shell's answers (src-tauri/src/gh_me.rs). The pure part (attention order,
// sorting, grouping, the status chips, the sidebar badge, the account picked for a repository) and the lists kept for
// each chosen GitHub account: read when the page opens, on window focus, on ⟳ and every 5 minutes while omher runs.
// Read-only (BOUNDARY rule 33): nothing here writes to GitHub.
import { useSyncExternalStore } from "react";
import { taskHost, MeFail } from "./host";
import { getTasks, subscribeTasks } from "./state";
import { ME_SECTIONS, accountId, type ChosenAccount, type GhAccount, type GhAccounts, type MeFailKind, type MeItem, type MeSection } from "./types";

/** A row of the "나" list: an item, the account it was read as and the section it came from. */
export interface MeRow extends MeItem {
  account: string;
  section: MeSection;
}

/** How much an item needs me now: 0 its CI failed, 1 changes were requested, 2 it has a merge conflict, 3 my review is
 *  asked for, 4 the rest (gh_me.rs `attention`, the same order). */
export function attention(i: MeItem): number {
  if (i.ci === "failed") return 0;
  if (i.review === "changes") return 1;
  if (i.conflict) return 2;
  if (i.asked) return 3;
  return 4;
}

const waited = (i: MeItem) => i.requested || i.created;

/** Items needing action first; review requests oldest first (waited longest); the rest newest first. */
export function sortMe<T extends MeItem>(items: readonly T[]): T[] {
  return [...items].sort((a, b) => {
    const x = attention(a);
    const y = attention(b);
    if (x !== y) return x - y;
    const t = x === 3 ? waited(a) - waited(b) : b.updated - a.updated;
    return t || a.repo.localeCompare(b.repo) || a.number - b.number;
  });
}

/** The rows grouped for the page: by section (in ME_SECTIONS order, every section listed even when empty) or by
 *  repository (each item once, the repositories with the most urgent row first). */
export function groupRows(rows: readonly MeRow[], by: "section" | "repo"): { key: string; rows: MeRow[] }[] {
  if (by === "section") return ME_SECTIONS.map((sec) => ({ key: sec, rows: sortMe(rows.filter((r) => r.section === sec)) }));
  const seen = new Set<string>();
  const byRepo = new Map<string, MeRow[]>();
  for (const r of rows) {
    const k = `${r.account}\0${r.repo}#${r.number}`;
    if (seen.has(k)) continue;
    seen.add(k);
    byRepo.set(r.repo, [...(byRepo.get(r.repo) ?? []), r]);
  }
  const groups = [...byRepo].map(([key, rs]) => ({ key, rows: sortMe(rs) }));
  return groups.sort((a, b) => attention(a.rows[0]) - attention(b.rows[0]) || a.key.localeCompare(b.key));
}

export type ChipTone = "ok" | "fail" | "pending" | "warn" | "quiet";
export interface Chip {
  /** what it says (an i18n key's word, see MeView) */
  kind: "draft" | "ciPassed" | "ciFailed" | "ciPending" | "approved" | "changes" | "conflict" | "waiting";
  tone: ChipTone;
}

/** The status chips of a row, in the order they show. */
export function chipsFor(i: MeItem): Chip[] {
  const out: Chip[] = [];
  if (i.draft || i.state === "draft") out.push({ kind: "draft", tone: "quiet" });
  if (i.ci === "failed") out.push({ kind: "ciFailed", tone: "fail" });
  else if (i.ci === "pending") out.push({ kind: "ciPending", tone: "pending" });
  else if (i.ci === "passed") out.push({ kind: "ciPassed", tone: "ok" });
  if (i.review === "changes") out.push({ kind: "changes", tone: "fail" });
  else if (i.review === "approved") out.push({ kind: "approved", tone: "ok" });
  if (i.conflict) out.push({ kind: "conflict", tone: "warn" });
  if (i.asked) out.push({ kind: "waiting", tone: "quiet" });
  return out;
}

/** When a review request started waiting (seconds). */
export const waitingSince = (i: MeItem) => waited(i);

/** The accounts the "나" list shows: the chip's one, else every chosen account. */
export function shownAccounts(accounts: readonly ChosenAccount[], chip: string): string[] {
  const ids = accounts.map(accountId);
  return chip !== "all" && ids.includes(chip) ? [chip] : ids;
}

/** The sidebar badge: review requests summed over `ids` (an account that failed adds nothing). */
export function reviewBadge(lists: Readonly<Record<string, AccountLists>>, ids: readonly string[]): number {
  return ids.reduce((n, id) => n + (lists[id]?.sections.review?.items.length ?? 0), 0);
}

/** The chosen accounts on the repository's host (a GitHub Enterprise account never reads a github.com repository). */
export const accountsOnHost = (accounts: readonly ChosenAccount[], host = "github.com") => accounts.filter((a) => a.host === host);

/** "이 저장소": the chosen account to read `owner`'s repository (on `host`) as. The person's own pick when it is still
 *  chosen and on that host; else the chosen account on that host whose login is the owner; else none (gh's active
 *  account). Organisations are not looked up. */
export function pickRepoAccount(accounts: readonly ChosenAccount[], picked: string | null, owner: string, host = "github.com"): string | null {
  const here = accountsOnHost(accounts, host);
  if (picked && here.some((a) => accountId(a) === picked)) return picked;
  const own = here.find((a) => a.login.toLowerCase() === owner.toLowerCase());
  return own ? accountId(own) : null;
}

/** A chosen account as gh lists it now: `ok`, `relogin` (gh says its login fails, or no longer lists it). */
export function accountState(a: ChosenAccount, detected: GhAccounts | null): "ok" | "relogin" | "unknown" {
  if (!detected) return "unknown";
  const g = detected.accounts.find((x: GhAccount) => x.host === a.host && x.login.toLowerCase() === a.login.toLowerCase());
  return g && g.state === "success" ? "ok" : "relogin";
}

// ---- the lists, per account ----------------------------------------------------------------------

export interface SectionList {
  items: MeItem[];
  more: boolean;
  /** the last page read */
  page: number;
}

export interface AccountLists {
  sections: Partial<Record<MeSection, SectionList>>;
  /** the last failure that is not the rate limit (auth: the chip says "sign in again") */
  fail: { kind: Exclude<MeFailKind, "rate">; line: string } | null;
  /** GitHub's rate limit stopped the last read: the page says "try again soon" and keeps what it had */
  rate: boolean;
  loading: boolean;
  /** when it was last read (ms) */
  at: number;
}

interface MeData {
  lists: Record<string, AccountLists>;
  detected: GhAccounts | null;
}

let data: MeData = { lists: {}, detected: null };
const listeners = new Set<() => void>();

function emit() {
  for (const fn of listeners) fn();
}

/** Still one of the chosen accounts (a read that ends after its account was removed changes nothing). */
const chosen = (id: string) => getTasks().accounts.some((a) => accountId(a) === id);

function put(id: string, patch: Partial<AccountLists>) {
  if (!chosen(id)) return;
  const was = data.lists[id] ?? { sections: {}, fail: null, rate: false, loading: false, at: 0 };
  data = { ...data, lists: { ...data.lists, [id]: { ...was, ...patch } } };
  emit();
}

export const getMeData = () => data;
export function subscribeMe(fn: () => void) {
  listeners.add(fn);
  return () => void listeners.delete(fn);
}
export const useMeData = () => useSyncExternalStore(subscribeMe, getMeData, getMeData);

/** Ask gh which accounts it is signed in to (Settings › Accounts and the chips' "sign in again"). */
export async function detectAccounts(fresh = false): Promise<GhAccounts> {
  const got = await taskHost()
    .ghAccounts(fresh)
    .catch(() => ({ installed: false, accounts: [] }) as GhAccounts);
  data = { ...data, detected: got };
  emit();
  return got;
}

/** Read every section of account `id` (page 0), review first (the badge), one call after another. */
export async function readAccount(id: string, fresh = false): Promise<void> {
  if (data.lists[id]?.loading) return;
  put(id, { loading: true });
  const host = taskHost();
  const sections: Partial<Record<MeSection, SectionList>> = { ...data.lists[id]?.sections };
  let fail: AccountLists["fail"] = null;
  let rate = false;
  for (const sec of ME_SECTIONS) {
    try {
      const p = await host.me(id, sec, 0, fresh);
      sections[sec] = { items: p.items, more: p.more, page: 0 };
    } catch (e) {
      const f = e instanceof MeFail ? e : new MeFail("other", e instanceof Error ? e.message : String(e));
      if (f.kind === "rate") rate = true;
      else {
        fail = { kind: f.kind, line: f.message };
        // the account cannot be read: drop what it showed, so no row shows under a login that no longer works
        if (f.kind === "auth") for (const k of ME_SECTIONS) delete sections[k];
        break;
      }
    }
  }
  put(id, { sections, fail, rate, loading: false, at: Date.now() });
}

/** The next page of one section of account `id`, added under what it shows. */
export async function readMore(id: string, sec: MeSection): Promise<void> {
  const cur = data.lists[id]?.sections[sec];
  if (!cur?.more) return;
  try {
    const p = await taskHost().me(id, sec, cur.page + 1);
    const now = data.lists[id]?.sections ?? {};
    // a row that moved up a page while it was read (it was updated) shows once
    const have = new Set(cur.items.map((i) => `${i.repo}#${i.number}`));
    const added = p.items.filter((i) => !have.has(`${i.repo}#${i.number}`));
    put(id, { sections: { ...now, [sec]: { items: [...cur.items, ...added], more: p.more, page: cur.page + 1 } } });
  } catch (e) {
    if (e instanceof MeFail && e.kind === "rate") put(id, { rate: true });
  }
}

/** Read the accounts the "나" chip shows (every chosen one with "모두"). `fresh`: ⟳ asks past the minute's answer. */
export async function refreshMe(fresh = false): Promise<void> {
  const tk = getTasks();
  await Promise.all(shownAccounts(tk.accounts, tk.meAccount).map((id) => readAccount(id, fresh)));
}

/** Forget a removed account's lists. */
export function forgetAccount(id: string) {
  if (!data.lists[id]) return;
  const lists = { ...data.lists };
  delete lists[id];
  data = { ...data, lists };
  emit();
}

/** How often the lists are read again while omher runs. */
export const POLL_MS = 5 * 60_000;
/** A window focus reads again only lists older than this (the shell keeps each answer a minute anyway). */
const FOCUS_GAP_MS = 60_000;

let polling: (() => void) | null = null;

/** Keep the chosen accounts' lists read while omher runs: now, every 5 minutes, and on window focus when older than a
 *  minute. Started once (the sidebar's Tasks row); a second call does nothing. */
export function startMePolling(): () => void {
  if (polling) return polling;
  const tick = () => {
    if (getTasks().accounts.length) void refreshMe();
  };
  const onFocus = () => {
    const tk = getTasks();
    const stale = shownAccounts(tk.accounts, tk.meAccount).filter((id) => Date.now() - (data.lists[id]?.at ?? 0) > FOCUS_GAP_MS);
    for (const id of stale) void readAccount(id);
  };
  tick();
  const h = setInterval(tick, POLL_MS);
  window.addEventListener("focus", onFocus);
  // a chosen account added, or the chip changed: read what is not read yet
  let before = JSON.stringify([getTasks().accounts.map(accountId), getTasks().meAccount]);
  const off = subscribeTasks(() => {
    const now = JSON.stringify([getTasks().accounts.map(accountId), getTasks().meAccount]);
    if (now === before) return;
    before = now;
    const tk = getTasks();
    for (const id of Object.keys(data.lists)) if (!tk.accounts.some((a) => accountId(a) === id)) forgetAccount(id);
    for (const id of shownAccounts(tk.accounts, tk.meAccount)) if (!data.lists[id]) void readAccount(id);
  });
  polling = () => {
    clearInterval(h);
    window.removeEventListener("focus", onFocus);
    off();
    polling = null;
  };
  return polling;
}

/** Tests: start from nothing. */
export function resetMe() {
  polling?.();
  data = { lists: {}, detected: null };
  emit();
}
