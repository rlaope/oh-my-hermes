"""Closed, inert support-template export for the monitor-recipe scripts.

The three scripts are companion data under `automation-blueprint`'s
`toolkit/monitors/`: install and update only materialize their bytes, and the
monitor recipes (`monitor_recipes.py`) copy one into `<profile>/scripts/` for a
Hermes cron monitor job to run. OMH never imports or runs them.
"""
from __future__ import annotations

from importlib.resources import files

SKILL_NAME = "automation-blueprint"
TOOLKIT_DIR = "monitor_watch_toolkit"
TOOLKIT_RESOURCES = (
    "README.md",
    "scripts/api_watch.py",
    "scripts/google_watch.py",
    "scripts/vault_watch.py",
    "examples/calendar-starting-soon.json",
    "examples/gmail-new-mail.json",
    "examples/jira-assigned.json",
    "examples/linear-assigned.json",
    "examples/notion-changed.json",
    "examples/obsidian-folder-changed.json",
    "examples/sentry-new-issue.json",
)


def monitor_watch_support_templates():
    from .support_files import SkillSupportTemplate, validate_support_templates
    root = files("omh.skills").joinpath(TOOLKIT_DIR)
    texts = {}
    for relative in TOOLKIT_RESOURCES:
        with root.joinpath(relative).open("rb") as stream:
            raw = stream.read(1_048_577)
        if len(raw) > 1_048_576:
            raise ValueError("monitor watch toolkit resource exceeds size limit")
        texts[relative] = raw.decode("utf-8")
    return validate_support_templates([SkillSupportTemplate(SKILL_NAME, "toolkit/monitors/" + relative, texts[relative])
                                       for relative in TOOLKIT_RESOURCES])
