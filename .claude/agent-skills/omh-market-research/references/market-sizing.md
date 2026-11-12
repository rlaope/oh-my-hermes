# Market sizing method and worksheet

Use only for a scoped addressable-market question. Do not supply default figures.

1. Freeze buyer versus user, geography, product/use-case boundary, period,
   currency/base year, count unit and revenue denominator. Exclude substitutes
   only with a reason. Distinguish annual revenue, annual spend, installed stock,
   transactions and potential buyers; never sum incompatible measures.
2. Register each operand before calculation: `I1 | value or unknown | unit |
   population/denominator | observation period | S1 or A1 | applicability`.
   `S1` names a retrieved source; `A1` names an explicit assumption with owner,
   rationale, plausible bounds and validation need. A source pointer is not a read.
3. Build top-down TAM from the broad eligible population or spend, applying
   documented segment filters without double-counting overlapping categories.
   Build bottom-up TAM from eligible buyer counts times annual spend per buyer
   (or annual units times price per unit). If inputs are unavailable, show the
   symbolic formula and unknown, never a fabricated estimate.
4. Derive SAM by product, geography, channel, regulatory and service constraints
   within TAM. Derive SOM for an explicit horizon from reachable accounts,
   evidenced conversion assumptions, sales capacity, onboarding capacity and
   retention. Do not select an arbitrary share of TAM. Require SOM <= SAM <= TAM
   only when all three use the same currency, period and denominator.
5. Run formulas with a calculator or code tool and retain command/expression,
   input IDs, result and unit. Record exchange-rate/date and inflation/base-year
   adjustments separately; unknown operands must not silently become zero.
6. Reconcile top-down and bottom-up results: inspect taxonomy, overlap, time
   period and spend-versus-revenue definitions. Never average incompatible
   estimates. If only one method is feasible, say why the other is unavailable.
7. Use bounded low/base/high scenarios with source-based or labeled assumed
   ranges. Vary each uncertain driver once (one-way sensitivity), state what was
   held fixed and identify the driver changing the decision most. Do not call
   these statistical confidence intervals or attach invented probabilities.

## Fillable output

Scope: [buyer, geography, period, currency/base year, denominator, cutoff]

| Layer | Population and exclusions | Formula with I/A IDs | Tool result + unit | Source coverage / limitation |
| --- | --- | --- | --- | --- |
| TAM top-down | [eligible universe] | [sourced formula] | [unknown until run] | [S IDs] |
| TAM bottom-up | [buyer count] | [count x annual spend] | [unknown until run] | [S/A IDs] |
| SAM | [serviceable constraints] | [nested filter] | [unknown until run] | [exclusions] |
| SOM | [horizon and capacity] | [reachable x conversion, capped by capacity] | [unknown until run] | [A IDs to test] |

| Driver | Low / base / high + units | Why bounded | Fixed inputs | Result range | Decision sensitivity |
| --- | --- | --- | --- | --- | --- |
| [I/A ID] | [unknown until supported] | [source or assumption] | [IDs] | [tool receipt] | [threshold crossed or unresolved] |

Close with reconciliation, contrary estimates, missing inputs, and the next
verification that could change the range. No market-size figure proves demand.
