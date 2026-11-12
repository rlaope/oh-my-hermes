// Accounts rules, pure so vitest pins them: row names, plan words, the usage line, the in-use account, and the
// fill-first auto-switch with its reset-first choice, and the notice before unused quota lapses.
// The reset-first choice follows the idea of spending the quota that resets soonest first from yetone/magpie
// (commit 5e933e153a87c4017a19502e1d2e87aa714572b9, MIT): concept only, reimplemented here against omher's own code.
import type { Account, AccountCli, AccountGroup, UsageProvider } from "../../lib/protocol";
import { clock, limitName } from "../../sidebar/usageFormat";
import type { LoginStatus } from "./native";
import { t } from "../../i18n";

export const CLIS: AccountCli[] = ["claude", "codex", "pi", "omp", "grok", "gemini"];
export const CLI_NAME: Record<AccountCli, string> = {
  claude: "Claude Code",
  codex: "Codex",
  pi: "pi",
  omp: "oh-my-pi",
  grok: "Grok",
  gemini: "Gemini CLI",
};
/** How another subscription is added: the app runs the CLI's own sign-in (`run`), or a session of the CLI is
 *  opened with the account's home and the person types /login (`session`). Grok and Gemini: not yet. */
export const SIGN_IN: Record<AccountCli, "run" | "session" | null> = {
  claude: "run",
  codex: "run",
  pi: "session",
  omp: "session",
  grok: null,
  gemini: null,
};


/** "max_20x" -> "Max 20x", "pro" -> "Pro", "chatgpt" -> "" (a login method is not a plan). */
export function planName(plan?: string | null): string {
  if (!plan) return "";
  const p = plan.trim().toLowerCase();
  if (!p || p === "chatgpt" || p === "api_key" || p === "claude.ai") return "";
  return p
    .split(/[_\s-]+/)
    .filter(Boolean)
    .map((w, i) => (i === 0 ? w.charAt(0).toUpperCase() + w.slice(1) : w))
    .join(" ");
}

/** The row's title is who the login is: the full email (this is the owner's own computer). Without a known email:
 *  the CLI's own login is "This computer", an added one its label, else "Account n". */
export function rowTitle(a: Account, index: number): string {
  if (a.email) return a.email;
  if (a.id === "default") return t("acc.thisComputer");
  if (isCpa(a)) return t("acc.cpaLogin", { n: index + 1 });
  return a.label || t("acc.accountN", { n: index + 1 });
}

const METHOD: Record<string, () => string> = {
  chatgpt: () => t("acc.chatgptLogin"),
  api_key: () => t("acc.apiKey"),
  "claude.ai": () => t("acc.claudeLogin"),
};

/** Where the login lives, the same words for every CLI: "This computer" (the CLI's own) or "Added in omher". When
 *  the title already says "This computer", the login method stands in ("ChatGPT login"). */
export function rowSource(a: Account & { method?: string | null }): string {
  if (a.source === "cpa") return "CLIProxyAPI";
  if (a.id !== "default") return t("acc.addedHere");
  if (a.email) return t("acc.thisComputer");
  return (a.method && METHOD[a.method]?.()) || "";
}

/** The line under the title: the person's own name for the login (when the title is the email or "This computer"),
 *  then source · plan. */
export function rowSub(a: Account & { method?: string | null; plan?: string }): string {
  const named = a.label && (a.email || a.id === "default") ? a.label : "";
  return [named, rowSource(a), a.in_cpa ? t("acc.alsoInCpa") : "", a.plan ?? ""].filter(Boolean).join(" · ");
}

/** A login a local CLIProxyAPI holds (listed from its file name): shown, never used for a session or switched to. */
export const isCpa = (a: Pick<Account, "source">): boolean => a.source === "cpa";

/** What a CLIProxyAPI row says where a usage line would be: nothing on this computer records its usage. */
export const cpaUsage = () => t("acc.noUsageRecord");

/** The name used outside this page (chat line, session menu): label, else the email, else "#n". */
export function accountName(a: Account, index: number): string {
  if (a.label) return a.label;
  if (a.email) return a.email;
  return a.id === "default" ? t("acc.thisComputer") : `#${index + 1}`;
}

/** One line per usage window: "5-hour limit: 62% used · resets 21:00". A % only when the record gave one. */
export function usageLines(u: UsageProvider | null | undefined, now: number): string[] {
  if (!u) return [];
  return u.windows.map((w) => {
    const name = limitName(w.label);
    if (w.stale) return t("acc.noRecent", { name });
    const pct = typeof w.used_percent === "number" ? t("acc.pctUsed", { n: Math.round(w.used_percent) }) : "";
    if (typeof w.resets_at !== "number") return pct ? `${name}: ${pct}` : name;
    const when = clock(w.resets_at, now);
    if (!pct) return u.state === "limited" ? t("acc.limitedUntilOf", { name, when }) : t("acc.resetsOf", { name, when });
    return t("acc.pctResets", { name, pct, when });
  });
}

/** A row with the CLI's status merged in (the status, when the app could ask, wins over the bridge's files). */
export interface Row extends Account {
  plan: string;
  signedIn: boolean;
  method: string | null;
}

export function mergeRow(a: Account, st: LoginStatus | null | undefined): Row {
  const signedIn = st ? st.logged_in : a.state !== "login";
  const state = !signedIn ? "login" : a.state === "login" ? "ready" : a.state;
  return {
    ...a,
    state,
    email: (st?.logged_in && st.email) || a.email,
    plan: planName(st?.plan) || planName(a.usage?.plan),
    signedIn,
    method: st?.method ?? null,
  };
}

/** The pill on a row: "In use" (only when the CLI has two or more logins to choose from), "Limited until 14:00",
 *  "Not signed in", or nothing. */
export function pill(r: Row, inUse: boolean, now: number, logins = 2): string {
  if (!r.signedIn) return t("acc.notSignedIn");
  if (r.state === "limited") return typeof r.resets_at === "number" && r.resets_at > now ? t("acc.limitedUntil", { when: clock(r.resets_at, now) }) : t("acc.limited");
  return inUse && logins > 1 ? t("acc.inUse") : "";
}

/** The account a new session of `cli` starts with, for the SESSIONS agent menu (null: the CLI's own login). */
export function accountForNewSessions(groups: AccountGroup[] | null, cli: AccountCli): Account | null {
  const g = groups?.find((x) => x.cli === cli);
  if (!g) return null;
  return g.accounts.find((a) => a.id === (g.active ?? "default")) ?? null;
}

function limited(a: Account, usage: Record<string, UsageProvider | null | undefined>): boolean {
  return a.state === "limited" || usage[a.id]?.state === "limited";
}

/** How long a usage window is, from its label (\"5 hours\", \"Weekly\", \"2d\", \"3h\"); Infinity for a label we cannot size. */
function windowSeconds(label: string): number {
  if (label === "Weekly") return 7 * 86400;
  const m = /^(\d+)\s*(hours?|h|days?|d)$/i.exec(label.trim());
  if (!m) return Infinity;
  return Number(m[1]) * (m[2].toLowerCase().startsWith("h") ? 3600 : 86400);
}

/** The live resets of an account's usage windows by label: not stale, with a reset time still ahead. */
function liveResets(u: UsageProvider | null | undefined, now: number): Map<string, number> {
  const out = new Map<string, number>();
  for (const w of u?.windows ?? []) {
    if (w.stale || typeof w.resets_at !== "number" || w.resets_at <= now || out.has(w.label)) continue;
    out.set(w.label, w.resets_at);
  }
  return out;
}

export interface NextOptions {
  /** Reset-first: among the accounts fill-first would accept, the one whose limit resets soonest goes first. */
  resetFirst?: boolean;
  /** Seconds since epoch; defaults to the clock. Only reset-first reads it. */
  now?: number;
}

/**
 * Fill-first: when the in-use account is limited, the first signed-in account that is not limited takes over,
 * in list order. Returns null when the in-use one is fine or no other account is ready.
 *
 * With `resetFirst`, the same candidates are ordered by when their limit resets, compared like with like: the
 * shortest window any candidate reports (the 5-hour one for Codex), and only a window that is not stale and
 * resets in the future. A candidate with no such reset keeps its list position after those that have one, so
 * when nothing is comparable the answer is the fill-first one. `soonest` (its reset time) is set only when this
 * picked a different account than list order would.
 */
export function nextAccount(
  accounts: Account[],
  usage: Record<string, UsageProvider | null | undefined> = {},
  activeId?: string | null,
  opts: NextOptions = {},
): { from: number; to: number; soonest?: number } | null {
  const from = accounts.findIndex((a) => (activeId ? a.id === activeId : a.state === "active"));
  if (from < 0) return null;
  if (!limited(accounts[from], usage)) return null;
  const ready: number[] = [];
  accounts.forEach((a, i) => {
    if (i !== from && a.state === "ready" && !isCpa(a) && !limited(a, usage)) ready.push(i);
  });
  if (ready.length === 0) return null;
  if (!opts.resetFirst) return { from, to: ready[0] };
  const now = opts.now ?? Date.now() / 1000;
  const resets = ready.map((i) => liveResets(usage[accounts[i].id] ?? accounts[i].usage, now));
  let label: string | null = null;
  for (const m of resets) {
    for (const l of m.keys()) if (label === null || windowSeconds(l) < windowSeconds(label)) label = l;
  }
  let best = -1;
  let bestAt = Infinity;
  if (label !== null) {
    resets.forEach((m, k) => {
      const at = m.get(label as string);
      if (at !== undefined && at < bestAt) {
        best = k;
        bestAt = at;
      }
    });
  }
  if (best <= 0) return { from, to: ready[0] };
  return { from, to: ready[best], soonest: bestAt };
}

/** One account's quota about to lapse unused: `key` is the account and the reset time, so it is told once. */
export interface LapseNotice {
  key: string;
  index: number;
  percent: number;
  resets_at: number;
}

export const LAPSE_WITHIN_S = 60 * 60;
export const LAPSE_UNDER_PERCENT = 50;

/**
 * Windows that reset within the hour with under half used, for signed-in accounts of `cli` that are not in
 * `seen`. Only a window that reports both a percentage and a reset time counts (Codex today; Claude Code gives
 * no percentage), and not a stale one. One notice per account (its soonest such window).
 */
export function lapseNotices(cli: AccountCli, accounts: Account[], now: number, seen: ReadonlySet<string>): LapseNotice[] {
  const out: LapseNotice[] = [];
  accounts.forEach((a, index) => {
    if (isCpa(a) || a.state === "login") return;
    let best: LapseNotice | null = null;
    for (const w of a.usage?.windows ?? []) {
      if (w.stale || typeof w.used_percent !== "number" || typeof w.resets_at !== "number") continue;
      if (w.resets_at <= now || w.resets_at - now > LAPSE_WITHIN_S || w.used_percent >= LAPSE_UNDER_PERCENT) continue;
      if (!best || w.resets_at < best.resets_at) best = { key: `${cli}:${a.id}:${w.resets_at}`, index, percent: w.used_percent, resets_at: w.resets_at };
    }
    if (best && !seen.has(best.key)) out.push(best);
  });
  return out;
}

/** "Switched Codex to Work (limit on This computer, resets 14:00)": the one quiet line in the bot chat. */
export function switchNote(g: AccountGroup, from: number, to: number, now: number, soonest?: number): string {
  const a = g.accounts[from];
  const b = g.accounts[to];
  const reset = typeof a.resets_at === "number" && a.resets_at > now ? t("acc.resetsAt", { when: clock(a.resets_at, now) }) : "";
  const args = { cli: CLI_NAME[g.cli], to: accountName(b, to), from: accountName(a, from), reset };
  // reset-first picked it over an earlier account in the list: say why
  return typeof soonest === "number" ? t("acc.switchedByReset", { ...args, when: clock(soonest, now) }) : t("acc.switched", args);
}

/** Per-CLI auto-switch, on unless turned off (saved on this computer). */
export function autoSwitchOn(cli: AccountCli, store: Pick<Storage, "getItem"> | undefined = globalThis.localStorage): boolean {
  try {
    const raw = store?.getItem("omher.autoswitch");
    const off = raw ? (JSON.parse(raw) as Record<string, boolean>) : {};
    return off[cli] !== false;
  } catch {
    return true;
  }
}

export function setAutoSwitch(cli: AccountCli, on: boolean): void {
  try {
    const raw = localStorage.getItem("omher.autoswitch");
    const cur = raw ? (JSON.parse(raw) as Record<string, boolean>) : {};
    localStorage.setItem("omher.autoswitch", JSON.stringify({ ...cur, [cli]: on }));
  } catch {
    /* no storage */
  }
}

/** Per-CLI reset-first choice, off unless turned on (saved on this computer, beside `omher.autoswitch`). */
export function resetFirstOn(cli: AccountCli, store: Pick<Storage, "getItem"> | undefined = globalThis.localStorage): boolean {
  try {
    const raw = store?.getItem("omher.resetfirst");
    const on = raw ? (JSON.parse(raw) as Record<string, boolean>) : {};
    return on[cli] === true;
  } catch {
    return false;
  }
}

export function setResetFirst(cli: AccountCli, on: boolean): void {
  try {
    const raw = localStorage.getItem("omher.resetfirst");
    const cur = raw ? (JSON.parse(raw) as Record<string, boolean>) : {};
    localStorage.setItem("omher.resetfirst", JSON.stringify({ ...cur, [cli]: on }));
  } catch {
    /* no storage */
  }
}

/** Groups to show (on this computer, or holding added accounts) and the names of the rest. */
export function splitGroups(
  groups: AccountGroup[],
  onComputer: Partial<Record<AccountCli, boolean>> | null,
): { shown: AccountGroup[]; missing: string[] } {
  const shown: AccountGroup[] = [];
  const missing: string[] = [];
  for (const g of groups) {
    const here = onComputer?.[g.cli] ?? g.installed;
    if (here || g.accounts.length > 1) shown.push(g);
    else missing.push(CLI_NAME[g.cli]);
  }
  return { shown, missing };
}
