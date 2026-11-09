// Accounts rules, pure so vitest pins them: masking, state chips, and the CPA-style fill-first auto-switch.
import type { Account, AccountCli, AccountGroup, UsageProvider } from "../../lib/protocol";
import { clock } from "../../sidebar/usageFormat";

export const CLI_NAME: Record<AccountCli, string> = { claude: "Claude", codex: "ChatGPT / Codex", grok: "Grok", gemini: "Gemini" };
/** Short names for one-line notes ("Switched to Claude #2"). */
export const CLI_SHORT: Record<AccountCli, string> = { claude: "Claude", codex: "Codex", grok: "Grok", gemini: "Gemini" };
/** The env var a new session uses for an omher account (mirrors the Rust `home_var`). */
export const HOME_VAR: Record<AccountCli, string> = {
  claude: "CLAUDE_CONFIG_DIR",
  codex: "CODEX_HOME",
  grok: "GROK_HOME",
  gemini: "GEMINI_CLI_HOME",
};
/** The CLI's own login, run with that env. */
export const LOGIN_CMD: Record<AccountCli, string> = { claude: "claude, then /login", codex: "codex login", grok: "grok login", gemini: "gemini" };
/** CLIProxyAPI's own login flags per CLI. */
export const CPA_LOGIN: Record<AccountCli, string> = {
  claude: "cliproxyapi -claude-login",
  codex: "cliproxyapi -codex-login",
  grok: "cliproxyapi -xai-login",
  gemini: "cliproxyapi -login",
};

/** "khope@sionic.ai" -> "k***@sionic.ai". Not an email -> unchanged. */
export function maskEmail(email: string): string {
  const at = email.indexOf("@");
  if (at < 1) return email;
  return `${email[0]}***${email.slice(at)}`;
}

/** What a row is called outside the Accounts page: its label, else the masked email, else "#n". */
export function accountName(a: Account, index: number): string {
  if (a.label) return a.label;
  if (a.email) return maskEmail(a.email);
  return `#${index + 1}`;
}

/** The state chip: Active / Ready / Limited until 14:00 / Expired / Disabled / Log in. */
export function stateChip(a: Account, now: number): string {
  switch (a.state) {
    case "active":
      return "Active";
    case "ready":
      return "Ready";
    case "limited":
      return typeof a.resets_at === "number" && a.resets_at > now ? `Limited until ${clock(a.resets_at, now)}` : "Limited";
    case "expired":
      return "Expired";
    case "disabled":
      return "Disabled";
    case "login":
      return "Log in";
  }
}

function limited(a: Account, usage: Record<string, UsageProvider | null | undefined>): boolean {
  return a.state === "limited" || a.state === "expired" || usage[a.id]?.state === "limited";
}

/**
 * Fill-first, like CLIProxyAPI's `routing.strategy: fill-first`: when the active account is limited or
 * expired, the first Ready account in list order takes over. Returns null when the active one is fine or no
 * other account is ready. `usage` (account id -> usage record) can mark an account limited on its own.
 */
export function nextAccount(
  accounts: Account[],
  usage: Record<string, UsageProvider | null | undefined> = {},
  activeId?: string | null,
): { from: number; to: number } | null {
  const from = accounts.findIndex((a) => (activeId ? a.id === activeId : a.state === "active"));
  if (from < 0) return null;
  const cur = accounts[from];
  if (!limited(cur, usage)) return null;
  const to = accounts.findIndex((a, i) => i !== from && a.state === "ready" && !limited(a, usage));
  return to < 0 ? null : { from, to };
}

/** "Switched to Claude #2 Work (limit on #1 Default, resets 14:00)" — the one quiet line in the bot chat. */
export function switchNote(g: AccountGroup, from: number, to: number, now: number): string {
  const a = g.accounts[from];
  const b = g.accounts[to];
  const reset = typeof a.resets_at === "number" && a.resets_at > now ? `, resets ${clock(a.resets_at, now)}` : "";
  const why = a.state === "expired" ? "expired" : "limit on";
  return `Switched to ${CLI_SHORT[g.cli]} #${to + 1} ${accountName(b, to)} (${why} #${from + 1} ${accountName(a, from)}${reset})`;
}

/** Per-group auto-switch preference, on unless turned off (saved on this computer). */
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

/** The hint shown when CPA's management API is off. */
export const CPA_OFF_HINT =
  "CPA management is off. Turn it on in ~/.cli-proxy-api/config.yaml (management.secret-key) to manage accounts here.";
