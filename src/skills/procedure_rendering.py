from __future__ import annotations

from ..catalogs.skill_display_names import omh_skill_display_name
from .catalog_types import ProcedureBail, SkillDefinition
from .expert_question_rendering import expert_questions_markdown


def specialist_procedure_reference_markdown(definition: SkillDefinition) -> str:
    questions = expert_questions_markdown(definition)
    return f"# {definition.name} Specialist Procedure\n\n{questions}\n\n{procedure_markdown(definition)}\n"


def _bail_lines(bail: ProcedureBail | None) -> list[str]:
    if bail is None:
        return []
    stands = ", ".join(f"`{ref}`" for ref in bail.still_stands) or "nothing yet"
    lines = [
        f"- If this step fails: {bail.downgrade_to}; still stands: {stands}; hand back: {bail.handback}"
    ]
    if bail.fallback_skill:
        lines.append(f"- Then continue with: `{omh_skill_display_name(bail.fallback_skill)}`")
    return lines


def procedure_markdown(definition: SkillDefinition) -> str:
    if not definition.procedure_steps:
        return ""
    lines = ["## Procedure", "", "Declared checks:"]
    for check in definition.procedure_checks:
        lines.extend(
            [
                f"- `{check.check_id}`",
                f"  - Required result fields: {', '.join(f'`{field}`' for field in check.required_result_fields)}",
                f"  - Criterion: {check.instruction}",
            ]
        )
    lines.append("")
    for step in definition.procedure_steps:
        lines.extend(
            [
                f"### `{step.step_id}` ({step.kind})",
                "",
                step.instruction,
                "",
                f"- Input refs: {', '.join(f'`{ref}`' for ref in step.input_refs)}",
                f"- Output refs: {', '.join(f'`{ref}`' for ref in step.output_refs)}",
                f"- Check IDs: {', '.join(f'`{check_id}`' for check_id in step.check_ids)}",
                *_bail_lines(step.on_fail),
                "",
            ]
        )
    return "\n".join(lines).rstrip()


def procedure_reference_lines(definition: SkillDefinition) -> list[str]:
    if not definition.procedure_steps:
        return []
    lines = ["- Procedure checks:"]
    for check in definition.procedure_checks:
        lines.extend(
            [
                f"  - `{check.check_id}`",
                f"    - Required result fields: {', '.join(f'`{field}`' for field in check.required_result_fields)}",
                f"    - Criterion: {check.instruction}",
            ]
        )
    lines.append("- Procedure steps:")
    for step in definition.procedure_steps:
        lines.extend(
            [
                f"  - `{step.step_id}` (`{step.kind}`)",
                f"    - Input refs: {', '.join(f'`{ref}`' for ref in step.input_refs)}",
                f"    - Output refs: {', '.join(f'`{ref}`' for ref in step.output_refs)}",
                f"    - Check IDs: {', '.join(f'`{check_id}`' for check_id in step.check_ids)}",
                *(f"    {line}" for line in _bail_lines(step.on_fail)),
                f"    - Instruction: {step.instruction}",
            ]
        )
    return lines


def procedure_check_payloads(definition: SkillDefinition) -> list[dict[str, object]]:
    return [
        {
            "check_id": check.check_id,
            "required_result_fields": list(check.required_result_fields),
            "instruction": check.instruction,
        }
        for check in definition.procedure_checks
    ]


def procedure_step_payloads(definition: SkillDefinition) -> list[dict[str, object]]:
    return [
        {
            "step_id": step.step_id,
            "kind": step.kind,
            "input_refs": list(step.input_refs),
            "output_refs": list(step.output_refs),
            "check_ids": list(step.check_ids),
            "instruction": step.instruction,
            **({"on_fail": {
                "still_stands": list(step.on_fail.still_stands),
                "downgrade_to": step.on_fail.downgrade_to,
                "handback": step.on_fail.handback,
                "fallback_skill": step.on_fail.fallback_skill,
            }} if step.on_fail is not None else {}),
        }
        for step in definition.procedure_steps
    ]


def copy_procedure_check_payloads(payloads: object) -> list[dict[str, object]]:
    if not isinstance(payloads, list):
        raise TypeError("procedure check payloads must be a list")
    copied: list[dict[str, object]] = []
    for item in payloads:
        if not isinstance(item, dict):
            raise TypeError("procedure check payload must be an object")
        copied.append(
            {
                "check_id": item["check_id"],
                "required_result_fields": list(item["required_result_fields"]),
                "instruction": item["instruction"],
            }
        )
    return copied


def copy_procedure_step_payloads(payloads: object) -> list[dict[str, object]]:
    if not isinstance(payloads, list):
        raise TypeError("procedure step payloads must be a list")
    copied: list[dict[str, object]] = []
    for item in payloads:
        if not isinstance(item, dict):
            raise TypeError("procedure step payload must be an object")
        copied.append(
            {
                "step_id": item["step_id"],
                "kind": item["kind"],
                "input_refs": list(item["input_refs"]),
                "output_refs": list(item["output_refs"]),
                "check_ids": list(item["check_ids"]),
                "instruction": item["instruction"],
                **({"on_fail": {
                    "still_stands": list(item["on_fail"]["still_stands"]),
                    "downgrade_to": item["on_fail"]["downgrade_to"],
                    "handback": item["on_fail"]["handback"],
                    "fallback_skill": item["on_fail"]["fallback_skill"],
                }} if "on_fail" in item else {}),
            }
        )
    return copied
