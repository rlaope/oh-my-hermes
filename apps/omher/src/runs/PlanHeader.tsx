// A run's header: plain text in the app's font. The plan's title, then one muted line that says where it stands,
// then the goal as one dim line.
//   Checkout redesign
//   Running · 3 of 7 done · 1 failed · 2 waiting · 12m · main Opus 5.5 · high
// No card, badge, progress bar, chips or mark. A run nobody has started says so ("Starts in 0:10" when it carries a
// start time) and offers Start now / Edit as text; like "Ask in chat" they only put a request in the message box.
import type { ReactNode } from "react";
import type { Bot } from "../lib/protocol";
import { cliName, isRepaired, span, type AgentRun, type AgentRunSummary } from "../lib/runs";
import { getStore, useStore } from "../state/store";
import { t } from "../i18n";
import { modelName, runName } from "./format";

const clock = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
const folder = (cwd: string) => cwd.replace(/[\\/]+$/, "").split(/[\\/]/).pop() ?? cwd;

export function PlanHeader({
  summary,
  run,
  bot,
  nowS,
  action,
}: {
  summary: AgentRunSummary;
  /** The run with its nodes, once loaded: the waiting count and whether anything started come from it. */
  run?: (AgentRun & { startsAt?: number }) | null;
  bot: Bot;
  nowS: number;
  /** At the right end of the title's line (the panel's "Full view ⌘⇧G"). */
  action?: ReactNode;
}) {
  const c = summary.counts;
  const waiting = run ? run.nodes.filter((n) => n.state === "waiting" || n.state === "parked").length : 0;
  const repaired = run ? run.nodes.filter((n) => isRepaired(n, run.nodes)).length : (c.repaired ?? 0);
  // "not started" is a running plan nobody has handed out yet; a cancelled or failed one says so instead
  const started = summary.state !== "running" || !run || run.nodes.some((n) => n.started !== undefined);
  const word = !started
    ? run?.startsAt !== undefined
      ? t("graph.startsIn", { t: clock(Math.max(0, run.startsAt - nowS)) })
      : t("graph.notStarted")
    : t(`graph.run.${summary.state}`);
  const name = runName(summary.id);
  const prefill = (text: string) => getStore().actions.prefill(text);
  // the bot's own runs name the main agent's model and the effort it thinks at, as a node does ("Opus 5.5 · high");
  // a CLI session's names the CLI and the folder it ran in
  const effort = useStore().chats[bot.name]?.reasoning ?? "";
  const main = [modelName(bot.model), effort === "none" ? "" : effort].filter(Boolean).join(" · ");
  const where = summary.agent ? [cliName(summary.agent), summary.cwd ? folder(summary.cwd) : ""].filter(Boolean).join(" · ") : bot.model ? `${t("graph.main")} ${main}` : "";
  return (
    <div className="ph" data-testid="run-plan" data-state={summary.state}>
      <div className="ph-top">
        <b className="ph-title" data-testid="run-plan-title" title={summary.title}>
          {summary.title}
        </b>
        {action}
      </div>
      <div className="ph-meta" data-testid="run-plan-counts">
        <span className={`ph-w ${started ? summary.state : "waiting"}`} data-testid="run-state">
          {word}
        </span>
        <span data-testid="run-progress"> · {t("graph.done", { done: c.done, total: c.nodes })}</span>
        {c.failed > 0 && <span className="ph-w failed"> · {t("graph.nfailed", { n: c.failed })}</span>}
        {repaired > 0 && <span className="ph-w repaired"> · {t("graph.nrepaired", { n: repaired })}</span>}
        {summary.state === "running" && waiting > 0 && <span> · {t("graph.nwaiting", { n: waiting })}</span>}
        {started && <span data-testid="run-plan-time"> · {span((summary.ended ?? nowS) - summary.started)}</span>}
        {where && <span data-testid="run-plan-where"> · {where}</span>}
      </div>
      {summary.goal && (
        <div className="ph-goal" data-testid="run-plan-goal" title={summary.goal}>
          {summary.goal}
        </div>
      )}
      {!started && (
        <div className="ph-act" title={t("graph.prefill")}>
          <button type="button" onClick={() => prefill(`Start run \`${name}\` now`)} data-testid="run-plan-start">
            {t("graph.startNow")}
          </button>
          <span className="ph-dim"> · </span>
          <button type="button" onClick={() => prefill(`Edit the plan of run \`${name}\`: `)} data-testid="run-plan-edit">
            {t("graph.edit")}
          </button>
          <span className="ph-dim ph-note"> · {t("graph.prefill")}</span>
        </div>
      )}
    </div>
  );
}
