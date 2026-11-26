# Skill

Load this on-demand contract after the compact `skill` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The user wants an OMH capability family turned on or off; use `omh-capability-toggle`.
- The user wants a public skill found and vetted before installing it; use `omh-skill-scout`.
- The user wants skill health checked: stale surfaces, failure patterns, or pending amendments; use `omh-skill-health`.
- The user is writing or editing a skill that ships in the hermes-agent repository itself rather than a local one; load Hermes' optional `hermes-agent-skill-authoring` skill instead of this one when installed (if skill_view cannot find it: hermes skills install official/software-development/hermes-agent-skill-authoring).

## Examples

Good example:

- Prompt: which skills do I have, and add one for our release checklist
- Expected behavior: List with `skills_list`, read close matches with `skill_view`, create the new skill with `skill_manage` under a name of the person's own, and report it from the tool result.
- Why: Listing and creating a person's own skill are Hermes' native skill tools' job.

Bad example:

- Prompt: skill: patch omh-plan's SKILL.md with skill_manage so it asks fewer questions
- Expected behavior: Decline the in-place edit and offer a separately named skill or an OMH catalog change instead.
- Why: An OMH-managed body is generated from OMH's catalog, so the patch would not carry into the next generation.

## Full Input, Output, and Artifact Expectations

Required inputs:

- skill action
- target skill name or directory

Expected outputs:

- skill inventory or mutation result
- verification note

Artifact expectations:

- manifest update when managed skills change
