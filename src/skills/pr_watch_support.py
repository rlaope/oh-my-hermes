"""Closed, inert support-template export for the PR watch monitor and event guard.

The two scripts are companion data under `github-event-ops`' `toolkit/`:
install and update only materialize their bytes, and the PR-watch recipe copies
them into `<profile>/scripts/` for a Hermes cron monitor job and a webhook
route filter to run. OMH never imports or runs them.
"""
from __future__ import annotations

from importlib.resources import files

SKILL_NAME = "github-event-ops"
TOOLKIT_DIR = "pr_watch_toolkit"
TOOLKIT_RESOURCES = (
    "README.md",
    "scripts/pr_watch.py",
    "scripts/pr_event_guard.py",
    "examples/pr-watch.json",
    "examples/pr-event-guard.json",
)


def pr_watch_support_templates():
    from .support_files import SkillSupportTemplate, validate_support_templates
    root = files("omh.skills").joinpath(TOOLKIT_DIR)
    texts = {}
    for relative in TOOLKIT_RESOURCES:
        with root.joinpath(relative).open("rb") as stream:
            raw = stream.read(1_048_577)
        if len(raw) > 1_048_576:
            raise ValueError("pr watch toolkit resource exceeds size limit")
        texts[relative] = raw.decode("utf-8")
    return validate_support_templates([SkillSupportTemplate(SKILL_NAME, "toolkit/" + relative, texts[relative])
                                       for relative in TOOLKIT_RESOURCES])
