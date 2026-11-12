// First run: until the person dismisses it (`omher.onboarded=1` in localStorage), two small cards say what Bots
// and Sessions are, each with one quiet button of the same look ("Message a bot" focuses the first bot's composer,
// "New session" opens the SESSIONS + menu), and an empty Bots section carries one muted line. The cards show
// only where there is no conversation yet (the empty main area, a chat with no messages), never above a chat's
// history; one × closes both. A Language row under the cards shows the language picked from the system (or
// English) and changes it on the spot, the same control as Settings › General › Language.
// A person who has Hermes but not oh-my-hermes gets a third card, marked recommended: what oh-my-hermes adds, and an
// Install button that runs the first-run screen's fixed installer (the shell's one command) with its output shown
// the same way. When it ends well the card goes (the + row then reads "oh-my-hermes"); when it fails the card keeps
// the last line and offers Install again. The + menu keeps one quiet "Add oh-my-hermes" line after the × too.
import { useEffect, useSyncExternalStore } from "react";
import "./firstrun.css";
import { LANG_NAMES, LANGS, t, type Lang } from "../i18n";
import { Seg } from "../chat/model/Seg";
import { selectSidebarBots, useStore } from "../state/store";
import { openNewSessionMenu } from "../sessions/SessionsSection";
import { hermesOnly } from "../sessions/agents";
import { getSessions, useSessions } from "../sessions/sessions";
import { getAddOmh, useAddOmh } from "../sessions/addOmh";
import { InstallLog } from "../app/BridgeGate";
import { CloseIcon, IconButton, Spinner } from "../ui";

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
  const ss = useSessions();
  // which agents are here decides the third card; read once, as the SESSIONS section does
  useEffect(() => {
    if (!onboarded && ss.agents === null) void getSessions().loadAgents();
  }, [onboarded, ss.agents]);
  const offer = hermesOnly(ss.agents);
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
    <section className={`onb${offer ? " onb-3" : ""}`} aria-label={t("onb.label")} data-testid="onboarding">
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
      {offer && <OmhCard />}
      <div className="onb-lang" data-testid="onb-lang">
        <span className="onb-lang-t">{t("lang.title")}</span>
        <Seg
          small
          label={t("lang.title")}
          value={s.ui.lang}
          onChange={(v) => s.setLanguage(v as Lang)}
          options={LANGS.map((l) => ({ value: l, label: LANG_NAMES[l] }))}
          testId="onb-language"
        />
      </div>
      <IconButton label={t("onb.dismiss")} className="onb-x" onClick={dismissOnboarding} data-testid="onb-dismiss">
        <CloseIcon />
      </IconButton>
    </section>
  );
}

/** The third card for a person with Hermes but not oh-my-hermes: what it adds, recommended, and Install. */
function OmhCard() {
  const add = useAddOmh();
  const running = add.phase === "running";
  const failed = add.phase === "failed";
  return (
    <div className="onb-card onb-omh" data-testid="onb-omh" data-phase={add.phase}>
      <b className="onb-t">
        oh-my-hermes
        <span className="onb-rec" data-testid="onb-omh-rec">
          {t("onb.omh.rec")}
        </span>
      </b>
      <p className="onb-p">{running ? t("omh.add.running") : t("onb.omh.body")}</p>
      {running && <InstallLog lines={add.lines} compact testId="onb-omh-log" />}
      {failed && add.error && (
        <p className="onb-err" role="status" title={add.error} data-testid="onb-omh-error">
          {add.error}
        </p>
      )}
      <button
        type="button"
        className="onb-btn"
        disabled={running}
        onClick={() => void getAddOmh().run()}
        title={t("omh.add.tip")}
        data-testid="onb-omh-install"
      >
        {running && <Spinner size={11} label={t("gate.installing")} />}
        {running ? t("gate.installing") : failed ? t("gate.again") : t("gate.install")}
      </button>
    </div>
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
