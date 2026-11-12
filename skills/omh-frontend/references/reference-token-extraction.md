# Reference Token Extraction

A user-supplied reference is the visual contract. The work is extraction
into `DESIGN.md`, not admiration: a reference that is only glanced at
degrades into a vague mood, the contract inherits none of its precision,
and the output lands back at generic — which is what the gate exists to
stop.

## Static reference (screenshot, mockup, Figma export)

Extract into `DESIGN.md`, naming the reference in the Research Log:

- palette samples per background layer, text level, and accent;
- the type scale as measured ratios (display/heading/body/caption), the
  weights in play, and how line-height behaves;
- layout geometry: container width, column rhythm, section spacing values;
- component anatomy: radii, borders, shadows, and every state treatment the
  reference shows;
- copy tone and density — the real shape of the content, not lorem
  geometry.

## Live URL reference

When the user's selected executor or browser lane can drive a page, extract
runtime truth instead of guessing from pixels: computed styles for tokens,
the actual default/hover/focus/active states, transition durations and
easings, and responsive behavior at the breakpoints that matter. Record
what was extracted in the Research Log. OMH itself never launches a
browser, network call, or daemon — extraction happens in the lane the user
selected, and only its recorded findings enter the contract.

## Fidelity discipline

- Extract tokens and layout grammar; never copy logos, trademarks, or
  brand copy.
- Recombine into project-specific primitives — the reference calibrates
  quality; it does not become the product.
- Final QA for reference-driven work goes to the visual-QA owner: request a
  `visual_qa_plan/v1` whose references name the supplied reference, with
  the visual-fidelity review perspective comparing the rendered result
  against it side by side — and verify the implementation is a reusable
  design-system build, not a screenshot-matched one-off.

## Skeleton versus brand

A reference carries two layers: a skeleton (layout, spacing rhythm,
component anatomy, motion) and a brand (colour and type). They are taken
separately.

- **A project that already has a brand or design system** takes skeleton and
  motion from the reference, and colour and type from its own brand. Taking
  the reference's colour and type as well would replace the brand with the
  reference.
- **Colour and type are extracted too** when no brand exists yet, or when the
  user asked to match the reference. Record which of the two applied in the
  Research Log.
- **Several references** are rebuilt on one spacing unit, one grid and one
  type scale, with one transition treatment across all borrowed sections.
  Stacked as they came, they read as several sites on one page.
- **Drop what only meant something for the reference's owner**: its mascot,
  its seasonal banner, its menu names.

## Remove traces before it leaves the team

Before a result goes outside the team, search it for traces of the
reference: its name in titles, comments and metadata, redrawn copies of its
artwork, and working notes that name it. The search is a command whose
output is in hand; reading the files does not count. The result's own copy
does not name the reference either. Keep the Research Log, which stays with
the team, as the one place the reference is named.

## Boundary

Extraction produces a prepared contract. Rendered comparisons, screenshots,
and PASS verdicts belong to the visual-QA owner and stay observed-only.

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
