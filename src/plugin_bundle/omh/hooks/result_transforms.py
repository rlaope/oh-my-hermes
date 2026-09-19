"""Composed ``transform_tool_result`` seam.

This is the single registered entry for the hook; it chains the six OMH
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
4. Kanban readback bounding — a ``kanban_show`` / ``kanban_list`` /
   ``kanban_attachments`` result is cut to a field and payload ceiling and
   prefixed with one evidence-vocabulary label line, so a worker's unbounded
   completion summary cannot flood the main session and a self-reported
   ``completed`` never reads as verified (``kanban_readback.py``).
5. Unarmed remote waits — a ``terminal`` call that starts work on a remote
   with no background process armed to wake the session, or one blocked at
   the human approval gate, gets a per-turn directive naming the two honest
   exits (``remote_wait_nudge.py``).
6. Full-width diff band padding — tool-result diffs get their painted lines
   padded to a uniform band (``diff_presentation.py``).

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
``tests/test_truncated_read_recovery.py``. Code-mode guidance still cannot
meet either of them: it watches ``execute_code`` and nothing else, and
neither can unarmed remote waits, which watches ``terminal`` and nothing
else and writes ``omh_remote_wait``. ``read_file`` is the only tool two
annotating passes share; the full picture is ``execute_code`` for code-mode
guidance, ``{write_file, patch}`` plus ``{read_file, search_files,
web_search, web_extract}`` plus the delegation tools for engagement nudges,
``read_file`` for truncated-read recovery, the ``kanban_*`` readback tools
for kanban bounding, and ``terminal`` for unarmed remote waits. Engagement
nudges deliberately do NOT watch ``terminal``, so no result reaches both of
those. ``tests/test_remote_wait_nudge.py`` derives those sets from the
modules and pins the disjointness, so a pass that later widens into
``terminal`` fails there rather than silently sharing a result.

**Why unarmed remote waits runs last of the annotating passes.** It is the
only one whose DECISION reads fields of the host's result rather than just
its tool name: ``exit_code`` to know the command succeeded, ``status`` /
``approval_pending`` for the gate, and ``session_id`` to recognise a
background spawn. Being disjoint from the others it always sees the host's
own object anyway, and running it immediately before the diff pass states
that ordering as an invariant rather than an accident: every pass that reads
host fields runs before the one that reformats text.
"""

from __future__ import annotations

from typing import Any

from ..code_mode_guidance import annotate_execute_code_result
from ..engagement_nudges import annotate_engagement_nudge
from ..kanban_readback import transform_kanban_readback
from ..remote_wait_nudge import annotate_remote_wait
from ..truncated_read_recovery import annotate_truncated_read_recovery
from .diff_presentation import transform_tool_result as _pad_diff_result


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
        session_id=session_id,
        # The host passes this seam the identity fields, the result, and the
        # timing — no home (`model_tools._apply_transform_tool_result_hook`).
        # Empty here means the nudge's plan read and its budget store both
        # fall back to the default home, the way every other bundle reader
        # does; the kwargs are still consulted so a bundle-internal caller or
        # a test can bind one. The two must agree, and they do because they
        # are the same string.
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
    )
    if recovered is not None:
        annotated = recovered
        kwargs = {**kwargs, "result": recovered}
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
    )
    if waited is not None:
        annotated = waited
        kwargs = {**kwargs, "result": waited}
    padded = _pad_diff_result(**kwargs)
    if padded is not None:
        return padded
    return annotated
