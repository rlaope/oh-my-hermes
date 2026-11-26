"""Contracts for `native_capability_change_preview/v1` (issue #794).

Grouped by acceptance criterion:

- AC1: routing, skill, memory, wrapper, handoff, evidence, docs, and tests are
  each marked changed, unchanged, or not applicable -- all eight, every time,
  with `unchanged` and `not_applicable` staying two answers rather than one.
- AC2: a material change produces a new digest and requires renewed review; a
  non-material one does not. Both directions, with the line under test.
- AC3: an accepted preview cannot be described as implemented or available,
  asserted across the whole status vocabulary rather than on one example.

Plus the guards the artifact would be useless without: an unknown axis and an
unknown state are refused, the key set is closed in both directions, and the
digest reads no clock.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

from _local_package import load_local_package

load_local_package()
from omh.workflows.native_capability_change_preview import (
    AXIS_KEYS,
    AXIS_STATES,
    CHANGE_AXES,
    DERIVED_PREVIEW_KEYS,
    EXPLANATORY_FIELD,
    MATERIAL_PREVIEW_KEYS,
    NATIVE_CAPABILITY_CHANGE_PREVIEW_CLAIM_BOUNDARY,
    NATIVE_CAPABILITY_CHANGE_PREVIEW_KEYS,
    NATIVE_CAPABILITY_CHANGE_PREVIEW_SCHEMA_VERSION,
    PREVIEW_STATUS_CLAIMS,
    PREVIEW_STATUSES,
    PRIVACY_IMPACTS,
    REFUSED_PREVIEW_STATUSES,
    REVIEW_STATE_KEYS,
    REVIEW_STATES,
    ROLLBACK_BOUNDARIES,
    NativeCapabilityChangePreviewError,
    accept_native_capability_change_preview,
    build_native_capability_change_preview,
    material_preview_content,
    native_capability_change_preview_digest,
    preview_requires_renewed_review,
    preview_review_state,
    preview_status_claim,
    revise_native_capability_change_preview,
    validate_native_capability_change_preview,
)


REVIEWER = "demo"

AXES: tuple[dict[str, object], ...] = (
    {"axis": "routing", "state": "changed", "surfaces": ["routing.chat"], "note": "adds one phrase trigger"},
    {"axis": "skill", "state": "changed", "surfaces": ["skills.catalog"], "note": "adds one installable lane"},
    {"axis": "memory", "state": "unchanged", "note": "no record is retained by this change"},
    {"axis": "wrapper", "state": "not_applicable", "note": "no wrapper session carries a preview"},
    {"axis": "handoff", "state": "changed", "surfaces": ["coding.handoff"], "note": "pins the reviewed digest"},
    {"axis": "evidence", "state": "changed", "surfaces": ["workflows.preview"], "note": "adds a claim boundary"},
    {"axis": "docs", "state": "changed", "surfaces": ["docs.architecture"], "note": "adds a section"},
    {"axis": "tests", "state": "changed", "surfaces": ["tests.preview"], "note": "adds one contract file"},
)

BASE: dict[str, object] = {
    "capability_id": "native-capability-change-preview",
    "target_experience": "Hermes shows the whole OMH change before anyone starts building it.",
    "baseline": "OMH answers with a generic implementation plan that hides the product-wide impact.",
    "axes": AXES,
    "privacy_impact": "metadata_only",
    "rollback": {"boundary": "no_persisted_state", "note": "delete the module and its tests"},
    "handoff_scope": {
        "delegated": ["implement-preview-contract", "add-preview-tests"],
        "retained": ["shape-the-preview-with-the-user"],
        "note": "OMH shapes the preview and the selected coding owner builds it",
    },
    "verification_expectations": (
        {"id": "preview-unit-tests", "kind": "unit_test", "note": "eight axes and both digest directions"},
        {"id": "repo-lint", "kind": "lint_gate", "note": "pyflakes over src and tests"},
    ),
    "compatibility_risks": (
        {"id": "digest-churn", "severity": "low", "note": "a reworded note must not move the digest"},
    ),
}


def make_preview(**overrides: object) -> dict[str, object]:
    return build_native_capability_change_preview(**{**BASE, **overrides})


def axes_with(axis: str, **changes: object) -> list[dict[str, object]]:
    rows = [dict(row) for row in AXES]
    for index, row in enumerate(rows):
        if row["axis"] == axis:
            rows[index] = {**row, **changes}
    return rows


class ChangeAxisCoverageTests(unittest.TestCase):
    """AC1: every axis is answered, and the three answers stay three."""

    def test_the_axes_are_the_eight_the_criterion_names(self) -> None:
        self.assertEqual(
            CHANGE_AXES,
            ("routing", "skill", "memory", "wrapper", "handoff", "evidence", "docs", "tests"),
        )
        self.assertEqual(AXIS_STATES, ("changed", "unchanged", "not_applicable"))

    def test_every_axis_is_present_and_carries_one_of_the_three_states(self) -> None:
        preview = make_preview()
        self.assertEqual(validate_native_capability_change_preview(preview), [])
        self.assertEqual([row["axis"] for row in preview["axes"]], list(CHANGE_AXES))
        for row in preview["axes"]:
            self.assertIn(row["state"], AXIS_STATES, row)
            self.assertEqual(set(row), set(AXIS_KEYS))

    def test_a_preview_missing_an_axis_fails_validation_naming_it(self) -> None:
        with self.assertRaises(NativeCapabilityChangePreviewError) as raised:
            make_preview(axes=[row for row in AXES if row["axis"] != "tests"])
        self.assertIn("missing change axes: ['tests']", str(raised.exception))

        hand_built = dict(make_preview())
        hand_built["axes"] = [row for row in hand_built["axes"] if row["axis"] not in ("memory", "docs")]
        hand_built["preview_digest"] = native_capability_change_preview_digest(hand_built)
        errors = validate_native_capability_change_preview(hand_built)
        self.assertIn("native capability change preview is missing change axes: ['memory', 'docs']", errors)

    def test_unchanged_and_not_applicable_stay_distinguishable(self) -> None:
        unchanged = make_preview(axes=axes_with("memory", state="unchanged", note="identical wording"))
        not_applicable = make_preview(
            axes=axes_with("memory", state="not_applicable", note="identical wording")
        )
        self.assertEqual(validate_native_capability_change_preview(unchanged), [])
        self.assertEqual(validate_native_capability_change_preview(not_applicable), [])

        self.assertEqual(unchanged["axes"][2]["state"], "unchanged")
        self.assertEqual(not_applicable["axes"][2]["state"], "not_applicable")
        # Two answers, not one: the difference survives into the digest, so a
        # reviewer who accepted "considered and left alone" has not accepted
        # "has no bearing here".
        self.assertNotEqual(unchanged["preview_digest"], not_applicable["preview_digest"])

    def test_a_changed_axis_must_name_at_least_one_affected_surface(self) -> None:
        with self.assertRaises(NativeCapabilityChangePreviewError) as raised:
            make_preview(axes=axes_with("docs", state="changed", surfaces=[]))
        self.assertIn("marked changed and must name at least one affected surface", str(raised.exception))

    def test_an_axis_that_is_not_changed_must_not_name_a_surface(self) -> None:
        for state in ("unchanged", "not_applicable"):
            with self.subTest(state=state):
                with self.assertRaises(NativeCapabilityChangePreviewError) as raised:
                    make_preview(axes=axes_with("memory", state=state, surfaces=["memory.store"]))
                self.assertIn("must not name an affected surface", str(raised.exception))


class MaterialChangeTests(unittest.TestCase):
    """AC2: the digest covers the decisions, not the prose that explains them."""

    def test_the_material_line_is_the_note_field_and_nothing_else(self) -> None:
        # The partition is exhaustive, so a key added to the schema is material
        # by default and has to be argued out rather than silently left out.
        self.assertEqual(
            set(MATERIAL_PREVIEW_KEYS) | set(REVIEW_STATE_KEYS) | set(DERIVED_PREVIEW_KEYS),
            set(NATIVE_CAPABILITY_CHANGE_PREVIEW_KEYS),
        )
        self.assertEqual(set(MATERIAL_PREVIEW_KEYS) & set(REVIEW_STATE_KEYS), set())
        self.assertEqual(set(MATERIAL_PREVIEW_KEYS) & set(DERIVED_PREVIEW_KEYS), set())
        self.assertEqual(EXPLANATORY_FIELD, "note")

        material = material_preview_content(make_preview())
        self.assertEqual(sorted(material), sorted(MATERIAL_PREVIEW_KEYS))
        self.assertNotIn(EXPLANATORY_FIELD, _every_key(material))
        # Everything that is not a note survives the projection.
        self.assertEqual([row["axis"] for row in material["axes"]], list(CHANGE_AXES))
        self.assertEqual(material["rollback"], {"boundary": "no_persisted_state"})

    def test_the_digest_reuses_the_repository_hashing_scheme(self) -> None:
        # `policy_decision_digest` drops a key named `omh_observed_record` from
        # its seed; the closed key set is what keeps that irrelevant here.
        self.assertNotIn("omh_observed_record", MATERIAL_PREVIEW_KEYS)
        digest = make_preview()["preview_digest"]
        self.assertEqual(len(digest), 64)
        self.assertEqual(digest, digest.lower())
        int(digest, 16)
        self.assertEqual(make_preview()["preview_digest"], digest)

    def test_rewording_an_explanatory_note_keeps_the_review(self) -> None:
        accepted = accept_native_capability_change_preview(make_preview(), reviewer=REVIEWER)
        revisions = (
            ("axis note", {"axes": axes_with("docs", note="documents the preview contract instead")}),
            (
                "risk note",
                {"compatibility_risks": [{"id": "digest-churn", "severity": "low", "note": "reworded"}]},
            ),
            (
                "verification note",
                {
                    "verification_expectations": [
                        {"id": "preview-unit-tests", "kind": "unit_test", "note": "reworded"},
                        {"id": "repo-lint", "kind": "lint_gate", "note": "reworded too"},
                    ]
                },
            ),
            ("rollback note", {"rollback": {"boundary": "no_persisted_state", "note": "reworded again"}}),
            (
                "handoff note",
                {
                    "handoff_scope": {
                        "delegated": ["implement-preview-contract", "add-preview-tests"],
                        "retained": ["shape-the-preview-with-the-user"],
                        "note": "reworded once more",
                    }
                },
            ),
        )
        for label, change in revisions:
            with self.subTest(field=label):
                revised = revise_native_capability_change_preview(accepted, **change)
                self.assertEqual(revised["preview_digest"], accepted["preview_digest"])
                self.assertEqual(revised["status"], "accepted")
                self.assertEqual(preview_review_state(revised), "current")
                self.assertFalse(preview_requires_renewed_review(revised))
                self.assertEqual(validate_native_capability_change_preview(revised), [])

    def test_widening_an_axis_moves_the_digest_and_supersedes_the_review(self) -> None:
        accepted = accept_native_capability_change_preview(make_preview(), reviewer=REVIEWER)
        widened = revise_native_capability_change_preview(
            accepted, axes=axes_with("docs", surfaces=["docs.architecture", "docs.readme"])
        )
        self.assertNotEqual(widened["preview_digest"], accepted["preview_digest"])
        self.assertEqual(widened["status"], "superseded")
        self.assertEqual(preview_review_state(widened), "stale")
        self.assertTrue(preview_requires_renewed_review(widened))
        # The review that was given is kept as the record of what was accepted.
        self.assertEqual(widened["reviewed_by"], REVIEWER)
        self.assertEqual(widened["reviewed_digest"], accepted["preview_digest"])
        self.assertEqual(validate_native_capability_change_preview(widened), [])

    def test_flipping_an_axis_state_supersedes_the_review(self) -> None:
        accepted = accept_native_capability_change_preview(make_preview(), reviewer=REVIEWER)
        flipped = revise_native_capability_change_preview(
            accepted, axes=axes_with("memory", state="changed", surfaces=["memory.store"])
        )
        self.assertNotEqual(flipped["preview_digest"], accepted["preview_digest"])
        self.assertEqual(flipped["status"], "superseded")
        self.assertTrue(preview_requires_renewed_review(flipped))

    def test_every_other_material_edit_moves_the_digest(self) -> None:
        baseline = make_preview()["preview_digest"]
        edits = (
            ("capability_id", {"capability_id": "some-other-capability"}),
            ("target_experience", {"target_experience": "Hermes shows something else entirely."}),
            ("baseline", {"baseline": "OMH already answers this perfectly today."}),
            ("privacy_impact", {"privacy_impact": "local_content"}),
            ("risk severity", {"compatibility_risks": [{"id": "digest-churn", "severity": "high"}]}),
            (
                "verification kind",
                {
                    "verification_expectations": [
                        {"id": "preview-unit-tests", "kind": "manual_observation"},
                        {"id": "repo-lint", "kind": "lint_gate"},
                    ]
                },
            ),
            ("rollback boundary", {"rollback": {"boundary": "persisted_records_retained"}}),
            (
                "handoff scope",
                {
                    "handoff_scope": {
                        "delegated": ["implement-preview-contract"],
                        "retained": ["shape-the-preview-with-the-user"],
                    }
                },
            ),
            ("blueprint_ref", {"blueprint_ref": "native-capability-blueprint-794"}),
        )
        for label, change in edits:
            with self.subTest(field=label):
                self.assertNotEqual(make_preview(**change)["preview_digest"], baseline)

    def test_naming_the_same_surfaces_in_another_order_is_not_a_material_change(self) -> None:
        forward = make_preview(axes=axes_with("docs", surfaces=["docs.architecture", "docs.readme"]))
        backward = make_preview(axes=axes_with("docs", surfaces=["docs.readme", "docs.architecture"]))
        self.assertEqual(forward["preview_digest"], backward["preview_digest"])

    def test_accepting_a_preview_does_not_move_the_digest_it_names(self) -> None:
        preview = make_preview()
        self.assertEqual(preview_review_state(preview), "not_reviewed")
        self.assertTrue(preview_requires_renewed_review(preview))
        accepted = accept_native_capability_change_preview(preview, reviewer=REVIEWER)
        self.assertEqual(accepted["preview_digest"], preview["preview_digest"])
        self.assertEqual(accepted["reviewed_digest"], preview["preview_digest"])
        self.assertEqual(preview_review_state(accepted), "current")

    def test_an_accepted_preview_cannot_outlive_the_content_it_was_accepted_at(self) -> None:
        accepted = accept_native_capability_change_preview(make_preview(), reviewer=REVIEWER)
        tampered = dict(accepted)
        tampered["axes"] = axes_with("docs", surfaces=["docs.architecture", "docs.readme"])
        tampered["axes"] = build_native_capability_change_preview(**{**BASE, "axes": tampered["axes"]})["axes"]
        tampered["preview_digest"] = native_capability_change_preview_digest(tampered)
        errors = validate_native_capability_change_preview(tampered)
        self.assertTrue(
            any("the review has to be renewed" in error for error in errors),
            errors,
        )

    def test_a_hand_edited_digest_is_refused(self) -> None:
        preview = dict(make_preview())
        preview["preview_digest"] = "0" * 64
        self.assertIn(
            "native capability change preview preview_digest must be the digest of its own material content",
            validate_native_capability_change_preview(preview),
        )

    def test_a_renewed_review_makes_a_superseded_preview_current_again(self) -> None:
        accepted = accept_native_capability_change_preview(make_preview(), reviewer=REVIEWER)
        superseded = revise_native_capability_change_preview(
            accepted, axes=axes_with("docs", surfaces=["docs.architecture", "docs.readme"])
        )
        self.assertEqual(superseded["status"], "superseded")
        renewed = accept_native_capability_change_preview(superseded, reviewer=REVIEWER)
        self.assertEqual(renewed["status"], "accepted")
        self.assertEqual(preview_review_state(renewed), "current")
        self.assertFalse(preview_requires_renewed_review(renewed))
        self.assertEqual(renewed["reviewed_digest"], superseded["preview_digest"])

    def test_review_states_are_the_three_the_criterion_needs(self) -> None:
        self.assertEqual(REVIEW_STATES, ("not_reviewed", "current", "stale"))

    def test_a_revision_may_not_reach_the_review_fields_directly(self) -> None:
        accepted = accept_native_capability_change_preview(make_preview(), reviewer=REVIEWER)
        for field in REVIEW_STATE_KEYS:
            with self.subTest(field=field):
                with self.assertRaises(NativeCapabilityChangePreviewError) as raised:
                    revise_native_capability_change_preview(accepted, **{field: "accepted"})
                self.assertIn("may only change material content", str(raised.exception))

    def test_the_digest_reads_no_clock(self) -> None:
        source = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "workflows"
            / "native_capability_change_preview.py"
        ).read_text(encoding="utf-8")
        imported: set[str] = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertEqual(imported & {"datetime", "time", "random", "uuid"}, set())


class UnbuiltCapabilityTests(unittest.TestCase):
    """AC3: an accepted preview is a plan, in every word it is described with."""

    def test_no_status_in_the_vocabulary_claims_the_capability_exists(self) -> None:
        self.assertEqual(PREVIEW_STATUSES, ("draft", "in_review", "accepted", "superseded"))
        self.assertEqual(sorted(PREVIEW_STATUS_CLAIMS), sorted(PREVIEW_STATUSES))
        for status in PREVIEW_STATUSES:
            with self.subTest(status=status):
                self.assertNotIn(status, REFUSED_PREVIEW_STATUSES)
                claim = preview_status_claim(status)
                lowered = claim.lower()
                for word in REFUSED_PREVIEW_STATUSES:
                    self.assertNotIn(word, lowered, f"{status} claim says {word}")
                self.assertIn("nothing has been built", lowered)

    def test_an_implementation_word_is_refused_as_a_status(self) -> None:
        for word in REFUSED_PREVIEW_STATUSES:
            with self.subTest(word=word):
                with self.assertRaises(NativeCapabilityChangePreviewError) as raised:
                    make_preview(status=word)
                self.assertIn("may not claim the capability exists", str(raised.exception))

                hand_built = dict(make_preview())
                hand_built["status"] = word
                self.assertTrue(
                    any(
                        "may not claim the capability exists" in error
                        for error in validate_native_capability_change_preview(hand_built)
                    )
                )

    def test_the_claim_boundary_travels_with_an_accepted_preview(self) -> None:
        accepted = accept_native_capability_change_preview(make_preview(), reviewer=REVIEWER)
        self.assertEqual(accepted["claim_boundary"], NATIVE_CAPABILITY_CHANGE_PREVIEW_CLAIM_BOUNDARY)
        boundary = accepted["claim_boundary"].lower()
        self.assertIn("has not built", boundary)
        self.assertIn("never implementation", boundary)
        for axis in CHANGE_AXES:
            self.assertIn(axis, boundary)

    def test_rendering_an_unknown_status_is_refused(self) -> None:
        with self.assertRaises(NativeCapabilityChangePreviewError):
            preview_status_claim("implemented")

    def test_a_review_cannot_be_attached_to_an_unreviewed_status(self) -> None:
        preview = dict(make_preview())
        preview["reviewed_by"] = REVIEWER
        preview["reviewed_digest"] = preview["preview_digest"]
        self.assertIn(
            "native capability change preview status draft must not carry a review",
            validate_native_capability_change_preview(preview),
        )


class PreviewGuardTests(unittest.TestCase):
    """The refusals the artifact would be untrustworthy without."""

    def test_an_unknown_axis_is_refused(self) -> None:
        rows = [dict(row) for row in AXES]
        rows[6] = {"axis": "telemetry", "state": "changed", "surfaces": ["telemetry.sink"]}
        with self.assertRaises(NativeCapabilityChangePreviewError) as raised:
            make_preview(axes=rows)
        self.assertIn("unsupported change axis: 'telemetry'", str(raised.exception))

        hand_built = dict(make_preview())
        hand_built["axes"] = [
            *hand_built["axes"],
            {"axis": "telemetry", "state": "changed", "surfaces": ["telemetry.sink"], "note": ""},
        ]
        hand_built["preview_digest"] = native_capability_change_preview_digest(hand_built)
        self.assertTrue(
            any(
                "unsupported change axis: 'telemetry'" in error
                for error in validate_native_capability_change_preview(hand_built)
            )
        )

    def test_an_unknown_state_is_refused(self) -> None:
        with self.assertRaises(NativeCapabilityChangePreviewError) as raised:
            make_preview(axes=axes_with("docs", state="maybe", surfaces=["docs.architecture"]))
        self.assertIn("unsupported state: 'maybe'", str(raised.exception))

        hand_built = dict(make_preview())
        hand_built["axes"] = [
            {**row, "state": "partially"} if row["axis"] == "docs" else row for row in hand_built["axes"]
        ]
        hand_built["preview_digest"] = native_capability_change_preview_digest(hand_built)
        self.assertTrue(
            any(
                "unsupported state: 'partially'" in error
                for error in validate_native_capability_change_preview(hand_built)
            )
        )

    def test_an_axis_cannot_be_answered_twice(self) -> None:
        with self.assertRaises(NativeCapabilityChangePreviewError) as raised:
            make_preview(axes=[*AXES, dict(AXES[0])])
        self.assertIn("marks change axis routing more than once", str(raised.exception))

    def test_the_key_set_is_closed_in_both_directions(self) -> None:
        preview = make_preview()
        self.assertEqual(sorted(preview), sorted(NATIVE_CAPABILITY_CHANGE_PREVIEW_KEYS))
        self.assertEqual(preview["schema_version"], NATIVE_CAPABILITY_CHANGE_PREVIEW_SCHEMA_VERSION)

        extra = {**preview, "estimate": "two days"}
        self.assertIn(
            "native capability change preview has unsupported keys: ['estimate']",
            validate_native_capability_change_preview(extra),
        )

        for key in NATIVE_CAPABILITY_CHANGE_PREVIEW_KEYS:
            with self.subTest(key=key):
                short = {name: value for name, value in preview.items() if name != key}
                self.assertIn(
                    f"native capability change preview is missing keys: ['{key}']",
                    validate_native_capability_change_preview(short),
                )

    def test_a_raw_or_hidden_key_is_refused(self) -> None:
        preview = {**make_preview(), "transcript": "the whole chat"}
        self.assertTrue(
            any(
                "must not carry raw or hidden keys" in error
                for error in validate_native_capability_change_preview(preview)
            )
        )

    def test_free_text_stays_one_bounded_metadata_line(self) -> None:
        cases = (
            ("link", "See https:" + "//example.invalid for the plan"),
            ("path", "The change lands in src" + "/workflows"),
            ("too long", "x" * 401),
        )
        for label, text in cases:
            with self.subTest(case=label):
                with self.assertRaises(NativeCapabilityChangePreviewError):
                    make_preview(target_experience=text)

    def test_the_vocabularies_stay_closed(self) -> None:
        self.assertNotIn("unbounded", PRIVACY_IMPACTS)
        with self.assertRaises(NativeCapabilityChangePreviewError):
            make_preview(privacy_impact="whatever")
        with self.assertRaises(NativeCapabilityChangePreviewError):
            make_preview(rollback={"boundary": "probably_fine"})
        self.assertIn("irreversible", ROLLBACK_BOUNDARIES)

    def test_a_preview_names_verification_and_delegated_work(self) -> None:
        with self.assertRaises(NativeCapabilityChangePreviewError) as raised:
            make_preview(verification_expectations=[])
        self.assertIn("at least one verification expectation", str(raised.exception))

        with self.assertRaises(NativeCapabilityChangePreviewError) as raised:
            make_preview(handoff_scope={"delegated": [], "retained": ["shape-the-preview"]})
        self.assertIn("at least one delegated unit of work", str(raised.exception))

    def test_the_blueprint_reference_is_an_optional_named_seam(self) -> None:
        # `native_capability_blueprint/v1` (#791) is built separately. Nothing
        # here imports or requires one; the field exists so the two artifacts
        # can be joined later without reshaping this schema.
        self.assertEqual(make_preview()["blueprint_ref"], "")
        joined = make_preview(blueprint_ref="native-capability-blueprint-794")
        self.assertEqual(joined["blueprint_ref"], "native-capability-blueprint-794")
        self.assertEqual(validate_native_capability_change_preview(joined), [])


def _every_key(value: object) -> set[str]:
    if isinstance(value, dict):
        keys = set(value)
        for item in value.values():
            keys |= _every_key(item)
        return keys
    if isinstance(value, list):
        keys: set[str] = set()
        for item in value:
            keys |= _every_key(item)
        return keys
    return set()


if __name__ == "__main__":
    unittest.main()
