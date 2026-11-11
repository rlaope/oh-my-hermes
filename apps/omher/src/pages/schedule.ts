// A job's schedule in words. Hermes stores a display string (`0 9 * * 1-5`, `every 30m`, `once at 2026-12-01 09:00`);
// the common shapes are said in the UI language ("weekdays at 09:00", "평일 09:00"), anything else stays as written.
import { lang, t } from "../i18n";

const pad = (n: number) => String(n).padStart(2, "0");
const num = (s: string, lo: number, hi: number): number | null => {
  if (!/^\d{1,2}$/.test(s)) return null;
  const n = Number(s);
  return n >= lo && n <= hi ? n : null;
};
// 2026-11-01 is a Sunday: day 1 + n is weekday n (0 = Sunday), in the UI language's own word.
const weekday = (n: number) => new Date(2026, 10, 1 + (n % 7)).toLocaleDateString(lang(), { weekday: "long" });
const monthDay = (month: number, day: number) => new Date(2026, month - 1, day).toLocaleDateString(lang(), { month: "short", day: "numeric" });

function everyMinutes(min: number): string {
  if (min % 1440 === 0) return t("sched.everyDays", { n: min / 1440 });
  if (min % 60 === 0) return t("sched.everyHours", { n: min / 60 });
  return t("sched.everyMin", { n: min });
}

function cronWords(f: string[]): string | null {
  const [mi, h, dom, mon, dow] = f;
  const step = (s: string) => (/^\*\/\d{1,3}$/.test(s) ? Number(s.slice(2)) : null);
  if (h === "*" && dom === "*" && mon === "*" && dow === "*" && step(mi)) return everyMinutes(step(mi)!);
  if (mi === "0" && dom === "*" && mon === "*" && dow === "*" && step(h)) return everyMinutes(step(h)! * 60);
  const m = num(mi, 0, 59);
  const hr = num(h, 0, 23);
  if (m === null || hr === null) return null;
  const at = `${pad(hr)}:${pad(m)}`;
  if (dom === "*" && mon === "*") {
    if (dow === "*") return t("sched.daily", { at });
    if (dow === "1-5") return t("sched.weekdays", { at });
    const d = num(dow, 0, 7);
    return d === null ? null : t("sched.weekly", { day: weekday(d), at });
  }
  const day = num(dom, 1, 31);
  if (day === null || dow !== "*") return null;
  if (mon === "*") return t("sched.monthly", { d: day, at });
  const month = num(mon, 1, 12);
  return month === null ? null : t("sched.yearly", { date: monthDay(month, day), at });
}

/** `schedule` in words when its shape is a known one, else exactly as Hermes wrote it. */
export function scheduleWords(schedule: string): string {
  const s = schedule.trim();
  const every = /^every (\d{1,6})m$/.exec(s);
  if (every) return everyMinutes(Number(every[1]));
  const once = /^once at (\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})$/.exec(s);
  if (once) {
    const d = new Date(Number(once[1]), Number(once[2]) - 1, Number(once[3]));
    return t("sched.once", { date: d.toLocaleDateString(lang(), { year: "numeric", month: "short", day: "numeric" }), at: `${once[4]}:${once[5]}` });
  }
  const fields = s.split(/\s+/);
  return (fields.length === 5 && cronWords(fields)) || s;
}
