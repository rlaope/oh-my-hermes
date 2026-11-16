// A thread's live state, as its sidebar row shows it. This function alone decides it; the row, its glyph and the
// tests read nothing else.
//
//   needs_you  an approval or question of the thread is waiting on the person (wins over running)
//   running    a turn runs now
//   failed     the last turn ended in an error, or the person stopped it
//   done       the last turn ended normally
//   idle       nothing ran since the app started (a thread listed from Hermes, or a new empty one)

export type ThreadStatus = "running" | "needs_you" | "done" | "failed" | "idle";

export const THREAD_STATUSES: readonly ThreadStatus[] = ["running", "needs_you", "done", "failed", "idle"];

export interface ThreadFacts {
  /** A turn runs now (the chat's live turn, or the bridge's list said so before the chat was read). */
  running: boolean;
  /** Approvals and questions of this thread still waiting on the person. */
  asks: number;
  /** How the last finished turn ended; null when none has finished in view. */
  lastOutcome: "done" | "interrupted" | "ended" | "error" | null;
}

export function threadStatus(f: ThreadFacts): ThreadStatus {
  if (f.asks > 0) return "needs_you";
  if (f.running) return "running";
  if (f.lastOutcome === "error" || f.lastOutcome === "interrupted") return "failed";
  if (f.lastOutcome === "done" || f.lastOutcome === "ended") return "done";
  return "idle";
}
