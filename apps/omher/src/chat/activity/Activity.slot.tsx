// The one activity line per turn (design rule 6). Tool/skill calls never get their own timeline rows:
// while the turn runs, this line's text slides up in place; when it ends it collapses to
// "Worked for 2m 41s · 6 steps" and a click opens one detail row per step.
import { useEffect, useState } from "react";
import type { SlotProps } from "../../features";
import { activityText, getStore, liveLabel, type Step, type Turn } from "../../state/store";
import { ChevronRight, Spinner } from "../../ui";
import { elapsed } from "../../app/time";
import { t } from "../../i18n";
import "./activity.css";

export const slot = "activity";

/** Plain verbs for the detail rows. Unknown tools read as their own name, with underscores spaced. */
const VERBS: Record<string, string> = {
  terminal: "Ran",
  read_file: "Read",
  search_files: "Searched",
  web_search: "Searched the web",
  web_extract: "Read",
  write_file: "Edited",
  patch: "Edited",
  delegate_task: "Asked a helper",
  skill_view: "Used skill",
  skill_use: "Used skill",
  browser_navigate: "Opened",
};
const stepVerb = (name: string) => VERBS[name] ?? name.replace(/_/g, " ");
/** Code-like details (commands, paths, URLs) render in mono; prose (a helper's goal) stays text. */
const isCode = (name: string) => !["delegate_task", "web_search"].includes(name);

/** Step duration: "0.4s" under a second, else "38s" / "2m 41s". */
function stepTime(ms: number): string {
  return ms < 1000 ? `${(Math.max(0, ms) / 1000).toFixed(1)}s` : elapsed(ms);
}

interface Label {
  verb: string;
  code?: string;
}

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

/** "Assigned `t8-site` to a helper · working": one plain line per dag part a delegate_task handed out. The
 *  status is read-only (nothing here reassigns); the run link opens the Runs tab on that run. */
function DagRows({ step, live }: { step: Step; live: boolean }) {
  const running = step.endedAt === undefined;
  const status = step.ok === false ? "failed" : running ? (live ? "working" : "stopped") : "returned";
  return (
    <>
      {step.dag!.map((d) => (
        <div key={`${d.run}/${d.node}`} className={`act-step act-dag${step.ok === false ? " fail" : ""}`} data-testid="activity-dag">
          <span className="v prose">
            Assigned <code>{d.node}</code> to a helper
          </span>
          <span className={`act-dag-st ${status}`} data-testid="activity-dag-status">
            {status}
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

function StepRow({ step, live, now }: { step: Step; live: boolean; now: number }) {
  if (step.name === "delegate_task" && step.dag?.length) return <DagRows step={step} live={live} />;
  const failed = step.ok === false;
  const running = step.endedAt === undefined;
  const ms = (step.endedAt ?? now) - step.startedAt;
  return (
    <div
      className={`act-step${failed ? " fail" : ""}`}
      data-testid="activity-step"
      data-ok={failed ? "false" : running ? "running" : "true"}
    >
      <span className="k">{stepVerb(step.name)}</span>
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
      <span className="s">{running && live ? "…" : `${failed ? "failed · " : ""}${stepTime(ms)}`}</span>
    </div>
  );
}

export default function Activity({ item, live }: SlotProps["activity"]) {
  const t = item.turn;
  const [open, setOpen] = useState(false);
  const [, tick] = useState(0);
  useEffect(() => {
    if (!live) return;
    const h = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(h);
  }, [live]);

  const now = Date.now();
  const total = elapsed((t.endedAt ?? now) - t.startedAt);
  const n = t.steps.length;
  const state = live ? "live" : t.outcome === "interrupted" || t.outcome === "ended" || t.outcome === "error" ? t.outcome : "done";
  const canOpen = n > 0;

  let summary = "";
  if (state === "done") summary = `Worked for ${total} · ${n} step${n === 1 ? "" : "s"}`;
  else if (state === "interrupted") summary = `Stopped after ${total}`;
  else if (state === "ended") summary = `Ended after ${total}`;
  else if (state === "error") summary = `Failed after ${total}${t.error ? ` · ${t.error}` : ""}`;

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
          <Spinner size={11} label="Working" />
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
          <Ticker label={liveLabel(t)} />
        ) : (
          <span className="act-sum" data-testid="activity-text">
            {summary}
          </span>
        )}
        {live && (
          <span className="act-el" data-testid="activity-elapsed">
            {total}
          </span>
        )}
        {canOpen && (
          <span className="act-chev" aria-hidden>
            <ChevronRight size={10} />
          </span>
        )}
      </button>
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
