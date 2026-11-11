// The subagents of a fan-out in the chat: ONE card per delegate_task in the turn's activity, one row per subagent,
// updating in place from Hermes' subagent events. Running: "2 subagents running · 1 of 2 · 41s"; done: "Ran 2
// subagents · 3m". Each row: the model's vendor mark, the goal in a few words, its state, its current step or
// its result line, and its time. The card's run name opens that run in Plans. Read-only: nothing here assigns,
// steers or stops a subagent. `SubagentLine` is the row alone, for any chat that shows subagents (SESSIONS too).
import { useEffect, useState } from "react";
import type { Fanout, SubagentRow } from "../../state/store";
import { getStore, subagentEnded } from "../../state/store";
import { ModelIcon, Spinner } from "../../ui";
import { elapsed } from "../../app/time";
import { t } from "../../i18n";
import { modelName } from "../../runs/format";

const STATE_KEY = {
  queued: "sub.queued",
  running: "sub.running",
  thinking: "sub.thinking",
  done: "sub.done",
  failed: "sub.failed",
  cancelled: "sub.cancelled",
} as const;

/** The first words of a goal, cut at a word near `n` characters. */
export function fewWords(goal: string, n = 60): string {
  const s = goal.replace(/\s+/g, " ").trim();
  if (s.length <= n) return s;
  const cut = s.slice(0, n);
  const sp = cut.lastIndexOf(" ");
  return `${(sp > n * 0.6 ? cut.slice(0, sp) : cut).replace(/[\s,.;:]+$/, "")}…`;
}

/** A subagent's time: its own run time when it ended, else counted from when omher first heard of it. */
const rowMs = (s: SubagentRow, now: number) => (s.seconds !== undefined ? s.seconds * 1000 : (s.endedAt ?? now) - s.startedAt);

export function SubagentLine({ sub, now, live = true }: { sub: SubagentRow; now: number; live?: boolean }) {
  const ended = subagentEnded(sub);
  const [open, setOpen] = useState(false);
  // a turn that ended with the child still out and nothing more heard (the bridge dropped, the chat reopened)
  const state = !ended && !live ? "stopped" : sub.state;
  const line = ended ? sub.summary : sub.step;
  // its name and its task: "general-purpose · Read a.txt first line"; either alone when the agent gives one
  const title = [sub.name, fewWords(sub.goal)].filter(Boolean).join(" · ") || t("sub.untitled", { n: sub.index + 1 });
  const canOpen = !!(sub.steps?.length || (ended && sub.summary));
  return (
    <div className={`sa-row s-${state}${open ? " open" : ""}`} data-testid="subagent-row" data-state={state} data-sub={sub.id} data-agent={sub.agent}>
      <span className="sa-mark" title={sub.model ? modelName(sub.model) : undefined}>
        <ModelIcon model={sub.model} size={12} />
      </span>
      <span className="sa-main">
        <button
          type="button"
          className="sa-top"
          aria-expanded={canOpen ? open : undefined}
          disabled={!canOpen}
          onClick={() => setOpen((v) => !v)}
          data-testid="subagent-open"
        >
          <span className="sa-goal" title={[sub.name, sub.goal].filter(Boolean).join(" · ")} data-testid="subagent-goal">
            {title}
          </span>
          <span className={`sa-st ${state}`} data-testid="subagent-state">
            {state === "stopped" ? t("sub.stopped") : t(STATE_KEY[sub.state])}
          </span>
          <span className="sa-t" data-testid="subagent-time">
            {elapsed(rowMs(sub, now))}
          </span>
        </button>
        {line && !open && (
          <span className={`sa-line${ended ? " result" : ""}`} title={line} data-testid="subagent-line">
            {!ended && sub.tool ? <code>{line}</code> : line}
          </span>
        )}
        {open && (
          <span className="sa-det" data-testid="subagent-detail">
            {sub.steps?.map((s, i) => (
              <span key={i} className="sa-step" data-testid="subagent-step">
                <code>{s.text}</code>
              </span>
            ))}
            {ended && sub.summary && (
              <span className="sa-ans" data-testid="subagent-answer">
                {sub.summary}
              </span>
            )}
          </span>
        )}
      </span>
    </div>
  );
}

export function FanoutCard({ fan, live }: { fan: Fanout; live: boolean }) {
  const subs = fan.subs;
  const total = Math.max(fan.count, subs.length);
  const done = subs.filter(subagentEnded).length;
  const running = live && done < total;
  const [, tick] = useState(0);
  useEffect(() => {
    if (!running) return;
    const h = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(h);
  }, [running]);
  const now = Date.now();
  const ends = subs.map((s) => s.startedAt + rowMs(s, now));
  const span = elapsed((running ? now : Math.max(fan.startedAt, ...ends)) - fan.startedAt);
  const failed = subs.filter((s) => s.state === "failed").length;
  const run = subs.find((s) => s.dag)?.dag?.run ?? null;
  const open = () => getStore().actions.openRun(run ?? (fan.delegation ? `delegate:${fan.delegation}` : null));
  return (
    <div className="sa-card" data-testid="fanout-card" data-state={running ? "running" : "done"} data-delegation={fan.delegation}>
      <div className="sa-head">
        {running ? <Spinner size={10} label={t("ui.working")} /> : <span className={`sa-ic${failed ? " failed" : ""}`} aria-hidden="true" />}
        <span className="sa-sum" data-testid="fanout-summary">
          {running
            ? t(total === 1 ? "sub.running1" : "sub.runningN", { n: total, done, t: span })
            : t(total === 1 ? "sub.ran1" : "sub.ranN", { n: total, t: span }) + (failed ? ` · ${t("sub.nfailed", { n: failed })}` : "")}
        </span>
        {(run || fan.delegation) && (
          <button type="button" className="sa-open" onClick={open} data-testid="fanout-open" title={t("plans.open", { name: run ?? t("plans.tab") })}>
            {run ?? t("plans.tab")}
          </button>
        )}
      </div>
      <div className="sa-rows">
        {subs.map((s) => (
          <SubagentLine key={s.id} sub={s} now={now} live={live} />
        ))}
      </div>
    </div>
  );
}
