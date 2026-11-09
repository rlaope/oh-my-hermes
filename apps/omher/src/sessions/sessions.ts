// SESSIONS: the terminal sessions omher started in this run of the app. Each one is an allow-listed agent
// (claude, codex, omh, pi, omp) in a folder the person picked, running in a pseudo-terminal through the
// SessionHost. Sessions live only while the app runs; the last few agent+folder pairs are remembered on
// this computer for a quick relaunch.
import { useSyncExternalStore } from "react";
import type { ITheme, Terminal } from "@xterm/xterm";
import type { FitAddon } from "@xterm/addon-fit";
import { agentDef, parseRecent, pushRecent, RECENT_KEY, type AgentId, type AgentInfo, type Recent, type SessionRec } from "./agents";
import { getHost, type SessionHost } from "./host";
import { getStore } from "../state/store";

export interface SessionsState {
  /** null until the first look-up */
  agents: AgentInfo[] | null;
  home: string | null;
  list: SessionRec[];
  recent: Recent[];
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

const readRecent = () => {
  try {
    return parseRecent(typeof localStorage !== "undefined" ? localStorage.getItem(RECENT_KEY) : null);
  } catch {
    return [];
  }
};

export function createSessions(host: SessionHost) {
  let state: SessionsState = { agents: null, home: null, list: [], recent: readRecent() };
  const listeners = new Set<() => void>();
  const terms = new Map<string, Term>();
  let seq = 0;
  let resetDone: Promise<void> | null = null;

  const set = (patch: Partial<SessionsState>) => {
    state = { ...state, ...patch };
    for (const l of [...listeners]) l();
  };
  const patchRec = (id: string, p: Partial<SessionRec>) =>
    set({ list: state.list.map((s) => (s.id === id ? { ...s, ...p } : s)) });

  const ready = () => (resetDone ??= host.reset().catch(() => undefined));

  const loadAgents = async () => {
    try {
      const [agents, home] = await Promise.all([host.agents(), state.home ? Promise.resolve(state.home) : host.home()]);
      set({ agents, home });
    } catch {
      set({ agents: state.agents ?? [] });
    }
  };

  /** Ask for a folder (default: the last one used, else home) and start `agent` there. */
  const launch = async (agent: AgentId, cwd?: string): Promise<string | null> => {
    await ready();
    const home = state.home ?? (await host.home().catch(() => ""));
    const folder = cwd ?? (await host.pickFolder(state.recent[0]?.cwd || home));
    if (!folder) return null;
    const id = `s${++seq}`;
    const rec: SessionRec = { id, agent, cwd: folder, startedAt: Date.now(), status: "starting" };
    const recent = pushRecent(state.recent, { agent, cwd: folder, at: rec.startedAt });
    try {
      localStorage.setItem(RECENT_KEY, JSON.stringify(recent));
    } catch {
      /* no storage */
    }
    set({ list: [rec, ...state.list], recent, home: state.home ?? home });
    getStore().actions.openSession(id);
    return id;
  };

  const start = async (id: string, t: Term) => {
    const rec = state.list.find((s) => s.id === id);
    if (!rec) return;
    try {
      const hostId = await host.start(
        rec.agent,
        rec.cwd,
        t.term.cols,
        t.term.rows,
        (d) => t.term.write(d),
        (code) => {
          t.closed = true;
          patchRec(id, { status: "exited", exitCode: code });
          t.term.write(`\r\n\x1b[2m[${agentDef(rec.agent).label} ended${code ? ` with exit ${code}` : ""}]\x1b[0m\r\n`);
        },
      );
      t.hostId = hostId;
      if (t.closed) {
        // closed while starting
        void host.close(hostId);
        return;
      }
      patchRec(id, { status: "running" });
    } catch (e) {
      t.closed = true;
      const error = typeof e === "string" ? e : e instanceof Error ? e.message : String(e);
      patchRec(id, { status: "failed", error });
      t.term.write(`\x1b[31m${error}\x1b[0m\r\n`);
    }
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
    if (fresh) void ready().then(() => start(id, tt));
    const ro = new ResizeObserver(refit);
    ro.observe(container);
    tt.term.focus();
    return () => {
      ro.disconnect();
      if (tt.el.parentElement === container) container.removeChild(tt.el);
    };
  };

  /** Stop the program (if running) and remove the session. */
  const close = (id: string) => {
    const t = terms.get(id);
    if (t) {
      if (t.hostId !== null && !t.closed) void host.close(t.hostId).catch(() => undefined);
      t.closed = true;
      t.term.dispose();
      t.el.remove();
      terms.delete(id);
    }
    const idx = state.list.findIndex((s) => s.id === id);
    const list = state.list.filter((s) => s.id !== id);
    set({ list });
    const ui = getStore().getState().ui;
    if (ui.view === "session" && ui.session === id) {
      const next = list[Math.min(idx, list.length - 1)];
      getStore().actions.openSession(next ? next.id : null);
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
  };
}

export type SessionsStore = ReturnType<typeof createSessions>;

let singleton: SessionsStore | null = null;
export function getSessions(): SessionsStore {
  return (singleton ??= createSessions(getHost()));
}

export function useSessions(): SessionsState {
  const s = getSessions();
  return useSyncExternalStore(s.subscribe, s.getState, s.getState);
}
