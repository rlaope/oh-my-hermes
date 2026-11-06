"""The editing model behind the chain picker, shared by its two surfaces.

Bare `omh model-chains` on a terminal and `/omh-model` in the OMH TUI walk
one row per shipped mixture category, showing whether its chain is shipped
or customized.
Left and right step the head model through the known aliases; minus and plus
step the head's reasoning effort inside that model's resolved selectable
ladder (the caller injects the resolver because the contract table is outside
this bundle), and a save composes the override document exactly the way
`omh model-chains set` composes it while re-checking only the efforts a +/-
edit produced against the live user document. This module holds every one of
those rules so neither surface carries chain logic of its own; it renders
nothing and reads no keys.

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


Chain = tuple[tuple[str, str], ...]


class PickerChanges(dict[str, Chain]):
    """Edited chains plus the categories whose heads were explicitly effort-edited.

    Keep this result intact through save: chain equality cannot recover key
    history after tail deduplication or an effort stepped away and back.
    """

    def __init__(self, changes: Mapping[str, Chain], *, effort_edits: frozenset[str] = frozenset()) -> None:
        super().__init__(changes)
        self.effort_edits = effort_edits.intersection(changes)

PICKER_SCHEMA_VERSION = "model_chain_picker/v2"

# The selectable reasoning vocabulary, weakest first. `none` is the explicit
# no-thinking rung (the Hermes boundary spells it `none`, never `off`);
# `off` is the older OMH spelling and stays readable in stored chains, but it
# is not offered as a new choice and a user override naming it is rejected.
# `auto` means "provider default" and is not an effort level either; both are
# preserved when a row is merely opened, and only a deliberate +/- edit moves
# a row out of them.
EFFORT_VOCABULARY: tuple[str, ...] = ("none", "minimal", "low", "medium", "high", "xhigh", "max")

# User overrides for the *selectable* ladder of a model. This is a sibling of
# `model-chains.json`, not a field inside it: that document's strict schema
# rejects unknown keys, so an older OMH reading a newer chain document would
# drop every override whole. The file is strict and atomic like
# `model-prices.json`: an invalid document is ignored entirely (and reported),
# never half-applied.
#
#   {"schema_version": "model_effort_options/v1",
#    "models": {"claude-haiku-5-5": {"efforts": ["low", "high"]},
#               "my-custom-model": {"efforts": []}}}
#
# A user entry REPLACES the built-in ladder for that model (it can add or
# remove rungs, and a custom model OMH has no contract for can be configured
# this way). An empty list is a deliberate "no adjustable effort" and is not
# the same as an unknown model. `none` is selectable only when a contract
# documents a thinking-disable capability or a user override names it; this
# file is user metadata, not proof that a provider accepts the value.
MODEL_EFFORT_OPTIONS_SCHEMA_VERSION = "model_effort_options/v1"


def model_effort_options_path(omh_home: str | Path | None = None) -> Path:
    root = Path(omh_home).expanduser() if omh_home else runtime_paths.default_omh_home()
    return root / "routing" / "model-efforts.json"


def load_model_effort_options(
    omh_home: str | Path | None = None,
) -> tuple[dict[str, tuple[str, ...]], str]:
    """Read the user's model-effort document.

    Returns ``(overrides, status)`` where status is ``absent``, ``applied``,
    or ``invalid: <reason>``, matching `load_mixture_chain_overrides`. An
    invalid document is ignored entirely rather than half-applied, and the
    picker surfaces its status so a typo cannot silently widen the ladders it
    was meant to narrow.
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
    seen: set[str] = set()
    for name, entry in models.items():
        if not isinstance(name, str) or not _CHAIN_TOKEN_RE.fullmatch(name):
            return {}, f"invalid: model {name!r} is not a plain model token"
        key = name.casefold()
        if key in seen:
            return {}, f"invalid: model {name!r} repeats another spelling of the same id"
        seen.add(key)
        if not isinstance(entry, dict):
            return {}, f"invalid: model {name!r} must be an object"
        entry_unknown = sorted(set(entry) - {"efforts"})
        if entry_unknown:
            return {}, f"invalid: model {name!r} fields {entry_unknown}"
        efforts = entry.get("efforts")
        if not isinstance(efforts, list):
            return {}, f"invalid: model {name!r} efforts must be a list"
        chosen: list[str] = []
        for effort in efforts:
            if not isinstance(effort, str) or not effort.strip():
                return {}, f"invalid: model {name!r} efforts must be non-empty strings"
            token = effort.strip()
            if token.casefold() == "off":
                return {}, (
                    f"invalid: model {name!r} effort 'off' is not selectable; "
                    "write 'none' (Hermes does not recognize 'off')"
                )
            if token != token.casefold() or token not in EFFORT_VOCABULARY:
                return {}, (
                    f"invalid: model {name!r} effort {token!r} is not one of "
                    + ", ".join(EFFORT_VOCABULARY)
                )
            if token in chosen:
                return {}, f"invalid: model {name!r} repeats effort {token!r}"
            chosen.append(token)
        # Canonical order independent of how the file listed them, so the
        # picker always steps the same way for the same set.
        overrides[key] = tuple(rung for rung in EFFORT_VOCABULARY if rung in chosen)
    return overrides, "applied"


def chain_text(chain: Chain) -> str:
    """`model[:effort], ...` — the form `omh model-chains set` accepts back."""
    return ", ".join(model + (f":{effort}" if effort else "") for model, effort in chain)


def chain_entries(chain: Chain) -> list[dict[str, str]]:
    return [{"model": model, "reasoning_effort": effort} for model, effort in chain]


def known_model_aliases(
    overrides: Mapping[str, Chain] | None = None,
) -> tuple[str, ...]:
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
    effort_options: Callable[[str], Mapping[str, Any] | None] | None = None,
    effort_status: str = "",
) -> dict[str, Any]:
    """Everything a picker surface renders, read once.

    Rows carry the chain as stored — the override or the shipped default —
    not the entitlement-reordered projection `omh model-chains show` prints,
    because the picker edits what will be written, and a save of the shaped
    order would silently freeze a reordering that was meant to follow the
    machine's providers. `providers` lists the providers counted for the
    served marks, each with where it was found, so the surface can show why
    a model is marked instead of only that it is.

    `effort_options` is the *caller's* resolver for a model's selectable
    reasoning ladder, and `effort_status` is the user document's status.
    Neither can live here: this module ships inside the standalone plugin
    bundle and may not import the contract table, so the main package
    resolves the source-backed ladder from `model_contracts` (plus the user's
    `model-efforts.json`) and injects the result. A model the resolver does
    not know is `unconfigured` — its stored effort is kept and the surface
    disables +/- rather than guessing a common ladder.
    """
    labels = labels or {}
    purposes = purposes or {}
    omh_home = _bound_store(omh_home, hermes_home)
    overrides, status = load_mixture_chain_overrides(omh_home)
    entitlements, entitlement_status, providers = effective_provider_entitlements(omh_home, hermes_home)
    routes, _ = load_model_provider_routes(omh_home)

    def served(alias: str) -> bool:
        return alias_is_served(alias, entitlements, routes) if entitlements is not None else True

    def effort_fields(alias: str) -> dict[str, Any]:
        option = effort_options(alias) if effort_options is not None else None
        if not isinstance(option, Mapping):
            return {
                "efforts": None,
                "efforts_source": "unknown",
                "efforts_configured": False,
                "effort_model_id": "",
                "effort_provenance": "",
            }
        raw_efforts = option.get("efforts")
        efforts = [str(rung) for rung in raw_efforts] if isinstance(raw_efforts, (list, tuple)) else []
        return {
            "efforts": efforts,
            "efforts_source": str(option.get("source", "") or "user"),
            "efforts_configured": True,
            "effort_model_id": str(option.get("model_id", "") or alias),
            "effort_provenance": str(option.get("provenance", "") or ""),
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
        "effort_path": str(model_effort_options_path(omh_home)),
        "effort_document_status": effort_status,
        "effort_vocabulary": list(EFFORT_VOCABULARY),
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


def step_effort(chain: Chain, direction: int, allowed: tuple[str, ...] | None = None) -> Chain:
    """Step the head's effort inside `allowed`, clamped at its ends.

    `allowed` is the resolved selectable ladder for the head model, weakest
    first. `None` (unconfigured) and the empty tuple (configured with no
    effort knob) both refuse to move: the caller disables +/- there instead
    of guessing a common ladder. A stored value the ladder does not list (an
    old `off`, a provider mapping alias, `auto`) is kept until this explicit
    edit and then lands on the nearest allowed rung: the next one above on
    `+`, the next one below on `-`, clamped at the list's end. `off` is read
    as the `none` rung, so an old spelling normalizes to the Hermes spelling
    when the person steps it.
    """
    if not chain or not allowed:
        return chain
    head_model, current = chain[0]
    positions = {rung: EFFORT_VOCABULARY.index(rung) for rung in allowed if rung in EFFORT_VOCABULARY}
    ordered = tuple(rung for rung in EFFORT_VOCABULARY if rung in positions)
    if not ordered:  # an allowed value outside the vocabulary is a caller bug
        return chain
    token = "none" if current == "off" else current
    if token in positions:
        index = ordered.index(token)
        new = ordered[min(max(index + direction, 0), len(ordered) - 1)]
    else:
        # A stored value outside the ladder still has a vocabulary position
        # when it is a legacy/provider alias (`medium` on DeepSeek), so the
        # step lands on the next allowed rung rather than jumping to the
        # bottom. `auto`, an empty effort, and anything else unrecognized
        # enter at the lowest rung from either direction.
        position = EFFORT_VOCABULARY.index(token) if token in EFFORT_VOCABULARY else None
        if position is None:
            new = ordered[0]
        elif direction > 0:
            new = next((rung for rung in ordered if positions[rung] > position), ordered[-1])
        else:
            new = next((rung for rung in reversed(ordered) if positions[rung] < position), ordered[0])
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

    The `omh model-chains` command keeps the repo-wide atomic writer; this is
    the bundle's own (the todo store's idiom: a fresh temporary beside the
    target, then `os.replace`), because a module in the plugin bundle may not
    import `omh.system` (`tests/test_plugin_bundle_standalone.py`). Validated once
    more before the bytes land, so an invalid document is never written by
    either surface.
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
        os.replace(temporary, path)
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
    omh_home: str | Path | None,
    *,
    contract_option: Callable[[str], Mapping[str, Any] | None],
    hermes_home: str | Path | None = None,
) -> tuple[Callable[[str], dict[str, Any] | None], str]:
    """Build the picker's model -> selectable-effort resolver, plus document status.

    The built-in ladder cannot be derived here (the contract table is outside
    this bundle), so the main package injects ``contract_option`` — a
    callable answering one model id with ``{efforts, source, model_id,
    provenance, thinking_disable}`` or None. This function owns the user
    document and the wire-id-before-alias precedence: the exact wire model
    named by a `model-providers.json` route is checked first, then the alias.
    The caller rebuilds the resolver after the picker closes (the save path)
    so a `model-efforts.json` edit made while the picker was open is seen
    before anything is written.
    """
    store = _bound_store(omh_home, hermes_home)
    routes, _routes_status = load_model_provider_routes(store)
    overrides, status = load_model_effort_options(store)

    def resolve(alias: str) -> dict[str, Any] | None:
        text = str(alias or "").strip()
        if not text:
            return None
        route = routes.get(text)
        wire_model = route[1] if route is not None else ""
        keys: list[str] = []
        for key in (wire_model, text):
            folded = str(key or "").strip().casefold()
            if folded and folded not in keys:
                keys.append(folded)
        for key in keys:
            override = overrides.get(key)
            if override is not None:
                return {
                    "efforts": override,
                    "source": "user",
                    "model_id": key,
                    "provenance": "user_override",
                    "thinking_disable": "none" in override,
                    "override_key": key,
                    "wire_model": wire_model,
                }
        for key in keys:
            option = contract_option(key)
            if isinstance(option, Mapping):
                return {**option, "override_key": "", "wire_model": wire_model}
        return None

    return resolve, status


def picker_store(
    omh_home: str | Path | None, hermes_home: str | Path | None = None
) -> str | Path:
    """The store a picker surface reads and writes, bound once.

    A caller that must also load user documents for the picker (the main
    package's effort resolver, which cannot run inside this bundle) passes
    the result here to that loader, so the picker and the resolver cannot
    disagree about which OMH home they are reading.
    """
    return _bound_store(omh_home, hermes_home)


def _changed_effort_error(
    new_chain: Chain,
    effort_options: Callable[[str], Mapping[str, Any] | None] | None,
) -> str:
    """Check only the explicitly edited head, never untouched tail entries."""
    if effort_options is None:
        return ""
    for model, effort in new_chain[:1]:
        option = effort_options(model)
        if not isinstance(option, Mapping):
            return (
                f"model {model!r} has no configured effort options; add it to "
                "the model-efforts.json document before choosing an effort"
            )
        raw_efforts = option.get("efforts")
        efforts = tuple(str(rung) for rung in raw_efforts) if isinstance(raw_efforts, (list, tuple)) else ()
        if not efforts:
            return f"model {model!r} is configured with no selectable efforts; +/- cannot change it"
        token = effort.strip()
        if token == "off":
            return (
                f"effort 'off' is not selectable for model {model!r}; "
                "choose 'none' (Hermes does not recognize 'off')"
            )
        if token not in efforts:
            return (
                f"effort {token!r} is not selectable for model {model!r} "
                f"(configured: {', '.join(efforts)})"
            )
    return ""


def apply_picker_changes(
    omh_home: str | Path | None,
    raw_changes: object,
    *,
    hermes_home: str | Path | None = None,
    effort_options: Callable[[str], Mapping[str, Any] | None] | None,
    effort_status: str = "",
) -> dict[str, Any]:
    """The save `/omh-model` in the OMH TUI makes, as one call.

    `raw_changes` is the intact `PickerChanges` returned by the picker.
    Plain category mappings remain accepted for model-only changes; effort
    edits must carry `PickerChanges.effort_edits`, never inferred from diffs.
    A refusal comes back as `{"error": ...}` rather than a traceback.

    `effort_options` is the caller's save-time resolver for each model's
    current selectable ladder, and `effort_status` is that same read's
    document status. The caller builds both after the picker closes, so a
    `model-efforts.json` edit made while the picker was open cannot let a
    now-invalid new effort be written; untouched rows and model switches are
    never revalidated. When that document became malformed meanwhile the
    resolver falls back to the built-in ladders, so a new effort is refused
    rather than checked against a list the person's file meant to narrow. A
    save with no effort edit still proceeds (historical values and
    model-only changes stay permitted) and carries the same
    `model-efforts.json ignored` sentence in `warning` for the surface to
    print.
    """
    if not isinstance(raw_changes, Mapping):
        return {"error": "changes must be a JSON object keyed by category"}
    try:
        omh_home = _bound_store(omh_home, hermes_home)
    except runtime_paths.RuntimeBindingError as exc:
        return {"error": str(exc)}
    changes: dict[str, Chain] = {}
    effort_edits = raw_changes.effort_edits if isinstance(raw_changes, PickerChanges) else frozenset()
    for name, entries in raw_changes.items():
        if isinstance(entries, tuple) and all(
            isinstance(entry, tuple) and len(entry) == 2 for entry in entries
        ):
            changes[str(name)] = tuple((str(entry[0]), str(entry[1])) for entry in entries)
            continue
        if not isinstance(entries, (list, tuple)) or not all(
            isinstance(entry, Mapping) and isinstance(entry.get("model"), str) for entry in entries
        ):
            return {"error": f"category {name!r} needs a list of model entries"}
        changes[str(name)] = tuple(
            (str(entry["model"]), str(entry.get("reasoning_effort", "") or "")) for entry in entries
        )
    pending = [chain for name, chain in changes.items() if name in effort_edits]
    # A document that turned malformed while the picker was open is ignored
    # whole by the reader, so the resolver above silently fell back to the
    # built-in ladders. Checking a new effort against that wider fallback is
    # exactly the silent widening R2 forbids, so an effort edit is refused
    # until the file is fixed. Anything else may still save, with the
    # document named in the result.
    warning = ""
    status = str(effort_status or "")
    if status.startswith("invalid:"):
        reason = status[len("invalid:"):].strip() or "unreadable document"
        if pending:
            return {
                "error": (
                    f"model-efforts.json is invalid ({reason}); fix or delete it "
                    "before changing an effort"
                )
            }
        warning = (
            f"model-efforts.json ignored: {reason} · built-in ladders apply; "
            "custom models stay unconfigured"
        )
    for chain in pending:
        error = _changed_effort_error(chain, effort_options)
        if error:
            return {"error": error}
    try:
        path = mixture_chain_overrides_path(omh_home)
        if changes:
            document = compose_override_document(read_override_document(omh_home), changes)
            path = write_override_document(omh_home, document)
    except (ValueError, OSError) as exc:
        return {"error": str(exc)}
    result: dict[str, Any] = {
        "schema_version": "model_chain_picker_apply/v1",
        "path": str(path),
        "changed": sorted(changes),
        "categories_changed": sorted(changes),
    }
    if warning:
        result["warning"] = warning
    return result
