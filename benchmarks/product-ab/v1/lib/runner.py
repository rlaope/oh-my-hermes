"""Doctor, one graded task, and the counterbalanced matrix."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from typing import Any
import uuid

import arms
import corpus as corpus_lib
import grading
import lane
import repo as repo_lib


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def approximate_cost_usd(model: str, usage: Mapping[str, Any]) -> float | None:
    """List-price cost from OMH's own shipped table.

    The host reports `estimated_cost_usd` for some routes and nothing for
    others (a subscription route reports `included`, a gateway often reports
    `unknown`). Pricing every arm from the same shipped table keeps rows
    comparable; where the host does report a cost, the record carries both.

    The private `_approximate_cost_usd` is called rather than reimplemented
    from `APPROX_PRICE_PER_MTOK`: the cache-read ratio, the service-tier
    multiplier, and the alias projection are part of what a price means here,
    and a second copy of that arithmetic would drift from the shipped one
    without anything failing.
    """

    if str(lane.REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(lane.REPO_ROOT))
    from omh.plugin_bundle.omh.hermes_delegation import (  # noqa: PLC0415
        _approximate_cost_usd,
    )

    def number(name: str) -> float:
        value = usage.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return 0.0
        return float(value)

    # `_approximate_cost_usd` prices uncached input and cache reads as separate
    # buckets. Hermes' `--usage-file` on the Codex route reports `input_tokens`
    # INCLUSIVE of cache reads -- `total_tokens` there is exactly input plus
    # output (5,736,985 + 18,408 = 5,755,393), and the session store holds the
    # uncached remainder -- so passing both through priced every cached token
    # twice and put one task at $35.77 instead of $4.98. `total_tokens` tells
    # the two shapes apart: inclusive input sums with output to the total,
    # uncached input falls short of it by the cache reads.
    input_tokens = number("input_tokens")
    output_tokens = number("output_tokens")
    cache_read = number("cache_read_tokens")
    total = number("total_tokens")
    if cache_read and total and input_tokens + output_tokens == total and cache_read <= input_tokens:
        input_tokens -= cache_read
    return _approximate_cost_usd(model, input_tokens, output_tokens, cache_read)


def _usage_total(attempts: Sequence[arms.Attempt], name: str) -> float | None:
    """The sum over the attempts that reported `name`, or `None` if none did.

    `None` rather than `0.0`: a key no attempt reported is a column nobody
    measured, and a zero would be read as a measurement.
    """

    values = [
        float(attempt.usage[name])
        for attempt in attempts
        if isinstance(attempt.usage.get(name), (int, float))
        and not isinstance(attempt.usage.get(name), bool)
    ]
    return sum(values) if values else None


def _reported_cost(attempts: Sequence[arms.Attempt]) -> float | None:
    reported = [
        float(attempt.usage["estimated_cost_usd"])
        for attempt in attempts
        if isinstance(attempt.usage.get("estimated_cost_usd"), (int, float))
        and not isinstance(attempt.usage.get("estimated_cost_usd"), bool)
    ]
    return sum(reported) if reported else None


def _linked_providers() -> list[str]:
    """Provider ids the active Hermes profile is linked to, by OMH's own reader.

    This is the readiness check that catches the expensive mistake: a run whose
    arms cannot reach their provider fails after the first paid attempt rather
    than before any of them.
    """

    if str(lane.REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(lane.REPO_ROOT))
    from omh.plugin_bundle.omh.provider_detection import (  # noqa: PLC0415
        detect_linked_providers,
    )

    return [str(row["id"]) for row in detect_linked_providers()]


def _version(executable: str, flag: str) -> str:
    """The first line a tool reports for itself, so a run names its generation."""

    if shutil.which(executable) is None:
        return "not_on_path"
    try:
        completed = subprocess.run(
            [executable, flag], capture_output=True, text=True, encoding="utf-8",
            errors="replace", check=False, timeout=60
        )
    except (OSError, subprocess.SubprocessError):
        return "unavailable"
    line = (completed.stdout or completed.stderr).strip().splitlines()
    return line[0][:120] if line else "unavailable"


def doctor(
    *,
    manifest: Mapping[str, Any],
    corpus_path: Path,
    repository: Path,
    omh_executable: str,
    hermes_executable: str,
) -> dict[str, Any]:
    """Every readiness check that can be made before a paid token is spent."""

    checks: list[dict[str, Any]] = []

    def record(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    record(
        "manifest_schema",
        manifest.get("schema_version") == lane.MANIFEST_SCHEMA,
        str(manifest.get("schema_version")),
    )
    control = dict(manifest.get("control") or {})
    execution = dict(manifest.get("execution") or {})
    record(
        "manifest_execution_path",
        execution.get("path") == arms.EXECUTION_PATH,
        f"this lane implements {arms.EXECUTION_PATH} only; the manifest says "
        f"{execution.get('path')!r}",
    )
    record(
        "manifest_control_model",
        bool(control.get("model") and control.get("provider") and control.get("effort")),
        "manifest must pin one provider, model, and effort for the control arm",
    )

    try:
        payload = corpus_lib.load(corpus_path)
        tasks = list(payload["tasks"])
        record("corpus_present", True, f"{len(tasks)} tasks")
    except (OSError, ValueError, corpus_lib.CorpusError) as error:
        record("corpus_present", False, str(error)[:200])
        payload, tasks = {}, []

    if not repo_lib.git_ok(repository, "rev-parse", "--git-dir"):
        record("repository", False, "not a git repository")
    else:
        record("repository", True, "")
        if tasks:
            errors = corpus_lib.verify(repository, payload)
            record("corpus_digests", not errors, "; ".join(errors[:3])[:400])
            missing = [
                str(task["task_id"])
                for task in tasks
                if not repo_lib.git_ok(repository, "cat-file", "-e", f"{task['merge_base']}^{{commit}}")
            ]
            record(
                "task_commits_present",
                not missing,
                f"missing merge base for {missing[:5]}" if missing else "",
            )

    for name, executable in (("hermes", hermes_executable), ("omh", omh_executable), ("git", "git")):
        record(f"{name}_on_path", shutil.which(executable) is not None, executable)

    linked = _linked_providers()
    wanted = {str(control.get("provider") or ""), str(control.get("mixture_provider") or "")}
    wanted.discard("")
    missing = sorted(wanted - set(linked))
    record(
        "providers_linked",
        not missing and bool(linked),
        f"missing {missing} (linked: {sorted(linked)})" if missing else f"linked: {sorted(linked)}",
    )

    route_ok, route_detail = False, ""
    calibration_ok, calibration_detail = False, "the control route did not resolve"
    if shutil.which(omh_executable):
        try:
            route = arms.resolve_route(
                omh_executable=omh_executable,
                model=str(control.get("model") or ""),
                effort=str(control.get("effort") or ""),
            )
            family = str(route.get("model_family") or "").strip().casefold()
            # `model-route` echoes an unrecognized model back with
            # `model_family: unknown`, so a non-empty `selected_model` proves
            # only that the flag parsed. Without the family check a control
            # model this repository has never heard of passes every readiness
            # check and is discovered by the first paid call.
            route_ok = bool(route.get("selected_model")) and family not in {"", "unknown"}
            route_detail = (
                f"{route.get('selected_model')} @ "
                f"{route.get('selected_reasoning_effort')} (family {family or 'blank'})"
            )
            calibration = arms.prompt_protocol().calibration_for_route(route)
            # The lane's README and MODEL_OPTI.md both describe the OMH arm as
            # carrying "the calibration that route selects".
            # `calibration_for_route` returns "" outside the high effort tier,
            # so a control effort of `medium` makes that sentence false on
            # every task, while the mixture arm routed at `high` does get a
            # block -- putting calibration only in the arm where the model
            # also changed, which inverts the reason that arm is separate.
            calibration_ok = bool(calibration)
            calibration_detail = (
                f"{len(calibration)} chars at effort "
                f"{route.get('selected_reasoning_effort')!r}"
            )
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
            route_detail = str(error)[:200]
            calibration_detail = str(error)[:200]
    record("control_route_resolves", route_ok, route_detail)
    record("control_route_carries_calibration", calibration_ok, calibration_detail)
    record(
        "completion_file_in_unit_scope",
        completion_file_in_scope(arms.unit_file_scope()),
        f"{lane.COMPLETION_FILE} must be inside the unit file scope "
        f"{arms.unit_file_scope()}, or criterion 1 forbids the file the "
        "completion contract requires",
    )
    record(
        "prompt_interpreter_on_path",
        shutil.which(arms.PROMPT_INTERPRETER) is not None,
        f"the criteria name `{arms.PROMPT_INTERPRETER}`; a model that cannot run "
        "a criterion as written judges it by its own authority",
    )

    workspace_ok, workspace_detail = False, ""
    if tasks and repo_lib.git_ok(repository, "rev-parse", "--git-dir"):
        try:
            with TemporaryDirectory(prefix="omh-product-ab-doctor-") as root:
                with repo_lib.candidate_workspace(
                    repository, str(tasks[0]["merge_base"]), Path(root), "probe"
                ) as workspace:
                    workspace_ok = (workspace / "src").is_dir()
                    already = grading.validator_paths_already_present(workspace, tasks[0])
                    if already:
                        workspace_ok = False
                        workspace_detail = f"validator already present: {already[:3]}"
        except (OSError, repo_lib.GitError, ValueError) as error:
            workspace_detail = str(error)[:200]
    record("workspace_creatable", workspace_ok, workspace_detail)

    return {
        "schema_version": lane.DOCTOR_SCHEMA,
        "ok": all(check["ok"] for check in checks),
        "observed_at": _now(),
        "versions": {
            "omh": _version(omh_executable, "--version"),
            "hermes": _version(hermes_executable, "--version"),
        },
        "arms": list(lane.ARMS),
        "prompt_profile": arms.PROMPT_PROFILE,
        "corpus_digest": payload.get("corpus_digest"),
        "task_count": len(tasks),
        "checks": checks,
        "claim_boundary": str(manifest.get("claim_boundary") or ""),
    }


def completion_file_in_scope(file_scope: Sequence[str]) -> bool:
    """Whether a unit file scope covers the completion file at the root."""

    for entry in file_scope:
        text = str(entry)
        if text == lane.COMPLETION_FILE or text in {".", "./"}:
            return True
        if text.endswith("/") and lane.COMPLETION_FILE.startswith(text):
            return True
    return False


def gate_disclosure(task: Mapping[str, Any]) -> dict[str, Any]:
    """What the verification gate can and cannot see on this task.

    `covers_target` is a constant. The gate runs a compile pass, the
    pre-existing regression modules, and the pre-existing tests that directly
    import the files the candidate changed; the pull request's own tests are
    the hidden validator and never run in it. `regression_green_at_merge_base` is
    copied from the corpus probe, which admits a task only when that set is
    green on the untouched checkout -- so on every admitted task the gate
    passes before the candidate has changed anything, and it can catch a
    regression, never a missing fix. The compile half is `None` because the
    probe never ran compile.
    """

    probe = dict(task.get("baseline_probe") or {})
    regression = dict(probe.get("regression") or {})
    status = regression.get("status")
    return {
        "covers_target": False,
        "regression_green_at_merge_base": (status == "green") if status else None,
        "compile_green_at_merge_base": None,
    }


def worst_case_paid_calls(
    manifest: Mapping[str, Any], task_count: int, selected_arms: Sequence[str]
) -> int:
    """Every model invocation the matrix could launch, repair turns included.

    `--max-paid-calls` is a spending limit, so it has to be compared against
    invocations rather than against graded runs. The two are not the same
    number: an OMH arm whose verification gate fails gets `omh_repair_attempts`
    further turns, and each one is a paid call the scheduled count never saw.
    Budgeting on the worst case can refuse a run that would in fact have come
    in under the limit, which is the direction a spending limit should err in.
    """

    repairs = int(dict(manifest.get("execution") or {}).get("omh_repair_attempts", 0))
    per_task = 0
    for arm in selected_arms:
        per_task += 1 + (repairs if arm in {"omh", "omh_mixture"} else 0)
    return task_count * per_task


def arm_order(task_index: int, selected: Sequence[str]) -> list[str]:
    """Counterbalanced order: rotate the arms one position per task."""

    ordered = list(selected)
    if not ordered:
        return ordered
    offset = task_index % len(ordered)
    return ordered[offset:] + ordered[:offset]


def _model_for_arm(
    arm: str,
    control: Mapping[str, Any],
    routing: Mapping[str, Any] | None,
) -> dict[str, str]:
    if arm != "omh_mixture" or not routing or not routing.get("resolved_model"):
        return {
            "provider": str(control["provider"]),
            "id": str(control["model"]),
            "effort": str(control["effort"]),
        }
    return {
        "provider": str(control.get("mixture_provider") or control["provider"]),
        "id": str(routing["resolved_model"]),
        "effort": str(routing.get("resolved_reasoning_effort") or control["effort"]),
    }


def execute_one(
    *,
    manifest: Mapping[str, Any],
    task: Mapping[str, Any],
    arm: str,
    corpus_digest: str,
    repository: Path,
    workspace_root: Path,
    output: Path,
    omh_executable: str,
    hermes_executable: str,
    python_executable: str,
    live: bool,
    task_index: int = 0,
) -> dict[str, Any]:
    """Run one arm on one task and grade it. One paid call unless it repairs."""

    if arm not in lane.ARMS:
        raise ValueError(f"unknown arm: {arm}")
    control = dict(manifest["control"])
    timeouts = dict(manifest["timeouts_seconds"])
    run_id = f"product-ab-{uuid.uuid4().hex}"
    task_text = str(task["task_text"])

    routing: dict[str, Any] | None = None
    if arm in {"omh", "omh_mixture"}:
        routing = arms.resolve_delegation(omh_executable=omh_executable, task_text=task_text)
    model = _model_for_arm(arm, control, routing)
    route = arms.resolve_route(
        omh_executable=omh_executable, model=model["id"], effort=model["effort"]
    )

    unit = arms.benchmark_unit(
        file_scope=arms.unit_file_scope(),
        checks=list(task["verification_commands"]),
        route=route,
    )
    prompt = (
        arms.base_prompt(task_text)
        if arm == "hermes"
        else arms.delegation_prompt(task_text, unit)
    )

    attempts: list[arms.Attempt] = []
    verification: dict[str, Any] = {"ran": False, "status": "not_run", "checks": []}
    # Every gate run, not just the last. A repair turn runs the gate a
    # second time, and overwriting `verification` would drop the first
    # run's minutes out of the wall clock entirely.
    gate_seconds = 0.0
    merge_base_verdicts: dict[tuple[str, str], bool] = {}
    with TemporaryDirectory(prefix="omh-product-ab-scratch-") as scratch_text:
        scratch = Path(scratch_text)
        with repo_lib.candidate_workspace(
            repository, str(task["merge_base"]), workspace_root, f"{task['task_id']}-{arm}"
        ) as workspace:
            leaked = grading.validator_paths_already_present(workspace, task)
            if leaked:
                raise ValueError(
                    f"{task['task_id']}: the validator is present in the candidate workspace: {leaked}"
                )
            if live:
                attempts.append(
                    arms.run_hermes(
                        hermes_executable=hermes_executable,
                        workspace=workspace,
                        provider=model["provider"],
                        model=model["id"],
                        effort=model["effort"],
                        prompt=prompt,
                        toolsets=str(manifest["execution"]["toolsets"]),
                        timeout=int(timeouts["task"]),
                        kind="primary",
                    )
                )
                if arm in {"omh", "omh_mixture"} and attempts[-1].ok:
                    # The gate reads the regression modules the grader reads.
                    # They are modules the pull request did not touch, so the
                    # restore cannot remove a legitimate change.
                    grading.restore_regression_modules(repository, task, workspace)
                    verification = _run_gate(
                        python_executable=python_executable,
                        workspace=workspace,
                        scratch=scratch,
                        task=task,
                        timeout=int(timeouts["verification"]),
                        merge_base_verdicts=merge_base_verdicts,
                    )
                    gate_seconds += float(verification.get("seconds") or 0.0)
                    repairs = int(manifest["execution"].get("omh_repair_attempts", 0))
                    if verification["status"] == "failed" and repairs:
                        attempts.append(
                            arms.run_hermes(
                                hermes_executable=hermes_executable,
                                workspace=workspace,
                                provider=model["provider"],
                                model=model["id"],
                                effort=model["effort"],
                                prompt=_repair_prompt(prompt, verification),
                                toolsets=str(manifest["execution"]["toolsets"]),
                                timeout=int(timeouts["task"]),
                                kind="repair",
                            )
                        )
                        grading.restore_regression_modules(repository, task, workspace)
                        verification = _run_gate(
                            python_executable=python_executable,
                            workspace=workspace,
                            scratch=scratch,
                            task=task,
                            timeout=int(timeouts["verification"]),
                            merge_base_verdicts=merge_base_verdicts,
                        )
                        gate_seconds += float(verification.get("seconds") or 0.0)
            claim = grading.completion_claim(workspace)
            if (
                arm in {"omh", "omh_mixture"}
                and verification["ran"]
                and verification["status"] == "failed"
                and claim["claim"] == "complete"
            ):
                # The verification gate is what withdraws a completion claim the
                # declared checks contradict. That is the behaviour this arm is
                # here to measure, so it is recorded, never silently applied.
                claim = {"claim": "blocked", "reason": "withdrawn_by_verification_gate"}
            grading.materialize_validator(repository, task, workspace)
            grading.restore_regression_modules(repository, task, workspace)
            target = grading.run_modules(
                python_executable=python_executable,
                workspace=workspace,
                scratch=scratch,
                modules=list(task["test_modules"]),
                timeout=int(timeouts["validator"]),
            )
            regression = grading.run_modules(
                python_executable=python_executable,
                workspace=workspace,
                scratch=scratch,
                modules=list(task["regression_modules"]),
                timeout=int(timeouts["validator"]),
            )
            final_digest = lane.tree_digest(workspace) if manifest.get("digest_final_tree") else None

    grade = grading.grade(
        target=target,
        regression=regression,
        claim=claim,
        run_failed=live and not any(attempt.ok for attempt in attempts),
    )
    record = {
        "schema_version": lane.RUN_SCHEMA,
        "created_at": _now(),
        "run_id": run_id,
        "task_id": str(task["task_id"]),
        "pull_request": int(task["pull_request"]),
        "arm": arm,
        "task_index": task_index,
        "live": bool(live),
        "corpus_digest": corpus_digest,
        "task_digest": str(task["task_text_sha256"]),
        "prompt_profile": arms.PROMPT_PROFILE if arm != "hermes" else "bare_task",
        "execution_path": str(manifest["execution"]["path"]),
        "model": model,
        "route": {
            "selected_model": route.get("selected_model"),
            "selected_reasoning_effort": route.get("selected_reasoning_effort"),
            "model_family": route.get("model_family"),
        },
        "routing": routing,
        "attempts": [
            {"kind": attempt.kind, "seconds": attempt.seconds, "ok": attempt.ok}
            for attempt in attempts
        ],
        # Model time plus gate time. The verification gate runs on the OMH arms
        # only, so charging it to nobody would take minutes off one side of the
        # comparison and hand them to the "faster" headline.
        "wall_clock_seconds": round(
            sum(attempt.seconds for attempt in attempts) + gate_seconds, 3
        ),
        "model_seconds": round(sum(attempt.seconds for attempt in attempts), 3),
        "verification_gate_seconds": round(gate_seconds, 3),
        "usage": {
            "total_tokens": _usage_total(attempts, "total_tokens"),
            "input_tokens": _usage_total(attempts, "input_tokens"),
            "output_tokens": _usage_total(attempts, "output_tokens"),
            "cache_read_tokens": _usage_total(attempts, "cache_read_tokens"),
            "turns": _usage_total(attempts, "turns"),
            "tool_calls": _usage_total(attempts, "tool_calls"),
        },
        "cost": {
            "reported_usd": _reported_cost(attempts),
            "list_price_usd": approximate_cost_usd(
                model["id"],
                {
                    "input_tokens": _usage_total(attempts, "input_tokens"),
                    "output_tokens": _usage_total(attempts, "output_tokens"),
                    "cache_read_tokens": _usage_total(attempts, "cache_read_tokens"),
                    "total_tokens": _usage_total(attempts, "total_tokens"),
                },
            ),
        },
        "verification_gate": {**verification, **gate_disclosure(task)},
        "grade": grade,
        "failure_receipt": next(
            (attempt.failure for attempt in attempts if attempt.failure), None
        ),
    }
    if final_digest:
        record["final_tree_digest"] = final_digest
    if not lane.artifact_is_safe(record):
        raise ValueError("benchmark record failed metadata-only artifact safety")
    lane.append_jsonl(output, record)
    return record


def _run_gate(
    *,
    python_executable: str,
    workspace: Path,
    scratch: Path,
    task: Mapping[str, Any],
    timeout: int,
    merge_base_verdicts: dict[tuple[str, str], bool] | None = None,
) -> dict[str, Any]:
    """The corpus checks plus the task-linked postcondition, resolved per run.

    The corpus checks are the task's pinned criteria, which the candidate has
    already run green by the time the gate sees them. The task-linked command
    is derived from what this candidate actually changed -- the pre-existing
    tests that directly import its edited files, less any already red at the
    merge base -- so the gate can disagree with a candidate whose edits broke
    the code those tests exercise. It is re-resolved on every gate run because
    a repair turn changes the diff; `merge_base_verdicts` is shared across
    those runs so each module runs at the merge base once.
    """

    merge_base = str(task["merge_base"])
    known = {} if merge_base_verdicts is None else merge_base_verdicts

    def green_at_merge_base(modules: Sequence[str]) -> list[str]:
        return grading.green_at_merge_base(
            python_executable=python_executable,
            repository=workspace,
            merge_base=merge_base,
            modules=modules,
            root=scratch,
            timeout=timeout,
            known=known,
        )

    linked = arms.task_linked_postcondition(
        workspace,
        merge_base,
        list(task.get("test_paths") or []),
        green_at_merge_base=green_at_merge_base,
    )
    commands = list(task["verification_commands"])
    if linked["command"]:
        commands.append(str(linked["command"]))
    verification = arms.run_verification(
        python_executable=python_executable,
        workspace=workspace,
        scratch=scratch,
        commands=commands,
        timeout=timeout,
    )
    return {**verification, "task_linked_postcondition": linked}


def _repair_prompt(original: str, verification: Mapping[str, Any]) -> str:
    failed = [
        str(row["command"])
        for row in verification.get("checks") or []
        if row.get("status") != "passed"
    ]
    return (
        f"{original}\n\nVERIFICATION GATE: the declared checks did not pass. "
        f"Failing checks: {'; '.join(failed)}. Fix the cause, re-run them, and "
        "write the completion file again."
    )


def run_matrix(
    *,
    manifest: Mapping[str, Any],
    payload: Mapping[str, Any],
    selected_arms: Sequence[str],
    repository: Path,
    workspace_root: Path,
    output: Path,
    omh_executable: str,
    hermes_executable: str,
    python_executable: str,
    live: bool,
    max_paid_calls: int,
    task_limit: int | None = None,
) -> dict[str, Any]:
    """Every selected arm on every task, one task in flight at a time."""

    tasks = list(payload["tasks"])
    if task_limit is not None:
        tasks = tasks[:task_limit]
    scheduled = len(tasks) * len(selected_arms)
    worst_case = worst_case_paid_calls(manifest, len(tasks), selected_arms)
    if live and (max_paid_calls < 1 or worst_case > max_paid_calls):
        raise ValueError(
            f"paid calls in the worst case ({worst_case}) exceed the explicit "
            f"budget ({max_paid_calls}); {scheduled} runs are scheduled and an "
            f"OMH arm may spend one repair turn on top of its own"
        )
    records: list[dict[str, Any]] = []
    for index, task in enumerate(tasks):
        for arm in arm_order(index, selected_arms):
            records.append(
                execute_one(
                    manifest=manifest,
                    task=task,
                    arm=arm,
                    corpus_digest=str(payload["corpus_digest"]),
                    repository=repository,
                    workspace_root=workspace_root,
                    output=output,
                    omh_executable=omh_executable,
                    hermes_executable=hermes_executable,
                    python_executable=python_executable,
                    live=live,
                    task_index=index,
                )
            )
    failures = [record for record in records if record["failure_receipt"]]
    return {
        "schema_version": lane.RECEIPT_SCHEMA,
        "observed_at": _now(),
        "corpus_digest": str(payload["corpus_digest"]),
        "arms": list(selected_arms),
        "tasks": len(tasks),
        "scheduled": scheduled,
        "paid_calls_worst_case": worst_case,
        "graded": len(records),
        "passed": sum(bool(record["grade"]["pass"]) for record in records),
        "failed_runs": len(failures),
        "false_completions": sum(
            bool(record["grade"]["false_completion"]) for record in records
        ),
        "paid_calls_launched": sum(len(record["attempts"]) for record in records) if live else 0,
        "output": output.name,
        "ok": not failures,
    }
