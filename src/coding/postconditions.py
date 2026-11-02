"""Task-linked postconditions: the tests a unit's own changes reach.

A contract unit's declared `verification_commands` say what the operator chose
to check. Nothing ties them to the task: a compile pass and a few modules from
the same package pass whether or not the change is right, and a gate that
re-runs them can never disagree with the executor that already ran them green.

A unit that declares `task_linked_test_runner` adds one postcondition whose
subject is derived from what the unit actually changed, not from what anyone
wrote down: the dispatcher reads the observed diff between the base and the
unit's committed head, walks the local codegraph's recorded import edges
backwards one step, and runs the runner on every test module that directly
imports a changed file (plus any changed test module itself). The command's
exit status is the verdict, recorded like every other dispatcher-observed
check; wording cannot move it.

One step, not the whole reverse closure: on this repository a single core
module's closure reaches most of the suite, which would turn a task-linked
check into a slower full run. A direct importer is a test that names the
changed module, which is the smallest set a static reader can call "the tests
of this change". Everything here is pure: the graph and the changed paths are
passed in, and nothing is imported, executed, or spawned.
"""

from __future__ import annotations

import shlex
from typing import Any, Mapping, Sequence

from ..codegraph import CODEGRAPH_TEST_SELECTION_SCHEMA_VERSION, select_tests_for_changes

from .fanout_contracts import FanoutContractError, require_shell_free_command, verification_command_argv

TASK_LINKED_POSTCONDITION_SCHEMA_VERSION = "task_linked_postcondition/v1"
TASK_LINKED_TEST_RULE = "direct_importer_tests"
# Distance 0 is a changed test module itself; 1 is a test importing a changed
# file. The codegraph selection records both in the same field.
TASK_LINKED_MAX_DISTANCE = 1
MAX_TASK_LINKED_TEST_RUNNER_CHARS = 200

TASK_LINKED_STATUSES = ("tests_selected", "no_reachable_tests", "not_resolved")
TASK_LINKED_POSTCONDITION_CLAIM_BOUNDARY = (
    "A task-linked postcondition names the test modules that directly import the files a unit changed, "
    "read from recorded import edges. Its exit status is observed only when the dispatcher ran it; the "
    "selection has the codegraph's blind spots (dynamic imports, fixtures read by path, spawned commands, "
    "non-Python changes), and a passing run is not the full suite, review, CI, or merge evidence."
)


def normalized_task_linked_test_runner(value: object, index: int) -> str:
    """Collapse a unit's declared runner to its stored shape, or '' when absent.

    The runner is a command prefix the selected test paths are appended to,
    for example `PYTHONPATH=tests python -m unittest`. It is parsed here, at
    freeze time, so a runner no dispatcher could execute fails where the
    operator is still holding it.
    """
    if value is None:
        return ""
    if not isinstance(value, str) or not value.strip():
        raise FanoutContractError(
            f"unit at index {index} task_linked_test_runner must be a non-empty command prefix string"
        )
    runner = " ".join(value.split())
    if len(runner) > MAX_TASK_LINKED_TEST_RUNNER_CHARS:
        raise FanoutContractError(
            f"unit at index {index} task_linked_test_runner must be at most "
            f"{MAX_TASK_LINKED_TEST_RUNNER_CHARS} chars"
        )
    try:
        require_shell_free_command(runner, field="task_linked_test_runner")
    except FanoutContractError as exc:
        raise FanoutContractError(f"unit at index {index} {exc}") from exc
    verification_command_argv(runner)
    return runner


def task_linked_criterion(runner: str) -> str:
    """The completion criterion a unit declaring a runner reads in its prompt.

    It states the rule and the command so the executor can run the same check
    the dispatcher will run; it replaces the prose "unit tests covering the
    unit's file_scope pass", which named no command anyone could observe.
    """
    return (
        f"`{runner} <test files>` passes for every test module that directly imports a file you changed "
        "(and every test module you changed); list them with `omh codegraph tests --changed <paths>` "
        "and take the entries at distance 0 or 1. OMH runs this check itself on your changes "
        "and records its exit status."
    )


def resolve_task_linked_postcondition(
    graph: Mapping[str, Any],
    changed_paths: Sequence[str],
    runner: str,
    *,
    exclude_test_paths: Sequence[str] = (),
) -> dict[str, Any]:
    """Resolve the rule against observed changed paths into one runnable command.

    `exclude_test_paths` removes named modules from the selection, recorded
    separately so the exclusion is visible; the benchmark lane uses it to keep
    a hidden validator out of its gate.
    """
    changed = sorted({str(path) for path in changed_paths if str(path).strip()})
    record: dict[str, Any] = {
        "schema_version": TASK_LINKED_POSTCONDITION_SCHEMA_VERSION,
        "rule": TASK_LINKED_TEST_RULE,
        "runner": runner,
        "selection_schema": CODEGRAPH_TEST_SELECTION_SCHEMA_VERSION,
        "changed_paths": changed,
        "selected_test_paths": [],
        "command": "",
        "status": "no_reachable_tests",
        "claim_boundary": TASK_LINKED_POSTCONDITION_CLAIM_BOUNDARY,
    }
    if not changed:
        return record
    selection = select_tests_for_changes(dict(graph), changed)
    excluded = set(exclude_test_paths)
    reached = sorted(
        str(item["path"])
        for item in selection["selected_tests"]
        if int(item["distance"]) <= TASK_LINKED_MAX_DISTANCE
    )
    selected = [path for path in reached if path not in excluded]
    if excluded:
        record["excluded_test_paths"] = [path for path in reached if path in excluded]
    record["selected_test_paths"] = selected
    if selected:
        record["command"] = f"{runner} {' '.join(shlex.quote(path) for path in selected)}"
        record["status"] = "tests_selected"
    return record


def unresolved_task_linked_postcondition(runner: str, reason: str) -> dict[str, Any]:
    """The record for a rule that could not be resolved, which fails closed."""
    return {
        "schema_version": TASK_LINKED_POSTCONDITION_SCHEMA_VERSION,
        "rule": TASK_LINKED_TEST_RULE,
        "runner": runner,
        "selection_schema": CODEGRAPH_TEST_SELECTION_SCHEMA_VERSION,
        "changed_paths": [],
        "selected_test_paths": [],
        "command": "",
        "status": "not_resolved",
        "reason": reason,
        "claim_boundary": TASK_LINKED_POSTCONDITION_CLAIM_BOUNDARY,
    }
