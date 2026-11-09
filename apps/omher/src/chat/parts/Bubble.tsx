import { memo, type ReactNode } from "react";
import type { MessageItem } from "../../state/store";
import { Avatar, SourceIcon } from "../../ui";
import { Markdown } from "./Markdown";

/** Messenger bubble, filled on both sides. Bot text renders markdown; user text stays plain. Memoized: a
 * store change elsewhere (a streamed token) must not re-render every bubble and its face. */
export const Bubble = memo(function Bubble({
  item,
  streaming,
  bot,
  face,
  faceEl,
}: {
  item: Pick<MessageItem, "kind" | "text" | "error" | "reply">;
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
        <div className="b">{item.text}</div>
        {item.reply && (
          <div className="msg-reply" data-testid="bubble-reply">
            Reply target <SourceIcon source={item.reply.source} size={11} /> {item.reply.label}
          </div>
        )}
        {item.error && <div className="msg-err">Not sent · {item.error}</div>}
      </div>
    );
  }
  return (
    <div className={`msg a${streaming ? " streaming" : ""}${bot ? " face" : ""}`} data-testid={streaming ? "bubble-streaming" : "bubble-bot"}>
      {bot &&
        (faceEl ? (
          <span className={`msg-face${face === false ? " blank" : ""}`}>{faceEl}</span>
        ) : (
          <Avatar bot={bot} size={28} className={`msg-face${face === false ? " blank" : ""}`} />
        ))}
      <div className="b md">
        <Markdown text={item.text} />
      </div>
    </div>
  );
});
