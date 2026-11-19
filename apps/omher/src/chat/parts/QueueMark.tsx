import { t } from "../../i18n";

/** steer queue sessions: actions that are off, each with its one-line reason (a SESSIONS agent without its own
 *  steer; a message already handed to the agent). */
export type QueueOffReasons = Partial<Record<QueueChoice, string>>;

export type QueueChoice = "now" | "steer" | "edit" | "delete" | "send";

/** The buttons before a held message (steer queue), with no menu between the person and the action (khope: a menu
 *  for this is one step too many).
 *  - ↵ sends it now: Steer, into the running answer without stopping it; where the agent has no steer of its own,
 *    Send now (stop the answer, send this one first). A steer whose answer never came: send it again as a new one.
 *  - ↓ puts it back in the message box, to fix or add to.
 *  - × (shown on hover or focus) drops it.
 *  An action that is off says why in its tooltip and does nothing. */
export function QueueMark({
  onPick,
  busy = false,
  off = {},
  unknown = false,
}: {
  onPick: (c: QueueChoice) => void;
  busy?: boolean;
  off?: QueueOffReasons;
  /** A steer whose answer never came (it may be in the answer already): only Send or Delete. */
  unknown?: boolean;
}) {
  const go: QueueChoice = unknown ? "send" : off.steer ? "now" : "steer";
  const goTip = unknown ? t("sq.sendTip") : go === "steer" ? t("sq.steerTip") : t("sq.sendNowTip");
  const button = (c: QueueChoice, glyph: string, label: string, tip: string, testId: string, cls = "") => (
    <button
      type="button"
      className={`sq-mark${cls}${off[c] ? " off" : ""}`}
      aria-label={label}
      title={off[c] ?? tip}
      aria-disabled={off[c] ? true : undefined}
      disabled={busy}
      onClick={() => {
        if (!off[c]) onPick(c);
      }}
      data-testid={testId}
      data-choice={c}
    >
      {glyph}
    </button>
  );
  return (
    // × on the outside: hidden at rest, it leaves no gap between ↵ ↓ and the bubble
    <span className="sq-w" data-testid="queue-acts">
      {button("delete", "×", t("sq.delete"), t("sq.deleteTip"), "queue-delete", " sq-x")}
      {button(go, "↵", unknown ? t("sq.send") : go === "steer" ? t("sq.steer") : t("sq.sendNow"), goTip, "queue-mark")}
      {!unknown && button("edit", "↓", t("sq.edit"), t("sq.editTip"), "queue-edit")}
    </span>
  );
}
