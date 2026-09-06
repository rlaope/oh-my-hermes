from __future__ import annotations

import json
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..plugin_bundle.omh.memory_governance import contains_credential_like_material

_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")


@dataclass(frozen=True)
class ScanFinding:
    relative_path: str
    artifact_kind: str
    target_id: str
    value: Mapping[str, object]


def safe_token(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(_SAFE_TOKEN.fullmatch(value))
        and not contains_credential_like_material(value)
    )


def stamp(value: datetime) -> str:
    current = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    return current.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_time(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def relative_path(root: Path, path: Path) -> str:
    resolved_root, resolved = root.resolve(strict=False), path.resolve(strict=False)
    if resolved_root != resolved and resolved_root not in resolved.parents:
        raise ValueError("path_escape")
    return path.relative_to(root).as_posix()


def memory_path(root: Path, relative: str) -> Path:
    path = Path(relative)
    if not relative or path.is_absolute() or ".." in path.parts:
        raise ValueError("path_escape")
    candidate = root / path
    for parent in (candidate, *candidate.parents):
        if parent.is_symlink():
            raise ValueError("symlink_target")
        if parent == root:
            break
    relative_path(root, candidate)
    return candidate


def read_json(root: Path, relative: str) -> tuple[dict[str, object] | None, str | None]:
    try:
        path = memory_path(root, relative)
    except ValueError as exc:
        return None, str(exc)
    if not path.exists():
        return None, "already_absent"
    if not path.is_file():
        return None, "unsupported_target"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, "corrupt_json"
    return (value, None) if isinstance(value, dict) else (None, "unsupported_target")


def json_files(root: Path, directory: str) -> Iterator[tuple[str, str | None]]:
    try:
        base = memory_path(root, directory)
    except ValueError as exc:
        yield directory, str(exc)
        return
    if not base.exists():
        return
    if base.is_symlink() or not base.is_dir():
        yield directory, "symlink_target" if base.is_symlink() else "unsupported_target"
        return
    for path in sorted(base.rglob("*.json")):
        try:
            yield relative_path(root, path), None if not path.is_symlink() else "symlink_target"
        except ValueError:
            yield path.name, "path_escape"


def matching_record(value: Mapping[str, object], record_id: str, revision: int) -> bool:
    return value.get("record_id") == record_id and value.get("revision") == revision


def identity_matches(value: object, record_id: str, revision: int) -> bool:
    return isinstance(value, Mapping) and value.get("id") == record_id and value.get("revision") == revision


def linked_to(value: object, record_id: str, revision: int) -> bool:
    if not isinstance(value, Mapping):
        return False
    if matching_record(value, record_id, revision):
        return True
    for key in ("artifact_identity", "source_record_identity", "record_identity", "origin", "correction_target"):
        if identity_matches(value.get(key), record_id, revision):
            return True
    return False


def matching_json_findings(root: Path, directory: str, record_id: str, revision: int, kind: str) -> tuple[list[ScanFinding], list[str]]:
    findings: list[ScanFinding] = []
    errors: list[str] = []
    for relative, error in json_files(root, directory):
        if error:
            errors.append(error)
            continue
        value, error = read_json(root, relative)
        if error:
            errors.append(error)
        elif value is not None and (matching_record(value, record_id, revision) or linked_to(value, record_id, revision)):
            findings.append(ScanFinding(relative, kind, f"{kind}:{record_id}:r{revision}:{len(findings)}", value))
    return findings, errors


def matching_scope_findings(root: Path, record_id: str, revision: int) -> tuple[list[ScanFinding], list[str]]:
    findings: list[ScanFinding] = []
    errors: list[str] = []
    for relative, error in json_files(root, "scopes"):
        if error:
            errors.append(error)
            continue
        value, error = read_json(root, relative)
        items = value.get("items") if value else None
        if error:
            errors.append(error)
        elif isinstance(items, Mapping):
            for item_id, item in sorted(items.items()):
                if safe_token(item_id) and linked_to(item, record_id, revision):
                    findings.append(ScanFinding(relative, "scope_item", f"scope_item:{record_id}:r{revision}:{item_id}", value))
    return findings, errors


def journal_findings(root: Path, record_id: str, revision: int) -> tuple[list[ScanFinding], list[str], list[dict[str, object]]]:
    findings: list[ScanFinding] = []
    errors: list[str] = []
    preserved: list[dict[str, object]] = []
    for relative in ("write_journal.jsonl", "consolidation.jsonl"):
        try:
            path = memory_path(root, relative)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if not path.exists():
            continue
        if path.is_symlink() or not path.is_file():
            errors.append("symlink_target" if path.is_symlink() else "unsupported_target")
            continue
        try:
            lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        except (OSError, json.JSONDecodeError):
            errors.append("corrupt_json")
            continue
        if any(not isinstance(line, dict) for line in lines):
            errors.append("unsupported_target")
            continue
        matching = [line for line in lines if linked_to(line, record_id, revision)]
        if matching:
            findings.append(ScanFinding(relative, "journal_entry", f"journal_entry:{record_id}:r{revision}:{len(findings)}", {"lines": lines}))
        elif lines:
            preserved.append({"target_id": f"journal:{relative.replace('/', ':')}", "artifact_kind": "journal_entry", "outcome": "unlinked_preserved", "reason_code": "no_declared_identity_link"})
    return findings, errors, preserved


def rejected_outcomes(errors: list[str]) -> list[dict[str, object]]:
    return [{"target_id": f"rejected:{index}", "artifact_kind": "local_target", "outcome": "rejected", "reason_code": error} for index, error in enumerate(sorted(set(errors)))]
