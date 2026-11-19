// A TERMINALS session's link: `omher://terminal/<link id>`. The id is 10 characters of lowercase base32 (a-z, 2-7),
// drawn at random when the session is made and kept in its record (a session saved before links existed gets one
// when it comes back), so the link stays the same across restarts. These helpers are pure: no store, no clipboard.
// The shell (src-tauri/src/term_link.rs) checks a link the same way before it hands one to the page.

export const LINK_ID_LEN = 10;
const ALPHABET = "abcdefghijklmnopqrstuvwxyz234567";
const ID = /^[a-z2-7]{10}$/;
const LINK = /^omher:\/\/terminal\/([a-z2-7]{10})\/?$/;
/** A link inside text: not glued to a letter or digit on either side. */
const IN_TEXT = /omher:\/\/terminal\/[a-z2-7]{10}(?![a-z0-9])/gi;

/** A fresh link id. `random` fills the bytes (crypto.getRandomValues by default; tests pass their own). */
export function newLinkId(random: (b: Uint8Array<ArrayBuffer>) => Uint8Array = (b) => crypto.getRandomValues(b)): string {
  const bytes = random(new Uint8Array(LINK_ID_LEN));
  let out = "";
  // 256 is a multiple of 32: each byte's low five bits are uniform
  for (let i = 0; i < LINK_ID_LEN; i++) out += ALPHABET[bytes[i]! & 31];
  return out;
}

export const isLinkId = (v: unknown): v is string => typeof v === "string" && ID.test(v);

/** `omher://terminal/<id>`. */
export const termLinkUrl = (id: string): string => `omher://terminal/${id}`;

/** The link id in `url` when it is a terminal link (one trailing slash allowed, nothing else around it), else null. */
export function parseTermLink(url: string | null | undefined): string | null {
  if (typeof url !== "string") return null;
  const m = LINK.exec(url.trim());
  return m ? m[1]! : null;
}

/** The terminal links in plain text, with where each sits. Upper case in the id is not a link (ids are lower case). */
export function findTermLinks(text: string): { url: string; id: string; start: number; end: number }[] {
  const out: { url: string; id: string; start: number; end: number }[] = [];
  if (!text.includes("omher://")) return out;
  IN_TEXT.lastIndex = 0;
  for (let m = IN_TEXT.exec(text); m; m = IN_TEXT.exec(text)) {
    const id = parseTermLink(m[0]);
    if (!id) continue;
    // a letter or digit right before it makes it part of another word
    if (m.index > 0 && /[a-z0-9]/i.test(text[m.index - 1]!)) continue;
    out.push({ url: m[0], id, start: m.index, end: m.index + m[0].length });
  }
  return out;
}

type KeyLike = { key: string; code?: string; metaKey: boolean; ctrlKey: boolean; altKey: boolean; shiftKey: boolean };

/** Copy link in a TERMINALS terminal: ⌘⇧C on macOS; Alt+Shift+C elsewhere (Ctrl+Shift+C is a terminal's own copy
 *  there). The key where C stands counts on a non-Latin layout. */
export function isCopyLinkKey(e: KeyLike, mac: boolean): boolean {
  const c = e.key.toLowerCase() === "c" || (!/^[a-z]$/i.test(e.key) && e.code === "KeyC");
  if (!c || !e.shiftKey) return false;
  return mac ? e.metaKey && !e.ctrlKey && !e.altKey : e.altKey && !e.ctrlKey && !e.metaKey;
}

/** The page-wide event a copied link sends (detail: the session id), so the terminal showing it can say so. */
export const LINK_COPIED_EVENT = "omher-term-link-copied";
