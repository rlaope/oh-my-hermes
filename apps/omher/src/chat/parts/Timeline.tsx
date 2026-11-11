import { Fragment, useEffect, useLayoutEffect, useRef, type ReactNode } from "react";
import type { Bot } from "../../lib/protocol";
import { selectTimeline, turnHasActivity, useStore, type TimelineItem } from "../../state/store";
import { slots } from "../../features";
import { dayLabel, hhmm, sameDay } from "../../app/time";
import { Bubble } from "./Bubble";
import { TypingRow, awaitingFirstToken } from "./Typing";
import { ActivityFallback, CardFallback, ElsewhereFallback, RoutineFallback } from "./fallbacks";
import { PluginAddedCard, RoutineAddedCard } from "../../pages/ChatCards";

/** A time label goes in when the day changes, or after a quiet gap within the same day. */
const GAP = 30 * 60;

function divider(prev: TimelineItem | undefined, cur: TimelineItem): string | null {
  if (!prev || !sameDay(prev.ts, cur.ts)) return dayLabel(cur.ts);
  if (cur.ts - prev.ts > GAP) return hhmm(new Date(cur.ts * 1000));
  return null;
}

/** A bot bubble right above: the next bot bubble keeps the indent but not the face (one face per run). */
const botSpoke = (it?: TimelineItem) => it?.kind === "assistant" || it?.kind === "away";

/** `face` stands in for the bot's picture beside its bubbles and the typing bubble (a SESSIONS chat: its
 *  agent's mark). Pass a stable element (useMemo): the bubbles are memoized on it. */
export function Timeline({ bot, face }: { bot: Bot; face?: ReactNode }) {
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

  // Files the bot sent load after the row is drawn and make it taller: stay at the bottom if pinned.
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => {
      if (pinned.current) el.scrollTop = el.scrollHeight;
    });
    for (const row of el.querySelectorAll(".row-assistant")) ro.observe(row);
    return () => ro.disconnect();
  }, [bot.name, items]);

  const render = (it: TimelineItem, prev?: TimelineItem): ReactNode => {
    switch (it.kind) {
      case "user":
        return <Bubble item={it} />;
      case "assistant":
        // the face shows on the first bot bubble after something else (the user, a day line, a card)
        return <Bubble item={it} bot={bot.name} face={!botSpoke(prev)} faceEl={face} />;
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
        return <C bot={bot.name} item={it} face={!botSpoke(prev)} />;
      }
      case "routine": {
        const C = slots.routineLine ?? RoutineFallback;
        return <C bot={bot.name} item={it} />;
      }
      case "routineAdded":
        return <RoutineAddedCard bot={bot.name} item={it} />;
      case "pluginAdded":
        return <PluginAddedCard bot={bot.name} item={it} />;
      case "system":
        return (
          <div className="line sys" data-testid="system-line">
            <span className="line-t">{it.text}</span>
          </div>
        );
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
        <div className="day note" data-testid="chat-error">
          {bot.display_name} is not reachable ({chat.openError}). Start Hermes for this profile, then pick it again.
        </div>
      )}
      {/* A Hermes installed from the setup screen has no model yet: the first chat screen says where to pick one,
          never a terminal command. */}
      {chat?.loaded && !chat.openError && !(chat.model || bot.model) && (
        <div className="day note" data-testid="chat-no-model">
          {bot.display_name} has no model yet. Pick one from the model menu at the top right to start.
        </div>
      )}
      {chat?.loaded && !chat.openError && items.length === 0 && <div className="day">Say hi to {bot.display_name}</div>}
      {items.map((it, i) => {
        // the live activity line with nothing to say yet: the typing bubble below stands in for it
        if (it.kind === "activity" && chat?.turn?.id === it.turn.id && !turnHasActivity(it.turn)) return null;
        const label = divider(items[i - 1], it);
        return (
          <Fragment key={it.id}>
            {label && <div className="day">{label}</div>}
            <div className={`row row-${it.kind}`} data-kind={it.kind}>
              {render(it, label ? undefined : items[i - 1])}
            </div>
          </Fragment>
        );
      })}
      {typing && (
        <div className="row row-assistant row-typing" data-kind="typing">
          <TypingRow bot={bot.name} name={bot.display_name} face={face} />
        </div>
      )}
      {streaming && (
        <div className="row row-assistant" data-kind="streaming">
          <Bubble
            item={{ kind: "assistant", text: streaming }}
            streaming
            bot={bot.name}
            face={!botSpoke(items[items.length - 1])}
            faceEl={face}
          />
        </div>
      )}
    </div>
  );
}
