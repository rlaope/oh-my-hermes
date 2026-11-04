from __future__ import annotations

import json
import os
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from _local_package import load_local_package

load_local_package()

from project_identity_fixture import memory_paths as resolve_paths
from omh.plugin_bundle.omh.memory_blocks import approve_memory_block, build_memory_block, write_memory_block
from omh.plugin_bundle.omh.memory_principals import (
    PrincipalContractError,
    build_memory_identity,
    derive_principal_ref,
    memory_identity_errors,
    parse_principal_context,
)
from omh.plugin_bundle.omh.memory_provider import OmhMemoryProvider
from omh.workflows.memory import (
    approve_project_memory_candidate,
    capture_project_memory_candidate,
    validate_project_memory_record,
)
PRINCIPAL_A = "principal:v1:" + "a" * 64
PRINCIPAL_B = "principal:v1:" + "b" * 64
NOW = datetime(2026, 9, 12, tzinfo=timezone.utc)



def _context(
    principal: str | None,
    *,
    actor_kind: str = "human",
    profile: str = "profile_fixture",
    turn: str = "turn_1",
) -> dict[str, Any]:
    return {
        "schema_version": "memory_principal_context/v1",
        "principal": principal,
        "profile_ref": profile,
        "surface_ref": "fixture",
        "session_ref": "shared_fixture",
        "turn_ref": turn,
        "actor_kind": actor_kind,
        "identity_evidence_refs": ["evidence:fixture"],
        "binding_state": "validated_local" if actor_kind == "human" else "unbound",
    }


def _approved(
    paths,
    summary: str,
    context: dict[str, Any],
    *,
    audience: tuple[str, ...] = (),
    retention_class: str = "standard",
    ttl_days: int | None = None,
) -> dict[str, Any]:
    scope_kind = "project" if audience else "user"
    captured: Any = capture_project_memory_candidate(
        paths,
        summary,
        scope_kind=scope_kind,
        principal_context=context,
        audience_principals=audience,
        ttl_days=ttl_days,
        retention_class=retention_class,
    )
    reviewed: Any = approve_project_memory_candidate(
        paths,
        str(captured["candidate"]["candidate_id"]),
        reviewer_principal=PRINCIPAL_B,
    )
    return reviewed["record"]


def _provider_pack(paths, context: dict[str, Any] | None) -> tuple[str, dict[str, Any]]:
    provider = OmhMemoryProvider(omh_home=paths.omh_home, hermes_home=paths.hermes_home)
    try:
        provider.initialize("shared_fixture", cwd=paths.omh_home.parent, principal_context=_context(PRINCIPAL_A), shared_surface=True)
        provider.on_turn_start(1, "fixture", principal_context=context)
        # A live turn serves only what its query matches; this one names every fixture record.
        provider.queue_prefetch("preference project fact", session_id="shared_fixture", now=NOW)
        text = provider.prefetch("preference project fact", session_id="shared_fixture")
        return text, provider.latest_prefetch_receipt() or {}
    finally:
        provider.shutdown()


class MemoryPrincipalTests(unittest.TestCase):
    def test_M3_malformed_actor_and_binding_values_fail_closed_without_exceptions(self) -> None:
        # Given closed context JSON with malformed empty/container/non-string variants.
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / "omh", Path(tmp) / "hermes")
            malformed_values: tuple[Any, ...] = ("", [], {}, 7, None)

            # When parsing and user-scoped capture cross the actual boundary.
            for field in ("actor_kind", "binding_state"):
                for malformed in malformed_values:
                    with self.subTest(field=field, malformed=malformed):
                        context = {**_context(PRINCIPAL_A), field: malformed}
                        parsed = parse_principal_context(context)
                        capture: Any = capture_project_memory_candidate(
                            paths,
                            "Malformed principal context fixture",
                            scope_kind="user",
                            principal_context=context,
                        )

                        # Then malformed input is a bounded deny, never an exception/write.
                        self.assertIsNone(parsed)
                        self.assertFalse(capture["captured"])
                        self.assertEqual(capture["reason"], "principal_context_required")
            self.assertFalse((paths.memory_dir / "candidates").exists())

    def test_M4_nested_audience_kind_containers_return_bounded_admission_errors(self) -> None:
        # Given an otherwise valid reviewed shared v3 record.
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / "omh", Path(tmp) / "hermes")
            record = _approved(
                paths,
                "Shared malformed audience fixture",
                _context(PRINCIPAL_A),
                audience=(PRINCIPAL_A, PRINCIPAL_B),
            )

            # When nested audience.kind is a JSON container at both validators.
            for malformed in ([], {}):
                with self.subTest(malformed=malformed):
                    candidate: Any = json.loads(json.dumps(record))
                    candidate["identity"]["audience"]["kind"] = malformed
                    identity_errors = memory_identity_errors(candidate["identity"])
                    admission_errors = validate_project_memory_record(candidate)

                    # Then both paths return bounded codes instead of raising.
                    self.assertEqual(identity_errors, ["identity_values"])
                    self.assertIn("project_memory_record.identity_values", admission_errors)

    def test_M4_review_refs_reject_malformed_and_private_values_without_retention(self) -> None:
        # Given a safe candidate plus review-ref variants at the identity boundary.
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / "omh", Path(tmp) / "hermes")
            context = _context(PRINCIPAL_A)
            capture_project_memory_candidate(paths, "Safe persisted candidate", scope_kind="user", principal_context=context)
            private_sentinel = "password=private-review-ref-sentinel"
            malformed_values: tuple[Any, ...] = ("", [], {}, 7, private_sentinel)

            # When persisted identity validation inspects each nested review_ref.
            valid = build_memory_identity(
                context,
                scope_kind="user",
                reviewer_principal=PRINCIPAL_B,
                review_ref="review_safe_1",
            )
            for owner in ("reviewer", "audience"):
                for malformed in malformed_values:
                    with self.subTest(owner=owner, malformed=malformed):
                        identity = json.loads(json.dumps(valid))
                        identity[owner]["review_ref"] = malformed
                        self.assertTrue(memory_identity_errors(identity))

            # Then builders reject container/non-string/private refs without echoing them.
            identity_builder: Any = build_memory_identity
            for malformed in ([], {}, 7, private_sentinel):
                with self.subTest(builder_ref=malformed), self.assertRaises(PrincipalContractError) as raised:
                    identity_builder(context, scope_kind="user", review_ref=malformed)
                self.assertNotIn(private_sentinel, str(raised.exception))
            persisted = "".join(path.read_text(encoding="utf-8") for path in paths.memory_dir.rglob("*.json"))
            self.assertNotIn(private_sentinel, persisted)

    def test_M1_M2_two_principals_share_thread_without_cross_user_recall(self) -> None:
        # Given user-only A/B records and reviewed shared project audiences.
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / "omh", Path(tmp) / "hermes")
            _approved(paths, "A-only preference", _context(PRINCIPAL_A))
            _approved(paths, "B-only preference", _context(PRINCIPAL_B))
            _approved(paths, "Both principals project fact", _context(PRINCIPAL_A), audience=(PRINCIPAL_A, PRINCIPAL_B))
            _approved(paths, "A-only shared project fact", _context(PRINCIPAL_A), audience=(PRINCIPAL_A,))

            # When each principal recalls from the same profile and thread.
            text_a, _ = _provider_pack(paths, _context(PRINCIPAL_A))
            text_b, _ = _provider_pack(paths, _context(PRINCIPAL_B))

            # Then personal and explicit audience boundaries are independent.
            self.assertIn("A-only preference", text_a)
            self.assertNotIn("B-only preference", text_a)
            self.assertIn("B-only preference", text_b)
            self.assertNotIn("A-only preference", text_b)
            self.assertIn("Both principals project fact", text_a)
            self.assertIn("Both principals project fact", text_b)
            self.assertNotIn("A-only shared project fact", text_b)

    def test_M3_nonhuman_missing_and_wrong_profile_turns_fail_closed(self) -> None:
        # Given one approved personal record in a shared provider.
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / "omh", Path(tmp) / "hermes")
            _approved(paths, "Private human preference", _context(PRINCIPAL_A))
            write_memory_block(paths.omh_home, approve_memory_block(build_memory_block("legacy-block", "unbound-block-value")))

            # When unresolved and nonhuman actors recall.
            contexts = (
                None,
                _context(None, actor_kind="ambiguous"),
                _context(None, actor_kind="bot"),
                _context(None, actor_kind="system"),
                _context(PRINCIPAL_A, profile="wrong_profile"),
                _context(PRINCIPAL_A, turn="turn_2"),
            )

            # Then none receives personal content or a stale prepared pack.
            for context in contexts:
                with self.subTest(context=context):
                    text, receipt = _provider_pack(paths, context)
                    self.assertNotIn("Private human preference", text)
                    self.assertNotIn("unbound-block-value", text)
                    self.assertEqual(receipt["principal_decision"]["allowed_count"], 0)

    def test_M4_capture_receipt_separates_roles_and_discards_raw_identity(self) -> None:
        # Given a raw host id and source body at the local boundary.
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / "omh", Path(tmp) / "hermes")
            raw_id, raw_body = "platform-user-raw-123", "message-body-sentinel"
            principal = derive_principal_ref(paths.omh_home, profile_ref="profile_fixture", surface_ref="fixture", host_identity=raw_id)
            context = _context(principal)

            # When capture and approval bind distinct roles.
            captured: Any = capture_project_memory_candidate(paths, "Bound preference", content=raw_body, scope_kind="user", principal_context=context)
            approved: Any = approve_project_memory_candidate(paths, str(captured["candidate"]["candidate_id"]), reviewer_principal=PRINCIPAL_B)
            serialized = json.dumps({"captured": captured, "approved": approved}, sort_keys=True)

            # Then only opaque/digest provenance survives.
            receipt: Any = captured["capture_receipt"]
            identity: Any = approved["record"]["identity"]
            self.assertEqual(receipt["subject_principal"], principal)
            self.assertEqual(receipt["event_actor"]["principal"], principal)
            self.assertEqual(identity["reviewer"]["principal"], PRINCIPAL_B)
            self.assertEqual(identity["executor_perspective"], "hermes")
            self.assertNotIn(raw_id, serialized)
            self.assertNotIn(raw_body, serialized)
            # The chmod contract is POSIX-only; Windows attains 0o666 instead
            # (docs/INSTALLATION.md, POSIX-only surfaces).
            expected_mode = 0o666 if os.name == "nt" else 0o600
            self.assertEqual((paths.memory_dir / "principal.key").stat().st_mode & 0o777, expected_mode)

    def test_M7_receipts_and_native_write_observation_are_redacted(self) -> None:
        # Given a provider with one principal-bound record.
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / "omh", Path(tmp) / "hermes")
            _approved(paths, "Receipt fixture fact", _context(PRINCIPAL_A))
            provider = OmhMemoryProvider(omh_home=paths.omh_home, hermes_home=paths.hermes_home)
            try:
                provider.initialize("shared_fixture", cwd=Path(tmp), principal_context=_context(PRINCIPAL_A), shared_surface=True)
                provider.on_turn_start(1, "fixture", principal_context=_context(PRINCIPAL_A))
                provider.queue_prefetch("fixture", session_id="shared_fixture", now=NOW)
                provider.prefetch("fixture", session_id="shared_fixture")
                receipt = provider.latest_prefetch_receipt() or {}
                provider.on_memory_write("add", "user", "native-write-body-sentinel", metadata=_context(PRINCIPAL_A))
            finally:
                provider.shutdown()

            # Then receipt/write evidence is decision metadata, not content or admission.
            journal = (paths.memory_dir / "write_journal.jsonl").read_text()
            self.assertEqual(receipt["schema_version"], "omh_memory_prefetch_receipt/v3")
            self.assertEqual(receipt["principal_decision"]["principal_ref"], PRINCIPAL_A)
            self.assertNotIn("Receipt fixture fact", json.dumps(receipt))
            self.assertNotIn("native-write-body-sentinel", journal)
            self.assertIn('"admission_performed": false', journal)

    def test_M8_nonshared_legacy_project_scope_requires_explicit_inspection(self) -> None:
        # Given an existing v2 project record.
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / "omh", Path(tmp) / "hermes")
            captured: Any = capture_project_memory_candidate(paths, "Legacy project compatibility", scope_kind="project", scope_ref="default")
            approve_project_memory_candidate(paths, str(captured["candidate"]["candidate_id"]))

            # When a nonshared provider recalls through the existing scope.
            provider = OmhMemoryProvider(omh_home=paths.omh_home, hermes_home=paths.hermes_home)
            try:
                provider.initialize("shared_fixture", cwd=Path(tmp), platform="cli", shared_surface=False)
                provider.queue_prefetch("compatibility", session_id="shared_fixture", now=NOW)
                text = provider.prefetch("compatibility", session_id="shared_fixture")
            finally:
                provider.shutdown()

            # Basename records remain inspectable, but never enter automatic recall.
            self.assertNotIn("Legacy project compatibility", text)
            from omh.workflows.memory import build_project_memory_recall_pack
            inspection = build_project_memory_recall_pack(paths, scope_kind="project", scope_ref="default")
            self.assertEqual(inspection["record_count"], 1)


if __name__ == "__main__":
    unittest.main()
