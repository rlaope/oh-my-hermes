// Bridge ops and events of threads under a bot (bridge `thread.*`). Kept here, not in lib/protocol.ts, so this lane
// merges cleanly beside the others; the shapes are the bridge's (omher_bridge.py op_thread_*).

/** One thread as `thread.list` / `thread.create` give it. `thread` is Hermes' stored session id (stable across
 *  restarts); its events arrive tagged `session: <thread>` and land in the store under `fold:<bot>:<thread>`. */
export interface ThreadRow {
  thread: string;
  /** Without the `omher · ` prefix; "" until the first message names it. */
  title: string;
  cwd: string;
  /** seconds since epoch */
  started_at: number;
  running: boolean;
  /** An approval or question of it waits (as the bridge saw it). */
  needs: boolean;
  message_count: number;
  preview?: string;
  /** seconds since epoch of the last thing that happened in it (set by the app as events arrive) */
  last?: number;
}

export interface ThreadOpenResult {
  thread: string;
  session_id: string;
  title: string;
  cwd: string;
  messages: { id: string; role: "user" | "assistant"; text: string; ts: number }[];
  running: boolean;
  model: string;
  provider: string;
  reasoning: string;
}

export interface ThreadOps {
  "thread.create": { params: { bot: string; title?: string; cwd?: string; key?: string }; result: ThreadRow & { model: string; provider: string; reasoning: string } };
  "thread.list": { params: { bot: string }; result: { threads: ThreadRow[] } };
  "thread.open": { params: { bot: string; thread: string }; result: ThreadOpenResult };
  "thread.remove": { params: { bot: string; thread: string }; result: { thread: string; archived: boolean } };
}

export type ThreadEvent = { event: "thread.added"; bot: string; thread: string; title: string } | { event: "thread.removed"; bot: string; thread: string };

/** A `thread.added` / `thread.removed` frame (not in lib/protocol's BridgeEvent union), or null. */
export function threadEvent(ev: { event: string }): ThreadEvent | null {
  return ev.event === "thread.added" || ev.event === "thread.removed" ? (ev as unknown as ThreadEvent) : null;
}

/** Store key of a thread's chat: the same `fold:<bot>:<id>` the bridge's `session`-tagged events land under. */
export const threadKey = (bot: string, thread: string) => `fold:${bot}:${thread}`;

/** How many thread rows a bot shows before "Show N more". */
export const THREADS_SHOWN = 5;

/** A title for a thread Hermes has not named yet: the first words of the first message (the bridge does the same). */
export const firstWords = (text: string, n = 40) => {
  const one = text.split(/\s+/).filter(Boolean).join(" ");
  return one.length <= n ? one : `${one.slice(0, n - 1).trimEnd()}…`;
};
