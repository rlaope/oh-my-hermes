// A session's name in SESSIONS, in this order: what the person typed when renaming it, the title the agent
// gave its conversation (Claude Code's own title, a Codex thread name, a Hermes session title), a short
// summary of the person's first real message made here on this computer, and last the folder. No model is
// asked for a title: the summary is plain text work.

/** Longest summary, in characters as a person counts them (an emoji or a Hangul syllable is one). */
export const TITLE_MAX = 40;

const graphemer =
  typeof Intl !== "undefined" && "Segmenter" in Intl ? new Intl.Segmenter(undefined, { granularity: "grapheme" }) : null;
const graphemes = (s: string): string[] => (graphemer ? Array.from(graphemer.segment(s), (x) => x.segment) : Array.from(s));

/** Has a letter or a digit in some script: a line of only emoji, punctuation or symbols says nothing. */
const wordy = (s: string) => /[\p{L}\p{N}]/u.test(s);

/** `s` cut to `max` characters: at the last space when there is one in the second half, else mid-word (Japanese
 *  and Chinese have no spaces), then an ellipsis. Never splits an emoji or a Hangul syllable. */
export function clipTitle(s: string, max = TITLE_MAX): string {
  const g = graphemes(s);
  if (g.length <= max) return s;
  const head = g.slice(0, max - 1);
  // the head already ends at a word when the next character is a space
  const space = g[max - 1] === " " ? head.length : head.lastIndexOf(" ");
  const kept = (space >= Math.floor((max - 1) / 2) ? head.slice(0, space) : head).join("");
  return `${kept.replace(/[\s,;:、，—–-]+$/u, "")}…`;
}

/**
 * The person's message as a short session name: no code blocks, links, `@file` references or a leading
 * `/command`; the first line that has words, and of it the first sentence or clause; at most TITLE_MAX
 * characters, cut at a word. "" when nothing worth a name is left (a bare command, a link, an emoji).
 */
export function promptTitle(raw: string, max = TITLE_MAX): string {
  let t = String(raw ?? "").replace(/\r\n?/g, "\n");
  t = t.replace(/(```|~~~)[\s\S]*?(\1|$)/g, "\n"); // fenced code, an unclosed fence to the end
  t = t.replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1"); // [text](url) -> text
  t = t.replace(/<?\b(?:https?|ftp|file):\/\/[^\s>]+>?/gi, " ").replace(/\bwww\.\S+/gi, " ");
  t = t.replace(/(^|\s)@\S+/g, "$1"); // @src/app.ts, @file:notes.md
  t = t.replace(/(^|\n)[ \t]*\/[A-Za-z][\w:.-]*/g, "$1"); // /review, /compact at a line's start
  t = t.replace(/`([^`\n]*)`/g, "$1");
  const line = t
    .split("\n")
    .map((l) =>
      l
        .replace(/^\s*(?:#{1,6}|>+|[-*+•]|\d+[.)])\s+/u, "")
        .replace(/[*_~]{2,}/g, "")
        .replace(/\s+/g, " ")
        .trim(),
    )
    .find(wordy);
  if (!line) return "";
  // the first sentence or clause: up to . ! ? before a space or the end, a CJK 。！？ anywhere, or ; / a spaced dash
  const m = /^(.+?)(?:([.!?]+)(?=\s|$)|([。！？]+)|[;；]\s?|\s[—–-]\s)/u.exec(line);
  const stop = (m?.[2] ?? m?.[3] ?? "").match(/[!?！？]/u)?.[0] ?? "";
  let first = m ? m[1] + stop : line;
  first = first.replace(/[\s,;:、，]+$/u, "").trim();
  if (!wordy(first)) first = line;
  return clipTitle(first, max);
}

/** Where a session's name came from. */
export type TitleSource = "person" | "agent" | "prompt" | "folder";

/** The name a session shows, by the order above, and where it came from. */
export function pickTitle(
  s: { title?: string; agentTitle?: string; promptTitle?: string },
  folder: string,
): { title: string; source: TitleSource } {
  const clean = (v?: string) => (v ?? "").replace(/\s+/g, " ").trim();
  if (clean(s.title)) return { title: clean(s.title), source: "person" };
  if (clean(s.agentTitle)) return { title: clean(s.agentTitle), source: "agent" };
  if (clean(s.promptTitle)) return { title: clean(s.promptTitle), source: "prompt" };
  return { title: folder, source: "folder" };
}

// ---- names the person gave (this computer only) ---------------------------------------------

export const TITLES_KEY = "omher.sessions.titles";
export const TITLES_MAX = 200;
export const NAME_MAX = 80;

/** Saved names by `<agent>:<agent session id>`: the agent's own conversation id outlives omher's row, so a
 *  name stays with the conversation (a Restart, a Claude Code `--resume`). */
export function parseTitles(raw: string | null): Record<string, string> {
  try {
    const v = raw ? JSON.parse(raw) : {};
    if (!v || typeof v !== "object" || Array.isArray(v)) return {};
    const out: Record<string, string> = {};
    for (const [k, t] of Object.entries(v)) if (typeof t === "string" && t.trim() && k) out[k] = t.slice(0, NAME_MAX);
    return out;
  } catch {
    return {};
  }
}

/** `map` with `key` set to `title` (moved to the newest end) or removed (`null`), oldest dropped past TITLES_MAX. */
export function putTitle(map: Record<string, string>, key: string, title: string | null): Record<string, string> {
  const next = { ...map };
  delete next[key];
  if (title) next[key] = title;
  const keys = Object.keys(next);
  for (const k of keys.slice(0, Math.max(0, keys.length - TITLES_MAX))) delete next[k];
  return next;
}
