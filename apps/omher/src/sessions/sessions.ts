// SESSIONS: the agent sessions omher started in this run of the app. Each one is an allow-listed agent
// (claude, codex, omo, dsh, omh, pi, omp, grok) in a folder the person picked. Most open as a chat: Claude Code,
// Codex, OmO, pi and oh-my-pi run in their structured mode in the desktop shell (src-tauri/src/agent_chat.rs),
// oh-my-hermes opens a Hermes chat in that folder through the bridge (`folder.open`). Their events land in
// the app store under the session's own chat key, so the bot chat's timeline, activity line, cards and
// composer draw them. DSH (DeepSeek Harness) is a chat too, one headless run per message continuing the harness's
// own session (`--session-id`); it has no terminal view. Grok has no chat mode here, so it stays a terminal (xterm on
// a pseudo-terminal). Every other chat can switch to its agent's terminal view.
//
// SESSIONS + opens a small menu of the agents; picking one opens a New session chat on it at once (a draft), its
// folder in the chip under the composer (the last folder used, else home). Nothing starts until the first message, which becomes the
// agent's first prompt (a terminal agent starts on Start and is sent nothing); then agent and folder are fixed.
// Closing a draft starts nothing.
//
// A session's program lives only while the app runs. The list itself comes back after a restart (resume.ts saves
// it): a Claude Code or Codex chat that was running continues its conversation in the same folder and account,
// the others come back paused with a Resume button, ended ones stay ended, and a draft comes back as a draft
// (never started). The last few folders (with the agent that used each) are remembered on this computer.
//
// Files the person attaches (paste, the + menu, a drop) are saved by the shell under omher's own folder, one per
// session (`~/.omher/session-files/<id>/`, removed when the session is closed). A picture goes to the agent as its
// own image input (Claude Code and OmO / pi inline, Codex by the saved path); any other file is named in the
// message by its saved copy's path. An oh-my-hermes session takes no files: the bridge attaches files to a bot's
// main chat only.
import { useSyncExternalStore } from "react";
import type { ITerminalInitOnlyOptions, ITerminalOptions, Terminal } from "@xterm/xterm";
import type { FitAddon } from "@xterm/addon-fit";
import { afterOpen, bracketedPaste, CELLS_EVENT, feed, isParked, live, onVisible, PARKING_EVENT, type Remake } from "./term/engine";
import { onCwd, onProgress } from "./term/engine-marks";
import { applyLook, termOptions } from "./term/look";
import { termFontsReady } from "./term/fonts";
import { onTermSettings, readTermSettings } from "./term/settings";
import { forgetHistory, pruneHistory, restoredText, trackHistory, watchHistorySetting } from "./term/history";
import { savedPanelKeys } from "../terminal/state";
import { termTheme } from "./term/themes";
import { getShellHost, learnThisHost } from "../terminal/host";
import { onSessionFg } from "./fg";
import { termActs } from "./termActivity";
import { LINK_COPIED_EVENT, newLinkId, termLinkUrl } from "./termLink";
import { acpRow, agentDef, agentLabel, continues, draftAgent, draftFolder, draftOpen, hermesOnly, installLine, isBuiltin, isGone, isShell, isTerminalRec, LAST_LINE_MAX, SHELL, termEnd, termMarkAgent, lastPrintedLine, OPEN_KEY, opensAs, parseOpens, parseRecent, pushRecent, RECENT_KEY, registerAcp, sessionMode, type AgentId, type AgentInfo, type OpenAs, type Unseen, type Opens, type Recent, type SessionRec } from "./agents";
import { NAME_MAX, parseTitles, promptTitle, putTitle, TITLES_KEY } from "./titles";
import { getDraft, setDraft as setUnsent } from "../app/drafts";
import { getHost, type ChatEvent, type ChatInput, type PastChat, type SessionHost } from "./host";
import { localBot } from "../peers/peerKey";
import { folderKey, getStore, notifySessionEvent, notifySessionNote, onBridgeEvent, selectAsks, setChatRoute, setSessionKeyLookup, type OutFile, type SentFile, type Store } from "../state/store";
import { blobType, bytesOf, inlinePicture, parseSentFiles, putSentFiles, SENT_FILES_KEY, shellQuote, wireText, type SavedFile, type SentFilesBook } from "./attach";
import type { AccountCli, AccountGroup, ApprovalChoice, BridgeEvent, ClarifyAnswers, Msg } from "../lib/protocol";
import { continuesItself, type SavedSession } from "../app/resume";
import { accountGroups } from "../settings/accounts/useAccounts";
import { modesOf, steersOf } from "./controls";
import { parseCommands, type AgentCommand } from "../chat/parts/commands";
import { t as tr } from "../i18n";
import { windowWatched, type SessionNote } from "../lib/notify";
import { createCloseGrace, graceMs, restoreSplitIn, type SplitWas } from "./closeGrace";
import { getSplit, groupOf, setSplit } from "./splitState";

/** The Accounts CLI a session of `agent` signs in as (mirrors `session_cli` in src-tauri/src/accounts.rs). */
const ACCOUNT_CLI: Partial<Record<AgentId, AccountCli>> = { claude: "claude", codex: "codex", grok: "grok" };

/** The account a new session of `agent` runs as, from the Accounts list when it is loaded (none = unknown or the
 *  agent has no accounts; the shell then uses the one picked for new sessions). */
export function accountFor(groups: AccountGroup[] | null, agent: AgentId): string | undefined {
  const cli = ACCOUNT_CLI[agent];
  const g = cli ? groups?.find((x) => x.cli === cli) : undefined;
  return g ? (g.active ?? "default") : undefined;
}

export interface ModelOption {
  id: string;
  label: string;
  detail?: string;
  /** Hermes provider slug (oh-my-hermes sessions). */
  provider?: string;
}

export interface SessionsState {
  /** null until the first look-up */
  agents: AgentInfo[] | null;
  home: string | null;
  list: SessionRec[];
  recent: Recent[];
  /** How the person last opened each agent (Chat or Terminal), kept on this computer. */
  opens: Opens;
  /** models a chat session can switch to, by session id */
  models: Record<string, ModelOption[]>;
  /** last problem a chat reported that is not a turn's own error (model refused, …), by session id */
  notes: Record<string, string>;
  /** what each chat's agent reported about itself, by session id */
  live: Record<string, AgentLive>;
  /** what a session did while the person was not looking at it, by session id (gone once they open it) */
  unseen: Record<string, Unseen>;
}

/** What a chat's agent said about its controls (agent_chat.rs events). Nothing here is estimated. */
export interface AgentLive {
  /** the permission mode in force ("" = one omher does not offer, the agent's own) */
  mode?: string;
  /** what the agent itself reported it runs with: its approval policy and sandbox (Codex `never`,
   *  `dangerFullAccess`; Claude Code's permission mode), shown when it means no approvals or full disk access */
  approval?: string;
  sandbox?: string;
  /** the reasoning effort in force */
  effort?: string;
  /** the reasoning levels it takes; none = it has no effort control */
  efforts?: string[];
  /** its own commands and skills, for the `/` menu */
  commands?: AgentCommand[];
  /** context tokens in use and its window, as it counted them */
  usage?: { used: number; max: number };
  /** the git branch of its folder ("" = not a repository) */
  branch?: string;
  /** the agent can take back the person's last message (its own rewind; Claude Code and Codex) */
  rewind?: boolean;
  /** it ended because it is not signed in: the command that signs it in, run by the person in a terminal */
  signin?: string;
}

interface Term {
  /** the terminal now: reading it makes a parked one again (term/park.ts) */
  readonly term: Terminal;
  /** the xterm it has, parked or not */
  raw: Terminal;
  fit: FitAddon;
  /** makes it again after it was parked */
  remake?: Remake;
  /** xterm renders into this element; it moves between session views instead of being re-created */
  el: HTMLDivElement;
  hostId: number | null;
  closed: boolean;
  /** Undoes what the engine attached after the terminal opened (its renderer, add-ons). */
  undo: () => void;
  /** The size the program was last told (when it started, then each resize sent). */
  told: { cols: number; rows: number } | null;
  /** A changed size waiting to be sent (`RESIZE_SETTLE_MS`). */
  settle: ReturnType<typeof setTimeout> | null;
  /** Where its program runs: the agent PTY host, or (a Shell row) the login-shell host of the bottom panel. */
  io: TermIo;
  /** Which program run in this terminal it is (a CLI row goes on as the login shell when its CLI ends): output
   *  drawn after its program was replaced is not acknowledged to the next one. */
  run: number;
  /** The person typed into the current program: a shell that ends before that, with an error, failed at start. */
  typed: boolean;
  /** Its row was closed and waits out the undo window (closeGrace.ts): its program runs on, hidden, and takes no
   *  input (keys, bot prompts, dropped files) until Undo puts the row back. */
  held?: boolean;
}

/** The PTY calls a terminal makes once its program runs. */
type TermIo = Pick<SessionHost, "write" | "ack" | "resize" | "close">;

/** The row's last-output time is written at most this often (a flood would otherwise re-render the sidebar). */
const OUT_MARK_MS = 500;

/** A terminal's new size goes to its program once it has stopped changing for this long. Dragging a window gives
 *  one size per frame (16.7 ms at 60 Hz), so a wait of one frame or less collapses nothing; two frames does, and
 *  the program redraws once for the size the drag ended on instead of once per frame. */
export const RESIZE_SETTLE_MS = 32;

const utf8 = new TextEncoder();

/** A random (version 4) UUID: the id omher gives a new Claude Code conversation in a terminal (`--session-id`). */
export function newConversationId(): string {
  const c = globalThis.crypto;
  if (typeof c?.randomUUID === "function") return c.randomUUID();
  const b = c.getRandomValues(new Uint8Array(16));
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  const h = [...b].map((x) => x.toString(16).padStart(2, "0")).join("");
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

/** TERMINALS agents that continue their own conversation after omher restarts (`claude --resume`, `codex resume`). */
const TERM_CONTINUES: readonly AgentId[] = ["claude", "codex"];
/** When a TERMINALS Codex session first asks for its conversation id, and how often after that until it has one. */
const CODEX_ID_FIRST_MS = 5_000;
const CODEX_ID_EVERY_MS = 15_000;

type Xterm = [typeof import("@xterm/xterm"), typeof import("@xterm/addon-fit")];
let xtermLoad: Promise<Xterm> | null = null;
let xtermMods: Xterm | null = null;
/** xterm (about 88 kB gz) loads when the first session opens, not with the app. */
const loadXterm = () =>
  (xtermLoad ??= Promise.all([import("@xterm/xterm"), import("@xterm/addon-fit"), import("@xterm/xterm/css/xterm.css"), termFontsReady()]).then(
    ([x, f]) => (xtermMods = [x, f]),
  ));

/** A chat's process (agent chat in the shell) or Hermes folder chat (bridge). */
interface ChatProc {
  kind: "agent" | "folder";
  /** shell chat id (agent) */
  hostId?: number;
  /** bridge folder chat id (folder) */
  fid?: string;
  bot?: string;
  /** set when omher itself stopped it (close, Terminal toggle), so its exit is not an end of the session */
  stopping?: boolean;
  /** the program never spoke its chat protocol (an old version, a hung start): the reason its turn and exit carry */
  noChat?: string;
  /** it is not signed in (an Agent Client Protocol agent's `-32000`): omher ends it with `noChat` as the reason */
  signedOut?: boolean;
}

const readRecent = () => {
  try {
    return parseRecent(typeof localStorage !== "undefined" ? localStorage.getItem(RECENT_KEY) : null);
  } catch {
    return [];
  }
};

/** The names the person gave sessions, kept on this computer by the agent's own conversation id. */
/** Files sent in session chats (saved paths), so their bubbles show them again after a restart. */
const readSentFiles = (): SentFilesBook => {
  try {
    return parseSentFiles(typeof localStorage !== "undefined" ? localStorage.getItem(SENT_FILES_KEY) : null);
  } catch {
    return {};
  }
};

const readTitles = () => {
  try {
    return parseTitles(typeof localStorage !== "undefined" ? localStorage.getItem(TITLES_KEY) : null);
  } catch {
    return {};
  }
};
const titleKey = (r: SessionRec) => (r.agentSession ? `${r.agent}:${r.agentSession}` : null);

/** Agents whose own session files carry a conversation title the bridge can read (`cli.title`). */
const TITLED: readonly AgentId[] = ["claude", "codex"];

/** The shell's own words when it will not start OpenCode (`NO_RULES` in acp_chat.rs, kept equal by a test); for Kilo
 *  Code the same sentence names Kilo Code (`no_rules`). */
export const NO_RULES = "OpenCode did not start because omher could not confirm it would keep your own OpenCode permission rules.";

/** The shell's own sentence for an Agent Client Protocol agent that is not signed in (`signed_out` in acp_chat.rs,
 *  the command between backticks; a test keeps the two equal). */
const SIGNED_OUT = /^(.+) is not signed in\. Run `([^`]+)` in a terminal and sign in\.$/;

/** `text` as a person reads it: the shell's not-signed-in sentence is said in their language with the command as
 *  plain words (no backticks); anything else is returned as it is. */
export const signedOutSaid = (text: string): string => {
  const m = SIGNED_OUT.exec(text.trim());
  return m ? tr("ss.signedOut", { agent: m[1], cmd: m[2] }) : text;
};

const errText = (e: unknown) =>
  signedOutSaid(
    typeof e === "string"
      ? e
      : e instanceof Error
        ? e.message
        : typeof e === "object" && e && "message" in e
          ? String((e as { message: unknown }).message)
          : String(e),
  );

const readOpens = () => {
  try {
    return parseOpens(typeof localStorage !== "undefined" ? localStorage.getItem(OPEN_KEY) : null);
  } catch {
    return {};
  }
};

export function createSessions(host: SessionHost, store: () => Store = getStore, accounts: () => AccountGroup[] | null = () => null) {
  let state: SessionsState = { agents: null, home: null, list: [], recent: readRecent(), opens: readOpens(), models: {}, notes: {}, live: {}, unseen: {} };
  const listeners = new Set<() => void>();
  const terms = new Map<string, Term>();
  const procs = new Map<string, ChatProc>();
  /** app-store chat key per session id */
  const keys = new Map<string, string>();
  let seq = 0;
  let localSeq = 0;
  let resetDone: Promise<void> | null = null;
  let restored = false;
  /** Sessions put back after a restart: when started again they name the account they ran with (a new session
   *  sends no account; the shell uses the one picked for new sessions). */
  const fromBefore = new Set<string>();
  const accountOf = (r: SessionRec) => (fromBefore.has(r.id) ? r.account : undefined);
  /** TERMINALS sessions put back after a restart whose agent continues its own conversation: their next start (once)
   *  continues it (`--resume`, `codex resume`) instead of starting a new one. */
  const termAgain = new Set<string>();
  /** TERMINALS sessions put back after a restart whose kept history goes into their terminal before their program's
   *  first output (once). */
  const histBack = new Set<string>();
  /** Each TERMINALS session's history keeping (term/history.ts). */
  const histOf = new Map<string, { touch: () => void; stop: () => void; flush: () => void }>();
  watchHistorySetting(host);
  /** drafts whose agent / folder the person picked: a late agent or home look-up no longer moves them */
  const picked = new Map<string, { agent?: boolean; cwd?: boolean }>();
  let notify: ((ev: BridgeEvent) => void) | null = null;
  let notifyState: ((id: string, n: SessionNote) => void) | null = null;

  const set = (patch: Partial<SessionsState>) => {
    state = { ...state, ...patch };
    for (const l of [...listeners]) l();
  };
  const rec = (id: string) => state.list.find((s) => s.id === id);
  /** A link id no session in the list holds (termLink.ts). */
  const freshLinkId = (taken: ReadonlySet<string> = new Set(state.list.map((r) => r.linkId).filter((x): x is string => !!x))): string => {
    for (;;) {
      const id = newLinkId();
      if (!taken.has(id)) return id;
    }
  };

  // ---- what a session did while the person looked elsewhere --------------------------------

  /** The person sees session `id` right now: the window has focus and shows it. */
  const watching = (id: string) => {
    const ui = store().getState().ui;
    return windowWatched() && ui.view === "session" && ui.session === id;
  };
  /** `web-app · Claude Code`, as its notifications and its Needs-you row name it. */
  const nameOf = (r: SessionRec) => `${r.cwd.split(/[\\/]/).filter(Boolean).pop() ?? r.cwd} · ${agentLabel(r.agent, state.agents)}`;
  /** Session `id` did something the person did not see: its row carries it until they open the session. True when
   *  this is news (they are not watching, and the row does not say it already). */
  const flag = (id: string, what: Unseen): boolean => {
    if (!rec(id) || watching(id) || state.unseen[id] === what) return false;
    set({ unseen: { ...state.unseen, [id]: what } });
    return true;
  };
  /** The person opened session `id`: what its row carried for them is seen. */
  const seen = (id: string) => {
    if (!(id in state.unseen)) return;
    const unseen = { ...state.unseen };
    delete unseen[id];
    set({ unseen });
  };
  /** Session `id`'s program ended or could not start while the person was elsewhere: its row says so and a
   *  notification goes out. */
  const tellEnd = (id: string, kind: "ended" | "failed", detail: { code?: number | null; error?: string }, told = false) => {
    const r = rec(id);
    if (!r || watching(id)) return;
    flag(id, "end");
    // `told`: the turn that failed with it said the same reason (a notification only with "Also notify on errors");
    // `ms`: a program that ends within its first seconds did not really run
    notifyState?.(id, { kind, name: nameOf(r), ...detail, ms: Date.now() - r.startedAt, told });
  };
  const patchRec = (id: string, p: Partial<SessionRec>) => set({ list: state.list.map((s) => (s.id === id ? { ...s, ...p } : s)) });
  let titles = readTitles();
  const saveTitles = (next: Record<string, string>) => {
    titles = next;
    try {
      localStorage.setItem(TITLES_KEY, JSON.stringify(next));
    } catch {
      /* no storage */
    }
  };
  /** The agent's conversation id is known now: a name given before it was keeps under it, a saved one comes back. */
  const onAgentSession = (id: string) => {
    const r = rec(id);
    const k = r && titleKey(r);
    if (!r || !k) return;
    if (r.title && titles[k] !== r.title) saveTitles(putTitle(titles, k, r.title));
    else if (!r.title && titles[k]) patchRec(id, { title: titles[k] });
  };
  /** The title the agent wrote for this conversation in its own session files (Claude Code's title, a Codex thread
   *  name), read by the bridge. Quietly nothing when the bridge is older or the file is not there. */
  const readAgentTitle = async (id: string) => {
    const r = rec(id);
    if (!r?.agentSession || !TITLED.includes(r.agent)) return;
    try {
      const res = await store().actions.cliTitle(r.agent as "claude" | "codex", r.agentSession, r.cwd);
      const t = typeof res?.title === "string" ? res.title.trim() : "";
      if (t && rec(id) && rec(id)!.agentTitle !== t) patchRec(id, { agentTitle: t });
    } catch {
      /* an older bridge, or no file yet */
    }
  };
  const patchLive = (id: string, p: Partial<AgentLive>) => set({ live: { ...state.live, [id]: { ...state.live[id], ...p } } });
  /** The folder's branch, read again when a turn ends (the agent may have switched it). */
  const readBranch = async (id: string) => {
    const r = rec(id);
    if (!r?.cwd) return;
    try {
      const b = await host.branch(r.cwd);
      if (rec(id) && state.live[id]?.branch !== b) patchLive(id, { branch: b });
    } catch {
      /* an older shell */
    }
  };
  const note = (id: string, text: string | null) => {
    const notes = { ...state.notes };
    if (text) notes[id] = text;
    else delete notes[id];
    set({ notes });
  };

  const ready = () => (resetDone ??= host.reset().catch(() => undefined));

  const loadAgents = async () => {
    try {
      const [agents, home] = await Promise.all([host.agents(), state.home ? Promise.resolve(state.home) : host.home()]);
      // the generic ACP agents are rows the shell sends with the look-up: learn them before anything names one
      registerAcp(agents);
      set({ agents, home });
      refreshDrafts();
    } catch {
      set({ agents: state.agents ?? [] });
    }
  };

  /** Drafts the person has not set yet follow what is now known: the installed agents, the home folder. */
  const refreshDrafts = () => {
    for (const r of state.list) {
      if (r.status !== "draft") continue;
      const p = picked.get(r.id) ?? {};
      const patch: Partial<SessionRec> = {};
      if (!p.agent) {
        const agent = draftAgent(state.recent, state.agents);
        if (agent !== r.agent) patch.agent = agent;
      }
      if (!p.cwd && !r.cwd) {
        const cwd = draftFolder(state.recent, state.home);
        if (cwd) patch.cwd = cwd;
      }
      if (Object.keys(patch).length) patchRec(r.id, patch);
    }
  };

  // ---- chat plumbing ------------------------------------------------------------------------

  /** Apply one event from a session's chat to the app store, under the session's chat key. */
  const dispatchChat = (id: string, ev: ChatEvent) => {
    const key = keys.get(id);
    if (!key) return;
    const full = { ...ev, bot: key } as unknown as BridgeEvent;
    store().dispatch({ type: "event", ev: full, now: Date.now() });
    notify?.(full);
  };

  /** The chat's program is gone (it exited, or omher stopped it): a turn the chat still shows ends with it. The
   *  shell sends the turn's end before the exit when its adapter knew of the turn; this covers the rest (omher
   *  stopped it, so its last events are dropped). */
  const endLiveTurn = (id: string, outcome: "interrupted" | "ended") => {
    const key = keys.get(id);
    if (!key) return;
    if (store().getState().chats[key]?.turn) store().dispatch({ type: "event", ev: { event: "turn.end", bot: key, outcome } as BridgeEvent, now: Date.now() });
    // nobody is left to take an answer: an ask still open (a background subagent's, which outlives its turn) reads
    // "Not answered"
    for (const a of selectAsks(store().getState()).filter((x) => x.bot === key))
      store().dispatch({ type: "event", ev: { event: "prompt.expired", bot: key, request_id: a.item.request_id, reason: "cancelled" } as BridgeEvent, now: Date.now() });
  };

  /** An agent that is not signed in: omher stops it and the session ends with that one line (`proc.noChat`), said once
   *  beside Restart; the turn it failed keeps no second copy. */
  const endSignedOut = (id: string, proc: ChatProc) => {
    if (procs.get(id) !== proc) return;
    const error = proc.noChat ?? "";
    proc.stopping = true;
    procs.delete(id);
    endLiveTurn(id, "ended");
    if (proc.hostId !== undefined) void host.chatClose(proc.hostId).catch(() => undefined);
    patchRec(id, { status: "exited", exitCode: null, error });
    const key = keys.get(id);
    if (key) store().dispatch({ type: "turn.reasonMoved", bot: key, error });
    tellEnd(id, "ended", { code: null, error });
  };

  const onAgentEvent = (id: string, proc: ChatProc) => (ev: ChatEvent) => {
    if (procs.get(id) !== proc && ev.event !== "exit") return; // an old process of this session (Terminal toggle)
    switch (ev.event) {
      case "session.info": {
        const p: Partial<SessionRec> = {};
        const fresh = typeof ev.agent_session === "string" && !!ev.agent_session && ev.agent_session !== rec(id)?.agentSession;
        if (typeof ev.agent_session === "string" && ev.agent_session) p.agentSession = ev.agent_session;
        if (typeof ev.model === "string" && ev.model) p.model = ev.model;
        // a model picked mid-turn waits for the next turn ("" = it has taken effect, or was taken back)
        if (typeof ev.model_next === "string") p.modelNext = ev.model_next || undefined;
        // the agent named the conversation (Claude Code's session title, a Codex thread name)
        if (typeof ev.title === "string" && ev.title.trim()) p.agentTitle = ev.title.trim();
        if (typeof ev.background === "number") p.background = ev.background;
        patchRec(id, p);
        const l: Partial<AgentLive> = {};
        if (typeof ev.rewind === "boolean") l.rewind = ev.rewind;
        if (typeof ev.mode === "string") l.mode = ev.mode;
        if (typeof ev.approval === "string") l.approval = ev.approval;
        if (typeof ev.sandbox === "string") l.sandbox = ev.sandbox;
        if (typeof ev.effort === "string" && ev.effort) l.effort = ev.effort;
        if (Object.keys(l).length) patchLive(id, l);
        if (fresh) {
          onAgentSession(id);
          void readAgentTitle(id);
        }
        return;
      }
      case "session.models":
        set({ models: { ...state.models, [id]: Array.isArray(ev.options) ? (ev.options as ModelOption[]) : [] } });
        return;
      case "session.efforts":
        patchLive(id, { efforts: Array.isArray(ev.levels) ? ev.levels.filter((x): x is string => typeof x === "string" && !!x) : [] });
        return;
      case "session.commands": {
        // an agent may send its list in parts (Codex: skills after start-up): keep each entry once
        const next = parseCommands(ev.commands);
        const had = state.live[id]?.commands ?? [];
        const key = (c: AgentCommand) => c.prefix + c.name;
        const seen = new Set(next.map(key));
        patchLive(id, { commands: [...had.filter((c) => !seen.has(key(c))), ...next] });
        return;
      }
      case "session.usage":
        if (typeof ev.used === "number" && typeof ev.max === "number" && ev.max > 0) patchLive(id, { usage: { used: ev.used, max: ev.max } });
        return;
      case "session.error":
        if (ev.kind === "signed_out") {
          // not signed in: one line in the person's words with the agent's own sign-in command (its row in
          // acp_chat.rs), then the session ends; a turn already started fails with it first
          const agent = rec(id)?.agent ?? "claude";
          const login = typeof ev.login === "string" ? ev.login : "";
          proc.noChat = tr("ss.signedOut", { agent: agentDef(agent).label, cmd: login });
          proc.signedOut = true;
          patchLive(id, { signin: login });
          const key = keys.get(id);
          if (!key || !store().getState().chats[key]?.turn) endSignedOut(id, proc);
          return;
        }
        if (ev.kind === "no_chat_mode") {
          // the shell ends this session: say why in the person's words, with the line that updates the agent
          const agent = rec(id)?.agent ?? "claude";
          proc.noChat = tr("ss.noChatMode", { agent: agentDef(agent).label, install: installLine(agent) });
          return;
        }
        note(id, signedOutSaid(String(ev.message ?? "")));
        return;
      case "session.note":
        // something the agent's side did on its own that the person should know (Codex: a new conversation in place
        // of one that is gone)
        if (ev.kind === "new_conversation") {
          const key = keys.get(id);
          if (key) store().dispatch({ type: "system.note", bot: key, text: tr("ss.newConversation"), now: Date.now() });
        }
        return;
      case "exit": {
        if (procs.get(id) === proc) procs.delete(id);
        if (proc.stopping) return;
        endLiveTurn(id, "ended");
        const code = typeof ev.code === "number" ? ev.code : null;
        // code 0 is an orderly close: whatever the program printed (a start-up warning) is not why it ended
        const error = proc.noChat ?? (code !== 0 && typeof ev.error === "string" ? signedOutSaid(ev.error.trim()) : "");
        patchRec(id, { status: "exited", exitCode: code, ...(error ? { error } : {}) });
        // the turn the exit failed says "Failed after 0s"; its reason is the Ended line's, said once beside Restart
        const key = keys.get(id);
        if (key && error) store().dispatch({ type: "turn.reasonMoved", bot: key, error });
        const last = key ? store().getState().chats[key]?.lastTurn : null;
        tellEnd(id, "ended", { code, error }, !!last && last.outcome === "error" && Date.now() - (last.endedAt ?? 0) < 3000);
        return;
      }
      case "rewound": {
        // the agent took the person's last message back: the chat drops it and what came after, and the box offers
        // its text again (the text the person typed; the agent's own copy when omher has none)
        const key = keys.get(id);
        const items = key ? (store().getState().chats[key]?.items ?? []) : [];
        const last = [...items].reverse().find((i) => i.kind === "user");
        const text = last && last.kind === "user" ? last.text : typeof ev.text === "string" ? ev.text : "";
        dispatchChat(id, ev);
        if (key && text) store().dispatch({ type: "ui.draft", bot: key, text });
        return;
      }
      default:
        // a turn that failed because the agent is not signed in (a model that needs its account): the shell's
        // sentence, said in the person's language
        if (ev.event === "turn.end" && typeof ev.error === "string") ev = { ...ev, error: signedOutSaid(ev.error) };
        if (ev.event === "turn.end" && proc.noChat && ev.outcome === "error") ev = { ...ev, error: proc.noChat };
        dispatchChat(id, ev);
        if (ev.event === "turn.end") afterTurn(id, ev.outcome === "interrupted");
        if (ev.event === "turn.end" && proc.signedOut) {
          endSignedOut(id, proc);
          return;
        }
        // the agent may have titled the conversation during the turn
        // a new turn: the finished one its row still showed is behind it
        if (ev.event === "turn.start" && state.unseen[id] === "end") seen(id);
        if (ev.event === "turn.end") {
          // an answer the person did not watch arrive: the row says it finished until they open it
          if (ev.outcome === "done") flag(id, "end");
          void readAgentTitle(id);
          void readBranch(id);
        }
    }
  };

  /** Mark the session's chat loaded in the store (empty, or with the messages saved before a restart), so the
   *  timeline says hi instead of loading. */
  const openChat = (id: string, model = "", messages: Msg[] = []) => {
    const key = keys.get(id)!;
    if (store().getState().chats[key]?.loaded) return;
    store().dispatch({
      type: "chat.opened",
      bot: key,
      res: { session_id: key, messages, running: false, model, provider: "", reasoning: "" },
      now: Date.now(),
    });
  };

  const startAgentChat = async (id: string, resume?: string) => {
    const r = rec(id)!;
    const proc: ChatProc = { kind: "agent" };
    procs.set(id, proc);
    // a new process can take back only what it was sent itself (its own rewind)
    if (state.live[id]?.rewind) patchLive(id, { rewind: false });
    try {
      proc.hostId = await host.chatStart(r.agent, r.cwd, onAgentEvent(id, proc), resume, accountOf(r), id);
      // it said it is not signed in before omher knew its id: it is ended already, so only the process goes
      if (proc.signedOut) {
        void host.chatClose(proc.hostId).catch(() => undefined);
        return;
      }
      if (procs.get(id) !== proc) {
        // closed while starting
        void host.chatClose(proc.hostId).catch(() => undefined);
        return;
      }
      patchRec(id, { status: "running" });
      // the mode and effort the person picked before (a restart, a Restart) are set again
      const again = rec(id);
      if (again?.mode && modesOf(again.agent).includes(again.mode)) await host.chatInput(proc.hostId, { kind: "mode", mode: again.mode }).catch(() => undefined);
      if (again?.effort) await host.chatInput(proc.hostId, { kind: "effort", effort: again.effort }).catch(() => undefined);
      void readBranch(id);
    } catch (e) {
      if (procs.get(id) === proc) procs.delete(id);
      // the shell's refusal to start an agent whose ask rules it could not prove (acp_chat.rs NO_RULES), translated
      const why = errText(e);
      const label = agentDef(r.agent).label;
      const error = why === NO_RULES ? tr("ss.noRules") : why === NO_RULES.replaceAll("OpenCode", label) ? tr("ss.noRulesAgent", { agent: label }) : why;
      patchRec(id, { status: "failed", error });
      tellEnd(id, "failed", { error });
    }
  };

  const loadHermesModels = async (id: string, bot: string) => {
    const st = store();
    if (!st.getState().models[bot]) await st.actions.loadModels(bot);
    const opts = st.getState().models[bot];
    if (!opts) return;
    const list: ModelOption[] = opts.providers.flatMap((p) => p.models.map((m) => ({ id: m, label: m, detail: p.name, provider: p.slug })));
    set({ models: { ...state.models, [id]: list } });
  };

  const startFolderChat = async (id: string) => {
    const r = rec(id)!;
    const bot = r.bot;
    const proc: ChatProc = { kind: "folder", bot };
    procs.set(id, proc);
    try {
      if (!bot) throw new Error(tr("ss.noBot"));
      const res = await store().actions.folderOpen(bot, r.cwd);
      proc.fid = res.session;
      if (procs.get(id) !== proc) {
        void store().actions.folderClose(bot, res.session).catch(() => undefined);
        return;
      }
      keys.set(id, folderKey(bot, res.session));
      registerRoute(id);
      openChat(id, res.model);
      patchRec(id, { status: "running", model: res.model, agentSession: res.session });
      void loadHermesModels(id, bot);
    } catch (e) {
      if (procs.get(id) === proc) procs.delete(id);
      const error = errText(e);
      patchRec(id, { status: "failed", error });
      tellEnd(id, "failed", { error });
    }
  };

  const input = async (id: string, i: ChatInput) => {
    const proc = procs.get(id);
    const r = rec(id);
    if (!proc || !r) throw new Error(tr("ss.agentNotRunning", { agent: r ? agentDef(r.agent).label : tr("ss.theAgent") }));
    if (proc.kind === "agent") {
      if (proc.hostId === undefined) throw new Error(tr("ss.stillStarting"));
      await host.chatInput(proc.hostId, i);
      return;
    }
    const a = store().actions;
    const bot = proc.bot!;
    const fid = proc.fid;
    if (!fid) throw new Error(tr("ss.stillStarting"));
    if (i.kind === "send") await a.folderSend(bot, fid, i.text);
    else if (i.kind === "interrupt") await a.folderInterrupt(bot, fid);
    else if (i.kind === "approve") await a.folderApprove(bot, fid, i.request_id, i.choice);
    else if (i.kind === "clarify") await a.folderClarify(bot, fid, i.request_id, i.answer);
  };

  // ---- steer queue sessions ------------------------------------------------------------------
  //
  // A message sent while an agent chat's turn runs stays in omher (a held row with the ↵ mark, "Waiting") instead of
  // going to the agent's own queue, so it can still be sent now, steered in, edited or deleted. When the turn ends the
  // head goes out, one per turn, in order. The rows reuse the bot chat's steer queue (held rows, `queue.take` /
  // `queue.front` / `queue.drop`); the store's own flush, which sends through the Hermes bridge, is kept off agent
  // chats by a standing `steering` mark (HOLD_MARK), so only this code sends them, to the agent.

  /** What each held row sends, by its bubble id. */
  const heldInputs = new Map<string, { id: string; input: Extract<ChatInput, { kind: "send" }>; sent?: () => void }>();
  /** Sessions whose running turn Send now stopped: its end sends the chosen one first and keeps the rest waiting. */
  const sendingNow = new Set<string>();
  const HOLD_MARK = "agent-hold";
  const chatOf = (key: string) => store().getState().chats[key];
  /** Held for agent chats only (a Hermes folder chat goes through the bridge as before). */
  const mustHoldHere = (id: string, key: string) => procs.get(id)?.kind === "agent" && (!!chatOf(key)?.turn || !!chatOf(key)?.queue?.length);
  const hold = (id: string, key: string, lid: string, i: Extract<ChatInput, { kind: "send" }>, show: () => void, sent?: () => void) => {
    const st = store();
    if (chatOf(key)?.steering !== HOLD_MARK) st.dispatch({ type: "queue.steering", bot: key, id: HOLD_MARK });
    heldInputs.set(lid, { id, input: i, sent });
    show();
    // the row reads "Waiting", as a message the agent queued does
    dispatchChat(id, { event: "message.queued", id: lid });
  };
  /** The head held message goes out now: the row leaves the queue (moved to the end) before the request, once. */
  const sendHead = async (id: string) => {
    const key = keys.get(id);
    const head = key ? chatOf(key)?.queue?.[0] : undefined;
    if (!key || !head || chatOf(key)?.turn) return;
    const h = heldInputs.get(head);
    heldInputs.delete(head);
    store().dispatch({ type: "queue.take", bot: key, id: head, now: Date.now() });
    dispatchChat(id, { event: "message.taken", id: head });
    // no text kept for it, or the send fails: no turn starts, so no turn.end would ever send the next one
    if (!h) return void setTimeout(() => void sendHead(id), 0);
    h.sent?.();
    try {
      await input(id, h.input);
    } catch (e) {
      store().dispatch({ type: "send.failed", bot: key, id: head, error: errText(e) });
      setTimeout(() => void sendHead(id), 0);
    }
  };
  /** A turn ended. Stop (not Send now) throws away what waited, as the agents themselves do; otherwise the head goes. */
  const afterTurn = (id: string, stopped: boolean) => {
    const key = keys.get(id);
    // a Send now mark is used by this turn's end, whatever waits: a later real Stop is never read as Send now
    const now = sendingNow.delete(id);
    if (!key || !chatOf(key)?.queue?.length) return;
    if (stopped && !now) {
      for (const lid of [...(chatOf(key)?.queue ?? [])]) {
        heldInputs.delete(lid);
        store().dispatch({ type: "queue.take", bot: key, id: lid, now: Date.now() });
        dispatchChat(id, { event: "message.dropped", id: lid });
      }
      return;
    }
    setTimeout(() => void sendHead(id), 0);
  };
  const heldIn = (id: string, lid: string) => {
    const key = keys.get(id);
    return key && chatOf(key)?.queue?.includes(lid) && heldInputs.get(lid)?.id === id ? key : null;
  };
  /** The ↵ ↓ × buttons of a waiting message in session `id`'s chat. */
  const queuePick = async (id: string, lid: string, c: "now" | "steer" | "edit" | "delete") => {
    const key = heldIn(id, lid);
    if (!key) return; // already with the agent: the menu offers nothing
    const st = store();
    if (c === "delete" || c === "edit") {
      const text = heldInputs.get(lid)?.input.text ?? "";
      heldInputs.delete(lid);
      st.dispatch({ type: "queue.drop", bot: key, id: lid });
      if (c === "edit") {
        const typed = getDraft(key).trim();
        st.dispatch({ type: "ui.draft", bot: key, text: typed ? `${text}\n${typed}` : text });
      }
      return;
    }
    if (c === "now") {
      st.dispatch({ type: "queue.front", bot: key, id: lid });
      if (!chatOf(key)?.turn) return void sendHead(id);
      // one Stop, however often it is pressed; the stopped turn's end sends this one first
      if (sendingNow.has(id)) return;
      sendingNow.add(id);
      await input(id, { kind: "interrupt" }).catch((e) => {
        sendingNow.delete(id);
        note(id, errText(e));
      });
      return;
    }
    // Steer: the agent's own mid-turn input, text only; with pictures, or no turn left to steer, it goes out next
    const h = heldInputs.get(lid)!;
    const agent = rec(id)?.agent ?? "";
    if (!steersOf(agent)) return;
    if (!chatOf(key)?.turn || h.input.images?.length) {
      st.dispatch({ type: "queue.front", bot: key, id: lid });
      if (!chatOf(key)?.turn) void sendHead(id);
      return;
    }
    try {
      await input(id, { kind: "steer", id: lid, text: h.input.text });
      heldInputs.delete(lid);
      // with the agent now: no longer held, "Waiting" until the agent says it took it
      st.dispatch({ type: "queue.take", bot: key, id: lid, now: Date.now() });
    } catch {
      st.dispatch({ type: "queue.front", bot: key, id: lid });
    }
  };

  /** Send chat text: the bubble shows at once; a refusal marks it "Not sent". */
  const send = async (id: string, text: string) => {
    const t = text.trim();
    const key = keys.get(id);
    if (!t || !key) return;
    const st = store();
    const lid = `local-s${++localSeq}`;
    if (mustHoldHere(id, key)) {
      hold(id, key, lid, { kind: "send", text: t, id: lid }, () => st.dispatch({ type: "local.user", bot: key, id: lid, text: t, now: Date.now(), held: true }));
      return;
    }
    st.dispatch({ type: "local.user", bot: key, id: lid, text: t, now: Date.now() });
    // the first message that says something names the session until the agent or the person does
    const r = rec(id);
    if (r && !r.promptTitle) {
      const pt = promptTitle(t);
      if (pt) patchRec(id, { promptTitle: pt });
    }
    try {
      await input(id, { kind: "send", text: t, id: lid });
    } catch (e) {
      st.dispatch({ type: "send.failed", bot: key, id: lid, error: errText(e) });
    }
  };

  // ---- files --------------------------------------------------------------------------------

  let sentFiles = readSentFiles();
  const saveSentFiles = (next: SentFilesBook) => {
    sentFiles = next;
    try {
      localStorage.setItem(SENT_FILES_KEY, JSON.stringify(next));
    } catch {
      /* no storage */
    }
  };
  const forgetSentFiles = (id: string) => {
    if (!sentFiles[id]) return;
    const next = { ...sentFiles };
    delete next[id];
    saveSentFiles(next);
  };

  /** The bubble's own preview of a file (the composer lets go of its chips' copies when it goes). */
  const preview = (name: string, kind: SentFile["kind"], bytes: Uint8Array) =>
    kind === "file" ? null : URL.createObjectURL(new Blob([bytes as BlobPart], { type: blobType(name) }));

  /** A message with files, ready for the agent: each file saved under the session's own folder (pictures the agent
   *  reads itself listed apart), the text naming the others. Throws on the first file that cannot be saved; then
   *  nothing is sent. */
  const prepare = async (id: string, text: string, files: OutFile[]) => {
    const images: string[] = [];
    const named: string[] = [];
    const saved: SavedFile[] = [];
    const shown: SentFile[] = [];
    for (const f of files) {
      let path: string;
      let bytes: Uint8Array;
      try {
        bytes = bytesOf(await f.read());
        path = await host.saveFile(id, f.name, bytes);
      } catch (e) {
        throw new Error(tr("att.failed", { name: f.name, error: errText(e) }));
      }
      (inlinePicture(f.name, f.size) ? images : named).push(path);
      saved.push({ name: f.name, size: f.size, kind: f.kind, path });
      shown.push({ name: f.name, size: f.size, kind: f.kind, url: preview(f.name, f.kind, bytes) });
    }
    return { input: { kind: "send" as const, text: wireText(text, named), ...(images.length ? { images } : {}) }, saved, shown };
  };

  /** The bubble for a message with files, kept on this computer so it shows them again after a restart. */
  const showWithFiles = (id: string, key: string, text: string, p: Awaited<ReturnType<typeof prepare>>) => {
    const t = text.trim();
    const now = Date.now();
    const lid = `local-s${++localSeq}`;
    store().dispatch({ type: "local.user", bot: key, id: lid, text: t, now, files: p.shown });
    saveSentFiles(putSentFiles(sentFiles, id, String(now), { ts: now / 1000, text: t, files: p.saved }));
    const r = rec(id);
    const pt = t ? promptTitle(t) : "";
    if (r && !r.promptTitle && pt) patchRec(id, { promptTitle: pt });
    return lid;
  };

  /**
   * Send a message with files from a running chat. The files are saved first; if one cannot be, nothing is sent
   * and the error goes back to the composer (its chips stay).
   */
  const sendFiles = async (id: string, text: string, files: OutFile[]) => {
    if (!files.length) return send(id, text);
    const key = keys.get(id);
    if (!key) return;
    if (procs.get(id)?.kind !== "agent") throw new Error(tr("ss.agentNotRunning", { agent: agentDef(rec(id)?.agent ?? "claude").label }));
    const p = await prepare(id, text, files);
    if (mustHoldHere(id, key)) {
      // held with its saved files: they go with it when it goes out
      const lid = `local-s${++localSeq}`;
      hold(
        id,
        key,
        lid,
        { ...p.input, id: lid },
        () => store().dispatch({ type: "local.user", bot: key, id: lid, text: text.trim(), now: Date.now(), files: p.shown, held: true }),
        // kept for a restart only once it went out (as showWithFiles does for a message sent at once)
        () => {
          const now = Date.now();
          saveSentFiles(putSentFiles(sentFiles, id, String(now), { ts: now / 1000, text: text.trim(), files: p.saved }));
        },
      );
      return;
    }
    const lid = showWithFiles(id, key, text, p);
    try {
      await input(id, { ...p.input, id: lid });
    } catch (e) {
      store().dispatch({ type: "send.failed", bot: key, id: lid, error: errText(e) });
    }
  };

  /** Open a restored chat with its sent files back in their bubbles: each sent message's bubble is put down first
   *  with the files (read back from the saved copies), and the restored message with the same text and time takes
   *  them over; one sent with files and no text stays as it is. */
  const openWithFiles = async (id: string, model: string, msgs: Msg[]) => {
    const key = keys.get(id)!;
    const entries = Object.entries(sentFiles[id] ?? {});
    const oldest = msgs.length ? msgs[0].ts : -Infinity;
    for (const [mid, e] of entries) {
      if (e.ts < oldest - 1) continue; // older than what the chat kept
      const shown: SentFile[] = await Promise.all(
        e.files.map(async (f) => {
          if (f.kind === "file") return { name: f.name, size: f.size, kind: f.kind, url: null };
          try {
            return { name: f.name, size: f.size, kind: f.kind, url: preview(f.name, f.kind, await host.readFile(f.path)) };
          } catch {
            return { name: f.name, size: f.size, kind: "file" as const, url: null };
          }
        }),
      );
      if (store().getState().chats[key]?.loaded) return;
      store().dispatch({ type: "local.user", bot: key, id: `local-f${mid}`, text: e.text, now: e.ts * 1000, files: shown });
    }
    openChat(id, model, msgs);
  };

  const registerRoute = (id: string) => {
    const key = keys.get(id)!;
    const r = rec(id);
    setChatRoute(key, {
      // folder first: it tells sessions apart, and a narrow Needs-you row keeps it when the name is cut
      label: r ? `${r.cwd.split(/[\\/]/).filter(Boolean).pop() ?? r.cwd} · ${agentLabel(r.agent, state.agents)}` : tr("ss.session"),
      open: () => store().actions.openSession(id),
      send: (text) => send(id, text),
      interrupt: () => input(id, { kind: "interrupt" }),
      approve: (request_id: string, choice: ApprovalChoice) => input(id, { kind: "approve", request_id, choice }),
      clarify: (request_id: string, answer: string | ClarifyAnswers) => input(id, { kind: "clarify", request_id, answer }),
    });
  };

  // Hermes titles a folder chat on its own (instant title, then its titler): the session takes that name.
  onBridgeEvent((ev) => {
    if (ev.event !== "session.title" || !ev.session || !ev.title.trim()) return;
    for (const [id, p] of procs) if (p.kind === "folder" && p.bot === ev.bot && p.fid === ev.session) patchRec(id, { agentTitle: ev.title.trim() });
  });

  // A Hermes folder chat ends when the bridge says so (its gateway went away).
  onBridgeEvent((ev) => {
    if (ev.event !== "folder.closed" || !ev.session) return;
    for (const [id, p] of procs) {
      if (p.kind === "folder" && p.bot === ev.bot && p.fid === ev.session) {
        procs.delete(id);
        const error = ev.reason || tr("ss.hermesClosed");
        patchRec(id, { status: "exited", exitCode: null, error });
        tellEnd(id, "ended", { code: null, error });
      }
    }
  });

  // A Hermes folder chat's turns come over the bridge: an answer the person did not watch arrive marks its row, and
  // the next turn puts it behind.
  onBridgeEvent((ev) => {
    if (!ev.session || (ev.event !== "turn.start" && !(ev.event === "turn.end" && ev.outcome === "done"))) return;
    for (const [id, p] of procs) {
      if (p.kind !== "folder" || p.bot !== ev.bot || p.fid !== ev.session) continue;
      if (ev.event === "turn.end") flag(id, "end");
      else if (state.unseen[id] === "end") seen(id);
    }
  });

  // ---- sessions -----------------------------------------------------------------------------

  /**
   * Open a New session chat: a draft on `agent` (the one picked in the SESSIONS + menu; none = the last agent
   * used, else the first installed) in the last folder used (else home). An open draft is reused rather than
   * stacking a second one, and takes the agent picked. Nothing starts here.
   */
  const draft = (agent?: AgentId): string => {
    const open = state.list.find((r) => r.status === "draft");
    if (open) {
      if (agent) setDraft(open.id, { agent });
      store().actions.openSession(open.id);
      return open.id;
    }
    const id = `s${++seq}`;
    if (agent) picked.set(id, { agent: true });
    const r: SessionRec = {
      id,
      linkId: freshLinkId(),
      agent: agent ?? draftAgent(state.recent, state.agents),
      cwd: draftFolder(state.recent, state.home),
      startedAt: Date.now(),
      status: "draft",
      view: "chat",
    };
    set({ list: [r, ...state.list] });
    store().actions.openSession(id);
    if (state.agents === null || state.home === null) void loadAgents();
    return id;
  };

  /** New session here: a draft with session `id`'s agent and folder (an open draft takes them instead). */
  const draftHere = (id: string): string | null => {
    const r = rec(id);
    if (!r) return null;
    // an agent omher no longer offers: a New session on the usual agent, in the same folder
    if (isGone(r.agent)) {
      const d = draft();
      if (r.cwd) setDraft(d, { cwd: r.cwd });
      return d;
    }
    const d = draft(r.agent);
    if (r.cwd) setDraft(d, { agent: r.agent, cwd: r.cwd });
    return d;
  };

  /**
   * TERMINALS +: start `agent` (or the Shell, `SHELL`) in a terminal in `cwd` (none: the last folder used, else home)
   * at once, and open it. Never a chat: an agent that usually opens as omher's chat is opened as its own terminal.
   * A Shell runs `shell` (an id from the shell's list; none: Settings › Terminal › Default shell, else the login shell).
   */
  const startTerminal = (agent: AgentId, cwd?: string, shell?: string): string | null => {
    const at = cwd || draftFolder(state.recent, state.home);
    if (!at) return null;
    const id = `s${++seq}`;
    const startedAt = Date.now();
    const asTerminal = !isShell(agent) && sessionMode(state.agents, { agent }) !== "terminal";
    const account = isShell(agent) ? undefined : accountFor(accounts(), agent);
    const shellId = isShell(agent) ? shell || readTermSettings().defaultShell || undefined : undefined;
    const r: SessionRec = {
      id,
      linkId: freshLinkId(),
      agent,
      cwd: at,
      startedAt,
      status: "starting",
      view: "terminal",
      ...(asTerminal ? { open: "terminal" as const } : {}),
      ...(account ? { account } : {}),
      ...(shellId ? { shell: shellId } : {}),
      fgAgent: null,
    };
    const recent = pushRecent(state.recent, { agent, cwd: at, at: startedAt });
    try {
      localStorage.setItem(RECENT_KEY, JSON.stringify(recent));
    } catch {
      /* no storage */
    }
    set({ list: [r, ...state.list], recent });
    store().actions.openSession(id);
    return id;
  };

  /** The CLI running in the foreground of session `id`'s terminal (the shell's foreground-process event), or null. */
  const setSessionFg = (id: string, agent: string | null) => {
    const r = rec(id);
    if (!r || (r.fgAgent ?? null) === agent) return;
    patchRec(id, { fgAgent: agent });
  };

  /**
   * Continue a conversation Claude Code or Codex keeps for a folder (made in its CLI, or anywhere else): a session in
   * that folder whose chat shows the conversation's last messages, and whose agent continues it (Claude Code
   * `--resume`, Codex `thread/resume`). A session that already runs that conversation is opened instead.
   */
  const continuePast = async (chat: PastChat): Promise<string> => {
    const there = state.list.find((r) => r.agent === chat.agent && r.agentSession === chat.id && r.status !== "draft");
    if (there) {
      store().actions.openSession(there.id);
      if (there.status === "exited" || there.status === "failed") void restart(there.id);
      return there.id;
    }
    const id = `s${++seq}`;
    const startedAt = Date.now();
    const r: SessionRec = {
      id,
      linkId: freshLinkId(),
      agent: chat.agent,
      cwd: chat.cwd,
      startedAt,
      status: "starting",
      view: "chat",
      agentSession: chat.id,
      ...(chat.named ? { agentTitle: chat.title } : { promptTitle: chat.title }),
    };
    const recent = pushRecent(state.recent, { agent: chat.agent, cwd: chat.cwd, at: startedAt });
    try {
      localStorage.setItem(RECENT_KEY, JSON.stringify(recent));
    } catch {
      /* no storage */
    }
    set({ list: [r, ...state.list], recent });
    keys.set(id, `agent:${id}`);
    registerRoute(id);
    store().actions.openSession(id);
    await ready();
    let msgs: Msg[] = [];
    try {
      msgs = (await host.pastMessages(chat.agent, chat.id, chat.cwd)).map((m, i) => ({ id: `p-${i}`, role: m.role, text: m.text, ts: m.ts }));
    } catch {
      /* the conversation continues all the same; only its earlier messages are not shown */
    }
    if (!rec(id)) return id; // closed meanwhile
    openChat(id, "", msgs);
    onAgentSession(id);
    await startAgentChat(id, chat.id);
    return id;
  };

  /** Show session `id`'s folder in the file manager; a failure is said under its chat. */
  const revealFolder = async (id: string) => {
    const r = rec(id);
    if (!r?.cwd) return;
    try {
      await host.reveal(r.cwd);
    } catch (e) {
      note(id, errText(e));
    }
  };

  /** Open the person's own system terminal in session `id`'s folder; a failure is said under its chat. */
  const openTerminal = async (id: string) => {
    const r = rec(id);
    if (!r?.cwd) return;
    try {
      await host.openTerminal(r.cwd);
    } catch (e) {
      note(id, errText(e));
    }
  };

  /** Change a draft's agent or folder (refused once it has started). */
  const setDraft = (id: string, p: { agent?: AgentId; cwd?: string }) => {
    const r = rec(id);
    if (!r || r.status !== "draft") return;
    const patch: Partial<SessionRec> = {};
    if (p.agent) patch.agent = p.agent;
    if (p.cwd) patch.cwd = p.cwd;
    picked.set(id, { ...picked.get(id), ...(p.agent ? { agent: true } : {}), ...(p.cwd ? { cwd: true } : {}) });
    patchRec(id, patch);
  };

  /** The native folder dialog for a draft, opening at its folder; cancelling it changes nothing. */
  const chooseFolder = async (id: string): Promise<string | null> => {
    const r = rec(id);
    if (!r || r.status !== "draft") return null;
    const folder = await host.pickFolder(r.cwd || state.home || "");
    if (folder) setDraft(id, { cwd: folder });
    return folder;
  };

  /** Pick how a draft opens, Chat or Terminal (one the agent has; remembered for the agent on this computer). */
  const setOpen = (id: string, way: OpenAs) => {
    const r = rec(id);
    if (!r || r.status !== "draft" || !opensAs(r.agent, state.agents)[way]) return;
    const opens = { ...state.opens, [r.agent]: way };
    try {
      localStorage.setItem(OPEN_KEY, JSON.stringify(opens));
    } catch {
      /* no storage */
    }
    set({ opens });
  };

  /**
   * Start a draft: its agent in its folder, `first` as the agent's first prompt (a chat agent; the bubble shows at
   * once). A draft opened as a terminal (the agent's own, or the person's pick) starts the program in the folder and
   * is sent nothing. From here the agent, folder and way of opening are fixed.
   */
  const start = async (id: string, first?: string, startedAs?: string, files: OutFile[] = []): Promise<boolean> => {
    const r0 = rec(id);
    if (!r0 || r0.status !== "draft" || !r0.cwd) return false;
    await ready();
    const r = rec(id);
    if (!r || r.status !== "draft") return false; // closed or started meanwhile
    const open = draftOpen(r.agent, state.agents, state.opens);
    const mode = sessionMode(state.agents, { agent: r.agent, open });
    const text = first?.trim() ?? "";
    // the first message's files are saved before anything starts: one that cannot be leaves the draft as it was
    // (its chips stay)
    let withFiles: Awaited<ReturnType<typeof prepare>> | null = null;
    if (files.length && mode === "chat") {
      try {
        withFiles = await prepare(id, text, files);
      } catch (e) {
        void host.removeFiles(id).catch(() => undefined);
        throw e;
      }
      if (rec(id)?.status !== "draft") return false; // closed meanwhile
    }
    picked.delete(id);
    const app = store().getState();
    const startedAt = Date.now();
    // the account it runs as is the one picked for new sessions now (recorded so a restart continues as it)
    const account = accountFor(accounts(), r.agent);
    const recent = pushRecent(state.recent, { agent: r.agent, cwd: r.cwd, at: startedAt });
    try {
      localStorage.setItem(RECENT_KEY, JSON.stringify(recent));
    } catch {
      /* no storage */
    }
    set({ recent });
    patchRec(id, {
      startedAt,
      status: "starting",
      view: mode === "terminal" ? "terminal" : "chat",
      // only a way the agent does not open by itself is kept on the session
      ...(open === "terminal" && sessionMode(state.agents, { agent: r.agent }) !== "terminal" ? { open } : {}),
      ...(account ? { account } : {}),
      ...(startedAs ? { startedAs } : {}),
      // oh-my-hermes runs on the bot you were looking at (else the first bot)
      // a folder chat runs on this computer: a bot on another one (`<peer>:<name>`) is never its engine
      ...(mode === "hermes" ? { bot: localBot(app.selectedBot, app.bots) } : {}),
    });
    // the message is sent: the draft view goes before its composer clears its own unsent text, so clear it here
    // (a terminal starts without the text and files the draft held)
    if (text || files.length || mode === "terminal") setUnsent(`agent:${id}`, "");
    // the first message names the session (as a later one would in send) until the agent or the person does
    const pt = text ? promptTitle(text) : "";
    if (pt) patchRec(id, { promptTitle: pt });
    if (mode === "chat") {
      keys.set(id, `agent:${id}`);
      registerRoute(id);
      openChat(id);
      if (!text && !withFiles) {
        await startAgentChat(id);
        return true;
      }
      // the first prompt shows at once (with its files) and goes to the agent as soon as it runs
      const st = store();
      const key = keys.get(id)!;
      const lid = withFiles ? showWithFiles(id, key, text, withFiles) : `local-s${++localSeq}`;
      if (!withFiles) st.dispatch({ type: "local.user", bot: key, id: lid, text, now: Date.now() });
      await startAgentChat(id);
      try {
        await input(id, withFiles ? { ...withFiles.input, id: lid } : { kind: "send", text, id: lid });
      } catch (e) {
        st.dispatch({ type: "send.failed", bot: key, id: lid, error: errText(e) });
      }
    } else if (mode === "hermes") {
      await startFolderChat(id);
      if (text && rec(id)?.status === "running") await send(id, text);
    }
    return true;
  };

  /** The app theme in force, as the terminal views last reported it. */
  let look: "dark" | "light" = "dark";

  /** How many times session `id`'s terminal was started again (Restart): the view keys its terminal on it. */
  const termRuns = new Map<string, number>();
  /** What stops following each session's foreground CLI (its pty's `session-fg` events). */
  const fgOff = new Map<string, () => void>();

  /** TERMINALS Codex sessions that do not know their conversation id yet: the next ask. A running Codex holds its
   *  own rollout open once its first prompt is answered, so while the row's Codex runs the shell is asked which
   *  conversation the Codex in that terminal's foreground holds open (rule 11: only the pty id goes out, only a UUID
   *  comes back), 5 s after it started and every 15 s after, until it names one; that is kept as the row's
   *  `agentSession` so a restart continues it (`codex resume <id>`) and the asking stops. A row only ever hears of the
   *  file its own process holds, so another row's conversation can never come to it. A Codex that ends stops the
   *  asking and hands its id to no row (its row goes on as its shell and is not resumed); one that never learned it
   *  comes back paused. */
  const codexIdTimer = new Map<string, ReturnType<typeof setTimeout>>();
  const findCodexId = (id: string, t: Term, run: number, pty: number, wait: number) => {
    if (!host.codexConversation) return;
    clearTimeout(codexIdTimer.get(id));
    codexIdTimer.set(
      id,
      setTimeout(async () => {
        codexIdTimer.delete(id);
        const live = () => terms.get(id) === t && t.run === run && !t.closed && t.hostId === pty && rec(id)?.agent === "codex" && !rec(id)?.agentSession;
        if (!live()) return;
        const got = await host.codexConversation!(pty).catch(() => null);
        if (!live()) return;
        if (got) patchRec(id, { agentSession: got });
        else findCodexId(id, t, run, pty, CODEX_ID_EVERY_MS);
      }, wait),
    );
  };

  /**
   * Start session `id`'s program in its terminal `t`. A Shell row runs the person's login shell; a CLI row runs its
   * CLI and, when that ends, goes on as the login shell in the same terminal (same scrollback, size and folder), so
   * the next CLI the person starts there is followed like any other (`session-fg`). When the shell of a TERMINALS row
   * ends the row closes, as its x does; a shell that ends with an error before the person typed anything (it could
   * not start properly) stays, with what it printed.
   */
  const startTerm = async (id: string, t: Term) => {
    const r = rec(id);
    if (!r) return;
    const run = ++t.run;
    const shell = isShell(r.agent);
    const io: TermIo = shell ? getShellHost() : host;
    t.io = io;
    t.hostId = null;
    t.closed = false;
    t.typed = false;
    t.told = null;
    // the terminal view of a chat session does not decide the session's status; the chat does
    const ofChat = sessionMode(state.agents, r) !== "terminal";
    // a TERMINALS Claude Code or Codex session put back after a restart continues its own conversation (once);
    // Claude Code's terminal view of a chat continues the chat's conversation
    const again = !ofChat && termAgain.delete(id) && !!r.agentSession && TERM_CONTINUES.includes(r.agent);
    const resume = again ? r.agentSession : r.agentSession && ofChat && r.agent === "claude" ? r.agentSession : undefined;
    // any other Claude Code terminal starts a new conversation under an id omher makes, kept so a restart continues it
    const sessionId = !ofChat && !resume && r.agent === "claude" ? newConversationId() : undefined;
    if (sessionId) patchRec(id, { agentSession: sessionId });
    // what this terminal showed before omher restarted comes first, dimmed, under a divider (once)
    if (!ofChat && histBack.delete(id)) {
      const back = await restoredText(host, id);
      if (t.run !== run) return;
      if (back) feed(t.term, back);
    }
    if (!ofChat && !histOf.has(id)) {
      const h = trackHistory(host, id, () => (terms.get(id) === t && !isParked(t.raw) ? t.term : null));
      const flush = () => h.flush();
      t.el.addEventListener(PARKING_EVENT, flush);
      histOf.set(id, { ...h, stop: () => (t.el.removeEventListener(PARKING_EVENT, flush), h.stop()) });
    }
    const { cols, rows } = t.term;
    let marked = 0;
    // this program's pty id once known, and what was drawn of its output before that
    let pty: number | null = null;
    let owed = 0;
    // the TERMINALS card's second line: the last line on its screen with text, read a moment after output stops
    // flowing in (once per OUT_MARK_MS at most), from the terminal itself
    let lineTimer: ReturnType<typeof setTimeout> | null = null;
    const readLine = () => {
      lineTimer = null;
      const b = t.term.buffer.active;
      const lines: string[] = [];
      for (let y = 0; y < t.term.rows; y++) lines.push(b.getLine(b.baseY + y)?.translateToString(true) ?? "");
      const line = lastPrintedLine(lines) || undefined;
      // its own small store: a line change re-renders that one row, never the sessions list
      if (rec(id)) termActs.patch(id, { lastLine: line });
    };
    // parked before that read came (only an e2e's short thresholds allow it: a real park waits for a minute of
    // quiet): the line is read now, from the xterm being parked, so the read does not make it again
    const lineBeforePark = () => {
      if (t.run !== run) return t.el.removeEventListener(PARKING_EVENT, lineBeforePark);
      if (lineTimer === null) return;
      clearTimeout(lineTimer);
      readLine();
    };
    t.el.addEventListener(PARKING_EVENT, lineBeforePark);
    const onData = (d: Uint8Array | string) => {
      // every message is acknowledged once the terminal has taken it, in order: the shell reads the program
      // no further ahead of the page than its credit allows (to this program only: a replaced one is gone)
      const bytes = typeof d === "string" ? utf8.encode(d).length : d.byteLength;
      feed(t.term, d, () => {
        if (t.run !== run) return;
        if (pty === null) owed += bytes;
        else io.ack(pty, bytes);
      });
      histOf.get(id)?.touch();
      // the TERMINALS row's spinner and age: when output last flowed (throttled)
      const now = Date.now();
      if (!ofChat && now - marked >= OUT_MARK_MS) {
        marked = now;
        termActs.patch(id, { lastOut: now });
      }
      if (!ofChat && lineTimer === null) lineTimer = setTimeout(readLine, OUT_MARK_MS);
    };
    try {
      const onExit = (code: number | null) => {
        // a program omher stopped (the row closed, Restart) or one already replaced says nothing more
        if (terms.get(id) !== t || t.run !== run) return;
        t.closed = true;
        termActs.patch(id, { progress: undefined });
        if (lineTimer !== null) clearTimeout(lineTimer);
        lineTimer = null;
        fgOff.get(id)?.();
        fgOff.delete(id);
        if (rec(id)?.fgAgent) setSessionFg(id, null);
        // its row was closed and waits to be undone: with the program gone there is nothing to undo
        if (t.held) {
          grace.finish(id);
          return;
        }
        const label = agentDef(r.agent).label;
        const end = termEnd({ ofChat, shell, typed: t.typed, code });
        if (end === "shell") {
          // the CLI ended: the same terminal goes on as the person's login shell in that folder
          feed(t.term, `\r\n\x1b[2m${code ? tr("ss.backToShellExit", { agent: label, code }) : tr("ss.backToShell", { agent: label })}\x1b[0m\r\n`);
          patchRec(id, { agent: SHELL, open: undefined, account: undefined, agentSession: undefined, agentTitle: undefined, startedAs: undefined, fgAgent: null, status: "starting", exitCode: null, error: undefined });
          void startTerm(id, t);
          return;
        }
        if (end === "close") {
          // exit, Ctrl+D: the row goes, as closing it with its x does (nothing runs, so no undo window)
          close(id);
          return;
        }
        if (!ofChat) {
          patchRec(id, { status: "exited", exitCode: code });
          tellEnd(id, "ended", { code });
        }
        feed(t.term, `\r\n\x1b[2m[${code ? tr("ss.termEndedExit", { agent: label, code }) : tr("ss.termEnded", { agent: label })}]\x1b[0m\r\n`);
      };
      // a Shell row is the person's login shell (the bottom panel's `shell_start`: only a folder and a size go out)
      // this computer's name first, so the program's first OSC 7 already counts as local
      await learnThisHost();
      let hostId: number;
      if (shell) {
        const got = await getShellHost().start(r.cwd || null, cols, rows, onData, onExit, rec(id)?.shell);
        hostId = got.id;
        if (got.missing && t.run === run) {
          // the shell it was made with is gone from this computer: the default one runs, and the row says so once
          feed(t.term, `\x1b[33m${tr("term.shellMissing", { shell: got.missing })}\x1b[0m\r\n`);
          patchRec(id, { shell: undefined });
        }
      } else hostId = await host.start(r.agent, r.cwd, cols, rows, onData, onExit, resume, accountOf(r), sessionId);
      if (t.run !== run) {
        // replaced while starting
        void io.close(hostId).catch(() => undefined);
        return;
      }
      t.hostId = hostId;
      pty = hostId;
      // the TERMINALS row's mark follows the CLI the shell sees in the foreground (`session-fg`)
      fgOff.get(id)?.();
      fgOff.set(id, onSessionFg(hostId, (agent) => setSessionFg(id, agent)));
      if (t.closed) {
        // closed while starting
        void io.close(hostId);
        return;
      }
      if (owed) io.ack(hostId, owed);
      owed = 0;
      // the program started at this size; one that changed while it started is sent now
      t.told = { cols, rows };
      if (t.settle === null) tellSize(t);
      if (!ofChat) patchRec(id, { status: "running" });
      if (!ofChat && r.agent === "codex" && !rec(id)?.agentSession) findCodexId(id, t, run, hostId, CODEX_ID_FIRST_MS);
    } catch (e) {
      if (t.run !== run) return;
      t.closed = true;
      const error = errText(e);
      if (!ofChat) {
        patchRec(id, { status: "failed", error });
        tellEnd(id, "failed", { error });
      }
      feed(t.term, `\x1b[31m${error}\x1b[0m\r\n`);
    }
  };

  /** Tell the program its terminal's size, if it is not the one it was last told. */
  const tellSize = (t: Term) => {
    t.settle = null;
    if (t.hostId === null || t.closed) return;
    const { cols, rows } = t.term;
    if (t.told?.cols === cols && t.told.rows === rows) return;
    t.told = { cols, rows };
    void t.io.resize(t.hostId, cols, rows).catch(() => undefined);
  };

  const disposeTerm = (id: string) => {
    const t = terms.get(id);
    if (!t) return;
    // its history keeping follows the next terminal of the session (Restart), or ends with it
    histOf.get(id)?.stop();
    histOf.delete(id);
    clearTimeout(codexIdTimer.get(id));
    codexIdTimer.delete(id);
    fgOff.get(id)?.();
    fgOff.delete(id);
    if (t.hostId !== null && !t.closed) void t.io.close(t.hostId).catch(() => undefined);
    t.closed = true;
    if (t.settle !== null) clearTimeout(t.settle);
    const wasParked = isParked(t.raw);
    t.undo();
    if (!wasParked) t.raw.dispose(); // a parked one was disposed when it was parked
    t.el.remove();
    terms.delete(id);
  };

  /** Mount session `id`'s terminal into `container` (creating and starting it the first time). */
  const attach = (id: string, container: HTMLElement, mode: "dark" | "light"): (() => void) => {
    look = mode;
    if (xtermMods) return mount(xtermMods, id, container);
    let detach: (() => void) | null = null;
    let gone = false;
    void loadXterm().then((m) => {
      if (!gone) detach = mount(m, id, container);
    });
    return () => {
      gone = true;
      detach?.();
    };
  };

  const mount = ([{ Terminal }, { FitAddon }]: Xterm, id: string, container: HTMLElement, quiet = false): (() => void) => {
    const settings = readTermSettings();
    const theme = termTheme(look, settings);
    let t = terms.get(id);
    const fresh = !t;
    if (!t) {
      const el = document.createElement("div");
      el.className = "term-host";
      const make = (opts: ITerminalOptions & ITerminalInitOnlyOptions) => {
        const term = new Terminal(opts);
        const fit = new FitAddon();
        term.loadAddon(fit);
        return { term, fit };
      };
      const first = make(termOptions(theme, settings));
      t = {
        get term() {
          return live(this.raw);
        },
        raw: first.term,
        fit: first.fit,
        el,
        hostId: null,
        closed: false,
        undo: () => undefined,
        told: null,
        settle: null,
        io: isShell(rec(id)?.agent) ? getShellHost() : host,
        run: 0,
        typed: false,
      };
      terms.set(id, t);
      const tt = t;
      // a parked terminal made again: the same options and handlers, at the size it had, where it was
      tt.remake = ({ cols, rows }) => {
        const s = readTermSettings();
        const th = termTheme(look, s);
        const next = make({ ...termOptions(th, s), cols, rows });
        tt.raw = next.term;
        tt.fit = next.fit;
        wire(next.term);
        next.term.open(tt.el);
        tt.undo = afterOpen(next.term, tt.el, s, tt.remake);
        applyLook(next.term, th, s);
        return next.term;
      };
      const wire = (term: Terminal) => {
        term.onData((d) => {
          if (tt.hostId === null || tt.closed || tt.held) return;
          tt.typed = true;
          void tt.io.write(tt.hostId, d).catch(() => undefined);
        });
        // the title the program sets (OSC 0/2): the TERMINALS card's second line until it prints a line
        term.onTitleChange((title) => {
          const v = title.replace(/\s+/g, " ").trim().slice(0, LAST_LINE_MAX) || undefined;
          if (rec(id)) termActs.patch(id, { oscTitle: v });
        });
        term.onResize(() => {
          // the size it ends on is sent, once (a drag gives one size per frame)
          if (tt.settle !== null) clearTimeout(tt.settle);
          tt.settle = setTimeout(() => tellSize(tt), RESIZE_SETTLE_MS);
        });
        // The program rang the terminal's bell, as agents do when they wait for the person. omher reads nothing the
        // program prints: the bell is the one thing a terminal tells it. The row says so and a notification goes
        // out, once, until the person comes back to the session.
        const ring = () => {
          const r = rec(id);
          if (r && !tt.closed && flag(id, "bell")) notifyState?.(id, { kind: "bell", name: nameOf(r), agent: termMarkAgent(r) !== null });
        };
        term.onBell(ring);
        // The notification escapes agents send instead of a bell count as a ring too: OSC 9 with a message (not a
        // `9;<number>` report such as the 9;4 progress bar) and OSC 777 `notify`. Their text is never shown or kept.
        term.parser.registerOscHandler(9, (d) => {
          if (!/^\d+(;|$)/.test(d)) ring();
          return false; // not consumed: another handler may want the escape
        });
        term.parser.registerOscHandler(777, (d) => {
          if (d.startsWith("notify;")) ring();
          return false;
        });
      };
      wire(first.term);
      // the folder its shell reports (OSC 7): the row's folder line. Progress (OSC 9;4): working while reported; done
      // after working, unseen, marks the row as the bell does (no notification: a report is not a ring). Both come
      // on the element, which a parked terminal made again keeps, and go with it.
      onCwd(el, (path) => {
        if (rec(id)) termActs.patch(id, { cwd: path });
      });
      onProgress(el, (st) => {
        if (!rec(id) || tt.closed) return;
        if (st === "busy") return termActs.patch(id, { progress: true });
        if (!termActs.get(id).progress) return;
        termActs.patch(id, { progress: undefined });
        flag(id, "bell");
      });
    }
    const tt = t;
    container.appendChild(tt.el);
    if (fresh) {
      tt.raw.open(tt.el);
      tt.undo = afterOpen(tt.raw, tt.el, settings, tt.remake);
    }
    applyLook(tt.term, theme, settings);
    const refit = () => {
      if (!tt.el.isConnected || tt.el.clientWidth === 0) return;
      try {
        tt.fit.fit();
      } catch {
        /* not measurable yet */
      }
    };
    refit();
    if (fresh) void ready().then(() => startTerm(id, tt));
    const ro = new ResizeObserver(refit);
    ro.observe(container);
    // and when its cells change size (the GPU renderer arrived after this fit, or went)
    tt.el.addEventListener(CELLS_EVENT, refit);
    onVisible(tt.term, true);
    if (!quiet) tt.term.focus();
    return () => {
      ro.disconnect();
      tt.el.removeEventListener(CELLS_EVENT, refit);
      onVisible(tt.raw, false);
      if (tt.el.parentElement === container) container.removeChild(tt.el);
    };
  };

  /** A paused TERMINALS session's kept history (dimmed, under its divider), shown read-only in `container` until the
   *  person presses Resume: a terminal of its own that starts nothing, takes no keys and is not the session's
   *  terminal (Resume makes that one, which writes the same history back first). `shown` hears whether there was any. */
  const previewHistory = (id: string, container: HTMLElement, mode: "dark" | "light", shown: (has: boolean) => void): (() => void) => {
    let gone = false;
    let term: Terminal | null = null;
    let ro: ResizeObserver | null = null;
    if (!histBack.has(id)) {
      shown(false);
      return () => undefined;
    }
    void Promise.all([loadXterm(), restoredText(host, id)]).then(([[{ Terminal: Term }, { FitAddon }], text]) => {
      if (gone) return;
      if (!text) return shown(false);
      const s = readTermSettings();
      const theme = termTheme(mode, s);
      const t = (term = new Term({ ...termOptions(theme, s), disableStdin: true, cursorBlink: false }));
      const fit = new FitAddon();
      t.loadAddon(fit);
      t.open(container);
      applyLook(t, theme, s);
      const refit = () => {
        if (!container.isConnected || container.clientWidth === 0) return;
        try {
          fit.fit();
        } catch {
          /* not measurable yet */
        }
      };
      refit();
      ro = new ResizeObserver(refit);
      ro.observe(container);
      // the kept text, and no cursor: nothing runs here
      t.write(`${text}\x1b[?25l`);
      shown(true);
    });
    return () => {
      gone = true;
      ro?.disconnect();
      term?.dispose();
    };
  };

  /** Type text at session `id`'s terminal prompt, as if the person had (a dropped file's path). */
  const typeAt = async (id: string, text: string) => {
    const t = terms.get(id);
    if (!t || t.hostId === null || t.closed || t.held) return;
    t.typed = true;
    await t.io.write(t.hostId, text);
    t.term.focus();
  };

  /** Type a bot's prompt the person allowed (termShare.ts: the card's Allow, each request its own) into session
   *  `id`'s terminal, then Enter. A bracketed paste when the program turned that on, so a many-line prompt arrives as
   *  one (a parked terminal keeps the mode it had: term/engine.ts `bracketedPaste`); else its lines are typed as a
   *  paste types them. Control characters never reach the program (the prompt is
   *  cleaned before and here). Nothing else calls this. */
  const typeAllowed = async (id: string, prompt: string) => {
    const t = terms.get(id);
    if (!t || t.hostId === null || t.closed || t.held) return false;
    // eslint-disable-next-line no-control-regex
    const text = prompt.replace(/\r\n/g, "\n").replace(/[\u0000-\u0009\u000b-\u001f\u007f-\u009f]/g, "");
    if (!text.trim()) return false;
    const bracketed = bracketedPaste(t.raw);
    await t.io.write(t.hostId, bracketed ? `\x1b[200~${text}\x1b[201~\r` : `${text.replace(/\n/g, "\r")}\r`);
    return true;
  };

  /** Files dropped or pasted on session `id`'s terminal: each saved under the session's own folder (the page
   *  never sees a dropped file's own path), then the saved paths typed at the prompt, shell-quoted. */
  const dropOnTerminal = async (id: string, files: { name: string; read: () => Promise<Uint8Array> }[], windows: boolean) => {
    const t = terms.get(id);
    if (t?.held) return; // closed, waiting to be undone: nothing is saved or typed
    const paths: string[] = [];
    for (const f of files) {
      try {
        paths.push(shellQuote(await host.saveFile(id, f.name, await f.read()), windows));
      } catch (e) {
        if (t) feed(t.term, `\r\n\x1b[31m${tr("att.failed", { name: f.name, error: errText(e) })}\x1b[0m\r\n`);
        return;
      }
    }
    if (paths.length) await typeAt(id, `${paths.join(" ")} `);
  };

  const stopChat = async (id: string) => {
    const p = procs.get(id);
    if (!p) return;
    p.stopping = true;
    procs.delete(id);
    endLiveTurn(id, "interrupted");
    if (p.kind === "agent" && p.hostId !== undefined) await host.chatClose(p.hostId).catch(() => undefined);
    if (p.kind === "folder" && p.bot && p.fid) await store().actions.folderClose(p.bot, p.fid).catch(() => undefined);
  };

  /**
   * Switch a chat session between its chat and its agent's terminal. Claude Code's terminal continues the
   * same conversation (`--resume`), and coming back continues it in the chat; every other agent's terminal
   * starts its TUI fresh while its chat stays as it was.
   */
  const setView = async (id: string, view: "chat" | "terminal") => {
    const r = rec(id);
    if (!r || r.view === view || sessionMode(state.agents, r) === "terminal") return;
    // a Hermes chat without oh-my-hermes has no terminal view: that view would start `omh`
    if (view === "terminal" && r.agent === "omh" && hermesOnly(state.agents)) return;
    if (r.agent === "claude" && r.agentSession) {
      if (view === "terminal") {
        await stopChat(id);
        disposeTerm(id); // a fresh terminal each time, resuming the conversation as it is now
        patchRec(id, { view });
      } else {
        disposeTerm(id);
        patchRec(id, { view, status: "starting" });
        await startAgentChat(id, r.agentSession);
        // Claude Code's own terminal titles the conversation; the chat continues it under that title
        void readAgentTitle(id);
      }
      return;
    }
    patchRec(id, { view });
  };

  /** A session opened as a terminal whose agent has no terminal on this computer any more (oh-my-hermes was removed
   *  and only Hermes is left) goes on as its agent opens by itself, instead of starting a program that is not there. */
  const lostTerminal = (id: string) => {
    const r = rec(id);
    if (!r || r.open !== "terminal" || state.agents === null || opensAs(r.agent, state.agents).terminal) return;
    const t = terms.get(id);
    if (t && !t.closed) return; // its program still runs: leave it be
    disposeTerm(id);
    // a Hermes chat runs on a bot: the one in view (else the first), as a New session picks it
    const app = store().getState();
    const bot = agentDef(r.agent).mode === "hermes" && !r.bot ? localBot(app.selectedBot, app.bots) : undefined;
    patchRec(id, { open: undefined, view: "chat", ...(bot ? { bot } : {}) });
  };

  /**
   * Start an ended session's agent again: a chat agent in the same chat, a terminal agent in a fresh terminal, in
   * the same folder and account. Agents in `CONTINUES` continue their conversation (Claude Code `--resume`, Codex
   * `thread/resume`, OmO `--session`, DSH `--session-id`); the others (pi, oh-my-pi, Grok's terminal) start a new one.
   */
  const restart = async (id: string) => {
    lostTerminal(id);
    const r = rec(id);
    if (!r || (r.status !== "exited" && r.status !== "failed") || isGone(r.agent)) return;
    if (sessionMode(state.agents, r) === "terminal") {
      // a fresh terminal: the view mounts it and starts the program (continuing the conversation, as startTerm says)
      const t = terms.get(id);
      if (t && !t.closed) return;
      disposeTerm(id);
      termRuns.set(id, (termRuns.get(id) ?? 0) + 1);
      patchRec(id, { status: "starting", error: undefined, exitCode: null, view: "terminal", paused: undefined });
      return;
    }
    if (procs.has(id) || sessionMode(state.agents, r) !== "chat") return;
    const resume = continues(r.agent) && r.agentSession ? r.agentSession : undefined;
    patchRec(id, { status: "starting", error: undefined, exitCode: null, view: "chat", paused: undefined });
    patchLive(id, { signin: undefined });
    note(id, null);
    await startAgentChat(id, resume);
  };

  /**
   * Start a session that was running when omher closed and did not continue by itself (pi, oh-my-pi, Grok,
   * oh-my-hermes, a chat whose conversation id was never reported), in the same folder and account. Once only.
   */
  const resume = async (id: string) => {
    lostTerminal(id);
    const r = rec(id);
    if (!r?.paused || procs.has(id) || terms.has(id)) return;
    const mode = sessionMode(state.agents, r);
    if (mode === "chat") return restart(id);
    if (mode === "terminal") {
      // the terminal view starts the program when it mounts
      patchRec(id, { paused: undefined, status: "starting", error: undefined, exitCode: null });
      return;
    }
    // oh-my-hermes: a new Hermes chat in the folder; the saved one was only a picture of the old chat
    const old = keys.get(id);
    patchRec(id, { paused: undefined, status: "starting", error: undefined, exitCode: null });
    if (old) {
      keys.delete(id);
      setChatRoute(old, null);
      store().dispatch({ type: "chat.forget", bot: old });
    }
    await startFolderChat(id);
  };

  /**
   * Put back the sessions saved before omher restarted (once per page load; a second call does nothing, so no
   * program starts twice). Each keeps its id, folder, account and chat. A chat that was running and continues a
   * conversation (Claude Code, Codex, OmO) continues it; any other running one comes back paused; ended ones stay
   * ended (with Restart).
   */
  const restore = (saved: SavedSession[]) => {
    if (restored || state.list.length > 0) return;
    restored = true;
    if (!saved.length) {
      void ready().then(() => host.pruneFiles([]).catch(() => undefined));
      void ready().then(() => pruneHistory(host, savedPanelKeys()));
      saveSentFiles({});
      return;
    }
    const list: SessionRec[] = [];
    const again: { id: string; resume: string }[] = [];
    // generic ACP agents the shell has not described yet (it answers after this): whether they continue by themselves
    // is known once it has
    const later: string[] = [];
    for (const s of saved) {
      if (isGone(s.agent) && s.draft) {
        // a New session never started on an agent omher no longer offers: a draft again, on the usual agent
        list.push({ id: s.id, agent: draftAgent(state.recent, state.agents), cwd: s.cwd, startedAt: s.startedAt, view: "chat", status: "draft" });
        picked.set(s.id, { cwd: true });
        seq = Math.max(seq, Number(s.id.slice(1)) || 0);
        continue;
      }
      if (isGone(s.agent)) {
        // an agent omher no longer offers (Kilo Code): ended, with its chat as it was, one plain line and no Restart
        // (SessionView's Ended); nothing is started, now or on Resume
        list.push({ id: s.id, agent: s.agent, cwd: s.cwd, startedAt: s.startedAt, view: "chat", status: "exited", exitCode: null, ...(s.title ? { title: s.title } : {}), ...(s.agentTitle ? { agentTitle: s.agentTitle } : {}), ...(s.promptTitle ? { promptTitle: s.promptTitle } : {}) });
        fromBefore.add(s.id);
        seq = Math.max(seq, Number(s.id.slice(1)) || 0);
        keys.set(s.id, `agent:${s.id}`);
        openChat(s.id, s.model ?? "", (s.messages ?? []).map((m) => ({ id: `r-${m.id}`, role: m.role, text: m.text, ts: m.ts })));
        continue;
      }
      if (s.draft) {
        // a New session chat that never started: a draft again, with its agent and folder fixed by the person
        list.push({ id: s.id, agent: s.agent, cwd: s.cwd, startedAt: s.startedAt, view: "chat", status: "draft" });
        picked.set(s.id, { agent: true, cwd: true });
        seq = Math.max(seq, Number(s.id.slice(1)) || 0);
        continue;
      }
      const mode = sessionMode(state.agents, s);
      if (s.agent === "dsh" && s.view === "terminal") {
        // omher 0.2.4's DSH ran deepseek-bot's terminal (its id is a deepseek-bot conversation): it comes back ended
        // with a plain line and never starts deepseek-bot; Restart starts DeepSeek Harness in the folder
        list.push({ id: s.id, agent: s.agent, cwd: s.cwd, startedAt: s.startedAt, view: "chat", status: "exited", exitCode: null, error: tr("ss.dshOld"), ...(s.title ? { title: s.title } : {}) });
        fromBefore.add(s.id);
        seq = Math.max(seq, Number(s.id.slice(1)) || 0);
        keys.set(s.id, `agent:${s.id}`);
        openChat(s.id);
        continue;
      }
      // TERMINALS lists terminal sessions only: a saved chat-mode session is kept as it was (its files and messages
      // stay) but is not listed and never starts again
      const terminalOnly = !isTerminalRec(state.agents, { agent: s.agent, open: s.open, status: "exited" });
      const auto = !terminalOnly && s.running && mode === "chat" && continuesItself(s);
      // a TERMINALS Claude Code or Codex session that was running continues its own conversation in a fresh terminal
      const termAuto = !terminalOnly && s.running && mode === "terminal" && !!s.agentSession && TERM_CONTINUES.includes(s.agent);
      const r: SessionRec = {
        id: s.id,
        agent: s.agent,
        cwd: s.cwd,
        startedAt: s.startedAt,
        // a chat agent comes back as its chat (its terminal view would start the program on sight)
        view: mode === "terminal" ? "terminal" : "chat",
        ...(s.open === "terminal" ? { open: s.open } : {}),
        status: auto || termAuto ? "starting" : s.failed ? "failed" : "exited",
        exitCode: s.running ? null : (s.exitCode ?? null),
        ...(s.error && !s.running ? { error: s.error } : {}),
        ...(s.agentSession ? { agentSession: s.agentSession } : {}),
        ...(s.account ? { account: s.account } : {}),
        ...(s.bot ? { bot: s.bot } : {}),
        ...(s.model ? { model: s.model } : {}),
        // its name comes back with it
        ...(s.title ? { title: s.title } : {}),
        ...(s.agentTitle ? { agentTitle: s.agentTitle } : {}),
        ...(s.promptTitle ? { promptTitle: s.promptTitle } : {}),
        ...(s.mode ? { mode: s.mode } : {}),
        ...(s.effort ? { effort: s.effort } : {}),
        ...(s.shell && isShell(s.agent) ? { shell: s.shell } : {}),
        ...(s.running && !auto && !termAuto ? { paused: true } : {}),
      };
      list.push(r);
      fromBefore.add(s.id);
      seq = Math.max(seq, Number(s.id.slice(1)) || 0);
      if (mode !== "terminal") {
        keys.set(s.id, `agent:${s.id}`);
        // fresh ids: the agent's own message ids start over in its new process
        const msgs: Msg[] = (s.messages ?? []).map((m) => ({ id: `r-${m.id}`, role: m.role, text: m.text, ts: m.ts }));
        if (sentFiles[s.id]) void openWithFiles(s.id, s.model ?? "", msgs);
        else openChat(s.id, s.model ?? "", msgs);
      }
      if (auto) again.push({ id: s.id, resume: s.agentSession! });
      if (termAuto) termAgain.add(s.id);
      if (!terminalOnly && mode === "terminal") histBack.add(s.id);
      else if (s.running && s.agentSession && !isBuiltin(s.agent) && !acpRow(s.agent) && !terminalOnly) later.push(s.id);
    }
    // each keeps its link (a session saved before links existed, or a clash, gets a fresh one)
    const taken = new Set(state.list.map((r) => r.linkId).filter((x): x is string => !!x));
    for (const [i, r] of list.entries()) {
      const was = saved.find((x) => x.id === r.id)?.linkId;
      const linkId = was && !taken.has(was) ? was : freshLinkId(taken);
      taken.add(linkId);
      list[i] = { ...r, linkId };
    }
    set({ list: [...list, ...state.list] });
    for (const r of list) if (keys.has(r.id)) registerRoute(r.id);
    // the saved copies of sessions that are gone go; the ones kept show again in their bubbles
    const ids = list.map((r) => r.id);
    void ready().then(() => host.pruneFiles(ids).catch(() => undefined));
    // the kept history of terminals that are gone goes (the bottom panel's tabs keep theirs)
    void ready().then(() => pruneHistory(host, [...ids, ...savedPanelKeys()]));
    saveSentFiles(Object.fromEntries(Object.entries(sentFiles).filter(([sid]) => ids.includes(sid))));

    // the home folder (for `~/…` paths) and each agent's mode, as a first launch would read them; then the generic ACP
    // agents' chats whose row says they continue go on by themselves, as the others did
    void loadAgents().then(() => {
      for (const id of later) {
        const r = rec(id);
        if (r?.paused && continues(r.agent) && sessionMode(state.agents, r) === "chat") void resume(id);
      }
    });
    if (again.length) void ready().then(() => Promise.all(again.map(({ id, resume: rid }) => (procs.has(id) ? undefined : startAgentChat(id, rid)))));
    // their terminals are made and started now, off the page (a view that opens one later takes it as it is)
    if (termAgain.size && typeof document !== "undefined") void loadXterm().then((m) => [...termAgain].forEach((id) => startOffPage(m, id)));
  };

  /** Make session `id`'s terminal and start its program without showing it: measured in a box off the page, then
   *  taken off it, as a terminal whose view the person left. Nothing happens when its view already made it. */
  const startOffPage = (m: Xterm, id: string) => {
    if (terms.has(id) || !rec(id)) return;
    const box = document.createElement("div");
    box.style.cssText = "position:fixed;left:-10000px;top:0;width:960px;height:600px;visibility:hidden";
    document.body.appendChild(box);
    try {
      mount(m, id, box, true)();
    } finally {
      box.remove();
    }
  };

  /** What a closed row needs to come back: itself, where it stood in the list, and the split it was in. */
  type Held = { rec: SessionRec; index: number; split: SplitWas | null };
  /** Closed TERMINALS rows whose program still runs for the undo window; at its end the old close runs, once. */
  const grace = createCloseGrace<Held>({ expire: (g) => close(g.id) });
  /** The rows of closes waiting out their window (no longer listed): what `close` reads when the window ends. */
  const heldRecs = new Map<string, SessionRec>();
  if (typeof document !== "undefined") {
    // a hidden window may hold timers back: whatever passed its deadline closes when the window shows again
    document.addEventListener("visibilitychange", () => grace.sweep());
    window.addEventListener("focus", () => grace.sweep());
  }
  /** The undo window now, in ms (0: Off). The mock host takes `window.__omherCloseGraceMs` for a window that is on;
   *  a browser driven by a test (`navigator.webdriver`) that set none closes at once, as specs written before the
   *  undo window expect (term-close-undo.spec.ts sets it). */
  const graceNow = () => {
    let w: unknown;
    if (typeof window !== "undefined" && !("__TAURI_INTERNALS__" in window)) {
      w = (window as unknown as { __omherCloseGraceMs?: unknown }).__omherCloseGraceMs;
      if (w === undefined && typeof navigator !== "undefined" && navigator.webdriver) w = 0;
    }
    return graceMs(readTermSettings().undoClose, w);
  };

  /** Close TERMINALS row `id` so it can be undone: it leaves the list (and its split) now, its terminal takes no
   *  input, its program runs on hidden. False when it closes as before: the setting is Off, it is not a TERMINALS row,
   *  or its program is not running (ended, or still starting with nothing yet). */
  const holdable = (id: string): boolean => {
    const r = rec(id);
    const t = terms.get(id);
    return !!r && !!t && !t.closed && !t.held && t.hostId !== null && isTerminalRec(state.agents, r) && graceNow() > 0;
  };
  const holdClosed = (id: string): boolean => {
    const r = rec(id);
    const t = terms.get(id);
    if (!r || !t || !holdable(id)) return false;
    const ms = graceNow();
    const g = groupOf(getSplit().groups, id);
    const index = state.list.findIndex((s) => s.id === id);
    const split: SplitWas | null = g ? { layout: g.layout, ...(g.zoom ? { zoom: true as const } : {}) } : null;
    if (!grace.begin(id, r.title || nameOf(r), ms, { rec: r, index, split })) return false;
    heldRecs.set(id, r);
    t.held = true;
    const list = state.list.filter((s) => s.id !== id);
    set({ list });
    const ui = store().getState().ui;
    if (ui.view === "session" && ui.session === id) {
      const next = list[Math.min(index, list.length - 1)];
      store().actions.openSession(next ? next.id : null);
    }
    return true;
  };

  /** Undo the close of row `id` (the newest when none is named): the same row, terminal and program back where it
   *  was, in its split when that is still there. False when there is nothing to undo. */
  const undoClose = (id?: string): boolean => {
    const which = id ?? grace.list()[0]?.id;
    const g = which ? grace.undo(which) : null;
    if (!g) return false;
    heldRecs.delete(g.id);
    const t = terms.get(g.id);
    if (t) t.held = false;
    const list = [...state.list];
    list.splice(Math.max(0, Math.min(g.data.index, list.length)), 0, g.data.rec);
    set({ list });
    if (g.data.split) {
      const groups = restoreSplitIn(getSplit().groups, g.id, g.data.split, new Set(list.map((r) => r.id)));
      if (groups !== getSplit().groups) setSplit({ groups });
    }
    store().actions.openSession(g.id);
    return true;
  };

  /** The person closes session `id` (row x, its menu, ⌘W): a running TERMINALS row waits out the undo window first
   *  (Settings › Terminal), anything else closes at once. A shell that ended by itself closes through `close`. */
  const closeRow = (id: string) => {
    if (holdClosed(id)) return;
    if (grace.finish(id)) return;
    close(id);
  };

  /** Stop the program(s) and remove the session. A row that waited out its undo window is no longer listed: its
   *  kept row says what it was. */
  const close = (id: string) => {
    const r = rec(id) ?? heldRecs.get(id);
    heldRecs.delete(id);
    picked.delete(id);
    histOf.get(id)?.stop();
    histOf.delete(id);
    histBack.delete(id);
    termAgain.delete(id);
    if (r && isTerminalRec(state.agents, { ...r, status: "exited" })) forgetHistory(host, id);
    disposeTerm(id);
    void stopChat(id).then(() => host.removeFiles(id).catch(() => undefined));
    forgetSentFiles(id);
    const key = keys.get(id);
    if (key) {
      setChatRoute(key, null);
      store().dispatch({ type: "chat.forget", bot: key }); // its asks leave the Needs-you strip with it
    }
    keys.delete(id);
    const idx = state.list.findIndex((s) => s.id === id);
    const list = state.list.filter((s) => s.id !== id);
    const models = { ...state.models };
    delete models[id];
    const notes = { ...state.notes };
    delete notes[id];
    const live = { ...state.live };
    delete live[id];
    const unseen = { ...state.unseen };
    delete unseen[id];
    set({ list, models, notes, live, unseen });
    const ui = store().getState().ui;
    if (ui.view === "session" && ui.session === id) {
      const next = list[Math.min(idx, list.length - 1)];
      store().actions.openSession(next ? next.id : null);
    }
  };

  /** A person's own agent was removed on Settings › Agents: each open session of it ends cleanly (its program is
   *  stopped, its chat stays as it was, it says it ended), its drafts move to the usual agent, and the + menu forgets it. */
  const endAgent = async (agent: AgentId) => {
    for (const r of state.list.filter((x) => x.agent === agent)) {
      if (r.status === "draft") {
        picked.delete(r.id);
        patchRec(r.id, { agent: draftAgent(state.recent, (state.agents ?? []).filter((a) => a.id !== agent)) });
        continue;
      }
      disposeTerm(r.id);
      if (procs.has(r.id)) await stopChat(r.id);
      if (r.status === "running" || r.status === "starting" || r.paused) patchRec(r.id, { status: "exited", exitCode: null, paused: undefined });
    }
    const recent = state.recent.filter((x) => x.agent !== agent);
    set({ recent });
    try {
      localStorage.setItem(RECENT_KEY, JSON.stringify(recent));
    } catch {
      // storage refused: the recents are only this page's until it loads again
    }
    await loadAgents();
  };

  /** Name a session (Rename). Empty or null = back to the automatic name. Kept on this computer under the agent's
   *  own conversation id, so the name follows the conversation when it is resumed. */
  const rename = (id: string, title: string | null) => {
    const r = rec(id);
    if (!r || r.status === "draft") return; // a draft is named once it starts
    const t = (title ?? "").replace(/\s+/g, " ").trim().slice(0, NAME_MAX);
    patchRec(id, { title: t || undefined });
    const k = titleKey(r);
    if (k) saveTitles(putTitle(titles, k, t || null));
  };

  /** Change a chat session's model (Claude Code `set_model`, Codex per turn, pi `set_model`, Hermes). */
  const setModel = async (id: string, option: ModelOption) => {
    const p = procs.get(id);
    if (!rec(id) || !p) return;
    note(id, null);
    try {
      if (p.kind === "folder") {
        const cur = await store().actions.folderSetModel(p.bot!, p.fid!, { model: option.id, ...(option.provider ? { provider: option.provider } : {}) });
        patchRec(id, { model: cur.model || option.label });
      } else {
        await input(id, { kind: "model", model: option.id });
      }
    } catch (e) {
      note(id, tr("ss.modelNotChanged", { error: errText(e) }));
    }
  };

  /** Change a chat session's permission mode (Claude Code's own switch; Codex from its next turn). Kept with the
   *  session, so a restart sets it again. Only the modes controls.ts offers for the agent. */
  const setMode = async (id: string, mode: string) => {
    const r = rec(id);
    if (!r || !modesOf(r.agent).includes(mode)) return;
    note(id, null);
    try {
      await input(id, { kind: "mode", mode });
      patchRec(id, { mode });
    } catch (e) {
      note(id, tr("ss.modelNotChanged", { error: errText(e) }));
    }
  };

  /** Change a chat session's reasoning effort, one of the levels its agent reported. */
  const setEffort = async (id: string, effort: string) => {
    const r = rec(id);
    if (!r || !(state.live[id]?.efforts ?? []).includes(effort)) return;
    note(id, null);
    try {
      await input(id, { kind: "effort", effort });
      patchRec(id, { effort });
    } catch (e) {
      note(id, tr("ss.modelNotChanged", { error: errText(e) }));
    }
  };

  /** Every open terminal takes the look again: the app theme changed, or a terminal setting did. */
  const relook = () => {
    const settings = readTermSettings();
    const theme = termTheme(look, settings);
    for (const t of terms.values()) {
      if (isParked(t.raw)) continue; // takes the look when it is made again
      applyLook(t.term, theme, settings);
      // a changed font or line height changes how many cells fit
      if (t.el.isConnected && t.el.clientWidth > 0) {
        try {
          t.fit.fit();
        } catch {
          /* not measurable yet */
        }
      }
    }
  };
  const setLook = (mode: "dark" | "light") => {
    look = mode;
    relook();
  };
  onTermSettings(relook);

  return {
    getState: () => state,
    subscribe(fn: () => void) {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
    /** Stop whatever an earlier load of this page left running (called once at startup). */
    reset: ready,
    loadAgents,
    endAgent,
    draft,
    draftHere,
    startTerminal,
    setSessionFg,
    /** The pty id session `id`'s terminal runs on (the `session-fg` event's id), null before it started. */
    ptyOf: (id: string): number | null => terms.get(id)?.hostId ?? null,
    /** The native folder dialog (TERMINALS + menu's "Choose folder…"); null when cancelled. */
    pickFolder: (at: string) => host.pickFolder(at),
    continuePast,
    revealFolder,
    openTerminal,
    setDraft,
    setOpen,
    chooseFolder,
    start,
    attach,
    close: closeRow,
    /** Closing row `id` now could be undone (its row then closes without asking: the toast's Undo is the way back). */
    closeUndoable: holdable,
    undoClose,
    /** Closed rows waiting out their undo window, newest first (the toasts). */
    closing: grace.list,
    onClosing: grace.subscribe,
    setLook,
    setView,
    setModel,
    setMode,
    setEffort,
    rename,
    restart,
    resume,
    restore,
    send,
    sendFiles,
    dropOnTerminal,
    typeAllowed,
    /** Session `id`'s terminal program runs and takes input now (what `typeAllowed` needs). */
    canType: (id: string): boolean => {
      const t = terms.get(id);
      return !!t && t.hostId !== null && !t.closed && !t.held;
    },
    /** The ↵ ↓ × buttons of a waiting message (steer queue sessions): Send now or Steer, Edit, Delete. */
    queuePick,
    /** Esc / Stop: the agent's own interrupt. */
    interrupt: (id: string) => input(id, { kind: "interrupt" }).catch(() => undefined),
    /** Edit and resend: the agent takes back the last message (its own rewind), then the box holds its text. */
    rewind: async (id: string) => {
      try {
        await input(id, { kind: "rewind" });
      } catch (e) {
        note(id, errText(e));
      }
    },
    /** The session whose link id is `linkId`, if it is in the list. */
    byLink: (linkId: string): SessionRec | null => state.list.find((r) => r.linkId === linkId) ?? null,
    /** Session `id`'s link (`omher://terminal/<id>`), null when it has none. */
    linkOf: (id: string): string | null => {
      const l = rec(id)?.linkId;
      return l ? termLinkUrl(l) : null;
    },
    /** Copy session `id`'s link to the clipboard; false when it has none or the clipboard refused. */
    copyLink: async (id: string): Promise<boolean> => {
      const l = rec(id)?.linkId;
      if (!l) return false;
      try {
        await navigator.clipboard.writeText(termLinkUrl(l));
        window.dispatchEvent(new CustomEvent<string>(LINK_COPIED_EVENT, { detail: id }));
        return true;
      } catch {
        return false;
      }
    },
    /** Session `id` has a terminal in this page load (an ended one keeps its output until it is closed). */
    hasTerm: (id: string) => terms.has(id),
    previewHistory,
    /** Changes each time Restart starts session `id`'s terminal program again. */
    termRun: (id: string) => termRuns.get(id) ?? 0,
    /** The session whose chat has app-store key `key`. */
    byKey: (key: string) => {
      for (const [id, k] of keys) if (k === key) return rec(id) ?? null;
      return null;
    },
    /** The app-store chat key of session `id`'s chat, if it has one. */
    chatKey: (id: string | null) => (id ? (keys.get(id) ?? null) : null),
    /** Hook for system notifications of session chats (the app sets it). */
    setNotify(fn: ((ev: BridgeEvent) => void) | null) {
      notify = fn;
    },
    /** The person opened session `id`: what its row carried for them is seen. */
    seen,
    /** Hook for system notifications of what a session did outside its chat (the app sets it). */
    setNotifyState(fn: ((id: string, n: SessionNote) => void) | null) {
      notifyState = fn;
    },
  };
}

export type SessionsStore = ReturnType<typeof createSessions>;

let singleton: SessionsStore | null = null;
export function getSessions(): SessionsStore {
  if (!singleton) {
    const s = createSessions(getHost(), getStore, accountGroups);
    singleton = s;
    // e2e (mock host only): drive a terminal's foreground CLI the way the shell's event will
    if (typeof window !== "undefined" && !("__TAURI_INTERNALS__" in window)) (window as unknown as { __omherSessions?: SessionsStore }).__omherSessions = s;
    setSessionKeyLookup((id) => s.chatKey(id));
    s.setNotify((ev) => notifySessionEvent(ev, getStore().getState()));
    s.setNotifyState((id, n) => notifySessionNote(id, n, getStore().getState()));
  }
  return singleton;
}

export function useSessions(): SessionsState {
  const s = getSessions();
  return useSyncExternalStore(s.subscribe, s.getState, s.getState);
}
