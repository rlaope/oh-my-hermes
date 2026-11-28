import { useEffect, useState } from "react";
import { waitingIds, type Chat } from "../../state/store";
import { t } from "../../i18n";

/** How long Clear waits for its second press before it goes back. */
const CONFIRM_MS = 4000;

/** One quiet line above the composer while messages wait in omher (steer queue): how many, Pause / Resume, and
 *  Clear. Paused, nothing waiting goes out on its own (a row's own ↵ still sends that one). Clear deletes them all
 *  on a second press within a few seconds; Escape, leaving the button or the wait puts it back. */
export function QueueBar({ chat, onPause, onClear }: { chat: Chat | undefined; onPause: (paused: boolean) => void; onClear: () => void }) {
  const n = waitingIds(chat).length;
  const paused = !!chat?.queuePaused;
  const [confirm, setConfirm] = useState(false);
  useEffect(() => {
    if (!confirm) return;
    const timer = setTimeout(() => setConfirm(false), CONFIRM_MS);
    return () => clearTimeout(timer);
  }, [confirm]);
  useEffect(() => {
    if (!n) setConfirm(false);
  }, [n]);
  if (!n) return null;
  const count = paused ? t(n === 1 ? "sq.pausedOne" : "sq.paused", { n }) : t(n === 1 ? "sq.waitingOne" : "sq.waiting", { n });
  return (
    <div className={`sq-bar${paused ? " paused" : ""}`} role="group" aria-label={t("sq.bar")} data-testid="queue-bar" data-paused={paused || undefined}>
      <span className="sq-bar-n" aria-live="polite" data-testid="queue-bar-count">
        {count}
      </span>
      <button
        type="button"
        className="sq-bar-b"
        title={paused ? t("sq.resumeTip") : t("sq.pauseTip")}
        onClick={() => {
          setConfirm(false);
          onPause(!paused);
        }}
        data-testid="queue-pause"
      >
        {paused ? t("sq.resume") : t("sq.pause")}
      </button>
      <button
        type="button"
        className={`sq-bar-b sq-bar-clear${confirm ? " confirm" : ""}`}
        title={confirm ? t("sq.clearConfirmTip") : t("sq.clearTip")}
        onClick={() => {
          if (!confirm) return setConfirm(true);
          setConfirm(false);
          onClear();
        }}
        onBlur={() => setConfirm(false)}
        onKeyDown={(e) => {
          // Escape takes back the confirm here, before it could stop the running answer
          if (e.key !== "Escape" || !confirm) return;
          e.preventDefault();
          e.stopPropagation();
          setConfirm(false);
        }}
        data-testid="queue-clear"
        data-confirm={confirm || undefined}
      >
        {confirm ? t("sq.clearConfirm", { n }) : t("sq.clear")}
      </button>
    </div>
  );
}
