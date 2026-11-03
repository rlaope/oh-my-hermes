from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _local_package import load_local_package

load_local_package()

from omh.goal_ledger import create_goal_ledger  # noqa: E402
from omh.goal_loop import (  # noqa: E402
    LOOP_STICKY_RULE_ATTACHMENT_SCHEMA,
    LOOP_STICKY_RULE_DEFAULT_GAP,
    LOOP_STICKY_RULE_DEFAULT_MAX_REPEATS,
    LOOP_STICKY_RULE_ONCE_MAX_REPEATS,
    LOOP_STICKY_RULE_REPEAT_MODES,
    LOOP_STICKY_RULE_SCHEMA,
    build_loop_status_card,
    create_loop_cycle,
    declare_sticky_rule,
    tick_loop_runtime,
    validate_loop_cycle,
    validate_loop_sticky_rule_attachment,
)
from omh.paths import resolve_paths  # noqa: E402


def _paths(tmp: str):
    return resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")


def _cycle(paths, **overrides):
    kwargs = {
        "goal_summary": "Keep a standing rule attached across a long loop",
        "goal_reframe": "Prepare bounded loop slices while a sticky rule stays re-attached under its policy.",
        "success_criteria": ["The sticky rule keeps re-attaching under its bounded policy"],
        "permission_profile": "handoff_only",
    }
    kwargs.update(overrides)
    return create_loop_cycle(paths, **kwargs)


class StickyRuleDeclarationTests(unittest.TestCase):
    def test_declare_creates_a_zero_state_rule(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            cycle = _cycle(paths)
            declared = declare_sticky_rule(
                paths,
                cycle["loop_id"],
                rule_id="never-claim-without-evidence",
                text="Never claim completion without observed evidence.",
            )

        self.assertEqual(len(declared["sticky_rules"]), 1)
        rule = declared["sticky_rules"][0]
        self.assertEqual(rule["schema_version"], LOOP_STICKY_RULE_SCHEMA)
        self.assertEqual(rule["rule_id"], "never-claim-without-evidence")
        self.assertEqual(rule["repeat_mode"], "after_gap")
        self.assertEqual(rule["repeat_gap"], LOOP_STICKY_RULE_DEFAULT_GAP)
        self.assertEqual(rule["max_repeats"], LOOP_STICKY_RULE_DEFAULT_MAX_REPEATS)
        self.assertEqual(rule["injected_count"], 0)
        self.assertIsNone(rule["last_injected_heartbeat"])
        self.assertEqual(validate_loop_cycle(declared), {"ok": True, "errors": []})

    def test_declare_rejects_bad_inputs(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            cycle = _cycle(paths)
            loop_id = cycle["loop_id"]

            with self.assertRaises(ValueError):
                declare_sticky_rule(paths, loop_id, rule_id="r1", text="")
            with self.assertRaises(ValueError):
                declare_sticky_rule(paths, loop_id, rule_id="r1", text="x", repeat_mode="always")
            with self.assertRaises(ValueError):
                declare_sticky_rule(paths, loop_id, rule_id="r1", text="x", repeat_gap=0)
            with self.assertRaises(ValueError):
                declare_sticky_rule(paths, loop_id, rule_id="r1", text="x", max_repeats=0)
            with self.assertRaises(ValueError):
                declare_sticky_rule(paths, loop_id, rule_id="r1", text="x", max_repeats=10_000)

    def test_once_mode_forces_a_max_repeat_budget_of_one(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            cycle = _cycle(paths)
            declared = declare_sticky_rule(
                paths,
                cycle["loop_id"],
                rule_id="r1",
                text="Stated once.",
                repeat_mode="once",
                max_repeats=50,
            )

        # A caller-supplied max_repeats never widens "once" past a budget of one.
        self.assertEqual(declared["sticky_rules"][0]["max_repeats"], LOOP_STICKY_RULE_ONCE_MAX_REPEATS)

    def test_redeclaring_the_same_rule_id_dedups_and_preserves_injection_state(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            cycle = _cycle(paths)
            loop_id = cycle["loop_id"]
            declare_sticky_rule(paths, loop_id, rule_id="r1", text="Original text.", repeat_gap=1)
            tick_loop_runtime(paths, loop_id)  # injects r1 once, injected_count -> 1

            redeclared = declare_sticky_rule(paths, loop_id, rule_id="r1", text="Updated text.", repeat_gap=5)

        self.assertEqual(len(redeclared["sticky_rules"]), 1)
        rule = redeclared["sticky_rules"][0]
        self.assertEqual(rule["text"], "Updated text.")
        self.assertEqual(rule["repeat_gap"], 5)
        self.assertEqual(rule["injected_count"], 1)
        self.assertIsNotNone(rule["last_injected_heartbeat"])


class StickyRuleAttachmentPolicyTests(unittest.TestCase):
    def test_once_mode_attaches_on_the_first_tick_then_never_again(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            cycle = _cycle(paths)
            loop_id = cycle["loop_id"]
            declare_sticky_rule(paths, loop_id, rule_id="r1", text="Stated once.", repeat_mode="once")

            attachments = [
                tick_loop_runtime(paths, loop_id)["sticky_rule_attachment"] for _ in range(5)
            ]

        rule_ids_per_tick = [[rule["rule_id"] for rule in attachment["rules"]] for attachment in attachments]
        self.assertEqual(rule_ids_per_tick, [["r1"], [], [], [], []])
        self.assertEqual(attachments[0]["rules"][0]["injected_count"], 1)

    def test_after_gap_mode_honors_the_interval_and_the_max_repeats_cap(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            cycle = _cycle(paths)
            loop_id = cycle["loop_id"]
            declare_sticky_rule(
                paths, loop_id, rule_id="r1", text="Restated on a gap.", repeat_mode="after_gap",
                repeat_gap=2, max_repeats=3,
            )

            attachments = [
                tick_loop_runtime(paths, loop_id)["sticky_rule_attachment"] for _ in range(8)
            ]

        fired_at_heartbeat = [a["heartbeat_count"] for a in attachments if a["rules"]]
        # First tick after declaration attaches immediately; then every 2 ticks
        # (repeat_gap=2), retiring once injected_count reaches max_repeats=3.
        self.assertEqual(fired_at_heartbeat, [1, 3, 5])
        injected_counts = [a["rules"][0]["injected_count"] for a in attachments if a["rules"]]
        self.assertEqual(injected_counts, [1, 2, 3])
        # No further attachment even though later ticks satisfy the gap again.
        self.assertEqual(attachments[7]["rules"], [])

    def test_multiple_rules_are_deduped_by_id_and_emitted_in_sorted_order(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            cycle = _cycle(paths)
            loop_id = cycle["loop_id"]
            declare_sticky_rule(paths, loop_id, rule_id="zzz-rule", text="Second rule.", repeat_gap=1)
            declare_sticky_rule(paths, loop_id, rule_id="aaa-rule", text="First rule.", repeat_gap=1)

            attachment = tick_loop_runtime(paths, loop_id)["sticky_rule_attachment"]

        self.assertEqual([rule["rule_id"] for rule in attachment["rules"]], ["aaa-rule", "zzz-rule"])

    def test_status_card_reads_do_not_advance_the_gap(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            cycle = _cycle(paths)
            loop_id = cycle["loop_id"]
            declare_sticky_rule(paths, loop_id, rule_id="r1", text="Stable across reads.", repeat_gap=3)
            tick_loop_runtime(paths, loop_id)

            reads = [build_loop_status_card(paths, loop_id)["sticky_rule_attachment"] for _ in range(4)]

        # Reading the status card any number of times between ticks changes
        # nothing: the gap is keyed to runtime.heartbeat_count, not to reads.
        for read in reads:
            self.assertEqual(read, reads[0])
        self.assertEqual(reads[0]["heartbeat_count"], 1)

    def test_a_stopped_tick_does_not_advance_sticky_rule_state(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            goal = create_goal_ledger(paths, "Objective with no recorded progress", ["Criterion"])
            cycle = _cycle(paths, linked_goal_id=goal["goal_id"])
            loop_id = cycle["loop_id"]
            declare_sticky_rule(paths, loop_id, rule_id="r1", text="Held across a stalled tick.", repeat_gap=1)

            first = tick_loop_runtime(paths, loop_id)
            second = tick_loop_runtime(paths, loop_id)  # stops on no_progress_cap; heartbeat does not advance

        self.assertEqual(first["runtime"]["heartbeat_count"], 1)
        self.assertEqual(first["sticky_rule_attachment"]["rules"][0]["injected_count"], 1)
        self.assertEqual(second["runtime"]["stop_ladder"]["stop_reason"], "no_progress_cap")
        self.assertEqual(second["next_action"], "replan_stuck_loop_once")
        self.assertEqual(second["runtime"]["heartbeat_count"], 1)
        # A stopped tick recomputes nothing: the attachment carried over from
        # the last real tick, byte-identical, rather than being re-derived.
        self.assertEqual(second["sticky_rule_attachment"], first["sticky_rule_attachment"])
        self.assertEqual(second["sticky_rules"][0]["injected_count"], 1)


class StickyRuleAttachmentSchemaTests(unittest.TestCase):
    def test_empty_attachment_on_a_freshly_started_loop_is_schema_valid(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            cycle = _cycle(paths)
            card = build_loop_status_card(paths, cycle["loop_id"])

        attachment = card["sticky_rule_attachment"]
        self.assertEqual(attachment["schema_version"], LOOP_STICKY_RULE_ATTACHMENT_SCHEMA)
        self.assertEqual(attachment["rules"], [])
        self.assertEqual(validate_loop_sticky_rule_attachment(attachment), [])

    def test_populated_attachment_round_trips_through_the_validator(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            cycle = _cycle(paths)
            loop_id = cycle["loop_id"]
            declare_sticky_rule(paths, loop_id, rule_id="r1", text="Schema-checked rule.", repeat_gap=1)
            card = build_loop_status_card(paths, loop_id)
            self.assertEqual(card["sticky_rule_attachment"]["rules"], [])  # no tick yet

            ticked = tick_loop_runtime(paths, loop_id)
            card_after_tick = build_loop_status_card(paths, loop_id)

        self.assertEqual(validate_loop_sticky_rule_attachment(ticked["sticky_rule_attachment"]), [])
        self.assertEqual(validate_loop_sticky_rule_attachment(card_after_tick["sticky_rule_attachment"]), [])
        self.assertEqual(card_after_tick["sticky_rule_attachment"], ticked["sticky_rule_attachment"])

    def test_validator_rejects_duplicate_rule_ids_and_out_of_order_entries(self) -> None:
        base = {
            "schema_version": LOOP_STICKY_RULE_ATTACHMENT_SCHEMA,
            "heartbeat_count": 1,
            "rules": [
                {"rule_id": "b", "text": "B.", "repeat_mode": "once", "injected_count": 1, "max_repeats": 1},
                {"rule_id": "a", "text": "A.", "repeat_mode": "once", "injected_count": 1, "max_repeats": 1},
            ],
            "claim_boundary": "x",
        }
        errors = validate_loop_sticky_rule_attachment(base)
        self.assertTrue(any("out of rule_id order" in error for error in errors))

        duplicate = {
            **base,
            "rules": [
                {"rule_id": "a", "text": "A.", "repeat_mode": "once", "injected_count": 1, "max_repeats": 1},
                {"rule_id": "a", "text": "A2.", "repeat_mode": "once", "injected_count": 1, "max_repeats": 1},
            ],
        }
        errors = validate_loop_sticky_rule_attachment(duplicate)
        self.assertTrue(any("duplicates an earlier entry" in error for error in errors))

    def test_validator_rejects_wrong_schema_version_and_missing_claim_boundary(self) -> None:
        errors = validate_loop_sticky_rule_attachment({"schema_version": "wrong/v1", "heartbeat_count": 0, "rules": []})
        self.assertTrue(any("schema_version" in error for error in errors))
        self.assertTrue(any("claim_boundary" in error for error in errors))

    def test_repeat_modes_are_the_documented_pair(self) -> None:
        self.assertEqual(LOOP_STICKY_RULE_REPEAT_MODES, ("once", "after_gap"))


if __name__ == "__main__":
    unittest.main()
