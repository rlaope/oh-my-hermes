import { pickTitle, type TitleSource } from "./titles";
import { t } from "../i18n";

// The agent programs a session can run, and the pure helpers the sidebar and the session views share.
// The list is fixed and mirrors `AGENTS` in src-tauri/src/sessions.rs (the shell refuses anything else).
// `mode` says how a new session opens: `chat` = the agent's structured mode shown as an omher chat,
// `hermes` = a Hermes chat in the folder (oh-my-hermes, through the bridge), `terminal` = its own TUI.

export type AgentId = "claude" | "codex" | "omo" | "dsh" | "omh" | "pi" | "omp" | "grok" | "opencode" | "kilo" | "gemini" | "qwen" | "kimi" | "copilot" | "cline";

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
  { id: "omo", program: "omo", label: "OmO", mode: "chat" },
  { id: "dsh", program: "dsh", label: "DSH", mode: "chat" },
  { id: "omh", program: "omh", label: "oh-my-hermes", mode: "hermes" },
  { id: "pi", program: "pi", label: "pi", mode: "chat" },
  { id: "omp", program: "omp", label: "oh-my-pi", mode: "chat" },
  { id: "grok", program: "grok", label: "Grok", mode: "terminal" },
  { id: "opencode", program: "opencode", label: "OpenCode", mode: "chat" },
  { id: "kilo", program: "kilo", label: "Kilo Code", mode: "chat" },
  { id: "gemini", program: "gemini", label: "Gemini CLI", mode: "chat" },
  { id: "qwen", program: "qwen", label: "Qwen Code", mode: "chat" },
  { id: "kimi", program: "kimi", label: "Kimi Code", mode: "chat" },
  { id: "copilot", program: "copilot", label: "Copilot CLI", mode: "chat" },
  { id: "cline", program: "cline", label: "Cline", mode: "chat" },
];

/** Tooltip on the session header's Terminal toggle: whether the terminal view continues the same
 *  conversation or starts the agent's own terminal UI fresh. */
export function terminalNote(agent: AgentId): string {
  if (agent === "claude") return t("ss.termClaude");
  if (agent === "omh") return t("ss.termOmh");
  return t("ss.termFresh", { agent: agentDef(agent).label });
}

/** The install line for an agent's CLI, shown as text in the new-session menu's "Not installed" tooltip (omher
 *  never runs it), each as that product's own docs give it: pi's npm package moved to @earendil-works (its README's
 *  npm line), oh-my-pi's npm build needs Bun so its line is the installer from its README, Grok's is the one-line
 *  installer from docs.x.ai; the six Agent Client Protocol agents (Kilo Code, Gemini CLI, Qwen Code, Kimi Code, Copilot CLI,
 *  Cline) take the npm line of their own READMEs. Codex also notes that the copy inside the ChatGPT (or Codex) desktop app on macOS is
 *  detected. The lines of the agents with an install layout are repeated in `LAYOUTS` (src-tauri/src/sessions.rs),
 *  which names them when the program found does not look like the agent; a Rust test keeps the two the same. */
export const INSTALL: Record<AgentId, string> = {
  claude: "npm i -g @anthropic-ai/claude-code",
  codex: "npm i -g @openai/codex",
  omo: "npm i -g omo-ai",
  dsh: "npm i -g @deepseek-ai/dsh",
  omh: "curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | sh",
  pi: "npm i -g --ignore-scripts @earendil-works/pi-coding-agent",
  omp: "curl -fsSL https://omp.sh/install | sh",
  grok: "curl -fsSL https://x.ai/cli/install.sh | bash",
  opencode: "npm install -g opencode-ai",
  kilo: "npm install -g @kilocode/cli",
  gemini: "npm install -g @google/gemini-cli",
  qwen: "npm install -g @qwen-code/qwen-code@latest",
  kimi: "npm install -g @moonshot-ai/kimi-code",
  copilot: "npm install -g @github/copilot",
  cline: "npm install -g cline",
};

/** Tooltip of an agent that is not installed: what is missing, then how to install it. DSH names DeepSeek Harness
 *  (another `dsh` on PATH, such as deepseek-bot's, does not count) and its desktop app, which carries the CLI. */
export function missingNote(agent: AgentId): string {
  const install = t("ss.installHow", { cmd: INSTALL[agent] }) + (agent === "codex" ? t("ss.codexBundled") : agent === "dsh" ? t("ss.dshApp") : "");
  return t("ss.missing", { program: agent === "dsh" ? "DeepSeek Harness (dsh)" : agentDef(agent).program, how: install });
}

export const isAgentId = (v: unknown): v is AgentId => typeof v === "string" && AGENTS.some((a) => a.id === v);

/** Agents whose Restart (and Resume) continues the conversation, all of them chats: Claude Code `--resume`, Codex
 *  `thread/resume`, OmO `--session`, DSH `--session-id` (DeepSeek Harness's own session),
 *  OpenCode and the other Agent Client Protocol agents `session/resume` (or `session/load`). pi, oh-my-pi and Grok (a
 *  terminal) start a new one. */
export const CONTINUES: readonly AgentId[] = ["claude", "codex", "omo", "dsh", "opencode", "kilo", "gemini", "qwen", "kimi", "copilot", "cline"];

export const agentDef = (id: AgentId): AgentDef => AGENTS.find((a) => a.id === id)!;

/** Agents whose own Stop, sent with no turn running, stops the work still running in the background: Claude Code's
 *  `interrupt` stops its background subagents and withdraws their asks, and its `stop_task` stops a background
 *  command (claude-13-late-ask-stop, claude-14-background-stop.jsonl). OmO's `abort` with no turn touches none of
 *  the background commands it counts, and Codex, ACP agents and DSH refuse a Stop with no turn and count no
 *  background work, so they get no such Stop. */
export const STOPS_BACKGROUND: readonly AgentId[] = ["claude"];

/** One allow-listed agent as found on this computer (`path: null` = not installed). */
export interface AgentInfo {
  id: AgentId;
  label: string;
  /** Missing from older shells: the UI list's mode then applies. */
  mode?: AgentMode;
  path: string | null;
  /** `hermes`: the oh-my-hermes row of a person who has Hermes but not `omh`. Its session is the same Hermes chat in
   *  the folder, `path` is where Hermes was found, and it has no terminal view (that would start `omh`). */
  via?: "hermes";
}

/** The oh-my-hermes row's name when only Hermes is there (the shell's `HERMES_LABEL`). */
export const HERMES_LABEL = "Hermes";

/** Hermes is there and `omh` is not: the + menu's oh-my-hermes row opens a Hermes chat named "Hermes", and the app
 *  offers to add oh-my-hermes. False until the look-up answers. */
export function hermesOnly(agents: AgentInfo[] | null | undefined): boolean {
  return !!agents?.some((a) => a.id === "omh" && a.via === "hermes" && !!a.path);
}

/** How an agent is named on this computer: "Hermes" for the oh-my-hermes row of a person without `omh`. */
export function agentLabel(id: AgentId, agents: AgentInfo[] | null | undefined): string {
  return id === "omh" && hermesOnly(agents) ? HERMES_LABEL : agentDef(id).label;
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

/** How a session opens: as omher's chat, or as the agent's own terminal. The person picks it in a New session. */
export type OpenAs = "chat" | "terminal";

/** What the person picked per agent last time (`omher.sessions.open`). */
export type Opens = Partial<Record<AgentId, OpenAs>>;

export const OPEN_KEY = "omher.sessions.open";

/** Saved picks, defensively: anything malformed is dropped. */
export function parseOpens(raw: string | null): Opens {
  try {
    const v = raw ? JSON.parse(raw) : {};
    if (!v || typeof v !== "object" || Array.isArray(v)) return {};
    const out: Opens = {};
    for (const [k, w] of Object.entries(v)) if (isAgentId(k) && (w === "chat" || w === "terminal")) out[k] = w;
    return out;
  } catch {
    return {};
  }
}

/** Which ways `agent` can open: omher's chat and/or its own terminal. oh-my-hermes has a terminal (`omh`) but, for a
 *  person who has Hermes and no `omh`, only the Hermes chat; DSH has no terminal here; Grok has no chat here. */
export function opensAs(agent: AgentId, agents?: AgentInfo[] | null): Record<OpenAs, boolean> {
  if (agent === "dsh") return { chat: true, terminal: false };
  if (agent === "grok") return { chat: false, terminal: true };
  if (agent === "omh" && hermesOnly(agents)) return { chat: true, terminal: false };
  return { chat: true, terminal: true };
}

/** The way a New session opens: the one remembered for the agent if it still has it, else Chat, else the terminal
 *  (an agent with only one way). */
export function draftOpen(agent: AgentId, agents: AgentInfo[] | null | undefined, remembered?: Opens): OpenAs {
  const has = opensAs(agent, agents);
  const w = remembered?.[agent];
  if (w && has[w]) return w;
  return has.chat ? "chat" : "terminal";
}

/** Whether a session runs as a chat, a Hermes chat or a terminal: a session opened as a terminal is one whatever
 *  its agent usually does; any other is as its agent opens (the shell's list, else this app's). */
export function sessionMode(agents: AgentInfo[] | null | undefined, rec: Pick<SessionRec, "agent" | "open">): AgentMode {
  if (rec.open === "terminal") return "terminal";
  return agents?.find((a) => a.id === rec.agent)?.mode ?? agentDef(rec.agent).mode;
}

/** `draft` = a New session chat whose agent and folder can still change: nothing runs until its first message
 *  (or Start, for an agent that opens in its terminal). */
export type SessionStatus = "draft" | "starting" | "running" | "exited" | "failed";

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
  /** `terminal` = the person opened it as the agent's own terminal (it has no chat, whatever the agent usually
   *  does). None = as the agent opens. */
  open?: OpenAs;
  /** The chat's own session id (Claude Code session, Codex thread, pi session), when the agent said. */
  agentSession?: string;
  /** The chat's model, when known. */
  model?: string;
  /** A model picked while a turn ran: the agent takes it from the next turn on (Claude Code), shown until then. */
  modelNext?: string;
  /** Hermes profile a folder chat (oh-my-hermes) runs on. */
  bot?: string;
  /** The Settings › Accounts login it started with (claude, codex, grok); none = the CLI's own. */
  account?: string;
  /** omher restarted while it ran and it does not continue by itself: it starts again on Resume. */
  paused?: boolean;
  /** The name the person gave it (Rename); none = the automatic one. */
  title?: string;
  /** The title the agent gave its conversation (Claude Code's own title, a Codex thread name). */
  agentTitle?: string;
  /** Work the agent says still runs in the background after its turn (commands; subagents have their own rows). */
  background?: number;
  /** A short summary of the person's first real message, made here (no model is asked). */
  promptTitle?: string;
  /** How the account it started with reads (`as work@…`), when Settings › Accounts picked one other than This
   *  computer: shown under its composer. Display only; `account` is what the shell gets. */
  startedAs?: string;
  /** The permission mode the person picked (controls.ts MODES); set again when the agent starts after a restart.
   *  None = the agent's own. */
  mode?: string;
  /** The reasoning effort the person picked, likewise. */
  effort?: string;
}

/** Live state of a session's chat that the row needs (from the store). */
export interface ChatLive {
  /** a turn is running */
  turn: boolean;
  /** an approval or question waits for the person */
  needsYou: boolean;
  /** its last turn stopped on an error and no turn has run since */
  failed?: boolean;
}

/** What a session did while the person was not looking at it, kept on its row until they open it: its terminal rang
 *  its bell, or it finished (a turn, or the program itself). */
export type Unseen = "bell" | "end";

/** The state a row shows in the time's place, as a sign and a word: it waits for the person, it stopped on an error,
 *  or it finished something the person has not seen. */
export type RowMark = "needs" | "error" | "done";

/** The other rows a row is told apart from: every session's folder, and the home folder for `~`. */
export interface RowContext {
  cwds: string[];
  home: string | null;
  /** The agents found on this computer (names the oh-my-hermes row "Hermes" without `omh`). */
  agents?: AgentInfo[] | null;
}

/** What one sidebar row shows. Line 1 is the session's name ([pickTitle]: the person's, the agent's, a summary of
 *  the first message, else the folder); line 2 is the folder, the agent and its state (`web-app · Claude Code`).
 *  `where` is the parent folder (`~/work`), set only when another session's folder has the same name in a
 *  different place: it follows the folder on line 2 (`web-app · ~/work · Claude Code`), or the name on line 1
 *  while the name still is the folder. */
export function rowModel(
  s: SessionRec,
  chat?: ChatLive,
  ctx?: RowContext,
  unseen?: Unseen,
): {
  title: string;
  titleSource: TitleSource;
  folder: string;
  where?: string;
  sub: string;
  live: boolean;
  needsYou: boolean;
  /** the state the row shows, if any */
  mark: RowMark | null;
  /** nothing runs in it (ended, could not start, or waiting for Resume): the row steps back */
  over: boolean;
  ts: number;
} {
  const label = agentLabel(s.agent, ctx?.agents);
  // a draft: "New session" over the folder it will start in; it has no name yet and nothing runs, so nothing is live
  if (s.status === "draft")
    return {
      title: t("ss.newTitle"),
      titleSource: "folder",
      folder: folderName(s.cwd),
      sub: s.cwd ? tildePath(s.cwd, ctx?.home ?? null) : label,
      live: false,
      needsYou: false,
      mark: null,
      over: false,
      ts: s.startedAt / 1000,
    };
  const alive = s.status === "running" || s.status === "starting";
  const needsYou = alive && !!chat?.needsYou;
  // an error: it could not start, its program ended with an error or a non-zero exit, or its last turn failed
  const failedTurn = s.status === "running" && !!chat?.failed;
  const broke =
    s.status === "failed" || failedTurn || (s.status === "exited" && !s.paused && (!!s.error || (typeof s.exitCode === "number" && s.exitCode !== 0)));
  const mark: RowMark | null = needsYou || (alive && unseen === "bell") ? "needs" : broke ? "error" : unseen === "end" ? "done" : null;
  // While running the ring (chat) or the live dot (terminal) says it, and while it waits on the person "waiting" and
  // the amber dot say it, so the line is just the agent.
  // The state's sign and word (waiting, error, done) stand in the time's place on line 1, so line 2 is as before.
  const state = needsYou
    ? ""
    : s.status === "running"
      ? ""
      : s.paused
        ? t("ss.paused")
        : s.status === "starting"
          ? t("ss.starting")
          : s.status === "failed"
            ? t("ss.couldNotStart")
            : s.exitCode === 0 || s.exitCode === null || s.exitCode === undefined
              ? t("ss.ended")
              : t("ss.endedExit", { code: s.exitCode });
  // A chat is live while a turn runs; a terminal while its program runs.
  const live = s.view === "chat" && chat ? alive && chat.turn : alive;
  const folder = folderName(s.cwd);
  const clash = !!ctx?.cwds.some((c) => c !== s.cwd && folderName(c) === folder);
  const where = clash ? parentPath(tildePath(s.cwd, ctx!.home)) : undefined;
  const { title, source } = pickTitle(s, folder);
  const agent = state ? `${label} · ${state}` : label;
  const place = source === "folder" ? "" : `${folder}${where ? ` · ${where}` : ""} · `;
  return {
    title,
    titleSource: source,
    folder,
    ...(where && source === "folder" ? { where } : {}),
    sub: `${place}${agent}`,
    live,
    needsYou,
    mark,
    over: !alive,
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
export const RECENT_MAX = 5;

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

/** `next` first, each folder only once (whichever agent used it last), at most RECENT_MAX. */
export function pushRecent(list: Recent[], next: Recent): Recent[] {
  return [next, ...list.filter((r) => r.cwd !== next.cwd)].slice(0, RECENT_MAX);
}

/** The folders the new-session menu offers, for any agent: distinct, newest first, at most RECENT_MAX. */
export function recentFolders(list: Recent[]): string[] {
  const out: string[] = [];
  for (const r of [...list].sort((a, b) => b.at - a.at)) if (!out.includes(r.cwd)) out.push(r.cwd);
  return out.slice(0, RECENT_MAX);
}

// ---- a New session chat (draft) ---------------------------------------------------------------

/** The agent a person used last (newest recent), if any. */
export function lastAgent(list: Recent[]): AgentId | null {
  let best: Recent | null = null;
  for (const r of list) if (!best || r.at > best.at) best = r;
  return best ? best.agent : null;
}

/** The SESSIONS + menu's order: the installed agents first, the last one used on top of them, then the rest in
 *  list order; the agents that are not installed after those, in list order. */
export function menuOrder(agents: AgentInfo[], list: Recent[]): AgentInfo[] {
  const last = lastAgent(list);
  const rank = (a: AgentInfo) => (a.path ? (a.id === last ? 0 : 1) : 2);
  const at = (a: AgentInfo) => AGENTS.findIndex((d) => d.id === a.id);
  return agents.filter((a) => isAgentId(a.id)).sort((a, b) => rank(a) - rank(b) || at(a) - at(b));
}

/** The + menu in two parts: the rows it always shows (the installed agents, in [menuOrder]), and the agents that are
 *  not installed, folded behind one "More agents" row that opens them with their install lines. With nothing
 *  installed yet every agent shows, so the menu is never just that one row. */
export function menuParts(agents: AgentInfo[], list: Recent[]): { shown: AgentInfo[]; more: AgentInfo[] } {
  const all = menuOrder(agents, list);
  const shown = all.filter((a) => !!a.path);
  return shown.length ? { shown, more: all.filter((a) => !a.path) } : { shown: all, more: [] };
}

/** The agent a New session chat starts on: the last one used if it is installed, else the first installed (menu
 *  order), else the last one used or Claude Code. Before the look-up (`agents` null) the last one used stands. */
export function draftAgent(list: Recent[], agents: AgentInfo[] | null): AgentId {
  const last = lastAgent(list);
  if (!agents) return last ?? AGENTS[0].id;
  const installed = (id: AgentId) => agents.some((a) => a.id === id && !!a.path);
  if (last && installed(last)) return last;
  const first = AGENTS.find((a) => installed(a.id));
  return first ? first.id : (last ?? AGENTS[0].id);
}

/** The folder a New session chat starts in: the last folder used, else the home folder ("" until it is known). */
export function draftFolder(list: Recent[], home: string | null): string {
  return recentFolders(list)[0] ?? home ?? "";
}

/** The folder chip's menu: the recent folders (newest first), then the home folder unless it is one of them. */
export function folderChoices(list: Recent[], home: string | null): { recent: string[]; home: string | null } {
  const recent = recentFolders(list);
  return { recent, home: home && !recent.includes(home) ? home : null };
}
