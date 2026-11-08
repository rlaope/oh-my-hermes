// Small time formatters shared by the sidebar and the timeline. `ts` is seconds since epoch.

const pad = (n: number) => String(n).padStart(2, "0");
export const hhmm = (d: Date) => `${pad(d.getHours())}:${pad(d.getMinutes())}`;
const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
const WEEKDAY = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTH = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** Sidebar time: "now" (<1 min), "14:02" (today), "Mon" (this week), "Nov 2" (older). */
export function shortTime(ts: number, nowMs = Date.now()): string {
  const d = new Date(ts * 1000);
  if (nowMs - d.getTime() < 60_000) return "now";
  const days = Math.round((startOfDay(new Date(nowMs)) - startOfDay(d)) / 86_400_000);
  if (days <= 0) return hhmm(d);
  if (days < 7) return WEEKDAY[d.getDay()];
  return `${MONTH[d.getMonth()]} ${d.getDate()}`;
}

/** Day divider label: "Today", "Yesterday", "Monday", "Nov 2". */
export function dayLabel(ts: number, nowMs = Date.now()): string {
  const d = new Date(ts * 1000);
  const days = Math.round((startOfDay(new Date(nowMs)) - startOfDay(d)) / 86_400_000);
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 7) return ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"][d.getDay()];
  return `${MONTH[d.getMonth()]} ${d.getDate()}`;
}

export const sameDay = (a: number, b: number) => startOfDay(new Date(a * 1000)) === startOfDay(new Date(b * 1000));

/** "38s", "2m 41s", "1h 4m". */
export function elapsed(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${s % 60}s`;
  return `${Math.floor(m / 60)}h ${m % 60}m`;
}
