import { Fragment, useLayoutEffect, useRef, type ReactNode } from "react";
import type { Bot } from "../../lib/protocol";
import { selectTimeline, useStore, type TimelineItem } from "../../state/store";
import { slots } from "../../features";
import { dayLabel, hhmm, sameDay } from "../../app/time";
import { Bubble } from "./Bubble";
import { TypingRow, awaitingFirstToken } from "./Typing";
import { ActivityFallback, CardFallback, ElsewhereFallback, RoutineFallback } from "./fallbacks";

/** A time label goes in when the day changes, or after a quiet gap within the same day. */
const GAP = 30 * 60;

function divider(prev: TimelineItem | undefined, cur: TimelineItem): string | null {
  if (!prev || !sameDay(prev.ts, cur.ts)) return dayLabel(cur.ts);
  if (cur.ts - prev.ts > GAP) return hhmm(new Date(cur.ts * 1000));
  return null;
}

export function Timeline({ bot }: { bot: Bot }) {
  const s = useStore();
  const items = selectTimeline(s, bot.name);
  const chat = s.chats[bot.name];
  const streaming = chat?.turn?.streaming ?? "";
  const typing = awaitingFirstToken(chat);
  const ref = useRef<HTMLDivElement>(null);
  const pinned = useRef(true);
  const lastBot = useRef<string | null>(null);

  // Stick to the bottom unless the person scrolled up; jump to the bottom on bot switch.
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (lastBot.current !== bot.name || pinned.current) el.scrollTop = el.scrollHeight;
    lastBot.current = bot.name;
  }, [bot.name, items, streaming, typing]);

  const render = (it: TimelineItem): ReactNode => {
    switch (it.kind) {
      case "user":
      case "assistant":
        return <Bubble item={it} />;
      case "activity": {
        const C = slots.activity ?? ActivityFallback;
        return <C bot={bot.name} item={it} live={chat?.turn?.id === it.turn.id} />;
      }
      case "approval":
      case "clarify": {
        const C = slots.cards ?? CardFallback;
        return <C bot={bot.name} item={it} />;
      }
      case "away": {
        const C = slots.elsewhereLine ?? ElsewhereFallback;
        return <C bot={bot.name} item={it} />;
      }
      case "routine": {
        const C = slots.routineLine ?? RoutineFallback;
        return <C bot={bot.name} item={it} />;
      }
    }
  };

  return (
    <div
      className="thread"
      ref={ref}
      data-testid="timeline"
      onScroll={(e) => {
        const el = e.currentTarget;
        pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
      }}
    >
      {!chat?.loaded && items.length === 0 && <div className="day">Loading…</div>}
      {chat?.openError && (
        <div className="day" data-testid="chat-error">
          {bot.display_name} is not reachable ({chat.openError}). Start Hermes for this profile, then pick it again.
        </div>
      )}
      {chat?.loaded && !chat.openError && items.length === 0 && <div className="day">Say hi to {bot.display_name}</div>}
      {items.map((it, i) => {
        const label = divider(items[i - 1], it);
        return (
          <Fragment key={it.id}>
            {label && <div className="day">{label}</div>}
            <div className={`row row-${it.kind}`} data-kind={it.kind}>
              {render(it)}
            </div>
          </Fragment>
        );
      })}
      {typing && (
        <div className="row row-assistant row-typing" data-kind="typing">
          <TypingRow bot={bot.name} name={bot.display_name} />
        </div>
      )}
      {streaming && (
        <div className="row row-assistant" data-kind="streaming">
          <Bubble item={{ kind: "assistant", text: streaming }} streaming />
        </div>
      )}
    </div>
  );
}
