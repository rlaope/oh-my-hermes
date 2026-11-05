"""Canonical QC-gated sprite-frame skill and closed, inert optional toolkit exports."""
from __future__ import annotations

import hashlib
from importlib.resources import files
import json

from .catalog_types import ExpertQuestion, ProcedureCheck, ProcedureBail, ProcedureStep, SkillDefinition, SkillExample

TOOLKIT_RESOURCES = (
    "README.md", "LICENSE.upstream", "scripts/forge.py",
    "examples/layout.json", "upstream-manifest.json",
)

_INPUTS = (
    "grid sheet from the host image tool on flat #FF00FF",
    "declared rows x cols, cell size and feet baseline",
    "new output directory and execution budget",
)
_OUTPUTS = ("aligned equal-size frames and sheet", "sprite_forge_qc/v1 receipt", "character art-direction record")

DEFINITION = SkillDefinition(
    name="sprite-forge",
    description="Character art to animate in a game: turn image-model sprite sheets into aligned, QC-gated frames with a fail-closed Pillow helper.",
    triggers=("sprite-forge", "sprite sheet", "pixel sprite", "pixel art character", "game sprite frames", "2d sprite animation"),
    use_when="Use when a game character needs animation frames cut from an image-model grid sheet, with measured scale and baseline QC rather than hand-edited frames.",
    category="analysis", phase="sprite-production", hermes_role="operator",
    delegation_boundary="retained-catalog-intent", progressive_disclosure=True,
    reasoning_demand="heavy",
    required_inputs=_INPUTS, expected_outputs=_OUTPUTS,
    expert_questions=tuple(ExpertQuestion(key, question, question) for key, question in (
        (_INPUTS[0], "Which host image tool produces the sheet, which grid (2x2, 2x3, ...) holds which pose, and is the background flat #FF00FF?"),
        (_INPUTS[1], "What cell size and feet baseline (for example 512px cell, y=430) and which frames map to which game-data timings?"),
        (_INPUTS[2], "Which new directory receives frames, is optional Pillow installed in a separate environment, and what host timeout bounds the run?"),
    )),
    opening_steps=(
        "Read `toolkit/README.md` and `references/execution-and-qa.md` before executing `toolkit/scripts/forge.py`; installation and skill discovery never run it.",
        "Obtain the raw sheet from the host's own image tool as a grid on flat #FF00FF; OMH generates no images, and a 1xN strip is regenerated as a grid, never processed.",
        "Record identity elements, rejected drafts, cell size and baseline in `references/character-art-direction.md` form before cutting frames.",
    ),
    handoff_policy="Hermes retains art direction and QC interpretation. Raw sheets come from the host image tool; frames come only from the optional standalone helper within accepted file and execution scope. A prepared command is not observed frame processing.",
    procedure_checks=(
        ProcedureCheck("sprite_input_check", ("grid_layout", "background_key", "cell_division", "source_record"),
                       "Refuse 1xN strips, inexact cell division, oversized files and wide effects packed into a character cell; put slashes and muzzle flashes on a separate sheet."),
        ProcedureCheck("sprite_backend_check", ("pillow_version", "command", "exit_code", "script_sha256"),
                       "Name the real interpreter and Pillow version; missing Pillow, refusal exit 2 or timeout never yields guessed frames."),
        ProcedureCheck("sprite_qc_check", ("body_scale_cv", "anchor_y_std", "verdict", "output_hashes"),
                       "Require body_scale_cv <= 0.08 and anchor_y_std <= 0.05; a REGENERATE verdict (exit 3) means a new source sheet, never hand-patched frames."),
    ),
    procedure_steps=(
        ProcedureStep("sprite_direct", "analysis", (_INPUTS[0], _INPUTS[1]), (_OUTPUTS[2],), ("sprite_input_check",),
                      "Write the character art-direction record: identity elements, rejected drafts with reasons, cell size, baseline and attack-frame timing linked to game data."),
        ProcedureStep("sprite_process", "production", _INPUTS, _OUTPUTS, ("sprite_input_check", "sprite_backend_check"),
                      "Run the helper with a finite host timeout: chroma key, cell split, component cleanup, one common scale, feet-baseline alignment and nearest-neighbor resize.",
            on_fail=ProcedureBail(
                still_stands=('character art-direction record',),
                downgrade_to='not_observed',
                handback='Return the character art-direction record and observed helper command, refusal or timeout, with the required grid correction or optional Pillow setup before retrying in a new output directory.',
            ),
        ),
        ProcedureStep("sprite_verify", "validation", _INPUTS, _OUTPUTS, ("sprite_qc_check", "sprite_backend_check"),
                      "Read back every frame, the aligned sheet and qc.json; recompute hashes and report observed metrics separately from art-quality judgement.",
            on_fail=ProcedureBail(
                still_stands=('character art-direction record',),
                downgrade_to='tentative',
                handback='Return the sprite_forge_qc/v1 receipt with observed metrics or read-back gaps and, for REGENERATE, the tighter pose and scale instructions for a new source sheet, never patched frames.',
            ),
        ),
    ),
    artifact_expectations=(
        "Actual `frame_000.png`... equal-size RGBA frames with feet on one shared `baseline_y`, plus the re-composited aligned `sheet.png`.",
        "Authored `sprite_forge_qc/v1` in `qc.json`: frame count, grid, cell/frame size, per-frame bbox, body_scale_cv, anchor_y_std, thresholds, verdict, hashes and argv.",
        "A character art-direction record: identity elements, rejected drafts with reasons, cell size + baseline, and attack-frame timing tied to game data.",
    ),
    safety_rules=(
        "OMH generates no images: raw sheets come from the host's own image tool, and the helper only processes a supplied file.",
        "Never hand-patch, redraw or nudge produced frames to pass QC; a REGENERATE verdict sends the work back to a new source sheet.",
        "A real-person or photo source stays recognizable (no SD/chibi redraw) and requires that person's consent plus a source record before processing.",
        "Do not auto-install Pillow, import the companion on skill load, open a network connection or overwrite an existing output directory.",
        "No frame is observed until the helper exits and its files and qc.json are read back; refusal and timeout are not empty-animation findings.",
    ),
    quality_tier="execution-evidence-gated",
    quality_bar=(
        "Require a grid sheet on flat #FF00FF with exact cell division; strips and packed wide effects are regenerated, not cropped.",
        "Record the real interpreter, Pillow version, command, exit and output hashes; QC numbers come from qc.json, not from inspection by eye.",
        "Gate on body_scale_cv <= 0.08 and anchor_y_std <= 0.05, and keep technical PASS distinct from art-direction approval.",
    ),
    why_this_exists="Image models return character poses at drifting scales and offsets, so frames cut by hand jitter in play. This skill couples a grid-sheet contract to a fail-closed processor whose numeric QC decides whether to regenerate the source.",
    do_not_use_when=(
        "Create a product showcase video for a launch, with narration and subtitles; use `show-reel`.",
        "The task is judging already-rendered UI screenshots or layout captures; use `visual-qa`.",
        "The output is an image card or visual prompt card summarizing source material; use `img-summary`.",
    ),
    good_example=SkillExample(
        "Make a pixel sprite sheet for my game character.",
        "Get a 2x3 #FF00FF grid from the host image tool, record art direction, run the helper, then read back frames and qc.json and regenerate on a REGENERATE verdict.",
        "Animation frames need measured scale and baseline consistency, not a single illustration."),
    bad_example=SkillExample(
        "Tighten the CSS pixel spacing on this sheet of settings cards.",
        "Answer as a front-end styling question; do not run a sprite processor.",
        "Pixel and sheet vocabulary alone does not establish game-character frames."),
    final_checklist=(
        "The source sheet is a host-generated grid on #FF00FF with a source record; real-person sources carry consent.",
        "The actual helper command and exit were observed; frames, sheet and qc.json were read back and hashed, or the blocker is stated.",
        "body_scale_cv and anchor_y_std are quoted from qc.json; a REGENERATE verdict led to a new sheet, not frame edits.",
    ),
    recovery_notes=(
        "If the sheet is a 1xN strip or packs a wide effect, ask the host image tool for a grid and a separate effect sheet; do not slice it by hand.",
        "If Pillow is missing, return the refusal and an explicit optional-environment setup recipe; never synthesize frames.",
        "If QC returns REGENERATE, regenerate the source with tighter pose and scale instructions and rerun into a new output directory.",
    ),
    situations=("character poses drift in size between frames", "feet float or sink across an idle loop", "an image model returned a single strip of poses", "an attack frame must line up with a hit window in game data", "a player wants a recognizable avatar of themselves"),
)

REFERENCE_TEXT = {"execution-and-qa": """# Sprite-forge execution and QA

Read `toolkit/README.md` for setup, refusals and exact metric definitions. The
backend is **direct Pillow**; numpy is neither used nor required. Skill loading
and resource materialization only read inert text; OMH generates no images.

## Source sheet contract

- The raw sheet comes from the host's own image tool. Ask for a grid (2x2, 2x3,
  ...) on a flat `#FF00FF` background, one pose per cell, the whole body inside
  the cell with margin. A 1xN or Nx1 strip is refused; regenerate it as a grid.
- Wide effects (slashes, muzzle flash, dust) go on a separate sheet, never into
  an oversized character cell.
- The sheet must divide exactly into rows x cols cells. Files over 64 MiB or a
  side over 8192 px are refused before any output is written.
- A sheet with real transparency is used as-is (opaque = alpha >= 128);
  otherwise pixels within `--tolerance` (default 30) of `--key` are background.

## Execute

Use the host's bounded terminal with a finite timeout and a separate,
operator-approved environment that has Pillow. Write into a new output
directory; an existing directory is refused and never overwritten.

```sh
python scripts/forge.py process --input sheet.png --rows 2 --cols 3 \\
  --output new-frames --key FF00FF --tolerance 30 --target-height 128
```

The helper keeps the largest component per cell plus components >= 5% of it,
applies one common scale (nearest-neighbor) and aligns every body's feet on a
shared baseline. An empty cell or a body touching the cell edge (bleed) is
refused with the cell index.

## Read back and decide

Exit codes: 0 PASS, 2 refusal (no outputs), 3 REGENERATE (outputs written as
evidence). On exit 0 or 3, read `qc.json` (`sprite_forge_qc/v1`), every
`frame_NNN.png` and `sheet.png`, and recompute their sha256 against the receipt.

- `body_scale_cv` <= 0.08 and `anchor_y_std` <= 0.05 give PASS.
- REGENERATE means the source drifted: ask the host image tool for a new sheet
  with tighter pose and scale instructions. Never hand-patch, redraw or shift
  produced frames to pass the gate.
- A numeric PASS is technical evidence only; art-direction approval is a
  separate judgement against the character record. Use `visual-qa` when the
  frames must be checked inside a rendered game scene.
""", "character-art-direction": """# Character art-direction record

Write this record before cutting frames and update it on every regeneration.
It travels with the frames and the `qc.json` receipt.

## Identity elements

List what must stay constant in every frame: silhouette, palette (hex values),
proportions (head-to-body ratio), signature props and costume marks. A
regeneration that loses an identity element is rejected even when QC passes.

## Rejected drafts

For each rejected sheet record the source file hash, the prompt or settings
used, and the reason (scale drift, strip layout, effect packed into a cell,
identity element lost, background not flat). Rejected drafts are evidence, not
waste; do not delete them before the record is written.

## Cell size and baseline

Declare the cell size and the feet baseline the game expects, for example a
512px cell with feet at y=430, and the target frame height passed to the helper.
Every frame must share that baseline; the helper's `baseline_y` and
`anchor_y_std` are the evidence.

## Attack-frame timing

Map each frame index to its game-data timing: startup, active (hit window) and
recovery frames, with the source table or config path. An attack frame that does
not line up with its hit window is a design defect to fix in data or in a new
sheet, not by retiming pixels.

## Real-person or photo sources

A real person's likeness stays recognizable (no SD/chibi redraw unless that
person asks for it). Record the person's consent and the photo's source before
processing, and keep the source photo out of shared evidence.
"""}


def sprite_forge_definition():
    return DEFINITION


def sprite_forge_reference_templates():
    from .render import SkillReferenceTemplate, loadable_skill_mentions
    return [SkillReferenceTemplate(DEFINITION.name, f"references/{key}.md", loadable_skill_mentions(text))
            for key, text in REFERENCE_TEXT.items()]


def sprite_forge_provenance_manifest():
    """Generate hashes for reviewed original resources; this does not write them."""
    root = files("omh.skills").joinpath("sprite_forge_toolkit")
    entries = {}
    for relative in TOOLKIT_RESOURCES:
        if relative == "upstream-manifest.json":
            continue
        sha256 = hashlib.sha256(root.joinpath(relative).read_bytes()).hexdigest()
        entries[relative] = {"local_sha256": sha256, "source_sha256": sha256,
            "source_path": "src/skills/sprite_forge_toolkit/" + relative,
            "classification": "original_omh", "upstream": [], "license": "MIT",
            "copyright": "Copyright (c) 2026 oh-my-hermes contributors",
            "modification_notice": "Original OMH helper, synthetic example or guidance; no upstream source copied."}
    return {"schema": "omh_sprite_forge_provenance/v1",
        "repository": "https://github.com/rlaope/oh-my-hermes", "revision": None,
        "revision_note": "Original uncommitted resources identified by content hashes; not attributed to an upstream revision.",
        "license": "MIT", "self_hash": "excluded; outer distribution inventories hash this manifest", "files": entries}


def sprite_forge_support_templates():
    from .support_files import SkillSupportTemplate, validate_support_templates
    root = files("omh.skills").joinpath("sprite_forge_toolkit")
    texts = {}
    for relative in TOOLKIT_RESOURCES:
        resource = root.joinpath(relative)
        with resource.open("rb") as stream:
            raw = stream.read(1_048_577)
        if len(raw) > 1_048_576:
            raise ValueError("sprite-forge toolkit resource exceeds size limit")
        texts[relative] = raw.decode("utf-8")
    provenance = json.loads(texts["upstream-manifest.json"])
    expected = set(TOOLKIT_RESOURCES) - {"upstream-manifest.json"}
    if (not isinstance(provenance, dict) or provenance.get("schema") != "omh_sprite_forge_provenance/v1"
            or not isinstance(provenance.get("files"), dict) or set(provenance["files"]) != expected):
        raise ValueError("invalid closed sprite-forge provenance inventory")
    for relative in expected:
        entry = provenance["files"][relative]
        if not isinstance(entry, dict) or hashlib.sha256(texts[relative].encode("utf-8")).hexdigest() != entry.get("local_sha256"):
            raise ValueError(f"sprite-forge provenance digest mismatch: {relative}")
    return validate_support_templates([SkillSupportTemplate(DEFINITION.name, "toolkit/" + relative, texts[relative])
                                       for relative in TOOLKIT_RESOURCES])
