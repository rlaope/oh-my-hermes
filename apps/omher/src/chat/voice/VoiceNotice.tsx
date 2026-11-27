// The first-use notice of voice (BOUNDARY rule 54): before anything is sent for a bot, where it goes and which
// provider the bot's config names, with Continue and Cancel. Continue is remembered on this computer (voice.ts).
// While it is open the keyboard stays in it (Tab and Shift+Tab go round its two buttons) and Escape is Cancel; the
// caller puts the keyboard back where the person needs it when it closes.
import type { KeyboardEvent } from "react";
import { t } from "../../i18n";

export function VoiceNotice({ testId, title, body, where, onContinue, onCancel }: {
  testId: string;
  title: string;
  body: string;
  where: string;
  onContinue: () => void;
  onCancel: () => void;
}) {
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.nativeEvent.isComposing) return;
    if (e.key === "Escape") {
      // the notice's own Escape: it never reaches the chat, where it would stop a running answer
      e.preventDefault();
      e.stopPropagation();
      onCancel();
      return;
    }
    if (e.key !== "Tab") return;
    const buttons = [...e.currentTarget.querySelectorAll<HTMLButtonElement>("button")];
    if (!buttons.length) return;
    const at = buttons.indexOf(document.activeElement as HTMLButtonElement);
    e.preventDefault();
    const next = at < 0 ? 0 : (at + (e.shiftKey ? buttons.length - 1 : 1)) % buttons.length;
    buttons[next].focus();
  };
  return (
    <div className="voice-notice" role="dialog" aria-modal="false" aria-label={title} data-testid={testId} onKeyDown={onKeyDown}>
      <b className="voice-notice-h">{title}</b>
      <p>
        {body} {where}
      </p>
      <p className="voice-keep">{t("voice.keepsNothing")}</p>
      <div className="voice-notice-row">
        <button type="button" className="voice-btn" onClick={onCancel} data-testid={`${testId}-cancel`}>
          {t("voice.cancel")}
        </button>
        <button type="button" className="voice-btn primary" onClick={onContinue} data-testid={`${testId}-continue`} autoFocus>
          {t("voice.continue")}
        </button>
      </div>
    </div>
  );
}
