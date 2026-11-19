"""Prepared per-dispatch model routing for Hermes-native delegation.

Hermes `delegate_task` resolves the child's model, provider, and reasoning
effort from the `delegation.*` keys of `config.yaml` **at every dispatch**,
and its config cache is keyed on the file's mtime and size — editing the file
between dispatches is therefore a supported, race-free way to give each child
its own route: write the route, dispatch the lane, write the next route,
dispatch the next lane. Children already running keep the model they were
built with.

This module owns that write. It is deliberately narrow:

* Only the three routable keys under the top-level `delegation:` section are
  ever touched — `model`, `reasoning_effort`, `provider`. Every other byte of
  the config, including the rest of the delegation section, passes through
  unchanged.
* Values must be plain identifier tokens; anything else is refused rather
  than quoted, so a crafted "model name" can never smuggle YAML structure.
* The write is atomic (temp file + rename in the config's directory) and a
  symlinked config is refused instead of silently replaced with a file.
* A route Hermes would not send where it says is refused before any byte is
  written (`guard_route_endpoint`, see `route_endpoint_guard`): a direct
  `delegation.base_url` that overrides the provider, the main model's
  local-endpoint bypass, a managed config layered over this file, or a shape
  the guard cannot read. The keys it names are the person's; OMH never
  rewrites them.
* A leading byte-order mark stays where it is, and the `delegation:` line
  after it is recognised rather than duplicated.

Writing a route is preparation, not execution: nothing dispatches from here,
and the route only takes effect when the agent's next `delegate_task` call
reads it.
"""

from __future__ import annotations

from . import runtime_paths
from .route_endpoint_guard import BOM, child_endpoint, managed_config_layer, route_endpoint_refusal

import os
import re
import tempfile
from pathlib import Path
from typing import Any, Mapping

ROUTABLE_KEYS = ("model", "reasoning_effort", "provider")

_VALUE_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._/-]|:(?=[A-Za-z0-9])){0,127}$")
_SECTION_RE = re.compile(r"^delegation:\s*(#.*)?$")
_MODEL_SECTION_RE = re.compile(r"^model:\s*(#.*)?$")
_MODEL_PROVIDER_RE = re.compile(r"^\s+provider\s*:")
def _managed_key_re(key: str, indent: int) -> re.Pattern[str]:
    return re.compile(rf"^ {{{indent}}}{re.escape(key)}\s*:")


def read_delegation_route(hermes_home: str | Path | None = None) -> dict[str, str]:
    """Read the current routable delegation keys from config.yaml (text scan).

    Last occurrence wins, mirroring YAML's duplicate-key behaviour, so what
    this reports is what Hermes will actually resolve.
    """
    config_path = _config_path(hermes_home)
    text, _, error = _read_config_snapshot(config_path)
    if error:
        return {}
    return _read_delegation_route_text(text)


def read_delegation_settings(hermes_home: str | Path | None, keys: tuple[str, ...]) -> dict[str, str]:
    """Other `delegation.*` scalars (`max_concurrent_children`, ...) as written, quotes and comments dropped.

    The same section scan as the routable keys, read-only and last occurrence
    wins; a value that is not a one-line scalar is left out, so a caller falls
    back to Hermes' own default for it.
    """
    text, _, error = _read_config_snapshot(_config_path(hermes_home))
    if error:
        return {}
    lines = text.removeprefix(BOM).splitlines()
    child_indents = _delegation_child_indents(lines)
    values: dict[str, str] = {}
    in_section = False
    child_indent = 2
    for index, line in enumerate(lines):
        if _SECTION_RE.match(line):
            in_section, child_indent = True, child_indents.get(index, 2)
            continue
        if in_section and _top_level_key(line) is not None:
            in_section = False
        key = _mapping_key(line, child_indent) if in_section else None
        if key in keys and _managed_key_re(key, child_indent).match(line):
            raw = line.partition(":")[2].split("#", 1)[0].strip().strip("'\"")
            if raw and not _continuation_follows(lines, index, child_indent):
                values[key] = raw
            else:
                values.pop(key, None)
    return values


def read_child_endpoint(hermes_home: str | Path | None = None) -> dict[str, str] | None:
    """Where Hermes builds a delegated child while `delegation.base_url` is set.

    `route_endpoint_guard.child_endpoint` over config.yaml and Hermes'
    managed config. A route that names no provider is written on that
    endpoint, so this is what makes it visible.
    """
    text, _, error = _read_config_snapshot(_config_path(hermes_home))
    if error:
        return {"from": "config.yaml", "host": "", "provider": ""}
    return child_endpoint(text, managed_config_layer())


def _read_delegation_route_text(text: str) -> dict[str, str]:
    lines = text.removeprefix(BOM).splitlines()
    if _has_unsupported_delegation(lines):
        return {}
    child_indents = _delegation_child_indents(lines)
    values: dict[str, str] = {}
    in_section = False
    child_indent = 2
    for index, line in enumerate(lines):
        if _SECTION_RE.match(line):
            in_section = True
            child_indent = child_indents.get(index, 2)
            continue
        if in_section and _top_level_key(line) is not None:
            in_section = False
        if not in_section:
            continue
        for key in ROUTABLE_KEYS:
            if _managed_key_re(key, child_indent).match(line):
                _, _, raw = line.partition(":")
                value = _yaml_string_token(raw)
                if value is None:
                    return {}
                # An empty value is Hermes's stock "inherit" spelling for the
                # key; last occurrence wins, so it unsets an earlier value.
                if value:
                    values[key] = value
                else:
                    values.pop(key, None)
    return values


def read_session_provider(hermes_home: str | Path | None = None) -> str:
    """The provider this session runs on, from config.yaml's own `model:` block.

    A child dispatched with no `delegation.provider` inherits this value, so
    it is the provider that will actually serve the run. Read by the same
    text scan as the delegation keys, and empty whenever the file, the block,
    or the key is missing -- an unknown provider must never be treated as a
    wrong one.
    """
    config_path = _config_path(hermes_home)
    text, _, error = _read_config_snapshot(config_path)
    if error:
        return ""
    return _read_session_provider_text(text)


def _read_session_provider_text(text: str) -> str:
    lines = text.removeprefix(BOM).splitlines()
    in_model = False
    provider = ""
    for line in lines:
        if _MODEL_SECTION_RE.match(line):
            in_model = True
            continue
        if in_model and _top_level_key(line) is not None:
            in_model = False
        if not in_model:
            continue
        if _MODEL_PROVIDER_RE.match(line):
            _, _, raw = line.partition(":")
            value = _yaml_string_token(raw)
            # Last occurrence wins, mirroring YAML, and a bare empty value
            # unsets an earlier one exactly as it does for delegation keys.
            provider = value or ""
    return provider


_ROUTE_WRITE_ATTEMPTS = 5


def _apply_route_delta(text: str, desired: Mapping[str, str]) -> str:
    """Return text with only the routable delegation keys set to desired.

    Pure transformation: every other byte passes through unchanged. Returns
    text itself when there is nothing to add or remove, so the caller can skip
    a byte-identical write.
    """
    bom = BOM if text.startswith(BOM) else ""
    lines = text[len(bom):].splitlines()
    child_indents = _delegation_child_indents(lines)
    output: list[str] = []
    inserted = False
    in_section = False
    section_seen = False
    child_indent = 2
    for index, line in enumerate(lines):
        if _SECTION_RE.match(line):
            in_section = True
            section_seen = True
            output.append(line)
            child_indent = child_indents.get(index, 2)
            prefix = " " * child_indent
            for key in ROUTABLE_KEYS:
                value = desired.get(key, "")
                if value:
                    output.append(f"{prefix}{key}: '{value}'")
            inserted = True
            continue
        if in_section and _top_level_key(line) is not None:
            in_section = False
        if in_section and any(
            _managed_key_re(key, child_indent).match(line)
            for key in ROUTABLE_KEYS
        ):
            continue
        output.append(line)
    wanted = {key: value for key, value in desired.items() if value}
    if wanted and not inserted:
        if output and output[-1].strip():
            output.append("")
        output.append("delegation:")
        for key in ROUTABLE_KEYS:
            value = wanted.get(key, "")
            if value:
                output.append(f"  {key}: '{value}'")
        section_seen = True
    if not section_seen and not wanted:
        return text
    new_text = bom + "\n".join(output)
    if text.endswith("\n") or not text:
        new_text += "\n"
    return new_text


def write_delegation_route(
    hermes_home: str | Path | None = None,
    *,
    model: str = "",
    reasoning_effort: str = "",
    provider: str = "",
    clear: bool = False,
    expected_previous: Mapping[str, str] | None = None,
    guard_route_endpoint: bool = False,
) -> dict[str, Any]:
    """Set (or clear) the routable delegation keys, touching nothing else.

    Keys with an empty desired value are removed, restoring parent
    inheritance for that key; `clear=True` removes all three.

    `guard_route_endpoint` is for a route: it refuses one Hermes would not
    send where it says (`route_endpoint_guard.route_endpoint_refusal`),
    judged on the config the write replaces, re-read just before the rename.
    A restore leaves it off, because putting back the person's own values is
    not a switch.
    """
    desired = {} if clear else {
        "model": model.strip(),
        "reasoning_effort": reasoning_effort.strip(),
        "provider": provider.strip(),
    }
    for key, value in desired.items():
        if value and not _VALUE_RE.match(value):
            return {"status": "error", "error": f"invalid {key} value"}
    config_path = _config_path(hermes_home)
    text, signature, error = _read_config_snapshot(config_path)
    if error:
        return {"status": "error", "error": error}
    if _file_signature(config_path) != signature:
        return {"status": "error", "error": "config changed during route read"}
    previous = _read_delegation_route_text(text)
    if expected_previous is not None and previous != dict(expected_previous):
        return {
            "status": "error",
            "error": "active route changed before fallback write",
        }
    bom = BOM if text.startswith(BOM) else ""
    lines = text[len(bom):].splitlines()
    if _has_unsupported_delegation(lines):
        return {
            "status": "error",
            "error": (
                "unsupported delegation mapping; refusing to rewrite it — "
                "no route was written, so the next delegate_task dispatch "
                "inherits the parent model"
            ),
        }
    if guard_route_endpoint:
        refusal = route_endpoint_refusal(
            text,
            provider=desired.get("provider", ""),
            current_provider=previous.get("provider", ""),
            managed=managed_config_layer(),
        )
        if refusal:
            return refusal
    wanted = {key: value for key, value in desired.items() if value}
    # Write from the latest config, not the validation snapshot. A writer
    # outside the OMH lock (hermes config set) may have added an unrelated key
    # since the snapshot; re-reading and re-applying only the delegation delta
    # just before the rename preserves every unrelated byte and closes the
    # lost update that dropped such keys. A byte-identical result is not written.
    for _attempt in range(_ROUTE_WRITE_ATTEMPTS):
        fresh_text, fresh_signature, fresh_error = _read_config_snapshot(config_path)
        if fresh_error:
            return {"status": "error", "error": fresh_error}
        fresh_bom = BOM if fresh_text.startswith(BOM) else ""
        if _has_unsupported_delegation(fresh_text[len(fresh_bom):].splitlines()):
            return {
                "status": "error",
                "error": (
                    "unsupported delegation mapping; refusing to rewrite it — "
                    "no route was written, so the next delegate_task dispatch "
                    "inherits the parent model"
                ),
            }
        if guard_route_endpoint:
            refusal = route_endpoint_refusal(
                fresh_text,
                provider=desired.get("provider", ""),
                current_provider=previous.get("provider", ""),
                managed=managed_config_layer(),
            )
            if refusal:
                return refusal
        new_text = _apply_route_delta(fresh_text, desired)
        if new_text == fresh_text:
            return {
                "status": "cleared" if clear else "routed",
                "previous": previous,
                "applied": wanted,
            }
        try:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temp_name = tempfile.mkstemp(
                prefix=".omh-delegation-route-", dir=str(config_path.parent)
            )
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    handle.write(new_text)
                if _file_signature(config_path) != fresh_signature:
                    os.unlink(temp_name)
                    continue
                if config_path.exists():
                    os.chmod(temp_name, config_path.stat().st_mode & 0o7777)
                os.replace(temp_name, config_path)
            except OSError:
                try:
                    os.unlink(temp_name)
                except OSError:
                    pass
                raise
        except OSError as exc:
            return {"status": "error", "error": f"config write failed: {type(exc).__name__}"}
        return {
            "status": "cleared" if clear else "routed",
            "previous": previous,
            "applied": wanted,
        }
    return {"status": "error", "error": "config kept changing during route update"}


def delegation_config_path(hermes_home: str | Path | None = None) -> Path:
    """The canonical identity of the config.yaml these keys live in.

    Public because the restore record has to say WHICH config it describes:
    two Hermes profiles may share one OMH home by design, and a record that
    named no file let one profile's session act on the other's route.

    The PARENT is resolved and the file name is not. Resolving the parent is
    what makes two callers agree: one may hold `/var/...` and another the
    `/private/var/...` the same path resolves to, and an unresolved compare
    reported one profile's own record as another profile's. Resolving the
    file itself would defeat the writer's `O_NOFOLLOW` refusal of a
    symlinked config, so this is identity only and never the path opened.
    """
    path = _config_path(hermes_home)
    try:
        return Path(os.path.realpath(path.parent)) / path.name
    except OSError:
        return path


def _config_path(hermes_home: str | Path | None) -> Path:
    if hermes_home:
        return Path(hermes_home).expanduser() / "config.yaml"
    return runtime_paths.default_hermes_home() / "config.yaml"


def _delegation_child_indents(lines: list[str]) -> dict[int, int]:
    indents: dict[int, int] = {}
    section_index: int | None = None
    for index, line in enumerate(lines):
        if _SECTION_RE.match(line):
            section_index = index
            continue
        if section_index is None:
            continue
        if _top_level_key(line) is not None:
            section_index = None
            continue
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(stripped)
        if indent:
            indents[section_index] = min(indents.get(section_index, indent), indent)
    return indents


def config_file_signature(path: Path) -> tuple[int, int, int, int] | None:
    """The stamp this writer compares, exposed for OMH's other config writers.

    Public on purpose and as a one-line alias rather than a second
    implementation: the whole point of one write discipline is that a CLI
    write and a route write can each detect the other, which they cannot do
    if the two sides compute their own idea of "the file changed" (#1742).

    `st_ino` is what carries the compare in practice. Both OMH writer
    families replace by rename, so the inode changes on every OMH write and
    the timestamp's resolution never enters into it. `st_mtime_ns` matters
    only for a third party rewriting the config IN PLACE at exactly the same
    size, and only on a filesystem that stores whole seconds (ext4 with
    128-byte inodes, HFS+); APFS and ext4 with 256-byte inodes store
    nanoseconds and distinguish consecutive rewrites.
    """
    return _file_signature(path)


def read_config_snapshot(path: Path) -> tuple[str, tuple[int, int, int, int] | None, str]:
    """Read the config and its stamp together, the way this writer does.

    Same reason as above, plus the `O_NOFOLLOW` refusal of a symlinked
    config: a writer that reached the file another way would not inherit it.
    """
    return _read_config_snapshot(path)


def _file_signature(path: Path) -> tuple[int, int, int, int] | None:
    try:
        stat = path.lstat()
    except FileNotFoundError:
        return None
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)


def _read_config_snapshot(
    path: Path,
) -> tuple[str, tuple[int, int, int, int] | None, str]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError:
        return "", None, ""
    except OSError as exc:
        if path.is_symlink():
            return "", None, "config.yaml is a symlink; refusing to rewrite it"
        return "", None, f"config unreadable: {type(exc).__name__}"
    try:
        stat = os.fstat(descriptor)
        with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
            text = handle.read()
    except (OSError, UnicodeDecodeError) as exc:
        try:
            os.close(descriptor)
        except OSError:
            pass
        return "", None, f"config unreadable: {type(exc).__name__}"
    signature = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
    return text, signature, ""


def _has_unsupported_delegation(lines: list[str]) -> bool:
    child_indents = _delegation_child_indents(lines)
    in_section = False
    child_indent = 2
    for index, line in enumerate(lines):
        top_level_key = _top_level_key(line)
        if top_level_key == "delegation":
            if not _SECTION_RE.match(line):
                return True
            in_section = True
            child_indent = child_indents.get(index, 2)
            continue
        if in_section and top_level_key is not None:
            in_section = False
        if not in_section:
            continue
        key = _mapping_key(line, child_indent)
        if key not in ROUTABLE_KEYS:
            continue
        if not _managed_key_re(key, child_indent).match(line):
            return True
        _, _, raw = line.partition(":")
        if _yaml_string_token(raw) is None:
            return True
        # A plain scalar (null, ~, or an ordinary token) continues onto a
        # more-indented following line in YAML: OMH would read one value
        # while Hermes resolves the continuation, and the writer would drop
        # the key line and orphan that continuation into unparseable YAML.
        # Refuse any routable key whose next content line sits deeper — the
        # guard is about whether a continuation follows, not which token
        # appeared.
        if _continuation_follows(lines, index, child_indent):
            return True
    return False


def _continuation_follows(lines: list[str], index: int, indent: int) -> bool:
    for following in lines[index + 1 :]:
        stripped = following.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        return len(following) - len(stripped) > indent
    return False


def _top_level_key(line: str) -> str | None:
    if not line or line[0].isspace() or line.startswith("#"):
        return None
    if line[0] in {"'", '"'}:
        quote = line[0]
        end = line.find(quote, 1)
        if end < 0 or not line[end + 1 :].lstrip().startswith(":"):
            return None
        return line[1:end]
    key, separator, _ = line.partition(":")
    return key.strip() if separator and key.strip() else None


def _mapping_key(line: str, indent: int) -> str | None:
    prefix = " " * indent
    if not line.startswith(prefix):
        return None
    remainder = line[indent:]
    if not remainder or remainder[0].isspace():
        return None
    return _top_level_key(remainder)


def _yaml_string_token(raw: str) -> str | None:
    value = raw.split("#", 1)[0].strip()
    if (
        len(value) >= 2
        and value[0] in {"'", '"'}
        and value[-1] == value[0]
    ):
        token = value[1:-1]
        if not token:
            # `model: ''` is Hermes's own stock config shape for "no route,
            # inherit the parent". It is an absent value, not an unsupported
            # mapping — refusing it locked routing out of every vanilla
            # install (observed live: all category sets refused, lanes
            # silently dispatched as inherit).
            return ""
        return token if _VALUE_RE.fullmatch(token) else None
    lowered = value.casefold()
    if lowered in {"~", "null"}:
        # Same inherit family. These are PLAIN scalars, which YAML continues
        # onto a more-indented following line — that continuation case is
        # refused by the lookahead in _has_unsupported_delegation, not here.
        return ""
    if not lowered:
        # A BARE empty value is different: `model:` with nothing after the
        # colon may be a block-mapping header whose children live on the next,
        # more-indented lines. Treating it as an empty scalar would let the
        # writer drop the header and orphan those children into unparseable
        # YAML, so it stays refused.
        return None
    if lowered in {
        "true",
        "false",
        "yes",
        "no",
        "on",
        "off",
        "y",
        "n",
    }:
        return None
    if re.fullmatch(
        r"(?:[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[-+]?\d+)?"
        r"|0x[0-9a-f]+|0o[0-7]+|0b[01]+|\d{4}-\d{2}-\d{2})",
        lowered,
    ):
        return None
    return value if _VALUE_RE.fullmatch(value) else None
