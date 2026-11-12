// What the terminal preview in Settings shows: a short stretch of ordinary program output that uses a prompt, bold
// and dim text, all eight normal and all eight bright ANSI colours, and one stretch of selected text. It is
// program output, so it reads the same in every language.
const ESC = "\x1b[";
const sgr = (code: string, text: string) => `${ESC}${code}m${text}${ESC}0m`;
const PROMPT = `${sgr("35", "❯")} `;
const blocks = (base: number) => Array.from({ length: 8 }, (_, i) => `${ESC}${base + i}m   `).join("") + `${ESC}0m`;

const SELECTED = "src/theme.ts";
const LINES = [
  `${sgr("1;34", "~/code/web-app")} ${sgr("32", "main")} ${sgr("2", "2 ahead")}`,
  `${PROMPT}git status --short`,
  ` ${sgr("31", "M")} src/app.ts`,
  `${sgr("32", "A")}  ${SELECTED}`,
  `${sgr("36", "??")} notes.md`,
  `${PROMPT}pnpm test`,
  ` ${sgr("32", "✓")} 42 passed  ${sgr("31", "✗")} 1 failed  ${sgr("33", "○")} 2 skipped  ${sgr("2", "1.2s")}`,
  blocks(40),
  blocks(100),
];

/** The widest line, in cells: narrower than this and the lines wrap. */
export const SAMPLE_COLS = 48;
/** Rows the preview needs: the lines above and the prompt the cursor waits on. */
export const SAMPLE_ROWS = LINES.length + 1;
/** The cells to show selected, as `term.select(col, row, length)` takes them. */
export const SAMPLE_SELECT = { col: 3, row: 3, length: SELECTED.length } as const;

/** The bytes to write into a fresh terminal. */
export const termSample = (): string => `${LINES.join("\r\n")}\r\n${PROMPT}`;
