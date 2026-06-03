from __future__ import annotations

from dataclasses import dataclass


CORE_SKILLS = [
    "oh-my-hermes",
    "ralph",
    "ultragoal",
    "deep-interview",
    "team",
    "ultraqa",
    "plan",
    "ralplan",
    "code-review",
    "ai-slop-cleaner",
    "best-practice-research",
    "autoresearch-goal",
    "performance-goal",
    "wiki",
    "ask",
    "cancel",
    "skill",
    "doctor",
]


DESCRIPTIONS = {
    "oh-my-hermes": "Router guidance for using adapted OMX/Codex skills inside Hermes Agent.",
    "ralph": "Hermes adaptation of OMX Ralph: persistent execution with verification and review.",
    "ultragoal": "Hermes adaptation of OMX Ultragoal: file-backed durable goal ledgers.",
    "deep-interview": "Hermes adaptation of OMX Deep Interview: one-question-at-a-time clarification.",
    "team": "Hermes adaptation of OMX Team: coordinated parallel or sequential work lanes.",
    "ultraqa": "Hermes adaptation of OMX UltraQA: adversarial QA and fix loops.",
    "plan": "Hermes adaptation of OMX Plan: structured planning before execution.",
    "ralplan": "Hermes adaptation of OMX Ralplan: consensus planning with review gates.",
    "code-review": "Hermes adaptation of OMX Code Review: bug-first review with evidence.",
    "ai-slop-cleaner": "Hermes adaptation of OMX AI slop cleaner: behavior-preserving cleanup.",
    "best-practice-research": "Hermes adaptation for bounded official/upstream best-practice research.",
    "autoresearch-goal": "Hermes adaptation for durable research-goal execution.",
    "performance-goal": "Hermes adaptation for measurable performance-goal execution.",
    "wiki": "Hermes adaptation for maintaining a project-local markdown wiki.",
    "ask": "Hermes adaptation for consulting an external advisor when configured.",
    "cancel": "Hermes adaptation for ending active workflow state cleanly.",
    "skill": "Hermes adaptation for managing local skills.",
    "doctor": "Hermes adaptation for diagnosing oh-my-hermes installation health.",
}


@dataclass(frozen=True)
class SkillTemplate:
    name: str
    content: str


def _frontmatter(name: str, description: str) -> str:
    return f"---\nname: {name}\ndescription: {description}\nmetadata:\n  hermes:\n    tags: [omx, oh-my-hermes]\n---\n"


def router_skill() -> SkillTemplate:
    body = """# Oh My Hermes Router

Use this skill when the user mentions OMX, oh-my-codex, oh-my-hermes, or a workflow keyword such as `ralph`, `ultragoal`, `deep-interview`, `team`, `ultraqa`, `ralplan`, or `code-review`.

## Routing Contract

This is best-effort Hermes prompt guidance. It does not override Hermes core routing and it does not claim exact Codex/OMX runtime parity.

Priority:

1. Explicit slash skill invocation wins.
2. Explicit workflow keywords route to the matching adapted skill when installed.
3. Broad planning requests route to `ralplan` or `plan` before implementation.
4. Persistence or finish-until-done requests route to `ralph` only after scope is concrete.
5. Unknown or conflicting signals stay in this router and ask one concise clarification question.

Recovery:

- If the right skill was not loaded, call `skills_list` or `skill_view`.
- If a slash command exists, use the explicit slash skill such as `/ralph`.
- If a skill name collides, ask the user whether to use the Hermes-native skill or the oh-my-hermes adapted skill.

## Hermes Compatibility

- Use Hermes tools and subagents when available.
- Replace Codex goal tools with file-backed checklists or ledgers.
- Replace `omx question` with one direct question through the current Hermes surface.
- Treat shelling out to `omx` as optional bridge behavior only when the user explicitly asks and `omx` is installed.
"""
    return SkillTemplate("oh-my-hermes", _frontmatter("oh-my-hermes", DESCRIPTIONS["oh-my-hermes"]) + "\n" + body)


def workflow_skill(name: str) -> SkillTemplate:
    title = name.replace("-", " ").title()
    body = f"""# {title}

This is a Hermes-compatible adaptation of the OMX/Codex `{name}` workflow.

## Use When

Use this skill when the user explicitly invokes `{name}` or when `oh-my-hermes` routing identifies this workflow as the safest next step.

## Hermes Compatibility Contract

- Preserve the OMX workflow intent, stop conditions, and verification discipline.
- Use Hermes-native tools, file operations, and subagent/delegation features when available.
- Do not require Codex-only `get_goal`, `create_goal`, `update_goal`, native Codex role prompts, tmux overlays, or `omx question`.
- When a Codex-only mechanism appears in upstream OMX instructions, translate it to a Hermes-native artifact:
  - goal tools -> `.omh/goals/` ledgers or explicit checklists,
  - `omx question` -> one concise question in the current Hermes interface,
  - Codex native subagents -> Hermes delegation when available, otherwise sequential lanes,
  - `omx` shell commands -> optional bridge mode only.

## Execution Rules

1. Load supporting context with `skills_list` / `skill_view` when needed.
2. State the workflow target, constraints, validation evidence, and stop condition.
3. Keep progress evidence-backed.
4. Verify with the smallest relevant test or inspection before claiming completion.
5. If Hermes cannot provide a required runtime capability, say so and use the fallback above.
"""
    return SkillTemplate(name, _frontmatter(name, DESCRIPTIONS[name]) + "\n" + body)


def builtin_skill_templates() -> list[SkillTemplate]:
    return [router_skill(), *[workflow_skill(name) for name in CORE_SKILLS if name != "oh-my-hermes"]]

