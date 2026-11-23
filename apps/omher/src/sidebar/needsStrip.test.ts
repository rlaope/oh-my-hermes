import { describe, expect, it } from "vitest";
import { prReason, prWho, stripText } from "./Needs";

describe("needs strip line", () => {
  it("names the newest ask's sender and its first words, cut with an ellipsis", () => {
    expect(stripText(1, "Friren", "Allow `rm -rf build/`?")).toEqual({ count: "1 needs you", rest: " · Friren: Allow rm -rf build/?" });
    const long = stripText(3, "web-app · Claude Code", "Which environment should I deploy the gateway to first?");
    expect(long.count).toBe("3 need you");
    expect(long.rest).toBe(" · web-app · Claude Code: Which environment should I depl…");
    expect(long.rest.split(": ")[1]).toHaveLength(32);
    expect(stripText(2, "Kami", "line one\n  line two").rest).toBe(" · Kami: line one line two");
  });
});

describe("a failing pull request in the strip", () => {
  const f = { bot: "kami", thread: "t1", pr: { number: 12, repo: "o/r", url: "https://github.com/o/r/pull/12", state: "open" as const, checks: "failing" as const } };
  it("says which PR's checks fail and names the thread, else the bot", () => {
    expect(prReason(f)).toBe("checks failing on #12");
    expect(prWho({ threads: { kami: [{ thread: "t1", title: "Docs dark mode" }] } }, f, "Kami")).toBe("Docs dark mode");
    expect(prWho({ threads: { kami: [{ thread: "t1", title: "" }] } }, f, "Kami")).toBe("Kami");
    expect(prWho({ threads: {} }, f, "Kami")).toBe("Kami");
    expect(stripText(1, "Docs dark mode", prReason(f)).rest).toBe(" · Docs dark mode: checks failing on #12");
  });
});
