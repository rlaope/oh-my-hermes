// The bot page's line for a bot template that waits to be applied (BOUNDARY rule 44): New bot made the bot, but the bot
// could not see the template skill yet. Apply template sends the same one message once rule 19's skill read shows the
// skill; Forget drops the reminder. Nothing is sent before the person presses Apply template.
import { useRef, useState } from "react";
import type { Bot } from "../lib/protocol";
import { t, tx } from "../i18n";
import { applyTemplate, clearPendingTemplate, pendingTemplate } from "./pending";
import { skillSyncCmd } from "./templates";

export function PendingTemplate({ bot }: { bot: Bot }) {
  const [template, setTemplate] = useState(() => pendingTemplate(bot.name));
  const [still, setStill] = useState(false);
  // one apply at a time: a double click sends one message
  const [sending, setSending] = useState(false);
  const inFlight = useRef(false);
  if (!template || bot.host) return null;
  const apply = async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    setSending(true);
    try {
      if (await applyTemplate(bot.name, template)) setTemplate(null);
      else setStill(true);
    } finally {
      inFlight.current = false;
      setSending(false);
    }
  };
  return (
    <div className="st-grp bp-grp bp-tpl" data-testid="bp-template">
      <div className="bp-tpl-line">
        {still
          ? tx("ab.stillNoSkill", { name: bot.name, cmd: <code>{skillSyncCmd(bot.name)}</code> })
          : tx("bp.templateWaits", { id: <code>{template}</code>, cmd: <code>{skillSyncCmd(bot.name)}</code> })}
      </div>
      <div className="bp-tpl-actions">
        <button
          type="button"
          className="st-btn"
          data-testid="bp-template-forget"
          onClick={() => (clearPendingTemplate(bot.name), setTemplate(null))}
        >
          {t("bp.templateForget")}
        </button>
        <button type="button" className="st-btn" data-testid="bp-template-apply" disabled={sending} onClick={() => void apply()}>
          {t("ab.apply")}
        </button>
      </div>
    </div>
  );
}
