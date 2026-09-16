"""View and edit the per-category mixture model chains.

The chains live as user config in `<omh-home>/routing/model-chains.json`
(`mixture_chain_overrides/v1`): the document replaces only the categories it
names and the shipped defaults keep serving the rest. This command is the
supported editing surface over that file:

* `omh model-chains` (bare, on a terminal) — the arrow-key picker: one row
  per category, left/right steps the head model, -/+ its effort, Enter saves.
  `omh model` is the same command under a shorter name. Off a terminal the
  bare form prints `show`.
* `omh model-chains show` — the current effective chain per category, with
  its origin (shipped default vs override) and the document status.
* `omh model-chains set <category> "model[:effort], model[:effort]"` — write
  one category's replacement chain; `--clear` returns it to the default.
* `omh model-chains interview` — walk every category with numbered choices
  (keep / shipped default / Ultrafast tier / custom entry) on a terminal.
* `omh model-chains provider set <id> <kind>` / `clear <id>` — record what
  one of this machine's providers serves, which is what reorders the chains
  above. The scriptable counterpart of the `omh setup` provider question,
  which a `--yes`, `--json`, or non-TTY install never reaches.

Editing the JSON file directly stays equally supported; every path converges
on the same validated document.
"""

from __future__ import annotations

import argparse
import json
import re
import sys

from ..catalogs.model_chain_table import CHAIN_SURFACE_PURPOSES, MODEL_DISPLAY_LABELS
from ..coding.data_handling_policy import (
    SENSITIVE_WORK_CHAIN_CLAIM_BOUNDARY,
    data_handling_filtered_chain,
)
from ..local_store import atomic_write_text
from ..plugin_bundle.omh.hermes_delegation import (
    APPROX_PRICE_PER_MTOK,
    HERMES_MIXTURE_CATEGORY_CHAINS,
    PROVIDER_FAMILY_VOCABULARY,
    PROVIDER_KIND_VOCABULARY,
    alias_is_served,
    chains_with_overrides,
    entitlement_shaped_chain,
    load_mixture_chain_overrides,
    load_model_provider_routes,
    effective_provider_entitlements,
    mixture_chain_overrides_path,
    model_provider_routes_path,
    is_provider_id_token,
    parse_mixture_chain_overrides,
    provider_entitlements_path,
    provider_family_for,
    routes_to_unknown_providers,
    split_unknown_routes,
    unknown_route_labels,
)
from ..plugin_bundle.omh.model_chain_picker import (
    chain_text,
    compose_override_document,
    picker_rows,
    read_override_document,
)
from ..install.config_adapter import display_skin_selection, read_config
from ..skin_pack import skin_colors, theme_for_skin_name
from .common import _paths
from .model_chain_picker import default_palette, pick_chains_interactively

# From `quickstart`, not `setup`, for the reason `theme` gives: importing the
# parser module back here would close an import cycle.
from .quickstart import _use_color
from .theme_picker import picker_available

_ENTRY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")

# The Ultrafast-tier interview option: a chain member is offered its
# `<model>-ultrafast` speed variant when that token is a known model (shipped
# chains or the price table), so no variant is invented. Editorial offer, not
# a capability claim; the option is offered only when it changes the chain.
_KNOWN_MODEL_TOKENS = frozenset(APPROX_PRICE_PER_MTOK) | {
    model for chain in HERMES_MIXTURE_CATEGORY_CHAINS.values() for model, _ in chain
}
_ULTRAFAST_SWAPS = {
    model: f"{model}-ultrafast"
    for model in _KNOWN_MODEL_TOKENS
    if f"{model}-ultrafast" in _KNOWN_MODEL_TOKENS
}


def _parsechain_text(text: str) -> tuple[tuple[str, str], ...]:
    """Parse `model[:effort], model[:effort]` into chain entries or raise ValueError."""
    entries: list[tuple[str, str]] = []
    for piece in text.split(","):
        piece = piece.strip()
        if not piece:
            continue
        model, _, effort = piece.partition(":")
        model = model.strip()
        effort = effort.strip()
        if not _ENTRY_RE.match(model):
            raise ValueError(f"{model!r} is not a plain model identifier")
        if effort and not _ENTRY_RE.match(effort):
            raise ValueError(f"{effort!r} is not a plain reasoning-effort token")
        entries.append((model, effort))
    if not entries:
        raise ValueError("a chain needs at least one `model[:effort]` entry")
    return tuple(entries)


def _write_document(omh_home, document: dict[str, object]) -> str:
    _, status = parse_mixture_chain_overrides(document)
    if status.startswith("invalid"):
        raise ValueError(status)
    path = mixture_chain_overrides_path(omh_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(document, indent=2, sort_keys=True) + "\n")
    return str(path)


def _state(omh_home, hermes_home=None) -> dict[str, object]:
    overrides, status = load_mixture_chain_overrides(omh_home)
    entitlements, entitlement_status, providers = effective_provider_entitlements(omh_home, hermes_home)
    routes, routes_status = load_model_provider_routes(omh_home)
    chains = chains_with_overrides(overrides)
    categories = []
    for name, chain in chains.items():
        shaped = chain
        if entitlements is not None:
            shaped = entitlement_shaped_chain(chain, entitlements, routes)
        categories.append(
            {
                "category": name,
                "chain": [
                    {
                        "model": model,
                        "reasoning_effort": effort,
                        "served": (
                            alias_is_served(model, entitlements, routes)
                            if entitlements is not None
                            else True
                        ),
                    }
                    for model, effort in shaped
                ],
                "chain_text": chain_text(shaped),
                "origin": "override" if name in overrides else "default",
                "entitlement_shaped": shaped != chain,
            }
        )
    return {
        "schema_version": "model_chain_state/v1",
        "path": str(mixture_chain_overrides_path(omh_home)),
        "document_status": status,
        "entitlements_path": str(provider_entitlements_path(omh_home)),
        "entitlements_status": entitlement_status,
        "providers": [dict(row) for row in providers],
        # Providers whose kind names no model family: `gateway`, `unknown`,
        # or an id nothing on this machine records. The serving rule counts
        # every alias as served for such a provider, so on its own it can
        # only ever leave a chain in the order it already had. Resolved
        # through `provider_family_for` -- the one id -> family lookup this
        # surface has -- so the printed line cannot drift from a second copy
        # of the rule.
        "unplaced_providers": [
            row["id"]
            for row in providers
            if provider_family_for(str(row["id"]), entitlements) not in PROVIDER_FAMILY_VOCABULARY
        ],
        "routes_path": str(model_provider_routes_path(omh_home)),
        "routes_status": routes_status,
        # Routes to a provider neither recorded nor linked, each with its
        # effect: `chain` rows name an alias a chain names (demoted behind
        # every served entry); `dispatch` rows reach no chain and only
        # resolve a pinned dispatch, unchecked.
        "unserved_routes": [dict(row) for row in routes_to_unknown_providers(routes, entitlements, chains)],
        "categories": categories,
    }


def _print_state(state: dict[str, object]) -> None:
    print("Current model chains (category -> effective order):")
    for row in state["categories"]:
        marker = " (override)" if row["origin"] == "override" else ""
        if row.get("entitlement_shaped"):
            marker += " (reordered by this machine's providers)"
        print(f"  {row['category']}: {row['chain_text']}{marker}")
    print(f"Overrides file: {state['path']} [{state['document_status']}]")
    print(f"Provider entitlements: {state['entitlements_path']} [{state['entitlements_status']}]")
    if str(state["entitlements_status"]).startswith("invalid:"):
        # An invalid record yields no document: its kinds are dropped and a
        # linked row it excluded counts again. Said here, not left to the
        # bracketed status.
        print("  providers.json is ignored: its recorded kinds are dropped and any providers it excluded count again")
    linked = [row for row in state.get("providers", []) if row["source"] != "recorded"]
    if linked:
        print("Linked Hermes providers: " + ", ".join(f"{row['id']} ({row['source']})" for row in linked))
        unplaced = set(state.get("unplaced_providers", []))
        reordered = any(row.get("entitlement_shaped") for row in state["categories"])
        # Said only when it is the whole story: every provider this machine
        # holds is one whose kind names no family, and no category came out
        # reordered. A named multi-vendor family (`openrouter`, `opencode`)
        # leaves the chains unshaped too, but correctly -- it does serve
        # every family, and no answer would change that -- so a machine
        # holding one is not told to go and fix something. A route in
        # model-providers.json can shape a chain past a gateway kind, and
        # then the reordering is not doing nothing, so the line stays off.
        #
        # Both ways out are named. A `--yes`, `--json`, or non-TTY setup
        # asks no provider question, so an agent-driven or scripted install
        # -- which overlaps heavily with the machines that land here -- can
        # never take advice that says only `omh setup`.
        if unplaced >= {str(row["id"]) for row in state.get("providers", [])} and not reordered:
            print("  none of these names a model family, so no chain is reordered. Record what one serves with")
            print("  `omh model-chains provider set <id> <kind>`, or answer `omh setup` on a terminal.")
    else:
        print("Linked Hermes providers: none found (a `hermes auth` login, a config provider, or a key name counts)")
    routes_status = str(state.get("routes_status", ""))
    if routes_status.startswith("invalid:"):
        # An absent document is the common case and says nothing; an
        # invalid one silently drops every route, so it is named.
        print(f"Provider routes: {state.get('routes_path', '')} [{routes_status}] (ignored: every alias dispatches unchanged)")
    demoted, dispatch_only = split_unknown_routes(state.get("unserved_routes", []))
    if demoted:
        print(
            "Chain entries routed to a provider neither recorded nor linked: "
            + unknown_route_labels(demoted)
            + " (each sorts behind the served entries of every chain naming it)"
        )
    if dispatch_only:
        print(
            "Dispatch-only routes to a provider neither recorded nor linked: "
            + unknown_route_labels(dispatch_only)
            + " (no chain names these; a dispatch pinning one asks Hermes for a provider it is not linked to)"
        )
    print("Edit a category with `omh model-chains set <category> \"model[:effort], ...\"`,")
    print("walk all of them with `omh model-chains interview`, or edit the JSON directly.")


def _sensitive_state(state: dict[str, object]) -> dict[str, object]:
    """Re-shape the chain state for declared-sensitive work.

    Sensitivity arrives as the caller's `--sensitive` flag and nothing else;
    the gate never reads a message, a path, or a category name to decide it.
    Every category keeps its row even when nothing survives, because a
    category that vanished would read as one with no chain configured.
    """
    categories = state["categories"]
    assert isinstance(categories, list)
    shaped: list[dict[str, object]] = []
    for row in categories:
        chain = row["chain"]
        assert isinstance(chain, list)
        report = data_handling_filtered_chain(
            [str(entry["model"]) for entry in chain],
            work_is_sensitive=True,
        )
        permitted = set(report["chain"])
        kept = [entry for entry in chain if str(entry["model"]) in permitted]
        shaped.append(
            {
                **row,
                "chain": kept,
                "chain_text": chain_text(
                    tuple((str(entry["model"]), str(entry["reasoning_effort"])) for entry in kept)
                ),
                "data_handling": report,
            }
        )
    empty = [str(row["category"]) for row in shaped if not row["chain"]]
    return {
        **state,
        "categories": shaped,
        "work_is_sensitive": True,
        "categories_with_no_permitted_model": empty,
        "claim_boundary": SENSITIVE_WORK_CHAIN_CLAIM_BOUNDARY,
    }


def _print_sensitive_state(state: dict[str, object]) -> None:
    print("Model chains for work declared sensitive (category -> permitted order):")
    categories = state["categories"]
    assert isinstance(categories, list)
    for row in categories:
        report = row["data_handling"]
        assert isinstance(report, dict)
        summary = report["summary"]
        assert isinstance(summary, dict)
        text = row["chain_text"] or "(no model in this chain has a permitting documented policy)"
        print(f"  {row['category']}: {text}")
        for excluded in report["excluded"]:
            print(f"    excluded {excluded['model']}: {excluded['verdict']} ({excluded['reason']})")
    empty = state["categories_with_no_permitted_model"]
    assert isinstance(empty, list)
    if empty:
        print("Categories with nothing left to route sensitive work to: " + ", ".join(empty))
    print(str(state["claim_boundary"]))


def _sensitive_chain_exit_code(state: object) -> int:
    """0 only when every category still has a model declared-sensitive work may use.

    1 when at least one category was emptied. A wrapper reading only the
    status must not start declared-sensitive work against a chain the gate
    emptied, and an empty chain is the concrete finding: there is no
    recoverable lane in which "nothing is permitted" is a normal result. A
    plain `show` never sets the key, so it keeps returning 0.

    Generic failure signals -- a refused or interrupted run, or a unit
    carrying a failure kind -- are never success either, so this mapper
    cannot be passed by ignoring them.
    """
    summary = state if isinstance(state, dict) else {}
    if summary.get("refused") or summary.get("interrupted"):
        return 1
    units = summary.get("units")
    if isinstance(units, list) and any(isinstance(unit, dict) and unit.get("failure_kind") for unit in units):
        return 1
    return 1 if summary.get("categories_with_no_permitted_model") else 0


def cmd_model_chains_show(args: argparse.Namespace) -> int:
    paths = _paths(args)
    state = _state(paths.omh_home, paths.hermes_home)
    sensitive = bool(getattr(args, "sensitive", False))
    if sensitive:
        state = _sensitive_state(state)
    if getattr(args, "json", False):
        print(json.dumps(state, ensure_ascii=True, separators=(",", ":"), sort_keys=True))
    elif sensitive:
        _print_sensitive_state(state)
    else:
        _print_state(state)
    return _sensitive_chain_exit_code(state)


def cmd_model_chains_set(args: argparse.Namespace) -> int:
    paths = _paths(args)
    omh_home = paths.omh_home
    category = str(args.category)
    if category not in HERMES_MIXTURE_CATEGORY_CHAINS:
        print(
            f"omh: unknown category {category!r}; choose one of "
            + ", ".join(HERMES_MIXTURE_CATEGORY_CHAINS),
            file=sys.stderr,
        )
        return 2
    document = read_override_document(omh_home)
    categories = document["categories"]
    assert isinstance(categories, dict)
    if args.clear:
        categories.pop(category, None)
    else:
        if not args.chain:
            print("omh: set needs a chain (`model[:effort], ...`) or --clear", file=sys.stderr)
            return 2
        try:
            entries = _parsechain_text(" ".join(args.chain))
        except ValueError as exc:
            print(f"omh: {exc}", file=sys.stderr)
            return 2
        categories[category] = [
            {"model": model, "reasoning_effort": effort} for model, effort in entries
        ]
    try:
        path = _write_document(omh_home, document)
    except ValueError as exc:
        print(f"omh: refused to write an invalid document: {exc}", file=sys.stderr)
        return 2
    state = _state(omh_home, paths.hermes_home)
    if getattr(args, "json", False):
        print(json.dumps(state, ensure_ascii=True, separators=(",", ":"), sort_keys=True))
    else:
        row = next(r for r in state["categories"] if r["category"] == category)
        print(f"{category}: {row['chain_text']} ({row['origin']})")
        print(f"Written to {path}. New delegations use this order; running children keep theirs.")
    return 0


def _active_palette(paths) -> dict[str, str]:
    """The active OMH skin's colours, so the picker matches the TUI; the
    default skin when `display.skin` is unset or not an OMH theme."""
    theme = theme_for_skin_name(display_skin_selection(read_config(paths.hermes_config_path)))
    return skin_colors(theme.skin_name) if theme else default_palette()


def cmd_model_chains_pick(args: argparse.Namespace) -> int:
    """Bare `omh model-chains` picks interactively; anything else prints `show`.

    The split is the theme command's: `show` is the scriptable surface and
    stays byte-predictable, the bare form is what a person types to SEE the
    chains and move them. `--json` and any non-terminal end degrade the bare
    form to the same listing.
    """
    if getattr(args, "json", False) or not picker_available():
        return cmd_model_chains_show(args)
    paths = _paths(args)
    omh_home = paths.omh_home
    payload = picker_rows(
        omh_home, hermes_home=paths.hermes_home, labels=MODEL_DISPLAY_LABELS, purposes=CHAIN_SURFACE_PURPOSES
    )
    changes = pick_chains_interactively(payload, use_color=_use_color(), palette=_active_palette(paths))
    if changes is None:
        print(f"Cancelled; {payload['path']} was not changed.")
        return 0
    if not changes:
        print("No changes.")
        return 0
    try:
        document = compose_override_document(read_override_document(omh_home), changes)
        path = _write_document(omh_home, document)
    except ValueError as exc:
        print(f"omh: refused to write an invalid document: {exc}", file=sys.stderr)
        return 2
    print(f"Saved {len(changes)} categor{'y' if len(changes) == 1 else 'ies'} to {path}.")
    _print_state(_state(omh_home, paths.hermes_home))
    return 0


def _ultrafast_variant(
    chain: tuple[tuple[str, str], ...],
) -> tuple[tuple[str, str], ...] | None:
    swapped = tuple((_ULTRAFAST_SWAPS.get(model, model), effort) for model, effort in chain)
    return swapped if swapped != chain else None


def _stdin_is_tty() -> bool:
    return sys.stdin.isatty()


def model_chains_interview(paths) -> int:
    """Numbered per-category interview on a terminal.

    Non-interactive callers (agents, pipes) get a refusal that names the
    scriptable path instead of a hanging prompt.

    Takes resolved paths rather than the parsed args so the interactive
    `omh setup` wizard can offer the same walk inline, exactly the way
    `category_maestro_interview` serves the Maestro lane's category dial.
    """
    if not _stdin_is_tty():
        print(
            "omh: interview needs a terminal; use `omh model-chains show` and "
            "`omh model-chains set <category> \"model[:effort], ...\"` instead.",
            file=sys.stderr,
        )
        return 2
    omh_home = paths.omh_home
    overrides, _ = load_mixture_chain_overrides(omh_home)
    document = read_override_document(omh_home)
    categories = document["categories"]
    assert isinstance(categories, dict)
    print("Model chain interview — Enter keeps the current order.")
    changed = 0
    for name, default_chain in HERMES_MIXTURE_CATEGORY_CHAINS.items():
        current = overrides.get(name, default_chain)
        options: list[tuple[str, tuple[tuple[str, str], ...] | None]] = [
            (f"keep current: {chain_text(current)}", current),
        ]
        if current != default_chain:
            options.append((f"shipped default: {chain_text(default_chain)}", default_chain))
        ultrafast = _ultrafast_variant(current)
        if ultrafast is not None:
            options.append((f"Ultrafast tier: {chain_text(ultrafast)}", ultrafast))
        options.append(("custom entry (`model[:effort], ...`)", None))
        print(f"\n[{name}]")
        for index, (label, _chain) in enumerate(options, start=1):
            print(f"  {index}) {label}")
        raw = input(f"choose 1-{len(options)} [1]: ").strip() or "1"
        try:
            pick = int(raw)
        except ValueError:
            pick = 0
        if not 1 <= pick <= len(options):
            print("  unrecognized choice; keeping current")
            continue
        label, selected = options[pick - 1]
        if selected is None:
            custom = input("  chain: ").strip()
            try:
                selected = _parsechain_text(custom)
            except ValueError as exc:
                print(f"  {exc}; keeping current")
                continue
        if selected == current:
            continue
        if selected == default_chain:
            categories.pop(name, None)
        else:
            categories[name] = [
                {"model": model, "reasoning_effort": effort} for model, effort in selected
            ]
        changed += 1
    if not changed:
        print("\nNo changes.")
        return 0
    try:
        path = _write_document(omh_home, document)
    except ValueError as exc:
        print(f"omh: refused to write an invalid document: {exc}", file=sys.stderr)
        return 2
    print(f"\nSaved {changed} categor{'y' if changed == 1 else 'ies'} to {path}.")
    _print_state(_state(omh_home, paths.hermes_home))
    return 0


def cmd_model_chains_interview(args: argparse.Namespace) -> int:
    return model_chains_interview(_paths(args))


def _provider_kind_error(kind: str) -> str:
    return (
        f"omh: unknown provider kind {kind!r}; choose one of "
        + ", ".join(PROVIDER_KIND_VOCABULARY)
    )


def cmd_model_chains_provider_set(args: argparse.Namespace) -> int:
    """Record what one provider serves, without a terminal.

    The scriptable counterpart of the `omh setup` provider question, which a
    `--yes`, `--json`, or non-TTY install never reaches. A kind outside the
    vocabulary is refused by name rather than recorded: an unresolvable kind
    is the exact state the `model-chains show` hint exists to make visible,
    so writing one from a typo would manufacture it.
    """
    paths = _paths(args)
    provider_id = str(args.provider)
    kind = str(args.kind)
    if not is_provider_id_token(provider_id):
        print(f"omh: {provider_id!r} is not a plain provider identifier", file=sys.stderr)
        return 2
    if kind not in PROVIDER_KIND_VOCABULARY:
        print(_provider_kind_error(kind), file=sys.stderr)
        return 2
    return _report_provider_record(args, paths.omh_home, provider_id, kind)


def cmd_model_chains_provider_clear(args: argparse.Namespace) -> int:
    """Remove one provider from the record; detection counts it again afterwards."""
    paths = _paths(args)
    provider_id = str(args.provider)
    if not is_provider_id_token(provider_id):
        print(f"omh: {provider_id!r} is not a plain provider identifier", file=sys.stderr)
        return 2
    return _report_provider_record(args, paths.omh_home, provider_id, None)


def _report_provider_record(args: argparse.Namespace, omh_home, provider_id: str, kind: str | None) -> int:
    from .provider_entitlements import record_provider_kind

    payload = record_provider_kind(omh_home, provider_id, kind)
    if getattr(args, "json", False):
        print(json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True))
    status = str(payload["status"])
    if status == "refused_invalid_document":
        # Never silently discard an operator document a script has not read.
        if not getattr(args, "json", False):
            print(
                f"omh: {payload['path']} is not readable as a provider record "
                f"[{payload['document_status']}]; fix or delete it first",
                file=sys.stderr,
            )
        return 2
    if not getattr(args, "json", False):
        if status == "unchanged":
            print(f"{provider_id} already recorded as expected in {payload['path']}; nothing written")
        elif status == "cleared":
            print(f"Cleared {provider_id} from {payload['path']}; this machine's own providers count it again")
        else:
            print(f"Recorded {provider_id} as {kind} in {payload['path']}; `omh model-chains show` prints the effect")
    return 0


def _add_model_chains_commands(sub) -> None:
    chains = sub.add_parser(
        "model-chains",
        aliases=["model"],
        help="View and edit the per-category mixture model chains (routing, fallback, HUD labels).",
    )
    chains.add_argument("--json", action="store_true", help="Print the machine-readable state payload.")
    chains.set_defaults(func=cmd_model_chains_pick, model_chains_command=None)
    chains_sub = chains.add_subparsers(dest="model_chains_command")

    show = chains_sub.add_parser("show", help="Show the effective chain per category and its origin.")
    show.add_argument("--json", action="store_true", help="Print the machine-readable state payload.")
    show.add_argument(
        "--sensitive",
        action="store_true",
        help=(
            "Declare the work sensitive: drop every model whose contract does not document a "
            "permitting data-handling default, naming each exclusion (a model of unknown policy "
            "is excluded, never silently kept). Exits 1 if a category is left with no model."
        ),
    )
    show.set_defaults(func=cmd_model_chains_show)

    set_cmd = chains_sub.add_parser("set", help="Replace one category's chain (or --clear it back to the default).")
    set_cmd.add_argument("category", help="Mixture category name (e.g. quick, architect).")
    set_cmd.add_argument("chain", nargs="*", help='Replacement chain: "model[:effort], model[:effort], ..."')
    set_cmd.add_argument("--clear", action="store_true", help="Remove the override so the shipped default applies again.")
    set_cmd.add_argument("--json", action="store_true", help="Print the machine-readable state payload.")
    set_cmd.set_defaults(func=cmd_model_chains_set)

    interview = chains_sub.add_parser(
        "interview",
        help="Walk every category with numbered choices (keep / default / Ultrafast / custom).",
    )
    interview.set_defaults(func=cmd_model_chains_interview)

    # The provider record lives beside the chains because it is what reorders
    # them, and `show` already prints it. These two are the scriptable half
    # of the `omh setup` provider question, which no `--yes`, `--json`, or
    # non-TTY install ever reaches.
    provider = chains_sub.add_parser(
        "provider",
        help="Record what one of this machine's providers serves (scriptable; `omh setup` asks a person).",
    )
    provider_sub = provider.add_subparsers(dest="model_chains_provider_command", required=True)

    provider_set = provider_sub.add_parser("set", help="Record one provider id as serving one model family.")
    provider_set.add_argument("provider", help="Provider id as Hermes names it (a `providers.<id>` key).")
    provider_set.add_argument("kind", help="One of: " + ", ".join(PROVIDER_KIND_VOCABULARY))
    provider_set.add_argument("--json", action="store_true", help="Print the machine-readable result payload.")
    provider_set.set_defaults(func=cmd_model_chains_provider_set)

    provider_clear = provider_sub.add_parser("clear", help="Remove one provider id from the record.")
    provider_clear.add_argument("provider", help="Provider id to stop recording.")
    provider_clear.add_argument("--json", action="store_true", help="Print the machine-readable result payload.")
    provider_clear.set_defaults(func=cmd_model_chains_provider_clear)
