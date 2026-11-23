"""The one runner behind every scenario-suite lane's `bench.py`.

`benchmarks/automation-intent/v1/bench.py` and `benchmarks/orchestration/v1/bench.py`
are thin: each names its suite module, its lane directory and its grader, and
calls `main` here, so the two lanes cannot drift apart.

`validate` and `grade` are offline and free. `run` spends money: it answers
each scenario of one split through `omh coding hermes-child dispatch
--confirm-dispatch`, and refuses without `--allow-paid-live`,
`--max-paid-calls` and `--confirm`. Nothing here runs by default or in CI.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
from types import ModuleType
from typing import Any

from omh.quality.scenario_suite import (
    DEFAULT_SPLIT,
    HELD_OUT_SPLIT,
    SPLITS,
    Failure,
    ScenarioSuiteError,
    build_suite_report,
    canonical_digest,
    child_dispatch_argv,
    corpus_errors,
    load_split,
    new_observations_document,
    normalize_split,
    observation_from_dispatch,
    read_decision_file,
    read_json_document,
    scenario_prompt,
    skill_texts_digest,
    split_isolation_errors,
    summary_lines,
    write_json,
)

ROOT = Path(__file__).resolve().parents[1]
ARM_KINDS = ("skill-text", "bare")
# Grace for the dispatcher to stop its own Hermes child after SIGTERM. The
# dispatcher relays the signal to the child's process group and reaps it; a
# SIGKILL straight away would leave that group running with no parent.
TERMINATION_GRACE_SECONDS = 30

Grader = Callable[[Mapping[str, Any], Mapping[str, Any]], tuple[Failure, ...]]


def artifact_label(path: Path) -> str:
    """How a report names its observations file: repository-relative, or a bare name.

    An absolute path outside the checkout can carry a home directory or user
    name, so it is reduced to its file name.
    """
    resolved = Path(path).resolve()
    if resolved.is_relative_to(ROOT.resolve()):
        return resolved.relative_to(ROOT.resolve()).as_posix()
    return f"outside-repository:{resolved.name}"


def emit(value: object) -> None:
    print(json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False))


def validation_payload(suite: ModuleType, lane: Path) -> dict[str, object]:
    """Both splits against the schema, against each other, and against the manifest."""
    manifest = read_json_document(lane / "manifest.json")
    errors: list[str] = []
    splits: dict[str, object] = {}
    corpora = {}
    for split in SPLITS:
        corpus = load_split(lane, split)
        corpora[split] = corpus
        errors.extend(f"{split}: {error}" for error in corpus_errors(
            corpus,
            suite=suite.SUITE,
            split=split,
            categories=suite.CATEGORIES,
            id_prefix=suite.ID_PREFIX,
            scenario_errors=suite.scenario_errors,
        ))
        digest = canonical_digest(corpus)
        count = len(corpus.get("scenarios", []))
        splits[split] = {"scenarios": count, "digest": digest}
        pinned = manifest.get("splits", {}).get(split, {})
        if pinned.get("digest") != digest or pinned.get("scenarios") != count:
            errors.append(f"manifest pins {split} at {pinned.get('scenarios')} scenarios / {pinned.get('digest')}; corpus is {count} / {digest}")
    errors.extend(split_isolation_errors(corpora[SPLITS[0]], corpora[HELD_OUT_SPLIT], categories=suite.CATEGORIES))
    return {"suite": suite.SUITE, "valid": not errors, "errors": errors, "splits": splits}


def skill_texts(lane: Path, arm_kind: str) -> list[tuple[str, str]]:
    manifest = read_json_document(lane / "manifest.json")
    files = manifest["arms"][arm_kind]["skill_files"]
    return [(name, (ROOT / name).read_text(encoding="utf-8")) for name in files]


def _platform_argv(argv: list[str]) -> list[str]:
    """Run a `.py` launcher under this interpreter, with `-P` off its own directory."""
    if argv[0].endswith(".py"):
        return [sys.executable, "-P", *argv]
    return argv


def _child_environment() -> dict[str, str]:
    # The prompt can hold Korean or Japanese text: encode it as UTF-8 whatever
    # the platform's locale encoding is (cp1252 on many Windows machines).
    return {**os.environ, "PYTHONIOENCODING": "utf-8"}


def _dispatch(command: list[str], prompt: str, timeout: int) -> tuple[bool, bool, str]:
    """Run one child-boundary command; return (launched, timed_out, stdout)."""
    try:
        process = subprocess.Popen(
            _platform_argv(command),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_child_environment(),
        )
    except OSError:
        return False, False, ""
    try:
        stdout, _stderr = process.communicate(prompt, timeout=timeout)
        return True, False, stdout or ""
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.communicate(timeout=TERMINATION_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
        return True, True, ""


def build_parser(suite: ModuleType, *, parent_run_id: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=f"{suite.SUITE} scenario suite (operator/maintainer).")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("validate", help="Check both splits, their isolation, and the manifest pins. Offline.")

    grade = sub.add_parser("grade", help="Grade an observations file against one split. Offline.")
    grade.add_argument("--observations", type=Path, required=True)
    grade.add_argument("--split", default=DEFAULT_SPLIT, help="tuning (default) or held-out.")
    grade.add_argument("--output", type=Path, default=None)
    grade.add_argument("--text", action="store_true", help="Print the headline and per-category lines only.")

    run = sub.add_parser("run", help="Answer one split with a live arm through the child boundary. Spends money.")
    run.add_argument("--arm", required=True, help="Name this arm carries in the report.")
    run.add_argument("--arm-kind", choices=ARM_KINDS, required=True)
    run.add_argument("--split", default=DEFAULT_SPLIT, help="tuning (default) or held-out.")
    run.add_argument("--scenario", action="append", default=[], help="Run only this scenario id; repeatable.")
    run.add_argument("--model", required=True)
    run.add_argument("--provider", required=True)
    run.add_argument("--reasoning", required=True)
    run.add_argument("--omh-executable", default="omh")
    run.add_argument("--hermes-executable", default="hermes")
    run.add_argument("--timeout", type=int, default=600)
    run.add_argument("--parent-run-id", default=parent_run_id)
    run.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help="Parent of the per-scenario workspaces; a new directory outside this checkout by default.",
    )
    run.add_argument("--output", type=Path, required=True, help="Observations file to write; must not exist.")
    run.add_argument("--allow-paid-live", action="store_true")
    run.add_argument("--max-paid-calls", type=int, default=0)
    run.add_argument("--confirm", action="store_true", help="Confirm the paid effect boundary.")
    return parser


def main(
    argv: list[str] | None,
    *,
    suite: ModuleType,
    lane: Path,
    grade: Grader,
    parent_run_id: str,
) -> int:
    parser = build_parser(suite, parent_run_id=parent_run_id)
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            payload = validation_payload(suite, lane)
            emit(payload)
            return 0 if payload["valid"] else 1
        if args.command == "grade":
            split = normalize_split(args.split)
            report = build_suite_report(
                suite=suite.SUITE,
                corpus=load_split(lane, split),
                observations=read_json_document(args.observations),
                grade=grade,
                categories=suite.CATEGORIES,
                artifact=artifact_label(args.observations),
            )
            if args.output is not None:
                write_json(args.output, report)
            if args.text:
                print("\n".join(summary_lines(report)))
            else:
                emit(report)
            return 0
        return _run(parser, args, suite=suite, lane=lane)
    except ScenarioSuiteError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2


def _run(parser: argparse.ArgumentParser, args: argparse.Namespace, *, suite: ModuleType, lane: Path) -> int:
    if not args.allow_paid_live:
        parser.error("a live arm requires --allow-paid-live")
    if args.max_paid_calls < 1:
        parser.error("a live arm requires --max-paid-calls")
    if not args.confirm:
        parser.error("a live arm requires --confirm at the effect boundary")
    if args.output.exists():
        parser.error(f"{args.output} exists; a run never appends to another run's observations")
    if not 1 <= args.timeout <= 3600:
        parser.error("--timeout must be from 1 to 3600 seconds")
    if args.workspace is not None and args.workspace.resolve().is_relative_to(ROOT.resolve()):
        parser.error(f"--workspace {args.workspace} is inside this checkout, whose AGENTS.md or CLAUDE.md could reach the arm")
    split = normalize_split(args.split)
    if args.scenario and split == HELD_OUT_SPLIT:
        parser.error("--scenario is refused on the held-out split: a held-out run covers the whole split")
    scenarios = load_split(lane, split)["scenarios"]
    if args.scenario:
        unknown = sorted(set(args.scenario) - {row["id"] for row in scenarios})
        if unknown:
            parser.error(f"not in the {split} split: {', '.join(unknown)}")
        scenarios = [row for row in scenarios if row["id"] in set(args.scenario)]
    if len(scenarios) > args.max_paid_calls:
        parser.error(f"{len(scenarios)} scenarios exceed --max-paid-calls {args.max_paid_calls}")
    texts = skill_texts(lane, args.arm_kind)
    document = new_observations_document(
        suite=suite.SUITE,
        split=split,
        arm=args.arm,
        run={
            "execution_path": "omh_hermes_child",
            "arm_kind": args.arm_kind,
            "model": args.model,
            "provider": args.provider,
            "reasoning": args.reasoning,
            "skill_digest": skill_texts_digest(texts),
        },
    )
    # Outside the checkout by default, so the child never sits in a directory
    # whose AGENTS.md or CLAUDE.md could reach one arm and not the other.
    workspace_root = args.workspace or Path(tempfile.mkdtemp(prefix="omh-scenario-suite-"))
    if args.workspace is None and workspace_root.resolve().is_relative_to(ROOT.resolve()):
        # TMPDIR can point inside the checkout; the default gets the same refusal.
        parser.error(f"the default workspace {workspace_root} is inside this checkout; set TMPDIR elsewhere or pass --workspace")
    # Unique per invocation: the child boundary refuses a run id it has seen.
    nonce = secrets.token_hex(4)
    write_json(args.output, document)
    for index, scenario in enumerate(scenarios, start=1):
        run_id = f"{args.parent_run_id}-{nonce}-{index:04d}"
        workspace = workspace_root / run_id
        workspace.mkdir(parents=True, exist_ok=False)
        prompt = scenario_prompt(
            suite_instructions=suite.SUITE_INSTRUCTIONS,
            decision_contract=suite.DECISION_CONTRACT,
            view=suite.arm_view(scenario),
            skill_texts=texts,
        )
        command = child_dispatch_argv(
            args.omh_executable,
            hermes_executable=args.hermes_executable,
            workspace=workspace,
            model=args.model,
            provider=args.provider,
            reasoning=args.reasoning,
            parent_run_id=args.parent_run_id,
            run_id=run_id,
            timeout=args.timeout,
        )
        # The dispatcher enforces --timeout itself; this outer wait is a backstop.
        launched, timed_out, stdout = _dispatch(command, prompt, args.timeout + 30)
        decision, reason = read_decision_file(workspace)
        document["observations"].append(observation_from_dispatch(
            scenario["id"],
            launched=launched,
            timed_out=timed_out,
            stdout=stdout,
            decision=decision,
            decision_keys=suite.DECISION_KEYS,
            # The scenario's own evidence, set here; the model's file never adds any.
            evidence_links=suite.harness_evidence_links(scenario),
            reason=reason,
        ))
        # Rewritten after every scenario: an interrupted run keeps what it bought.
        write_json(args.output, document)
    emit({
        "suite": suite.SUITE,
        "split": split,
        "arm": args.arm,
        "observations": str(args.output),
        "scenarios_run": len(scenarios),
        "workspaces": str(workspace_root),
        "next": f"python {lane.relative_to(ROOT).as_posix()}/bench.py grade --split {args.split} --observations {args.output}",
    })
    return 0
