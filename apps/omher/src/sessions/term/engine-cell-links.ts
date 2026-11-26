// An address a program broke across rows itself. A table cell or a hard-wrapped paragraph (Claude Code's markdown
// tables, Ink's wrapping) prints `https://github.com/` on one row and `sgl-project/sglang/` under it with a real
// newline between, so the row is not "wrapped" in xterm's sense and the web-links add-on, which only joins
// soft-wrapped rows, links the first piece alone: Cmd+click opened github.com. This finds such an address by
// reading the pieces back together, one cell (the columns between two borders) at a time, and links each piece to
// the whole address. Two rows join only when the piece above ends where an address can break, the piece below
// starts at the same left edge, and the piece below could not have fit on the row above, so the program must have
// broken it there; a word that would have fit is a new word, not the rest of the address.

/** One row, one entry per column: the cell's text, "" for the right half of a wide character. */
export interface CellRow {
  cols: readonly string[];
  /** xterm's own soft wrap: the web-links add-on already joins these rows. */
  wrapped: boolean;
}

/** One piece of a joined address on one row, columns 0-based and end-exclusive, and the whole address. */
export interface CellLink {
  y: number;
  start: number;
  end: number;
  url: string;
}

const BORDERS = new Set(["│", "┃", "║", "|"]);
// the web-links add-on's own pattern, so a joined address ends where an unbroken one would
const URL_RE = /(https?|HTTPS?):[/]{2}[^\s"'!*(){}|\\^<>`]*[^\s"':,.!?{}|\\^~[\]`()<>]/g;
const BREAKS_AFTER = /[/\-_.?=&#%+~:@]$/;
const MAX_ROWS = 30;

interface Seg {
  start: number;
  end: number;
  bordered: boolean;
}
interface Tok {
  start: number;
  end: number;
  text: string;
}

const blank = (c: string | undefined) => c === undefined || c === " " || c === " ";

function segments(cols: readonly string[]): Seg[] {
  const out: Seg[] = [];
  let s = 0;
  for (let x = 0; x <= cols.length; x++) {
    if (x < cols.length && !BORDERS.has(cols[x])) continue;
    if (x > s) out.push({ start: s, end: x, bordered: x < cols.length });
    s = x + 1;
  }
  return out;
}

function tokens(cols: readonly string[], seg: Seg): Tok[] {
  const out: Tok[] = [];
  let cur: Tok | null = null;
  for (let x = seg.start; x < seg.end; x++) {
    if (blank(cols[x])) {
      if (cur) out.push(cur);
      cur = null;
    } else if (cur) {
      cur.end = x + 1;
      cur.text += cols[x];
    } else {
      cur = { start: x, end: x + 1, text: cols[x] };
    }
  }
  if (cur) out.push(cur);
  return out;
}

const sameSeg = (cols: readonly string[], seg: Seg) => segments(cols).find((s) => s.start === seg.start && s.end === seg.end);

/** Does the cell `seg` on row `y` carry on into the same cell on row `y + 1`? */
function joins(row: (y: number) => CellRow | undefined, y: number, seg: Seg): boolean {
  const up = row(y);
  const down = row(y + 1);
  if (!up || !down || down.wrapped || !sameSeg(up.cols, seg) || !sameSeg(down.cols, seg)) return false;
  const upToks = tokens(up.cols, seg);
  const downToks = tokens(down.cols, seg);
  if (!upToks.length || !downToks.length) return false;
  const last = upToks[upToks.length - 1];
  const first = downToks[0];
  if (first.start !== upToks[0].start) return false;
  const room = seg.end - last.end - (seg.bordered ? 1 : 0);
  if (first.end - first.start + 1 <= room) return false; // it fit after a space: a new word
  return BREAKS_AFTER.test(last.text) || room <= 0;
}

/** The pieces of one joined run that starts with the last token of `seg` on row `top`. */
function run(row: (y: number) => CellRow | undefined, top: number, seg: Seg): { y: number; tok: Tok }[] {
  const head = tokens(row(top)!.cols, seg);
  const pieces = [{ y: top, tok: head[head.length - 1] }];
  for (let y = top; pieces.length < MAX_ROWS && joins(row, y, seg); y++) {
    const toks = tokens(row(y + 1)!.cols, seg);
    pieces.push({ y: y + 1, tok: toks[0] });
    if (toks.length > 1) break; // the address ended on this row
  }
  return pieces;
}

function linksOfRun(row: (y: number) => CellRow | undefined, pieces: { y: number; tok: Tok }[], y: number): CellLink[] {
  if (pieces.length < 2) return [];
  let text = "";
  const at: { y: number; x: number; piece: number }[] = [];
  pieces.forEach((p, i) => {
    const cols = row(p.y)!.cols;
    for (let x = p.tok.start; x < p.tok.end; x++) {
      for (const ch of cols[x]) {
        text += ch;
        at.push({ y: p.y, x, piece: i });
      }
    }
  });
  const out: CellLink[] = [];
  for (const m of text.matchAll(URL_RE)) {
    const from = m.index;
    const to = from + m[0].length - 1;
    if (at[from].piece === at[to].piece) continue; // on one row: the add-on links it
    const mine = at.slice(from, to + 1).filter((c) => c.y === y);
    if (!mine.length) continue;
    out.push({ y, start: mine[0].x, end: mine[mine.length - 1].x + 1, url: m[0] });
  }
  return out;
}

/** The address pieces on row `y` (0-based) that belong to an address the program broke across rows. */
export function cellWrappedLinks(row: (y: number) => CellRow | undefined, y: number): CellLink[] {
  const here = row(y);
  if (!here) return [];
  const out: CellLink[] = [];
  for (const seg of segments(here.cols)) {
    const toks = tokens(here.cols, seg);
    if (!toks.length) continue;
    let top = y;
    while (top > y - MAX_ROWS && top > 0 && joins(row, top - 1, seg)) top--;
    if (top < y) out.push(...linksOfRun(row, run(row, top, seg), y));
    // a run that starts on this row: unless this row's only token was the tail of the run above
    if (top === y || toks.length > 1) out.push(...linksOfRun(row, run(row, y, seg), y));
  }
  return out;
}
