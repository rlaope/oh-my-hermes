// A bot's messaging platforms (Discord, Slack, ...) as OMH reads them from Hermes' gateway records and logs
// (`bots.platforms` -> the bridge's one `omh hermes platforms`, BOUNDARY rule 43): what the sidebar row and the bot
// page say. Only `failed`, `disconnected` and `reconnecting` are "known not to be connected now"; a row shows nothing
// for any other state, and `unknown` is never worded as connected or as not connected. The fix is words, a link to
// the Discord Developer Portal and Hermes' restart command to copy: nothing here changes anything. A bot on another
// computer (`<peer>:<name>`) reads the same way from what that computer's own bridge read there (rule 45).
import type { BotPlatforms, PlatformState, PlatformStatus, PlatformsRead } from "../lib/protocol";
import { listText, locale, t, type Key } from "../i18n";

/** The sidebar asks again this often while omher runs; the bridge answers from one OMH run for 30 s. */
export const PLATFORMS_POLL_MS = 60_000;
export const DISCORD_PORTAL = "https://discord.com/developers/applications";

// Platform names stay as each platform writes its own, in every language.
const NAMES: Record<string, string> = {
  discord: "Discord",
  slack: "Slack",
  telegram: "Telegram",
  whatsapp: "WhatsApp",
  signal: "Signal",
  matrix: "Matrix",
  mattermost: "Mattermost",
  email: "Email",
  sms: "SMS",
};
export const platformName = (p: string): string => NAMES[p] ?? (p ? p[0].toUpperCase() + p.slice(1).replace(/_/g, " ") : p);

export const NOT_CONNECTED: ReadonlySet<PlatformStatus> = new Set<PlatformStatus>(["failed", "disconnected", "reconnecting"]);
const STATUS_KEY: Record<PlatformStatus, Key> = {
  connected: "pf.st.connected",
  degraded: "pf.st.degraded",
  connecting: "pf.st.connecting",
  disabled: "pf.st.disabled",
  failed: "pf.st.failed",
  disconnected: "pf.st.disconnected",
  reconnecting: "pf.st.reconnecting",
  unknown: "pf.st.unknown",
};
const ROW_KEY: Partial<Record<PlatformStatus, Key>> = { failed: "pf.failed", disconnected: "pf.disconnected", reconnecting: "pf.reconnecting" };
const REASON_KEY: Record<string, Key> = {
  discord_privileged_intents: "pf.r.intents",
  discord_token_rejected: "pf.r.token",
  transient: "pf.r.transient",
  none_logged: "pf.r.none",
  unrecognized: "pf.r.unrecognized",
};
const WHY_KEY: Record<string, Key> = {
  earlier_run: "pf.why.earlier",
  not_served: "pf.why.unserved",
  ambiguous: "pf.why.ambiguous",
  unknown_state: "pf.why.state",
};
const RESTART = /^hermes -p ([a-z0-9][a-z0-9_-]{0,63}) gateway restart$/;

/** A reconnect Hermes runs by itself shows on the sidebar row only after this long (the bot page says it at once). */
export const ROW_RECONNECT_MS = 10 * 60_000;

/** Why a bot's computer could not say: its link is down, it gave no answer that checked out, or no answer of it has
 *  come yet (a bridge older than rule 45, a computer attached since the last read, an ask still under way). "" when
 *  it said. */
export type PeerWhy = "" | "offline" | "unread" | "unasked";

/** What was read for one bot: on this computer, or for `<peer>:<name>` on that computer by its own bridge. */
export interface BotRead {
  /** The computer could say; when false nothing is known and nothing is shown as connected. */
  available: boolean;
  entry: BotPlatforms | undefined;
  /** The peer id for a bot on another computer, else null. */
  peer: string | null;
  /** The profile name on its own computer (Hermes' restart command names this one). */
  bare: string;
  why: PeerWhy;
}

export function botRead(read: PlatformsRead | null, bot: string): BotRead {
  const at = bot.indexOf(":");
  if (at < 0) return { available: !!read?.available, entry: read?.available ? read.bots[bot] : undefined, peer: null, bare: bot, why: "" };
  const peer = bot.slice(0, at);
  const bare = bot.slice(at + 1);
  const there = read?.peers?.[peer];
  if (!there) return { available: false, entry: undefined, peer, bare, why: "unasked" };
  if (!there.available) return { available: false, entry: undefined, peer, bare, why: there.why === "offline" ? "offline" : "unread" };
  return { available: true, entry: there.bots[bare], peer, bare, why: "" };
}

/** The bot's platforms known not to be connected now; [] when its computer could not say, or for a bot it has no row
 *  for. */
export function notConnected(read: PlatformsRead | null, bot: string): PlatformState[] {
  const r = botRead(read, bot);
  if (!r.available) return [];
  return (r.entry?.platforms ?? []).filter((p) => NOT_CONNECTED.has(p.status));
}

/** What the sidebar row names: failed and disconnected at once; reconnecting only when Hermes flags it as needing the
 *  person, or after ROW_RECONNECT_MS of it, so Hermes' routine reconnects stay off the row. */
export function rowDown(read: PlatformsRead | null, bot: string, now: number): PlatformState[] {
  return notConnected(read, bot).filter((p) => {
    if (p.status !== "reconnecting" || p.attention) return true;
    const since = p.since ? Date.parse(p.since) : NaN;
    return Number.isFinite(since) && now - since >= ROW_RECONNECT_MS;
  });
}

/** "Discord disconnected": the sidebar row's words for a platform that is not connected. */
export function rowWords(p: PlatformState): string {
  const key = ROW_KEY[p.status];
  return key ? t(key, { platform: platformName(p.platform) }) : "";
}

export const statusWords = (p: PlatformState): string => t(STATUS_KEY[p.status] ?? "pf.st.unknown");

/** Why, in plain words: the reason kind for a failure, why the state is not known for `unknown`. */
export function whyWords(p: PlatformState): string {
  if (p.status === "unknown") return t(WHY_KEY[p.unknown_why] ?? "pf.why.state");
  const key = REASON_KEY[p.reason_kind];
  return key ? t(key) : "";
}

/** A UTC time as this language writes a date and a time; "" when there is none. */
export function whenText(iso: string): string {
  const at = iso ? Date.parse(iso) : NaN;
  if (!Number.isFinite(at)) return "";
  return new Date(at).toLocaleString(locale(), { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

/** The gateway a restart command names, when it is not the bot's own: the host that serves it and other bots. */
export function restartGateway(p: PlatformState, bot: string): string | null {
  const m = RESTART.exec(p.restart);
  return m && m[1] !== bot ? m[1] : null;
}

export type FixStep =
  | { kind: "text"; text: string }
  | { kind: "portal" }
  /** Hermes' restart, to copy: `then` after the steps above it, `maybe` when it is only worth a try. */
  | { kind: "restart"; command: string; lead: "then" | "maybe"; gateway: string | null };

/** What the person can do, in order. Nothing for a platform that is connected or that Hermes is reconnecting by
 *  itself (that case says so instead); a restart only when Hermes gave its command. */
export function fixSteps(p: PlatformState, bot: string): FixStep[] {
  if (!NOT_CONNECTED.has(p.status) && !p.attention) return [];
  if (p.status === "reconnecting" && !p.attention) return [{ kind: "text", text: t("pf.fix.retries") }];
  const steps: FixStep[] = [];
  let lead: "then" | "maybe" = "maybe";
  if (p.reason_kind === "discord_privileged_intents") {
    const intents = p.intents.map((i) => `${i} Intent`);
    steps.push({ kind: "text", text: intents.length ? t("pf.fix.intents", { intents: listText(intents) }) : t("pf.fix.intentsUnknown") });
    steps.push({ kind: "portal" });
    if (!p.intents.length || p.intents.includes("Server Members")) steps.push({ kind: "text", text: t("pf.fix.allowlist") });
    lead = "then";
  } else if (p.reason_kind === "discord_token_rejected") {
    steps.push({ kind: "text", text: t("pf.fix.token") }, { kind: "portal" });
    lead = "then";
  } else if (p.reason_kind === "transient") {
    steps.push({ kind: "text", text: t("pf.fix.transient") });
  } else if (p.reason_kind === "none_logged" || p.reason_kind === "unrecognized") {
    const at = whenText(p.logged);
    steps.push({ kind: "text", text: at ? t("pf.fix.readAt", { time: at }) : t("pf.fix.read") });
  }
  if (p.restart) steps.push({ kind: "restart", command: p.restart, lead, gateway: restartGateway(p, bot) });
  return steps;
}
