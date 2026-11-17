// The terminal's bundled font (as Otty draws its terminal): JetBrains Mono for text, Symbols Nerd Font Mono for the
// icon glyphs prompts draw (powerline arrows, git branch, file icons). A family the person typed in Settings comes
// first and these stand behind it; Korean, Japanese and Chinese fall through to the system's own fonts.
import "./fonts.css";

export const BUNDLED_FAMILIES = ["JetBrains Mono", "Symbols Nerd Font Mono"] as const;

/** Wait no longer than this for the bundled font (a stuck load must not hold a terminal back). */
const FONT_WAIT_MS = 1500;

let ready: Promise<void> | null = null;

/** Resolves once JetBrains Mono's four styles have loaded (or could not), so a terminal made after it measures its
 *  cells and draws its first glyphs in it instead of the fallback. */
export function termFontsReady(): Promise<void> {
  if (ready) return ready;
  const fonts = typeof document !== "undefined" ? document.fonts : undefined;
  if (!fonts?.load) return (ready = Promise.resolve());
  const all = Promise.all(["", "bold ", "italic ", "italic bold "].map((v) => fonts.load(`${v}13px "${BUNDLED_FAMILIES[0]}"`))).then(
    () => undefined,
    () => undefined,
  );
  return (ready = Promise.race([all, new Promise<void>((res) => setTimeout(res, FONT_WAIT_MS))]));
}
