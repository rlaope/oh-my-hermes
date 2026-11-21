import type { MessageItem, TimelineItem } from "../../state/store";

/** What a bot answer at `at` (an index into the timeline, or its length for the answer still being written)
 *  replies to: the person's messages since the bot last spoke,
 *  oldest first. A send that failed or that Stop threw away was never read, so it is not answered. */
export function answered(items: TimelineItem[], at: number): MessageItem[] {
  const out: MessageItem[] = [];
  for (let k = at - 1; k >= 0; k--) {
    const it = items[k];
    // the bot spoke since. A SESSIONS agent (Claude Code, Codex)
    // sends each text block of one turn as its own bubble, so only the first bubble after the person's messages
    // carries the quote: the ones after it break here.
    if (it.kind === "assistant") break;
    // a held message (steer queue) was never sent, so no answer replies to it
    if (it.kind === "user" && !it.error && it.wait !== "dropped" && !it.held) out.unshift(it);
  }
  return out;
}

export interface Quote {
  /** Each message answered (whitespace folded, at most QUOTE_CHARS), oldest first, at most QUOTE_LINES of them. */
  lines: { id: string; text: string }[];
  /** How many more of the person's messages this answer covers than `lines` shows. */
  more: number;
}

const QUOTE_CHARS = 140;
const QUOTE_LINES = 3;

/** The quote an answer carries, or null unless it covers two or more of the person's messages. One message is
 *  plain enough, whatever sits between it and the answer (activity, a card, a notice). Several messages sent
 *  before one answer, and the answer says what it replies to: each message's first line. */
export function quoteFor(items: TimelineItem[], at: number): Quote | null {
  const asks = answered(items, at);
  if (asks.length < 2) return null;
  const shown = asks.slice(-QUOTE_LINES);
  return { lines: shown.map((m) => ({ id: m.id, text: firstLine(m.text || m.files?.[0]?.name || "") })), more: asks.length - shown.length };
}

function firstLine(text: string): string {
  const line = text.replace(/\s+/g, " ").trim();
  return line.length > QUOTE_CHARS ? `${line.slice(0, QUOTE_CHARS - 1).trimEnd()}…` : line;
}
