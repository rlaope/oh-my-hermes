from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

from _local_package import load_local_package

load_local_package()

from omh.paths import OmhPaths
from omh.visual_summary import (
    build_visual_observation,
    build_visual_prompt_card,
    validate_visual_observation,
    visual_card_identity_digest,
)
from omh.workflows.visual_generation_receipts import (
    CLAIM_BOUNDARY,
    DOES_NOT_PROVE,
    MAX_ARTIFACT_BYTES,
    RECEIPT_KEYS,
    ROUTE_CLAIM_BOUNDARY,
    ROUTE_FIELDS,
    UNKNOWN,
    USAGE_METRIC_NAMES,
    VISUAL_GENERATION_RECEIPT_PROJECTION_SCHEMA_VERSION,
    VISUAL_GENERATION_RECEIPT_SCHEMA_VERSION,
    VISUAL_GENERATION_ROUTE_EVIDENCE_SCHEMA_VERSION,
    VisualGenerationReceiptError,
    bind_visual_generation_receipt,
    build_visual_generation_receipt,
    generated_image_binding_errors,
    latest_receipt_for_effect,
    observed_route_field,
    parse_usage_arg,
    project_legacy_visual_observation,
    read_visual_generation_receipt,
    read_visual_generation_receipts,
    record_visual_generation_receipt,
    route_evidence,
    route_status_warnings,
    usage_reading,
    validate_visual_generation_receipt,
    validate_visual_generation_receipt_store,
    visual_generation_effect_id,
)


DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
SOURCE_DIGEST = "c" * 64


def _card(**overrides):
    fields = {
        "kind": "github_pr",
        "sections": [{"role": "summary", "title": "What changed", "image_text": "Route evidence contract landed."}],
    }
    fields.update(overrides)
    return build_visual_prompt_card(**fields)


def _receipt(card, **overrides):
    fields = {
        "card_id": card["card_id"],
        "card_digest": card["card_digest"],
        "action_id": "act-1",
        "attempt_id": "att-1",
        "producer": "hermes-image-connector",
        "outcome": "succeeded",
        "requested_route": {
            "provider": "gpt-image",
            "model": "gpt-image-1",
            "quality": "high",
            "operation": "generate",
            "dimensions": "1024x1536",
            "credential_class": "host_managed",
        },
        "observed_route": {},
        "attested_route_fields": (),
        "artifact": {
            "artifact_ref": "art-1",
            "content_sha256": DIGEST_A,
            "mime_type": "image/png",
            "byte_size": 4096,
            "provider_response_ref": "resp-1",
        },
        "input_lineage": {"source_image_count": 0},
        "usage": {},
        "summary": "connector reported one image",
    }
    fields.update(overrides)
    return build_visual_generation_receipt(**fields)


class VisualGenerationReceiptContractTests(unittest.TestCase):
    def test_card_publishes_the_digest_a_receipt_binds(self) -> None:
        card = _card()
        self.assertEqual(card["card_digest"], visual_card_identity_digest(card))
        # A revision moves the digest, which is what makes a stale-card warning
        # possible at all.
        revised = _card(headline="A revised headline")
        self.assertNotEqual(revised["card_digest"], card["card_digest"])
        self.assertEqual(_card()["card_digest"], card["card_digest"])

    def test_requested_route_never_becomes_observed_route(self) -> None:
        """A successful artifact cannot promote requested intent into evidence."""
        card = _card()
        receipt = _receipt(card)
        self.assertEqual(receipt["schema_version"], VISUAL_GENERATION_RECEIPT_SCHEMA_VERSION)
        self.assertEqual(receipt["claim_boundary"], CLAIM_BOUNDARY)
        self.assertEqual(receipt["route_claim_boundary"], ROUTE_CLAIM_BOUNDARY)
        self.assertEqual(receipt["does_not_prove"], list(DOES_NOT_PROVE))
        self.assertEqual(sorted(receipt), sorted(RECEIPT_KEYS))
        self.assertEqual(receipt["requested_route"]["model"], "gpt-image-1")
        for field in ROUTE_FIELDS:
            with self.subTest(field=field):
                self.assertEqual(receipt["observed_route"][field], UNKNOWN)
                self.assertEqual(observed_route_field(receipt, field), UNKNOWN)
        self.assertEqual(receipt["attested_route_fields"], [])
        self.assertEqual(validate_visual_generation_receipt(receipt), [])

    def test_attested_fields_are_the_only_bridge_to_observed_route(self) -> None:
        card = _card()
        receipt = _receipt(
            card,
            observed_route={"provider": "gpt-image", "model": "gpt-image-1-mini", "operation": "generate"},
            attested_route_fields=("provider", "model", "operation"),
        )
        self.assertEqual(observed_route_field(receipt, "provider"), "gpt-image")
        self.assertEqual(observed_route_field(receipt, "model"), "gpt-image-1-mini")
        self.assertEqual(observed_route_field(receipt, "quality"), UNKNOWN)
        # A hand-edited store that filled an observed field in without attesting
        # it still reads as unknown.
        tampered = deepcopy(receipt)
        tampered["observed_route"]["quality"] = "high"
        self.assertEqual(observed_route_field(tampered, "quality"), UNKNOWN)
        self.assertIn(
            "observed_route quality must be unknown unless it is named in attested_route_fields",
            " ".join(validate_visual_generation_receipt(tampered)),
        )

    def test_attesting_nothing_is_not_an_attestation(self) -> None:
        card = _card()
        with self.assertRaisesRegex(VisualGenerationReceiptError, "attested but unknown"):
            _receipt(card, observed_route={"model": UNKNOWN}, attested_route_fields=("model",))

    def test_route_evidence_reports_mismatch_and_unknown_without_resolving_either(self) -> None:
        card = _card()
        receipt = _receipt(
            card,
            observed_route={"provider": "gpt-image", "model": "gpt-image-1-mini", "operation": "generate"},
            attested_route_fields=("provider", "model", "operation"),
        )
        evidence = route_evidence(receipt)
        self.assertEqual(evidence["schema_version"], VISUAL_GENERATION_ROUTE_EVIDENCE_SCHEMA_VERSION)
        self.assertEqual(evidence["mismatched_route_fields"], ["model"])
        self.assertEqual(evidence["unknown_route_fields"], ["quality"])
        self.assertEqual(evidence["warnings"], ["route_mismatch:model", "unknown_observed_route:quality"])
        self.assertEqual(evidence["requested_route"]["model"], "gpt-image-1")
        self.assertEqual(evidence["observed_route"]["model"], "gpt-image-1-mini")
        self.assertEqual(evidence["claim_boundary"], ROUTE_CLAIM_BOUNDARY)

    def test_successful_artifact_alone_keeps_every_route_field_unavailable(self) -> None:
        """The second fixture of AC2: a file, and nothing said about the route."""
        card = _card()
        receipt = _receipt(card)
        evidence = route_evidence(receipt)
        self.assertEqual(evidence["attested_route_fields"], [])
        self.assertEqual(evidence["mismatched_route_fields"], [])
        self.assertEqual(
            evidence["warnings"],
            [
                "unknown_observed_route:provider",
                "unknown_observed_route:model",
                "unknown_observed_route:quality",
                "unknown_observed_route:operation",
            ],
        )
        self.assertEqual(evidence["observed_route"], {field: UNKNOWN for field in ROUTE_FIELDS})

    def test_two_provider_fixtures_carry_different_attested_capability(self) -> None:
        """Provider-specific behaviour stays in the fixtures, never in OMH core."""
        card = _card()
        rich = _receipt(
            card,
            attempt_id="att-rich",
            observed_route={
                "provider": "gpt-image",
                "model": "gpt-image-1",
                "quality": "high",
                "operation": "generate",
                "dimensions": "1024x1536",
                "credential_class": "host_managed",
            },
            attested_route_fields=ROUTE_FIELDS,
            usage={
                "image_units": {"value": 1, "measurement": "measured"},
                "cost_usd": {"value": 0.04, "measurement": "estimated"},
            },
        )
        sparse = _receipt(
            card,
            attempt_id="att-sparse",
            requested_route={
                "provider": "generic-image-tool",
                "model": "unknown",
                "quality": "unknown",
                "operation": "generate",
                "dimensions": "unknown",
                "credential_class": "user_supplied",
            },
            observed_route={"provider": "generic-image-tool"},
            attested_route_fields=("provider",),
        )
        self.assertEqual(route_evidence(rich)["unknown_route_fields"], [])
        self.assertEqual(route_evidence(rich)["mismatched_route_fields"], [])
        self.assertEqual(route_evidence(sparse)["unknown_route_fields"], ["model", "quality", "operation"])
        # A requested value of `unknown` is not a mismatch; it is nothing asked for.
        self.assertEqual(route_evidence(sparse)["mismatched_route_fields"], [])
        self.assertEqual(usage_reading(rich, "cost_usd"), {"value": 0.04, "measurement": "estimated"})
        self.assertEqual(usage_reading(sparse, "cost_usd"), {"value": None, "measurement": "unavailable"})

    def test_rejects_unsupported_operation_credential_class_and_outcome(self) -> None:
        card = _card()
        with self.assertRaisesRegex(VisualGenerationReceiptError, "outcome is unsupported"):
            _receipt(card, outcome="probably")
        with self.assertRaisesRegex(VisualGenerationReceiptError, "requested_route operation must be one of"):
            _receipt(card, requested_route={"operation": "upscale"})
        with self.assertRaisesRegex(VisualGenerationReceiptError, "credential_class is unsupported"):
            _receipt(
                card,
                requested_route={"operation": "generate", "credential_class": "raw_api_key"},
            )

    def test_rejects_foreign_attempt_ids_and_stale_card_identities(self) -> None:
        card = _card()
        receipt = _receipt(card)
        self.assertEqual(
            receipt["effect_id"], visual_generation_effect_id(card["card_id"], "act-1", "att-1")
        )
        for field, value in (("attempt_id", "att-elsewhere"), ("action_id", "act-elsewhere")):
            with self.subTest(field=field):
                foreign = deepcopy(receipt)
                foreign[field] = value
                self.assertIn(
                    "effect_id must be", " ".join(validate_visual_generation_receipt(foreign))
                )
        # Two accepted actions that number their attempts the same way are two
        # attempts, not one superseding the other.
        other_action = _receipt(card, action_id="act-2")
        self.assertNotEqual(other_action["effect_id"], receipt["effect_id"])
        with self.assertRaisesRegex(VisualGenerationReceiptError, "card_digest must be a sha256 hex digest"):
            _receipt(card, card_digest="not-a-digest")
        stale = _receipt(card, attempt_id="att-2", card_digest=DIGEST_B)
        self.assertEqual(
            route_status_warnings([stale], card_digest=card["card_digest"]),
            [f"stale_card_identity:{stale['receipt_id']}"],
        )
        self.assertEqual(route_status_warnings([receipt], card_digest=card["card_digest"]), [])

    def test_failed_and_partial_attempts_keep_a_stage_and_no_artifact(self) -> None:
        card = _card()
        failed = _receipt(
            card,
            outcome="failed",
            failure_stage="authorization",
            attempt_id="att-failed",
            artifact={},
        )
        self.assertEqual(failed["failure_stage"], "authorization")
        self.assertEqual(failed["artifact"]["content_sha256"], "")
        self.assertIsNone(failed["artifact"]["byte_size"])
        with self.assertRaisesRegex(VisualGenerationReceiptError, "must name the stage it stopped at"):
            _receipt(card, outcome="failed", attempt_id="att-x", artifact={})
        with self.assertRaisesRegex(VisualGenerationReceiptError, "succeeded must carry failure_stage none"):
            _receipt(card, failure_stage="provider")
        with self.assertRaisesRegex(VisualGenerationReceiptError, "must be empty unless the attempt succeeded"):
            _receipt(card, outcome="partial", failure_stage="download", attempt_id="att-p")

    def test_succeeded_requires_a_content_digest_size_and_supported_mime(self) -> None:
        card = _card()
        with self.assertRaisesRegex(VisualGenerationReceiptError, "content_sha256 must be a sha256 hex digest"):
            _receipt(card, artifact={"artifact_ref": "art-1", "content_sha256": "nope", "mime_type": "image/png", "byte_size": 1})
        with self.assertRaisesRegex(VisualGenerationReceiptError, "mime_type must be one of"):
            _receipt(card, artifact={"artifact_ref": "art-1", "content_sha256": DIGEST_A, "mime_type": "image/gif", "byte_size": 1})
        with self.assertRaisesRegex(VisualGenerationReceiptError, "byte_size must be a positive integer"):
            _receipt(card, artifact={"artifact_ref": "art-1", "content_sha256": DIGEST_A, "mime_type": "image/png", "byte_size": 0})
        with self.assertRaisesRegex(VisualGenerationReceiptError, "byte_size must be at most"):
            _receipt(
                card,
                artifact={
                    "artifact_ref": "art-1",
                    "content_sha256": DIGEST_A,
                    "mime_type": "image/png",
                    "byte_size": MAX_ARTIFACT_BYTES + 1,
                },
            )

    def test_edit_lineage_is_bounded_and_generate_lineage_is_empty(self) -> None:
        card = _card()
        edit = _receipt(
            card,
            attempt_id="att-edit",
            requested_route={
                "provider": "gpt-image",
                "model": "gpt-image-1",
                "quality": "high",
                "operation": "edit",
                "dimensions": "1024x1536",
                "credential_class": "host_managed",
            },
            input_lineage={
                "source_image_count": 1,
                "source_image_digests": [SOURCE_DIGEST],
                "edit_constraints": ["preserve", "remove"],
            },
        )
        self.assertEqual(edit["input_lineage"]["source_image_digests"], [SOURCE_DIGEST])
        self.assertEqual(edit["input_lineage"]["edit_constraints"], ["preserve", "remove"])
        with self.assertRaisesRegex(VisualGenerationReceiptError, "a generate request has no source images"):
            _receipt(card, attempt_id="att-bad", input_lineage={"source_image_count": 2})
        with self.assertRaisesRegex(VisualGenerationReceiptError, "must be empty or name every source image"):
            _receipt(
                card,
                attempt_id="att-bad2",
                requested_route={"operation": "edit", "credential_class": "host_managed"},
                input_lineage={"source_image_count": 2, "source_image_digests": [SOURCE_DIGEST]},
            )
        with self.assertRaisesRegex(VisualGenerationReceiptError, "must be a sha256 hex digest"):
            _receipt(
                card,
                attempt_id="att-bad3",
                requested_route={"operation": "edit", "credential_class": "host_managed"},
                input_lineage={"source_image_count": 1, "source_image_digests": ["/private/photo.png"]},
            )

    def test_receipt_stores_no_prompt_path_credential_or_provider_body(self) -> None:
        card = _card()
        # Offered to the record, and refused, rather than merely absent from a
        # record that was never given them.
        with self.assertRaisesRegex(VisualGenerationReceiptError, "not a filesystem path"):
            _receipt(card, attempt_id="att-path", artifact={
                "artifact_ref": "private/var/folders/omh/card.png",
                "content_sha256": DIGEST_A,
                "mime_type": "image/png",
                "byte_size": 4096,
            })
        with self.assertRaisesRegex(VisualGenerationReceiptError, "not a filesystem path"):
            _receipt(card, attempt_id="att-evidence", evidence_refs=("Users/demo/mockups/card.png",))
        # A raw prompt pasted into the one free-text field is redacted, not
        # truncated: the value is not a summary that ran long.
        prompt_line = " ".join(card["generation_prompt"].split())[:180]
        self.assertEqual(_receipt(card, attempt_id="att-prompt", summary=prompt_line)["summary"], "[redacted]")
        self.assertEqual(
            len(_receipt(card, attempt_id="att-long", summary="word " * 200)["summary"]), 200
        )
        with self.assertRaisesRegex(VisualGenerationReceiptError, "must be an opaque identifier, not a URL"):
            _receipt(card, attempt_id="att-url", producer="https://images.example.com/v1")
        redacted = _receipt(card, attempt_id="att-redacted", summary="used sk_live_abcdefghijklmnop")
        self.assertEqual(redacted["summary"], "[redacted]")
        raw = _receipt(card, attempt_id="att-raw")
        raw["prompt"] = "a raw prompt"
        self.assertIn(
            "must not carry raw or hidden keys: ['prompt']",
            " ".join(validate_visual_generation_receipt(raw)),
        )
        unsupported = _receipt(card, attempt_id="att-extra")
        unsupported["observed_model_from_config"] = "gpt-image-1"
        self.assertIn(
            "has unsupported keys: ['observed_model_from_config']",
            " ".join(validate_visual_generation_receipt(unsupported)),
        )

    def test_usage_is_producer_attributed_and_absence_is_never_zero(self) -> None:
        card = _card()
        receipt = _receipt(
            card,
            usage={
                "input_tokens": {"value": 0, "measurement": "measured"},
                "cost_usd": {"value": 0.02, "measurement": "estimated"},
            },
        )
        # A reported zero survives as a measured zero.
        self.assertEqual(usage_reading(receipt, "input_tokens"), {"value": 0, "measurement": "measured"})
        self.assertEqual(usage_reading(receipt, "cost_usd"), {"value": 0.02, "measurement": "estimated"})
        for name in ("output_tokens", "image_units"):
            with self.subTest(name=name):
                self.assertEqual(usage_reading(receipt, name), {"value": None, "measurement": "unavailable"})
        stored_unavailable = deepcopy(receipt)
        stored_unavailable["usage"]["image_units"] = {"value": None, "measurement": "unavailable"}
        self.assertIn(
            "must be omitted rather than stored as unavailable",
            " ".join(validate_visual_generation_receipt(stored_unavailable)),
        )
        oversized = deepcopy(receipt)
        oversized["usage"]["image_units"] = {"value": 10**12, "measurement": "measured"}
        self.assertIn("value must be from 0 to", " ".join(validate_visual_generation_receipt(oversized)))
        malformed = deepcopy(receipt)
        malformed["usage"]["image_units"] = {"value": "one", "measurement": "measured"}
        self.assertIn("value must be a number", " ".join(validate_visual_generation_receipt(malformed)))

    def test_usage_arguments_require_an_explicit_measurement(self) -> None:
        self.assertEqual(parse_usage_arg("cost_usd=0.04:estimated"), ("cost_usd", {"value": 0.04, "measurement": "estimated"}))
        self.assertEqual(parse_usage_arg("image_units=2:measured"), ("image_units", {"value": 2, "measurement": "measured"}))
        with self.assertRaisesRegex(ValueError, "NAME=VALUE:MEASUREMENT"):
            parse_usage_arg("cost_usd=0.04")
        with self.assertRaisesRegex(ValueError, "omit the metric when it is unavailable"):
            parse_usage_arg("cost_usd=0.04:unavailable")
        with self.assertRaisesRegex(ValueError, "must be one of"):
            parse_usage_arg("mystery=1:measured")

    def test_reuses_a_wrapper_supplied_effect_identity_instead_of_minting_a_rival(self) -> None:
        card = _card()
        receipt = _receipt(card, external_effect_ref="message_sent:run-77")
        self.assertEqual(receipt["external_effect_ref"], "message_sent:run-77")
        self.assertEqual(validate_visual_generation_receipt(receipt), [])


class VisualGenerationReceiptStoreTests(unittest.TestCase):
    def test_reporting_one_attempt_twice_records_one_receipt(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = OmhPaths(omh_home=Path(tmp) / ".omh", hermes_home=Path(tmp) / ".hermes")
            card = _card()
            fields = {
                "card_id": card["card_id"],
                "card_digest": card["card_digest"],
                "action_id": "act-1",
                "attempt_id": "att-1",
                "producer": "hermes-image-connector",
                "outcome": "succeeded",
                "requested_route": {"operation": "generate", "provider": "gpt-image"},
                "artifact": {
                    "artifact_ref": "art-1",
                    "content_sha256": DIGEST_A,
                    "mime_type": "image/png",
                    "byte_size": 4096,
                },
                "summary": "one image",
            }
            first, minted_first = record_visual_generation_receipt(paths, **fields)
            second, minted_second = record_visual_generation_receipt(paths, **fields)
            self.assertTrue(minted_first)
            self.assertFalse(minted_second)
            self.assertEqual(first["receipt_id"], second["receipt_id"])
            self.assertEqual(len(read_visual_generation_receipts(paths, card_id=card["card_id"])), 1)

            # The same reference carrying different bytes is a different result,
            # so it mints its own receipt linked to the earlier one.
            replaced_fields = dict(fields)
            replaced_fields["artifact"] = dict(fields["artifact"], content_sha256=DIGEST_B)
            replaced, minted_replaced = record_visual_generation_receipt(paths, **replaced_fields)
            self.assertTrue(minted_replaced)
            self.assertNotEqual(replaced["receipt_id"], first["receipt_id"])
            self.assertEqual(replaced["supersedes_receipt_ref"], first["receipt_id"])

            receipts = read_visual_generation_receipts(paths, card_id=card["card_id"])
            self.assertEqual(len(receipts), 2)
            self.assertEqual(
                latest_receipt_for_effect(receipts, first["effect_id"])["receipt_id"], replaced["receipt_id"]
            )
            self.assertEqual(
                route_status_warnings(receipts, card_digest=card["card_digest"]),
                ["artifact_digest_drift:art-1"],
            )
            self.assertEqual(read_visual_generation_receipt(paths, replaced["receipt_id"]), replaced)

            report = validate_visual_generation_receipt_store(paths.visual_generation_receipts_path)
            self.assertTrue(report["ok"], report["errors"])
            self.assertEqual(report["receipt_count"], 2)

    def test_store_reports_unparseable_lines_and_broken_chains(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = OmhPaths(omh_home=Path(tmp) / ".omh", hermes_home=Path(tmp) / ".hermes")
            path = paths.visual_generation_receipts_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{not json}\n", encoding="utf-8")
            report = validate_visual_generation_receipt_store(path)
            self.assertFalse(report["ok"])
            self.assertTrue(report["errors"])

    def test_store_reports_duplicate_receipt_ids_and_forked_chains(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = OmhPaths(omh_home=Path(tmp) / ".omh", hermes_home=Path(tmp) / ".hermes")
            path = paths.visual_generation_receipts_path
            path.parent.mkdir(parents=True, exist_ok=True)
            card = _card()
            first = _receipt(card, attempt_id="att-1")
            duplicate = deepcopy(first)
            duplicate["summary"] = "a different payload under the same receipt id"
            second = _receipt(card, attempt_id="att-2", supersedes_receipt_ref=first["receipt_id"])
            fork = _receipt(card, attempt_id="att-3", supersedes_receipt_ref=first["receipt_id"])
            path.write_text(
                "".join(json.dumps(record, sort_keys=True) + "\n" for record in (first, duplicate, second, fork)),
                encoding="utf-8",
            )
            report = validate_visual_generation_receipt_store(path)
            self.assertFalse(report["ok"])
            joined = " ".join(report["errors"])
            self.assertIn("receipt_id is not unique", joined)
            self.assertIn("forks the chain", joined)

    def test_one_provider_response_credited_to_two_attempts_is_reported(self) -> None:
        card = _card()
        first = _receipt(card, attempt_id="att-1")
        second = _receipt(card, attempt_id="att-2", artifact={
            "artifact_ref": "art-2",
            "content_sha256": DIGEST_B,
            "mime_type": "image/png",
            "byte_size": 2048,
            "provider_response_ref": "resp-1",
        })
        self.assertIn(
            "provider_response_reuse:resp-1",
            route_status_warnings([first, second], card_digest=card["card_digest"]),
        )
        self.assertEqual(route_status_warnings([first], card_digest=card["card_digest"]), [])


class VisualObservationBindingTests(unittest.TestCase):
    def _observation(self, card):
        return build_visual_observation(
            card_id=card["card_id"],
            observation_type="generated-image",
            path_or_uri="/tmp/omh-card.png",
            evidence_summary="wrapper reported a PNG",
        )

    def test_unbound_observation_says_it_cannot_name_a_route(self) -> None:
        card = _card()
        observation = self._observation(card)
        self.assertEqual(observation["generation_receipt"], {})
        self.assertIn("generation_route_attested", observation["does_not_prove"])
        self.assertEqual(observation["artifact"]["content_sha256"], "")
        self.assertIsNone(observation["artifact"]["byte_size"])
        self.assertEqual(validate_visual_observation(observation), [])

    def test_binding_a_succeeded_receipt_carries_attempt_and_digest_but_not_route(self) -> None:
        card = _card()
        receipt = _receipt(
            card,
            observed_route={"provider": "gpt-image", "model": "gpt-image-1"},
            attested_route_fields=("provider", "model"),
        )
        bound = bind_visual_generation_receipt(self._observation(card), receipt)
        self.assertEqual(bound["generation_receipt"]["receipt_id"], receipt["receipt_id"])
        self.assertEqual(bound["generation_receipt"]["attempt_id"], "att-1")
        self.assertEqual(bound["generation_receipt"]["card_digest"], card["card_digest"])
        self.assertEqual(bound["artifact"]["content_sha256"], DIGEST_A)
        self.assertEqual(bound["artifact"]["byte_size"], 4096)
        self.assertNotIn("generation_route_attested", bound["does_not_prove"])
        self.assertIn("visual_qa_passed", bound["does_not_prove"])
        self.assertNotIn("provider", json.dumps(bound["generation_receipt"]))
        self.assertEqual(validate_visual_observation(bound), [])

    def test_failed_partial_and_foreign_receipts_cannot_mint_image_evidence(self) -> None:
        card = _card()
        other = _card(headline="A different card")
        observation = self._observation(card)
        failed = _receipt(card, outcome="failed", failure_stage="provider", attempt_id="att-f", artifact={})
        with self.assertRaisesRegex(VisualGenerationReceiptError, "is not generated-image evidence"):
            bind_visual_generation_receipt(observation, failed)
        partial = _receipt(card, outcome="partial", failure_stage="download", attempt_id="att-pp", artifact={})
        self.assertTrue(generated_image_binding_errors(partial, card_id=card["card_id"]))
        foreign = _receipt(other, attempt_id="att-other")
        with self.assertRaisesRegex(VisualGenerationReceiptError, "does not match the observed card"):
            bind_visual_generation_receipt(observation, foreign)

    def test_a_receipt_cannot_bind_an_image_it_is_not_about(self) -> None:
        card = _card()
        jpeg = build_visual_observation(
            card_id=card["card_id"],
            observation_type="generated-image",
            path_or_uri="/tmp/other-image.jpeg",
            evidence_summary="a different file was reported",
        )
        with self.assertRaisesRegex(VisualGenerationReceiptError, "a receipt binds the image it is about"):
            bind_visual_generation_receipt(jpeg, _receipt(card))
        already_digested = deepcopy(self._observation(card))
        already_digested["artifact"]["content_sha256"] = DIGEST_B
        with self.assertRaisesRegex(VisualGenerationReceiptError, "never overwrites a digest"):
            bind_visual_generation_receipt(already_digested, _receipt(card))

    def test_a_binding_on_qa_or_delivery_evidence_is_refused_by_the_contract(self) -> None:
        """The rule lives in the validator, not only in the function that writes it."""
        card = _card()
        bound = bind_visual_generation_receipt(self._observation(card), _receipt(card))
        for observation_type in ("visual_qa_observed", "delivery_observed"):
            with self.subTest(observation_type=observation_type):
                crossed = deepcopy(bound)
                crossed["observation_type"] = observation_type
                crossed["does_not_prove"] = ["delivered"]
                self.assertIn(
                    "generation_receipt binds a generated_image_observed observation only; "
                    "visual QA and delivery are separate evidence states",
                    validate_visual_observation(crossed),
                )

    def test_a_receipt_binds_generated_image_evidence_only(self) -> None:
        card = _card()
        qa_observation = build_visual_observation(
            card_id=card["card_id"],
            observation_type="visual-qa",
            path_or_uri="/tmp/omh-card.png",
            evidence_summary="reviewer read the card",
        )
        with self.assertRaisesRegex(VisualGenerationReceiptError, "generated_image_observed observation only"):
            bind_visual_generation_receipt(qa_observation, _receipt(card))

    def test_observation_validator_rejects_a_binding_that_disagrees_with_the_artifact(self) -> None:
        card = _card()
        bound = bind_visual_generation_receipt(self._observation(card), _receipt(card))
        drifted = deepcopy(bound)
        drifted["artifact"]["content_sha256"] = DIGEST_B
        self.assertIn(
            "artifact.content_sha256 must match generation_receipt.content_sha256",
            validate_visual_observation(drifted),
        )
        silent = deepcopy(bound)
        silent["does_not_prove"] = ["visual_qa_passed", "delivered", "generation_route_attested"]
        self.assertIn(
            "does_not_prove must drop generation_route_attested once a receipt binds the observation",
            validate_visual_observation(silent),
        )

    def test_legacy_observations_project_every_new_field_as_unknown(self) -> None:
        legacy = {
            "schema_version": "visual_observation/v1",
            "observation_id": "20260101T000000Z-card-generated-image-abc123",
            "visual_card_id": "github-pr-000000000000",
            "observation_type": "generated_image_observed",
            "status": "observed",
            "observed_at": "2026-01-01T00:00:00Z",
            "observer": "wrapper_or_user",
            "artifact": {"kind": "image", "path_or_uri": "/tmp/legacy.png", "mime_type": "image/png"},
            "evidence_summary": "a PNG appeared",
            "does_not_prove": ["visual_qa_passed", "delivered"],
        }
        # The legacy record still validates: absence of the binding key is not a fault.
        self.assertEqual(validate_visual_observation(legacy), [])
        projection = project_legacy_visual_observation(legacy)
        self.assertEqual(projection["schema_version"], VISUAL_GENERATION_RECEIPT_PROJECTION_SCHEMA_VERSION)
        self.assertEqual(projection["source_schema"], "visual_observation/v1")
        for field in ROUTE_FIELDS:
            with self.subTest(field=field):
                self.assertEqual(projection["requested_route"][field], UNKNOWN)
                self.assertEqual(projection["observed_route"][field], UNKNOWN)
        self.assertEqual(projection["attested_route_fields"], [])
        for name in ("attempt_id", "action_id", "card_digest", "producer"):
            with self.subTest(name=name):
                self.assertEqual(projection[name], UNKNOWN)
        self.assertEqual(projection["artifact"]["content_sha256"], UNKNOWN)
        self.assertEqual(projection["artifact"]["artifact_ref"], UNKNOWN)
        self.assertIsNone(projection["artifact"]["byte_size"])
        self.assertIsNone(projection["input_lineage"]["source_image_count"])
        for name in USAGE_METRIC_NAMES:
            with self.subTest(name=name):
                self.assertEqual(projection["usage"][name], {"value": None, "measurement": "unavailable"})
        self.assertEqual(projection["route_claim_boundary"], ROUTE_CLAIM_BOUNDARY)

    def test_projection_of_a_bound_observation_keeps_the_receipt_reference(self) -> None:
        card = _card()
        bound = bind_visual_generation_receipt(self._observation(card), _receipt(card))
        projection = project_legacy_visual_observation(bound)
        self.assertEqual(projection["attempt_id"], "att-1")
        self.assertEqual(projection["card_digest"], card["card_digest"])
        self.assertEqual(projection["artifact"]["content_sha256"], DIGEST_A)
        # The projection still refuses to name a route: that is on the receipt.
        self.assertEqual(projection["observed_route"], {field: UNKNOWN for field in ROUTE_FIELDS})


if __name__ == "__main__":
    unittest.main()
