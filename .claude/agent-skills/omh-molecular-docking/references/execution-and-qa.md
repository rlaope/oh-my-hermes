# Explicit standalone Vina execution and QA

Read `toolkit/README.md` before invoking `toolkit/scripts/dock.py`. Nothing
executes or installs on discovery. Python 3.11+ suffices for --help/preflight;
actual docking requires the optional Vina package in the chosen environment.

## Backend identity and source provenance

ToolUniverse was inspected at `53b4f8eb48d304f947bab85182b88d7c2a5c6794`:
`src/tooluniverse/tools/NvidiaNIM_diffdock.py` forwards NVIDIA NIM requests;
`ClusPro_submit_peptide_docking.py` submits peptide jobs, not completed
small-molecule poses; `src/tooluniverse/data/remote_tools/boltz_tools.json`
registers `boltz2_docking`, whose remote README requires Linux/CUDA. None was
invoked. No ToolUniverse Vina tool is invented. The backend here is explicitly
standalone AutoDock Vina Python, not ToolUniverse integration.

Official Vina tutorial/API/Apache-2.0 license and 1IEP inputs were inspected at
`bb64e5e26b520569a86360d69248069b5e665b3f`; input bytes remain in external
evidence, not bundled. The tutorial box is center 15.190 53.903 16.917, sides
20 20 20 angstrom; never reuse that site for another target without justification.
The closed provenance manifest records reviewed source revisions/hashes.

## Explicit operator invocation

Use installed skill-relative paths. The host must enforce a real finite timeout
for the whole command and capture stdout/stderr, argv, UTC times and exit status:

```sh
python toolkit/scripts/dock.py --receptor RECEPTOR.pdbqt --ligand LIGAND.pdbqt \
  --center 15.190 53.903 16.917 --box-size 20 20 20 \
  --cpu 1 --seed 20261022 --exhaustiveness 1 --n-poses 1 \
  --host-timeout-seconds 180 --output-dir NEW_DIRECTORY
```

--host-timeout-seconds records the outer deadline contract; it cannot safely
interrupt native code itself. Add --validate-only for dependency-free preflight,
which writes preflight.json and execution_status not_observed, never poses/scores.
Ordinary execution lazily imports Vina, calls set_receptor/set_ligand_from_file,
compute_vina_maps, actual dock(), energies() and nonoverwriting write_poses().
Missing/unusable optional dependencies exit 3 without creating the output
directory. Invalid inputs or execution/readback failures exit 2; partial files
from a failed native run are not success and no success manifest is written.

## Validation and evidence gates

Require ASCII fixed-column PDBQT with finite coordinates/charge and supported
atom types, one ligand with balanced ROOT/ENDROOT, BRANCH/ENDBRANCH and final
TORSDOF, and a rigid receptor. Reject PDB/SDF, multi-model and flexible-receptor
inputs, duplicate serials and unsafe/existing output paths. Caps: 4 MiB per
input, 30000 receptor atoms, 128 ligand atoms, 16 branches/TORSDOF; CPU 1-2,
positive seed up to 2147483647, exhaustiveness 1-4, poses 1-5, box sides 1-24
angstrom, host deadline 1-180 seconds. Never silently convert or repair.
Protonation, charge assignment, tautomer, stereochemistry, missing atoms,
cofactors, preparation validity and the binding site still require domain review.

Read poses.pdbqt, scores.json and manifest.json. Every sequential MODEL must
close before the next begins, contain exactly one valid VINA RESULT record and
nonempty fixed-column atoms with finite coordinates. Each model must retain
the ligand's unique serial-keyed atom identities/count (record kind, name,
residue/chain/insertion identity, charge and type), without missing/extra atoms.
Require finite five-column Vina energies in kcal/mol, matching each saved total
to its engine row in model order within an absolute 0.001, with finite
nonnegative RMSDs. The helper parses and reconciles all models before writing
scores.json or a success manifest; corrupt poses remain failed-run diagnostics.
Input/output/helper SHA-256 hashes bind bytes, not scientific validity. Require
engine version/platform, seed, all settings and replay argv. Preserve host raw
logs and the deadline/exit receipt alongside outputs. For replay, change only
--output-dir to a new path and rerun under the host deadline. Reconcile outputs
rather than promising universal byte identity across versions/platforms.
The manifest records fixed grid spacing, energy range, RMSD, refinement and
heuristic max_evals defaults plus engine.info(). It does not hash itself;
external host evidence should hash the manifest and logs.

## Observed bounded smoke, not biological validation

The first wheel-only setup failed on macOS arm64. The existing Boost 1.85/SWIG
native environment initially failed to locate Boost because upstream in_conda()
checks CONDA_DEFAULT_ENV, which was absent. Actual PyPI 1.2.7 source matched the
pinned setup audit. One authorized correction supplied CONDA_DEFAULT_ENV,
CONDA_PREFIX and PATH; the same native build succeeded. Earlier errors remain
preserved; no Docker, global package, paid service or third installation strategy
was used. Python 3.12.15, Vina 1.2.7 and NumPy 2.5.4 ran the real 1IEP helper
with CPU 1, seed 20261022, exhaustiveness 1 and one pose under a 180-second host
cap. Saved 41-atom pose total -10.871 kcal/mol matched engine energies. A second
same-host seeded run produced equal pose/score bytes; this is only that observed
version/platform. It is not ToolUniverse execution, chemical preparation review,
affinity certainty, efficacy, safety, clinical utility or a dosing conclusion.
