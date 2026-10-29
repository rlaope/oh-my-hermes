"""Composed ``transform_tool_result`` seam, and the ``transform_llm_output``
half of unarmed remote waits.

This is the single registered entry for the hook; it chains the seven OMH
result transforms in a fixed order:

1. Code-mode discipline annotation — the first ``execute_code`` result of a
   session gains a bounded guidance block under its own JSON key
   (``code_mode_guidance.py``).
2. Engagement nudges — a session that has changed several files without
   declaring a plan, or searched repeatedly without routing a lane, gets a
   bounded, budgeted, self-latching nudge (``engagement_nudges.py``).
3. Truncated-read recovery — a ``read_file`` refusal or ``unchanged`` stub for
   a path whose earlier read was cut short gains a bounded note naming the
   lines that WERE returned and the offset that continues past them, because
   the host's refusal asserts the model already has content no read ever
   returned (``truncated_read_recovery.py``).
4. Read outline — a truncated ``read_file`` result of a large Python file gains
   one key holding the whole file's classes, functions and methods with their
   line ranges, so the model can jump to an offset instead of paging
   (``read_outline.py``). Spliced in, never cut; once per file version per
   session.
5. Kanban readback bounding — a ``kanban_show`` / ``kanban_list`` /
   ``kanban_attachments`` result is cut to a field and payload ceiling and
   prefixed with one evidence-vocabulary label line, so a worker's unbounded
   completion summary cannot flood the main session and a self-reported
   ``completed`` never reads as verified (``kanban_readback.py``).
6. Unarmed remote waits — a ``terminal`` call that starts work on a remote
   with no background process armed to wake the session, or one blocked at
   the human approval gate, gets a per-turn directive naming the two honest
   exits (``remote_wait_nudge.py``).
7. Full-width diff band padding — tool-result diffs get their painted lines
   padded to a uniform band (``diff_presentation.py``), except Kanban readback
   tools: their serialized records must retain the bound and valid JSON even
   when a string contains Unicode line separators and diff-looking text.

Every transform is fail-open: anything one declines passes through to the
next, and ``None`` from all of them leaves the host result untouched. Order
matters when one result matches more than one pass, which happens two ways.

**An annotating pass and the diff pass** (an execute_code result whose output
embeds a diff): the annotating passes run first so the diff pass still sees
and pads the final string.

**Two annotating passes.** Their tool sets are NOT disjoint: engagement nudges
watch ``read_file`` among their direct-read tools, and truncated-read recovery
watches ``read_file`` alone, so one refused re-read can match both and leave
with both keys. They compose rather than collide because each pass parses the
string it is HANDED and re-serialises it, and each writes a key no other pass
writes (``omh_guidance``, ``omh_engagement``, ``omh_truncated_read``,
``omh_readback``). In this order the nudge lands first, so the recovery pass
parses the already-nudged object and adds its key beside the nudge; neither
reads the other's key, so swapping the two would produce the same two keys in
the other insertion order. The composed case is pinned in
``tests/test_truncated_read_recovery.py``. The read outline also watches
``read_file`` and writes ``omh_read_outline``, but only on a successful
truncated read, which is never one of the refusal shapes recovery annotates;
it can follow a nudge on the same result, and it splices its key in before
the closing brace rather than re-serialising, so the nudged bytes stay as they
were (pinned in ``tests/test_read_outline.py``). Code-mode guidance still cannot
meet either of them: it watches ``execute_code`` and nothing else, and
neither can unarmed remote waits, which watches ``terminal`` and nothing
else and writes ``omh_remote_wait``. ``read_file`` is the only tool
annotating passes share; the full picture is ``execute_code`` for code-mode
guidance, ``{write_file, patch}`` plus ``{read_file, search_files,
web_search, web_extract}`` plus the delegation tools for engagement nudges,
``read_file`` for truncated-read recovery and the read outline, the ``kanban_*`` readback tools
for kanban bounding, and ``terminal`` for unarmed remote waits. Engagement
nudges deliberately do NOT watch ``terminal``, so no result reaches both of
those. ``tests/test_remote_wait_nudge.py`` derives those sets from the
modules and pins the disjointness, so a pass that later widens into
``terminal`` fails there rather than silently sharing a result.

**Why unarmed remote waits runs last of the annotating passes.** It is the
pass which reads terminal-specific outcome fields: ``exit_code`` to know the
command succeeded, ``status`` /
``approval_pending`` for the gate, and ``session_id`` to recognise a
background spawn. Being disjoint from the others it always sees the host's
own object anyway, and running it immediately before the diff pass states
that ordering as an invariant rather than an accident: every pass that reads
host fields runs before the one that reformats text.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from ..code_mode_guidance import annotate_execute_code_result
from ..delegation_snapshot import appended, messenger_snapshot
from ..engagement_nudges import annotate_engagement_nudge
from ..kanban_readback import KANBAN_READBACK_TOOLS, transform_kanban_readback
from ..read_outline import annotate_read_outline
from ..remote_wait_nudge import annotate_remote_wait, honest_stop_output
from ..truncated_read_recovery import annotate_truncated_read_recovery
from .diff_presentation import transform_tool_result as _pad_diff_result

# Failures of the delegation snapshot by exception type; a block that failed is a reply without one.
snapshot_failures: Counter[str] = Counter()


def transform_tool_result(**kwargs: Any) -> str | None:
    """Return the transformed result string, or ``None`` to leave it alone."""
    session_id = str(kwargs.get("session_id", "") or "")
    annotated = annotate_execute_code_result(
        tool_name=kwargs.get("tool_name"),
        result=kwargs.get("result"),
        session_id=session_id,
    )
    if annotated is not None:
        kwargs = {**kwargs, "result": annotated}
    nudged = annotate_engagement_nudge(
        tool_name=kwargs.get("tool_name"),
        result=kwargs.get("result"),
        # The same arguments the recovery pass below reads, and the host
        # passes them here already coerced to the tool's schema types
        # (`model_tools.handle_function_call` runs `coerce_tool_args` before
        # dispatch), so two calls that are the same call digest the same. The
        # delegation nudge counts DISTINCT searches, and this is the only
        # thing at this seam that can tell one search twice from two (#1701).
        args=kwargs.get("args"),
        tool_call_id=kwargs.get("tool_call_id") or "",
        turn_id=kwargs.get("turn_id") or "",
        status=str(kwargs.get("status") or ""),
        session_id=session_id,
        # The host passes this seam the identity fields, the result, and the
        # timing — no home (`model_tools._apply_transform_tool_result_hook`).
        # The observer resolves both via runtime_paths, so native profile
        # scope (not a cached launch home) owns its counters and plan reads.
        omh_home=str(kwargs.get("omh_home", "") or ""),
        hermes_home=str(kwargs.get("hermes_home", "") or ""),
    )
    if nudged is not None:
        annotated = nudged
        kwargs = {**kwargs, "result": nudged}
    recovered = annotate_truncated_read_recovery(
        tool_name=kwargs.get("tool_name"),
        # The host passes this seam the call's arguments, already coerced to
        # the tool's schema types (`model_tools.handle_function_call` runs
        # `coerce_tool_args` before dispatch). This pass needs them for the
        # path it keys on and the offset the call asked for.
        args=kwargs.get("args"),
        result=kwargs.get("result"),
        session_id=session_id,
        # The catch it records for the person resolves the home the way the
        # nudge above does: the host passes none, so runtime_paths decides.
        omh_home=str(kwargs.get("omh_home", "") or ""),
    )
    if recovered is not None:
        annotated = recovered
        kwargs = {**kwargs, "result": recovered}
    outlined = annotate_read_outline(
        tool_name=kwargs.get("tool_name"),
        args=kwargs.get("args"),
        result=kwargs.get("result"),
        session_id=session_id,
        # The host's task identity (`model_tools._CallIds`): the path resolves
        # against that task's workspace, the way `read_file` resolved it.
        task_id=str(kwargs.get("task_id", "") or ""),
    )
    if outlined is not None:
        annotated = outlined
        kwargs = {**kwargs, "result": outlined}
    bounded = transform_kanban_readback(kwargs.get("tool_name"), kwargs.get("result"))
    if bounded is not None:
        annotated = bounded
        kwargs = {**kwargs, "result": bounded}
    waited = annotate_remote_wait(
        tool_name=kwargs.get("tool_name"),
        args=kwargs.get("args"),
        result=kwargs.get("result"),
        session_id=session_id,
        # The host's own turn identity, threaded through every tool hook by
        # `model_tools._CallIds.hook_kwargs`. It is this pass's only turn
        # boundary, which is why the directive declines without it.
        turn_id=str(kwargs.get("turn_id", "") or ""),
        hermes_home=str(kwargs.get("hermes_home", "") or ""),
        omh_home=str(kwargs.get("omh_home", "") or ""),
    )
    if waited is not None:
        annotated = waited
        kwargs = {**kwargs, "result": waited}
    # Board readbacks are serialized records, not presentation diffs. Python's
    # splitlines() also splits Unicode separators inside JSON strings; padding
    # that text could corrupt JSON and invalidate the final readback ceiling.
    # Apply the same exclusion on a second pass over an already-labelled result.
    if str(kwargs.get("tool_name") or "") in KANBAN_READBACK_TOOLS:
        return annotated
    padded = _pad_diff_result(**kwargs)
    if padded is not None:
        return padded
    return annotated


def transform_llm_output(**kwargs: Any) -> str | None:
    """The end-of-turn half of unarmed remote waits, then the delegation snapshot.

    Hermes fires this once per turn after the tool loop with ``response_text``,
    ``session_id``, ``model``, ``platform`` and ``turn_id``
    (`agent/turn_finalizer.py::_apply_output_hooks`); the first plugin to
    return a non-empty string wins, so both of OMH's end-of-turn passes are
    composed in this one handler. The honest stop (``remote_wait_nudge.py``)
    reads the latch its tool-result half records. The delegation snapshot
    (``delegation_snapshot.py``) appends, on a chat platform, a delegated
    run's start block, a count line on a turn its counts changed, or its end
    block. Both append and neither rewrites: the CLI prints only the suffix
    of a transformed reply that starts with the streamed one
    (`cli.py::_post_stream_transform_output`). The host passes no home, so the
    process record resolves the way the tool-result half resolves it.
    """
    honest = honest_stop_output(
        response_text=kwargs.get("response_text"),
        session_id=kwargs.get("session_id"),
        turn_id=kwargs.get("turn_id"),
        hermes_home=str(kwargs.get("hermes_home", "") or ""),
    )
    reply = honest if honest is not None else kwargs.get("response_text")
    if not isinstance(reply, str) or not reply.strip():
        return honest
    post = _delegation_snapshot(kwargs, reply)
    return appended(reply, post) if post else honest


def _delegation_snapshot(kwargs: dict[str, Any], reply: str) -> str:
    """The delegation post for ``reply``, or "": a failure in it must not take the honest stop above down with it."""
    try:
        return messenger_snapshot(
            session_id=kwargs.get("session_id"), platform=kwargs.get("platform"), model=kwargs.get("model"),
            reply=reply,
        )
    except Exception as exc:  # noqa: BLE001 - the host swallows a raise from this hook, which would also
        # drop the honest stop composed beside it; recorded by type, and the reply goes out without a post.
        snapshot_failures[type(exc).__name__] += 1
        return ""
