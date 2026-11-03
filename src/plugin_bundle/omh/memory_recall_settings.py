"""The two profile settings that quiet recall: `recall_line` and `recall_mode`.

Both live beside `dreaming_mode` in the profile's own ``config.yaml``, at
``plugins.entries.omh.settings.<name>``, and are read the same way: fresh on
each call through `runtime_paths.plugin_setting_text`, so a change applies from
the next render without restarting Hermes.

- ``recall_line`` decides where Hermes' ``🧠 OMH — recalled N memories`` line
  is shown. It never changes what the prefetch serves: on a surface it
  excludes, memory still reaches the turn and the prefetch receipt still
  records it.
- ``recall_mode`` decides whether memory reaches a turn unasked. ``auto`` is
  per-turn recall; ``on_demand`` serves no records or blocks per turn and
  leaves tool recall and saving alone; ``off`` also refuses tool recall.

An unknown value, or a config this reader cannot follow, keeps the default and
says so (`issue`), like `memory_dreaming.read_dreaming_mode_setting`.
"""

from __future__ import annotations

from pathlib import Path

from . import runtime_paths

RECALL_LINE_SETTING = "recall_line"
RECALL_LINES = ("all", "console", "off")
# Owner decision 2026-11-03: the line stays on the operator's own screen
# (CLI, TUI, Desktop) and is not posted into Discord or Slack.
DEFAULT_RECALL_LINE = "console"

RECALL_MODE_SETTING = "recall_mode"
RECALL_MODES = ("auto", "on_demand", "off")
DEFAULT_RECALL_MODE = "auto"

RECALL_SETTING_UNRECOGNIZED = "recall_setting_unrecognized"
# `off` written bare is a YAML false, and `hermes config set ... off` stores it
# as `false`; the false spellings all mean the profile chose `off`.
_OFF_SPELLINGS = frozenset({"off", "false", "no"})
_RAW_DISPLAY_CHARS = 64


def read_recall_line_setting(hermes_home: str | Path | None) -> dict[str, object]:
    """``{"value", "raw", "recognized"}`` for this profile's `recall_line`, plus ``issue``/``reason`` when unread."""
    return _read_setting(hermes_home, RECALL_LINE_SETTING, RECALL_LINES, DEFAULT_RECALL_LINE)


def read_recall_mode_setting(hermes_home: str | Path | None) -> dict[str, object]:
    """``{"value", "raw", "recognized"}`` for this profile's `recall_mode`, plus ``issue``/``reason`` when unread."""
    return _read_setting(hermes_home, RECALL_MODE_SETTING, RECALL_MODES, DEFAULT_RECALL_MODE)


def configured_recall_line(hermes_home: str | Path | None) -> str:
    return str(read_recall_line_setting(hermes_home)["value"])


def configured_recall_mode(hermes_home: str | Path | None) -> str:
    return str(read_recall_mode_setting(hermes_home)["value"])


def recall_line_shown(recall_line: str, platform: str, console_platforms: frozenset[str]) -> bool:
    """Whether Hermes may show the recall line on `platform` under `recall_line`."""
    if recall_line == "all":
        return True
    if recall_line == "console":
        return platform in console_platforms
    return False


def _read_setting(hermes_home: str | Path | None, name: str, values: tuple[str, ...], default: str) -> dict[str, object]:
    if hermes_home is None:
        return {"value": default, "raw": None, "recognized": True}
    try:
        text = (Path(hermes_home).expanduser() / "config.yaml").read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"value": default, "raw": None, "recognized": True}
    except (OSError, ValueError):
        return _unrecognized(default, None, "config_unreadable")
    try:
        written = runtime_paths.plugin_setting_text(text, name)
    except runtime_paths.RuntimeBindingError:
        return _unrecognized(default, None, "config_unreadable")
    if written is None:
        return {"value": default, "raw": None, "recognized": True}
    raw = "".join(character for character in written if character.isprintable())[:_RAW_DISPLAY_CHARS]
    spelled = written.strip().lower()
    if spelled in _OFF_SPELLINGS and "off" in values:
        return {"value": "off", "raw": raw, "recognized": True}
    if spelled in values:
        return {"value": spelled, "raw": raw, "recognized": True}
    return _unrecognized(default, raw, "unknown_value")


def _unrecognized(default: str, raw: str | None, reason: str) -> dict[str, object]:
    return {"value": default, "raw": raw, "recognized": False, "issue": RECALL_SETTING_UNRECOGNIZED, "reason": reason}
