---
name: "omh-molecular-docking"
description: "[omh] Prepared PDBQT inputs: run bounded standalone Vina docking with real poses, scores and replay provenance; never infer efficacy or safety. Use when the user says: molecular-docking, rigid-receptor docking, PDBQT docking, ligand docking poses, AutoDock Vina."
license: MIT
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, analysis]
    category: analysis
    phase: docking-validation
    role: operator
    quality_tier: evidence-gated
---

# Molecular Docking

This is an OMH `molecular-docking` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

Input validation and tutorial numbers are not measured docking. Require a real engine search and digest-bound poses, finite energies and replay settings.

## First Steps

- Read `toolkit/README.md` and `references/execution-and-qa.md`. Use the explicitly invoked standalone Vina Python helper, not an invented ToolUniverse tool or hidden core execution service.
- Recover prepared file paths, source/license and preparation receipts, angstrom binding box, seed, CPU, new output directory and host deadline. Never guess a site, silently prepare a molecule or install dependencies on skill load.
- Use `--validate-only` for dependency-free prerequisites, or explicitly invoke actual docking in an approved environment with a host-enforced timeout and stdout/stderr capture. Missing dependencies must refuse, not produce guessed findings.

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

## Completion Checklist

- Input/format/resource checks and exact input hashes are observed; source rights and preparation assumptions remain explicit.
- Actual poses, finite matching energies, backend version/settings, host logs/exit/deadline and replay manifest are read back, or the run is reported BLOCKED without invented results.

## Recovery Notes

- Preserve failed setup receipts. On this host, one authorized correction of the existing native build supplied CONDA_DEFAULT_ENV as well as CONDA_PREFIX/PATH, then Vina 1.2.7 built and the real 1IEP smoke passed; this is not a promise for other platforms.
- If a native run fails or times out, retain its logs and partial files without a success claim; review the backend failure before retrying in a new output directory.



## When to Use

Use when prepared receptor/ligand files and an explicit binding box need a bounded rigid-receptor computational run.

    Strong routing signals: `molecular-docking`, `rigid-receptor docking`, `PDBQT docking`, `ligand docking poses`, `AutoDock Vina`

## Catalog Metadata

Category: `analysis`
Phase: `docking-validation`
Quality tier: `evidence-gated`
Reasoning demand: `standard`

Quality bar:

- Reject symlinks, existing output directories, unsupported formats, non-finite inputs and resource-cap violations before output writes. Preserve existing user files and keep failed-run partial files distinct from success manifests.
- Retain actual setup and runtime errors. Never fill a missing backend gate with tutorial numbers, fake poses, optimizer output or a success stub.

Required inputs:

- prepared receptor and ligand PDBQT paths
- binding box and preparation provenance
- approved local resource budget

Expert clarification questions:
- `prepared receptor and ligand PDBQT paths`
  - English: Which prepared, rights-cleared single-ligand and rigid-receptor PDBQT files are authorized?
  - Korean: Which prepared, rights-cleared single-ligand and rigid-receptor PDBQT files are authorized?

Expected outputs:

- molecular_docking_preflight/v1
- molecular_docking_run/v1 and real pose/score files

Artifact expectations:

- Keep raw inputs, stdout/stderr and pose/score files in the approved evidence directory, outside metadata-only OMH state. Preflight/run/score JSON schemas are standalone file contracts, not new registered operations artifacts.

Safety rules:

- Never infer efficacy, safety, affinity certainty, target validation, dosing or treatment advice. PDBQT syntax validation is not chemical validity or a preparation review.
- No hidden execution, network, credentials, global install or paid compute. Dependencies are optional and task-isolated; discovery, routing and skill installation never execute the helper.
- ToolUniverse registrations were inspected, not invoked. This toolkit uses standalone AutoDock Vina Python only; do not invent a ToolUniverse adapter or tool name.

Procedure: load `references/procedure.md`.

## Runtime Evidence

Use the current host's own tools and subagent/task mechanism when available;
otherwise run the same lanes sequentially or name the unavailable capability.
A prepared plan, handoff, checklist, or skill installation is not execution,
review, CI, merge-readiness, or merge evidence. Record actual tool results, or
`not_observed` / `not_available`, in the record; never invent dispatch or host
accounting.
Treat supplied context as advisory, not proof of hidden memory reads or writes.
State scope, constraints, verification, and the stop condition before work.
Reply in the user's own words and the host's own voice: the host's persona owns
reply language, tone, speech level, and sentence endings, progress updates
included (where it sets no language, use the one the user wrote in), and OMH
shapes structure and content only; OMH's record terms
(surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in
records and tool calls, never in the sentence the user reads unless they ask
about one; and when a real unresolved user decision or a useful briefing discussion
remains, offer one specific, content-linked question. Completed work needs no question;
omit unrelated non-action footers and generic offers to continue.
Supporting paths are relative to this skill directory; sibling skill paths are
relative to its parent. Resolve them from the host-provided skill base directory
(`{baseDir}` on hosts that provide it), never a hardcoded install location.
A named workflow not installed here is unavailable, not permission to emulate
its host-specific capabilities. Verify through the real surface before done.
