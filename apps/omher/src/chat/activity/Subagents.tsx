// The subagents of a fan-out in the chat: ONE card per delegate_task in the turn's activity, one row per subagent,
// updating in place from Hermes' subagent events. Running: "Running · 1 of 2 done · 41s", the way Plans counts;
// done: "Ran 2 subagents · 3m". Each row: the model's vendor mark, the goal in a few words, its state ("waiting" in
// amber while its approval or question waits on the person), its current step or its result line, and its time. The
// card's run name opens that run in Plans. Read-only: nothing here assigns, steers or stops a subagent.
// `SubagentLine` is the row alone, for any chat that shows subagents (SESSIONS too).
import { useState } from "react";
import type { ChatItem, Fanout, SubagentRow } from "../../state/store";
import { askOpen, getStore, subagentEnded, useStore } from "../../state/store";
import { ChevronRight, ModelIcon, Spinner } from "../../ui";
import { elapsed } from "../../app/time";
import { useClock } from "../../app/clock";
import { t } from "../../i18n";
import { modelName } from "../../runs/format";
import { DiffView } from "./Work";

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
export const rowMs = (s: SubagentRow, now: number) => (s.seconds !== undefined ? s.seconds * 1000 : (s.endedAt ?? now) - s.startedAt);

/** The subagents whose approval or question is open in `items` (an ask that names its subagent). */
export function waitingSubs(items: ChatItem[] | undefined): Set<string> {
  const out = new Set<string>();
  for (const it of items ?? []) if ((it.kind === "approval" || it.kind === "clarify") && it.subagent?.id && askOpen(items!, it)) out.add(it.subagent.id);
  return out;
}

export function SubagentLine({ sub, now, live = true, waiting = false }: { sub: SubagentRow; now: number; live?: boolean; waiting?: boolean }) {
  const ended = subagentEnded(sub);
  const [open, setOpen] = useState(false);
  // a turn that ended with the child still out and nothing more heard (the bridge dropped, the chat reopened); a
  // child whose ask is open waits on the person, and runs again once it is answered
  const state = !ended && !live ? "stopped" : !ended && waiting ? "waiting" : sub.state;
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
            {state === "stopped" ? t("sub.stopped") : state === "waiting" ? t("sub.waiting") : t(STATE_KEY[sub.state])}
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
            {sub.steps?.map((s, i) => (s.diff?.length ? <EditStep key={i} text={s.text} diff={s.diff} /> : (
              <span key={i} className="sa-step" data-testid="subagent-step">
                <code>{s.text}</code>
              </span>
            )))}
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

/** A subagent's file edit: its line opens to the same diff a session's own edit shows. */
function EditStep({ text, diff }: { text: string; diff: NonNullable<NonNullable<SubagentRow["steps"]>[number]["diff"]> }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" className={`sa-step sa-edit${open ? " open" : ""}`} aria-expanded={open} onClick={() => setOpen((o) => !o)} data-testid="subagent-step">
        <code>{text}</code>
        <span className="sa-chev" aria-hidden>
          <ChevronRight size={9} />
        </span>
      </button>
      {open && <DiffView files={diff} />}
    </>
  );
}

export function FanoutCard({ fan, live, bot }: { fan: Fanout; live: boolean; bot: string }) {
  const subs = fan.subs;
  const total = Math.max(fan.count, subs.length);
  const done = subs.filter(subagentEnded).length;
  const running = live && done < total;
  // the app's one clock (a quarter second): this card, the activity line above it and Plans read the same instant
  const now = useClock(running);
  // a row reads "waiting" while its own ask is open in this chat
  const waiting = waitingSubs(useStore().chats[bot]?.items);
  // the fan-out's elapsed time: from its first subagent's start (one that ended with its own time began that long
  // before it ended, which can be before omher heard of it) to now, or to its last end; never less than its longest row
  const begun = Math.min(fan.startedAt, ...subs.map((s) => (s.seconds !== undefined && s.endedAt !== undefined ? s.endedAt - s.seconds * 1000 : s.startedAt)));
  const ends = subs.map((s) => s.endedAt ?? s.startedAt + rowMs(s, now));
  const span = elapsed(Math.max((running ? now : Math.max(begun, ...ends)) - begun, ...subs.map((s) => rowMs(s, now))));
  const failed = subs.filter((s) => s.state === "failed").length;
  const run = subs.find((s) => s.dag)?.dag?.run ?? null;
  const open = () => getStore().actions.openRun(run ?? (fan.delegation ? `delegate:${fan.delegation}` : null));
  return (
    <div className="sa-card" data-testid="fanout-card" data-state={running ? "running" : "done"} data-delegation={fan.delegation}>
      <div className="sa-head">
        {running ? <Spinner size={10} label={t("ui.working")} /> : <span className={`sa-ic${failed ? " failed" : ""}`} aria-hidden="true" />}
        <span className="sa-sum" data-testid="fanout-summary">
          {running
            ? t("sub.runningDone", { n: total, done, t: span })
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
          <SubagentLine key={s.id} sub={s} now={now} live={live} waiting={waiting.has(s.id)} />
        ))}
      </div>
    </div>
  );
}
