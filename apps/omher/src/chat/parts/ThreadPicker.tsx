import type { Ref } from "react";
import { t } from "../../i18n";
import { NewThreadIcon } from "../../threads/NewThreadIcon";
import { THREAD_CMD } from "./threadCommand";

/** The `./` picker of a bot's composer: one built-in row, `./thread`, a new thread with this bot. Skills are `$name`
 *  and never listed here, so a skill named `thread` neither shadows nor repeats it. Keys stay in the textarea. */
export function ThreadPicker({ bot, active, onPick, popRef }: { bot: string; active: boolean; onPick: () => void; popRef: Ref<HTMLDivElement> }) {
  return (
    <div className="sk-pop" ref={popRef} role="listbox" aria-label={t("thread.cmdList")} data-testid="thread-picker">
      <div
        role="option"
        aria-selected={active}
        className={`sk-row sk-thread${active ? " on" : ""}`}
        data-testid="thread-option"
        onMouseDown={(e) => e.preventDefault()}
        onClick={onPick}
      >
        <NewThreadIcon size={14} />
        <code className="sk-pill">{THREAD_CMD}</code>
        <span className="sk-d">{t("thread.cmdHint", { name: bot })}</span>
      </div>
    </div>
  );
}
