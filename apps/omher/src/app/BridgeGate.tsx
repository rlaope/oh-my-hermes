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
import { t } from "../i18n";

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

/** The shell's commands (or the e2e stand-in); `null` outside Tauri with no stand-in (browser dev): nothing can install. */
export async function gateShell(): Promise<GateShell | null> {
  return testShell() ?? (inTauri() ? await tauriShell() : null);
}

/** The installer's output as the setup screen shows it: one line each, `[failed]` lines in the danger colour, the
 *  newest at the bottom. Also used by the offer to add oh-my-hermes (the + menu line and the first-run card). */
export function InstallLog({ lines, compact, testId = "setup-log" }: { lines: string[]; compact?: boolean; testId?: string }) {
  const ref = useRef<HTMLPreElement | null>(null);
  useEffect(() => {
    const el = ref.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [lines]);
  if (!lines.length) return null;
  return (
    <pre className={`gate-log${compact ? " gate-log-sm" : ""}`} data-testid={testId} ref={ref} aria-live="polite">
      {lines.map((line, i) => (
        <span key={i} className={`gate-line gate-line--${lineTone(line)}`}>
          {line}
        </span>
      ))}
    </pre>
  );
}

const hasShell = () => inTauri() || testShell() !== null;
const MAX_LINES = 400;

/** How a log line reads: the installer's `[failed]`/`ERROR` lines in the danger colour, its `[ok]` lines muted. */
export function lineTone(text: string): "bad" | "ok" | "plain" {
  const t = text.trimStart();
  if (/^\[failed\]/i.test(t) || /^(ERROR|error:|fatal:|curl: \(\d+\))/.test(t)) return "bad";
  if (/^\[ok\]/i.test(t)) return "ok";
  return "plain";
}

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
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const t = setTimeout(() => setCopied(false), 1500);
    return () => clearTimeout(t);
  }, [copied]);
  const [exitCode, setExitCode] = useState<number | null>(null);
  const [installError, setInstallError] = useState<string | null>(null);
  const shellRef = useRef<GateShell | null>(null);
  const installRef = useRef<HTMLButtonElement | null>(null);

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

  // Focus follows the one action that matters: Install on arrival, Install again after a failure.
  const failedInstall = install === "failed";
  useEffect(() => {
    if (failedInstall) installRef.current?.focus();
  }, [failedInstall]);

  const runInstall = useCallback(async () => {
    setInstall("running");
    setLines([]);
    setExitCode(null);
    setInstallError(null);
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
      // The shell refuses with a message: it could not start the installer, or the installer exited 0
      // and Hermes is still not where omher looks.
      setInstallError(String(e));
      setInstall("failed");
    }
  }, [shell]);

  if (status?.state === "ready") return <>{children}</>;

  if (needsHermes || install !== "idle") {
    return (
      <div className="gate" data-testid="bridge-gate" data-state="setup">
        <div className="gate-box gate-setup" data-testid="setup-screen">
          <img className="gate-mark" src={mark} alt="" width={44} height={44} />
          <div className="gate-head" data-testid="setup-head">
            {install === "failed" ? t("gate.failedHead") : t("gate.head")}
          </div>
          <p className="gate-text">{t("gate.text")}</p>
          {command && (
            <div className="gate-cmdbox">
              <code className="gate-cmd" data-testid="setup-command">
                {/* one unbreakable token per word, and a line break before the pipe: the URL never wraps
                    at its own hyphens and the pipe never dangles at a line end */}
                {command.split(" ").map((word, i) => (
                  <Fragment key={i}>
                    {i > 0 &&
                      (word === "|" ? (
                        <>
                          {" "}
                          <br />
                        </>
                      ) : (
                        " "
                      ))}
                    <span className="gate-tok">{word}</span>
                  </Fragment>
                ))}
              </code>
              <button
                type="button"
                className="gate-copy"
                data-testid="setup-copy"
                aria-label={t("gate.copyCmd")}
                onClick={() => {
                  void navigator.clipboard?.writeText(command).then(() => setCopied(true), () => {});
                }}
              >
                {copied ? t("gate.copied") : t("gate.copy")}
              </button>
            </div>
          )}
          <InstallLog lines={lines} />
          {install === "failed" && (
            <p className="gate-error gate-error--bad" data-testid="setup-failed">
              {installError
                ? installError
                : exitCode === null
                  ? t("gate.couldNotRun")
                  : t("gate.stopped", { code: exitCode })}
            </p>
          )}
          <div className="gate-actions">
            <button
              type="button"
              className="gate-retry gate-primary"
              data-testid="setup-install"
              ref={installRef}
              autoFocus
              disabled={running}
              onClick={runInstall}
            >
              {running && <span className="gate-spin" aria-hidden="true" />}
              {running ? t("gate.installing") : install === "failed" ? t("gate.again") : t("gate.install")}
            </button>
            <button
              type="button"
              className="gate-retry gate-quiet"
              data-testid="bridge-retry"
              disabled={running || retrying}
              onClick={retry}
            >
              {t("gate.check")}
            </button>
          </div>
          {install !== "failed" && (
            <p className="gate-note" data-testid="setup-note">
              {t("gate.note")}
            </p>
          )}
        </div>
      </div>
    );
  }

  const failed = status?.state === "failed";
  return (
    <div className="gate" data-testid="bridge-gate" data-state={status?.state ?? "starting"}>
      <div className="gate-box">
        <div className="gate-title">{failed ? t("gate.unreachable") : t("gate.starting")}</div>
        {failed && (
          <>
            <p className="gate-error" data-testid="bridge-error">
              {status?.error || t("gate.noBridge")}
            </p>
            <button type="button" className="gate-retry" data-testid="bridge-retry" disabled={retrying} onClick={retry}>
              {t("gate.retry")}
            </button>
          </>
        )}
      </div>
    </div>
  );
}
