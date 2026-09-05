# Materials and Accessibility

## Source record

- Apple guidance, accessed 2026-09-05: https://developer.apple.com/design/human-interface-guidelines/materials
- Apple guidance, accessed 2026-09-05: https://developer.apple.com/tutorials/data/design/human-interface-guidelines/materials.json
- Apple guidance, accessed 2026-09-05: https://developer.apple.com/documentation/technologyoverviews/adopting-liquid-glass.md
- Apple guidance, accessed 2026-09-05: https://developer.apple.com/design/human-interface-guidelines/accessibility
- Web standard, accessed 2026-09-05: https://www.w3.org/WAI/standards-guidelines/wcag/

## Materials

Liquid Glass belongs to the controls and navigation layer; standard materials
belong behind content. Use custom glass sparingly. Prefer regular material when
text legibility matters, and clear material only over rich-media backgrounds.
The explicit exception is transient interactive content controls, where the
current Apple guidance may justify the control-layer treatment. Native Liquid
Glass is not a CSS `backdrop-filter` recipe.

Apple's materials guidance includes a bright-content example that considers 35%
dark dimming. Carry that as conditional source-applicable guidance, never as a
universal CSS token or a fixed opacity recipe. Respect current API and version
availability, different appearances, Reduce Transparency, and Increase
Contrast. For web approximations, offer an opaque fallback rather than claiming
native material behavior.

## Access and input

For native work, identify system control semantics, VoiceOver labels, Full
Keyboard Access and keyboard paths, gesture alternatives, Reduce Motion, and
appearance/contrast behavior. Dynamic Type applies to iOS and iPadOS, while
macOS uses system styles, app text scaling, and adaptive layout. Verify with the
current platform APIs and the actual target state.

For Apple-inspired web, require semantic HTML, keyboard and focus behavior,
reflow/zoom, contrast, pointer targets, motion reduction, and WCAG
applicability. An accessibility plan is not WCAG PASS: hand observed proof to
`accessibility-audit`; hand rendered state and motion evidence to `visual-qa`.

## Boundary

Use the Apple records for Apple-platform applicability and the W3C record for
web-standard applicability. Neither source grants certification; unobserved
screens, assistive-tech behavior, and rendered states remain not_observed.
