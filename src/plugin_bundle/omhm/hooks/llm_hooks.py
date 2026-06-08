from __future__ import annotations

from ..runtime_reader import read_omhm_status


def pre_llm_call(**kwargs) -> dict[str, str] | None:
    """Inject bounded OMHM status context without reading or storing prompts."""
    try:
        omh_home = str(kwargs.get("omh_home", "") or "") or None
        status = read_omhm_status(omh_home=omh_home, limit=3)
    except Exception:
        return None

    if not status.get("runtime_state_present") and not status.get("runs"):
        return None

    lines = [
        "[OMHM] Native bridge status context.",
        "Evidence boundary: prepared handoffs are not execution, review, CI, merge-readiness, or merge evidence.",
    ]
    latest_run_id = status.get("latest_run_id")
    if latest_run_id:
        lines.append(f"Latest runtime run: {latest_run_id}.")
    for run in status.get("runs", [])[:3]:
        run_id = run.get("run_id", "unknown")
        workflow = run.get("workflow", "unknown")
        phase = run.get("phase", "unknown")
        observation = run.get("observation_status", "unknown")
        execution = run.get("execution_observed", False)
        review = run.get("review_observed", False)
        ci = run.get("ci_observed", False)
        merge = run.get("merge_observed", False)
        lines.append(
            f"- {run_id}: workflow={workflow}, phase={phase}, observation={observation}, "
            f"execution_observed={execution}, review_observed={review}, ci_observed={ci}, merge_observed={merge}."
        )
    lines.append("Use omhm_status for the full metadata-only status payload.")
    return {"context": "\n".join(lines)}
