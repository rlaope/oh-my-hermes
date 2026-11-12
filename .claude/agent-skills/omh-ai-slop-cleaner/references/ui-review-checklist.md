# UI Review Checklist

Load this when the cleanup target is UI code. It lists the generic visual
defaults that make a generated interface read as unreviewed. The reasoning
behind each one lives in `omh-frontend/references/taste-foundations.md`
(Review prompts - not bans); this file does not repeat it. What it adds is how
a cleanup pass treats each one.

Every item is a question, not a ban. A stated reason closes it and the
pattern stays: the brand asks for it, legibility or contrast needs it, the view
is a dense data screen, or the project's design system says so. No reason
means the default was never chosen, and that is the finding.

## The six prompts

Ordered by treatment: the first three are deletions a cleanup pass can make,
the last three are findings it hands on.

| Prompt | What the diff or the page shows | Cleanup treatment |
| --- | --- | --- |
| Shadows everywhere | one shadow repeated on cards, icons, logos, and page backgrounds alike | delete each shadow that marks neither a raised layer nor an interaction |
| Extreme gradients | loud multi-stop gradients on surfaces, buttons, or headline text | delete or flatten them unless the brand owns that look |
| Stacked section labels | a small label, a heading, a subheading, and one more paragraph over each section; decorative emoji badges | delete every layer that repeats what the heading says |
| Korean body text below 14px | Korean body copy at 11-13px | raise it to 14px; a dense data table keeps its size only with the reason written down |
| Default palette | a framework-default blue (`#3B82F6`) or a blue-to-purple scheme nobody chose | report it; a new palette is a design decision for `omh-frontend` |
| Uniform grid | rows of equal cards in a perfect 3 or 4 columns when the items are not equals | report it; a new layout is `omh-frontend` work |

Deletion-first still holds. Removing a shadow, a label, or a gradient is a
cleanup. Picking a new palette or a new layout is a redesign, and a redesign
goes to `omh-frontend`, or to `omh-frontend-refactor` when component behavior must stay
identical.

## Evidence

A finding about how a page looks needs the rendered page: a screenshot, or a
visual-QA verdict. Reading the CSS proves which value is set, not that it is
what renders. Say which of the two a finding rests on.

## Attribution

The six prompts and the review-mode split adapt concepts from the
`ai-slop-cleaner` skill of `Yeachan-Heo/oh-my-claudecode@8262f9f` (MIT),
reconstructed in OMH's own wording; the cleanup treatments are OMH's.
