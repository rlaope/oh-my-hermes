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
  effort. `host_support` looks for that function, with the PR's own
  signature and its read of the entry's `reasoning_effort`, in the Hermes
  source, read off disk as text: nothing is imported or executed.

  The source on disk is what the installation declares, not what a running
  process loaded, and a running Hermes that predates the update would run
  the chain at the wrong efforts -- worse than no chain. So inside a running
  Hermes the answer also takes runtime evidence: the capability module
  already loaded in this process is support; a capability file changed
  after this process loaded OMH's plugin is `restart_pending`, not support.
  `omh doctor`, outside the process, compares the file with the gateway's
  pid file the same way.

Read-only: nothing here writes. `omh doctor` reports both answers
(`plugin_delegate_route_fallback_chain`).
"""

from __future__ import annotations

import json
import re
import sys
import time
from importlib.util import find_spec
from pathlib import Path
from typing import Any

from . import runtime_paths

DELEGATE_ROUTE_OPTIONS_SCHEMA_VERSION = "delegate_route_options/v1"
OPTION_KEY = "write_fallback_providers"
# The module and function hermes-agent PR #144787 adds; their presence is
# the capability. The PR number is named so a reader can check the claim.
HOST_CAPABILITY_MODULE = Path("agent") / "fallback_reasoning.py"
HOST_CAPABILITY_MODULE_NAME = "agent.fallback_reasoning"
HOST_CAPABILITY_REFERENCE = "hermes-agent PR #144787 (agent.fallback_reasoning)"
# The PR's resolver takes the fallback entry and reads the entry's own
# effort; a function of the same name that does neither is not the capability.
_CAPABILITY_SIGNATURE = re.compile(r"^def resolve_fallback_reasoning\(\s*agent\b[^)]*\bentry\b", re.MULTILINE)
_CAPABILITY_ENTRY_READ = re.compile(r"""\bentry\.get\(\s*["']reasoning_effort["']\s*\)""")
_MAX_SOURCE_BYTES = 256_000
# When this process loaded OMH's plugin, which Hermes does at startup: a
# capability file newer than this was not there when this Hermes started.
PROCESS_LOADED_AT = time.time()


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


def host_support(code_root: str | Path | None = None, *, started_at: float | None = None) -> dict[str, Any]:
    """Whether the Hermes at `code_root` honours a fallback entry's `reasoning_effort`.

    `code_root` defaults to the running Hermes (`running_hermes_code_root`),
    where the capability module already in `sys.modules` is the strongest
    evidence and `started_at` defaults to `PROCESS_LOADED_AT`. `omh doctor`
    passes the installation under the Hermes home and the gateway's start.
    A capability file modified after `started_at` is `restart_pending`. The
    answer carries `supported`, a `reason` token and the file it read.
    """
    if code_root is None:
        loaded = sys.modules.get(HOST_CAPABILITY_MODULE_NAME)
        if callable(getattr(loaded, "resolve_fallback_reasoning", None)):
            return {"supported": True, "reason": "capability_loaded", "evidence": str(getattr(loaded, "__file__", ""))}
        started_at = PROCESS_LOADED_AT if started_at is None else started_at
    root = Path(code_root) if code_root is not None else running_hermes_code_root()
    if root is None:
        return {"supported": False, "reason": "hermes_source_not_found", "evidence": ""}
    source = root / HOST_CAPABILITY_MODULE
    try:
        if not source.is_file() or source.stat().st_size > _MAX_SOURCE_BYTES:
            return {"supported": False, "reason": "fallback_reasoning_missing", "evidence": source.as_posix()}
        modified = source.stat().st_mtime
        text = source.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {"supported": False, "reason": "fallback_reasoning_unreadable", "evidence": source.as_posix()}
    if not (_CAPABILITY_SIGNATURE.search(text) and _CAPABILITY_ENTRY_READ.search(text)):
        return {"supported": False, "reason": "fallback_reasoning_without_entry_effort", "evidence": source.as_posix()}
    if started_at is not None and modified > started_at:
        return {"supported": False, "reason": "restart_pending", "evidence": source.as_posix()}
    return {"supported": True, "reason": "entry_effort_honoured", "evidence": source.as_posix()}


def chain_allowed(omh_home: str | Path | None = None) -> bool:
    """The option is on and the running host honours the entry's effort."""
    return load_fallback_chain_option(omh_home)[0] and bool(host_support()["supported"])


def host_support_note(support: dict[str, Any]) -> str:
    """One sentence for a person: why the chain is or is not written on this host."""
    if support.get("supported"):
        return f"this Hermes honours a fallback entry's reasoning_effort ({support.get('evidence')})"
    where = support.get("evidence") or "the running Hermes"
    reason = str(support.get("reason", ""))
    if reason == "restart_pending":
        return (
            f"{where} honours a fallback entry's reasoning_effort but changed after this Hermes started, "
            "so the running Hermes may not; restart Hermes (and its gateway) to pick it up"
        )
    if reason == "hermes_source_not_found":
        return "the Hermes source could not be found, so whether it honours a fallback entry's reasoning_effort is unknown"
    return (
        f"{where} does not show {HOST_CAPABILITY_REFERENCE}, so Hermes would run every fallback "
        "at agent.reasoning_overrides / the global effort instead of the chain's own"
    )
