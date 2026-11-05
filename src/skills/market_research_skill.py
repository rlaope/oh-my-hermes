"""Original OMH market-research methodology and on-demand working templates.

This is authored guidance, not an imported framework or a research executor.
No figures, customer quotations, retrievals, or validations are supplied here.
"""
from __future__ import annotations

from .catalog_types import ExpertQuestion, ProcedureCheck, ProcedureBail, ProcedureStep, SkillDefinition, SkillExample

_INPUTS = (
    "decision and audience",
    "buyer segment and geography",
    "period currency units and source cutoff",
    "available evidence and source boundary",
    "research budget and stop condition",
)
_OUTPUTS = (
    "market scope and source ledger",
    "TAM SAM SOM model and sensitivity",
    "customer evidence and JTBD matrix",
    "comparable competitor and pricing profiles",
    "decision-ready market findings",
)

DEFINITION = SkillDefinition(
    "market-research",
    "Market sizing or customer/competitive analysis: investigate a scoped market with TAM/SAM/SOM sensitivity, attributed customer evidence, and comparable competitor/pricing profiles before a decision brief.",
    (
        "market-research", "market sizing", "tam sam som", "bottom up market sizing",
        "market size sensitivity", "customer evidence analysis", "jtbd evidence matrix",
        "competitor pricing profiles", "competitive pricing analysis",
    ),
    "Use when the task needs market-specific analysis of addressable demand, customer jobs and pains, or comparable competitor and pricing evidence, not merely a generic brief or source list.",
    category="research",
    phase="market-analysis",
    hermes_role="retained-cognition",
    delegation_boundary="retained-catalog-intent",
    handoff_policy=(
        "Keep scoping, source-backed analysis, calculations, and uncertainty reporting in Hermes. "
        "Use `research-brief` for the audience's final synthesis and `research-department` for recurring operations. "
        "Product investment, kill/pivot/persevere, and customer-validation gates remain owned by `product-discovery-validation`; "
        "market findings are not customer validation or permission to build."
    ),

    required_inputs=_INPUTS,
    expert_questions=tuple(
        ExpertQuestion(key, question, question)
        for key, question in zip(_INPUTS, (
            "Which decision must this inform, for which audience and decision owner?",
            "Which buyer versus user segment, geography, alternatives, and exclusions define the market?",
            "Which observation period, currency/base year, units/denominator, and source cutoff apply?",
            "Which evidence is supplied, which sources may be retrieved, and which access/privacy limits apply?",
            "What time/source/cost budget and stop condition bound the work?",
        ))
    ),
    expected_outputs=_OUTPUTS,
    artifact_expectations=("prepared market analysis with source IDs, assumptions, failed retrieval gaps, and tool calculation receipts when captured",),
    opening_steps=(
        "Confirm the decision, buyer/segment, geography, period, currency/base year, units/denominator, source cutoff, budget, and stop condition before retrieval. Mark missing inputs unknown; ask the one that changes the analysis first.",
        "Read `references/findings-template.md` to open the ledger, then load only the needed methods: `references/market-sizing.md`, `references/customer-evidence.md`, or `references/competitive-pricing.md`. Do not manufacture empty analysis lanes for an out-of-scope question.",
    ),
    procedure_checks=(
        ProcedureCheck("market_scope_check", ("decision", "segment", "geography", "period", "currency_base_year", "units_denominator", "source_cutoff", "budget", "stop_condition"),
                       "PASS only when scope is supplied or explicitly unknown; HOLD numeric estimates when a missing denominator or period makes them uninterpretable."),
        ProcedureCheck("market_source_check", ("source_id", "source_date", "retrieved_at", "coverage", "evidence_class", "claim_ids", "failed_retrieval", "contrary_evidence"),
                       "Require observed, vendor-asserted, or inferred per claim, not per document; preserve source dates and access failures, and do not count copied press coverage as independent evidence."),
        ProcedureCheck("market_size_check", ("input_refs", "assumptions", "formula_units", "tool_receipt", "tam", "sam", "som", "reconciliation", "sensitivity"),
                       "Use tools for calculations; enforce nested scope and consistent units. Unknown operands yield unknown results, not zeros; test bounded scenarios and reconcile top-down with bottom-up or explain why one is unavailable."),
        ProcedureCheck("market_customer_check", ("evidence_ids", "quote_ids", "segment", "sample_frame", "jtbd", "past_behavior", "bias", "contrary_evidence", "privacy"),
                       "Keep observed behavior separate from stated intent and analyst inference. Attribute quotations exactly or omit them; sample counts are not population prevalence or willingness-to-pay evidence."),
        ProcedureCheck("market_comparability_check", ("competitor", "source_ids", "as_of", "coverage", "segment", "packaging", "normalized_price", "limits", "evidence_class"),
                       "Require comparable buyer/use-case and billing units before ranking. A missing feature or price is not observed, never absent or free; vendor claims are not verified outcomes."),
        ProcedureCheck("market_findings_check", ("finding_ids", "source_refs", "assumption_refs", "contrary_evidence", "confidence_limits", "decision_implications", "verification_needs", "stop_reason"),
                       "Every finding must link evidence or explicit assumptions, state uncertainty and a falsifier, and name a next verification owner without making the product investment decision."),
    ),
    procedure_steps=(
        ProcedureStep("frame_market", "analysis", _INPUTS, (_OUTPUTS[0],), ("market_scope_check",),
                      "Record the bounded market contract and exclusions; choose only the relevant method references and precommit what evidence would change the decision."),
        ProcedureStep("register_market_evidence", "analysis", (_INPUTS[2], _INPUTS[3], _INPUTS[4]), (_OUTPUTS[0],), ("market_source_check",),
                      "Register sources at retrieval with IDs, dates, cutoff coverage, access failures and claim classes; seek contrary evidence within the budget, preserving gaps rather than filling them from recall."),
        ProcedureStep("size_addressable_market", "production", (_INPUTS[1], _INPUTS[2], _INPUTS[3]), (_OUTPUTS[1],), ("market_size_check",),
                      "When in scope, use references/market-sizing.md to construct sourced TAM/SAM/SOM boundaries, calculate top-down and bottom-up scenarios with tools, reconcile disagreement, and report sensitivity; otherwise mark this lane not requested.",
            on_fail=ProcedureBail(
                still_stands=('market scope and source ledger',),
                downgrade_to='unresolved',
                handback='Return the market scope and source ledger with an unresolved TAM SAM SOM model and sensitivity, preserving unknown operands, unit gaps, calculation receipts, and unreconciled ranges.',
            ),
        ),
        ProcedureStep("analyze_customer_evidence", "analysis", (_INPUTS[1], _INPUTS[3]), (_OUTPUTS[2],), ("market_customer_check",),
                      "When in scope, use references/customer-evidence.md to code attributed jobs, pains, triggers, alternatives and behavior; retain sample frame, selection bias and contrary cases. An interview plan is not an interview."),
        ProcedureStep("compare_competitors_and_pricing", "analysis", (_INPUTS[1], _INPUTS[2], _INPUTS[3]), (_OUTPUTS[3],), ("market_comparability_check",),
                      "When in scope, use references/competitive-pricing.md to build dated comparable profiles and normalize price/packaging with tool calculations; separate observation, assertion and inference and keep unavailable metrics unavailable."),
        ProcedureStep("deliver_market_findings", "validation", _INPUTS, (_OUTPUTS[4],), ("market_source_check", "market_findings_check"),
                      "Use references/findings-template.md to deliver findings, calculations, assumptions, contrary evidence and unresolved retrieval gaps; record optional lanes as not requested, stop at the agreed budget, and hand decision implications to the decision owner.",
            on_fail=ProcedureBail(
                still_stands=('market scope and source ledger', 'TAM SAM SOM model and sensitivity', 'customer evidence and JTBD matrix', 'comparable competitor and pricing profiles'),
                downgrade_to='tentative',
                handback='Return tentative decision-ready market findings with the source ledger, calculation receipts, assumptions, contrary evidence, and unresolved retrieval gaps; name each next verification owner.',
            ),
        ),
    ),
    safety_rules=(
        "Never invent figures or quotes, customer participants, market shares, traffic/revenue estimates, source IDs, or tool results. Label unsupported inputs unknown rather than borrowing a generic industry ratio.",
        "Outreach, participant recruitment, payments, and scheduling each require separate explicit approval; research approval is not permission to contact people, buy reports, run surveys, or create jobs.",
        "Keep contact details, raw recordings, private transcripts, and sensitive customer data outside durable artifacts; use consented bounded summaries and pseudonymous IDs with access-controlled source pointers.",
        "A prepared analysis is not retrieval, interviews, willingness to pay, customer validation, product-market fit, or an approved investment decision. No external tool, paid dataset, or MCP integration is mandatory.",
    ),
    quality_tier="source-gated",
    quality_bar=(
        "Require source IDs, dates/cutoffs, observed/vendor-asserted/inferred labels, assumptions and units on material claims.",
        "Keep failed retrieval, contrary evidence, sample bias, scope mismatch and confidence limits visible; a citation alone does not verify a claim.",
        "Load method and output templates on demand; calculations need real tool receipts, and absent evidence cannot be synthesized into certainty.",
    ),
    why_this_exists="`market-research` turns a broad market question into bounded sizing, customer evidence, and comparable competitive analysis that a decision owner can inspect without mistaking secondary research for validation.",
    do_not_use_when=(
        "A kill, pivot, or persevere gate before a PRD is needed; use `product-discovery-validation`.",
        "A recurring source inbox with Scout, Analyst, and Briefer operations is needed; use `research-department`.",
        "Supplied tickets need clustering and investigation priorities; use `feedback-triage`.",
        "A supplied spreadsheet needs cleaning, descriptive statistics, or anomaly analysis; use `data-analysis`.",
        "A supplied academic PDF needs section-by-section explanation; use `paper-learning`.",
        "A general business question needs an audience-ready synthesis rather than a domain model; use `research-brief`.",
    ),
    good_example=SkillExample(
        "Estimate TAM SAM SOM for US independent dental clinics with sourced counts and sensitivity, not a guessed capture percentage.",
        "Fix scope and units, build a source/assumption ledger, calculate addressable scenarios with tools, and expose confidence limits and missing inputs.",
        "The task needs an addressable-market model, not only a narrative brief.",
    ),
    bad_example=SkillExample(
        "Approve our startup for investment because a large total market proves demand.",
        "Keep the size estimate separate from a discovery decision; require target-customer evidence and the decision owner's gate.",
        "Market scale is not customer validation or permission to build.",
    ),
    final_checklist=(
        "The scope, units, source cutoff and stop reason are explicit, and every material finding links sources or labeled assumptions.",
        "Requested methods include source coverage, contrary evidence and confidence limits; unrequested lanes are marked not requested, not completed.",
        "Calculation receipts, unresolved retrieval gaps and customer sample limitations are attached; unknowns remain unknown.",
        "Decision implications name verification needs and an owner, never an automatic discovery, outreach, payment, scheduling or coding action.",
    ),
    recovery_notes=(
        "If retrieval fails, record the source ID, attempted date, failure and uncovered period; seek an allowed alternative once within budget or leave the finding unresolved.",
        "If sources disagree, compare definitions, geography, units and dates before choosing; preserve both ranges when they cannot be reconciled.",
        "If customer evidence is absent, prepare a consent-aware evidence request and leave the JTBD hypothesis unvalidated, never generate participant answers.",
    ),
    progressive_disclosure=True,
    situations=(
        "size a market with sourced assumptions", "addressable demand model with bounded assumptions",
        "customer jobs pains and purchase triggers", "rival plans and per-seat prices side by side",
        "quantify demand and synthesize customer signals before a business decision",
    ),
)

REFERENCE_CONTENT = {
    "market-sizing.md": """# Market sizing method and worksheet

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
""",
    "customer-evidence.md": """# Customer evidence, JTBD and sample worksheet

1. Identify whose evidence is present: buyer/user role, segment, geography,
   sample frame, inclusion/exclusion criteria, recruitment channel, dates and
   consent. Record available sample count and missingness; do not infer a
   representative sample from a convenient set of reviews or stakeholder notes.
2. Assign evidence IDs `E1` and source IDs `S1`. A quotation `Q1` must point to
   exact retrieved or consented supplied wording and its location; a paraphrase
   must not use quotation marks. Never fabricate a quote or a participant.
3. Code a JTBD as circumstance -> desired progress -> current alternative.
   Extract pains, purchase triggers, switching costs, decision participants and
   observed commitments. Prefer past behavior over future intention. Keep stated
   intent, observed behavior and analyst inference in different cells.
4. Seek contrary cases and non-buyers within scope. Record selection bias,
   survivorship, channel bias, sponsor incentives, recall effects and segment
   mismatch. Count unique participants rather than repeated comments; if identity
   is unknown, do not claim deduplication or population prevalence.
5. Synthesize only supported patterns with E/Q IDs, denominator and limits.
   Reviews do not establish willingness to pay. A modeled persona is a hypothesis,
   not a participant; an interview guide is not a completed interview.

## Fillable output

| Evidence / source / quote IDs | Segment + role | Circumstance / JTBD | Pain + current alternative | Trigger / past behavior | Observed / stated / inferred | Contrary evidence | Sample limitation |
| --- | --- | --- | --- | --- | --- | --- | --- |
| [E1 / S1 / Q1 or no quote] | [known or unknown] | [supported paraphrase] | [evidence] | [evidence or unknown] | [class] | [IDs or sought/not found within coverage] | [selection bias] |

Sample frame: [population sought, channel reached, count, dates, exclusions].
Confidence: [coverage and disagreement, not a score invented from sample size].
Next evidence need: [falsifier, owner, consent/privacy constraint, bounded budget].

Outreach, interviews, surveys, recruitment and incentives require their own
explicit approval. Keep PII, contacts, raw transcripts and recordings outside
shared artifacts; use pseudonymous IDs and access-controlled source pointers.
A summary does not override consent or grant reuse rights.
""",
    "competitive-pricing.md": """# Comparable competitor and pricing profiles

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
""",
    "findings-template.md": """# Decision-ready market findings

This is a fillable working template, not an observed research report. Leave
unavailable values unknown; remove unrequested method sections explicitly.

## Scope and stop rule
Decision / audience / owner: [named decision, not automatic approval]
Buyer versus user / segment / geography / exclusions: [scope]
Period / currency + base year / units + denominator: [scope]
Research budget / source cutoff / actual stop reason: [bounds and gaps]
Methods requested: [sizing, customer evidence, competitors/pricing; others not requested]

## Source ledger (open before first retrieval)
| Source ID | Title / publisher + safe pointer | Published / effective | Retrieved at | Period covered / source cutoff | Claim IDs + evidence class | Access / failed retrieval gap |
| --- | --- | --- | --- | --- | --- | --- |
| [S1] | [actual source or candidate, marked unread] | [date or unknown] | [observed timestamp or not retrieved] | [window] | [observed / vendor-asserted / inferred] | [read scope or failed retrieval reason] |

Do not reuse a source ID for another source. Preserve failed attempts, uncovered
windows, inaccessible paywalls and alternative-source limitations; no retrieval
means no evidence. A date or citation does not prove the claim true. Keep raw
customer data out of this ledger. No invented figures or quotes may fill a gap.

## Assumptions and calculation receipts
| Assumption / input ID | Value or unknown + unit | Source IDs or rationale | Applicability / bounds | Formula + actual tool receipt | Validation owner / need |
| --- | --- | --- | --- | --- | --- |
| [A1 / I1] | [unknown until supported] | [S IDs or explicit assumption] | [range, no default ratios] | [expression + result or not run] | [owner] |

Attach only requested method worksheets. Preserve differing definitions rather
than averaging incompatible estimates, and label scenario ranges, not confidence
intervals. If no calculation ran, say so.

## Findings and decision implications
| Finding ID | Finding + observed / vendor-asserted / inferred | Source / assumption IDs | Contrary evidence | confidence limits | Decision implication + falsifier | Next verification / owner |
| --- | --- | --- | --- | --- | --- | --- |
| [F1] | [claim or unresolved question] | [S/E/Q/A IDs] | [counterevidence or bounded search gap] | [sample/coverage/time limits] | [what could change the decision] | [evidence task, not authorized outreach] |

Lead the human-readable brief with what the evidence changes, not a source dump.
State unresolved conflicts, failed retrieval and verification needs beside the
recommendation. Stop at the agreed budget with an inconclusive result if needed.
Use `research-brief` for audience synthesis. Investment validation remains with
`product-discovery-validation`; desk research cannot pass its customer gates.
""",
}
