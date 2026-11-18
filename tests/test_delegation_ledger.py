"""The delegation ledger: what Hermes' hooks said, kept as ids, order and status words, and nothing else."""

from __future__ import annotations

import json
import os
import time
import unittest

from _local_package import load_local_package

load_local_package()

from _delegation_state import PARENT, dispatched, homes, route, start, stop  # noqa: E402
from omh.plugin_bundle.omh import delegation_ledger  # noqa: E402
from omh.plugin_bundle.omh.delegation_ledger import (  # noqa: E402
    CLOSED_LIMIT,
    LEDGER_CHILD_LIMIT,
    LEDGER_MAX_AGE_SECONDS,
    child_title,
    ledger_key,
    ledger_path,
    note_posted,
    observe_delegate_call,
    posted_fingerprint,
    posted_record,
    prune_ledgers,
    read_ledger,
    title_from_goal,
    with_unjoined_stop,
)

NOW = 1_800_000_000.0
GOALS = ("Refresh HUD docs for the graph flag", "Polish HUD CLI output", "TASK: Update HUD tests\nVERIFY: ...")


class BindingTests(unittest.TestCase):
    def test_a_background_call_gives_each_child_its_call_task_index_and_delegation(self) -> None:
        with homes() as home:
            for index, goal in enumerate(GOALS):
                self.assertTrue(start(home, f"child-{index}", f"sa-{index}-0000000{index}", goal, now=NOW + index))
            self.assertTrue(dispatched(home, ["sa-0-00000000", "sa-1-00000001", "sa-2-00000002"], now=NOW + 3))
            self.assertTrue(stop(home, "child-1", now=NOW + 65))
            record = read_ledger(home.omh, PARENT)
            children = {child["subagent_id"]: child for child in record["children"]}
            self.assertEqual(
                [(child["task_index"], child["delegation_id"], child["call_id"]) for child in record["children"]],
                [(0, "deleg-1", "call-deleg-1"), (1, "deleg-1", "call-deleg-1"), (2, "deleg-1", "call-deleg-1")],
            )
            self.assertEqual(children["sa-1-00000001"]["stop"]["status"], "completed")
            self.assertEqual(children["sa-1-00000001"]["stop"]["duration_ms"], 62_000)
            self.assertNotIn("stop", children["sa-0-00000000"])
            self.assertEqual(record["calls"][0]["mode"], "background")

    def test_a_synchronous_call_binds_the_children_it_started_in_build_order(self) -> None:
        with homes() as home:
            for index in range(2):
                start(home, f"child-{index}", f"sa-{index}-x", "goal", now=NOW + index)
            result = {"results": [{"task_index": 0, "status": "completed"}, {"task_index": 1, "status": "failed"}]}
            self.assertTrue(observe_delegate_call(
                {"tool_name": "delegate_task", "result": json.dumps(result), "session_id": PARENT,
                 "tool_call_id": "sync-1", "turn_id": "turn-3", "duration_ms": 5_000, **home.hooks()},
                now=NOW + 3,
            ))
            record = read_ledger(home.omh, PARENT)
            self.assertEqual([child.get("task_index") for child in record["children"]], [0, 1])
            self.assertEqual(record["calls"][0]["mode"], "sync")

    def test_a_synchronous_call_whose_children_do_not_count_up_binds_none(self) -> None:
        with homes() as home:
            start(home, "child-0", "sa-0-x", "goal", now=NOW)
            result = {"results": [{"task_index": 0}, {"task_index": 1}]}
            observe_delegate_call(
                {"tool_name": "delegate_task", "result": json.dumps(result), "session_id": PARENT,
                 "tool_call_id": "sync-1", "turn_id": "turn-3", "duration_ms": 5_000, **home.hooks()},
                now=NOW + 1,
            )
            self.assertNotIn("task_index", read_ledger(home.omh, PARENT)["children"][0])

    def test_a_refused_or_unreadable_result_records_no_call(self) -> None:
        with homes() as home:
            start(home, "child-0", "sa-0-x", "goal", now=NOW)
            for result in ("not json", json.dumps({"error": "Delegation spawning is paused."})):
                self.assertFalse(observe_delegate_call(
                    {"tool_name": "delegate_task", "result": result, "session_id": PARENT, **home.hooks()},
                    now=NOW + 1,
                ))
            self.assertEqual(read_ledger(home.omh, PARENT)["calls"], [])

    def test_an_unjoined_stop_joins_a_child_that_has_none_and_the_newest_one_wins(self) -> None:
        """`with_unjoined_stop`. Mutations: let an unjoined stop replace a child's own; take the oldest stop."""
        own = {"status": "completed", "observed_at": NOW + 5, "duration_ms": 5_000}
        child = {"child_session_id": "child-0", "started_at": NOW, "stop": own}
        stops = [{"child_session_id": "child-0", "status": "failed", "observed_at": NOW + 9},
                 {"child_session_id": "child-0b", "status": "interrupted", "observed_at": NOW + 8}]
        self.assertIs(with_unjoined_stop(child, stops, ["child-0b"])["stop"], own, "a child's own stop is kept")
        open_child = {"child_session_id": "child-0", "started_at": NOW}
        self.assertEqual(with_unjoined_stop(open_child, stops, ["child-0b"])["stop"],
                         {"status": "failed", "observed_at": NOW + 9, "duration_ms": None})
        self.assertEqual(with_unjoined_stop(open_child, list(reversed(stops)), ["child-0b"])["stop"]["status"],
                         "failed", "the newest, whatever the order")
        self.assertNotIn("stop", with_unjoined_stop(open_child, stops[1:]), "a continuation is named only by `later`")

    def test_a_stop_the_ledger_cannot_join_is_kept_apart_not_guessed_onto_a_child(self) -> None:
        with homes() as home:
            start(home, "child-0", "sa-0-x", "goal", now=NOW)
            stop(home, "child-0-continued", now=NOW + 10)
            record = read_ledger(home.omh, PARENT)
            self.assertNotIn("stop", record["children"][0])
            self.assertEqual(record["unjoined_stops"][0]["child_session_id"], "child-0-continued")


class ResumeTests(unittest.TestCase):
    """Hermes 0.23.2 `delegation.auto_resume` (and `action='continue'`) starts a stopped child again under the same
    subagent id and session, and that run's own stop is the one that counts."""

    def test_a_resumed_child_drops_its_earlier_stop_and_takes_the_resumed_runs(self) -> None:
        """Mutation: keep refusing a repeated start, or keep the old stop on a resume."""
        goal = "Edit file 4 [dag:run1/n4]"
        with homes() as home:
            self.assertTrue(start(home, "child-a", "sa-0-aaaa", goal, now=NOW))
            self.assertTrue(stop(home, "child-a", "error", now=NOW + 60))
            self.assertTrue(start(home, "child-a", "sa-0-aaaa", goal, now=NOW + 3600))
            waiting = read_ledger(home.omh, PARENT)["children"]
            self.assertTrue(stop(home, "child-a", "completed", now=NOW + 3700))
            record = read_ledger(home.omh, PARENT)
        self.assertEqual(len(waiting), 1)
        self.assertNotIn("stop", waiting[0])
        self.assertEqual((waiting[0]["resumed_at"], waiting[0]["resumes"], waiting[0]["started_at"]),
                         (NOW + 3600, 1, NOW))
        self.assertEqual(record["children"][0]["stop"]["status"], "completed")
        self.assertEqual(record["unjoined_stops"], [])

    def test_a_repeated_start_under_another_session_is_still_refused(self) -> None:
        """Mutation: take any repeated subagent id as a resume."""
        with homes() as home:
            start(home, "child-a", "sa-0-aaaa", "goal", now=NOW)
            self.assertFalse(start(home, "child-b", "sa-0-aaaa", "goal", now=NOW + 5))
            children = read_ledger(home.omh, PARENT)["children"]
        self.assertEqual([(c["child_session_id"], "resumed_at" in c) for c in children], [("child-a", False)])

    def test_a_resumed_child_takes_only_a_stop_from_its_resumed_run(self) -> None:
        """Mutation: let an unjoined stop older than the resume answer for the resumed run."""
        child = {"child_session_id": "child-0", "started_at": NOW, "resumed_at": NOW + 100}
        old = [{"child_session_id": "child-0", "status": "error", "observed_at": NOW + 50}]
        self.assertNotIn("stop", with_unjoined_stop(child, old))
        new = old + [{"child_session_id": "child-0", "status": "completed", "observed_at": NOW + 150}]
        self.assertEqual(with_unjoined_stop(child, new)["stop"]["status"], "completed")

    def test_the_resume_marks_survive_a_read_back(self) -> None:
        with homes() as home:
            start(home, "child-a", "sa-0-aaaa", "goal", now=NOW)
            stop(home, "child-a", "error", now=NOW + 1)
            start(home, "child-a", "sa-0-aaaa", "goal", now=NOW + 2)
            start(home, "child-a", "sa-0-aaaa", "goal", now=NOW + 3)
            child = read_ledger(home.omh, PARENT)["children"][0]
        self.assertEqual((child["resumed_at"], child["resumes"]), (NOW + 3, 2))


class HookEntryTests(unittest.TestCase):
    def test_the_registered_hooks_write_the_ledger(self) -> None:
        from omh.plugin_bundle.omh.hooks import session_hooks, tool_hooks

        with homes() as home:
            session_hooks.subagent_start(
                parent_session_id=PARENT, parent_turn_id="turn-3", parent_subagent_id=None,
                child_session_id="child-0", child_subagent_id="sa-0-1a2b3c4d", child_role="leaf",
                child_goal="Refresh docs", **home.hooks(),
            )
            blocked = json.dumps({"status": "dispatched", "delegation_id": "deleg-x", "subagent_ids": ["sa-0-1a2b3c4d"]})
            tool_hooks.post_tool_call(tool_name="delegate_task", args={}, result=blocked, session_id=PARENT,
                                      tool_call_id="call-0", turn_id="turn-3", status="blocked", **home.hooks())
            self.assertEqual(read_ledger(home.omh, PARENT)["calls"], [], "a blocked call is not Hermes' dispatch")
            handle = json.dumps({"status": "dispatched", "mode": "background", "count": 1,
                                 "delegation_id": "deleg-1", "goals": ["Refresh docs"],
                                 "subagent_ids": ["sa-0-1a2b3c4d"]})
            tool_hooks.post_tool_call(tool_name="delegate_task", args={}, result=handle, session_id=PARENT,
                                      tool_call_id="call-1", turn_id="turn-3", status="ok", **home.hooks())
            session_hooks.subagent_stop(
                parent_session_id=PARENT, parent_turn_id="turn-3", child_session_id="child-0", child_role="leaf",
                child_summary="done", child_status="completed", tool_call_history=[], duration_ms=1_000,
                **home.hooks(),
            )
            child = read_ledger(home.omh, PARENT)["children"][0]
            self.assertEqual((child["task_index"], child["delegation_id"], child["stop"]["status"]),
                             (0, "deleg-1", "completed"))


class RecordTests(unittest.TestCase):
    def test_no_goal_summary_or_prompt_text_is_written(self) -> None:
        with homes() as home:
            for index, goal in enumerate(GOALS):
                start(home, f"child-{index}", f"sa-{index}-x", goal, now=NOW + index)
            stop(home, "child-0", now=NOW + 10)
            stored = ledger_path(home.omh, PARENT).read_text(encoding="utf-8")
            for text in (*GOALS, "Refresh HUD docs", "Update HUD tests", "SECRET SUMMARY TEXT", "VERIFY"):
                self.assertNotIn(text, stored)
            if os.name == "posix":  # Windows keeps no POSIX mode bits to check
                self.assertEqual(oct(os.stat(ledger_path(home.omh, PARENT)).st_mode & 0o777), "0o600")

    def test_titles_stay_in_this_process(self) -> None:
        with homes() as home:
            start(home, "child-2", "sa-2-x", GOALS[2], now=NOW)
            self.assertEqual(child_title("sa-2-x"), "Update HUD tests")
        self.assertEqual(title_from_goal("Refresh docs [omh-team:hud/docs/attempt-1]\nmore"), "Refresh docs")
        self.assertEqual(title_from_goal("Export API [dag:export/api]"), "Export API")
        self.assertEqual(title_from_goal("Export API [dag:export/api]. Please hurry"), "Export API. Please hurry")
        # Goals handed out before an update open with their marker.
        self.assertEqual(title_from_goal("[omh-team:hud/docs/attempt-1] Refresh docs\nmore"), "Refresh docs")
        self.assertEqual(title_from_goal("[dag:export/api] Export API"), "Export API")
        self.assertEqual(title_from_goal("\n\n  TASK:  Port   the module  "), "Port the module")
        self.assertEqual(title_from_goal(7), "")

    def test_the_route_is_the_one_this_session_recorded_before_the_child_started(self) -> None:
        with homes() as home:
            route(home, "deep", "claude-opus-5-5", "high", written_at=NOW - 10, session="another-session")
            route(home, "writing", "claude-opus-5-5", "medium", written_at=NOW - 20)
            route(home, "quick", "glm-5.3-flash", "low", written_at=NOW + 50)  # written after the start
            start(home, "child-0", "sa-0-x", "goal", now=NOW)
            snapshot = read_ledger(home.omh, PARENT)["children"][0]["route"]
            self.assertEqual((snapshot["category"], snapshot["wire_model"]), ("writing", "claude-opus-5-5"))

    def test_a_stale_route_is_no_route(self) -> None:
        with homes() as home:
            route(home, "writing", "claude-opus-5-5", "medium", written_at=NOW - 3_600)
            start(home, "child-0", "sa-0-x", "goal", now=NOW)
            self.assertEqual(read_ledger(home.omh, PARENT)["children"][0]["route"], {})

    def test_a_nested_child_lands_in_its_root_conversation(self) -> None:
        with homes() as home:
            start(home, "child-0", "sa-0-orch", "orchestrate", now=NOW)
            start(home, "grandchild-0", "sa-0-leaf", "leaf work", parent="child-0", parent_subagent="sa-0-orch",
                  now=NOW + 1)
            self.assertEqual(len(read_ledger(home.omh, PARENT)["children"]), 2)
            # A process that never saw the orchestrator start follows `_delegate_from` in state.db.
            delegation_ledger._roots.clear()
            home.session("child-0", "claude-opus-5-5", parent=PARENT)
            start(home, "grandchild-1", "sa-1-leaf", "leaf work", parent="child-0", parent_subagent="sa-0-orch",
                  now=NOW + 2)
            self.assertEqual(len(read_ledger(home.omh, PARENT)["children"]), 3)
            self.assertIsNone(read_ledger(home.omh, "child-0"))

    def test_the_record_is_bounded(self) -> None:
        with homes() as home:
            for index in range(LEDGER_CHILD_LIMIT + 5):
                start(home, f"child-{index}", f"sa-{index}", "goal", now=NOW + index)
            children = read_ledger(home.omh, PARENT)["children"]
            self.assertEqual(len(children), LEDGER_CHILD_LIMIT)
            self.assertEqual(children[0]["subagent_id"], "sa-5")
            start(home, "late", "sa-late", "goal", now=NOW + 2 * 24 * 3600)
            self.assertEqual([child["subagent_id"] for child in read_ledger(home.omh, PARENT)["children"]],
                             ["sa-late"])

    def test_a_malformed_record_reads_as_none_and_is_replaced_by_the_next_write(self) -> None:
        with homes() as home:
            path = ledger_path(home.omh, PARENT)
            path.parent.mkdir(parents=True)
            for garbage in ("{", "[]", json.dumps({"schema_version": "delegation_ledger/v0"}),
                            json.dumps({"schema_version": "delegation_ledger/v1", "session_id": "someone-else"})):
                path.write_text(garbage, encoding="utf-8")
                self.assertIsNone(read_ledger(home.omh, PARENT))
            self.assertTrue(start(home, "child-0", "sa-0-x", "goal", now=NOW))
            self.assertEqual(len(read_ledger(home.omh, PARENT)["children"]), 1)

    def test_a_record_behind_a_symlink_is_neither_read_nor_written(self) -> None:
        with homes() as home:
            elsewhere = home.omh / "elsewhere.json"
            elsewhere.write_text("{}", encoding="utf-8")
            path = ledger_path(home.omh, PARENT)
            path.parent.mkdir(parents=True)
            path.symlink_to(elsewhere)
            self.assertFalse(start(home, "child-0", "sa-0-x", "goal", now=NOW))
            self.assertEqual(elsewhere.read_text(encoding="utf-8"), "{}")

    def test_the_posted_fingerprint_round_trips(self) -> None:
        with homes() as home:
            self.assertTrue(note_posted(home.omh, PARENT, "e" * 64, now=NOW), "a team that has sent nothing yet")
            self.assertEqual(posted_fingerprint(home.omh, PARENT), "e" * 64)
            start(home, "child-0", "sa-0-x", "goal", now=NOW)
            self.assertTrue(note_posted(home.omh, PARENT, "f" * 64, now=NOW))
            self.assertEqual(posted_fingerprint(home.omh, PARENT), "f" * 64)

    def test_the_posted_moment_round_trips_and_a_tampered_one_is_dropped(self) -> None:
        with homes() as home:
            start(home, "child-0", "sa-0-x", "goal", now=NOW)
            self.assertTrue(note_posted(home.omh, PARENT, "f" * 64, moment_name="end", phase="closed",
                                        counts="1/1/0/0/", closed=["a" * 16, "b" * 16], now=NOW))
            posted = posted_record(home.omh, PARENT)
            self.assertEqual(
                {key: posted[key] for key in ("moment", "phase", "counts", "closed")},
                {"moment": "end", "phase": "closed", "counts": "1/1/0/0/", "closed": ["a" * 16, "b" * 16]},
            )
            path = ledger_path(home.omh, PARENT)
            raw = json.loads(path.read_text(encoding="utf-8"))
            raw["posted"].update(moment="boxes", phase="half", closed=["c" * 99, 7] * 300)
            path.write_text(json.dumps(raw), encoding="utf-8")
            posted = posted_record(home.omh, PARENT)
            self.assertEqual((posted["moment"], posted["phase"]), ("", ""))
            self.assertEqual(posted["closed"], ["c" * 16] * CLOSED_LIMIT)

    def test_a_stored_dag_binding_keeps_only_ids_omh_mints(self) -> None:
        """Mutation: check a stored binding through the goal reader, by a prefix match, or not at all."""
        with homes() as home:
            for index, node in enumerate(("api", "ui", "docs")):
                start(home, f"child-{index}", f"sa-{index}-x", f"Node {node} [dag:feat/{node}]", now=NOW + index)
            path = ledger_path(home.omh, PARENT)
            raw = json.loads(path.read_text(encoding="utf-8"))
            raw["children"][1]["dag"] = {"run": "feat", "node": "api] x [dag:feat/ui"}
            raw["children"][2]["dag"] = {"run": "feat", "node": "Docs"}
            path.write_text(json.dumps(raw), encoding="utf-8")
            bound = [child.get("dag") for child in read_ledger(home.omh, PARENT)["children"]]
        self.assertEqual(bound, [{"run": "feat", "node": "api"}, None, None])

    def test_records_no_hook_wrote_for_a_day_are_removed_and_their_locks_stay(self) -> None:
        with homes() as home:
            start(home, "child-0", "sa-0-x", "goal", now=NOW)
            start(home, "child-9", "sa-9-x", "goal", parent="other-parent", now=NOW)
            old = ledger_path(home.omh, "other-parent")
            lock = old.with_name(f".{old.name}.lock")
            stale = time.time() - LEDGER_MAX_AGE_SECONDS - 60
            os.utime(old, (stale, stale))
            self.assertEqual(prune_ledgers(home.omh), 1)
            self.assertFalse(old.exists())
            self.assertTrue(lock.exists(), "a lock file stays: a waiter may hold it")
            self.assertIsNotNone(read_ledger(home.omh, PARENT), "a record written today stays")
            self.assertEqual(prune_ledgers(home.omh), 0)

    def test_the_file_key_is_the_team_records_key(self) -> None:
        from omh.workflows.team import session_key

        for session in (PARENT, "agent:main:discord:dm:123", "한글 세션", ""):
            self.assertEqual(ledger_key(session), session_key(session))


if __name__ == "__main__":
    unittest.main()
