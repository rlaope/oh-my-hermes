// The whole app view model: one reducer, one store, one React hook. UI nodes only read this and call
// its actions; they never edit this file.
import { useSyncExternalStore } from "react";
import { BridgeClient, type BridgeStatus } from "../lib/bridge";
import { noteFor, showNote, windowWatched } from "../lib/notify";
import { appSounds, soundFor, type SoundBoard } from "../lib/sounds";
import { promptText } from "../chat/parts/attachFiles";
import { toWire } from "../chat/parts/skillTokens";
import { forBots, parseResume, RESUME_KEY, type ResumeSnap } from "../app/resume";
import { LANG_KEY, readLang, setLang, t as tr, type Key, type Lang } from "../i18n";
import type {
  Away,
  LinkPlaces,
  ApprovalChoice,
  Bot,
  BridgeEvent,
  EventOf,
  ChatOpenResult,
  ClarifyAnswers,
  ClarifyQuestion,
  HelloResult,
  FolderOpenResult,
  ModelCurrent,
  ModelOptions,
  PeekMsg,
  ReplyRef,
  Routine,
  BotInfo,
  TerminalRun,
  Worktree,
  UsageProvider,
  WorktreeDiff,
  MediaFile,
  SubagentState,
  AskSubagent,
  AttachKind,
  AttachResult,
  AccountCli,
  AccountGroup,
  Skill,
  Automation,
  CatalogResult,
  InspectResult,
  OpMap,
  PluginRow,
} from "../lib/protocol";
import type { AgentRunSummary, CliAgent, NodePr, RunDetail } from "../lib/runs";

export type PanelTabId = "details" | "terminal" | "schedule" | "worktrees" | "diff" | "runs";

// ---- view model types -----------------------------------------------------------------------

export interface Step {
  id: string;
  name: string;
  detail: string;
  startedAt: number; // ms
  endedAt?: number; // ms
  ok?: boolean;
  /** delegate_task: the dag parts this call handed out (one plain line each in the activity details). */
  dag?: { run: string; node: string }[];
}

export interface Turn {
  id: string;
  startedAt: number; // ms
  endedAt?: number; // ms
  outcome?: "done" | "interrupted" | "ended" | "error";
  error?: string;
  /** Latest tool text ("Reading gateway.log") or status text. */
  status: string;
  steps: Step[];
  skills: string[];
  /** Answer text streamed so far (cleared when the final `message` lands). */
  streaming: string;
  /** The fan-outs (delegate_task children) this turn started, as Hermes' subagent events tell them. */
  fanouts?: Fanout[];
}

/** One subagent of a fan-out, as its latest event left it. */
export interface SubagentRow {
  id: string;
  index: number;
  goal: string;
  /** Which agent reported it (a session's CLI) and its name or type, when the agent gives them. */
  agent?: string;
  name?: string;
  /** Its recent steps, oldest first (at most SUB_STEPS): what the row shows when opened. */
  steps?: { tool?: string; text: string }[];
  model?: string;
  dag?: { run: string; node: string };
  state: SubagentState;
  tool?: string;
  step?: string;
  summary?: string;
  /** Its own run time when it ended (Hermes'), else counted from `startedAt`. */
  seconds?: number;
  startedAt: number; // ms
  endedAt?: number; // ms
}

/** One fan-out of a turn: the children of one delegate_task call. */
export interface Fanout {
  /** The delegation id once Hermes names it; until then a local key. */
  key: string;
  delegation?: string;
  count: number;
  startedAt: number; // ms
  /** When its last event came (ms): a fan-out no event moved for a while is not shown as running. */
  updatedAt: number;
  subs: SubagentRow[];
}

/** Timeline items. `ts` is seconds since epoch so chat rows and away lines sort together. */
export type MessageItem = {
  kind: "user" | "assistant";
  id: string;
  ts: number;
  text: string;
  /** user rows only: the send failed (text of the bridge error). */
  error?: string;
  /** user rows only: sent while a turn ran, and the agent has not taken it yet (`queued`), or Stop threw it away
   *  before the agent read it (`dropped`). */
  wait?: "queued" | "dropped";
  /** user rows only: sent with "Reply there" (where the person pointed the bot). */
  reply?: { source: string; label: string };
  /** user rows only: files sent with it, shown from the local copies (never read back). */
  files?: SentFile[];
  /** user rows only: the prompt text actually sent when it differs from `text` (files add `@file:` refs). */
  sent?: string;
};

/** A file the person sent, as their own bubble shows it. `url` is a blob URL for pictures and video. */
export interface SentFile {
  name: string;
  size: number;
  kind: "image" | "video" | "file";
  url: string | null;
}

/** One file to send: the Hermes attach call it takes, its bytes, and how the bubble shows it. */
export interface OutFile extends SentFile {
  attach: AttachKind;
  read: () => Promise<string>;
}
export type ActivityItem = { kind: "activity"; id: string; ts: number; turn: Turn };
/** Why an ask stopped waiting without an answer from omher: the gateway timed it out, withdrew it, or it was
 *  answered somewhere else (another Hermes window, Slack). */
export type AskExpiry = "timeout" | "cancelled" | "resolved";
export type ApprovalItem = {
  kind: "approval";
  id: string;
  ts: number;
  request_id: string;
  title: string;
  command: string;
  choices: ApprovalChoice[];
  /** The folder the command runs in, when the agent says. */
  cwd?: string;
  /** Asked inside a subagent: which one. */
  subagent?: AskSubagent;
  resolved?: ApprovalChoice;
  expired?: AskExpiry;
};
export type ClarifyItem = {
  kind: "clarify";
  id: string;
  ts: number;
  request_id: string;
  question: string;
  choices?: string[];
  /** Several picks allowed (single question). */
  multi?: boolean;
  /** An interview: every question of the ask (2-5), answered in one card. */
  questions?: ClarifyQuestion[];
  subagent?: AskSubagent;
  answer?: string;
  /** Interview answers per question id (null = skipped). */
  answers?: ClarifyAnswers;
  expired?: AskExpiry;
};
export type AwayItem = { kind: "away"; id: string; ts: number; away: Away };
export type RoutineItem = {
  kind: "routine";
  id: string;
  ts: number;
  routine_id: string;
  name: string;
  status: string;
};
/** A card for an automation the bot made from this chat (`routine.added`): what, when, where it delivers. */
export type RoutineAddedItem = {
  kind: "routineAdded";
  id: string;
  ts: number;
  routine_id: string;
  name: string;
  schedule: string;
  next_run_at: number | string | null;
  deliver: string;
  origin: { platform: string; place: string } | null;
};
/** A card for a plugin the bot installed from this chat (`plugin.added`). */
export type PluginAddedItem = { kind: "pluginAdded"; id: string; ts: number; name: string; title: string; tools: number; hooks: number };
/** One quiet line from omher itself (e.g. "Switched to Claude #2 (limit on #1)"); never sent to the bot. */
export type SystemItem = { kind: "system"; id: string; ts: number; text: string };
export type ChatItem =
  | MessageItem
  | ActivityItem
  | ApprovalItem
  | ClarifyItem
  | RoutineItem
  | RoutineAddedItem
  | PluginAddedItem
  | SystemItem;
export type TimelineItem = ChatItem | AwayItem;

export interface Chat {
  /** user / assistant / activity / approval / clarify / routine rows in arrival order. */
  items: ChatItem[];
  /** The user/assistant subset of `items`, as plain messages. */
  messages: { id: string; role: "user" | "assistant"; text: string; ts: number }[];
  turn: Turn | null;
  lastTurn: Turn | null;
  model: string;
  provider: string;
  reasoning: string;
  loaded: boolean;
  sessionId: string | null;
  turnSeq: number;
  /** Set when chat.open failed (bot offline, gateway refused); the timeline shows it instead of loading forever. */
  openError?: string | null;
  /** A status that came while no turn ran (Hermes says "Resuming interrupted turn…" just before the turn starts):
   *  never shown on its own; a turn that starts within EARLY_STATUS_MS opens with it. */
  early?: { text: string; at: number } | null;
}

/** The composer's "Reply there" chip: a thread elsewhere the next message points the bot at. */
export interface ReplyChip {
  session_id: string;
  source: string;
  /** "#og-dev" (or the source name when the place is unknown). */
  place: string;
  kind: "thread" | "channel";
}

export interface Peek {
  messages: PeekMsg[];
  total: number;
  loading: boolean;
  error?: string;
}

export type Theme = "system" | "dark" | "light";
/** Colour set for bubbles, links and the accent points (send, badges, live dots). The logo never changes. */
export type Palette = "omh" | "graphite" | "ocean" | "forest" | "sunset" | "rose";
/** soft = both sides in tinted bubbles (default); solid = your bubble in the accent colour; open = the bot
 *  writes on the page and only your messages are bubbles. */
export type BubbleStyle = "soft" | "solid" | "open";
export const BUBBLE_STYLES: BubbleStyle[] = ["soft", "solid", "open"];
export type TextSize = "small" | "medium" | "large";
export interface Look {
  palette: Palette;
  bubbles: BubbleStyle;
  text: TextSize;
}
export const PALETTES: Palette[] = ["omh", "graphite", "ocean", "forest", "sunset", "rose"];
export interface Ui {
  panelOpen: boolean;
  panelTab: PanelTabId;
  /** The run the Runs tab shows (a full id, or a dag run name from a chat line); null = the first in its list. */
  runId: string | null;
  /** The Runs graph fills the chat column (⌘⇧G); the side panel stays. */
  runsFull: boolean;
  /** Text put into a bot's composer for the person to edit and send (never sent by omher). */
  draft: { bot: string; text: string; n: number } | null;
  theme: Theme;
  look: Look;
  /** "session" = a terminal session (SESSIONS in the sidebar) fills the main column; `session` names it.
   *  "automations" and "plugins" are the two pages of the sidebar's foot. */
  view: "chat" | "settings" | "session" | "automations" | "plugins";
  /** Automations: the job the detail panel shows (`<bot>:<id>`); Plugins: the bot whose plugins the page shows. */
  automation: string | null;
  pluginsBot: string | null;
  /** The UI language (Settings › General › Language), saved as `omher.lang`. */
  lang: Lang;
  settingsPage: string;
  /** Sidebar: bots pinned to the top (in pin order) and bots hidden from the list. Saved on this computer. */
  pinned: string[];
  hidden: string[];
  /** The ask card to scroll to and focus (set by the Needs-you strip and ⌘J); `seq` re-triggers the same one. */
  focusAsk: FocusAsk | null;
  session: string | null;
}

export interface FocusAsk {
  bot: string;
  id: string;
  seq: number;
}

export interface AppState {
  conn: BridgeStatus;
  hello: HelloResult | null;
  lastError: string | null;
  bots: Bot[];
  selectedBot: string | null;
  chats: Record<string, Chat>;
  unread: Record<string, number>;
  elsewhere: Record<string, Away[]>;
  peeks: Record<string, Peek>;
  routines: Record<string, Routine[]>;
  /** Every bot's automations (`automations.list`, read from each profile's cron/jobs.json); null until read. */
  automations: Automation[] | null;
  models: Record<string, ModelOptions>;
  /** Per bot: the composer's "Reply there" chip, if any. */
  replyTo: Record<string, ReplyChip | null>;
  ui: Ui;
}

// ---- activity text --------------------------------------------------------------------------

const VERBS: Record<string, Key> = {
  terminal: "live.running",
  read_file: "live.reading",
  search_files: "live.searching",
  web_search: "live.searchingWeb",
  web_extract: "live.reading",
  write_file: "live.editing",
  patch: "live.editing",
  delegate_task: "live.asking",
  skill_view: "live.usingSkill",
  skill_use: "live.usingSkill",
};

/** "<Verb> <detail>" for a tool call, the verb in the current language; unknown tools keep their own name. */
export function activityText(name: string, detail: string): string {
  const verb = VERBS[name] ? tr(VERBS[name]) : name;
  const d = (detail ?? "").trim();
  return d ? `${verb} ${d}` : verb;
}

/** The live text split for display: when it is the latest tool's text, `code` holds its command or path. */
/** The status of a turn found running on open, before any event: shown as "Working…" in the current language. */
export const WORKING = "Working…";
/** The status a turn gets from `thinking`, before any tool or status text. */
export const THINKING = "Thinking…";

export function liveLabel(t: Turn): { verb: string; code?: string } {
  const status = t.status || WORKING;
  const last = t.steps[t.steps.length - 1];
  if (last && last.detail && status === activityText(last.name, last.detail)) {
    return { verb: activityText(last.name, ""), code: last.detail };
  }
  return { verb: status };
}

/** Whether a running turn has something for its activity line to say: a tool or skill ran, or the bot sent a
 *  status of its own. Before that (only thinking) the chat shows the typing bubble instead of the line. */
export function turnHasActivity(t: Turn): boolean {
  return t.steps.length > 0 || t.skills.length > 0 || !!(t.status && t.status !== THINKING && t.status !== WORKING);
}

// ---- state helpers --------------------------------------------------------------------------

const emptyChat = (): Chat => ({
  items: [],
  messages: [],
  turn: null,
  lastTurn: null,
  model: "",
  provider: "",
  reasoning: "",
  loaded: false,
  sessionId: null,
  turnSeq: 0,
});

const DEFAULT_LOOK: Look = { palette: "omh", bubbles: "soft", text: "small" };

function readLook(): Look {
  try {
    const raw = typeof localStorage !== "undefined" ? localStorage.getItem("omher.look") : null;
    const v = raw ? (JSON.parse(raw) as Partial<Look>) : {};
    return {
      palette: PALETTES.includes(v.palette as Palette) ? (v.palette as Palette) : DEFAULT_LOOK.palette,
      bubbles: BUBBLE_STYLES.includes(v.bubbles as BubbleStyle) ? (v.bubbles as BubbleStyle) : "soft",
      text: v.text === "medium" || v.text === "large" ? v.text : "small",
    };
  } catch {
    return { ...DEFAULT_LOOK };
  }
}

function readList(key: string): string[] {
  try {
    const raw = typeof localStorage !== "undefined" ? localStorage.getItem(key) : null;
    const v: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
  } catch {
    return [];
  }
}

function saveList(key: string, v: string[]): void {
  try {
    if (typeof localStorage !== "undefined") localStorage.setItem(key, JSON.stringify(v));
  } catch {
    /* no storage */
  }
}

export function readTheme(): Theme {
  try {
    const v = typeof localStorage !== "undefined" ? localStorage.getItem("omher.theme") : null;
    if (v === "dark" || v === "light" || v === "system") return v;
  } catch {
    /* no storage */
  }
  return "system";
}

export function initialState(): AppState {
  return {
    conn: "closed",
    hello: null,
    lastError: null,
    bots: [],
    selectedBot: null,
    chats: {},
    unread: {},
    elsewhere: {},
    peeks: {},
    routines: {},
    automations: null,
    models: {},
    replyTo: {},
    ui: {
      panelOpen: false,
      panelTab: "details",
      runId: null,
      runsFull: false,
      draft: null,
      theme: readTheme(),
      look: readLook(),
      view: "chat",
      settingsPage: "general",
      pinned: readList("omher.pinned"),
      hidden: readList("omher.hidden"),
      focusAsk: null,
      session: null,
      automation: null,
      pluginsBot: null,
      lang: readLang(),
    },
  };
}

function withItems(chat: Chat, items: ChatItem[]): Chat {
  const messages = items
    .filter((i): i is MessageItem => i.kind === "user" || i.kind === "assistant")
    .map((i) => ({ id: i.id, role: i.kind, text: i.text, ts: i.ts }));
  return { ...chat, items, messages };
}

/** The person answered a card: the running turn's "Waiting for approval / your answer" goes back to what the turn
 *  was doing (its latest step), or to the plain working line, unless another card still waits. */
function doneWaiting(c: Chat): Chat {
  const t = c.turn;
  if (!t || (t.status !== tr("live.waitApproval") && t.status !== tr("live.waitAnswer"))) return c;
  if (c.items.some((i) => (i.kind === "approval" || i.kind === "clarify") && askOpen(c.items, i))) return c;
  const last = t.steps[t.steps.length - 1];
  return patchTurn(c, (x) => ({ ...x, status: last && last.endedAt === undefined ? activityText(last.name, last.detail) : "" }));
}

/** How long a status that came before its turn still opens that turn (Hermes sends it right before). */
const EARLY_STATUS_MS = 5_000;

function newTurn(chat: Chat, bot: string, now: number, status = ""): [Chat, Turn] {
  const seq = chat.turnSeq + 1;
  const turn: Turn = { id: `${bot}-t${seq}`, startedAt: now, status, steps: [], skills: [], streaming: "" };
  const item: ActivityItem = { kind: "activity", id: turn.id, ts: now / 1000, turn };
  return [{ ...withItems(chat, [...chat.items, item]), turn, turnSeq: seq }, turn];
}

function patchTurn(chat: Chat, fn: (t: Turn) => Turn): Chat {
  if (!chat.turn) return chat;
  const turn = fn(chat.turn);
  const items = chat.items.map((i) => (i.kind === "activity" && i.id === turn.id ? { ...i, turn } : i));
  return { ...withItems(chat, items), turn };
}

/** Applies `fn` to the turn of activity item `id`, wherever it is (the running turn, the last one, or older). */
function patchTurnById(chat: Chat, id: string, fn: (t: Turn) => Turn): Chat {
  let next: Turn | null = null;
  const items = chat.items.map((i) => (i.kind === "activity" && i.id === id ? { ...i, turn: (next = fn(i.turn)) } : i));
  if (!next) return chat;
  return {
    ...withItems(chat, items),
    turn: chat.turn?.id === id ? next : chat.turn,
    lastTurn: chat.lastTurn?.id === id ? next : chat.lastTurn,
  };
}

const SUB_DONE: SubagentState[] = ["done", "failed", "cancelled"];
/** How many of a subagent's own steps its row keeps. */
export const SUB_STEPS = 8;
export const subagentEnded = (s: Pick<SubagentRow, "state">) => SUB_DONE.includes(s.state);

/** A subagent event into its fan-out. A fan-out is named by its delegation id once Hermes gives one; the turn that
 *  already shows that delegation takes the event. Otherwise the running turn takes it, and with none running, the
 *  latest turn whose fan-out holds that subagent still out, else the latest turn that ran a delegate_task (a
 *  background fan-out outlives its turn). An event no turn can take (the chat opened afterwards) is left to Plans. */
function withSubagent(chat: Chat, ev: EventOf<"subagent">, now: number): Chat {
  const acts = [...chat.items.filter((i): i is ActivityItem => i.kind === "activity")].reverse();
  const byDeleg = (t: Turn) => !!ev.delegation && !!t.fanouts?.some((f) => f.delegation === ev.delegation);
  const outHere = (t: Turn) => !!t.fanouts?.some((f) => f.subs.some((s) => s.id === ev.id && !subagentEnded(s)));
  const target =
    acts.find((i) => byDeleg(i.turn))?.id ??
    chat.turn?.id ??
    acts.find((i) => outHere(i.turn))?.id ??
    acts.find((i) => i.turn.steps.some((s) => s.name === "delegate_task"))?.id;
  if (!target) return chat;
  return patchTurnById(chat, target, (t) => {
    const fanouts = [...(t.fanouts ?? [])];
    // its fan-out by delegation id; a subagent id is matched only inside a fan-out with no other delegation id
    let fi = fanouts.findIndex(
      (f) => (!!ev.delegation && f.delegation === ev.delegation) || (f.subs.some((s) => s.id === ev.id) && (!f.delegation || !ev.delegation)),
    );
    // a first event names no delegation yet: it joins the newest fan-out still filling with that many children
    if (fi < 0) fi = fanouts.findIndex((f) => !f.delegation && f.count === ev.count && f.subs.length < f.count && !f.subs.some((s) => s.index === ev.index));
    if (fi < 0) {
      fanouts.push({ key: ev.delegation ?? `${t.id}-f${fanouts.length}`, count: ev.count, startedAt: now, updatedAt: now, subs: [] });
      fi = fanouts.length - 1;
    }
    const f = fanouts[fi];
    const old = f.subs.find((s) => s.id === ev.id);
    const ended = SUB_DONE.includes(ev.state);
    const row: SubagentRow = {
      ...(old ?? { id: ev.id, startedAt: now }),
      index: ev.index,
      goal: ev.goal || old?.goal || "",
      state: old && subagentEnded(old) && !ended ? old.state : ev.state,
      ...(ev.model ? { model: ev.model } : {}),
      ...(ev.agent ? { agent: ev.agent } : {}),
      ...(ev.name ? { name: ev.name } : {}),
      ...(ev.step && ev.step !== old?.steps?.at(-1)?.text ? { steps: [...(old?.steps ?? []), { tool: ev.tool, text: ev.step }].slice(-SUB_STEPS) } : {}),
      ...(ev.dag ? { dag: ev.dag } : {}),
      // the step line is the current tool's; it goes when the child ends (its result line takes its place)
      ...(ev.step !== undefined ? { step: ev.step, tool: ev.tool } : {}),
      ...(ended ? { endedAt: old?.endedAt ?? now, summary: ev.summary, seconds: ev.seconds, step: undefined, tool: undefined } : {}),
    } as SubagentRow;
    const subs = old ? f.subs.map((s) => (s.id === ev.id ? row : s)) : [...f.subs, row].sort((a, b) => a.index - b.index);
    fanouts[fi] = { ...f, subs, updatedAt: now, count: Math.max(f.count, ev.count), ...(ev.delegation ? { delegation: ev.delegation } : {}) };
    return { ...t, fanouts };
  });
}

/** Closes the running turn (if any) and moves it to lastTurn. */
function endTurn(chat: Chat, now: number, outcome: NonNullable<Turn["outcome"]>, error?: string): Chat {
  if (!chat.turn) return chat;
  const patched = patchTurn(chat, (t) => ({
    ...t,
    endedAt: now,
    outcome,
    ...(error ? { error } : {}),
    steps: t.steps.map((s) => (s.endedAt ? s : { ...s, endedAt: now })),
  }));
  return { ...patched, lastTurn: patched.turn, turn: null };
}

function touchChat(state: AppState, bot: string, fn: (c: Chat) => Chat): AppState {
  const chat = state.chats[bot] ?? emptyChat();
  return { ...state, chats: { ...state.chats, [bot]: fn(chat) } };
}

function bumpUnread(state: AppState, bot: string): AppState {
  if (bot === state.selectedBot) return state;
  return { ...state, unread: { ...state.unread, [bot]: (state.unread[bot] ?? 0) + 1 } };
}

/** Insert `extra` rows into `base` by ts, after the last row whose ts is <= theirs. */
function mergeByTs(base: ChatItem[], extra: ChatItem[]): ChatItem[] {
  const out = [...base];
  for (const r of extra) {
    let idx = out.length;
    while (idx > 0 && out[idx - 1].ts > r.ts) idx -= 1;
    out.splice(idx, 0, r);
  }
  return out;
}

/** "slack:C1:1794.5" + "#og-dev" -> { source: "slack", label: "#og-dev" }. */
export function replyOf(ref: ReplyRef): { source: string; label: string } {
  return { source: ref.target.split(":")[0] || "elsewhere", label: ref.label };
}

/** The chip for an away session, or null when it has no thread to reply in. */
export function replyChipFor(a: Away): ReplyChip | null {
  if (!a.reply_target) return null;
  const parts = a.reply_target.split(":");
  const source = parts[0] || a.source;
  const name = SOURCE_NAMES[source] ?? source;
  return { session_id: a.id, source, place: a.place?.trim() || name, kind: parts.length >= 3 ? "thread" : "channel" };
}
const SOURCE_NAMES: Record<string, string> = { slack: "Slack", discord: "Discord", telegram: "Telegram" };

/** `since`: when the chat.open request went out. A turn that started or ended after that is newer than the reply's
 *  `running`, which then changes nothing: the live events are the truth for it. */
function applyOpened(chat: Chat, res: ChatOpenResult, now: number, bot: string, since = Infinity): Chat {
  const server: MessageItem[] = res.messages.map((m) => ({
    kind: m.role,
    id: m.id,
    ts: m.ts,
    text: m.text,
    ...(m.reply_to ? { reply: replyOf(m.reply_to) } : {}),
  }));
  const ids = new Set(server.map((m) => m.id));
  const lastServerTs = server.length ? server[server.length - 1].ts : 0;
  const keep = chat.items.filter((i) => {
    if (i.kind !== "user" && i.kind !== "assistant") return true;
    if (ids.has(i.id)) return false;
    if (i.id.startsWith("local-")) {
      const sent = i.sent ?? i.text;
      const twin = server.find((s) => s.kind === "user" && s.text === sent && s.ts >= i.ts - 120);
      // keep the local pictures, and the text as typed (skill tokens go out hoisted)
      if (twin && (i.files || i.sent)) Object.assign(twin, { text: i.text, sent, ...(i.files ? { files: i.files } : {}) });
      return !twin;
    }
    return i.ts >= lastServerTs;
  });
  let next: Chat = {
    ...withItems(chat, mergeByTs(server, keep)),
    model: res.model,
    provider: res.provider,
    reasoning: res.reasoning,
    loaded: true,
    sessionId: res.session_id,
  };
  if (res.running && !next.turn && !((next.lastTurn?.endedAt ?? -Infinity) >= since)) {
    next = newTurn(next, bot, now, WORKING)[0];
  } else if (!res.running && next.turn && next.turn.startedAt < since) {
    next = endTurn(next, now, "done");
  }
  return next;
}

// ---- reducer --------------------------------------------------------------------------------

export type Action =
  | { type: "conn"; status: BridgeStatus; now?: number }
  | { type: "chat.failed"; bot: string; message: string }
  | { type: "hello"; hello: HelloResult }
  | { type: "error"; message: string | null }
  | { type: "bots"; bots: Bot[] }
  | { type: "select"; bot: string }
  | { type: "chat.opened"; bot: string; res: ChatOpenResult; now: number; since?: number }
  | {
      type: "local.user";
      bot: string;
      id: string;
      text: string;
      now: number;
      reply?: { source: string; label: string };
      files?: SentFile[];
      sent?: string;
    }
  | { type: "reply.set"; bot: string; chip: ReplyChip | null }
  | { type: "send.failed"; bot: string; id: string; error: string }
  | { type: "event"; ev: BridgeEvent; now: number }
  | { type: "approval.resolved"; bot: string; request_id: string; choice: ApprovalChoice }
  | { type: "clarify.resolved"; bot: string; request_id: string; answer: string; answers?: ClarifyAnswers }
  | { type: "elsewhere"; bot: string; sessions: Away[] }
  | { type: "peek.loading"; id: string }
  | { type: "peek.loaded"; id: string; messages: PeekMsg[]; total: number }
  | { type: "peek.failed"; id: string; error: string }
  | { type: "routines"; bot: string; routines: Routine[] }
  | { type: "automations"; automations: Automation[] }
  | { type: "ui.automations"; job?: string | null }
  | { type: "ui.plugins"; bot?: string | null }
  | { type: "ui.lang"; lang: Lang }
  | { type: "models"; bot: string; options: ModelOptions }
  | { type: "model.set"; bot: string; current: ModelCurrent }
  | { type: "ui.panel"; open?: boolean }
  | { type: "ui.panelTab"; tab: PanelTabId }
  | { type: "ui.run"; run: string | null }
  | { type: "ui.runsFull"; open: boolean }
  | { type: "ui.draft"; bot: string; text: string }
  | { type: "ui.theme"; theme: Theme }
  | { type: "ui.look"; look: Partial<Look> }
  | { type: "ui.settings"; page?: string }
  | { type: "ui.closeSettings" }
  | { type: "system.note"; bot: string; text: string; now: number }
  | { type: "ui.pin"; bot: string; on: boolean }
  | { type: "ui.hide"; bot: string; on: boolean }
  | { type: "ui.focusAsk"; bot: string; id: string }
  | { type: "ui.session"; id: string | null }
  /** After a restart: the panel, Plans view and open session as they were (resume.ts). */
  | { type: "ui.restore"; ui: Pick<Ui, "panelOpen" | "panelTab" | "runsFull" | "runId"> & { session: string | null } }
  /** Drop a chat that is gone for good (a closed SESSIONS chat): its open asks go with it. */
  | { type: "chat.forget"; bot: string }
  /** A SESSIONS chat ended with `error`: its last turn, failed with that same reason, no longer repeats it (the
   *  Ended line above the composer says it once, beside Restart). */
  | { type: "turn.reasonMoved"; bot: string; error: string };

// ---- chats that are not a bot's main chat ------------------------------------------------------
//
// SESSIONS chats reuse this reducer and the bot chat's timeline, cards and composer under their own key:
// `fold:<bot>:<id>` for a Hermes chat in a folder (bridge `folder.open`, events tagged `session`) and
// `agent:<id>` for a Claude Code / Codex / pi chat run by the desktop shell. A route says where the
// person's answers go.

export interface ChatRoute {
  send(text: string): Promise<void>;
  interrupt(): Promise<void>;
  approve(requestId: string, choice: ApprovalChoice): Promise<void>;
  /** A text answer, or (Hermes folder chats) an interview's answers per question id. */
  clarify(requestId: string, answer: string | ClarifyAnswers): Promise<void>;
  /** Name for notifications. */
  label: string;
  /** Show this chat (a notification was clicked). */
  open(): void;
}

const chatRoutes = new Map<string, ChatRoute>();
/** Register (or with null, remove) where chat `key`'s answers go. */
export function setChatRoute(key: string, route: ChatRoute | null): void {
  if (route) chatRoutes.set(key, route);
  else chatRoutes.delete(key);
}
export const chatRoute = (key: string): ChatRoute | undefined => chatRoutes.get(key);
/** Key of a folder chat's events. */
export const folderKey = (bot: string, session: string) => `fold:${bot}:${session}`;
/** True for a SESSIONS chat key (not a bot's main chat). */
export const isSessionChat = (key: string) => key.startsWith("fold:") || key.startsWith("agent:");

function reduceEvent(state: AppState, ev: BridgeEvent, now: number): AppState {
  if (ev.session && ev.event !== "folder.closed") {
    if (ev.event === "bot.status") return state; // a folder chat's turn never moves the bot's own status
    return reduceEvent(state, { ...ev, bot: folderKey(ev.bot, ev.session), session: undefined }, now);
  }
  const bot = ev.bot;
  switch (ev.event) {
    // A turn starts only on turn.start (or a chat found running on open). Every other live event belongs to the
    // running turn and is dropped without one: an agent's own status after its turn ended (OmO's setStatus after
    // agent_end) must not start a turn that nothing ends.
    case "turn.start":
      return touchChat(state, bot, (c) => {
        const early = c.early && now - c.early.at <= EARLY_STATUS_MS ? c.early.text : "";
        return { ...newTurn(endTurn(c, now, "done"), bot, now, early)[0], early: null };
      });
    case "status":
      return touchChat(state, bot, (c) =>
        c.turn ? patchTurn(c, (t) => ({ ...t, status: ev.text })) : { ...c, early: { text: ev.text, at: now } },
      );
    case "thinking":
      return touchChat(state, bot, (c) => (c.turn && !c.turn.status ? patchTurn(c, (t) => ({ ...t, status: THINKING })) : c));
    case "tool.start":
      return touchChat(state, bot, (c) =>
        patchTurn(c, (t) => ({
          ...t,
          status: activityText(ev.name, ev.detail),
          steps: [
            ...t.steps,
            { id: ev.tool_id, name: ev.name, detail: ev.detail, startedAt: now, ...(ev.dag?.length ? { dag: ev.dag } : {}) },
          ],
        })),
      );
    case "tool.end":
      return touchChat(state, bot, (c) =>
        patchTurn(c, (t) => ({
          ...t,
          steps: t.steps.map((s) => (s.id === ev.tool_id ? { ...s, endedAt: now, ok: ev.ok } : s)),
        })),
      );
    case "subagent": {
      const c = state.chats[bot];
      const next = c && withSubagent(c, ev, now);
      return next && next !== c ? { ...state, chats: { ...state.chats, [bot]: next } } : state;
    }
    case "skill":
      return touchChat(state, bot, (c) =>
        patchTurn(c, (t) => (t.skills.includes(ev.name) ? t : { ...t, skills: [...t.skills, ev.name] })),
      );
    case "delta":
      return touchChat(state, bot, (c) => patchTurn(c, (t) => ({ ...t, streaming: t.streaming + ev.text })));
    case "message": {
      const next = touchChat(state, bot, (c) => {
        const cleared = patchTurn(c, (t) => ({ ...t, streaming: "" }));
        const msg: MessageItem = { kind: "assistant", id: ev.id, ts: now / 1000, text: ev.text };
        const exists = cleared.items.some((i) => i.kind === "assistant" && i.id === ev.id);
        const items = exists
          ? cleared.items.map((i) => (i.kind === "assistant" && i.id === ev.id ? { ...i, text: ev.text } : i))
          : [...cleared.items, msg];
        return withItems(cleared, items);
      });
      const existed = state.chats[bot]?.items.some((i) => i.kind === "assistant" && i.id === ev.id);
      return existed ? next : bumpUnread(next, bot);
    }
    case "approval.request":
      return touchChat(state, bot, (c) => {
        // chat.open replays asks that are still waiting; the card is already there.
        if (c.items.some((i) => i.kind === "approval" && i.request_id === ev.request_id)) return c;
        const base = patchTurn(c, (t) => ({ ...t, status: tr("live.waitApproval") }));
        const item: ApprovalItem = {
          kind: "approval",
          id: `approval-${ev.request_id}`,
          ts: now / 1000,
          request_id: ev.request_id,
          title: ev.title,
          command: ev.command,
          choices: ev.choices,
          ...(ev.cwd ? { cwd: ev.cwd } : {}),
          ...(ev.subagent?.id ? { subagent: ev.subagent } : {}),
        };
        return withItems(base, [...base.items, item]);
      });
    case "clarify.request":
      return touchChat(state, bot, (c) => {
        if (c.items.some((i) => i.kind === "clarify" && i.request_id === ev.request_id)) return c;
        const base = patchTurn(c, (t) => ({ ...t, status: tr("live.waitAnswer") }));
        const qs = (ev.questions ?? []).filter((q) => q && typeof q.question === "string" && q.question.trim());
        const item: ClarifyItem = {
          kind: "clarify",
          id: `clarify-${ev.request_id}`,
          ts: now / 1000,
          request_id: ev.request_id,
          question: ev.question || qs[0]?.question || "",
          choices: ev.choices,
          ...(ev.multi_select ? { multi: true } : {}),
          ...(qs.length > 1 ? { questions: qs } : {}),
          ...(ev.subagent?.id ? { subagent: ev.subagent } : {}),
        };
        return withItems(base, [...base.items, item]);
      });
    case "prompt.expired":
      return touchChat(state, bot, (c) =>
        withItems(
          c,
          c.items.map((i) => {
            if (i.kind === "approval" && i.request_id === ev.request_id && !i.resolved) return { ...i, expired: ev.reason };
            if (i.kind === "clarify" && i.request_id === ev.request_id && i.answer === undefined) return { ...i, expired: ev.reason };
            return i;
          }),
        ),
      );
    case "turn.end":
      return touchChat(state, bot, (c) => {
        let base = c;
        // A done turn that streamed text but never sent the final message: keep what was said.
        if (ev.outcome === "done" && c.turn && c.turn.streaming) {
          const text = c.turn.streaming;
          base = withItems(c, [...c.items, { kind: "assistant", id: `${c.turn.id}-a`, ts: now / 1000, text }]);
          base = patchTurn(base, (t) => ({ ...t, streaming: "" }));
        }
        return { ...endTurn(base, now, ev.outcome, ev.error), early: null };
      });
    case "bot.status":
      return {
        ...state,
        bots: state.bots.map((b) => (b.name === bot ? { ...b, status: ev.status, running: ev.running } : b)),
      };
    case "elsewhere.update":
    case "bots.update":
    case "accounts.update":
      return state; // the store refetches; nothing to change here
    case "routine.added": {
      const id = `routine-added-${ev.routine_id}`;
      if (state.chats[bot]?.items.some((i) => i.id === id)) return state;
      const item: RoutineAddedItem = {
        kind: "routineAdded",
        id,
        ts: ev.ts || now / 1000,
        routine_id: ev.routine_id,
        name: ev.name,
        schedule: ev.schedule,
        next_run_at: ev.next_run_at,
        deliver: ev.deliver,
        origin: ev.origin,
      };
      return bumpUnread(touchChat(state, bot, (c) => withItems(c, [...c.items, item])), bot);
    }
    case "plugin.added": {
      const id = `plugin-added-${ev.name}-${ev.ts}`;
      if (state.chats[bot]?.items.some((i) => i.id === id)) return state;
      const item: PluginAddedItem = { kind: "pluginAdded", id, ts: ev.ts || now / 1000, name: ev.name, title: ev.title, tools: ev.tools, hooks: ev.hooks };
      return bumpUnread(touchChat(state, bot, (c) => withItems(c, [...c.items, item])), bot);
    }
    case "routine.ran": {
      const next = touchChat(state, bot, (c) =>
        withItems(c, [
          ...c.items,
          {
            kind: "routine",
            id: `routine-${ev.routine_id}-${ev.ts}`,
            ts: ev.ts,
            routine_id: ev.routine_id,
            name: ev.name,
            status: ev.status,
          },
        ]),
      );
      return bumpUnread(next, bot);
    }
    // a message sent while a turn ran (a SESSIONS chat): waiting until the agent takes it, or thrown away by Stop
    case "message.queued":
    case "message.taken":
    case "message.dropped": {
      const id = (ev as { id?: unknown }).id;
      if (typeof id !== "string" || !state.chats[bot]?.items.some((i) => i.kind === "user" && i.id === id)) return state;
      const wait = ev.event === "message.queued" ? ("queued" as const) : ev.event === "message.dropped" ? ("dropped" as const) : undefined;
      return touchChat(state, bot, (c) =>
        withItems(
          c,
          c.items.map((i) => {
            if (i.kind !== "user" || i.id !== id) return i;
            const { wait: _old, ...rest } = i;
            return wait ? { ...rest, wait } : rest;
          }),
        ),
      );
    }
    default:
      return state;
  }
}

export function reduce(state: AppState, a: Action): AppState {
  switch (a.type) {
    case "conn": {
      if (a.status === "open" || a.status === state.conn) return { ...state, conn: a.status };
      // The bridge went away: whatever was running is no longer observed. End live turns as interrupted
      // now, so the activity line and Stop do not stay up for the whole outage (a later chat.open with
      // running:false must not turn them into "done").
      const t = a.now ?? Date.now();
      const chats: AppState["chats"] = {};
      // agent:<id> chats run in the desktop shell, not through Hermes: a bridge outage does not touch them
      for (const [b, c] of Object.entries(state.chats))
        chats[b] = c.turn && !b.startsWith("agent:") ? endTurn(c, t, "interrupted", tr("live.lost")) : c;
      return { ...state, conn: a.status, chats };
    }
    case "chat.failed":
      return touchChat(state, a.bot, (c) => ({ ...c, loaded: true, openError: a.message }));
    case "hello":
      return { ...state, hello: a.hello };
    case "error":
      return { ...state, lastError: a.message };
    case "bots":
      return { ...state, bots: a.bots };
    case "select":
      return { ...state, selectedBot: a.bot, unread: { ...state.unread, [a.bot]: 0 }, ui: { ...state.ui, view: "chat" } };
    case "chat.opened":
      return touchChat(state, a.bot, (c) => ({ ...applyOpened(c, a.res, a.now, a.bot, a.since), openError: null }));
    case "local.user":
      return touchChat(state, a.bot, (c) =>
        withItems(c, [
          ...c.items,
          {
            kind: "user",
            id: a.id,
            ts: a.now / 1000,
            text: a.text,
            ...(a.reply ? { reply: a.reply } : {}),
            ...(a.files?.length ? { files: a.files } : {}),
            ...(a.sent !== undefined && a.sent !== a.text ? { sent: a.sent } : {}),
          },
        ]),
      );
    case "reply.set":
      return { ...state, replyTo: { ...state.replyTo, [a.bot]: a.chip } };
    case "send.failed":
      return touchChat(state, a.bot, (c) =>
        withItems(
          c,
          c.items.map((i) => (i.kind === "user" && i.id === a.id ? { ...i, error: a.error } : i)),
        ),
      );
    case "event":
      return reduceEvent(state, a.ev, a.now);
    case "approval.resolved":
      return touchChat(state, a.bot, (c) =>
        doneWaiting(
          withItems(
            c,
            c.items.map((i) =>
              i.kind === "approval" && i.request_id === a.request_id ? { ...i, resolved: a.choice } : i,
            ),
          ),
        ),
      );
    case "clarify.resolved":
      return touchChat(state, a.bot, (c) =>
        doneWaiting(
          withItems(
            c,
            c.items.map((i) =>
              i.kind === "clarify" && i.request_id === a.request_id
                ? { ...i, answer: a.answer, ...(a.answers ? { answers: a.answers } : {}) }
                : i,
            ),
          ),
        ),
      );
    case "elsewhere":
      return {
        ...state,
        elsewhere: { ...state.elsewhere, [a.bot]: [...a.sessions].sort((x, y) => y.last_active - x.last_active) },
      };
    case "peek.loading":
      return {
        ...state,
        peeks: {
          ...state.peeks,
          [a.id]: { messages: state.peeks[a.id]?.messages ?? [], total: state.peeks[a.id]?.total ?? 0, loading: true },
        },
      };
    case "peek.loaded":
      return { ...state, peeks: { ...state.peeks, [a.id]: { messages: a.messages, total: a.total, loading: false } } };
    case "peek.failed":
      return {
        ...state,
        peeks: {
          ...state.peeks,
          [a.id]: { messages: state.peeks[a.id]?.messages ?? [], total: state.peeks[a.id]?.total ?? 0, loading: false, error: a.error },
        },
      };
    case "routines":
      return { ...state, routines: { ...state.routines, [a.bot]: a.routines } };
    case "automations":
      return { ...state, automations: a.automations };
    case "ui.automations":
      return { ...state, ui: { ...state.ui, view: "automations", ...(a.job !== undefined ? { automation: a.job } : {}) } };
    case "ui.plugins":
      return { ...state, ui: { ...state.ui, view: "plugins", ...(a.bot ? { pluginsBot: a.bot } : {}) } };
    case "ui.lang":
      return { ...state, ui: { ...state.ui, lang: a.lang } };
    case "models":
      return { ...state, models: { ...state.models, [a.bot]: a.options } };
    case "model.set": {
      const next = touchChat(state, a.bot, (c) => ({
        ...c,
        model: a.current.model,
        provider: a.current.provider,
        reasoning: a.current.reasoning,
      }));
      return {
        ...next,
        bots: next.bots.map((b) =>
          b.name === a.bot ? { ...b, model: a.current.model, provider: a.current.provider } : b,
        ),
        models: next.models[a.bot]
          ? { ...next.models, [a.bot]: { ...next.models[a.bot], current: a.current } }
          : next.models,
      };
    }
    case "ui.panel":
      return { ...state, ui: { ...state.ui, panelOpen: a.open ?? !state.ui.panelOpen } };
    case "ui.panelTab":
      return { ...state, ui: { ...state.ui, panelOpen: true, panelTab: a.tab } };
    case "ui.run":
      return { ...state, ui: { ...state.ui, panelOpen: true, panelTab: "runs", runId: a.run } };
    case "ui.runsFull":
      return { ...state, ui: { ...state.ui, runsFull: a.open, ...(a.open ? { panelOpen: true, panelTab: "runs" as const } : {}) } };
    case "ui.draft":
      return { ...state, ui: { ...state.ui, draft: { bot: a.bot, text: a.text, n: (state.ui.draft?.n ?? 0) + 1 } } };
    case "ui.theme":
      return { ...state, ui: { ...state.ui, theme: a.theme } };
    case "ui.look":
      return { ...state, ui: { ...state.ui, look: { ...state.ui.look, ...a.look } } };
    case "ui.settings":
      return { ...state, ui: { ...state.ui, view: "settings", settingsPage: a.page ?? state.ui.settingsPage } };
    case "ui.closeSettings":
      return { ...state, ui: { ...state.ui, view: "chat" } };
    case "system.note":
      return touchChat(state, a.bot, (c) =>
        withItems(c, [...c.items, { kind: "system", id: `system-${a.now}-${c.items.length}`, ts: a.now / 1000, text: a.text }]),
      );
    case "ui.restore": {
      const { session, ...rest } = a.ui;
      return { ...state, ui: { ...state.ui, ...rest, ...(session ? { view: "session" as const, session } : {}) } };
    }
    case "ui.session":
      return a.id
        ? { ...state, ui: { ...state.ui, view: "session", session: a.id } }
        : { ...state, ui: { ...state.ui, view: state.ui.view === "session" ? "chat" : state.ui.view, session: null } };
    case "ui.pin": {
      const rest = state.ui.pinned.filter((b) => b !== a.bot);
      return { ...state, ui: { ...state.ui, pinned: a.on ? [...rest, a.bot] : rest } };
    }
    case "ui.hide": {
      const rest = state.ui.hidden.filter((b) => b !== a.bot);
      return { ...state, ui: { ...state.ui, hidden: a.on ? [...rest, a.bot] : rest } };
    }
    case "ui.focusAsk":
      return { ...state, ui: { ...state.ui, focusAsk: { bot: a.bot, id: a.id, seq: (state.ui.focusAsk?.seq ?? 0) + 1 } } };
    case "turn.reasonMoved": {
      const c = state.chats[a.bot];
      const last = c?.lastTurn;
      if (!c || !last || last.outcome !== "error" || last.error?.trim() !== a.error.trim()) return state;
      return { ...state, chats: { ...state.chats, [a.bot]: patchTurnById(c, last.id, ({ error: _, ...t }) => t) } };
    }
    case "chat.forget": {
      if (!state.chats[a.bot]) return state;
      const chats = { ...state.chats };
      delete chats[a.bot];
      return { ...state, chats };
    }
    default:
      return state;
  }
}

// ---- selectors ------------------------------------------------------------------------------

const timelineCache = new Map<string, { items: ChatItem[]; away: Away[] | undefined; max: number; out: TimelineItem[] }>();

/**
 * The bot's timeline: chat rows in order with its elsewhere sessions placed by `last_active`.
 * Only the `maxAway` most recent elsewhere sessions go in (the UI shows the rest in the panel).
 * The result is memoised, so it is safe to call from render.
 */
export function selectTimeline(state: AppState, bot: string, maxAway = 2): TimelineItem[] {
  const items = state.chats[bot]?.items ?? EMPTY_ITEMS;
  const away = state.elsewhere[bot];
  const hit = timelineCache.get(bot);
  if (hit && hit.items === items && hit.away === away && hit.max === maxAway) return hit.out;
  const recent = [...(away ?? [])].sort((a, b) => b.last_active - a.last_active).slice(0, maxAway);
  const out: TimelineItem[] = [...items];
  // oldest first so equal timestamps keep newest-last
  for (const a of recent.reverse()) {
    const row: AwayItem = { kind: "away", id: `away-${a.id}`, ts: a.last_active, away: a };
    let idx = out.length;
    while (idx > 0 && out[idx - 1].ts > row.ts) idx -= 1;
    out.splice(idx, 0, row);
  }
  timelineCache.set(bot, { items, away, max: maxAway, out });
  return out;
}
const EMPTY_ITEMS: ChatItem[] = [];

/** One approval or question still waiting on the person, in any bot's chat. */
export interface Ask {
  bot: string;
  item: ApprovalItem | ClarifyItem;
  /** seconds since epoch */
  ts: number;
}

/** False once the ask is answered, expired, or the turn that raised it is over (it went unanswered). An ask
 *  raised outside any known turn stays open until answered or expired. */
export function askOpen(items: ChatItem[], it: ApprovalItem | ClarifyItem): boolean {
  if (it.expired) return false;
  if (it.kind === "approval" ? !!it.resolved : it.answer !== undefined) return false;
  let owner: number | undefined;
  for (const i of items) if (i.kind === "activity" && i.turn.startedAt <= it.ts * 1000 + 1) owner = i.turn.endedAt ?? -1;
  return owner === undefined || owner === -1;
}

let asksCache: { chats: AppState["chats"]; out: Ask[] } | null = null;

/** Every open ask across bots, oldest first. Memoised on `state.chats`, so safe to call from render. */
export function selectAsks(state: AppState): Ask[] {
  if (asksCache && asksCache.chats === state.chats) return asksCache.out;
  const out: Ask[] = [];
  for (const [bot, chat] of Object.entries(state.chats)) {
    for (const it of chat.items) {
      if ((it.kind === "approval" || it.kind === "clarify") && askOpen(chat.items, it)) out.push({ bot, item: it, ts: it.ts });
    }
  }
  out.sort((a, b) => a.ts - b.ts);
  asksCache = { chats: state.chats, out };
  return out;
}

/** Who an ask comes from, as the Needs-you list names it: the bot's name, or for a SESSIONS chat its route's
 *  label (the session's folder and agent, "web-app · Claude Code"). */
export function askFrom(state: AppState, key: string): string {
  return chatRoute(key)?.label ?? state.bots.find((b) => b.name === key)?.display_name ?? key;
}

/** One plain line for an ask: "Allow `rm -rf build/`?" or the (first) question. */
export function askText(it: ApprovalItem | ClarifyItem): string {
  if (it.kind === "approval") return it.command ? tr("ask.allowCmd", { cmd: `\`${it.command}\`` }) : it.title || tr("ask.allowThis");
  const n = it.questions?.length ?? 0;
  return n > 1 ? tr("ask.questions", { n, first: it.questions![0].question }) : it.question;
}

let sideCache: { bots: Bot[]; pinned: string[]; hidden: string[]; out: Bot[] } | null = null;

/** The sidebar's bot order: pinned bots first (in pin order), then the rest as Hermes lists them; hidden bots
 *  are left out. ⌘1…⌘9 follow this order too. Memoised. */
export function selectSidebarBots(state: AppState): Bot[] {
  const { bots } = state;
  const { pinned, hidden } = state.ui;
  if (sideCache && sideCache.bots === bots && sideCache.pinned === pinned && sideCache.hidden === hidden) return sideCache.out;
  const shown = bots.filter((b) => !hidden.includes(b.name));
  const pins = pinned.map((n) => shown.find((b) => b.name === n)).filter((b): b is Bot => !!b);
  const out = [...pins, ...shown.filter((b) => !pinned.includes(b.name))];
  sideCache = { bots, pinned, hidden, out };
  return out;
}

export function selectUnreadTotal(state: AppState): number {
  return Object.values(state.unread).reduce((a, b) => a + b, 0);
}

// ---- store ----------------------------------------------------------------------------------

export interface Actions {
  init(): Promise<void>;
  selectBot(bot: string): Promise<void>;
  /** Sends to the main chat; a "Reply there" chip goes along as `reply_to` and is then cleared. Skill tokens
   *  (`./name`) go out hoisted to the front as `/name`; the bubble keeps the text as typed. */
  send(text: string): Promise<void>;
  /** Put (or clear, with null) the composer's "Reply there" chip for a bot. Sends nothing. */
  setReplyTo(chip: ReplyChip | null, bot?: string): void;
  /** Attach each file in order (`chat.attach`), then send. Rejects, sending nothing, if any attach fails. */
  sendWithFiles(text: string, files: OutFile[]): Promise<void>;
  interrupt(): Promise<void>;
  respondApproval(requestId: string, choice: ApprovalChoice, bot?: string): Promise<void>;
  /** A text answer for one question, or every answer of an interview at once (one `clarify.respond`). */
  respondClarify(requestId: string, answer: string | ClarifyAnswers, bot?: string): Promise<void>;
  loadElsewhere(bot?: string): Promise<void>;
  loadRoutines(bot?: string): Promise<void>;
  /** Re-read every bot's automations (files only; no gateway). */
  loadAutomations(): Promise<void>;
  /** Open the Automations page, on one job (`<bot>:<id>`) when given. */
  openAutomations(job?: string | null): void;
  /** Open the Plugins page, scoped to `bot` when given (else the last one, else the selected bot). */
  openPlugins(bot?: string | null): void;
  /** Open `bot`'s main chat and send `text` there (the pages' "say it in words" box, Run now). */
  sendTo(bot: string, text: string): Promise<void>;
  /** The bot's own `cron.manage` through the bridge: pause, resume or remove one job, or add one. Rejects with
   *  the bridge's error (Hermes' own text when it refused). */
  automationDo(bot: string, job: string, action: "pause" | "resume" | "remove"): Promise<void>;
  addAutomation(p: OpMap["automations.add"]["params"]): Promise<{ job: string; name: string }>;
  /** Plugins: reads and the bot's own `plugins.manage` (the page keeps its own copy). */
  pluginsList(bot: string): Promise<PluginRow[]>;
  pluginsCatalog(bot: string, query?: string, category?: string): Promise<CatalogResult>;
  pluginsInspect(bot: string, catalogName: string): Promise<InspectResult>;
  pluginsInstall(bot: string, catalogName: string, sha: string): Promise<OpMap["plugins.install"]["result"]>;
  pluginsToggle(bot: string, key: string, enable: boolean): Promise<OpMap["plugins.toggle"]["result"]>;
  pluginsUpdate(bot: string, name: string): Promise<OpMap["plugins.update"]["result"]>;
  pluginsRemove(bot: string, name: string): Promise<void>;
  /** Settings › General › Language: saved on this computer, applied at once (no restart). */
  setLanguage(lang: Lang): void;
  loadModels(bot?: string): Promise<void>;
  peek(sessionId: string, limit?: number, bot?: string): Promise<void>;
  setModel(change: { model?: string; provider?: string; reasoning?: string }): Promise<void>;
  togglePanel(open?: boolean): void;
  /** Open the side panel on one tab (Details, Terminal, Schedule, Worktrees, Diff). */
  setPanelTab(tab: PanelTabId): void;
  /** Open the Runs tab on one run (null: the first in the list). */
  openRun(run: string | null): void;
  /** Show or hide the full-size Runs graph over the chat column. */
  setRunsFull(open: boolean): void;
  /** Put text in the selected bot's composer and focus it. Never sends. */
  prefill(text: string): void;
  setTheme(theme: Theme): void;
  setLook(look: Partial<Look>): void;
  openSettings(page?: string): void;
  closeSettings(): void;
  /** Sidebar row menu: pin to top / hide from the list (saved on this computer). */
  pinBot(bot: string, on: boolean): void;
  hideBot(bot: string, on: boolean): void;
  /** Open the bot's chat and scroll to / focus one of its ask cards. */
  jumpToAsk(bot: string, id: string): Promise<void>;
  /** Show terminal session `id` in the main column; null goes back to the selected bot's chat. */
  openSession(id: string | null): void;
  /** A new Hermes chat for `bot` in folder `cwd` (SESSIONS > oh-my-hermes). */
  folderOpen(bot: string, cwd: string): Promise<FolderOpenResult>;
  folderClose(bot: string, session: string): Promise<void>;
  /** Change the model of folder chat `session`. */
  folderSetModel(bot: string, session: string, change: { model: string; provider?: string }): Promise<ModelCurrent>;
  folderSend(bot: string, session: string, text: string): Promise<void>;
  folderInterrupt(bot: string, session: string): Promise<void>;
  folderApprove(bot: string, session: string, requestId: string, choice: ApprovalChoice): Promise<void>;
  folderClarify(bot: string, session: string, requestId: string, answer: string | ClarifyAnswers): Promise<void>;
  /** Re-read bots.list (names, status, picture revisions). */
  reloadBots(): Promise<void>;
  renameBot(bot: string, name: string): Promise<void>;
  setAvatar(bot: string, data: string | null): Promise<void>;
  botInfo(bot: string): Promise<BotInfo>;
  /** The bot's skills for the composer's `./` picker, read once per bot; [] when the bridge cannot list them. */
  skills(bot: string): Promise<Skill[]>;
  /** Channel names for Slack / Discord link chips, read once per bot; empty when the bridge cannot say. */
  linkPlaces(bot: string): Promise<LinkPlaces>;
  avatarOf(bot: string): Promise<{ rev: number | null; data: string | null }>;
  /** Side panel reads (never cached in the store; the panel keeps its own copy). */
  panelTerminal(bot: string): Promise<{ runs: TerminalRun[] }>;
  panelWorktrees(bot: string): Promise<{ worktrees: Worktree[] }>;
  panelDiff(bot: string, path: string): Promise<WorktreeDiff>;
  /** A file the bot sent (`MEDIA:` line); never cached in the store. */
  readMedia(bot: string, path: string, info?: boolean): Promise<MediaFile>;
  /** Runs tab reads (read-only: nothing here retries or cancels a run). */
  runsList(bot: string): Promise<{ runs: AgentRunSummary[] }>;
  runsGet(bot: string, run: string): Promise<RunDetail>;
  /** The GitHub state of the PRs a run's nodes name (the bridge asks `gh`, apart from `runsGet`). */
  runsPrs(bot: string, run: string): Promise<{ prs: Record<string, NodePr> }>;
  runsCli(params?: { agent?: CliAgent; cwd?: string; since?: number }): Promise<{ runs: AgentRunSummary[] }>;
  /** A SESSIONS chat's title from the agent's own session files (`cli.title`). */
  cliTitle(agent: "claude" | "codex", session: string, cwd?: string): Promise<{ title: string }>;
  /** Subscription usage meters (sidebar); the meter keeps its own copy. */
  usage(): Promise<{ providers: UsageProvider[] }>;
  /** Settings › Accounts (the page keeps its own copy). */
  accounts(): Promise<{ groups: AccountGroup[] }>;
  addAccount(cli: AccountCli, label: string): Promise<{ id: string; dir: string }>;
  setActiveAccount(cli: AccountCli, id: string): Promise<void>;
  removeAccount(cli: AccountCli, id: string): Promise<void>;
  labelAccount(cli: AccountCli, id: string, label: string): Promise<void>;
  /** A cancelled sign-in: the new, still empty folder goes. */
  discardAccount(cli: AccountCli, id: string): Promise<void>;
  /** A quiet omher line in a bot's main chat (the selected bot when none is given). */
  systemNote(text: string, bot?: string): void;
  /** Every bridge event, for views that keep their own copy (Accounts listens for `accounts.update`). */
  onBridgeEvent(fn: (ev: BridgeEvent) => void): () => void;
}

export type BridgeLike = Pick<BridgeClient, "connect" | "request" | "onAny" | "onStatus">;

export interface Store {
  /** Settles once init has put back what was saved before a restart (or found nothing to put back). */
  resumed: Promise<void>;
  getState(): AppState;
  /** State plus actions, one stable object per state version (for useSyncExternalStore). */
  getSnapshot(): AppState & Actions;
  subscribe(fn: () => void): () => void;
  dispatch(a: Action): void;
  actions: Actions;
}

function lastUserReplied(state: AppState, bot: string): boolean {
  const items = state.chats[bot]?.items ?? [];
  for (let i = items.length - 1; i >= 0; i -= 1) {
    const it = items[i];
    if (it.kind === "user") return !!it.reply;
  }
  return false;
}

const errText = (e: unknown) =>
  typeof e === "object" && e && "message" in e ? String((e as { message: unknown }).message) : String(e);

export interface StoreOptions {
  now?: () => number;
  /** Called for every bridge event after it is applied; the app uses it for system notifications. */
  onEvent?: (ev: BridgeEvent, state: AppState) => void;
  /** Called for every action after it is applied, and once the first state (or a reconnect's re-read) has
   *  loaded; the app uses them for sounds. */
  onAction?: (a: Action, state: AppState) => void;
  onSettled?: () => void;
  /** The snapshot saved before omher last closed (resume.ts), read once the bot list is known. */
  resume?: () => ResumeSnap | null;
}

/** Every bridge event, after the store applied it (SESSIONS listens for `folder.closed`). */
const bridgeListeners = new Set<(ev: BridgeEvent) => void>();
export function onBridgeEvent(fn: (ev: BridgeEvent) => void): () => void {
  bridgeListeners.add(fn);
  return () => bridgeListeners.delete(fn);
}

export function createStore(bridge: BridgeLike, opts: StoreOptions = {}): Store {
  const now = opts.now ?? Date.now;
  let state = initialState();
  const listeners = new Set<() => void>();
  let localSeq = 0;
  let snapshot: (AppState & Actions) | null = null;
  let started = false;
  let markResumed: () => void = () => {};
  const resumed = new Promise<void>((r) => (markResumed = r));
  const eventFns = new Set<(ev: BridgeEvent) => void>();
  // skills.list per bot: the promise (asked once) and the names, for hoisting tokens when a message is sent
  const skillLists = new Map<string, Promise<Skill[]>>();
  const skillNames = new Map<string, string[]>();

  const dispatch = (a: Action) => {
    const next = reduce(state, a);
    if (next === state) return;
    state = next;
    snapshot = null;
    for (const l of [...listeners]) l();
    opts.onAction?.(a, state);
  };
  const fail = (e: unknown) => dispatch({ type: "error", message: errText(e) });
  const botArg = (bot?: string) => bot ?? state.selectedBot;

  const loadChat = async (bot: string) => {
    let res: ChatOpenResult;
    const since = now();
    try {
      res = await bridge.request("chat.open", { bot });
    } catch (e) {
      // Without this the chat stays unloaded and the timeline shows "Loading…" forever (bot offline).
      dispatch({ type: "chat.failed", bot, message: errText(e) });
      throw e;
    }
    dispatch({ type: "chat.opened", bot, res, now: now(), since });
  };
  const loadElsewhere = async (bot?: string) => {
    const b = botArg(bot);
    if (!b) return;
    try {
      const r = await bridge.request("elsewhere.list", { bot: b });
      dispatch({ type: "elsewhere", bot: b, sessions: r.sessions });
    } catch (e) {
      fail(e);
    }
  };
  const loadRoutines = async (bot?: string) => {
    const b = botArg(bot);
    if (!b) return;
    try {
      const r = await bridge.request("routines.list", { bot: b });
      dispatch({ type: "routines", bot: b, routines: r.routines });
    } catch (e) {
      fail(e);
    }
  };
  const loadAutomations = async () => {
    try {
      dispatch({ type: "automations", automations: (await bridge.request("automations.list", {})).automations });
    } catch {
      /* an older bridge without the op, or a failed read: the page shows what it last had */
    }
  };
  const loadModels = async (bot?: string) => {
    const b = botArg(bot);
    if (!b) return;
    try {
      dispatch({ type: "models", bot: b, options: await bridge.request("models.options", { bot: b }) });
    } catch (e) {
      fail(e);
    }
  };

  const online = (b: Bot) => b.status !== "offline";

  const selectBot = async (bot: string) => {
    dispatch({ type: "select", bot });
    const jobs: Promise<unknown>[] = [loadElsewhere(bot), loadRoutines(bot), loadModels(bot)];
    if (!state.chats[bot]?.loaded) jobs.push(loadChat(bot).catch(fail));
    await Promise.all(jobs);
  };

  const reloadBots = async () => {
    try {
      const r = await bridge.request("bots.list", {});
      dispatch({ type: "bots", bots: r.bots });
    } catch (e) {
      fail(e);
    }
  };

  /** After a reconnect: events were missed, so re-read the lists and every loaded chat. */
  const resync = async () => {
    try {
      const r = await bridge.request("bots.list", {});
      dispatch({ type: "bots", bots: r.bots });
    } catch (e) {
      return fail(e);
    }
    const names = new Set(state.bots.map((b) => b.name));
    const loaded = Object.entries(state.chats).filter(([n, c]) => c.loaded && names.has(n)).map(([n]) => n);
    await Promise.allSettled([...loaded.map(loadChat), loadElsewhere(), loadRoutines(), loadAutomations()]);
  };

  const actions: Actions = {
    async init() {
      if (started) return;
      started = true;
      let opened = false;
      bridge.onStatus((status) => {
        dispatch({ type: "conn", status, now: now() });
        if (status === "open") {
          if (opened) void resync().then(() => opts.onSettled?.());
          opened = true;
        }
      });
      bridge.onAny((ev) => {
        dispatch({ type: "event", ev, now: now() });
        for (const l of [...bridgeListeners]) l(ev);
        opts.onEvent?.(ev.session ? { ...ev, bot: folderKey(ev.bot, ev.session) } : ev, state);
        for (const fn of [...eventFns]) fn(ev);
        if (ev.event === "elsewhere.update") void loadElsewhere(ev.bot);
        // After a turn the person pointed at a thread, re-read the places so the bot's new reply shows there.
        if (ev.event === "turn.end" && lastUserReplied(state, ev.bot)) void loadElsewhere(ev.bot);
        if (ev.event === "routine.ran") void loadRoutines(ev.bot);
        if (ev.event === "routine.ran" || ev.event === "routines.update" || ev.event === "routine.added") void loadAutomations();
        if (ev.event === "bots.update") void reloadBots();
      });
      await bridge.connect();
      try {
        dispatch({ type: "hello", hello: await bridge.request("hello", {}) });
        const { bots } = await bridge.request("bots.list", {});
        dispatch({ type: "bots", bots });
        // pick up where the person left off: the bot, panel and Plans view saved before a restart (a bot that
        // is gone takes them with it)
        const saved = opts.resume?.();
        const back = saved ? forBots(saved, bots.map((b) => b.name)) : null;
        const first =
          state.selectedBot && bots.some((b) => b.name === state.selectedBot) ? state.selectedBot : (back?.bot ?? bots[0]?.name);
        void loadAutomations();
        // the panel and view come back as the bot is selected, before its chat and lists load: put back only once
        // those reads ended, a click on the panel in the meantime (the places chip, ⌘.) was undone by it
        const loading = first ? selectBot(first) : Promise.resolve();
        if (back?.bot) {
          const { panelOpen, panelTab, runsFull, runId, session } = back;
          dispatch({ type: "ui.restore", ui: { panelOpen, panelTab, runsFull, runId, session } });
        } else if (back?.session) dispatch({ type: "ui.session", id: back.session });
        await loading;
        // Load the other chats too, so the sidebar can show previews and unread counts.
        await Promise.allSettled(
          bots.filter((b) => b.name !== first && online(b)).map((b) => loadChat(b.name)),
        );
      } catch (e) {
        fail(e);
      }
      markResumed();
      opts.onSettled?.();
    },
    selectBot,
    async send(text) {
      const bot = state.selectedBot;
      const t = text.trim();
      if (!bot || !t) return;
      const id = `local-${++localSeq}`;
      const chip = state.replyTo[bot] ?? null;
      const reply = chip ? { source: chip.source, label: chip.place } : undefined;
      const wire = toWire(t, skillNames.get(bot) ?? []);
      dispatch({ type: "local.user", bot, id, text: t, now: now(), reply, sent: wire });
      if (chip) dispatch({ type: "reply.set", bot, chip: null });
      try {
        await bridge.request("chat.send", chip ? { bot, text: wire, reply_to: chip.session_id } : { bot, text: wire });
      } catch (e) {
        dispatch({ type: "send.failed", bot, id, error: errText(e) });
      }
    },
    setReplyTo(chip, bot) {
      const b = botArg(bot);
      if (b) dispatch({ type: "reply.set", bot: b, chip });
    },
    async sendWithFiles(text, files) {
      const bot = state.selectedBot;
      if (!bot) return;
      if (!files.length) return actions.send(text);
      const results: AttachResult[] = [];
      for (const f of files) {
        try {
          results.push(await bridge.request("chat.attach", { bot, kind: f.attach, name: f.name, data_base64: await f.read() }));
        } catch (e) {
          throw new Error(tr("att.failed", { name: f.name, error: errText(e) }));
        }
      }
      const sent = toWire(promptText(text, results), skillNames.get(bot) ?? []);
      const id = `local-${++localSeq}`;
      const shown: SentFile[] = files.map(({ name, size, kind, url }) => ({ name, size, kind, url }));
      dispatch({ type: "local.user", bot, id, text: text.trim(), now: now(), files: shown, sent });
      try {
        await bridge.request("chat.send", { bot, text: sent });
      } catch (e) {
        dispatch({ type: "send.failed", bot, id, error: errText(e) });
      }
    },
    async interrupt() {
      const bot = state.selectedBot;
      if (!bot) return;
      try {
        await bridge.request("chat.interrupt", { bot });
      } catch (e) {
        fail(e);
      }
    },
    async respondApproval(requestId, choice, bot) {
      const b = botArg(bot);
      if (!b) return;
      try {
        const route = chatRoute(b);
        if (route) await route.approve(requestId, choice);
        else if (isSessionChat(b)) throw new Error(tr("ask.sessionEnded"));
        else await bridge.request("approval.respond", { bot: b, request_id: requestId, choice });
        dispatch({ type: "approval.resolved", bot: b, request_id: requestId, choice });
      } catch (e) {
        fail(e);
      }
    },
    async respondClarify(requestId, answer, bot) {
      const b = botArg(bot);
      if (!b) return;
      try {
        const route = chatRoute(b);
        const say = (x: string | ClarifyAnswers) =>
          route
            ? route.clarify(requestId, x)
            : isSessionChat(b)
              ? Promise.reject(new Error(tr("ask.sessionEnded")))
              : bridge.request("clarify.respond", typeof x === "string" ? { bot: b, request_id: requestId, answer: x } : { bot: b, request_id: requestId, answers: x });
        await say(answer);
        if (typeof answer === "string") {
          dispatch({ type: "clarify.resolved", bot: b, request_id: requestId, answer });
          return;
        }
        const given = Object.values(answer).filter((v) => v !== null).length;
        const total = Object.keys(answer).length;
        const summary = `${given} of ${total}`;
        dispatch({ type: "clarify.resolved", bot: b, request_id: requestId, answer: summary, answers: answer });
      } catch (e) {
        fail(e);
      }
    },
    loadElsewhere,
    loadRoutines,
    loadAutomations,
    loadModels,
    openAutomations: (job) => {
      dispatch({ type: "ui.automations", job });
      void loadAutomations();
    },
    openPlugins: (bot) => dispatch({ type: "ui.plugins", bot: bot ?? state.ui.pluginsBot ?? state.selectedBot ?? state.bots[0]?.name ?? null }),
    async sendTo(bot, text) {
      if (!text.trim()) return;
      if (state.selectedBot !== bot || state.ui.view !== "chat") await selectBot(bot);
      await actions.send(text);
    },
    async automationDo(bot, job, action) {
      await bridge.request(`automations.${action}` as "automations.pause", { bot, job });
      await loadAutomations();
    },
    async addAutomation(p) {
      const r = await bridge.request("automations.add", p);
      await loadAutomations();
      return r;
    },
    pluginsList: async (bot) => (await bridge.request("plugins.list", { bot })).plugins,
    pluginsCatalog: (bot, query, category) =>
      bridge.request("plugins.catalog", { bot, ...(query ? { query } : {}), ...(category ? { category } : {}) }),
    pluginsInspect: (bot, catalogName) => bridge.request("plugins.inspect", { bot, catalog_name: catalogName }),
    pluginsInstall: (bot, catalogName, sha) => bridge.request("plugins.install", { bot, catalog_name: catalogName, inspected_sha: sha }),
    pluginsToggle: (bot, key, enable) => bridge.request("plugins.toggle", { bot, key, enable }),
    pluginsUpdate: (bot, name) => bridge.request("plugins.update", { bot, name }),
    async pluginsRemove(bot, name) {
      await bridge.request("plugins.remove", { bot, name });
    },
    setLanguage(lang) {
      try {
        if (typeof localStorage !== "undefined") localStorage.setItem(LANG_KEY, lang);
      } catch {
        /* no storage */
      }
      setLang(lang);
      dispatch({ type: "ui.lang", lang });
    },
    async peek(sessionId, limit, bot) {
      const b =
        bot ?? Object.keys(state.elsewhere).find((n) => state.elsewhere[n].some((a) => a.id === sessionId)) ?? state.selectedBot;
      if (!b) return;
      dispatch({ type: "peek.loading", id: sessionId });
      try {
        const r = await bridge.request("elsewhere.peek", { bot: b, session_id: sessionId, ...(limit ? { limit } : {}) });
        dispatch({ type: "peek.loaded", id: sessionId, messages: r.messages, total: r.total });
      } catch (e) {
        dispatch({ type: "peek.failed", id: sessionId, error: errText(e) });
      }
    },
    async setModel(change) {
      const bot = state.selectedBot;
      if (!bot) return;
      try {
        const current = await bridge.request("chat.set_model", { bot, ...change });
        dispatch({ type: "model.set", bot, current });
      } catch (e) {
        fail(e);
      }
    },
    togglePanel: (open) => dispatch({ type: "ui.panel", open }),
    setPanelTab: (tab) => dispatch({ type: "ui.panelTab", tab }),
    openRun: (run) => dispatch({ type: "ui.run", run }),
    setRunsFull: (open) => dispatch({ type: "ui.runsFull", open }),
    prefill(text) {
      const bot = state.selectedBot;
      if (!bot) return;
      if (state.ui.view !== "chat") dispatch({ type: "ui.closeSettings" });
      dispatch({ type: "ui.draft", bot, text });
    },
    setTheme(theme) {
      try {
        if (typeof localStorage !== "undefined") localStorage.setItem("omher.theme", theme);
      } catch {
        /* no storage */
      }
      dispatch({ type: "ui.theme", theme });
    },
    setLook(look) {
      dispatch({ type: "ui.look", look });
      try {
        if (typeof localStorage !== "undefined") localStorage.setItem("omher.look", JSON.stringify(state.ui.look));
      } catch {
        /* no storage */
      }
    },
    openSettings: (page) => dispatch({ type: "ui.settings", page }),
    closeSettings: () => dispatch({ type: "ui.closeSettings" }),
    pinBot(bot, on) {
      dispatch({ type: "ui.pin", bot, on });
      saveList("omher.pinned", state.ui.pinned);
    },
    hideBot(bot, on) {
      dispatch({ type: "ui.hide", bot, on });
      saveList("omher.hidden", state.ui.hidden);
    },
    async jumpToAsk(bot, id) {
      dispatch({ type: "ui.focusAsk", bot, id });
      // a SESSIONS chat's ask opens that session; a bot's opens the bot's chat
      const route = isSessionChat(bot) ? chatRoute(bot) : undefined;
      if (route) route.open();
      else if (state.selectedBot !== bot || state.ui.view !== "chat") await selectBot(bot);
    },
    openSession: (id) => dispatch({ type: "ui.session", id }),
    folderOpen: (bot, cwd) => bridge.request("folder.open", { bot, cwd }),
    async folderClose(bot, session) {
      await bridge.request("folder.close", { bot, session });
    },
    folderSetModel: (bot, session, change) => bridge.request("chat.set_model", { bot, session, ...change }),
    async folderSend(bot, session, text) {
      await bridge.request("chat.send", { bot, session, text });
    },
    async folderInterrupt(bot, session) {
      await bridge.request("chat.interrupt", { bot, session });
    },
    async folderApprove(bot, session, requestId, choice) {
      await bridge.request("approval.respond", { bot, session, request_id: requestId, choice });
    },
    async folderClarify(bot, session, requestId, answer) {
      await bridge.request(
        "clarify.respond",
        typeof answer === "string" ? { bot, session, request_id: requestId, answer } : { bot, session, request_id: requestId, answers: answer },
      );
    },
    reloadBots,
    async renameBot(bot, name) {
      const r = await bridge.request("bots.rename", { bot, name });
      dispatch({ type: "bots", bots: state.bots.map((b) => (b.name === bot ? { ...b, display_name: r.display_name } : b)) });
    },
    async setAvatar(bot, data) {
      const r = await bridge.request("bots.set_avatar", data === null ? { bot, clear: true } : { bot, data });
      dispatch({ type: "bots", bots: state.bots.map((b) => (b.name === bot ? { ...b, avatar_rev: r.avatar_rev } : b)) });
    },
    botInfo: (bot) => bridge.request("bots.info", { bot }),
    skills(bot) {
      let list = skillLists.get(bot);
      if (!list) {
        list = bridge
          .request("skills.list", { bot })
          .then((r) => {
            skillNames.set(bot, r.skills.map((x) => x.name));
            return r.skills;
          })
          .catch(() => {
            skillLists.delete(bot); // an older bridge without the op, or a failed read: no picker, no toast
            return [];
          });
        skillLists.set(bot, list);
      }
      return list;
    },
    linkPlaces: (bot) =>
      bridge
        .request("links.places", { bot })
        .then((r) => r.places)
        .catch(() => ({ slack: {}, discord: {} })), // an older bridge without the op: chips keep their fallback
    avatarOf: (bot) => bridge.request("bots.avatar", { bot }),
    panelTerminal: (bot) => bridge.request("panel.terminal", { bot }),
    panelWorktrees: (bot) => bridge.request("panel.worktrees", { bot }),
    panelDiff: (bot, path) => bridge.request("panel.diff", { bot, path }),
    readMedia: (bot, path, info) => bridge.request("media.read", info ? { bot, path, info } : { bot, path }),
    runsList: (bot) => bridge.request("runs.list", { bot }),
    runsGet: (bot, run) => bridge.request("runs.get", { bot, run }),
    runsPrs: (bot, run) => bridge.request("runs.prs", { bot, run }),
    runsCli: (params = {}) => bridge.request("runs.cli", params),
    cliTitle: (agent, session, cwd) => bridge.request("cli.title", { agent, session, ...(cwd ? { cwd } : {}) }),
    usage: () => bridge.request("usage.read", {}),
    accounts: () => bridge.request("accounts.list", {}),
    addAccount: (cli, label) => bridge.request("accounts.add", { cli, label }),
    async setActiveAccount(cli, id) {
      await bridge.request("accounts.set_active", { cli, account: id });
    },
    async removeAccount(cli, id) {
      await bridge.request("accounts.remove", { cli, account: id });
    },
    async labelAccount(cli, id, label) {
      await bridge.request("accounts.label", { cli, account: id, label });
    },
    async discardAccount(cli, id) {
      await bridge.request("accounts.discard", { cli, account: id });
    },
    systemNote(text, bot) {
      const b = bot ?? state.selectedBot ?? state.bots[0]?.name;
      if (b) dispatch({ type: "system.note", bot: b, text, now: now() });
    },
    onBridgeEvent(fn) {
      eventFns.add(fn);
      return () => eventFns.delete(fn);
    },
  };

  return {
    resumed,
    getState: () => state,
    getSnapshot: () => (snapshot ??= { ...state, ...actions }),
    subscribe(fn) {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
    dispatch,
    actions,
  };
}

// ---- app singleton + hook -------------------------------------------------------------------

/** "Notify me" (Settings > General). On unless turned off; saved on this computer. */
export function notifyEnabled(): boolean {
  try {
    return typeof localStorage === "undefined" || localStorage.getItem("omher.notify") !== "off";
  } catch {
    return true;
  }
}

export function setNotifyEnabled(on: boolean): void {
  try {
    localStorage.setItem("omher.notify", on ? "on" : "off");
  } catch {
    /* no storage */
  }
}

let singleton: Store | null = null;
export function getStore(): Store {
  return (singleton ??= createStore(new BridgeClient(), {
    onEvent(ev, state) {
      notifySessionEvent(ev, state);
    },
    onAction: (a, state) => soundOf(a, state, appSounds()),
    onSettled: () => appSounds().settle(),
    resume: () => {
      try {
        return parseResume(typeof localStorage !== "undefined" ? localStorage.getItem(RESUME_KEY) : null);
      } catch {
        return null;
      }
    },
  }));
}

/** True while the person sees chat `key`: the window has focus and shows that bot's chat or that session. */
function watchingChat(state: AppState, key: string): boolean {
  if (!windowWatched()) return false;
  if (isSessionChat(key)) return state.ui.view === "session" && sessionKeyOf?.(state.ui.session) === key;
  return state.ui.view === "chat" && state.selectedBot === key;
}

/** Sounds: your own send (any chat), and a bot's or SESSIONS chat's events. A chat's (re)load and a dropped
 *  connection tell the board which asks are replays. */
export function soundOf(a: Action, state: AppState, board: SoundBoard): void {
  if (a.type === "local.user") board.offer("send");
  else if (a.type === "chat.opened") board.opened(a.bot);
  else if (a.type === "conn" && a.status !== "open") board.unsettle();
  else if (a.type === "event") {
    const ev = a.ev.session ? { ...a.ev, bot: folderKey(a.ev.bot, a.ev.session) } : a.ev;
    const s = soundFor(ev, {
      watching: (key) => watchingChat(state, key),
      open: (key, id) => selectAsks(state).some((x) => x.bot === key && x.item.request_id === id),
    });
    if (s) board.offer(s.sound, s.ask ? { chat: ev.bot, id: s.ask } : undefined);
  }
}

/** A system notification for a chat event, unless the person is looking at that chat. SESSIONS chats
 *  (`fold:` / `agent:` keys) name themselves through their route and open their own view. */
export function notifySessionEvent(ev: BridgeEvent, state: AppState): void {
  if (!notifyEnabled()) return;
  const watching = (bot: string) => watchingChat(state, bot);
  const name = (bot: string) => chatRoute(bot)?.label ?? state.bots.find((b) => b.name === bot)?.display_name ?? bot;
  const note = noteFor(ev, { name, watching });
  if (note) void showNote(note, () => {
    const route = chatRoute(note.bot);
    if (route) route.open();
    else void singleton?.actions.selectBot(note.bot);
  });
}

/** Set by SESSIONS: the chat key shown for a session id (so its own notifications stay quiet). */
let sessionKeyOf: ((id: string | null) => string | null) | null = null;
export function setSessionKeyLookup(fn: (id: string | null) => string | null): void {
  sessionKeyOf = fn;
}

/** The whole view model plus actions. Re-renders on any state change. */
export function useStore(): AppState & Actions {
  const s = getStore();
  return useSyncExternalStore(s.subscribe, s.getSnapshot, s.getSnapshot);
}
