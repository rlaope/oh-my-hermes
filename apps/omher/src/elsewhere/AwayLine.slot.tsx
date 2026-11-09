// Timeline: what this bot last said in a thread elsewhere (Slack, Discord, cron), as an ordinary bot
// bubble with one link back to the thread at the end. omher never writes to that thread.
import type { SlotProps } from "../features";
import { openExternal } from "../lib/openExternal";
import { Avatar, SourceIcon, Spinner } from "../ui";
import { sourceName, workingFor } from "./format";
import { useNow } from "./useNow";
import "./elsewhere.css";

export const slot = "elsewhereLine";

export default function AwayLine({ bot, item, face }: SlotProps["elsewhereLine"]) {
  const a = item.away;
  const now = useNow(a.running);
  const src = sourceName(a.source);
  const title = a.label?.trim() || a.title?.trim() || `${src} session`;
  // cron has no thread to open: name the job instead ("Cron · superagent-observe")
  const job = a.source === "cron" ? (a.label || a.title || "").split(" · ")[0].trim() : "";
  const where = a.place ? `${src} ${a.place}` : job ? `${src} · ${job}` : src;
  const text = a.last_reply?.trim() || title;
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
      <SourceIcon source={a.source} size={12} />
      <span className="ew-lt">{where}</span>
    </a>
  ) : (
    <span className="ew-where">
      <SourceIcon source={a.source} size={12} />
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
            <Spinner size={10} label={`${src} session working`} /> working · {workingFor(a.started_at, now)}
          </span>
        )}
      </div>
    </div>
  );
}
