"""Closed, inert support-template export for `data-share-review`'s offline residual scanner."""
from __future__ import annotations

from importlib.resources import files

SKILL_NAME = "data-share-review"
TOOLKIT_DIR = "data_share_review_toolkit"
TOOLKIT_RESOURCES = (
    "README.md",
    "scripts/residual_scan.py",
)


def data_share_review_support_templates():
    from .support_files import SkillSupportTemplate, validate_support_templates

    root = files("omh.skills").joinpath(TOOLKIT_DIR)
    texts = {}
    for relative in TOOLKIT_RESOURCES:
        with root.joinpath(relative).open("rb") as stream:
            raw = stream.read(1_048_577)
        if len(raw) > 1_048_576:
            raise ValueError("data-share-review toolkit resource exceeds size limit")
        texts[relative] = raw.decode("utf-8").replace("\r\n", "\n")
    return validate_support_templates(
        [
            SkillSupportTemplate(SKILL_NAME, "toolkit/" + relative, texts[relative])
            for relative in TOOLKIT_RESOURCES
        ]
    )
