// The one activity line per turn (design rule 6). Tool/skill calls never get their own timeline rows:
// while the turn runs, this line's text slides up in place; when it ends it collapses to
// "Worked for 2m 41s · 6 steps" and a click opens one detail row per step.
import { useState } from "react";
import type { SlotProps } from "../../features";
import { activityText, getStore, liveLabel, subagentEnded, THINKING, WORKING, type Step, type Turn } from "../../state/store";
import { ChevronRight, Spinner } from "../../ui";
import { elapsed } from "../../app/time";
import { useClock } from "../../app/clock";
import { t, t as tr, tx, type Key } from "../../i18n";
import { FanoutCard, rowMs } from "./Subagents";
import "./activity.css";

/** A fan-out still counts as running this long after its last event, though its turn ended (background). */
const FANOUT_QUIET_MS = 10 * 60_000;

export const slot = "activity";

/** Plain verbs for the detail rows. Unknown tools read as their own name, with underscores spaced. */
const VERBS: Record<string, Key> = {
  terminal: "act.ran",
  read_file: "act.read",
  search_files: "act.searched",
  web_search: "act.searchedWeb",
  web_extract: "act.read",
  write_file: "act.edited",
  patch: "act.edited",
  delegate_task: "act.asked",
  skill_view: "act.usedSkill",
  skill_use: "act.usedSkill",
  browser_navigate: "act.opened",
};
const stepVerb = (name: string) => (VERBS[name] ? tr(VERBS[name]) : name.replace(/_/g, " "));
const DAG_STATUS: Record<string, Key> = { failed: "act.dag.failed", working: "act.dag.working", stopped: "act.dag.stopped", returned: "act.dag.returned" };
/** Code-like details (commands, paths, URLs) render in mono; prose (a subagent's goal) stays text. */
const isCode = (name: string) => !["delegate_task", "web_search"].includes(name);

/** Step duration: "0.4s" under a second, else "38s" / "2m 41s". */
function stepTime(ms: number): string {
  return ms < 1000 ? `${(Math.max(0, ms) / 1000).toFixed(1)}s` : elapsed(ms);
}

interface Label {
  verb: string;
  code?: string;
}

/** A placeholder status word the store keeps in English, said in the current language. */
const shownLabel = (l: Label): Label => (l.verb === WORKING ? { ...l, verb: tr("act.working") } : l.verb === THINKING ? { ...l, verb: tr("row.thinking") } : l);

const labelText = (l: Label) => (l.code ? `${l.verb} ${l.code}` : l.verb);

function LabelView({ label }: { label: Label }) {
  return (
    <>
      {label.verb}
      {label.code && (
        <>
          {" "}
          <code>{label.code}</code>
        </>
      )}
    </>
  );
}

/** Old text moves up and fades, new text comes from below (220 ms; none under reduced motion). */
function Ticker({ label }: { label: Label }) {
  const text = labelText(label);
  const [cur, setCur] = useState({ label, text, k: 0 });
  const [prev, setPrev] = useState<{ label: Label; k: number } | null>(null);
  if (text !== cur.text) {
    setPrev({ label: cur.label, k: cur.k });
    setCur({ label, text, k: cur.k + 1 });
  }
  return (
    <span className="act-tick">
      {prev && (
        <span key={`p${prev.k}`} className="act-tick-t out" aria-hidden onAnimationEnd={() => setPrev(null)}>
          <LabelView label={prev.label} />
        </span>
      )}
      <span key={`c${cur.k}`} className={`act-tick-t${cur.k > 0 ? " in" : ""}`} data-testid="activity-text">
        <LabelView label={cur.label} />
      </span>
    </span>
  );
}

/** "Assigned `t8-site` to a subagent · working": one plain line per dag part a delegate_task handed out. The
 *  status is read-only (nothing here reassigns); the run link opens the Runs tab on that run. */
function DagRows({ step, live }: { step: Step; live: boolean }) {
  const running = step.endedAt === undefined;
  const status = step.stopped ? "stopped" : step.ok === false ? "failed" : running ? (live ? "working" : "stopped") : "returned";
  return (
    <>
      {step.dag!.map((d) => (
        <div key={`${d.run}/${d.node}`} className={`act-step act-dag${step.ok === false ? " fail" : ""}`} data-testid="activity-dag">
          <span className="v prose">
            {tx("act.assigned", { node: <code>{d.node}</code> })}
          </span>
          <span className={`act-dag-st ${status}`} data-testid="activity-dag-status">
            {tr(DAG_STATUS[status])}
          </span>
          <button
            type="button"
            className="act-dag-open"
            onClick={() => getStore().actions.openRun(d.run)}
            data-testid="activity-dag-open"
            title={t("plans.open", { name: d.run })}
          >
            {d.run}
          </button>
        </div>
      ))}
    </>
  );
}

/** A stopped step's time: how long it had run at Stop, or, when the agent later said it finished, that it kept
 *  running and how long the command ran in all (from its own start, by the agent's count). */
function stoppedTime(step: Step, ms: number): string {
  if (!step.late) return stepTime(ms);
  return tr(step.late.ok ? "act.stepLate" : "act.stepLateFailed", { t: stepTime(step.late.ms) });
}

function StepRow({ step, live, now }: { step: Step; live: boolean; now: number }) {
  if (step.name === "delegate_task" && step.dag?.length) return <DagRows step={step} live={live} />;
  const stopped = !!step.stopped;
  const failed = step.ok === false && !stopped;
  const running = step.endedAt === undefined;
  const ms = (step.endedAt ?? now) - step.startedAt;
  return (
    <div
      className={`act-step${failed ? " fail" : ""}${stopped ? " stopped" : ""}`}
      data-testid="activity-step"
      data-ok={stopped ? "stopped" : failed ? "false" : running ? "running" : "true"}
      {...(step.late ? { "data-late": step.late.ok ? "done" : "failed" } : {})}
    >
      {stopped && <span className="act-ic interrupted" aria-hidden>■</span>}
      <span className="k">{stopped ? tr("act.stoppedVerb") : stepVerb(step.name)}</span>
      {step.detail &&
        (isCode(step.name) ? (
          <code className="v" title={step.detail}>
            {step.detail}
          </code>
        ) : (
          <span className="v prose" title={step.detail}>
            {step.detail}
          </span>
        ))}
      <span className="s" data-testid="activity-step-time">
        {running && live ? "…" : stopped ? stoppedTime(step, ms) : failed ? tr("act.stepFailed", { t: stepTime(ms) }) : stepTime(ms)}
      </span>
    </div>
  );
}

export default function Activity({ bot, item, live }: SlotProps["activity"]) {
  const t = item.turn;
  const [open, setOpen] = useState(false);
  // the app's one clock: the elapsed time here and a subagent row's time below read the same instant
  const now = useClock(live);
  const total = elapsed((t.endedAt ?? now) - t.startedAt);
  // while the line names a subagent that is still out ("Asking `Count lines of b.txt`"), its time is that subagent's,
  // the number its row in the card shows; otherwise the turn's
  const last = t.steps[t.steps.length - 1];
  const named = live && last?.name === "delegate_task" && last.endedAt === undefined && liveLabel(t).code === last.detail;
  const sub = named ? t.fanouts?.flatMap((f) => f.subs).find((x) => x.id === last.id && !subagentEnded(x)) : undefined;
  const shownTime = sub ? elapsed(rowMs(sub, now)) : total;
  // what the details show: a delegate_task that handed out dag parts is one row per part
  const n = t.steps.reduce((k, st) => k + (st.name === "delegate_task" && st.dag?.length ? st.dag.length : 1), 0);
  const state = live ? "live" : t.outcome === "interrupted" || t.outcome === "ended" || t.outcome === "error" ? t.outcome : "done";
  const canOpen = n > 0;

  let summary = "";
  if (state === "done") summary = n === 0 ? tr("act.worked0", { t: total }) : n === 1 ? tr("act.worked1", { t: total }) : tr("act.worked", { t: total, n });
  else if (state === "interrupted") summary = tr("act.stopped", { t: total });
  else if (state === "ended") summary = tr("act.ended", { t: total });
  else if (state === "error") summary = `${tr("act.failedAfter", { t: total })}${t.error ? ` · ${t.error}` : ""}`;

  return (
    <div className={`act${open ? " open" : ""}`} data-testid="activity" data-state={state}>
      <button
        type="button"
        className="act-h"
        data-testid="activity-toggle"
        aria-expanded={canOpen ? open : undefined}
        disabled={!canOpen}
        onClick={() => setOpen((o) => !o)}
      >
        {state === "live" ? (
          <Spinner size={11} label={tr("ui.working")} />
        ) : (
          <span className={`act-ic ${state}`} aria-hidden>
            {state === "done" ? "✓" : state === "error" ? "!" : "■"}
          </span>
        )}
        {live &&
          t.skills.map((s) => (
            <span key={s} className="act-skill" data-testid="activity-skill">
              /{s}
            </span>
          ))}
        {live ? (
          <Ticker label={shownLabel(liveLabel(t))} />
        ) : (
          <span className={`act-sum${state === "error" ? " wrap" : ""}`} data-testid="activity-text">
            {summary}
          </span>
        )}
        {live && (
          <span className="act-el" data-testid="activity-elapsed">
            {shownTime}
          </span>
        )}
        {canOpen && (
          <span className="act-chev" aria-hidden>
            <ChevronRight size={10} />
          </span>
        )}
      </button>
      {t.fanouts?.map((f) => (
        <FanoutCard key={f.key} fan={f} live={live || now - f.updatedAt < FANOUT_QUIET_MS} bot={bot} />
      ))}
      {open && canOpen && (
        <div className="act-det" data-testid="activity-details">
          {t.steps.map((s) => (
            <StepRow key={s.id} step={s} live={live} now={now} />
          ))}
        </div>
      )}
    </div>
  );
}
