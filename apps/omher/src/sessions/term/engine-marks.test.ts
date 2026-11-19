// engine-marks.ts: what is read from OSC 133 marks, OSC 7 folders and OSC 9;4 progress, and where a prompt jump goes.
import { describe, expect, it } from "vitest";
import { nextPrompt, parse133, parseOsc7, parseProgress } from "./engine-marks";

describe("parse133", () => {
  it("reads the four marks and a finished command's exit code", () => {
    expect(parse133("A")).toEqual({ kind: "A", exit: null });
    expect(parse133("B")).toEqual({ kind: "B", exit: null });
    expect(parse133("C")).toEqual({ kind: "C", exit: null });
    expect(parse133("D")).toEqual({ kind: "D", exit: null });
    expect(parse133("D;0")).toEqual({ kind: "D", exit: 0 });
    expect(parse133("D;1")).toEqual({ kind: "D", exit: 1 });
    expect(parse133("D;130")).toEqual({ kind: "D", exit: 130 });
  });
  it("takes extra fields after the letter (a prompt's options) and an unreadable code as none", () => {
    expect(parse133("A;k=i;cl=m")).toEqual({ kind: "A", exit: null });
    expect(parse133("D;x")).toEqual({ kind: "D", exit: null });
    expect(parse133("D;99999999999")).toEqual({ kind: "D", exit: null });
  });
  it("reads nothing from another letter or an empty mark", () => {
    expect(parse133("")).toBeNull();
    expect(parse133("P;k=v")).toBeNull();
    expect(parse133("a")).toBeNull();
    expect(parse133("AB")).toBeNull();
  });
});

describe("parseOsc7", () => {
  it("takes an empty host, localhost and this computer's name", () => {
    expect(parseOsc7("file:///home/you/code")).toBe("/home/you/code");
    expect(parseOsc7("file://localhost/home/you")).toBe("/home/you");
    expect(parseOsc7("file://LOCALHOST./tmp")).toBe("/tmp");
    expect(parseOsc7("file://my-mac.local/Users/you", ["my-mac.local"])).toBe("/Users/you");
    expect(parseOsc7("file://My-Mac.local./Users/you", ["my-mac.local"])).toBe("/Users/you");
  });
  it("refuses another computer's folder", () => {
    expect(parseOsc7("file://build-box/home/ci")).toBeNull();
    expect(parseOsc7("file://my-mac.local/Users/you")).toBeNull();
    expect(parseOsc7("file://evil.example/tmp", ["my-mac.local"])).toBeNull();
    expect(parseOsc7("file://user@localhost/tmp")).toBeNull();
  });
  it("percent-decodes the path", () => {
    expect(parseOsc7("file:///tmp/x%20y")).toBe("/tmp/x y");
    expect(parseOsc7("file:///Users/you/%ED%95%9C%EA%B8%80")).toBe("/Users/you/한글");
  });
  it("refuses a relative path, a broken escape and control characters", () => {
    expect(parseOsc7("file://localhost")).toBeNull();
    expect(parseOsc7("file:relative/path")).toBeNull();
    expect(parseOsc7("file:///tmp/%E0%A4%A")).toBeNull();
    expect(parseOsc7("file:///tmp/a%0Ab")).toBeNull();
    expect(parseOsc7("file:///tmp/a%1B]0;x%07")).toBeNull();
    expect(parseOsc7(`file:///${"a".repeat(5000)}`)).toBeNull();
  });
  it("refuses every scheme but file", () => {
    expect(parseOsc7("http://localhost/tmp")).toBeNull();
    expect(parseOsc7("https:///tmp")).toBeNull();
    expect(parseOsc7("kitty-shell-cwd://localhost/tmp")).toBeNull();
    expect(parseOsc7("/tmp")).toBeNull();
    expect(parseOsc7("")).toBeNull();
  });
  it("takes the scheme in any case and a Windows drive path", () => {
    expect(parseOsc7("FILE:///tmp")).toBe("/tmp");
    expect(parseOsc7("file:///C:/Users/you")).toBe("C:/Users/you");
  });
});

describe("parseProgress", () => {
  it("reads working for states 1, 2 and 3 and done for 0", () => {
    expect(parseProgress("4;1;50")).toBe("busy");
    expect(parseProgress("4;2;10")).toBe("busy");
    expect(parseProgress("4;3")).toBe("busy");
    expect(parseProgress("4;3;0")).toBe("busy");
    expect(parseProgress("4;0")).toBe("done");
    expect(parseProgress("4;0;0")).toBe("done");
  });
  it("reads no progress from a message or another report", () => {
    expect(parseProgress("Needs your approval")).toBeNull();
    expect(parseProgress("4;4;10")).toBeNull();
    expect(parseProgress("4")).toBeNull();
    expect(parseProgress("4;1;50;extra")).toBeNull();
    expect(parseProgress("1;2")).toBeNull();
  });
});

describe("nextPrompt", () => {
  const lines = [3, 40, 90];
  it("goes to the nearest prompt above or below", () => {
    expect(nextPrompt(lines, 100, -1)).toBe(90);
    expect(nextPrompt(lines, 90, -1)).toBe(40);
    expect(nextPrompt(lines, 41, -1)).toBe(40);
    expect(nextPrompt(lines, 3, 1)).toBe(40);
    expect(nextPrompt(lines, 0, 1)).toBe(3);
  });
  it("has none past the first or the last", () => {
    expect(nextPrompt(lines, 3, -1)).toBeNull();
    expect(nextPrompt(lines, 90, 1)).toBeNull();
    expect(nextPrompt([], 10, -1)).toBeNull();
  });
});
