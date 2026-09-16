from __future__ import annotations

from .. import runtime_paths

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import uuid

from ..degradation import runtime_binding_degradation
from ..host_observation import observe_plugin_hook_call
from .nudge_budget import note_delegated_session


def subagent_start(**kwargs) -> None:
    """Record that ``child_session_id`` names a delegated lane, not an orchestrator.

    The one thing OMH takes from this hook. A delegated child runs under its
    own session id, and the tool-result seam the engagement nudges ride carries
    no agent identity, so without this record those nudges cannot tell a
    subagent from the session that spawned it -- and would ask a subagent to
    declare the parent's checklist.

    Observation only: it writes no file, reads no runtime state, returns
    nothing, and never blocks a spawn. A host that does not call it is a host
    with no children to mistake for orchestrators, because the same
    `tools/delegate_tool.py` that creates a child emits this.

    Nothing here raises. The caller already wraps the invocation in its own
    quiet block, so a raise would be swallowed and this would simply stop
    recording -- invisibly, which is the failure worth avoiding.
    """
    try:
        observe_plugin_hook_call("subagent_start", kwargs)
        note_delegated_session(kwargs.get("child_session_id"))
    except Exception:  # noqa: BLE001 - swallowed upstream either way; failing
        # to record one child must not interrupt that child's spawn.
        return None
    return None


def on_session_end(**kwargs) -> dict[str, object] | None:
    """Record a metadata-only plugin checkpoint when OMH runtime state exists."""
    try:
        home = runtime_paths.plugin_home(kwargs.get("omh_home"))
        runtime_paths.plugin_home(kwargs.get("hermes_home"), hermes=True)
    except (runtime_paths.RuntimeBindingError, OSError, RuntimeError) as exc:
        return runtime_binding_degradation(exc)
    observe_plugin_hook_call("on_session_end", kwargs)
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
