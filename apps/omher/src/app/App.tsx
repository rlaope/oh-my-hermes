import { useEffect } from "react";
import "../theme/tokens.css";
import "../theme/base.css";
import "./app.css";
import { useStore } from "../state/store";
import { slots } from "../features";
import { Sidebar } from "../sidebar/Sidebar";
import { Chat } from "../chat/Chat";
import { DetailsFallback } from "./DetailsFallback";
import { SettingsView } from "./SettingsView";
import { SessionView } from "../sessions/SessionView";
import { useLookAttributes, useThemeAttribute } from "./theme";
import { useShortcuts } from "./shortcuts";

export function App() {
  const s = useStore();
  useThemeAttribute(s.ui.theme);
  useLookAttributes(s.ui.look);
  useShortcuts();
  useEffect(() => {
    void s.init();
    // init is idempotent in the store; run once on mount
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const bot = s.bots.find((b) => b.name === s.selectedBot) ?? null;
  const panelOpen = s.ui.panelOpen && s.ui.view === "chat" && !!bot;
  const Details = slots.detailsPanel;
  const close = () => s.togglePanel(false);

  return (
    <div className={`window${panelOpen ? " panel-open" : ""}`} data-testid="window">
      <Sidebar />
      <main className="main">
        {s.ui.view === "settings" ? <SettingsView /> : s.ui.view === "session" ? <SessionView /> : <Chat />}
      </main>
      <aside className="details" aria-hidden={!panelOpen} data-testid="details">
        {bot &&
          (Details ? (
            <Details bot={bot} open={panelOpen} onClose={close} />
          ) : (
            <DetailsFallback bot={bot} onClose={close} />
          ))}
      </aside>
    </div>
  );
}
