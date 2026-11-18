import { describe, expect, it } from "vitest";
import { threadCommand, threadFragment } from "./threadCommand";

describe("threadCommand", () => {
  it("reads ./thread alone as a new empty thread", () => {
    expect(threadCommand("./thread")).toEqual({ start: 0, end: 8, first: "" });
    expect(threadCommand("./thread   ")).toEqual({ start: 0, end: 8, first: "" });
  });

  it("takes the rest of the message as the thread's first message", () => {
    expect(threadCommand("./thread fix the 502 on OG")?.first).toBe("fix the 502 on OG");
    expect(threadCommand("./thread\nline one\nline two")?.first).toBe("line one\nline two");
    expect(threadCommand("./thread 릴리스 노트 정리")?.first).toBe("릴리스 노트 정리");
  });

  it("allows blank space before it", () => {
    expect(threadCommand("  ./thread do X")).toEqual({ start: 2, end: 10, first: "do X" });
  });

  it("counts only at the start: mid-message it goes out as typed", () => {
    expect(threadCommand("please ./thread do X")).toBeNull();
    expect(threadCommand("do X\n./thread")).toBeNull();
  });

  it("is the whole word only, as written", () => {
    expect(threadCommand("./threads")).toBeNull();
    expect(threadCommand("./thread.sh")).toBeNull();
    expect(threadCommand("./thread-x")).toBeNull();
    expect(threadCommand("./Thread x")).toBeNull();
    expect(threadCommand("/thread x")).toBeNull();
    expect(threadCommand("$thread x")).toBeNull();
    expect(threadCommand("`./thread` x")).toBeNull();
  });
});

describe("threadFragment", () => {
  it("opens on ./ and on each beginning of thread", () => {
    expect(threadFragment("./")).toBe("");
    expect(threadFragment("./th")).toBe("th");
    expect(threadFragment("./thread")).toBe("thread");
    expect(threadFragment(" ./t")).toBe("t");
  });

  it("stays shut on paths, other words, and once the message goes on", () => {
    expect(threadFragment("./b")).toBeNull();
    expect(threadFragment("./build.sh")).toBeNull();
    expect(threadFragment("./threads")).toBeNull();
    expect(threadFragment("./thread x")).toBeNull();
    expect(threadFragment("see ./th")).toBeNull();
    expect(threadFragment("")).toBeNull();
  });
});
