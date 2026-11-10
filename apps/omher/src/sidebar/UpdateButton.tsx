// The update control in the sidebar's user row. Hidden until a newer signed release exists; then one
// small button ("Update to 0.1.2") downloads and installs it, shows the progress, and restarts omher.
// A failed check stays quiet (the next one runs in 6 hours); a failed install says why in one line.
import { useCallback, useEffect, useRef, useState } from "react";
import { Spinner } from "../ui";
import { percent, shortError, updateHost, type PendingUpdate } from "./updater";

const EVERY_MS = 6 * 60 * 60 * 1000;

type State =
  | { kind: "none" }
  | { kind: "ready"; update: PendingUpdate }
  | { kind: "installing"; update: PendingUpdate; pct: number | null }
  | { kind: "restarting" }
  | { kind: "failed"; update: PendingUpdate; error: string };

export function UpdateButton() {
  const [st, setSt] = useState<State>({ kind: "none" });
  const busy = useRef(false);

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
      await host.relaunch();
    } catch (e) {
      busy.current = false;
      setSt({ kind: "failed", update, error: shortError(e) });
    }
  }, []);

  if (st.kind === "none") return null;
  if (st.kind === "installing" || st.kind === "restarting") {
    const label = st.kind === "restarting" ? "Restarting…" : st.pct === null ? "Updating…" : `Updating ${st.pct}%`;
    return (
      <span className="upd upd-busy" data-testid="update-progress" aria-live="polite">
        <Spinner size={10} label={label} />
        {label}
      </span>
    );
  }
  return (
    <>
      <button
        type="button"
        className="upd"
        data-testid="update-btn"
        title={st.kind === "failed" ? st.error : `Install omher ${st.update.version} and restart`}
        onClick={() => void install(st.update)}
      >
        {st.kind === "failed" ? "Retry update" : `Update to ${st.update.version}`}
      </button>
      {st.kind === "failed" && (
        <span className="upd-err" role="alert" data-testid="update-error">
          {st.error}
        </span>
      )}
    </>
  );
}
