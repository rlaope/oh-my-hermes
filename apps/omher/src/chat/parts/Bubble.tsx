import type { MessageItem } from "../../state/store";
import { Markdown } from "./Markdown";
import { MediaList } from "./Media";
import { splitMedia } from "./mediaLines";

/** Messenger bubble, filled on both sides. Bot text renders markdown; user text stays plain. Files the bot
 * sent (`MEDIA:` lines) leave the text and show below it, in order; while streaming the lines are only hidden. */
export function Bubble({
  item,
  streaming,
  bot,
}: {
  item: Pick<MessageItem, "kind" | "text" | "error">;
  streaming?: boolean;
  bot?: string;
}) {
  if (item.kind === "user") {
    return (
      <div className="msg u" data-testid="bubble-user">
        <div className="b">{item.text}</div>
        {item.error && <div className="msg-err">Not sent · {item.error}</div>}
      </div>
    );
  }
  const { text, paths } = splitMedia(item.text);
  return (
    <div className={`msg a${streaming ? " streaming" : ""}`} data-testid={streaming ? "bubble-streaming" : "bubble-bot"}>
      {(text || streaming || paths.length === 0) && (
        <div className="b md">
          <Markdown text={text} />
        </div>
      )}
      {bot && !streaming && paths.length > 0 && <MediaList bot={bot} paths={paths} />}
    </div>
  );
}
