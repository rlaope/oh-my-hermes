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
scopes, roles, the goal's separately checkable criteria when the parent gave
them, and each node's prompt, kept so ``ready`` can hand a node out after
the parent's own context was compacted. It holds no child output, summary or
tool history. Data between nodes moves through handoff files whose paths
this module names (`handoff_path`); it reads one only for whether it exists
and, for a verify node of a run with criteria, its ``CRITERION <id>: <status>``
lines, of which an attempt keeps the status word per criterion and nothing
else (`criterion_statuses`). On a Docker or SSH terminal the child writes its file
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
original node. Its last repair cycle briefs a re-plan from the earlier
failures, not another retry of the same approach. Once its latest group is
all accepted the original counts as satisfied and the nodes after it read
the group's handoff files, except a verification node (or a role-less writer
guessed as one, ``role_guess``): it runs again, and only its own accepted
re-run satisfies it. Nodes of an earlier group that never got accepted are
superseded. ``extend`` adds a round of nodes to a run whose every node passed
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
import unicodedata

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
OVERLAPS_NAMED: Final = 20  # pairs one write_scope_overlap refusal names; the rest are counted
MAX_REASON_CHARS: Final = 200
# The goal split into separately checkable outcomes (`criteria`), each an id and one line, given at define or extend.
MAX_CRITERIA: Final = 12
MAX_CRITERION_CHARS: Final = MAX_GOAL_CHARS
CRITERION_FIELDS: Final = frozenset({"id", "text"})
# What a verify node's handoff says per criterion (`criterion_statuses`); a view adds `unchecked` (no read yet).
CRITERION_STATUSES: Final = ("met", "unmet", "unobserved")
# How much of a verify node's handoff is read for its criterion lines; the rest is ignored.
MAX_HANDOFF_READ_BYTES: Final = 262_144
# What a goal over `MAX_GOAL_CHARS` (or not text) is told: the conditions go into criteria, each the state asked for.
GOAL_REFUSED: Final = (
    f"The goal is one short line of at most {MAX_GOAL_CHARS} characters: keep `goal` to what the request is for, and "
    "put each checkable outcome in `criteria` ({id, text}, one line each), each naming the state the person asked "
    "for, not that a check was run or its result reported."
)
# The verify node's producer scope map and a repair node's `git diff` paths are cut at these lengths (per node turn).
SCOPE_MAP_CHARS: Final = 600
LEFTOVER_PATHS_CHARS: Final = 300
MAX_REPAIR_CYCLES: Final = 2
REPLAN_CYCLE: Final = MAX_REPAIR_CYCLES
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
# The categories that carry the one judgement deciding a run (a design decision, a root cause, a contested
# trade-off); a graph this wide with none of them is told to give that node `ultrabrain` (`no_judgement_node`).
JUDGEMENT_CATEGORIES: Final = frozenset({"ultrabrain", "architect", "forensics"})
JUDGEMENT_GRAPH_NODES: Final = 4
OUTCOMES: Final = ("accepted", "failed", "blocked", "parked")
# The ``origin`` kinds of a node added after define: ``repair:<root>`` and ``extend:<round>``.
ADDED_ORIGIN_KINDS: Final = ("repair", "extend")
PROMPT_MARKERS: Final = ("TASK", "DELIVERABLE", "SCOPE", "VERIFY", "STOP WHEN")
# A run this wide whose build nodes mostly sit on one chain is one chain wearing a graph's clothes (`build_chain`).
# Baseline, review and verify nodes are serial by design, so they do not count toward the chain.
SERIAL_GRAPH_NODES: Final = 5
SERIAL_GRAPH_SHARE: Final = 0.8
# Hermes' `subagent_stop` words that say the child did not finish (`delegation_graph._FAILED_STOPS` plus interrupted).
CHILD_FAILURE_STOPS: Final = frozenset({"failed", "error", "timeout", "interrupted"})
# What every view says for a node accepted while its handoff could not be read where the child wrote it.
HANDOFF_NOT_CHECKED: Final = "handoff not checked"
EXTERNAL_OWNERS: Final = ("claude-code", "codex")
NODE_FIELDS: Final = frozenset({"id", "label", "category", "prompt", "depends_on", "write_scope", "role", "owner",
                                "local"})
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
# Read only for a new node's guess (``role_guess``), not for a node stored before nodes carried a role (`node_role`).
_DOUBLE_CHECK: Final = re.compile(r"(?<![a-z])double[- ]check")
# A write scope entry with one of these suffixes is docs, not code (`writes_code`).
DOC_SUFFIXES: Final = frozenset({".md", ".markdown", ".rst", ".adoc", ".txt"})
# A write scope entry named exactly one of these (casefolded, no suffix) is docs, not code (`writes_code`).
DOC_NAMES: Final = frozenset({"readme", "changelog", "license", "notice", "authors", "contributing", "copying"})
# `CRITERION <id> #<token>: met|unmet|unobserved` at a line's start (after spaces, list bullets or backticks), then
# the rest (`criterion_statuses`): nothing, or a separator and the evidence. The token is the attempt's own.
_CRITERION_LINE: Final = re.compile(
    r"[ \t*`-]*CRITERION[ \t]+([A-Za-z0-9][A-Za-z0-9-]{0,31})[ \t]+#([A-Za-z0-9]{1,16})[ \t]*:[ \t]*"
    r"(?i:(met|unmet|unobserved))(.*)")
_CRITERION_EVIDENCE: Final = re.compile("[ \t]*[-:\u2013\u2014](.*)")
# The random token a verify node's attempt in a run with criteria carries (`hand_out`), in hex digits.
ATTEMPT_TOKEN_BYTES: Final = 3
# Of a verify node's handoff head only the last lines naming the marker are read, each cut at a byte count, the same
# way on this host and in a Docker or SSH terminal (`criterion_lines`, `dag_tool.backend_criterion_lines`).
CRITERION_LINE_BYTES: Final = 400
CRITERION_LINES_KEPT: Final = 64
# The unread reason for a handoff that is on this host but cannot be opened (`dag_tool.read_handoff_criteria`).
HANDOFF_UNREADABLE: Final = "handoff_unreadable"
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
    # The coding owners the defining request named (`dag_tool._define`); only `define` writes them.
    owners = raw.get("owners", [])
    if not isinstance(owners, list) or not all(isinstance(owner, str) and owner in EXTERNAL_OWNERS for owner in owners):
        return False
    # The goal criteria (`_validated_criteria`); a run defined without them has no key.
    criteria = raw.get("criteria", [])
    if not isinstance(criteria, list) or not all(
            isinstance(item, dict) and isinstance(item.get("id"), str) and _ID.fullmatch(item["id"])
            and isinstance(item.get("text"), str) for item in criteria):
        return False
    if len({item["id"] for item in criteria}) != len(criteria):
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
        if "owner" in node and (node["owner"] not in EXTERNAL_OWNERS or not is_coding(node)):
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
                         "Each node takes only id, label, category, prompt, depends_on, write_scope, role, owner and "
                         "local.")
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
    if guess == DEFAULT_ROLE and "role" not in raw and _DOUBLE_CHECK.search(label.casefold()):
        guess = "verify"
    if guess != DEFAULT_ROLE:
        # The node runs as a build node and stays a producer; the lint names the role its label reads like, and the
        # guess keeps it native (`is_coding`). Not in the digest (`NODE_FIELDS`).
        validated["role_guess"] = guess
    if "owner" in raw:
        if raw["owner"] not in EXTERNAL_OWNERS or not is_coding(validated):
            raise DagRefusal("invalid_owner",
                             f"Node {node_id}: owner is one of {', '.join(EXTERNAL_OWNERS)} and only a coding node may name it.")
        validated["owner"] = raw["owner"]
    if "local" in raw:
        # A node whose material must not leave the machine: only a local model_map option runs it (`local_options`).
        # An external coding CLI calls its own cloud model, so a local node never names one. Stored only when true,
        # so a node sent with `local: false` keeps the digest it had before the field existed.
        if not isinstance(raw["local"], bool):
            raise DagRefusal("invalid_local", f"Node {node_id}: local is true or false.")
        if raw["local"] and "owner" in validated:
            raise DagRefusal("invalid_local",
                             f"Node {node_id}: a local node runs only on a local model, so it cannot name an owner.")
        if raw["local"]:
            validated["local"] = True
    return validated


def _validated_criteria(raw: object, taken: Sequence[str] = ()) -> list[dict[str, str]]:
    """The goal criteria as given at define (``taken`` empty) or extend (``taken``: the ids the run already has).

    Each is ``{id, text}``: an id as a node's, and one plain line. New ids
    only; nothing rewrites or removes a criterion, and a run holds at most
    `MAX_CRITERIA` in all.
    """
    if not isinstance(raw, list):
        raise DagRefusal("invalid_criteria",
                         f"criteria lists up to {MAX_CRITERIA} outcomes, each {{id, text}}; leave it out when the goal "
                         "has no separately checkable outcome.")
    if len(taken) + len(raw) > MAX_CRITERIA:
        raise DagRefusal("invalid_criteria",
                         f"A run holds at most {MAX_CRITERIA} criteria in all; merge the outcomes that are checked "
                         "together.")
    criteria: list[dict[str, str]] = []
    seen = set(taken)
    for item in raw:
        if not isinstance(item, Mapping) or set(item) != CRITERION_FIELDS:
            raise DagRefusal("invalid_criteria", "Each criterion takes exactly id and text.")
        raw_id = item.get("id")
        # Read in lower case (`C1` is `c1`), here and in the handoff lines (`criterion_status`).
        criterion_id = valid_id(raw_id.lower() if isinstance(raw_id, str) else raw_id, "invalid_criteria",
                                "Each criterion needs a short id (a-z, 0-9, -; upper case reads as lower case).")
        if criterion_id in seen:
            raise DagRefusal("invalid_criteria",
                             f"Criterion {criterion_id} is already in the run; give each criterion its own id "
                             "(extend adds new ones only, and nothing rewrites one).")
        seen.add(criterion_id)
        text = item.get("text")
        if isinstance(text, str) and "\n" in text:
            text = None
        criteria.append({"id": criterion_id, "text": _plain(
            text, MAX_CRITERION_CHARS, "invalid_criteria",
            f"Criterion {criterion_id}: text is one plain line of at most {MAX_CRITERION_CHARS} characters.")})
    return criteria


def run_criteria(record: Mapping[str, Any]) -> list[dict[str, str]]:
    """The run's goal criteria, in the order given; ``[]`` for a run defined without them."""
    return list(record.get("criteria") or [])


def criterion_lines(data: bytes) -> list[str]:
    """The lines of a handoff's head that a criterion can be read from, as every reader takes them.

    The first `MAX_HANDOFF_READ_BYTES` bytes, NUL made SOH, the lines (split
    on ``\\n``) holding ``CRITERION``, each cut at `CRITERION_LINE_BYTES`, the
    last `CRITERION_LINES_KEPT` kept, decoded as UTF-8 with replacement. A
    Docker or SSH terminal runs the same steps in its shell
    (`dag_tool.backend_criterion_lines`), so both sides hand
    `criterion_status` the same lines.
    """
    head = data[:MAX_HANDOFF_READ_BYTES].replace(b"\x00", b"\x01")
    kept = [line[:CRITERION_LINE_BYTES] for line in head.split(b"\n") if b"CRITERION" in line][-CRITERION_LINES_KEPT:]
    return b"\n".join(kept).decode("utf-8", errors="replace").split("\n")


def criterion_status(line: str, ids: Iterable[str], token: str) -> tuple[str, str] | None:
    """``(id, status)`` when ``line`` is a criterion line of the attempt whose token is ``token`` for one of
    ``ids``, else None. An empty ``token`` (an attempt stored without one) matches no line.

    Every reader takes its lines through `criterion_lines` and hands each one
    here, so the host and a Docker or SSH terminal read them the same way.
    A trailing CR and a leading BOM are dropped; a line holding any other
    control or line-separator character is no criterion line. The line opens
    with ``CRITERION <id> #<token>: <status>`` (spaces, ``-``, ``*`` or
    backticks before it are fine), and after the status comes nothing or a
    separator (``-``, ``:``, an en or em dash) and the evidence. ``met``
    needs evidence with a letter or digit in it that is not one ``<...>``
    placeholder; a bare ``unmet`` or ``unobserved`` stands, since it can
    only hold the run back. Anything else after the status (``?``, ``(``,
    ``/``, ``|``, another word) makes it no criterion line.
    """
    line = line.removesuffix("\r").removeprefix("\ufeff")
    if any(char != "\t" and unicodedata.category(char) in ("Cc", "Zl", "Zp") for char in line):
        return None
    match = _CRITERION_LINE.match(line)
    criterion_id = match[1].lower() if match is not None else ""
    if match is None or criterion_id not in ids or not token or match[2].lower() != token:
        return None
    status, rest = match[3].casefold(), match[4]
    if not rest.strip(" \t"):
        return None if status == "met" else (criterion_id, status)
    separated = _CRITERION_EVIDENCE.fullmatch(rest)
    if separated is None:
        return None
    evidence = separated[1].strip()
    if status == "met" and (not any(char.isalnum() for char in evidence)
                            or (evidence.startswith("<") and evidence.endswith(">"))):
        return None
    return criterion_id, status


def criterion_statuses(lines: Iterable[str], ids: Sequence[str], token: str) -> dict[str, str]:
    """Each of ``ids`` as a verify node's handoff marks it for the attempt whose token is ``token``: ``met``,
    ``unmet`` or ``unobserved`` (`criterion_status` reads each line). The last line per id wins, and an id with no
    line, or only lines of another attempt, is ``unobserved``. Only the status word is kept, never the evidence text.
    """
    statuses = dict.fromkeys(ids, "unobserved")
    for line in lines:
        found = criterion_status(line, statuses, token)
        if found is not None:
            statuses[found[0]] = found[1]
    return statuses


def attempt_token(node: Mapping[str, Any]) -> str:
    """The token of the node's latest attempt, the ``#<token>`` its verify child writes on each criterion line;
    ``""`` when it has none (no attempt, or one stored without a token, which counts no line)."""
    attempts = node.get("attempts") or []
    token = attempts[-1].get("token") if attempts and isinstance(attempts[-1], Mapping) else None
    return token if isinstance(token, str) else ""


def wants_token(record: Mapping[str, Any], node: Mapping[str, Any]) -> bool:
    """Whether a new attempt of ``node`` carries a token: a verify node of a run with criteria, and nothing else, so
    a run without criteria keeps the record it always had."""
    return is_verification(node) and bool(run_criteria(record))


def leading_check_role(label: str) -> str:
    """``verify`` or ``review`` when a label's first word is a check word (Verify, Validate, Audit, QA, Review),
    else "". Narrower than `guessed_role`: "Add input validation" or "Fix review comments" names build work."""
    words = str(label).split()
    first = words[0].casefold().rstrip(":,.;-") if words else ""
    if _REVIEW_WORDS.match(first):
        return "review"
    return "verify" if _VERIFY_WORDS.match(first) else ""


def require_named_roles(raw_nodes: Sequence[Mapping[str, Any]]) -> None:
    """Refuse a node sent with no role that writes files and whose label opens with a check word (`role_required`).

    As a build node it would go to an external coding owner and be repaired
    rather than run again: a builder approving itself. The parent says which
    it is. Called on validated nodes, before anything is recorded.
    """
    for raw in raw_nodes:
        guess = "" if "role" in raw or not raw.get("write_scope") else leading_check_role(str(raw["label"]))
        if guess:
            raise DagRefusal("role_required",
                             f"Node {raw['id']} writes files and its label opens like a {guess} node: give it "
                             f"role={guess}, or role=build when it builds.")


def _require_graph(
    nodes: Sequence[Mapping[str, Any]], *, editable: Iterable[str] | None = None, involving: Iterable[str] = (),
    before: Mapping[str, Iterable[str]] | None = None,
) -> None:
    """The hard rejects over a whole graph: references, cycles, and write scopes shared without an edge.

    Scopes are compared as paths (`dag_core.shared_scope_pairs` ``as_paths``):
    ``./src/x.py`` is ``src/x.py``, ``src/`` holds it, and ``src/*.py`` matches
    it. One refusal names every overlapping pair in the check, and which node
    wrote which entry, so a directory entry is not refused one pair per round.

    ``editable`` limits the scope check to pairs of those nodes: a repair is
    checked against the nodes that can still run, not against finished ones.
    ``involving`` limits it further to pairs with one of those nodes in them:
    a repair or an extend round is checked against the run's earlier nodes,
    not the run against itself again (two earlier nodes are not the new
    nodes' to change). ``before`` adds orderings the scope check counts as
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
    scopes = {str(node["id"]): node["write_scope"] for node in nodes}
    ordered = {node: [*listed, *(before or {}).get(node, ())] for node, listed in parents.items()}
    overlaps = [
        f"{first} writes {', '.join(entry for entry in shared if entry in scopes[first])} and "
        f"{second} writes {', '.join(entry for entry in shared if entry in scopes[second])}"
        for first, second, shared, joined in dag_core.shared_scope_pairs(list(scopes.items()), ordered, as_paths=True)
        if not joined and first in checked and second in checked and (not new or first in new or second in new)
    ]
    if overlaps:
        raise DagRefusal(
            "write_scope_overlap",
            f"These nodes write overlapping paths with no edge between them: {'; '.join(overlaps[:OVERLAPS_NAMED])}"
            f"{f' and {len(overlaps) - OVERLAPS_NAMED} more pairs' if len(overlaps) > OVERLAPS_NAMED else ''}. "
            "Make one of each pair depend on the other, or split the scope.",
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


def lint(nodes: Sequence[Mapping[str, Any]], *, defining: bool = True) -> list[str]:
    """Advisory findings: they never reject a run, and the run records them.

    `no_judgement_node` is define-time only (``defining``): a repair or extend
    round cannot change the category of a node already settled.
    """
    findings: list[str] = []
    for node in nodes:
        missing = [marker for marker in PROMPT_MARKERS if not _MARKER_PATTERNS[marker].search(str(node["prompt"]))]
        if missing:
            findings.append(f"missing_markers:{node['id']}:{','.join(marker.replace(' ', '_') for marker in missing)}")
    if len(nodes) >= SERIAL_GRAPH_NODES:
        builds, chain = build_chain(nodes)
        if builds > 1 and chain >= SERIAL_GRAPH_SHARE * builds:
            findings.append(f"serial_graph:{builds} build nodes, {chain} of them in one chain; most of the build work "
                            "is one chain, so split it into parallel lanes where the work allows, or fold a small step "
                            "that only follows another into the node it follows.")
    findings += [f"role_guess:{node['id']}={node['role_guess']}" for node in nodes if node.get("role_guess")]
    verifiers = [node for node in nodes if is_verification(node)]
    if len(nodes) > 1 and not verifiers:
        findings.append("no_verification_node")
    # A role-less node guessed as review ("Review the diff") counts as the review here, and its guess is named above.
    if (len(nodes) > 1 and not any(node_role(node) == "review" or node.get("role_guess") == "review" for node in nodes)
            and any(node_role(node) == DEFAULT_ROLE and writes_code(node) for node in nodes)):
        findings.append("no_review_node")
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
    if defining and len(nodes) >= JUDGEMENT_GRAPH_NODES and not any(node["category"] in JUDGEMENT_CATEGORIES for node in nodes):
        findings.append("no_judgement_node")
    # Only a declared review: a guessed one (a role-less or stored node) is not asked to move. Verify nodes are left
    # alone: they judge the run goal, which can need a high category.
    findings += [f"review_not_review_category:{node['id']}" for node in nodes
                 if node.get("role") == "review" and node["category"] != "review"]
    return findings


def build_chain(nodes: Sequence[Mapping[str, Any]]) -> tuple[int, int]:
    """(how many build nodes the graph has, the most of them on one dependency path) for `serial_graph`.

    A path passes through baseline, review and verify nodes without counting them: they are serial by design, so a
    baseline before two builds that run side by side, and a review and a verify after them, is no chain of work.
    """
    ids = [str(node["id"]) for node in nodes]
    parents = {str(node["id"]): list(node["depends_on"]) for node in nodes}
    builds = {str(node["id"]) for node in nodes if node_role(node) == DEFAULT_ROLE}
    placed, _stuck = dag_core.layer_of(ids, parents)
    depth: dict[str, int] = {}
    for node_id in sorted(placed, key=lambda item: (placed[item], item)):
        depth[node_id] = int(node_id in builds) + max((depth[parent] for parent in parents[node_id] if parent in depth),
                                                      default=0)
    return len(builds), max(depth.values(), default=0)


def writes_code(node: Mapping[str, Any]) -> bool:
    """Whether a node's write scope may touch code (`no_review_node`): any entry that is not docs.

    An entry is docs when it ends in a docs suffix (``DOC_SUFFIXES``), sits
    under a ``docs`` directory anywhere in its path, or is named one of ``DOC_NAMES``
    (README, CHANGELOG, LICENSE, ...). Any other directory, glob or file
    counts as code. Advice only, so it errs toward naming the missing review.
    """
    return not all(_is_docs_entry(str(entry)) for entry in node["write_scope"])


def _is_docs_entry(entry: str) -> bool:
    """Docs: a docs suffix or name, or a ``docs`` directory anywhere in the path (``/repo/docs/``, ``../wt/docs/x``).
    An entry ending in ``/`` is all directories, and so is a bare ``docs``; otherwise its last segment is the file, so
    ``src/docs`` is code."""
    segments = [segment for segment in entry.casefold().split("/") if segment not in ("", ".")]
    if not segments:
        return False
    directories = segments if entry.endswith("/") or segments == ["docs"] else segments[:-1]
    return (posixpath.splitext(segments[-1])[1] in DOC_SUFFIXES or "docs" in directories
            or segments[-1] in DOC_NAMES)


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
    """A node an external coding owner may take: a build node that writes files.

    Baselines, verification and review stay native whoever builds: the builder never approves itself. So does a build
    node defined with no role whose label reads like another role (``role_guess``, as in "Re-verify the fix" or
    "independent verification vs baseline"): it is not refused, since "Add input validation" reads the same way,
    but it never leaves for an external owner. A node the parent named ``build`` carries no guess and goes.
    """
    return bool(node["write_scope"]) and node_role(node) == DEFAULT_ROLE and not node.get("role_guess")


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


def definition_digest(nodes: Sequence[Mapping[str, Any]], criteria: Sequence[Mapping[str, str]] = ()) -> str:
    # A build role is left out, so a run stored before nodes carried a role, defined again unchanged, is the same run.
    shape: object = [{key: node[key] for key in sorted(NODE_FIELDS)
                      if key in node and (key != "role" or node[key] != DEFAULT_ROLE)}
                     for node in nodes]
    if criteria:
        # Criteria are part of what a run is; a run defined without them keeps the digest it had before they existed.
        shape = {"criteria": [dict(item) for item in criteria], "nodes": shape}
    return hashlib.sha256(json.dumps(shape, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def new_record(session_id: str, run: str, name: object, goal: object, raw_nodes: object, now: float, *,
               oneshot_limit: int | None = None, oneshot_spent: int = 0,
               named_roles: bool = True, criteria: object = None) -> dict[str, Any]:
    """A validated run record. ``oneshot_limit`` and ``oneshot_spent``: the one-shot child budget and the children
    this process already started against it; a graph over what is left is refused. ``named_roles=False`` leaves
    `require_named_roles` to the caller: `dag_tool` first checks whether the run already exists (a run stored
    before nodes carried a role, defined again unchanged, is the same run). ``criteria``: the goal's separately
    checkable outcomes (`_validated_criteria`); ``None`` keeps the record as it was before criteria existed."""
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
    if named_roles:
        require_named_roles(raw_nodes)
    require_prompt_markers(nodes)
    _require_graph(nodes)
    title = _plain(name, MAX_NAME_CHARS, "invalid_name", "The run needs a short name.") if name else run
    stated = _plain(goal, MAX_GOAL_CHARS, "invalid_goal", GOAL_REFUSED) if goal else ""
    # An empty list is no criteria: the run is as one defined without them.
    checks = _validated_criteria(criteria) if criteria is not None and criteria != [] else []
    record = {
        "schema_version": DAG_SCHEMA_VERSION,
        "session_id": session_id,
        "run": run,
        "name": title,
        "goal": stated,
        "digest": definition_digest(nodes, checks),
        "defined_at": now,
        "updated_at": now,
        "cancelled_at": None,
        "nodes": nodes,
        "repairs": {},
        "topology": topology(nodes),
        "lint": lint(nodes),
        "claim_boundary": DAG_CLAIM_BOUNDARY,
    }
    if checks:
        record["criteria"] = checks
    return record


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
            # A role-less writer guessed as verify ("Re-verify the fix") re-runs too, though it covers nothing, but only
            # after a group `repair` stamped ``reruns_root``: a group stored before that rule keeps the root repaired.
            reruns = any(nodes.get(member, {}).get("reruns_root") for member in latest)
            if not (is_verification(nodes[root]) or reruns):
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

    A run with criteria is ``verified`` only when, beside the conditions of
    `_checks_verdict`, every criterion is ``met`` in the last attempt of an accepted
    verify node whose handoff was read (the newest such node per criterion);
    otherwise it is ``unverified`` with ``criteria_unmet:<ids>`` and
    ``criteria_unobserved:<ids>`` beside the other reasons (`criteria_reasons`).
    ``verify_failed`` is unchanged, and so is a run without criteria.
    """
    verdict, reasons = _checks_verdict(record, derived)
    missing = criteria_reasons(record, derived) if verdict != "verify_failed" else []
    return ("unverified", [*reasons, *missing]) if missing else (verdict, reasons)


def _checks_verdict(record: Mapping[str, Any], derived: Mapping[str, Mapping[str, Any]]) -> tuple[str, list[str]]:
    """`goal_verdict` from the verify nodes' outcomes alone, criteria aside.

    ``verified``: every producer (`is_producer`; a repair node standing in
    for what it repairs) is an ancestor of a verify node that was accepted
    with its handoff checked, and every verify node passed. ``verify_failed``:
    a verify node is failed or blocked and no accepted re-run replaced it.
    Otherwise ``unverified``, with ``no_producers`` (no node wrote files and
    none checked anything), ``no_verification_node``, ``verification_open:<ids>``,
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
    built = any(is_producer(node) for node in live)
    if not checks:
        return "unverified", ["no_verification_node" if built else "no_producers"]
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
    # An unread verify node counts for nothing; it is named where it alone follows a producer, and in a run that
    # built nothing (only checks) while no verify node was read, so a later check that was read clears it.
    reasons += [f"handoff_not_checked:{node['id']}" for node in passed if handoff_unchecked(node) and (
                uncovered - set(verification_misses(record["nodes"], [*checked, node], skip=superseded))
                if built else not checked)]
    return ("unverified", reasons) if reasons else ("verified", [])


def _criterion_reads(record: Mapping[str, Any], derived: Mapping[str, Mapping[str, Any]], *,
                     accepted_only: bool) -> dict[str, str]:
    """Each criterion's status as the newest verify read naming it says (by ``settled_at``, then record order).

    Only each verify node's last attempt counts, and only when it recorded a
    read: an earlier attempt's read is never shown or counted, and a last
    attempt whose handoff was not read leaves its criteria to other nodes.
    ``accepted_only``: accepted verify nodes whose handoff was read, as the
    verdict counts them; otherwise any outcome, as the views show them, so a
    failed or blocked check still gives its count. A criterion no read names
    is left out.
    """
    ids = [item["id"] for item in run_criteria(record)]
    reads: list[tuple[float, int, Mapping[str, Any]]] = []
    for order, node in enumerate(record["nodes"]):
        node_id = str(node["id"])
        if not is_verification(node) or derived[node_id]["state"] == "superseded":
            continue
        if accepted_only and (derived[node_id]["state"] != "accepted" or handoff_unchecked(node)):
            continue
        last = (node.get("attempts") or [None])[-1]
        if isinstance(last, Mapping) and isinstance(last.get("criteria"), Mapping):
            reads.append((_number(last.get("settled_at")) or 0.0, order, last["criteria"]))
    found: dict[str, str] = {}
    for _settled, _order, statuses in sorted(reads, key=lambda read: (read[0], read[1])):
        found.update({key: str(statuses[key]) for key in ids if statuses.get(key) in CRITERION_STATUSES})
    return found


def criteria_reasons(record: Mapping[str, Any], derived: Mapping[str, Mapping[str, Any]]) -> list[str]:
    """``criteria_unmet:<ids>`` and ``criteria_unobserved:<ids>`` for the criteria no accepted, read verify node
    marked ``met``; ``[]`` when each one is met, or the run has none."""
    ids = [item["id"] for item in run_criteria(record)]
    found = _criterion_reads(record, derived, accepted_only=True)
    unmet = [key for key in ids if found.get(key) == "unmet"]
    unseen = [key for key in ids if found.get(key) not in ("met", "unmet")]
    return ([f"criteria_unmet:{','.join(unmet)}"] if unmet else []) + (
        [f"criteria_unobserved:{','.join(unseen)}"] if unseen else [])


def criteria_view(record: Mapping[str, Any], derived: Mapping[str, Mapping[str, Any]]) -> dict[str, Any] | None:
    """The run's criteria as every view shows them, or ``None`` for a run without criteria: ``total``, ``met``,
    the ``unmet`` and ``unobserved`` ids, and each item's ``status`` as the newest verify read says it, or
    ``unchecked`` when no verify attempt was read yet. The verdict counts accepted reads only (`criteria_reasons`)."""
    criteria = run_criteria(record)
    if not criteria:
        return None
    found = _criterion_reads(record, derived, accepted_only=False)
    items = [{"id": item["id"], "text": item["text"], "status": found.get(item["id"], "unchecked")}
             for item in criteria]
    return {
        "total": len(items),
        "met": sum(1 for item in items if item["status"] == "met"),
        "unmet": [item["id"] for item in items if item["status"] == "unmet"],
        "unobserved": [item["id"] for item in items if item["status"] == "unobserved"],
        "items": items,
    }


def criteria_count(view: Mapping[str, Any]) -> str:
    """``2/3 criteria met``: what the status line, the done say and the run's end views add for a run with criteria."""
    return f"{view['met']}/{view['total']} criteria met"


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
    view = criteria_view(record, derived)
    if view is not None:
        parts.append(criteria_count(view))
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


def running_children(record: Mapping[str, Any], derived: Mapping[str, Mapping[str, Any]],
                     now: float) -> list[dict[str, Any]]:
    """Nodes with a live child: id, label, subagent id and seconds open, in record order.

    Cancel names these so the parent can stop each one instead of losing track
    of it: a cancelled record never settles them, and their results land in no
    handoff the run reads.
    """
    ages = open_for(record, derived, now)
    rows = []
    for node in record["nodes"]:
        node_id = str(node["id"])
        if derived[node_id]["state"] != "running":
            continue
        child = derived[node_id].get("child") or {}
        if not isinstance(child, Mapping) or isinstance(child.get("stop"), Mapping):
            continue
        subagent = child.get("subagent_id")
        if not subagent:
            continue
        rows.append({"id": node_id, "label": str(node["label"]), "subagent_id": str(subagent),
                     "open_for_s": int(ages.get(node_id, 0.0))})
    return rows


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


def hand_out(node: dict[str, Any], derived_state: str, now: float, *, lost: bool = False,
             token: bool = False) -> dict[str, Any]:
    """Write-ahead: the attempt exists before its goal leaves this tool, so a marker always finds it.

    ``lost``: the attempt is offered again because a restart ended its child, which the attempt counts.
    ``token`` (`wants_token`): a new attempt gets a random token its criterion lines must carry, so no line written
    for another attempt, earlier or later, counts for it. Offering the same attempt again keeps its token.
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
    if token:
        attempt["token"] = secrets.token_hex(ATTEMPT_TOKEN_BYTES)
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


def _fit(items: Sequence[str], limit: int, sep: str) -> tuple[list[str], int]:
    """The leading ``items`` whose ``sep`` join fits ``limit`` (the first always), and how many were left out."""
    shown = list(items[:1])
    for item in items[1:]:
        if len(sep.join([*shown, item])) > limit:
            break
        shown.append(item)
    return shown, len(items) - len(shown)


def _producer_scopes(record: Mapping[str, Any], node: Mapping[str, Any], preceding: set[str]) -> str:
    """``id: path, path; ...`` for the producers a verify node follows (and their repairs, and its own), cut at
    `SCOPE_MAP_CHARS` on whole paths and producers. Attribution by declared scope only: no write is observed."""
    holders = preceding | {str(node["id"])}
    rows = []
    for item in record["nodes"]:
        if is_producer(item) and (str(item["id"]) in preceding or item.get("repairs") in holders):
            paths, left = _fit(item["write_scope"], SCOPE_MAP_CHARS, ", ")
            rows.append(f"{item['id']}: {', '.join(paths)}" + (f" (+{left} more paths)" if left else ""))
    shown, left = _fit(rows, SCOPE_MAP_CHARS, "; ")
    return "; ".join(shown) + (f"; (+{left} more producers)" if left else "")


def _leftovers_line(record: Mapping[str, Any], node: Mapping[str, Any]) -> str:
    """A repair that writes starts from what earlier attempts left on disk (no rollback: the worktree is shared)."""
    root = _root(node)
    earlier = {root}
    for group in (record.get("repairs") or {}).get(root, [])[:max(0, int(node.get("cycle") or 1) - 1)]:
        earlier.update(group)
    paths = sorted({path for item in record["nodes"] if str(item["id"]) in earlier for path in item["write_scope"]})
    # `shlex.quote` is POSIX shell quoting; a Windows shell reads those quotes differently.
    shown, left = _fit([shlex.quote(path) for path in paths or node["write_scope"]], LEFTOVER_PATHS_CHARS, " ")
    more = f" (+{left} more paths)" if left else ""
    check = (f"if this is a git checkout, inspect `git status --short -- {' '.join(shown)}`{more} and "
             "`git diff HEAD` on the same paths")
    if not paths:  # the failed root declared no scope (a verify node): earlier nodes' edits sit in this one's
        return (f"Files in your SCOPE may already carry earlier nodes' edits: {check} before editing; keep what is "
                "right, undo what is wrong in your SCOPE.")
    return (f"The failed attempt's edits may still be on disk: {check} (or the files its handoff reported) before "
            "editing; keep what is right, undo what is wrong in your SCOPE.")


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
    if node.get("cycle") == REPLAN_CYCLE:
        root = _root(node)
        earlier = {root}
        for group in (record.get("repairs") or {}).get(root, [])[:REPLAN_CYCLE - 1]:
            earlier.update(group)
        failures = [
            (str(item["id"]), attempt)
            for item in record["nodes"] if str(item["id"]) in earlier
            for attempt in item.get("attempts") or [] if attempt.get("outcome") in ("failed", "blocked")
        ]
        failures.sort(key=lambda row: _number(row[1].get("settled_at")) or 0.0)
        recent = [
            (f"{attempt['outcome']} {node_id} attempt {attempt.get('n', 1)}: ",
             " ".join(str(attempt.get("reason") or "").split()),
             " (provider error)" if attempt.get("provider_error") else "")
            for node_id, attempt in failures[-6:]
        ]
        intro = f"Re-plan: last repair cycle for {root}. Earlier failures (newest last):"
        guidance = (
            "Do not retry the same approach; before editing, write two or three approaches that differ in kind "
            "into the handoff, rule out what the failures refute, and take the one that remains. "
            "Read earlier handoffs (<node id>.md beside your handoff) for evidence (test ids, errors, measurements), "
            "not for their plan. If every listed failure is an infrastructure cut (provider error, interrupted child), "
            "retrying the same approach is right; say so in the handoff."
        )
        # Keep all six identities and provider flags; share the remaining space between settle reasons.
        reason_limit = max(0, (1180 - len(intro) - len(guidance)
                              - sum(len(prefix) + len(flag) + 1 for prefix, _, flag in recent)) // max(1, len(recent)))
        evidence = [prefix + (reason if len(reason) <= reason_limit else reason[:max(0, reason_limit - 1)] + "…") + flag
                    for prefix, reason, flag in recent]
        lines.extend([intro, *evidence, guidance, ""])
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
        criteria = run_criteria(record)
        if criteria:
            # The engine reads these lines from the handoff (`criterion_statuses`); a criterion without one is unobserved.
            token = attempt_token(node)
            lines.extend([
                "Goal criteria:",
                *(f"- {item['id']}: {item['text']}" for item in criteria),
                "In the handoff, write one line per criterion, each at the start of a line, with one status word:",
                f"CRITERION <id> #{token}: met | unmet | unobserved - <the command you ran and what it showed>",
                f"`#{token}` is this attempt's mark: a line without it, or with another, does not count. `met` needs "
                "that evidence after the dash. `unmet` means you ran the check and the outcome is not there; "
                "`unobserved` means the check could not run here, and the reason says why. Every criterion gets a "
                "line; one without a line counts as unobserved.",
            ])
        scopes = _producer_scopes(record, node, preceding)
        if scopes:
            lines.append("In the handoff, name for each failing check the producer whose declared write_scope holds "
                         f"its failing path, or `unattributed`: by declared scope, not proven cause. Scopes: {scopes}")
    if node.get("repairs") and node["write_scope"]:
        lines.append(_leftovers_line(record, node))
    lines.append("Stay inside your SCOPE: other parts of this run work at the same time. If you cannot finish, "
                 "say plainly that you are blocked and why; do not report blocked work as done.")
    # The marker ends the goal: Hermes previews each goal by its first 40 characters, and a person reads the label
    # there. It stays on the label's line, since Hermes prints `goal[:40]` as a one-line completion label.
    return {"goal": f"{node['label']} [dag:{run}/{node['id']}]", "context": "\n".join(lines)}


def retry_count(node: Mapping[str, Any]) -> int:
    """How many of the node's attempts ended in a provider-error retry: the index of its next model_map option."""
    return sum(1 for item in node.get("attempts") or [] if item.get("outcome") == "retry")


def local_blocked(record: Mapping[str, Any], offered: Iterable[str], backend: Mapping[str, Any] | None) -> list[str]:
    """Offered nodes marked ``local`` that no local model can take now; they are held, never sent to another model.

    A local node runs only on a local option of Hermes' `model_map` backend
    (`category_local_options`), one per provider-error retry. Under any other
    backend, an unreadable one, or with every local option tried, OMH cannot
    tell where a child would run, so the node waits for the person.
    """
    nodes = {str(node["id"]): node for node in record["nodes"]}
    local_options = (backend or {}).get("local_options") or {}
    readable = str((backend or {}).get("backend") or "") == "model_map" and (backend or {}).get("status") == "read"
    blocked = []
    for node_id in offered:
        node = nodes[node_id]
        if not node.get("local"):
            continue
        names = list(local_options.get(str(node["category"])) or []) if readable else []
        if retry_count(node) >= len(names):
            blocked.append(node_id)
    return blocked


def _call_route(
    category: str, fallback: bool, retries: int, backend: Mapping[str, Any] | None, local: bool = False
) -> tuple[dict[str, Any], str]:
    """The call's ``route`` and the model_map option its tasks carry (``""`` for none).

    Under `default` (or an unread backend: ``None``) the parent sets the
    route with `omh_delegate_route` as before. Under `model_map` the option
    goes on each task and no tool runs: a provider-error retry takes the
    category's next option. Any other backend gets nothing from OMH -- it
    never picks a `profile_routes` profile. A ``local`` call takes the
    category's local options only; `local_blocked` keeps a local node that
    has none out of every call.
    """
    name = str((backend or {}).get("backend") or "default")
    if name == "default":
        return {"tool": "omh_delegate_route", "action": "fallback" if fallback else "set", "category": category}, ""
    route: dict[str, Any] = {"backend": name, "category": category}
    if local:
        route["local"] = True
    if name != "model_map" or (backend or {}).get("status") != "read":
        route["status"] = "not_applied"
        return route, ""
    names = list(((backend or {}).get("local_options" if local else "options") or {}).get(category) or [])
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
    skipped = set(skip)
    # Under model_map the option is the retry count's: nodes on different retries go in different calls.
    by_option = str((backend or {}).get("backend") or "") == "model_map"
    # A local node no local model can take is never handed out, whatever the caller skips.
    skipped |= set(local_blocked(record, offerable(record, derived, now, limits=limits), backend))
    groups: dict[tuple[str, bool, int, bool], list[str]] = {}
    for node_id in offerable(record, derived, now, limits=limits):
        if node_id in skipped:
            continue
        node = nodes[node_id]
        attempts = node.get("attempts") or []
        fallback = bool(attempts) and attempts[-1].get("outcome") == "retry"
        retries = retry_count(node) if by_option else 0
        groups.setdefault((str(node["category"]), fallback, retries, bool(node.get("local"))), []).append(node_id)
    calls: list[dict[str, Any]] = []
    held: list[str] = []
    size = max(1, per_call)
    left = None if task_budget is None else max(0, task_budget)
    for (category, fallback, retries, local), members in groups.items():
        route, option = _call_route(category, fallback, retries, backend, local)
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
                                   lost=bool(derived[node_id].get("lost")), token=wants_token(record, nodes[node_id]))
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
    read_criteria: Callable[[], tuple[bool, str, list[str]]] | None = None,
) -> str:
    """Close the node's open attempt. Returns what happened: the outcome, or ``retry`` (a provider error's one retry).

    ``read_handoff`` answers (found, unread) and is called only for an
    ``accepted`` settle that every other check let through, so a settle
    refused for another reason reads nothing. ``unread`` names why the
    handoff could not be read where the child wrote it
    (`dag_tool.backend_handoff`): ``accepted`` then stands, and the attempt
    records ``handoff_checked: false`` with that reason.

    A verify node of a run with criteria is read with ``read_criteria``
    instead, which also answers the handoff's ``CRITERION`` lines, on an
    accepted, failed or blocked settle (not a provider error's retry). A
    handoff that was read records each criterion's status on the attempt
    (`criterion_statuses`); an ``accepted`` settle with one ``unmet`` is
    refused as ``criteria_unmet``, and with one ``unobserved`` as
    ``criteria_unobserved``. A missing handoff still refuses only
    ``accepted``, and an unread one records no statuses.
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
    retries = sum(1 for item in nodes[node_id]["attempts"] if item.get("outcome") == "retry")
    retrying = outcome == "failed" and bool(provider_error) and retries < MAX_PROVIDER_RETRIES
    ids = ([item["id"] for item in run_criteria(record)]
           if is_verification(nodes[node_id]) and outcome in ("accepted", "failed", "blocked") and not retrying else [])
    unread = ""
    statuses: dict[str, str] | None = None
    if outcome == "accepted" or ids:
        lines: list[str] = []
        if ids and read_criteria is not None:
            found, unread, lines = read_criteria()
        else:
            found, unread = read_handoff()
        if outcome == "accepted" and not found and not unread:
            raise DagRefusal(
                "handoff_missing",
                f"Node {node_id} has no handoff file, and the nodes after it read one. Write it from the child's "
                "result, or settle the node failed.",
            )
        if outcome == "accepted" and unread == HANDOFF_UNREADABLE:
            raise DagRefusal(
                HANDOFF_UNREADABLE,
                f"Node {node_id}'s handoff file is there but could not be opened as a plain file, so its criteria "
                "cannot be read. Fix the file (its permissions, or what replaced it) and settle again, or settle "
                "the node failed or blocked.",
            )
        if ids and found and not unread:
            statuses = criterion_statuses(lines, ids, attempt_token(nodes[node_id]))
    if outcome == "accepted" and statuses is not None:
        unmet = [key for key in ids if statuses[key] == "unmet"]
        unseen = [key for key in ids if statuses[key] == "unobserved"]
        again = _checked_again(nodes, nodes[node_id])
        if unmet:
            raise DagRefusal(
                "criteria_unmet",
                f"Node {node_id}'s handoff marks criteria {', '.join(unmet)} unmet, so it is not accepted. Settle it "
                f"failed, then repair it with nodes that fix the work; {again}.",
            )
        if unseen:
            raise DagRefusal(
                "criteria_unobserved",
                f"Node {node_id}'s handoff has no checked result of this attempt for criteria {', '.join(unseen)} (no "
                f"CRITERION line marked #{attempt_token(nodes[node_id])}, or met with no evidence), so it is not "
                f"accepted. Settle it failed and repair it so they are checked ({again}), or settle it blocked when "
                "they cannot be checked here.",
            )
    attempt = nodes[node_id]["attempts"][-1]
    note = _plain(reason, MAX_REASON_CHARS, "invalid_reason", "The reason is one short line.") if reason else ""
    attempt.update(settled_at=now, reason=note, provider_error=bool(provider_error))
    if retrying:
        attempt["outcome"] = "retry"
        return "retry"
    attempt["outcome"] = outcome
    if outcome == "parked":
        attempt.update(handle=handle, wake_at=wake_at)
    if outcome == "accepted" and unread:
        attempt.update(handoff_checked=False, handoff_unread=unread)
    if statuses is not None:
        attempt["criteria"] = statuses  # the status words only: no evidence text, no handoff content
    return str(outcome)


def _checked_again(nodes: Mapping[str, Mapping[str, Any]], node: Mapping[str, Any]) -> str:
    """What runs the check again once a failed verify node's repair group passes, as `derive` decides it."""
    root = str(node.get("repairs") or "")
    if not root:
        return "this check runs again once they pass"
    if root in nodes and (is_verification(nodes[root]) or nodes[root].get("role_guess") == "verify"):
        return f"{root} runs again once they pass"
    parents = {key: item["depends_on"] for key, item in nodes.items()}
    later = sorted(key for key, item in nodes.items()
                   if is_verification(item) and item is not node and root in ancestors(key, parents))
    if later:
        return (f"this node is part of {root}'s repair group and does not run again; {', '.join(later)} "
                f"{'checks' if len(later) == 1 else 'check'} the work once they pass")
    return (f"this node is part of {root}'s repair group and does not run again, so put a role=verify node in the "
            "new group to check the work")


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
    require_named_roles(raw_nodes)
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
        if nodes[root].get("role_guess") == "verify":
            node["reruns_root"] = True  # `derive` runs the root again once this group is accepted; not in the digest
    runnable = {key for key, info in derived.items() if info["state"] in LIVE | {"ready", "waiting", "held"}}
    # The group runs before every node that waits on the root (they wait on the root, the root on the group), so a
    # dependent writing what the group writes is ordered, not an overlap.
    every = {str(node["id"]): node["depends_on"] for node in record["nodes"]}
    below = {key: sorted(group) for key in every if root in ancestors(key, every)}
    _require_graph(list(record["nodes"]) + added, editable=group | runnable, involving=group, before=below)
    _require_oneshot_room(added, oneshot_remaining, "repair")
    record["nodes"].extend(added)
    groups.append([str(node["id"]) for node in added])
    record["topology"] = topology(record["nodes"])
    record["lint"] = lint(record["nodes"], defining=False)
    record["updated_at"] = now
    return [str(node["id"]) for node in added]


def extend_rounds_left(record: Mapping[str, Any]) -> int:
    return MAX_EXTEND_ROUNDS - len(record.get("extends") or [])


def extend(
    record: dict[str, Any], derived: Mapping[str, Mapping[str, Any]], raw_nodes: object, found_by: object, now: float,
    *, oneshot_remaining: int | None = None, criteria: object = None,
) -> list[str]:
    """Add a round of nodes to a run whose every node passed but whose goal check found work missing.

    ``criteria`` adds goal criteria the run does not have yet (new ids only,
    `MAX_CRITERIA` in all); nothing rewrites or removes one.

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
    require_named_roles(raw_nodes)
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
    more = (_validated_criteria(criteria, [item["id"] for item in run_criteria(record)])
            if criteria is not None and criteria != [] else [])
    record["nodes"].extend(added)
    rounds.append([str(node["id"]) for node in added])
    if more:
        record["criteria"] = [*run_criteria(record), *more]
    record["topology"] = topology(record["nodes"])
    record["lint"] = lint(record["nodes"], defining=False)
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
