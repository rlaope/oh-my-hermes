import { describe, expect, it } from "vitest";
import { hideSplitBlocks } from "./types";

// The streaming bubble hides only the blocks the bridge acts on: top-level ones, the same rule as `split_blocks`.
// A block quoted inside another fence or a `>` quote is an example and stays as written.

// a real answer (trimmed) that explains the block inside a 4-backtick fence: the bridge opens no thread for it
const QUOTED = [
  "이 블록은 **omher에게 새 스레드(작업 단위)를 열어 달라고 요청하는 명령 형식**이에요.",
  "",
  "````",
  '```omher-thread {"title": "x", "task": "y"}```',
  "````",
  "",
  "구성 요소별 의미는 다음과 같아요.",
].join("\n");

describe("hideSplitBlocks", () => {
  it("keeps a block quoted inside a 4-backtick fence verbatim", () => {
    expect(hideSplitBlocks(QUOTED)).toBe(QUOTED);
  });

  it("keeps several blocks quoted inside a 4-backtick fence", () => {
    const text = ["예를 들어:", "", "````", '```omher-thread {"title": "A", "task": "a"}```', '```omher-thread {"title": "B", "task": "b"}```', "````", "", "끝."].join("\n");
    expect(hideSplitBlocks(text)).toBe(text);
  });

  it("keeps a block inside a ~~~ fence", () => {
    const text = ["~~~", "```omher-thread", '{"title": "x", "task": "y"}', "```", "~~~"].join("\n");
    expect(hideSplitBlocks(text)).toBe(text);
  });

  it("keeps a block quoted with >", () => {
    const text = ["Like this:", "", '> ```omher-thread {"title": "x", "task": "y"}```', "", "done"].join("\n");
    expect(hideSplitBlocks(text)).toBe(text);
  });

  it("hides a top-level one-line block", () => {
    expect(hideSplitBlocks(['Two parts.', "", '```omher-thread {"title": "x", "task": "y"}```', "", "On it."].join("\n"))).toBe("Two parts.\n\nOn it.");
  });

  it("hides a top-level block with its JSON as the body, and one with the JSON on the opening line", () => {
    expect(hideSplitBlocks(["A", "```omher-thread", '{"title": "x", "task": "y"}', "```", "B"].join("\n"))).toBe("A\nB");
    expect(hideSplitBlocks(["A", '```omher-thread-route {"thread": "t1"}', "```", "B"].join("\n"))).toBe("A\nB");
  });

  it("hides a top-level block still streaming", () => {
    expect(hideSplitBlocks('Two parts.\n\n```omher-thread {"title": "x", "ta')).toBe("Two parts.");
    expect(hideSplitBlocks('Two parts.\n\n```omher-thread {"title": "x", "task": "y"}\n``')).toBe("Two parts.");
    expect(hideSplitBlocks('Two parts.\n\n```omher-thread\n{"title": "x"')).toBe("Two parts.");
  });

  it("leaves other code and text without a block untouched", () => {
    const text = "Run `omher-thread` docs:\n\n```ts\nconst a = 1;\n```";
    expect(hideSplitBlocks(text)).toBe(text);
    expect(hideSplitBlocks("plain")).toBe("plain");
  });
});
