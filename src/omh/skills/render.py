from __future__ import annotations

from dataclasses import dataclass

from .catalog import DESCRIPTIONS, SkillDefinition, builtin_definitions


@dataclass(frozen=True)
class SkillTemplate:
    name: str
    content: str


def _frontmatter(name: str, description: str) -> str:
    return f"---\nname: {name}\ndescription: {description}\nmetadata:\n  hermes:\n    tags: [workflow, oh-my-hermes]\n---\n"


def _trigger_table(definitions: list[SkillDefinition]) -> str:
    lines = []
    for definition in definitions:
        if definition.name == "oh-my-hermes":
            continue
        triggers = ", ".join(f"`{trigger}`" for trigger in definition.triggers[:5])
        lines.append(f"- `{definition.name}`: {triggers}")
    return "\n".join(lines)


def router_skill() -> SkillTemplate:
    definitions = builtin_definitions()
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

## Automatic Routing Registry

When Hermes exposes installed skill descriptions to the model, use this registry as the routing map:

{_trigger_table(definitions)}

Routing is conservative: route only on explicit invocation, strong keyword evidence, or a clear workflow-shaped request. A bare common word such as `team`, `ask`, `wiki`, or `review` is not enough when it could mean normal conversation.

Recovery:

- If the right skill was not loaded, call `skills_list` or `skill_view`.
- If a slash command exists, use the explicit slash skill such as `/ralph`.
- If a skill name collides, ask the user whether to use the Hermes-native skill or the oh-my-hermes adapted skill.

## Hermes Compatibility

- Use Hermes tools and subagents when available.
- Replace unavailable goal tools with file-backed checklists or ledgers.
- Replace unavailable question renderers with one direct question through the current Hermes surface.
- Keep shell bridge behavior explicit and opt-in.
"""
    return SkillTemplate("oh-my-hermes", _frontmatter("oh-my-hermes", DESCRIPTIONS["oh-my-hermes"]) + "\n" + body)


def workflow_skill(name: str) -> SkillTemplate:
    definitions = {definition.name: definition for definition in builtin_definitions()}
    definition = definitions[name]
    title = name.replace("-", " ").title()
    triggers = ", ".join(f"`{trigger}`" for trigger in definition.triggers)
    body = f"""# {title}

This is a Hermes-native `{name}` workflow skill.

## Use When

{definition.use_when}

Strong routing signals: {triggers}

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
