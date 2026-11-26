"""Closed, inert support-template export for `inference-serving`'s offline VRAM/KV-cache calculator."""
from __future__ import annotations

from importlib.resources import files

SKILL_NAME = "inference-serving"
TOOLKIT_DIR = "inference_serving_toolkit"
TOOLKIT_RESOURCES = (
    "README.md",
    "scripts/vram_kv_calc.py",
)


def inference_serving_support_templates():
    from .support_files import SkillSupportTemplate, validate_support_templates

    root = files("omh.skills").joinpath(TOOLKIT_DIR)
    texts = {}
    for relative in TOOLKIT_RESOURCES:
        with root.joinpath(relative).open("rb") as stream:
            raw = stream.read(1_048_577)
        if len(raw) > 1_048_576:
            raise ValueError("inference-serving toolkit resource exceeds size limit")
        texts[relative] = raw.decode("utf-8").replace("\r\n", "\n")
    return validate_support_templates(
        [
            SkillSupportTemplate(SKILL_NAME, "toolkit/" + relative, texts[relative])
            for relative in TOOLKIT_RESOURCES
        ]
    )
