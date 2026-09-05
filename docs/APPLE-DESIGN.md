# Apple Design

`omh-apple-design` first prepares original Apple marketing/product visuals:
3D hero art direction, studio lighting, camera/object/motion direction, actual
render comparison, and revision through an available renderer or selected coding
owner. It also designs, reviews, and improves native Apple-platform interfaces
and Apple-inspired web UI. These are separate targets; the skill is not Apple
certification, automatic implementation, or a claim that web effects are native
Apple behavior.

## Ask Hermes

After installing the skill through the normal OMH setup or update flow, ask:

- "Review this iPhone settings screen against Apple HIG. Explain the user
  impact and prioritize the fixes."
- "Use omh-apple-design to prepare an Apple-inspired web dashboard. Keep our
  brand, keyboard access, and responsive layout."
- "Review the Liquid Glass navigation in this macOS app, including reduced
  transparency and contrast."
- "Use omh-apple-design to direct an original Apple-style 3D hero: define the
  sculpture, camera, satin metal and optical-glass materials, studio light,
  reduced-motion fallback, and render comparison."

The canonical workflow identifier is `apple-design`; the displayed skill name
is `omh-apple-design`. Explicit invocation supports both names. Non-English
natural-language discovery belongs to Hermes' semantic selection; this change
does not expand OMH's frozen Korean trigger table.

Provide the target surface, platform and OS version, framework, primary task,
existing design system, and available screenshots or source. Hermes should
identify missing inputs rather than invent screens or assume the latest SDK.
An initial design request produces direction and implementation guidance; a
review produces findings tied to supplied evidence. Source inspection alone
does not establish rendered appearance or assistive-technology behavior.

## See designed examples

Open [the OMH design workspace](../examples/apple-design/index.html) locally.
The self-contained page applies the skill to a fictional onboarding brief and
renders a typography, color, material, and action specimen. It includes working
appearance and platform selectors, expandable review findings, and prepared
versus observed handoff notes.

The [example guide](../examples/apple-design/README.md) links browser-captured
desktop and mobile previews and explains the design decisions. This is
illustrative sample data, not a connected OMH dashboard or observed coding run.
The page needs no server, dependencies, or remote assets.

The [OMH 3D hero demonstration](../examples/apple-design/hero-3d/README.md)
presents one original interlocking double-loop sculpture at the same camera on
both sides: a neutral-plastic baseline and a precision satin-aluminum/optical-
glass, studio-lit refinement. Main QA observed a local realtime WebGL1 SDF
ray-marcher capture through ANGLE Metal with GL error 0. It is not an image-
generation result, UI dashboard, exported mesh, validated path trace, or
autonomous Hermes run; the renderer and capture are example provenance, not a
hardware or browser requirement.

## Production modes

Choose the visual target before making a direction: Apple marketing/product
visual, native Apple application, or Apple-inspired web UI. Marketing references
are concrete visual observations, not a replacement for native HIG controls or
an instruction to copy Apple assets. For product visuals, select the reference
by deliverable, define original object/camera/material/light/composition, then
run reference -> actual generation or render -> same-subject comparison ->
revision.

A connected image-generation tool can produce a generated still image; text-only
image tooling prepares prompt variants, not image-to-image edits. When image
generation is unavailable, use an authorized confirmed Blender, local realtime
shader renderer, or other renderer through the selected coding owner when one
is available. A local realtime shader render is not an exported mesh or
validated path trace. Frontend execution may implement a web surface but does
not verify a mesh, physical rendering, animation, or native Liquid Glass. Only
when no execution path is available does Hermes prepare the exact prompt or
scene handoff and name the missing boundary.
Motion needs actual frames, video, or browser evidence plus a reduced-motion
alternative; a still image does not prove it.

## Optional web-production references

For an explicit Apple marketing/product visual or explicit `apple-design`
invocation, consult the generated
[`web-production-libraries` reference](../skills/omh-apple-design/references/web-production-libraries.md)
before asking a selected coding owner to integrate an existing project library.
It covers GSAP sequencing and cleanup, liquid-logo as PolyForm-licensed
link-only shader research, and liquid-glass-js as an MIT web-only effect. It
does not install dependencies, fetch CDN assets, turn generic GSAP/logo work
into Apple work, or claim native Apple material. Each path needs reduced-motion
or static fallback, lifecycle cleanup, and observed rendered evidence.

## Why a separate skill

The Apple-specific gap is platform judgment, not another generic quality gate.

| Existing skill | Its responsibility | What Apple Design adds |
| --- | --- | --- |
| `omh-design-orchestration` | Broad design direction and selection of downstream specialists | An Apple-specific brief once the platform or style intent is known |
| `omh-frontend` | Web/TUI design systems, implementation preparation, responsive states, and performance | A distinction between native Apple conventions and deliberate web adaptations |
| `omh-design-quality-gate` | Quality across websites, decks, PDFs, and other visual deliverables | Current Apple HIG sources rather than a general premium-design bar |
| `omh-accessibility-audit` | Accessibility findings and observed conformance checks | Apple platform settings and input conventions to include in the audit |
| `omh-visual-qa` | Fresh rendered evidence and visual verdicts | Platform-specific questions for capture and review, not a substitute verdict |
| `omh-award-bar-score` | Assessment against an external award's published judging model | No award score or claim that Apple-style work must resemble an award website |

Implementation remains with the selected coding owner. Web implementation can
use `frontend`; native work goes to the selected owner with the native platform
requirements. Accessibility and rendered verification retain their existing
owners and require observations after the last relevant change.

## What the research changed

The starting reference was
[dickwu/apple-design-skill](https://github.com/dickwu/apple-design-skill/tree/d0bac1e765a27a696839e62962e36330ce72f0b7),
reviewed on 2026-09-05. Its topic-oriented review structure is useful, but its
generalization from Apple platforms to mobile and desktop can hide important
differences. Its numeric CSS blur, opacity, and saturation recipes are not
universal Apple specifications.

OMH uses independently written guidance rather than importing the upstream
skill or its reference collection. No license file was present at the reviewed
revision; its README describes HIG-derived material without granting a
redistribution license. The upstream remains a link-only discovery reference
in [the source registry](SKILL-SOURCES.md).

Apple's own current guidance supplies the following distinctions:

- **Native controls before imitation.** Standard SwiftUI, UIKit, and AppKit
  controls adopt system appearance through the applicable SDK and OS.
  Custom backgrounds can interfere with those behaviors.
- **Liquid Glass has a purpose.** Use it for the functional controls and
  navigation layer, with standard materials for content. Apple's transient
  interactive-control exception is not permission to make every content card
  glass. The regular and clear variants serve different legibility needs;
  clear is for visually rich backgrounds. Apple's conditional 35% dimming
  example for bright backgrounds is not a universal CSS opacity recipe.
- **Typography is platform-specific.** Use Dynamic Type on iOS and iPadOS.
  Apple's typography guidance explicitly distinguishes macOS, which does not
  support Dynamic Type. Mac layouts still need readable system typography and
  appropriate text-sizing behavior. Web layouts need browser zoom and reflow,
  not a claim that CSS implements Dynamic Type.
- **Accessibility constrains the treatment.** Check keyboard access,
  VoiceOver or the target platform's assistive technology, labels, gesture
  alternatives, text enlargement, contrast, and reduced-motion behavior.
  Translucent treatments need reduced-transparency behavior and legibility
  checks against changing backgrounds.
- **Units and assets do not transfer automatically.** Apple points are not a
  universal CSS-pixel requirement. Prefer platform font and symbol APIs in
  native apps; web work uses suitable system-font fallbacks and licensed
  icons, not redistributed Apple fonts, logos, or SF Symbols by assumption.

For other Apple platforms or non-Apple native apps, consult the target
platform's current guidance. Do not turn iPhone navigation, macOS windows, or
web breakpoints into universal requirements.

## Sources and evidence

Primary sources checked on 2026-09-05:

- [Apple Human Interface Guidelines](https://developer.apple.com/design/human-interface-guidelines/)
- [Materials](https://developer.apple.com/design/human-interface-guidelines/materials)
- [Adopting Liquid Glass](https://developer.apple.com/documentation/technologyoverviews/adopting-liquid-glass)
- [Accessibility](https://developer.apple.com/design/human-interface-guidelines/accessibility)
- [Typography](https://developer.apple.com/design/human-interface-guidelines/typography)
- [SF Symbols](https://developer.apple.com/sf-symbols/)
- [MacBook Pro](https://www.apple.com/macbook-pro/) — selected for metal edge
  light, dark studio, and silhouette observations
- [AirPods Pro](https://www.apple.com/airpods-pro/) — selected for macro scale,
  white ceramic/plastic reading, and restrained negative space
- [Apple Vision Pro](https://www.apple.com/apple-vision-pro/) — selected for
  glass, physical depth, and controlled reflection
- [Icon Composer](https://developer.apple.com/icon-composer/) — native
  multilayer icon craft, not a marketing renderer
- [GSAP](https://github.com/greensock/gsap) — optional existing-project web
  animation reference, not a native Apple API
- [liquid-logo](https://github.com/paper-design/liquid-logo) — PolyForm
  Shield-licensed link-only shader research, not a drop-in package
- [liquid-glass-js](https://github.com/dashersw/liquid-glass-js) — MIT
  web-only effect reference, not native Liquid Glass

The materials, accessibility, and typography pages were inspected through
Apple's own documentation JSON under
`https://developer.apple.com/tutorials/data/design/human-interface-guidelines/`;
their plain HTML responses expose only a documentation shell. The adoption
guide also provides an official `.md` representation. These are research
inputs, not new OMH runtime network integrations.

For web accessibility, use the applicable
[WCAG standard](https://www.w3.org/WAI/standards-guidelines/wcag/) rather than
calling Apple guidance a web conformance standard. Each review should separate
Apple guidance, web requirements, and OMH recommendations, naming the source,
platform applicability, evidence, and missing checks. A prepared review or
handoff is not execution, accessibility PASS, visual PASS, or Apple endorsement.
