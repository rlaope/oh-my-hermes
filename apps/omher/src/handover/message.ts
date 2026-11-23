// "Hand to <bot>": the thread's title and its first message, made from a folder the person hands over (a TERMINALS
// session's folder or a Worktrees row). Fixed English text, like "Start in thread" (src/tasks/message.ts): the
// folder, the branch, a short git status and diff stat when omher has them, an optional goal line, and one closing
// line saying nothing moved. The git facts come only from the bot's own Worktrees list and one `panel.diff` of a
// worktree in it (BOUNDARY.md rule 10); a folder outside them is handed with no git facts and the bot reads them
// with its own tools. Paths and branch names go in code spans, so spaces, backslashes and `_` show as written.
// Every name in it (folder, worktree, branch, file) comes from disk or from a repository someone else may have
// written, so each goes through printable() first: a control character, a line or paragraph separator or a bidi
// control becomes a visible escape and cannot start a line of its own (a forged "Goal:"), and each name, its code
// span's fences included, is at most NAME_CHARS. The goal is one line the same way. The whole message stays under
// MESSAGE_CHARS by construction.
import { pathKey } from "../sessions/folders";
import type { Worktree, WorktreeDiff } from "../lib/protocol";

/** The most files the diff stat lists by name; the rest are counted. */
export const STAT_FILES = 20;
/** The most characters of the goal line. */
export const GOAL_CHARS = 500;
/** The most characters of one name (a path, a branch, a file) as written: its escapes and its code span's fences. */
export const NAME_CHARS = 240;
/** What the whole message stays under: the fixed lines, three names (folder, worktree, branch), STAT_FILES file names
 *  (each at most NAME_CHARS, fences included) and the goal at its cap come to under 7,500. */
export const MESSAGE_CHARS = 8192;

/** C0 and C1 controls, DEL, the line and paragraph separators and the bidi controls (U+200E/F, U+202A-202E,
 *  U+2066-2069): what could start a new line or reorder what a reader sees. */
const UNSAFE = /[\u0000-\u001f\u007f-\u009f\u2028\u2029\u200e\u200f\u202a-\u202e\u2066-\u2069]/g;
const NAMED: Record<string, string> = { "\n": "\\n", "\r": "\\r", "\t": "\\t" };

/** `s` as its tokens: each character, or its visible escape when it is UNSAFE (`\n`, `\r`, `\t`, else `\u202E` and
 *  the like). A cut never splits a token, so an escape is never left half written. */
function tokens(s: string): string[] {
  return [...s].map((c) => (UNSAFE_ONE.test(c) ? (NAMED[c] ?? `\\u${c.charCodeAt(0).toString(16).toUpperCase().padStart(4, "0")}`) : c));
}
const UNSAFE_ONE = new RegExp(UNSAFE.source);

/** The tokens as text, at most `max` characters: whole tokens and then "…" when they do not all fit. */
function fit(t: string[], max: number): string {
  const all = t.join("");
  if ([...all].length <= max) return all;
  let out = "";
  let used = 0;
  for (const x of t) {
    const n = [...x].length;
    if (used + n > max - 1) break;
    out += x;
    used += n;
  }
  return `${out}…`;
}

/** `s` with every UNSAFE character as a visible escape, cut on whole tokens to `max` characters with "…". */
export function printable(s: string, max = NAME_CHARS): string {
  return fit(tokens(s), max);
}

/** A name as the message writes it: printable, in a code span, the whole span at most NAME_CHARS (a name full of
 *  backticks needs a long fence, so the text inside is cut, on whole tokens, until the span fits). */
function name(s: string): string {
  const t = tokens(s);
  for (let max = NAME_CHARS; ; max--) {
    const span = codeSpan(fit(t, max));
    if ([...span].length <= NAME_CHARS || max <= 1) return span;
  }
}

export interface HandoverFacts {
  /** The folder handed over: a TERMINALS session's own folder, or the worktree's path. */
  folder: string;
  /** The bot's worktree that holds the folder, when there is one. */
  worktree: Pick<Worktree, "path" | "branch" | "head"> | null;
  /** That worktree's `panel.diff`, or null when it was not read (no worktree, or git could not read it). */
  diff: Pick<WorktreeDiff, "scope" | "files" | "truncated"> | null;
  /** What the person typed as the goal; empty for none. */
  goal: string;
}

/** `s` as one Markdown code span: a fence longer than any run of backticks inside it, padded when it starts or
 *  ends with one (CommonMark), so any path or branch shows exactly as written. */
export function codeSpan(s: string): string {
  const runs = s.match(/`+/g) ?? [];
  const fence = "`".repeat(Math.max(0, ...runs.map((r) => r.length)) + 1);
  const pad = s.startsWith("`") || s.endsWith("`") ? " " : "";
  return `${fence}${pad}${s}${pad}${fence}`;
}


const isWindows = (key: string) => /^[A-Za-z]:\\|^\\\\/.test(key);

/** One spelling to compare folders by: pathKey's, and case folded for a Windows path. */
const cmpKey = (path: string) => {
  const k = pathKey(path);
  return isWindows(k) ? k.toLowerCase() : k;
};

/** The deepest of `trees` that is `folder` or holds it, compared as written (nothing is looked up on disk). */
export function worktreeOf<T extends Pick<Worktree, "path">>(folder: string, trees: T[]): T | null {
  const f = cmpKey(folder);
  if (!f) return null;
  let best: T | null = null;
  let bestLen = -1;
  for (const w of trees) {
    const k = cmpKey(w.path);
    if (!k) continue;
    const sep = isWindows(k) ? "\\" : "/";
    const inside = f === k || f.startsWith(k.endsWith(sep) ? k : k + sep);
    if (inside && k.length > bestLen) {
      best = w;
      bestLen = k.length;
    }
  }
  return best;
}

/** The last part of a path, `/` or `\` separated. */
const leaf = (p: string) => pathKey(p).split(/[\\/]/).filter(Boolean).pop() ?? p;

/** One line: the folder's last part and, when known, its branch. */
export function handoverTitle(f: Pick<HandoverFacts, "folder" | "worktree">): string {
  const branch = printable(f.worktree?.branch || (f.worktree?.head ? f.worktree.head.slice(0, 7) : ""), 80);
  const base = printable(leaf(f.folder).replace(/\s+/g, " ").trim() || f.folder, 80);
  return branch ? `${base} (${branch})` : base;
}

/** The goal as one line (every run of white space, line breaks included, is one space), printable, at most
 *  GOAL_CHARS characters: it can never start a line of the message. */
export function goalLine(goal: string): string {
  return printable(goal.replace(/[\s\u2028\u2029]+/g, " ").trim(), GOAL_CHARS);
}

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/** The git lines: branch, status and diff stat, or one line saying omher read none. */
function gitLines(f: HandoverFacts): string[] {
  const w = f.worktree;
  const out: string[] = [];
  if (w && cmpKey(w.path) !== cmpKey(f.folder)) out.push(`- Worktree: ${name(w.path)}`);
  if (w) {
    const head = w.head ? ` at ${printable(w.head.slice(0, 7))}` : "";
    out.push(w.branch ? `- Branch: ${name(w.branch)}${head}` : `- Branch: detached${head}`);
  }
  if (!w || !f.diff) {
    out.push("- Git: omher did not read this folder's status; check it with `git status` and `git diff --stat` there.");
    return out;
  }
  const tracked = f.diff.files.filter((x) => !x.untracked);
  const untracked = f.diff.files.filter((x) => x.untracked);
  const add = tracked.reduce((a, x) => a + x.add, 0);
  const del = tracked.reduce((a, x) => a + x.del, 0);
  const cut = f.diff.truncated ? " (list cut)" : "";
  if (f.diff.scope === "uncommitted") {
    out.push(`- Status: ${plural(tracked.length, "changed file", "changed files")}, ${untracked.length} untracked${cut}`);
    if (tracked.length) out.push(`- Diff stat (uncommitted, vs HEAD): ${plural(tracked.length, "file", "files")}, +${add} -${del}`);
  } else {
    out.push("- Status: clean, no uncommitted changes");
    if (tracked.length) out.push(`- Last commit: ${plural(tracked.length, "file", "files")}, +${add} -${del}${cut}`);
  }
  const named = [...tracked.map((x) => `  - ${name(x.path)} +${x.add} -${x.del}`), ...untracked.map((x) => `  - ${name(x.path)} untracked`)];
  out.push(...named.slice(0, STAT_FILES));
  if (named.length > STAT_FILES) out.push(`  - and ${named.length - STAT_FILES} more`);
  return out;
}

/** The first message of the handover thread. */
export function handoverMessage(f: HandoverFacts): string {
  const parts = [
    "Handover from omher: pick up the work in this folder.",
    [`- Folder: ${name(f.folder)}`, ...gitLines(f)].join("\n"),
  ];
  const goal = goalLine(f.goal);
  if (goal) parts.push(`Goal: ${goal}`);
  parts.push("Nothing was moved or closed: the folder, its files and any terminal open in it stay as they are. Work there with your own tools.");
  return parts.join("\n\n");
}
