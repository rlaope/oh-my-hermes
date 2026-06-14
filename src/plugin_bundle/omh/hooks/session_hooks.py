from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import uuid


def on_session_end(**kwargs) -> dict[str, str] | None:
    """Record a metadata-only plugin checkpoint when OMH runtime state exists."""
    home = _expand_path(str(kwargs.get("omh_home", "") or "") or os.environ.get("OMH_HOME", "~/.omh"))
    runtime_dir = home / "runtime"
    if not runtime_dir.exists():
        return None
    runs_dir = runtime_dir / "runs"
    run_count = len(list(runs_dir.glob("*/run.json"))) if runs_dir.exists() else 0
    state = _read_json(runtime_dir / "state.json")
    if not state and run_count == 0:
        return None
    payload = {
        "schema_version": "omh_plugin_session_end/v1",
        "observed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "runtime_state_present": bool(state),
        "latest_run_id": str(state.get("last_run_id", "")) if isinstance(state, dict) else "",
        "run_count": run_count,
        "privacy": "metadata_only",
        "claim_boundary": "This checkpoint proves only that the local OMH plugin hook ran; it is not execution, review, CI, merge, or Hermes reload evidence.",
    }
    path = runtime_dir / "plugin-session-end.json"
    _atomic_write_json(path, payload)
    return {"status": "checkpoint_written", "path": str(path)}


def _expand_path(value: str) -> Path:
    return Path(os.path.expandvars(value)).expanduser().resolve()


def _read_json(path: Path) -> dict[str, object]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
