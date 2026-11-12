// The words and presses of one bot's restart (restart.ts), wherever it is offered: under the bot's row in the
// sidebar, in an offline bot's chat, in the Plugins sheet. Plain 12px lines, borderless text actions, Cancel first.
import type { Bot } from "../lib/protocol";
import { t } from "../i18n";
import { getRestarts, useRestart } from "./restart";

/** The confirm, the busy refusal and a failure, for `bot`; nothing while idle or restarting. */
export function RestartLine({ bot, testId = "restart-line" }: { bot: Bot; testId?: string }) {
  const st = useRestart(bot.name);
  const r = getRestarts();
  if (st.step === "idle" || st.step === "restarting") return null;
  const cancel = (
    <button type="button" className="rs-act" onClick={() => r.dismiss(bot.name)} data-testid="restart-cancel">
      {t("rs.cancel")}
    </button>
  );
  if (st.step === "confirm") {
    const names = st.others.map((o) => o.display_name).join(", ");
    return (
      <div className="rs-line" role="alertdialog" aria-label={t("rs.restart")} data-testid={testId} data-step="confirm">
        <p className="rs-t">{t("rs.takesAlong", { bot: bot.display_name, list: names, n: st.others.length })}</p>
        <div className="rs-acts">
          {cancel}
          <button type="button" className="rs-act" onClick={() => void r.confirm(bot.name)} data-testid="restart-go">
            {t("rs.restart")}
          </button>
        </div>
      </div>
    );
  }
  if (st.step === "refused") {
    return (
      <div className="rs-line" role="alertdialog" aria-label={t("rs.busyTitle", { bot: bot.display_name })} data-testid={testId} data-step="refused">
        <p className="rs-t">{t("rs.busy", { bot: bot.display_name })}</p>
        <ul className="rs-work" data-testid="restart-work">
          {st.lines.map((l, i) => (
            <li key={i}>{l}</li>
          ))}
        </ul>
        <div className="rs-acts">
          {cancel}
          <button type="button" className="rs-act" onClick={() => void r.anyway(bot.name)} data-testid="restart-anyway">
            {t("rs.anyway")}
          </button>
        </div>
      </div>
    );
  }
  return (
    <div className="rs-line" role="alert" data-testid={testId} data-step="failed">
      <p className="rs-t">{t("rs.failed", { bot: bot.display_name })}</p>
      {st.line && (
        <p className="rs-why" data-testid="restart-why">
          {st.line}
        </p>
      )}
      <div className="rs-acts">
        {cancel}
        <button type="button" className="rs-act" onClick={() => void r.press(bot.name)} data-testid="restart-again">
          {t("rs.again")}
        </button>
      </div>
    </div>
  );
}

/** One press in place: "Restart" (or "Start" for an offline bot), then the same line as the row's. */
export function RestartAction({ bot, start = false, testId = "restart-press" }: { bot: Bot; start?: boolean; testId?: string }) {
  const st = useRestart(bot.name);
  if (st.step === "restarting") {
    return (
      <span className="rs-wait" role="status" data-testid={`${testId}-wait`}>
        {t(start ? "rs.starting" : "rs.restarting")}
      </span>
    );
  }
  if (st.step !== "idle") return null;
  return (
    <button type="button" className="rs-act" onClick={() => void getRestarts().press(bot.name)} data-testid={testId}>
      {t(start ? "rs.start" : "rs.restart")}
    </button>
  );
}
