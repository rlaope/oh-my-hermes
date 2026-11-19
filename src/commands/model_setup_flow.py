from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Callable

from ..coding.hermes_model_config import (
    AliasCollisionError,
    effective_fallback_entries,
    fallback_entries,
    HermesCommandError,
    HermesConfigUnreadableError,
    HermesModelConfigError,
    HermesUnavailableError,
)
from ..coding.model_recommendations import (
    SHIPPED_MODEL_RECOMMENDATIONS,
    merge_recommendation_catalog,
)
from ..installer import OmhError
from .language import tr
from .model_setup_inputs import (
    classified_model_candidates,
    confirmed_model_ids,
    fallback_model_target,
    model_alias_changes,
)
from .model_setup_overrides import load_category_overrides
from .model_setup_projections import provider_next_actions, recommendation_projections


@dataclass(frozen=True, slots=True)
class ModelSetupFlowDependencies:
    discover_local_models: Callable
    inspect_hermes_model_config: Callable
    preview_hermes_model_config: Callable
    apply_hermes_model_config: Callable
    resolve_model_recommendation: Callable
    ask_yes_no: Callable
    ask: Callable
    use_color: Callable
    print_model_preview_review: Callable


def model_activation_result(
    args: argparse.Namespace,
    *,
    language: str,
    dependencies: ModelSetupFlowDependencies,
) -> dict[str, object]:
    discovery = dependencies.discover_local_models(Path.home())
    confirmed = confirmed_model_ids(getattr(args, "confirm_model", []))
    candidates = classified_model_candidates(discovery, confirmed)
    try:
        inspection = dependencies.inspect_hermes_model_config()
    # Every later stage reads, writes, or is bound to the digest of Hermes'
    # config, so none can run; asking the interactive questions would collect
    # answers nothing uses.
    except HermesUnavailableError as exc:
        return _inspection_failed_result(
            discovery,
            candidates,
            status="hermes_unavailable",
            next_action="install_hermes_then_rerun_model_setup",
            cause="Hermes was not found",
            details={"reason": str(exc)},
        )
    except HermesConfigUnreadableError as exc:
        dry_run = bool(getattr(args, "dry_run", False))
        details = {"config_path": str(exc.config_path), "dry_run": dry_run}
        if not exc.missing:
            # The file is there; no setup run creates it, and a dry run is
            # not why it cannot be read.
            return _inspection_failed_result(
                discovery,
                candidates,
                status="hermes_config_unreadable",
                next_action="fix_hermes_config_permissions_then_rerun",
                cause="Hermes' config file exists but could not be read",
                details=details,
            )
        return _inspection_failed_result(
            discovery,
            candidates,
            status="hermes_config_missing",
            # A dry run writes nothing, so on a fresh home the file a real
            # setup creates (step 2 registers OMH in it) does not exist yet.
            next_action="rerun_without_dry_run" if dry_run else "create_hermes_config_then_rerun_model_setup",
            cause="Hermes' config file does not exist",
            details=details,
        )
    except HermesCommandError as exc:
        # `hermes config path` exited nonzero, timed out, or a query returned
        # output the adapter refuses: Hermes is there but did not answer.
        return _inspection_failed_result(
            discovery,
            candidates,
            status="hermes_command_failed",
            next_action="check_hermes_config_commands_then_rerun_model_setup",
            cause="A Hermes command failed",
            details={"reason": str(exc)},
        )
    aliases = model_alias_changes(getattr(args, "model_alias", []))
    fallback = fallback_model_target(getattr(args, "fallback_model", []))

    if getattr(args, "interactive", False):
        confirmed = _confirm_discovered_models(
            candidates,
            confirmed,
            language=language,
            dependencies=dependencies,
        )
        candidates = classified_model_candidates(discovery, confirmed)
        aliases = _edit_model_aliases(aliases, confirmed, dependencies=dependencies)

    active_models = [
        {
            "status": "confirmed_active",
            "model_alias": model_id.rsplit("/", 1)[-1],
            "model_id": model_id.rsplit("/", 1)[-1],
            "provider": model_id.partition("/")[0] if "/" in model_id else "",
            "provider_family": model_id.partition("/")[0] if "/" in model_id else "",
        }
        for model_id in sorted(confirmed)
    ]
    imported_category_overrides = None
    category_override_source = ""
    if getattr(args, "import_category_overrides", False):
        try:
            imported_category_overrides, category_override_source = load_category_overrides(Path.home())
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            raise OmhError(f"cannot import category overrides: {exc}") from exc
    recommendation_catalog = merge_recommendation_catalog(
        SHIPPED_MODEL_RECOMMENDATIONS,
        imported_category_overrides,
    )
    explicit_main = aliases.get("main") or ""
    recommendation = dependencies.resolve_model_recommendation(
        owner="hermes",
        active_models=active_models,
        role_slot="main",
        explicit_model=explicit_main,
        catalog=recommendation_catalog,
    )
    recommendations = recommendation_projections(
        active_models=active_models,
        catalog=recommendation_catalog,
        main=recommendation,
        resolve_model_recommendation=dependencies.resolve_model_recommendation,
        imported_category_overrides=imported_category_overrides,
        category_override_source=category_override_source,
    )
    next_actions = provider_next_actions(confirmed, inspection)

    preview = None
    apply_status: dict[str, object] = {
        "status": "declined" if aliases or fallback else "not_requested",
        "commands": [],
    }
    verification: dict[str, object] = {"status": "not_run", "verified": False}
    status = "unconfigured"
    next_action = "confirm_active_model"

    # A fallback-only run names no main alias, so an unresolved main choice
    # does not block it; with aliases the choice still comes first.
    if recommendation["status"] == "choice_required" and (aliases or not fallback):
        status = "choice_required"
    elif aliases or fallback:
        try:
            model_preview = dependencies.preview_hermes_model_config(
                inspection,
                aliases,
                allow_collisions=bool(getattr(args, "allow_model_alias_collision", False)),
                fallback=fallback,
            )
        except AliasCollisionError as exc:
            if not getattr(args, "interactive", False):
                raise OmhError(str(exc)) from exc
            if not dependencies.ask_yes_no(
                tr(language, "model_setup_collision_prompt", collision=str(exc)),
                default=False,
                use_color=dependencies.use_color(),
                language=language,
            ):
                raise OmhError(str(exc)) from exc
            model_preview = dependencies.preview_hermes_model_config(
                inspection,
                aliases,
                allow_collisions=True,
                fallback=fallback,
            )
        except HermesModelConfigError as exc:
            raise OmhError(str(exc)) from exc
        preview = _model_preview_payload(model_preview)
        status = "preview_ready"
        next_action = "apply_model_config"
        if getattr(args, "interactive", False):
            dependencies.print_model_preview_review(preview, language=language)
            args.apply_model_config = dependencies.ask_yes_no(
                # A dry run writes nothing: the question is whether to list
                # the commands an apply would run, not whether to apply.
                tr(
                    language,
                    "model_setup_apply_prompt_dry_run" if getattr(args, "dry_run", False) else "model_setup_apply_prompt",
                ),
                default=False,
                use_color=dependencies.use_color(),
                language=language,
            )
        if getattr(args, "apply_model_config", False):
            if model_preview.fallback_refusal is not None:
                # Refused before any write, dry run included.
                raise OmhError(model_preview.fallback_refusal)
            expected_digest = str(getattr(args, "model_config_digest", "") or "")
            if getattr(args, "interactive", False) and not expected_digest:
                expected_digest = model_preview.approval_digest
            if not expected_digest:
                raise OmhError("--apply-model-config requires --model-config-digest from this preview.")
            # The digest names the file AND the change the person approved: a
            # preview of one change never authorizes a different one.
            if expected_digest != model_preview.approval_digest:
                raise OmhError(
                    "expected digest does not match the preview digest: rerun the preview with the "
                    "same arguments and pass its approval_digest"
                )
            expected_digest = model_preview.config_digest
            if getattr(args, "dry_run", False):
                # A dry run never spawns a mutating Hermes command: report the
                # exact argv the apply would run, checked against the same digest.
                apply_status = {
                    "status": "dry_run",
                    "commands": [list(command) for command in model_preview.commands],
                }
            else:
                try:
                    receipt = dependencies.apply_hermes_model_config(
                        model_preview,
                        confirmed=True,
                        expected_config_digest=expected_digest,
                    )
                except HermesModelConfigError as exc:
                    raise OmhError(str(exc)) from exc
                apply_status = {
                    "status": "applied",
                    "commands": [list(command) for command in receipt.commands],
                    "before_digest": receipt.before_digest,
                    "after_digest": receipt.after_digest,
                }
                verification = {
                    "status": "verified" if receipt.verified else "failed",
                    "verified": receipt.verified,
                    "config_digest": receipt.after_digest,
                }
                status = "verified" if receipt.verified else "verification_failed"
                next_action = "model_setup_complete" if receipt.verified else "inspect_model_config"
    elif recommendation["status"] == "owner_default":
        status = "defaulted"
        next_action = "model_setup_complete"
    elif confirmed:
        next_action = "edit_model_recommendations"
    else:
        next_action = "confirm_active_model"

    return {
        "schema_version": "omh_model_activation/v1",
        "status": status,
        "stages": ["inspect", "confirm_active", "preview", "apply", "verify"],
        "discovery": discovery,
        "inspection": _model_inspection_payload(inspection),
        "candidates": candidates,
        "recommendations": recommendations,
        "provider_next_actions": next_actions,
        "preview": preview,
        "apply": apply_status,
        "verification": verification,
        "next_action": next_action,
        "claim_boundary": (
            "Model activation uses local metadata and explicit confirmation only. "
            "Observed-before records are not active-model confirmation, and preview is not apply."
        ),
    }


def _inspection_failed_result(
    discovery: dict[str, object],
    candidates: list[dict[str, str]],
    *,
    status: str,
    next_action: str,
    cause: str,
    details: dict[str, object],
) -> dict[str, object]:
    """The payload for a model step that stopped at inspection: nothing later ran."""
    return {
        "schema_version": "omh_model_activation/v1",
        "status": status,
        **details,
        "stages": ["inspect", "confirm_active", "preview", "apply", "verify"],
        "discovery": discovery,
        "inspection": None,
        "candidates": candidates,
        "recommendations": None,
        "provider_next_actions": [],
        "preview": None,
        "apply": {"status": "not_run", "commands": []},
        "verification": {"status": "not_run", "verified": False},
        "next_action": next_action,
        "claim_boundary": (
            f"{cause}, so its model config was not inspected, previewed, or changed. "
            "Nothing about the active model was observed."
        ),
    }


def _confirm_discovered_models(
    candidates: list[dict[str, str]],
    confirmed: set[str],
    *,
    language: str,
    dependencies: ModelSetupFlowDependencies,
) -> set[str]:
    selected = set(confirmed)
    for candidate in candidates:
        if candidate["model"] in selected:
            continue
        if dependencies.ask_yes_no(
            tr(language, "model_setup_confirm_prompt", model=candidate["model"]),
            default=False,
            use_color=dependencies.use_color(),
            note=tr(language, "model_setup_observed_note", status=candidate["status"]),
            language=language,
        ):
            selected.add(candidate["model"])
    return selected


def _edit_model_aliases(
    aliases: dict[str, str],
    confirmed: set[str],
    *,
    dependencies: ModelSetupFlowDependencies,
) -> dict[str, str]:
    if aliases or not confirmed:
        return aliases
    default_model = sorted(confirmed)[0]
    raw = dependencies.ask(
        "Hermes main model alias (provider/model, blank to leave unconfigured)",
        default=default_model,
        use_color=dependencies.use_color(),
    ).strip()
    return {"main": raw} if raw else {}


def _model_preview_payload(preview) -> dict[str, object]:
    return {
        "config_path": str(preview.config_path),
        "config_digest": preview.config_digest,
        # What `--model-config-digest` must name to apply exactly this preview.
        "approval_digest": preview.approval_digest,
        "changes": dict(preview.changes),
        "fallback_model": _fallback_payload(preview),
        "commands": [list(command) for command in preview.commands],
    }


def _fallback_payload(preview) -> dict[str, object] | None:
    """The fallback chain before -> after; None when the run left it alone.

    `before` is Hermes' effective chain (`fallback_providers`, then legacy
    `fallback_model` entries not already present); `after` is its only entry.
    """
    if preview.fallback is None:
        return None
    before = list(preview.before_fallback_chain)
    return {
        "before": before,
        "before_chain": before,
        "after": preview.fallback,
        "replaces_chain": preview.fallback_replaces_chain,
        "unchanged": not preview.fallback_commands and preview.fallback_refusal is None,
        # The chain is in Hermes' older `fallback_model` key; apply is refused.
        "legacy": preview.fallback_is_legacy,
        "refusal": preview.fallback_refusal,
    }


def _model_inspection_payload(inspection) -> dict[str, object]:
    return {
        "config_path": str(inspection.config_path),
        "config_digest": inspection.config_digest,
        "config_check_ok": inspection.config_check_ok,
        "aliases": dict(inspection.model_dot_aliases),
        "main_model": inspection.main_model,
        "fallback_model": list(fallback_entries(inspection.fallback_model)),
        "fallback_chain": list(
            effective_fallback_entries(inspection.fallback_providers, inspection.fallback_model)
        ),
        "providers": [
            {
                "provider_id": provider.provider_id,
                "auth_present": provider.auth_present,
                "auth_status_ok": provider.auth_status_ok,
                "plugin_present": provider.plugin_present,
            }
            for provider in inspection.providers
        ],
        "commands": [list(command) for command in inspection.commands],
    }
