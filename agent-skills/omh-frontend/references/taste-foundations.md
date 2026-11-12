# Taste Foundations

**Hold the work to what a senior product designer at a top-tier product company — the Linear/Stripe/Supabase class — would sign off on. Technically clean output that reads
flat does not clear this bar — flatness is a defect to fix, not a baseline
to accept.** Generic output is not a neutral outcome; it is the specific
failure this reference exists to prevent.

## Name one primary direction

Taste directions pull in different directions; blending them by accident
produces mud. Name ONE primary direction in the `DESIGN.md` Overview. An
element genuinely borrowed from another direction is allowed — named there
with its reason — so a hybrid brief (a premium marketing shell over an
operational product) stays expressible without dissolving into no direction
at all.

- **Operational** — dense internal tools and dashboards where utility
  leads: information density over drama, native controls, stable
  dimensions, restrained color. Typical failure: settling here when the
  brief wants a public, polished surface.
- **Minimalist / editorial** — briefs that want whitespace-led calm and
  reading-first structure: generous space, a strict type scale doing the
  hierarchy work, a single accent, almost no ornament. Typical failure:
  emptiness without rhythm — minimal is a spacing system, not an absence.
- **Premium / soft** — surfaces that should feel costly and unhurried:
  layered depth, soft large-radius shadows, muted-but-saturated palette,
  slow small motion. Typical failure: gloss layered over weak hierarchy.
- **Bold / expressive** — statement pages that lead with oversized display
  type and hard contrast, breaking one grid rule at a time on purpose.
  Typical failure: every element shouting, so nothing leads.

## Style presets are rule sets, not adjectives

When a brief names a style - "neobrutalism", "glassy", "Swiss" - write it
into the `DESIGN.md` Do's and Don'ts as concrete rules a reviewer can check
against a screenshot. A style name with no rules is the same unactionable
negation as "make it modern".

**Neobrutalism**, as a worked example:

- Thick, solid borders on every element, usually in one dark ink color.
- Hard shadows: a flat offset with zero blur, in the same ink. The offset
  value is NOT published by the reference library; pick one (a few pixels on
  both axes) and record it as the project's own token.
- Flat, saturated fills. No gradients, no glass, no blur anywhere.
- Square or near-square corners, heavy display type.
- The active state presses into its shadow: the element translates by the
  shadow offset and the shadow shrinks to nothing.
- Contrast check every saturated fill against the ink text on it; loud
  yellows and pinks pass, mid-tone blues and greens often do not.
- A dark-mode border strategy, decided up front: a dark ink border vanishes
  on a dark ground, so the dark theme needs a light ink or a lighter surface
  layer, not the light theme's border inverted by accident.

**Mood-named directions.** A direction can also be recorded the way Refero's
style library records real sites: a mood name ("midnight command center",
"white with one accent") over a `DESIGN.md` that carries the palette, type,
spacing, and component rules extracted from a reference. The name is a
handle; the rules underneath are the decision.

## Footer anatomy

A footer is the last section a visitor who read everything reaches, and the
one templates fill with filler. Its usual parts:

- the wordmark with a one-line positioning statement;
- link columns grouped by what a visitor is looking for;
- a closing call to action;
- social links;
- legal and credits.

Pick the footer's style deliberately rather than inheriting a template: a
large typographic wordmark, a dense link grid, or cards. On mobile the link
columns collapse - into stacked groups or disclosure sections - instead of
shrinking to unreadable type.

## The default aesthetic you already carry

A coding model does not start neutral. Left to its own judgment it converges
on one house style — cream and off-white grounds, a serif display face over a
quiet sans, muted terracotta or clay accents, wide margins, an editorial
rhythm. It is a real aesthetic and often a good one, but it is a prior, not a
response to the brief, and it arrives whether or not anyone chose it.

Say which case the brief is before using it:

- **It suits** editorial and long-form reading, portfolio and studio sites,
  hospitality, food, wellness, and print-adjacent marketing — briefs where
  warmth and unhurried calm are the product.
- **It is a failure mode** for dashboards, developer tools, admin consoles,
  fintech, trading, analytics, and anything data-dense. Cream grounds wash out
  status color, serif display faces fight tabular figures, and editorial
  margins spend the width a dense table needs. An operational brief rendered
  in the default prior reads as a blog that grew a table.

## Overriding the default takes tokens, not negations

"Don't make it look AI-generated", "make it minimal", "less generic", "more
modern" — none of these move the output. They retire one default and leave the
next-most-likely default in its place, which is usually the same house style
with the serif swapped out. A negation names what to stop; it never names
where to go.

An override is actionable only when it carries concrete values:

- a palette as hex — every background layer, every text level, the accent and
  its budget;
- a typeface stack — display family, text family, and fallbacks, including the
  CJK stack when the audience needs one;
- the geometry that travels with them: radius, border weight, spacing base.

Those land in `DESIGN.md` as `colors:`, `typography:`, `rounded:`, and
`spacing:` tokens before implementation starts. When the direction arrives as
negations only, convert it into tokens and state them back — a named palette
and stack the user can reject is a decision; "less AI-looking" is not.

## Review prompts — not bans

The patterns below are not forbidden. They are the ones that show up when
nothing chose them, so each is a question the review asks; a stated reason
closes it and keeps the pattern.

- **Framework blue** — is the primary `#3B82F6` (or a framework-default
  neighbour) because the brand is blue, or because it was already there? A
  default accent with no brand rationale is an unmade decision.
- **Glass surfaces and cyan-to-purple gradients** — what do the blur and the
  gradient communicate? Depth and brand can both justify them; "it looked
  modern" cannot.
- **Inter everywhere** — Inter and the system stack are good text faces and
  poor signatures. Is anything on the page doing typographic work the default
  UI face is not?
- **Bounce easing** — does the overshoot describe a physical motion the user
  initiated, or is it decoration on a menu that should settle?
- **Shadows on every surface** — elevation is a hierarchy signal, and when
  every card carries the same shadow it signals nothing. Which surfaces are
  deliberately raised, and above what?
- **Eyebrow, title, description, on every section** — does each section need
  all three, or did the template supply them? Stacked labels above every
  heading are padding wearing hierarchy's clothes.
- **The uniform grid** — a perfect 3- or 4-column row is right when the items
  are peers of equal weight. When they are not, an asymmetric or bento rhythm
  says which one leads, and the uniform grid says nothing leads.
- **CJK body under 14px** — Korean, Japanese, and Chinese glyphs carry more
  strokes inside the same em. Copy that reads cleanly at 13px in Latin is
  degraded in CJK: hold a 14px floor for Korean body text, and measure
  captions against that floor instead of shrinking below it.

## Anti-slop checklist — reject on sight

- Template gravity: rows of three equal cards, hero-icon-grid boilerplate,
  floating decorative shapes with no content role.
- One-note palette: a single flood color plus gray, no layered backgrounds,
  no semantic states.
- Weak hierarchy: adjacent text sizes doing three jobs, everything at
  medium weight, headings that do not organize scanning.
- Arrhythmic spacing: values off the scale, sections that touch, sibling
  padding that differs for no stated reason.
- Placeholder gravity: lorem-shaped copy, unrealistic content, empty states
  never designed.
- Missing states: any interactive primitive without hover, focus-visible,
  active, disabled, loading, error, and empty treatments.
- Motion as decoration: animation that communicates neither state nor
  causality, or that ignores `prefers-reduced-motion`.
- CJK as an afterthought: Latin-tuned line-height and truncation applied
  unchanged to a Korean, Japanese, or Chinese audience.

## Content before chrome

Before laying anything out, list what the surface must say and decide what
each block is for: draw attention, explain, build trust, support
comparison, drive the action, or help people find their way. Sequence
sections in the order a visitor actually decides; visual symmetry never
outranks that sequence. Review content accuracy and hierarchy before any
polish — a beautiful wrong page fails first on content.

## Interface copy

Labels, toasts, errors, and empty states steer the reader as much as layout
does, so read them in the same review. Four checks:

- Name things the way the reader already does. A clinic receptionist books
  "appointments", not "calendar slot reservations". A label lifted from the
  schema, the API, or the code is a finding.
- One action keeps one verb everywhere it shows up: the button, its
  in-progress label, the result message, and any undo. A button that says
  "Archive" is followed by a message that the item was archived, not
  "Moved". Generic verbs such as "Submit", "Confirm", or "OK" tell the
  reader nothing about the result.
- An error message gives the cause, then the way out: "That date is fully
  booked. Pick another day or join the waitlist." Drop the "Oops" and the
  "Sorry"; "An error occurred" leaves the reader with nothing to do.
- An empty list carries the control that fills it: "No appointments today"
  sits beside "Book appointment". An illustration without that control is
  decoration.

Korean, Japanese, and Chinese copy takes the same checks in its own
register; translate the meaning of an action name, and keep it identical
across the flow in every locale.

## Screen copy: what the page says about itself

Interface copy covers the controls. This section covers the sentences, numbers,
and labels a page uses to describe itself; review them against the captured
screen, not the source.

Review prompts - a stated reason keeps each one:

- **A hero sentence that introduces the product** - does it tell a visitor
  something they could not infer from the name and the first image, or does it
  restate them?
- **A one-line description under every section title** - the section-level
  version of the eyebrow, title, and description prompt above. Which sections
  need it to be understood?
- **A contrast headline of the "not X but Y" shape** - is X something a visitor
  believed before arriving? A denial of a position nobody held spends the
  headline on nothing.
- **A paragraph narrating how a decision was reached** - does the visitor need
  the history, or only the result? The history belongs in a changelog or a case
  study.

Reject on sight:

- 01 / 02 / 03 numbering on content that has no order. Numbers promise a
  sequence; use them only when the reader must take the items in that order.
- An outcome number with no source.

The test for any number on the page is: "what is this number trying to prove?"

- A comparison measured on the same basis stays, with the basis visible.
- A configuration or limit value that explains behaviour stays, because it
  tells the reader what to expect.
- A boast about improvement goes, or gets its source beside it.

When there is no real content, do not invent sentences, roles, or experience.
Leave the title and the image slot in place and ask what goes there. An invented
testimonial or team bio is a claim about real people that nobody made.

After the build, read every string on the captured screen. Components fill in
numbers and copy on their own, and the placeholder a component ships with is
easy to leave in.

## Boundary

Taste guidance shapes the prepared direction and contract. It never
substitutes for observed rendered evidence: the visual-QA owner judges what
actually shipped.

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

The interface-copy checks adapt ideas from the `frontend-design` skill in
`anthropics/claude-plugins-official` (Apache-2.0); no text from it is
reproduced, and the examples and wording here are OMH's own.
