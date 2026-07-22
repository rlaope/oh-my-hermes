# Contract Sunset Candidates

**Candidates only — no removal decided; each needs its own goal PR.**

This is a starter list produced by PR-9 (omh flat-shim sweep). It enumerates
schema-versioned (`*/vN`) contract IDs whose grep footprint is **≤ 2 source
files** (typically the defining module plus at most one consumer/command),
which makes them low-blast-radius candidates for a future deprecation pass.

Selection rule: a candidate qualifies only when the exact contract token (e.g.
`\bcomparative_quality_rubric/v1\b`, word-boundary matched) appears in **at most
two files under `src/`**. Footprints below were verified individually with
`grep -rEln`. Test-file references are reported separately and do **not** count
toward the ≤2 `src/` footprint.

**This PR removes zero contracts and zero code.** Any actual sunset must be its
own goal PR with its own consumer re-verification and migration/telemetry review.

## Candidates

| Contract ID | Defining file | src footprint | Consumer count (src) | Test refs | Sunset rationale |
|---|---|---|---|---|---|
| `agent_operator_productivity/v1` | `src/workflows/operator_productivity.py` | 2 files | 1 (`src/skills/catalog.py`) | 0 | Operator-productivity index feature has a single catalog consumer; low adoption surface. |
| `agent_operator_productivity_index/v1` | `src/workflows/operator_productivity.py` | 1 file | 0 | 0 | Defined but never consumed outside its own module; pure internal sub-contract. |
| `agent_operator_productivity_validation/v1` | `src/workflows/operator_productivity.py` | 1 file | 0 | 0 | Validation schema paired with the above; no external reader. |
| `product_evidence_loop/v1` | `src/workflows/product_evidence_loop.py` | 2 files | 1 (`src/skills/catalog.py`) | 2 (`test_cli.py`, `test_router_content.py`) | Single catalog consumer; product-evidence-loop workflow is narrowly wired. |
| `comparative_quality_rubric/v1` | _(none — prescriptive only)_ | 2 files | 2 (`src/routing/recommend.py`, `src/skills/catalog.py`) | 1 (`test_router_content.py`) | No owning module: referenced only as a prescribed artifact string in a route hint and catalog copy; candidate for consolidation into the design-quality-gate contract. |

## Mandate examples evaluated but NOT qualifying (>2 src files)

Verified and excluded so the list stays honest — these exceed the ≤2 threshold
and are therefore **not** low-blast-radius:

| Contract ID | src footprint | Files |
|---|---|---|
| `research_department_plan/v1` | 5 | `capabilities/orchestration.py`, `catalogs/playbooks.py`, `routing/recommend.py`, `skills/catalog.py`, `workflows/research_department.py` |
| `paper_learning_card/v1` | 4 | `routing/recommend.py`, `skills/catalog.py`, `workflows/paper_learning.py`, `wrapper/contract.py` |
| `menubar_app/v1` | 3 | `commands/menubar.py`, `commands/setup.py`, `surfaces/menubar_app.py` |

## Next steps (per candidate, in its own PR)

1. Re-run the word-boundary footprint grep across `src/`, `tests/`, `examples/`,
   `docs/`, `scripts/`, and `plugin_bundle` — footprints drift.
2. Confirm no runtime record/handoff validator keys on the contract ID.
3. Decide replace vs. remove; if replacing, ship the successor contract first.
4. Update `docs/WORKFLOWS.md` regeneration output and any skill-catalog copy.
