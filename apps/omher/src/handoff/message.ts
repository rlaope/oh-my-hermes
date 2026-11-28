// "Hand to bot" from an answer (BOUNDARY rule 56): the new thread's title and first message, and the message "Give to
// <bot>" sends back. Fixed English text, like the terminal handover's (src/handover/message.ts), whose printable() and
// goalLine() it reuses: the note is one printable line, a bot's name is printable, and every line of the answer is
// quoted, so nothing in it can start a line of its own outside the quote. An answer longer than ANSWER_CHARS is cut on
// whole characters and the text says so. Pure: the caller passes the names and the text.
import { goalLine, printable } from "../handover/message";
import { firstWords } from "../threads/types";

/** The most characters of an answer that travel to the other bot (and back). */
export const ANSWER_CHARS = 6000;
/** The most characters of a bot's name as the text writes it. */
const NAME = 60;

/** `text` cut to ANSWER_CHARS characters (whole code points), and how long it was when it was cut. */
function capped(text: string): { text: string; cut: number | null } {
  const all = [...text.trim()];
  return all.length <= ANSWER_CHARS ? { text: all.join(""), cut: null } : { text: all.slice(0, ANSWER_CHARS).join("").trimEnd(), cut: all.length };
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

/** The new thread's first message: the note (when there is one), a line naming whose answer it is, the answer quoted,
 *  and a line when it was cut. */
export function handoffMessage(f: HandoffFacts): string {
  const note = goalLine(f.note);
  const a = capped(f.answer);
  const parts = note ? [note] : [];
  parts.push(`${printable(f.from, NAME)} wrote this answer in omher, and the person handed it to you:`, quote(a.text));
  if (a.cut) parts.push(cutLine(a.cut));
  return parts.join("\n\n");
}

/** What "Give to <origin bot>" sends there as the person's own message: "<bot> answered:" and that answer. */
export function givenMessage(from: string, answer: string): string {
  const a = capped(answer);
  const parts = [`${printable(from, NAME)} answered:`, a.text];
  if (a.cut) parts.push(cutLine(a.cut));
  return parts.join("\n\n");
}
