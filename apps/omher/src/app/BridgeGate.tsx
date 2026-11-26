// While the Tauri shell's bridge is not up, say so on one centred screen instead of an empty app.
// Outside Tauri (browser dev, e2e against the mock) there is no shell to ask and the app renders directly,
// unless the page sets `window.__OMHER_GATE__` (the e2e stand-in for the shell).
//
// When Hermes itself is missing, the screen offers to install Hermes and oh-my-hermes. The shell runs one
// fixed command (OMH's one-line installer with `omher`, without the app); the page only presses the
// button and shows the output.
import { Fragment, useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import mark from "../assets/omher-mark.png";
import "./gate.css";
import { t } from "../i18n";
import { omhInstalled } from "../onboarding/omhPrompt";
import type { CheckResult, FailKind } from "../peers/host";
import { UpdateButton } from "../sidebar/UpdateButton";
import "../sidebar/sidebar.css";
import { CHANGE_SERVER_EVENT, noteServerMode, serverLabel } from "./remote";
import { RemoteConnect } from "./RemoteConnect";

/** `bridge_status`. Local mode may name `missing: "hermes"`; remote-only mode (rule 46) names the server's `host` and
 *  never `missing` (connecting and reconnecting both read `starting`, with the last failure line in `error`). */
export type BridgeState = { state: "ready" | "starting" | "failed"; error?: string; missing?: "hermes"; mode?: "local" | "remote"; host?: string };
export type InstallEvent = { kind: "line"; text: string } | { kind: "exit"; code: number | null };

/** `remote_status`, `remote_use` and `remote_leave`: the mode file and its link. */
export type RemoteStatus =
  | { mode: "local" }
  | {
      mode: "remote";
      host: string;
      port?: number;
      label: string;
      state: "connecting" | "connected" | "reconnecting" | "failed";
      kind?: FailKind;
      reason?: string;
      attempt?: number;
    };

/** The shell's commands, or the e2e stand-in. The remote ones are optional so an older stand-in still loads. */
export interface GateShell {
  status(): Promise<BridgeState>;
  retry(): Promise<void>;
  installCommand(): Promise<string>;
  install(onEvent: (e: InstallEvent) => void): Promise<number | null>;
  /** `peers_hosts`: names from ~/.ssh/config. */
  hosts?(): Promise<string[]>;
  /** `remote_check`: one link up, nothing written; fails with `{kind, line}`. */
  remoteCheck?(host: string, port?: number): Promise<CheckResult>;
  /** `peers_check_close`: a Check link no Connect took. */
  remoteCheckClose?(check: string): Promise<void>;
  /** `remote_use`: writes ~/.omher/remote.json and switches to that server now (adopting the checked link). */
  remoteUse?(label: string, host: string, port: number | undefined, check: string | undefined): Promise<RemoteStatus>;
  /** `remote_leave`: deletes the file, stops the link, starts this computer's bridge again. */
  remoteLeave?(): Promise<RemoteStatus>;
  remoteStatus?(): Promise<RemoteStatus>;
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
    hosts: () => invoke<string[]>("peers_hosts"),
    remoteCheck: (host, port) => invoke<CheckResult>("remote_check", { host, port: port ?? null }),
    remoteCheckClose: (check) => invoke<void>("peers_check_close", { check }),
    remoteUse: (label, host, port, check) => invoke<RemoteStatus>("remote_use", { label, host, port: port ?? null, check: check ?? null }),
    remoteLeave: () => invoke<RemoteStatus>("remote_leave"),
    remoteStatus: () => invoke<RemoteStatus>("remote_status"),
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
          {compact ? slashBreaks(line) : line}
        </span>
      ))}
    </pre>
  );
}

/** A line with a break chance (`<wbr>`) after each "/" inside a path (a word starting with `/`, `~/`, `./` or holding
 *  `://`), so the small log wraps a path between its parts and never inside a word; other words break only at spaces. */
export function slashBreaks(line: string): ReactNode[] {
  const out: ReactNode[] = [];
  let k = 0;
  for (const word of line.split(/(\s+)/)) {
    if (!/^(~|\.{1,2})?\/|:\/\//.test(word)) {
      out.push(word);
      continue;
    }
    word.split(/(?<=\/)(?=[^/])/).forEach((part, i) => {
      if (i) out.push(<wbr key={`w${k++}`} />);
      out.push(part);
    });
  }
  return out;
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

/** Where the gate stands: `boot` (the app has not been up yet: the screen alone), `up` (the app shows; a bridge that
 *  died is being started again and the chats say they are reconnecting), `down` (the shell gave up after the app was up:
 *  a bar says so and offers Retry, and the app stays usable under it, terminals included, until the bridge is ready). */
export type GateMode = "boot" | "up" | "down";

export function gateMode(prev: GateMode, state: BridgeState["state"] | undefined, remote = false): GateMode {
  if (state === "ready") return "up";
  if (prev === "up" && state === "failed") return "down";
  // a server's link that drops is said at once (the shell is already reconnecting it): the bar, never the gate
  if (remote && prev === "up" && state === "starting") return "down";
  return prev;
}

/** One `bridge_status` answer against the last: the same answer keeps the same object (a steady poll re-renders nothing). */
export const sameStatus = (a: BridgeState | null, b: BridgeState) =>
  !!a && a.state === b.state && a.error === b.error && a.missing === b.missing && a.mode === b.mode && a.host === b.host;

/** How often the gate asks the shell: often while the bridge is not up, then every couple of seconds so a bridge that
 *  dies later (and a shell that gives up on starting it again) is seen without a restart. */
export const pollMs = (ready: boolean) => (ready ? 2000 : 500);

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
  const ready = status?.state === "ready";
  useEffect(() => {
    if (!hasShell() || running) return;
    let alive = true;
    const poll = async () => {
      try {
        const s = await (await shell()).status();
        // the same answer keeps the same object: a steady "ready" every 2 s re-renders nothing
        if (alive) setStatus((prev) => (sameStatus(prev, s) ? prev : s));
      } catch (e) {
        // once the bridge is up, one refused ask (a webview reload, say) is not a failure: the shell answers the next one
        if (alive) setStatus((prev) => (prev?.state === "ready" ? prev : { state: "failed", error: String(e) }));
      }
    };
    if (!ready) void poll();
    const h = setInterval(poll, pollMs(ready));
    return () => {
      alive = false;
      clearInterval(h);
    };
  }, [ready, running, shell]);

  const remote = status?.mode === "remote";
  const host = remote ? status?.host : undefined;
  useEffect(() => {
    if (status) noteServerMode(status);
  }, [status]);
  // the server's name (the mode file's label) for "Connecting to <label>…": asked once per host
  const [label, setLabel] = useState("");
  useEffect(() => {
    if (!host) return;
    let alive = true;
    void shell()
      .then((s) => s.remoteStatus?.())
      .then((r) => {
        if (!alive || !r || r.mode !== "remote") return;
        setLabel(r.label);
        noteServerMode({ mode: "remote", host: r.host, label: r.label });
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [host, shell]);
  const name = serverLabel({ host, label });

  // Settings › Server › Change server: the Connect form over the app; a Connect there reloads onto the new server
  const [changing, setChanging] = useState(false);
  useEffect(() => {
    const open = () => setChanging(true);
    window.addEventListener(CHANGE_SERVER_EVENT, open);
    return () => window.removeEventListener(CHANGE_SERVER_EVENT, open);
  }, []);
  // the first screen's two ways in: install Hermes here, or use one on a server
  const [choice, setChoice] = useState<"install" | "remote">("install");
  const [leaving, setLeaving] = useState(false);
  const [leaveError, setLeaveError] = useState("");
  const useThisComputer = useCallback(async () => {
    setLeaving(true);
    setLeaveError("");
    try {
      await (await shell()).remoteLeave?.();
      setStatus({ state: "starting" });
      setChoice("install");
    } catch (e) {
      setLeaveError(String(e));
    } finally {
      setLeaving(false);
    }
  }, [shell]);

  const [mode, setMode] = useState<GateMode>("boot");
  const nextMode = gateMode(mode, status?.state, remote);
  if (nextMode !== mode) setMode(nextMode);

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
        // the installer's own default profile is the new person's bot: land in its chat (the connect block shows
        // there when it has no AI account yet)
        omhInstalled("default");
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

  const changeForm = changing && (
    <div className="gate gate-over" data-testid="change-server">
      <div className="gate-box gate-setup">
        <img className="gate-mark" src={mark} alt="" width={44} height={44} />
        <div className="gate-head">{t("remote.changeHead")}</div>
        <RemoteConnect shell={shell} onCancel={() => setChanging(false)} onDone={() => window.location.reload()} />
      </div>
    </div>
  );

  if (nextMode === "up")
    return (
      <>
        {children}
        {changeForm}
      </>
    );
  // after the app was up, nothing hides it: terminals need no bridge, and a hidden one could still take keystrokes
  if (nextMode === "down") {
    const failed = status?.state === "failed";
    return (
      <>
        {children}
        <div className="gate-bar" role={failed ? "alert" : "status"} data-testid="bridge-bar" data-state={status?.state ?? "starting"}>
          <span className="gate-bar-title">
            {remote ? (failed ? t("remote.unreachable", { label: name }) : t("remote.lost", { label: name })) : failed ? t("gate.unreachable") : t("gate.reviving")}
          </span>
          {remote && !failed && status?.error && (
            <span className="gate-bar-error" data-testid="bridge-error" title={status.error}>
              {status.error}
            </span>
          )}
          {failed && (
            <>
              <span className="gate-bar-error" data-testid="bridge-error" title={status?.error}>
                {status?.error || t("gate.noBridge")}
              </span>
              <button type="button" className="gate-retry" data-testid="bridge-retry" disabled={retrying} onClick={retry}>
                {t("gate.retry")}
              </button>
            </>
          )}
        </div>
        {changeForm}
      </>
    );
  }

  // remote-only mode before the app was up: the server's name, the last failure line, Retry, and the way back
  if (remote) {
    const failed = status?.state === "failed";
    return (
      <div className="gate" data-testid="bridge-gate" data-state={status?.state ?? "starting"} data-mode="remote">
        <div className="gate-box gate-setup" data-testid="remote-gate">
          <img className="gate-mark" src={mark} alt="" width={44} height={44} />
          <div className="gate-head" data-testid="remote-head">
            {failed ? t("remote.unreachable", { label: name }) : t("remote.connecting", { label: name })}
          </div>
          {host && host !== name && <code className="gate-remote-at">{host}</code>}
          {!failed && <span className="gate-spin gate-spin-lg" aria-hidden="true" />}
          {status?.error && (
            <p className={`gate-error${failed ? " gate-error--bad" : ""}`} data-testid="bridge-error">
              {status.error}
            </p>
          )}
          {leaveError && (
            <p className="gate-error gate-error--bad" role="alert">
              {leaveError}
            </p>
          )}
          <div className="gate-actions">
            <button type="button" className="gate-retry gate-primary" data-testid="bridge-retry" disabled={retrying} onClick={retry}>
              {t("gate.retry")}
            </button>
            <button type="button" className="gate-retry gate-quiet" data-testid="remote-leave" disabled={leaving} onClick={() => void useThisComputer()}>
              {t("remote.useHere")}
            </button>
          </div>
          <GateUpdate />
        </div>
      </div>
    );
  }

  if (needsHermes || install !== "idle") {
    return (
      <div className="gate" data-testid="bridge-gate" data-state="setup">
        <div className="gate-box gate-setup" data-testid="setup-screen">
          <img className="gate-mark" src={mark} alt="" width={44} height={44} />
          <div className="gate-head" data-testid="setup-head">
            {install === "failed" ? t("gate.failedHead") : choice === "remote" ? t("remote.head") : t("gate.head")}
          </div>
          <div className="gate-choice" role="group" aria-label={t("remote.choiceLabel")} data-testid="gate-choices">
            <button
              type="button"
              className="gate-choice-b"
              aria-pressed={choice === "install"}
              disabled={running}
              onClick={() => setChoice("install")}
              data-testid="gate-choice-install"
            >
              {t("remote.choiceInstall")}
            </button>
            <button
              type="button"
              className="gate-choice-b"
              aria-pressed={choice === "remote"}
              disabled={running}
              onClick={() => setChoice("remote")}
              data-testid="gate-choice-remote"
            >
              {t("remote.choiceRemote")}
            </button>
          </div>
          {choice === "remote" ? (
            <RemoteConnect shell={shell} onDone={() => setStatus({ state: "starting", mode: "remote" })} />
          ) : (
          <>
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
          </>
          )}
          <GateUpdate />
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

/** The update button on the gate: the updater needs no bridge, so a person stuck here can still update in place. */
function GateUpdate() {
  return (
    <div className="gate-upd" data-testid="gate-update">
      <UpdateButton />
    </div>
  );
}
