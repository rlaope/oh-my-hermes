# Award Judging Model

The instrument behind "make it award-winning". The rules are CSS Design Awards'
published ones; the score and stack tables are measured from public entry pages
and live sites, sampled 2026-09-03. Re-read both before quoting them, and name
the body and the read date in the artifact. Other award bodies score different
axes on different scales, so never carry these numbers to a different jury.

## The published model

CSSDA scores an entry on three axes:

| Axis | Reported weight | What it measures |
| --- | --- | --- |
| UI | 40% | Interface design: aesthetics, craft, and effects |
| UX | 30% | Experience and functionality |
| Innovation | 30% | New development and design ideas |

A jury panel scores each entry, and an entry page exposes the per-judge scores
alongside the public per-axis vote averages. Award tiers
(cssdesignawards.com/about, read 2026-11-07): Website of the Day needs a judge
average **above 8.00**, a figure CSSDA says varies with the quality of the
entries submitted; Special Kudos needs an average **above 6**; the public
awards need **more than 20 votes** and a judge average above 6. The 40/30/30
split is reported rather than stated in the jury rules, so when the artifact
depends on the ratio, mark it reported and score the axes separately too.

## The bar is a pass mark, not a ranking

Daily winners cluster immediately above the cutoff: most sit between 8.0 and
8.5, and a score above 8.6 is the exception. The distribution is a spike at the
threshold because 8.0 is where the award starts. "Award-winning" therefore
means *cleared the published floor of 8.0*, not exceptional, and a brief that
treats it as exceptional overbuilds. The day's cut can sit higher than 8.0.

## The three axes move together

Nine sampled entries, per-axis public scores:

| Entry | UI | UX | INN | Final | Axis spread |
| --- | --- | --- | --- | --- | --- |
| Why Zero | 8.87 | 8.90 | 8.93 | 8.90 | 0.06 |
| Son Daven | 8.46 | 8.51 | 8.53 | 8.50 | 0.07 |
| MECHA | 8.13 | 8.25 | 7.75 | 8.05 | 0.50 |
| monolayer | 7.77 | 7.63 | 7.73 | 7.71 | 0.14 |
| METRIC. | 7.60 | 7.69 | 7.63 | 7.64 | 0.09 |
| Jeffrey's LAB | 7.56 | 7.60 | 7.66 | 7.60 | 0.10 |
| Inngest | 7.60 | 7.18 | 7.62 | 7.47 | 0.44 |
| Thinkz | 7.16 | 7.39 | 7.31 | 7.28 | 0.23 |
| Royal Green | 6.97 | 6.97 | 6.93 | 6.96 | 0.04 |

The spread between a site's own three axes has a median of 0.10 and a maximum
of 0.50. The spread between sites is 1.94. **Axis spread is roughly a twentieth
of site spread**, so judges rate a site, not three independent properties.

Two rules follow, and they bound how this skill reports:

- Treat a lopsided profile as a reason to re-read the evidence. In the nine
  sampled entries the largest gap between a site's own axes was 0.50, so a gap
  above 1.0 in a self-assessment means re-check the evidence for both axes
  before reporting it; it is not proof the scoring is wrong.
- A weak axis is worth naming only near the threshold. MECHA is the case:
  Innovation 0.50 below UX drags a would-be 8.2 to 8.05. Below 8.0 the axis
  gap is not the problem, because **the whole site is the problem** and moving
  one axis 0.1 changes nothing.

Report the constraint honestly: at 7.3, say the site needs a level change, not
an axis fix. Reserve binding-constraint language for totals inside about 0.3
of the threshold, where a single axis can still decide it.

## What winners actually ship

The same nine sites, measured from their live HTML, CSS, and first-party
bundles:

| Capability | Sites | Read |
| --- | --- | --- |
| `clamp()` fluid type | 8/9 | Entry fee, not innovation |
| Self-hosted or variable font | 8/9 | Entry fee |
| `mix-blend-mode` | 6/9 | Common craft signal |
| Lenis or GSAP motion | 6/9 | Common, not required |
| `prefers-reduced-motion` | 6/9 | See below |
| Three.js or WebGL | 3/9 | **Not required** |

Two readings the table earns:

- **Fluid type and real typography are the floor.** The one site without
  `clamp()` and the one without a variable or self-hosted face are the bottom
  two scores. These buy no points; their absence costs them.
- **WebGL is not the price of Innovation.** Only a third of the sample ships
  3D at all, and the 8.50 entry scores 8.53 on Innovation with GSAP and
  scroll work alone. A brief that treats WebGL as the requirement is buying
  the most expensive path to an axis that accepts cheaper ones.

## What the innovation axis costs

Of the six sites shipping a motion library, **three respect
`prefers-reduced-motion` and three do not**. So the tradeoff is real at the
cutoff: some entries do buy Innovation by dropping the media query.

The two highest-scoring entries both ship heavy motion *and* respect it. That
is the pattern worth copying — the accessible path is not the lower-scoring
path, and the sites that skipped the query did not out-score the ones that
kept it.

The budgets stay authoritative. When an innovation move breaks one:

- Record it in `tradeoff_ledger/v1`: the move, the axis point it buys, the
  budget or success criterion it costs, and the mitigation if one exists.
- Let the user choose. Chasing a score past a WCAG criterion or a Core Web
  Vitals budget is a decision the brief records, never a default this skill
  takes.
- Prefer the move that buys the axis point without the cost: motion behind
  `prefers-reduced-motion`, a native control styled rather than rebuilt, a
  scene that degrades to a static poster. `omh-accessibility-audit` and
  `omh-frontend/references/web-vitals-budgets.md` own those budgets.

## Awwwards

Awwwards publishes four criteria instead (awwwards.com/about-evaluation, read
2026-11-07): Design 40%, Usability 30%, Creativity 20%, Content 10%, with
honorable mentions at 6.5 or more from the jury. Score those four axes against
rendered evidence the same way, and never mix them with the CSSDA axes or
thresholds above. For any other body, ask for its published rules URL and score
only the axes it publishes.

## Boundary

Scoring a surface against a published rubric is a self-assessment. A jury
scores submissions; OMH does not, and no score prepared here predicts a
placement, a selection, or an award. Axis scores require rendered evidence —
the visual-QA owner produces it, and an unrendered page keeps every axis
`not_observed`. The stack table is a nine-site sample read on one date, not a
survey; treat a single row as an example and never as a rule.

## Attribution

The judging axes, weights, tiers, and thresholds are factual reporting of CSS
Design Awards' published rules, read 2026-09-03. Per-axis scores are public
figures from entry pages; stack rows are measured from publicly served assets
on the same date. No page text, markup, or asset is reproduced here. OMH is
not affiliated with, endorsed by, or sponsored by CSS Design Awards, any award
body, or any site named above.
