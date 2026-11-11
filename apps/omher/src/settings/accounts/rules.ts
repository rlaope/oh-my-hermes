// Accounts rules, pure so vitest pins them: row names, plan words, the usage line, the in-use account, and the
// fill-first auto-switch.
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

/**
 * Fill-first: when the in-use account is limited, the first signed-in account that is not limited takes over,
 * in list order. Returns null when the in-use one is fine or no other account is ready.
 */
export function nextAccount(
  accounts: Account[],
  usage: Record<string, UsageProvider | null | undefined> = {},
  activeId?: string | null,
): { from: number; to: number } | null {
  const from = accounts.findIndex((a) => (activeId ? a.id === activeId : a.state === "active"));
  if (from < 0) return null;
  if (!limited(accounts[from], usage)) return null;
  const to = accounts.findIndex((a, i) => i !== from && a.state === "ready" && !isCpa(a) && !limited(a, usage));
  return to < 0 ? null : { from, to };
}

/** "Switched Codex to Work (limit on This computer, resets 14:00)": the one quiet line in the bot chat. */
export function switchNote(g: AccountGroup, from: number, to: number, now: number): string {
  const a = g.accounts[from];
  const b = g.accounts[to];
  const reset = typeof a.resets_at === "number" && a.resets_at > now ? t("acc.resetsAt", { when: clock(a.resets_at, now) }) : "";
  return t("acc.switched", { cli: CLI_NAME[g.cli], to: accountName(b, to), from: accountName(a, from), reset });
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
