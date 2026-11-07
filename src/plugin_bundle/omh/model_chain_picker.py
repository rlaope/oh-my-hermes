"""The editing model behind the chain picker, shared by its two surfaces.

Bare `omh model-chains` on a terminal and `/omh-model` in the OMH TUI walk
the same rows: one per shipped mixture category, each showing the chain
in effect, whether it is a shipped default or an override, and whether a
provider this machine holds -- linked to Hermes, or recorded by `omh setup`
-- serves its head. Left and right step the head
model through the known aliases, minus and plus step the head's reasoning
effort along that model's ladder, and a save composes the override document
exactly the way `omh model-chains set` composes it. The ladder is a contract's,
or a `model-efforts.json` entry's, or the shared steps marked as not known for
that model. This module holds every one of those rules so neither surface
carries chain logic of its own; it renders nothing and reads no keys.

It lives in the plugin bundle, so it may depend only on siblings in this
package (`tests/test_plugin_bundle_standalone.py`). Display labels and
purpose phrases live in the repo's catalog module, which the bundle cannot
see; `picker_rows` takes them as optional mappings and falls back to the raw
alias — the name routing actually uses — so a surface without the catalog
still shows the truth, just less prettily.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import json
import os
from pathlib import Path
import secrets
from typing import Any

from . import runtime_paths
from .awareness_delivery import _with_windows_retry
from .hermes_delegation import (
    HERMES_MIXTURE_CATEGORY_CHAINS,
    MIXTURE_CHAIN_OVERRIDES_SCHEMA_VERSION,
    _CHAIN_TOKEN_RE,
    _strict_json_loads,
    alias_is_served,
    effective_provider_entitlements,
    load_mixture_chain_overrides,
    load_model_provider_routes,
    mixture_chain_overrides_path,
    parse_mixture_chain_overrides,
    provider_entitlements_path,
)
from .tools.delegate_route_tool import _always_thinking_claude

Chain = tuple[tuple[str, str], ...]

PICKER_SCHEMA_VERSION = "model_chain_picker/v2"

# The shared steps of a model with no contract and no user entry. Shipped chains
# only ever declare these four, and none of them asks a route to turn thinking
# off, so stepping a model OMH knows nothing about cannot walk into a refusal.
PICKER_EFFORT_RING: tuple[str, ...] = ("low", "medium", "high", "xhigh")

# Every rung a ladder may name, weakest first, and how `off` in the canonical
# `REASONING_EFFORT_LADDER` in `omh.coding.model_routing` is spelled at the
# Hermes boundary; `tests/test_model_chain_picker.py` pins parity. `off` and
# `auto` stay readable in stored chains but are not rungs: both survive until a
# deliberate press moves the row.
EFFORT_VOCABULARY: tuple[str, ...] = ("none", "minimal", "low", "medium", "high", "xhigh", "max")

# `model-efforts.json` sits beside `model-chains.json` rather than inside it,
# because that document's strict schema would make an older OMH drop every
# chain override over one unknown key. A model's entry replaces its ladder and
# an empty list turns the effort keys off. The file is user metadata, not proof
# that a provider accepts a rung.
MODEL_EFFORT_OPTIONS_SCHEMA_VERSION = "model_effort_options/v1"


class PickerChanges(dict[str, Chain]):
    """Edited chains plus the categories whose heads took a -/+ press.

    Chain equality cannot recover that: a tail deduplicated by a model switch
    or an effort stepped away and back reads the same as no press at all.
    """

    def __init__(self, changes: Mapping[str, Chain], *, effort_edits: frozenset[str] = frozenset()) -> None:
        super().__init__(changes)
        self.effort_edits = effort_edits


def model_effort_options_path(omh_home: str | Path) -> Path:
    return Path(omh_home).expanduser() / "routing" / "model-efforts.json"


def load_model_effort_options(omh_home: str | Path) -> tuple[dict[str, tuple[str, ...]], str]:
    """Read the user's model-effort document.

    Returns ``(overrides, status)`` where status is ``absent``, ``applied``,
    or ``invalid: <reason>``, matching `load_mixture_chain_overrides`. An
    invalid document is ignored whole rather than half-applied, and the picker
    paints its status.
    """
    path = model_effort_options_path(omh_home)
    try:
        raw = _strict_json_loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, "absent"
    except (OSError, UnicodeDecodeError, ValueError, RecursionError):
        return {}, "invalid: unreadable JSON"
    return parse_model_effort_options(raw)


def parse_model_effort_options(
    raw: object,
) -> tuple[dict[str, tuple[str, ...]], str]:
    """Validate one already-parsed effort document (strict, atomic)."""
    if not isinstance(raw, dict):
        return {}, "invalid: document must be a JSON object"
    if raw.get("schema_version") != MODEL_EFFORT_OPTIONS_SCHEMA_VERSION:
        return {}, f"invalid: schema_version must be {MODEL_EFFORT_OPTIONS_SCHEMA_VERSION}"
    unknown = sorted(set(raw) - {"schema_version", "models"})
    if unknown:
        return {}, f"invalid: unsupported fields {unknown}"
    models = raw.get("models")
    if not isinstance(models, dict):
        return {}, "invalid: models must be an object"
    overrides: dict[str, tuple[str, ...]] = {}
    for name, entry in models.items():
        if not _CHAIN_TOKEN_RE.fullmatch(name):
            return {}, f"invalid: model {name!r} is not a plain model token"
        key = name.casefold()
        if key in overrides:
            return {}, f"invalid: model {name!r} repeats another spelling of the same id"
        if not isinstance(entry, dict):
            return {}, f"invalid: model {name!r} must be an object"
        entry_unknown = sorted(set(entry) - {"efforts"})
        if entry_unknown:
            return {}, f"invalid: model {name!r} fields {entry_unknown}"
        efforts = entry.get("efforts")
        if not isinstance(efforts, list):
            return {}, f"invalid: model {name!r} efforts must be a list"
        for effort in efforts:
            if effort == "off":
                return {}, f"invalid: model {name!r} effort 'off' is not selectable; write 'none'"
            if effort not in EFFORT_VOCABULARY:
                return {}, f"invalid: model {name!r} effort {effort!r} is not one of " + ", ".join(EFFORT_VOCABULARY)
            if efforts.count(effort) > 1:
                return {}, f"invalid: model {name!r} repeats effort {effort!r}"
        # Vocabulary order whatever the file's order, so stepping is the same
        # for the same set.
        overrides[key] = tuple(rung for rung in EFFORT_VOCABULARY if rung in efforts)
    return overrides, "applied"


def chain_text(chain: Chain) -> str:
    """`model[:effort], ...` — the form `omh model-chains set` accepts back."""
    return ", ".join(model + (f":{effort}" if effort else "") for model, effort in chain)


def chain_entries(chain: Chain) -> list[dict[str, str]]:
    return [{"model": model, "reasoning_effort": effort} for model, effort in chain]


def known_model_aliases(overrides: Mapping[str, Chain] | None = None) -> tuple[str, ...]:
    """Every alias a chain names today, alphabetical: each member of a shipped
    chain plus each member of the user's overrides.

    Deliberately not the price table. That table also carries superseded
    generations and recognition-only aliases, and a ring is an offer: a model
    it steps to reads as one OMH recommends. Anything a person wants beyond
    what a chain already names is one `omh model-chains set` away, and once
    written it joins the ring here.
    """
    aliases = {model for chain in HERMES_MIXTURE_CATEGORY_CHAINS.values() for model, _ in chain}
    for chain in (overrides or {}).values():
        aliases.update(model for model, _ in chain)
    return tuple(sorted(aliases))


def model_ring(
    aliases: tuple[str, ...],
    entitlements: Mapping[str, Any] | None,
    routes: Mapping[str, tuple[str, str]] | None,
) -> tuple[dict[str, Any], ...]:
    """The aliases left/right step through: served first, alphabetical within.

    Unserved aliases stay in the ring rather than vanishing — the picker marks
    them, and a person may want one anyway (an entitlement recorded before a
    provider was added) — but they sit behind every served one so the common
    walk never crosses a model this machine cannot reach.
    """
    rows = [
        {
            "alias": alias,
            "served": alias_is_served(alias, entitlements, routes) if entitlements is not None else True,
        }
        for alias in aliases
    ]
    return tuple(sorted(rows, key=lambda row: (not row["served"], row["alias"])))


def read_override_document(omh_home: str | Path | None) -> dict[str, Any]:
    """The override document as written, or an empty one for anything else.

    An unreadable or invalid file yields the empty document on purpose: the
    writer then replaces it with a valid one instead of preserving a shape the
    reader would keep ignoring.
    """
    path = mixture_chain_overrides_path(omh_home)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeDecodeError, ValueError):
        raw = None
    if isinstance(raw, dict) and isinstance(raw.get("categories"), dict):
        return raw
    return {"schema_version": MIXTURE_CHAIN_OVERRIDES_SCHEMA_VERSION, "categories": {}}


def picker_rows(
    omh_home: str | Path | None,
    *,
    hermes_home: str | Path | None = None,
    labels: Mapping[str, str] | None = None,
    purposes: Mapping[str, str] | None = None,
    contract_option: Callable[[str], Mapping[str, Any] | None] | None = None,
) -> dict[str, Any]:
    """Everything a picker surface renders, read once.

    Rows carry the chain as stored — the override or the shipped default —
    not the entitlement-reordered projection `omh model-chains show` prints,
    because the picker edits what will be written, and a save of the shaped
    order would silently freeze a reordering that was meant to follow the
    machine's providers. `providers` lists the providers counted for the
    served marks, each with where it was found, so the surface can show why
    a model is marked instead of only that it is.

    `contract_option` answers a model id with its contract ladder; the contract
    table is outside this bundle, so the main package injects it. A model it
    does not know and the user's file does not name keeps the shared steps,
    with `efforts_configured` false so the surface can say the ladder is not
    known. An empty `efforts` list is the user's explicit "no effort keys".
    """
    labels = labels or {}
    purposes = purposes or {}
    omh_home = _bound_store(omh_home, hermes_home)
    overrides, status = load_mixture_chain_overrides(omh_home)
    entitlements, entitlement_status, providers = effective_provider_entitlements(omh_home, hermes_home)
    routes, _ = load_model_provider_routes(omh_home)
    effort_options, effort_status = effort_option_resolver(omh_home, contract_option)

    def served(alias: str) -> bool:
        return alias_is_served(alias, entitlements, routes) if entitlements is not None else True

    def effort_fields(alias: str) -> dict[str, Any]:
        option = effort_options(alias)
        return {
            "efforts": list(_selectable_efforts(option)),
            "efforts_source": option["source"] if option else "unknown",
            "efforts_configured": option is not None,
            "refuses_none": _always_thinking_claude(alias),
        }

    categories = []
    for name, default_chain in HERMES_MIXTURE_CATEGORY_CHAINS.items():
        chain = overrides.get(name, default_chain)
        categories.append(
            {
                "category": name,
                "purpose": purposes.get(name, ""),
                "chain": [
                    {
                        "model": model,
                        "reasoning_effort": effort,
                        "label": labels.get(model, model),
                        "served": served(model),
                    }
                    for model, effort in chain
                ],
                "default_chain": chain_entries(default_chain),
                "origin": "override" if name in overrides else "default",
            }
        )
    return {
        "schema_version": PICKER_SCHEMA_VERSION,
        "path": str(mixture_chain_overrides_path(omh_home)),
        "document_status": status,
        "entitlements_path": str(provider_entitlements_path(omh_home)),
        "entitlements_status": entitlement_status,
        "effort_document_status": effort_status,
        "providers": [dict(row) for row in providers],
        "categories": categories,
        "models": [
            {
                "alias": row["alias"],
                "label": labels.get(row["alias"], row["alias"]),
                "served": row["served"],
                **effort_fields(row["alias"]),
            }
            for row in model_ring(known_model_aliases(overrides), entitlements, routes)
        ],
    }


def chain_from_entries(entries: list[dict[str, Any]]) -> Chain:
    return tuple((str(entry["model"]), str(entry.get("reasoning_effort", ""))) for entry in entries)


def step_head_model(chain: Chain, aliases: tuple[str, ...], direction: int) -> Chain:
    """Replace the head model with its ring neighbour, keeping its effort.

    The tail is preserved minus any entry now equal to the new head, so a
    chain never names one model twice. A head the ring does not know (a
    custom entry) is one step away from either end of the ring; it cannot be
    stepped back to, which is what `d` and cancel are for.
    """
    if not chain or not aliases:
        return chain
    head_model, head_effort = chain[0]
    if head_model in aliases:
        index = aliases.index(head_model)
        new_head = aliases[(index + direction) % len(aliases)]
    else:
        new_head = aliases[0] if direction > 0 else aliases[-1]
    tail = tuple(entry for entry in chain[1:] if entry[0] != new_head)
    return ((new_head, head_effort),) + tail


def step_effort(chain: Chain, direction: int, allowed: tuple[str, ...]) -> Chain:
    """Step the head's effort along `allowed`, clamped at its ends.

    `allowed` is the head model's ladder, weakest first; an empty one holds. A
    stored value the ladder does not list (an old `off`, a provider mapping
    alias, `max` on the shared steps) lands on the next rung that way: `+` with
    no rung above holds, and `-` with no rung below enters at the lowest. `off`
    reads as `none`. `auto`, unset or anything unrecognized enter at the lowest
    rung above `none` from either direction: a press on a value that says
    nothing must not turn thinking off. Walking down from `low` reaches `none`.
    """
    if not chain or not allowed:
        return chain
    head_model, current = chain[0]
    token = "none" if current == "off" else current
    if token in allowed:
        new = allowed[min(max(allowed.index(token) + direction, 0), len(allowed) - 1)]
    elif token not in EFFORT_VOCABULARY:
        new = next((rung for rung in allowed if rung != "none"), allowed[0])
    else:
        position = EFFORT_VOCABULARY.index(token)
        if direction > 0:
            above = [rung for rung in allowed if EFFORT_VOCABULARY.index(rung) > position]
            if not above:
                return chain
            new = above[0]
        else:
            below = [rung for rung in allowed if EFFORT_VOCABULARY.index(rung) < position]
            new = below[-1] if below else allowed[0]
    return ((head_model, new),) + chain[1:]


def compose_override_document(
    document: Mapping[str, Any],
    changes: Mapping[str, Chain],
) -> dict[str, Any]:
    """A new document with `changes` applied, validated the way the reader
    validates.

    A category set back to its shipped default is removed from the document
    rather than written out, so the shipped default keeps following
    `omh update`; every category `changes` does not name is carried over
    byte-for-byte. Raises ValueError for an unknown category or a document
    the reader would reject.
    """
    categories = dict(document.get("categories") or {})
    for name, chain in changes.items():
        default_chain = HERMES_MIXTURE_CATEGORY_CHAINS.get(name)
        if default_chain is None:
            raise ValueError(f"unknown category {name!r}")
        if chain == default_chain:
            categories.pop(name, None)
        else:
            categories[name] = chain_entries(chain)
    composed = {**document, "schema_version": MIXTURE_CHAIN_OVERRIDES_SCHEMA_VERSION, "categories": categories}
    _, status = parse_mixture_chain_overrides(composed)
    if status.startswith("invalid"):
        raise ValueError(status)
    return composed


def write_override_document(omh_home: str | Path | None, document: Mapping[str, Any]) -> Path:
    """Write a composed document where the reader looks for it.

    Both picker surfaces save through this; `omh model-chains set` and
    `interview` keep the repo-wide atomic writer. This is the bundle's own (the
    todo store's idiom: a fresh temporary beside the target, then a replace that
    retries a transient Windows denial), because a module in the plugin bundle
    may not import `omh.system` (`tests/test_plugin_bundle_standalone.py`).
    Validated once more before the bytes land, so an invalid document is never
    written by either surface.
    """
    _, status = parse_mixture_chain_overrides(document)
    if status.startswith("invalid"):
        raise ValueError(status)
    path = mixture_chain_overrides_path(omh_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}-{secrets.token_hex(8)}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="") as handle:
            handle.write(json.dumps(document, indent=2, sort_keys=True) + "\n")
        _with_windows_retry(lambda: os.replace(temporary, path))
    finally:
        if temporary.exists() and not temporary.is_symlink():
            temporary.unlink()
    return path


def _bound_store(omh_home: str | Path | None, hermes_home: str | Path | None) -> str | Path:
    """A store named by the caller, else the one `hermes_home` resolves to.

    Naming no store means "the store this Hermes home dispatches from": a
    profile's own `plugins.entries.omh.settings.omh_home`, then the
    standalone precedence (#1679). Bound here, once, so every read and the
    write below agree, and so `hermes_home` binds rather than reading as if
    it did while the ambient `HERMES_HOME` decided.
    """
    if omh_home is not None:
        return omh_home
    return runtime_paths.resolve_homes(None, hermes_home)[0]


def effort_option_resolver(
    store: str | Path,
    contract_option: Callable[[str], Mapping[str, Any] | None] | None,
) -> tuple[Callable[[str], Mapping[str, Any] | None], str]:
    """The model -> ladder resolver for one read of the user's file, plus its status.

    The exact wire model a `model-providers.json` route names is checked before
    the alias, a user entry at either key before any contract, and None means
    no one knows this model's ladder. A save builds its own after the picker
    closes, so an edit made while the picker was open is seen before anything
    is written.
    """
    routes, _ = load_model_provider_routes(store)
    overrides, status = load_model_effort_options(store)

    def resolve(alias: str) -> Mapping[str, Any] | None:
        route = routes.get(alias)
        keys = [key.casefold() for key in (route[1] if route else "", alias) if key]
        for key in keys:
            if key in overrides:
                return {"efforts": overrides[key], "source": "user"}
        for key in keys:
            option = contract_option(key) if contract_option is not None else None
            if option is not None:
                return option
        return None

    return resolve, status


def _selectable_efforts(option: Mapping[str, Any] | None) -> tuple[str, ...]:
    return PICKER_EFFORT_RING if option is None else tuple(option["efforts"])


def apply_picker_changes(
    omh_home: str | Path | None,
    changes: PickerChanges,
    *,
    hermes_home: str | Path | None = None,
    contract_option: Callable[[str], Mapping[str, Any] | None],
) -> dict[str, Any]:
    """The save both picker surfaces make, as one call.

    A refusal comes back as `{"error": ...}` rather than a traceback, and the
    surface shows the sentence; nothing is written then. The picker already
    keeps a -/+ edit off the model's ladder from reaching this point, so the
    effort check here only fires for a `model-efforts.json` edited or broken
    while the picker was open: such a file is ignored whole, and checking a new
    effort against the wider built-in ladder would undo what it meant to narrow.
    Untouched rows and model switches are never checked, and still save with a
    broken file, carrying a `warning` for the surface to print.
    """
    try:
        omh_home = _bound_store(omh_home, hermes_home)
    except runtime_paths.RuntimeBindingError as exc:
        return {"error": str(exc)}
    effort_options, status = effort_option_resolver(omh_home, contract_option)
    pending = [chain for name, chain in changes.items() if name in changes.effort_edits]
    warning = ""
    if status.startswith("invalid:"):
        reason = status[len("invalid:"):].strip()
        if pending:
            return {"error": f"model-efforts.json is invalid ({reason}); fix or delete it before changing an effort"}
        warning = f"model-efforts.json ignored: {reason}"
    for chain in pending:
        model, effort = chain[0]
        efforts = _selectable_efforts(effort_options(model))
        if effort not in efforts:
            return {
                "error": (
                    f"effort {effort!r} is not selectable for model {model!r} "
                    f"(its list: {', '.join(efforts) or 'empty'})"
                )
            }
    try:
        document = compose_override_document(read_override_document(omh_home), changes)
        path = write_override_document(omh_home, document)
    except (ValueError, OSError) as exc:
        return {"error": str(exc)}
    result = {
        "schema_version": "model_chain_picker_apply/v1",
        "path": str(path),
        "changed": sorted(changes),
    }
    if warning:
        result["warning"] = warning
    return result
