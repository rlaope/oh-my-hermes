// Main column for a SESSIONS entry: a header (agent mark, the session's name, the agent and folder, status, the
// Terminal toggle and the model button) above either the chat (the bot chat's own Timeline and Composer, fed by
// the agent's structured mode) or the agent's terminal. A New session (draft) is a chat that has not started, on the
// agent picked in the SESSIONS + menu: its composer shows that agent read-only and, under it, the folder chip; the
// first message starts the agent there (Start, for an agent that opens in its terminal). After that the folder is
// read-only too. A chat agent's composer takes files as the bot chat's does (paste, the + menu, a drop on the chat),
// in a draft too; a file dropped or pasted on a terminal is saved and its path typed at the prompt.
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { ITheme } from "@xterm/xterm";
import { selectAsks, useStore, type OutFile } from "../state/store";
import { resolveTheme } from "../app/theme";
import { Timeline } from "../chat/parts/Timeline";
import { Composer } from "../chat/parts/Composer";
import { CheckIcon } from "../chat/model/CheckIcon";
import "../chat/model/model.css";
import { ArrowUp, ChatIcon, ChevronDown, ModelIcon, Popover, TerminalIcon } from "../ui";
import type { Bot } from "../lib/protocol";
import { AgentMark } from "./AgentMark";
import { SessionFace } from "./SessionFace";
import { agentDef, CONTINUES, folderChoices, folderName, missingNote, parentPath, terminalNote, tildePath, type AgentId, type SessionRec } from "./agents";
import { pickTitle } from "./titles";
import { t as tr, type Key } from "../i18n";
import { getSessions, useSessions, type ModelOption } from "./sessions";
import { sessionAccountSuffix } from "./SessionsSection";
import { useAccounts } from "../settings/accounts/useAccounts";
import { t } from "../i18n";

// Matched to omher's tokens (--bg, --body, --ink) so the terminal reads as part of the page.
const DARK: ITheme = {
  background: "#0b090d",
  foreground: "#dcd6de",
  cursor: "#f3eff4",
  cursorAccent: "#0b090d",
  selectionBackground: "#3d364066",
  selectionInactiveBackground: "#3d364044",
  black: "#1b181e",
  red: "#f08a8a",
  green: "#7fd6a4",
  yellow: "#eaaf55",
  blue: "#8cbcff",
  magenta: "#e48fd0",
  cyan: "#7fd1d6",
  white: "#dcd6de",
  brightBlack: "#6f6872",
  brightRed: "#ffa3a3",
  brightGreen: "#9be6b9",
  brightYellow: "#f5c779",
  brightBlue: "#a9ccff",
  brightMagenta: "#f0a8de",
  brightCyan: "#9de2e6",
  brightWhite: "#f3eff4",
};
const LIGHT: ITheme = {
  background: "#ffffff",
  foreground: "#2c2630",
  cursor: "#19151b",
  cursorAccent: "#ffffff",
  selectionBackground: "#cbc4cf88",
  selectionInactiveBackground: "#cbc4cf55",
  black: "#19151b",
  red: "#c0392b",
  green: "#1f8a52",
  yellow: "#a86a00",
  blue: "#1d5fd1",
  magenta: "#a8327a",
  cyan: "#0f7f86",
  white: "#e9e5eb",
  brightBlack: "#756d7a",
  brightRed: "#d9534f",
  brightGreen: "#28a065",
  brightYellow: "#c08000",
  brightBlue: "#3a78e0",
  brightMagenta: "#c4367f",
  brightCyan: "#1b97a0",
  brightWhite: "#ffffff",
};

export const termTheme = (mode: "dark" | "light") => (mode === "light" ? LIGHT : DARK);

const STATUS: Record<string, Key> = { starting: "ss.starting", running: "ss.running", exited: "ss.ended", failed: "ss.couldNotStart" };

const isWindows = () => typeof navigator !== "undefined" && /^Win/.test(navigator.platform);

/** A file as the terminal's drop and paste hand it on. */
const fileIn = (f: File) => ({ name: f.name || "pasted.png", read: async () => new Uint8Array(await f.arrayBuffer()) });

function TerminalPane({ rec }: { rec: SessionRec }) {
  const s = useStore();
  const box = useRef<HTMLDivElement>(null);
  const wrap = useRef<HTMLDivElement>(null);
  const mode = resolveTheme(s.ui.theme);
  // A file dropped on the terminal, or a picture pasted there, is saved and its path typed at the prompt (as a
  // system terminal types a dropped file's path). Plain text pastes stay xterm's own.
  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const hasFiles = (e: DragEvent) => !!e.dataTransfer && [...e.dataTransfer.types].includes("Files");
    const over = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      if (e.dataTransfer) e.dataTransfer.dropEffect = "copy";
    };
    const drop = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      const files = [...(e.dataTransfer?.files ?? [])];
      if (files.length) void getSessions().dropOnTerminal(rec.id, files.map(fileIn), isWindows());
    };
    const paste = (e: ClipboardEvent) => {
      const files = [...(e.clipboardData?.files ?? [])];
      if (!files.length) return;
      e.preventDefault();
      e.stopPropagation();
      void getSessions().dropOnTerminal(rec.id, files.map(fileIn), isWindows());
    };
    el.addEventListener("dragenter", over);
    el.addEventListener("dragover", over);
    el.addEventListener("drop", drop);
    el.addEventListener("paste", paste, true);
    return () => {
      el.removeEventListener("dragenter", over);
      el.removeEventListener("dragover", over);
      el.removeEventListener("drop", drop);
      el.removeEventListener("paste", paste, true);
    };
  }, [rec.id]);
  useEffect(() => {
    if (!box.current) return;
    return getSessions().attach(rec.id, box.current, termTheme(mode));
    // re-attach only when the session changes; theme changes go through setTheme below
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rec.id]);
  useEffect(() => {
    getSessions().setTheme(termTheme(mode));
  }, [mode]);
  return (
    <div className="term-wrap" ref={wrap} data-testid="terminal" data-session={rec.id}>
      <div className="term-box" ref={box} />
    </div>
  );
}

function ChatPane({ rec, chatKey }: { rec: SessionRec; chatKey: string }) {
  const s = useStore();
  const ss = useSessions();
  const chat = s.chats[chatKey];
  // files go to a chat agent; an oh-my-hermes session's chat is Hermes', which takes files in a bot's main chat only
  const takesFiles = (ss.agents?.find((a) => a.id === rec.agent)?.mode ?? agentDef(rec.agent).mode) === "chat";
  const label = agentDef(rec.agent).label;
  // The bot chat's parts take a Bot: this session's chat stands in for one.
  const bot: Bot = {
    name: chatKey,
    display_name: label,
    is_default: false,
    // DeepSeek Harness keeps its model in its own app and its headless stream names none: nothing to pick here
    model: rec.model || (rec.agent === "dsh" ? "dsh" : ""),
    provider: "",
    description: "",
    status: rec.status === "running" ? "online" : rec.status === "starting" ? "starting" : "offline",
    running: !!chat?.turn,
  };
  const ended = isEnded(rec);
  const offlineText = rec.paused
    ? tr("ss.isPaused", { agent: label })
    : rec.status === "failed"
      ? tr("ss.agentCouldNotStart", { agent: label })
      : rec.status === "starting"
        ? tr("ss.startingAgent", { agent: label })
        : tr("ss.hasEnded", { agent: label });
  // one element per chat: the bubbles are memoized on it
  const face = useMemo(() => <SessionFace chatKey={chatKey} size={28} />, [chatKey]);
  return (
    <div className="pane ss-chat" data-pane={chatKey} data-testid="session-chat">
      <Timeline bot={bot} face={face} />
      {rec.paused ? <Paused rec={rec} /> : ended && <Ended rec={rec} />}
      <Composer
        key={chatKey}
        bot={bot}
        running={!!chat?.turn}
        asking={selectAsks(s).some((a) => a.bot === chatKey)}
        offline={rec.status !== "running"}
        offlineText={offlineText}
        onSend={(t) => void getSessions().send(rec.id, t)}
        onSendFiles={takesFiles ? (t, files) => getSessions().sendFiles(rec.id, t, files) : undefined}
        onStop={() => void getSessions().interrupt(rec.id)}
        tools={<AgentFixed agent={rec.agent} />}
        foot={<Context rec={rec} />}
      />
    </div>
  );
}

const HomeIcon = ({ size = 14 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" aria-hidden="true">
    <path d="M4 10.5 12 4l8 6.5V19a1 1 0 0 1-1 1h-4.5v-5.5h-5V20H5a1 1 0 0 1-1-1z" />
  </svg>
);

const FolderIcon = ({ size = 13 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
    <path d="M3 7.5A1.5 1.5 0 0 1 4.5 6h4.4l2 2h8.6A1.5 1.5 0 0 1 21 9.5v8a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 17.5z" />
  </svg>
);

/** The session's agent in the composer row, read-only (a draft's agent is changed from the SESSIONS + menu). */
function AgentFixed({ agent }: { agent: AgentId }) {
  return (
    <span className="ss-pick ro" title={agentDef(agent).label} data-testid="session-agent-fixed">
      <AgentMark agent={agent} size={14} />
      <span className="ss-pick-n">{agentDef(agent).label}</span>
    </span>
  );
}

/** The line under a session's composer: the folder (and the account it runs as). A draft's folder is a menu:
 *  the recent folders, Choose folder… (the native dialog) and the home folder. Started, it is read-only. */
function Context({ rec, account }: { rec: SessionRec; account?: string }) {
  const ss = useSessions();
  const [open, setOpen] = useState(false);
  const draft = rec.status === "draft";
  const name = rec.cwd ? folderName(rec.cwd) : t("sessions.findingHome");
  const as = draft ? account : rec.startedAs;
  const pick = (cwd: string) => {
    setOpen(false);
    getSessions().setDraft(rec.id, { cwd });
  };
  const choose = async () => {
    setOpen(false);
    await getSessions().chooseFolder(rec.id);
  };
  const { recent, home } = folderChoices(ss.recent, ss.home);
  const row = (cwd: string, label: string, testid: string, icon?: ReactNode, path = true) => {
    const on = cwd === rec.cwd;
    return (
      <button key={`${testid}:${cwd}`} type="button" className={`ss-item${on ? " on" : ""}`} title={cwd} aria-pressed={on} onClick={() => pick(cwd)} data-testid={testid}>
        <span className="ss-ic">{icon}</span>
        <span className="ss-n">{label}</span>
        {path && <span className="ss-path">{parentPath(tildePath(cwd, ss.home)) || tildePath(cwd, ss.home)}</span>}
        <span className="ss-ck">{on && <CheckIcon />}</span>
      </button>
    );
  };
  return (
    <div className="ss-ctx" data-testid="session-context">
      {draft ? (
        <span className="ss-chip-w">
          <button
            type="button"
            className="ss-chip"
            title={rec.cwd || undefined}
            aria-label={`${t("sessions.folder")}: ${name}`}
            aria-haspopup="dialog"
            aria-expanded={open}
            disabled={!rec.cwd}
            onClick={() => setOpen((v) => !v)}
            data-testid="session-folder"
          >
            <FolderIcon />
            <span className="ss-chip-n">{name}</span>
            <ChevronDown />
          </button>
          <Popover open={open} onClose={() => setOpen(false)} side="top" align="left" width={280} label={t("sessions.folder")} className="ss-dpop">
            <div data-testid="session-folder-menu">
              {recent.length > 0 && <div className="ss-h">{t("sessions.recent")}</div>}
              {recent.map((cwd) => row(cwd, folderName(cwd), "session-recent"))}
              {recent.length > 0 && <div className="ss-sep" />}
              <button type="button" className="ss-item" onClick={() => void choose()} data-testid="session-choose">
                <span className="ss-ic">
                  <FolderIcon size={14} />
                </span>
                <span className="ss-n">{t("sessions.choose")}</span>
              </button>
              {home && row(home, t("sessions.home"), "session-home", <HomeIcon />, false)}
            </div>
          </Popover>
        </span>
      ) : (
        <span className="ss-chip ro" title={rec.cwd} data-testid="session-folder">
          <FolderIcon />
          <span className="ss-chip-n">{name}</span>
        </span>
      )}
      {as && (
        <span className="ss-acct" data-testid="session-account">
          {as}
        </span>
      )}
    </div>
  );
}

/** A New session: the chat before its agent runs. */
function DraftPane({ rec }: { rec: SessionRec }) {
  const ss = useSessions();
  const accounts = useAccounts();
  const def = agentDef(rec.agent);
  const mode = ss.agents?.find((a) => a.id === rec.agent)?.mode ?? def.mode;
  const terminal = mode === "terminal";
  // until the look-up answers, the agent counts as there (a flash of "not found" would be wrong more often)
  const installed = ss.agents === null || !!ss.agents.find((a) => a.id === rec.agent)?.path;
  const account = sessionAccountSuffix(accounts.groups, rec.agent);
  const ready = installed && !!rec.cwd;
  const folder = rec.cwd ? folderName(rec.cwd) : "";
  // the session chat's own key: unsent text is kept under it (the resume snapshot saves it) and is still there
  // in the chat once it starts
  const key = `agent:${rec.id}`;
  const bot: Bot = { name: key, display_name: def.label, is_default: false, model: "", provider: "", description: "", status: "online", running: false };
  const start = (text?: string) => void getSessions().start(rec.id, text, account || undefined);
  /** The first message with files: they are saved before the agent starts; a file that cannot be keeps the draft
   *  (and the chips) as they were. */
  const startWithFiles = async (text: string, files: OutFile[]) => {
    await getSessions().start(rec.id, text, account || undefined, files);
  };
  // the composer takes the focus once it can be typed in (the folder or the agent list may arrive after it shows)
  const live = ready && !terminal;
  useEffect(() => {
    if (live) document.querySelector<HTMLTextAreaElement>(`[data-pane="${key}"] [data-testid=composer]`)?.focus();
  }, [live, key]);
  return (
    <div className="pane ss-chat ss-draft" data-pane={key} data-testid="session-chat" data-draft="true">
      <div className="thread" data-testid="timeline">
        <div className="day" data-testid="draft-note">
          {!rec.cwd
            ? t("sessions.findingHome")
            : !installed
              ? missingNote(rec.agent)
              : t(terminal ? "sessions.firstStart" : "sessions.firstSend", { agent: def.label, folder })}
        </div>
      </div>
      <Composer
        key={key}
        bot={bot}
        running={false}
        offline={!ready || terminal}
        offlineText={!ready ? (!rec.cwd ? t("sessions.findingHome") : missingNote(rec.agent)) : t("sessions.pressStart", { agent: def.label })}
        onSend={(text) => start(text)}
        onSendFiles={mode === "chat" ? startWithFiles : undefined}
        onStop={() => undefined}
        tools={<AgentFixed agent={rec.agent} />}
        action={
          terminal ? (
            <button type="button" className="ss-go" disabled={!ready} onClick={() => start()} data-testid="session-go">
              {t("sessions.start")}
              <ArrowUp />
            </button>
          ) : undefined
        }
        foot={<Context rec={rec} account={account} />}
      />
    </div>
  );
}

const isEnded = (rec: SessionRec) => rec.status === "exited" || rec.status === "failed";

/** Restart's (and Resume's) tooltip: whether the agent continues this conversation or starts a new one. */
function againTip(rec: SessionRec): string {
  const agent = agentDef(rec.agent).label;
  return CONTINUES.includes(rec.agent) && rec.agentSession ? tr("ss.restartContinue", { agent }) : tr("ss.restartFolder", { agent });
}

/** An ended session (chat or terminal): one quiet line, and Restart, which starts its agent again in the same folder
 *  and account. */
function Ended({ rec }: { rec: SessionRec }) {
  const why = rec.error ? rec.error.trim().split("\n").pop() : "";
  return (
    <div className="ss-ended" role="status" data-testid="session-ended">
      <span className="ss-ended-t" title={why || undefined}>
        {rec.status === "failed" ? tr("ss.couldNotStart") : tr("ss.ended")}
        {why ? ` · ${why}` : ""}
      </span>
      <button type="button" className="ss-restart" onClick={() => void getSessions().restart(rec.id)} title={againTip(rec)} data-testid="session-restart">
        {tr("ss.restart")}
      </button>
    </div>
  );
}

/** A session that was running when omher restarted and does not continue by itself: one line and Resume, which
 *  starts it again in the same folder (and account). */
function Paused({ rec }: { rec: SessionRec }) {
  return (
    <div className="ss-ended" role="status" data-testid="session-paused">
      <span className="ss-ended-t">{t("resume.paused")}</span>
      <button
        type="button"
        className="ss-restart"
        onClick={() => void getSessions().resume(rec.id)}
        title={againTip(rec)}
        data-testid="session-resume"
      >
        {t("resume.resume")}
      </button>
    </div>
  );
}

/** A restored terminal session that is not running: no terminal is started until the person asks (Resume, or
 *  Restart once it has ended). */
function TerminalIdle({ rec }: { rec: SessionRec }) {
  const label = agentDef(rec.agent).label;
  return (
    <div className="pane ss-chat ss-idle" data-testid="session-idle">
      <div className="chat-empty">{rec.paused ? null : tr("ss.agentEnded", { agent: label })}</div>
      {rec.paused ? <Paused rec={rec} /> : <Ended rec={rec} />}
    </div>
  );
}

/** The session's model button: the same pill as a bot's, listing what the agent itself offers. */
function SessionModel({ rec, options, note }: { rec: SessionRec; options: ModelOption[] | undefined; note: string | undefined }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const live = rec.status === "running";
  const label = agentDef(rec.agent).label;
  const vendor = rec.agent === "codex" ? "openai" : rec.agent;
  return (
    <div className="mp-wrap">
      <button
        type="button"
        className={`mp${open ? " on" : ""}`}
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="dialog"
        aria-expanded={open}
        title={tr("ss.model")}
        data-testid="model-pill"
      >
        <span className="mp-mk" title={live ? tr("ss.running") : tr("ss.notRunning")}>
          <ModelIcon model={rec.model || label} provider={vendor} size={14} />
          <span className={`mp-d${live ? " live" : ""}`} aria-hidden="true" />
        </span>
        <span data-testid="model-label">{rec.model || tr("ss.model")}</span>
        <ChevronDown />
      </button>
      <Popover open={open} onClose={() => setOpen(false)} label={tr("ss.model")} width={256} className="mp-pop">
        <div data-testid="model-pop" aria-busy={busy}>
          <div className="mp-h">{tr("ss.model")}</div>
          <div className="mp-list">
            {!options || options.length === 0 ? (
              <div className="mp-empty">{live ? tr("ss.loadingModels") : tr("ss.agentNotRunning", { agent: label })}</div>
            ) : (
              options.map((o) => {
                const on = o.label === rec.model || o.id === rec.model;
                return (
                  <button
                    key={`${o.provider ?? ""}/${o.id}`}
                    type="button"
                    className={`mp-opt${on ? " on" : ""}`}
                    aria-pressed={on}
                    disabled={busy || !live}
                    title={o.detail || undefined}
                    onClick={async () => {
                      if (on) return;
                      setBusy(true);
                      await getSessions().setModel(rec.id, o);
                      setBusy(false);
                    }}
                    data-testid="model-opt"
                  >
                    <ModelIcon model={`${o.id} ${o.label}`} provider={o.provider ?? vendor} size={13} />
                    <span className="mp-n">{o.label}</span>
                    <span className="mp-ck">
                      <CheckIcon />
                    </span>
                  </button>
                );
              })
            )}
          </div>
          {note && (
            <div className="mp-note" role="status" title={note} data-testid="model-note">
              {note}
            </div>
          )}
          <div className="mp-f">{tr("ss.applies")}</div>
        </div>
      </Popover>
    </div>
  );
}

export function SessionView() {
  const s = useStore();
  const ss = useSessions();
  const rec = ss.list.find((r) => r.id === s.ui.session) ?? null;
  if (!rec) {
    return (
      <div className="chat-empty" data-testid="session-gone">
        {tr("ss.closed")}
      </div>
    );
  }
  const def = agentDef(rec.agent);
  if (rec.status === "draft") {
    return (
      <>
        <header className="head" data-testid="header">
          <span className="ss-head-mark">
            <AgentMark agent={rec.agent} size={18} />
          </span>
          <span className="head-title" data-testid="session-title">
            {t("sessions.new")}
          </span>
        </header>
        <DraftPane key={rec.id} rec={rec} />
      </>
    );
  }
  const name = pickTitle(rec, folderName(rec.cwd)).title;
  const chatKey = getSessions().chatKey(rec.id);
  const mode = ss.agents?.find((a) => a.id === rec.agent)?.mode ?? def.mode;
  // DeepSeek Harness ships no terminal profile: a DSH chat has no Terminal view (and its model is set in its own app)
  const canToggle = mode !== "terminal" && rec.agent !== "dsh";
  const showChat = rec.view === "chat" && !!chatKey;
  const c = chatKey ? s.chats[chatKey] : undefined;
  const turn = !!c?.turn;
  // an approval or question of this chat is still open (the Needs-you model: answered, expired or its turn over closes it)
  const needs = !!chatKey && selectAsks(s).some((a) => a.bot === chatKey);
  const status = rec.paused
    ? t("resume.pausedShort")
    : rec.view === "terminal" && canToggle
      ? tr("ss.terminalView")
      : rec.status === "exited" && rec.exitCode
        ? tr("ss.endedExit", { code: rec.exitCode })
        : rec.status === "running" && showChat
          ? needs
            ? tr("ss.needsYou")
            : turn
              ? tr("ss.working")
              : tr("ss.ready")
          : STATUS[rec.status]
            ? tr(STATUS[rec.status])
            : rec.status;
  return (
    <>
      <header className="head" data-testid="header">
        <span className="ss-head-mark">
          <AgentMark agent={rec.agent} size={18} />
        </span>
        <span className="head-title" data-testid="session-title" title={name}>
          {name}
        </span>
        {/* the same order as the row's second line: where, then which agent */}
        <span className="ss-head-path" title={rec.cwd}>
          <span data-testid="session-cwd">{tildePath(rec.cwd, ss.home)}</span>
          {" · "}
          <span data-testid="session-agent">{def.label}</span>
        </span>
        <span
          className={`ss-head-st ${rec.view === "terminal" && canToggle ? "mode" : rec.status}${showChat && !turn ? " idle" : ""}${showChat && needs ? " needs" : ""}`}
          data-testid="session-status"
        >
          {status}
        </span>
        {canToggle && (
          <div className="head-right ss-head-right" data-testid="head-right">
            <button
              type="button"
              className={`ss-toggle${rec.view === "terminal" ? " on" : ""}`}
              aria-pressed={rec.view === "terminal"}
              aria-label={rec.view === "terminal" ? tr("ss.backToChat") : tr("ss.openTerminal")}
              title={rec.view === "terminal" ? tr("ss.backToChat") : tr("ss.openTerminal")}
              aria-description={rec.view === "terminal" ? undefined : terminalNote(rec.agent)}
              onClick={() => void getSessions().setView(rec.id, rec.view === "terminal" ? "chat" : "terminal")}
              data-testid="session-terminal-toggle"
            >
              {rec.view === "terminal" ? <ChatIcon /> : <TerminalIcon />}
            </button>
            {showChat && <SessionModel rec={rec} options={ss.models[rec.id]} note={ss.notes[rec.id]} />}
          </div>
        )}
      </header>
      {showChat ? (
        <ChatPane rec={rec} chatKey={chatKey!} />
      ) : rec.paused || ((rec.status === "exited" || rec.status === "failed") && !getSessions().hasTerm(rec.id)) ? (
        <TerminalIdle rec={rec} />
      ) : rec.view === "chat" && mode !== "terminal" ? (
        // a Hermes folder chat between its first message and the bridge's chat id: not a reason to start a terminal
        <div className="pane ss-chat" data-testid="session-chat">
          <div className="thread" data-testid="timeline">
            <div className="day">{rec.status === "failed" ? (rec.error ? tr("ss.couldNotStartWhy", { agent: def.label, error: rec.error }) : tr("ss.agentCouldNotStart", { agent: def.label })) : tr("ss.startingAgent", { agent: def.label })}</div>
          </div>
        </div>
      ) : (
        <>
          {/* a new key after Restart: a fresh terminal for the program started again */}
          <TerminalPane key={`${rec.id}-term-${getSessions().termRun(rec.id)}`} rec={rec} />
          {!canToggle && isEnded(rec) && <Ended rec={rec} />}
        </>
      )}
    </>
  );
}
