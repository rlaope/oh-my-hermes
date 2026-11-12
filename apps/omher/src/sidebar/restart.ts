// Restart, only on the person's press: Hermes' own `hermes gateway restart` of the PROCESS that serves the bot (the
// bridge's `bots.restart`, BOUNDARY rule 29): the host gateway for a bot it serves, the bot's own gateway for a
// standalone one. Every place that offers it (the bot row's menu, the Plugins sheet when only a restart loads a
// plugin, an offline bot's chat, the omh load line) goes through `press` here:
//   idle -> every bot on that gateway reads "restarting" -> each back when the bridge says it is attached again
//   (`bot.restarted`); Hermes refused for live work -> under the pressed row, what it named in plain words with whose
//   it is, Cancel first, then "Restart anyway" (`--yes`); failed -> the last line Hermes printed, once, with "Try again".
// A busy bot is never cut silently: the first press never passes `--yes`. Nothing here restarts by itself.
import { useEffect, useSyncExternalStore } from "react";
import type { BridgeEvent, RestartResult, RestartScope, WorkUnit } from "../lib/protocol";
import { getStore } from "../state/store";

type Named = RestartScope["bots"][number];

export type RestartState =
  | { step: "idle" }
  | { step: "restarting" }
  | { step: "refused"; work: WorkUnit[]; bots: Named[] }
  | { step: "failed"; line: string };

export interface RestartDeps {
  restart(bot: string, interrupt: boolean): Promise<RestartResult>;
  scope(bot: string): Promise<RestartScope>;
  onEvent(fn: (ev: BridgeEvent) => void): () => void;
}

const IDLE: RestartState = { step: "idle" };
const NONE: Named[] = [];

export function createRestarts(deps: RestartDeps) {
  const states = new Map<string, RestartState>();
  // per bot: the bots on its gateway (it included), and the others (stable arrays, for useSyncExternalStore)
  const scopes = new Map<string, { all: Named[]; others: Named[] }>();
  const asked = new Set<string>();
  const fns = new Set<() => void>();
  const changed = () => {
    for (const f of [...fns]) f();
  };
  const put = (bot: string, st: RestartState) => {
    if (st.step === "idle") states.delete(bot);
    else states.set(bot, st);
  };
  const set = (bot: string, st: RestartState) => {
    put(bot, st);
    changed();
  };
  const get = (bot: string): RestartState => states.get(bot) ?? IDLE;

  deps.onEvent((ev) => {
    if (ev.event !== "bot.restarted" || get(ev.bot).step !== "restarting") return;
    set(ev.bot, ev.ok ? IDLE : { step: "failed", line: "" });
  });

  /** Which bots `bot`'s gateway serves (it included), from the bridge; kept for the words before the press. */
  const scope = async (bot: string) => {
    asked.add(bot);
    const s = await deps.scope(bot).catch(() => ({ gateway: bot, bots: NONE }));
    const all = s.bots.some((b) => b.name === bot) ? s.bots : [{ name: bot, display_name: bot }, ...s.bots];
    const got = { all, others: all.filter((b) => b.name !== bot) };
    scopes.set(bot, got);
    changed();
    return got;
  };

  const run = async (bot: string, interrupt: boolean) => {
    const sc = scopes.get(bot) ?? (await scope(bot));
    // the whole gateway goes down: every bot on it reads "restarting" together
    for (const m of sc.all) put(m.name, { step: "restarting" });
    put(bot, { step: "restarting" });
    changed();
    let r: RestartResult;
    try {
      r = await deps.restart(bot, interrupt);
    } catch (e) {
      const msg = typeof e === "object" && e && "message" in e ? String((e as { message: unknown }).message) : String(e);
      for (const m of sc.all) put(m.name, IDLE);
      return set(bot, { step: "failed", line: msg });
    }
    if (r.outcome === "ok") return; // each bot stays "restarting" until the bridge says it is attached again
    for (const m of sc.all) put(m.name, IDLE);
    if (r.outcome === "refused") set(bot, { step: "refused", work: r.work, bots: sc.all });
    else set(bot, { step: "failed", line: r.line });
  };

  return {
    get,
    /** The bots that share `bot`'s gateway (it excluded); [] until the bridge has answered `ensure`. */
    mates: (bot: string): Named[] => scopes.get(bot)?.others ?? NONE,
    /** Ask the bridge once which bots share `bot`'s gateway. */
    ensure(bot: string) {
      if (!asked.has(bot)) void scope(bot);
    },
    subscribe(f: () => void) {
      fns.add(f);
      return () => {
        fns.delete(f);
      };
    },
    /** The press: restarts the gateway that serves `bot`, without `--yes`. No confirm: Hermes refuses while any bot
     *  on it is working, and the refusal is the confirm. */
    async press(bot: string) {
      if (get(bot).step === "restarting") return;
      await run(bot, false);
    },
    /** "Restart anyway", offered only after Hermes refused for live work. */
    anyway: (bot: string) => (get(bot).step === "refused" ? run(bot, true) : Promise.resolve()),
    /** Cancel, or Close after a failure: back to normal. */
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

/** The bots that share `bot`'s gateway (it excluded), for the words before the press. */
export function useMates(bot: string): Named[] {
  const r = getRestarts();
  useEffect(() => r.ensure(bot), [r, bot]);
  return useSyncExternalStore(r.subscribe, () => r.mates(bot), () => r.mates(bot));
}
