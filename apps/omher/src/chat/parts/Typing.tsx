import type { ReactNode } from "react";
import type { Chat } from "../../state/store";
import { answerSoFar, askOpen } from "../../state/store";
import { Avatar, LiveRing, TypingDots } from "../../ui";
import { t } from "../../i18n";

/** True while the bot works on an answer and nothing of it shows yet: a turn is running, no line of the answer
 *  shows, no answer of this turn landed, and the bot is not waiting on the person (an open card says that instead).
 *  Tool steps do not end it: the dots stay under the activity line until the answer starts, so the person always
 *  sees the bot is still writing (owner's ask, messenger style). */
export function awaitingFirstToken(chat: Chat | undefined): boolean {
  const t = chat?.turn;
  // text being written ends the typing bubble only once a whole line of it can show (answerSoFar)
  if (!t || answerSoFar(t)) return false;
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

/** The bot's face with the live ring and a typing bubble beside it, until the answer starts. Face 28px + 10px gap:
 *  the same column as the face beside bot bubbles. `under`: the activity line shows and holds the one ringed face,
 *  so the dots sit under it in the text column with no face of their own. */
export function TypingRow({ bot, name, face, under }: { bot: string; name: string; face?: ReactNode; under?: boolean }) {
  return (
    <div className={`msg a typing${under ? " under" : ""}`} data-testid="typing" role="status" aria-label={t("ty.writing", { name })}>
      {!under && <LiveFace bot={bot} face={face} testId="typing-ring" />}
      <div className="b" data-testid="typing-bubble">
        <TypingDots size={6} />
      </div>
    </div>
  );
}
