#!/usr/bin/env python3
"""Offline and explicit opt-in 2-model skill-lift benchmark runner (`benchmarks/skill-lift/v1`)."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from grader import (  # noqa: E402
    SKILL_LIFT_REPORT_SCHEMA_VERSION,
    TaskGrade,
    evaluate_model_arm_pair,
    grade_response,
)

CORPUS_PATH = Path(__file__).resolve().parent / "corpus" / "tasks.json"


def load_corpus(path: Path = CORPUS_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_corpus(corpus: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if corpus.get("schema_version") != "omh_skill_lift_corpus/v1":
        errors.append("unexpected corpus schema_version")
    tasks = corpus.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        errors.append("corpus must contain non-empty tasks list")
        return errors
    seen_ids: set[str] = set()
    positives = 0
    negatives = 0
    for idx, task in enumerate(tasks):
        if not isinstance(task, dict):
            errors.append(f"task[{idx}] must be an object")
            continue
        task_id = str(task.get("id") or "")
        if not task_id or task_id in seen_ids:
            errors.append(f"task[{idx}] has missing or duplicate id {task_id!r}")
        seen_ids.add(task_id)
        kind = str(task.get("kind") or "")
        if kind == "positive":
            positives += 1
        elif kind == "negative_control":
            negatives += 1
        else:
            errors.append(f"{task_id}: invalid kind {kind!r}")
        if not task.get("prompt"):
            errors.append(f"{task_id}: missing prompt")
        if not task.get("required_substrings"):
            errors.append(f"{task_id}: missing required_substrings")
    if positives == 0:
        errors.append("corpus must include at least one positive task")
    if negatives == 0:
        errors.append("corpus must include at least one negative_control task")
    return errors


def _fake_adapter_reply(task: dict[str, Any], *, with_skill: bool) -> tuple[str, int]:
    """Deterministic offline simulator for CI validation of the grading/verdict pipeline."""
    kind = str(task["kind"])
    required = [str(x) for x in task.get("required_substrings", ())]
    if kind == "negative_control":
        return f"Direct answer covering {', '.join(required)}.", 120 if not with_skill else 135
    if with_skill:
        return f"Skill-guided answer enforcing: {', '.join(required)}.", 240
    # Baseline without skill misses one counter-default constraint on 75% of positive tasks.
    task_hash = int(hashlib.sha256(str(task["id"]).encode("utf-8")).hexdigest()[:8], 16)
    if task_hash % 4 == 0:
        return f"Bare answer covering {', '.join(required)}.", 190
    forbidden = [str(x) for x in task.get("forbidden_substrings", ())]
    return f"Bare shortcut answer: {forbidden[0] if forbidden else 'missing guardrail'}.", 190


def _hermes_child_reply(task: dict[str, Any], *, model: str, with_skill: bool) -> tuple[str, int]:
    prompt = str(task["prompt"])
    if with_skill:
        prompt = f"Use the `omh-{task['skill']}` skill rules for this request.\n\n{prompt}"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "omh.cli",
            "coding",
            "hermes-child",
            "dispatch",
            "--confirm-dispatch",
            "--model",
            model,
        ],
        input=prompt,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"hermes-child dispatch failed ({proc.returncode}): {proc.stderr.strip()[:240]}")
    out = proc.stdout.strip()
    return out, max(1, len(out) // 4)


def run_benchmark(
    *,
    adapter: str,
    models: list[str],
    corpus: dict[str, Any],
    allow_paid_live: bool = False,
    confirm: bool = False,
) -> dict[str, object]:
    if adapter not in {"fake", "hermes-child"}:
        raise ValueError(f"unsupported adapter {adapter!r}")
    if len(models) < 2:
        raise ValueError("skill-lift gate requires at least 2 distinct models")
    if len(set(models)) != len(models):
        raise ValueError("models must be distinct")
    if adapter == "hermes-child" and not (allow_paid_live and confirm):
        raise PermissionError(
            "live hermes-child benchmark requires both --allow-paid-live and --confirm"
        )

    tasks = list(corpus["tasks"])
    per_model: list[dict[str, object]] = []
    for model in models:
        without_grades: list[TaskGrade] = []
        with_grades: list[TaskGrade] = []
        for task in tasks:
            if adapter == "fake":
                wo_text, wo_tok = _fake_adapter_reply(task, with_skill=False)
                w_text, w_tok = _fake_adapter_reply(task, with_skill=True)
            else:
                wo_text, wo_tok = _hermes_child_reply(task, model=model, with_skill=False)
                w_text, w_tok = _hermes_child_reply(task, model=model, with_skill=True)
            without_grades.append(grade_response(task, wo_text, tokens=wo_tok))
            with_grades.append(grade_response(task, w_text, tokens=w_tok))
        per_model.append(
            evaluate_model_arm_pair(
                model=model,
                without_grades=without_grades,
                with_grades=with_grades,
            )
        )

    all_passed = all(bool(item["passed"]) for item in per_model)
    return {
        "schema_version": SKILL_LIFT_REPORT_SCHEMA_VERSION,
        "adapter": adapter,
        "live_observed": adapter == "hermes-child",
        "models": models,
        "corpus_task_count": len(tasks),
        "overall_verdict": "pass" if all_passed else "retire_or_rework",
        "overall_passed": all_passed,
        "model_results": per_model,
        "claim_boundary": (
            "Offline fake-adapter dry-run validates corpus schema, deterministic grading, and "
            "omh_reported_rate/v1 verdict logic only (prepared_not_observed for real models)."
            if adapter == "fake"
            else "Observed live 2-model with-vs-without lift run via hermes-child dispatch."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OMH skill-lift v1 benchmark runner.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("validate", help="Validate the benchmark corpus offline.")

    run_p = sub.add_parser("run", help="Run the 2-model with-vs-without lift benchmark.")
    run_p.add_argument("--adapter", choices=("fake", "hermes-child"), default="fake")
    run_p.add_argument("--models", default="fake-frontier-a,fake-frontier-b", help="Comma-separated model ids (min 2).")
    run_p.add_argument("--allow-paid-live", action="store_true")
    run_p.add_argument("--confirm", action="store_true")
    run_p.add_argument("--output", default="", help="Optional JSON output file path.")

    args = parser.parse_args(argv)
    corpus = load_corpus()
    errors = validate_corpus(corpus)
    if args.command == "validate":
        payload = {"valid": not errors, "errors": errors, "task_count": len(corpus.get("tasks", []))}
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if not errors else 1

    if errors:
        print(json.dumps({"valid": False, "errors": errors}, indent=2), file=sys.stderr)
        return 2
    models = [m.strip() for m in str(args.models).split(",") if m.strip()]
    try:
        report = run_benchmark(
            adapter=str(args.adapter),
            models=models,
            corpus=corpus,
            allow_paid_live=bool(args.allow_paid_live),
            confirm=bool(args.confirm),
        )
    except (PermissionError, ValueError, RuntimeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 2
    serialized = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(serialized + "\n", encoding="utf-8")
    print(serialized)
    return 0 if report["overall_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
