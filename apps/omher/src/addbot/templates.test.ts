import { describe, expect, it } from "vitest";
import { applyMessage, checkName, normalizeName, skillSyncCmd } from "./templates";

describe("new bot name", () => {
  it("reads a typed name as Hermes does: trimmed and lowercased", () => {
    expect(normalizeName("  PR-Bot ")).toBe("pr-bot");
  });

  it("takes Hermes' own rule and refuses its reserved names and the bots already here", () => {
    expect(checkName("", [])).toBe("empty");
    for (const bad of ["a b", "-p", "_x", "pr.bot", "x;y", "봇", "a".repeat(65)]) expect(checkName(bad, []), bad).toBe("rule");
    for (const r of ["hermes", "default", "test", "tmp", "root", "sudo"]) expect(checkName(r, []), r).toBe("reserved");
    expect(checkName("omh-tui", [])).toBe("omh");
    expect(checkName("kami", ["kami", "friren"])).toBe("taken");
    expect(checkName("pr-bot", ["kami"])).toBe("ok");
    expect(checkName("9to5_bot", [])).toBe("ok");
    expect(checkName("a".repeat(64), [])).toBe("ok");
  });
});

describe("apply message", () => {
  it("opens with the skill's command and names the template id", () => {
    expect(applyMessage("pr-review")).toBe("/omh-bot-template Apply the bot template `pr-review` to this bot.");
  });

  it("is built from an id alone and refuses anything else", () => {
    for (const bad of ["", "PR", "a b", "x`; rm", "../x", "-x"]) expect(() => applyMessage(bad), bad).toThrow();
  });
});

describe("skill sync command", () => {
  it("names OMH's one-profile registration for exactly this bot", () => {
    expect(skillSyncCmd("pr-bot")).toBe("omh apply --profile pr-bot");
  });
});
