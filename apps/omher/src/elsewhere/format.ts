// Small formatters for the read-only elsewhere view. Timestamps are seconds since epoch.
import { hhmm, shortTime } from "../app/time";
import { sourceName } from "../chat/parts/fallbacks";
import { listText, t, type Key } from "../i18n";
import { monthDay, weekdayName } from "../app/time";

/** "38s", "4m", "1h 4m": how long an away session has been working. */
export function workingFor(startedAt: number, nowMs = Date.now()): string {
  const s = Math.max(0, Math.floor(nowMs / 1000 - startedAt));
  if (s < 60) return t("unit.s", { n: s });
  const m = Math.floor(s / 60);
  if (m < 60) return t("unit.m", { n: m });
  return t("unit.hm", { h: Math.floor(m / 60), m: m % 60 });
}

/** Right-hand time of an away line or panel row: "working · 4m" while running, else "14:02" / "Mon" / "Nov 2". */
export function awayTime(a: { running: boolean; started_at: number; last_active: number }, nowMs = Date.now()): string {
  return a.running ? t("aw.working", { t: workingFor(a.started_at, nowMs) }) : shortTime(a.last_active, nowMs);
}

/** `next_run_at` may be seconds, an ISO string or null. */
export function toSeconds(v: number | string | null | undefined): number | null {
  if (typeof v === "number" && Number.isFinite(v)) return v > 1e12 ? v / 1000 : v;
  if (typeof v === "string" && v) {
    const ms = Date.parse(v);
    return Number.isNaN(ms) ? null : ms / 1000;
  }
  return null;
}

/** "next 09:00" (within a day), "next Fri" (within a week), "next Nov 20", or "paused" / "not scheduled". */
export function nextRun(r: { next_run_at: number | string | null; enabled: boolean }, nowMs = Date.now()): string {
  if (!r.enabled) return t("ew.paused");
  const ts = toSeconds(r.next_run_at);
  if (ts === null) return t("ew.notScheduled");
  const d = new Date(ts * 1000);
  const ahead = d.getTime() - nowMs;
  if (ahead < 24 * 3600_000) return t("ew.next", { when: hhmm(d) });
  if (ahead < 7 * 24 * 3600_000) return t("ew.next", { when: weekdayName(d) });
  return t("ew.next", { when: monthDay(d) });
}

const CADENCE = ["hourly", "daily", "weekly", "monthly", "yearly"] as const;
const CADENCE_KEY: Record<(typeof CADENCE)[number], Key> = { hourly: "ew.hourly", daily: "ew.daily", weekly: "ew.weekly", monthly: "ew.monthly", yearly: "ew.yearly" };

/** "Daily 09:00" → "daily" ("매일" in Korean), "Weekly (Mon 09:00)" → "weekly"; anything else (cron text, "every 30m")
 *  as is. The word is the UI language's: a Korean panel read "다음 05:06 · daily" before. */
export function cadence(schedule: string): string {
  const first = schedule.trim().split(/[\s(]/)[0]?.toLowerCase() ?? "";
  return (CADENCE as readonly string[]).includes(first) ? t(CADENCE_KEY[first as (typeof CADENCE)[number]]) : schedule.trim();
}

/** "Slack", "Slack and Discord", "Slack, Discord and Telegram" (unique, in order). */
export function sourceList(sources: string[]): string {
  const names = [...new Set(sources.map(sourceName))];
  return names.length <= 1 ? (names[0] ?? "") : listText(names);
}

export { sourceName };

// ---- a routine run's status (Hermes' run states) ---------------------------------------------

type Word = "done" | "failed" | "notDelivered" | "blocked";
// Hermes' run states (the bridge's FAILED_RUN): delivery_failed = the job ran but its message could not be delivered;
// blocked_config = the job's config stopped it from running.
const WORD: Record<string, Word> = {
  ok: "done",
  success: "done",
  done: "done",
  completed: "done",
  error: "failed",
  failed: "failed",
  failure: "failed",
  delivery_failed: "notDelivered",
  blocked_config: "blocked",
};
const WORD_KEY: Record<Word, Key> = { done: "rt.done", failed: "rt.failed", notDelivered: "rt.notDelivered", blocked: "rt.blocked" };

export const statusWord = (status: string): string => WORD[status.trim().toLowerCase()] ?? (status.trim() || "done");
export const isFailure = (status: string): boolean => {
  const w = WORD[status.trim().toLowerCase()];
  return w === "failed" || w === "notDelivered" || w === "blocked";
};
/** The status word in the current language; a status omher does not know stays as Hermes wrote it. Every place a
 *  routine's last run shows (the chat line, Details › Routines, the Schedule tab) says it this way, never the raw
 *  state ("ok", "delivery_failed"). */
export const statusText = (status: string) => {
  const w = WORD[status.trim().toLowerCase()] ?? (status.trim() ? null : "done");
  return w ? t(WORD_KEY[w]) : status.trim();
};
