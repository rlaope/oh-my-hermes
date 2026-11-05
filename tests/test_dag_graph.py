"""A dag-ulw run where people see it: the delegation graph, its drawing, `omh hud --graph`, and the chat posts.

The run is kept through the `omh_dag` handler and its children start and stop
through the ledger's own hook observers, as in Hermes. The graph reader then
draws the run's nodes with their recorded edges, and a messenger reply gets
the three moments only: a start block, a count line when counts change, and
an end block once the run itself is over.
"""

from __future__ import annotations

import json
import re
import time
import unittest
from unittest.mock import patch

from _local_package import load_local_package

load_local_package()

from _cli_harness import run_cli  # noqa: E402
from _delegation_state import PARENT, homes, start, stop  # noqa: E402
from omh.plugin_bundle.omh import dag_run  # noqa: E402
from omh.plugin_bundle.omh.delegation_graph import build_delegation_graph, graph_fingerprint  # noqa: E402
from omh.plugin_bundle.omh.delegation_view import render_delegation_view  # noqa: E402
from omh.plugin_bundle.omh.hooks import result_transforms  # noqa: E402
from omh.plugin_bundle.omh.tools import dag_tool  # noqa: E402
from test_dag_tool import HOME_UNUSABLE, Answers, Terminal, terminal_env  # noqa: E402

PROMPT = "TASK: t\nDELIVERABLE: d\nSCOPE: s\nVERIFY: v\nSTOP WHEN: w"
NODES = [
    {"id": "api", "label": "Export API", "category": "quick", "prompt": PROMPT, "write_scope": ["src/api.py"]},
    {"id": "ui", "label": "Export button", "category": "unspecified-low", "prompt": PROMPT,
     "write_scope": ["src/ui.py"]},
    {"id": "verify", "label": "Verify export", "category": "unspecified-high", "prompt": PROMPT, "role": "verify",
     "depends_on": ["api", "ui"]},
]


def call(**arguments: object) -> dict:
    return json.loads(dag_tool.omh_dag_handler(arguments, session_id=PARENT))


def write_handoff(home, node: str) -> None:
    path = dag_run.handoff_path(home.omh, PARENT, "export", node)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("done", encoding="utf-8")


def reply(text: str, *, platform: str = "discord", turn: str = "t1") -> str | None:
    return result_transforms.transform_llm_output(
        response_text=text, session_id=PARENT, model="claude-opus-5-5", platform=platform, turn_id=turn
    )


def defined(home) -> None:
    # Hermes' own table carries the owner pid the pool belongs to; with it the slots are read, not guessed.
    home.execute("ALTER TABLE async_delegations ADD COLUMN owner_pid INTEGER")
    home.session(PARENT, "claude-opus-5-5", effort="high")
    home.hermes.joinpath("config.yaml").write_text("delegation:\n  max_concurrent_children: 10\n")
    call(action="define", run="export", name="export feature", nodes=NODES)


def started(home, node: str, *, now: float) -> None:
    start(home, f"child-{node}", f"sa-{node}", f"{node} [dag:export/{node}]", now=now)
    home.session(f"child-{node}", "glm-5.3-flash", parent=PARENT, effort="low")
    home.usage(f"child-{node}", "glm-5.3-flash", last_seen=now)


class GraphTests(unittest.TestCase):
    def test_the_graph_draws_the_run_with_its_recorded_edges(self) -> None:
        with homes() as home:
            defined(home)
            now = time.time()
            started(home, "api", now=now)
            graph = build_delegation_graph(home.omh, home.hermes, PARENT, now=now + 1)
        self.assertEqual(graph["status"], "active")
        self.assertEqual(graph["name"], "export feature")
        self.assertTrue(graph["dag_open"])
        by_id = {node["id"]: node for node in graph["nodes"]}
        self.assertEqual(set(by_id), {"root", "d:export:api", "d:export:ui", "d:export:verify"})
        self.assertEqual(by_id["d:export:api"]["state"], "running")
        self.assertEqual(by_id["d:export:api"]["model"], "glm-5.3-flash")
        self.assertEqual(by_id["d:export:ui"]["state"], "dispatched")
        self.assertEqual((by_id["d:export:ui"]["category"], by_id["d:export:ui"]["category_source"]),
                         ("unspecified-low", "dag_plan"))
        self.assertEqual(by_id["d:export:verify"]["waits_on"], 2)
        edges = {(edge["from"], edge["to"], edge["kind"]) for edge in graph["edges"]}
        self.assertEqual(edges, {("root", "d:export:api", "dispatch"), ("root", "d:export:ui", "dispatch"),
                                 ("d:export:api", "d:export:verify", "depends_on"),
                                 ("d:export:ui", "d:export:verify", "depends_on")})
        # The bound child is the node, never a second lane beside it.
        self.assertFalse([node for node in graph["nodes"] if node["id"].startswith("s:")])
        header = render_delegation_view(graph, width=100).text_lines()[:2]  # the task count, then the run's name
        self.assertIn("export feature", header[1])

    def test_a_node_bound_to_a_child_carries_the_childs_output_tokens(self) -> None:
        # The same fact a native lane carries: what the child's own state.db row has counted, out of the fingerprint.
        with homes() as home:
            defined(home)
            now = time.time()
            started(home, "api", now=now)
            home.tokens("child-api", 1234)
            graph = build_delegation_graph(home.omh, home.hermes, PARENT, now=now + 1)
            home.tokens("child-api", 56_000)
            grown = build_delegation_graph(home.omh, home.hermes, PARENT, now=now + 1)
        by_id = {node["id"]: node for node in graph["nodes"]}
        self.assertEqual(by_id["d:export:api"]["output_tokens"], 1234)
        self.assertEqual({node["id"]: node.get("output_tokens") for node in grown["nodes"]}["d:export:api"], 56_000)
        self.assertNotIn("output_tokens", by_id["d:export:ui"], "a node no child has taken has no count")
        self.assertEqual(graph_fingerprint(graph), graph_fingerprint(grown))
        view = render_delegation_view(graph, width=100)
        self.assertIn("    Running 1s · ↓1.2k tokens · layer 1 · session child-ap", view.text_lines())
        self.assertRegex(view.text(), r"│ ● Running 1s · ↓1\.2k *│")
        tree = render_delegation_view(graph, width=100, layout="tree").text()
        self.assertIn("running 1s · ↓1.2k", tree)

    def test_a_box_makes_room_for_a_count_so_it_stays_in_sight_while_the_node_runs(self) -> None:
        # Without a count the run's boxes are 22 cells inside, as #2191 draws them for these titles. Once a lane
        # carries one, a box makes room for `● Running 59m 59s · ↓999.9k` (27 cells), so the count stays through
        # the first hour; past what the room holds it drops out whole, never cut.
        def boxes(count: int | None, seconds: int, width: int = 100):
            with homes() as home:
                defined(home)
                now = time.time()
                started(home, "api", now=now)
                if count is not None:
                    home.tokens("child-api", count)
                home.usage("child-api", "glm-5.3-flash", last_seen=now + seconds - 1)  # running, not no news
                return render_delegation_view(build_delegation_graph(home.omh, home.hermes, PARENT, now=now + seconds),
                                              width=width)

        def inner(view) -> set[int]:
            return {len(edge) - 4 for edge in re.findall(r"┌─*┐", view.text())}

        for width in (80, 100, 120):
            with self.subTest(width=width):
                self.assertEqual(inner(boxes(None, 21, width)), {22}, "no count: #2191's widths")
                self.assertEqual(inner(boxes(1400, 21, width)), {27})
        for seconds, count, line in ((21, 1400, "● Running 21s · ↓1.4k"), (724, 45_600, "● Running 12m 4s · ↓45.6k"),
                                     (3599, 999_900, "● Running 59m 59s · ↓999.9k")):
            with self.subTest(seconds=seconds):
                self.assertRegex(boxes(count, seconds).text(), rf"│ {re.escape(line)} *│")
        # `100h 59m` with `↓999.9k` is 28 cells, past the room: the count drops out whole.
        late = boxes(999_900, 100 * 3600 + 59 * 60)
        self.assertRegex(late.text(), r"│ ● Running 100h 59m *│")
        self.assertIsNone(re.search(r"↓[0-9.]*[kM]?…", late.text()))
        self.assertIn("Running 100h 59m · ↓999.9k tokens", late.text(), "the card still says it")

    def test_a_repair_hangs_below_the_node_it_repairs_and_superseded_nodes_go(self) -> None:
        with homes() as home:
            defined(home)
            for node in ("api", "ui"):
                write_handoff(home, node)
                call(action="settle", run="export", node=node, outcome="accepted")
            call(action="settle", run="export", node="verify", outcome="failed")
            call(action="repair", run="export", node="verify", nodes=[
                {"id": "fix", "label": "Fix export", "category": "quick", "prompt": PROMPT}])
            call(action="settle", run="export", node="fix", outcome="failed")
            call(action="repair", run="export", node="fix", nodes=[
                {"id": "fix2", "label": "Fix export again", "category": "quick", "prompt": PROMPT}])
            graph = build_delegation_graph(home.omh, home.hermes, PARENT)
        ids = {node["id"] for node in graph["nodes"]}
        self.assertNotIn("d:export:fix", ids)
        self.assertIn(("d:export:verify", "d:export:fix2", "repair"),
                      {(edge["from"], edge["to"], edge["kind"]) for edge in graph["edges"]})

    def test_a_repair_node_carries_the_repair_cycle_it_belongs_to(self) -> None:
        # The second repair of `verify` (fix2, repairing fix, which repaired verify) is cycle 2 of verify; fix, the
        # first cycle's node that was never accepted, leaves the drawing, so counting the repair edges would say 1.
        with homes() as home:
            defined(home)
            for node in ("api", "ui"):
                write_handoff(home, node)
                call(action="settle", run="export", node=node, outcome="accepted")
            call(action="settle", run="export", node="verify", outcome="failed")
            call(action="repair", run="export", node="verify", nodes=[
                {"id": "fix", "label": "Fix export", "category": "quick", "prompt": PROMPT}])
            first = build_delegation_graph(home.omh, home.hermes, PARENT)
            call(action="settle", run="export", node="fix", outcome="failed")
            call(action="repair", run="export", node="fix", nodes=[
                {"id": "fix2", "label": "Fix export again", "category": "quick", "prompt": PROMPT}])
            second = build_delegation_graph(home.omh, home.hermes, PARENT)
        self.assertEqual({node["id"]: node["cycle"] for node in first["nodes"] if "cycle" in node}, {"d:export:fix": 1})
        self.assertEqual({node["id"]: node["cycle"] for node in second["nodes"] if "cycle" in node},
                         {"d:export:fix2": 2})

    def test_each_node_carries_its_role(self) -> None:
        # The TUI names a finished child's briefing by it (`● verify @verify finished`): the declared role, `build`
        # where none was declared, as `dag_run.node_role` reads it.
        with homes() as home:
            defined(home)
            graph = build_delegation_graph(home.omh, home.hermes, PARENT)
        roles = {node["id"]: node.get("role") for node in graph["nodes"] if node.get("dag_node")}
        self.assertEqual(roles, {"d:export:api": "build", "d:export:ui": "build", "d:export:verify": "verify"})

    def test_each_node_carries_its_place_in_the_runs_definition_order(self) -> None:
        # The TUI picks a node's handle hue by it: a repair's node is added after, and the node it supersedes keeps its
        # place, so no drawn node's index moves.
        with homes() as home:
            defined(home)
            first = build_delegation_graph(home.omh, home.hermes, PARENT)
            call(action="settle", run="export", node="ui", outcome="failed")
            call(action="repair", run="export", node="ui", nodes=[
                {"id": "fix-ui", "label": "Fix the button", "category": "quick", "prompt": PROMPT,
                 "write_scope": ["src/ui.py"]}])
            second = build_delegation_graph(home.omh, home.hermes, PARENT)

        def places(graph: dict) -> dict:
            return {node["id"]: node["node_index"] for node in graph["nodes"] if node.get("dag_node")}

        self.assertEqual(places(first), {"d:export:api": 0, "d:export:ui": 1, "d:export:verify": 2})
        self.assertEqual(places(second)["d:export:fix-ui"], 3)
        self.assertEqual({key: value for key, value in places(second).items() if key in places(first)},
                         {key: value for key, value in places(first).items() if key in places(second)})

    def test_added_nodes_hang_below_where_they_came_from(self) -> None:
        with homes() as home:
            defined(home)
            write_handoff(home, "api")
            call(action="settle", run="export", node="api", outcome="accepted")
            call(action="settle", run="export", node="ui", outcome="failed")
            call(action="repair", run="export", node="ui", nodes=[
                {"id": "fix-ui", "label": "Fix the button", "category": "quick", "prompt": PROMPT,
                 "depends_on": ["api"], "write_scope": ["src/ui.py"]}])
            for node in ("fix-ui", "verify"):
                write_handoff(home, node)
                call(action="settle", run="export", node=node, outcome="accepted")
            call(action="extend", run="export", nodes=[
                {"id": "csv", "label": "Add CSV export", "category": "quick", "prompt": PROMPT, "depends_on": ["api"],
                 "write_scope": ["src/api.py"]},
                {"id": "verify2", "label": "Verify CSV", "category": "unspecified-high", "prompt": PROMPT,
                 "role": "verify", "depends_on": ["csv"]}])
            graph = build_delegation_graph(home.omh, home.hermes, PARENT)
        by_id = {node["id"]: node for node in graph["nodes"]}
        self.assertEqual({key: by_id[f"d:export:{key}"]["dag_origin"] for key in ("api", "fix-ui", "csv", "verify2")},
                         {"api": "define", "fix-ui": "repair:ui", "csv": "extend:1", "verify2": "extend:1"})
        edges = {(edge["from"], edge["to"], edge["kind"]) for edge in graph["edges"]}
        # The first node of each added group hangs from where it came from, beside its own depends_on edges; a node
        # led to by its own group does not.
        self.assertLessEqual({("d:export:ui", "d:export:fix-ui", "repair"),
                              ("d:export:api", "d:export:fix-ui", "depends_on"),
                              ("d:export:verify", "d:export:csv", "extend"),
                              ("d:export:api", "d:export:csv", "depends_on"),
                              ("d:export:csv", "d:export:verify2", "depends_on")}, edges)
        self.assertFalse({edge for edge in edges if edge[1] == "d:export:verify2" and edge[2] == "extend"})
        # An extend round is its own group in the tree; a repair node keeps its layer.
        self.assertEqual((by_id["d:export:csv"]["group"], by_id["d:export:verify2"]["group"]), ("extend 1", "extend 1"))
        self.assertEqual(by_id["d:export:fix-ui"]["group"], "layer 2")
        lines = render_delegation_view(graph, width=100, layout="tree").text_lines()
        # In the tree an added node sits under the node it came from. Its title is matched by a prefix: a deep added
        # row's title gives way before any status does, so how much of it shows depends on the room the statuses
        # leave.
        verify_row = next(index for index, line in enumerate(lines) if "Verify export" in line)
        csv_row = next(index for index, line in enumerate(lines) if "Add CSV" in line)
        lead = len(lines[verify_row]) - len(lines[verify_row].lstrip(" │├└─"))
        self.assertEqual(csv_row, verify_row + 1)
        self.assertGreater(len(lines[csv_row]) - len(lines[csv_row].lstrip(" │├└─")), lead)

    def test_the_nesting_never_cuts_a_flat_rows_status(self) -> None:
        # A repair nested under its node and an extend under its check deepen the tree by two levels. Those rows pay
        # the indent from their own titles; the flat rows beside them keep the status room a flat tree gives them.
        with homes() as home:
            defined(home)
            write_handoff(home, "api")
            call(action="settle", run="export", node="api", outcome="accepted")
            call(action="settle", run="export", node="ui", outcome="failed")
            call(action="repair", run="export", node="ui", nodes=[
                {"id": "fix-ui", "label": "Fix the button, with its hotkey", "category": "quick", "prompt": PROMPT,
                 "depends_on": ["api"], "write_scope": ["src/ui.py"]}])
            for node in ("fix-ui", "verify"):
                write_handoff(home, node)
                call(action="settle", run="export", node=node, outcome="accepted")
            call(action="extend", run="export", nodes=[
                {"id": "csv", "label": "Add CSV export", "category": "quick", "prompt": PROMPT, "depends_on": ["api"],
                 "write_scope": ["src/api.py"]}])
            graph = build_delegation_graph(home.omh, home.hermes, PARENT)
        lanes = [dict(node, model="glm-5.3-flash", effort="low") for node in graph["nodes"] if node["kind"] != "root"]
        api = next(node for node in lanes if node["id"] == "d:export:api")
        api.update(status="accepted", elapsed_seconds=3_725)
        late = dict(graph, nodes=[node for node in graph["nodes"] if node["kind"] == "root"] + lanes)
        rows = render_delegation_view(late, width=90, layout="tree").text_lines()
        self.assertTrue(next(row for row in rows if "Export API" in row).endswith("accepted 1h 02m"), rows)
        # Where the statuses leave room it goes back to the nested titles: at 120 they are whole.
        wide = "\n".join(render_delegation_view(late, width=120, layout="tree").text_lines())
        self.assertIn("Fix the button, with its hotkey ", wide)
        self.assertIn("Add CSV export ", wide)

    def test_a_compacted_parent_still_finds_its_run(self) -> None:
        with homes() as home:
            defined(home)
            later = "20261020_160000_later"
            home.rotate(PARENT, later)
            graph = build_delegation_graph(home.omh, home.hermes, later)
        self.assertEqual(graph["name"], "export feature")

    def test_a_node_whose_stop_hermes_filed_under_the_rotated_parent_has_returned(self) -> None:
        with homes() as home:
            defined(home)
            now = time.time()
            started(home, "api", now=now)
            later = "20261020_160000_later"
            home.rotate(PARENT, later)
            stop(home, "child-api", parent=later, now=now + 1)  # Hermes names the parent's current segment
            graph = build_delegation_graph(home.omh, home.hermes, later, now=now + 2)
        api = next(item for item in graph["nodes"] if item["id"] == "d:export:api")
        self.assertEqual((api["state"], api["status"]), ("dispatched", "returned"))

    def test_omh_hud_graph_prints_the_run(self) -> None:
        with homes() as home:
            defined(home)
            start(home, "child-api", "sa-api", "api [dag:export/api]", now=time.time())
            with patch("omh.commands.hud._encodes", return_value=True):
                code, stdout, stderr = run_cli(
                    ["--omh-home", str(home.omh), "--hermes-home", str(home.hermes), "hud", "--graph"],
                    output_json=False)
        self.assertEqual(code, 0, stderr)
        self.assertIn("\nexport feature · ", stdout)
        self.assertIn("Export API", stdout)


class MessengerTests(unittest.TestCase):
    def test_start_then_count_lines_then_the_end_once_the_run_is_over(self) -> None:
        with homes() as home:
            defined(home)
            now = time.time()
            for node in ("api", "ui"):
                started(home, node, now=now)
            first = reply("Dispatched the first layer.", turn="t1")
            for node in ("api", "ui"):
                stop(home, f"child-{node}", now=now + 5)
                write_handoff(home, node)
                call(action="settle", run="export", node=node, outcome="accepted")
            # The parent answers a completion turn with the run's own status line: no second line is added, and the
            # counts are recorded, so the next reply with nothing new adds nothing either.
            second = reply("DAG export feature · 2/3 done · 0 running", turn="t2")
            quiet = reply("Waiting on verification.", turn="t2b")
            # The verification fails and the parent repairs it in the same turn.
            call(action="settle", run="export", node="verify", outcome="failed", reason="1 test red")
            call(action="repair", run="export", node="verify", nodes=[
                {"id": "fix", "label": "Fix the red test", "category": "quick", "prompt": PROMPT}])
            third = reply("Verification failed; repairing.", turn="t3")
            write_handoff(home, "fix")
            rerun = call(action="settle", run="export", node="fix", outcome="accepted")
            # The fix is in, and the verification runs again: the run is not over until that run passes.
            fourth = reply("Fixed; verifying again.", turn="t4")
            write_handoff(home, "verify")
            call(action="settle", run="export", node="verify", outcome="accepted")
            fifth = reply("Verified.", turn="t5")
            sixth = reply("Anything else?", turn="t6")
        self.assertIn("DAG · export feature · 3 tasks · 2 layers", first)
        self.assertIsNone(second)
        self.assertIsNone(quiet)
        self.assertTrue(third.endswith("DAG export feature · 2/4 done · 0 running · 1 failed (Verify export) · "
                                       "+1 added (repair: Fix the red test)"), third)
        self.assertEqual([c["nodes"] for c in rerun["calls"]], [["verify"]])
        self.assertTrue(fourth.endswith("DAG export feature · 3/4 done · 0 running"), fourth)
        self.assertIn("DAG · export feature · ended", fifth)
        self.assertIn("4 tasks · 4 done", fifth)
        self.assertIsNone(sixth)

    def test_a_reply_that_only_mentions_the_run_still_gets_its_count_line(self) -> None:
        with homes() as home:
            defined(home)
            now = time.time()
            started(home, "api", now=now)
            reply("Dispatched.", turn="t1")
            stop(home, "child-api", now=now + 5)
            write_handoff(home, "api")
            call(action="settle", run="export", node="api", outcome="accepted")
            mentioned = reply("The DAG export feature run is moving.", turn="t2")
        self.assertTrue(mentioned.endswith("\n\nDAG export feature · 1/3 done · 0 running"), mentioned)

    def test_a_run_whose_children_went_quiet_is_not_over_until_it_says_so(self) -> None:
        # Both children's sessions ended with no stop recorded: every drawn lane reads settled ("ended"), but the
        # parent has settled neither node, so the run is still running and no end block goes out.
        with homes() as home:
            home.execute("ALTER TABLE async_delegations ADD COLUMN owner_pid INTEGER")
            home.session(PARENT, "claude-opus-5-5", effort="high")
            home.hermes.joinpath("config.yaml").write_text("delegation:\n  max_concurrent_children: 10\n")
            call(action="define", run="export", name="export feature", nodes=NODES[:2])
            now = time.time()
            for node in ("api", "ui"):
                started(home, node, now=now)
            reply("Dispatched.", turn="t1")
            for node in ("api", "ui"):
                home.session(f"child-{node}", "glm-5.3-flash", parent=PARENT, effort="low", ended=now + 5)
            quiet = reply("Still waiting on both parts.", turn="t2")
            graph = build_delegation_graph(home.omh, home.hermes, PARENT)
        lanes = [node for node in graph["nodes"] if node["kind"] != "root"]
        self.assertEqual({node["status"] for node in lanes}, {"ended"}, lanes)
        self.assertTrue(graph["dag_open"])
        self.assertNotIn("ended", quiet or "")

    def test_a_run_left_waiting_on_a_repair_ends_on_that_reply(self) -> None:
        # The parent reports instead of repairing: nothing will move, so the end block goes now, not after the
        # 15-minute stall; a repair made later reopens the run with a count line.
        with homes() as home:
            defined(home)
            now = time.time()
            started(home, "api", now=now)
            reply("Dispatched.", turn="t1")
            stop(home, "child-api", now=now + 5)
            call(action="settle", run="export", node="api", outcome="failed", reason="no key")
            call(action="settle", run="export", node="ui", outcome="accepted")  # refused: no handoff, still out
            call(action="settle", run="export", node="ui", outcome="failed")
            status = call(action="status", run="export")
            reported = reply("Both parts failed; here is what is open.", turn="t2")
            call(action="repair", run="export", node="api", nodes=[
                {"id": "api-fix", "label": "Fix the API", "category": "quick", "prompt": PROMPT}])
            reopened = reply("Repairing the API after all.", turn="t3")
        self.assertEqual(status["state"], "needs_repair")
        self.assertIn("cancel", status["say"])
        self.assertIn("DAG · export feature · ended", reported)
        self.assertNotIn("```", reopened)
        self.assertIn("+1 added (repair: Fix the API)", reopened)

    def test_a_node_added_mid_run_is_named_once_on_the_count_line(self) -> None:
        with homes() as home:
            defined(home)
            now = time.time()
            for node in ("api", "ui"):
                started(home, node, now=now)
            off_chat = call(action="status", run="export")["status_line"]
            first = reply("Dispatched the first layer.", turn="t1")
            for node in ("api", "ui"):
                stop(home, f"child-{node}", now=now + 5)
            write_handoff(home, "api")
            call(action="settle", run="export", node="api", outcome="accepted")
            call(action="settle", run="export", node="ui", outcome="failed")
            line = call(action="repair", run="export", node="ui", nodes=[
                {"id": "fix-ui", "label": "Fix the button", "category": "quick", "prompt": PROMPT}])["status_line"]
            second = reply("Repairing the button.", turn="t2")
            again = call(action="status", run="export")["status_line"]
            started(home, "fix-ui", now=now + 10)
            third = reply("Still going.", turn="t3")
        self.assertNotIn("added", off_chat)  # no chat post yet: nothing to name a node against
        self.assertIn("DAG · export feature", first)
        self.assertEqual(line, "DAG export feature · 1/4 done · 0 running · 1 failed (Export button) · "
                               "+1 added (repair: Fix the button)")
        self.assertTrue(second.endswith("DAG export feature · 1/4 done · 0 running · 1 failed (Export button) · "
                                        "+1 added (repair: Fix the button)"), second)
        # Named once: the tool's own line and the next count line no longer carry it.
        self.assertNotIn("added", again)
        self.assertTrue(third.endswith("DAG export feature · 1/4 done · 1 running · 1 failed (Export button)"), third)

    def test_a_reply_that_is_the_status_line_names_the_added_node_and_nothing_repeats_it(self) -> None:
        with homes() as home:
            defined(home)
            now = time.time()
            started(home, "api", now=now)
            reply("Dispatched.", turn="t1")
            stop(home, "child-api", now=now + 5)
            call(action="settle", run="export", node="api", outcome="failed")
            line = call(action="repair", run="export", node="api", nodes=[
                {"id": "fix", "label": "Fix the API", "category": "quick", "prompt": PROMPT}])["status_line"]
            echoed = reply(line, turn="t2")
            started(home, "fix", now=now + 10)
            later = reply("Working.", turn="t3")
        self.assertTrue(line.endswith("+1 added (repair: Fix the API)"), line)
        self.assertIsNone(echoed)
        self.assertNotIn("added", later)

    def test_two_labels_then_a_count_and_the_line_alone_when_the_names_do_not_fit(self) -> None:
        from omh.plugin_bundle.omh.delegation_snapshot import added_clause

        self.assertEqual(added_clause([("repair", "Docs body")]), "+1 added (repair: Docs body)")
        self.assertEqual(added_clause([("repair", "Docs body"), ("extend", "CSV header"), ("extend", "Verify CSV")]),
                         "+3 added (repair: Docs body, extend: CSV header, +1 more)")
        self.assertEqual(added_clause([("extend", "CSV export"), ("extend", "CSV docs"), ("extend", "Verify CSV")]),
                         "+3 added (extend: CSV export, CSV docs, +1 more)")
        with homes() as home:
            defined(home)
            now = time.time()
            started(home, "api", now=now)
            reply("Dispatched.", turn="t1")
            stop(home, "child-api", now=now + 5)
            call(action="settle", run="export", node="api", outcome="failed")
            call(action="repair", run="export", node="api", nodes=[
                {"id": "fix", "label": "Fix the API", "category": "quick", "prompt": PROMPT}])
            line = "DAG export feature · 0/4 done · 0 running · 1 failed (Export API)"
            # Discord's cap is 2,000 characters, 90% of it for the reply and the post: room for the line only.
            tight = reply("x" * (1_800 - len(line) - 2), turn="t2")
            started(home, "fix", now=now + 10)
            roomy = reply("Working.", turn="t3")
        self.assertTrue(tight.endswith("\n\n" + line), tight[-120:])
        self.assertTrue(roomy.endswith("· +1 added (repair: Fix the API)"), roomy)

    def test_an_extend_after_the_end_post_continues_the_run_without_a_second_start(self) -> None:
        with homes() as home:
            defined(home)
            now = time.time()
            for node in ("api", "ui"):
                started(home, node, now=now)
            start_post = reply("Dispatched.", turn="t1")
            for node in ("api", "ui", "verify"):
                stop(home, f"child-{node}", now=now + 5)
                write_handoff(home, node)
                call(action="settle", run="export", node=node, outcome="accepted")
            end_post = reply("All passed.", turn="t2")
            call(action="extend", run="export", nodes=[
                {"id": "csv", "label": "Add CSV export", "category": "quick", "prompt": PROMPT, "depends_on": ["api"],
                 "write_scope": ["src/api.py"]}])
            status = call(action="status", run="export")["status_line"]
            reopened = reply("The goal check found CSV missing.", turn="t3")
            write_handoff(home, "csv")
            call(action="settle", run="export", node="csv", outcome="accepted")
            closing = reply("CSV added.", turn="t4")
        self.assertIn("DAG · export feature · 3 tasks · 2 layers", start_post)
        self.assertIn("DAG · export feature · ended", end_post)
        self.assertEqual(status, "DAG export feature · 3/4 done · 0 running · +1 added (extend: Add CSV export)")
        self.assertTrue(reopened.endswith(status), reopened)
        self.assertNotIn("```", reopened)  # no second start block
        self.assertIn("DAG · export feature · ended", closing)
        self.assertIn("4 tasks · 4 done", closing)

    def test_a_runs_posts_are_the_same_with_and_without_token_counts(self) -> None:
        # Messengers do not change: a growing count on the children's rows leaves every post byte-identical.
        def posts(counted: bool) -> list[str | None]:
            with homes() as home:
                defined(home)
                now = time.time()
                said = []
                for node in ("api", "ui"):
                    started(home, node, now=now)
                    if counted:
                        home.tokens(f"child-{node}", 900)
                said.append(reply("Dispatched the first layer.", turn="t1"))
                stop(home, "child-api", now=now + 5)
                if counted:
                    home.tokens("child-api", 4_900)
                write_handoff(home, "api")
                call(action="settle", run="export", node="api", outcome="accepted")
                said.append(reply("The API is in.", turn="t2"))
                stop(home, "child-ui", now=now + 6)
                if counted:
                    home.tokens("child-ui", 7_800)
                for node in ("ui", "verify"):
                    write_handoff(home, node)
                    call(action="settle", run="export", node=node, outcome="accepted")
                said.append(reply("Verified.", turn="t3"))
                return said

        plain, counted = posts(False), posts(True)
        self.assertEqual(counted, plain)
        self.assertTrue(all(post for post in plain), plain)
        self.assertFalse([post for post in counted if "↓" in post])

    def test_a_subagent_turn_gets_no_post(self) -> None:
        with homes() as home:
            defined(home)
            started(home, "api", now=time.time())
            self.assertIsNone(reply("child reply", platform="subagent"))
            self.assertIn("DAG · export feature", reply("parent reply"))


class HandoffNotCheckedTests(unittest.TestCase):
    def test_a_node_accepted_with_its_handoff_not_checked_says_so_wherever_it_is_shown(self) -> None:
        """Mutation: keep `accepted` as the word, list a Done lane by its title alone, or leave the totals as they were.

        A Docker terminal whose environment is gone by the time api settles: its
        handoff cannot be read where the child wrote it. The button's is on the
        host, so it is checked, and the views tell the two apart.
        """
        terminal = Terminal("docker", Answers(HOME_UNUSABLE))  # this host's path for the run, read there first
        with homes() as home, terminal_env(), terminal.modules():
            defined(home)
            terminal.environment = None
            now = time.time()
            for node in ("api", "ui"):
                started(home, node, now=now)
            reply("Dispatched.", turn="t1")
            for node in ("api", "ui"):
                stop(home, f"child-{node}", now=now + 5)
            settled = call(action="settle", run="export", node="api", outcome="accepted")
            mid = reply("API is in.", turn="t1b")
            for node in ("ui", "verify"):
                write_handoff(home, node)
                call(action="settle", run="export", node=node, outcome="accepted")
            graph = build_delegation_graph(home.omh, home.hermes, PARENT, now=now + 10)
            end = reply("Verified.", turn="t2")
            with patch("omh.commands.hud._encodes", return_value=True):
                code, stdout, stderr = run_cli(
                    ["--omh-home", str(home.omh), "--hermes-home", str(home.hermes), "hud", "--graph"],
                    output_json=False)
        self.assertEqual(settled["status"], "ok", settled)
        lanes = {node["id"]: node for node in graph["nodes"]}
        api, ui = lanes["d:export:api"], lanes["d:export:ui"]
        self.assertEqual((api["state"], api["status"], api["handoff_checked"]), ("done", "handoff not checked", False))
        self.assertEqual((ui["state"], ui["status"]), ("done", "accepted"))
        self.assertNotIn("handoff_checked", ui)
        # The box (a card), the tree, and `omh hud --graph`.
        self.assertIn("✓ Handoff not checked", render_delegation_view(graph, width=120, layout="box").text())
        self.assertIn("handoff not checked", render_delegation_view(graph, width=120, layout="tree").text())
        self.assertEqual(code, 0, stderr)
        self.assertIn("Handoff not checked", stdout)
        # The count line while the run goes on, and the run's own status line the parent replies with.
        self.assertTrue(mid.endswith("\n\nDAG export feature · 1/3 done · 0 running · 1 handoff not checked"), mid)
        self.assertEqual(settled["status_line"], "DAG export feature · 1/3 done · 0 running · 1 handoff not checked")
        # The chat end post: under Done with its word, and in the totals, which still say it for a lane the listing
        # counts as `+N`.
        self.assertIn("\n✓ Done     Export API (handoff not checked) · Export button +1\n", end)
        self.assertIn("\n3 tasks · 3 done · 0 failed · 0 stopped · 1 handoff not checked\n", end)


if __name__ == "__main__":
    unittest.main()
