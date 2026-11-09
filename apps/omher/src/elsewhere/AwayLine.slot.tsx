// Timeline: what this bot last said in a thread elsewhere (Slack, Discord, cron), as an ordinary bot
// bubble with one link back to the thread at the end. omher never writes to that thread.
import { memo } from "react";
import type { SlotProps } from "../features";
import { openExternal } from "../lib/openExternal";
import { Avatar, LiveRing, SourceIcon } from "../ui";
import { sourceName, workingFor } from "./format";
import { useNow } from "./useNow";
import "./elsewhere.css";

export const slot = "elsewhereLine";

// The slot registry takes a plain function (memo() returns an object), so the default export stays a function
// and the memoized body does the work: a streamed token must not re-render every away bubble and its face.
export default function AwayLine(props: SlotProps["elsewhereLine"]) {
  return <AwayBubble {...props} />;
}

const AwayBubble = memo(function AwayBubble({ bot, item, face }: SlotProps["elsewhereLine"]) {
  const a = item.away;
  const now = useNow(a.running);
  const src = sourceName(a.source);
  const title = a.label?.trim() || a.title?.trim() || `${src} session`;
  // cron has no thread to open: name the job instead ("Cron · superagent-observe")
  const job = a.source === "cron" ? (a.label || a.title || "").split(" · ")[0].trim() : "";
  const where = a.place ? `${src} ${a.place}` : job ? `${src} · ${job}` : src;
  const text = a.last_reply?.trim() || title;
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
      <div className="b">
        <span data-testid="away-text">{text}</span> {link}
        {a.running && (
          <span className="ew-working" data-testid="away-time">
            working · {workingFor(a.started_at, now)}
          </span>
        )}
      </div>
    </div>
  );
});
