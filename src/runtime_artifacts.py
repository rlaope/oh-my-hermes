from __future__ import annotations

import json
import re
import secrets
from json import JSONDecodeError
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .local_store import atomic_write_json, ensure_dir, ensure_file, read_json_object, read_json_object_result, utc_now
from .paths import OmhPaths
from .runtime_records import (
    DELEGATION_RESULTS,
    EVENT_LEVELS,
    OBSERVED_RESULTS,
    OPTIONAL_RECORD_VALIDATORS,
    PRIVACY_MODES,
    RUN_STATUSES,
    SCHEMA_VERSION,
    UNOBSERVED_RESULTS,
    WRAPPER_COMPLETION_STATUSES,
    build_delegation_record,
    build_event_record,
    build_routing_record,
    build_run_record,
    build_wrapper_record,
    validate_delegation_record,
    validate_delegation_result,
    validate_event_record,
    validate_routing_record,
    validate_run_record,
    validate_wrapper_record,
)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return (slug or "run")[:48].strip("-") or "run"


def _stamp(value: datetime | str | None) -> str:
    if value is None:
        value = datetime.now(timezone.utc)
    if isinstance(value, str):
        return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def new_run_id(now: datetime | str | None = None, slug: str = "run") -> str:
    return f"{_stamp(now)}-{_slugify(slug)}"


def _unique_run_id(paths: OmhPaths, slug: str) -> str:
    for _ in range(100):
        run_id = f"{new_run_id(slug=slug)}-{secrets.token_hex(3)}"
        if not (paths.runtime_runs_dir / run_id).exists():
            return run_id
    raise RuntimeError("could not allocate unique runtime run id")


def read_state(paths: OmhPaths) -> dict[str, Any] | None:
    return read_json_object(paths.runtime_state_path)


def read_state_result(paths: OmhPaths) -> tuple[dict[str, Any] | None, str | None]:
    return read_json_object_result(paths.runtime_state_path)


def read_state_error(paths: OmhPaths) -> str | None:
    return read_state_result(paths)[1]


def update_state(paths: OmhPaths, patch: dict[str, Any]) -> dict[str, Any]:
    current, state_error = read_state_result(paths)
    current = current or {"schema_version": SCHEMA_VERSION}
    merged = {**current, **patch, "schema_version": SCHEMA_VERSION, "updated_at": utc_now()}
    if state_error:
        merged["previous_state_error"] = state_error
    try:
        atomic_write_json(paths.runtime_state_path, merged, private=True)
    except OSError as exc:
        merged["state_write_error"] = str(exc)
    return merged


def create_run(paths: OmhPaths, metadata: dict[str, Any]) -> dict[str, Any]:
    skill = str(metadata.get("skill", "unknown"))
    harness = str(metadata.get("harness", "unknown"))
    run_id = str(metadata.get("run_id") or _unique_run_id(paths, f"{skill}-{harness}"))
    run = build_run_record(metadata, run_id)
    run_dir = paths.runtime_runs_dir / run_id
    evidence_dir = run_dir / "evidence"
    ensure_dir(evidence_dir, private=True)
    atomic_write_json(run_dir / "run.json", run, private=True)
    append_event(run_dir, {"event": "run_recorded", "level": "info", "message": f"{skill}/{harness} recorded as {run['status']}"})
    update_state(paths, {"last_run_id": run_id})
    return run


def append_event(run_dir: Path, event: dict[str, Any]) -> dict[str, Any]:
    item = build_event_record(event)
    ensure_dir(run_dir, private=True)
    events_path = run_dir / "events.jsonl"
    ensure_file(events_path, private=True)
    with events_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(item, sort_keys=True) + "\n")
    return item


def write_delegation(run_dir: Path, delegation: dict[str, Any]) -> dict[str, Any]:
    record = build_delegation_record(delegation)
    atomic_write_json(run_dir / "delegation.json", record, private=True)
    append_event(
        run_dir,
        {
            "event": "delegation_recorded",
            "level": "info",
            "message": f"delegation {record['result']}",
            "data": {"requested": record["requested"], "observed": record["observed"]},
        },
    )
    return record


def write_wrapper_contract(run_dir: Path, wrapper: dict[str, Any]) -> dict[str, Any]:
    record = build_wrapper_record(wrapper)
    atomic_write_json(run_dir / "wrapper.json", record, private=True)
    append_event(
        run_dir,
        {
            "event": "wrapper_contract_recorded",
            "level": "info",
            "message": f"wrapper contract {record['completion_status']}",
            "data": {
                "prompt_dispatched": record["prompt_dispatched"],
                "hermes_response_observed": record["hermes_response_observed"],
                "verification_observed": record["verification_observed"],
            },
        },
    )
    return record


def write_routing_decision(run_dir: Path, routing: dict[str, Any]) -> dict[str, Any]:
    record = build_routing_record(routing)
    atomic_write_json(run_dir / "routing.json", record, private=True)
    append_event(
        run_dir,
        {
            "event": "routing_decision_recorded",
            "level": "info",
            "message": f"routing {record['action']} {record['selected_skill']}",
            "data": {
                "source": record["source"],
                "action": record["action"],
                "selected_skill": record["selected_skill"],
                "confidence": record["confidence"],
                "score": record["score"],
            },
        },
    )
    return record


def list_runs(paths: OmhPaths) -> list[dict[str, Any]]:
    if not paths.runtime_runs_dir.exists():
        return []
    runs: list[dict[str, Any]] = []
    for run_json in sorted(paths.runtime_runs_dir.glob("*/run.json")):
        run = read_json_object(run_json)
        if run:
            runs.append(run)
    return runs


def read_events(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "events.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def show_run(paths: OmhPaths, run_id: str) -> dict[str, Any]:
    run_dir = paths.runtime_runs_dir / run_id
    run = read_json_object(run_dir / "run.json")
    if not run:
        raise FileNotFoundError(run_id)
    evidence_dir = run_dir / "evidence"
    return {
        "run": run,
        "events": read_events(run_dir),
        "routing": read_json_object(run_dir / "routing.json"),
        "delegation": read_json_object(run_dir / "delegation.json"),
        "wrapper": read_json_object(run_dir / "wrapper.json"),
        "evidence": sorted(path.name for path in evidence_dir.iterdir()) if evidence_dir.exists() else [],
    }


def validate_run_dir(run_dir: Path) -> dict[str, Any]:
    errors: list[str] = []
    run_path = run_dir / "run.json"
    try:
        run = read_json_object(run_path)
    except (OSError, JSONDecodeError, ValueError) as exc:
        run = None
        errors.append(f"{run_path}: {exc}")
    if not run:
        errors.append(f"{run_path}: missing run.json")
    else:
        errors.extend(f"{run_path}: {error}" for error in validate_run_record(run))
    events_path = run_dir / "events.jsonl"
    if events_path.exists():
        try:
            for index, line in enumerate(events_path.read_text(encoding="utf-8").splitlines(), start=1):
                if not line.strip():
                    continue
                event = json.loads(line)
                if not isinstance(event, dict):
                    errors.append(f"{events_path}:{index}: event must be an object")
                    continue
                errors.extend(f"{events_path}:{index}: {error}" for error in validate_event_record(event))
        except (OSError, JSONDecodeError) as exc:
            errors.append(f"{events_path}: {exc}")
    else:
        errors.append(f"{events_path}: missing events.jsonl")
    for name, validator in OPTIONAL_RECORD_VALIDATORS:
        path = run_dir / name
        if not path.exists():
            continue
        try:
            record = read_json_object(path)
        except (OSError, JSONDecodeError, ValueError) as exc:
            record = None
            errors.append(f"{path}: {exc}")
        if record:
            errors.extend(f"{path}: {error}" for error in validator(record))
    return {"run_id": run_dir.name, "ok": not errors, "errors": errors}


def validate_runtime(paths: OmhPaths, run_id: str | None = None) -> dict[str, Any]:
    if run_id:
        run_dirs = [paths.runtime_runs_dir / run_id]
    else:
        run_dirs = sorted(path for path in paths.runtime_runs_dir.glob("*") if path.is_dir()) if paths.runtime_runs_dir.exists() else []
    results = [validate_run_dir(run_dir) for run_dir in run_dirs]
    return {"ok": all(result["ok"] for result in results), "runs": results}


SENSITIVE_KEY_PARTS = ("prompt", "response", "secret", "token", "api_key", "apikey", "password")


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if any(part in key.lower() for part in SENSITIVE_KEY_PARTS):
                redacted[key] = "[redacted]"
            else:
                redacted[key] = _redact(item)
        return redacted
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def export_runtime(paths: OmhPaths, redacted: bool = True) -> dict[str, Any]:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "runtime_dir": str(paths.runtime_dir),
        "state": read_state(paths),
        "runs": [show_run(paths, run["run_id"]) for run in list_runs(paths)],
    }
    if redacted:
        payload = _redact(payload)
        payload["redacted"] = True
    else:
        payload["redacted"] = False
    return payload
