import { describe, expect, it } from "vitest";
import { codeRanges, findTokens, fragmentAt, leadRow, matchSkills, sentTokens, toWire } from "./skillTokens";

const NAMES = ["plan", "review", "plan-x"];
const names = (text: string) => findTokens(text, NAMES).map((t) => t.name);

describe("findTokens", () => {
  it("finds a token at the start, in the middle and at the end, with its range", () => {
    expect(findTokens("$plan this", NAMES)).toEqual([{ name: "plan", start: 0, end: 5 }]);
    expect(findTokens("fix this $plan now", NAMES)).toEqual([{ name: "plan", start: 9, end: 14 }]);
    expect(names("then $review")).toEqual(["review"]);
    expect(names("line one\n$plan\nline two")).toEqual(["plan"]);
  });

  it("finds several tokens, and the longer name wins", () => {
    expect(names("$plan it, then $review it")).toEqual(["plan", "review"]);
    expect(names("$plan-x and $plan")).toEqual(["plan-x", "plan"]);
  });

  it("allows closing punctuation after a token, never a slash or a word character", () => {
    for (const p of [".", ",", ";", ":", "!", "?", ")"]) expect(names(`use $plan${p} ok`), p).toEqual(["plan"]);
    expect(names("($plan)")).toEqual([]); // "(" before is not whitespace
    expect(names("open $plan/x")).toEqual([]);
    expect(names("$planning")).toEqual([]);
    expect(names("$plan_b")).toEqual([]);
    expect(names("$plan-y")).toEqual([]);
  });

  it("a full stop ends a token only when no extension follows", () => {
    expect(names("open $plan.md and $review.sh")).toEqual([]);
    expect(names("see $plan.test.ts")).toEqual([]);
    expect(names("then $plan. Next")).toEqual(["plan"]);
    expect(names("then $plan.")).toEqual(["plan"]);
    expect(names("then $plan...")).toEqual(["plan"]);
    expect(toWire("open $plan.md and $review.sh", NAMES)).toBe("open $plan.md and $review.sh");
  });

  it("a slash is not the skill sigil: /name, ./name and paths are plain text wherever they stand", () => {
    for (const t of ["/plan", "fix this /plan now", "then /review", "./plan", "fix this ./plan now", "../plan", "and/or", "https://x/plan", "src/plan"])
      expect(names(t), t).toEqual([]);
    expect(names("/plan and $review")).toEqual(["review"]);
  });

  it("is never a token when the $ follows a non-space character, or when the name is in other letter case", () => {
    for (const t of ["x$plan", "US$plan", "$$plan", "a.$review", "$PLAN", "echo $Plan", "costs $20", "echo $HOME"]) expect(names(t), t).toEqual([]);
    expect(findTokens("echo $HOME", ["home"])).toEqual([]);
    expect(names("a\t$plan")).toEqual(["plan"]);
  });

  it("ignores unknown names and an empty list", () => {
    expect(names("$deploy now")).toEqual([]);
    expect(findTokens("$plan", [])).toEqual([]);
  });

  it("is not a token inside inline code or a fenced block", () => {
    expect(names("run `$plan` here")).toEqual([]);
    expect(names("run `` a $plan b `` here $review")).toEqual(["review"]);
    expect(names("```\n$plan\n```\n$review")).toEqual(["review"]);
    expect(names("~~~sh\n$plan\n~~~")).toEqual([]);
    expect(names("```\n$plan never closed")).toEqual([]);
    // an unclosed backtick is a literal backtick
    expect(names("a ` b $plan")).toEqual(["plan"]);
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
    for (const t of ["hello", "  spaced  out ", "open /src/app.ts", "`$plan`", "$planning", "/tmp/x is full", "see https://x/plan", "costs $20", "echo $HOME", "a$plan"])
      expect(toWire(t, NAMES)).toBe(t);
  });

  it("sends /name and ./name byte for byte, at the start or in the middle: no hoisting", () => {
    for (const t of ["/plan", "fix this /plan now", "then /review", "./plan", "fix this ./plan now", "  ./review ./plan  ", "open ./plan.md"])
      expect(toWire(t, NAMES)).toBe(t);
  });

  it("sends Hermes' own commands, and a skill typed the Hermes way, byte for byte", () => {
    for (const t of ["/new", "/help", "/model x", "/model  claude-opus ", "/plan as typed", " /review  now", "/dag-ulw add dark mode"]) expect(toWire(t, NAMES)).toBe(t);
  });

  it("hoists a $name token to the front as /name and closes the gap", () => {
    expect(toWire("fix this $plan now", NAMES)).toBe("/plan fix this now");
    expect(toWire("fix this $plan", NAMES)).toBe("/plan fix this");
    expect(toWire("$plan", NAMES)).toBe("/plan");
    expect(toWire("$plan fix it", NAMES)).toBe("/plan fix it");
  });

  it("hoists several tokens in the order they appear, once each", () => {
    expect(toWire("look $review then $plan it", NAMES)).toBe("/review /plan look then it");
    expect(toWire("a $plan b $plan c", NAMES)).toBe("/plan a b c");
  });

  it("keeps punctuation and line breaks around a removed token", () => {
    expect(toWire("please $plan.", NAMES)).toBe("/plan please.");
    expect(toWire("use $plan, then go", NAMES)).toBe("/plan use, then go");
    expect(toWire("one\n$plan\ntwo", NAMES)).toBe("/plan one\ntwo");
    expect(toWire("one $plan\ntwo", NAMES)).toBe("/plan one\ntwo");
  });

  it("keeps slash commands typed first in front, as typed: the hoisted skills follow them", () => {
    expect(toWire("/model x $plan", NAMES)).toBe("/model /plan x");
    expect(toWire("/review check $plan this", NAMES)).toBe("/review /plan check this");
    expect(toWire("/plan again $plan", NAMES)).toBe("/plan again"); // already named: not twice
    expect(toWire("  /review  look $plan", NAMES)).toBe("/review /plan look");
    expect(toWire("/new $plan fix it", NAMES)).toBe("/new /plan fix it");
    // a slash inside a word later in the text is not a command
    expect(toWire("see a/b $plan", NAMES)).toBe("/plan see a/b");
  });

  it("leaves code, paths, /name and ./name where they are", () => {
    expect(toWire("run `$plan` with $review on ./plan and /src/x, not /plan", NAMES)).toBe("/review run `$plan` with on ./plan and /src/x, not /plan");
  });
});

describe("sentTokens", () => {
  it("draws the $name tokens of the skills a message was sent with, not slash words", () => {
    expect(sentTokens("fix $plan now", ["plan"]).map((t) => t.name)).toEqual(["plan"]);
    expect(sentTokens("hello", undefined)).toEqual([]);
    expect(sentTokens("/new $plan x", ["plan"]).map((t) => t.name)).toEqual(["plan"]);
    expect(sentTokens("see ./plan", ["plan"])).toEqual([]);
    expect(sentTokens("/plan x", ["plan"])).toEqual([]);
  });
});

describe("fragmentAt", () => {
  it("finds the $ being typed at the caret, anywhere in the text", () => {
    expect(fragmentAt("$", 1)).toEqual({ start: 0, query: "" });
    expect(fragmentAt("fix this $pl", 12)).toEqual({ start: 9, query: "pl" });
    expect(fragmentAt("fix $pl now", 7)).toEqual({ start: 4, query: "pl" });
  });

  it("is nothing after a space, inside a word, after a slash, in a path or in code", () => {
    expect(fragmentAt("fix $plan ", 10)).toBeNull();
    expect(fragmentAt("x$pl", 4)).toBeNull();
    expect(fragmentAt("US$pl", 5)).toBeNull();
    expect(fragmentAt("/pl", 3)).toBeNull();
    expect(fragmentAt("fix /pl", 7)).toBeNull();
    expect(fragmentAt("./pl", 4)).toBeNull();
    expect(fragmentAt("$src/a", 6)).toBeNull();
    expect(fragmentAt("`$pl`", 4)).toBeNull();
    expect(fragmentAt("```\n$pl", 7)).toBeNull();
    expect(fragmentAt("plain", 5)).toBeNull();
    expect(fragmentAt("", 12)).toBeNull(); // a caret left over from longer text
    expect(fragmentAt("$pl", 9)).toEqual({ start: 0, query: "pl" });
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

describe("leadRow", () => {
  const skills = ["homeassistant", "p5js", "plan", "review", "github-code-review"].map((name) => ({ name, description: "" }));
  const lead = (q: string) => leadRow(matchSkills(skills, q), q);
  it("opens on the first row only when what is typed, as written, begins a skill's name", () => {
    expect(lead("pl")).toBe(0);
    expect(lead("")).toBe(0); // a bare `$` lists every skill
    expect(lead("rev")).toBe(0); // `review` begins with it, `github-code-review` only contains it
  });
  it("chooses no row for a price, a shell variable or letters that only sit inside a name, so Enter sends them", () => {
    expect(matchSkills(skills, "5").map((s) => s.name)).toEqual(["p5js"]);
    expect(lead("5")).toBe(-1);
    expect(matchSkills(skills, "HOME").map((s) => s.name)).toEqual(["homeassistant"]);
    expect(lead("HOME")).toBe(-1);
    expect(lead("PLAN")).toBe(-1);
    expect(lead("code")).toBe(-1);
    expect(lead("zz")).toBe(-1); // nothing matches
  });
});
