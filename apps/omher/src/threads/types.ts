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

// The ```omher-thread``` / ```omher-thread-route``` blocks of an answer being written: the bridge acts on the top-level
// ones and the final answer comes without them, so the streaming bubble hides them too. The same line walk as the
// bridge's `split_blocks`: only a top-level fence counts (not in a `>` quote, not inside another fence such as a
// ```` or ~~~ fence quoting one as an example); a block still open at the end is hidden while it streams.
const SPLIT_KINDS = new Set(["omher-thread", "omher-thread-route"]);
const SPLIT_FENCE = /^( {0,3})(`{3,}|~{3,})[ \t]*([^\s`]*)[ \t]*(.*?)\s*$/;
const SPLIT_CLOSE = /^ {0,3}(`{3,}|~{3,})[ \t]*$/;
const SPLIT_INLINE = /^ {0,3}(`{3,})(omher-thread|omher-thread-route)[ \t]+(\{.*\})[ \t]*\1[ \t]*$/;
const closes = (line: string | undefined, fence: string) => {
  const c = line === undefined ? null : SPLIT_CLOSE.exec(line.replace(/\r$/, ""));
  return !!c && c[1][0] === fence[0] && c[1].length >= fence.length;
};

/** What follows an opening line with its JSON is, so far, nothing or the start of its closing fence. */
const streamingClose = (after: string[]) => after.length <= 1 && /^ {0,3}[`~]*[ \t]*\r?$/.test(after[0] ?? "");

export function hideSplitBlocks(text: string): string {
  if (!text.includes("omher-thread")) return text;
  const lines = text.split("\n");
  const keep: string[] = [];
  for (let i = 0; i < lines.length; ) {
    const line = lines[i].replace(/\r$/, "");
    if (SPLIT_INLINE.test(line)) {
      i += 1;
      continue;
    }
    const m = SPLIT_FENCE.exec(line);
    if (!m || line.trimStart().startsWith(">")) {
      keep.push(lines[i]);
      i += 1;
      continue;
    }
    const [, , fence, info, rest] = m;
    const kind = SPLIT_KINDS.has(info);
    // the JSON on the opening fence line, closed on the very next line, or the last line so far (still streaming)
    const oneLine = kind && rest.startsWith("{") && (closes(lines[i + 1], fence) || streamingClose(lines.slice(i + 1)));
    if (fence[0] === "`" && rest.includes("`") && !oneLine) {
      keep.push(lines[i]); // an inline code span, not a fence
      i += 1;
      continue;
    }
    let j = i + 1;
    while (j < lines.length && !closes(lines[j], fence)) j += 1;
    if (!(kind && (!rest || oneLine))) keep.push(...lines.slice(i, j + 1));
    i = j + 1;
  }
  return keep.join("\n").replace(/\n{3,}/g, "\n\n").trim();
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
