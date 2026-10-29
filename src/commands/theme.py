"""`omh theme` -- list, select, and report the OMH TUI colour theme.

The choice lives under the OMH home (`<omh_home>/tui/theme.json`, resolved
the way every other command resolves the store, so a profile that names its
own store keeps its own theme), and the OMH TUI that bare `omh` opens is its
reader. Nothing here writes Hermes' config or installs anything into the
Hermes home: bare `hermes` is stock Hermes and keeps whatever skin Hermes
itself is set to. The TUI paints from the palettes shipped inside the
package, so no skin file has to exist anywhere. `display.skin` is read, for
the report only, because the TUI falls back to an OMH palette it names
(`skin_pack.effective_theme`).

`omh theme use <name>` is the one writer of the theme, and running it is the
consent; `omh theme glow on|off` writes the OMH TUI's working glow choice in
the same record, as `/glow` inside the TUI does.
The TUI reads the choice when it opens, so a change lands on the next
`omh`; `/theme` inside the TUI switches the open session only.

Plain text is the default and `--json` is the opt-in, matching every other
polled surface in this package.
"""

from __future__ import annotations

import argparse
import sys

from ..installer import OmhError
from ..install.config_adapter import display_skin_selection, read_config
from ..skin_pack import (
    SKIN_THEMES,
    SkinTheme,
    default_theme,
    effective_theme,
    read_glow_choice,
    read_theme_choice,
    theme_for_name,
    theme_names,
    theme_store_path,
    write_glow_choice,
    write_theme_choice,
)
from .common import _paths, _print_json, _wants_json
from .language import LANGUAGE_CODES, language_from_env, normalize_language, tr
from .theme_picker import pick_theme_interactively, picker_available

# From `quickstart`, not `setup`: importing the parser module back here would
# close an import cycle, exactly as `capability_policy` documents.
from .quickstart import _color, _use_color

THEME_LIST_SCHEMA_VERSION = "omh_theme_list/v2"
THEME_CHANGE_SCHEMA_VERSION = "omh_theme_change/v2"
THEME_STATUS_SCHEMA_VERSION = "omh_theme_status/v2"
THEME_REPAIR_SCHEMA_VERSION = "omh_theme_repair/v2"
THEME_GLOW_SCHEMA_VERSION = "omh_theme_glow/v1"


def _language(args: argparse.Namespace) -> str:
    raw = getattr(args, "language", None)
    try:
        return normalize_language(raw) if raw else language_from_env()
    except ValueError as exc:
        raise OmhError(str(exc)) from exc


def _restart_note(language: str) -> str:
    return tr(language, "theme_restart_note")


def _theme_row(theme: SkinTheme, active: SkinTheme) -> dict[str, object]:
    return {
        "name": theme.short_name,
        "skin": theme.skin_name,
        "summary": theme.summary,
        "default": theme == default_theme(),
        "active": theme == active,
    }


def _theme_report(args: argparse.Namespace) -> dict[str, object]:
    paths = _paths(args)
    # Read, never written: the TUI falls back to an OMH palette Hermes'
    # `display.skin` names, so the report has to read the same key to say
    # what the TUI will actually open with.
    hermes_skin = display_skin_selection(read_config(paths.hermes_config_path))
    active, source = effective_theme(paths.omh_home, hermes_skin)
    return {
        "active_theme": active.short_name,
        "active_skin": active.skin_name,
        "active_source": source,
        "store_path": str(theme_store_path(paths.omh_home)),
        "themes": [_theme_row(theme, active) for theme in SKIN_THEMES],
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
        print("Cancelled; the OMH theme was not changed.")
        return 0
    _print_theme_change(_apply_theme(args, chosen, dry_run=False))
    return 0


def cmd_theme_status(args: argparse.Namespace) -> int:
    language = _language(args)
    payload = {
        "schema_version": THEME_STATUS_SCHEMA_VERSION,
        **_theme_report(args),
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


def _apply_theme(args: argparse.Namespace, theme: SkinTheme, *, dry_run: bool) -> dict[str, object]:
    """The one selection path. `theme use` and the picker both land here."""
    language = _language(args)
    paths = _paths(args)
    previous = read_theme_choice(paths.omh_home)
    # What the TUI would have opened with, which is what undoing this means
    # even when nothing was saved before.
    opened_with = theme_for_name(str(_theme_report(args)["active_theme"])) or default_theme()
    changed = previous != theme and not dry_run
    if changed:
        try:
            write_theme_choice(paths.omh_home, theme)
        except OSError as exc:
            raise OmhError(f"could not save the OMH theme to {theme_store_path(paths.omh_home)}: {exc}") from exc
    return {
        "schema_version": THEME_CHANGE_SCHEMA_VERSION,
        "theme": theme.short_name,
        "skin": theme.skin_name,
        "previous_theme": previous.short_name if previous else "",
        "already_active": previous == theme,
        "changed": changed,
        "dry_run": dry_run,
        "store_path": str(theme_store_path(paths.omh_home)),
        "restart_note": _restart_note(language),
        "reverse_command": f"omh theme use {opened_with.short_name}",
        "language": language,
    }


def cmd_theme_glow(args: argparse.Namespace) -> int:
    """`omh theme glow on|off` saves whether the OMH TUI's working glow is on; alone, reports it."""
    requested = str(getattr(args, "state", "") or "").strip().lower()
    if requested not in ("", "on", "off"):
        print(f"omh: the working glow is on or off, not {requested!r}: `omh theme glow on` or `omh theme glow off`.")
        return 2
    paths = _paths(args)
    saved = read_glow_choice(paths.omh_home)
    on = True if saved is None else saved
    payload: dict[str, object] = {
        "schema_version": THEME_GLOW_SCHEMA_VERSION,
        "glow": "on" if on else "off",
        "source": "default" if saved is None else "saved",
        "changed": False,
        "store_path": str(theme_store_path(paths.omh_home)),
    }
    if requested:
        wanted = requested == "on"
        payload.update(previous="on" if on else "off", glow=requested, source="saved")
        if saved is not wanted:
            try:
                write_glow_choice(paths.omh_home, wanted)
            except OSError as exc:
                raise OmhError(
                    f"could not save the working glow to {theme_store_path(paths.omh_home)}: {exc}") from exc
            payload["changed"] = True
    if _wants_json(args):
        _print_json(payload)
    else:
        _print_glow(payload, requested)
    return 0


def _print_glow(payload: dict[str, object], requested: str) -> None:
    use_color = _use_color()
    glow = str(payload.get("glow", ""))
    print(_color(f"OMH TUI working glow: {glow}", "1;36", use_color))
    if not requested:
        print(f"  {'Saved' if payload.get('source') == 'saved' else 'Nothing saved; on by default'}"
              f" in {payload.get('store_path', '')}.")
    elif payload.get("changed"):
        print(f"  Saved {glow} in {payload.get('store_path', '')}.")
    else:
        print(f"  No change: {glow} is already saved.")
    print(_color("Next", "1;32", use_color))
    print("  The OMH TUI reads it when it opens; `/glow on|off` switches it inside a session. "
          "OMH_TUI_GLOW=0 holds it off in one terminal.")


def cmd_theme_repair(args: argparse.Namespace) -> int:
    """Retired with the skin files it reinstalled; scripts that still call it exit 0, as retired flags do.

    The old name, `--all` and `--dry-run` are still accepted and ignored.
    `--json` gets a retirement object, so a caller parsing the output reads
    "retired" rather than failing on plain text.
    """
    message = "`omh theme repair` is retired; OMH installs no skin files into Hermes, so there is nothing to repair."
    if _wants_json(args):
        _print_json({"schema_version": THEME_REPAIR_SCHEMA_VERSION, "retired": True, "changed": False, "message": message})
    else:
        print(f"omh: {message}", file=sys.stderr)
    return 0


def _active_line(payload: dict[str, object]) -> str:
    theme = payload.get("active_theme", "")
    source = payload.get("active_source")
    if source == "saved":
        return f"  Active: {theme}"
    if source == "hermes_skin":
        return f"  Active: {theme} (no theme saved; Hermes' display.skin names {payload.get('active_skin', '')})"
    return f"  Active: {theme} (the default; no theme saved)"


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
    print("  Switch with `omh theme use <name>`; the OMH TUI opens with it the next time you run `omh`.")


def _print_theme_status(payload: dict[str, object]) -> None:
    use_color = _use_color()
    print(_color("OMH theme status", "1;36", use_color))
    print(_active_line(payload))
    print(f"  Saved in: {payload.get('store_path', '')}")
    print(_color("Next", "1;32", use_color))
    print(f"  {payload.get('restart_note', '')}")


def _print_theme_change(payload: dict[str, object]) -> None:
    use_color = _use_color()
    theme = str(payload.get("theme", ""))
    print(_color(f"OMH theme: {theme}", "1;36", use_color))
    if payload.get("dry_run"):
        print(f"  Dry run: the OMH theme would become {theme}; nothing was written.")
    elif payload.get("already_active"):
        print(f"  No change: {theme} is already the saved theme.")
    else:
        print(f"  Saved {theme} in {payload.get('store_path', '')}.")
    print(_color("Next", "1;32", use_color))
    print(f"  {payload.get('restart_note', '')}")
    print(f"  Reverse: {payload.get('reverse_command', '')}")


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
        help="Select the OMH TUI theme. Applies the next time `omh` opens the OMH TUI.",
    )
    theme_use.add_argument("name", help=f"Theme short name ({', '.join(theme_names())}) or full skin name.")
    theme_use.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the selection without saving it.",
    )
    _add_shared_theme_arguments(theme_use, "Print the full machine-readable change payload.")
    theme_use.set_defaults(func=cmd_theme_use)

    theme_status = theme_sub.add_parser(
        "status",
        help="Show the active OMH TUI theme and where it is saved.",
    )
    _add_shared_theme_arguments(theme_status, "Print the full machine-readable status payload.")
    theme_status.set_defaults(func=cmd_theme_status)

    theme_glow = theme_sub.add_parser(
        "glow",
        help="Turn the OMH TUI's working glow (a light round the screen while a turn runs) on or off; alone, show it.",
    )
    theme_glow.add_argument("state", nargs="?", help="on or off; omit to show the saved choice.")
    _add_shared_theme_arguments(theme_glow, "Print the machine-readable glow payload.")
    theme_glow.set_defaults(func=cmd_theme_glow)

    theme_repair = theme_sub.add_parser("repair", help="Retired: OMH installs no skin files into Hermes. Does nothing.")
    theme_repair.add_argument("name", nargs="?", help="Accepted for compatibility and ignored.")
    theme_repair.add_argument("--all", action="store_true", help="Accepted for compatibility and ignored.")
    theme_repair.add_argument("--dry-run", action="store_true", help="Accepted for compatibility and ignored.")
    _add_shared_theme_arguments(theme_repair, "Print the retirement notice as JSON.")
    theme_repair.set_defaults(func=cmd_theme_repair)


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
