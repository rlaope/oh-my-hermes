// The terminal's bundled font (as Otty draws its terminal): JetBrains Mono for text, Symbols Nerd Font Mono for the
// icon glyphs prompts draw (powerline arrows, git branch, file icons). A family the person typed in Settings comes
// first and these stand behind it; Korean, Japanese and Chinese fall through to the system's own fonts.
import "./fonts.css";

export const BUNDLED_FAMILIES = ["JetBrains Mono", "Symbols Nerd Font Mono"] as const;

/** Wait no longer than this for the bundled font (a stuck load must not hold a terminal back). */
const FONT_WAIT_MS = 1500;

/** JetBrains Mono's four styles, as the CSS font shorthand writes them. */
const FACES = ["", "bold ", "italic ", "italic bold "] as const;

let ready: Promise<void> | null = null;

/** Resolves once JetBrains Mono's four styles have loaded (or could not), so a terminal made after it measures its
 *  cells and draws its first glyphs in it instead of the fallback. */
export function termFontsReady(): Promise<void> {
  if (ready) return ready;
  const fonts = typeof document !== "undefined" ? document.fonts : undefined;
  if (!fonts?.load) return (ready = Promise.resolve());
  // WebKit drops a face no element uses back to unloaded when the page's styles change (xterm's own stylesheet
  // arrives at the same moment), so bold and italic would load and then be gone before a program first prints in
  // them: that first bold or italic line would draw in the fallback. A hidden sample keeps the four in use.
  keepInUse(BUNDLED_FAMILIES[0]);
  const all = Promise.all(FACES.map((v) => fonts.load(`${v}13px "${BUNDLED_FAMILIES[0]}"`, "M"))).then(
    () => undefined,
    () => undefined,
  );
  return (ready = Promise.race([all, new Promise<void>((res) => setTimeout(res, FONT_WAIT_MS))]));
}

/** A sample of each style, laid out off screen and never painted, so the browser counts every face as in use. */
function keepInUse(family: string): void {
  if (typeof document === "undefined" || !document.body) return;
  const box = document.createElement("div");
  box.setAttribute("aria-hidden", "true");
  box.dataset.termFonts = "";
  box.style.cssText = `position:fixed;left:-9999px;top:0;visibility:hidden;pointer-events:none;font:13px "${family}"`;
  for (const v of FACES) {
    const span = document.createElement("span");
    span.style.font = `${v}13px "${family}"`;
    span.textContent = "M";
    box.appendChild(span);
  }
  document.body.appendChild(box);
}
