# Skill Eval

Load this on-demand contract after the compact `skill-eval` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The ask is a dashboard of the whole skill portfolio's drift, stale surfaces or pending amendments; use `omh-skill-health`.
- The ask is finding an existing skill to adopt before writing one; use `omh-skill-scout`.
- The ask is comparing coding agents or models on the same task; use `omh-agent-evaluation`.
- OMH itself is not installed or its skills do not appear at all; use `omh-doctor`.

## Examples

Good example:

- Prompt: I wrote a skill in ./my-skills/pdf-tables. Will it load in Claude Code and Codex?
- Expected behavior: Run `omh skill-eval ./my-skills/pdf-tables --install-root .claude/skills`, then again for .agents/skills, quote each host row and give the fix for every ❌ and ⚠️ finding.
- Why: The question is whether named hosts load the folder, which the offline check answers row by row.

Bad example:

- Prompt: All hosts show ✅, so tell the team the skill makes our PDF answers better.
- Expected behavior: Say the check shows only that it loads; offer the with/without run before any claim about results.
- Why: Loading is not lift; a better-results claim needs the same tasks run with and without the skill.

## Full Input, Output, and Artifact Expectations

Required inputs:

- the skill folder (with SKILL.md) or the folder of skills to check
- where it will be installed: .agents/skills, .claude/skills, ~/.hermes/skills, or another host root
- the hosts that matter, and the model's context window when it is known

Expected outputs:

- omh_skill_eval/v1
- a fix list ordered by effect: not_loaded first, then degraded

Artifact expectations:

- omh_skill_eval/v1 is the command's own JSON: one row per host with status, root and findings, the catalog size and description total, overlap groups, and static findings, each finding with its message and fix
