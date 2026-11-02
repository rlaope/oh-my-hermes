"""Operator defaults for fanout dispatch that outlive one command line (#2471).

`--owner-env` and friends exist only per invocation, so an agent-driven
dispatch (ulw-maestro, a dag node exporting to a coding owner) could not pick
up a grant the operator needs on every run. This file holds those grants and
the Codex Windows sandbox backend, and dispatch reads it on every run:

    <omh_home>/coding/fanout-settings.json
    {
      "schema_version": "omh_fanout_settings/v1",
      "environment_policy": {
        "owner_capabilities": {"codex": ["SOME_NAME"]},
        "project_variables": [],
        "verification_capabilities": [],
        "denied_names": []
      },
      "codex": {"windows_sandbox": "mxc"}
    }

Names only, never values, like the CLI flags. Broad inheritance stays a
per-command choice (`--allow-broad-environment`); the file cannot turn it on.
An absent file changes nothing. A file that exists but cannot be read or does
not validate fails the dispatch loudly: a grant the operator wrote down and
dispatch silently dropped is the failure this file exists to remove.
"""

from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path

from .codex_windows_sandbox import CODEX_WINDOWS_SANDBOX_BACKENDS

FANOUT_SETTINGS_SCHEMA_VERSION = "omh_fanout_settings/v1"
_POLICY_LIST_KEYS = ("project_variables", "verification_capabilities", "denied_names")
_POLICY_KEYS = frozenset({"owner_capabilities", *_POLICY_LIST_KEYS})
_TOP_KEYS = frozenset({"schema_version", "environment_policy", "codex"})


def fanout_settings_path(omh_home: Path) -> Path:
    return Path(omh_home) / "coding" / "fanout-settings.json"


def read_fanout_settings(omh_home: Path) -> dict[str, object]:
    """The validated settings document, or `{}` when no file exists."""
    path = fanout_settings_path(omh_home)
    try:
        if not path.is_file():
            return {}
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"fanout settings at {path} could not be read: {type(exc).__name__}") from exc
    if not isinstance(document, dict) or document.get("schema_version") != FANOUT_SETTINGS_SCHEMA_VERSION:
        raise ValueError(f"fanout settings at {path} must be an object with schema_version {FANOUT_SETTINGS_SCHEMA_VERSION}")
    unknown = sorted(set(document) - _TOP_KEYS)
    if unknown:
        raise ValueError(f"fanout settings at {path} has unknown keys: {', '.join(unknown)}")
    policy = document.get("environment_policy", {})
    if not isinstance(policy, dict) or set(policy) - _POLICY_KEYS:
        raise ValueError(
            f"fanout settings at {path}: environment_policy accepts only {', '.join(sorted(_POLICY_KEYS))}"
        )
    codex = document.get("codex", {})
    if not isinstance(codex, dict) or set(codex) - {"windows_sandbox"}:
        raise ValueError(f"fanout settings at {path}: codex accepts only windows_sandbox")
    backend = codex.get("windows_sandbox", "")
    if backend and backend not in CODEX_WINDOWS_SANDBOX_BACKENDS:
        raise ValueError(
            f"fanout settings at {path}: codex.windows_sandbox must be one of "
            + ", ".join(CODEX_WINDOWS_SANDBOX_BACKENDS)
        )
    return document


def stored_codex_windows_sandbox(omh_home: Path) -> str:
    """The backend dispatch passes to `codex exec`, or "" for Codex's own config."""
    codex = read_fanout_settings(omh_home).get("codex", {})
    return str(codex.get("windows_sandbox", "") or "") if isinstance(codex, dict) else ""


def merged_environment_policy(
    omh_home: Path, declaration: Mapping[str, object] | None,
) -> Mapping[str, object] | None:
    """The command's declaration with the stored grants added to it.

    Union, never override: the command line can add names for one run but
    cannot silently drop one the operator stored. With no stored policy the
    declaration is returned as it came, `None` included.
    """
    stored = read_fanout_settings(omh_home).get("environment_policy")
    if not isinstance(stored, dict) or not stored:
        return declaration
    merged: dict[str, object] = dict(declaration or {})
    for key in _POLICY_LIST_KEYS:
        merged[key] = sorted(set(_list(merged.get(key), key)) | set(_list(stored.get(key), key)))
    owners: dict[str, set[str]] = {}
    for source in (merged.get("owner_capabilities"), stored.get("owner_capabilities")):
        if source is None:
            continue
        if not isinstance(source, Mapping):
            raise ValueError("owner_capabilities must map an owner to a list of names")
        for owner, names in source.items():
            owners.setdefault(str(owner), set()).update(_list(names, f"owner_capabilities.{owner}"))
    merged["owner_capabilities"] = {owner: sorted(names) for owner, names in sorted(owners.items())}
    return merged


def _list(value: object, label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{label} must be a list of environment variable names")
    return list(value)
