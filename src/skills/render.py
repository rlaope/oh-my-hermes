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
    primary_harness_for_skill,
)


@dataclass(frozen=True)
class SkillTemplate:
    name: str
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
    return (
        f"---\nname: {name}\ndescription: {description}\nmetadata:\n"
        f"  hermes:\n    tags: [workflow, oh-my-hermes, {category}]\n"
        f"    category: {category}\n    phase: {phase}\n"
        f"    role: {definition.hermes_role if definition else 'hybrid-guidance'}\n"
        f"    quality_tier: {definition.quality_tier if definition else 'evidence-gated'}\n---\n"
    )


def _trigger_table(definitions: list[SkillDefinition]) -> str:
    lines = []
    for definition in definitions:
        if definition.name == "oh-my-hermes":
            continue
        triggers = ", ".join(f"`{trigger}`" for trigger in definition.triggers[:5])
        lines.append(f"- `{definition.name}`: {triggers}")
    return "\n".join(lines)


def _harness_summary(harness: HarnessDefinition) -> str:
    evidence_ladder = " -> ".join(f"`{step}`" for step in harness.evidence_ladder[:4])
    wrapper_actions = ", ".join(f"`{action}`" for action in harness.wrapper_actions[:5])
    return (
        f"- `{harness.name}`: {harness.purpose} Tier `{harness.quality_tier}`. "
        f"Ladder: {evidence_ladder}. Actions: {wrapper_actions or '`show_status`'}. "
        f"Privacy `{harness.privacy_default}`."
    )


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
    lines.append("- Full per-skill handoff policies live in generated workflow skills and `docs/WORKFLOWS.md`.")
    return "\n".join(lines)


def _responsibility_roles_compact() -> str:
    return (
        "Responsibility role details are generated in `docs/WORKFLOWS.md` and surfaced by `skill_view`. "
        "Use the compact role registry above in the router prompt to keep ordinary Hermes routing lightweight."
    )


def _tuple_list(values: tuple[str, ...]) -> str:
    return "\n".join(f"- {value}" for value in values)


def _skill_metadata_block(definition: SkillDefinition) -> str:
    return f"""Category: `{definition.category}`
Phase: `{definition.phase}`
Hermes role: `{definition.hermes_role}`
Quality tier: `{definition.quality_tier}`

Quality bar:

{_tuple_list(definition.quality_bar)}

Handoff policy:

{definition.handoff_policy}

Required inputs:

{_tuple_list(definition.required_inputs)}

Expected outputs:

{_tuple_list(definition.expected_outputs)}

Artifact expectations:

{_tuple_list(definition.artifact_expectations)}

Safety rules:

{_tuple_list(definition.safety_rules)}"""


def router_skill() -> SkillTemplate:
    definitions = builtin_definitions()
    harnesses = builtin_harnesses()
    body = f"""# Oh My Hermes Router

Use this skill when the user mentions oh-my-hermes or a workflow keyword such as `ralph`, `ultragoal`, `ultrawork`, `ultraprocess`, `deep-interview`, `web-research`, `team`, `ultraqa`, `ralplan`, or `code-review`.

## Routing Contract

This is best-effort Hermes prompt guidance. It does not override Hermes core routing and it does not claim exact runtime parity with another agent framework.

Normal users should talk to Hermes Agent or invoke installed Hermes skills through Hermes' own skill surface. Do not ask chat users to run `omh` commands for ordinary workflow use. The `omh` command is bootstrap, maintenance, verification, and wrapper/backend infrastructure.

Hermes-native install paths should converge on the same skill-visible state:

- `hermes skills tap add rlaope/oh-my-hermes`, then `hermes skills install rlaope/oh-my-hermes/skills/oh-my-hermes --yes` installs this tap-compatible skill pack directly when Hermes supports taps.
- `omh setup` installs generated managed skills and registers their directory through `skills.external_dirs` when a local bootstrap or repair path is preferred.

Priority:

1. Explicit slash skill invocation wins.
2. Explicit workflow keywords route to the matching adapted skill when installed.
3. Broad planning requests route to `ralplan` or `plan` before implementation.
4. Persistence or finish-until-done requests route to `ralph` only after scope is concrete.
5. Unknown or conflicting signals stay in this router and ask one concise clarification question.

## Skill Role Classification

Keep compatible workflow names installed, but use this advisory wrapper guidance to decide what Hermes should own:

{_role_registry(definitions)}

General rule: Hermes should retain routing, web/source research, deep interview, planning, status, and evidence narration. This role metadata is advisory unless a wrapper/runtime artifact records observed enforcement. When the accepted next action mutates code, the wrapper should ask for or apply the selected executor profile, prepare the matching handoff, and track only evidence it actually observes instead of implying Hermes coded secretly.

{_target_topology_router_section()}

## Responsibility Roles

{_responsibility_roles_compact()}

## Wrapper Backend Chat Routing

Discord, Slack, or hosted Hermes wrappers can run `omh chat route` before dispatching a plain chat message to Hermes. This is an adapter/backend call, not end-user UX:

```sh
omh chat route --source discord --record "risky refactor"
```

Use `route.routing_prompt_template` with `{{message}}` replaced by the received chat message as the prompt forwarded to Hermes. If the wrapper does not log stdout and wants a pre-expanded prompt, pass `--include-message` and forward `route.routing_prompt`. A `dispatch` action targets the selected workflow skill; `clarify` and `fallback` target this router so Hermes can ask one concise follow-up instead of guessing.

This is a deterministic wrapper-side decision layer. By default, stdout and runtime artifacts avoid duplicating the raw prompt body. It does not patch Hermes core or require platform network access from `omh`.

## Wrapper Backend Coding Delegation

When a chat message is implementation-shaped and the wrapper wants a concrete executor handoff, run `omh coding delegate` after or instead of generic chat routing. This prepares adapter data; Hermes still narrates the user-facing state:

```sh
omh coding delegate --source discord --executor codex --record "risky refactor"
```

The command returns a `coding_delegation/v1` payload with a recommended workflow, harness, executor profile, acceptance criteria, verification expectations, and a `delegation_prompt_template` that the wrapper can forward with the user message substituted. It is deterministic and uses only local catalog metadata. Without an explicit executor, wrappers can receive an executor-choice response; non-Codex executors receive prompt-only handoffs unless a tested lifecycle contract exists.

With `--record`, `omh` creates a `.omh/runtime/runs/<run-id>/` prepared runtime run only for a Codex-selected delegate payload that contains a real `executor_handoff`. Executor-choice, prompt-only, retained-Hermes, clarify, and fallback responses return `runtime.recorded=false` and must stay wrapper/session state rather than prepared run evidence. For Codex runs, `coding_delegation.json` is paired with `run.json` marked `status: prepared`, `artifact_kind: prepared_coding_delegation`, `phase: prepared`, and `observation_status: prepared_not_observed`. These artifacts store only allowlisted metadata, acceptance criteria, verification expectations, recommendation evidence, source references, `message_sha256`, and `message_length`. They mean a coding handoff was prepared; they do not mean Hermes executed the work or that a specialist lane was observed.

## Wrapper Backend Memory Context

Wrappers can run `omh memory inspect`, `omh memory pack`, and `omh memory apply` to review OMH-local or wrapper-supplied context before preparing a handoff. This emits `{MEMORY_REVIEW_SCHEMA}` and `{HANDOFF_CONTEXT_PACK_SCHEMA}` artifacts only; it does not read or mutate opaque Hermes internal memory. A context pack may be attached to an executor handoff only when unresolved conflicts are absent.

## Hermes-Facing Planning

For planning-shaped requests, wrappers or operators can run `omh hermes plan` to create a deterministic `hermes_plan/v1` planning scaffold. In normal chat, Hermes can express this plan directly through the installed skill guidance:

```sh
omh hermes plan --source discord --record "risky refactor with review"
```

With `--record`, `omh` writes a Markdown draft under `.hermes/plans/`. Weak requests also write `.hermes/context/` so Hermes can ask one blocking clarification before a final plan. The plan includes goals, non-goals, options, risks, acceptance criteria, verification, execution handoff guidance, and a review gate. Review gate entries default to `not_observed`; do not call the plan approved unless wrapper or human evidence proves the review happened.

The stdout `wrapper_contract` is the adapter contract for follow-on wrapper work. Use it instead of parsing the Markdown file. For implementation-shaped draft plans, `wrapper_contract.coding_delegate.argv_template` gives the exact `omh coding delegate --executor codex --record` argv shape for a run-backed Codex handoff after plan acceptance. For blocked or non-coding plans, `coding_delegate.available` is `false`; follow `wrapper_contract.next_action` and do not dispatch a coding handoff.

## Automatic Routing Registry

When Hermes exposes installed skill descriptions to the model, use this registry as the routing map:

{_trigger_table(definitions)}

Routing is conservative: route only on explicit invocation, strong keyword evidence, or a clear workflow-shaped request. A bare common word such as `team`, `ask`, `wiki`, or `review` is not enough when it could mean normal conversation.

## Representative Harness Registry

Use these harnesses to shape the response before adding new skills. They are quality lanes, not proof that a separate runtime role exists.

{_harness_registry(harnesses)}

Harness priority:

1. Coding requests start with `coding-handling`.
2. Multi-step durable work adds `goal-execution`.
3. Current-source or best-practice questions use the `research` harness and stay in Hermes-side evidence gathering before any coding handoff.
4. Unclear work uses `deep-interview` before `planning`.
5. Risky architecture uses `architect`, then `critic`.
6. User-visible behavior changes add `qa-specialist`.
7. Public commands, examples, or limitations add `docs-specialist`.

Recovery:

- If the right skill was not loaded, call `skills_list` or `skill_view`.
- If a slash command exists, use the explicit slash skill such as `/ralph`.
- If a skill name collides, ask the user whether to use the Hermes-native skill or the oh-my-hermes adapted skill.

## Hermes Compatibility

- Use Hermes tools and subagents when available.
- Replace unavailable goal tools with file-backed checklists or ledgers.
- Replace unavailable question renderers with one direct question through the current Hermes surface.
- Keep shell bridge behavior explicit and opt-in.

## Runtime Evidence

When local shell access or a bot wrapper is available, record prepared handoffs and observed workflow evidence under `.omh/runtime/`.

Examples:

```sh
omh coding delegate --source discord --executor codex --record "risky refactor"
omh runtime delegate --run <run-id> --requested --not-observed --result not_observed
```

Record only what is observed. A Codex-selected `coding_delegation.json` record and its `prepared_coding_delegation` run envelope prove a prepared handoff, not execution. Executor-choice and prompt-only handoffs do not create runtime runs. If Hermes does not expose delegation metadata, use `not_observed` or `not_available` instead of implying a specialist lane ran.
"""
    return SkillTemplate("oh-my-hermes", _frontmatter("oh-my-hermes", DESCRIPTIONS["oh-my-hermes"]) + "\n" + body)


def workflow_skill(name: str) -> SkillTemplate:
    definition = _definitions_by_name()[name]
    title = name.replace("-", " ").title()
    triggers = ", ".join(f"`{trigger}`" for trigger in definition.triggers)
    primary_harness = primary_harness_for_skill(name)
    body = f"""# {title}

This is a Hermes-native `{name}` workflow skill.

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
    definitions = builtin_definitions()
    harnesses = builtin_harnesses()
    lines = [
        "# Workflow Reference",
        "",
        "This file is generated from `src/skills/catalog.py`. Update the catalog first, then refresh this document.",
        "",
        "The reference describes prompt-level Hermes workflow guidance and local evidence expectations. It does not claim hidden Hermes runtime behavior.",
        "",
        "Workflow names are kept for compatibility, but each skill declares advisory wrapper guidance for whether Hermes should retain the work directly, ask the user to choose an executor, or prepare a coding handoff for coding-heavy execution.",
        "",
        TARGET_TOPOLOGY_REFERENCE_CONTEXT,
        MEMORY_CONTEXT_REFERENCE_CONTEXT,
        GOAL_STATUS_REFERENCE_CONTEXT,
        "",
        "## Skills",
        "",
    ]
    for definition in definitions:
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
                f"- Handoff policy: {definition.handoff_policy}",
                f"- Use when: {definition.use_when}",
                f"- Strong routing signals: {triggers}",
                "- Quality bar:",
                *[f"  - {item}" for item in definition.quality_bar],
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
    return {
        "schema_version": "workflow_catalog/v1",
        "description": (
            "Deterministic Hermes-native skill and harness metadata. This payload is local guidance, "
            "not proof of hidden Hermes runtime behavior."
        ),
        "skills": [_skill_payload(definition) for definition in builtin_definitions()],
        "harnesses": [_harness_payload(harness) for harness in builtin_harnesses()],
    }


def _skill_payload(definition: SkillDefinition) -> dict[str, object]:
    return {
        "name": definition.name,
        "description": definition.description,
        "use_when": definition.use_when,
        "category": definition.category,
        "phase": definition.phase,
        "triggers": list(definition.triggers),
        "primary_harness": primary_harness_for_skill(definition.name),
        "hermes_role": definition.hermes_role,
        "handoff_policy": definition.handoff_policy,
        "quality_tier": definition.quality_tier,
        "quality_bar": list(definition.quality_bar),
        "required_inputs": list(definition.required_inputs),
        "expected_outputs": list(definition.expected_outputs),
        "artifact_expectations": list(definition.artifact_expectations),
        "safety_rules": list(definition.safety_rules),
    }


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
