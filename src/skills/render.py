from __future__ import annotations

from dataclasses import dataclass

from .catalog import DESCRIPTIONS, HarnessDefinition, SkillDefinition, builtin_definitions, builtin_harnesses, primary_harness_for_skill


@dataclass(frozen=True)
class SkillTemplate:
    name: str
    content: str


def _frontmatter(name: str, description: str) -> str:
    definitions = {definition.name: definition for definition in builtin_definitions()}
    definition = definitions.get(name)
    category = definition.category if definition else "workflow"
    phase = definition.phase if definition else "general"
    return (
        f"---\nname: {name}\ndescription: {description}\nmetadata:\n"
        f"  hermes:\n    tags: [workflow, oh-my-hermes, {category}]\n"
        f"    category: {category}\n    phase: {phase}\n---\n"
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
    inputs = ", ".join(harness.required_inputs[:3])
    outputs = ", ".join(harness.expected_outputs[:3])
    verification = ", ".join(harness.verification[:2])
    artifact_events = ", ".join(f"`{event}`" for event in harness.artifact_events[:3])
    return (
        f"- `{harness.name}`: {harness.purpose}\n"
        f"  - Use when: {harness.use_when}\n"
        f"  - Inputs: {inputs}\n"
        f"  - Outputs: {outputs}\n"
        f"  - Verification: {verification}\n"
        f"  - Runtime Evidence: events {artifact_events}; privacy `{harness.privacy_default}`\n"
        f"  - Delegation: {harness.delegation_expectation}\n"
        f"  - Fallback: {harness.fallback}"
    )


def _harness_registry(harnesses: list[HarnessDefinition]) -> str:
    return "\n".join(_harness_summary(harness) for harness in harnesses)


def _tuple_list(values: tuple[str, ...]) -> str:
    return "\n".join(f"- {value}" for value in values)


def _skill_metadata_block(definition: SkillDefinition) -> str:
    return f"""Category: `{definition.category}`
Phase: `{definition.phase}`

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

Use this skill when the user mentions oh-my-hermes or a workflow keyword such as `ralph`, `ultragoal`, `deep-interview`, `team`, `ultraqa`, `ralplan`, or `code-review`.

## Routing Contract

This is best-effort Hermes prompt guidance. It does not override Hermes core routing and it does not claim exact runtime parity with another agent framework.

Priority:

1. Explicit slash skill invocation wins.
2. Explicit workflow keywords route to the matching adapted skill when installed.
3. Broad planning requests route to `ralplan` or `plan` before implementation.
4. Persistence or finish-until-done requests route to `ralph` only after scope is concrete.
5. Unknown or conflicting signals stay in this router and ask one concise clarification question.

## Wrapper-Assisted Chat Routing

Discord, Slack, or hosted Hermes wrappers can run `omh chat route` before dispatching a plain chat message to Hermes:

```sh
omh chat route --source discord --record "risky refactor"
```

Use `route.routing_prompt_template` with `{{message}}` replaced by the received chat message as the prompt forwarded to Hermes. If the wrapper does not log stdout and wants a pre-expanded prompt, pass `--include-message` and forward `route.routing_prompt`. A `dispatch` action targets the selected workflow skill; `clarify` and `fallback` target this router so Hermes can ask one concise follow-up instead of guessing.

This is a deterministic wrapper-side decision layer. By default, stdout and runtime artifacts avoid duplicating the raw prompt body. It does not patch Hermes core or require platform network access from `omh`.

## Wrapper-Assisted Coding Delegation

When a chat message is implementation-shaped and the wrapper wants a concrete executor handoff, run `omh coding delegate` after or instead of generic chat routing:

```sh
omh coding delegate --source discord --record "risky refactor"
```

The command returns a `coding_delegation/v1` payload with a recommended workflow, harness, executor profile, acceptance criteria, verification expectations, and a `delegation_prompt_template` that the wrapper can forward with the user message substituted. It is deterministic and uses only local catalog metadata.

With `--record`, `omh` writes `coding_delegation.json` under `.omh/runtime/runs/<run-id>/`. The companion `run.json` is marked with `status: prepared`, `artifact_kind: prepared_coding_delegation`, `phase: prepared`, and `observation_status: prepared_not_observed`. These artifacts store only allowlisted metadata, acceptance criteria, verification expectations, recommendation evidence, source references, `message_sha256`, and `message_length`. Validation treats the run envelope and `coding_delegation.json` as a required pair. They mean a coding handoff was prepared; they do not mean Hermes executed the work or that a specialist lane was observed.

## Hermes-Facing Planning

For planning-shaped requests, wrappers or operators can run `omh hermes plan` to create a deterministic `hermes_plan/v1` planning scaffold:

```sh
omh hermes plan --source discord --record "risky refactor with review"
```

With `--record`, `omh` writes a Markdown draft under `.hermes/plans/`. Weak requests also write `.hermes/context/` so Hermes can ask one blocking clarification before a final plan. The plan includes goals, non-goals, options, risks, acceptance criteria, verification, execution handoff guidance, and a review gate. Review gate entries default to `not_observed`; do not call the plan approved unless wrapper or human evidence proves the review happened.

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
3. Unclear work uses `deep-interview` before `planning`.
4. Risky architecture uses `architect`, then `critic`.
5. User-visible behavior changes add `qa-specialist`.
6. Public commands, examples, or limitations add `docs-specialist`.

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
omh coding delegate --source discord --record "risky refactor"
omh runtime delegate --run <run-id> --requested --not-observed --result not_observed
```

Record only what is observed. A `coding_delegation.json` record and its `prepared_coding_delegation` run envelope prove a prepared handoff, not execution. If Hermes does not expose delegation metadata, use `not_observed` or `not_available` instead of implying a specialist lane ran.
"""
    return SkillTemplate("oh-my-hermes", _frontmatter("oh-my-hermes", DESCRIPTIONS["oh-my-hermes"]) + "\n" + body)


def workflow_skill(name: str) -> SkillTemplate:
    definitions = {definition.name: definition for definition in builtin_definitions()}
    definition = definitions[name]
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

- Start from the representative harness registry in `oh-my-hermes` when the workflow needs coding, planning, goal execution, architecture, critique, QA, or documentation lanes.
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
- When a runtime-specific mechanism appears in imported instructions, translate it to a Hermes-native artifact:
  - goal tools -> `.omh/goals/` ledgers or explicit checklists,
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
    names = [definition.name for definition in builtin_definitions()]
    return [router_skill(), *[workflow_skill(name) for name in names if name != "oh-my-hermes"]]


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
                f"- Use when: {definition.use_when}",
                f"- Strong routing signals: {triggers}",
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
                "- Inputs:",
                *[f"  - {item}" for item in harness.required_inputs],
                "- Outputs:",
                *[f"  - {item}" for item in harness.expected_outputs],
                "- Stop conditions:",
                *[f"  - {item}" for item in harness.stop_conditions],
                "- Verification:",
                *[f"  - {item}" for item in harness.verification],
                "- Artifact events:",
                *[f"  - `{item}`" for item in harness.artifact_events],
                f"- Delegation expectation: {harness.delegation_expectation}",
                f"- Privacy default: `{harness.privacy_default}`",
                f"- Fallback: {harness.fallback}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"
