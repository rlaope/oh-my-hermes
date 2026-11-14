// Connect over SSH: one card for both ways in (the sidebar `+` popover, and a bot's `omher-peer` draft chip).
//   host + label -> Check -> what was found (the exact command, the remote Hermes, its bots) -> Cancel | Connect
// Check runs the shell's fixed `ssh` link once and reads the remote's `hello` and `bots.list` through it; nothing is
// written. Only Connect writes `~/.omher/peers.json` (the shell's `peers_add`). Errors are said in plain words; a
// host that wants a password is told to run `ssh-copy-id` itself, since omher never takes one.
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { BridgeClient } from "../lib/bridge";
import type { PeerProbe } from "../lib/protocol";
import { t } from "../i18n";
import { Spinner } from "../ui";
import { failKey, getPeersHost, type CheckResult, type Failure } from "./host";
import { labelFor, validHost, validLabel } from "./draft";
import { SshIcon } from "./SshMarker";
import { markFresh } from "./links";
import { CopyButton } from "../chat/parts/Copy";

/** The command as the card shows it: one option per line (`\` continuations), so it never breaks inside a word. */
export function commandLines(cmd: string): string {
  const parts = cmd.split(" ");
  const lines: string[] = [];
  for (let i = 0; i < parts.length; i++) {
    const p = parts[i];
    if (p === "--") {
      lines.push(parts.slice(i).join(" "));
      break;
    }
    if (p.startsWith("-") && i + 1 < parts.length && !parts[i + 1].startsWith("-") && p !== "-T") {
      lines.push(`${p} ${parts[i + 1]}`);
      i++;
    } else lines.push(p);
  }
  return lines.join(" \\\n  ");
}
import "./peers.css";

export interface AttachSeed {
  host?: string;
  label?: string;
  port?: number;
  /** The bot that proposed it (a draft chip): one quiet line on the card. */
  by?: string;
}

type Step =
  | { at: "form" }
  | { at: "checking" }
  | { at: "found"; check: CheckResult; probe: PeerProbe }
  | { at: "failed"; fail: Failure }
  | { at: "connecting" };

const FOCUSABLE = "button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex='-1'])";

async function probe(url: string, label: string): Promise<PeerProbe> {
  const b = new BridgeClient();
  try {
    await b.connect();
    return await b.request("peers.probe", { url, label });
  } finally {
    b.close();
  }
}

const failOf = (e: unknown): Failure => {
  if (e && typeof e === "object" && "kind" in e) return e as Failure;
  const line = e && typeof e === "object" && "message" in e ? String((e as { message: unknown }).message) : String(e);
  return { kind: "bridge", line };
};

export function AttachCard({ seed, onClose, onDone }: { seed: AttachSeed; onClose: () => void; onDone?: () => void }) {
  const [host, setHost] = useState(seed.host ?? "");
  const [label, setLabel] = useState(seed.label ?? "");
  const [labelTouched, setLabelTouched] = useState(!!seed.label);
  const [step, setStep] = useState<Step>({ at: "form" });
  const [hosts, setHosts] = useState<string[]>([]);
  const [err, setErr] = useState("");
  const box = useRef<HTMLDivElement>(null);
  const checkId = useRef<string | null>(null);

  useEffect(() => {
    void getPeersHost()
      .hosts()
      .then(setHosts)
      .catch(() => setHosts([]));
  }, []);
  useEffect(() => {
    box.current?.querySelector<HTMLElement>(seed.host ? "[data-testid=peer-check]" : "input")?.focus();
  }, [seed.host]);

  // a Check tunnel the card opened ends when the card closes without Connect
  useEffect(
    () => () => {
      if (checkId.current) void getPeersHost().checkClose(checkId.current).catch(() => undefined);
    },
    [],
  );

  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        close.current();
        return;
      }
      if (e.key !== "Tab" || !box.current) return;
      const els = [...box.current.querySelectorAll<HTMLElement>(FOCUSABLE)];
      if (!els.length) return;
      const first = els[0];
      const last = els[els.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKey, true);
    return () => document.removeEventListener("keydown", onKey, true);
  }, []);

  const h = host.trim();
  const shownLabel = (labelTouched ? label : label || labelFor(h)).trim();
  const hostOk = validHost(h);
  const labelOk = validLabel(shownLabel);

  const check = async () => {
    if (!hostOk || !labelOk) return;
    setErr("");
    setStep({ at: "checking" });
    try {
      if (checkId.current) await getPeersHost().checkClose(checkId.current).catch(() => undefined);
      const c = await getPeersHost().check(h, seed.port);
      checkId.current = c.check;
      const p = await probe(c.url, shownLabel);
      setStep({ at: "found", check: c, probe: p });
    } catch (e) {
      setStep({ at: "failed", fail: failOf(e) });
    }
  };

  const connect = async () => {
    if (step.at !== "found") return;
    setStep({ at: "connecting" });
    try {
      const st = await getPeersHost().add(shownLabel, h, seed.port, step.check.check);
      markFresh(st.id);
      checkId.current = null;
      onDone?.();
      onClose();
    } catch (e) {
      setErr(failOf(e).line);
      setStep({ at: "form" });
    }
  };

  const busy = step.at === "checking" || step.at === "connecting";
  const fail = step.at === "failed" ? step.fail : null;

  return createPortal(
    <div className="upd-veil peer-veil" data-testid="peer-veil" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={box} className="upd-dlg peer-card" role="dialog" aria-modal="true" aria-labelledby="peer-card-t" data-testid="peer-card">
        <h2 className="upd-dlg-t peer-t" id="peer-card-t">
          <SshIcon size={13} />
          {t("peer.title")}
        </h2>
        {seed.by && (
          <p className="peer-by" data-testid="peer-by">
            {t("peer.proposedBy", { bot: seed.by })}
          </p>
        )}
        <p className="peer-sub">{t("peer.sub")}</p>
        <div className="peer-form">
          <label className="peer-f">
            <span>{t("peer.host")}</span>
            <input
              value={host}
              onChange={(e) => {
                setHost(e.target.value);
                if (step.at !== "form") setStep({ at: "form" });
              }}
              onKeyDown={(e) => e.key === "Enter" && void check()}
              placeholder="user@host"
              list="peer-hosts"
              spellCheck={false}
              autoCapitalize="off"
              autoCorrect="off"
              disabled={busy}
              data-testid="peer-host"
              aria-invalid={!!h && !hostOk}
            />
            <datalist id="peer-hosts">
              {hosts.map((x) => (
                <option key={x} value={x} />
              ))}
            </datalist>
          </label>
          <label className="peer-f">
            <span>{t("peer.label")}</span>
            <input
              value={labelTouched ? label : label || labelFor(h)}
              onChange={(e) => {
                setLabelTouched(true);
                setLabel(e.target.value);
              }}
              onKeyDown={(e) => e.key === "Enter" && void check()}
              placeholder={t("peer.labelPh")}
              maxLength={40}
              disabled={busy}
              data-testid="peer-label"
            />
          </label>
          {hosts.length > 0 && step.at === "form" && !h && (
            <div className="peer-sugg" data-testid="peer-suggestions">
              <span>{t("peer.fromConfig")}</span>
              {hosts.slice(0, 6).map((x) => (
                <button type="button" key={x} className="peer-sugg-b" onClick={() => setHost(x)}>
                  {x}
                </button>
              ))}
            </div>
          )}
          {h && !hostOk && <p className="peer-warn" data-testid="peer-host-bad">{t("peer.badHost")}</p>}
        </div>

        {step.at === "checking" && (
          <div className="peer-wait" data-testid="peer-checking">
            <Spinner size={12} label={t("peer.checking")} />
            <span>{t("peer.checkingHost", { host: h })}</span>
          </div>
        )}

        {fail && (
          <div className="peer-fail" role="alert" data-testid="peer-fail" data-kind={fail.kind}>
            <b>{t(failKey(fail.kind), { host: h })}</b>
            {fail.kind === "auth" && (
              <div className="peer-cmd-w">
                <code className="peer-cmd">ssh-copy-id {h}</code>
                <CopyButton className="peer-copy" text={() => `ssh-copy-id ${h}`} testId="peer-copy-fix" />
              </div>
            )}
            {fail.line && fail.kind !== "auth" && <span className="peer-line">{fail.line}</span>}
          </div>
        )}

        {step.at === "found" && (
          <div className="peer-found" data-testid="peer-found">
            <div className="peer-k">{t("peer.willRun")}</div>
            <div className="peer-cmd-w">
              <code className="peer-cmd" data-testid="peer-command">
                {commandLines(step.check.found.command)}
              </code>
              <CopyButton className="peer-copy" text={() => step.check.found.command} testId="peer-copy-command" />
            </div>
            <div className="peer-k">{t("peer.hermesThere")}</div>
            <div className="peer-v" data-testid="peer-hermes">
              {t("peer.hermesLine", { version: step.probe.hermes.version || "?", py: step.check.found.pyver || "?" })}
              <span className="peer-path">{step.check.found.python}</span>
            </div>
            <div className="peer-k">{t("peer.botsThere", { n: step.probe.bots.length })}</div>
            <ul className="peer-bots" data-testid="peer-bots">
              {step.probe.bots.map((b) => (
                <li key={b.name}>
                  <b>{b.display_name}</b>
                  {b.name !== b.display_name && <code>{b.name}</code>}
                </li>
              ))}
              {step.probe.bots.length === 0 && <li className="peer-none">{t("peer.noBots")}</li>}
            </ul>
            <p className="peer-note">{t("peer.writes")}</p>
          </div>
        )}

        {err && (
          <p className="peer-warn" role="alert" data-testid="peer-error">
            {err}
          </p>
        )}

        <div className="upd-dlg-f">
          <button type="button" className="upd-dlg-btn" onClick={onClose} data-testid="peer-cancel">
            {t("update.cancel")}
          </button>
          {step.at === "found" || step.at === "connecting" ? (
            <button type="button" className="upd-dlg-btn primary" onClick={() => void connect()} disabled={busy} data-testid="peer-connect">
              {step.at === "connecting" ? t("peer.connectingNow") : t("peer.connect")}
            </button>
          ) : (
            <button type="button" className="upd-dlg-btn primary" onClick={() => void check()} disabled={busy || !hostOk || !labelOk} data-testid="peer-check">
              {fail ? t("peer.checkAgain") : t("peer.check")}
            </button>
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}
