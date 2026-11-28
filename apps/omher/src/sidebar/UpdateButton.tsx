// The update control in the sidebar's user row. Hidden until a newer signed release exists; then one
// small button ("Update to 0.1.2") asks first (omher will restart; chats, panels and sessions pick up where they
// were), then downloads and installs it, shows the progress, saves what is open and restarts omher.
// A failed check stays quiet and is tried again within minutes; coming back to the window checks too when the
// last good check is half an hour old (`watchForUpdates`). A failed install says why in one line. A restart that does
// not happen (the relaunch was refused, or omher is still here 10 s later) shows "Waiting to restart" with Restart
// again / Later; the update is installed by then, so neither downloads it again, and each restart saves what is open.
import { useCallback, useEffect, useRef, useState } from "react";
import { Spinner } from "../ui";
import { t } from "../i18n";
import { percent, relaunchOrWait, shortError, updateHost, watchForUpdates, type PendingUpdate } from "./updater";
import { runningLine, UpdateConfirm } from "./UpdateConfirm";
import { getSessions } from "../sessions/sessions";
import { sessionMode } from "../sessions/agents";
import { saveResumeNow } from "../app/resumeBoot";

type State =
  | { kind: "none" }
  | { kind: "ready"; update: PendingUpdate }
  | { kind: "installing"; update: PendingUpdate; pct: number | null }
  | { kind: "restarting"; update: PendingUpdate }
  /** Installed, but omher is still here after asking for the restart: the card with Restart again / Later. */
  | { kind: "waiting"; update: PendingUpdate }
  /** Installed, the card closed with Later: the button restarts (never installs again). */
  | { kind: "installed"; update: PendingUpdate }
  | { kind: "failed"; update: PendingUpdate; error: string };

export function UpdateButton() {
  const [st, setSt] = useState<State>({ kind: "none" });
  const [asking, setAsking] = useState(false);
  const busy = useRef(false);
  const btn = useRef<HTMLButtonElement>(null);
  /** Cancel / Esc give the focus back to the button once the dialog (and its focus trap) is gone. */
  const refocus = useRef(false);
  useEffect(() => {
    if (asking || !refocus.current) return;
    refocus.current = false;
    btn.current?.focus();
  }, [asking]);

  useEffect(() => {
    const host = updateHost();
    if (!host) return;
    return watchForUpdates(
      host,
      (u) => setSt(u ? { kind: "ready", update: u } : { kind: "none" }),
      () => busy.current,
    );
  }, []);

  const stopWait = useRef<(() => void) | null>(null);
  useEffect(() => () => stopWait.current?.(), []);

  /** One restart attempt of an installed update: saves what is open first (every attempt), never installs. */
  const restart = useCallback((update: PendingUpdate) => {
    const host = updateHost();
    if (!host) return;
    stopWait.current?.();
    setSt({ kind: "restarting", update });
    // what is open right now, so the new version opens it again
    stopWait.current = relaunchOrWait(host, saveResumeNow, () => setSt({ kind: "waiting", update }));
  }, []);

  const install = useCallback(async (update: PendingUpdate) => {
    const host = updateHost();
    if (!host || busy.current) return;
    busy.current = true;
    setSt({ kind: "installing", update, pct: null });
    try {
      await update.install((p) => setSt({ kind: "installing", update, pct: percent(p) }));
    } catch (e) {
      busy.current = false;
      setSt({ kind: "failed", update, error: shortError(e) });
      return;
    }
    // installed: busy stays set, so no later check offers (and installs) it again
    restart(update);
  }, [restart]);

  if (st.kind === "none") return null;
  if (st.kind === "installing" || st.kind === "restarting") {
    const label = st.kind === "restarting" ? t("upd.restarting") : st.pct === null ? t("upd.updating") : t("upd.updatingPct", { n: st.pct });
    return (
      <span className="upd upd-busy" data-testid="update-progress" aria-live="polite">
        <Spinner size={10} label={label} />
        {label}
      </span>
    );
  }
  if (st.kind === "waiting") {
    const update = st.update;
    return (
      <>
        <span className="upd upd-busy" data-testid="update-progress">
          {t("upd.waiting")}
        </span>
        <div className="upd-wait" role="alertdialog" aria-label={t("upd.waiting")} data-testid="update-waiting">
          <p className="upd-dlg-t">{t("upd.waiting")}</p>
          <p className="upd-wait-b">{t("upd.waitingBody", { version: update.version })}</p>
          <div className="upd-dlg-f">
            <button type="button" className="upd-dlg-btn" data-testid="update-later" onClick={() => setSt({ kind: "installed", update })}>
              {t("upd.later")}
            </button>
            <button type="button" className="upd-dlg-btn primary" data-testid="update-restart-again" autoFocus onClick={() => restart(update)}>
              {t("upd.restartAgain")}
            </button>
          </div>
        </div>
      </>
    );
  }
  const update = st.update;
  const installed = st.kind === "installed";
  const close = () => {
    refocus.current = true;
    setAsking(false);
  };
  const ss = asking ? getSessions().getState() : null;
  return (
    <>
      <button
        ref={btn}
        type="button"
        className="upd"
        data-testid="update-btn"
        aria-haspopup="dialog"
        aria-expanded={asking}
        title={st.kind === "failed" ? st.error : installed ? t("upd.restartTo", { version: update.version }) : t("upd.tip", { version: update.version })}
        onClick={() => setAsking(true)}
      >
        {st.kind === "failed" ? t("upd.retry") : installed ? t("upd.restartTo", { version: update.version }) : t("upd.to", { version: st.update.version })}
      </button>
      {st.kind === "failed" && (
        <span className="upd-err" role="alert" data-testid="update-error">
          {st.error}
        </span>
      )}
      {asking && ss && (
        <UpdateConfirm
          version={update.version}
          running={runningLine(ss.list, (r) => sessionMode(ss.agents, r))}
          onCancel={close}
          onConfirm={() => {
            setAsking(false);
            if (installed) restart(update);
            else void install(update);
          }}
        />
      )}
    </>
  );
}
