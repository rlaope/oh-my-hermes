"""External handoff facade over the existing coding delegation builder."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, cast

from ..coding_delegation import _build_coding_delegation_payload_native
from ..executors import EXTERNAL_CLI_PROFILES
from .contracts import (
    ExternalHandoffCapability,
    ExternalHandoffRequest,
    ExternalProfile,
    HandoffField,
    PreparedExternalHandoff,
    PreparedHandoffObservationAdapter,
    PreparedHandoffStatusAdapter,
)


_HANDOFF_FIELD_BY_OWNER_MODE: dict[str, HandoffField] = {
    "external_executor": "executor_handoff",
    "prompt_only_handoff": "prompt_handoff",
    "runtime_handoff": "runtime_handoff",
}
# Everything this facade will build a handoff for. Derived from the narrow
# external-CLI tuple so `set(EXTERNAL_CLI_PROFILES) < _EXTERNAL_PROFILES`
# holds by construction: the handoff builder also serves runtime profiles and
# the generic prompt fallback, which are not Maestro.
_EXTERNAL_PROFILES = frozenset(
    {*EXTERNAL_CLI_PROFILES, "omx-runtime", "pi-family-runtime", "omc-runtime", "generic"}
)


class HermesNativeSelectionError(ValueError):
    """Raised when a Hermes-owned path reaches the external coordinator."""

    def __init__(self, message: str, *, payload: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.payload = payload


def build_external_handoff(request: ExternalHandoffRequest) -> PreparedExternalHandoff:
    """Build an external handoff without changing any public payload field."""

    if request.profile == "hermes":
        raise HermesNativeSelectionError(
            "Hermes-native selection bypasses maestro; use the Hermes runtime path."
        )
    if request.profile not in _EXTERNAL_PROFILES:
        raise ValueError(f"unsupported maestro external profile: {request.profile}")
    payload = _build_coding_delegation_payload_native(
        request.message,
        source=request.source,
        limit=request.limit,
        include_message=request.include_message,
        source_metadata=dict(request.source_metadata) if request.source_metadata else None,
        main_agent_model=request.main_agent_model,
        executor_target=request.profile,
        context_pack=request.context_pack,
        input_manifest=request.input_manifest,
        memory_recall_pack=request.memory_recall_pack,
        plan_artifact=request.plan_artifact,
        preferred_workflow=request.preferred_workflow,
        preferred_workflow_score=request.preferred_workflow_score,
        prefer_direct_coding_handoff=request.prefer_direct_coding_handoff,
        preserve_preferred_workflow=request.preserve_preferred_workflow,
        force_coding_handoff=request.force_coding_handoff,
        explicit_owner_choice=request.explicit_owner_choice,
        capability_snapshot_directory=request.capability_snapshot_directory,
        project_root=request.project_root,
        governance_default=request.governance_default,
        product_family=request.product_family,
        message_context_mode=request.message_context_mode,
        safety_preflight=request.safety_preflight,
        live_safety_profile_revision=request.live_safety_profile_revision,
        requested_authority_actions=request.requested_authority_actions,
        model_recommendation=request.model_recommendation,
        model_chains=request.model_chains,
        requested_model=request.requested_model,
        requested_effort=request.requested_effort,
        requested_identity=request.requested_identity,
        identity_config=request.identity_config,
        handoff_contract=request.handoff_contract,
    )
    selected_profile = payload.get("selected_executor_profile")
    if selected_profile == "hermes" or payload.get("work_owner_mode") == "retained_hermes":
        raise HermesNativeSelectionError(
            "Hermes-native selection bypasses maestro; use the Hermes runtime path.",
            payload=payload,
        )
    owner_mode = str(payload["work_owner_mode"])
    try:
        handoff_field = _HANDOFF_FIELD_BY_OWNER_MODE[owner_mode]
    except KeyError as exc:
        raise ValueError(f"unsupported external handoff owner mode: {owner_mode}") from exc
    handoff_value = payload.get(handoff_field)
    if not isinstance(handoff_value, dict):
        raise ValueError(f"external handoff payload is missing {handoff_field}")
    schema_version = handoff_value.get("schema_version")
    if not isinstance(schema_version, str):
        raise ValueError(f"{handoff_field} is missing schema_version")
    if selected_profile not in _EXTERNAL_PROFILES:
        raise ValueError(f"builder selected a non-external profile: {selected_profile}")
    capability = ExternalHandoffCapability(
        profile=cast(ExternalProfile, selected_profile),
        work_owner_mode=owner_mode,
        handoff_field=handoff_field,
        schema_version=schema_version,
        dispatchable=bool(payload["dispatchable"]),
    )
    return PreparedExternalHandoff(
        capability=capability,
        payload=payload,
        handoff=handoff_value,
    )


@dataclass(frozen=True)
class Maestro:
    """Coordinates prepared handoffs through injected status adapters."""

    status_adapter: PreparedHandoffStatusAdapter
    observation_adapter: PreparedHandoffObservationAdapter

    def prepare(self, request: ExternalHandoffRequest) -> PreparedExternalHandoff:
        return build_external_handoff(request)

    def status(self, handoff: PreparedExternalHandoff) -> Mapping[str, object]:
        return self.status_adapter.status_for(handoff)

    def observations(
        self,
        handoff: PreparedExternalHandoff,
    ) -> tuple[Mapping[str, object], ...]:
        return self.observation_adapter.observations_for(handoff)
