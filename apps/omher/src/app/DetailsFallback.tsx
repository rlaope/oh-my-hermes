import type { Bot } from "../lib/protocol";
import { Avatar, CloseIcon, IconButton } from "../ui";
import { t } from "../i18n";

/** Plain Details panel used until a `detailsPanel` slot is registered. */
export function DetailsFallback({ bot, onClose }: { bot: Bot; onClose: () => void }) {
  return (
    <div className="details-in">
      <div className="details-h">
        {t("pn.details")}
        <IconButton label={t("pn.close")} onClick={onClose}>
          <CloseIcon />
        </IconButton>
      </div>
      <div className="details-id">
        <Avatar bot={bot.name} size={40} />
        <div>
          <b>{bot.display_name}</b>
          <span>
            {t("pn.profile", { name: bot.name })} · {bot.model}
          </span>
        </div>
      </div>
    </div>
  );
}
