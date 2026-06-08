from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

STATUS_SCHEMA_VERSION = "omhm_status/v1"


def _expand_path(value: str | Path) -> Path:
    return Path(os.path.expandvars(str(value))).expanduser().resolve()


def _default_omh_home() -> Path:
    return _expand_path(os.environ.get("OMH_HOME", "~/.omh"))


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _bool_from_record(record: dict[str, Any], key: str = "observed") -> bool:
    return bool(record.get(key, False)) if record else False


def _summarize_run(run_dir: Path) -> dict[str, Any]:
    run = _read_json(run_dir / "run.json")
    coding = _read_json(run_dir / "coding_delegation.json")
    delegation = _read_json(run_dir / "delegation.json")
    wrapper = _read_json(run_dir / "wrapper.json")
    review = _read_json(run_dir / "review.json")
    ci = _read_json(run_dir / "ci.json")
    merge = _read_json(run_dir / "merge.json")
    return {
        "run_id": str(run.get("run_id", run_dir.name)),
        "workflow": str(coding.get("recommended_workflow") or run.get("skill", "unknown")),
        "harness": str(coding.get("recommended_harness") or run.get("harness", "unknown")),
        "phase": str(run.get("phase", run.get("status", "unknown"))),
        "artifact_kind": str(run.get("artifact_kind", "")),
        "observation_status": str(run.get("observation_status", coding.get("status", "unknown"))),
        "prepared_handoff": bool(coding) and str(coding.get("status", "")) == "prepared_not_observed",
        "prompt_dispatched": _bool_from_record(wrapper, "prompt_dispatched"),
        "execution_observed": _bool_from_record(delegation),
        "verification_observed": _bool_from_record(wrapper, "verification_observed"),
        "review_observed": _bool_from_record(review),
        "review_status": str(review.get("status", "not_observed" if review else "unknown")),
        "ci_observed": _bool_from_record(ci),
        "ci_status": str(ci.get("status", "not_observed" if ci else "unknown")),
        "merge_observed": _bool_from_record(merge),
        "merge_status": str(merge.get("status", "not_observed" if merge else "unknown")),
    }


def read_omhm_status(omh_home: str | Path | None = None, limit: int = 5) -> dict[str, Any]:
    safe_limit = max(0, min(int(limit), 20))
    home = _expand_path(omh_home) if omh_home else _default_omh_home()
    runtime_dir = home / "runtime"
    runs_dir = runtime_dir / "runs"
    state = _read_json(runtime_dir / "state.json")
    runs: list[dict[str, Any]] = []
    if runs_dir.exists():
        for run_json in sorted(runs_dir.glob("*/run.json"), reverse=True)[:safe_limit]:
            runs.append(_summarize_run(run_json.parent))
    return {
        "schema_version": STATUS_SCHEMA_VERSION,
        "omh_home": str(home),
        "runtime_dir": str(runtime_dir),
        "runtime_state_present": bool(state),
        "latest_run_id": str(state.get("last_run_id", "")) if state else "",
        "runs": runs,
        "evidence_boundary": {
            "prepared_handoff": "not execution evidence",
            "execution": "requires observed delegation result",
            "verification": "requires observed wrapper verification",
            "review": "requires separate review record",
            "ci": "requires separate CI record",
            "merge": "requires separate merge record",
        },
        "privacy": "metadata_only",
    }
