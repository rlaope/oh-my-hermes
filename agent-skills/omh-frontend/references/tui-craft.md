# TUI Craft

**Hold terminal UI work to what a senior product designer at a top-tier product company — the Linear/Stripe/Supabase class — would sign off on. A default widget is
scaffolding, not finished UI — an unstyled list, table, or panel shipped
as it came out of the framework does not clear this bar any more than a
default-template web page would.** The terminal is a design medium with
its own materials — cells, box-drawing, a color budget, a keyboard — not
a place where the taste bar stops applying.

## Defaults are scaffolding

Framework widgets render something so development can start; what they
render is the placeholder, not the product. Every visible widget gets a
deliberate pass — selection treatment, header styling, alignment,
truncation, foreground hierarchy — or a stated decision in `DESIGN.md`
that the default genuinely matches the contract. "It rendered" is the
terminal's technically clean but flat: a defect to fix, not a baseline
to accept.

## Borders are weight — spend them sparingly

A border is the heaviest structural device a terminal has, and the
easiest to reach for. Boxes around everything read as noise, not
structure. Build hierarchy with spacing — blank lines, indents, column
gutters — and a muted-color ladder first: bright foreground for primary
content, dimmed for secondary, faint for chrome. Reserve borders for the
one or two containers that must read as containers. Typical failure:
every panel boxed, so no panel leads.

## Name one terminal aesthetic

As with web taste directions, blending terminal aesthetics by accident
produces mud. Name ONE in the `DESIGN.md` Overview and execute it
consistently across every screen, prompt, help line, and empty state:

- **Minimal utility** — quiet monochrome plus one accent; density and
  alignment do the hierarchy work. Typical failure: reading as unstyled
  because the accent and the alignment discipline never actually land.
- **Modern product** — the polished-CLI class: light or rounded borders
  used sparingly, a real palette, styled status and help surfaces.
  Typical failure: web-app ornament transplanted into cells.
- **Retro terminal** — amber or green phosphor, DOS-era mainframe mood,
  committed fully: charset, palette, and copy all in period. Typical
  failure: one nostalgic color over otherwise default widgets.
- **Dense operational** — dashboard-grade information density on a
  strict column grid with semantic color states. Typical failure:
  density without the grid, which is clutter.

## Box-drawing and color strategy

- Pick one box-drawing family — light, heavy, double, or rounded — and
  never mix families on one surface. Mixed corner styles are the
  template gravity of the terminal.
- Decide the color floor. Truecolor is not guaranteed: define the
  palette as roles (background layers, text ladder, accent, semantic
  states), give every role a 256-color fallback, and degrade
  deliberately instead of letting the terminal quantize for you.
- Never assume the user's background. The surface survives dark and
  light terminal themes, or `DESIGN.md` states the supported-theme
  decision explicitly.

## Keyboard states are the interaction states

There is no pointer. Focus, selection, and activation must each be
visible at a glance — a focus treatment that is only the hardware cursor
fails on sight. Cover focused, selected, active, disabled, loading,
empty, and error treatments for every interactive widget, and keep the
available keys discoverable on screen — a help line or footer — not
memorized folklore.

## Verify at named sizes — the pasted render is the screenshot

Terminal work has a screenshot-equivalent: rendered output captured at
an explicit size. Verification renders at 80x24 and 120x40 minimum —
plus the sizes the product actually targets — and pastes the captured
output as evidence. A claim without a pasted render at a named size is a
prepared claim, not an observed one.

## Short-terminal squeeze — a named defect class

When height shrinks, something must yield, and unowned yielding is the
defect: docked chrome crushing the content area, prompts pushed out of
view, scroll regions collapsing to zero. Decide in `DESIGN.md` which
region owns flexibility, what collapses first, and the minimum height
below which the surface degrades gracefully instead of breaking. The
80x24 render is the check that this decision was actually made.

## Anti-slop checklist — TUI rejects

These extend the anti-slop checklist in `taste-foundations.md`; reject
on sight:

- Unstyled default widget: a framework list, table, or panel shipped
  with its out-of-the-box styling.
- Border noise: boxes as the only structural device, panels boxed by
  reflex, mixed box-drawing families on one surface.
- Colorless hierarchy: everything at default foreground, or one accent
  doing every job with no muted ladder beneath it.
- Truecolor gamble: a palette that quantizes to mud on a 256-color
  terminal because no fallback was ever chosen.
- Cursor-only focus: interactive widgets whose focus state is invisible
  without hunting for the hardware cursor.
- Keybinding folklore: interactions that exist but appear nowhere on
  screen.
- One-size render: verified only in the author's terminal, with no
  80x24 or 120x40 evidence.
- Squeeze blindness: a short terminal crushing chrome into content
  because no region was chosen to yield.

## Boundary

TUI craft guidance shapes the prepared direction and contract. It never
substitutes for observed rendered evidence: the visual-QA owner judges
the pasted renders at their named sizes.

## Attribution

The idea of pairing a design-system contract file with taste-direction
material and an evidence-bound critique lane adapts concepts from the
`frontend` skill of `code-yeongyu/oh-my-openagent@9c62b62` (Sustainable Use
License 1.0) and its permissively licensed design upstreams:
`Leonxlnx/taste-skill` (MIT), `nextlevelbuilder/ui-ux-pro-max-skill` (MIT),
`Owl-Listener/designpowers` (MIT), and `nexu-io/open-design` (Apache-2.0).
No upstream text is reproduced; the wording here is OMH's own, and OMH keeps
its deterministic no-render boundary. Product names appear as quality
analogies only; OMH is not affiliated with, endorsed by, or sponsored by any
named company.

TUI-specific concepts — defaults-as-scaffolding, border restraint, and
the named-terminal-aesthetic discipline — additionally adapt ideas from
the community `tui-design` (kastheco) and `terminal-ui-design` (ingpoc)
skills and the Charm/lipgloss ecosystem's published guidance. No text
from those sources is reproduced either; the wording here is OMH's own.
