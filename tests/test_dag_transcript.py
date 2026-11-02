"""The dag-ulw graph printed into the TUI transcript: at define, repair, extend and the run's end, once each.

The `omh_dag` results are the tool's own, from runs kept through its handler;
the app gets them as Hermes' `tool.complete` events and reads the graph the
way its panel does (`dag_block.read_graph`).
"""

from __future__ import annotations

import json
import unittest

from _local_package import load_local_package

load_local_package()

from _delegation_graphs import graph, lane, root  # noqa: E402
from _delegation_state import PARENT, homes  # noqa: E402
from omh.plugin_bundle.omh import dag_run  # noqa: E402
from omh.plugin_bundle.omh.delegation_graph import build_delegation_graph  # noqa: E402
from omh.tui import dag_block  # noqa: E402
from omh.tui.gateway import Event  # noqa: E402
from omh.tui.transcript import block_rows  # noqa: E402
from test_dag_tool import (  # noqa: E402
    HOME_UNUSABLE, Answers, Terminal, call, handoff, node, slots_table, terminal_env,
)
from _tui_lines import lines_text  # noqa: E402
from test_tui_modes import SID, make_app  # noqa: E402
from test_tui_muscle_memory import send  # noqa: E402
from test_tui_panels import THEME  # noqa: E402

NODES = [node("api", scope=("src/api.py",), label="Export API"), node("ui", scope=("src/ui.py",), label="Export button"),
         node("verify", depends_on=("api", "ui"), label="Verify export", role="verify")]


def completed(result: dict, *, name: str = "omh_dag", tool_id: str = "t1") -> Event:
    return Event("tool.complete", SID, {"tool_id": tool_id, "name": name, "result": json.dumps(result)})


def run_results(home) -> dict[str, dict]:
    """One result per action of a run that is defined, repaired, settled to done, extended, and done again."""
    slots_table(home)
    results = {"define": call(action="define", run="export", name="export feature", nodes=NODES)}
    results["reused"] = call(action="define", run="export", name="export feature", nodes=NODES)
    results["status"] = call(action="status", run="export")
    handoff(home, "export", "api")
    results["settle"] = call(action="settle", run="export", node="api", outcome="accepted")
    call(action="settle", run="export", node="ui", outcome="failed")
    results["repair"] = call(action="repair", run="export", node="ui", nodes=[
        node("ui-fix", scope=("src/ui.py",), label="Fix the button")])
    handoff(home, "export", "ui-fix")
    call(action="settle", run="export", node="ui-fix", outcome="accepted")
    handoff(home, "export", "verify")
    results["end"] = call(action="settle", run="export", node="verify", outcome="accepted")
    results["status-end"] = call(action="status", run="export")
    results["ready"] = call(action="ready", run="export")
    results["extend"] = call(action="extend", run="export", nodes=[
        node("csv", scope=("src/api.py",), depends_on=("api",), label="CSV export"),
        node("verify-csv", depends_on=("csv",), label="Verify CSV", role="verify")])
    for node_id in ("csv", "verify-csv"):
        handoff(home, "export", node_id)
        results[f"end-{node_id}"] = call(action="settle", run="export", node=node_id, outcome="accepted")
    return results


class MomentTests(unittest.TestCase):
    def test_define_repair_extend_and_the_end_print_and_nothing_else_does(self) -> None:
        with homes() as home:
            results = run_results(home)
        ended: set[tuple[str, int]] = set()
        seen = {key: dag_block.moment({"name": "omh_dag", "result": json.dumps(result)}, ended)
                for key, result in results.items()}
        self.assertEqual(seen["define"], ("plan", "export", []))
        self.assertEqual(seen["repair"], ("repair · +1 node", "export", ["ui-fix"]))
        self.assertEqual(seen["extend"], ("extend · +2 nodes", "export", ["csv", "verify-csv"]))
        self.assertEqual(seen["end"], ("end · done · verified", "export", []))
        self.assertEqual(seen["end-verify-csv"], ("end · done · verified", "export", []))  # the extended run ends again
        for quiet in ("reused", "status", "settle", "ready", "end-csv"):
            self.assertIsNone(seen[quiet], quiet)
        # A status or ready that reads an ended run is not its end, even where no end was printed yet.
        for late in ("status-end", "ready"):
            self.assertIsNone(dag_block.moment({"name": "omh_dag", "result": json.dumps(results[late])}, set()), late)
        # The same end read again prints nothing: one block per moment.
        self.assertIsNone(dag_block.moment({"name": "omh_dag", "result": json.dumps(results["end"])}, ended))
        self.assertIsNone(dag_block.moment({"name": "terminal", "result": json.dumps(results["define"])}, set()))
        self.assertIsNone(dag_block.moment({"name": "omh_dag", "result": json.dumps(
            {"status": "refused", "action": "define", "reason": "dependency_cycle"})}, set()))

    def test_a_run_done_without_a_verify_node_ends_unverified_wherever_its_end_is_drawn(self) -> None:
        """Mutation: drop the verdict from the end title, the one-line summary, or the messenger end block."""
        from omh.plugin_bundle.omh.delegation_snapshot import end_block, lanes_of
        from omh.tui.panels import dag_run_summary

        self.assertEqual(dag_block.VERDICTS, dag_run.VERDICTS)
        with homes() as home:
            slots_table(home)
            call(action="define", run="export", name="export feature", nodes=NODES[:2])
            for node_id in ("api", "ui"):
                handoff(home, "export", node_id)
                end = call(action="settle", run="export", node=node_id, outcome="accepted")
            graph = build_delegation_graph(home.omh, home.hermes, PARENT)
        self.assertEqual(dag_block.moment({"name": "omh_dag", "result": json.dumps(end)}, set()),
                         ("end · done · unverified", "export", []))
        self.assertEqual(graph["dag_verdict"], "unverified")
        self.assertEqual(dag_run_summary(graph), "DAG · export feature · done 2/2 · unverified")
        self.assertTrue(end_block(graph, lanes_of(graph)).splitlines()[1].endswith("ended · unverified"))
        # A word the payload does not know is not printed.
        self.assertEqual(dag_block.moment({"name": "omh_dag", "result": json.dumps({**end, "verdict": "goal met"})},
                                          set()), ("end · done", "export", []))


class BlockTests(unittest.TestCase):
    def _graphs(self) -> tuple[dict, dict]:
        """The plan (two producers fanning in to a verification) and the same run after a repair."""
        with homes() as home:
            slots_table(home)
            call(action="define", run="export", name="export feature", nodes=NODES)
            plan = build_delegation_graph(home.omh, home.hermes, PARENT)
            call(action="settle", run="export", node="ui", outcome="failed")
            call(action="repair", run="export", node="ui", nodes=[node("ui-fix", scope=("src/ui.py",),
                                                                        label="Fix the button")])
            return plan, build_delegation_graph(home.omh, home.hermes, PARENT)

    @staticmethod
    def _text(block: dag_block.DagBlock, width: int) -> list[str]:
        return ["".join(span.text for span in line) for line in block_rows(block, width, THEME)]

    def test_boxes_where_they_fit_the_tree_where_they_do_not(self) -> None:
        plan, _repaired = self._graphs()
        wide = self._text(dag_block.DagBlock("plan", plan), 140)
        narrow = self._text(dag_block.DagBlock("plan", plan), 24)  # under one box's width
        self.assertEqual(wide[0].strip(), "dag-ulw plan")
        self.assertTrue(any("┌" in line for line in wide), wide)
        self.assertFalse(any("┌" in line for line in narrow), narrow)
        self.assertTrue(any("├─" in line or "└─" in line for line in narrow), narrow)
        self.assertTrue(all(len(line) <= 24 for line in narrow), narrow)

    def test_an_added_node_names_where_it_came_from_once(self) -> None:
        _plan, repaired = self._graphs()
        block = dag_block.DagBlock("repair · +1 node", repaired)
        boxes, tree = self._text(block, 140), self._text(block, 24)
        self.assertEqual(boxes[0].strip(), "dag-ulw repair · +1 node")
        # As boxes: the drawing's own repair mark, a parents line naming the node it repairs and the connector into
        # its box; the block adds no mark of its own, so none is doubled. No Dependencies list. The gap into the repair
        # is crossed by Verify export's edges, which skip it (Verify sits below the repair that runs first), so it is
        # the one centred connector that draws no edge (`▽`), and the parents line names the edge.
        added = next(index for index, line in enumerate(boxes) if "↻ Fix the button" in line)
        self.assertIn("← Export button", boxes[added + 3])
        self.assertEqual(boxes[added - 2].strip(), "▽")
        self.assertNotIn("Dependencies", "\n".join(boxes))
        self.assertFalse([line for line in boxes if "+ " in line and "Fix" in line], boxes)
        # As the tree: nested under the node it repairs.
        failed = next(index for index, line in enumerate(tree) if "Export bu" in line)
        self.assertTrue(any("Fix" in line for line in tree[failed + 1:failed + 4]), tree)

    def test_a_node_carries_its_prompts_first_clause_as_its_summary(self) -> None:
        """Mutation: drop the summary from `_dag_nodes`, clean the prompt before cutting its clause, or keep `TASK:`.

        dag-ulw writes a node prompt one field a line (TASK, DELIVERABLE, SCOPE, VERIFY, STOP WHEN; its SKILL.md):
        cleaned first, the line ends go and the task runs into `DELIVERABLE:`."""
        from omh.plugin_bundle.omh.delegation_graph import _prompt_summary

        long_task = "Move every caller of the old exporter onto the new streaming writer and delete the shim afterwards"
        nodes = [node("api", label="Export API", prompt="TASK: Rebase the branch onto main\nDELIVERABLE: green CI"
                      "\nSCOPE: src/api.py\nVERIFY: run `make test`, exit 0\nSTOP WHEN: green"),
                 node("ui", label="Export button", prompt="TASK:\n  Wire the button to the endpoint\r\nDELIVERABLE: "
                      "a button\r\nSTOP WHEN: it exports"),
                 node("docs", label="Export docs", prompt="TASK: Add the CSV endpoint to the API. Keep the JSON one."),
                 node("cli", label="Export CLI", prompt="Document the flag VERIFY: run `omh --help`"),
                 node("move", label="Move callers", prompt=f"TASK: {long_task}\nSTOP WHEN: green")]
        with homes() as home:
            slots_table(home)
            call(action="define", run="export", name="export feature", nodes=nodes)
            built = build_delegation_graph(home.omh, home.hermes, PARENT)
        summaries = {item["dag_node"]: item.get("summary") for item in built["nodes"] if item.get("dag_node")}
        self.assertEqual(summaries, {"api": "Rebase the branch onto main", "ui": "Wire the button to the endpoint",
                                     "docs": "Add the CSV endpoint to the API", "cli": "Document the flag",
                                     "move": long_task[:80]})
        self.assertEqual(_prompt_summary("Task: Fix the flaky test\nDELIVERABLE: green"), "Fix the flaky test")
        self.assertEqual(_prompt_summary("task: fix the flaky test"), "fix the flaky test")
        self.assertEqual(_prompt_summary("   \n"), "")
        self.assertEqual(_prompt_summary(None), "")

    def test_the_end_block_and_the_collapsed_run_say_a_handoff_was_not_checked(self) -> None:
        """Mutation: drop the word from the graph's node, or leave the one-line summary as it was."""
        from omh.tui.panels import dag_run_summary

        # An SSH terminal whose environment is gone when api settles; the others' handoffs are on the host.
        terminal = Terminal("ssh", Answers(HOME_UNUSABLE))  # this host's path for the run, read there first
        with homes() as home, terminal_env(), terminal.modules():
            slots_table(home)
            call(action="define", run="export", name="export feature", nodes=NODES)
            terminal.environment = None
            call(action="settle", run="export", node="api", outcome="accepted")
            for node_id in ("ui", "verify"):
                handoff(home, "export", node_id)
                end = call(action="settle", run="export", node=node_id, outcome="accepted")
            graph = build_delegation_graph(home.omh, home.hermes, PARENT)
        self.assertEqual(dag_block.moment({"name": "omh_dag", "result": json.dumps(end)}, set()),
                         ("end · done · verified", "export", []))
        text = self._text(dag_block.DagBlock("end · done", graph), 140)
        self.assertEqual(sum("Handoff not checked" in line for line in text), 1, text)
        self.assertEqual(dag_run_summary(graph), "DAG · export feature · done 3/3 · 1 handoff not checked · verified")


def big_run(sizes: tuple[int, ...], states: dict[str, str] | None = None) -> dict:
    """A dag run's graph with ``sizes[i]`` nodes in layer ``i + 1``, each after the first node of the layer above;
    ``states`` sets a node's state by its dag node id (``n<order>``), the rest wait."""
    nodes, edges, above = [root()], [], ""
    order = 0
    for layer, size in enumerate(sizes, 1):
        first = ""
        for _index in range(size):
            order += 1
            key = f"n{order}"
            nodes.append({**lane(f"d:r1:{key}", f"Migrate service {order} config", "quick", "glm-5.3-flash", "low",
                                 (states or {}).get(key, "waiting"), order=order, group=f"layer {layer}"),
                          "dag_node": key})
            edges.append((above or "root", f"d:r1:{key}", "depends_on" if above else "dispatch"))
            first = first or f"d:r1:{key}"
        above = first
    return graph(nodes, edges, name="service migration")


class CondensedTests(unittest.TestCase):
    """A run of up to `SMALL_GRAPH_LANES` lanes prints every box; a bigger one is condensed: its header, a row per
    layer, the boxes the moment changed and how many nodes it leaves to `/dag`; a big run's end is its tally and the
    nodes that stopped. Neither prints Dependencies or Node details, which `/dag` keeps."""

    @staticmethod
    def _text(block: dag_block.DagBlock, width: int = 140) -> list[str]:
        return ["".join(span.text for span in line) for line in block_rows(block, width, THEME)]

    def test_twelve_lanes_print_every_box_and_thirteen_condense(self) -> None:
        self.assertEqual(dag_block.SMALL_GRAPH_LANES, 12)
        small = self._text(dag_block.DagBlock("plan", big_run((4, 7, 1))))
        text = "\n".join(small)
        self.assertEqual([index for index in range(1, 14) if f"Migrate service {index} config " in text],
                         list(range(1, 13)), "every box")
        self.assertIn("┌", text)
        self.assertTrue(any("│" in line and "Waiting" in line for line in small))
        for gone in ("Dependencies", "Node details", "more nodes", "layer 1 ·"):
            self.assertNotIn(gone, text)
        big = self._text(dag_block.DagBlock("plan", big_run((4, 8, 1))))
        self.assertEqual([line.strip() for line in big[:5]], [
            "dag-ulw plan", "DAG · service migration · 13 nodes · 9 edges · 13 waiting",
            "layer 1 · 4 nodes · 4 waiting", "layer 2 · 8 nodes · 8 waiting", "layer 3 · 1 node · 1 waiting"])
        self.assertEqual(big[-1].strip(), "… 9 more nodes · /dag shows the whole graph")
        # Lanes the graph reader left out count: 12 drawn and 1 hidden is a run of 13.
        hidden = self._text(dag_block.DagBlock("plan", {**big_run((4, 7, 1)), "hidden_nodes": 1}))
        self.assertEqual(hidden[-1].strip(), "… 9 more nodes · /dag shows the whole graph")

    def test_a_big_print_is_condensed_whatever_the_screen(self) -> None:
        big = big_run((4, 40, 1))
        condensed = self._text(dag_block.DagBlock("plan", big))
        self.assertLessEqual(len(condensed), 20)
        self.assertEqual([line.strip() for line in condensed[:5]], [
            "dag-ulw plan", "DAG · service migration · 45 nodes · 41 edges · 45 waiting",
            "layer 1 · 4 nodes · 4 waiting", "layer 2 · 40 nodes · 40 waiting", "layer 3 · 1 node · 1 waiting"])
        text = "\n".join(condensed)
        for gone in ("Dependencies", "Node details"):
            self.assertNotIn(gone, text)
        # At define, the boxes are the first layer's, the plan's start.
        self.assertEqual([index for index in range(1, 46) if f"Migrate service {index} config " in text],
                         [1, 2, 3, 4])
        self.assertEqual(condensed[-1].strip(), "… 41 more nodes · /dag shows the whole graph")

    def test_a_layer_cut_by_the_graph_reader_says_what_it_kept_of_how_many(self) -> None:
        big = {**big_run((4, 40, 1)), "hidden_by_group": {"layer 2": 600}, "hidden_nodes": 600}
        condensed = self._text(dag_block.DagBlock("plan", big))
        self.assertEqual(condensed[3].strip(), "layer 2 · 40 of 640 nodes · 40 waiting")
        self.assertEqual(condensed[-1].strip(), "… 641 more nodes · /dag shows the whole graph")

    def test_a_layer_the_cap_emptied_keeps_its_row_in_its_place(self) -> None:
        big = big_run((4, 40, 9))
        for item in big["nodes"]:
            if item.get("group") == "layer 3":
                item["group"] = "layer 4"  # layer 3 is the one the graph reader's cap emptied
        big.update(hidden_nodes=161, hidden_by_group={"layer 3": 161},
                   group_order=["layer 1", "layer 2", "layer 3", "layer 4"])
        condensed = self._text(dag_block.DagBlock("plan", big))
        self.assertEqual([line.strip() for line in condensed[2:6]], [
            "layer 1 · 4 nodes · 4 waiting", "layer 2 · 40 nodes · 40 waiting", "layer 3 · 0 of 161 nodes",
            "layer 4 · 9 nodes · 9 waiting"])

    def test_a_repair_draws_the_nodes_it_added_naming_what_they_wait_on(self) -> None:
        big = big_run((4, 40, 1), {"n1": "done", "n6": "failed", "n7": "running"})
        condensed = self._text(dag_block.DagBlock("repair · +1 node", big, added=("n7",)))
        self.assertEqual(condensed[3].strip(), "layer 2 · 40 nodes · 1 running · 1 failed · 38 waiting")
        boxes = [line for line in condensed if "│" in line]
        self.assertEqual([line.strip(" │") for line in boxes], [
            "Migrate service 7 config", "quick · glm-5.3-flash:low", "● Running", "← Migrate service 1 conf…"])
        self.assertEqual(condensed[-1].strip(), "… 44 more nodes · /dag shows the whole graph")

    def test_a_big_runs_end_is_its_tally_and_the_nodes_that_stopped(self) -> None:
        states = {f"n{index}": "done" for index in range(1, 46)}
        states.update(n2="failed", n9="stuck")
        condensed = self._text(dag_block.DagBlock("end · failed", big_run((4, 40, 1), states)))
        self.assertEqual([line.strip() for line in condensed], [
            "dag-ulw end · failed", "DAG · service migration · 45 nodes · 1 stuck · 1 failed · 43 done",
            "✗ Migrate service 2 config · failed", "! Migrate service 9 config · stuck"])
        # The tally is the whole run's: lanes the graph reader's cap left out count, by the state they ended in.
        capped = {**big_run((4, 40, 1), states), "hidden_nodes": 965, "hidden_by_state": {"done": 963, "failed": 2}}
        self.assertEqual([line.strip() for line in self._text(dag_block.DagBlock("end · failed", capped))], [
            "dag-ulw end · failed", "DAG · service migration · 1,010 nodes · 1 stuck · 3 failed · 1,006 done",
            "✗ Migrate service 2 config · failed", "! Migrate service 9 config · stuck", "… 2 more"])
        # A small run's end is its boxes in their final states: they are the tally.
        small = self._text(dag_block.DagBlock("end · failed", big_run((2, 1), {"n1": "done", "n2": "failed",
                                                                               "n3": "done"})))
        self.assertEqual(sum("┌" in line for line in small), 2, "two frontiers of boxes")
        self.assertEqual([word for word in ("✓ Done", "✗ Failed") if any(word in line for line in small)],
                         ["✓ Done", "✗ Failed"])


def turn_ended() -> Event:
    return Event("message.complete", SID, {"text": "done"})


class AppTests(unittest.TestCase):
    @staticmethod
    def _app(graphs: list[dict]) -> object:
        """An app whose graph reads return ``graphs`` in turn (the last one from then on)."""
        app, _client = make_app(rows=60, cols=140)
        app.stored_id = PARENT

        def read(_omh: object, _hermes: object, session: str) -> dict | None:
            if session != PARENT:
                return None
            return graphs.pop(0) if len(graphs) > 1 else graphs[0]

        app.read_dag_graph = read
        return app

    @staticmethod
    def _titles(app) -> list[str]:
        return [block.title for block in app.transcript.blocks + app.transcript._held
                if isinstance(block, dag_block.DagBlock)]

    def test_the_app_appends_one_block_per_moment_and_none_on_a_settle(self) -> None:
        with homes() as home:
            results = run_results(home)
            graph = build_delegation_graph(home.omh, home.hermes, PARENT)
        app = self._app([graph])
        for index, key in enumerate(("define", "status", "settle", "repair", "end", "end")):
            app._on_event(completed(results[key], tool_id=f"t{index}"))
        self.assertEqual(self._titles(app), ["plan", "repair · +1 node"], "the end waits for the turn's end")
        app._on_event(turn_ended())
        for index, key in enumerate(("ready", "extend")):
            app._on_event(completed(results[key], tool_id=f"u{index}"))
        app._on_event(turn_ended())
        self.assertEqual(self._titles(app), ["plan", "repair · +1 node", "end · done · verified", "extend · +2 nodes"])
        self.assertEqual(dag_run.DAG_SCHEMA_VERSION, "omh_dag/v1")

    def test_a_repair_print_names_the_nodes_it_added(self) -> None:
        with homes() as home:
            results = run_results(home)
            graph = build_delegation_graph(home.omh, home.hermes, PARENT)
        app = self._app([graph])
        for index, key in enumerate(("define", "repair", "end")):
            app._on_event(completed(results[key], tool_id=f"t{index}"))
        app._on_event(turn_ended())
        blocks = [block for block in app.transcript.blocks + app.transcript._held
                  if isinstance(block, dag_block.DagBlock)]
        self.assertEqual([(block.title, block.added) for block in blocks], [
            ("plan", ()), ("repair · +1 node", ("ui-fix",)), ("end · done · verified", ())])

    def test_an_end_the_same_turn_extends_prints_nothing_and_the_last_end_prints_once(self) -> None:
        with homes() as home:
            results = run_results(home)
            graph = build_delegation_graph(home.omh, home.hermes, PARENT)
        app = self._app([graph])
        # The goal check extends the run in the turn that ended it: the extend's block stands for both.
        for index, key in enumerate(("define", "end", "extend")):
            app._on_event(completed(results[key], tool_id=f"t{index}"))
        app._on_event(turn_ended())
        self.assertEqual(self._titles(app), ["plan", "extend · +2 nodes"])
        app._on_event(completed(results["end-verify-csv"], tool_id="t9"))
        app._on_event(turn_ended())
        app._on_event(turn_ended())
        self.assertEqual(self._titles(app), ["plan", "extend · +2 nodes", "end · done · verified"])

    def test_an_end_whose_run_moved_on_before_the_turn_ended_prints_nothing(self) -> None:
        with homes() as home:
            results = run_results(home)
            graph = build_delegation_graph(home.omh, home.hermes, PARENT)
        app = self._app([graph, {**graph, "dag_open": True}])
        app._on_event(completed(results["define"], tool_id="t0"))
        app._on_event(completed(results["end"], tool_id="t1"))
        app._on_event(turn_ended())
        self.assertEqual(self._titles(app), ["plan"])


class ToolRowTests(unittest.TestCase):
    def test_a_delegate_task_row_shows_the_node_labels_not_their_markers(self) -> None:
        app, _client = make_app(rows=30, cols=140)
        app._on_event(Event("tool.start", SID, {"tool_id": "d1", "name": "delegate_task",
                                                "context": "2 tasks: Export API [dag:export/api] | Export docs [dag:export/docs]"}))
        app._on_event(Event("tool.start", SID, {"tool_id": "d2", "name": "terminal", "context": "echo [dag:a/b] kept"}))
        text = "\n".join(lines_text(app.transcript.live_lines(140, THEME)))
        self.assertIn("delegate_task(2 tasks: Export API | Export docs)", text)
        self.assertIn("terminal(echo [dag:a/b] kept)", text)  # only a delegate_task preview carries node goals

    def test_a_marker_hermes_cut_goes_too(self) -> None:
        """Hermes cuts each goal of the preview to 40 characters (`agent/display.py` `_tail_trunc`, `...`), so a label
        shorter than 37 characters can leave the head of its marker; these are its previews at d923a5eb48."""
        cases = {
            "1 tasks: Wire the export button to API [dag:ex...": "1 tasks: Wire the export button to API",
            "1 tasks: Document the CSV export in the API [d...": "1 tasks: Document the CSV export in the API",
            "1 tasks: Document the CSV export in the APIs [...": "1 tasks: Document the CSV export in the APIs",
            "2 tasks: Refresh docs [omh-team:hud-graph/docs... | Fix the parser [omh-team:...":
                "2 tasks: Refresh docs | Fix the parser",
            "2 tasks: Fix [omh-team:t1/a/attempt-1] | Docs [omh-team:t1/b/attempt-1]": "2 tasks: Fix | Docs",
            # A goal handed out before an update opens with its marker; a lone `goal` argument previews as itself.
            "2 tasks: [dag:export/ui] Export button | [dag:export/docs] Export docs": "2 tasks: Export button | Export docs",
            "[dag:export/ui] Export button": "Export button",
            # A whole marker goes wherever it is: a model may add text after it.
            "1 tasks: Export API [dag:export/api]. Please h...": "1 tasks: Export API. Please h...",
            "1 tasks: Export API [dag:export/api] Extra ins...": "1 tasks: Export API Extra ins...",
            # Hermes' 80-character cut of the whole row can follow a goal's own cut: the head still goes.
            "3 tasks: Render t [dag:export/n0] | Render the invoice PDFs f [dag:export... ...":
                "3 tasks: Render t | Render the invoice PDFs f ...",
            "3 tasks: Render t [dag:export/n0] | Render the invoice PDFs from the b [d... ...":
                "3 tasks: Render t | Render the invoice PDFs from the b ...",
            # Only a head that ends its goal is a cut marker.
            "1 tasks: Explain the [dag:...] marker syntax": "1 tasks: Explain the [dag:...] marker syntax",
            # A cut that took no marker keeps its `...`, and so does a label's own bracket.
            "1 tasks: Render invoice PDFs from the new temp...": "1 tasks: Render invoice PDFs from the new temp...",
            "1 tasks: Handle [...] in args [dag:a/b]": "1 tasks: Handle [...] in args",
            # A head too short to name its kind goes only after the space OMH writes before a marker.
            "1 tasks: Investigate the flaky test in tests/[...": "1 tasks: Investigate the flaky test in tests/[...",
        }
        for context, shown in cases.items():
            with self.subTest(context=context):
                app, _client = make_app(rows=30, cols=140)
                app._on_event(Event("tool.start", SID, {"tool_id": "d1", "name": "delegate_task", "context": context}))
                text = "\n".join(lines_text(app.transcript.live_lines(140, THEME)))
                self.assertIn(f"delegate_task({shown})", text)


class PagerTests(unittest.TestCase):
    def test_dag_closes_a_runs_graph_with_its_critical_path_and_bottlenecks(self) -> None:
        with homes() as home:
            slots_table(home)
            call(action="define", run="export", name="export feature", nodes=NODES)
            graph = build_delegation_graph(home.omh, home.hermes, PARENT)
        app, _client = make_app(rows=30, cols=120)
        app.hud = type("Hud", (), {"payload": {"privacy": "metadata_only", "delegation_graph": graph},
                                   "received_at": None})()
        send(app, "/dag")
        app._render()  # the pager draws the HUD's newest read at each frame
        rows = lines_text(app.pager.lines)
        self.assertTrue(any("┌" in row for row in rows), rows)
        self.assertEqual(rows[-3:], ["", "critical path: Export API → Verify export",
                                     "bottlenecks: Export API (blocks 1) · Export button (blocks 1)"])

    def test_a_graph_that_is_not_a_dag_run_gets_no_topology_lines(self) -> None:
        from _delegation_graphs import owner_mock

        app, _client = make_app(rows=30, cols=120)
        app.hud = type("Hud", (), {"payload": {"privacy": "metadata_only", "delegation_graph": owner_mock()},
                                   "received_at": None})()
        send(app, "/dag")
        app._render()
        rows = lines_text(app.pager.lines)
        self.assertTrue(rows)
        self.assertFalse([row for row in rows if row.startswith(("critical path", "bottlenecks"))], rows)


if __name__ == "__main__":
    unittest.main()
