"""Refuse a model file write into the stores OMH's own hooks and commands keep.

A delegation ledger, a dag-ulw run record, a decision gate, a research fetch
receipt or a plan todo is evidence because OMH's code wrote it from what the
host reported: `post_tool_call` writes a receipt for a URL Hermes' web tool
really opened, `subagent_start` writes a ledger row for a child Hermes really
spawned. A line the model writes into the same file with `write_file` or
`patch` is byte-for-byte indistinguishable from one of those, so a forged
`fetched` receipt passes `omh research receipts verify` and a forged child
row reads as a dispatch that happened.

`pre_tool_call` therefore blocks `write_file` and `patch` (every file a V4A
patch names) whose target resolves under one of the stores below inside this
profile's OMH home. OMH writes them in Python, never through a tool call, so
the block costs OMH nothing. The one file a model is meant to write there is a
dag-ulw node's handoff report, ``runtime/dag/<key>/<run>/<node>.md``
(`dag_run.handoff_path`), and it passes.

Scope, stated plainly: this covers Hermes' two structured file tools. A shell
command (`terminal`, `execute_code`) that appends to the same file is not
judged, because a command string does not say which files it writes. This
stops an accidental or naive forgery, not a determined one.

Never raises. A target this module cannot resolve passes, and the miss is
logged once per process at WARNING, the same fail-open shape as the other
`pre_tool_call` gates: a hook exception would skip every gate after it.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from typing import Final

from .consistency_trigger import _edit_targets
from .tools.lsp_nav_tool import _workspace_root

FILE_WRITE_TOOLS: Final = frozenset({"write_file", "patch"})

# Under ``<omh_home>/runtime``: a directory (trailing ``/``) or one file.
EVIDENCE_STORES: Final[Mapping[str, str]] = {
    "journal/": "the runtime journal (decision gates, events, blocked work)",
    "delegation/": "the delegation ledger",
    "dag/": "dag-ulw run records",
    "research_receipts/": "research fetch receipts",
    "runs/": "runtime run records",
    "todos/": "session plan todos",
    "todo.json": "the home-wide plan todo",
}

_HANDOFF_SUFFIX: Final = ".md"
_LOG = logging.getLogger("omh.evidence_store_guard")
_warned = False


def evidence_write_directive(
    *, tool_name: object, tool_input: object, task_id: object, omh_home: str
) -> dict[str, str] | None:
    """A `block` naming the store, when this write lands in OMH evidence; else None."""
    if str(tool_name or "") not in FILE_WRITE_TOOLS or not isinstance(tool_input, dict) or not omh_home:
        return None
    try:
        runtime_root = _comparable(os.path.join(os.path.expanduser(omh_home), "runtime"))
        base = _workspace_root(task_id) or os.getcwd()
        for requested in _edit_targets(str(tool_name), tool_input):
            store = _store_for(_comparable(os.path.join(base, os.path.expanduser(requested))), runtime_root)
            if store:
                return {"action": "block", "message": evidence_write_message(requested, store)}
    except (OSError, ValueError, TypeError) as exc:
        _warn_once(exc)
    return None


def evidence_write_message(requested: str, store: str) -> str:
    return (
        f"OMH blocked this write: {requested!r} is in {EVIDENCE_STORES[store]}, which only OMH's own hooks "
        "and commands write. A record written by a tool call cannot be told apart from one OMH observed, "
        "so it would read as evidence of something that did not happen. Do not retry this write or route it "
        "through the shell; use the omh command that owns this record, or write your file somewhere else."
    )


def _store_for(target: str, runtime_root: str) -> str:
    if not target.startswith(runtime_root + os.sep):
        return ""
    parts = target[len(runtime_root) + 1:].split(os.sep)
    if len(parts) == 4 and parts[0] == "dag" and parts[3].endswith(_HANDOFF_SUFFIX):
        return ""
    relative = "/".join(parts)
    for store in EVIDENCE_STORES:
        if relative == store.rstrip("/") or (store.endswith("/") and relative.startswith(store)):
            return store
    return ""


def _comparable(path: str) -> str:
    # realpath settles `..`, `~` already expanded, and every symlink on the way; casefold because the
    # default macOS and Windows filesystems treat `Runtime/Journal` and `runtime/journal` as one file.
    return os.path.normcase(os.path.realpath(path)).casefold()


def _warn_once(exc: BaseException) -> None:
    global _warned
    if not _warned:
        _warned = True
        _LOG.warning("evidence store guard could not resolve a write target (%s); the write was allowed",
                     type(exc).__name__)
