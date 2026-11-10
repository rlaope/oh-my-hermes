// SESSIONS in the sidebar: the `+` menu that starts claude / codex / omh / pi / omp / grok in a folder,
// and one row per session started in this run of the app. A chat row shows the bot row's live states: the
// answer ring around the agent mark and the turn's elapsed time while a turn runs, and the amber dot with
// "waiting" while one of its approvals or questions is open (the same asks the Needs-you strip lists). A
// terminal row keeps a live dot while its program runs: a terminal has no turn to ring for.
import { useEffect, useState } from "react";
import { selectAsks, useStore, type AppState } from "../state/store";
import { ChevronRight, CloseIcon, LiveRing, PlusIcon, Popover, TypingDots } from "../ui";
import { busyFor, shortTime } from "../app/time";
import { useNow } from "../elsewhere/useNow";
import { t } from "../i18n";
import { AgentMark } from "./AgentMark";
import { agentDef, folderName, parentPath, recentFolders, rowModel, tildePath, type AgentId, type ChatLive, type SessionRec } from "./agents";
import { getSessions, useSessions } from "./sessions";
import type { Account, AccountCli, AccountGroup } from "../lib/protocol";
import { useAccounts } from "../settings/accounts/useAccounts";
import { accountForNewSessions } from "../settings/accounts/rules";

/** The Accounts CLI a new session of `agent` signs in as (mirrors `session_cli` in src-tauri/src/accounts.rs). */
const SESSION_CLI: Partial<Record<AgentId, AccountCli>> = { claude: "claude", codex: "codex", grok: "grok" };

/** `work@example.com` -> `work@…`. */
const maskEmail = (email: string) => (email.includes("@") ? `${email.slice(0, email.indexOf("@"))}@…` : email);

/** The quiet "as …" next to an agent in the menu: the account Settings › Accounts picked for new sessions, by
 *  its name, else its masked email. Nothing for "This computer" or an agent without accounts. */
export function sessionAccountSuffix(groups: AccountGroup[] | null, agent: AgentId): string {
  const cli = SESSION_CLI[agent];
  const a: Account | null = cli ? accountForNewSessions(groups, cli) : null;
  if (!a || a.id === "default") return "";
  const name = a.label || maskEmail(a.email) || a.id;
  return `as ${name}`;
}

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
          <PlusIcon size={14} />
        </button>
        {open && <NewSessionMenu onClose={() => setOpen(false)} />}
      </span>
    </div>
  );
}

/** The empty section: one row-sized "New session" button (opens the + menu), the installed agents under it. */
function SessionStart() {
  const ss = useSessions();
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (ss.agents === null) void getSessions().loadAgents();
  }, [ss.agents]);
  const installed = (ss.agents ?? []).filter((a) => a.path).slice(0, 4);
  const names = installed.map((a) => agentDef(a.id).label).join(" · ");
  return (
    <div className="ss-none" data-testid="session-none">
      <div className="ss-start-w">
        <button type="button" className="ss-start" aria-expanded={open} onClick={() => setOpen((v) => !v)} data-testid="session-start">
          <PlusIcon size={14} />
          New session
        </button>
        {open && <NewSessionMenu onClose={() => setOpen(false)} />}
      </div>
      {installed.length > 0 && (
        // each mark next to its name; past two agents the rest show their mark only (all names in the tooltip)
        <div className="ss-start-ag" data-testid="session-start-agents" title={names}>
          {installed.map((a, i) => (
            <span key={a.id} className="ss-start-a">
              {i > 0 && <span className="ss-start-dot">·</span>}
              <AgentMark agent={a.id} size={12} />
              {i < 2 && <span className="ss-start-n">{agentDef(a.id).label}</span>}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

/** The menu spans the section, 8px inside both sidebar edges. */
const MENU_W = "min(240px, calc(var(--side-w) - 16px))";

/** The + menu in two steps: pick an agent, then its folder ("Choose folder…" or one of the recent folders). */
function NewSessionMenu({ onClose }: { onClose: () => void }) {
  const ss = useSessions();
  const accounts = useAccounts();
  /** step 2: the agent picked, asking for its folder */
  const [agent, setAgent] = useState<AgentId | null>(null);
  /** the agent ← came back from, which takes the focus again */
  const [from, setFrom] = useState<AgentId | null>(null);
  useEffect(() => {
    void getSessions().loadAgents();
  }, []);
  if (agent) {
    const back = () => {
      setFrom(agent);
      setAgent(null);
    };
    // the native folder dialog; cancelling it keeps this step open and starts nothing
    const choose = async () => {
      if (await getSessions().launch(agent)) onClose();
    };
    const start = (cwd: string) => {
      onClose();
      void getSessions().launch(agent, cwd);
    };
    const folders = recentFolders(ss.recent);
    return (
      <Popover open onClose={onClose} align="left" width={MENU_W} label="New session" className="ss-pop">
        <div data-testid="session-menu" data-step="folder">
          <div className="ss-agent" data-testid="session-folder-agent">
            <button type="button" className="ss-back" aria-label={t("sessions.back")} title={t("sessions.back")} onClick={back} data-testid="session-back">
              <ChevronRight size={12} />
            </button>
            <AgentMark agent={agent} size={14} />
            <span className="ss-n">{agentDef(agent).label}</span>
          </div>
          <button type="button" className="ss-item" onClick={() => void choose()} autoFocus data-testid="session-choose">
            <span className="ss-ic">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
                <path d="M3 7.5A1.5 1.5 0 0 1 4.5 6h4.4l2 2h8.6A1.5 1.5 0 0 1 21 9.5v8a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 17.5z" />
              </svg>
            </span>
            <span className="ss-n">{t("sessions.choose")}</span>
          </button>
          {folders.length > 0 && (
            <>
              <div className="ss-sep" />
              <div className="ss-h">{t("sessions.recent")}</div>
              {folders.map((cwd) => (
                <button key={cwd} type="button" className="ss-item" title={cwd} onClick={() => start(cwd)} data-testid="session-recent">
                  <span className="ss-ic" />
                  <span className="ss-n">{folderName(cwd)}</span>
                  <span className="ss-path">{parentPath(tildePath(cwd, ss.home))}</span>
                </button>
              ))}
            </>
          )}
        </div>
      </Popover>
    );
  }
  return (
    <Popover open onClose={onClose} align="left" width={MENU_W} label="New session" className="ss-pop">
      <div data-testid="session-menu">
        <div className="ss-h">New session</div>
        {ss.agents === null && <div className="ss-empty">Looking for agents…</div>}
        {(ss.agents ?? []).map((a) => {
          const def = agentDef(a.id);
          const account = sessionAccountSuffix(accounts.groups, a.id);
          return (
            <button
              key={a.id}
              type="button"
              className="ss-item"
              disabled={!a.path}
              title={a.path ?? `${def.program} was not found on this computer`}
              onClick={() => setAgent(a.id)}
              autoFocus={a.id === from}
              data-testid={`session-agent-${a.id}`}
            >
              <span className="ss-ic">
                <AgentMark agent={a.id} />
              </span>
              <span className="ss-n ss-n-as" title={account ? `${def.label} ${account}` : def.label}>
                <span className="ss-l">{def.label}</span>
                {account && (
                  <span className="ss-as" data-testid={`session-account-${a.id}`}>
                    {account}
                  </span>
                )}
              </span>
              {a.path ? <code className="ss-cmd">{def.program}</code> : <span className="ss-missing">Not installed</span>}
            </button>
          );
        })}
      </div>
    </Popover>
  );
}

export function SessionList() {
  const s = useStore();
  const ss = useSessions();
  const [confirm, setConfirm] = useState<string | null>(null);
  const [refocus, setRefocus] = useState<string | null>(null);
  const current = s.ui.view === "session" ? s.ui.session : null;
  useEffect(() => {
    if (!refocus) return;
    // the row itself (its × shows only on hover, so it cannot hold focus)
    document.querySelector<HTMLElement>(`[data-testid="session-${refocus}"] .ss-open`)?.focus();
    setRefocus(null);
  }, [refocus]);
  const cancel = (id: string) => {
    setConfirm(null);
    setRefocus(id);
  };
  const ask = (rec: SessionRec) => {
    if (rec.status === "running" || rec.status === "starting") setConfirm(rec.id);
    else getSessions().close(rec.id);
  };
  if (ss.list.length === 0) return <SessionStart />;
  return (
    <nav className="bot-list ss-list" aria-label="Sessions" data-testid="session-list">
      {ss.list.map((rec) =>
        confirm === rec.id ? (
          <div
            key={rec.id}
            className="ss-row ss-confirm"
            role="group"
            aria-label={`Stop ${agentDef(rec.agent).label} in ${folderName(rec.cwd)}?`}
            data-testid={`session-confirm-${rec.id}`}
            onKeyDown={(e) => {
              if (e.key !== "Escape") return;
              e.preventDefault();
              e.stopPropagation();
              cancel(rec.id);
            }}
          >
            <span className="ss-q" title={rec.cwd}>
              Stop {agentDef(rec.agent).label}?
            </span>
            <button type="button" className="ss-btn" onClick={() => cancel(rec.id)} autoFocus>
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

/** The row's view of a session's chat: a turn running, and an ask of it open (the Needs-you model). */
function chatLive(s: AppState, key: string | null): ChatLive | undefined {
  const c = key ? s.chats[key] : undefined;
  if (!c) return undefined;
  return { turn: !!c.turn, needsYou: selectAsks(s).some((a) => a.bot === key) };
}

function Row({ rec, active, onClose }: { rec: SessionRec; active: boolean; onClose: () => void }) {
  const s = useStore();
  const key = getSessions().chatKey(rec.id);
  const chat = rec.view === "chat" ? chatLive(s, key) : undefined;
  const m = rowModel(rec, chat);
  // a chat answers in turns (ring); a terminal just runs (dot)
  const ring = rec.view === "chat" && m.live && !m.needsYou;
  const dot = rec.view !== "chat" && m.live;
  const busySince = ring && key ? (s.chats[key]?.turn?.startedAt ?? null) : null;
  const now = useNow(busySince !== null, 1_000);
  return (
    <div
      className={`ss-row bot${active ? " active" : ""}${m.needsYou ? " needs" : ""}`}
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
        <LiveRing on={ring} size={34} gap={3.5} label="Answering" seed={rec.id}>
          <span className="ss-av">
            <AgentMark agent={rec.agent} size={18} />
            {dot && <span className="live-dot" data-testid="live-dot" aria-label="running" />}
          </span>
        </LiveRing>
        <span className="bot-m">
          <span className="bot-r1">
            <span className="bot-n">{m.title}</span>
            {m.needsYou ? (
              <span className="bot-t wait" data-testid="bot-time">
                waiting
              </span>
            ) : busySince !== null ? (
              <span className="bot-t busy" data-testid="bot-time">
                {busyFor(now - busySince)}
              </span>
            ) : (
              <span className="bot-t" data-testid="bot-time">
                {shortTime(m.ts)}
              </span>
            )}
          </span>
          <span className="bot-r2">
            <span className={`bot-p${ring ? " live" : ""}`} data-testid="session-sub">
              {m.sub}
            </span>
            {ring && <TypingDots size={3} testId="bot-typing" />}
            {m.needsYou && (
              // the bot row's plain amber dot: no number (the strip carries the count)
              <span className="needs-dot" data-testid="needs" role="status" aria-label="Needs your answer" title="Needs your answer" />
            )}
          </span>
        </span>
      </button>
      <button type="button" className="ss-x" aria-label="Close session" title="Close session" onClick={onClose} data-testid="session-close">
        <CloseIcon />
      </button>
    </div>
  );
}
