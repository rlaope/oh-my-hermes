"""The one DAG core (`plugin_bundle/omh/dag_core.py`) and the callers that decide topology through it.

`omh_dag`, `omh_team`, the fanout contract, the delegation graph's dag runs
and the view's drawing read a graph's references, cycles, layers and shared
write scopes here. These tests pin the core's answers and that each caller
still refuses or draws exactly what it did, wording included. Two walks stay
on their own code because the core answers differently on inputs they can
see: the graph's `_layers` (a repeated node id) and its team stages (a cyclic
hand-edited record).
"""

from __future__ import annotations

import unittest

from _local_package import load_local_package

load_local_package()

from omh.coding.fanout import detect_boundary_overlaps, merge_order, validate_fanout_units  # noqa: E402
from omh.coding.fanout_contracts import FanoutContractError  # noqa: E402
from omh.plugin_bundle.omh import dag_core  # noqa: E402
from omh.plugin_bundle.omh.delegation_graph import _layers as graph_layers  # noqa: E402
from omh.plugin_bundle.omh.delegation_view import _layers as view_layers  # noqa: E402
from omh.workflows import team  # noqa: E402

DIAMOND = {"a": [], "b": ["a"], "c": ["a"], "d": ["b", "c"]}


class EdgeProblemTests(unittest.TestCase):
    def test_unknown_comes_before_self_and_order_is_kept(self) -> None:
        self.assertIsNone(dag_core.edge_problem("b", ["a"], {"a", "b"}))
        self.assertEqual(dag_core.edge_problem("b", ["x", "b"], {"a", "b"}), (dag_core.UNKNOWN_DEPENDENCY, "x"))
        self.assertEqual(dag_core.edge_problem("b", ["b", "x"], {"a", "b"}), (dag_core.SELF_DEPENDENCY, "b"))


class LayerTests(unittest.TestCase):
    def test_layers_are_longest_paths_in_input_order(self) -> None:
        self.assertEqual(dag_core.layers(list(DIAMOND), DIAMOND), [["a"], ["b", "c"], ["d"]])
        # A node waiting on a deep chain lands below the deepest parent, not beside the shallow one.
        chain = {"a": [], "b": ["a"], "c": ["b"], "x": ["a", "c"]}
        self.assertEqual(dag_core.layers(list(chain), chain), [["a"], ["b"], ["c"], ["x"]])

    def test_a_cycle_leaves_its_nodes_and_everything_below_unplaced(self) -> None:
        graph = {"a": [], "b": ["a", "c"], "c": ["b"], "d": ["c"]}
        placed, stuck = dag_core.layer_of(list(graph), graph)
        self.assertEqual(placed, {"a": 0})
        self.assertEqual(stuck, ["b", "c", "d"])
        self.assertIsNone(dag_core.layers(list(graph), graph))

    def test_a_self_edge_is_a_cycle_and_unknown_parents_are_ignored(self) -> None:
        self.assertIsNone(dag_core.layers(["a"], {"a": ["a"]}))
        self.assertEqual(dag_core.layers(["a", "b"], {"b": ["a", "ghost"]}), [["a"], ["b"]])

    def test_strict_holds_what_waits_on_an_unknown_parent(self) -> None:
        graph = {"a": [], "b": ["ghost"], "c": ["b"]}
        self.assertEqual(dag_core.layer_of(list(graph), graph, strict=True), ({"a": 0}, ["b", "c"]))
        self.assertEqual(dag_core.layer_of(list(graph), graph), ({"a": 0, "b": 0, "c": 1}, []))

    def test_ready_needs_every_parent_satisfied(self) -> None:
        self.assertEqual(dag_core.ready(["b", "c", "d"], DIAMOND, {"a", "b"}), ["b", "c"])
        self.assertEqual(dag_core.ready(["d"], DIAMOND, {"a", "b", "c"}), ["d"])
        self.assertEqual(dag_core.ready(["d"], DIAMOND, {"a", "b"}), [])


class PathAndBottleneckTests(unittest.TestCase):
    def test_critical_path_is_the_longest_chain_with_ties_to_the_smaller_id(self) -> None:
        self.assertEqual(dag_core.critical_path(list(DIAMOND), DIAMOND), ["a", "b", "d"])
        two = {"z": [], "y": []}
        self.assertEqual(dag_core.critical_path(list(two), two), ["y"])
        self.assertEqual(dag_core.critical_path([], {}), [])
        self.assertEqual(dag_core.critical_path(["a"], {"a": ["a"]}), [])

    def test_bottlenecks_count_transitive_dependents(self) -> None:
        self.assertEqual(dag_core.bottlenecks(list(DIAMOND), DIAMOND), [("a", 3), ("b", 1), ("c", 1)])
        self.assertEqual(dag_core.bottlenecks(list(DIAMOND), DIAMOND, limit=1), [("a", 3)])
        self.assertEqual(dag_core.bottlenecks(["a", "b"], {}), [])


class SharedScopeTests(unittest.TestCase):
    def test_pairs_name_the_shared_entries_and_whether_a_direct_edge_joins_them(self) -> None:
        scopes = [("a", ["x.py", "y.py"]), ("b", ["y.py"]), ("c", ["y.py"]), ("d", ["z.py"])]
        parents = {"b": ["a"], "c": ["b"]}
        self.assertEqual(
            dag_core.shared_scope_pairs(scopes, parents),
            [("a", "b", ["y.py"], True), ("a", "c", ["y.py"], False), ("b", "c", ["y.py"], True)],
        )

    def test_as_written_a_directory_and_a_file_under_it_do_not_meet(self) -> None:
        """The fanout contract still compares as written: its frozen boundary notes stay the bytes they were."""
        self.assertEqual(dag_core.shared_scope_pairs([("a", ["src/"]), ("b", ["src/x.py"])], {}), [])

    def test_as_paths_entries_written_differently_meet(self) -> None:
        """Mutation: compare as written, as a raw string prefix, without the leading `/`, the glob match or the
        `[` escape; a row then reads the other way."""
        meeting = (
            ("src/", "src/x.py"), ("src", "src/x.py"), ("src/x.py", "./src/x.py"), ("src//x.py", "src/x.py"),
            ("src/x.py/", "src/x.py"), ("src/*.py", "src/x.py"), ("src/*.py", "src/lib/y.py"),
            ("tests/test_*.py", "tests/test_b.py"), ("*.md", "docs/a.md"), (".", "a.py"), ("SRC/X.py", "src/x.py"),
            ("src/a?.py", "src/a1.py"), ("src\\x.py", "src/x.py"), ("src/../lib/x.py", "lib/x.py"),
            ("/src/x.py", "/src/x.py"), ("app/[slug]/*.tsx", "app/[slug]/page.tsx"),
            # A glob beside a directory or another glob meets by its directory: a name with no suffix may be one.
            ("src/*.py", "src/lib"), ("src/*.py", "src/"), ("src/*.py", "src/*.md"), ("*.md", "src/"),
        )
        apart = (
            ("src/a", "src/ab"), ("docs/x.md", "docs/xy.md"), ("src/*.py", "lib/x.py"), ("src/a/", "src/ab/c.py"),
            ("app/[slug]/page.tsx", "app/about/page.tsx"), ("/src/x.py", "lib/x.py"), ("/src/x.py", "src/x.py"),
            ("*.md", "src/x.py"), ("src/*.py", "src/x.md"), ("tests/test_a*.py", "tests/test_b.py"),
        )
        for first, second in meeting:
            with self.subTest(first=first, second=second):
                self.assertEqual(dag_core.shared_scope_pairs([("a", [first]), ("b", [second])], {}, as_paths=True),
                                 [("a", "b", sorted({first, second}), False)])
        for first, second in apart:
            with self.subTest(first=first, second=second):
                self.assertEqual(dag_core.shared_scope_pairs([("a", [first]), ("b", [second])], {}, as_paths=True), [])

    def test_as_paths_names_each_meeting_entry_as_written_and_keeps_the_direct_edge_rule(self) -> None:
        scopes = [("a", ["src/", "README.md"]), ("b", ["./src/x.py", "src/y.py", "docs/b.md"]), ("c", ["src/x.py"])]
        parents = {"b": ["a"], "c": ["b"]}
        self.assertEqual(
            dag_core.shared_scope_pairs(scopes, parents, as_paths=True),
            [("a", "b", ["./src/x.py", "src/", "src/y.py"], True), ("a", "c", ["src/", "src/x.py"], False),
             ("b", "c", ["./src/x.py", "src/x.py"], True)],
        )


class CallerTests(unittest.TestCase):
    """Each caller decides through the core and keeps its own refusal."""

    def test_team_refuses_cycles_and_bad_references(self) -> None:
        units = [{"unit_id": "a", "depends_on": ["b"]}, {"unit_id": "b", "depends_on": ["a"]}]
        with self.assertRaises(team.TeamRefusal) as caught:
            team._require_acyclic(units)
        self.assertEqual(caught.exception.reason, "dependency_cycle")
        team._require_acyclic([{"unit_id": "a", "depends_on": []}, {"unit_id": "b", "depends_on": ["a"]}])

    def test_fanout_messages_are_unchanged(self) -> None:
        units = [
            {"unit_id": "a", "file_scope": ["x.py"], "depends_on": []},
            {"unit_id": "b", "file_scope": ["x.py"], "depends_on": ["a"]},
            {"unit_id": "c", "file_scope": ["c.py"], "depends_on": ["b", "a"]},
        ]
        self.assertEqual(merge_order(units), ["a", "b", "c"])
        self.assertEqual(
            detect_boundary_overlaps(units),
            [{"units": ["a", "b"], "shared_files": ["x.py"],
              "resolution": "ordered by depends_on edge; merge strictly in merge_order"}],
        )
        with self.assertRaisesRegex(FanoutContractError, r"^depends_on contains a cycle among units: a, b$"):
            merge_order([{"unit_id": "a", "depends_on": ["b"]}, {"unit_id": "b", "depends_on": ["a"]}])
        with self.assertRaisesRegex(FanoutContractError, r"^units a and b share files \['x.py'\] without a depends_on"):
            detect_boundary_overlaps([{"unit_id": "a", "file_scope": ["x.py"]}, {"unit_id": "b", "file_scope": ["x.py"]}])
        with self.assertRaisesRegex(FanoutContractError, r"^unit b depends on unknown unit 'zz'$"):
            validate_fanout_units([{"unit_id": "a", "file_scope": ["a"]}, {"unit_id": "b", "file_scope": ["b"],
                                                                            "depends_on": ["zz"]}])
        with self.assertRaisesRegex(FanoutContractError, r"^unit b cannot depend on itself$"):
            validate_fanout_units([{"unit_id": "b", "file_scope": ["b"], "depends_on": ["b"]}])
        # The raw value is named, not its text: an int dependency reads 5, not '5'; None and a list read as on main.
        for raw, shown in ((5, "5"), (None, "None"), (["api"], "['api']")):
            with self.subTest(raw=raw), self.assertRaises(FanoutContractError) as caught:
                validate_fanout_units([{"unit_id": "b", "file_scope": ["b"], "depends_on": [raw]}])
            self.assertEqual(str(caught.exception), f"unit b depends on unknown unit {shown}")
        # An unknown dependency holds the unit out of the merge order, so it is reported as stuck in a cycle.
        with self.assertRaisesRegex(FanoutContractError, r"^depends_on contains a cycle among units: b, c$"):
            merge_order([{"unit_id": "a"}, {"unit_id": "b", "depends_on": ["ghost"]}, {"unit_id": "c", "depends_on": ["b"]}])

    def test_view_layers_come_from_the_core_and_graph_layers_keep_their_walk(self) -> None:
        self.assertEqual(
            list(view_layers(["b", "root", "a"], [("root", "a"), ("a", "b")]).items()), [("b", 2), ("root", 0), ("a", 1)]
        )
        self.assertIsNone(view_layers(["a", "b"], [("a", "b"), ("b", "a")]))
        nodes = [{"id": "root"}, {"id": "a"}, {"id": "b"}]
        edges = [{"from": "root", "to": "a"}, {"from": "a", "to": "b"}, {"from": "root", "to": "b"}]
        self.assertEqual(graph_layers(nodes, edges), [["root"], ["a"], ["b"]])
        self.assertEqual(graph_layers(nodes, edges + [{"from": "b", "to": "a"}]), [])
        # A repeated root id is counted twice by the graph's own walk, which then answers no layers at all.
        self.assertEqual(graph_layers(nodes + [{"id": "root"}], edges), [])


if __name__ == "__main__":
    unittest.main()
