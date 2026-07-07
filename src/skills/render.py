from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from .catalog import (
    DESCRIPTIONS,
    HarnessDefinition,
    SkillDefinition,
    builtin_definitions,
    builtin_harnesses,
    harness_quality_contract,
    memory_context_policy_for_skill,
    omh_description,
    primary_harness_for_skill,
    skill_exposure_payload,
    surface_exposure_for_skill,
    workflow_reference_definitions,
)
from ..plugin_bundle.omh.awareness import (
    awareness_workflow_context_markdown,
    router_keyword_summary,
)


WORKFLOW_REGISTRY_TRIGGER_LIMIT = 9


@dataclass(frozen=True)
class SkillTemplate:
    name: str
    content: str


@dataclass(frozen=True)
class SkillReferenceTemplate:
    skill_name: str
    relative_path: str
    content: str


TARGET_TOPOLOGY_SCHEMA = "omh_target_topology/v1"
TARGET_TOPOLOGY_ROUTER_CONTEXT = (
    f"Wrappers may report `{TARGET_TOPOLOGY_SCHEMA}` when a workspace moves between one Hermes "
    "agent target and multiple Hermes agent targets. Treat that topology as setup evidence only. "
    "If `active_agent_count` is greater than one, bind this workflow to the current target and "
    "thread, name the target boundary in status, and do not claim another Hermes agent observed, "
    "accepted, or executed the workflow unless target-specific evidence exists."
)
TARGET_TOPOLOGY_CHANGE_CONTEXT = (
    "If a wrapper reports `single_to_multi` or `multi_to_single`, answer with one concise "
    "target-change comment. If the wrapper exposes an `apply_target_change` action and the user "
    "accepts it, persist the target registry update; otherwise keep the workflow scoped to the "
    "current thread target and ask before assuming multi-agent behavior. A skill that does not need "
    "multiple agents should continue as a single-target workflow even when multiple targets are known."
)
TARGET_TOPOLOGY_SKILL_CONTRACT = (
    f"Respect `{TARGET_TOPOLOGY_SCHEMA}` when a wrapper reports it: bind state to the current "
    "target/thread, adapt only the parts of this workflow that benefit from multiple Hermes agents, "
    "and fall back to single-target behavior when `active_agent_count` is one."
)
TARGET_TOPOLOGY_SKILL_CHANGE_CONTRACT = (
    "When target topology changes from one to many or many to one, give a concise setup-change "
    "comment or use the wrapper's apply action before treating the new topology as persistent."
)
TARGET_TOPOLOGY_REFERENCE_CONTEXT = (
    f"When wrapper metadata reports `{TARGET_TOPOLOGY_SCHEMA}`, skills bind workflow state to the "
    "current Hermes target/thread, adapt only the steps that benefit from multiple targets, and fall "
    "back to single-target behavior when the active agent count is one."
)
MEMORY_REVIEW_SCHEMA = "memory_review_card/v1"
HANDOFF_CONTEXT_PACK_SCHEMA = "handoff_context_pack/v1"
MEMORY_CONTEXT_SKILL_CONTRACT = (
    f"When wrapper metadata includes `{MEMORY_REVIEW_SCHEMA}` or `{HANDOFF_CONTEXT_PACK_SCHEMA}`, "
    "treat it as reviewed OMH-local or wrapper-supplied context only. Use conflict-free context "
    "summaries to shape plans and handoffs, but do not claim Hermes internal memory was read or "
    "changed."
)
MEMORY_CONTEXT_COMPACT_SKILL_CONTRACT = (
    "Treat wrapper-supplied memory/context summaries as advisory local context, not proof that "
    "opaque Hermes memory was read or changed."
)
MEMORY_CONTEXT_REFERENCE_CONTEXT = (
    f"`{MEMORY_REVIEW_SCHEMA}` is separate from `status_card/v1`; `{HANDOFF_CONTEXT_PACK_SCHEMA}` "
    "may be attached to executor handoffs only when unresolved conflicts are absent."
)
GOAL_STATUS_REFERENCE_CONTEXT = (
    "`goal_status_card/v1` and `goal_continuation/v1` are goal-execution payloads separate "
    "from generic `status_card/v1`; they must name the next action instead of merely summarizing work."
)

def _target_topology_router_section() -> str:
    return "\n\n".join(
        [
            "## Multi-Agent Target Awareness",
            TARGET_TOPOLOGY_ROUTER_CONTEXT,
            TARGET_TOPOLOGY_CHANGE_CONTEXT,
        ]
    )


def _target_topology_skill_contract_bullets() -> str:
    return "\n".join(
        [
            f"- {TARGET_TOPOLOGY_SKILL_CONTRACT}",
            f"- {TARGET_TOPOLOGY_SKILL_CHANGE_CONTRACT}",
        ]
    )


def _memory_context_skill_contract_bullets(definition: SkillDefinition) -> str:
    if _needs_explicit_memory_context(definition):
        return f"- {MEMORY_CONTEXT_SKILL_CONTRACT}"
    return f"- {MEMORY_CONTEXT_COMPACT_SKILL_CONTRACT}"


def _needs_explicit_memory_context(definition: SkillDefinition) -> bool:
    return memory_context_policy_for_skill(definition.name) == "explicit"


@lru_cache(maxsize=1)
def _definitions_by_name() -> dict[str, SkillDefinition]:
    return {definition.name: definition for definition in builtin_definitions()}


def _frontmatter(name: str, description: str) -> str:
    definition = _definitions_by_name().get(name)
    category = definition.category if definition else "workflow"
    phase = definition.phase if definition else "general"
    description = omh_description(description)
    return (
        f"---\nname: {name}\ndescription: {description}\nmetadata:\n"
        f"  hermes:\n    tags: [workflow, oh-my-hermes, {category}]\n"
        f"    category: {category}\n    phase: {phase}\n"
        f"    role: {definition.hermes_role if definition else 'guide'}\n"
        f"    quality_tier: {definition.quality_tier if definition else 'evidence-gated'}\n---\n"
    )


def _trigger_table(definitions: list[SkillDefinition]) -> str:
    lines = []
    for definition in definitions:
        if definition.name == "oh-my-hermes":
            continue
        triggers = ", ".join(f"`{trigger}`" for trigger in definition.triggers[:WORKFLOW_REGISTRY_TRIGGER_LIMIT])
        lines.append(f"- `{definition.name}`: {triggers}")
    return "\n".join(lines)


def _harness_summary(harness: HarnessDefinition) -> str:
    keep_markers = (
        "visual_qa",
        "frontend_handoff",
        "first_task_runway",
        "codegraph_handoff",
        "overflow_recovery",
        "safe_action_policy",
        "remediation_handoff",
    )
    evidence_ladder = " -> ".join(
        f"`{step}`" for step in _compact_sequence(harness.evidence_ladder, 4, keep_contains=keep_markers)
    )
    wrapper_actions = ", ".join(
        f"`{action}`" for action in _compact_sequence(harness.wrapper_actions, 4, keep_contains=keep_markers)
    )
    return (
        f"- `{harness.name}`: {_compact_harness_purpose(harness.purpose)}. "
        f"L: {evidence_ladder}. A: {wrapper_actions or '`show_status`'}."
    )


def _compact_harness_purpose(purpose: str, limit: int = 84) -> str:
    if len(purpose) <= limit:
        return purpose
    prefix = purpose[: limit - 3].rstrip()
    if " " in prefix:
        prefix = prefix.rsplit(" ", 1)[0]
    return f"{prefix}..."


def _compact_sequence(items: tuple[str, ...], limit: int, keep_contains: tuple[str, ...] = ()) -> tuple[str, ...]:
    if len(items) <= limit:
        return items
    compact = list(items[:limit])
    for item in items[limit:]:
        if any(marker in item for marker in keep_contains):
            compact.append(item)
    hidden = len([item for item in items if item not in compact])
    if hidden:
        compact.append(f"+{hidden} more")
    return tuple(compact)


def _harness_registry(harnesses: list[HarnessDefinition]) -> str:
    return "\n".join(_harness_summary(harness) for harness in harnesses)


def _role_registry(definitions: list[SkillDefinition]) -> str:
    grouped: dict[str, list[str]] = {}
    for definition in definitions:
        grouped.setdefault(definition.hermes_role, []).append(definition.name)
    lines = [
        f"- `{role}`: {', '.join(f'`{name}`' for name in names)}"
        for role, names in sorted(grouped.items())
    ]
    lines.append(
        "- Installed workflow skill policies live in generated workflow skills; "
        "compatibility/reference-only surface policies live in `docs/WORKFLOWS.md` "
        "and are not guaranteed to have `skills/<name>/SKILL.md` files."
    )
    return "\n".join(lines)


def _responsibility_roles_compact() -> str:
    return (
        "Responsibility role details are generated in `docs/WORKFLOWS.md` and surfaced by `skill_view`. "
        "Use the compact role registry above in the router prompt to keep ordinary Hermes routing lightweight."
    )


def _tuple_list(values: tuple[str, ...]) -> str:
    return "\n".join(f"- {value}" for value in values)


def _example_block(label: str, definition: SkillDefinition, *, good: bool) -> str:
    example = definition.good_example if good else definition.bad_example
    if example is None:
        return ""
    return f"""{label} example:

- Prompt: {example.prompt}
- Expected behavior: {example.expected}
- Why: {example.why}"""


def _quality_rubric_sections(definition: SkillDefinition) -> str:
    return f"""## Why This Exists

{definition.why_this_exists}

## Do Not Use When

{_tuple_list(definition.do_not_use_when)}

## Examples

{_example_block("Good", definition, good=True)}

{_example_block("Bad", definition, good=False)}

## Completion Checklist

{_tuple_list(definition.final_checklist)}

## Recovery Notes

{_tuple_list(definition.recovery_notes)}"""


def _skill_metadata_block(definition: SkillDefinition) -> str:
    return f"""Category: `{definition.category}`
Phase: `{definition.phase}`
Hermes role: `{definition.hermes_role}`
Quality tier: `{definition.quality_tier}`

Quality bar:

{_tuple_list(definition.quality_bar)}

Handoff policy:

{definition.handoff_policy}{_executor_readiness_skill_note(definition)}

Required inputs:

{_tuple_list(definition.required_inputs)}

Expected outputs:

{_tuple_list(definition.expected_outputs)}

Artifact expectations:

{_tuple_list(definition.artifact_expectations)}

Safety rules:

{_tuple_list(definition.safety_rules)}"""


def _executor_readiness_skill_note(definition: SkillDefinition) -> str:
    if definition.hermes_role not in {"handoff-guide", "runtime-handoff-guidance"} and definition.quality_tier != "handoff-gated":
        return ""
    return """

Executor readiness:

- When accepted work mutates code, check `executor_readiness/v1` for the selected Codex, Claude Code, Hermes, or oh-my runtime path before first dispatch.
- If readiness is `missing` or `blocked`, ask the user to choose another coding agent, configure PATH, continue in Hermes, or keep a prompt/runtime handoff; retry only after that state changes.
- A readiness probe is not dispatch, implementation, verification, review, CI, merge-readiness, or merge evidence."""


def router_reference_templates() -> list[SkillReferenceTemplate]:
    return list(_router_reference_templates_cached())


@lru_cache(maxsize=1)
def _router_reference_templates_cached() -> tuple[SkillReferenceTemplate, ...]:
    definitions = builtin_definitions()
    harnesses = builtin_harnesses()
    return (
        SkillReferenceTemplate(
            "oh-my-hermes",
            "references/workflow-registry.md",
            _router_workflow_registry_reference(definitions),
        ),
        SkillReferenceTemplate(
            "oh-my-hermes",
            "references/harness-registry.md",
            _router_harness_registry_reference(harnesses),
        ),
        SkillReferenceTemplate(
            "oh-my-hermes",
            "references/wrapper-routing.md",
            _router_wrapper_routing_reference(),
        ),
        SkillReferenceTemplate(
            "oh-my-hermes",
            "references/coding-handoff-progress-reporting.md",
            _router_coding_handoff_progress_reference(),
        ),
        SkillReferenceTemplate(
            "oh-my-hermes",
            "references/operator-maintenance.md",
            _router_operator_maintenance_reference(),
        ),
        SkillReferenceTemplate(
            "oh-my-hermes",
            "references/evidence-boundaries.md",
            _router_evidence_boundaries_reference(),
        ),
    )


def _router_workflow_registry_reference(definitions: list[SkillDefinition]) -> str:
    return f"""# OMH Workflow Registry

This generated reference is loaded only when exact workflow routing detail matters.
The always-on `oh-my-hermes` skill keeps only the compact lane map and recovery rules.

## Role Registry

{_role_registry(definitions)}

## Automatic Routing Registry

When Hermes exposes installed skill descriptions to the model, use this registry as the routing map:

{_trigger_table(definitions)}

Routing is conservative: route only on explicit invocation, strong keyword evidence, or a clear workflow-shaped request. A bare common word such as `team`, `ask`, `wiki`, or `review` is not enough when it could mean normal conversation.
""".rstrip() + "\n"


def _router_harness_registry_reference(harnesses: list[HarnessDefinition]) -> str:
    return f"""# OMH Harness Registry

Harnesses shape response quality and evidence gates. They are not proof that a separate runtime role exists.

Legend: Tier `quality-tier` is in each harness definition; Ladder: evidence steps; Actions: wrapper actions; Privacy `metadata_only`.

## Representative Harnesses

{_harness_registry(harnesses)}

## Harness Priority

1. Coding requests start with `coding-handling`.
2. Multi-step durable work adds `goal-execution`.
3. Current-source or best-practice questions use the `research` harness and stay in Hermes-side evidence gathering before any coding handoff.
4. Unclear work uses `deep-interview` before `planning`.
5. Risky architecture uses `architect`, then `critic`.
6. User-visible behavior changes add `qa-specialist`.
7. Public commands, examples, or limitations add `docs-specialist`.
""".rstrip() + "\n"


def _router_wrapper_routing_reference() -> str:
    return f"""# OMH Wrapper Routing

This reference is for Discord, Slack, hosted Hermes, plugin, or backend adapters. It is not normal end-user UX.

## Chat Routing

Wrappers can run `omh chat route` before dispatching a plain chat message to Hermes:

```sh
omh chat route --source discord --record "risky refactor"
```

Use `route.routing_prompt_template` with `{{message}}` replaced by the received chat message as the prompt forwarded to Hermes. If the wrapper wants a pre-expanded prompt, pass `--include-message` and forward `route.routing_prompt`.

Prefer `omh_interact` when the plugin/tool surface is available because it returns `chat_interaction/v1` and can record a metadata-only wrapper session. Use `omh_recommend` only when Hermes needs route hints without a session record. The plugin-authored metadata has producer provenance so it stays distinguishable from wrapper/backend metadata.

Do not make a normal chat user approve `omh list`, `omh recommend`, `omh chat interact`, or other backend commands just to see workflow options. Render compact summaries, context briefs, pickers, quickstart, probe, or status cards instead.

## Coding Delegation

When a chat message is implementation-shaped and a wrapper wants a concrete executor handoff, run `omh coding delegate` after or instead of generic chat routing:

```sh
omh coding delegate --source discord --executor codex --record "risky refactor"
```

The payload is deterministic local adapter data: recommended workflow, harness, executor/runtime profile, acceptance criteria, verification expectations, and handoff prompt template. Hermes still narrates the user-facing state.

Check `executor_readiness/v1` for Codex, Claude Code, Hermes, or oh-my runtime profiles before first dispatch. If readiness is `missing` or `blocked`, ask the user to choose another coding agent, configure PATH, continue in Hermes, or use prompt/runtime handoff; retry only after that state changes. A readiness probe is not dispatch, execution, verification, review, CI, or merge evidence.

With `--record`, Codex-selected real executor handoffs create `.omh/runtime/runs/<run-id>/` prepared runtime runs with `observation_status: prepared_not_observed`. Executor-choice, prompt-only, runtime-handoff, clarify, and fallback responses remain wrapper/session state.

## Large Output And Context Safety

Wrappers must keep raw Codex JSONL, tool output, process logs, and oversized
executor notes out of Hermes chat context. Use `omh chat codex-progress` or the
Codex progress fields on executor-session actions to pass only
`codex_progress_summary/v1`, `omh_context_artifact_ref/v1`, compact evidence
refs, and bounded human-readable summaries. Raw output belongs in a wrapper or
operator artifact store referenced by `raw_output_artifact`; a prepared artifact
reference is not execution, review, CI, merge-readiness, or merge evidence.

Prefer event-triggered progress over timed polling for long executor, goal,
research, or workflow runs. Emit `omh_progress_event/v1` when a meaningful state
changes: failure discovered, root cause identified, fix strategy selected, files
or area chosen, targeted tests pass/fail, full tests start/pass/fail, commit
created, PR created/updated, or blocker encountered. Keep each update to one or
two human-readable sentences with optional compact file refs, artifact refs,
severity, and status. Store raw logs, JSONL, command output, and transcripts as
artifacts; pass only event summaries and refs into Hermes chat context.

## Memory And Planning

Wrappers can run `omh memory inspect`, `omh memory pack`, and `omh memory apply` to review OMH-local or wrapper-supplied context before preparing a handoff. This emits `{MEMORY_REVIEW_SCHEMA}` and `{HANDOFF_CONTEXT_PACK_SCHEMA}` artifacts only; it does not read or mutate opaque Hermes internal memory.

For planning-shaped requests, wrappers or operators can run `omh hermes plan` to create a deterministic `hermes_plan/v1` scaffold. The stdout `wrapper_contract` is the adapter contract for follow-on work; after acceptance, pass the accepted plan artifact or generated context pack to `omh coding delegate --from-plan` instead of treating Discord/channel summary text as the executor plan.

## Backend Boundary

This is a deterministic wrapper-side decision layer. By default, stdout and runtime artifacts avoid duplicating the raw prompt body. It does not patch Hermes core or require platform network access from `omh`.
""".rstrip() + "\n"


def _router_operator_maintenance_reference() -> str:
    return """# OMH Operator Maintenance

Short OMH maintenance commands are operator commands, not workflow or coding requests.

## Top Priority Guard

Exact or near-exact requests such as `omh update`, `omh setup`, `omh doctor`, `omh uninstall`, `omh install`, `omh list`, `omh 업데이트해줘`, `omh 닥터 돌려줘`, `omh 삭제해줘`, and `omh 셋업해줘` route as `operator_maintenance_command` with task type `omh_cli_maintenance`.

They outrank stale coding context, router-design feedback, runtime portability, migration, and workflow implementation signals unless the user explicitly asks for code changes.

## Semantics

- `route_level`: `operator_maintenance_command`
- `not_a_workflow`: `coding_handoff`, `router_design_feedback`, `runtime_portability`, `migration`, `workflow_implementation`
- `operation_primitives`: `run_requested_command`, `optional_health_check`, `report_observed_output`, `avoid_repo_mutation`
- `risk_domains`: `stale_context_inheritance`, `over_execution`, `unrequested_repo_mutation`

## Wrapper Copy

Say: "I will run the OMH maintenance update path; code changes require a separate request." Adapt `update` to the requested command.

## Evidence Boundary

The requested command output and optional doctor status can become observed evidence. Future Hermes reload, plugin runtime use, coding work, review, CI, and repository mutation stay unobserved unless separately verified.

## Human Summary Vs JSON

Maintenance commands should prefer compact human summaries for chat/operator flows. Full `--json` output remains available for wrappers, automation, and tests that need machine-readable state.
""".rstrip() + "\n"


def _router_coding_handoff_progress_reference() -> str:
    return """# OMH Coding Handoff Progress Reporting

Use this reference when coding work is delegated, attached to an executor
session, or running in the background.

## Active Narration

Hermes must remain an active status narrator after it prepares or observes a
coding handoff. Immediately report the observed executor handle when available:
process/session id, PID, branch or PR target, and the prepared-vs-observed
boundary. Do not silently wait for a final result after saying an executor is
running.

## Progress Cadence

For long-running executor work, use an event-triggered status loop or bounded
watchdog when the wrapper exposes one, and remove it when work completes. Each
update should separate:

- prepared handoff
- dispatch or attached session
- running process
- changed files or affected area
- tests/checks started, passed, failed, or still missing
- commit, push, PR, CI, review, and merge evidence

## Completion Verification

After completion, verify the executor self-report against local git status/log,
remote branch SHA, PR metadata, and required checks before claiming anything
landed. If a PR was already merged before follow-up commits landed, open or
prepare a follow-up PR instead of implying the merged PR contains the new fix.

## Boundary

Progress narration is not execution proof by itself. Only observed runtime
events, git state, PR metadata, checks, review records, and merge records can
satisfy their matching evidence states. Revert or follow-up commits still need
the repository's DCO and commit trailers when required.
""".rstrip() + "\n"


def _router_evidence_boundaries_reference() -> str:
    return f"""# OMH Evidence Boundaries

OMH is a Hermes-native wrapper orchestration layer. It keeps Hermes responsible for chat intake, clarification, source-backed research, planning, and status narration while coding-heavy work is prepared as explicit handoff and tracked only when observed.

## Prepared Versus Observed

Prepared routing, plans, task cards, and handoffs are not execution evidence. `prepared_not_observed` is not implementation, review, CI, merge-readiness, merge evidence, plugin runtime use, or proof that another agent acted.

## Runtime Evidence

When local shell access or a bot wrapper is available, record prepared handoffs and observed workflow evidence under `.omh/runtime/`:

```sh
omh coding delegate --source discord --executor codex --record "risky refactor"
omh runtime delegate --run <run-id> --requested --not-observed --result not_observed
```

Record only what is observed. If Hermes or a chosen oh-my runtime does not expose delegation metadata, use `not_observed` or `not_available` instead of implying a specialist lane ran.

## Multi-Agent Target Awareness

{TARGET_TOPOLOGY_ROUTER_CONTEXT}

{TARGET_TOPOLOGY_CHANGE_CONTEXT}

## Memory Context

{MEMORY_CONTEXT_REFERENCE_CONTEXT}

## Goal Status

{GOAL_STATUS_REFERENCE_CONTEXT}

## Hermes Compatibility

- Use Hermes tools and subagents when available.
- Replace unavailable goal tools with file-backed checklists or ledgers.
- Replace unavailable question renderers with one direct question through the current Hermes surface.
- Keep shell bridge behavior explicit and opt-in.
""".rstrip() + "\n"


def router_skill() -> SkillTemplate:
    body = f"""# Oh My Hermes Router

Use this skill when the user mentions oh-my-hermes or a workflow keyword such as {router_keyword_summary()}.

## Routing Contract

This is best-effort Hermes prompt guidance. It does not override Hermes core routing and it does not claim exact runtime parity with another agent framework.

Normal users should talk to Hermes Agent or invoke installed Hermes skills through Hermes' own skill surface. Do not ask chat users to run `omh` commands for ordinary workflow use. The `omh` command is bootstrap, maintenance, verification, and wrapper/backend infrastructure.

{_quality_rubric_sections(_definitions_by_name()["oh-my-hermes"])}

## OMH Awareness Primer (Compact)

OMH is Hermes-native workflow guidance, not a hidden executor or Hermes core patch. Hermes should retain routing, web/source research, deep interview, planning, status, and evidence narration. Coding-heavy work becomes an explicit prepared handoff to the selected executor/runtime profile and stays `prepared_not_observed` until evidence is recorded.

Compact lane map:

- Intent -> plan: `deep-interview`, `ralplan`, `plan`, `loop`, `ultraprocess`.
- Research and company ops: `web-research`, `source-finder`, `research-department`, `paper-learning`, `feedback-triage`, `strategy-brief`, `meeting-brief`.
- Retained knowledge: `wiki`.
- Materials and visual summaries: `design-quality-gate`, `frontend`, `accessibility-audit`, `visual-qa`, `materials-package`, `img-summary`, `report-package`, `deliverable-package`.
- Operations and evidence gates: `workspace-audit`, `production-audit`, `verification-gate`, `agent-evaluation`, `rules-distill`, `agent-ops-review`, `harness-session-inventory`, `ops-observability-card`, `instinct-ledger`, `workflow-learning`.
- Coding handoff and review: `idea-to-deploy`, `code-review`, `ultraprocess`, `team`, `ultrawork`, `ultraqa`.

## Priority Rules

1. Exact or near-exact OMH maintenance commands (`omh update`, `omh setup`, `omh doctor`, `omh uninstall`, `omh install`, `omh list`, and Korean equivalents such as `omh 업데이트해줘`, `omh 닥터 돌려줘`, `omh 삭제해줘`, `omh 셋업해줘`) route as `operator_maintenance_command`. Run the requested command, report observed output, and avoid repo mutation unless the user separately asks for code changes.
2. Explicit slash skill invocation wins when it is not one of those maintenance commands.
3. Explicit workflow keywords route to the matching adapted skill when installed.
4. Broad planning requests route to `ralplan` or `plan` before implementation.
5. Persistence or finish-until-done requests route to `ralph` only after scope is concrete.
6. Unknown or conflicting signals stay in this router and ask one concise clarification question.

## Direct Picker Aliases

If the user has only typed `./`, `/`, `./o`, or `/om`, show a command preview with exactly one top-level suggestion: `omh`. Selecting it should insert `./omh` or `/omh` and then open the workflow picker. Do not preview every installed workflow at the first `./` stage.

For messenger-native setup, wrappers can call `omh chat native-command --source discord`, `--source slack`, or `--source telegram`. When plain-message autocomplete is not available, render the returned `omh_command_fallback_card/v1` as an `Open omh` button/card before opening the picker.

If the user types `./omh`, `/omh`, `./skills`, or `/skills` without a task, show a compact workflow picker instead of creating a plan. Keep real skill names unchanged and keep `chat_response.state.skill_picker.options` as the flat-list fallback.

Choosing a skill is routing intent, not plan acceptance, dispatch, execution, or verification evidence. Do not make the user approve `omh list` just to see the catalog.

## Install And CLI Boundary

Hermes-native install paths should converge on the same skill-visible state:

- `hermes skills tap add rlaope/oh-my-hermes`, then `hermes skills install rlaope/oh-my-hermes/skills/oh-my-hermes --yes` installs this tap-compatible skill pack directly when Hermes supports taps.
- `omh setup` installs generated managed skills and registers their directory through `skills.external_dirs` when a local bootstrap or repair path is preferred.

Use compact human summaries for normal `omh setup`, `omh doctor`, `omh update`, `omh uninstall`, `omh install`, and `omh list` operator flows. Full `--json` output is for wrappers, automation, and tests.

## Wrapper Backend Summary

`omh chat route`, `omh_interact`, `omh_recommend`, `omh coding delegate`, `omh memory ...`, and `omh hermes plan` are adapter/backend surfaces, not normal chat UX. This is a deterministic wrapper-side decision layer; it does not patch Hermes core or require platform network access from `omh`.

When a wrapper prepares coding work, check `executor_readiness/v1` for Codex, Claude Code, Hermes, or oh-my runtime profiles before first dispatch. A readiness probe is not dispatch, implementation, verification, review, CI, merge-readiness, or merge evidence.

## Runtime Evidence

Record only what is observed. A task card, route, plan, `coding_delegation.json`, or `prepared_coding_delegation` run envelope proves preparation, not execution. Executor-choice, prompt-only, and runtime handoffs do not create lifecycle runtime runs.

## Hermes Compatibility Contract

- Use Hermes-native tools, file operations, and subagent/delegation features when available.
- Do not require runtime tools, role prompts, or overlays that Hermes Agent does not expose.
- Translate runtime-specific mechanisms to Hermes-native artifacts:
  - goal tools -> `.omh/goals/` ledgers, goal status cards, or explicit checklists with named next actions,
  - question renderers -> one concise question in the current Hermes interface,
  - native subagents -> Hermes delegation when available, otherwise sequential lanes,
  - shell bridge commands -> optional bridge mode only.
- Record observed delegation results when Hermes or the wrapper exposes them. If delegation is unavailable, keep the result explicit as `not_available` or `not_observed`.

## Progressive Disclosure References

Load these only when exact detail matters:

- `references/operator-maintenance.md` for short `omh` maintenance command semantics.
- `references/workflow-registry.md` for full workflow triggers and role registry.
- `references/harness-registry.md` for representative harnesses and priority.
- `references/wrapper-routing.md` for backend/plugin/chat/coding delegation contracts.
- `references/coding-handoff-progress-reporting.md` for active progress cadence, background executor watchdogs, PR head/merge verification, and memory/context collision pitfalls.
- `references/evidence-boundaries.md` for prepared-vs-observed, target topology, memory, and compatibility rules.

## Recovery

- If exact route detail matters, load `references/workflow-registry.md` or the specific workflow skill before answering.
- If harness behavior matters, load `references/harness-registry.md`.
- If wrapper/backend behavior matters, load `references/wrapper-routing.md`.
- If delegated coding work is running or being reported, load `references/coding-handoff-progress-reporting.md`.
- If maintenance command behavior matters, load `references/operator-maintenance.md`.
- If evidence or target topology is disputed, load `references/evidence-boundaries.md`.
- If the right skill was not loaded, call `skills_list` or `skill_view`.
- If a slash command exists, use the explicit slash skill such as `/ralph`.
- If a skill name collides, ask the user whether to use the Hermes-native skill or the oh-my-hermes adapted skill.
"""
    return SkillTemplate("oh-my-hermes", _frontmatter("oh-my-hermes", DESCRIPTIONS["oh-my-hermes"]) + "\n" + body)


def workflow_skill(name: str) -> SkillTemplate:
    definition = _definitions_by_name()[name]
    title = name.replace("-", " ").title()
    triggers = ", ".join(f"`{trigger}`" for trigger in definition.triggers)
    primary_harness = primary_harness_for_skill(name)
    body = f"""# {title}

This is a Hermes-native `{name}` workflow skill.

{_quality_rubric_sections(definition)}

{awareness_workflow_context_markdown(name)}

## Use When

{definition.use_when}

    Strong routing signals: {triggers}

## Catalog Metadata

{_skill_metadata_block(definition)}

## Harness Discipline

- Start from the representative harness registry in `oh-my-hermes` when the workflow needs coding, research, planning, goal execution, architecture, critique, QA, or documentation lanes.
- Prefer richer evidence and clearer stop conditions over adding more workflow names.
- Use specialist lanes only when they change the quality of the answer or verification.

## Runtime Evidence

Preferred harness for this skill: `{primary_harness}`.

When local shell access or a bot wrapper is available, record metadata-only evidence:

```sh
omh runtime record --skill {name} --harness {primary_harness} --status started
omh runtime delegate --run <run-id> --requested --not-observed --result not_observed
```

Record observed delegation results when Hermes or the wrapper exposes them. If delegation is unavailable, keep the result explicit as `not_available` or `not_observed`.

## Hermes Compatibility Contract

- Preserve the workflow intent, stop conditions, and verification discipline.
- Use Hermes-native tools, file operations, and subagent/delegation features when available.
- Do not require runtime tools, role prompts, or overlays that Hermes Agent does not expose.
{_target_topology_skill_contract_bullets()}
{_memory_context_skill_contract_bullets(definition)}
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
"""
    return SkillTemplate(name, _frontmatter(name, definition.description) + "\n" + body)


def builtin_skill_templates() -> list[SkillTemplate]:
    from .packaging import builtin_skill_templates as packaged_templates

    return packaged_templates()


def workflow_reference_markdown() -> str:
    return _workflow_reference_markdown_cached()


@lru_cache(maxsize=1)
def _workflow_reference_markdown_cached() -> str:
    definitions = workflow_reference_definitions()
    harnesses = builtin_harnesses()
    lines = [
        "# Workflow Reference",
        "",
        "This file is generated from `src/skills/catalog.py`. Update the catalog first, then refresh this document.",
        "",
        "The reference describes prompt-level Hermes workflow guidance and local evidence expectations. It does not claim hidden Hermes runtime behavior.",
        "",
        "Workflow names are kept for compatibility, but each skill declares advisory wrapper guidance for whether Hermes should retain the work directly, ask the user to choose an executor/runtime profile, or prepare a coding handoff for coding-heavy execution.",
        "",
        "Exposure is the install contract: `install_visibility: true` surfaces generate `skills/<name>/SKILL.md`; router-only, harness-only, and agent-context surfaces stay routable references unless this document explicitly promotes them.",
        "",
        TARGET_TOPOLOGY_REFERENCE_CONTEXT,
        MEMORY_CONTEXT_REFERENCE_CONTEXT,
        GOAL_STATUS_REFERENCE_CONTEXT,
        "",
        "## Skills",
        "",
    ]
    for definition in definitions:
        exposure = surface_exposure_for_skill(definition.name)
        triggers = ", ".join(f"`{trigger}`" for trigger in definition.triggers)
        lines.extend(
            [
                f"### {definition.name}",
                "",
                definition.description,
                "",
                f"- Category: `{definition.category}`",
                f"- Phase: `{definition.phase}`",
                f"- Hermes role: `{definition.hermes_role}`",
                f"- Quality tier: `{definition.quality_tier}`",
                f"- Exposure: `{exposure.exposure}`",
                f"- Install visibility: `{str(exposure.install_visibility).lower()}`",
                f"- Docs visibility: `{exposure.docs_visibility}`",
                f"- Compatibility alias: `{str(exposure.compatibility_alias).lower()}`",
                f"- Preferred usage: {exposure.preferred_usage}",
                f"- Handoff policy: {definition.handoff_policy}",
                f"- Why this exists: {definition.why_this_exists}",
                f"- Use when: {definition.use_when}",
                "- Do not use when:",
                *[f"  - {item}" for item in definition.do_not_use_when],
                f"- Strong routing signals: {triggers}",
                "- Good example:",
                f"  - Prompt: {definition.good_example.prompt if definition.good_example else ''}",
                f"  - Expected behavior: {definition.good_example.expected if definition.good_example else ''}",
                f"  - Why: {definition.good_example.why if definition.good_example else ''}",
                "- Bad example:",
                f"  - Prompt: {definition.bad_example.prompt if definition.bad_example else ''}",
                f"  - Expected behavior: {definition.bad_example.expected if definition.bad_example else ''}",
                f"  - Why: {definition.bad_example.why if definition.bad_example else ''}",
                "- Quality bar:",
                *[f"  - {item}" for item in definition.quality_bar],
                "- Completion checklist:",
                *[f"  - {item}" for item in definition.final_checklist],
                "- Recovery notes:",
                *[f"  - {item}" for item in definition.recovery_notes],
                "- Required inputs:",
                *[f"  - {item}" for item in definition.required_inputs],
                "- Expected outputs:",
                *[f"  - {item}" for item in definition.expected_outputs],
                "- Artifact expectations:",
                *[f"  - {item}" for item in definition.artifact_expectations],
                "- Safety rules:",
                *[f"  - {item}" for item in definition.safety_rules],
                "",
            ]
        )
    lines.extend(["## Representative Harnesses", ""])
    for harness in harnesses:
        lines.extend(
            [
                f"### {harness.name}",
                "",
                harness.purpose,
                "",
                f"- Use when: {harness.use_when}",
                f"- Quality tier: `{harness.quality_tier}`",
                "- Quality bar:",
                *[f"  - {item}" for item in harness.quality_bar],
                "- Inputs:",
                *[f"  - {item}" for item in harness.required_inputs],
                "- Outputs:",
                *[f"  - {item}" for item in harness.expected_outputs],
                "- Stop conditions:",
                *[f"  - {item}" for item in harness.stop_conditions],
                "- Verification:",
                *[f"  - {item}" for item in harness.verification],
                "- Evidence ladder:",
                *[f"  - `{item}`" for item in harness.evidence_ladder],
                "- Wrapper actions:",
                *[f"  - `{item}`" for item in harness.wrapper_actions],
                "- Artifact events:",
                *[f"  - `{item}`" for item in harness.artifact_events],
                f"- Delegation expectation: {harness.delegation_expectation}",
                f"- Privacy default: `{harness.privacy_default}`",
                "- Overclaim guards:",
                *[f"  - {item}" for item in harness.overclaim_guards],
                f"- Fallback: {harness.fallback}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def workflow_reference_payload() -> dict[str, object]:
    return _copy_workflow_reference_payload(_workflow_reference_payload_cached())


@lru_cache(maxsize=1)
def _workflow_reference_payload_cached() -> dict[str, object]:
    return {
        "schema_version": "workflow_catalog/v1",
        "description": (
            "Deterministic Hermes-native skill and harness metadata. This payload is local guidance, "
            "not proof of hidden Hermes runtime behavior."
        ),
        "skills": [_skill_payload(definition) for definition in workflow_reference_definitions()],
        "harnesses": [_harness_payload(harness) for harness in builtin_harnesses()],
    }


def _copy_workflow_reference_payload(payload: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": payload["schema_version"],
        "description": payload["description"],
        "skills": [_copy_skill_payload(skill) for skill in payload["skills"]],
        "harnesses": [_copy_harness_payload(harness) for harness in payload["harnesses"]],
    }


def _copy_skill_payload(payload: dict[str, object]) -> dict[str, object]:
    copied = dict(payload)
    for key in (
        "triggers",
        "do_not_use_when",
        "quality_bar",
        "final_checklist",
        "recovery_notes",
        "required_inputs",
        "expected_outputs",
        "artifact_expectations",
        "safety_rules",
        "projections",
    ):
        copied[key] = list(payload[key])
    copied["good_example"] = dict(payload["good_example"])
    copied["bad_example"] = dict(payload["bad_example"])
    return copied


def _copy_harness_payload(payload: dict[str, object]) -> dict[str, object]:
    copied = dict(payload)
    for key in (
        "quality_bar",
        "required_inputs",
        "expected_outputs",
        "stop_conditions",
        "verification",
        "evidence_ladder",
        "wrapper_actions",
        "artifact_events",
        "overclaim_guards",
    ):
        copied[key] = list(payload[key])
    copied["harness_quality"] = _copy_harness_quality_payload(payload["harness_quality"])
    return copied


def _copy_harness_quality_payload(payload: dict[str, object]) -> dict[str, object]:
    copied = dict(payload)
    for key in ("quality_bar", "evidence_ladder", "wrapper_actions", "overclaim_guards"):
        copied[key] = list(payload[key])
    return copied


def _skill_payload(definition: SkillDefinition) -> dict[str, object]:
    exposure = skill_exposure_payload(definition.name)
    return {
        "name": definition.name,
        "description": definition.description,
        "use_when": definition.use_when,
        "category": definition.category,
        "phase": definition.phase,
        "triggers": list(definition.triggers),
        "primary_harness": primary_harness_for_skill(definition.name),
        "surface_exposure": exposure["exposure"],
        "exposure": exposure["exposure"],
        "projections": exposure["projections"],
        "install_visibility": exposure["install_visibility"],
        "docs_visibility": exposure["docs_visibility"],
        "preferred_usage": exposure["preferred_usage"],
        "compatibility_alias": exposure["compatibility_alias"],
        "hermes_role": definition.hermes_role,
        "handoff_policy": definition.handoff_policy,
        "why_this_exists": definition.why_this_exists,
        "do_not_use_when": list(definition.do_not_use_when),
        "good_example": _example_payload(definition.good_example),
        "bad_example": _example_payload(definition.bad_example),
        "quality_tier": definition.quality_tier,
        "quality_bar": list(definition.quality_bar),
        "final_checklist": list(definition.final_checklist),
        "recovery_notes": list(definition.recovery_notes),
        "required_inputs": list(definition.required_inputs),
        "expected_outputs": list(definition.expected_outputs),
        "artifact_expectations": list(definition.artifact_expectations),
        "safety_rules": list(definition.safety_rules),
    }


def _example_payload(example) -> dict[str, str]:
    if example is None:
        return {"prompt": "", "expected": "", "why": ""}
    return {"prompt": example.prompt, "expected": example.expected, "why": example.why}


def _harness_payload(harness: HarnessDefinition) -> dict[str, object]:
    return {
        "name": harness.name,
        "purpose": harness.purpose,
        "use_when": harness.use_when,
        "quality_tier": harness.quality_tier,
        "quality_bar": list(harness.quality_bar),
        "required_inputs": list(harness.required_inputs),
        "expected_outputs": list(harness.expected_outputs),
        "stop_conditions": list(harness.stop_conditions),
        "verification": list(harness.verification),
        "evidence_ladder": list(harness.evidence_ladder),
        "wrapper_actions": list(harness.wrapper_actions),
        "artifact_events": list(harness.artifact_events),
        "delegation_expectation": harness.delegation_expectation,
        "privacy_default": harness.privacy_default,
        "overclaim_guards": list(harness.overclaim_guards),
        "fallback": harness.fallback,
        "harness_quality": harness_quality_contract(harness.name),
    }
