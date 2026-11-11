// Text and colour rules for the sidebar usage meters. Pure, so vitest pins them: a % appears only when the
// source gave one, and a window whose reset time has passed says "stale" instead of a number.
import type { UsageAccount, UsageProvider, UsageWindow } from "../lib/protocol";
import { locale, t } from "../i18n";

export const PROVIDER_NAME: Record<string, string> = { codex: "Codex", claude: "Claude Code", grok: "Grok", gemini: "Gemini CLI" };

/** The largest percentage the source gave over the provider's live windows, or null when it gave none. */
export function topPercent(p: UsageProvider): number | null {
  const xs = p.windows.filter((w) => !w.stale && typeof w.used_percent === "number").map((w) => w.used_percent!);
  return xs.length ? Math.max(...xs) : null;
}

/** Ring colour: gray under 70 %, amber 70–90 %, red over 90 %. */
export function ringLevel(percent: number): "gray" | "amber" | "red" {
  return percent > 90 ? "red" : percent >= 70 ? "amber" : "gray";
}

/** "1h 47m", "4d 23h", "12m", "<1m". */
export function duration(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (d > 0) return h ? t("unit.dh", { d, h }) : t("unit.d", { n: d });
  if (h > 0) return m ? t("unit.hm", { h, m }) : t("unit.h", { n: h });
  return m > 0 ? t("unit.m", { n: m }) : t("unit.lt1m");
}

/** "14:00" today, "Tue 14:00" within a week, else "Nov 18 14:00" (local time). */
export function clock(ts: number, now: number): string {
  const d = new Date(ts * 1000);
  const hm = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  const today = new Date(now * 1000);
  if (d.toDateString() === today.toDateString()) return hm;
  if (ts - now < 6 * 86400) return `${d.toLocaleDateString(locale(), { weekday: "short" })} ${hm}`;
  return `${d.toLocaleDateString(locale(), { month: "short", day: "numeric" })} ${hm}`;
}

/** What a window past its reset time says (no number: the record is old). */
export const stale = () => t("use.stale");
/** What a CLI that is here but has written no usage record says. */
export const noUsage = () => t("use.none");

/** A window's name as a limit: "5 hours" -> "5-hour limit", "Weekly" -> "Weekly limit" (Settings › Accounts says the same). */
export function limitName(label: string): string {
  if (label === "Weekly") return t("acc.limitWeekly");
  const m = /^(\d+) (hour|day)s?$/.exec(label);
  return m ? t(m[2] === "hour" ? "acc.limitHours" : "acc.limitDays", { n: m[1] }) : label;
}

/** One card row: [limit name, "73% used" ("" when the source gave none), note]. */
export function windowRow(p: UsageProvider, w: UsageWindow, now: number): [string, string, string] {
  const name = limitName(w.label);
  const pct = !w.stale && typeof w.used_percent === "number" ? t("acc.pctUsed", { n: Math.round(w.used_percent) }) : "";
  if (w.stale) return [name, pct, stale()];
  if (p.state === "limited" && pct === "" && typeof w.resets_at === "number") return [name, pct, t("acc.limitedUntil", { when: clock(w.resets_at, now) })];
  if (typeof w.resets_at === "number") return [name, pct, t("use.resetsIn", { t: duration(w.resets_at - now) })];
  return [name, pct, ""];
}

/** The card's one-line state when there is no window to show (or for the header). */
export function stateText(p: UsageProvider): string {
  switch (p.state) {
    case "limited":
      return t("acc.limited");
    case "near":
      return t("use.near");
    case "stale":
      return stale();
    case "connected":
      return noUsage();
    default:
      return t("use.ok");
  }
}

export function planText(plan?: string): string {
  return plan ? plan.charAt(0).toUpperCase() + plan.slice(1) : "";
}

/** The small dot on a meter: only for a state worth a glance (limited, near, stale). A ring carries the rest. */
export function meterDot(p: UsageProvider): "limited" | "near" | "stale" | null {
  if (p.state === "limited") return "limited";
  if (topPercent(p) !== null) return null;
  return p.state === "near" || p.state === "stale" ? p.state : null;
}

/** Accessible name for a meter button: provider, then the % or the state. */
export function meterLabel(p: UsageProvider): string {
  const pct = topPercent(p);
  return t("use.meter", { name: PROVIDER_NAME[p.id] ?? p.id, value: pct === null ? stateText(p) : `${Math.round(pct)}%` });
}

/** One login under the Claude card: [who, what its own record says]. The email (or the person's name for it), then
 *  "Limited until 17:00" / "OK" / "No recent record" from that login's own usage file, or "No record" when
 *  nothing on this computer records it (a CLIProxyAPI login). Never a number the record did not give. */
export function accountRow(a: UsageAccount, now: number): [string, string] {
  const who = a.label || a.email || (a.source === "cpa" ? t("use.cpaLogin") : t("acc.thisComputer"));
  if (a.state === "no_record") return [who, t("use.noRecord")];
  if (a.state === "limited") return [who, typeof a.resets_at === "number" && a.resets_at > now ? t("acc.limitedUntil", { when: clock(a.resets_at, now) }) : t("acc.limited")];
  if (a.state === "connected") return [who, noUsage()];
  return [who, stateText({ id: "claude", windows: [], state: a.state, source_mtime: null })];
}
