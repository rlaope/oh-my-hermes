# Biomedical evidence producer

Status: producer implementation and bounded two-source live retrieval observed.
The real report is **partial**, not a clinical conclusion or complete identity /
freshness reconciliation. Integration/distribution acceptance remains separate.

## Delivered contract

Canonical module: `src/skills/biomedical_evidence_skill.py` exports `DEFINITION`,
`biomedical_evidence_definition()`, `REFERENCE_TEXT`,
`biomedical_evidence_reference_templates()`, `TOOLKIT_RESOURCES`,
`biomedical_evidence_support_templates()` and
`biomedical_evidence_provenance_manifest()`.

- Generic progressive method rendering; no new core command or artifact RPC.
- Explicit `reasoning_demand="heavy"` for identity, structured assertions,
  provenance, conflicting claims, source failures and freshness validation.
  This is supported by executable reconciliation and observed source captures,
  not an installation/readiness claim for every host.
- Generated execution reference: `references/execution-and-qa.md`. The shared
  renderer owns `references/full-contract.md` and `references/procedure.md`.
- Closed support paths, relative to this toolkit only:

```text
README.md
scripts/reconcile.py
upstream-manifest.json
```

No upstream pack or API response is shipped. All local content is original OMH
MIT guidance/helper code. No `LICENSE.upstream` is needed because no upstream
code or playbook prose was copied. The provenance manifest pins source audit
paths and digests at BioMCP revision
`a843629fb447750418cf746effe94010b1028a28`, including LICENSE, README, source
licensing and the two focused worked examples. BioMCP code is MIT, Copyright
(c) 2025 Ian Maurer; provider data rights remain separate. The source audit
revision is not a claimed build commit of the installed binary.

## Runnable behavior

Agent/operator setup and capture grammar are in `toolkit/README.md`. The chosen
policy-compliant architecture explicitly runs the separately installed
`biomcp-cli` binary through the host's bounded terminal tool, then invokes:

```sh
python toolkit/scripts/reconcile.py --capture-manifest CAPTURES.json \
  --output-dir NEW_DIRECTORY
```

The helper opens no socket and launches no process. It validates the declared
public scope, exact argv/version/time receipts, both raw-stream hashes, relative
capture paths, nonsymlink components, bounded inputs and known BioMCP source
schemas. It preserves identity/build/HGVS/transcript fields, ClinVar accession /
RCV / SCV assertion objects with submitter/review/context, and registry records.
Germline, somatic, disease contexts and assertion levels are never flattened.
Differing exact-context values and upstream conflict/cached-primary notes remain
visible without adjudication. Evaluation, update and retrieval times are distinct;
missing dates are null, not filled with retrieval or trial start/completion dates.
Literal disease-label matching is not ontology equivalence. Registry status is
not eligibility and variant-to-trial relevance remains unestablished.

Outputs are `evidence-matrix.json` and hashed `manifest.json`. Exit 0 means no
detected completeness gap in recognized inputs, not clinical validity. Exit 3
writes an unmistakable usable partial report; exit 2 refuses invalid envelopes,
integrity/path violations or existing output paths without a success artifact.
Raw capture receipts are operator assertions, not authenticated retrieval proofs.
No patient data, clinical eligibility or treatment recommendation is supported.

## Observed isolated environment and public smoke

Evidence root (outside the repository):
`$HOME/.hermes/cache/scratch/omh-domain-dag-evidence-20261022/bio/`.
Every probe/test process used
`TMPDIR=$HOME/.hermes/cache/scratch`.

Observed installation commands, both exit 0:

```sh
uv venv --python 3.12 $HOME/.hermes/cache/scratch/omh-domain-dag-evidence-20261022/bio/venv
uv pip install --python $HOME/.hermes/cache/scratch/omh-domain-dag-evidence-20261022/bio/venv/bin/python biomcp-cli
```

Resolved: **biomcp-cli 0.9.3**, binary `biomcp 0.9.3`, CPython 3.12.13,
macOS 26.5.1 arm64. Package/version/platform/binary hash receipts are in
`smoke-summary.json`; installed help and version streams plus receipts are kept
alongside it. Core OMH dependencies and live Hermes profiles were not changed.

The following commands used that isolated binary; public retrievals had a
40-second initial limit or a 35-second focused-discovery/detail limit. Health
had a 30-second limit. No retry or substitute biological response was used:

```sh
biomcp --json --no-cache health --apis-only --api ClinicalTrials.gov --api MyVariant --fail-on-error
biomcp --json --no-cache --disable-sources commercial-restricted get variant "BRAF V600E" clinvar
biomcp --json --no-cache search trial --source ctgov -c melanoma --mutation "BRAF V600E" --limit 1
biomcp --json --no-cache get trial NCT02410863 --source ctgov
```

Each exited 0. Health reported the two requested APIs healthy; MyVariant health
alone is not a ClinVar-specific health proof. Trial detail used an identifier
actually returned by discovery. An earlier documented-example lookup of
`NCT02576665` is also preserved, but is not the selected main trial capture.
The capture envelope retains exact query strings and intended identifiers.

`verification.json` identifies the final real output at
`reconciliation-final/evidence-matrix.json` and checks both raw hashes, the
helper hash and output matrix hash. Observed source availability is complete for
ClinVar and ClinicalTrials.gov; report status is **partial**, helper exit **3**:

- ClinVar: 86 preserved assertion objects; three scoped disagreement records.
  Some source assertions lack evaluation dates; no date was manufactured.
- ClinicalTrials.gov: detail retrieved successfully, but BioMCP omitted registry
  update time. The returned disease label differs from the literal query label;
  no alias or ontology equivalence was silently asserted. A registry record is
  preserved, not represented as a genetic classification assertion.
- Source retrieval does not establish clinical agreement, eligibility or patient
  applicability. Extra cached BioMCP enrichment stays in raw captures and is not
  treated as requested live evidence.

Live raw responses are **not** copied into this report or the shipped toolkit.
No public-source outage occurred during this bounded smoke; partial/failing
source behavior was exercised separately with original synthetic schema fixtures.

## Offline verification

From the scoped checkout, exact commands (all exit 0):

```sh
TMPDIR=$HOME/.hermes/cache/scratch PYTHONPATH=tests uv run python -m unittest tests.test_biomedical_evidence_skill -v
TMPDIR=$HOME/.hermes/cache/scratch PYTHONPATH=tests uv run python -m unittest tests.test_handoff_safety_contract_enforcement -q
TMPDIR=$HOME/.hermes/cache/scratch uv run --group lint ruff check src/skills/biomedical_evidence_skill.py src/skills/biomedical_evidence_toolkit tests/test_biomedical_evidence_skill.py
TMPDIR=$HOME/.hermes/cache/scratch uv run python -m py_compile src/skills/biomedical_evidence_skill.py src/skills/biomedical_evidence_toolkit/scripts/reconcile.py tests/test_biomedical_evidence_skill.py
```

Observed: 12 focused tests passed, with loader/test-ID count independently
cross-checked; 35 source-safety tests passed; lint and compilation passed.
Focused cases include wrong identity/build/transcript/accession/NCT and disease,
nonzero/missing/embedded source failure, invalid JSON/unknown shapes, contradictory
same-context claims without merging somatic domains, absent/old timestamps,
public-scope attestation, hashes/traversal/symlinks, output preservation, CLI
partial exit, dependency-free help and closed resource provenance/tamper checks.
Synthetic fixtures use invented schema labels, not claimed biological findings.

Direct generic method rendering measured 5,610 UTF-8 body bytes; both toolkit
and execution-reference pointers were present. The existing density producer
reported zero filler hits, zero repeated share, 13.7 payload markers per 1,000
prose characters, and no density violations. That direct producer check is not
catalog registration or native/portable distribution evidence.

## V-01 schema repair verification

The independent review found a synthetic aggregate classification object being
accepted as complete. The original verifier report, `verify/negative_cases.py`,
its input fixtures and historical output remain unchanged. This is an adapter
schema defect, not a claim that a live ClinVar response contained that value.

The repaired adapter applies one nonblank-string classification check to every
record-level germline, aggregate and submission assertion. It does not enumerate
clinical classifications, coerce values or infer biomedical truth. Unsupported
classification values and their original assertion objects/JSON-pointer paths
remain visible, with an explicit unavailable claim, unavailable ClinVar row and
schema gap. The matrix becomes partial and exits 3. Unsupported assertions are
excluded from conflict comparison; legitimate levels, domains and disease
contexts remain separate. The local helper and toolkit README hashes were
refreshed in `upstream-manifest.json`; upstream audit identities are unchanged.

Evidence is separate from the historical producer evidence, under:
`$HOME/.hermes/cache/scratch/omh-domain-dag-evidence-20261022/repair-verify/bio-schema-fix/`.
From the checkout, with `TMPDIR=$HOME/.hermes/cache/scratch` and
`PYTHONPATH=tests`:

- Test-first regression command:
  `.venv/bin/python -m unittest test_biomedical_evidence_skill.ReconcileTests.test_every_assertion_requires_nonblank_string_classification -v`.
  Before repair: exit 1, one method with 27 failing subcases. After repair: exit 0.
  Subcases exercise absent/null/empty/blank/object/list/bool/number values at all
  three assertion levels, including a malformed later row after a valid one.
- `.venv/bin/python -m unittest test_biomedical_evidence_skill -v`:
  exit 0, 13 tests; independently counted 13 unique test IDs. Cases verify partial
  CLI/manifest state, raw assertion retention, pointers, no unsupported conflict
  interpretation, unchanged input bytes, and preserved valid-schema success.
- `.venv/bin/python -m unittest test_handoff_safety_contract_enforcement -q`:
  exit 0, 35 tests. Scoped Ruff, compilation and `git diff --check`: exit 0.
- The original independent biomedical test/assertions also pass against current
  source (one test, exit 0). The task-local wrapper redirects only the helper
  load and output directory; it does not replace assertions, inputs or the
  historical installed helper. This is not a fresh installed-wheel gate.
- Real CLI replay of the original malformed fixture: exit 3, status/availability
  partial; the classification object remains unchanged at
  `/clinvar/aggregates/0` with an explicit schema gap.
- Offline replay of the actual BioMCP 0.9.3 public captures: exit 3, both sources
  available, status partial. The matrix is byte-identical to the historical
  producer matrix, SHA-256
  `2220f49d8c00183f17cc87f9b4b5f9232531b1e01ae557238bad49cd6e6e1a51`.
  No fresh retrieval or biological result is claimed; missing dates and literal
  disease-label gaps remain unresolved.

`verify_fix.py`, `commands.jsonl`, `red.*`, `readback.json` and per-command
streams retain the exact commands/exits and hash checks. Shared generated
projections, builds and acceptance remain the parent's responsibility. No full
suite, new wheel, live installation or overall acceptance pass is claimed here.

## Original producer integration checklist (historical)

No shared file or generated projection was edited by this producer. Integrator:

1. Register `DEFINITION`, lazy reference factory and closed support factory in
   catalog definitions, `SkillRecord` reference/support dispatch and shared
   support registry. Preserve owner filtering; remove show-reel-only assumptions
   in materialization, ownership/stale handling and local-source conversion.
2. Add the three explicit resources to `pyproject.toml` package-data and portable
   support paths, the execution reference to portable declarations, and LF policy.
   Do not add science dependencies or process/network allowlist exceptions.
3. Wire awareness lane/context card, routing policy, labels/actions/dedicated card,
   direct-workflow membership, positive unbranded requests and misleading-word
   negatives. Keep English triggers and the frozen Korean trigger tables intact.
4. Regenerate the shared native/tap/portable inventories and six adapters; update
   producer-derived counts/digests and source/discoverability documentation.
5. Run source-hidden wheel/sdist, six-host parity, ownership/update/collision
   checks, shared routing/procedure/deference/density gates and the full suite.
   None of those distribution/integration checks is claimed here.

There is no verified bundled `bioinformatics` name in the current closed
`HermesSkillLine` inventory. The definition does not invent one or expand that
inventory: computational biology is deferred generically, and citation-only work
uses the verified bundled `grounded-citations` boundary.
