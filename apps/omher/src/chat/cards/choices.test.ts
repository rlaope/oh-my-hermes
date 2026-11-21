import { describe, expect, it } from "vitest";
import { choiceIndexForKey, parseChoice } from "./choices";

describe("parseChoice", () => {
  it("leaves a plain choice as one line", () => {
    expect(parseChoice("staging")).toEqual({ title: "staging", desc: "", recommended: false });
  });
  it("splits at the first ' — ' into title and description", () => {
    expect(parseChoice("Retry — run it again — with logs")).toEqual({ title: "Retry", desc: "run it again — with logs", recommended: false });
  });
  it("does not split on a dash without spaces around it", () => {
    expect(parseChoice("a—b and c - d").title).toBe("a—b and c - d");
  });
  it("drops a dash at the end", () => {
    expect(parseChoice("Retry — ")).toEqual({ title: "Retry", desc: "", recommended: false });
    expect(parseChoice("Retry —")).toEqual({ title: "Retry", desc: "", recommended: false });
  });
  it("keeps one line when nothing is before the dash", () => {
    expect(parseChoice(" — only a note").desc).toBe("");
  });
  it("lifts a trailing (Recommended) into the badge", () => {
    expect(parseChoice("production (Recommended)")).toEqual({ title: "production", desc: "", recommended: true });
  });
  it("lifts a trailing (권장) into the badge", () => {
    expect(parseChoice("스테이징에 먼저 배포 (권장)")).toEqual({ title: "스테이징에 먼저 배포", desc: "", recommended: true });
  });
  it("handles badge and description together", () => {
    expect(
      parseChoice("Slack 실패 스레드에 남기기 — 원인 요약(11-19부터 같은 모델 실패, #1188 무관)을 #deploy-common 스레드에 카미가 답글로 (Recommended)"),
    ).toEqual({
      title: "Slack 실패 스레드에 남기기",
      desc: "원인 요약(11-19부터 같은 모델 실패, #1188 무관)을 #deploy-common 스레드에 카미가 답글로",
      recommended: true,
    });
  });
  it("leaves a badge in the middle alone", () => {
    expect(parseChoice("(Recommended) first")).toEqual({ title: "(Recommended) first", desc: "", recommended: false });
  });
  it("keeps a lone badge as the text instead of an empty row", () => {
    expect(parseChoice("(권장)")).toEqual({ title: "(권장)", desc: "", recommended: false });
  });
});

const key = (k: string, over: Record<string, unknown> = {}) => ({ key: k, target: { tagName: "BUTTON" }, ...over });

describe("choiceIndexForKey", () => {
  it("maps 1..n to 0-based rows, Other included", () => {
    expect(choiceIndexForKey(key("1"), 3)).toBe(0);
    expect(choiceIndexForKey(key("3"), 3)).toBe(2);
  });
  it("ignores digits past the last row, 0, and non-digits", () => {
    expect(choiceIndexForKey(key("4"), 3)).toBe(-1);
    expect(choiceIndexForKey(key("0"), 3)).toBe(-1);
    expect(choiceIndexForKey(key("a"), 3)).toBe(-1);
    expect(choiceIndexForKey(key("10"), 12)).toBe(-1);
  });
  it("ignores keys with a modifier", () => {
    for (const m of ["metaKey", "ctrlKey", "altKey", "shiftKey"]) expect(choiceIndexForKey(key("1", { [m]: true }), 3)).toBe(-1);
  });
  it("ignores auto-repeat, which would toggle a multi-select back and forth", () => {
    expect(choiceIndexForKey(key("1", { repeat: true }), 3)).toBe(-1);
  });
  it("does not fire while typing in a field", () => {
    for (const tagName of ["INPUT", "TEXTAREA", "SELECT"]) expect(choiceIndexForKey(key("1", { target: { tagName } }), 3)).toBe(-1);
    expect(choiceIndexForKey(key("1", { target: { tagName: "DIV", isContentEditable: true } }), 3)).toBe(-1);
  });
  it("does not fire while an input method composes", () => {
    expect(choiceIndexForKey(key("1", { nativeEvent: { isComposing: true } }), 3)).toBe(-1);
    expect(choiceIndexForKey(key("1", { isComposing: true }), 3)).toBe(-1);
    expect(choiceIndexForKey(key("1", { keyCode: 229 }), 3)).toBe(-1);
  });
  it("fires from the card itself", () => {
    expect(choiceIndexForKey(key("2", { target: { tagName: "DIV" } }), 3)).toBe(1);
  });
});
