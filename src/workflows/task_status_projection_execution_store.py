"""Persistent store for task status projection executions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .task_status_projection_executor import (
    ProjectionDeliveryExecution,
)


SCHEMA_VERSION = "task_status_projection_execution/v1"

def append_execution(
    path: Path,
    execution: ProjectionDeliveryExecution,
) -> ProjectionDeliveryExecution:
    validate_execution(execution)

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with path.open(
        "a",
        encoding="utf-8",
    ) as handle:
        handle.write(
            json.dumps(
                execution,
                sort_keys=True,
            )
            + "\n"
        )

    return execution


def read_executions(
    path: Path,
) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    rows = []

    for line in path.read_text(
        encoding="utf-8",
    ).splitlines():
        if line.strip():
            rows.append(
                json.loads(line)
            )

    return rows


def find_execution_by_action(
    path: Path,
    action_id: str,
) -> dict[str, Any] | None:
    executions = read_executions(path)

    for execution in reversed(executions):
        if execution.get("action_id") == action_id:
            return execution

    return None


def append_if_missing(
    path: Path,
    execution: ProjectionDeliveryExecution,
) -> tuple[ProjectionDeliveryExecution, bool]:
    existing = find_execution_by_action(
        path,
        execution["action_id"],
    )

    if existing:
        return existing, False

    append_execution(
        path,
        execution,
    )

    return execution, True


def validate_execution(
    execution: dict[str, Any],
) -> None:
    required = {
        "schema_version",
        "execution_id",
        "action_id",
        "action",
        "status",
        "idempotency_key",
        "claim_boundary",
    }

    missing = required - set(execution)

    if missing:
        raise ValueError(
            f"missing execution fields: {sorted(missing)}"
        )

    if execution["schema_version"] != SCHEMA_VERSION:
        raise ValueError(
            "invalid execution schema"
        )
