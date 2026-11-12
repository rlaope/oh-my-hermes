// The one-time model-setup line after omher's own oh-my-hermes install: the command comes from the bot's skills, the
// line is offered once (pending -> done on this computer), and a bot whose skills never show it gets the restart line.
import { describe, expect, it } from "vitest";
import type { Skill } from "../lib/protocol";
import { createOmhPrompt, modelSetupCommand, PROMPT_KEY, promptText, restartCommand } from "./omhPrompt";

const mem = (init: Record<string, string> = {}) => {
  const m = new Map(Object.entries(init));
  return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v), m };
};
const sk = (...names: string[]): Skill[] => names.map((name) => ({ name, description: "" }));

function make(lists: Skill[][], init: Record<string, string> = {}) {
  const storage = mem(init);
  let reads = 0;
  let shown = 0;
  const p = createOmhPrompt({
    storage,
    skills: async () => lists[Math.min(reads++, lists.length - 1)],
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

  it("restart command: Hermes' own, the profile named unless it is the default", () => {
    expect(restartCommand({ name: "kami", is_default: false })).toBe("hermes -p kami gateway restart");
    expect(restartCommand({ name: "default", is_default: true })).toBe("hermes gateway restart");
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
    expect(p.getState()).toEqual({ phase: "ready", bot: "kami", command: "/omh-model-setup" });
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
