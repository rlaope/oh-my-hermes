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

- `config.yaml`: the root's, copied verbatim (model, providers and their keys,
  memory, skills with `external_dirs` carrying OMH's own skills, plugins) and
  refreshed whenever it differs from the root's; a copy the person changed in
  the TUI home is replaced too, and `TuiHome.overwritten` says so. A root
  config that names a messaging token under `platforms:`
  (`config_platform_credentials`) is reported, and the launch stays on the
  shared gateway: the TUI runtime must never poll a bot's token.
- `auth.json`: copied when the root's is newer than the TUI home's. Hermes
  rotates single-use OAuth refresh tokens into the store it read, so a TUI
  home copy that moved after the root's is kept, never replaced by a stale one.
- `.env`: the root's, minus every messaging credential (`is_messaging_name`),
  so no adapter of the TUI runtime ever polls a bot's token beside the bots'
  gateway (Hermes' own warning against two pollers on one token). The root
  `.env` is the default profile's; a named profile's tokens live in that
  profile's own `.env`, which this never reads. The launch strips the same
  names from the process environment it hands the TUI.
- `SOUL.md`: a symlink to the root's, where it exists.
- `skills/`: one symlink per skill, at the skill's own relative path
  (`<category>/<skill>` or `<skill>`), over the root's `skills/` and every
  served profile's: a skill is a directory holding `SKILL.md`, as Hermes
  discovers them at any depth, and the root wins a clash of skill names
  (Hermes refuses same-tier duplicates as `Ambiguous skill name`, so two roots
  cannot ride `skills.external_dirs`). Links this made to a skill that went
  are removed, with the category directories left empty; a link or a real
  directory the person put there is left alone.
- `plugins/omh`: a symlink to the root's OMH plugin bundle, the same
  generation the bots run; `omh update` moves both.
- `omh-tui-home.json`: what was built from what, for `omh doctor`.

Every file is written whole and moved into place, so a running TUI gateway
never reads a half-written copy. Everything else in the home (`state.db`,
`kanban.db`, `cache/`, `cron/`, `sessions/`, `memories/`) is Hermes' own,
created by the TUI runtime's gateway, and never touched here. Bare `omh` reads
the saved choice (`skin_pack.read_runtime_choice`, `omh theme runtime
own|shared`) and opens the TUI on this home when it is `own`
(`commands/bare_launch.py`).
"""
from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
import os
from pathlib import Path

from ..system.local_store import atomic_write_json

TUI_HOME_DIR = "tui-home"
MARKER_FILE = "omh-tui-home.json"
MARKER_SCHEMA = "omh_tui_home/v1"
# Symlinked to the root home's, where it exists.
LINKED_FILES = ("SOUL.md",)
PLUGIN_NAME = "omh"
SKILL_FILE = "SKILL.md"
# A `.env` name that starts with one of these, or is one of `MESSAGING_NAMES`, is a messaging platform's
# credential or setting and never reaches the TUI home or the TUI's process environment. The prefixes follow
# Hermes' platform plugins (`plugins/platforms/*`) and its API server; a prefix, not a substring, so `ALPHA_TOKEN`
# or `PIPELINE_URL` stay.
MESSAGING_NAME_PREFIXES = (
    "DISCORD_", "SLACK_", "TELEGRAM_", "MATRIX_", "MATTERMOST_", "WEIXIN_", "WECOM_", "QQ_", "QQBOT_", "FEISHU_",
    "LARK_", "WHATSAPP_", "SIGNAL_", "TEAMS_", "GOOGLE_CHAT_", "YUANBAO_", "MSGRAPH_", "HOMEASSISTANT_",
    "DINGTALK_", "LINE_", "TWILIO_", "WEBHOOK_", "EMAIL_", "IMAP_", "SMTP_", "IRC_", "BLUEBUBBLES_", "NTFY_",
    "A2A_", "SMS_", "API_SERVER_", "PHOTON_", "RAFT_", "BUZZ_", "SIMPLEX_",
)
MESSAGING_NAMES = frozenset({"HA_TOKEN", "HA_URL"})
# The keys under a `platforms:` entry of `config.yaml` that make an adapter connect (`gateway/config.py`).
PLATFORM_CREDENTIAL_KEYS = frozenset({
    "token", "api_key", "bot_token", "app_token", "webhook_url", "enabled", "address", "password", "app_id", "app_secret",
    "client_secret", "secret", "signing_secret",
})
HOME_MODE = 0o700
FILE_MODE = 0o600


@dataclass(frozen=True)
class TuiHome:
    """What `build_tui_home` left: the home, the root it mirrors, and what it did this time."""

    path: Path
    root: Path
    served: tuple[str, ...]  # the named profiles whose skills joined the union
    skills: tuple[str, ...]  # every skill linked, as `<category>/<skill>` or `<skill>`, sorted
    clashes: tuple[tuple[str, str], ...]  # (skill path, the profile whose copy lost to the root's or an earlier one's)
    kept_local: tuple[str, ...]  # entries under skills/ the person made (a directory or a link elsewhere), left alone
    scrubbed: tuple[str, ...]  # `.env` names left out as messaging credentials
    refreshed: tuple[str, ...]  # the files and links written this time, relative to the home
    overwritten: tuple[str, ...]  # copies the person had changed in the TUI home, replaced by the root's
    config_platform_credentials: tuple[str, ...]  # `platforms.<name>.<key>` entries of the root config that connect


def tui_home_path(omh_home: Path) -> Path:
    return Path(omh_home) / TUI_HOME_DIR


def is_messaging_name(name: str) -> bool:
    """Whether an environment name is a messaging platform's credential or setting."""
    upper = name.strip().upper()
    return upper in MESSAGING_NAMES or upper.startswith(MESSAGING_NAME_PREFIXES)


def scrub_env_text(text: str) -> tuple[str, tuple[str, ...]]:
    """The `.env` text without its messaging entries, and the names left out. Comments and blank lines stay; a
    quoted value that runs over several lines goes or stays whole with its name."""
    kept: list[str] = []
    scrubbed: list[str] = []
    dropping = False  # inside a scrubbed value's open quote
    quote = ""
    for line in text.splitlines():
        if dropping:
            if _unescaped(line, quote) % 2 == 1:
                dropping = False
            continue
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            name, _, value = stripped.partition("=")
            name = name.removeprefix("export ").strip()
            if is_messaging_name(name):
                scrubbed.append(name)
                value = value.strip()
                if value[:1] in ('"', "'") and _unescaped(value, value[0]) % 2 == 1:
                    dropping, quote = True, value[0]
                continue
        kept.append(line)
    body = "\n".join(kept)
    return (body + "\n" if body else ""), tuple(scrubbed)


def _unescaped(text: str, quote: str) -> int:
    """How many `quote` characters `text` holds that no backslash escapes."""
    count = 0
    for index, char in enumerate(text):
        if char == quote and (index == 0 or text[index - 1] != "\\"):
            count += 1
    return count


def scrub_environment(environ: dict[str, str]) -> tuple[dict[str, str], tuple[str, ...]]:
    """The environment without its messaging names, and the names left out."""
    scrubbed = tuple(sorted(name for name in environ if is_messaging_name(name)))
    return {name: value for name, value in environ.items() if name not in scrubbed}, scrubbed


def config_platform_credentials(config_text: str) -> tuple[str, ...]:
    """`platforms.<name>.<key>` entries of a Hermes `config.yaml` that would connect an adapter: the top-level
    `platforms:` block read line by line, never parsed as YAML. The platform names sit at the indentation of the
    block's first child; a credential key at any deeper level counts, `enabled: false` does not. A `platforms:` line
    that carries a value of its own (flow style) counts whole unless it is empty (`{}`, `[]`, `null`)."""
    found: list[str] = []
    in_block = False
    platform_indent: int | None = None
    platform = ""
    for raw in config_text.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent == 0:
            in_block = line.startswith("platforms:")
            platform_indent, platform = None, ""
            if in_block:
                inline = line.partition(":")[2].split("#", 1)[0].strip()
                if inline and inline not in ("{}", "[]", "null", "~"):
                    found.append(f"platforms: {inline}")
            continue
        if not in_block:
            continue
        key, sep, value = line.strip().partition(":")
        if not sep:
            continue
        if platform_indent is None:
            platform_indent = indent
        if indent <= platform_indent:
            platform = key.strip()
            inline = value.split("#", 1)[0].strip()
            if inline and inline not in ("{}", "[]", "null", "~") and inline.lower() not in ("false", "no", "off"):
                found.append(f"{platform}: {inline}")
            continue
        if platform and key.strip() in PLATFORM_CREDENTIAL_KEYS:
            value = value.split("#", 1)[0].strip().strip("'\"")
            if value and not (key.strip() == "enabled" and value.lower() in ("false", "no", "off", "0")):
                found.append(f"{platform}.{key.strip()}")
    return tuple(found)


def served_profile_names(root: Path) -> tuple[str, ...]:
    """The named profiles whose skills join the union: the ones the root's live gateway record says it serves (none
    when it serves only the default), else every `profiles/<name>` with a `skills/` directory."""
    from .bot_board import read_gateway

    gateway = read_gateway(Path(root))
    if gateway.live:
        return tuple(dict.fromkeys(name for name in gateway.served if name and name != "default"))
    profiles = Path(root) / "profiles"
    if not profiles.is_dir():
        return ()
    return tuple(sorted(p.name for p in profiles.iterdir() if (p / "skills").is_dir()))


def skill_roots(root: Path, served: Sequence[str]) -> tuple[tuple[str, Path], ...]:
    """`(owner, skills dir)` in precedence order: the root first, then each served profile as given."""
    root = Path(root)
    return ((("default", root / "skills"),) + tuple((name, root / "profiles" / name / "skills") for name in served))


def iter_skills(skills_dir: Path) -> Iterator[tuple[str, Path]]:
    """`(relative path, directory)` of every skill under `skills_dir`: a directory holding `SKILL.md`, found at any
    depth as Hermes finds them, nothing beneath one (its support files), nothing under a dot directory."""
    if not skills_dir.is_dir():
        return
    pending = [skills_dir]
    while pending:
        directory = pending.pop()
        try:
            entries = sorted(directory.iterdir(), key=lambda p: p.name)
        except OSError:
            continue
        for entry in entries:
            if entry.name.startswith(".") or not entry.is_dir():
                continue
            if (entry / SKILL_FILE).is_file():
                yield entry.relative_to(skills_dir).as_posix(), entry
            else:
                pending.append(entry)


def _write_whole(target: Path, data: bytes, stamp: os.stat_result | None = None) -> None:
    """Write `data` to a temporary file beside `target` and move it into place, with `stamp`'s times carried over."""
    temporary = target.with_name(f".{target.name}.{os.getpid()}.omh-tmp")
    with open(temporary, "wb") as handle:
        handle.write(data)
    os.chmod(temporary, FILE_MODE)
    if stamp is not None:
        os.utime(temporary, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    os.replace(temporary, target)


def _mtime(path: Path) -> int | None:
    try:
        return path.lstat().st_mtime_ns
    except FileNotFoundError:
        return None


def _points_at(link: Path, destination: Path) -> bool:
    r"""Whether the symlink `link` names `destination`: by the real path of each, since Windows spells a link's
    target with its own prefix (`\\?\`) and a text comparison would relink it at every build."""
    try:
        return os.path.realpath(link) == os.path.realpath(destination)
    except OSError:
        return False


def _under(path: Path, roots: Sequence[Path]) -> bool:
    """Whether the real path of `path` lies under one of `roots` (also by real path)."""
    try:
        real = os.path.realpath(path)
    except OSError:
        return False
    return any(real.startswith(os.path.realpath(root) + os.sep) for root in roots)


def _link(target: Path, destination: Path) -> bool:
    """Make `target` a symlink to `destination`; True when it was made or changed, False when it already was or a
    real entry the person made stands there."""
    if target.is_symlink():
        if _points_at(target, destination):
            return False
        target.unlink()
    elif target.exists():
        return False
    try:
        target.symlink_to(destination, target_is_directory=destination.is_dir())
    except FileExistsError:
        if target.is_symlink() and _points_at(target, destination):
            return False  # another launch made the same link meanwhile
        raise
    return True


def build_tui_home(omh_home: Path, root: Path, served: Sequence[str] | None = None) -> TuiHome:
    """Make or refresh the TUI home under `omh_home` from the root Hermes home; what it did (`TuiHome`).

    Idempotent and cheap: a build on an unchanged root writes nothing. Raises
    `OSError` when the home cannot be made or the root cannot be read, and
    `ValueError` when the root's `.env` or `config.yaml` is not UTF-8 text.
    """
    root = Path(root)
    home = tui_home_path(omh_home)
    served = tuple(served) if served is not None else served_profile_names(root)
    refreshed: list[str] = []
    overwritten: list[str] = []
    for directory in (home, home / "skills", home / "plugins"):
        directory.mkdir(parents=True, exist_ok=True)
    os.chmod(home, HOME_MODE)

    platform_credentials: tuple[str, ...] = ()
    source = root / "config.yaml"
    if source.is_file():
        data = source.read_bytes()
        platform_credentials = config_platform_credentials(_decode(data, source))
        target = home / "config.yaml"
        stamp = source.stat()
        if platform_credentials:
            pass  # never copied: the launch stays on the shared gateway and says why
        elif _mtime(target) != stamp.st_mtime_ns or target.read_bytes() != data:
            previous = _mtime(target)
            if previous is not None and previous > stamp.st_mtime_ns:
                overwritten.append("config.yaml")
            _write_whole(target, data, stamp)
            refreshed.append("config.yaml")

    source = root / "auth.json"
    if source.is_file():
        target = home / "auth.json"
        stamp = source.stat()
        current = _mtime(target)
        if current is None or stamp.st_mtime_ns > current:
            _write_whole(target, source.read_bytes(), stamp)
            refreshed.append("auth.json")

    scrubbed: tuple[str, ...] = ()
    source = root / ".env"
    if source.is_file():
        text, scrubbed = scrub_env_text(_decode(source.read_bytes(), source))
        target = home / ".env"
        stamp = source.stat()
        if _mtime(target) != stamp.st_mtime_ns or _differs(target, text):
            _write_whole(target, text.encode("utf-8"), stamp)
            refreshed.append(".env")

    for name in LINKED_FILES:
        if (root / name).exists() and _link(home / name, root / name):
            refreshed.append(name)

    roots = skill_roots(root, served)
    wanted: dict[str, Path] = {}  # relative path -> skill directory
    names: dict[str, str] = {}  # skill name -> relative path that holds it
    clashes: list[tuple[str, str]] = []
    for owner, skills in roots:
        for relative, directory in iter_skills(skills):
            name = directory.name
            if name in names:
                clashes.append((relative, owner))
                continue
            names[name] = relative
            wanted[relative] = directory
    skills_dir = home / "skills"
    root_dirs = [root / "skills", root / "profiles"]  # links this made point here, served now or before
    kept_local: list[str] = []
    for entry in _walk(skills_dir):
        relative = entry.relative_to(skills_dir).as_posix()
        if entry.is_symlink():
            if relative in wanted and _points_at(entry, wanted[relative]):
                continue
            if _under(entry, root_dirs) or not entry.exists():
                entry.unlink()  # a link this made: its skill went, moved, or lost its name to the root's
                refreshed.append(f"skills/{relative} (removed)")
            else:
                kept_local.append(relative)  # the person's own link, elsewhere
                _shadow(relative, wanted, names)
        elif (entry / SKILL_FILE).is_file():
            kept_local.append(relative)  # a skill the person put in the TUI home itself
            _shadow(relative, wanted, names)
    for relative, destination in wanted.items():
        (skills_dir / relative).parent.mkdir(parents=True, exist_ok=True)
        if _link(skills_dir / relative, destination):
            refreshed.append(f"skills/{relative}")
    for directory in sorted((p for p in skills_dir.rglob("*") if p.is_dir() and not p.is_symlink()), reverse=True):
        try:
            directory.rmdir()  # a category left empty by the links that went; a non-empty one is kept
        except OSError:
            pass

    plugin = root / "plugins" / PLUGIN_NAME
    if plugin.is_dir() and _link(home / "plugins" / PLUGIN_NAME, plugin):
        refreshed.append(f"plugins/{PLUGIN_NAME}")

    built = TuiHome(
        path=home, root=root, served=served, skills=tuple(sorted({*wanted, *kept_local})),
        clashes=tuple(clashes), kept_local=tuple(sorted(kept_local)), scrubbed=scrubbed, refreshed=tuple(refreshed),
        overwritten=tuple(overwritten), config_platform_credentials=platform_credentials,
    )
    marker = {
        "schema_version": MARKER_SCHEMA, "root": str(root), "served": list(served), "skills": list(built.skills),
        "clashes": [list(pair) for pair in clashes], "kept_local": list(built.kept_local), "scrubbed": list(scrubbed),
        "config_platform_credentials": list(platform_credentials),
    }
    atomic_write_json(home / MARKER_FILE, marker, private=True)
    return built


def _shadow(relative: str, wanted: dict[str, Path], names: dict[str, str]) -> None:
    """A local entry at `relative` stands for the skill of that name: the union's copy of it is not linked."""
    name = relative.rsplit("/", 1)[-1]
    held = names.get(name)
    if held is not None:
        wanted.pop(held, None)
        names[name] = relative


def _walk(skills_dir: Path) -> list[Path]:
    """Every entry under the TUI home's `skills/`, links and skill directories, deepest first; nothing is followed."""
    found: list[Path] = []
    pending = [skills_dir]
    while pending:
        directory = pending.pop()
        try:
            entries = sorted(directory.iterdir(), key=lambda p: p.name)
        except OSError:
            continue
        for entry in entries:
            if entry.name.startswith("."):
                continue
            if entry.is_symlink() or (entry / SKILL_FILE).is_file():
                found.append(entry)
            elif entry.is_dir():
                pending.append(entry)
    return found


def _decode(data: bytes, source: Path) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError(f"{source} is not UTF-8 text ({error.reason} at byte {error.start})") from None


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
    config_platform_credentials: tuple[str, ...]  # `platforms.*` credentials the marker recorded in the root config
    gateway_live: bool
    gateway_pid: int | None
    platforms: tuple[str, ...]  # adapters the TUI runtime's gateway reports connected: never expected

    @property
    def built(self) -> bool:
        return bool(self.built_from)


def tui_home_status(omh_home: Path, runtime: str | None) -> TuiHomeStatus:
    """The TUI home as it is now, for the report surfaces; `runtime` is the saved choice (`read_runtime_choice`).
    Read-only; a home that cannot be read reads as not built."""
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
    broken = tuple(
        entry.relative_to(home / "skills").as_posix() for entry in _walk(home / "skills")
        if entry.is_symlink() and not entry.exists()
    ) if exists else ()
    messaging: tuple[str, ...] = ()
    if (home / ".env").is_file():
        try:
            _, messaging = scrub_env_text((home / ".env").read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            messaging = ()
    gateway = read_gateway(home) if exists else None
    live = bool(gateway is not None and gateway.live)
    return TuiHomeStatus(
        runtime=runtime or "shared", home=home, exists=exists, built_from=str(marker.get("root") or ""),
        served=_strings(marker.get("served")),
        skill_count=len(_strings(marker.get("skills"))),
        clash_count=len(marker.get("clashes")) if isinstance(marker.get("clashes"), list) else 0,
        broken_links=broken, messaging_names=messaging,
        config_platform_credentials=_strings(marker.get("config_platform_credentials")),
        gateway_live=live,
        gateway_pid=gateway.pid if live else None,
        platforms=tuple(p.name for p in gateway.platforms if p.current and p.state == "connected") if live else (),
    )


def _strings(value: object) -> tuple[str, ...]:
    return tuple(str(item) for item in value) if isinstance(value, list) else ()
