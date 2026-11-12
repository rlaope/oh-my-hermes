// Restart one bot, only on the person's press, through Hermes' own `hermes -p <bot> gateway restart` (the bridge's
// `bots.restart`, BOUNDARY rule 29). Every place that offers it (the bot row's menu, the Plugins sheet when only a
// restart loads a plugin, an offline bot's chat) goes through `press` here, so the row shows one state:
//   idle -> (the default profile: "also restarts N bots" confirm) -> restarting -> back when the bot is attached
//   again (`bot.restarted`); Hermes refused for live work -> the lines it named, Cancel first, then "Restart
//   anyway" (`--yes`); failed -> the last line Hermes printed, once, with "Try again".
// A busy bot is never cut silently: the first press never passes `--yes`. Nothing here restarts by itself.
import { useSyncExternalStore } from "react";
import type { BridgeEvent } from "../lib/protocol";
import { getStore } from "../state/store";

export type RestartState =
  | { step: "idle" }
  | { step: "confirm"; others: { name: string; display_name: string }[] }
  | { step: "restarting" }
  | { step: "refused"; lines: string[] }
  | { step: "failed"; line: string };

export interface RestartDeps {
  restart(bot: string, interrupt: boolean): Promise<
    { outcome: "ok" } | { outcome: "refused"; lines: string[] } | { outcome: "failed"; line: string }
  >;
  scope(bot: string): Promise<{ name: string; display_name: string }[]>;
  onEvent(fn: (ev: BridgeEvent) => void): () => void;
}

const IDLE: RestartState = { step: "idle" };

export function createRestarts(deps: RestartDeps) {
  const states = new Map<string, RestartState>();
  const fns = new Set<() => void>();
  const set = (bot: string, st: RestartState) => {
    if (st.step === "idle") states.delete(bot);
    else states.set(bot, st);
    for (const f of [...fns]) f();
  };
  const get = (bot: string): RestartState => states.get(bot) ?? IDLE;

  deps.onEvent((ev) => {
    if (ev.event !== "bot.restarted" || get(ev.bot).step !== "restarting") return;
    set(ev.bot, ev.ok ? IDLE : { step: "failed", line: "" });
  });

  const run = async (bot: string, interrupt: boolean) => {
    set(bot, { step: "restarting" });
    let r: Awaited<ReturnType<RestartDeps["restart"]>>;
    try {
      r = await deps.restart(bot, interrupt);
    } catch (e) {
      const msg = typeof e === "object" && e && "message" in e ? String((e as { message: unknown }).message) : String(e);
      return set(bot, { step: "failed", line: msg });
    }
    // ok: stays "restarting" until the bridge says the bot is attached again
    if (r.outcome === "refused") set(bot, { step: "refused", lines: r.lines });
    else if (r.outcome === "failed") set(bot, { step: "failed", line: r.line });
  };

  return {
    get,
    subscribe(f: () => void) {
      fns.add(f);
      return () => {
        fns.delete(f);
      };
    },
    /** The press. An idle named bot restarts at once; the default profile first names the bots it takes along. */
    async press(bot: string) {
      const st = get(bot);
      if (st.step === "restarting") return;
      const others = await deps.scope(bot).catch(() => []);
      if (others.length) return set(bot, { step: "confirm", others });
      await run(bot, false);
    },
    /** The confirm's "Restart" (the default profile): still without `--yes`. */
    confirm: (bot: string) => (get(bot).step === "confirm" ? run(bot, false) : Promise.resolve()),
    /** "Restart anyway", offered only after Hermes refused for live work. */
    anyway: (bot: string) => (get(bot).step === "refused" ? run(bot, true) : Promise.resolve()),
    /** Cancel, the x, or a failure read: back to normal. */
    dismiss: (bot: string) => set(bot, IDLE),
  };
}

export type Restarts = ReturnType<typeof createRestarts>;

let single: Restarts | null = null;
export function getRestarts(): Restarts {
  if (!single) {
    const store = getStore();
    single = createRestarts({
      restart: (bot, interrupt) => store.actions.restartBot(bot, interrupt),
      scope: (bot) => store.actions.restartScope(bot),
      onEvent: (fn) => store.actions.onBridgeEvent(fn),
    });
  }
  return single;
}

export function useRestart(bot: string): RestartState {
  const r = getRestarts();
  return useSyncExternalStore(r.subscribe, () => r.get(bot), () => r.get(bot));
}
