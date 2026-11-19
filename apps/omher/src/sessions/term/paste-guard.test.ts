import { describe, expect, it } from "vitest";
import { needsConfirm, pasteLines, previewOf, PREVIEW_COLS, PREVIEW_LINES } from "./paste-guard";

describe("multi-line paste guard", () => {
  it("asks only for text with a line break, when the program has not turned bracketed paste on and the setting is on", () => {
    for (const text of ["a\nb", "a\r\nb", "a\rb", "one line\n", "x\ny\nz"]) {
      expect(needsConfirm(text, false, true), JSON.stringify(text)).toBe(true);
      expect(needsConfirm(text, true, true), JSON.stringify(text)).toBe(false); // bracketed paste: the program is safe
      expect(needsConfirm(text, false, false), JSON.stringify(text)).toBe(false); // setting off
    }
    for (const text of ["", "ls -la", "tab\tseparated", "no break at all"]) expect(needsConfirm(text, false, true), JSON.stringify(text)).toBe(false);
  });

  it("counts lines as a person sees them: a final line break ends the last line, CRLF is one break", () => {
    expect(pasteLines("a\nb\nc")).toEqual(["a", "b", "c"]);
    expect(pasteLines("a\nb\nc\n")).toEqual(["a", "b", "c"]);
    expect(pasteLines("a\r\nb\r\n")).toEqual(["a", "b"]);
    expect(pasteLines("a\rb")).toEqual(["a", "b"]);
    expect(pasteLines("one\n")).toEqual(["one"]);
    expect(pasteLines("a\n\nb")).toEqual(["a", "", "b"]);
  });

  it("previews the first lines, each cut to a width with an ellipsis, and says how many there are", () => {
    const long = "x".repeat(PREVIEW_COLS + 40);
    const p = previewOf(`echo 1\n${long}\necho 3\necho 4\necho 5\n`);
    expect(p.total).toBe(5);
    expect(p.lines).toHaveLength(PREVIEW_LINES);
    expect(p.lines[0]).toBe("echo 1");
    expect(p.lines[1]).toHaveLength(PREVIEW_COLS);
    expect(p.lines[1].endsWith("…")).toBe(true);
    expect(p.lines[2]).toBe("echo 3");
    expect(previewOf("a\nb")).toEqual({ lines: ["a", "b"], total: 2 });
  });
});
