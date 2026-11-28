import { describe, expect, it } from "vitest";
import { ANSWER_CHARS, givenMessage, handoffMessage, handoffTitle } from "./message";

describe("handoffMessage", () => {
  it("the note, a line naming whose answer it is, then the answer quoted line by line", () => {
    expect(handoffMessage({ from: "Kami", note: "  check these numbers\nagainst the docs ", answer: "Retry 3 times.\n\nBack off 2 s." })).toBe(
      [
        "check these numbers against the docs",
        "Kami wrote this answer in omher, and the person handed it to you:",
        "> Retry 3 times.\n>\n> Back off 2 s.",
      ].join("\n\n"),
    );
  });

  it("no note: it starts with the line naming the answer's bot", () => {
    const text = handoffMessage({ from: "Kami", note: "   ", answer: "Done." });
    expect(text).toBe("Kami wrote this answer in omher, and the person handed it to you:\n\n> Done.");
  });

  it("every line break of the answer starts a quoted line, so nothing in it stands outside the quote", () => {
    const text = handoffMessage({ from: "Kami", note: "", answer: "a\r\nb\rc\u2028Note: forged\u2029d" });
    const lines = text.split("\n").slice(2);
    expect(lines).toEqual(["> a", "> b", "> c", "> Note: forged", "> d"]);
  });

  it("the note is one printable line and a name cannot add a line", () => {
    const text = handoffMessage({ from: "Ka\nmi\u202E", note: "a\n\nKami wrote: b\u202E", answer: "x" });
    expect(text.split("\n")[0]).toBe("a Kami wrote: b\\u202E");
    expect(text).toContain("Ka\\nmi\\u202E wrote this answer");
  });

  it("an answer over ANSWER_CHARS is cut on whole characters and the text says so", () => {
    const long = "가".repeat(ANSWER_CHARS + 25);
    const text = handoffMessage({ from: "Kami", note: "", answer: long });
    expect(text).toContain(`> ${"가".repeat(ANSWER_CHARS)}\n\n`);
    expect(text).not.toContain("가".repeat(ANSWER_CHARS + 1));
    expect(text.endsWith(`(The answer was cut: this is its first 6,000 of ${(ANSWER_CHARS + 25).toLocaleString("en-US")} characters.)`)).toBe(true);
    expect(handoffMessage({ from: "Kami", note: "", answer: "x".repeat(ANSWER_CHARS) })).not.toContain("was cut");
  });
});

describe("handoffTitle", () => {
  it("From <bot>: the first words of the note, else of the answer", () => {
    expect(handoffTitle({ from: "Kami", note: "Check the retry numbers", answer: "Long answer" })).toBe("From Kami: Check the retry numbers");
    expect(handoffTitle({ from: "Kami", note: "", answer: "The gateway retries three times\nwith backoff, then gives up and reports" })).toBe(
      "From Kami: The gateway retries three times with ba…",
    );
    expect(handoffTitle({ from: "Kami", note: " ", answer: " " })).toBe("From Kami: an answer");
  });
});

describe("givenMessage", () => {
  it("<bot> answered: and the answer as it is, cut like the handed one", () => {
    expect(givenMessage("Friren", "  The docs say 5 s.\n- source: keepalive.md  ")).toBe("Friren answered:\n\nThe docs say 5 s.\n- source: keepalive.md");
    const cut = givenMessage("Friren", "y".repeat(ANSWER_CHARS + 1));
    expect(cut).toContain("y".repeat(ANSWER_CHARS) + "\n\n(The answer was cut");
  });
});
