"""Authenticated persisted Hermes-child observation receipts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
from typing import Final, Mapping, TypeAlias, TypeVar

from .hermes_child_dispatch import HermesChildObservation, is_dispatch_observation
from .hermes_child_evaluation import (
    HermesChildEvaluationBinding,
    parse_evaluation_binding,
    seal_evaluation_binding,
)
from .routing_observation import validate_routing_observation
from ..system.local_store import atomic_write_json
from ..system.metadata_safety import require_opaque_metadata_ref
from ..system.secure_regular_file import SecureFileError, open_regular_read, read_bounded

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
_ObservationValue = TypeVar("_ObservationValue")
_SIGNATURE_SCHEMA: Final = "hermes_child_observation_signature/v1"
_KEY_BYTES: Final = 32
_MAX_OBSERVATION_BYTES: Final = 65_536
_MAX_SIGNATURE_BYTES: Final = 4_096
_TERMINAL_STATUSES: Final = frozenset({"completed", "failed", "timed_out", "cancelled"})
_UTC_Z: Final = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$")


class ReceiptVerificationError(Exception):
    __slots__ = ("reason",)

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class _ReceiptAuthority:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance


_AUTHORITY: Final = _ReceiptAuthority()


@dataclass(frozen=True, slots=True)
class VerifiedHermesChildReceipt:
    """Process-sealed proof that one persisted dispatch observation verified."""

    run_id: str
    claim: str
    status: str
    observed_at: str
    receipt_ref: str
    evaluation_binding: HermesChildEvaluationBinding | None
    _authority: _ReceiptAuthority

    def has_receipt_authority(self) -> bool:
        """Return whether persisted receipt verification minted this value."""
        return self._authority is _AUTHORITY


def is_verified_receipt(value: VerifiedHermesChildReceipt) -> bool:
    return value.has_receipt_authority()


def canonical_observation(observation: Mapping[str, _ObservationValue]) -> bytes:
    return json.dumps(
        observation,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def observation_key_open_flags() -> int:
    return os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)


def hermes_child_run_dir(omh_home: Path, run_id: str, *, create_root: bool) -> Path:
    try:
        safe_run_id = require_opaque_metadata_ref(run_id, field="run_id")
    except ValueError as exc:
        raise ReceiptVerificationError(str(exc)) from exc
    if safe_run_id in {".", ".."} or "/" in safe_run_id or "\\" in safe_run_id:
        raise ReceiptVerificationError("run_id must be a single safe opaque metadata reference")
    home = omh_home.expanduser()
    coding = home / "coding"
    root = coding / "hermes-child"
    for component in (home, coding, root):
        if component.is_symlink() or (
            component.exists() and component.resolve(strict=True) != component
        ):
            raise ReceiptVerificationError("Hermes child storage path must not contain a symlink")
    if create_root:
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
    candidate = root / safe_run_id
    if (
        candidate.is_symlink()
        or (candidate.exists() and candidate.resolve(strict=True) != candidate)
        or candidate.parent != root
    ):
        raise ReceiptVerificationError("run_id resolves outside the Hermes child run directory")
    return candidate


def load_or_create_observation_key(root: Path) -> bytes:
    key_path = root / ".observation-hmac-key"
    try:
        descriptor = os.open(key_path, observation_key_open_flags(), 0o600)
    except FileExistsError:
        descriptor = None
    if descriptor is not None:
        try:
            os.write(descriptor, os.urandom(_KEY_BYTES))
        finally:
            os.close(descriptor)
    return _read_observation_key(key_path)


def write_signed_observation(
    run_dir: Path,
    observation: Mapping[str, JsonValue],
    dispatch_observation: HermesChildObservation | None = None,
) -> None:
    """Sign prepared state or a process-sealed real dispatch observation."""
    payload: dict[str, JsonValue] = dict(observation)
    if dispatch_observation is None:
        payload.pop("evaluation_binding", None)
    claim = payload.get("claim")
    status = payload.get("status")
    if claim == "prepared" and status == "prepared" and dispatch_observation is None:
        pass
    elif (
        dispatch_observation is None
        or not is_dispatch_observation(dispatch_observation)
        or claim != "observed"
        or status != dispatch_observation.status
        or payload.get("run_id") != dispatch_observation.run_id
    ):
        raise ReceiptVerificationError(
            "observed receipts require a matching process-sealed Hermes dispatch event"
        )
    else:
        payload["observed_at"] = dispatch_observation.observed_at
        context = dispatch_observation.evaluation_context
        if context is None:
            payload.pop("evaluation_binding", None)
        else:
            payload["evaluation_binding"] = seal_evaluation_binding(
                context,
                dispatch_observation.request_model,
                dispatch_observation.timeout_seconds,
            ).to_record()
    if validate_routing_observation(payload):
        raise ReceiptVerificationError("Hermes child observation is invalid")
    atomic_write_json(run_dir / "observation.json", payload, private=True)
    key = load_or_create_observation_key(run_dir.parent)
    signature = hmac.new(key, canonical_observation(payload), hashlib.sha256).hexdigest()
    atomic_write_json(
        run_dir / "observation.signature.json",
        {"schema_version": _SIGNATURE_SCHEMA, "hmac_sha256": signature},
        private=True,
    )


def observation_signature_valid(
    run_dir: Path,
    observation: Mapping[str, _ObservationValue],
) -> bool:
    try:
        signature = _read_json_object(run_dir / "observation.signature.json")
        key = _read_observation_key(run_dir.parent / ".observation-hmac-key")
    except ReceiptVerificationError:
        return False
    observed = signature.get("hmac_sha256")
    if signature.get("schema_version") != _SIGNATURE_SCHEMA or not isinstance(observed, str):
        return False
    expected = hmac.new(key, canonical_observation(observation), hashlib.sha256).hexdigest()
    return hmac.compare_digest(observed, expected)


def load_hermes_child_receipt(
    omh_home: Path,
    run_id: str,
) -> VerifiedHermesChildReceipt:
    """Verify persisted bytes and return a process-sealed receipt."""
    run_dir = hermes_child_run_dir(omh_home, run_id, create_root=False)
    observation = read_hermes_child_observation(run_dir)
    signature = _read_json_object(run_dir / "observation.signature.json")
    if validate_routing_observation(observation):
        raise ReceiptVerificationError("Hermes child observation is invalid")
    if observation.get("run_id") != run_id or observation.get("claim") != "observed":
        raise ReceiptVerificationError("Hermes child observation is not the requested observed run")
    if observation.get("status") not in _TERMINAL_STATUSES:
        raise ReceiptVerificationError("Hermes child observation is not terminal")
    observed_at = observation.get("observed_at")
    if not isinstance(observed_at, str) or _UTC_Z.fullmatch(observed_at) is None:
        raise ReceiptVerificationError("Hermes child observation time must be signed UTC-Z")
    try:
        datetime.fromisoformat(observed_at.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise ReceiptVerificationError("Hermes child observation time must be signed UTC-Z") from exc
    if set(signature) != {"schema_version", "hmac_sha256"}:
        raise ReceiptVerificationError("Hermes child observation signature is invalid")
    if signature.get("schema_version") != _SIGNATURE_SCHEMA:
        raise ReceiptVerificationError("Hermes child observation signature is invalid")
    observed_signature = signature.get("hmac_sha256")
    if not isinstance(observed_signature, str):
        raise ReceiptVerificationError("Hermes child observation signature is invalid")
    key = _read_observation_key(run_dir.parent / ".observation-hmac-key")
    expected = hmac.new(key, canonical_observation(observation), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(observed_signature, expected):
        raise ReceiptVerificationError("Hermes child observation signature is invalid")
    binding_value = observation.get("evaluation_binding")
    binding = (
        parse_evaluation_binding(binding_value)
        if binding_value is not None
        else None
    )
    if binding_value is not None and binding is None:
        raise ReceiptVerificationError("Hermes child evaluation binding is invalid")
    digest = hmac.new(
        key,
        canonical_observation(observation) + b"\0receipt",
        hashlib.sha256,
    ).hexdigest()
    return VerifiedHermesChildReceipt(
        run_id,
        "observed",
        str(observation["status"]),
        observed_at,
        f"hermes-child:{run_id}:{digest}",
        binding,
        _AUTHORITY,
    )


def read_hermes_child_observation(run_dir: Path) -> dict[str, JsonValue]:
    """Read one bounded no-follow observation object."""
    return _read_json_object(run_dir / "observation.json", _MAX_OBSERVATION_BYTES)


def _read_json_object(path: Path, maximum: int = _MAX_SIGNATURE_BYTES) -> dict[str, JsonValue]:
    try:
        with open_regular_read(path) as descriptor:
            value = json.loads(read_bounded(descriptor, maximum).decode("utf-8"))
    except (SecureFileError, OSError, ValueError, UnicodeError, RecursionError) as exc:
        raise ReceiptVerificationError("Hermes child receipt file is unreadable") from exc
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ReceiptVerificationError("Hermes child receipt file must contain an object")
    return value


def _read_observation_key(path: Path) -> bytes:
    try:
        with open_regular_read(path) as descriptor:
            key = read_bounded(descriptor, _KEY_BYTES)
    except (SecureFileError, OSError) as exc:
        raise ReceiptVerificationError("Hermes child observation integrity key is invalid") from exc
    if len(key) != _KEY_BYTES:
        raise ReceiptVerificationError("Hermes child observation integrity key is invalid")
    return key
