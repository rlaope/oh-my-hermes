"""`omh theme` -- list, select, and report the OMH TUI colour theme.

Selection is Hermes-side: the only thing this group writes is `display.skin`
in the Hermes config, and the only thing it installs are the shipped skin
YAMLs OMH already manages. It never patches Hermes and never restarts one --
Hermes reads its skin at start, so a change lands on the next session.

Running `omh theme use <name>` IS the explicit consent the managed-artifact
rule asks for, which is why it takes the forcing `activate_omh_skin` path
rather than the unset-only `ensure_omh_skin` default writer.

`omh theme repair` follows the same consent rule for the other direction: it
adopts a theme file OMH does not own, so the bare form only reports and a
theme name (or `--all`) is the accept. Nothing else in the product may call
the repair path.

Plain text is the default and `--json` is the opt-in, matching every other
polled surface in this package.
"""

from __future__ import annotations

import argparse

from ..installer import OmhError
from ..install.config_adapter import (
    ConfigChange,
    activate_omh_skin,
    display_skin_selection,
    read_config,
    update_config,
)
from ..skin_pack import (
    SKIN_THEMES,
    SkinTheme,
    install_skin,
    installed_skin_report,
    is_omh_skin_name,
    repair_skins,
    theme_for_name,
    theme_for_skin_name,
    theme_names,
)
from .common import _paths, _print_json, _wants_json
from .language import LANGUAGE_CODES, language_from_env, normalize_language, tr
from .theme_picker import pick_theme_interactively, picker_available

# From `quickstart`, not `setup`: importing the parser module back here would
# close an import cycle, exactly as `capability_policy` documents.
from .quickstart import _color, _use_color

THEME_LIST_SCHEMA_VERSION = "omh_theme_list/v1"
THEME_CHANGE_SCHEMA_VERSION = "omh_theme_change/v1"
THEME_STATUS_SCHEMA_VERSION = "omh_theme_status/v1"
THEME_REPAIR_SCHEMA_VERSION = "omh_theme_repair/v1"


def _language(args: argparse.Namespace) -> str:
    raw = getattr(args, "language", None)
    try:
        return normalize_language(raw) if raw else language_from_env()
    except ValueError as exc:
        raise OmhError(str(exc)) from exc


def _restart_note(language: str) -> str:
    # Deliberately the verdict copy setup/update already print: a theme change
    # and a fresh install land the same way -- next Hermes start.
    return tr(language, "tui_verdict_ready")


def _theme_row(theme: SkinTheme, active_skin: str, states: dict[str, str]) -> dict[str, object]:
    return {
        "name": theme.short_name,
        "skin": theme.skin_name,
        "summary": theme.summary,
        "default": theme.skin_name == SKIN_THEMES[0].skin_name,
        "active": theme.skin_name == active_skin,
        "install_state": states.get(theme.skin_name, "missing"),
    }


def _theme_report(args: argparse.Namespace) -> dict[str, object]:
    paths = _paths(args)
    config_text = read_config(paths.hermes_config_path)
    active_skin = display_skin_selection(config_text)
    states = {entry["skin"]: entry["state"] for entry in installed_skin_report(paths.hermes_home)}
    active_theme = theme_for_skin_name(active_skin)
    return {
        "active_skin": active_skin,
        "active_theme": active_theme.short_name if active_theme else "",
        "active_is_omh": is_omh_skin_name(active_skin),
        # An unset `display.skin` is Hermes resolving its own default, which is
        # neither an OMH theme nor a foreign one; say so instead of guessing.
        "active_is_unset": not active_skin,
        "config_path": str(paths.hermes_config_path),
        "skins_dir": str(paths.hermes_home / "skins"),
        "themes": [_theme_row(theme, active_skin, states) for theme in SKIN_THEMES],
        # Named separately from the per-theme rows so the hint that makes
        # `omh theme repair` findable has one thing to test, in both the text
        # and the JSON surface.
        "unmanaged_themes": [
            theme.short_name for theme in SKIN_THEMES if states.get(theme.skin_name) == "unmanaged"
        ],
    }


def cmd_theme_list(args: argparse.Namespace) -> int:
    """Bare `omh theme` picks interactively; `omh theme list` always prints.

    The split is deliberate: `list` is the scriptable surface and must stay
    byte-predictable, while the bare form is the one a person types when they
    want to SEE the palettes. `--json` and any non-terminal end degrade the
    bare form back to the same plain listing.
    """
    if getattr(args, "theme_command", None) is None and not _wants_json(args) and picker_available():
        return _pick_theme(args)
    payload = {"schema_version": THEME_LIST_SCHEMA_VERSION, **_theme_report(args)}
    if _wants_json(args):
        _print_json(payload)
    else:
        _print_theme_list(payload)
    return 0


def _pick_theme(args: argparse.Namespace) -> int:
    report = _theme_report(args)
    chosen = pick_theme_interactively(
        SKIN_THEMES,
        str(report["active_skin"]),
        use_color=_use_color(),
    )
    if chosen is None:
        print("Cancelled; display.skin was not changed.")
        return 0
    _print_theme_change(_apply_theme(args, chosen, dry_run=False))
    return 0


def cmd_theme_status(args: argparse.Namespace) -> int:
    language = _language(args)
    report = _theme_report(args)
    payload = {
        "schema_version": THEME_STATUS_SCHEMA_VERSION,
        **report,
        "managed": installed_skin_report(_paths(args).hermes_home),
        "restart_note": _restart_note(language),
        "language": language,
    }
    if _wants_json(args):
        _print_json(payload)
    else:
        _print_theme_status(payload)
    return 0


def cmd_theme_use(args: argparse.Namespace) -> int:
    requested = str(getattr(args, "name", "") or "")
    theme = theme_for_name(requested)
    if theme is None:
        print(
            f"omh: unknown theme {requested!r}; valid names are {', '.join(theme_names())} "
            "(or the full skin name, for example omh-amber)."
        )
        return 2

    payload = _apply_theme(args, theme, dry_run=bool(getattr(args, "dry_run", False)))
    if _wants_json(args):
        _print_json(payload)
    else:
        _print_theme_change(payload)
    return 0


def cmd_theme_repair(args: argparse.Namespace) -> int:
    """Report unmanaged theme files, and adopt the ones explicitly named.

    The invocation IS the consent. Nothing on disk distinguishes a theme file
    OMH wrote from one a person wrote -- a manifest that went stale while the
    template also moved on leaves ours looking exactly like theirs -- so the
    bare form never writes and a name (or `--all`) is the accept.
    """
    language = _language(args)
    paths = _paths(args)
    requested = str(getattr(args, "name", "") or "")
    every = bool(getattr(args, "all", False))
    dry_run = bool(getattr(args, "dry_run", False))
    if requested and every:
        print("omh: pass a theme name or --all, not both.")
        return 2
    theme = theme_for_name(requested) if requested else None
    if requested and theme is None:
        print(
            f"omh: unknown theme {requested!r}; valid names are {', '.join(theme_names())} "
            "(or the full skin name, for example omh-amber)."
        )
        return 2
    if every:
        adopt = frozenset(candidate.filename for candidate in SKIN_THEMES)
    elif theme is not None:
        adopt = frozenset({theme.filename})
    else:
        adopt = frozenset()
    result = repair_skins(paths.hermes_home, adopt=adopt, dry_run=dry_run)
    payload = {
        "schema_version": THEME_REPAIR_SCHEMA_VERSION,
        "mode": "repair" if adopt else "report",
        "requested": theme.short_name if theme is not None else "",
        "all": every,
        "dry_run": dry_run,
        "status": result["status"],
        "skins_dir": str(result["path"]),
        "themes": result["skins"],
        "restart_note": _restart_note(language),
        "language": language,
    }
    if _wants_json(args):
        _print_json(payload)
    else:
        _print_theme_repair(payload)
    return 0


def _apply_theme(args: argparse.Namespace, theme: SkinTheme, *, dry_run: bool) -> dict[str, object]:
    """The one selection path. `theme use` and the picker both land here.

    Keeping it single means the picker cannot drift into a second, laxer way of
    writing `display.skin` -- same forcing activate, same install, same notice.
    """
    language = _language(args)
    paths = _paths(args)
    # Only a binding for the `nonlocal` below; the mutation runs at least
    # once on every path that reaches it, including `--dry-run`, so this
    # value is always replaced before anything reads it.
    previous_skin = ""

    def _select(config_text: str) -> ConfigChange:
        # Re-read on a retry means re-deciding: another writer's file is the
        # one this selection has to land on, and the reported previous skin
        # has to describe the file that was actually replaced.
        nonlocal previous_skin
        previous_skin = display_skin_selection(config_text)
        return activate_omh_skin(config_text, theme.skin_name)

    # Installing is idempotent and offline, so a `use` on a machine whose skins
    # directory was never refreshed still ends with the file Hermes needs.
    install = install_skin(paths.hermes_home, dry_run=dry_run)
    # A `ConfigWriteRefused` propagates: it is an `OmhError`, so the CLI
    # already reports it as one `omh: ...` line and exit 2. Catching it here
    # to re-raise the same class only lost the subclass that names the cause.
    change = update_config(
        paths.hermes_config_path, _select, omh_home=paths.omh_home, dry_run=dry_run
    )

    return {
        "schema_version": THEME_CHANGE_SCHEMA_VERSION,
        "theme": theme.short_name,
        "skin": theme.skin_name,
        "previous_skin": previous_skin,
        "already_active": previous_skin == theme.skin_name,
        "changed": change.changed and not dry_run,
        "message": change.message,
        "dry_run": dry_run,
        "config_path": str(paths.hermes_config_path),
        "install": install,
        "restart_note": _restart_note(language),
        "reverse_command": (
            f"omh theme use {theme_for_skin_name(previous_skin).short_name}"
            if theme_for_skin_name(previous_skin) is not None
            else f"omh theme use {SKIN_THEMES[0].short_name}"
        ),
        "language": language,
    }


def _active_line(payload: dict[str, object]) -> str:
    if payload.get("active_is_unset"):
        return "  Active: Hermes default (display.skin is unset)."
    if payload.get("active_is_omh"):
        return f"  Active: {payload.get('active_theme', '')} (display.skin: {payload.get('active_skin', '')})"
    return f"  Active: {payload.get('active_skin', '')} - not an OMH theme; your own skin choice is kept."


def _repair_hint(payload: dict[str, object]) -> str:
    """The one line that makes `omh theme repair` findable, when it applies.

    Printed only while something is actually unmanaged. An always-on hint would
    train people to skip the Next block, and a hand-authored skin is a valid
    end state rather than a fault to nag about.
    """
    names = payload.get("unmanaged_themes")
    if not isinstance(names, list) or not names:
        return ""
    joined = ", ".join(str(name) for name in names)
    return (
        f"  Unmanaged: {joined} - OMH leaves these alone and never updates them. "
        "Run `omh theme repair` to see what adopting them would change."
    )


def _print_theme_list(payload: dict[str, object]) -> None:
    use_color = _use_color()
    print(_color("OMH TUI themes", "1;36", use_color))
    themes = payload.get("themes", [])
    if isinstance(themes, list):
        for theme in themes:
            if not isinstance(theme, dict):
                continue
            mark = "*" if theme.get("active") else " "
            suffix = " (default)" if theme.get("default") else ""
            print(f"  [{mark}] {str(theme.get('name', '')):<8} {theme.get('summary', '')}{suffix}")
    print(_color("Current", "1;32", use_color))
    print(_active_line(payload))
    print(_color("Next", "1;32", use_color))
    print("  Switch with `omh theme use <name>`; the new look applies on the next Hermes start.")
    hint = _repair_hint(payload)
    if hint:
        print(hint)


def _print_theme_status(payload: dict[str, object]) -> None:
    use_color = _use_color()
    print(_color("OMH theme status", "1;36", use_color))
    print(_active_line(payload))
    print(f"  Hermes config: {payload.get('config_path', '')}")
    print(f"  Skins directory: {payload.get('skins_dir', '')}")
    print(_color("Installed theme files", "1;32", use_color))
    managed = payload.get("managed", [])
    if isinstance(managed, list):
        for entry in managed:
            if isinstance(entry, dict):
                print(f"  {str(entry.get('theme', '')):<8} {entry.get('filename', '')} - {entry.get('state', '')}")
    print(_color("Next", "1;32", use_color))
    print(f"  {payload.get('restart_note', '')}")
    hint = _repair_hint(payload)
    if hint:
        print(hint)


def _print_theme_change(payload: dict[str, object]) -> None:
    use_color = _use_color()
    theme = str(payload.get("theme", ""))
    print(_color(f"OMH theme: {theme}", "1;36", use_color))
    if payload.get("dry_run"):
        print(f"  Dry run: display.skin would become {payload.get('skin', '')}; nothing was written.")
    elif payload.get("already_active"):
        print(f"  No change: {theme} is already active.")
    elif payload.get("changed"):
        print(f"  display.skin is now {payload.get('skin', '')}.")
    else:
        print(f"  Not applied: {payload.get('message', '')}")
    print(_color("Next", "1;32", use_color))
    print(f"  {payload.get('restart_note', '')}")
    print(f"  Reverse: {payload.get('reverse_command', '')}")


# What each repair status means in one human phrase. Kept out of the payload
# on purpose: the JSON carries `state`/`status` for machines, and prose that
# consumers might start parsing is prose that can never be reworded.
_REPAIR_NOTES: dict[str, str] = {
    "managed": "managed; untouched",
    "unmanaged": "unmanaged; NOT adopted (name it, or pass --all, to accept)",
    "missing": "missing; NOT installed (name it, or pass --all, to install)",
    "would_repair": "unmanaged; WOULD be replaced with the shipped file",
    "would_install": "missing; WOULD be installed",
    "repaired": "repaired; replaced with the shipped file",
    "installed": "installed",
}
_REPAIR_WRITTEN = ("repaired", "installed")


def _print_theme_repair(payload: dict[str, object]) -> None:
    """Show the before/after of every file BEFORE anything destructive lands.

    Digest pair plus the palette tokens that move, per file. A person accepting
    an overwrite of a file OMH cannot prove it wrote deserves to see exactly
    what they are trading away first.
    """
    use_color = _use_color()
    print(_color("OMH theme repair", "1;36", use_color))
    print(f"  Skins directory: {payload.get('skins_dir', '')}")
    print(_color("Theme files", "1;32", use_color))
    written = 0
    pending = 0
    themes = payload.get("themes", [])
    if isinstance(themes, list):
        for entry in themes:
            if not isinstance(entry, dict):
                continue
            status = str(entry.get("status", ""))
            if status in _REPAIR_WRITTEN:
                written += 1
            elif status in ("unmanaged", "missing"):
                pending += 1
            note = _REPAIR_NOTES.get(status, status)
            print(f"  {str(entry.get('theme', '')):<8} {str(entry.get('filename', '')):<17} - {note}")
            if status == "managed":
                continue
            before = str(entry.get("before_sha256", "")) or "(absent)"
            print(f"      sha256 {before[:16]} -> {str(entry.get('after_sha256', ''))[:16]}")
            changes = entry.get("palette_changes")
            if isinstance(changes, list):
                for change in changes:
                    if isinstance(change, dict):
                        old = str(change.get("before", "")) or "(unset)"
                        new = str(change.get("after", "")) or "(removed)"
                        print(f"      {change.get('key', '')}: {old} -> {new}")
    print(_color("Next", "1;32", use_color))
    if payload.get("dry_run"):
        print("  Dry run: nothing was written. Re-run without --dry-run to accept.")
    elif written:
        print(f"  Adopted {written} theme file(s); future updates now reach them.")
        print(f"  {payload.get('restart_note', '')}")
    elif pending:
        print("  Nothing was written. Accept with `omh theme repair <name>` or `omh theme repair --all`.")
    else:
        print("  Every shipped theme file is managed; there is nothing to repair.")


def _add_theme_commands(sub) -> None:
    theme = sub.add_parser(
        "theme",
        help="List, select, or report the OMH TUI colour theme.",
    )
    theme.add_argument("--json", action="store_true", help="Print the full machine-readable theme listing.")
    theme.add_argument("--language", default=None, help=f"Human output language ({', '.join(LANGUAGE_CODES)}).")
    # Bare `omh theme` lists: the question people ask first is "what can I pick?".
    theme.set_defaults(func=cmd_theme_list, theme_command=None)
    theme_sub = theme.add_subparsers(dest="theme_command")

    theme_list = theme_sub.add_parser("list", help="Show every shipped theme and mark the active one.")
    _add_shared_theme_arguments(theme_list, "Print the full machine-readable theme listing.")
    theme_list.set_defaults(func=cmd_theme_list)

    theme_use = theme_sub.add_parser(
        "use",
        help="Select one theme by writing display.skin. Applies on the next Hermes start.",
    )
    theme_use.add_argument("name", help=f"Theme short name ({', '.join(theme_names())}) or full skin name.")
    theme_use.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the selection without writing the Hermes config or installing skin files.",
    )
    _add_shared_theme_arguments(theme_use, "Print the full machine-readable change payload.")
    theme_use.set_defaults(func=cmd_theme_use)

    theme_repair = theme_sub.add_parser(
        "repair",
        help="Report theme files OMH does not own, and adopt the ones you name.",
    )
    theme_repair.add_argument(
        "name",
        nargs="?",
        default="",
        help=f"Theme to adopt ({', '.join(theme_names())}) or full skin name. Omit to only report.",
    )
    theme_repair.add_argument("--all", action="store_true", help="Adopt every unmanaged theme file.")
    theme_repair.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what adopting would change without writing anything.",
    )
    _add_shared_theme_arguments(theme_repair, "Print the full machine-readable repair payload.")
    theme_repair.set_defaults(func=cmd_theme_repair)

    theme_status = theme_sub.add_parser(
        "status",
        help="Show the active skin, whether OMH owns it, and the managed theme files on disk.",
    )
    _add_shared_theme_arguments(theme_status, "Print the full machine-readable status payload.")
    theme_status.set_defaults(func=cmd_theme_status)


def _add_shared_theme_arguments(parser: argparse.ArgumentParser, json_help: str) -> None:
    """Add `--json`/`--language` to a leaf so either position accepts them.

    `argparse.SUPPRESS` is the point: without it a subparser's own default
    overwrites the value the group parser already stored, so `omh theme --json
    list` would silently print plain text.
    """
    parser.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=json_help)
    parser.add_argument(
        "--language",
        default=argparse.SUPPRESS,
        help=f"Human output language ({', '.join(LANGUAGE_CODES)}).",
    )
