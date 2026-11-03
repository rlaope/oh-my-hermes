"""The unfinished work `on_pre_compress` hands Hermes' compaction summary (`compaction_work_state`).

Each test writes the records the way their own writers keep them -- a run as
`omh_dag define` stores it, a plan as `omh_todo action=set` stores it -- and
reads what the provider returns at compaction: facts naming the live run and
the open plan items, and nothing at all for a finished or empty session.
"""

from __future__ import annotations

import json
import time
import unittest
from unittest.mock import patch

from _local_package import load_local_package

load_local_package()

from _delegation_state import PARENT, homes  # noqa: E402
from omh.plugin_bundle.omh import compaction_work_state, dag_run  # noqa: E402
from omh.plugin_bundle.omh.compaction_work_state import (  # noqa: E402
    HEADER,
    MAX_TEXT_CHARS,
    MAX_WORK_STATE_CHARS,
    work_state_facts,
)
from omh.plugin_bundle.omh.memory_blocks import (  # noqa: E402
    DEFAULT_SYSTEM_RENDER_BUDGET_CHARS,
    approve_memory_block,
    build_memory_block,
    read_memory_blocks,
    render_memory_blocks,
    write_memory_block,
)
from omh.plugin_bundle.omh.memory_provider import OmhMemoryProvider  # noqa: E402
from omh.plugin_bundle.omh.todo_store import (  # noqa: E402
    MAX_TODO_ITEMS,
    MAX_TODO_TEXT_CHARS,
    MAX_TODO_TITLE_CHARS,
    build_todo_record,
    write_todo,
)
from test_dag_tool import node  # noqa: E402

# Words that would make a fact a request; Hermes reads this text as source material only.
_REQUEST_WORDS = ("call ", "continue", "resume", "please", "you should", "must ", "next step", "omh_dag action")
_PERSONA_WORDS = ("persona", "voice", "tone", "language", "soul")


def stored_run(home, nodes: list[dict], *, run: str = "feat", goal: str = "Ship the export feature",
               session: str = PARENT, accepted: tuple[str, ...] = (), cancelled: bool = False) -> dict:
    moment = time.time()
    record = dag_run.new_record(session, run, "Export feature", goal, nodes, moment)
    for item in record["nodes"]:
        if item["id"] in accepted:
            item["attempts"] = [{"n": 1, "handed_out_at": moment, "opened_at": moment, "outcome": "accepted"}]
    if cancelled:
        record["cancelled_at"] = moment
    path = dag_run.record_path(home.omh, session, run)
    path.parent.mkdir(parents=True, exist_ok=True)
    dag_run.write_run(path, record)
    return record


def stored_todo(home, items: list[dict], *, title: str = "Export feature", source: str = "omh_todo",
                session: str = PARENT, **fields: object) -> None:
    write_todo(home.omh, build_todo_record(title, items, source=source, session_ref=session, **fields))


def provider_for(home, session: str = PARENT, *, platform: str = "cli") -> OmhMemoryProvider:
    provider = OmhMemoryProvider(home.omh)
    provider.initialize(session, platform=platform, hermes_home=str(home.hermes), agent_context="primary",
                        cwd=str(home.omh.parent))
    return provider


def facts(home, session: str = PARENT) -> str:
    return work_state_facts(omh_home=home.omh, hermes_home=home.hermes, session_id=session)


class LiveWorkTests(unittest.TestCase):
    """Mutation: drop the run lines or the todo line from `work_state_facts`."""

    def test_a_live_run_and_open_todos_reach_the_summary_as_facts(self) -> None:
        with homes() as home:
            stored_run(home, [node("api", label="Build the API"), node("docs", depends_on=("api",), label="Write docs"),
                              node("ui", label="Build the UI")], accepted=("ui",))
            stored_todo(home, [{"text": "Define the schema", "state": "done"},
                               {"text": "Wire the export endpoint", "state": "active"},
                               {"text": "Document the flags", "state": "pending"}])
            preserved = provider_for(home).on_pre_compress([{"role": "user", "content": "x"}] * 4)
        lines = preserved.splitlines()
        self.assertEqual(lines[0], HEADER)
        self.assertEqual(lines[1], (
            "- dag-ulw run feat (Export feature), goal: Ship the export feature. Run state running; 1/3 nodes done. "
            "Open nodes: api \"Build the API\" ready; docs \"Write docs\" waiting."))
        self.assertEqual(lines[2], (
            "- Plan todo \"Export feature\": 1/3 items done. Open items: active: Wire the export endpoint; "
            "pending: Document the flags."))
        self.assertEqual(len(lines), 3)

    def test_facts_follow_the_blocks_and_take_their_room_from_the_block_budget(self) -> None:
        with homes() as home:
            write_memory_block(home.omh, approve_memory_block(build_memory_block("facts", "must survive compaction")))
            stored_run(home, [node("api")])
            work = facts(home)
            preserved = provider_for(home).on_pre_compress([{"role": "user"}])
            blocks = read_memory_blocks(home.omh, tier="system")
        self.assertTrue(work)
        self.assertTrue(preserved.endswith("\n\n" + work))
        self.assertIn("must survive compaction", preserved[: -len(work)])
        self.assertTrue(render_memory_blocks(blocks, budget_chars=DEFAULT_SYSTEM_RENDER_BUDGET_CHARS - len(work) - 2))

    def test_a_run_survives_a_rotating_compaction_of_its_conversation(self) -> None:
        with homes() as home:
            home.session(PARENT, "m")
            stored_run(home, [node("api")])
            home.rotate(PARENT, "20261020_150000_next")
            text = facts(home, "20261020_150000_next")
        self.assertIn("dag-ulw run feat", text)

    def test_a_plan_hermes_native_todo_list_wrote_is_left_to_hermes(self) -> None:
        # Hermes folds its own todo list back into the compacted transcript verbatim.
        with homes() as home:
            stored_todo(home, [{"text": "Native step", "state": "pending"}], source="todo_list")
            self.assertEqual(facts(home), "")

    def test_stamps_a_plan_carries_are_named(self) -> None:
        with homes() as home:
            stored_todo(home, [{"text": "Step one", "state": "pending"}], plan_stage="awaiting_acceptance",
                        deferred_reason="The user asked to wait for the review.")
            text = facts(home)
        self.assertIn("(plan stage awaiting_acceptance; deferred)", text)
        self.assertNotIn("wait for the review", text)


class SurfaceAndFaultTests(unittest.TestCase):
    """Mutation: compute the facts unguarded, drop the block-budget reservation, or sort on a raw ``updated_at``."""

    def test_a_shared_surface_gets_its_own_facts_and_no_blocks(self) -> None:
        with homes() as home:
            write_memory_block(home.omh, approve_memory_block(build_memory_block("facts", "operator only")))
            stored_run(home, [node("api")], session="discord-1")
            preserved = provider_for(home, "discord-1", platform="discord").on_pre_compress([{"role": "user"}])
            work = facts(home, "discord-1")
        self.assertTrue(work)
        self.assertEqual(preserved, work)
        self.assertNotIn("operator only", preserved)

    def test_past_the_hosts_ceiling_the_facts_survive_its_elision_whole(self) -> None:
        # `sanitize_memory_context` (`agent/context_engine.py`): past 6,000 characters Hermes keeps
        # the first 4,000 and the last 1,500. Block elements fill their budget and the omission lines
        # for the blocks that did not fit come on top of it.
        with homes() as home:
            for index in range(60):
                write_memory_block(home.omh, approve_memory_block(
                    build_memory_block(f"fact{index:02d}", f"{index:02d} " + "v" * 1_800)))
            stored_run(home, [node("api"), node("docs", depends_on=("api",))])
            stored_todo(home, [{"text": f"Step {index}", "state": "pending"} for index in range(10)])
            work = facts(home)
            provider = provider_for(home)
            preserved = provider.on_pre_compress([{"role": "user"}])
            blocks = read_memory_blocks(home.omh, tier="system")
            evaluations = provider._block_selection(blocks=blocks, now=None).evaluations
        # The blocks gave up exactly the facts' room, which here costs them a block.
        reduced = render_memory_blocks(blocks, budget_chars=DEFAULT_SYSTEM_RENDER_BUDGET_CHARS - len(work) - 2,
                                       evaluations=evaluations)
        full = render_memory_blocks(blocks, budget_chars=DEFAULT_SYSTEM_RENDER_BUDGET_CHARS, evaluations=evaluations)
        self.assertEqual(preserved, reduced + "\n\n" + work)
        self.assertNotEqual(reduced, full)
        self.assertGreater(len(preserved), 6_000)
        self.assertTrue(preserved.endswith(work))
        kept_tail = preserved[-1_500:]
        self.assertIn(work, kept_tail)

    def test_a_fault_in_the_facts_costs_only_the_facts(self) -> None:
        with homes() as home:
            write_memory_block(home.omh, approve_memory_block(build_memory_block("facts", "kept through a fault")))
            stored_run(home, [node("api")])
            provider = provider_for(home)
            with patch.object(compaction_work_state, "work_state_facts", side_effect=AttributeError("boom")):
                preserved = provider.on_pre_compress([{"role": "user"}])
            blocks = read_memory_blocks(home.omh, tier="system")
            selection = provider._block_selection(blocks=blocks, now=None)
        self.assertEqual(preserved, render_memory_blocks(
            blocks, budget_chars=DEFAULT_SYSTEM_RENDER_BUDGET_CHARS, evaluations=selection.evaluations))
        self.assertEqual(provider._write_failures[-1],
                         {"op": "work_state", "path": "compaction_work_state", "error": "AttributeError"})

    def test_a_run_whose_stamp_is_not_a_number_sorts_last_and_costs_nothing(self) -> None:
        with homes() as home:
            stored_run(home, [node("api")], run="good")
            stored_run(home, [node("api")], run="odd")
            path = dag_run.record_path(home.omh, PARENT, "odd")
            record = json.loads(path.read_text(encoding="utf-8"))
            record["updated_at"] = "yesterday"
            path.write_text(json.dumps(record), encoding="utf-8")
            text = facts(home)
        runs = [line for line in text.splitlines() if line.startswith("- dag-ulw run")]
        self.assertEqual([line.split()[3] for line in runs], ["good", "odd"])


class IdleTests(unittest.TestCase):
    """Mutation: let a finished run or a finished plan through, or emit the header with no lines."""

    def test_a_finished_or_empty_session_adds_zero_bytes(self) -> None:
        with homes() as home:
            self.assertEqual(provider_for(home).on_pre_compress([{"role": "user"}]), "")
            stored_run(home, [node("api"), node("ui")], accepted=("api", "ui"))
            stored_run(home, [node("api")], run="old", cancelled=True)
            stored_todo(home, [{"text": "Step one", "state": "done"}, {"text": "Step two", "state": "done"}])
            self.assertEqual(facts(home), "")
            self.assertEqual(provider_for(home).on_pre_compress([{"role": "user"}]), "")

    def test_with_blocks_and_no_live_work_the_return_is_byte_identical(self) -> None:
        with homes() as home:
            write_memory_block(home.omh, approve_memory_block(build_memory_block("facts", "kept as before")))
            stored_run(home, [node("api")], accepted=("api",))
            preserved = provider_for(home).on_pre_compress([{"role": "user"}])
            blocks = read_memory_blocks(home.omh, tier="system")
            provider = provider_for(home)
            selection = provider._block_selection(blocks=blocks, now=None)
        self.assertEqual(preserved, render_memory_blocks(
            blocks, budget_chars=DEFAULT_SYSTEM_RENDER_BUDGET_CHARS, evaluations=selection.evaluations))

    def test_a_home_wide_plan_of_no_session_is_not_this_conversations(self) -> None:
        # `omh runtime todo set` with no session writes `runtime/todo.json`. The projection may still
        # call it `established` for a reader whose ownership it cannot decide; it is not `own_record`.
        with homes() as home:
            write_todo(home.omh, build_todo_record("Owner plan", [{"text": "Owner step", "state": "pending"}],
                                                   source="omh"))
            self.assertTrue((home.omh / "runtime" / "todo.json").is_file())
            self.assertEqual(facts(home, "20261103_discord_abc"), "")
            self.assertEqual(provider_for(home, "20261103_discord_abc", platform="discord").on_pre_compress(
                [{"role": "user"}]), "")

    def test_another_sessions_work_is_not_this_sessions(self) -> None:
        with homes() as home:
            stored_run(home, [node("api")], session="20261020_160000_other")
            stored_todo(home, [{"text": "Other step", "state": "pending"}], session="20261020_160000_other")
            self.assertEqual(facts(home), "")

    def test_no_session_or_no_hermes_home_adds_nothing(self) -> None:
        with homes() as home:
            stored_run(home, [node("api")])
            self.assertEqual(work_state_facts(omh_home=home.omh, hermes_home=home.hermes, session_id=""), "")
            self.assertEqual(work_state_facts(omh_home=home.omh, hermes_home=None, session_id=PARENT), "")


class CapTests(unittest.TestCase):
    """Mutation: raise or drop any cap in `compaction_work_state`."""

    def _crowded(self, home) -> None:
        for index in range(5):
            stored_run(home, [node(f"n{step}", label="L" * 80) for step in range(10)],
                       run=f"run{index}", goal="G" * dag_run.MAX_GOAL_CHARS)
        stored_todo(home, [{"text": "T" * MAX_TODO_TEXT_CHARS, "state": "pending"} for _ in range(MAX_TODO_ITEMS)],
                    title="P" * MAX_TODO_TITLE_CHARS, plan_stage="accepted", template="")

    def test_the_whole_is_bounded_keeps_the_newest_run_and_the_plan_and_counts_the_rest(self) -> None:
        with homes() as home:
            self._crowded(home)
            text = facts(home)
        lines = text.splitlines()
        self.assertLessEqual(len(text), 1_500)
        self.assertEqual(MAX_WORK_STATE_CHARS, 1_500, "Hermes keeps the last 1,500 characters when it elides")
        self.assertLessEqual(len(text.encode("utf-8")), 1_500 + 2 * text.count("…"))
        self.assertEqual(lines[0], HEADER)
        self.assertTrue(lines[1].startswith("- dag-ulw run run"))
        self.assertEqual(lines[1].count('" '), 6)
        self.assertTrue(lines[1].endswith("; 4 more."))
        self.assertNotIn("G" * MAX_TEXT_CHARS, lines[1])
        # The plan keeps its head, cut to the room left; the older runs past MAX_RUNS are never lines at all.
        self.assertTrue(lines[2].startswith(f"- Plan todo \"{'P' * MAX_TODO_TITLE_CHARS}\" (plan stage accepted): 0/{MAX_TODO_ITEMS}"))
        self.assertTrue(lines[2].endswith("…"))
        # Three runs and the plan were lines; two of them were listed.
        self.assertEqual(lines[3], "- 2 more record line(s) not listed.")
        self.assertEqual(len(lines), 4)

    def test_at_most_max_runs_runs_are_named(self) -> None:
        with homes() as home:
            for index in range(5):
                stored_run(home, [node("a")], run=f"r{index}", goal="")
            text = facts(home)
        self.assertEqual(sum(1 for line in text.splitlines() if line.startswith("- dag-ulw run")), 3)
        self.assertNotIn("more record line", text)

    def test_a_full_plan_alone_fits_whole(self) -> None:
        with homes() as home:
            stored_todo(home, [{"text": "T" * MAX_TODO_TEXT_CHARS, "state": "pending"} for _ in range(MAX_TODO_ITEMS)],
                        title="P" * MAX_TODO_TITLE_CHARS, plan_stage="accepted", deferred_reason="wait")
            text = facts(home)
        self.assertLessEqual(len(text), MAX_WORK_STATE_CHARS)
        line = text.splitlines()[1]
        self.assertEqual(line.count("pending: "), 10)
        self.assertTrue(line.endswith(f"; {MAX_TODO_ITEMS - 10} more open."))
        self.assertEqual(len(text.splitlines()), 2)

    def test_a_full_run_alone_fits_whole(self) -> None:
        with homes() as home:
            stored_run(home, [node(f"node-{step:02d}-{'x' * 23}", label="L" * dag_run.MAX_LABEL_CHARS)
                              for step in range(dag_run.MAX_NODES)], goal="G" * dag_run.MAX_GOAL_CHARS)
            text = facts(home)
        self.assertLessEqual(len(text), MAX_WORK_STATE_CHARS)
        self.assertEqual(len(text.splitlines()), 2)
        self.assertTrue(text.endswith(f"; {dag_run.MAX_NODES - 6} more."))


class FactsOnlyTests(unittest.TestCase):
    """The text is source material: it asks nothing and never touches the bot's persona."""

    def test_the_facts_ask_for_nothing_and_leave_the_persona_alone(self) -> None:
        with homes() as home:
            soul = home.hermes / "SOUL.md"
            soul.write_text("You are Kami. Always answer in Korean with a warm voice.\n", encoding="utf-8")
            before = soul.read_bytes()
            stored_run(home, [node("api"), node("docs", depends_on=("api",))])
            stored_todo(home, [{"text": "Wire it", "state": "active"}])
            preserved = provider_for(home).on_pre_compress([{"role": "user"}] * 3)
            self.assertEqual(soul.read_bytes(), before)
        self.assertTrue(preserved)
        self.assertNotIn("Kami", preserved)
        lowered = preserved.lower()
        for word in (*_REQUEST_WORDS, *_PERSONA_WORDS):
            self.assertNotIn(word, lowered)


if __name__ == "__main__":
    unittest.main()
