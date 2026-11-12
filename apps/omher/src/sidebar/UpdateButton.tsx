// The update control in the sidebar's user row. Hidden until a newer signed release exists; then one
// small button ("Update to 0.1.2") asks first (omher will restart; chats, panels and sessions pick up where they
// were), then downloads and installs it, shows the progress, saves what is open and restarts omher.
// A failed check stays quiet (the next one runs in 6 hours); a failed install says why in one line.
import { useCallback, useEffect, useRef, useState } from "react";
import { Spinner } from "../ui";
import { t } from "../i18n";
import { percent, shortError, updateHost, type PendingUpdate } from "./updater";
import { runningLine, UpdateConfirm } from "./UpdateConfirm";
import { getSessions } from "../sessions/sessions";
import { sessionMode } from "../sessions/agents";
import { saveResumeNow } from "../app/resumeBoot";

const EVERY_MS = 6 * 60 * 60 * 1000;

type State =
  | { kind: "none" }
  | { kind: "ready"; update: PendingUpdate }
  | { kind: "installing"; update: PendingUpdate; pct: number | null }
  | { kind: "restarting" }
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
    let live = true;
    const run = async () => {
      if (busy.current) return;
      try {
        const u = await host.check();
        if (live && !busy.current) setSt(u ? { kind: "ready", update: u } : { kind: "none" });
      } catch {
        /* offline or the endpoint is down: try again on the next tick */
      }
    };
    void run();
    const t = window.setInterval(run, EVERY_MS);
    return () => {
      live = false;
      window.clearInterval(t);
    };
  }, []);

  const install = useCallback(async (update: PendingUpdate) => {
    const host = updateHost();
    if (!host || busy.current) return;
    busy.current = true;
    setSt({ kind: "installing", update, pct: null });
    try {
      await update.install((p) => setSt({ kind: "installing", update, pct: percent(p) }));
      setSt({ kind: "restarting" });
      // what is open right now, so the new version opens it again
      saveResumeNow();
      await host.relaunch();
    } catch (e) {
      busy.current = false;
      setSt({ kind: "failed", update, error: shortError(e) });
    }
  }, []);

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
  const update = st.update;
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
        title={st.kind === "failed" ? st.error : t("upd.tip", { version: update.version })}
        onClick={() => setAsking(true)}
      >
        {st.kind === "failed" ? t("upd.retry") : t("upd.to", { version: st.update.version })}
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
            void install(update);
          }}
        />
      )}
    </>
  );
}
