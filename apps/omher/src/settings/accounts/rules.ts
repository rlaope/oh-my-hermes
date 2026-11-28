// Accounts rules, pure so vitest pins them: row names, plan words, the usage line, the in-use account, and the
// fill-first auto-switch with its threshold, headroom and reset-first choice, and the notice before unused quota lapses.
// The reset-first choice follows the idea of spending the quota that resets soonest first from yetone/magpie
// (commit 5e933e153a87c4017a19502e1d2e87aa714572b9, MIT): concept only, reimplemented here against omher's own code.
// The threshold, the headroom, the fresh-reading rule, model-scoped weekly limits and Codex's one switch per five
// minutes follow 2rami/kasaterm (MIT): ideas and numbers only, code written fresh.
import type { Account, AccountCli, AccountGroup, UsageProvider, UsageWindow } from "../../lib/protocol";
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
    // a model's own window says limited by itself (it never limits the account); any other by the account's state
    const lim = w.model ? w.limited === true : u.state === "limited";
    if (!pct) return lim ? t("acc.limitedUntilOf", { name, when }) : t("acc.resetsOf", { name, when });
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

/** Where the auto-switch moves (Settings › Accounts, per CLI): the level of the fullest limit that applies, 80 to 100
 *  in steps of 5. 100 waits for the limit itself. */
export const SWITCH_AT_STEPS = [80, 85, 90, 95, 100] as const;
export const SWITCH_AT_DEFAULT = 90;
/** The account moved to must be at least this many points under the threshold. Moving at 100% onto a 98% account
 *  meant hitting that one's limit minutes later (kasaterm's own note). */
export const SWITCH_ROOM = 5;
/** Codex: one automatic switch at most this often. Its numbers come from session files, written only while a session
 *  runs, so the account just left keeps its old reading for a while; this keeps the switch from bouncing on it. */
export const CODEX_SWITCH_EVERY_S = 300;

/** The models running sessions use, by account id (`default` = the CLI's own login). */
export type ModelsInUse = Record<string, readonly string[]>;

/** The models of the running (or starting) sessions of `cli`, by the account each runs as. A session whose model is
 *  not known (a TERMINALS one) adds none. Only Claude Code's windows are scoped to a model today. */
export function modelsInUse(
  list: readonly { agent: string; status: string; account?: string; model?: string }[],
  cli: AccountCli,
): Record<string, string[]> {
  const out: Record<string, string[]> = {};
  for (const r of list) {
    if (r.agent !== cli || (r.status !== "running" && r.status !== "starting") || !r.model) continue;
    const id = r.account || "default";
    const have = (out[id] ??= []);
    if (!have.includes(r.model)) have.push(r.model);
  }
  return out;
}

/** A window applies to an account when it holds for the whole account, or for a model one of its running sessions
 *  uses (the window's model family inside the session's model id: "opus" in `claude-opus-4-5`). With no model known
 *  a model's window never applies: better to judge by the account-wide limits than to guess. */
function applies(w: UsageWindow, models: readonly string[]): boolean {
  if (!w.model) return true;
  const m = w.model.toLowerCase();
  return models.some((x) => x.toLowerCase().includes(m));
}

/** A reading that is still true: a window with a percent and a reset time still ahead, not stale (the same notion as
 *  `liveResets`). A window without a reset time could be any age, so it is no fresh reading. */
function fresh(w: UsageWindow, now: number): w is UsageWindow & { used_percent: number; resets_at: number } {
  return !w.stale && typeof w.used_percent === "number" && typeof w.resets_at === "number" && w.resets_at > now;
}

/** The fullest fresh window that applies, or null: no fresh reading for this account. */
function reading(u: UsageProvider | null | undefined, models: readonly string[], now: number): { percent: number; resets_at: number } | null {
  let best: { percent: number; resets_at: number } | null = null;
  for (const w of u?.windows ?? []) {
    if (!fresh(w, now) || !applies(w, models)) continue;
    if (!best || w.used_percent > best.percent) best = { percent: w.used_percent, resets_at: w.resets_at };
  }
  return best;
}

/** Limited: the bridge says so (account-wide windows only), or a model window that applies is at its limit. */
function limited(a: Account, usage: Record<string, UsageProvider | null | undefined>, models: readonly string[] = [], now = 0): boolean {
  if (a.state === "limited" || usage[a.id]?.state === "limited") return true;
  return ((usage[a.id] ?? a.usage)?.windows ?? []).some(
    (w) => w.model && !w.stale && applies(w, models) && (w.limited === true || (w.used_percent ?? 0) >= 100) && !(typeof w.resets_at === "number" && w.resets_at <= now),
  );
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
  /** Seconds since epoch; defaults to the clock. */
  now?: number;
  /** One of SWITCH_AT_STEPS (anything else is SWITCH_AT_DEFAULT). */
  threshold?: number;
  /** The models the running sessions of each account use (`modelsInUse`); none known = none. */
  models?: ModelsInUse;
}

/** Why the account in use should move: its level (`percent`, the fullest window that applies, and when that one
 *  resets) when it reached the threshold before any limit; only `resets_at` (when known) when it is limited. */
export interface SwitchAt {
  percent?: number;
  resets_at?: number;
}

/** A move (`to` an index), or none possible (`to` null: no other account has room). `at` is absent for a move off a
 *  limited account, which the line words as a limit. */
export type SwitchCheck = { from: number; to: number; soonest?: number; at?: SwitchAt } | { from: number; to: null; at: SwitchAt };

/**
 * Fill-first with a threshold: when the account in use reaches `threshold` on a window that applies to it (or is
 * limited), the first signed-in account in list order that has a fresh reading at least SWITCH_ROOM points under the
 * threshold on its own windows, and is not limited, takes over. An account with no fresh reading is never a
 * candidate: moving to a login nobody has seen working can leave every new session signed out. When no other account
 * has a fresh reading at all, the rule is the one from before the threshold, so missing readings never strand the
 * person on a limited account: once the one in use is actually limited, the first ready one that is not limited.
 * CLIProxyAPI's logins are never candidates. Returns null when the one in use is under the threshold, or has no other
 * login to move to; `{to: null}` when it should move and no account qualifies.
 *
 * With `resetFirst`, the same candidates are ordered by when their limit resets, compared like with like: the
 * shortest window any candidate reports (the 5-hour one for Codex), and only a window that is not stale and
 * resets in the future. A candidate with no such reset keeps its list position after those that have one, so
 * when nothing is comparable the answer is the fill-first one. `soonest` (its reset time) is set only when this
 * picked a different account than list order would.
 */
export function switchCheck(
  accounts: Account[],
  usage: Record<string, UsageProvider | null | undefined> = {},
  activeId?: string | null,
  opts: NextOptions = {},
): SwitchCheck | null {
  const from = accounts.findIndex((a) => (activeId ? a.id === activeId : a.state === "active"));
  if (from < 0) return null;
  const now = opts.now ?? Date.now() / 1000;
  const threshold = (SWITCH_AT_STEPS as readonly number[]).includes(opts.threshold ?? NaN) ? (opts.threshold as number) : SWITCH_AT_DEFAULT;
  const modelsOf = (a: Account) => opts.models?.[a.id] ?? [];
  const read = (a: Account) => reading(usage[a.id] ?? a.usage, modelsOf(a), now);
  const isLimited = (a: Account) => limited(a, usage, modelsOf(a), now);
  const cur = accounts[from];
  const curLimited = isLimited(cur);
  const curReading = read(cur);
  // a single signed-in login has nowhere to go and nothing to say
  if (!accounts.some((a, i) => i !== from && a.state !== "login" && !isCpa(a))) return null;
  const others: number[] = [];
  accounts.forEach((a, i) => {
    if (i !== from && a.state === "ready" && !isCpa(a)) others.push(i);
  });
  const withReading = others.filter((i) => read(accounts[i]) !== null);
  let ready: number[];
  if (withReading.length === 0) {
    if (!curLimited) return null;
    ready = others.filter((i) => !isLimited(accounts[i]));
  } else {
    if (!curLimited && !(curReading && curReading.percent >= threshold)) return null;
    ready = withReading.filter((i) => !isLimited(accounts[i]) && (read(accounts[i]) as { percent: number }).percent <= threshold - SWITCH_ROOM);
  }
  const at: SwitchAt | undefined = curLimited
    ? undefined
    : { percent: (curReading as { percent: number }).percent, resets_at: (curReading as { resets_at: number }).resets_at };
  const why = at ? { at } : {};
  if (ready.length === 0) {
    const lifts = typeof cur.resets_at === "number" && cur.resets_at > now ? { resets_at: cur.resets_at } : {};
    return { from, to: null, at: at ?? lifts };
  }
  if (!opts.resetFirst) return { from, to: ready[0], ...why };
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
  if (best <= 0) return { from, to: ready[0], ...why };
  return { from, to: ready[best], soonest: bestAt, ...why };
}

/** `switchCheck`'s move only: `{from, to, soonest?}`, or null when nothing moves. */
export function nextAccount(
  accounts: Account[],
  usage: Record<string, UsageProvider | null | undefined> = {},
  activeId?: string | null,
  opts: NextOptions = {},
): { from: number; to: number; soonest?: number } | null {
  const c = switchCheck(accounts, usage, activeId, opts);
  if (!c || c.to === null) return null;
  return c.soonest === undefined ? { from: c.from, to: c.to } : { from: c.from, to: c.to, soonest: c.soonest };
}

/** Codex is held for CODEX_SWITCH_EVERY_S after its last automatic switch (`last`, seconds); no other CLI is. */
export function switchHeld(cli: AccountCli, last: number | undefined, now: number): boolean {
  return cli === "codex" && last !== undefined && now - last < CODEX_SWITCH_EVERY_S;
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

/** The told keys that still matter: those whose reset time (the end of the key) is still ahead. A key past its
 *  reset can never come up again, so it is dropped; a live one is kept however many there are. */
export function pruneSeen(seen: readonly string[], now: number): string[] {
  return seen.filter((k) => Number(k.slice(k.lastIndexOf(":") + 1)) > now);
}

const resetText = (at: number | null | undefined, now: number) =>
  typeof at === "number" && at > now ? t("acc.resetsAt", { when: clock(at, now) }) : "";

/** "Switched Codex to Work (limit on This computer, resets 14:00)": the one quiet line in the bot chat. With `at`
 *  (the switch came at the threshold, before any limit): "(This computer at 92%, resets 14:00)". */
export function switchNote(g: AccountGroup, from: number, to: number, now: number, soonest?: number, at?: SwitchAt): string {
  const a = g.accounts[from];
  const b = g.accounts[to];
  const early = typeof at?.percent === "number";
  const reset = resetText(early ? at?.resets_at : a.resets_at, now);
  const args = { cli: CLI_NAME[g.cli], to: accountName(b, to), from: accountName(a, from), reset, pct: Math.round(at?.percent ?? 0) };
  // reset-first picked it over an earlier account in the list: say why
  if (typeof soonest === "number") return t(early ? "acc.switchedAtByReset" : "acc.switchedByReset", { ...args, when: clock(soonest, now) });
  return t(early ? "acc.switchedAt" : "acc.switched", args);
}

/** The line when the account in use should move and no other account has room (told once per window). */
export function noRoomNote(g: AccountGroup, from: number, now: number, at: SwitchAt): string {
  const a = g.accounts[from];
  const args = { cli: CLI_NAME[g.cli], from: accountName(a, from), reset: resetText(at.resets_at, now) };
  return typeof at.percent === "number" ? t("acc.noRoom", { ...args, pct: Math.round(at.percent) }) : t("acc.noRoomLimited", args);
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

/** Per-CLI threshold (one of SWITCH_AT_STEPS), SWITCH_AT_DEFAULT unless another step was saved on this computer. */
export function switchAt(cli: AccountCli, store: Pick<Storage, "getItem"> | undefined = globalThis.localStorage): number {
  try {
    const raw = store?.getItem("omher.switchat");
    const v = raw ? (JSON.parse(raw) as Record<string, unknown>)[cli] : undefined;
    return typeof v === "number" && (SWITCH_AT_STEPS as readonly number[]).includes(v) ? v : SWITCH_AT_DEFAULT;
  } catch {
    return SWITCH_AT_DEFAULT;
  }
}

export function setSwitchAt(cli: AccountCli, at: number): void {
  try {
    const raw = localStorage.getItem("omher.switchat");
    const cur = raw ? (JSON.parse(raw) as Record<string, number>) : {};
    localStorage.setItem("omher.switchat", JSON.stringify({ ...cur, [cli]: at }));
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
