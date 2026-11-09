import { describe, expect, it } from "vitest";
import { appendLine } from "./BridgeGate";

describe("installer output on the setup screen", () => {
  it("keeps every line until the cap, then only the newest", () => {
    expect(appendLine(["a"], "b")).toEqual(["a", "b"]);
    expect(appendLine(["a", "b", "c"], "d", 3)).toEqual(["b", "c", "d"]);
    let lines: string[] = [];
    for (let i = 0; i < 450; i++) lines = appendLine(lines, String(i));
    expect(lines).toHaveLength(400);
    expect(lines[0]).toBe("50");
    expect(lines[399]).toBe("449");
  });
});
