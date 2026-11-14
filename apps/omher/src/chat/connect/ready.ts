// Whether a bot can answer: Hermes' own readiness probe (`bots.ready` -> the bot's `setup.runtime_check`), asked once
// per bot and kept until a chat error, or (for a bot that could not answer) until the window comes back to the front.
// A bot that can answer shows nothing; one that cannot shows the chat's connect block (ConnectBlock.tsx).
//
// After the person picks a sign-in in the block (a system terminal runs `hermes auth add <id>`), the bot is asked
// again every 3 s for up to 10 min, and at once when the window comes back to the front. `hermes auth add` stores the
// login only: it writes no model, and for `anthropic` it does not make the provider the active one either, so the
// bot's own check can still say no. Then the strict check for that provider (`bots.ready {provider}`) tells whether the
// sign-in itself landed; when it did, the main chat gets that provider and its first model from the bot's own
// `models.options` list that is not an Opus or Fable tier (Hermes' own cost-safe pick), through `chat.set_model`, the
// same path as the model menu. Nothing here writes config.
import { useSyncExternalStore } from "react";
import type { BotReady, ModelOptions } from "../../lib/protocol";
import { getStore } from "../../state/store";

/** The providers whose own sign-in the block opens (src-tauri hermes_auth.rs SIGN_IN). */
export const SIGN_IN = ["openai-codex", "anthropic", "nous"] as const;
export type SignIn = (typeof SIGN_IN)[number];
export const isSignIn = (p: string): p is SignIn => (SIGN_IN as readonly string[]).includes(p);

export const POLL_MS = 3_000;
export const WAIT_MS = 10 * 60_000;

/** checking: asked, no answer yet (nothing shows). ready: the bot can answer. not: it cannot (the block shows). */
export type ReadyStatus = "checking" | "ready" | "not";

export interface BotReadyState {
  status: ReadyStatus;
  /** Hermes' own sentence when it cannot answer. */
  error: string;
  /** The sign-in the person opened, while the block waits for it. */
  waiting: SignIn | null;
  /** Ask again the next time the bot's chat is on screen. */
  stale: boolean;
}

const NONE: BotReadyState = { status: "checking", error: "", waiting: null, stale: true };

/** Hermes' rule for a model chosen without asking: the first one that is not an Anthropic Opus or Fable tier, else
 *  the first (hermes_cli/models.py `pick_silent_default_model`). */
export function pickModel(models: readonly string[]): string {
  const base = (m: string) => m.toLowerCase().split("/").pop() ?? "";
  return models.find((m) => !/^claude-(opus|fable)-/.test(base(m))) ?? models[0] ?? "";
}

export interface ReadyDeps {
  ask(bot: string, provider?: SignIn): Promise<BotReady>;
  /** The bot's models list (the store's copy, read again when `fresh`). */
  models(bot: string, fresh?: boolean): Promise<ModelOptions | undefined>;
  setModel(bot: string, provider: SignIn, model: string): Promise<void>;
  /** The provider the bot's main chat runs on now ("" when not known). */
  chatProvider(bot: string): string;
  now(): number;
  every(fn: () => void, ms: number): () => void;
}

export function createReady(deps: ReadyDeps) {
  let states: Record<string, BotReadyState> = {};
  const polls = new Map<string, { stop: () => void; since: number; busy: boolean }>();
  const fns = new Set<() => void>();
  const asking = new Set<string>();
  const set = (bot: string, p: Partial<BotReadyState>) => {
    states = { ...states, [bot]: { ...(states[bot] ?? NONE), ...p } };
    for (const f of [...fns]) f();
  };

  /** The main chat on `provider` with a model that provider lists, through the model menu's own path. */
  const ensureModel = async (bot: string, provider: SignIn) => {
    let opts = await deps.models(bot);
    if (!opts?.providers.some((p) => p.slug === provider)) opts = await deps.models(bot, true);
    const list = opts?.providers.find((p) => p.slug === provider)?.models ?? [];
    if (opts?.current.provider === provider && list.includes(opts.current.model)) return;
    const model = pickModel(list);
    if (model) await deps.setModel(bot, provider, model);
  };

  /** Can `bot` answer? `want`: the sign-in the person just opened. */
  const verdict = async (bot: string, want?: SignIn): Promise<{ ok: boolean; error: string }> => {
    const r = await deps.ask(bot);
    if (r.unknown) return { ok: true, error: "" };
    if (r.ok) {
      if (want && r.provider === want) await ensureModel(bot, want);
      return { ok: true, error: "" };
    }
    // The bot's own check says no. A finished sign-in (or the chat already on a signed-in provider) still answers
    // when the strict check for that provider passes and the chat runs on it.
    const chat = deps.chatProvider(bot);
    const signed = want ?? (isSignIn(chat) ? chat : null);
    if (!signed) return { ok: false, error: r.error };
    const strict = await deps.ask(bot, signed);
    if (!strict.ok || strict.unknown) return { ok: false, error: r.error };
    await ensureModel(bot, signed);
    return { ok: true, error: "" };
  };

  const stop = (bot: string) => {
    polls.get(bot)?.stop();
    polls.delete(bot);
  };

  /** Ask about `bot` when nothing fresh is known (one `bots.ready` per selection; a ready answer is kept). */
  const ensure = async (bot: string) => {
    const cur = states[bot];
    if ((cur && !cur.stale) || asking.has(bot) || polls.has(bot)) return;
    asking.add(bot);
    set(bot, { stale: false, status: cur?.status === "not" ? "not" : "checking" });
    try {
      const v = await verdict(bot);
      set(bot, { status: v.ok ? "ready" : "not", error: v.error });
    } catch {
      // offline or no bridge: no verdict; the chat's own offline notice says what is wrong
      set(bot, { status: cur?.status ?? "ready", stale: true });
    } finally {
      asking.delete(bot);
    }
  };

  const tick = async (bot: string, provider: SignIn) => {
    const poll = polls.get(bot);
    if (!poll || poll.busy) return;
    if (deps.now() - poll.since > WAIT_MS) {
      stop(bot);
      return set(bot, { waiting: null });
    }
    poll.busy = true;
    try {
      const v = await verdict(bot, provider);
      if (polls.get(bot) !== poll) return;
      if (v.ok) {
        stop(bot);
        set(bot, { status: "ready", error: "", waiting: null, stale: false });
      }
    } catch {
      /* asked again on the next tick */
    } finally {
      poll.busy = false;
    }
  };

  /** The person opened `provider`'s sign-in for `bot`: wait for it. */
  const waitFor = (bot: string, provider: SignIn) => {
    stop(bot);
    const poll = { stop: () => {}, since: deps.now(), busy: false };
    polls.set(bot, poll);
    poll.stop = deps.every(() => void tick(bot, provider), POLL_MS);
    set(bot, { waiting: provider, status: "not" });
  };

  /** A chat error: ask again the next time the chat is on screen. */
  const invalidate = (bot: string) => {
    if (states[bot] && !polls.has(bot)) set(bot, { stale: true });
  };

  /** The window came back to the front: a waiting sign-in is asked at once; a bot that could not answer is asked
   *  again when its chat shows. A bot that answers is not asked (its answer holds until a chat error). */
  const focused = () => {
    for (const [bot, s] of Object.entries(states)) {
      if (s.waiting) void tick(bot, s.waiting);
      else if (s.status === "not") set(bot, { stale: true });
    }
  };

  return {
    get: (bot: string): BotReadyState => states[bot] ?? NONE,
    subscribe(f: () => void) {
      fns.add(f);
      return () => {
        fns.delete(f);
      };
    },
    getStates: () => states,
    ensure,
    waitFor,
    invalidate,
    focused,
    stop,
  };
}

export type Ready = ReturnType<typeof createReady>;

let single: Ready | null = null;
export function getReady(): Ready {
  if (!single) {
    const store = getStore();
    const r = createReady({
      ask: (bot, provider) => store.actions.botReady(bot, provider),
      async models(bot, fresh) {
        if (fresh || !store.getState().models[bot]) await store.actions.loadModels(bot);
        return store.getState().models[bot];
      },
      setModel: (bot, provider, model) => store.actions.setModel({ provider, model }, bot),
      chatProvider: (bot) => store.getState().chats[bot]?.provider ?? "",
      now: () => Date.now(),
      every(fn, ms) {
        const h = setInterval(fn, ms);
        return () => clearInterval(h);
      },
    });
    if (typeof window !== "undefined") window.addEventListener("focus", () => r.focused());
    // a turn that ended in an error may mean the bot lost its account: ask again
    store.actions.onBridgeEvent((ev) => {
      if (ev.event === "turn.end" && ev.outcome === "error" && !ev.session) r.invalidate(ev.bot);
    });
    single = r;
  }
  return single;
}

export function useBotReady(bot: string): BotReadyState {
  const r = getReady();
  const get = () => r.get(bot);
  return useSyncExternalStore(r.subscribe, get, get);
}
