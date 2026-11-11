import { afterEach, describe, expect, it } from "vitest";
import { setLang } from "../i18n";
import { scheduleWords } from "./schedule";

describe("scheduleWords", () => {
  afterEach(() => setLang("en"));

  it("says the common cron shapes in words", () => {
    expect(scheduleWords("0 9 * * *")).toBe("every day at 09:00");
    expect(scheduleWords("0 9 * * 1-5")).toBe("weekdays at 09:00");
    expect(scheduleWords("0 10 * * 1")).toBe("every Monday at 10:00");
    expect(scheduleWords("30 18 * * 0")).toBe("every Sunday at 18:30");
    expect(scheduleWords("0 18 1 * *")).toBe("day 1 of every month at 18:00");
    expect(scheduleWords("0 9 1 12 *")).toBe("every year on Dec 1 at 09:00");
    expect(scheduleWords("*/15 * * * *")).toBe("every 15 min");
    expect(scheduleWords("0 */2 * * *")).toBe("every 2 h");
  });

  it("says Hermes' interval and one-time displays in words", () => {
    expect(scheduleWords("every 30m")).toBe("every 30 min");
    expect(scheduleWords("every 120m")).toBe("every 2 h");
    expect(scheduleWords("every 2880m")).toBe("every 2 days");
    expect(scheduleWords("once at 2026-12-01 09:00")).toBe("once, Dec 1, 2026 09:00");
  });

  it("leaves a shape it does not know exactly as written", () => {
    for (const s of ["0 9 * * 1,3,5", "0 9-17 * * *", "5 4 * * mon", "once in 2h", "0 9 1 * 1", "61 9 * * *", ""]) expect(scheduleWords(s)).toBe(s);
  });

  it("uses the UI language's own words", () => {
    setLang("ko");
    expect(scheduleWords("0 9 * * 1-5")).toBe("평일 09:00");
    expect(scheduleWords("0 10 * * 1")).toBe("매주 월요일 10:00");
    expect(scheduleWords("every 30m")).toBe("30분마다");
    expect(scheduleWords("0 9 1 12 *")).toBe("매년 12월 1일 09:00");
    setLang("ja");
    expect(scheduleWords("0 9 * * *")).toBe("毎日 09:00");
    expect(scheduleWords("0 10 * * 1")).toBe("毎週月曜日 10:00");
    setLang("zh");
    expect(scheduleWords("0 9 * * 1-5")).toBe("工作日 09:00");
    expect(scheduleWords("every 60m")).toBe("每 1 小时");
  });
});
