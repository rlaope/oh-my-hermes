// UI <-> bridge protocol v1. Mirrors the protocol table in the omher briefs (01-protocol.md).
// The UI only ever talks to the bridge (real: Python, mock: e2e/mock-bridge.mjs).

export type BotStatus = "online" | "offline" | "starting";

export interface Bot {
  name: string;
  display_name: string;
  is_default: boolean;
  model: string;
  provider: string;
  description: string;
  status: BotStatus;
  running: boolean;
  /** Changes whenever the bot's own picture changes; null = no picture, the built-in face is used. */
  avatar_rev?: number | null;
}

/** What a bot has done, for its page: sessions per place (slack, discord, cron…), skills, routines. */
export interface BotInfo {
  places: Record<string, number>;
  first_active: number | null;
  last_active: number | null;
  skills: number;
  routines: number;
}

/** One row of a bot's main chat. `ts` is seconds since epoch (float). */
export interface Msg {
  id: string;
  role: "user" | "assistant";
  text: string;
  ts: number;
}

/** A session of the bot that lives somewhere else (Slack, Discord, cron…). Read-only in omher. */
export interface Away {
  id: string;
  source: string;
  label: string;
  title: string;
  started_at: number;
  last_active: number;
  message_count: number;
  running: boolean;
  /** Opens the thread in its own app (slack:// or https://discord.com/channels/…), when known. */
  url?: string | null;
  /** Short place name, e.g. "#product-opengateway". */
  place?: string | null;
  /** The bot's last answer in that thread, as one short plain-text paragraph. */
  last_reply?: string | null;
  last_reply_at?: number | null;
}

export interface PeekMsg {
  role: string;
  author?: string;
  text: string;
  ts: number;
}

export interface Routine {
  id: string;
  name: string;
  schedule: string;
  next_run_at: number | string | null;
  last_run_at: number | string | null;
  last_status: string | null;
  enabled: boolean;
}

export type ApprovalChoice = "once" | "session" | "always" | "deny";

export interface ModelProvider {
  slug: string;
  name: string;
  models: string[];
}

export interface ModelCurrent {
  model: string;
  provider: string;
  reasoning: string;
}

export interface ModelOptions {
  providers: ModelProvider[];
  current: ModelCurrent;
  reasoning_levels: string[];
}

// ---- requests -------------------------------------------------------------------------------

export interface HelloResult {
  bridge: "real" | "mock";
  version: string;
  hermes: { home: string; version?: string };
}

export interface ChatOpenResult {
  session_id: string;
  messages: Msg[];
  running: boolean;
  model: string;
  provider: string;
  reasoning: string;
}

/** op name -> { params, result }. `bot` is always the profile name. */
export interface OpMap {
  hello: { params: Record<string, never>; result: HelloResult };
  "bots.list": { params: Record<string, never>; result: { bots: Bot[] } };
  "chat.open": { params: { bot: string }; result: ChatOpenResult };
  "chat.send": { params: { bot: string; text: string }; result: { input_id: string } };
  "chat.interrupt": { params: { bot: string }; result: Record<string, never> };
  "approval.respond": {
    params: { bot: string; request_id: string; choice: ApprovalChoice };
    result: Record<string, never>;
  };
  "clarify.respond": {
    params: { bot: string; request_id: string; answer: string };
    result: Record<string, never>;
  };
  "elsewhere.list": { params: { bot: string }; result: { sessions: Away[] } };
  "elsewhere.peek": {
    params: { bot: string; session_id: string; limit?: number };
    result: { messages: PeekMsg[]; total: number };
  };
  "routines.list": { params: { bot: string }; result: { routines: Routine[] } };
  "models.options": { params: { bot: string }; result: ModelOptions };
  "chat.set_model": {
    params: { bot: string; model?: string; provider?: string; reasoning?: string };
    result: ModelCurrent;
  };
  /** Display name only; "" goes back to the profile's own name. The profile id never changes. */
  "bots.rename": { params: { bot: string; name: string }; result: { display_name: string } };
  "bots.avatar": { params: { bot: string }; result: { rev: number | null; data: string | null } };
  "bots.set_avatar": {
    params: { bot: string; data?: string; clear?: boolean };
    result: { avatar_rev: number | null };
  };
  "bots.info": { params: { bot: string }; result: BotInfo };
  /** Side panel, all read-only: the bot's latest terminal runs, the git worktrees it worked in, one diff. */
  "panel.terminal": { params: { bot: string }; result: { runs: TerminalRun[] } };
  "panel.worktrees": { params: { bot: string }; result: { worktrees: Worktree[] } };
  "panel.diff": { params: { bot: string; path: string }; result: WorktreeDiff };
  /** A file the bot named in a `MEDIA:` line of its own answers (read-only). `info` skips the bytes. */
  "media.read": { params: { bot: string; path: string; info?: boolean }; result: MediaFile };
}

export interface MediaFile {
  /** The real file (symlinks resolved). */
  path: string;
  name: string;
  mime: string;
  size: number;
  /** The bytes; absent when `info` was asked or the file is over 25 MB (`too_big`). */
  data_base64?: string;
  too_big?: boolean;
}

export interface TerminalRun {
  id: string;
  command: string;
  output: string;
  exit_code: number | null;
  cwd: string;
  /** Where the run happened: "tui" (omher / desktop), "slack", "discord", "cron", … */
  source: string;
  session_id: string;
  ts: number;
}

export interface Worktree {
  path: string;
  branch: string;
  head: string;
  repo: string;
  /** Changed files, or null when git could not tell. */
  dirty: number | null;
  /** Newest terminal run of the bot in this worktree (seconds). */
  last: number;
}

export interface WorktreeDiff {
  path: string;
  branch: string;
  repo: string;
  /** "uncommitted" (vs HEAD) or "last commit" when the tree is clean. */
  scope: string;
  files: { path: string; add: number; del: number }[];
  patch: string;
  truncated: boolean;
}

export type Op = keyof OpMap;
export type OpParams<K extends Op> = OpMap[K]["params"];
export type OpResult<K extends Op> = OpMap[K]["result"];

export interface RequestFrame {
  id: string;
  op: string;
  [param: string]: unknown;
}

export interface BridgeError {
  code: string;
  message: string;
}

export type ReplyFrame =
  | { id: string; ok: true; result: unknown }
  | { id: string; ok: false; error: BridgeError };

// ---- events ---------------------------------------------------------------------------------

interface EventBase {
  bot: string;
}

export type BridgeEvent =
  | (EventBase & { event: "turn.start" })
  | (EventBase & { event: "status"; text: string })
  | (EventBase & { event: "thinking" })
  | (EventBase & { event: "tool.start"; tool_id: string; name: string; detail: string })
  | (EventBase & { event: "tool.end"; tool_id: string; name: string; ok: boolean; ms: number })
  | (EventBase & { event: "skill"; name: string })
  | (EventBase & { event: "delta"; text: string })
  | (EventBase & { event: "message"; id: string; text: string })
  | (EventBase & {
      event: "approval.request";
      request_id: string;
      title: string;
      command: string;
      choices: ApprovalChoice[];
    })
  | (EventBase & { event: "clarify.request"; request_id: string; question: string; choices?: string[] })
  | (EventBase & { event: "turn.end"; outcome: "done" | "interrupted" | "error"; error?: string })
  | (EventBase & { event: "bot.status"; status: BotStatus; running: boolean })
  | (EventBase & { event: "elsewhere.update" })
  | (EventBase & { event: "bots.update" })
  | (EventBase & {
      event: "routine.ran";
      routine_id: string;
      name: string;
      status: string;
      ts: number;
    });

export type EventName = BridgeEvent["event"];
export type EventOf<K extends EventName> = Extract<BridgeEvent, { event: K }>;

/** Platforms that are NOT "elsewhere": the bot's own front-ends. */
export const LOCAL_SOURCES = ["tui", "cli", "local", "desktop", "acp", "api_server", "omher"] as const;

export function isBridgeError(x: unknown): x is BridgeError {
  return typeof x === "object" && x !== null && typeof (x as BridgeError).code === "string";
}
