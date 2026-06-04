from __future__ import annotations

import json
import re
import secrets
from json import JSONDecodeError
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .paths import OmhPaths


SCHEMA_VERSION = 1
RUN_STATUSES = ("started", "completed", "blocked", "failed", "unknown")
PRIVACY_MODES = ("metadata_only",)
DELEGATION_RESULTS = ("completed", "blocked", "failed", "not_available", "not_observed")
OBSERVED_RESULTS = ("completed", "blocked", "failed")
UNOBSERVED_RESULTS = ("not_available", "not_observed")
EVENT_LEVELS = ("debug", "info", "warning", "error")
WRAPPER_COMPLETION_STATUSES = ("started", "completed", "blocked", "failed", "unknown")


def _ensure_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)


def _ensure_private_file(path: Path) -> None:
    if not path.exists():
        path.touch(mode=0o600)
    path.chmod(0o600)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    _ensure_private_dir(path.parent)
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.chmod(0o600)
        tmp.replace(path)
        path.chmod(0o600)
    except OSError:
        if tmp.exists():
            tmp.unlink()
        raise


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("expected JSON object")
    return data


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
    return _read_json(paths.runtime_state_path)


def read_state_result(paths: OmhPaths) -> tuple[dict[str, Any] | None, str | None]:
    try:
        return read_state(paths), None
    except (OSError, JSONDecodeError, ValueError) as exc:
        return None, str(exc)


def read_state_error(paths: OmhPaths) -> str | None:
    return read_state_result(paths)[1]


def update_state(paths: OmhPaths, patch: dict[str, Any]) -> dict[str, Any]:
    current, state_error = read_state_result(paths)
    current = current or {"schema_version": SCHEMA_VERSION}
    merged = {**current, **patch, "schema_version": SCHEMA_VERSION, "updated_at": utc_now()}
    if state_error:
        merged["previous_state_error"] = state_error
    try:
        _atomic_write_json(paths.runtime_state_path, merged)
    except OSError as exc:
        merged["state_write_error"] = str(exc)
    return merged


def create_run(paths: OmhPaths, metadata: dict[str, Any]) -> dict[str, Any]:
    status = metadata.get("status", "unknown")
    if status not in RUN_STATUSES:
        raise ValueError(f"unsupported run status: {status}")
    privacy = metadata.get("privacy", "metadata_only")
    if privacy not in PRIVACY_MODES:
        raise ValueError(f"unsupported privacy mode: {privacy}")
    skill = str(metadata.get("skill", "unknown"))
    harness = str(metadata.get("harness", "unknown"))
    run_id = str(metadata.get("run_id") or _unique_run_id(paths, f"{skill}-{harness}"))
    created_at = str(metadata.get("created_at") or utc_now())
    run = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "created_at": created_at,
        "updated_at": created_at,
        "skill": skill,
        "harness": harness,
        "trigger": metadata.get("trigger", ""),
        "status": status,
        "privacy": privacy,
        "inputs_summary": metadata.get("inputs_summary", ""),
        "outputs_summary": metadata.get("outputs_summary", ""),
        "verification_summary": metadata.get("verification_summary", ""),
    }
    run_dir = paths.runtime_runs_dir / run_id
    evidence_dir = run_dir / "evidence"
    _ensure_private_dir(evidence_dir)
    _atomic_write_json(run_dir / "run.json", run)
    append_event(run_dir, {"event": "run_recorded", "level": "info", "message": f"{skill}/{harness} recorded as {status}"})
    update_state(paths, {"last_run_id": run_id})
    return run


def append_event(run_dir: Path, event: dict[str, Any]) -> dict[str, Any]:
    item = {
        "schema_version": SCHEMA_VERSION,
        "timestamp": event.get("timestamp") or utc_now(),
        "event": event.get("event", "event"),
        "level": event.get("level", "info"),
        "message": event.get("message", ""),
    }
    if "data" in event:
        item["data"] = event["data"]
    _ensure_private_dir(run_dir)
    events_path = run_dir / "events.jsonl"
    _ensure_private_file(events_path)
    with events_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(item, sort_keys=True) + "\n")
    return item


def _validate_delegation(observed: bool, result: str) -> None:
    if observed and result not in OBSERVED_RESULTS:
        raise ValueError("observed delegation requires result completed, blocked, or failed")
    if not observed and result not in UNOBSERVED_RESULTS:
        raise ValueError("unobserved delegation requires result not_available or not_observed")


def write_delegation(run_dir: Path, delegation: dict[str, Any]) -> dict[str, Any]:
    result = delegation.get("result", "not_observed")
    if result not in DELEGATION_RESULTS:
        raise ValueError(f"unsupported delegation result: {result}")
    observed = bool(delegation.get("observed", False))
    _validate_delegation(observed, result)
    record = {
        "schema_version": SCHEMA_VERSION,
        "updated_at": utc_now(),
        "requested": bool(delegation.get("requested", False)),
        "observed": observed,
        "participants": list(delegation.get("participants", [])),
        "result": result,
        "evidence_refs": list(delegation.get("evidence_refs", [])),
        "message": delegation.get("message", ""),
    }
    _atomic_write_json(run_dir / "delegation.json", record)
    append_event(
        run_dir,
        {
            "event": "delegation_recorded",
            "level": "info",
            "message": f"delegation {result}",
            "data": {"requested": record["requested"], "observed": record["observed"]},
        },
    )
    return record


def write_wrapper_contract(run_dir: Path, wrapper: dict[str, Any]) -> dict[str, Any]:
    status = wrapper.get("completion_status", "unknown")
    if status not in WRAPPER_COMPLETION_STATUSES:
        raise ValueError(f"unsupported wrapper completion status: {status}")
    record = {
        "schema_version": SCHEMA_VERSION,
        "updated_at": utc_now(),
        "prompt_dispatched": bool(wrapper.get("prompt_dispatched", False)),
        "hermes_response_observed": bool(wrapper.get("hermes_response_observed", False)),
        "verification_observed": bool(wrapper.get("verification_observed", False)),
        "completion_status": status,
        "unobserved_gaps": list(wrapper.get("unobserved_gaps", [])),
        "message": wrapper.get("message", ""),
    }
    _atomic_write_json(run_dir / "wrapper.json", record)
    append_event(
        run_dir,
        {
            "event": "wrapper_contract_recorded",
            "level": "info",
            "message": f"wrapper contract {status}",
            "data": {
                "prompt_dispatched": record["prompt_dispatched"],
                "hermes_response_observed": record["hermes_response_observed"],
                "verification_observed": record["verification_observed"],
            },
        },
    )
    return record


def _require(condition: bool, errors: list[str], message: str) -> None:
    if not condition:
        errors.append(message)


def validate_run_record(run: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    _require(run.get("schema_version") == SCHEMA_VERSION, errors, "run schema_version is invalid")
    for key in ("run_id", "created_at", "updated_at", "skill", "harness", "status", "privacy"):
        _require(isinstance(run.get(key), str) if key != "schema_version" else True, errors, f"run {key} must be a string")
    _require(run.get("status") in RUN_STATUSES, errors, f"run status is invalid: {run.get('status')!r}")
    _require(run.get("privacy") in PRIVACY_MODES, errors, f"run privacy is invalid: {run.get('privacy')!r}")
    for key in ("trigger", "inputs_summary", "outputs_summary", "verification_summary"):
        _require(isinstance(run.get(key, ""), str), errors, f"run {key} must be a string")
    return errors


def validate_event_record(event: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    _require(event.get("schema_version") == SCHEMA_VERSION, errors, "event schema_version is invalid")
    for key in ("timestamp", "event", "level", "message"):
        _require(isinstance(event.get(key), str), errors, f"event {key} must be a string")
    _require(event.get("level") in EVENT_LEVELS, errors, f"event level is invalid: {event.get('level')!r}")
    if "data" in event:
        _require(isinstance(event["data"], dict), errors, "event data must be an object")
    return errors


def validate_delegation_record(delegation: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    _require(delegation.get("schema_version") == SCHEMA_VERSION, errors, "delegation schema_version is invalid")
    _require(isinstance(delegation.get("requested"), bool), errors, "delegation requested must be boolean")
    _require(isinstance(delegation.get("observed"), bool), errors, "delegation observed must be boolean")
    _require(delegation.get("result") in DELEGATION_RESULTS, errors, f"delegation result is invalid: {delegation.get('result')!r}")
    _require(isinstance(delegation.get("participants"), list), errors, "delegation participants must be a list")
    _require(isinstance(delegation.get("evidence_refs"), list), errors, "delegation evidence_refs must be a list")
    try:
        _validate_delegation(bool(delegation.get("observed")), str(delegation.get("result")))
    except ValueError as exc:
        errors.append(str(exc))
    return errors


def validate_wrapper_record(wrapper: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    _require(wrapper.get("schema_version") == SCHEMA_VERSION, errors, "wrapper schema_version is invalid")
    for key in ("prompt_dispatched", "hermes_response_observed", "verification_observed"):
        _require(isinstance(wrapper.get(key), bool), errors, f"wrapper {key} must be boolean")
    _require(wrapper.get("completion_status") in WRAPPER_COMPLETION_STATUSES, errors, f"wrapper completion_status is invalid: {wrapper.get('completion_status')!r}")
    _require(isinstance(wrapper.get("unobserved_gaps"), list), errors, "wrapper unobserved_gaps must be a list")
    _require(isinstance(wrapper.get("message", ""), str), errors, "wrapper message must be a string")
    return errors


def list_runs(paths: OmhPaths) -> list[dict[str, Any]]:
    if not paths.runtime_runs_dir.exists():
        return []
    runs: list[dict[str, Any]] = []
    for run_json in sorted(paths.runtime_runs_dir.glob("*/run.json")):
        run = _read_json(run_json)
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
    run = _read_json(run_dir / "run.json")
    if not run:
        raise FileNotFoundError(run_id)
    evidence_dir = run_dir / "evidence"
    return {
        "run": run,
        "events": read_events(run_dir),
        "delegation": _read_json(run_dir / "delegation.json"),
        "wrapper": _read_json(run_dir / "wrapper.json"),
        "evidence": sorted(path.name for path in evidence_dir.iterdir()) if evidence_dir.exists() else [],
    }


def validate_run_dir(run_dir: Path) -> dict[str, Any]:
    errors: list[str] = []
    run_path = run_dir / "run.json"
    try:
        run = _read_json(run_path)
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
    for name, validator in (("delegation.json", validate_delegation_record), ("wrapper.json", validate_wrapper_record)):
        path = run_dir / name
        if not path.exists():
            continue
        try:
            record = _read_json(path)
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
