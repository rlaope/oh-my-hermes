// The words and presses of a restart (restart.ts), wherever it is offered: under the pressed bot's row in the
// sidebar (on the menu's own surface, so it belongs to that row), in an offline bot's chat, in the Plugins sheet.
// 12px lines; Cancel first and quiet, the press that goes ahead outlined; nothing filled or coloured.
import type { Bot, WorkUnit } from "../lib/protocol";
import { t } from "../i18n";
import { getRestarts, useRestart } from "./restart";

/** "3m", "40s", "1h 5m": how long a unit has run. */
export function runFor(secs: number): string {
  if (secs < 60) return `${secs}s`;
  const m = Math.floor(secs / 60);
  return m < 60 ? `${m}m` : `${Math.floor(m / 60)}h ${m % 60}m`;
}

/** One live unit in two parts: whose it is and what it is in plain words, with its name when Hermes gave one (this
 *  part may be cut), and how long it has run (never cut: it is what a person weighs before Restart anyway). A line
 *  Hermes sent that the bridge could not read is "something else", still with whose it is when Hermes named it. */
export function workParts(u: WorkUnit, who?: string): { what: string; time: string | null } {
  const time = u.secs == null ? null : runFor(u.secs);
  if (u.kind === "work") return { what: who ? t("rs.w.otherOf", { bot: who }) : t("rs.w.other"), time };
  const what =
    u.kind === "chat" ? t("rs.w.chat")
    : u.kind === "cron" ? (u.name ? t("rs.w.cronNamed", { name: u.name }) : t("rs.w.cron"))
    : u.kind === "task" ? t("rs.w.task")
    : t("rs.w.run", { name: u.name ?? "" });
  return { what: who ? t("rs.w.of", { bot: who, what }) : what, time };
}

/** The same unit as one line, for its tooltip. */
export function workLine(u: WorkUnit, who?: string): string {
  const p = workParts(u, who);
  return p.time ? `${p.what}, ${p.time}` : p.what;
}

/** What a refused restart lists: one row per unit; the units Hermes said nothing readable about (no owner, no time)
 *  share one honest row at the end, "1 more thing is running", or "Hermes did not say what." when they are all. */
export function workRows(work: WorkUnit[], who: (u: WorkUnit) => string | undefined): { what: string; time: string | null; title: string }[] {
  const blank = (u: WorkUnit) => u.kind === "work" && u.secs == null && !who(u);
  const rows = work.filter((u) => !blank(u)).map((u) => ({ ...workParts(u, who(u)), title: workLine(u, who(u)) }));
  const n = work.length - rows.length;
  if (n) {
    const what = !rows.length ? t("rs.w.unsaid") : n === 1 ? t("rs.w.more1") : t("rs.w.more", { n });
    rows.push({ what, time: null, title: what });
  }
  return rows;
}

/** Hermes' refusal (what is running on that gateway) and a failure, for `bot`; nothing while idle or restarting. */
export function RestartLine({ bot, testId = "restart-line", pop = false }: { bot: Bot; testId?: string; pop?: boolean }) {
  const st = useRestart(bot.name);
  const r = getRestarts();
  if (st.step === "idle" || st.step === "restarting") return null;
  const cls = `rs-line${pop ? " rs-pop" : ""}`;
  const quiet = (label: string, id: string) => (
    <button type="button" className="rs-act" onClick={() => r.dismiss(bot.name)} data-testid={id}>
      {label}
    </button>
  );
  if (st.step === "refused") {
    const shared = st.bots.length > 1;
    const who = (u: WorkUnit) => (shared && u.bot ? (st.bots.find((b) => b.name === u.bot)?.display_name ?? u.bot) : undefined);
    return (
      <div className={cls} role="alertdialog" aria-label={t("rs.busyTitle", { bot: bot.display_name })} data-testid={testId} data-step="refused">
        <p className="rs-t">{st.work.length > 1 ? t("rs.busy", { n: st.work.length }) : t("rs.busy1")}</p>
        <ul className="rs-work" data-testid="restart-work">
          {workRows(st.work, who).map((w, i) => (
            <li key={i} title={w.title}>
              <span className="rs-what">{w.what}</span>
              {w.time && <span className="rs-for">{w.time}</span>}
            </li>
          ))}
        </ul>
        <div className="rs-acts">
          {quiet(t("rs.cancel"), "restart-cancel")}
          <button type="button" className="rs-act go" onClick={() => void r.anyway(bot.name)} data-testid="restart-anyway">
            {t("rs.anyway")}
          </button>
        </div>
      </div>
    );
  }
  return (
    <div className={cls} role="alert" data-testid={testId} data-step="failed">
      <p className="rs-t">{t("rs.failed", { bot: bot.display_name })}</p>
      {st.line && (
        <p className="rs-why" data-testid="restart-why">
          {st.line}
        </p>
      )}
      <div className="rs-acts">
        {quiet(t("page.close"), "restart-close")}
        <button type="button" className="rs-act go" onClick={() => void r.press(bot.name)} data-testid="restart-again">
          {t("rs.again")}
        </button>
      </div>
    </div>
  );
}

/** One press in place: "Restart" (or "Start" for an offline bot), outlined, then the same line as the row's. */
export function RestartAction({ bot, start = false, label, testId = "restart-press" }: { bot: Bot; start?: boolean; label?: string; testId?: string }) {
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
    <button type="button" className="rs-act go" onClick={() => void getRestarts().press(bot.name)} data-testid={testId}>
      {label ?? t(start ? "rs.start" : "rs.restart")}
    </button>
  );
}
