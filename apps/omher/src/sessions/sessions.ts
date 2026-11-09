// SESSIONS: the agent sessions omher started in this run of the app. Each one is an allow-listed agent
// (claude, codex, omh, pi, omp, grok) in a folder the person picked. Most open as a chat: Claude Code,
// Codex, pi and oh-my-pi run in their structured mode in the desktop shell (src-tauri/src/agent_chat.rs),
// oh-my-hermes opens a Hermes chat in that folder through the bridge (`folder.open`). Their events land in
// the app store under the session's own chat key, so the bot chat's timeline, activity line, cards and
// composer draw them. Grok has no verifiable chat mode, so it stays a terminal (xterm on a pseudo-terminal),
// and every chat can switch to its agent's terminal view.
//
// Sessions live only while the app runs; the last few agent+folder pairs are remembered on this computer.
import { useSyncExternalStore } from "react";
import type { ITheme, Terminal } from "@xterm/xterm";
import type { FitAddon } from "@xterm/addon-fit";
import { agentDef, parseRecent, pushRecent, RECENT_KEY, type AgentId, type AgentInfo, type Recent, type SessionRec } from "./agents";
import { getHost, type ChatEvent, type ChatInput, type SessionHost } from "./host";
import { folderKey, getStore, notifySessionEvent, onBridgeEvent, setChatRoute, setSessionKeyLookup, type Store } from "../state/store";
import type { ApprovalChoice, BridgeEvent, ClarifyAnswers } from "../lib/protocol";

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

export function createSessions(host: SessionHost, store: () => Store = getStore) {
  let state: SessionsState = { agents: null, home: null, list: [], recent: readRecent(), models: {}, notes: {} };
  const listeners = new Set<() => void>();
  const terms = new Map<string, Term>();
  const procs = new Map<string, ChatProc>();
  /** app-store chat key per session id */
  const keys = new Map<string, string>();
  let seq = 0;
  let localSeq = 0;
  let resetDone: Promise<void> | null = null;
  let notify: ((ev: BridgeEvent) => void) | null = null;

  const set = (patch: Partial<SessionsState>) => {
    state = { ...state, ...patch };
    for (const l of [...listeners]) l();
  };
  const rec = (id: string) => state.list.find((s) => s.id === id);
  const patchRec = (id: string, p: Partial<SessionRec>) => set({ list: state.list.map((s) => (s.id === id ? { ...s, ...p } : s)) });
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
    } catch {
      set({ agents: state.agents ?? [] });
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

  const onAgentEvent = (id: string, proc: ChatProc) => (ev: ChatEvent) => {
    if (procs.get(id) !== proc && ev.event !== "exit") return; // an old process of this session (Terminal toggle)
    switch (ev.event) {
      case "session.info": {
        const p: Partial<SessionRec> = {};
        if (typeof ev.agent_session === "string" && ev.agent_session) p.agentSession = ev.agent_session;
        if (typeof ev.model === "string" && ev.model) p.model = ev.model;
        patchRec(id, p);
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
        const code = typeof ev.code === "number" ? ev.code : null;
        const error = typeof ev.error === "string" ? ev.error.trim() : "";
        patchRec(id, { status: "exited", exitCode: code, ...(error ? { error } : {}) });
        return;
      }
      default:
        dispatchChat(id, ev);
    }
  };

  /** Mark the session's chat loaded and empty in the store, so the timeline says hi instead of loading. */
  const openChat = (id: string, model = "") => {
    const key = keys.get(id)!;
    if (store().getState().chats[key]?.loaded) return;
    store().dispatch({
      type: "chat.opened",
      bot: key,
      res: { session_id: key, messages: [], running: false, model, provider: "", reasoning: "" },
      now: Date.now(),
    });
  };

  const startAgentChat = async (id: string, resume?: string) => {
    const r = rec(id)!;
    const proc: ChatProc = { kind: "agent" };
    procs.set(id, proc);
    try {
      proc.hostId = await host.chatStart(r.agent, r.cwd, onAgentEvent(id, proc), resume);
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
      if (!bot) throw new Error("No Hermes bot to run oh-my-hermes on");
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
    if (!proc || !r) throw new Error(`${r ? agentDef(r.agent).label : "The agent"} is not running`);
    if (proc.kind === "agent") {
      if (proc.hostId === undefined) throw new Error("still starting");
      await host.chatInput(proc.hostId, i);
      return;
    }
    const a = store().actions;
    const bot = proc.bot!;
    const fid = proc.fid;
    if (!fid) throw new Error("still starting");
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
      label: r ? `${agentDef(r.agent).label} · ${r.cwd.split(/[\\/]/).filter(Boolean).pop() ?? r.cwd}` : "Session",
      open: () => store().actions.openSession(id),
      send: (text) => send(id, text),
      interrupt: () => input(id, { kind: "interrupt" }),
      approve: (request_id: string, choice: ApprovalChoice) => input(id, { kind: "approve", request_id, choice }),
      clarify: (request_id: string, answer: string | ClarifyAnswers) => input(id, { kind: "clarify", request_id, answer }),
    });
  };

  // A Hermes folder chat ends when the bridge says so (its gateway went away).
  onBridgeEvent((ev) => {
    if (ev.event !== "folder.closed" || !ev.session) return;
    for (const [id, p] of procs) {
      if (p.kind === "folder" && p.bot === ev.bot && p.fid === ev.session) {
        procs.delete(id);
        patchRec(id, { status: "exited", exitCode: null, error: ev.reason || "Hermes closed this chat" });
      }
    }
  });

  // ---- sessions -----------------------------------------------------------------------------

  /** Ask for a folder (default: the last one used, else home) and start `agent` there. */
  const launch = async (agent: AgentId, cwd?: string): Promise<string | null> => {
    await ready();
    const home = state.home ?? (await host.home().catch(() => ""));
    const folder = cwd ?? (await host.pickFolder(state.recent[0]?.cwd || home));
    if (!folder) return null;
    const id = `s${++seq}`;
    const mode = modeOf(state.agents, agent);
    const app = store().getState();
    const r: SessionRec = {
      id,
      agent,
      cwd: folder,
      startedAt: Date.now(),
      status: "starting",
      view: mode === "terminal" ? "terminal" : "chat",
      // oh-my-hermes runs on the bot you were looking at (else the first bot)
      ...(mode === "hermes" ? { bot: app.selectedBot ?? app.bots[0]?.name } : {}),
    };
    const recent = pushRecent(state.recent, { agent, cwd: folder, at: r.startedAt });
    try {
      localStorage.setItem(RECENT_KEY, JSON.stringify(recent));
    } catch {
      /* no storage */
    }
    set({ list: [r, ...state.list], recent, home: state.home ?? home });
    if (mode === "chat") {
      keys.set(id, `agent:${id}`);
      registerRoute(id);
      openChat(id);
      void startAgentChat(id);
    } else if (mode === "hermes") {
      void startFolderChat(id);
    }
    store().actions.openSession(id);
    return id;
  };

  const startTerm = async (id: string, t: Term) => {
    const r = rec(id);
    if (!r) return;
    // the terminal view of a chat session does not decide the session's status; the chat does
    const ofChat = modeOf(state.agents, r.agent) !== "terminal";
    // Claude Code's terminal continues the chat's conversation
    const resume = ofChat && r.agent === "claude" && r.agentSession ? r.agentSession : undefined;
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
          t.term.write(`\r\n\x1b[2m[${agentDef(r.agent).label} ended${code ? ` with exit ${code}` : ""}]\x1b[0m\r\n`);
        },
        resume,
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
      }
      return;
    }
    patchRec(id, { view });
  };

  /** Stop the program(s) and remove the session. */
  const close = (id: string) => {
    disposeTerm(id);
    void stopChat(id);
    const key = keys.get(id);
    if (key) setChatRoute(key, null);
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
      note(id, `Model not changed: ${errText(e)}`);
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
    launch,
    attach,
    close,
    setTheme,
    setView,
    setModel,
    send,
    /** Esc / Stop: the agent's own interrupt. */
    interrupt: (id: string) => input(id, { kind: "interrupt" }).catch(() => undefined),
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
    const s = createSessions(getHost());
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
