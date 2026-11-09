"""Which Hermes delegation backend picks a child's route, read-only.

Hermes 0.22.5 added pluggable delegation backends. `delegation.backend` in
config.yaml names the one that routes the next `delegate_task` spawn:

* ``default`` (or unset, or a Hermes before 0.22.5): the child is built from
  `delegation.model` / `provider` / `reasoning_effort`, which is the route
  `omh_delegate_route` writes.
* ``model_map`` (the bundled `advanced-delegation` plugin): each task names
  one of the user's `delegation.backends.model_map.options` in an ``option``
  field, and `delegation.model` / `provider` are ignored.
* ``profile_routes``: each task names one of
  `delegation.backends.profile_routes.profiles` in a ``profile`` field; the
  child runs as that whole Hermes profile, credentials and tools included.

`/delegation <backend>` rewrites `delegation.backend` in config.yaml (the
``--now`` form included), so the file is what the next spawn uses. A backend
OMH does not know is reported as such and never guessed at.

OMH does not register a backend and never writes these keys: under a
non-default backend it hands the matching option name to the parent, and the
backend that Hermes runs decides. This module only reads.

The reader is stdlib-only (the plugin runs without PyYAML) and understands
block-style YAML, which is what Hermes' own config writer emits. Flow
collections, block scalars, anchors, tags, or any line it cannot place make
the backend section ``unreadable``; a caller then names no option rather
than guessing one.
"""

from __future__ import annotations

import ipaddress
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse

from .delegation_routing import _config_path, _read_config_snapshot, read_delegation_settings
from .route_endpoint_guard import BOM

DEFAULT_BACKEND = "default"
MODEL_MAP_BACKEND = "model_map"
PROFILE_ROUTES_BACKEND = "profile_routes"
KNOWN_BACKENDS = (DEFAULT_BACKEND, MODEL_MAP_BACKEND, PROFILE_ROUTES_BACKEND)

# `status` values of `read_backend_mode`.
STATUS_READ = "read"
STATUS_UNREADABLE = "unreadable"

_NAME_LIMIT = 128
_OPTION_FIELDS = ("provider", "model", "reasoning_effort", "base_url", "service_tier")

# Categories whose work is many small or parallel children: an option with a
# fast speed tier (`service_tier` fast/priority/ultrafast, Hermes' `/fast`
# words) is tried first there, and a normal one first everywhere else. Hermes
# refuses a tier the option's model does not offer, and that task then takes
# the next option like any other provider error.
FAST_TIER_CATEGORIES = frozenset({"swarm", "quick", "simple-work"})
_FAST_TIERS = frozenset({"fast", "priority", "ultrafast"})

# Providers Hermes runs on this machine with no base_url of their own
# (`hermes_cli/providers.py`: LM Studio's 127.0.0.1 default, the managed
# llama.cpp server). Any other option is local only through its base_url.
_LOCAL_PROVIDERS = frozenset({"lmstudio", "lm-studio", "lm_studio", "llamacpp", "llama.cpp", "llama-cpp"})
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0"})
_CONTAINER_LOCAL_SUFFIXES = (".docker.internal", ".containers.internal", ".lima.internal", ".local")
_TAILSCALE_CGNAT = ipaddress.IPv4Network("100.64.0.0/10")


class _Unsupported(ValueError):
    """A YAML shape the block reader will not interpret."""


class Quoted(str):
    """A quoted scalar, equal to its text: YAML never reads it as a bool, a number or null."""


class _Flow:
    """A one-line flow collection other than ``[]``/``{}``, kept uninterpreted.

    A key elsewhere in the section (`fallback_providers: [a, b]`) must not
    make the backend's own settings unreadable; one that the backend's
    options or profiles live in does, at the point they are read.
    """

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _Flow)

    def __repr__(self) -> str:
        return "_Flow()"


def _flow_value(value: str) -> Any:
    closing = {"[": "]", "{": "}"}[value[0]]
    body = value
    for position, char in enumerate(value):
        if char == "#" and position and value[position - 1].isspace():
            body = value[:position].rstrip()
            break
    if not body.endswith(closing):
        raise _Unsupported("multi-line flow collection")
    inner = body[1:-1].strip()
    if not inner:
        return [] if closing == "]" else {}
    return _Flow()


def read_backend_mode(hermes_home: str | Path | None = None) -> dict[str, Any]:
    """The delegation backend config.yaml names, with its options or profiles.

    Returns ``{"backend", "status", "default", "options", "profiles"}``:

    * ``backend`` is lowercased and stripped; unset or blank is ``default``.
    * ``status`` is ``read`` or ``unreadable``: the file, or a shape inside
      the `delegation` section, could not be interpreted. ``backend`` then
      still comes from the one-line `delegation.backend` scalar when that
      line is readable, so a caller knows not to write routes; only the
      options and profiles are unknown.
    * ``options`` are model_map options as
      ``{"name", "provider", "model", "reasoning_effort", "base_url"}``
      (absent fields are empty strings; credentials are never copied).
    * ``profiles`` are profile_routes profile names.
    * ``default`` is the backend's own default option or profile name.
    """
    empty: dict[str, Any] = {
        "backend": DEFAULT_BACKEND,
        "status": STATUS_READ,
        "default": "",
        "options": [],
        "profiles": [],
    }
    text, _, error = _read_config_snapshot(_config_path(hermes_home))
    if error:
        return {**empty, "status": STATUS_UNREADABLE}
    try:
        section = delegation_section(text)
    except _Unsupported:
        backend = read_delegation_settings(hermes_home, ("backend",)).get("backend", "")
        return {
            **empty,
            "backend": backend.strip().lower() or DEFAULT_BACKEND,
            "status": STATUS_UNREADABLE,
        }
    return backend_mode_from_section(section)


def backend_mode_from_section(section: Mapping[str, Any] | None) -> dict[str, Any]:
    """`read_backend_mode`'s answer for an already-parsed `delegation` mapping."""
    section = section if isinstance(section, Mapping) else {}
    raw = section.get("backend")
    backend = raw.strip().lower() if isinstance(raw, str) else ""
    backend = backend or DEFAULT_BACKEND
    result: dict[str, Any] = {
        "backend": backend,
        "status": STATUS_READ,
        "default": "",
        "options": [],
        "profiles": [],
    }
    backends = section.get("backends")
    settings = backends.get(backend) if isinstance(backends, Mapping) else None
    if isinstance(backends, _Flow) or isinstance(settings, _Flow):
        return {**result, "status": STATUS_UNREADABLE}
    if not isinstance(settings, Mapping):
        return result
    default = settings.get("default")
    if isinstance(default, str):
        result["default"] = _name(default)
    entries = settings.get("options" if backend == MODEL_MAP_BACKEND else "profiles")
    if isinstance(entries, _Flow) or (
        isinstance(entries, list) and any(isinstance(entry, _Flow) for entry in entries)
    ):
        return {**result, "status": STATUS_UNREADABLE}
    if backend == MODEL_MAP_BACKEND:
        result["options"] = _options(settings.get("options"))
    elif backend == PROFILE_ROUTES_BACKEND:
        result["profiles"] = _profiles(settings.get("profiles"))
    return result


def _name(value: object) -> str:
    if not isinstance(value, str):
        return ""
    name = value.strip()
    return name if 0 < len(name) <= _NAME_LIMIT else ""


def _options(raw: object) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    options: list[dict[str, str]] = []
    seen: set[str] = set()
    for entry in raw:
        if not isinstance(entry, Mapping):
            continue
        name = _name(entry.get("name"))
        if not name or name in seen:
            continue
        seen.add(name)
        option = {"name": name}
        for field in _OPTION_FIELDS:
            value = entry.get(field)
            option[field] = value.strip() if isinstance(value, str) else ""
        options.append(option)
    return options


def _profiles(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    names: list[str] = []
    for entry in raw:
        name = _name(entry.get("name")) if isinstance(entry, Mapping) else _name(entry)
        if name and name not in names:
            names.append(name)
    return names


# ── option matching ──────────────────────────────────────────────────────


def _same_model(left: str, right: str) -> bool:
    a, b = left.strip().casefold(), right.strip().casefold()
    if not a or not b:
        return False
    return a == b or a.rsplit("/", 1)[-1] == b.rsplit("/", 1)[-1]


def is_fast_tier(option: Mapping[str, str]) -> bool:
    """Whether a model_map option asks Hermes for a fast speed tier."""
    return str(option.get("service_tier", "") or "").strip().casefold() in _FAST_TIERS


def options_for(
    options: Sequence[Mapping[str, str]],
    alias: str,
    effort: str,
    *,
    wire_model: str = "",
    provider: str = "",
    prefer_fast: bool = False,
) -> list[str]:
    """Every model_map option that runs this chain entry, the preferred speed tier first.

    An option matches when its model is the entry's alias or wire model
    (provider path ignored), its provider -- when both name one -- agrees,
    and its effort is the entry's or unset. An option with a different
    effort is not the same lane and does not match. Options whose speed tier
    is the preferred one (fast under ``prefer_fast``, normal otherwise) come
    first; within a tier the user's own order holds.
    """
    matched: list[Mapping[str, str]] = []
    for option in options:
        model = option.get("model", "")
        if not (_same_model(model, alias) or (wire_model and _same_model(model, wire_model))):
            continue
        option_provider = option.get("provider", "").strip().casefold()
        if provider and option_provider and option_provider != provider.strip().casefold():
            continue
        option_effort = option.get("reasoning_effort", "").strip().casefold()
        if option_effort and option_effort != effort.strip().casefold():
            continue
        matched.append(option)
    preferred = [option for option in matched if is_fast_tier(option) == prefer_fast]
    rest = [option for option in matched if is_fast_tier(option) != prefer_fast]
    return [str(option.get("name", "")) for option in preferred + rest]


def option_for(
    options: Sequence[Mapping[str, str]],
    alias: str,
    effort: str,
    *,
    wire_model: str = "",
    provider: str = "",
    prefer_fast: bool = False,
) -> str:
    """The user's model_map option that runs this chain entry, or ``""``: the first of `options_for`."""
    names = options_for(options, alias, effort, wire_model=wire_model, provider=provider, prefer_fast=prefer_fast)
    return names[0] if names else ""


def option_chain(
    chain: Sequence[tuple[str, str]],
    options: Sequence[Mapping[str, str]],
    routes: Mapping[str, tuple[str, str]] | None = None,
    *,
    prefer_fast: bool = False,
) -> list[dict[str, str]]:
    """A category chain carried onto the user's options, in chain order.

    Each entry is ``{"option", "alias", "reasoning_effort"}``; chain entries
    no option serves are dropped, and an option already named earlier in the
    chain is not repeated. An entry served by several options (one model at
    two speed tiers) carries each, the preferred tier first, so a refused
    tier falls over to the same model at the other. ``routes`` maps an alias
    to ``(provider, wire model)`` the way `resolve_provider_model` reads it.
    """
    carried: list[dict[str, str]] = []
    named: set[str] = set()
    for alias, effort in chain:
        provider, wire_model = (routes or {}).get(alias, ("", ""))
        for name in options_for(options, alias, effort, wire_model=wire_model, provider=provider,
                                prefer_fast=prefer_fast):
            if name and name not in named:
                named.add(name)
                carried.append({"option": name, "alias": alias, "reasoning_effort": effort})
    return carried


def _local_host(base_url: str) -> bool:
    """Hermes' `is_local_endpoint`: loopback, container DNS, unqualified or `.local` hosts, private and Tailscale IPs."""
    raw = base_url.strip()
    try:
        host = (urlparse(raw if "://" in raw else f"//{raw}").hostname or "").lower().rstrip(".")
    except ValueError:
        return False
    if not host:
        return False
    if host in _LOCAL_HOSTS or host.endswith(_CONTAINER_LOCAL_SUFFIXES) or ("." not in host and ":" not in host):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return bool(address.is_private or address.is_loopback or address.is_link_local
                or (isinstance(address, ipaddress.IPv4Address) and address in _TAILSCALE_CGNAT))


def is_local_option(option: Mapping[str, str]) -> bool:
    """Whether a model_map option runs on this machine or its private network.

    Its ``base_url`` decides when it names one; with none, only a provider
    Hermes itself serves locally counts. A cloud provider never does.
    """
    base_url = str(option.get("base_url", "") or "").strip()
    if base_url:
        return _local_host(base_url)
    return str(option.get("provider", "") or "").strip().casefold() in _LOCAL_PROVIDERS


def category_options(
    mode: Mapping[str, Any],
    chains: Mapping[str, Sequence[tuple[str, str]]],
    routes: Mapping[str, tuple[str, str]] | None = None,
) -> dict[str, list[str]]:
    """Each category's model_map option names in chain order, for `omh_dag`.

    Empty unless the backend is `model_map` and its options were read: no
    other backend takes an option OMH may choose.
    """
    if mode.get("backend") != MODEL_MAP_BACKEND or mode.get("status") != STATUS_READ:
        return {}
    options = list(mode.get("options") or [])
    return {
        str(category): [
            entry["option"]
            for entry in option_chain(chain, options, routes, prefer_fast=category in FAST_TIER_CATEGORIES)
        ]
        for category, chain in chains.items()
    }


def category_local_options(
    mode: Mapping[str, Any],
    chains: Mapping[str, Sequence[tuple[str, str]]],
    routes: Mapping[str, tuple[str, str]] | None = None,
) -> dict[str, list[str]]:
    """Each category's local model_map options, for a dag node marked ``local``.

    Only options `is_local_option` accepts: those the category's chain names
    first, in chain order, then every other local option in the user's
    order (a local model is rarely one a shipped chain names). Empty unless
    the backend is `model_map` and its options were read.
    """
    if mode.get("backend") != MODEL_MAP_BACKEND or mode.get("status") != STATUS_READ:
        return {}
    local = [option for option in mode.get("options") or [] if is_local_option(option)]
    result: dict[str, list[str]] = {}
    for category, chain in chains.items():
        named = [entry["option"] for entry in option_chain(chain, local, routes,
                                                            prefer_fast=category in FAST_TIER_CATEGORIES)]
        result[str(category)] = named + [str(option["name"]) for option in local if option["name"] not in named]
    return result


# ── a block-YAML reader for the `delegation` section ─────────────────────


def delegation_section(text: str) -> dict[str, Any] | None:
    """The top-level `delegation:` mapping of a config, or ``None`` when absent.

    Only that section is interpreted; the rest of the file is skipped by
    indentation, so an unusual shape elsewhere does not make this unreadable.
    """
    lines = text.removeprefix(BOM).splitlines()
    start = None
    for index, line in enumerate(lines):
        if line.startswith(("---", "...")) and index:
            raise _Unsupported("multi-document config")
        if line[:1].isspace() or not line.strip() or line.lstrip().startswith("#"):
            continue
        key, rest = _split_key(line.strip())
        if key == "delegation":
            if _scalar_text(rest):
                raise _Unsupported("delegation is not a mapping")
            start = index + 1  # last occurrence wins, as YAML loaders do
    if start is None:
        return None
    body: list[tuple[int, str]] = []
    for line in lines[start:]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not line[:1].isspace():
            break
        if "\t" in line[: len(line) - len(line.lstrip())]:
            raise _Unsupported("tab indentation")
        body.append((len(line) - len(line.lstrip(" ")), stripped))
    if not body:
        return {}
    value, consumed = _block(body, 0, body[0][0])
    if consumed != len(body) or not isinstance(value, dict):
        raise _Unsupported("unplaced line")
    return value


def _block(rows: list[tuple[int, str]], index: int, indent: int) -> tuple[Any, int]:
    if rows[index][1].startswith("- ") or rows[index][1] == "-":
        return _sequence(rows, index, indent)
    return _mapping(rows, index, indent)


def _mapping(rows: list[tuple[int, str]], index: int, indent: int) -> tuple[dict[str, Any], int]:
    mapping: dict[str, Any] = {}
    while index < len(rows):
        row_indent, content = rows[index]
        if row_indent < indent:
            break
        if row_indent > indent or content.startswith("- ") or content == "-":
            raise _Unsupported("unexpected indentation")
        key, rest = _split_key(content)
        if key is None:
            raise _Unsupported("not a mapping entry")
        index += 1
        if _scalar_text(rest):
            mapping[key] = _scalar(rest)
            continue
        if index < len(rows) and (
            rows[index][0] > indent
            or (rows[index][0] == indent and rows[index][1].startswith("-"))
        ):
            child_indent = rows[index][0]
            mapping[key], index = _block(rows, index, child_indent)
        else:
            mapping[key] = None
    return mapping, index


def _sequence(rows: list[tuple[int, str]], index: int, indent: int) -> tuple[list[Any], int]:
    items: list[Any] = []
    while index < len(rows):
        row_indent, content = rows[index]
        if row_indent < indent or not (content.startswith("- ") or content == "-"):
            if row_indent > indent:
                raise _Unsupported("unexpected indentation")
            break
        if row_indent > indent:
            raise _Unsupported("unexpected indentation")
        rest = content[1:].lstrip(" ")
        item_indent = indent + (len(content) - len(rest))
        index += 1
        if not rest:
            if index < len(rows) and rows[index][0] > indent:
                value, index = _block(rows, index, rows[index][0])
                items.append(value)
            else:
                items.append(None)
            continue
        key, _ = _split_key(rest)
        if key is None:
            items.append(_scalar(rest))
            continue
        # `- key: value` opens a mapping whose further keys sit at item_indent.
        head: list[tuple[int, str]] = [(item_indent, rest)]
        while index < len(rows) and rows[index][0] >= item_indent:
            head.append(rows[index])
            index += 1
        value, consumed = _mapping(head, 0, item_indent)
        if consumed != len(head):
            raise _Unsupported("unplaced line")
        items.append(value)
    return items, index


def _split_key(content: str) -> tuple[str | None, str]:
    if content[:1] in {"'", '"'}:
        quote = content[0]
        end = content.find(quote, 1)
        if end < 0:
            return None, ""
        tail = content[end + 1 :]
        if not tail.startswith(":") or (len(tail) > 1 and not tail[1].isspace()):
            return None, ""
        return content[1:end], tail[1:]
    if content[:1] in {"[", "{", "&", "*", "!", "|", ">", "?"}:
        raise _Unsupported("unsupported node")
    for position, char in enumerate(content):
        if char == ":" and (position + 1 == len(content) or content[position + 1].isspace()):
            key = content[:position].strip()
            return (key or None), content[position + 1 :]
        if char == "#" and position and content[position - 1].isspace():
            break
    return None, ""


def _scalar_text(rest: str) -> str:
    value = rest.strip()
    if value.startswith("#"):
        return ""
    return value


def _scalar(rest: str) -> Any:
    value = rest.strip()
    if value[:1] in {"[", "{"}:
        return _flow_value(value)
    if value[:1] in {"&", "*", "!", "|", ">"}:
        raise _Unsupported("unsupported scalar")
    if value[:1] in {"'", '"'}:
        quote = value[0]
        end = value.find(quote, 1)
        if end < 0:
            raise _Unsupported("unterminated quote")
        trailing = value[end + 1 :].strip()
        if trailing and not trailing.startswith("#"):
            raise _Unsupported("text after quoted scalar")
        inner = value[1:end]
        if quote == '"' and "\\" in inner:
            raise _Unsupported("escaped scalar")
        return Quoted(inner)
    for position, char in enumerate(value):
        if char == "#" and position and value[position - 1].isspace():
            value = value[:position].rstrip()
            break
    if value in {"", "~", "null", "Null", "NULL"}:
        return None
    return value
