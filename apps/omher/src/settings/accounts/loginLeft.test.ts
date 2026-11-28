import { describe, expect, it } from "vitest";
import { loginLeft } from "./loginLeft";

const NOW = Date.parse("2026-11-28T00:00:00Z");
const H = 3600 * 1000;
const D = 24 * H;
const at = (ms: number) => new Date(NOW + ms).toISOString();

describe("login days left", () => {
  it("days while more than a day is left; red only within three days", () => {
    expect(loginLeft(at(12 * D + 5 * H), NOW)).toEqual({ text: "Login: 12 days left", soon: false });
    expect(loginLeft(at(3 * D + 1000), NOW)).toEqual({ text: "Login: 3 days left", soon: false });
    expect(loginLeft(at(3 * D), NOW)).toEqual({ text: "Login: 3 days left", soon: true });
    expect(loginLeft(at(2 * D + 23 * H), NOW)).toEqual({ text: "Login: 2 days left", soon: true });
    expect(loginLeft(at(D + H), NOW)).toEqual({ text: "Login: 1 day left", soon: true });
  });
  it("hours under a day, never 0 h", () => {
    expect(loginLeft(at(23 * H), NOW)).toEqual({ text: "Login: 23 h left", soon: true });
    expect(loginLeft(at(5 * H + 59 * 60 * 1000), NOW)).toEqual({ text: "Login: 5 h left", soon: true });
    expect(loginLeft(at(10 * 60 * 1000), NOW)).toEqual({ text: "Login: 1 h left", soon: true });
  });
  it("expired at 0 and past it", () => {
    expect(loginLeft(at(0), NOW)).toEqual({ text: "Login: expired", soon: true });
    expect(loginLeft(at(-2 * D), NOW)).toEqual({ text: "Login: expired", soon: true });
  });
  it("unknown or unreadable: nothing", () => {
    expect(loginLeft(null, NOW)).toBeNull();
    expect(loginLeft(undefined, NOW)).toBeNull();
    expect(loginLeft("", NOW)).toBeNull();
    expect(loginLeft("not a date", NOW)).toBeNull();
    expect(loginLeft("2026-13-45T99:00:00Z", NOW)).toBeNull();
  });
  it("reads an offset time the same as UTC", () => {
    expect(loginLeft("2026-12-01T09:00:00+09:00", NOW)).toEqual({ text: "Login: 3 days left", soon: true });
  });
});
