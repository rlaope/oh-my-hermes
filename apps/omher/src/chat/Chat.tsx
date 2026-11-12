import "./chat.css";
import { selectAsks, useStore } from "../state/store";
import { Header } from "./parts/Header";
import { Timeline } from "./parts/Timeline";
import { Composer } from "./parts/Composer";
import { RunsFull } from "../runs/RunsTab";
import { t } from "../i18n";

/** The selected bot's one main chat: header, timeline, composer. */
export function Chat() {
  const s = useStore();
  const bot = s.bots.find((b) => b.name === s.selectedBot) ?? null;
  if (!bot) {
    // no bot at all: say what a bot is and how to get one, not only that none was found
    const none = s.conn === "open" && s.bots.length === 0;
    return (
      <div className="chat-empty" data-testid="chat-empty">
        {none ? (
          <>
            <b>{t("chat.noBots")}</b>
            <span>
              {t("chat.noBotsHint")} <code>hermes profile create &lt;name&gt;</code>
            </span>
          </>
        ) : s.conn === "open" ? (
          t("chat.pick")
        ) : (
          t("chat.connecting")
        )}
      </div>
    );
  }
  const chat = s.chats[bot.name];
  const asking = selectAsks(s).some((a) => a.bot === bot.name);
  // the bridge is away (it reconnects by itself): the composer says so and waits, like a bot that is offline
  const away = s.conn !== "open";
  return (
    <>
      <Header bot={bot} chat={chat} />
      <div className={`pane${s.ui.runsFull ? " has-full" : ""}`} data-pane={bot.name}>
        <Timeline bot={bot} />
        {s.ui.runsFull && <RunsFull bot={bot} />}
        <Composer
          key={bot.name}
          bot={bot}
          running={!!chat?.turn}
          asking={asking}
          offline={bot.status === "offline" || away}
          offlineText={away ? t("chat.connecting") : undefined}
          skills
          onSend={(text) => void s.send(text)}
          onSendFiles={(text, files) => s.sendWithFiles(text, files)}
          onStop={() => void s.interrupt()}
          reply={s.replyTo[bot.name] ?? null}
          onClearReply={() => s.setReplyTo(null, bot.name)}
        />
      </div>
    </>
  );
}
