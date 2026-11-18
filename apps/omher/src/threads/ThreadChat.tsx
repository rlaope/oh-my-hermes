// A thread of a bot in the main column: the bot's own header, timeline and composer, fed by the thread's chat
// (`fold:<bot>:<thread>`). Same Chat parts as the main chat; only where the words go differs.
import { selectAsks, useStore } from "../state/store";
import type { Bot } from "../lib/protocol";
import { Timeline } from "../chat/parts/Timeline";
import { Composer } from "../chat/parts/Composer";
import { Avatar } from "../ui";
import { t } from "../i18n";
import { threadKey } from "./types";
import { rowStatus } from "./ThreadTree";
import { StatusGlyph } from "./StatusGlyph";

export function ThreadChat({ bot, thread }: { bot: Bot; thread: string }) {
  const s = useStore();
  const key = threadKey(bot.name, thread);
  const chat = s.chats[key];
  const row = (s.threads[bot.name] ?? []).find((r) => r.thread === thread);
  const title = row?.title || t("thread.untitled");
  const away = s.conn !== "open";
  // the thread's chat stands in for a bot in the timeline and composer (its key, the bot's own picture and model)
  const as: Bot = { ...bot, name: key, model: chat?.model || bot.model, running: !!chat?.turn };
  return (
    <>
      <header className="head th-head" data-testid="thread-header">
        <button type="button" className="who-btn" onClick={() => void s.openThread(bot.name, null)} title={bot.display_name} data-testid="thread-back">
          <Avatar bot={bot.name} size={26} />
          <span className="head-title th-head-bot">{bot.display_name}</span>
        </button>
        <span className="th-head-sep" aria-hidden="true">
          /
        </span>
        {row && <StatusGlyph status={rowStatus(s, bot.name, row)} />}
        <span className="head-title th-head-title" data-testid="thread-title" title={title}>
          {title}
        </span>
      </header>
      <div className="pane" data-pane={key} data-testid="thread-chat" data-thread={thread}>
        <Timeline
          bot={as}
          face={<Avatar bot={bot.name} size={28} />}
          connectionNotice={false}
          emptyHint={
            !chat?.turn && (
              <div className="th-empty" data-testid="thread-empty">
                {t("thread.newHint", { name: bot.display_name })}
              </div>
            )
          }
        />
        <Composer
          key={key}
          bot={as}
          running={!!chat?.turn}
          asking={selectAsks(s).some((a) => a.bot === key)}
          offline={bot.status === "offline" || away}
          offlineText={away ? t("chat.connecting") : undefined}
          onSend={(text) => void s.threadSend(bot.name, thread, text)}
          onStop={() => void s.threadInterrupt(bot.name, thread)}
        />
      </div>
    </>
  );
}
