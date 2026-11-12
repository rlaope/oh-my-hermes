// After omher's own installer ends well (the sidebar "!" popover, or the first-run screen that installs Hermes and
// oh-my-hermes), the app shows a bot's chat with one quiet line above the composer, once: pressing it puts a
// model-setup request in the composer (the bot's own `/…model-setup` command from `skills.list`, then one sentence
// in the app's language). Nothing is sent; the person reads it, may edit it and presses Enter. The line is offered
// only when the bot's skills really hold that command (asked again for about a minute); else it says the bot needs
// a restart, with the exact command as text. omher restarts nothing and runs nothing for it.
//
// A gateway that was already running when oh-my-hermes was installed sees its skills at once (Hermes rescans skill
// folders) but not its plugin: plugins load once per gateway process. The model-setup skill needs no `omh_*` tool
// (it reads with the terminal and Hermes' own commands), so the ready line shows at once; when the bot's own gateway
// lists the `omh` plugin as enabled with no tool of its own registered (`plugins.manage list`, the loader's record),
// a second quiet line under it says the rest of oh-my-hermes arrives after a restart, with the command as text.
//
// Kept on this computer under PROMPT_KEY: "pending" from the install's success until the person presses the action
// or the x, then "done" for good. A person who had oh-my-hermes all along, or installed it outside omher, never has
// "pending", so never sees the line.
import { useSyncExternalStore } from "react";
import type { Bot, PluginRow, Skill } from "../lib/protocol";
import { getStore } from "../state/store";
import { t } from "../i18n";

export const PROMPT_KEY = "omher.omhPrompt";

/** off: nothing to show. pending: the install ended well, no check yet. checking: asking the bot's skills.
 *  ready: the line with the action. restart: the bot's skills never showed the command; the restart line. */
export type PromptPhase = "off" | "pending" | "checking" | "ready" | "restart";

export interface PromptState {
  phase: PromptPhase;
  /** The bot the check ran on (the line shows in its chat only). */
  bot: string | null;
  /** The command exactly as `skills.list` names it, with its slash (`/omh-model-setup`). */
  command: string | null;
  /** With `ready`: the bot's running gateway has not loaded the oh-my-hermes plugin yet (a restart loads it). */
  restart: boolean;
}

/** Waits before each `skills.list` read: one at once, then again for about a minute. */
export const CHECK_DELAYS = [0, 2_000, 3_000, 5_000, 10_000, 20_000, 20_000];

/** The model-setup skill among a bot's skills: the one whose name ends in `model-setup` (OMH ships it as
 *  `omh-model-setup`); the command is taken from the list, never written here. */
export function modelSetupCommand(skills: readonly Skill[]): string | null {
  const hit = skills.find((s) => /(^|-)model-setup$/.test(s.name));
  return hit ? `/${hit.name}` : null;
}

/** What the action puts in the composer: the command, then one sentence in the app's language. */
export function promptText(command: string): string {
  return `${command} ${t("omhp.ask")}`;
}

/** Whether a bot's running gateway has loaded oh-my-hermes' plugin: false only when its `omh` row is enabled and
 *  lists no tool of its own in that process; null when it cannot be told (no row, an older bridge, offline). */
export function omhPluginLoaded(rows: readonly PluginRow[] | null): boolean | null {
  const omh = rows?.find((r) => r.name === "omh" || r.key === "omh");
  if (!omh || !omh.enabled || typeof omh.live_tools !== "number") return null;
  return omh.live_tools > 0;
}

/** The command a person runs to restart this bot's gateway (Hermes' own; omher never runs it). */
export function restartCommand(bot: Pick<Bot, "name" | "is_default">): string {
  return bot.is_default ? "hermes gateway restart" : `hermes -p ${bot.name} gateway restart`;
}

type Kv = Pick<Storage, "getItem" | "setItem">;

export interface PromptDeps {
  storage: Kv | null;
  skills: (bot: string) => Promise<Skill[]>;
  /** The bot's plugins as its running gateway lists them (null when it cannot say). */
  plugins: (bot: string) => Promise<PluginRow[] | null>;
  sleep: (ms: number) => Promise<void>;
  /** Show a bot's chat once the app's bots are known: the one in view, else the first. */
  showChat: () => void;
  delays?: readonly number[];
}

export function createOmhPrompt(deps: PromptDeps) {
  const read = () => {
    try {
      return deps.storage?.getItem(PROMPT_KEY) ?? null;
    } catch {
      return null;
    }
  };
  const write = (v: string) => {
    try {
      deps.storage?.setItem(PROMPT_KEY, v);
    } catch {
      /* no storage: it holds for this run */
    }
  };
  let state: PromptState = { phase: read() === "pending" ? "pending" : "off", bot: null, command: null, restart: false };
  let run = 0;
  const fns = new Set<() => void>();
  const set = (p: Partial<PromptState>) => {
    state = { ...state, ...p };
    for (const f of [...fns]) f();
  };

  /** The installer ended well: offer the line once (never again after it was pressed or closed). */
  const installed = () => {
    if (read() === "done") return;
    write("pending");
    run += 1;
    set({ phase: "pending", bot: null, command: null, restart: false });
    deps.showChat();
  };

  /** Ask `bot`'s skills for the command, again for about a minute; the line or the restart line follows. */
  const check = async (bot: string) => {
    if (state.phase !== "pending") return;
    const mine = ++run;
    set({ phase: "checking", bot });
    for (const ms of deps.delays ?? CHECK_DELAYS) {
      if (ms) await deps.sleep(ms);
      if (run !== mine) return;
      const command = modelSetupCommand(await deps.skills(bot).catch(() => []));
      if (run !== mine) return;
      if (command) {
        const loaded = omhPluginLoaded(await deps.plugins(bot).catch(() => null));
        if (run !== mine) return;
        return set({ phase: "ready", command, restart: loaded === false });
      }
    }
    set({ phase: "restart" });
  };

  /** The x: the line goes and never comes back on this computer. */
  const finish = () => {
    write("done");
    run += 1;
    set({ phase: "off" });
  };

  /** The action: the ready line goes for good; a restart line under it stays until its x (this run only). */
  const used = () => {
    if (state.phase === "ready" && state.restart) {
      write("done");
      run += 1;
      set({ phase: "restart" });
    } else finish();
  };

  return {
    getState: () => state,
    subscribe(f: () => void) {
      fns.add(f);
      return () => {
        fns.delete(f);
      };
    },
    installed,
    check,
    finish,
    used,
  };
}

export type OmhPrompt = ReturnType<typeof createOmhPrompt>;

let single: OmhPrompt | null = null;
export function getOmhPrompt(): OmhPrompt {
  if (!single) {
    single = createOmhPrompt({
      storage: typeof localStorage === "undefined" ? null : localStorage,
      skills: (bot) => getStore().actions.skills(bot, true),
      plugins: (bot) => getStore().actions.pluginsList(bot),
      sleep: (ms) => new Promise((r) => setTimeout(r, ms)),
      // e2e shortens the minute of re-reads (`__omherPromptDelays`); the app uses CHECK_DELAYS
      delays: typeof window === "undefined" ? undefined : (window as unknown as { __omherPromptDelays?: number[] }).__omherPromptDelays,
      showChat() {
        // after the store has its bots (the first-run screen installs before the app has started)
        const store = getStore();
        void store.resumed.then(() => {
          const s = store.getState();
          const bot = s.selectedBot ?? s.bots[0]?.name;
          if (!bot) return;
          if (s.ui.runsFull) store.actions.setRunsFull(false);
          if (s.ui.view !== "chat" || s.selectedBot !== bot) void store.actions.selectBot(bot);
        });
      },
    });
  }
  return single;
}

/** The installer's success path calls this (addOmh.ts, BridgeGate.tsx). */
export function omhInstalled(): void {
  getOmhPrompt().installed();
}

export function useOmhPrompt(): PromptState {
  const p = getOmhPrompt();
  return useSyncExternalStore(p.subscribe, p.getState, p.getState);
}
