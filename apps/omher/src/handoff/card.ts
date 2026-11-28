// The "Handed to <bot>" card's state (BOUNDARY rule 58): how the first turn of the thread it started goes, read from
// that thread's own events as the store reduces them, and from what ends a turn without an event (the connection
// dropping, the thread read again, the first send refused). Pure; the store keeps the card in the origin chat and a
// map from the thread's chat key to it, in the page only.
import type { BridgeEvent } from "../lib/protocol";
import type { Chat, HandoffItem } from "../state/store";

/** The answer the target thread gave to the handed text: its last bot answer (the thread is new, made for it; not a
 *  mid-turn command's output, not a question's context row). */
function lastAnswer(target: Chat | undefined): string {
  const items = target?.items ?? [];
  for (let i = items.length - 1; i >= 0; i--) {
    const it = items[i];
    if (it.kind === "assistant" && !it.command && !it.id.startsWith("clarify-note-") && it.text.trim()) return it.text;
  }
  return "";
}

const open = (card: HandoffItem) => card.phase === "working" || card.phase === "waiting";

/** The bridge connection dropped: the thread's turn is no longer seen (the store ends it as interrupted), so the card
 *  stops too, marked `lost` so the thread's next read settles it. */
export function handoffLost(card: HandoffItem, error: string): HandoffItem {
  return open(card) ? { ...card, phase: "stopped", outcome: "interrupted", error, lost: true } : card;
}

/** The target thread was read again (`target`: its chat after the read) after the connection dropped and stopped the
 *  card (`lost`), when no event may tell how its turn went: still running, the card works on; else it is done with the
 *  answer the thread holds, or stopped when it holds none. A card the drop did not stop is left to the thread's own
 *  events: a read between the handed text's send and its turn's start sees neither a turn nor an answer yet. */
export function handoffOpened(card: HandoffItem, target: Chat | undefined): HandoffItem {
  if (!card.lost) return card;
  const { lost: _l, outcome: _o, error: _e, ...base } = card;
  if (target?.turn) return { ...base, phase: "working" };
  const answer = lastAnswer(target);
  return answer ? { ...base, phase: "done", answer } : { ...base, phase: "stopped", outcome: "ended" };
}

/** A send into the target thread was refused while no turn runs there: the handed text never started one. */
export function handoffFailed(card: HandoffItem, target: Chat | undefined, error: string): HandoffItem {
  return open(card) && !target?.turn ? { ...card, phase: "stopped", outcome: "error", error } : card;
}

/** The card after one event of the target thread (`target`: that thread's chat with the event already applied). The
 *  first turn's end settles it: later turns there do not change it, and nothing goes back by itself. */
export function handoffStep(card: HandoffItem, ev: BridgeEvent, target: Chat | undefined): HandoffItem {
  if (!open(card)) return card;
  switch (ev.event) {
    case "approval.request":
    case "clarify.request":
      return card.phase === "waiting" ? card : { ...card, phase: "waiting" };
    // the person answered in the thread and the bot goes on
    case "turn.start":
    case "tool.start":
    case "tool.end":
    case "delta":
    case "message":
    case "prompt.expired":
      return card.phase === "waiting" ? { ...card, phase: "working" } : card;
    case "turn.end":
      if (ev.outcome === "done" && !ev.error) return { ...card, phase: "done", answer: lastAnswer(target) };
      return { ...card, phase: "stopped", outcome: ev.outcome, ...(ev.error ? { error: ev.error } : {}) };
    // the bot's gateway dropped before the handed text's turn started (a running one ends with turn.end first): as a
    // dropped bridge connection, the thread's next read settles it
    case "folder.closed":
      return handoffLost(card, ev.reason ?? "");
    default:
      return card;
  }
}
