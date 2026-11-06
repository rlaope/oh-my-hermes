# Molecular Docking

Load this on-demand contract after the compact `molecular-docking` body identifies the
workflow. The main body owns routing signals, shared rules, the runtime
operation, delegation fallback, and completion/recovery pointers; this file
holds the workflow-specific detail without copying those shared rails.

## Do Not Use When

- A general literature question belongs to `ulw-research`; one supplied paper belongs to `omh-paper-learning`.
- A boat reservation, molecular mechanism explanation without computation, drug recommendation or clinical decision is outside this scope.

## Examples

Good example:

- Prompt: Run these prepared PDBQT inputs in this declared box with one CPU and fixed seed, preserving actual poses and replay settings.
- Expected behavior: Validate inputs, run the explicit optional Vina helper under a host deadline, then read back poses/scores/hashes and state limitations.
- Why: Actual engine output is distinguishable from preflight and source inspection.

Bad example:

- Prompt: These scores prove the compound is safe and effective; recommend a dose.
- Expected behavior: Reject the unsupported inference and do not produce clinical advice.
- Why: Computational score evidence cannot establish those claims.

## When to Use

Routing signals: `molecular-docking`, `rigid-receptor docking`, `PDBQT docking`, `ligand docking poses`, `AutoDock Vina`

## Workflow Contract

Category: `analysis`
Phase: `docking-validation`
Hermes role: `operator`
Quality tier: `evidence-gated`
Reasoning demand: `standard`

Quality bar:

- Reject symlinks, existing output directories, unsupported formats, non-finite inputs and resource-cap violations before output writes. Preserve existing user files and keep failed-run partial files distinct from success manifests.
- Retain actual setup and runtime errors. Never fill a missing backend gate with tutorial numbers, fake poses, optimizer output or a success stub.

Handoff policy:

Keep framing and evidence assessment with the host. Report actual docking only after reading genuine pose/score/version/log/hash/replay evidence. Optional dependency or native failures remain BLOCKED for that run; preflight, source inspection and a successful install alone are not execution. No ToolUniverse execution is claimed.

Required inputs:

- prepared receptor and ligand PDBQT paths
- binding box and preparation provenance
- approved local resource budget

Expected outputs:

- molecular_docking_preflight/v1
- molecular_docking_run/v1 and real pose/score files

Artifact expectations:

- Keep raw inputs, stdout/stderr and pose/score files in the approved evidence directory, outside metadata-only OMH state. Preflight/run/score JSON schemas are standalone file contracts, not new registered operations artifacts.

Detailed procedure steps: `references/procedure.md`.
