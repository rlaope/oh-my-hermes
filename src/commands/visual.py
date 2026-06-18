from __future__ import annotations

import argparse
from pathlib import Path

from ..installer import OmhError
from ..visual_summary import (
    ASPECT_RATIO_CHOICES,
    CAPABILITY_STATES,
    LANGUAGE_MODES,
    OBSERVATION_TYPES,
    SOURCE_KINDS,
    VISUAL_FORMAT_CHOICES,
    build_visual_observation,
    build_visual_prompt_card,
    normalize_observation_type,
    parse_section_arg,
    write_visual_observation,
)
from .common import _paths, _print_json


def cmd_visual_prompt_card(args: argparse.Namespace) -> int:
    try:
        source_text = _source_text_from_args(args)
        sections = [parse_section_arg(value) for value in args.section or []]
        card = build_visual_prompt_card(
            kind=args.kind,
            headline=args.headline,
            audience=args.audience,
            language=args.language,
            aspect_ratio=args.aspect_ratio,
            visual_format=args.visual_format,
            sections=sections,
            source_text=source_text,
            capability_state=args.capability_state,
        )
    except (OSError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    if args.json:
        _print_json(card)
    else:
        _print_prompt_card_summary(card)
    return 0


def cmd_visual_observe(args: argparse.Namespace) -> int:
    try:
        observation = build_visual_observation(
            card_id=args.card_id,
            observation_type=args.type,
            path_or_uri=args.path,
            mime_type=args.mime_type,
            evidence_summary=args.summary,
            observer=args.observer,
        )
        written = write_visual_observation(_paths(args), observation)
    except (OSError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    if args.json:
        _print_json(written)
    else:
        _print_observation_summary(written)
    return 0


def _source_text_from_args(args: argparse.Namespace) -> str:
    parts: list[str] = []
    if args.from_file:
        path = Path(args.from_file).expanduser()
        if not path.is_file():
            raise ValueError(f"--from-file must point to a readable local file: {path}")
        parts.append(path.read_text(encoding="utf-8"))
    if args.source_text:
        parts.append(" ".join(args.source_text).strip())
    return "\n".join(part for part in parts if part.strip())


def _print_prompt_card_summary(card: dict[str, object]) -> None:
    capability = card.get("capability_detection", {})
    state = capability.get("state", "unknown") if isinstance(capability, dict) else "unknown"
    print("Visual prompt card prepared.")
    print(f"Card: {card['card_id']}")
    print(f"Kind: {card['source_kind']}")
    print(f"Status: {card['status']}")
    print(f"Copy mode: {card['copy_mode']}")
    print(f"Language: {', '.join(card.get('languages', []))}")
    print(f"Visual format: {card['visual_format']}")
    print(f"Aspect ratio: {card['aspect_ratio']}")
    print(f"Image generator: {state}")
    print("")
    print(str(card["image_text"]["headline"]))
    for section in card.get("sections", []):
        print(f"- {section['title']}: {section['image_text']}")
    if card.get("requires_human_or_hermes_review"):
        print("")
        print("Needs review before public use:")
        for item in card.get("missing_structured_inputs", []):
            print(f"- {item}")
    print("")
    print("Next actions:")
    if "generate_visual_image" in card.get("available_actions", []):
        print("- Generate image in the connected wrapper or image tool.")
    else:
        print("- Copy the prompt into the image tool selected by the user or wrapper.")
    print("- Record generated image, visual QA, and delivery only after observed evidence exists.")
    print("")
    print("Not evidence yet: image generated, visual QA passed, delivered.")
    print("For machine-readable output, rerun with `--json`.")


def _print_observation_summary(record: dict[str, object]) -> None:
    artifact = record.get("artifact", {})
    print("Visual observation recorded.")
    print(f"Observation: {record['observation_id']}")
    print(f"Card: {record['visual_card_id']}")
    print(f"Type: {record['observation_type']}")
    print(f"Status: {record['status']}")
    if isinstance(artifact, dict):
        print(f"Artifact: {artifact.get('path_or_uri', '')}")
        print(f"MIME: {artifact.get('mime_type', '')}")
    print("")
    if record.get("does_not_prove"):
        print("Does not prove:")
        for item in record["does_not_prove"]:
            print(f"- {item}")
    print("For machine-readable output, rerun with `--json`.")


def _add_visual_commands(sub) -> None:
    visual = sub.add_parser(
        "visual",
        help="Prepare visual summary prompt cards and record observed visual evidence.",
    )
    visual_sub = visual.add_subparsers(dest="visual_command", required=True)

    prompt_card = visual_sub.add_parser(
        "prompt-card",
        help="Prepare a visual_prompt_card/v1 for a meeting, PR, issue, research, or release summary image.",
    )
    prompt_card.add_argument("source_text", nargs="*", help="Raw source text for extractive draft mode.")
    prompt_card.add_argument("--kind", required=True, help=f"Source kind or strict alias. Canonical values: {', '.join(SOURCE_KINDS)}.")
    prompt_card.add_argument("--headline", default="")
    prompt_card.add_argument("--audience", default="")
    prompt_card.add_argument("--language", choices=LANGUAGE_MODES, default="source")
    prompt_card.add_argument("--aspect-ratio", choices=ASPECT_RATIO_CHOICES, default="auto")
    prompt_card.add_argument("--visual-format", choices=VISUAL_FORMAT_CHOICES, default="auto")
    prompt_card.add_argument("--section", action="append", metavar="ROLE:TITLE:TEXT")
    prompt_card.add_argument("--from-file", default="")
    prompt_card.add_argument("--capability-state", choices=CAPABILITY_STATES, default="unknown")
    prompt_card.add_argument("--json", action="store_true")
    prompt_card.set_defaults(func=cmd_visual_prompt_card)

    observe = visual_sub.add_parser(
        "observe",
        help="Record supplied visual_observation/v1 metadata for generated image, visual QA, or delivery evidence.",
    )
    observe.add_argument("--card-id", required=True)
    observe.add_argument(
        "--type",
        required=True,
        help=f"Observation type or alias. Canonical values: {', '.join(OBSERVATION_TYPES)}.",
    )
    observe.add_argument("--path", required=True, help="Absolute local path or URI for the observed image artifact.")
    observe.add_argument("--mime-type", default="")
    observe.add_argument("--summary", required=True, help="Short observed evidence summary.")
    observe.add_argument("--observer", default="wrapper_or_user")
    observe.add_argument("--json", action="store_true")
    observe.set_defaults(func=cmd_visual_observe)


__all__ = [
    "_add_visual_commands",
    "cmd_visual_observe",
    "cmd_visual_prompt_card",
    "normalize_observation_type",
]
