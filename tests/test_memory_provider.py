"""OMH's memory blocks, dreaming scheduler, eviction plan, and Hermes provider.

The defect these close is that everything OMH knew about memory had to be asked
for. Hermes wrote its own memory after every turn through
``agent/background_review.py`` with no statement of what OMH already held, and
OMH could only notice afterwards that some entry matched no record it kept.

Three boundaries are load-bearing enough to be pinned here rather than described:

- A block value is OMH's own content and is returned in full. A Hermes memory
  entry is not, and never appears outside a count or a hash.
- The provider never runs consolidation. It decides that consolidation is due
  and writes a brief; a model does the rest.
- The provider is not permitted to take a memory-provider slot another product
  holds, because Hermes runs exactly one.
"""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from _cli_harness import run_cli
from _local_package import load_local_package

load_local_package()
from omh.install.config_adapter import (
    clear_memory_provider,
    memory_provider_selection,
    set_memory_provider,
)
from omh.plugin_bundle.omh import register
from omh.plugin_bundle.omh.memory_blocks import (
    DEFAULT_BLOCK_LIMIT_CHARS,
    MemoryBlockError,
    approve_memory_block,
    build_memory_block,
    delete_memory_block,
    read_memory_block,
    read_memory_blocks,
    render_block_index,
    render_memory_blocks,
    select_memory_blocks,
    write_memory_block,
)
from omh.plugin_bundle.omh.memory_dreaming import (
    DEFAULT_TURN_INTERVAL,
    clear_after_consolidation,
    consolidation_reasons,
    empty_dreaming_state,
    read_dreaming_state,
    read_latest_consolidation,
    record_compaction,
    record_memory_write,
    record_turn,
    write_dreaming_state,
)
from omh.plugin_bundle.omh.memory_eviction import build_eviction_plan, eviction_plan_summary
from omh.plugin_bundle.omh.memory_provider import PROVIDER_NAME, OmhMemoryProvider
from omh.plugin_bundle.omh.metadata import MEMORY_PROVIDER_NAME
from omh.plugin_bundle.omh.tools.memory_tool import MEMORY_ACTIONS, OMH_MEMORY_SCHEMA, omh_memory_handler

HERMES_DELIMITER = "§"


def _write_hermes_memory(hermes_home: Path, *entries: str) -> Path:
    path = hermes_home / "memories" / "MEMORY.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(HERMES_DELIMITER.join(entries), encoding="utf-8")
    return path


class BlockStoreTests(unittest.TestCase):
    def test_a_block_round_trips_through_disk(self) -> None:
        with TemporaryDirectory() as tmp:
            block = build_memory_block("project-facts", "OMH wraps Hermes.", description="Facts.")
            write_memory_block(tmp, block)
            self.assertEqual(read_memory_blocks(tmp), (block,))

    def test_an_over_limit_block_is_rejected_rather_than_truncated(self) -> None:
        # Truncating would make the store disagree with what the caller believes
        # it wrote, and the disagreement only shows up as a missing sentence later.
        with self.assertRaises(MemoryBlockError):
            build_memory_block("facts", "x" * 51, limit=50)

    def test_labels_are_constrained_because_they_name_files(self) -> None:
        for label in ("", "Has Caps", "../escape", "-leading", "a" * 64):
            with self.subTest(label=label), self.assertRaises(MemoryBlockError):
                build_memory_block(label, "value")

    def test_an_unknown_tier_is_rejected(self) -> None:
        with self.assertRaises(MemoryBlockError):
            build_memory_block("facts", "value", tier="archival")

    def test_blocks_are_read_in_label_order_so_a_render_is_reproducible(self) -> None:
        with TemporaryDirectory() as tmp:
            for label in ("zulu", "alpha", "mike"):
                write_memory_block(tmp, build_memory_block(label, "v"))
            self.assertEqual([block.label for block in read_memory_blocks(tmp)], ["alpha", "mike", "zulu"])

    def test_tiers_are_stored_and_listed_separately(self) -> None:
        with TemporaryDirectory() as tmp:
            write_memory_block(tmp, build_memory_block("always", "v", tier="system"))
            write_memory_block(tmp, build_memory_block("sometimes", "v", tier="reference"))
            self.assertEqual([b.label for b in read_memory_blocks(tmp, tier="system")], ["always"])
            self.assertEqual([b.label for b in read_memory_blocks(tmp, tier="reference")], ["sometimes"])
            self.assertEqual(len(read_memory_blocks(tmp)), 2)

    def test_an_unreadable_block_is_absent_rather_than_fatal(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "memory" / "blocks" / "system" / "broken.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{not json", encoding="utf-8")
            self.assertIsNone(read_memory_block(path))
            self.assertEqual(read_memory_blocks(tmp), ())

    def test_removing_a_block_reports_whether_it_was_there(self) -> None:
        with TemporaryDirectory() as tmp:
            write_memory_block(tmp, build_memory_block("facts", "v"))
            self.assertTrue(delete_memory_block(tmp, "facts", "system"))
            self.assertFalse(delete_memory_block(tmp, "facts", "system"))


class RenderTests(unittest.TestCase):
    def test_a_render_shows_the_model_how_full_each_block_is(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            block = approve_memory_block(build_memory_block("facts", "abc", description="What we know.", limit=100))
            write_memory_block(home, block)
            selection = select_memory_blocks((block,), omh_home=home)
            rendered = render_memory_blocks([block], evaluations=selection.evaluations)
            self.assertIn("<memory_blocks>", rendered)
            self.assertIn("chars_current=3 chars_limit=100", rendered)
            self.assertIn("<value>abc</value>", rendered)

    def test_an_empty_store_renders_nothing_at_all(self) -> None:
        self.assertEqual(render_memory_blocks([]), "")
        self.assertEqual(render_block_index([]), "")

    def test_the_budget_drops_whole_blocks_and_says_which(self) -> None:
        # A clipped block would read as something the store actually holds.
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            blocks = [approve_memory_block(build_memory_block(f"b{index}", "x" * 200)) for index in range(5)]
            for block in blocks:
                write_memory_block(home, block)
            selection = select_memory_blocks(blocks, omh_home=home)
            rendered = render_memory_blocks(blocks, budget_chars=400, evaluations=selection.evaluations)
            self.assertIn("render_budget_exhausted", rendered)
            self.assertNotIn("b4", rendered)
            self.assertNotIn("<b4>", rendered)

    def test_the_index_lists_reference_blocks_without_their_values(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            block = approve_memory_block(
                build_memory_block("runbook", "SECRET-VALUE", description="How to deploy.", tier="reference")
            )
            write_memory_block(home, block)
            selection = select_memory_blocks((block,), omh_home=home)
            index = render_block_index([block], evaluations=selection.evaluations)
            self.assertIn('label="runbook"', index)
            self.assertIn("How to deploy.", index)
            self.assertNotIn("SECRET-VALUE", index)


class DreamingScheduleTests(unittest.TestCase):
    def test_counters_round_trip_and_survive_a_corrupt_file(self) -> None:
        with TemporaryDirectory() as tmp:
            write_dreaming_state(tmp, record_turn(empty_dreaming_state()))
            self.assertEqual(read_dreaming_state(tmp)["turns_since_consolidation"], 1)
            (Path(tmp) / "memory" / "dreaming.json").write_text("{", encoding="utf-8")
            self.assertEqual(read_dreaming_state(tmp), empty_dreaming_state())

    def test_the_turn_interval_is_the_baseline_trigger(self) -> None:
        state = empty_dreaming_state()
        for _ in range(DEFAULT_TURN_INTERVAL - 1):
            state = record_turn(state)
        self.assertEqual(consolidation_reasons(state), [])
        state = record_turn(state)
        self.assertTrue(any(reason.startswith("turn_interval_reached") for reason in consolidation_reasons(state)))

    def test_compaction_triggers_consolidation_on_its_own(self) -> None:
        reasons = consolidation_reasons(record_compaction(empty_dreaming_state()))
        self.assertIn("context_compaction_observed", reasons)

    def test_low_headroom_triggers_before_the_file_is_full(self) -> None:
        reasons = consolidation_reasons(empty_dreaming_state(), headroom_chars=100, headroom_floor_chars=300)
        self.assertTrue(any(reason.startswith("headroom_below_floor") for reason in reasons))

    def test_reasons_are_named_so_a_brief_can_state_its_own_cause(self) -> None:
        reasons = consolidation_reasons(record_compaction(empty_dreaming_state()), duplicate_count=2)
        self.assertIn("context_compaction_observed", reasons)
        self.assertIn("duplicate_records:2", reasons)

    def test_mode_off_silences_every_trigger(self) -> None:
        state = record_compaction(empty_dreaming_state())
        self.assertEqual(consolidation_reasons(state, mode="off", headroom_chars=0), [])

    def test_memory_writes_are_counted_separately_from_turns(self) -> None:
        state = record_memory_write(record_turn(empty_dreaming_state()))
        self.assertEqual(state["turns_since_consolidation"], 1)
        self.assertEqual(state["memory_writes_observed"], 1)


class StandingConditionSuppressionTests(unittest.TestCase):
    """A condition nobody can clear must not be reported on every turn.

    Observed on a live install: 19 consecutive briefs, every one of them reading
    `headroom_below_floor:289<=300`. Turn counts and compaction flags clear
    themselves by firing; headroom clears only when somebody consolidates, and
    OMH cannot -- by design. So the condition re-fired forever and the journal
    filled with one repeated sentence.
    """

    HEADROOM = 289
    FLOOR = 300

    def test_a_standing_condition_is_reported_once_not_every_turn(self) -> None:
        state = empty_dreaming_state()
        fired = 0
        for _ in range(20):
            state = record_turn(state)
            reasons = consolidation_reasons(state, headroom_chars=self.HEADROOM, headroom_floor_chars=self.FLOOR)
            if reasons:
                fired += 1
                state = clear_after_consolidation(state, at="t", reasons=reasons)
        # Once on the first turn, then only when the interval genuinely comes
        # due. Twenty briefs in twenty turns is what this replaced.
        self.assertEqual(fired, 4)

    def test_the_condition_still_rides_along_on_a_real_trigger(self) -> None:
        # Suppression must not hide it: a brief woken by the interval while
        # memory is nearly full should still say memory is nearly full.
        state = clear_after_consolidation(
            empty_dreaming_state(), at="t", reasons=[f"headroom_below_floor:{self.HEADROOM}<={self.FLOOR}"]
        )
        for _ in range(DEFAULT_TURN_INTERVAL):
            state = record_turn(state)
        reasons = consolidation_reasons(state, headroom_chars=self.HEADROOM, headroom_floor_chars=self.FLOOR)
        self.assertTrue(any(r.startswith("turn_interval_reached") for r in reasons))
        self.assertTrue(any(r.startswith("headroom_below_floor") for r in reasons))

    def test_a_changed_condition_fires_immediately(self) -> None:
        state = clear_after_consolidation(
            empty_dreaming_state(), at="t", reasons=[f"headroom_below_floor:{self.HEADROOM}<={self.FLOOR}"]
        )
        self.assertEqual(consolidation_reasons(state, headroom_chars=self.HEADROOM, headroom_floor_chars=self.FLOOR), [])
        self.assertTrue(consolidation_reasons(state, headroom_chars=self.HEADROOM - 40, headroom_floor_chars=self.FLOOR))

    def test_duplicate_and_expiry_counts_are_conditions_too(self) -> None:
        for reason, kwargs in (
            ("duplicate_records:2", {"duplicate_count": 2}),
            ("expiring_records:3", {"expiring_count": 3}),
        ):
            with self.subTest(reason=reason):
                state = clear_after_consolidation(empty_dreaming_state(), at="t", reasons=[reason])
                self.assertEqual(consolidation_reasons(state, **kwargs), [])

    def test_every_event_reason_may_fire_again_at_once(self) -> None:
        # These describe a moment, and the moment happened again.
        compaction = clear_after_consolidation(empty_dreaming_state(), at="t", reasons=["context_compaction_observed"])
        self.assertIn("context_compaction_observed", consolidation_reasons(record_compaction(compaction)))

        turns = clear_after_consolidation(
            empty_dreaming_state(), at="t", reasons=[f"turn_interval_reached:{DEFAULT_TURN_INTERVAL}/{DEFAULT_TURN_INTERVAL}"]
        )
        for _ in range(DEFAULT_TURN_INTERVAL):
            turns = record_turn(turns)
        self.assertTrue(any(r.startswith("turn_interval_reached") for r in consolidation_reasons(turns)))

    def test_a_session_ending_still_reports_its_unconsolidated_turns(self) -> None:
        state = clear_after_consolidation(
            empty_dreaming_state(), at="t", reasons=["session_ending_with_unconsolidated_turns:3"]
        )
        state = record_turn(record_turn(record_turn(state)))
        reasons = consolidation_reasons(state, session_ending=True)
        self.assertIn("session_ending_with_unconsolidated_turns:3", reasons)

    def test_the_provider_stops_rewriting_the_same_brief(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_hermes_memory(root / ".hermes", "x" * 2100)
            provider = OmhMemoryProvider(root / ".omh")
            provider.initialize("s", hermes_home=str(root / ".hermes"), agent_context="primary")
            journal = root / ".omh" / "memory" / "consolidation.jsonl"

            for turn in range(1, DEFAULT_TURN_INTERVAL):
                provider.on_turn_start(turn, "hi")
            # One brief from `initialize`; the standing condition adds no more
            # until the interval genuinely comes due.
            self.assertEqual(len(journal.read_text(encoding="utf-8").splitlines()), 1)


class EvictionPlanTests(unittest.TestCase):
    def test_rewordings_of_one_fact_group_into_a_single_cluster(self) -> None:
        entries = (
            "document-harness는 sionic-ai 레포의 에이전트 하네스 기반 문서 작성 시스템이다",
            "document-harness: sionic-ai 레포의 에이전트 하네스 기반 문서 작성 시스템",
            "커피 원두는 밀봉 용기에 보관한다",
        )
        plan = build_eviction_plan(entries, cap=2200)
        self.assertEqual(len(plan["duplicate_clusters"]), 1)
        self.assertEqual(plan["duplicate_clusters"][0]["entry_indices"], [0, 1])
        self.assertGreater(plan["reclaimable_chars"], 0)

    def test_distinct_entries_produce_no_cluster(self) -> None:
        plan = build_eviction_plan(("release 스크립트 dry-run", "커피 원두 보관"), cap=2200)
        self.assertEqual(plan["duplicate_clusters"], [])
        self.assertEqual(plan["reclaimable_chars"], 0)

    def test_a_shortfall_counts_the_delimiter_the_write_will_cost(self) -> None:
        plan = build_eviction_plan(("x" * 90,), cap=100, required_chars=10)
        # 90 used, 10 free, and the write needs 10 + 1 for the delimiter.
        self.assertEqual(plan["headroom_chars"], 10)
        self.assertEqual(plan["required_chars"], 11)
        self.assertEqual(plan["shortfall_chars"], 1)

    def test_a_plan_that_cannot_free_enough_says_so(self) -> None:
        plan = build_eviction_plan(("x" * 99,), cap=100, required_chars=500)
        self.assertFalse(plan["sufficient"])
        self.assertIn("provably redundant", eviction_plan_summary(plan))

    def test_an_unexplained_entry_is_never_an_eviction_candidate(self) -> None:
        # Unexplained is a reason to ask, not a reason to delete.
        plan = build_eviction_plan(("a fact nothing in OMH explains",), cap=2200)
        self.assertTrue(plan["unexplained_entries_are_not_candidates"])
        self.assertEqual(plan["duplicate_clusters"], [])

    def test_the_plan_carries_no_entry_text(self) -> None:
        secret = "루트 비밀번호는 hunter2 이다"
        plan = build_eviction_plan((secret, secret + " 확실히"), cap=2200)
        self.assertNotIn("hunter2", json.dumps(plan, ensure_ascii=False))


class ProviderRegistrationTests(unittest.TestCase):
    class _Collector:
        """Mirrors Hermes' `_ProviderCollector`: one real method, the rest no-ops."""

        def __init__(self) -> None:
            self.provider = None
            self.tools: list[str] = []

        def register_memory_provider(self, provider) -> None:
            self.provider = provider

        def register_tool(self, *args, **kwargs) -> None:
            self.tools.append(args[0] if args else "")

        def register_hook(self, *args, **kwargs) -> None:
            pass

    class _PluginCtx:
        """Mirrors the real Hermes plugin context, which has no provider method."""

        def __init__(self) -> None:
            self.tools: list[str] = []
            self.hooks: list[str] = []

        def register_tool(self, name, *args, **kwargs) -> None:
            self.tools.append(name)

        def register_hook(self, name, callback) -> None:
            self.hooks.append(name)

    def test_the_memory_loader_gets_a_provider_and_no_tools(self) -> None:
        collector = self._Collector()
        register(collector)
        self.assertIsInstance(collector.provider, OmhMemoryProvider)
        # Registering ten tools into a collector that discards them is work the
        # provider load should never do.
        self.assertEqual(collector.tools, [])

    def test_the_plugin_loader_still_gets_every_tool_and_hook(self) -> None:
        ctx = self._PluginCtx()
        register(ctx)
        self.assertIn("omh_memory", ctx.tools)
        self.assertEqual(len(ctx.tools), 10)
        self.assertIn("on_session_end", ctx.hooks)

    def test_the_provider_exposes_no_tool_schemas(self) -> None:
        # `agent/memory_provider.py` names tool-schema bloat as the reason only
        # one external provider may run; the block read lives on `omh_memory`.
        self.assertEqual(OmhMemoryProvider().get_tool_schemas(), [])

    def test_the_provider_name_matches_what_config_must_carry(self) -> None:
        self.assertEqual(OmhMemoryProvider().name, MEMORY_PROVIDER_NAME)
        self.assertEqual(PROVIDER_NAME, MEMORY_PROVIDER_NAME)


class ProviderLifecycleTests(unittest.TestCase):
    def _provider(self, root: Path, *, agent_context: str = "primary") -> OmhMemoryProvider:
        provider = OmhMemoryProvider(root / ".omh")
        provider.initialize("session-1", hermes_home=str(root / ".hermes"), agent_context=agent_context)
        return provider

    def test_availability_is_a_local_check_with_no_network(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertFalse(OmhMemoryProvider(root / "absent").is_available())
            (root / ".omh").mkdir()
            self.assertTrue(OmhMemoryProvider(root / ".omh").is_available())

    def test_prefetch_serves_a_pack_rendered_off_the_hot_path(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_memory_block(root / ".omh", approve_memory_block(build_memory_block("facts", "OMH wraps Hermes.")))
            provider = self._provider(root)
            self.assertIn("OMH wraps Hermes.", provider.prefetch("anything"))

            # A block written mid-session is not served until the next turn is
            # queued, which is where the base class puts the work.
            write_memory_block(root / ".omh", approve_memory_block(build_memory_block("later", "added mid-session")))
            self.assertNotIn("added mid-session", provider.prefetch(""))
            provider.queue_prefetch("")
            self.assertIn("added mid-session", provider.prefetch(""))

    def test_reference_blocks_reach_prefetch_as_labels_not_values(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_memory_block(
                root / ".omh",
                approve_memory_block(build_memory_block("runbook", "SECRET-VALUE", description="How to deploy.", tier="reference")),
            )
            pack = self._provider(root).prefetch("")
            self.assertIn("runbook", pack)
            self.assertIn("How to deploy.", pack)
            self.assertNotIn("SECRET-VALUE", pack)

    def test_a_memory_write_is_journalled_without_its_text(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = self._provider(root)
            secret = "루트 비밀번호는 hunter2 이다"
            provider.on_memory_write("add", "memory", secret, {"write_origin": "background_review"})

            journal = (root / ".omh" / "memory" / "write_journal.jsonl").read_text(encoding="utf-8")
            self.assertNotIn("hunter2", journal)
            entry = json.loads(journal.splitlines()[0])
            self.assertEqual(entry["action"], "add")
            self.assertEqual(entry["chars"], len(secret))
            self.assertEqual(entry["write_origin"], "background_review")
            self.assertEqual(entry["redaction_policy"], "metadata_only")

    def test_a_non_primary_context_moves_no_counters(self) -> None:
        # Hermes states that cron and subagent contexts must not write; letting
        # them would move the counters that decide when consolidation is due.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = self._provider(root, agent_context="cron")
            provider.on_turn_start(1, "hello")
            provider.on_memory_write("add", "memory", "text")
            self.assertEqual(read_dreaming_state(root / ".omh"), empty_dreaming_state())

    def test_compaction_hands_back_system_blocks_and_consolidates_at_once(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_memory_block(root / ".omh", approve_memory_block(build_memory_block("facts", "must survive compaction")))
            provider = self._provider(root)
            preserved = provider.on_pre_compress([{"role": "user", "content": "hi"}])

            self.assertIn("must survive compaction", preserved)
            # The flag is cleared because the brief was written here rather than
            # deferred; waiting would put it after the material it describes.
            self.assertFalse(read_dreaming_state(root / ".omh")["compaction_pending"])
            self.assertTrue((root / ".omh" / "memory" / "consolidation.json").exists())

    def test_consolidation_writes_a_brief_only_when_it_is_due(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = self._provider(root)
            handoff_path = root / ".omh" / "memory" / "consolidation.json"

            self.assertFalse(provider.consolidation_due()["due"])
            self.assertFalse(handoff_path.exists())

            for turn in range(1, DEFAULT_TURN_INTERVAL + 1):
                provider.on_turn_start(turn, "hello")
            self.assertTrue(handoff_path.exists())
            # The interval fired on the turn itself and reset the counters, so
            # asking again straight after finds nothing further due.
            self.assertEqual(read_dreaming_state(root / ".omh")["turns_since_consolidation"], 0)
            self.assertFalse(provider.consolidation_due()["due"])

    def test_the_brief_never_claims_consolidation_happened(self) -> None:
        with TemporaryDirectory() as tmp:
            provider = self._provider(Path(tmp))
            boundary = str(provider.consolidation_due()["claim_boundary"])
            self.assertIn("not evidence", boundary)

    def test_headroom_pressure_reaches_the_scheduler_from_hermes(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_hermes_memory(root / ".hermes", "x" * 2100)
            self._provider(root)

            # The pressure is picked up by the evaluation `initialize` already
            # runs, so the brief exists before anything else asks. Asking again
            # finds the same standing condition suppressed rather than restated.
            brief = json.loads((root / ".omh" / "memory" / "consolidation.json").read_text(encoding="utf-8"))
            self.assertTrue(any(str(r).startswith("headroom_below_floor") for r in brief["reasons"]))
            self.assertEqual(brief["eviction_plan"]["cap"], 2200)

    def test_a_read_only_home_costs_a_journal_line_not_the_turn(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = self._provider(root)
            with patch("omh.plugin_bundle.omh.memory_provider._append_bounded_json_line", side_effect=OSError("read-only")):
                provider.on_memory_write("add", "memory", "text")  # must not raise


class LossPreventionTests(unittest.TestCase):
    """The four moments memory can be lost, and that each one leaves a brief.

    The first implementation evaluated only at `on_session_end`. Turns and
    compaction set counters nobody read until then, so a laptop closed
    mid-session wrote nothing at all and a turn interval that came due at turn 5
    waited for whenever the session happened to stop. These pin the fix.
    """

    def _provider(self, root: Path, session: str = "s1") -> OmhMemoryProvider:
        provider = OmhMemoryProvider(root / ".omh")
        provider.initialize(session, hermes_home=str(root / ".hermes"), agent_context="primary")
        return provider

    def _briefs(self, root: Path) -> list[dict]:
        path = root / ".omh" / "memory" / "consolidation.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []

    def test_the_turn_interval_fires_mid_session_not_at_the_end(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = self._provider(root)
            for turn in range(1, DEFAULT_TURN_INTERVAL):
                provider.on_turn_start(turn, "hi")
            self.assertEqual(self._briefs(root), [])

            provider.on_turn_start(DEFAULT_TURN_INTERVAL, "hi")
            briefs = self._briefs(root)
            self.assertEqual(len(briefs), 1)
            self.assertEqual(briefs[0]["trigger"], "turn")

    def test_the_interval_keeps_firing_on_every_further_cycle(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = self._provider(root)
            for turn in range(1, DEFAULT_TURN_INTERVAL * 2 + 1):
                provider.on_turn_start(turn, "hi")
            self.assertEqual(len(self._briefs(root)), 2)

    def test_compaction_writes_its_brief_before_the_messages_go(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = self._provider(root)
            provider.on_turn_start(1, "hi")
            provider.on_pre_compress([{"role": "user", "content": "x"}] * 40)

            briefs = self._briefs(root)
            self.assertEqual(len(briefs), 1)
            self.assertEqual(briefs[0]["trigger"], "compaction")
            self.assertEqual(briefs[0]["messages_at_risk"], 40)
            self.assertIn("about to discard", briefs[0]["requested_of_executor"][0])

    def test_shutdown_consolidates_even_below_the_interval(self) -> None:
        # Three turns and a closed lid would otherwise leave nothing behind: the
        # interval assumes a later turn, and a closing session has none.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = self._provider(root)
            for turn in range(1, 4):
                provider.on_turn_start(turn, "hi")
            provider.shutdown()

            briefs = self._briefs(root)
            self.assertEqual(len(briefs), 1)
            self.assertEqual(briefs[0]["trigger"], "shutdown")
            self.assertIn("session_ending_with_unconsolidated_turns:3", briefs[0]["reasons"])

    def test_session_end_consolidates_even_below_the_interval(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = self._provider(root)
            provider.on_turn_start(1, "hi")
            provider.on_session_end([])
            self.assertEqual(self._briefs(root)[0]["trigger"], "session_end")

    def test_a_session_that_died_is_settled_when_the_next_one_starts(self) -> None:
        # A killed process reaches no hook at all. The counters are on disk, so
        # the next startup is the first moment anything can act on them.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            died = self._provider(root, "dead-session")
            for turn in range(1, 4):
                died.on_turn_start(turn, "hi")
            self.assertEqual(self._briefs(root), [])
            del died

            self._provider(root, "next-session")
            briefs = self._briefs(root)
            self.assertEqual(len(briefs), 1)
            self.assertEqual(briefs[0]["trigger"], "session_start_recovery")
            self.assertIn("closed laptop", briefs[0]["requested_of_executor"][0])

    def test_a_clean_start_recovers_nothing_and_says_nothing(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._provider(root)
            self.assertEqual(self._briefs(root), [])

    def test_briefs_accumulate_so_an_earlier_one_is_never_overwritten(self) -> None:
        # The compaction brief describes material that is already gone; losing
        # it to a later shutdown brief would defeat the point.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = self._provider(root)
            provider.on_turn_start(1, "hi")
            provider.on_pre_compress([{"role": "user"}])
            provider.on_turn_start(2, "hi")
            provider.shutdown()

            triggers = [brief["trigger"] for brief in self._briefs(root)]
            self.assertEqual(triggers, ["compaction", "shutdown"])
            latest = json.loads((root / ".omh" / "memory" / "consolidation.json").read_text(encoding="utf-8"))
            self.assertEqual(latest["trigger"], "shutdown")

    def test_a_fired_trigger_does_not_immediately_refire(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = self._provider(root)
            for turn in range(1, DEFAULT_TURN_INTERVAL + 1):
                provider.on_turn_start(turn, "hi")
            self.assertEqual(len(self._briefs(root)), 1)
            provider.on_session_end([])
            self.assertEqual(len(self._briefs(root)), 1)

    def test_a_non_primary_context_never_writes_a_brief(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = OmhMemoryProvider(root / ".omh")
            provider.initialize("cron-1", hermes_home=str(root / ".hermes"), agent_context="cron")
            for turn in range(1, DEFAULT_TURN_INTERVAL + 2):
                provider.on_turn_start(turn, "hi")
            provider.on_pre_compress([{"role": "user"}])
            provider.shutdown()
            self.assertEqual(self._briefs(root), [])


class MemoryToolActionTests(unittest.TestCase):
    def _call(self, root: Path, **args) -> dict:
        with patch.dict(os.environ, {"OMH_HOME": str(root / ".omh"), "HERMES_HOME": str(root / ".hermes")}):
            return json.loads(omh_memory_handler(args))

    def test_the_default_action_is_still_the_bridge(self) -> None:
        with TemporaryDirectory() as tmp:
            payload = self._call(Path(tmp).resolve())
            self.assertEqual(payload["action"], "status")
            self.assertEqual(payload["schema_version"], "hermes_memory_bridge/v1")

    def test_every_advertised_action_is_handled(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            for action in MEMORY_ACTIONS:
                with self.subTest(action=action):
                    self.assertEqual(self._call(root, action=action)["action"], action)

    def test_the_schema_advertises_exactly_the_handled_actions(self) -> None:
        enum = OMH_MEMORY_SCHEMA["parameters"]["properties"]["action"]["enum"]
        self.assertEqual(tuple(enum), MEMORY_ACTIONS)

    def test_blocks_lists_labels_and_read_returns_the_value(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            write_memory_block(root / ".omh", approve_memory_block(build_memory_block("runbook", "deploy steps", tier="reference")))

            listing = self._call(root, action="blocks")
            self.assertEqual(listing["block_count"], 1)
            self.assertNotIn("deploy steps", json.dumps(listing))

            read = self._call(root, action="read", label="runbook")
            self.assertTrue(read["found"])
            self.assertEqual(read["block"]["value"], "deploy steps")

    def test_a_missing_block_is_a_stated_miss_not_an_empty_value(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            self.assertEqual(self._call(root, action="read", label="absent")["reason"], "unknown_label")
            self.assertEqual(self._call(root, action="read")["reason"], "label_required")

    def test_an_unknown_action_names_what_is_supported(self) -> None:
        with TemporaryDirectory() as tmp:
            payload = self._call(Path(tmp).resolve(), action="delete-everything")
            self.assertEqual(payload["status"], "unavailable")
            self.assertEqual(tuple(payload["supported_actions"]), MEMORY_ACTIONS)

    def test_hermes_entry_text_still_never_reaches_the_payload(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            secret = "루트비밀번호는hunter2이다"
            _write_hermes_memory(root / ".hermes", secret)
            for action in MEMORY_ACTIONS:
                with self.subTest(action=action):
                    self.assertNotIn(secret, json.dumps(self._call(root, action=action), ensure_ascii=False))


class ProviderSlotTests(unittest.TestCase):
    def test_the_slot_is_taken_when_it_is_free(self) -> None:
        change = set_memory_provider("memory:\n  memory_char_limit: 2200\n", "omh")
        self.assertTrue(change.changed)
        self.assertEqual(memory_provider_selection(change.text), "omh")

    def test_a_config_without_a_memory_section_grows_one(self) -> None:
        change = set_memory_provider("plugins:\n  enabled:\n    - omh\n", "omh")
        self.assertTrue(change.changed)
        self.assertEqual(memory_provider_selection(change.text), "omh")

    def test_an_empty_provider_key_is_treated_as_free(self) -> None:
        change = set_memory_provider("memory:\n  provider: ''\n", "omh")
        self.assertTrue(change.changed)
        self.assertEqual(memory_provider_selection(change.text), "omh")

    def test_another_product_holding_the_slot_is_never_overwritten(self) -> None:
        # Hermes runs one external provider, so a silent overwrite would switch
        # off whatever the operator actually chose.
        original = "memory:\n  provider: honcho\n"
        change = set_memory_provider(original, "omh")
        self.assertFalse(change.changed)
        self.assertEqual(change.text, original)
        self.assertIn("honcho", change.message)

    def test_taking_a_slot_omh_already_holds_is_a_no_op(self) -> None:
        self.assertFalse(set_memory_provider("memory:\n  provider: omh\n", "omh").changed)

    def test_only_omh_may_release_the_slot_omh_took(self) -> None:
        self.assertTrue(clear_memory_provider("memory:\n  provider: omh\n", "omh").changed)
        self.assertFalse(clear_memory_provider("memory:\n  provider: honcho\n", "omh").changed)
        self.assertFalse(clear_memory_provider("memory:\n  provider: ''\n", "omh").changed)

    def test_a_provider_key_in_another_section_is_not_mistaken_for_this_one(self) -> None:
        self.assertEqual(memory_provider_selection("image_gen:\n  provider: openai\n"), "")


class ProviderClaimTests(unittest.TestCase):
    def test_memory_mode_off_never_writes_the_provider(self) -> None:
        from omh.install.config_adapter import maybe_set_memory_provider

        change = maybe_set_memory_provider("plugins:\n  enabled:\n    - omh\n", "omh", "off")
        self.assertFalse(change.changed)
        self.assertNotIn("provider", change.text)

    def test_memory_mode_off_preserves_an_existing_provider(self) -> None:
        from omh.install.config_adapter import maybe_set_memory_provider

        original = "memory:\n  provider: honcho\n"
        change = maybe_set_memory_provider(original, "omh", "off")
        self.assertFalse(change.changed)
        self.assertEqual(change.text, original)

    def test_memory_mode_full_still_writes_the_provider(self) -> None:
        from omh.install.config_adapter import maybe_set_memory_provider

        change = maybe_set_memory_provider("plugins:\n  enabled:\n    - omh\n", "omh", "full")
        self.assertTrue(change.changed)
        self.assertIn("provider: omh", change.text)


class MemoryCliTests(unittest.TestCase):
    def _base(self, root: Path) -> list[str]:
        return ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]

    @staticmethod
    def _json(result: tuple[int, str, str]) -> tuple[int, dict, str]:
        status, stdout, stderr = result
        return status, (json.loads(stdout) if stdout.strip() else {}), stderr

    def test_a_block_can_be_written_listed_and_removed_from_the_cli(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = self._base(root)
            status, payload, stderr = self._json(run_cli(base + ["memory", "block-set", "facts", "--value", "OMH wraps Hermes."]))
            self.assertEqual(status, 0, stderr)
            self.assertTrue(payload["written"])

            status, payload, _ = self._json(run_cli(base + ["memory", "blocks"]))
            self.assertEqual(status, 0)
            self.assertEqual(payload["block_count"], 1)
            self.assertEqual(payload["blocks"][0]["label"], "facts")

            status, payload, _ = self._json(run_cli(base + ["memory", "block-remove", "facts"]))
            self.assertEqual(status, 0)
            self.assertTrue(payload["removed"])

    def test_an_over_limit_block_fails_the_command_rather_than_truncating(self) -> None:
        with TemporaryDirectory() as tmp:
            status, _, stderr = run_cli(
                self._base(Path(tmp)) + ["memory", "block-set", "facts", "--value", "x" * 40, "--limit", "10"]
            )
            self.assertNotEqual(status, 0)
            self.assertIn("40 chars", stderr)

    def test_the_listing_can_be_narrowed_to_one_tier(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = self._base(root)
            self._json(run_cli(base + ["memory", "block-set", "always", "--value", "v", "--tier", "system"]))
            self._json(run_cli(base + ["memory", "block-set", "sometimes", "--value", "v", "--tier", "reference"]))
            _, payload, _ = self._json(run_cli(base + ["memory", "blocks", "--tier", "reference"]))
            self.assertEqual([block["label"] for block in payload["blocks"]], ["sometimes"])

    def test_dream_reports_without_evaluating_unless_asked(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            status, payload, stderr = self._json(run_cli(self._base(root) + ["memory", "dream"]))
            self.assertEqual(status, 0, stderr)
            self.assertFalse(payload["evaluated"])
            self.assertNotIn("due", payload)
            self.assertFalse((root / ".omh" / "memory" / "consolidation.json").exists())

    def test_dream_evaluate_weighs_the_triggers_and_never_consolidates(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_hermes_memory(root / ".hermes", "x" * 2100)
            status, payload, stderr = self._json(run_cli(self._base(root) + ["memory", "dream", "--evaluate"]))
            self.assertEqual(status, 0, stderr)
            self.assertIn("not evidence that memory was consolidated", payload["claim_boundary"])
            # The brief lands on disk whether or not this particular call is the
            # one that weighed the trigger: `initialize` evaluates first, and a
            # standing condition is not restated once it has been reported.
            self.assertTrue((root / ".omh" / "memory" / "consolidation.json").is_file())

            # Asking twice does not write twice, which is the whole point.
            before = (root / ".omh" / "memory" / "consolidation.jsonl").read_text(encoding="utf-8")
            run_cli(self._base(root) + ["memory", "dream", "--evaluate"])
            self.assertEqual((root / ".omh" / "memory" / "consolidation.jsonl").read_text(encoding="utf-8"), before)

    def test_the_provider_slot_can_be_taken_and_handed_back(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = self._base(root)
            status, payload, stderr = self._json(run_cli(base + ["memory", "provider", "--enable"]))
            self.assertEqual(status, 0, stderr)
            self.assertTrue(payload["is_omh"])

            _, payload, _ = self._json(run_cli(base + ["memory", "provider"]))
            self.assertEqual(payload["provider"], MEMORY_PROVIDER_NAME)
            self.assertFalse(payload["changed"])

            _, payload, _ = self._json(run_cli(base + ["memory", "provider", "--disable"]))
            self.assertTrue(payload["changed"])
            self.assertFalse(payload["is_omh"])

    def test_enabling_never_evicts_another_product_from_the_slot(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / ".hermes" / "config.yaml"
            config.parent.mkdir(parents=True, exist_ok=True)
            config.write_text("memory:\n  provider: honcho\n", encoding="utf-8")

            status, payload, stderr = self._json(run_cli(self._base(root) + ["memory", "provider", "--enable"]))
            self.assertEqual(status, 0, stderr)
            self.assertFalse(payload["changed"])
            self.assertEqual(payload["provider"], "honcho")
            self.assertEqual(config.read_text(encoding="utf-8"), "memory:\n  provider: honcho\n")

    def test_a_dry_run_reports_the_change_without_writing_config(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            status, payload, stderr = self._json(run_cli(self._base(root) + ["memory", "provider", "--enable", "--dry-run"]))
            self.assertEqual(status, 0, stderr)
            self.assertTrue(payload["changed"])
            self.assertFalse((root / ".hermes" / "config.yaml").exists())


class DoctorSlotReportTests(unittest.TestCase):
    """A slot held by something else is why OMH's hooks would not be running."""

    def _doctor(self, root: Path) -> dict:
        status, stdout, stderr = run_cli(
            ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes"), "doctor"]
        )
        self.assertIn(status, (0, 1), stderr)
        return json.loads(stdout)

    def _message(self, payload: dict) -> str:
        return next(
            str(check["message"]) for check in payload["checks"] if check["name"] == "memory_provider"
        )

    def test_an_off_state_points_at_a_command_ordinary_users_know(self) -> None:
        # `omh setup` claims a free slot, so this is what an unset one means --
        # and setup is one of the three commands AGENTS.md says people should
        # need. Naming `omh memory provider --enable` here would send them to
        # the control plane for something setup already does.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".hermes").mkdir(parents=True)
            (root / ".hermes" / "config.yaml").write_text("memory:\n  provider: ''\n", encoding="utf-8")
            message = self._message(self._doctor(root))
            self.assertIn("omh setup", message)
            self.assertNotIn("omh memory provider", message)

    def test_a_slot_held_by_another_product_reads_as_working_not_broken(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".hermes").mkdir(parents=True)
            (root / ".hermes" / "config.yaml").write_text("memory:\n  provider: honcho\n", encoding="utf-8")
            message = self._message(self._doctor(root))
            self.assertIn("honcho", message)
            self.assertIn("not a fault", message)

    def test_omh_holding_the_slot_reads_as_healthy(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".hermes").mkdir(parents=True)
            (root / ".hermes" / "config.yaml").write_text("memory:\n  provider: omh\n", encoding="utf-8")
            self.assertIn("OMH memory is on", self._message(self._doctor(root)))


class SetupTurnsMemoryOnTests(unittest.TestCase):
    """A capability that needs a control-plane command is one most people never get.

    AGENTS.md says ordinary users should only need `omh setup`, `omh update`,
    and `omh doctor`. The provider first shipped requiring `omh memory provider
    --enable`, which put it outside that set entirely. Setup claims the slot now
    -- but only when it is free.
    """

    def _base(self, root: Path) -> list[str]:
        return ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]

    def test_setup_turns_memory_on_when_the_slot_is_free(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            status, stdout, stderr = run_cli(self._base(root) + ["setup"])
            self.assertEqual(status, 0, stderr)
            self.assertEqual(json.loads(stdout)["steps"]["apply"]["memory_provider"]["selected"], MEMORY_PROVIDER_NAME)
            self.assertIn("provider: omh", (root / ".hermes" / "config.yaml").read_text(encoding="utf-8"))

    def test_setup_never_takes_a_slot_another_product_holds(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / ".hermes" / "config.yaml"
            config.parent.mkdir(parents=True, exist_ok=True)
            config.write_text("memory:\n  provider: honcho\n", encoding="utf-8")

            status, stdout, stderr = run_cli(self._base(root) + ["setup"])
            self.assertEqual(status, 0, stderr)
            provider = json.loads(stdout)["steps"]["apply"]["memory_provider"]
            self.assertFalse(provider["changed"])
            self.assertEqual(provider["selected"], "honcho")
            self.assertIn("provider: honcho", config.read_text(encoding="utf-8"))

    def test_setup_is_idempotent_on_the_slot(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_cli(self._base(root) + ["setup"])
            _, stdout, _ = run_cli(self._base(root) + ["setup"])
            provider = json.loads(stdout)["steps"]["apply"]["memory_provider"]
            self.assertFalse(provider["changed"])
            self.assertEqual(provider["selected"], MEMORY_PROVIDER_NAME)

    def test_a_dry_run_setup_writes_no_provider_selection(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            status, _, stderr = run_cli(self._base(root) + ["setup", "--dry-run"])
            self.assertEqual(status, 0, stderr)
            self.assertFalse((root / ".hermes" / "config.yaml").exists())

    def test_the_summary_tells_the_user_memory_is_on(self) -> None:
        # The JSON payload is for wrappers; this line is what a person reads.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, stdout, _ = run_cli(self._base(root) + ["setup"], output_json=False)
            self.assertIn("Memory: OMH remembers across sessions", stdout)

    def test_the_summary_explains_an_off_state_rather_than_staying_silent(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / ".hermes" / "config.yaml"
            config.parent.mkdir(parents=True, exist_ok=True)
            config.write_text("memory:\n  provider: honcho\n", encoding="utf-8")
            _, stdout, _ = run_cli(self._base(root) + ["setup"], output_json=False)
            self.assertIn("honcho", stdout)
            self.assertIn("OMH memory stays off", stdout)

    def test_an_operator_can_still_hand_the_slot_back(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_cli(self._base(root) + ["setup"])
            status, stdout, stderr = run_cli(self._base(root) + ["memory", "provider", "--disable"])
            self.assertEqual(status, 0, stderr)
            self.assertTrue(json.loads(stdout)["changed"])
            self.assertFalse(json.loads(stdout)["is_omh"])


class DoctorSurfacesTheBriefTests(unittest.TestCase):
    """The scheduler's decision has to reach a human somewhere.

    A brief was written to `consolidation.json` and nothing read it back, so
    OMH knew memory was nearly full and said so only to itself. Doctor is where
    an operator already looks.

    It is a warning, never a fault: OMH cannot run the consolidation, and it
    cannot tell whether Hermes already did.
    """

    def _checks(self, root: Path) -> dict[str, dict]:
        status, stdout, stderr = run_cli(
            ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes"), "doctor"]
        )
        self.assertIn(status, (0, 1), stderr)
        return {check["name"]: check for check in json.loads(stdout)["checks"]}

    def _fire_a_brief(self, root: Path) -> None:
        _write_hermes_memory(root / ".hermes", "x" * 2100)
        provider = OmhMemoryProvider(root / ".omh")
        provider.initialize("s", hermes_home=str(root / ".hermes"), agent_context="primary")

    def test_a_pending_brief_is_reported_with_its_reasons(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._fire_a_brief(root)
            check = self._checks(root)["memory_consolidation"]
            self.assertEqual(check["severity"], "warning")
            self.assertIn("headroom_below_floor", check["message"])
            self.assertIn("consolidat", check["message"].lower())

    def test_a_pending_brief_never_fails_the_install(self) -> None:
        # OMH cannot run the consolidation and cannot tell whether Hermes has,
        # so an outstanding brief is a thing to know, not a thing that is broken.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._fire_a_brief(root)
            self.assertTrue(self._checks(root)["memory_consolidation"]["ok"])

    def test_no_brief_reads_as_nothing_pending(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            check = self._checks(root)["memory_consolidation"]
            self.assertEqual(check["severity"], "ok")
            self.assertIn("No memory consolidation is pending", check["message"])

    def test_an_unreadable_brief_reads_as_nothing_pending(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / ".omh" / "memory" / "consolidation.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{not json", encoding="utf-8")
            self.assertEqual(self._checks(root)["memory_consolidation"]["severity"], "ok")

    def test_a_brief_that_was_not_due_is_not_reported_as_pending(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = OmhMemoryProvider(root / ".omh")
            provider.initialize("s", hermes_home=str(root / ".hermes"), agent_context="primary")
            # Nothing fired, so no brief was written at all.
            self.assertEqual(self._checks(root)["memory_consolidation"]["severity"], "ok")

    def test_the_reader_is_defensive_about_the_schema(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "memory" / "consolidation.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"schema_version": "something_else/v1"}), encoding="utf-8")
            self.assertIsNone(read_latest_consolidation(tmp))


class ChatNoticeOnEveryMessengerTests(unittest.TestCase):
    """A pending consolidation brief reaches chat, whatever the messenger.

    `omh doctor` surfaced the brief for people who run commands. Someone talking
    to Hermes from Slack or Telegram never runs commands, so for them the brief
    did not exist. The notice attaches at the one seam every chat surface passes
    through, so covering the seam covers Slack, Telegram, Discord, CLI, and
    desktop at once.

    The review pass on the first version confirmed two failures by execution:
    a schema-valid brief whose ``reasons`` was an int crashed every chat turn,
    and nothing ever retired a brief, so the notice suffixed every reply
    forever. Both are pinned here now.
    """

    NOTICE_KO = "기억 정리가 밀려 있습니다"
    NOTICE_EN = "Memory tidy-up is pending"
    KO_MESSAGE = "이 레포에 기능 하나 안전하게 추가하고 싶어"

    def _due_paths(self, root: Path):
        from omh.paths import resolve_paths

        memories = root / ".hermes" / "memories"
        memories.mkdir(parents=True, exist_ok=True)
        (memories / "MEMORY.md").write_text("x" * 2100, encoding="utf-8")
        provider = OmhMemoryProvider(root / ".omh")
        provider.initialize("s", hermes_home=str(root / ".hermes"), agent_context="primary")
        return provider, resolve_paths(root / ".omh", root / ".hermes")

    def _payload(self, paths, source: str, message: str | None = None) -> dict:
        from omh.wrapper.contract import build_chat_interaction_payload

        return build_chat_interaction_payload(message or self.KO_MESSAGE, source=source, paths=paths)

    def test_every_chat_source_carries_the_notice_in_its_rendered_body(self) -> None:
        from omh.ingress import CHAT_SOURCES

        with TemporaryDirectory() as tmp:
            _, paths = self._due_paths(Path(tmp))
            for source in sorted(CHAT_SOURCES):
                with self.subTest(source=source):
                    payload = self._payload(paths, source)
                    notice = payload.get("memory_consolidation_notice")
                    self.assertIsInstance(notice, dict)
                    self.assertIn("not evidence", str(notice["claim_boundary"]))
                    self.assertTrue(notice["raised_at"])
                    self.assertIn(self.NOTICE_KO, str(payload["chat_response"]["body"]))
                    # Unconditional on purpose: a vacuous isinstance guard here
                    # is exactly the regression this assertion exists to catch.
                    rendering = payload["chat_response"]["messenger_rendering"]
                    self.assertIn(self.NOTICE_KO, str(rendering["body_text"]))

    def test_the_notice_speaks_the_language_of_the_card(self) -> None:
        # The routed card's copy is localized; an English suffix on a Korean
        # body reads as a glitch. Same brief, two messages, two languages.
        with TemporaryDirectory() as tmp:
            _, paths = self._due_paths(Path(tmp))
            korean = str(self._payload(paths, "slack")["chat_response"]["body"])
            english = str(self._payload(paths, "slack", "I want to add a feature safely")["chat_response"]["body"])
            self.assertIn(self.NOTICE_KO, korean)
            self.assertNotIn(self.NOTICE_EN, korean)
            self.assertIn(self.NOTICE_EN, english)
            self.assertNotIn(self.NOTICE_KO, english)

    def test_the_routed_card_is_not_displaced(self) -> None:
        # Additive means additive: same kind, same headline, one extra sentence.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            from omh.paths import resolve_paths

            clean = resolve_paths(root / ".clean-omh", root / ".clean-hermes")
            control = self._payload(clean, "slack")["chat_response"]
            _, paths = self._due_paths(root)
            noticed = self._payload(paths, "slack")["chat_response"]
            self.assertEqual(noticed["kind"], control["kind"])
            self.assertEqual(noticed["headline"], control["headline"])
            self.assertTrue(str(noticed["body"]).startswith(str(control["body"])))

    def test_no_brief_means_no_notice_anywhere(self) -> None:
        with TemporaryDirectory() as tmp:
            from omh.paths import resolve_paths

            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            payload = self._payload(paths, "telegram")
            self.assertNotIn("memory_consolidation_notice", payload)
            self.assertNotIn(self.NOTICE_KO, str(payload["chat_response"]["body"]))

    def test_a_malformed_brief_never_takes_down_a_turn(self) -> None:
        # The first version crashed here: valid JSON, right schema string,
        # reasons an int -- and the TypeError escaped through every messenger.
        cases = (
            {"schema_version": "omh_memory_consolidation_handoff/v1", "due": True, "reasons": 5},
            {"schema_version": "omh_memory_consolidation_handoff/v1", "due": True, "reasons": None},
            {"schema_version": "omh_memory_consolidation_handoff/v1", "due": True, "reasons": "headroom"},
            {"schema_version": "omh_memory_consolidation_handoff/v1", "due": True, "reasons": {"a": 1}},
            "{not json",
        )
        for case in cases:
            with self.subTest(case=str(case)[:40]), TemporaryDirectory() as tmp:
                from omh.paths import resolve_paths

                root = Path(tmp)
                broken = root / ".omh" / "memory" / "consolidation.json"
                broken.parent.mkdir(parents=True, exist_ok=True)
                broken.write_text(case if isinstance(case, str) else json.dumps(case), encoding="utf-8")
                payload = self._payload(resolve_paths(root / ".omh", root / ".hermes"), "slack")
                self.assertNotIn("memory_consolidation_notice", payload)

    def test_the_notice_retires_once_consolidation_is_observed(self) -> None:
        # A Hermes memory write is what an actual consolidation looks like from
        # here. Before: the brief was never rewritten, so the notice suffixed
        # every reply forever, including after the user complied.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider, paths = self._due_paths(root)
            self.assertIn("memory_consolidation_notice", self._payload(paths, "slack"))

            (root / ".hermes" / "memories" / "MEMORY.md").write_text("short note", encoding="utf-8")
            provider.on_memory_write("replace", "memory", "short note")

            payload = self._payload(paths, "slack")
            self.assertNotIn("memory_consolidation_notice", payload)
            self.assertNotIn(self.NOTICE_KO, str(payload["chat_response"]["body"]))
            brief = json.loads((root / ".omh" / "memory" / "consolidation.json").read_text(encoding="utf-8"))
            self.assertFalse(brief["due"])
            self.assertEqual(brief["superseded_by_trigger"], "memory_write")

    def test_the_notice_persists_while_the_condition_still_holds(self) -> None:
        # Suppression (#700) stops repeated briefs; it must not retire one. A
        # memory write that does NOT clear the pressure keeps the notice alive.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider, paths = self._due_paths(root)
            provider.on_turn_start(1, "hi")
            provider.on_memory_write("add", "memory", "still full")
            self.assertIn("memory_consolidation_notice", self._payload(paths, "slack"))

    def test_an_interval_brief_survives_the_turn_after_it_fired(self) -> None:
        # Event reasons clear themselves by firing -- the counter resets -- so
        # "nothing standing" one turn later is not evidence anyone consolidated.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            from omh.paths import resolve_paths

            memories = root / ".hermes" / "memories"
            memories.mkdir(parents=True, exist_ok=True)
            (memories / "MEMORY.md").write_text("plenty of headroom", encoding="utf-8")
            provider = OmhMemoryProvider(root / ".omh")
            provider.initialize("s", hermes_home=str(root / ".hermes"), agent_context="primary")
            for turn in range(1, DEFAULT_TURN_INTERVAL + 2):
                provider.on_turn_start(turn, "hi")
            paths = resolve_paths(root / ".omh", root / ".hermes")
            self.assertIn("memory_consolidation_notice", self._payload(paths, "slack"))

    def test_messenger_copy_carries_no_filesystem_paths(self) -> None:
        # A Slack channel is a shared surface; a local path in the body leaks
        # the operator's machine layout to everyone in it. The structured
        # notice is wrapper-facing and equally shared, so it is scanned too.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, paths = self._due_paths(root)
            payload = self._payload(paths, "slack")
            for surface in (str(payload["chat_response"]["body"]), json.dumps(payload["memory_consolidation_notice"])):
                self.assertNotIn(str(root), surface)
                self.assertNotIn("/Users/", surface)
                self.assertNotIn(".omh", surface)

    def test_the_cached_pathless_call_stays_notice_free(self) -> None:
        # The cache key excludes any OMH home, so a cached payload must never
        # carry state it could not have read.
        from omh.wrapper.contract import build_chat_interaction_payload

        payload = build_chat_interaction_payload("hello", source="slack")
        self.assertNotIn("memory_consolidation_notice", payload)

    def test_the_real_plugin_tool_carries_it_on_both_paths(self) -> None:
        from omh.plugin_bundle.omh.tools.chat_tool import omh_interact_handler

        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            self._due_paths(root)
            with patch.dict(os.environ, {"OMH_HOME": str(root / ".omh"), "HERMES_HOME": str(root / ".hermes")}):
                for record_session in (True, False):
                    with self.subTest(record_session=record_session):
                        out = json.loads(
                            omh_interact_handler(
                                {
                                    "message": "PR 하나 올리고 싶은데 도와줘",
                                    "source": "slack",
                                    "record_session": record_session,
                                    "omh_home": str(root / ".omh"),
                                    "hermes_home": str(root / ".hermes"),
                                }
                            )
                        )
                        self.assertIn("memory_consolidation_notice", out)
                        self.assertIn(self.NOTICE_KO, str(out["chat_response"]["body"]))


class RetirementSignalTests(unittest.TestCase):
    """Only a consolidation-shaped write may retire a brief.

    The re-review reproduced the gap: an interval-raised brief has its counters
    cleared at birth, so under trigger-only gating ANY memory write one moment
    later looked like consolidation and erased the notice before anyone could
    act. Hermes documents its write actions as add/replace/remove; an 'add'
    appends new material and consolidates nothing, while 'replace' and 'remove'
    are what a merge or prune actually emits.
    """

    def _interval_brief(self, root: Path) -> OmhMemoryProvider:
        memories = root / ".hermes" / "memories"
        memories.mkdir(parents=True, exist_ok=True)
        (memories / "MEMORY.md").write_text("plenty of headroom", encoding="utf-8")
        provider = OmhMemoryProvider(root / ".omh")
        provider.initialize("s", hermes_home=str(root / ".hermes"), agent_context="primary")
        for turn in range(1, DEFAULT_TURN_INTERVAL + 1):
            provider.on_turn_start(turn, "hi")
        return provider

    def _due(self, root: Path) -> bool:
        brief = read_latest_consolidation(root / ".omh")
        return bool(brief and brief["due"])

    def test_an_unrelated_add_write_never_retires_a_brief(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = self._interval_brief(root)
            self.assertTrue(self._due(root))
            provider.on_memory_write("add", "memory", "an unrelated single fact")
            self.assertTrue(self._due(root))

    def test_a_consolidating_write_retires_when_nothing_stands(self) -> None:
        with TemporaryDirectory() as tmp:
            for action in ("replace", "remove"):
                with self.subTest(action=action):
                    root = Path(tmp) / action
                    provider = self._interval_brief(root)
                    provider.on_memory_write(action, "memory", "merged entries")
                    self.assertFalse(self._due(root))
                    brief = read_latest_consolidation(root / ".omh")
                    self.assertEqual(brief["superseded_by_trigger"], "memory_write")

    def test_a_consolidating_write_does_not_retire_while_pressure_remains(self) -> None:
        # A 'replace' that fails to clear the condition is not a consolidation
        # worth retiring over -- the store is still full.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            memories = root / ".hermes" / "memories"
            memories.mkdir(parents=True, exist_ok=True)
            (memories / "MEMORY.md").write_text("x" * 2100, encoding="utf-8")
            provider = OmhMemoryProvider(root / ".omh")
            provider.initialize("s", hermes_home=str(root / ".hermes"), agent_context="primary")
            provider.on_memory_write("replace", "memory", "still full afterwards")
            self.assertTrue(self._due(root))

    def test_writes_do_not_reraise_briefs_or_reset_the_turn_counter(self) -> None:
        # The first retirement path routed writes through the full evaluation:
        # every write below the headroom floor re-raised a brief (the embedded
        # value changes, so suppression never held) and reset the turn counter,
        # starving the interval trigger and growing the journal per write.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            memories = root / ".hermes" / "memories"
            memories.mkdir(parents=True, exist_ok=True)
            (memories / "MEMORY.md").write_text("x" * 2100, encoding="utf-8")
            provider = OmhMemoryProvider(root / ".omh")
            provider.initialize("s", hermes_home=str(root / ".hermes"), agent_context="primary")
            for turn in range(1, 4):
                provider.on_turn_start(turn, "hi")
            journal = root / ".omh" / "memory" / "consolidation.jsonl"
            turns_before = read_dreaming_state(root / ".omh")["turns_since_consolidation"]
            records_before = len(journal.read_text(encoding="utf-8").splitlines())

            for index in range(5):
                (memories / "MEMORY.md").write_text("x" * (2100 + index), encoding="utf-8")
                provider.on_memory_write("add", "memory", f"fact {index}")

            self.assertEqual(read_dreaming_state(root / ".omh")["turns_since_consolidation"], turns_before)
            self.assertEqual(len(journal.read_text(encoding="utf-8").splitlines()), records_before)

    def test_a_not_due_inspection_carries_no_raised_at(self) -> None:
        # Stamping the inspection object gave it a raise time for a raise that
        # never happened.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = OmhMemoryProvider(root / ".omh")
            provider.initialize("s", hermes_home=str(root / ".hermes"), agent_context="primary")
            handoff = provider.consolidation_due()
            self.assertFalse(handoff["due"])
            self.assertEqual(handoff["raised_at"], "")


class ConsolidationResetsTheClockTests(unittest.TestCase):
    """A session whose work WAS the consolidation must end quiet.

    Observed live: Hermes consolidated MEMORY.md (six removes, two adds,
    1921 -> 1122 chars), the headroom brief retired mid-session -- and then the
    session ended and raised `session_ending_with_unconsolidated_turns:1`,
    because `turns_since_consolidation` reset only when a BRIEF fired, never
    when the consolidation itself did. Every tidy-up ended by requesting the
    next one.
    """

    def _consolidating_session(self, root: Path) -> OmhMemoryProvider:
        memories = root / ".hermes" / "memories"
        memories.mkdir(parents=True, exist_ok=True)
        (memories / "MEMORY.md").write_text("x" * 2100, encoding="utf-8")
        provider = OmhMemoryProvider(root / ".omh")
        provider.initialize("s", hermes_home=str(root / ".hermes"), agent_context="primary")
        provider.on_turn_start(1, "기억 정리해줘")
        (memories / "MEMORY.md").write_text("consolidated" * 20, encoding="utf-8")
        for _ in range(3):
            provider.on_memory_write("remove", "memory", "")
        provider.on_memory_write("add", "memory", "merged summary")
        return provider

    def test_a_consolidating_write_restarts_the_turn_clock(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._consolidating_session(root)
            state = read_dreaming_state(root / ".omh")
            self.assertEqual(state["turns_since_consolidation"], 0)
            self.assertFalse(state["compaction_pending"])

    def test_the_session_that_consolidated_ends_without_raising(self) -> None:
        # The live failure: retirement worked mid-session, then the session's
        # own exit re-raised. Both halves are asserted.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = self._consolidating_session(root)
            self.assertFalse(read_latest_consolidation(root / ".omh")["due"])
            provider.on_session_end([])
            self.assertFalse(read_latest_consolidation(root / ".omh")["due"])

    def test_a_session_that_did_not_consolidate_still_raises_at_exit(self) -> None:
        # Loss prevention is the reason the session-ending bar exists; a plain
        # append is not a consolidation and must not silence it.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".hermes" / "memories").mkdir(parents=True)
            (root / ".hermes" / "memories" / "MEMORY.md").write_text("small", encoding="utf-8")
            provider = OmhMemoryProvider(root / ".omh")
            provider.initialize("s", hermes_home=str(root / ".hermes"), agent_context="primary")
            provider.on_turn_start(1, "hi")
            provider.on_memory_write("add", "memory", "a new fact")
            provider.on_session_end([])
            brief = read_latest_consolidation(root / ".omh")
            self.assertTrue(brief["due"])
            self.assertIn("session_ending_with_unconsolidated_turns:1", brief["reasons"])

    def test_turns_after_the_consolidation_count_from_zero(self) -> None:
        # The interval restarts at the consolidation, not at the last brief.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = self._consolidating_session(root)
            for turn in range(2, DEFAULT_TURN_INTERVAL + 1):
                provider.on_turn_start(turn, "hi")
            self.assertFalse(read_latest_consolidation(root / ".omh")["due"])
            provider.on_turn_start(DEFAULT_TURN_INTERVAL + 1, "hi")
            self.assertTrue(read_latest_consolidation(root / ".omh")["due"])


class NoticeLocaleCoverageTests(unittest.TestCase):
    """The notice speaks every locale the copy system supports, gated."""

    def test_the_notice_tables_cover_every_supported_locale(self) -> None:
        # This repo gates parallel tables so a new locale cannot silently
        # regress the notice to English; this is that gate.
        from omh.wrapper.localized_copy import (
            _CONSOLIDATION_FALLBACK_SUMMARY,
            _CONSOLIDATION_NOTICE_SENTENCES,
            _CONSOLIDATION_REASON_PHRASES,
            SUPPORTED_COPY_LOCALES,
        )

        expected = set(SUPPORTED_COPY_LOCALES)
        self.assertEqual(set(_CONSOLIDATION_NOTICE_SENTENCES), expected)
        self.assertEqual(set(_CONSOLIDATION_FALLBACK_SUMMARY), expected)
        for family, phrases in _CONSOLIDATION_REASON_PHRASES.items():
            self.assertEqual(set(phrases), expected, family)

    def test_latin_script_messages_get_their_own_sentence(self) -> None:
        # The re-review round-tripped every card body through the detector and
        # found es/fr/de all fell back to English: the Latin-script hints are
        # user-question phrases that declarative card copy never contains. The
        # locale now comes from the user's message -- the same input the card
        # copy itself localized from.
        from omh.paths import resolve_paths
        from omh.wrapper.contract import build_chat_interaction_payload

        cases = (
            ("¿Puedes ayudarme? quiero añadir una función", "La consolidación de memoria está pendiente"),
            ("Peux-tu m'aider à ajouter une fonctionnalité ?", "Le rangement de la mémoire est en attente"),
            ("Kannst du mir helfen, eine Funktion hinzuzufügen?", "Das Aufräumen des Gedächtnisses steht aus"),
        )
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            memories = root / ".hermes" / "memories"
            memories.mkdir(parents=True, exist_ok=True)
            (memories / "MEMORY.md").write_text("x" * 2100, encoding="utf-8")
            OmhMemoryProvider(root / ".omh").initialize("s", hermes_home=str(root / ".hermes"), agent_context="primary")
            paths = resolve_paths(root / ".omh", root / ".hermes")
            for message, marker in cases:
                with self.subTest(message=message[:24]):
                    payload = build_chat_interaction_payload(message, source="slack", paths=paths)
                    self.assertIn(marker, str(payload["chat_response"]["body"]))


class BlockBudgetDefaultTests(unittest.TestCase):
    def test_the_default_block_limit_fits_beside_hermes_own_cap(self) -> None:
        # A block that alone exceeded Hermes' 2200-char memory file would make
        # the always-rendered tier the largest thing in the turn.
        self.assertLessEqual(DEFAULT_BLOCK_LIMIT_CHARS, 2200)


if __name__ == "__main__":
    unittest.main()


# --- record expiry classifier (memory-expiry-retirement todo 1) ---

import time as _time
from datetime import datetime as _datetime, timedelta, timezone as _timezone

from omh.plugin_bundle.omh.hermes_memory import classify_record_expiry, count_record_expiry

_EXPIRY_NOW = _datetime(2026, 7, 28, 12, 0, 0, tzinfo=_timezone.utc)


def _write_expiry_record(
    omh_home: Path,
    record_id: str,
    expires_at: str | None,
    *,
    include_ttl: bool = True,
    status: str = "approved",
    schema: str = "project_memory_record/v1",
) -> Path:
    directory = omh_home / "memory" / "records"
    directory.mkdir(parents=True, exist_ok=True)
    record: dict = {
        "schema_version": schema,
        "review_status": status,
        "record_id": record_id,
        "summary": "expiry fixture",
    }
    if include_ttl:
        record["ttl"] = {"ttl_days": 1, "expires_at": expires_at}
    path = directory / f"{record_id}.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


class ExpiryClassifierTests(unittest.TestCase):
    def _record(self, expires_at: str | None = None, *, include_ttl: bool = True) -> dict:
        record: dict = {
            "schema_version": "project_memory_record/v1",
            "review_status": "approved",
            "record_id": "mem_fixture",
        }
        if include_ttl:
            record["ttl"] = {"ttl_days": 1, "expires_at": expires_at}
        return record

    def test_classifier_states_and_exact_boundary(self) -> None:
        self.assertEqual(classify_record_expiry(self._record("2026-07-28T11:59:59Z"), now=_EXPIRY_NOW), "expired")
        # The exact boundary expires_at == now is expired: same <= operator as recall.
        self.assertEqual(classify_record_expiry(self._record("2026-07-28T12:00:00Z"), now=_EXPIRY_NOW), "expired")
        self.assertEqual(classify_record_expiry(self._record("2026-07-30T12:00:00Z"), now=_EXPIRY_NOW), "expiring")
        # Window edge: now + 7d exactly is still expiring.
        self.assertEqual(classify_record_expiry(self._record("2026-08-04T12:00:00Z"), now=_EXPIRY_NOW), "expiring")
        self.assertEqual(classify_record_expiry(self._record("2026-08-04T12:00:01Z"), now=_EXPIRY_NOW), "fresh")
        self.assertEqual(classify_record_expiry(self._record(""), now=_EXPIRY_NOW), "no_ttl")
        self.assertEqual(classify_record_expiry(self._record(include_ttl=False), now=_EXPIRY_NOW), "no_ttl")
        self.assertEqual(classify_record_expiry(self._record("not-a-date"), now=_EXPIRY_NOW), "malformed")

    def test_naive_timestamps_read_as_utc_under_any_host_timezone(self) -> None:
        naive_expired = self._record("2026-07-28T11:00:00")
        naive_fresh = self._record("2026-09-01T00:00:00")
        original = os.environ.get("TZ")
        try:
            results = []
            for tz in ("Pacific/Kiritimati", "Pacific/Niue"):
                os.environ["TZ"] = tz
                _time.tzset()
                results.append(
                    (
                        classify_record_expiry(naive_expired, now=_EXPIRY_NOW),
                        classify_record_expiry(naive_fresh, now=_EXPIRY_NOW),
                    )
                )
            self.assertEqual(results[0], results[1])
            self.assertEqual(results[0], ("expired", "fresh"))
        finally:
            if original is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = original
            _time.tzset()

    def test_count_record_expiry_counts_only_expiry_states(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp) / ".omh"
            _write_expiry_record(home, "mem_expired", "2026-07-28T00:00:00Z")
            _write_expiry_record(home, "mem_soon", "2026-07-30T00:00:00Z")
            _write_expiry_record(home, "mem_fresh", "2026-09-01T00:00:00Z")
            _write_expiry_record(home, "mem_malformed", "garbage")
            _write_expiry_record(home, "mem_no_ttl", None, include_ttl=False)
            _write_expiry_record(home, "mem_rejected", "2026-07-01T00:00:00Z", status="rejected")
            _write_expiry_record(home, "mem_wrong_schema", "2026-07-01T00:00:00Z", schema="other/v1")
            counts = count_record_expiry(home, now=_EXPIRY_NOW)
            self.assertEqual(counts, {"expired": 1, "expiring_soon": 1})


class RecordExpiryWiringTests(unittest.TestCase):
    def _provider(self, root: Path) -> OmhMemoryProvider:
        provider = OmhMemoryProvider(root / ".omh")
        provider.initialize("session-1", hermes_home=str(root / ".hermes"), agent_context="primary")
        return provider

    @staticmethod
    def _iso(moment: _datetime) -> str:
        return moment.replace(microsecond=0).isoformat().replace("+00:00", "Z")

    def _briefs(self, root: Path) -> tuple[dict, int]:
        home = root / ".omh" / "memory"
        latest = json.loads((home / "consolidation.json").read_text(encoding="utf-8"))
        lines = (home / "consolidation.jsonl").read_text(encoding="utf-8").splitlines()
        return latest, len([line for line in lines if line.strip()])

    def test_expiring_record_wakes_a_brief_with_record_expiry(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            soon = _datetime.now(_timezone.utc) + timedelta(days=3)
            _write_expiry_record(root / ".omh", "mem_soonfix", self._iso(soon))
            self._provider(root)
            latest, _count = self._briefs(root)
            self.assertTrue(latest["due"])
            self.assertIn("expiring_records:1", latest["reasons"])
            self.assertEqual(latest["record_expiry"], {"expired": 0, "expiring_soon": 1})

    def test_standing_expiry_never_blocks_brief_retirement(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            soon = _datetime.now(_timezone.utc) + timedelta(days=3)
            _write_expiry_record(root / ".omh", "mem_soonfix", self._iso(soon))
            provider = self._provider(root)
            latest, _count = self._briefs(root)
            self.assertTrue(latest["due"])
            provider.on_memory_write("replace", "memory", "merged entries", {"write_origin": "memory_tool"})
            self.assertFalse(read_latest_consolidation(root / ".omh")["due"])

    def test_expired_transition_refreshes_brief_without_new_notification(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            soon = _datetime.now(_timezone.utc) + timedelta(days=3)
            record_path = _write_expiry_record(root / ".omh", "mem_soonfix", self._iso(soon))
            provider = self._provider(root)
            _latest, lines_before = self._briefs(root)
            mutated = json.loads(record_path.read_text(encoding="utf-8"))
            mutated["ttl"]["expires_at"] = "2020-01-01T00:00:00Z"
            record_path.write_text(json.dumps(mutated), encoding="utf-8")
            provider.on_turn_start(2, "next turn")
            latest, lines_after = self._briefs(root)
            self.assertEqual(latest["record_expiry"], {"expired": 1, "expiring_soon": 0})
            self.assertTrue(latest["due"])
            self.assertEqual(lines_after, lines_before)

    def test_pre_change_brief_normalizes_record_expiry_to_zeros(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp) / ".omh"
            (home / "memory").mkdir(parents=True)
            (home / "memory" / "consolidation.json").write_text(
                json.dumps({"schema_version": "omh_memory_consolidation_handoff/v1", "due": True, "reasons": ["turn_interval_reached:5/5"]}),
                encoding="utf-8",
            )
            brief = read_latest_consolidation(home)
            self.assertEqual(brief["record_expiry"], {"expired": 0, "expiring_soon": 0})

    def test_expiry_scan_runs_once_per_evaluation_and_not_in_standing(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            soon = _datetime.now(_timezone.utc) + timedelta(days=3)
            _write_expiry_record(root / ".omh", "mem_soonfix", self._iso(soon))
            provider = self._provider(root)
            with patch(
                "omh.plugin_bundle.omh.memory_provider.count_record_expiry",
                return_value={"expired": 0, "expiring_soon": 1},
            ) as counter:
                provider.consolidation_due(trigger="manual")
                self.assertEqual(counter.call_count, 1)
                provider.on_memory_write("replace", "memory", "merged", {"write_origin": "memory_tool"})
                self.assertEqual(counter.call_count, 1)


class ReasonAwareOperatorSurfaceTests(unittest.TestCase):
    """Chat notice and doctor must name the remedy that actually fits the brief."""

    def _write_brief(self, root: Path, *, record_expiry: dict | None) -> None:
        home = root / ".omh" / "memory"
        home.mkdir(parents=True, exist_ok=True)
        brief: dict = {
            "schema_version": "omh_memory_consolidation_handoff/v1",
            "due": True,
            "reasons": ["expiring_records:2"],
            "raised_at": "2026-07-28T00:00:00Z",
            "trigger": "turn",
        }
        if record_expiry is not None:
            brief["record_expiry"] = record_expiry
        (home / "consolidation.json").write_text(json.dumps(brief), encoding="utf-8")

    def test_chat_next_action_forks_on_expired_records_in_both_fields(self) -> None:
        from omh.paths import resolve_paths
        from omh.wrapper.contract import build_chat_interaction_payload

        cases = [
            ({"expired": 2, "expiring_soon": 0}, "run_omh_memory_retire"),
            ({"expired": 0, "expiring_soon": 2}, "ask_hermes_to_consolidate_memory"),
            (None, "ask_hermes_to_consolidate_memory"),  # pre-change brief on disk
        ]
        for record_expiry, expected in cases:
            with self.subTest(record_expiry=record_expiry):
                with TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    (root / ".omh").mkdir()
                    self._write_brief(root, record_expiry=record_expiry)
                    paths = resolve_paths(root / ".omh", root / ".hermes")
                    payload = build_chat_interaction_payload("hello there", source="discord", paths=paths)
                    notice = payload["memory_consolidation_notice"]
                    self.assertEqual(notice["next_action"], expected)
                    state = payload["chat_response"]["state"]["memory_consolidation"]
                    self.assertEqual(state["next_action"], expected)

    def test_doctor_names_retire_only_when_expired_records_exist(self) -> None:
        from omh.maintenance.doctor import _memory_consolidation_check
        from omh.paths import resolve_paths

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".omh").mkdir()
            paths = resolve_paths(root / ".omh", root / ".hermes")

            self._write_brief(root, record_expiry={"expired": 2, "expiring_soon": 0})
            expired_check = _memory_consolidation_check(paths)
            self.assertEqual(expired_check.severity, "warning")
            self.assertIn("omh memory retire", expired_check.message)
            self.assertIn("2 expired record(s)", expired_check.message)

            self._write_brief(root, record_expiry={"expired": 0, "expiring_soon": 2})
            pending_check = _memory_consolidation_check(paths)
            self.assertNotIn("retire", pending_check.message)
            self.assertIn("consolidate", pending_check.message.lower())

            self._write_brief(root, record_expiry=None)
            legacy_check = _memory_consolidation_check(paths)
            self.assertNotIn("retire", legacy_check.message)


class BundleReplayAdmissionTests(unittest.TestCase):
    """Regression coverage for the final bundle replay boundaries."""

    def _approved_block(self, value: str, **kwargs):
        from omh.plugin_bundle.omh.memory_blocks import approve_memory_block

        return approve_memory_block(build_memory_block("reviewed", value, **kwargs))

    def test_unreviewed_default_system_block_is_staged_and_never_prefetched(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            value = "UNREVIEWED_SYSTEM_VALUE"
            path = write_memory_block(root / ".omh", build_memory_block("pending", value))
            provider = OmhMemoryProvider(root / ".omh")
            provider.initialize("session", hermes_home=root / ".hermes", agent_context="primary")

            self.assertIn("block_candidates", str(path))
            pack = provider.prefetch("")
            self.assertNotIn(value, pack)
            self.assertIn("review_required", pack)
            provider.queue_prefetch("")
            self.assertNotIn(value, provider.prefetch(""))
            self.assertIn("review_required", provider.on_pre_compress([]))

    def test_unreviewed_reference_block_never_returns_a_tool_value(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            value = "UNREVIEWED_REFERENCE_VALUE"
            write_memory_block(
                root / ".omh",
                build_memory_block("pending-ref", value, description="UNREVIEWED_REFERENCE_DESCRIPTION", tier="reference"),
            )

            listing = self._call_tool(root, action="blocks")
            self.assertEqual(listing["blocks"][0]["admission_status"], "pending_review")
            self.assertEqual(listing["blocks"][0]["replay"]["reason_code"], "review_required")
            payload = self._call_tool(root, action="read", label="pending-ref")
            self.assertTrue(payload["found"])
            self.assertFalse(payload["replay"]["eligible"])
            self.assertEqual(payload["replay"]["reason_code"], "review_required")
            self.assertNotIn(value, json.dumps(payload))
            self.assertNotIn("value", payload)
            pack = OmhMemoryProvider(root / ".omh").render_pack()
            self.assertNotIn(value, pack)
            self.assertNotIn("UNREVIEWED_REFERENCE_DESCRIPTION", pack)
            self.assertIn("review_required", pack)

    def test_missing_review_evidence_is_omitted_before_rendering(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            block = self._approved_block("MISSING_REVIEW_VALUE")
            write_memory_block(root / ".omh", block)
            review_path = root / ".omh" / "memory" / "block_reviews" / f"{block.admission['review_id']}.json"
            self.assertTrue(review_path.is_file())
            review_path.unlink()
            self.assertFalse(review_path.exists())

            pack = OmhMemoryProvider(root / ".omh").render_pack()
            self.assertNotIn("MISSING_REVIEW_VALUE", pack)
            self.assertIn("review_not_found", pack)

    def test_dreaming_only_prepares_stale_and_expired_volatile_reminders(self) -> None:
        from datetime import datetime, timedelta, timezone

        from omh.plugin_bundle.omh.memory_governance import build_retention

        now = datetime.now(timezone.utc)
        stale = approve_memory_block(
            build_memory_block("stale", "STALE_PRIVATE", revalidation={"deadline": "2000-01-01T00:00:00Z"})
        )
        expired = approve_memory_block(
            build_memory_block(
                "expired",
                "EXPIRED_PRIVATE",
                retention=build_retention("volatile", record_type="fact", admitted_at=now - timedelta(days=7)),
            )
        )
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            write_memory_block(root / ".omh", stale)
            write_memory_block(root / ".omh", expired)
            handoff = OmhMemoryProvider(root / ".omh").consolidation_due()
            self.assertIn("stale_review_required:1", handoff["reasons"])
            self.assertIn("expired_volatile_records:1", handoff["reasons"])
            self.assertIn("not evidence", handoff["claim_boundary"])
            self.assertNotIn("STALE_PRIVATE", json.dumps(handoff))
            self.assertNotIn("EXPIRED_PRIVATE", json.dumps(handoff))

    def test_manual_dreaming_reports_each_standing_replay_reminder_without_regular_triggers(self) -> None:
        from datetime import datetime, timedelta, timezone

        from omh.plugin_bundle.omh.memory_governance import build_retention

        now = datetime(2026, 7, 30, 12, tzinfo=timezone.utc)
        cases = (
            (
                "stale-only",
                "stale_review_required:1",
                approve_memory_block(
                    build_memory_block("stale-only", "STALE_ONLY_PRIVATE", revalidation={"deadline": "2026-07-30T11:59:59Z"})
                ),
            ),
            (
                "expired-volatile-only",
                "expired_volatile_records:1",
                approve_memory_block(
                    build_memory_block(
                        "expired-only",
                        "EXPIRED_ONLY_PRIVATE",
                        retention=build_retention("volatile", record_type="fact", admitted_at=now - timedelta(days=7)),
                    )
                ),
            ),
        )
        for name, expected_reason, block in cases:
            with self.subTest(name=name), TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                state = empty_dreaming_state()
                state["last_reasons"] = [expected_reason]
                write_dreaming_state(root / ".omh", state)
                path = write_memory_block(root / ".omh", block)
                before = path.read_bytes()

                handoff = OmhMemoryProvider(root / ".omh").consolidation_due(now=now)

                self.assertEqual(handoff["reasons"], [expected_reason])
                self.assertEqual(path.read_bytes(), before)
                self.assertNotIn("PRIVATE", json.dumps(handoff))

    def test_provider_applies_the_exact_volatile_boundary(self) -> None:
        from datetime import datetime, timedelta, timezone

        from omh.plugin_bundle.omh.memory_governance import build_retention

        now = datetime(2026, 7, 30, 12, tzinfo=timezone.utc)
        block = self._approved_block(
            "APPROVED_VOLATILE_VALUE",
            retention=build_retention("volatile", record_type="fact", admitted_at=now),
        )
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            write_memory_block(root / ".omh", block)
            provider = OmhMemoryProvider(root / ".omh")

            before = provider.render_pack(now=now + timedelta(days=7, microseconds=-1))
            at_boundary = provider.render_pack(now=now + timedelta(days=7))
            provider.queue_prefetch(now=now + timedelta(days=7))
            pre_compress = provider.on_pre_compress([], now=now + timedelta(days=7))
            self.assertIn("APPROVED_VOLATILE_VALUE", before)
            self.assertNotIn("APPROVED_VOLATILE_VALUE", at_boundary)
            self.assertIn("expired_volatile", at_boundary)
            self.assertNotIn("APPROVED_VOLATILE_VALUE", provider.prefetch(""))
            self.assertIn("expired_volatile", pre_compress)
            self.assertNotIn("APPROVED_VOLATILE_VALUE", pre_compress)

    def test_replay_reason_codes_are_distinct_and_metadata_only(self) -> None:
        from datetime import datetime, timedelta, timezone

        from omh.plugin_bundle.omh.memory_governance import build_retention

        now = datetime(2026, 7, 30, 12, tzinfo=timezone.utc)
        cases = {
            "stale": {"revalidation": {"deadline": "2026-07-30T11:59:59Z"}, "reason": "stale_review_required"},
            "expired": {
                "retention": build_retention("volatile", record_type="fact", admitted_at=now - timedelta(days=7)),
                "reason": "expired_volatile",
            },
            "tampered": {"tampered": True, "reason": "payload_digest_mismatch"},
            "superseded": {"superseded_by": {"revision": 2}, "reason": "superseded"},
            "tombstoned": {"tombstoned": True, "reason": "tombstoned"},
        }
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            for name, case in cases.items():
                with self.subTest(case=name):
                    options = {key: value for key, value in case.items() if key not in {"reason", "tampered", "tombstoned"}}
                    block = self._approved_block(f"PRIVATE_{name}", **options)
                    write_memory_block(home, block)
                    review_path = home / "memory" / "block_reviews" / f"{block.admission['review_id']}.json"
                    self.assertTrue(review_path.is_file())
                    if case.get("tampered"):
                        block = block.with_value(f"PRIVATE_{name}_CHANGED")
                    selection = select_memory_blocks(
                        (block,),
                        now=now,
                        omh_home=home,
                        tombstoned=bool(case.get("tombstoned")),
                    )
                    evaluation = selection.evaluations[block.block_id]
                    self.assertFalse(evaluation["eligible"])
                    self.assertEqual(evaluation["reason_code"], case["reason"])
                    self.assertNotIn(f"PRIVATE_{name}", json.dumps(selection.omissions))

    def test_provider_journals_stay_bounded_and_do_not_hash_content(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            provider = OmhMemoryProvider(root / ".omh")
            provider.initialize("session", hermes_home=root / ".hermes", agent_context="primary")
            for index in range(80):
                provider.on_memory_write(
                    "add",
                    "memory",
                    f"private {index}",
                    {
                        "record_identity": {
                            "schema_version": "project_memory_record/v2",
                            "id": "safe",
                            "id_key": "record_id",
                            "revision": 1,
                            "scope": {"kind": "project", "ref": "default"},
                        }
                    },
                )
                provider._write_handoff({"schema_version": "test/v1", "due": True, "sequence": index})

            journals = {}
            for name in ("write_journal.jsonl", "consolidation.jsonl"):
                lines = (root / ".omh" / "memory" / name).read_text(encoding="utf-8").splitlines()
                self.assertLessEqual(len(lines), 32)
                self.assertNotIn("private", "\n".join(lines))
                self.assertNotIn("sha256", "\n".join(lines))
                journals[name] = [json.loads(line) for line in lines]
            self.assertEqual(journals["write_journal.jsonl"][-1]["record_identity"]["id"], "safe")
            self.assertEqual(journals["consolidation.jsonl"][-1]["sequence"], 79)

    def test_legacy_v1_blocks_do_not_crash_consolidation_due_on_repeated_reads(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            omh_home = root / ".omh"
            fixtures = (
                (
                    "system",
                    "legacy-system-fact",
                    "Legacy system block",
                    "LEGACY_SYSTEM_VALUE",
                    1024,
                ),
                (
                    "reference",
                    "legacy-ref-index",
                    "Legacy reference block",
                    "LEGACY_REFERENCE_VALUE",
                    2048,
                ),
            )
            for tier, label, description, value, limit in fixtures:
                path = omh_home / "memory" / "blocks" / tier / f"{label}.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    json.dumps(
                        {
                            "schema_version": "omh_memory_block/v1",
                            "label": label,
                            "description": description,
                            "value": value,
                            "limit": limit,
                            "tier": tier,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    encoding="utf-8",
                )

            provider = OmhMemoryProvider(omh_home)
            provider.initialize("session_001", hermes_home=root / ".hermes", agent_context="primary")
            with patch(
                "omh.plugin_bundle.omh.memory_provider.read_memory_blocks",
                wraps=read_memory_blocks,
            ) as read_blocks:
                handoffs = tuple(provider.consolidation_due(trigger="manual") for _ in range(3))
            self.assertEqual(read_blocks.call_count, 3)
            for handoff in handoffs:
                self.assertIsInstance(handoff, dict)
                self.assertIn("reasons", handoff)
                self.assertIn("blocks", handoff)
                self.assertNotIn("LEGACY_SYSTEM_VALUE", json.dumps(handoff))
                self.assertNotIn("LEGACY_REFERENCE_VALUE", json.dumps(handoff))

            pack = provider.render_pack()
            self.assertIn("review_required_legacy", pack)
            self.assertNotIn("LEGACY_SYSTEM_VALUE", pack)
            self.assertNotIn("LEGACY_REFERENCE_VALUE", pack)

    @staticmethod
    def _call_tool(root: Path, **args: object) -> dict:
        with patch.dict(os.environ, {"OMH_HOME": str(root / ".omh"), "HERMES_HOME": str(root / ".hermes")}):
            return json.loads(omh_memory_handler(args))
