"""A dag-ulw run in the TUI panel: the plan, the graph and the agents each say a different thing once.

The split the panel keeps for a dag run:

* `[Plan]` holds the run's layers, one item per layer, the way the skill tells
  the parent to declare them (`todo_list`, which OMH mirrors, or `omh_todo`);
* the delegation block draws the nodes and their edges, with each bound
  child's model and state on its node;
* the agents block (`● main │ …`) lists only the children the graph does not
  draw (here one with no ledger row, which started before the hooks were
  registered), and says so;
* the app's roster, which names the agents under the composer, names a node's
  child by the node's label, not by the `[dag:<run>/<node>]` marker that binds
  it;
* once the run is over the graph block collapses to its one summary line,
  and `/dag` still opens the whole graph.

The run is kept through the `omh_dag` handler and the plan through
`omh_todo`, the payload is `read_omh_hud`'s, and the rows are `panel_lines`'.
"""

from __future__ import annotations

import json
import time
import unittest

from _local_package import load_local_package

load_local_package()

from _delegation_state import PARENT, homes, start  # noqa: E402
from omh.plugin_bundle.omh.runtime_reader import read_omh_hud  # noqa: E402
from omh.plugin_bundle.omh.tools import dag_tool  # noqa: E402
from omh.plugin_bundle.omh.tools.todo_tool import omh_todo_handler  # noqa: E402
from omh.tui.panels import panel_lines  # noqa: E402
from omh.tui.subagents import Roster  # noqa: E402
from test_tui_panels import THEME  # noqa: E402

PROMPT = "TASK: t\nDELIVERABLE: d\nSCOPE: s\nVERIFY: v\nSTOP WHEN: w"
NODES = [
    {"id": "api", "label": "Export API", "category": "quick", "prompt": PROMPT, "write_scope": ["src/api.py"]},
    {"id": "ui", "label": "Export button", "category": "unspecified-low", "prompt": PROMPT,
     "write_scope": ["src/ui.py"]},
    {"id": "verify", "label": "Verify export", "category": "unspecified-high", "prompt": PROMPT,
     "depends_on": ["api", "ui"]},
]
LAYERS = ["Build the API and the button", "Verify the export"]


def child(home, session: str, *, now: float, goal: str = "") -> None:
    """A native child of the parent; with a goal its start reached the ledger, without one it did not."""
    if goal:
        start(home, session, f"sa-{session}", goal, now=now)
    home.session(session, "glm-5.3-flash", parent=PARENT, effort="low", started=now)
    home.execute("UPDATE sessions SET parent_session_id = ? WHERE id = ?", (PARENT, session))
    home.usage(session, "glm-5.3-flash", last_seen=now)


def dag_run_handoff(home, node: str):
    from omh.plugin_bundle.omh import dag_run

    return dag_run.handoff_path(home.omh, PARENT, "export", node)


def panel(home) -> list[str]:
    payload = read_omh_hud(home.omh, home.hermes, session_ref=PARENT, status={"runs": []})
    return ["".join(span.text for span in line) for line in panel_lines(payload, 120, 60, THEME, time.time())]


class DagPanelSplitTests(unittest.TestCase):
    def test_plan_holds_layers_graph_holds_nodes_agents_holds_only_what_the_graph_does_not(self) -> None:
        with homes() as home:
            home.execute("ALTER TABLE async_delegations ADD COLUMN owner_pid INTEGER")
            home.session(PARENT, "claude-opus-5-5", effort="high")
            defined = json.loads(dag_tool.omh_dag_handler(
                {"action": "define", "run": "export", "name": "export feature", "nodes": NODES}, session_id=PARENT))
            self.assertEqual(defined["status"], "ok", defined)
            written = json.loads(omh_todo_handler({"action": "set", "title": "export feature", "items": [
                {"text": LAYERS[0], "state": "active"}, {"text": LAYERS[1], "state": "pending"}]},
                session_id=PARENT))
            self.assertEqual(written["status"], "written", written)
            now = time.time()  # after define handed api and ui out: their children start now
            child(home, "20261021_100001_api", now=now, goal="Export API [dag:export/api]")
            child(home, "20261021_100002_ui", now=now, goal="Export button [dag:export/ui]")
            child(home, "20261021_095959_early", now=now - 9)  # no ledger row: the graph cannot draw it
            lines = panel(home)
        text = "\n".join(lines)
        agents = next(index for index, line in enumerate(lines) if line.startswith("● main │"))
        dag = next(index for index, line in enumerate(lines) if line.lstrip().startswith("DAG · export feature"))
        plan = next(index for index, line in enumerate(lines) if line.startswith("[Plan]"))
        self.assertLess(agents, dag)
        self.assertLess(dag, plan)
        # The agents block counts and lists only the child outside the graph.
        self.assertIn("1 other agent", lines[agents])
        agent_rows = lines[agents + 1:dag]
        self.assertEqual(len([row for row in agent_rows if row.strip()]), 1, agent_rows)
        # Each node is drawn once, in the graph block, and never as an agent row or a plan item.
        for label in ("Export API", "Export button", "Verify export"):
            self.assertEqual(text.count(label), 1, (label, text))
            self.assertTrue(any(label in line for line in lines[dag:plan]), label)
        # The plan holds the layers, not the nodes.
        self.assertTrue(all(any(layer in line for line in lines[plan:]) for layer in LAYERS), lines[plan:])
        self.assertNotIn("[dag:", text)

    def test_a_finished_run_collapses_to_one_line_and_dag_still_opens_it_whole(self) -> None:
        from omh.tui.panels import dag_page_lines

        with homes() as home:
            home.execute("ALTER TABLE async_delegations ADD COLUMN owner_pid INTEGER")
            home.session(PARENT, "claude-opus-5-5", effort="high")
            json.loads(dag_tool.omh_dag_handler(
                {"action": "define", "run": "export", "name": "export feature", "nodes": NODES}, session_id=PARENT))
            for node in ("api", "ui", "verify"):
                handoff = dag_run_handoff(home, node)
                handoff.parent.mkdir(parents=True, exist_ok=True)
                handoff.write_text("done", encoding="utf-8")
                settled = json.loads(dag_tool.omh_dag_handler(
                    {"action": "settle", "run": "export", "node": node, "outcome": "accepted"}, session_id=PARENT))
            self.assertEqual(settled["state"], "done", settled)
            lines = panel(home)
            payload = read_omh_hud(home.omh, home.hermes, session_ref=PARENT, status={"runs": []})
            page = ["".join(span.text for span in line) for line in dag_page_lines(payload, 120, THEME)[0]]
        dag = [line for line in lines if "export feature" in line]
        self.assertEqual(len(dag), 1, lines)
        self.assertIn("done 3/3", dag[0])
        self.assertFalse([line for line in lines if "Verify export" in line])
        self.assertTrue(any("Verify export" in line for line in page))

    def test_a_run_that_is_not_over_keeps_its_tree_though_every_lane_settled(self) -> None:
        from omh.tui.panels import dag_run_summary

        # The node's child went quiet: its lane reads `unknown`, but the run still has it out.
        graph = {"name": "export feature", "dag_open": True,
                 "nodes": [{"id": "root", "kind": "root"}, {"id": "d:export:api", "kind": "lane", "state": "unknown"}]}
        self.assertEqual(dag_run_summary(graph), "")
        self.assertEqual(dag_run_summary({**graph, "dag_open": False}), "DAG · export feature · done 0/1 · 1 unknown")

    def test_an_outside_lane_is_no_lane_of_the_runs_summary(self) -> None:
        from omh.tui.panels import dag_run_summary

        run = [{"id": "root", "kind": "root"}, {"id": "d:export:api", "kind": "lane", "state": "done"}]
        graph = {"name": "export feature", "nodes": run}
        self.assertEqual(dag_run_summary(graph), "DAG · export feature · done 1/1")
        # A markerless child still running beside a finished run neither holds the run open nor joins its tally.
        outside = {"id": "s:sa-fix", "kind": "lane", "state": "running", "outside_dag": True}
        self.assertEqual(dag_run_summary({**graph, "nodes": [*run, outside]}), "DAG · export feature · done 1/1")
        # The same child unflagged is a lane of the run, as before.
        unflagged = {key: value for key, value in outside.items() if key != "outside_dag"}
        self.assertEqual(dag_run_summary({**graph, "nodes": [*run, unflagged]}), "")

    def test_the_agent_strip_names_a_nodes_child_by_its_label(self) -> None:
        roster = Roster()
        roster.apply("subagent.start", {"subagent_id": "sa-api", "goal": "Export API [dag:export/api]"}, 0.0)
        roster.apply("subagent.start", {"subagent_id": "sa-old", "goal": "[dag:export/ui] Export button"}, 0.0)
        roster.apply("subagent.start", {"subagent_id": "sa-team", "goal": "Refresh docs [omh-team:hud/docs/attempt-1]"},
                     0.0)
        roster.apply("subagent.start", {"subagent_id": "sa-more", "goal": "Export docs [dag:export/docs]. Please hurry"},
                     0.0)
        roster.apply("subagent.start", {"subagent_id": "sa-plain", "goal": "Look [dag: not a marker]"}, 0.0)
        self.assertEqual(roster.agents["sa-api"].goal, "Export API")
        self.assertEqual(roster.agents["sa-old"].goal, "Export button")  # handed out before an update
        self.assertEqual(roster.agents["sa-team"].goal, "Refresh docs")
        self.assertEqual(roster.agents["sa-more"].goal, "Export docs. Please hurry")
        self.assertEqual(roster.agents["sa-plain"].goal, "Look [dag: not a marker]")


if __name__ == "__main__":
    unittest.main()
