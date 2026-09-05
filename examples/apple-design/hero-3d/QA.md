# OMH 3D Hero: Observed Browser QA

Checked on 2026-09-05 in Chromium on macOS, with WebGL 1 through
`ANGLE (Apple, ANGLE Metal Renderer: Apple M4 Pro, Unspecified Version)`.
These captures are reusable example outputs, not an autonomous Hermes run.

## Source binding

SHA-256 for the source used by the final captures:

| File | SHA-256 |
| --- | --- |
| `index.html` | `f4df3d81807c09809e656c237bfc515f3eb1330eb623fe81b44469bde91fe065` |
| `renderer.js` | `62d5d8eb701439a1b2aecd962352511d854810b395e8375185428e3edc308661` |

## Observed cases

| Scenario | Action | Observed result | Artifact |
| --- | --- | --- | --- |
| Desktop comparison | Open `index.html` at 1600 x 1050; await `omh-hero-ready` or an already-ready state after fonts load | Both canvases compile, link, draw, and finish; GL error 0; same geometry and camera, different materials and lighting | [Desktop](before-after.png) |
| Responsive composition | Open at 390 x 844 and capture the full page after readiness | Both renders succeed; no horizontal overflow; panels stack and footer is visible below them | [Mobile](mobile.png) |
| Renderer unavailable | Start a separate browser with `--disable-webgl` and open the same page | Both contexts are unavailable; state is `missing-webgl`, render count is 0, and two visible fallback messages replace the renders | [Fallback](no-webgl.png) |
| Layout regression | Assert footer top is at or below the panel container bottom in both viewports | Desktop: both bounds are 1005; mobile: both are 979; neither overlaps | [Desktop](before-after.png), [mobile](mobile.png) |
| Offline example | Load through `file://`; inspect resource timing and page errors | Ready state with no HTTP(S) resource entries; browser error command lists no page errors | [Desktop](before-after.png) |

Capture commands used `agent-browser` with isolated sessions, viewport set
before navigation, `document.fonts.ready`, and the renderer's exact completion
event/state. The event is emitted after both `gl.finish()` calls. No fixed
sleep, polling loop, or animation-timing guess was used. The renderer is static.

`node --check renderer.js` also completed successfully. HTML/JavaScript LSP
checks could not run because Biome and `typescript-language-server` are not
installed; no dependencies were added for these diagnostics.

## Visual review and corrections

The refined render visibly separates a reflective silver link from a cool,
transmissive glass link; the baseline uses blue polymer throughout. Both keep
the same silhouette, pose, camera, scale, copy, and studio composition.
The baseline is illustrative, not a screenshot of a shipped OMH product.

The first desktop capture showed stepped silhouette edges at a 1x backing
resolution. The static renderer now supersamples at 2x within its existing
pixel budget. The first mobile capture also exposed a footer hidden behind
the second panel: removing the body's fixed height corrected the flow.
The linked captures were taken after both corrections and inspected directly.

## Limits

This proves the local procedural 3D example, not a validated path tracer,
exported mesh, animation, native Liquid Glass, or assistive-technology audit.
Image generation was attempted but its configured model returned
`model_not_found`; the delivered image is instead an observed WebGL render.

GSAP, Paper liquid-logo, and liquid-glass-js are separate optional production
references in the skill. None is installed or executed by this example, and
these screenshots are not evidence of those libraries running.
