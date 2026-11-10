"""The delegation graph: every field from a record, `?` where there is none (a title names its node instead), edges
only where recorded."""

from __future__ import annotations

import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from _local_package import load_local_package

load_local_package()

from _delegation_state import PARENT, dispatched, homes, route, start, stop  # noqa: E402
from omh.plugin_bundle.omh.delegation_graph import (  # noqa: E402
    CHILD_STALE_SECONDS,
    GRAPH_LINGER_SECONDS,
    GRAPH_NODE_LIMIT,
    build_delegation_graph,
    fanout_graph,
    graph_fingerprint,
    RUN_USAGE_CHILD_LIMIT,
    graph_segments,
    run_usage,
    session_usage,
    team_unit_state,
)
from omh.plugin_bundle.omh.delegation_ledger import ledger_key  # noqa: E402

NOW = 1_800_000_000.0


def built(home, **options) -> dict:
    return build_delegation_graph(home.omh, home.hermes, PARENT, now=options.pop("now", NOW + 100), **options)


def node(graph: dict, title: str) -> dict:
    return next(item for item in graph["nodes"] if item.get("title") == title)


def three_lanes(home, *, routed: bool = True) -> None:
    """Three lanes routed writing / quick / deep, dispatched in one call, as ulw-work does it."""
    home.session(PARENT, "claude-opus-5-5", effort="high")
    lanes = [("Refresh HUD docs", "writing", "claude-opus-5-5", "medium"),
             ("Polish HUD CLI", "quick", "glm-5.3-flash", "low"),
             ("Update HUD tests", "deep", "claude-opus-5-5", "high")]
    for index, (title, category, model, effort) in enumerate(lanes):
        if routed:
            route(home, category, model, effort, written_at=NOW + index - 0.5)
        start(home, f"child-{index}", f"sa-{index}", title, now=NOW + index)
        home.session(f"child-{index}", model, parent=PARENT, effort=effort, started=NOW + index)
    dispatched(home, ["sa-0", "sa-1", "sa-2"], now=NOW + 3)


class FieldEvidenceTests(unittest.TestCase):
    def test_the_category_is_the_recorded_route_while_the_observed_model_matches_it(self) -> None:
        with homes() as home:
            three_lanes(home)
            graph = built(home)
            self.assertEqual(
                [(item["title"], item["category"], item["model"], item["effort"]) for item in graph["nodes"][1:]],
                [("Refresh HUD docs", "writing", "claude-opus-5-5", "medium"),
                 ("Polish HUD CLI", "quick", "glm-5.3-flash", "low"),
                 ("Update HUD tests", "deep", "claude-opus-5-5", "high")],
            )
            self.assertEqual({item["category_source"] for item in graph["nodes"][1:]}, {"route_provenance"})
            self.assertEqual([item["session_tail"] for item in graph["nodes"][1:]], ["child-0", "child-1", "child-2"],
                             "each lane names its child the way the native HUD rows do")

    def test_a_route_the_child_did_not_run_is_no_category(self) -> None:
        with homes() as home:
            home.session(PARENT, "claude-opus-5-5")
            route(home, "deep", "claude-opus-5-5", "high", written_at=NOW - 1)
            start(home, "child-0", "sa-0", "Lane", now=NOW)
            home.session("child-0", "gpt-6.1-sol", parent=PARENT)  # a provider fallback ran something else
            lane = node(built(home), "Lane")
            self.assertEqual((lane["category"], lane["category_source"], lane["model"]),
                             ("?", "route_model_mismatch", "gpt-6.1-sol"))

    def test_an_auxiliary_call_does_not_name_the_childs_model(self) -> None:
        # Hermes left the child row's model empty, so the usage rows name it. A compression call on the aux route's
        # model is a call (the child is running), but not the model that answered.
        for has_task, expected in ((True, ("claude-opus-5-5", "deep", "route_provenance")),
                                   (False, ("?", "?", "model_not_observed"))):
            with self.subTest(task_column=has_task), homes() as home:
                home.session(PARENT, "claude-opus-5-5")
                route(home, "deep", "claude-opus-5-5", "high", written_at=NOW - 1)
                start(home, "child-0", "sa-0", "Lane", now=NOW)
                home.session("child-0", "", parent=PARENT, started=NOW)
                home.usage("child-0", "claude-opus-5-5", last_seen=NOW + 90)
                if has_task:
                    home.execute("ALTER TABLE session_model_usage ADD COLUMN task TEXT NOT NULL DEFAULT ''")
                    home.execute("INSERT INTO session_model_usage (session_id, model, task, api_call_count, last_seen) "
                                 "VALUES ('child-0', 'gemini-3-flash', 'compression', 1, ?)", (NOW + 95,))
                else:  # a state.db before Hermes split auxiliary calls out cannot tell one, so both rows count
                    home.usage("child-0", "gemini-3-flash", last_seen=NOW + 95)
                lane = node(built(home), "Lane")
                self.assertEqual((lane["model"], lane["category"], lane["category_source"]), expected)
                self.assertEqual(lane["state"], "running")

    def test_inherit_only_by_equality_with_the_parents_recorded_model(self) -> None:
        with homes() as home:
            home.session(PARENT, "claude-opus-5-5")
            start(home, "child-0", "sa-0", "Same model", now=NOW)
            home.session("child-0", "claude-opus-5-5", parent=PARENT)
            start(home, "child-1", "sa-1", "Other model", now=NOW + 1)
            home.session("child-1", "glm-5.3-flash", parent=PARENT)
            graph = built(home)
            self.assertEqual(node(graph, "Same model")["category"], "inherit")
            self.assertEqual(node(graph, "Other model")["category"], "?")

    def test_the_model_is_never_taken_from_current_config(self) -> None:
        with homes() as home:
            (home.hermes / "config.yaml").write_text("delegation:\n  model: claude-fable-5-1\n", encoding="utf-8")
            route(home, "deep", "claude-fable-5-1", "high", written_at=NOW - 1)
            start(home, "child-0", "sa-0", "Not started yet", now=NOW)
            lane = node(built(home), "Not started yet")
            self.assertEqual((lane["model"], lane["category"], lane["state"]), ("?", "?", "dispatched"))

    def test_the_model_hermes_recorded_at_dispatch_fills_in_before_the_child_row_exists(self) -> None:
        with homes() as home:
            start(home, "child-0", "sa-0", "Pinned lane", now=NOW)
            dispatched(home, ["sa-0"], delegation_id="deleg-9", now=NOW + 1)
            home.delegation("deleg-9", ["Pinned lane"], model="glm-5.3-flash")
            self.assertEqual(node(built(home), "Pinned lane")["model"], "glm-5.3-flash")

    def test_titles_come_from_hermes_records_when_this_process_did_not_see_the_start(self) -> None:
        from omh.plugin_bundle.omh import delegation_ledger

        with homes() as home:
            start(home, "child-0", "sa-0", "goal seen here", now=NOW)
            start(home, "child-1", "sa-1", "goal seen here too", now=NOW + 1)
            dispatched(home, ["sa-0", "sa-1"], delegation_id="deleg-7", now=NOW + 2)
            delegation_ledger._titles.clear()
            home.delegation("deleg-7", ["TASK: First lane\nSCOPE: x", "Second lane"])
            home.opener("child-1", "Opener says otherwise")
            titles = [item["title"] for item in built(home)["nodes"][1:]]
            self.assertEqual(titles, ["First lane", "Second lane"])
            start(home, "child-2", "sa-2", "x", now=NOW + 3)
            delegation_ledger._titles.clear()
            home.opener("child-2", "From the opener")
            self.assertEqual(built(home)["nodes"][-1]["title"], "From the opener")
            start(home, "20261022_101500_7c41e9a2", "sa-3", "x", now=NOW + 4)
            delegation_ledger._titles.clear()
            self.assertEqual(built(home)["nodes"][-1]["title"], "session 7c41e9a2",
                             "no record names it: its short session id, as its card says it, never `?`")


class StateTests(unittest.TestCase):
    def test_states_from_stops_model_calls_and_session_rows(self) -> None:
        with homes() as home:
            three_lanes(home)
            home.usage("child-0", "claude-opus-5-5", last_seen=NOW + 90)  # running
            home.usage("child-1", "glm-5.3-flash", last_seen=NOW + 60)
            stop(home, "child-1", now=NOW + 62)  # completed after a model call
            stop(home, "child-2", now=NOW + 70)  # completed with no model call at all
            graph = built(home)
            self.assertEqual(
                [(item["state"], item["status"]) for item in graph["nodes"][1:]],
                [("running", "running"), ("done", "done"), ("failed", "no model call")],
            )
            self.assertAlmostEqual(node(graph, "Polish HUD CLI")["elapsed_seconds"], 62.0)

    def test_an_unread_usage_table_never_turns_a_completed_child_into_a_failure(self) -> None:
        with homes() as home:
            three_lanes(home)
            home.usage("child-1", "glm-5.3-flash", last_seen=NOW + 60)
            stop(home, "child-1", now=NOW + 62)
            stop(home, "child-2", now=NOW + 70)  # completed with no model call
            home.execute("ALTER TABLE session_model_usage RENAME TO session_model_usage_gone")
            graph = built(home)
            self.assertEqual([(item["state"], item["status"]) for item in graph["nodes"][2:]],
                             [("done", "done"), ("done", "done")],
                             "with no usage table read, nothing says there was no model call")

    def test_a_child_with_no_news_is_unknown_never_running(self) -> None:
        with homes() as home:
            start(home, "child-0", "sa-0", "Quiet", now=NOW)
            home.session("child-0", "m", parent=PARENT)
            home.usage("child-0", "m", last_seen=NOW + 5)
            later = NOW + CHILD_STALE_SECONDS + 60
            start(home, "child-1", "sa-1", "Fresh", now=later - 10)  # keeps the graph from settling
            lane = node(built(home, now=later), "Quiet")
            self.assertEqual((lane["state"], lane["status"]), ("unknown", "no news"))

    def test_a_recent_auxiliary_call_keeps_a_child_running(self) -> None:
        # The child's own last call is older than the stale window, but it has compressed its context since: an
        # auxiliary call is still the child at work.
        later = NOW + CHILD_STALE_SECONDS + 600
        with homes() as home:
            start(home, "child-0", "sa-0", "Long lane", now=NOW)
            home.session("child-0", "claude-opus-5-5", parent=PARENT, started=NOW)
            home.usage("child-0", "claude-opus-5-5", last_seen=NOW + 90)
            home.execute("ALTER TABLE session_model_usage ADD COLUMN task TEXT NOT NULL DEFAULT ''")
            home.execute("INSERT INTO session_model_usage (session_id, model, task, api_call_count, last_seen) "
                         "VALUES ('child-0', 'gemini-3-flash', 'compression', 1, ?)", (later - 60,))
            lane = node(built(home, now=later), "Long lane")
            self.assertEqual((lane["state"], lane["status"], lane["model"]), ("running", "running", "claude-opus-5-5"))

    def test_a_segment_closed_for_compaction_is_unknown_never_done(self) -> None:
        with homes() as home:
            start(home, "child-0", "sa-0", "Compacted", now=NOW)
            home.session("child-0", "m", parent=PARENT, ended=NOW + 30, end_reason="compression")
            lane = node(built(home), "Compacted")
            self.assertEqual((lane["state"], lane["status"]), ("unknown", "compacted"))

    def test_failed_and_interrupted_stops(self) -> None:
        with homes() as home:
            for index, status in enumerate(("failed", "timeout", "interrupted")):
                start(home, f"child-{index}", f"sa-{index}", status.title(), now=NOW + index)
                stop(home, f"child-{index}", status, now=NOW + 10 + index)
            states = [(item["state"], item["status"]) for item in built(home)["nodes"][1:]]
            self.assertEqual(states, [("failed", "failed"), ("failed", "timeout"), ("interrupted", "interrupted")])


class StructureTests(unittest.TestCase):
    def test_waves_are_dispatch_turns_and_only_dispatch_edges_are_drawn(self) -> None:
        with homes() as home:
            three_lanes(home)
            start(home, "child-9", "sa-9", "Integration verify", turn="turn-5", now=NOW + 400)
            graph = built(home, now=NOW + 410)
            groups = [item["group"] for item in graph["nodes"][1:]]
            self.assertEqual([group.split(" · ")[0] for group in groups], ["wave 1"] * 3 + ["wave 2"])
            self.assertEqual({edge["kind"] for edge in graph["edges"]}, {"dispatch"})
            self.assertEqual({edge["from"] for edge in graph["edges"]}, {"root"})
            self.assertEqual(graph["layers"][0], ["root"])

    def test_a_nested_child_hangs_from_the_child_that_started_it(self) -> None:
        with homes() as home:
            start(home, "child-0", "sa-0-orch", "Orchestrator", now=NOW)
            start(home, "grand-0", "sa-0-leaf", "Leaf", parent="child-0", parent_subagent="sa-0-orch",
                  now=NOW + 1)
            graph = built(home)
            self.assertIn({"from": "s:sa-0-orch", "to": "s:sa-0-leaf", "kind": "dispatch"}, graph["edges"])
            self.assertEqual(len(graph["layers"]), 3)

    def test_a_child_under_a_parent_the_graph_does_not_hold_leaves_no_edge_behind(self) -> None:
        from omh.plugin_bundle.omh import delegation_ledger

        with homes() as home:
            # The orphan lands in this conversation's ledger, under a parent session the ledger holds no child for.
            delegation_ledger._remember(delegation_ledger._roots, "pruned-parent", PARENT, 10)
            start(home, "child-1", "sa-1", "Orphan", parent="pruned-parent", now=NOW)
            start(home, "grand-1", "sa-2", "Under the orphan", parent="child-1", parent_subagent="sa-1", now=NOW + 1)
            start(home, "child-2", "sa-3", "Placed", now=NOW + 2)
            graph = built(home)
            ids = {item["id"] for item in graph["nodes"]}
            self.assertEqual(ids, {"root", "s:sa-3"})
            self.assertTrue(all(edge["from"] in ids and edge["to"] in ids for edge in graph["edges"]), graph["edges"])

    def test_the_graph_is_bounded_and_every_kept_edge_has_both_ends(self) -> None:
        with homes() as home:
            for index in range(GRAPH_NODE_LIMIT + 20):
                start(home, f"child-{index}", f"sa-{index}", f"Lane {index}", now=NOW + index)
            graph = built(home, now=NOW + 200)
            ids = {item["id"] for item in graph["nodes"]}
            self.assertLessEqual(len(graph["nodes"]), GRAPH_NODE_LIMIT)
            self.assertEqual(graph["hidden_nodes"], GRAPH_NODE_LIMIT + 21 - len(graph["nodes"]))
            self.assertEqual(sum(graph["hidden_by_group"].values()), graph["hidden_nodes"])
            self.assertTrue(all(edge["from"] in ids and edge["to"] in ids for edge in graph["edges"]))

    def test_a_cut_says_what_each_group_lost(self) -> None:
        """So a dag run's layer under the cap reads `5 of 10 nodes`, not a total of 5."""
        from omh.plugin_bundle.omh.delegation_graph import _cut

        lanes = [{"id": f"{state}-{index}", "kind": "lane", "state": state, "order": order, "group": group}
                 for order, (index, state, group) in enumerate(
                     [(index, "done", "layer 1") for index in range(10)]
                     + [(index, "waiting", "layer 2") for index in range(10)], start=1)]
        layer_ids = [[lane["id"] for lane in lanes]]
        cut = _cut({"nodes": [{"id": "root", "kind": "root"}, *lanes], "edges": []},
                   {f"waiting-{index}" for index in range(5, 10)}, layer_ids, {lane["id"]: 0 for lane in lanes})
        self.assertEqual(cut["hidden_by_group"], {"layer 1": 10, "layer 2": 5})
        self.assertEqual(cut["hidden_nodes"], 15)
        # Layer 1 lost every node: its place stays known, and so do the states the cut lanes ended in.
        self.assertEqual(cut["group_order"], ["layer 1", "layer 2"])
        self.assertEqual(cut["hidden_by_state"], {"done": 10, "waiting": 5})
        self.assertEqual(cut["layer_hidden"], [{"count": 15, "states": {"done": 10, "waiting": 5}}])


    def test_a_settled_graph_goes_quiet_after_the_linger(self) -> None:
        with homes() as home:
            start(home, "child-0", "sa-0", "Done lane", now=NOW)
            stop(home, "child-0", now=NOW + 10)
            self.assertEqual(built(home, now=NOW + 20)["status"], "active")
            later = built(home, now=NOW + 10 + GRAPH_LINGER_SECONDS + 1)
            self.assertEqual((later["status"], later["reason"]), ("inactive", "settled"))

    def test_a_wave_settled_past_the_linger_leaves_while_newer_work_moves(self) -> None:
        with homes() as home:
            home.session(PARENT, "claude-opus-5-5")
            start(home, "child-0", "sa-0", "Old lane", turn="turn-1", now=NOW)
            start(home, "grand-0", "sa-0a", "Old leaf", parent="child-0", parent_subagent="sa-0", now=NOW + 1)
            stop(home, "grand-0", now=NOW + 10)
            stop(home, "child-0", now=NOW + 20)
            later = NOW + 20 + GRAPH_LINGER_SECONDS + 60
            start(home, "child-1", "sa-1", "Recent lane", turn="turn-2", now=later - 120)
            stop(home, "child-1", now=later - 60)
            start(home, "child-2", "sa-2", "New lane", turn="turn-3", now=later)
            home.session("child-2", "claude-opus-5-5", parent=PARENT)
            home.usage("child-2", "claude-opus-5-5", last_seen=later + 5)
            graph = built(home, now=later + 10)
            self.assertEqual([item["title"] for item in graph["nodes"]], ["main", "Recent lane", "New lane"],
                             "the old wave leaves with its nested lane; one settled within the linger stays")
            ids = {item["id"] for item in graph["nodes"]}
            self.assertTrue(all(edge["from"] in ids and edge["to"] in ids for edge in graph["edges"]))
            whole = built(home, now=later + 10, linger=None)
            self.assertEqual(len(whole["nodes"]), 5, "with no linger nothing is dropped")
            stop(home, "child-2", now=later + 20)
            settled = built(home, now=later + 30)
            self.assertIn("Old lane", [item["title"] for item in settled["nodes"]],
                          "with nothing moving, no wave is dropped: the whole graph lingers or goes quiet")

    def test_the_fingerprint_ignores_elapsed_time(self) -> None:
        with homes() as home:
            three_lanes(home)
            home.usage("child-0", "claude-opus-5-5", last_seen=NOW + 90)
            first, second = built(home, now=NOW + 100), built(home, now=NOW + 130)
            self.assertNotEqual(node(first, "Refresh HUD docs")["elapsed_seconds"],
                                node(second, "Refresh HUD docs")["elapsed_seconds"])
            self.assertEqual(graph_fingerprint(first), graph_fingerprint(second))
            stop(home, "child-0", now=NOW + 140)
            self.assertNotEqual(graph_fingerprint(first), graph_fingerprint(built(home, now=NOW + 150)))


def team_record(units: list[dict]) -> dict:
    return {"schema_version": "omh_team/v1", "team_id": "hud-graph", "units": units, "events": []}


def unit(unit_id: str, title: str, depends_on: list[str], attempts: list[dict] | None = None) -> dict:
    return {"unit_id": unit_id, "title": title, "depends_on": depends_on, "verification_command": "make test",
            "plan_item": title, "attempts": attempts or [], "blocked": None, "lease": None}


class TeamOverlayTests(unittest.TestCase):
    def write_team(self, home, units: list[dict]) -> None:
        directory = home.omh / "runtime" / "teams" / ledger_key(PARENT)
        directory.mkdir(parents=True)
        (directory / "hud-graph.json").write_text(json.dumps(team_record(units)), encoding="utf-8")

    def test_recorded_dependencies_are_the_edges_and_a_waiting_part_counts_its_unmet_parents(self) -> None:
        with homes() as home:
            home.session(PARENT, "claude-opus-5-5")
            route(home, "writing", "claude-opus-5-5", "medium", written_at=NOW - 1)
            start(home, "child-0", "sa-0", "[omh-team:hud-graph/docs/attempt-1] Refresh docs", now=NOW)
            home.session("child-0", "claude-opus-5-5", parent=PARENT, effort="medium")
            accepted = {"n": 1, "dispatch": {"child_session_id": "child-0", "subagent_id": "sa-0"},
                        "returned_at": "t", "check": {"outcome": "passed", "command": "c", "exit_code": 0,
                                                      "observed_at": "t"}, "inconclusive": []}
            self.write_team(home, [
                unit("docs", "Refresh docs", [], [accepted]),
                unit("cli", "Polish CLI", []),
                unit("verify", "Integration verify", ["docs", "cli"]),
            ])
            graph = built(home)
            self.assertEqual(graph["name"], "team hud-graph")
            self.assertEqual(
                sorted((edge["from"], edge["to"], edge["kind"]) for edge in graph["edges"]),
                [("root", "t:cli", "dispatch"), ("root", "t:docs", "dispatch"),
                 ("t:cli", "t:verify", "depends_on"), ("t:docs", "t:verify", "depends_on")],
            )
            docs, verify = node(graph, "Refresh docs"), node(graph, "Integration verify")
            self.assertEqual((docs["state"], docs["status"], docs["category"], docs["model"]),
                             ("done", "accepted", "writing", "claude-opus-5-5"))
            self.assertEqual((verify["state"], verify["waits_on"], verify["category"], verify["model"]),
                             ("waiting", 1, "?", "?"))
            self.assertEqual(verify["group"], "stage 2")
            self.assertEqual(sum(1 for item in graph["nodes"] if item["title"] == "Refresh docs"), 1,
                             "the helper is the part, not a second node")

    def test_a_part_with_no_title_reads_its_unit_id(self) -> None:
        with homes() as home:
            home.session(PARENT, "claude-opus-5-5")
            self.write_team(home, [unit("docs", "Refresh docs", []), unit("cli", "", ["docs"]),
                                   unit("verify", " \x07 ", ["cli"])])
            self.assertEqual([item["title"] for item in built(home)["nodes"][1:]], ["Refresh docs", "cli", "verify"])

    def test_the_part_state_mirrors_the_team_records_own(self) -> None:
        from omh.workflows.team import unit_state

        dispatch = {"child_session_id": "c", "subagent_id": "s"}
        shapes = [
            unit("a", "A", []),
            unit("a", "A", [], [{"n": 1, "dispatch": None, "inconclusive": []}]),
            unit("a", "A", [], [{"n": 1, "dispatch": dispatch, "inconclusive": []}]),
            unit("a", "A", [], [{"n": 1, "dispatch": dispatch, "returned_at": "t", "inconclusive": []}]),
            unit("a", "A", [], [{"n": 1, "dispatch": dispatch, "returned_at": "t",
                                 "check": {"outcome": "passed"}, "inconclusive": []}]),
            unit("a", "A", [], [{"n": 1, "inconclusive": []}, {"n": 2, "dispatch": dispatch, "inconclusive": []}]),
            {**unit("a", "A", []), "blocked": {"reason": "repair_budget_exhausted"}},
        ]
        for shape in shapes:
            with self.subTest(shape=shape):
                self.assertEqual(team_unit_state(shape), unit_state(shape))


    def test_a_repair_is_running_only_while_its_child_is(self) -> None:
        first = {"n": 1, "dispatch": {"child_session_id": "child-0", "subagent_id": "sa-0"}, "returned_at": "t",
                 "check": {"outcome": "failed"}, "inconclusive": []}
        with homes() as home:
            home.session(PARENT, "claude-opus-5-5")
            start(home, "child-0", "sa-0", "[omh-team:hud-graph/fix/attempt-1] Fix the parser", now=NOW)
            self.write_team(home, [unit("fix", "Fix the parser", [], [first, {"n": 2, "inconclusive": []}]),
                                   unit("next", "Keep going", [])])
            reserved = node(built(home), "Fix the parser")
            self.assertEqual((reserved["state"], reserved["status"]), ("waiting", "repair prepared"))
        with homes() as home:
            home.session(PARENT, "claude-opus-5-5")
            start(home, "child-0", "sa-0", "[omh-team:hud-graph/fix/attempt-1] Fix the parser", now=NOW)
            start(home, "child-1", "sa-1", "[omh-team:hud-graph/fix/attempt-2] Fix the parser", now=NOW + 10)
            home.session("child-1", "claude-opus-5-5", parent=PARENT)
            home.usage("child-1", "claude-opus-5-5", last_seen=NOW + 20)
            repair = {"n": 2, "dispatch": {"child_session_id": "child-1", "subagent_id": "sa-1"}, "inconclusive": []}
            self.write_team(home, [unit("fix", "Fix the parser", [], [first, repair]), unit("next", "Keep going", [])])
            moving = node(built(home, now=NOW + 30), "Fix the parser")
            self.assertEqual((moving["state"], moving["status"]), ("running", "repairing"))
            later = NOW + CHILD_STALE_SECONDS + 60
            start(home, "child-9", "sa-9", "Fresh", now=later - 5)  # keeps the graph from settling
            silent = node(built(home, now=later), "Fix the parser")
            self.assertEqual((silent["state"], silent["status"]), ("unknown", "no news"),
                             "a repair silent past the stale window is not drawn running")
        with homes() as home:
            home.session(PARENT, "claude-opus-5-5")
            repair = {"n": 2, "dispatch": {"child_session_id": "child-x", "subagent_id": "sa-x"}, "inconclusive": []}
            self.write_team(home, [unit("fix", "Fix the parser", [], [first, repair])])
            unseen = node(built(home), "Fix the parser")
            self.assertEqual((unseen["state"], unseen["status"]), ("dispatched", "repair dispatched"))

    def test_a_helper_a_restart_ended_is_drawn_nowhere(self) -> None:
        """Mutation: drop `team_lost` from either free-child filter."""
        with homes() as home:
            home.session(PARENT, "claude-opus-5-5")
            start(home, "child-0", "sa-0", "[omh-team:hud-graph/docs/attempt-1] Refresh docs", now=NOW)
            home.session("child-0", "claude-opus-5-5", parent=PARENT)
            start(home, "child-1", "sa-1", "Read the logs", turn="turn-4", now=NOW + 10)
            lost = {"n": 1, "dispatch": None, "lost": [{"child_session_id": "child-0", "subagent_id": "sa-0",
                                                        "lost_at": "t"}], "inconclusive": []}
            self.write_team(home, [unit("docs", "Refresh docs", [], [lost])])
            graph = built(home)
        self.assertEqual(sorted(item["title"] for item in graph["nodes"] if item["id"] != "root"),
                         ["Read the logs", "Refresh docs"], "the ended helper is not a lane of its own")
        self.assertEqual(node(graph, "Refresh docs")["status"], "prepared")
        self.assertTrue(node(graph, "Read the logs")["group"].startswith("wave 1 "), "nor does it take a wave")


class FanoutTests(unittest.TestCase):
    def test_a_fanout_draws_its_units_owners_models_and_dependencies(self) -> None:
        record = {
            "contract": {"fanout_id": "fanout-0123456789ab", "units": [
                {"unit_id": "core", "title": "Core", "owner": "codex", "depends_on": []},
                {"unit_id": "ui", "title": "UI", "owner": "claude-code", "depends_on": ["core"]},
            ]},
            "roster": {"units": [
                {"unit_id": "core", "status": "running", "model": "gpt-6.1-sol", "reasoning_effort": "high",
                 "unit_state": "progress_stalled", "state_reason": "same error", "stalled_for_seconds": "400"},
                {"unit_id": "ui", "status": "prepared_not_observed"},
            ]},
        }
        graph = fanout_graph(record)
        self.assertEqual((graph["source"], graph["scope"], graph["name"]),
                         ("fanout", "global", "fanout fanout-0123456789ab"))
        core, ui = node(graph, "Core"), node(graph, "UI")
        self.assertEqual((core["state"], core["status"], core["category"], core["model"], core["elapsed_seconds"]),
                         ("stuck", "stuck: same error", "codex", "gpt-6.1-sol", 400))
        self.assertEqual((ui["state"], ui["status"], ui["waits_on"], ui["model"]), ("waiting", "prepared", 1, "?"))
        self.assertIn({"from": "f:core", "to": "f:ui", "kind": "depends_on"}, graph["edges"])

    def test_a_native_graph_wins_over_the_fanout(self) -> None:
        record = {"contract": {"fanout_id": "fanout-0123456789ab", "units": [
            {"unit_id": "core", "title": "Core", "owner": "codex", "depends_on": []}]},
            "roster": {"units": [{"unit_id": "core", "status": "running"}]}}
        with homes() as home:
            self.assertEqual(built(home, fanout=record)["source"], "fanout")
            start(home, "child-0", "sa-0", "Native", now=NOW)
            self.assertEqual(built(home, fanout=record)["source"], "native")


LATER = "20261020_150000_later"


class RotatingCompactionTests(unittest.TestCase):
    """Hermes' rotating compaction (`compression.in_place: false`) moves a conversation, or one child, to a new id.

    Hermes names the sessions as they are when a child stops
    (`delegate_tool_results._fire_subagent_stop_hooks`): the parent's current
    segment and the child's current segment, so the stop reaches the ledger
    unjoined (`delegation_ledger.observe_subagent_stop`).
    """

    def test_a_rotated_parent_keeps_its_lanes_and_joins_the_stop_filed_under_its_new_segment(self) -> None:
        with homes() as home:
            three_lanes(home)
            home.usage("child-0", "claude-opus-5-5", last_seen=NOW + 90)
            home.usage("child-1", "glm-5.3-flash", last_seen=NOW + 60)
            home.rotate(PARENT, LATER, at=NOW + 40)
            stop(home, "child-1", parent=LATER, now=NOW + 62)
            graph = build_delegation_graph(home.omh, home.hermes, LATER, now=NOW + 100)
            earlier = built(home)
        lanes = graph["nodes"][1:]
        self.assertEqual([(item["title"], item["state"]) for item in lanes],
                         [("Refresh HUD docs", "running"), ("Polish HUD CLI", "done"), ("Update HUD tests", "dispatched")])
        groups = {item["group"] for item in lanes}
        self.assertTrue(len(groups) == 1 and groups.pop().startswith("wave 1 · "), lanes)
        self.assertAlmostEqual(node(graph, "Polish HUD CLI")["elapsed_seconds"], 61.0)
        self.assertEqual(graph_fingerprint(earlier), graph_fingerprint(graph), "every segment reads one graph")

    def test_a_team_record_under_an_earlier_segment_is_read(self) -> None:
        with homes() as home:
            home.session(PARENT, "claude-opus-5-5")
            directory = home.omh / "runtime" / "teams" / ledger_key(PARENT)
            directory.mkdir(parents=True)
            (directory / "hud-graph.json").write_text(json.dumps(team_record([unit("docs", "Refresh docs", [])])),
                                                      encoding="utf-8")
            home.rotate(PARENT, LATER, at=NOW + 40)
            graph = build_delegation_graph(home.omh, home.hermes, LATER, now=NOW + 100)
            # A team started after the rotation is under the new segment, and the newest record is the one drawn.
            os.utime(directory / "hud-graph.json", (1_700_000_000, 1_700_000_000))
            newer = home.omh / "runtime" / "teams" / ledger_key(LATER)
            newer.mkdir(parents=True)
            (newer / "second.json").write_text(
                json.dumps({**team_record([unit("cli", "Polish CLI", [])]), "team_id": "second"}), encoding="utf-8")
            second = build_delegation_graph(home.omh, home.hermes, LATER, now=NOW + 100)
        self.assertEqual((graph["name"], node(graph, "Refresh docs")["state"]), ("team hud-graph", "waiting"))
        self.assertEqual(second["name"], "team second")

    def test_a_rotated_child_is_read_through_its_continuation(self) -> None:
        late = NOW + CHILD_STALE_SECONDS + 100  # the first segment's last call alone would read `no news` by now
        with homes() as home:
            start(home, "child-0", "sa-0", "Long lane", now=NOW)
            home.session("child-0", "glm-5.3-flash", parent=PARENT, started=NOW)
            home.usage("child-0", "glm-5.3-flash", last_seen=NOW + 20)
            home.tokens("child-0", 1_200)
            home.rotate("child-0", "child-0b", at=NOW + 30)
            home.usage("child-0b", "glm-5.3-flash", last_seen=late - 10)
            home.tokens("child-0b", 700)
            running = node(built(home, now=late), "Long lane")
            stop(home, "child-0b", now=late - 5)
            done = node(built(home, now=late), "Long lane")
        self.assertEqual((running["state"], running["status"], running["output_tokens"]), ("running", "running", 1_900))
        self.assertEqual((done["state"], done["status"], done["output_tokens"], done["elapsed_seconds"]),
                         ("done", "done", 1_900, late - 5 - NOW))

    def test_a_stale_sibling_beside_a_rotated_childs_continuation_does_not_end_it(self) -> None:
        # A reconnect can leave a second row under the closed segment (`get_compression_chain`); the child is open
        # while any of them is.
        with homes() as home:
            start(home, "child-0", "sa-0", "Long lane", now=NOW)
            home.session("child-0", "glm-5.3-flash", parent=PARENT, started=NOW)
            home.rotate("child-0", "child-0b", at=NOW + 30)
            home.rotate("child-0", "child-0a", at=NOW + 30)
            home.execute("UPDATE sessions SET ended_at = ?, end_reason = 'ws_orphan_reap' WHERE id = 'child-0a'",
                         (NOW + 31,))
            home.usage("child-0b", "glm-5.3-flash", last_seen=NOW + 90)
            lane = node(built(home), "Long lane")
        self.assertEqual((lane["state"], lane["status"]), ("running", "running"))

    def test_a_rotated_child_whose_continuation_ended_without_a_stop_is_unknown(self) -> None:
        with homes() as home:
            start(home, "child-0", "sa-0", "Long lane", now=NOW)
            home.session("child-0", "glm-5.3-flash", parent=PARENT, started=NOW)
            home.rotate("child-0", "child-0b", at=NOW + 30)
            home.execute("UPDATE sessions SET ended_at = ?, end_reason = 'agent_close' WHERE id = 'child-0b'",
                         (NOW + 60,))
            lane = node(built(home), "Long lane")
        self.assertEqual((lane["state"], lane["status"]), ("unknown", "ended"))

    def test_a_fork_of_the_conversation_is_not_one_of_its_segments(self) -> None:
        # A reset beside the continuation is a chat of its own: neither reads the other's lanes or stops.
        with homes() as home:
            three_lanes(home)
            home.rotate(PARENT, LATER, at=NOW + 40)
            home.execute("INSERT INTO sessions (id, source, model, model_config, started_at, parent_session_id) "
                         "VALUES ('reset-1', 'discord', 'claude-opus-5-5', ?, ?, ?)",
                         (json.dumps({"_reset_from": PARENT}), NOW + 50, PARENT))
            start(home, "child-r", "sa-r", "Other chat", parent="reset-1", now=NOW + 55)
            stop(home, "child-1", parent="reset-1", now=NOW + 62)  # a stop no segment of PARENT's filed
            ours = build_delegation_graph(home.omh, home.hermes, LATER, now=NOW + 100)
            theirs = build_delegation_graph(home.omh, home.hermes, "reset-1", now=NOW + 100)
        self.assertEqual([item["title"] for item in ours["nodes"][1:]],
                         ["Refresh HUD docs", "Polish HUD CLI", "Update HUD tests"])
        self.assertNotEqual(node(ours, "Polish HUD CLI")["state"], "done")
        self.assertEqual([item["title"] for item in theirs["nodes"][1:]], ["Other chat"])


class OutputTokenTests(unittest.TestCase):
    """Each native lane's `output_tokens`: what its child's state.db row has counted, or None without a count."""

    def test_a_lane_carries_what_its_childs_row_has_counted(self) -> None:
        with homes() as home:
            three_lanes(home)
            home.usage("child-0", "claude-opus-5-5", last_seen=NOW + 90)
            home.tokens("child-0", 1234)
            home.tokens("child-1", 0)  # the column's default before the child's first call
            graph = built(home)
            self.assertEqual([item.get("output_tokens") for item in graph["nodes"][1:]], [1234, None, None])
            self.assertNotIn("output_tokens", graph["nodes"][0], "the root is the conversation, not a lane")
            home.tokens("child-0", 2500)
            self.assertEqual(node(built(home), "Refresh HUD docs")["output_tokens"], 2500)

    def test_a_finished_lane_keeps_its_childs_final_count(self) -> None:
        with homes() as home:
            three_lanes(home)
            home.usage("child-1", "glm-5.3-flash", last_seen=NOW + 60)
            home.tokens("child-1", 4900)
            stop(home, "child-1", now=NOW + 62)
            stop(home, "child-2", "error", now=NOW + 70)
            home.tokens("child-2", 750)  # the failure path's stop carries no count; the row does
            graph = built(home)
            self.assertEqual((node(graph, "Polish HUD CLI")["state"], node(graph, "Polish HUD CLI")["output_tokens"]),
                             ("done", 4900))
            self.assertEqual((node(graph, "Update HUD tests")["state"], node(graph, "Update HUD tests")["output_tokens"]),
                             ("failed", 750))

    def test_a_team_part_carries_its_bound_childs_count_and_an_unbound_one_none(self) -> None:
        with homes() as home:
            home.session(PARENT, "claude-opus-5-5")
            start(home, "child-0", "sa-0", "[omh-team:hud-graph/docs/attempt-1] Refresh docs", now=NOW)
            home.session("child-0", "claude-opus-5-5", parent=PARENT)
            home.usage("child-0", "claude-opus-5-5", last_seen=NOW + 90)
            home.tokens("child-0", 640)
            sent = {"n": 1, "dispatch": {"child_session_id": "child-0", "subagent_id": "sa-0"}}
            TeamOverlayTests().write_team(home, [unit("docs", "Refresh docs", [], [sent]), unit("cli", "Polish CLI", [])])
            graph = built(home)
            self.assertEqual(node(graph, "Refresh docs")["output_tokens"], 640)
            self.assertIsNone(node(graph, "Polish CLI").get("output_tokens"))

    def test_a_state_db_without_the_column_or_unreadable_gives_no_count_and_the_rest_stands(self) -> None:
        with homes() as home:
            three_lanes(home)
            home.tokens("child-0", 1234)
            home.execute("ALTER TABLE sessions DROP COLUMN output_tokens")
            graph = built(home)
            self.assertEqual([item.get("output_tokens") for item in graph["nodes"][1:]], [None, None, None])
            self.assertEqual(node(graph, "Refresh HUD docs")["category"], "writing", "the other facts are still read")
            (home.hermes / "state.db").write_bytes(b"not a database")
            self.assertIsNone(node(built(home), "Refresh HUD docs")["output_tokens"])

    def test_a_count_that_moves_does_not_move_the_fingerprint(self) -> None:
        # The chat posts are keyed on the fingerprint: a growing count must not make a new one.
        with homes() as home:
            three_lanes(home)
            home.usage("child-0", "claude-opus-5-5", last_seen=NOW + 90)
            home.tokens("child-0", 100)
            first = built(home)
            home.tokens("child-0", 90_000)
            self.assertEqual(graph_fingerprint(first), graph_fingerprint(built(home)))

    def test_a_home_whose_path_holds_a_hash_or_a_question_mark_is_read(self) -> None:
        # A URI reads `#` as the start of a fragment and `?` as the start of the query: the path is quoted.
        from tempfile import TemporaryDirectory
        from unittest.mock import patch

        from _delegation_state import Homes
        from omh.plugin_bundle.omh import delegation_ledger

        name = "odd#home" if os.name == "nt" else "odd#home?x"  # Windows allows no `?` in a file name
        with TemporaryDirectory() as tmp:
            (Path(tmp) / name).mkdir()
            home = Homes(Path(tmp) / name)
            with patch.dict(os.environ, {"OMH_HOME": str(home.omh), "HERMES_HOME": str(home.hermes)}):
                delegation_ledger._roots.clear()
                delegation_ledger._titles.clear()
                try:
                    three_lanes(home)
                    home.usage("child-0", "claude-opus-5-5", last_seen=NOW + 90)
                    home.tokens("child-0", 1234)
                    lane = node(built(home), "Refresh HUD docs")
                    self.assertEqual((lane["model"], lane["output_tokens"]), ("claude-opus-5-5", 1234))
                finally:
                    delegation_ledger._roots.clear()
                    delegation_ledger._titles.clear()

    def test_a_fanout_unit_has_no_count(self) -> None:
        record = {"contract": {"fanout_id": "fanout-0123456789ab", "units": [
            {"unit_id": "core", "title": "Core", "owner": "codex", "depends_on": []}]},
            "roster": {"units": [{"unit_id": "core", "status": "running"}]}}
        self.assertNotIn("output_tokens", node(fanout_graph(record), "Core"))


class UsageTests(unittest.TestCase):
    """Each lane's `usage`: the input, cache and cost columns of its child's state.db row, absent where uncounted."""

    @staticmethod
    def with_columns(home) -> None:
        """The `sessions` columns as Hermes declares them: counts default to 0, costs to NULL (no figure yet)."""
        for column, kind in (("input_tokens", "INTEGER DEFAULT 0"), ("cache_read_tokens", "INTEGER DEFAULT 0"),
                             ("cache_write_tokens", "INTEGER DEFAULT 0"), ("actual_cost_usd", "REAL"),
                             ("estimated_cost_usd", "REAL")):
            home.execute(f"ALTER TABLE sessions ADD COLUMN {column} {kind}")

    @staticmethod
    def with_usage_columns(home) -> None:
        """`session_model_usage`'s counting columns as Hermes declares them: every one NOT NULL DEFAULT 0, and the
        nullable `cost_status` only the main loop writes."""
        for column, kind in (("task", "TEXT"), ("input_tokens", "INTEGER"), ("output_tokens", "INTEGER"),
                             ("cache_read_tokens", "INTEGER"), ("cache_write_tokens", "INTEGER"),
                             ("estimated_cost_usd", "REAL"), ("actual_cost_usd", "REAL")):
            default = "''" if kind == "TEXT" else "0"
            home.execute(f"ALTER TABLE session_model_usage ADD COLUMN {column} {kind} NOT NULL DEFAULT {default}")
        home.execute("ALTER TABLE session_model_usage ADD COLUMN cost_status TEXT")

    @staticmethod
    def call(home, session: str, task: str, uncached: int, output: int, read: int = 0, write: int = 0, *,
             estimated: float = 0.0, actual: float = 0.0, cost_status: str | None = None) -> None:
        """One `session_model_usage` row: the main loop's (task ``''`` or a per-turn route's, with the `cost_status`
        `turn_usage` always passes) or an auxiliary call's under its task (no `cost_status`)."""
        home.execute("INSERT INTO session_model_usage (session_id, model, task, api_call_count, input_tokens, "
                     "output_tokens, cache_read_tokens, cache_write_tokens, estimated_cost_usd, actual_cost_usd, "
                     "cost_status, last_seen) VALUES (?, 'm', ?, 1, ?, ?, ?, ?, ?, ?, ?, 1)",
                     (session, task, uncached, output, read, write, estimated, actual, cost_status))

    @staticmethod
    def count(home, session: str, uncached: int, read: int, write: int, *, actual: float | None = None,
              estimated: float | None = None) -> None:
        home.execute("UPDATE sessions SET input_tokens = ?, cache_read_tokens = ?, cache_write_tokens = ?, "
                     "actual_cost_usd = ?, estimated_cost_usd = ? WHERE id = ?",
                     (uncached, read, write, actual, estimated, session))

    def test_a_lane_carries_its_childs_input_cache_and_cost(self) -> None:
        with homes() as home:
            three_lanes(home)
            self.with_columns(home)
            self.count(home, "child-0", 120, 4_000, 300, actual=0.5)
            self.count(home, "child-1", 10, 0, 0, estimated=0.02)
            graph = built(home)
        self.assertEqual(node(graph, "Refresh HUD docs")["usage"],
                         {"input": 120, "cache_read": 4_000, "cache_write": 300, "output": 0, "cost_usd": 0.5})
        self.assertEqual(node(graph, "Polish HUD CLI")["usage"],
                         {"input": 10, "cache_read": 0, "cache_write": 0, "output": 0, "cost_usd": 0.02,
                          "cost_estimated": True})
        self.assertNotIn("usage", node(graph, "Update HUD tests"), "a child that counted nothing has no usage")
        self.assertNotIn("usage", graph["nodes"][0], "the root is the conversation, not a lane")

    def test_tokens_hermes_did_not_price_stay_tokens(self) -> None:
        with homes() as home:
            three_lanes(home)
            self.with_columns(home)
            self.count(home, "child-0", 50, 900, 0)
            usage = node(built(home), "Refresh HUD docs")["usage"]
        self.assertEqual(usage, {"input": 50, "cache_read": 900, "cache_write": 0, "output": 0})

    def test_a_provider_reported_zero_is_a_zero_cost_not_the_estimate(self) -> None:
        """Mutation: read `actual_cost_usd` 0 as absent (the estimate takes over), or NULL as a reported 0."""
        with homes() as home:
            three_lanes(home)
            self.with_columns(home)
            self.count(home, "child-0", 50, 900, 0, actual=0.0, estimated=0.04)
            self.count(home, "child-1", 50, 900, 0, estimated=0.04)
            graph = built(home)
        self.assertEqual(node(graph, "Refresh HUD docs")["usage"]["cost_usd"], 0.0)
        self.assertNotIn("cost_estimated", node(graph, "Refresh HUD docs")["usage"])
        self.assertEqual((node(graph, "Polish HUD CLI")["usage"]["cost_usd"],
                          node(graph, "Polish HUD CLI")["usage"]["cost_estimated"]), (0.04, True))

    def test_a_lane_counts_its_childs_auxiliary_calls(self) -> None:
        """Mutation: read only the `sessions` row, or add the main loop's own usage rows on top of it."""
        with homes() as home:
            three_lanes(home)
            self.with_columns(home)
            self.with_usage_columns(home)
            home.tokens("child-0", 200)
            self.count(home, "child-0", 120, 4_000, 300, actual=0.5)
            self.call(home, "child-0", "", 120, 200, 4_000, 300, actual=0.5,  # the main loop, already in the row
                      cost_status="estimated")
            self.call(home, "child-0", "compression", 2_000, 400, estimated=0.01)
            usage = node(built(home), "Refresh HUD docs")["usage"]
        self.assertEqual(usage, {"input": 2_120, "cache_read": 4_000, "cache_write": 300, "output": 600,
                                 "cost_usd": 0.51, "cost_estimated": True})

    def test_a_rotated_child_adds_its_segments_and_marks_a_cost_one_segment_lacks_as_a_floor(self) -> None:
        with homes() as home:
            start(home, "child-0", "sa-0", "Long lane", now=NOW)
            home.session("child-0", "glm-5.3-flash", parent=PARENT, started=NOW)
            home.usage("child-0", "glm-5.3-flash", last_seen=NOW + 20)
            home.rotate("child-0", "child-0b", at=NOW + 30)
            home.usage("child-0b", "glm-5.3-flash", last_seen=NOW + 90)
            self.with_columns(home)
            self.count(home, "child-0", 100, 1_000, 50, actual=0.25)
            self.count(home, "child-0b", 40, 3_000, 0)
            summed = node(built(home), "Long lane")["usage"]
            self.count(home, "child-0b", 40, 3_000, 0, actual=0.5)
            priced = node(built(home), "Long lane")["usage"]
        self.assertEqual(summed, {"input": 140, "cache_read": 4_000, "cache_write": 50, "output": 0, "cost_usd": 0.25,
                                  "cost_partial": True})
        self.assertEqual(priced, {"input": 140, "cache_read": 4_000, "cache_write": 50, "output": 0, "cost_usd": 0.75})

    def test_a_state_db_without_the_columns_gives_no_usage_and_the_rest_stands(self) -> None:
        with homes() as home:
            three_lanes(home)
            home.tokens("child-0", 1_234)
            graph = built(home)
        self.assertNotIn("usage", node(graph, "Refresh HUD docs"))
        self.assertEqual(node(graph, "Refresh HUD docs")["output_tokens"], 1_234)

    def test_a_count_that_moves_does_not_move_the_fingerprint(self) -> None:
        with homes() as home:
            three_lanes(home)
            self.with_columns(home)
            self.count(home, "child-0", 1, 2, 3)
            first = built(home)
            self.count(home, "child-0", 9_000, 8_000, 7_000)
            self.assertEqual(graph_fingerprint(first), graph_fingerprint(built(home)))


class SessionUsageTests(unittest.TestCase):
    """`session_usage`: the figures the pane's usage board shows for the chat itself, not for its children."""

    def test_a_chat_carries_its_own_figures_and_not_its_childrens(self) -> None:
        with homes() as home:
            home.session(PARENT, "gpt-6-luna", started=NOW)
            home.session("child-0", "glm-5.3-flash", parent=PARENT, started=NOW)
            UsageTests.with_columns(home)
            home.tokens(PARENT, 630)
            UsageTests.count(home, PARENT, 120, 4_000, 300, actual=0.5)
            UsageTests.count(home, "child-0", 9, 9, 9, actual=9.0)
            usage = session_usage(home.hermes, PARENT)
        self.assertEqual(usage, {"session_id": PARENT, "model": "gpt-6-luna", "output": 630, "input": 120,
                                 "cache_read": 4_000, "cache_write": 300, "cost_usd": 0.5})

    def test_a_chats_auxiliary_calls_count_once_beside_its_row(self) -> None:
        """Mutation: drop the auxiliary rows, add the main loop's rows on top of the row, or price an unpriced call."""
        with homes() as home:
            home.session(PARENT, "gpt-6-luna", started=NOW)
            UsageTests.with_columns(home)
            UsageTests.with_usage_columns(home)
            home.tokens(PARENT, 630)
            UsageTests.count(home, PARENT, 120, 4_000, 300, actual=0.5)
            UsageTests.call(home, PARENT, "", 120, 630, 4_000, 300, actual=0.5, cost_status="estimated")
            UsageTests.call(home, PARENT, "title_generation", 300, 12, estimated=0.001)
            UsageTests.call(home, PARENT, "compression", 5_000, 800, 1_000, estimated=0.02)
            priced = session_usage(home.hermes, PARENT)
            UsageTests.call(home, PARENT, "vision", 900, 40)
            unpriced = session_usage(home.hermes, PARENT)
        self.assertEqual(priced, {"session_id": PARENT, "model": "gpt-6-luna", "output": 1_442, "input": 5_420,
                                  "cache_read": 5_000, "cache_write": 300, "cost_usd": 0.521, "cost_estimated": True})
        self.assertEqual(unpriced, {"session_id": PARENT, "model": "gpt-6-luna", "output": 1_482, "input": 6_320,
                                    "cache_read": 5_000, "cache_write": 300, "cost_usd": 0.521, "cost_estimated": True,
                                    "cost_partial": True},
                         "a call Hermes did not price keeps the priced sum, marked as a floor")

    def test_a_voice_turn_counts_once_beside_an_auxiliary_call(self) -> None:
        """Mutation: count a per-turn route's `voice_chat` rows (already in the `sessions` row) as auxiliary calls.

        Hermes' `update_token_counts(task="voice_chat")` adds the turn to the row and writes it under that task too.
        """
        with homes() as home:
            home.session(PARENT, "gpt-6-luna", started=NOW)
            UsageTests.with_columns(home)
            UsageTests.with_usage_columns(home)
            home.tokens(PARENT, 700)
            UsageTests.count(home, PARENT, 1_100, 4_000, 300, actual=0.6)  # the text turn and the voice turn
            UsageTests.call(home, PARENT, "", 1_000, 600, 4_000, 300, actual=0.5, cost_status="estimated")
            UsageTests.call(home, PARENT, "voice_chat", 100, 100, actual=0.1, cost_status="estimated")
            UsageTests.call(home, PARENT, "compression", 2_000, 400, estimated=0.02)
            counted = session_usage(home.hermes, PARENT)
            # A route task named nowhere yet is still a main-loop row: `turn_usage` gave it a `cost_status`.
            UsageTests.call(home, PARENT, "a_later_route", 50, 50, estimated=0.01, cost_status="estimated")
            later = session_usage(home.hermes, PARENT)
        self.assertEqual(counted, {"session_id": PARENT, "model": "gpt-6-luna", "output": 1_100, "input": 3_100,
                                   "cache_read": 4_000, "cache_write": 300, "cost_usd": 0.62,
                                   "cost_estimated": True})
        self.assertEqual(later, counted)

    def test_a_chat_whose_only_counts_are_auxiliary_or_whose_usage_table_is_older_reads_as_its_row(self) -> None:
        with homes() as home:
            home.session(PARENT, "gpt-6-luna", started=NOW)
            UsageTests.with_columns(home)
            UsageTests.with_usage_columns(home)
            UsageTests.call(home, PARENT, "title_generation", 300, 12, estimated=0.001)
            only_auxiliary = session_usage(home.hermes, PARENT)
        with homes() as home:
            # `session_model_usage` without `task`: no auxiliary call can be told from the main loop's, so the row.
            home.session(PARENT, "gpt-6-luna", started=NOW)
            UsageTests.with_columns(home)
            home.tokens(PARENT, 630)
            UsageTests.count(home, PARENT, 120, 4_000, 300, actual=0.5)
            home.usage(PARENT, "gpt-6-luna", last_seen=NOW)
            older = session_usage(home.hermes, PARENT)
            home.execute("ALTER TABLE session_model_usage RENAME TO session_model_usage_gone")
            missing = session_usage(home.hermes, PARENT)
        self.assertEqual(only_auxiliary, {"session_id": PARENT, "model": "gpt-6-luna", "output": 12, "input": 300,
                                          "cache_read": 0, "cache_write": 0, "cost_usd": 0.001,
                                          "cost_estimated": True})
        row = {"session_id": PARENT, "model": "gpt-6-luna", "output": 630, "input": 120, "cache_read": 4_000,
               "cache_write": 300, "cost_usd": 0.5}
        self.assertEqual((older, missing), (row, row))

    def test_a_compacted_chat_adds_its_segments_and_marks_a_cost_one_segment_lacks_as_a_floor(self) -> None:
        with homes() as home:
            home.session(PARENT, "gpt-6-luna", started=NOW)
            home.rotate(PARENT, f"{PARENT}b", at=NOW + 30)
            UsageTests.with_columns(home)
            home.tokens(PARENT, 100)
            home.tokens(f"{PARENT}b", 50)
            UsageTests.count(home, PARENT, 100, 1_000, 50, actual=0.25)
            UsageTests.count(home, f"{PARENT}b", 40, 3_000, 0)
            usage = session_usage(home.hermes, PARENT)
        self.assertEqual(usage, {"session_id": PARENT, "model": "gpt-6-luna", "output": 150, "input": 140,
                                 "cache_read": 4_000, "cache_write": 50, "cost_usd": 0.25, "cost_partial": True})

    def test_an_estimated_cost_is_marked_and_an_unpriced_chat_has_none(self) -> None:
        with homes() as home:
            home.session(PARENT, "gpt-6-luna", started=NOW)
            UsageTests.with_columns(home)
            UsageTests.count(home, PARENT, 10, 20, 0, estimated=0.02)
            estimated = session_usage(home.hermes, PARENT)
            UsageTests.count(home, PARENT, 10, 20, 0)
            unpriced = session_usage(home.hermes, PARENT)
        self.assertEqual(estimated, {"session_id": PARENT, "model": "gpt-6-luna", "output": 0, "input": 10,
                                     "cache_read": 20, "cache_write": 0, "cost_usd": 0.02, "cost_estimated": True})
        self.assertEqual(unpriced, {"session_id": PARENT, "model": "gpt-6-luna", "output": 0, "input": 10,
                                    "cache_read": 20, "cache_write": 0})

    def test_a_state_db_without_the_columns_still_gives_the_output(self) -> None:
        with homes() as home:
            home.session(PARENT, "gpt-6-luna", started=NOW)
            home.tokens(PARENT, 1_234)
            usage = session_usage(home.hermes, PARENT)
        self.assertEqual(usage, {"session_id": PARENT, "model": "gpt-6-luna", "output": 1_234})

    def test_a_chat_with_no_row_or_no_count_or_no_database_has_no_figures(self) -> None:
        with homes() as home:
            self.assertIsNone(session_usage(home.hermes, "no-such-chat"))
            home.session(PARENT, "gpt-6-luna", started=NOW)
            self.assertIsNone(session_usage(home.hermes, PARENT))
        self.assertIsNone(session_usage(Path("/nonexistent/hermes"), PARENT))


class RunUsageTests(unittest.TestCase):
    """`run_usage`: a dag run's children added up, each with its compaction segments and auxiliary calls (#2684)."""

    def test_children_add_up_with_their_segments_and_a_repeated_id_counts_once(self) -> None:
        """Mutation: drop a compacted child's later segment, or count a child named twice twice."""
        with homes() as home:
            home.session("child-0", "glm-5.3-flash", parent=PARENT, started=NOW)
            home.rotate("child-0", "child-0b", at=NOW + 30)
            home.session("child-1", "glm-5.3-flash", parent=PARENT, started=NOW)
            UsageTests.with_columns(home)
            home.tokens("child-0", 100)
            home.tokens("child-0b", 50)
            home.tokens("child-1", 10)
            UsageTests.count(home, "child-0", 100, 1_000, 50, actual=0.25)
            UsageTests.count(home, "child-0b", 40, 3_000, 0, actual=0.05)
            UsageTests.count(home, "child-1", 5, 0, 0, actual=0.0)
            usage = run_usage(home.hermes, ["child-0", "child-1", "child-0", "", "child-gone"])
        self.assertEqual(usage, {"input": 145, "cache_read": 4_000, "cache_write": 50, "output": 160,
                                 "cost_usd": 0.3, "children": 2, "children_unrecorded": 1, "priced": 2})

    def test_children_past_the_cap_are_named_unread_and_the_cost_is_a_floor(self) -> None:
        children = [f"child-{at}" for at in range(RUN_USAGE_CHILD_LIMIT + 2)]
        with homes() as home:
            UsageTests.with_columns(home)
            for child in children:
                home.session(child, "glm-5.3-flash", parent=PARENT, started=NOW)
                UsageTests.count(home, child, 10, 0, 0, actual=0.01)
            usage = run_usage(home.hermes, children)
        self.assertEqual((usage["children"], usage["children_unread"], usage["priced"]),
                         (RUN_USAGE_CHILD_LIMIT, 2, RUN_USAGE_CHILD_LIMIT))
        self.assertTrue(usage["cost_partial"])

    def test_no_child_no_count_or_no_database_is_no_usage(self) -> None:
        with homes() as home:
            self.assertIsNone(run_usage(home.hermes, []))
            home.session("child-0", "glm-5.3-flash", parent=PARENT, started=NOW)
            self.assertIsNone(run_usage(home.hermes, ["child-0"]))
        self.assertIsNone(run_usage(Path("/nonexistent/hermes"), ["child-0"]))


class NoRaiseTests(unittest.TestCase):
    def test_a_broken_database_or_record_leaves_the_graph_smaller_never_an_exception(self) -> None:
        with homes() as home:
            start(home, "child-0", "sa-0", "Lane", now=NOW)
            (home.hermes / "state.db").write_bytes(b"not a database")
            lane = node(built(home), "Lane")
            self.assertEqual((lane["model"], lane["category"]), ("?", "?"))
            os.remove(home.hermes / "state.db")
            self.assertEqual(node(built(home), "Lane")["model"], "?")
            teams = home.omh / "runtime" / "teams" / ledger_key(PARENT)
            teams.mkdir(parents=True)
            (teams / "bad.json").write_text("{", encoding="utf-8")
            (teams / "worse.json").write_text(json.dumps({"schema_version": "omh_team/v1", "units": [
                {"unit_id": "a", "depends_on": ["missing"]}]}), encoding="utf-8")
            self.assertEqual(built(home)["source"], "native")
        for session in ("", "no-such-session"):
            graph = build_delegation_graph(Path("/nonexistent/omh"), Path("/nonexistent/hermes"), session, now=NOW)
            self.assertEqual(graph["status"], "inactive")

    def test_a_hermes_home_that_cannot_be_searched_never_raises(self) -> None:
        # Python 3.11's `Path.is_file` raises PermissionError under a directory it cannot search; 3.14 answers False.
        # Patched, so every version takes 3.11's path: the graph is unreadable (main's answer), the lineage one id.
        with homes() as home:
            start(home, "child-0", "sa-0", "Lane", now=NOW)
            with patch.object(Path, "is_file", side_effect=PermissionError(13, "Permission denied")):
                graph = built(home)
                segments = graph_segments(home.hermes, PARENT)
            self.assertEqual((graph["status"], graph["reason"]), ("inactive", "unreadable:PermissionError"))
            self.assertEqual(segments, [PARENT])
            if os.name != "nt" and os.geteuid() != 0:  # a real unsearchable home, wherever permissions bind
                home.hermes.chmod(0)
                try:
                    graph, segments = built(home), graph_segments(home.hermes, PARENT)
                finally:
                    home.hermes.chmod(0o700)
                self.assertIn(graph["status"], ("active", "inactive"))
                self.assertEqual(segments, [PARENT])



def _layered_graph(states: list[str], width: int = 3, summary: int = 400) -> dict:
    """A run of `len(states)` layers of `width` lanes, each lane waiting on every lane of the layer above it."""
    from omh.plugin_bundle.omh.delegation_graph import _finish

    lanes, edges = [], []
    for at, state in enumerate(states):
        for index in range(width):
            lane = f"L{at}-{index}"
            lanes.append({"id": lane, "kind": "lane", "state": state, "order": at * width + index, "group": f"layer {at + 1}",
                          "summary": "x" * summary})
            edges += [{"from": f"L{at - 1}-{up}", "to": lane, "kind": "depends_on"} for up in range(width)] if at else [
                {"from": "root", "to": lane, "kind": "dispatch"}]
    return _finish("run", [{"id": "root", "kind": "root"}, *lanes], edges, "session", source="dag")


class LayerBoundTests(unittest.TestCase):
    """The graph is cut by layer, outward from the frontier, and the pane's open layers come whole."""

    def _bounded(self, graph: dict, open_layers=(), byte_limit: int = 6_000) -> dict:
        from omh.plugin_bundle.omh import delegation_graph

        with patch.object(delegation_graph, "GRAPH_BYTE_LIMIT", byte_limit):
            return delegation_graph._bounded(graph, open_layers)

    @staticmethod
    def _kept_layers(graph: dict) -> list[int]:
        return sorted({node["layer"] for node in graph["nodes"] if node.get("kind") != "root"})

    def test_a_deep_run_keeps_the_layers_around_its_frontier_not_the_root_alone(self) -> None:
        # Regression: every kept lane used to pull in all it waits on, so a deep run fell through to the root alone.
        graph = self._bounded(_layered_graph(["done"] * 5 + ["running"] + ["waiting"] * 6))
        kept = self._kept_layers(graph)
        self.assertIn(5, kept)
        self.assertEqual(kept, list(range(kept[0], kept[-1] + 1)), "whole layers, outward from the frontier")
        ids = {node["id"] for node in graph["nodes"]}
        self.assertTrue(all(edge["from"] in ids and edge["to"] in ids for edge in graph["edges"]))
        self.assertEqual(sum(row["count"] for row in graph["layer_hidden"]), graph["hidden_nodes"])
        self.assertEqual(len(graph["layer_hidden"]), 12)
        self.assertLessEqual(len(json.dumps(graph, sort_keys=True, default=str)), 6_000)

    def test_an_open_layer_comes_whole_however_far_from_the_frontier(self) -> None:
        graph = self._bounded(_layered_graph(["done"] * 5 + ["running"] + ["waiting"] * 6), open_layers=(0, 11))
        kept = self._kept_layers(graph)
        self.assertIn(0, kept)
        self.assertIn(11, kept)
        self.assertEqual((graph["layer_hidden"][0]["count"], graph["layer_hidden"][11]["count"]), (0, 0))

    def test_a_graph_that_fits_is_unchanged_unless_the_pane_holds_layers_open(self) -> None:
        small = _layered_graph(["done", "running"], width=2, summary=10)
        self.assertIs(self._bounded(small), small)
        opened = self._bounded(small, open_layers=(1,))
        # Named open layers: every lane carries its layer and nothing is counted lost, so the pane asks the same again.
        self.assertEqual([node.get("layer") for node in opened["nodes"]], [None, 0, 0, 1, 1])
        self.assertEqual(opened["hidden_nodes"], 0)
        self.assertEqual([row["count"] for row in opened["layer_hidden"]], [0, 0])

    def test_open_layers_are_read_from_the_query_as_digits_only(self) -> None:
        from omh.plugin_bundle.omh.dashboard.plugin_api import OPEN_LAYER_LIMIT, open_layers

        self.assertEqual(open_layers("3, 1,3,x,-2,1e3,"), (3, 1))
        self.assertEqual(open_layers(""), ())
        self.assertEqual(len(open_layers(",".join(str(at) for at in range(OPEN_LAYER_LIMIT + 9)))), OPEN_LAYER_LIMIT)


if __name__ == "__main__":
    unittest.main()
