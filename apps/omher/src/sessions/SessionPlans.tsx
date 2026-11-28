// A SESSIONS chat's right panel: Plans for that session alone. The agent's own record of the subagents this
// session started (`runs.get` by the session's agent id, else `runs.cli` for its agent and folder), drawn with
// the same header, graph and node detail as a bot's Plans, re-read while the session works and when a subagent
// moves. Before the agent's record exists, the subagents the chat has seen are listed from the chat itself.
// Read-only: nothing here assigns, steers or stops a subagent. A TERMINALS session in a split gets the split drawn
// small at the top (each pane a rounded box in the layout's proportions with its CLI mark and title, the focused one
// filled); a click on a box focuses that pane, and the panel below follows it. Under the map, what the focused pane
// runs (SessionDetails): a Shell row with Claude Code or Codex typed in it is read as that harness, its run found by the
// conversation id the shell named (`fgSession`), as an agent row's is by its own (`agentSession`).
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { Bot } from "../lib/protocol";
import type { AgentRun, AgentRunSummary, CliAgent, RunDetail } from "../lib/runs";
import { CLI_AGENTS, countsOf } from "../lib/runs";
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
import { useServerMode } from "../app/remote";
import { paneHarness } from "./paneHarness";
import { SessionDetails } from "./SessionDetails";
import { fgName } from "./TermRowMark";
import { termActs } from "./termActivity";
import "../runs/runs.css";

/** The Plans graph's run id of a session: `<agent>:<its agent session id>`, for the agents whose records omher
 *  reads (rule 16); for a Shell row, the CLI in its front and the conversation the shell named (paneHarness). */
export function sessionRunId(rec: Pick<SessionRec, "agent" | "agentSession" | "fgAgent" | "fgSession">): string | null {
  return paneHarness(rec).runId;
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

type RunReader = Pick<ReturnType<typeof getStore>["actions"], "runsGet" | "runsCli">;

/** A session's run: read by its own id (`runs.get`; a CLI run needs no bot), so a resumed conversation older than any
 *  list window keeps its subagents; only when that read fails, looked up in its folder's list (`runs.cli`, from
 *  `since`) and read from there. Null when neither has it. */
export async function readSessionRun(
  a: RunReader,
  runId: string,
  agent: CliAgent,
  cwd: string,
  since?: number,
): Promise<{ id: string; summary: AgentRunSummary; detail: RunDetail } | null> {
  try {
    const detail = await a.runsGet("", runId);
    const { nodes, ...run } = detail.run;
    return { id: runId, summary: { ...run, counts: countsOf({ nodes }) }, detail };
  } catch {
    const r = await a.runsCli({ agent, cwd, ...(since !== undefined ? { since } : {}) });
    const summary = r.runs.find((x) => x.id === runId);
    if (!summary) return null;
    return { id: runId, summary, detail: await a.runsGet("", runId) };
  }
}

/** The session's run from the agent's own files, re-read every few seconds while a subagent works and once more
 *  when one ends. Null until found (the agent writes its record as it goes). */
function useSessionRun(rec: SessionRec, working: number, moved: string) {
  const h = paneHarness(rec);
  const runId = h.runId;
  // a harness typed in a Shell row runs where the shell is now (OSC 7), which may not be where the row started
  const cwd = h.inShell ? (termActs.get(rec.id).cwd ?? rec.cwd) : rec.cwd;
  const [got, setGot] = useState<{ id: string; summary: AgentRunSummary; detail: RunDetail } | null>(null);
  const [n, setN] = useState(0);
  useEffect(() => {
    if (!runId || !h.runAgent) return;
    let live = true;
    const a = getStore().actions;
    // a conversation typed in a shell (or resumed there) can be older than the row: its own id finds it
    const since = h.inShell ? undefined : Math.floor(rec.startedAt / 1000) - 60;
    readSessionRun(a, runId, h.runAgent, cwd, since)
      .then((r) => live && setGot(r))
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [runId, cwd, h.runAgent, h.inShell, rec.startedAt, n, moved]);
  // a shell's harness has no chat to say a subagent moved: its record is re-read while the pane is shown
  const poll = working > 0 || (h.inShell && !!runId);
  useEffect(() => {
    if (!poll) return;
    const t = setInterval(() => setN((x) => x + 1), LIVE_POLL_MS);
    return () => clearInterval(t);
  }, [poll]);
  return got && got.id === runId ? got : null;
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
  const nowMs = useNow(working > 0 || got?.summary.state === "running", 250);
  const nowS = nowMs / 1000;
  const h = paneHarness(rec);
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
        <SessionDetails rec={rec} />
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
            <div>
              {h.inShell && h.cli
                ? h.runAgent
                  ? t("plans.harnessNone", { name: fgName(h.cli) })
                  : t("plans.harnessUnread", { name: fgName(h.cli) })
                : t("plans.sessionNone")}
            </div>
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
  // on a server (rule 47) a session of this computer has no Plans: the server cannot read its agent's records here
  const remote = useServerMode().mode === "remote";
  const rec = ss.list.find((r) => r.id === s.ui.session) ?? null;
  if (!rec || remote) return null;
  const key = getSessions().chatKey(rec.id);
  return <SessionPlans key={rec.id} rec={rec} chat={key ? s.chats[key] : undefined} onClose={onClose} />;
}
