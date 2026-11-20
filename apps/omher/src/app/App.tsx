import { lazy, Suspense, useEffect, useMemo } from "react";
import "../theme/tokens.css";
import "../theme/base.css";
import "./app.css";
import { getStore, useStore } from "../state/store";
import { MentionContext, type Mentions } from "../chat/parts/Mention";
import { botResolver } from "../chat/parts/mentions";
import { slots } from "../features";
import { Sidebar } from "../sidebar/Sidebar";
import { Chat } from "../chat/Chat";
import { DetailsFallback } from "./DetailsFallback";
import { PanelResizer } from "./PanelResizer";
import { SettingsView } from "./SettingsView";
import { AutomationsPage } from "../pages/Automations";
import { PluginsPage } from "../pages/Plugins";
import { TasksPage } from "../tasks/TasksPage";
import { useLookAttributes, useThemeAttribute } from "./theme";
import { useShortcuts } from "./shortcuts";
import { useAsksBadge } from "./badge";
import { startPeers } from "../peers/links";
import { startPower } from "../lib/power";
import { setTerminalCwd, useTermPanel } from "../terminal/state";

// The terminal view (and xterm with it) loads when a session is first opened.
const SessionView = lazy(() => import("../sessions/SessionView").then((m) => ({ default: m.SessionView })));
const SessionPanel = lazy(() => import("../sessions/SessionPlans").then((m) => ({ default: m.SessionPanel })));
// The bottom terminal panel (Ctrl+`) loads the first time it opens, then stays mounted so hidden shells keep running.
const TerminalPanel = lazy(() => import("../terminal/Panel").then((m) => ({ default: m.TerminalPanel })));

export function App() {
  const s = useStore();
  useThemeAttribute(s.ui.theme);
  useLookAttributes(s.ui.look);
  useShortcuts();
  useAsksBadge();
  const term = useTermPanel();
  useEffect(() => {
    void s.init();
    void startPeers();
    // close = hide to the tray, keep awake while agents work (Settings › General)
    void startPower();
    // init is idempotent in the store; run once on mount
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const bot = s.bots.find((b) => b.name === s.selectedBot) ?? null;
  // the terminal panel's next tab starts in the open thread's folder (the bot's main chat: home)
  const threadCwd = s.ui.view === "chat" && bot && s.ui.thread ? ((s.threads[bot.name] ?? []).find((r) => r.thread === s.ui.thread)?.cwd ?? null) : null;
  useEffect(() => setTerminalCwd(threadCwd), [threadCwd]);
  // `@name` in any chat text opens that bot's chat; the open chat's own bot is not a link
  const current = s.ui.view === "chat" ? s.selectedBot : null;
  const mentions = useMemo<Mentions>(() => {
    const names = new Map(s.bots.map((b) => [b.name, b.display_name || b.name]));
    return {
      resolve: botResolver(s.bots),
      nameOf: (b) => names.get(b) ?? b,
      current,
      open: (b) => {
        const st = getStore();
        if (st.getState().ui.panelMax) st.actions.setPanelMax(false);
        void st.actions.selectBot(b);
      },
    };
  }, [s.bots, current]);
  // a bot's chat shows its Details and Plans; a SESSIONS chat shows Plans for that session alone
  const onSession = s.ui.view === "session" && !!s.ui.session;
  const panelOpen = s.ui.panelOpen && ((s.ui.view === "chat" && !!bot) || onSession);
  // maximised in place: the panel takes the chat column's room; the chat stays mounted (draft, scroll, stream)
  const panelMax = panelOpen && !onSession && s.ui.panelMax;
  const Details = slots.detailsPanel;
  const close = () => s.togglePanel(false);

  return (
    <MentionContext.Provider value={mentions}>
    <div className={`window${panelOpen ? " panel-open" : ""}${panelMax ? " panel-max" : ""}`} data-testid="window" lang={s.ui.lang}>
      <Sidebar />
      <main className="main" inert={panelMax} aria-hidden={panelMax || undefined}>
        {s.ui.view === "settings" ? <SettingsView /> : s.ui.view === "automations" ? (
          <AutomationsPage />
        ) : s.ui.view === "plugins" ? (
          <PluginsPage />
        ) : s.ui.view === "tasks" ? (
          <TasksPage />
        ) : s.ui.view === "session" ? (
          <Suspense fallback={null}>
            <SessionView />
          </Suspense>
        ) : <Chat />}
        {term.mounted && (
          <Suspense fallback={null}>
            <TerminalPanel />
          </Suspense>
        )}
      </main>
      {/* inert while closed: the off-screen panel takes no focus and no clicks */}
      <aside className="details" aria-hidden={!panelOpen} inert={!panelOpen} data-testid="details">
        <PanelResizer open={panelOpen} tab={onSession ? "runs" : s.ui.panelTab} max={panelMax} />
        {onSession ? (
          // mounted only while open: a closed panel reads nothing, and reopening it reads the session's run afresh
          panelOpen && (
            <Suspense fallback={null}>
              <SessionPanel onClose={close} />
            </Suspense>
          )
        ) : bot &&
          (Details ? (
            <Details bot={bot} open={panelOpen} onClose={close} />
          ) : (
            <DetailsFallback bot={bot} onClose={close} />
          ))}
      </aside>
    </div>
    </MentionContext.Provider>
  );
}
