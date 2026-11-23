"""The automation-intent and orchestration graders catch deliberately wrong decisions.

Each suite's grader is a pure function from a scenario and one observation row
to failures. A decision built from the scenario's own expectation must pass,
for every scenario in both splits; each deliberately wrong one below must fail
on the named check.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from _local_package import load_local_package

load_local_package()

from omh.quality import automation_intent_grading as automation  # noqa: E402
from omh.quality import orchestration_grading as orchestration  # noqa: E402
from omh.quality.scenario_suite import SPLITS, load_split  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
AUTOMATION_LANE = ROOT / "benchmarks" / "automation-intent" / "v1"
ORCHESTRATION_LANE = ROOT / "benchmarks" / "orchestration" / "v1"


def _scenarios(lane: Path) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for split in SPLITS:
        for scenario in load_split(lane, split)["scenarios"]:
            rows[scenario["id"]] = scenario
    return rows


AUTOMATION = _scenarios(AUTOMATION_LANE)
ORCHESTRATION = _scenarios(ORCHESTRATION_LANE)


def _ideal_automation_decision(scenario: dict) -> dict:
    """The decision the scenario's expectation describes, in observation form."""
    expect = scenario["expect"]
    decision: dict = {"outcome": expect["outcome"]}
    if "automation" in expect:
        want = expect["automation"]
        projection = {
            "schedule": want["schedule"][0],
            "deliver": list(want["deliver"]),
            "filters": copy.deepcopy(want.get("filters", {})),
        }
        if "timezone" in want:
            projection["timezone"] = want["timezone"][0]
        for key in ("job_id", "target", "silence", "state"):
            if key in want:
                projection[key] = copy.deepcopy(want[key])
        if isinstance(want.get("target"), list):
            projection["target"] = copy.deepcopy(want["target"][0])
        decision["automation"] = projection
    if "clarify_about" in expect:
        decision["asks_about"] = list(expect["clarify_about"])
    return decision


def _ideal_orchestration_decision(scenario: dict) -> dict:
    expect = scenario["expect"]
    handoffs = []
    if expect["handoff"] == "required":
        handoffs = [{"owner": expect["owner"], "repository": expect["repository"]}]
    reply = "Done."
    if expect.get("must_cite"):
        reply = "See " + " and ".join(expect["must_cite"]) + "."
    return {"handoffs": handoffs, "parent_edits": [], "reply": reply}


def _observed(decision: dict) -> dict:
    return {"scenario_id": "x", "status": "observed", "decision": decision}


def _checks(failures) -> list[str]:
    return [failure.check for failure in failures]


class AutomationIntentGraderTests(unittest.TestCase):
    def grade(self, scenario_id: str, decision: dict):
        return automation.grade_automation_intent(AUTOMATION[scenario_id], _observed(decision))

    def ideal(self, scenario_id: str) -> dict:
        return _ideal_automation_decision(AUTOMATION[scenario_id])

    def test_every_scenario_passes_with_its_own_expected_decision(self) -> None:
        for scenario_id, scenario in AUTOMATION.items():
            with self.subTest(scenario_id):
                self.assertEqual(self.grade(scenario_id, _ideal_automation_decision(scenario)), ())

    def test_every_timezone_expectation_is_satisfiable_under_the_stated_contract(self) -> None:
        # The contract: the zone the request names, else prior_state.user_timezone, else empty.
        named_zones = {"KST": "Asia/Seoul", "UTC": "UTC"}
        self.assertIn("the one the request names, else prior_state.user_timezone", automation.DECISION_CONTRACT)
        checked = 0
        for scenario_id, scenario in AUTOMATION.items():
            want = scenario["expect"].get("automation", {})
            if "timezone" not in want:
                continue
            words = scenario["request"].replace(",", " ").replace(".", " ").split()
            named = [zone for token, zone in named_zones.items() if token in words]
            zone = named[0] if named else scenario.get("prior_state", {}).get("user_timezone", "")
            decision = _ideal_automation_decision(scenario)
            decision["automation"]["timezone"] = zone
            with self.subTest(scenario_id):
                self.assertEqual(self.grade(scenario_id, decision), ())
            checked += 1
        self.assertGreater(checked, 10)

    def test_multiple_values_under_one_filter_key_mean_any(self) -> None:
        self.assertIn("Several values under one key match any of them.", automation.DECISION_CONTRACT)
        for scenario_id, scenario in AUTOMATION.items():
            filters = scenario["expect"].get("automation", {}).get("filters", {})
            if any(len(values) > 1 for values in filters.values()):
                with self.subTest(scenario_id):
                    self.assertNotIn(" both ", f" {scenario['request'].casefold()} ")

    def test_coding_the_parent_may_do_without_an_owner_rests_on_the_owner_rule(self) -> None:
        # With the rule out of the shared instructions, a coding request that names
        # no owner in this request can be answered "hand it off" by an arm that
        # never read the rule. Every such scenario is in the skill_rule group.
        for scenario_id, scenario in ORCHESTRATION.items():
            expect = scenario["expect"]
            if expect["handoff"] == "forbidden" and expect["parent_may_edit"]:
                with self.subTest(scenario_id):
                    self.assertEqual(scenario.get("skill_rule"), "owner_named_in_this_request")

    def test_the_skill_rule_group_is_more_than_one_observation_in_every_split(self) -> None:
        root = Path(__file__).resolve().parents[1]
        for lane in ("automation-intent", "orchestration"):
            manifest = json.loads((root / "benchmarks" / lane / "v1" / "manifest.json").read_text(encoding="utf-8"))
            for split, block in manifest["splits"].items():
                corpus = load_split(root / "benchmarks" / lane / "v1", split)
                ruled = sum(1 for row in corpus["scenarios"] if row.get("skill_rule"))
                with self.subTest(lane=lane, split=split):
                    self.assertGreaterEqual(ruled, 2)
                    self.assertEqual(block["skill_rule_scenarios"], ruled)

    def test_skill_rules_reach_only_the_skill_text_arm(self) -> None:
        # The rule a skill_rule scenario rests on is in the skill text the
        # skill-text arm reads, and in nothing every arm is given.
        root = Path(__file__).resolve().parents[1]
        for module, scenarios in ((automation, AUTOMATION), (orchestration, ORCHESTRATION)):
            for rule, (skill_file, words) in module.SKILL_RULES.items():
                with self.subTest(rule):
                    self.assertIn(words, (root / skill_file).read_text(encoding="utf-8"))
                    for given in (module.SUITE_INSTRUCTIONS, module.DECISION_CONTRACT):
                        self.assertNotIn("never spends", given)
                        self.assertNotIn("never moves money", given)
                        self.assertNotIn("in this request", given)
                    self.assertTrue(any(row.get("skill_rule") == rule for row in scenarios.values()))
        for scenario_id, scenario in {**AUTOMATION, **ORCHESTRATION}.items():
            if "skill_rule" in scenario:
                with self.subTest(scenario_id):
                    self.assertNotIn("skill_rule", json.dumps(
                        automation.arm_view(scenario) if scenario_id.startswith("ai-") else orchestration.arm_view(scenario)
                    ))

    def test_asking_about_every_topic_is_not_a_question(self) -> None:
        everything = {"outcome": "clarifying_question", "asks_about": list(automation.CLARIFY_TOPICS)}
        self.assertEqual(_checks(self.grade("ai-ask-daily-without-time", everything)), ["asks_about"])
        self.assertEqual(_checks(self.grade("ai-ask-daily-without-time", {"outcome": "clarifying_question"})), ["asks_about"])

    def test_any_open_topic_is_a_right_question(self) -> None:
        # A synthetic scenario: held-out ids stay out of the tests.
        scenario = copy.deepcopy(AUTOMATION["ai-ask-which-repository"])
        scenario["expect"]["clarify_about"] = ["target", "schedule"]
        for topics, passes in ((["target"], True), (["schedule"], True), (["target", "schedule"], True), (["delivery"], False)):
            decision = {"outcome": "clarifying_question", "asks_about": topics}
            with self.subTest(topics):
                self.assertEqual(automation.grade_automation_intent(scenario, _observed(decision)) == (), passes)

    def test_edit_must_not_move_a_state_nobody_changed(self) -> None:
        scenario_id = "ai-edit-move-standup-time"
        decision = self.ideal(scenario_id)
        for state, passes in (("removed", False), ("paused", False), ("active", True), (None, True)):
            if state is None:
                decision["automation"].pop("state", None)
            else:
                decision["automation"]["state"] = state
            with self.subTest(state):
                failures = self.grade(scenario_id, decision)
                self.assertEqual(failures == (), passes, failures)

    def test_edit_of_a_job_without_a_recorded_state_treats_it_as_active(self) -> None:
        scenario = copy.deepcopy(AUTOMATION["ai-edit-move-standup-time"])
        del scenario["prior_state"]["automations"][0]["state"]
        decision = _ideal_automation_decision(scenario)
        decision["automation"]["state"] = "active"
        self.assertEqual(automation.grade_automation_intent(scenario, _observed(decision)), ())
        decision["automation"]["state"] = "removed"
        self.assertEqual(_checks(automation.grade_automation_intent(scenario, _observed(decision))), ["automation.state"])

    def test_attached_blueprint_to_another_channel_fails(self) -> None:
        scenario_id = "ai-slack-merged-prs-to-channel"
        decision = self.ideal(scenario_id)
        blueprint = {
            "schema_version": "prepared_native_blueprint/v1",
            "observation_status": "prepared",
            "native_blueprint": {"cronjob_manage_create": {"action": "create", "schedule": "0 18 * * 1-5", "deliver": "slack:#general"}},
        }
        decision["artifact"] = blueprint
        self.assertEqual(_checks(self.grade(scenario_id, decision)), ["artifact.deliver"])
        blueprint["native_blueprint"]["cronjob_manage_create"]["deliver"] = "slack"
        self.assertEqual(self.grade(scenario_id, decision), ())
        blueprint["native_blueprint"]["cronjob_manage_create"]["deliver"] = "slack:release-notes"
        self.assertEqual(self.grade(scenario_id, decision), ())

    def test_zone_abbreviation_the_request_names_is_accepted(self) -> None:
        decision = self.ideal("ai-schedule-sunday-night-explicit-zone")
        decision["automation"]["timezone"] = "KST"
        self.assertEqual(self.grade("ai-schedule-sunday-night-explicit-zone", decision), ())
        decision["automation"]["timezone"] = "EST"
        self.assertEqual(_checks(self.grade("ai-schedule-sunday-night-explicit-zone", decision)), ["automation.timezone"])

    def test_github_author_spellings_are_one_author(self) -> None:
        for author in ("dependabot[bot]", "@dependabot", "Dependabot"):
            decision = self.ideal("ai-filters-bot-commits-on-main")
            decision["automation"]["filters"]["authors"] = [author]
            with self.subTest(author):
                self.assertEqual(self.grade("ai-filters-bot-commits-on-main", decision), ())

    def test_a_list_that_may_be_empty_is_not_graded_on_silence(self) -> None:
        for scenario_id in ("ai-github-stale-open-prs-weekly", "ai-results-to-email"):
            for silence in ("only_report_changes", "report_each_run"):
                decision = self.ideal(scenario_id)
                decision["automation"]["silence"] = silence
                with self.subTest(scenario_id, silence=silence):
                    self.assertEqual(self.grade(scenario_id, decision), ())

    def test_reasonable_readings_the_corpus_accepts(self) -> None:
        decision = self.ideal("ai-schedule-weekday-morning-status")
        decision["automation"]["filters"] = {"keywords": ["degraded"]}
        self.assertEqual(self.grade("ai-schedule-weekday-morning-status", decision), ())
        decision = self.ideal("ai-filters-two-labels")
        decision["automation"]["filters"]["states"] = ["open"]
        self.assertEqual(self.grade("ai-filters-two-labels", decision), ())
        decision = self.ideal("ai-results-to-two-destinations")
        decision["automation"]["target"] = {"kind": "url", "ref": "https://news.example.com/rss"}
        self.assertEqual(self.grade("ai-results-to-two-destinations", decision), ())
        decision["automation"]["target"] = {"kind": "url", "ref": "https://news.example.com/other"}
        self.assertEqual(_checks(self.grade("ai-results-to-two-destinations", decision)), ["automation.target"])
        decision = self.ideal("ai-schedule-weekday-morning-status")
        decision["automation"]["schedule"] = "0 9 * * 1,2,3,4,5"
        self.assertEqual(self.grade("ai-schedule-weekday-morning-status", decision), ())

    def test_equivalent_schedule_spellings_pass(self) -> None:
        for spelling in ("0 9 * * MON-FRI", "00 09 * * 1-5", " 0  9 * * mon-fri "):
            decision = self.ideal("ai-schedule-weekday-morning-status")
            decision["automation"]["schedule"] = spelling
            with self.subTest(spelling):
                self.assertEqual(self.grade("ai-schedule-weekday-morning-status", decision), ())
        for spelling in ("every 2 hours", "every 120m", "every 120 minutes", "0 */2 * * *"):
            decision = self.ideal("ai-schedule-every-two-hours-feed")
            decision["automation"]["schedule"] = spelling
            with self.subTest(spelling):
                self.assertEqual(self.grade("ai-schedule-every-two-hours-feed", decision), ())

    def test_wrong_schedule_fails(self) -> None:
        for spelling in ("0 9 * * *", "0 21 * * 1-5", "every 9h", "0 9 * * 0-4"):
            decision = self.ideal("ai-schedule-weekday-morning-status")
            decision["automation"]["schedule"] = spelling
            with self.subTest(spelling):
                self.assertEqual(_checks(self.grade("ai-schedule-weekday-morning-status", decision)), ["automation.schedule"])

    def test_profile_timezone_instead_of_named_zone_fails(self) -> None:
        decision = self.ideal("ai-schedule-sunday-night-explicit-zone")
        decision["automation"]["timezone"] = "America/New_York"
        self.assertEqual(_checks(self.grade("ai-schedule-sunday-night-explicit-zone", decision)), ["automation.timezone"])

    def test_wrong_repository_target_fails(self) -> None:
        decision = self.ideal("ai-github-failed-ci-on-main")
        decision["automation"]["target"] = {"kind": "github_repo", "ref": "acme/web"}
        self.assertEqual(_checks(self.grade("ai-github-failed-ci-on-main", decision)), ["automation.target"])

    def test_repository_url_spelling_of_the_right_target_passes(self) -> None:
        decision = self.ideal("ai-github-failed-ci-on-main")
        decision["automation"]["target"] = {"kind": "github_repo", "ref": "https://github.com/Acme/Payments.git"}
        self.assertEqual(self.grade("ai-github-failed-ci-on-main", decision), ())

    def test_invented_filter_fails(self) -> None:
        decision = self.ideal("ai-github-new-issues-daily")
        decision["automation"]["filters"]["labels"] = ["bug"]
        self.assertEqual(_checks(self.grade("ai-github-new-issues-daily", decision)), ["automation.filters.labels (not requested)"])
        # An optional filter with a value outside the listed ones is still invented.
        decision = self.ideal("ai-github-new-issues-daily")
        decision["automation"]["filters"]["states"] = ["closed"]
        self.assertEqual(_checks(self.grade("ai-github-new-issues-daily", decision)), ["automation.filters.states (not requested)"])
        decision["automation"]["filters"]["states"] = ["open"]
        self.assertEqual(self.grade("ai-github-new-issues-daily", decision), ())

    def test_dropped_filter_value_fails(self) -> None:
        decision = self.ideal("ai-filters-two-labels")
        decision["automation"]["filters"]["labels"] = ["bug"]
        self.assertEqual(_checks(self.grade("ai-filters-two-labels", decision)), ["automation.filters.labels"])

    def test_equivalent_spellings_of_places_pass(self) -> None:
        decision = self.ideal("ai-github-stale-open-prs-weekly")
        decision["automation"]["deliver"] = ["Slack:eng-review"]
        self.assertEqual(self.grade("ai-github-stale-open-prs-weekly", decision), ())
        decision = self.ideal("ai-results-to-two-destinations")
        decision["automation"]["deliver"] = ["origin", "telegram:daily_brief"]
        self.assertEqual(self.grade("ai-results-to-two-destinations", decision), ())
        decision = self.ideal("ai-slack-watch-support-for-outages")
        decision["automation"]["target"] = {"kind": "slack_channel", "ref": "support"}
        self.assertEqual(self.grade("ai-slack-watch-support-for-outages", decision), ())
        decision = self.ideal("ai-schedule-weekday-morning-status")
        decision["automation"]["target"] = {"kind": "url", "ref": "https://status.example.com/"}
        self.assertEqual(self.grade("ai-schedule-weekday-morning-status", decision), ())
        decision = self.ideal("ai-results-to-email")
        decision["automation"]["timezone"] = "Etc/UTC"
        self.assertEqual(self.grade("ai-results-to-email", decision), ())
        decision = self.ideal("ai-filters-merged-prs-touching-path")
        decision["automation"]["filters"]["paths"] = ["src/routing"]
        self.assertEqual(self.grade("ai-filters-merged-prs-touching-path", decision), ())

    def test_optional_filters_may_be_stated_but_not_invented(self) -> None:
        scenario_id = "ai-slack-watch-support-for-outages"
        decision = self.ideal(scenario_id)
        decision["automation"]["filters"] = {"keywords": ["outage"], "event_types": ["messages"]}
        self.assertEqual(self.grade(scenario_id, decision), ())
        decision["automation"]["filters"] = {"keywords": ["refund"]}
        self.assertEqual(_checks(self.grade(scenario_id, decision)), ["automation.filters.keywords (not requested)"])
        decision["automation"]["filters"] = {"labels": ["vip"]}
        self.assertEqual(_checks(self.grade(scenario_id, decision)), ["automation.filters.labels (not requested)"])

    def test_wrong_delivery_target_fails(self) -> None:
        decision = self.ideal("ai-slack-merged-prs-to-channel")
        decision["automation"]["deliver"] = ["origin"]
        self.assertEqual(_checks(self.grade("ai-slack-merged-prs-to-channel", decision)), ["automation.deliver"])
        decision["automation"]["deliver"] = ["slack:#release-notes", "origin"]
        self.assertEqual(_checks(self.grade("ai-slack-merged-prs-to-channel", decision)), ["automation.deliver"])

    def test_hermes_comma_joined_deliver_string_is_read(self) -> None:
        decision = self.ideal("ai-results-to-two-destinations")
        decision["automation"]["deliver"] = "telegram:@daily_brief,origin"
        self.assertEqual(self.grade("ai-results-to-two-destinations", decision), ())

    def test_guessing_instead_of_asking_fails(self) -> None:
        decision = self.ideal("ai-results-to-discord-channel")
        self.assertEqual(_checks(self.grade("ai-ask-slack-without-channel", decision)), ["outcome"])

    def test_asking_about_the_wrong_topic_fails(self) -> None:
        decision = {"outcome": "clarifying_question", "asks_about": ["schedule"]}
        self.assertEqual(_checks(self.grade("ai-ask-slack-without-channel", decision)), ["asks_about"])

    def test_a_question_carrying_an_automation_fails(self) -> None:
        decision = {"outcome": "clarifying_question", "asks_about": ["schedule"], "automation": {"schedule": "0 9 * * *"}}
        self.assertEqual(_checks(self.grade("ai-ask-daily-without-time", decision)), ["automation"])

    def test_automation_for_a_one_off_request_fails(self) -> None:
        decision = {"outcome": "prepared_automation", "automation": {"schedule": "@daily", "deliver": ["slack:#release-notes"]}}
        self.assertEqual(_checks(self.grade("ai-none-one-off-post-now", decision)), ["outcome"])

    def test_no_automation_with_a_prepared_record_fails(self) -> None:
        decision = {"outcome": "no_automation", "artifact": {"schema_version": "prepared_native_blueprint/v1"}}
        self.assertEqual(_checks(self.grade("ai-none-recurring-payment", decision)), ["artifact"])

    def test_duplicate_job_instead_of_edit_fails(self) -> None:
        decision = self.ideal("ai-edit-add-label-to-watch")
        decision["outcome"] = "prepared_automation"
        self.assertEqual(_checks(self.grade("ai-edit-add-label-to-watch", decision)), ["outcome"])

    def test_editing_the_wrong_job_fails(self) -> None:
        decision = self.ideal("ai-edit-pause-one-of-two")
        decision["automation"]["job_id"] = "job-release-watch"
        self.assertEqual(_checks(self.grade("ai-edit-pause-one-of-two", decision)), ["automation.job_id"])

    def test_edit_that_drops_an_unchanged_field_fails(self) -> None:
        decision = self.ideal("ai-edit-add-label-to-watch")
        decision["automation"]["filters"]["labels"] = ["regression"]
        self.assertEqual(_checks(self.grade("ai-edit-add-label-to-watch", decision)), ["automation.filters.labels"])

    def test_pause_without_state_fails(self) -> None:
        decision = self.ideal("ai-edit-pause-one-of-two")
        del decision["automation"]["state"]
        self.assertEqual(_checks(self.grade("ai-edit-pause-one-of-two", decision)), ["automation.state"])

    def test_missing_projection_fails(self) -> None:
        self.assertEqual(_checks(self.grade("ai-github-new-issues-daily", {"outcome": "prepared_automation"})), ["automation"])

    def test_malformed_decision_fails_rather_than_raising(self) -> None:
        for decision in ({}, {"outcome": 3}, {"outcome": "prepared_automation", "automation": {"filters": "bug"}}):
            with self.subTest(decision):
                self.assertTrue(self.grade("ai-github-new-issues-daily", decision))

    def test_attached_blueprint_must_agree_and_stay_prepared(self) -> None:
        scenario_id = "ai-schedule-weekday-morning-status"
        decision = self.ideal(scenario_id)
        decision["artifact"] = {
            "schema_version": "prepared_native_blueprint/v1",
            "observation_status": "prepared",
            "silence_policy": {"mode": "only_report_changes"},
            "native_blueprint": {"cronjob_manage_create": {"action": "create", "schedule": "0 9 * * 1-5", "deliver": "origin"}},
        }
        self.assertEqual(self.grade(scenario_id, decision), ())
        disagreeing = copy.deepcopy(decision)
        disagreeing["artifact"]["native_blueprint"]["cronjob_manage_create"]["schedule"] = "0 9 * * *"
        self.assertEqual(_checks(self.grade(scenario_id, disagreeing)), ["artifact.schedule"])
        wrong_platform = copy.deepcopy(decision)
        wrong_platform["artifact"]["native_blueprint"]["cronjob_manage_create"]["deliver"] = "slack"
        self.assertEqual(_checks(self.grade(scenario_id, wrong_platform)), ["artifact.deliver"])
        observed = copy.deepcopy(decision)
        observed["artifact"]["observation_status"] = "observed"
        self.assertEqual(_checks(self.grade(scenario_id, observed)), ["artifact.observation_status"])
        unknown = copy.deepcopy(decision)
        unknown["artifact"]["schema_version"] = "hermes_ops_blueprint/v1"
        self.assertEqual(_checks(self.grade(scenario_id, unknown)), ["artifact.schema_version"])

    def test_attached_recurring_intent_must_stay_paused(self) -> None:
        scenario_id = "ai-edit-move-standup-time"
        decision = self.ideal(scenario_id)
        decision["artifact"] = {
            "schema_version": "hermes_recurring_intent/v1",
            "observation_status": "prepared",
            "lifecycle": {"state": "paused"},
            "schedule_intent": {"explicit_schedule": "30 8 * * 1-5"},
            "delivery_intent": {"surfaces": ["slack"]},
            "silence_policy": {"mode": "report_each_run"},
        }
        self.assertEqual(self.grade(scenario_id, decision), ())
        activated = copy.deepcopy(decision)
        activated["artifact"]["lifecycle"]["state"] = "activated"
        self.assertEqual(_checks(self.grade(scenario_id, activated)), ["artifact.lifecycle.state"])
        silence = copy.deepcopy(decision)
        silence["artifact"]["silence_policy"]["mode"] = "only_report_changes"
        self.assertEqual(_checks(self.grade(scenario_id, silence)), ["artifact.silence_policy.mode"])


class ScheduleNormalizationTests(unittest.TestCase):
    def test_forms(self) -> None:
        cases = {
            "0 9 * * MON-FRI": "0 9 * * 1-5",
            "0 22 * * 7": "0 22 * * 0",
            "0 22 * * SUN": "0 22 * * 0",
            "30 8 1 JAN,JUL *": "30 8 1 1,7 *",
            "@hourly": "0 * * * *",
            "@daily": "0 0 * * *",
            "every 2h": "every 120m",
            "every 2 hours": "every 120m",
            "Every 1 Day": "every 1440m",
            "every hour": "every 60m",
            "*/15 * * * *": "*/15 * * * *",
            "tomorrow at noon": "tomorrow at noon",
        }
        for value, expected in cases.items():
            with self.subTest(value):
                self.assertEqual(automation.normalize_schedule(value), expected)

    def test_cron_and_interval_are_not_converted_into_each_other(self) -> None:
        self.assertNotEqual(automation.normalize_schedule("every 15m"), automation.normalize_schedule("*/15 * * * *"))


class OrchestrationGraderTests(unittest.TestCase):
    def grade(self, scenario_id: str, decision: dict, evidence_links: list[str] | None = None):
        row = _observed(decision)
        if evidence_links is not None:
            row["evidence_links"] = evidence_links
        return orchestration.grade_orchestration(ORCHESTRATION[scenario_id], row)

    def ideal(self, scenario_id: str) -> dict:
        return _ideal_orchestration_decision(ORCHESTRATION[scenario_id])

    def test_every_scenario_passes_with_its_own_expected_decision(self) -> None:
        for scenario_id, scenario in ORCHESTRATION.items():
            with self.subTest(scenario_id):
                self.assertEqual(self.grade(scenario_id, _ideal_orchestration_decision(scenario)), ())

    def test_handoff_to_the_wrong_owner_fails(self) -> None:
        decision = self.ideal("orc-handoff-claude-code-feature")
        decision["handoffs"][0]["owner"] = "codex"
        self.assertEqual(_checks(self.grade("orc-handoff-claude-code-feature", decision)), ["handoff.owner"])

    def test_owner_spelling_variants_pass(self) -> None:
        decision = self.ideal("orc-handoff-claude-code-feature")
        for spelling in ("Claude Code", "claude_code", "CLAUDE-CODE", "claude"):
            decision["handoffs"][0]["owner"] = spelling
            with self.subTest(spelling):
                self.assertEqual(self.grade("orc-handoff-claude-code-feature", decision), ())

    def test_parent_coding_itself_instead_of_handing_off_fails(self) -> None:
        decision = {"handoffs": [], "parent_edits": ["README.md"], "reply": "Fixed it."}
        self.assertEqual(
            _checks(self.grade("orc-handoff-korean-request", decision)),
            ["handoff", "parent_edits (parent coded instead of handing off)"],
        )
        both = self.ideal("orc-handoff-korean-request")
        both["parent_edits"] = ["README.md"]
        self.assertEqual(_checks(self.grade("orc-handoff-korean-request", both)), ["parent_edits (parent coded instead of handing off)"])

    def test_handoff_on_a_stale_choice_fails(self) -> None:
        decision = {"handoffs": [{"owner": "codex", "repository": "rlaope/oh-my-hermes"}], "parent_edits": [], "reply": "Sent to Codex."}
        self.assertEqual(_checks(self.grade("orc-nohandoff-stale-owner-choice", decision)), ["handoff (not allowed)"])

    def test_default_lane_may_edit_only_where_allowed(self) -> None:
        edit = {"handoffs": [], "parent_edits": ["docs/INSTALLATION.md"], "reply": "Fixed."}
        self.assertEqual(self.grade("orc-nohandoff-default-lane-typo", edit), ())
        self.assertEqual(_checks(self.grade("orc-nohandoff-question-only", edit)), ["parent_edits (not allowed)"])

    def test_wrong_repository_fails(self) -> None:
        decision = self.ideal("orc-repo-named-other-than-current")
        decision["handoffs"][0]["repository"] = "acme/web"
        self.assertEqual(_checks(self.grade("orc-repo-named-other-than-current", decision)), ["handoff.repository"])
        decision["handoffs"][0]["repository"] = "/work/web"
        self.assertEqual(_checks(self.grade("orc-repo-named-other-than-current", decision)), ["handoff.repository"])

    def test_repository_path_or_url_spelling_passes(self) -> None:
        decision = self.ideal("orc-repo-named-by-path")
        for spelling in ("/work/docs-site", "/work/docs-site/", "https://github.com/acme/docs-site.git"):
            decision["handoffs"][0]["repository"] = spelling
            with self.subTest(spelling):
                self.assertEqual(self.grade("orc-repo-named-by-path", decision), ())

    def test_invented_link_fails(self) -> None:
        decision = self.ideal("orc-links-no-invented-pr")
        decision["reply"] = "Codex is on it; the PR will be https://github.com/rlaope/oh-my-hermes/pull/3091."
        self.assertEqual(_checks(self.grade("orc-links-no-invented-pr", decision)), ["reply.links (not in observed evidence)"])

    def test_link_recalled_from_memory_fails_when_nothing_was_observed(self) -> None:
        decision = {"handoffs": [], "parent_edits": [], "reply": "Here: [cron docs](https://hermes-agent.nousresearch.com/docs/cron)"}
        self.assertEqual(_checks(self.grade("orc-links-none-observed", decision)), ["reply.links (not in observed evidence)"])

    def test_harness_recorded_evidence_counts_and_model_links_do_not(self) -> None:
        decision = {"handoffs": [], "parent_edits": [], "reply": "Here: https://hermes-agent.nousresearch.com/docs/cron"}
        self.assertEqual(self.grade("orc-links-none-observed", decision, ["https://hermes-agent.nousresearch.com/docs/cron/"]), ())
        decision["evidence_links"] = ["https://hermes-agent.nousresearch.com/docs/cron"]
        self.assertEqual(_checks(self.grade("orc-links-none-observed", decision)), ["reply.links (not in observed evidence)"])

    def test_observed_link_in_markdown_and_punctuation_passes(self) -> None:
        link = "https://github.com/rlaope/oh-my-hermes/pull/3102"
        for reply in (f"Merged: {link}.", f"Merged ([PR]({link}/)).", f"Merged: <{link}>", f"**{link}**"):
            decision = {"handoffs": [], "parent_edits": [], "reply": reply}
            with self.subTest(reply):
                self.assertEqual(self.grade("orc-links-pr-but-no-ci-run", decision), ())

    def test_missing_required_citation_fails(self) -> None:
        decision = {"handoffs": [], "parent_edits": [], "reply": "Yes, it merged."}
        self.assertEqual(_checks(self.grade("orc-links-pr-but-no-ci-run", decision)), ["reply.must_cite"])

    def test_over_budget_reply_fails(self) -> None:
        decision = {"handoffs": [], "parent_edits": [], "reply": " ".join(["word"] * 26)}
        self.assertEqual(_checks(self.grade("orc-budget-one-line-status", decision)), ["reply.word_budget"])
        decision["reply"] = " ".join(["word"] * 25)
        self.assertEqual(self.grade("orc-budget-one-line-status", decision), ())

    def test_malformed_decision_fails_rather_than_raising(self) -> None:
        for decision in ({}, {"handoffs": "codex", "reply": "ok"}, {"handoffs": [], "parent_edits": "x", "reply": ""}):
            with self.subTest(decision):
                self.assertTrue(self.grade("orc-handoff-codex-named-in-request", decision))

    def test_reply_link_extraction(self) -> None:
        text = "See (https://a.example/x), [b](https://b.example/y/) and https://a.example/x. Not http:/broken"
        self.assertEqual(orchestration.reply_links(text), ["https://a.example/x", "https://b.example/y"])
        tricky = (
            "_https://github.com/a/b/pull/1_ HTTPS://GitHub.com/a/b/pull/2 github.com/a/b/pull/9999 "
            "https://x.example/foo_bar 링크:https://github.com/a/b/pull/3102를"
        )
        self.assertEqual(orchestration.reply_links(tricky), [
            "https://github.com/a/b/pull/1",
            "https://github.com/a/b/pull/2",
            "https://github.com/a/b/pull/9999",
            "https://x.example/foo_bar",
            "https://github.com/a/b/pull/3102",
        ])

    def test_schemeless_or_uppercase_invented_link_fails(self) -> None:
        for reply in ("PR: github.com/rlaope/oh-my-hermes/pull/3091", "PR: HTTPS://github.com/rlaope/oh-my-hermes/pull/3091"):
            decision = self.ideal("orc-links-no-invented-pr")
            decision["reply"] = reply
            with self.subTest(reply):
                self.assertEqual(_checks(self.grade("orc-links-no-invented-pr", decision)), ["reply.links (not in observed evidence)"])

    def test_bare_host_invented_link_fails(self) -> None:
        decision = {"handoffs": [], "parent_edits": [], "reply": "It is at hermes-agent.nousresearch.com/docs/cron"}
        self.assertEqual(_checks(self.grade("orc-links-none-observed", decision)), ["reply.links (not in observed evidence)"])
        paths = {"handoffs": [], "parent_edits": ["docs/INSTALLATION.md"], "reply": "Fixed docs/INSTALLATION.md and README.md."}
        self.assertEqual(self.grade("orc-nohandoff-default-lane-typo", paths), ())

    def test_slash_joined_file_names_are_not_links(self) -> None:
        reply = "Fixed README.md/CHANGELOG.md and setup.py/pyproject.toml; see docs/INSTALLATION.md."
        self.assertEqual(orchestration.reply_links(reply), [])
        edit = {"handoffs": [], "parent_edits": ["README.md", "CHANGELOG.md"], "reply": reply}
        self.assertEqual(self.grade("orc-nohandoff-default-lane-typo", edit), ())
        self.assertEqual(orchestration.reply_links("docs at example.com/docs"), ["https://example.com/docs"])

    def test_www_host_with_a_file_extension_tld_is_still_a_link(self) -> None:
        self.assertEqual(orchestration.reply_links("see www.example.md"), ["https://www.example.md"])

    def test_wrapped_or_prefixed_bare_host_links_are_found(self) -> None:
        self.assertEqual(orchestration.reply_links("_example.com/x_"), ["https://example.com/x"])
        self.assertEqual(orchestration.reply_links("~~www.foo.com~~"), ["https://www.foo.com"])
        self.assertEqual(orchestration.reply_links("링크:github.com/a/b"), ["https://github.com/a/b"])

    def test_a_lone_scheme_is_not_a_link(self) -> None:
        self.assertEqual(orchestration.reply_links("links start with https:// as usual"), [])
        decision = {"handoffs": [], "parent_edits": [], "reply": "No link observed; normally it would start with https://"}
        self.assertEqual(self.grade("orc-links-none-observed", decision), ())

    def test_more_owner_spellings(self) -> None:
        for spelling, owner in (("Claude Code CLI", "claude-code"), ("OpenAI Codex", "codex"), ("코덱스", "codex"), ("클로드 코드", "claude-code")):
            with self.subTest(spelling):
                self.assertEqual(orchestration.normalize_owner(spelling), owner)

    def test_http_and_https_are_one_link(self) -> None:
        decision = {"handoffs": [], "parent_edits": [], "reply": "Merged: http://github.com/rlaope/oh-my-hermes/pull/3102"}
        self.assertEqual(self.grade("orc-links-pr-but-no-ci-run", decision), ())

    def test_library_names_in_prose_are_not_links(self) -> None:
        for prose in ("uses socket.io/client for the stream", "swap Node.js/Deno later", "see vue.js/react docs"):
            with self.subTest(prose):
                self.assertEqual(orchestration.reply_links(prose), [])
        self.assertEqual(orchestration.reply_links("socket.io/docs at https://socket.io/docs"), ["https://socket.io/docs"])
        self.assertEqual(orchestration.reply_links("docs.socket.io/v4"), ["https://docs.socket.io/v4"])

    def test_two_label_docs_hosts_on_any_tld_are_links(self) -> None:
        for reply in ("See nousresearch.ai/docs/cron", "See hermes-agent.io/docs/cron", "See example.xyz/guide"):
            decision = {"handoffs": [], "parent_edits": [], "reply": reply}
            with self.subTest(reply):
                self.assertEqual(_checks(self.grade("orc-links-none-observed", decision)), ["reply.links (not in observed evidence)"])
        for prose in ("uses socket.io/client for the stream", "ported from ASP.NET/Core"):
            decision = {"handoffs": [], "parent_edits": [], "reply": prose}
            with self.subTest(prose):
                self.assertEqual(self.grade("orc-links-none-observed", decision), ())

    def test_github_link_case_is_not_an_invented_link(self) -> None:
        decision = {"handoffs": [], "parent_edits": [], "reply": "Merged: https://github.com/RLAOPE/Oh-My-Hermes/pull/3102"}
        self.assertEqual(self.grade("orc-links-pr-but-no-ci-run", decision), ())

    def test_korean_particle_on_an_observed_link_passes(self) -> None:
        decision = {"handoffs": [], "parent_edits": [], "reply": "머지됐습니다: https://github.com/rlaope/oh-my-hermes/pull/3102를 보세요."}
        self.assertEqual(self.grade("orc-links-pr-but-no-ci-run", decision), ())


if __name__ == "__main__":
    unittest.main()
