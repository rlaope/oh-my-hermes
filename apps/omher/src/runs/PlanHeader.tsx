// A run's header: plain text in the app's font, no card. The plan's title leads (14px, ink); under it, close by,
// where it stands and who runs it; then, a little apart, the goal in two lines at most.
//   Docs dark mode                                                    [⤢]
//   ● Running · 2 of 6 done · 1 waiting · 9m · 1 needs you
//   [Claude] Opus 5.5 · high effort · main
//   Ship a dark mode for the docs site: tokens, a toggle, contrast…
// No badge, progress bar, chips or section box. A run nobody has started says so ("Starts in 0:10" when it carries
// a start time) and offers Start now / Edit as text; like "Ask in chat" they only put a request in the message box.
import type { ReactNode } from "react";
import type { Bot } from "../lib/protocol";
import { cliName, isRepaired, span, type AgentRun, type AgentRunSummary } from "../lib/runs";
import { getStore, selectAsks, useStore } from "../state/store";
import { t } from "../i18n";
import { AgentIcon, ModelIcon } from "../ui";
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
  /** At the right end of the title's row (the panel's full-view button). */
  action?: ReactNode;
}) {
  const s = useStore();
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
  // what waits on the person in this bot's chat while the plan runs: the newest opens, as from the sidebar's strip
  const asks = summary.agent || summary.state !== "running" ? [] : selectAsks(s).filter((a) => a.bot === bot.name);
  const newest = asks.reduce<(typeof asks)[number] | null>((a, b) => (!a || b.ts > a.ts ? b : a), null);
  // who runs it: the bot's own runs name the main agent's model and the effort it thinks at; a CLI session's names
  // the CLI and the folder it ran in
  const effort = s.chats[bot.name]?.reasoning ?? "";
  const who = summary.agent
    ? [cliName(summary.agent), summary.cwd ? folder(summary.cwd) : ""].filter(Boolean).join(" · ")
    : bot.model
      ? [modelName(bot.model), effort && effort !== "none" ? t("graph.effort", { e: effort }) : "", t("graph.main")].filter(Boolean).join(" · ")
      : "";
  const dot = started ? summary.state : "waiting";
  return (
    <div className="ph" data-testid="run-plan" data-state={summary.state}>
      <div className="ph-top">
        <b className="ph-title" data-testid="run-plan-title" title={summary.title}>
          {summary.title}
        </b>
        {action}
      </div>
      <div className="ph-meta" data-testid="run-plan-counts">
        <span className={`ph-dot ${dot}`} aria-hidden="true" data-testid="run-dot" />
        <span className={`ph-w ${dot}`} data-testid="run-state">
          {word}
        </span>
        <span data-testid="run-progress"> · {t("graph.done", { done: c.done, total: c.nodes })}</span>
        {c.failed > 0 && <span className="ph-w failed"> · {t("graph.nfailed", { n: c.failed })}</span>}
        {repaired > 0 && <span className="ph-w repaired"> · {t("graph.nrepaired", { n: repaired })}</span>}
        {summary.state === "running" && waiting > 0 && <span> · {t("graph.nwaiting", { n: waiting })}</span>}
        {started && <span data-testid="run-plan-time"> · {span((summary.ended ?? nowS) - summary.started)}</span>}
        {newest && (
          <span>
            {" · "}
            <button type="button" className="ph-needs" onClick={() => void s.jumpToAsk(newest.bot, newest.item.id)} data-testid="run-plan-needs">
              {t("graph.needs", { n: asks.length })}
            </button>
          </span>
        )}
      </div>
      {who && (
        <div className="ph-who" data-testid="run-plan-where" title={who}>
          {summary.agent ? <AgentIcon id={summary.agent} size={12} /> : <ModelIcon model={bot.model} provider={bot.provider} size={12} />}
          <span className="ph-who-t">{who}</span>
        </div>
      )}
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
