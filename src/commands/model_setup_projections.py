from __future__ import annotations

from collections.abc import Callable

from ..coding.hermes_model_config import providers_entry_remedy
from ..coding.model_routing import MODEL_CATEGORIES


def recommendation_projections(
    *,
    active_models: list[dict[str, str]],
    catalog: dict[str, object],
    main: dict[str, object],
    resolve_model_recommendation: Callable,
    imported_category_overrides: dict[str, object] | None,
    category_override_source: str,
) -> dict[str, object]:
    return {
        "main": main,
        "hermes_native": {
            "owner": "hermes",
            "main": main,
            "categories": _category_recommendations(
                owner="hermes",
                active_models=active_models,
                catalog=catalog,
                resolve_model_recommendation=resolve_model_recommendation,
            ),
        },
        "maestro": {
            "owner": "maestro",
            "categories": _category_recommendations(
                owner="maestro",
                active_models=active_models,
                catalog=catalog,
                resolve_model_recommendation=resolve_model_recommendation,
            ),
        },
        "category_overrides": {
            "status": "imported" if imported_category_overrides else "not_imported",
            "source": category_override_source,
            "categories": sorted((imported_category_overrides or {}).get("categories", {})),
        },
    }


def provider_next_actions(confirmed: set[str], inspection) -> list[dict[str, str]]:
    presence = {provider.provider_id: provider for provider in inspection.providers}
    actions: list[dict[str, str]] = []
    for provider_id in sorted(
        reference.partition("/")[0] for reference in confirmed if "/" in reference
    ):
        provider = presence.get(provider_id)
        if provider_id == "custom" and (provider is None or not provider.auth_present):
            # Bare `custom` names no credential pool to log in to; Hermes
            # resolves a configured custom provider by its own name.
            actions.append(
                {
                    "provider": provider_id,
                    "status": "custom_provider_name_required",
                    "next_action": "use the configured custom provider name as the prefix: <name>/<model>",
                }
            )
        elif provider is not None and not provider.auth_present and provider.provider_entry:
            # A Hermes `providers:` entry has no login: `hermes auth login <id>`
            # answers Unknown provider. Name the route that does make it observable.
            actions.append(
                {
                    "provider": provider_id,
                    "status": "credential_not_observable",
                    "next_action": providers_entry_remedy(provider),
                }
            )
        elif provider is None or not provider.auth_present:
            actions.append(
                {
                    "provider": provider_id,
                    "status": "auth_missing",
                    "next_action": f"hermes auth login {provider_id}",
                }
            )
        elif not provider.auth_status_ok:
            actions.append(
                {
                    "provider": provider_id,
                    "status": "auth_check_failed",
                    "next_action": f"hermes auth status {provider_id}",
                }
            )
        else:
            actions.append(
                {
                    "provider": provider_id,
                    "status": "ready",
                    "next_action": "",
                }
            )
    return actions


def _category_recommendations(
    *,
    owner: str,
    active_models: list[dict[str, str]],
    catalog: dict[str, object],
    resolve_model_recommendation: Callable,
) -> dict[str, object]:
    return {
        category: resolve_model_recommendation(
            owner=owner,
            active_models=active_models,
            category=category,
            catalog=catalog,
        )
        for category in MODEL_CATEGORIES
    }
