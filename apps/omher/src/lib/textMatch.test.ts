// textMatch.ts: the list searches' one rule, case ignored and Unicode compared composed (NFC).
import { describe, expect, it } from "vitest";
import { matchesSearch, searchKey } from "./textMatch";

describe("searchKey / matchesSearch", () => {
  const word = "보고서";
  const nfd = word.normalize("NFD");

  it("matches a Korean name typed composed against one a shell reported decomposed, and the other way", () => {
    expect(nfd).not.toBe(word);
    expect(matchesSearch(searchKey(word), `/Users/you/${nfd}`)).toBe(true);
    expect(matchesSearch(searchKey(nfd), `/Users/you/${word}`)).toBe(true);
    expect(matchesSearch(searchKey("보고"), nfd)).toBe(true);
    expect(matchesSearch(searchKey("보고서2"), nfd)).toBe(false);
  });

  it("ignores case as before, in either form of an accented letter", () => {
    expect(matchesSearch(searchKey("CAFÉ"), "Café notes")).toBe(true);
    expect(matchesSearch(searchKey("café"), "CAFÉ")).toBe(true);
    expect(matchesSearch(searchKey("Web-App"), "/home/you/code/web-app")).toBe(true);
    // a capital that lower-cases into a letter and a mark is composed again
    expect(searchKey("İ")).toBe("i̇".normalize("NFC"));
  });

  it("an empty needle matches everything; a missing field matches nothing", () => {
    expect(matchesSearch("", null)).toBe(true);
    expect(matchesSearch("a", null, undefined, "")).toBe(false);
    expect(matchesSearch("b", undefined, "abc")).toBe(true);
  });
});
