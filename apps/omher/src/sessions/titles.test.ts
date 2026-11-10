import { describe, expect, it } from "vitest";
import { clipTitle, parseTitles, pickTitle, promptTitle, putTitle, TITLE_MAX, TITLES_MAX } from "./titles";

const len = (s: string) => Array.from(new Intl.Segmenter(undefined, { granularity: "grapheme" }).segment(s)).length;

describe("session titles: a summary of the first message", () => {
  it("keeps the first sentence of an English message", () => {
    expect(promptTitle("Fix the login redirect loop after OAuth sign-in. It started after the last deploy.")).toBe(
      "Fix the login redirect loop after OAuth…",
    );
    expect(promptTitle("Add dark mode to settings. Then ship it")).toBe("Add dark mode to settings");
    expect(promptTitle("Why does the build fail on Windows? Logs below")).toBe("Why does the build fail on Windows?");
    expect(promptTitle("Rename the env var; keep the old one as an alias")).toBe("Rename the env var");
    expect(promptTitle("refactor the parser - it is too slow")).toBe("refactor the parser");
    // a dot inside a word or a version is not a sentence end
    expect(promptTitle("Bump vite to 6.2.1 in package.json")).toBe("Bump vite to 6.2.1 in package.json");
  });

  it("works in Korean", () => {
    expect(promptTitle("사용자 목록 API에 페이지네이션 추가해줘. 테스트도 같이")).toBe("사용자 목록 API에 페이지네이션 추가해줘");
    expect(promptTitle("로그인 리다이렉트가 왜 두 번 되는지 봐줄래?")).toBe("로그인 리다이렉트가 왜 두 번 되는지 봐줄래?");
    // long Korean is cut at a space, never inside a syllable
    const ko = promptTitle("게이트웨이 재시작 후에 슬랙 응답이 늦게 오는 문제를 원인부터 차근차근 찾아서 고쳐줘");
    expect(ko.endsWith("…")).toBe(true);
    expect(len(ko)).toBeLessThanOrEqual(TITLE_MAX);
    expect(ko).toBe("게이트웨이 재시작 후에 슬랙 응답이 늦게 오는 문제를 원인부터 차근차근…");
    // CJK full stops end a sentence too
    expect(promptTitle("配置を確認して。それから再起動")).toBe("配置を確認して");
  });

  it("drops a leading slash command and @file references", () => {
    expect(promptTitle("/review @src/routes/users.ts 사용자 목록 API에 페이지네이션 추가해줘")).toBe("사용자 목록 API에 페이지네이션 추가해줘");
    expect(promptTitle("/compact")).toBe("");
    expect(promptTitle("/plugin:do-thing check the docs")).toBe("check the docs");
    expect(promptTitle("look at @README.md and @docs/x.md please")).toBe("look at and please");
    // a path in the middle of a sentence is not a command
    expect(promptTitle("move it to /tmp/out")).toBe("move it to /tmp/out");
  });

  it("drops code blocks and inline code marks", () => {
    // "…into" would make 41 characters: the cut goes one word back
    expect(promptTitle("```\nTODO\n```\nSummarize this week's meeting notes into action items")).toBe("Summarize this week's meeting notes…");
    expect(promptTitle("```ts\nconst a = 1\n```")).toBe("");
    expect(promptTitle("why does `pnpm test` hang?")).toBe("why does pnpm test hang?");
    // an unclosed fence takes the rest
    expect(promptTitle("Explain this\n```\nlet x")).toBe("Explain this");
  });

  it("drops links: a link alone names nothing, a Markdown link keeps its text", () => {
    expect(promptTitle("https://github.com/rlaope/oh-my-hermes/pull/2752")).toBe("");
    expect(promptTitle("  <https://example.com/a>  ")).toBe("");
    expect(promptTitle("Read https://example.com/spec and summarize it")).toBe("Read and summarize it");
    expect(promptTitle("See [the spec](https://example.com/spec) first")).toBe("See the spec first");
  });

  it("skips Markdown marks and empty or symbol-only lines", () => {
    expect(promptTitle("\n\n## Goal\n- ship it")).toBe("Goal");
    expect(promptTitle("> **Fix** the flaky test")).toBe("Fix the flaky test");
    expect(promptTitle("---\n\n1. Rename the module")).toBe("Rename the module");
    expect(promptTitle("   ")).toBe("");
  });

  it("handles emoji: emoji alone names nothing, an emoji is never split", () => {
    expect(promptTitle("👍")).toBe("");
    expect(promptTitle("🎉🎉")).toBe("");
    expect(promptTitle("🚀 Ship the release today")).toBe("🚀 Ship the release today");
    const long = promptTitle("👨‍👩‍👧 family emoji test " + "word ".repeat(20));
    expect(long.startsWith("👨‍👩‍👧 ")).toBe(true);
    expect(len(long)).toBeLessThanOrEqual(TITLE_MAX);
    // a cut right after an emoji keeps it whole
    const at = clipTitle("x".repeat(38) + "👨‍👩‍👧👨‍👩‍👧👨‍👩‍👧", 40);
    expect(at).toBe("x".repeat(38) + "👨‍👩‍👧…");
  });

  it("cuts a very long message at a word, with an ellipsis, within the limit", () => {
    const long = "Please go through every single file in the repository and update the license header to the new year";
    const t = promptTitle(long);
    expect(t).toBe("Please go through every single file in…");
    expect(len(t)).toBeLessThanOrEqual(TITLE_MAX);
    // one very long word is cut where it must
    const word = promptTitle("a".repeat(120));
    expect(word).toBe("a".repeat(39) + "…");
    // a short message is kept whole
    expect(clipTitle("short", 40)).toBe("short");
  });
});

describe("session titles: which name shows", () => {
  it("the person's name, then the agent's, then the summary, then the folder", () => {
    expect(pickTitle({ title: "Mine", agentTitle: "Agent", promptTitle: "Prompt" }, "web-app")).toEqual({ title: "Mine", source: "person" });
    expect(pickTitle({ agentTitle: "Agent", promptTitle: "Prompt" }, "web-app")).toEqual({ title: "Agent", source: "agent" });
    expect(pickTitle({ promptTitle: "Prompt" }, "web-app")).toEqual({ title: "Prompt", source: "prompt" });
    expect(pickTitle({}, "web-app")).toEqual({ title: "web-app", source: "folder" });
    expect(pickTitle({ title: " ", agentTitle: "  A\n b " }, "f")).toEqual({ title: "A b", source: "agent" });
  });

  it("saved names: malformed storage is dropped, the oldest go past the cap", () => {
    expect(parseTitles(null)).toEqual({});
    expect(parseTitles("not json")).toEqual({});
    expect(parseTitles("[1,2]")).toEqual({});
    expect(parseTitles(JSON.stringify({ "claude:a": "One", "codex:b": 3, "": "x", "claude:c": "  " }))).toEqual({ "claude:a": "One" });
    let m: Record<string, string> = {};
    for (let i = 0; i < TITLES_MAX + 5; i++) m = putTitle(m, `k${i}`, `t${i}`);
    expect(Object.keys(m).length).toBe(TITLES_MAX);
    expect(m.k0).toBeUndefined();
    expect(m[`k${TITLES_MAX + 4}`]).toBe(`t${TITLES_MAX + 4}`);
    expect(putTitle({ a: "1" }, "a", null)).toEqual({});
  });
});
