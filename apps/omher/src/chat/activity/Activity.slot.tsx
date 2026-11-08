// The one activity line per turn (design rule 6). Tool/skill calls never get their own timeline rows:
// while the turn runs, this line's text slides up in place; when it ends it collapses to
// "Worked for 2m 41s · 6 steps" and a click opens one detail row per step.
import { useEffect, useState } from "react";
import type { SlotProps } from "../../features";
import { activityText, type Step, type Turn } from "../../state/store";
import { ChevronRight, Spinner } from "../../ui";
import { elapsed } from "../../app/time";
import "./activity.css";

export const slot = "activity";

/** Short verbs for the detail rows (the live line keeps the store's longer "Reading …" text). */
const KEYS: Record<string, string> = {
  terminal: "run",
  read_file: "read",
  search_files: "search",
  web_search: "web",
  web_extract: "fetch",
  write_file: "edit",
  patch: "edit",
  delegate_task: "agent",
  skill_view: "skill",
  skill_use: "skill",
};
const stepKey = (name: string) => KEYS[name] ?? name;

/** Step duration: "0.4s" under a second, else "38s" / "2m 41s". */
function stepTime(ms: number): string {
  return ms < 1000 ? `${(Math.max(0, ms) / 1000).toFixed(1)}s` : elapsed(ms);
}

interface Label {
  verb: string;
  code?: string;
}

/** The live text: when it is the latest tool's text, split it so the detail renders as code. */
function liveLabel(t: Turn): Label {
  const status = t.status || "Working…";
  const last = t.steps[t.steps.length - 1];
  if (last && last.detail && status === activityText(last.name, last.detail)) {
    return { verb: activityText(last.name, ""), code: last.detail };
  }
  return { verb: status };
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

function StepRow({ step, live, now }: { step: Step; live: boolean; now: number }) {
  const failed = step.ok === false;
  const running = step.endedAt === undefined;
  const ms = (step.endedAt ?? now) - step.startedAt;
  return (
    <div
      className={`act-step${failed ? " fail" : ""}`}
      data-testid="activity-step"
      data-ok={failed ? "false" : running ? "running" : "true"}
    >
      <span className="k">{stepKey(step.name)}</span>
      <span className="v" title={step.detail}>
        {step.detail || step.name}
      </span>
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
  const state = live ? "live" : t.outcome === "interrupted" ? "interrupted" : t.outcome === "error" ? "error" : "done";
  const canOpen = n > 0;

  let summary = "";
  if (state === "done") summary = `Worked for ${total} · ${n} step${n === 1 ? "" : "s"}`;
  else if (state === "interrupted") summary = `Stopped after ${total}`;
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
