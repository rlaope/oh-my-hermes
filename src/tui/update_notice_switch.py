"""What holds the OMH TUI's update notice off: no network client here, so `omh theme update-check` can report it.

`tui/update_notice.py`, the client, may be imported only by `tui/app.py`
(INVARIANT 2), so the switches it reads live in this module.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from ..skin_pack import read_update_check_choice

UPDATE_CHECK_ENV = "OMH_TUI_UPDATE_CHECK"
UPDATE_CHECK_OFF = "0"
# What holds the check off, as `held_off_by` names it, in the order it is read.
HELD_BY_ENV = "OMH_TUI_UPDATE_CHECK=0"
HELD_BY_THEME = "omh theme update-check off"
HELD_BY_LAUNCH_CHECK = "omh update-check off"


def held_off_by(environ: Mapping[str, str], omh_home: Path) -> str:
    """What holds the check off ("" while it is on): `OMH_TUI_UPDATE_CHECK=0` in this terminal, `update_check` saved
    off in the TUI's settings (`omh theme update-check off`), or `omh update-check` set to `off` by the person
    (owner, 2026-11-02). Any off wins over any on.

    The last is read from what is stored, `update_check.mode` in `<omh_home>/setup-profile.json`, never from the
    policy's default: a home where nothing ever wrote a mode was never asked, so the check is on there, while a
    stored `off` was chosen (by `omh update-check set --mode off`, or confirmed in `omh setup`, where it is the
    preselected answer).
    """
    if environ.get(UPDATE_CHECK_ENV) == UPDATE_CHECK_OFF:
        return HELD_BY_ENV
    if read_update_check_choice(omh_home) is False:
        return HELD_BY_THEME
    from ..maintenance.update_check_state import read_update_check_policy, update_check_policy_recorded
    from ..system.paths import OmhPaths

    paths = OmhPaths(omh_home=Path(omh_home), hermes_home=Path(environ.get("HERMES_HOME", "")))  # only the OMH home is read
    if update_check_policy_recorded(paths) and read_update_check_policy(paths)["mode"] == "off":
        return HELD_BY_LAUNCH_CHECK
    return ""


def update_check_off(environ: Mapping[str, str], omh_home: Path) -> bool:
    """Whether the check is off (`held_off_by` names what holds it)."""
    return bool(held_off_by(environ, omh_home))
