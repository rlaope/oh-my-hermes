// A file's diff lines (DiffFile.lines: `+`, `-`, ` ` or `@@`) as rows with their old and new line numbers, for the
// diff view's two gutters. A hunk header `@@ -a,b +c,d @@` (a count may be left out: `@@ -3 +3 @@`) starts the old
// side at a and the new side at c; a context line has both numbers and advances both, a `-` line only the old one, a
// `+` line only the new one. Lines under a header that carries no numbers (an edit made from a tool's input, whose
// place in the file is unknown, joins its parts with a bare `@@`), and `\ No newline at end of file`, have none.

export type DiffKind = "hunk" | "add" | "del" | "ctx";

export interface DiffRow {
  kind: DiffKind;
  /** The line's text, without its `+` / `-` / ` ` mark ("" for a hunk header). */
  text: string;
  old?: number;
  new?: number;
}

const HUNK = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/;

export function diffRows(lines: readonly string[]): DiffRow[] {
  let o: number | null = null;
  let n: number | null = null;
  return lines.map((l): DiffRow => {
    if (l.startsWith("@@")) {
      const m = HUNK.exec(l);
      o = m ? Number(m[1]) : null;
      n = m ? Number(m[2]) : null;
      return { kind: "hunk", text: "" };
    }
    const kind: DiffKind = l[0] === "+" ? "add" : l[0] === "-" ? "del" : "ctx";
    const text = l.slice(1);
    if (l[0] === "\\") return { kind, text };
    const row: DiffRow = { kind, text };
    if (kind !== "add" && o !== null) row.old = o++;
    if (kind !== "del" && n !== null) row.new = n++;
    return row;
  });
}

/** The gutter's width in characters: the longest number any row carries (0 when no row has one). */
export function gutterWidth(rows: readonly DiffRow[]): number {
  let w = 0;
  for (const r of rows) w = Math.max(w, String(r.old ?? "").length, String(r.new ?? "").length);
  return w;
}
