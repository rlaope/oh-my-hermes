import "./chat.css";
import { useStore } from "../state/store";
import { Header } from "./parts/Header";
import { Timeline } from "./parts/Timeline";
import { Composer } from "./parts/Composer";

/** The selected bot's one main chat: header, timeline, composer. */
export function Chat() {
  const s = useStore();
  const bot = s.bots.find((b) => b.name === s.selectedBot) ?? null;
  if (!bot) {
    const text =
      s.conn === "open" ? (s.bots.length ? "Pick a bot" : "No Hermes profiles found") : "Connecting to Hermes…";
    return (
      <div className="chat-empty" data-testid="chat-empty">
        {text}
      </div>
    );
  }
  const chat = s.chats[bot.name];
  return (
    <>
      <Header bot={bot} chat={chat} />
      <div className="pane" data-pane={bot.name}>
        <Timeline bot={bot} />
        <Composer
          key={bot.name}
          bot={bot}
          running={!!chat?.turn}
          offline={bot.status === "offline"}
          onSend={(t) => void s.send(t)}
          onStop={() => void s.interrupt()}
          reply={s.replyTo[bot.name] ?? null}
          onClearReply={() => s.setReplyTo(null, bot.name)}
        />
      </div>
    </>
  );
}
