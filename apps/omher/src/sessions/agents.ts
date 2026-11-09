// The agent programs a session can run, and the pure helpers the sidebar and the session views share.
// The list is fixed and mirrors `AGENTS` in src-tauri/src/sessions.rs (the shell refuses anything else).
// `mode` says how a new session opens: `chat` = the agent's structured mode shown as an omher chat,
// `hermes` = a Hermes chat in the folder (oh-my-hermes, through the bridge), `terminal` = its own TUI.

export type AgentId = "claude" | "codex" | "omh" | "pi" | "omp" | "grok";

export type AgentMode = "chat" | "hermes" | "terminal";

export interface AgentDef {
  id: AgentId;
  /** What the person types in a terminal to start it. */
  program: string;
  label: string;
  mode: AgentMode;
}

export const AGENTS: readonly AgentDef[] = [
  { id: "claude", program: "claude", label: "Claude Code", mode: "chat" },
  { id: "codex", program: "codex", label: "Codex", mode: "chat" },
  { id: "omh", program: "omh", label: "oh-my-hermes", mode: "hermes" },
  { id: "pi", program: "pi", label: "pi", mode: "chat" },
  { id: "omp", program: "omp", label: "oh-my-pi", mode: "chat" },
  { id: "grok", program: "grok", label: "Grok", mode: "terminal" },
];

/** Tooltip on the session header's Terminal toggle: whether the terminal view continues the same
 *  conversation or starts the agent's own terminal UI fresh. */
export function terminalNote(agent: AgentId): string {
  if (agent === "claude") return "Terminal view: Claude Code's own terminal, continuing this conversation (--resume). Back to chat continues it too.";
  if (agent === "omh") return "Terminal view: starts oh-my-hermes in a new terminal; this chat stays as it is.";
  return `Terminal view: starts ${agentDef(agent).label} fresh in its own terminal; this chat stays as it is.`;
}

export const isAgentId = (v: unknown): v is AgentId => typeof v === "string" && AGENTS.some((a) => a.id === v);

export const agentDef = (id: AgentId): AgentDef => AGENTS.find((a) => a.id === id)!;

/** One allow-listed agent as found on this computer (`path: null` = not installed). */
export interface AgentInfo {
  id: AgentId;
  label: string;
  /** Missing from older shells: the UI list's mode then applies. */
  mode?: AgentMode;
  path: string | null;
}

/** The last folder segment of a macOS/Linux or Windows path: `/a/b/` -> `b`, `C:\\x\\y` -> `y`, `/` -> `/`. */
export function folderName(path: string): string {
  const trimmed = path.replace(/[\\/]+$/, "");
  if (!trimmed) return path ? "/" : "";
  if (/^[A-Za-z]:$/.test(trimmed)) return `${trimmed}\\`;
  const parts = trimmed.split(/[\\/]/);
  return parts[parts.length - 1] || trimmed;
}

/** The folder that holds `path`: `~/code/x` -> `~/code`, `/x` -> `/`. */
export function parentPath(path: string): string {
  const trimmed = path.replace(/[\\/]+$/, "");
  const i = Math.max(trimmed.lastIndexOf("/"), trimmed.lastIndexOf("\\"));
  if (i < 0) return "";
  return i === 0 ? trimmed[0] : trimmed.slice(0, i);
}

/** `/Users/k/code/x` -> `~/code/x` when it is under `home`. */
export function tildePath(path: string, home: string | null): string {
  if (!home) return path;
  const h = home.replace(/[\\/]+$/, "");
  if (h && (path === h || path.startsWith(`${h}/`) || path.startsWith(`${h}\\`))) return `~${path.slice(h.length)}`;
  return path;
}

export type SessionStatus = "starting" | "running" | "exited" | "failed";

export interface SessionRec {
  id: string;
  agent: AgentId;
  cwd: string;
  /** ms since epoch */
  startedAt: number;
  status: SessionStatus;
  /** exit code when exited; null after a signal (closed, killed) */
  exitCode?: number | null;
  error?: string;
  /** What the main column shows: the chat or the terminal. */
  view: "chat" | "terminal";
  /** The chat's own session id (Claude Code session, Codex thread, pi session), when the agent said. */
  agentSession?: string;
  /** The chat's model, when known. */
  model?: string;
  /** Hermes profile a folder chat (oh-my-hermes) runs on. */
  bot?: string;
}

/** Live state of a session's chat that the row needs (from the store). */
export interface ChatLive {
  /** a turn is running */
  turn: boolean;
  /** an approval or question waits for the person */
  needsYou: boolean;
}

/** What one sidebar row shows. */
export function rowModel(s: SessionRec, chat?: ChatLive): { title: string; sub: string; live: boolean; needsYou: boolean; ts: number } {
  const label = agentDef(s.agent).label;
  const alive = s.status === "running" || s.status === "starting";
  const needsYou = alive && !!chat?.needsYou;
  // While running the live dot says it, so the line is just the agent.
  const state = needsYou
    ? "Needs you"
    : s.status === "running"
      ? ""
      : s.status === "starting"
        ? "Starting…"
        : s.status === "failed"
          ? "Could not start"
          : s.exitCode === 0 || s.exitCode === null || s.exitCode === undefined
            ? "Ended"
            : `Ended · exit ${s.exitCode}`;
  // A chat is live while a turn runs; a terminal while its program runs.
  const live = s.view === "chat" && chat ? alive && chat.turn : alive;
  return {
    title: folderName(s.cwd),
    sub: state ? `${label} · ${state}` : label,
    live,
    needsYou,
    ts: s.startedAt / 1000,
  };
}

// ---- recent launches (this computer only) ---------------------------------------------------

export interface Recent {
  agent: AgentId;
  cwd: string;
  /** ms since epoch */
  at: number;
}

export const RECENT_KEY = "omher.sessions.recent";
export const RECENT_MAX = 4;

/** Saved recents, defensively: anything malformed is dropped. */
export function parseRecent(raw: string | null): Recent[] {
  try {
    const v = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(v)) return [];
    return v
      .filter((r) => r && isAgentId(r.agent) && typeof r.cwd === "string" && r.cwd && typeof r.at === "number")
      .slice(0, RECENT_MAX)
      .map((r) => ({ agent: r.agent, cwd: r.cwd, at: r.at }));
  } catch {
    return [];
  }
}

/** `next` first, the same agent+folder only once, at most RECENT_MAX. */
export function pushRecent(list: Recent[], next: Recent): Recent[] {
  return [next, ...list.filter((r) => !(r.agent === next.agent && r.cwd === next.cwd))].slice(0, RECENT_MAX);
}
