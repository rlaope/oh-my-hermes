// Runs tab: the bot's agent runs (OMH dag runs today) as a list and a read-only layered graph. Nothing
// here retries, settles or cancels anything: steering stays in the chat.
import { useEffect, useMemo, useState } from "react";
import type { Bot } from "../lib/protocol";
import { span, sortRuns, type AgentRunSummary, type RunDetail, type RunNode } from "../lib/runs";
import { getStore, useStore } from "../state/store";
import { Markdown } from "../chat/parts/Markdown";
import { CloseIcon, IconButton, Spinner } from "../ui";
import { useNow } from "./useNow";
import "./runs.css";

const CARD_W = 112;
const COL = 136; // card + gap: the column step
const CARD_H = 44;
const ROW = 54; // card + gap: the row step
const PAD = 8;
const PREVIEW = 1200; // handoff chars shown before "Show all"

const GLYPH: Record<RunNode["state"], string> = {
  done: "✓",
  running: "●",
  failed: "✕",
  blocked: "!",
  parked: "‖",
  waiting: "○",
  cancelled: "–",
};

const act = () => getStore().actions;
const nodeTime = (n: RunNode, nowS: number) => (n.started === undefined ? null : span((n.ended ?? nowS) - n.started));
const meta = (n: RunNode) => n.model || (n.category && !n.category.startsWith("unspecified") ? n.category : "") || n.lane || "";

export function RunsTab({ bot }: { bot: Bot }) {
  const s = useStore();
  const [list, setList] = useState<{ bot: string; runs: AgentRunSummary[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [n, setN] = useState(0);
  useEffect(() => {
    let live = true;
    setError(null);
    act()
      .runsList(bot.name)
      .then(
        (r) => live && setList({ bot: bot.name, runs: sortRuns(r.runs) }),
        (e) => live && setError(String(e?.message ?? e)),
      );
    return () => {
      live = false;
    };
  }, [bot.name, n]);
  const runs = list?.bot === bot.name ? list.runs : null;
  const nowMs = useNow(!!runs?.some((r) => r.state === "running"));
  if (!runs)
    return (
      <div className={`pn-empty${error ? " bad" : ""}`}>{error ?? <Spinner size={12} label="Loading" />}</div>
    );
  const selected = runs.find((r) => r.id === s.ui.runId) ?? runs[0] ?? null;
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
                aria-current={r.id === selected?.id ? "true" : undefined}
                onClick={() => s.openRun(r.id)}
                title={r.goal || r.title}
              >
                {r.state === "running" ? <i className="rn-live" aria-label="running" /> : <i className="rn-dot" />}
                <span className="rn-title">{r.title}</span>
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
      {selected && <RunGraph key={selected.id} bot={bot} summary={selected} nowS={nowS} />}
    </div>
  );
}

function RunGraph({ bot, summary, nowS }: { bot: Bot; summary: AgentRunSummary; nowS: number }) {
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    act()
      .runsGet(bot.name, summary.id)
      .then(
        (d) => live && setDetail(d),
        (e) => live && setError(String(e?.message ?? e)),
      );
    return () => {
      live = false;
    };
    // re-read when the list shows the run changed
  }, [bot.name, summary.id, summary.updated]);

  const layout = useMemo(() => {
    if (!detail) return null;
    const cols: RunNode[][] = [];
    for (const n of detail.run.nodes) (cols[n.layer] ??= []).push(n);
    const pos = new Map<string, { x: number; y: number }>();
    cols.forEach((col, i) => col.forEach((n, j) => pos.set(n.id, { x: PAD + i * COL, y: PAD + j * ROW })));
    const rows = Math.max(1, ...cols.map((c) => c?.length ?? 0));
    const edges = detail.run.nodes.flatMap((n) =>
      n.deps.map((d) => {
        const a = pos.get(d)!;
        const b = pos.get(n.id)!;
        const x1 = a.x + CARD_W;
        const y1 = a.y + CARD_H / 2;
        const x2 = b.x;
        const y2 = b.y + CARD_H / 2;
        const k = (x2 - x1) / 2;
        return { key: `${d}>${n.id}`, d: `M${x1},${y1} C${x1 + k},${y1} ${x2 - k},${y2} ${x2},${y2}` };
      }),
    );
    return { pos, edges, w: PAD * 2 + cols.length * COL - (COL - CARD_W), h: PAD * 2 + rows * ROW - (ROW - CARD_H), cols: cols.length };
  }, [detail]);

  if (!detail || !layout) return <div className={`pn-empty${error ? " bad" : ""}`}>{error ?? <Spinner size={12} label="Loading" />}</div>;
  const run = detail.run;
  const node = run.nodes.find((x) => x.id === open) ?? null;
  return (
    <div className="rn-run" data-testid="run-graph-box" data-run={run.id} data-state={run.state}>
      <div className="rn-head">
        <b title={run.title}>{run.title}</b>
        <span className={`rn-state ${run.state}`} data-testid="run-state">
          {run.state === "running" ? "Running" : run.state === "done" ? "Done" : run.state === "failed" ? "Failed" : "Cancelled"}
        </span>
      </div>
      {run.goal && <div className="rn-goal">{run.goal}</div>}
      <div className="rn-graph" data-testid="run-graph" data-cols={layout.cols}>
        <div className="rn-canvas" style={{ width: layout.w, height: layout.h }}>
          <svg className="rn-edges" width={layout.w} height={layout.h} aria-hidden>
            {layout.edges.map((e) => (
              <path key={e.key} d={e.d} data-testid="run-edge" />
            ))}
          </svg>
          {run.nodes.map((x) => {
            const p = layout.pos.get(x.id)!;
            const t = nodeTime(x, nowS);
            const m = meta(x);
            return (
              <button
                key={x.id}
                type="button"
                className={`rn-card st-${x.state}${x.state === "failed" ? " bad" : ""}${x.id === open ? " on" : ""}`}
                style={{ left: p.x, top: p.y, width: CARD_W, height: CARD_H }}
                data-testid="run-node"
                data-node={x.id}
                data-layer={x.layer}
                data-state={x.state}
                onClick={() => setOpen(x.id === open ? null : x.id)}
              >
                <span className="rn-l">
                  <i className="rn-g" aria-label={x.state}>
                    {GLYPH[x.state]}
                  </i>
                  <span className="rn-lt" title={x.label}>
                    {x.label}
                  </span>
                </span>
                <span className="rn-m">{[m, t].filter(Boolean).join(" · ") || x.state}</span>
              </button>
            );
          })}
        </div>
      </div>
      {node && <NodeDrawer bot={bot} node={node} text={detail.handoffs[node.id]} nowS={nowS} onClose={() => setOpen(null)} />}
    </div>
  );
}

function NodeDrawer({ bot, node, text, nowS, onClose }: { bot: Bot; node: RunNode; text?: string; nowS: number; onClose: () => void }) {
  const [all, setAll] = useState(false);
  useEffect(() => setAll(false), [node.id]);
  const last = node.attempts[node.attempts.length - 1];
  const model = node.model ? `${node.model}${node.effort ? `:${node.effort}` : ""}` : "";
  const facts = [model, node.lane, nodeTime(node, nowS)].filter(Boolean).join(" · ");
  const long = (text?.length ?? 0) > PREVIEW;
  return (
    <div className={`rn-drawer st-${node.state}`} data-testid="run-drawer">
      <div className="rn-dh">
        <i className={`rn-g st-${node.state}`}>{GLYPH[node.state]}</i>
        <b title={node.label}>{node.label}</b>
        <IconButton label="Close node" onClick={onClose}>
          <CloseIcon />
        </IconButton>
      </div>
      <div className="rn-df">
        <span data-testid="run-attempt">
          {node.attempts.length ? `attempt ${last.n} of ${node.attempts.length}` : "not started"}
        </span>
        <span>{node.state}</span>
        {facts && <span className="mono">{facts}</span>}
      </div>
      {last?.reason && (
        <div className={`rn-reason${node.state === "failed" || node.state === "blocked" ? " bad" : ""}`} data-testid="run-reason">
          {last.reason}
        </div>
      )}
      {node.attempts.length > 1 && (
        <ol className="rn-atts">
          {node.attempts.slice(0, -1).map((a) => (
            <li key={a.n}>
              <span className="mono">#{a.n} {a.outcome}</span>
              {a.reason && <span> · {a.reason}</span>}
            </li>
          ))}
        </ol>
      )}
      {text ? (
        <>
          <div className="rn-md md" data-testid="run-handoff">
            <Markdown text={all || !long ? text : text.slice(0, PREVIEW) + " …"} />
          </div>
          {long && (
            <button type="button" className="pn-more" onClick={() => setAll((v) => !v)} data-testid="run-handoff-more">
              {all ? "Show less" : "Show all"}
            </button>
          )}
        </>
      ) : (
        <div className="rn-none">No handoff written.</div>
      )}
      {(node.state === "failed" || node.state === "blocked") && (
        <div className="rn-hint">Ask {bot.display_name} in chat to retry.</div>
      )}
    </div>
  );
}
