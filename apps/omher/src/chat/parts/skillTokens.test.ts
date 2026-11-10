import { describe, expect, it } from "vitest";
import { codeRanges, findTokens, fragmentAt, matchSkills, sentTokens, toWire } from "./skillTokens";

const NAMES = ["plan", "review", "plan-x"];
const names = (text: string) => findTokens(text, NAMES).map((t) => t.name);

describe("findTokens", () => {
  it("finds a token at the start, in the middle and at the end, with its range", () => {
    expect(findTokens("./plan this", NAMES)).toEqual([{ name: "plan", start: 0, end: 6 }]);
    expect(findTokens("fix this ./plan now", NAMES)).toEqual([{ name: "plan", start: 9, end: 15 }]);
    expect(names("then ./review")).toEqual(["review"]);
    expect(names("line one\n./plan\nline two")).toEqual(["plan"]);
  });

  it("finds several tokens, and the longer name wins", () => {
    expect(names("./plan it, then ./review it")).toEqual(["plan", "review"]);
    expect(names("./plan-x and ./plan")).toEqual(["plan-x", "plan"]);
  });

  it("allows closing punctuation after a token, never a slash or a word character", () => {
    for (const p of [".", ",", ";", ":", "!", "?", ")"]) expect(names(`use ./plan${p} ok`), p).toEqual(["plan"]);
    expect(names("(./plan)")).toEqual([]); // "(" before is not whitespace
    expect(names("open ./src/app.ts")).toEqual([]);
    expect(names("./plan/x")).toEqual([]);
    expect(names("./planning")).toEqual([]);
    expect(names("./plan_b")).toEqual([]);
    expect(names("./plan-y")).toEqual([]);
  });

  it("needs the start or whitespace before ./", () => {
    expect(names("x./plan")).toEqual([]);
    expect(names("../plan")).toEqual([]);
    expect(names("a\t./plan")).toEqual(["plan"]);
  });

  it("ignores unknown names and an empty list", () => {
    expect(names("./deploy now")).toEqual([]);
    expect(findTokens("./plan", [])).toEqual([]);
  });

  it("is not a token inside inline code or a fenced block", () => {
    expect(names("run `./plan` here")).toEqual([]);
    expect(names("run `` a ./plan b `` here ./review")).toEqual(["review"]);
    expect(names("```\n./plan\n```\n./review")).toEqual(["review"]);
    expect(names("~~~sh\n./plan\n~~~")).toEqual([]);
    expect(names("```\n./plan never closed")).toEqual([]);
    // an unclosed backtick is a literal backtick
    expect(names("a ` b ./plan")).toEqual(["plan"]);
  });
});

describe("codeRanges", () => {
  it("covers fences and spans, not the text between", () => {
    const text = "a `x` b\n```\ncode\n```\nc";
    const r = codeRanges(text);
    expect(r.map(([s, e]) => text.slice(s, e))).toEqual(["`x`", "```\ncode\n```"]);
  });
});

describe("toWire", () => {
  it("sends a message without a token byte for byte", () => {
    for (const t of ["hello", "  spaced  out ", "/plan as typed", "open ./src/app.ts", "`./plan`", "./planning"])
      expect(toWire(t, NAMES)).toBe(t);
  });

  it("hoists a mid-message token to the front and closes the gap", () => {
    expect(toWire("fix this ./plan now", NAMES)).toBe("/plan fix this now");
    expect(toWire("./plan fix this", NAMES)).toBe("/plan fix this");
    expect(toWire("fix this ./plan", NAMES)).toBe("/plan fix this");
    expect(toWire("./plan", NAMES)).toBe("/plan");
  });

  it("hoists several tokens in the order they appear, once each", () => {
    expect(toWire("look ./review then ./plan it", NAMES)).toBe("/review /plan look then it");
    expect(toWire("./plan a ./plan b", NAMES)).toBe("/plan a b");
  });

  it("keeps punctuation and line breaks around a removed token", () => {
    expect(toWire("please ./plan.", NAMES)).toBe("/plan please.");
    expect(toWire("use ./plan, then go", NAMES)).toBe("/plan use, then go");
    expect(toWire("one\n./plan\ntwo", NAMES)).toBe("/plan one\ntwo");
    expect(toWire("one ./plan\ntwo", NAMES)).toBe("/plan one\ntwo");
  });

  it("leaves code and paths where they are", () => {
    expect(toWire("run `./plan` with ./review on ./src/x", NAMES)).toBe("/review run `./plan` with on ./src/x");
  });
});

describe("sentTokens", () => {
  it("reads the hoisted names back from the wire text", () => {
    expect(sentTokens("fix ./plan now", "/plan fix now").map((t) => t.name)).toEqual(["plan"]);
    expect(sentTokens("hello", undefined)).toEqual([]);
    // a leading /skill the person typed is not drawn as a ./ token
    expect(sentTokens("/review ./plan x", "/plan /review x").map((t) => t.name)).toEqual(["plan"]);
  });
});

describe("fragmentAt", () => {
  it("finds the ./ being typed at the caret, anywhere in the text", () => {
    expect(fragmentAt("./", 2)).toEqual({ start: 0, query: "" });
    expect(fragmentAt("fix this ./pl", 13)).toEqual({ start: 9, query: "pl" });
    expect(fragmentAt("fix ./pl now", 8)).toEqual({ start: 4, query: "pl" });
  });

  it("is nothing after a space, inside a word, in a path or in code", () => {
    expect(fragmentAt("fix ./plan ", 11)).toBeNull();
    expect(fragmentAt("x./pl", 5)).toBeNull();
    expect(fragmentAt("./src/a", 7)).toBeNull();
    expect(fragmentAt("`./pl`", 5)).toBeNull();
    expect(fragmentAt("```\n./pl", 8)).toBeNull();
    expect(fragmentAt("plain", 5)).toBeNull();
    expect(fragmentAt("", 12)).toBeNull(); // a caret left over from longer text
    expect(fragmentAt("./pl", 9)).toEqual({ start: 0, query: "pl" });
  });
});

describe("matchSkills", () => {
  const skills = ["deploy", "plan", "review", "unplanned"].map((name) => ({ name, description: "" }));
  it("puts prefix matches first, then substring matches", () => {
    expect(matchSkills(skills, "pl").map((s) => s.name)).toEqual(["plan", "deploy", "unplanned"]);
    expect(matchSkills(skills, "").map((s) => s.name)).toEqual(["deploy", "plan", "review", "unplanned"]);
    expect(matchSkills(skills, "PL").map((s) => s.name)).toEqual(["plan", "deploy", "unplanned"]);
    expect(matchSkills(skills, "zz")).toEqual([]);
  });
});
