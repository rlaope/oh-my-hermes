"""`omh_team`: split accepted work into helper parts that count as done only on a passing check.

A separate tool from `omh_agent_board` on purpose. That tool prepares and
never runs anything, and its description says so; this one runs each part's
frozen check command. Keeping them apart keeps both descriptions true and
leaves `omh_agent_board` byte-identical (`tests/fixtures/agent_board_golden.json`).

The engine is `omh.workflows.team`, imported inside the handler with the
#1623 guard: Hermes execs this directory with its own interpreter, and a
module-level `omh` import would turn "this host has no team engine" into an
ImportError on every call.
"""
from __future__ import annotations

from collections.abc import Mapping
import json
import os
from pathlib import Path
from typing import Any

from .. import runtime_paths
from ..host_observation import host_session_id
from ..host_process import process_alive

KANBAN_TASK_ENV = "HERMES_KANBAN_TASK"
# Hermes marks a cron run with this; its approval can be an automatic `approve`.
CRON_SESSION_ENV = "HERMES_CRON_SESSION"
_OUTPUT_TAIL_CHARS = 4000
# Each read-only git call `_helper_work` makes, the same bound as the working-tree fingerprint's.
_GIT_READ_TIMEOUT_SECONDS = 15

# Process memory, never disk (`omh.workflows.team.TeamContext`): the exact
# command lists a person approved through the host gate since this Hermes
# started, keyed (durable session, team_id, commands_digest), and the nonce of
# every check this process ran. Only a successful `team_start` below adds to
# the first, and the host runs that handler only after its approval gate.
_APPROVED_TEAMS: set[tuple[str, str, str]] = set()
_OBSERVED_CHECKS: set[str] = set()

OMH_TEAM_SCHEMA = {
    "name": "omh_team",
    "description": (
        "Run an accepted plan as parallel helper parts. Each part counts as done only when OMH runs "
        "that part's check command itself and it exits 0. team_start needs the accepted plan's "
        "plan_ref and each check command written in that plan as check: `<command>`; the person approves the "
        "command list. Dispatch the returned delegate_task entries unchanged, call team_reconcile "
        "after helpers return, and follow its fix-up entries until team_state is done or blocked. "
        "Relay each say line; events newer than since_seq describe each helper's progress."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["team_start", "team_reconcile", "team_status"]},
            "team_id": {"type": "string"},
            "plan_ref": {"type": "string"},
            "units": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "unit_id": {"type": "string"},
                        "title": {"type": "string"},
                        "depends_on": {"type": "array", "items": {"type": "string"}},
                        "verification_command": {"type": "string"},
                    },
                    "required": ["unit_id", "title", "verification_command"],
                },
            },
            "max_repair_attempts": {"type": "integer"},
            "since_seq": {"type": "integer"},
        },
        "required": ["action", "team_id"],
        "additionalProperties": False,
    },
}

_ACTIONS = ("team_start", "team_reconcile", "team_status")


def omh_team_handler(args: Mapping[str, object], **kwargs: object) -> str:
    action = str(args.get("action", ""))
    if action not in _ACTIONS:
        return _refused(action, "invalid_action", "Use team_start, team_reconcile or team_status.")
    if os.environ.get(KANBAN_TASK_ENV, "").strip():
        # A board worker's own session: it must never accept its own work (R8).
        return _refused(action, "called_from_board_worker", "A board worker cannot start or check a team.")
    try:
        from omh.workflows import team
    except ImportError:
        return _refused(action, "omh_team_core_unavailable", "This install has no team engine.")
    if _BUNDLE_IMPORT_FAILURE:
        return _refused(action, "omh_team_core_unavailable", "This install has no team engine.",
                        detail=f"bundle_module_unimportable:{_BUNDLE_IMPORT_FAILURE}")
    # A sibling Hermes could not exec can sit in sys.modules as a stub with
    # none of its names (#1623): a missing component, not an AttributeError.
    try:
        session_is_delegated = _nudge_budget.session_is_delegated
        read_omh_todo = _runtime_reader.read_omh_todo
        reading_session_id = _runtime_reader.reading_session_id
        todo_items_digest = _todo_store.todo_items_digest
        compaction_ancestors = _live_session.compaction_ancestors
        _ = (_evidence_tool.run_verification_command, _cost_receipt.build_cost_receipt)
    except AttributeError:
        return _refused(action, "omh_team_core_unavailable", "This install has no team engine.",
                        detail="bundle_module_incomplete")
    try:
        session = host_session_id(dict(kwargs))
        hermes_home = runtime_paths.default_hermes_home()
        omh_home = runtime_paths.default_omh_home()
        if session and session_is_delegated(session, omh_home=str(runtime_paths.plugin_home(None))):
            # The host reported this session as a delegate child: a helper
            # must not reconcile, and so accept, its own part (R8).
            return _refused(action, "called_from_helper", "A helper cannot start or check its own team.")
        durable = reading_session_id(hermes_home, session)
        if not durable:
            return _refused(action, "session_required", "A team needs a named chat session.")
        # The session the team was started under. Hermes' rotating compaction
        # moves this conversation to a new session id; the team stays under
        # the segment that started it, reached only through the links Hermes
        # wrote (`team.owning_session`).
        owner = durable
        lineage: Mapping[str, Any] = {}
        team_id = args.get("team_id")
        if isinstance(team_id, str) and not team.owning_session(omh_home, durable, team_id):
            lineage = compaction_ancestors(str(hermes_home), durable)
            owner = team.owning_session(omh_home, durable, team_id, lineage.get("ancestors") or []) or durable
            if owner == durable and lineage.get("status") != "resolved" and action != "team_start":
                raise team.lineage_refusal(str(lineage.get("reason") or ""))
        ctx = team.TeamContext(
            omh_home=omh_home, session_ref=owner, runner=_runner(team),
            fingerprint=_fingerprint, now=_now, host_guard=_host_floor, helper_work=_helper_work,
            approved=_APPROVED_TEAMS, observed_checks=_OBSERVED_CHECKS, dispatcher_alive=process_alive,
        )
        if action == "team_start" and _cron_session():
            # A cron run's approval can be answered by `approve` mode with no
            # person reading the command list.
            return _refused(action, "called_from_cron", "A scheduled run cannot start a team; start it in a chat.")
        if action == "team_start":
            # A team resumed from a later segment binds to the plan it was
            # started with, which is that segment's own.
            plan = dict(read_omh_todo(omh_home, hermes_home, session_ref=session if owner == durable else owner))
            if not plan.get("own_record") and owner == durable:
                # This segment holds no plan of its own. The plan the person
                # accepted earlier in this conversation is under the segment
                # Hermes compacted it from, found through the same links.
                lineage = lineage or compaction_ancestors(str(hermes_home), durable)
                for earlier in lineage.get("ancestors") or []:
                    found = dict(read_omh_todo(omh_home, hermes_home, session_ref=earlier))
                    if found.get("own_record"):
                        plan = found
                        break
            plan["items_digest"] = todo_items_digest(plan.get("items"))
            try:
                result = team.team_start(
                    ctx, team_id=args.get("team_id"), units=args.get("units"), plan=plan,
                    plan_ref=args.get("plan_ref"), workdir=runtime_paths.runtime_cwd(),
                    max_repair_attempts=args.get("max_repair_attempts"),
                )
            except team.TeamRefusal as refusal:
                payload = team.refusal_result(action, refusal)
                if refusal.reason == "plan_ref_mismatch" and plan.get("own_record") and plan.get("plan_stage") == "accepted":
                    # The accepted plan's reference, so the caller can bind to
                    # the plan the person accepted. Approval still rests on the
                    # verbatim command match and the person's own prompt.
                    payload["plan_ref"] = plan["items_digest"]
                return json.dumps(payload, sort_keys=True)
            _APPROVED_TEAMS.add((owner, str(result["team_id"]), str(result["commands_digest"])))
        elif action == "team_reconcile":
            result = team.team_reconcile(ctx, team_id=args.get("team_id"), since_seq=args.get("since_seq", 0))
        else:
            result = team.team_status(ctx, team_id=args.get("team_id"), cost=_cost(hermes_home, omh_home, durable),
                                      since_seq=args.get("since_seq", 0))
        return json.dumps(result, sort_keys=True)
    except team.TeamRefusal as refusal:
        return json.dumps(team.refusal_result(action, refusal), sort_keys=True)
    except (runtime_paths.RuntimeBindingError, OSError, ValueError):
        # Never echo exception strings, paths or command output.
        return _refused(action, "team_store_unavailable", "The team record could not be reached.")
    except (KeyError, TypeError):
        # A record that passed the shape check yet misses a field it is read by.
        return _refused(action, "team_store_unreadable", "The team record could not be read.")


def _host_floor(command: str) -> str | None:
    """Hermes' own command floor and the person's `approvals.deny`, or a refusal.

    The plugin runs inside the Hermes process, so `tools.approval` is the
    host's own module: its hardline floor ("never, even under yolo") and the
    operator's deny rules. Without it there is no second layer, and no team
    command is allowed at all.
    """
    try:
        from tools.approval import _floor_block, _user_deny_block
    except ImportError:
        return "host_command_floor_unavailable"
    try:
        if _floor_block(command) is not None or _user_deny_block(command) is not None:
            return "command_refused_by_host"
    except Exception:
        # A floor that raises has not said yes: fail closed, reason only.
        return "host_command_floor_unavailable"
    return None


def _cron_session() -> bool:
    try:
        from tools.approval_context import _is_cron_approval_context
    except ImportError:
        return os.environ.get(CRON_SESSION_ENV, "").strip().lower() in ("1", "true", "yes", "on")
    return bool(_is_cron_approval_context())


def _runner(team: Any) -> Any:
    run_verification_command = _evidence_tool.run_verification_command

    def run(tokens: list[str], workdir: Path, timeout: int) -> Any:
        observed = run_verification_command(tokens, workdir=workdir, timeout=timeout)
        output = str(observed.get("output", ""))
        return team.CheckRun(
            outcome=str(observed["outcome"]),
            exit_code=observed["exit_code"] if isinstance(observed["exit_code"], int) else None,
            output_tail=output[-_OUTPUT_TAIL_CHARS:],
        )

    return run


def _fingerprint(workdir: Path) -> tuple[str, str | None]:
    from omh.quality.working_tree_fingerprint import working_tree_content_fingerprint

    observed = working_tree_content_fingerprint(workdir)
    return (str(observed.state.value), observed.fingerprint)


def _helper_work(workdir: Path, branch: str) -> str:
    """Where a helper's work stands against this workspace: one of `team.HELPER_WORK_STATES`.

    Hermes makes the helper's worktree at ``<repo>/.worktrees/<name>`` on branch
    ``hermes-subagent/<name>`` (`tools/subagent_worktree.py`). A helper can leave
    that branch inside its worktree (a detached HEAD, a branch of its own), so
    the worktree is found by its path as well as by the branch, and both the
    branch's last commit and the commit the worktree's HEAD is on must be in the
    history of this workspace's HEAD. Read-only git, through the same
    minimal-environment runner as the checks; uncommitted changes in the
    worktree are read with the checks' own fingerprint.
    """
    ref = "refs/heads/" + branch
    code, listed = _git(workdir, ["git", "-c", "core.fsmonitor=false", "--no-optional-locks", "for-each-ref",
                                  "--format=%(refname)%00%(objectname)", ref])
    if code != 0:
        return "unreadable"
    row = next((fields for fields in (line.split("\0") for line in listed.splitlines()) if fields[0] == ref), None)
    if row is not None and len(row) != 2:
        return "unreadable"
    code, worktrees = _git(workdir, ["git", "-c", "core.fsmonitor=false", "--no-optional-locks", "worktree", "list",
                                     "--porcelain"])
    if code != 0:
        return "unreadable"
    found = _helper_worktree(worktrees, ref, branch.rpartition("/")[2])
    if row is None and found is None:
        return "absent"
    commits = [row[1]] if row is not None else []
    if found is not None:
        path, head = found
        # The branch checked out in this workspace itself is this workspace's
        # own state, which the check sees as it is.
        if Path(path).is_dir() and not workdir.resolve().is_relative_to(Path(path).resolve()):
            state, _ = _fingerprint(Path(path))
            if state == "dirty":
                return "uncommitted_changes"
            if state != "clean":
                return "unreadable"
        if head:
            commits.append(head)
    for commit in commits:
        code, _ = _git(workdir, ["git", "-c", "core.fsmonitor=false", "--no-optional-locks", "merge-base",
                                 "--is-ancestor", commit, "HEAD"])
        if code == 1:
            return "commits_not_merged"
        if code != 0:
            return "unreadable"
    return "merged"


def _helper_worktree(porcelain: str, ref: str, name: str) -> tuple[str, str] | None:
    """``(path, head)`` of the helper's worktree in `git worktree list --porcelain`, or None.

    Matched by the path Hermes gave it (``.worktrees/<name>``) or by its branch
    still checked out somewhere, so a helper that left the branch is still found.
    """
    for block in porcelain.split("\n\n"):
        fields = dict(line.split(" ", 1) for line in block.splitlines() if " " in line)
        path = fields.get("worktree", "")
        named = Path(path).name == name and Path(path).parent.name == ".worktrees"
        if path and (named or fields.get("branch") == ref):
            return path, fields.get("HEAD", "")
    return None


def _git(workdir: Path, argv: list[str]) -> tuple[int | None, str]:
    """One bounded git read: its exit code (None when it never exited or its output would not decode)."""
    try:
        observed = _evidence_tool.run_verification_command(argv, workdir=workdir, timeout=_GIT_READ_TIMEOUT_SECONDS)
    except (OSError, UnicodeError):
        return None, ""
    code = observed.get("exit_code")
    return (code if observed.get("outcome") == "exited" and isinstance(code, int) else None), str(observed.get("output", ""))


def _now() -> float:
    import time

    return time.time()


def _cost(hermes_home: Path, omh_home: Path, session: str) -> dict[str, Any]:
    receipt = _cost_receipt.build_cost_receipt(hermes_home=hermes_home, omh_home=omh_home, session_id=session)
    if receipt.get("status") != "observed":
        return {"status": "not_observed", "say": "Cost for this conversation is not available."}
    helpers = (receipt.get("sources") or {}).get("delegated_children") or {}
    total = receipt.get("observed_cost_usd")
    return {
        "status": "observed",
        "conversation_cost_usd": total,
        "helpers_cost_usd": helpers.get("cost_usd"),
        "unpriced_tokens": receipt.get("unpriced_tokens"),
        "say": ("Cost so far for this whole conversation, helpers included: "
                + (f"${float(total):,.4f}." if total is not None else "no priced usage recorded yet.")),
    }


def _refused(action: str, reason: str, say: str, *, detail: str = "") -> str:
    payload: dict[str, object] = {"schema_version": "omh_team_result/v1", "action": action, "status": "refused",
                                  "reason": reason, "say": say, "delegate_task": None}
    if detail:
        # Which bundle module failed to import: a module name, never a message or a path.
        payload["detail"] = detail
    return json.dumps(payload, sort_keys=True)


# Module scope, not call time: Hermes can evict the bundle from sys.modules
# while this handler stays registered, and a call-time relative import then
# has no parent package (#1979). Guarded so a host missing one still registers
# the tool and names the module instead of failing to load (#1623). Last, so
# an import cycle finds every name.
try:
    from .. import cost_receipt as _cost_receipt
    from .. import live_session as _live_session
    from .. import runtime_reader as _runtime_reader
    from .. import todo_store as _todo_store
    from ..hooks import nudge_budget as _nudge_budget
    from . import evidence_tool as _evidence_tool
except ImportError as _bundle_import_error:
    _BUNDLE_IMPORT_FAILURE = _bundle_import_error.name or "unknown"
else:
    _BUNDLE_IMPORT_FAILURE = ""
