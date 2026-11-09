// Runs tab: the bot's runs (OMH dag runs, Hermes delegate fan-outs) as a list and a compact read-only graph,
// plus the full-size view over the chat column (⌘⇧G / Expand). Nothing here retries, settles or cancels.
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { Bot } from "../lib/protocol";
import { sortRuns, span, type AgentRunSummary, type RunDetail } from "../lib/runs";
import { getStore, useStore } from "../state/store";
import { CloseIcon, IconButton, Spinner } from "../ui";
import { useNow } from "../elsewhere/useNow";
import { Legend, RunGraph } from "./RunGraph";
import { NodeDrawer } from "./NodeDrawer";
import { PlanCard } from "./PlanCard";
import { columnLabel } from "./layout";
import type { AgentRun } from "../lib/runs";

/** Each layer's name, the same words as the graph's column labels ("Plan + Build"). */
const layerNames = (run: AgentRun) => {
  const by: AgentRun["nodes"][] = [];
  for (const n of run.nodes) (by[n.layer] ??= []).push(n);
  return [...by].map((ns, l) => (ns ? columnLabel(ns, l).replace(/ · \d+$/, "") : ""));
};
import { runName } from "./format";
import "./runs.css";

const act = () => getStore().actions;

/** The run a `ui.runId` names: a full id, or a dag run's short name from a chat line. */
export function pickRun<T extends { id: string }>(runs: T[], runId: string | null): T | null {
  return runs.find((r) => r.id === runId) ?? runs.find((r) => runId !== null && runName(r.id) === runId) ?? runs[0] ?? null;
}

function useWidth<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = useRef<T>(null);
  const [w, setW] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    setW(el.clientWidth);
    const ro = new ResizeObserver(() => setW(el.clientWidth));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

function useRuns(bot: string, n = 0) {
  const [list, setList] = useState<{ bot: string; runs: AgentRunSummary[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    setError(null);
    act()
      .runsList(bot)
      .then(
        (r) => live && setList({ bot, runs: sortRuns(r.runs) }),
        (e) => live && setError(String(e?.message ?? e)),
      );
    return () => {
      live = false;
    };
  }, [bot, n]);
  return { runs: list?.bot === bot ? list.runs : null, error };
}

function useDetail(bot: string, summary: AgentRunSummary | null) {
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!summary) return;
    let live = true;
    act()
      .runsGet(bot, summary.id)
      .then(
        (d) => live && setDetail(d),
        (e) => live && setError(String(e?.message ?? e)),
      );
    return () => {
      live = false;
    };
    // re-read when the list shows the run changed
  }, [bot, summary?.id, summary?.updated]);
  return { detail: detail && detail.run.id === summary?.id ? detail : null, error };
}

const STATE_LABEL = { running: "Running", done: "Done", failed: "Failed", cancelled: "Cancelled" } as const;

/** "● Running ▬▬▬▭▭ 3/6": the run's state with a slim progress bar. */
function StatusBadge({ run, time }: { run: Pick<AgentRunSummary, "state" | "counts">; time?: string }) {
  const { done, nodes, failed } = run.counts;
  return (
    <span className={`rn-badge ${run.state}${failed > 0 && run.state === "done" ? " mixed" : ""}`} data-testid="run-state">
      {run.state === "running" && <i className="rn-live" aria-hidden />}
      <span className="rn-badge-t">{STATE_LABEL[run.state]}</span>
      <span className="rn-bar" aria-hidden>
        <i style={{ width: `${nodes ? (100 * done) / nodes : 0}%` }} />
        {run.counts.running > 0 && (
          <i className="run" style={{ left: `calc(${(100 * done) / nodes}% + 1px)`, width: `calc(${(100 * run.counts.running) / nodes}% - 1px)` }} />
        )}
        {(run.counts.repaired ?? 0) > 0 && (
          <i className="fix" style={{ left: `calc(${(100 * (done + run.counts.running)) / nodes}% + 1px)`, width: `calc(${(100 * run.counts.repaired!) / nodes}% - 1px)` }} />
        )}
        {failed > 0 && (
          <i
            className="bad"
            style={{ left: `calc(${(100 * (done + run.counts.running + (run.counts.repaired ?? 0))) / nodes}% + 1px)`, width: `calc(${(100 * failed) / nodes}% - 1px)` }}
          />
        )}
      </span>
      <span className="rn-badge-n" data-testid="run-progress">
        {done}/{nodes}
      </span>
      {failed > 0 && run.state !== "failed" && <span className="rn-badge-bad">· {failed} failed</span>}
      {(run.counts.repaired ?? 0) > 0 && <span className="rn-badge-fix">· {run.counts.repaired} repaired</span>}
      {time && <span className="rn-badge-n">· {time}</span>}
    </span>
  );
}

const ExpandIcon = () => (
  <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M14 4h6v6M10 20H4v-6M20 4l-7 7M4 20l7-7" />
  </svg>
);

export function RunsTab({ bot }: { bot: Bot }) {
  const s = useStore();
  const [n, setN] = useState(0);
  const { runs, error } = useRuns(bot.name, n);
  const nowMs = useNow(!!runs?.some((r) => r.state === "running"));
  if (!runs) return <div className={`pn-empty${error ? " bad" : ""}`}>{error ?? <Spinner size={12} label="Loading" />}</div>;
  const selected = pickRun(runs, s.ui.runId);
  const nowS = nowMs / 1000;
  return (
    <div className="pn-body rn" data-testid="panel-runs">
      <div className="pn-sec">
        {bot.display_name}'s runs<span>{runs.length}</span>
        <button type="button" className="pn-ref" onClick={() => setN((x) => x + 1)} title="Refresh" aria-label="Refresh">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" width="12" height="12">
            <path d="M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7" />
          </svg>
        </button>
      </div>
      {runs.length === 0 && (
        <div className="pn-empty">
          No runs yet.
          <br />
          When {bot.display_name} splits work into parallel parts, they show here.
        </div>
      )}
      {runs.length > 0 && (
        <ul className="rn-list" data-testid="run-list">
          {runs.map((r) => (
            <li key={r.id}>
              <button
                type="button"
                className={`rn-row${r.id === selected?.id ? " on" : ""}`}
                data-testid="run-row"
                data-state={r.state}
                data-kind={r.kind}
                aria-current={r.id === selected?.id ? "true" : undefined}
                onClick={() => s.openRun(r.id)}
                title={r.goal || r.title}
              >
                <i className={r.state === "running" ? "rn-live" : `rn-dot ${r.state}${r.state === "done" && r.counts.failed > 0 ? " mixed" : ""}`} aria-label={r.state} />
                <span className="rn-title">{r.title}</span>
                {r.kind === "delegate" && <span className="rn-tag">helpers</span>}
                {r.state !== "failed" && r.state !== "cancelled" && r.counts.failed > 0 && <span className="rn-tag bad">{r.counts.failed} failed</span>}
                {r.state !== "failed" && r.state !== "cancelled" && !r.counts.failed && (r.counts.repaired ?? 0) > 0 && (
                  <span className="rn-tag fix">{r.counts.repaired} repaired</span>
                )}
                {r.state === "cancelled" && <span className="rn-tag">Cancelled</span>}
                {r.state === "failed" && <span className="rn-tag bad">Failed</span>}
                <span className="rn-n">
                  {r.counts.done}/{r.counts.nodes} · {span((r.ended ?? nowS) - r.started)}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {selected && <PanelRun key={selected.id} bot={bot} summary={selected} nowS={nowS} />}
    </div>
  );
}

function PanelRun({ bot, summary, nowS }: { bot: Bot; summary: AgentRunSummary; nowS: number }) {
  const s = useStore();
  const { detail, error } = useDetail(bot.name, summary);
  const [open, setOpen] = useState<string | null>(null);
  const [ref, width] = useWidth<HTMLDivElement>();
  const run = detail?.run;
  const node = run?.nodes.find((x) => x.id === open) ?? null;
  return (
    <div className="rn-run" data-testid="run-graph-box" data-run={summary.id} data-state={summary.state}>
      <div className="rn-head">
        <b title={summary.title}>{summary.title}</b>
        <StatusBadge run={summary} />
        <button type="button" className="pn-ref" onClick={() => s.setRunsFull(true)} data-testid="graph-expand" title="Expand (⌘⇧G)" aria-label="Expand">
          <ExpandIcon />
        </button>
      </div>
      {run && <PlanCard run={run} mode="panel" nowS={nowS} names={layerNames(run)} />}
      <div className="rn-gwrap" ref={ref}>
        {!run || !width ? (
          <div className={`pn-empty${error ? " bad" : ""}`}>{error ?? <Spinner size={12} label="Loading" />}</div>
        ) : (
          <>
            <RunGraph run={run} handoffs={detail!.handoffs} mode="panel" width={width} open={open} onOpen={setOpen} nowS={nowS} bot={bot} />
          </>
        )}
      </div>
      {run && <Legend run={run} />}
      {run && node && <NodeDrawer runId={run.id} node={node} text={detail!.handoffs[node.id]} nowS={nowS} onClose={() => setOpen(null)} />}
    </div>
  );
}

/** The full-size graph over the chat column. The side panel stays; Esc or × closes it. */
export function RunsFull({ bot }: { bot: Bot }) {
  const s = useStore();
  const { runs, error } = useRuns(bot.name);
  const selected = runs ? pickRun(runs, s.ui.runId) : null;
  const { detail } = useDetail(bot.name, selected);
  const nowMs = useNow(selected?.state === "running");
  const [open, setOpen] = useState<string | null>(null);
  const [ref, width] = useWidth<HTMLDivElement>();
  useEffect(() => setOpen(null), [selected?.id]);
  const run = detail?.run;
  const node = run?.nodes.find((x) => x.id === open) ?? null;
  const nowS = nowMs / 1000;
  return (
    <div className="rf" data-testid="runs-full" role="dialog" aria-label="Run graph">
      <div className="rf-head">
        {selected ? (
          <>
            <b title={selected.title}>{selected.title}</b>
            <StatusBadge run={selected} time={span((selected.ended ?? nowS) - selected.started)} />
          </>
        ) : (
          <b>{bot.display_name}'s runs</b>
        )}
        <span className="rf-hint">View only · drag cards to rearrange · Esc closes</span>
        <IconButton label="Close graph" onClick={() => s.setRunsFull(false)}>
          <CloseIcon />
        </IconButton>
      </div>
      {run && <PlanCard run={run} mode="full" nowS={nowS} names={layerNames(run)} />}
      <div className="rf-body" ref={ref}>
        {!runs ? (
          <div className="pn-empty">{error ?? <Spinner size={12} label="Loading" />}</div>
        ) : !selected ? (
          <div className="pn-empty">No runs yet.</div>
        ) : !run || !width ? (
          <div className="pn-empty">
            <Spinner size={12} label="Loading" />
          </div>
        ) : (
          <RunGraph key={run.id} run={run} handoffs={detail!.handoffs} mode="full" width={width} open={open} onOpen={setOpen} nowS={nowS} bot={bot} />
        )}
        {run && node && (
          <div className="rf-drawer">
            <NodeDrawer runId={run.id} node={node} text={detail!.handoffs[node.id]} nowS={nowS} onClose={() => setOpen(null)} />
          </div>
        )}
      </div>
    </div>
  );
}
