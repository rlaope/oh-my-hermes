// Ctrl+` (the bottom terminal panel) on every OS, by the physical key, and never while an input method composes.
import { describe, expect, it } from "vitest";
import { shortcutFor } from "./shortcuts";

type K = Parameters<typeof shortcutFor>[0];
const k = (key: string, code: string | undefined, m: Partial<K> = {}): K => ({ key, code, metaKey: false, ctrlKey: false, altKey: false, shiftKey: false, ...m });

describe("Ctrl+` opens the terminal panel", () => {
  it("is Ctrl+` on macOS and on Windows/Linux alike", () => {
    for (const mac of [true, false]) {
      expect(shortcutFor(k("`", "Backquote", { ctrlKey: true }), mac)).toEqual({ kind: "terminal" });
    }
  });

  it("goes by the key's place, so non-US layouts work (Korean, German, French, Japanese)", () => {
    for (const mac of [true, false]) {
      // Korean 2-set: the same key, but the layout may report ₩ or ` ; German: ^ ; French AZERTY: ²
      for (const key of ["`", "₩", "^", "²", "Dead", "半角/全角"]) {
        expect(shortcutFor(k(key, "Backquote", { ctrlKey: true }), mac), `${key} mac=${mac}`).toEqual({ kind: "terminal" });
      }
    }
    // an engine with no `code`: the character decides
    expect(shortcutFor(k("`", undefined, { ctrlKey: true }), false)).toEqual({ kind: "terminal" });
  });

  it("is not ⌘`, Ctrl+Shift+`, Ctrl+Alt+` or a plain `", () => {
    expect(shortcutFor(k("`", "Backquote", { metaKey: true }), true)).toBeNull();
    expect(shortcutFor(k("~", "Backquote", { ctrlKey: true, shiftKey: true }), true)).toBeNull();
    expect(shortcutFor(k("`", "Backquote", { ctrlKey: true, altKey: true }), false)).toBeNull();
    expect(shortcutFor(k("`", "Backquote", { ctrlKey: true, metaKey: true }), true)).toBeNull();
    expect(shortcutFor(k("`", "Backquote"), true)).toBeNull();
    // another key that prints ` on some layout is not the shortcut
    expect(shortcutFor(k("`", "Equal", { ctrlKey: true }), false)).toBeNull();
  });

  it("does nothing while an input method is composing", () => {
    expect(shortcutFor(k("`", "Backquote", { ctrlKey: true, isComposing: true }), true)).toBeNull();
    expect(shortcutFor(k("Process", "Backquote", { ctrlKey: true, keyCode: 229 }), false)).toBeNull();
  });

  it("leaves ⌘J as next-ask (not the terminal)", () => {
    expect(shortcutFor(k("j", "KeyJ", { metaKey: true }), true)).toEqual({ kind: "next-ask" });
    expect(shortcutFor(k("j", "KeyJ", { ctrlKey: true }), false)).toEqual({ kind: "next-ask" });
  });
});

describe("⌘⇧[ ] step order", () => {
  it("follows the sidebar: one folder spelled with and without a trailing slash is one group", async () => {
    const { terminalOrder } = await import("./shortcuts");
    const rows = [
      { id: "a", cwd: "/w/app/" },
      { id: "b", cwd: "/w/other" },
      { id: "c", cwd: "/w/app" },
    ];
    expect(terminalOrder(rows, [])).toEqual(["a", "c", "b"]);
    expect(terminalOrder(rows, ["/w/other"])).toEqual(["b", "a", "c"]);
  });
});
