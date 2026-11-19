import { afterEach, describe, expect, it, vi } from "vitest";
import { canRetry, decideHardware, decidePlatform, decideWebgl, LOSS_LIMIT, LOSS_WINDOW_MS, probeWebgl, recordLoss, resetWebglProbe } from "./engine-policy";

const info = (o: Partial<Parameters<typeof decideWebgl>[0]> = {}) => ({ webgl2: true, renderer: "ANGLE (Apple, Apple M4 Pro, OpenGL 4.1)", vendor: "Google Inc. (Apple)", linux: false, mac: false, ...o });

describe("auto: the GPU renderer wherever the hardware allows it, so CLI block art draws without seams", () => {
  it("lets the hardware rule decide on every platform", () => {
    for (const mac of [true, false]) expect(decidePlatform({ mac }), JSON.stringify({ mac })).toBeNull();
    expect(decideWebgl(info({ mac: true }))).toEqual({ allow: true, reason: "hardware" });
    expect(decideWebgl(info({ mac: true, renderer: null, vendor: null })).allow).toBe(true);
    expect(decideWebgl(info({ renderer: "ANGLE (NVIDIA, NVIDIA GeForce RTX 4070 Direct3D11 vs_5_0 ps_5_0, D3D11)", vendor: "Google Inc. (NVIDIA)" })).allow).toBe(true);
  });
  it("still keeps the standard renderer without WebGL2 or on a software rasterizer", () => {
    expect(decideWebgl(info({ mac: true, webgl2: false, renderer: null, vendor: null }))).toEqual({ allow: false, reason: "no-webgl2" });
    expect(decideWebgl(info({ linux: true, renderer: "llvmpipe (LLVM 15.0.7, 256 bits)", vendor: "" }))).toEqual({ allow: false, reason: "software-renderer" });
  });

  describe("the probe", () => {
    afterEach(() => {
      vi.unstubAllGlobals();
      resetWebglProbe();
    });
    it("asks one throw-away WebGL2 canvas what the hardware is, then remembers", () => {
      resetWebglProbe();
      const lose = vi.fn();
      const gl = { getExtension: (n: string) => (n === "WEBGL_lose_context" ? { loseContext: lose } : null), getParameter: () => null };
      const createElement = vi.fn(() => ({ getContext: () => gl }));
      vi.stubGlobal("navigator", { platform: "MacIntel", userAgent: "Mac" });
      vi.stubGlobal("document", { createElement });
      expect(probeWebgl()).toEqual({ allow: true, reason: "hardware" });
      expect(probeWebgl().allow).toBe(true);
      expect(createElement).toHaveBeenCalledTimes(1);
      expect(lose).toHaveBeenCalledTimes(1);
    });
    it("keeps the standard renderer when the page has no WebGL2", () => {
      resetWebglProbe();
      vi.stubGlobal("navigator", { platform: "MacIntel", userAgent: "Mac" });
      vi.stubGlobal("document", { createElement: () => ({ getContext: () => null }) });
      expect(probeWebgl()).toEqual({ allow: false, reason: "no-webgl2" });
    });
  });
});

describe("the hardware rule", () => {
  it("allows a hardware renderer", () => {
    expect(decideHardware(info())).toEqual({ allow: true, reason: "hardware" });
  });
  it("refuses when there is no WebGL2", () => {
    expect(decideHardware(info({ webgl2: false, renderer: null, vendor: null }))).toEqual({ allow: false, reason: "no-webgl2" });
  });
  it.each(["Google SwiftShader", "llvmpipe (LLVM 15.0.7, 256 bits)", "softpipe", "Microsoft Basic Render Driver", "Mesa virgl", "Software Rasterizer"])("refuses the software renderer %s", (renderer) => {
    expect(decideHardware(info({ renderer, vendor: "" }))).toEqual({ allow: false, reason: "software-renderer" });
    expect(decideHardware(info({ renderer: "ANGLE (Google, Vulkan, " + renderer + ")" })).allow).toBe(false);
  });
  it("trusts a browser that hides the renderer's name, except on Linux", () => {
    expect(decideHardware(info({ renderer: null, vendor: null })).allow).toBe(true);
    expect(decideHardware(info({ renderer: null, vendor: null, linux: true }))).toEqual({ allow: false, reason: "linux-renderer-unknown" });
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
