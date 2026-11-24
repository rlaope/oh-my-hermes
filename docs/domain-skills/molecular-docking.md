# Molecular docking: observed standalone Vina execution

## Producer verdict

The historical real standalone Vina smoke below remains genuine. Independent
review subsequently found V-02: global record counts accepted corrupt models
as success. The scoped per-model repair is documented at the end of this report;
the earlier smoke is not proof that the old validator rejected corruption.
This is not a ToolUniverse adapter, publication, installed Hermes skill or proof
of final integration/distribution parity. Shared acceptance remains with the
parent/integrator and independent verifier; no complete-goal PASS is claimed.

The toolkit now validates prepared PDBQT inputs and runs actual Vina `dock()`,
then writes nonoverwriting poses, finite engine energies and a replay manifest.
`--validate-only` remains dependency-free and explicitly not docking. Missing
Vina exits 3 with no output directory; validation/engine/readback failures are
nonzero, never success stubs. Existing inputs/results are preserved.

## One bounded correction, not a third installation strategy

Earlier receipts remain unmodified under the task's external `docking/`
evidence directory. The wheel-only attempt found no macOS arm64 Vina 1.2.7
wheel. The existing native Boost/SWIG environment's first build failed with
`ValueError: Boost library location was not found!`. That attempt supplied
CONDA_PREFIX/PATH, but omitted CONDA_DEFAULT_ENV.

The pinned upstream audit and **actual PyPI 1.2.7 source** both implement:

```python
def in_conda():
    return 'CONDA_DEFAULT_ENV' in os.environ.keys()
```

The downloaded PyPI source archive matched its published SHA-256. Its setup.py
was byte-identical to the prior audit and to the exact source in the corrected
uv build cache. One parent-authorized correction reused the existing native
environment with CONDA_DEFAULT_ENV, CONDA_PREFIX and PATH all set. The native
build exited **0** in 16.708 seconds. No Docker daemon, global package, paid
service, new provider or different installation strategy was used.

Operator reproduction of that observed correction (existing environment only):

```sh
export TMPDIR=$HOME/.hermes/cache/scratch
export EVIDENCE=$HOME/.hermes/cache/scratch/omh-domain-dag-evidence-20261022/docking
CONDA_DEFAULT_ENV="$EVIDENCE/build-env" CONDA_PREFIX="$EVIDENCE/build-env" \
  PATH="$EVIDENCE/build-env/bin:$PATH" UV_CACHE_DIR="$EVIDENCE/repair-uv-cache" \
  uv pip install --python "$EVIDENCE/build-env/bin/python" vina==1.2.7
```

A host subprocess wrapper imposed a 600-second build deadline. Environment:
macOS 26.5.1 arm64, Python **3.12.15**, Boost **1.85.0**, SWIG **4.5.1**,
Vina **1.2.7**, NumPy **2.5.4**. `repair-native-build.json/.log`,
`repair-source-audit.json`, `repair-actual-build-source.json` and
`repair-package-freeze.log` retain exact observed commands/versions.
`setup-attempts.json` remains the historical BLOCKED receipt, not current status.

## Actual bounded helper run and independent output readback

The final smoke ran at **2026-10-22T11:30:47Z**, exited **0** in **3.240 s**,
under a real **180-second host timeout**:

```sh
"$EVIDENCE/build-env/bin/python" -I \
  src/skills/molecular_docking_toolkit/scripts/dock.py \
  --receptor "$EVIDENCE/inputs/1iep_receptor.pdbqt" \
  --ligand "$EVIDENCE/inputs/1iep_ligand.pdbqt" \
  --center 15.190 53.903 16.917 --box-size 20 20 20 \
  --cpu 1 --seed 20261022 --exhaustiveness 1 --n-poses 1 \
  --host-timeout-seconds 180 --output-dir "$EVIDENCE/repair-final-smoke"
```

The host used `subprocess.run(..., timeout=180, stdout=..., stderr=...)`;
`--host-timeout-seconds` is only a recorded declaration, never an unsupported
claim of Python interrupting native code. The helper lazily imports Vina and
calls set_receptor, set_ligand_from_file, compute_vina_maps, actual dock,
energies and write_poses(overwrite=False). No optimize-only or score-only
substitute is used.

Independent host readback verified one balanced MODEL/ENDMDL, **41 ligand
atoms with finite coordinates**, all input/output/helper hashes and finite
five-column Vina energies in kcal/mol:

```text
[total, inter, intra, torsions, intra_best_pose]
[-10.871, -15.320, -0.967, 4.449, -0.967]
```

The saved `REMARK VINA RESULT` total was **-10.871 kcal/mol**, matching the
engine record within 0.001. Stdout contains the actual seeded docking progress
and affinity table; stderr is empty. A replay from manifest argv, changing only
the output directory, exited **0** in **3.333 s** under another 180-second cap.
Pose and score bytes were equal on this same version/platform; no universal
cross-platform determinism is claimed.

Final artifacts live in `repair-final-smoke/` and `repair-final-replay/`;
`repair-final-execution-verification.json` hashes each input, pose, score,
manifest, stdout/stderr and host receipt. Earlier successful exploratory
receipts and all failed-attempt receipts remain external and intact.

## Source and result provenance

Official tutorial/API/license/input revision:
`ccsb-scripps/AutoDock-Vina@bb64e5e26b520569a86360d69248069b5e665b3f`.
Sources and exact URLs are preserved in `sources/retrieval.json`. No upstream
molecular input, binary or raw result file is bundled in the toolkit.

| Bytes | SHA-256 |
| --- | --- |
| 1IEP receptor, 216188 bytes / 2702 atoms | `761469710e3915b89b274483076dfe49754be7956661bc42f4cc36a182399d59` |
| 1IEP ligand, 3630 bytes / 41 atoms | `37a20e58e77072c6b3ff07f285a345e647dd4e564af316a06e49518b15b7aa61` |
| Upstream Apache-2.0 LICENSE | `cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30` |
| PyPI Vina 1.2.7 source archive | `79e5288d10207b85f20adac3dd6f4708eac761c2d8070fbad76ff997cf48e4f9` |
| Actual upstream/PyPI/build-cache setup.py | `bd9bc6a60c3ff03ad5fd395941898c76c18fdce3f0258a37aa65b4ffe57a8d41` |
| Historical smoke helper before V-02 repair | `56265b02719313f817cc4d1e2b56b50f5e194df20a7477f79e5772c17a16bf39` |
| Final pose, 3849 bytes | `121d02cca19d3d5ae9073fed722ae25524991abeab5887631f901b5249e8923d` |
| Final scores.json | `f7f5ae01336211c6834415c1e86e69f2ccac050c5fdbfb81bdd5ec3444cd005e` |
| Historical smoke manifest.json | `25630a4af45107986051b1f71a418eeb88f766def07ddba61ea82bdf1d6b8b99` |

ToolUniverse revision `53b4f8eb48d304f947bab85182b88d7c2a5c6794` was inspected,
not executed: `NvidiaNIM_diffdock` is a NVIDIA NIM route;
`ClusPro_submit_peptide_docking` submits peptide jobs; `boltz2_docking` is a
remote registration whose README requires Linux/CUDA. None establishes a
credentialless local Vina integration. The original MIT helper and guidance
remain correctly attributed, with closed per-resource provenance validation.

## Verification observed

All commands inherited the approved scratch TMPDIR and ran from the scoped
checkout, branch `hermes/domain-science-skills`. Exact argv, output, exit codes,
parsed test IDs and hashes are in `repair-verification-receipt.json` and logs:

```sh
PYTHONPATH=tests uv run python -m unittest tests.test_molecular_docking_skill -v
# Exit 0: 13 tests enumerated; 12 passed, 1 optional native test skipped.
VINA_TEST_INPUT_DIR="$EVIDENCE/inputs" "$EVIDENCE/build-env/bin/python" \
  -m unittest tests.test_molecular_docking_skill.NativeDockingTests -v
# Exit 0: actual native test passed, including nonoverwrite refusal.
PYTHONPATH=tests uv run python -m unittest \
  tests.test_handoff_safety_contract_enforcement tests.test_broad_exception_policy -v
# Exit 0: all 41 enumerated test IDs passed; no allowlist changes.
uv run --group lint ruff check src/skills/molecular_docking_skill.py \
  src/skills/molecular_docking_toolkit/scripts/dock.py tests/test_molecular_docking_skill.py
# Exit 0: All checks passed.
uv run python -m compileall -q src/skills/molecular_docking_skill.py \
  src/skills/molecular_docking_toolkit/scripts/dock.py tests/test_molecular_docking_skill.py
# Exit 0.
git diff --check -- src/skills/molecular_docking_skill.py \
  src/skills/molecular_docking_toolkit tests/test_molecular_docking_skill.py \
  docs/domain-skills/molecular-docking.md
# Exit 0.
```

Focused contracts cover malformed PDBQT, non-finite inputs/energies, resource
caps, unsafe/missing paths, preservation, missing dependency, malformed engine
pose refusal without a success manifest, help, factories, procedure references
and provenance tampering. Corrupted backend fixtures are refusal tests only,
never evidence of real docking. Test-first observed failures caught the old
permanent blocker and an unhandled malformed VINA RESULT record; both were
corrected and rerun green. A harness initially miscounted multiline unittest
docstrings; it was corrected to count leading test IDs independently, then
cross-checked against testsRun. That was not a source-policy test failure.

Actual isolated no-Vina CLI checks separately returned help **0** and missing
dependency **3**, without traceback/output directory (`repair-refusal-receipt.json`).
Every hash in the historical setup receipt was rechecked unchanged.

## Integration-owned work and limitations

Public exports and the exact closed inventory are unchanged:
`README.md`, `NOTICE.md`, `scripts/dock.py`, `examples/settings.json`,
`upstream-manifest.json`. Parent/integrator must wire/regenerate shared catalog,
reference/support factories, owner-filtered materialization/converter, portable
paths/package data/LF policy, routing/actions/cards/awareness, projections and
count/digest fixtures per `implementation-contract.md`. No shared files,
projections, commits, live installs or safety allowlists were changed here.

Native/portable/tap/local-source and source-hidden wheel/sdist parity, the full
repository suite and an independent verifier verdict are not claimed by this
producer. Prepared input syntax is not chemical preparation validity. The
observed engine score is not affinity certainty, efficacy, safety, clinical
utility or dosing evidence.

## V-02 follow-up: validate every pose model and atom

Independent review correctly reproduced false success in the old global-count
readback with a synthetic corrupt backend. This was a validator defect, not a
claim that the historical actual Vina pose was corrupt. The original verifier
and `negative_cases.py` remain unchanged.

The repaired helper parses sequential, balanced, nonnested MODEL/ENDMDL records
and requires exactly one valid VINA RESULT per model. All three score fields
must be finite, RMSDs nonnegative, and each total must match the corresponding
actual five-column backend energy row in model order within an absolute
0.001 kcal/mol (`rel_tol=0`). Every model is separately passed through the
fixed-column ligand structure parser: nonempty atoms, finite bounded x/y/z,
valid charge/type, positive unique serials, balanced ROOT/BRANCH and TORSDOF.
Serial-keyed record/name/residue/chain/insertion/charge/type identities and the
atom count must match the prepared ligand; coordinates and atom order may change.
Missing, duplicated, extra or changed atoms fail. A saved pose file is capped
at 4 MiB. All models are checked before `scores.json` or a success manifest is
written. Failed output may remain as diagnostics, never a completed run.

SHA-256 binds observed bytes; hashing corrupt backend output proves neither
structural nor scientific validity. Syntax checks and energy reconciliation do
not certify chemical preparation, affinity certainty, efficacy or safety.

New evidence lives only under
`omh-domain-dag-evidence-20261022/repair-verify/docking-pose-fix/`:

- Test-first `PoseValidationTests`: initial run **exit 1**, eight test methods
  with **54 failing subtest/assertion events**, exposing accepted NaN/Inf or
  malformed coordinates, empty models, redistributed/misplaced scores,
  nesting/unbalanced order, and wrong/missing/duplicate/extra atom identities.
  A separate malformed-additional-score regression failed first (**exit 1**,
  one method / two subtest failures), then was repaired. These are corruption
  fixtures only, never native-execution evidence.
- Final focused command: **exit 0**, **68 tests, one optional native skip**,
  including all nine new pose-validation methods, existing docking contracts,
  handoff source-safety, broad-exception policy and module-patch policy.
  `commands.jsonl` records exact argv, cwd, environment, exits, stream hashes
  and enumerated test IDs. `ruff`, scoped `compileall` and diff hygiene exit 0.
- The unchanged independent V-02 test body passes against the canonical repaired
  source (**one test**), with only path/output globals rebound in memory to
  this task-owned evidence directory. This is not an installed-wheel recheck.
- Existing optional native test remains green (**exit 0, one real test**) using
  the already-installed Vina 1.2.7 build environment, with no install performed.
- Retained real smoke and replay each exit **0**, under separate **180-second**
  host deadlines, using the same pinned inputs, CPU 1, seed 20261022 and
  exhaustiveness 1. Independent readback checks every coordinate, unique serial
  and ligand identity, per-model energy and manifest input/output/helper hash.
  Both have **one 41-atom model, total -10.871 kcal/mol**, and pose/score bytes
  equal both each other and the historical successful run. A separate request
  for two poses also exits 0 but returns **one** filtered model; no real
  multi-model result is claimed. Valid multiple-model handling is covered by
  explicitly synthetic fixtures.

Current helper SHA-256:
`6439478a365f94ff7a68dfc50b1ee7bba1ec54f64ba7a1b12bc6481fb4fa0f9e`.
`upstream-manifest.json` now binds the changed helper/README bytes while retaining
historical native-smoke metadata and pinned inspected-source provenance.
New smoke manifest SHA-256:
`3bff66360b7260e172eb05adbfbe9f5d7232dbfac411c888ab0bca34ba1b4307`.
Exact smoke/replay/two-request readback is in `runtime-readback.json`.

This scoped fix changes no shared generated pack/inventory, dependency,
allowlist, version, backend identity or historical result. The parent must
regenerate the changed reference/toolkit projections, rebuild distribution and
rerun installed/source-hidden parity and independent acceptance. Full-suite
completion/accounting, live Hermes and Windows remain separate unresolved
acceptance gates; the earlier full-suite failures/timeouts are not superseded.
