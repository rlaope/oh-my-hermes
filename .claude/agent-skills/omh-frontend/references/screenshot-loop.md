# Screenshot Iteration Loop

**Code that was only read is UI that was never seen.** Structural
reasoning predicts what the pixels should be; only a rendered capture
shows what they are. After implementation lands on a web surface, the
work is not done until the loop below has run to an empty difference
list — a first pass that "looks done" from the code usually is not, and
two or three rounds are the normal cost of clearing
what a senior product designer at a top-tier product company — the Linear/Stripe/Supabase class — would sign off on.

## Live environment first

Judge the running UI before re-reading the code. Load the real pages
with real content, real fonts, and real breakpoints, and interact with
them — hover, focus, scroll, open the modal — before forming any
opinion from the source. Reviewing the implementation by reading what
was supposed to produce it is working blind; the capture, not the
diff, is the surface under review.

## During implementation

The loop below judges a finished surface. Before it, every change that
affects what renders gets its own look: after the change, capture the
affected page, state, or (for a 3D or canvas scene) the default camera and
each declared preset, and read the capture before making the next change. A
batch of unseen edits compounds: a shifted layout, a wrong colour, or a
broken frame hides behind the next edit, and the final loop then has to
unwind several defects at once. A change that was not looked at is not done.
This does not replace the loop: the 1440/768/375 pass still runs once the
work lands.

## The loop

1. Implement against `DESIGN.md` (the contract from
   `design-system-contract.md` — it exists before any component code).
2. Capture the affected pages and states at 1440px, 768px, and 375px
   wide — desktop, tablet, and mobile. These are the web minimum, the
   counterpart of the TUI's 80x24 and 120x40; add the widths the
   product actually targets. Capture each in every theme the contract
   defines, and once with `prefers-reduced-motion: reduce` for any surface
   that animates.
3. Compare each capture against the comparison target, side by side.
4. List every difference — spacing, weight, color, alignment,
   truncation, state treatment — however small. A difference you did
   not write down is a difference you never judged.
5. Fix, recapture at the same widths, re-compare.
6. Exit only when the difference list is empty. An exhausted iteration
   budget is a reportable blocker, not a quiet exit.

## Comparison target

- A user-supplied mock, reference screenshot, or Figma export is the
  target; differences are read against it directly.
- Otherwise `DESIGN.md` is the target: each difference cites the token,
  spacing rule, type step, or state treatment it violates.
- Neither exists: stop. The contract gate was skipped — iterating
  toward an unstated target converges on generic. Write the contract
  first.

## Triage every finding

Label each difference the moment it is listed:

- **[Blocker]** — broken layout, unusable control, unreadable text,
  contract violation on a primary surface.
- **[High]** — clearly visible deviation from the target on any
  covered viewport or state.
- **[Medium]** — noticeable in a side-by-side but not at a glance.
- **Nit:** — polish; record it even when it will be accepted.

State problems, not prescriptions — name what is wrong and where, and
let the fix be decided at the code. Every finding attaches the capture
that shows it, cropped or annotated when the defect is small. Triage
orders the fixing and, when a loop is cut short, states exactly what
remains at which severity.

## Where `omh-visual-qa` takes over

This loop is the builder's inner iteration, not the QA verdict. The
enumeration of what to capture — every route, viewport, scroll
position, modal/tab state, and CJK-heavy region — is owned by
`omh-visual-qa`'s viewport_state_capture_matrix/v1; when the surface has
more than the pages just touched, capture from that matrix instead of
re-deriving a private list, and read 1440/768/375 as this loop's
minimum widths inside the matrix's viewport axis. An empty difference
list ends the loop; it is not PASS. PASS, REVISE, or BLOCK stays with
`omh-visual-qa`, judged on observed captures whose source lineage matches
the target.

## Boundary

OMH never launches a browser or takes a screenshot. The loop runs
where the implementation runs, and its captures are executor-observed
evidence. A loop claim without attached captures at named widths is a
prepared claim, not an observed one.

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

The screenshot-iterate concept additionally adapts published guidance
from Anthropic's Claude Code best practices (implement, screenshot,
compare, iterate) and the OneRedOak design-review workflow
(live-environment-first review, 1440/768/375px responsiveness passes,
severity-triaged findings with attached screenshots). No text from
those sources is reproduced either; the wording here is OMH's own.
