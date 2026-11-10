// Pick up where the person left off after omher restarts (an update, a quit and reopen, a crash): one snapshot
// under `omher.resume` in this computer's storage, with a version and a time. It holds the selected bot or
// session, the right panel, the Plans full view, the composers' unsent text, and the SESSIONS list (agent,
// folder, account, view, the agent's own conversation id, whether it was running, and the last messages of its
// chat, which omher draws itself). These functions are pure; resumeBoot.ts reads, writes and applies them.
import type { PanelTabId } from "../state/store";
import { isAgentId, type AgentId } from "../sessions/agents";

export const RESUME_KEY = "omher.resume";
export const RESUME_VERSION = 1;

const PANEL_TABS: readonly PanelTabId[] = ["details", "terminal", "schedule", "worktrees", "diff", "runs"];
const MAX_SESSIONS = 20;
const MAX_MESSAGES = 40;
const MAX_TEXT = 4_000;
const MAX_DRAFT = 20_000;
const SESSION_ID = /^s\d{1,9}$/;

export interface SavedMsg {
  id: string;
  role: "user" | "assistant";
  text: string;
  ts: number;
}

export interface SavedSession {
  id: string;
  agent: AgentId;
  cwd: string;
  startedAt: number;
  view: "chat" | "terminal";
  /** Its program ran (or was starting) when omher closed. */
  running: boolean;
  /** A New session chat that never started: it comes back as a draft and is never started by the restart. */
  draft?: boolean;
  /** Ended ones: how. */
  failed?: boolean;
  exitCode?: number | null;
  error?: string;
  /** The agent's own conversation id (Claude Code session, Codex thread). */
  agentSession?: string;
  /** The Settings › Accounts login it ran as. */
  account?: string;
  /** oh-my-hermes: the bot it ran on. */
  bot?: string;
  model?: string;
  /** Its name: the person's (Rename), the agent's own title, a summary of the first message (SessionRec). */
  title?: string;
  agentTitle?: string;
  promptTitle?: string;
  /** The chat's last messages, text only. */
  messages?: SavedMsg[];
}

export interface ResumeSnap {
  v: typeof RESUME_VERSION;
  /** ms since epoch */
  at: number;
  bot: string | null;
  view: "chat" | "session";
  session: string | null;
  panelOpen: boolean;
  panelTab: PanelTabId;
  runsFull: boolean;
  runId: string | null;
  /** Unsent composer text by chat key (a bot's name, or a session chat's `agent:<id>`). */
  drafts: Record<string, string>;
  sessions: SavedSession[];
}

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const str = (v: unknown, max = 4096): string | undefined => (typeof v === "string" && v && v.length <= max ? v : undefined);
const cut = (s: string, max: number) => (s.length > max ? s.slice(0, max) : s);

function parseMsg(v: unknown): SavedMsg | null {
  if (!isObj(v)) return null;
  const id = str(v.id, 200);
  if (!id || (v.role !== "user" && v.role !== "assistant") || typeof v.text !== "string" || typeof v.ts !== "number") return null;
  return { id, role: v.role, text: cut(v.text, MAX_TEXT), ts: v.ts };
}

function parseSession(v: unknown): SavedSession | null {
  if (!isObj(v)) return null;
  const id = str(v.id, 12);
  const cwd = str(v.cwd);
  if (!id || !SESSION_ID.test(id) || !isAgentId(v.agent) || !cwd || typeof v.startedAt !== "number") return null;
  const out: SavedSession = {
    id,
    agent: v.agent,
    cwd,
    startedAt: v.startedAt,
    view: v.view === "terminal" ? "terminal" : "chat",
    running: v.running === true,
  };
  if (v.failed === true) out.failed = true;
  if (v.draft === true) {
    out.draft = true;
    out.running = false;
  }
  if (typeof v.exitCode === "number" || v.exitCode === null) out.exitCode = v.exitCode;
  const error = str(v.error, MAX_TEXT);
  if (error) out.error = error;
  for (const k of ["agentSession", "account", "bot", "model", "title", "agentTitle", "promptTitle"] as const) {
    const s = str(v[k], 200);
    if (s) out[k] = s;
  }
  if (Array.isArray(v.messages)) {
    const msgs = v.messages.map(parseMsg).filter((m): m is SavedMsg => !!m).slice(-MAX_MESSAGES);
    if (msgs.length) out.messages = msgs;
  }
  return out;
}

/** The saved snapshot, or null when there is none, it is malformed, or it is from another version. */
export function parseResume(raw: string | null | undefined): ResumeSnap | null {
  if (!raw) return null;
  let v: unknown;
  try {
    v = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!isObj(v) || v.v !== RESUME_VERSION || typeof v.at !== "number" || !Number.isFinite(v.at)) return null;
  if (v.bot !== null && typeof v.bot !== "string") return null;
  if (!Array.isArray(v.sessions) || !isObj(v.drafts)) return null;
  const sessions: SavedSession[] = [];
  for (const s of v.sessions.map(parseSession)) if (s && !sessions.some((x) => x.id === s.id)) sessions.push(s);
  const drafts: Record<string, string> = {};
  for (const [k, d] of Object.entries(v.drafts)) if (k && typeof d === "string" && d) drafts[k] = cut(d, MAX_DRAFT);
  const session = typeof v.session === "string" && sessions.some((s) => s.id === v.session) ? v.session : null;
  return {
    v: RESUME_VERSION,
    at: v.at,
    bot: v.bot || null,
    view: v.view === "session" && session ? "session" : "chat",
    session,
    panelOpen: v.panelOpen === true,
    panelTab: PANEL_TABS.includes(v.panelTab as PanelTabId) ? (v.panelTab as PanelTabId) : "details",
    runsFull: v.runsFull === true,
    runId: typeof v.runId === "string" && v.runId ? v.runId : null,
    drafts,
    sessions: sessions.slice(0, MAX_SESSIONS),
  };
}

/** What the store restores once the bot list is known: a bot that is gone takes its panel, Plans view and
 *  draft with it (the app then opens the first bot as on a fresh start). */
export function forBots(snap: ResumeSnap, bots: readonly string[]): ResumeSnap {
  const known = !!snap.bot && bots.includes(snap.bot);
  const sessionKeys = new Set(snap.sessions.map((s) => `agent:${s.id}`));
  const drafts = Object.fromEntries(Object.entries(snap.drafts).filter(([k]) => bots.includes(k) || sessionKeys.has(k)));
  return known
    ? { ...snap, drafts }
    : { ...snap, bot: null, panelOpen: false, runsFull: false, runId: null, drafts };
}

/** What the snapshot is built from (resumeBoot.ts reads the app store, SESSIONS and the drafts). */
export interface ResumeInput {
  bot: string | null;
  bots: readonly string[];
  view: "chat" | "settings" | "session";
  session: string | null;
  panelOpen: boolean;
  panelTab: PanelTabId;
  runsFull: boolean;
  runId: string | null;
  drafts: Record<string, string>;
  sessions: Omit<SavedSession, "messages">[];
  /** A session chat's messages by session id. */
  messages: (id: string) => SavedMsg[] | undefined;
}

export function buildResume(i: ResumeInput, now: number): ResumeSnap {
  const sessions: SavedSession[] = i.sessions.slice(0, MAX_SESSIONS).map((s) => {
    const msgs = i
      .messages(s.id)
      ?.filter((m) => m.text)
      .slice(-MAX_MESSAGES)
      .map((m) => ({ id: m.id, role: m.role, text: cut(m.text, MAX_TEXT), ts: m.ts }));
    return msgs?.length ? { ...s, messages: msgs } : { ...s };
  });
  const ids = new Set(sessions.map((s) => s.id));
  const session = i.view === "session" && i.session && ids.has(i.session) ? i.session : null;
  const keep = (k: string) => i.bots.includes(k) || (k.startsWith("agent:") && ids.has(k.slice(6)));
  return {
    v: RESUME_VERSION,
    at: now,
    bot: i.bot,
    // Settings is a place you pass through: a restart opens the chat (or session) behind it
    view: session ? "session" : "chat",
    session,
    panelOpen: i.panelOpen,
    panelTab: i.panelTab,
    runsFull: i.runsFull,
    runId: i.runId,
    drafts: Object.fromEntries(Object.entries(i.drafts).filter(([k, d]) => d && keep(k)).map(([k, d]) => [k, cut(d, MAX_DRAFT)])),
    sessions,
  };
}

/** Claude Code and Codex chats continue their own conversation by themselves; anything else waits for Resume. */
export const continuesItself = (s: Pick<SavedSession, "agent" | "view" | "agentSession">): boolean =>
  (s.agent === "claude" || s.agent === "codex") && !!s.agentSession;
