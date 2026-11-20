"""The machine-checkable contract a prepared coding handoff can carry.

A prepared handoff says what to do, what to avoid, and what counts as done in
prose, so whether an executor satisfied it is a reading, not a verdict. A
`handoff_contract/v1` block adds the checkable half:

- typed `inputs[]` — every template variable the executor-facing templates
  carry must be declared, and every declared input must be used; either
  mismatch refuses the handoff and names the offender;
- `postconditions[]` — commands compiled through the same
  `compile_verification_plan` the fanout dispatcher uses, so a postcondition is
  a runnable check with a stable id rather than a sentence;
- an optional `output_shape` — the fields the executor's final report carries;
- `forbidden_actions[]` — rendered into the executor-facing prompt section,
  never only into routing metadata;
- optional `parts[]` — `id`, `title`, `depends_on`: the work split. When two
  or more parts depend on nothing, the Codex prompt lists them and gives Codex
  permission to use subagents (OpenAI's documented trigger phrase).

OMH still executes nothing here. The executor or host runs each postcondition
and reports its exit status; `build_handoff_contract_receipt` records those
statuses, and the receipt is the only thing that promotes the contract from
`prepared_not_observed` to `observed`. A receipt accepts an integer exit status
per declared postcondition and nothing else, so a claim such as "tests passed"
has no field to land in.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping, Sequence

from ..plugin_bundle.omh import dag_core
from .fanout_contracts import FanoutContractError
from .verification_plan import compile_verification_plan

HANDOFF_CONTRACT_SCHEMA_VERSION = "handoff_contract/v1"
HANDOFF_CONTRACT_RECEIPT_SCHEMA_VERSION = "handoff_contract_receipt/v1"
HANDOFF_CONTRACT_KEY = "handoff_contract"
HANDOFF_CONTRACT_RECEIPT_FILENAME = "handoff_contract_receipt.json"

INPUT_TYPES = ("string", "number", "boolean", "date", "file")
INPUT_REQUIREMENTS = ("required", "optional", "user_prompt")
OUTPUT_SHAPE_FORMATS = ("json", "markdown", "text")
# The task text is the one input OMH itself always supplies: every prepared
# handoff template carries `{message}`, filled at dispatch time. It is declared
# by the builder, so a caller cannot declare it again or leave it out.
TASK_INPUT_NAME = "message"
TASK_INPUT = {
    "name": TASK_INPUT_NAME,
    "input_type": "string",
    "requirement": "required",
    "default": None,
}

MAX_INPUTS = 16
MAX_POSTCONDITIONS = 16
MAX_FORBIDDEN_ACTIONS = 16
MAX_OUTPUT_FIELDS = 32
MAX_PARTS = 16
MAX_TEXT_CHARS = 300

RECEIPT_STATUSES = ("observed", "prepared_not_observed")
RECEIPT_VERDICTS = ("passed", "failed", "not_observed")

HANDOFF_CONTRACT_CLAIM_BOUNDARY = (
    "A handoff contract declares typed inputs, postcondition commands, an output shape, and forbidden "
    "actions. It is prepared_not_observed until a receipt records an exit status for every postcondition; "
    "OMH does not run the commands, and no wording in an executor report can stand in for an exit status."
)
HANDOFF_CONTRACT_RECEIPT_CLAIM_BOUNDARY = (
    "A handoff contract receipt records the exit status the executor or host reported for each declared "
    "postcondition. It is observed only when every postcondition has one, and passed only when every one is "
    "0. It is not review, CI, merge-readiness, or merge evidence."
)

_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_POSTCONDITION_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_TEMPLATE_VARIABLE_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


class HandoffContractError(ValueError):
    """A contract declaration, handoff, or receipt that fails the contract."""


def build_handoff_contract(declaration: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize a caller's declaration into a `handoff_contract/v1` block.

    Shape errors raise here, naming the field. Whether each input is used and
    each template variable declared can only be judged against a rendered
    handoff, so that check is `handoff_contract_errors`.
    """
    if not isinstance(declaration, Mapping):
        raise HandoffContractError("handoff_contract declaration must be a JSON object")
    known = {"inputs", "postconditions", "output_shape", "forbidden_actions", "parts"}
    unknown = sorted(str(key) for key in declaration if key not in known)
    if unknown:
        raise HandoffContractError(f"handoff_contract has unknown field(s): {', '.join(unknown)}")
    contract: dict[str, Any] = {
        "schema_version": HANDOFF_CONTRACT_SCHEMA_VERSION,
        "status": "prepared_not_observed",
        "inputs": [dict(TASK_INPUT), *_inputs(declaration.get("inputs", []))],
        "postconditions": _postconditions(declaration.get("postconditions")),
        "forbidden_actions": _texts(
            declaration.get("forbidden_actions", []), "forbidden_actions", MAX_FORBIDDEN_ACTIONS
        ),
        "claim_boundary": HANDOFF_CONTRACT_CLAIM_BOUNDARY,
    }
    output_shape = declaration.get("output_shape")
    if output_shape is not None:
        contract["output_shape"] = _output_shape(output_shape)
    # Optional, and absent from the contract unless declared, so a contract
    # without parts keeps its digest.
    parts = declaration.get("parts")
    if parts is not None:
        contract["parts"] = _parts(parts)
    return contract


def _parts(value: object) -> list[dict[str, Any]]:
    """The declared work parts: `id`, `title`, and the `depends_on` edges between them.

    The Codex handoff reads these as the structural signal for parallel work:
    parts with no `depends_on` can move ahead independently.
    """
    if not isinstance(value, list) or not value or len(value) > MAX_PARTS:
        raise HandoffContractError(f"handoff_contract parts must be a list of 1 to {MAX_PARTS} objects")
    parts: list[dict[str, Any]] = []
    for index, entry in enumerate(value):
        if not isinstance(entry, Mapping) or set(entry) - {"id", "title", "depends_on"}:
            raise HandoffContractError(
                f"handoff_contract part at index {index} must be an object with only id, title, depends_on"
            )
        part_id = entry.get("id")
        if not isinstance(part_id, str) or not _POSTCONDITION_ID_RE.match(part_id):
            raise HandoffContractError(f"handoff_contract part at index {index} has an invalid id: {part_id!r}")
        if any(part["id"] == part_id for part in parts):
            raise HandoffContractError(f"handoff_contract part {part_id!r} is declared twice")
        title = entry.get("title")
        if not isinstance(title, str) or not title.strip() or len(title) > MAX_TEXT_CHARS:
            raise HandoffContractError(
                f"handoff_contract part {part_id!r} title must be a non-empty string of at most {MAX_TEXT_CHARS} chars"
            )
        depends_on = entry.get("depends_on", [])
        if not isinstance(depends_on, list) or not all(isinstance(item, str) for item in depends_on):
            raise HandoffContractError(f"handoff_contract part {part_id!r} depends_on must list other part ids")
        parts.append({"id": part_id, "title": " ".join(title.split()), "depends_on": sorted(set(depends_on))})
    ids = [part["id"] for part in parts]
    for part in parts:
        problem = dag_core.edge_problem(part["id"], part["depends_on"], ids)
        if problem is not None:
            raise HandoffContractError(f"handoff_contract part {part['id']!r} depends_on {problem[1]!r}: {problem[0]}")
    if dag_core.layers(ids, {part["id"]: part["depends_on"] for part in parts}) is None:
        raise HandoffContractError("handoff_contract parts depends_on contains a cycle")
    return parts


def independent_parts(contract: Mapping[str, Any] | None) -> list[Mapping[str, Any]]:
    """The declared parts that depend on no other part, in declaration order."""
    raw = contract.get("parts") if isinstance(contract, Mapping) else None
    if not isinstance(raw, list):
        return []
    return [part for part in raw if isinstance(part, Mapping) and not part.get("depends_on")]


def _inputs(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > MAX_INPUTS:
        raise HandoffContractError(f"handoff_contract inputs must be a list of at most {MAX_INPUTS} objects")
    inputs: list[dict[str, Any]] = []
    seen = {TASK_INPUT_NAME}
    for index, entry in enumerate(value):
        if not isinstance(entry, Mapping):
            raise HandoffContractError(f"handoff_contract input at index {index} must be an object")
        name = entry.get("name")
        if not isinstance(name, str) or not _NAME_RE.match(name):
            raise HandoffContractError(f"handoff_contract input at index {index} has an invalid name: {name!r}")
        if name in seen:
            reason = "is supplied by OMH" if name == TASK_INPUT_NAME else "is declared twice"
            raise HandoffContractError(f"handoff_contract input {name!r} {reason}")
        seen.add(name)
        input_type = entry.get("input_type", "string")
        if input_type not in INPUT_TYPES:
            raise HandoffContractError(
                f"handoff_contract input {name!r} input_type must be one of {', '.join(INPUT_TYPES)}"
            )
        requirement = entry.get("requirement", "required")
        if requirement not in INPUT_REQUIREMENTS:
            raise HandoffContractError(
                f"handoff_contract input {name!r} requirement must be one of {', '.join(INPUT_REQUIREMENTS)}"
            )
        default = entry.get("default")
        if requirement == "optional" and default is None:
            raise HandoffContractError(f"handoff_contract optional input {name!r} must declare a default")
        if requirement != "optional" and default is not None:
            raise HandoffContractError(f"handoff_contract {requirement} input {name!r} must not declare a default")
        if default is not None and not isinstance(default, (str, int, float, bool)):
            raise HandoffContractError(f"handoff_contract input {name!r} default must be a scalar")
        inputs.append({"name": name, "input_type": input_type, "requirement": requirement, "default": default})
    return inputs


def _postconditions(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value or len(value) > MAX_POSTCONDITIONS:
        raise HandoffContractError(
            f"handoff_contract postconditions must be a list of 1 to {MAX_POSTCONDITIONS} command objects"
        )
    commands: list[str] = []
    checks: list[dict[str, str]] = []
    for index, entry in enumerate(value):
        if not isinstance(entry, Mapping):
            raise HandoffContractError(f"handoff_contract postcondition at index {index} must be an object")
        postcondition_id = entry.get("id")
        if not isinstance(postcondition_id, str) or not _POSTCONDITION_ID_RE.match(postcondition_id):
            raise HandoffContractError(
                f"handoff_contract postcondition at index {index} has an invalid id: {postcondition_id!r}"
            )
        if any(check["id"] == postcondition_id for check in checks):
            raise HandoffContractError(f"handoff_contract postcondition {postcondition_id!r} is declared twice")
        command = entry.get("command")
        if not isinstance(command, str) or not command.strip() or len(command) > MAX_TEXT_CHARS:
            raise HandoffContractError(
                f"handoff_contract postcondition {postcondition_id!r} command must be a non-empty string "
                f"of at most {MAX_TEXT_CHARS} chars"
            )
        commands.append(" ".join(command.split()))
        checks.append({"id": postcondition_id})
    try:
        plan = compile_verification_plan(
            {"verification_commands": commands, "verification_checks": checks},
            fanout_id=HANDOFF_CONTRACT_SCHEMA_VERSION,
            unit_id="postconditions",
        )
    except FanoutContractError as exc:
        raise HandoffContractError(f"handoff_contract postcondition is not a runnable command: {exc}") from exc
    if plan is None:
        raise HandoffContractError("handoff_contract postconditions compiled to no runnable command")
    return [
        {
            "id": node.declared_id,
            "check_id": node.check_id,
            "command": node.command,
            "claim_scope": node.claim_scope,
            "verdict_source": "exit_status",
        }
        for node in plan.nodes
    ]


def _texts(value: object, field: str, limit: int) -> list[str]:
    if not isinstance(value, list) or len(value) > limit:
        raise HandoffContractError(f"handoff_contract {field} must be a list of at most {limit} strings")
    texts: list[str] = []
    for index, entry in enumerate(value):
        if not isinstance(entry, str) or not entry.strip() or len(entry) > MAX_TEXT_CHARS:
            raise HandoffContractError(
                f"handoff_contract {field} entry at index {index} must be a non-empty string "
                f"of at most {MAX_TEXT_CHARS} chars"
            )
        texts.append(" ".join(entry.split()))
    return texts


def _output_shape(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise HandoffContractError("handoff_contract output_shape must be an object")
    output_format = value.get("format", "json")
    if output_format not in OUTPUT_SHAPE_FORMATS:
        raise HandoffContractError(
            f"handoff_contract output_shape format must be one of {', '.join(OUTPUT_SHAPE_FORMATS)}"
        )
    fields = value.get("required_fields")
    if not isinstance(fields, list) or not fields or len(fields) > MAX_OUTPUT_FIELDS:
        raise HandoffContractError(
            f"handoff_contract output_shape required_fields must list 1 to {MAX_OUTPUT_FIELDS} field names"
        )
    for field in fields:
        if not isinstance(field, str) or not _NAME_RE.match(field):
            raise HandoffContractError(f"handoff_contract output_shape has an invalid field name: {field!r}")
    if len(set(fields)) != len(fields):
        raise HandoffContractError("handoff_contract output_shape required_fields must not repeat a field")
    return {"format": output_format, "required_fields": list(fields)}


def handoff_templates(handoff: Mapping[str, Any]) -> list[str]:
    """Every executor-facing template a wrapper fills at dispatch time."""
    templates = [str(handoff.get("prompt_template", ""))]
    for key in ("invocation", "codex_invocation"):
        invocation = handoff.get(key)
        if isinstance(invocation, Mapping):
            templates.append(str(invocation.get("dispatch_text_template", "")))
    return [template for template in templates if template]


def template_variables(templates: Sequence[str]) -> list[str]:
    """The `{name}` placeholders the templates carry, sorted and unique."""
    return sorted({match for template in templates for match in _TEMPLATE_VARIABLE_RE.findall(template)})


def handoff_contract_errors(handoff: Mapping[str, Any]) -> list[str]:
    """Why the handoff's templates and its contract's inputs disagree, by name.

    Empty when the handoff carries no contract: the check applies only to a
    handoff that declared one.
    """
    contract = handoff.get(HANDOFF_CONTRACT_KEY)
    if contract is None:
        return []
    if not isinstance(contract, Mapping) or contract.get("schema_version") != HANDOFF_CONTRACT_SCHEMA_VERSION:
        return [f"handoff_contract schema_version must be {HANDOFF_CONTRACT_SCHEMA_VERSION}"]
    raw_inputs = contract.get("inputs")
    declared = [
        str(entry.get("name"))
        for entry in (raw_inputs if isinstance(raw_inputs, list) else [])
        if isinstance(entry, Mapping)
    ]
    used = template_variables(handoff_templates(handoff))
    errors = [
        f"handoff_contract input {name!r} is declared but no handoff template uses it"
        for name in declared
        if name not in used
    ]
    errors.extend(
        f"handoff_contract template variable {name!r} has no input declaration"
        for name in used
        if name not in declared
    )
    return errors


def require_valid_handoff_contract(handoff: Mapping[str, Any]) -> None:
    """Refuse a handoff whose contract fails validation, naming each offender."""
    errors = handoff_contract_errors(handoff)
    if errors:
        raise HandoffContractError("; ".join(errors))


def contract_digest(contract: Mapping[str, Any]) -> str:
    """The digest a receipt binds to, so a receipt cannot cross contracts."""
    canonical = json.dumps(contract, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_handoff_contract_receipt(
    contract: Mapping[str, Any], exit_statuses: Mapping[str, object]
) -> dict[str, Any]:
    """Record reported exit statuses against the contract's postconditions.

    An exit status is an integer. Anything else — `"passed"`, `True`, a
    sentence — is refused with the postcondition's name, because a verdict read
    from wording is exactly what the contract exists to replace. A postcondition
    with no recorded status stays `not_observed`, and so does the receipt.
    """
    postconditions = [
        entry for entry in contract.get("postconditions", []) if isinstance(entry, Mapping)
    ]
    declared_ids = [str(entry.get("id")) for entry in postconditions]
    unknown = sorted(str(key) for key in exit_statuses if key not in declared_ids)
    if unknown:
        raise HandoffContractError(f"exit status recorded for undeclared postcondition(s): {', '.join(unknown)}")
    rows: list[dict[str, Any]] = []
    for entry in postconditions:
        postcondition_id = str(entry.get("id"))
        exit_status = exit_statuses.get(postcondition_id)
        if exit_status is not None and (isinstance(exit_status, bool) or not isinstance(exit_status, int)):
            raise HandoffContractError(
                f"postcondition {postcondition_id!r} exit status must be an integer, got {exit_status!r}"
            )
        if exit_status is None:
            status = "not_observed"
        else:
            status = "passed" if exit_status == 0 else "failed"
        rows.append(
            {
                "id": postcondition_id,
                "check_id": str(entry.get("check_id", "")),
                "exit_status": exit_status,
                "status": status,
            }
        )
    unobserved = [row["id"] for row in rows if row["status"] == "not_observed"]
    observed = bool(rows) and not unobserved
    if any(row["status"] == "failed" for row in rows):
        verdict = "failed"
    elif observed:
        verdict = "passed"
    else:
        verdict = "not_observed"
    return {
        "schema_version": HANDOFF_CONTRACT_RECEIPT_SCHEMA_VERSION,
        "contract_digest": contract_digest(contract),
        "status": "observed" if observed else "prepared_not_observed",
        "verdict": verdict,
        "verdict_source": "exit_status",
        "postconditions": rows,
        "unobserved_postconditions": unobserved,
        "claim_boundary": HANDOFF_CONTRACT_RECEIPT_CLAIM_BOUNDARY,
    }


def contract_verification_observed(contract: Mapping[str, Any], receipt: object) -> bool:
    """True only when a receipt for THIS contract recorded every exit status as 0."""
    if not isinstance(receipt, Mapping):
        return False
    return (
        receipt.get("schema_version") == HANDOFF_CONTRACT_RECEIPT_SCHEMA_VERSION
        and receipt.get("contract_digest") == contract_digest(contract)
        and receipt.get("status") == "observed"
        and receipt.get("verdict") == "passed"
    )


def contract_verification_summary(contract: Mapping[str, Any], receipt: object) -> dict[str, Any]:
    """The contract's state as a status reader shows it: never run reads as never run."""
    if not isinstance(receipt, Mapping) or receipt.get("contract_digest") != contract_digest(contract):
        return {
            "schema_version": HANDOFF_CONTRACT_SCHEMA_VERSION,
            "status": "prepared_not_observed",
            "verdict": "not_observed",
            "reason": "no_exit_status_recorded",
            "unobserved_postconditions": [
                str(entry.get("id"))
                for entry in contract.get("postconditions", [])
                if isinstance(entry, Mapping)
            ],
        }
    return {
        "schema_version": HANDOFF_CONTRACT_SCHEMA_VERSION,
        "status": str(receipt.get("status")),
        "verdict": str(receipt.get("verdict")),
        "unobserved_postconditions": list(receipt.get("unobserved_postconditions", [])),
    }
