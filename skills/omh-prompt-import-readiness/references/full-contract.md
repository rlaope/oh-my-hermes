# Prompt Import Readiness

Load this on-demand contract after the compact `prompt-import-readiness` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- Adopting a plugin, connector, API, or memory provider; use `omh-external-connector-readiness`.
- A runtime capability or CLI the work needs is missing; use `omh-toolbelt-readiness`.
- Searching for an existing skill to reuse before writing one; use `omh-skill-scout`.

## Examples

Good example:

- Prompt: prompt-import-readiness review Codex and Claude Code prompt folders before exposing them as Hermes slash commands with $ARGUMENTS mapping.
- Expected behavior: Produce `prepare_prompt_import_readiness` with required context, wrapper actions, and not-evidence boundaries.
- Why: Argument syntax differs per CLI and a name can shadow a built-in command; settle both before writing.

Bad example:

- Prompt: prompt-import-readiness silently import every external prompt, overwrite slash commands, and claim the prompts are trusted without review.
- Expected behavior: Report the missing observed evidence or authority instead of claiming the external step happened.
- Why: Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.

## Full Input, Output, and Artifact Expectations

Required inputs:

- user request
- target context
- delivery or status expectation
- known missing evidence

Expected outputs:

- prompt_import_readiness_card/v1
- prompt_compatibility_audit/v1 for explicitly named local files
- prompt_source_inventory/v1
- prompt_format_matrix/v1
- argument_interpolation_policy/v1
- slash_command_collision_report/v1
- prompt_trust_review/v1
- prompt_import_manifest/v1 when observed
- next action
- prepared-vs-observed boundary

Artifact expectations:

- prompt_import_readiness_card/v1 metadata-only wrapper card when prepared
- prompt_compatibility_audit/v1 with bounded source metadata, format classification, argument syntax, collisions, and review reasons for explicitly named local files
- prompt_source_inventory/v1 with source directory, agent family, file count, format claim, and review state
- prompt_format_matrix/v1 separating YAML frontmatter, TOML frontmatter, raw markdown/text, and unsupported formats
- argument_interpolation_policy/v1 for $ARGUMENTS, $1-$9, {{args}}, named placeholders, escaping, and missing argument handling
- slash_command_collision_report/v1 with command names, aliases, existing Hermes commands, and conflict resolution policy
- prompt_trust_review/v1 with source trust, prompt-injection risk, secret leakage risk, license/source notes, and review owner
- prompt_import_manifest/v1 only when file reads, parsed prompts, generated slash-command candidates, or dry-run output are observed
