"""The three arms.

* ``hermes``       — Hermes alone: one `hermes --oneshot` attempt, bare task.
* ``omh``          — the same model and effort, reached through OMH's coding
  delegation: the route OMH resolves, the calibration that route selects, the
  delegation prompt discipline, and the verification gate.
* ``omh_mixture``  — the same, except the model comes from the category
  mixture OMH's complexity routing resolves, so the cost number stays
  attributable to routing rather than to calibration.

Every arm runs through the same Hermes execution path, so the only differences
between ``hermes`` and ``omh`` are the ones OMH owns.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import shlex
import subprocess
from tempfile import TemporaryDirectory
import time
from typing import Any

import lane
import repo as repo_lib

#: Both arms carry the identical completion contract, so a completion claim
#: means the same thing on both sides of the comparison.
COMPLETION_CONTRACT = (
    "BENCHMARK COMPLETION CONTRACT:\n"
    f"1. Before stopping, write `{lane.COMPLETION_FILE}` at the workspace root.\n"
    '2. That file must be one JSON object: {"status": "complete"} when you '
    'believe the goal is met, or {"status": "blocked", "reason": "<short '
    'reason>"} when it is not.\n'
    "3. Write it exactly once, as the last thing you do, and put no prose in it.\n"
)

WORKSPACE_PREAMBLE = (
    "You are working in a checkout of the oh-my-hermes repository at an "
    "earlier commit. Make the change the task describes in this checkout. "
    "Do not create a branch, do not commit, and do not push. Where an "
    "instruction says to commit, leave the change uncommitted in the working tree."
)

#: The delegation prompt this lane composes, and what it deliberately leaves
#: out. `UNIT_RESULT_RETURN_PROTOCOL` and the unit-branch commit criterion are
#: fanout *transport*: they exist so a dispatched worktree can be collected and
#: merged. There is no fanout collector here, so including them would make the
#: OMH arm spend tokens on an artifact nothing reads. The prompt is the
#: product's own `assemble_unit_prompt` output with `OMITTED_BLOCKS` left out.
#:
#: One transport clause stays in, because it sits inside a shipped sentence
#: rather than in a criterion of its own: `VERIFICATION_STOP_PROTOCOL` ends
#: "commit what passes". Cutting it would mean editing shipped text, and this
#: lane measures shipped text. The contradiction with "do not commit" is
#: resolved instead by the last sentence of `WORKSPACE_PREAMBLE`, which both
#: arms receive, so the resolution cannot move with the arm. `GOAL_ECHO_PROTOCOL`
#: tells the model to stop on a conflict, so an unresolved one surfaces as a
#: decline, and a decline is scored like any other missing claim.
PROMPT_PROFILE = "delegation_without_fanout_transport"

#: The one execution path this lane implements, recorded on every record.
#:
#: `omh coding hermes-child dispatch` is the other Hermes execution boundary,
#: and it is deliberately isolated from the caller's profile: it points HOME
#: and HERMES_HOME at throwaway directories and passes only the named
#: provider's documented environment variables. A machine whose models are
#: reached through a subscription login or a gateway registration cannot
#: authenticate through it, which is why every measured run in the sibling
#: lane also uses the profile path. `doctor` refuses a manifest naming any
#: other path, so this field can never claim a path the lane does not run.
EXECUTION_PATH = "hermes_current_session"

ROUTE_TIMEOUT_SECONDS = 120


@dataclass
class Attempt:
    """One Hermes invocation."""

    kind: str
    seconds: float
    usage: dict[str, Any] = field(default_factory=dict)
    ok: bool = False
    failure: dict[str, Any] | None = None


def prompt_protocol() -> Any:
    """The shipped unit prompt protocol, read in process.

    The lane composes the OMH arm's prompt from the product's own constants
    rather than copying their text, so a calibration the repository revises is
    the calibration the next run measures.
    """

    import sys  # noqa: PLC0415

    if str(lane.REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(lane.REPO_ROOT))
    from omh.coding import unit_prompt_protocol  # noqa: PLC0415

    return unit_prompt_protocol


def base_prompt(task_text: str) -> str:
    return f"{WORKSPACE_PREAMBLE}\n\nTASK:\n{task_text.strip()}\n\n{COMPLETION_CONTRACT}"


#: A check no protocol could write. It marks where the unit's own integration
#: checks sit in the criteria list, so the transport criteria can be read off
#: as everything after it.
TRANSPORT_SENTINEL = "Product-ab transport sentinel check."


def fanout_transport_criteria() -> tuple[str, ...]:
    """The criteria the shipped protocol appends after the unit's own checks.

    Derived, not copied. `completion_criteria_for_unit` builds the criteria
    from the unit data and then appends the fanout-transport criterion
    unconditionally, so asking it for the criteria of a unit whose only check
    is a sentinel, and keeping what comes after the sentinel, leaves exactly
    the criteria that follow the unit's own checks.

    Everything before the sentinel is kept. Dropping "all but the first line of
    an empty unit" instead would also drop any criterion the protocol inserts
    ahead of the integration checks -- a product criterion would then vanish
    from this lane's prompt without anything failing, and the lane would
    measure a product that does not exist.

    The assembler carries the commit criterion as its own block, which
    `OMITTED_BLOCKS` drops; this derivation is the independent check that no
    transport criterion reaches the prompt. They have to be dropped because
    they are transport: they exist so a dispatched worktree can be collected
    and merged, and this lane has no collector. Leaving the commit criterion
    in put a direct contradiction in front of the model, which was told in the
    same prompt not to commit, and falsified `PROMPT_PROFILE`. Deriving the
    text rather than matching it means a rewording upstream stays filtered
    instead of silently reappearing.
    """

    protocol = prompt_protocol()
    criteria = [
        str(criterion)
        for criterion in protocol.completion_criteria_for_unit(
            {"boundary": {}, "integration_checks": [TRANSPORT_SENTINEL]}
        )
    ]
    return tuple(criteria[criteria.index(TRANSPORT_SENTINEL) + 1 :])


#: The assembler blocks this lane leaves out, by `unit_prompt_assembly`
#: block name. Each is fanout transport or fanout framing: the structured
#: return and its parent-clarification escalation feed a collector this lane
#: does not have; the unit title, scope sentence, sibling exclusions, and
#: branch line frame a unit inside a fanout worktree (the scope itself still
#: reaches the model as criterion 1); the commit criterion and the tail's
#: commit instruction exist so a dispatched branch can be merged. Everything
#: else the assembler emits for the unit reaches the model in the assembler's
#: own order, so a block the product adds is a block this lane measures.
OMITTED_BLOCKS: frozenset[str] = frozenset({
    "head.unit_result_return",
    "head.parent_clarification",
    "unit.title",
    "unit.scope",
    "unit.do_not_touch",
    "unit.branch",
    "unit.commit_criterion",
    "tail.unit_result_contract",
    "tail.commit",
})


def prompt_assembly() -> Any:
    """`omh.coding.unit_prompt_assembly`, read in process like `prompt_protocol`."""

    prompt_protocol()  # puts the checkout on sys.path
    from omh.coding import unit_prompt_assembly  # noqa: PLC0415

    return unit_prompt_assembly


def delegation_prompt(task_text: str, unit: Mapping[str, Any]) -> str:
    """The OMH arm's prompt: the product's assembled unit prompt minus transport.

    The shared head, then `WORKSPACE_PREAMBLE`, then the unit zone (criteria,
    tool batching, role, calibration, domain bundle, skills), then the
    completion contract.
    """

    assembled = prompt_assembly().assemble_unit_prompt(
        unit,
        task_text,
        route=dict(unit["handoff"]["model_route"]),
        omit=OMITTED_BLOCKS,
    )

    def zone(name: str) -> str:
        return "\n".join(block.text for block in assembled.blocks if block.zone == name)

    return "\n".join([zone("shared_head"), "", WORKSPACE_PREAMBLE, "", zone("unit"), "", COMPLETION_CONTRACT])


#: The interpreter name a criterion shows the model. A stable token, never the
#: lane's absolute interpreter path: that path differs per machine, so it would
#: change the prompt bytes between machines and hand one arm a convenience the
#: other never sees. `python3` rather than `python`, because a bare `python`
#: is absent on the machines the lane has run on and a model that cannot run
#: the criterion as written ends up judging it by its own authority. The gate
#: puts the lane's interpreter in this token's place.
PROMPT_INTERPRETER = "python3"

#: The corpus spells every verification command with this interpreter name.
CORPUS_INTERPRETER = "python"


#: What `lane.unittest_environment` sets `PYTHONPATH` to. Named here so the
#: criterion prefix and the gate environment are compared by a test rather than
#: kept equal by hand.
GATE_PYTHONPATH = "tests"


def gate_invocation(command: str) -> tuple[tuple[str, ...], list[str]]:
    """The environment prefix and argv for one verification command.

    The single source for both the criterion the model reads and the command
    the gate runs, so the two cannot drift apart. The prefix states the one
    variable the gate's environment sets that decides whether the command
    works at all: the repository's tests import helpers from the `tests`
    directory itself. The argv carries `PROMPT_INTERPRETER`; `run_verification`
    swaps in the lane's interpreter and nothing else.
    """

    argv = shlex.split(command)
    if argv and argv[0] == CORPUS_INTERPRETER:
        argv = [PROMPT_INTERPRETER, *argv[1:]]
    return (f"PYTHONPATH={GATE_PYTHONPATH}",), argv


def criterion_for_command(command: str) -> str:
    """A shell command stated as a criterion the model can run literally.

    Rendered from `gate_invocation`, so the command in the criterion is the
    command the gate runs, with the interpreter named by a stable token.

    `completion_criteria_for_unit` capitalizes the first character of each
    integration check, so a bare `python -m compileall -q src` reached the
    model as `Python -m compileall -q src`. Wrapping the command puts a word in
    the position that gets capitalized and leaves the command alone.
    """

    prefix, argv = gate_invocation(command.strip())
    return f"Run `{shlex.join([*prefix, *argv])}` and make it pass."


#: The whole checkout, the reach the Hermes arm's prompt gives it.
WHOLE_CHECKOUT_SCOPE = "./"


def unit_file_scope() -> list[str]:
    """The benchmark unit's file scope: the whole checkout, as the Hermes arm has.

    The lane compares the same task under two harnesses, so the OMH arm may
    edit whatever the Hermes arm may. A scope of `src/` and `tests/` told the
    OMH arm alone that `docs/` and `skills/` were off limits, and in this
    repository a catalog change regenerates `docs/WORKFLOWS.md` and the skill
    bodies, which a regression module compares byte for byte. Fenced out of
    them, the OMH arm either declined or bent that test to pass, and the gate
    then withdrew the claim; the Hermes arm, never told, regenerated them.

    The completion contract requires `lane.COMPLETION_FILE` at the workspace
    root, and criterion 1 says every edit stays inside the file scope, so the
    scope must cover it; `doctor` fails when it stops doing so. Naming the
    checkout tells neither arm anything about the hidden validator.
    """

    return [WHOLE_CHECKOUT_SCOPE]


#: The runner the task-linked postcondition appends its selected test paths
#: to, spelled with the corpus interpreter so `gate_invocation` renders and
#: runs it exactly like every other check.
TASK_LINKED_RUNNER = f"{CORPUS_INTERPRETER} -m unittest"


def postconditions() -> Any:
    """The shipped task-linked postcondition module, read in process."""

    prompt_protocol()  # puts the checkout on sys.path
    from omh.coding import postconditions as module  # noqa: PLC0415

    return module


def task_linked_criterion() -> str:
    """The shipped task-linked criterion, naming the command the gate runs."""

    prefix, argv = gate_invocation(TASK_LINKED_RUNNER)
    return postconditions().task_linked_criterion(shlex.join([*prefix, *argv]))


def workspace_changed_paths(workspace: Path, merge_base: str) -> list[str]:
    """Every path the candidate changed: tracked edits against the base plus new files.

    The candidate never commits, so the diff is the working tree against the
    merge base, not a commit range.
    """

    tracked = repo_lib.git(workspace, "-c", "core.quotepath=off", "diff", "--name-only", "--no-renames", merge_base)
    untracked = repo_lib.git(workspace, "-c", "core.quotepath=off", "ls-files", "--others", "--exclude-standard")
    return sorted({line for line in (tracked + untracked).splitlines() if line.strip()})


def task_linked_postcondition(
    workspace: Path,
    merge_base: str,
    hidden_test_paths: Sequence[str],
    *,
    green_at_merge_base: Callable[[Sequence[str]], list[str]],
) -> dict[str, Any]:
    """The shipped rule resolved against the candidate's own changes.

    The pull request's own test files are excluded, as they are from the
    regression set: they are the hidden validator, and their merge-base copies
    assert the behaviour the pull request changed, so running them would push
    a correct fix back toward the old behaviour. A module the pull request
    edits is therefore a target test, never a regression check.

    A selected module that is not green at the merge base is excluded too, for
    the reason the corpus admits a task only when its regression set is green
    there: no fix can make a pre-existing failure the candidate's fault. It is
    recorded under `red_at_merge_base_test_paths`, apart from the hidden paths.
    """

    module = postconditions()
    from omh.codegraph import build_codegraph  # noqa: PLC0415

    graph = build_codegraph(workspace)
    changed = workspace_changed_paths(workspace, merge_base)
    hidden = list(hidden_test_paths)
    linked = module.resolve_task_linked_postcondition(
        graph, changed, TASK_LINKED_RUNNER, exclude_test_paths=hidden
    )
    reached = list(linked["selected_test_paths"])
    green = set(green_at_merge_base(reached)) if reached else set()
    red = [path for path in reached if path not in green]
    if not red:
        return linked
    linked = module.resolve_task_linked_postcondition(
        graph, changed, TASK_LINKED_RUNNER, exclude_test_paths=[*hidden, *red]
    )
    excluded_hidden = [path for path in linked["excluded_test_paths"] if path not in red]
    if excluded_hidden:
        linked["excluded_test_paths"] = excluded_hidden
    else:
        del linked["excluded_test_paths"]
    linked["red_at_merge_base_test_paths"] = red
    return linked


def benchmark_unit(
    *, file_scope: Sequence[str], checks: Sequence[str], route: Mapping[str, Any]
) -> dict[str, Any]:
    """The unit shape the shipped protocol functions read.

    The task-linked criterion is the one the shipped contract carries for a
    unit that declares a test runner; the gate runs the command it names.
    """

    return {
        "unit_id": "task",
        "title": "benchmark task",
        "role": "implementation",
        "boundary": {"file_scope": list(file_scope), "do_not_touch": []},
        "integration_checks": [
            *(criterion_for_command(check) for check in checks),
            task_linked_criterion(),
        ],
        "handoff": {"model_route": dict(route)},
    }


def resolve_route(
    *, omh_executable: str, model: str, effort: str, timeout: int = ROUTE_TIMEOUT_SECONDS
) -> dict[str, Any]:
    """`omh coding model-route`: metadata only, never an invocation."""

    completed = subprocess.run(
        [
            omh_executable, "coding", "model-route", "--executor", "hermes",
            "--model", model, "--effort", effort, "--role", "implementation", "--json",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=timeout,
    )
    if completed.returncode:
        raise RuntimeError(f"omh coding model-route failed with exit {completed.returncode}")
    route = json.loads(completed.stdout)
    if not isinstance(route, dict):
        raise RuntimeError("omh coding model-route did not return an object")
    return route


def resolve_delegation(
    *, omh_executable: str, task_text: str, timeout: int = ROUTE_TIMEOUT_SECONDS
) -> dict[str, Any]:
    """`omh coding delegate`: the routing decision OMH makes for this task.

    The task text goes in on stdin, never on argv, and only the deterministic
    routing fields are kept. No model is called to produce any of it.
    """

    completed = subprocess.run(
        [omh_executable, "coding", "delegate", "--executor", "hermes", "--stdin"],
        input=task_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=timeout,
    )
    if completed.returncode:
        raise RuntimeError(f"omh coding delegate failed with exit {completed.returncode}")
    payload = json.loads(completed.stdout)
    complexity = payload.get("request_complexity") or {}
    recommendation = payload.get("complexity_model_recommendation") or {}
    resolved = recommendation.get("resolved") or {}
    return {
        "tier": complexity.get("tier"),
        "score": complexity.get("score"),
        "signals": [str(signal.get("name")) for signal in complexity.get("signals") or []],
        "model_class": recommendation.get("model_class"),
        "chain_status": recommendation.get("chain_status"),
        "resolved_model": resolved.get("model"),
        "resolved_reasoning_effort": resolved.get("reasoning_effort"),
        "chain_length": len(recommendation.get("chain") or []),
    }


def oneshot_argv(
    *,
    hermes_executable: str,
    workspace: Path,
    provider: str,
    model: str,
    effort: str,
    usage_file: Path,
    prompt: str,
    toolsets: str,
) -> list[str]:
    """`hermes --oneshot` against the active profile.

    The prompt is the argument immediately after `--oneshot`: this CLI does
    not read a prompt from stdin. `--in` pins the working directory, because
    process cwd alone is not enough — Hermes otherwise restores the invoking
    user's home directory.
    """

    return [
        hermes_executable,
        "--oneshot",
        prompt,
        "--in",
        str(workspace),
        "--provider",
        provider,
        "--model",
        model,
        "--reasoning",
        effort,
        "--toolsets",
        toolsets,
        "--usage-file",
        str(usage_file),
    ]


def _child_environment(workspace: Path) -> dict[str, str]:
    environment = dict(os.environ)
    environment["TERMINAL_CWD"] = str(workspace)
    return environment


USAGE_KEYS = (
    "estimated_cost_usd", "cost_status", "cost_source", "input_tokens",
    "output_tokens", "cache_read_tokens", "cache_write_tokens",
    "reasoning_tokens", "total_tokens", "api_calls", "model", "provider",
    "completed", "failed", "service_tier", "turns", "tool_calls",
)


def _read_usage(path: Path) -> dict[str, Any]:
    """Every usage key, `None` where the usage file does not carry it.

    An absent key is recorded as `None`, never dropped: a dropped key summed to
    `0.0` downstream, and on the Hermes version the lane ran against the file
    carries no `turns` or `tool_calls`, so two secondary columns read zero on
    every row of both arms -- a measurement nobody took.
    """

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, Mapping):
        return {}
    return {
        key: raw[key] if isinstance(raw.get(key), (str, int, float, bool)) else None
        for key in USAGE_KEYS
    }


def usage_observed(usage: Mapping[str, Any]) -> bool:
    """Whether a usage reading carries any value at all."""

    return any(value is not None for value in usage.values())


def run_hermes(
    *,
    hermes_executable: str,
    workspace: Path,
    provider: str,
    model: str,
    effort: str,
    prompt: str,
    toolsets: str,
    timeout: int,
    kind: str,
) -> Attempt:
    """One paid Hermes invocation. The prompt is never persisted."""

    with TemporaryDirectory(prefix="omh-product-ab-usage-") as usage_root:
        usage_file = Path(usage_root) / "usage.json"
        started = time.monotonic()
        try:
            completed = subprocess.run(
                oneshot_argv(
                    hermes_executable=hermes_executable,
                    workspace=workspace,
                    provider=provider,
                    model=model,
                    effort=effort,
                    usage_file=usage_file,
                    prompt=prompt,
                    toolsets=toolsets,
                ),
                cwd=workspace,
                env=_child_environment(workspace),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return Attempt(
                kind=kind,
                seconds=round(time.monotonic() - started, 3),
                failure={"classification": "timeout", "kind": kind},
            )
        seconds = round(time.monotonic() - started, 3)
        usage = _read_usage(usage_file)
    if completed.returncode:
        return Attempt(
            kind=kind,
            seconds=seconds,
            usage=usage,
            failure={
                "classification": _classify(completed.stderr),
                "kind": kind,
                "exit_code": completed.returncode,
            },
        )
    if not usage_observed(usage):
        # The process finished, so whatever it did to the tree stands and the
        # validator is still the ground truth. Only the metrics are missing:
        # the attempt counts as run, the receipt says so, and the cost columns
        # stay unpriced rather than silently becoming zero.
        return Attempt(
            kind=kind,
            seconds=seconds,
            ok=True,
            failure={"classification": "usage_unavailable", "kind": kind},
        )
    return Attempt(kind=kind, seconds=seconds, usage=usage, ok=True)


def _classify(detail: str) -> str:
    normalized = (detail or "").casefold()
    for markers, classification in (
        (("auth", "credential", "api key", "unauthorized", "forbidden"), "authentication_failed"),
        (("rate limit", "too many requests", "429"), "rate_limited"),
        (("session limit", "usage limit", "quota"), "limit_reached"),
        (("model not found", "model unavailable", "unknown model"), "model_unavailable"),
        (("provider",), "provider_error"),
    ):
        if any(marker in normalized for marker in markers):
            return classification
    return "process_crash"


def run_verification(
    *,
    python_executable: str,
    workspace: Path,
    scratch: Path,
    commands: Sequence[str],
    timeout: int,
) -> dict[str, Any]:
    """The OMH arm's verification gate.

    These are the task's stated criteria — a compile gate and the pre-existing
    regression modules for the touched packages. The pull request's own tests
    are never here: they are the hidden validator.
    """

    rows: list[dict[str, Any]] = []
    environment = lane.unittest_environment(workspace, scratch)
    started = time.monotonic()
    for command in commands:
        try:
            _prefix, argv = gate_invocation(command)
        except ValueError:
            rows.append({"command": command, "status": "failed", "classification": "unparseable"})
            continue
        if argv and argv[0] == PROMPT_INTERPRETER:
            argv = [python_executable, *argv[1:]]
        if not argv:
            rows.append({"command": command, "status": "failed", "classification": "unparseable"})
            continue
        try:
            completed = subprocess.run(
                argv,
                cwd=workspace,
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired):
            rows.append({"command": command, "status": "failed", "classification": "not_observed"})
            continue
        rows.append(
            {
                "command": command,
                "status": "passed" if completed.returncode == 0 else "failed",
                "exit_code": completed.returncode,
            }
        )
    failed = [row for row in rows if row["status"] != "passed"]
    return {
        "ran": True,
        "status": "failed" if failed else "passed",
        "checks": rows,
        "failed_count": len(failed),
        # The gate runs a compile pass and up to six unittest modules, which
        # costs minutes. It runs on the OMH arms only, so leaving it out of the
        # wall clock would take time off exactly one side of the comparison and
        # put it on the "faster" headline.
        "seconds": round(time.monotonic() - started, 3),
    }
