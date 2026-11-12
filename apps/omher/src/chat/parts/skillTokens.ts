// Skill tokens in the composer: `$name`, where `name` is one of the bot's skills (the sigil Codex uses for a
// skill). A token stands after the start of the text or whitespace and before the end, whitespace or closing
// punctuation, anywhere in the message, and never inside inline code or a fenced block. `/` is not a skill sigil
// here: `/name` is one of Hermes' own commands or a skill typed the Hermes way, and it goes out as typed, as do
// `./name` and a path. The person sees what they typed; the wire carries each token hoisted to the front as
// `/name` (OMH's router and Hermes read a skill at the start of the message, with a slash).

import type { Skill } from "../../lib/protocol";

export interface SkillToken {
  name: string;
  /** `text.slice(start, end)` is `$name`. */
  start: number;
  end: number;
}

/** Whether the character at `at` ends a token: the end of the text, whitespace, closing punctuation, or a full
 * stop that does not start a file extension ("$plan." ends a sentence; "$plan.md" is not a skill). */
const closes = (text: string, at: number) => at >= text.length || /[\s,;:!?)]/.test(text[at]) || (text[at] === "." && !/[\w/]/.test(text[at + 1] ?? ""));
const FENCE = /^ {0,3}(`{3,}|~{3,})/;

/** Ranges of `text` that are code: fenced blocks (an unclosed fence runs to the end) and inline code spans
 * (a backtick run closed by the next run of the same length; an unclosed run is a literal backtick). */
export function codeRanges(text: string): [number, number][] {
  const fences: [number, number][] = [];
  let open: { mark: string; len: number; start: number } | null = null;
  let at = 0;
  for (const line of text.split("\n")) {
    const end = at + line.length;
    const m = FENCE.exec(line);
    if (!open && m) open = { mark: m[1][0], len: m[1].length, start: at };
    else if (open && m && m[1][0] === open.mark && m[1].length >= open.len && !line.slice(m[0].length).trim()) {
      fences.push([open.start, end]);
      open = null;
    }
    at = end + 1;
  }
  if (open) fences.push([open.start, text.length]);

  const out: [number, number][] = [...fences];
  let from = 0;
  for (const [s, e] of [...fences, [text.length, text.length] as [number, number]]) {
    const runs = [...text.slice(from, s).matchAll(/`+/g)].map((r) => ({ at: from + r.index, len: r[0].length }));
    for (let i = 0; i < runs.length; i += 1) {
      const close = runs.findIndex((r, j) => j > i && r.len === runs[i].len);
      if (close < 0) continue;
      out.push([runs[i].at, runs[close].at + runs[close].len]);
      i = close;
    }
    from = e;
  }
  return out.sort((a, b) => a[0] - b[0]);
}

const inside = (ranges: [number, number][], i: number) => ranges.some(([s, e]) => i >= s && i < e);

/** What a person types before a skill's name. */
export const SIGIL = "$";

/** Every skill token in `text`, in order. Longer names win (`$plan-x` is `plan-x` when both exist). Names match
 * as written, so a shell variable in capitals (`$HOME`) is not a skill. */
export function findTokens(text: string, names: readonly string[]): SkillToken[] {
  if (!names.length || !text.includes(SIGIL)) return [];
  const byLength = [...names].filter(Boolean).sort((a, b) => b.length - a.length);
  const code = codeRanges(text);
  const out: SkillToken[] = [];
  for (let i = text.indexOf(SIGIL); i >= 0; i = text.indexOf(SIGIL, i + 1)) {
    if ((i > 0 && !/\s/.test(text[i - 1])) || inside(code, i)) continue;
    const name = byLength.find((n) => text.startsWith(n, i + 1) && closes(text, i + 1 + n.length));
    if (!name) continue;
    out.push({ name, start: i, end: i + 1 + name.length });
    i += name.length;
  }
  return out;
}

/** The text to send: each `$name` token taken out and put in front as `/name` (in order, once each). Where a
 * token was, the whitespace around it becomes one run (a line break wins). The slash words a message starts with
 * (Hermes commands, a skill typed as `/name`) stay first, as typed, and the hoisted skills follow them. Text with
 * no token comes back unchanged. */
export function toWire(text: string, names: readonly string[]): string {
  const typed = /^\s*\/[\w-]+(?:[ \t]+\/[\w-]+)*(?=\s|$)/.exec(text)?.[0] ?? "";
  const tokens = findTokens(text, names).filter((t) => t.start >= typed.length);
  if (!tokens.length) return text;
  let rest = text;
  for (const t of [...tokens].reverse()) {
    const left = rest.slice(0, t.start).replace(/\s+$/, "");
    const lws = rest.slice(left.length, t.start);
    const after = rest.slice(t.end);
    const right = after.replace(/^\s+/, "");
    const rws = after.slice(0, after.length - right.length);
    const gap = !left || !right || !rws ? "" : /\n/.test(rws) && !/\n/.test(lws) ? rws : lws;
    rest = left + gap + right;
  }
  const had = new Set(typed.split(/\s+/).filter(Boolean));
  const lead = [...new Set(tokens.map((t) => `/${t.name}`))].filter((n) => !had.has(n)).join(" ");
  const tail = rest.slice(typed.length).replace(/^[ \t]+/, "");
  return [typed.trim(), lead, tail].filter(Boolean).join(" ");
}

/** The tokens of a sent message `text`, given the skills it was sent with (a typed `/new` is not one). */
export function sentTokens(text: string, skills: readonly string[] | undefined): SkillToken[] {
  return skills?.length ? findTokens(text, skills) : [];
}

/** The `$query` the caret is typing, or null: `$` after the start or whitespace, outside code, and the caret
 * at the end of a run with no whitespace, `$`, slash or backtick. */
export function fragmentAt(text: string, caret: number): { start: number; query: string } | null {
  let k = Math.min(caret, text.length);
  const end = k;
  while (k > 0 && !/[\s$/`]/.test(text[k - 1])) k -= 1;
  const start = k - 1;
  if (start < 0 || text[start] !== SIGIL || (start > 0 && !/\s/.test(text[start - 1]))) return null;
  if (inside(codeRanges(text), start)) return null;
  return { start, query: text.slice(k, end) };
}

/** Skills whose name starts with `query` first, then those that contain it (case-insensitive, list order kept). */
export function matchSkills(skills: readonly Skill[], query: string): Skill[] {
  const q = query.toLowerCase();
  const head = skills.filter((s) => s.name.toLowerCase().startsWith(q));
  return [...head, ...skills.filter((s) => !s.name.toLowerCase().startsWith(q) && s.name.toLowerCase().includes(q))];
}

/** The row the picker opens on for `items = matchSkills(skills, query)`: the first when `query`, as written,
 * begins its name; none (-1) otherwise. A price or a shell variable is not a skill: `$5` sits inside `p5js` and
 * `$HOME` is `homeassistant` in capitals, and for those Enter must send what was typed, not put a skill in. */
export function leadRow(items: readonly Skill[], query: string): number {
  return items.length && items[0].name.startsWith(query) ? 0 : -1;
}
