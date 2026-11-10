// Skill tokens in the composer: `./name`, where `name` is one of the bot's skills. A token stands after the start
// of the text or whitespace and before the end, whitespace or closing punctuation, anywhere in the message, and
// never inside inline code or a fenced block. The person sees what they typed; the wire carries each token
// hoisted to the front as `/name` (OMH's router and Hermes read a skill sigil at the start of the message).

import type { Skill } from "../../lib/protocol";

export interface SkillToken {
  name: string;
  /** `text.slice(start, end)` is `./name`. */
  start: number;
  end: number;
}

const AFTER = /[\s.,;:!?)]/;
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

/** Every skill token in `text`, in order. Longer names win (`./plan-x` is `plan-x` when both exist). */
export function findTokens(text: string, names: readonly string[]): SkillToken[] {
  if (!names.length || !text.includes("./")) return [];
  const byLength = [...names].filter(Boolean).sort((a, b) => b.length - a.length);
  const code = codeRanges(text);
  const out: SkillToken[] = [];
  for (let i = text.indexOf("./"); i >= 0; i = text.indexOf("./", i + 1)) {
    if ((i > 0 && !/\s/.test(text[i - 1])) || inside(code, i)) continue;
    const name = byLength.find((n) => text.startsWith(n, i + 2) && (i + 2 + n.length === text.length || AFTER.test(text[i + 2 + n.length])));
    if (!name) continue;
    out.push({ name, start: i, end: i + 2 + name.length });
    i += 1 + name.length;
  }
  return out;
}

/** The text to send: each token taken out and put in front as `/name` (in order, once each). Where a token was,
 * the whitespace around it becomes one run (a line break wins). Text without a token comes back unchanged. */
export function toWire(text: string, names: readonly string[]): string {
  const tokens = findTokens(text, names);
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
  const lead = [...new Set(tokens.map((t) => t.name))].map((n) => `/${n}`).join(" ");
  return rest ? `${lead} ${rest}` : lead;
}

/** The tokens of a sent message `text`, given the `sent` wire text: the names hoisted to its front. */
export function sentTokens(text: string, sent: string | undefined): SkillToken[] {
  const lead = sent?.match(/^(?:\/\S+(?:\s+|$))+/)?.[0] ?? "";
  return lead ? findTokens(text, lead.trim().split(/\s+/).map((w) => w.slice(1))) : [];
}

/** The `./query` the caret is typing, or null: `./` after the start or whitespace, outside code, and the caret
 * at the end of a run with no whitespace, slash or backtick. */
export function fragmentAt(text: string, caret: number): { start: number; query: string } | null {
  let k = Math.min(caret, text.length);
  const end = k;
  while (k > 0 && !/[\s/`]/.test(text[k - 1])) k -= 1;
  const start = k - 2;
  if (start < 0 || text.slice(start, k) !== "./" || (start > 0 && !/\s/.test(text[start - 1]))) return null;
  if (inside(codeRanges(text), start)) return null;
  return { start, query: text.slice(k, end) };
}

/** Skills whose name starts with `query` first, then those that contain it (case-insensitive, list order kept). */
export function matchSkills(skills: readonly Skill[], query: string): Skill[] {
  const q = query.toLowerCase();
  const head = skills.filter((s) => s.name.toLowerCase().startsWith(q));
  return [...head, ...skills.filter((s) => !s.name.toLowerCase().startsWith(q) && s.name.toLowerCase().includes(q))];
}
