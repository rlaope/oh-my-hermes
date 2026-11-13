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
| `horizontal_overflow_px` | document `scrollWidth` minus the requested viewport width, never below 0; on a page that starts at its right edge (see `first_action_y`) the scrolling element's `scrollWidth` is used, because in quirks mode the root's misses an absolutely placed box overflowing to the left. A quirks-mode page can have no scrolling element (`overflow-x: hidden` on both `<html>` and `<body>` gives none, `clip` on both keeps `<body>`); the root's number is used there and can read 0 while the screen still pans |
| `elements_past_right_edge` | count and up to 20 elements whose right edge passes the viewport width. On a page that starts at its right edge the overflowing side is the left: the same key then lists elements whose left edge lies left of page x 0, each with `left` (page px, negative) instead of `right`, and the `note` says so. Page x 0 is a document coordinate, not the left edge of the screen at load: under the phone emulation an overflowing page can load with a listed element already on screen |
| `first_data_y` | top of the first visible match of `--data`, in document px (a match fixed to the viewport is placed by its viewport box); without `--data` the guess is `table tbody tr, [role=row], li, article`, and `"not_found"` plus a hint means pass `--data` |
| `first_action_y` | top of the first visible `a[href]` or `button` whose box reaches into the page; a control parked off-screen (a skip link above the page) is skipped, and a control fixed to the viewport is judged and placed by its viewport box, so one parked above the screen stays skipped after the page scrolls. `position: fixed` under an ancestor with a transform, a filter or paint containment is fixed to that ancestor, scrolls with the page and is measured in document px like any other control. The edge the page cannot scroll past is its start edge, read from `<body>`, writing mode first: a `vertical-*` or `sideways-*` mode starts at the right when it ends in `-rl` and at the left when it ends in `-lr`, whatever the direction, and horizontal text starts at the right only under `direction: rtl`. On a right-start page a control counts only when a scroll or a pan can put part of it on screen. The part its ancestors do not clip away must reach left of the start edge and lie inside the page's scroll range, so a control in the left overflow counts, one parked past the right edge is skipped, and so is one painted left of page x 0 without widening the page (content under layout containment). Where `document.scrollingElement` is null (a quirks-mode page can get there with `overflow-x` auto, scroll or hidden on both `<html>` and `<body>`; `clip` or visible on `<body>` keeps `<body>`) the page does not report where it starts or how far it scrolls, so it gets only the edge test a left-start page gets: there a control that lies wholly in the left overflow is not counted, and a control parked past the right edge, or one whose only unclipped part lies left of the page, is. Where the viewport cannot scroll sideways (`overflow-x` hidden or clip on `<html>`, or on `<body>` when `<html>` leaves overflow visible) that part must instead lie across the band the screen still pans over, client x 0 to `innerWidth`. A control with no such part counts only inside a reachable ancestor that scrolls (`overflow` auto or scroll) far enough to show it, toward whichever side that ancestor scrolls (read from its writing mode, direction and flex flow), and a fixed control only when it lies across the same band. A control the browser has not rendered yet (`content-visibility: auto`, off screen) shows what clips it only once it is rendered, and the script does not scroll the page to render it: it counts when its own box passes the edge test a left-start page gets, below the top and right of page x 0, unless the box that skips it is known to stay off screen: that box cannot be reached and has no positive `overflow-clip-margin`, which would let it paint past its own edge. So an unrendered control is still counted when a clip inside that content hides it or when it is parked past the right edge, and is missed when it lies in the left overflow. So a skip link at `left: -9999px` is the first action where it is left overflow the reader can pan to, and is skipped inside a clipping container or on a page whose root clips. A left-start page gets the edge test only |
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
- **Measuring writes nothing to the page.** Which way a scroll box at
  position 0 scrolls (a reversed flex line scrolls to negative positions) is
  read from its writing mode, direction and flex flow, not found by scrolling
  it: a scroll runs the page's own listeners, and what they add would be
  counted. `--shot` with `--scroll` scrolls only after the numbers are taken.
- **Named markup is not a browser measurement.** A hidden `<form
  name="scrollingElement">` can replace `document.scrollingElement` with that
  form through the browser's named-property lookup, without any page script.
  The additional start-side and right-start reach inputs (root, body,
  scrolling element, ancestor links and scroll-box sizes) are read through
  their interface prototypes, so named markup cannot replace those reads.
  This does not protect the older DOM reads shared with the left-start path.
- **Page scripts can still corrupt measurements.** This is an in-page helper,
  not an isolated-world measurement. A page script that changes a prototype,
  `getBoundingClientRect`, `getComputedStyle` or `IntersectionObserver` can
  make it omit or misplace a control. In one measured page, a real y100 link
  reported its rectangle at y-500: the left-start path omitted it and
  returned the y300 fallback, while the right-start path kept it through the
  observer and reported -500. An observer wrapper that reports an empty
  intersection can likewise hide a touched link on the right-start path;
  the left-start path does not consume that observer. The prototype reads
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
