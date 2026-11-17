"""Explicit paired-run adapter over the sanctioned Hermes child boundary."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
import hashlib
from pathlib import Path
import re

from ..quality.paired_run_model import ArmRole, PairedRunDecision
from ..system.secure_regular_file import (
    SecureFileError,
    open_regular_read,
    read_bounded,
    validate_no_symlinks,
)
from .fanout_dispatch import signal_safe_unit_runner
from .paired_run_dispatch_model import PairedRunDispatchPlan
from .paired_run_execution_model import PairedRunExecutionReport
from .paired_run_local_models import (
    PairedRunLocalRunnerConfig,
    PairedRunLocalRunnerError,
)
from .hermes_child_arm_setup import parse_arm_toolsets
from .paired_run_arm_home import ArmHomeRun, PairedRunArmHomeError, prepare_arm_home
from .paired_run_local_worktrees import execute_local_paired_plan


MAX_PAIRED_RUN_TASK_BYTES = 262_144
_REVISION = re.compile(r"^[0-9a-f]{40}$")
_SUPPORTED_EXECUTORS = frozenset(("hermes",))


def parse_task_file_arguments(values: tuple[str, ...]) -> dict[str, Path]:
    """Parse repeated ``TASK_ID=PATH`` arguments without reading their bytes."""
    parsed: dict[str, Path] = {}
    for value in values:
        task_id, separator, raw_path = value.partition("=")
        if (
            not separator
            or not task_id
            or not raw_path
            or task_id in parsed
        ):
            raise PairedRunLocalRunnerError(
                "--task-file must name each task exactly once as TASK_ID=PATH"
            )
        parsed[task_id] = Path(raw_path).expanduser()
    return parsed


def build_paired_run_local_boundary(
    decision: PairedRunDecision,
    task_files: Mapping[str, Path],
    config: PairedRunLocalRunnerConfig,
) -> Callable[[PairedRunDispatchPlan], PairedRunExecutionReport]:
    """Validate all external inputs before returning the confirmed run closure."""
    contents = _task_contents(decision, task_files)
    _validate_targets(decision)
    if not config.provider.strip():
        raise PairedRunLocalRunnerError(
            "confirmed paired-run dispatch requires --provider"
        )
    if (
        isinstance(config.timeout_seconds, bool)
        or not isinstance(config.timeout_seconds, (int, float))
        or config.timeout_seconds <= 0
    ):
        raise PairedRunLocalRunnerError("paired-run timeout must be positive")
    toolsets = _validated_toolsets(config.arm_toolsets)
    repo_root = _validated_repo(config.repo_root, decision.execution_revision)
    effective = PairedRunLocalRunnerConfig(
        config.paths,
        repo_root,
        config.provider.strip(),
        config.hermes,
        config.reasoning,
        min(float(config.timeout_seconds), float(decision.max_dispatch_seconds)),
        config.provider_config,
        toolsets,
    )

    def run(plan: PairedRunDispatchPlan) -> PairedRunExecutionReport:
        if plan.decision_id != decision.decision_id or not plan.launch_authorized:
            raise PairedRunLocalRunnerError(
                "local runner requires the matching authorized paired-run plan"
            )
        homes: dict[ArmRole, ArmHomeRun] = {}
        try:
            # Both homes are started and warmed before any cell's clock runs.
            for role, arm in ((ArmRole.BASELINE, decision.baseline), (ArmRole.VARIANT, decision.variant)):
                homes[role] = prepare_arm_home(
                    role.value,
                    provider=effective.provider,
                    model=arm.model,
                    reasoning=effective.reasoning,
                    hermes=effective.hermes,
                    provider_config=effective.provider_config,
                    exposed_skills=arm.exposed_skills,
                    omh_plugin=role is ArmRole.VARIANT,
                    # One value for both arms: the toolsets never differ per arm.
                    toolsets=effective.arm_toolsets,
                    warmup_timeout_seconds=effective.timeout_seconds,
                )
            report = execute_local_paired_plan(plan, decision, contents, effective, homes)
        except PairedRunArmHomeError as exc:
            raise PairedRunLocalRunnerError(str(exc)) from exc
        finally:
            stopped = {role: home.close() for role, home in homes.items()}
        records = {
            role.value: {**home.record(), "stopped": stopped[role]}
            for role, home in homes.items()
        }
        return replace(report, arm_homes=records, arm_toolsets=effective.arm_toolsets)

    return run


def _validated_toolsets(value: str) -> str:
    try:
        return parse_arm_toolsets(value)
    except ValueError as exc:
        raise PairedRunLocalRunnerError(str(exc)) from exc


def _validated_repo(repo_root: Path, revision: str) -> Path:
    if _REVISION.fullmatch(revision) is None:
        raise PairedRunLocalRunnerError(
            "confirmed paired-run dispatch requires an immutable 40-hex revision"
        )
    try:
        expanded = repo_root.expanduser()
        validate_no_symlinks(expanded)
        resolved = expanded.resolve(strict=True)
    except (OSError, SecureFileError) as exc:
        raise PairedRunLocalRunnerError("paired-run repository is unavailable") from exc
    if not resolved.is_dir():
        raise PairedRunLocalRunnerError(
            "paired-run repository must be a real non-symlink directory"
        )
    completed = _resolved_commit(resolved, revision)
    if completed != revision:
        raise PairedRunLocalRunnerError(
            "paired-run execution revision is not the exact repository commit"
        )
    return resolved


def _task_contents(
    decision: PairedRunDecision,
    task_files: Mapping[str, Path],
) -> dict[str, str]:
    expected = {task.task_id: task for task in decision.tasks}
    if set(task_files) != set(expected):
        raise PairedRunLocalRunnerError(
            "--task-file must provide every frozen task id exactly once"
        )
    contents: dict[str, str] = {}
    for task_id, task in expected.items():
        try:
            with open_regular_read(task_files[task_id]) as descriptor:
                payload = read_bounded(descriptor, MAX_PAIRED_RUN_TASK_BYTES)
        except (OSError, SecureFileError) as exc:
            raise PairedRunLocalRunnerError(
                f"task file is unreadable or exceeds {MAX_PAIRED_RUN_TASK_BYTES} bytes"
            ) from exc
        if hashlib.sha256(payload).hexdigest() != task.input_digest:
            raise PairedRunLocalRunnerError(
                f"task file digest does not match frozen input for {task_id}"
            )
        try:
            contents[task_id] = payload.decode("utf-8")
        except UnicodeError as exc:
            raise PairedRunLocalRunnerError("task files must be UTF-8 text") from exc
    return contents


def _validate_targets(decision: PairedRunDecision) -> None:
    unsupported = sorted(
        {
            arm.executor
            for arm in (decision.baseline, decision.variant)
            if arm.executor not in _SUPPORTED_EXECUTORS
        }
    )
    if unsupported:
        raise PairedRunLocalRunnerError(
            "no sanctioned paired-run adapter for executor(s): "
            + ", ".join(unsupported)
            + "; refusing without substitution"
        )


def _resolved_commit(repo: Path, revision: str) -> str:
    completed = signal_safe_unit_runner(
        ["git", "rev-parse", "--verify", f"{revision}^{{commit}}"],
        cwd=str(repo),
        text=True,
        capture_output=True,
        timeout=120,
    )
    if completed.returncode != 0:
        return ""
    return str(completed.stdout or "").strip()
