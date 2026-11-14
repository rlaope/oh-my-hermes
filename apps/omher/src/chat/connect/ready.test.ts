import { describe, expect, it } from "vitest";
import type { BotReady, ModelOptions } from "../../lib/protocol";
import { POLL_MS, WAIT_MS, createReady, pickModel, type ReadyDeps, type SignIn } from "./ready";

const NO = "Hermes is not connected to any AI provider yet.";
const ok = (provider = "claude-proxy", model = "m"): BotReady => ({ ok: true, provider, model, error: "" });
const no = (error = NO): BotReady => ({ ok: false, provider: "", model: "", error });
const opts = (current: { provider: string; model: string }, extra: { slug: string; models: string[] }[] = []): ModelOptions => ({
  providers: [{ slug: "claude-proxy", name: "Claude", models: ["Opus 5.5"] }, ...extra.map((e) => ({ ...e, name: e.slug }))],
  current: { ...current, reasoning: "" },
  reasoning_levels: [],
});
const flush = () => new Promise((r) => setTimeout(r, 0));

/** A fake bridge: `answer(provider?)` decides each bots.ready; timers run by hand. */
function make(answer: (provider?: SignIn) => BotReady, models: () => ModelOptions = () => opts({ provider: "", model: "" }), chat = "") {
  const asks: (string | undefined)[] = [];
  const sets: { bot: string; provider: string; model: string }[] = [];
  const modelReads: boolean[] = [];
  let clock = 0;
  let ticks: (() => void)[] = [];
  let chatProvider = chat;
  const deps: ReadyDeps = {
    ask: async (_bot, provider) => {
      asks.push(provider);
      return answer(provider);
    },
    models: async (_bot, fresh) => {
      modelReads.push(!!fresh);
      return models();
    },
    setModel: async (bot, provider, model) => {
      sets.push({ bot, provider, model });
      chatProvider = provider;
    },
    chatProvider: () => chatProvider,
    now: () => clock,
    every(fn) {
      ticks.push(fn);
      return () => {
        ticks = ticks.filter((f) => f !== fn);
      };
    },
  };
  const r = createReady(deps);
  return {
    r,
    asks,
    sets,
    modelReads,
    pollers: () => ticks.length,
    async tick(ms = POLL_MS) {
      clock += ms;
      for (const f of [...ticks]) f();
      await flush();
      await flush();
    },
  };
}

describe("pickModel", () => {
  it("takes Hermes' cost-safe pick: the first model that is not an Opus or Fable tier", () => {
    expect(pickModel(["claude-opus-5-5", "claude-sonnet-5"])).toBe("claude-sonnet-5");
    expect(pickModel(["anthropic/claude-fable-5.2", "moonshotai/kimi-k3"])).toBe("moonshotai/kimi-k3");
    expect(pickModel(["gpt-6-sol", "gpt-6-luna"])).toBe("gpt-6-sol");
    expect(pickModel(["claude-opus-5-5"])).toBe("claude-opus-5-5");
    expect(pickModel([])).toBe("");
  });
});

describe("bot readiness", () => {
  it("a ready bot is asked once and shows nothing; a focus does not ask it again", async () => {
    const f = make(() => ok());
    await f.r.ensure("kami");
    await f.r.ensure("kami");
    expect(f.r.get("kami").status).toBe("ready");
    f.r.focused();
    await f.r.ensure("kami");
    expect(f.asks).toEqual([undefined]);
  });

  it("a bot Hermes says cannot answer shows the block with Hermes' sentence; a focus asks it again", async () => {
    const f = make(() => no());
    await f.r.ensure("kami");
    expect(f.r.get("kami")).toMatchObject({ status: "not", error: NO, waiting: null });
    f.r.focused();
    expect(f.r.get("kami").stale).toBe(true);
    await f.r.ensure("kami");
    expect(f.asks).toEqual([undefined, undefined]);
  });

  it("a chat error makes a ready bot be asked again", async () => {
    const f = make(() => ok());
    await f.r.ensure("kami");
    f.r.invalidate("kami");
    await f.r.ensure("kami");
    expect(f.asks.length).toBe(2);
  });

  it("an unknown answer (older Hermes, still checking) counts as ready", async () => {
    const f = make(() => ({ ...no(), unknown: true }));
    await f.r.ensure("kami");
    expect(f.r.get("kami").status).toBe("ready");
  });

  it("each bot is its own: multi-bot users see the block only on the bot that cannot answer", async () => {
    const f = make(() => no());
    await f.r.ensure("friren");
    const g = make(() => ok());
    await g.r.ensure("kami");
    expect(f.r.get("friren").status).toBe("not");
    expect(f.r.get("kami").status).toBe("checking");
    expect(g.r.get("kami").status).toBe("ready");
  });

  it("after a sign-in: polls every 3 s, sets the provider's cost-safe model once its strict check passes, clears", async () => {
    let signed = false;
    const f = make(
      (provider) => (provider ? (signed && provider === "anthropic" ? ok("anthropic", "z-ai/glm-5.3") : no()) : no()),
      () => opts({ provider: "", model: "" }, signed ? [{ slug: "anthropic", models: ["claude-opus-5-5", "claude-sonnet-5"] }] : []),
    );
    await f.r.ensure("kami");
    f.r.waitFor("kami", "anthropic");
    expect(f.r.get("kami")).toMatchObject({ status: "not", waiting: "anthropic" });
    await f.tick();
    expect(f.r.get("kami").waiting).toBe("anthropic");
    expect(f.sets).toEqual([]);
    signed = true;
    await f.tick();
    expect(f.sets).toEqual([{ bot: "kami", provider: "anthropic", model: "claude-sonnet-5" }]);
    expect(f.r.get("kami")).toMatchObject({ status: "ready", waiting: null });
    expect(f.pollers()).toBe(0);
  });

  it("a sign-in whose own check already passes on that provider still gets a model the provider lists", async () => {
    let signed = false;
    const f = make(
      () => (signed ? ok("openai-codex", "z-ai/glm-5.3") : no()),
      () => opts({ provider: "", model: "z-ai/glm-5.3" }, [{ slug: "openai-codex", models: ["gpt-6-sol"] }]),
    );
    await f.r.ensure("kami");
    f.r.waitFor("kami", "openai-codex");
    signed = true;
    await f.tick();
    expect(f.sets).toEqual([{ bot: "kami", provider: "openai-codex", model: "gpt-6-sol" }]);
    expect(f.r.get("kami").status).toBe("ready");
  });

  it("re-reads a models list that does not name the provider yet", async () => {
    let first = true;
    const g = make(
      (p) => (p === "nous" ? ok("nous") : no()),
      () => {
        const o = first ? opts({ provider: "", model: "" }) : opts({ provider: "", model: "" }, [{ slug: "nous", models: ["moonshotai/kimi-k3"] }]);
        first = false;
        return o;
      },
    );
    await g.r.ensure("kami");
    g.r.waitFor("kami", "nous");
    await g.tick();
    expect(g.modelReads).toEqual([false, true]);
    expect(g.sets).toEqual([{ bot: "kami", provider: "nous", model: "moonshotai/kimi-k3" }]);
  });

  it("a focus asks a waiting sign-in at once", async () => {
    let signed = false;
    const f = make((p) => (signed && p === "anthropic" ? ok("anthropic") : no()), () => opts({ provider: "", model: "" }, [{ slug: "anthropic", models: ["claude-sonnet-5"] }]));
    await f.r.ensure("kami");
    f.r.waitFor("kami", "anthropic");
    signed = true;
    f.r.focused();
    await flush();
    await flush();
    expect(f.r.get("kami").status).toBe("ready");
  });

  it("stops waiting after 10 minutes; the block stays and offers the sign-ins again", async () => {
    const f = make(() => no());
    await f.r.ensure("kami");
    f.r.waitFor("kami", "anthropic");
    await f.tick(WAIT_MS + 1);
    expect(f.r.get("kami")).toMatchObject({ status: "not", waiting: null });
    expect(f.pollers()).toBe(0);
  });

  it("a bot whose chat already runs on a signed-in provider is ready when that provider's strict check passes", async () => {
    // e.g. the app opened again after a sign-in: the bot's own check says no (anthropic is not Hermes' active
    // provider), but its chat runs on anthropic with a model anthropic lists
    const on = () => opts({ provider: "anthropic", model: "claude-sonnet-5" }, [{ slug: "anthropic", models: ["claude-sonnet-5"] }]);
    const f = make((p) => (p === "anthropic" ? ok("anthropic") : no()), on, "anthropic");
    await f.r.ensure("kami");
    expect(f.r.get("kami").status).toBe("ready");
    expect(f.asks).toEqual([undefined, "anthropic"]);
    expect(f.sets).toEqual([]); // already on a model the provider lists: nothing is changed
    // a chat on a provider that is not one of the sign-ins is not second-guessed
    const g = make(() => no(), () => opts({ provider: "claude-proxy", model: "Opus 5.5" }), "claude-proxy");
    await g.r.ensure("kami");
    expect(g.r.get("kami").status).toBe("not");
    expect(g.asks).toEqual([undefined]);
  });
});
