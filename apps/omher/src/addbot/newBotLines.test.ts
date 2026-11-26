import { afterEach, describe, expect, it } from "vitest";
import { setLang, t } from "../i18n";
import { createLine, refusalLine } from "./NewBot";

afterEach(() => setLang("en"));

describe("the New bot card's refusals read in the UI language", () => {
  for (const l of ["ko", "zh", "ja"] as const) {
    it(`${l}: no English from the bridge's codes`, () => {
      setLang(l);
      const lines = [
        createLine({ outcome: "failed", reason: "no_hermes", line: "Hermes is not on this computer." }, "x"),
        createLine({ outcome: "failed", reason: "exit", code: 2, line: "Hermes exited with code 2." }, "x"),
        createLine({ outcome: "unconfirmed", reason: "left", leftovers: ["profiles/x"], said: "", line: "omher could not confirm" }, "x"),
        createLine({ outcome: "unconfirmed", reason: "running", leftovers: [], said: "", line: "omher could not confirm" }, "x"),
        refusalLine({ code: "busy", message: "omher is still making another bot" }, "x"),
        refusalLine({ code: "exists", message: "A folder named x is already under Hermes' profiles." }, "x"),
      ];
      for (const line of lines) expect(line).not.toMatch(/could not confirm|not on this computer|still making|already under|exited with/);
    });
  }

  it("a bad_request refusal names the rule the name broke: reserved, omh-tui, or the name rule", () => {
    expect(refusalLine({ code: "bad_request", message: "root is a name Hermes keeps for itself." }, "root")).toBe(t("ab.nameReserved", { name: "root" }));
    expect(refusalLine({ code: "bad_request", message: "omh-tui is oh-my-hermes' own TUI profile." }, "omh-tui")).toBe(t("ab.nameOmh", { name: "omh-tui" }));
    expect(refusalLine({ code: "bad_request", message: "Use lowercase letters" }, "a b")).toBe(t("ab.nameRule"));
  });

  it("Hermes' own words and unknown errors pass through", () => {
    expect(createLine({ outcome: "failed", reason: "hermes", line: "Error: boom" }, "x")).toBe("Error: boom");
    expect(refusalLine({ code: "weird", message: "odd" }, "x")).toBe("odd");
    expect(createLine({ outcome: "unconfirmed", reason: "running", said: "why", line: "" }, "pr")).toContain("\nwhy");
  });
});
