// What the terminal preview in Settings shows: a short stretch of ordinary program output that uses a prompt, bold
// and dim text, all eight normal and all eight bright ANSI colours, and one stretch of selected text. It is
// program output, so it reads the same in every language. A preview wide enough for it shows a second pane beside
// the first (a server's request log, as in a split terminal), so a wide box is not two thirds empty.
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

/** The second pane, shown from `SAMPLE_WIDE_COLS` columns: one line beside each line above. */
const at = (time: string) => sgr("2", time);
const req = (time: string, verb: string, path: string, code: string, status: number, ms: string) => `${at(time)} ${sgr("36", verb.padEnd(4))} ${path.padEnd(13)} ${sgr(code, String(status))} ${sgr("2", ms.padStart(6))}`;
const SIDE = [
  `${sgr("32", "●")} ${sgr("1", "api-server")} ${sgr("2", "listening on :8080")}`,
  req("14:02:11", "GET", "/health", "32", 200, "3 ms"),
  req("14:02:12", "POST", "/sessions", "32", 201, "18 ms"),
  req("14:02:14", "GET", "/sessions/7", "33", 404, "2 ms"),
  req("14:02:15", "PUT", "/sessions/7", "31", 500, "41 ms"),
  `${at("14:02:15")} ${sgr("1;31", "error")} ECONNRESET, ${sgr("33", "retry 1 of 3")}`,
  req("14:02:16", "PUT", "/sessions/7", "32", 200, "22 ms"),
  `${at("14:02:19")} ${sgr("33", "warn")}  slow query ${sgr("35", "212 ms")}`,
  `${at("14:02:20")} ${sgr("34", "info")}  3 files changed, ${sgr("32", "reloaded")}`,
];
/** The column (1-based) the second pane's divider stands in. */
const SIDE_AT = 51;
const side = (text: string) => `${ESC}${SIDE_AT}G${sgr("2", "│")} ${text}`;

/** The widest line, in cells: narrower than this and the lines wrap. */
export const SAMPLE_COLS = 48;
/** From this many columns the second pane fits beside the first (its widest line ends in this column). */
export const SAMPLE_WIDE_COLS = 92;
/** Rows the preview needs: the lines above and the prompt the cursor waits on. */
export const SAMPLE_ROWS = LINES.length + 1;
/** The cells to show selected, as `term.select(col, row, length)` takes them. */
export const SAMPLE_SELECT = { col: 3, row: 3, length: SELECTED.length } as const;

/** The bytes to write into a fresh terminal of `cols` columns. The cursor ends on the prompt in both layouts. */
export function termSample(cols: number = SAMPLE_COLS): string {
  if (cols < SAMPLE_WIDE_COLS) return `${LINES.join("\r\n")}\r\n${PROMPT}`;
  // the divider runs down the prompt's row too; the cursor goes back to the prompt (save, draw, restore)
  return `${LINES.map((l, i) => l + side(SIDE[i])).join("\r\n")}\r\n${PROMPT}\x1b7${ESC}${SIDE_AT}G${sgr("2", "│")}\x1b8`;
}
