// "Start in thread": the thread's title and its first message, made from an issue or pull request. The text is what
// the person would paste: the item's address, title and description (cut to 4 KB), then "Work on this issue." Any
// token-like string in the title or description is masked (src/lib/secrets.ts) before it is sent.
import { maskSecrets } from "../lib/secrets";
import type { TaskDetail, TaskItem } from "./types";

/** The most bytes of the description carried into the first message. */
export const BODY_BYTES = 4096;

/** `s` cut to at most `n` UTF-8 bytes, on a character boundary, with "…" when it was cut. */
export function cutBytes(s: string, n: number): string {
  const enc = new TextEncoder();
  if (enc.encode(s).length <= n) return s;
  let out = "";
  let used = 0;
  for (const ch of s) {
    const b = enc.encode(ch).length;
    if (used + b > n - 3) break;
    out += ch;
    used += b;
  }
  // end on a word when one ends in the last fifth
  const sp = out.search(/\s\S*$/);
  if (sp > out.length * 0.8) out = out.slice(0, sp);
  return `${out.trimEnd()}…`;
}

/** `#<n> <title>`, one line. */
export const threadTitle = (item: Pick<TaskItem, "number" | "title">) => `#${item.number} ${maskSecrets(item.title).replace(/\s+/g, " ").trim()}`;

/** The first message of the thread. */
export function firstMessage(d: Pick<TaskDetail, "item" | "body">, ask = "Work on this issue."): string {
  const parts = [d.item.url, threadTitle(d.item)];
  const body = maskSecrets(d.body).replace(/\r\n?/g, "\n").trim();
  if (body) parts.push(cutBytes(body, BODY_BYTES));
  parts.push(ask);
  return parts.filter(Boolean).join("\n\n");
}
