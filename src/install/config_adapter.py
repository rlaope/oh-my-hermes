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


def plugin_enablement(config_text: str) -> dict[str, list[str]]:
    """Read Hermes' `plugins.enabled` / `plugins.disabled` lists.

    Read-only, and shaped like `external_dirs` above rather than pulling in a
    YAML parser, since the core stays dependency-free.

    A bundle can be installed, importable, and register cleanly while Hermes
    still refuses to load it, because enablement lives here and nowhere else.
    `omh doctor` reported `Hermes registration: ok (4/4)` against exactly that
    state, so every OMH tool was unreachable in chat while the install looked
    healthy.
    """
    lists: dict[str, list[str]] = {"enabled": [], "disabled": []}
    in_plugins = False
    current = ""
    for line in config_text.splitlines():
        stripped = line.strip()
        if not line.startswith(" ") and stripped:
            in_plugins = stripped == "plugins:"
            current = ""
            continue
        if not in_plugins or not stripped:
            continue
        if line.startswith("  ") and not line.startswith("    "):
            key, _, rest = stripped.partition(":")
            key = key.strip()
            inline = _parse_inline_list(rest.strip()) if rest.strip() else None
            if key in lists and inline is not None:
                lists[key] = list(inline)
                current = ""
                continue
            current = key if key in lists else ""
            continue
        if current and stripped.startswith("- "):
            lists[current].append(stripped[2:].strip().strip("\"'"))
    return lists


def plugin_is_enabled(config_text: str, name: str) -> bool:
    listed = plugin_enablement(config_text)
    return name in listed["enabled"] and name not in listed["disabled"]


def ensure_plugin_enabled(config_text: str, name: str) -> ConfigChange:
    """Add `name` to `plugins.enabled` so Hermes will actually load the bridge.

    Installing the bundle and enabling it are separate steps, and setup only did
    the first. The result is an install that passes every structural check while
    no OMH tool is reachable in chat.

    Never un-disables: if the plugin is listed under `plugins.disabled` that is a
    deliberate opt-out, and setup must not override it. `omh doctor` reports that
    state instead.
    """
    listed = plugin_enablement(config_text)
    if name in listed["disabled"]:
        return ConfigChange(False, f"{name} is explicitly disabled; leaving it alone", config_text)
    if name in listed["enabled"]:
        return ConfigChange(False, "plugin already enabled", config_text)

    lines = config_text.splitlines()
    plugins_index = next(
        (idx for idx, line in enumerate(lines) if line.strip() == "plugins:" and not line.startswith(" ")),
        None,
    )
    if plugins_index is None:
        text = (config_text.rstrip() + f"\n\nplugins:\n  enabled:\n    - {name}\n").lstrip("\n")
        return ConfigChange(True, "appended plugins.enabled", text)

    for idx in range(plugins_index + 1, len(lines)):
        line = lines[idx]
        if line.strip() and not line.startswith(" "):
            break
        if line.startswith("  ") and not line.startswith("    "):
            key, _, rest = line.strip().partition(":")
            if key.strip() != "enabled":
                continue
            inline = _parse_inline_list(rest.strip()) if rest.strip() else None
            if inline is not None:
                lines[idx:idx + 1] = ["  enabled:", *[f"    - {value}" for value in [*inline, name]]]
                return ConfigChange(True, "expanded inline plugins.enabled", "\n".join(lines) + "\n")
            lines.insert(idx + 1, f"    - {name}")
            return ConfigChange(True, "added plugin to plugins.enabled", "\n".join(lines) + "\n")

    lines.insert(plugins_index + 1, f"    - {name}")
    lines.insert(plugins_index + 1, "  enabled:")
    return ConfigChange(True, "inserted plugins.enabled", "\n".join(lines) + "\n")


def memory_provider_selection(config_text: str) -> str:
    """The name in `memory.provider`, or "" when Hermes is on its built-in memory."""
    return _section_scalar(config_text, "memory", "provider")


def maybe_set_memory_provider(config_text: str, name: str, mode: str) -> ConfigChange:
    """Alias of `set_memory_provider` that honors the CLI's memory_mode.

    mode='off' means the operator explicitly told setup to leave Hermes
    memory integration alone; in that case we must not claim the
    `memory.provider` slot, whether it is empty or already set. Other modes
    ('basic'/'full') preserve today's claim semantics via `set_memory_provider`.
    """
    if mode == "off":
        return ConfigChange(False, "memory provider claim skipped (memory mode off)", config_text)
    return set_memory_provider(config_text, name)


def set_memory_provider(config_text: str, name: str) -> ConfigChange:
    """Point `memory.provider` at `name`, unless another product already holds it.

    Hermes runs at most one external memory provider
    (`agent/memory_manager.py`), so this key is a slot rather than a list.
    Overwriting a different provider would silently switch off whatever the
    operator chose -- honcho, mem0, hindsight -- so it is refused and reported
    instead. Clearing the slot is the operator's call, made explicitly.
    """
    current = memory_provider_selection(config_text)
    if current == name:
        return ConfigChange(False, f"memory.provider is already {name}", config_text)
    if current:
        return ConfigChange(
            False,
            f"memory.provider is {current}; Hermes runs one external provider, so clear it first",
            config_text,
        )

    lines = config_text.splitlines()
    memory_index = next(
        (idx for idx, line in enumerate(lines) if line.strip() == "memory:" and not line.startswith(" ")),
        None,
    )
    if memory_index is None:
        text = (config_text.rstrip() + f"\n\nmemory:\n  provider: {name}\n").lstrip("\n")
        return ConfigChange(True, "appended memory.provider", text)

    for idx in range(memory_index + 1, len(lines)):
        line = lines[idx]
        if line.strip() and not line.startswith(" "):
            break
        if line.startswith("  ") and not line.startswith("    "):
            key, _, _rest = line.strip().partition(":")
            if key.strip() == "provider":
                lines[idx] = f"  provider: {name}"
                return ConfigChange(True, "set memory.provider", "\n".join(lines) + "\n")

    lines.insert(memory_index + 1, f"  provider: {name}")
    return ConfigChange(True, "inserted memory.provider", "\n".join(lines) + "\n")


def clear_memory_provider(config_text: str, name: str) -> ConfigChange:
    """Hand the slot back, but only when `name` is the one holding it."""
    current = memory_provider_selection(config_text)
    if not current:
        return ConfigChange(False, "memory.provider is already unset", config_text)
    if current != name:
        return ConfigChange(False, f"memory.provider is {current}, not {name}; leaving it alone", config_text)

    lines = config_text.splitlines()
    for idx, line in enumerate(lines):
        if not line.startswith("  ") or line.startswith("    "):
            continue
        key, _, _rest = line.strip().partition(":")
        if key.strip() == "provider" and _enclosing_section(lines, idx) == "memory":
            lines[idx] = "  provider: ''"
            return ConfigChange(True, "cleared memory.provider", "\n".join(lines) + "\n")
    return ConfigChange(False, "memory.provider line not found", config_text)


def _section_scalar(config_text: str, section: str, key: str) -> str:
    dotted = f"{section}.{key}:"
    for index, line in enumerate(config_text.splitlines()):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith(dotted) and not line.startswith(" "):
            return _scalar_value(stripped[len(dotted) :])
        if line.startswith("  ") and not line.startswith("    "):
            candidate, separator, rest = stripped.partition(":")
            if separator and candidate.strip() == key and _enclosing_section(config_text.splitlines(), index) == section:
                return _scalar_value(rest)
    return ""


def _enclosing_section(lines: list[str], index: int) -> str:
    for cursor in range(index - 1, -1, -1):
        line = lines[cursor]
        if line.strip() and not line.startswith(" "):
            return line.strip().rstrip(":")
    return ""


def _scalar_value(value: str) -> str:
    stripped = value.split("#")[0].strip() if not value.strip().startswith(("'", '"')) else value.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in {"'", '"'}:
        return stripped[1:-1]
    return stripped


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
