// Connect to a server over SSH (remote-only mode, BOUNDARY rule 47): the gate's second choice, and Settings › Server ›
// Change server. host (with ~/.ssh/config names) + port + name -> Check -> what the server has (the exact command, its
// Hermes, its bots: read straight through the link Check opened, since this computer has no bridge of its own) ->
// Connect. Only Connect writes ~/.omher/remote.json (the shell's `remote_use`). Failures read as a peer's do; a key
// the server refuses names `ssh-copy-id`, since omher never takes a password.
import { useEffect, useRef, useState } from "react";
import { BridgeClient } from "../lib/bridge";
import type { Bot, HelloResult } from "../lib/protocol";
import { t } from "../i18n";
import { Spinner } from "../ui";
import { CopyButton } from "../chat/parts/Copy";
import { commandLines } from "../peers/AttachCard";
import { failKey, type CheckResult, type Failure } from "../peers/host";
import { labelFor, validHost, validLabel } from "../peers/draft";
import { parsePort } from "./remote";
import type { GateShell } from "./BridgeGate";
import "../peers/peers.css";

export interface RemoteProbe {
  hello: HelloResult;
  bots: Bot[];
}

type Step =
  | { at: "form" }
  | { at: "checking" }
  | { at: "found"; check: CheckResult; probe: RemoteProbe }
  | { at: "failed"; fail: Failure }
  | { at: "connecting" };

const PROBE_MS = 15_000;

/** The server's `hello` and `bots.list`, read through the URL Check returned (its own bridge, at the end of the link). */
export async function probeRemote(url: string, ms = PROBE_MS): Promise<RemoteProbe> {
  const b = new BridgeClient({ url, maxDelay: 1000 });
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    const late = new Promise<never>((_, rej) => {
      timer = setTimeout(() => rej({ kind: "timeout", line: "" }), ms);
    });
    return await Promise.race([
      (async () => {
        await b.connect();
        const [hello, list] = await Promise.all([b.request("hello"), b.request("bots.list")]);
        return { hello, bots: list.bots };
      })(),
      late,
    ]);
  } finally {
    if (timer) clearTimeout(timer);
    b.close();
  }
}

/** What went wrong, as the shell's `peers::Failure`, or the bridge's own words. */
export const failOf = (e: unknown): Failure => {
  if (e && typeof e === "object" && "kind" in e) return e as Failure;
  const line = e && typeof e === "object" && "message" in e ? String((e as { message: unknown }).message) : String(e);
  return { kind: "bridge", line };
};

export function RemoteConnect({ shell, onCancel, onDone }: { shell: () => Promise<GateShell>; onCancel?: () => void; onDone?: () => void }) {
  const [host, setHost] = useState("");
  const [port, setPort] = useState("");
  const [label, setLabel] = useState("");
  const [labelTouched, setLabelTouched] = useState(false);
  const [hosts, setHosts] = useState<string[]>([]);
  const [step, setStep] = useState<Step>({ at: "form" });
  const [err, setErr] = useState("");
  const checkId = useRef<string | null>(null);
  // false once the form is gone: a Check that answers after that closes its own link at once
  const mounted = useRef(true);
  const hostRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    hostRef.current?.focus();
    void shell()
      .then((s) => s.hosts?.() ?? [])
      .then(setHosts)
      .catch(() => setHosts([]));
  }, [shell]);
  // a Check link the form opened ends when the form goes away without Connect
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      const id = checkId.current;
      checkId.current = null;
      if (id) void shell().then((s) => s.remoteCheckClose?.(id)).catch(() => undefined);
    };
  }, [shell]);

  const h = host.trim();
  const p = parsePort(port);
  const shownLabel = (labelTouched ? label : label || labelFor(h)).trim();
  const hostOk = validHost(h);
  const ok = hostOk && p !== null && validLabel(shownLabel);
  const busy = step.at === "checking" || step.at === "connecting";
  const fail = step.at === "failed" ? step.fail : null;
  const edit = () => step.at !== "form" && !busy && setStep({ at: "form" });

  const check = async () => {
    if (!ok || busy) return;
    setErr("");
    setStep({ at: "checking" });
    try {
      const s = await shell();
      if (checkId.current) {
        const old = checkId.current;
        checkId.current = null;
        await s.remoteCheckClose?.(old).catch(() => undefined);
      }
      if (!s.remoteCheck) throw { kind: "bridge", line: "" };
      const c = await s.remoteCheck(h, p ?? undefined);
      // the form went away while Check ran (Install picked, Change server cancelled): nothing will Connect it
      if (!mounted.current) {
        await s.remoteCheckClose?.(c.check).catch(() => undefined);
        return;
      }
      checkId.current = c.check;
      setStep({ at: "found", check: c, probe: await probeRemote(c.url) });
    } catch (e) {
      setStep({ at: "failed", fail: failOf(e) });
    }
  };

  const connect = async () => {
    if (step.at !== "found") return;
    const used = step.check.check;
    setStep({ at: "connecting" });
    try {
      const s = await shell();
      if (!s.remoteUse) throw new Error("");
      await s.remoteUse(shownLabel, h, p ?? undefined, used);
      // the shell adopted the checked link: it is no longer this form's to close
      checkId.current = null;
      onDone?.();
    } catch (e) {
      setErr(failOf(e).line || String(e));
      setStep({ at: "form" });
    }
  };

  const enter = (e: React.KeyboardEvent) => e.key === "Enter" && void (step.at === "found" ? connect() : check());

  return (
    <div className="gate-remote" data-testid="remote-connect">
      <p className="gate-text">{t("remote.text")}</p>
      <div className="peer-form">
        <div className="gate-remote-row">
          <label className="peer-f gate-remote-host">
            <span>{t("peer.host")}</span>
            <input
              ref={hostRef}
              value={host}
              onChange={(e) => {
                setHost(e.target.value);
                edit();
              }}
              onKeyDown={enter}
              placeholder="user@host"
              list="remote-hosts"
              spellCheck={false}
              autoCapitalize="off"
              autoCorrect="off"
              disabled={busy}
              data-testid="remote-host"
              aria-invalid={!!h && !hostOk}
            />
            <datalist id="remote-hosts">
              {hosts.map((x) => (
                <option key={x} value={x} />
              ))}
            </datalist>
          </label>
          <label className="peer-f gate-remote-port">
            <span>{t("remote.port")}</span>
            <input
              value={port}
              onChange={(e) => {
                setPort(e.target.value);
                edit();
              }}
              onKeyDown={enter}
              placeholder="22"
              inputMode="numeric"
              maxLength={5}
              disabled={busy}
              data-testid="remote-port"
              aria-invalid={p === null}
            />
          </label>
        </div>
        <label className="peer-f">
          <span>{t("peer.label")}</span>
          <input
            value={labelTouched ? label : label || labelFor(h)}
            onChange={(e) => {
              setLabelTouched(true);
              setLabel(e.target.value);
            }}
            onKeyDown={enter}
            placeholder={t("remote.labelPh")}
            maxLength={40}
            disabled={busy}
            data-testid="remote-label"
          />
        </label>
        {hosts.length > 0 && step.at === "form" && !h && (
          <div className="peer-sugg" data-testid="remote-suggestions">
            <span>{t("peer.fromConfig")}</span>
            {hosts.slice(0, 6).map((x) => (
              <button type="button" key={x} className="peer-sugg-b" onClick={() => setHost(x)}>
                {x}
              </button>
            ))}
          </div>
        )}
        {h && !hostOk && <p className="peer-warn" data-testid="remote-host-bad">{t("peer.badHost")}</p>}
        {p === null && <p className="peer-warn" data-testid="remote-port-bad">{t("remote.badPort")}</p>}
      </div>

      {step.at === "checking" && (
        <div className="peer-wait" data-testid="remote-checking">
          <Spinner size={12} label={t("peer.checking")} />
          <span>{t("peer.checkingHost", { host: h })}</span>
        </div>
      )}

      {fail && (
        <div className="peer-fail" role="alert" data-testid="remote-fail" data-kind={fail.kind}>
          <b>{t(failKey(fail.kind), { host: h })}</b>
          {fail.kind === "auth" && (
            <div className="peer-cmd-w">
              <code className="peer-cmd" data-testid="remote-fix">
                ssh-copy-id {h}
              </code>
              <CopyButton className="peer-copy" text={() => `ssh-copy-id ${h}`} testId="remote-copy-fix" />
            </div>
          )}
          {fail.line && fail.kind !== "auth" && <span className="peer-line">{fail.line}</span>}
        </div>
      )}

      {step.at === "found" && (
        <div className="peer-found" data-testid="remote-found">
          <div className="peer-k">{t("peer.willRun")}</div>
          <div className="peer-cmd-w">
            <code className="peer-cmd" data-testid="remote-command">
              {commandLines(step.check.found.command)}
            </code>
            <CopyButton className="peer-copy" text={() => step.check.found.command} testId="remote-copy-command" />
          </div>
          <div className="peer-k">{t("peer.hermesThere")}</div>
          <div className="peer-v" data-testid="remote-hermes">
            {t("peer.hermesLine", { version: step.probe.hello.hermes.version || "?", py: step.check.found.pyver || "?" })}
            <span className="peer-path">{step.check.found.python}</span>
          </div>
          <div className="peer-k">{t("peer.botsThere", { n: step.probe.bots.length })}</div>
          <ul className="peer-bots" data-testid="remote-bots">
            {step.probe.bots.map((b) => (
              <li key={b.name}>
                <b>{b.display_name}</b>
                {b.name !== b.display_name && <code>{b.name}</code>}
              </li>
            ))}
            {step.probe.bots.length === 0 && <li className="peer-none">{t("peer.noBots")}</li>}
          </ul>
          <p className="peer-note">{t("remote.writes")}</p>
        </div>
      )}

      {err && (
        <p className="peer-warn" role="alert" data-testid="remote-error">
          {err}
        </p>
      )}

      <div className="gate-actions">
        {step.at === "found" || step.at === "connecting" ? (
          <button type="button" className="gate-retry gate-primary" onClick={() => void connect()} disabled={busy} data-testid="remote-use">
            {step.at === "connecting" && <span className="gate-spin" aria-hidden="true" />}
            {step.at === "connecting" ? t("peer.connectingNow") : t("peer.connect")}
          </button>
        ) : (
          <button type="button" className="gate-retry gate-primary" onClick={() => void check()} disabled={busy || !ok} data-testid="remote-check">
            {step.at === "checking" && <span className="gate-spin" aria-hidden="true" />}
            {fail ? t("peer.checkAgain") : t("peer.check")}
          </button>
        )}
        {onCancel && (
          <button type="button" className="gate-retry gate-quiet" onClick={onCancel} disabled={step.at === "connecting"} data-testid="remote-cancel">
            {t("update.cancel")}
          </button>
        )}
      </div>
    </div>
  );
}
