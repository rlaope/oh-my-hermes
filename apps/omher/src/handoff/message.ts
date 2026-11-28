// "Hand to bot" from an answer (BOUNDARY rule 58): the new thread's title and first message, and the message "Give to
// <bot>" sends back. Fixed English text, like the terminal handover's (src/handover/message.ts), whose printable() and
// goalLine() it reuses. Each text starts with a fixed lead, so neither can ever start with `/` and run as a Hermes
// command (the bridge and the page read a text as one when it starts with `/` after white space), whatever the note,
// the answer or a bot's name hold. The note is one printable line after "Note: ", a bot's name is printable, and every
// line of the handed answer is quoted, so nothing in it can start a line of its own outside the quote. An answer
// longer than ANSWER_CHARS is cut on whole characters, a code fence the cut leaves open is closed, and the text says
// so. Pure: the caller passes the names and the text.
import { goalLine, printable } from "../handover/message";
import { firstWords } from "../threads/types";

/** The most characters of an answer that travel to the other bot (and back). */
export const ANSWER_CHARS = 6000;
/** The most characters of a bot's name as the text writes it. */
const NAME = 60;

/** A line's block quote markers (CommonMark: each `>` after up to three spaces, with one optional space after it). */
const QUOTES = /^(?: {0,3}> ?)*/;
/** A fenced code block's opening or closing line (CommonMark: up to three spaces, then three or more ` or ~), after
 *  the line's quote markers. A line indented four or more spaces there is no fence: CommonMark reads it as a line of an
 *  indented code block, so it neither opens nor closes one. */
const FENCE = /^((?: {0,3}> ?)*) {0,3}(`{3,}|~{3,})(.*)$/;
const depth = (quotes: string) => quotes.split(">").length - 1;

/** The line that closes the code fence `text` leaves open at its end (with that fence's quote markers, when it is
 *  inside a block quote of the answer), or "" when none is open. */
function openFence(text: string): string {
  let open: { mark: string; quotes: string } | null = null;
  for (const line of text.split(/\r\n|[\r\n\u2028\u2029]/)) {
    // a fence inside a block quote ends with the quote: a line with fewer markers is outside it (no lazy line
    // continues a fence)
    if (open && depth(QUOTES.exec(line)![0]) < depth(open.quotes)) open = null;
    const m = FENCE.exec(line);
    if (!m) continue;
    const [, quotes, mark, info] = m;
    // a backtick fence's info string holds no backtick; a closing fence is the same mark, as long or longer, alone,
    // in the same block quote
    if (open === null) open = mark[0] === "`" && info.includes("`") ? null : { mark, quotes };
    else if (depth(quotes) === depth(open.quotes) && mark[0] === open.mark[0] && mark.length >= open.mark.length && !info.trim()) open = null;
  }
  return open ? `${open.quotes}${open.mark}` : "";
}

/** `text` cut to ANSWER_CHARS characters (whole code points), and how long it was when it was cut. A cut inside a
 *  code fence closes it, so the line saying it was cut is never read as code. */
function capped(text: string): { text: string; cut: number | null } {
  const all = [...text.trim()];
  if (all.length <= ANSWER_CHARS) return { text: all.join(""), cut: null };
  const kept = all.slice(0, ANSWER_CHARS).join("").trimEnd();
  const fence = openFence(kept);
  return { text: fence ? `${kept}\n${fence}` : kept, cut: all.length };
}

const cutLine = (n: number) => `(The answer was cut: this is its first ${ANSWER_CHARS.toLocaleString("en-US")} of ${n.toLocaleString("en-US")} characters.)`;

/** Every line of `text` as a Markdown quote line; any line break (CR, LF, U+2028, U+2029) starts a quoted line. */
const quote = (text: string) =>
  text
    .split(/\r\n|[\r\n\u2028\u2029]/)
    .map((l) => (l ? `> ${l}` : ">"))
    .join("\n");

export interface HandoffFacts {
  /** The display name of the bot whose answer it is. */
  from: string;
  /** What the person typed for the other bot to do; empty for none. */
  note: string;
  /** The answer's text. */
  answer: string;
}

/** The new thread's title: "From <bot>: " and the first words of the note, else of the answer. */
export function handoffTitle(f: HandoffFacts): string {
  const note = goalLine(f.note);
  return `From ${printable(f.from, NAME)}: ${firstWords(note || goalLine(f.answer)) || "an answer"}`;
}

/** The new thread's first message: the fixed line naming whose answer it is, "Note: " and the note (when there is one),
 *  the answer quoted, and a line when it was cut. */
export function handoffMessage(f: HandoffFacts): string {
  const note = goalLine(f.note);
  const a = capped(f.answer);
  const parts = [`Handoff from omher: ${printable(f.from, NAME)} wrote the answer below, and the person handed it to you.`];
  if (note) parts.push(`Note: ${note}`);
  parts.push(quote(a.text));
  if (a.cut) parts.push(cutLine(a.cut));
  return parts.join("\n\n");
}

/** What "Give to <origin bot>" sends there as the person's own message: "Answer from <bot>:" and that answer. */
export function givenMessage(from: string, answer: string): string {
  const a = capped(answer);
  const parts = [`Answer from ${printable(from, NAME)}:`, a.text];
  if (a.cut) parts.push(cutLine(a.cut));
  return parts.join("\n\n");
}
