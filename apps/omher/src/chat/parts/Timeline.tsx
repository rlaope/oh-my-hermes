import { Fragment, useEffect, useLayoutEffect, useRef, type ReactNode } from "react";
import { RestartAction, RestartLine } from "../../sidebar/RestartLine";
import type { Bot } from "../../lib/protocol";
import { answerSlot, answerSoFar, selectTimeline, turnHasActivity, useStore, type TimelineItem } from "../../state/store";
import { slots } from "../../features";
import { dayLabel, hhmm, sameDay } from "../../app/time";
import { Bubble } from "./Bubble";
import type { QueueChoice, QueueOffReasons } from "./QueueMark";
import type { MessageItem } from "../../state/store";

/** steer queue sessions: a SESSIONS chat's own ↵ menu. `off` says which items are off and why for a user row, or
 *  null for a row with no menu; `pick` runs the choice. */
export interface SessionQueue {
  off(it: MessageItem): QueueOffReasons | null;
  pick(id: string, c: QueueChoice): void;
}
import { quoteFor } from "./answers";
import { LiveFace, TypingRow, awaitingFirstToken } from "./Typing";
import { liveFaceRow } from "./liveFace";
import { ActivityFallback, CardFallback, RoutineFallback } from "./fallbacks";
import { PluginAddedCard, RoutineAddedCard } from "../../pages/ChatCards";
import { ThreadLinkLine, ThreadRouteCard } from "../cards/ThreadNotes";
import { WatchLine } from "../../routines/WatchLine";
import { t } from "../../i18n";
import { useBotReady } from "../connect/ready";

/** A time label goes in when the day changes, or after a quiet gap within the same day. */
const GAP = 30 * 60;

function divider(prev: TimelineItem | undefined, cur: TimelineItem): string | null {
  if (!prev || !sameDay(prev.ts, cur.ts)) return dayLabel(cur.ts);
  if (cur.ts - prev.ts > GAP) return hhmm(new Date(cur.ts * 1000));
  return null;
}

/** A bot bubble right above: the next bot bubble keeps the indent but not the face (one face per run). */
const botSpoke = (it?: TimelineItem) => it?.kind === "assistant";

/** `face` stands in for the bot's picture beside its bubbles and the typing bubble (a SESSIONS chat: its
 *  agent's mark). Pass a stable element (useMemo): the bubbles are memoized on it. */
export function Timeline({
  bot,
  face,
  onEditLast,
  connectionNotice = true,
  queue,
}: {
  bot: Bot;
  face?: ReactNode;
  onEditLast?: () => void;
  connectionNotice?: boolean;
  queue?: SessionQueue;
}) {
  const s = useStore();
  const items = selectTimeline(s, bot.name);
  const chat = s.chats[bot.name];
  const notReady = useBotReady(bot.name).status === "not";
  // the answer being written, in whole lines: never word by word, never the commentary beside a tool call
  const writing = chat?.turn ? answerSoFar(chat.turn) : "";
  const typing = awaitingFirstToken(chat);
  // the one row of the live run that carries the bot's ringed face
  const faceRow = liveFaceRow(items, chat?.turn, typing);
  const ref = useRef<HTMLDivElement>(null);
  const pinned = useRef(true);
  const lastTop = useRef(0);
  const lastBot = useRef<string | null>(null);
  // the person's last message, when the chat can take it back (a SESSIONS agent's own rewind)
  const lastUser = onEditLast ? [...items].reverse().find((i) => i.kind === "user") : undefined;
  // taking it back rewinds the conversation only: when its turn changed files, the Edit control says they stay
  const lastUserAt = lastUser ? items.indexOf(lastUser) : -1;
  const keptFiles =
    lastUserAt >= 0 && items.slice(lastUserAt + 1).some((i) => i.kind === "activity" && i.turn.steps.some((st) => st.diff?.length));

  // Stick to the bottom unless the person scrolled up; jump to the bottom on bot switch.
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (lastBot.current !== bot.name || pinned.current) el.scrollTop = el.scrollHeight;
    lastBot.current = bot.name;
  }, [bot.name, items, writing, typing]);

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

  // steer queue: the ↵ menu of a held message (Edit puts it back in this chat's box)
  const queuePick = (id: string) => (c: QueueChoice) => {
    if (c === "now") void s.queueSendNow(id, bot.name);
    else if (c === "steer") void s.queueSteer(id, bot.name);
    else if (c === "edit") s.queueEdit(id, bot.name);
    else if (c === "send") s.queueResend(id, bot.name);
    else s.queueDelete(id, bot.name);
  };

  // a quote's click: the message it answers, brought into view and lit for a moment
  const showMessage = (id: string) => {
    const el = ref.current?.querySelector<HTMLElement>(`[data-item="${CSS.escape(id)}"]`);
    if (!el) return;
    el.scrollIntoView({ block: "center", behavior: "smooth" });
    el.classList.remove("lit");
    void el.offsetWidth;
    el.classList.add("lit");
  };

  const render = (it: TimelineItem, prev?: TimelineItem, at = -1): ReactNode => {
    switch (it.kind) {
      case "user": {
        const off = queue ? queue.off(it) : it.held || it.steerUnknown ? {} : null;
        return (
          <Bubble
            item={it}
            onEdit={it === lastUser && !it.error && !it.wait && !it.held ? onEditLast : undefined}
            editKeepsFiles={it === lastUser && keptFiles}
            onQueue={off ? (queue ? (c: QueueChoice) => queue.pick(it.id, c) : queuePick(it.id)) : undefined}
            queueBusy={it.held && chat?.steering === it.id}
            queueOff={off ?? undefined}
            steeredTo={bot.display_name}
          />
        );
      }
      case "assistant":
        // the face shows on the first bot bubble after something else (the user, a day line, a card); an automation's
        // answer has its "Watch · <name>" line above it
        if (it.watch)
          return (
            <>
              <WatchLine name={it.watch.name} ts={it.watch.ts} text={it.text} />
              <Bubble item={it} bot={bot.name} face faceEl={face} />
            </>
          );
        return <Bubble item={it} bot={bot.name} face={!botSpoke(prev)} faceEl={face} quote={quoteFor(items, at)} onQuote={showMessage} />;
      case "activity": {
        const C = slots.activity ?? ActivityFallback;
        return <C bot={bot.name} item={it} live={chat?.turn?.id === it.turn.id} />;
      }
      case "approval":
      case "clarify": {
        const C = slots.cards ?? CardFallback;
        return <C bot={bot.name} item={it} />;
      }
      case "routine": {
        const C = slots.routineLine ?? RoutineFallback;
        return <C bot={bot.name} item={it} />;
      }
      case "routineAdded":
        return <RoutineAddedCard bot={bot.name} item={it} />;
      case "pluginAdded":
        return <PluginAddedCard bot={bot.name} item={it} />;
      case "threadLink":
        return <ThreadLinkLine item={it} />;
      case "threadRoute":
        return <ThreadRouteCard item={it} />;
      case "system":
        return (
          <div className="line sys" data-testid="system-line">
            <span className="line-t">{it.text}</span>
          </div>
        );
    }
  };

  // the answer as it is written, a whole line or paragraph at a time (answerSoFar), in the one bubble the whole answer
  // then takes: never word by word, never the bot's commentary beside its tool calls. It sits where the answer will
  // land (answerSlot): above a message the person sent while it was being written, which is answered next.
  const slotId = chat?.turn ? chat.items[answerSlot(chat)]?.id : undefined;
  const writingRow = writing ? (
    <div className="row row-assistant" data-kind="streaming">
      <Bubble
        item={{ kind: "assistant", text: writing }}
        streaming
        bot={bot.name}
        face={!botSpoke(slotId ? items[items.findIndex((i) => i.id === slotId) - 1] : items[items.length - 1])}
        faceEl={face}
        live={faceRow === "streaming"}
        quote={quoteFor(items, slotId ? items.findIndex((i) => i.id === slotId) : items.length)}
        onQuote={showMessage}
      />
    </div>
  ) : null;
  // the typing dots too: where the answer will land
  const typingRow = typing ? (
    <div className="row row-assistant row-typing" data-kind="typing">
      <TypingRow bot={bot.name} name={bot.display_name} face={face} />
    </div>
  ) : null;

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
      {connectionNotice && bot.status === "offline" && (
        <div className="day note rs-note" data-testid="chat-offline">
          <span>{t("tl.offline", { bot: bot.display_name })}</span> <RestartAction bot={bot} start testId="chat-start" />
          <RestartLine bot={bot} testId="chat-restart-line" />
        </div>
      )}
      {/* A Hermes installed from the setup screen has no model yet: the first chat screen says where to pick one,
          never a terminal command. */}
      {chat?.loaded && !chat.openError && !(chat.model || bot.model) && !(connectionNotice && notReady) && (
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
            {it.id === slotId && writingRow}
            {it.id === slotId && typingRow}
            {label && <div className="day">{label}</div>}
            <div className={`row row-${it.kind}${liveLine ? " live-line" : ""}`} data-kind={it.kind} {...(it.kind === "user" ? { "data-item": it.id } : {})}>
              {liveFace && <LiveFace bot={bot.name} face={face} />}
              {render(it, label ? undefined : items[i - 1], i)}
            </div>
          </Fragment>
        );
      })}
      {!slotId && writingRow}
      {!slotId && typingRow}
    </div>
  );
}
