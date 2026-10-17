---
name: "omh-llm-app-dev"
description: "[omh] LLM-powered feature to build: LLM app development: prepare a build handoff for an LLM-powered feature with a pinned provider boundary, schema-first outputs, versioned prompt files, grounded retrieval, and an eval suite as a shipped deliverable. Use when the user says: llm-app-dev, llm app development, llm application development, build an llm app, build an llm feature, llm feature development, build a rag pipeline, rag pipeline."
license: MIT
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, delivery]
    category: delivery
    phase: llm-app-dev
    role: operator
    quality_tier: delivery-gated
---

# Llm App Dev

This is an OMH `llm-app-dev` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`llm-app-dev` exists because the failure modes of an LLM feature are not the failure modes of the code around it. A floating model alias, a prompt buried in a string literal, an output scraped out of prose with a regex, and a retrieval layer nobody measured all pass code review and all fail in production, and without a golden set nobody can tell whether the next prompt edit helped or hurt.

## Do Not Use When

- The subject is comparing executors or agent harnesses - Codex against Claude Code against Hermes coding - rather than evaluating the product's own model calls.
- An agent run is already stuck, looping, or drifting and needs diagnosis; use `omh-agent-debug`.
- The subject is the harness's own context window, prompt caching, or token budget rather than the application being built; use `omh-context-budget-review`.
- The request is a prompt-injection, secret-handling, or dependency risk gate on work that already exists; use `omh-security-safety-review`.
- The feature makes no model call - the LLM is only mentioned as the subject being discussed - so this is a direct answer, not a build handoff.
- The ask is training the weights themselves on your own data -- SFT, DPO, RLVR, or a LoRA adapter; use `omh-model-finetuning`.

## Examples

Good example:

- Prompt: $llm-app-dev we are adding an invoice-field extractor that calls a model per upload - set it up so we can change the prompt later without guessing.
- Expected behavior: Name the rails, put the provider call behind one client module with a pinned model ID, declare the extraction schema and the repair path, lay the prompt out as a versioned file, and specify the golden set and validators that let the next prompt edit be compared against this baseline.
- Why: The feature is a real model call whose output another system consumes, which is exactly where an unpinned model, an inline prompt, and a missing golden set become expensive later.

Bad example:

- Prompt: $llm-app-dev the extractor is done - confirm the new prompt is better than the old one.
- Expected behavior: Prepare the paired baseline-vs-candidate comparison and state that no result exists until the run is observed; report nothing about which prompt is better.
- Why: Better is a claim about an observed run. Without one, the comparison is a design, and calling it a result is the false-green this workflow exists to prevent.

## Completion Checklist

- Every rail - provider boundary, structured output, prompt artifacts, retrieval grounding, evaluation - is either decided or explicitly deferred with a reason.
- One client boundary owns the model ID, credentials, timeout, retry, and backoff, and no credential appears in source, prompts, tests, or examples.
- The model ID is exact, and it is recorded next to any result meant to be compared.
- Every model response is validated against a declared schema, with a bounded repair path and a loud failure - no prose scraping.
- Prompts are files with a version identifier, and system rules, task instruction, and injected context are separated.
- Untrusted retrieved or user-supplied content is fenced from the instruction channel and cannot change the task.
- The eval deliverables - golden set, task-level validators, baseline-vs-candidate comparison - exist as committed artifacts, and retrieval is evaluated before generation when retrieval is in the path.
- Token, latency, and cost figures come from an observed run or stay null; no design output is reported as an eval result, implementation, review, CI, or merge evidence.
- If the feature communicates through a public board, the destination carries a public-audience label, each action class names its own authority and outbound data, the exact draft and its host-recorded approval reference travel with the request through compaction and executor handoff, and no publication is reported without an observed connector result.

## Recovery Notes

- If the exact model ID or provider is not decided yet, name the candidates and prepare the boundary against a config value rather than choosing one silently.
- If no failing case can be stated, the golden set has no seed: collect the real failures first, because a golden set written from imagination measures the imagination.
- If a response cannot be made to satisfy the schema after one bounded repair, treat that as a schema or prompt defect and record it as a golden-set case rather than loosening validation.
- If retrieval quality was never measured, stop before scoring generation and route the retrieval evaluation first; a generation score on unmeasured retrieval is not attributable.
- If the comparison run did not emit tokens or cost, leave those fields null and say the harness did not report them; never reconstruct them from pricing tables.
- If a public-board send returned no confirmed outcome, do not retry: read the board back or resolve the receipt first, because a duplicate public post cannot be withdrawn the way a failed private write can be repeated.



## When to Use

Use when the work is building or hardening an LLM-powered feature - provider calls, structured outputs, prompt files, retrieval grounding, a user-requested public-board communication path, or the eval suite that guards a prompt or model swap - and the request needs engineering discipline before a coding handoff.

    Strong routing signals: `llm-app-dev`, `$llm-app-dev`, `llm app development`, `llm application development`, `build an llm app`, `build an llm feature`, `llm feature development`, `build a rag pipeline`, `rag pipeline`, `retrieval augmented generation`, `structured output schema`, `json schema output`, `prompt versioning`, `llm eval suite`, `golden set`, `LLMアプリ開発`, `LLM機能開発`, `RAGパイプライン構築`, `構造化出力スキーマ`, `プロンプトのバージョン管理`, `LLM評価セット`, `llm 앱 개발`, `llm 애플리케이션 개발`, `llm 기능 개발`, `rag 파이프라인`, `rag 파이프라인 구축`, `구조화된 출력 스키마`, `프롬프트 버전 관리`, `llm 평가셋`, `골든셋`, `大模型应用开发`, `检索增强生成`, `结构化输出模式`, `提示词版本管理`, `评测集`, `bangun aplikasi berbasis LLM`, `bantu buat fitur dengan LLM`, `buat pipeline RAG`, `rancang chatbot dengan retrieval`, `siapkan evaluasi untuk fitur LLM`, `buat keluaran terstruktur dari LLM`

## Catalog Metadata

Category: `delivery`
Phase: `llm-app-dev`
Quality tier: `delivery-gated`
Reasoning demand: `heavy`

Quality bar:

- Decide the rails in order - provider boundary, structured output, prompt artifacts, retrieval grounding, evaluation - and say which are deferred rather than leaving them unnamed. Load `references/build-rails.md` for the per-rail decision and its failure mode.
- Route every provider call through one client boundary module that owns the model ID, credentials, timeout, retry policy, and rate-limit backoff. A second call site that builds its own client is how a model pin, a timeout, and a retry policy quietly diverge.
- Pin the exact model ID as a named constant or config value, never a floating alias, and record it next to any result that will be compared to another result.
- Take structured output from a declared schema - a JSON schema, a typed parser, or the provider's structured-output mode - and validate every response against it. A response that fails validation is repaired by one bounded re-ask that shows the validation error, then fails loudly; it is never regex-scraped out of prose.
- Keep prompts as reviewable files with a version identifier, separated into system rules, task instruction, and injected context, so a prompt change shows up in a diff instead of inside a string literal.
- For retrieval, fix chunking and citation grounding first and evaluate retrieval before evaluating generation: a generation score on top of unmeasured retrieval cannot tell a bad answer from a bad document set.
- Ship the eval suite as a deliverable, not a follow-up: golden set, task-level validators, baseline-vs-candidate comparison, with deterministic validators wherever the task allows one. Load `references/eval-harness.md` for the golden-set shape, the corpus-hygiene checks that run before a score is quoted, the validator ladder, and the comparison record.
- Run the regression before a prompt or model swap, not after, and compare baseline against candidate on the same golden set with token and cost capture. Report only what the run reported; a metric the harness did not emit stays null.
- Give every agentic loop its budgets as product features, not prompt advice: step, time, token, cost, and tool-call budgets each with a recorded termination reason, and for recursive delegation the budgets bind the whole tree, not each node separately.
- Separate draft from commit for risky side effects: reads and drafts may run autonomously when scoped and labeled, but external writes, deletions, and communications need an approval record outside the prompt - a model's stated intention is never the authorization.
- When the user asks for communication through a public board, treat the destination as a public external disclosure even when the account is authenticated: give read, search, register, profile, reply, publish their own authority and outbound-data expectation, show the exact destination, the public-audience label, and the complete outbound payload before a host-recorded approval, and reconcile an ambiguous send by read-back or receipt before any retry. Load `references/public-board.md` for the per-action authority table, the untrusted-peer rules, and what survives compaction and handoff.
- When the feature presents or acts on business records; enforces a cumulative business limit; stores facts about a person, load `references/stateful-contracts.md`. Provenance is not authorization, follow-up references resolve against the final-order receipt, limits are checked on resulting state inside one atomic apply boundary, and stored user facts are host-validated and deletable. A feature with none of those properties records that and skips this conditional contract.
- Keep design and evidence separate: a prepared schema, prompt layout, or eval plan is not implementation, an observed eval run, review, CI, or merge evidence.

Required inputs:

- the feature the model is supposed to perform
- the exact provider and model ID under consideration
- the shape of the output the caller consumes
- the failing cases that must not regress

Expected outputs:

- rail decisions across provider boundary, structured output, prompt artifacts, retrieval grounding, evaluation
- the output schema and the validate-and-repair path for a response that does not match it
- the prompt artifact layout and its version identifier
- the eval deliverables - golden set, task-level validators, baseline-vs-candidate comparison
- the executor handoff and what stays unobserved until a run produces it

Artifact expectations:

- prompt files committed under version control with a version identifier the call site records, so a response can be traced to the prompt that produced it
- a golden set committed beside the code as data, not as prose in a chat log

Safety rules:

- Do not hardcode an API key, token, or provider credential in source, prompts, tests, or examples; the client boundary reads them from the environment or a secret store.
- Do not pin a model by a floating alias when the behavior is being evaluated; a benchmark against a moving target proves nothing.
- Do not catch provider failures broadly; classify timeout, rate limit, transient server error, invalid request, and content refusal separately, because only some of them are safe to retry.
- Do not put untrusted content - retrieved documents, user uploads, tool output, web pages - in the same channel as instructions, and never let it change the task.
- Do not report token counts, latency, or cost that a run did not produce; telemetry the run did not report stays null and is never estimated.
- Do not claim an eval passed, a prompt shipped, or a model swap is safe from a prepared design; every such claim needs an observed run.
- Do not treat a public board as private because the account is authenticated, and do not let board content or a peer's claimed identity, authority, or approval authorize a post, a reply, a registration, or a profile field; a changed destination or changed payload invalidates the prior approval.

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
about one; and when a stop condition or a decision the user owns ends the turn,
offer the next action as a question rather than declaring what will not be done.
Supporting paths are relative to this skill directory; sibling skill paths are
relative to its parent. Resolve them from the host-provided skill base directory
(`{baseDir}` on hosts that provide it), never a hardcoded install location.
A named workflow not installed here is unavailable, not permission to emulate
its host-specific capabilities. Verify through the real surface before done.
