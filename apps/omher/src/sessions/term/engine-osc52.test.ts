import { describe, expect, it } from "vitest";
import { OSC52_ACTIVE_MS, OSC52_MAX_CHARS, osc52Allowed, parseOsc52 } from "./engine-osc52";
import { parseTermSettings, TERM_DEFAULTS } from "./settings";

const b64 = (s: string) => Buffer.from(s, "utf8").toString("base64");

describe("OSC 52", () => {
  it("decodes the text a program copies, UTF-8 included, for any target", () => {
    expect(parseOsc52(`c;${b64("hello")}`)).toBe("hello");
    expect(parseOsc52(`;${b64("no target")}`)).toBe("no target");
    expect(parseOsc52(`p;${b64("한글 복사")}`)).toBe("한글 복사");
    expect(parseOsc52(`s0;${b64("line one\nline two")}`)).toBe("line one\nline two");
    expect(parseOsc52(`q;${b64("q target")}`)).toBe("q target");
    expect(parseOsc52("c;aGVsbG8")).toBe("hello"); // unpadded
    expect(parseOsc52("c;aGVs bG8=")).toBe("hello"); // split by a space
    expect(parseOsc52(`c;${b64("tab\there\r\n")}`)).toBe("tab\there\r\n");
  });

  it("drops text holding control characters a paste would act on (ESC, Ctrl-O, C1)", () => {
    expect(parseOsc52(`c;${b64("\x1b[201~rm -rf ~\x0f")}`)).toBeNull();
    expect(parseOsc52(`c;${b64("run\x0f")}`)).toBeNull();
    expect(parseOsc52(`c;${b64("c1 \u009b x")}`)).toBeNull();
    expect(parseOsc52(`c;${b64("nul\x00")}`)).toBeNull();
  });

  it("never answers a query and drops what is malformed, empty, not UTF-8 or too long", () => {
    expect(parseOsc52("c;?")).toBeNull();
    expect(parseOsc52("c;")).toBeNull();
    expect(parseOsc52(b64("no semicolon"))).toBeNull();
    expect(parseOsc52("x;aGVsbG8=")).toBeNull();
    expect(parseOsc52("c;not*base64")).toBeNull();
    expect(parseOsc52(`c;${btoa("\xff\xfe")}`)).toBeNull();
    expect(parseOsc52(`c;${b64("a".repeat(OSC52_MAX_CHARS + 1))}`)).toBeNull();
    expect(parseOsc52(`c;${b64("a".repeat(OSC52_MAX_CHARS))}`)).toHaveLength(OSC52_MAX_CHARS);
    expect(parseOsc52("c;aGVsbG8==")).toBeNull(); // over-padded
    // the length check alone: base64 longer than the most OSC52_MAX_CHARS can encode is refused before decoding
    expect(parseOsc52(`c;${"A".repeat(4 * OSC52_MAX_CHARS + 8)}`)).toBeNull();
    // the cap counts UTF-16 units: an astral character is two
    expect(parseOsc52(`c;${b64("😀".repeat(OSC52_MAX_CHARS / 2))}`)).toHaveLength(OSC52_MAX_CHARS);
    expect(parseOsc52(`c;${b64("😀".repeat(OSC52_MAX_CHARS / 2 + 1))}`)).toBeNull();
  });

  it("takes a copy only from the terminal with the keyboard, within a moment of the person's key or click", () => {
    expect(osc52Allowed(true, 10_000, 10_000 - 50)).toBe(true);
    expect(osc52Allowed(true, 10_000, 10_000 - OSC52_ACTIVE_MS)).toBe(true);
    expect(osc52Allowed(true, 10_000, 10_000 - OSC52_ACTIVE_MS - 1)).toBe(false);
    expect(osc52Allowed(false, 10_000, 10_000 - 50)).toBe(false);
    expect(osc52Allowed(true, 10_000, -Infinity)).toBe(false);
  });

  it("is on by default and kept as the person sets it", () => {
    expect(TERM_DEFAULTS.osc52).toBe(true);
    expect(parseTermSettings({ osc52: false }).osc52).toBe(false);
    expect(parseTermSettings({ osc52: "yes" }).osc52).toBe(true);
  });
});
