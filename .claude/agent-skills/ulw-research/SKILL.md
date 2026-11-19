---
name: "ulw-research"
description: "[omh] Deep dive before a decision."
license: MIT
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, research]
    category: research
    phase: decision-grounding
    role: researcher
    quality_tier: source-gated
---

# Research

This is an OMH `research` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`research` exists to make the host a careful research engine: it routes research demands to source-backed evidence gathering - from live web citations to studied reference implementations - verifies contested claims, and distills decision-grounding output so planning starts from evidence instead of guesses.

## First Steps

- When Hermes' bundled `grounded-citations` skill is available, set the citation ledger up before the first retrieval: choose one run-private file, have the parent reset it once (`sources.py --ledger <path> reset`), and declare parent-only writes in every lane brief. No lane resets it. Discover the current search/read tools and authorized scope, then follow `references/search-method.md`: plan -> actual host search/read -> merge -> assess -> bounded retry. Use `omh_search` only when available; otherwise report the skill-only fallback. Keep direct file lookups direct.

## Do Not Use When

- The user asks for a full plan-to-PR delivery cycle; use `ulw-work` (its `delivery_boundary` capability) or a planning workflow after research instead.
- The request is purely local repo inspection with no external, current, citation, or source-comparison need.
- The study target is this repository itself rather than external references; use `omh-codebase-onboarding`.
- The user needs coding execution, review, CI, or merge evidence rather than research synthesis.
- The requested output is a typed candidate list or acquisition status without factual synthesis; use `omh-source-finder`.
- The user needs a market, customer, or pricing decision brief with evidence-versus-inference treatment; use `omh-research-brief`.
- The user asks for recurring monitoring, a source inbox, or Scout/Analyst/Briefer operations.
- One cited retrieval round settles the question and no reference implementation needs reading; use `omh-web-research`.

## Examples

Good example:

- Prompt: 딥리서치로 다른 오픈소스 구현들을 깊게 보고 스펙 잡기 전에 근거를 만들어줘.
- Expected behavior: Run the Hermes research lane at depth: decompose axes, study the most relevant reference implementations with pinned refs, verify contested claims, then distill a decision-grounding dossier for the planning step.
- Why: The user explicitly asked for deep pre-spec grounding built on other open-source implementations.

Bad example:

- Prompt: 이 레포 코드 구조만 파악해줘.
- Expected behavior: Route to `omh-codebase-onboarding` because the study target is this repository, not external sources or reference implementations.
- Why: Local repo orientation needs no external evidence gathering or claim verification.

## Completion Checklist

- The research question, source boundaries, recency assumptions, and confidence level are named.
- Observed sources, inference, synthesis, and unresolved retrieval gaps are separated.
- Follow-up planning or handoff uses the research summary without calling it execution evidence.
- When a human briefing was written, the citation check is reported from an observed ledger verify run that cited at least one source, or as `not_observed`; it never stands in for the contested-claim gate.

## Recovery Notes

- If a source fails with HTTP 403, HTTP 429, a paywall, or a WAF or bot wall, use the host's blocked-page recovery capability once for that source when it offers one and never retry the same URL in a loop; cite an archive or cached copy it returns as a dated historical capture, never as the live page. If no such capability exists, recovery fails, the retrieval budget is spent, or the source needs a login or payment, name the retrieval gap with that reason. Record each blocked source as one `research_source_recovery/v1`.
- If web or repository access is unavailable, name the retrieval gap and use only observed local context instead of inventing findings.
- If no archive access exists or the capture provider's paid authority is exhausted, record a temporal retrieval gap with no network action and keep the as-of claim in the annex; never substitute the current page for it.
- If the evidence stays thin or contested, lower the stated confidence and keep the unresolved claims in the annex rather than flattening them.
- If leads keep expanding past the declared budget, stop, record open leads in the dossier, and ask whether to extend the budget.
- If enough evidence already exists and the real request is planning, hand off to `ulw-plan` with the recorded dossier.
- If the audience answer arrives after retrieval started, keep the evidence and re-render rather than re-running: the dossier feeds both branches.



## When to Use

Use for research before planning, deciding, or handoff - from current web evidence and citations to exhaustive grounding with studied reference implementations and verified contested claims.

    Strong routing signals: `research plan`, `literature review`, `research literature`, `review recent papers`, `deep research`, `deep-research`, `exhaustive research`, `saturation research`, `pre-spec research`, `research before spec`, `research before planning`, `reference implementation`, `reference implementations`, `reference implementation study`, `prior art`, `prior art research`, `study existing implementations`, `comparable implementations`, `compare open source implementations`, `decision-grounding research`, `autoresearch-goal`, `research goal`, `durable research`, `critic research`, `ディープリサーチ`, `深く調査`, `出典付きで調査`, `OSS実装を調査`, `조사`, `근거`, `고객 피드백`, `문헌 검토`, `논문들 검토`, `딥리서치`, `딥 리서치`, `심층 리서치`, `레퍼런스 구현`, `오픈소스 깊게 참고`, `сделай ресерч`, `глубокий ресерч`, `дип ресерч`, `огромный ресерч`, `проведи исследование`, `ресерч перед решением`, `сделать ресерч`, `нужен ресерч`, `большой ресерч`, `ресерча`, `сделай огромный ресерч`, `поищи и сделай ресерч`, `глубокое исследование`, `深度调研`, `深入调研`, `带出处的调研`, `调研开源实现`, `lakukan riset mendalam`, `teliti implementasi referensi open source`, `buat tinjauan literatur`, `bandingkan implementasi OSS sebelum menyusun spesifikasi`, `bantu riset teknis secara menyeluruh`, `verifikasi klaim teknis dari berbagai sumber`, `tiến hành nghiên cứu chuyên sâu`, `nghiên cứu các triển khai mã nguồn mở tham khảo`, `lập tổng quan tài liệu`, `so sánh các triển khai OSS trước khi xây dựng đặc tả`, `giúp nghiên cứu kỹ thuật toàn diện`, `kiểm chứng các tuyên bố kỹ thuật từ nhiều nguồn`

## Catalog Metadata

Read `references/details.md` before you act: it holds this skill's quality bar and catalog metadata, kept out of this file so the whole of it fits in one read on every host.

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
