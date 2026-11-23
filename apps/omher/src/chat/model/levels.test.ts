import { describe, expect, it } from "vitest";
import { levelOptions } from "./levels";

describe("chat reasoning levels", () => {
  it("offers the bot's own levels, else Hermes' full ladder in its order", () => {
    expect(levelOptions(["none", "low", "high"]).map((o) => o.value)).toEqual(["none", "low", "high"]);
    const full = ["none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"];
    expect(levelOptions().map((o) => o.value)).toEqual(full);
    expect(levelOptions([]).map((o) => o.label)).toEqual(full);
  });
});
