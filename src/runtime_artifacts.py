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
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(path)
    path.chmod(0o600)


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


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


def read_state_error(paths: OmhPaths) -> str | None:
    try:
        read_state(paths)
    except (OSError, JSONDecodeError) as exc:
        return str(exc)
    return None


def update_state(paths: OmhPaths, patch: dict[str, Any]) -> dict[str, Any]:
    current = read_state(paths) or {"schema_version": SCHEMA_VERSION}
    merged = {**current, **patch, "schema_version": SCHEMA_VERSION, "updated_at": utc_now()}
    _atomic_write_json(paths.runtime_state_path, merged)
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
        "evidence": sorted(path.name for path in evidence_dir.iterdir()) if evidence_dir.exists() else [],
    }
