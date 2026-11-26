import { describe, expect, it } from "vitest";
import { cellWrappedLinks, type CellRow } from "./engine-cell-links";

// a screen from plain strings: a Hangul syllable takes two columns, as xterm lays it out
const wide = (ch: string) => /[ᄀ-ᇿ㄰-㆏가-힯]/.test(ch);
function screen(lines: string[], wrapped: number[] = []): (y: number) => CellRow | undefined {
  const rows = lines.map((line, i) => {
    const cols: string[] = [];
    for (const ch of line) cols.push(...(wide(ch) ? [ch, ""] : [ch]));
    return { cols, wrapped: wrapped.includes(i) };
  });
  // every xterm row is as wide as the terminal
  const width = Math.max(...rows.map((r) => r.cols.length));
  for (const r of rows) while (r.cols.length < width) r.cols.push(" ");
  return (y) => rows[y];
}

const PR = "https://github.com/sgl-project/sglang/pull/53061";

describe("terminal links: an address the program broke across rows", () => {
  // the reported screen: a markdown table cell 20 columns wide
  const table = [
    "│ sglang #53061        │ 설정       │",
    "│ (https://github.com/ │ Deep       │",
    "│ sgl-project/sglang/  │ Nemo       │",
    "│ pull/53061) (보강)   │ GLM        │",
    "└──────────────────────┴────────────┘",
  ];

  it("every piece of a table cell's address opens the whole address", () => {
    const row = screen(table);
    expect(cellWrappedLinks(row, 1)).toEqual([{ y: 1, start: 3, end: 22, url: PR }]);
    expect(cellWrappedLinks(row, 2)).toEqual([{ y: 2, start: 2, end: 21, url: PR }]);
    expect(cellWrappedLinks(row, 3)).toEqual([{ y: 3, start: 2, end: 12, url: PR }]);
  });

  it("the rows around it and the other cells carry no link", () => {
    const row = screen(table);
    expect(cellWrappedLinks(row, 0)).toEqual([]);
    expect(cellWrappedLinks(row, 4)).toEqual([]);
  });

  it("a paragraph the program hard-wrapped joins the same way", () => {
    // a word longer than the row is cut at the row's end, wherever it falls
    const row = screen(["see https://example.", "com/docs/a-long-path", "/more for it"]);
    const url = "https://example.com/docs/a-long-path/more";
    expect(cellWrappedLinks(row, 0)).toEqual([{ y: 0, start: 4, end: 20, url }]);
    expect(cellWrappedLinks(row, 1)).toEqual([{ y: 1, start: 0, end: 20, url }]);
    expect(cellWrappedLinks(row, 2)).toEqual([{ y: 2, start: 0, end: 5, url }]);
  });

  it("a word that would have fit on the row above is a new word, not the rest of the address", () => {
    const row = screen(["│ see https://a.com/      │", "│ and more                │"]);
    expect(cellWrappedLinks(row, 0)).toEqual([]);
    expect(cellWrappedLinks(row, 1)).toEqual([]);
  });

  it("a piece that does not end where an address breaks, with room left, stays apart", () => {
    const row = screen(["│ https://a.com/x     │", "│ yzzzzzzzzzzzzzzzzzz │"]);
    expect(cellWrappedLinks(row, 0)).toEqual([]);
  });

  it("a row below that starts at another left edge does not continue it", () => {
    const row = screen(["│ (https://github.com/ │", "│   sgl-project/sglang │"]);
    expect(cellWrappedLinks(row, 0)).toEqual([]);
  });

  it("an address on one row, or soft-wrapped by xterm itself, is left to the web-links add-on", () => {
    expect(cellWrappedLinks(screen(["│ https://github.com/x    │", "│ next                    │"]), 0)).toEqual([]);
    expect(cellWrappedLinks(screen(["see https://example.", "com/docs"], [1]), 0)).toEqual([]);
  });

  it("only http and https addresses are joined", () => {
    const row = screen(["│ (ftp://github.com/   │", "│ sgl-project/sglang/  │"]);
    expect(cellWrappedLinks(row, 0)).toEqual([]);
  });
});
