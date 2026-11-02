"""Does a recorded Hermes gateway start predate the OMH bundle its home now carries?

A gateway keeps serving the plugin code it loaded at start, so after
`omh update` a bot that was running through the update still answers with
pre-update plugin code until someone restarts it; this module says which
gateways that is, from file evidence alone. Skills are not part of it:
`refresh_skill_dir_caches` makes a running Hermes re-read OMH's skills
directory after the generation pointer moves, with no restart.

Hermes writes ``<hermes_home>/gateway.pid`` when a gateway starts (a JSON
record: ``pid``, ``kind``, ``argv``, ``start_time``, ``hermes_home``, created
O_EXCL and unlinked on a clean stop) and appends one epoch-seconds line per
start attempt to ``<hermes_home>/gateway-starts.log`` (its respawn-storm
ledger: a bounded ring of ``repr(float)`` lines, written at CLI entry before
the pid-ownership check). The pid record's ``start_time`` is NOT a wall clock
and is never read as one here: Hermes' ``_get_process_start_time`` is
``/proc/<pid>/stat`` field 22 (clock ticks since boot) on Linux and psutil
``create_time() * 100`` (centiseconds) elsewhere -- a per-host PID-reuse
fingerprint. The starts ledger carries the wall clock, so the comparison
reads that: the LAST RECORDED START for the home against the bundle
manifest's ``installed_at``. The stamp is rewritten only when an update
changes the bundle's files (a moved ``package_site`` alone keeps it), so the
hint names a gateway whose last recorded start precedes the bundle bytes it
would now load; it does not prove the running process is the one that start
recorded.

No signal, no process listing, no subprocess, and nothing here raises: a
successful update must not end in a traceback over a ledger line that is
not a number. A pid record Hermes left behind after a crash produces a hint
to restart a gateway that is not running, which costs one line; a missing
record produces no hint even when a gateway runs under some other
supervision, which is the evidence boundary and is said as such. A record
naming a different ``hermes_home`` is another profile's, exactly as Hermes'
own cross-profile guard reads it, and produces nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime
import math
import os
from pathlib import Path
import time

from ..install.config_adapter import read_config
from ..install.plugin_pack import read_plugin_manifest
from ..local_store import read_json_object
from ..paths import OmhPaths
from ..install.skill_registration import hermes_profile_dirs, managed_candidate_entries, registration_home_label

GATEWAY_PID_FILENAME = "gateway.pid"
GATEWAY_STARTS_FILENAME = "gateway-starts.log"


def gateway_restart_hints(paths: OmhPaths, *, unrefreshed_configs: frozenset[str] = frozenset()) -> list[str]:
    """One line per home whose last recorded gateway start precedes its bundle install.

    `unrefreshed_configs` names the config.yaml files `refresh_skill_dir_caches`
    could not touch; a gateway there also needs the restart for its skills.
    """
    hints: list[str] = []
    primary = gateway_restart_hint(
        paths.hermes_home,
        label=str(paths.hermes_home),
        restart_command="hermes gateway restart",
        skills_reloaded=str(paths.hermes_home / "config.yaml") not in unrefreshed_configs,
    )
    if primary:
        hints.append(primary)
    for name, profile_dir in hermes_profile_dirs(paths.hermes_home):
        hint = gateway_restart_hint(
            profile_dir,
            label=f"profile {name}",
            restart_command=f"hermes --profile {name} gateway restart",
            skills_reloaded=str(profile_dir / "config.yaml") not in unrefreshed_configs,
        )
        if hint:
            hints.append(hint)
    return hints


def recorded_gateway_starts(hermes_home: Path) -> list[float]:
    """The last recorded start of each gateway the home and its profiles name.

    Update's generation retention reads this, on the same evidence as the
    hint: a pid record naming the home and a wall-clock start in its ledger.
    """
    starts: list[float] = []
    for home in (hermes_home, *(profile for _name, profile in hermes_profile_dirs(hermes_home))):
        start = _last_gateway_start(home / GATEWAY_STARTS_FILENAME) if _pid_record_names_home(home) else None
        if start is not None:
            starts.append(start)
    return starts


def refresh_skill_dir_caches(hermes_home: Path, skills_pointer: Path | None) -> list[dict[str, str]]:
    """Make every Hermes process re-read OMH's skills directory, without a restart.

    Hermes caches the RESOLVED path of each `skills.external_dirs` entry,
    keyed by config.yaml's file signature (mtime, size, inode, ctime). OMH
    registers `<root>/current/skills`, and `current` is the symlink update
    moves to a new generation, so a running gateway kept resolving the old
    generation -- and lost every OMH skill once that generation was
    collected -- until `hermes gateway restart`. Moving the mtime of each
    config that names the pointer changes that signature, and Hermes
    resolves the pointer again on its next skill lookup.

    Only a home whose config names `skills_pointer` (matched the way the
    registration writer matches it, `managed_candidate_entries`) is touched;
    the content is never rewritten, atime is kept, and a missing config is
    never created. Best effort: a home that could not be touched is a
    `failed` row with the reason, never an exception.
    """
    if skills_pointer is None:
        return []
    homes: list[tuple[str | None, Path]] = [(None, hermes_home), *hermes_profile_dirs(hermes_home)]
    rows: list[dict[str, str]] = []
    for profile, home in homes:
        config = home / "config.yaml"
        label = registration_home_label(config, profile=profile)
        try:
            # The pointer check sits inside the try: a pointer that cannot be
            # stat'ed is a `failed` row for each home, not an exception.
            if not config.is_file() or not skills_pointer.is_dir():
                continue
            if not managed_candidate_entries(read_config(config), [skills_pointer], hermes_home=home):
                continue
            os.utime(config, ns=(config.stat().st_atime_ns, time.time_ns()))
        except (OSError, UnicodeError, ValueError) as exc:
            rows.append({"home": label, "config": str(config), "status": "failed", "error": str(exc)})
            continue
        rows.append({"home": label, "config": str(config), "status": "refreshed"})
    return rows


def gateway_restart_hint(hermes_home: Path, *, label: str, restart_command: str, skills_reloaded: bool = True) -> str | None:
    """The hint for one home, or None when the files do not prove a stale gateway."""
    if not _pid_record_names_home(hermes_home):
        return None
    last_start = _last_gateway_start(hermes_home / GATEWAY_STARTS_FILENAME)
    if last_start is None:
        return None
    manifest = read_plugin_manifest(hermes_home / "plugins" / "omh")
    installed_at = _installed_at_epoch(manifest)
    if installed_at is None or last_start >= installed_at:
        return None
    started_iso = _iso_utc(last_start)
    installed_iso = _iso_utc(installed_at)
    if started_iso is None or installed_iso is None:
        return None
    reload = (
        "OMH skills reload on their own, but the new OMH plugin code loads"
        if skills_reloaded
        else "the new OMH skills and plugin code load"
    )
    return (
        f"Hermes gateway for {label}: last recorded start {started_iso} precedes this bundle's "
        f"install ({installed_iso}); {reload} only after `{restart_command}`"
    )


def _pid_record_names_home(hermes_home: Path) -> bool:
    try:
        record = read_json_object(hermes_home / GATEWAY_PID_FILENAME)
    except (OSError, ValueError):
        return False
    if record is None:
        return False
    recorded_home = record.get("hermes_home")
    if not isinstance(recorded_home, str) or not recorded_home.strip():
        # A legacy record without a home proves nothing about another
        # profile, so it is read as this home's -- Hermes reads it the same way.
        return True
    return _same_home(recorded_home, hermes_home)


def _same_home(left: str | Path, right: str | Path) -> bool:
    return os.path.normcase(os.path.realpath(os.path.expanduser(str(left)))) == os.path.normcase(
        os.path.realpath(os.path.expanduser(str(right)))
    )


def _last_gateway_start(path: Path) -> float | None:
    """The latest wall-clock start in the ledger, or None when no line is one.

    Only a finite, positive number is a start: `nan`, `inf`, a negative value
    or bytes that are not UTF-8 are a ledger Hermes did not write, and the
    hint stays silent rather than raising out of `omh update`.
    """
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    starts: list[float] = []
    for line in lines:
        try:
            value = float(line.strip())
        except ValueError:
            continue
        if math.isfinite(value) and value > 0:
            starts.append(value)
    return max(starts) if starts else None


def _installed_at_epoch(manifest: dict[str, object] | None) -> float | None:
    if not manifest:
        return None
    value = manifest.get("installed_at")
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.timestamp()
    except (ValueError, OverflowError, OSError):
        return None


def _iso_utc(epoch: float) -> str | None:
    try:
        return datetime.fromtimestamp(epoch, UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    except (ValueError, OverflowError, OSError):
        return None
