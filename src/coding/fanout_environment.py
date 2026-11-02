"""Least-privilege process environments for local fanout children."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re
from typing import Mapping

from .pi_family_interop import PI_DISTRIBUTION_AGENT_DIR_ENV, PI_DISTRIBUTION_BRAND_ENV

CHILD_ENVIRONMENT_POLICY_SCHEMA_VERSION = "child_environment_policy/v1"
CHILD_ENVIRONMENT_POLICY_CLAIM_BOUNDARY = (
    "This receipt records environment variable names selected at the local child-process boundary. "
    "It stores no environment values and is not evidence that a child read, used, or protected a capability."
)
_RECEIPT_NAMES = ("approved", "denied", "missing", "passed", "removed")
# SYSTEMDRIVE belongs with SYSTEMROOT and WINDIR: a non-sensitive Windows base
# variable. Codex's MXC sandbox refuses to start any shell command without it
# ("MXC requires nonempty Unicode host SystemDrive", #2471).
_PORTABLE_BASE_NAMES = frozenset({
    "APPDATA", "COLORTERM", "COMSPEC", "HOME", "HOMEDRIVE", "HOMEPATH", "LANG", "LC_ALL",
    "LC_CTYPE", "LOCALAPPDATA", "LOGNAME", "NO_COLOR", "PATH", "PATHEXT", "SHELL", "SYSTEMDRIVE",
    "SYSTEMROOT", "TEMP", "TERM", "TMP", "TMPDIR", "USER", "USERPROFILE", "WINDIR",
})
_OWNER_STATE_NAMES = {
    "codex": frozenset({"CODEX_HOME"}),
    "claude-code": frozenset({"CLAUDE_CONFIG_DIR"}),
    "hermes": frozenset({"HERMES_HOME"}),
    "pi-family-runtime": frozenset({"PI_CODING_AGENT_DIR", PI_DISTRIBUTION_BRAND_ENV, PI_DISTRIBUTION_AGENT_DIR_ENV}),
}
_LINEAGE_NAMES = frozenset({"OMH_FANOUT_DEPTH", "OMH_FANOUT_LINEAGE"})
_SENSITIVE_NAME_TOKENS = frozenset({
    "AUTH", "AUTHORIZATION", "CONNECTOR", "CONNECTION", "CREDENTIAL", "DEPLOY", "KEY", "PASS",
    "PASSWORD", "PIN", "PROVIDER", "SECRET", "TOKEN",
})
_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_MAX_RECEIPT_NAMES = 64


@dataclass(frozen=True, slots=True)
class ChildEnvironmentDecision:
    """Filtered environment plus a metadata-only policy receipt."""

    environment: dict[str, str]
    receipt: dict[str, object]
    _owner: str
    _purpose: str
    _compatibility: str
    _removed: tuple[str, ...]
    _parent_names: tuple[str, ...]
    _missing: tuple[str, ...]
    _denied: tuple[str, ...]
    _conflicts: tuple[str, ...]
    _approved: tuple[str, ...]
    _reasons: dict[str, tuple[str, str]]

    @property
    def ready(self) -> bool:
        """Whether every declared required capability was available and allowed."""
        return not self._missing and not self._conflicts


def resolve_child_environment(
    parent: Mapping[str, str], *, owner: str, purpose: str,
    declaration: Mapping[str, object] | None = None, overrides: Mapping[str, str] | None = None,
) -> ChildEnvironmentDecision:
    """Select the declared capabilities for one owner or verification child."""
    if purpose not in {"owner", "verification"}:
        raise ValueError("child environment purpose must be owner or verification")
    if declaration is not None and not isinstance(declaration, Mapping):
        raise ValueError("child environment policy must be a mapping")
    policy = {} if declaration is None else declaration
    owner_caps = _capability_names(policy.get("owner_capabilities"), owner)
    verification_caps = _names(policy.get("verification_capabilities"), "verification_capabilities")
    project = _names(policy.get("project_variables"), "project_variables")
    declared_denied = _names(policy.get("denied_names"), "denied_names")
    broad = policy.get("allow_broad_inheritance", False)
    if not isinstance(broad, bool):
        raise ValueError("allow_broad_inheritance must be a boolean")
    required = owner_caps if purpose == "owner" else verification_caps
    allowed = set(_PORTABLE_BASE_NAMES) | set(_LINEAGE_NAMES) | set(project)
    reasons = {name: ("portable_base", "policy") for name in _PORTABLE_BASE_NAMES}
    reasons.update({name: ("lineage_metadata", "dispatcher") for name in _LINEAGE_NAMES})
    reasons.update({name: ("project_variable", "declaration") for name in project})
    if purpose == "owner":
        state = _OWNER_STATE_NAMES.get(owner, frozenset())
        allowed.update(state)
        allowed.update(owner_caps)
        reasons.update({name: ("owner_state", "policy") for name in state})
        reasons.update({name: ("owner_capability", "declaration") for name in owner_caps})
    else:
        allowed.update(verification_caps)
        reasons.update({name: ("verification_capability", "declaration") for name in verification_caps})
    override_names = _names(tuple((overrides or {}).keys()), "overrides")
    denied = set(declared_denied)
    for name in override_names:
        if name in _LINEAGE_NAMES or name in declared_denied or (_sensitive_name(name) and name not in required):
            denied.add(name)
            reasons[name] = ("override_not_granted", "override")
        else:
            allowed.add(name)
            reasons[name] = ("command_override", "override")
    missing = tuple(sorted(name for name in required if name not in parent and name not in (overrides or {})))
    conflicts = tuple(sorted(denied & (set(required) | set(project) | set(override_names))))
    environment = dict(parent) if broad else {name: parent[name] for name in sorted(allowed) if name in parent}
    for name in denied:
        environment.pop(name, None)
    environment.update({name: value for name, value in (overrides or {}).items() if name not in denied})
    removed = tuple(sorted(name for name in parent if name not in environment))
    for name in removed:
        reasons.setdefault(name, ("parent_not_approved", "parent"))
    return _decision(
        environment, owner, purpose, "compatibility_explicit" if broad else "least_privilege",
        removed, tuple(sorted(parent)), missing, tuple(sorted(denied)), conflicts,
        tuple(sorted((set(required) | set(project)) & set(environment))), reasons,
    )


def finalize_child_environment(
    decision: ChildEnvironmentDecision, environment: Mapping[str, str],
) -> ChildEnvironmentDecision:
    """Rebuild a receipt after dispatcher-owned metadata changes the environment."""
    reasons = dict(decision._reasons)
    for name in environment:
        reasons.setdefault(name, ("dispatcher_metadata", "dispatcher"))
    return _decision(
        dict(environment), decision._owner, decision._purpose, decision._compatibility,
        tuple(sorted(set(decision._parent_names) - set(environment))), decision._parent_names,
        decision._missing, decision._denied, decision._conflicts,
        tuple(sorted(set(decision._approved) & set(environment))), reasons,
    )


def _decision(
    environment: dict[str, str], owner: str, purpose: str, compatibility: str, removed: tuple[str, ...],
    parent_names: tuple[str, ...], missing: tuple[str, ...], denied: tuple[str, ...], conflicts: tuple[str, ...], approved: tuple[str, ...],
    reasons: dict[str, tuple[str, str]],
) -> ChildEnvironmentDecision:
    passed = tuple(sorted(environment))
    receipt = _receipt(owner, purpose, compatibility, approved, denied, missing, passed, removed, reasons, conflicts)
    return ChildEnvironmentDecision(environment, receipt, owner, purpose, compatibility, removed, parent_names, missing, denied, conflicts, approved, reasons)


def _capability_names(value: object, owner: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, Mapping):
        raise ValueError("owner_capabilities must map owner names to variable-name lists")
    return _names(value.get(owner), f"owner_capabilities[{owner}]")


def _names(value: object, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)) or not all(isinstance(name, str) for name in value):
        raise ValueError(f"{field} must be a list of environment variable names")
    names = tuple(sorted(set(value)))
    if any(_NAME_RE.fullmatch(name) is None for name in names):
        raise ValueError(f"{field} contains an invalid environment variable name")
    return names


def _sensitive_name(name: str) -> bool:
    return bool(set(name.upper().split("_")) & _SENSITIVE_NAME_TOKENS)


def _receipt(
    owner: str, purpose: str, compatibility: str, approved: tuple[str, ...], denied: tuple[str, ...],
    missing: tuple[str, ...], passed: tuple[str, ...], removed: tuple[str, ...],
    reasons: Mapping[str, tuple[str, str]], conflicts: tuple[str, ...],
) -> dict[str, object]:
    full: dict[str, tuple[str, ...]] = {
        name: values
        for name, values in zip(
            _RECEIPT_NAMES, (approved, denied, missing, passed, removed), strict=True
        )
    }
    classifications = [
        {"name": name, "classification": _classification(name, full), "reason": reasons.get(name, ("parent_not_approved", "parent"))[0], "policy_source": reasons.get(name, ("parent_not_approved", "parent"))[1]}
        for name in sorted(set().union(*full.values()))
    ]
    digest = sha256(json.dumps([CHILD_ENVIRONMENT_POLICY_SCHEMA_VERSION, owner, purpose, compatibility, full, classifications], separators=(",", ":"), sort_keys=True).encode("utf-8")).hexdigest()
    bounded = {
        name: [value for value in values if _NAME_RE.fullmatch(value) is not None][:_MAX_RECEIPT_NAMES]
        for name, values in full.items()
    }
    preview_classifications = [
        entry for entry in classifications if _NAME_RE.fullmatch(entry["name"]) is not None
    ][:_MAX_RECEIPT_NAMES]
    return {
        "schema_version": CHILD_ENVIRONMENT_POLICY_SCHEMA_VERSION,
        "status": "not_ready" if missing or conflicts else "ready", "owner": owner, "purpose": purpose,
        "compatibility": compatibility, **bounded,
        "counts": {name: len(values) for name, values in full.items()},
        "truncated": {name: len(bounded[name]) < len(values) for name, values in full.items()},
        "classifications": preview_classifications,
        "classifications_truncated": len(preview_classifications) < len(classifications),
        "policy_digest": digest, "claim_boundary": CHILD_ENVIRONMENT_POLICY_CLAIM_BOUNDARY,
    }


def _classification(name: str, full: Mapping[str, tuple[str, ...]]) -> str:
    for classification in ("denied", "missing", "passed", "removed"):
        if name in full[classification]:
            return classification
    return "approved"
