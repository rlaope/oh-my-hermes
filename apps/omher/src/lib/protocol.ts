// UI <-> bridge protocol v1. Mirrors the protocol table in the omher briefs (01-protocol.md).
// The UI only ever talks to the bridge (real: Python, mock: e2e/mock-bridge.mjs).

import type { AgentRunSummary, CliAgent, CliAgentStatus, RunDetail } from "./runs";

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
  /** user rows sent with "Reply there": the thread the person pointed the bot at. */
  reply_to?: ReplyRef | null;
}

/** A thread the bot was pointed at (`target` is Hermes' `platform:chat_id[:thread_id]`). */
export interface ReplyRef {
  target: string;
  label: string;
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
  /** Hermes' send target for that thread (`slack:C…:1731…`); null when there is no thread to reply in. */
  reply_target?: string | null;
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

/** One question of a clarify ask. Hermes' clarify tool asks 1-5 at once ("interview"); `qid` is its id. */
export interface ClarifyQuestion {
  qid: string;
  question: string;
  choices?: string[];
  /** More than one choice may be picked; the answer is then a JSON array of labels. */
  multi_select?: boolean;
}

/** Per-question answers of an interview: the text (or JSON array for multi-select), null = skipped. */
export type ClarifyAnswers = Record<string, string | null>;

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

/** A Hermes chat the bridge created in a picked folder (SESSIONS > oh-my-hermes). */
export interface FolderOpenResult {
  session: string;
  cwd: string;
  model: string;
  provider: string;
  reasoning: string;
}

/** op name -> { params, result }. `bot` is always the profile name. `session` (optional) names a folder chat
 *  the bridge created with `folder.open`; without it an op acts on the bot's main chat. `id` is the frame's
 *  own request id, so no op takes a param named `id` (accounts use `account`). */
export interface OpMap {
  hello: { params: Record<string, never>; result: HelloResult };
  "bots.list": { params: Record<string, never>; result: { bots: Bot[] } };
  "chat.open": { params: { bot: string }; result: ChatOpenResult };
  /** `reply_to` = an elsewhere session id: the bridge adds that thread as context for the bot.
   *  omher posts nothing. */
  "chat.send": { params: { bot: string; text: string; session?: string; reply_to?: string }; result: { input_id: string } };
  "chat.interrupt": { params: { bot: string; session?: string }; result: Record<string, never> };
  "approval.respond": {
    params: { bot: string; request_id: string; choice: ApprovalChoice; session?: string };
    result: Record<string, never>;
  };
  /** One answer (`answer`) for a single question, or every answer of an interview at once (`answers`). */
  "clarify.respond": {
    params: { bot: string; request_id: string; answer?: string; answers?: ClarifyAnswers; session?: string };
    result: Record<string, never>;
  };
  "folder.open": { params: { bot: string; cwd: string }; result: FolderOpenResult };
  "folder.close": { params: { bot: string; session: string }; result: Record<string, never> };
  "elsewhere.list": { params: { bot: string }; result: { sessions: Away[] } };
  "elsewhere.peek": {
    params: { bot: string; session_id: string; limit?: number };
    result: { messages: PeekMsg[]; total: number };
  };
  "routines.list": { params: { bot: string }; result: { routines: Routine[] } };
  "models.options": { params: { bot: string }; result: ModelOptions };
  "chat.set_model": {
    params: { bot: string; model?: string; provider?: string; reasoning?: string; session?: string };
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
  /** Stage one file the person picked for the next `chat.send`, in the bot's main chat only. */
  "chat.attach": { params: { bot: string; kind: AttachKind; name: string; data_base64: string }; result: AttachResult };
  /** Runs tab, read-only: the bot's agent runs (OMH dag runs today) and one run with its handoffs. */
  "runs.list": { params: { bot: string }; result: { runs: AgentRunSummary[] } };
  "runs.get": { params: { bot: string; run: string }; result: RunDetail };
  /** CLI agent sessions with sub-runs on this machine (Claude Code subagents, Codex sub-agents), read-only. A run's
   *  detail comes from `runs.get` with its id. `since` is epoch seconds (the last week when absent). */
  "runs.cli": {
    params: { agent?: CliAgent; cwd?: string; since?: number };
    result: { runs: AgentRunSummary[]; agents: Record<CliAgent, CliAgentStatus> };
  };
  /** Subscription usage of the CLIs on this machine, from their own session files (read-only). */
  "usage.read": { params: Record<string, never>; result: { providers: UsageProvider[] } };
  /** The coding CLIs on this computer with their logins: the CLI's own home first, then omher's added ones. */
  "accounts.list": { params: Record<string, never>; result: { groups: AccountGroup[] } };
  /** A new empty folder ~/.omher/accounts/<cli>/<id>/; the app then runs the CLI's own sign-in with it. */
  "accounts.add": { params: { cli: AccountCli; label: string }; result: { id: string; dir: string } };
  /** The account new sessions of the CLI start with (running sessions are untouched). */
  "accounts.set_active": { params: { cli: AccountCli; account: string }; result: Record<string, never> };
  /** Deletes ~/.omher/accounts/<cli>/<id>/ and nothing else. */
  "accounts.remove": { params: { cli: AccountCli; account: string }; result: Record<string, never> };
  /** The person's own name for a row ("" clears it); `default` = the CLI's own login. */
  "accounts.label": { params: { cli: AccountCli; account: string; label: string }; result: Record<string, never> };
  /** A cancelled sign-in: removes the new folder; refused when the CLI did sign in there. */
  "accounts.discard": { params: { cli: AccountCli; account: string }; result: Record<string, never> };
}

/** Which Hermes attach call a file takes: `image.attach_bytes`, `pdf.attach` or `file.attach`. */
export type AttachKind = "image" | "pdf" | "file";

export interface AttachResult {
  kind: AttachKind;
  name: string;
  /** Hermes' own line for it, e.g. `[User attached image: upload_1.png]`. */
  text: string;
  /** `@file:…` for a staged file; the prompt must carry it. Empty for images and PDFs. */
  ref_text: string;
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

export type AccountCli = "claude" | "codex" | "pi" | "omp" | "grok" | "gemini";
/** login = nobody is signed in there (yet). */
export type AccountState = "active" | "ready" | "limited" | "login";

export interface Account {
  /** "default" = the CLI's own home on this computer; otherwise the omher folder name. Never a token. */
  id: string;
  label: string;
  /** Claude Code's signed-in email (from its own `.claude.json`), else "". */
  email: string;
  state: AccountState;
  /** Limited accounts: when the limit resets (seconds). */
  resets_at?: number | null;
  /** omher accounts: the folder new sessions use. */
  dir?: string | null;
  /** The usage record found in that account's own folder. */
  usage?: UsageProvider | null;
}

export interface AccountGroup {
  cli: AccountCli;
  /** On the bridge's PATH (the desktop app re-checks the install folders). */
  installed: boolean;
  /** The account new sessions start with. */
  active: string | null;
  accounts: Account[];
  /** Another tool on this computer that holds logins for this CLI (only counted, managed there). */
  also?: { name: string; accounts: number };
}

export type UsageState = "ok" | "near" | "limited" | "stale" | "connected";

export interface UsageWindow {
  /** "5 hours", "Weekly", "2d"… */
  label: string;
  /** Only when the source gave one (Codex does, Claude Code never does). */
  used_percent?: number;
  /** Seconds since epoch. */
  resets_at?: number;
  /** The reset time has passed since the source was written: no number is shown. */
  stale?: boolean;
}

export interface UsageProvider {
  id: "codex" | "claude" | "grok" | "gemini";
  plan?: string;
  windows: UsageWindow[];
  state: UsageState;
  /** mtime of the file the numbers came from; null when only the CLI was found on PATH. */
  source_mtime: number | null;
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
  /** Changed files; `untracked` ones are new files git does not track yet (listed without content). */
  files: { path: string; add: number; del: number; untracked?: boolean }[];
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
  /** Set on events of a folder chat (`folder.open`); absent for the bot's main chat. */
  session?: string;
}

export type BridgeEvent =
  | (EventBase & { event: "turn.start" })
  | (EventBase & { event: "status"; text: string })
  | (EventBase & { event: "thinking" })
  | (EventBase & {
      event: "tool.start";
      tool_id: string;
      name: string;
      detail: string;
      /** delegate_task only: the `[dag:<run>/<node>]` parts it hands out. */
      dag?: { run: string; node: string }[];
    })
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
      /** Seconds the gateway waits before giving up on it, when it says. */
      timeout_s?: number;
    })
  | (EventBase & {
      event: "clarify.request";
      request_id: string;
      question: string;
      choices?: string[];
      multi_select?: boolean;
      /** Set when the bot asks several questions at once (an interview); `question` is then the first. */
      questions?: ClarifyQuestion[];
      timeout_s?: number;
    })
  /** An approval or question is no longer waiting (timed out, withdrawn, or answered somewhere else). */
  | (EventBase & { event: "prompt.expired"; request_id: string; reason: "timeout" | "cancelled" | "resolved" })
  | (EventBase & { event: "turn.end"; outcome: "done" | "interrupted" | "error"; error?: string })
  | (EventBase & { event: "bot.status"; status: BotStatus; running: boolean })
  | (EventBase & { event: "elsewhere.update" })
  | (EventBase & { event: "bots.update" })
  /** omher accounts changed (added, removed, made active); the Accounts views re-read accounts.list. */
  | (EventBase & { event: "accounts.update" })
  | (EventBase & { event: "folder.closed"; reason?: string })
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
