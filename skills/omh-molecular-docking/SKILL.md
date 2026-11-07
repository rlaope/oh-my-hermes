---
name: "omh-molecular-docking"
description: "[omh] Prepared PDBQT inputs: run bounded standalone Vina docking with real poses, scores and replay provenance; never infer efficacy or safety. Use when the user says: molecular-docking, rigid-receptor docking, PDBQT docking, ligand docking poses, AutoDock Vina."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, analysis]
    category: analysis
    phase: docking-validation
    role: operator
    quality_tier: evidence-gated
    related_skills: [ulw-research, omh-paper-learning]
---

# Molecular Docking

Required: prepared receptor and ligand PDBQT paths, binding box and preparation provenance, approved local resource budget. Output: molecular_docking_preflight/v1, molecular_docking_run/v1 and real pose/score files.

**HOLD:** Missing inputs or failed contract gates. Prepared OMH routing is not execution or approval.

## Why This Exists

Input validation and tutorial numbers are not measured docking. Require a real engine search and digest-bound poses, finite energies and replay settings.

## First Steps

- Read `toolkit/README.md` and `references/execution-and-qa.md`. Use the explicitly invoked standalone Vina Python helper, not an invented ToolUniverse tool or hidden core execution service.
- Recover prepared file paths, source/license and preparation receipts, angstrom binding box, seed, CPU, new output directory and host deadline. Never guess a site, silently prepare a molecule or install dependencies on skill load. If the person has a SMILES or a PDB id rather than PDBQT, stop and list the preparation steps they must approve (protonation state, charges, tautomer, receptor cleanup, box) with a named converter such as Meeko or ADFR; do not convert silently.
- Use `--validate-only` for dependency-free prerequisites, or explicitly invoke actual docking in an approved environment with a host-enforced timeout and stdout/stderr capture. Missing dependencies must refuse, not produce guessed findings.

Contract: `references/full-contract.md`, loaded before analysis. Procedure: `references/procedure.md`. These are working methods, not an OMH runtime operation.

## Safety Rules

- Never infer efficacy, safety, affinity certainty, target validation, dosing or treatment advice. PDBQT syntax validation is not chemical validity or a preparation review.
- No hidden execution, network, credentials, global install or paid compute. Dependencies are optional and task-isolated; discovery, routing and skill installation never execute the helper.
- ToolUniverse registrations were inspected, not invoked. This toolkit uses standalone AutoDock Vina Python only; do not invent a ToolUniverse adapter or tool name.
- Exhaustiveness is capped at 4 here (Vina's default is 8): treat energies as one under-sampled run, never as a ranking or a comparison across ligands. Before reporting a site, redock the co-crystal ligand when one exists and report its pose RMSD to the crystal pose; with none, say the site is unvalidated.

## When to Use

Use when prepared receptor/ligand files and an explicit binding box need a bounded rigid-receptor computational run.

Strong routing signals: `molecular-docking`, `rigid-receptor docking`, `PDBQT docking`, `ligand docking poses`, `AutoDock Vina`

## Catalog Metadata

Category: `analysis`
Phase: `docking-validation`
Hermes role: `operator`
Quality tier: `evidence-gated`

## Completion Checklist

- Input/format/resource checks and exact input hashes are observed; source rights and preparation assumptions remain explicit.
- Actual poses, finite matching energies, backend version/settings, host logs/exit/deadline and replay manifest are read back, or the run is reported BLOCKED without invented results.

## Recovery Notes

- Preserve failed setup receipts. PyPI ships Vina 1.2.7 wheels only for x86_64 Linux, so macOS arm64 needs a source build with Boost and SWIG, and its setup.py checks CONDA_DEFAULT_ENV, not only CONDA_PREFIX. If the build fails, return the failure log and do not retry blindly; the observed 1IEP smoke is one platform, not a promise for others.
- If a native run fails or times out, retain its logs and partial files without a success claim; review the backend failure before retrying in a new output directory.

## Workflow Lane

- Current lane: **Research and company ops** (`product-docs`, `source-finder`, `web-research`, `research`, `model-optimization`, `inference-serving`, `model-finetuning`, `research-brief`, `+28 more`) - research, signals, ops, and briefings.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## Runtime Evidence

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only; OMH's record terms (surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in records and tool calls, never in the sentence the user reads unless they ask about one; and when a real unresolved user decision or a useful briefing discussion remains, offer one specific, content-linked question. Completed work needs no question; omit unrelated non-action footers and generic offers to continue.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
