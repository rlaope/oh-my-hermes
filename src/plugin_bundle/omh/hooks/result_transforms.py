"""Composed ``transform_tool_result`` seam.

This is the single registered entry for the hook; it chains the three OMH
result transforms in a fixed order:

1. Code-mode discipline annotation — the first ``execute_code`` result of a
   session gains a bounded guidance block under its own JSON key
   (``code_mode_guidance.py``).
2. Engagement nudges — a session that has changed several files without
   declaring a plan, or searched repeatedly without routing a lane, gets a
   bounded, budgeted, self-latching nudge (``engagement_nudges.py``).
3. Full-width diff band padding — tool-result diffs get their painted lines
   padded to a uniform band (``diff_presentation.py``).

Every transform is fail-open: anything one declines passes through to the
next, and ``None`` from all of them leaves the host result untouched. Order
matters only when one result matches more than one pass (an execute_code
result whose output embeds a diff): the annotating passes run before the diff
pass so it still sees and pads the final string.

The two annotating passes cannot collide. They watch disjoint tool sets —
``execute_code`` for the first, the file-mutating and search/read tools for the
second — so no result is ever handed to both, and each writes its own JSON key.
"""

from __future__ import annotations

from typing import Any

from ..code_mode_guidance import annotate_execute_code_result
from ..engagement_nudges import annotate_engagement_nudge
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
        session_id=session_id,
        # The host passes this seam the identity fields, the result, and the
        # timing — no home (`model_tools._apply_transform_tool_result_hook`).
        # Empty here means the nudge's plan read falls back to the default
        # home, the way every other bundle reader does; the kwargs are still
        # consulted so a bundle-internal caller or a test can bind one.
        omh_home=str(kwargs.get("omh_home", "") or ""),
        hermes_home=str(kwargs.get("hermes_home", "") or ""),
    )
    if nudged is not None:
        annotated = nudged
        kwargs = {**kwargs, "result": nudged}
    padded = _pad_diff_result(**kwargs)
    if padded is not None:
        return padded
    return annotated
