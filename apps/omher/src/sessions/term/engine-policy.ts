// The two decisions behind the GPU renderer, kept pure so they can be tested without a browser:
// whether `auto` uses WebGL on this machine, and when a terminal that keeps losing its context stops
// trying. Ported in idea from Orca's terminal-webgl-auto-policy.ts and pane-webgl-context-loss-policy.ts.

/** What the page can tell about WebGL. `renderer`/`vendor` are the unmasked strings when the browser gives them. */
export interface WebglInfo {
  webgl2: boolean;
  renderer: string | null;
  vendor: string | null;
  linux: boolean;
  mac: boolean;
}

export interface WebglDecision {
  allow: boolean;
  reason: "hardware" | "no-webgl2" | "software-renderer" | "linux-renderer-unknown" | "macos-measured-slower" | "not-measured";
}

/** Software rasterizers: drawing with these is slower than the standard renderer. */
export const SOFTWARE_RENDERER = /\b(swiftshader|llvmpipe|softpipe|software rasterizer|software adapter|basic render|microsoft basic|virgl|svga3d)\b/i;

/** `auto` by platform alone, before anything is asked of WebGL: the standard renderer everywhere, for now.
 *  macOS was measured (bench/render): the add-on is about 2 to 3 times slower on a full-screen redraw (scenarios C
 *  and C2, in WebKit and in Chromium on Metal) and only a few percent faster on streaming text (WebKit). Windows
 *  and Linux were never measured, so `auto` does not use the add-on there either until somebody measures it
 *  faster; that platform then returns null here and the hardware rule below decides. `gpu: "on"` still tries the
 *  add-on everywhere. */
export function decidePlatform(info: Pick<WebglInfo, "mac">): WebglDecision | null {
  return { allow: false, reason: info.mac ? "macos-measured-slower" : "not-measured" };
}

/** The hardware rule (Orca's), for a platform `decidePlatform` lets through: yes unless there is no WebGL2 or the
 *  renderer is a software one. Where the browser hides the renderer's name (WebKit does) the machine is trusted,
 *  except on Linux, where a hidden name has gone with corrupt glyphs. */
export function decideHardware(info: WebglInfo): WebglDecision {
  if (!info.webgl2) return { allow: false, reason: "no-webgl2" };
  const identity = `${info.vendor ?? ""} ${info.renderer ?? ""}`.trim();
  if (!identity) return info.linux ? { allow: false, reason: "linux-renderer-unknown" } : { allow: true, reason: "hardware" };
  if (SOFTWARE_RENDERER.test(identity)) return { allow: false, reason: "software-renderer" };
  return { allow: true, reason: "hardware" };
}

/** `auto` on this machine: the platform first, then its hardware. */
export function decideWebgl(info: WebglInfo): WebglDecision {
  return decidePlatform(info) ?? decideHardware(info);
}

let probed: WebglDecision | null = null;

/** Ask the page once, then remember the answer. A platform that is decided without its hardware makes no WebGL
 *  context at all; otherwise a throw-away canvas tells what the hardware is. */
export function probeWebgl(): WebglDecision {
  if (probed) return probed;
  let info: WebglInfo = { webgl2: false, renderer: null, vendor: null, linux: false, mac: false };
  try {
    const linux = /Linux/.test(navigator.platform) || /Linux/.test(navigator.userAgent);
    const mac = /Mac/.test(navigator.platform);
    const byPlatform = decidePlatform({ mac });
    if (byPlatform) return (probed = byPlatform);
    const canvas = document.createElement("canvas");
    const gl = canvas.getContext("webgl2");
    if (gl) {
      const dbg = gl.getExtension("WEBGL_debug_renderer_info");
      info = {
        webgl2: true,
        linux,
        mac,
        renderer: dbg ? String(gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) ?? "") || null : null,
        vendor: dbg ? String(gl.getParameter(dbg.UNMASKED_VENDOR_WEBGL) ?? "") || null : null,
      };
      gl.getExtension("WEBGL_lose_context")?.loseContext();
    }
  } catch {
    /* no WebGL here */
  }
  return (probed = decideWebgl(info));
}

/** Tests: forget the probe. */
export function resetWebglProbe(): void {
  probed = null;
}

export const LOSS_LIMIT = 3;
export const LOSS_WINDOW_MS = 60_000;

/** Add a context loss at `now` to the ones still inside the window; returns the kept list. */
export function recordLoss(losses: readonly number[], now: number): number[] {
  return [...losses.filter((t) => t > now - LOSS_WINDOW_MS), now];
}

/** Try the GPU renderer again after these losses? Three inside the window stop it; once the window has moved on the
 *  count falls and the next try is allowed. */
export function canRetry(losses: readonly number[], now: number): boolean {
  return losses.filter((t) => t > now - LOSS_WINDOW_MS).length < LOSS_LIMIT;
}
