from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from .local_store import atomic_write_text


@dataclass(frozen=True)
class ConfigChange:
    changed: bool
    message: str
    text: str


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


def _inline_external_dirs(line: str) -> list[str] | None:
    match = re.match(r"^  external_dirs:\s*(?P<value>\S.*)$", line)
    if not match:
        return None
    return _parse_inline_list(match.group("value"))


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
        if in_skills and line.startswith("  ") and not line.startswith("    "):
            inline = _inline_external_dirs(line)
            if inline is not None:
                result.extend(inline)
                in_external = False
                continue
            in_external = stripped == "external_dirs:"
            continue
        if in_skills and in_external and line.startswith("    - "):
            result.append(stripped[2:].strip().strip("'\""))
    return result


def ensure_external_dir(config_text: str, skill_dir: str | Path) -> ConfigChange:
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
            inline = _inline_external_dirs(line)
            if inline is not None:
                values = inline
                if target in values:
                    return ConfigChange(False, "external dir already present", config_text)
                lines[idx:idx + 1] = _format_external_dirs([*values, target])
                return ConfigChange(True, "expanded inline external_dirs", "\n".join(lines) + "\n")
            if line.strip().startswith("external_dirs:") and line.strip() != "external_dirs:":
                raise ValueError("unsupported skills.external_dirs shape; use a YAML block list or inline list")
            if line.strip() == "external_dirs:":
                external_index = idx
                break

    if external_index is None:
        lines[skills_index + 1:skills_index + 1] = ["  external_dirs:", f"    - {target}"]
        return ConfigChange(True, "inserted skills.external_dirs", "\n".join(lines) + "\n")

    insert_at = external_index + 1
    while insert_at < len(lines) and lines[insert_at].startswith("    - "):
        insert_at += 1
    lines.insert(insert_at, f"    - {target}")
    return ConfigChange(True, "added external dir", "\n".join(lines) + "\n")


def remove_external_dir(config_text: str, skill_dir: str | Path) -> ConfigChange:
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
        if in_skills and line.startswith("  ") and not line.startswith("    "):
            inline = _inline_external_dirs(line)
            if inline is not None:
                values = [value for value in inline if value != target]
                if len(values) != len(inline):
                    changed = True
                    output.extend(_format_external_dirs(values))
                    in_external = False
                    continue
            in_external = stripped == "external_dirs:"
            output.append(line)
            continue
        if in_skills and in_external and line.startswith("    - "):
            value = stripped[2:].strip().strip("'\"")
            if value == target:
                changed = True
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
