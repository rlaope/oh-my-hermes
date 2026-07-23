---
name: prompt-import-readiness
description: [omh] Hermes prompt import readiness workflow: decide whether external CLI-agent prompt files can be safely reviewed, normalized, and offered as Hermes slash-command candidates without mutating prompts or command registries.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, prompt]
    category: prompt
    phase: prompt-import-readiness
    role: guide
    quality_tier: workflow-surface-gated
---

# Prompt Import Readiness

This is a Hermes-native `prompt-import-readiness` workflow skill.

## Why This Exists

`prompt-import-readiness` exists so Hermes users can ask for this workflow in chat and receive a structured, evidence-bounded OMH operating surface instead of ad hoc narration.

## Do Not Use When

- The request is already handled by a narrower explicit skill with stronger evidence.
- The user asks OMH to secretly run external platforms, connectors, schedulers, file exports, or runtime agents.
- The only safe answer is to ask for missing authority, credentials, target, or observed evidence first.

## Examples

Good example:

- Prompt: prompt-import-readiness review Codex and Claude Code prompt folders before exposing them as Hermes slash commands with $ARGUMENTS mapping.
- Expected behavior: Produce `prepare_prompt_import_readiness` with required context, wrapper actions, and not-evidence boundaries.
- Why: The prompt names a real workflow surface that Hermes can orchestrate without hiding execution.

Bad example:

- Prompt: prompt-import-readiness silently import every external prompt, overwrite slash commands, and claim the prompts are trusted without review.
- Expected behavior: Report the missing observed evidence or authority instead of claiming the external step happened.
- Why: Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.

## Completion Checklist

- Prompt sources, agent family, expected file formats, argument syntax, slash-command names, trust level, and stop condition are explicit.
- Prompt file reads, parser results, command registration, prompt mutation, slash-command activation, and dry-run execution are marked observed, missing, risky, or not_observed.
- Route broad candidate discovery to skill-scout, prompt/tool safety to security-safety-review, missing CLIs or directories to toolbelt-readiness, and approved implementation to a selected executor handoff.
- Imported prompts, generated command files, registry updates, and dry-run results are reported only from observed prompt-import evidence.

## Recovery Notes

- If source prompt directories are unknown, route to workspace-audit or skill-scout before readiness scoring.
- If source trust, prompt-injection risk, secrets, or destructive command content is unclear, route to security-safety-review before import.
- If the user asks to actually copy, generate, or register prompt files, prepare an executor or workspace-file handoff and keep readiness prepared_not_observed until file evidence exists.

## OMH Context Rail

- This skill is part of OMH's Hermes workflow layer, not a standalone executor.
- Product context: OMH is a Hermes-native workflow pack: choose skills, shape work, prepare artifacts, show status, and hand off with evidence boundaries.
- Current lane: **Automation and status** (`achievements`, `workspace-audit`, `production-audit`, `automation-blueprint`, `github-event-ops`, `agent-board`, `gateway-intent-card`, `voice-operator`, `+30 more`) - schedules, status, health, and ops review.
- If the user intent belongs to another OMH lane, hand back to `oh-my-hermes` or name the adjacent workflow instead of force-fitting this skill.
- Cross-skill context: every OMH skill: match lane; generic tool can render or execute.
- Generic-tool checkpoint: image->img-summary; frontend->frontend/a11y/visual-qa; paper->paper-learning; content->content-operator; media->media-input-operator; file->materials-package; search->web-research; live->live-info-operator; audit->workspace/production/security; failures->build-failure; verify->verification-gate; code->codegraph/onboarding/ultraprocess.
- Coverage: Every generated workflow skill carries this rail.
- Normal users talk to Hermes; OMH CLI is infra.
- Boundary: Prepared OMH routing, cards, handoffs, or artifacts are not observed execution, image generation, delivery, review, CI, merge-readiness, or merge evidence.

## Use When

Use before importing, normalizing, or exposing external prompt files as Hermes slash commands so source trust, formats, argument interpolation, name collisions, review status, and dry-run evidence stay explicit.

    Strong routing signals: `prompt-import-readiness`, `prompt import readiness`, `slash prompt import`, `slash prompts import`, `slash command prompt import`, `prompt library import`, `prompt folder import`, `prompt directory import`, `import CLI prompts`, `import agent prompts`, `CLI agent prompt files`, `OpenCode prompt import`, `Claude Code prompt import`, `Codex prompt import`, `codex prompt import`, `Gemini CLI prompt import`, `frontmatter prompt import`, `argument interpolation`, `$ARGUMENTS mapping`, `{{args}} mapping`, `$1-$9 prompt arguments`, `prompt slash command collision`, `Hermes slash prompts`, `슬래시 프롬프트 가져오기`, `프롬프트 가져오기`, `프롬프트 디렉터리 가져오기`, `프롬프트 폴더 가져오기`, `슬래시 명령 프롬프트`, `프롬프트 인자 매핑`

## Catalog Metadata

Category: `prompt`
Phase: `prompt-import-readiness`
Hermes role: `guide`
Quality tier: `workflow-surface-gated`

Quality bar:

- Name the user-facing workflow objective, required context, next action, and stop condition.
- Separate prepared guidance from observed platform, runtime, connector, file, memory, or delivery evidence.
- Expose missing tools, credentials, targets, or observations as user-visible gaps.

Handoff policy:

Keep this as Hermes-facing orchestration guidance first. Prepare executor, connector, gateway, or host-runtime handoff only when the user accepts that next step and observed evidence can be recorded.

Required inputs:

- user request
- target context
- delivery or status expectation
- known missing evidence

Expected outputs:

- prompt_import_readiness_card/v1
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
- prompt_source_inventory/v1 with source directory, agent family, file count, format claim, and review state
- prompt_format_matrix/v1 separating YAML frontmatter, TOML frontmatter, raw markdown/text, and unsupported formats
- argument_interpolation_policy/v1 for $ARGUMENTS, $1-$9, {{args}}, named placeholders, escaping, and missing argument handling
- slash_command_collision_report/v1 with command names, aliases, existing Hermes commands, and conflict resolution policy
- prompt_trust_review/v1 with source trust, prompt-injection risk, secret leakage risk, license/source notes, and review owner
- prompt_import_manifest/v1 only when file reads, parsed prompts, generated slash-command candidates, or dry-run output are observed

Safety rules:

- A prompt import readiness card is not prompt file access, prompt parsing success, slash command registration, prompt mutation, command activation, imported prompt trust, or successful dry-run evidence unless observed prompt-import evidence records it.
- Do not claim connector, gateway, runtime, file generation, memory mutation, or host automation evidence from prepared guidance.

## Harness Discipline

- Start from the representative harness registry in `oh-my-hermes` when the workflow needs coding, research, planning, goal execution, architecture, critique, QA, or documentation lanes.
- Prefer richer evidence and clearer stop conditions over adding more workflow names.
- Use specialist lanes only when they change the quality of the answer or verification.

## Runtime Evidence

Preferred harness for this skill: `prompt-import-readiness`.

When local shell access or a bot wrapper is available, record metadata-only evidence:

```sh
omh runtime record --skill prompt-import-readiness --harness prompt-import-readiness --status started
omh runtime delegate --run <run-id> --requested --not-observed --result not_observed
```

Record observed delegation results when Hermes or the wrapper exposes them. If delegation is unavailable, keep the result explicit as `not_available` or `not_observed`.

## Hermes Compatibility Contract

- Preserve the workflow intent, stop conditions, and verification discipline.
- Use Hermes-native tools, file operations, and subagent/delegation features when available.
- Do not require runtime tools, role prompts, or overlays that Hermes Agent does not expose.
- Respect `omh_target_topology/v1` when a wrapper reports it: bind state to the current target/thread, adapt only the parts of this workflow that benefit from multiple Hermes agents, and fall back to single-target behavior when `active_agent_count` is one.
- When target topology changes from one to many or many to one, give a concise setup-change comment or use the wrapper's apply action before treating the new topology as persistent.
- Treat wrapper-supplied memory/context summaries as advisory local context, not proof that opaque Hermes memory was read or changed.
- When a runtime-specific mechanism appears in imported instructions, translate it to a Hermes-native artifact:
  - goal tools -> `.omh/goals/` ledgers, `goal_completion_gate/v1`, `goal_status_card/v1`, `goal_continuation/v1`, or explicit checklists with named next actions,
  - question renderers -> one concise question in the current Hermes interface,
  - native subagents -> Hermes delegation when available, otherwise sequential lanes,
  - shell bridge commands -> optional bridge mode only.

## Execution Rules

1. Load supporting context with `skills_list` / `skill_view` when needed.
2. State the workflow target, constraints, validation evidence, and stop condition.
3. Keep progress evidence-backed.
4. Verify with the smallest relevant test or inspection before claiming completion.
5. If Hermes cannot provide a required runtime capability, say so and use the fallback above.
