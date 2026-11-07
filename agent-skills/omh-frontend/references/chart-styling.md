# Chart Styling

A chart is a component, and it answers to the same token system as every other
component. A chart themed by hand - colors pasted into a config object, fonts
set in a stylesheet the chart library never reads - is the first surface to
drift when the theme changes, and the first to break in dark mode.

## Chart tokens

Define the chart's tokens beside the rest of the palette - `colors:` entries
in `DESIGN.md`, then CSS variables under `:root` redefined under the dark
theme - never inline in a chart config:

- **Categorical** - `chart-1` .. `chart-N`, one hue per series, chosen to be
  distinguishable from each other and from the status colors.
- **Sequential** - a separate scale (for example `chart-scale-01` ..
  `chart-scale-05`) for magnitude: heatmaps, choropleths, intensity. It is a
  lightness ramp of one or two hues, not the categorical set reused. Keep the
  two sets apart; a categorical hue used as a magnitude step implies an order
  that does not exist.
- **Role tokens** - the chart's own chrome: background, grid, crosshair, axis
  label, muted label, marker, and tooltip surface and text. Grid and
  crosshair sit well below the data in contrast; axis labels meet the text
  contrast floor.

Bklit, a shadcn-based chart registry, publishes exactly this split: role
tokens for grid, crosshair, markers, and labels, categorical `--chart-1..5`,
and a separate sequential `--chart-scale-01..05`. shadcn/ui's own chart
component reads `chart-1..5` from the same theme variables as everything
else.

## The palette is a function of the mode

A light-mode palette rendered on a dark surface loses its low-lightness
series and over-saturates the rest. Treat the palette as a function of the
color mode - two sets of values for the same token names - rather than one
list. MUI X Charts accepts a palette as a function of the mode for this
reason.

## Choose the color mapping deliberately

How a value becomes a color is a decision, and the contract names it per
chart:

- **Piecewise** - thresholds split the range into bands, each with one color.
  Right for status bands and pass/fail limits.
- **Continuous** - a value interpolates between a minimum and a maximum
  color. Right for magnitude.
- **Ordinal** - a fixed list of categories maps to a fixed list of colors,
  with an explicit fallback color for an unknown category so a new value is
  visible as unmapped rather than silently borrowing a neighbour's hue.

MUI X Charts exposes the three as `piecewise`, `continuous`, and `ordinal`
color maps, with an `unknownColor` fallback on the ordinal one.

## Color is never the only encoding

A palette that passes the token rules can still be unreadable for a reader
with color-vision deficiency, and marks need their own contrast.

- Every series also differs by a direct label, a marker shape, or a line dash
  (WCAG 1.4.1).
- Marks, and the gridlines or axes a reader needs, meet 3:1 against their
  background (WCAG 1.4.11).
- The chart carries a text alternative or a data table for its main finding.
- Check the categorical set under a deuteranopia and a protanopia simulation,
  and record the result beside the tokens.

## Categorical slot exhaustion

When the series outnumber the categorical slots, do not generate more hues.
Near-duplicate colors are worse than no color, because they invite a reader
to match the wrong series. Instead:

- group the long tail into an "Other" series;
- use direct labels at the line ends or bar tips instead of a color legend;
- or split into small multiples that share an axis.

## Axis text goes through the library, not CSS

Chart libraries that lay out their own axes measure label text to compute
margins. Set tick and axis label size, weight, and family through the
library's label-style API - in MUI X, `tickLabelStyle` and `labelStyle` -
and never through a CSS override. A CSS font change happens after the
library has measured, so labels overflow or clip and the margins are wrong.
The values still come from the typography tokens; only the path is the
library's.

## Designed states

Loading, no-data, and error are states of the chart, designed like any other
component state in the `DESIGN.md` Components section:

- **Loading** - a skeleton that holds the chart's final dimensions, so the
  page does not shift when data arrives.
- **No data** - a message that says why (no events in this range, filter
  excludes everything) and what changes it.
- **Error** - what failed and how to retry, without dropping the axes the
  user was reading.

## Starting palettes

`omh design data --kind palette --context data-viz` returns curated local
palette rows for data-dense surfaces, with neutral chrome that leaves hue
budget for a separate categorical series scale. Use them as the starting
point for the role and categorical tokens above; this reference does not
restate them.

## Source record

Reviewed on 2026-10-07 as link-only design context; no source or
documentation text is reproduced.

- Bklit theming - https://bklit.com/docs/theming - license: check before
  adopting
- shadcn/ui charts and theming - https://ui.shadcn.com/docs/theming - MIT
  (repository license)
- MUI X Charts styling - https://mui.com/x/react-charts/styling/ - the
  community `@mui/x-charts` package is MIT (package license file)

## Boundary

Chart tokens, a mapping choice, or a prepared handoff are not a rendered
chart, a measured contrast ratio, or a visual-QA PASS. Those stay
`prepared_not_observed` until the selected coding owner supplies captures in
both color modes and in the loading, no-data, and error states.
