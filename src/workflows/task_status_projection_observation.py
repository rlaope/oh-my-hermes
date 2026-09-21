"""Delivery observations for task status projections."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict
import re


SCHEMA_VERSION = "task_status_projection_observation/v1"

_OUTCOMES = {
    "accepted",
    "rejected",
    "ambiguous",
}

_REFERENCE = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z"
)


class DeliveryObservationRecord(TypedDict):
    schema_version: str
    execution_id: str
    provider_ref: str
    outcome: str
    detail: str


@dataclass(frozen=True)
class DeliveryObservation:
    execution_id: str
    provider_ref: str
    outcome: str
    detail: str

    def build(self) -> DeliveryObservationRecord:
        _reference(self.execution_id, "execution_id")
        _reference(self.provider_ref, "provider_ref")

        if self.outcome not in _OUTCOMES:
            raise ValueError("invalid observation outcome")

        if not isinstance(self.detail, str) or not self.detail:
            raise ValueError("invalid observation detail")

        return {
            "schema_version": SCHEMA_VERSION,
            "execution_id": self.execution_id,
            "provider_ref": self.provider_ref,
            "outcome": self.outcome,
            "detail": self.detail,
        }


def _reference(value: str, field: str) -> None:
    if not isinstance(value, str) or not _REFERENCE.fullmatch(value):
        raise ValueError(f"invalid {field}")
