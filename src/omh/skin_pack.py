"""The OMH themes: the palettes the OMH TUI paints with, and the choice of one.

Each theme is a Hermes skin document shipped in ``omh/skins/``, read straight
off its YAML (`skin_colors`), so the OMH TUI and the pickers paint with what a
theme declares. The choice lives under the OMH home (`theme_store_path`) and
`effective_theme` is the one order every reader follows. The launch look the
OMH TUI opens with (`read_launch_choice`) is saved in the same record.

Earlier versions also installed every theme file into ``$HERMES_HOME/skins/``
and selected one through `display.skin`, so bare `hermes` wore it.
`uninstall_skin` takes those files back: setup and update through the display
release, uninstall on its own. It removes only a file OMH can prove it wrote,
by manifest record or, until that config's display release is recorded, by
matching the shipped bytes, and never the file `display.skin` still names;
anything else is the person's and stays.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
import hashlib
from importlib import resources
import json
import os
from pathlib import Path
import secrets

from .system.local_store import atomic_write_json

SKIN_NAME = "omh"
SKIN_FILENAME = "omh.yaml"
MANIFEST_FILENAME = ".omh-skin.manifest.json"
_MANIFEST_SCHEMA = "omh_skin_manifest/v2"
_LEGACY_MANIFEST_SCHEMA = "omh_skin_manifest/v1"
THEME_STORE_SCHEMA = "omh_tui_theme/v1"


@dataclass(frozen=True)
class SkinTheme:
    """One shipped palette: its user-facing short name and its Hermes skin name.

    Two names on purpose. ``skin_name`` is what goes into `display.skin` and
    must stay namespaced so it never collides with a Hermes built-in or another
    product's skin; ``short_name`` is what a person types and reads.
    """

    short_name: str
    skin_name: str
    filename: str
    summary: str


SKIN_THEMES: tuple[SkinTheme, ...] = (
    SkinTheme("sky", "omh", "omh.yaml", "Sky turquoise on deep teal. The OMH default."),
    SkinTheme("amber", "omh-amber", "omh-amber.yaml", "Amber gold on deep bronze."),
    SkinTheme("crimson", "omh-crimson", "omh-crimson.yaml", "Ember red-orange on deep crimson."),
    SkinTheme("mono", "omh-mono", "omh-mono.yaml", "Neutral grayscale with white accents."),
)

_SKIN_FILENAMES: tuple[str, ...] = tuple(theme.filename for theme in SKIN_THEMES)

# `default` is not a theme, it is a way of saying "the shipped default"; both
# aliases resolve to the same skin the fresh-config path writes.
_THEME_ALIASES: dict[str, str] = {"default": "sky", "omh-sky": "sky"}


class SkinInstallError(RuntimeError):
    """The managed Hermes skin destination is unsafe."""


def available_skins() -> tuple[str, ...]:
    """Hermes skin names for every theme this build ships, in display order."""
    return tuple(theme.skin_name for theme in SKIN_THEMES)


def default_theme() -> SkinTheme:
    return SKIN_THEMES[0]


def theme_for_name(value: str) -> SkinTheme | None:
    """Resolve a short name, an alias, or a full skin name to one theme."""
    candidate = value.strip().lower()
    candidate = _THEME_ALIASES.get(candidate, candidate)
    for theme in SKIN_THEMES:
        if candidate in (theme.short_name, theme.skin_name):
            return theme
    return None


def theme_for_skin_name(value: str) -> SkinTheme | None:
    """Resolve a `display.skin` value, matching skin names only.

    Distinct from `theme_for_name` on purpose: config values are exact, and a
    foreign skin literally named `amber` must not be read as our theme.
    """
    candidate = value.strip()
    for theme in SKIN_THEMES:
        if candidate == theme.skin_name:
            return theme
    return None


def is_omh_skin_name(value: str) -> bool:
    """True when `display.skin` names a skin OMH ships, not a foreign one.

    The predicate every "is the OMH identity active?" question goes through.
    Comparing against the single default name instead used to read an operator
    who chose `omh-crimson` as an operator who chose `ares`.
    """
    return value.strip() in available_skins()


def theme_names() -> tuple[str, ...]:
    """User-facing short names, for validation messages."""
    return tuple(theme.short_name for theme in SKIN_THEMES)


def theme_store_path(omh_home: Path) -> Path:
    """Where the OMH TUI theme choice lives: under the OMH home, never Hermes'."""
    return Path(omh_home) / "tui" / "theme.json"


def _theme_store_record(omh_home: Path) -> dict[str, object]:
    """The saved record under the OMH home, or {} when there is none this module wrote (unreadable, another schema)."""
    try:
        record = json.loads(theme_store_path(omh_home).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    if not isinstance(record, dict) or record.get("schema_version") != THEME_STORE_SCHEMA:
        return {}
    return record


def read_theme_choice(omh_home: Path) -> SkinTheme | None:
    """The theme saved for this OMH home, or None when none is saved.

    None for anything this module did not write as well (unreadable, another
    schema, an unknown name), so a damaged file costs the person their saved
    choice, never the TUI's start.
    """
    name = _theme_store_record(omh_home).get("theme")
    return theme_for_name(name) if isinstance(name, str) else None


def write_theme_choice(omh_home: Path, theme: SkinTheme) -> Path:
    """Save the theme the OMH TUI opens with; the path it was written to. The launch look saved beside it stays."""
    return _write_theme_store(omh_home, "theme", theme.short_name)


def read_launch_choice(omh_home: Path) -> str | None:
    """The launch look saved for this OMH home (`launch`, beside the theme), as written; None when none is saved.

    The OMH TUI owns the names (`tui.theme.LAUNCH_PRESETS`) and says when a
    saved one is not among them, so the raw text comes back here.
    """
    name = _theme_store_record(omh_home).get("launch")
    return name if isinstance(name, str) else None


def write_launch_choice(omh_home: Path, name: str) -> Path:
    """Save the launch look the OMH TUI opens with; the path it was written to. The theme saved beside it stays."""
    return _write_theme_store(omh_home, "launch", name)


def read_glow_choice(omh_home: Path) -> bool | None:
    """Whether the OMH TUI's working glow is on, as saved for this OMH home (`glow`, beside the theme); None when
    nothing this module wrote says."""
    value = _theme_store_record(omh_home).get("glow")
    return {"on": True, "off": False}.get(value) if isinstance(value, str) else None


def write_glow_choice(omh_home: Path, on: bool) -> Path:
    """Save whether the OMH TUI's working glow is on; the path it was written to. The theme and look stay."""
    return _write_theme_store(omh_home, "glow", "on" if on else "off")


def read_wallpaper_choice(omh_home: Path) -> bool | None:
    """Whether the OMH TUI's living wallpaper (a look's background colour and its moving scene) is on, as saved for
    this OMH home (`wallpaper`, beside the theme); None when nothing this module wrote says."""
    value = _theme_store_record(omh_home).get("wallpaper")
    return {"on": True, "off": False}.get(value) if isinstance(value, str) else None


def write_wallpaper_choice(omh_home: Path, on: bool) -> Path:
    """Save whether the OMH TUI's living wallpaper is on; the path it was written to. The theme, look and glow stay."""
    return _write_theme_store(omh_home, "wallpaper", "on" if on else "off")


# The keys the one writer (`_write_theme_store`) keeps: every write carries the others over.
THEME_STORE_KEYS = ("theme", "launch", "glow", "wallpaper")


def _write_theme_store(omh_home: Path, key: str, value: str) -> Path:
    path = theme_store_path(omh_home)
    kept = {name: _theme_store_record(omh_home).get(name) for name in THEME_STORE_KEYS if name != key}
    record = {"schema_version": THEME_STORE_SCHEMA, **{name: v for name, v in kept.items() if isinstance(v, str)}}
    atomic_write_json(path, {**record, key: value})
    return path


def effective_theme(omh_home: Path | None, hermes_skin: str) -> tuple[SkinTheme, str]:
    """The theme the OMH TUI opens with, and which source decided it.

    One order, read by the TUI and reported by `omh theme`: the choice saved
    under the OMH home (`saved`); else Hermes' own `display.skin` when it
    names an OMH palette (`hermes_skin`), which is the case on an install the
    display release has not reached yet, or when the person picked one for
    Hermes; else the shipped default (`default`). Skin names only, so a
    foreign skin that happens to be called `amber` is not OMH's amber.
    """
    saved = read_theme_choice(omh_home) if omh_home is not None else None
    if saved is not None:
        return saved, "saved"
    named = theme_for_skin_name(hermes_skin)
    if named is not None:
        return named, "hermes_skin"
    return default_theme(), "default"


def skin_payload(name: str = SKIN_NAME) -> bytes:
    theme = theme_for_name(name)
    if theme is None:
        raise SkinInstallError(f"unknown OMH skin: {name}")
    return resources.files("omh.skins").joinpath(theme.filename).read_text(encoding="utf-8").encode()


def colors_from_text(text: str) -> dict[str, str]:
    """The `colors:` block of one skin document, as token -> `#RRGGBB`.

    A deliberately narrow reader rather than a YAML dependency: OMH ships with
    zero runtime dependencies, these documents are ours, and the block is a
    flat two-space mapping of quoted hex strings. Every consumer -- the OMH
    TUI, the theme picker's preview, the model-chain picker -- must paint with
    the palette a theme actually declares, not a copy that drifts from the
    YAML.
    """
    colors: dict[str, str] = {}
    inside = False
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith(" "):
            inside = line.startswith("colors:")
            continue
        if not inside or not line.startswith("  ") or line.startswith("    "):
            continue
        key, separator, raw = line.strip().partition(":")
        value = raw.strip().strip('"')
        if separator and value.startswith("#"):
            colors[key] = value
    return colors


def skin_colors(name: str = SKIN_NAME) -> dict[str, str]:
    """The palette of one shipped theme, read straight off its YAML."""
    return colors_from_text(skin_payload(name).decode("utf-8"))


def logo_from_text(text: str) -> list[tuple[str, str, bool]]:
    """The `banner_logo:` block of one skin document: per row its text, its `#RRGGBB` (or ""), and whether it is bold.

    Each row is Rich markup for Hermes' banner, an opening tag such as
    `[bold #B8F4FF]`, the row, then `[/]`, and the markup is taken off here.
    As narrow a reader as `colors_from_text`: the block is a `|-` literal of
    two-space-indented rows, and a row without a tag keeps its text whole,
    with no colour. The text is returned as the file has it; a reader that
    writes it to a terminal takes out what is not printable.
    """
    rows: list[tuple[str, str, bool]] = []
    inside = False
    for line in text.splitlines():
        if not line.startswith(" "):
            inside = line.startswith("banner_logo:")
            continue
        if not inside or not line.startswith("  "):
            continue
        row, colour, bold = line[2:], "", False
        if row.startswith("[") and "]" in row:
            tag, row = row[1:].split("]", 1)
            words = tag.split()
            colour = next((word for word in words if word.startswith("#") and hex_to_rgb(word)), "")
            bold = "bold" in words
        rows.append((row.removesuffix("[/]"), colour, bold))
    return rows


def skin_logo(name: str = SKIN_NAME) -> list[tuple[str, str, bool]]:
    """The block logo of one shipped theme, read straight off its YAML."""
    return logo_from_text(skin_payload(name).decode("utf-8"))


def hex_to_rgb(value: str) -> tuple[int, int, int] | None:
    """`#RRGGBB` -> channel triple, or None when the token is not a plain hex."""
    text = value.strip().lstrip("#")
    if len(text) != 6:
        return None
    try:
        return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)
    except ValueError:
        return None


def _reject_symlink_path(path: Path) -> None:
    current = path
    while True:
        if current.is_symlink():
            raise SkinInstallError(f"refusing symlinked skin path: {current}")
        if current == current.parent:
            return
        current = current.parent


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}-{secrets.token_hex(8)}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
        os.replace(temporary, path)
    finally:
        if temporary.exists() and not temporary.is_symlink():
            temporary.unlink()


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _read_manifest_records(manifest: Path) -> dict[str, str]:
    """Filename -> sha256 for every file the manifest claims OMH wrote.

    Reads both schema versions. A v1 manifest predates multiple themes and
    described exactly one file, so it migrates to the single-entry map rather
    than being discarded — discarding it would make an already-installed
    `omh.yaml` look user-authored and freeze it forever.
    """
    try:
        if manifest.is_symlink() or not manifest.is_file():
            return {}
        record = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(record, dict):
        return {}
    schema = record.get("schema_version")
    if schema == _LEGACY_MANIFEST_SCHEMA:
        filename = record.get("filename")
        digest = record.get("sha256")
        if isinstance(filename, str) and isinstance(digest, str):
            return {filename: digest}
        return {}
    if schema != _MANIFEST_SCHEMA:
        return {}
    files = record.get("files")
    if not isinstance(files, dict):
        return {}
    return {
        str(name): str(entry.get("sha256", ""))
        for name, entry in files.items()
        if isinstance(entry, dict) and isinstance(entry.get("sha256"), str)
    }


def _manifest_document(records: dict[str, str]) -> bytes:
    return json.dumps(
        {
            "schema_version": _MANIFEST_SCHEMA,
            "files": {name: {"sha256": digest} for name, digest in sorted(records.items())},
        },
        sort_keys=True,
    ).encode()


def _is_managed_file(destination: Path, records: dict[str, str], payload: bytes, *, manifest_only: bool) -> bool:
    """Does OMH own this file -- by manifest record, or by being our own content?

    Two proofs, either sufficient. The manifest record is the primary one. The
    second exists because a manifest can fall behind the file it describes: on
    a real install the owner's `omh.yaml` was byte-identical to the shipped
    template while the v1 manifest still recorded an older sha, because some
    past update refreshed the file without refreshing the record. Record-only
    ownership read that machine as user-authored, which would have frozen the
    skin as `kept_unmanaged` forever and meant no future template change ever
    reached it.

    Matching the current template is a safe second proof precisely because the
    bytes are ours: removing the file cannot destroy anything a user wrote,
    since the package still ships the same bytes. A file that matches
    neither the record nor the template is genuinely user-edited and stays
    kept_unmanaged.

    `manifest_only` drops the second proof, once the config's display
    release is recorded. That pass removed every file either proof covered
    and deleted the manifest it emptied, so a shipped-bytes file that
    appears afterwards is one the person put there, typically to give
    Hermes an OMH palette again, and the template match would take it on
    every update.
    """
    try:
        digest = _sha256(destination.read_bytes())
    except OSError:
        return False
    if records.get(destination.name) == digest:
        return True
    return not manifest_only and digest == _sha256(payload)


_UNINSTALL_STATUS_ORDER = ("removed", "would_remove", "kept_unmanaged", "kept_selected", "absent")


def _aggregate_status(statuses: list[str], order: tuple[str, ...]) -> str:
    for candidate in order:
        if candidate in statuses:
            return candidate
    return order[-1]


def uninstall_skin(
    hermes_home: Path,
    *,
    dry_run: bool = False,
    keep: Collection[str] = (),
    manifest_only: bool = False,
) -> dict[str, object]:
    """Remove only the theme files OMH owns -- by record, or by being our bytes.

    The installer earlier versions ran adopted and refreshed a file on either
    proof, so either proof is what lets this take it away again; a machine
    with a stale manifest would otherwise keep orphaned skin files.
    `manifest_only` limits it to the record (see `_is_managed_file`).

    `keep` names skins the Hermes config still selects. Their files stay
    (`kept_selected`) with their manifest records, whoever wrote them:
    removing one would leave Hermes naming a skin that is not there.
    """
    destination_dir = hermes_home / "skins"
    manifest = destination_dir / MANIFEST_FILENAME
    if not any(os.path.lexists(destination_dir / name) for name in (MANIFEST_FILENAME, *_SKIN_FILENAMES)):
        # Nothing under an OMH name, so nothing to remove and nothing to
        # refuse: a `skins/` symlinked from a dotfiles repo is the person's.
        # Looked up by name only; no entry is opened or followed.
        return {
            "status": "absent",
            "path": str(destination_dir),
            "skins": [
                {
                    "skin": theme.skin_name,
                    "filename": theme.filename,
                    "status": "absent",
                    "path": str(destination_dir / theme.filename),
                }
                for theme in SKIN_THEMES
            ],
        }
    _reject_symlink_path(destination_dir)
    _reject_symlink_path(manifest)
    records = _read_manifest_records(manifest)
    remaining = dict(records)
    entries: list[dict[str, str]] = []
    for theme in SKIN_THEMES:
        destination = destination_dir / theme.filename
        _reject_symlink_path(destination)
        if not destination.exists():
            remaining.pop(theme.filename, None)
            entries.append(
                {
                    "skin": theme.skin_name,
                    "filename": theme.filename,
                    "status": "absent",
                    "path": str(destination),
                }
            )
            continue
        if theme.skin_name in keep:
            entries.append(
                {
                    "skin": theme.skin_name,
                    "filename": theme.filename,
                    "status": "kept_selected",
                    "path": str(destination),
                }
            )
            continue
        if not _is_managed_file(destination, records, skin_payload(theme.skin_name), manifest_only=manifest_only):
            entries.append(
                {
                    "skin": theme.skin_name,
                    "filename": theme.filename,
                    "status": "kept_unmanaged",
                    "path": str(destination),
                }
            )
            continue
        if not dry_run:
            destination.unlink()
            remaining.pop(theme.filename, None)
        entries.append(
            {
                "skin": theme.skin_name,
                "filename": theme.filename,
                "status": "would_remove" if dry_run else "removed",
                "path": str(destination),
            }
        )
    if not dry_run and manifest.exists():
        if remaining:
            _atomic_write_bytes(manifest, _manifest_document(remaining))
        else:
            manifest.unlink()
    return {
        "status": _aggregate_status([entry["status"] for entry in entries], _UNINSTALL_STATUS_ORDER),
        "path": str(destination_dir),
        "skins": entries,
    }
