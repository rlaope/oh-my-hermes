# Scroll Motion Libraries

Smooth scroll is a design decision that arrives with an accessibility bill
attached. This reference is the record for taking a scroll library at all,
and the integration contract for the one OMH has reviewed.

## Take the native path first

A library is the answer to a requirement, never to an adjective. Work down
this list and stop at the first row that covers the brief:

| Need | Native answer |
| --- | --- |
| Anchor and in-page jumps that glide | CSS `scroll-behavior: smooth` with `scroll-padding-top` for the sticky header |
| Reveal on entry, progress bars, scroll-linked parallax | CSS scroll-driven animations - `animation-timeline: scroll()` / `view()` - which the browser can run off the main thread |
| One-off enter animations | `IntersectionObserver` plus a class, no scroll listener at all |
| Section-by-section paging | CSS `scroll-snap-type` |

`animation-timeline` is the newest row and the one to check rather than
assume: read its current support against the project's own browser matrix and
name the fallback before the contract commits to it. The other three rows are
long-settled.

A scroll library earns its place only when the brief needs an *interpolated
scroll position that more than one consumer reads*: a WebGL or canvas scene
synced to the page, a velocity- or progress-driven sequence, horizontal and
nested axes driven from one loop. "Make it feel premium" is not that
requirement, and a library added for it buys jank, keyboard bugs, and a
dependency in exchange for nothing the native rows above could not do.

## Source record

- Lenis, reviewed at `eea71595f5ae595f49b21ed87520822d3624098a` (v1.3.26) on
  2026-09-08: https://github.com/darkroomengineering/lenis - MIT, no runtime
  dependencies. It wraps the browser's own scroll instead of replacing it, so
  `position: sticky` and accessibility keep working, per its own feature
  list. Vertical, horizontal, and nested axes come from one instance, and
  the published packages are `lenis`, `lenis/react`, `lenis/vue`,
  `lenis/framer`, and `lenis/snap`.
- GSAP is recorded in `omh-apple-design/references/web-production-libraries.md`
  with its own license note. Read that note there rather than restating it;
  the GreenSock Standard "no charge" license is not an OSI license.

OMH does not install, vendor, pin, or fetch any of this at runtime. Before
the selected coding owner adds a dependency, inspect the project's own
dependency, bundle-size, CSP, and license policy - a reviewed source record
is not permission to add a package to someone else's build.

## Integration contract

1. **One instance, one loop.** Either `autoRaf: true` or a manual
   `lenis.raf(time)` call inside the loop the project already runs - never
   both, and never a second instance per component.
2. **The recommended stylesheet ships with it.** `lenis/dist/lenis.css` is
   part of the integration, not an optional extra; `autoToggle` does not work
   without it.
3. **Anchors are opt-in.** Upstream states it prevents anchor links from
   working while scrolling until `anchors: true` (or a `scrollTo` options
   object) is passed. A deep link that stopped working is this setting.
4. **Nested scrollables are declared.** Modals, dropdowns, code blocks, chat
   panes, and map surfaces carry `data-lenis-prevent` (or the
   wheel/touch/axis-specific variants), or a `prevent` predicate names them.
   `allowNestedScroll: true` is the shortcut and it walks the DOM tree on
   every scroll event - upstream documents that cost, so choose it knowingly.
5. **Teardown is owned.** Call `destroy()` on route change and component
   unmount. An instance that outlives its route stays subscribed to wheel and
   touch events, and the next mount's instance then doubles every delta.
6. **GSAP sync is a fixed recipe.** `lenis.on('scroll', ScrollTrigger.update)`,
   drive `lenis.raf(time * 1000)` from `gsap.ticker`, and set
   `gsap.ticker.lagSmoothing(0)`. Two independent rAF loops fight.
7. **CSS scroll-snap does not survive.** Upstream states it is unsupported;
   `lenis/snap` is the only supported snapping path.
8. **A no-build CDN tag is an origin decision.** The one-line drop-in exists,
   but a third-party script and stylesheet is a CSP, SRI, offline, and
   supply-chain question for the project, not a convenience.

## Reduced motion is a branch, not a flag

`respectReducedMotion` defaults to `true`, and it is worth knowing exactly
what that buys. When the user prefers reduced motion, smoothing is disabled -
`lerp` is forced to `1` so scroll tracks the input device 1:1 and
`duration`/`easing` are ignored - and programmatic scrolls, including anchor
links, jump instantly. The instance keeps running so WebGL and DOM
synchronization stay intact, and the preference is picked up live without a
reload.

What it does not do is touch the animations *you* wrote. Read
`lenis.prefersReducedMotion` and branch your own reveals, pins, and parallax
on it, or the page still moves for someone who asked it not to. Setting
`respectReducedMotion: false` is a documented opt-out and an accessibility
decision the user makes explicitly, never a default the implementation picks.

## Limitations to quote, not discover

Upstream publishes these. Reading them late turns each one into a bug report:

- Capped to 60fps on Safari, and 30fps in low power mode.
- Smooth scroll stops at iframes, which do not forward wheel events.
- `position: fixed` lags on pre-M1 macOS Safari.
- `syncTouch` can behave unexpectedly on iOS below 16.
- No CSS scroll-snap support.
- Nested scroll containers need the explicit configuration above.

## What it costs, and who pays

Scroll smoothing runs on the main thread and reacts to input, so INP is the
metric it moves. Name the budget from `references/web-vitals-budgets.md`
before the change, not after, and capture the baseline on the same device and
network class.

The rest of the bill is behavioral, and each item is a state someone will hit
on the first day:

- Keyboard scrolling: Space, PageUp/PageDown, Home/End, and arrow keys.
- Browser scroll restoration on back/forward, and cold-load deep links.
- Find-in-page, which scrolls the native way.
- Screen-reader and focus-driven scrolling into view.
- Touch, where `syncTouch` changes the feel and the inertia model.
- Print and reader modes, where none of this exists.

## Verification

Before anyone calls a scroll integration done, these states are rendered and
observed - captured, not reasoned about: default motion; reduced motion;
keyboard-only traversal; an anchor deep link on cold load; a nested
scrollable such as a modal or code block; route change and back; touch on a
real device; and Safari, because of the frame cap above.

## Boundary

A library selection, an option table, a code recipe, or a prepared handoff is
not an installed dependency, a rendered frame, a motion proof, an
accessibility PASS, or a Core Web Vitals measurement. All of those stay
`prepared_not_observed` until the selected coding owner supplies the observed
project version, license review, teardown evidence, and rendered states.
