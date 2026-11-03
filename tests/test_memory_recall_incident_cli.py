from __future__ import annotations

from contextlib import chdir
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from _cli_harness import run_cli
from project_identity_fixture import pin_review_first, seed_project_identity
from omh.paths import resolve_paths
from omh.plugin_bundle.omh.memory_provider import OmhMemoryProvider


class MemoryRecallIncidentCliTests(unittest.TestCase):
    def test_pending_claim_diagnosis_is_private_and_explicitly_persisted(self) -> None:
        for persist in (False, True):
            with self.subTest(persist=persist), TemporaryDirectory() as directory, chdir(directory):
                # Given: a real pending candidate in isolated OMH/Hermes homes.
                root = Path(directory)
                seed_project_identity(root)
                home = root / "omh"
                prefix = ["--omh-home", str(home), "--hermes-home", str(root / "hermes")]
                pin_review_first(resolve_paths(home, root / "hermes"))
                summary = "PRIVATE_CLAIM_SENTINEL"
                status, stdout, stderr = run_cli(prefix + ["memory", "capture", summary])
                self.assertEqual(status, 0, stderr)
                candidate_id = json.loads(stdout)["candidate"]["candidate_id"]
                candidate_path = home / "memory" / "candidates" / f"{candidate_id}.json"
                before = candidate_path.read_bytes()
                anchor = (
                    ["--claim-digest", hashlib.sha256(summary.encode()).hexdigest()]
                    if persist
                    else ["--record-id", candidate_id]
                )
                args = prefix + [
                    "memory", "recall-incident", *anchor,
                    "--query", "PRIVATE_QUERY_SENTINEL",
                    "--session-id", "PRIVATE_SESSION_SENTINEL",
                    "--provider-served-count", "0",
                ]
                if persist:
                    args.append("--write")

                # When: the actual parser/handler diagnoses that expected claim.
                status, stdout, stderr = run_cli(args)

                # Then: evidence is scoped, diagnosis is read-only, saving is opt-in.
                self.assertEqual(status, 0, stderr)
                incident = json.loads(stdout)
                self.assertEqual(incident["schema_version"], "memory_recall_incident/v1")
                self.assertEqual(incident["stage"], "pending_or_rejected")
                self.assertEqual(incident["anchor"]["candidate_id"], candidate_id)
                self.assertFalse(incident["authorizes_mutation"])
                self.assertIsNone(incident["delivery_observed"])
                self.assertEqual(
                    incident["evidence_surfaces"]["live_prefetch_receipt"]["status"],
                    "unavailable",
                )
                self.assertEqual(
                    incident["evidence_surfaces"]["provider_recall_status"]["status"],
                    "not_authoritative",
                )
                for sentinel in (summary, "PRIVATE_QUERY_SENTINEL", "PRIVATE_SESSION_SENTINEL"):
                    self.assertNotIn(sentinel, stdout)
                self.assertEqual(candidate_path.read_bytes(), before)
                incidents = home / "memory" / "incidents"
                if persist:
                    saved = incidents / f"{incident['incident_id']}.json"
                    self.assertEqual(json.loads(saved.read_text()), incident)
                else:
                    self.assertFalse(incidents.exists())

    def test_live_receipt_binds_only_to_its_session_and_configuration(self) -> None:
        with TemporaryDirectory() as directory, chdir(directory):
            # Given: an approved record and the actual provider's served receipt in this home.
            root = Path(directory)
            seed_project_identity(root)
            home = root / "omh"
            prefix = ["--omh-home", str(home), "--hermes-home", str(root / "hermes")]
            status, stdout, stderr = run_cli(prefix + ["memory", "capture", "LIVE_CLAIM_SENTINEL"])
            self.assertEqual(status, 0, stderr)
            candidate_id = json.loads(stdout)["candidate"]["candidate_id"]
            status, stdout, stderr = run_cli(prefix + ["memory", "review", "--candidate", candidate_id])
            self.assertEqual(status, 0, stderr)
            revision = json.loads(stdout)["cards"][0]["review_revision"]
            status, stdout, stderr = run_cli(
                prefix + ["memory", "approve", candidate_id, "--candidate-revision", revision]
            )
            self.assertEqual(status, 0, stderr)
            record_id = json.loads(stdout)["record"]["record_id"]
            live = OmhMemoryProvider(home, hermes_home=root / "hermes")
            live.initialize("session-a", platform="cli", hermes_home=str(root / "hermes"), agent_context="primary", cwd=str(root))
            # A live turn serves what its query matches, never the whole store.
            live.queue_prefetch("LIVE_CLAIM_SENTINEL")
            live.prefetch("LIVE_CLAIM_SENTINEL")
            receipt = live.latest_prefetch_receipt()
            live.shutdown()
            assert receipt is not None
            self.assertEqual([item["record_id"] for item in receipt["rendering"]["rendered_records"]], [record_id])
            before = {str(p): p.read_bytes() for p in home.rglob("*") if p.is_file()}
            expectations = (
                (["--session-id", "session-a"], "observed", "canonical_1452_receipt_bound", "rendered_delivery_not_observed"),
                (["--session-id", "session-b"], "not_authoritative", "receipt_session_mismatch", "unresolved"),
                ([], "not_authoritative", "receipt_session_unbound", "unresolved"),
                (["--session-id", "session-a", "--limit", "1"], "not_authoritative", "receipt_configuration_mismatch", "unresolved"),
            )
            for options, surface_status, basis, stage in expectations:
                with self.subTest(options=options):
                    # When: the registered parser/handler diagnoses through the receipt seam.
                    status, stdout, stderr = run_cli(
                        prefix + ["memory", "recall-incident", "--record-id", record_id, *options]
                    )
                    # Then: identity decides authority; delivery and use stay unknown.
                    self.assertEqual(status, 0, stderr)
                    incident = json.loads(stdout)
                    self.assertEqual(incident["evidence_surfaces"]["live_prefetch_receipt"],
                                     {"status": surface_status, "basis": basis})
                    self.assertEqual(incident["stage"], stage)
                    self.assertIsNone(incident["delivery_observed"])
                    self.assertFalse(incident["authorizes_mutation"])
                    self.assertNotIn("LIVE_CLAIM_SENTINEL", stdout)
                    self.assertNotIn("selected_record_ids", stdout)
            self.assertEqual({str(p): p.read_bytes() for p in home.rglob("*") if p.is_file()}, before)
