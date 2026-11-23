// The bot page's line for a bot template that waits to be applied (BOUNDARY rule 44): New bot made the bot, but the bot
// could not see the template skill yet. Apply template sends the same one message once rule 19's skill read shows the
// skill; Forget drops the reminder. Nothing is sent before the person presses Apply template.
import { useState } from "react";
import type { Bot } from "../lib/protocol";
import { t, tx } from "../i18n";
import { applyTemplate, clearPendingTemplate, pendingTemplate } from "./pending";

const UPDATE_CMD = "omh update";

export function PendingTemplate({ bot }: { bot: Bot }) {
  const [template, setTemplate] = useState(() => pendingTemplate(bot.name));
  const [still, setStill] = useState(false);
  if (!template || bot.host) return null;
  const apply = async () => {
    if (await applyTemplate(bot.name, template)) setTemplate(null);
    else setStill(true);
  };
  return (
    <div className="st-grp bp-grp bp-tpl" data-testid="bp-template">
      <div className="bp-tpl-line">
        {still
          ? tx("ab.stillNoSkill", { name: bot.name, cmd: <code>{UPDATE_CMD}</code> })
          : tx("bp.templateWaits", { id: <code>{template}</code>, cmd: <code>{UPDATE_CMD}</code> })}
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
        <button type="button" className="st-btn" data-testid="bp-template-apply" onClick={() => void apply()}>
          {t("ab.apply")}
        </button>
      </div>
    </div>
  );
}
