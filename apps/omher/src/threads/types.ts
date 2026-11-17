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

export type ThreadEvent =
  | { event: "thread.added"; bot: string; thread: string; title: string }
  | { event: "thread.removed"; bot: string; thread: string }
  /** The bot's main-chat answer (`message`) held an ```omher-thread``` block: the bridge opened `thread` for it and
   *  sent the block's task there. The main chat shows one link line under that answer. */
  | { event: "thread.split"; bot: string; thread: string; title: string; message: string }
  /** The answer held an ```omher-thread-route``` block naming an open thread: the main chat asks "Send this to
   *  <title>?". Nothing moves until the person presses Send there. */
  | { event: "thread.route"; bot: string; thread: string; title: string; message: string };

const THREAD_EVENTS = new Set(["thread.added", "thread.removed", "thread.split", "thread.route"]);

/** A `thread.*` frame (not in lib/protocol's BridgeEvent union), or null. */
export function threadEvent(ev: { event: string }): ThreadEvent | null {
  return THREAD_EVENTS.has(ev.event) ? (ev as unknown as ThreadEvent) : null;
}

/** A top-level ```omher-thread``` / ```omher-thread-route``` fence of an answer being written (closed, or still open
 *  at the end): the bridge acts on it and the final answer comes without it, so the streaming bubble hides it too. */
const SPLIT_FENCE = /^ {0,3}(`{3,}|~{3,})[ \t]*omher-thread(?:-route)?[ \t]*(?:\r?\n[\s\S]*?\r?\n {0,3}\1[ \t]*$|\r?\n[\s\S]*$|$)/gm;
const SPLIT_INLINE = /^ {0,3}(`{3,})omher-thread(?:-route)?[ \t]+\{[^\n]*\}[ \t]*\1[ \t]*$/gm;
/** The JSON on the opening fence line, closed on the next line (or that close, or anything after the line, not
 *  streamed yet). */
const SPLIT_OPEN_LINE = /^ {0,3}(`{3,}|~{3,})[ \t]*omher-thread(?:-route)?[ \t]+\{[^\n]*(?:\r?\n {0,3}[`~]+[ \t]*$|\s*(?![\s\S]))/gm;

export function hideSplitBlocks(text: string): string {
  if (!text.includes("omher-thread")) return text;
  return text
    .replace(SPLIT_INLINE, "")
    .replace(SPLIT_OPEN_LINE, "")
    .replace(SPLIT_FENCE, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
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
