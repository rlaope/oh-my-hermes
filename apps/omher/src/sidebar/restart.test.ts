import { describe, expect, it, vi } from "vitest";
import type { BridgeEvent } from "../lib/protocol";
import { createRestarts, type RestartDeps } from "./restart";

vi.mock("../state/store", () => ({ getStore: () => ({}) }));

function setup(answers: Awaited<ReturnType<RestartDeps["restart"]>>[], others: { name: string; display_name: string }[] = []) {
  const calls: [string, boolean][] = [];
  let emit: (ev: BridgeEvent) => void = () => {};
  const r = createRestarts({
    restart: async (bot, interrupt) => {
      calls.push([bot, interrupt]);
      return answers.shift() ?? { outcome: "ok" };
    },
    scope: async () => others,
    onEvent: (fn) => {
      emit = fn;
      return () => {};
    },
  });
  return { r, calls, back: (bot: string, ok = true) => emit({ event: "bot.restarted", bot, ok } as BridgeEvent) };
}

describe("restart one bot", () => {
  it("an idle named bot restarts on the first press, without --yes, and is back on bot.restarted", async () => {
    const { r, calls, back } = setup([{ outcome: "ok" }]);
    await r.press("kami");
    expect(calls).toEqual([["kami", false]]);
    expect(r.get("kami").step).toBe("restarting");
    back("kami");
    expect(r.get("kami").step).toBe("idle");
  });

  it("a busy bot shows what Hermes named; only Restart anyway passes --yes", async () => {
    const { r, calls } = setup([{ outcome: "refused", lines: ["chat turn s1"] }, { outcome: "ok" }]);
    await r.press("kami");
    expect(r.get("kami")).toEqual({ step: "refused", lines: ["chat turn s1"] });
    expect(calls).toEqual([["kami", false]]);
    await r.anyway("kami");
    expect(calls).toEqual([
      ["kami", false],
      ["kami", true],
    ]);
  });

  it("Cancel on a refusal restarts nothing", async () => {
    const { r, calls } = setup([{ outcome: "refused", lines: ["x"] }]);
    await r.press("kami");
    r.dismiss("kami");
    await r.anyway("kami"); // no refusal open any more: nothing runs
    expect(calls).toEqual([["kami", false]]);
    expect(r.get("kami").step).toBe("idle");
  });

  it("the default profile names the bots it takes along before anything runs", async () => {
    const { r, calls } = setup([{ outcome: "ok" }], [{ name: "kami", display_name: "Kami" }]);
    await r.press("default");
    expect(r.get("default")).toEqual({ step: "confirm", others: [{ name: "kami", display_name: "Kami" }] });
    expect(calls).toEqual([]);
    await r.confirm("default");
    expect(calls).toEqual([["default", false]]);
  });

  it("a failure keeps Hermes' line; a bot that did not come back says so", async () => {
    const { r, back } = setup([{ outcome: "failed", line: "Gateway service restart failed." }, { outcome: "ok" }]);
    await r.press("kami");
    expect(r.get("kami")).toEqual({ step: "failed", line: "Gateway service restart failed." });
    await r.press("kami"); // Try again
    back("kami", false);
    expect(r.get("kami").step).toBe("failed");
  });
});
