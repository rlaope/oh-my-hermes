// Timeline: one line per session this bot runs elsewhere (Slack, Discord, cron). It links to the thread in
// its own app; omher does not replay that thread's messages here and never writes to it.
import type { SlotProps } from "../features";
import { openExternal } from "../lib/openExternal";
import { Spinner } from "../ui";
import { awayTime, sourceName } from "./format";
import { useNow } from "./useNow";
import "./elsewhere.css";

export const slot = "elsewhereLine";

export default function AwayLine({ item }: SlotProps["elsewhereLine"]) {
  const a = item.away;
  const now = useNow(a.running);
  const src = sourceName(a.source);
  const title = a.label?.trim() || a.title?.trim() || `${src} session`;
  const where = a.place ? `${src} ${a.place}` : src;
  const body = (
    <>
      <span className="ew-src">
        <i className={`src-sq src-${a.source}`} />
        {where}
      </span>
      <span className="ew-ttl">{title}</span>
      {a.running && <Spinner size={11} label={`${src} session working`} />}
      <span className="ew-tm" data-testid="away-time">
        {awayTime(a, now)}
      </span>
      {a.url && (
        <span className="ew-go" aria-hidden="true">
          ↗
        </span>
      )}
    </>
  );
  return (
    <div className="ew-away" data-testid="away" data-source={a.source} data-session={a.id}>
      {a.url ? (
        <a
          className="ew-away-h link"
          href={a.url}
          title={`Open in ${src}`}
          data-testid="away-link"
          onClick={(e) => {
            e.preventDefault();
            void openExternal(a.url!);
          }}
        >
          {body}
        </a>
      ) : (
        <div className="ew-away-h">{body}</div>
      )}
    </div>
  );
}
