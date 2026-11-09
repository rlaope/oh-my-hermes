// While the Tauri shell's bridge is not up, say so on one centred screen instead of an empty app.
// Outside Tauri (browser dev, e2e against the mock) there is no shell to ask and the app renders directly,
// unless the page sets `window.__OMHER_GATE__` (the e2e stand-in for the shell).
//
// When Hermes itself is missing, the screen offers to install Hermes and oh-my-hermes. The shell runs one
// fixed command (OMH's one-line installer with `omher@beta`, without the app); the page only presses the
// button and shows the output.
import { Fragment, useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import mark from "../assets/omher-mark.png";
import "./gate.css";

export type BridgeState = { state: "ready" | "starting" | "failed"; error?: string; missing?: "hermes" };
export type InstallEvent = { kind: "line"; text: string } | { kind: "exit"; code: number | null };

/** The shell's commands, or the e2e stand-in. */
export interface GateShell {
  status(): Promise<BridgeState>;
  retry(): Promise<void>;
  installCommand(): Promise<string>;
  install(onEvent: (e: InstallEvent) => void): Promise<number | null>;
}

const inTauri = () => typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

async function tauriShell(): Promise<GateShell> {
  const { invoke, Channel } = await import("@tauri-apps/api/core");
  return {
    status: () => invoke<BridgeState>("bridge_status"),
    retry: () => invoke<void>("bridge_retry"),
    installCommand: () => invoke<string>("install_engine_command"),
    install: (onEvent) => {
      const ch = new Channel<InstallEvent>();
      ch.onmessage = onEvent;
      return invoke<number | null>("install_engine", { onEvent: ch });
    },
  };
}

function testShell(): GateShell | null {
  if (typeof window === "undefined") return null;
  return (window as unknown as { __OMHER_GATE__?: GateShell }).__OMHER_GATE__ ?? null;
}

const hasShell = () => inTauri() || testShell() !== null;
const MAX_LINES = 400;

/** Append one installer line, keeping the newest MAX_LINES. */
export function appendLine(lines: string[], text: string, max = MAX_LINES): string[] {
  const next = [...lines, text];
  return next.length > max ? next.slice(next.length - max) : next;
}

export function BridgeGate({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<BridgeState | null>(hasShell() ? null : { state: "ready" });
  const [retrying, setRetrying] = useState(false);
  const [command, setCommand] = useState("");
  const [install, setInstall] = useState<"idle" | "running" | "failed">("idle");
  const [lines, setLines] = useState<string[]>([]);
  const [exitCode, setExitCode] = useState<number | null>(null);
  const shellRef = useRef<GateShell | null>(null);
  const logRef = useRef<HTMLPreElement | null>(null);

  const shell = useCallback(async () => {
    if (!shellRef.current) shellRef.current = testShell() ?? (await tauriShell());
    return shellRef.current;
  }, []);

  const running = install === "running";
  useEffect(() => {
    if (!hasShell() || status?.state === "ready" || running) return;
    let alive = true;
    const poll = async () => {
      try {
        const s = await (await shell()).status();
        if (alive) setStatus(s);
      } catch (e) {
        if (alive) setStatus({ state: "failed", error: String(e) });
      }
    };
    void poll();
    const h = setInterval(poll, 500);
    return () => {
      alive = false;
      clearInterval(h);
    };
  }, [status?.state === "ready", running, shell]);

  const needsHermes = status?.state === "failed" && status.missing === "hermes";

  useEffect(() => {
    if (!needsHermes || command) return;
    void shell()
      .then((s) => s.installCommand())
      .then(setCommand, () => {});
  }, [needsHermes, command, shell]);

  useEffect(() => {
    const el = logRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [lines]);

  const retry = useCallback(async () => {
    setRetrying(true);
    setInstall("idle");
    setStatus({ state: "starting" });
    try {
      await (await shell()).retry();
    } catch (e) {
      setStatus({ state: "failed", error: String(e) });
    } finally {
      setRetrying(false);
    }
  }, [shell]);

  const runInstall = useCallback(async () => {
    setInstall("running");
    setLines([]);
    setExitCode(null);
    try {
      const code = await (await shell()).install((e) => {
        if (e.kind === "line") setLines((l) => appendLine(l, e.text));
      });
      setExitCode(code);
      if (code === 0) {
        // The shell starts the bridge again after a clean install; poll it from "starting".
        setInstall("idle");
        setStatus({ state: "starting" });
      } else {
        setInstall("failed");
      }
    } catch (e) {
      setLines((l) => appendLine(l, String(e)));
      setInstall("failed");
    }
  }, [shell]);

  if (status?.state === "ready") return <>{children}</>;

  if (needsHermes || install !== "idle") {
    return (
      <div className="gate" data-testid="bridge-gate" data-state="setup">
        <div className="gate-box gate-setup" data-testid="setup-screen">
          <img className="gate-mark" src={mark} alt="" width={44} height={44} />
          <div className="gate-head">omher needs Hermes and oh-my-hermes</div>
          <p className="gate-text">
            omher runs your bots through Hermes Agent on this computer, and Hermes isn’t installed yet. Install sets
            up Hermes and oh-my-hermes with their official installer, then opens your bots.
          </p>
          {command && (
            <code className="gate-cmd" data-testid="setup-command">
              {/* one unbreakable token per word: the URL never wraps at its own hyphens */}
              {command.split(" ").map((word, i) => (
                <Fragment key={i}>
                  {i > 0 && " "}
                  <span className="gate-tok">{word}</span>
                </Fragment>
              ))}
            </code>
          )}
          {lines.length > 0 && (
            <pre className="gate-log" data-testid="setup-log" ref={logRef} aria-live="polite">
              {lines.map((line, i) => (
                <span key={i} className="gate-line">
                  {line}
                </span>
              ))}
            </pre>
          )}
          {install === "failed" && (
            <p className="gate-error gate-error--bad" data-testid="setup-failed">
              {exitCode === null
                ? "The installer could not run."
                : `The installer stopped (exit ${exitCode}). The output above says why. Fix it and press Install again.`}
            </p>
          )}
          <div className="gate-actions">
            <button
              type="button"
              className="gate-retry gate-primary"
              data-testid="setup-install"
              disabled={running}
              onClick={runInstall}
            >
              {running && <span className="gate-spin" aria-hidden="true" />}
              {running ? "Installing…" : install === "failed" ? "Install again" : "Install"}
            </button>
            <button
              type="button"
              className="gate-retry gate-quiet"
              data-testid="bridge-retry"
              disabled={running || retrying}
              onClick={retry}
            >
              I installed it, retry
            </button>
          </div>
          <p className="gate-note">
            Takes a few minutes. Afterwards, run <code>hermes setup</code> once to choose a model.
          </p>
        </div>
      </div>
    );
  }

  const failed = status?.state === "failed";
  return (
    <div className="gate" data-testid="bridge-gate" data-state={status?.state ?? "starting"}>
      <div className="gate-box">
        <div className="gate-title">{failed ? "omher can’t reach Hermes" : "Starting omher…"}</div>
        {failed && (
          <>
            <p className="gate-error" data-testid="bridge-error">
              {status?.error || "The local bridge did not start."}
            </p>
            <button type="button" className="gate-retry" data-testid="bridge-retry" disabled={retrying} onClick={retry}>
              Retry
            </button>
          </>
        )}
      </div>
    </div>
  );
}
