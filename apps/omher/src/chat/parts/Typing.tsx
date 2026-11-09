import type { Chat } from "../../state/store";
import { askOpen } from "../../state/store";
import { Avatar, LiveRing, TypingDots } from "../../ui";

/** True while the bot works on an answer and nothing of it has arrived: a turn is running, no delta yet, no
 *  answer of this turn landed, and the bot is not waiting on the person (an open card says that instead). */
export function awaitingFirstToken(chat: Chat | undefined): boolean {
  const t = chat?.turn;
  if (!t || t.streaming) return false;
  const since = t.startedAt / 1000;
  for (const i of chat.items) {
    if (i.kind === "assistant" && i.ts >= since) return false;
    if ((i.kind === "approval" || i.kind === "clarify") && askOpen(chat.items, i)) return false;
  }
  return true;
}

/** The bot's face with the live ring and a typing bubble beside it, until the first delta replaces it with
 *  the streaming bubble. Face 28px + 10px gap: the same column as the face beside bot bubbles. */
export function TypingRow({ bot, name }: { bot: string; name: string }) {
  return (
    <div className="msg a typing" data-testid="typing" role="status" aria-label={`${name} is writing`}>
      <LiveRing on size={28} gap={3} testId="typing-ring" seed={bot}>
        <Avatar bot={bot} size={28} className="msg-face" />
      </LiveRing>
      <div className="b" data-testid="typing-bubble">
        <TypingDots size={6} />
      </div>
    </div>
  );
}
