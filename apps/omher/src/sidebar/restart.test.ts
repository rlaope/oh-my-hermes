import { describe, expect, it, vi } from "vitest";
import type { BridgeEvent, RestartResult, RestartScope, WorkUnit } from "../lib/protocol";
import { createRestarts } from "./restart";

vi.mock("../state/store", () => ({ getStore: () => ({}) }));

const HOST: RestartScope = {
  gateway: "default",
  bots: [
    { name: "default", display_name: "Hermes" },
    { name: "kami", display_name: "Kami" },
    { name: "friren", display_name: "Friren" },
  ],
};

function setup(answers: RestartResult[], scope: RestartScope = HOST) {
  const calls: [string, boolean][] = [];
  let emit: (ev: BridgeEvent) => void = () => {};
  const r = createRestarts({
    restart: async (bot, interrupt) => {
      calls.push([bot, interrupt]);
      return answers.shift() ?? { outcome: "ok" };
    },
    scope: async () => scope,
    onEvent: (fn) => {
      emit = fn;
      return () => {};
    },
  });
  return { r, calls, back: (bot: string, ok = true) => emit({ event: "bot.restarted", bot, ok } as BridgeEvent) };
}

const chat = (bot: string | null, secs = 60): WorkUnit => ({ kind: "chat", name: null, secs, bot });

describe("restart the gateway that serves a bot", () => {
  it("one press, no confirm, no --yes; every bot on that gateway reads restarting until it is back", async () => {
    const { r, calls, back } = setup([{ outcome: "ok", bots: ["default", "kami", "friren"] }]);
    await r.press("kami");
    expect(calls).toEqual([["kami", false]]);
    expect(["default", "kami", "friren"].map((b) => r.get(b).step)).toEqual(["restarting", "restarting", "restarting"]);
    back("kami");
    back("default");
    expect(r.get("kami").step).toBe("idle");
    expect(r.get("default").step).toBe("idle");
    expect(r.get("friren").step).toBe("restarting");
    back("friren");
    expect(r.get("friren").step).toBe("idle");
  });

  it("a busy gateway: Hermes' list under the pressed bot with whose each is; only Restart anyway passes --yes", async () => {
    const work = [chat("kami", 180), { kind: "cron", name: "PR digest", secs: 40, bot: "friren" } as WorkUnit];
    const { r, calls } = setup([{ outcome: "refused", work }, { outcome: "ok" }]);
    await r.press("kami");
    expect(r.get("kami")).toEqual({ step: "refused", work, bots: HOST.bots });
    expect(r.get("friren").step).toBe("idle"); // nothing went down
    expect(calls).toEqual([["kami", false]]);
    await r.anyway("kami");
    expect(calls).toEqual([
      ["kami", false],
      ["kami", true],
    ]);
  });

  it("Cancel on a refusal restarts nothing", async () => {
    const { r, calls } = setup([{ outcome: "refused", work: [chat(null)] }]);
    await r.press("kami");
    r.dismiss("kami");
    await r.anyway("kami"); // no refusal open any more: nothing runs
    expect(calls).toEqual([["kami", false]]);
    expect(r.get("kami").step).toBe("idle");
  });

  it("a bot that shares its gateway names its mates before the press; a standalone bot names none", async () => {
    const shared = setup([]);
    expect(shared.r.mates("kami")).toEqual([]);
    shared.r.ensure("kami");
    await vi.waitFor(() => expect(shared.r.mates("kami").map((m) => m.name)).toEqual(["default", "friren"]));
    const solo = setup([], { gateway: "solo", bots: [{ name: "solo", display_name: "Solo" }] });
    solo.r.ensure("solo");
    await new Promise((res) => setTimeout(res, 0));
    expect(solo.r.mates("solo")).toEqual([]);
  });

  it("a failure keeps Hermes' line and frees the other rows; a bot that did not come back says so", async () => {
    const { r, back } = setup([{ outcome: "failed", line: "Gateway service restart failed." }, { outcome: "ok" }]);
    await r.press("kami");
    expect(r.get("kami")).toEqual({ step: "failed", line: "Gateway service restart failed." });
    expect(r.get("friren").step).toBe("idle");
    await r.press("kami"); // Try again
    back("kami", false);
    expect(r.get("kami").step).toBe("failed");
  });
});
