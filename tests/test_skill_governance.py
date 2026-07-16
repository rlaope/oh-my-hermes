import json
import tempfile
import unittest
from pathlib import Path

from omh.quality.skill_governance import (
    build_skill_governance_policy,
    resolve_skill_governance,
    policy_decision_digest,
    validate_skill_governance_policy,
)
from omh.routing.chat import route_chat_message


class SkillGovernanceTests(unittest.TestCase):
    def test_project_precedes_user_builtin_and_native_per_field(self) -> None:
        policy = build_skill_governance_policy(
            project={"skills": ["project"], "priority": "project"},
            user={"skills": ["user"], "priority": "user", "runtime_priority": "user"},
            builtin_omh={"skills": ["builtin"], "runtime_priority": "builtin"},
            native_hermes={"skills": ["native"]},
        )
        result = resolve_skill_governance(policy)
        self.assertEqual(result["selected_skills"], ["project"])
        self.assertEqual(result["selected_policy"]["priority"], "project")
        self.assertEqual(result["selected_policy"]["runtime_priority"], "user")
        self.assertEqual(result["runtime_priority_observed"], False)
        self.assertEqual(result["native_recommendations"], ["native"])
        self.assertEqual(result["selected_native_skills"], [])

    def test_native_cannot_override_omh(self) -> None:
        result = resolve_skill_governance(
            build_skill_governance_policy(builtin_omh={"skills": ["omh"]}, native_hermes={"skills": ["native"]})
        )
        self.assertEqual(result["selected_skills"], ["omh"])
        self.assertEqual(result["selected_native_skills"], [])

    def test_unknown_and_conflicting_policy_fail_closed(self) -> None:
        unknown = {"schema_version": "skill_governance_policy/v9", "project": {"typo": 1}}
        self.assertFalse(validate_skill_governance_policy(unknown)["valid"])
        conflict = build_skill_governance_policy(project=[{"skills": ["a"]}, {"skills": ["b"]}])
        result = resolve_skill_governance(conflict)
        self.assertEqual(result["status"], "fail_closed")
        self.assertEqual(result["selected_native_skills"], [])

    def test_prepared_policy_is_not_observed_without_explicit_record(self) -> None:
        prepared = resolve_skill_governance(build_skill_governance_policy(builtin_omh={"priority": "high"}))
        self.assertTrue(prepared["policy_prepared"])
        self.assertEqual(prepared["prepared_status"], "policy_prepared")
        self.assertEqual(prepared["evidence_boundary"], "prepared_not_observed")
        self.assertFalse(prepared["runtime_priority_observed"])
        policy = build_skill_governance_policy(
                builtin_omh={
                    "runtime_priority": "high",
                    "omh_observed_record": {
                        "provenance": "omh_observed_record", "ref": "obs-1",
                        "record_type": "policy_applied", "executor": "high", "runtime_priority": "high",
                        "source": {"repository_id": "repo", "commit_sha": "commit", "tree_sha": "tree"},
                        "policy_digest": policy_decision_digest(
                            {"runtime_priority": "high"}, executor="high",
                            source={"repository_id": "repo", "commit_sha": "commit", "tree_sha": "tree"},
                        ),
                    },
                },
                source={"repository_id": "repo", "commit_sha": "commit", "tree_sha": "tree"},
            )
        self.assertEqual(resolve_skill_governance(policy)["status"], "fail_closed")

    def test_policy_applied_record_must_match_winning_policy(self) -> None:
        source = {"repository_id": "repo", "commit_sha": "commit", "tree_sha": "tree"}
        record = {
            "provenance": "omh_observed_record", "ref": "obs-1", "record_type": "policy_applied",
            "executor": "project", "runtime_priority": "project", "source": source,
            "policy_digest": policy_decision_digest({"runtime_priority": "builtin"}, executor="builtin", source=source),
        }
        result = resolve_skill_governance(build_skill_governance_policy(
            project={"runtime_priority": "project"}, builtin_omh={"runtime_priority": "builtin", "omh_observed_record": record}, source=source,
        ))
        self.assertEqual(result["status"], "fail_closed")
        self.assertFalse(result["runtime_priority_observed"])

    def test_policy_applied_record_requires_source_executor_and_priority(self) -> None:
        source = {"repository_id": "repo", "commit_sha": "commit", "tree_sha": "tree"}
        for record in ({"provenance": "omh_observed_record", "ref": "obs"}, {
            "provenance": "omh_observed_record", "ref": "obs", "record_type": "policy_applied",
            "executor": "high", "source": source, "policy_digest": "0" * 64,
        }):
            result = resolve_skill_governance(build_skill_governance_policy(
                builtin_omh={"omh_observed_record": record}, source=source,
            ))
            self.assertEqual(result["status"], "fail_closed")
            self.assertFalse(result["runtime_priority_observed"])

    def test_local_omh_record_is_required_for_observation(self) -> None:
        source = {"repository_id": "repo", "commit_sha": "commit", "tree_sha": "tree"}
        record = {
            "provenance": "omh_observed_record", "ref": "records/policy.json", "record_type": "policy_applied", "observed": True,
            "executor": "high", "runtime_priority": "high", "source": source,
            "policy_digest": policy_decision_digest({"runtime_priority": "high"}, executor="high", source=source),
        }
        record["policy_identity"] = {
            "policy": {"runtime_priority": "high"}, "executor": "high", "source": source,
        }
        policy = build_skill_governance_policy(builtin_omh={"runtime_priority": "high", "omh_observed_record": record}, source=source)
        with tempfile.TemporaryDirectory() as home:
            target = Path(home) / record["ref"]
            target.parent.mkdir()
            target.write_text(json.dumps(record), encoding="utf-8")
            self.assertTrue(resolve_skill_governance(policy, omh_home=home)["runtime_priority_observed"])
            self.assertEqual(resolve_skill_governance(policy, omh_home=home + "/missing")["status"], "fail_closed")

    def test_bare_or_foreign_observation_data_cannot_upgrade_prepared_policy(self) -> None:
        for record in (
            {"ref": "bare"},
            {"provenance": "config", "ref": "config"},
            {"provenance": "omh_observed_record", "ref": ""},
            {"provenance": "omh_observed_record", "ref": "x", "extra": True},
        ):
            result = resolve_skill_governance(build_skill_governance_policy(builtin_omh={"omh_observed_record": record}))
            self.assertEqual(result["status"], "fail_closed")
            self.assertFalse(result["runtime_priority_observed"])

    def test_skills_are_nonempty_unique_strings(self) -> None:
        result = resolve_skill_governance(build_skill_governance_policy(project={"skills": ["same", "same"]}))
        self.assertEqual(result["status"], "fail_closed")

    def test_native_recommendations_cannot_supply_governance_fields(self) -> None:
        result = resolve_skill_governance(
            build_skill_governance_policy(native_hermes={"skills": ["native"], "priority": "native"})
        )
        self.assertEqual(result["status"], "fail_closed")

    def test_governed_values_reject_whitespace(self) -> None:
        result = resolve_skill_governance(
            build_skill_governance_policy(project={"skills": [" "], "priority": " "})
        )
        self.assertEqual(result["status"], "fail_closed")

    def test_falsey_malformed_levels_do_not_become_empty_policy(self) -> None:
        result = resolve_skill_governance(build_skill_governance_policy(project=""))
        self.assertEqual(result["status"], "fail_closed")
        self.assertEqual(result["errors"], ["malformed_policy"])

    def test_explicit_null_policy_levels_fail_closed(self) -> None:
        for level in ("project", "user", "builtin_omh", "native_hermes"):
            with self.subTest(level=level):
                policy = {
                    "schema_version": "skill_governance_policy/v1",
                    level: None,
                }
                result = resolve_skill_governance(policy)
                self.assertEqual(result["status"], "fail_closed")
                self.assertEqual(result["errors"], ["malformed_policy"])

    def test_chat_route_applies_omh_policy_and_keeps_native_as_recommendation(self) -> None:
        policy = build_skill_governance_policy(
            project={"skills": ["code-review"]},
            native_hermes={"skills": ["native-browser"]},
        )

        route = route_chat_message(
            "plan a product change",
            source="discord",
            skill_policy=policy,
        )

        self.assertEqual(route["selected_skill"], "code-review")
        self.assertEqual(route["skill_governance"]["status"], "resolved")
        self.assertEqual(route["native_skill_recommendations"], ["native-browser"])
        self.assertNotEqual(route["selected_skill"], "native-browser")


if __name__ == "__main__":
    unittest.main()
