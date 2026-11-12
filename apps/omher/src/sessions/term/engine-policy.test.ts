import { afterEach, describe, expect, it, vi } from "vitest";
import { canRetry, decideHardware, decidePlatform, decideWebgl, LOSS_LIMIT, LOSS_WINDOW_MS, probeWebgl, recordLoss, resetWebglProbe } from "./engine-policy";

const info = (o: Partial<Parameters<typeof decideWebgl>[0]> = {}) => ({ webgl2: true, renderer: "ANGLE (Apple, Apple M4 Pro, OpenGL 4.1)", vendor: "Google Inc. (Apple)", linux: false, mac: false, ...o });

describe("auto: the standard renderer on every platform until the add-on is measured faster there", () => {
  it("stays on the standard renderer on macOS, where the bench measured the GPU slower on full-screen redraws", () => {
    expect(decideWebgl(info({ mac: true }))).toEqual({ allow: false, reason: "macos-measured-slower" });
    expect(decideWebgl(info({ mac: true, renderer: null, vendor: null })).allow).toBe(false);
  });
  it("stays on the standard renderer with a hardware renderer on Windows and Linux too: nothing was measured there", () => {
    expect(decideWebgl(info())).toEqual({ allow: false, reason: "not-measured" });
    expect(decideWebgl(info({ linux: true, renderer: "Mesa Intel(R) UHD Graphics 620 (KBL GT2)", vendor: "Intel" }))).toEqual({ allow: false, reason: "not-measured" });
    expect(decideWebgl(info({ renderer: "ANGLE (NVIDIA, NVIDIA GeForce RTX 4070 Direct3D11 vs_5_0 ps_5_0, D3D11)", vendor: "Google Inc. (NVIDIA)" }))).toEqual({ allow: false, reason: "not-measured" });
  });
  it("never allows the add-on, whatever the machine", () => {
    for (const webgl2 of [true, false])
      for (const mac of [true, false])
        for (const linux of [true, false])
          for (const renderer of [null, "Apple M4 Pro", "llvmpipe", "ANGLE (Intel, Intel(R) Iris(R) Xe Graphics Direct3D11)"]) {
            expect(decidePlatform({ mac }), JSON.stringify({ mac })).not.toBeNull();
            expect(decideWebgl({ webgl2, mac, linux, renderer, vendor: null }).allow, JSON.stringify({ webgl2, mac, linux, renderer })).toBe(false);
          }
  });

  describe("the probe", () => {
    afterEach(() => {
      vi.unstubAllGlobals();
      resetWebglProbe();
    });
    it.each(["MacIntel", "Win32", "Linux x86_64"])("makes no WebGL context to say no on %s", (platform) => {
      resetWebglProbe();
      const createElement = vi.fn(() => {
        throw new Error("auto asked the page for a canvas");
      });
      vi.stubGlobal("navigator", { platform, userAgent: platform });
      vi.stubGlobal("document", { createElement });
      expect(probeWebgl().allow).toBe(false);
      expect(probeWebgl().reason).toBe(platform === "MacIntel" ? "macos-measured-slower" : "not-measured");
      expect(createElement).not.toHaveBeenCalled();
    });
  });
});

describe("the hardware rule, for a platform that has been measured", () => {
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
