# Capability and Public Skill Map

Load this reference for questions about what OMH can do, which skill fits a
task, the public ULW family, or how many skills are installed.

## Retrieve the Current Catalog

- For the public catalog, inspect the generated
  `skills/omh-routing/references/catalog-index.md` and
  `skills/omh-routing/references/workflow-registry.md` on the disclosed official
  ref, or run `omh docs workflows --json` from a version-pinned checkout.
  Registry IDs and internal fields are not public display names; derive public
  names with `src/skills/catalog_types.py` and
  `src/routing/display_names.py`.
- `omh list --json` reports only the current installed manifest. Count those
  returned records only when the user asks about `current_local_install`; a
  clean or differently profiled home can legitimately report zero skills.
- Use `omh recommend "<intent>" --json --limit 3` for a bounded recommendation;
  a recommendation is not a reason to dump or memorize the full catalog.
- Verify the six capability families in `src/capabilities/families.py` at the
  disclosed ref.

Never hard-code a mutable public catalog or installed-manifest count in an
answer or in the always-loaded skill body. They answer different questions and
can differ by version and profile.

## Six Capability Families

Use the current projection, whose public families are:

1. Plan and decide.
2. Learn and gather.
3. Retain knowledge.
4. Create materials and visuals.
5. Delegate coding and ship.
6. Operate and observe.

Representative exact public skills across the engineering-intelligence catalog:

| Area | Public skill examples |
| --- | --- |
| Operations | `omh-support-operations`, `omh-deploy-and-monitor` |
| Design | `omh-design-orchestration`, `omh-design-quality-gate` |
| Frontend | `omh-frontend`, `omh-frontend-refactor` |
| Finance and financial statements | `omh-finance-analysis` |
| Planning | `ulw-plan`, `ulw-interview`, `ulw-context` |
| Research | `ulw-research`, `omh-web-research`, `omh-source-finder` |
| Inference serving | `omh-inference-serving` |
| Reliability and review | `omh-reliability-review`, `omh-code-review` |
| Materials | `omh-materials-package`, `omh-report-package` |
| Retained knowledge | `omh-memory-new`, `omh-memory-sync`, `omh-decision-recall`, `omh-wiki` |

## Public ULW Names

When examples need an engine name, use only these current public labels:
`ulw-context`, `ulw-interview`, `ulw-research`, `ulw-plan`, `ulw-work`,
`ulw-maestro`, `ulw-loop`, `ulw-qa`, and `ulw-perf`.

Canonical implementation identifiers may differ internally. Do not expose an
internal identifier as the public skill name, and do not derive an installed
name by guessing from the canonical id.
