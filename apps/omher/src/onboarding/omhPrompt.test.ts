// The one-time model-setup line after omher's own oh-my-hermes install: the command comes from the bot's skills, the
// line is offered once (pending -> done on this computer), and a bot whose skills never show it gets the restart line.
import { describe, expect, it } from "vitest";
import type { PluginRow, Skill } from "../lib/protocol";
import { createOmhPrompt, modelSetupCommand, omhPluginLoaded, PROMPT_KEY, promptText } from "./omhPrompt";

const mem = (init: Record<string, string> = {}) => {
  const m = new Map(Object.entries(init));
  return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v), m };
};
const sk = (...names: string[]): Skill[] => names.map((name) => ({ name, description: "" }));

const omhRow = (enabled: boolean, live?: number): PluginRow =>
  ({ name: "omh", key: "omh", title: "", version: "4.0.7", description: "", source: "user", enabled, tier: "user", category: "",
     catalog_name: null, tools: 23, hooks: 6, update_available: false, needs_env: [], ...(live === undefined ? {} : { live_tools: live }) });

function make(lists: Skill[][], init: Record<string, string> = {}, plugins: PluginRow[] | null = [omhRow(true, 23)]) {
  const storage = mem(init);
  let reads = 0;
  let shown = 0;
  const p = createOmhPrompt({
    storage,
    skills: async () => lists[Math.min(reads++, lists.length - 1)],
    plugins: async () => plugins,
    sleep: async () => {},
    showChat: () => void (shown += 1),
    delays: [0, 1, 1, 1],
  });
  return { p, storage, reads: () => reads, shown: () => shown };
}

describe("the model-setup command", () => {
  it("is taken from the bot's skills, with its slash, never guessed", () => {
    expect(modelSetupCommand(sk("plan", "omh-model-setup", "review"))).toBe("/omh-model-setup");
    expect(modelSetupCommand(sk("model-setup"))).toBe("/model-setup");
    expect(modelSetupCommand(sk("plan", "model-setup-notes", "omh-model-optimization"))).toBeNull();
    expect(modelSetupCommand([])).toBeNull();
  });

  it("is followed by one sentence that names no key", () => {
    const text = promptText("/omh-model-setup");
    expect(text.startsWith("/omh-model-setup Set up my models")).toBe(true);
    expect(text).not.toMatch(/key|token|secret|password/i);
  });
});

describe("the one-time line", () => {
  it("is off for a person who never installed through omher", () => {
    const { p } = make([sk("omh-model-setup")]);
    expect(p.getState().phase).toBe("off");
  });

  it("install -> pending -> ready once the bot lists the command; the chat is shown", async () => {
    const { p, storage, shown } = make([sk("plan"), sk("plan", "omh-model-setup")]);
    p.installed();
    expect(p.getState().phase).toBe("pending");
    expect(storage.m.get(PROMPT_KEY)).toBe("pending");
    expect(shown()).toBe(1);
    await p.check("kami");
    expect(p.getState()).toEqual({ phase: "ready", bot: "kami", command: "/omh-model-setup", restart: false });
  });

  it("asks again, then gives the restart line when the command never shows", async () => {
    const { p, reads } = make([sk("plan")]);
    p.installed();
    await p.check("kami");
    expect(reads()).toBe(4);
    expect(p.getState().phase).toBe("restart");
  });

  it("finish: gone and never offered again, across a restart", async () => {
    const { p, storage } = make([sk("omh-model-setup")]);
    p.installed();
    await p.check("kami");
    p.finish();
    expect(p.getState().phase).toBe("off");
    expect(storage.m.get(PROMPT_KEY)).toBe("done");
    p.installed(); // a second install through omher
    expect(p.getState().phase).toBe("off");
    const again = make([sk("omh-model-setup")], { [PROMPT_KEY]: "done" });
    expect(again.p.getState().phase).toBe("off");
  });

  it("a pending offer survives a restart until it is used", () => {
    const { p } = make([sk("omh-model-setup")], { [PROMPT_KEY]: "pending" });
    expect(p.getState().phase).toBe("pending");
  });

  it("closing it while it still asks stops the asking", async () => {
    const lists = [sk("plan")];
    const storage = mem();
    let reads = 0;
    const p = createOmhPrompt({
      storage,
      skills: async () => (reads++, lists[0]),
      plugins: async () => null,
      sleep: async () => {
        if (reads === 2) p.finish();
      },
      showChat: () => {},
      delays: [0, 1, 1, 1, 1],
    });
    p.installed();
    await p.check("kami");
    expect(reads).toBe(2);
    expect(p.getState().phase).toBe("off");
  });
});

describe("a gateway that has not loaded oh-my-hermes' plugin yet", () => {
  it("is told only by the running gateway's own record: omh enabled, no tool of its own registered", () => {
    expect(omhPluginLoaded([omhRow(true, 0)])).toBe(false);
    expect(omhPluginLoaded([omhRow(true, 23)])).toBe(true);
    // not enabled, no row, an older bridge without the field, or no answer: unknown, so no restart line
    expect(omhPluginLoaded([omhRow(false, 0)])).toBeNull();
    expect(omhPluginLoaded([])).toBeNull();
    expect(omhPluginLoaded([omhRow(true)])).toBeNull();
    expect(omhPluginLoaded(null)).toBeNull();
  });

  it("the ready line comes with the restart line under it; the action leaves only the restart line, this run", async () => {
    const { p, storage } = make([sk("omh-model-setup")], {}, [omhRow(true, 0)]);
    p.installed();
    await p.check("kami");
    expect(p.getState()).toMatchObject({ phase: "ready", restart: true });
    p.used();
    expect(p.getState()).toMatchObject({ phase: "restart", command: "/omh-model-setup" });
    expect(storage.m.get(PROMPT_KEY)).toBe("done");
    p.finish();
    expect(p.getState().phase).toBe("off");
  });

  it("a loaded plugin, or one omher cannot ask about, gets no restart line", async () => {
    for (const rows of [[omhRow(true, 23)], null]) {
      const { p } = make([sk("omh-model-setup")], {}, rows);
      p.installed();
      await p.check("kami");
      expect(p.getState()).toMatchObject({ phase: "ready", restart: false });
      p.used();
      expect(p.getState().phase).toBe("off");
    }
  });
});
