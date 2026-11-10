// Bot mentions in chat text: `@name`, where `name` resolves to a bot omher knows (its profile slug, its display
// name, or `hermes` for the default profile, which is how agents name it). A mention stands after the start of
// the text, whitespace or punctuation, never after a letter, digit or `.`/`-`/`+`/`/` (an email `a@b.com`, a path,
// a URL), and never inside code or a link. `@file:x` and the other `@kind:value` context refs are not mentions; a
// colon followed by a space is (`@hermes: check this`). Names are ASCII, so Korean particles after a name stay
// outside it (`@kami도`). Pure: the caller passes the lookup.

export interface MentionBot {
  name: string;
  display_name: string;
  is_default?: boolean;
}

export interface Mention {
  /** The profile slug of the bot the mention opens. */
  bot: string;
  /** `text.slice(start, end)` is the `@name` as written. */
  start: number;
  end: number;
}

const slug = (s: string) => s.trim().toLowerCase().replace(/\s+/g, "-");

/** A lookup from a written name to a bot's profile slug: the slug wins, then `hermes` for the default profile,
 * then the display name (spaces as hyphens, so \"OMH TUI\" answers to `@omh-tui`). Case-insensitive. */
export function botResolver(bots: readonly MentionBot[]): (name: string) => string | null {
  const byName = new Map<string, string>();
  for (const b of bots) byName.set(b.name.toLowerCase(), b.name);
  const fallback = new Map<string, string>();
  const def = bots.find((b) => b.is_default) ?? bots.find((b) => b.name === "default");
  if (def) fallback.set("hermes", def.name);
  for (const b of bots) {
    const d = slug(b.display_name || "");
    if (d && !fallback.has(d)) fallback.set(d, b.name);
  }
  return (name) => {
    const n = name.toLowerCase();
    return byName.get(n) ?? fallback.get(n) ?? null;
  };
}

const NAME = /@([a-z0-9][a-z0-9_-]*)/gi;
/** What may not stand right before the `@`: a word character or a character that joins words in an address. */
const JOINS_BEFORE = /[\p{L}\p{N}_.+\-/@\\]/u;

/** Every mention in `text`, in order. `skip` ranges (code, as [start, end)) are left alone. */
export function findMentions(text: string, resolve: (name: string) => string | null, skip: readonly [number, number][] = []): Mention[] {
  if (!text.includes("@")) return [];
  const out: Mention[] = [];
  for (const m of text.matchAll(NAME)) {
    const at = m.index;
    if (at > 0 && JOINS_BEFORE.test(text[at - 1])) continue;
    if (skip.some(([s, e]) => at >= s && at < e)) continue;
    // a name ends on a letter or digit: `@hermes-` is `@hermes` and a hyphen
    const name = m[1].replace(/[-_]+$/, "");
    const end = at + 1 + name.length;
    const next = text[end] ?? "";
    const after = text[end + 1] ?? "";
    // `@file:src/a.ts`, `@scope/pkg`, `@host.com`, `@a@b`: a ref, a package, a domain, an address
    if ((next === ":" || next === "/") && after && !/\s/.test(after)) continue;
    if (next === "." && /[a-z0-9]/i.test(after)) continue;
    if (next === "@") continue;
    const bot = resolve(name);
    if (bot) out.push({ bot, start: at, end });
  }
  return out;
}
