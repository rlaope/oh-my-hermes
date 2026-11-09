import { describe, expect, it } from "vitest";
import { appendLine, lineTone } from "./BridgeGate";

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

describe("installer line tones", () => {
  it("marks failures bad, done steps ok, and leaves the rest plain", () => {
    expect(lineTone("      [failed] Install OMH package")).toBe("bad");
    expect(lineTone("  ERROR: could not reach github.com")).toBe("bad");
    expect(lineTone("curl: (56) The requested URL returned error: 404")).toBe("bad");
    expect(lineTone("      [ok] Hermes Agent")).toBe("ok");
    expect(lineTone("[note] omher@beta: found Hermes")).toBe("plain");
    expect(lineTone("No ERROR here")).toBe("plain");
  });
});
