from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from ..local_store import atomic_write_text


@dataclass(frozen=True)
class ConfigChange:
    changed: bool
    message: str
    text: str


@dataclass(frozen=True)
class _InlineExternalDirs:
    matched: bool
    supported: bool
    values: list[str]


_BARE_YAML_NULLS = {"null", "Null", "NULL", "~"}
_UNSUPPORTED_EXTERNAL_DIRS_SHAPE = "unsupported skills.external_dirs shape; use a YAML block list or inline list"
_DUPLICATE_EXTERNAL_DIRS_SHAPE = "duplicate skills.external_dirs entries are unsupported; keep one YAML block list or inline list"


def _normalize(value: str | Path) -> str:
    return str(Path(value).expanduser())


def _parse_inline_list(value: str) -> list[str] | None:
    value = value.strip()
    if value == "[]":
        return []
    if not (value.startswith("[") and value.endswith("]")):
        return None
    inner = value[1:-1].strip()
    if not inner:
        return []
    items = []
    for raw in inner.split(","):
        item = raw.strip().strip("'\"")
        if not item:
            return None
        items.append(item)
    return items


def _format_external_dirs(values: list[str]) -> list[str]:
    return ["  external_dirs:", *[f"    - {value}" for value in values]]


def _external_dir_item_value(line: str) -> str | None:
    if line.startswith("    - ") or line.startswith("  - "):
        return line.strip()[2:].strip().strip("'\"")
    return None


def _external_dir_item_prefix(line: str) -> str | None:
    if line.startswith("    - "):
        return "    - "
    if line.startswith("  - "):
        return "  - "
    return None


def _classify_inline_external_dirs(line: str) -> _InlineExternalDirs:
    # Readers stay non-throwing for doctor/probe stability: unsupported inline
    # scalars mean "no valid dirs observed". Mutations remain strict and reject
    # matched-but-unsupported shapes instead of guessing YAML semantics.
    match = re.match(r"^  external_dirs:\s*(?P<value>\S.*)$", line)
    if not match:
        return _InlineExternalDirs(False, False, [])
    value = match.group("value").strip()
    if value in _BARE_YAML_NULLS:
        return _InlineExternalDirs(True, True, [])
    parsed = _parse_inline_list(value)
    if parsed is None:
        return _InlineExternalDirs(True, False, [])
    return _InlineExternalDirs(True, True, parsed)


def _validate_external_dirs_mutation_shape(config_text: str) -> None:
    in_skills = False
    external_dirs_declarations = 0
    for line in config_text.splitlines():
        stripped = line.strip()
        if not line.startswith(" ") and stripped:
            in_skills = stripped == "skills:"
            continue
        if in_skills and line.startswith("  ") and not line.startswith("    "):
            inline = _classify_inline_external_dirs(line)
            if inline.matched or stripped == "external_dirs:":
                external_dirs_declarations += 1
                if external_dirs_declarations > 1:
                    raise ValueError(_DUPLICATE_EXTERNAL_DIRS_SHAPE)
                if inline.matched and not inline.supported:
                    raise ValueError(_UNSUPPORTED_EXTERNAL_DIRS_SHAPE)


def external_dirs(config_text: str) -> list[str]:
    lines = config_text.splitlines()
    result: list[str] = []
    in_skills = False
    in_external = False
    for line in lines:
        stripped = line.strip()
        if not line.startswith(" ") and stripped:
            in_skills = stripped == "skills:"
            in_external = False
            continue
        if in_skills and in_external:
            value = _external_dir_item_value(line)
            if value is not None:
                result.append(value)
                continue
        if in_skills and line.startswith("  ") and not line.startswith("    "):
            inline = _classify_inline_external_dirs(line)
            if inline.matched:
                if inline.supported:
                    result.extend(inline.values)
                in_external = False
                continue
            in_external = stripped == "external_dirs:"
            continue
    return result


def ensure_external_dir(config_text: str, skill_dir: str | Path) -> ConfigChange:
    _validate_external_dirs_mutation_shape(config_text)
    target = _normalize(skill_dir)
    if target in external_dirs(config_text):
        return ConfigChange(False, "external dir already present", config_text)

    lines = config_text.splitlines()
    if not lines:
        text = f"skills:\n  external_dirs:\n    - {target}\n"
        return ConfigChange(True, "created skills.external_dirs", text)

    skills_index = next((idx for idx, line in enumerate(lines) if line.strip() == "skills:" and not line.startswith(" ")), None)
    if skills_index is None:
        text = config_text.rstrip() + f"\n\nskills:\n  external_dirs:\n    - {target}\n"
        return ConfigChange(True, "appended skills.external_dirs", text)

    external_index = None
    for idx in range(skills_index + 1, len(lines)):
        line = lines[idx]
        if line and not line.startswith(" "):
            break
        if line.startswith("  ") and not line.startswith("    "):
            inline = _classify_inline_external_dirs(line)
            if inline.matched:
                if not inline.supported:
                    raise ValueError(_UNSUPPORTED_EXTERNAL_DIRS_SHAPE)
                values = inline.values
                if target in values:
                    return ConfigChange(False, "external dir already present", config_text)
                lines[idx:idx + 1] = _format_external_dirs([*values, target])
                return ConfigChange(True, "expanded inline external_dirs", "\n".join(lines) + "\n")
            if line.strip() == "external_dirs:":
                external_index = idx
                break

    if external_index is None:
        lines[skills_index + 1:skills_index + 1] = ["  external_dirs:", f"    - {target}"]
        return ConfigChange(True, "inserted skills.external_dirs", "\n".join(lines) + "\n")

    insert_at = external_index + 1
    item_prefix = "    - "
    while insert_at < len(lines):
        prefix = _external_dir_item_prefix(lines[insert_at])
        if prefix is None:
            break
        item_prefix = prefix
        insert_at += 1
    lines.insert(insert_at, f"{item_prefix}{target}")
    return ConfigChange(True, "added external dir", "\n".join(lines) + "\n")


def remove_external_dir(config_text: str, skill_dir: str | Path) -> ConfigChange:
    _validate_external_dirs_mutation_shape(config_text)
    target = _normalize(skill_dir)
    lines = config_text.splitlines()
    changed = False
    output: list[str] = []
    in_skills = False
    in_external = False
    for line in lines:
        stripped = line.strip()
        if not line.startswith(" ") and stripped:
            in_skills = stripped == "skills:"
            in_external = False
            output.append(line)
            continue
        if in_skills and in_external:
            value = _external_dir_item_value(line)
            if value is not None:
                if value == target:
                    changed = True
                    continue
                output.append(line)
                continue
        if in_skills and line.startswith("  ") and not line.startswith("    "):
            inline = _classify_inline_external_dirs(line)
            if inline.matched:
                if not inline.supported:
                    raise ValueError(_UNSUPPORTED_EXTERNAL_DIRS_SHAPE)
                values = [value for value in inline.values if value != target]
                if len(values) != len(inline.values):
                    changed = True
                    output.extend(_format_external_dirs(values))
                    in_external = False
                    continue
            in_external = stripped == "external_dirs:"
            output.append(line)
            continue
        output.append(line)
    if not changed:
        return ConfigChange(False, "external dir absent", config_text)
    return ConfigChange(True, "removed external dir", "\n".join(output).rstrip() + "\n")


def read_config(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def write_config(path: Path, text: str) -> None:
    atomic_write_text(path, text)
