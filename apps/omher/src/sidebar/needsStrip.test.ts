import { describe, expect, it } from "vitest";
import { stripText } from "./Needs";

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
