from __future__ import annotations

import argparse
import json
from pathlib import Path

from omh.adapter_quality import build_adapter_quality_delivery_card, build_adapter_quality_observation, link_adapter_quality_session, prepare_adapter_quality_delivery, record_adapter_quality_delivery, write_adapter_quality_observation
from omh.installer import OmhError

from .common import _paths, _print_json


def cmd_adapter_quality_observe(args: argparse.Namespace) -> int:
    try:
        payload = _json_file(args.manifest)
        observation = write_adapter_quality_observation(_paths(args), build_adapter_quality_observation(
            observation_id=_text(payload, "observation_id"),
            subject_id=_text(payload, "subject_id"),
            surface_kind=_text(payload, "surface_kind"),
            adapter_id=_text(payload, "adapter_id"),
            source_revision=_text(payload, "source_revision"),
            debug_signals=_dict_list(payload, "debug_signals"),
            checks=_dict_list(payload, "checks"),
            layout_checks=_dict_list(payload, "layout_checks"),
            metrics=_dict_list(payload, "metrics"),
        ))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(observation)
    return 0


def cmd_adapter_quality_prepare_delivery(args: argparse.Namespace) -> int:
    try:
        observation = _json_file(args.observation)
        card = build_adapter_quality_delivery_card(observation, renderer_target=args.renderer_target)
        preparation = prepare_adapter_quality_delivery(_paths(args), session_id=args.session_id, card=card)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json({"card": card, "preparation": preparation})
    return 0


def cmd_adapter_quality_record_delivery(args: argparse.Namespace) -> int:
    try:
        preparation = _json_file(args.preparation)
        record = record_adapter_quality_delivery(
            _paths(args),
            preparation=preparation,
            adapter=args.adapter,
            delivery_result=args.delivery_result,
            external_message_ref=args.external_message_ref,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(record)
    return 0


def cmd_adapter_quality_link(args: argparse.Namespace) -> int:
    try:
        record = link_adapter_quality_session(_paths(args), session_id=args.session_id, subject_id=args.subject_id, surface_kind=args.surface_kind, source_revision=args.source_revision, observation_id=args.observation_id, renderer_target=args.renderer_target)
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    _print_json(record)
    return 0


def _add_adapter_quality_commands(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    quality = sub.add_parser("adapter-quality", help="Record adapter-owned web, desktop, and app quality evidence.")
    commands = quality.add_subparsers(dest="adapter_quality_command", required=True)
    observe = commands.add_parser("observe", help="Validate a metadata-only adapter quality manifest.")
    observe.add_argument("--manifest", required=True)
    observe.set_defaults(func=cmd_adapter_quality_observe)
    link = commands.add_parser("link", help="Link one wrapper session to adapter quality state.")
    link.add_argument("--session-id", required=True)
    link.add_argument("--subject-id", required=True)
    link.add_argument("--surface-kind", choices=("web", "desktop", "app"), required=True)
    link.add_argument("--source-revision", required=True)
    link.add_argument("--observation-id", default="")
    link.add_argument("--renderer-target", choices=("discord", "slack", "telegram"), default="")
    link.set_defaults(func=cmd_adapter_quality_link)
    prepare = commands.add_parser("prepare-delivery", help="Prepare a renderer-specific quality delivery card.")
    prepare.add_argument("--session-id", required=True)
    prepare.add_argument("--observation", required=True)
    prepare.add_argument("--renderer-target", choices=("discord", "slack", "telegram"), required=True)
    prepare.set_defaults(func=cmd_adapter_quality_prepare_delivery)
    delivery = commands.add_parser("record-delivery", help="Record an adapter-observed quality delivery result.")
    delivery.add_argument("--preparation", required=True)
    delivery.add_argument("--adapter", required=True)
    delivery.add_argument("--delivery-result", choices=("delivered", "failed", "blocked"), required=True)
    delivery.add_argument("--external-message-ref", default="")
    delivery.set_defaults(func=cmd_adapter_quality_record_delivery)


def _json_file(path: str) -> dict[str, object]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("JSON manifest must be an object")
    return value


def _text(value: dict[str, object], key: str) -> str:
    return str(value.get(key, ""))


def _dict_list(value: dict[str, object], key: str) -> list[dict[str, object]]:
    entries = value.get(key, [])
    if not isinstance(entries, list) or not all(isinstance(item, dict) for item in entries):
        raise ValueError(f"{key} must be a list of objects")
    return entries
