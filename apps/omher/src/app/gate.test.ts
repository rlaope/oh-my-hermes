import { describe, expect, it } from "vitest";
import { appendLine, gateMode, lineTone, pollMs, type GateMode } from "./BridgeGate";

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
    expect(lineTone("[note] omher: found Hermes")).toBe("plain");
    expect(lineTone("No ERROR here")).toBe("plain");
  });
});

describe("the gate after the app was up", () => {
  const walk = (states: ("ready" | "starting" | "failed" | undefined)[]) => {
    const modes: GateMode[] = [];
    let m: GateMode = "boot";
    for (const st of states) modes.push((m = gateMode(m, st)));
    return modes;
  };

  it("shows its screen alone until the bridge is first ready", () => {
    expect(walk([undefined, "starting", "failed", "starting", "ready"])).toEqual(["boot", "boot", "boot", "boot", "up"]);
  });

  it("leaves the app alone while a bridge that died is started again", () => {
    expect(walk(["ready", "starting", "starting", "ready"])).toEqual(["up", "up", "up", "up"]);
  });

  it("covers the app when the shell gives up, until Retry brings the bridge back", () => {
    expect(walk(["ready", "starting", "failed", "starting", "failed", "ready"])).toEqual(["up", "up", "down", "down", "down", "up"]);
  });

  it("keeps asking the shell after ready, less often", () => {
    expect(pollMs(false)).toBe(500);
    expect(pollMs(true)).toBe(2000);
  });
});
