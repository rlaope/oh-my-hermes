// A SESSIONS chat's right panel: Plans for that session alone. The agent's own record of the subagents this
// session started (`runs.cli` for its agent and folder, the run whose owner is the session's agent id), drawn with
// the same header, graph and node detail as a bot's Plans, re-read while the session works and when a subagent
// moves. Before the agent's record exists, the subagents the chat has seen are listed from the chat itself.
// Read-only: nothing here assigns, steers or stops a subagent. A TERMINALS session in a split gets the split drawn
// small at the top (each pane a rounded box in the layout's proportions with its CLI mark and title, the focused one
// filled); a click on a box focuses that pane, and the Plans below follow it.
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { Bot } from "../lib/protocol";
import { RunEvidence } from "./dag/Evidence";
import type { AgentRun, AgentRunSummary, CliAgent, RunDetail, RunNode } from "../lib/runs";
import { CLI_AGENTS } from "../lib/runs";
import { getStore, useStore, subagentEnded, type Chat, type SubagentRow } from "../state/store";
import { CloseIcon, IconButton, Spinner } from "../ui";
import { useNow } from "../elsewhere/useNow";
import { t } from "../i18n";
import { RunGraph } from "../runs/RunGraph";
import { NodeDrawer } from "../runs/NodeDrawer";
import { PlanHeader } from "../runs/PlanHeader";
import { LIVE_POLL_MS } from "../runs/live";
import { SubagentLine, waitingSubs } from "../chat/activity/Subagents";
import { getSessions, useSessions } from "./sessions";
import type { SessionRec } from "./agents";
import { folderName, splitPaneName, termMarkAgent } from "./agents";
import { TermRowMark } from "./TermRowMark";
import { focusSplitPane } from "./SplitView";
import { groupOf, sessionOf, useSplit } from "./splitState";
import { paneRects } from "../terminal/layout";
import { pickTitle } from "./titles";
import "../runs/runs.css";

/** The Plans graph's run id of a session: `<agent>:<its agent session id>`, for the agents whose records omher
 *  reads (rule 16). */
export function sessionRunId(rec: Pick<SessionRec, "agent" | "agentSession">): string | null {
  if (!rec.agentSession || !(CLI_AGENTS as string[]).includes(rec.agent)) return null;
  return `${rec.agent}:${rec.agentSession}`;
}

/** The subagents a session's chat has seen, newest fan-out last. */
export function chatSubagents(chat: Chat | undefined): SubagentRow[] {
  if (!chat) return [];
  return chat.items.flatMap((i) => (i.kind === "activity" ? (i.turn.fanouts ?? []).flatMap((f) => f.subs) : []));
}

/** How many of a session's subagents are at work now (the header button's live dot). */
export const workingSubagents = (chat: Chat | undefined) => chatSubagents(chat).filter((s) => !subagentEnded(s)).length;

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

/** The session's run from the agent's own files, re-read every few seconds while a subagent works and once more
 *  when one ends. Null until found (the agent writes its record as it goes). */
function useSessionRun(rec: SessionRec, working: number, moved: string) {
  const runId = sessionRunId(rec);
  const [got, setGot] = useState<{ summary: AgentRunSummary; detail: RunDetail } | null>(null);
  const [n, setN] = useState(0);
  useEffect(() => {
    if (!runId) return;
    let live = true;
    const a = getStore().actions;
    a.runsCli({ agent: rec.agent as CliAgent, cwd: rec.cwd, since: Math.floor(rec.startedAt / 1000) - 60 })
      .then((r) => {
        const summary = r.runs.find((x) => x.id === runId);
        if (!summary) return live && setGot(null);
        // a CLI run is found by its id alone: no bot is named
        return a.runsGet("", runId).then((detail) => live && setGot({ summary, detail }));
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [runId, rec.cwd, rec.agent, rec.startedAt, n, moved]);
  useEffect(() => {
    if (!working) return;
    const h = setInterval(() => setN((x) => x + 1), LIVE_POLL_MS);
    return () => clearInterval(h);
  }, [working]);
  return got;
}

/** The graph, measured once it is on screen (it mounts when the agent's record is found). */
function SessionGraph({ run, nowS, text, onNode, selectedNode, inertHandoff = false }: { run: AgentRun; nowS: number; text?: string; onNode?: (node: string | null) => void; selectedNode?: string | null; inertHandoff?: boolean }) {
  const [localOpen, setOpen] = useState<string | null>(null);
  const open = selectedNode === undefined ? localOpen : selectedNode;
  const [ref, width] = useWidth<HTMLDivElement>();
  const node = run.nodes.find((x) => x.id === open) ?? null;
  return (
    <div className="rn-gwrap" ref={ref}>
      {!width ? (
        <div className="pn-empty">
          <Spinner size={12} label={t("pn.loading")} />
        </div>
      ) : (
        <RunGraph
          run={run}
          mode="panel"
          width={width}
          open={open}
          onOpen={(id) => { setOpen(id); onNode?.(id); }}
          nowS={nowS}
          detail={node && <NodeDrawer run={run} node={node} text={text} inertHandoff={inertHandoff} nowS={nowS} onClose={() => { setOpen(null); onNode?.(null); }} />}
        />
      )}
    </div>
  );
}

function scopedRunIds(bot: string, stored: string, runs: AgentRunSummary[]): AgentRunSummary[] {
  return runs.filter((r) => r.kind === "dag" && r.id.startsWith(`dag:${stored}/`) && r.owner.type === "bot" && r.owner.id === bot);
}

/** Read-only scoped DAG evidence. A selected folder key is a route, never a raw session-id grant. */
function OmhSessionPlans({ rec, chat, onClose }: { rec: SessionRec; chat: Chat | undefined; onClose: () => void }) {
  const conn = useStore().conn;
  const attachment = getSessions().folderAttachment(rec.id);
  const fid = attachment?.fid;
  const stored = attachment?.stored ?? "";
  const botName = attachment?.bot ?? "";
  const [tick, setTick] = useState(0);
  const [scopeRuns, setScopeRuns] = useState<{ scope: string; runs: AgentRunSummary[] } | null>(null);
  const folderScope = JSON.stringify([botName, fid, stored]);
  const scope = `${folderScope}:${conn}`;
  const runs = scopeRuns?.scope === scope ? scopeRuns.runs : [];
  const [selection, setSelection] = useState<{ scope: string; run: string; node: string | null } | null>(null);
  const selected = selection?.scope === folderScope ? selection : null;
  const [detail, setDetail] = useState<{ scope: string; value: RunDetail } | null>(null);
  const [handoff, setHandoff] = useState<{ scope: string; run: string; node: string; value: { node: RunNode; text: string } } | null>(null);
  const [error, setError] = useState("");
  const listFence = useRef(0);
  const detailFence = useRef(0);
  const nodeFence = useRef(0);
  const scopeRef = useRef("");
  const inScope = scopeRef.current === scope && conn === "open" && !!fid;
  const run = inScope ? runs.find((r) => r.id === selected?.run) ?? runs[0] : undefined;
  const runId = run?.id;
  const selectedNode = selected?.run === runId ? selected?.node ?? null : null;
  const shownDetail = detail?.scope === scope && detail.value.run.id === runId ? detail.value : null;
  const shownHandoff = handoff?.scope === scope && handoff.run === runId && handoff.node === selectedNode ? handoff.value : undefined;
  useEffect(() => {
    const refresh = () => setTick((n) => n + 1);
    const foreground = () => { if (!document.hidden) refresh(); };
    document.addEventListener("visibilitychange", foreground);
    window.addEventListener("focus", refresh);
    const timer = window.setInterval(() => { if (!document.hidden) refresh(); }, 15000);
    return () => { document.removeEventListener("visibilitychange", foreground); window.removeEventListener("focus", refresh); window.clearInterval(timer); };
  }, []);
  useEffect(() => {
    // Reconnect drops cached data, not the same folder's run and node selection.
    const changedScope = scopeRef.current !== scope;
    const token = ++listFence.current;
    scopeRef.current = scope;
    ++detailFence.current;
    if (changedScope) { ++nodeFence.current; setScopeRuns(null); setDetail(null); setHandoff(null); }
    setSelection((previous) => previous?.scope === folderScope ? previous : null);
    setError("");
    if (!fid || !botName || conn !== "open") return;
    getStore().actions.runsSessionList(botName, fid).then(({ runs: found }) => {
      if (listFence.current === token && scopeRef.current === scope) setScopeRuns({ scope, runs: scopedRunIds(botName, stored, found) });
    }).catch((e: unknown) => { if (listFence.current === token && scopeRef.current === scope) { setScopeRuns(null); setDetail(null); setHandoff(null); setError(String(e)); } });
    return () => { ++listFence.current; };
  }, [botName, fid, stored, tick, conn, folderScope, scope]);
  useEffect(() => {
    const token = ++detailFence.current;
    if (detail?.scope !== scope || detail.value.run.id !== runId) { ++nodeFence.current; setDetail(null); setHandoff(null); }
    if (!fid || !runId || conn !== "open") return;
    getStore().actions.runsSessionGet(botName, fid, runId).then((found) => {
      if (detailFence.current === token && scopeRef.current === scope && found.run.id === runId && found.run.owner.id === botName) setDetail({ scope, value: found });
    }).catch((e: unknown) => { if (detailFence.current === token && scopeRef.current === scope) { setDetail(null); setHandoff(null); setError(String(e)); } });
    return () => { ++detailFence.current; };
  }, [botName, fid, runId, tick, conn, scope]);
  const onNode = (node: string | null) => {
    if (!runId) return;
    ++nodeFence.current;
    setSelection({ scope: folderScope, run: runId, node });
    setHandoff(null);
  };
  useEffect(() => {
    const token = ++nodeFence.current;
    if (!selectedNode || !fid || !runId || conn !== "open") return;
    const node = selectedNode;
    getStore().actions.runsSessionGet(botName, fid, runId, node).then((found) => {
      const item = found.run.nodes.find((n) => n.id === node);
      if (nodeFence.current === token && scopeRef.current === scope && found.run.id === runId && found.run.owner.id === botName && item)
        setHandoff({ scope, run: runId, node, value: { node: item, text: Object.hasOwn(found.handoffs, node) ? found.handoffs[node] : "" } });
    }).catch((e: unknown) => { if (nodeFence.current === token && scopeRef.current === scope) { setHandoff(null); setError(String(e)); } });
    return () => { ++nodeFence.current; };
  }, [botName, fid, runId, selectedNode, tick, conn, scope]);
  const nowS = Date.now() / 1000;
  const subs = chatSubagents(chat);
  const waiting = waitingSubs(chat?.items);
  return <div className="details-in ew-panel pn-wide" data-testid="details-panel" data-tab="runs">
    <div className="details-h pn-tabs">
      <span className="pn-tab on">{t("plans.tab")}</span>
      <IconButton label={t("pn.close")} onClick={onClose}><CloseIcon /></IconButton>
    </div>
    <div className="pn-body rn" data-testid="session-dag-panel" data-session={rec.id}>
      <SplitMap rec={rec} />
      <h2 className="pn-sec">{t("plans.dag")}</h2>
      {!fid && <p>{t("plans.dagUnavailable")}</p>}
      {error && <p role="alert">{t("plans.dagFailed", { error })}</p>}
      {inScope && runs.length > 0 && <nav className="dag-picks" aria-label={t("plans.dagRuns")}>{runs.map((r) =>
        <button key={r.id} type="button" aria-pressed={runId === r.id} onClick={() => {
          if (r.id === runId) return;
          ++nodeFence.current;
          setSelection({ scope: folderScope, run: r.id, node: null });
        }}>{r.title || r.id}</button>
      )}</nav>}
      {fid && !error && !runs.length && <p role="status">{t(conn !== "open" ? "plans.dagUnavailable" : scopeRuns?.scope === scope ? "plans.dagNone" : "pn.loading")}</p>}
      {inScope && run && shownDetail && <div className="rn-run" data-testid="run-graph-box" data-run={run.id} data-state={run.state}>
        <RunEvidence run={shownDetail.run} selected={selectedNode} onNode={onNode} evidence={shownHandoff} />
      </div>}
      {!shownDetail && subs.length > 0 && <div className="sa-rows ss-plans-rows" data-testid="session-plans-rows">
        {subs.map((sub) => <SubagentLine key={sub.id} sub={sub} now={nowS * 1000} live={!!chat?.turn || !subagentEnded(sub)} waiting={waiting.has(sub.id)} />)}
      </div>}
    </div>
  </div>;
}

export function SessionPlans({ rec, chat, onClose }: { rec: SessionRec; chat: Chat | undefined; onClose: () => void }) {
  const subs = chatSubagents(chat);
  const waiting = waitingSubs(chat?.items);
  const working = subs.filter((x) => !subagentEnded(x)).length;
  // a subagent that ended (or a new one) re-reads the record at once
  const moved = subs.map((x) => `${x.id}:${x.state}`).join(",");
  const got = useSessionRun(rec, working, moved);
  // the same clock as the chat's card, which re-reads it every quarter second
  const nowMs = useNow(working > 0, 250);
  const nowS = nowMs / 1000;
  const name = pickTitle(rec, folderName(rec.cwd)).title;
  // the record's own title is the agent's ("Claude Code session" when it wrote none): the session row's name reads
  const summary = got ? { ...got.summary, title: name } : null;
  const run: AgentRun | undefined = got?.detail.run ? { ...got.detail.run, title: name } : undefined;
  // the graph's header names the CLI; its mark stands in for a bot
  const bot = { name: "", display_name: name, is_default: false, model: rec.model ?? "", provider: "", description: "", status: "online", running: false } as Bot;
  return (
    <div className="details-in ew-panel pn-wide" data-testid="details-panel" data-tab="runs">
      <div className="details-h pn-tabs" role="tablist" aria-label={t("pn.panel")}>
        <button type="button" role="tab" aria-selected className="pn-tab on" data-testid="panel-tab-runs">
          <span>{t("plans.tab")}</span>
        </button>
        <IconButton label={t("pn.close")} onClick={onClose}>
          <CloseIcon />
        </IconButton>
      </div>
      <div className="pn-body rn" data-testid="panel-runs" data-session={rec.id}>
        <SplitMap rec={rec} />
        <div className="pn-sec">{t("plans.session")}</div>
        {summary && run ? (
          <div className="rn-run" data-testid="run-graph-box" data-run={summary.id} data-state={summary.state}>
            <PlanHeader summary={summary} run={run} bot={bot} nowS={nowS} />
            <SessionGraph run={run} nowS={nowS} />
          </div>
        ) : subs.length ? (
          // the agent has not written its record yet (or keeps none omher reads): the chat's own rows
          <div className="sa-rows ss-plans-rows" data-testid="session-plans-rows">
            {subs.map((x) => (
              <SubagentLine key={x.id} sub={x} now={nowMs} live={!!chat?.turn || !subagentEnded(x)} waiting={waiting.has(x.id)} />
            ))}
          </div>
        ) : (
          <div className="pn-empty rn-empty" data-testid="plans-empty">
            <div>{t("plans.sessionNone")}</div>
          </div>
        )}
      </div>
    </div>
  );
}

/** The split the session is in, drawn small: a box per pane in the layout's proportions (CLI mark and title), the
 *  focused one filled; a click focuses that pane. Nothing when the session is not in a split. */
function SplitMap({ rec }: { rec: SessionRec }) {
  const sp = useSplit();
  const ss = useSessions();
  const g = groupOf(sp.groups, rec.id);
  if (!g) return null;
  const rects = [...paneRects(g.layout)];
  return (
    <>
      <div className="pn-sec">{t("split.map")}</div>
      <div className="ss-map" data-testid="split-map" data-panes={rects.length}>
        {rects.map(([n, r]) => {
          const id = sessionOf(n);
          const row = ss.list.find((x) => x.id === id);
          if (!row) return null;
          const name = splitPaneName(row, ss.agents);
          const on = id === rec.id;
          return (
            <button
              key={id}
              type="button"
              className={`ss-map-box${on ? " on" : ""}`}
              style={{ left: `${r.x * 100}%`, top: `${r.y * 100}%`, width: `${r.w * 100}%`, height: `${r.h * 100}%` }}
              aria-pressed={on}
              aria-label={t("split.mapFocus", { name })}
              title={name}
              data-testid="split-map-box"
              data-session={id}
              data-focused={on ? "true" : "false"}
              onClick={() => focusSplitPane(id)}
            >
              <span className="ss-map-in">
                <TermRowMark agent={termMarkAgent(row)} size={12} />
                <span className="ss-map-name">{name}</span>
              </span>
            </button>
          );
        })}
      </div>
    </>
  );
}

/** The panel for the session on screen, or nothing. */
export function SessionPanel({ onClose }: { onClose: () => void }) {
  const s = useStore();
  const ss = useSessions();
  const rec = ss.list.find((r) => r.id === s.ui.session) ?? null;
  if (!rec) return null;
  const key = getSessions().chatKey(rec.id);
  if (rec.agent === "omh" && rec.open !== "terminal" && rec.view === "chat") return <OmhSessionPlans key={rec.id} rec={rec} chat={key ? s.chats[key] : undefined} onClose={onClose} />;
  return <SessionPlans key={rec.id} rec={rec} chat={key ? s.chats[key] : undefined} onClose={onClose} />;
}
