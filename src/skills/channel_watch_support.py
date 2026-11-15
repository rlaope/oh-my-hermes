"""Closed, inert support-template export for the channel watch collector.

The collector is companion data under `automation-blueprint`'s `toolkit/`:
install and update only materialize its bytes, and the channel-watch recipe
copies the script into `<profile>/scripts/` for a Hermes cron job to run.
OMH never imports or runs it.
"""
from __future__ import annotations

from importlib.resources import files

SKILL_NAME = "automation-blueprint"
TOOLKIT_DIR = "channel_watch_toolkit"
TOOLKIT_RESOURCES = ("README.md", "scripts/channel_watch.py", "examples/watch.json")


def channel_watch_support_templates():
    from .support_files import SkillSupportTemplate, validate_support_templates
    root = files("omh.skills").joinpath(TOOLKIT_DIR)
    texts = {}
    for relative in TOOLKIT_RESOURCES:
        with root.joinpath(relative).open("rb") as stream:
            raw = stream.read(1_048_577)
        if len(raw) > 1_048_576:
            raise ValueError("channel watch toolkit resource exceeds size limit")
        texts[relative] = raw.decode("utf-8")
    return validate_support_templates([SkillSupportTemplate(SKILL_NAME, "toolkit/" + relative, texts[relative])
                                       for relative in TOOLKIT_RESOURCES])
