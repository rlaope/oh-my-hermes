import { describe, expect, it } from "vitest";
import { diffRows, gutterWidth } from "./diffLines";

const nums = (lines: string[]) => diffRows(lines).map((r) => [r.kind, r.old ?? null, r.new ?? null, r.text]);

describe("diff line numbers", () => {
  it("a hunk header starts both sides; context advances both, - the old side, + the new side", () => {
    expect(nums(["@@ -5,4 +5,5 @@", " a", "-b", "+B", "+B2", " c"])).toEqual([
      ["hunk", null, null, ""],
      ["ctx", 5, 5, "a"],
      ["del", 6, null, "b"],
      ["add", null, 6, "B"],
      ["add", null, 7, "B2"],
      ["ctx", 7, 8, "c"],
    ]);
  });

  it("a header with its counts left out, and a second hunk that starts over", () => {
    expect(nums(["@@ -3 +3 @@", "-x", "+y", "@@ -40,2 +40,3 @@ def f():", " p", "+q", " r"])).toEqual([
      ["hunk", null, null, ""],
      ["del", 3, null, "x"],
      ["add", null, 3, "y"],
      ["hunk", null, null, ""],
      ["ctx", 40, 40, "p"],
      ["add", null, 41, "q"],
      ["ctx", 41, 42, "r"],
    ]);
  });

  it("a new file counts from line 1 on the new side only", () => {
    expect(nums(["@@ -0,0 +1,2 @@", "+one", "+two"])).toEqual([
      ["hunk", null, null, ""],
      ["add", null, 1, "one"],
      ["add", null, 2, "two"],
    ]);
  });

  it("no numbers where the place is unknown: no header, a bare @@, the no-newline note", () => {
    expect(nums(["-a", "+b", "@@", "-c", "+d"])).toEqual([
      ["del", null, null, "a"],
      ["add", null, null, "b"],
      ["hunk", null, null, ""],
      ["del", null, null, "c"],
      ["add", null, null, "d"],
    ]);
    expect(nums(["@@ -1 +1 @@", "-a", "\\ No newline at end of file", "+a"])).toEqual([
      ["hunk", null, null, ""],
      ["del", 1, null, "a"],
      ["note", null, null, "No newline at end of file"],
      ["add", null, 1, "a"],
    ]);
    // the note advances neither side: the context line after it keeps counting from where the file left off
    expect(nums(["@@ -4,2 +4,2 @@", "-x", "\\ No newline at end of file", "+y", "\\ No newline at end of file"]).map((r) => r[0])).toEqual([
      "hunk",
      "del",
      "note",
      "add",
      "note",
    ]);
    expect(nums(["@@ -4,3 +4,3 @@", " a", "\\ No newline at end of file", " b"])).toEqual([
      ["hunk", null, null, ""],
      ["ctx", 4, 4, "a"],
      ["note", null, null, "No newline at end of file"],
      ["ctx", 5, 5, "b"],
    ]);
  });

  it("the gutter is as wide as the longest number, none without numbers", () => {
    expect(gutterWidth(diffRows(["@@ -98,3 +98,4 @@", " a", " b", "+c", " d"]))).toBe(3);
    expect(gutterWidth(diffRows(["+a", "-b"]))).toBe(0);
  });
});
