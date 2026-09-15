"""Contract tests for exporting and applying one machine's OMH setup profile.

Every test here builds its OMH and Hermes homes under a temporary directory.
None of them may read the developer's real `~/.omh` or `~/.hermes`, and the MCP
apply case names an explicit config path so it cannot reach a real host config
file either -- a profile apply that silently edited the developer's Codex or
Claude Code configuration during a test run would be the worst possible way to
learn that the writer is wired up.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from _cli_harness import run_cli
from _credential_fixtures import AWS_ACCESS_KEY_ID
from _local_package import load_local_package

load_local_package()
from omh.capabilities.toggles import (
    read_capability_policy,
    write_capability_policy,
    write_org_rule_source_policy,
)
from omh.paths import resolve_paths
from omh.profiles.pack import (
    SETUP_PROFILE_PACK_SCHEMA_VERSION,
    SetupProfilePackError,
    apply_setup_profile_pack,
    build_setup_profile_pack,
    configured_field_summary,
    pack_version_refusal,
    read_setup_profile_pack,
    write_setup_profile_pack,
)
from omh.profiles.setup import read_setup_profile, write_setup_profile
from omh.runtime.artifacts import update_state


# A platform-token shape, written out: `_PLATFORM_SECRET_PREFIX` in
# `src/system/metadata_safety.py` matches it, and it is short of the 36-char
# body a real GitHub PAT carries, so no scanner pattern matches it on disk.
_SOURCE_SECRET = "ghp_0123456789abcdef0123456789"
# An AWS access key id shape, imported rather than written: the literal cannot
# exist in a tracked file or secret scanning alerts on a value nobody issued.
# `tests/test_credential_fixture_policy.py` enforces that, and this constant is
# the same twenty characters at runtime that the literal was.
_SOURCE_ACCESS_KEY = AWS_ACCESS_KEY_ID


class _PackFixture(unittest.TestCase):
    def _paths(self, root: Path):
        return resolve_paths(root / ".omh", root / ".hermes")

    def _configured_source(self, root: Path, **overrides):
        """A machine whose profile someone actually configured."""
        paths = self._paths(root)
        write_setup_profile(
            paths,
            ["3"],
            default_executor=overrides.get("default_executor", "codex"),
            operating_model=overrides.get("operating_model", "small-team"),
            memory_mode=overrides.get("memory_mode", "auto-safe"),
        )
        write_capability_policy(paths, ["retain_knowledge"])
        return paths

    def _with_hermes_aliases(self, paths, aliases: dict[str, str]) -> None:
        body = "model:\n  aliases:\n" + "".join(
            f"    {alias}: {target}\n" for alias, target in sorted(aliases.items())
        )
        paths.hermes_config_path.parent.mkdir(parents=True, exist_ok=True)
        paths.hermes_config_path.write_text(body, encoding="utf-8")

    def _with_mcp_record(self, paths, *, host: str = "codex") -> None:
        update_state(
            paths,
            {
                "last_mcp_host_config_install": {
                    "host": host,
                    "command": "omh",
                    "server_args": ["mcp", "serve"],
                    "scope": "user",
                    "path": str(paths.omh_home / "codex-config.toml"),
                    "status": "updated",
                }
            },
        )

    def _inject_profile_keys(self, paths, values: dict[str, object]) -> None:
        profile = json.loads(paths.setup_profile_path.read_text(encoding="utf-8"))
        profile.update(values)
        paths.setup_profile_path.write_text(
            json.dumps(profile, indent=2, sort_keys=True), encoding="utf-8"
        )


class SetupProfilePackExportTests(_PackFixture):
    def test_an_unconfigured_machine_has_nothing_to_export(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SetupProfilePackError) as caught:
                build_setup_profile_pack(self._paths(Path(tmp)))
        self.assertIn("omh setup", str(caught.exception))

    def test_a_corrupt_profile_names_the_file_instead_of_raising_a_decoder_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._configured_source(Path(tmp))
            paths.setup_profile_path.write_text("{not json", encoding="utf-8")

            with self.assertRaises(SetupProfilePackError) as caught:
                build_setup_profile_pack(paths)

            self.assertIn(str(paths.setup_profile_path), str(caught.exception))

    def test_the_pack_carries_every_configured_ingredient(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._configured_source(Path(tmp))
            self._with_hermes_aliases(paths, {"main": "anthropic/claude-opus-5"})
            self._with_mcp_record(paths)

            pack = build_setup_profile_pack(paths)

        self.assertEqual(pack["schema_version"], SETUP_PROFILE_PACK_SCHEMA_VERSION)
        self.assertEqual(pack["profile"]["default_executor"], "codex")
        self.assertEqual(pack["profile"]["operating_model_id"], "small-team")
        self.assertEqual(pack["profile"]["memory_mode"], "auto-safe")
        self.assertEqual(pack["capability_policy"]["disabled_families"], ["retain_knowledge"])
        self.assertEqual(pack["mcp"]["status"], "recorded")
        self.assertEqual(pack["mcp"]["host"], "codex")
        self.assertEqual(pack["model_aliases"]["aliases"], {"main": "anthropic/claude-opus-5"})

    def test_the_manifest_is_content_addressed_and_names_its_builder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._configured_source(Path(tmp))
            first = build_setup_profile_pack(paths)
            second = build_setup_profile_pack(paths)

        self.assertEqual(first["manifest"]["pack_id"], second["manifest"]["pack_id"])
        self.assertEqual(sorted(first["manifest"]["sections"]), sorted(first["manifest"]["section_digests"]))
        self.assertTrue(first["manifest"]["source_omh_version"])
        self.assertIn("not execution", first["manifest"]["claim_boundary"])

    def test_a_secret_is_absent_from_the_artifact_and_named_as_withheld(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._configured_source(Path(tmp))
            self._inject_profile_keys(
                paths,
                {"github_token": _SOURCE_SECRET, "operator_note": _SOURCE_ACCESS_KEY},
            )

            pack = build_setup_profile_pack(paths)

        serialized = json.dumps(pack, sort_keys=True)
        self.assertNotIn(_SOURCE_SECRET, serialized)
        self.assertNotIn(_SOURCE_ACCESS_KEY, serialized)
        withheld = {entry["field"]: entry["reason"] for entry in pack["withheld"]}
        # The point of the criterion: absent AND announced. A quiet drop would
        # pass the two assertions above and still be the failure mode.
        self.assertIn("profile.github_token", withheld)
        self.assertIn("profile.operator_note", withheld)
        self.assertIn("credential", withheld["profile.github_token"])
        self.assertIn("credential-shaped", withheld["profile.operator_note"])
        self.assertEqual(pack["manifest"]["withheld_field_count"], len(pack["withheld"]))

    def test_machine_local_paths_are_withheld_with_their_own_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self._configured_source(root)
            write_org_rule_source_policy(
                paths,
                enabled=True,
                source_path=str(root / "org-rules.md"),
                attestation_key_path=str(root / "org-rule.key"),
            )

            pack = build_setup_profile_pack(paths)

        withheld = {entry["field"]: entry["reason"] for entry in pack["withheld"]}
        self.assertIn("profile.org_rule_source_policy.source_path", withheld)
        self.assertIn("profile.org_rule_source_policy.attestation_key_path", withheld)
        for field in (
            "profile.org_rule_source_policy.source_path",
            "profile.org_rule_source_policy.attestation_key_path",
        ):
            self.assertIn("machine-local", withheld[field])

    def test_product_prose_survives_redaction(self) -> None:
        """The screens must not eat the profile's own claim boundary."""
        with tempfile.TemporaryDirectory() as tmp:
            pack = build_setup_profile_pack(self._configured_source(Path(tmp)))

        self.assertIn("claim_boundary", pack["profile"])
        self.assertTrue(pack["profile"]["choices"])
        self.assertEqual(pack["profile"]["local_only"], True)
        self.assertEqual(pack["profile"]["network_calls"], False)

    def test_an_absent_hermes_config_reports_why_rather_than_failing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pack = build_setup_profile_pack(self._configured_source(Path(tmp)))

        self.assertEqual(pack["model_aliases"]["status"], "no_hermes_config")
        self.assertEqual(pack["model_aliases"]["aliases"], {})
        self.assertTrue(pack["model_aliases"]["reason"])


class SetupProfilePackVersionTests(_PackFixture):
    def test_a_pack_from_a_newer_omh_is_refused_as_newer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pack = build_setup_profile_pack(self._configured_source(Path(tmp)))
        pack["schema_version"] = "omh_setup_profile_pack/v2"

        refusal = pack_version_refusal(pack)

        self.assertIn("newer OMH", refusal)
        self.assertIn("omh_setup_profile_pack/v2", refusal)
        self.assertIn("update OMH", refusal)

    def test_an_unrecognized_pack_is_refused_without_claiming_it_is_newer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pack = build_setup_profile_pack(self._configured_source(Path(tmp)))
        pack["schema_version"] = "some_other_pack/v1"

        refusal = pack_version_refusal(pack)

        self.assertIn("some_other_pack/v1", refusal)
        self.assertNotIn("newer OMH", refusal)

    def test_a_newer_inner_profile_is_refused_too(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pack = build_setup_profile_pack(self._configured_source(Path(tmp)))
        pack["profile"]["schema_version"] = "setup_profile/v2"

        self.assertIn("newer OMH", pack_version_refusal(pack))

    def test_a_version_mismatch_writes_no_partial_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pack = build_setup_profile_pack(self._configured_source(root / "source"))
            pack["schema_version"] = "omh_setup_profile_pack/v2"
            target = self._paths(root / "target")

            with self.assertRaises(SetupProfilePackError) as caught:
                apply_setup_profile_pack(target, pack, dry_run=False)

            self.assertFalse(target.setup_profile_path.exists())
        self.assertIn("Nothing was written", str(caught.exception))


class SetupProfilePackApplyTests(_PackFixture):
    def test_applying_to_an_empty_profile_reproduces_the_configured_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._configured_source(root / "source")
            pack = build_setup_profile_pack(source)
            target = self._paths(root / "target")

            report = apply_setup_profile_pack(target, pack, dry_run=False)

            self.assertEqual(
                configured_field_summary(read_setup_profile(target)),
                configured_field_summary(read_setup_profile(source)),
            )
            self.assertEqual(
                read_capability_policy(target)["disabled_families"],
                read_capability_policy(source)["disabled_families"],
            )

        applied = {row["field"] for row in report["fields"] if row["status"] == "applied"}
        self.assertEqual(
            applied,
            {
                "default_executor",
                "operating_model_id",
                "memory_mode",
                "selected_categories",
                "capability_policy.disabled_families",
            },
        )
        self.assertTrue(report["applied"])
        for row in report["fields"]:
            self.assertIn(row["status"], ("applied", "not_applied"))

    def test_a_dry_run_reports_the_same_fields_and_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pack = build_setup_profile_pack(self._configured_source(root / "source"))
            target = self._paths(root / "target")

            report = apply_setup_profile_pack(target, pack, dry_run=True)

            self.assertFalse(target.setup_profile_path.exists())
        self.assertFalse(report["applied"])
        self.assertTrue(report["dry_run"])
        self.assertIsNone(report["profile_after"])
        would = {row["field"] for row in report["fields"] if row["status"] == "would_apply"}
        self.assertIn("default_executor", would)

    def test_a_field_this_omh_cannot_accept_is_reported_with_its_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pack = build_setup_profile_pack(self._configured_source(root / "source"))
            pack["profile"]["default_executor"] = "future-executor"
            pack["profile"]["operating_model_id"] = "future-model"
            target = self._paths(root / "target")

            report = apply_setup_profile_pack(target, pack, dry_run=False)
            written = read_setup_profile(target)

        rows = {row["field"]: row for row in report["fields"]}
        self.assertEqual(rows["default_executor"]["status"], "not_applied")
        self.assertIn("future-executor", rows["default_executor"]["reason"])
        self.assertIn("codex", rows["default_executor"]["reason"])
        self.assertEqual(rows["operating_model_id"]["status"], "not_applied")
        self.assertIn("future-model", rows["operating_model_id"]["reason"])
        # The rest of the pack still lands: one unknown name must not cost the
        # person every other field they configured.
        self.assertEqual(rows["memory_mode"]["status"], "applied")
        self.assertEqual(written["memory_mode"], "auto-safe")
        self.assertIn("default_executor", report["not_applied_fields"])

    def test_a_list_with_one_unknown_entry_applies_the_rest_and_says_which_fell(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pack = build_setup_profile_pack(self._configured_source(root / "source"))
            pack["capability_policy"]["disabled_families"] = ["retain_knowledge", "future_family"]
            target = self._paths(root / "target")

            report = apply_setup_profile_pack(target, pack, dry_run=False)
            policy = read_capability_policy(target)

        row = {r["field"]: r for r in report["fields"]}["capability_policy.disabled_families"]
        # `not_applied` beside a value that did land would send the reader
        # looking for a write that already happened, so a partial list reports
        # the write it made and names only what fell out.
        self.assertEqual(row["status"], "applied")
        self.assertEqual(row["value"], ["retain_knowledge"])
        self.assertIn("future_family", row["reason"])
        self.assertEqual(policy["disabled_families"], ["retain_knowledge"])

    def test_a_list_whose_every_entry_is_unknown_is_reported_as_not_applied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pack = build_setup_profile_pack(self._configured_source(root / "source"))
            pack["capability_policy"]["disabled_families"] = ["future_family"]
            target = self._paths(root / "target")

            report = apply_setup_profile_pack(target, pack, dry_run=False)
            policy = read_capability_policy(target)

        row = {r["field"]: r for r in report["fields"]}["capability_policy.disabled_families"]
        self.assertEqual(row["status"], "not_applied")
        self.assertIn("future_family", row["reason"])
        self.assertEqual(policy["disabled_families"], [])

    def test_the_report_states_what_matching_means_on_both_sides(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pack = build_setup_profile_pack(self._configured_source(root / "source"))

            report = apply_setup_profile_pack(self._paths(root / "target"), pack, dry_run=False)

        self.assertEqual(report["configured_after"], report["configured_in_pack"])
        self.assertEqual(report["configured_after"]["default_executor"], "codex")
        self.assertEqual(report["configured_after"]["disabled_families"], ["retain_knowledge"])

    def test_model_aliases_are_carried_reported_and_handed_back_as_a_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._configured_source(root / "source")
            self._with_hermes_aliases(
                source, {"main": "anthropic/claude-opus-5", "fast": "openai/gpt-6-astra"}
            )
            pack = build_setup_profile_pack(source)
            target = self._paths(root / "target")

            report = apply_setup_profile_pack(target, pack, dry_run=False)

            self.assertFalse(target.hermes_config_path.exists())
        rows = {row["field"]: row for row in report["fields"]}
        self.assertEqual(rows["model_aliases"]["status"], "not_applied")
        self.assertIn("--apply-model-config", rows["model_aliases"]["reason"])
        self.assertEqual(
            [action for action in report["next_actions"] if "--model-setup" in action],
            [
                "omh setup --model-setup --model-alias fast=openai/gpt-6-astra "
                "--model-alias main=anthropic/claude-opus-5 --apply-model-config"
            ],
        )

    def test_an_edited_parallelism_block_is_reported_rather_than_reset_in_silence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._configured_source(root / "source")
            profile = json.loads(source.setup_profile_path.read_text(encoding="utf-8"))
            profile["parallelism"]["global_concurrency"] = 3
            source.setup_profile_path.write_text(json.dumps(profile, sort_keys=True), encoding="utf-8")
            pack = build_setup_profile_pack(source)
            target = self._paths(root / "target")

            report = apply_setup_profile_pack(target, pack, dry_run=False)
            written = read_setup_profile(target)

        rows = {row["field"]: row for row in report["fields"]}
        self.assertEqual(rows["parallelism"]["status"], "not_applied")
        self.assertEqual(rows["parallelism"]["value"], {"global_concurrency": 3})
        self.assertIn("accepts no parallelism flag", rows["parallelism"]["reason"])
        self.assertEqual(written["parallelism"]["global_concurrency"], 8)

    def test_a_default_parallelism_block_produces_no_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pack = build_setup_profile_pack(self._configured_source(root / "source"))

            report = apply_setup_profile_pack(self._paths(root / "target"), pack, dry_run=False)

        self.assertNotIn("parallelism", {row["field"] for row in report["fields"]})

    def test_the_mcp_recipe_is_not_written_without_the_explicit_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._configured_source(root / "source")
            self._with_mcp_record(source)
            pack = build_setup_profile_pack(source)

            report = apply_setup_profile_pack(self._paths(root / "target"), pack, dry_run=False)

        rows = {row["field"]: row for row in report["fields"]}
        self.assertEqual(rows["mcp.host_config"]["status"], "not_applied")
        self.assertIn("--with-mcp", rows["mcp.host_config"]["reason"])
        self.assertIn(
            "omh setup --with-mcp --mcp-host codex --mcp-command omh", report["next_actions"]
        )

    def test_with_mcp_writes_the_host_entry_through_the_existing_setup_writer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._configured_source(root / "source")
            self._with_mcp_record(source)
            pack = build_setup_profile_pack(source)
            host_config = root / "target-codex-config.toml"

            report = apply_setup_profile_pack(
                self._paths(root / "target"),
                pack,
                dry_run=False,
                with_mcp=True,
                mcp_config_path=host_config,
            )

            self.assertTrue(host_config.exists())
            self.assertIn("mcp_servers.omh", host_config.read_text(encoding="utf-8"))
        rows = {row["field"]: row for row in report["fields"]}
        self.assertEqual(rows["mcp.host_config"]["status"], "applied")

    def test_with_mcp_on_a_dry_run_writes_no_host_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._configured_source(root / "source")
            self._with_mcp_record(source)
            pack = build_setup_profile_pack(source)
            host_config = root / "target-codex-config.toml"

            report = apply_setup_profile_pack(
                self._paths(root / "target"),
                pack,
                dry_run=True,
                with_mcp=True,
                mcp_config_path=host_config,
            )

            self.assertFalse(host_config.exists())
        rows = {row["field"]: row for row in report["fields"]}
        self.assertEqual(rows["mcp.host_config"]["status"], "would_apply")

    def test_the_withheld_list_travels_into_the_apply_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._configured_source(root / "source")
            self._inject_profile_keys(source, {"github_token": _SOURCE_SECRET})
            pack = build_setup_profile_pack(source)

            report = apply_setup_profile_pack(self._paths(root / "target"), pack, dry_run=True)

        self.assertIn(
            "profile.github_token", {entry["field"] for entry in report["withheld"]}
        )


class SetupProfilePackFileTests(_PackFixture):
    def test_a_written_pack_reads_back_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self._configured_source(root)
            target = root / "nested" / "pack.json"

            written = write_setup_profile_pack(paths, target)

            self.assertEqual(read_setup_profile_pack(target), written)

    def test_a_non_object_pack_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pack.json"
            path.write_text("[1, 2]", encoding="utf-8")

            with self.assertRaises(SetupProfilePackError):
                read_setup_profile_pack(path)

    def test_invalid_json_is_refused_with_a_readable_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pack.json"
            path.write_text("{not json", encoding="utf-8")

            with self.assertRaises(SetupProfilePackError) as caught:
                read_setup_profile_pack(path)

        self.assertIn("not valid JSON", str(caught.exception))


class SetupProfilePackCliTests(_PackFixture):
    def _cli(self, root: Path, *args: str) -> tuple[int, dict]:
        status, stdout, _ = run_cli(
            [
                "--omh-home",
                str(root / ".omh"),
                "--hermes-home",
                str(root / ".hermes"),
                *args,
            ]
        )
        return status, json.loads(stdout)

    def test_export_writes_the_pack_and_reports_what_it_withheld(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self._configured_source(root)
            self._inject_profile_keys(paths, {"github_token": _SOURCE_SECRET})
            output = root / "pack.json"

            status, payload = self._cli(root, "setup-profile", "export", "--output", str(output))

            self.assertEqual(status, 0)
            self.assertTrue(output.exists())
            self.assertNotIn(_SOURCE_SECRET, output.read_text(encoding="utf-8"))
        self.assertEqual(payload["output_path"], str(output))
        self.assertEqual(payload["withheld_field_count"], len(payload["withheld"]))
        self.assertIn("profile.github_token", {entry["field"] for entry in payload["withheld"]})
        self.assertIn("no network calls", payload["transport_boundary"])

    def test_export_without_output_prints_the_pack_for_piping(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._configured_source(root)

            status, payload = self._cli(root, "setup-profile", "export")

        self.assertEqual(status, 0)
        self.assertEqual(payload["pack"]["schema_version"], SETUP_PROFILE_PACK_SCHEMA_VERSION)
        self.assertEqual(payload["output_path"], "")
        self.assertEqual(payload["configured"]["default_executor"], "codex")
        self.assertEqual(payload["configured"]["disabled_families"], ["retain_knowledge"])

    def test_apply_is_a_dry_run_until_apply_is_passed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_root = root / "source"
            write_setup_profile_pack(self._configured_source(source_root), root / "pack.json")
            target_root = root / "target"

            status, dry = self._cli(
                target_root, "setup-profile", "apply", "--from", str(root / "pack.json")
            )
            self.assertEqual(status, 0)
            self.assertFalse((target_root / ".omh" / "setup-profile.json").exists())

            status, applied = self._cli(
                target_root,
                "setup-profile",
                "apply",
                "--from",
                str(root / "pack.json"),
                "--apply",
            )
            self.assertEqual(status, 0)
            self.assertTrue((target_root / ".omh" / "setup-profile.json").exists())

        self.assertFalse(dry["applied"])
        self.assertTrue(applied["applied"])
        self.assertEqual(applied["profile_after"]["default_executor"], "codex")

    def test_apply_refuses_a_newer_pack_at_the_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pack_path = root / "pack.json"
            pack = build_setup_profile_pack(self._configured_source(root / "source"))
            pack["schema_version"] = "omh_setup_profile_pack/v2"
            pack_path.write_text(json.dumps(pack), encoding="utf-8")
            target_root = root / "target"

            status, stdout, stderr = run_cli(
                [
                    "--omh-home",
                    str(target_root / ".omh"),
                    "--hermes-home",
                    str(target_root / ".hermes"),
                    "setup-profile",
                    "apply",
                    "--from",
                    str(pack_path),
                    "--apply",
                ]
            )

            # A refusal must not read as a completed apply to a shell that only
            # checks the status, so the code is the CLI's error code, not 0.
            self.assertEqual(status, 2)
            self.assertEqual(stdout, "")
            self.assertFalse((target_root / ".omh" / "setup-profile.json").exists())
        self.assertIn("newer OMH", stderr)
        self.assertIn("Nothing was written", stderr)

    def test_the_human_export_output_names_every_withheld_field(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self._configured_source(root)
            self._inject_profile_keys(paths, {"github_token": _SOURCE_SECRET})

            status, stdout, _ = run_cli(
                [
                    "--omh-home",
                    str(root / ".omh"),
                    "--hermes-home",
                    str(root / ".hermes"),
                    "setup-profile",
                    "export",
                ],
                output_json=False,
            )

        self.assertEqual(status, 0)
        self.assertIn("profile.github_token", stdout)
        self.assertNotIn(_SOURCE_SECRET, stdout)

    def test_the_human_apply_output_names_each_field_and_its_verdict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._configured_source(root / "source")
            self._with_hermes_aliases(source, {"main": "anthropic/claude-opus-5"})
            write_setup_profile_pack(source, root / "pack.json")
            target_root = root / "target"

            status, stdout, _ = run_cli(
                [
                    "--omh-home",
                    str(target_root / ".omh"),
                    "--hermes-home",
                    str(target_root / ".hermes"),
                    "setup-profile",
                    "apply",
                    "--from",
                    str(root / "pack.json"),
                    "--apply",
                ],
                output_json=False,
            )

        self.assertEqual(status, 0)
        self.assertIn("[applied] default_executor = codex", stdout)
        self.assertIn("[not applied] model_aliases", stdout)
        self.assertIn("--apply-model-config", stdout)


if __name__ == "__main__":
    unittest.main()
