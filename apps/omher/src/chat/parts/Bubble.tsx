import { memo, type ReactNode } from "react";
import type { MessageItem } from "../../state/store";
import { Avatar, SourceIcon } from "../../ui";
import { Markdown } from "./Markdown";
import { MediaList } from "./Media";
import { splitMedia } from "./mediaLines";
import { SentFiles } from "./Attach";
import { SkillText } from "./Skills";

/** Messenger bubble, filled on both sides. Bot text renders markdown; user text stays plain. Files the bot
 * sent (`MEDIA:` lines) leave the text and show under it in the same column as the bubble, in order; while
 * streaming the lines are only hidden. Files the person sent sit under their own bubble, on the right.
 * Memoized: a store change elsewhere (a streamed token) must not re-render every bubble and its face. */
export const Bubble = memo(function Bubble({
  item,
  streaming,
  bot,
  face,
  faceEl,
}: {
  item: Pick<MessageItem, "kind" | "text" | "error" | "reply" | "files" | "sent">;
  streaming?: boolean;
  /** The bot whose face sits beside its bubble; `face` false keeps the indent without repeating it. */
  bot?: string;
  face?: boolean;
  /** Drawn in the face column instead of the bot's picture (a SESSIONS chat's agent mark). */
  faceEl?: ReactNode;
}) {
  if (item.kind === "user") {
    return (
      <div className="msg u" data-testid="bubble-user">
        {(item.text || !item.files?.length) && (
          <div className="b">
            <SkillText text={item.text} sent={item.sent} />
          </div>
        )}
        {item.files?.length ? <SentFiles files={item.files} /> : null}
        {item.reply && (
          <div className="msg-reply" data-testid="bubble-reply">
            Reply target <SourceIcon source={item.reply.source} size={11} /> {item.reply.label}
          </div>
        )}
        {item.error && <div className="msg-err">Not sent · {item.error}</div>}
      </div>
    );
  }
  const { text, paths } = splitMedia(item.text);
  return (
    <div className={`msg a${streaming ? " streaming" : ""}${bot ? " face" : ""}`} data-testid={streaming ? "bubble-streaming" : "bubble-bot"}>
      {bot &&
        (faceEl ? (
          <span className={`msg-face${face === false ? " blank" : ""}`}>{faceEl}</span>
        ) : (
          <Avatar bot={bot} size={28} className={`msg-face${face === false ? " blank" : ""}`} />
        ))}
      {/* one column beside the face: the caption, then the files under it, both on the bubble's left edge */}
      <div className="msg-col">
        {(text || streaming || paths.length === 0) && (
          <div className="b md">
            <Markdown text={text} />
          </div>
        )}
        {bot && !streaming && paths.length > 0 && <MediaList bot={bot} paths={paths} />}
      </div>
    </div>
  );
});
