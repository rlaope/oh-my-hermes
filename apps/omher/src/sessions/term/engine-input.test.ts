import { describe, expect, it } from "vitest";
import { isFindKey } from "./engine-input";

const key = (o: Partial<{ key: string; code: string; metaKey: boolean; ctrlKey: boolean; altKey: boolean; shiftKey: boolean }>) => ({ key: "f", code: "KeyF", metaKey: false, ctrlKey: false, altKey: false, shiftKey: false, ...o });

describe("find shortcut", () => {
  it("macOS: Cmd+F; Ctrl+F stays the program's (it moves the cursor forward in a shell)", () => {
    expect(isFindKey(key({ metaKey: true }), true, false)).toBe(true);
    expect(isFindKey(key({ metaKey: true }), true, true)).toBe(true); // Cmd is never a program's key
    expect(isFindKey(key({ ctrlKey: true }), true, false)).toBe(false);
    expect(isFindKey(key({}), true, false)).toBe(false);
    expect(isFindKey(key({ metaKey: true, altKey: true }), true, false)).toBe(false);
    expect(isFindKey(key({ metaKey: true, shiftKey: true }), true, false)).toBe(false);
  });

  it("Windows and Linux: Ctrl+F finds at a prompt, but a full-screen program (alternate screen) keeps it", () => {
    expect(isFindKey(key({ ctrlKey: true }), false, false)).toBe(true);
    expect(isFindKey(key({ ctrlKey: true }), false, true)).toBe(false);
  });

  it("Windows and Linux: Ctrl+Shift+F finds everywhere, so the bar is always reachable", () => {
    expect(isFindKey(key({ ctrlKey: true, shiftKey: true, key: "F" }), false, true)).toBe(true);
    expect(isFindKey(key({ ctrlKey: true, shiftKey: true, key: "F" }), false, false)).toBe(true);
  });

  it("other keys and a plain f are not find; a non-Latin layout still has its F key", () => {
    expect(isFindKey(key({ metaKey: true, key: "g", code: "KeyG" }), true, false)).toBe(false);
    expect(isFindKey(key({ ctrlKey: true, key: "g", code: "KeyG" }), false, false)).toBe(false);
    expect(isFindKey(key({ metaKey: true, key: "ㄹ", code: "KeyF" }), true, false)).toBe(true);
    expect(isFindKey(key({ metaKey: true, key: "ф", code: "KeyF" }), true, false)).toBe(true);
    // a Latin key that is not f on this layout is not find even when its physical place is F
    expect(isFindKey(key({ metaKey: true, key: "t", code: "KeyF" }), true, false)).toBe(false);
  });
});
