# Worked Example: Capacity Planning

Hire, outsource, or cut scope is an options-tradeoffs-decision question, and
this skill's frame already fits it. What it needs is the quantification,
because the failure mode here is not a missing framework - it is a discussion
where "the team is stretched" and "we could hire" are compared to each other
without either being a number.

## Quantify both sides in the same unit

Pick one unit and hold it for the whole analysis. Person-weeks is usually the
least arguable; story points are fine if the team already estimates in them and
has a measured throughput.

**Demand.** Every committed item with its estimate, plus the work that is not
on the roadmap and always happens: support escalations, on-call, code review,
interviewing, and the maintenance nobody plans. Take those from the last two
quarters rather than from intention - the gap between planned and actual is
frequently the whole finding, and a demand figure that omits them understates
by a third or more in most teams.

**Capacity.** Headcount times weeks, minus holiday, leave, onboarding time for
anyone who joined in the window, and the fraction of senior time the other
items above already consumed. Then subtract the capacity that is not fungible:
a backend person cannot absorb a design backlog, so capacity that cannot reach
the demand does not count against it.

## The worked shape

For one quarter, one team:

| | Person-weeks |
| --- | --- |
| Committed roadmap | 52 |
| Unplanned (from last two quarters' actuals) | 21 |
| **Demand total** | **73** |
| Headcount x weeks (5 x 13) | 65 |
| Holiday, leave, onboarding | -9 |
| **Capacity total** | **56** |
| **Gap** | **17 person-weeks, 23% of demand** |

A gap stated as a percentage of demand is what makes the three options
comparable, because each one closes a different fraction of it at a different
price and a different lag.

## The three options, priced and lagged

| Option | Closes | Lands in | Costs | Risk |
| --- | --- | --- | --- | --- |
| Hire | the gap permanently, once ramped | one to two quarters, counting ramp | salary plus the senior time recruiting and onboarding consume - which comes out of this quarter's capacity | the gap is worse before it is better |
| Outsource | a bounded, specifiable slice | weeks | contract rate plus the internal time to specify and review | only works where the work can be handed over without the context that is not written down |
| Cut scope | exactly what is cut | immediately | whatever the cut item was for | the only option that closes the gap this quarter, and the only one whose cost is a commitment to somebody |

The comparison is the deliverable. Hiring to close a 17-week gap that exists
this quarter does not close it this quarter; saying so is the analysis.

## What the brief carries

The demand and capacity figures with their sources, the gap as an absolute and
a percentage, the three options priced and lagged, the recommendation, and the
assumptions that would change it - most often the unplanned-work figure, which
is the one drawn from actuals and the one most likely to be disputed.

## Boundary

Estimates, throughput figures, and the unplanned-work fraction come from what
the user supplies or from records they point at. A capacity brief is a
recommendation, not an approved hire, a signed contract, or a descoped roadmap.
