"""The opt-in in-child fallback chain for `omh_delegate_route` (#3124).

`set` writes a lane's chain head into `delegation.model` /
`delegation.reasoning_effort` / `delegation.provider`. With this option on,
it also writes the chain positions after the head into
`delegation.fallback_providers`, each with its own provider, wire model and
effort, so a child whose head fails moves to the next position inside the
same dispatch instead of waiting for `action=fallback` to re-dispatch it.

Two things must both hold, and either one missing leaves the three scalars
exactly as before:

* **The person turned it on**: `write_fallback_providers: true` in
  `~/.omh/routing/delegate-route.json` (`delegate_route_options/v1`). It is
  off by default and off for a missing or invalid document.
* **The host honours the entry's effort.** Hermes before hermes-agent PR
  #144787 resolves a fallback's reasoning from `agent.reasoning_overrides`
  and the global effort and ignores the entry's own `reasoning_effort`
  (hermes-agent #136441), so a chain written there would run every step at
  the wrong effort. The PR adds `agent/fallback_reasoning.py` with
  `resolve_fallback_reasoning`, whose precedence starts with the entry's
  effort. `host_support` looks for that function in the Hermes source,
  read off disk as text: nothing is imported or executed. That is evidence
  of what the installation declares, not of what a running process loaded,
  so a Hermes updated on disk but not restarted reads as the new one.

Read-only: nothing here writes. `omh doctor` reports both answers
(`delegate_route_fallback_chain`).
"""

from __future__ import annotations

import json
from importlib.util import find_spec
from pathlib import Path
from typing import Any

from . import runtime_paths

DELEGATE_ROUTE_OPTIONS_SCHEMA_VERSION = "delegate_route_options/v1"
OPTION_KEY = "write_fallback_providers"
# The module and function hermes-agent PR #144787 adds; their presence is
# the capability. The PR number is named so a reader can check the claim.
HOST_CAPABILITY_MODULE = Path("agent") / "fallback_reasoning.py"
HOST_CAPABILITY_FUNCTION = "def resolve_fallback_reasoning("
HOST_CAPABILITY_REFERENCE = "hermes-agent PR #144787 (agent.fallback_reasoning)"
_MAX_SOURCE_BYTES = 256_000


def delegate_route_options_path(omh_home: str | Path | None = None) -> Path:
    root = Path(omh_home).expanduser() if omh_home else runtime_paths.default_omh_home()
    return root / "routing" / "delegate-route.json"


def load_fallback_chain_option(omh_home: str | Path | None = None) -> tuple[bool, str]:
    """Whether the person turned the in-child chain on, and the document's status.

    The status is `absent`, `enabled`, `disabled` or `invalid: <reason>`; only
    `enabled` turns it on.
    """
    path = delegate_route_options_path(omh_home)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return False, "absent"
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return False, f"invalid: {type(exc).__name__}"
    if not isinstance(raw, dict) or raw.get("schema_version") != DELEGATE_ROUTE_OPTIONS_SCHEMA_VERSION:
        return False, f"invalid: schema_version must be {DELEGATE_ROUTE_OPTIONS_SCHEMA_VERSION}"
    value = raw.get(OPTION_KEY, False)
    if not isinstance(value, bool):
        return False, f"invalid: {OPTION_KEY} must be true or false"
    return value, "enabled" if value else "disabled"


def running_hermes_code_root() -> Path | None:
    """The source root of the Hermes this process runs in, when it runs in one.

    `find_spec` of a top-level package locates it without importing it. No
    `agent` package (OMH's own CLI, a test) is no Hermes.
    """
    try:
        spec = find_spec("agent")
    except (ImportError, ValueError):
        return None
    locations = list(getattr(spec, "submodule_search_locations", None) or []) if spec else []
    return Path(locations[0]).parent if locations else None


def host_support(code_root: str | Path | None = None) -> dict[str, Any]:
    """Whether the Hermes at `code_root` honours a fallback entry's `reasoning_effort`.

    `code_root` defaults to the running Hermes (`running_hermes_code_root`);
    `omh doctor` passes the installation under the Hermes home. The answer
    carries `supported`, a `reason` token and the file it read.
    """
    root = Path(code_root) if code_root is not None else running_hermes_code_root()
    if root is None:
        return {"supported": False, "reason": "hermes_source_not_found", "evidence": ""}
    source = root / HOST_CAPABILITY_MODULE
    try:
        if not source.is_file() or source.stat().st_size > _MAX_SOURCE_BYTES:
            return {"supported": False, "reason": "fallback_reasoning_missing", "evidence": source.as_posix()}
        text = source.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {"supported": False, "reason": "fallback_reasoning_unreadable", "evidence": source.as_posix()}
    if HOST_CAPABILITY_FUNCTION not in text or "reasoning_effort" not in text:
        return {"supported": False, "reason": "fallback_reasoning_without_entry_effort", "evidence": source.as_posix()}
    return {"supported": True, "reason": "entry_effort_honoured", "evidence": source.as_posix()}


def host_support_note(support: dict[str, Any]) -> str:
    """One sentence for a person: why the chain is or is not written on this host."""
    if support.get("supported"):
        return f"this Hermes honours a fallback entry's reasoning_effort ({support.get('evidence')})"
    where = support.get("evidence") or "the running Hermes"
    reason = str(support.get("reason", ""))
    if reason == "hermes_source_not_found":
        return "the Hermes source could not be found, so whether it honours a fallback entry's reasoning_effort is unknown"
    return (
        f"{where} does not show {HOST_CAPABILITY_REFERENCE}, so Hermes would run every fallback "
        "at agent.reasoning_overrides / the global effort instead of the chain's own"
    )
