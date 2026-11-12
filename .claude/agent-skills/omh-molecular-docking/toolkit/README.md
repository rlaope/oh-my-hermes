# Standalone molecular docking toolkit

Explicitly invoked `scripts/dock.py` validates prepared local PDBQT inputs,
then runs the optional **AutoDock Vina Python API** to produce real poses,
finite scores and a replay manifest. This is not ToolUniverse integration.
Skill discovery, routing and installation never import Vina or run this helper.
No dependency, binary, molecular input or result file is bundled or auto-installed.

## Operator interface

Python 3.11+ and stdlib suffice for `--help` and `--validate-only`. For actual
docking, explicitly provision Vina in an approved isolated environment, using
its official installation instructions for the target platform. The observed
smoke used Python 3.12.15, Vina 1.2.7 and NumPy 2.5.4 on macOS arm64; wheel
availability and native-build requirements differ elsewhere. No core OMH
science dependency is required. Use installed skill-relative paths:

```sh
python toolkit/scripts/dock.py --receptor RECEPTOR.pdbqt --ligand LIGAND.pdbqt \
  --center 15.190 53.903 16.917 --box-size 20 20 20 \
  --cpu 1 --seed 20261022 --exhaustiveness 1 --n-poses 1 \
  --host-timeout-seconds 180 --output-dir NEW_DIRECTORY
```

**The host terminal must enforce a real finite timeout** and capture stdout,
stderr, exact argv, start/end times and exit status. The timeout flag is a
recorded contract, not a native-code interruption mechanism. For example, a
host Python `subprocess.run(argv, timeout=180, stdout=..., stderr=...)` wrapper
can bound this explicit standalone command; the shipped helper itself never
spawns a process. A host timeout is failure, not a partial success.

Supply rights-cleared files, preparation receipts and an explicitly justified
binding box. The example box is from the official 1IEP tutorial, not a general
binding-site inference. `examples/settings.json` documents bounded settings,
not an engine input file or result. Flags are authoritative.

### Outputs and exit status

- Exit **0**, ordinary invocation: `poses.pdbqt`, `scores.json`, `manifest.json`.
  The helper calls actual `dock()`, not `score()` or `optimize()`, and writes
  poses with `overwrite=False` into an exclusively new output directory. Saved
  models are parsed structurally: nonnested sequential MODEL/ENDMDL pairs,
  exactly one valid VINA RESULT record per model, nonempty finite fixed-column
  atoms, and unique atom serials/identities/counts matching the prepared ligand.
  Record kind, name, residue/chain/insertion identity, charge and AutoDock type
  must be retained; coordinates may move and atom order may change. All three
  score fields must be finite, RMSDs nonnegative, and each total must match its
  corresponding finite five-column engine energy row within an absolute
  0.001 kcal/mol. Validation of every model precedes scores/success publication.
  The manifest records input/output/helper SHA-256,
  byte/atom counts, Vina/Python versions, platform, seed, complete settings,
  engine.info(), UTC times and absolute replay argv. Host logs/receipt are
  external evidence and should be hashed with the manifest after exit.
- Exit **0**, `--validate-only`: only `preflight.json`, with syntax/resource
  checks, input hashes and `execution_status: not_observed`. It never imports
  Vina or writes poses/scores. Preflight is not docking or chemical validation.
- Exit **2**: invalid inputs/settings/paths or an engine/output reconciliation
  failure. A failed native run can leave partial files in its newly created
  output directory, but no success manifest. Preserve them for diagnosis;
  never treat them as a completed run or overwrite a previous result.
- Exit **3**: missing/unusable optional Vina dependency; no output directory
  is created and nothing is installed. `--help` does not need Vina.

Read all output files and compare hashes against the actual input bytes. For a
replay, take `replay_argv`, replace the value after `--output-dir` with a **new**
path and rerun under the host deadline, capturing a new receipt. Seeded equality
is bounded by engine/platform; do not promise universal byte-identical results.
A requested pose count is an upper bound; filtering can yield fewer poses.
Hashes bind the observed bytes; hashing corrupt engine output does not prove
structural, chemical or scientific validity. The parser checks above are a
separate prerequisite, not a replacement for preparation and domain review.

## Validated subset and resource limits

Inputs must be ASCII, fixed-column PDBQT with finite coordinates/charge and
supported AutoDock atom types. The receptor is rigid (ATOM/HETATM plus
REMARK/TER/END); one ligand requires balanced ROOT/ENDROOT, BRANCH/ENDBRANCH
and final TORSDOF. Reject flexible receptors, multi-model inputs, PDB/SDF,
missing charge/type, duplicate serials, symlink components and existing output
directories; the only links accepted are macOS's own `/etc`, `/tmp` and `/var`
into `/private`. The output parent must already exist. No conversion or silent
repair occurs. Parsing cannot certify protonation, stereochemistry, tautomer,
charge preparation, missing atoms, receptor state or binding-site validity.

Caps: 4 MiB/input; 30000 receptor atoms; 128 ligand atoms; 16 branches/TORSDOF;
CPU 1-2 (never 0/all CPUs); seed 1-2147483647; exhaustiveness 1-4; poses 1-5;
finite bounded center; each box side 1-24 angstrom; host deadline 1-180 seconds.
Fixed settings are grid spacing 0.375 angstrom, force_even_voxels False,
no_refine False, verbosity 1, min_rmsd 1.0 angstrom, energy_range 3.0 kcal/mol
and max_evals 0 (engine heuristic). The outer deadline bounds total work.
This is not a hardened service for concurrently attacker-mutated filesystems.

## Observed smoke and setup correction

The prior wheel-only Vina 1.2.7 attempt had no usable macOS arm64 wheel. An
existing task-local Boost 1.85/SWIG native environment initially failed to find
Boost. The actual PyPI setup.py is byte-identical to the upstream audit and
checks `CONDA_DEFAULT_ENV`, not just `CONDA_PREFIX`. One explicitly authorized
correction supplied all of `CONDA_DEFAULT_ENV`, `CONDA_PREFIX` and `PATH` to
that same native build; it succeeded. Earlier failure receipts remain intact.
No new package strategy, Docker daemon, global install or paid service was used.

The real helper then ran official pinned 1IEP inputs with CPU 1, seed 20261022,
exhaustiveness 1, one pose and a 180-second host deadline. Readback found a
41-atom pose and total **-10.871 kcal/mol**, matching the engine energies. A
same-version/platform replay produced equal pose/score bytes. This is measured
standalone execution, not copied tutorial output, mock-engine evidence or
ToolUniverse execution. See `references/execution-and-qa.md` and the domain
report for setup/input/output hashes and acceptance boundaries.

`upstream-manifest.json` validates the closed original MIT resource inventory
and records pinned inspected sources; tutorial input/result files are external,
not shipped. Never infer affinity certainty, efficacy, safety, clinical utility,
dosing or treatment advice from docking scores.
