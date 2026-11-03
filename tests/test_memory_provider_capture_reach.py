"""Chat-turn recall keeps the question rather than the pasted host payload."""
from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from _local_package import load_local_package

load_local_package()
from omh.plugin_bundle.omh import memory_provider  # noqa: E402
from omh.plugin_bundle.omh.memory_prefetch_receipt import build_prefetch_receipt, mark_prefetch_receipt_returned, validate_prefetch_receipt  # noqa: E402
from omh.plugin_bundle.omh.memory_records import prepare_prefetch_records, read_record_store_snapshot  # noqa: E402
from omh.plugin_bundle.omh.memory_query_sanitizer import sanitize_memory_query  # noqa: E402
from test_memory_prefetch_canonical import approve, provider, rendered_ids  # noqa: E402
from test_memory_provider_hermes_order import hermes_turn  # noqa: E402


QUESTION = "How should we deploy the production release?"
LOG = ("2026-10-01T10:00:00Z ERROR socket timeout traceback retry telemetry\n" * 50).rstrip()


class CaptureReachHomes(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(self.enterContext(TemporaryDirectory())).resolve()
        self.home = self.root / ".omh"
        self.hermes = self.root / ".hermes"
        self.hermes.mkdir()
        self.enterContext(patch.dict(os.environ, {"OMH_HOME": str(self.home), "HERMES_HOME": str(self.hermes)}))
        for name in ("HERMES_KANBAN_TASK", "HERMES_SESSION_SOURCE"):
            os.environ.pop(name, None)

    def seed(self, summary: str) -> dict:
        return approve(self.root, summary, scope_kind="user-global", scope_ref="default")


class SanitizedProviderQueryTests(CaptureReachHomes):
    def test_log_pastes_rank_deploy_records_first_in_both_question_positions(self) -> None:
        deploy = self.seed("Deploy the production release from a signed staging tag.")
        noisy = [self.seed(summary)["record_id"] for summary in (
            "Socket timeout troubleshooting uses packet capture.",
            "Traceback retry analysis uses the crash archive.",
            "Telemetry error reports live in the diagnostics folder.",
        )]
        for turn, message in enumerate((LOG + "\n" + QUESTION, QUESTION + "\n" + LOG), 1):
            # A fresh conversation each: one that already holds the deploy
            # record would not serve it again.
            live = provider(self.root, session_id=f"session-{turn}")
            with self.subTest(question_first=turn == 2):
                ids = rendered_ids(hermes_turn(live, turn, message))
                self.assertTrue(ids)
                self.assertEqual(ids[0], deploy["record_id"])
                self.assertFalse(set(noisy) & set(ids[:3]))
                receipt = live.latest_prefetch_receipt()
                self.assertIsNotNone(receipt)
                clean = sanitize_memory_query(message)
                self.assertEqual(receipt["lens"]["query_method"], clean.method)
                self.assertEqual(receipt["lens"]["query_original_length"], len(message))
                self.assertEqual(receipt["lens"]["query_clean_length"], len(clean.clean))
                self.assertNotIn(QUESTION, json.dumps(receipt))
                self.assertNotIn(LOG, json.dumps(receipt))
                self.assertEqual(validate_prefetch_receipt(receipt), [])

    def test_discord_backfill_prefetch_keeps_the_question_and_the_chosen_reply(self) -> None:
        live = memory_provider.OmhMemoryProvider(self.home, hermes_home=self.hermes)
        live.initialize(
            "discord-backfill", cwd=str(self.root), platform="discord", chat_type="group",
            chat_id="1111111111111111111", user_id="987654321098765432", chat_name="fixture",
        )
        channel_context = "[Recent channel messages]\n[jun] The telemetry archive moved to cold storage."
        message_text = f"[mina] {QUESTION}"
        message_text = f"{channel_context}\n\n[New message]\n{message_text}"
        reply_text = "The older checklist used another branch."
        message_text = f'[Replying to: "{reply_text}"]\n\n{message_text}'
        note = "[Triggering message id: 2222222222222222222]"
        message_text = f"{note}\n\n{message_text}"
        self.assertEqual(live._surface_class, "channel")
        with patch.object(memory_provider, "prepare_prefetch_records", wraps=prepare_prefetch_records) as prepare:
            hermes_turn(live, 1, message_text)
        # Another speaker's backfill line never reaches the query; the message the
        # person chose to reply to does, after their own words.
        self.assertEqual(live._query, f"{QUESTION} {reply_text}")
        self.assertEqual(prepare.call_args.args[1], f"{QUESTION} {reply_text}")
        self.assertNotIn("telemetry archive", live._query)
        self.assertEqual(live.latest_prefetch_receipt()["lens"]["query_method"], "framing_only")

    def test_short_query_pack_matches_the_unchanged_raw_selector_byte_for_byte(self) -> None:
        self.seed("Deploy the production release from a signed staging tag.")
        live = provider(self.root)
        raw = prepare_prefetch_records(
            read_record_store_snapshot((self.home,)), QUESTION,
            allowed_scopes=live._prefetch_scopes(), session_id=live._session_id,
        )
        pack = hermes_turn(live, 1, QUESTION)
        self.assertEqual(pack.encode("utf-8"), raw.section.text.encode("utf-8"))
        self.assertEqual(live.latest_prefetch_receipt()["lens"]["query_method"], "passthrough")

    def test_receipts_accept_legacy_lens_and_optional_sanitizer_metadata(self) -> None:
        prepared = prepare_prefetch_records(
            read_record_store_snapshot((self.home,)), QUESTION,
            allowed_scopes=[{"kind": "user-global", "ref": "default"}],
        )
        old = build_prefetch_receipt(prepared, session_id="fixture", home_digests=())
        self.assertNotIn("query_method", old["lens"])
        self.assertNotIn("query_original_length", old["lens"])
        self.assertNotIn("query_clean_length", old["lens"])
        self.assertEqual(validate_prefetch_receipt(old), [])
        new = build_prefetch_receipt(
            prepared, session_id="fixture", home_digests=(),
            query_sanitized=sanitize_memory_query(LOG + "\n" + QUESTION),
        )
        self.assertEqual(validate_prefetch_receipt(new), [])
        for key, bad in (("query_method", 5), ("query_original_length", True), ("query_clean_length", -1)):
            with self.subTest(key=key):
                invalid = json.loads(json.dumps(new))
                invalid["lens"][key] = bad
                signed = mark_prefetch_receipt_returned(invalid)
                self.assertIn("lens.query_sanitized", validate_prefetch_receipt(signed))

    def test_repeated_long_prefetch_reuses_the_turn_render(self) -> None:
        self.seed("Deploy the production release from a signed staging tag.")
        live = provider(self.root)
        message = LOG + "\n" + QUESTION
        with patch.object(live, "render_pack", wraps=live.render_pack) as render:
            live.on_turn_start(1, message)
            first = live.prefetch(message)
            self.assertEqual(live.prefetch(message), first)
            self.assertEqual(render.call_count, 1)

    def test_prefetch_and_queue_sanitize_even_without_a_turn_hook(self) -> None:
        live = provider(self.root)
        for query in (LOG + "\n" + QUESTION, QUESTION + "\n" + LOG):
            live.prefetch(query)
            self.assertEqual(live._query, QUESTION)
            live.queue_prefetch(query)
            self.assertEqual(live._query, QUESTION)


class BackupPathsTests(CaptureReachHomes):
    def make_provider(self) -> memory_provider.OmhMemoryProvider:
        return memory_provider.OmhMemoryProvider(self.home, hermes_home=self.hermes)

    def test_backup_paths_before_initialize_does_not_create_an_absent_store(self) -> None:
        live = self.make_provider()
        self.assertEqual(live.backup_paths(), [])
        self.assertFalse(self.home.exists())

    def test_backup_paths_returns_only_the_existing_real_memory_directory(self) -> None:
        memory = self.home / "memory"
        memory.mkdir(parents=True)
        live = self.make_provider()
        self.assertEqual(live.backup_paths(), [str(memory)])
        self.assertTrue(all(Path(path).is_absolute() for path in live.backup_paths()))
        self.assertEqual(list(memory.iterdir()), [])

    def test_backup_paths_refuses_a_file_or_linked_memory_directory(self) -> None:
        self.home.mkdir()
        memory = self.home / "memory"
        memory.write_text("not a directory", encoding="utf-8")
        live = self.make_provider()
        self.assertEqual(live.backup_paths(), [])
        memory.unlink()
        outside = self.root / "outside-memory"
        outside.mkdir()
        try:
            memory.symlink_to(outside, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"directory symlinks unavailable: {type(error).__name__}")
        self.assertEqual(live.backup_paths(), [])
        self.assertEqual(list(outside.iterdir()), [])

    def test_backup_paths_never_raises_on_unreadable_directory(self) -> None:
        live = self.make_provider()
        with patch.object(Path, "is_dir", side_effect=PermissionError("denied")):
            self.assertEqual(live.backup_paths(), [])

    def test_restored_principal_key_is_preserved_and_retightened_on_next_read(self) -> None:
        from omh.plugin_bundle.omh.memory_principals import _principal_key

        key = _principal_key(self.home)
        path = self.home / "memory" / "principal.key"
        path.chmod(0o644)
        live = self.make_provider()
        self.assertEqual(live.backup_paths(), [str(self.home / "memory")])
        self.assertEqual(_principal_key(self.home), key)
        if os.name != "nt":
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
