from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
from typing import Any, Callable, Mapping, Sequence

from ..runtime.artifacts import append_journal_observation, create_run, show_run
from ..system.paths import OmhPaths
from .executor_readiness import probe_executor_readiness
from .fanout_contracts import FANOUT_CLAIM_BOUNDARY

FANOUT_DISPATCH_SCHEMA_VERSION = "fanout_dispatch_summary/v1"
DISPATCH_CLAIM_BOUNDARY = (
    "A dispatch summary records observed local subprocess activity only. It is not verification, review, CI, "
    "merge-readiness, or merge evidence, and omh never merges unit branches itself."
)

# Spawnability is a data property: profiles listed here have a local headless
# CLI template. Every other profile (hermes, omx/omo/omc runtimes, generic,
# unassigned) gets a prepared-prompt fallback and is never spawned.
DISPATCH_COMMAND_TEMPLATES: dict[str, tuple[str, ...]] = {
    "codex": ("codex", "exec", "{prompt}"),
    "claude-code": ("claude", "-p", "{prompt}", "--permission-mode", "acceptEdits"),
}


def build_unit_prompt(unit: Mapping[str, Any], goal_text: str) -> str:
    boundary = unit.get("boundary", {}) if isinstance(unit.get("boundary"), Mapping) else {}
    file_scope = ", ".join(str(path) for path in boundary.get("file_scope", []))
    do_not_touch = ", ".join(str(path) for path in boundary.get("do_not_touch", []))
    checks = "; ".join(str(check) for check in unit.get("integration_checks", []))
    lines = [
        f"Work unit: {unit.get('title', unit.get('unit_id'))}",
        f"Overall goal: {goal_text.strip()}",
        f"Stay strictly inside these paths: {file_scope}.",
    ]
    if do_not_touch:
        lines.append(f"Do not touch: {do_not_touch} (owned by sibling units).")
    lines.append(f"Work on branch {unit.get('branch_suggestion', '')} in the current worktree.")
    if checks:
        lines.append(f"Before finishing: {checks}.")
    lines.append("Commit your work; do not merge or push other branches.")
    return "\n".join(lines)


def verify_goal_matches_contract(contract: Mapping[str, Any], goal_text: str) -> None:
    """Refuse dispatch when the supplied goal diverges from the frozen contract.

    The contract stores the goal as a digest only (privacy); the operator
    re-supplies the text at dispatch time, so integrity must be re-proven.
    """
    from hashlib import sha256

    normalized = " ".join(goal_text.split())
    digest = sha256(normalized.encode("utf-8")).hexdigest()
    expected = str(contract.get("goal", {}).get("sha256", ""))
    if digest != expected:
        raise ValueError(
            "goal text does not match the digest frozen in the fanout contract; "
            "dispatch refuses to run a diverged goal (re-run fanout prepare for a new goal)"
        )


def dispatch_fanout(
    paths: OmhPaths,
    contract: Mapping[str, Any],
    *,
    goal_text: str,
    repo_root: Path,
    base_sha: str,
    concurrency: int = 2,
    timeout: int = 1800,
    only_units: Sequence[str] | None = None,
    dry_run: bool = False,
    runner: Callable[..., Any] = subprocess.run,
    readiness: Callable[..., dict[str, object]] = probe_executor_readiness,
) -> dict[str, Any]:
    verify_goal_matches_contract(contract, goal_text)
    units = {str(unit["unit_id"]): unit for unit in contract.get("units", []) if isinstance(unit, Mapping)}
    order = [str(unit_id) for unit_id in contract.get("merge_plan", {}).get("merge_order", [])]
    selected = set(only_units) if only_units else set(order)
    results: dict[str, dict[str, Any]] = {}

    for unit_id in order:
        unit = units[unit_id]
        if _already_completed(paths, unit):
            # Completed units satisfy dependencies whether or not they are in
            # the current selection, so partial re-dispatch of downstream
            # units works after an earlier run (or manual recovery) finished
            # their prerequisites.
            results[unit_id] = _skipped(unit, "already_completed", merge_ready=True)
        elif unit_id not in selected:
            results[unit_id] = _skipped(unit, "not_selected")

    pending = [unit_id for unit_id in order if unit_id not in results]
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        while pending:
            ready = [
                unit_id
                for unit_id in pending
                if all(_dependency_satisfied(results.get(dep)) for dep in units[unit_id].get("depends_on", []))
            ]
            blocked = [
                unit_id
                for unit_id in pending
                if any(_dependency_failed(results.get(dep)) for dep in units[unit_id].get("depends_on", []))
            ]
            for unit_id in blocked:
                results[unit_id] = _blocked(units[unit_id], results)
                pending.remove(unit_id)
            ready = [unit_id for unit_id in ready if unit_id in pending]
            if not ready:
                if pending and not blocked:
                    for unit_id in list(pending):
                        results[unit_id] = _blocked(units[unit_id], results)
                        pending.remove(unit_id)
                continue
            futures = {
                unit_id: pool.submit(
                    _dispatch_unit,
                    paths,
                    units[unit_id],
                    goal_text=goal_text,
                    repo_root=repo_root,
                    base_sha=base_sha,
                    timeout=timeout,
                    dry_run=dry_run,
                    runner=runner,
                    readiness=readiness,
                )
                for unit_id in ready
            }
            for unit_id, future in futures.items():
                results[unit_id] = future.result()
                pending.remove(unit_id)

    summary_units = [results[unit_id] for unit_id in order]
    return {
        "schema_version": FANOUT_DISPATCH_SCHEMA_VERSION,
        "fanout_id": contract.get("fanout_id", ""),
        "dry_run": dry_run,
        "merge_order": order,
        "units": summary_units,
        "merge_ready_units": [entry["unit_id"] for entry in summary_units if entry.get("merge_ready")],
        "auto_merge": False,
        "dependency_bar": (
            "A satisfied dependency means only that the owner agent process exited 0. "
            "It is not verified, reviewed, or correct work."
        ),
        "base_sha": base_sha,
        "claim_boundary": f"{DISPATCH_CLAIM_BOUNDARY} {FANOUT_CLAIM_BOUNDARY}",
    }


def _dispatch_unit(
    paths: OmhPaths,
    unit: Mapping[str, Any],
    *,
    goal_text: str,
    repo_root: Path,
    base_sha: str,
    timeout: int,
    dry_run: bool,
    runner: Callable[..., Any],
    readiness: Callable[..., dict[str, object]],
) -> dict[str, Any]:
    unit_id = str(unit["unit_id"])
    run_ref = str(unit.get("run_ref", unit_id))
    owner = str(unit.get("handoff", {}).get("executor_target", "choose"))
    template = DISPATCH_COMMAND_TEMPLATES.get(owner)
    if template is None:
        return {
            "unit_id": unit_id,
            "run_ref": run_ref,
            "owner": owner,
            "status": "unsupported_for_local_dispatch",
            "merge_ready": False,
            "fallback": "use the unit handoff as a prepared prompt for this owner",
        }
    probe = readiness(paths, owner)
    if str(probe.get("status", "")) != "ready":
        return {
            "unit_id": unit_id,
            "run_ref": run_ref,
            "owner": owner,
            "status": "executor_not_ready",
            "readiness_status": str(probe.get("status", "unknown")),
            "merge_ready": False,
        }
    prompt = build_unit_prompt(unit, goal_text)
    argv = [part.replace("{prompt}", prompt) for part in template]
    worktree = _worktree_path(repo_root, unit_id)
    if dry_run:
        return {
            "unit_id": unit_id,
            "run_ref": run_ref,
            "owner": owner,
            "status": "dry_run_planned",
            "planned_argv": [part if part != prompt else "<unit prompt>" for part in argv],
            "worktree_path": str(worktree),
            "merge_ready": False,
        }
    from .worktree_creator import ensure_fanout_unit_worktree

    worktree_record = ensure_fanout_unit_worktree(
        paths,
        repo_root=repo_root,
        unit_id=unit_id,
        branch=str(unit.get("branch_suggestion", f"agent/{unit_id}")),
        base_sha=base_sha,
        runner=runner,
    )
    if not worktree_record.get("created"):
        return {
            "unit_id": unit_id,
            "run_ref": run_ref,
            "owner": owner,
            "status": "worktree_failed",
            "reason": str(worktree_record.get("reason", "")),
            "merge_ready": False,
        }
    worktree = Path(str(worktree_record["worktree_path"]))
    _ensure_unit_run(paths, unit, owner)
    append_journal_observation(
        paths,
        {
            "target_type": "run",
            "target_id": run_ref,
            "run_id": run_ref,
            "event": "worker_dispatch",
            "status": "observed",
            "summary": f"local dispatch of unit {unit_id} to {owner}",
            "worker_ref": unit_id,
            "worktree_ref": str(worktree),
        },
    )
    try:
        completed = runner(argv, cwd=str(worktree), text=True, capture_output=True, timeout=timeout)
        exit_code = int(getattr(completed, "returncode", 1))
        output_tail = str(getattr(completed, "stdout", "") or "")[-2000:]
    except FileNotFoundError:
        exit_code, output_tail = 127, f"{argv[0]} not found on PATH"
    except subprocess.TimeoutExpired:
        exit_code, output_tail = 124, f"unit timed out after {timeout}s"
    except OSError as exc:
        exit_code, output_tail = 1, f"spawn failed: {exc}"
    status = "observed" if exit_code == 0 else "failed"
    append_journal_observation(
        paths,
        {
            "target_type": "run",
            "target_id": run_ref,
            "run_id": run_ref,
            "event": "worker_result",
            "status": status,
            "summary": f"unit {unit_id} exit {exit_code}: {output_tail[-300:]}",
            "worker_ref": unit_id,
            "worktree_ref": str(worktree),
        },
    )
    return {
        "unit_id": unit_id,
        "run_ref": run_ref,
        "owner": owner,
        "status": "completed" if exit_code == 0 else "failed",
        "exit_code": exit_code,
        "worktree_path": str(worktree),
        "merge_ready": exit_code == 0,
    }


def _ensure_unit_run(paths: OmhPaths, unit: Mapping[str, Any], owner: str) -> None:
    run_ref = str(unit.get("run_ref", unit.get("unit_id", "")))
    run_path = paths.runtime_runs_dir / run_ref / "run.json"
    if run_path.exists():
        return
    create_run(
        paths,
        {
            "run_id": run_ref,
            "skill": "fanout-unit",
            "harness": "coding-handling",
            "trigger": f"fanout:dispatch:{unit.get('unit_id')}",
            "privacy": "metadata_only",
            "inputs_summary": f"fanout unit {unit.get('unit_id')} owned by {owner}",
            "outputs_summary": "local dispatch bridge run",
            "verification_summary": "observed via journal worker_dispatch/worker_result events",
        },
    )


def _already_completed(paths: OmhPaths, unit: Mapping[str, Any]) -> bool:
    run_ref = str(unit.get("run_ref", ""))
    try:
        shown = show_run(paths, run_ref)
    except (OSError, ValueError, KeyError):
        return False
    if not isinstance(shown, dict):
        return False
    for event in shown.get("journal_events", []) or []:
        if (
            isinstance(event, dict)
            and str(event.get("event", "")) in {"worker_result", "executor_result_observed"}
            and str(event.get("status", "")) == "observed"
        ):
            return True
    return False


def _dependency_satisfied(result: dict[str, Any] | None) -> bool:
    if result is None:
        return False
    # dry_run_planned satisfies dependencies so a --dry-run renders the full
    # plan; live dispatch only advances on an observed exit-0 result.
    return (
        result.get("status") in {"completed", "already_completed", "dry_run_planned"}
        or bool(result.get("merge_ready"))
    )


def _dependency_failed(result: dict[str, Any] | None) -> bool:
    if result is None:
        return False
    return result.get("status") in {
        "failed",
        "blocked_by_dependency",
        "executor_not_ready",
        "unsupported_for_local_dispatch",
        "worktree_failed",
        "not_selected",
    } and not result.get("merge_ready")


def _blocked(unit: Mapping[str, Any], results: Mapping[str, dict[str, Any]]) -> dict[str, Any]:
    entry = _skipped(unit, "blocked_by_dependency")
    entry["blocked_on"] = [
        str(dep)
        for dep in unit.get("depends_on", []) or []
        if _dependency_failed(results.get(str(dep)))
    ]
    return entry


def _skipped(unit: Mapping[str, Any], status: str, *, merge_ready: bool = False) -> dict[str, Any]:
    return {
        "unit_id": str(unit["unit_id"]),
        "run_ref": str(unit.get("run_ref", "")),
        "owner": str(unit.get("handoff", {}).get("executor_target", "choose")),
        "status": status,
        "merge_ready": merge_ready,
    }


def _worktree_path(repo_root: Path, unit_id: str) -> Path:
    return repo_root.parent / f"{repo_root.name}-fanout-{unit_id}"
