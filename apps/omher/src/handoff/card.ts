// The "Handed to <bot>" card's state (BOUNDARY rule 56): how the first turn of the thread it started goes, read from
// that thread's own events as the store reduces them. Pure; the store keeps the card in the origin chat and a map from
// the thread's chat key to it, in the page only.
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

/** The card after one event of the target thread (`target`: that thread's chat with the event already applied). The
 *  first turn's end settles it: later turns there do not change it, and nothing goes back by itself. */
export function handoffStep(card: HandoffItem, ev: BridgeEvent, target: Chat | undefined): HandoffItem {
  if (card.phase !== "working" && card.phase !== "waiting") return card;
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
    default:
      return card;
  }
}
