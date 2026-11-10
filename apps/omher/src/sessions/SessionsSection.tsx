// SESSIONS in the sidebar: the `+` that opens a New session chat (agent and folder are picked in that chat, see
// DraftPane in SessionView), and one row per session started in this run of the app. A draft row reads "New
// session" over its folder until its first message. A chat row shows the bot row's live states: the
// answer ring around the agent mark and the turn's elapsed time while a turn runs, and the amber dot with
// "waiting" while one of its approvals or questions is open (the same asks the Needs-you strip lists). A
// terminal row keeps a live dot while its program runs: a terminal has no turn to ring for.
// Line 1 is the session's name (the person's, the agent's own title, a summary of the first message, else the
// folder) and line 2 the folder and the agent. Double-click the name, or right-click › Rename, to name it.
import { useEffect, useRef, useState } from "react";
import { selectAsks, useStore, type AppState } from "../state/store";
import { CloseIcon, LiveRing, PlusIcon, TypingDots } from "../ui";
import { busyFor, shortTime } from "../app/time";
import { useNow } from "../elsewhere/useNow";
import { t } from "../i18n";
import { AgentMark } from "./AgentMark";
import { agentDef, folderName, rowModel, type AgentId, type ChatLive, type RowContext, type SessionRec } from "./agents";
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

/** Open a New session chat (the SESSIONS +, its empty-state row, the first-run card): an open draft is reused. */
export function openNewSession(): void {
  getSessions().draft();
}

export function SessionsHeader() {
  return (
    <div className="side-sh side-sh-row">
      <span>Sessions</span>
      <span className="ss-add">
        <button type="button" className="ss-plus" aria-label="New session" title="New session" onClick={openNewSession} data-testid="session-new">
          <PlusIcon size={14} />
        </button>
      </span>
    </div>
  );
}

/** The coding agents the New session tooltip names: the CLIs a person launches to code with (omh stays in the + menu). */
const CODING: AgentId[] = ["claude", "codex", "pi", "omp", "grok"];

/** The empty section: one "New session" row built like the sidebar's nav rows, opening a New session chat. What
 *  it does and the installed coding agents sit in its tooltip; nothing else shows, nothing is centred or boxed. */
function SessionStart() {
  const ss = useSessions();
  useEffect(() => {
    if (ss.agents === null) void getSessions().loadAgents();
  }, [ss.agents]);
  const names = (ss.agents ?? [])
    .filter((a) => a.path && CODING.includes(a.id))
    .map((a) => agentDef(a.id).label)
    .join(", ");
  const tip = names ? `${t("onb.sessionsHint")} ${names}` : t("onb.sessionsHint");
  return (
    <div className="ss-none" data-testid="session-none">
      <button type="button" className="ss-start" title={tip} onClick={openNewSession} data-testid="session-start">
        <PlusIcon size={16} />
        New session
      </button>
    </div>
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
  // a draft's folder is not settled yet: it never makes another row show its parent
  const ctx: RowContext = { cwds: ss.list.filter((r) => r.status !== "draft").map((r) => r.cwd), home: ss.home };
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
          <Row key={rec.id} rec={rec} ctx={ctx} active={current === rec.id} onClose={() => ask(rec)} />
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

/** Right-click menu of a session row: Rename, Close session. Placed at the pointer, inside the window. */
function SessionMenu({ at, name, onRename, onClose, onDismiss }: { at: { x: number; y: number }; name: string; onRename: () => void; onClose: () => void; onDismiss: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    ref.current?.querySelector<HTMLButtonElement>("button")?.focus();
    const onDown = (e: globalThis.MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onDismiss();
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [onDismiss]);
  const items: [string, string, () => void][] = [
    ["Rename", "session-rename", onRename],
    ["Close session", "session-menu-close", onClose],
  ];
  return (
    <div
      ref={ref}
      className="row-menu"
      style={{ left: at.x, top: at.y }}
      role="menu"
      aria-label={`${name} actions`}
      data-testid="session-row-menu"
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.preventDefault();
          e.stopPropagation();
          onDismiss();
          return;
        }
        if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
        e.preventDefault();
        const btns = [...(ref.current?.querySelectorAll<HTMLButtonElement>("button") ?? [])];
        const i = btns.indexOf(document.activeElement as HTMLButtonElement);
        btns[(i + (e.key === "ArrowDown" ? 1 : btns.length - 1)) % btns.length]?.focus();
      }}
    >
      {items.map(([label, id, fn]) => (
        <button
          key={id}
          type="button"
          role="menuitem"
          className="row-mi"
          data-testid={id}
          onClick={() => {
            onDismiss();
            fn();
          }}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

const MENU_SIZE = { w: 168, h: 70 };

/** The name field of a row being renamed: Enter or leaving it saves, Esc cancels, an empty name goes back to the
 *  automatic one. */
function NameInput({ initial, auto, onDone }: { initial: string; auto: boolean; onDone: (title: string | null | undefined) => void }) {
  const ref = useRef<HTMLInputElement>(null);
  const done = useRef(false);
  useEffect(() => {
    ref.current?.focus();
    ref.current?.select();
  }, []);
  const finish = (save: boolean) => {
    if (done.current) return;
    done.current = true;
    const v = (ref.current?.value ?? "").replace(/\s+/g, " ").trim();
    // undefined = leave it as it was; "" = back to the automatic name
    onDone(!save ? undefined : !v ? "" : auto && v === initial ? undefined : v);
  };
  return (
    <input
      ref={ref}
      className="ss-name-in"
      defaultValue={initial}
      maxLength={80}
      aria-label="Session name"
      placeholder="Automatic name"
      spellCheck={false}
      data-testid="session-rename-input"
      onKeyDown={(e) => {
        e.stopPropagation();
        if (e.key === "Enter" && !e.nativeEvent.isComposing) {
          e.preventDefault();
          finish(true);
        } else if (e.key === "Escape") {
          e.preventDefault();
          finish(false);
        }
      }}
      onBlur={() => finish(true)}
    />
  );
}

function Row({ rec, ctx, active, onClose }: { rec: SessionRec; ctx: RowContext; active: boolean; onClose: () => void }) {
  const s = useStore();
  const key = getSessions().chatKey(rec.id);
  const chat = rec.view === "chat" ? chatLive(s, key) : undefined;
  const m = rowModel(rec, chat, ctx);
  const [editing, setEditing] = useState(false);
  const [menu, setMenu] = useState<{ x: number; y: number } | null>(null);
  const wrap = useRef<HTMLDivElement>(null);
  // a chat answers in turns (ring); a terminal just runs (dot)
  const ring = rec.view === "chat" && m.live && !m.needsYou;
  const dot = rec.view !== "chat" && m.live;
  const busySince = ring && key ? (s.chats[key]?.turn?.startedAt ?? null) : null;
  const now = useNow(busySince !== null, 1_000);
  const endEdit = (title: string | null | undefined) => {
    setEditing(false);
    if (title !== undefined) getSessions().rename(rec.id, title);
    requestAnimationFrame(() => wrap.current?.querySelector<HTMLElement>(".ss-open")?.focus());
  };
  const body = (
    <>
      <LiveRing on={ring} size={34} gap={3.5} label="Answering" seed={rec.id}>
        <span className="ss-av">
          <AgentMark agent={rec.agent} size={18} />
          {dot && <span className="live-dot" data-testid="live-dot" aria-label="running" />}
        </span>
      </LiveRing>
      <span className="bot-m">
        <span className="bot-r1">
          {editing ? (
            <NameInput initial={m.title} auto={m.titleSource !== "person"} onDone={endEdit} />
          ) : (
            <span
              className="bot-n"
              data-testid="session-name"
              data-source={m.titleSource}
              title={m.titleSource === "folder" ? undefined : m.title}
              onDoubleClick={(e) => {
                e.preventDefault();
                if (rec.status !== "draft") setEditing(true);
              }}
            >
              {m.title}
              {m.where && (
                <span className="ss-where" data-testid="session-where">
                  {" · "}
                  {m.where}
                </span>
              )}
            </span>
          )}
          {m.needsYou ? (
            <span className="bot-t wait" data-testid="bot-time">
              waiting
            </span>
          ) : busySince !== null ? (
            <span className="bot-t busy" data-testid="bot-time">
              {busyFor(now - busySince)}
            </span>
          ) : rec.status === "draft" ? null : (
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
    </>
  );
  return (
    <div
      ref={wrap}
      className={`ss-row bot${active ? " active" : ""}${m.needsYou ? " needs" : ""}${menu ? " menu-open" : ""}`}
      data-testid={`session-${rec.id}`}
      data-status={rec.status}
      data-needs-you={m.needsYou ? "true" : undefined}
      onContextMenu={(e) => {
        e.preventDefault();
        if (editing) return;
        // a draft has nothing to rename yet: right-click closes it, as before
        if (rec.status === "draft") return onClose();
        const side = wrap.current?.closest(".side")?.getBoundingClientRect();
        const right = (side?.right ?? window.innerWidth) - 6;
        setMenu({ x: Math.max(6, Math.min(e.clientX, right - MENU_SIZE.w)), y: Math.min(e.clientY, window.innerHeight - MENU_SIZE.h - 6) });
      }}
    >
      {editing ? (
        // no button around a text field: the same row, not clickable while the name is edited
        <div className="ss-open ss-editing" title={rec.cwd}>
          {body}
        </div>
      ) : (
        <button
          type="button"
          className="ss-open"
          onClick={() => s.openSession(rec.id)}
          aria-current={active ? "true" : undefined}
          title={rec.cwd}
        >
          {body}
        </button>
      )}
      {!editing && (
        <button type="button" className="ss-x" aria-label="Close session" title="Close session" onClick={onClose} data-testid="session-close">
          <CloseIcon />
        </button>
      )}
      {menu && <SessionMenu at={menu} name={m.title} onRename={() => setEditing(true)} onClose={onClose} onDismiss={() => setMenu(null)} />}
    </div>
  );
}
