# Comparable competitor and pricing profiles

1. Define the buyer, job, geography and comparable alternatives, including
   workarounds and doing nothing. State the inclusion rule before selecting
   competitors so the comparison cannot silently select only weak rivals.
2. For each profile record source IDs, publication/effective date, retrieval
   timestamp, source cutoff and coverage. `S1` can establish an observed listed
   price; performance text on that page is vendor-asserted, not a verified
   outcome. An analyst conclusion is inferred and names the premises.
3. Use the same fields for every competitor: buyer/use case, product boundary,
   capabilities, distribution, packaging, limits, evidence and gaps. A feature
   is absent only with explicit evidence; missing coverage means not observed.
   Do not fabricate traffic, revenue, market share, adoption or retention.
4. Normalize prices to the same currency, billing period, seat/account/usage
   unit and geography using tools. Preserve original price and formula receipt;
   state annual commitment, minimum seats, included usage, overages, setup fee,
   tax inclusion/exclusion, discount eligibility and effective date. Model the
   same workload before comparing totals. Do not compare per-seat and per-call
   prices without a stated workload; free tier is not free total cost.
5. Leave custom/negotiated price unknown unless observed in an authorized quote.
   Do not infer willingness to pay from a published price. Record differences
   that defeat comparability instead of forcing a ranked table.

## Fillable output

| Alternative | Buyer / job | Source IDs + as-of / retrieved | Observed facts | Vendor-asserted claims | Inferred position + premise IDs | Coverage / not observed |
| --- | --- | --- | --- | --- | --- | --- |
| [name] | [comparable boundary] | [S1, dates] | [supported facts] | [unverified outcomes] | [bounded inference] | [gaps] |

| Alternative / package | Original price + currency | billing period / commitment | Unit + included workload | Minimum / overage / tax / fees | Normalized scenario + tool receipt | Source / effective date / limits |
| --- | --- | --- | --- | --- | --- | --- |
| [name / tier] | [observed or unknown] | [terms] | [unit] | [conditions] | [same scenario or not comparable] | [S IDs] |

Close with comparable differences, counterexamples, retrieval failures and what
must be verified before a pricing decision. Profiles are dated snapshots, not
permanent product truths or evidence of a customer's buying decision.
