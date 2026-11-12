"""Phone-screen density gate: the body of `references/mobile-density-gate.md`."""

from __future__ import annotations


def mobile_density_gate_reference() -> str:
    return """# Mobile Density Gate

A phone layout can pass every "does it break" check and still be a poor
tool: the first screen goes to chrome and filters, and the thing the person
came for sits below the fold. This gate judges a phone-used surface on two
axes and says what to capture, measure and report. It adds to
`screenshot-loop.md`; it does not replace the 375 capture.

## Two axes, judged separately

- **Hygiene** — the surface does not break: no sideways scroll, no clipped
  label, no target too small to hit, no input that zooms the page.
- **Density** — the surface is usable at a glance: the content the screen
  exists for is on the first screen, and frequent controls cost one tap.

Passing hygiene alone is not a pass. A clean page can still put three
stacked filters above its first row; record two verdicts, one per axis.

## The first screen is data

1. Use one phone viewport for the measurement, default 390x844 CSS px, and
   name it in the report. Another size is fine when the product targets it.
2. Measure the y position, in CSS px from the top of the viewport, where the
   first data row starts. On a page with no data rows, measure the y of the
   first action control instead. Read it from the rendered page (the
   element's bounding box), not from the stylesheet.
3. The default limit is 300 px. It is an agreed default a project may
   change, not a measured fact about phones; when a project sets another
   number, write it down in the contract and use that one.
4. A first row below the limit is a density finding even when nothing is
   broken; state the number and the elements above it.

## Lay controls flat before hiding them

- Re-flow stacked filters, selects and labels into rows first; two or three
  short controls often fit on one line at phone width.
- Collapse behind a button last. A control used on every visit then costs
  two taps (open, then act), so collapse only what is used rarely.
- A label whose value already names itself (a search box with a
  placeholder) may go; the reader loses nothing and the row gets shorter.

## Extend the rule the project already has

Find the project's existing responsive rule (a breakpoint, a container
query, a shared layout class) and extend it before writing a second one: a
parallel rule drifts from the first at the next redesign. A screen that has
to differ from its siblings says why in a comment beside the rule, so the
next editor can tell a decision from an accident.

## A bar that hides on scroll

Move it with `transform` (a translate in, a translate out). Switching its
`display` or `position` takes it out of flow or puts it back, the content
under it changes height, and the line being read jumps. Give the movement a
`prefers-reduced-motion` branch that shows or hides the bar without the
slide.

## Horizontal scroll is a failure

A page-level sideways scroll at phone width is a hygiene failure. A "swipe
sideways" hint, a fade at the edge or a shrunken font does not turn it into
a pass. Convert the layout instead:

- a wide table becomes stacked rows, each row a small block of label and
  value pairs, or keeps only the identifying columns with the rest behind
  a row tap;
- a wide board becomes tabs, one column per tab, or ranges the person steps
  through;

A region that is meant to scroll sideways (a chart, a code block) is
contained in its own box and named as such in the report.

## How to look

- **Do not just narrow the window.** Turn on touch and a mobile user agent
  in the session when it can set them (device emulation, a mobile profile).
  Without them `(hover: none)` and `(pointer: coarse)` rules and
  server-side device branches never run, and the capture shows a desktop
  page in a thin column.
- When the session cannot set touch emulation, the capture is width-only;
  say so in the manifest. It is not a phone check.
- Capture the first viewport, not the full page, when judging a
  bottom-fixed element: a full-page capture stitches the page and puts a
  fixed bar once at the end, or repeats it.
- Capture after scrolling when judging scroll behaviour (a hiding bar, a
  sticky header, a floating button), at least once past the bar's trigger.

## Hygiene list

Each item already has an owner in OMH; check it here, do not restate it:

- Touch target size — `design-system-contract.md`, the accessibility
  section; `omh-accessibility-audit` for the audit.
- Text inputs at 16 px or larger; below that, iOS Safari zooms the page on
  focus and the layout shifts under the person's thumb.
- Dynamic viewport units (`dvh`, `svh`) for full-height sections, so the
  browser's collapsing toolbar does not cut the bottom.
- Safe-area insets (`env(safe-area-inset-*)`) on fixed bars at the screen
  edge, so a notch or home indicator does not cover them.
- Clipped labels that carry meaning.

A target that is too small grows its hit area, not its visible size: extend
it with a pseudo-element that takes no layout space, so table rows and
paragraphs keep their height.

## Report shape

Three parts, in this order:

1. **Changed** — each change as a before and after pair in px, such as
   `first row y: 514 -> 311px`, with the viewport the pair was taken at.
2. **Concerns** — judgement calls and what each rests on: a control left
   collapsed because it is rare, a screen that differs from its siblings,
   a threshold the project moved.
3. **Not checked** — viewports, states, devices and pages that were not
   captured, each named.

An item without a number is counted as not done: "the filters are tighter"
is a claim, `3 rows -> 1 row` is a result.

## Open limits

- The 300 px default is a convention the team agreed to, not something
  measured about people; a project with other content may set another.
- Emulation approximates a phone. Nothing in this gate replaces watching a
  person use the surface on a real device.

## Boundary

OMH never launches a browser or measures a page. The viewport, the touch
emulation setting and every pixel value here are executor-observed
evidence; a density claim without a capture and a measured number at a
named viewport is a prepared claim, not an observed one. PASS, REVISE or
BLOCK stays with `visual-qa`.
"""
