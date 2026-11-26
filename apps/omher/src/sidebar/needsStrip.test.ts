import { describe, expect, it } from "vitest";
import { prReason, prWho, stripText } from "./Needs";

describe("needs strip line", () => {
  it("names who waits, once each and in the list's order, never the ask's words", () => {
    expect(stripText(1, ["Friren"])).toEqual({ count: "1 needs you", rest: " · Friren" });
    expect(stripText(2, ["Friren", "Hermes"]).rest).toBe(" · Friren, Hermes");
    expect(stripText(3, ["Kami", "Friren", "Kami"]).rest).toBe(" · Kami, Friren");
    // past two names the rest is a count, so the line fits the sidebar
    expect(stripText(5, ["Kami", "Friren", "Hermes", "web-app · Claude Code", "Kami"]).rest).toBe(" · Kami, Friren +2");
    expect(stripText(1, [""])).toEqual({ count: "1 needs you", rest: "" });
  });
});

describe("a failing pull request in the strip", () => {
  const f = { bot: "kami", thread: "t1", pr: { number: 12, repo: "o/r", url: "https://github.com/o/r/pull/12", state: "open" as const, checks: "failing" as const } };
  it("says which PR's checks fail and names the thread, else the bot", () => {
    expect(prReason(f)).toBe("checks failing on #12");
    expect(prWho({ threads: { kami: [{ thread: "t1", title: "Docs dark mode" }] } }, f, "Kami")).toBe("Docs dark mode");
    expect(prWho({ threads: { kami: [{ thread: "t1", title: "" }] } }, f, "Kami")).toBe("Kami");
    expect(prWho({ threads: {} }, f, "Kami")).toBe("Kami");
    expect(stripText(1, [prWho({ threads: { kami: [{ thread: "t1", title: "Docs dark mode" }] } }, f, "Kami")]).rest).toBe(" · Docs dark mode");
  });
});
