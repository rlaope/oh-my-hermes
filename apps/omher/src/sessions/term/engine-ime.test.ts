// The input method layer's rules (engine-ime.ts), on the event sequences the two engines send. The e2e
// (e2e/term-exit.spec.ts) runs the same sequences through a real terminal.
import { describe, expect, it } from "vitest";
import { ImeInput } from "./engine-ime";

function make() {
  const sent: string[] = [];
  const shown: (string | null)[] = [];
  const ime = new ImeInput({ send: (d) => sent.push(d), show: (t) => shown.push(t) });
  return { ime, sent, shown };
}

/** WebKit, macOS 2-Set Korean: a syllable's first jamo as insertText, then in-place edits, each with a 229 keydown. */
function syllable(ime: ImeInput, steps: string[]) {
  const took: boolean[] = [];
  took.push(ime.input("insertText", steps[0], true), ime.input("insertText", steps[0]), ime.keydown({ key: "Process", keyCode: 229 }));
  for (const s of steps.slice(1)) took.push(ime.input("insertReplacementText", s, true), ime.input("insertReplacementText", s), ime.keydown({ key: "Process", keyCode: 229 }));
  return took;
}

describe("WebKit's 2-Set Korean (no composition events)", () => {
  it("sends each syllable once, when the next one starts or a real key comes; xterm sees none of it", () => {
    const { ime, sent } = make();
    const took = [...syllable(ime, ["ㅇ", "아", "안", "안"]), ...syllable(ime, ["ㄴ", "녀", "녕", "녕"]), ...syllable(ime, ["ㅎ", "하", "핫", "하"])];
    expect(took.every(Boolean)).toBe(true);
    expect(sent).toEqual(["안", "녕"]);
    // Enter right after the last syllable: the syllable first, then Enter is xterm's
    expect(ime.keydown({ key: "Enter", keyCode: 13 })).toBe(false);
    expect(sent).toEqual(["안", "녕", "하"]);
  });

  it("a space or a Latin key the input method passes through ends the syllable; their text stays xterm's", () => {
    const { ime, sent } = make();
    syllable(ime, ["ㅎ", "하", "한"]);
    expect(ime.keydown({ key: " ", keyCode: 32 })).toBe(false);
    expect(sent).toEqual(["한"]);
    // the space's own insertText (xterm did not cancel the key) is xterm's to send
    expect(ime.input("insertText", " ", true)).toBe(false);
    expect(ime.input("insertText", " ")).toBe(false);
    expect(ime.keydown({ key: "a", keyCode: 65 })).toBe(false);
    expect(sent).toEqual(["한"]);
  });

  it("losing focus sends the syllable; the input method taking it back sends nothing", () => {
    const { ime, sent, shown } = make();
    syllable(ime, ["ㄱ", "그", "글"]);
    ime.flush();
    expect(sent).toEqual(["글"]);
    expect(shown.at(-1)).toBeNull();
    syllable(ime, ["ㄱ"]);
    expect(ime.input("deleteContentBackward", null)).toBe(true);
    ime.flush();
    expect(sent).toEqual(["글"]);
  });

  it("modifiers alone keep the syllable open; an edit with nothing held is not taken", () => {
    const { ime, sent } = make();
    syllable(ime, ["ㅎ", "하"]);
    expect(ime.keydown({ key: "Shift", keyCode: 16 })).toBe(false);
    expect(sent).toEqual([]);
    ime.flush();
    expect(ime.input("insertReplacementText", "x", true)).toBe(false);
    expect(ime.input("insertReplacementText", "x")).toBe(false);
  });
});

describe("composition events (Chromium, and Japanese or Chinese everywhere)", () => {
  it("sends a composition's text once, at its end", () => {
    const { ime, sent, shown } = make();
    ime.compositionStart();
    for (const s of ["ㅎ", "하", "한"]) {
      ime.compositionUpdate(s);
      expect(ime.input("insertCompositionText", s, true)).toBe(true);
      expect(ime.input("insertCompositionText", s)).toBe(true);
    }
    expect(shown.at(-1)).toBe("한");
    ime.compositionEnd("한");
    expect(sent).toEqual(["한"]);
    expect(shown.at(-1)).toBeNull();
  });

  it("Enter while the last syllable is still composing sends the syllable first, and its late end sends nothing", () => {
    const { ime, sent } = make();
    ime.compositionStart();
    ime.compositionUpdate("ㄱ");
    ime.compositionUpdate("글");
    expect(ime.keydown({ key: "Enter", keyCode: 13 })).toBe(false);
    expect(sent).toEqual(["글"]);
    // what Chromium sends after that Enter: input of an empty composition, then the end
    expect(ime.input("insertCompositionText", "")).toBe(true);
    ime.compositionEnd("글");
    expect(sent).toEqual(["글"]);
    // the next composition is sent again as usual
    ime.compositionStart();
    ime.compositionUpdate("요");
    ime.compositionEnd("요");
    expect(sent).toEqual(["글", "요"]);
  });

  it("keyCode 229 keys belong to the input method", () => {
    const { ime } = make();
    expect(ime.keydown({ key: "Process", keyCode: 229 })).toBe(true);
    expect(ime.keydown({ key: "Enter", keyCode: 229 })).toBe(true);
  });
});
