from __future__ import annotations

from collections.abc import Iterable

import os

from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
import random
import re
import time
from typing import Callable

from omh.skin_pack import SKIN_NAME, is_omh_skin_name

from ..core.errors import OmhError
from ..plugin_bundle.omh import runtime_paths

from ..system.local_store import atomic_replace_text, atomic_write_text


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


def _classify_dotted_external_dirs(line: str) -> _InlineExternalDirs:
    match = re.match(r"^skills\.external_dirs:\s*(?P<value>\S.*)$", line)
    if not match:
        return _InlineExternalDirs(False, False, [])
    value = match.group("value").strip()
    if value in _BARE_YAML_NULLS:
        return _InlineExternalDirs(True, True, [])
    parsed = _parse_inline_list(value)
    return _InlineExternalDirs(True, parsed is not None, parsed or [])


def _dotted_plugin_list(line: str) -> tuple[str, list[str] | None] | None:
    if line.startswith(" "):
        return None
    key, sep, value = line.strip().partition(":")
    if not sep or key not in {"plugins.enabled", "plugins.disabled"}:
        return None
    return key.split(".", 1)[1], _parse_inline_list(value.strip())


_BARE_YAML_NULLS = {"null", "Null", "NULL", "~"}
# `'[]'` and `"[]"` are strings to YAML, not sequences: Hermes reads either as
# no plugins at all, and a list item cannot be added under a closed scalar.
_EMPTY_QUOTED_FLOW_SEQUENCES = {"'[]'", '"[]"'}
_UNSUPPORTED_EXTERNAL_DIRS_SHAPE = "unsupported skills.external_dirs shape; use a YAML block list or inline list"
_DUPLICATE_EXTERNAL_DIRS_SHAPE = "duplicate skills.external_dirs entries are unsupported; keep one YAML block list or inline list"
_DUPLICATE_ENABLED_SHAPE = "duplicate plugins.enabled keys are unsupported; keep one YAML block list or inline list"


def _normalize(value: str | Path) -> str:
    # POSIX-form separators keep config.yaml entries byte-stable across
    # platforms; on POSIX this equals str().
    return Path(value).expanduser().as_posix()


def _parse_inline_list(value: str) -> list[str] | None:
    value = value.strip()
    if value == "[]":
        return []
    if not (value.startswith("[") and value.endswith("]")):
        return None
    inner = value[1:-1].strip()
    if not inner:
        return []
    items: list[str] = []
    for raw in inner.split(","):
        item = raw.strip().strip("'\"")
        if not item:
            return None
        items.append(item)
    return items


def _plugins_list_shape(rest: str) -> tuple[str, list[str]]:
    """Classify the text after `enabled:` / `disabled:` on a `plugins.*` key line.

    `block`: nothing (or only a comment) follows the colon, so the members are
    the `- item` lines under it. `inline`: a flow sequence this editor can
    rewrite. `empty`: a scalar that carries no member -- a YAML null, or the
    quoted `[]` YAML reads as a string and Hermes therefore reads as no
    plugins (#1825). `scalar`: any other scalar. YAML refuses a child node
    under a closed value and folds one under a plain scalar into the string,
    so the writer must never insert an item under the last two.
    """
    value = rest.strip()
    if not value or value.startswith("#") or _only_node_properties(value):
        return "block", []
    inline = _parse_inline_list(_split_trailing_comment(value)[0])
    if inline is not None:
        return "inline", inline
    if value in _BARE_YAML_NULLS or value in _EMPTY_QUOTED_FLOW_SEQUENCES:
        return "empty", []
    return "scalar", []


def _split_trailing_comment(value: str, closers: str = "]") -> tuple[str, str]:
    """`[omh] # keep` -> (`[omh]`, ` # keep`); anything else -> (`value`, "").

    The split is taken only when what precedes ` #` closes a flow node, so
    `['a #b', omh]` stays one value and a quoted scalar keeps its comment as
    part of the text it is refused with. YAML reads the comment as nothing;
    the writers carry it onto the key line so the person's note survives the
    rewrite.

    `closers` is which flow node may end the value: a sequence for the
    `enabled:` / `disabled:` key lines, a sequence or a mapping for the
    `plugins:` node line, which is the one place a flow mapping is read.
    """
    head, sep, tail = value.partition(" #")
    if sep and head.rstrip().endswith(tuple(closers)):
        return head.rstrip(), f" #{tail}"
    return value, ""


_PLUGINS_NODE_BLOCK = "block"
_PLUGINS_NODE_FLOW = "flow"
_PLUGINS_NODE_UNREADABLE = "unreadable"


def _split_flow_items(inner: str) -> list[str] | None:
    """Split a flow node's body on the commas that separate its members.

    A comma inside a nested flow node or inside quotes belongs to the member,
    not to the node above it, so a plain `split(",")` reads
    `{enabled: [a, b]}` as two pairs and neither of them as a key. `None` for
    a bracket or a quote that never closes: Hermes refuses that file outright,
    and this reader must not answer for a document its own loader rejects.
    """
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    quote = ""
    for char in inner:
        if quote:
            current.append(char)
            if char == quote:
                quote = ""
            continue
        if char in "'\"":
            quote = char
        elif char in "[{":
            depth += 1
        elif char in "]}":
            depth -= 1
            if depth < 0:
                return None
        elif char == "," and depth == 0:
            parts.append("".join(current))
            current = []
            continue
        current.append(char)
    if depth or quote:
        return None
    parts.append("".join(current))
    return parts


def _plugins_flow_mapping(inner: str) -> dict[str, list[str]] | None:
    """Read `enabled` / `disabled` out of a `plugins:` flow mapping body, or None.

    Bounded on purpose, and `None` means "this reader did not read the node",
    never "nothing is enabled" -- the difference the whole predicate below
    exists to keep. Refused: a backslash, which is a double-quoted escape the
    splitter above does not model; a member with no colon; a repeated
    `enabled` or `disabled` key, since YAML keeps the last and reading either
    would be a guess; and a member whose value is itself a flow mapping,
    which Hermes hands its plugin loader as a mapping and not as a list of
    names. A key OMH does not model is skipped, the way the block reader
    skips a key that is neither `enabled` nor `disabled`.

    Members go through `_parse_inline_list`, so a flow mapping reads exactly
    what the same sequence reads on its own key line and the two forms cannot
    give different answers.
    """
    if "\\" in inner:
        return None
    parts = _split_flow_items(inner)
    if parts is None:
        return None
    lists: dict[str, list[str]] = {"enabled": [], "disabled": []}
    seen: set[str] = set()
    for part in parts:
        member = part.strip()
        if not member:
            continue
        key, sep, raw = member.partition(":")
        if not sep:
            return None
        key = key.strip().strip("\"'")
        if key not in lists:
            continue
        if key in seen:
            return None
        seen.add(key)
        value = raw.strip()
        if value.startswith("{"):
            return None
        parsed = _parse_inline_list(value)
        if parsed is not None:
            lists[key] = parsed
        # Any other scalar here (a null, the quoted `[]`, a bare name) carries
        # no list member, so Hermes loads no plugin from it and the empty list
        # this leaves in place is the answer, not a gap.
    return lists


def _plugins_node_shape(rest: str) -> tuple[str, dict[str, list[str]]]:
    """Classify the text after a top-level `plugins:`, and read a flow mapping.

    `block`: nothing or only a comment follows the colon, so `enabled` and
    `disabled` are the lines below -- what Hermes writes and what every writer
    here edits. `flow`: a single-line flow mapping, which Hermes loads exactly
    as it loads the block form; measured with the PyYAML in Hermes' own venv,
    `plugins: {enabled: [hermes-jev]}` loads as
    `{'plugins': {'enabled': ['hermes-jev']}}`. `unreadable`: everything else,
    including an anchor or a tag on the node. An anchored `plugins: &p` is a
    block node a `*p` alias elsewhere resolves to, and the writers here must
    not edit under it, so the reader does not claim it either.

    One classifier for the reader, the readability predicate and the writers,
    so no caller can disagree with another about which node it is looking at.
    """
    value = _split_trailing_comment(rest.strip(), closers="]}")[0].strip()
    if not value or value.startswith("#"):
        return _PLUGINS_NODE_BLOCK, {}
    if not (value.startswith("{") and value.endswith("}")):
        return _PLUGINS_NODE_UNREADABLE, {}
    lists = _plugins_flow_mapping(value[1:-1])
    if lists is None:
        return _PLUGINS_NODE_UNREADABLE, {}
    return _PLUGINS_NODE_FLOW, lists


def _plugins_node_line_shape(line: str) -> tuple[str, dict[str, list[str]]] | None:
    """`line`'s `plugins` node shape, or None when this is not that key line.

    By key rather than by the exact text `plugins:`, so `plugins:  # third-party`
    is the node it is rather than a node nobody found.
    """
    if line.startswith(" ") or not line.strip():
        return None
    key, sep, rest = line.strip().partition(":")
    if not sep or key.strip() != "plugins":
        return None
    return _plugins_node_shape(rest)


def _only_node_properties(value: str) -> bool:
    """`&anchor` / `!tag` alone: properties of the block node on the lines below.

    `enabled: &plist` followed by items is a list every `*plist` alias in the
    file resolves to, not a scalar; reading it as one would empty the list
    and the reversal guard (`test_config_reversal`) already refuses to edit
    under it. The writers keep their own refusal; this only keeps the reader
    honest about where the members are.
    """
    tokens = value.split(" #", 1)[0].split()
    return bool(tokens) and all(token[:1] in {"&", "!"} for token in tokens)


def _closed_yaml_value(value: str) -> bool:
    """Whether YAML refuses a child node under `value`: quoted or a flow node."""
    return value[:1] in {"'", '"', "[", "{"}


def _quoted_inline_items(value: str) -> bool:
    """Whether an inline flow sequence carries quoting this editor would lose."""
    return "'" in value or '"' in value


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
            dotted = _classify_dotted_external_dirs(line)
            if dotted.matched:
                external_dirs_declarations += 1
                if external_dirs_declarations > 1:
                    raise ValueError(_DUPLICATE_EXTERNAL_DIRS_SHAPE)
                if not dotted.supported:
                    raise ValueError(_UNSUPPORTED_EXTERNAL_DIRS_SHAPE)
                in_skills = False
                continue
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
            dotted = _classify_dotted_external_dirs(line)
            if dotted.matched:
                if dotted.supported:
                    result.extend(dotted.values)
                in_skills = False
                in_external = False
                continue
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

    Both forms Hermes loads are read: the block node, whose keys are the lines
    below, and the flow mapping `plugins: {enabled: [omh]}`, whose keys are on
    the key line. The entry condition used to be the exact text `plugins:`, so
    the flow form returned the empty lists a config enabling nothing returns
    and every caller reported a plugin the host had enabled as disabled
    (#1814). A node outside both forms leaves the lists empty and
    `plugin_enablement_is_readable` False, which is what keeps that answer
    from being read as a negative.
    """
    lists: dict[str, list[str]] = {"enabled": [], "disabled": []}
    in_plugins = False
    current = ""
    for line in config_text.splitlines():
        stripped = line.strip()
        if not line.startswith(" ") and stripped:
            dotted = _dotted_plugin_list(line)
            if dotted is not None:
                key, values = dotted
                if values is not None:
                    lists[key] = list(values)
                in_plugins = False
                current = ""
                continue
            current = ""
            node = _plugins_node_line_shape(line)
            in_plugins = node is not None and node[0] == _PLUGINS_NODE_BLOCK
            if node is not None and node[0] == _PLUGINS_NODE_FLOW:
                for key, values in node[1].items():
                    lists[key] = list(values)
            continue
        if not in_plugins or not stripped:
            continue
        # A list item belongs to the key above it whether it sits under that
        # key (`    - omh`, Hermes' own style) or level with it (`  - omh`,
        # equally valid YAML). Checking the item shape before the key shape is
        # what keeps a level item from being read as a new key and emptying
        # the list (issue #1322).
        if stripped.startswith("- "):
            if current:
                lists[current].append(stripped[2:].strip().strip("\"'"))
            continue
        if line.startswith("  ") and not line.startswith("    "):
            key, _, rest = stripped.partition(":")
            key = key.strip()
            shape, inline = _plugins_list_shape(rest)
            if key in lists and shape == "inline":
                lists[key] = list(inline)
                current = ""
                continue
            if key in lists and shape != "block":
                # Hermes keeps only list members (`_names` in its plugin
                # loader), so a scalar here means no plugins, and a scalar
                # takes no children: item lines below it belong to nothing,
                # not to this key (#1825).
                lists[key] = []
                current = ""
                continue
            current = key if key in lists else ""
    return lists


def _plugin_list_item_indent(lines: list[str], plugins_index: int) -> str:
    """The indent the file already uses for `plugins.*` list items.

    Hermes writes `    - name`; a hand-edited file may use `  - name`. A new
    item has to match whichever is there, or the list ends up with items at
    two depths and YAML reads it as two different nodes.
    """
    for line in lines[plugins_index + 1:]:
        if line.strip() and not line.startswith(" "):
            break
        if line.strip().startswith("- "):
            return line[: len(line) - len(line.lstrip(" "))]
    return "    "


# The provider-id reader lives in the plugin bundle (`provider_detection`),
# which cannot import this module: routing-time detection, the setup
# interview and every test read `providers.<id>` and `model.provider` through
# one function, so the two sides cannot disagree on a config.
from ..plugin_bundle.omh.provider_detection import configured_provider_ids  # noqa: E402, F401


def plugin_is_enabled(config_text: str, name: str) -> bool:
    listed = plugin_enablement(config_text)
    return name in listed["enabled"] and name not in listed["disabled"]


def plugin_enablement_is_readable(config_text: str) -> bool:
    """Whether `plugin_enablement` read the `plugins:` node or walked past it.

    That reader follows two forms, the block node and the single-line flow
    mapping, and returns empty lists for anything else -- an alias, a scalar,
    an anchored node. Empty lists are also what a config that enables nothing
    produces, and the two are different facts: one is "nothing is enabled",
    the other is "nobody read it". A caller that reports the second as the
    first states a machine fact it does not hold.

    This predicate is derived from the reader's own classifier rather than
    from a second opinion about YAML, so it cannot drift from what the reader
    does. It is not a claim that every other form is modelled -- it answers
    only for the node this key names, which is the one `plugins.enabled`
    lives in.
    """
    for line in config_text.splitlines():
        node = _plugins_node_line_shape(line)
        if node is not None and node[0] == _PLUGINS_NODE_UNREADABLE:
            return False
    return True


def plugin_enablement_shape_error(config_text: str) -> str:
    """Why Hermes reads no list at `plugins.enabled` / `plugins.disabled`, or "".

    Names one shape: a key whose value is a scalar with `- item` lines under
    it, which is what setup wrote for `enabled: '[]'` before #1825. Under a
    closed value (a quoted string or a flow node) YAML refuses the children
    and Hermes fails the whole file; under a plain scalar YAML folds them
    into the string, so Hermes loads no plugin and reports nothing. The line
    reader used to attribute those items to the key, and doctor reported the
    plugin enabled. It no longer does; this is the sentence that says why, so
    doctor can report the file rather than the switch.
    """
    in_plugins = False
    scalar_key = ""
    scalar_value = ""
    for line in config_text.splitlines():
        stripped = line.strip()
        if not line.startswith(" ") and stripped:
            node = _plugins_node_line_shape(line)
            in_plugins = node is not None and node[0] == _PLUGINS_NODE_BLOCK
            scalar_key = ""
            continue
        if not in_plugins or not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- "):
            if not scalar_key:
                continue
            # A closed value takes no child at any depth; a plain scalar
            # folds a deeper item into itself, but an item at the key's own
            # indent ends the scalar and YAML refuses it too.
            level_item = len(line) - len(line.lstrip(" ")) <= 2
            if _closed_yaml_value(scalar_value) or level_item:
                consequence = "Hermes cannot parse this file"
            else:
                consequence = "YAML folds the items into that string, so Hermes loads no plugin from it"
            return (
                f"plugins.{scalar_key} is the scalar `{scalar_value}` with list items under it; "
                f"{consequence}. Rewrite the key as a YAML block list."
            )
        if line.startswith("  ") and not line.startswith("    "):
            key, _, rest = stripped.partition(":")
            key = key.strip()
            shape, _members = _plugins_list_shape(rest)
            if key in ("enabled", "disabled") and shape in ("empty", "scalar"):
                scalar_key, scalar_value = key, rest.strip()
            else:
                scalar_key = ""
    return ""


def _unsupported_enabled_shape_message(value: str, name: str) -> str:
    return (
        f"unsupported plugins.enabled shape ({value!r}); use a YAML block list "
        f"or inline list, or run `hermes plugins enable {name}`"
    )


def _unextendable_plugins_node_message(line: str, name: str) -> str:
    return (
        f"setup extends a plain `plugins:` block and this file writes the node as "
        f"`{line}`; OMH does not add an item under a node its uninstall cannot take "
        f"it back out of. Rewrite it as `plugins:` over `  enabled:`, or run "
        f"`hermes plugins enable {name}`"
    )


def _plugins_node_extension_error(config_text: str, name: str) -> str:
    """Why setup cannot add `name` under this `plugins` node, or "".

    `ensure_plugin_enabled` looked for the exact text `plugins:`, found
    nothing under a flow mapping or an alias, and appended a second top-level
    `plugins:` block; measured with the PyYAML in Hermes' own venv, a
    duplicate top-level key resolves to its last value, so
    `plugins: {enabled: [hermes-jev]}` plus that appended block loads as
    `{'plugins': {'enabled': ['omh']}}` -- the person's own plugin dropped,
    with no error anywhere (#1814).

    The bar is the remover's, not the reader's: `remove_plugin_enabled` goes
    through `section_edit_guard`, which refuses every `plugins` node that is
    not the plain block, so a node the reader now follows is still one setup
    must not write into. Adding an item OMH could never take back out is the
    one outcome worse than refusing. The refusal names Hermes' own writer
    instead.

    Silent when no write is needed. A name already enabled, or deliberately
    disabled, is an answer `ensure_plugin_enabled` gives without touching the
    file, so a flow-form config that already enables the bridge is not
    reported as a fault.
    """
    for line in config_text.splitlines():
        if _plugins_node_line_shape(line) is None or line.strip() == "plugins:":
            continue
        listed = plugin_enablement(config_text)
        if name in listed["enabled"] or name in listed["disabled"]:
            return ""
        return _unextendable_plugins_node_message(line.strip(), name)
    return ""


def _plugins_block_index(lines: list[str]) -> int | None:
    """The index of the plain top-level `plugins:` this module's writers edit.

    The exact text, matching the guard `remove_plugin_enabled` already runs.
    `_plugins_node_extension_error` has refused every other node shape before
    a writer reaches this, so a miss here means the document names no
    `plugins` key at all.
    """
    for index, line in enumerate(lines):
        if line.strip() == "plugins:" and not line.startswith(" "):
            return index
    return None


def plugins_enabled_extension_error(config_text: str, name: str) -> str:
    """Why `ensure_plugin_enabled` would refuse `config_text`, or "".

    The same sentence setup raises, so `omh doctor` can report it on a home
    where setup already refused: setup stops before it installs the bundle,
    and the plugin checks only run once a bundle exists, so without this the
    diagnostic named side effects and never the cause (#1825).
    """
    shape_error = plugin_enablement_shape_error(config_text)
    if shape_error:
        return shape_error
    node_error = _plugins_node_extension_error(config_text, name)
    if node_error:
        return node_error
    in_plugins = False
    enabled_keys = 0
    for line in config_text.splitlines():
        stripped = line.strip()
        if not line.startswith(" ") and stripped:
            node = _plugins_node_line_shape(line)
            in_plugins = node is not None and node[0] == _PLUGINS_NODE_BLOCK
            continue
        if not in_plugins or not stripped or stripped.startswith("- "):
            continue
        if line.startswith("  ") and not line.startswith("    "):
            key, _, rest = stripped.partition(":")
            if key.strip() != "enabled":
                continue
            enabled_keys += 1
            if enabled_keys > 1:
                # YAML keeps the last duplicate and the writer edits the
                # first, so setup would report an enable Hermes never reads.
                return _DUPLICATE_ENABLED_SHAPE
            if _plugins_list_shape(rest)[0] == "scalar":
                return _unsupported_enabled_shape_message(rest.strip(), name)
    return ""


def ensure_plugin_enabled(config_text: str, name: str) -> ConfigChange:
    """Add `name` to `plugins.enabled` so Hermes will actually load the bridge.

    Installing the bundle and enabling it are separate steps, and setup only did
    the first. The result is an install that passes every structural check while
    no OMH tool is reachable in chat.

    Never un-disables: if the plugin is listed under `plugins.disabled` that is a
    deliberate opt-out, and setup must not override it. `omh doctor` reports that
    state instead.
    """
    refusal = plugins_enabled_extension_error(config_text, name)
    if refusal:
        raise ValueError(refusal)
    listed = plugin_enablement(config_text)
    if name in listed["disabled"]:
        return ConfigChange(False, f"{name} is explicitly disabled; leaving it alone", config_text)
    if name in listed["enabled"]:
        return ConfigChange(False, "plugin already enabled", config_text)

    lines = config_text.splitlines()
    dotted_plugin_index = None
    for idx, line in enumerate(lines):
        dotted = _dotted_plugin_list(line)
        if dotted is None:
            continue
        key, values = dotted
        if values is None:
            raise ValueError(f"unsupported plugins.{key} shape; use an inline YAML list")
        if dotted_plugin_index is None:
            dotted_plugin_index = idx
        if key == "enabled":
            lines[idx] = f"plugins.enabled: [{', '.join([*values, name])}]"
            return ConfigChange(True, "expanded dotted plugins.enabled", "\n".join(lines) + "\n")
    if dotted_plugin_index is not None:
        lines.insert(dotted_plugin_index, f"plugins.enabled: [{name}]")
        return ConfigChange(True, "inserted dotted plugins.enabled", "\n".join(lines) + "\n")
    plugins_index = _plugins_block_index(lines)
    if plugins_index is None:
        # Only reachable when the document names no `plugins` key at all:
        # `_plugins_node_extension_error` above has already refused every node
        # this writer cannot extend, so appending here can no longer shadow a
        # node that is there.
        text = (config_text.rstrip() + f"\n\nplugins:\n  enabled:\n    - {name}\n").lstrip("\n")
        return ConfigChange(True, "appended plugins.enabled", text)

    indent = _plugin_list_item_indent(lines, plugins_index)
    for idx in range(plugins_index + 1, len(lines)):
        line = lines[idx]
        if line.strip() and not line.startswith(" "):
            break
        if line.strip().startswith("- "):
            continue
        if line.startswith("  ") and not line.startswith("    "):
            key, _, rest = line.strip().partition(":")
            if key.strip() != "enabled":
                continue
            shape, inline = _plugins_list_shape(rest)
            if shape == "inline":
                comment = _split_trailing_comment(rest.strip())[1]
                lines[idx:idx + 1] = [f"  enabled:{comment}", *[f"{indent}- {value}" for value in [*inline, name]]]
                return ConfigChange(True, "expanded inline plugins.enabled", "\n".join(lines) + "\n")
            if shape == "empty":
                # A null or a quoted `[]` carries no member, so a block list
                # loses nothing of the person's. Inserting an item under it
                # is what wrote the file Hermes could not parse (#1825).
                lines[idx:idx + 1] = ["  enabled:", f"{indent}- {name}"]
                return ConfigChange(
                    True, "normalized empty plugins.enabled to a block list", "\n".join(lines) + "\n"
                )
            if shape == "scalar":
                # Hermes reads any other scalar as no plugins. Rewriting it
                # would decide what the person meant, so setup stops with the
                # file untouched and names Hermes' own writer instead.
                raise ValueError(_unsupported_enabled_shape_message(rest.strip(), name))
            lines.insert(idx + 1, f"{indent}- {name}")
            return ConfigChange(True, "added plugin to plugins.enabled", "\n".join(lines) + "\n")

    lines.insert(plugins_index + 1, f"{indent}- {name}")
    lines.insert(plugins_index + 1, "  enabled:")
    return ConfigChange(True, "inserted plugins.enabled", "\n".join(lines) + "\n")


PLUGIN_OMH_HOME_KEY_PATH: tuple[str, ...] = ("plugins", "entries", "omh", "settings", "omh_home")


def plugin_omh_home_setting(config_text: str) -> str:
    """The raw `plugins.entries.omh.settings.omh_home`, or "" when none is readable.

    Read through the plugin's own standalone scan, so this can never find a
    value the plugin would not bind, or miss one it would.
    """
    try:
        found, value = runtime_paths.omh_home_setting(config_text)
    except runtime_paths.RuntimeBindingError:
        return ""
    return (value or "") if found else ""


def ensure_plugin_omh_home(config_text: str, omh_home: str | Path) -> ConfigChange:
    """Name `omh_home` as the store the plugin loaded from this home binds (#1960).

    Without it the plugin resolves the Hermes process's `OMH_HOME`, then
    `~/.omh`, so an install at any other store had a plugin reading another
    install's manifest and writing runtime state there. Unset-only: a value
    already there is the home's own choice of store -- a bot profile's
    dispatch store is exactly that (#1679) -- and is never replaced. Doctor
    reports a value that names a different store.

    The written text is read back through the plugin's own scan before it is
    returned, so a file this editor misreads is left alone rather than handed
    to Hermes with a setting the plugin would not find.
    """
    value = _normalize(omh_home)
    try:
        found, _current = runtime_paths.omh_home_setting(config_text)
    except runtime_paths.RuntimeBindingError as exc:
        return ConfigChange(False, f"{exc}; plugins.entries.omh.settings.omh_home left unset", config_text)
    if found:
        return ConfigChange(False, "plugins.entries.omh already names an omh_home; leaving it alone", config_text)
    leaf = f"'{value}'"
    lines = config_text.splitlines()
    guard = section_edit_guard(lines, "plugins", "entries")
    if not guard and ("'" in value or _contains_potential_quoted_mapping_key(f"omh_home: {leaf}")):
        guard = "the OMH home path cannot be written as one plain YAML string"
    if guard:
        return ConfigChange(False, f"{guard}; plugins.entries.omh.settings.omh_home left unset", config_text)
    edited = _insert_block_leaf(lines, PLUGIN_OMH_HOME_KEY_PATH, leaf)
    if edited is None:
        return ConfigChange(
            False, "plugins.entries is in a shape this editor does not extend; omh_home left unset", config_text
        )
    text = _joined(edited)
    if plugin_omh_home_setting(text) != value:
        return ConfigChange(
            False, "the plugin would not read the written omh_home back; leaving the config alone", config_text
        )
    return ConfigChange(True, "recorded plugins.entries.omh.settings.omh_home", text)


def _block_children_end(lines: list[str], start: int, stop: int, parent_indent: int) -> int:
    """The first line at or before `parent_indent` in `[start, stop)`, else `stop`."""
    for index in range(start, stop):
        line = lines[index]
        body = line.strip()
        if body and not body.startswith("#") and len(line) - len(line.lstrip(" ")) <= parent_indent:
            return index
    return stop


def _block_key_at_level(
    lines: list[str], start: int, stop: int, parent_indent: int, key: str
) -> tuple[int | None, int | None, int] | None:
    """`(key index, sibling indent, level end)` for one level, or None for a shape not walked.

    The plugin's `_scan_block_setting` rule: children are the lines deeper
    than the parent, the first one fixes the sibling indent, and the last
    duplicate wins. A tab indent or a merge key at the level is refused.
    """
    child_indent: int | None = None
    found_at: int | None = None
    end = _block_children_end(lines, start, stop, parent_indent)
    for index in range(start, end):
        line = lines[index]
        body = line.strip()
        if not body or body.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if "\t" in line[: indent + 1]:
            return None
        if child_indent is None:
            child_indent = indent
        if indent != child_indent:
            continue
        name, separator, _rest = body.partition(":")
        if name.strip() == "<<":
            return None
        if separator and name.strip() == key:
            found_at = index
    return found_at, child_indent, end


def _insert_block_leaf(lines: list[str], key_path: tuple[str, ...], leaf: str) -> list[str] | None:
    """Insert the missing tail of a block-mapping key path, or None for any other shape.

    Adds only the keys that are absent, at the sibling indent already in use
    (two spaces deeper when the level is empty). An existing key on the path
    that carries an inline value (`entries: {}`, `omh: ~`) is somebody's
    shape, not an absent key, and so is a leaf that is already there.
    """
    start, stop, parent_indent = 0, len(lines), -1
    for depth, key in enumerate(key_path):
        level = _block_key_at_level(lines, start, stop, parent_indent, key)
        if level is None:
            return None
        found_at, child_indent, stop = level
        if found_at is None:
            indent = child_indent if child_indent is not None else parent_indent + 2 if parent_indent >= 0 else 0
            tail = key_path[depth:]
            added = [
                f"{' ' * (indent + 2 * offset)}{name}:{f' {leaf}' if offset == len(tail) - 1 else ''}"
                for offset, name in enumerate(tail)
            ]
            position = stop
            while position > start and not lines[position - 1].strip():
                position -= 1
            if depth == 0:
                # A new top-level section, separated the way the other
                # `ensure_*` writers append theirs.
                return [*lines[:position], *([""] if position else []), *added, *lines[position:]]
            return [*lines[:position], *added, *lines[position:]]
        rest = lines[found_at].partition(":")[2].strip()
        if depth == len(key_path) - 1 or (rest and not rest.startswith("#")):
            return None
        start, parent_indent = found_at + 1, int(child_indent or 0)
    return None


def _block_key_chain(lines: list[str], key_path: tuple[str, ...]) -> list[int] | None:
    """The line index of each key on a block-mapping path, or None when one is absent."""
    chain: list[int] = []
    start, stop, parent_indent = 0, len(lines), -1
    for key in key_path:
        level = _block_key_at_level(lines, start, stop, parent_indent, key)
        if level is None or level[0] is None:
            return None
        found_at, child_indent, stop = level
        chain.append(found_at)
        start, parent_indent = found_at + 1, int(child_indent or 0)
    return chain


def remove_plugin_omh_home(config_text: str, expected: str) -> ConfigChange:
    """Take back the `omh_home` `ensure_plugin_omh_home` wrote, if it still says `expected`.

    With it go the `settings:` and `omh:` keys the removal leaves with no
    children: an empty mapping there is a null Hermes reads as no entry at
    all, and leaving it would make the uninstalled file differ from the one
    before setup. `plugins.entries` is a depth-two container and goes through
    the recorded-container cleanup every other managed section does.
    """
    if plugin_omh_home_setting(config_text) != expected:
        return ConfigChange(False, "plugins.entries.omh.settings.omh_home is not the value OMH wrote", config_text)
    lines = config_text.splitlines()
    guard = section_edit_guard(lines, "plugins", "entries")
    if guard:
        return ConfigChange(False, guard, config_text)
    chain = _block_key_chain(lines, PLUGIN_OMH_HOME_KEY_PATH)
    if chain is None:
        return ConfigChange(False, "plugins.entries.omh.settings.omh_home line not found", config_text)
    del lines[chain[-1]]
    # `settings`, then `omh`; never `entries` or `plugins`.
    for index in reversed(chain[2:-1]):
        if _has_child_lines(lines, index):
            break
        del lines[index]
    return ConfigChange(True, "removed plugins.entries.omh.settings.omh_home", _joined(lines))


def memory_provider_selection(config_text: str) -> str:
    """The name in `memory.provider`, or "" when Hermes is on its built-in memory."""
    return _section_scalar(config_text, "memory", "provider")


def display_skin_selection(config_text: str) -> str:
    """The name in `display.skin`, or "" when Hermes resolves its built-in default.

    The active skin is what colours the OMH widget's panel border, so doctor
    names it when reporting the chrome. `ensure_omh_skin` is the one writer,
    and only for the unset case.
    """
    return _section_scalar(config_text, "display", "skin")


def references_mapping_key(line: str, key: str) -> bool:
    """Whether `line` uses `key` as a mapping key, quoted, dotted or explicit.

    Public because the uninstall report asks a different question from the
    writers: they ask "may I edit here", this asks "is the key there at all".
    """
    return _references_mapping_key(line, key)


def _references_mapping_key(line: str, key: str) -> bool:
    escaped = re.escape(key)
    token = rf"""(?:{escaped}|"{escaped}"|'{escaped}')"""
    return (
        re.search(rf"(?:^|[{{,])\s*{token}\s*:", line) is not None
        or re.match(rf"^\s*\?\s*{token}\s*$", line) is not None
    )


def _contains_potential_quoted_mapping_key(line: str) -> bool:
    return (
        re.match(r"""^\s*(?:\?\s*)?["']""", line) is not None
        or re.search(r"""(?:^|[,{])\s*["']""", line) is not None
    )


def _contains_unsupported_yaml_node_syntax(line: str) -> bool:
    return (
        re.match(r"^\s*\?", line) is not None
        or re.match(r"^\s*[&*!]", line) is not None
        or re.search(r"(?:^|[,{])\s*[&*!]", line) is not None
        or re.search(r":\s*[&*!]", line) is not None
    )


def _section_node_is_sequence(lines: list[str], section: str) -> bool:
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not line.startswith(" ") and stripped.startswith("-"):
            return True
    section_indices = [index for index, line in enumerate(lines) if line == f"{section}:"]
    if len(section_indices) != 1:
        return False
    for line in lines[section_indices[0] + 1 :]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not line.startswith(" "):
            break
        return stripped.startswith("-")
    return False


def _root_is_plain_block_mapping(lines: list[str]) -> bool:
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or line.startswith(" "):
            continue
        if stripped in {"---", "..."} or stripped.startswith("%"):
            return False
        if stripped.startswith(("{", "[", "-")):
            return False
        if re.match(r"^[^:#][^:]*:(?:\s|$)", stripped) is None:
            return False
    return True


def _document_edit_guard(lines: list[str]) -> str:
    """Refusals that hold for every key in every section of the document."""
    if lines and lines[0].startswith("\ufeff"):
        return "BOM-prefixed YAML is user-owned; leaving it alone"
    if not _root_is_plain_block_mapping(lines):
        return "non-mapping or multi-document YAML is user-owned; leaving it alone"
    return ""


def _document_syntax_guard(lines: list[str]) -> str:
    """Node syntax this hand-rolled editor cannot preserve if it rewrites a line."""
    if any(_contains_potential_quoted_mapping_key(line) for line in lines):
        return "quoted YAML mapping keys are user-owned; leaving them alone"
    if any(_contains_unsupported_yaml_node_syntax(line) for line in lines):
        return "YAML node properties are user-owned; leaving them alone"
    return ""


def _section_shape_guard(lines: list[str], section: str) -> str:
    """Refusals about one top-level section's own shape."""
    section_lines = [line for line in lines if _references_mapping_key(line, section)]
    section_indices = [index for index, line in enumerate(lines) if line == f"{section}:"]
    if len(section_lines) > 1:
        return f"duplicate {section} sections are ambiguous; leaving them alone"
    if section_lines and not section_indices:
        return f"noncanonical {section} configuration is user-owned; leaving it alone"
    return ""


def section_edit_guard(lines: list[str], section: str, key: str = "") -> str:
    """The refusal every mutation of `section` (and optionally `section.key`) shares.

    `_display_edit_guard` below is this same sequence pinned to `display`,
    and the two were one list for a reason that only became visible from the
    uninstall side: the display writers refused a shape while the memory and
    plugin writers edited the same file anyway. On a config carrying both a
    dotted `memory.provider: omh` and a `memory:` block, the owner check read
    the dotted value and the mutator then deleted the block's value, so OMH's
    marker survived and the person's provider did not. On a config with
    `enabled: &plist`, the display path refused over the anchor while the
    plugin path emptied the list the anchor names, leaving every `*plist`
    alias resolving to null.

    So this is not defensive tidying. Each clause is a shape where editing
    one key changes the meaning of something the person owns elsewhere.
    """
    guard = _document_edit_guard(lines)
    if guard:
        return guard
    if _section_node_is_sequence(lines, section):
        return f"sequence {section} configuration is user-owned; leaving it alone"
    guard = _document_syntax_guard(lines)
    if guard:
        return guard
    guard = _section_shape_guard(lines, section)
    if guard:
        return guard
    if key and any(_references_mapping_key(line, f"{section}.{key}") for line in lines):
        return f"dotted {section}.{key} is user-owned; leaving it alone"
    return ""


def _display_edit_guard(lines: list[str]) -> str:
    return section_edit_guard(lines, "display")


def _canonical_display_entries(lines: list[str], key: str) -> list[tuple[int, str]]:
    display_indices = [index for index, line in enumerate(lines) if line == "display:"]
    if len(display_indices) != 1:
        return []
    entries: list[tuple[int, str]] = []
    for index in range(display_indices[0] + 1, len(lines)):
        line = lines[index]
        if line.strip() and not line.startswith(" "):
            break
        if line.startswith("  ") and not line.startswith("    "):
            candidate, separator, rest = line.strip().partition(":")
            if separator and candidate == key:
                entries.append((index, rest.strip()))
    return entries


def _activate_display_scalar(config_text: str, key: str, value: str) -> ConfigChange:
    """Set one canonical ``display`` scalar after explicit operator consent."""
    lines = config_text.splitlines()
    guard = _display_edit_guard(lines)
    if guard:
        return ConfigChange(False, guard, config_text)
    dotted = f"display.{key}"
    if any(_references_mapping_key(line, dotted) for line in lines):
        return ConfigChange(False, f"dotted display.{key} is user-owned; leaving it alone", config_text)

    display_indices = [index for index, line in enumerate(lines) if line == "display:"]
    if not display_indices:
        text = (config_text.rstrip() + f"\n\ndisplay:\n  {key}: {value}\n").lstrip("\n")
        return ConfigChange(True, f"appended display.{key}", text)

    display_index = display_indices[0]
    entries: list[tuple[int, str]] = []
    key_like_lines = 0
    for index in range(display_index + 1, len(lines)):
        line = lines[index]
        if line.strip() and not line.startswith(" "):
            break
        if _references_mapping_key(line, key):
            key_like_lines += 1
        if line.startswith("  ") and not line.startswith("    "):
            candidate, separator, rest = line.strip().partition(":")
            if separator and candidate == key:
                entries.append((index, rest.strip()))
    if key_like_lines != len(entries) or len(entries) > 1:
        return ConfigChange(False, f"ambiguous display.{key} is user-owned; leaving it alone", config_text)
    if entries:
        index, raw = entries[0]
        if not _scalar_value(raw) or raw.startswith(("{", "[", "|", ">")):
            return ConfigChange(False, f"non-scalar display.{key} is user-owned; leaving it alone", config_text)
        if _scalar_value(raw) == value:
            return ConfigChange(False, f"display.{key} is already {value}", config_text)
        lines[index] = f"  {key}: {value}"
        return ConfigChange(True, f"set display.{key} to {value}", "\n".join(lines) + "\n")

    lines.insert(display_index + 1, f"  {key}: {value}")
    return ConfigChange(True, f"inserted display.{key}", "\n".join(lines) + "\n")


COLLAPSED_DISPLAY_SECTIONS: tuple[tuple[str, str], ...] = (
    ("thinking", "collapsed"),
    ("tools", "collapsed"),
    ("subagents", "collapsed"),
)


def display_sections_selection(config_text: str) -> dict[str, str]:
    """The canonical `display.sections` scalars, or {} for any other shape.

    Read-only companion to the writer below, and the surface the apply result
    reports so `omh uninstall` (#1725) can later tell what setup wrote from
    what a person chose.
    """
    lines = config_text.splitlines()
    if _display_edit_guard(lines):
        return {}
    located = _canonical_display_sections(lines)
    if located is None or isinstance(located, str):
        return {}
    _index, children = located
    return {key: _scalar_value(raw) for _child_index, key, raw in children if _scalar_value(raw)}


def activate_display_sections(config_text: str) -> ConfigChange:
    """Collapse the three transcript sections after the operator accepts the branded TUI.

    Part of the same consented bundle as `display.interface` and
    `display.skin`, and under the same rules: never on a noncanonical YAML
    shape, never over a value the person set, and only from the default-Yes
    confirmation or `--yes`.

    Narrower than the two scalars in one way that matters. Consent lets those
    two REPLACE a stock canonical value, because the whole point is migrating
    somebody off `cli`. Here every key is unset-only, per key: an existing
    `display.sections.tools: expanded` survives while `thinking` and
    `subagents` are still added. Hermes' own defaults are `expanded`
    (`SECTION_DEFAULTS` in `ui-tui/src/domain/details.ts`), so an explicit
    `expanded` and the default look identical in behavior but not in
    provenance -- one is a choice -- and only the absent key is OMH's to fill.

    `collapsed` is not `hidden`: counts stay visible and a click expands.
    """
    lines = config_text.splitlines()
    guard = _display_edit_guard(lines)
    if guard:
        return ConfigChange(False, guard, config_text)
    if any(_references_mapping_key(line, "display.sections") for line in lines):
        return ConfigChange(False, "dotted display.sections is user-owned; leaving it alone", config_text)

    located = _canonical_display_sections(lines)
    if isinstance(located, str):
        return ConfigChange(False, located, config_text)

    if located is None:
        block = ["  sections:", *(f"    {key}: {value}" for key, value in COLLAPSED_DISPLAY_SECTIONS)]
        display_index = next((index for index, line in enumerate(lines) if line == "display:"), None)
        if display_index is None:
            text = (config_text.rstrip() + "\n\ndisplay:\n" + "\n".join(block) + "\n").lstrip("\n")
            return ConfigChange(True, "appended display.sections", text)
        lines[display_index + 1 : display_index + 1] = block
        return ConfigChange(True, "inserted display.sections", "\n".join(lines) + "\n")

    sections_index, children = located
    present = {key for _child_index, key, _raw in children}
    missing = [(key, value) for key, value in COLLAPSED_DISPLAY_SECTIONS if key not in present]
    if not missing:
        # Not "already collapsed": every key being present says nothing about
        # its value, and on a config where all three read `expanded` the old
        # wording claimed the opposite of what is on disk.
        return ConfigChange(
            False,
            "display.sections already sets "
            + ", ".join(key for key, _value in COLLAPSED_DISPLAY_SECTIONS)
            + "; leaving those values to the user",
            config_text,
        )
    # After the `sections:` line, not after the last child: the children of a
    # block mapping are unordered, and inserting at the head cannot land past
    # a trailing comment that belongs to the key above it.
    lines[sections_index + 1 : sections_index + 1] = [f"    {key}: {value}" for key, value in missing]
    kept = sorted(present & {key for key, _value in COLLAPSED_DISPLAY_SECTIONS})
    detail = f"; kept user value(s) for {', '.join(kept)}" if kept else ""
    return ConfigChange(
        True,
        f"set display.sections.{', display.sections.'.join(key for key, _value in missing)}{detail}",
        "\n".join(lines) + "\n",
    )


def _canonical_display_sections(
    lines: list[str],
) -> tuple[int, list[tuple[int, str, str]]] | str | None:
    """Locate `display.sections` as a block mapping.

    Returns the `sections:` line index plus its (index, key, raw value)
    children, `None` when the key is simply absent, or a refusal message when
    the shape is anything this hand-rolled editor must not edit. The refusal
    is a string rather than an exception because every caller reports it as a
    `ConfigChange` that changed nothing.
    """
    display_indices = [index for index, line in enumerate(lines) if line == "display:"]
    if not display_indices:
        return None
    if len(display_indices) > 1:
        return "duplicate display sections are ambiguous; leaving them alone"
    display_index = display_indices[0]

    end = len(lines)
    for index in range(display_index + 1, len(lines)):
        if lines[index].strip() and not lines[index].startswith(" "):
            end = index
            break

    entries: list[tuple[int, str]] = []
    sections_like = 0
    for index in range(display_index + 1, end):
        line = lines[index]
        if _references_mapping_key(line, "sections"):
            sections_like += 1
        if line.startswith("  ") and not line.startswith("    "):
            candidate, separator, rest = line.strip().partition(":")
            if separator and candidate == "sections":
                entries.append((index, rest.strip()))
    if sections_like != len(entries):
        return "noncanonical display.sections is user-owned; leaving it alone"
    if len(entries) > 1:
        return "duplicate display.sections keys are ambiguous; leaving them alone"
    if not entries:
        return None

    sections_index, raw = entries[0]
    if raw and not raw.startswith("#"):
        # A flow mapping, a scalar, a block scalar: all shapes this editor
        # cannot extend a key into without rewriting the person's value.
        return "non-block display.sections is user-owned; leaving it alone"

    children: list[tuple[int, str, str]] = []
    for index in range(sections_index + 1, end):
        line = lines[index]
        if not line.strip():
            continue
        if not line.startswith("    "):
            # Back out to a sibling of `sections`; its children end here.
            break
        if line.startswith("     "):
            return "deeper display.sections nesting is user-owned; leaving it alone"
        candidate, separator, rest = line.strip().partition(":")
        if not separator:
            continue
        children.append((index, candidate, rest.strip()))
    keys = [key for _index, key, _raw in children]
    if len(keys) != len(set(keys)):
        return "duplicate display.sections keys are ambiguous; leaving them alone"
    return (sections_index, children)


def activate_omh_skin(config_text: str, name: str = SKIN_NAME) -> ConfigChange:
    """Select one managed OMH skin after the operator accepts it.

    Forcing on purpose: this is the consent path. The setup/update prompt and
    `omh theme use <name>` are both explicit choices, so they may replace an
    existing canonical value; `ensure_omh_skin` is the narrow unset-only writer.
    """
    return _activate_display_scalar(config_text, "skin", name)


def ensure_omh_skin(config_text: str, name: str = SKIN_NAME) -> ConfigChange:
    """Default `display.skin` to the managed OMH skin when no skin is chosen.

    This is the owner-directed identity default: installing OMH is opting into
    the OH-MY-HERMES look, the way installing oh-my-zsh restyles the shell it
    wraps. It is deliberately narrower than the retired `display.interface`
    write that #986 removed — that write moved users off Hermes' default
    terminal and cost them chrome; this one selects a palette on the terminal
    they already use, only when `display.skin` is unset, and `hermes skin use
    <anything>` immediately and permanently overrides it because an explicit
    value is never rewritten.

    An already-selected OMH theme (`omh theme use amber` and friends) is left
    alone for the same reason a foreign skin is: it is an explicit choice. The
    two cases differ only in the message, because "leaving user preference
    unchanged" reads as a foreign skin and would hide a working OMH theme.
    """
    lines = config_text.splitlines()
    guard = _display_edit_guard(lines)
    if guard:
        return ConfigChange(False, guard, config_text)
    skin_entries = _canonical_display_entries(lines, "skin")
    if len(skin_entries) > 1:
        return ConfigChange(False, "duplicate display.skin keys are ambiguous; leaving them alone", config_text)
    if skin_entries and (
        not _scalar_value(skin_entries[0][1])
        or skin_entries[0][1].startswith(("{", "[", "|", ">"))
    ):
        return ConfigChange(False, "non-scalar display.skin is user-owned; leaving it alone", config_text)
    selected = display_skin_selection(config_text)
    if selected == name:
        return ConfigChange(False, f"display.skin is already {name}", config_text)
    if selected and is_omh_skin_name(selected):
        return ConfigChange(False, f"display.skin is the chosen OMH theme {selected}; leaving it unchanged", config_text)
    if selected:
        return ConfigChange(False, f"display.skin is {selected}; leaving user preference unchanged", config_text)

    if any(line.startswith("display.skin:") for line in lines):
        return ConfigChange(False, "dotted display.skin is user-owned; leaving it alone", config_text)
    display_indices = [index for index, line in enumerate(lines) if line == "display:"]
    if len(display_indices) > 1:
        return ConfigChange(False, "duplicate display sections are ambiguous; leaving them alone", config_text)
    if not display_indices:
        text = (config_text.rstrip() + f"\n\ndisplay:\n  skin: {name}\n").lstrip("\n")
        return ConfigChange(True, "appended display.skin", text)
    lines.insert(display_indices[0] + 1, f"  skin: {name}")
    return ConfigChange(True, f"set display.skin to {name}", "\n".join(lines) + "\n")


def model_scalar_selection(config_text: str, key: str) -> str:
    """The scalar `model.<key>` (`default`, `provider`, `base_url`), or "".

    Read-only: OMH writes `model.aliases.*` through Hermes' own `config set`
    and never touches these keys. `maintenance.hermes_model_routing` reads them
    to report when they disagree.
    """
    return _section_scalar(config_text, "model", key)


def display_interface_selection(config_text: str) -> str:
    """The unambiguous scalar `display.interface`, or "" for other shapes."""
    lines = config_text.splitlines()
    display_indices = [index for index, line in enumerate(lines) if line == "display:"]
    if len(display_indices) != 1:
        return ""
    entries: list[str] = []
    for line in lines[display_indices[0] + 1 :]:
        if line.strip() and not line.startswith(" "):
            break
        if line.startswith("  ") and not line.startswith("    "):
            key, separator, rest = line.strip().partition(":")
            if separator and key == "interface":
                entries.append(rest.strip())
        elif re.match(r"^interface\s*:", line.lstrip()):
            return ""
    if len(entries) != 1 or not entries[0] or entries[0].startswith(("{", "[", "|", ">")):
        return ""
    return _scalar_value(entries[0])


def activate_tui_interface(config_text: str) -> ConfigChange:
    """Select Hermes' modern TUI after the operator accepts the prompt."""
    return _activate_display_scalar(config_text, "interface", "tui")


def ensure_tui_interface(config_text: str) -> ConfigChange:
    """Default `display.interface` to tui whenever the user has not chosen one.

    Existing installs matter as much as fresh ones: OMH's HUD widgets render
    only in Hermes' official Ink TUI, so an upgrading user whose config predates
    this key would otherwise keep landing in the classic REPL where the HUD
    cannot exist. Every explicit or noncanonical display choice below stays
    user-owned; only the genuinely unset case is defaulted.
    """
    lines = config_text.splitlines()
    guard = _display_edit_guard(lines)
    if guard:
        return ConfigChange(False, guard, config_text)
    display_lines = [
        line
        for line in lines
        if re.match(r"^\s*display\s*:", line)
    ]
    if any(line.startswith("display.interface:") for line in lines):
        return ConfigChange(False, "dotted display.interface is user-owned; leaving it alone", config_text)
    if len(display_lines) > 1:
        return ConfigChange(False, "duplicate display sections are ambiguous; leaving them alone", config_text)
    if display_lines and display_lines[0] != "display:":
        return ConfigChange(False, "inline display configuration is user-owned; leaving it alone", config_text)

    display_index = next(
        (index for index, line in enumerate(lines) if line.strip() == "display:" and not line.startswith(" ")),
        None,
    )
    interface_entries: list[tuple[int, str]] = []
    interface_like_lines = 0
    if display_index is not None:
        for index in range(display_index + 1, len(lines)):
            line = lines[index]
            if line.strip() and not line.startswith(" "):
                break
            if line.startswith("  ") and not line.startswith("    "):
                key, separator, rest = line.strip().partition(":")
                if separator and key.strip() == "interface":
                    interface_entries.append((index, rest.strip()))
            if re.match(r"^interface\s*:", line.lstrip()):
                interface_like_lines += 1
    if interface_like_lines != len(interface_entries):
        return ConfigChange(False, "noncanonical display.interface is user-owned; leaving it alone", config_text)
    if len(interface_entries) > 1:
        return ConfigChange(False, "duplicate display.interface keys are ambiguous; leaving them alone", config_text)
    if interface_entries and (
        not _scalar_value(interface_entries[0][1])
        or interface_entries[0][1].startswith(("{", "[", "|", ">"))
    ):
        return ConfigChange(False, "non-scalar display.interface is user-owned; leaving it alone", config_text)
    selected = display_interface_selection(config_text)
    if selected == "tui":
        return ConfigChange(False, "display.interface is already tui", config_text)
    if selected:
        return ConfigChange(False, f"display.interface is {selected}; leaving user preference unchanged", config_text)

    if display_index is None:
        text = (config_text.rstrip() + "\n\ndisplay:\n  interface: tui\n").lstrip("\n")
        return ConfigChange(True, "appended display.interface", text)

    if interface_entries:
        lines[interface_entries[0][0]] = "  interface: tui"
        return ConfigChange(True, "set display.interface to tui", "\n".join(lines) + "\n")

    lines.insert(display_index + 1, "  interface: tui")
    return ConfigChange(True, "inserted display.interface", "\n".join(lines) + "\n")


def maybe_set_memory_provider(config_text: str, name: str, mode: str) -> ConfigChange:
    """Alias of `set_memory_provider` that honors the CLI's memory_mode.

    mode='off' releases the slot only when OMH owns it. An empty or foreign
    provider remains byte-preserved. Other modes preserve today's claim
    semantics via `set_memory_provider`.
    """
    if mode == "off":
        return clear_memory_provider(config_text, name)
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


def remove_memory_provider(config_text: str, name: str) -> ConfigChange:
    """Drop the `memory.provider` line, but only when `name` still holds the slot.

    Not the same act as `clear_memory_provider`, which writes an empty value.
    That is what `omh memory --disable` means: the person keeps a config
    that says "no external provider, and I chose that". Uninstall means the
    key OMH inserted is gone again, so the line goes rather than emptying.
    """
    lines = config_text.splitlines()
    guard = section_edit_guard(lines, "memory", "provider")
    if guard:
        return ConfigChange(False, guard, config_text)
    current = memory_provider_selection(config_text)
    if not current:
        return ConfigChange(False, "memory.provider is already unset", config_text)
    if current != name:
        return ConfigChange(False, f"memory.provider is {current}, not {name}; leaving it alone", config_text)

    for idx, line in enumerate(lines):
        if not line.startswith("  ") or line.startswith("    "):
            continue
        key, _, _rest = line.strip().partition(":")
        if key.strip() == "provider" and _enclosing_section(lines, idx) == "memory":
            del lines[idx]
            return ConfigChange(True, "removed memory.provider", _joined(lines))
    return ConfigChange(False, "memory.provider line not found", config_text)


def remove_plugin_enabled(config_text: str, name: str) -> ConfigChange:
    """Take `name` back out of `plugins.enabled`; the inverse of `ensure_plugin_enabled`.

    Only that one item, and only from `enabled`. A name under
    `plugins.disabled` is the person's own opt-out, which setup never wrote
    and uninstall must not clean up.
    """
    lines = config_text.splitlines()
    guard = section_edit_guard(lines, "plugins", "enabled")
    if guard:
        return ConfigChange(False, guard, config_text)
    listed = plugin_enablement(config_text)
    if name not in listed["enabled"]:
        return ConfigChange(False, f"{name} is not in plugins.enabled", config_text)
    plugins_index = next(
        (idx for idx, line in enumerate(lines) if line.strip() == "plugins:" and not line.startswith(" ")),
        None,
    )
    if plugins_index is None:
        return ConfigChange(False, "plugins section not found", config_text)

    output: list[str] = lines[: plugins_index + 1]
    changed = False
    current = ""
    index = plugins_index + 1
    while index < len(lines):
        line = lines[index]
        if line.strip() and not line.startswith(" "):
            break
        stripped = line.strip()
        # Item shape before key shape, for the reason `plugin_enablement`
        # documents: a level item (`  - omh`) is a member of the key above
        # it, not a new key.
        if stripped.startswith("- "):
            if current == "enabled" and stripped[2:].strip().strip("\"'") == name:
                changed = True
                index += 1
                continue
            output.append(line)
            index += 1
            continue
        if stripped and line.startswith("  ") and not line.startswith("    "):
            key, _, rest = stripped.partition(":")
            key = key.strip()
            shape, inline = _plugins_list_shape(rest)
            if key in {"enabled", "disabled"} and shape == "inline":
                if key == "enabled" and name in inline and _quoted_inline_items(rest.strip()):
                    # `_parse_inline_list` splits on commas before it strips
                    # quotes, so `["a,b", omh]` parses as three entries and
                    # re-renders as two. Rewriting the line would either drop
                    # the person's quoting or split one entry in half, and
                    # both are edits to a value OMH never wrote.
                    return ConfigChange(
                        False,
                        "quoted inline plugins.enabled is user-owned; leaving it alone",
                        config_text,
                    )
                if key == "enabled" and name in inline:
                    remaining = [value for value in inline if value != name]
                    comment = _split_trailing_comment(rest.strip())[1]
                    output.append(f"  enabled: [{', '.join(remaining)}]{comment}")
                    changed = True
                else:
                    output.append(line)
                current = ""
                index += 1
                continue
            current = key if key in {"enabled", "disabled"} and shape == "block" else ""
        output.append(line)
        index += 1
    output.extend(lines[index:])
    if not changed:
        return ConfigChange(False, f"{name} is not in plugins.enabled", config_text)
    return ConfigChange(True, f"removed {name} from plugins.enabled", _joined(output))


def _locate_display_scalar(lines: list[str], key: str) -> tuple[int, str] | str | None:
    """Locate one canonical `display.<key>` scalar for a mutation.

    Returns its (index, raw value), `None` when the key is absent, or a
    refusal message for every shape this hand-rolled editor must not touch.
    The refusal is a string because each caller reports it as a
    `ConfigChange` that changed nothing, exactly as
    `_canonical_display_sections` does one level down.
    """
    guard = _display_edit_guard(lines)
    if guard:
        return guard
    if any(_references_mapping_key(line, f"display.{key}") for line in lines):
        return f"dotted display.{key} is user-owned; leaving it alone"
    display_indices = [index for index, line in enumerate(lines) if line == "display:"]
    if not display_indices:
        return None
    display_index = display_indices[0]
    entries: list[tuple[int, str]] = []
    key_like_lines = 0
    for index in range(display_index + 1, len(lines)):
        line = lines[index]
        if line.strip() and not line.startswith(" "):
            break
        if _references_mapping_key(line, key):
            key_like_lines += 1
        if line.startswith("  ") and not line.startswith("    "):
            candidate, separator, rest = line.strip().partition(":")
            if separator and candidate == key:
                entries.append((index, rest.strip()))
    if key_like_lines != len(entries) or len(entries) > 1:
        return f"ambiguous display.{key} is user-owned; leaving it alone"
    if not entries:
        return None
    index, raw = entries[0]
    if not _scalar_value(raw) or raw.startswith(("{", "[", "|", ">")):
        return f"non-scalar display.{key} is user-owned; leaving it alone"
    return (index, raw)


def revert_display_scalar(config_text: str, key: str, expected: str, previous: str = "") -> ConfigChange:
    """Put one canonical `display.<key>` back, but only while it reads `expected`.

    The uninstall half of `_activate_display_scalar`, and under the same
    guards: a shape that writer would have refused is a shape this one
    refuses too, so the pair can never leave a config the editor no longer
    understands.

    `previous` is the value the person had before consent let OMH migrate
    them off it. Removing the line in that case would be the wrong inverse:
    somebody on `display.interface: cli` who accepted the branded TUI is
    owed `cli` back, not Hermes' default for an unset key. Absent `previous`
    the key was OMH's insertion and the line goes.
    """
    lines = config_text.splitlines()
    located = _locate_display_scalar(lines, key)
    if isinstance(located, str):
        return ConfigChange(False, located, config_text)
    if located is None:
        return ConfigChange(False, f"display.{key} is not set", config_text)
    index, raw = located
    current = _scalar_value(raw)
    if current != expected:
        return ConfigChange(False, f"display.{key} is {current}, not {expected}; leaving it alone", config_text)
    if previous:
        lines[index] = f"  {key}: {previous}"
        return ConfigChange(True, f"restored display.{key} to {previous}", _joined(lines))
    del lines[index]
    return ConfigChange(True, f"removed display.{key}", _joined(lines))


def remove_display_sections(config_text: str, keys: list[str], expected: str) -> ConfigChange:
    """Drop the named `display.sections` children that still read `expected`.

    Per key, like the writer: a child the person has since changed stays, and
    the caller reports it by name. Deciding which keys to pass is the
    caller's job -- `display_sections_selection` is the reading both sides
    use -- so this only refuses shapes and removes lines.
    """
    lines = config_text.splitlines()
    guard = _display_edit_guard(lines)
    if guard:
        return ConfigChange(False, guard, config_text)
    if any(_references_mapping_key(line, "display.sections") for line in lines):
        return ConfigChange(False, "dotted display.sections is user-owned; leaving it alone", config_text)
    located = _canonical_display_sections(lines)
    if isinstance(located, str):
        return ConfigChange(False, located, config_text)
    if located is None:
        return ConfigChange(False, "display.sections is not set", config_text)
    _sections_index, children = located
    wanted = set(keys)
    removals = [
        index
        for index, key, raw in children
        if key in wanted and _scalar_value(raw) == expected
    ]
    if not removals:
        return ConfigChange(False, "no display.sections child to remove", config_text)
    for index in sorted(removals, reverse=True):
        del lines[index]
    removed = sorted(key for index, key, _raw in children if index in set(removals))
    return ConfigChange(True, f"removed display.sections.{', display.sections.'.join(removed)}", _joined(lines))


def config_container_paths(config_text: str) -> set[str]:
    """Top- and second-level mapping keys that carry no inline value.

    The set uninstall compares before and after setup's own writes, so it can
    drop a `display:` or `skills:` that OMH created and nothing else. Depth
    two is where every key OMH writes lives, so it is where this stops.
    """
    paths: set[str] = set()
    section = ""
    for line in config_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not line.startswith(" "):
            key, separator, rest = stripped.partition(":")
            section = ""
            if separator and not rest.strip() and key.strip():
                section = key.strip()
                paths.add(section)
            continue
        if section and line.startswith("  ") and not line.startswith("    "):
            key, separator, rest = stripped.partition(":")
            key = key.strip()
            if separator and not rest.strip() and key and not key.startswith("-"):
                paths.add(f"{section}.{key}")
    return paths


def _container_line_index(lines: list[str], path: str) -> int | None:
    parts = path.split(".")
    if len(parts) == 1:
        for index, line in enumerate(lines):
            if not line.startswith(" ") and line.strip() == f"{parts[0]}:":
                return index
        return None
    section, key = parts
    in_section = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not line.startswith(" ") and stripped:
            in_section = stripped == f"{section}:"
            continue
        if in_section and line.startswith("  ") and not line.startswith("    ") and stripped == f"{key}:":
            return index
    return None


def childless_containers(config_text: str) -> set[str]:
    """The container keys that carry no child lines right now.

    Compared before and after a reversal so uninstall can tell a container
    its own removals emptied from one the person already kept empty.
    """
    lines = config_text.splitlines()
    empty: set[str] = set()
    for path in config_container_paths(config_text):
        index = _container_line_index(lines, path)
        if index is not None and not _has_child_lines(lines, index):
            empty.add(path)
    return empty


def _has_child_lines(lines: list[str], index: int) -> bool:
    indent = len(lines[index]) - len(lines[index].lstrip(" "))
    for line in lines[index + 1 :]:
        stripped = line.strip()
        if not stripped:
            continue
        if len(line) - len(line.lstrip(" ")) > indent:
            return True
        return False
    return False


def remove_childless_containers(config_text: str, paths: list[str]) -> ConfigChange:
    """Drop each listed container key that reversal left with no children.

    Deepest first, so removing `skills.external_dirs` can leave `skills:`
    childless and both go in one pass. A blank line directly above a removed
    key goes with it when the line above that is not blank: that separator is
    the one `ensure_*` wrote when it appended the section, and leaving it
    behind is the difference between a config that matches the bytes before
    the install and one that does not.
    """
    lines = config_text.splitlines()
    removed: list[str] = []
    for path in sorted(paths, key=lambda value: (-value.count("."), value)):
        index = _container_line_index(lines, path)
        if index is None or _has_child_lines(lines, index):
            continue
        del lines[index]
        if index > 0 and not lines[index - 1].strip() and (index == 1 or lines[index - 2].strip()):
            del lines[index - 1]
        removed.append(path)
    if not removed:
        return ConfigChange(False, "no empty managed section to remove", config_text)
    return ConfigChange(True, f"removed empty {', '.join(sorted(removed))}", _joined(lines))


def _joined(lines: list[str]) -> str:
    """Render edited lines back to config text, never inventing a lone newline."""
    if not any(line.strip() for line in lines):
        return ""
    return "\n".join(lines).rstrip("\n") + "\n"


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


def external_dir_registered(dirs: list[str], skill_dir: str | Path) -> bool:
    """Whether one registered entry names `skill_dir`, by text or by real path.

    The installer registers the managed pack under the `current` pointer so the
    entry survives generation switches, while a running command resolves its
    own generation directory. Comparing the two as strings reported every
    staged-update install as unregistered; the directories are the same one.
    """
    wanted_text = _normalize(skill_dir)
    if wanted_text in dirs:
        return True
    try:
        wanted_real = os.path.realpath(os.path.expanduser(str(skill_dir)))
    except OSError:
        return False
    for entry in dirs:
        try:
            if os.path.realpath(os.path.expanduser(entry)) == wanted_real:
                return True
        except OSError:
            continue
    return False


def ensure_external_dir(config_text: str, skill_dir: str | Path) -> ConfigChange:
    _validate_external_dirs_mutation_shape(config_text)
    target = _normalize(skill_dir)
    if target in external_dirs(config_text):
        return ConfigChange(False, "external dir already present", config_text)

    lines = config_text.splitlines()
    for idx, line in enumerate(lines):
        dotted = _classify_dotted_external_dirs(line)
        if dotted.matched:
            if not dotted.supported:
                raise ValueError(_UNSUPPORTED_EXTERNAL_DIRS_SHAPE)
            values = [*dotted.values, target]
            lines[idx] = f"skills.external_dirs: [{', '.join(values)}]"
            return ConfigChange(True, "expanded dotted skills.external_dirs", "\n".join(lines) + "\n")
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
    """Remove the entry spelled exactly as `skill_dir` normalizes, the way registration wrote it."""
    target = _normalize(skill_dir)
    return _remove_external_dir_items(config_text, lambda value: value == target)


def remove_external_dir_entries(config_text: str, entries: Iterable[str]) -> ConfigChange:
    """Remove the entries whose text the file spells exactly as one of `entries`.

    The caller has already decided which entries name the directory it means
    -- by real path, as `external_dir_registered` reads -- so this removes by
    the entry's own text and never re-normalizes it: an entry spelled through
    `~`, with a trailing slash or through a symlink is removed as written.
    """
    wanted = set(entries)
    if not wanted:
        return ConfigChange(False, "external dir absent", config_text)
    return _remove_external_dir_items(config_text, lambda value: value in wanted)


def _remove_external_dir_items(config_text: str, should_remove: Callable[[str], bool]) -> ConfigChange:
    _validate_external_dirs_mutation_shape(config_text)
    lines = config_text.splitlines()
    for idx, line in enumerate(lines):
        dotted = _classify_dotted_external_dirs(line)
        if dotted.matched:
            if not dotted.supported:
                raise ValueError(_UNSUPPORTED_EXTERNAL_DIRS_SHAPE)
            removed = [value for value in dotted.values if should_remove(value)]
            if not removed:
                return ConfigChange(False, "external dir absent", config_text)
            remaining = [value for value in dotted.values if not should_remove(value)]
            lines[idx] = f"skills.external_dirs: [{', '.join(remaining)}]"
            return ConfigChange(True, "removed external dir", "\n".join(lines).rstrip() + "\n")
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
                if should_remove(value):
                    changed = True
                    continue
                output.append(line)
                continue
        if in_skills and line.startswith("  ") and not line.startswith("    "):
            inline = _classify_inline_external_dirs(line)
            if inline.matched:
                if not inline.supported:
                    raise ValueError(_UNSUPPORTED_EXTERNAL_DIRS_SHAPE)
                values = [value for value in inline.values if not should_remove(value)]
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
    """Replace `config.yaml` with no lock and no compare; `update_config` instead.

    Kept only for tests that build a fixture config from nothing, where
    there is no other writer to race. Every writer in `src/` goes through
    `update_config`, and `tests/test_config_write_discipline.py` re-derives
    that from source and fails on a new bare call (#1742).
    """
    atomic_write_text(path, text)


class ConfigWriteRefused(OmhError):
    """`update_config` declined to write, for a reason its subclass names.

    An `OmhError` so every CLI surface already reports it the same way -- a
    one-line `omh: ...` and exit 2. A refusal is a real outcome here, not an
    internal fault: the alternative is writing over something OMH must not.
    Callers that care about "did the write happen" catch this; callers that
    care why catch one of the two below.
    """


class ConfigConcurrentUpdate(ConfigWriteRefused):
    """Another writer replaced `config.yaml` between this writer's read and its write."""


class ConfigMutationFailed(ConfigWriteRefused):
    """The caller's mutation timed out while deciding what to write.

    Narrow on purpose. Every other exception a mutation raises already
    propagated before `update_config` existed and its callers already map
    it -- `ensure_external_dir` raises `ValueError` on a shape it refuses,
    and `omh setup` turns that into an `OmhError`. `TimeoutError` is the one
    that changed: the lock handler used to swallow it and report a lock
    timeout that had not happened, and narrowing that handler to the
    acquisition left it escaping as a traceback instead of one line. It is
    neither, now: the write is refused and the message says the mutation,
    not the lock.
    """


class ConfigUnwritable(ConfigWriteRefused):
    """The config could not be read, or is a shape OMH refuses to replace.

    Separate from `ConfigConcurrentUpdate` because it names a different
    cause: an unreadable file and a symlinked config both used to raise the
    concurrency class, so a traceback or a log line reported a race that had
    not happened. The person saw the right message either way; the record
    did not.
    """


@dataclass(frozen=True)
class ConfigUpdate:
    """What one `update_config` call decided and did."""

    changed: bool
    written: bool
    message: str
    text: str
    attempts: int
    lock_enforced: bool


def update_config(
    path: Path,
    mutate: Callable[[str], ConfigChange],
    *,
    omh_home: str | Path | None = None,
    dry_run: bool = False,
    attempts: int = 3,
    sleep: Callable[[float], None] = time.sleep,
) -> ConfigUpdate:
    """Read, mutate and replace one Hermes `config.yaml` under one discipline.

    OMH used to write this file from two families that did not know about
    each other. The delegation route writer read, compared a file signature
    and replaced atomically; `write_config` rewrote the whole file with no
    lock and no compare, from `omh setup`, `omh theme`, `omh memory`,
    self-update and `system/targets`. One of those could read the file, have
    a route land, and write back its stale copy -- erasing the route, after
    which the restore record saw a value it had not written and dropped the
    person's baseline as a foreign edit (#1742).

    `mutate` receives the text just read and returns the text to write. It
    runs again on every retry, and that is what makes retrying safe: the
    second attempt derives its change from the OTHER writer's file, so
    neither update is lost. Keep it pure with respect to the config; it may
    be called more than once.

    Two mechanisms, and they are not redundant:

    * The signature compare is the contract. It holds for every writer,
      including one in a process that never heard of the lock.
    * The lock is taken when `omh_home` names an existing OMH home AND this
      is not a dry run, and it is the SAME lock the route writer holds
      (`route_write_lock`), so the two families serialize rather than
      merely detecting each other. It turns a retry that would have
      happened into one that never has to.

    Symlinks are refused before any of this, which is also what keeps the
    compare's two sides describing one file: the read stamps the opened
    descriptor and the guard stamps the path without following it, and
    those agree for every shape except a link. Aligning them the other way
    -- following the link on both sides -- would weaken the guard, because
    a file swapped for a symlink between the read and the replace would
    stop being detected.

    What the compare cannot do, stated because it decides how a caller has
    to be written: it guards the window between the text handed to `mutate`
    and the replace, and nothing earlier. A mutation that ignores that text
    and returns bytes derived from some earlier read writes a stale copy no
    signature can detect, because the file has not moved since this writer
    read it. `tests/test_config_write_discipline.py` fails a mutation that
    never names its argument; the rest is a review question.

    A file that keeps moving for `attempts` rounds raises
    `ConfigConcurrentUpdate` rather than writing, and so does a lock this
    command could not take in time. A config that cannot be read, or that is
    a symlink, raises `ConfigUnwritable`. A mutation that times out raises
    `ConfigMutationFailed`. All three are `ConfigWriteRefused` and all three
    are `OmhError`, so every CLI surface reports them as one line and exit
    2. Refusing is the honest end: the alternative is the lost update this
    exists to prevent. Any OTHER exception from the mutation belongs to the
    caller and propagates unchanged, as it did before this function existed.
    """
    from ..plugin_bundle.omh.delegation_route_restore import route_write_lock
    from ..plugin_bundle.omh.delegation_routing import config_file_signature, read_config_snapshot

    def _attempt() -> ConfigUpdate | None:
        if path.is_symlink():
            # Before the read, on every round, and not left to the reader.
            # `read_config_snapshot` refuses a symlink by opening with
            # `O_NOFOLLOW` and catching the `OSError`, and `os.O_NOFOLLOW`
            # does not exist on Windows -- `getattr(os, "O_NOFOLLOW", 0)`
            # makes the flag a no-op there, so the open follows the link
            # and succeeds. The refusal then never fires, and the two sides
            # of the compare stop describing the same file: the read
            # signature comes from `fstat` on the followed descriptor (the
            # target) and the guard's from `lstat` on the path (the link),
            # which differ in inode and size. Every round mismatched, and a
            # symlinked config failed with "kept changing" after three
            # attempts instead of being refused as the symlink it is.
            #
            # Only the final component. The temp file is created in
            # `path.parent` and renamed within it, so a symlinked parent
            # directory cannot produce the link-destruction this prevents,
            # and people do symlink dotfile directories. `O_NOFOLLOW`
            # guards only the final component too, so both writer families
            # refuse the same thing.
            raise ConfigUnwritable("config.yaml is a symlink; refusing to rewrite it")
        text, signature, error = read_config_snapshot(path)
        if error:
            raise ConfigUnwritable(error)
        try:
            change = mutate(text)
        except TimeoutError as exc:
            raise ConfigMutationFailed(f"the config mutation timed out: {exc}") from exc
        if not change.changed or dry_run:
            return ConfigUpdate(change.changed, False, change.message, change.text, 1, False)
        if not atomic_replace_text(
            path, change.text, guard=lambda: config_file_signature(path) == signature
        ):
            return None
        return ConfigUpdate(True, True, change.message, change.text, 1, False)

    rounds = max(attempts, 1)

    def _loop() -> ConfigUpdate:
        for attempt in range(1, rounds + 1):
            result = _attempt()
            if result is not None:
                return ConfigUpdate(
                    result.changed, result.written, result.message, result.text, attempt, False
                )
            if attempt < rounds:
                # Jittered, and short. Without the lock -- no OMH home yet,
                # or `system/targets` writing a home this invocation is not
                # bound to -- three immediate rounds burn out in microseconds
                # against a writer that would have finished a millisecond
                # later, and the refusal then means "I was fast", not "the
                # file kept moving". Jitter rather than a fixed delay for the
                # reason `_with_windows_retry` records: writers that collided
                # once re-collide in lockstep on a deterministic wait.
                # `sleep` is a seam so a test can hold this: timing cannot
                # be asserted without flakiness, and a comment explaining
                # the jitter survives a refactor that deletes the sleep.
                sleep(0.005 * attempt * (0.5 + random.random()))
        raise ConfigConcurrentUpdate(
            f"config.yaml kept changing during {rounds} update "
            f"{'attempt' if rounds == 1 else 'attempts'}: {path}"
        )

    home = Path(omh_home).expanduser() if omh_home else None
    if dry_run or home is None or not home.is_dir():
        # A dry run writes nothing, so it has nothing to serialize against.
        # Taking the lock anyway made a read-only command create
        # `routing/` and a lock file inside it, force that directory to
        # 0700, and acquire a five-second wait and a way to exit non-zero --
        # none of which "the same --dry-run semantics" allows. It reads
        # without the lock and reports a snapshot, which is what a preview
        # is.
        #
        # No OMH home is the other case: no home to key the shared lock on
        # means no plugin is bound to one either, so there is no route
        # writer on the other side of it. The signature compare stands on
        # its own in both.
        return _loop()
    with ExitStack() as stack:
        try:
            # Only the acquisition is inside this `try`. `FileLockTimeout`
            # in this repo is a `TimeoutError`, so wrapping `_loop()` too
            # would report any future mutation that touches a locked store
            # as a lock timeout here.
            mechanism = stack.enter_context(route_write_lock(home))
        except TimeoutError as exc:
            raise ConfigConcurrentUpdate(
                f"timed out waiting for the OMH config lock: {exc}"
            ) from exc
        result = _loop()
    return ConfigUpdate(
        result.changed,
        result.written,
        result.message,
        result.text,
        result.attempts,
        mechanism != "none",
    )
