"""Contract tests for immutable, content-addressed role-context packs (#831).

The three acceptance criteria this file locks:

1. Every accepted coding handoff names exactly one immutable pack hash.
2. Changing guidance mints a new pack instead of mutating an accepted one.
3. Codex, Claude Code, Hermes, and generic executor profiles consume the same
   neutral pack contract.

Immutability is asserted structurally, not just behaviourally: `NoMutatingWriterTests`
re-derives the module's write sites from its own source, so a future writer that
edits a stored pack fails this file rather than silently existing.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from _cli_harness import run_cli
from _local_package import load_local_package

load_local_package()
from omh.coding_delegation import build_coding_delegation_payload
from omh.local_store import atomic_write_text
from omh.memory import (
    SOURCE_TRUTH_LEVELS,
    approve_project_memory_candidate,
    build_handoff_context_pack,
    capture_project_memory_candidate,
    freshness_reason_detail,
    memory_recall_pack_for_handoff,
)
from omh.paths import resolve_paths
from omh.runtime.records import validate_handoff_context_pack_fields
from omh.workflows.role_context_packs import (
    ROLE_CONTEXT_PACK_ORIGINS,
    ROLE_CONTEXT_PACK_SCHEMA_VERSION,
    TRUTH_LEVEL_REASON_TEXT,
    build_role_context_pack,
    diff_role_context_packs,
    pin_role_context_pack,
    read_role_context_pack,
    role_context_pack_hash,
    role_context_pack_is_empty,
    role_context_pack_path,
    validate_accepted_role_context,
    validate_role_context_pack,
    validate_role_context_pack_pin,
    write_role_context_pack,
)


_MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "workflows" / "role_context_packs.py"


def _approve(paths, summary, **kwargs):
    captured = capture_project_memory_candidate(paths, summary, **kwargs)
    return approve_project_memory_candidate(paths, captured["candidate"]["candidate_id"])["record"]


def _recall_pack(paths, query="verification", executor_target="codex"):
    pack = memory_recall_pack_for_handoff(paths, query, executor_target=executor_target)
    assert pack is not None, "fixture expected an eligible recall pack"
    return pack


def _handoff_of(payload):
    for key in ("executor_handoff", "runtime_handoff", "prompt_handoff"):
        handoff = payload.get(key)
        if isinstance(handoff, dict):
            return key, handoff
    raise AssertionError(f"payload prepared no coding handoff: {sorted(payload)}")


class AcceptedHandoffNamesOnePackHashTests(unittest.TestCase):
    """AC1: every accepted handoff names exactly one immutable pack hash."""

    def test_prepared_handoff_names_one_hash_that_matches_its_pack(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            _approve(paths, "Run the full unittest suite before claiming verification")
            payload = build_coding_delegation_payload(
                "risky refactor",
                source="discord",
                executor_target="codex",
                memory_recall_pack=_recall_pack(paths),
            )
            _, handoff = _handoff_of(payload)

            self.assertIn("role_context_pack_hash", handoff)
            self.assertIn("role_context_pack", handoff)
            self.assertIsInstance(handoff["role_context_pack_hash"], str)
            self.assertEqual(handoff["role_context_pack_hash"], handoff["role_context_pack"]["pack_hash"])
            self.assertEqual(handoff["role_context_pack"]["schema_version"], ROLE_CONTEXT_PACK_SCHEMA_VERSION)
            self.assertEqual(validate_accepted_role_context(handoff, "handoff"), [])
            # "Exactly one": the pin is a single scalar, not a list of
            # candidate hashes a reader would have to choose between.
            self.assertEqual(
                [key for key in handoff if key.startswith("role_context_pack")],
                ["role_context_pack_hash", "role_context_pack"],
            )

    def test_handoff_with_no_pack_fails_acceptance_but_still_validates_as_prepared(self) -> None:
        handoff: dict[str, object] = {"schema_version": "coding_executor_handoff/v1"}

        self.assertEqual(
            validate_role_context_pack_pin(handoff, "handoff"),
            [],
            "a handoff prepared before packs existed is not retroactively broken",
        )
        errors = validate_accepted_role_context(handoff, "handoff")
        self.assertEqual(len(errors), 1)
        self.assertIn("must name exactly one role_context_pack_hash before acceptance", errors[0])

    def test_every_prepared_coding_handoff_carries_a_pack_even_with_no_guidance(self) -> None:
        payload = build_coding_delegation_payload(
            "risky refactor",
            source="discord",
            executor_target="claude-code",
        )
        _, handoff = _handoff_of(payload)

        self.assertEqual(validate_accepted_role_context(handoff, "handoff"), [])
        self.assertTrue(role_context_pack_is_empty(handoff["role_context_pack"]))

    def test_recorded_handoff_keeps_the_pin_and_the_run_manifest_names_the_hash(self) -> None:
        from omh.runtime.artifacts import _handoff_contract_summary
        from omh.runtime.records import _compact_executor_handoff, _compact_prompt_handoff, _compact_runtime_handoff

        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            _approve(paths, "Verification means the full unittest suite, not a subset")
            payload = build_coding_delegation_payload(
                "risky refactor",
                source="discord",
                executor_target="codex",
                memory_recall_pack=_recall_pack(paths),
            )
            key, handoff = _handoff_of(payload)
            compactor = {
                "executor_handoff": _compact_executor_handoff,
                "runtime_handoff": _compact_runtime_handoff,
                "prompt_handoff": _compact_prompt_handoff,
            }[key]
            compacted = compactor(handoff)

            self.assertEqual(compacted["role_context_pack_hash"], handoff["role_context_pack_hash"])
            self.assertEqual(
                validate_handoff_context_pack_fields(compacted, "recorded handoff"),
                [],
                "the recorded copy must still recompute to the hash it names",
            )
            summary = _handoff_contract_summary(handoff)
            self.assertEqual(summary["role_context_pack_hash"], handoff["role_context_pack_hash"])
            self.assertEqual(summary["role_context_pack"]["pack_hash"], handoff["role_context_pack_hash"])


class AcceptedPlanHandoffCliTests(unittest.TestCase):
    """AC1 end to end: the repo's real acceptance path pins and stores a pack."""

    def test_delegating_from_an_accepted_plan_pins_and_stores_the_pack(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            hermes_home = root / ".hermes"
            common = ["--omh-home", str(omh_home), "--hermes-home", str(hermes_home)]

            status, stdout, stderr = run_cli([*common, "hermes", "plan", "risky", "refactor", "with", "review", "--record"])
            self.assertEqual((status, stderr), (0, ""))
            plan_path = json.loads(stdout)["artifact"]["path"]

            status, _, stderr = run_cli([*common, "hermes", "plan-accept", plan_path, "--write-context-pack", "--executor", "codex"])
            self.assertEqual((status, stderr), (0, ""))

            status, stdout, stderr = run_cli([*common, "coding", "delegate", "--executor", "codex", "--from-plan", plan_path])
            self.assertEqual((status, stderr), (0, ""))
            _, handoff = _handoff_of(json.loads(stdout))
            pack_hash = handoff["role_context_pack_hash"]

            self.assertEqual(validate_accepted_role_context(handoff, "accepted handoff"), [])
            self.assertEqual(
                [record["record_id"] for record in handoff["role_context_pack"]["records"]],
                ["accepted-hermes-plan"],
                "the accepted plan is the reviewed guidance this handoff carries",
            )
            paths = resolve_paths(omh_home, hermes_home)
            self.assertEqual(
                sorted(path.name for path in paths.role_context_packs_dir.glob("*.json")),
                [f"{pack_hash}.json"],
                "the store is addressed by the hash the handoff pinned",
            )
            self.assertEqual(read_role_context_pack(paths, pack_hash), handoff["role_context_pack"])


class NewPackNeverMutatesAnAcceptedOneTests(unittest.TestCase):
    """AC2: changing guidance mints a new pack; nothing edits an accepted one."""

    def test_changing_a_record_summary_yields_a_different_hash(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            _approve(paths, "Verification runs the full suite")
            _approve(paths, "Verification also runs the byte gates")
            recall = _recall_pack(paths)
            self.assertGreaterEqual(len(recall["included_records"]), 2)

            original = build_role_context_pack(memory_recall_pack=recall)
            edited = json.loads(json.dumps(recall))
            edited["included_records"][0]["summary"] += " and the lint gate"
            changed = build_role_context_pack(memory_recall_pack=edited)

            self.assertNotEqual(original["pack_hash"], changed["pack_hash"])
            self.assertNotEqual(
                original["records"][0]["record_hash"],
                changed["records"][0]["record_hash"],
                "the per-record hash covers the guidance text, not only its id",
            )

    def test_reordering_the_same_records_yields_a_different_hash(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            _approve(paths, "Verification runs the full suite")
            _approve(paths, "Verification also runs the byte gates")
            recall = _recall_pack(paths)

            forward = build_role_context_pack(memory_recall_pack=recall)
            reversed_pack = json.loads(json.dumps(recall))
            reversed_pack["included_records"].reverse()
            backward = build_role_context_pack(memory_recall_pack=reversed_pack)

            self.assertEqual(
                {record["record_hash"] for record in forward["records"]},
                {record["record_hash"] for record in backward["records"]},
                "the same records, so only their order can differ",
            )
            self.assertNotEqual(
                forward["pack_hash"],
                backward["pack_hash"],
                "record order is guidance precedence, so it is part of pack identity",
            )

    def test_dropping_a_record_mints_a_new_pack_and_leaves_the_stored_one_untouched(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            _approve(paths, "Verification runs the full suite")
            _approve(paths, "Verification also runs the byte gates")
            recall = _recall_pack(paths)

            accepted = build_role_context_pack(memory_recall_pack=recall)
            accepted_path = write_role_context_pack(paths, accepted)
            accepted_bytes = accepted_path.read_bytes()

            dropped_id = accepted["records"][0]["record_id"]
            adjusted = build_role_context_pack(memory_recall_pack=recall, excluded_record_ids=(dropped_id,))
            adjusted_path = write_role_context_pack(paths, adjusted)

            self.assertNotEqual(accepted["pack_hash"], adjusted["pack_hash"])
            self.assertNotEqual(accepted_path, adjusted_path)
            self.assertEqual(accepted_path.read_bytes(), accepted_bytes, "the accepted pack is byte-identical after the edit")
            self.assertEqual(len(sorted(paths.role_context_packs_dir.glob("*.json"))), 2)
            self.assertEqual(read_role_context_pack(paths, accepted["pack_hash"]), accepted)

    def test_a_handoff_pinned_to_the_old_hash_still_names_the_old_hash(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            _approve(paths, "Verification runs the full suite")
            _approve(paths, "Verification also runs the byte gates")
            recall = _recall_pack(paths)

            accepted = build_role_context_pack(memory_recall_pack=recall)
            handoff: dict[str, object] = {"schema_version": "coding_executor_handoff/v1"}
            pin_role_context_pack(handoff, accepted)
            write_role_context_pack(paths, accepted)

            adjusted = build_role_context_pack(
                memory_recall_pack=recall,
                excluded_record_ids=(accepted["records"][0]["record_id"],),
            )
            write_role_context_pack(paths, adjusted)

            self.assertEqual(handoff["role_context_pack_hash"], accepted["pack_hash"])
            self.assertEqual(handoff["role_context_pack"], accepted)
            self.assertEqual(read_role_context_pack(paths, str(handoff["role_context_pack_hash"])), accepted)
            self.assertEqual(validate_accepted_role_context(handoff, "handoff"), [])

    def test_rewriting_the_same_pack_is_a_no_op_rather_than_an_edit(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            pack = build_role_context_pack()
            first = write_role_context_pack(paths, pack)
            stat_before = first.stat().st_mtime_ns
            second = write_role_context_pack(paths, pack)

            self.assertEqual(first, second)
            self.assertEqual(first.stat().st_mtime_ns, stat_before)

    def test_a_pack_edited_out_of_band_no_longer_answers_to_its_name(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            _approve(paths, "Verification runs the full suite")
            pack = build_role_context_pack(memory_recall_pack=_recall_pack(paths))
            path = write_role_context_pack(paths, pack)

            tampered = json.loads(path.read_text(encoding="utf-8"))
            tampered["records"][0]["reason"] = "Included because someone said so."
            # `atomic_write_text` keeps the bytes platform-stable; a plain
            # `Path.write_text` would inject CRLF on Windows and this test
            # hashes what it writes.
            atomic_write_text(path, json.dumps(tampered, indent=2, sort_keys=True) + "\n")

            with self.assertRaisesRegex(ValueError, "does not match the pack content"):
                read_role_context_pack(paths, str(pack["pack_hash"]))


class NoMutatingWriterTests(unittest.TestCase):
    """AC2, structurally: the module cannot express an in-place pack edit."""

    def test_the_only_write_site_derives_its_destination_from_the_content_hash(self) -> None:
        tree = ast.parse(_MODULE_PATH.read_text(encoding="utf-8"))
        write_calls = {"atomic_write_json", "atomic_write_text", "write_text", "write_bytes", "open", "unlink", "replace", "rename"}
        writers: dict[str, list[str]] = {}
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for inner in ast.walk(node):
                if not isinstance(inner, ast.Call):
                    continue
                name = inner.func.attr if isinstance(inner.func, ast.Attribute) else getattr(inner.func, "id", "")
                if name in write_calls:
                    writers.setdefault(node.name, []).append(name)

        self.assertEqual(
            sorted(writers),
            ["write_role_context_pack"],
            "a second writer means a pack can be edited in place; store the next pack instead",
        )
        self.assertEqual(sorted(set(writers["write_role_context_pack"])), ["atomic_write_json"])

        writer = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "write_role_context_pack"
        )
        destinations = {
            inner.func.id
            for inner in ast.walk(writer)
            if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name)
        }
        self.assertIn(
            "role_context_pack_path",
            destinations,
            "the destination must come from the content hash, never from a caller-chosen name",
        )

    def test_no_public_entry_point_offers_an_update_or_delete_verb(self) -> None:
        tree = ast.parse(_MODULE_PATH.read_text(encoding="utf-8"))
        public = [
            node.name
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and not node.name.startswith("_")
        ]
        forbidden = [name for name in public if name.split("_")[0] in {"update", "edit", "patch", "append", "delete", "remove", "set"}]

        self.assertEqual(forbidden, [], "an accepted pack has no mutating verb by design")

    def test_a_credential_shaped_record_id_is_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "bounded, non-credential metadata reference"):
            build_role_context_pack(
                context_pack={
                    "included_context": [
                        {
                            "item_id": "AKIAIOSFODNN7EXAMPLE",
                            "key": "k",
                            "summary": "s",
                            "source": "wrapper_snapshot",
                            "truth_level": "supplied_hint",
                        }
                    ]
                }
            )

    def test_an_unusual_but_harmless_wrapper_item_id_is_accepted(self) -> None:
        pack = build_role_context_pack(
            context_pack={
                "included_context": [
                    {
                        "item_id": "wrapper item #7 (thread)",
                        "key": "default executor",
                        "summary": "Wrapper supplied a hint",
                        "source": "wrapper_snapshot",
                        "truth_level": "supplied_hint",
                    }
                ]
            }
        )

        self.assertEqual(validate_role_context_pack(pack), [])
        self.assertEqual(pack["records"][0]["record_id"], "wrapper item #7 (thread)")

    def test_the_store_path_refuses_anything_that_is_not_a_content_hash(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            for unsafe in ("../escape", "not-a-hash", "A" * 64, ""):
                with self.subTest(unsafe=unsafe), self.assertRaisesRegex(ValueError, "unsafe role context pack hash"):
                    role_context_pack_path(paths, unsafe)


class NeutralContractAcrossExecutorProfilesTests(unittest.TestCase):
    """AC3: one contract for Codex, Claude Code, Hermes, and generic profiles."""

    profiles = ("codex", "claude-code", "hermes", "generic")

    def test_all_four_profiles_get_an_identical_contract_from_identical_guidance(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            _approve(paths, "Every executor runs the full unittest suite for verification")

            packs = {
                profile: build_role_context_pack(memory_recall_pack=_recall_pack(paths, executor_target=profile))
                for profile in self.profiles
            }

            shapes = {profile: sorted(pack) for profile, pack in packs.items()}
            self.assertEqual(len(set(map(tuple, shapes.values()))), 1, shapes)
            record_shapes = {
                profile: sorted(pack["records"][0]) if pack["records"] else []
                for profile, pack in packs.items()
            }
            self.assertEqual(len(set(map(tuple, record_shapes.values()))), 1, record_shapes)
            self.assertEqual(
                len({pack["pack_hash"] for pack in packs.values()}),
                1,
                "the pack carries no owner field, so identical guidance is one pack for every profile",
            )
            for profile, pack in packs.items():
                with self.subTest(profile=profile):
                    self.assertEqual(validate_role_context_pack(pack), [])

    def test_owner_specific_fields_live_on_the_handoff_not_in_the_pack(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            _approve(paths, "Every executor runs the full unittest suite for verification")
            handoffs = {}
            for profile in self.profiles:
                payload = build_coding_delegation_payload(
                    "risky refactor",
                    source="discord",
                    executor_target=profile,
                    memory_recall_pack=_recall_pack(paths, executor_target=profile),
                )
                handoffs[profile] = _handoff_of(payload)[1]

            owners = {profile: handoff.get("selected_executor_profile") for profile, handoff in handoffs.items()}
            self.assertEqual(len(set(owners.values())), len(self.profiles), owners)
            self.assertEqual(
                len({handoff["role_context_pack_hash"] for handoff in handoffs.values()}),
                1,
                "the owner names itself on the handoff; the guidance contract stays neutral",
            )

    def test_the_perspective_lens_still_scopes_which_records_reach_a_profile(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            _approve(paths, "Shared verification rule for every executor")
            _approve(paths, "codex needs an explicit verification command", observed="codex")

            codex = build_role_context_pack(memory_recall_pack=_recall_pack(paths, executor_target="codex"))
            generic = build_role_context_pack(memory_recall_pack=_recall_pack(paths, executor_target="generic"))

            self.assertGreater(len(codex["records"]), len(generic["records"]))
            self.assertNotEqual(
                codex["pack_hash"],
                generic["pack_hash"],
                "different guidance is a different pack; that is selection, not a forked contract",
            )
            self.assertEqual(sorted(codex), sorted(generic), "selection changed, the contract did not")


class PackGuardTests(unittest.TestCase):
    def test_a_mismatched_pin_is_a_validation_error(self) -> None:
        pack = build_role_context_pack()
        handoff: dict[str, object] = {"schema_version": "coding_executor_handoff/v1"}
        pin_role_context_pack(handoff, pack)
        handoff["role_context_pack_hash"] = "0" * 64

        errors = validate_role_context_pack_pin(handoff, "handoff")
        self.assertTrue(any("does not match the attached pack" in error for error in errors), errors)
        self.assertTrue(
            any("does not match the attached pack" in error for error in validate_handoff_context_pack_fields(handoff, "handoff")),
            "the runtime record contract rejects it too, rather than warning",
        )

    def test_a_pack_edited_in_place_stops_matching_its_own_hash(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            _approve(paths, "Verification runs the full suite")
            pack = build_role_context_pack(memory_recall_pack=_recall_pack(paths))
            pack["records"][0]["reason"] = "rewritten"

            self.assertIn("pack_hash does not match the pack content", " ".join(validate_role_context_pack(pack)))

    def test_half_a_pin_is_refused_from_either_side(self) -> None:
        pack = build_role_context_pack()
        hash_only: dict[str, object] = {"role_context_pack_hash": pack["pack_hash"]}
        pack_only: dict[str, object] = {"role_context_pack": pack}

        self.assertTrue(any("without a resolvable role_context_pack" in error for error in validate_role_context_pack_pin(hash_only, "h")))
        self.assertTrue(any("without naming role_context_pack_hash" in error for error in validate_role_context_pack_pin(pack_only, "h")))

    def test_an_empty_pack_is_distinguishable_from_an_absent_one(self) -> None:
        empty = build_role_context_pack()
        handoff_with_empty: dict[str, object] = {}
        pin_role_context_pack(handoff_with_empty, empty)
        handoff_without: dict[str, object] = {}

        self.assertTrue(role_context_pack_is_empty(empty))
        self.assertEqual(empty["records"], [])
        self.assertEqual(empty["record_count"], 0)
        self.assertEqual(validate_role_context_pack(empty), [], "an empty pack is a real, valid pack")
        self.assertEqual(validate_accepted_role_context(handoff_with_empty, "h"), [])
        self.assertNotEqual(validate_accepted_role_context(handoff_without, "h"), [])
        self.assertNotIn("role_context_pack_hash", handoff_without)

    def test_an_empty_pack_hash_differs_from_every_non_empty_one(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            _approve(paths, "Verification runs the full suite")
            empty = build_role_context_pack()
            filled = build_role_context_pack(memory_recall_pack=_recall_pack(paths))

            self.assertNotEqual(empty["pack_hash"], filled["pack_hash"])

    def test_the_hash_is_deterministic_and_carries_no_wall_clock(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            _approve(paths, "Verification runs the full suite")
            recall = _recall_pack(paths)

            self.assertEqual(
                build_role_context_pack(memory_recall_pack=recall)["pack_hash"],
                build_role_context_pack(memory_recall_pack=recall)["pack_hash"],
            )
            # A timestamp anywhere in the seed would make two builds a second
            # apart disagree; asserting the frozen digest of a fixed pack is
            # what catches a clock (or an encoding change) sneaking in.
            self.assertEqual(
                role_context_pack_hash(
                    {
                        "schema_version": ROLE_CONTEXT_PACK_SCHEMA_VERSION,
                        "pack_hash": "ignored",
                        "scope": {"kind": "project", "ref": "default"},
                        "records": [],
                        "record_count": 0,
                        "redaction_policy": "metadata_only",
                        "claim_boundary": "frozen fixture",
                    }
                ),
                "8dc6f566517e56e41515633291e02b739a66be6c163c44be3dff316cd29790db",
            )

    def test_the_digest_cannot_be_forged_by_moving_text_across_field_boundaries(self) -> None:
        left = {"a": "x", "b": "yz"}
        right = {"a": "xy", "b": "z"}

        self.assertNotEqual(role_context_pack_hash(left), role_context_pack_hash(right))
        self.assertNotEqual(role_context_pack_hash({"a": "1"}), role_context_pack_hash({"a": 1}))


class ExplainedRecordTests(unittest.TestCase):
    def test_every_included_record_carries_a_human_readable_reason(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            _approve(paths, "Verification runs the full unittest suite")
            pack = build_role_context_pack(memory_recall_pack=_recall_pack(paths))

            self.assertTrue(pack["records"])
            for record in pack["records"]:
                with self.subTest(record_id=record["record_id"]):
                    self.assertTrue(record["reason"].strip())
                    self.assertTrue(record["reason"].endswith("."))
                    self.assertIn(record["origin"], ROLE_CONTEXT_PACK_ORIGINS)

    def test_the_reason_vocabulary_is_the_existing_one_not_a_parallel_table(self) -> None:
        self.assertEqual(
            set(TRUTH_LEVEL_REASON_TEXT),
            set(SOURCE_TRUTH_LEVELS.values()),
            "the context-pack truth levels are the vocabulary; rendering may not add or drop a code",
        )
        for code in ("stale_review_required", "source_changed", "superseded"):
            with self.subTest(code=code):
                self.assertTrue(freshness_reason_detail(code), "freshness text stays owned by the recall pack")
        self.assertEqual(freshness_reason_detail("eligible"), "", "eligible is not a freshness reason")

    def test_context_pack_items_are_explained_by_their_own_truth_level(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            _approve(paths, "Verification runs the full unittest suite")
            context_pack = build_handoff_context_pack(paths, executor_target="codex")
            pack = build_role_context_pack(context_pack=context_pack)

            self.assertTrue(pack["records"])
            for record in pack["records"]:
                with self.subTest(record_id=record["record_id"]):
                    self.assertEqual(record["origin"], "handoff_context_pack/v1")
                    self.assertTrue(record["reason"].strip())


class PreAcceptanceDiffTests(unittest.TestCase):
    def test_the_diff_names_additions_removals_and_reorders(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            _approve(paths, "Verification runs the full suite")
            _approve(paths, "Verification also runs the byte gates")
            recall = _recall_pack(paths)
            current = build_role_context_pack(memory_recall_pack=recall)
            dropped_id = current["records"][0]["record_id"]
            adjusted = build_role_context_pack(memory_recall_pack=recall, excluded_record_ids=(dropped_id,))

            diff = diff_role_context_packs(current, adjusted)

            self.assertTrue(diff["changed"])
            self.assertEqual([entry["record_id"] for entry in diff["removed"]], [dropped_id])
            self.assertEqual(diff["added"], [])
            self.assertEqual(diff["previous_pack_hash"], current["pack_hash"])
            self.assertEqual(diff["current_pack_hash"], adjusted["pack_hash"])
            self.assertTrue(all(entry["reason"] for entry in diff["removed"]))

            reversed_recall = json.loads(json.dumps(recall))
            reversed_recall["included_records"].reverse()
            reordered = build_role_context_pack(memory_recall_pack=reversed_recall)
            reorder_diff = diff_role_context_packs(current, reordered)
            self.assertEqual(reorder_diff["added"], [])
            self.assertEqual(reorder_diff["removed"], [])
            self.assertTrue(reorder_diff["reordered"])
            self.assertTrue(reorder_diff["changed"], "a reorder is a different pack, so the diff says changed")

    def test_an_unchanged_pack_diffs_to_nothing(self) -> None:
        pack = build_role_context_pack()
        diff = diff_role_context_packs(pack, pack)

        self.assertFalse(diff["changed"])
        self.assertEqual((diff["added"], diff["removed"], diff["reordered"], diff["stale"]), ([], [], [], []))


if __name__ == "__main__":
    unittest.main()
