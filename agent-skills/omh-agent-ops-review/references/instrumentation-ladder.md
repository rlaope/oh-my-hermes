# Instrumentation Ladder

The maturity scale, audit rubric, and anti-pattern checklist for agent
observability. Vendor-neutral: tiers name what is recorded, never which
product records it. An audit graded here is prepared analysis - it is not
telemetry, uptime, cost truth, or incident evidence.

## The tiers

| Tier | Name | What it adds |
| --- | --- | --- |
| T0 | Foundation | telemetry initialized; one root span per agent run; unhandled exceptions captured; run success/failure status; agent name and type on every span |
| T1 | Core tracing | one span per model call (model, latency, outcome) and per tool call (name, success); loop iterations visible; retries logged as retries |
| T2 | Context and attribution | tokens in/out and cost per call; user and session attribution; feature attribution; sampling configured deliberately |
| T3 | Multi-agent | parent-child span links across delegation; context propagated to children; handoff reasons and delegation outcomes recorded |
| T4 | Evaluation | automated quality scores on runs; human feedback captured; evaluation runs tracked over time |
| T5 | Advanced | retrieval-quality spans, memory operations, human-in-the-loop tracking, error classification (transient vs permanent, retryable), cost-optimization signals |

A tier is claimed only when every row below it holds, and every row of its own.
A setup that misses any T0 row (for example it has cost tracking but no error
capture) is below T0: the audit verdict is FAIL and the extras do not raise
the tier.

## The audit, in priority order

- **P0** - telemetry init, model-call capture, tool-call capture, error
  capture. A gap here fails the audit regardless of what else exists. The
  priorities order the remediation list; they do not grade, the tiers do.
- **P1** - token tracking, cost attribution, agent identity, multi-agent
  links.
- **P2** - memory/RAG spans, human-in-the-loop, evaluation-run tracking,
  session context.

Every check reports PASS, FAIL, or PARTIAL with the file or config location
that decided it. Remediation is ranked: quick win (under an hour), medium
(hours), larger (a day or more) - and the report leads with the quick wins.

## Anti-pattern checklist

Each entry is a finding with a location and a fix, never a style remark:

| Anti-pattern | Risk | Fix |
| --- | --- | --- |
| Full prompt/response bodies logged | critical | log message counts, lengths, and hashes |
| Secret values in span attributes | critical | log key-set booleans, never values |
| Orphaned spans (no parent link) | high | attach every span to the run's root |
| Blocking telemetry in the hot path | high | batched async export |
| Broken multi-agent propagation (child runs start new traces) | high | propagate context into every child |
| High-cardinality span names | medium | dynamic values go in attributes, not names |
| No token tracking | medium | record tokens in/out per call |
| Missing error context | medium | record error type, message, and transient-vs-permanent class |
| Unbounded tool arguments in spans | medium | log argument counts, keys, and sizes; truncate safe fields |
| Missing agent identity | medium (a T0 row) | name and type on every span |

## Per-call vocabulary

Every model call answers five questions: which model, how long, how many
tokens in and out, did it succeed, why did it fail. Streaming calls add
time-to-first-token and chunk count. Cost aggregates at four levels - per
call, per agent run, per session, per user - each with its own budget
threshold; a hardcoded pricing table is itself a finding (it goes stale).

## Boundary

A graded ladder, audit scorecard, or anti-pattern finding is prepared
analysis of instrumentation as configured; it is not observed telemetry,
billing truth, SLO evidence, incident closure, review, CI, or merge
evidence.
