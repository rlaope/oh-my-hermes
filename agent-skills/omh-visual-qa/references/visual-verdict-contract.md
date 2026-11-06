# Visual Verdict Contract

Subjective visual work has no natural stopping point. "Looks better" ends the
loop whenever patience runs out, which is how a surface gets revised four
times and ships the same defect. This contract gives the loop a number: one
scored verdict per capture round, a threshold that decides whether the round
ends, and a required next action when it does not.

## The verdict shape

A round returns one JSON object and nothing else — no prose above it, no
commentary after it:

```json
{
  "score": 84,
  "verdict": "REVISE",
  "differences": [
    {
      "difference": "Card padding is 12px against the reference's 24px, so the three-up row reads cramped at 1440px.",
      "suggestion": "Raise card padding to the contract's space-6 step and recapture the row at 1440/768/375."
    }
  ]
}
```

- `score` — an integer from 0 to 100. Not a band, not a letter, not a range: a
  whole number, so two rounds are comparable and a regression is visible.
- `verdict` — `PASS`, `REVISE`, or `BLOCK`, the same three states
  `visual_qa_verdict/v1` already carries.
- `differences` — one entry per observed difference, each pairing what is
  wrong with the smallest change that would fix it. A difference with no
  suggestion is an unfinished finding; a suggestion with no difference is an
  opinion. Neither is admissible.

An empty `differences` list under a sub-threshold score is a contradiction:
either the differences were never written down, or the score was guessed.

## The threshold

**90 is the pass line.** At or above it the round may return `PASS`, provided
the evidence rules below still hold. Under it the verdict is `REVISE` and the
loop is not over: the differences go back to the implementation owner, the
named edits land, the same pages, states, and viewports are recaptured, and a
fresh scored round runs against the new captures. Rescoring the same captures
is not a round.

The loop ends in one of three stated states:

- the round scores 90 or above and the evidence rules hold — `PASS`;
- the round scores under 90 and another edit-and-recapture round is available
  — `REVISE`, with the differences attached;
- the round cannot proceed — missing captures, mismatched lineage, an
  exhausted iteration budget — `BLOCK`, naming exactly what is missing. An
  exhausted budget is a reported blocker, never a quiet `PASS`.

The score never substitutes for the lineage rule. A 96 on captures whose
repository and revision do not match the package target is still not a `PASS`.

## Pixel diff is the secondary aid

An objective diff — `diffRatio`, `similarityScore`, `dimensionsMatch`, hotspot
coordinates — answers where two images differ. It does not answer whether the
difference matters, and it cannot see a defect that is pixel-identical to its
reference and wrong anyway: contrast under the floor, a label that says the
wrong thing, a hierarchy that reads flat.

So the diff localizes hotspots; it does not score:

- it points the review at the regions worth looking at first;
- it never produces the `score`, and a low `diffRatio` is not evidence of a
  high one;
- a region with no diff is still judged on the rubric axes;
- `visual_diff_evidence/v1` and `visual_hotspot_review/v1` stay separate
  fields from the verdict, because they answer a different question.

The score comes from the rubric instead: the axes in
`omh-design-quality-gate/references/design-critique-rubric.md`, judged against
the declared target, with `differences` as the working record of every
deduction.

## Boundary

OMH prepares this contract; it does not run it. Captures, edits, and reruns
happen in whichever executor or wrapper lane the user selected — named in the
handoff, never assumed. What OMH holds is the shape of the verdict, the
threshold, and the rule that a sub-threshold score owes another observed
round. A scored verdict with no attached observed captures is a prepared
claim, not an observed one.

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

The scored-verdict shape additionally adapts the score-then-iterate pattern
common to community visual-review skills, restated in OMH's prepared-versus-
observed vocabulary. No text from any of them is reproduced either; the
wording here is OMH's own.
