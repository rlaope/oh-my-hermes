"""The OMH TUI's own Hermes runtime: a TUI-only Hermes home beside the bots' gateway.

Hermes serves every profile under `<root>/profiles/` from one gateway per
host, and refuses its standalone stdio entry beside that gateway. A session
opened there shares the bots' fate: a whole-gateway restart with a bot turn
running drains first (up to `agent.restart_after_turn_timeout`) and refuses
every new or resumed session meanwhile. A home outside `profiles/` is its own
root: a client on it gets an unmanaged gateway of its own, which exits once
idle (`gateway.unmanaged_idle_exit_seconds`), and nothing that happens to the
bots' gateway reaches it. Measured in `tools/qa/tui_own_runtime/RESULTS.md`.

`build_tui_home` makes and refreshes that home under the OMH home
(`<omh_home>/tui-home`), from the root Hermes home the bots run on:

- `config.yaml` and `auth.json`: copied, refreshed when the root's is newer
  (mtime carried over, so the next build sees no change). The config is the
  root's as it is: model, providers and their keys, memory (OMH's provider,
  shared), skills (`external_dirs` carries OMH's own skills), plugins.
- `.env`: the root's, minus every messaging credential (`MESSAGING_NAME_PARTS`),
  so no adapter of the TUI runtime ever polls a bot's token beside the bots'
  gateway (Hermes' own warning against two pollers on one token). The root
  `.env` is the default profile's; a named profile's tokens live in that
  profile's own `.env`, which this never reads.
- `SOUL.md`: a symlink to the root's, where it exists.
- `skills/`: one symlink per skill, the union of the root's `skills/` and
  every served profile's, the root winning a name clash (Hermes refuses
  same-tier duplicates as `Ambiguous skill name`, so two roots cannot ride
  `skills.external_dirs`). Links this made that no longer resolve are removed;
  a real directory the person put there is left alone and keeps its name.
- `plugins/omh`: a symlink to the root's OMH plugin bundle, the same
  generation the bots run; `omh update` moves both.
- `omh-tui-home.json`: what was built from what, for `omh doctor`.

Everything else in the home (`state.db`, `kanban.db`, `cache/`, `cron/`,
`sessions/`, `memories/`) is Hermes' own, created by the TUI runtime's
gateway, and never touched here. Bare `omh` reads the saved choice
(`skin_pack.read_runtime_choice`, `omh theme runtime own|shared`) and opens
the TUI on this home when it is `own` (`commands/bare_launch.py`).
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import os
from pathlib import Path
import shutil

from ..system.local_store import atomic_write_json

TUI_HOME_DIR = "tui-home"
MARKER_FILE = "omh-tui-home.json"
MARKER_SCHEMA = "omh_tui_home/v1"
# Copied from the root home and refreshed when the root's copy is newer.
COPIED_FILES = ("config.yaml", "auth.json")
# Symlinked to the root home's, where it exists.
LINKED_FILES = ("SOUL.md",)
PLUGIN_NAME = "omh"
# A `.env` name carrying any of these is a messaging credential or setting: never copied into the TUI home.
MESSAGING_NAME_PARTS = (
    "DISCORD_", "SLACK_", "TELEGRAM_", "MATRIX_", "MATTERMOST_", "WEIXIN_", "WECOM_", "QQ_", "FEISHU_", "LARK_",
    "WHATSAPP_", "SIGNAL_", "TEAMS_", "GOOGLE_CHAT_", "YUANBAO_", "MSGRAPH_", "HOMEASSISTANT_", "HA_TOKEN", "HA_URL",
    "DINGTALK_", "LINE_", "TWILIO_", "WEBHOOK_",
)
HOME_MODE = 0o700
FILE_MODE = 0o600


@dataclass(frozen=True)
class TuiHome:
    """What `build_tui_home` left: the home, the root it mirrors, and what it did this time."""

    path: Path
    root: Path
    served: tuple[str, ...]  # the named profiles whose skills joined the union
    skills: tuple[str, ...]  # every skill name linked, sorted
    clashes: tuple[tuple[str, str], ...]  # (skill, the profile whose copy lost to the root's or an earlier profile's)
    kept_local: tuple[str, ...]  # real entries in skills/ the person made, left alone
    scrubbed: tuple[str, ...]  # `.env` names left out as messaging credentials
    refreshed: tuple[str, ...]  # the files and links written this time, relative to the home


def tui_home_path(omh_home: Path) -> Path:
    return Path(omh_home) / TUI_HOME_DIR


def is_messaging_name(name: str) -> bool:
    """Whether a `.env` name is a messaging credential or setting (`MESSAGING_NAME_PARTS`)."""
    upper = name.strip().upper()
    return any(part in upper for part in MESSAGING_NAME_PARTS)


def scrub_env_text(text: str) -> tuple[str, tuple[str, ...]]:
    """The `.env` text without its messaging lines, and the names left out. Comments and blank lines stay."""
    kept: list[str] = []
    scrubbed: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            name = stripped.split("=", 1)[0].removeprefix("export ").strip()
            if is_messaging_name(name):
                scrubbed.append(name)
                continue
        kept.append(line)
    body = "\n".join(kept)
    return (body + "\n" if body else ""), tuple(scrubbed)


def served_profile_names(root: Path) -> tuple[str, ...]:
    """The named profiles whose skills join the union: the ones the root's gateway record says it serves, else every
    `profiles/<name>` with a `skills/` directory. `default` is the root itself."""
    from .bot_board import read_gateway

    served = [name for name in read_gateway(Path(root)).served if name and name != "default"]
    if not served:
        profiles = Path(root) / "profiles"
        if profiles.is_dir():
            served = sorted(p.name for p in profiles.iterdir() if (p / "skills").is_dir())
    return tuple(dict.fromkeys(served))


def skill_roots(root: Path, served: Sequence[str]) -> tuple[tuple[str, Path], ...]:
    """`(owner, skills dir)` in precedence order: the root first, then each served profile as given."""
    root = Path(root)
    return ((("default", root / "skills"),) + tuple((name, root / "profiles" / name / "skills") for name in served))


def _needs_copy(source: Path, target: Path, *, same_size: bool = True) -> bool:
    """Whether `target` is not the copy of `source` made last time: the mtime the copy carried over moved, or, for a
    verbatim copy (`same_size`), the size differs. A scrubbed copy is shorter by design and compares by mtime alone."""
    try:
        src, dst = source.stat(), target.lstat()
    except FileNotFoundError:
        return True
    return src.st_mtime_ns != dst.st_mtime_ns or (same_size and src.st_size != dst.st_size)


def _copy(source: Path, target: Path) -> None:
    shutil.copy2(source, target)  # the mtime rides along: the next build sees no change
    os.chmod(target, FILE_MODE)


def _link(target: Path, destination: Path) -> bool:
    """Make `target` a symlink to `destination`; True when it was made or changed, False when it already was."""
    if target.is_symlink():
        if os.readlink(target) == str(destination):
            return False
        target.unlink()
    elif target.exists():
        return False  # a real entry the person made: left alone
    target.symlink_to(destination)
    return True


def build_tui_home(omh_home: Path, root: Path, served: Sequence[str] | None = None) -> TuiHome:
    """Make or refresh the TUI home under `omh_home` from the root Hermes home; what it did (`TuiHome`).

    Idempotent and cheap: a build on an unchanged root writes nothing. Raises
    `OSError` when the home cannot be made or the root cannot be read.
    """
    root = Path(root)
    home = tui_home_path(omh_home)
    served = tuple(served) if served is not None else served_profile_names(root)
    refreshed: list[str] = []
    for directory in (home, home / "skills", home / "plugins"):
        directory.mkdir(parents=True, exist_ok=True)
    os.chmod(home, HOME_MODE)

    for name in COPIED_FILES:
        source = root / name
        if source.is_file() and _needs_copy(source, home / name):
            _copy(source, home / name)
            refreshed.append(name)

    scrubbed: tuple[str, ...] = ()
    source = root / ".env"
    if source.is_file():
        text, scrubbed = scrub_env_text(source.read_text(encoding="utf-8"))
        target = home / ".env"
        if _needs_copy(source, target, same_size=False) or _differs(target, text):
            target.write_text(text, encoding="utf-8")
            os.chmod(target, FILE_MODE)
            stamp = source.stat()
            os.utime(target, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
            refreshed.append(".env")

    for name in LINKED_FILES:
        if (root / name).exists() and _link(home / name, root / name):
            refreshed.append(name)

    wanted: dict[str, Path] = {}
    clashes: list[tuple[str, str]] = []
    for owner, skills in skill_roots(root, served):
        if not skills.is_dir():
            continue
        for entry in sorted(skills.iterdir(), key=lambda p: p.name):
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            if entry.name in wanted:
                clashes.append((entry.name, owner))
                continue
            wanted[entry.name] = entry
    kept_local: list[str] = []
    skills_dir = home / "skills"
    for entry in sorted(skills_dir.iterdir(), key=lambda p: p.name):
        if entry.is_symlink():
            if entry.name not in wanted or os.readlink(entry) != str(wanted[entry.name]):
                entry.unlink()
                refreshed.append(f"skills/{entry.name} (removed)")
        else:
            kept_local.append(entry.name)
            wanted.pop(entry.name, None)
    for name, destination in wanted.items():
        if _link(skills_dir / name, destination):
            refreshed.append(f"skills/{name}")

    plugin = root / "plugins" / PLUGIN_NAME
    if plugin.is_dir() and _link(home / "plugins" / PLUGIN_NAME, plugin):
        refreshed.append(f"plugins/{PLUGIN_NAME}")

    built = TuiHome(
        path=home, root=root, served=served, skills=tuple(sorted({*wanted, *kept_local})),
        clashes=tuple(clashes), kept_local=tuple(kept_local), scrubbed=scrubbed, refreshed=tuple(refreshed),
    )
    marker = {
        "schema_version": MARKER_SCHEMA, "root": str(root), "served": list(served), "skills": list(built.skills),
        "clashes": [list(pair) for pair in clashes], "kept_local": list(kept_local), "scrubbed": list(scrubbed),
    }
    atomic_write_json(home / MARKER_FILE, marker, private=True)
    return built


def _differs(target: Path, text: str) -> bool:
    try:
        return target.read_text(encoding="utf-8") != text
    except (OSError, UnicodeDecodeError):
        return True


@dataclass(frozen=True)
class TuiHomeStatus:
    """What `omh doctor` and the menu bar say of the TUI home, read without building it (`tui_home_status`)."""

    runtime: str  # the saved choice: `own` or `shared`
    home: Path
    exists: bool
    built_from: str  # the root the marker names; "" without a marker
    served: tuple[str, ...]
    skill_count: int
    clash_count: int
    broken_links: tuple[str, ...]  # skills whose link resolves to nothing: the skill went since the last build
    messaging_names: tuple[str, ...]  # `.env` names that are messaging credentials: never expected after a build
    gateway_live: bool
    gateway_pid: int | None
    platforms: tuple[str, ...]  # adapters the TUI runtime's gateway reports connected: never expected

    @property
    def built(self) -> bool:
        return bool(self.built_from)


def tui_home_status(omh_home: Path, runtime: str | None) -> TuiHomeStatus:
    """The TUI home as it is now, for the report surfaces; `runtime` is the saved choice (`read_runtime_choice`)."""
    import json

    from .bot_board import read_gateway

    home = tui_home_path(omh_home)
    exists = home.is_dir()
    marker: dict[str, object] = {}
    if exists:
        try:
            loaded = json.loads((home / MARKER_FILE).read_text(encoding="utf-8"))
            marker = loaded if isinstance(loaded, dict) and loaded.get("schema_version") == MARKER_SCHEMA else {}
        except (OSError, ValueError):
            marker = {}
    broken: list[str] = []
    skills_dir = home / "skills"
    if skills_dir.is_dir():
        for entry in sorted(skills_dir.iterdir(), key=lambda p: p.name):
            if entry.is_symlink() and not entry.exists():
                broken.append(entry.name)
    messaging: tuple[str, ...] = ()
    if (home / ".env").is_file():
        try:
            _, messaging = scrub_env_text((home / ".env").read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            messaging = ()
    gateway = read_gateway(home) if exists else None
    served = marker.get("served")
    skills = marker.get("skills")
    clashes = marker.get("clashes")
    return TuiHomeStatus(
        runtime=runtime or "shared", home=home, exists=exists, built_from=str(marker.get("root") or ""),
        served=tuple(str(name) for name in served) if isinstance(served, list) else (),
        skill_count=len(skills) if isinstance(skills, list) else 0,
        clash_count=len(clashes) if isinstance(clashes, list) else 0,
        broken_links=tuple(broken), messaging_names=messaging,
        gateway_live=bool(gateway is not None and gateway.live),
        gateway_pid=gateway.pid if gateway is not None and gateway.live else None,
        platforms=tuple(p.name for p in gateway.platforms if p.current) if gateway is not None and gateway.live else (),
    )
