// Main column for a SESSIONS entry: a header (agent mark, folder, status, the Terminal toggle and the model
// button) above either the chat (the bot chat's own Timeline and Composer, fed by the agent's structured
// mode) or the agent's terminal.
import { useEffect, useRef, useState } from "react";
import "@xterm/xterm/css/xterm.css";
import type { ITheme } from "@xterm/xterm";
import { useStore } from "../state/store";
import { resolveTheme } from "../app/theme";
import { Timeline } from "../chat/parts/Timeline";
import { Composer } from "../chat/parts/Composer";
import { CheckIcon } from "../chat/model/CheckIcon";
import "../chat/model/model.css";
import { ChevronDown, ModelIcon, Popover } from "../ui";
import type { Bot } from "../lib/protocol";
import { AgentMark } from "./AgentMark";
import { agentDef, terminalNote, tildePath, type SessionRec } from "./agents";
import { getSessions, useSessions, type ModelOption } from "./sessions";

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

const STATUS: Record<string, string> = { starting: "Starting…", running: "Running", exited: "Ended", failed: "Could not start" };

function TerminalPane({ rec }: { rec: SessionRec }) {
  const s = useStore();
  const box = useRef<HTMLDivElement>(null);
  const mode = resolveTheme(s.ui.theme);
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
    <div className="term-wrap" data-testid="terminal" data-session={rec.id}>
      <div className="term-box" ref={box} />
    </div>
  );
}

function ChatPane({ rec, chatKey }: { rec: SessionRec; chatKey: string }) {
  const s = useStore();
  const chat = s.chats[chatKey];
  const label = agentDef(rec.agent).label;
  // The bot chat's parts take a Bot: this session's chat stands in for one.
  const bot: Bot = {
    name: chatKey,
    display_name: label,
    is_default: false,
    model: rec.model ?? "",
    provider: "",
    description: "",
    status: rec.status === "running" ? "online" : rec.status === "starting" ? "starting" : "offline",
    running: !!chat?.turn,
  };
  const ended = rec.status === "exited" || rec.status === "failed";
  const offlineText =
    rec.status === "failed" ? `${label} could not start` : rec.status === "starting" ? `Starting ${label}…` : `${label} has ended`;
  const why = rec.error ? rec.error.trim().split("\n").pop() : "";
  return (
    <div className="pane ss-chat" data-pane={chatKey} data-testid="session-chat">
      <Timeline bot={bot} />
      {ended && (
        <div className="ss-ended" role="status" data-testid="session-ended">
          {rec.status === "failed" ? "Could not start" : "Ended"}
          {why ? ` · ${why}` : ""}
        </div>
      )}
      <Composer
        key={chatKey}
        bot={bot}
        running={!!chat?.turn}
        offline={rec.status !== "running"}
        offlineText={offlineText}
        onSend={(t) => void getSessions().send(rec.id, t)}
        onStop={() => void getSessions().interrupt(rec.id)}
      />
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
        title="Model"
        data-testid="model-pill"
      >
        <span className="mp-mk" title={live ? "Running" : "Not running"}>
          <ModelIcon model={rec.model || label} provider={vendor} size={14} />
          <span className={`mp-d${live ? " live" : ""}`} aria-hidden="true" />
        </span>
        <span data-testid="model-label">{rec.model || "Model"}</span>
        <ChevronDown />
      </button>
      <Popover open={open} onClose={() => setOpen(false)} label="Model" width={256} className="mp-pop">
        <div data-testid="model-pop" aria-busy={busy}>
          <div className="mp-h">Model</div>
          <div className="mp-list">
            {!options || options.length === 0 ? (
              <div className="mp-empty">{live ? "Loading models…" : `${label} is not running`}</div>
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
          <div className="mp-f">Applies to this session</div>
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
        This session was closed
      </div>
    );
  }
  const def = agentDef(rec.agent);
  const chatKey = getSessions().chatKey(rec.id);
  const mode = ss.agents?.find((a) => a.id === rec.agent)?.mode ?? def.mode;
  const canToggle = mode !== "terminal";
  const showChat = rec.view === "chat" && !!chatKey;
  const c = chatKey ? s.chats[chatKey] : undefined;
  const turn = !!c?.turn;
  // an approval or question of the running turn is still open
  const needs =
    !!c?.turn &&
    c.items.some(
      (i) => i.ts >= c.turn!.startedAt / 1000 - 1 && ((i.kind === "approval" && !i.resolved) || (i.kind === "clarify" && i.answer === undefined)),
    );
  const status =
    rec.view === "terminal" && canToggle
      ? "Terminal view"
      : rec.status === "exited" && rec.exitCode
        ? `Ended · exit ${rec.exitCode}`
        : rec.status === "running" && showChat
          ? needs
            ? "Needs you"
            : turn
              ? "Working"
              : "Ready"
          : STATUS[rec.status];
  return (
    <>
      <header className="head" data-testid="header">
        <span className="ss-head-mark">
          <AgentMark agent={rec.agent} size={18} />
        </span>
        <span className="head-title" data-testid="session-title">
          {def.label}
        </span>
        <span className="ss-head-path" title={rec.cwd} data-testid="session-cwd">
          {tildePath(rec.cwd, ss.home)}
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
              title={rec.view === "terminal" ? "Back to the chat" : terminalNote(rec.agent)}
              onClick={() => void getSessions().setView(rec.id, rec.view === "terminal" ? "chat" : "terminal")}
              data-testid="session-terminal-toggle"
            >
              {rec.view === "terminal" ? "Chat" : "Terminal"}
            </button>
            {showChat && <SessionModel rec={rec} options={ss.models[rec.id]} note={ss.notes[rec.id]} />}
          </div>
        )}
      </header>
      {showChat ? <ChatPane rec={rec} chatKey={chatKey!} /> : <TerminalPane key={`${rec.id}-term`} rec={rec} />}
    </>
  );
}
