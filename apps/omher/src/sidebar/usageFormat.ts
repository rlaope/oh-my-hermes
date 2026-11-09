// Text and colour rules for the sidebar usage meters. Pure, so vitest pins them: a % appears only when the
// source gave one, and a window whose reset time has passed says "stale" instead of a number.
import type { UsageProvider, UsageWindow } from "../lib/protocol";

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
  if (d > 0) return h ? `${d}d ${h}h` : `${d}d`;
  if (h > 0) return m ? `${h}h ${m}m` : `${h}h`;
  return m > 0 ? `${m}m` : "<1m";
}

/** "14:00" today, "Tue 14:00" within a week, else "Nov 18 14:00" (local time). */
export function clock(ts: number, now: number): string {
  const d = new Date(ts * 1000);
  const hm = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  const today = new Date(now * 1000);
  if (d.toDateString() === today.toDateString()) return hm;
  if (ts - now < 6 * 86400) return `${d.toLocaleDateString("en-US", { weekday: "short" })} ${hm}`;
  return `${d.toLocaleDateString("en-US", { month: "short", day: "numeric" })} ${hm}`;
}

/** One card row: [label, percent text ("" when the source gave none), note]. */
export function windowRow(p: UsageProvider, w: UsageWindow, now: number): [string, string, string] {
  const pct = !w.stale && typeof w.used_percent === "number" ? `${Math.round(w.used_percent)}%` : "";
  if (w.stale) return [w.label, pct, "stale"];
  if (p.state === "limited" && pct === "" && typeof w.resets_at === "number") return [w.label, pct, `Limited until ${clock(w.resets_at, now)}`];
  if (typeof w.resets_at === "number") return [w.label, pct, `resets in ${duration(w.resets_at - now)}`];
  return [w.label, pct, ""];
}

/** The card's one-line state when there is no window to show (or for the header). */
export function stateText(p: UsageProvider): string {
  switch (p.state) {
    case "limited":
      return "Limited";
    case "near":
      return "Near the limit";
    case "stale":
      return "stale";
    case "connected":
      return "Connected · no usage record";
    default:
      return "OK";
  }
}

export function planText(plan?: string): string {
  return plan ? plan.charAt(0).toUpperCase() + plan.slice(1) : "";
}

/** Accessible name for a meter button: provider, then the % or the state. */
export function meterLabel(p: UsageProvider): string {
  const pct = topPercent(p);
  return `${PROVIDER_NAME[p.id] ?? p.id} usage: ${pct === null ? stateText(p) : `${Math.round(pct)}%`}`;
}
