// Main column for a terminal session: header (agent + folder) and the live terminal.
import { useEffect, useRef } from "react";
import type { ITheme } from "@xterm/xterm";
import { useStore } from "../state/store";
import { resolveTheme } from "../app/theme";
import { AgentMark } from "./AgentMark";
import { agentDef, tildePath } from "./agents";
import { getSessions, useSessions } from "./sessions";

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

export function SessionView() {
  const s = useStore();
  const ss = useSessions();
  const rec = ss.list.find((r) => r.id === s.ui.session) ?? null;
  const box = useRef<HTMLDivElement>(null);
  const mode = resolveTheme(s.ui.theme);

  useEffect(() => {
    if (!rec || !box.current) return;
    return getSessions().attach(rec.id, box.current, termTheme(mode));
    // re-attach only when the session changes; theme changes go through setTheme below
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rec?.id]);
  useEffect(() => {
    getSessions().setTheme(termTheme(mode));
  }, [mode]);

  if (!rec) {
    return (
      <div className="chat-empty" data-testid="session-gone">
        This session was closed
      </div>
    );
  }
  const def = agentDef(rec.agent);
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
        <span className={`ss-head-st ${rec.status}`} data-testid="session-status">
          {rec.status === "exited" && rec.exitCode ? `Ended · exit ${rec.exitCode}` : STATUS[rec.status]}
        </span>
      </header>
      <div className="term-wrap" data-testid="terminal" data-session={rec.id}>
        <div className="term-box" ref={box} />
      </div>
    </>
  );
}
