import { describe, expect, it } from "vitest";
import { canRetry, decideWebgl, LOSS_LIMIT, LOSS_WINDOW_MS, recordLoss } from "./engine-policy";

const info = (o: Partial<Parameters<typeof decideWebgl>[0]> = {}) => ({ webgl2: true, renderer: "ANGLE (Apple, Apple M4 Pro, OpenGL 4.1)", vendor: "Google Inc. (Apple)", linux: false, ...o });

describe("the auto rule", () => {
  it("allows a hardware renderer", () => {
    expect(decideWebgl(info())).toEqual({ allow: true, reason: "hardware" });
  });
  it("refuses when there is no WebGL2", () => {
    expect(decideWebgl(info({ webgl2: false, renderer: null, vendor: null }))).toEqual({ allow: false, reason: "no-webgl2" });
  });
  it.each(["Google SwiftShader", "llvmpipe (LLVM 15.0.7, 256 bits)", "softpipe", "Microsoft Basic Render Driver", "Mesa virgl", "Software Rasterizer"])("refuses the software renderer %s", (renderer) => {
    expect(decideWebgl(info({ renderer, vendor: "" }))).toEqual({ allow: false, reason: "software-renderer" });
    expect(decideWebgl(info({ renderer: "ANGLE (Google, Vulkan, " + renderer + ")" })).allow).toBe(false);
  });
  it("trusts a browser that hides the renderer's name, except on Linux", () => {
    expect(decideWebgl(info({ renderer: null, vendor: null })).allow).toBe(true);
    expect(decideWebgl(info({ renderer: null, vendor: null, linux: true }))).toEqual({ allow: false, reason: "linux-renderer-unknown" });
  });
});

describe("the context-loss policy", () => {
  it("keeps trying after one or two losses", () => {
    let l: number[] = [];
    for (const t of [0, 1000]) {
      l = recordLoss(l, t);
      expect(canRetry(l, t)).toBe(true);
    }
  });
  it(`stops at ${LOSS_LIMIT} losses inside ${LOSS_WINDOW_MS / 1000} s`, () => {
    let l: number[] = [];
    for (const t of [0, 10_000, 20_000]) l = recordLoss(l, t);
    expect(canRetry(l, 20_000)).toBe(false);
    expect(canRetry(l, 59_999)).toBe(false);
  });
  it("tries again once the window has moved past the losses", () => {
    let l: number[] = [];
    for (const t of [0, 10_000, 20_000]) l = recordLoss(l, t);
    // a 4th attempt after the first loss left the window: only two losses still count
    expect(canRetry(l, 60_001)).toBe(true);
    l = recordLoss(l, 60_001);
    expect(l).toEqual([10_000, 20_000, 60_001]);
    expect(canRetry(l, 60_001)).toBe(false);
  });
});
