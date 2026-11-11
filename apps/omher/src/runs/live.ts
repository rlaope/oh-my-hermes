// The bot's own runs, read once per bot and shared by the header's panel button and the Plans tab. They re-read by
// themselves: every 3 s while one of them is live, right after a `delegate_task` step of the bot's chat starts or
// ends, and at the end of its turn; never while the window is hidden. A run the bridge calls `stale` (running in
// its record, but nothing changed for a day) is not live: no live dot, not counted. Read-only.
import { useEffect, useSyncExternalStore } from "react";
import type { AgentRunSummary } from "../lib/runs";
import { sortRuns } from "../lib/runs";
import { getStore, onBridgeEvent } from "../state/store";

/** How often the runs re-read while one is live (ms). */
export const LIVE_POLL_MS = 3000;
/** The window width from which a turn's first `delegate_task` opens the panel on Plans by itself. */
export const AUTO_OPEN_MIN_WIDTH = 1100;

export interface BotRuns {
  runs: AgentRunSummary[] | null;
  error: string | null;
}

const EMPTY: BotRuns = { runs: null, error: null };
const entries = new Map<string, BotRuns>();
const inflight = new Map<string, Promise<void>>();
const listeners = new Set<() => void>();

const emit = () => listeners.forEach((l) => l());
const set = (bot: string, e: BotRuns) => {
  entries.set(bot, e);
  emit();
};

/** A run that is running and still moving. */
export const isLive = (r: Pick<AgentRunSummary, "state"> & { stale?: boolean }) => r.state === "running" && !r.stale;

/** Subagents at work: the running nodes of the live runs. */
export const workingCount = (runs: AgentRunSummary[] | null | undefined) =>
  (runs ?? []).reduce((n, r) => n + (isLive(r) ? r.counts.running : 0), 0);

/** Read the bot's runs again (one read at a time per bot). */
export function refreshRuns(bot: string): Promise<void> {
  const busy = inflight.get(bot);
  if (busy) return busy;
  const p = getStore()
    .actions.runsList(bot)
    .then(
      (r) => set(bot, { runs: sortRuns(r.runs), error: null }),
      (e) => set(bot, { runs: entries.get(bot)?.runs ?? null, error: String(e?.message ?? e) }),
    )
    .finally(() => inflight.delete(bot));
  inflight.set(bot, p);
  return p;
}

/** The bot's runs as last read (null until the first read). */
export function useBotRuns(bot: string): BotRuns {
  return useSyncExternalStore(
    (fn) => {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
    () => entries.get(bot) ?? EMPTY,
  );
}

const hidden = () => typeof document !== "undefined" && document.visibilityState === "hidden";

/** The turn of each bot that already opened the panel by itself: once per turn, and a close sticks. */
const opened = new Map<string, string>();

function autoOpen(bot: string, dagRun: string | undefined) {
  const st = getStore();
  const s = st.getState();
  const turn = s.chats[bot]?.turn?.id;
  if (!turn || opened.get(bot) === turn || s.selectedBot !== bot || s.ui.view !== "chat") return;
  opened.set(bot, turn);
  if (typeof window === "undefined" || window.innerWidth < AUTO_OPEN_MIN_WIDTH) return;
  const since = (s.chats[bot]?.turn?.startedAt ?? Date.now()) / 1000 - 5;
  st.actions.openRun(dagRun ?? null);
  if (dagRun) return;
  // a fan-out with no dag: its run is the newest delegate run that started in this turn, once the bridge lists it
  void refreshRuns(bot).then(() => {
    const now = getStore().getState();
    const run = entries.get(bot)?.runs?.find((r) => r.kind === "delegate" && r.started >= since);
    if (run && now.ui.panelOpen && now.ui.panelTab === "runs" && now.ui.runId === null) getStore().actions.openRun(run.id);
  });
}

/** Keeps the bot's runs fresh while its chat is on screen (mounted by the chat header). */
export function useRunsPoll(bot: string): void {
  const { runs } = useBotRuns(bot);
  const live = (runs ?? []).some(isLive);
  useEffect(() => {
    void refreshRuns(bot);
    const off = onBridgeEvent((ev) => {
      if (ev.bot !== bot || ev.session) return;
      if ((ev.event === "tool.start" || ev.event === "tool.end") && ev.name === "delegate_task") {
        if (ev.event === "tool.start") autoOpen(bot, ev.dag?.[0]?.run);
        void refreshRuns(bot);
      } else if (ev.event === "turn.end") void refreshRuns(bot);
    });
    const back = () => {
      if (!hidden()) void refreshRuns(bot);
    };
    document.addEventListener("visibilitychange", back);
    return () => {
      off();
      document.removeEventListener("visibilitychange", back);
    };
  }, [bot]);
  useEffect(() => {
    if (!live) return;
    const h = setInterval(() => {
      if (!hidden()) void refreshRuns(bot);
    }, LIVE_POLL_MS);
    return () => clearInterval(h);
  }, [bot, live]);
}
