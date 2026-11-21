// Display-only reading of a clarify choice, and the digit keys that pick one. The answer sent back to Hermes is
// always the original choice string; nothing here changes it.
import { composing } from "../../lib/ime";

export interface ParsedChoice {
  title: string;
  /** Text after the first " — ", shown dimmer under the title; empty when there is none. */
  desc: string;
  /** The choice ended in "(Recommended)" or "(권장)"; the marker is cut from the text and shown as a badge. */
  recommended: boolean;
}

const BADGE = /\s*\((?:Recommended|권장)\)$/i;

export function parseChoice(raw: string): ParsedChoice {
  let text = raw.trim();
  let recommended = false;
  const stripped = text.replace(BADGE, "");
  if (stripped && stripped !== text) {
    text = stripped;
    recommended = true;
  }
  text = text.replace(/ —$/, "");
  const at = text.indexOf(" — ");
  if (at <= 0) return { title: text, desc: "", recommended };
  return { title: text.slice(0, at).trim(), desc: text.slice(at + 3).trim(), recommended };
}

interface DigitKey {
  key: string;
  metaKey?: boolean;
  ctrlKey?: boolean;
  altKey?: boolean;
  shiftKey?: boolean;
  repeat?: boolean;
  isComposing?: boolean;
  keyCode?: number;
  nativeEvent?: { isComposing?: boolean };
  target?: EventTarget | { tagName?: string; isContentEditable?: boolean } | null;
}

/** The 0-based row a digit key picks among `count` numbered rows, or -1 when the key is not a pick: a modifier
 *  is down, the key auto-repeats, an input method composes, the focus is in a text field, or the digit has no row. */
export function choiceIndexForKey(e: DigitKey, count: number): number {
  if (e.metaKey || e.ctrlKey || e.altKey || e.shiftKey || e.repeat || composing(e)) return -1;
  const el = e.target as { tagName?: string; isContentEditable?: boolean } | null | undefined;
  const tag = el?.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || el?.isContentEditable) return -1;
  if (!/^[1-9]$/.test(e.key)) return -1;
  const i = Number(e.key) - 1;
  return i < count ? i : -1;
}
