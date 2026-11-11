// SESSIONS: the agent sessions omher started in this run of the app. Each one is an allow-listed agent
// (claude, codex, omo, dsh, omh, pi, omp, grok) in a folder the person picked. Most open as a chat: Claude Code,
// Codex, OmO, pi and oh-my-pi run in their structured mode in the desktop shell (src-tauri/src/agent_chat.rs),
// oh-my-hermes opens a Hermes chat in that folder through the bridge (`folder.open`). Their events land in
// the app store under the session's own chat key, so the bot chat's timeline, activity line, cards and
// composer draw them. Grok and DSH have no chat mode here, so they stay a terminal (xterm on a pseudo-terminal);
// DSH gets a conversation id when it starts (`--resume <id>`), so its Resume continues that conversation.
// Every chat can switch to its agent's terminal view.
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
import { useSyncExternalStore } from "react";
import type { ITheme, Terminal } from "@xterm/xterm";
import type { FitAddon } from "@xterm/addon-fit";
import { agentDef, CONTINUES, draftAgent, draftFolder, parseRecent, pushRecent, RECENT_KEY, type AgentId, type AgentInfo, type Recent, type SessionRec } from "./agents";
import { NAME_MAX, parseTitles, promptTitle, putTitle, TITLES_KEY } from "./titles";
import { setDraft as setUnsent } from "../app/drafts";
import { getHost, type ChatEvent, type ChatInput, type SessionHost } from "./host";
import { folderKey, getStore, notifySessionEvent, onBridgeEvent, setChatRoute, setSessionKeyLookup, type Store } from "../state/store";
import type { AccountCli, AccountGroup, ApprovalChoice, BridgeEvent, ClarifyAnswers, Msg } from "../lib/protocol";
import { continuesItself, type SavedSession } from "../app/resume";
import { accountGroups } from "../settings/accounts/useAccounts";
import { t as tr } from "../i18n";

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
  /** models a chat session can switch to, by session id */
  models: Record<string, ModelOption[]>;
  /** last problem a chat reported that is not a turn's own error (model refused, …), by session id */
  notes: Record<string, string>;
}

interface Term {
  term: Terminal;
  fit: FitAddon;
  /** xterm renders into this element; it moves between session views instead of being re-created */
  el: HTMLDivElement;
  hostId: number | null;
  closed: boolean;
}

type Xterm = [typeof import("@xterm/xterm"), typeof import("@xterm/addon-fit")];
let xtermLoad: Promise<Xterm> | null = null;
let xtermMods: Xterm | null = null;
/** xterm (about 88 kB gz) loads when the first session opens, not with the app. */
const loadXterm = () =>
  (xtermLoad ??= Promise.all([import("@xterm/xterm"), import("@xterm/addon-fit"), import("@xterm/xterm/css/xterm.css")]).then(
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
}

const readRecent = () => {
  try {
    return parseRecent(typeof localStorage !== "undefined" ? localStorage.getItem(RECENT_KEY) : null);
  } catch {
    return [];
  }
};

/** The names the person gave sessions, kept on this computer by the agent's own conversation id. */
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

const errText = (e: unknown) =>
  typeof e === "string"
    ? e
    : e instanceof Error
      ? e.message
      : typeof e === "object" && e && "message" in e
        ? String((e as { message: unknown }).message)
        : String(e);

/** How an agent opens, from the shell's list (or the UI list for an older shell). */
const modeOf = (agents: AgentInfo[] | null, id: AgentId) => agents?.find((a) => a.id === id)?.mode ?? agentDef(id).mode;

export function createSessions(host: SessionHost, store: () => Store = getStore, accounts: () => AccountGroup[] | null = () => null) {
  let state: SessionsState = { agents: null, home: null, list: [], recent: readRecent(), models: {}, notes: {} };
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
  /** drafts whose agent / folder the person picked: a late agent or home look-up no longer moves them */
  const picked = new Map<string, { agent?: boolean; cwd?: boolean }>();
  let notify: ((ev: BridgeEvent) => void) | null = null;

  const set = (patch: Partial<SessionsState>) => {
    state = { ...state, ...patch };
    for (const l of [...listeners]) l();
  };
  const rec = (id: string) => state.list.find((s) => s.id === id);
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
    if (!key || !store().getState().chats[key]?.turn) return;
    store().dispatch({ type: "event", ev: { event: "turn.end", bot: key, outcome } as BridgeEvent, now: Date.now() });
  };

  const onAgentEvent = (id: string, proc: ChatProc) => (ev: ChatEvent) => {
    if (procs.get(id) !== proc && ev.event !== "exit") return; // an old process of this session (Terminal toggle)
    switch (ev.event) {
      case "session.info": {
        const p: Partial<SessionRec> = {};
        const fresh = typeof ev.agent_session === "string" && !!ev.agent_session && ev.agent_session !== rec(id)?.agentSession;
        if (typeof ev.agent_session === "string" && ev.agent_session) p.agentSession = ev.agent_session;
        if (typeof ev.model === "string" && ev.model) p.model = ev.model;
        // the agent named the conversation (Claude Code's session title, a Codex thread name)
        if (typeof ev.title === "string" && ev.title.trim()) p.agentTitle = ev.title.trim();
        patchRec(id, p);
        if (fresh) {
          onAgentSession(id);
          void readAgentTitle(id);
        }
        return;
      }
      case "session.models":
        set({ models: { ...state.models, [id]: Array.isArray(ev.options) ? (ev.options as ModelOption[]) : [] } });
        return;
      case "session.error":
        note(id, String(ev.message ?? ""));
        return;
      case "exit": {
        if (procs.get(id) === proc) procs.delete(id);
        if (proc.stopping) return;
        endLiveTurn(id, "ended");
        const code = typeof ev.code === "number" ? ev.code : null;
        const error = typeof ev.error === "string" ? ev.error.trim() : "";
        patchRec(id, { status: "exited", exitCode: code, ...(error ? { error } : {}) });
        return;
      }
      default:
        dispatchChat(id, ev);
        // the agent may have titled the conversation during the turn
        if (ev.event === "turn.end") void readAgentTitle(id);
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
    try {
      proc.hostId = await host.chatStart(r.agent, r.cwd, onAgentEvent(id, proc), resume, accountOf(r));
      if (procs.get(id) !== proc) {
        // closed while starting
        void host.chatClose(proc.hostId).catch(() => undefined);
        return;
      }
      patchRec(id, { status: "running" });
    } catch (e) {
      if (procs.get(id) === proc) procs.delete(id);
      patchRec(id, { status: "failed", error: errText(e) });
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
      patchRec(id, { status: "failed", error: errText(e) });
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

  /** Send chat text: the bubble shows at once; a refusal marks it "Not sent". */
  const send = async (id: string, text: string) => {
    const t = text.trim();
    const key = keys.get(id);
    if (!t || !key) return;
    const st = store();
    const lid = `local-s${++localSeq}`;
    st.dispatch({ type: "local.user", bot: key, id: lid, text: t, now: Date.now() });
    // the first message that says something names the session until the agent or the person does
    const r = rec(id);
    if (r && !r.promptTitle) {
      const pt = promptTitle(t);
      if (pt) patchRec(id, { promptTitle: pt });
    }
    try {
      await input(id, { kind: "send", text: t });
    } catch (e) {
      st.dispatch({ type: "send.failed", bot: key, id: lid, error: errText(e) });
    }
  };

  const registerRoute = (id: string) => {
    const key = keys.get(id)!;
    const r = rec(id);
    setChatRoute(key, {
      // folder first: it tells sessions apart, and a narrow Needs-you row keeps it when the name is cut
      label: r ? `${r.cwd.split(/[\\/]/).filter(Boolean).pop() ?? r.cwd} · ${agentDef(r.agent).label}` : tr("ss.session"),
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
        patchRec(id, { status: "exited", exitCode: null, error: ev.reason || tr("ss.hermesClosed") });
      }
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

  /**
   * Start a draft: its agent in its folder, `first` as the agent's first prompt (a chat agent; the bubble shows at
   * once). A terminal agent starts in the folder and is sent nothing. From here the agent and folder are fixed.
   */
  const start = async (id: string, first?: string, startedAs?: string): Promise<boolean> => {
    const r0 = rec(id);
    if (!r0 || r0.status !== "draft" || !r0.cwd) return false;
    await ready();
    const r = rec(id);
    if (!r || r.status !== "draft") return false; // closed or started meanwhile
    picked.delete(id);
    const mode = modeOf(state.agents, r.agent);
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
      ...(account ? { account } : {}),
      ...(startedAs ? { startedAs } : {}),
      // a terminal agent that continues a conversation (DSH) names it by the id it is started with (`--resume <id>`):
      // one id per session, so Restart and Resume continue it
      ...(mode === "terminal" && CONTINUES.includes(r.agent) ? { agentSession: crypto.randomUUID() } : {}),
      // oh-my-hermes runs on the bot you were looking at (else the first bot)
      ...(mode === "hermes" ? { bot: app.selectedBot ?? app.bots[0]?.name } : {}),
    });
    const text = first?.trim() ?? "";
    // the message is sent: the draft view goes before its composer clears its own unsent text, so clear it here
    if (text) setUnsent(`agent:${id}`, "");
    // the first message names the session (as a later one would in send) until the agent or the person does
    const pt = text ? promptTitle(text) : "";
    if (pt) patchRec(id, { promptTitle: pt });
    if (mode === "chat") {
      keys.set(id, `agent:${id}`);
      registerRoute(id);
      openChat(id);
      if (!text) {
        await startAgentChat(id);
        return true;
      }
      // the first prompt shows at once and goes to the agent as soon as it runs
      const st = store();
      const key = keys.get(id)!;
      const lid = `local-s${++localSeq}`;
      st.dispatch({ type: "local.user", bot: key, id: lid, text, now: Date.now() });
      await startAgentChat(id);
      try {
        await input(id, { kind: "send", text });
      } catch (e) {
        st.dispatch({ type: "send.failed", bot: key, id: lid, error: errText(e) });
      }
    } else if (mode === "hermes") {
      await startFolderChat(id);
      if (text && rec(id)?.status === "running") await send(id, text);
    }
    return true;
  };

  /** How many times session `id`'s terminal was started again (Restart): the view keys its terminal on it. */
  const termRuns = new Map<string, number>();

  const startTerm = async (id: string, t: Term) => {
    const r = rec(id);
    if (!r) return;
    // the terminal view of a chat session does not decide the session's status; the chat does
    const ofChat = modeOf(state.agents, r.agent) !== "terminal";
    // Claude Code's terminal continues the chat's conversation; a terminal agent that continues one (DSH) its own
    const resume = r.agentSession && ((ofChat && r.agent === "claude") || (!ofChat && CONTINUES.includes(r.agent))) ? r.agentSession : undefined;
    try {
      const hostId = await host.start(
        r.agent,
        r.cwd,
        t.term.cols,
        t.term.rows,
        (d) => t.term.write(d),
        (code) => {
          t.closed = true;
          if (!ofChat) patchRec(id, { status: "exited", exitCode: code });
          t.term.write(`\r\n\x1b[2m[${code ? tr("ss.termEndedExit", { agent: agentDef(r.agent).label, code }) : tr("ss.termEnded", { agent: agentDef(r.agent).label })}]\x1b[0m\r\n`);
        },
        resume,
        accountOf(r),
      );
      t.hostId = hostId;
      if (t.closed) {
        // closed while starting
        void host.close(hostId);
        return;
      }
      if (!ofChat) patchRec(id, { status: "running" });
    } catch (e) {
      t.closed = true;
      const error = errText(e);
      if (!ofChat) patchRec(id, { status: "failed", error });
      t.term.write(`\x1b[31m${error}\x1b[0m\r\n`);
    }
  };

  const disposeTerm = (id: string) => {
    const t = terms.get(id);
    if (!t) return;
    if (t.hostId !== null && !t.closed) void host.close(t.hostId).catch(() => undefined);
    t.closed = true;
    t.term.dispose();
    t.el.remove();
    terms.delete(id);
  };

  /** Mount session `id`'s terminal into `container` (creating and starting it the first time). */
  const attach = (id: string, container: HTMLElement, theme: ITheme): (() => void) => {
    if (xtermMods) return mount(xtermMods, id, container, theme);
    let detach: (() => void) | null = null;
    let gone = false;
    void loadXterm().then((m) => {
      if (!gone) detach = mount(m, id, container, theme);
    });
    return () => {
      gone = true;
      detach?.();
    };
  };

  const mount = ([{ Terminal }, { FitAddon }]: Xterm, id: string, container: HTMLElement, theme: ITheme): (() => void) => {
    let t = terms.get(id);
    const fresh = !t;
    if (!t) {
      const el = document.createElement("div");
      el.className = "term-host";
      const term = new Terminal({
        fontFamily: getComputedStyle(document.documentElement).getPropertyValue("--mono").trim() || "monospace",
        fontSize: 12.5,
        lineHeight: 1.2,
        cursorBlink: true,
        allowProposedApi: false,
        scrollback: 5000,
        // dim text (agents use it a lot) stays readable on the light background
        minimumContrastRatio: 4.5,
        macOptionIsMeta: true,
        theme,
      });
      const fit = new FitAddon();
      term.loadAddon(fit);
      t = { term, fit, el, hostId: null, closed: false };
      terms.set(id, t);
      const tt = t;
      term.onData((d) => {
        if (tt.hostId !== null && !tt.closed) void host.write(tt.hostId, d).catch(() => undefined);
      });
      term.onResize(({ cols, rows }) => {
        if (tt.hostId !== null && !tt.closed) void host.resize(tt.hostId, cols, rows).catch(() => undefined);
      });
    }
    const tt = t;
    container.appendChild(tt.el);
    if (fresh) tt.term.open(tt.el);
    tt.term.options.theme = theme;
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
    tt.term.focus();
    return () => {
      ro.disconnect();
      if (tt.el.parentElement === container) container.removeChild(tt.el);
    };
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
    if (!r || r.view === view || modeOf(state.agents, r.agent) === "terminal") return;
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

  /**
   * Start an ended session's agent again: a chat agent in the same chat, a terminal agent in a fresh terminal, in
   * the same folder and account. Agents in `CONTINUES` continue their conversation (Claude Code `--resume`, Codex
   * `thread/resume`, OmO `--session`, DSH `--resume <id>`); the others start a new one.
   */
  const restart = async (id: string) => {
    const r = rec(id);
    if (!r || (r.status !== "exited" && r.status !== "failed")) return;
    if (modeOf(state.agents, r.agent) === "terminal") {
      // a fresh terminal: the view mounts it and starts the program (continuing the conversation, as startTerm says)
      const t = terms.get(id);
      if (t && !t.closed) return;
      disposeTerm(id);
      termRuns.set(id, (termRuns.get(id) ?? 0) + 1);
      patchRec(id, { status: "starting", error: undefined, exitCode: null, view: "terminal", paused: undefined });
      return;
    }
    if (procs.has(id) || modeOf(state.agents, r.agent) !== "chat") return;
    const resume = CONTINUES.includes(r.agent) && r.agentSession ? r.agentSession : undefined;
    patchRec(id, { status: "starting", error: undefined, exitCode: null, view: "chat", paused: undefined });
    note(id, null);
    await startAgentChat(id, resume);
  };

  /**
   * Start a session that was running when omher closed and did not continue by itself (pi, oh-my-pi, Grok,
   * oh-my-hermes, a chat whose conversation id was never reported), in the same folder and account. Once only.
   */
  const resume = async (id: string) => {
    const r = rec(id);
    if (!r?.paused || procs.has(id) || terms.has(id)) return;
    const mode = modeOf(state.agents, r.agent);
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
    if (!saved.length) return;
    const list: SessionRec[] = [];
    const again: { id: string; resume: string }[] = [];
    for (const s of saved) {
      if (s.draft) {
        // a New session chat that never started: a draft again, with its agent and folder fixed by the person
        list.push({ id: s.id, agent: s.agent, cwd: s.cwd, startedAt: s.startedAt, view: "chat", status: "draft" });
        picked.set(s.id, { agent: true, cwd: true });
        seq = Math.max(seq, Number(s.id.slice(1)) || 0);
        continue;
      }
      const mode = modeOf(state.agents, s.agent);
      const auto = s.running && mode === "chat" && continuesItself(s);
      const r: SessionRec = {
        id: s.id,
        agent: s.agent,
        cwd: s.cwd,
        startedAt: s.startedAt,
        // a chat agent comes back as its chat (its terminal view would start the program on sight)
        view: mode === "terminal" ? "terminal" : "chat",
        status: auto ? "starting" : s.failed ? "failed" : "exited",
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
        ...(s.running && !auto ? { paused: true } : {}),
      };
      list.push(r);
      fromBefore.add(s.id);
      seq = Math.max(seq, Number(s.id.slice(1)) || 0);
      if (mode !== "terminal") {
        keys.set(s.id, `agent:${s.id}`);
        // fresh ids: the agent's own message ids start over in its new process
        const msgs: Msg[] = (s.messages ?? []).map((m) => ({ id: `r-${m.id}`, role: m.role, text: m.text, ts: m.ts }));
        openChat(s.id, s.model ?? "", msgs);
      }
      if (auto) again.push({ id: s.id, resume: s.agentSession! });
    }
    set({ list: [...list, ...state.list] });
    for (const r of list) if (keys.has(r.id)) registerRoute(r.id);
    // the home folder (for `~/…` paths) and each agent's mode, as a first launch would read them
    void loadAgents();
    if (again.length) void ready().then(() => Promise.all(again.map(({ id, resume: rid }) => (procs.has(id) ? undefined : startAgentChat(id, rid)))));
  };

  /** Stop the program(s) and remove the session. */
  const close = (id: string) => {
    picked.delete(id);
    disposeTerm(id);
    void stopChat(id);
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
    set({ list, models, notes });
    const ui = store().getState().ui;
    if (ui.view === "session" && ui.session === id) {
      const next = list[Math.min(idx, list.length - 1)];
      store().actions.openSession(next ? next.id : null);
    }
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

  const setTheme = (theme: ITheme) => {
    for (const t of terms.values()) t.term.options.theme = theme;
  };

  return {
    getState: () => state,
    subscribe(fn: () => void) {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
    /** Stop whatever an earlier load of this page left running (called once at startup). */
    reset: ready,
    loadAgents,
    draft,
    setDraft,
    chooseFolder,
    start,
    attach,
    close,
    setTheme,
    setView,
    setModel,
    rename,
    restart,
    resume,
    restore,
    send,
    /** Esc / Stop: the agent's own interrupt. */
    interrupt: (id: string) => input(id, { kind: "interrupt" }).catch(() => undefined),
    /** Session `id` has a terminal in this page load (an ended one keeps its output until it is closed). */
    hasTerm: (id: string) => terms.has(id),
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
  };
}

export type SessionsStore = ReturnType<typeof createSessions>;

let singleton: SessionsStore | null = null;
export function getSessions(): SessionsStore {
  if (!singleton) {
    const s = createSessions(getHost(), getStore, accountGroups);
    singleton = s;
    setSessionKeyLookup((id) => s.chatKey(id));
    s.setNotify((ev) => notifySessionEvent(ev, getStore().getState()));
  }
  return singleton;
}

export function useSessions(): SessionsState {
  const s = getSessions();
  return useSyncExternalStore(s.subscribe, s.getState, s.getState);
}
