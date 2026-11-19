## Why This Exists

`research` exists to make the host a careful research engine: it routes research demands to source-backed evidence gathering - from live web citations to studied reference implementations - verifies contested claims, and distills decision-grounding output so planning starts from evidence instead of guesses.

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

## When to Use

Use for research before planning, deciding, or handoff - from current web evidence and citations to exhaustive grounding with studied reference implementations and verified contested claims.

    Strong routing signals: `research plan`, `literature review`, `research literature`, `review recent papers`, `deep research`, `deep-research`, `exhaustive research`, `saturation research`, `pre-spec research`, `research before spec`, `research before planning`, `reference implementation`, `reference implementations`, `reference implementation study`, `prior art`, `prior art research`, `study existing implementations`, `comparable implementations`, `compare open source implementations`, `decision-grounding research`, `autoresearch-goal`, `research goal`, `durable research`, `critic research`, `ディープリサーチ`, `深く調査`, `出典付きで調査`, `OSS実装を調査`, `조사`, `근거`, `고객 피드백`, `문헌 검토`, `논문들 검토`, `딥리서치`, `딥 리서치`, `심층 리서치`, `레퍼런스 구현`, `오픈소스 깊게 참고`, `сделай ресерч`, `глубокий ресерч`, `дип ресерч`, `огромный ресерч`, `проведи исследование`, `ресерч перед решением`, `сделать ресерч`, `нужен ресерч`, `большой ресерч`, `ресерча`, `сделай огромный ресерч`, `поищи и сделай ресерч`, `глубокое исследование`, `深度调研`, `深入调研`, `带出处的调研`, `调研开源实现`, `lakukan riset mendalam`, `teliti implementasi referensi open source`, `buat tinjauan literatur`, `bandingkan implementasi OSS sebelum menyusun spesifikasi`, `bantu riset teknis secara menyeluruh`, `verifikasi klaim teknis dari berbagai sumber`, `tiến hành nghiên cứu chuyên sâu`, `nghiên cứu các triển khai mã nguồn mở tham khảo`, `lập tổng quan tài liệu`, `so sánh các triển khai OSS trước khi xây dựng đặc tả`, `giúp nghiên cứu kỹ thuật toàn diện`, `kiểm chứng các tuyên bố kỹ thuật từ nhiều nguồn`

Required inputs:

- research question
- output audience - a human reader or a coding agent - asked before retrieval and never inferred
- output format when the reader is human - markdown, a print-ready page, or both
- output language when the reader is human - declared, never inferred from the request
- target user/task if usability matters
- usability/quality dimension if applicable
- source boundaries
- candidate reference implementations or repos when relevant
- declared depth or wave budget when exhaustive grounding is requested - never inferred from phrasing
- freshness, jurisdiction, or version constraints
- requested as-of date or interval when the question is point-in-time

Artifact expectations:

- research notes with source URLs, retrieval dates, source-quality notes, and per-reference mechanism, tradeoff, license, and pinned-ref notes when the wrapper captures them
