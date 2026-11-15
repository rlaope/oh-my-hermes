import { memo, type ReactNode } from "react";
import type { MessageItem } from "../../state/store";
import { Avatar, LiveRing, SourceIcon } from "../../ui";
import { Markdown } from "./Markdown";
import { MediaList } from "./Media";
import { splitMedia } from "./mediaLines";
import { SentFiles } from "./Attach";
import { SkillText } from "./Skills";
import { CopyButton } from "./Copy";
import { PeerChips } from "../../peers/PeerChip";
import { peerDraftsAllowed, stripPeerDrafts } from "../../peers/draft";
import { AgentChips } from "./AgentChip";
import { draftsAllowed, stripDrafts } from "./agentDraft";
import { t } from "../../i18n";
import { QueueMark, type QueueChoice, type QueueOffReasons } from "./QueueMark";
import type { Quote } from "./answers";

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
  onEdit,
  editKeepsFiles,
  from,
  onQueue,
  queueBusy,
  queueOff,
  steeredTo,
  quote,
  onQuote,
}: {
  item: Pick<MessageItem, "kind" | "text" | "error" | "reply" | "files" | "skills" | "wait" | "held" | "steered" | "steerUnknown" | "steerUnused">;
  streaming?: boolean;
  /** The bot whose face sits beside its bubble; `face` false keeps the indent without repeating it. */
  bot?: string;
  face?: boolean;
  /** Drawn in the face column instead of the bot's picture (a SESSIONS chat's agent mark). */
  faceEl?: ReactNode;
  /** The answer being written: its face wears the live ring (the bot is still working). */
  live?: boolean;
  /** A user bubble the agent can take back (a SESSIONS chat's last message): its Edit control. */
  onEdit?: () => void;
  /** The turn Edit takes back changed files: a quiet line beside it says they stay as they are. */
  editKeepsFiles?: boolean;
  /** A user bubble someone else sent (a parent agent, in a read-only agent-to-agent chat): their small mark and name
   *  above it. */
  from?: ReactNode;
  /** A held message (steer queue): its ↵ mark's menu. */
  onQueue?: (c: QueueChoice) => void;
  /** Its steer is on the way: the mark waits. */
  queueBusy?: boolean;
  /** The bot's name a steered message went to, for its line. */
  steeredTo?: string;
  /** Menu items that are off, with their reasons (a SESSIONS chat's agent). */
  queueOff?: QueueOffReasons;
  /** A bot answer: the message of the person's it replies to, when that is not plain from where it sits; a click
   *  scrolls to that message. */
  quote?: Quote | null;
  onQuote?: (id: string) => void;
}) {
  if (item.kind === "user") {
    const held = !!item.held;
    // a SESSIONS chat's waiting message carries the mark too (held by omher, or already with the agent)
    const marked = (held || item.wait === "queued" || !!item.steerUnknown) && !!onQueue;
    return (
      <div
        className={`msg u${item.wait ? ` ${item.wait}` : ""}${held ? " held" : ""}`}
        data-testid="bubble-user"
        data-wait={item.wait}
        data-held={held || undefined}
        data-steered={item.steered || undefined}
      >
        {from && (
          <div className="msg-from" data-testid="bubble-from">
            {from}
          </div>
        )}
        {(item.text || !item.files?.length) &&
          (marked && onQueue ? (
            // a held message: its ↵ mark before the bubble, on the bubble's first line
            <div className="msg-line">
              <QueueMark onPick={onQueue} busy={queueBusy} off={queueOff} unknown={!!item.steerUnknown} />
              <div className="b">
                <SkillText text={item.text} skills={item.skills} />
              </div>
            </div>
          ) : (
            <div className="b">
              <SkillText text={item.text} skills={item.skills} />
            </div>
          ))}
        {item.files?.length ? <SentFiles files={item.files} /> : null}
        {item.reply && (
          <div className="msg-reply" data-testid="bubble-reply">
            {t("bub.replyTarget")} <SourceIcon source={item.reply.source} size={11} /> {item.reply.label}
          </div>
        )}
        {item.wait === "queued" && !item.steered && (
          <div className="msg-wait" data-testid="bubble-queued">
            {t("ctl.queued")}
          </div>
        )}
        {held && item.wait !== "queued" && (
          <div className="msg-wait" data-testid="bubble-held">
            {queueBusy ? t("sq.steering") : t("ctl.queued")}
          </div>
        )}
        {item.steered && (
          <div className="msg-wait msg-steered" data-testid="bubble-steered">
            {t("sq.steered", { bot: steeredTo ?? "" })}
          </div>
        )}
        {item.steerUnknown && (
          <div className="msg-wait" data-testid="bubble-steer-unknown">
            {item.steerUnused ? t("sq.unused") : t("sq.unknown")}
          </div>
        )}
        {item.wait === "dropped" && (
          <div className="msg-wait" data-testid="bubble-dropped">
            {t("ctl.dropped")}
          </div>
        )}
        {item.error && <div className="msg-err">{t("bub.notSent", { error: item.error })}</div>}
        {onEdit && (
          <button type="button" className="msg-edit" onClick={onEdit} title={t("rw.tip")} data-testid="bubble-edit">
            {t("rw.edit")}
          </button>
        )}
        {onEdit && editKeepsFiles && (
          <div className="msg-edit-note" data-testid="bubble-edit-note">
            {t("rw.filesStay")}
          </div>
        )}
      </div>
    );
  }
  const { text, paths } = splitMedia(item.text);
  // a draft block shows only as its chip under the reply (where the chip can show); the chips still read `text`
  const shown = bot ? draftless(text, bot, !!streaming) : text;
  const faceNode =
    bot &&
    (faceEl ? (
      <span className={`msg-face${face === false ? " blank" : ""}`}>{faceEl}</span>
    ) : (
      <Avatar bot={bot} size={28} className={`msg-face${face === false ? " blank" : ""}`} />
    ));
  const body = (
    <div className={`msg a${streaming ? " streaming" : ""}${bot ? " face" : ""}`} data-testid={streaming ? "bubble-streaming" : "bubble-bot"}>
      {bot && live && face !== false ? (
        <LiveRing on size={28} gap={3} testId="face-ring" seed={bot}>
          {faceNode}
        </LiveRing>
      ) : (
        faceNode
      )}
      {/* one column beside the face: the caption, then the files under it, both on the bubble's left edge; a reply that
          was only a draft block shows its chip alone */}
      <div className="msg-col">
        {(shown || streaming || (paths.length === 0 && shown === text)) && (
          <div className="b md">
            <Markdown text={shown} />
            {/* copy the answer: beside the bubble's last line, on hover; it takes no room */}
            {!streaming && shown.trim() && <CopyButton className="msg-copy" text={() => shown} testId="copy-answer" />}
          </div>
        )}
        {bot && !streaming && paths.length > 0 && <MediaList bot={bot} paths={paths} />}
        {/* an `omher-peer` draft in a finished reply: its Connect over SSH chip (a bot's main chat only) */}
        {bot && !streaming && <PeerChips chatKey={bot} text={text} />}
        {/* an `omher-agent` draft in a finished reply: its Add agent chip (main and folder chats only; `bot` is the chat) */}
        {bot && !streaming && <AgentChips chatKey={bot} text={text} />}
      </div>
    </div>
  );
  if (!quote) return body;
  // what this answer replies to, above it in the bubbles' column (the face stays beside the bubble): each message's
  // first line, a click brings that message into view
  return (
    <>
      <div className={`msg-quotes${bot ? " face" : ""}`} data-testid="bubble-quote">
        <span className="msg-quote-h" data-testid="bubble-quote-head">
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M9 14 4 9l5-5" />
            <path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11" />
          </svg>
          {quote.lines.length + quote.more === 1 ? t("bub.repliedTo1") : t("bub.repliedTo", { n: quote.lines.length + quote.more })}
        </span>
        {quote.more > 0 && <span className="msg-quote-n">{t("bub.quoteMore", { n: quote.more })}</span>}
        {quote.lines.map((l) => (
          <button key={l.id} type="button" className="msg-quote" onClick={() => onQuote?.(l.id)} title={t("bub.quoteTip")} data-testid="bubble-quote-line">
            {l.text}
          </button>
        ))}
      </div>
      {body}
    </>
  );
});

/** The reply text the bubble shows: without the omher-peer / omher-agent blocks of a chat that turns them into chips. */
function draftless(text: string, chatKey: string, streaming: boolean): string {
  let out = text;
  if (peerDraftsAllowed(chatKey)) out = stripPeerDrafts(out, streaming);
  if (draftsAllowed(chatKey)) out = stripDrafts(out, streaming);
  return out;
}
