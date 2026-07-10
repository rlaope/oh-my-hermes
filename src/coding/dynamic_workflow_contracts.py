from __future__ import annotations


DYNAMIC_WORKFLOW_SCHEMA_VERSION = "dynamic_coding_workflow/v1"
DYNAMIC_WORKFLOW_CHART_SCHEMA_VERSION = "dynamic_coding_workflow_chart/v1"
DYNAMIC_WORKFLOW_MESSAGE_PROJECTION_SCHEMA_VERSION = "dynamic_coding_workflow_message_projection/v1"
PREPARED_NOT_OBSERVED = "prepared_not_observed"
CLAIM_BOUNDARY = (
    "Dynamic workflow plans and charts are prepared orchestration artifacts only. "
    "They are not model invocation, runtime dispatch, implementation, review, CI, merge-readiness, or merge evidence."
)
DYNAMIC_WORKFLOW_LANES = ("intake", "planning", "critique", "implementation", "review", "report")
