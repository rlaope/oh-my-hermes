// A SESSIONS chat's right panel: Plans for that session alone. The agent's own record of the subagents this
// session started (`runs.cli` for its agent and folder, the run whose owner is the session's agent id), drawn with
// the same header, graph and node detail as a bot's Plans, re-read while the session works and when a subagent
// moves. Before the agent's record exists, the subagents the chat has seen are listed from the chat itself.
// Read-only: nothing here assigns, steers or stops a subagent.
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { Bot } from "../lib/protocol";
import type { AgentRun, AgentRunSummary, CliAgent, RunDetail } from "../lib/runs";
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
import { folderName } from "./agents";
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
function SessionGraph({ run, nowS }: { run: AgentRun; nowS: number }) {
  const [open, setOpen] = useState<string | null>(null);
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
          onOpen={setOpen}
          nowS={nowS}
          detail={node && <NodeDrawer run={run} node={node} nowS={nowS} onClose={() => setOpen(null)} />}
        />
      )}
    </div>
  );
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

/** The panel for the session on screen, or nothing. */
export function SessionPanel({ onClose }: { onClose: () => void }) {
  const s = useStore();
  const ss = useSessions();
  const rec = ss.list.find((r) => r.id === s.ui.session) ?? null;
  if (!rec) return null;
  const key = getSessions().chatKey(rec.id);
  return <SessionPlans key={rec.id} rec={rec} chat={key ? s.chats[key] : undefined} onClose={onClose} />;
}
