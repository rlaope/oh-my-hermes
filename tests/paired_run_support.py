from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
import threading

from omh.coding.routing_observation import (
    authenticate_child_observation,
    build_routing_observation,
)
from omh.quality.paired_run_values import exposure_digest

# One OMH home holds one integrity key, shared by every run directory under it.
# `execute_paired_run_plan` runs sibling cells on threads, so two cells of the
# same wave write receipts into one home at once. Rewriting the key on each
# receipt truncates it to zero for as long as the write takes, and a sibling
# reading it in that window gets a short key, fails verification, and reaches
# its caller as a crashed cell with no receipt. Create it once instead, and
# sign with whatever key the home already holds.
_KEY_FILENAME = ".observation-hmac-key"
_KEY_LOCK = threading.Lock()


def _shared_observation_key(root: Path) -> bytes:
    key_path = root / _KEY_FILENAME
    with _KEY_LOCK:
        if not key_path.exists():
            key_path.write_bytes(b"k" * 32)
    return key_path.read_bytes()


def paired_evaluation_binding(
    *,
    task_id: str,
    criteria_ref: str,
    input_digest: str,
    arm: str,
    executor: str,
    model: str,
    exposed_skills: tuple[str, ...],
    execution_revision: str,
    timeout_seconds: int = 900,
) -> dict[str, str | int]:
    return {
        "task_id": task_id,
        "acceptance_criteria_ref": criteria_ref,
        "input_digest": input_digest,
        "arm": arm,
        "executor": executor,
        "model": model,
        "exposure_digest": exposure_digest(tuple(sorted(exposed_skills))),
        "execution_revision": execution_revision,
        "timeout_seconds": timeout_seconds,
    }


def write_observed_receipt(
    omh_home: Path,
    run_id: str,
    status: str = "completed",
    observed_at: str = "2026-08-27T00:00:00Z",
    *,
    evaluation_binding: dict[str, str | int] | None = None,
    elapsed_seconds: float | None = None,
) -> Path:
    root = omh_home / "coding" / "hermes-child"
    run_dir = root / run_id
    run_dir.mkdir(parents=True)
    observation = build_routing_observation(
        route={
            "selected_model": "fixture/model",
            "selected_reasoning_effort": "high",
            "role": "agent_maintainer",
            "executor_profile": "hermes_child",
            "chain": [],
        },
        child_dispatch=authenticate_child_observation(
            {"status": status, "run_id": run_id}
        ),
        run_id=run_id,
    )
    observation["observed_at"] = observed_at
    if elapsed_seconds is not None:
        observation["elapsed_seconds"] = elapsed_seconds
    if evaluation_binding is not None:
        observation["evaluation_binding"] = evaluation_binding
    canonical = json.dumps(
        observation,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    key = _shared_observation_key(root)
    (run_dir / "observation.json").write_text(json.dumps(observation), encoding="utf-8")
    signature = hmac.new(key, canonical, hashlib.sha256).hexdigest()
    (run_dir / "observation.signature.json").write_text(
        json.dumps(
            {
                "schema_version": "hermes_child_observation_signature/v1",
                "hmac_sha256": signature,
            }
        ),
        encoding="utf-8",
    )
    return run_dir


def resign_observation(run_dir: Path) -> None:
    observation = json.loads((run_dir / "observation.json").read_text(encoding="utf-8"))
    canonical = json.dumps(
        observation,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    key = (run_dir.parent / ".observation-hmac-key").read_bytes()
    signature = hmac.new(key, canonical, hashlib.sha256).hexdigest()
    (run_dir / "observation.signature.json").write_text(
        json.dumps(
            {
                "schema_version": "hermes_child_observation_signature/v1",
                "hmac_sha256": signature,
            }
        ),
        encoding="utf-8",
    )
