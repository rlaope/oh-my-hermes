from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from typing import Any, Mapping

from omh.coding.routing_observation import (
    authenticate_executor_observation,
    build_routing_observation,
    validate_routing_observation,
)
from omh.coding.unit_prompt_assembly import assemble_unit_prompt
from omh.coding.unit_prompt_protocol import calibration_for_route


_TASK_START = "OMH benchmark task:\n"
_TASK_END = "\n\nOMH benchmark protocol:"
MAX_PROMPT_BYTES = 131_072


def _failure_classification(detail: str) -> str:
    normalized = detail.casefold()
    if any(marker in normalized for marker in ("auth", "credential", "api key", "unauthorized", "forbidden")):
        return "authentication_failed"
    if any(marker in normalized for marker in ("rate limit", "too many requests", "429")):
        return "rate_limited"
    if any(marker in normalized for marker in ("model not found", "model unavailable", "unknown model")):
        return "model_unavailable"
    if "provider" in normalized:
        return "provider_error"
    return "process_crash"


def _failed_current_session_trial(
    *,
    route: Mapping[str, Any],
    condition: str,
    prompt: str,
    detail: str,
    kind: str,
    exit_code: int | None = None,
    classification: str | None = None,
    prompt_sent: bool = True,
    edit_surface: str = "patch",
) -> dict[str, object]:
    receipt: dict[str, object] = {"classification": classification or _failure_classification(detail), "kind": kind}
    if exit_code is not None:
        receipt["exit_code"] = exit_code
    return {
        "schema_version": "omh_live_model_trial/v1",
        "execution_path": "hermes_current_session",
        "condition": condition,
        "edit_surface": edit_surface,
        "task_digest": task_digest(prompt),
        # A route failure ends the trial before the condition prompt exists.
        "prompt_digest": prompt_digest(prompt) if prompt_sent else None,
        "route": {
            "selected_model": route["selected_model"],
            "selected_reasoning_effort": route["selected_reasoning_effort"],
            "model_family": route["model_family"],
        },
        "observation": {"status": "failed", "tools": None, "tokens": None, "cost_usd": None},
        "failure_receipt": receipt,
    }


def route_argv(
    executable: str,
    *,
    model: str,
    effort: str,
    role: str = "implementation",
) -> list[str]:
    return [
        executable,
        "coding",
        "model-route",
        "--executor",
        "hermes",
        "--model",
        model,
        "--effort",
        effort,
        "--role",
        role,
        "--json",
    ]


def dispatch_argv(
    executable: str,
    *,
    hermes_executable: str,
    workspace: Path,
    route: Mapping[str, Any],
    provider: str,
    parent_run_id: str,
    run_id: str,
    timeout: int,
) -> list[str]:
    return [
        executable,
        "coding",
        "hermes-child",
        "dispatch",
        "--confirm-dispatch",
        "--model",
        str(route["selected_model"]),
        "--provider",
        provider,
        "--reasoning",
        str(route["selected_reasoning_effort"]),
        "--parent-run-id",
        parent_run_id,
        "--run-id",
        run_id,
        "--hermes",
        hermes_executable,
        "--cwd",
        str(workspace),
        "--timeout",
        str(timeout),
        "--json",
    ]


def current_session_argv(
    hermes_executable: str,
    *,
    route: Mapping[str, Any],
    provider: str,
    usage_file: Path,
    prompt: str,
    workspace: Path,
    edit_surface: str = "patch",
) -> list[str]:
    """Use the caller's authenticated Hermes config, never the isolated child.

    `--oneshot` requires its prompt as the immediately following argument, so
    the prompt is placed directly after the flag rather than appended last.
    `--in <workspace>` pins the working directory: process cwd alone is not
    sufficient because Hermes restores the invoking user's home directory
    otherwise.

    `edit_surface="patch"` (default) keeps the argv byte-identical to the
    original `--toolsets file,terminal` invocation. `edit_surface="hashline"`
    exposes the plugin toolset `omh-hashline` (tools `hashline_read` /
    `hashline_edit`, gated by env `OMH_HASHLINE_TOOLS=1`) instead of the
    builtin `file` toolset, so the builtin `patch` tool (toolsets.py "file":
    ["read_file", "write_file", "patch", "search_files"]) is not exposed while
    `terminal` is kept.
    """
    if edit_surface == "patch":
        toolsets = "file,terminal"
    elif edit_surface == "hashline":
        toolsets = "omh-hashline,terminal"
    elif edit_surface == "lsp":
        # LSP augments the builtin file toolset; `patch` stays available.
        toolsets = "file,terminal,omh-lsp"
    else:
        raise ValueError("edit_surface must be 'patch', 'hashline' or 'lsp'")
    return [
        hermes_executable,
        "--oneshot",
        prompt,
        "--in",
        str(workspace),
        "--provider",
        provider,
        "--model",
        str(route["selected_model"]),
        "--reasoning",
        str(route["selected_reasoning_effort"]),
        "--toolsets",
        toolsets,
        "--usage-file",
        str(usage_file),
    ]


# Same sentence for both surfaces; only the tool names differ. Without it a model with `terminal`
# rewrites files through the shell and neither edit surface is measured (2026-10-27 smoke: 0 patch
# and 0 hashline_edit calls, 7 terminal calls).
_EDIT_TOOLS = {"patch": ("read_file", "patch"), "hashline": ("hashline_read", "hashline_edit")}


def edit_directive(edit_surface: str) -> str:
    if edit_surface not in _EDIT_TOOLS:
        raise ValueError("edit_surface must be 'patch' or 'hashline'")
    read, edit = _EDIT_TOOLS[edit_surface]
    return (f"EDIT TOOL RULE: read source files with `{read}` and change existing files only with `{edit}`. "
            "Do not modify files through terminal commands (sed, perl, python, shell redirection); "
            "use terminal only to search, run tests, and write the answer file.")


# Rename A/B pair (`--edit-directive rename`), used by BOTH arms so the two texts differ only in
# tool names; the patch/hashline rules above stay byte-identical.
_RENAME_TOOLS = {
    "patch": ("search_files", "search_files", "patch"),
    "lsp": ("lsp_definition", "lsp_references", "lsp_rename"),
}


def rename_directive(edit_surface: str) -> str:
    if edit_surface not in _RENAME_TOOLS:
        raise ValueError("rename directive needs edit_surface 'patch' or 'lsp'")
    definition, references, rename = _RENAME_TOOLS[edit_surface]
    return (f"EDIT TOOL RULE: find symbol definitions with `{definition}` and symbol uses with `{references}`, "
            f"rename symbols with `{rename}`, and change other code with `patch`. "
            "Do not modify files through terminal commands (sed, perl, python, shell redirection); "
            "use terminal only to search, run tests, and write the answer file.")


def directive_text(edit_surface: str, directive: bool | str) -> str | None:
    """Prompt prefix for a run: None (off), the edit rule (True), or the rename rule ("rename")."""
    if directive == "rename":
        return rename_directive(edit_surface)
    if directive is True:
        return edit_directive(edit_surface)
    if directive is False or directive is None:
        return None
    raise ValueError("directive must be a bool or 'rename'")


def prompt_pair(task: str, route: Mapping[str, Any]) -> tuple[str, str]:
    common = (
        f"{_TASK_START}{task.strip()}{_TASK_END}\n"
        "Use the available file and terminal tools when task execution requires them. "
        "You are operating inside the benchmark workspace; complete the task there.\n\n"
        "MANDATORY BENCHMARK COMPLETION CONTRACT:\n"
        "1. Perform the requested task before answering.\n"
        "2. Before stopping, write `.omh-benchmark-answer.json` at the workspace root.\n"
        "3. That file must contain exactly one valid JSON object answering the task; do not put Markdown or prose in it.\n"
        "4. Do not substitute a chat-only final answer for that file.\n"
        "5. Verify the file exists and parses as JSON, then stop."
    )
    calibration = calibration_for_route(route)
    optimized = common if not calibration else f"{calibration}\n\n{common}"
    return common, optimized


# The `Overall goal:` line of the unit head. Fixed rather than the task text so
# the head stays byte-identical across instances, the way sibling units of one
# fanout share it, and so the task appears once, inside its digest boundary.
UNIT_HEAD_GOAL = "Complete the OMH benchmark task below in this workspace."

# Blocks `unit_lean` drops from the product head, by the assembler's block
# names (`unit_prompt_assembly.BLOCK_NAMES`). Data, so a later arm can vary it.
# The first trim candidate from the 2026-10-04 prompt audit: the
# parent-clarification block, which also carries the head's only
# fanout_unit_result/v1 JSON example.
UNIT_LEAN_OMITTED_BLOCKS: tuple[str, ...] = ("head.parent_clarification",)

# The head's own return instructions name a fanout_unit_result/v1 block and an
# input_required escalation to a parent; neither exists in a benchmark run.
# Both unit arms state this precedence explicitly, after the head and its
# calibration and before the task, so the graded answer file stays the
# deliverable and `common` stays byte-identical across all five conditions.
UNIT_DELIVERABLE_PRECEDENCE = (
    "Benchmark deliverable: this unit runs inside the OMH benchmark, not a fanout. The "
    "`.omh-benchmark-answer.json` file the completion contract below requires is the graded "
    "deliverable and takes precedence over any other return format named above; there is no "
    "sidecar path, dispatch identity, or parent to consult in this run. A fenced result block "
    "in your final reply is optional and is not graded."
)

# The unit the assembler is asked for. Only its shared head and calibration
# blocks are sent; the rest of a fanout unit (scope, branch, criteria) has no
# meaning in a single-workspace benchmark task.
_BENCHMARK_UNIT: dict[str, Any] = {"unit_id": "benchmark"}


def unit_head_and_calibration(route: Mapping[str, Any], omitted: tuple[str, ...] = ()) -> tuple[str, str]:
    """The product's shared unit head and the route's calibration block.

    Both come from `assemble_unit_prompt`, the assembler every dispatch path
    uses, so the bytes and block names are the product's. An omitted name the
    assembler does not know raises there.
    """
    assembled = assemble_unit_prompt(
        _BENCHMARK_UNIT, UNIT_HEAD_GOAL, route=route, omit=frozenset(omitted)
    )
    head = "\n".join(block.text for block in assembled.blocks if block.zone == "shared_head")
    calibration = next(
        (block.text for block in assembled.blocks if block.base_name == "unit.calibration"), ""
    )
    return head, calibration


def head_omitted_blocks(condition: str) -> list[str] | None:
    """The head blocks a condition drops; `None` when it carries no head."""
    if condition == "unit":
        return []
    if condition == "unit_lean":
        return list(UNIT_LEAN_OMITTED_BLOCKS)
    return None


def prompt_for_condition(task: str, route: Mapping[str, Any], condition: str) -> str:
    """The prompt one benchmark condition sends; every condition shares one task.

    `baseline` is the bare contract, `optimized` adds the calibration the
    route resolves (an exact-model override when one exists), and `family`
    adds the block the model would inherit from its family with the override
    skipped. `family` exists so an exact-model override can be measured
    against what it replaced, not only against no calibration at all.

    `unit` is what a dispatched fanout unit carries in front of its work: the
    product's shared unit head, then the `optimized` calibration, then the
    deliverable-precedence note, then the same contract. `unit_lean` is `unit`
    with `UNIT_LEAN_OMITTED_BLOCKS` removed from the head and nothing else.
    """
    baseline, optimized = prompt_pair(task, route)
    if condition == "optimized":
        return optimized
    if condition == "family":
        calibration = calibration_for_route(route, family_only=True)
        return baseline if not calibration else f"{calibration}\n\n{baseline}"
    omitted = head_omitted_blocks(condition)
    if omitted is not None:
        head, calibration = unit_head_and_calibration(route, tuple(omitted))
        parts = [head, calibration, UNIT_DELIVERABLE_PRECEDENCE, baseline]
        return "\n\n".join(part for part in parts if part)
    return baseline


def prompt_digest(prompt: str) -> str:
    """SHA-256 of the exact prompt text a condition sent; the text is never kept."""
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def task_digest(prompt: str) -> str:
    try:
        task = prompt.split(_TASK_START, 1)[1].split(_TASK_END, 1)[0]
    except IndexError as exc:
        raise ValueError("prompt does not contain the OMH benchmark task boundary") from exc
    return hashlib.sha256(task.encode("utf-8")).hexdigest()


def observation_metrics(observation: Mapping[str, Any]) -> dict[str, object]:
    errors = validate_routing_observation(observation)
    if errors:
        raise ValueError("invalid routing observation: " + "; ".join(errors))
    return {
        "status": observation.get("status"),
        "tools": observation.get("tools"),
        "tokens": observation.get("tokens"),
        "cost_usd": observation.get("cost_usd"),
    }


def run_trial(
    *,
    omh_executable: str,
    hermes_executable: str,
    workspace: Path,
    omh_home: Path,
    task: str,
    model: str,
    provider: str,
    effort: str,
    condition: str,
    parent_run_id: str,
    run_id: str,
    timeout: int,
    confirmed: bool = False,
) -> dict[str, object]:
    if not confirmed:
        raise ValueError("explicit paid-live confirmation is required at the effect boundary")
    if not isinstance(timeout, int) or isinstance(timeout, bool) or not 1 <= timeout <= 3600:
        raise ValueError("timeout must be an integer from 1 to 3600 seconds")
    if len(task.encode("utf-8")) > MAX_PROMPT_BYTES:
        raise ValueError(f"prompt exceeds {MAX_PROMPT_BYTES} bytes")
    route_completed = subprocess.run(
        _platform_argv(route_argv(omh_executable, model=model, effort=effort)),
        check=False,
        capture_output=True,
        text=True,
        env=_environment(omh_home),
        timeout=60,
    )
    if route_completed.returncode:
        raise RuntimeError(f"OMH model route failed with exit {route_completed.returncode}")
    route = json.loads(route_completed.stdout)
    prompt = prompt_for_condition(task, route, condition)
    completed = subprocess.run(
        _platform_argv(dispatch_argv(
            omh_executable,
            hermes_executable=hermes_executable,
            workspace=workspace,
            route=route,
            provider=provider,
            parent_run_id=parent_run_id,
            run_id=run_id,
            timeout=timeout,
        )),
        input=prompt,
        check=False,
        capture_output=True,
        text=True,
        env=_environment(omh_home),
        timeout=timeout + 30,
    )
    if completed.returncode:
        detail = completed.stderr.strip()
        raise RuntimeError(
            f"OMH Hermes child dispatch failed with exit {completed.returncode}: {detail}"
        )
    observation = json.loads(completed.stdout)
    metrics = observation_metrics(observation)
    return {
        "schema_version": "omh_live_model_trial/v1",
        "condition": condition,
        "task_digest": task_digest(prompt),
        "prompt_digest": prompt_digest(prompt),
        "route": {
            "selected_model": route["selected_model"],
            "selected_reasoning_effort": route["selected_reasoning_effort"],
            "model_family": route["model_family"],
        },
        "observation": metrics,
    }


def run_current_session_trial(
    *,
    omh_executable: str,
    hermes_executable: str,
    workspace: Path,
    task: str,
    model: str,
    provider: str,
    effort: str,
    condition: str,
    parent_run_id: str,
    run_id: str,
    timeout: int,
    confirmed: bool = False,
    edit_surface: str = "patch",
    directive: bool | str = False,
) -> dict[str, object]:
    """Execute via the active Hermes profile and retain only observed metrics."""
    if not confirmed:
        raise ValueError("explicit paid-live confirmation is required at the effect boundary")
    if not isinstance(timeout, int) or isinstance(timeout, bool) or not 1 <= timeout <= 3600:
        raise ValueError("timeout must be an integer from 1 to 3600 seconds")
    if len(task.encode("utf-8")) > MAX_PROMPT_BYTES:
        raise ValueError(f"prompt exceeds {MAX_PROMPT_BYTES} bytes")
    fallback_route = {
        "selected_model": model,
        "selected_reasoning_effort": effort,
        "model_family": "unknown",
    }
    try:
        route_completed = subprocess.run(
            _platform_argv(route_argv(omh_executable, model=model, effort=effort)),
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _failed_current_session_trial(
            route=fallback_route,
            condition=condition,
            prompt=prompt_pair(task, fallback_route)[0],
            prompt_sent=False,
            detail="",
            kind="route_timeout" if isinstance(exc, subprocess.TimeoutExpired) else "route_launch",
            classification="timeout" if isinstance(exc, subprocess.TimeoutExpired) else "process_crash",
            edit_surface=edit_surface,
        )
    if route_completed.returncode:
        return _failed_current_session_trial(
            route=fallback_route,
            condition=condition,
            prompt=prompt_pair(task, fallback_route)[0],
            prompt_sent=False,
            edit_surface=edit_surface,
            detail=route_completed.stderr,
            kind="route_exit",
            exit_code=route_completed.returncode,
        )
    try:
        route = json.loads(route_completed.stdout)
        if not isinstance(route, dict):
            raise ValueError("route must be an object")
    except (json.JSONDecodeError, ValueError):
        return _failed_current_session_trial(
            route=fallback_route,
            condition=condition,
            prompt=prompt_pair(task, fallback_route)[0],
            prompt_sent=False,
            edit_surface=edit_surface,
            detail="",
            kind="route_protocol",
            classification="adapter_protocol_error",
        )
    prompt = prompt_for_condition(task, route, condition)
    rule = directive_text(edit_surface, directive)
    if rule is not None:
        prompt = f"{rule}\n\n{prompt}"
    with TemporaryDirectory(prefix="omh-current-session-usage-") as usage_root:
        usage_file = Path(usage_root) / "usage.json"
        try:
            completed = subprocess.run(
                _platform_argv(current_session_argv(
                    hermes_executable, route=route, provider=provider, usage_file=usage_file,
                    prompt=prompt, workspace=workspace, edit_surface=edit_surface,
                )),
                check=False,
                capture_output=True,
                text=True,
                cwd=workspace,
                env=_current_session_environment(workspace, edit_surface),
                timeout=timeout + 30,
            )
        except subprocess.TimeoutExpired:
            return _failed_current_session_trial(
                route=route,
                condition=condition,
                prompt=prompt,
                detail="",
                kind="timeout",
                classification="timeout",
                edit_surface=edit_surface,
            )
        if completed.returncode:
            return _failed_current_session_trial(
                route=route,
                condition=condition,
                prompt=prompt,
                detail=completed.stderr,
                kind="process_exit",
                exit_code=completed.returncode,
                edit_surface=edit_surface,
            )
        try:
            usage = _load_usage(usage_file)
        except RuntimeError:
            return _failed_current_session_trial(
                route=route,
                condition=condition,
                prompt=prompt,
                detail="",
                kind="usage_telemetry",
                classification="usage_unavailable",
                edit_surface=edit_surface,
            )
    observation = _current_session_observation(
        route=route, usage=usage, parent_run_id=parent_run_id, run_id=run_id,
    )
    return {
        "schema_version": "omh_live_model_trial/v1",
        "execution_path": "hermes_current_session",
        "condition": condition,
        "edit_surface": edit_surface,
        "edit_directive": directive,
        "task_digest": task_digest(prompt),
        "prompt_digest": prompt_digest(prompt),
        "route": {
            "selected_model": route["selected_model"],
            "selected_reasoning_effort": route["selected_reasoning_effort"],
            "model_family": route["model_family"],
        },
        "observation": observation_metrics(observation),
    }


def _load_usage(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("Hermes current-session execution did not produce valid usage telemetry") from exc
    if not isinstance(value, dict):
        raise RuntimeError("Hermes current-session usage telemetry must be an object")
    return value


def _current_session_observation(
    *, route: Mapping[str, Any], usage: Mapping[str, object], parent_run_id: str, run_id: str,
) -> dict[str, object]:
    session: dict[str, object] = {"status": "completed"}
    for source, target in (
        ("provider", "provider"), ("model", "model"), ("total_tokens", "tokens"),
        ("estimated_cost_usd", "cost_usd"), ("tool_calls", "tools"), ("turns", "turn"),
    ):
        value = usage.get(source)
        if isinstance(value, (str, int, float)) and not isinstance(value, bool):
            session[target] = value
    return build_routing_observation(
        route=route,
        session_observation=authenticate_executor_observation(session),
        parent_session_id=parent_run_id,
        child_session_id=run_id,
        run_id=run_id,
    )


def _platform_argv(argv: list[str]) -> list[str]:
    # `.py` launchers cannot rely on the PATH `python3` being new enough for
    # this codebase (requires-python >= 3.11), so always run them under the
    # current interpreter, on every platform.
    if Path(argv[0]).suffix.casefold() == ".py":
        return [sys.executable, *argv]
    return argv


def _environment(omh_home: Path) -> dict[str, str]:
    environment = dict(os.environ)
    environment["OMH_HOME"] = str(omh_home)
    return environment


def _current_session_environment(workspace: Path, edit_surface: str = "patch") -> dict[str, str]:
    """Pin the terminal/file tool anchor to the benchmark workspace.

    The caller's shell exports TERMINAL_CWD (for example the user's home
    directory); without an override the live model would read and mutate
    files there instead of the isolated benchmark workspace, even though
    the subprocess cwd is set to the workspace.

    When `edit_surface="hashline"`, `OMH_HASHLINE_TOOLS=1` is set for this run
    only, so the plugin tools `hashline_read`/`hashline_edit` (toolset
    `omh-hashline`) become available.
    """
    environment = dict(os.environ)
    environment["TERMINAL_CWD"] = str(workspace)
    # An opt-in flag inherited from the caller's shell must not reach the other arm.
    environment.pop("OMH_HASHLINE_TOOLS", None)
    environment.pop("OMH_LSP_TOOLS", None)
    if edit_surface == "hashline":
        environment["OMH_HASHLINE_TOOLS"] = "1"
    elif edit_surface == "lsp":
        # Harmless for the gateway, which reads the profile setting; set for parity with hashline.
        environment["OMH_LSP_TOOLS"] = "1"
    return environment
