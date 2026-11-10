// Plans tab: the bot's plans (OMH dag runs, Hermes delegate fan-outs) as a list of plain text rows, and the
// selected one as plain text and a read-only graph (frontiers of outlined boxes joined by lines), plus the same
// drawing at full size over the chat column (⌘⇧G). Below the bot's own, the CLI agents' on this machine (Claude Code subagents,
// Codex sub-agents) in the same list style. A plan is a run in the code and the protocol (`runs.list`); only the
// words on screen say "plan". Nothing here retries, settles or cancels.
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { Bot } from "../lib/protocol";
import { cliName, sortRuns, span, type AgentRunSummary, type RunDetail } from "../lib/runs";
import { getStore, useStore } from "../state/store";
import { CloseIcon, ExpandIcon, IconButton, ModelIcon, Spinner } from "../ui";
import { isMac } from "../app/shortcuts";
import { useNow } from "../elsewhere/useNow";
import { t } from "../i18n";
import { frontiers } from "./boxView";
import { RunGraph } from "./RunGraph";
import { NodeDrawer } from "./NodeDrawer";
import { PlanHeader } from "./PlanHeader";
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

/** One plan in the list, as plain text: a small state dot, its goal (its title when it has none), then "3/7 · 12m".
 *  No pills. A CLI agent's row names the agent before the text. */
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
        title={[r.title, r.goal, r.cwd].filter(Boolean).join(" · ")}
      >
        <i className={r.state === "running" ? "rn-live" : `rn-dot ${r.state}${r.state === "done" && r.counts.failed > 0 ? " mixed" : ""}`} aria-label={r.state} />
        {r.agent && (
          <span className="rn-agent" data-testid="run-agent">
            <ModelIcon model={r.agent} size={11} />
            {cliName(r.agent)}
          </span>
        )}
        <span className="rn-title" data-testid="run-row-text">
          {r.goal || r.title}
        </span>
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

/** The nodes `id` has a line from in the graph, for its detail's "after …" line. Worked out once a run as it was
 *  read: an open node's detail renders every second. */
const PARENTS = new WeakMap<object, Map<string, string[]>>();
function parentsOf(run: RunDetail["run"], id: string) {
  const byId = new Map(run.nodes.map((n) => [n.id, n]));
  let all = PARENTS.get(run.nodes);
  if (!all) PARENTS.set(run.nodes, (all = frontiers(run.nodes).parents));
  return (all.get(id) ?? []).map((p) => byId.get(p)!);
}

const Chevron = ({ up }: { up: boolean }) => (
  <svg viewBox="0 0 24 24" width="10" height="10" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
    <path d={up ? "M6 15l6-6 6 6" : "M6 9l6 6 6-6"} />
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
        {t("plans.of", { bot: bot.display_name })}
        {selected ? (
          <button type="button" className="rn-toggle" data-testid="run-list-toggle" aria-expanded={listOpen} onClick={() => setListOpen((v) => !v)}>
            {t("plans.all", { n: runs.length + cli.length })}
            <Chevron up={listOpen} />
          </button>
        ) : (
          <span className="rn-count">{runs.length}</span>
        )}
        <button type="button" className="pn-ref" onClick={() => setN((x) => x + 1)} title={t("plans.refresh")} aria-label={t("plans.refresh")}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" width="12" height="12">
            <path d="M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7" />
          </svg>
        </button>
      </div>
      {runs.length === 0 && (
        <div className="pn-empty">
          {t("plans.none")}
          <br />
          {t("plans.noneHint", { bot: bot.display_name })}
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
          {all ? t("plans.fewer") : t("plans.showAll", { n: runs.length })}
        </button>
      )}
      {lists && cli.length > 0 && (
        <>
          <div className="pn-sec rn-sec2">
            {t("plans.cli")}
            <span>{cli.length}</span>
          </div>
          <ul className={`rn-list${allCli ? " all" : ""}`} data-testid="cli-run-list">
            {shownRuns(cli, allCli, selected?.id).map((r) => (
              <RunRow key={r.id} r={r} on={r.id === selected?.id} nowS={nowS} onPick={picked} testId="cli-run-row" />
            ))}
          </ul>
          {cli.length > LIST_CAP && (
            <button type="button" className="rn-more" data-testid="cli-run-list-more" onClick={() => setAllCli((v) => !v)}>
              {allCli ? t("plans.fewer") : t("plans.showAll", { n: cli.length })}
            </button>
          )}
        </>
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
  // the open node's detail sits under the graph: bring it into view
  const drawer = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (open) drawer.current?.scrollIntoView({ block: "nearest" });
  }, [open]);
  const fullKey = isMac() ? "⌘⇧G" : "Ctrl+Shift+G";
  return (
    <div className="rn-run" data-testid="run-graph-box" data-run={summary.id} data-state={summary.state}>
      <PlanHeader
        summary={summary}
        run={run}
        bot={bot}
        nowS={nowS}
        action={
          <button
            type="button"
            className="ph-full"
            onClick={() => s.setRunsFull(true)}
            data-testid="graph-expand"
            title={`${t("graph.full")} ${fullKey}`}
            aria-label={`${t("graph.full")} ${fullKey}`}
          >
            <ExpandIcon />
          </button>
        }
      />
      <div className="rn-gwrap" ref={ref}>
        {!run || !width ? (
          <div className={`pn-empty${error ? " bad" : ""}`}>{error ?? <Spinner size={12} label="Loading" />}</div>
        ) : (
          <RunGraph
            run={run}
            mode="panel"
            width={width}
            open={open}
            onOpen={setOpen}
            nowS={nowS}
            bot={bot}
            detail={
              node && (
                <div ref={drawer}>
                  <NodeDrawer run={run} node={node} parents={parentsOf(run, node.id)} bot={bot} text={detail!.handoffs[node.id]} nowS={nowS} onClose={() => setOpen(null)} />
                </div>
              )
            }
          />
        )}
      </div>
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
    <div className="rf" data-testid="runs-full" role="dialog" aria-label={t("plans.graph")}>
      <div className="rf-head">
        {selected ? <PlanHeader summary={selected} run={run} bot={bot} nowS={nowS} /> : <b>{t("plans.of", { bot: bot.display_name })}</b>}
        <span className="rf-hint">{t("graph.hint")}</span>
        <IconButton label={t("graph.close")} onClick={() => s.setRunsFull(false)}>
          <CloseIcon />
        </IconButton>
      </div>
      <div className="rf-body" ref={ref}>
        {!runs ? (
          <div className="pn-empty">{error ?? <Spinner size={12} label="Loading" />}</div>
        ) : !selected ? (
          <div className="pn-empty">{t("plans.none")}</div>
        ) : !run || !width ? (
          <div className="pn-empty">
            <Spinner size={12} label="Loading" />
          </div>
        ) : (
          <RunGraph key={run.id} run={run} mode="full" width={width} open={open} onOpen={setOpen} nowS={nowS} bot={bot} />
        )}
        {run && node && (
          <div className="rf-drawer">
            <NodeDrawer run={run} node={node} parents={parentsOf(run, node.id)} bot={bot} text={detail!.handoffs[node.id]} nowS={nowS} onClose={() => setOpen(null)} />
          </div>
        )}
      </div>
    </div>
  );
}
