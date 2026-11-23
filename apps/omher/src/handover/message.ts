// "Hand to <bot>": the thread's title and its first message, made from a folder the person hands over (a TERMINALS
// session's folder or a Worktrees row). Fixed English text, like "Start in thread" (src/tasks/message.ts): the
// folder, the branch, a short git status and diff stat when omher has them, an optional goal line, and one closing
// line saying nothing moved. The git facts come only from the bot's own Worktrees list and one `panel.diff` of a
// worktree in it (BOUNDARY.md rule 10); a folder outside them is handed with no git facts and the bot reads them
// with its own tools. Paths and branch names go in code spans, so spaces, backslashes and `_` show as written.
import { pathKey } from "../sessions/folders";
import type { Worktree, WorktreeDiff } from "../lib/protocol";

/** The most files the diff stat lists by name; the rest are counted. */
export const STAT_FILES = 20;
/** The most characters of the goal line. */
export const GOAL_CHARS = 500;

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
  const branch = f.worktree?.branch || (f.worktree?.head ? f.worktree.head.slice(0, 7) : "");
  const name = leaf(f.folder).replace(/\s+/g, " ").trim() || f.folder;
  return branch ? `${name} (${branch})` : name;
}

/** The goal as one line, at most GOAL_CHARS characters. */
export function goalLine(goal: string): string {
  const one = goal.replace(/\s+/g, " ").trim();
  const chars = [...one];
  return chars.length <= GOAL_CHARS ? one : `${chars.slice(0, GOAL_CHARS - 1).join("").trimEnd()}…`;
}

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/** The git lines: branch, status and diff stat, or one line saying omher read none. */
function gitLines(f: HandoverFacts): string[] {
  const w = f.worktree;
  const out: string[] = [];
  if (w && cmpKey(w.path) !== cmpKey(f.folder)) out.push(`- Worktree: ${codeSpan(w.path)}`);
  if (w) {
    const head = w.head ? ` at ${w.head.slice(0, 7)}` : "";
    out.push(w.branch ? `- Branch: ${codeSpan(w.branch)}${head}` : `- Branch: detached${head}`);
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
  const named = [...tracked.map((x) => `  - ${codeSpan(x.path)} +${x.add} -${x.del}`), ...untracked.map((x) => `  - ${codeSpan(x.path)} untracked`)];
  out.push(...named.slice(0, STAT_FILES));
  if (named.length > STAT_FILES) out.push(`  - and ${named.length - STAT_FILES} more`);
  return out;
}

/** The first message of the handover thread. */
export function handoverMessage(f: HandoverFacts): string {
  const parts = [
    "Handover from omher: pick up the work in this folder.",
    [`- Folder: ${codeSpan(f.folder)}`, ...gitLines(f)].join("\n"),
  ];
  const goal = goalLine(f.goal);
  if (goal) parts.push(`Goal: ${goal}`);
  parts.push("Nothing was moved or closed: the folder, its files and any terminal open in it stay as they are. Work there with your own tools.");
  return parts.join("\n\n");
}
