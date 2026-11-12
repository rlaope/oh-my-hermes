// How a SESSIONS terminal draws and takes its program's output: what is attached once it is on the page (the
// renderer, add-ons) and how bytes from the program reach it.
import type { Terminal } from "@xterm/xterm";
import type { TermSettings } from "./settings";

/** Called once, right after `term.open(el)`. Returns what undoes it (called before the terminal is disposed). */
export function afterOpen(_term: Terminal, _el: HTMLElement, _s: TermSettings): () => void {
  return () => undefined;
}

/** Output from the program into the terminal. `done` runs once the terminal has taken these bytes. */
export function feed(term: Terminal, data: string | Uint8Array, done?: () => void): void {
  term.write(data, done);
}

/** What draws the terminals now: the GPU renderer, the standard one, or null while no terminal is open.
 *  Settings shows it, so a person (and a check of the real window) can see which is in use. */
export function rendererInUse(): "gpu" | "standard" | null {
  return null;
}

/** A terminal came onto the page (`shown`) or left it while its program keeps running. */
export function onVisible(_term: Terminal, _shown: boolean): void {
  /* nothing to release or restore yet */
}
