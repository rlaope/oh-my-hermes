// `./thread` in a bot's composer: a new thread under the bot, the rest of the message (if any) its first message.
// It counts only at the start of the box (after any blank space) and only as the whole word: `./thread` alone or
// followed by whitespace. Anywhere else, `./threads`, `./thread.sh` and `./Thread` go out as typed, like any other
// `./name` or path. It is omher's own command, not a skill: skills are `$name`, so a skill named `thread` is
// `$thread` and never meets it. The token itself is never sent to the bot.

export const THREAD_CMD = "./thread";
const NAME = "thread";

/** `./thread` at the start of `text`: where the token sits and the first message after it (trimmed, "" for none). */
export function threadCommand(text: string): { start: number; end: number; first: string } | null {
  const m = /^(\s*)\.\/thread(?=\s|$)/.exec(text);
  if (!m) return null;
  const start = m[1].length;
  return { start, end: start + THREAD_CMD.length, first: text.slice(m[0].length).trim() };
}

/** While the whole box is `./` and a beginning of `thread` (`./`, `./th`, `./thread`): what follows `./`, else null.
 *  The picker shows then; `./b`, `./thread x` or a path do not open it. */
export function threadFragment(text: string): string | null {
  const m = /^\s*\.\/([a-z]*)$/.exec(text);
  return m && NAME.startsWith(m[1]) ? m[1] : null;
}
