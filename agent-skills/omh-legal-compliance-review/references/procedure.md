# legal-compliance-review Specialist Procedure

Expert clarification questions:
- `jurisdiction`
  - English: Which parties, actor or data roles, operative facts, governing law and forum, and separately applicable regulatory jurisdictions are supplied?
  - Korean: 어떤 당사자, 행위자 또는 데이터 역할, 주요 사실, 준거법과 관할, 별도 적용 규제 관할권이 제공되었나요?
- `document or process version`
  - English: Which instrument type, complete document set and precedence, version, execution/effective date, amendments, and as-of date are in scope?
  - Korean: 어떤 문서 유형, 전체 문서 세트와 우선순위, 버전, 체결일과 효력일, 개정본, 기준일이 범위에 포함되나요?
- `supplied authority`
  - English: Which supplied authority identifiers, issuers, versions, effective status, exact pinpoints, hierarchy, and verification state may be used?
  - Korean: 사용 가능한 제공 근거의 식별자, 발행기관, 버전, 효력 상태, 정확한 인용 위치, 위계, 검증 상태는 무엇인가요?
- `review objective`
  - English: Which decision, risk tolerance, approval owner, deadline, and mandatory counsel questions should the review support?
  - Korean: 이 검토가 지원할 의사결정, 위험 허용 범위, 승인 책임자, 기한, 필수 법률 자문 질문은 무엇인가요?

## Procedure

Declared checks:
- `legal_scope_facts_instruments_check`
  - Required result fields: `actors_roles`, `operative_facts`, `instrument_set`, `order_of_precedence`, `governing_law_forum`, `regulatory_jurisdictions`, `execution_effective_as_of_dates`, `assumptions_blockers`
  - Criterion: Require material facts and roles, complete instruments and precedence, distinct contractual and regulatory jurisdictions, and temporal scope; never infer missing values.
- `legal_authority_citation_check`
  - Required result fields: `source_type`, `source_identifier`, `source_version`, `effective_status`, `pinpoint`, `operative_text_summary`, `verification_status`
  - Criterion: Each authority-dependent proposition must trace to supplied or observed authority and an exact locator and status; user summaries and inferences stay unverified.
- `legal_issue_matrix_check`
  - Required result fields: `applicability_facts`, `obligation_position`, `definitions_dependencies`, `exceptions_carveouts_conflicts`, `evidence_status`, `risk_uncertainty`, `action_owner`, `recommended_disposition`, `counsel_question`, `issue_family_applicability`
  - Criterion: Map facts to operative text, dependencies, exceptions and conflicts; when triggered cover warranty, disclaimer, indemnity and liability interactions or privacy roles, basis, transfers, security, breach, retention, rights and DPIA, marking other families not applicable.
- `legal_counsel_hold_check`
  - Required result fields: `trigger_ids`, `impact`, `likelihood_applicability`, `urgency`, `evidence_confidence`, `reversibility`, `hold_status`, `counsel_owner`
  - Criterion: Mandatory HOLD triggers include uncertain or conflicting authority, missing jurisdiction or dates, enforceability or privilege, material or uncapped liability or indemnity, regulatory deadlines, and sensitive, high-risk or cross-border privacy or DPIA uncertainty.
- `legal_negotiation_preparation_check`
  - Required result fields: `playbook_position`, `gap`, `proposed_language`, `fallback_position`, `walk_away_trigger`, `concession_order`, `counsel_hold_state`
  - Criterion: Every proposed clause traces to a cited playbook position and carries its fallback and walk-away; a row whose position cannot be cited becomes a counsel question, an open hold blocks its row, and the concession order states which rows are linked.
- `legal_final_determination_guard`
  - Required result fields: `invented_authority_status`, `stale_authority_status`, `unresolved_triggers`, `disposition`
  - Criterion: Fail closed on absent, fabricated, stale, superseded or unverified authority; invent no citation, holding, requirement or compliance conclusion and issue no final determination while a hold remains open.

### `legal_scope_facts_instruments` (analysis)

Record actors, roles, facts, instrument set and precedence, governing law, forum, regulatory reach, dates, objective, and every missing assumption or blocker.

- Input refs: `jurisdiction`, `document or process version`, `review objective`
- Output refs: `legal_scope_authority_record/v1`
- Check IDs: `legal_scope_facts_instruments_check`

### `legal_trace_authority` (validation)

Create a citation ledger using only supplied or observed sources, exact pinpoints and effective status; route absent authority to research or counsel instead of filling it in.

- Input refs: `supplied authority`, `document or process version`
- Output refs: `legal_scope_authority_record/v1`
- Check IDs: `legal_authority_citation_check`, `legal_final_determination_guard`

### `legal_map_issues_exceptions` (analysis)

Build clause and obligation rows with facts-to-rule traceability, definitions, dependencies, exceptions, conflicts, evidence state, uncertainty, disposition and counsel questions, adding only triggered issue families.

- Input refs: `jurisdiction`, `document or process version`, `supplied authority`, `review objective`
- Output refs: `legal_issue_traceability_matrix/v1`
- Check IDs: `legal_issue_matrix_check`

### `legal_apply_counsel_holds` (production)

Rank impact, applicability, urgency, confidence and reversibility, then impose mandatory counsel holds and owners for every triggered high-risk or authority-sensitive issue.

- Input refs: `jurisdiction`, `supplied authority`, `review objective`
- Output refs: `legal_risk_counsel_hold_register/v1`
- Check IDs: `legal_counsel_hold_check`

### `legal_prepare_negotiation_positions` (production)

When the objective is a redline, build one row per contested clause -- playbook position, gap, proposed language, fallback, walk-away, counsel-hold state -- then rank the concession order by what is lost and name the linked rows; prepare nothing for a clause whose hold is open.

- Input refs: `document or process version`, `supplied authority`, `review objective`
- Output refs: `legal_negotiation_preparation/v1 when the objective is a redline rather than an assessment`
- Check IDs: `legal_negotiation_preparation_check`, `legal_counsel_hold_check`

### `legal_validate_disposition` (validation)

Return PASS, REVISE, or HOLD with exact open triggers and counsel route; prohibit final legal or compliance determinations until all mandatory holds are resolved by qualified counsel.

- Input refs: `jurisdiction`, `document or process version`, `supplied authority`, `review objective`
- Output refs: `legal_review_disposition/v1`
- Check IDs: `legal_scope_facts_instruments_check`, `legal_authority_citation_check`, `legal_issue_matrix_check`, `legal_counsel_hold_check`, `legal_final_determination_guard`
