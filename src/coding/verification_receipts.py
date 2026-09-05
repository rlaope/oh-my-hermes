"""Immutable verification receipts and single-flight process sharing.

A `verification_receipt/v1` is the one piece of evidence one check ever
produces under one receipt key. Receipts are immutable: written once with
`atomic_write_json`, never updated, and keyed so that any revision, command,
toolchain, environment, or claim-scope change is a different receipt rather
than a mutation of this one. Multiple consumers of the same key reference
the same receipt; reuse is observed on the consumer's row (`reused: true`),
not by rewriting the receipt — so `reused`/`reuse_count` here always record
the creation-time state.

Privacy is structural: a receipt carries key, check id, timestamps, duration,
status, revision, dependency ids, claim scope, and observation source. It
never carries command text, argv, env values, worktree content, or command
output — failure detail stays behind the dispatcher's bounded-tail-plus-spill
path, which the receipt does not copy.
"""

from __future__ import annotations

from contextlib import contextmanager
import re
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, TypeVar

from ..system.local_store import atomic_write_json, file_lock, read_json_object_result
from .verification_plan import ReceiptKey, VerificationNode

if TYPE_CHECKING:
    from ..system.paths import OmhPaths

VERIFICATION_RECEIPT_SCHEMA_VERSION = "verification_receipt/v1"
VERIFICATION_RECEIPT_CLAIM_BOUNDARY = (
    "A verification receipt records that one declared check produced one terminal status under one "
    "revision-bound key. It is not full verification, review, CI, merge-readiness, or merge evidence, "
    "and it is invalid the moment any key component — revision, command, toolchain, environment, or "
    "claim scope — changes."
)
VERIFICATION_RECEIPT_OBSERVATION_SOURCE = "verification_receipt"
RECEIPT_STATUSES = ("passed", "failed")

_T = TypeVar("_T")
_RECEIPT_KEY_RE = re.compile(r"^[0-9a-f]{64}$")
_WINDOWS_EXTENDED_PREFIX = "\\\\?\\"
_WINDOWS_EXTENDED_UNC_PREFIX = "\\\\?\\UNC\\"


def _containment_path(path: Path) -> Path:
    """Normalize equivalent Windows extended paths only for containment checks.

    `Path.resolve(strict=False)` can return an extended DOS path for a missing
    child while returning a normal path for its existing parent. Extended UNC
    has a distinct spelling, so convert it to UNC rather than dropping the
    namespace prefix blindly. Other device namespaces have no ordinary DOS or
    UNC equivalent and remain unchanged.
    """
    raw = str(path)
    if raw[: len(_WINDOWS_EXTENDED_UNC_PREFIX)].casefold() == _WINDOWS_EXTENDED_UNC_PREFIX.casefold():
        return type(path)("\\\\" + raw[len(_WINDOWS_EXTENDED_UNC_PREFIX) :])
    if (
        raw.startswith(_WINDOWS_EXTENDED_PREFIX)
        and len(raw) > len(_WINDOWS_EXTENDED_PREFIX) + 2
        and raw[len(_WINDOWS_EXTENDED_PREFIX)].isalpha()
        and raw[len(_WINDOWS_EXTENDED_PREFIX) + 1] == ":"
        and raw[len(_WINDOWS_EXTENDED_PREFIX) + 2] == "\\"
    ):
        return type(path)(raw[len(_WINDOWS_EXTENDED_PREFIX) :])
    return path


def receipts_dir(paths: OmhPaths) -> Path:
    return paths.omh_home / "coding" / "verification-receipts"


def receipt_path(paths: OmhPaths, key: str) -> Path:
    """Return a contained receipt destination for one exact SHA-256 key."""
    if not _RECEIPT_KEY_RE.fullmatch(key):
        raise ValueError("verification receipt key must be exactly 64 lowercase hexadecimal characters")
    directory = receipts_dir(paths)
    if directory.is_symlink():
        raise ValueError("verification receipt directory must not be a symlink")
    resolved_home = _containment_path(paths.omh_home.resolve(strict=False))
    resolved_directory = _containment_path(directory.resolve(strict=False))
    try:
        resolved_directory.relative_to(resolved_home)
    except ValueError as exc:
        raise ValueError("verification receipt directory escapes omh home") from exc
    destination = directory / f"{key}.json"
    if destination.is_symlink():
        raise ValueError("verification receipt destination must not be a symlink")
    try:
        _containment_path(destination.resolve(strict=False)).relative_to(resolved_directory)
    except ValueError as exc:
        raise ValueError("verification receipt destination escapes receipt directory") from exc
    return destination


@contextmanager
def receipt_file_lock(
    paths: OmhPaths, key: ReceiptKey, *, timeout_seconds: float
) -> Iterator[dict[str, Any]]:
    """Lock a receipt only through the same validated, contained path boundary."""
    with file_lock(receipt_path(paths, str(key)), timeout_seconds=timeout_seconds, private=True) as state:
        yield state


def build_receipt(
    *,
    key: ReceiptKey,
    node: VerificationNode,
    revision: str,
    status: str,
    queued_at: str,
    started_at: str,
    finished_at: str,
    duration_seconds: float,
) -> dict[str, Any]:
    """The immutable receipt for one finished check — metadata only."""
    return {
        "schema_version": VERIFICATION_RECEIPT_SCHEMA_VERSION,
        "receipt_key": str(key),
        "check_id": node.check_id,
        "status": status,
        "queued_at": queued_at,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_seconds": round(duration_seconds, 3),
        "reused": False,
        "reuse_count": 0,
        "revision": revision,
        "depends_on": list(node.depends_on),
        "claim_scope": node.claim_scope,
        "observation_source": VERIFICATION_RECEIPT_OBSERVATION_SOURCE,
        "claim_boundary": VERIFICATION_RECEIPT_CLAIM_BOUNDARY,
    }


def load_receipt(paths: OmhPaths, key: ReceiptKey) -> dict[str, Any] | None:
    """The stored receipt for one key, or None when absent or malformed."""
    receipt, error = read_json_object_result(receipt_path(paths, str(key)))
    if receipt is None or error is not None:
        return None
    if receipt.get("schema_version") != VERIFICATION_RECEIPT_SCHEMA_VERSION:
        return None
    if receipt.get("receipt_key") != str(key):
        return None
    if receipt.get("status") not in RECEIPT_STATUSES:
        return None
    return receipt


def store_receipt(paths: OmhPaths, receipt: dict[str, Any]) -> None:
    """Write one receipt once; an existing key is immutable evidence."""
    raw_key = receipt.get("receipt_key")
    if not isinstance(raw_key, str):
        raise ValueError("verification receipt key must be a string")
    path = receipt_path(paths, raw_key)
    if path.exists():
        return
    atomic_write_json(path, receipt, private=True)


def receipt_hit_status(
    paths: OmhPaths, key: ReceiptKey, *, claim_scope: str, revision: str | None
) -> str | None:
    """The terminal status a stored receipt proves for this context, or None.

    Scope and revision ride inside the key, so a field mismatch here means
    the store was written against a weaker context — scope-insufficient or
    stale evidence, which is treated as missing, never as a hit.
    """
    receipt = load_receipt(paths, key)
    if receipt is None:
        return None
    if receipt.get("claim_scope") != claim_scope or receipt.get("revision") != revision:
        return None
    return str(receipt["status"])


def file_receipt(
    paths: OmhPaths,
    *,
    key: ReceiptKey,
    node: VerificationNode,
    revision: str,
    status: str,
    queued_at: str,
    started_at: str,
    finished_at: str,
    duration_seconds: float,
) -> None:
    """Build and store the immutable receipt for one finished check."""
    store_receipt(
        paths,
        build_receipt(
            key=key,
            node=node,
            revision=revision,
            status=status,
            queued_at=queued_at,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=duration_seconds,
        ),
    )


_UNSET: Any = object()


class _Flight:
    """One in-flight or completed produce call. Mutable by design: it is the
    shared slot every consumer of one key synchronizes on; mutation is its
    whole purpose (MUTABLE_OK)."""

    def __init__(self) -> None:
        self.done = threading.Event()
        self.result: Any = _UNSET


class SingleFlight:
    """One produce call per key for the life of this process.

    The first consumer to claim a key runs `produce`; every other consumer —
    concurrent or later — shares that one outcome and is told it reused it.
    Completed flights are kept, not evicted: a repeated key MUST reuse rather
    than spawn a second process (that is the point of the machinery), and the
    persistent receipt store is what carries sharing across processes. A
    produce that raises propagates to its own caller only; waiters observe
    the unset slot and run their own produce rather than reuse a failure.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._flights: dict[str, _Flight] = {}

    def run(self, key: str, produce: Callable[[], _T], *, wait_timeout: float = 660.0) -> tuple[_T, bool]:
        """Return `(outcome, reused)`; exactly one caller per key runs `produce`."""
        with self._lock:
            flight = self._flights.get(key)
            owner = flight is None
            if owner:
                flight = _Flight()
                self._flights[key] = flight
        if owner:
            try:
                flight.result = produce()
            finally:
                # Set on every outcome, raise included: a waiter must never
                # hang behind an owner that already gave up.
                flight.done.set()
            return flight.result, False
        if not flight.done.wait(timeout=wait_timeout) or flight.result is _UNSET:
            # A wedged or failed owner must not hold consumers open, and a
            # failed produce is not evidence worth sharing: degrade to a
            # duplicate run, which keeps the failure local and observable.
            return produce(), False
        return flight.result, True
