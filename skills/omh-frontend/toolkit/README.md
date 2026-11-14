# Frontend phone-check toolkit

`scripts/phone_check.py` opens one page in a phone-sized, touch-emulating
Chromium and prints measurements as one JSON object. It is original OMH code,
optional, and never installs anything. It reports numbers only; the `frontend`
skill's references decide what a number means for a project.

## Run it

```
uv run --with playwright python scripts/phone_check.py <url | file.html | dir> \
  [--data '<css selector>'] [--measure '<sel>,<sel>'] [--shot <new png path>] [--scroll <px>] \
  [--desktop] [--width N --height N] [--browser <executable>] [--timeout <s>]
```

Playwright is imported only when a page is measured. If it is missing the
script exits 2 and names `pip install playwright` and `playwright install
chromium`. `--help` needs no third-party package.

The default is 390x844 at device scale 3 with a mobile user agent, `is_mobile`
and touch on, so `(hover: none)` and `(pointer: coarse)` match. `--desktop`
switches to 1440x900 with none of those. The output records which emulation
ran.

## What each number means

| field | meaning |
|---|---|
| `horizontal_overflow_px` | document `scrollWidth` minus the requested viewport width, never below 0; on a page that starts at its right edge (body writing mode `vertical-rl` / `sideways-rl`, or horizontal text with `direction: rtl`) the scrolling element's `scrollWidth` is used, because in quirks mode the root's misses an absolutely placed box overflowing to the left. A quirks-mode page can have no scrolling element (`overflow-x: hidden` on both `<html>` and `<body>` gives none, `clip` on both keeps `<body>`); the root's number is used there and can read 0 while the screen still pans |
| `elements_past_right_edge` | count and up to 20 elements whose right edge passes the viewport width. On a page that starts at its right edge the overflowing side is the left: the same key then lists elements whose left edge lies left of page x 0, each with `left` (page px, negative) instead of `right`, and the `note` says so. Page x 0 is a document coordinate, not the left edge of the screen at load: under the phone emulation an overflowing page can load with a listed element already on screen |
| `first_data_y` | top of the first visible match of `--data`, in document px (a match fixed to the viewport is placed by its viewport box); without `--data` the guess is `table tbody tr, [role=row], li, article`, and `"not_found"` plus a hint means pass `--data` |
| `first_action_y` | geometric top of the first visible `a[href]` or `button` in DOM order whose box reaches below the top and right of document x 0, on either start side. A control fixed to the viewport is judged and placed by its viewport box; `position: fixed` under a containing ancestor (a transform, filter or paint containment) scrolls with that ancestor and is placed in document px. This keeps the earlier edge test, not an activation test. It skips controls wholly in the left overflow of a right-start page even when the phone loads panned to them; it can count a control a container clips away, one under an overlay, a disabled control, or one a scroll box cannot reach. It sends no tap, scroll or focus to discover whether a control really acts, and does not predict `:active` / `:hover` changes or event delivery into a nested document |
| `small_targets` | visible `a, button, [role=button], input, select, summary` under 44 px in either dimension: count and first 20 |
| `small_inputs` | visible text-entry controls (`textarea`, `select`, and `input` other than checkbox, radio, button, submit, reset, file, image, range, color and hidden) whose computed font size is under 16 px: count and first 20; `checked` counts only these |
| `console_errors` | `console.error` messages and uncaught page errors during load |
| `measure` | height of the first visible match of each `--measure` selector |

The 44 and 16 are the script's defaults, reported beside the counts as
`minimum_px` and `minimum_font_px`; a project that sets other minimums reads
the lists, not the counts.

## Pitfalls

- **`innerWidth` is not the viewport you asked for.** In a mobile-emulated
  context a page with a 520 px child reported `innerWidth` 520 and
  `scrollWidth` 520 while `clientWidth` stayed 390. Overflow is therefore
  computed against the requested width. `inner_width` is printed so the
  difference is visible.
- **An element in the past-right list may be clipped.** A child inside an
  `overflow: hidden` ancestor can sit past the edge without scrolling the page.
  The verdict is `horizontal_overflow_px`; the list points at where to look.
- **A right-to-left page overflows to the left.** A page that starts at its
  right edge and is too wide scrolls into negative `scrollX`, and the reader
  pans left to reach the rest. Under the phone emulation it loads already
  there (`scrollX` -210 for a 600 px row at 390 px); a `--desktop --width 320`
  run of the same page loads at `scrollX` 0 and scrolls to -280. The script
  reads the start side from `<body>`, writing mode before direction, so
  `<html dir="rtl"><body dir="ltr">` is measured as a left-to-right page,
  `body{direction:rtl}` as a right-to-left one, and a `vertical-lr` body as a
  left-start page even under `direction: rtl`.
- **Measuring writes nothing to the page.** The script does not tap, scroll,
  focus or write to the page to find a control: those actions run the page's
  own listeners and may change its state. `first_action_y` keeps the earlier
  geometric edge test rather than predicting activation. `--shot` with
  `--scroll` scrolls only after the numbers are taken.
- **Named markup is not a browser measurement.** A hidden `<form
  name="scrollingElement">` can replace `document.scrollingElement` with that
  form through the browser's named-property lookup, without any page script.
  The start side, the root, body and scrolling element, and
  every step up the tree (`parentElement`, `offsetParent`, the node kind)
  are read through their interface prototypes,
  so named markup cannot replace those reads. A `<form>` holding `<input
  name="parentElement">` used to send the walk that asks whether a control is
  fixed to the viewport round in a circle until the time limit.
  The other reads are as the page exposes them, on either start side. Three
  measured consequences, the same before this script read right-start pages:
  a form control named `getBoundingClientRect`, or an element named
  `querySelector` or `querySelectorAll` on `document`, ends the run with exit
  2 and no report; a hidden `<form name="documentElement">` reports
  `client_width` 0.
- **Geometry is not activation.** The RTL change fixes overflow reporting,
  not `first_action_y` reachability. An attempted hit-test addition counted
  links wrapping an iframe, object or embed even when the nested document
  took the tap. A hit test also cannot predict a `:hover` or `:active` style
  that changes the control when touched. That addition was withdrawn; both
  start sides keep the same geometric edge test and its existing misses.
  A control wholly left of document x 0 stays skipped even if it is on screen.
  A control to its right stays eligible even if a scroll box, shadow tree,
  `::details-content` box or overlay prevents interaction.
- **Page scripts can still corrupt measurements.** This is an in-page helper,
  not an isolated-world measurement. A page script that changes a prototype,
  `getBoundingClientRect` or `getComputedStyle` can
  make it omit or misplace a control. In one measured page, a real y100 link
  reported its rectangle at y-500: both start sides omitted it and returned
  the y300 fallback. The prototype reads
  above also bypass a page-authored own `document.scrollingElement` getter,
  but do not protect every API the helper reads.
- **Width alone misses touch rules.** A desktop window resized to 390 px keeps
  hover and a fine pointer, so hover-only controls look fine and a 30 px button
  passes by eye. The touch and mobile flags are what make the pointer media
  queries and tap-size findings real.
- `--shot` captures the first viewport only; with `--scroll N` it scrolls first.
  A full-page capture would hide where the first screen ends.

## Example

```
uv run --with playwright python scripts/phone_check.py examples/phone-overflow.html --data '.row'
```

prints (trimmed) `horizontal_overflow_px: 130`, `first_data_y: 600`,
`small_targets.count: 1` (a 120x30 button) and `small_inputs.count: 1`
(14 px). `examples/phone-clean.html` reports 0 overflow, first data at 120, no
small targets and no small inputs.

## Refusals (exit 2, nothing printed on stdout)

- Playwright or Chromium missing, navigation failure or HTTP 4xx/5xx, a selector
  the browser rejects, or a run past `--timeout` (default 30 s, at most 300 s).
- Bad arguments: width or height outside 200-4000, negative `--scroll`,
  `--scroll` without `--shot`, an empty `--data` or `--measure`.
- A target other than an http(s) URL, an `.html`/`.htm` file or a directory with
  `index.html`; a path with `..` or a symlink component (macOS's own `/tmp`,
  `/var` and `/etc` links are trusted).
- `--shot` that already exists, is a link, has no existing parent directory or
  does not end in `.png`. The path is checked again after the page loads, and
  on macOS and Linux the file is created inside its directory opened without
  following a link, so a path or a directory that changed meanwhile is refused.
  Windows has no such create; there the second check and an exclusive create
  are the guard.

The script makes no network request beyond loading the target and passes user
strings to the page only as selector arguments to one fixed script.
