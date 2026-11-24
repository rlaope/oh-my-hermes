# Domain science implementation and distribution contract

Status: producer contract, not implemented capability. Inspected on 2026-10-22 against
base `39d0d172d1f2ffdf8fb73acd010f6d9342a815d1`, branch
`hermes/domain-science-skills`. The accepted goal is three executable optional
science toolkits, not three report-only cards. Integration and independent
verification must still prove every completion gate below.

## Authority, ownership and policy decision before production

`AGENTS.md`, `docs/DIRECTION.md`, `docs/ADDING-A-SKILL.md`, `CLAUDE.md` and the
shared execution brief apply. No core dependency, live profile installation,
publication, paid endpoint, credentials, patient data, push, PR or release.
Every probe/test process must inherit
`TMPDIR=$HOME/.hermes/cache/scratch`. Evidence environments belong under
`$HOME/.hermes/cache/scratch/omh-domain-dag-evidence-20261022/<gis|bio|docking>/`.
This machine-local execution boundary is not a path to embed in shipped skill prose.
The contract node has no upstream DAG dependency; the existing shortlist and
`specialist.md` research handoffs were read. They explicitly say execution was
not verified; their proposals are not backend receipts.

**Genuine policy collision:** the AST safety tests scan *all* Python under
`src/`, including inert companion data. Adding `subprocess` to a BioMCP wrapper
or Vina CLI launcher requires a new `PROCESS_SPAWN_ALLOWLIST` entry; adding
`requests`, `socket` or `urllib.request` retrieval requires network-policy changes.
The current run forbids broadening those allowlists. Inert packaging alone does
not exempt a script. Do not bypass the checks through dynamic imports, `os`
spawn, shell scripts, or an imported bridge.

**Chosen compliant design:** GIS uses direct optional spatial libraries; docking
uses the documented direct Python `vina` API; BioMCP retrieval is an explicit
host `terminal` invocation of the separately installed BioMCP binary, followed
by a shipped, offline reconciliation helper reading captured JSON and receipts.
The BioMCP method remains runnable end-to-end, but the OMH helper itself does
not spawn BioMCP or open a socket. Deadline enforcement belongs to the host's
bounded execution tool, not a new core execution service. If a producer needs
another design, stop and obtain a parent policy decision before implementing it.
Do not weaken safety tests to make the goal appear complete.

## Disjoint producer ownership and public exports

| Canonical ID | Exclusive definition | Exclusive inert data directory | Exclusive unit test | Exclusive domain report |
| --- | --- | --- | --- | --- |
| `geospatial-analysis` | `src/skills/geospatial_analysis_skill.py` | `src/skills/geospatial_analysis_toolkit/` | `tests/test_geospatial_analysis_skill.py` | `docs/domain-skills/geospatial-analysis.md` |
| `biomedical-evidence` | `src/skills/biomedical_evidence_skill.py` | `src/skills/biomedical_evidence_toolkit/` | `tests/test_biomedical_evidence_skill.py` | `docs/domain-skills/biomedical-evidence.md` |
| `molecular-docking` | `src/skills/molecular_docking_skill.py` | `src/skills/molecular_docking_toolkit/` | `tests/test_molecular_docking_skill.py` | `docs/domain-skills/molecular-docking.md` |

Producers must not edit shared registration files, generated projections or
another producer's paths. Parent/integrator owns commits. Each producer exports
these names, substituting its underscore stem and canonical ID:

```python
from .catalog_types import SkillDefinition

DEFINITION = SkillDefinition(
    name="geospatial-analysis",
    description="Spatial layers to intersect: execute CRS-safe spatial analysis.",
    triggers=("geospatial-analysis", "geospatial overlay", "spatial intersection"),
    use_when="Use when supplied spatial layers need measured spatial computation.",
    category="analysis", hermes_role="operator",
    delegation_boundary="retained-catalog-intent",
    progressive_disclosure=True,
    # Add concrete domain inputs, questions, outputs, opening actions,
    # procedure_checks, procedure_steps, boundaries and completion rules.
)

def geospatial_analysis_definition() -> SkillDefinition:
    return DEFINITION

REFERENCE_TEXT = {"execution-and-qa": "...original complete instructions..."}

def geospatial_analysis_reference_templates():
    # Lazy import avoids a render/catalog definition import cycle.
    from .render import SkillReferenceTemplate, loadable_skill_mentions
    return [SkillReferenceTemplate(DEFINITION.name, f"references/{key}.md",
                                   loadable_skill_mentions(text))
            for key, text in REFERENCE_TEXT.items()]
```

The snippet fixes interfaces, not sufficient content or an implementation stub.
Provide corresponding `biomedical_evidence_definition`,
`biomedical_evidence_reference_templates`, `molecular_docking_definition`, and
`molecular_docking_reference_templates`. Prefer `DEFINITION` registration, matching
`show_reel_skill.py` and `decision_prototype_skill.py`; each agreed factory is a
convenient public accessor with the same immutable return value. Definitions
must import types from `catalog_types`, not `catalog`.

All three use existing generic `workflow_skill(name)` rendering through
`SkillRecord`, not a bespoke body or core execution command. The compact body
must point to `toolkit/README.md` and the domain execution reference; the generic
progressive renderer generates `references/full-contract.md` and, when procedures
are present, `references/procedure.md`. Do not produce those paths again.
Each `ProcedureStep` input/output ref must resolve against required inputs or
expected outputs, and each check ID against that definition's `ProcedureCheck`.
Use the existing `analysis`, `validation`, `production` procedure vocabulary.
Keep artifact schema identifiers as authored file contracts; do not claim new
registered `artifact_contracts` or new OMH RPCs.

Use English triggers only. Do not extend Korean trigger tables. Use concrete
`situations` describing problems rather than copying the triggers. Leave
`capability_family` and `path_globs` empty unless integration demonstrates a need;
common `.json`, `.csv` or `.pdb` paths must not select these skills by themselves.
Keep optional dependency checks inside explicit helper invocation, never module
registration/discovery. `--help` and input validation must work without optional
science libraries where feasible. Hermes-only bundled-skill deference uses
`HermesSkillLine`; ordinary OMH siblings use backticked canonical names.

### Closed support API on each producer module

Export `TOOLKIT_RESOURCES: tuple[str, ...]` with every reviewed path relative to
that producer's toolkit, and `<stem>_support_templates()` returning
`list[SkillSupportTemplate]`. Include `README.md`, actual scripts, any promised
JSON examples, and `upstream-manifest.json`; include `LICENSE.upstream` only when
applicable, plus notices in allowed text formats. The support factory must:

1. Read only `importlib.resources.files("omh.skills").joinpath("<stem>_toolkit")`.
2. Read precisely `TOOLKIT_RESOURCES`, never recursively glob or trust a local
   source manifest to expand the inventory.
3. Validate a bounded JSON provenance inventory and per-resource UTF-8 hashes.
4. Return `SkillSupportTemplate(DEFINITION.name, "toolkit/" + relative, text)`.
5. Never import/execute a toolkit script or a science dependency.

Expose `<stem>_provenance_manifest()` if provenance is generated. Exclude the
manifest's own hash from its internal inventory; outer native/portable inventories
hash the manifest. Record repository, immutable revision, source path/hash,
local path/hash, license, copyright, original/copied/modified classification and
modification notice. Original helpers must be identified as original, not
misattributed upstream derivatives.

Existing `validate_support_path` permits `toolkit/` paths with reviewed text
suffixes `.md`, `.json`, `.html`, `.css`, `.js`, `.mjs`, `.py`, `.swift`, `.sh`,
and special `LICENSE.upstream`; size is bounded to 1 MiB per content string.
It rejects traversal, Windows reserved names, NUL and casefold collisions.
Do not add `.geojson`, `.pdbqt`, `.txt`, binary fixtures or broad suffix exceptions.
GeoJSON examples may be actual GeoJSON objects stored as `.json`. Docking smoke
inputs can be fetched explicitly into the evidence directory with audited
provenance rather than promised as shipped resources. No binary toolkits,
`__init__.py` packages or hidden dependency bootstrapping.

## Supported external and toolkit CLI contracts

The helper names/flags below are the agreed new *standalone script* interfaces,
not pre-existing OMH commands. Producers must implement them or report an exact
interface amendment in their handoff before integration. Each script supports
`--help`; argument/validation/dependency failure is nonzero, never a success
manifest with guessed findings. Keep outputs new or require explicit overwrite;
reject symlinks/unsafe paths and preserve pre-existing user files.

### GIS: direct GeoPandas/Shapely/PyProj vector computation

Minimum shipped entry: `toolkit/scripts/analyze.py`:

```text
python analyze.py --input INPUT.json --overlay OVERLAY.json \
  --input-crs EPSG:3857 --overlay-crs EPSG:3857 --target-crs EPSG:3857 \
  --output-dir NEW_DIRECTORY
```

CRS must come from a trustworthy input declaration or explicit flags, never a
silent guess. Validate geometry, finite coordinates, CRS compatibility and units
before actual overlay/intersection/join. Distances/areas in geographic degrees
must be rejected or explicitly reprojected to an appropriate metric CRS. Do not
silently repair invalid geometry. Emit actual result GeoJSON, measured summary
JSON and replay/provenance manifest. Emit a map only if genuinely implemented
and inspected; exclude raster/NoData/statistical claims unless exercised.

Ship declared synthetic `.json` layers with a known analytic area/count answer,
not a claimed public flood-risk finding. The isolated real-library smoke runs
the exact command above against these layers; verify actual geometry/count/area
against the independent analytical expectation and record library versions.
Use GIS-MCP only if actually available and exercised; otherwise label the backend
as direct libraries, not MCP.

### Bio: explicit BioMCP capture, then offline reconciliation

Observed upstream grammar at `a843629fb447750418cf746effe94010b1028a28`:
`biomcp get variant "BRAF V600E" clinvar`,
`biomcp search trial -c melanoma -s recruiting`,
`biomcp variant trials "BRAF V600E" --limit 5`,
`biomcp get trial NCT02576665 eligibility locations outcomes`.
The README documents JSON mode and `_meta.section_sources`. The producer must
inspect the installed `--help` for exact global/subcommand `--json` placement
and trial source filtering; do not assume a different BioMCP version implements
all flags. Install **`biomcp-cli`**, never the unrelated `biomcp` package.

The host invokes the approved BioMCP binary with finite command timeouts and
saves stdout, stderr, argv, version, UTC start/end, exit code and hashes under the
approved evidence directory. Two focused public captures target ClinVar plus
ClinicalTrials.gov. Avoid unrequested enrichment sources and restricted sources.
Read `biomcp skill list` / `biomcp skill <slug>` for upstream methods only after
license review; do not install the whole pack into an agent profile.

Minimum shipped entry: `toolkit/scripts/reconcile.py`:

```text
python reconcile.py --capture-manifest CAPTURES.json --output-dir NEW_DIRECTORY
```

`CAPTURES.json` is a local envelope with a public `query` (gene/variant/disease),
`captures` entries (`source`, `argv`, `version`, `started_at`, `finished_at`,
`exit_code`, `stdout_path`, `stderr_path`, `sha256`), and optional intended entity
IDs. Relative capture paths resolve beneath the envelope's directory; do not
accept traversal or follow symlinks. Producers may add fields, but must document
them and retain the original responses unmodified. Source time and retrieval
time are separate. A successful adapter must preserve accession/NCT identifiers,
variant assembly/HGVS/transcript where provided, disease matching basis,
source-specific assertions, trial status and update time, disagreements and gaps.
Recruitment is not eligibility; population, germline/somatic and disease-context
mismatches must not be flattened into one clinical conclusion.

Emit an evidence matrix and manifest referencing raw capture hashes. If an API
fails or an embedded source section reports failure despite CLI exit zero,
preserve it as unavailable/partial, never an empty-success/no-evidence finding.
A usable partial report must have an unmistakable partial status and nonzero
CLI status so shell callers cannot interpret a failed source as complete.
No new network client, subprocess wrapper, patient data or treatment advice.
The real smoke must capture actual upstream responses; offline synthetic schema
fixtures are separate tests and cannot stand in for live findings.

### Docking: observed ToolUniverse assessment; explicit standalone Vina fallback

Observed ToolUniverse revision `53b4f8eb48d304f947bab85182b88d7c2a5c6794` has:

- `src/tooluniverse/tools/NvidiaNIM_diffdock.py`: exact name
  `NvidiaNIM_diffdock`, parameters `protein`, `ligand`, `ligand_file_type`,
  `num_poses`, `time_divisions`, `steps`, `save_trajectory`, `is_staged`.
  This is a NVIDIA NIM provider route, not proof of a local installed engine.
- `src/tooluniverse/tools/ClusPro_submit_peptide_docking.py`: exact name
  `ClusPro_submit_peptide_docking`, receptor PDB ID and peptide sequence;
  submitting a job is not a completed small-molecule docking result.
- `src/tooluniverse/data/remote_tools/boltz_tools.json`: exact name
  `boltz2_docking`, `sequence` plus `ligands` with `id`/`smiles`;
  `return_structure` defaults false. Its remote README requires Linux/CUDA,
  separate model environment/checkpoints; private relay/setup observations are
  upstream claims, not this machine's execution or consent to deploy a service.

No free, credentialless, macOS-ready ToolUniverse execution was established by
this inspection. Do not invent `AutoDockVina_dock`, `vina_docking` or similar
ToolUniverse names. The authorized fallback is **standalone AutoDock Vina Python**,
not ToolUniverse integration. Actual backend readiness remains the docking
producer's smoke gate; source docs do not prove installation succeeds.

Official `ccsb-scripps/AutoDock-Vina` Python tutorial documents `from vina import
Vina`, `set_receptor`, `set_ligand_from_file`, `compute_vina_maps`, `dock`, and
`write_poses`. The observed `develop` revision is
`bb64e5e26b520569a86360d69248069b5e665b3f`; freeze inputs/docs to an immutable
revision in the producer's receipt. The example uses 1IEP receptor/ligand and
center `[15.190, 53.903, 16.917]`, box `[20, 20, 20]` angstrom. Do not copy the
tutorial's output scores as measured values.

Minimum shipped entry: `toolkit/scripts/dock.py`:

```text
python dock.py --receptor RECEPTOR.pdbqt --ligand LIGAND.pdbqt \
  --center 15.190 53.903 16.917 --box-size 20 20 20 \
  --cpu 1 --seed 20261022 --exhaustiveness 1 --n-poses 1 \
  --output-dir NEW_DIRECTORY
```

Use the direct `Vina(sf_name="vina", cpu=1, seed=...)` API after validating paths,
PDBQT content, finite center/box values, positive bounded box dimensions,
CPU/exhaustiveness/pose bounds and input byte caps. Keep native imports lazy.
Enforce a finite host timeout for the entire command (suggested smoke cap 180 s);
no unsupported claim that a Python flag can interrupt a native engine safely.
Capture real pose PDBQT, finite score(s) with units and scoring function, engine
version, stdout/stderr, input/output hashes, settings and replay command.
A score-only call, `optimize()` or fake pose is not docking. Seed reproducibility
is bounded by engine version/platform; do not claim universal byte identity.
Do not convert docking scores into efficacy/safety, affinity certainty or clinical
claims. If two genuinely different bounded setup attempts fail, stop BLOCKED
with exact failures; do not ship a success stub or mark the three-skill goal done.

## Integration-owned shared seams (current source, not speculative APIs)

| Seam | Required integration change |
| --- | --- |
| `src/skills/catalog_definitions.py` `_DEFINITIONS` | Import each `DEFINITION` once and append once; no producer edits here. |
| `src/skills/skill_record.py` `REFERENCE_PRODUCERS` | Add each lazy domain reference factory once. Generic body rendering already works. |
| `src/skills/support_files.py` `builtin_skill_support_templates()` | Concatenate the three closed support factories with existing show-reel; run existing validation. |
| `src/skills/skill_record.py` `SkillRecord.support()` | Remove show-reel-only filtering; return only this record's declared templates. |
| `src/install/support_materialization.py` `support_records`, `support_path`, `write_support` | Replace show-reel-only owner/prefix/stale-cleanup assumptions with the reviewed finite owners derived from canonical support templates; preserve strict path/ownership checks and stale edited/foreign files. |
| `src/omh/converter.py` `convert_support_from_dir()` | Recognize only declared domain owners; filter expected templates by that source skill before comparing exact bytes. Never multiply every owner's templates into each directory or trust source inventories. |
| `src/skills/catalog_portable.py` | Declare each display ID's portability and each `canonical-id/toolkit/<path>` in `PORTABLE_SUPPORT_PATHS`; add reference entries under the existing portable reference scheme. |
| `pyproject.toml` `[tool.setuptools.package-data]` `"omh.skills"` | Enumerate exact toolkit paths, notices and provenance; keep `dependencies=[]`, no science package registration. |
| `.gitattributes` | Match existing LF policy for all canonical/generated domain support text so hash parity survives Windows autocrlf. |
| `src/commands/docs.py` tap reference/support discovery | Current actual-file scan names `omh-show-reel/toolkit/**/*`; extend to closed owners so missing AND undeclared actual support are detected. |
| `src/skills/catalog.py` surface/lane derivations | Confirm install visibility, discovery and default role/category without inventing a role/banner category. |
| `src/plugin_bundle/omh/awareness.py` | Register lane membership and `_WORKFLOW_CONTEXT_CARD_BY_WORKFLOW` entries. |
| `src/routing/recommend.py` | Register `_SKILL_POLICIES`; keep normalization/cue helpers and whole-phrase protections, no broad new substring route. |
| `src/routing/action_copy.py`, `src/wrapper/contract.py` | Curated next-action labels, `VISIBLE_ACTIONS`, `_ACK_PRIMARY_ACTIONS_BY_NEXT_ACTION`, dedicated operations chat cards and `_DIRECT_WORKFLOW_SKILLS`; no legacy allowlist extensions. |
| `src/quality/routing_precision.py`, `src/quality/chat_card_coverage.py` | Positive/negative reach plus dedicated-card evidence. Re-derive affected count pins and drift budgets from actual producers. |
| `src/skills/catalog_harnesses.py`, existing exposure/operations registries | Inspect reachability requirements; register only needed harness/surface data. Do not pretend authored output JSON is a registered machine-enforced operations artifact. |
| Generated families and fixtures | Regenerate tap/native, portable single manifest and six adapters, workflows/roles, capability families, shortlist, demo cards, affected count/deference/digest fixtures and discoverability docs. |

The existing portable inventory is `agent_skill_files()` /
`agent_skills_manifest()`; do not make per-host copied maps. Extend the existing
materializers rather than creating a second companion installation framework.
The `tools/render_skill_pack.py` show-reel provenance refresh is not automatically
a domain-manifest writer; wire audited domain provenance deliberately or have
each producer deliver validated canonical manifests before rendering.

## Routing and scope controls

Add unbranded English intervention requests that route to each new canonical ID,
and misleading vocabulary negatives. Explicit canonical/display-name invocations
are additional tests, not enough to satisfy natural-language skill reach.

| Owner | Positive request | Negative/control request |
| --- | --- | --- |
| GIS | Intersect these two GeoJSON layers in a metric CRS and compute overlap area. | Explain the map metaphor in this essay; only plot existing CSV totals without spatial computation. |
| Bio | Cross-check this public BRAF V600E/melanoma query across ClinVar and trial registry records, retaining disagreements and update dates. | Summarize one supplied paper (`paper-learning`); explain the word variant in a UI experiment; generic literature review (`research`). |
| Docking | Run rigid-receptor docking for these prepared PDBQT inputs and declared binding box, returning real poses and replay settings. | Repair a boat docking reservation; explain a molecular mechanism without computation; list papers about drugs. |

Use sibling vocabulary in deference prose to avoid `test_catalog_deference_policy`
inversions. GIS does not own generic `data-analysis`; Bio does not replace
`research`, `paper-learning`, the bundled bioinformatics skill or generic MCP
setup; docking does not own drug profiling or clinical treatment choices.
Korean requests must be exercised through existing host nomination/explicit
workflow handling without growing frozen Korean trigger tables. If natural Korean
routing is unsupported, report that limitation; do not disguise English lexical
fixtures as live Hermes semantic-routing evidence.

## Dependencies, provenance and isolated smoke recipes

Core registration/render/install tests use stdlib `unittest` and mocks only.
Optional libraries/binaries are installed **only** into task-owned demo envs.
Use Python 3.11/3.12 if native wheels do not support the repository's current
3.14 interpreter. Record exact resolved versions/installation commands, and keep
lock/freeze receipts outside the repo or in reviewed toolkit JSON if useful.

Agent/operator recipe (new shell environments, not instructions for normal users):

```sh
export TMPDIR=$HOME/.hermes/cache/scratch
# EVIDENCE is the task-owned evidence root named above.
uv venv --python 3.12 "$EVIDENCE/gis/venv"
uv pip install --python "$EVIDENCE/gis/venv/bin/python" geopandas shapely pyproj
uv venv --python 3.12 "$EVIDENCE/bio/venv"
uv pip install --python "$EVIDENCE/bio/venv/bin/python" biomcp-cli
uv venv --python 3.12 "$EVIDENCE/docking/venv"
uv pip install --python "$EVIDENCE/docking/venv/bin/python" vina
```

These are explicit optional setup recipes, not commands observed successful in
this contract node. Producers must run their helper commands from the preceding
sections using their isolated interpreter and actual input paths, capture real
exit codes, and write a reproducible command block in the domain report. BioMCP
must additionally save installed `--help`/version and execute the verified JSON
capture grammar. Docking must retrieve license-audited tutorial inputs explicitly
and run the full docking command; Vina build failure is a blocker, not proof a
ToolUniverse backend exists.

Observed license sources: GIS-MCP at
`be8a33d25aefccf256136f3de0f18124f6efa16f` is MIT, copyright 2025 Mahdi Nazari
Ashani; BioMCP at `a843629fb447750418cf746effe94010b1028a28` is MIT, copyright
2025 Ian Maurer; ToolUniverse at
`53b4f8eb48d304f947bab85182b88d7c2a5c6794` is Apache-2.0; AutoDock-Vina's
observed official LICENSE is Apache-2.0. Preserve per-file notices and upstream
NOTICE obligations if copying. A dependency's license is not a license to
redistribute arbitrary biomedical API captures. BioMCP's
`docs/reference/source-licensing.md` explicitly keeps captured provider fixtures
out of public build artifacts pending per-source rights. Retain live captures
outside the shipped pack; use original synthetic schema fixtures for offline
adapter tests. Record ClinVar accession/submitter context and trial identifiers,
source terms, retrieval timestamp and non-endorsement limitations.

Primary source locators, frozen by the revisions above: GIS-MCP `README.md` and
`LICENSE`; BioMCP `README.md`, `LICENSE`, `docs/reference/source-licensing.md`;
ToolUniverse exact registration/module paths in the docking section and
`src/tooluniverse/remote/boltz/README.md`; AutoDock-Vina
`docs/source/docking_python.rst`, `docs/source/docking_basic.rst`, `LICENSE` and
`example/python_scripting/`. The corresponding repositories are
`mahdin75/gis-mcp`, `genomoncology/biomcp`, `mims-harvard/ToolUniverse`, and
`ccsb-scripps/AutoDock-Vina` on GitHub. Freeze the actual downloaded bytes and
source digests in each producer's own provenance rather than relying on prose.

## Verification and hard completion gates

### Producer gates

- Definition/reference/support factories import without optional dependencies,
  side effects, subprocesses, network or toolkit-module imports.
- Dependency-free focused tests cover actual validation branches, wrong/missing
  inputs, dependency absence, no fabricated results, provenance inventory and
  script help. GIS covers missing CRS, invalid geometry and degree-unit rejection
  or valid reprojection. Bio covers schema mismatch, failed/missing sources,
  conflicting entity/context assertions and freshness. Docking covers malformed
  PDBQT/settings, non-finite values, resource caps and missing backend.
- Optional real-library tests are separate from mandatory offline tests; a mock
  engine cannot satisfy actual backend smoke. Each promised output is read back,
  hashed and reconciled with genuine stdout/return status. Timeouts are failures.
- Each handoff lists every changed path, literal commands and exit codes,
  version/license/input provenance, actual outputs, missing gates and precise
  downstream integration needs. No producer edits the shared files listed above.

### Integrator and verifier gates

1. All three focused unit suites pass without science dependencies in core.
2. Native/portable/tap/local-source inventories equal producer-derived
   `(canonical owner, relative path, sha256)` maps for actual resources. Do not
   flatten paths across owners: all three toolkits have `README.md`.
3. Test fresh install, unchanged upgrade, explicit force of edited owned files,
   refusal/preservation without force, unowned collisions, stale unchanged versus
   stale edited files, selective-owner update, legacy roots, symlinks, traversal,
   reserved paths, casefold collisions, undeclared and missing resources.
4. Build both wheel and sdist with `uv build --out-dir "$EVIDENCE/dist"`.
   Inspect archives and install/extract the wheel in a fresh isolated site.
   Run outside the checkout using `-I`/`-P`, remove source from import paths and
   deny checkout reads with the existing audit-hook pattern. Invoke actual
   built-package resource factories/materializers, not fixture bytes. Compare
   each domain's map across native, portable, tap producer and explicit local
   source; prove no companion import, socket or subprocess during materialization.
   Source-hidden means source-unavailable; six-host adapter parity is a separate
   additional check, not a substitute for this wheel proof.
5. Run six host adapter fresh/upgrade/edited/unowned checks against the single
   portable manifest. Preserve existing show-reel bytes and its safety coverage.
6. Run catalog shape, skill index/density/situations, procedures, routing positive
   and negative corpora, reach, deference, wrapper/action/card coverage, awareness,
   display/layout, digest, support/distribution and source-policy gates. Re-derive
   legitimate count/digest updates; never expand frozen exemptions.
7. Regenerate through `tools/render_skill_pack.py --write`, existing `docs`
   commands for workflows, roles, capability-families, skill-shortlist,
   agent-skills and demo case engine; run their `--check` gates, `docs navigation
   --check`, `release drift`, compileall, `git diff --check` and the full unittest
   suite with `PYTHONPATH=tests`. Follow current source pins over stale prose
   about how many fixtures changed.
8. Real GIS library execution, bounded live BioMCP retrieval and real docking
   execution must each have distinct evidence. A partial BioMCP source outage
   can be demonstrated truthfully but remains a named gap in two-source success.
   Missing actual docking blocks the complete three-skill claim. Independent
   verifier records PASS/FAIL/BLOCKED against every goal, not only old green tests.

### Contract-node observations (not producer acceptance)

CodeGraph executable was absent from PATH and `node_modules/.bin`; `.codegraph`
exists but no local executable was available. No global tool or index was
installed. Used bounded direct reads of the named sources instead.
Inspected peer definitions `show_reel_skill.py` and `decision_prototype_skill.py`,
reference/support factories, `skill_record.py`, native support materialization,
local-source conversion, portable support paths, and exact package-data entries.

Executed from the scoped checkout, each with exit **0**:

```sh
git status --short
# Empty at initial inspection; branch was hermes/domain-science-skills.
TMPDIR=$HOME/.hermes/cache/scratch PYTHONPATH=tests uv run python -m unittest tests/test_render_skill_pack.py tests/test_show_reel_support_files.py -q
# Ran 7 tests; OK.
TMPDIR=$HOME/.hermes/cache/scratch PYTHONPATH=tests uv run python -m unittest tests.test_show_reel_distribution.DistributionParityTests.test_record_native_and_portable_return_same_support_without_execution tests.test_show_reel_distribution.WheelSupportTests.test_built_wheel_contains_actual_companion_resources -q
# Ran 2 tests; OK, including actual built-wheel source-hidden support proof for existing show-reel.
```

The initial `uv run` created the ignored local `.venv` using CPython 3.14.7 and
built the existing project; it added no runtime science dependencies or tracked
package changes. Those passing existing tests establish the distribution seam,
not new-domain runtime or parity. No new skill implementation or science smoke
was performed by this contract node.
