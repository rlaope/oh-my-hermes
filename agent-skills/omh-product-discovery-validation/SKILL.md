---
name: "omh-product-discovery-validation"
description: "[omh] Unvalidated early product idea: test whether a customer problem, segment, and business hypothesis deserve product investment, ending in kill, pivot, persevere, or inconclusive before any PRD. Use when the user says: product-discovery-validation, product discovery validation, product discovery, customer discovery, customer discovery plan, zero to one validation, validate the problem before building, problem solution interview."
license: MIT
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, planning]
    category: planning
    phase: product-discovery-validation
    role: planner
    quality_tier: decision-gated
---

# Product Discovery Validation

This is an OMH `omh-product-discovery-validation` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`omh-product-discovery-validation` gives an early idea a bounded, evidence-typed path to a kill, pivot, persevere, or inconclusive decision so `omh-product-brief` consumes validated inputs instead of judging raw discovery itself.

## Do Not Use When

- The user needs market, competitor, pricing, or customer research on named sources without a discovery decision to make; use `omh-research-brief`.
- The user is clarifying their own request, requirements, or preferences rather than testing a customer problem with external people; use `ulw-interview`.
- The user needs a company or product strategy decision across existing options with evidence already in hand; use `omh-decide`.
- The problem, segment, and evidence are already validated and accepted and the user wants a PRD or prioritization; use `omh-product-brief`.
- An accepted product brief and plan exist and the user wants implementation, QA, and release gates; use `omh-idea-to-deploy`.
- The user has one falsifiable technical or empirical question a disposable prototype can answer; use `omh-decision-prototype`.

## Examples

Good example:

- Prompt: I think freelance designers struggle to chase late invoices. Before we write a PRD, help me test whether this is worth building.
- Expected behavior: Frame the decision and kill criteria, classify the existing evidence, plan past-behavior customer interviews, rank the riskiest assumptions with precommitted tests, and stop at an explicit kill, pivot, persevere, or inconclusive receipt.
- Why: The request is a pre-PRD discovery decision about a customer problem and segment, not research on named sources, requester clarification, or a PRD.

Bad example:

- Prompt: Write the PRD for our invoice-chasing feature; the interviews already confirmed the problem.
- Expected behavior: Route to `omh-product-brief` and ask for the accepted discovery receipt or evidence rather than rerunning discovery.
- Why: Validated, accepted evidence with a PRD request belongs to the PRD owner, not to discovery.

## Completion Checklist

- The problem gate state is recorded as validated, refuted, or inconclusive with the external-human or behavioral-data refs that decided it, all observed in the framed target segment.
- The target segment is explicit enough to recruit or tied to observed behavioral data before any solution, PRD, prototype, or coding output leaves this workflow.
- Every assumption test in the portfolio carries its precommitted success, failure, inconclusive, segment, deadline, cost, owner, and evidence re-entry fields.
- The receipt names kill, pivot, persevere, or inconclusive, preserves rejected paths, and routes to `omh-product-brief` only from an accepted persevere.
- Every artifact is reported as prepared; interviews, tests, and prototypes stay not_observed until re-entered evidence exists.

## Recovery Notes

- If external-human or behavioral-data evidence is absent, hold the problem gate at inconclusive and hand the customer discovery plan to a human owner instead of filling the gap with personas.
- If a test passes its deadline or budget without meeting a precommitted condition, record inconclusive with the residual risk and let the decision owner choose a new budget or a kill.
- If the target segment is unknown, synthetic-only, or non-recruitable, keep the discovery frame and customer discovery plan and report defining a recruitable or behaviorally observed audience as the next evidence task.
- If a pivot changes the problem or segment, open a new decision frame and carry the falsified hypotheses forward as rejected paths.



## When to Use

Use when a founder or product owner brings an early idea and needs the problem, segment, value proposition, and business hypothesis framed, evidence-typed, and tested to an explicit discovery decision before a PRD, prototype, or delivery plan exists.

    Strong routing signals: `product-discovery-validation`, `product discovery validation`, `product discovery`, `customer discovery`, `customer discovery plan`, `zero to one validation`, `validate the problem before building`, `problem solution interview`, `customer interview guide`, `riskiest assumption test`, `assumption test portfolio`, `kill pivot persevere`, `kill or pivot decision`, `willingness to pay test`, `business hypothesis validation`, `is this idea worth building`, `고객 발견 검증`, `가정 검증 테스트`, `킬 피벗 지속 결정`

## Catalog Metadata

Category: `planning`
Phase: `product-discovery-validation`
Quality tier: `decision-gated`
Reasoning demand: `standard`

Quality bar:

- Separate the decision frame, typed evidence, customer re-entry plan, ranked assumptions, and the receipt so each can be reviewed alone.
- Keep every kill, pivot, persevere, or inconclusive claim tied to precommitted criteria and observed evidence.

Required inputs:

- problem hypothesis
- target segment
- known evidence and current alternatives
- decision owner
- learning budget and deadline
- success, failure, and stop criteria

Expert clarification questions:
- `problem hypothesis`
  - English: Which customer problem or opportunity do you believe exists, for whom, and what would you expect to observe if it were false?
  - Korean: 어떤 고객 문제 또는 기회가 존재한다고 보시며, 누구에게 해당하고, 그 가설이 틀렸다면 무엇이 관찰될 것으로 예상하시나요?

Expected outputs:

- discovery_decision_frame/v1
- discovery_evidence_ledger/v1
- customer_discovery_plan/v1
- assumption_test_portfolio/v1
- discovery_decision_receipt/v1
- initial_gtm_hypothesis/v1

Artifact expectations:

- prepared discovery decision frame, evidence ledger, customer discovery plan, assumption test portfolio, decision receipt, and GTM hypothesis when a wrapper captures them

Safety rules:

- Do not recruit or contact participants, record interviews, run surveys, scrape communities, buy ads, launch fake doors, accept payments, build a prototype, write a PRD, write code, or deploy anything from this workflow.
- Synthetic personas, model-generated interview answers, secondary summaries, prototypes without representative-user observation, and unsupported market-size figures cannot satisfy a customer-validation gate.
- Interview praise, stated purchase intent, a waitlist signup, a finished prototype, or one passed experiment is not product-market fit; state what each signal can and cannot establish.
- Founder-market fit and strategic preference may inform the decision but never substitute for target-customer evidence.
- An unknown, synthetic-only, or non-recruitable target segment blocks a solution, PRD, prototype-as-validation, or coding handoff; discovery framing, the customer discovery plan, and evidence work continue while it does.

Procedure: load `references/procedure.md`.

## Runtime Evidence

Use the current host's own tools and subagent/task mechanism when available;
otherwise run the same lanes sequentially or name the unavailable capability.
A prepared plan, handoff, checklist, or skill installation is not execution,
review, CI, merge-readiness, or merge evidence. Record actual tool results, or
`not_observed` / `not_available`, in the record; never invent dispatch or host
accounting.
Treat supplied context as advisory, not proof of hidden memory reads or writes.
State scope, constraints, verification, and the stop condition before work.
Reply in the user's own words and the host's own voice: the host's persona owns
reply language, tone, speech level, and sentence endings, progress updates
included (where it sets no language, use the one the user wrote in), and OMH
shapes structure and content only; OMH's record terms
(surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in
records and tool calls, never in the sentence the user reads unless they ask
about one; and when a real unresolved user decision or a useful briefing discussion
remains, offer one specific, content-linked question. Completed work needs no question;
omit unrelated non-action footers and generic offers to continue.
Supporting paths are relative to this skill directory; sibling skill paths are
relative to its parent. Resolve them from the host-provided skill base directory
(`{baseDir}` on hosts that provide it), never a hardcoded install location.
A named workflow not installed here is unavailable, not permission to emulate
its host-specific capabilities. Verify through the real surface before done.
