// Timeline: what this bot last said in a thread elsewhere (Slack, Discord, cron), as an ordinary bot
// bubble with one link back to the thread at the end. omher never writes to that thread: "Reply there"
// only puts a reference to it in the composer, and the bot posts with its own tools if asked.
import { memo, useState } from "react";
import type { SlotProps } from "../features";
import { openExternal } from "../lib/openExternal";
import { getStore, replyChipFor } from "../state/store";
import { Avatar, LiveRing, Popover, SourceIcon } from "../ui";
import { sourceName, workingFor } from "./format";
import { useNow } from "./useNow";
import "./elsewhere.css";

export const slot = "elsewhereLine";

const ReplyIcon = () => (
  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
    <path d="M9 14 4 9l5-5" />
    <path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11" />
  </svg>
);
const MoreIcon = () => (
  <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
    <circle cx="5" cy="12" r="1.8" />
    <circle cx="12" cy="12" r="1.8" />
    <circle cx="19" cy="12" r="1.8" />
  </svg>
);

// The slot registry takes a plain function (memo() returns an object), so the default export stays a function
// and the memoized body does the work: a streamed token must not re-render every away bubble and its face.
export default function AwayLine(props: SlotProps["elsewhereLine"]) {
  return <AwayBubble {...props} />;
}

const AwayBubble = memo(function AwayBubble({ bot, item, face }: SlotProps["elsewhereLine"]) {
  const [menu, setMenu] = useState(false);
  const a = item.away;
  const now = useNow(a.running);
  const src = sourceName(a.source);
  const title = a.label?.trim() || a.title?.trim() || `${src} session`;
  // cron has no thread to open: name the job instead ("Cron · superagent-observe")
  const job = a.source === "cron" ? (a.label || a.title || "").split(" · ")[0].trim() : "";
  const where = a.place ? `${src} ${a.place}` : job ? `${src} · ${job}` : src;
  const text = a.last_reply?.trim() || title;
  const chip = replyChipFor(a);
  const replyThere = () => {
    setMenu(false);
    if (chip) getStore().actions.setReplyTo(chip, bot);
  };
  // still working there: the same live ring as the sidebar, around the place's mark
  const mark = (
    <LiveRing on={a.running} size={12} gap={4} label={`${src} session working`} testId="away-ring" seed={a.id}>
      <SourceIcon source={a.source} size={12} />
    </LiveRing>
  );
  const link = a.url ? (
    <a
      className="ew-link"
      href={a.url}
      title={`Open in ${src}`}
      data-testid="away-link"
      onClick={(e) => {
        e.preventDefault();
        void openExternal(a.url!);
      }}
    >
      {mark}
      <span className="ew-lt">{where}</span>
    </a>
  ) : (
    <span className="ew-where">
      {mark}
      <span className="ew-lt">{where}</span>
    </span>
  );
  return (
    <div className="msg a face ew-msg" data-testid="away" data-source={a.source} data-session={a.id}>
      <Avatar bot={bot} size={28} className={`msg-face${face === false ? " blank" : ""}`} />
      <div className="ew-row">
        <div className="b">
          <span data-testid="away-text">{text}</span> {link}
          {a.running && (
            <span className="ew-working" data-testid="away-time">
              working · {workingFor(a.started_at, now)}
            </span>
          )}
        </div>
        {(chip || a.url) && (
          <div className={`ew-acts${menu ? " on" : ""}`} data-testid="away-actions">
            {chip && (
              <button
                type="button"
                className="ew-act"
                onClick={replyThere}
                data-testid="reply-there"
                title="Point your next message at this thread"
              >
                <ReplyIcon /> Reply there
              </button>
            )}
            <span className="ew-menu-w">
              <button
                type="button"
                className="ew-act ew-act-ic"
                aria-label="More"
                aria-expanded={menu}
                title="More"
                onClick={() => setMenu((v) => !v)}
                data-testid="away-more"
              >
                <MoreIcon />
              </button>
              <Popover open={menu} onClose={() => setMenu(false)} align="right" width={176} label="Thread actions" className="ew-menu">
                {chip && (
                  <button type="button" className="ew-mi" onClick={replyThere} data-testid="menu-reply-there">
                    <ReplyIcon /> Reply there
                  </button>
                )}
                {a.url && (
                  <button
                    type="button"
                    className="ew-mi"
                    onClick={() => {
                      setMenu(false);
                      void openExternal(a.url!);
                    }}
                    data-testid="menu-open"
                  >
                    <SourceIcon source={a.source} size={12} /> Open in {src}
                  </button>
                )}
              </Popover>
            </span>
          </div>
        )}
      </div>
    </div>
  );
});
