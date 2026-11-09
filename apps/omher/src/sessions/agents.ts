// The agent programs a session can run, and the pure helpers the sidebar and the terminal view share.
// The list is fixed and mirrors `AGENTS` in src-tauri/src/sessions.rs (the shell refuses anything else).

export type AgentId = "claude" | "codex" | "omh" | "pi" | "omp" | "grok";

export interface AgentDef {
  id: AgentId;
  /** What the person types in a terminal to start it. */
  program: string;
  label: string;
}

export const AGENTS: readonly AgentDef[] = [
  { id: "claude", program: "claude", label: "Claude Code" },
  { id: "codex", program: "codex", label: "Codex" },
  { id: "omh", program: "omh", label: "oh-my-hermes" },
  { id: "pi", program: "pi", label: "pi" },
  { id: "omp", program: "omp", label: "oh-my-pi" },
  { id: "grok", program: "grok", label: "Grok" },
];

export const isAgentId = (v: unknown): v is AgentId => typeof v === "string" && AGENTS.some((a) => a.id === v);

export const agentDef = (id: AgentId): AgentDef => AGENTS.find((a) => a.id === id)!;

/** One allow-listed agent as found on this computer (`path: null` = not installed). */
export interface AgentInfo {
  id: AgentId;
  label: string;
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
}

/** What one sidebar row shows. */
export function rowModel(s: SessionRec): { title: string; sub: string; live: boolean; ts: number } {
  const label = agentDef(s.agent).label;
  // While running the live dot says it, so the line is just the agent.
  const state =
    s.status === "running"
      ? ""
      : s.status === "starting"
        ? "Starting…"
        : s.status === "failed"
          ? "Could not start"
          : s.exitCode === 0 || s.exitCode === null || s.exitCode === undefined
            ? "Ended"
            : `Ended · exit ${s.exitCode}`;
  return {
    title: folderName(s.cwd),
    sub: state ? `${label} · ${state}` : label,
    live: s.status === "running" || s.status === "starting",
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
