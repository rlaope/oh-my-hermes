"""`omh_dag/v1`: one dag-ulw run, its nodes, attempts and repair cycles, and what is ready next.

The `omh_dag` tool (`tools/dag_tool.py`) is the only writer; the delegation
graph (`delegation_graph.py`) reads it. Hermes runs every node: the parent
agent dispatches the ready nodes with its own `delegate_task`, and nothing
here executes, delegates or calls a model.

The record
----------
One JSON file per run under ``<omh_home>/runtime/dag/<session key>/``, keyed
by the durable session that defined it. A reader looks under every segment
of the conversation (`dag_tool.conversation_keys`), so a run survives
Hermes' compaction in either direction. Writes are a temp file and
``os.replace`` under the record's lock.

It holds the plan the parent declared: ids, labels, categories, edges, write
scopes, roles, and each node's prompt, kept so ``ready`` can hand a node out after
the parent's own context was compacted. It holds no child output, summary or
tool history. Data between nodes moves through handoff files whose paths
this module names (`handoff_path`); it never reads them beyond asking
whether one exists. On a Docker or SSH terminal the child writes its file
there, under the ``handoff_root`` the run pins in that terminal user's home
(`node_handoff`), so `dag_tool` asks there (the run records its
``backend`` at define); when nothing can reach that terminal, an accepted
node keeps ``handoff_checked: false`` and every view says
`HANDOFF_NOT_CHECKED`.

State is derived on every read, never stored
--------------------------------------------
A node is ``accepted`` only by the parent's ``settle``. Its child, bound
through the ``[dag:<run>/<node>]`` goal marker the delegation ledger reads at
``subagent_start``, says whether it is running or has returned; a child's own
status is a report, and a returned node waits for ``settle``. A child marked
``lost`` (`dag_tool` found the Hermes process it ran in gone: a restart ends
a child and fires no stop) does not count, so its node is out with no child
and is offered again at once, at most `MAX_LOST_REOFFERS` times per attempt;
past that the parent settles it. A node out longer than `STUCK_AFTER_SECONDS`
is named in every view (`stuck`); the profile can move that mark, the
re-offer wait and the re-offer bound (`Limits`). A failed or blocked node blocks its
dependents and nothing else. ``repair`` adds a group
of repair nodes for a failed or blocked node, at most `MAX_REPAIR_CYCLES` per
original node. Once its latest group is all accepted the original counts as
satisfied and the nodes after it read the group's handoff files, except a
verification node: it runs again, and only its own accepted re-run satisfies
it. Nodes of an earlier group that never got accepted are superseded. ``extend`` adds a round of nodes to a run whose every node passed
when the goal check finds work missing, at most `MAX_EXTEND_ROUNDS` per run.
Each node records where it came from (``origin``): ``define``,
``repair:<root>`` or ``extend:<round>``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import posixpath
import re
import secrets
import shlex
import shutil
from typing import Any, Final

from . import dag_core
from .awareness_delivery import _awareness_delivery_lock
from .delegation_ledger import ledger_key
from .hermes_delegation import HERMES_MIXTURE_CATEGORY_CHAINS
from .iso_datetime import strict_fromisoformat

DAG_SCHEMA_VERSION: Final = "omh_dag/v1"
DAG_RESULT_SCHEMA_VERSION: Final = "omh_dag_result/v1"
DAG_DIRNAME: Final = "dag"
MAX_NODES: Final = 48
MAX_RUNS_PER_SESSION: Final = 16
MAX_PROMPT_CHARS: Final = 3_000
MAX_LABEL_CHARS: Final = 80
MAX_NAME_CHARS: Final = 48
MAX_GOAL_CHARS: Final = 240
MAX_SCOPE_ENTRIES: Final = 16
MAX_SCOPE_CHARS: Final = 200
MAX_REASON_CHARS: Final = 200
MAX_REPAIR_CYCLES: Final = 2
MAX_EXTEND_ROUNDS: Final = 2
MAX_PROVIDER_RETRIES: Final = 1
MAX_PARKS: Final = 3
MAX_HANDLE_CHARS: Final = 120
MAX_PARK_SECONDS: Final = 24 * 3600
MAX_RECORD_BYTES: Final = 262_144
LOCK_SECONDS: Final = 5.0
# A node handed out that no child has bound to for this long was not dispatched; `ready` offers it again.
HANDOUT_STALE_SECONDS: Final = 600.0
# A node whose child a Hermes restart ended is offered again at once this many times per attempt, then left to settle.
MAX_LOST_REOFFERS: Final = 3
# A node open this long (handed out, running, or returned and not settled) is named in `say` and the status line.
STUCK_AFTER_SECONDS: Final = 3600.0
# The profile can change the three marks above (`dag_tool.dag_limits`); a time mark is never shorter than this, so a
# child still starting is not offered twice, and at most this many restart re-offers.
MIN_MARK_SECONDS: Final = 60.0
MAX_LOST_REOFFERS_LIMIT: Final = 10
# A child counts for an attempt when it started no earlier than this before the attempt was handed out.
BIND_SLACK_SECONDS: Final = 2.0
CATEGORIES: Final = tuple(HERMES_MIXTURE_CATEGORY_CHAINS)
DEEP_CATEGORIES: Final = frozenset({"deep", "deep-work"})
OUTCOMES: Final = ("accepted", "failed", "blocked", "parked")
# The ``origin`` kinds of a node added after define: ``repair:<root>`` and ``extend:<round>``.
ADDED_ORIGIN_KINDS: Final = ("repair", "extend")
PROMPT_MARKERS: Final = ("TASK", "DELIVERABLE", "SCOPE", "VERIFY", "STOP WHEN")
# A run this wide whose critical path is this much of it is one chain wearing a graph's clothes.
SERIAL_GRAPH_NODES: Final = 5
SERIAL_GRAPH_SHARE: Final = 0.8
# Hermes' `subagent_stop` words that say the child did not finish (`delegation_graph._FAILED_STOPS` plus interrupted).
CHILD_FAILURE_STOPS: Final = frozenset({"failed", "error", "timeout", "interrupted"})
# What every view says for a node accepted while its handoff could not be read where the child wrote it.
HANDOFF_NOT_CHECKED: Final = "handoff not checked"
NODE_FIELDS: Final = frozenset({"id", "label", "category", "prompt", "depends_on", "write_scope", "role"})
# What a node is for, as the parent declares it (``build`` when it names none). A ``build`` node with a write scope is a
# producer; baseline, verify and review nodes stay native whoever builds, and only a ``verify`` node verifies the goal.
ROLES: Final = ("build", "baseline", "verify", "review")
DEFAULT_ROLE: Final = "build"
# A run's goal verdict (`goal_verdict`), apart from its state: a ``done`` run may be ``unverified``.
VERDICTS: Final = ("verified", "unverified", "verify_failed")
# What a goal verdict is (`goal_verdict`), carried wherever the verdict leaves the tool's own payload.
VERDICT_CLAIM_BOUNDARY: Final = (
    "A goal verdict derived from the dag run record: the outcomes the parent settled, Hermes' child status and the "
    "handoff reads. Not observed verification, CI or review evidence."
)
DAG_CLAIM_BOUNDARY: Final = (
    "The plan a parent agent declared for a dag-ulw run and the outcomes it settled. A settled outcome is the "
    "parent's judgement; a child's status is Hermes' report. Not execution, verification, review, CI or merge "
    "evidence."
)

_ID: Final = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
_CONTROL: Final = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_BASELINE_WORD: Final = re.compile(r"(?<![a-z])baseline(?![a-z])")
_VERIFY_WORDS: Final = re.compile(r"(?<![a-z])(verif|audit|validat|qa(?![a-z]))")
_REVIEW_WORDS: Final = re.compile(r"(?<![a-z])review")
_MARKER_PATTERNS: Final = {
    marker: re.compile(r"(?<![A-Za-z])" + r"\s+".join(marker.split()) + r"\s*:", re.IGNORECASE)
    for marker in PROMPT_MARKERS
}

# Node states the derivation produces.
SATISFIED: Final = frozenset({"accepted", "repaired"})
OPEN: Final = frozenset({"handed_out", "running", "returned"})
LIVE: Final = OPEN | {"parked"}


@dataclass(frozen=True)
class Limits:
    """When `ready` offers again a node no child took, when an open node counts as stuck (``0``: never), and how many
    times a node whose child a restart ended is offered again. Defaults are the constants; a profile changes them."""

    stale_after_s: float = HANDOUT_STALE_SECONDS
    stuck_after_s: float = STUCK_AFTER_SECONDS
    max_lost_reoffers: int = MAX_LOST_REOFFERS


DEFAULT_LIMITS: Final = Limits()


class DagRefusal(Exception):
    def __init__(self, reason: str, say: str) -> None:
        super().__init__(reason)
        self.reason = reason
        self.say = say


# ── paths and the record ─────────────────────────────────────────────────


def session_dir(omh_home: Path, session_id: str) -> Path:
    return Path(omh_home) / "runtime" / DAG_DIRNAME / ledger_key(session_id)


def record_path(omh_home: Path, session_id: str, run: str) -> Path:
    return session_dir(omh_home, session_id) / f"{run}.json"


def handoff_path(omh_home: Path, session_id: str, run: str, node: str) -> Path:
    """Where a node's child writes its report and its dependents read it, on this host."""
    return session_dir(omh_home, session_id) / run / f"{node}.md"


def node_handoff(record: Mapping[str, Any], omh_home: Path, node: str) -> str:
    """Where a node's child writes its report and its dependents read it.

    Under the run's pinned ``handoff_root`` inside its Docker or SSH terminal
    (`dag_tool.backend_root`, the terminal user's own home) when it has one,
    else on this host (`handoff_path`).
    """
    root = record.get("handoff_root")
    if isinstance(root, str) and root:
        return posixpath.join(root, ledger_key(str(record["session_id"])), str(record["run"]), f"{node}.md")
    return str(handoff_path(omh_home, str(record["session_id"]), str(record["run"]), node))


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if number == number and abs(number) != float("inf") else None


def read_run(path: Path) -> dict[str, Any] | None:
    """One stored run, or None when it is missing, too large, or not a run this module wrote."""
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_RECORD_BYTES:
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError, RecursionError):
        return None
    return raw if _record_shape_ok(raw) else None


def _record_shape_ok(raw: object) -> bool:
    if not isinstance(raw, dict) or raw.get("schema_version") != DAG_SCHEMA_VERSION:
        return False
    if not isinstance(raw.get("run"), str) or not _ID.fullmatch(raw["run"]):
        return False
    nodes = raw.get("nodes")
    if not isinstance(nodes, list) or not 1 <= len(nodes) <= MAX_NODES:
        return False
    ids = [node.get("id") for node in nodes if isinstance(node, dict)]
    if len(ids) != len(nodes) or len(set(ids)) != len(ids) or not all(isinstance(i, str) and _ID.fullmatch(i) for i in ids):
        return False
    known = set(ids)
    for node in nodes:
        if not isinstance(node.get("depends_on"), list) or not set(node["depends_on"]) <= known:
            return False
        if not isinstance(node.get("attempts"), list) or not all(isinstance(item, dict) for item in node["attempts"]):
            return False
        if not isinstance(node.get("prompt"), str) or node.get("category") not in CATEGORIES:
            return False
        if "role" in node and node["role"] not in ROLES:
            return False
    if dag_core.layers(ids, {node["id"]: node["depends_on"] for node in nodes}) is None:
        return False
    repairs = raw.get("repairs")
    extends = raw.get("extends", [])
    return isinstance(repairs, dict) and all(
        isinstance(groups, list) and all(isinstance(group, list) and set(group) <= known for group in groups)
        for groups in repairs.values()
    ) and isinstance(extends, list) and all(isinstance(group, list) and set(group) <= known for group in extends)


def write_run(path: Path, record: Mapping[str, Any]) -> None:
    data = json.dumps(record, sort_keys=True).encode("utf-8")
    if len(data) > MAX_RECORD_BYTES:
        raise DagRefusal("record_too_large", "This run's plan is too large to keep; use fewer or shorter nodes.")
    if path.is_symlink():
        raise DagRefusal("record_unwritable", "The run's record is a link, so OMH will not write through it.")
    temporary = path.with_name(f".{path.name}.{os.getpid()}-{secrets.token_hex(6)}.tmp")
    try:
        # Created 0600: the record holds the node prompts, so it is never readable to others, not even briefly.
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists() and not temporary.is_symlink():
            temporary.unlink()


def locked(path: Path) -> AbstractContextManager[str]:
    """The run record's own lock, held for one read-modify-write."""
    return _awareness_delivery_lock(path, timeout_seconds=LOCK_SECONDS)


def session_runs(omh_home: Path, session_id: str) -> list[tuple[dict[str, Any], Path]]:
    """Every readable run stored under one session, newest change first."""
    directory = session_dir(omh_home, session_id)
    try:
        paths = [path for path in directory.iterdir()
                 if path.suffix == ".json" and not path.name.startswith(".") and not path.is_symlink()]
    except OSError:
        return []
    runs = [(record, path) for path in paths if (record := read_run(path)) is not None]
    return sorted(runs, key=lambda item: _number(item[0].get("updated_at")) or 0.0, reverse=True)


FINISHED_STATES: Final = frozenset({"done", "cancelled", "stopped"})


def make_room(omh_home: Path, session_id: str, children: Sequence[Mapping[str, Any]], now: float) -> bool:
    """Drop one session's oldest finished runs until a new run fits under `MAX_RUNS_PER_SESSION`.

    A finished run is done, cancelled or out of repair cycles; its record and
    its handoff folder go together. False when the session is full of runs
    that can still move, which a new run must not push out.
    """
    runs = session_runs(omh_home, session_id)  # newest first
    while len(runs) >= MAX_RUNS_PER_SESSION:
        finished = [item for item in runs if run_state(item[0], derive(item[0], children, now)) in FINISHED_STATES]
        if not finished:
            return False
        _record, path = finished[-1]
        with locked(path):
            path.unlink(missing_ok=True)
        folder = path.with_suffix("")
        if folder.is_dir() and not folder.is_symlink():
            shutil.rmtree(folder)
        runs = [item for item in runs if item[1] != path]
    return True


# ── validation ───────────────────────────────────────────────────────────


def _plain(value: object, limit: int, reason: str, say: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit or _CONTROL.search(value):
        raise DagRefusal(reason, say)
    return " ".join(value.split())


def valid_id(value: object, reason: str, say: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise DagRefusal(reason, say)
    return value


def _validated_node(raw: object) -> dict[str, Any]:
    if not isinstance(raw, Mapping) or set(raw) - NODE_FIELDS:
        raise DagRefusal("invalid_node",
                         "Each node takes only id, label, category, prompt, depends_on, write_scope and role.")
    node_id = valid_id(raw.get("id"), "invalid_node_id", "Each node needs a short lowercase id (a-z, 0-9, -).")
    label = _plain(raw.get("label"), MAX_LABEL_CHARS, "invalid_label", f"Node {node_id} needs a short label.")
    # Either lane's reader also takes a marker that opens a goal (one handed out before an update), so a label holding
    # either marker could bind a child to another node or team part.
    if "[dag:" in label or "[omh-team:" in label:
        raise DagRefusal("invalid_label",
                         f"Node {node_id}: a label cannot hold a [dag:...] or [omh-team:...] marker; OMH adds its own.")
    category = raw.get("category")
    if category not in CATEGORIES:
        raise DagRefusal("invalid_category", f"Node {node_id} needs a category: {', '.join(CATEGORIES)}.")
    prompt = raw.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > MAX_PROMPT_CHARS or "\x00" in prompt:
        raise DagRefusal("invalid_prompt",
                         f"Node {node_id} needs a prompt of at most {MAX_PROMPT_CHARS} characters.")
    depends_on = raw.get("depends_on", [])
    if not isinstance(depends_on, list) or not all(isinstance(item, str) for item in depends_on):
        raise DagRefusal("invalid_depends_on", f"Node {node_id}: depends_on lists other nodes by id.")
    scope = raw.get("write_scope", [])
    if (not isinstance(scope, list) or len(scope) > MAX_SCOPE_ENTRIES
            or not all(isinstance(item, str) and item.strip() and len(item) <= MAX_SCOPE_CHARS
                       and not _CONTROL.search(item) for item in scope)):
        raise DagRefusal("invalid_write_scope",
                         f"Node {node_id}: write_scope lists at most {MAX_SCOPE_ENTRIES} paths it may change.")
    role = raw.get("role", DEFAULT_ROLE)
    if role not in ROLES:
        raise DagRefusal("invalid_role", f"Node {node_id}: role is one of {', '.join(ROLES)}.")
    validated = {
        "id": node_id,
        "label": label,
        "category": category,
        "prompt": prompt.strip(),
        "depends_on": sorted(set(depends_on)),
        "write_scope": sorted({item.strip() for item in scope}),
        "role": role,
        "repairs": "",
        "cycle": 0,
        "origin": "define",
        "found_by": "",
        "attempts": [],
    }
    guess = guessed_role(validated) if "role" not in raw else DEFAULT_ROLE
    if guess in ("verify", "review") and validated["write_scope"]:
        # As a build node it would go to an external coding owner and be repaired rather than run again: a builder
        # approving itself. The parent says which it is.
        raise DagRefusal("role_required",
                         f"Node {node_id} writes files and reads like a {guess} node: give it role={guess}, "
                         "or role=build when it builds.")
    if guess != DEFAULT_ROLE:
        # Advice only (`lint`): the node runs as a build node, and the role its label reads like is named.
        validated["role_guess"] = guess
    return validated


def _require_graph(
    nodes: Sequence[Mapping[str, Any]], *, editable: Iterable[str] | None = None, involving: Iterable[str] = (),
    before: Mapping[str, Iterable[str]] | None = None,
) -> None:
    """The hard rejects over a whole graph: references, cycles, and write scopes shared without an edge.

    ``editable`` limits the scope check to pairs of those nodes: a repair is
    checked against the nodes that can still run, not against finished ones.
    ``involving`` limits it further to pairs with one of those nodes in them:
    an extend round is checked against the run's earlier nodes, not the run
    against itself again. ``before`` adds orderings the scope check counts as
    edges, {node: nodes ordered before it}: a repair group runs before every
    node that waits on the node it repairs.
    """
    ids = [str(node["id"]) for node in nodes]
    if len(set(ids)) != len(ids):
        raise DagRefusal("duplicate_node_id", "Each node id must be unique in the run.")
    known = set(ids)
    parents = {str(node["id"]): list(node["depends_on"]) for node in nodes}
    for node in nodes:
        problem = dag_core.edge_problem(str(node["id"]), node["depends_on"], known)
        if problem is not None and problem[0] == dag_core.UNKNOWN_DEPENDENCY:
            raise DagRefusal("unknown_dependency", f"Node {node['id']} depends on {problem[1]}, which is not in the run.")
        if problem is not None:
            raise DagRefusal("self_dependency", f"Node {node['id']} cannot depend on itself.")
    _placed, stuck = dag_core.layer_of(ids, parents)
    if stuck:
        raise DagRefusal("dependency_cycle", f"These nodes depend on each other in a circle: {', '.join(stuck)}.")
    checked = set(editable) if editable is not None else known
    new = set(involving)
    scopes = [(str(node["id"]), node["write_scope"]) for node in nodes]
    ordered = {node: [*listed, *(before or {}).get(node, ())] for node, listed in parents.items()}
    for first, second, shared, joined in dag_core.shared_scope_pairs(scopes, ordered):
        if not joined and first in checked and second in checked and (not new or first in new or second in new):
            raise DagRefusal(
                "write_scope_overlap",
                f"Nodes {first} and {second} both write {', '.join(shared)} with no edge between them; "
                "make one depend on the other or split the scope.",
            )


def markerless_nodes(nodes: Sequence[Mapping[str, Any]]) -> list[str]:
    """Nodes whose prompt names none of the five markers: a hard reject at define, repair and extend.

    A partial set is a lint finding, not a refusal; a prompt with no marker at
    all gives the child nothing to plan against, so the node is refused.
    """
    return [
        str(node["id"]) for node in nodes
        if not any(pattern.search(str(node["prompt"])) for pattern in _MARKER_PATTERNS.values())
    ]


def require_prompt_markers(nodes: Sequence[Mapping[str, Any]]) -> None:
    missing = markerless_nodes(nodes)
    if missing:
        raise DagRefusal(
            "prompt_markers_missing",
            f"Node{'s' if len(missing) > 1 else ''} {', '.join(missing)}: no prompt names any of "
            f"{', '.join(PROMPT_MARKERS)}; add them (a partial set stays a lint finding).",
        )


def _mentions_full_suite(prompt: str) -> bool:
    """Advisory detection of broad suites, excluding pytest's explicit positional targets."""
    if re.search(r"\b(?:full\s+(?:test\s+)?suite|unittest\s+discover)\b", prompt, re.IGNORECASE):
        return True
    # Commands end at shell separators, line breaks or inline-code fences; prose often adds ', exit 0'.
    for match in re.finditer(r"(?<![\w.-])pytest(?![\w.-])([^\n`;&|,]*)", prompt, re.IGNORECASE):
        try:
            arguments = shlex.split(match[1])
        except ValueError:
            continue  # An unfinished quotation is not enough to infer an unscoped command.
        takes_value = {"-k", "-m", "-c", "-o", "-p", "--override-ini", "--maxfail", "--tb",
                       "--durations", "--durations-min", "--color", "--capture", "--confcutdir",
                       "--rootdir", "--basetemp", "--ignore", "--ignore-glob", "--deselect", "--log-level"}
        skip_value = False
        targeted = False
        for argument in arguments:
            if skip_value:
                skip_value = False
            elif argument in takes_value:
                skip_value = True
            elif not argument.startswith("-"):
                targeted = True
                break
        if not targeted:
            return True
    return False


def lint(nodes: Sequence[Mapping[str, Any]]) -> list[str]:
    """Advisory findings: they never reject a run, and the run records them."""
    findings: list[str] = []
    for node in nodes:
        missing = [marker for marker in PROMPT_MARKERS if not _MARKER_PATTERNS[marker].search(str(node["prompt"]))]
        if missing:
            findings.append(f"missing_markers:{node['id']}:{','.join(marker.replace(' ', '_') for marker in missing)}")
    if len(nodes) >= SERIAL_GRAPH_NODES:
        path_length = len(topology(nodes)["critical_path"])
        if path_length >= SERIAL_GRAPH_SHARE * len(nodes):
            findings.append(f"serial_graph:{len(nodes)} nodes, critical path {path_length}; "
                            "most of the graph is one chain, so split it into parallel lanes where the work allows.")
    findings += [f"role_guess:{node['id']}={node['role_guess']}" for node in nodes if node.get("role_guess")]
    verifiers = [node for node in nodes if is_verification(node)]
    if len(nodes) > 1 and not verifiers:
        findings.append("no_verification_node")
    if verifiers:
        parents = {str(node["id"]): node["depends_on"] for node in nodes}
        baselines = {str(node["id"]) for node in nodes if is_baseline(node)}
        for verifier in verifiers:
            preceding = ancestors(str(verifier["id"]), parents)
            if not preceding & baselines and _mentions_full_suite(str(verifier["prompt"])):
                findings.append(f"verify_without_baseline:{verifier['id']}")
        unchecked = verification_misses(nodes, verifiers)
        if unchecked:
            findings.append(f"verification_misses:{','.join(unchecked)}")
    if len(nodes) > 1 and all(node["category"] in DEEP_CATEGORIES for node in nodes):
        findings.append("all_nodes_deep")
    if sum(1 for node in nodes if node["category"] == "ultrabrain") > 1:
        findings.append("ultrabrain_more_than_once")
    return findings


def guessed_role(node: Mapping[str, Any]) -> str:
    """The role a node's id and label read like. Never a new node's role: a lint hint (``role_guess``) for a node
    defined without one, and the role of a node stored before nodes carried one (`node_role`)."""
    text = f"{node['id']} {node['label']}".casefold()
    if _BASELINE_WORD.search(text):
        return "baseline"
    if _VERIFY_WORDS.search(text):
        return "verify"
    if _REVIEW_WORDS.search(text):
        return "review"
    return DEFAULT_ROLE


def node_role(node: Mapping[str, Any]) -> str:
    """The node's declared role. A node stored before nodes carried one (a run in flight across the update that added
    the field) reads as its label did then (`guessed_role`); every node define, repair or extend records has one."""
    role = node.get("role")
    return str(role) if role in ROLES else guessed_role(node)


def is_baseline(node: Mapping[str, Any]) -> bool:
    """A baseline captures existing failures before later verification judges the change."""
    return node_role(node) == "baseline"


def is_verification(node: Mapping[str, Any]) -> bool:
    return node_role(node) == "verify"


def is_coding(node: Mapping[str, Any]) -> bool:
    """A node an external coding owner may take, and the work a verify node follows: a build node that writes files.

    Baselines, verification and review stay native whoever builds: the builder never approves itself.
    """
    return bool(node["write_scope"]) and node_role(node) == DEFAULT_ROLE


def is_producer(node: Mapping[str, Any]) -> bool:
    """Work a verify node has to follow: any node that writes files and is no verify node (baselines and review
    writers count, as they did before nodes carried a role). Wider than `is_coding`, which only build nodes pass."""
    return bool(node["write_scope"]) and not is_verification(node)


def verification_misses(nodes: Sequence[Mapping[str, Any]], verifiers: Sequence[Mapping[str, Any]], *,
                        skip: Iterable[str] = ()) -> list[str]:
    """The producers (`is_producer`) no node of ``verifiers`` follows, sorted; ``skip`` names nodes left out.

    A repair node stands in for the node it repairs; a verification node's repair is checked by its re-run.
    """
    parents = {str(node["id"]): node["depends_on"] for node in nodes}
    covered: set[str] = set()
    for verifier in verifiers:
        covered |= ancestors(str(verifier["id"]), parents)
    checks = {str(verifier["id"]) for verifier in verifiers}
    covered |= {str(node["id"]) for node in nodes if node.get("repairs") and node["repairs"] in covered | checks}
    left_out = covered | set(skip)
    return sorted(str(node["id"]) for node in nodes if is_producer(node) and str(node["id"]) not in left_out)


def ancestors(node_id: str, parents: Mapping[str, Iterable[str]]) -> set[str]:
    seen: set[str] = set()
    frontier = list(parents.get(node_id, ()))
    while frontier:
        current = frontier.pop()
        if current not in seen:
            seen.add(current)
            frontier.extend(parents.get(current, ()))
    return seen


def topology(nodes: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    ids = [str(node["id"]) for node in nodes]
    parents = {str(node["id"]): node["depends_on"] for node in nodes}
    return {
        "layers": dag_core.layers(ids, parents) or [],
        "critical_path": dag_core.critical_path(ids, parents),
        "bottlenecks": [{"node": node, "blocks": count} for node, count in dag_core.bottlenecks(ids, parents)],
    }


def definition_digest(nodes: Sequence[Mapping[str, Any]]) -> str:
    # A build role is left out, so a run stored before nodes carried a role, defined again unchanged, is the same run.
    shape = [{key: node[key] for key in sorted(NODE_FIELDS) if key != "role" or node[key] != DEFAULT_ROLE}
             for node in nodes]
    return hashlib.sha256(json.dumps(shape, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def new_record(session_id: str, run: str, name: object, goal: object, raw_nodes: object, now: float, *,
               oneshot_limit: int | None = None, oneshot_spent: int = 0) -> dict[str, Any]:
    """A validated run record. ``oneshot_limit`` and ``oneshot_spent``: the one-shot child budget and the children
    this process already started against it; a graph over what is left is refused."""
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise DagRefusal("empty_graph", "A run needs at least one node.")
    if len(raw_nodes) > MAX_NODES:
        raise DagRefusal("too_many_nodes", f"A run holds at most {MAX_NODES} nodes; split the goal into phases.")
    remaining = None if oneshot_limit is None else max(0, oneshot_limit - oneshot_spent)
    if remaining is not None and len(raw_nodes) > remaining:
        used = (f" This session already started {oneshot_spent} of its {oneshot_limit}, so {remaining} "
                f"{'is' if remaining == 1 else 'are'} left." if oneshot_spent else "")
        cut = (f"cut the graph to {remaining} or fewer" if remaining else "do the work in this session yourself")
        raise DagRefusal(
            "oneshot_budget_exceeded",
            f"This one-shot session may define at most {remaining} "
            f"{'node' if remaining == 1 else 'nodes'} (delegation.oneshot_max_children is {oneshot_limit}), and the "
            f"graph has {len(raw_nodes)}.{used} A one-shot run has no later session: {cut}, or "
            "run the work interactively.",
        )
    nodes = [_validated_node(raw) for raw in raw_nodes]
    require_prompt_markers(nodes)
    _require_graph(nodes)
    title = _plain(name, MAX_NAME_CHARS, "invalid_name", "The run needs a short name.") if name else run
    stated = _plain(goal, MAX_GOAL_CHARS, "invalid_goal", "The goal is one line.") if goal else ""
    return {
        "schema_version": DAG_SCHEMA_VERSION,
        "session_id": session_id,
        "run": run,
        "name": title,
        "goal": stated,
        "digest": definition_digest(nodes),
        "defined_at": now,
        "updated_at": now,
        "cancelled_at": None,
        "nodes": nodes,
        "repairs": {},
        "topology": topology(nodes),
        "lint": lint(nodes),
        "claim_boundary": DAG_CLAIM_BOUNDARY,
    }


# ── derivation ───────────────────────────────────────────────────────────


def bound_children(children: Sequence[Mapping[str, Any]], run: str) -> dict[str, list[Mapping[str, Any]]]:
    """The ledger's children bound to this run, per node, oldest start first."""
    by_node: dict[str, list[Mapping[str, Any]]] = {}
    for child in children:
        dag = child.get("dag")
        if isinstance(dag, Mapping) and dag.get("run") == run and isinstance(dag.get("node"), str):
            by_node.setdefault(dag["node"], []).append(child)
    for listed in by_node.values():
        listed.sort(key=lambda child: _number(child.get("started_at")) or 0.0)
    return by_node


def attempt_child(attempt: Mapping[str, Any], children: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    """The newest child that started for this attempt, if one did."""
    out = _number(attempt.get("handed_out_at")) or 0.0
    # A short park can end within the normal binding slack: its old child must not take the fresh attempt.
    slack = 0.0 if attempt.get("resume_handle") else BIND_SLACK_SECONDS
    matched = [child for child in children if (_number(child.get("started_at")) or 0.0) >= out - slack]
    return matched[-1] if matched else None


def _root(node: Mapping[str, Any]) -> str:
    return str(node.get("repairs") or node["id"])


def derive(record: Mapping[str, Any], children: Sequence[Mapping[str, Any]], now: float) -> dict[str, dict[str, Any]]:
    """Each node's state, what it waits on, and its bound child. Never stored; recomputed on every read."""
    nodes = {str(node["id"]): node for node in record["nodes"]}
    bound = bound_children(children, str(record["run"]))
    groups: Mapping[str, list[list[str]]] = record.get("repairs") or {}
    base: dict[str, dict[str, Any]] = {}
    for node_id, node in nodes.items():
        attempts = node.get("attempts") or []
        last = attempts[-1] if attempts else None
        info: dict[str, Any] = {"child": None, "attempts": len(attempts), "waits_on": [], "held_by": []}
        if last is None or last.get("outcome") == "retry":
            info["state"] = "pending"
        elif last.get("outcome") in OUTCOMES:
            info["state"] = str(last["outcome"])
            info["child"] = attempt_child(last, bound.get(node_id, []))
        else:
            child = attempt_child(last, bound.get(node_id, []))
            if child is not None and child.get("lost"):
                child = None
                info["lost"] = True
            info["child"] = child
            if child is None:
                info["state"] = "handed_out"
            elif isinstance(child.get("stop"), Mapping):
                info["state"] = "returned"
            else:
                info["state"] = "running"
        base[node_id] = info
    # A root's latest repair group, all accepted, stands in for it; older groups' unaccepted nodes are superseded.
    # A verification root is the exception: the group fixed what it found, and only the root running again says
    # the goal holds. Each failure of the root is answered by one group, so the re-run is due while the failures
    # number no more than the groups.
    for root, root_groups in groups.items():
        if root not in base or not root_groups:
            continue
        latest = root_groups[-1]
        if base[root]["state"] in ("failed", "blocked") and latest and all(
            base.get(member, {}).get("state") == "accepted" for member in latest
        ):
            failures = sum(1 for attempt in nodes[root].get("attempts") or [] if attempt.get("outcome") in ("failed", "blocked"))
            if not is_verification(nodes[root]):
                base[root]["state"] = "repaired"
            elif failures <= len(root_groups):
                base[root].update(state="pending", child=None)
        for older in root_groups[:-1]:
            for member in older:
                if member in base and base[member]["state"] != "accepted":
                    base[member]["state"] = "superseded"
    cancelled = record.get("cancelled_at") is not None
    satisfied = {node_id for node_id, info in base.items() if info["state"] in SATISFIED}
    dead = {node_id for node_id, info in base.items() if info["state"] in ("failed", "blocked")}
    for node_id, info in base.items():
        if info["state"] != "pending":
            if cancelled and info["state"] in LIVE:
                info["state"] = "cancelled"
            continue
        parents = nodes[node_id]["depends_on"]
        info["waits_on"] = [parent for parent in parents if parent not in satisfied]
        info["held_by"] = sorted(ancestor for ancestor in ancestors(node_id, {k: v["depends_on"] for k, v in nodes.items()})
                                 if ancestor in dead)
        if cancelled:
            info["state"] = "cancelled"
        elif info["waits_on"]:
            info["state"] = "held" if info["held_by"] else "waiting"
        else:
            info["state"] = "ready"
    return base


def cycles_left(record: Mapping[str, Any], node_id: str) -> int:
    nodes = {str(node["id"]): node for node in record["nodes"]}
    root = _root(nodes[node_id]) if node_id in nodes else node_id
    return MAX_REPAIR_CYCLES - len((record.get("repairs") or {}).get(root, []))


def open_failures(record: Mapping[str, Any], derived: Mapping[str, Mapping[str, Any]]) -> list[str]:
    """Failed or blocked nodes no accepted repair resolves, in record order."""
    return [str(node["id"]) for node in record["nodes"] if derived[str(node["id"])]["state"] in ("failed", "blocked")]


def run_state(record: Mapping[str, Any], derived: Mapping[str, Mapping[str, Any]]) -> str:
    """``done``, ``cancelled``, ``running``, ``needs_repair`` (failures, a cycle left) or ``stopped`` (none left)."""
    if record.get("cancelled_at") is not None:
        return "cancelled"
    live = [info for info in derived.values() if info["state"] != "superseded"]
    if all(info["state"] in SATISFIED for info in live):
        return "done"
    if any(info["state"] in LIVE or info["state"] == "ready" for info in live):
        return "running"
    failures = open_failures(record, derived)
    if any(cycles_left(record, node_id) > 0 for node_id in failures):
        return "needs_repair"
    return "stopped"


def goal_verdict(record: Mapping[str, Any], derived: Mapping[str, Mapping[str, Any]]) -> tuple[str, list[str]]:
    """Whether a passing verify node covers the run's work, and the reason codes when none does. Apart from
    `run_state`: a ``done`` run may be ``unverified``.

    ``verified``: every producer (`is_producer`; a repair node standing in
    for what it repairs) is an ancestor of a verify node that was accepted
    with its handoff checked, and every verify node passed. ``verify_failed``:
    a verify node is failed or blocked and no accepted re-run replaced it.
    Otherwise ``unverified``, with ``no_producers`` (nothing was built to
    verify), ``no_verification_node``, ``verification_open:<ids>``,
    ``verification_misses:<ids>`` (no passed verify node follows them), or
    ``handoff_not_checked:<id>`` (only that unread verify node follows a
    producer; a checked later one clears it). Read from the record and the
    derived states only (the outcomes the parent settled, Hermes' child
    status, the handoff reads), never from a child's or the model's own words.
    """
    superseded = {node_id for node_id, info in derived.items() if info["state"] == "superseded"}
    live = [node for node in record["nodes"] if str(node["id"]) not in superseded]
    checks = [node for node in live if is_verification(node)]
    failed = [str(node["id"]) for node in checks if derived[str(node["id"])]["state"] in ("failed", "blocked")]
    if failed:
        return "verify_failed", [f"verify_failed:{','.join(failed)}"]
    if not any(is_producer(node) for node in live):
        return "unverified", ["no_producers"]
    if not checks:
        return "unverified", ["no_verification_node"]
    passed = [node for node in checks if derived[str(node["id"])]["state"] == "accepted"]
    checked = [node for node in passed if not handoff_unchecked(node)]
    reasons = []
    still = [str(node["id"]) for node in checks if node not in passed]
    if still:
        reasons.append(f"verification_open:{','.join(still)}")
    uncovered = set(verification_misses(record["nodes"], checked, skip=superseded))
    unreached = verification_misses(record["nodes"], passed, skip=superseded)
    if unreached:
        reasons.append(f"verification_misses:{','.join(unreached)}")
    # An unread verify node counts for nothing; it is named only where it alone follows a producer.
    reasons += [f"handoff_not_checked:{node['id']}" for node in passed if handoff_unchecked(node)
                and uncovered - set(verification_misses(record["nodes"], [*checked, node], skip=superseded))]
    return ("unverified", reasons) if reasons else ("verified", [])


def counts(record: Mapping[str, Any], derived: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """The run's tallies. ``running`` counts nodes whose child is running, as the graph and its chat line do;
    ``out`` every node handed out and not settled (no child yet, running, or returned)."""
    live = {node_id: info for node_id, info in derived.items() if info["state"] != "superseded"}
    failures = open_failures(record, derived)
    labels = {str(node["id"]): str(node["label"]) for node in record["nodes"]}
    return {
        "total": len(live),
        "done": sum(1 for info in live.values() if info["state"] in SATISFIED),
        "running": sum(1 for info in live.values() if info["state"] == "running"),
        "out": sum(1 for info in live.values() if info["state"] in OPEN),
        "parked": sum(1 for info in live.values() if info["state"] == "parked"),
        "failed": len(failures),
        "first_failure": labels[failures[0]] if failures else "",
    }


def status_line(record: Mapping[str, Any], derived: Mapping[str, Mapping[str, Any]], *, added: str = "",
                now: float | None = None, limits: Limits = DEFAULT_LIMITS) -> str:
    """The one line a messenger reply carries on a completion turn: ``DAG <name> · 3/6 done · 2 running``.

    ``added`` is the clause naming nodes a repair or an extend round added
    since the chat last showed the run (`delegation_snapshot.added_clause`).
    With ``now``, nodes open past the stuck mark are counted, the oldest named
    with its age: ``1 open past 1h (Docs body 2h 10m)``.
    """
    tally = counts(record, derived)
    parts = [f"DAG {record['name']}", f"{tally['done']}/{tally['total']} done", f"{tally['running']} running"]
    if tally["parked"]:
        parts.append(f"{tally['parked']} parked")
    if tally["failed"]:
        parts.append(f"{tally['failed']} failed ({tally['first_failure']})")
    unchecked = sum(1 for node in record["nodes"]
                    if derived[str(node["id"])]["state"] == "accepted" and handoff_unchecked(node))
    if unchecked:
        parts.append(f"{unchecked} {HANDOFF_NOT_CHECKED}")
    found = stuck(record, derived, now, limits=limits) if now is not None else []
    if found:
        labels = {str(node["id"]): str(node["label"]) for node in record["nodes"]}
        oldest, age = found[0]
        more = f", +{len(found) - 1}" if len(found) > 1 else ""
        parts.append(f"{len(found)} open past {age_text(limits.stuck_after_s)} ({labels[oldest]} {age_text(age)}{more})")
    if added:
        parts.append(added)
    return " · ".join(parts)


# ── handing nodes out ────────────────────────────────────────────────────


def _layer_index(record: Mapping[str, Any]) -> dict[str, int]:
    nodes = record["nodes"]
    placed, _stuck = dag_core.layer_of([str(node["id"]) for node in nodes], {str(n["id"]): n["depends_on"] for n in nodes})
    return placed


def offerable(record: Mapping[str, Any], derived: Mapping[str, Mapping[str, Any]], now: float, *,
              limits: Limits = DEFAULT_LIMITS) -> list[str]:
    """Nodes to hand out now: ready ones, ones whose child a restart ended, and ones no child ever took."""
    order = _layer_index(record)
    nodes = []
    for node in record["nodes"]:
        node_id = str(node["id"])
        state = derived[node_id]["state"]
        if state == "ready":
            nodes.append(node_id)
        elif state == "parked":
            deadline = _number(node["attempts"][-1].get("wake_at"))
            if deadline is not None and now >= deadline:
                nodes.append(node_id)
        elif state == "handed_out":
            last = node["attempts"][-1]
            if last.get("lane") in ("fanout", "parent"):
                # Exported to a coding owner, or left to the parent once the one-shot child budget was spent: settled
                # from the fanout result or the parent's own work, never handed to delegate_task.
                continue
            if derived[node_id].get("lost"):
                if int(last.get("lost", 0)) < limits.max_lost_reoffers:
                    nodes.append(node_id)
            elif now - (_number(last.get("handed_out_at")) or 0.0) > limits.stale_after_s:
                nodes.append(node_id)
    return sorted(nodes, key=lambda node_id: (order.get(node_id, 0), node_id))


def lost_for_good(record: Mapping[str, Any], derived: Mapping[str, Mapping[str, Any]], *,
                  limits: Limits = DEFAULT_LIMITS) -> list[str]:
    """Nodes whose child a restart ended after ``limits.max_lost_reoffers`` offers (`MAX_LOST_REOFFERS` by default):
    not offered again; the parent settles them."""
    return [str(node["id"]) for node in record["nodes"] if derived[str(node["id"])].get("lost")
            and derived[str(node["id"])]["state"] == "handed_out"
            and int(node["attempts"][-1].get("lost", 0)) >= limits.max_lost_reoffers]


def opened_at(attempt: Mapping[str, Any]) -> float:
    """When the attempt first went out. Offering a node again moves ``handed_out_at`` but not this, so a node that
    keeps being offered and never taken still shows how long it has been open."""
    return _number(attempt.get("opened_at")) or _number(attempt.get("handed_out_at")) or 0.0


def open_for(record: Mapping[str, Any], derived: Mapping[str, Mapping[str, Any]], now: float) -> dict[str, float]:
    """Seconds each open node (handed out, running, or returned and not settled) has been open, by node id."""
    return {str(node["id"]): max(0.0, now - opened_at(node["attempts"][-1])) for node in record["nodes"]
            if derived[str(node["id"])]["state"] in OPEN and node.get("attempts")}


def stuck(record: Mapping[str, Any], derived: Mapping[str, Mapping[str, Any]], now: float, *,
          limits: Limits = DEFAULT_LIMITS) -> list[tuple[str, float]]:
    """Open nodes past ``limits.stuck_after_s``, oldest first, as ``(node id, seconds open)``; none when the mark is 0.

    Left out: a node whose child a restart ended (offered again, or settled past the bound, on its own line), and
    one exported to a coding owner or left to the parent, which no delegate_task child runs.
    """
    if limits.stuck_after_s <= 0:
        return []
    lanes = {str(node["id"]): (node.get("attempts") or [{}])[-1].get("lane") for node in record["nodes"]}
    found = [(node_id, age) for node_id, age in open_for(record, derived, now).items()
             if age > limits.stuck_after_s and not derived[node_id].get("lost")
             and lanes[node_id] not in ("fanout", "parent")]
    return sorted(found, key=lambda item: (-item[1], item[0]))


def age_text(seconds: float) -> str:
    """``9h 12m``, ``45m``, ``1h``: whole minutes, never under one."""
    minutes = max(1, int(seconds // 60))
    hours, minutes = divmod(minutes, 60)
    if not hours:
        return f"{minutes}m"
    return f"{hours}h {minutes}m" if minutes else f"{hours}h"


def stuck_say(record: Mapping[str, Any], derived: Mapping[str, Mapping[str, Any]],
              found: Sequence[tuple[str, float]], limits: Limits = DEFAULT_LIMITS) -> str:
    """What the parent is told about stuck nodes: which, for how long, and what to check. ``""`` for none.

    A node no child took, one whose child still runs, and one whose child came back unsettled each get their own
    sentence, because each has a different thing to check.
    """
    mark = age_text(limits.stuck_after_s)
    by_state: dict[str, list[str]] = {"handed_out": [], "running": [], "returned": []}
    for node_id, age in found:
        by_state[str(derived[node_id]["state"])].append(f"{node_id} ({age_text(age)})")
    parts = []
    for state, named in by_state.items():
        if not named:
            continue
        one = len(named) == 1
        head = f"{'Node' if one else 'Nodes'} {', '.join(named)}"
        it, each = ("it", "it") if one else ("them", "each")
        if state == "handed_out":
            parts.append(
                f"{head} {'has' if one else 'have'} been out past the {mark} stuck mark with no child taking "
                f"{it}: the delegate_task call did not start one (a refused route does that). Dispatch the call "
                f"ready returns for {it}, or settle {each} failed if the route cannot run.")
        elif state == "running":
            parts.append(
                f"{head} {'has' if one else 'have'} run past the {mark} stuck mark: run delegate_task action=list, "
                f"and settle {each} failed and repair when no child of {it} is live there.")
        else:
            parts.append(
                f"{head} came back but {'is' if one else 'are'} still not settled past the {mark} stuck mark: read "
                f"{'its handoff' if one else 'each handoff'} and settle {each}.")
    return " ".join(parts)


def resume_handle_for(attempts: Sequence[Mapping[str, Any]]) -> str:
    """The process identity a new attempt must resume, or ``""`` for fresh work.

    A park hands its ``handle`` to the wake attempt, and a provider-error retry
    replaces that attempt without ending the wait, so it inherits the attempt's
    ``resume_handle``. Only the immediately previous attempt is read: once a
    resumed attempt settles accepted, failed or blocked, its handle dies with it
    and later work on the node (a repair re-run, for instance) starts fresh
    instead of checking an unrelated old process.
    """
    if not attempts:
        return ""
    previous = attempts[-1]
    if previous.get("outcome") == "parked":
        return str(previous.get("handle") or "")
    if previous.get("outcome") == "retry":
        return str(previous.get("resume_handle") or "")
    return ""


def hand_out(node: dict[str, Any], derived_state: str, now: float, *, lost: bool = False) -> dict[str, Any]:
    """Write-ahead: the attempt exists before its goal leaves this tool, so a marker always finds it.

    ``lost``: the attempt is offered again because a restart ended its child, which the attempt counts.
    """
    attempts = node.setdefault("attempts", [])
    if derived_state == "handed_out" and attempts:
        attempts[-1].setdefault("opened_at", attempts[-1].get("handed_out_at"))
        attempts[-1]["handed_out_at"] = now
        attempts[-1]["reoffered"] = int(attempts[-1].get("reoffered", 0)) + 1
        if lost:
            attempts[-1]["lost"] = int(attempts[-1].get("lost", 0)) + 1
        return attempts[-1]
    fallback = bool(attempts) and attempts[-1].get("outcome") == "retry"
    attempt = {"n": len(attempts) + 1, "handed_out_at": now, "fallback": fallback,
               "settled_at": None, "outcome": "", "reason": "", "provider_error": False}
    handle = resume_handle_for(attempts)
    if handle:
        attempt["resume_handle"] = handle
    attempts.append(attempt)
    return attempt


def reads_for(record: Mapping[str, Any], derived: Mapping[str, Mapping[str, Any]], node: Mapping[str, Any]) -> list[str]:
    """The nodes whose handoff files ``node`` reads: its parents, a repaired parent replaced by its latest repair group."""
    groups = record.get("repairs") or {}
    reads: list[str] = []
    for parent in node["depends_on"]:
        if derived.get(parent, {}).get("state") == "repaired" and groups.get(parent):
            reads.extend(groups[parent][-1])
        else:
            reads.append(parent)
    return reads


def task_for(
    record: Mapping[str, Any], node: Mapping[str, Any], omh_home: Path, derived: Mapping[str, Mapping[str, Any]]
) -> dict[str, str]:
    """One `delegate_task` task: the marked goal, and the node's prompt with where to write and read handoffs."""
    run = str(record["run"])
    lines = [str(node["prompt"]), ""]
    attempts = node.get("attempts") or []
    if attempts and attempts[-1].get("resume_handle"):
        lines.extend([f"Resume the still-running wait: {attempts[-1]['resume_handle']}. "
                      "Check its result before starting any replacement work.", ""])
    goal = record.get("goal")
    if isinstance(goal, str) and goal.strip():
        lines.extend([
            f"Run goal (saved):\n{goal}\n",
            "The run goal is acceptance context, not permission to widen your SCOPE.",
            "",
        ])
    lines.extend([
        f"Handoff: before you stop, write your report to {node_handoff(record, omh_home, str(node['id']))}: "
        "what you did, the files you changed, what VERIFY showed, and anything still open. The parent reads that "
        "file and your final message.",
    ])
    if node["depends_on"]:
        reads = ", ".join(node_handoff(record, omh_home, parent) for parent in reads_for(record, derived, node))
        lines.append(f"Read first: {reads}. A missing file means that part did not finish: stop and say so.")
    if is_verification(node):
        parents = {str(item["id"]): item["depends_on"] for item in record["nodes"]}
        preceding = ancestors(str(node["id"]), parents)
        for baseline in record["nodes"]:
            if str(baseline["id"]) in preceding and is_baseline(baseline):
                lines.append(f"Baseline: Read {node_handoff(record, omh_home, str(baseline['id']))}. Exempt only a "
                             "failure it lists that you re-ran here with the same test id and assertion/error "
                             "signature, under a comparable command and environment at the pinned base and candidate "
                             "revisions; report it as pre-existing. A same-id failure that changed, missing evidence, "
                             "skipped or reduced coverage, collection/execution/exit errors, and security or mandatory "
                             "gates are never exempt: fail them. A baseline list does not make an unmet full-suite-green "
                             "goal done.")
        lines.append("Check the complete run goal, not only this node's local VERIFY. "
                     "Name each unmet or unobserved goal criterion; producer claims are not verification evidence.")
    lines.append("Stay inside your SCOPE: other parts of this run work at the same time. If you cannot finish, "
                 "say plainly that you are blocked and why; do not report blocked work as done.")
    # The marker ends the goal: Hermes previews each goal by its first 40 characters, and a person reads the label
    # there. It stays on the label's line, since Hermes prints `goal[:40]` as a one-line completion label.
    return {"goal": f"{node['label']} [dag:{run}/{node['id']}]", "context": "\n".join(lines)}


def _call_route(
    category: str, fallback: bool, retries: int, backend: Mapping[str, Any] | None
) -> tuple[dict[str, Any], str]:
    """The call's ``route`` and the model_map option its tasks carry (``""`` for none).

    Under `default` (or an unread backend: ``None``) the parent sets the
    route with `omh_delegate_route` as before. Under `model_map` the option
    goes on each task and no tool runs: a provider-error retry takes the
    category's next option. Any other backend gets nothing from OMH -- it
    never picks a `profile_routes` profile.
    """
    name = str((backend or {}).get("backend") or "default")
    if name == "default":
        return {"tool": "omh_delegate_route", "action": "fallback" if fallback else "set", "category": category}, ""
    route: dict[str, Any] = {"backend": name, "category": category}
    if name != "model_map" or (backend or {}).get("status") != "read":
        route["status"] = "not_applied"
        return route, ""
    names = list(((backend or {}).get("options") or {}).get(category) or [])
    if retries < len(names):
        route.update(status="option_selected", option=names[retries])
        return route, names[retries]
    route["status"] = "options_exhausted" if names else "no_matching_option"
    return route, ""


def calls_for(
    record: dict[str, Any], derived: Mapping[str, Mapping[str, Any]], *, free_slots: int, per_call: int,
    omh_home: Path, now: float, skip: Iterable[str] = (), task_budget: int | None = None,
    backend: Mapping[str, Any] | None = None, limits: Limits = DEFAULT_LIMITS,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Ready nodes as `delegate_task` calls, one per category (and route fallback), at most ``free_slots`` calls.

    Returns the calls, whose nodes are now handed out in ``record``, and the
    ready nodes left for a later call because no slot was free, or because
    the calls already carry ``task_budget`` tasks in all (a one-shot session's
    children left: every task costs one, a re-offered node's too). ``skip``
    are nodes that go elsewhere (an external coding owner's export).
    ``backend`` is Hermes' delegation backend as `omh_dag` read it
    (``backend``, ``status``, and per-category model_map ``options``); see
    `_call_route`.
    """
    nodes = {str(node["id"]): node for node in record["nodes"]}
    groups: dict[tuple[str, bool, int], list[str]] = {}
    skipped = set(skip)
    # Under model_map the option is the retry count's: nodes on different retries go in different calls.
    by_option = str((backend or {}).get("backend") or "") == "model_map"
    for node_id in offerable(record, derived, now, limits=limits):
        if node_id in skipped:
            continue
        node = nodes[node_id]
        attempts = node.get("attempts") or []
        fallback = bool(attempts) and attempts[-1].get("outcome") == "retry"
        retries = sum(1 for item in attempts if item.get("outcome") == "retry") if by_option else 0
        groups.setdefault((str(node["category"]), fallback, retries), []).append(node_id)
    calls: list[dict[str, Any]] = []
    held: list[str] = []
    size = max(1, per_call)
    left = None if task_budget is None else max(0, task_budget)
    for (category, fallback, retries), members in groups.items():
        route, option = _call_route(category, fallback, retries, backend)
        for start in range(0, len(members), size):
            chunk = members[start:start + size]
            if left is not None:
                held.extend(chunk[left:])
                chunk = chunk[:left]
            if not chunk:
                continue
            if len(calls) >= free_slots:
                held.extend(chunk)
                continue
            if left is not None:
                left -= len(chunk)
            for node_id in chunk:
                attempt = hand_out(nodes[node_id], derived[node_id]["state"], now,
                                   lost=bool(derived[node_id].get("lost")))
                if "backend" in route:
                    attempt.update(backend=route["backend"], option=option)
            tasks = [task_for(record, nodes[node_id], omh_home, derived) for node_id in chunk]
            if option:
                tasks = [{**task, "option": option} for task in tasks]
            calls.append({"category": category, "route": dict(route), "nodes": chunk, "tasks": tasks})
    return calls, held


# ── settling and repairing ───────────────────────────────────────────────


def _park_deadline(value: object, now: float) -> float:
    deadline = _number(value)
    if isinstance(value, str):
        try:
            parsed = strict_fromisoformat(value)
            offset = parsed.utcoffset()
            if offset is not None and offset.total_seconds() == 0:
                deadline = parsed.timestamp()
        except (ValueError, OverflowError, OSError):
            deadline = None
    if deadline is None or not 0 < deadline - now <= MAX_PARK_SECONDS:
        raise DagRefusal("invalid_wake_at",
                         "parked needs wake_at as UTC ISO-8601 or epoch, in the future and at most 24 hours ahead.")
    return deadline


def settle(
    record: dict[str, Any], derived: Mapping[str, Mapping[str, Any]], node_id: str, outcome: object, reason: object,
    provider_error: bool, *, read_handoff: Callable[[], tuple[bool, str]], now: float,
    handle: object = None, wake_at: object = None,
) -> str:
    """Close the node's open attempt. Returns what happened: the outcome, or ``retry`` (a provider error's one retry).

    ``read_handoff`` answers (found, unread) and is called only for an
    ``accepted`` settle that every other check let through, so a settle
    refused for another reason reads nothing. ``unread`` names why the
    handoff could not be read where the child wrote it
    (`dag_tool.backend_handoff`): ``accepted`` then stands, and the attempt
    records ``handoff_checked: false`` with that reason.
    """
    nodes = {str(node["id"]): node for node in record["nodes"]}
    if node_id not in nodes:
        raise DagRefusal("unknown_node", f"Node {node_id} is not in run {record['run']}.")
    if record.get("cancelled_at") is not None:
        raise DagRefusal("run_cancelled", "The run was cancelled; nothing in it settles now.")
    if outcome not in OUTCOMES:
        raise DagRefusal("invalid_outcome", "Settle a node as accepted, failed, blocked or parked.")
    info = derived[node_id]
    if info["state"] not in OPEN:
        raise DagRefusal("node_not_out", f"Node {node_id} is {info['state']}, not out with a child; nothing to settle.")
    if outcome == "parked" and sum(1 for item in nodes[node_id]["attempts"]
                                   if item.get("outcome") == "parked") >= MAX_PARKS:
        raise DagRefusal("park_limit_reached",
                         f"Node {node_id} has parked {MAX_PARKS} times; settle it accepted, failed or blocked.")
    if outcome == "parked":
        if (not isinstance(handle, str) or not handle.strip() or len(handle) > MAX_HANDLE_CHARS
                or _CONTROL.search(handle) or any(char in handle for char in "\r\n\t")):
            raise DagRefusal("invalid_handle", "parked needs a nonempty handle of at most 120 characters on one line.")
        wake_at = _park_deadline(wake_at, now)
    child = info["child"]
    stop = child.get("stop") if isinstance(child, Mapping) else None
    if outcome == "accepted" and isinstance(stop, Mapping) and stop.get("status") in CHILD_FAILURE_STOPS:
        raise DagRefusal(
            "child_reported_failure",
            f"Hermes reported node {node_id}'s child {stop.get('status')}; settle it failed or blocked, not accepted.",
        )
    if reason and record.get("backend"):
        # A run on a Docker or SSH terminal checks the reason before its backend is asked, so a bad one sends nothing.
        _plain(reason, MAX_REASON_CHARS, "invalid_reason", "The reason is one short line.")
    unread = ""
    if outcome == "accepted":
        found, unread = read_handoff()
        if not found and not unread:
            raise DagRefusal(
                "handoff_missing",
                f"Node {node_id} has no handoff file, and the nodes after it read one. Write it from the child's "
                "result, or settle the node failed.",
            )
    attempt = nodes[node_id]["attempts"][-1]
    retries = sum(1 for item in nodes[node_id]["attempts"] if item.get("outcome") == "retry")
    note = _plain(reason, MAX_REASON_CHARS, "invalid_reason", "The reason is one short line.") if reason else ""
    attempt.update(settled_at=now, reason=note, provider_error=bool(provider_error))
    if outcome == "failed" and provider_error and retries < MAX_PROVIDER_RETRIES:
        attempt["outcome"] = "retry"
        return "retry"
    attempt["outcome"] = outcome
    if outcome == "parked":
        attempt.update(handle=handle, wake_at=wake_at)
    if outcome == "accepted" and unread:
        attempt.update(handoff_checked=False, handoff_unread=unread)
    return str(outcome)


def handoff_unchecked(node: Mapping[str, Any]) -> bool:
    """True when the node's last attempt was accepted without its handoff read (``handoff_checked: false``)."""
    attempts = node.get("attempts") or []
    return bool(attempts) and isinstance(attempts[-1], Mapping) and attempts[-1].get("handoff_checked") is False


def _require_oneshot_room(added: Sequence[Mapping[str, Any]], remaining: int | None, what: str) -> None:
    if remaining is not None and len(added) > remaining:
        raise DagRefusal(
            "oneshot_budget_exceeded",
            f"This one-shot session can start {remaining} more "
            f"{'child' if remaining == 1 else 'children'} (delegation.oneshot_max_children), and the {what} adds "
            f"{len(added)} {'node' if len(added) == 1 else 'nodes'}. Add {remaining} or fewer, or do the work in this "
            "session yourself and report what is open.",
        )


def repair(
    record: dict[str, Any], derived: Mapping[str, Mapping[str, Any]], node_id: str, raw_nodes: object, now: float,
    *, oneshot_remaining: int | None = None,
) -> list[str]:
    """Add a group of repair nodes for a failed or blocked node. Returns the new ids.

    ``oneshot_remaining``: the children a one-shot session can still start; a group larger than that is refused.
    """
    nodes = {str(node["id"]): node for node in record["nodes"]}
    if node_id not in nodes:
        raise DagRefusal("unknown_node", f"Node {node_id} is not in run {record['run']}.")
    if record.get("cancelled_at") is not None:
        raise DagRefusal("run_cancelled", "The run was cancelled; start a new run instead.")
    if derived[node_id]["state"] not in ("failed", "blocked"):
        raise DagRefusal("not_failed", f"Node {node_id} is {derived[node_id]['state']}; only a failed or blocked node is repaired.")
    root = _root(nodes[node_id])
    groups = record.setdefault("repairs", {}).setdefault(root, [])
    if len(groups) >= MAX_REPAIR_CYCLES:
        raise DagRefusal(
            "repair_limit_reached",
            f"{root} has had {MAX_REPAIR_CYCLES} repair cycles; report what is still open instead of repairing again.",
        )
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise DagRefusal("empty_graph", "A repair needs at least one node.")
    added = [_validated_node(raw) for raw in raw_nodes]
    require_prompt_markers(added)
    if len(nodes) + len(added) > MAX_NODES:
        raise DagRefusal("too_many_nodes", f"A run holds at most {MAX_NODES} nodes.")
    group = {str(node["id"]) for node in added}
    accepted = {key for key, info in derived.items() if info["state"] in SATISFIED}
    for node in added:
        outside = [parent for parent in node["depends_on"] if parent not in group and parent not in accepted]
        if outside:
            raise DagRefusal(
                "repair_depends_on_open_node",
                f"Repair node {node['id']} may depend only on accepted nodes or its own group, not {', '.join(outside)}.",
            )
        node.update(repairs=root, cycle=len(groups) + 1, origin=f"repair:{root}")
    runnable = {key for key, info in derived.items() if info["state"] in LIVE | {"ready", "waiting", "held"}}
    # The group runs before every node that waits on the root (they wait on the root, the root on the group), so a
    # dependent writing what the group writes is ordered, not an overlap.
    every = {str(node["id"]): node["depends_on"] for node in record["nodes"]}
    below = {key: sorted(group) for key in every if root in ancestors(key, every)}
    _require_graph(list(record["nodes"]) + added, editable=group | runnable, before=below)
    _require_oneshot_room(added, oneshot_remaining, "repair")
    record["nodes"].extend(added)
    groups.append([str(node["id"]) for node in added])
    record["topology"] = topology(record["nodes"])
    record["lint"] = lint(record["nodes"])
    record["updated_at"] = now
    return [str(node["id"]) for node in added]


def extend_rounds_left(record: Mapping[str, Any]) -> int:
    return MAX_EXTEND_ROUNDS - len(record.get("extends") or [])


def extend(
    record: dict[str, Any], derived: Mapping[str, Mapping[str, Any]], raw_nodes: object, found_by: object, now: float,
    *, oneshot_remaining: int | None = None,
) -> list[str]:
    """Add a round of nodes to a run whose every node passed but whose goal check found work missing.

    The new nodes may depend on the run's accepted nodes and on each other.
    The whole run then passes define's hard rejects: unknown or self edges, a
    cycle, `MAX_NODES` over every round, and a write scope a new node shares
    without an edge with any node of the run, finished ones included (a
    superseded repair node excepted). ``found_by`` names the node whose check
    found the gap; without it, the run's last accepted verification node.
    ``oneshot_remaining``: the children a one-shot session can still start;
    a round larger than that is refused. Returns the new ids.
    """
    nodes = {str(node["id"]): node for node in record["nodes"]}
    if record.get("cancelled_at") is not None:
        raise DagRefusal("run_cancelled", "The run was cancelled; start a new run instead.")
    state = run_state(record, derived)
    if state != "done":
        raise DagRefusal(
            "run_not_done",
            f"The run is {state.replace('_', ' ')}: extend adds work only once every node is accepted. Finish the "
            "run, or repair the failed node.",
        )
    rounds = record.setdefault("extends", [])
    if len(rounds) >= MAX_EXTEND_ROUNDS:
        raise DagRefusal(
            "extend_limit_reached",
            f"This run has had {MAX_EXTEND_ROUNDS} extend rounds; report what is still open instead of extending again.",
        )
    if found_by not in (None, ""):
        origin = valid_id(found_by, "invalid_node_id", "Name the node whose check found the missing work.")
        if origin not in nodes:
            raise DagRefusal("unknown_node", f"Node {origin} is not in run {record['run']}.")
    else:
        checks = [key for key, node in nodes.items() if is_verification(node) and derived[key]["state"] in SATISFIED]
        origin = checks[-1] if checks else ""
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise DagRefusal("empty_graph", "An extend round needs at least one node.")
    added = [_validated_node(raw) for raw in raw_nodes]
    require_prompt_markers(added)
    if len(nodes) + len(added) > MAX_NODES:
        raise DagRefusal(
            "too_many_nodes", f"A run holds at most {MAX_NODES} nodes, extend rounds included; report what is open.")
    group = {str(node["id"]) for node in added}
    live = {key for key, info in derived.items() if info["state"] != "superseded"}
    _require_graph(list(record["nodes"]) + added, editable=live | group, involving=group)
    for node in added:
        outside = [parent for parent in node["depends_on"]
                   if parent not in group and derived[parent]["state"] not in SATISFIED]
        if outside:
            raise DagRefusal(
                "extend_depends_on_open_node",
                f"Node {node['id']} may depend only on accepted nodes or on this round's own, not {', '.join(outside)}.",
            )
        node.update(origin=f"extend:{len(rounds) + 1}", found_by=origin)
    _require_oneshot_room(added, oneshot_remaining, "extend round")
    record["nodes"].extend(added)
    rounds.append([str(node["id"]) for node in added])
    record["topology"] = topology(record["nodes"])
    record["lint"] = lint(record["nodes"])
    record["updated_at"] = now
    return [str(node["id"]) for node in added]


def node_rows(record: Mapping[str, Any], derived: Mapping[str, Mapping[str, Any]],
              now: float | None = None) -> list[dict[str, Any]]:
    """What `status` says per node: no prompt, no child output. With ``now``, an open node carries ``open_for_s``,
    the whole seconds since its attempt first went out."""
    ages = open_for(record, derived, now) if now is not None else {}
    rows = []
    for node in record["nodes"]:
        node_id = str(node["id"])
        info = derived[node_id]
        attempts = node.get("attempts") or []
        row: dict[str, Any] = {
            "id": node_id, "label": node["label"], "category": node["category"], "state": info["state"],
            "attempts": len(attempts), "depends_on": list(node["depends_on"]),
        }
        if info["waits_on"]:
            row["waits_on"] = list(info["waits_on"])
        if info["held_by"]:
            row["held_by"] = list(info["held_by"])
        if node.get("repairs"):
            row["repairs"] = node["repairs"]
        if node.get("origin", "define") != "define":
            row["origin"] = node["origin"]
        if node.get("found_by"):
            row["found_by"] = node["found_by"]
        if attempts and attempts[-1].get("reason"):
            row["reason"] = attempts[-1]["reason"]
        if info["state"] == "accepted" and handoff_unchecked(node):
            row.update(handoff_checked=False, handoff_unread=str(attempts[-1].get("handoff_unread") or ""))
        if info["state"] == "parked":
            row.update(handle=attempts[-1]["handle"], wake_at=attempts[-1]["wake_at"])
        if info["state"] in ("failed", "blocked"):
            row["repair_cycles_left"] = cycles_left(record, node_id)
        if node_id in ages:
            row["open_for_s"] = int(ages[node_id])
        rows.append(row)
    return rows
