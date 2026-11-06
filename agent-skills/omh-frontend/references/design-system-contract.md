# Design System Contract (DESIGN.md)

**The gate: no component code before `DESIGN.md` exists.** Design decisions
that live only in chat evaporate between screens; a contract file makes every
later component answer to the same tokens. When a project already has one,
read it and follow it — and when the work introduces a token, primitive,
interaction state, motion rule, or piece of accepted debt the contract
lacks, amend the contract before touching the code.

## One file, one format

`DESIGN.md` is also the file name of Google's open DESIGN.md format, and
Hermes bundles a `design-md` skill for that format. Two shapes for one file
would hand the model two contradicting instructions, so a new contract uses
no shape of OMH's own: it is a DESIGN.md in that format which also carries
OMH's extra sections. The format allows them, because a consumer keeps a
heading it does not recognize instead of rejecting the file.

- **File mechanics go to `design-md`.** For a file in the format, when
  Hermes' bundled `design-md` skill is available, load it to write the token
  block, lint the file, diff two versions, or export Tailwind or DTCG
  tokens. A file in the earlier OMH layout is not handed to it: its
  authoring adds front matter and reorders sections, which is the rewrite
  the legacy rule below forbids. This reference decides what the contract
  has to settle and when it blocks code; it does not restate the format's
  schema.
- **Lint counts only when it ran.** A lint result is observed contract
  evidence when Hermes, or the executor the user selected, ran
  `npx -y @google/design.md lint DESIGN.md` against the current file and
  the findings are in hand. An error finding (a broken token reference, for
  one) blocks the contract; each warning is reported together with what was
  decided about it. With no run, the lint status is `not_observed`; reading
  the file never makes it lint-clean. OMH itself runs no package and makes
  no network call.

## Token front matter

The file opens with a YAML block between two `---` lines. It always carries
`name:` and `colors:` with a `primary` entry, and adds `typography:`,
`spacing:`, `rounded:`, and `components:` for every group the design has. A
component points at tokens through references such as `{colors.primary}`
instead of repeating raw values, and a state that changes a value is a
sibling entry (`button-primary-hover`), never a nested key. A group left out
on purpose goes under `omitted:` with its reason, so the gap reads as a
decision. When the prose and a token disagree, the token wins and the prose
is corrected.

## Body sections

Body sections are `##` headings. The format's eight sections keep the
format's order; the four OMH sections (marked *OMH*) sit next to the section
they extend, which the format permits because its order check skips a
heading it does not know. Use each heading once: the format tells a consumer
to reject a file that repeats one. Every section is written (the Research
Log on greenfield builds), and an empty one states its decision ("no
elevation system; flat surfaces only") — silence is not a decision.

Write each heading as the bare name spelled exactly as listed, with no number
and no *OMH* marker (`## Colors`, `## Do's and Don'ts`, `## Research Log`).
The format matches heading text exactly, so `## 1. Overview` is a section it
does not know, and the order check never sees it.

1. **Overview** — the audience, three adjectives the surface must read as,
   and the chosen taste direction (primary, plus any deliberately borrowed
   elements with their reasons).
2. **Signature Element** *(OMH)* — the one element a template would not
   have, where it appears, and why this product earns it.
3. **Colors** — the full palette as `colors:` tokens: background layers,
   text hierarchy, accent budget, semantic states, borders. The prose names
   the proportion discipline (for example 60/30/10) and the contrast floor
   (WCAG AA at minimum). Write colors as semantic tokens, not raw palette
   steps:
   - **Surface and on-surface pairs.** Every surface token has the text
     token that sits on it. The front matter spells the pair `X` and `on-X`
     (`primary` / `on-primary`), the pattern of the format's recommended
     `surface` / `on-surface` names; in CSS, shadcn/ui names the same pair
     `X` and `X-foreground` (`card` / `card-foreground`) and daisyUI names
     it `X` and `X-content`. A component picks the pair, never a surface
     with an unrelated text color, so contrast is checked once per pair
     instead of once per component.
   - **The focus ring is its own token** (`ring`), not the accent reused, so
     focus stays visible on every surface the accent sits on. Once
     `components:` exists, a color token no component references draws an
     `orphaned-tokens` warning unless it is in a referenced token's family or
     in the Material baseline families; for `ring` and the `chart-N` set that
     warning is expected, not a contract failure.
   - **Themes redefine variables; components never branch.** A front-matter
     token holds one value, so it records the default theme, and the prose
     gives every other theme's values under the same token names. In CSS,
     light, dark, and any brand theme redefine the same variable names under
     `:root`, `.dark`, or `[data-theme="..."]`; OKLCH values are a sound
     choice because lightness steps stay perceptually even. Do not write
     `dark:` variants on semantic colors - a `dark:` override beside a
     semantic token means the token is not doing its job, and the two will
     disagree at the next theme change.
4. **Typography** — the pairing (at most two families), a modular scale
   whose named steps are the `typography:` tokens, weights in use, and
   line-height rules for body versus display. When the audience reads CJK:
   the fallback stacks, CJK line-height and letter-spacing rules, and
   `word-break`/truncation behavior for the heavy script.
5. **Layout** — the base unit and spacing scale as `spacing:` tokens,
   container widths, the grid, and which element owns scroll on every
   screen shape.
6. **Elevation & Depth** — the elevation system (shadows, borders, blur) or
   the explicit decision not to have one.
7. **Shapes** — the corner language as the `rounded:` scale. **One radius
   knob.** A single `--radius` drives the radius scale (small, medium, large
   derived from it), so the shape language changes in one place.
8. **Components** — the reusable primitives (button, input, card, nav,
   table, ...) with their variants and every interaction state: default,
   hover, focus-visible, active, disabled, loading, error, empty. A state
   that changes a token value is its own `components:` entry.
9. **Motion & Interaction** *(OMH)* — duration and easing tokens as named
   profiles, what animates and what never does, and the
   `prefers-reduced-motion` behavior. The format has no motion token group,
   so the profiles live in this section. Motion is punctuation, not
   decoration.
10. **Do's and Don'ts** — rules a reviewer can check against a screenshot:
    the accent budget in practice, the rules of any named style preset, and
    the patterns this surface refuses.
11. **Accessibility Constraints & Accepted Debt** *(OMH)* — the constraints
    honored (keyboard paths, focus order, contrast) and the debt knowingly
    accepted, each with its reason.
12. **Research Log** *(OMH, greenfield builds)* — an entry for every
    research lane that ran: the source consulted, what was taken from it
    (layout rhythm, color logic, type pairing choices), and any skipped lane
    with its reason. No log entry means the lane did not run.

## A contract in the earlier OMH layout

Before this alignment, an OMH contract had no front matter and nine
numbered sections: 0 Research Log, 1 Atmosphere & Identity, 2 Color,
3 Typography, 4 Spacing & Layout, 5 Components, 6 Motion & Interaction,
7 Depth & Surface, 8 Accessibility Constraints & Accepted Debt. A file in
that layout is still a valid contract and satisfies the gate.

- Read and follow it as written, and amend it in its own layout. Do not
  rewrite it into the format unasked.
- Other references name the format's sections and token groups. In a legacy
  file, write each into its counterpart by reading the conversion map below
  in reverse, as prose and without adding front matter: Overview and
  Signature Element into Atmosphere & Identity; Colors, Shapes, `colors:`,
  and `rounded:` into Color; Layout and `spacing:` into Spacing & Layout;
  Elevation & Depth into Depth & Surface; `typography:` and `components:`
  into Typography and Components. Do's and Don'ts has no counterpart, since
  the format added it; as an added mapping, its rules go into Atmosphere &
  Identity.
- Lint says nothing about it: with no front matter and no fenced YAML block,
  the linter reports a single no-YAML warning and runs no other check. That
  warning is not a contract failure.
- Convert only when the user asks. Atmosphere & Identity splits into
  Overview and Signature Element; Color becomes Colors, its values move into
  `colors:`, and its radius knob moves to Shapes; Spacing & Layout becomes
  Layout with `spacing:` tokens; Depth & Surface becomes Elevation & Depth;
  Typography and Components keep their names and gain their token groups;
  Research Log, Motion & Interaction, and Accessibility Constraints &
  Accepted Debt carry over as OMH sections; Do's and Don'ts is new. A
  conversion moves decisions and makes none: a gap it exposes goes to the
  user as a question, never filled in silently.

## Local reference data

`omh design data --kind palette|font|ux [--context <product context>]` prints
curated local rows: palette role tokens with the product contexts they suit,
display/body font stacks with fallbacks and CJK notes, and UX guidelines with
the reason each one holds. Contexts include `dashboard`, `dev-tool`,
`fintech`, `data-viz`, `editorial`, `docs`, `ecommerce`, `healthcare`,
`landing`, `mobile`, `portfolio`, `public-sector`, `saas`, and `education`.
Query it while filling Colors, Typography, and Components so the starting
tokens are a considered choice instead of a framework default, and while
checking the review prompts in `references/taste-foundations.md`.

The rows are input, not authority. Nothing is decided until it is written
into `DESIGN.md`, and the contract — not the query — is what gates the code.
The lookup is deterministic local data: no network call, no model call, and
no rendered evidence.

## Workflow

- Greenfield: design research is a build step, not optional exploration —
  consult references and real product surfaces, record each lane in the
  Research Log, and write the contract BEFORE the first component.
- Existing UI without a contract: stop and ask the user which path they
  want — either match the existing visual language and keep new styling
  local to the code it touches, or pause to extract the contract and shared
  primitives before continuing. Never decide silently.
- Every implementation cites the token it uses. A value that appears in
  code but not in `DESIGN.md` is drift: either the contract or the code is
  wrong, and one of them gets fixed.

## Boundary

`DESIGN.md` is a prepared contract, not rendered evidence: implementation,
screenshots, accessibility checks, and visual verdicts stay observed-only
through the visual-QA and web-QA owners. An observed lint run speaks for the
file — its structure, its token references, the contrast of the component
color pairs it declares — and never for the rendered UI.

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

The token front matter, the section names and their order, and the lint
command follow Google's DESIGN.md format
(`google-labs-code/design.md@9bf8eae`, Apache-2.0). Handing file authoring,
lint, diff, and export to Hermes' bundled `design-md` skill follows that
skill's stated scope (`NousResearch/hermes-agent@63d0b94`, MIT). Both were
read as references; the wording here is OMH's own.
