"""Explicit agent/maintainer CLI for one isolated local Hermes child."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import signal

from ..coding.hermes_child_dispatch import DispatchConfirmationError, DispatchRecursionError, HermesChildDispatchError, HermesChildObservation, HermesChildRequest, dispatch_hermes_child
from ..system.approval_tier import TIER_AUTO_ALLOWED, resolve_approval_tier
from ..system.security_posture import resolve_security_posture
from ..coding.hermes_child_receipts import ReceiptVerificationError, hermes_child_run_dir, observation_key_open_flags, observation_signature_valid, read_hermes_child_observation, write_signed_observation
from ..coding.routing_observation import JsonValue, authenticate_child_observation, build_routing_observation, render_routing_status_rows, validate_routing_observation
from ..core.errors import OmhError
from ..system.local_store import atomic_write_json, read_json_object
from .common import _paths, _print_json, _wants_json
from .hermes_child_inputs import (
    read_prompt as _read_prompt,
    validate_metadata_args as _validate_metadata_args,
    validate_run_id as _validate_run_id,
)
from .hermes_child_observations import result_payload as _result_payload, route as _route
from .hermes_child_parser import HermesChildHandlers, configure_hermes_child_parser
from .hermes_child_process import (
    process_identity as _process_identity,
    validate_active_record as _validate_active_record,
)
from .hermes_child_skill_load import cmd_hermes_child_skill_load_probe, cmd_hermes_child_skill_load_status

_AUDIENCE = "agent/maintainer"
_ACTIVE_SCHEMA_VERSION = "hermes_child_active/v2"


def cmd_hermes_child_prepare(args: argparse.Namespace) -> int:
    _validate_metadata_args(args)
    prompt = _read_prompt(args.prompt_file)
    del prompt  # Deliberately neither persisted nor returned.
    observation = _prepared_observation(args)
    _write_observation(args, observation)
    _emit(args, observation)
    return 0


def cmd_hermes_child_dispatch(args: argparse.Namespace) -> int:
    decision = resolve_approval_tier(
        "hermes_child_dispatch", confirmed=bool(args.confirm_dispatch), posture=resolve_security_posture()
    )
    if decision.tier != TIER_AUTO_ALLOWED:
        raise OmhError("Hermes child dispatch requires --confirm-dispatch; prepare is the safe default")
    _validate_metadata_args(args)
    prompt = _read_prompt(args.prompt_file)
    run_dir = _run_dir(args)
    run_dir.mkdir(mode=0o700, exist_ok=True)
    reservation_path = run_dir / "dispatch.reserved"
    try:
        reservation = os.open(
            reservation_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
    except FileExistsError as exc:
        raise OmhError(f"Hermes child run already exists: {args.run_id}") from exc
    os.close(reservation)
    active_path = run_dir / "active.json"
    run_nonce = secrets.token_hex(32)
    terminal_event: HermesChildObservation | None = None

    def observe(item: HermesChildObservation) -> None:
        nonlocal terminal_event
        observation = _observed_payload(args, item.status)
        _write_observation(
            args,
            observation,
            None if item.status == "prepared" else item,
        )
        if item.status in {"completed", "failed", "timed_out", "cancelled"}:
            terminal_event = item
        if item.pid is not None:
            atomic_write_json(
                active_path,
                {
                    "schema_version": _ACTIVE_SCHEMA_VERSION,
                    "run_id": args.run_id,
                    "run_nonce": run_nonce,
                    "dispatcher_pid": os.getpid(),
                    "child_pid": item.pid,
                    "process_identity": _process_identity(os.getpid()),
                },
                private=True,
            )

    try:
        result = dispatch_hermes_child(
            HermesChildRequest(
                prompt=prompt,
                model=args.model,
                provider=args.provider,
                reasoning=args.reasoning,
                parent_run_id=args.parent_run_id,
                run_id=args.run_id,
                timeout_seconds=args.timeout,
                termination_grace_seconds=args.termination_grace,
                hermes=args.hermes,
                cwd=Path(args.cwd).expanduser() if args.cwd else None,
            ),
            dispatch_policy="ask_before_dispatch",
            confirmed=True,
            observe=observe,
        )
    except (DispatchConfirmationError, DispatchRecursionError, HermesChildDispatchError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    finally:
        active_path.unlink(missing_ok=True)

    usage: dict[str, JsonValue] = {
        key: value
        for key, value in result.usage.items()
        if value is None or isinstance(value, (str, int, float, bool))
    }
    observation = _result_payload(args, result.status, usage)
    if terminal_event is None:
        raise OmhError("Hermes child dispatch produced no sealed terminal observation")
    signed = _write_observation(args, observation, terminal_event)
    _emit(args, signed)
    return 0 if result.status == "completed" else 1


def cmd_hermes_child_status(args: argparse.Namespace) -> int:
    _validate_run_id(args.run_id)
    try:
        observation = read_hermes_child_observation(_run_dir(args))
    except ReceiptVerificationError as exc:
        if not (_run_dir(args) / "observation.json").exists():
            raise OmhError(f"Hermes child run not found: {args.run_id}") from exc
        raise OmhError(f"Hermes child observation is unreadable: {exc}") from exc
    if (
        validate_routing_observation(observation)
        or observation.get("run_id") != args.run_id
        or not _observation_signature_valid(args, observation)
    ):
        raise OmhError("Hermes child observation is invalid")
    _emit(args, observation)
    return 0


def cmd_hermes_child_cancel(args: argparse.Namespace) -> int:
    _validate_run_id(args.run_id)
    active_path = _run_dir(args) / "active.json"
    try:
        active = read_json_object(active_path)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise OmhError(f"Hermes child active record is unreadable: {exc}") from exc
    if active is None:
        raise OmhError(f"Hermes child run is not active: {args.run_id}")
    _validate_active_record(active, args.run_id)
    pid = int(active["dispatcher_pid"])
    try:
        current_identity = _process_identity(pid)
    except (OSError, ValueError) as exc:
        active_path.unlink(missing_ok=True)
        raise OmhError(f"Hermes child run is no longer active: {args.run_id}") from exc
    if current_identity != active["process_identity"]:
        raise OmhError("Hermes child active process identity does not match")
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError as exc:
        active_path.unlink(missing_ok=True)
        raise OmhError(f"Hermes child run is no longer active: {args.run_id}") from exc
    observation = _cancelled_from_existing(args)
    _emit(args, observation)
    return 0


def _prepared_observation(args: argparse.Namespace) -> dict[str, JsonValue]:
    _validate_metadata_args(args)
    return build_routing_observation(
        route=_route(args),
        parent_session_id=args.parent_run_id,
        child_session_id=args.run_id,
        run_id=args.run_id,
    )


def _observed_payload(args: argparse.Namespace, status: str) -> dict[str, JsonValue]:
    if status == "prepared":
        return _prepared_observation(args)
    return build_routing_observation(
        route=_route(args),
        child_dispatch=authenticate_child_observation(
            {"status": status, "run_id": args.run_id}
        ),
        parent_session_id=args.parent_run_id,
        child_session_id=args.run_id,
        run_id=args.run_id,
    )


def _cancelled_from_existing(args: argparse.Namespace) -> dict[str, JsonValue]:
    try:
        existing = read_hermes_child_observation(_run_dir(args))
    except ReceiptVerificationError as exc:
        raise OmhError(f"Hermes child observation is unreadable: {exc}") from exc
    provider = str(existing.get("selected_provider") or "hermes")
    model = str(existing.get("selected_model") or "unknown")
    reasoning = str(existing.get("selected_reasoning") or "unknown")
    route = {
        "selected_model": f"{provider}/{model}",
        "selected_reasoning_effort": reasoning,
        "role": "agent_maintainer",
        "executor_profile": "hermes_child",
        "chain": [{"provider": provider, "model_id": model, "reasoning_effort": reasoning}],
    }
    return build_routing_observation(
        route=route,
        child_dispatch=authenticate_child_observation(
            {"status": "cancelled", "run_id": args.run_id}
        ),
        parent_session_id=str(existing.get("parent_session_id") or ""),
        child_session_id=str(existing.get("child_session_id") or args.run_id),
        run_id=args.run_id,
    )


def _run_dir(args: argparse.Namespace) -> Path:
    try:
        return hermes_child_run_dir(_paths(args).omh_home, args.run_id, create_root=True)
    except ReceiptVerificationError as exc:
        raise OmhError(str(exc)) from exc


def _write_observation(
    args: argparse.Namespace,
    observation: dict[str, JsonValue],
    dispatch_observation: HermesChildObservation | None = None,
) -> dict[str, JsonValue]:
    try:
        return write_signed_observation(_run_dir(args), observation, dispatch_observation)
    except ReceiptVerificationError as exc:
        raise OmhError(str(exc)) from exc


def _observation_signature_valid(
    args: argparse.Namespace,
    observation: dict[str, JsonValue],
) -> bool:
    return observation_signature_valid(_run_dir(args), observation)


def _observation_key_open_flags() -> int:
    return observation_key_open_flags()


def _emit(args: argparse.Namespace, observation: dict[str, JsonValue]) -> None:
    if _wants_json(args):
        _print_json(observation)
        return
    print(f"AUDIENCE {_AUDIENCE}")
    print("\n".join(render_routing_status_rows(observation)))


def add_hermes_child_command(
    coding_sub: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    configure_hermes_child_parser(
        coding_sub,
        HermesChildHandlers(
            prepare=cmd_hermes_child_prepare,
            dispatch=cmd_hermes_child_dispatch,
            skill_load_probe=cmd_hermes_child_skill_load_probe,
            skill_load_status=cmd_hermes_child_skill_load_status,
            status=cmd_hermes_child_status,
            cancel=cmd_hermes_child_cancel,
        ),
    )
