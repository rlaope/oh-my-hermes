import type { ReactNode } from "react";
import type { Chat } from "../../state/store";
import { askOpen, turnHasActivity } from "../../state/store";
import { Avatar, LiveRing, TypingDots } from "../../ui";
import { t } from "../../i18n";

/** True while the bot works on an answer and nothing of it shows yet: a turn is running with no step or status
 *  for the activity line (one live indicator in the chat: the line takes over at the first tool), no delta, no
 *  answer of this turn landed, and the bot is not waiting on the person (an open card says that instead). */
export function awaitingFirstToken(chat: Chat | undefined): boolean {
  const t = chat?.turn;
  if (!t || t.streaming || turnHasActivity(t)) return false;
  const since = t.startedAt / 1000;
  for (const i of chat.items) {
    if (i.kind === "assistant" && i.ts >= since) return false;
    if ((i.kind === "approval" || i.kind === "clarify") && askOpen(chat.items, i)) return false;
  }
  return true;
}

/** The bot's 28px face in the live ring (`face`: a SESSIONS chat's agent mark instead of the picture). One of
 *  these sits in the live run while the bot works: beside the typing bubble, then the activity line, then the
 *  streaming answer (liveFaceRow). */
export function LiveFace({ bot, face, testId = "face-ring" }: { bot: string; face?: ReactNode; testId?: string }) {
  return (
    <LiveRing on size={28} gap={3} testId={testId} seed={bot}>
      {face ?? <Avatar bot={bot} size={28} className="msg-face" />}
    </LiveRing>
  );
}

/** The bot's face with the live ring and a typing bubble beside it, until the turn has a status or a step for
 *  the activity line, or the first delta. Face 28px + 10px gap: the same column as the face beside bot bubbles. */
export function TypingRow({ bot, name, face }: { bot: string; name: string; face?: ReactNode }) {
  return (
    <div className="msg a typing" data-testid="typing" role="status" aria-label={t("ty.writing", { name })}>
      <LiveFace bot={bot} face={face} testId="typing-ring" />
      <div className="b" data-testid="typing-bubble">
        <TypingDots size={6} />
      </div>
    </div>
  );
}
