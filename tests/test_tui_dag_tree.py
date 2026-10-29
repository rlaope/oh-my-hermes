"""The dag run's folding tree under the composer (`omh.tui.dag_tree`, `agent_view._tree_view`), driven through `App`.

A dag run's view is one header row per node with what its child does now under
it: the child's latest call and its latest other line (thinking, Hermes'
progress line, or its reply), read from the roster the `subagent.*` frames
fill. Running and failed nodes open, the rest stay shut; a tree taller than
the view's cap folds, then cuts with a count. Down gives the tree the keys:
the arrows and Space fold, Enter opens a node's child's log, `x` and `s`
interrupt and steer it. A new turn keeps the open run's lanes in the roster.

The graph is a dag run record's (`d:<run>:<node>` ids, `layer N` groups, the
`_DAG_VIEW` state and status pairs, a repair hanging from the node it repairs
by a `repair` edge), as `delegation_graph._dag_nodes` builds it. Each child's
frames carry the goal `dag_run.task_for` writes, `<label> [dag:<run>/<node>]`,
and a child session whose last eight characters are the node's
`session_tail`, as Hermes and the graph reader give them.
"""

from __future__ import annotations

import re
import unittest

from _delegation_graphs import graph, lane, root
from test_tui_agent_view import agent_event, mode_row, view_text, with_graph
from test_tui_modes import SID, answer, drawn, make_app, notices, type_text
from test_tui_subagents import FRAMES, feed
from omh.tui.gateway import Event
from omh.tui.keys import CHAR, DOWN, ENTER, ESCAPE, LEFT, RIGHT, UP, Key
from omh.tui.prompts import CHOICE_MARK
from omh.tui.subagents import Roster

RUN = "sweep"
SOL, KIMI = "gpt-6.1-sol", "kimi-k3-ultrafast"
# key: (label, category, model, effort, layer, state, status, seconds, tokens, session tail)
NODES = {
    "inventory": ("Inventory rlaope PRs", "quick", KIMI, "low", 1, "done", "accepted", 48, 900, "4be1c07a"),
    "group-1": ("PR group 1: #138300 #107931", "deep", SOL, "high", 2, "running", "running", 132, 1300, "a9f3e210"),
    "group-2": ("PR group 2: #128662 #99354", "deep", SOL, "high", 2, "running", "running", 125, 1500, "c07d9b44"),
    "group-3": ("PR group 3: #127631 #58015", "quick", KIMI, "low", 2, "failed", "failed", 61, 700, "e2b85f19"),
    "group-4": ("PR group 4: #128680 #110669", "quick", KIMI, "low", 2, "waiting", "ready", None, None, ""),
    "group-3-fix": ("Resolve the registry conflict", "quick", KIMI, "low", 3, "running", "running", 12, 300, "71d0c3aa"),
    "verify": ("Verify handoffs", "deep", SOL, "high", 3, "waiting", "waiting", None, None, ""),
}
REPAIRS = {"group-3-fix": "group-3"}
# What each child sent: ("tool", name, preview), ("thinking", text) or ("progress", text), in order.
ACTIVITY = {
    "inventory": [("tool", "terminal", "gh search prs --author rlaope"), ("tool", "write_file", "inventory.json")],
    "group-1": [("tool", "terminal", "gh pr checkout 138300"), ("thinking", "Adding the test the review asks for"),
                ("tool", "terminal", "uv run pytest tests/test_chat_name.py -q")],
    "group-2": [("tool", "read_file", "tools/session_store.py"),
                ("progress", "🔀 [set 1 · 2/3] terminal, read_file, patch, terminal, terminal")],
    "group-3": [("tool", "terminal", "git rebase origin/main")],
    "group-3-fix": [("tool", "read_file", "tools/registry.py"), ("thinking", "Keeping both tool entries")],
}
SUMMARY = {"inventory": ("completed", "26 open PRs listed into inventory.json"),
           "group-3": ("failed", "blocked: rebase conflict in tools/registry.py\nsee the handoff")}
TREE_HINT = "↑↓ select · ←/→ or space fold · ⏎ log · x interrupt · s steer · esc back"


def node_id(key: str) -> str:
    return f"d:{RUN}:{key}"


def subagent_id(key: str) -> str:
    return f"sa-{key}"


def sweep(nodes: dict = NODES) -> dict:
    """The run's graph as the HUD carries it: layers, the repair under the node it repairs, the verification last."""
    built = [root(SOL, "high")]
    for order, (key, (label, category, model, effort, layer, state, status, seconds, tokens, tail)) in enumerate(
            nodes.items(), start=1):
        node = lane(node_id(key), label, category, model, effort, state, elapsed=seconds, order=order,
                    group=f"layer {layer}", status=status, waits=4 if key == "verify" else 0)
        node.update(dag_node=key, dag_origin=f"repair:{REPAIRS[key]}" if key in REPAIRS else "define")
        if tail:
            node["session_tail"] = tail
        if tokens:
            node["output_tokens"] = tokens
        built.append(node)
    layer = {key: values[4] for key, values in nodes.items()}
    edges = [("root", node_id(next(iter(nodes))), "dispatch")]
    for key in nodes:
        if key in REPAIRS:
            edges.append((node_id(REPAIRS[key]), node_id(key), "repair"))
            continue
        edges += [(node_id(upper), node_id(key), "depends_on") for upper in nodes
                  if layer[upper] == layer[key] - 1 and upper not in REPAIRS]
    return graph(built, edges, name=RUN, source="dag")


def run_children(app, keys=None) -> None:
    """Each child's frames, as Hermes relays them: started, what it did, and the verdict of the ones that ended."""
    for key in keys or [key for key, values in NODES.items() if values[-1]]:
        label, _category, model, *_rest, tail = NODES[key]
        base = {"goal": f"{label} [dag:{RUN}/{key}]", "model": model, "child_session_id": f"20261022_134612_{tail}"}
        agent_event(app, "start", subagent_id(key), **base, tool_count=0)
        for count, (kind, *said) in enumerate(ACTIVITY.get(key, []), start=1):
            if kind == "tool":
                agent_event(app, "tool", subagent_id(key), **base, tool_count=count, tool_name=said[0],
                            tool_preview=said[1], text=said[1])
            else:
                agent_event(app, kind, subagent_id(key), **base, text=said[0])
        if key in SUMMARY:
            status, summary = SUMMARY[key]
            agent_event(app, "complete", subagent_id(key), **base, status=status, summary=summary)


def tree_app(rows: int = 72, cols: int = 120, nodes: dict = NODES, children: bool = True):
    app, client = make_app(busy=True, rows=rows, cols=cols, clock=lambda: 0.0)
    with_graph(app, sweep(nodes))
    if children:
        run_children(app)
    drawn(app)  # the loop draws a frame before it reads a key
    return app, client


def left(row: str) -> str:
    """A row up to its right-hand figures (two spaces or more after its text starts: the figure columns start two
    cells after the title column), its indent kept; the highlighted row's pointer stands in its indent."""
    row = row.replace(CHOICE_MARK, " " * len(CHOICE_MARK), 1) if row.startswith(CHOICE_MARK) else row
    body = row.lstrip(" ")
    return row[: len(row) - len(body)] + re.split(r" {2,}", body.rstrip())[0] if body else ""


def right(row: str) -> str:
    parts = re.split(r" {2,}", row.strip(), maxsplit=1)
    return parts[-1] if len(parts) > 1 else ""


def accounted(shown: list[str]) -> int:
    """The nodes a drawn tree stands for: each node row, each shut layer's and `more` row's nodes, and every count."""
    headers = [row for row in shown if re.match(r"^ {4}( {4})*(▸ |▾ |  )[^\s›]", row) and " more · " not in row]
    folded = sum(int(found) for row in shown
                 for found in re.findall(r"^  ▸ layer \d+ · (\d+) nodes?|^ +▸ (\d+) more ·|^  … (\d+) more nodes?", row)
                 for found in found if found)
    return len(headers) + folded


def down_to(app, key: str) -> None:
    """Down until the tree highlights `key`; fails rather than loops when the keys never reach it."""
    for _ in range(80):
        if app.tree_selected == key:
            return
        app._on_input(Key(DOWN))
    raise AssertionError(f"Down never reached {key!r}; it stopped on {app.tree_selected!r}")


DEFAULT = [  # the tree's rows up to their right-hand figures, at 120x72 (a cap of 24 rows: all of it fits)
    "  DAG · sweep · 7 nodes · 9 edges · 3 running · 1 failed · 2 waiting · 1 done",
    "  ▾ layer 1 · 1 node · 1 done",
    "    ▸ ✓ Inventory rlaope PRs",
    "",
    "  ▾ layer 2 · 4 nodes · 2 running · 1 failed · 1 waiting",
    "    ▾ ⠋ PR group 1: #138300 #107931",
    "        › terminal(uv run pytest tests/test_chat_name.py -q)",
    "        › Adding the test the review asks for",
    "    ▾ ⠋ PR group 2: #128662 #99354",
    "        › read_file(tools/session_store.py)",
    "        › terminal, read_file, patch, terminal, terminal",
    "    ▾ ✗ PR group 3: #127631 #58015",
    "        › terminal(git rebase origin/main)",
    "        › blocked: rebase conflict in tools/registry.py",
    "        ▾ ⠋ ↻ repair 1 · Resolve the registry conflict",
    "            › read_file(tools/registry.py)",
    "            › Keeping both tool entries",
    "      · PR group 4: #128680 #110669",
    "",
    "  ▾ layer 3 · 1 node · 1 waiting",
    "      · Verify handoffs",
]


class DefaultFoldTests(unittest.TestCase):
    """Running and failed nodes open with their child's call and latest line; done and waiting ones stay shut."""

    def test_the_run_reads_layer_by_layer_with_what_each_running_child_does(self) -> None:
        app, _client = tree_app()
        self.assertEqual([left(row) for row in view_text(app)], DEFAULT)

    def test_a_header_row_ends_on_category_model_status_and_tokens(self) -> None:
        app, _client = tree_app()
        rows = {left(row): " · ".join(part.strip() for part in right(row).split("·")) for row in view_text(app)}
        self.assertEqual(rows["    ▾ ⠋ PR group 1: #138300 #107931"], "deep · gpt-6.1-sol:high · running 2m 12s · ↓1.3k")
        self.assertEqual(rows["    ▸ ✓ Inventory rlaope PRs"], "quick · kimi-k3-ultrafast:low · accepted 48s · ↓900")
        self.assertEqual(rows["      · Verify handoffs"], "deep · gpt-6.1-sol:high · waits on 4 lanes")

    def test_the_figures_stand_in_columns_two_cells_after_the_title_column(self) -> None:
        # The owner's GIF review (2026-10-23): figures pushed to the right edge, each row's own width, read as a
        # ragged column. They start at one column two cells after the widest title, each padded to its widest value.
        app, _client = tree_app()
        headers = [row for row in view_text(app) if right(row)]
        separators = [[at for at, char in enumerate(row) if char == "·" and at > len(left(row))] for row in headers]
        self.assertEqual(len({row.index(right(row)) for row in headers}), 1, headers)  # one start column
        self.assertEqual(len({tuple(found[:3]) for found in separators if len(found) >= 3}), 1, headers)  # aligned
        title_end = max(len(left(row)) for row in headers)
        self.assertEqual(headers[0].index(right(headers[0])), title_end + 2, headers)  # right after the titles

    def test_a_short_label_reads_with_its_prompts_first_clause_in_52_cells_cut_at_a_word(self) -> None:
        # The owner's GIF review (2026-10-23): "Inventory rlaope PRs" alone says too little. A label under
        # `SHORT_LABEL` cells takes its prompt's first clause after it; the title stops at `TITLE_CAP` cells, at a word.
        from omh.tui.dag_tree import SHORT_LABEL, TITLE_CAP, clamp_title, node_title

        built = sweep()
        by_key = {item.get("dag_node"): item for item in built["nodes"]}
        by_key["inventory"]["summary"] = "List every open PR by the author into inventory.json"
        by_key["group-1"]["summary"] = "Rebase both PRs onto main and add the missing test"
        by_key["verify"]["summary"] = "Verify handoffs"
        app, _client = make_app(busy=True, rows=72, cols=160, clock=lambda: 0.0)
        with_graph(app, built)
        shown = [left(row) for row in view_text(app)]
        self.assertIn("      ✓ Inventory rlaope PRs · List every open PR by the…", shown)
        self.assertIn("      ⠋ PR group 1: #138300 #107931", shown, f"{SHORT_LABEL} cells or more: the label alone")
        self.assertIn("      · Verify handoffs", shown, "a summary the label already says is not repeated")
        whole = "Inventory rlaope PRs · List every open PR by the author into inventory.json"
        self.assertEqual(node_title(by_key["inventory"]), clamp_title(whole, TITLE_CAP))
        self.assertLessEqual(len(node_title(by_key["inventory"])), TITLE_CAP)
        self.assertGreater(len("Inventory rlaope PRs · List every open PR by the author"), TITLE_CAP, "cut at a word")
        self.assertEqual(clamp_title("Apply review on #58281 · part two", 30), "Apply review on #58281 · part…")
        self.assertEqual(clamp_title("Apply review on #58281 part two", 24), "Apply review on #58281…")
        self.assertEqual(clamp_title("Antidisestablishmentarianism", 12), "Antidisesta…", "no word to cut at")

    def test_a_layer_the_graph_reader_cut_says_what_it_shows_of_how_many(self) -> None:
        # Under the graph's node cap a layer's count read as its total (`28 nodes` of 640).
        app, _client = make_app(busy=True, rows=72, cols=120, clock=lambda: 0.0)
        with_graph(app, {**sweep(), "hidden_nodes": 600, "hidden_by_group": {"layer 2": 600}})
        shown = [left(row) for row in view_text(app)]
        self.assertIn("  ▾ layer 2 · 4 of 604 nodes · 2 running · 1 failed · 1 waiting", shown)
        self.assertIn("  ▾ layer 1 · 1 node · 1 done", shown)

    def test_a_layer_the_cap_emptied_keeps_its_row_in_its_place(self) -> None:
        # scene_final under the 48-node cap drew 3 layers of a 4-layer run: the cut layer had no row at all.
        built = sweep()
        for item in built["nodes"]:
            if item.get("group") == "layer 3":
                item["group"] = "layer 4"
        built.update(hidden_nodes=161, hidden_by_group={"layer 3": 161},
                     group_order=["layer 1", "layer 2", "layer 3", "layer 4"])
        app, _client = make_app(busy=True, rows=72, cols=120, clock=lambda: 0.0)
        with_graph(app, built)
        layers = [row for row in (left(row) for row in view_text(app)) if "layer" in row]
        self.assertEqual([re.sub(r" · .*", "", row) for row in layers],
                         ["  ▾ layer 1", "  ▾ layer 2", "  ▸ layer 3", "  ▾ layer 4"])
        self.assertIn("  ▸ layer 3 · 0 of 161 nodes", layers)

    def test_a_long_token_is_cut_itself_rather_than_leaving_most_of_the_title_empty(self) -> None:
        from omh.tui.dag_tree import TITLE_CAP, clamp_title

        title = "Run the gateway retry test in tools/hermes_cli/gateway_retry_backoff_spec.py"
        self.assertEqual(clamp_title(title, TITLE_CAP), "Run the gateway retry test in tools/hermes_cli/gate…")
        self.assertEqual(clamp_title("Rebase each PR on main and run the full CI suite on it", TITLE_CAP),
                         "Rebase each PR on main and run the full CI suite on…", "a word boundary past 70% stays")

    def test_a_node_no_child_ran_for_has_no_triangle_and_one_with_no_frame_yet_has_no_detail(self) -> None:
        app, _client = tree_app(children=False)
        shown = [left(row) for row in view_text(app)]
        self.assertIn("      ⠋ PR group 1: #138300 #107931", shown)  # running, but no frame of its child yet
        self.assertFalse([row for row in shown if row.lstrip().startswith("›")])

    def test_a_node_is_bound_to_its_child_by_the_goals_marker_when_the_graph_names_no_session(self) -> None:
        nodes = {key: (*values[:-1], "") for key, values in NODES.items()}  # no session_tail on any node
        app, _client = tree_app(nodes=nodes)
        self.assertEqual([left(row) for row in view_text(app)], DEFAULT)


    def test_a_done_node_with_a_failed_extend_and_its_running_repair_under_it_opens(self) -> None:
        from _delegation_graphs import dag_export_repair_run

        # An extend round hangs under the verification that found the gap, accepted itself: shut, it would hide
        # the failed CSV node and the repair running for it.
        app, _client = make_app(busy=True, rows=63, cols=120, clock=lambda: 0.0)
        with_graph(app, dag_export_repair_run())
        shown = [left(row) for row in view_text(app)]
        self.assertEqual(shown[-3:], ["    ▾ ✓ Verify export",
                                      "        ▾ ✗ + extend · CSV export",
                                      "              ⠋ ↻ repair 1 · CSV export, with the header row"])


class FoldKeyTests(unittest.TestCase):
    """Down gives the tree the keys on its first running node; the arrows and Space fold, Esc gives them back."""

    def test_down_gives_the_tree_the_keys_on_its_first_running_node_and_nothing_moves(self) -> None:
        app, _client = tree_app()
        before = drawn(app)
        app._on_input(Key(DOWN))
        during = drawn(app)
        self.assertEqual(app.tree_selected, node_id("group-1"))
        self.assertIn(TREE_HINT, mode_row(app))
        self.assertEqual(len(during), len(before))
        self.assertEqual([left(row) for row in view_text(app)], DEFAULT, "the same rows, one highlighted")
        # One `❯`, the tree's pointer: the composer's prompt mark is gone, its rows blank while the tree has the keys.
        self.assertEqual("".join(during).count("❯"), 1, "the composer's rows are blank while the tree has the keys")
        app._on_input(Key(ESCAPE))
        self.assertIsNone(app.tree_selected)
        self.assertNotIn(TREE_HINT, mode_row(app))

    def test_ctrl_c_with_shift_or_alt_held_leaves_as_ctrl_c_does(self) -> None:
        for key in (Key(CHAR, "c", ctrl=True, shift=True), Key(CHAR, "c", ctrl=True, alt=True, protocol=True)):
            with self.subTest(key=key):
                app, client = tree_app()
                app._on_input(Key(DOWN))
                self.assertIsNotNone(app.tree_selected)
                app._on_input(key)
                self.assertEqual((app.tree_selected, client.named("session.interrupt"), app.exit_code), (None, [], None))

    def test_left_shuts_the_highlighted_node_right_opens_it_and_space_flips_it(self) -> None:
        app, _client = tree_app()
        app._on_input(Key(DOWN))
        app._on_input(Key(DOWN))  # group-2
        self.assertEqual(app.tree_selected, node_id("group-2"))
        app._on_input(Key(LEFT))
        shown = [left(row) for row in view_text(app)]
        self.assertIn("    ▸ ⠋ PR group 2: #128662 #99354", shown)
        self.assertNotIn("        › read_file(tools/session_store.py)", shown)
        app._on_input(Key(RIGHT))
        self.assertEqual([left(row) for row in view_text(app)], DEFAULT)
        app._on_input(Key(CHAR, " "))
        self.assertIn("    ▸ ⠋ PR group 2: #128662 #99354", [left(row) for row in view_text(app)])
        app._on_input(Key(ESCAPE))
        self.assertIn("    ▸ ⠋ PR group 2: #128662 #99354", [left(row) for row in view_text(app)], "the fold stays")

    def test_left_on_a_shut_node_goes_to_its_layer_and_left_again_shuts_the_layer(self) -> None:
        app, _client = tree_app()
        app._on_input(Key(DOWN))
        app._on_input(Key(LEFT))  # group-1 shut
        app._on_input(Key(LEFT))  # to layer 2
        self.assertEqual(app.tree_selected, "layer:layer 2")
        app._on_input(Key(LEFT))
        shown = [left(row) for row in view_text(app)]
        self.assertIn("  ▸ layer 2 · 4 nodes · 2 running · 1 failed · 1 waiting", shown)
        self.assertFalse([row for row in shown if "PR group" in row])
        app._on_input(Key(DOWN))
        self.assertEqual(app.tree_selected, "layer:layer 3", "a shut layer's nodes are not rows the keys move over")

    def test_up_and_down_stop_at_either_end(self) -> None:
        app, _client = tree_app()
        app._on_input(Key(DOWN))
        for _ in range(40):
            app._on_input(Key(UP))
        self.assertEqual(app.tree_selected, "layer:layer 1")
        for _ in range(40):
            app._on_input(Key(DOWN))
        self.assertEqual(app.tree_selected, node_id("verify"))

    def test_a_legacy_alt_chord_leaves_the_tree_as_esc_does(self) -> None:
        app, _client = tree_app()
        app._on_input(Key(DOWN))
        app._on_input(Key(CHAR, "b", alt=True))  # Esc and `b` in one read, as a terminal without kitty keys sends it
        self.assertIsNone(app.tree_selected)

    def test_down_with_a_draft_in_the_composer_stays_the_composers(self) -> None:
        app, _client = tree_app()
        type_text(app, "next")
        app._on_input(Key(DOWN))
        self.assertIsNone(app.tree_selected)


class CapTests(unittest.TestCase):
    """The view keeps its cap of a third of the screen: quiet layers shut, quiet nodes fold into a row, then a cut."""

    def big(self) -> dict:
        """The sweep with eight more layer-2 nodes waiting and two done, and five more layers of waiting work."""
        nodes = dict(NODES)
        for number in range(10):
            state, status = ("done", "accepted") if number < 2 else ("waiting", "ready")
            nodes[f"more-{number}"] = (f"Rebase batch {number}", "quick", KIMI, "low", 2, state, status,
                                       30 if state == "done" else None, None, "")
        for layer in range(4, 9):
            nodes[f"wait-{layer}"] = (f"Check CI {layer}", "quick", KIMI, "low", layer, "waiting", "waiting", None,
                                      None, "")
        return nodes

    def test_a_big_run_shuts_its_quiet_layers_and_folds_a_busy_layers_quiet_nodes_into_one_row(self) -> None:
        app, _client = tree_app(rows=72, nodes=self.big())
        shown = [left(row) for row in view_text(app)]
        self.assertLessEqual(len(shown), 72 // 3)
        self.assertIn("  ▸ layer 1 · 1 node · 1 done", shown)
        self.assertIn("    ▸ 11 more · 9 waiting · 2 done", shown)
        self.assertIn("    ▾ ⠋ PR group 1: #138300 #107931", shown, "the running nodes stay, open")
        self.assertIn("  ▸ layer 4 · 1 node · 1 waiting", shown)
        # Shut layers stack: no blank row between two of them.
        at = shown.index("  ▸ layer 4 · 1 node · 1 waiting")
        self.assertEqual(shown[at + 1], "  ▸ layer 5 · 1 node · 1 waiting")

    def test_past_the_folds_the_last_row_counts_the_nodes_cut(self) -> None:
        app, _client = tree_app(rows=30, nodes=self.big())  # a cap of 10
        shown = [left(row) for row in view_text(app)]
        self.assertEqual(len(shown), 10)
        self.assertRegex(shown[-1], r"^  … \d+ more nodes · ↓ to browse$")
        self.assertIn("    ▸ ⠋ PR group 1: #138300 #107931", shown, "running nodes shut before anything is cut")
        self.assertEqual(accounted(shown), len(self.big()), "every node is drawn, folded or counted")

    def test_rows_running_short_the_shut_done_layers_go_before_running_nodes(self) -> None:
        for rows in (30, 21, 12):  # caps of 10, 7 and 4
            app, _client = tree_app(rows=rows, nodes=self.big())
            shown = [left(row) for row in view_text(app)]
            self.assertNotIn("  ▸ layer 1 · 1 node · 1 done", shown, f"a done layer holds no row at {rows} rows")
            self.assertIn("    ▸ ⠋ PR group 1: #138300 #107931", shown, f"a running node keeps its row at {rows} rows")
            self.assertEqual(shown[1], "  ▾ layer 2 · 14 nodes · 2 running · 1 failed · 9 waiting · 2 done",
                             "no blank row under the header where the done layer was")
            self.assertEqual(accounted(shown), len(self.big()), "the done layer's node is in the count")

    def test_no_blank_row_stands_over_the_cut(self) -> None:
        for rows in range(9, 60):
            app, _client = tree_app(rows=rows, nodes=self.big())
            shown = [left(row) for row in view_text(app)]
            if shown[-1].startswith("  … "):
                self.assertNotEqual(shown[-2], "", f"a blank row over the cut at {rows} rows")
                self.assertEqual(accounted(shown), len(self.big()), f"every node is drawn, folded or counted at {rows}")

    def test_down_moves_no_row(self) -> None:
        # The done layers that yield their rows without the keys yield them with the keys too: Down only highlights.
        for rows, cols in ((40, 150), (30, 120), (21, 120)):
            app, _client = tree_app(rows=rows, cols=cols, nodes=self.big())
            before = [left(row) for row in view_text(app)]
            app._on_input(Key(DOWN))
            after = [left(row) for row in view_text(app)]
            self.assertEqual(app.tree_selected, node_id("group-1"))
            self.assertEqual(after[:-1], before[:-1], f"the rows moved on Down at {cols}x{rows}")
            self.assertNotIn("  ▸ layer 1 · 1 node · 1 done", after)
            self.assertRegex(after[-1], r"^  … \d+ more nodes · ↑↓ to browse$", "the count holds the done layer above")

    def test_with_the_keys_the_rows_scroll_to_the_highlight_between_counts(self) -> None:
        app, _client = tree_app(rows=30, nodes=self.big())  # a cap of 10
        app._on_input(Key(DOWN))
        seen = 0
        for _ in range(40):  # down to the last row and past it
            app._on_input(Key(DOWN))
            shown = [left(row) for row in view_text(app)]
            self.assertEqual(len(shown), 10, "the window never grows past the cap")
            self.assertIn(app.tree_selected, app.tree_state.rows, "the highlighted row is always drawn")
            self.assertEqual(accounted(shown), len(self.big()), f"every node is drawn or counted: {shown}")
            for at in (0, -1):
                if shown[at].startswith("  … "):
                    # `↑↓ to browse`: the count holds a done layer that yielded its row above and rows below.
                    self.assertRegex(shown[at], r"^  … ([1-9]\d* more nodes?|more)( above| below| · ↑↓ to browse)$",
                                     "no count of 0")
                    self.assertNotEqual(shown[1 if at == 0 else -2], "", "no blank row next to a count")
            seen += shown[0].startswith("  … ") and shown[-1].startswith("  … ")
        self.assertTrue(seen, "the window was between two counts at least once")
        self.assertEqual(shown[-1], "  ▸ layer 8 · 1 node · 1 waiting", "at the end the last row is the tree's last")
        self.assertEqual(app.tree_selected, "layer:layer 8")

    def test_opening_the_more_row_shows_its_nodes_and_highlights_the_first(self) -> None:
        app, _client = tree_app(rows=72, nodes=self.big())
        app._on_input(Key(DOWN))
        down_to(app, "more:layer 2")
        app._on_input(Key(RIGHT))
        self.assertEqual(app.tree_selected, node_id("group-4"))
        self.assertIn("      · Rebase batch 9", [left(row) for row in view_text(app)])


class TreeColourTests(unittest.TestCase):
    """The tree takes #2223's roles: the running blue (`Theme.running`) only on what runs, the failed red on a failed
    node, and a call's name in its tool family's hue (`theme.kind_style`), as the transcript paints it."""

    def test_a_running_node_is_the_running_blue_a_failed_one_red_and_a_call_its_kind_hue(self) -> None:
        from omh.tui.dag_tree import tree_lines
        from omh.tui.panels import SPINNER_FRAMES
        from omh.tui.theme import kind_style

        app, _client = tree_app()
        lines, _state = tree_lines(app.hud.payload["delegation_graph"], app.roster, 120, 40, app.theme, 0, {}, None)

        def span(row: str, text: str):
            line = next(line for line in lines if row in "".join(span.text for span in line))
            return next(span for span in line if text in span.text)  # neighbours in one style share a span

        self.assertEqual(span("PR group 1:", SPINNER_FRAMES[0]).style.fg, app.theme.running.fg)
        self.assertEqual(span("PR group 3:", "✗").style.fg, app.theme.error.fg)
        self.assertEqual(span("Inventory rlaope PRs", "✓").style.fg, app.theme.ok.fg)
        self.assertNotEqual(span("Inventory rlaope PRs", "✓").style.fg, app.theme.running.fg)
        self.assertEqual(span("terminal(uv run pytest", "terminal").style.fg, kind_style("terminal", app.theme).fg)
        self.assertEqual(span("read_file(tools/registry.py)", "read_file").style.fg,
                         kind_style("read_file", app.theme).fg)


class RepairTests(unittest.TestCase):
    def test_a_repair_hangs_under_the_node_it_repairs_with_its_own_child(self) -> None:
        app, _client = tree_app()
        shown = [left(row) for row in view_text(app)]
        at = shown.index("    ▾ ✗ PR group 3: #127631 #58015")
        self.assertEqual(shown[at + 3 : at + 6], ["        ▾ ⠋ ↻ repair 1 · Resolve the registry conflict",
                                                  "            › read_file(tools/registry.py)",
                                                  "            › Keeping both tool entries"])
        self.assertNotIn("  ▾ layer 3 · 2 nodes", " ".join(shown), "the repair is not counted in the layer it sits in")

    def test_a_failed_node_over_a_running_repair_stays_open_when_rows_run_short(self) -> None:
        app, _client = tree_app(rows=45)  # a cap of 15: open nodes shut from the bottom up, but not this one
        shown = [left(row) for row in view_text(app)]
        self.assertEqual(len(shown), 15)
        self.assertIn("    ▾ ✗ PR group 3: #127631 #58015", shown)
        self.assertIn("        ▸ ⠋ ↻ repair 1 · Resolve the registry conflict", shown)
        self.assertIn("    ▸ ⠋ PR group 2: #128662 #99354", shown)


class RepairCycleTests(unittest.TestCase):
    """`↻ repair N` reads the node's repair cycle, which the graph copies from the run record."""

    def test_a_second_cycle_reads_repair_2_once_the_first_cycles_node_left_the_drawing(self) -> None:
        from _delegation_state import PARENT, homes
        from test_dag_graph import PROMPT, call, defined, write_handoff
        from omh.plugin_bundle.omh.delegation_graph import build_delegation_graph

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
            built = build_delegation_graph(home.omh, home.hermes, PARENT)
        app, _client = make_app(busy=True, rows=72, cols=120, clock=lambda: 0.0)
        with_graph(app, built)
        shown = [left(row) for row in view_text(app)]
        self.assertTrue([row for row in shown if "↻ repair 2 · Fix export again" in row], shown)
        self.assertFalse([row for row in shown if "Fix export" in row and "again" not in row], "cycle 1 left the drawing")

    def test_a_graph_without_the_cycle_counts_the_repair_edges(self) -> None:
        nodes = dict(NODES)
        app, _client = tree_app(nodes=nodes)
        graph = app.hud.payload["delegation_graph"]
        self.assertNotIn("cycle", next(node for node in graph["nodes"] if node["id"] == node_id("group-3-fix")))
        self.assertIn("        ▾ ⠋ ↻ repair 1 · Resolve the registry conflict", [left(row) for row in view_text(app)])


class TreeActionTests(unittest.TestCase):
    """On a node a child ran for, Enter opens the child's log, and x and s interrupt and steer it as the list does."""

    def focused(self, steps: int = 1):
        app, client = tree_app()
        app._on_input(Key(DOWN))
        for _ in range(steps - 1):
            app._on_input(Key(DOWN))
        return app, client

    def test_enter_opens_the_highlighted_nodes_child_log_and_leaving_comes_back_to_the_tree(self) -> None:
        app, _client = self.focused()
        app._on_input(Key(ENTER))
        self.assertEqual(app.log_agent, subagent_id("group-1"))
        self.assertTrue(app.pager.title.startswith("PR group 1"), app.pager.title)
        app._on_input(Key(CHAR, "q"))
        self.assertEqual((app.pager, app.tree_selected), (None, node_id("group-1")))
        self.assertIn("    ▾ ⠋ PR group 1: #138300 #107931", [left(row) for row in view_text(app)], "Enter folds nothing")

    def test_x_asks_once_and_a_second_x_interrupts_the_nodes_child(self) -> None:
        app, client = self.focused()
        app._on_input(Key(CHAR, "x"))
        self.assertEqual(client.calls, [])
        self.assertIn("x again interrupts PR group 1 ·", mode_row(app))  # the name leaves the goal's colon off
        app._on_input(Key(CHAR, "x"))
        self.assertEqual(client.calls, [("subagent.interrupt", {"session_id": SID, "subagent_id": subagent_id("group-1")})])
        answer(app, client, {"found": True, "subagent_id": subagent_id("group-1")})
        self.assertEqual(notices(app)[-1], "Interrupted PR group 1.")
        self.assertEqual(app.tree_selected, node_id("group-1"))

    def test_any_other_key_ends_the_question(self) -> None:
        app, client = self.focused()
        app._on_input(Key(CHAR, "x"))
        app._on_input(Key(LEFT))  # it also shuts the node: the question ends and the key does what it does
        self.assertIn(TREE_HINT, mode_row(app))
        self.assertIn("    ▸ ⠋ PR group 1: #138300 #107931", [left(row) for row in view_text(app)])
        app._on_input(Key(CHAR, "x"))
        self.assertEqual(client.calls, [], "a first x again, not the second")

    def test_s_steers_the_nodes_child_with_the_text_sent_next(self) -> None:
        app, client = self.focused()
        app._on_input(Key(CHAR, "s"))
        self.assertIsNone(app.tree_selected)
        self.assertEqual(app.agent_steer, subagent_id("group-1"))
        type_text(app, "skip the docs")
        app._on_input(Key(ENTER))
        self.assertEqual(client.calls, [("subagent.steer", {"session_id": SID, "subagent_id": subagent_id("group-1"),
                                                            "text": "skip the docs"})])

    def test_on_a_finished_nodes_child_x_and_s_say_it_has_finished(self) -> None:
        app, client = tree_app()
        app._on_input(Key(DOWN))
        app._on_input(Key(UP))  # layer 2's row
        app._on_input(Key(UP))  # the inventory, accepted
        self.assertEqual(app.tree_selected, node_id("inventory"))
        app._on_input(Key(CHAR, "x"))
        app._on_input(Key(CHAR, "x"))
        self.assertEqual(client.calls, [])
        self.assertIn("has finished", notices(app)[-1])

    def test_on_a_layer_or_a_node_no_child_ran_for_enter_x_and_s_do_nothing(self) -> None:
        app, client = tree_app()
        app._on_input(Key(DOWN))
        for _ in range(3):  # layer 2's row, the inventory, layer 1's row
            app._on_input(Key(UP))
        self.assertEqual(app.tree_selected, "layer:layer 1")
        for key in (Key(ENTER), Key(CHAR, "x"), Key(CHAR, "s")):
            app._on_input(key)
        self.assertEqual((app.pager, client.calls, app.agent_steer, app.tree_selected),
                         (None, [], None, "layer:layer 1"))
        self.assertEqual([left(row) for row in view_text(app)], DEFAULT, "and fold nothing")
        down_to(app, node_id("group-4"))
        for key in (Key(ENTER), Key(CHAR, "x"), Key(CHAR, "s")):
            app._on_input(key)
        self.assertEqual((app.pager, client.calls, app.agent_steer), (None, [], None))


class OtherAgentsTests(unittest.TestCase):
    """An agent no node is bound to (a helper the parent delegated beside the run) closes the tree in its own group,
    where the keys reach it as the agent list did."""

    def test_a_helper_beside_the_run_is_a_row_of_its_own_group_and_enter_opens_its_log(self) -> None:
        app, _client = tree_app(rows=90)  # a cap of 30: the whole tree and the group under it
        agent_event(app, "start", "sa-helper", goal="Look up the release notes", model="glm-5.3",
                    child_session_id="helper-session")
        agent_event(app, "tool", "sa-helper", goal="Look up the release notes", model="glm-5.3",
                    child_session_id="helper-session", tool_name="web_search", tool_preview="hermes 0.22 notes")
        shown = [left(row) for row in view_text(app)]
        self.assertEqual(shown[len(DEFAULT):], ["", "  ▾ other agents · 1 agent · 1 running",
                                                 "    ▾ ⠋ Look up the release notes",
                                                 "        › web_search(hermes 0.22 notes)"])
        app._on_input(Key(DOWN))
        down_to(app, "agent:sa-helper")
        app._on_input(Key(ENTER))
        self.assertEqual(app.log_agent, "sa-helper")


    def test_a_lane_of_this_run_the_graph_no_longer_draws_is_not_another_agent(self) -> None:
        app, _client = tree_app(rows=90)
        agent_event(app, "start", "sa-old-fix", goal=f"First try at the conflict [dag:{RUN}/group-3-fix-old]",
                    child_session_id="20261022_130000_0badf00d")  # a superseded repair attempt: not in the graph
        self.assertEqual([left(row) for row in view_text(app)], DEFAULT)


class ProgressTests(unittest.TestCase):
    """`subagent.progress` is kept as the agent's progress line, without Hermes' batch tag; the second row shows the
    newest of it and the thinking or reply line, never repeating the call the first row shows."""

    BASE = {"goal": "PR group 1 [dag:sweep/group-1]", "child_session_id": "20261022_134612_a9f3e210"}

    def test_the_recorded_progress_frame_is_kept_without_its_tag_and_adds_no_log_row(self) -> None:
        roster = Roster()
        for kind, frame in FRAMES:
            roster.apply(kind, frame, 0.0)
            if kind == "subagent.progress":
                break
        agent = roster.agents[frame["subagent_id"]]
        self.assertEqual((agent.progress.kind, agent.progress.text, agent.progress_newest),
                         ("progress", "search_files, read_file, terminal, read_file, read_file", True))
        self.assertFalse([row for row in agent.log if row.kind == "progress"])

    def test_the_roster_keeps_which_of_progress_and_thinking_or_reply_came_last(self) -> None:
        roster = Roster()
        feed(roster, "start", subagent_id="a", **self.BASE)
        feed(roster, "thinking", subagent_id="a", text="Reading the review")
        agent = roster.agents["a"]
        self.assertEqual((agent.said.text, agent.progress, agent.progress_newest), ("Reading the review", None, False))
        feed(roster, "progress", subagent_id="a", text="🔀 [set 2 · 1/3] terminal, read_file")
        self.assertEqual((agent.progress.text, agent.progress_newest), ("terminal, read_file", True))
        feed(roster, "thinking", subagent_id="a", text="Rebasing now")
        self.assertEqual((agent.said.text, agent.progress_newest), ("Rebasing now", False))
        feed(roster, "complete", subagent_id="a", status="completed", summary="Rebased and pushed\nall green")
        self.assertEqual((agent.said.text, agent.progress_newest), ("Rebased and pushed", False))

    def second_row(self, *steps: tuple[str, ...]) -> list[str]:
        """The tree's rows under group 1 once its child sent `steps` (as `ACTIVITY` writes them) after its own."""
        app, _client = tree_app()
        label, _category, model, *_rest, tail = NODES["group-1"]
        base = {"goal": f"{label} [dag:{RUN}/group-1]", "model": model, "child_session_id": f"20261022_134612_{tail}"}
        for kind, *said in steps:
            if kind == "tool":
                agent_event(app, "tool", subagent_id("group-1"), **base, tool_name=said[0], tool_preview=said[1])
            else:
                agent_event(app, kind, subagent_id("group-1"), **base, text=said[0])
        shown = [left(row) for row in view_text(app)]
        at = shown.index("    ▾ ⠋ PR group 1: #138300 #107931")
        return shown[at + 1 : at + 3]

    def test_a_newer_progress_line_shows_under_the_call(self) -> None:
        self.assertEqual(self.second_row(("tool", "read_file", "a.py"), ("progress", "🔀 [set 1] patch, terminal, patch")),
                         ["        › read_file(a.py)", "        › patch, terminal, patch"])

    def test_a_progress_line_ending_on_the_shown_call_gives_way_to_thinking(self) -> None:
        # The fixture's thinking line came before: the newer progress ends on `terminal`, the call the first row shows.
        self.assertEqual(self.second_row(("tool", "terminal", "git push"), ("progress", "🔀 [set 1] read_file, terminal")),
                         ["        › terminal(git push)", "        › Adding the test the review asks for"])

    def test_with_no_thinking_or_reply_it_drops_the_repeated_name(self) -> None:
        roster = Roster()
        feed(roster, "tool", subagent_id="a", tool_name="terminal", tool_preview="git push", **self.BASE)
        feed(roster, "progress", subagent_id="a", text="🔀 [set 1 · 1/3] read_file, patch, terminal")
        from omh.tui.dag_tree import _second_row

        self.assertEqual(_second_row(roster.agents["a"]).text, "read_file, patch")
        feed(roster, "progress", subagent_id="a", text="🔀 [set 1 · 1/3] terminal")
        self.assertIsNone(_second_row(roster.agents["a"]), "nothing left but the call the first row shows")

    def test_the_latest_call_outlives_a_tail_that_replaces_the_log(self) -> None:
        roster = Roster()
        feed(roster, "tool", subagent_id="a", tool_name="terminal", tool_preview="git push", **self.BASE)
        roster.ingest_tail("a", "pushing\nEverything up-to-date")
        agent = roster.agents["a"]
        self.assertEqual((agent.last_call.text, agent.last_call.detail), ("terminal", "git push"))
        self.assertEqual((agent.said.text, agent.progress_newest), ("Everything up-to-date", False))
        self.assertEqual(agent.dag_node, "d:sweep:group-1")

    def test_the_tree_shows_the_progress_line_under_its_node(self) -> None:
        app, _client = tree_app()
        shown = [left(row) for row in view_text(app)]
        at = shown.index("    ▾ ⠋ PR group 2: #128662 #99354")
        self.assertEqual(shown[at + 2], "        › terminal, read_file, patch, terminal, terminal")


class TurnBoundaryTests(unittest.TestCase):
    """A new turn keeps the open dag run's lanes, so the tree keeps its detail rows without waiting for a frame.

    The three cases that keep nothing are the behaviour before this change, held: without an open dag run (no dag
    graph, or a run that is over) and when the session is left, a new turn still empties the roster."""

    def test_a_prompt_keeps_the_runs_lanes_and_their_rows(self) -> None:
        app, _client = tree_app()
        app.turn_pending = False  # the turn that sent them ended; the next prompt starts a turn
        agent_event(app, "start", "sa-helper", goal="look something up", child_session_id="helper-session")
        type_text(app, "how is it going")
        app._on_input(Key(ENTER))
        lanes = {subagent_id(key) for key, values in NODES.items() if values[-1]}
        self.assertEqual(set(app.roster.agents), lanes, "the run's lanes stay; the turn's other agent goes")
        self.assertEqual([left(row) for row in view_text(app)], DEFAULT)

    def test_without_a_dag_run_a_prompt_empties_the_roster_as_before(self) -> None:
        app, _client = make_app(busy=True, rows=72, cols=120, clock=lambda: 0.0)
        run_children(app)  # the same children, but no dag graph in the HUD
        app.turn_pending = False
        type_text(app, "next")
        app._on_input(Key(ENTER))
        self.assertEqual(app.roster.agents, {})

    def test_a_run_that_is_over_keeps_nothing(self) -> None:
        nodes = {key: (*values[:5], "done", "accepted", *values[7:]) for key, values in NODES.items()}
        app, _client = tree_app(nodes=nodes)
        app.turn_pending = False
        type_text(app, "next")
        app._on_input(Key(ENTER))
        self.assertEqual(app.roster.agents, {})

    def test_leaving_the_session_keeps_nothing(self) -> None:
        app, client = tree_app()
        type_text(app, "/new")
        app._on_input(Key(ENTER))
        answer(app, client, {"session_id": "live-2", "stored_session_id": "stored-2", "info": {}})
        self.assertEqual(app.roster.agents, {})

    def test_the_first_payload_showing_the_run_over_drops_the_lanes_a_stale_one_kept(self) -> None:
        from omh.tui.panels import HudSnapshot
        from test_tui_panels import hud_payload

        def take(app, built: dict | None, error: bool = False) -> None:
            payload = hud_payload(None)
            if built is not None:
                payload["delegation_graph"] = built
            if error:
                payload["error"] = "read failed"
            app.poller.take = lambda: HudSnapshot(app.stored_id, payload, 0.0)  # type: ignore[method-assign]
            app._take_hud()

        app, _client = tree_app()  # the run read as open when the next turn starts: a stale payload
        app.turn_pending = False
        type_text(app, "next")
        app._on_input(Key(ENTER))
        agent_event(app, "start", "sa-new", goal="look something up", child_session_id="new-session")
        lanes = {subagent_id(key) for key, values in NODES.items() if values[-1]}
        take(app, sweep())  # still open
        self.assertEqual(set(app.roster.agents), lanes | {"sa-new"})
        take(app, None, error=True)  # the HUD could not read: nothing is known about the run
        self.assertEqual(set(app.roster.agents), lanes | {"sa-new"})
        from omh.plugin_bundle.omh.delegation_graph import inactive_graph

        for reason in ("no_session", "lingered"):  # a payload that shows no run shows nothing over
            take(app, inactive_graph(reason))
            self.assertEqual(set(app.roster.agents), lanes | {"sa-new"}, reason)
        take(app, None)  # no graph in the payload at all
        self.assertEqual(set(app.roster.agents), lanes | {"sa-new"})
        over = {key: (*values[:5], "done", "accepted", *values[7:]) for key, values in NODES.items()}
        take(app, sweep(over))
        self.assertEqual(set(app.roster.agents), {"sa-new"}, "the run's lanes go; this turn's agent stays")

    def test_a_lane_a_new_turn_kept_still_takes_its_frames(self) -> None:
        app, _client = tree_app()
        app.turn_pending = False
        type_text(app, "next")
        app._on_input(Key(ENTER))
        label, _category, model, *_rest, tail = NODES["group-1"]
        app._on_event(Event("subagent.tool", SID, {"subagent_id": subagent_id("group-1"), "goal": f"{label} [dag:{RUN}/group-1]",
                                                   "model": model, "child_session_id": f"20261022_134612_{tail}",
                                                   "tool_count": 9, "tool_name": "terminal", "tool_preview": "git push"}))
        self.assertIn("        › terminal(git push)", [left(row) for row in view_text(app)])


if __name__ == "__main__":
    unittest.main()


def other_run(built: dict) -> dict:
    """`built` as another run of the same name draws it: the same nodes under another run id."""
    import json

    return json.loads(json.dumps(built).replace(f"d:{RUN}:", "d:other:"))


def shut_layer_2(app) -> None:
    """Down, then Left until layer 2 is shut: the person's fold, kept in `tree_folds`."""
    app._on_input(Key(DOWN))
    for _ in range(3):  # shut group 1, go to its layer, shut the layer
        app._on_input(Key(LEFT))
    if "  ▸ layer 2 · 4 nodes · 2 running · 1 failed · 1 waiting" not in [left(row) for row in view_text(app)]:
        raise AssertionError("layer 2 did not shut")
    app._on_input(Key(ESCAPE))


LAYER_2_OPEN = "  ▾ layer 2 · 4 nodes · 2 running · 1 failed · 1 waiting"


class FoldScopeTests(unittest.TestCase):
    """The person's folds belong to one run: a layer's key is only its label, so a fold carried into the next run, or
    into a run of the same name in the next session, would shut that run's running nodes out of sight."""

    def test_a_layer_shut_in_one_run_opens_in_the_next(self) -> None:
        app, _client = tree_app()
        shut_layer_2(app)
        with_graph(app, other_run(sweep()))
        shown = [left(row) for row in view_text(app)]
        self.assertIn(LAYER_2_OPEN, shown)
        self.assertEqual(app.tree_folds, {})

    def test_a_fold_stays_while_the_run_goes_on(self) -> None:
        app, _client = tree_app()
        shut_layer_2(app)
        with_graph(app, sweep())  # the next payload of the same run
        self.assertNotIn(LAYER_2_OPEN, [left(row) for row in view_text(app)])

    def test_leaving_the_session_drops_the_folds(self) -> None:
        app, client = tree_app()
        shut_layer_2(app)
        type_text(app, "/new")
        app._on_input(Key(ENTER))
        answer(app, client, {"session_id": "live-2", "stored_session_id": "stored-2", "info": {}})
        self.assertEqual(app.tree_folds, {})
        with_graph(app, sweep())  # a run of the same name in the session opened
        run_children(app)
        self.assertIn(LAYER_2_OPEN, [left(row) for row in view_text(app)])


class SmallCapTests(unittest.TestCase):
    """Under three rows a tree has no room for its highlight between two counts: Down opens the agent list there."""

    def test_the_tree_gives_the_keys_back_when_the_window_shrinks_under_three_rows(self) -> None:
        app, _client = tree_app(rows=30)
        app._on_input(Key(DOWN))
        self.assertEqual(app.tree_selected, node_id("group-1"))
        app.terminal.screen.resize(8, 120)  # type: ignore[attr-defined]  # a cap of 2
        app._on_resize()
        app._full_redraw()
        app.redraw_at = None
        drawn(app)
        self.assertIsNone(app.tree_selected, "the tree kept the keys with no room for its highlight")
        type_text(app, "hi")
        self.assertEqual(app.composer.text, "hi", "a typed key reaches the composer")

    def test_with_two_rows_or_fewer_down_opens_the_list(self) -> None:
        for rows in (6, 8):  # caps of 1 and 2
            app, _client = tree_app(rows=rows)
            app._on_input(Key(DOWN))
            self.assertIsNone(app.tree_selected, f"the tree took the keys at {rows} rows")
            self.assertEqual(app.list_selected, subagent_id("inventory"), f"Down opened no list at {rows} rows")

    def test_with_three_rows_the_tree_takes_the_keys(self) -> None:
        app, _client = tree_app(rows=9)
        app._on_input(Key(DOWN))
        self.assertEqual(app.tree_selected, node_id("group-1"))
        self.assertIn("    ▸ ⠋ PR group 1: #138300 #107931", [left(row) for row in view_text(app)])


class StaleFrameTests(unittest.TestCase):
    """Keys read in one batch arrive between two frames; a payload in between can take the highlighted row away."""

    def test_a_key_after_the_highlighted_node_left_keeps_the_tree(self) -> None:
        app, _client = tree_app()
        app._on_input(Key(DOWN))
        app._on_input(Key(DOWN))
        self.assertEqual(app.tree_selected, node_id("group-2"))
        nodes = {key: values for key, values in NODES.items() if key != "group-2"}
        with_graph(app, sweep(nodes))  # no frame drawn since
        app._on_input(Key(DOWN))
        self.assertEqual(app.tree_selected, "layer:layer 2", "the highlight goes to the row the node stood under")
        self.assertIn(TREE_HINT, mode_row(app))

    def test_a_key_after_the_run_ended_gives_the_keys_back(self) -> None:
        app, _client = tree_app()
        app._on_input(Key(DOWN))
        nodes = {key: (*values[:5], "done", "accepted", *values[7:]) for key, values in NODES.items()}
        with_graph(app, sweep(nodes))
        app.turn_pending = False  # the run ended and the turn with it: the tree folds to its summary line
        drawn(app)
        app._on_input(Key(DOWN))
        self.assertIsNone(app.tree_selected)


class TreeMouseTests(unittest.TestCase):
    """While the tree has the keys a click on its row selects it, as a click on a list row did; reports are on only
    then (round 2: the wheel scrolls and a drag selects the rest of the time)."""

    def test_a_click_on_a_node_row_highlights_it_and_opens_its_childs_log(self) -> None:
        from test_tui_agent_mouse import click, reporting, row_of, settled

        app, _client = tree_app()
        settled(app)
        self.assertFalse(reporting(app), "no reports while the composer has the keys")
        app._on_input(Key(DOWN))
        self.assertTrue(reporting(app))
        click(app, 10, row_of(app, "PR group 2: #128662"))
        self.assertEqual(app.tree_selected, node_id("group-2"))
        self.assertEqual(app.log_agent, subagent_id("group-2"))

    def test_a_click_on_a_layer_row_only_highlights_it(self) -> None:
        from test_tui_agent_mouse import click, row_of, settled

        app, _client = tree_app()
        settled(app)
        app._on_input(Key(DOWN))
        click(app, 10, row_of(app, "layer 3 · 1 node"))
        self.assertEqual(app.tree_selected, "layer:layer 3")
        self.assertIsNone(app.pager)


    def test_a_click_on_the_header_row_does_nothing(self) -> None:
        from test_tui_agent_mouse import click, row_of, settled

        app, _client = tree_app()
        settled(app)
        app._on_input(Key(DOWN))
        click(app, 10, row_of(app, "DAG · sweep · 7 nodes"))
        self.assertEqual(app.tree_selected, node_id("group-1"))
        self.assertIsNone(app.pager)


class TreeChipTests(unittest.TestCase):
    def test_the_count_is_the_runs_running_lanes(self) -> None:
        # During a dag run the chip counts the lanes running now, as the tree draws them (2026-10-23): the roster
        # holds every child the run started, an attempt the graph no longer draws and a helper beside it too.
        app, _client = tree_app()
        graph = app.hud.payload["delegation_graph"]
        running = sum(1 for node in graph["nodes"] if node.get("kind") != "root" and node.get("state") == "running")
        self.assertIn(f"{running} agent{'' if running == 1 else 's'}", mode_row(app))
        agent_event(app, "start", "sa-old-fix", goal=f"Resolve the registry conflict [dag:{RUN}/group-3-fix-0]",
                    child_session_id="20261022_134612_00000000")  # an attempt the graph no longer draws
        agent_event(app, "start", "sa-helper", goal="look something up", child_session_id="helper-session")
        self.assertIn(f"{running} agent{'' if running == 1 else 's'}", mode_row(app))
        for node in graph["nodes"]:
            if node.get("kind") != "root":
                node["state"] = "done"
        app.turn_pending = False
        self.assertIsNone(re.search(r"\d+ agents?", mode_row(app)), mode_row(app))  # a run over: no count

    def test_a_count_of_a_thousand_or_more_has_separators(self) -> None:
        built = sweep()
        for number in range(1200):
            built["nodes"].append(lane(f"d:{RUN}:extra-{number}", f"Extra lane {number}", "quick", KIMI, "low",
                                       "running", order=100 + number, group="layer 2"))
            built["edges"].append({"from": node_id("inventory"), "to": f"d:{RUN}:extra-{number}",
                                   "kind": "depends_on"})
        app, _client = make_app(busy=True, rows=72, cols=120, clock=lambda: 0.0)
        with_graph(app, built)
        self.assertIn("1,203 agents", mode_row(app))


def mixed(done: bool = True) -> dict:
    """Twelve running nodes, a layer of two between them and six more running ones: done (it gives its row way to
    fit) or running (nothing gives way)."""
    nodes = {}
    for number in range(12):
        nodes[f"fix-{number}"] = (f"Fix batch {number}", "quick", KIMI, "low", 1, "running", "running", 30, 100, "")
    for number in range(2):
        state, status = ("done", "accepted") if done else ("running", "running")
        nodes[f"check-{number}"] = (f"Check {number}", "quick", KIMI, "low", 2, state, status, 30, 100, "")
    for number in range(6):
        nodes[f"ship-{number}"] = (f"Ship {number}", "quick", KIMI, "low", 3, "running", "running", 30, 100, "")
    return nodes


class CountLabelTests(unittest.TestCase):
    """With the keys, a count says where the nodes it holds are: `above`, `below`, or `↑↓ to browse` when it holds a
    done layer that gave way from the other side of it or from between the rows shown. 20 nodes, a cap of 10."""

    def window(self, key: str, done: bool = True) -> list[str]:
        app, _client = tree_app(rows=30, nodes=mixed(done), children=False)
        app._on_input(Key(DOWN))
        down_to(app, key)
        shown = [left(row) for row in view_text(app)]
        self.assertEqual(len(shown), 10)
        self.assertIn(key, app.tree_state.rows, "the highlighted row is drawn")
        self.assertEqual(accounted(shown), 20, shown)
        return shown

    def test_the_first_rows_count_what_is_below(self) -> None:
        shown = self.window(node_id("fix-0"))
        self.assertEqual(shown[-1], "  … 13 more nodes below", "the done layer is below the rows shown")

    def test_the_middle_counts_a_done_layer_past_the_window_below(self) -> None:
        shown = self.window(node_id("fix-9"))
        self.assertEqual((shown[0], shown[-1]), ("  … 4 more nodes above", "  … 8 more nodes below"))

    def test_the_middle_says_browse_for_a_done_layer_between_its_rows(self) -> None:
        shown = self.window("layer:layer 3")
        self.assertEqual((shown[0], shown[-1]), ("  … 11 more nodes · ↑↓ to browse", "  … 3 more nodes below"))

    def test_the_last_rows_say_browse_for_a_done_layer_between_them(self) -> None:
        shown = self.window(node_id("ship-5"))
        self.assertEqual(shown[0], "  … 13 more nodes · ↑↓ to browse")

    def test_with_nothing_given_way_the_last_rows_count_what_is_above(self) -> None:
        shown = self.window(node_id("ship-5"), done=False)
        self.assertEqual(shown[0], "  … 13 more nodes above")

    def test_a_highlighted_done_layer_keeps_its_row(self) -> None:
        shown = self.window("layer:layer 2")
        self.assertIn("  ▸ layer 2 · 2 nodes · 2 done", shown)


class KeptRunTests(unittest.TestCase):
    """A run that is over takes its kept lanes with it, by run: a lane whose node left the drawing goes too, and
    another run's lanes stay."""

    def take(self, app, built: dict) -> None:
        from omh.tui.panels import HudSnapshot
        from test_tui_panels import hud_payload

        payload = hud_payload(None)
        payload["delegation_graph"] = built
        app.poller.take = lambda: HudSnapshot(app.stored_id, payload, 0.0)  # type: ignore[method-assign]
        app._take_hud()

    def test_the_run_over_drops_its_superseded_lane_and_only_its_own(self) -> None:
        nodes = {**NODES, "old-fix": ("Resolve the registry conflict", "quick", KIMI, "low", 3, "running", "running",
                                      12, 300, "")}
        app, _client = tree_app(nodes=nodes)
        agent_event(app, "start", "sa-old-fix", goal=f"Resolve the registry conflict [dag:{RUN}/old-fix]",
                    child_session_id="20261022_134612_0ldf1x00")
        app.turn_pending = False
        type_text(app, "next")
        app._on_input(Key(ENTER))
        self.assertIn("sa-old-fix", app.roster.agents, "the turn kept the lane while its node was drawn")
        over = {key: (*values[:5], "done", "accepted", *values[7:]) for key, values in NODES.items()}
        self.take(app, other_run(sweep(over)))  # another run is over: this one's lanes stay
        self.assertIn("sa-old-fix", app.roster.agents)
        self.assertIn(subagent_id("group-1"), app.roster.agents)
        self.take(app, sweep(over))  # this run is over, without the superseded attempt's node
        self.assertEqual(app.roster.agents, {})


OVER = {key: (*values[:5], "done", "accepted", *values[7:]) for key, values in NODES.items()}


def dag_end(run: str = RUN) -> Event:
    """The `omh_dag` settle that ended the run, as its `tool.complete` carries it (`dag_block.moment`)."""
    import json

    result = {"status": "ok", "run": run, "action": "settle", "state": "done",
              "nodes": [{"id": key, "state": "accepted"} for key in NODES]}
    return Event("tool.complete", SID, {"tool_id": "t-end", "name": "omh_dag", "result": json.dumps(result)})


def turn_end(app) -> None:
    app._on_event(Event("message.complete", SID, {"text": "done"}))


class RunEndTests(unittest.TestCase):
    """A dag run that is over leaves the view under the composer as its turn ends (the owner, 2026-10-26: it stayed
    there until the next prompt). Its end print in the transcript keeps the final graph, and `/dag` the whole of it.
    A run still open, between turns or across them, keeps its tree."""

    def test_a_run_that_ended_leaves_the_view_when_its_turn_ends(self) -> None:
        app, _client = tree_app(nodes=OVER)  # every lane settled while the turn runs: the tree stays until it ends
        self.assertGreater(len(view_text(app)), 1)
        turn_end(app)
        self.assertEqual(view_text(app), [], "no summary line, no tree: the end print in the transcript says it")
        self.assertIsNone(re.search(r"\d+ agents?", mode_row(app)), mode_row(app))

    def test_the_ended_run_does_not_come_back_while_the_next_turn_runs(self) -> None:
        app, _client = tree_app(nodes=OVER)
        turn_end(app)
        view_text(app)
        type_text(app, "thanks")
        app._on_input(Key(ENTER))
        self.assertTrue(app._busy())
        self.assertEqual(view_text(app), [], "the finished run's tree is not drawn again for the next turn")

    def test_the_ended_runs_agents_do_not_come_back_once_its_graph_lingers_out(self) -> None:
        from omh.plugin_bundle.omh.delegation_graph import inactive_graph

        app, _client = tree_app(nodes=OVER)
        turn_end(app)
        view_text(app)
        with_graph(app, inactive_graph("settled"))  # the HUD stops drawing a settled graph after its linger
        self.assertEqual(view_text(app), [], "the run's finished children are not listed in its place")

    def test_a_run_still_open_keeps_its_tree_between_turns_and_into_the_next(self) -> None:
        # The negative case: a dag-ulw run goes on across turns (each child's result starts the parent's next turn),
        # so a turn that ends with lanes running, or with every drawn lane settled but the run open, keeps the tree.
        app, _client = tree_app()
        turn_end(app)
        self.assertEqual([left(row) for row in view_text(app)], DEFAULT)
        type_text(app, "how is it going")
        app._on_input(Key(ENTER))
        self.assertEqual([left(row) for row in view_text(app)], DEFAULT)
        held = sweep(OVER)
        held["dag_open"] = True  # a node is out though its lane reads settled, or a repair is due
        app, _client = tree_app(nodes=OVER)
        with_graph(app, held)
        turn_end(app)
        self.assertGreater(len(view_text(app)), 1)
        type_text(app, "next")
        app._on_input(Key(ENTER))
        self.assertGreater(len(view_text(app)), 1)

    def test_the_end_print_clears_the_view_in_its_frame_though_the_panels_payload_is_older(self) -> None:
        # The HUD is read on its own clock, so the frame the turn ends in can still hold a payload with a lane
        # running. The end print reads the graph afresh: the view goes with it, in that frame.
        from omh.tui import dag_block

        app, _client = tree_app()  # the panel's payload: lanes still running
        app.stored_id = "stored-1"
        over = sweep(OVER)
        over["changed_at"] = 50.0
        app.read_dag_graph = lambda _omh, _hermes, session: over
        app.hud.payload["delegation_graph"]["changed_at"] = 40.0
        app._on_event(dag_end())
        turn_end(app)
        printed = [block.title for block in app.transcript.blocks + app.transcript._held
                   if isinstance(block, dag_block.DagBlock)]
        self.assertEqual(printed, ["end · done"])
        self.assertEqual(view_text(app), [])
        reopened = sweep({**NODES, "csv": ("CSV export", "quick", KIMI, "low", 4, "running", "running", 3, 10, "")})
        reopened["changed_at"] = 60.0  # an extend round reopened the run after its end
        with_graph(app, reopened)
        self.assertGreater(len(view_text(app)), 1, "a run that moved on after its end is drawn again")

    def test_on_the_bottom_rows_the_freed_rows_go_under_the_info_line_not_between_the_output_and_the_composer(self):
        # 150x42, the region on the screen's last row. The end print of a run of 20 lanes is condensed (a few rows),
        # shorter than the tree it replaces: the rows it leaves over stay blank under the info line, so no blank band
        # stands between the turn's last lines and the composer, and the composer never moves up. Output that comes
        # after takes them.
        from test_dag_transcript import big_run
        from test_tui_agent_view import box_top, pinned

        over = big_run((4, 6, 6, 4), {f"n{number}": "done" for number in range(1, 21)})
        app, _client = tree_app(rows=42, cols=150, children=False)
        pinned(app)
        with_graph(app, over)
        app.stored_id = "stored-1"
        app.read_dag_graph = lambda _omh, _hermes, session: over
        top = box_top(drawn(app))
        app._on_event(dag_end(run="r1"))
        turn_end(app)
        screen = drawn(app)
        self.assertGreaterEqual(box_top(screen), top, "the composer does not move up")
        info = box_top(screen) + 3
        # The tree's rows are blank under the info line, down to the region's last row.
        self.assertEqual(screen[info + 1 : 42], [""] * (41 - info), "the tree's rows are blank under the info line")
        self.assertIn("[⚚ OMH Native]", screen[info])
        above = screen[box_top(screen) - 2 : box_top(screen)]
        self.assertTrue(above[0].strip().startswith("✻"), screen)  # the turn's summary line, then one spacer row
        self.assertEqual(drawn(app), screen, "the next frame keeps them")
        held = app.frame_budget.agents
        app.transcript.add_notice("one\ntwo\nthree")
        self.assertLess((after := (drawn(app), app.frame_budget.agents))[1], held, after[0])
        self.assertEqual(after[0][box_top(after[0]) - 2].strip(), "three", "the output stands right over the composer")

    def test_another_run_is_drawn_after_one_ended(self) -> None:
        app, _client = tree_app(nodes=OVER)
        turn_end(app)
        type_text(app, "next")
        app._on_input(Key(ENTER))
        with_graph(app, other_run(sweep()))
        self.assertGreater(len(view_text(app)), 1)
