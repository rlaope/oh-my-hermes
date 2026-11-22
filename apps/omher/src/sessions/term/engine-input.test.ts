import { describe, expect, it } from "vitest";
import { findOptionKey, fontKey, isAppKey, isClearKey, isSelectAllKey, optionTyped, isFindKey, lineEditBytes, nextFontSize, scrollKey, clipboardKey } from "./engine-input";
import { validPattern } from "./engine-find";

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

describe("find options", () => {
  it("Alt+C flips Match case and Alt+R flips Regular expression, by the key's place too (Option+C types ç on a Mac)", () => {
    expect(findOptionKey(key({ altKey: true, key: "c", code: "KeyC" }))).toBe("caseSensitive");
    expect(findOptionKey(key({ altKey: true, key: "ç", code: "KeyC" }))).toBe("caseSensitive");
    expect(findOptionKey(key({ altKey: true, key: "r", code: "KeyR" }))).toBe("regex");
    expect(findOptionKey(key({ altKey: true, key: "®", code: "KeyR" }))).toBe("regex");
    expect(findOptionKey(key({ altKey: true, key: "ㄱ", code: "KeyR" }))).toBe("regex");
  });

  it("anything else is not an option key: no Alt, another modifier with it, another letter", () => {
    expect(findOptionKey(key({ key: "c", code: "KeyC" }))).toBeNull();
    expect(findOptionKey(key({ altKey: true, ctrlKey: true, key: "c", code: "KeyC" }))).toBeNull();
    expect(findOptionKey(key({ altKey: true, metaKey: true, key: "r", code: "KeyR" }))).toBeNull();
    expect(findOptionKey(key({ altKey: true, key: "x", code: "KeyX" }))).toBeNull();
    // a Latin layout whose C key types another letter: the letter counts, not the place
    expect(findOptionKey(key({ altKey: true, key: "j", code: "KeyC" }))).toBeNull();
  });

  it("a pattern is valid when it compiles as the search add-on compiles it", () => {
    for (const ok of ["fo+", "foo", "^a.*b$", "\\d{2,}", "(a|b)", "[x-z]"]) expect(validPattern(ok), ok).toBe(true);
    for (const bad of ["(", "[", "a{2,1}", "*", "(?<", "\\"]) expect(validPattern(bad), bad).toBe(false);
  });
});

describe("font size keys", () => {
  const k = (o: Partial<{ key: string; code: string; metaKey: boolean; ctrlKey: boolean; altKey: boolean; shiftKey: boolean }>) => key(o);

  it("macOS: Cmd+= and Cmd++ bigger, Cmd+- smaller, Cmd+0 default; Ctrl is the program's", () => {
    expect(fontKey(k({ metaKey: true, key: "=", code: "Equal" }), true)).toBe("bigger");
    expect(fontKey(k({ metaKey: true, shiftKey: true, key: "+", code: "Equal" }), true)).toBe("bigger");
    expect(fontKey(k({ metaKey: true, key: "+", code: "NumpadAdd" }), true)).toBe("bigger");
    expect(fontKey(k({ metaKey: true, key: "-", code: "Minus" }), true)).toBe("smaller");
    expect(fontKey(k({ metaKey: true, key: "0", code: "Digit0" }), true)).toBe("reset");
    expect(fontKey(k({ ctrlKey: true, key: "=", code: "Equal" }), true)).toBeNull();
    expect(fontKey(k({ ctrlKey: true, key: "-", code: "Minus" }), true)).toBeNull();
  });

  it("macOS: Cmd+Ctrl+= stays the panes' even-out key, Option is never a font key", () => {
    expect(fontKey(k({ metaKey: true, ctrlKey: true, key: "=", code: "Equal" }), true)).toBeNull();
    expect(fontKey(k({ metaKey: true, altKey: true, key: "=", code: "Equal" }), true)).toBeNull();
  });

  it("Windows and Linux: Ctrl with the same keys; Ctrl+Alt+= (even out) and Ctrl+Shift+- (Ctrl+_, undo) are not taken", () => {
    expect(fontKey(k({ ctrlKey: true, key: "=", code: "Equal" }), false)).toBe("bigger");
    expect(fontKey(k({ ctrlKey: true, key: "-", code: "Minus" }), false)).toBe("smaller");
    expect(fontKey(k({ ctrlKey: true, key: "0", code: "Digit0" }), false)).toBe("reset");
    expect(fontKey(k({ ctrlKey: true, altKey: true, key: "=", code: "Equal" }), false)).toBeNull();
    expect(fontKey(k({ ctrlKey: true, shiftKey: true, key: "_", code: "Minus" }), false)).toBeNull();
    expect(fontKey(k({ metaKey: true, key: "=", code: "Equal" }), false)).toBeNull();
  });

  it("other layouts: German + and - stand elsewhere and still count; the 1 to 9 keys stay the bots'", () => {
    expect(fontKey(k({ metaKey: true, key: "+", code: "BracketRight" }), true)).toBe("bigger");
    expect(fontKey(k({ metaKey: true, key: "-", code: "Slash" }), true)).toBe("smaller");
    expect(fontKey(k({ metaKey: true, key: "1", code: "Digit1" }), true)).toBeNull();
    expect(fontKey(k({ key: "=", code: "Equal" }), true)).toBeNull();
  });

  it("one point a step, Cmd+0 back to the default", () => {
    expect(nextFontSize(13, "bigger")).toBe(14);
    expect(nextFontSize(13.5, "smaller")).toBe(13);
    expect(nextFontSize(20, "reset")).toBe(13);
  });
});

describe("macOS line editing keys", () => {
  const k = (o: Partial<{ key: string; code: string; metaKey: boolean; ctrlKey: boolean; altKey: boolean; shiftKey: boolean }>) => key({ code: "", ...o });

  it("Cmd+Left/Right go to the line's start/end, Cmd+Backspace/Delete delete to its start/end", () => {
    expect(lineEditBytes(k({ metaKey: true, key: "ArrowLeft" }), true, false)).toBe("\x01");
    expect(lineEditBytes(k({ metaKey: true, key: "ArrowRight" }), true, false)).toBe("\x05");
    expect(lineEditBytes(k({ metaKey: true, key: "Backspace" }), true, false)).toBe("\x15");
    expect(lineEditBytes(k({ metaKey: true, key: "Delete" }), true, false)).toBe("\x0b");
  });

  it("Option+Left/Right move a word as readline knows it, except for a program with Kitty keys on", () => {
    expect(lineEditBytes(k({ altKey: true, key: "ArrowLeft" }), true, false)).toBe("\x1bb");
    expect(lineEditBytes(k({ altKey: true, key: "ArrowRight" }), true, false)).toBe("\x1bf");
    expect(lineEditBytes(k({ altKey: true, key: "ArrowLeft" }), true, true)).toBeNull();
    // Cmd stays line editing with Kitty keys on: no program reads Cmd
    expect(lineEditBytes(k({ metaKey: true, key: "ArrowLeft" }), true, true)).toBe("\x01");
  });

  it("leaves the other keys alone: Shift (selection), Cmd+Option (pane focus), Ctrl, Cmd+Up/Down (prompt jump), and Windows/Linux", () => {
    expect(lineEditBytes(k({ metaKey: true, shiftKey: true, key: "ArrowLeft" }), true, false)).toBeNull();
    expect(lineEditBytes(k({ metaKey: true, altKey: true, key: "ArrowLeft" }), true, false)).toBeNull();
    expect(lineEditBytes(k({ ctrlKey: true, key: "ArrowLeft" }), true, false)).toBeNull();
    expect(lineEditBytes(k({ metaKey: true, key: "ArrowUp" }), true, false)).toBeNull();
    expect(lineEditBytes(k({ key: "ArrowLeft" }), true, false)).toBeNull();
    expect(lineEditBytes(k({ ctrlKey: true, key: "ArrowLeft" }), false, false)).toBeNull();
    expect(lineEditBytes(k({ altKey: true, key: "ArrowLeft" }), false, false)).toBeNull();
  });

  it("Cmd+K clears on macOS (by the K key's place on a Korean layout); Ctrl+K stays the program's everywhere", () => {
    expect(isClearKey(k({ metaKey: true, key: "k", code: "KeyK" }), true)).toBe(true);
    expect(isClearKey(k({ metaKey: true, key: "ㅏ", code: "KeyK" }), true)).toBe(true);
    expect(isClearKey(k({ ctrlKey: true, key: "k", code: "KeyK" }), true)).toBe(false);
    expect(isClearKey(k({ ctrlKey: true, key: "k", code: "KeyK" }), false)).toBe(false);
    expect(isClearKey(k({ metaKey: true, shiftKey: true, key: "K", code: "KeyK" }), true)).toBe(false);
  });
});

describe("scroll keys", () => {
  const k = (o: Partial<{ key: string; code: string; metaKey: boolean; ctrlKey: boolean; altKey: boolean; shiftKey: boolean }>) => key({ code: "", ...o });
  it("Cmd+Home/End on macOS, Ctrl+Home/End elsewhere; plain Home/End stay the program's", () => {
    expect(scrollKey(k({ metaKey: true, key: "Home" }), true)).toBe("top");
    expect(scrollKey(k({ metaKey: true, key: "End" }), true)).toBe("bottom");
    expect(scrollKey(k({ ctrlKey: true, key: "Home" }), false)).toBe("top");
    expect(scrollKey(k({ ctrlKey: true, key: "End" }), false)).toBe("bottom");
    expect(scrollKey(k({ key: "Home" }), true)).toBeNull();
    expect(scrollKey(k({ key: "End" }), false)).toBeNull();
    expect(scrollKey(k({ ctrlKey: true, key: "Home" }), true)).toBeNull();
    expect(scrollKey(k({ metaKey: true, shiftKey: true, key: "Home" }), true)).toBeNull();
  });
});

describe("copy and paste keys off macOS", () => {
  const k = (o: Partial<{ key: string; code: string; metaKey: boolean; ctrlKey: boolean; altKey: boolean; shiftKey: boolean }>) => key({ code: "", ...o });
  it("Ctrl+Shift+C / Ctrl+Insert copy, Ctrl+Shift+V / Shift+Insert paste; plain Ctrl+C and Ctrl+V stay the program's", () => {
    expect(clipboardKey(k({ ctrlKey: true, shiftKey: true, key: "C", code: "KeyC" }), false)).toBe("copy");
    expect(clipboardKey(k({ ctrlKey: true, key: "Insert" }), false)).toBe("copy");
    expect(clipboardKey(k({ ctrlKey: true, shiftKey: true, key: "V", code: "KeyV" }), false)).toBe("paste");
    expect(clipboardKey(k({ shiftKey: true, key: "Insert" }), false)).toBe("paste");
    expect(clipboardKey(k({ ctrlKey: true, key: "c", code: "KeyC" }), false)).toBeNull();
    expect(clipboardKey(k({ ctrlKey: true, key: "v", code: "KeyV" }), false)).toBeNull();
    // a Korean layout: the keys where C and V stand
    expect(clipboardKey(k({ ctrlKey: true, shiftKey: true, key: "ㅊ", code: "KeyC" }), false)).toBe("copy");
  });
  it("macOS takes none of them (Cmd+C / Cmd+V are the Edit menu's)", () => {
    expect(clipboardKey(k({ ctrlKey: true, shiftKey: true, key: "C", code: "KeyC" }), true)).toBeNull();
    expect(clipboardKey(k({ shiftKey: true, key: "Insert" }), true)).toBeNull();
  });
});

describe("Cmd keys on macOS stay the app's", () => {
  const k = (key: string, mods: Partial<{ metaKey: boolean; ctrlKey: boolean; altKey: boolean; shiftKey: boolean }> = {}) => ({
    key,
    code: `Key${key.toUpperCase()}`,
    metaKey: false,
    ctrlKey: false,
    altKey: false,
    shiftKey: false,
    ...mods,
  });
  it("keeps Cmd+V, Cmd+C, Cmd+A and Cmd+Shift+anything on macOS", () => {
    for (const key of ["v", "c", "a", "x", "z"]) expect(isAppKey(k(key, { metaKey: true }), true)).toBe(true);
    expect(isAppKey(k("v", { metaKey: true, shiftKey: true }), true)).toBe(true);
  });
  it("leaves keys without Cmd, and every key off macOS, to the program", () => {
    expect(isAppKey(k("v"), true)).toBe(false);
    expect(isAppKey(k("v", { ctrlKey: true }), true)).toBe(false);
    expect(isAppKey(k("v", { metaKey: true }), false)).toBe(false);
  });
});

describe("Cmd+A selects the terminal on macOS", () => {
  const k = (key: string, code: string, mods: Partial<{ metaKey: boolean; ctrlKey: boolean; altKey: boolean; shiftKey: boolean }> = {}) => ({
    key,
    code,
    metaKey: false,
    ctrlKey: false,
    altKey: false,
    shiftKey: false,
    ...mods,
  });
  it("is Cmd+A on macOS, on a Latin or Korean layout", () => {
    expect(isSelectAllKey(k("a", "KeyA", { metaKey: true }), true)).toBe(true);
    expect(isSelectAllKey(k("ㅁ", "KeyA", { metaKey: true }), true)).toBe(true);
  });
  it("is not Cmd+Shift+A, Ctrl+A, or anything off macOS", () => {
    expect(isSelectAllKey(k("a", "KeyA", { metaKey: true, shiftKey: true }), true)).toBe(false);
    expect(isSelectAllKey(k("a", "KeyA", { ctrlKey: true }), true)).toBe(false);
    expect(isSelectAllKey(k("a", "KeyA", { metaKey: true }), false)).toBe(false);
  });

  it("Option types the ASCII sign a European Mac layout puts there; on a US layout it stays Meta", () => {
    const opt = { altKey: true };
    // German: Option+L @, Option+5/6 [ ], Option+8/9 { }, Option+7 |, Shift+Option+7 \; French: Option+Shift+L |
    for (const [key, code] of [["@", "KeyL"], ["[", "Digit5"], ["]", "Digit6"], ["{", "Digit8"], ["}", "Digit9"], ["|", "Digit7"], ["~", "KeyN"]] as const)
      expect(optionTyped(k(key, code, opt), true)).toBe(key);
    expect(optionTyped(k("\\", "Digit7", { altKey: true, shiftKey: true }), true)).toBe("\\");
    // US: Option types ∫ ƒ ≠, or a dead key; Option+letter on a layout where Option changes nothing is Meta
    for (const [key, code] of [["∫", "KeyB"], ["ƒ", "KeyF"], ["≠", "Equal"], ["Dead", "KeyE"], ["b", "KeyB"], ["5", "Digit5"], ["ArrowLeft", "ArrowLeft"]] as const)
      expect(optionTyped(k(key, code, opt), true)).toBeNull();
    expect(optionTyped(k("@", "KeyL", { altKey: true, metaKey: true }), true)).toBeNull();
    expect(optionTyped(k("@", "KeyL", { altKey: true, ctrlKey: true }), true)).toBeNull();
    expect(optionTyped(k("@", "KeyL", {}), true)).toBeNull();
    expect(optionTyped(k("@", "KeyQ", opt), false)).toBeNull();
  });
});
