import { afterEach, describe, expect, it, vi } from "vitest";
import { createNoteGate, HOLD_MS, noteFor, sessionNote, sessionRings, spoken } from "./notify";
import type { BridgeEvent } from "./protocol";

const ctx = (errors?: boolean) => ({ name: (b: string) => (b === "kami" ? "Kami" : b), watching: () => false, errors });
const ev = (e: Record<string, unknown>) => ({ bot: "kami", ...e }) as unknown as BridgeEvent;

describe("spoken: what the bot said, as a notification says it", () => {
  it.each([
    ["first sentence only", "Fixed the 502s. Then I ran the tests. All green.", "Fixed the 502s."],
    ["a greeting takes the next sentence", "Done! The 502s came from keep-alive. I raised the timeout.", "Done! The 502s came from keep-alive."],
    ["Korean greeting with an honorific", "네, 선생님! 배포를 마쳤어요. 확인해 주세요.", "네, 선생님! 배포를 마쳤어요."],
    ["three sentences at most", "Hi. Ok. Yes. Sure. The real news.", "Hi. Ok. Yes."],
    ["Korean sentence end", "빌드가 깨졌어요. 원인은 캐시예요.", "빌드가 깨졌어요."],
    ["Japanese sentence end", "テストが通りました。次はデプロイです。", "テストが通りました。"],
    ["Chinese full-width marks", "好的！我已经修好了这个错误。还有一个问题？", "好的！我已经修好了这个错误。"],
    ["a new line is a new sentence", "Fixed it\nsecond line", "Fixed it"],
    ["a code block goes", "```ts\nconst a = 1;\n```\nThe fix is in.", "The fix is in."],
    ["a table and a heading go", "## Summary\n| a | b |\n|---|---|\nAll three pass.", "All three pass."],
    ["markdown marks and bullets go", "- **Fixed** the `502s` in _gateway_.", "Fixed the 502s in gateway."],
    ["an aside in brackets goes", "Pushed the branch (after a rebase). Done.", "Pushed the branch."],
    ["a path keeps its last name", "I changed /a/b/c.ts for you.", "I changed c.ts for you."],
    ["a URL keeps its host", "Opened https://x.y/z?q for review.", "Opened x.y for review."],
    ["a markdown link keeps its words", "See [the PR](https://github.com/o/r/pull/1) now.", "See the PR now."],
  ])("%s", (_, input, want) => {
    expect(spoken(input)).toBe(want);
  });
  it("140 characters at most, ending in …", () => {
    const out = spoken(`${"word ".repeat(60)}end.`);
    expect(out.length).toBe(140);
    expect(out.endsWith("…")).toBe(true);
  });
});

describe("noteFor: only what needs the person", () => {
  it("a turn that ends with an error marks its chat only, unless Also notify on errors is on", () => {
    const err = ev({ event: "turn.end", outcome: "error", error: "provider 500" });
    expect(noteFor(err, ctx())).toBeNull();
    expect(noteFor(err, ctx(false))).toBeNull();
    expect(noteFor(err, ctx(true))).toMatchObject({ title: "Kami stopped with an error", body: "provider 500" });
  });
  it("the answer's body is its spoken first sentence; the title has no status marks", () => {
    const n = noteFor(ev({ event: "message", id: "m", text: "Done! I fixed `/w/gateway/src/pool.rs`. Next I ran the suite." }), ctx());
    expect(n).toMatchObject({ title: "Kami", body: "Done! I fixed pool.rs." });
  });
  it("an approval keeps its command, with paths and URLs shortened", () => {
    const n = noteFor(ev({ event: "approval.request", request_id: "a", title: "Run", command: "curl https://api.example.com/v1/x -o /tmp/a/b/out.json", choices: [] }), ctx());
    expect(n).toMatchObject({ title: "Kami needs your approval", body: "curl api.example.com -o out.json" });
  });
});

describe("sessionRings: a program end notifies only when it went wrong", () => {
  const name = "web-app · Claude Code";
  it("exit 0 after a real run only marks the row; exit 1 notifies", () => {
    expect(sessionRings({ kind: "ended", name, code: 0, ms: 60_000 })).toBe(false);
    expect(sessionRings({ kind: "ended", name, code: 1, ms: 60_000 })).toBe(true);
    expect(sessionRings({ kind: "ended", name, code: null, error: "Claude Code is not signed in.", ms: 60_000 })).toBe(true);
  });
  it("an end within the first 5 s could not run: it notifies", () => {
    expect(sessionRings({ kind: "ended", name, code: 0, ms: 1200 })).toBe(true);
  });
  it("a start that failed and a ring always notify", () => {
    expect(sessionRings({ kind: "failed", name, error: "" })).toBe(true);
    // an agent's bell is it waiting for the person; a plain shell's bell (tab completion, a stray \\a) only marks the row
    expect(sessionRings({ kind: "bell", name, agent: true })).toBe(true);
    expect(sessionRings({ kind: "bell", name, agent: false })).toBe(false);
    expect(sessionRings({ kind: "bell", name })).toBe(false);
  });
  it("an agent's reason reads as spoken", () => {
    expect(sessionNote("s1", { kind: "ended", name, code: 1, error: "Could not read /home/you/.config/app/auth.json (missing). Sign in again." }).body).toBe(
      "Could not read auth.json.",
    );
  });
});

describe("createNoteGate: a ring with no words waits for the question", () => {
  afterEach(() => vi.useRealTimers());
  it("an empty ring then a texted question within 8 s: one notification, the texted one", () => {
    vi.useFakeTimers();
    const gate = createNoteGate();
    const shown: string[] = [];
    gate.offer("kami", "empty", () => shown.push("ring"));
    vi.advanceTimersByTime(3000);
    gate.offer("kami", "ask", () => shown.push("Which branch?"));
    vi.advanceTimersByTime(HOLD_MS * 2);
    expect(shown).toEqual(["Which branch?"]);
  });
  it("an empty ring with nothing after it fires after 8 s, not before", () => {
    vi.useFakeTimers();
    const gate = createNoteGate();
    const shown: string[] = [];
    gate.offer("kami", "empty", () => shown.push("ring"));
    vi.advanceTimersByTime(HOLD_MS - 1);
    expect(shown).toEqual([]);
    vi.advanceTimersByTime(1);
    expect(shown).toEqual(["ring"]);
  });
  it("another chat's question does not take its place; an answer goes out as is", () => {
    vi.useFakeTimers();
    const gate = createNoteGate();
    const shown: string[] = [];
    gate.offer("kami", "empty", () => shown.push("kami ring"));
    gate.offer("friren", "ask", () => shown.push("friren asks"));
    gate.offer("kami", "plain", () => shown.push("kami answer"));
    vi.advanceTimersByTime(HOLD_MS);
    expect(shown).toEqual(["friren asks", "kami answer", "kami ring"]);
  });
  it("a clarify with no text is held (its note still names the chat)", () => {
    const n = noteFor(ev({ event: "clarify.request", request_id: "c", question: "  " }), ctx());
    expect(n).toMatchObject({ title: "Kami has a question", body: "It is waiting for you." });
  });
});
