# Component Registry Adoption

A copy-paste component registry is the opposite of a package. The CLI writes
the component's source into the project, and from that moment the project owns
it: there is no upstream release that will fix its accessibility, its
reduced-motion behavior, or its performance. Adopting one is a code review of
someone else's file, done before it lands, not a dependency bump.

## The ownership model

Most current UI registries distribute through the shadcn CLI registry format
(`npx shadcn@latest add <registry>/<component>`): shadcn/ui itself, and the
effect and motion registries built on the same format - Magic UI, Aceternity
UI, Cult UI, Kokonut UI, SmoothUI, the neobrutalism components, Animate UI,
React Bits, Vengeance UI, and Skiper UI. Several also publish an MCP server or
an `llms.txt` aimed at coding agents. The mechanism is the same everywhere:
open code you own.

Two consequences follow, and both belong in the contract:

1. **Every gap ships with the file.** A missing `aria-hidden`, a missing
   `prefers-reduced-motion` branch, a hover-only pause: once copied in, each
   is the project's defect, and it stays until the project fixes it.
2. **Updates are a merge, not an upgrade.** Re-running the CLI overwrites
   local fixes. Record which components were modified after adoption, so a
   later refresh is a reviewed diff rather than a silent regression.

## Adoption checklist

Run this per component, before it is committed:

- **License, observed at the source.** Read the license file of the exact
  repository the CLI pulls from - not a badge, a blog post, or a guess from a
  sibling project. Some registries are MIT; at least one in this list ships
  MIT with an added Commons Clause condition, which is not an OSI license and
  restricts redistributing the components themselves. When the license was
  not read, record it as "license: check before adopting".
- **What it pulls in.** List the dependencies the component adds - a motion
  library, GSAP and its plugins, a WebGL or canvas helper - and check each
  against the project's own dependency, bundle-size, and CSP policy.
- **A reduced-motion branch.** Name what the component shows under
  `prefers-reduced-motion: reduce`. "The library handles it" is a claim to
  verify in the copied source, not an assumption.
- **ARIA.** Decorative duplicates and per-character spans are hidden from
  assistive technology; interactive parts carry a role and an accessible name.
- **Keyboard and touch.** Every control a pointer can reach, a keyboard and a
  touch screen reach too. A hover-only affordance is a missing feature on two
  of the three input types.
- **Token mapping.** Replace hardcoded colors, radii, and shadows with the
  project's semantic tokens from `DESIGN.md`. A component that still names
  its own hex values will drift the moment the theme changes.
- **Performance cost.** Canvas, WebGL, particle, and blur effects run every
  frame. Name the INP and frame budget from `references/web-vitals-budgets.md`
  and the device class it is judged on.

## Layer behavior, motion, and style

The registries that age best separate three concerns, and adopting into the
same split keeps a component repairable:

1. **Behavior** - a headless primitive (Radix, Base UI, Headless UI) owns
   focus, keyboard, ARIA, and dismissal.
2. **Motion** - a thin wrapper animates the primitive's states (open, closed,
   entering, leaving) and owns the reduced-motion branch.
3. **Style** - a minimal layer that reads semantic tokens and nothing else.

Animate UI is organized this way. When a copied component fuses the three,
splitting it on adoption is cheaper than debugging it later.

## Decorative-effect budget

Effect registries offer aurora backgrounds, beams, spotlights, meteors, 3D
cards, globes, glass docks, and gooey inputs. The failure is not any one of
them; it is stacking them.

- **At most one hero effect per view.** A second effect competes with the
  first and with the content.
- **Heavy effects belong to marketing surfaces, not app UI.** A dashboard
  someone uses for eight hours does not get a particle background.
- **Gradient and glass text meets contrast at its worst-case background.**
  Check the lightest pixel the text can sit over, not the average.

## Text-motion contracts

### Split text

Character-by-character reveals are the most copied text effect and the
easiest to ship broken for screen readers.

- Put the full text where assistive technology reads it once: an
  `aria-label` on the container, or visually-hidden text beside it. The
  per-character or per-word spans are `aria-hidden="true"`.
- Wait for `document.fonts.ready` before splitting. Splitting before the web
  font loads measures the fallback face, and lines re-break when the real one
  arrives.
- On unmount, revert the split and kill the scroll triggers it created. A
  split that outlives its component leaks DOM and listeners on every route
  change.
- Do not char-split long text. Per-character DOM nodes on a paragraph cost
  layout time and turn a reading surface into an animation; split headings
  and short lines only.
- Under reduced motion, show the final state immediately - the text in place,
  no stagger.

An observed reference point, not a prescription: the React Bits SplitText
defaults are a 50ms stagger, a 1.25s duration, `power3.out` easing, a 40px
upward offset, and a one-shot play on entry.

### Marquee

A scrolling strip of logos or quotes duplicates its content to loop, and the
duplication is where it breaks.

- **The duplicates are `aria-hidden`.** Only the first copy is read; without
  this a screen reader reads the same list several times.
- **A pause control reachable by keyboard and touch, not only hover.** WCAG
  2.2.2 (Pause, Stop, Hide) requires a way to stop moving content that runs
  longer than five seconds alongside other content. Hover-to-pause leaves
  keyboard and touch users with no stop at all.
- **Reduced motion stops it.** Under `prefers-reduced-motion: reduce`, the
  strip is static, wraps, or scrolls only on user input.
- **Speed and gap are CSS variables**, so the theme and the reduced-motion
  branch can change them without editing the component.
- **Slow enough to read.** A marquee whose items cannot be read before they
  leave is decoration that looks like content.

The Magic UI marquee reviewed for this record duplicates its children without
`aria-hidden`, has no reduced-motion branch, and pauses on hover only - a
concrete instance of each gap above, observed in its source.

## Named motion profiles

Define motion once, as named profiles in the `DESIGN.md` Motion &
Interaction section, instead of per-component values. Each profile fixes
four numbers: stagger, duration, easing, and travel distance.

- **Calm** - long durations, small travel, gentle ease-out, little or no
  stagger. Product UI and reading surfaces.
- **Energetic** - shorter durations, larger travel, stronger easing, visible
  stagger. Launch pages and hero moments.

A component picks a profile; it does not invent numbers. SmoothUI names its
motion profiles this way (Calm and Energetic), though it does not publish the
values, so the numbers in the contract are the project's own.

## Source record

Reviewed on 2026-10-07 as link-only design context. No component source,
demo copy, or brand material is reproduced; the wording here is OMH's own.

- shadcn/ui - https://ui.shadcn.com/docs/theming - MIT (repository license)
- Magic UI marquee - https://magicui.design/docs/components/marquee - MIT
  (repository license)
- React Bits SplitText - https://reactbits.dev/text-animations/split-text -
  MIT with the Commons Clause condition (repository license file); not an OSI
  license
- Neobrutalism components - https://www.neobrutalism.com/docs - MIT
  (repository license)
- Animate UI - https://animate-ui.com/docs - license: check before adopting
- SmoothUI - https://smoothui.dev - license: check before adopting
- Aceternity UI - https://ui.aceternity.com - license: check before adopting
- Cult UI - https://www.cult-ui.com - MIT as stated on its site
- Kokonut UI - https://kokonutui.com - license: check before adopting
- Vengeance UI - https://www.vengenceui.com - license: check before adopting
- Skiper UI - https://skiper-ui.com - license: check before adopting

OMH does not install, vendor, pin, or fetch any of this at runtime. A
reviewed source record is not permission to add a component to someone
else's build; the selected coding owner runs the checklist above first.

## Boundary

An adoption checklist, a motion profile, or a prepared handoff is not an
installed component, a rendered frame, an accessibility PASS, or a
performance measurement. Those stay `prepared_not_observed` until the
selected coding owner supplies the observed source, license review, and
rendered states - including reduced motion and keyboard-only traversal.
