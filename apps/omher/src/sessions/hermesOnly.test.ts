// A person who has Hermes but not oh-my-hermes (`omh`): the + menu's oh-my-hermes row reads "Hermes" and opens the
// same Hermes chat in the folder; the offer to add oh-my-hermes runs the shell's one installer, once per press.
import { describe, expect, it, vi } from "vitest";
import { AGENTS, agentLabel, hermesOnly, HERMES_LABEL, menuOrder, rowModel, type AgentId, type AgentInfo, type SessionRec } from "./agents";
import { createAddOmh, failLine } from "./addOmh";
import type { GateShell, InstallEvent } from "../app/BridgeGate";

const info = (installed: AgentId[], omh: "omh" | "hermes" | "none"): AgentInfo[] =>
  AGENTS.map((a) =>
    a.id === "omh"
      ? omh === "omh"
        ? { id: a.id, label: a.label, mode: a.mode, path: "/u/.local/bin/omh" }
        : omh === "hermes"
          ? { id: a.id, label: HERMES_LABEL, mode: a.mode, path: "/u/.hermes/hermes-agent/venv/bin/python", via: "hermes" }
          : { id: a.id, label: a.label, mode: a.mode, path: null }
      : { id: a.id, label: a.label, mode: a.mode, path: installed.includes(a.id) ? `/bin/${a.id}` : null },
  );

const rec = (over: Partial<SessionRec> = {}): SessionRec => ({
  id: "s1",
  agent: "omh",
  cwd: "/Users/you/code/web-app",
  startedAt: 1_700_000_000_000,
  status: "running",
  view: "chat",
  bot: "kami",
  ...over,
});

describe("Hermes without oh-my-hermes", () => {
  it("is told apart from both and from neither", () => {
    expect(hermesOnly(info(["claude"], "hermes"))).toBe(true);
    expect(hermesOnly(info(["claude"], "omh"))).toBe(false);
    expect(hermesOnly(info(["claude"], "none"))).toBe(false);
    // before the look-up answers nothing is offered
    expect(hermesOnly(null)).toBe(false);
  });

  it("names the row Hermes only then; every other agent keeps its name", () => {
    expect(agentLabel("omh", info([], "hermes"))).toBe("Hermes");
    expect(agentLabel("omh", info([], "omh"))).toBe("oh-my-hermes");
    expect(agentLabel("omh", info([], "none"))).toBe("oh-my-hermes");
    expect(agentLabel("omh", null)).toBe("oh-my-hermes");
    expect(agentLabel("claude", info([], "hermes"))).toBe("Claude Code");
  });

  it("lists the Hermes row with the installed agents (it can be picked)", () => {
    const order = menuOrder(info(["claude"], "hermes"), []).map((a) => a.id);
    expect(order.slice(0, 2)).toEqual(["claude", "omh"]);
    expect(menuOrder(info(["claude"], "none"), []).map((a) => a.id).indexOf("omh")).toBeGreaterThan(1);
  });

  it("names the session's row Hermes on its second line", () => {
    expect(rowModel(rec(), undefined, { cwds: [], home: "/Users/you", agents: info([], "hermes") }).sub).toBe("Hermes");
    expect(rowModel(rec(), undefined, { cwds: [], home: "/Users/you", agents: info([], "omh") }).sub).toBe("oh-my-hermes");
  });
});

/** A stand-in for the shell: plays `lines`, then exits with `code` (or refuses with `refuse`). */
function shell(lines: string[], code: number | null, refuse?: string): GateShell & { install: ReturnType<typeof vi.fn> } {
  return {
    status: async () => ({ state: "ready" }),
    retry: async () => {},
    installCommand: async () => "",
    install: vi.fn(async (on: (e: InstallEvent) => void) => {
      for (const text of lines) on({ kind: "line", text });
      if (refuse) throw new Error(refuse);
      on({ kind: "exit", code });
      return code;
    }),
  };
}

describe("adding oh-my-hermes", () => {
  it("runs the installer once, then reads the agents again and goes back to idle", async () => {
    const s = shell(["[ok] omh installed"], 0);
    const reload = vi.fn(async () => {});
    const add = createAddOmh(async () => s, reload);
    const seen: string[] = [];
    add.subscribe(() => seen.push(add.getState().phase));
    const run = add.run();
    // a second press while it runs starts nothing
    void add.run();
    await run;
    expect(s.install).toHaveBeenCalledTimes(1);
    expect(reload).toHaveBeenCalledTimes(1);
    expect(seen[0]).toBe("running");
    expect(add.getState()).toEqual({ phase: "idle", lines: [], error: null });
  });

  it("keeps the last line on a failed run and runs again on the next press", async () => {
    const s = shell(["Installing oh-my-hermes …", "[failed] could not reach github.com", ""], 1);
    const reload = vi.fn(async () => {});
    const add = createAddOmh(async () => s, reload);
    await add.run();
    expect(add.getState().phase).toBe("failed");
    expect(add.getState().error).toBe("[failed] could not reach github.com");
    expect(reload).not.toHaveBeenCalled();
    await add.run();
    expect(s.install).toHaveBeenCalledTimes(2);
  });

  it("says what the shell refused with, and that nothing could run without a shell", async () => {
    const refused = createAddOmh(async () => shell([], null, "the installer is already running"), async () => {});
    await refused.run();
    expect(refused.getState().error).toBe("the installer is already running");
    const none = createAddOmh(async () => null, async () => {});
    await none.run();
    expect(none.getState().error).toBe("The installer could not run.");
  });

  it("sums a silent failure up by its exit code", () => {
    expect(failLine([], 3, null)).toBe("The installer stopped (exit 3).");
    expect(failLine(["a", "b "], 3, null)).toBe("b");
  });
});
