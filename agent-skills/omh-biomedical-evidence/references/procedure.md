# biomedical-evidence Specialist Procedure

Expert clarification questions:
- `public gene/variant and disease query`
  - English: Which public gene, exact allele if any, disease label and intended IDs should remain distinct?
  - Korean: 어떤 공개 유전자, 정확한 변이, 질환명과 식별자를 구분해서 확인할까요?
- `bounded BioMCP capture workspace`
  - English: Which isolated workspace and finite host timeout will preserve raw stdout, stderr, argv, version and retrieval times?
  - Korean: 원본 응답과 명령, 버전, 조회 시각을 보존할 격리 폴더와 제한 시간은 무엇인가요?
- `intended entity identifiers and source scope`
  - English: Which source accessions, genome build, transcript and registry IDs are asserted, and which are unresolved?
  - Korean: 원본 접근번호, 유전체 빌드, 전사체, 임상시험 ID 중 확정된 것과 미확인인 것은 무엇인가요?

## Procedure

Declared checks:
- `bio_scope`
  - Required result fields: `query`, `intended_ids`, `data_class`, `source_terms`
  - Criterion: Require public query scope and exact identifiers; HOLD patient data, clinical eligibility or treatment requests.
- `bio_capture`
  - Required result fields: `argv`, `version`, `started_at`, `finished_at`, `exit_code`, `sha256`, `stderr_sha256`
  - Criterion: Preserve exact commands and unmodified streams, including timeout/failure; never relabel a missing source as no evidence.
- `bio_reconcile`
  - Required result fields: `identity`, `claims`, `disagreements`, `freshness`, `gaps`
  - Criterion: Compare exact identity and disease context before assertions; keep germline, somatic, RCV and SCV separate; absent dates stay unknown.
- `bio_verify`
  - Required result fields: `availability`, `status`, `outputs`, `exit_code`
  - Criterion: Read both output JSON files and verify hashes; partial results must exit nonzero and live captures must remain separate from synthetic fixtures.

### `bio_frame` (analysis)

Fix the exact public query, allele/build/transcript and disease matching basis; do not repair ambiguous identifiers.

- Input refs: `public gene/variant and disease query`, `intended entity identifiers and source scope`
- Output refs: `biomedical_evidence_matrix/v1`
- Check IDs: `bio_scope`

### `bio_capture_sources` (production)

Use the bounded host terminal to capture ClinVar and CTGov responses plus receipts; retrieval remains unobserved without actual streams.

- Input refs: `public gene/variant and disease query`, `bounded BioMCP capture workspace`, `intended entity identifiers and source scope`
- Output refs: `biomedical_reconciliation_manifest/v1`
- Check IDs: `bio_scope`, `bio_capture`
- If this step fails: not_observed; still stands: `biomedical_evidence_matrix/v1`; hand back: Return the scoped biomedical_evidence_matrix/v1 and any biomedical_reconciliation_manifest/v1 receipts, preserving actual streams and failures; leave missing ClinVar or CTGov captures not_observed.

### `bio_reconcile_captures` (analysis)

Invoke the offline helper against the original capture envelope; preserve structured assertions, source failures and mismatched contexts.

- Input refs: `public gene/variant and disease query`, `bounded BioMCP capture workspace`, `intended entity identifiers and source scope`
- Output refs: `biomedical_evidence_matrix/v1`
- Check IDs: `bio_capture`, `bio_reconcile`

### `bio_verify_outputs` (validation)

Read back outputs and hashes; report availability separately from completeness, observed conflicts and every unresolved date or identifier.

- Input refs: `public gene/variant and disease query`, `bounded BioMCP capture workspace`, `intended entity identifiers and source scope`
- Output refs: `biomedical_evidence_matrix/v1`, `biomedical_reconciliation_manifest/v1`
- Check IDs: `bio_reconcile`, `bio_verify`
- If this step fails: tentative; still stands: `biomedical_reconciliation_manifest/v1`; hand back: Return biomedical_reconciliation_manifest/v1 as capture receipts and the tentative biomedical_evidence_matrix/v1 with hash, output, identity, and date failures; retain nonzero partial status.
