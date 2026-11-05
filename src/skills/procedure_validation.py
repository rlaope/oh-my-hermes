from __future__ import annotations

import re
import unicodedata

from .catalog_types import PROCEDURE_BAIL_LEVELS, SkillDefinition


# Migration ratchet: remove a skill as soon as all its required steps have bails.
PROCEDURE_BAIL_PENDING: frozenset[str] = frozenset()


PROCEDURE_STEP_KINDS = frozenset({"analysis", "production", "validation"})
_STEP_ID_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
_PLACEHOLDER_PREFIX_PATTERN = re.compile(r"^\s*(?:todo|tbd)(?=$|[^a-z0-9])", re.IGNORECASE)
_PLACEHOLDER_PREFIX_WRAPPERS = frozenset("`'\"*_~([{<")
_LEADING_MARKER_CONFUSABLES = str.maketrans("ТтВвΟοОоᎠꭰ", "TtBbOoOoDd")
_TOKEN_SEPARATOR_CONTROLS = frozenset("\t\n\r")
_MAX_PLACEHOLDER_SKELETON_CHARS = 5


def _normalized_placeholder_candidate(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    index = 0
    while index < len(normalized):
        character = normalized[index]
        if (
            character.isspace()
            or unicodedata.category(character) in {"Cc", "Cf"}
            or character in _PLACEHOLDER_PREFIX_WRAPPERS
        ):
            index += 1
            continue
        break

    skeleton: list[str] = []
    for character in normalized[index:]:
        category = unicodedata.category(character)
        if category == "Cf" or (
            category == "Cc" and character not in _TOKEN_SEPARATOR_CONTROLS
        ):
            continue
        skeleton.append(character)
        if len(skeleton) == _MAX_PLACEHOLDER_SKELETON_CHARS:
            break
    return "".join(skeleton)


def _has_placeholder_prefix(value: object) -> bool:
    if not isinstance(value, str):
        return False
    candidate = _normalized_placeholder_candidate(value)
    bounded_candidate = candidate[:4].translate(_LEADING_MARKER_CONFUSABLES) + candidate[4:]
    return _PLACEHOLDER_PREFIX_PATTERN.match(bounded_candidate) is not None


def _string_members(value: object) -> tuple[tuple[str, ...], bool] | None:
    if not isinstance(value, (tuple, list)):
        return None
    members = tuple(item for item in value if isinstance(item, str))
    return members, len(members) == len(value)


def procedure_violation_ids(definition: SkillDefinition) -> list[str]:
    """Return stable machine violation IDs for an opt-in procedure contract."""
    steps = definition.procedure_steps
    checks = definition.procedure_checks
    steps_supported = isinstance(steps, (tuple, list))
    checks_supported = isinstance(checks, (tuple, list))
    if steps_supported and checks_supported and not steps and not checks:
        return []

    violations: list[str] = []
    if not steps_supported or not steps:
        violations.append("procedure_steps_required")
    if not checks_supported or not checks:
        violations.append("procedure_checks_required")
    if not steps_supported or not checks_supported or not steps:
        return violations

    declared_checks: set[str] = set()
    if checks:
        for check in checks:
            check_id = getattr(check, "check_id", None)
            result_fields = getattr(check, "required_result_fields", None)
            instruction = getattr(check, "instruction", None)
            if not isinstance(check_id, str) or not _STEP_ID_PATTERN.fullmatch(check_id):
                violations.append("procedure_invalid_check_id")
            elif check_id in declared_checks:
                violations.append("procedure_duplicate_check_id")
            else:
                declared_checks.add(check_id)
            result_field_members = _string_members(result_fields)
            if result_field_members is None or not result_fields:
                violations.append("procedure_check_result_fields_required")
            elif not result_field_members[1]:
                violations.append("procedure_duplicate_or_invalid_check_result_field")
            elif any(_has_placeholder_prefix(field) for field in result_field_members[0]):
                violations.append("procedure_placeholder_check_result_field")
            elif (
                len(set(result_field_members[0])) != len(result_field_members[0])
                or any(not _STEP_ID_PATTERN.fullmatch(field) for field in result_field_members[0])
            ):
                violations.append("procedure_duplicate_or_invalid_check_result_field")
            if not isinstance(instruction, str) or not instruction.strip():
                violations.append("procedure_check_instruction_required")
            elif _has_placeholder_prefix(instruction):
                violations.append("procedure_placeholder_check_instruction")

    required_input_members = _string_members(definition.required_inputs)
    expected_output_members = _string_members(definition.expected_outputs)
    if required_input_members is None or not required_input_members[1]:
        violations.append("procedure_invalid_required_inputs")
    required_inputs = set(required_input_members[0] if required_input_members is not None else ())
    expected_outputs = set(expected_output_members[0] if expected_output_members is not None else ())

    questions = definition.expert_questions
    question_inputs: list[str] = []
    valid_questions = isinstance(questions, (tuple, list))
    if valid_questions:
        for question in questions:
            required_input = getattr(question, "required_input", None)
            if isinstance(required_input, str):
                question_inputs.append(required_input)
            else:
                valid_questions = False
    if not valid_questions:
        violations.append("procedure_invalid_expert_questions")
    referenced_inputs: set[str] = set()
    referenced_outputs: set[str] = set()
    referenced_checks: set[str] = set()
    seen_step_ids: set[str] = set()
    validation_seen = False

    for step in steps:
        step_id = getattr(step, "step_id", None)
        kind = getattr(step, "kind", None)
        input_refs = getattr(step, "input_refs", None)
        output_refs = getattr(step, "output_refs", None)
        check_ids = getattr(step, "check_ids", None)
        instruction = getattr(step, "instruction", None)

        if not isinstance(step_id, str) or not _STEP_ID_PATTERN.fullmatch(step_id):
            violations.append("procedure_invalid_step_id")
        elif step_id in seen_step_ids:
            violations.append("procedure_duplicate_step_id")
        else:
            seen_step_ids.add(step_id)

        if not isinstance(kind, str) or kind not in PROCEDURE_STEP_KINDS:
            violations.append("procedure_unknown_step_kind")
        elif kind == "validation":
            validation_seen = True

        if not isinstance(input_refs, (tuple, list)) or not input_refs:
            violations.append("procedure_step_input_refs_required")
        else:
            input_ref_members = _string_members(input_refs)
            string_input_refs = input_ref_members[0] if input_ref_members is not None else ()
            referenced_inputs.update(string_input_refs)
            if input_ref_members is None or not input_ref_members[1] or any(
                ref not in required_inputs for ref in string_input_refs
            ):
                violations.append("procedure_unknown_input_ref")

        if not isinstance(output_refs, (tuple, list)) or not output_refs:
            violations.append("procedure_step_output_refs_required")
        else:
            output_ref_members = _string_members(output_refs)
            string_output_refs = output_ref_members[0] if output_ref_members is not None else ()
            referenced_outputs.update(string_output_refs)
            if output_ref_members is None or not output_ref_members[1] or any(
                ref not in expected_outputs for ref in string_output_refs
            ):
                violations.append("procedure_unknown_output_ref")

        if not isinstance(check_ids, (tuple, list)) or not check_ids:
            violations.append("procedure_step_check_ids_required")
        else:
            check_id_members = _string_members(check_ids)
            string_check_ids = check_id_members[0] if check_id_members is not None else ()
            referenced_checks.update(string_check_ids)
            if check_id_members is None or not check_id_members[1] or any(
                check_id not in declared_checks for check_id in string_check_ids
            ):
                violations.append("procedure_unknown_check_id")

        if not isinstance(instruction, str) or not instruction.strip():
            violations.append("procedure_instruction_required")
        elif _has_placeholder_prefix(instruction):
            violations.append("procedure_placeholder_step_instruction")

    if not required_inputs.issubset(referenced_inputs):
        violations.append("procedure_missing_required_input_ref")
    if not expected_outputs.issubset(referenced_outputs):
        violations.append("procedure_missing_expected_output_ref")
    if declared_checks - referenced_checks:
        violations.append("procedure_unused_check_id")
    if not validation_seen:
        violations.append("procedure_missing_validation_step")

    question_input_set = set(question_inputs)
    if required_inputs - question_input_set:
        violations.append("procedure_missing_required_input_question")
    if question_input_set - required_inputs:
        violations.append("procedure_unknown_required_input_question")
    if len(question_input_set) != len(question_inputs):
        violations.append("procedure_duplicate_or_invalid_required_input_question")

    violations.extend(_procedure_bail_violations(definition))
    return list(dict.fromkeys(violations))


def _procedure_bail_violations(definition: SkillDefinition) -> list[str]:
    violations: list[str] = []
    earlier_outputs: set[str] = set()
    # An invalid all-analysis procedure has no required bails to migrate.
    required_bails_complete = any(
        getattr(step, "kind", None) in ("production", "validation")
        for step in definition.procedure_steps
    )
    for step in definition.procedure_steps:
        bail = getattr(step, "on_fail", None)
        if getattr(step, "kind", None) in ("production", "validation") and bail is None:
            required_bails_complete = False
            if definition.name not in PROCEDURE_BAIL_PENDING:
                violations.append("procedure_bail_required")
        if bail is not None:
            if getattr(bail, "downgrade_to", None) not in PROCEDURE_BAIL_LEVELS:
                violations.append("procedure_bail_unknown_level")
            stands = _string_members(getattr(bail, "still_stands", None))
            if stands is None or not stands[1] or any(ref not in earlier_outputs for ref in stands[0]):
                violations.append("procedure_bail_unknown_stands_ref")
            handback = getattr(bail, "handback", None)
            if not isinstance(handback, str) or not handback.strip() or _has_placeholder_prefix(handback):
                violations.append("procedure_bail_handback_required")
            fallback = getattr(bail, "fallback_skill", "")
            if fallback:
                # Catalog assembly imports this validator; resolve only after assembly.
                try:
                    from .catalog import installable_skill_names
                except ImportError:
                    pass  # Only the optional catalog-name check is unavailable.
                else:
                    if fallback == definition.name or fallback not in installable_skill_names():
                        violations.append("procedure_bail_unknown_fallback")
        outputs = _string_members(getattr(step, "output_refs", None))
        if outputs is not None:
            earlier_outputs.update(outputs[0])
    if definition.name in PROCEDURE_BAIL_PENDING and required_bails_complete:
        violations.append("procedure_bail_pending_stale")
    return violations


def validate_procedure_contract(
    definition: SkillDefinition,
    label: str,
    errors: list[str],
) -> None:
    errors.extend(f"{label} {violation}" for violation in procedure_violation_ids(definition))
