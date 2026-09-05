from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from _local_package import load_local_package

load_local_package()

from omh.coding import status_board  # noqa: E402
from omh.coding.inflight import write_inflight_marker  # noqa: E402
from omh.coding.status_board import (  # noqa: E402
    CODING_STATUS_BOARD_CLAIM_BOUNDARY,
    CODING_STATUS_BOARD_SCHEMA_VERSION,
    build_status_board,
    elapsed_text_for,
    model_label_for,
    normalize_status,
    render_status_board_text,
    status_board_messenger_body,
    tokens_text_for,
)
from omh.system.paths import OmhPaths  # noqa: E402

_NOW = "2026-08-03T12:00:00Z"
# Must satisfy omh.coding.fanout_contracts.FANOUT_ID_PATTERN: the real in-flight
# writer rejects anything else, so the fixtures use a real-shaped id.
_FANOUT_ID = "fanout-0123456789ab"


def _paths(root: Path) -> OmhPaths:
    return OmhPaths(omh_home=root / "omh", hermes_home=root / "hermes")


def _write_fanout(paths: OmhPaths, fanout_id: str, *, units: list[dict], titles: dict[str, str]) -> None:
    fanout_dir = paths.fanout_contracts_dir / fanout_id
    fanout_dir.mkdir(parents=True, exist_ok=True)
    (fanout_dir / "dispatch_summary.json").write_text(
        json.dumps({"fanout_id": fanout_id, "units": units}), encoding="utf-8"
    )
    (fanout_dir / "fanout_contract.json").write_text(
        json.dumps(
            {
                "fanout_id": fanout_id,
                "units": [{"unit_id": unit_id, "title": title} for unit_id, title in titles.items()],
            }
        ),
        encoding="utf-8",
    )


def _marker(**overrides) -> dict:
    marker = {
        "owner": "claude",
        "owner_host": "local",
        "model": "fable-5",
        "reasoning_effort": "high",
        "run_ref": "run-research",
        "worktree": "/w/research",
        "started_at": "2026-08-03T11:25:00Z",
        "unit_id": "research",
        "fanout_id": _FANOUT_ID,
    }
    marker.update(overrides)
    return marker


class StatusBoardBuildTests(unittest.TestCase):
    def test_empty_state_renders_without_crashing(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            with patch.object(status_board, "read_inflight_markers", return_value=[]):
                payload = build_status_board(paths, now=_NOW)
        self.assertEqual(payload["schema_version"], CODING_STATUS_BOARD_SCHEMA_VERSION)
        self.assertEqual(payload["unit_count"], 0)
        self.assertEqual(payload["running_count"], 0)
        self.assertEqual(payload["units"], [])
        self.assertEqual(payload["observed_at"], _NOW)
        self.assertEqual(payload["claim_boundary"], CODING_STATUS_BOARD_CLAIM_BOUNDARY)
        text = render_status_board_text(payload)
        self.assertIn("No coding work observed.", text)
        self.assertIn("0 running of 0 observed", text)

    def test_running_unit_with_full_data(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            with patch.object(status_board, "read_inflight_markers", return_value=[_marker()]):
                payload = build_status_board(paths, now=_NOW)
        self.assertEqual(payload["unit_count"], 1)
        self.assertEqual(payload["running_count"], 1)
        self.assertEqual(payload["sources_used"], ["inflight_markers"])
        unit = payload["units"][0]
        self.assertEqual(unit["unit_id"], "research")
        self.assertEqual(unit["status"], "running")
        self.assertEqual(unit["runtime"], "claude")
        self.assertEqual(unit["runtime_host"], "local")
        self.assertEqual(unit["model"], "fable-5")
        self.assertEqual(unit["model_label"], "fable-5 high")
        self.assertEqual(unit["run_ref"], "run-research")
        self.assertEqual(unit["elapsed_seconds"], 2100)
        self.assertEqual(unit["elapsed_text"], "35m")
        # A running unit has reported no token total, so the board says so.
        self.assertEqual(unit["tokens_total"], "unknown")
        self.assertEqual(unit["tokens_text"], "unknown")
        self.assertEqual(unit["session_ref"], "unknown")
        self.assertNotIn("fanout_id", unit)
        # The worktree path is where the unit runs, not observed progress.
        self.assertEqual(unit["summary"], "")
        self.assertNotIn("/w/research", render_status_board_text(payload))

    def test_completed_unit_with_unknown_tokens(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            _write_fanout(
                paths,
                _FANOUT_ID,
                units=[
                    {
                        "unit_id": "core",
                        "run_ref": "run-core",
                        "owner": "codex",
                        "model": "gpt-5.6-sol",
                        "reasoning_effort": "xhigh",
                        "status": "completed",
                        "duration_seconds": 92.517,
                    }
                ],
                titles={"core": "Core work"},
            )
            with patch.object(status_board, "read_inflight_markers", return_value=[]):
                payload = build_status_board(paths, now=_NOW)
        unit = payload["units"][0]
        self.assertEqual(payload["sources_used"], ["dispatch_summary"])
        self.assertEqual(unit["label"], "Core work")
        self.assertEqual(unit["status"], "completed")
        self.assertEqual(unit["model_label"], "gpt-5.6-sol xhigh")
        # The float duration is floored to a whole second; no float survives.
        self.assertEqual(unit["elapsed_seconds"], 92)
        self.assertIsInstance(unit["elapsed_seconds"], int)
        self.assertEqual(unit["elapsed_text"], "1m")
        self.assertEqual(unit["tokens_total"], "unknown")
        self.assertEqual(unit["tokens_text"], "unknown")

    def test_observed_tokens_render_thousands_separated(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            _write_fanout(
                paths,
                _FANOUT_ID,
                units=[
                    {
                        "unit_id": "core",
                        "owner": "claude",
                        "model": "fable-5",
                        "status": "completed",
                        "duration_seconds": 2100,
                        "tokens_total": 10_000_000,
                        "session_ref": "sess-7",
                    }
                ],
                titles={"core": "research work"},
            )
            with patch.object(status_board, "read_inflight_markers", return_value=[]):
                payload = build_status_board(paths, now=_NOW)
        unit = payload["units"][0]
        self.assertEqual(unit["tokens_total"], 10_000_000)
        self.assertEqual(unit["tokens_text"], "10,000,000")
        self.assertEqual(unit["session_ref"], "sess-7")
        self.assertEqual(unit["model_label"], "fable-5")
        text = render_status_board_text(payload)
        self.assertIn("research work", text)
        self.assertIn("10,000,000", text)
        self.assertIn("35m", text)

    def test_provider_prefixed_model_id_renders_intact(self) -> None:
        # A unit routed from a local-inventory catalog carries a
        # provider-prefixed model id ("provider/model_id", the shape
        # `inventory_model_catalog` derives for the omo runtime); the slash
        # must survive into the label on every render surface.
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            _write_fanout(
                paths,
                _FANOUT_ID,
                units=[
                    {
                        "unit_id": "omo-core",
                        "owner": "omo",
                        "model": "openrouter/qwen-3.5-coder",
                        "reasoning_effort": "high",
                        "status": "completed",
                        "duration_seconds": 40,
                    }
                ],
                titles={"omo-core": "omo work"},
            )
            with patch.object(status_board, "read_inflight_markers", return_value=[]):
                payload = build_status_board(paths, now=_NOW)
        unit = payload["units"][0]
        self.assertEqual(unit["model_label"], "openrouter/qwen-3.5-coder high")
        text = render_status_board_text(payload)
        self.assertIn("openrouter/qwen-3.5-coder high", text)
        bullets = status_board_messenger_body(payload, render_profile="limited_markdown")
        self.assertIn("omo work — omo (openrouter/qwen-3.5-coder high) — Code · reported done", bullets)
        self.assertNotIn(" — (", bullets)

    def test_mixed_running_and_completed_ordering_and_dedup(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            _write_fanout(
                paths,
                _FANOUT_ID,
                units=[
                    {"unit_id": "docs", "owner": "codex", "status": "completed", "duration_seconds": 30},
                    # Same (fanout_id, unit_id) as the in-flight marker below:
                    # the marker must win and the row must stay running.
                    {"unit_id": "research", "owner": "codex", "status": "failed", "duration_seconds": 5},
                ],
                titles={"docs": "docs work", "research": "stale title"},
            )
            with patch.object(status_board, "read_inflight_markers", return_value=[_marker()]):
                payload = build_status_board(paths, now=_NOW)
        self.assertEqual(payload["unit_count"], 2)
        self.assertEqual(payload["running_count"], 1)
        self.assertEqual(payload["sources_used"], ["inflight_markers", "dispatch_summary"])
        statuses = [unit["status"] for unit in payload["units"]]
        labels = [unit["label"] for unit in payload["units"]]
        self.assertEqual(statuses, ["running", "completed"])
        self.assertEqual(labels, ["research", "docs work"])

    def test_truncation_past_limit_is_stated(self) -> None:
        markers = [
            _marker(unit_id=f"unit-{index}", run_ref=f"run-{index}", fanout_id=_FANOUT_ID)
            for index in range(5)
        ]
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            with patch.object(status_board, "read_inflight_markers", return_value=markers):
                payload = build_status_board(paths, limit=2, now=_NOW)
        self.assertEqual(payload["unit_count"], 5)
        self.assertEqual(payload["running_count"], 5)
        self.assertEqual(len(payload["units"]), 2)
        text = render_status_board_text(payload)
        self.assertIn("Showing 2 of 5 units; 3 not shown because of the display limit.", text)
        bullets = status_board_messenger_body(payload, render_profile="limited_markdown")
        self.assertIn("Showing 2 of 5 units; 3 not shown because of the display limit.", bullets)

    def test_real_inflight_markers_reach_the_board(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            write_inflight_marker(
                paths,
                _FANOUT_ID,
                "research",
                {
                    "owner": "claude",
                    "owner_host": "local",
                    "model": "fable-5",
                    "reasoning_effort": "high",
                    "run_ref": "run-research",
                    "worktree": "/w/research",
                    "started_at": "2026-08-03T11:25:00Z",
                },
            )
            payload = build_status_board(paths, now=_NOW)
        self.assertEqual(payload["running_count"], 1)
        unit = payload["units"][0]
        self.assertEqual(unit["unit_id"], "research")
        self.assertEqual(unit["runtime"], "claude")
        self.assertEqual(unit["model_label"], "fable-5 high")
        self.assertEqual(unit["elapsed_text"], "35m")
        self.assertEqual(unit["tokens_text"], "unknown")

    def test_unreadable_markers_are_dropped_not_shown_as_running(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            marker_dir = paths.fanout_contracts_dir / _FANOUT_ID / "inflight"
            marker_dir.mkdir(parents=True)
            (marker_dir / "broken.json").write_text("{not json", encoding="utf-8")
            payload = build_status_board(paths, now=_NOW)
        self.assertEqual(payload["unit_count"], 0)
        self.assertEqual(payload["running_count"], 0)
        self.assertNotIn("broken", render_status_board_text(payload))

    def test_now_is_not_read_from_the_clock_when_provided(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            with patch.object(status_board, "read_inflight_markers", return_value=[]):
                with patch.object(status_board, "utc_now", side_effect=AssertionError("clock read")):
                    payload = build_status_board(paths, now=_NOW)
        self.assertEqual(payload["observed_at"], _NOW)


class UnknownRenderingTests(unittest.TestCase):
    def test_every_optional_field_renders_unknown(self) -> None:
        bare = {"unit_id": "bare", "started_at": "", "owner": "", "owner_host": "", "model": "",
                "reasoning_effort": "", "run_ref": "", "worktree": "", "fanout_id": ""}
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            with patch.object(status_board, "read_inflight_markers", return_value=[bare]):
                payload = build_status_board(paths, now=_NOW)
        unit = payload["units"][0]
        for field in (
            "run_ref",
            "runtime",
            "runtime_host",
            "model",
            "reasoning_effort",
            "elapsed_seconds",
            "elapsed_text",
            "tokens_total",
            "tokens_text",
            "session_ref",
        ):
            self.assertEqual(unit[field], "unknown", field)
        self.assertEqual(unit["label"], "bare")
        self.assertEqual(unit["model_label"], "executor default")
        self.assertEqual(unit["summary"], "")
        text = render_status_board_text(payload)
        self.assertIn("unknown", text)
        self.assertIn("bare", text)
        # Alignment survives an all-unknown row: every data line matches the
        # header row width, so the board is still a readable table.
        lines = [line for line in text.splitlines() if line.startswith(("LABEL", "bare"))]
        self.assertEqual(len(lines), 2)

    def test_unparseable_started_at_is_unknown_not_zero(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            with patch.object(status_board, "read_inflight_markers", return_value=[_marker(started_at="soon")]):
                payload = build_status_board(paths, now=_NOW)
        self.assertEqual(payload["units"][0]["elapsed_seconds"], "unknown")
        self.assertEqual(payload["units"][0]["elapsed_text"], "unknown")


class FormattingTests(unittest.TestCase):
    def test_elapsed_boundaries(self) -> None:
        self.assertEqual(elapsed_text_for(0), "0s")
        self.assertEqual(elapsed_text_for(45), "45s")
        self.assertEqual(elapsed_text_for(59), "59s")
        self.assertEqual(elapsed_text_for(60), "1m")
        self.assertEqual(elapsed_text_for(2100), "35m")
        self.assertEqual(elapsed_text_for(3599), "59m")
        self.assertEqual(elapsed_text_for(3600), "1h")
        self.assertEqual(elapsed_text_for(5400), "1h 30m")
        self.assertEqual(elapsed_text_for(7500), "2h 5m")
        self.assertEqual(elapsed_text_for(86399), "23h 59m")
        self.assertEqual(elapsed_text_for(86400), "1d")
        self.assertEqual(elapsed_text_for(90000), "1d 1h")

    def test_elapsed_unknown_inputs(self) -> None:
        self.assertEqual(elapsed_text_for("unknown"), "unknown")
        self.assertEqual(elapsed_text_for(None), "unknown")
        self.assertEqual(elapsed_text_for(-1), "unknown")
        self.assertEqual(elapsed_text_for(12.5), "unknown")
        self.assertEqual(elapsed_text_for(True), "unknown")

    def test_tokens_text(self) -> None:
        self.assertEqual(tokens_text_for(0), "0")
        self.assertEqual(tokens_text_for(10_000_000), "10,000,000")
        self.assertEqual(tokens_text_for("unknown"), "unknown")
        self.assertEqual(tokens_text_for(None), "unknown")
        self.assertEqual(tokens_text_for(-5), "unknown")
        self.assertEqual(tokens_text_for(True), "unknown")

    def test_model_label_matches_fanout_brief_format(self) -> None:
        self.assertEqual(model_label_for("gpt-5.6-sol", "xhigh"), "gpt-5.6-sol xhigh")
        self.assertEqual(model_label_for("fable-5", ""), "fable-5")
        self.assertEqual(model_label_for("", ""), "executor default")

    def test_model_label_parity_with_the_plugin_bundle_copy(self) -> None:
        # Two hand-synced builders render the `(model effort)` label:
        # `model_label_for` here (also used by `omh coding fanout brief`) and
        # the plugin bundle's `_model_label` (the bundle cannot import
        # `omh.*`, so it carries a copy). This table keeps the copies equal;
        # drift in either one fails the suite.
        from omh.plugin_bundle.omh.status_board_reader import _model_label as plugin_model_label

        table = (
            # (model, reasoning_effort, expected label)
            ("gpt-5.6-sol", "xhigh", "gpt-5.6-sol xhigh"),
            ("fable-5", "", "fable-5"),
            ("", "", "executor default"),
            # Provider-prefixed omo id from a local-inventory catalog
            # (`inventory_model_catalog` ids are "provider/model_id").
            ("openrouter/qwen-3.5-coder", "high", "openrouter/qwen-3.5-coder high"),
        )
        for model, effort, expected in table:
            with self.subTest(model=model, effort=effort):
                self.assertEqual(model_label_for(model, effort), expected)
                self.assertEqual(plugin_model_label(model, effort), expected)

    def test_status_vocabulary_is_closed(self) -> None:
        for status in ("running", "completed", "failed", "worktree_failed", "prepared_not_observed"):
            self.assertEqual(normalize_status(status), status)
        self.assertEqual(normalize_status("skipped"), "prepared_not_observed")
        self.assertEqual(normalize_status(""), "prepared_not_observed")
        self.assertEqual(normalize_status(None), "prepared_not_observed")


class MessengerProfileTests(unittest.TestCase):
    def _payload(self) -> dict:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            _write_fanout(
                paths,
                _FANOUT_ID,
                units=[
                    {
                        "unit_id": "core",
                        "owner": "codex",
                        "model": "gpt-5.6-sol",
                        "reasoning_effort": "xhigh",
                        "status": "completed",
                        "duration_seconds": 2100,
                        "tokens_total": 10_000_000,
                        "session_ref": "sess-7",
                    }
                ],
                titles={"core": "feature work"},
            )
            with patch.object(status_board, "read_inflight_markers", return_value=[_marker()]):
                return build_status_board(paths, now=_NOW)

    def test_rich_markdown_is_a_fenced_block_preserving_alignment(self) -> None:
        from omh.coding.status_board import (
            CODING_STATUS_BOARD_CLAIM_BOUNDARY,
            CODING_STATUS_BOARD_SHORT_BOUNDARY,
        )

        body = status_board_messenger_body(self._payload(), render_profile="rich_markdown")
        self.assertTrue(body.startswith("```\n"))
        self.assertIn("LABEL", body)

        # The caveat sits AFTER the fence. Inside it, a paragraph of prose is
        # monospace-wrapped at the table's width and reads as broken rendering.
        inner, _, trailer = body[4:].partition("\n```")
        self.assertNotIn(CODING_STATUS_BOARD_SHORT_BOUNDARY, inner)
        self.assertNotIn(CODING_STATUS_BOARD_CLAIM_BOUNDARY, inner)
        self.assertEqual(trailer.strip(), CODING_STATUS_BOARD_SHORT_BOUNDARY)

        # Alignment survives: every fenced line is a verbatim board row.
        aligned = render_status_board_text(self._payload())
        for line in inner.splitlines():
            self.assertIn(line, aligned)

    def test_limited_markdown_is_flat_bullets(self) -> None:
        body = status_board_messenger_body(self._payload(), render_profile="limited_markdown")
        self.assertNotIn("|", body)
        self.assertNotIn("**", body)
        self.assertNotIn("```", body)
        self.assertNotIn("  -", body)
        bullets = [line for line in body.splitlines() if line.startswith("- ")]
        self.assertEqual(len(bullets), 2)
        # Runtime and model read as ONE field. Separating them with a dash as
        # well produced "claude — (fable-5 high)", a doubled separator around a
        # parenthetical.
        self.assertIn("research — claude (fable-5 high) — Code · running — 35m — tokens unknown", bullets[0])
        self.assertIn("feature work — codex (gpt-5.6-sol xhigh) — Code · reported done — 35m — 10,000,000 tokens", bullets[1])
        for bullet in bullets:
            self.assertNotIn(" — (", bullet)
        self.assertIn("session sess-7", bullets[1])
        # The SHORT boundary, not the full one. At 308 characters the full text
        # was 53% of a two-row board -- boilerplate a reader scrolls past to
        # reach the data. It stays in the payload and in `--json`, which is
        # where an auditor reads it.
        from omh.coding.status_board import CODING_STATUS_BOARD_SHORT_BOUNDARY

        self.assertIn(CODING_STATUS_BOARD_SHORT_BOUNDARY, body)
        self.assertNotIn(CODING_STATUS_BOARD_CLAIM_BOUNDARY, body)
        self.assertIn(CODING_STATUS_BOARD_CLAIM_BOUNDARY, self._payload()["claim_boundary"])

    def test_limited_markdown_empty_state(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            with patch.object(status_board, "read_inflight_markers", return_value=[]):
                payload = build_status_board(paths, now=_NOW)
        body = status_board_messenger_body(payload, render_profile="limited_markdown")
        self.assertIn("No coding work observed.", body)


class LocaleTests(unittest.TestCase):
    def _payload(self) -> dict:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            with patch.object(status_board, "read_inflight_markers", return_value=[_marker()]):
                return build_status_board(paths, now=_NOW)

    def test_default_output_is_english(self) -> None:
        text = render_status_board_text(self._payload())
        self.assertIn("Coding status board", text)
        self.assertNotIn("코딩", text)

    def test_korean_is_opt_in_only(self) -> None:
        text = render_status_board_text(self._payload(), locale="ko")
        self.assertIn("코딩 작업 현황", text)
        # Column headers stay dialect-neutral so the table reads the same
        # everywhere; only the surrounding copy is localized.
        self.assertIn("LABEL", text)
        self.assertIn("RUNTIME", text)


class UnmappedStatusIsVisibleTests(unittest.TestCase):
    """A refused status word has to reach the surfaces a person actually reads.

    Recording it in the payload alone answers an auditor reading `--json` and
    nobody reading the board -- and the board is where "an executor reported
    something this vocabulary does not know" is meant to be noticed, because
    `prepared_not_observed` on its own reads as "nobody ever watched this run".
    """

    def _payload(self, status: str) -> dict:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            _write_fanout(
                paths,
                _FANOUT_ID,
                units=[
                    {"unit_id": "odd", "owner": "codex", "status": status, "duration_seconds": 12},
                    {"unit_id": "known", "owner": "codex", "status": "completed", "duration_seconds": 12},
                ],
                titles={"odd": "odd unit", "known": "known unit"},
            )
            with patch.object(status_board, "read_inflight_markers", return_value=[]):
                return build_status_board(paths, now=_NOW)

    def test_the_aligned_board_shows_the_word_beside_the_downgrade(self) -> None:
        text = render_status_board_text(self._payload("quiesced"))
        self.assertIn("Plan · not run (reported quiesced)", text)
        # The accepted row is untouched, so a board with nothing refused reads
        # exactly as it did before.
        self.assertIn("Code · reported done", text)
        self.assertNotIn("completed (reported", text)

    def test_the_column_stays_aligned_when_the_word_widens_it(self) -> None:
        text = render_status_board_text(self._payload("quiesced"))
        rows = [line for line in text.splitlines() if "codex" in line or line.startswith("LABEL")]
        self.assertEqual(len({len(line.split("codex")[0]) for line in rows if "codex" in line}), 1)
        self.assertIn("STATUS", text)

    def test_both_messenger_profiles_carry_the_word(self) -> None:
        payload = self._payload("quiesced")
        for profile in ("rich_markdown", "limited_markdown"):
            with self.subTest(profile=profile):
                body = status_board_messenger_body(payload, render_profile=profile)
                self.assertIn("Plan · not run (reported quiesced)", body)

    def test_an_accepted_status_renders_exactly_as_before(self) -> None:
        text = render_status_board_text(self._payload("running"))
        self.assertNotIn("(reported", text)

    def test_the_payload_still_carries_the_field_on_its_own(self) -> None:
        rows = {str(unit["unit_id"]): unit for unit in self._payload("quiesced")["units"]}
        self.assertEqual(rows["odd"]["unmapped_source_status"], "quiesced")
        self.assertEqual(rows["odd"]["status"], "prepared_not_observed")
        self.assertNotIn("unmapped_source_status", rows["known"])


class UnmappedStatusPluginParityTests(unittest.TestCase):
    """The vendored reader discarded the word entirely, with no gate to notice.

    `status_board_reader` is hand-mirrored and cannot import `omh.coding.*`, so
    the only thing keeping the two honest is a differential over the same
    on-disk fixture.
    """

    def _boards(self, status: str) -> tuple[dict, dict]:
        from omh.plugin_bundle.omh.status_board_reader import read_running_work_board

        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            _write_fanout(
                paths,
                _FANOUT_ID,
                units=[{"unit_id": "odd", "owner": "codex", "status": status}],
                titles={"odd": "odd unit"},
            )
            with patch.object(status_board, "read_inflight_markers", return_value=[]):
                source = build_status_board(paths, now=_NOW)
            plugin = read_running_work_board(paths.omh_home)
        return source, plugin

    def test_both_readers_keep_the_same_refused_word(self) -> None:
        source, plugin = self._boards("quiesced")
        self.assertEqual(source["units"][0]["unmapped_source_status"], "quiesced")
        self.assertEqual(plugin["units"][0]["unmapped_source_status"], "quiesced")
        self.assertEqual(source["units"][0]["status"], plugin["units"][0]["status"])

    def test_both_readers_render_the_same_status_text(self) -> None:
        from omh.plugin_bundle.omh.status_board_reader import render_running_work_block_text

        source, plugin = self._boards("quiesced")
        self.assertIn("Plan · not run (reported quiesced)", render_status_board_text(source))
        self.assertIn("Plan · not run (reported quiesced)", render_running_work_block_text(plugin))

    def test_neither_reader_invents_a_word_for_an_accepted_status(self) -> None:
        from omh.plugin_bundle.omh.status_board_reader import render_running_work_block_text

        source, plugin = self._boards("completed")
        self.assertNotIn("unmapped_source_status", source["units"][0])
        self.assertNotIn("unmapped_source_status", plugin["units"][0])
        self.assertNotIn("(reported", render_status_board_text(source))
        self.assertNotIn("(reported", render_running_work_block_text(plugin))

    def test_the_two_status_helpers_agree_value_by_value(self) -> None:
        from omh.coding.status_board import status_text_for, unmapped_status_source
        from omh.plugin_bundle.omh.status_board_reader import (
            _status_text as plugin_status_text,
            _unmapped_status_source as plugin_unmapped_status_source,
        )

        # Status-word-shaped values only. The source helper runs the full
        # chat-progress sanitizer (absolute-path redaction included) that the
        # bundle cannot import; a status field holds an identifier, so the two
        # agree on everything a status can be.
        table = (
            "quiesced",
            "skipped",
            "cancelled",
            "  spaced  out  ",
            "x" * 200,
            "completed",
            "running",
            "",
            None,
        )
        for value in table:
            with self.subTest(value=value):
                self.assertEqual(unmapped_status_source(value), plugin_unmapped_status_source(value))
        for value in table:
            with self.subTest(value=value):
                unit = {
                    "status": normalize_status(value),
                    "unmapped_source_status": unmapped_status_source(value),
                }
                self.assertEqual(status_text_for(unit), plugin_status_text(unit))

    def test_the_two_status_vocabularies_are_the_same_closed_set(self) -> None:
        from omh.coding.status_board import STATUS_VOCABULARY
        from omh.plugin_bundle.omh.status_board_reader import _STATUS_VOCABULARY as plugin_vocabulary

        self.assertEqual(STATUS_VOCABULARY, plugin_vocabulary)


if __name__ == "__main__":
    unittest.main()
