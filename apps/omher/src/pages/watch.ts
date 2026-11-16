// Channel watches on the Automations page: a cron job whose script is the channel-watch collector. The bridge's
// `read_automations` adds `watch` to such a job (what it watches, from the watch's config, and whether the bot could
// read the channel on its last check, from Hermes' run records). Pure helpers here; the rows are in Automations.tsx.
import type { Automation } from "../lib/protocol";
import { t } from "../i18n";
import { scheduleWords } from "./schedule";

export type WatchState = "ok" | "paused" | "not_readable";
export interface WatchInfo {
  name: string;
  platform: "slack" | "discord" | null;
  channels: string[];
  /** The condition in the person's words (from the judging prompt), else the keywords. */
  what: string;
  interval: string;
  last_check: number | string | null;
  /** When a check last found something and the bot told the person (unix s), or null. */
  last_alert: number | null;
  state: WatchState;
  /** Why the bot can't read the channel: the collector's reason code and the channel it names, if any. */
  reason: { code: string; channel: string | null } | null;
}

/** The watch facts of an automation, or null for any other job. */
export const watchOf = (a: Automation): WatchInfo | null => (a as Automation & { watch?: WatchInfo | null }).watch ?? null;

export const PLATFORM_NAME: Record<string, string> = { slack: "Slack", discord: "Discord" };

const CHANNEL = new Set(["not_in_channel", "channel_not_found", "access_denied", "is_archived", "not_found", "missing_access", "missing_permissions", "unknown_channel"]);
const TOKEN = new Set(["invalid_auth", "not_authed", "token_revoked", "token_expired", "account_inactive", "unauthorized"]);
const SCOPE = new Set(["missing_scope", "not_allowed_token_type"]);

/** Where the watch looks, in a line: "Slack #og, #ops". */
export function whereOf(w: WatchInfo): string {
  const p = w.platform ? PLATFORM_NAME[w.platform] : "";
  return [p, w.channels.join(", ")].filter(Boolean).join(" ");
}

/** Why the bot can't read the channel, in words. */
export function reasonWords(w: WatchInfo): string {
  const code = w.reason?.code ?? "failed";
  const platform = w.platform ? PLATFORM_NAME[w.platform] : "";
  if (CHANNEL.has(code)) return t("watch.why.channel", { channel: w.reason?.channel || w.channels.join(", ") || "?" });
  if (TOKEN.has(code)) return t("watch.why.token", { platform }).trim();
  if (SCOPE.has(code)) return t("watch.why.scope");
  if (code === "no_token") return t("watch.why.noToken", { platform }).trim();
  if (code === "config") return t("watch.why.config");
  return t("watch.why.failed");
}

/** The "+ New watch" sentence the bot receives in its chat; it sets nothing up before it confirms. */
export function watchSentence(p: { platform: "slack" | "discord"; channel: string; what: string; minutes: number }): string {
  return t("watch.msg", {
    platform: PLATFORM_NAME[p.platform],
    channel: p.channel.trim(),
    what: p.what.trim().replace(/[.。]+$/, ""),
    every: scheduleWords(`every ${p.minutes}m`),
  });
}

export const WATCH_EVERY = [5, 15, 60] as const;

/** The item "Not useful" quotes: the answer verbatim (`__init__`, backticks and all), whitespace collapsed, at most
 *  300 characters. */
export function notUsefulQuote(text: string): string {
  const flat = text.replace(/\s+/g, " ").trim();
  return flat.length <= 300 ? flat : `${flat.slice(0, 299)}…`;
}
