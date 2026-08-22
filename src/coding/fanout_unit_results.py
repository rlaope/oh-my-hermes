"""The `fanout_unit_result/v1` contract: what a unit *reports* about itself.

A dispatched unit is a foreign CLI process. Its exit code proves that the
process ended, nothing about what it verified, so this schema exists to give
the executor one bounded, typed place to say what it did — and to keep that
statement labelled as a report rather than as evidence.

Two rules carry the whole design:

* Validation is a *shape* check. A payload that passes here is well-formed;
  it is never thereby true. Only the dispatcher's own observations advance a
  unit's lifecycle, so nothing in this module infers a status.
* Provenance rides on every check row. `reported_by` says who wrote the row,
  `observed_by` says whether the dispatcher itself saw it, and
  `observation_source` names the journal event that observation came from.
  A row written by the executor cannot promote itself to a dispatcher
  observation without naming that source — that is the one way an executor
  could otherwise launder a claim into the evidence ladder.

Unknown keys are accepted and preserved, at both the payload and check-row
level. A newer executor writing an extra field must not be rejected by an
older dispatcher, and dropping the field silently would make the sidecar's
stored copy disagree with what the executor wrote. Rejecting unknown keys
would also mean any future `fanout_unit_result` field is a breaking change
for every already-installed dispatcher, which is exactly the coupling the
versioned-contract split exists to avoid.
"""

from __future__ import annotations

import re
from typing import Mapping, Sequence

from .fanout_contracts import FANOUT_ID_PATTERN


FANOUT_UNIT_RESULT_SCHEMA_VERSION = "fanout_unit_result/v1"
# Exit-code shaped, and deliberately only that. Anything richer (schema
# validity, observed verification, integration eligibility) is the
# dispatcher's to decide from its own observations, never the executor's to
# assert here.
FANOUT_UNIT_RESULT_PROCESS_STATUSES = ("process_succeeded", "process_failed")
FANOUT_UNIT_RESULT_CHECK_STATUSES = ("passed", "failed", "skipped")
FANOUT_UNIT_RESULT_REPORTERS = ("executor", "dispatcher")
# Only the dispatcher observes. An executor claiming to have observed itself
# is the report it already made, restated.
FANOUT_UNIT_RESULT_OBSERVERS = ("dispatcher",)
FANOUT_UNIT_RESULT_CLAIM_BOUNDARY = (
    "A fanout unit result is what one dispatched unit reported about its own run. "
    "A valid result proves the payload's shape, not that any listed check ran or passed; "
    "only rows the dispatcher observed itself carry observed_by and an observation_source."
)

# The same slug shape the contract builder accepts, restated rather than
# imported so result validation does not depend on the contract builder.
_UNIT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_FANOUT_ID_RE = re.compile(FANOUT_ID_PATTERN)
# Short-hex through full: `git rev-parse --short` yields 7+, a full object id
# is 40. Anything outside that window is not a SHA an executor read from git.
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")

_CHECK_KEYS = ("command", "status", "evidence_ref", "reported_by", "observed_by", "observation_source")


def validate_unit_result(payload: Mapping[str, object]) -> dict[str, object]:
    """Return the normalized `fanout_unit_result/v1` payload, or raise.

    Every failure raises `ValueError` naming the exact offending field, in the
    style of `validate_fanout_units`, because the dispatcher records that
    message verbatim as the reason a sidecar was rejected.
    """
    if not isinstance(payload, Mapping):
        raise ValueError(f"unit result payload must be an object; got {type(payload).__name__}")

    result: dict[str, object] = {key: value for key, value in payload.items()}
    result["schema_version"] = _validated_schema_version(payload.get("schema_version"))
    result["unit_id"] = _validated_slug(payload.get("unit_id"), "unit_id")
    result["run_id"] = _validated_text(payload.get("run_id"), "run_id")
    result["fanout_id"] = _validated_fanout_id(payload.get("fanout_id"))
    result["base_sha"] = _validated_sha(payload.get("base_sha"), "base_sha")
    result["head_sha"] = _validated_sha(payload.get("head_sha"), "head_sha")
    result["process_status"] = _validated_choice(
        payload.get("process_status"), "process_status", FANOUT_UNIT_RESULT_PROCESS_STATUSES
    )
    result["changed_paths"] = _validated_changed_paths(payload.get("changed_paths"))
    result["checks"] = _validated_checks(payload.get("checks"))
    result["findings"] = _validated_findings(payload.get("findings"))
    if "schema_error" in payload:
        result["schema_error"] = _validated_text(payload.get("schema_error"), "schema_error")
    return result


def validate_check_rows(rows: object) -> list[dict[str, object]]:
    """Return normalized check rows, or raise.

    The same gate `validate_unit_result` applies to a payload's `checks`,
    exposed on its own so rows the dispatcher writes about its own observations
    pass through the identical schema — including the provenance rule — rather
    than a second, looser copy of it.
    """
    return _validated_checks(rows)


def _validated_schema_version(value: object) -> str:
    if value != FANOUT_UNIT_RESULT_SCHEMA_VERSION:
        raise ValueError(
            f"schema_version must be {FANOUT_UNIT_RESULT_SCHEMA_VERSION!r}; got {value!r}"
        )
    return FANOUT_UNIT_RESULT_SCHEMA_VERSION


def _validated_slug(value: object, field: str) -> str:
    if not isinstance(value, str) or not _UNIT_ID_RE.match(value):
        raise ValueError(f"{field} must be a lowercase slug; got {value!r}")
    return value


def _validated_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string; got {value!r}")
    return value


def _validated_fanout_id(value: object) -> str:
    if not isinstance(value, str) or not _FANOUT_ID_RE.match(value):
        raise ValueError(f"fanout_id must match {FANOUT_ID_PATTERN}; got {value!r}")
    return value


def _validated_sha(value: object, field: str) -> str:
    if not isinstance(value, str) or not _GIT_SHA_RE.match(value):
        raise ValueError(f"{field} must be a 7-to-40 character lowercase git sha; got {value!r}")
    return value


def _validated_choice(value: object, field: str, allowed: Sequence[str]) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(f"{field} must be one of {', '.join(allowed)}; got {value!r}")
    return value


def _validated_optional_choice(value: object, field: str, allowed: Sequence[str]) -> str | None:
    if value is None:
        return None
    return _validated_choice(value, field, allowed)


def _validated_optional_text(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _validated_text(value, field)


def _validated_changed_paths(value: object) -> list[str]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"changed_paths must be a list of repo-relative paths; got {value!r}")
    paths: list[str] = []
    for entry in value:
        if not isinstance(entry, str) or not entry.strip():
            raise ValueError(f"changed_paths entries must be non-empty strings; got {entry!r}")
        # Absolute and escaping paths are refused rather than resolved: a unit
        # reports what it changed *inside* the repo, and a path pointing out of
        # it is either a mistake or an attempt to describe work the boundary
        # never covered.
        if entry.startswith("/") or entry.startswith("~") or re.match(r"^[A-Za-z]:[\\/]", entry):
            raise ValueError(f"changed_paths entries must be repo-relative; got {entry!r}")
        segments = entry.replace("\\", "/").split("/")
        if ".." in segments:
            raise ValueError(f"changed_paths entries must not escape the repo with '..'; got {entry!r}")
        paths.append(entry)
    return paths


def _validated_checks(value: object) -> list[dict[str, object]]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"checks must be a list of check rows; got {value!r}")
    return [_validated_check_row(row, index) for index, row in enumerate(value)]


def _validated_check_row(row: object, index: int) -> dict[str, object]:
    if not isinstance(row, Mapping):
        raise ValueError(f"checks[{index}] must be an object; got {type(row).__name__}")
    normalized: dict[str, object] = {key: value for key, value in row.items()}
    normalized["command"] = _validated_text(row.get("command"), f"checks[{index}].command")
    normalized["status"] = _validated_choice(
        row.get("status"), f"checks[{index}].status", FANOUT_UNIT_RESULT_CHECK_STATUSES
    )
    normalized["evidence_ref"] = _validated_optional_text(
        row.get("evidence_ref"), f"checks[{index}].evidence_ref"
    )
    normalized["reported_by"] = _validated_choice(
        row.get("reported_by"), f"checks[{index}].reported_by", FANOUT_UNIT_RESULT_REPORTERS
    )
    normalized["observed_by"] = _validated_optional_choice(
        row.get("observed_by"), f"checks[{index}].observed_by", FANOUT_UNIT_RESULT_OBSERVERS
    )
    normalized["observation_source"] = _validated_optional_text(
        row.get("observation_source"), f"checks[{index}].observation_source"
    )
    _validate_row_provenance(normalized, index)
    return normalized


def _validate_row_provenance(row: Mapping[str, object], index: int) -> None:
    """Refuse a row whose observation claim has nothing behind it.

    Both directions are errors, and both name `observation_source` because
    that field is the one carrying the proof: an observation with no source is
    an unbacked claim, and a source with no observer is a reference nothing
    asserts.
    """
    observed_by = row.get("observed_by")
    observation_source = row.get("observation_source")
    if observed_by is not None and observation_source is None:
        raise ValueError(
            f"checks[{index}].observation_source is required when observed_by is "
            f"{observed_by!r} (reported_by={row.get('reported_by')!r}); a dispatcher observation "
            "must name the journal event it came from"
        )
    if observation_source is not None and observed_by is None:
        raise ValueError(
            f"checks[{index}].observation_source requires observed_by to name the observer"
        )


def _validated_findings(value: object) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"findings must be a list of strings; got {value!r}")
    findings: list[str] = []
    for entry in value:
        if not isinstance(entry, str):
            raise ValueError(f"findings entries must be strings; got {entry!r}")
        findings.append(entry)
    return findings
