// The two decisions behind the GPU renderer, kept pure so they can be tested without a browser:
// whether this machine should try WebGL at all (`auto`), and when a terminal that keeps losing its context stops
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
  reason: "hardware" | "no-webgl2" | "software-renderer" | "linux-renderer-unknown" | "macos-measured-slower";
}

/** Software rasterizers: drawing with these is slower than the standard renderer. */
export const SOFTWARE_RENDERER = /\b(swiftshader|llvmpipe|softpipe|software rasterizer|software adapter|basic render|microsoft basic|virgl|svga3d)\b/i;

/** `auto`: yes unless there is no WebGL2 or the renderer is a software one. Where the browser hides the renderer's
 *  name (WebKit does) the machine is trusted, except on Linux, where a hidden name has gone with corrupt glyphs.
 *  On macOS `auto` stays on the standard renderer: bench/render measured the add-on slower on a full-screen redraw
 *  (scenarios C and C2: about 2 to 3 times the wall time in WebKit and in Chromium on Metal) and only a few percent
 *  faster on streaming text (WebKit), so not better in every scenario. `gpu: "on"` still uses it. Windows and Linux
 *  were not measured: `auto` there allows a hardware renderer. */
export function decideWebgl(info: WebglInfo): WebglDecision {
  if (!info.webgl2) return { allow: false, reason: "no-webgl2" };
  if (info.mac) return { allow: false, reason: "macos-measured-slower" };
  const identity = `${info.vendor ?? ""} ${info.renderer ?? ""}`.trim();
  if (!identity) return info.linux ? { allow: false, reason: "linux-renderer-unknown" } : { allow: true, reason: "hardware" };
  if (SOFTWARE_RENDERER.test(identity)) return { allow: false, reason: "software-renderer" };
  return { allow: true, reason: "hardware" };
}

let probed: WebglDecision | null = null;

/** Ask the page once (a throw-away canvas), then remember the answer. */
export function probeWebgl(): WebglDecision {
  if (probed) return probed;
  let info: WebglInfo = { webgl2: false, renderer: null, vendor: null, linux: false, mac: false };
  try {
    const linux = /Linux/.test(navigator.platform) || /Linux/.test(navigator.userAgent);
    const mac = /Mac/.test(navigator.platform);
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
