"""Which Windows sandbox backend a native-Windows Codex handoff will start with (#2471).

On native Windows, `codex exec` with no `[windows] sandbox` key runs its session
read-only, even under an explicit `-s workspace-write`: every write the unit
needs is refused and the unit ends without a result. Codex's own docs name
three backends (`mxc`, `elevated`, `unelevated`) and say the key lives in
`config.toml`. This module reads that key from the files Codex reads, so the
readiness surface can say "this handoff will be read-only" before a dispatch
spends a run finding out.

Local file reads only: no subprocess, no network, no value other than the
backend name is kept.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import tomllib

CODEX_WINDOWS_SANDBOX_BACKENDS = ("mxc", "elevated", "unelevated")
CODEX_WINDOWS_SANDBOX_CLAIM_BOUNDARY = (
    "Read from the user and project Codex config.toml files only. Managed requirements.toml, "
    "`-c` overrides and config profiles are not read, and no sandbox was started: a configured "
    "backend is not evidence that it starts on this host. The documented check is "
    "`codex -c windows.sandbox=<backend> sandbox --permission-profile :workspace -- cmd.exe /d /c echo OK`."
)
CODEX_WINDOWS_SANDBOX_READ_ONLY_NOTE = (
    "Codex on native Windows has no `[windows] sandbox` backend configured, so its sessions run "
    "read-only and a coding unit cannot write. Set `[windows] sandbox = \"mxc\"` in "
    "`~/.codex/config.toml` (or `elevated` / `unelevated` where MXC is unavailable), or "
    "`codex.windows_sandbox` in OMH's `coding/fanout-settings.json`."
)
_CONFIG_NAME = "config.toml"


def codex_windows_sandbox_signal(
    *,
    platform_name: str,
    environ: Mapping[str, str],
    home: Path,
    project_root: Path | None,
    dispatch_override: str = "",
) -> dict[str, object]:
    """The effective `windows.sandbox` setting a Codex child would read.

    Project config (`<repo>/.codex/config.toml`) wins over the user's
    (`$CODEX_HOME/config.toml`, default `~/.codex/config.toml`), the order
    Codex layers them in. `dispatch_override` is the backend OMH's fanout
    settings pass as `-c windows.sandbox=...`, which wins over both.
    """
    if platform_name != "nt":
        return {
            "status": "not_applicable",
            "value": "",
            "source": "",
            "write_capability": "not_observed",
            "claim_boundary": CODEX_WINDOWS_SANDBOX_CLAIM_BOUNDARY,
        }
    codex_home = environ.get("CODEX_HOME", "").strip()
    layers = [("user_config", (Path(codex_home) if codex_home else home / ".codex") / _CONFIG_NAME)]
    if project_root is not None:
        layers.append(("project_config", project_root / ".codex" / _CONFIG_NAME))
    value, source, unreadable = "", "", []
    for name, path in layers:
        read, failed = _sandbox_value(path)
        if failed:
            unreadable.append(name)
        elif read:
            value, source = read, name
    if dispatch_override:
        value, source = dispatch_override, "omh_fanout_settings"
    if value and value not in CODEX_WINDOWS_SANDBOX_BACKENDS:
        status, write_capability = "unrecognized", "not_observed"
    elif value:
        status, write_capability = "configured", "not_observed"
    elif unreadable:
        status, write_capability = "unreadable", "not_observed"
    else:
        status, write_capability = "not_configured", "read_only_expected"
    return {
        "status": status,
        "value": value,
        "source": source,
        "unreadable_sources": unreadable,
        "write_capability": write_capability,
        "claim_boundary": CODEX_WINDOWS_SANDBOX_CLAIM_BOUNDARY,
    }


def _sandbox_value(path: Path) -> tuple[str, bool]:
    """`(backend name, read failed)` for one config file; a missing file is not a failure."""
    try:
        if not path.is_file():
            return "", False
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return "", True
    windows = data.get("windows")
    if not isinstance(windows, dict):
        return "", False
    sandbox = windows.get("sandbox")
    if not isinstance(sandbox, str):
        return "", False
    # Only a short identifier is kept; anything else is reported as unrecognized
    # without echoing what the file held.
    cleaned = sandbox.strip().casefold()
    return (cleaned if cleaned.isidentifier() and len(cleaned) <= 32 else "invalid"), False
