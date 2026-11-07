"""Pure Kanban preparation and correlated, bounded observation contracts.

No executor, database, grant or filesystem access lives here. The host bridge
must enforce native exposure/worker guards and serialize durable board/request
metadata across processes. This object's lock only serializes its local callers.
Persist snapshot(), never the prepare response (which contains ephemeral text).
A pre callback reserves an action; it does not prove invocation or success.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
import copy
from dataclasses import dataclass, field
import hashlib
import json
import math
import re
from threading import RLock
from typing import Final, Protocol, TypeGuard, TypedDict

MAX_INTAKE_BYTES = 256 * 1024
MAX_TASK_IDS = 200
MAX_OPERATION_FACTS = 32
MAX_ATTACHMENT_REFS = 32
MAX_REQUESTS = 200
MAX_SKILLS = 8
BODY_MAX_CHARS = 16_000
_NO_HOOKS: Final[frozenset[str]] = frozenset()
CLAIM_BOUNDARY = "Prepared actions are not invocations; receipts prove only the correlated operation, not review approval, CI or merge."
_REFERENCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_MIME = re.compile(r"[A-Za-z0-9!#$&^_.+-]{1,64}/[A-Za-z0-9!#$&^_.+-]{1,64}\Z")
# `scheduled` is a host status since the floor release: a card parked until
# something unblocks it (`kanban_schedule` on newer hosts). A readback that
# refused it would leave a parked lane unreadable. It is not a `list` filter:
# the floor host's `kanban_list` status enum lacks it, as it lacks `review`.
_STATUSES = frozenset({"triage", "todo", "scheduled", "ready", "running", "review", "blocked", "done", "archived"})
_WORKSPACE_KINDS = frozenset({"scratch", "dir", "worktree"})
# Required arguments, selected optional arguments, required native success keys.
_OPERATIONS = {
    "create": ("title assignee",
               "body parents skills workspace_kind workspace_path priority max_runtime_seconds "
               "idempotency_key initial_status model provider completion_contract goal_mode goal_max_turns",
               "ok task_id status"),
    "link": ("parent_id child_id", "", "ok parent_id child_id"),
    "comment": ("task_id body", "", "ok task_id comment_id"),
    "heartbeat": ("", "task_id note", "ok task_id"),
    "request_review": ("summary", "task_id reviewer metadata", "ok task_id run_id status"),
    "request_changes": ("reason", "task_id", "ok task_id run_id status implementer"),
    "block": ("reason", "task_id kind", "ok task_id run_id status block_kind"),
    "unblock": ("task_id", "", "ok task_id status"),
    "complete": ("", "task_id summary result metadata created_cards", "ok task_id run_id"),
    "show": ("", "task_id", "task parents children comments events runs worker_context"),
    "list": ("", "assignee status tenant include_archived limit", "tasks count limit truncated next_limit promoted"),
    "attachments": ("", "task_id", "ok task_id attachments"),
}
# Operations whose task is not an existing one: a top-level `task_id` is refused on them and required on the rest.
_NO_TASK_ID = ("create", "link", "list")
_TYPES = {"parents": "array", "skills": "array", "created_cards": "array", "tasks": "array", "metadata": "object",
          "limit": "integer", "priority": "integer", "max_runtime_seconds": "integer",
          "include_archived": "boolean", "goal_mode": "boolean", "goal_max_turns": "integer"}
# Inclusive bounds for every integer-typed argument; an unlisted integer name is a
# programming error, so the lookup below indexes rather than defaults.
# `goal_max_turns` has no host ceiling. Each goal turn is a full model turn the
# person pays for while nobody watches the card, and the host default is 20;
# 100 is five times that, so a larger value is refused as a likely slip rather
# than prepared for an unattended worker.
_INTEGER_BOUNDS = {"limit": (1, 200), "priority": (0, 100), "max_runtime_seconds": (60, 86_400), "goal_max_turns": (1, 100)}
# Array arguments that are not task-id lists carry their own ceiling and reason.
_ARRAY_LIMITS = {"skills": (MAX_SKILLS, "too_many_skills")}


class LaneRoleContract(TypedDict):
    skill: str
    workspace_kind: str | None
    requires_parents: bool


# A lane role is a contract, not an instruction: the caller states the role and
# OMH fills the lane fields it implies. The role is removed before the native
# action is built, because native `kanban_create` has no such argument and a
# leaked one would fail the host schema gate as `unavailable`.
LANE_ROLES: Final[dict[str, LaneRoleContract]] = {
    "builder": {"skill": "ulw-work", "workspace_kind": "worktree", "requires_parents": False},
    "verifier": {"skill": "omh-verification-gate", "workspace_kind": "worktree", "requires_parents": True},
    "reviewer": {"skill": "omh-code-review", "workspace_kind": None, "requires_parents": True},
    "docs": {"skill": "omh-docs", "workspace_kind": "worktree", "requires_parents": False},
    "qa": {"skill": "ulw-qa", "workspace_kind": "worktree", "requires_parents": False},
}
# Each parent-requiring role names its own refusal; the lookup indexes so a new
# role cannot fall through to another role's reason code.
_LANE_ROLE_PARENT_REASONS: Final[dict[str, str]] = {
    "verifier": "verifier_requires_parents", "reviewer": "reviewer_requires_parents",
}


class NativeAction(TypedDict):
    tool_name: str
    arguments: dict[str, object]


class AgentBoardRequest(TypedDict):
    schema_version: str
    request_id: str
    request_ref: str
    board_ref: str
    route: str
    operation: str
    lane_role: str
    argument_digest: str
    state: str
    reason: str | None
    observation_ref: str
    expected_observation_ref: str | None
    required_capabilities: list[str]
    missing_capabilities: list[str]
    native_action: NativeAction | None
    observed_receipts: list[dict[str, object]]
    requires_reconciliation: bool
    task_refs: list[str]
    host_scope_ref: str
    host_call_ref: str | None
    in_flight: bool
    reconciled_by: str | None
    claim_boundary: str


class AgentBoardSnapshot(TypedDict):
    schema_version: str
    board: str
    board_ref: str
    observation_ref: str
    requests: list[AgentBoardRequest]
    operation_facts: list[dict[str, object]]
    truncated: bool
    claim_boundary: str


@dataclass(frozen=True)
class HostIdentity:
    """Identity supplied only by handler/hook kwargs, not model JSON authority."""

    session_id: str
    task_id: str
    tool_call_id: str

    def __post_init__(self) -> None:
        for value in (self.session_id, self.task_id, self.tool_call_id):
            _ = _reference(value)

    @property
    def scope_ref(self) -> str:
        return _digest([self.session_id, self.task_id])

    @property
    def call_ref(self) -> str:
        return _digest([self.session_id, self.task_id, self.tool_call_id])


def _reference(value: object) -> str:
    if not isinstance(value, str) or not _REFERENCE.fullmatch(value):
        raise ValueError("invalid_reference")
    return value


def _is_dict(value: object) -> TypeGuard[dict[object, object]]:
    return isinstance(value, dict)


def _is_object(value: object) -> TypeGuard[dict[str, object]]:
    return _is_dict(value) and all(isinstance(key, str) for key in value)


def _is_list(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)


def _json_check(value: object, depth: int = 0) -> None:
    if depth > 16:
        raise ValueError("json_depth_exceeded")
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float) and math.isfinite(value):
        return
    if _is_list(value):
        for item in value:
            _json_check(item, depth + 1)
        return
    if _is_object(value):
        for item in value.values():
            _json_check(item, depth + 1)
        return
    raise ValueError("invalid_json_value")


def _encoded(value: object) -> bytes:
    _json_check(value)
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                             allow_nan=False).encode("utf-8")
    except (UnicodeError, ValueError) as error:
        raise ValueError("invalid_json_encoding") from error
    if len(encoded) > MAX_INTAKE_BYTES:
        raise ValueError("intake_limit_exceeded")
    return encoded


def _digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(_encoded(value)).hexdigest()


def board_reference(root_identity: str, board: str) -> str:
    """Opaque same-root/same-slug identity, deliberately independent of profile.

    Caller obtains root identity from safely attributable host resolution, not
    model input. Hashing an unknown root does not make it safely attributable.
    """
    _ = _reference(board)
    if not root_identity or len(root_identity) > 4096:
        raise ValueError("invalid_root_identity")
    return _digest(["agent_board_binding/v1", root_identity, board])


def _object(value: object) -> dict[str, object]:
    if not _is_object(value):
        raise ValueError("expected_object")
    return dict(value)


def _array(value: object) -> list[object]:
    if not _is_list(value):
        raise ValueError("expected_array")
    return list(value)


def _integer(value: object, minimum: int = 0, maximum: int = 2**63 - 1) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        raise ValueError("invalid_integer")
    return value


def _text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("invalid_text")
    return value


def apply_lane_role(operation: str, payload: Mapping[str, object]) -> tuple[dict[str, object], str]:
    """Fill a create's lane fields from the stated role and drop the role.

    The caller states one role; the skill, the workspace and the parent
    requirement follow from it rather than from the caller's memory of the
    plan. An explicit `skills` or `workspace_kind` still wins, but a `skills`
    list that drops the role's own skill is a contradiction, not an override.
    """
    args = _object(payload.get("arguments"))
    if operation != "create" or "lane_role" not in args:
        return args, ""
    role = args.pop("lane_role")
    if not isinstance(role, str) or role not in LANE_ROLES:
        raise ValueError("invalid_lane_role")
    contract = LANE_ROLES[role]
    if "skills" not in args:
        args["skills"] = [contract["skill"]]
    elif contract["skill"] not in _array(args["skills"]):
        raise ValueError("lane_role_skills_mismatch")
    if contract["workspace_kind"] is not None and "workspace_kind" not in args:
        args["workspace_kind"] = contract["workspace_kind"]
    # A fan-in lane with no inputs is claimed by the dispatcher on the next
    # tick, so a missing edge is refused here rather than linked afterwards.
    if contract["requires_parents"] and not _array(args.get("parents", [])):
        raise ValueError(_LANE_ROLE_PARENT_REASONS[role])
    return args, role


def _arguments(operation: str, payload: dict[str, object], request_id: str, board: str) -> NativeAction:
    args = copy.deepcopy(_object(payload["arguments"]))
    if payload["coordination"] == "bounded_research":
        if operation != "research" or set(args) != {"tasks"} or "task_id" in payload:
            raise ValueError("invalid_bounded_research")
        tasks = _array(args["tasks"])
        if not 1 <= len(tasks) <= MAX_TASK_IDS:
            raise ValueError("invalid_task_count")
        for task in tasks:
            row = _object(task)
            if set(row) != {"goal", "context"}:
                raise ValueError("invalid_research_task")
            _ = _text(row["goal"])
            if not isinstance(row["context"], str):
                raise ValueError("invalid_research_context")
        return {"tool_name": "delegate_task", "arguments": args}
    required, optional, _ = _OPERATIONS[operation]
    allowed = set((required + " " + optional + " board").split())
    if set(args) - allowed:
        raise ValueError("unsupported_argument")
    if "board" in args and args["board"] != board:
        raise ValueError("foreign_board")
    args["board"] = board
    if operation not in _NO_TASK_ID:
        task_id = _reference(payload.get("task_id"))
        if "task_id" in args and args["task_id"] != task_id:
            raise ValueError("foreign_task")
        args["task_id"] = task_id
    elif "task_id" in payload:
        raise ValueError("unexpected_task_id")
    if operation == "create":
        if args.get("idempotency_key", request_id) != request_id:
            raise ValueError("idempotency_key_mismatch")
        args["idempotency_key"] = request_id
    if set(required.split()) - set(args):
        raise ValueError("missing_argument")
    for name, value in args.items():
        expected = _TYPES.get(name, "string")
        if expected == "array":
            rows = _array(value)
            limit, reason = _ARRAY_LIMITS.get(name, (MAX_TASK_IDS, "too_many_task_ids"))
            if len(rows) > limit:
                raise ValueError(reason)
            for item in rows:
                _ = _reference(item)
        elif expected == "object":
            _ = _object(value)
        elif expected == "integer":
            _ = _integer(value, *_INTEGER_BOUNDS[name])
        elif expected == "boolean":
            if type(value) is not bool:
                raise ValueError("invalid_boolean")
        else:
            _ = _text(value)
        if name in ("task_id", "parent_id", "child_id", "assignee", "reviewer", "idempotency_key"):
            _ = _reference(value)
    if operation == "link" and args["parent_id"] == args["child_id"]:
        raise ValueError("self_link")
    if operation == "complete" and not (args.get("summary") or args.get("result")):
        raise ValueError("completion_text_required")
    if operation == "list" and "status" in args and args["status"] not in _STATUSES - {"review", "scheduled"}:
        raise ValueError("invalid_list_status")
    if "initial_status" in args and args["initial_status"] not in {"todo", "running", "blocked", "triage"}:
        raise ValueError("invalid_initial_status")
    if "workspace_kind" in args and args["workspace_kind"] not in _WORKSPACE_KINDS:
        raise ValueError("invalid_workspace_kind")
    if "workspace_path" in args and args.get("workspace_kind") not in {"dir", "worktree"}:
        raise ValueError("workspace_path_requires_kind")
    body = args.get("body")
    if operation == "create" and isinstance(body, str) and len(body) > BODY_MAX_CHARS:
        raise ValueError("body_limit_exceeded")
    if "kind" in args and args["kind"] not in {"dependency", "needs_input", "capability", "transient"}:
        raise ValueError("invalid_block_kind")
    return {"tool_name": "kanban_" + operation, "arguments": args}


def native_schema_supported(schema: object, action: NativeAction) -> bool:
    if not _is_dict(schema):
        return False
    # Accept parameters, native name/parameters schema, or exposed function schema.
    schema = schema.get("function", schema)
    if not _is_dict(schema):
        return False
    schema = schema.get("parameters", schema)
    if not _is_dict(schema) or schema.get("type") != "object":
        return False
    properties, required = schema.get("properties"), schema.get("required", [])
    if not _is_dict(properties) or not _is_list(required):
        return False
    if any(not isinstance(key, str) or key not in action["arguments"] for key in required):
        return False
    for key, value in action["arguments"].items():
        prop = properties.get(key)
        if not _is_dict(prop) or prop.get("type") != _TYPES.get(key, "string"):
            return False
        if "enum" in prop and (not _is_list(prop["enum"]) or value not in prop["enum"]):
            return False
    return True


@dataclass
class _Request:
    request_id: str
    request_ref: str
    route: str
    operation: str
    argument_digest: str
    scope_ref: str
    action: NativeAction | None
    expected: str | None
    required: list[str]
    state: str = "prepared"
    reason: str | None = None
    lane_role: str = ""
    missing: list[str] = field(default_factory=list)
    call_ref: str | None = None
    receipt: dict[str, object] | None = None
    requires_reconciliation: bool = False
    task_refs: tuple[str, ...] = ()
    reconciled_by: str | None = None


class AgentBoard:
    """A bounded local state machine. Host authorization is strictly external.

    begin/observe are integration methods, never public JSON operations. Keep
    the same instance for local pairing. A durable bridge must atomically store
    frozen metadata and an in-flight marker before allowing the native call;
    after restart, an interrupted marker requires show, not automatic retry.
    """

    def __init__(self, board: str, board_ref: str) -> None:
        self.board: str = _reference(board)
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", board_ref):
            raise ValueError("invalid_board_ref")
        self.board_ref: str = board_ref
        self._requests: dict[str, _Request] = {}
        self._facts: list[dict[str, object]] = []
        self._sequence: int = 0
        self._lock: RLock = RLock()

    @property
    def observation_ref(self) -> str:
        return f"observation:{self._sequence}"

    def _projection(self, entry: _Request, *, include_action: bool = False) -> AgentBoardRequest:
        projection: AgentBoardRequest = {
            "schema_version": "agent_board_request/v1", "request_id": entry.request_id,
            "request_ref": entry.request_ref, "board_ref": self.board_ref, "route": entry.route,
            "operation": entry.operation, "lane_role": entry.lane_role,
            "argument_digest": entry.argument_digest,
            "state": entry.state, "reason": entry.reason,
            "observation_ref": self.observation_ref,
            "expected_observation_ref": entry.expected,
            "required_capabilities": entry.required, "missing_capabilities": entry.missing,
            "native_action": entry.action if include_action and entry.state == "prepared" and entry.call_ref is None else None,
            "observed_receipts": [entry.receipt] if entry.receipt is not None else [],
            "requires_reconciliation": entry.requires_reconciliation,
            "task_refs": list(entry.task_refs), "host_scope_ref": entry.scope_ref,
            "host_call_ref": entry.call_ref,
            "in_flight": entry.call_ref is not None and entry.receipt is None,
            "reconciled_by": entry.reconciled_by,
            "claim_boundary": CLAIM_BOUNDARY,
        }
        return copy.deepcopy(projection)

    def prepare(self, payload: Mapping[str, object], *, host: HostIdentity | None = None,
                schemas: Mapping[str, object] | None = None, hooks: frozenset[str] = _NO_HOOKS,
                board_is_safe: bool = False) -> AgentBoardRequest:
        """Validate closed JSON and return a next action, never invoke it.

        schemas contains actual exposed native schemas, not a grant. Unknown
        hooks/identity/board resolution produce unavailable even with schemas.
        board_is_safe must be false with a DB override or unattributable root.
        """
        data = dict(payload)
        _ = _encoded(data)
        request_id = _reference(data.get("request_id"))
        if data.get("action") == "status":
            if set(data) != {"action", "request_id"}:
                raise ValueError("closed_status_input")
            return self.status(request_id)
        required = {"action", "request_id", "coordination", "operation", "board", "profile", "arguments"}
        if (required - set(data) or set(data) - required - {"task_id", "expected_observation_ref"}
                or data.get("action") != "prepare"):
            raise ValueError("closed_prepare_input")
        if data["board"] != self.board:
            raise ValueError("foreign_board")
        _ = _reference(data["profile"])
        operation = _reference(data["operation"])
        coordination = data["coordination"]
        if coordination not in ("durable", "bounded_research"):
            raise ValueError("invalid_coordination")
        expected = data.get("expected_observation_ref")
        if expected is not None and (not isinstance(expected, str) or not re.fullmatch(r"observation:(0|[1-9][0-9]{0,18})", expected)):
            raise ValueError("invalid_observation_ref")
        # The role contract fills the lane fields before any native shape is
        # built, so the native action itself never carries `lane_role`.
        args, lane_role = apply_lane_role(operation, data)
        data["arguments"] = args
        route = "delegation" if coordination == "bounded_research" else "kanban"
        missing: list[str] = []
        action = None
        if {"expected_revision", "expected_run_id"} & set(args):
            missing.append("native_compare_and_swap")
        elif route == "kanban" and operation not in _OPERATIONS:
            missing.append("operation:" + operation)
        else:
            action = _arguments(operation, data, request_id, self.board)
        tool = action["tool_name"] if action else ("delegate_task" if route == "delegation" else "kanban_" + operation)
        required_caps = [tool, "pre_tool_call", "post_tool_call", "host_identity"]
        if route == "kanban":
            required_caps.extend(["board_binding", "native_read_guard" if operation in {"show", "attachments"} else "native_mutation_guard"])
        if action is not None:
            if schemas is None or tool not in schemas:
                missing.append(tool)
            elif not native_schema_supported(schemas[tool], action):
                missing.append("schema:" + tool)
        missing.extend(name for name in ("pre_tool_call", "post_tool_call") if name not in hooks)
        if host is None:
            missing.append("host_identity")
        if route == "kanban" and not board_is_safe:
            missing.append("board_binding")
        # The request reference and argument digest deliberately exclude profile
        # and expected local observation: neither changes the native action.
        digest = _digest(["agent_board_action/v1", self.board_ref, action if action else data])
        entry = _Request(request_id, _digest(["agent_board_request/v1", self.board_ref, request_id]),
                         route, operation, digest, host.scope_ref if host else "", action, expected,
                         required_caps, lane_role=lane_role, missing=missing)
        if action is not None:
            entry.task_refs = tuple(_reference(action["arguments"][key]) for key in
                                    ("task_id", "parent_id", "child_id") if key in action["arguments"])
        with self._lock:
            previous = self._requests.get(request_id)
            if previous is not None:
                if previous.argument_digest != digest:
                    entry.state, entry.reason = "denied", "request_digest_changed"
                    return self._projection(entry)
                # Completed create deduplication is a readback, not new host
                # authority. Cross-profile/restart callers get the same ID.
                if previous.operation == "create" and previous.state == "observed":
                    return self._projection(previous)
                if host is not None and previous.scope_ref and previous.scope_ref != host.scope_ref:
                    entry.state, entry.reason = "denied", "foreign_host_scope"
                    return self._projection(entry)
                if previous.call_ref is not None or previous.state in {"observed", "failed"}:
                    return self._projection(previous)
            if expected is not None and expected != self.observation_ref:
                entry.state, entry.reason = "denied", "stale_observation"
            elif missing:
                entry.state, entry.reason = "unavailable", "missing_capability"
            elif self._needs_reconciliation(entry):
                entry.state, entry.reason = "denied", "reconciliation_required"
            if previous is None and len(self._requests) >= MAX_REQUESTS:
                entry.state, entry.reason = "unavailable", "request_capacity"
                return self._projection(entry)
            self._requests[request_id] = entry
            return self._projection(entry, include_action=True)

    def status(self, request_id: str) -> AgentBoardRequest:
        """Read a bounded projection, with no raw action/body or authority."""
        _ = _reference(request_id)
        with self._lock:
            entry = self._requests.get(request_id)
            if entry is None:
                entry = _Request(request_id, _digest(["agent_board_request/v1", self.board_ref, request_id]),
                                 "kanban", "unknown", "", "", None, None, [],
                                 state="unavailable", reason="request_not_found")
            return self._projection(entry)

    def begin(self, request_id: str, *, host: HostIdentity, tool_name: str,
              arguments: Mapping[str, object]) -> bool:
        """Reserve the exact next host call after native/user vetoes, not execute."""
        with self._lock:
            entry = self._requests.get(request_id)
            if (entry is None or entry.state != "prepared" or entry.call_ref is not None
                    or entry.scope_ref != host.scope_ref):
                return False
            if entry.expected is not None and entry.expected != self.observation_ref:
                entry.state, entry.reason = "denied", "stale_observation"
                return False
            if self._needs_reconciliation(entry):
                entry.state, entry.reason = "denied", "reconciliation_required"
                return False
            if not self._matches(entry, tool_name, arguments):
                return False
            # A call ID cannot arm a second request, including after completion.
            if any(other.call_ref == host.call_ref for other in self._requests.values()):
                return False
            entry.call_ref = host.call_ref
            entry.requires_reconciliation = True
            entry.reason = "awaiting_correlated_result"
            return True

    def _needs_reconciliation(self, entry: _Request) -> bool:
        if entry.operation in {"show", "attachments", "research"}:
            return False
        targets = set(entry.task_refs)
        return any(other.requires_reconciliation and other.reconciled_by is None
                   and targets.intersection(other.task_refs) for other in self._requests.values())

    def _matches(self, entry: _Request, tool_name: str, arguments: Mapping[str, object]) -> bool:
        try:
            return entry.argument_digest == _digest(["agent_board_action/v1", self.board_ref,
                                                     {"tool_name": tool_name, "arguments": dict(arguments)}])
        except ValueError:
            return False

    def observe(self, request_id: str, *, host: HostIdentity, tool_name: str,
                arguments: Mapping[str, object], result: object,
                binding_is_safe: bool = True) -> dict[str, object] | None:
        """Accept only the paired post callback; retain no raw native response.

        Unpaired/foreign/replayed callbacks return None without changing state.
        A paired malformed/failing result records failed/ambiguous, never a
        landed task fact. Failure may still have native effects (e.g. TTL).
        """
        with self._lock:
            entry = self._requests.get(request_id)
            if entry is None or entry.call_ref != host.call_ref or entry.receipt is not None:
                return None
            reason = None
            facts: dict[str, object] = {}
            if not binding_is_safe:
                reason = "board_binding_changed"
            elif not self._matches(entry, tool_name, arguments):
                reason = "arguments_changed"
            elif entry.route == "delegation":
                # Native delegation has its own normal parent loop and receipts.
                # Never classify a model's child summary as Kanban execution.
                reason = "delegation_result_not_projected"
            else:
                try:
                    parsed = _parse_result(result)
                    # Durable reload intentionally restores no action text. The
                    # paired callback supplies arguments matching the frozen digest.
                    facts = _result_facts(entry.operation, dict(arguments), parsed, self.board, self.board_ref)
                except ValueError as error:
                    # Every error here is a closed, module-authored reason code.
                    reason = str(error)
            self._sequence += 1
            receipt: dict[str, object] = {
                "schema_version": "agent_board_receipt/v1", "request_ref": entry.request_ref,
                "argument_digest": entry.argument_digest, "observation_ref": self.observation_ref,
                "board_ref": self.board_ref, "operation": entry.operation, "lane_role": entry.lane_role,
                "host_call_ref": entry.call_ref,
                "state": "failed" if reason else "observed", "reason": reason,
                "requires_reconciliation": reason is not None, "truncated": False,
                "claim_boundary": CLAIM_BOUNDARY, **facts,
            }
            entry.receipt = receipt
            entry.state = "failed" if reason else "observed"
            entry.reason = reason
            entry.requires_reconciliation = reason is not None
            if reason is None and entry.operation == "show":
                for previous in self._requests.values():
                    if (previous.state == "failed" and previous.receipt is not None
                            and previous.task_refs == entry.task_refs):
                        previous.reconciled_by = self.observation_ref
            entry.action = None  # discard all ephemeral text after the paired callback
            self._facts.append(receipt)
            self._facts = self._facts[-MAX_OPERATION_FACTS:]
            return copy.deepcopy(receipt)

    def matching_requests(self, *, host: HostIdentity | None, tool_name: str,
                          arguments: Mapping[str, object]) -> list[str]:
        """Find only OMH-origin actions; unrelated native calls remain native.

        Create keys reserve a board-wide identity even if a caller changes the
        body or session. Other actions require exact digest AND host scope.
        """
        with self._lock:
            matches = [entry for entry in self._requests.values()
                       if (tool_name == "kanban_create" and entry.operation == "create"
                           and arguments.get("idempotency_key") == entry.request_id)
                       or ((host is None or entry.scope_ref == host.scope_ref)
                           and self._matches(entry, tool_name, arguments)
                           and (entry.state not in {"observed", "failed"}
                                or (entry.requires_reconciliation and entry.reconciled_by is None)
                                or (host is not None and entry.call_ref == host.call_ref)))]
            # An explicitly prepared fresh request may repeat an operation.
            # Historical denied/observed rows cannot shadow that new intent.
            active = [entry for entry in matches if entry.state == "prepared"]
            return [entry.request_id for entry in (active or matches)]

    @classmethod
    def restore(cls, board: str, board_ref: str, raw: str) -> AgentBoard:
        """Reload a bounded closed metadata snapshot, never an execution grant.

        No action bodies are restored. Interrupted pre markers remain reserved;
        the bridge additionally requires a process-local pre before any post.
        Reject the whole record on corruption rather than dropping dedup keys.
        """
        data = _parse_result(raw)
        _fill_lane_role_defaults(data)
        instance = cls(board, board_ref)
        sequence = _observation_sequence(data.get("observation_ref"))
        instance._sequence = sequence
        rows = _array(data.get("requests"))
        if len(rows) > MAX_REQUESTS:
            raise ValueError("invalid_state")
        for item in rows:
            row = _object(item)
            request_id = _reference(row.get("request_id"))
            operation = _reference(row.get("operation"))
            route = _choice(row.get("route"), {"kanban", "delegation"})
            state = _choice(row.get("state"), {"prepared", "unavailable", "denied", "failed", "observed"})
            lane_role = _choice(row.get("lane_role"), set(LANE_ROLES) | {""})
            expected = row.get("expected_observation_ref")
            if expected is not None:
                _ = _observation_sequence(expected)
            reason = row.get("reason")
            if reason is not None:
                reason = _reference(reason)
            call = row.get("host_call_ref")
            if call is not None:
                call = _hash_reference(call)
            scope = row.get("host_scope_ref")
            scope = "" if scope == "" else _hash_reference(scope)
            entry = _Request(request_id, _digest(["agent_board_request/v1", board_ref, request_id]),
                             route, operation, _hash_reference(row.get("argument_digest")), scope,
                             None, expected if isinstance(expected, str) else None,
                             [_reference(value) for value in _array(row.get("required_capabilities"))],
                             state=state, reason=reason, lane_role=lane_role,
                             missing=[_reference(value) for value in _array(row.get("missing_capabilities"))],
                             call_ref=call,
                             requires_reconciliation=_boolean(row.get("requires_reconciliation")),
                             task_refs=tuple(_reference(value) for value in _array(row.get("task_refs"))))
            if len(entry.task_refs) > 2:
                raise ValueError("invalid_state")
            reconciled = row.get("reconciled_by")
            if reconciled is not None:
                _ = _observation_sequence(reconciled)
                entry.reconciled_by = str(reconciled)
            receipts = _array(row.get("observed_receipts"))
            if len(receipts) > 1 or (state in {"failed", "observed"}) != bool(receipts):
                raise ValueError("invalid_state")
            if receipts:
                receipt = _stored_receipt(receipts[0], board_ref)
                if (receipt["request_ref"] != entry.request_ref
                        or receipt["argument_digest"] != entry.argument_digest
                        or receipt["host_call_ref"] != call or receipt["operation"] != operation
                        or receipt["state"] != state or receipt["reason"] != reason
                        or _observation_sequence(receipt["observation_ref"]) > sequence):
                    raise ValueError("invalid_state")
                entry.receipt = receipt
            if request_id in instance._requests or instance._projection(entry) != row:
                raise ValueError("invalid_state")
            instance._requests[request_id] = entry
        facts = [_stored_receipt(value, board_ref) for value in _array(data.get("operation_facts"))]
        receipts_by_sequence = sorted((entry.receipt for entry in instance._requests.values()
                                       if entry.receipt is not None),
                                      key=lambda row: _observation_sequence(row["observation_ref"]))
        if facts != receipts_by_sequence[-MAX_OPERATION_FACTS:]:
            raise ValueError("invalid_state")
        instance._facts = facts
        if instance.snapshot() != data:
            raise ValueError("invalid_state")
        return instance

    def snapshot(self) -> AgentBoardSnapshot:
        """Metadata-only local projection; not an auto-resumable execution store."""
        with self._lock:
            return {"schema_version": "agent_board_state/v1", "board": self.board, "board_ref": self.board_ref,
                    "observation_ref": self.observation_ref,
                    "requests": [self._projection(entry) for entry in self._requests.values()],
                    "operation_facts": copy.deepcopy(self._facts),
                    "truncated": self._sequence > MAX_OPERATION_FACTS,
                    "claim_boundary": CLAIM_BOUNDARY}


def _fill_lane_role_defaults(data: dict[str, object]) -> None:
    """Reload a snapshot written before lane roles as the empty role.

    The request projection and every receipt gained one closed field. A store
    that predates it is not corrupt, and rejecting the whole record would drop
    every create deduplication key, so a missing field reloads as "".
    """
    receipts: list[object] = []
    facts = data.get("operation_facts")
    if _is_list(facts):
        receipts.extend(facts)
    rows = data.get("requests")
    if _is_list(rows):
        for item in rows:
            if _is_object(item):
                _ = item.setdefault("lane_role", "")
                observed = item.get("observed_receipts")
                if _is_list(observed):
                    receipts.extend(observed)
    for receipt in receipts:
        if _is_object(receipt):
            _ = receipt.setdefault("lane_role", "")


def _choice(value: object, choices: set[str]) -> str:
    if not isinstance(value, str) or value not in choices:
        raise ValueError("invalid_state")
    return value


def _boolean(value: object) -> bool:
    if not isinstance(value, bool):
        raise ValueError("invalid_state")
    return value


def _hash_reference(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
        raise ValueError("invalid_state")
    return value


def _observation_sequence(value: object) -> int:
    if not isinstance(value, str) or not re.fullmatch(r"observation:(0|[1-9][0-9]{0,18})", value):
        raise ValueError("invalid_state")
    return int(value.split(":")[1])


def _stored_receipt(value: object, board_ref: str) -> dict[str, object]:
    row = _object(value)
    common = {"schema_version", "request_ref", "argument_digest", "observation_ref", "board_ref",
              "operation", "lane_role", "host_call_ref", "state", "reason", "requires_reconciliation",
              "truncated", "claim_boundary"}
    operation = _reference(row.get("operation"))
    fields: dict[str, set[str]] = {
        "create": {"task_id", "landed_status"}, "link": {"parent_id", "child_id"},
        "comment": {"task_id", "comment_id"}, "heartbeat": {"task_id"},
        "request_review": {"task_id", "run_id", "landed_status"},
        "request_changes": {"task_id", "run_id", "landed_status", "implementer"},
        "block": {"task_id", "run_id", "landed_status", "block_kind"},
        "unblock": {"task_id", "landed_status"}, "complete": {"task_id", "run_id"},
        "show": {"task_id", "landed_status", "parent_ids", "child_ids"},
        "list": {"task_ids", "count", "limit", "next_limit", "promoted"},
        "attachments": {"task_id", "attachment_refs"},
    }
    state = _choice(row.get("state"), {"observed", "failed"})
    expected: set[str] = common.copy()
    if state == "observed":
        expected.add("fact")
        expected.update(fields.get(operation, set()))
    if operation == "show" and "run_id" in row and state == "observed":
        expected.add("run_id")
    if (set(row) != expected or row.get("schema_version") != "agent_board_receipt/v1"
            or row.get("board_ref") != board_ref or row.get("claim_boundary") != CLAIM_BOUNDARY
            or row.get("requires_reconciliation") is not (state == "failed")):
        raise ValueError("invalid_state")
    _ = _boolean(row["truncated"])
    _ = _choice(row["lane_role"], set(LANE_ROLES) | {""})
    for key in ("request_ref", "argument_digest", "host_call_ref"):
        _ = _hash_reference(row[key])
    _ = _observation_sequence(row["observation_ref"])
    if state == "failed":
        _ = _reference(row["reason"])
    elif (row["reason"] is not None or operation not in fields
          or row["fact"] != {"request_review": "review_requested", "request_changes": "changes_requested"}.get(operation, operation)):
        raise ValueError("invalid_state")
    for key in ("task_id", "parent_id", "child_id", "implementer"):
        if key in row:
            _ = _reference(row[key])
    if "landed_status" in row:
        _ = _choice(row["landed_status"], set(_STATUSES))
    if "block_kind" in row:
        _ = _choice(row["block_kind"], {"dependency", "needs_input", "capability", "transient"})
    for key in ("comment_id", "run_id", "count", "limit", "next_limit", "promoted"):
        if key in row and row[key] is not None:
            _ = _integer(row[key])
    for key in ("parent_ids", "child_ids", "task_ids"):
        if key in row:
            values = _array(row[key])
            if len(values) > MAX_TASK_IDS:
                raise ValueError("invalid_state")
            for item in values:
                _ = _reference(item)
    if "attachment_refs" in row:
        refs = _array(row["attachment_refs"])
        if len(refs) > MAX_ATTACHMENT_REFS:
            raise ValueError("invalid_state")
        for value in refs:
            ref = _object(value)
            if (set(ref) != {"board_ref", "task_id", "attachment_id", "size", "content_type"}
                    or ref["board_ref"] != board_ref or ref["task_id"] != row["task_id"]):
                raise ValueError("invalid_state")
            _ = _integer(ref["attachment_id"], 1)
            _ = _integer(ref["size"], 0, 25 * 1024 * 1024)
            mime = ref["content_type"]
            if not isinstance(mime, str) or not _MIME.fullmatch(mime):
                raise ValueError("invalid_state")
    return row


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_result_key")
        result[key] = value
    return result


class _JsonModule(Protocol):
    def loads(self, s: str, *,
              object_pairs_hook: Callable[[list[tuple[str, object]]], dict[str, object]]) -> object: ...


# Decoding yields unvalidated boundary data, not a trusted JSON object.
_json: _JsonModule = json


def _parse_result(raw: object) -> dict[str, object]:
    if not isinstance(raw, str) or len(raw) > MAX_INTAKE_BYTES:
        raise ValueError("result_intake_exceeded")
    try:
        if len(raw.encode("utf-8")) > MAX_INTAKE_BYTES:
            raise ValueError("result_intake_exceeded")
        value = _json.loads(raw, object_pairs_hook=_unique_object)
        _json_check(value)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise ValueError("malformed_result") from error
    return _object(value)


def _binding(row: dict[str, object], board: str, task_id: object = None) -> None:
    if "board" in row and row["board"] != board:
        raise ValueError("foreign_result_board")
    if task_id is not None and "task_id" in row and row["task_id"] != task_id:
        raise ValueError("foreign_result_task")


def _task_rows(value: object, board: str) -> list[str]:
    result: list[str] = []
    for item in _array(value):
        row = _object(item)
        _binding(row, board)
        result.append(_reference(row.get("id")))
    if len(set(result)) != len(result):
        raise ValueError("duplicate_task_id")
    return result


def _result_facts(operation: str, args: dict[str, object], result: dict[str, object],
                  board: str, board_ref: str) -> dict[str, object]:
    if "error" in result or (operation not in {"show", "list"} and result.get("ok") is not True):
        raise ValueError("native_failure")
    if set(_OPERATIONS[operation][2].split()) - set(result):
        raise ValueError("missing_result_field")
    task_id = args.get("task_id")
    _binding(result, board, task_id)
    facts: dict[str, object] = {"fact": {"request_review": "review_requested", "request_changes": "changes_requested"}.get(operation, operation)}
    if operation == "link":
        for key in ("parent_id", "child_id"):
            if result[key] != args[key]:
                raise ValueError("foreign_result_edge")
            facts[key] = _reference(result[key])
    elif operation == "list":
        ids = _task_rows(result["tasks"], board)
        count = _integer(result["count"])
        limit = _integer(result["limit"], 1, 200)
        if count < len(ids) or type(result["truncated"]) is not bool:
            raise ValueError("invalid_list_counts")
        if result["next_limit"] is not None:
            _ = _integer(result["next_limit"], 1, 200)
        _ = _integer(result["promoted"])
        facts.update(task_ids=ids[:MAX_TASK_IDS], count=count, limit=limit,
                     truncated=result["truncated"] or len(ids) > MAX_TASK_IDS,
                     next_limit=result["next_limit"], promoted=result["promoted"])
    elif operation == "show":
        task = _object(result["task"])
        if task.get("id") != task_id:
            raise ValueError("foreign_result_task")
        _binding(task, board, task_id)
        facts["task_id"] = _reference(task_id)
        status = task.get("status")
        if not isinstance(status, str) or status not in _STATUSES:
            raise ValueError("invalid_landed_status")
        facts["landed_status"] = status
        if task.get("current_run_id") is not None:
            facts["run_id"] = _integer(task["current_run_id"], 1)
        parents = [_reference(item) for item in _array(result["parents"])]
        children = [_reference(item) for item in _array(result["children"])]
        facts.update(parent_ids=parents[:MAX_TASK_IDS], child_ids=children[:MAX_TASK_IDS],
                     truncated=len(parents) > MAX_TASK_IDS or len(children) > MAX_TASK_IDS)
        for key in ("comments", "events", "runs"):
            _ = _array(result[key])
        if not isinstance(result["worker_context"], str):
            raise ValueError("invalid_worker_context")
    else:
        facts["task_id"] = _reference(result["task_id"])
    success_keys = _OPERATIONS[operation][2].split()
    if "status" in success_keys:
        status = result["status"]
        if not isinstance(status, str) or status not in _STATUSES:
            raise ValueError("invalid_landed_status")
        facts["landed_status"] = status
    if "run_id" in success_keys:
        facts["run_id"] = None if result["run_id"] is None else _integer(result["run_id"], 1)
    if "comment_id" in success_keys:
        facts["comment_id"] = _integer(result["comment_id"], 1)
    if operation == "request_changes":
        facts["implementer"] = _reference(result["implementer"])
    if operation == "block":
        if result["block_kind"] not in ("dependency", "needs_input", "capability", "transient"):
            raise ValueError("invalid_block_kind")
        facts["block_kind"] = result["block_kind"]
    if operation == "attachments":
        refs: list[dict[str, object]] = []
        seen: set[int] = set()
        for item in _array(result["attachments"]):
            attachment = _object(item)
            _binding(attachment, board, task_id)
            attachment_id = _integer(attachment.get("id"), 1)
            size = _integer(attachment.get("size"), 0, 25 * 1024 * 1024)
            content_type = attachment.get("content_type")
            if not isinstance(content_type, str) or not _MIME.fullmatch(content_type):
                raise ValueError("invalid_attachment_type")
            if attachment_id in seen:
                raise ValueError("duplicate_attachment_id")
            seen.add(attachment_id)
            if len(refs) < MAX_ATTACHMENT_REFS:
                refs.append({"board_ref": board_ref, "task_id": task_id,
                             "attachment_id": attachment_id, "size": size, "content_type": content_type})
        facts.update(attachment_refs=refs, truncated=len(seen) > MAX_ATTACHMENT_REFS)
    return facts
