"""Persistent storage for task status projection observations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .task_status_projection_observation import (
    SCHEMA_VERSION,
)


def append_observation_if_missing(
    path: Path,
    observation: dict[str, Any],
) -> bool:
    validate_observation(observation)

    existing = find_observation(
        path,
        observation["execution_id"],
    )

    if existing is not None:
        return False

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with path.open(
        "a",
        encoding="utf-8",
    ) as file:
        file.write(
            json.dumps(
                observation,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            + "\n"
        )

    return True


def find_observation(
    path: Path,
    execution_id: str,
) -> dict[str, Any] | None:
    if not path.exists():
        return None

    with path.open(
        "r",
        encoding="utf-8",
    ) as file:
        for line in file:
            record = json.loads(line)

            if record.get("execution_id") == execution_id:
                return record

    return None


def validate_observation(
    observation: dict[str, Any],
) -> None:
    required = {
        "schema_version",
        "execution_id",
        "provider_ref",
        "outcome",
        "detail",
    }

    missing = required - set(observation)

    if missing:
        raise ValueError(
            f"missing observation fields: {sorted(missing)}"
        )

    if observation["schema_version"] != SCHEMA_VERSION:
        raise ValueError(
            "invalid observation schema"
        )

    if not isinstance(
        observation["execution_id"],
        str,
    ):
        raise ValueError(
            "invalid execution_id"
        )

    if not isinstance(
        observation["provider_ref"],
        str,
    ):
        raise ValueError(
            "invalid provider_ref"
        )

    if observation["outcome"] not in {
        "accepted",
        "rejected",
        "ambiguous",
    }:
        raise ValueError(
            "invalid observation outcome"
        )
