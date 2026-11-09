// SESSIONS in the sidebar: the `+` menu that starts claude / codex / omh / pi / omp / grok in a folder,
// and one row per session started in this run of the app (live dot while a turn runs, "Needs you" while
// an approval or question waits).
import { useEffect, useState } from "react";
import { useStore, type AppState } from "../state/store";
import { CloseIcon, PlusIcon, Popover } from "../ui";
import { shortTime } from "../app/time";
import { AgentMark } from "./AgentMark";
import { agentDef, folderName, parentPath, rowModel, tildePath, type AgentId, type ChatLive, type SessionRec } from "./agents";
import { getSessions, useSessions } from "./sessions";

export function SessionsHeader() {
  const [open, setOpen] = useState(false);
  return (
    <div className="side-sh side-sh-row">
      <span>Sessions</span>
      <span className="ss-add">
        <button
          type="button"
          className="ss-plus"
          aria-label="New session"
          title="New session"
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
          data-testid="session-new"
        >
          <PlusIcon size={13} />
        </button>
        {open && <NewSessionMenu onClose={() => setOpen(false)} />}
      </span>
    </div>
  );
}

function NewSessionMenu({ onClose }: { onClose: () => void }) {
  const ss = useSessions();
  useEffect(() => {
    void getSessions().loadAgents();
  }, []);
  const go = (agent: AgentId, cwd?: string) => {
    onClose();
    void getSessions().launch(agent, cwd);
  };
  const installed = new Set((ss.agents ?? []).filter((a) => a.path).map((a) => a.id));
  return (
    <Popover open onClose={onClose} align="left" width={232} label="New session" className="ss-pop">
      <div data-testid="session-menu">
        <div className="ss-h">New session</div>
        {ss.agents === null && <div className="ss-empty">Looking for agents…</div>}
        {(ss.agents ?? []).map((a) => {
          const def = agentDef(a.id);
          return (
            <button
              key={a.id}
              type="button"
              className="ss-item"
              disabled={!a.path}
              title={a.path ?? `${def.program} was not found on this computer`}
              onClick={() => go(a.id)}
              data-testid={`session-agent-${a.id}`}
            >
              <span className="ss-ic">
                <AgentMark agent={a.id} />
              </span>
              <span className="ss-n">{def.label}</span>
              {a.path ? <code className="ss-cmd">{def.program}</code> : <span className="ss-missing">Not installed</span>}
            </button>
          );
        })}
        {ss.recent.some((r) => installed.has(r.agent)) && (
          <>
            <div className="ss-sep" />
            <div className="ss-h">Recent</div>
            {ss.recent
              .filter((r) => installed.has(r.agent))
              .map((r) => (
                <button
                  key={`${r.agent}:${r.cwd}`}
                  type="button"
                  className="ss-item"
                  title={`${agentDef(r.agent).label} in ${r.cwd}`}
                  onClick={() => go(r.agent, r.cwd)}
                  data-testid="session-recent"
                >
                  <span className="ss-ic">
                    <AgentMark agent={r.agent} />
                  </span>
                  <span className="ss-n">{folderName(r.cwd)}</span>
                  <span className="ss-path">{parentPath(tildePath(r.cwd, ss.home))}</span>
                </button>
              ))}
          </>
        )}
      </div>
    </Popover>
  );
}

export function SessionList() {
  const s = useStore();
  const ss = useSessions();
  const [confirm, setConfirm] = useState<string | null>(null);
  const current = s.ui.view === "session" ? s.ui.session : null;
  const ask = (rec: SessionRec) => {
    if (rec.status === "running" || rec.status === "starting") setConfirm(rec.id);
    else getSessions().close(rec.id);
  };
  if (ss.list.length === 0) {
    return (
      <div className="ss-none" data-testid="session-none">
        Start Claude Code, Codex or another agent in a folder with <b>+</b>
      </div>
    );
  }
  return (
    <nav className="bot-list ss-list" aria-label="Sessions" data-testid="session-list">
      {ss.list.map((rec) =>
        confirm === rec.id ? (
          <div key={rec.id} className="ss-row ss-confirm" data-testid={`session-confirm-${rec.id}`}>
            <span className="ss-q">Stop {agentDef(rec.agent).label}?</span>
            <button type="button" className="ss-btn" onClick={() => setConfirm(null)} autoFocus>
              Cancel
            </button>
            <button
              type="button"
              className="ss-btn"
              onClick={() => {
                setConfirm(null);
                getSessions().close(rec.id);
              }}
              data-testid="session-stop"
            >
              Stop
            </button>
          </div>
        ) : (
          <Row key={rec.id} rec={rec} active={current === rec.id} onClose={() => ask(rec)} />
        ),
      )}
    </nav>
  );
}

/** The row's view of a session's chat: a turn running, and an approval or question still open. */
function chatLive(s: AppState, key: string | null): ChatLive | undefined {
  const c = key ? s.chats[key] : undefined;
  if (!c) return undefined;
  let needsYou = false;
  if (c.turn) {
    const since = c.turn.startedAt / 1000 - 1;
    needsYou = c.items.some(
      (i) => i.ts >= since && ((i.kind === "approval" && !i.resolved) || (i.kind === "clarify" && i.answer === undefined)),
    );
  }
  return { turn: !!c.turn, needsYou };
}

function Row({ rec, active, onClose }: { rec: SessionRec; active: boolean; onClose: () => void }) {
  const s = useStore();
  const m = rowModel(rec, rec.view === "chat" ? chatLive(s, getSessions().chatKey(rec.id)) : undefined);
  return (
    <div
      className={`ss-row bot${active ? " active" : ""}`}
      data-testid={`session-${rec.id}`}
      data-status={rec.status}
      data-needs-you={m.needsYou ? "true" : undefined}
      onContextMenu={(e) => {
        e.preventDefault();
        onClose();
      }}
    >
      <button
        type="button"
        className="ss-open"
        onClick={() => s.openSession(rec.id)}
        aria-current={active ? "true" : undefined}
        title={rec.cwd}
      >
        <span className="ss-av">
          <AgentMark agent={rec.agent} size={18} />
          {m.live && <span className="live-dot" data-testid="live-dot" aria-label="running" />}
        </span>
        <span className="bot-m">
          <span className="bot-r1">
            <span className="bot-n">{m.title}</span>
            <span className="bot-t">{shortTime(m.ts)}</span>
          </span>
          <span className="bot-r2">
            <span className={`bot-p${m.needsYou ? " ss-needs" : ""}`} data-testid="session-sub">
              {m.sub}
            </span>
          </span>
        </span>
      </button>
      <button type="button" className="ss-x" aria-label="Close session" title="Close session" onClick={onClose} data-testid="session-close">
        <CloseIcon />
      </button>
    </div>
  );
}
