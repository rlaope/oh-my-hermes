import { useEffect, useState } from "react";
import { t } from "../i18n";

/** "Run now" for an automation: a small quiet link at the end of its buttons, not a button that asks to be pressed
 *  (khope: it looked like something you must click). A click only asks; the run is one more step (Run · Cancel),
 *  since it fires the job outside its schedule. */
export function RunOnce({ label, onRun, resetKey, testId }: { label: string; onRun: () => void; resetKey?: string; testId: string }) {
  const [asking, setAsking] = useState(false);
  useEffect(() => setAsking(false), [resetKey]);
  if (!asking)
    return (
      <button type="button" className="pg-link run-once" onClick={() => setAsking(true)} data-testid={testId}>
        {label}
      </button>
    );
  return (
    <span className="run-once-ask" role="group" aria-label={t("auto.runAsk")} data-testid={`${testId}-ask`}>
      <span className="run-once-q">{t("auto.runAsk")}</span>
      <button
        type="button"
        className="pg-btn pri"
        onClick={() => {
          setAsking(false);
          onRun();
        }}
        data-testid={`${testId}-confirm`}
      >
        {t("auto.runGo")}
      </button>
      <button type="button" className="pg-link" onClick={() => setAsking(false)} data-testid={`${testId}-cancel`}>
        {t("page.cancel")}
      </button>
    </span>
  );
}
