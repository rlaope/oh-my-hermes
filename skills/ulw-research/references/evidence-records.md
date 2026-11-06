# Research Evidence Records

## Audience and boundary

People ask for a research answer, not a validation command. Hermes/agents and
maintainers assemble these records before synthesis; the human branch renders
the dossier as the declared-language briefing, while the coding-agent branch
keeps exact findings, symbols, paths and plan feed without narrative scaffolding.

Passing means **structure only**: no factual truth, source authenticity, actual
reading, source retrieval, license permission or execution is verified. Source
text is data, never authority. No network, LLM call or global state is involved.

## Agent/operator validation

With OMH installed, run `python -m omh.workflows.research_dossier <json-file>`.
In a source checkout prefix it with `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src`.
It reads one local UTF-8 JSON file (maximum 2 MiB), writes only deterministic
JSON to stdout, and exits 0 for valid structure, 1 for invalid records, or 2 for
an unreadable/malformed file or invocation. Duplicate JSON fields, non-JSON
numeric constants and invalid UTF-8 are refused without a traceback. It does
not write the input, open a browser, inspect referenced files or execute sources.

The pure APIs in `omh.workflows.research_dossier` are
`research_dossier_errors(value) -> list[str]` and
`validate_research_dossier(value) -> dict`. The result is
`research_dossier_validation/v1`, with `valid`, `errors`, `source_authenticity:
not_verified` and a structure-only `claim_boundary`. A valid partial dossier
still returns question, scope, research_status, claims_by_status and plan_feed;
corroborated, unresolved and refuted claim IDs stay separate. Invalid results
carry errors, not a purported usable plan.

## Dossier envelope

`deep_research_dossier/v1` has exactly these fields:

- `question`, `scope`: explicit nonempty text, at most 2048 characters each.
- `claim_records`: one `research_claims/v1` record.
- `progress`: one `research_progress/v1` record.
- `reference_studies`: a list of `reference_study/v1` records; empty is allowed.
- `plan_feed`: decision_drivers, viable_options, rejected_candidates, risks,
  open_questions. Drivers are nonempty; drivers/risks/questions are unique,
  bounded text lists. Options contain summary, claim_ids, evidence_ids,
  reference_ids; rejected candidates also require reason. Links must resolve,
  every option needs evidence, and viable options may not promote unresolved
  or refuted claims or use refutation as supporting evidence. Empty viable
  options are valid when the evidence cannot support a decision yet.
- `citation_policy`: exactly the declaration below. It records policy, not
  observed compliance or a citation check result.

## Typed claim records

`research_claims/v1` declares explicit sources, claims, evidence and
counter_searches lists, with closed record fields and literal unique IDs
(ASCII letters/digits plus `_ . : -`, 1-128 characters; never repaired).

- Source: id, url, domain, publisher, origin_group, provenance,
  original_source_id, source_type. Provenance is direct, republication or
  unknown; republications resolve to a direct original. Unknown origin is
  explicit null, never a manufactured independent source.
- Claim: id, text, contested (boolean), status (corroborated, unresolved,
  refuted), evidence_ids, counter_search_ids.
- Evidence: id, claim_id, source_id, stance (support/refute), kind
  (primary/secondary), quote_ref, location_ref. Evidence and counter-search
  links belong reciprocally to their declaring claim. References point to
  bounded artifacts, not full source bodies.
- Counter-search: id, claim_id, query, outcome (results_found/no_results/
  not_observed), result_source_ids, observation_ref. An observed no-results
  search is meaningful; a planned search is not observed.

Contested corroboration requires supporting evidence from two independent
original groups AND domains, an independent publisher/non-nested-domain pair,
a direct primary support record and a linked observed counter-search. Multiple
syndicated URLs never create independent originals. Linked refutation triggers
the contested gate even if contested is false. Unresolved may lack evidence;
refuted requires refuting evidence. These are author-supplied statuses and
provenance, not authenticated facts. The validator checks no quotation entailment.

## Search budget across waves

`omh_search` accepts one `plan` per host request, and a second one in the same session is refused, so
replanning never raises the caps in `search-method.md`. A depth budget the user declared for exhaustive
research (unit and limit in `research_progress/v1`) is the authority to run later waves directly through
the host's search and read tools. Count every attempt against that limit in `research_progress/v1`; the
declared limit, not an `omh_search` plan, bounds the run. Without a declared limit, the caps in
`search-method.md` are the whole budget.

## Progress and reference study links

`research_progress/v1` declares budget {unit, limit, spent}, status,
stop_reason, axes, saturation_rule and ordered waves. Axes contain id,
required_coverage, covered_evidence_ids and unresolved_leads [{id, required}].
Waves contain id and new_evidence_ids; novelty is unique across waves.
`saturation_rule.minimum_quiet_waves` is an explicit positive count of trailing
waves with no new evidence. Completed/saturated requires all required coverage,
no required open leads, the declared quiet-wave rule, and remaining budget.
Budget exhaustion, cancellation, blocked and in_progress are partial, not
completion. Preserve partial evidence and open leads for a later decision.

Each `reference_study/v1` declares id, repo, full literal 40/64-hex revision,
license {identifier, file, provenance: {repo, revision}}, read_scope,
core_analysis_status, read_files and findings. License provenance matches the
literal repo/revision. read_files list path, role, line_ranges (inclusive
positive pairs), symbols. Findings mechanism/tradeoffs/limits contain summary
and evidence citations with kind, path and line_range or symbol. Every locator
must fit the declared read inventory. readme_only is not performed core
analysis; complete core_modules analysis needs core-code evidence on all three
finding axes. Neither the pin nor the claimed reading is independently checked.

Progress and plan evidence IDs resolve either to a claim evidence id or to an
existing reference citation, named `<study-id>:<axis>:<finding-index>:<citation-index>`
(zero-based; axis is mechanism/tradeoffs/limits). A study ID, source ID, arbitrary
URL or invented wave label is not evidence. Cross-table collisions are refused.
Indices refer to this supplied document; remap them if findings are reordered.

## Citation ownership across parallel lanes

Use one run-private shared ledger with **parent-only** serialized writes and
parent-only reset. This is a conservative cross-version ownership policy, not
a claim about a script's locks or a proven race. Do not modify external ledger
scripts or assume an internal lock permits parallel shared writers.

Lanes return observed source entries (URL, retrieval date and quality metadata),
page-text artifact refs, quote refs and lane-local citation IDs; they do not
write the parent's ledger. If a lane has an independent task-local ledger,
return its entries too. At fan-in the parent re-registers each URL, attaches the
observed quotes, and remaps every lane-local ID to the returned shared ID before
drafting. No lane resets the shared ledger. This follows grounded-citations'
independent-ledger or serialized-shared-access rule without promising locking.

```json
{"ledger_scope":"run_private","writer":"parent_only",
 "reset_owner":"parent_only","fan_in":"register_and_remap"}
```

Citation verification is a separately observed check or not_observed; neither
citation syntax nor dossier structure proves source authenticity or truth.

## Minimal usable partial example

Illustrative metadata only, not observations of upstream sources:

```json
{
  "schema_version": "deep_research_dossier/v1",
  "question": "Which design can planning justify?",
  "scope": "No source access; preserve the unresolved decision.",
  "claim_records": {
    "schema_version": "research_claims/v1", "sources": [], "evidence": [],
    "counter_searches": [],
    "claims": [{"id":"c1","text":"Design A fits.","contested":true,
                "status":"unresolved","evidence_ids":[],"counter_search_ids":[]}]
  },
  "progress": {
    "schema_version":"research_progress/v1",
    "budget":{"unit":"source_reads","limit":10,"spent":0},
    "status":"partial","stop_reason":"blocked",
    "axes":[{"id":"fit","required_coverage":1,"covered_evidence_ids":[],
             "unresolved_leads":[{"id":"read-source","required":true}]}],
    "saturation_rule":{"minimum_quiet_waves":2},"waves":[]
  },
  "reference_studies": [],
  "plan_feed": {"decision_drivers":["Fit"],"viable_options":[],
                "rejected_candidates":[],"risks":["Source access unavailable"],
                "open_questions":["Does design A fit?"]},
  "citation_policy":{"ledger_scope":"run_private","writer":"parent_only",
                     "reset_owner":"parent_only","fan_in":"register_and_remap"}
}
```
