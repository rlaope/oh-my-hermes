// A run's header as the OMH TUI prints it: three plain lines of text, then the goal as one dim line.
//   OMH / DAG · 7 tasks
//   Checkout redesign · main opus-5-5
//   Running · Done 3/7 · 1 failed · 2 waiting · 12m
// No card, badge, progress bar or chips. A run nobody has started says so ("Starts in 0:10" when it carries a start
// time) and offers Start now / Edit as text; like "Ask in chat" they only put a request in the message box.
import type { ReactNode } from "react";
import type { Bot } from "../lib/protocol";
import { cliName, isRepaired, span, type AgentRun, type AgentRunSummary } from "../lib/runs";
import { getStore } from "../state/store";
import { t } from "../i18n";
import { shortModel } from "./boxView";
import { runName } from "./format";

const clock = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
const folder = (cwd: string) => cwd.replace(/[\\/]+$/, "").split(/[\\/]/).pop() ?? cwd;

/** "OMH / DAG", "Hermes / helpers", "Claude / subagents": where the run's tasks come from. */
export const sourceOf = (run: Pick<AgentRunSummary, "kind" | "agent">) =>
  run.agent ? t("graph.subagents", { agent: cliName(run.agent) }) : run.kind === "delegate" ? t("graph.helpers") : t("graph.dag");

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
  /** At the right end of the first line (the panel's "Full view ⌘⇧G"). */
  action?: ReactNode;
}) {
  const c = summary.counts;
  const waiting = run ? run.nodes.filter((n) => n.state === "waiting" || n.state === "parked").length : 0;
  const repaired = run ? run.nodes.filter((n) => isRepaired(n, run.nodes)).length : (c.repaired ?? 0);
  const started = !run || run.nodes.some((n) => n.started !== undefined);
  const word = !started
    ? run?.startsAt !== undefined
      ? t("graph.startsIn", { t: clock(Math.max(0, run.startsAt - nowS)) })
      : t("graph.notStarted")
    : t(`graph.run.${summary.state}`);
  const name = runName(summary.id);
  const prefill = (text: string) => getStore().actions.prefill(text);
  // the bot's own runs name its model; a CLI session's names the folder it ran in
  const where = summary.agent ? (summary.cwd ? folder(summary.cwd) : "") : bot.model ? `${t("graph.main")} ${shortModel(bot.model)}` : "";
  return (
    <div className="ph" data-testid="run-plan" data-state={summary.state}>
      <div className="ph-l">
        <span className="ph-k" data-testid="run-plan-source">
          {sourceOf(summary)} · {t(c.nodes === 1 ? "graph.tasks.one" : "graph.tasks", { n: c.nodes })}
        </span>
        {action}
      </div>
      <div className="ph-l" title={summary.title}>
        <b className="ph-title" data-testid="run-plan-title">
          {summary.title}
        </b>
        {where && <span className="ph-dim"> · {where}</span>}
      </div>
      <div className="ph-l" data-testid="run-plan-counts">
        <span className={`ph-w ${started ? summary.state : "waiting"}`} data-testid="run-state">
          {word}
        </span>
        <span data-testid="run-progress"> · {t("graph.done", { done: c.done, total: c.nodes })}</span>
        {c.failed > 0 && <span className="ph-w failed"> · {t("graph.nfailed", { n: c.failed })}</span>}
        {repaired > 0 && <span className="ph-w repaired"> · {t("graph.nrepaired", { n: repaired })}</span>}
        {summary.state === "running" && waiting > 0 && <span> · {t("graph.nwaiting", { n: waiting })}</span>}
        {started && (
          <span data-testid="run-plan-time"> · {span((summary.ended ?? nowS) - summary.started)}</span>
        )}
      </div>
      {summary.goal && (
        <div className="ph-l ph-goal" data-testid="run-plan-goal" title={summary.goal}>
          {summary.goal}
        </div>
      )}
      {!started && (
        <div className="ph-l ph-act" title={t("graph.prefill")}>
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
