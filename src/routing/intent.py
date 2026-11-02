"""Core facade for the workflow-intent classifier shipped with the standalone plugin.

The classifier lives in `plugin_bundle/omh/workflow_intent.py` so the bundle's
route hint and the chat router run one implementation, including on a Hermes
host that cannot import the `omh` package.
"""

from ..plugin_bundle.omh.workflow_intent import (
    META_OR_FEEDBACK_INTENTS,
    RUNTIME_VOCABULARY,
    WORKFLOW_VOCABULARY,
    OmhQualityIntent,
    WorkflowIntent,
    classify_omh_quality_intent,
    classify_workflow_intent,
    has_missing_requirements_signal,
    is_workflow_meta_or_feedback,
    scrub_diagnostic_status_text,
)

__all__ = [
    "META_OR_FEEDBACK_INTENTS",
    "RUNTIME_VOCABULARY",
    "WORKFLOW_VOCABULARY",
    "OmhQualityIntent",
    "WorkflowIntent",
    "classify_omh_quality_intent",
    "classify_workflow_intent",
    "has_missing_requirements_signal",
    "is_workflow_meta_or_feedback",
    "scrub_diagnostic_status_text",
]
