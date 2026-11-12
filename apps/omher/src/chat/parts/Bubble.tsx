import { memo, type ReactNode } from "react";
import type { MessageItem } from "../../state/store";
import { Avatar, LiveRing, SourceIcon } from "../../ui";
import { Markdown } from "./Markdown";
import { MediaList } from "./Media";
import { splitMedia } from "./mediaLines";
import { SentFiles } from "./Attach";
import { SkillText } from "./Skills";
import { t } from "../../i18n";

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
  live,
}: {
  item: Pick<MessageItem, "kind" | "text" | "error" | "reply" | "files" | "skills" | "wait">;
  streaming?: boolean;
  /** The bot whose face sits beside its bubble; `face` false keeps the indent without repeating it. */
  bot?: string;
  face?: boolean;
  /** Drawn in the face column instead of the bot's picture (a SESSIONS chat's agent mark). */
  faceEl?: ReactNode;
  /** The answer being written: its face wears the live ring (the bot is still working). */
  live?: boolean;
}) {
  if (item.kind === "user") {
    return (
      <div className={`msg u${item.wait ? ` ${item.wait}` : ""}`} data-testid="bubble-user" data-wait={item.wait}>
        {(item.text || !item.files?.length) && (
          <div className="b">
            <SkillText text={item.text} skills={item.skills} />
          </div>
        )}
        {item.files?.length ? <SentFiles files={item.files} /> : null}
        {item.reply && (
          <div className="msg-reply" data-testid="bubble-reply">
            {t("bub.replyTarget")} <SourceIcon source={item.reply.source} size={11} /> {item.reply.label}
          </div>
        )}
        {item.wait === "queued" && (
          <div className="msg-wait" data-testid="bubble-queued">
            {t("ctl.queued")}
          </div>
        )}
        {item.wait === "dropped" && (
          <div className="msg-wait" data-testid="bubble-dropped">
            {t("ctl.dropped")}
          </div>
        )}
        {item.error && <div className="msg-err">{t("bub.notSent", { error: item.error })}</div>}
      </div>
    );
  }
  const { text, paths } = splitMedia(item.text);
  const faceNode =
    bot &&
    (faceEl ? (
      <span className={`msg-face${face === false ? " blank" : ""}`}>{faceEl}</span>
    ) : (
      <Avatar bot={bot} size={28} className={`msg-face${face === false ? " blank" : ""}`} />
    ));
  return (
    <div className={`msg a${streaming ? " streaming" : ""}${bot ? " face" : ""}`} data-testid={streaming ? "bubble-streaming" : "bubble-bot"}>
      {bot && live && face !== false ? (
        <LiveRing on size={28} gap={3} testId="face-ring" seed={bot}>
          {faceNode}
        </LiveRing>
      ) : (
        faceNode
      )}
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
