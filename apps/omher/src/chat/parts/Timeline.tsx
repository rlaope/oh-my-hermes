import { Fragment, useEffect, useLayoutEffect, useRef, type ReactNode } from "react";
import type { Bot } from "../../lib/protocol";
import { selectTimeline, turnHasActivity, useStore, type TimelineItem } from "../../state/store";
import { slots } from "../../features";
import { dayLabel, hhmm, sameDay } from "../../app/time";
import { Bubble } from "./Bubble";
import { LiveFace, TypingRow, awaitingFirstToken } from "./Typing";
import { liveFaceRow } from "./liveFace";
import { ActivityFallback, CardFallback, ElsewhereFallback, RoutineFallback } from "./fallbacks";
import { PluginAddedCard, RoutineAddedCard } from "../../pages/ChatCards";
import { t } from "../../i18n";

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
export function Timeline({ bot, face, onEditLast }: { bot: Bot; face?: ReactNode; onEditLast?: () => void }) {
  const s = useStore();
  const items = selectTimeline(s, bot.name);
  const chat = s.chats[bot.name];
  const streaming = chat?.turn?.streaming ?? "";
  const typing = awaitingFirstToken(chat);
  // the one row of the live run that carries the bot's ringed face
  const faceRow = liveFaceRow(items, chat?.turn, typing);
  const ref = useRef<HTMLDivElement>(null);
  const pinned = useRef(true);
  const lastTop = useRef(0);
  const lastBot = useRef<string | null>(null);
  // the person's last message, when the chat can take it back (a SESSIONS agent's own rewind)
  const lastUser = onEditLast ? [...items].reverse().find((i) => i.kind === "user") : undefined;

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
    // and each turn's activity: a fan-out card grows after its turn ended, as its subagents report back
    for (const row of el.querySelectorAll(".row-assistant, .row-activity")) ro.observe(row);
    return () => ro.disconnect();
  }, [bot.name, items]);

  const render = (it: TimelineItem, prev?: TimelineItem): ReactNode => {
    switch (it.kind) {
      case "user":
        return <Bubble item={it} onEdit={it === lastUser && !it.error && !it.wait ? onEditLast : undefined} />;
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
        // only the person scrolling up lets go of the bottom: a reflow (the side panel opening narrows the column)
        // also fires scroll, with the bottom moved away but the position not moved up
        if (el.scrollHeight - el.scrollTop - el.clientHeight < 40) pinned.current = true;
        else if (el.scrollTop < lastTop.current) pinned.current = false;
        lastTop.current = el.scrollTop;
      }}
    >
      {!chat?.loaded && items.length === 0 && <div className="day">{t("tl.loading")}</div>}
      {chat?.openError && (
        <div className="day note" data-testid="chat-error">
          {t("tl.unreachable", { bot: bot.display_name, error: chat.openError })}
        </div>
      )}
      {/* A Hermes installed from the setup screen has no model yet: the first chat screen says where to pick one,
          never a terminal command. */}
      {chat?.loaded && !chat.openError && !(chat.model || bot.model) && (
        <div className="day note" data-testid="chat-no-model">
          {t("tl.noModel", { bot: bot.display_name })}
        </div>
      )}
      {chat?.loaded && !chat.openError && items.length === 0 && <div className="day">{t("tl.sayHi", { bot: bot.display_name })}</div>}
      {items.map((it, i) => {
        // the live activity line with nothing to say yet: the typing bubble below stands in for it
        if (it.kind === "activity" && chat?.turn?.id === it.turn.id && !turnHasActivity(it.turn)) return null;
        const label = divider(items[i - 1], it);
        // the live activity line holds the face between the typing bubble and the answer, and keeps the typing
        // bubble's height until the turn ends, so neither hand-over moves it
        const liveLine = it.kind === "activity" && chat?.turn?.id === it.turn.id && (faceRow === "activity" || faceRow === "streaming");
        const liveFace = liveLine && faceRow === "activity";
        return (
          <Fragment key={it.id}>
            {label && <div className="day">{label}</div>}
            <div className={`row row-${it.kind}${liveLine ? " live-line" : ""}`} data-kind={it.kind}>
              {liveFace && <LiveFace bot={bot.name} face={face} />}
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
            live={faceRow === "streaming"}
          />
        </div>
      )}
    </div>
  );
}
