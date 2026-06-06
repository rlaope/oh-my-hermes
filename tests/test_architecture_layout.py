from __future__ import annotations

import unittest

from _local_package import load_local_package

load_local_package()
from omh import chat_router, cli, coding_lifecycle, recommend, runtime_artifacts, runtime_records, wrapper_contract, wrapper_sessions
from omh.commands import main as command_main
from omh.ingress import compact_source_metadata, extract_message_text, extract_source_metadata
from omh.routing import chat as routing_chat
from omh.routing import recommend as routing_recommend
from omh.runtime import artifacts as runtime_artifacts_module
from omh.runtime import records as runtime_records_module
from omh.skills import builtin_skill_templates
from omh.skills import packaging as skills_packaging
from omh.wrapper import contract as wrapper_contract_module
from omh.wrapper import lifecycle as wrapper_lifecycle_module
from omh.wrapper import sessions as wrapper_sessions_module


class ArchitectureLayoutTests(unittest.TestCase):
    def test_compatibility_adapters_point_to_deep_modules(self) -> None:
        self.assertIs(cli.main, command_main.main)
        self.assertIs(chat_router.route_chat_message, routing_chat.route_chat_message)
        self.assertIs(recommend.recommend_skills, routing_recommend.recommend_skills)
        self.assertIs(runtime_artifacts.create_run, runtime_artifacts_module.create_run)
        self.assertIs(runtime_records.validate_run_record, runtime_records_module.validate_run_record)
        self.assertIs(wrapper_contract.build_chat_interaction_payload, wrapper_contract_module.build_chat_interaction_payload)
        self.assertIs(wrapper_sessions.create_or_resume_wrapper_session, wrapper_sessions_module.create_or_resume_wrapper_session)
        self.assertIs(coding_lifecycle.start_codex_delegation_lifecycle, wrapper_lifecycle_module.start_codex_delegation_lifecycle)
        self.assertIs(builtin_skill_templates, skills_packaging.builtin_skill_templates)

    def test_ingress_owns_message_and_metadata_extraction(self) -> None:
        event = {"event": {"text": "risky refactor", "id": "m1", "channel": "c1", "user": "u1", "ts": "123.4"}}

        self.assertEqual(extract_message_text(event), "risky refactor")
        self.assertEqual(
            extract_source_metadata(event),
            {"source_event_id": "m1", "channel_ref": "c1", "user_ref": "u1", "timestamp": "123.4"},
        )
        self.assertEqual(compact_source_metadata({"source_event_id": "m1", "raw": "drop"}), {"source_event_id": "m1"})


if __name__ == "__main__":
    unittest.main()
