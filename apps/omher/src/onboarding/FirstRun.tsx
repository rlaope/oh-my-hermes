// First run: until the person dismisses it (`omher.onboarded=1` in localStorage), two small cards say what Bots
// and Sessions are, each with one quiet button of the same look ("Message a bot" focuses the first bot's composer,
// "New session" opens the SESSIONS + menu), and an empty Bots section carries one muted line. The cards show
// only where there is no conversation yet (the empty main area, a chat with no messages), never above a chat's
// history; one × closes both.
import { useSyncExternalStore } from "react";
import "./firstrun.css";
import { t } from "../i18n";
import { selectSidebarBots, useStore } from "../state/store";
import { openNewSessionMenu } from "../sessions/SessionsSection";
import { CloseIcon, IconButton } from "../ui";

export const ONBOARDED_KEY = "omher.onboarded";

const fns = new Set<() => void>();
const read = (): boolean => {
  try {
    return typeof localStorage === "undefined" || localStorage.getItem(ONBOARDED_KEY) === "1";
  } catch {
    return true;
  }
};
let done = read();

/** True once the first-run cards were dismissed on this computer. */
export function useOnboarded(): boolean {
  return useSyncExternalStore(
    (f) => {
      fns.add(f);
      return () => fns.delete(f);
    },
    () => done,
    () => done,
  );
}

export function dismissOnboarding(): void {
  try {
    localStorage.setItem(ONBOARDED_KEY, "1");
  } catch {
    // no storage: the cards still go for this run
  }
  done = true;
  for (const f of [...fns]) f();
}

/** The two first-run cards, or nothing once dismissed. Callers render it only where no conversation is shown. */
export function FirstRun() {
  const s = useStore();
  const onboarded = useOnboarded();
  if (onboarded) return null;
  // the bot whose empty chat holds the cards, else the first bot in the sidebar
  const first = s.bots.find((b) => b.name === s.selectedBot) ?? selectSidebarBots(s)[0];
  const messageBot = async () => {
    if (!first) return;
    if (s.selectedBot !== first.name || s.ui.view !== "chat") await s.selectBot(first.name);
    // the composer of the chat just shown
    requestAnimationFrame(() => document.querySelector<HTMLTextAreaElement>(`[data-pane="${CSS.escape(first.name)}"] [data-testid=composer]`)?.focus());
  };
  return (
    <section className="onb" aria-label={t("onb.label")} data-testid="onboarding">
      <div className="onb-card" data-testid="onb-bots">
        <b className="onb-t">{t("onb.bots.title")}</b>
        <p className="onb-p">{t("onb.bots.body")}</p>
        <button type="button" className="onb-btn" onClick={() => void messageBot()} disabled={!first} data-testid="onb-message">
          {t("onb.bots.action")}
        </button>
      </div>
      <div className="onb-card" data-testid="onb-sessions">
        <b className="onb-t">{t("onb.sessions.title")}</b>
        <p className="onb-p">{t("onb.sessions.body")}</p>
        <button type="button" className="onb-btn" onClick={openNewSessionMenu} data-testid="onb-session">
          {t("onb.sessions.action")}
        </button>
      </div>
      <IconButton label={t("onb.dismiss")} className="onb-x" onClick={dismissOnboarding} data-testid="onb-dismiss">
        <CloseIcon />
      </IconButton>
    </section>
  );
}

/** One muted line under an empty sidebar section, shown on first run only. */
export function FirstRunHint({ text, testId }: { text: string; testId: string }) {
  const onboarded = useOnboarded();
  if (onboarded) return null;
  return (
    <div className="onb-hint" data-testid={testId}>
      {text}
    </div>
  );
}
