from __future__ import annotations

from typing import Final

from .workflow_learning_errors import WorkflowLearningError


SELF_IMPROVEMENT_STORE_ROUTING_SCHEMA_VERSION: Final = "self_improvement_store_routing/v1"
SELF_IMPROVEMENT_DESTINATION_DETAILS: Final = {
    "memory_candidate": {
        "target_workflow": "memory-curation-review",
        "target_record_type": "project_memory_candidate",
        "next_action": "prepare_memory_curation_review",
        "confidence": "high",
    },
    "skill_update_candidate": {
        "target_workflow": "workflow-learning",
        "target_record_type": "improvement_candidate",
        "next_action": "review_improvement",
        "confidence": "high",
    },
    "wiki_candidate": {
        "target_workflow": "wiki",
        "target_record_type": "retained_knowledge_note",
        "next_action": "prepare_wiki_guidance",
        "confidence": "high",
    },
    "failure_retrospective_candidate": {
        "target_workflow": "workflow-learning",
        "target_record_type": "workflow_learning_trace",
        "next_action": "record_workflow_learning_trace",
        "confidence": "high",
    },
    "automation_suggestion_candidate": {
        "target_workflow": "automation-blueprint",
        "target_record_type": "automation_suggestion",
        "next_action": "prepare_automation_blueprint",
        "confidence": "high",
    },
    "discard_transient": {
        "target_workflow": "none",
        "target_record_type": "none",
        "next_action": "do_not_store",
        "confidence": "high",
    },
    "manual_review_candidate": {
        "target_workflow": "memory-curation-review",
        "target_record_type": "store_review_question",
        "next_action": "review_self_improvement_store_route",
        "confidence": "needs_review",
    },
}
SELF_IMPROVEMENT_DESTINATION_PRIORITY: Final = (
    "discard_transient",
    "automation_suggestion_candidate",
    "failure_retrospective_candidate",
    "wiki_candidate",
    "skill_update_candidate",
    "memory_candidate",
)


def self_improvement_store_destinations() -> list[str]:
    return list(SELF_IMPROVEMENT_DESTINATION_DETAILS)


def self_improvement_store_destination_details(destination: str) -> dict[str, str]:
    if destination not in SELF_IMPROVEMENT_DESTINATION_DETAILS:
        raise WorkflowLearningError("self-improvement store destination is invalid")
    return {key: str(value) for key, value in SELF_IMPROVEMENT_DESTINATION_DETAILS[destination].items()}
