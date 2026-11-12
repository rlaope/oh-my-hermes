# Web Vitals Budgets

Thresholds, and the discipline that makes a number mean something. "Feels
faster" is not a result; a metric with a budget, a device class, and an
attribution is.

## The thresholds

Field percentiles, judged at the 75th percentile of real sessions:

| Metric | Good | Needs improvement | Poor |
| --- | --- | --- | --- |
| LCP - largest contentful paint | under 2.5s | 2.5s to 4.0s | over 4.0s |
| INP - interaction to next paint | under 200ms | 200ms to 500ms | over 500ms |
| CLS - cumulative layout shift | under 0.1 | 0.1 to 0.25 | over 0.25 |

These are the platform's published bars, not a preference: quote them, do not
soften them to fit a result.

## Field is not lab

A lab run (a synthetic audit on one machine) and field data (what real
sessions recorded) answer different questions. A lab number is reproducible
and diagnostic; a field percentile is the truth about users and cannot be
produced by running the audit again.

- A p75 claim needs field data. A lab run that scores well is evidence the
  change is *plausible*, never that the percentile moved.
- A lab run has no INP at all in the meaningful sense: interaction latency
  depends on what users actually do. Treat a lab interaction figure as a
  smoke check.
- One lab run is one sample on one device profile. Report the profile, or
  the number is not comparable to the previous one.

## Budget before change

Pick the budget first, one metric at a time, and record what it is measured
against:

1. **The metric and its bar** - which of the three, and the number this
   change must land under.
2. **The device and network class** - the profile the budget is judged on. A
   figure from an unthrottled desktop is not comparable to a mid-tier mobile
   figure, and moving between them silently is how a regression reads as a
   win.
3. **The page and the load shape** - which route, cold or warm, first visit
   or repeat, authenticated or not.
4. **The baseline** - the current number under that exact profile, captured
   before the change.

A budget chosen after seeing the result is not a budget; it is a description
of what happened.

## Attribution before optimization

Never optimize a metric - optimize the thing the metric measured. Each metric
names its own attribution question, and the answer is what the change
targets:

| Metric | The question the run must answer first |
| --- | --- |
| LCP | Which element is the LCP element, and which phase dominates - server response, resource load delay, resource load, or render delay? |
| INP | Which interaction produced the worst paint, and where did it go - input delay, processing, or presentation? |
| CLS | Which node shifted, at what point in the load, and what inserted or resized above it? |

A plan that lists optimizations without naming the LCP element, the worst
interaction, or the shifting node is folklore. The corollary: a change that
improves a different element than the one attributed did not fix the metric,
whatever the aggregate did that day.

## Instrumentation

Real-user measurement reports the field percentiles; the lab audit
diagnoses. Both are recorded with the same metadata (route, device class,
build, date), because a number without its conditions cannot be compared to
next month's number. Naming a specific analytics vendor is out of scope
here - the contract is the metadata, not the product.

## Boundary

A budget, an attribution, or an optimization plan is prepared_not_observed.
Only an observed measurement run is evidence, a lab pass is never a claim
about real users, and a metric that improved is not a claim that the page is
fast for anyone in particular until the field percentile says so.
