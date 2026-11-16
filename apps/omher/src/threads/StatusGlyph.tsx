// The small mark at the start of a thread row: a turning arc (running), a slow-pulsing amber dot (needs you), a
// check that pops once and then stays still (done), an x (failed or stopped), a faint hollow dot (idle). Static under
// prefers-reduced-motion (threads.css).
import type { ThreadStatus } from "./status";
import { t } from "../i18n";

const LABEL = {
  running: "thread.st.running",
  needs_you: "thread.st.needs",
  done: "thread.st.done",
  failed: "thread.st.failed",
  idle: "thread.st.idle",
} as const;

export function StatusGlyph({ status }: { status: ThreadStatus }) {
  const label = t(LABEL[status]);
  return (
    <span className={`th-g th-g-${status}`} data-testid="thread-glyph" data-state={status} role="img" aria-label={label} title={label}>
      {status === "running" && (
        <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true">
          <circle cx="5" cy="5" r="3.8" fill="none" stroke="currentColor" strokeOpacity="0.25" strokeWidth="1.5" />
          <path d="M5 1.2a3.8 3.8 0 0 1 3.8 3.8" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        </svg>
      )}
      {status === "needs_you" && <span className="th-dot" />}
      {/* idle: a faint hollow dot, so the branch ends on something */}
      {status === "idle" && <span className="th-ring" />}
      {status === "done" && (
        <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true">
          <path d="M2 5.3 4.1 7.3 8 2.8" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      )}
      {status === "failed" && (
        <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true">
          <path d="M2.8 2.8 7.2 7.2M7.2 2.8 2.8 7.2" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
        </svg>
      )}
    </span>
  );
}
