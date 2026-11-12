# Apple Platform Foundations

## Source record

- Apple guidance, accessed 2026-09-05: https://developer.apple.com/design/human-interface-guidelines/
- Apple guidance, accessed 2026-09-05: https://developer.apple.com/design/human-interface-guidelines/designing-for-ios
- Apple guidance, accessed 2026-09-05: https://developer.apple.com/design/human-interface-guidelines/designing-for-ipados
- Apple guidance, accessed 2026-09-05: https://developer.apple.com/design/human-interface-guidelines/designing-for-macos
- Apple guidance, accessed 2026-09-05: https://developer.apple.com/tutorials/data/design/human-interface-guidelines/typography.json
- Apple guidance, accessed 2026-09-05: https://developer.apple.com/sf-symbols/
- Apple guidance, accessed 2026-09-05: https://developer.apple.com/fonts/

## Frame the brief first

Record mode (`design`, `review`, or `improve`), target OS and current version,
framework, input method, surface and state, current brand/design tokens, and
whether the result is native Apple, Apple-inspired web, or another platform.
Treat a supplied screen, capture, or code path as an **observation** only for
what it shows; label any inferred intent or user behavior as a **hypothesis**.
Make two to four directions before visual production when no direction is
already selected.

## Native iOS and iPadOS

Prefer current system controls and semantic, adaptive colors over manually
recreated controls or hard-coded appearances. Use text styles and Dynamic Type
on iOS and iPadOS; design safe-area, adaptive-window, navigation, keyboard,
pointer, and VoiceOver behavior around the actual target. Standard SwiftUI,
UIKit, and AppKit components follow current SDK behavior, so avoid manual
backgrounds that fight them. Check current API availability for the deployed
platform rather than making a future-version assertion.

## macOS

macOS does **not** support Dynamic Type. Use macOS system styles, application
text-scaling choices, and adaptive layout instead. Keep menu, keyboard,
pointer, window, and VoiceOver behavior native to the selected macOS target;
do not transplant iOS interaction assumptions into a Mac window.

## Apple-inspired web

This is inspiration, not native equivalence. Use system-font fallbacks rather
than embedding system fonts; use appropriately licensed icons rather than
assuming SF Symbols license coverage. Require responsive reflow and zoom,
semantic HTML, visible focus, WCAG review, reduced-motion and
reduced-transparency behavior, and an opaque fallback. Do not equate points
with CSS pixels or prescribe one universal spacing, type, or blur recipe.

## Boundary

This reference covers iOS, iPadOS, macOS, and Apple-inspired web first. Route
other Apple targets to their current official platform documentation. A brief
or direction is prepared guidance, not observed implementation, accessibility
PASS, visual PASS, or Apple certification.
