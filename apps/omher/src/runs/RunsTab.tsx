// Runs tab: the bot's runs (OMH dag runs, Hermes delegate fan-outs) as a list and a compact read-only graph,
// plus the full-size view over the chat column (⌘⇧G / Expand). Below the bot's own runs, the CLI agents' runs on
// this machine (Claude Code subagents, Codex sub-agents) in the same list style. Nothing here retries, settles or
// cancels.
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { Bot } from "../lib/protocol";
import { cliName, sortRuns, span, type AgentRunSummary, type RunDetail } from "../lib/runs";
import { getStore, useStore } from "../state/store";
import { CloseIcon, IconButton, ModelIcon, Spinner } from "../ui";
import { isMac } from "../app/shortcuts";
import { useNow } from "../elsewhere/useNow";
import { Legend, PANEL_ZOOM, RunGraph } from "./RunGraph";
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

/** How many runs a list shows before "Show all (N)": the newest, running ones first (the list comes sorted). */
export const LIST_CAP = 12;

/** The runs a list shows: the first `LIST_CAP` (running first, then newest), plus the open run when it is further
 *  down, so the selected row is always on screen. */
export function shownRuns<T extends { id: string }>(sorted: T[], all: boolean, selected: string | undefined): T[] {
  if (all || sorted.length <= LIST_CAP) return sorted;
  const head = sorted.slice(0, LIST_CAP);
  const sel = selected === undefined ? undefined : sorted.find((r) => r.id === selected);
  return sel && !head.includes(sel) ? [...head, sel] : head;
}

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

const MIN_GRAPH_H = 320;
const LEGEND_H = 40;

/** The panel graph box's height cap: the rest of the side panel under the run's header and plan card, less the
 *  pinned legend, and at least MIN_GRAPH_H. The box is as tall as the run up to this; a larger run is fitted or
 *  scrolls inside it. With the run list collapsed everything above the graph counts, so the box ends
 *  at the panel's bottom with nothing to scroll; with the list open the list scrolls away and only the run's own
 *  header and plan card count. */
function useRoom(ref: React.RefObject<HTMLElement | null>, ready: boolean, listOpen: boolean): number {
  const [h, setH] = useState(MIN_GRAPH_H);
  useLayoutEffect(() => {
    const el = ref.current;
    const sc = el?.closest(".pn-scroll") as HTMLElement | null;
    const sec = el?.closest(".rn-run") as HTMLElement | null;
    if (!el || !sc || !sec) return;
    const read = () => {
      const top = listOpen ? sec.getBoundingClientRect().top : sc.getBoundingClientRect().top - sc.scrollTop;
      const above = el.getBoundingClientRect().top - top;
      setH(Math.max(MIN_GRAPH_H, Math.floor(sc.clientHeight - above - LEGEND_H - 12)));
    };
    read();
    const ro = new ResizeObserver(read);
    ro.observe(sc);
    if (sc.firstElementChild) ro.observe(sc.firstElementChild);
    return () => ro.disconnect();
  }, [ref, ready, listOpen]);
  return h;
}

function useRuns(bot: string, n = 0) {
  const [list, setList] = useState<{ bot: string; runs: AgentRunSummary[]; cli: AgentRunSummary[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    setError(null);
    // the CLI list is extra: a bridge without `runs.cli` (or a failed read) leaves the bot's own runs showing
    const cli = act()
      .runsCli()
      .then((r) => sortRuns(r.runs))
      .catch(() => [] as AgentRunSummary[]);
    act()
      .runsList(bot)
      .then(async (r) => live && setList({ bot, runs: sortRuns(r.runs), cli: await cli }))
      .catch((e) => live && setError(String(e?.message ?? e)));
    return () => {
      live = false;
    };
  }, [bot, n]);
  const mine = list?.bot === bot ? list : null;
  return { runs: mine?.runs ?? null, cli: mine?.cli ?? [], error };
}

/** One run in the list: state dot, title, tags, done/total and time. CLI runs carry their agent's mark and name. */
function RunRow({ r, on, nowS, onPick, testId = "run-row" }: { r: AgentRunSummary; on: boolean; nowS: number; onPick: () => void; testId?: string }) {
  const s = useStore();
  return (
    <li>
      <button
        type="button"
        className={`rn-row${on ? " on" : ""}`}
        data-testid={testId}
        data-state={r.state}
        data-kind={r.kind}
        data-agent={r.agent}
        aria-current={on ? "true" : undefined}
        onClick={() => {
          s.openRun(r.id);
          onPick();
        }}
        title={[r.goal || r.title, r.cwd].filter(Boolean).join(" · ")}
      >
        <i className={r.state === "running" ? "rn-live" : `rn-dot ${r.state}${r.state === "done" && r.counts.failed > 0 ? " mixed" : ""}`} aria-label={r.state} />
        {r.agent && (
          <span className="rn-agent" data-testid="run-agent">
            <ModelIcon model={r.agent} size={11} />
            {cliName(r.agent)}
          </span>
        )}
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
  );
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

const Chevron = ({ up }: { up: boolean }) => (
  <svg viewBox="0 0 24 24" width="10" height="10" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
    <path d={up ? "M6 15l6-6 6 6" : "M6 9l6 6 6-6"} />
  </svg>
);

const ExpandIcon = () => (
  <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M14 4h6v6M10 20H4v-6M20 4l-7 7M4 20l7-7" />
  </svg>
);

export function RunsTab({ bot }: { bot: Bot }) {
  const s = useStore();
  const [n, setN] = useState(0);
  const [all, setAll] = useState(false);
  const [allCli, setAllCli] = useState(false);
  // with a run selected the lists fold into the run's header ("All runs ▾"), so its graph starts high in the panel
  const [listOpen, setListOpen] = useState(false);
  const { runs, cli, error } = useRuns(bot.name, n);
  const nowMs = useNow(!!runs?.some((r) => r.state === "running") || cli.some((r) => r.state === "running"));
  if (!runs) return <div className={`pn-empty${error ? " bad" : ""}`}>{error ?? <Spinner size={12} label="Loading" />}</div>;
  const selected = pickRun([...runs, ...cli], s.ui.runId);
  const nowS = nowMs / 1000;
  const lists = !selected || listOpen;
  const picked = () => setListOpen(false);
  return (
    <div className="pn-body rn" data-testid="panel-runs" data-list={lists ? "open" : "closed"}>
      <div className="pn-sec">
        {bot.display_name}'s runs
        {selected ? (
          <button type="button" className="rn-toggle" data-testid="run-list-toggle" aria-expanded={listOpen} onClick={() => setListOpen((v) => !v)}>
            All {runs.length + cli.length} runs
            <Chevron up={listOpen} />
          </button>
        ) : (
          <span className="rn-count">{runs.length}</span>
        )}
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
      {lists && runs.length > 0 && (
        <ul className={`rn-list${all ? " all" : ""}`} data-testid="run-list">
          {shownRuns(runs, all, selected?.id).map((r) => (
            <RunRow key={r.id} r={r} on={r.id === selected?.id} nowS={nowS} onPick={picked} />
          ))}
        </ul>
      )}
      {lists && runs.length > LIST_CAP && (
        <button type="button" className="rn-more" data-testid="run-list-more" onClick={() => setAll((v) => !v)}>
          {all ? "Show fewer" : `Show all (${runs.length})`}
        </button>
      )}
      {lists && cli.length > 0 && (
        <>
          <div className="pn-sec rn-sec2">
            CLI agents<span>{cli.length}</span>
          </div>
          <ul className={`rn-list${allCli ? " all" : ""}`} data-testid="cli-run-list">
            {shownRuns(cli, allCli, selected?.id).map((r) => (
              <RunRow key={r.id} r={r} on={r.id === selected?.id} nowS={nowS} onPick={picked} testId="cli-run-row" />
            ))}
          </ul>
          {cli.length > LIST_CAP && (
            <button type="button" className="rn-more" data-testid="cli-run-list-more" onClick={() => setAllCli((v) => !v)}>
              {allCli ? "Show fewer" : `Show all (${cli.length})`}
            </button>
          )}
        </>
      )}
      {selected && <PanelRun key={selected.id} bot={bot} summary={selected} nowS={nowS} listOpen={lists} />}
    </div>
  );
}

function PanelRun({ bot, summary, nowS, listOpen }: { bot: Bot; summary: AgentRunSummary; nowS: number; listOpen: boolean }) {
  const s = useStore();
  const { detail, error } = useDetail(bot.name, summary);
  const [open, setOpen] = useState<string | null>(null);
  const [ref, width] = useWidth<HTMLDivElement>();
  const [over, setOver] = useState(false);
  const [hidden, setHidden] = useState(0);
  const onOverflow = useCallback((o: boolean, h: number) => {
    setOver(o);
    setHidden(h);
  }, []);
  const run = detail?.run;
  const room = useRoom(ref, !!run, listOpen);
  // the person's zoom over the fitted scale (1 = Fit)
  const [zoom, setZoom] = useState(1);
  // a box taller than what the panel shows: bring the run's box into view once, so its focus node is on screen
  useEffect(() => {
    const el = ref.current;
    const sc = el?.closest(".pn-scroll") as HTMLElement | null;
    if (!run || !el || !sc) return;
    const below = el.getBoundingClientRect().bottom + LEGEND_H - sc.getBoundingClientRect().bottom;
    if (below > 1) sc.scrollTop += below;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run?.id]);
  const node = run?.nodes.find((x) => x.id === open) ?? null;
  const fullKey = isMac() ? "⌘⇧G" : "Ctrl+Shift+G";
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
      <div className="rn-gwrap" ref={ref} style={{ maxHeight: room }}>
        {!run || !width ? (
          <div className={`pn-empty${error ? " bad" : ""}`}>{error ?? <Spinner size={12} label="Loading" />}</div>
        ) : (
          <>
            <RunGraph run={run} handoffs={detail!.handoffs} mode="panel" width={width} open={open} onOpen={setOpen} nowS={nowS} bot={bot} onOverflow={onOverflow} maxH={room - 2} zoom={zoom} />
          </>
        )}
      </div>
      {run && (
        <Legend
          run={run}
          extra={
            over ? (
              <button type="button" className="rn-full-hint" data-testid="run-full-hint" onClick={() => s.setRunsFull(true)} title="Open the whole run over the chat">
                {hidden > 0 && (
                  <span className="rn-hidden" data-testid="run-hidden">
                    {hidden} more ·
                  </span>
                )}
                Open full view <kbd>{fullKey}</kbd>
              </button>
            ) : null
          }
          tools={
            <span className="rn-zoom" role="group" aria-label="Zoom" data-testid="run-zoom">
              <button type="button" onClick={() => setZoom((z) => Math.max(PANEL_ZOOM.min / 2, z / PANEL_ZOOM.step))} aria-label="Zoom out" title="Zoom out" data-testid="run-zoom-out">
                −
              </button>
              <button type="button" onClick={() => setZoom(1)} className={zoom === 1 ? "on" : ""} title="Fit the run to the panel" data-testid="run-zoom-fit">
                Fit
              </button>
              <button type="button" onClick={() => setZoom((z) => Math.min(PANEL_ZOOM.max * 2, z * PANEL_ZOOM.step))} aria-label="Zoom in" title="Zoom in" data-testid="run-zoom-in">
                +
              </button>
            </span>
          }
        />
      )}
      {run && node && <NodeDrawer runId={run.id} node={node} text={detail!.handoffs[node.id]} nowS={nowS} onClose={() => setOpen(null)} />}
    </div>
  );
}

/** The full-size graph over the chat column. The side panel stays; Esc or × closes it. */
export function RunsFull({ bot }: { bot: Bot }) {
  const s = useStore();
  const { runs, cli, error } = useRuns(bot.name);
  const selected = runs ? pickRun([...runs, ...cli], s.ui.runId) : null;
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
