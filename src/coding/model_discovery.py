"""Bounded, metadata-only discovery across local coding-agent stores."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import json
import os
from pathlib import Path
import re
import time
from typing import Final, Iterator

from .pi_family_interop import (
    PI_DISTRIBUTION_HOME,
    PI_DISTRIBUTION_HOST,
    PI_FORK_HOME,
    PI_FORK_HOST,
    RUNTIME_CONFIG_FILES,
    RUNTIME_HOME,
    RUNTIME_MODELS_FILE,
)
from .model_discovery_adapters import RUNTIME_CONFIG_SOURCE, accepted_observation, model_candidates
from .model_discovery_contract import (
    MODEL_DISCOVERY_CLAIM_BOUNDARY,
    MODEL_DISCOVERY_SCHEMA_VERSION,
    DiscoveryLimits,
    deduplicate,
    source_payload,
)

_SOURCE_ROOTS: Final[dict[str, tuple[str, ...]]] = {
    "codex": (".codex/sessions", ".codex/archived_sessions"),
    "claude-code": (
        ".claude/projects",
        ".claude/transcripts",
        ".claude/pre-compact-session-histories",
    ),
    PI_DISTRIBUTION_HOST: (f"{PI_DISTRIBUTION_HOME}/agent/sessions",),
    "pi": (".pi/agent/sessions",),
    # The fork host writes `agent/sessions/<encoded-cwd>/<ts>_<id>.jsonl` under
    # its own home (upstream docs/session.md). Any other layout under that home
    # is reported `layout_unverified` and never read.
    PI_FORK_HOST: (f"{PI_FORK_HOME}/agent/sessions",),
    RUNTIME_CONFIG_SOURCE: (
        *(f"{RUNTIME_HOME}/{name}" for name in RUNTIME_CONFIG_FILES),
        f"{RUNTIME_HOME}/{RUNTIME_MODELS_FILE}",
    ),
    "opencode": (
        ".opencode/messages",
        ".local/share/opencode/storage/message",
    ),
    "hermes": (".hermes/sessions",),
}
_JSONC_LINE_COMMENT = re.compile(r"^\s*//.*$", re.MULTILINE)
_READ_ERRORS = (OSError, UnicodeDecodeError, json.JSONDecodeError)

def discover_local_models(
    home: Path,
    *,
    limits: Mapping[str, object] | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, object]:
    """Return safe model observations without traversing outside fixed roots."""
    bounded = DiscoveryLimits.from_mapping(limits)
    observations: list[dict[str, str]] = []
    sources: dict[str, dict[str, object]] = {}
    for source, relatives in _SOURCE_ROOTS.items():
        source_observations, source_result = _scan_source(
            home,
            source=source,
            relatives=relatives,
            limits=bounded,
            clock=clock,
        )
        observations.extend(source_observations)
        sources[source] = source_result
    if not sources[PI_FORK_HOST]["supported_root"] and (home / PI_FORK_HOME).exists():
        sources[PI_FORK_HOST] = source_payload(
            "layout_unverified",
            (),
            scanned_records=0,
            rejected=0,
            supported_root=False,
            truncated_reasons=(),
        )
    deduplicated = deduplicate(observations)
    return {
        "schema_version": MODEL_DISCOVERY_SCHEMA_VERSION,
        "limits": {
            "max_records_per_source": bounded.max_records_per_source,
            "max_record_bytes": bounded.max_record_bytes,
            "max_depth": bounded.max_depth,
            "soft_budget_seconds": bounded.soft_budget_seconds,
        },
        "sources": sources,
        "observations": deduplicated,
        "observation_count": len(deduplicated),
        "claim_boundary": MODEL_DISCOVERY_CLAIM_BOUNDARY,
    }


def _scan_source(
    home: Path,
    *,
    source: str,
    relatives: tuple[str, ...],
    limits: DiscoveryLimits,
    clock: Callable[[], float],
) -> tuple[list[dict[str, str]], dict[str, object]]:
    started = clock()
    observations: list[dict[str, str]] = []
    scanned_records = 0
    rejected = 0
    supported_root = False
    truncated_reasons: set[str] = set()
    stop = False
    for relative in relatives:
        root = home / relative
        if not root.exists() or not _is_safe_path(home, root):
            continue
        supported_root = True
        for path, depth_truncated in _bounded_files(root, limits.max_depth):
            if depth_truncated:
                truncated_reasons.add("depth")
                continue
            if clock() - started > limits.soft_budget_seconds:
                truncated_reasons.add("deadline")
                stop = True
                break
            records = iter(_records(path, limits.max_record_bytes))
            while True:
                if scanned_records >= limits.max_records_per_source:
                    truncated_reasons.add("record_count")
                    stop = True
                    break
                if clock() - started > limits.soft_budget_seconds:
                    truncated_reasons.add("deadline")
                    stop = True
                    break
                try:
                    raw = next(records)
                except StopIteration:
                    break
                if raw is None:
                    truncated_reasons.add("record_size")
                    continue
                scanned_records += 1
                try:
                    parsed = _parse_record(path, raw)
                except _READ_ERRORS:
                    rejected += 1
                    continue
                for candidate in model_candidates(source, parsed):
                    accepted = accepted_observation(source, candidate)
                    if accepted is None:
                        rejected += 1
                    else:
                        observations.append(accepted)
            if stop:
                break
        if stop:
            break
    status = _source_status(source, observations, supported_root, truncated_reasons)
    payload = source_payload(
        status,
        observations,
        scanned_records=scanned_records,
        rejected=rejected,
        supported_root=supported_root,
        truncated_reasons=tuple(sorted(truncated_reasons)),
    )
    return observations, payload


def _is_safe_path(home: Path, path: Path) -> bool:
    try:
        relative = path.relative_to(home)
        current = home
        for part in relative.parts:
            current /= part
            if current.is_symlink():
                return False
        path.resolve(strict=True).relative_to(home.resolve(strict=True))
    except (OSError, ValueError):
        return False
    return True


def _bounded_files(root: Path, max_depth: int) -> Iterator[tuple[Path, bool]]:
    if root.is_file():
        if root.name.casefold() != "auth.json" and not root.is_symlink():
            yield root, False
        return
    for directory, dirnames, filenames in os.walk(root):
        current = Path(directory)
        depth = len(current.relative_to(root).parts)
        dirnames.sort()
        filenames.sort()
        if depth >= max_depth and dirnames:
            yield current, True
            dirnames.clear()
        for name in filenames:
            if name.casefold() == "auth.json":
                continue
            path = current / name
            if not path.is_symlink():
                yield path, False


def _records(path: Path, max_bytes: int) -> Iterator[bytes | None]:
    try:
        if path.suffix.lower() == ".jsonl":
            with path.open("rb") as handle:
                discarding_oversized_record = False
                while line := handle.readline(max_bytes + 1):
                    if discarding_oversized_record:
                        discarding_oversized_record = not line.endswith(b"\n")
                        continue
                    if len(line) <= max_bytes:
                        yield line
                        continue
                    discarding_oversized_record = not line.endswith(b"\n")
                    yield None
            return
        size = path.stat().st_size
        if size > max_bytes:
            yield None
            return
        yield path.read_bytes()
    except OSError:
        return


def _parse_record(path: Path, raw: bytes) -> object:
    text = raw.decode("utf-8")
    if path.suffix.lower() == ".jsonc":
        text = _JSONC_LINE_COMMENT.sub("", text)
    return json.loads(text)


def _source_status(
    source: str,
    observations: list[dict[str, str]],
    supported_root: bool,
    truncated_reasons: set[str],
) -> str:
    if truncated_reasons:
        return "truncated"
    if observations:
        return "confirmed_active" if source == RUNTIME_CONFIG_SOURCE else "observed_before"
    return "unobserved"
