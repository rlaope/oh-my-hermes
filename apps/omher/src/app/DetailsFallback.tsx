import type { Bot } from "../lib/protocol";
import { Avatar, CloseIcon, IconButton } from "../ui";

/** Plain Details panel used until a `detailsPanel` slot is registered. */
export function DetailsFallback({ bot, onClose }: { bot: Bot; onClose: () => void }) {
  return (
    <div className="details-in">
      <div className="details-h">
        Details
        <IconButton label="Close details" onClick={onClose}>
          <CloseIcon />
        </IconButton>
      </div>
      <div className="details-id">
        <Avatar bot={bot.name} size={40} />
        <div>
          <b>{bot.display_name}</b>
          <span>
            Hermes profile · {bot.name} · {bot.model}
          </span>
        </div>
      </div>
    </div>
  );
}
