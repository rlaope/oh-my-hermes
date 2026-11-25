# Agent Instructions

Load this on-demand contract after the compact `agent-instructions` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The ask is distilling repeated lessons into reviewed rule candidates; use `omh-rules-distill`.
- The ask is a reading path through the codebase for a new engineer; use `omh-codebase-onboarding`.
- The ask is project terminology alignment -- reviewing the terms this project uses and correcting inconsistent vocabulary; use `ulw-context`.
- The ask is user-facing product documentation; use `omh-docs`.

## Examples

Good example:

- Prompt: update our CLAUDE.md
- Expected behavior: Inventory the instruction files, run or collect each build and test command, mark each verified or unverified, and replace only the marked region with the commands, the generated-file map, the gates, and the costed pitfalls, refusing any count or line number.
- Why: An instruction file that states an unrun command or a stale count sends every later agent the wrong way.

Bad example:

- Prompt: add that the suite has 4,100 tests and the router is at line 212 of chat.py
- Expected behavior: Refuse both values, and write the command that counts the tests and the symbol that locates the router instead.
- Why: Both numbers were already wrong by the next merge.

## Full Input, Output, and Artifact Expectations

Required inputs:

- which instruction files exist, where they sit, and which agents read them
- the build, test, lint, and regenerate commands the repository uses
- which files are generated, from what source, and which gate checks them
- the pitfalls that have cost time, each with what it cost
- observed output for every command written into the file

Expected outputs:

- instruction_file_inventory/v1
- command_verification_record/v1
- instruction_region_update/v1
- drift_refusal_note/v1 when a requested line would record a count or a line number

Artifact expectations:

- instruction_file_inventory/v1 lists every instruction file, its path, the agents that read it, and which one is closest to each directory, since the closest file wins
- command_verification_record/v1 marks every command verified, with the observed exit status and when, or unverified, and nothing is written as verified without an observed run
- instruction_region_update/v1 replaces only the text between `<!-- omh:agent-instructions:begin -->` and `<!-- omh:agent-instructions:end -->`, and inserts the markers once when absent, so every hand-written section outside them is left byte-for-byte
- drift_refusal_note/v1 names each requested count, line number, or other value the code already states, and writes the command or the file that derives it instead
