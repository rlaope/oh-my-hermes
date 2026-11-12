// The sidebar's one sign that oh-my-hermes is missing: a quiet "!" circle left of the top row's +, shown only to a
// person who has Hermes and not `omh` (and not after "Don't show again"). It opens a small popover: what oh-my-hermes
// adds, Install (the shell's one fixed installer, its output shown here in the setup screen's own log view) and
// "Don't show again". When the install ends well the agents are read again, `omh` is found and the "!" goes.
import { useEffect } from "react";
import { IconButton, Popover, Spinner } from "../ui";
import { t } from "../i18n";
import { InstallLog } from "../app/BridgeGate";
import { hermesOnly } from "../sessions/agents";
import { getSessions, useSessions } from "../sessions/sessions";
import { getAddOmh, useAddOmh } from "../sessions/addOmh";

const AlertIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
    <circle cx="12" cy="12" r="9" />
    <path d="M12 7.5v5.5" strokeLinecap="round" />
    <circle cx="12" cy="16.4" r="0.6" fill="currentColor" />
  </svg>
);

export function OmhNotice() {
  const ss = useSessions();
  const add = useAddOmh();
  useEffect(() => {
    if (ss.agents === null) void getSessions().loadAgents();
  }, [ss.agents]);
  if (!hermesOnly(ss.agents) || (add.hidden && !add.open)) return null;
  const running = add.phase === "running";
  const failed = add.phase === "failed";
  const a = getAddOmh();
  return (
    <div className="omh-note">
      <IconButton
        label={t("omh.icon")}
        className="omh-note-b"
        aria-haspopup="dialog"
        aria-expanded={add.open}
        onClick={() => a.setOpen(!add.open)}
        data-testid="omh-notice"
      >
        {running ? <Spinner size={13} label={t("gate.installing")} /> : <AlertIcon />}
      </IconButton>
      <Popover open={add.open} onClose={() => a.setOpen(false)} align="left" width="min(264px, calc(var(--side-w) - 16px))" label="oh-my-hermes" className="omh-pop">
        <div data-testid="omh-pop" data-phase={add.phase}>
          <b className="omh-pop-t">oh-my-hermes</b>
          <p className="omh-pop-p">{t("omh.pop.body")}</p>
          {running && (
            <div className="omh-pop-st" role="status" data-testid="omh-pop-running">
              <Spinner size={11} label={t("gate.installing")} />
              {t("omh.add.running")}
            </div>
          )}
          <InstallLog lines={running ? add.lines : []} compact testId="omh-pop-log" />
          {failed && add.error && (
            <p className="omh-pop-err" role="status" title={add.error} data-testid="omh-pop-error">
              {add.error}
            </p>
          )}
          <div className="omh-pop-a">
            <button type="button" className="omh-pop-go" disabled={running} onClick={() => void a.run()} data-testid="omh-pop-install">
              {failed ? t("gate.again") : t("gate.install")}
            </button>
            <button type="button" className="omh-pop-hide" disabled={running} onClick={() => a.hide()} data-testid="omh-pop-hide">
              {t("omh.pop.hide")}
            </button>
          </div>
        </div>
      </Popover>
    </div>
  );
}
