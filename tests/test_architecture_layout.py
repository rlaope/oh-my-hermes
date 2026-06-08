from __future__ import annotations

from pathlib import Path
import unittest

from _local_package import load_local_package

load_local_package()
from omh import (
    chat_router,
    cli,
    coding_lifecycle,
    playbooks,
    recommend,
    roles,
    runtime_artifacts,
    runtime_records,
    setup_profiles,
    team_profiles,
    wrapper_contract,
    wrapper_sessions,
)
from omh.catalogs import playbooks as catalog_playbooks
from omh.catalogs import roles as catalog_roles
from omh.commands import main as command_main
from omh.ingress import compact_source_metadata, extract_message_text, extract_source_metadata
from omh.profiles import setup as profile_setup
from omh.profiles import team as profile_team
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
        self.assertIs(playbooks.list_playbooks, catalog_playbooks.list_playbooks)
        self.assertIs(roles.role_definitions, catalog_roles.role_definitions)
        self.assertIs(setup_profiles.build_setup_profile, profile_setup.build_setup_profile)
        self.assertIs(team_profiles.list_team_profile_packs, profile_team.list_team_profile_packs)

    def test_root_compatibility_facades_stay_thin(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        facades = {
            "src/chat_router.py": "from .routing.chat import *  # noqa: F401,F403",
            "src/recommend.py": "from .routing.recommend import *  # noqa: F401,F403",
            "src/runtime_artifacts.py": "from .runtime.artifacts import *  # noqa: F401,F403",
            "src/runtime_records.py": "from .runtime.records import *  # noqa: F401,F403",
            "src/wrapper_contract.py": "from .wrapper.contract import *  # noqa: F401,F403",
            "src/wrapper_sessions.py": "from .wrapper.sessions import *  # noqa: F401,F403",
            "src/coding_lifecycle.py": "from .wrapper.lifecycle import *  # noqa: F401,F403",
            "src/playbooks.py": "from .catalogs.playbooks import *  # noqa: F401,F403",
            "src/roles.py": "from .catalogs.roles import *  # noqa: F401,F403",
            "src/setup_profiles.py": "from .profiles.setup import *  # noqa: F401,F403",
            "src/team_profiles.py": "from .profiles.team import *  # noqa: F401,F403",
        }
        for relative_path, import_line in facades.items():
            with self.subTest(relative_path=relative_path):
                lines = [
                    line
                    for line in (repo_root / relative_path).read_text(encoding="utf-8").splitlines()
                    if line.strip()
                ]
                self.assertEqual(lines, ["from __future__ import annotations", import_line])

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
