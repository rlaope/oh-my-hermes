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
| `horizontal_overflow_px` | document `scrollWidth` minus the requested viewport width, never below 0; on a page that starts at its right edge (see `first_action_y`) the scrolling element's `scrollWidth` is used, because the root's misses an absolutely placed box overflowing to the left |
| `elements_past_right_edge` | count and up to 20 elements whose right edge passes the viewport width. On a page that starts at its right edge the overflowing side is the left: the same key then lists elements whose left edge passes the first screen's left edge, each with `left` (page px, negative) instead of `right`, and the `note` says so |
| `first_data_y` | top of the first visible match of `--data`, in document px (a match fixed to the viewport is placed by its viewport box); without `--data` the guess is `table tbody tr, [role=row], li, article`, and `"not_found"` plus a hint means pass `--data` |
| `first_action_y` | top of the first visible `a[href]` or `button` whose box reaches into the page; a control parked off-screen (a skip link above the page) is skipped, and a control fixed to the viewport is judged and placed by its viewport box, so one parked above the screen stays skipped after the page scrolls. `position: fixed` under an ancestor with a transform, a filter or paint containment is fixed to that ancestor, scrolls with the page and is measured in document px like any other control. The edge the page cannot scroll past is its start edge, read from `<body>`: the left for left-to-right text, the right under `direction: rtl` or a `vertical-rl` writing mode. On a right-start page a control in the left overflow counts, a control parked past the right edge is skipped, and a fixed control counts only when it lies across the band the reader pans over |
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
- **A right-to-left page overflows to the left.** Under `direction: rtl` on
  `<body>` a page that is too wide starts at its right edge with a negative
  `scrollX`, and the reader pans left to reach the rest. The script reads the
  start side from `<body>`, so `<html dir="rtl"><body dir="ltr">` is measured
  as a left-to-right page and `body{direction:rtl}` as a right-to-left one.
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
