# Design Example QA

Observed on 2026-09-05 using Chrome/152.0.7977.64 on macOS. The page was loaded
directly from `index.html` through `file://`; no server or extra dependency was
needed. This report describes the actual example, not its fictional onboarding
project or sample review findings.

## Capture lineage

The inspected HTML SHA-256 is
`0816ad1ca40fbd08b10aa33b184247ea2b686d7c4f8e5a23a0de989ac35dcfdf`.
All previews were recaptured after the final CSS correction.

| Preview | State | Capture |
| --- | --- | --- |
| [Desktop](previews/desktop.png) | Auto with a light system appearance, Web platform, review notes closed | 1440 CSS-pixel viewport, full page |
| [Mobile](previews/mobile.png) | Auto with a light system appearance, Web platform, review notes closed | 375 × 1100 viewport |
| [Dark](previews/dark.png) | Explicit Dark override, Web platform, review notes closed | 1440 CSS-pixel viewport, full page |
| [Specimen](previews/specimen.png) | Explicit Light override, specimen anchor selected | 1440 × 1100 viewport |

Font readiness and animation completion were awaited before capture; browser
paint frames were observed after navigation. No fixed sleeps were used.
Each final image was inspected for clipping, missing layers, text hierarchy,
spacing, and legibility.

## Observed checks

- Document width matched the viewport at 375, 768, 1280, and 1440 CSS pixels.
- At 200% root text size, document width still matched 375- and 768-pixel
  viewports. Initial checks found an unwrappable header/direction row and a
  narrow definition-list value. Wrapping and grid-track sizing were corrected;
  horizontal overflow was not hidden.
- Appearance radios changed the rendered palette. Each iOS/macOS/Web radio
  displayed its matching platform note and hid the other notes.
- A native review-note control emitted the expected `toggle` event when
  opened and closed.
- Keyboard Tab exposed and focused the skip link with `:focus-visible`.
- Reduced-motion emulation left no running animations.
- Reduced-transparency and increased-contrast emulation produced opaque
  toolbar/sidebar backgrounds with `backdrop-filter: none`.
- The resource performance entries contained no HTTP(S) asset requests.

## Limits

Safari, Firefox, native iOS/macOS apps, VoiceOver output, forced-colors mode,
and behavior in browsers without `:has()` were not exercised. Root text
enlargement tests reflow but are not a substitute for every browser's zoom or
OS text-setting behavior. This browser pass is not WCAG certification, native
Liquid Glass verification, or Apple endorsement.
