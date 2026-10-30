from __future__ import annotations

from datetime import datetime, timezone
import time
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from typing import Any
import uuid

from common import CONDITIONS, append_jsonl, artifact_is_safe, load_object, tree_digest
from corpus import all_specs, materialize
from omh_live import (
    head_omitted_blocks,
    prompt_digest,
    prompt_for_condition,
    run_current_session_trial,
    run_trial,
)
from omp_live import run_omp_trial
from validation import validate


def _snapshot(root: Path) -> dict[str, bytes]:
    snapshot = {}
    canonical_root = root.resolve(strict=True)
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if path.is_symlink():
            continue
        if path.is_file() and ".git" not in relative.parts and "__pycache__" not in path.parts and ".venv" not in path.parts and ".pytest_cache" not in path.parts:
            snapshot[path.relative_to(root).as_posix()] = path.read_bytes()
    return snapshot


def _git_init(workspace: Path) -> None:
    """Make the workspace a git worktree so Hermes LSP engages.

    `agent/lsp/workspace.py: find_git_worktree` only checks that `.git` exists,
    so a bare `git init` (no commit) suffices.
    """
    subprocess.run(["git", "init", "-q"], cwd=workspace, check=True, capture_output=True, timeout=60)


def _test_env(root: Path, workspace: Path) -> Path:
    """A ready interpreter for the workspace's tests, outside the workspace (so it is never a mutation).

    The live session's `python` is Hermes' own venv: no pytest and no `benchapp` on its path.
    Weak models then spend dozens of turns on `pip install` and venv paths, which measures the
    host, not the edit surface. Both arms get this same interpreter: pytest installed and the
    workspace's `src/` on `sys.path` through a `.pth` file. Returns the interpreter path.
    """
    import shutil

    uv = shutil.which("uv")
    if uv is None:
        raise RuntimeError("--test-env needs `uv` on PATH")
    venv = root / "testenv"
    subprocess.run([uv, "venv", "-q", "--python", sys.executable, str(venv)], check=True, capture_output=True, timeout=120)
    python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    subprocess.run([uv, "pip", "install", "-q", "--python", str(python), "pytest"], check=True, capture_output=True, timeout=300)
    purelib = subprocess.run([str(python), "-c", "import sysconfig;print(sysconfig.get_paths()['purelib'])"],
                             check=True, capture_output=True, text=True, timeout=60).stdout.strip()
    Path(purelib, "bench_workspace_src.pth").write_text(str(workspace / "src") + "\n", encoding="utf-8")
    return python


def _live_task(instance_prompt: str, test_python: Path | None = None) -> str:
    """The task text every harness wraps in a condition prompt."""
    tests = ""
    if test_python is not None:
        tests = (f"Run tests with `{test_python} -m pytest -q`; pytest and this package are already "
                 "installed for that interpreter, so do not install anything.\n\n")
    return (
        f"{instance_prompt}\n\n"
        f"{tests}"
        "Write the final machine answer as JSON to `.omh-benchmark-answer.json` in the "
        "working directory. Do not include prose in that file."
    )


def doctor(base: Path, manifest_path: Path) -> dict[str, Any]:
    manifest = load_object(manifest_path)
    harness = manifest.get("live_harness")
    models = manifest.get("models")
    ok = (
        manifest.get("schema_version") == "omh_live_model_tool_benchmark/v1"
        and isinstance(harness, dict)
        and harness.get("kind") == "omh_hermes_child"
        and harness.get("observation_schema_version") == "routing_observation/v1"
        and isinstance(models, list)
        and {"qwen", "deepseek", "glm"}.issubset(
            {str(item.get("family")) for item in models if isinstance(item, dict)}
        )
    )
    return {
        "schema_version": "omh_live_model_tool_doctor/v1",
        "ok": ok,
        "benchmark_root": str(base),
        "capabilities": {
            "offline_fake": True,
            "live_harness": "omh_hermes_child",
            "explicit_dispatch": True,
            "observation_schema": "routing_observation/v1",
        },
    }


def execute_one(
    base: Path,
    manifest: dict[str, Any],
    split: str,
    template_id: str,
    task_class: str,
    seed: int,
    condition: str,
    output: Path,
    harness: str = "fake",
    *,
    model: dict[str, Any] | None = None,
    omh_executable: str = "omh",
    hermes_executable: str = "hermes",
    current_session_provider: str | None = None,
    edit_surface: str = "patch",
    edit_directive: bool | str = False,
    git_init_workspace: bool = False,
    test_env: bool = False,
    omp_executable: str = "omp",
) -> dict[str, Any]:
    if condition not in CONDITIONS:
        raise ValueError(f"condition must be one of: {', '.join(CONDITIONS)}")
    with TemporaryDirectory(prefix="omh-bench-") as root_text:
        root = Path(root_text)
        workspace = root / "workspace"
        private = root / "controller"
        workspace.mkdir()
        private.mkdir()
        instance, golden_path = materialize(split, template_id, task_class, seed, workspace, private)
        if git_init_workspace:
            _git_init(workspace)
        test_python = _test_env(root, workspace) if test_env and harness in {"hermes_current_session", "omp"} else None
        initial = _snapshot(workspace)
        answer_path = workspace / ".omh-benchmark-answer.json"
        events: list[dict[str, Any]] = []
        route: dict[str, object] = {}
        failure_receipt: dict[str, object] | None = None
        trial_task_digest = instance.fixture_digest
        trial_prompt_digest: str | None = None
        session_id: str | None = None
        wall_seconds: float | None = None
        harness_metrics: dict[str, Any] | None = None
        observation: dict[str, object] = {
            "status": "offline_fake",
            "tools": None,
            "tokens": None,
            "cost_usd": None,
        }

        if harness == "fake":
            result_path = root / "fake-result.json"
            request_path = root / "fake-request.json"
            prompt_path = root / "fake-prompt.txt"
            # The offline harness has no route, so the condition prompt is
            # built with an empty one (no calibration); its digest is still the
            # exact text this condition hands the harness.
            fake_prompt = prompt_for_condition(_live_task(instance.prompt), {}, condition)
            # Bytes, not text: a text write would emit CRLF on Windows.
            prompt_path.write_bytes(fake_prompt.encode("utf-8"))
            trial_prompt_digest = prompt_digest(fake_prompt)
            request_path.write_text(
                json.dumps(
                    {
                        "template_id": template_id,
                        "task_class": task_class,
                        "seed": seed,
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            environment = {
                "PATH": os.environ.get("PATH", ""),
                "HOME": str(root / "home"),
                "LMT_OUTPUT": str(result_path),
                "LMT_REQUEST": str(request_path),
                "LMT_WORKSPACE": str(workspace),
                "LMT_PROMPT": str(prompt_path),
            }
            completed = subprocess.run(
                [sys.executable, str(base / "adapters" / "fake_harness.py")],
                cwd=workspace,
                env=environment,
                capture_output=True,
                check=False,
                text=True,
                timeout=int(manifest["timeouts_seconds"]["hard"]),
            )
            if completed.returncode:
                raise RuntimeError(f"fake harness failed with exit {completed.returncode}")
            result = load_object(result_path)
            if result.get("prompt_sha256") != trial_prompt_digest:
                raise RuntimeError("fake harness did not receive the condition prompt")
            answer_path.write_text(json.dumps(result["answer"], sort_keys=True), encoding="utf-8")
            events = list(result["events"])
            for event in events:
                if event.get("mutating"):
                    event["checkpoint_pass"] = True
        elif harness in {"omh", "hermes_current_session"}:
            if model is None:
                raise ValueError("live Hermes harness requires a model")
            prompt = _live_task(instance.prompt, test_python)
            started = time.time()
            if harness == "hermes_current_session":
                trial = run_current_session_trial(
                    omh_executable=omh_executable,
                    hermes_executable=hermes_executable,
                    workspace=workspace,
                    task=prompt,
                    model=str(model["id"]),
                    provider=current_session_provider or str(model["provider"]),
                    effort=str(model["effort"]),
                    condition=condition,
                    parent_run_id=f"bench-parent-{uuid.uuid4().hex}",
                    run_id=f"bench-child-{uuid.uuid4().hex}",
                    timeout=int(manifest["timeouts_seconds"].get(task_class, 300)),
                    confirmed=True,
                    edit_surface=edit_surface,
                    directive=edit_directive,
                )
            else:
                trial = run_trial(
                    omh_executable=omh_executable,
                    hermes_executable=hermes_executable,
                    workspace=workspace,
                    omh_home=root / "omh-home",
                    task=prompt,
                    model=str(model["id"]),
                    provider=str(model["provider"]),
                    effort=str(model["effort"]),
                    condition=condition,
                    parent_run_id=f"bench-parent-{uuid.uuid4().hex}",
                    run_id=f"bench-child-{uuid.uuid4().hex}",
                    timeout=int(manifest["timeouts_seconds"].get(task_class, 300)),
                    confirmed=True,
                )
            wall_seconds = round(time.time() - started, 3)
            route = dict(trial["route"])
            raw_failure_receipt = trial.get("failure_receipt")
            failure_receipt = dict(raw_failure_receipt) if isinstance(raw_failure_receipt, dict) else None
            trial_task_digest = str(trial["task_digest"])
            raw_prompt_digest = trial.get("prompt_digest")
            trial_prompt_digest = raw_prompt_digest if isinstance(raw_prompt_digest, str) else None
            observation = dict(trial["observation"])
            raw_session_id = trial.get("session_id")
            session_id = raw_session_id if isinstance(raw_session_id, str) else None
        elif harness == "omp":
            if model is None:
                raise ValueError("the omp harness requires a model")
            if edit_directive:
                raise ValueError("the edit directives name Hermes tools; the omp harness takes none")
            started = time.time()
            trial = run_omp_trial(
                omp_executable=omp_executable,
                workspace=workspace,
                task=_live_task(instance.prompt, test_python),
                model=str(model["id"]),
                provider=str(model["provider"]),
                effort=str(model["effort"]),
                condition=condition,
                timeout=int(manifest["timeouts_seconds"].get(task_class, 300)),
                confirmed=True,
            )
            wall_seconds = round(time.time() - started, 3)
            route = dict(trial["route"])
            failure_receipt = trial["failure_receipt"]
            trial_task_digest = str(trial["task_digest"])
            trial_prompt_digest = str(trial["prompt_digest"])
            observation = dict(trial["observation"])
            session_id = trial["session_id"]
            harness_metrics = trial["harness_metrics"]
        else:
            raise ValueError("harness must be fake, omh, hermes_current_session, or omp")

        grade = validate(
            template_id,
            task_class,
            workspace,
            golden_path,
            answer_path,
            events,
            initial,
        )
        record = {
            "schema_version": "omh_live_model_tool_run/v1",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "instance_id": instance.instance_id,
            "split": split,
            "condition": condition,
            "harness": harness,
            "edit_surface": edit_surface if harness == "hermes_current_session" else None,
            "edit_directive": edit_directive if harness == "hermes_current_session" else None,
            "git_init_workspace": git_init_workspace if harness == "hermes_current_session" else None,
            "test_env": test_env if harness in {"hermes_current_session", "omp"} else None,
            "execution_path": harness,
            "model": model,
            "task_digest": trial_task_digest,
            "prompt_digest": trial_prompt_digest,
            "head_omitted_blocks": head_omitted_blocks(condition),
            "route": route,
            "observation": observation,
            "session_id": session_id,
            "wall_seconds": wall_seconds,
            "harness_metrics": harness_metrics,
            "failure_receipt": failure_receipt,
            "grade": grade,
            "final_tree_digest": tree_digest(workspace),
        }
        append_jsonl(output, record)
        if not artifact_is_safe(record):
            output.unlink(missing_ok=True)
            raise ValueError("benchmark record failed metadata-only artifact safety")
        return record


def run_matrix(
    base: Path,
    manifest: dict[str, Any],
    split: str,
    condition: str,
    output: Path,
    harness: str = "fake",
    *,
    models: list[dict[str, Any]] | None = None,
    omh_executable: str = "omh",
    hermes_executable: str = "hermes",
    current_session_provider: str | None = None,
    edit_surface: str = "patch",
    edit_directive: bool | str = False,
    git_init_workspace: bool = False,
    test_env: bool = False,
    max_paid_calls: int = 0,
    templates: list[str] | None = None,
    seeds: list[int] | None = None,
    omp_executable: str = "omp",
) -> dict[str, Any]:
    selected = models or [None]
    specs = all_specs(split)
    if templates:
        wanted = set(templates)
        specs = [spec for spec in specs if spec[0] in wanted]
    if seeds:
        specs = [spec for spec in specs if spec[2] in set(seeds)]
    scheduled = len(selected) * len(specs)
    if harness in {"omh", "hermes_current_session", "omp"} and (max_paid_calls < 1 or scheduled > max_paid_calls):
        raise ValueError(
            f"scheduled paid calls ({scheduled}) exceed explicit budget ({max_paid_calls})"
        )
    records: list[dict[str, Any]] = []
    for model in selected:
        for template_id, task_class, seed in specs:
            records.append(
                execute_one(
                    base,
                    manifest,
                    split,
                    template_id,
                    task_class,
                    seed,
                    condition,
                    output,
                    harness,
                    model=model,
                    omh_executable=omh_executable,
                    hermes_executable=hermes_executable,
                    current_session_provider=current_session_provider,
                    edit_surface=edit_surface,
                    edit_directive=edit_directive,
                    git_init_workspace=git_init_workspace,
                    test_env=test_env,
                    omp_executable=omp_executable,
                )
            )
    return {
        "schema_version": "omh_live_model_tool_run_receipt/v1",
        "split": split,
        "condition": condition,
        "edit_surface": edit_surface,
        "harness": harness,
        "scheduled": len(records),
        "graded": len(records),
        "passed": sum(bool(item["grade"]["pass"]) for item in records),
        "output": str(output),
        "paid_calls_launched": len(records) if harness in {"omh", "hermes_current_session", "omp"} else 0,
    }
