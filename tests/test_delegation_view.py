"""The delegation view: the boxes for a dag run and its variants, the tree, and what it never draws.

The snapshots are the drawings themselves, reviewed as drawings: the export
run (five nodes over three frontiers, one in each state a box colours
apart) at 100 columns and in ASCII at 80, and the tree a narrow terminal or
a tight budget gets. The other tests hold what one drawing cannot: each
box's four lines, frontiers side by side with their label, the edges drawn
between two frontiers (and the one connector where they cannot be drawn
exactly) and their colour, Dependencies that are the graph's edges
exactly, Node details only for a running or highlighted node, the width
fallback, the roles a painter colours by state, `/dag`'s fold and highlight,
no line wider than its width in terminal cells, and no exception for
anything malformed.
"""

from __future__ import annotations

import random
import re
import unittest

from _local_package import load_local_package

load_local_package()

from _delegation_graphs import (  # noqa: E402
    dag_export_button_repair_run,
    dag_export_repair_run,
    dag_export_run,
    export_run,
    graph,
    lane,
    nested,
    owner_mock,
    parallel,
    root,
    with_tokens,
)
from omh.plugin_bundle.omh.delegation_view import (  # noqa: E402
    BOX_MIN_WIDTH,
    Focus,
    cells,
    clean_text,
    render_delegation_view,
)

EXPORT100 = """\
OMH / DAG · 5 tasks
export feature · 1/1 · main opus-5-5:high
Running · Done 1/5 · 1 failed

                                  ┌──────────────────────────────┐
                                  │ Export API                   │
                                  │ quick · glm-5.3-flash:low    │
                                  │ ✓ Accepted 12s               │
                                  │ Start node                   │
                                  └──────────────────────────────┘
                                                  │
                ╭─────────────────────────────────┼─────────────────────────────────╮
                ▼                                 ▼                                 ▼
┌──────────────────────────────┐  ┌──────────────────────────────┐  ┌──────────────────────────────┐
│ Export button                │  │ Export docs                  │  │ Export CLI flag              │
│ unspecified-high · glm-5.3:… │  │ writing                      │  │ quick · glm-5.3-flash:low    │
│ ● Running 21s                │  │ ◌ Handed out                 │  │ ✗ Failed 8s                  │
│ ← Export API                 │  │ ← Export API                 │  │ ← Export API                 │
└──────────────────────────────┘  └──────────────────────────────┘  └──────────────────────────────┘
· Same frontier
                │                                 │                                 │
                ╰─────────────────────────────────┼─────────────────────────────────╯
                                                  ▼
                                  ┌──────────────────────────────┐
                                  │ Verify export                │
                                  │ unspecified-high             │
                                  │ ○ Waits on 3 lanes           │
                                  │ ← Export button, Export doc… │
                                  └──────────────────────────────┘

Dependencies
  Export API → Export button
  Export API → Export docs
  Export API → Export CLI flag
  Export button → Verify export
  Export docs → Verify export
  Export CLI flag → Verify export

Node details
  ● Export button
    unspecified-high · glm-5.3:low
    Running 21s · layer 2 · session 7c41e9a2
"""

EXPORT80ASCII = """\
OMH / DAG - 5 tasks
export feature - 1/1 - main opus-5-5:high
Running - Done 1/5 - 1 failed

                  +--------------------------------+
                  | Export API                     |
                  | quick - glm-5.3-flash:low      |
                  | + Accepted 12s                 |
                  | Start node                     |
                  +--------------------------------+
                                   :
                                   .
+--------------------------------+  +--------------------------------+
| Export button                  |  | Export docs                    |
| unspecified-high - glm-5.3:low |  | writing                        |
| * Running 21s                  |  | o Handed out                   |
| <- Export API                  |  | <- Export API                  |
+--------------------------------+  +--------------------------------+
+--------------------------------+
| Export CLI flag                |
| quick - glm-5.3-flash:low      |
| x Failed 8s                    |
| <- Export API                  |
+--------------------------------+
- Same frontier
                                   :
                                   .
                  +--------------------------------+
                  | Verify export                  |
                  | unspecified-high               |
                  | . Waits on 3 lanes             |
                  | <- Export button, Export do... |
                  +--------------------------------+

Dependencies
  Export API -> Export button
  Export API -> Export docs
  Export API -> Export CLI flag
  Export button -> Verify export
  Export docs -> Verify export
  Export CLI flag -> Verify export

Node details
  * Export button
    unspecified-high - glm-5.3:low
    Running 21s - layer 2 - session 7c41e9a2
"""

NESTED34TREE = """\
DAG · delegation · 6 nodes · 4 ed…
3 running · 2 dispatched · 1 done
◆ main · opus-5-5:high
├─ ● Port the auth module
│    architect · opu… · running 6…
│  ├─ ✓ Port token store
│  │    inherit · opu… · done 2m…
│  └─ ● Sub-orchestrate refresh
│       inherit · opu… · running…
│     ├─ ◌ Refresh tokens
│     │    ? · dispatched
│     └─ ◌ Rotate keys
│          ? · dispatched
└─ ● 인증 모듈 문서 정리
     writing · opu… · running 5m…
"""

NESTED40BUDGET = """\
DAG · delegation · 6 nodes · 4 edges
3 running · 2 dispatched · 1 done
◆ main · opus-5-5:high
├─ ● Port the auth module
│    architect · opus-… · running 6m 40s
│  ├─ ✓ Port token store
│  │    inherit · opus-5-… · done 2m 11s
│  └─ ● Sub-orchestrate refresh
│       inherit · opus-… · running 3m 2s
│     ├─ ◌ Refresh tokens
│     │    ? · dispatched
│     └─ ◌ Rotate keys
│          ? · dispatched
└─ ● 인증 모듈 문서 정리
     writing · opus-5-… · running 5m 55s
"""

EXPORT_TREE_CUT_8 = """\
DAG · export feature · 5 nodes · 6 edges · 1 running · 1 failed · 1 dispatched · 1 waiting · 1 done
◆ main · opus-5-5:high
├─ layer 2
│  ├─ ● Export button    unspecified-high  glm-5.3:low        running 21s
│  ├─ ◌ Export docs      writing                              handed out
│  └─ ✗ Export CLI flag  quick             glm-5.3-flash:low  failed 8s
└─ +2 more nodes (1 done)
"""

EXPORT_TREE_CUT_6 = """\
DAG · export feature · 5 nodes · 6 edges · 1 running · 1 failed · 1 dispatched · 1 waiting · 1 done
◆ main · opus-5-5:high
├─ layer 2
│  ├─ ● Export button    unspecified-high  glm-5.3:low        running 21s
│  └─ ✗ Export CLI flag  quick             glm-5.3-flash:low  failed 8s
└─ +3 more nodes (1 done)
"""

LAYER_CUT_7 = """\
DAG · delegation · 6 nodes · 5 edges · 1 running · 5 waiting
◆ main · opus-5-5:high
├─ layer 1
│  └─ ● Schema           deep   opus-5-5:high      running 30s
└─ layer 2
   ├─ · Migrate table 4  quick  glm-5.3-flash:low  waiting
   └─ +4 more nodes
"""

BUDGET = dict(width=40, max_chars=1782, max_lines=42)
BUTTON, DOCS, CLI = "d:r1:button", "d:r1:docs", "d:r1:cli"


def text(graph_payload: dict, **options) -> str:
    return render_delegation_view(graph_payload, **options).text()


def box_lines(view) -> dict[str, list[str]]:
    """Each box's lines, by node id: what sits between its side borders, read off the drawing."""
    lines = view.text_lines()
    by_top: dict[int, list[str]] = {}
    for node_id, top, _bottom in view.boxes:
        by_top.setdefault(top, []).append(node_id)
    found: dict[str, list[str]] = {}
    for node_id, top, bottom in view.boxes:
        column = by_top[top].index(node_id)
        found[node_id] = [re.findall(r"[│|] (.*?) *[│|]", lines[at])[column] for at in range(top + 1, bottom)]
    return found


def box_spans(view, node_id: str) -> list[list[tuple[str, str]]]:
    """One box's lines as (text, role) pieces, cut out of the rows it shares: its top border, then each line inside
    its side borders (the borders left out), then its bottom border."""
    top, bottom = next((first, last) for named, first, last in view.boxes if named == node_id)
    column = [named for named, first, _last in view.boxes if first == top].index(node_id)
    row = view.text_lines()[top]
    left = [at for at, char in enumerate(row) if char == "┌"][column]
    right = [at for at, char in enumerate(row) if char == "┐"][column]
    found = []
    for at in range(top, bottom + 1):
        pieces, place = [], 0
        for segment in view.lines[at]:
            for char in segment.text:
                inside = left < place < right if top < at < bottom else left <= place <= right
                if inside:
                    if pieces and pieces[-1][1] == segment.role:
                        pieces[-1] = (pieces[-1][0] + char, segment.role)
                    else:
                        pieces.append((char, segment.role))
                place += 1
        found.append([(text, role) for text, role in pieces if text.strip()])
    return found


def section(view, heading: str) -> list[str]:
    """The lines under ``heading`` up to the next blank line, their indent kept."""
    lines = view.text_lines()
    if heading not in lines:
        return []
    start = lines.index(heading) + 1
    end = next((at for at in range(start, len(lines)) if not lines[at]), len(lines))
    return lines[start:end]


def cards(view) -> list[str]:
    """The titles of the Node details cards, in order."""
    return [line[4:] for line in section(view, "Node details") if line.startswith("  ") and not line.startswith("    ")]


def branch_problems(drawing: str) -> list[str]:
    """Where a tree's branches lie: a `├─` with no sibling after it, or a `└─` that one follows."""
    rows = [row for row in drawing.splitlines() if row[:1] in "├└│ "]
    found = []
    for at, row in enumerate(rows):
        column = next((index for index, char in enumerate(row) if char in "├└"), None)
        if column is None:
            continue
        sibling = False
        for later in rows[at + 1:]:
            cell = later[column] if column < len(later) else " "
            if cell in "├└":
                sibling = True
                break
            if cell != "│" and (cell != " " or later[:column].strip(" │")):
                break
        if row[column] == "├" and not sibling:
            found.append(f"a ├─ with nothing after it: {row!r}")
        if row[column] == "└" and sibling:
            found.append(f"a └─ with a sibling after it: {row!r}")
    return found


def lane_edges(payload: dict) -> set[tuple[str, str, str]]:
    titles = {node["id"]: node["title"] for node in payload["nodes"] if node["kind"] != "root"}
    return {(titles[edge["from"]], titles[edge["to"]], edge["kind"]) for edge in payload["edges"]
            if edge["from"] in titles and edge["to"] in titles}


def fan(widths: tuple[int, ...], edges: list[tuple[str, str]], *, running: str = "") -> dict:
    """A graph of frontiers ``widths`` wide, lanes named by frontier and place (``1a``, ``1b``, ``2a``), every lane of
    the first frontier dispatched by main, and ``edges`` between lanes; ``running`` names the lane that runs."""
    lanes, order = [], 0
    for at, count in enumerate(widths, 1):
        for place in "abcdefgh"[:count]:
            order += 1
            lane_id = f"{at}{place}"
            lanes.append(lane(lane_id, f"Lane {lane_id}", "quick", "glm-5.3-flash", "low",
                              "running" if lane_id == running else "done", elapsed=12, order=order))
    first = [item["id"] for item in lanes if item["id"].startswith("1")]
    return graph([root(), *lanes], [*(("root", lane_id, "dispatch") for lane_id in first),
                                    *((upper, lower, "depends_on") for upper, lower in edges)])


CONNECTOR_GLYPHS = frozenset("│─╭╮╰╯┬┴┼├┤▼╎▽|-+v:.")


def connector_roles(view) -> list[set[str]]:
    """The roles of each line drawn only of connector glyphs (a stub, bus or arrow row), top to bottom."""
    return [
        {segment.role for segment in line if segment.text.strip()} for line in view.lines
        if any(segment.text.strip() for segment in line)
        and all(set(segment.text.strip()) <= CONNECTOR_GLYPHS for segment in line if segment.text.strip())
    ]


def gaps(view) -> list[tuple[list[str], list[str], list[str]]]:
    """Each gap between two rows of boxes: the box row above's node ids, the one below's, and the connector rows
    between them (the lines every piece of which is a connector)."""
    lines = view.text_lines()
    rows: dict[int, list[str]] = {}
    bottoms: dict[int, int] = {}
    for node_id, top, bottom in view.boxes:
        rows.setdefault(top, []).append(node_id)
        bottoms[top] = bottom
    tops = sorted(rows)
    found = []
    for upper, lower in zip(tops, tops[1:]):
        between = [lines[at] for at in range(bottoms[upper] + 1, lower)
                   if lines[at].strip() and all(segment.role.startswith("connector")
                                                for segment in view.lines[at] if segment.text.strip())]
        found.append((rows[upper], rows[lower], between))
    return found


def middles(view) -> dict[str, int]:
    """The cell under each box's middle, read off its top border."""
    lines = view.text_lines()
    by_top: dict[int, list[str]] = {}
    for node_id, top, _bottom in view.boxes:
        by_top.setdefault(top, []).append(node_id)
    found = {}
    for top, node_ids in by_top.items():
        row = f" {lines[top]} "  # a cell of room each side: a corner is told by the rule on its inner side
        lefts = [at - 1 for at, char in enumerate(row) if char in "┌+" and row[at + 1] in "─-"]
        rights = [at - 1 for at, char in enumerate(row) if char in "┐+" and row[at - 1] in "─-"]
        for node_id, left, right in zip(node_ids, lefts, rights):
            found[node_id] = left + (right - left + 1) // 2
    return found


UNDRAWN = frozenset("╎:")  # the one centred connector's bar in each charset: the gap's edges are not drawn


def drawn_edges(view, upper: list[str], lower: list[str], between: list[str]) -> set[tuple[str, str]]:
    """The edges the connector rows of one gap draw, read the way a person reads them: each run of the bus joins
    every stub over it to every arrow under it, and with no bus each stub leads straight down to the arrow under
    it. The one centred connector (`UNDRAWN`) draws none. A drawn stub or arrow under no box's middle fails: it
    would point at nothing."""
    if set(between[0].strip()) <= UNDRAWN:
        return set()
    middle = middles(view)
    above = {middle[node_id]: node_id for node_id in upper}
    below = {middle[node_id]: node_id for node_id in lower}
    stubs = [at for at, char in enumerate(between[0]) if char.strip()]
    arrows = [at for at, char in enumerate(between[-1]) if char.strip()]
    stray = [cell for cell in stubs if cell not in above] + [cell for cell in arrows if cell not in below]
    if stray:
        raise AssertionError(f"a drawn connector under no box's middle at {stray}: {between!r}")
    if len(between) == 2:
        return {(above[cell], below[cell]) for cell in stubs if cell in arrows}
    runs: list[list[int]] = []
    for at, char in enumerate(between[1]):
        if char.strip():
            if runs and runs[-1][-1] == at - 1:
                runs[-1].append(at)
            else:
                runs.append([at])
    return {(above[top], below[bottom]) for run in runs for top in stubs if top in run for bottom in arrows
            if bottom in run}


def gap_edges(payload: dict, upper: list[str], lower: list[str]) -> set[tuple[str, str]]:
    return {(edge["from"], edge["to"]) for edge in payload["edges"] if edge["from"] in upper and edge["to"] in lower}


def random_layered(seed: int) -> dict:
    """A random layered graph: 2 to 4 frontiers of 1 to 5 lanes; each lane past the first frontier has a parent in
    the frontier before it, maybe more there, and now and then one further up (an edge that skips a frontier)."""
    rng = random.Random(seed)
    widths = tuple(rng.randint(1, 5) for _ in range(rng.randint(2, 4)))
    names = [[f"{at}{place}" for place in "abcde"[:count]] for at, count in enumerate(widths, 1)]
    edges = []
    for at, layer in enumerate(names[1:], 1):
        for lower in layer:
            parents = set(rng.sample(names[at - 1], rng.randint(1, len(names[at - 1]))))
            if at > 1 and rng.random() < 0.15:
                parents.add(rng.choice(names[rng.randrange(at - 1)]))
            edges += [(upper, lower) for upper in sorted(parents)]
    return fan(widths, edges)


class SnapshotTests(unittest.TestCase):
    maxDiff = None

    def test_the_export_run_at_100_columns(self) -> None:
        view = render_delegation_view(dag_export_run(), width=100)
        self.assertEqual(view.layout, "box")
        self.assertEqual(view.text() + "\n", EXPORT100)

    def test_ascii_charset(self) -> None:
        drawn = text(dag_export_run(), width=80, charset="ascii")
        self.assertEqual(drawn + "\n", EXPORT80ASCII)
        self.assertTrue(drawn.isascii(), "the ASCII charset draws nothing else when the titles are ASCII")

    def test_a_narrow_terminal_gets_the_tree(self) -> None:
        self.assertEqual(render_delegation_view(nested(), width=BOX_MIN_WIDTH - 1).layout, "tree")
        view = render_delegation_view(nested(), width=34, layout="tree")
        self.assertEqual(view.text() + "\n", NESTED34TREE)

    def test_a_budget_gives_up_node_details_then_dependencies_then_the_boxes(self) -> None:
        whole = render_delegation_view(owner_mock(), width=40)
        self.assertEqual((whole.layout, bool(section(whole, "Node details"))), ("box", True))
        view = render_delegation_view(owner_mock(), **BUDGET)
        self.assertEqual(view.layout, "box")
        self.assertEqual(section(view, "Node details"), [], "Node details go first")
        self.assertEqual(len(section(view, "Dependencies")), 3, "the edges stay while they fit")
        tighter = render_delegation_view(owner_mock(), width=40, max_lines=len(view.lines) - 1)
        self.assertEqual((tighter.layout, section(tighter, "Dependencies")), ("box", []))
        self.assertIn("← Refresh HUD docs, Poli…", tighter.text(), "each box still names its parents")
        view = render_delegation_view(nested(), **BUDGET)
        self.assertEqual((view.layout, view.text() + "\n"), ("tree", NESTED40BUDGET))

    def test_a_character_cap_discloses_what_it_left_out(self) -> None:
        view = render_delegation_view(parallel(60), width=40, max_chars=1782, max_lines=42)
        lines = view.text_lines()
        self.assertEqual(view.layout, "tree")
        self.assertLessEqual(len(view.text()), 1782)
        self.assertLessEqual(len(lines), 42)
        self.assertEqual(lines[-1], f"└─ +{view.hidden_nodes} more nodes")
        self.assertGreater(view.hidden_nodes, 0)
        shown = sum(1 for line in lines if " Lane " in line)
        self.assertEqual(shown + view.hidden_nodes, 60, "every lane is either drawn or counted")


class BoxTests(unittest.TestCase):
    def test_each_box_holds_its_title_facts_status_and_parents(self) -> None:
        boxes = box_lines(render_delegation_view(dag_export_run(), width=120))
        self.assertEqual(boxes["d:r1:api"], ["Export API", "quick · glm-5.3-flash:low", "✓ Accepted 12s", "Start node"])
        self.assertEqual(boxes[BUTTON], ["Export button", "unspecified-high · glm-5.3:low", "● Running 21s",
                                         "← Export API"])
        self.assertEqual(boxes[DOCS], ["Export docs", "writing", "◌ Handed out", "← Export API"],
                         "a model no child has reported yet is left out, never `?`")
        self.assertEqual(boxes[CLI], ["Export CLI flag", "quick · glm-5.3-flash:low", "✗ Failed 8s", "← Export API"])
        self.assertEqual(boxes["d:r1:verify"],
                         ["Verify export", "unspecified-high", "○ Waits on 3 lanes", "← Export button, Export docs,…"])
        self.assertNotIn("main", " ".join(" ".join(lines) for lines in boxes.values()), "the root is not a box")

    def test_a_node_added_mid_run_says_where_it_came_from(self) -> None:
        boxes = box_lines(render_delegation_view(dag_export_repair_run(), width=100))
        self.assertEqual(boxes["d:r1:csv"][0], "+ CSV export", "an extend")
        self.assertEqual(boxes["d:r1:csv-fix"][0], "↻ CSV export … header row", "a repair")
        self.assertEqual(boxes["d:r1:verify"][0], "Verify export")
        ascii_boxes = box_lines(render_delegation_view(dag_export_repair_run(), width=100, charset="ascii"))
        self.assertEqual((ascii_boxes["d:r1:csv"][0], ascii_boxes["d:r1:csv-fix"][0][:4]), ("+ CSV export", "~ CS"))

    def test_a_repair_stands_above_the_nodes_that_wait_on_what_it_repairs(self) -> None:
        fix, verify = "d:r1:button-fix", "d:r1:verify"
        for width in (60, 100, 120):
            view = render_delegation_view(dag_export_button_repair_run(), width=width)
            rows = {node_id: (top, bottom) for node_id, top, bottom in view.boxes}
            with self.subTest(width=width):
                self.assertEqual(view.layout, "box")
                self.assertLess(rows[BUTTON][1], rows[fix][0], "below the node it repairs")
                self.assertLess(rows[fix][1], rows[verify][0], "above the check that waits on that node, which it "
                                                               "runs before; never on the check's frontier")
        boxes = box_lines(render_delegation_view(dag_export_button_repair_run(), width=120))
        self.assertEqual(boxes[verify][3], "← Export button, Export docs,…", "parents stay the recorded edges")
        self.assertEqual(boxes[fix][3], "← Export API, Export button")
        # An extend round the check found missing, built on the repair, is not part of the repair: it stays below the
        # check that found it.
        later = dag_export_button_repair_run()
        later["nodes"].append(lane("d:r1:csv", "CSV export", "quick", "glm-5.3-flash", "low", "running", elapsed=4,
                                   order=7, group="extend 1"))
        later["edges"] += [{"from": fix, "to": "d:r1:csv", "kind": "depends_on"},
                           {"from": verify, "to": "d:r1:csv", "kind": "extend"}]
        order = [node_id for node_id, _top, _bottom in render_delegation_view(later, width=120).boxes]
        self.assertLess(order.index(fix), order.index(verify))
        self.assertLess(order.index(verify), order.index("d:r1:csv"))
        # A repair of two nodes, one on the other: the check waits on both.
        two = dag_export_button_repair_run()
        two["nodes"].append(lane("d:r1:button-check", "Check the button", "quick", "glm-5.3-flash", "low", "waiting",
                                 order=7, group="layer 3"))
        two["edges"].append({"from": fix, "to": "d:r1:button-check", "kind": "depends_on"})
        rows = {node_id: (top, bottom) for node_id, top, bottom in render_delegation_view(two, width=120).boxes}
        self.assertLess(rows[fix][1], rows["d:r1:button-check"][0])
        self.assertLess(rows["d:r1:button-check"][1], rows[verify][0])
        # An extend round the repaired node's own check added came after its repair too.
        found = dag_export_button_repair_run()
        found["nodes"].append(lane("d:r1:key", "Export key rotation", "quick", "glm-5.3-flash", "low", "waiting",
                                   order=7, group="extend 1"))
        found["edges"].append({"from": BUTTON, "to": "d:r1:key", "kind": "extend"})
        view = render_delegation_view(found, width=120)
        rows = {node_id: (top, bottom) for node_id, top, bottom in view.boxes}
        self.assertLess(rows[fix][1], rows["d:r1:key"][0])
        self.assertIn("  Export button → Export key rotation (extend)", section(view, "Dependencies"))

    def test_what_a_repaired_lane_dispatched_keeps_its_place(self) -> None:
        # The button's own child delegated during the attempt that failed: that grandchild ran before the repair, so
        # it stays on the frontier under the button, beside the repair, and only the check waits below it.
        fix, verify = "d:r1:button-fix", "d:r1:verify"
        run = dag_export_button_repair_run()
        run["nodes"].append({**lane("s:sa-spec", "Read the button spec", "quick", "glm-5.3-flash", "low", "done",
                                    elapsed=4, order=7), "session_tail": "a1b2c3d4"})
        run["edges"].append({"from": BUTTON, "to": "s:sa-spec", "kind": "dispatch"})
        rows = {node_id: (top, bottom) for node_id, top, bottom in render_delegation_view(run, width=120).boxes}
        self.assertEqual(rows["s:sa-spec"][0], rows[fix][0])
        self.assertLess(rows[fix][1], rows[verify][0])

    def test_an_extend_round_built_on_the_repair_is_not_part_of_it(self) -> None:
        # An extend node whose finder is among its parents gets no extend edge (`_origin_parent`); its `dag_origin`
        # still says an extend round added it, so it never joins the repair it depends on.
        fix, verify = "d:r1:button-fix", "d:r1:verify"

        def extended(finder: str) -> dict:
            run = dag_export_button_repair_run()
            run["nodes"].append({**lane("d:r1:csv", "CSV export", "quick", "glm-5.3-flash", "low", "running",
                                        elapsed=4, order=7, group="extend 1"), "dag_origin": "extend:1"})
            run["edges"] += [{"from": finder, "to": "d:r1:csv", "kind": "depends_on"},
                             {"from": fix, "to": "d:r1:csv", "kind": "depends_on"}]
            return {node_id: (top, bottom) for node_id, top, bottom in render_delegation_view(run, width=120).boxes}

        rows = extended(verify)  # found by the check: the repair's order is kept, not dropped as a loop
        self.assertLess(rows[fix][1], rows[verify][0])
        self.assertLess(rows[verify][1], rows["d:r1:csv"][0])
        rows = extended(BUTTON)  # found by the repaired node: the check is not drawn below the extend
        self.assertLess(rows[fix][1], rows[verify][0])
        self.assertEqual(rows[verify][0], rows["d:r1:csv"][0])

    def test_a_repair_order_that_would_loop_is_dropped_and_the_recorded_edges_place_the_lanes(self) -> None:
        # The repair depends on the lane that waits on what it repairs: placing the repair above that lane would loop.
        looped = graph(
            [root(), lane("x", "Export button", "quick", "glm-5.3", "low", "failed", elapsed=8, order=1),
             lane("d", "Verify export", "deep", "glm-5.3", "low", "waiting", order=2, waits=1),
             lane("r", "Fix the button", "quick", "glm-5.3", "low", "running", elapsed=5, order=3)],
            [("root", "x", "dispatch"), ("x", "d", "depends_on"), ("x", "r", "repair"), ("d", "r", "depends_on")],
        )
        view = render_delegation_view(looped, width=100)
        self.assertEqual(view.layout, "box")
        self.assertEqual([node_id for node_id, _top, _bottom in view.boxes], ["x", "d", "r"])

    def test_a_duration_past_100_hours_stays_whole_and_widens_the_box_by_a_cell(self) -> None:
        def drawn(seconds: int):
            fix = graph([root(), lane("f", "Fix", "", "", "", "failed", elapsed=seconds, status="failed: timeout")],
                        [("root", "f", "dispatch")])
            return render_delegation_view(fix, width=100)

        widths = {}
        for seconds, status in ((3_599, "59m 59s"), (99 * 3600 + 59 * 60, "99h 59m"), (100 * 3600, "100h 00m"),
                                (400_000, "111h 06m")):
            view = drawn(seconds)
            with self.subTest(seconds=seconds):
                self.assertEqual(box_lines(view)["f"][2], f"✗ Failed: timeout {status}")
            widths[seconds] = box_inner(view)
        self.assertEqual(widths[3_599], widths[99 * 3600 + 59 * 60], "a ticking clock under 100 hours resizes nothing")
        self.assertEqual(widths[100 * 3600], {inner + 1 for inner in widths[3_599]}, "one cell wider at 100 hours")
        self.assertEqual(widths[400_000], widths[100 * 3600])
        stuck = graph([root(), lane("s", "Fix", "", "", "", "stuck", elapsed=400_000, status="stuck: same error")],
                      [("root", "s", "dispatch")])
        self.assertEqual(box_lines(render_delegation_view(stuck, width=100))["s"][2], "! Stuck 111h 06m: same error",
                         "a stuck lane's duration is measured as it reads too")

    def test_the_header_names_the_run_its_size_and_its_state(self) -> None:
        lines = text(dag_export_run(), width=100).splitlines()[:3]
        self.assertEqual(lines, ["OMH / DAG · 5 tasks", "export feature · 1/1 · main opus-5-5:high",
                                 "Running · Done 1/5 · 1 failed"])
        self.assertEqual(text(dag_export_repair_run(), width=100).splitlines()[2], "Running · Done 5/7 · 1 failed")
        settled = dag_export_run()
        for node in settled["nodes"][1:]:
            node["state"] = "done"
        self.assertEqual(text(settled, width=100).splitlines()[2], "Completed · Done 5/5")
        settled["nodes"][2]["state"] = "failed"
        self.assertEqual(text(settled, width=100).splitlines()[2], "Failed · Done 4/5 · 1 failed")
        cut = {**dag_export_run(), "hidden_nodes": 3}
        self.assertEqual(text(cut, width=100).splitlines()[:3:2],
                         ["OMH / DAG · 8 tasks", "Running · Done 1/5 · 1 failed · +3 more nodes"])
        fanout = graph([root(model="", effort=""), lane("u", "Core", "codex", "?", "", "running")],
                       [("root", "u", "dispatch")], name="fanout fanout-0123456789ab", source="fanout")
        self.assertEqual(text(fanout, width=80).splitlines()[1], "fanout fanout-0123456789ab · 1/1",
                         "a root that names no model adds nothing")

    def test_the_header_counts_the_runs_lanes_and_the_edges_between_them_with_separators(self) -> None:
        from omh.plugin_bundle.omh.delegation_view import header_text

        # main is the drawing's root, not a node of the run, and its dispatch edges are not the run's edges.
        self.assertEqual(header_text(dag_export_run()),
                         "DAG · export feature · 5 nodes · 6 edges · 1 running · 1 failed · 1 dispatched · 1 waiting · "
                         "1 done")
        wide = {**parallel(1200), "hidden_nodes": 1500}
        self.assertEqual(header_text(wide), "DAG · delegation · 1,200 nodes · 0 edges · 1,200 running · "
                                            "+1,500 more nodes")

    def test_frontiers_sit_side_by_side_and_say_so(self) -> None:
        view = render_delegation_view(dag_export_run(), width=120)
        rows = {node_id: (top, bottom) for node_id, top, bottom in view.boxes}
        self.assertEqual(len({rows[node_id] for node_id in (BUTTON, DOCS, CLI)}), 1, "one row")
        self.assertLess(rows["d:r1:api"][1], rows[BUTTON][0])
        self.assertLess(rows[BUTTON][1], rows["d:r1:verify"][0])
        labels = [at for at, line in enumerate(view.text_lines()) if line.strip() == "· Same frontier"]
        self.assertEqual(labels, [rows[BUTTON][1] + 1], "one label, under the frontier of three, none under a lone box")

    def test_a_frontier_too_wide_wraps_and_keeps_its_label(self) -> None:
        view = render_delegation_view(dag_export_run(), width=80)
        rows = {node_id: (top, bottom) for node_id, top, bottom in view.boxes}
        self.assertEqual(rows[BUTTON], rows[DOCS])
        self.assertEqual(rows[CLI][0], rows[BUTTON][1] + 1, "the third box wraps to the next row")
        lines = view.text_lines()
        self.assertEqual(lines[rows[CLI][1] + 1], "· Same frontier", "the label stays under the frontier")
        self.assertEqual(lines[rows[CLI][0]].index("┌"), lines[rows[BUTTON][0]].index("┌"),
                         "a wrapped row starts where the first one does")

    def test_the_edges_between_two_frontiers_are_drawn(self) -> None:
        # 1 -> 5 -> 2 -> 1: a fan-out, two fan-ins that share no parent, and a fan-in of two.
        payload = fan((1, 5, 2, 1), [("1a", f"2{place}") for place in "abcde"] + [(f"2{place}", "3a") for place in "abc"]
                      + [("2d", "3b"), ("2e", "3b"), ("3a", "4a"), ("3b", "4a")], running="3a")
        view = render_delegation_view(payload, width=150)
        self.assertEqual(view.layout, "box")
        rows = [between for _upper, _lower, between in gaps(view)]
        self.assertEqual([[line.rstrip() for line in between] for between in rows], [
            [" " * 74 + "│",
             " " * 14 + "╭" + "─" * 29 + "┬" + "─" * 29 + "┼" + "─" * 29 + "┬" + "─" * 29 + "╮",
             " " * 14 + ("▼" + " " * 29) * 4 + "▼"],
            [(" " * 14 + ("│" + " " * 29) * 4 + "│"),
             " " * 14 + "╰" + "─" * 29 + "┴" + "─" * 14 + "┬" + "─" * 14 + "╯" + " " * 14 + "╭" + "─" * 14 + "┴"
             + "─" * 29 + "╯",
             " " * 59 + "▼" + " " * 29 + "▼"],
            [" " * 59 + "│" + " " * 29 + "│",
             " " * 59 + "╰" + "─" * 14 + "┬" + "─" * 14 + "╯",
             " " * 74 + "▼"],
        ])
        for upper, lower, between in gaps(view):
            self.assertEqual(drawn_edges(view, upper, lower, between),
                             {(edge["from"], edge["to"]) for edge in payload["edges"]
                              if edge["from"] in upper and edge["to"] in lower})

    def test_the_drawn_edges_are_the_graph_edges_exactly(self) -> None:
        """Reading a gap's stubs, buses and arrows back gives the gap's edges, none missing and none that two groups
        sharing a bus would imply; the one centred connector draws none."""
        straight = fan((2, 2), [("1a", "2a"), ("1b", "2b")])
        disjoint = fan((4, 2), [("1a", "2a"), ("1b", "2a"), ("1c", "2b"), ("1d", "2b")])
        cases = (dag_export_run(), dag_export_repair_run(), dag_export_button_repair_run(), nested(), owner_mock(),
                 straight, disjoint, fan((1, 3, 1), [("1a", "2a"), ("1a", "2b"), ("1a", "2c"), ("2a", "3a"),
                                                     ("2b", "3a"), ("2c", "3a")]))
        drawn = 0
        for case in cases:
            for width in (60, 100, 150):
                for charset in ("unicode", "ascii"):
                    view = render_delegation_view(case, width=width, charset=charset)
                    for upper, lower, between in gaps(view):
                        if not between or set(between[0].strip()) <= UNDRAWN:
                            continue  # rows of one wrapped frontier, or the one centred connector
                        with self.subTest(name=case["name"], width=width, charset=charset, gap=(upper, lower)):
                            self.assertEqual(drawn_edges(view, upper, lower, between), gap_edges(case, upper, lower))
                            drawn += 1
        self.assertGreater(drawn, 10, "the cases draw edges, not only the one connector")
        for upper, lower, between in gaps(render_delegation_view(straight, width=100)):
            self.assertEqual(len(between), 2, "edges that all go straight down draw no bus")
            self.assertEqual(drawn_edges(render_delegation_view(straight, width=100), upper, lower, between),
                             {("1a", "2a"), ("1b", "2b")})
        bus = gaps(render_delegation_view(disjoint, width=150))[0][2][1]
        self.assertEqual(len(bus.split()), 2, f"two groups that share no edge share no bus: {bus!r}")

    def test_no_drawn_connector_implies_an_edge_the_graph_lacks(self) -> None:
        """Over random layered graphs at three widths in both charsets, every gap reads back as exactly its edges
        where it draws them and as none where it does not; never as an edge that is absent (the one centred
        connector once sat over the middle boxes of two odd frontiers and read as their edge)."""
        gaps_read = undrawn = 0
        for seed in range(150):
            payload = random_layered(seed)
            for width in (60, 100, 150):
                for charset in ("unicode", "ascii"):
                    view = render_delegation_view(payload, width=width, charset=charset)
                    for upper, lower, between in gaps(view):
                        if not between:
                            continue  # two rows of one wrapped frontier
                        with self.subTest(seed=seed, width=width, charset=charset, gap=(upper, lower)):
                            read, actual = drawn_edges(view, upper, lower, between), gap_edges(payload, upper, lower)
                            self.assertLessEqual(read, actual, "a connector that implies an absent edge")
                            if set(between[0].strip()) <= UNDRAWN:
                                undrawn += 1
                                self.assertEqual([len(line.strip()) for line in between], [1, 1])
                            else:
                                self.assertEqual(read, actual, "a drawn gap draws every edge it holds")
                            gaps_read += 1
        self.assertGreater(gaps_read, 500)
        self.assertGreater(undrawn, 50, "the random graphs reach the one centred connector too")
        # The reviewer's case: 1b has no edge, and the centred column is its middle and 2b's.
        odd = render_delegation_view(fan((3, 3), [("1a", "2a"), ("1a", "2b"), ("1c", "2b"), ("1c", "2c")]),
                                     width=120)
        self.assertEqual([[line.strip() for line in between] for _upper, _lower, between in gaps(odd)],
                         [["╎", "▽"]])

    def test_a_gap_whose_edges_cannot_be_drawn_exactly_gets_the_one_connector(self) -> None:
        cases = {
            # 1a leads to 2a and 2b, 1b only to 2b: one bus would say 1b -> 2a.
            "a group not every parent to every child": fan((2, 2), [("1a", "2a"), ("1a", "2b"), ("1b", "2b")]),
            # 1b's group sits inside the span of {1a, 1c} -> 2a: the two buses would share cells.
            "two groups whose buses overlap": fan((3, 2), [("1a", "2a"), ("1c", "2a"), ("1b", "2b")]),
            # 1a -> 3a skips frontier 2: no drawing of the gaps it crosses could show it.
            "an edge that skips a frontier": fan((1, 2, 1), [("1a", "2a"), ("1a", "2b"), ("2a", "3a"), ("2b", "3a"),
                                                             ("1a", "3a")]),
        }
        for name, case in cases.items():
            for width in (100, 150):
                view = render_delegation_view(case, width=width)
                with self.subTest(name, width=width):
                    self.assertEqual(view.layout, "box")
                    for _upper, _lower, between in gaps(view):
                        self.assertEqual([line.strip() for line in between], ["╎", "▽"])
                        self.assertEqual(between[0].index("╎"), between[1].index("▽"), "one centred connector")
                    text_drawn = view.text()
                    self.assertFalse(set(text_drawn) & set("╭╮╰╯┼"), "no bus is drawn")
        # A frontier that wraps has no one row to draw edges to: the gaps on either side of it take the connector.
        wrapped = render_delegation_view(dag_export_run(), width=80)
        self.assertEqual([[line.strip() for line in between] for _upper, _lower, between in gaps(wrapped)
                          if between], [["╎", "▽"], ["╎", "▽"]])
        one_row = render_delegation_view(dag_export_run(), width=120)
        self.assertEqual(len(gaps(one_row)[0][2]), 3, "the same run on one row draws its edges")

    def test_dependencies_are_the_graph_edges_exactly(self) -> None:
        for case in (dag_export_run(), dag_export_repair_run(), dag_export_button_repair_run(), nested(), owner_mock()):
            view = render_delegation_view(case, width=120)
            drawn = set()
            for line in section(view, "Dependencies"):
                found = re.fullmatch(r"  (.+?) → (.+?)(?: \((\w+)\))?", line)
                self.assertIsNotNone(found, line)
                drawn.add((found[1], found[2], found[3] or "depends_on"))
            with self.subTest(name=case["name"], nodes=len(case["nodes"])):
                self.assertEqual(drawn, lane_edges(case))
                self.assertEqual(len(section(view, "Dependencies")), len(lane_edges(case)), "each edge once")
        later = text(dag_export_repair_run(), width=120).splitlines()
        self.assertIn("  Verify export → CSV export (extend)", later)
        self.assertIn("  CSV export → CSV export, with the header row (repair)", later)
        self.assertNotIn("Dependencies", text(parallel(3), width=120), "a fan-out from main has none to list")

    def test_node_details_only_for_running_or_highlighted_nodes(self) -> None:
        self.assertEqual(cards(render_delegation_view(dag_export_run(), width=100)), ["Export button"])
        self.assertEqual(cards(render_delegation_view(dag_export_run(), width=100, focus=Focus(node=CLI))),
                         ["Export button", "Export CLI flag"])
        self.assertEqual(cards(render_delegation_view(dag_export_run(), width=100, focus=Focus(node=BUTTON))),
                         ["Export button"], "a running node highlighted has one card")
        hidden = render_delegation_view(dag_export_run(), width=100, focus=Focus(node=CLI, details=False))
        self.assertNotIn("Node details", hidden.text_lines())
        stuck = dag_export_run()
        stuck["nodes"][2].update(state="stuck", status="stuck: same error", elapsed_seconds=400)
        self.assertEqual(cards(render_delegation_view(stuck, width=100)), ["Export button"])
        self.assertIn("    Stuck 6m 40s: same error · layer 2 · session 7c41e9a2", text(stuck, width=100).splitlines())
        settled = dag_export_repair_run()
        settled["nodes"][-1]["state"] = "done"
        self.assertNotIn("Node details", text(settled, width=100), "nothing runs: no card")

    def test_a_card_holds_the_whole_title(self) -> None:
        long = dag_export_run()
        long["nodes"][2]["title"] = "Export button with a confirmation dialog and a keyboard shortcut"
        view = render_delegation_view(long, width=60)
        # The box grows toward its title (`BOX_INNER_MAX`), and a title still too long is cut in its middle, at word
        # boundaries, so its end, which tells two titles apart, stays.
        self.assertEqual(box_lines(view)[BUTTON][0], "Export button with a … and a keyboard shortcut")
        self.assertEqual(section(view, "Node details")[:2],
                         ["  ● Export button with a confirmation dialog and a keyboard", "    shortcut"])

    def test_the_width_falls_back_to_wrapping_then_cut_labels_then_the_tree(self) -> None:
        def per_row(view) -> int:
            tops = [top for node_id, top, _bottom in view.boxes if node_id in (BUTTON, DOCS, CLI)]
            return max(tops.count(top) for top in tops)

        # A frontier goes on one row while its boxes can narrow to it (82 columns for three); past that it wraps.
        for width, expected, facts in ((140, 3, "unspecified-high · glm-5.3:low"), (106, 3, "unspecified-high · glm-5.3:low"),
                                       (100, 3, "unspecified-high · glm-5.3:…"), (82, 3, "unspecified-high · gl…"),
                                       (81, 2, "unspecified-high · glm-5.3:low"), (60, 1, "unspecified-high · glm-5.3:low"),
                                       (34, 1, "unspecified-high · glm-5.3:low")):
            view = render_delegation_view(dag_export_run(), width=width)
            with self.subTest(width=width):
                self.assertEqual((view.layout, per_row(view)), ("box", expected))
                self.assertEqual(box_lines(view)[BUTTON][1], facts, "the category and model line is what is cut")
                self.assertEqual([lines[0] for lines in box_lines(view).values()],
                                 ["Export API", "Export button", "Export docs", "Export CLI flag", "Verify export"])
        for width, facts in ((30, "unspecified-high · glm-5.…"), (BOX_MIN_WIDTH, "unspecified-high · gl…")):
            view = render_delegation_view(dag_export_run(), width=width)
            with self.subTest(width=width):
                self.assertEqual(view.layout, "box")
                self.assertEqual(box_lines(view)[BUTTON][1], facts)
                self.assertTrue(all(cells(line) <= width for line in view.text_lines()))
        self.assertEqual(render_delegation_view(dag_export_run(), width=BOX_MIN_WIDTH - 1).layout, "tree")

    def test_dag_draws_fold_markers_and_the_highlight(self) -> None:
        static = render_delegation_view(dag_export_run(), width=100)
        self.assertNotIn("[-]", static.text(), "no key acts on the transcript's drawing")
        view = render_delegation_view(dag_export_run(), width=100, focus=Focus(node=CLI, folded=frozenset({"d:r1:api"})))
        boxes = box_lines(view)
        self.assertEqual(boxes["d:r1:api"], ["[+] ✓ Export API · Accepted"],
                         "a folded box is one line, and keeps its glyph and its status word")
        self.assertEqual(boxes[CLI][0], "[-] > Export CLI flag")
        self.assertEqual(boxes[BUTTON][0], "[-] Export button")
        borders = {node_id: {role for _text, role in box_spans(view, node_id)[0]} for node_id, _top, _bottom in view.boxes}
        self.assertEqual(borders, {"d:r1:api": {"node:done"}, BUTTON: {"node:running"}, DOCS: {"node:dispatched"},
                                   CLI: {"node:selected"}, "d:r1:verify": {"node:waiting"}})
        self.assertEqual([node_id for node_id, _top, _bottom in view.boxes],
                         ["d:r1:api", BUTTON, DOCS, CLI, "d:r1:verify"], "reading order")


class TreeTests(unittest.TestCase):
    maxDiff = None

    def test_a_cut_tree_closes_its_branches_and_counts_the_cut_where_it_was_made(self) -> None:
        for budget, snapshot in ((8, EXPORT_TREE_CUT_8), (6, EXPORT_TREE_CUT_6)):
            view = render_delegation_view(dag_export_run(), width=120, layout="tree", max_lines=budget)
            with self.subTest(budget=budget):
                self.assertEqual(view.text() + "\n", snapshot, "whole layers were cut: the count is at the root")
                self.assertEqual(branch_problems(view.text()), [])
        wide = graph(
            [root(), lane("a", "Schema", "deep", "claude-opus-5-5", "high", "running", elapsed=30, group="layer 1",
                          order=1),
             *(lane(f"b{index}", f"Migrate table {index}", "quick", "glm-5.3-flash", "low", "waiting",
                    group="layer 2", order=2 + index) for index in range(5))],
            [("root", "a", "dispatch"), *(("a", f"b{index}", "depends_on") for index in range(5))],
        )
        view = render_delegation_view(wide, width=100, layout="tree", max_lines=7)
        self.assertEqual(view.text() + "\n", LAYER_CUT_7, "only the last layer was cut: the count is under it")
        segments = [segment for line in view.lines for segment in line]
        self.assertEqual([segment.role for segment in segments if "more" in segment.text], ["more"])

    def test_every_cut_tree_is_well_formed(self) -> None:
        generator = random.Random(2026_10_21)
        for trial in range(80):
            nodes, edges = [root()], []
            for index in range(generator.randint(2, 12)):
                parent = generator.choice(["root"] + [node["id"] for node in nodes[1:]])
                nodes.append(lane(f"n{index}", f"Task {index}", "quick", "glm-5.3-flash", "",
                                  generator.choice(["running", "done", "failed", "waiting"]), order=index,
                                  group=generator.choice(["", "wave 1 · 14:02", "wave 2 · 14:09", "layer 3"])))
                edges.append((parent, f"n{index}", "dispatch"))
            case = graph(nodes, edges)
            for width in (34, 100):
                for budget in (4, 6, 9):
                    view = render_delegation_view(case, width=width, layout="tree", max_lines=budget)
                    with self.subTest(trial=trial, width=width, budget=budget):
                        self.assertEqual(branch_problems(view.text()), [], view.text())

    def test_a_field_not_recorded_yet_is_blank_in_the_tree(self) -> None:
        drawn = text(dag_export_run(), width=120, layout="tree").splitlines()
        docs = next(row for row in drawn if "Export docs" in row)
        self.assertEqual(docs.split()[-3:], ["writing", "handed", "out"], "no `?` where the model is not known yet")
        self.assertNotIn("?", text(dag_export_run(), width=120, layout="tree"))
        narrow = text(dag_export_run(), width=60, layout="tree")
        self.assertIn("writing · handed out", narrow)
        self.assertIn("unspecified-high · waits on 3 lanes", narrow)
        bare = graph([root(model="", effort=""), {"id": "x", "kind": "lane", "state": "dispatched"}],
                     [("root", "x", "dispatch")])
        self.assertIn("? · dispatched", text(bare, width=60, layout="tree"), "one `?` where neither is known")
        self.assertEqual(text(bare, width=100, layout="tree").count("?"), 1, "the category column's; a title has none")

    def test_the_category_column_holds_the_longest_category_and_the_model_gives_way(self) -> None:
        for width in (120, 74, 72):
            rows = text(dag_export_run(), width=width, layout="tree").splitlines()
            button = next(row for row in rows if "Export button" in row)
            with self.subTest(width=width):
                self.assertIn(" unspecified-high ", button, "never cut to `unspecified…`")
                self.assertTrue(all(cells(row) <= width for row in rows))
        tight = next(row for row in text(dag_export_run(), width=72, layout="tree").splitlines() if "Export API" in row)
        self.assertIn("quick             glm-5.3-flas…  accepted 12s", tight, "the model is cut, not the category")

    def test_a_duration_past_100_hours_keeps_its_room_in_the_tree(self) -> None:
        def lone(index: int, title: str, state: str, status: str, elapsed, category: str = "quick") -> dict:
            return lane(f"n{index}", title, category, "glm-5.3-flash", "low", state, elapsed=elapsed, order=index,
                        status=status)

        # The category column's widening and the spare cells a nested repair's title takes back both measure the
        # status as it reads, so `111h 06m` is never the cell they take.
        wide = graph([root(), lone(1, "Verify the whole feature end to end", "running", "running", 400_000,
                                   "unspecified-high"),
                      lone(2, "Export docs", "waiting", "waiting", None, "writing")],
                     [("root", "n1", "dispatch"), ("root", "n2", "dispatch")])
        row = text(wide, width=91, layout="tree").splitlines()[2]
        self.assertTrue(row.endswith("unspecified-high  glm-5.3-flas…  running 111h 06m"), row)
        nested_repair = graph([root(), lone(1, "Fix", "running", "running", 400_000),
                               lone(2, "Export button, with the key and the long header row", "dispatched",
                                    "handed out", None)],
                              [("root", "n1", "dispatch"), ("n1", "n2", "repair")])
        rows = text(nested_repair, width=89, layout="tree").splitlines()
        self.assertTrue(rows[2].endswith("running 111h 06m"), rows[2])
        self.assertTrue(all(cells(line) <= 89 for line in rows))

    def test_the_widened_category_never_takes_a_statuss_room(self) -> None:
        """The cells a long category takes come from room no status needs, then the model, then the title: a
        status main drew whole stays whole, and one main cut is cut no further."""
        late = dag_export_repair_run()
        late["nodes"][2]["elapsed_seconds"] = 3_725
        button = next(row for row in text(late, width=90, layout="tree").splitlines() if "Export button" in row)
        self.assertTrue(button.endswith("unspecified-high  glm-5.3:low    accepted 1h 02m"), button)
        verify = next(row for row in text(dag_export_run(), width=72, layout="tree").splitlines() if "Verify export" in row)
        self.assertTrue(verify.endswith("waits on 3 la…"), f"cut where main cut it, no further: {verify!r}")
        self.assertTrue(next(row for row in text(dag_export_run(), width=74, layout="tree").splitlines()
                             if "Verify export" in row).endswith("waits on 3 lanes"))

    def test_the_model_gives_way_down_to_its_floor_and_then_the_title(self) -> None:
        wide = graph([root(), lane("v", "Render the landing page hero", "visual-engineering", "glm-5.3-flash", "",
                                   "running", elapsed=5)], [("root", "v", "dispatch")])
        row = next(line for line in text(wide, width=72, layout="tree").splitlines() if "Render" in line)
        self.assertEqual(row, "└─ ● Render the landing pag…  visual-engineering  glm-5.3…  running 5s",
                         "the model keeps TREE_MODEL_MIN (8) cells; the title gives the rest")

    def test_the_hidden_count_says_what_the_reader_left_out_not_the_outside_lanes(self) -> None:
        """Mutation: subtract the drawn outside lanes from `hidden_nodes`, which erased genuinely hidden run lanes."""
        payload = graph(
            [root(),
             lane("a", "Export API", "quick", "glm-5.3-flash", "low", "running", elapsed=30, group="layer 1", order=1),
             lane("v", "Verify", "inherit", "?", "", "waiting", order=2, group="layer 2", waits=2)],
            [("root", "a", "dispatch"), ("a", "v", "depends_on")],
            source="dag",
        )
        payload["nodes"] += [
            {"id": "s:sa-free", "kind": "lane", "title": "Fix the typo", "category": "?", "model": "glm-5.3-flash",
             "effort": "low", "state": "done", "status": "done", "elapsed_seconds": None, "order": 3,
             "group": "wave 2 · 14:02", "waits_on": 0},
            {"id": "s:sa-leaf", "kind": "lane", "title": "Sweep the cache", "category": "quick",
             "model": "glm-5.3-flash", "effort": "low", "state": "done", "status": "done", "elapsed_seconds": None,
             "order": 4, "group": "wave 2 · 14:02", "waits_on": 0},
        ]
        for node in payload["nodes"][-2:]:
            node["outside_dag"] = True
        # The reader's own bounds: three run lanes it left out, named beside the two outside lanes it drew.
        payload["hidden_nodes"] = 3
        payload["hidden_by_state"] = {"waiting": 3}
        payload["layer_hidden"] = [{"layer": 2, "count": 3, "states": {"waiting": 3}}]
        drawn = text(payload, width=100, layout="tree")
        self.assertIn("+3 more nodes", drawn)
        self.assertNotIn("+1 more nodes", drawn)
        self.assertNotIn("+2 more nodes", drawn, "the drawn outside lanes are no part of the omitted count")
        self.assertIn("outside DAG", drawn)
        self.assertIn("Fix the typo", drawn)

    def test_a_cut_that_hides_only_nested_children_of_the_last_group_is_counted_under_it(self) -> None:
        nested_cut = graph(
            [root(),
             lane("x", "Schema", "deep", "claude-opus-5-5", "high", "running", elapsed=30, group="layer 1", order=1),
             lane("y", "Migrate", "quick", "glm-5.3-flash", "low", "running", elapsed=20, group="layer 2", order=2),
             lane("y1", "Table one", "quick", "glm-5.3-flash", "low", "waiting", order=3),
             lane("y2", "Table two", "quick", "glm-5.3-flash", "low", "waiting", order=4)],
            [("root", "x", "dispatch"), ("root", "y", "dispatch"), ("y", "y1", "dispatch"), ("y", "y2", "dispatch")],
        )
        lines = text(nested_cut, width=100, layout="tree", max_lines=7).splitlines()
        self.assertEqual(lines[-3:], ["└─ layer 2", "   ├─ ● Migrate   quick  glm-5.3-flash:low  running 20s",
                                      "   └─ +2 more nodes"], "the hidden children sit under layer 2")

    def test_a_known_model_with_no_category_record_shows_no_question_mark(self) -> None:
        unrouted = graph([root(), lane("a", "Port it", "?", "glm-5.3-flash", "low", "running", elapsed=5)],
                         [("root", "a", "dispatch")])
        self.assertEqual(text(unrouted, width=100, layout="tree").splitlines()[-1],
                         "└─ ● Port it     glm-5.3-flash:low  running 5s", "the category column is blank")
        self.assertIn("     glm-5.3-flash:low · running 5s", text(unrouted, width=50, layout="tree"))
        self.assertEqual(box_lines(render_delegation_view(unrouted, width=80))["a"][1], "glm-5.3-flash:low")


class ReviewTests(unittest.TestCase):
    """What the #2191 review measured: cut lines, `?`, the hud probe, folded words, the run word, and survivors."""

    def test_a_narrow_dependency_line_keeps_its_kind_and_cuts_its_titles(self) -> None:
        for charset, arrow, ellipsis in (("unicode", "→", "…"), ("ascii", "->", "...")):
            for width in (50, 40, 30):
                view = render_delegation_view(dag_export_repair_run(), width=width, charset=charset)
                lines = section(view, "Dependencies")
                with self.subTest(charset=charset, width=width):
                    self.assertEqual(len(lines), 8)
                    self.assertTrue(lines[-2].endswith(" (extend)") and lines[-1].endswith(" (repair)"), lines)
                    for line in lines:
                        source, _, target = line.strip().partition(f" {arrow} ")
                        self.assertTrue(source and target, f"both ends drawn: {line!r}")
                        self.assertLessEqual(cells(line), width)
                    self.assertTrue(lines[-1].startswith("  CSV ") and ellipsis in lines[-1])
        self.assertEqual(section(render_delegation_view(dag_export_repair_run(), width=30), "Dependencies")[-2:],
                         ["  Verify expo… → CSV… (extend)", "  CSV export → CSV e… (repair)"])

    def test_every_cut_line_ends_in_the_ellipsis(self) -> None:
        generator = random.Random(2191)
        words = ["Export", "보고서 작성 및 검토 단계", "x" * 40, "CSV export, with the header row", "A"]
        for trial in range(80):
            nodes = [root()] + [lane(f"n{index}", " ".join(generator.choice(words) for _ in range(generator.randint(1, 3))),
                                     "quick", "glm-5.3-flash", "", generator.choice(["running", "done", "waiting"]),
                                     order=index) for index in range(6)]
            edges = [("root", "n0", "dispatch")] + [
                (f"n{generator.randint(0, index - 1)}", f"n{index}", generator.choice(["depends_on", "repair", "extend"]))
                for index in range(1, 6)
            ]
            for charset, arrow, ellipsis in (("unicode", "→", "…"), ("ascii", "->", "...")):
                for width in (26, 30, 34, 40):
                    view = render_delegation_view(graph(nodes, edges), width=width, charset=charset)
                    for line in section(view, "Dependencies"):
                        with self.subTest(trial=trial, width=width, charset=charset, line=line):
                            self.assertFalse(line.rstrip().endswith((arrow, "·", "-")), "never an arrow with no target")
                            whole = {f"  {node['title']} {arrow} {other['title']}" for node in nodes for other in nodes}
                            if not any(line.startswith(prefix) for prefix in whole):
                                self.assertIn(ellipsis, line, "a cut line says so")

    def test_a_line_filled_to_the_edge_still_says_it_was_cut(self) -> None:
        """A category that fills the box exactly leaves no room for ` · model`: the category gives way to the
        ellipsis rather than the model vanishing with nothing to say so."""
        for charset, category, expected in (("unicode", "a" * 22, "a" * 21 + "…"), ("ascii", "a" * 21, "a" * 19 + "...")):
            full = graph([root(), lane("x", "Short", category, "glm-5.3-flash", "low", "running", elapsed=5)],
                         [("root", "x", "dispatch")])
            with self.subTest(charset=charset):
                self.assertEqual(box_lines(render_delegation_view(full, width=26, charset=charset))["x"][1], expected)

    def test_a_box_draws_no_question_mark(self) -> None:
        unowned = graph([root(model="", effort=""),
                         lane("u", "Unit one", "?", "?", "", "running", elapsed=30),
                         lane("w", "Unit two", "?", "?", "", "unknown", status="no news")],
                        [("root", "u", "dispatch"), ("root", "w", "dispatch")], source="fanout")
        view = render_delegation_view(unowned, width=80)
        boxes = box_lines(view)
        self.assertEqual(boxes["u"], ["Unit one", "", "● Running 30s", "Start node"])
        self.assertEqual(boxes["w"], ["Unit two", "", "◇ No news", "Start node"], "an unknown state's glyph is no `?`")
        self.assertNotIn("?", view.text())
        self.assertEqual(section(view, "Node details"), ["  ● Unit one", "    Running 30s"], "no facts line, no `?`")
        self.assertIn("<> No news", text(unowned, width=80, charset="ascii"))

    def test_the_hud_probe_names_every_character_a_box_draws(self) -> None:
        from omh.commands.hud import DELEGATION_VIEW_PROBE

        drawn = set()
        counted = with_tokens(dag_export_run(), {"d:r1:button": 1234})
        for case in (dag_export_run(), dag_export_repair_run(), nested(), owner_mock(), counted):
            for focus in (None, Focus(node="d:r1:api", folded=frozenset({"d:r1:api"}))):
                drawn |= set(render_delegation_view(case, width=120, focus=focus).text())
        unknown = graph([root(), lane("w", "Unit", "quick", "m", "", "unknown")], [("root", "w", "dispatch")])
        drawn |= set(render_delegation_view(unknown, width=80).text())
        lines_only = {char for char in drawn if not char.isascii() and not char.isalnum() and char not in "인증모듈문서정리"}
        self.assertEqual(lines_only - set(DELEGATION_VIEW_PROBE), set())
        self.assertIn("↻", lines_only)
        self.assertIn("↓", lines_only)

    def test_a_folded_box_keeps_its_status_word_in_both_charsets(self) -> None:
        focus = Focus(node="d:r1:cli", folded=frozenset({"d:r1:api", "d:r1:cli"}))
        unicode_boxes = box_lines(render_delegation_view(dag_export_run(), width=140, focus=focus))
        self.assertEqual(unicode_boxes["d:r1:api"], ["[+] ✓ Export API · Accepted"])
        self.assertEqual(unicode_boxes["d:r1:cli"], ["[+] > ✗ Export CLI flag · Failed"])
        ascii_boxes = box_lines(render_delegation_view(dag_export_run(), width=140, focus=focus, charset="ascii"))
        self.assertEqual(ascii_boxes["d:r1:api"], ["[+] + Export API - Accepted"])
        self.assertEqual(ascii_boxes["d:r1:cli"], ["[+] > x Export CLI flag - Failed"])
        longer = dag_export_run()
        longer["nodes"][4]["title"] = "Export CLI flag for every output format we ship today"
        self.assertEqual(box_lines(render_delegation_view(longer, width=140, focus=focus))["d:r1:cli"],
                         ["[+] > ✗ Export CLI flag for eve… · Failed"], "past the box the title gives way")
        self.assertEqual(box_lines(render_delegation_view(longer, width=140, focus=focus, charset="ascii"))["d:r1:cli"],
                         ["[+] > x Export CLI flag for e... - Failed"])
        # A folded, selected box whose one line is the widest of the drawing measures all of it: `[+] > ✓ ` is 8
        # cells, then the title, then ` · Accepted`, so nothing is cut while the width allows.
        alone = graph([root(), lane("a", "Export API", "quick", "m", "", "done", status="accepted", elapsed=12)],
                      [("root", "a", "dispatch")])
        line = box_lines(render_delegation_view(alone, width=80, focus=Focus(node="a", folded=frozenset({"a"}))))["a"]
        self.assertEqual(line, ["[+] > ✓ Export API · Accepted"])

    def test_a_run_that_only_lost_its_news_does_not_read_as_an_error(self) -> None:
        lost = dag_export_run()
        for node in lost["nodes"][1:]:
            node.update(state="unknown", status="no news")
        view = render_delegation_view(lost, width=100)
        self.assertEqual(view.text_lines()[2], "Ended · Done 0/5")
        self.assertEqual(view.lines[2][0].role, "node-word:unknown")
        cancelled = dag_export_run()
        cancelled["nodes"][2].update(state="interrupted", status="cancelled")
        for node in cancelled["nodes"][1:]:
            if node["state"] != "interrupted":
                node["state"] = "done"
        self.assertEqual(render_delegation_view(cancelled, width=100).lines[2][0].role, "node-word:interrupted")

    def test_a_connector_into_a_frontier_with_nothing_running_is_dim(self) -> None:
        handed = dag_export_run()
        handed["nodes"][2].update(state="dispatched", status="handed out")  # the frontier: handed out, failed
        for width in (80, 100):  # the one connector (a frontier wraps at 80), and the edges drawn
            view = render_delegation_view(handed, width=width)
            self.assertEqual(set().union(*connector_roles(view)), {"connector"},
                             "handed out is not running: the connector stays dim")

    def test_a_duplicated_edge_is_listed_once(self) -> None:
        twice = dag_export_run()
        twice["edges"].append({"from": "d:r1:api", "to": "d:r1:docs", "kind": "depends_on"})
        lines = section(render_delegation_view(twice, width=100), "Dependencies")
        self.assertEqual(lines.count("  Export API → Export docs"), 1)
        self.assertEqual(len(lines), 6)

    def test_a_repair_mark_wins_over_an_extend_mark(self) -> None:
        both = dag_export_repair_run()
        both["edges"].append({"from": "d:r1:verify", "to": "d:r1:csv-fix", "kind": "extend"})
        self.assertEqual(box_lines(render_delegation_view(both, width=100))["d:r1:csv-fix"][0][:2], "↻ ")


TOKEN_PART = re.compile(r"( · ↓| - out )[0-9.]+[kM]?( tokens)?")


def card_start(view) -> int:
    """Where the Node details section starts in ``view``, or its end when it has none."""
    lines = view.text_lines()
    return lines.index("Node details") if "Node details" in lines else len(lines)
EXPORT_COUNTS = {"d:r1:button": 1234, "d:r1:api": 5600, "d:r1:cli": 800}


class OutputTokenTests(unittest.TestCase):
    """A lane's `output_tokens`: after its status in its box and its tree row where they have room, in its card."""

    def test_a_box_says_its_count_after_its_status(self) -> None:
        boxes = box_lines(render_delegation_view(with_tokens(dag_export_run(), EXPORT_COUNTS), width=100))
        self.assertEqual(
            [boxes[node_id][2] for node_id in ("d:r1:api", "d:r1:button", "d:r1:docs", "d:r1:cli")],
            ["✓ Accepted 12s · ↓5.6k", "● Running 21s · ↓1.2k", "◌ Handed out", "✗ Failed 8s · ↓800"],
        )
        ascii_drawn = text(with_tokens(dag_export_run(), EXPORT_COUNTS), width=80, charset="ascii")
        self.assertIn("| * Running 21s - out 1.2k        |", ascii_drawn)
        self.assertIn("| + Accepted 12s - out 5.6k       |", ascii_drawn)
        self.assertTrue(ascii_drawn.isascii())

    def test_a_count_reads_in_four_characters_and_a_unit_up_to_trillions(self) -> None:
        from omh.plugin_bundle.omh.hud_text import compact_count

        self.assertEqual([compact_count(value) for value in (950, 1234, 3_000_000, 70_049_332_364, 1_234_567_890_123)],
                         ["950", "1.2k", "3M", "70B", "1.2T"])

    def test_a_box_count_shows_while_its_status_line_fits_and_drops_out_whole(self) -> None:
        # Measured as it reads, beside the status as it reads: the box keeps its width, the count comes and goes.
        def button(elapsed: float, count: int) -> str:
            counted = dag_export_run()
            for node in counted["nodes"]:
                if node["id"] == "d:r1:button":
                    node.update(elapsed_seconds=elapsed, output_tokens=count)
            return box_lines(render_delegation_view(counted, width=100))["d:r1:button"][2]

        self.assertEqual(button(21, 1400), "● Running 21s · ↓1.4k")
        self.assertEqual(button(21, 45_600), "● Running 21s · ↓45.6k")
        self.assertEqual(button(59 * 60 + 59, 45_600), "● Running 59m 59s · ↓45.6k")
        self.assertEqual(button(100 * 3600 + 59 * 60, 999_900), "● Running 100h 59m · ↓999.9k")
        widths = {len(render_delegation_view(dag_export_run(), width=100).text_lines()[4])}
        for elapsed in (21, 3599, 100 * 3600 + 59 * 60):
            counted = with_tokens(dag_export_run(), {"d:r1:button": 999_900})
            counted["nodes"][2]["elapsed_seconds"] = elapsed
            widths.add(len(render_delegation_view(counted, width=100).text_lines()[4]))
        self.assertEqual(len(widths), 1, "no count widens a box")

    def test_a_card_says_the_count_in_tokens(self) -> None:
        view = render_delegation_view(with_tokens(dag_export_run(), EXPORT_COUNTS), width=100)
        self.assertEqual(
            section(view, "Node details"),
            ["  ● Export button", "    unspecified-high · glm-5.3:low",
             "    Running 21s · ↓1.2k tokens · layer 2 · session 7c41e9a2"],
        )

    def test_the_tree_status_column_takes_the_count_where_the_row_has_room(self) -> None:
        counted = with_tokens(nested(), {"o": 45_600, "k": 900, "o1": 3000, "o2": 120})
        wide = render_delegation_view(counted, width=60, layout="tree").text_lines()
        self.assertEqual(wide[4], "│    architect · opus-5-5:xhigh · running 6m 40s · ↓45.6k")
        self.assertEqual(wide[-1], "     writing · opus-5-5:medium · running 5m 55s · ↓900")
        self.assertNotIn("↓", render_delegation_view(counted, width=34, layout="tree").text(), "the model first")
        row = render_delegation_view(with_tokens(owner_mock(), {"a": 1234}), width=100, layout="tree").text_lines()[2]
        self.assertTrue(row.endswith("running 2m 10s · ↓1.2k"), row)

    def test_a_count_cuts_nothing_and_a_growing_one_never_moves_the_layout(self) -> None:
        # The drawing with the count parts blanked out where they stand (a box keeps its padding, a row ends there):
        # the tree's is the plain one, and a box's is the same whatever the counts read, since a box makes its room
        # for a count at a fixed widest. Node details are left out: a card's group and session give way to a count.
        cases = [(dag_export_run, EXPORT_COUNTS), (nested, {"o": 45_600, "k": 900, "o1": 3000, "o2": 120}),
                 (owner_mock, {"a": 1234, "b": 62_000, "c": 7})]

        def blanked(view) -> list[str]:
            text = TOKEN_PART.sub(lambda part: " " * cells(part.group()), view.text())
            return [line.rstrip() for line in text.splitlines()][:card_start(view)]

        for make, counts in cases:
            for width in range(20, 161, 3):
                for layout in ("box", "tree"):
                    plain = render_delegation_view(make(), width=width, layout=layout)
                    drawn = []
                    for scale in (1, 1000, 100_000):
                        scaled = {key: value * scale for key, value in counts.items()}
                        counted = render_delegation_view(with_tokens(make(), scaled), width=width, layout=layout)
                        drawn.append(counted)
                        with self.subTest(case=make.__name__, width=width, layout=layout, scale=scale):
                            self.assertEqual(counted.layout, plain.layout)
                            if layout == "tree":
                                self.assertEqual(blanked(counted), [line.rstrip() for line in plain.text_lines()])
                            cut = [line for line in section(counted, "Node details") if "↓" in line]
                            self.assertFalse([line for line in cut if not TOKEN_PART.search(line)], "whole or none")
                            self.assertTrue(all(cells(line) <= width for line in counted.text_lines()))
                    with self.subTest(case=make.__name__, width=width, layout=layout):
                        self.assertEqual([view.boxes for view in drawn], [drawn[0].boxes] * 3)
                        self.assertEqual([blanked(view) for view in drawn], [blanked(drawn[0])] * 3)

    def test_a_card_keeps_its_status_whole_and_drops_its_session_before_the_count(self) -> None:
        counted = with_tokens(dag_export_run(), EXPORT_COUNTS)
        cases = {
            70: "    Running 21s · ↓1.2k tokens · layer 2 · session 7c41e9a2",
            45: "    Running 21s · ↓1.2k tokens · layer 2 · s…",
            40: "    Running 21s · ↓1.2k tokens · layer…",
            33: "    Running 21s · layer 2 · sess…",  # no room for a count at its widest: none at all
        }
        for width, line in cases.items():
            with self.subTest(width=width):
                view = render_delegation_view(counted, width=width, layout="box")
                self.assertEqual(view.layout, "box")
                self.assertEqual(section(view, "Node details")[-1], line)

    def test_a_count_after_a_status_past_a_hundred_hours_is_whole_or_absent(self) -> None:
        # `100h 59m` is eight cells, one more than a duration is measured at (`DURATION_CELLS`): the room for a count
        # is measured on the status as drawn there, so the count is never cut to `↓999.…`.
        for make in (dag_export_run, nested, owner_mock):
            long = make()
            for node in long["nodes"][1:]:
                node.update(state="running", status="running", elapsed_seconds=100 * 3600 + 59 * 60, waits_on=0)
                node["output_tokens"] = 999_900
            for width in range(8, 201):
                for layout in ("box", "tree"):
                    for charset in ("unicode", "ascii"):
                        drawn = text(long, width=width, layout=layout, charset=charset)
                        with self.subTest(case=make.__name__, width=width, layout=layout, charset=charset):
                            self.assertIsNone(re.search(r"(↓|out )[0-9.]*[kM]?(…|\.\.\.)", drawn), drawn)

    def test_a_cards_count_keeps_its_unit_whole_whatever_follows_it(self) -> None:
        # With a group and a session after it, an exactly full line once lent the ellipsis a cell of `tokens`.
        whole = re.compile(r"(↓|out )[0-9.]+[kM]? tokens(?![a-z])")
        for elapsed in (21, 12 * 60 + 34, 100 * 3600 + 59 * 60):
            for count in (800, 45_600, 999_900):
                counted = dag_export_run()
                for node in counted["nodes"]:
                    if node["id"] == "d:r1:button":
                        node.update(elapsed_seconds=elapsed, output_tokens=count)
                for charset in ("unicode", "ascii"):
                    for width in range(26, 121):
                        view = render_delegation_view(counted, width=width, layout="box", charset=charset)
                        written = "↓" if charset == "unicode" else "out "
                        for line in section(view, "Node details"):
                            if written in line:
                                with self.subTest(elapsed=elapsed, count=count, charset=charset, width=width):
                                    self.assertRegex(line, whole)

    def test_no_count_draws_nothing(self) -> None:
        plain = render_delegation_view(dag_export_run(), width=100).text()
        for count in (None, 0, -5, True, "1200", 1.5, 10**9):
            with self.subTest(count=count):
                counted = with_tokens(dag_export_run(), {"d:r1:button": count})
                self.assertEqual(render_delegation_view(counted, width=100).text(), plain)


def box_inner(view) -> set[int]:
    """The inner widths of the boxes in ``view``, read off their top borders."""
    return {len(edge) - 4 for edge in re.findall(r"[┌+][─-]*[┐+]", view.text()) if len(edge) > 4}


def bound(payload: dict, count: object) -> dict:
    """``payload`` with every lane bound to a child that has counted ``count`` (None: no count yet)."""
    for node in payload["nodes"][1:]:
        node["output_tokens"] = count
    return payload


class BoxTokenRoomTests(unittest.TestCase):
    """Once a lane carries a count, a box makes room for one at a realistic widest, so it stays in sight."""

    def test_a_graph_without_a_count_draws_exactly_as_before(self) -> None:
        # Lanes bound to children with no count yet (`output_tokens` None) draw as lanes with no key at all; the
        # #2191 snapshots above pin those drawings against main.
        makes = (dag_export_run, dag_export_repair_run, owner_mock, nested, lambda: parallel(3), lambda: parallel(6),
                 export_run, lambda: export_run(staged=True))
        for make in makes:
            for width in range(26, 161, 2):
                for charset in ("unicode", "ascii"):
                    for focus in (None, Focus(node=str(make()["nodes"][1]["id"]))):
                        with self.subTest(graph=make().get("name"), width=width, charset=charset, focus=focus):
                            plain = render_delegation_view(make(), width=width, charset=charset, focus=focus)
                            unseen = render_delegation_view(bound(make(), None), width=width, charset=charset,
                                                            focus=focus)
                            self.assertEqual(unseen.text(), plain.text())

    def test_a_counted_box_holds_a_running_status_of_an_hour_with_its_count(self) -> None:
        # `● Running 59m 59s · ↓999.9k` is 27 cells: the room, measured from the text, not written down as a number.
        counted = bound(parallel(2), 45_600)
        for width in (80, 100, 120):
            with self.subTest(width=width):
                self.assertEqual(box_inner(render_delegation_view(parallel(2), width=width)), {25})
                self.assertEqual(box_inner(render_delegation_view(counted, width=width)), {27})
        for elapsed, line in ((21, "● Running 21s · ↓45.6k"), (724, "● Running 12m 4s · ↓45.6k"),
                              (3599, "● Running 59m 59s · ↓45.6k")):
            for node in counted["nodes"][1:]:
                node["elapsed_seconds"] = elapsed
            with self.subTest(elapsed=elapsed):
                self.assertEqual(box_lines(render_delegation_view(counted, width=100))["l0"][2], line)

    def test_the_ascii_room_holds_its_longer_count_mark(self) -> None:
        # ASCII writes `out ` where Unicode writes `↓`: its room is measured in its own charset, three cells wider.
        counted = bound(parallel(2), 45_600)
        for node in counted["nodes"][1:]:
            node["elapsed_seconds"] = 3599
        view = render_delegation_view(counted, width=100, charset="ascii")
        self.assertEqual({len(edge) - 4 for edge in re.findall(r"\+-+\+", view.text())}, {30})
        self.assertIn("| * Running 59m 59s - out 45.6k  |", view.text())

    def test_a_layout_decided_before_a_count_is_not_replayed_after_it(self) -> None:
        # The kept layout decision is keyed on whether any lane carries a count, which changes the boxes' widths:
        # under a line budget a graph reached through a warm cache draws exactly as it does cold, either way round.
        from omh.plugin_bundle.omh import delegation_view

        cases = [(owner_mock, 62, 30), (lambda: parallel(3), 62, 20), (lambda: parallel(5), 62, 30),
                 (export_run, 62, 45)]
        for make, width, budget in cases:
            plain, counted = make(), make()
            for payload in (plain, counted):
                for node in payload["nodes"][1:]:
                    node["elapsed_seconds"] = 724
            for node in counted["nodes"][1:]:
                if node.get("state") in ("running", "stuck", "done", "failed", "interrupted"):
                    node["output_tokens"] = 45_600
            options = {"width": width, "max_lines": budget}
            cold = {}
            for name, payload in (("plain", plain), ("counted", counted)):
                delegation_view._DECISIONS.clear()
                cold[name] = render_delegation_view(payload, **options).text()
            for first, then in (("plain", "counted"), ("counted", "plain")):
                delegation_view._DECISIONS.clear()
                render_delegation_view(plain if first == "plain" else counted, **options)
                warm = render_delegation_view(plain if then == "plain" else counted, **options).text()
                with self.subTest(graph=make().get("name"), width=width, budget=budget, order=f"{first} then {then}"):
                    self.assertEqual(warm, cold[then])
        delegation_view._DECISIONS.clear()

    def test_a_layout_decided_past_100_hours_is_not_replayed_under_them(self) -> None:
        # A status counted as it reads widens its box at 100 hours, so the kept decision is keyed on the cells each
        # status is counted at: three timed-out lanes that wrap to a tree past the mark draw as boxes again under it.
        from omh.plugin_bundle.omh import delegation_view

        def timeouts(seconds: int) -> dict:
            payload = parallel(3)
            for node in payload["nodes"][1:]:
                node.update(title="Fix", category="", model="", effort="", state="failed", status="failed: timeout",
                            elapsed_seconds=seconds)
            return payload

        options = {"width": 60, "max_lines": 17}
        under, over = timeouts(99 * 3600 + 59 * 60), timeouts(100 * 3600)
        delegation_view._DECISIONS.clear()
        cold = render_delegation_view(under, **options)
        delegation_view._DECISIONS.clear()
        self.assertEqual(render_delegation_view(over, **options).layout, "tree")
        warm = render_delegation_view(under, **options)
        self.assertEqual((warm.layout, warm.text()), (cold.layout, cold.text()))
        self.assertEqual(cold.layout, "box")
        delegation_view._DECISIONS.clear()

    def test_three_boxes_still_share_a_row_at_100_columns(self) -> None:
        counted = with_tokens(dag_export_run(), {"d:r1:button": 1234, "d:r1:docs": 900, "d:r1:cli": 800})
        for payload in (dag_export_run(), counted):
            view = render_delegation_view(payload, width=100)
            rows = [line for line in view.text_lines() if "┌" in line]
            self.assertIn(3, [line.count("┌") for line in rows], "the middle frontier is one row")

    def test_a_row_that_cannot_afford_the_room_shrinks_and_the_count_shows_only_while_it_fits(self) -> None:
        # Three boxes in 82 columns get 22 cells inside, as without a count; the line as it reads decides.
        counted = bound(parallel(3), 1234)
        view = render_delegation_view(counted, width=82)
        self.assertEqual(box_inner(view), {22})
        self.assertEqual([line.count("┌") for line in view.text_lines() if "┌" in line], [3])
        self.assertEqual(box_lines(view)["l0"][2], "● Running 1m 0s")  # with the count, 23 cells: left out
        for node in counted["nodes"][1:]:
            node["elapsed_seconds"] = 21
        self.assertEqual(box_lines(render_delegation_view(counted, width=82))["l0"][2], "● Running 21s · ↓1.2k")

    def test_the_room_is_made_only_for_a_lane_bound_to_a_child(self) -> None:
        # A waiting lane with no child (no `output_tokens` key) keeps its own need: `○ Waits on 3 lanes` sets nothing.
        mock = owner_mock()
        mock["nodes"][1]["output_tokens"] = 1234  # the running `Refresh HUD docs` lane
        for node in mock["nodes"][1:]:
            node.update(title="A", category="c", model="m", effort="")
        widths = box_inner(render_delegation_view(mock, width=140))
        self.assertEqual(widths, {27})


class FieldTests(unittest.TestCase):
    def test_a_field_without_evidence_is_a_question_mark(self) -> None:
        bare = graph([root(model="", effort=""), {"id": "x", "kind": "lane", "state": "dispatched"}],
                     [("root", "x", "dispatch")])
        self.assertEqual(box_lines(render_delegation_view(bare, width=80))["x"],
                         ["untitled", "", "◌ Dispatched", "Start node"],
                         "neither category nor model known: the line is blank; no title: `untitled`, never `?`")
        self.assertIn("?  ", text(bare, width=80, layout="tree"))
        self.assertIn("◌ untitled", text(bare, width=80, layout="tree"))

    def test_a_question_mark_is_marked_unknown_for_the_painter(self) -> None:
        bare = graph([root(model="", effort=""), {"id": "x", "kind": "lane", "state": "dispatched"}],
                     [("root", "x", "dispatch")])
        # The box leaves out a category and model with no record; the tree's category column keeps its `?`.
        for layout, width, unknown in (("box", 80, {"untitled"}), ("tree", 80, {"untitled", "?"}),
                                       ("tree", 40, {"untitled", "?"})):
            view = render_delegation_view(bare, width=width, layout=layout)
            segments = [segment for line in view.lines for segment in line]
            with self.subTest(layout=layout, width=width):
                self.assertEqual({segment.text.strip() for segment in segments if segment.role == "unknown"}, unknown)
                self.assertFalse(any(segment.text.strip() == "?" and segment.role != "unknown" for segment in segments))
        known = render_delegation_view(owner_mock(), width=73)
        self.assertFalse(any(segment.role == "unknown" for line in known.lines for segment in line))
        running = graph([root(model="", effort=""), {"id": "x", "kind": "lane", "state": "running", "elapsed_seconds": 5}],
                        [("root", "x", "dispatch")])
        view = render_delegation_view(running, width=80, layout="box")
        self.assertEqual([segment.role for line in view.lines for segment in line if segment.text.strip() == "untitled"],
                         ["unknown", "unknown"], "the box's title and its Node details card's")

    def test_waits_on_names_how_many_recorded_dependencies_are_unmet(self) -> None:
        self.assertIn("○ Waits on 3 lanes", text(owner_mock(), width=73))
        single = owner_mock()
        single["nodes"][-1]["waits_on"] = 1
        self.assertIn("○ Waits on 1 lane", text(single, width=73))

    def test_a_stuck_unit_is_never_drawn_running(self) -> None:
        stuck = graph([root(), lane("s", "Fan out", "codex", "gpt-6.1-sol", "high", "stuck", elapsed=400,
                                     status="stuck: same error")], [("root", "s", "dispatch")])
        drawn = text(stuck, width=80)
        self.assertIn("! Stuck 6m 40s: same error", drawn)
        self.assertIn("Running · Done 0/1 · 1 stuck", drawn)
        self.assertNotIn("● ", drawn)

    def test_waves_of_one_root_are_one_frontier_and_the_tree_keeps_their_labels(self) -> None:
        waves = graph(
            [root(),
             lane("a", "Refresh docs", "writing", "claude-opus-5-5", "medium", "done", elapsed=250,
                  group="wave 1 · 14:02", order=1),
             lane("b", "Polish CLI output", "quick", "glm-5.3-flash", "low", "done", elapsed=62,
                  group="wave 1 · 14:02", order=2),
             lane("v", "Integration verify", "inherit", "claude-opus-5-5", "", "running", elapsed=30,
                  group="wave 2 · 14:09", order=3)],
            [("root", "a", "dispatch"), ("root", "b", "dispatch"), ("root", "v", "dispatch")],
        )
        view = render_delegation_view(waves, width=120)
        self.assertEqual(len({top for _node, top, _bottom in view.boxes}), 1, "a wave is order, not a dependency")
        self.assertIn("    Running 30s · wave 2 · 14:09", view.text_lines(), "the running node's card names its wave")
        self.assertIn("    Running 30s - wave 2 - 14:09", text(waves, width=120, charset="ascii").splitlines())
        tree = text(waves, width=80, layout="tree")
        self.assertLess(tree.index("wave 1 · 14:02"), tree.index("wave 2 · 14:09"))

    def test_text_is_folded_before_it_is_measured(self) -> None:
        self.assertEqual(clean_text("a​b‮c\x1b[31m d\n e"), "abc[31m d e")
        self.assertEqual(cells("인증 모듈"), 9)


class StructureTests(unittest.TestCase):
    def test_each_part_of_a_box_carries_its_nodes_state_for_the_painter(self) -> None:
        view = render_delegation_view(dag_export_run(), width=100, focus=Focus(node="d:r1:verify"))
        for node in dag_export_run()["nodes"][1:]:
            named = "selected" if node["id"] == "d:r1:verify" else node["state"]
            border, title, _facts, status, _parents, _bottom = box_spans(view, node["id"])
            with self.subTest(node=node["id"]):
                self.assertEqual({role for _text, role in border}, {f"node:{named}"})
                self.assertEqual({role for _text, role in title if role != "fold"},
                                 {f"node-title:{named}", f"node:{named}"} if named == "selected" else
                                 {f"node-title:{named}"})
                self.assertEqual([role for _text, role in status], [f"node:{node['state']}", f"node-word:{node['state']}"],
                                 "the glyph is a mark, the words a word; both keep the state's colour, selected or not")

    def test_a_connector_is_dim_and_blue_into_a_running_frontier(self) -> None:
        self.assertEqual(connector_roles(render_delegation_view(dag_export_run(), width=80)),
                         [{"connector:running"}] * 2 + [{"connector"}] * 2,
                         "the one connector: into the frontier where Export button runs, then into one where nothing does")
        self.assertEqual(connector_roles(render_delegation_view(dag_export_run(), width=100)),
                         [{"connector:running"}] * 3 + [{"connector"}] * 3, "the edges drawn take the same colours")
        split = fan((2, 2), [("1a", "2a"), ("1b", "2b")], running="2b")
        self.assertEqual(connector_roles(render_delegation_view(split, width=100)),
                         [{"connector", "connector:running"}] * 2, "each group by its own children")
        view = render_delegation_view(dag_export_run(), width=100)
        self.assertEqual({segment.role for line in view.lines for segment in line if segment.text.strip() == "→"},
                         {"connector"})
        self.assertEqual(view.levels, 1, "boxes are coloured by state, not by depth")
        tree = render_delegation_view(nested(), width=34, layout="tree")
        self.assertEqual((tree.layout, tree.levels), ("tree", 3), "the tree's levels are its depths")
        for width in (34, 90):
            columns: dict[int, set[int]] = {}
            for line in render_delegation_view(nested(), width=width, layout="tree").lines:
                at = 0
                for segment in line:
                    for offset, char in enumerate(segment.text):
                        if segment.role == "edge" and char in "│├└─":
                            columns.setdefault(at + offset, set()).add(segment.level)
                    at += len(segment.text)
            with self.subTest(width=width):
                self.assertEqual(sorted(columns), [0, 1, 3, 4, 6, 7], "three depths of branches")
                self.assertEqual([columns[x] for x in (0, 3, 6)], [{0}, {1}, {2}], "a bar keeps its depth's level")

    def test_any_acyclic_shape_is_boxes_and_a_cycle_the_tree(self) -> None:
        skipping = owner_mock()
        skipping["edges"].append({"from": "a", "to": "c", "kind": "depends_on"})  # c drops a frontier; a → v skips one
        crossing = graph(
            [root(), *(lane(name, name, "quick", "m", "", "running") for name in "abcd")],
            [("root", "a", "dispatch"), ("root", "b", "dispatch"),
             ("a", "c", "depends_on"), ("a", "d", "depends_on"), ("b", "d", "depends_on")],
        )
        for case in (skipping, crossing):
            with self.subTest(edges=len(case["edges"])):
                view = render_delegation_view(case, width=120)
                self.assertEqual(view.layout, "box")
                self.assertEqual(len(section(view, "Dependencies")), len(lane_edges(case)))
        loop = graph([root(), lane("a", "A", "c", "m", "", "running"), lane("b", "B", "c", "m", "", "waiting")],
                     [("root", "a", "dispatch"), ("a", "b", "depends_on"), ("b", "a", "depends_on")])
        self.assertEqual(render_delegation_view(loop, width=120).layout, "tree")

    def test_no_line_is_ever_wider_than_its_width(self) -> None:
        generator = random.Random(2026_10_20)
        titles = ["Refresh docs", "인증 모듈 문서 정리와 테스트", "x" * 90, "🙂 emoji title", "a\tb\nc"]
        for trial in range(120):
            nodes = [root()]
            edges = []
            for index in range(generator.randint(1, 14)):
                node_id = f"n{index}"
                parent = generator.choice(["root"] + [node["id"] for node in nodes[1:]])
                nodes.append(lane(node_id, generator.choice(titles), generator.choice(["deep", "?", "x" * 30]),
                                  generator.choice(["claude-opus-5-5", "openrouter/x" * 6, "?"]),
                                  generator.choice(["", "high"]),
                                  generator.choice(["running", "done", "failed", "waiting", "stuck", "bogus"]),
                                  elapsed=generator.choice([None, 5, 4000]), order=index))
                edges.append((parent, node_id, generator.choice(["dispatch", "depends_on", "repair"])))
            case = graph(nodes, edges)
            width = generator.randint(20, 160)
            focus = generator.choice([None, Focus(node="n0", folded=frozenset({"n1"}))])
            for charset in ("unicode", "ascii"):
                view = render_delegation_view(case, width=width, charset=charset, focus=focus,
                                              max_lines=generator.choice([None, 3, 12, 40]))
                with self.subTest(trial=trial, width=width, charset=charset, layout=view.layout):
                    self.assertTrue(all(cells(line) <= max(8, width) for line in view.text_lines()))

    def test_a_chain_too_deep_for_the_width_numbers_its_depth_and_stays_inside(self) -> None:
        nodes = [root()] + [lane(f"n{index}", f"Level {index} task", "deep", "claude-opus-5-5", "high", "running",
                                 elapsed=60) for index in range(16)]
        chain = graph(nodes, [("root", "n0", "dispatch")] + [(f"n{index}", f"n{index + 1}", "dispatch")
                                                             for index in range(15)])
        for width in (34, 40, 80):
            view = render_delegation_view(chain, width=width, layout="tree")
            with self.subTest(width=width):
                self.assertTrue(all(cells(line) <= width for line in view.text_lines()))
                self.assertTrue(any("15 └─ ● Level 15" in line for line in view.text_lines()) or width >= 80)

    def test_inf_nan_and_huge_numbers_draw_without_a_duration(self) -> None:
        for elapsed in (float("inf"), float("nan"), 1e300, -5):
            case = graph([root(), lane("a", "A", "c", "m", "", "running", elapsed=elapsed)], [("root", "a", "dispatch")])
            with self.subTest(elapsed=elapsed):
                self.assertEqual(box_lines(render_delegation_view(case, width=60))["a"][2], "● Running")
                self.assertNotIn("Running 1", render_delegation_view(case, width=60).text())

    def test_nothing_malformed_raises(self) -> None:
        for payload in (None, {}, {"nodes": "x"}, {"nodes": [1, None, {"id": 3}]},
                        {"nodes": [{"id": "a", "kind": "root"}], "edges": [{"from": "a", "to": "zz"}, "e"]},
                        graph([root(), lane("a", "A", "c", "m", "", "running")],
                              [("a", "root", "dispatch"), ("root", "a", "dispatch")]),  # a cycle through the root
                        {"nodes": [{"id": "a", "title": 5, "state": ["x"], "elapsed_seconds": "1",
                                    "waits_on": True}]},
                        {"nodes": [{"id": "a", "kind": "lane"}], "edges": [{"from": "a", "to": "a", "kind": 5}]}):
            for focus in (None, Focus(node="a", folded=frozenset({"a"}))):
                with self.subTest(payload=payload, focus=focus):
                    self.assertIsInstance(render_delegation_view(payload, width=60, focus=focus).text(), str)


if __name__ == "__main__":
    unittest.main()
