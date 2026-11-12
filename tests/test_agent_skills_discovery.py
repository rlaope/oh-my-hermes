"""Agent Skills host evidence: descriptors, receipts, matrix, command; no third-party host runs.

Every version probe here is a stub or a fixture script on a temporary PATH,
and every scan path is under a temporary project root or a temporary home.
The tests pin the contract: ``installed`` is observed from bytes against the
adapter manifest, no later stage is ever observed without a probe that
observes it, and a malformed or contradictory receipt raises.
"""

from __future__ import annotations

import contextlib
import copy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from _cli_harness import run_cli
from _credential_fixtures import AWS_ACCESS_KEY_ID
from _platform_support import requires_posix, requires_posix_permissions, requires_symlinks
from omh.coding.executor_readiness import agent_cli_version, version_probed_agent_clis
from omh.install.agent_skills_projection import agent_skill_files, agent_skills_manifest, install_agent_skills
from omh.quality.agent_skills_discovery import (
    EVIDENCE_SCHEMA_VERSION,
    HOSTS,
    OBSERVED_CLAIM_BOUNDARY,
    PROBE_UNSUPPORTED,
    RECEIPT_SCHEMA_VERSION,
    SCOPES,
    STAGES,
    STORED_CLAIM_BOUNDARY,
    CurrentPack,
    DiscoveryEvidenceError,
    ProbeDescriptor,
    build_agent_skills_evidence,
    format_agent_skills_evidence,
    load_evidence_receipts,
    parse_receipt,
    probe_descriptors,
    summarize_receipts,
)
from omh.skills.host_adapters import HOST_ADAPTERS, host_adapter, host_pack_files, source_digest

ROOT = Path(__file__).resolve().parents[1]
T0 = datetime(2026, 10, 14, 3, 0, 0, tzinfo=timezone.utc)
VERSIONS = {"claude": ("observed", "9.8.7"), "codex": ("executable_missing", None)}


def stub_probe(host: str) -> tuple[str, str | None]:
    return VERSIONS.get(host, ("executable_missing", None))


def ticking_clock():
    moments = iter(T0 + timedelta(seconds=index) for index in range(1000))
    return lambda: next(moments)


def tree(root: Path) -> dict[str, tuple[int, bytes | None]]:
    """Every entry under ``root`` (directories too) with its full mode and, for files, its bytes."""
    snapshot: dict[str, tuple[int, bytes | None]] = {}
    for path in root.rglob("*"):
        mode = path.lstat().st_mode
        snapshot[path.relative_to(root).as_posix()] = (mode, path.read_bytes() if stat.S_ISREG(mode) else None)
    return snapshot


def evidence(project: Path, home: Path, **kwargs):
    kwargs.setdefault("version_probe", stub_probe)
    kwargs.setdefault("clock", ticking_clock())
    return build_agent_skills_evidence(project_root=project, user_home=home, **kwargs)


def row(payload, host: str, scope: str) -> dict:
    return next(item for item in payload["matrix"] if item["host"] == host and item["scope"] == scope)


def receipt_of(payload, host: str, scope: str) -> dict:
    return next(item for item in payload["receipts"] if item["host"] == host and item["scope"] == scope)


class Roots(unittest.TestCase):
    def setUp(self) -> None:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.project = Path(tmp.name) / "project"
        self.home = Path(tmp.name) / "home"
        self.project.mkdir()
        self.home.mkdir()


class DescriptorTests(unittest.TestCase):
    def test_one_descriptor_per_adapter_host_and_scope_with_the_adapter_paths(self):
        descriptors = probe_descriptors(version_probed=())
        self.assertEqual([(d.host, d.scope) for d in descriptors], [(h, s) for h in HOSTS for s in SCOPES])
        self.assertEqual(set(HOSTS), {adapter.host for adapter in HOST_ADAPTERS})
        for descriptor in descriptors:
            adapter = host_adapter(descriptor.host)
            with self.subTest(host=descriptor.host, scope=descriptor.scope):
                expected = adapter.repo_path if descriptor.scope == "repo" else adapter.user_path
                self.assertEqual(descriptor.target_path, expected)
                self.assertEqual(descriptor.transform, adapter.transform)
                self.assertEqual(descriptor.discovery_mechanism, "none")
                self.assertIs(descriptor.credential_required, True)
                self.assertEqual(descriptor.probe_unsupported, PROBE_UNSUPPORTED[descriptor.host])

    def test_every_adapter_host_has_a_probe_unsupported_reason(self):
        self.assertEqual(set(PROBE_UNSUPPORTED), {adapter.host for adapter in HOST_ADAPTERS})

    def test_a_version_command_only_for_a_cli_the_readiness_probe_already_runs(self):
        only_claude = probe_descriptors(version_probed={"claude"})
        self.assertEqual({d.host for d in only_claude if d.version_command}, {"claude"})
        default = probe_descriptors()
        self.assertEqual(
            {d.host for d in default if d.version_command}, set(HOSTS) & version_probed_agent_clis()
        )
        for descriptor in default:
            if descriptor.version_command:
                self.assertEqual(descriptor.version_command, (descriptor.host, "--version"))

    def test_descriptor_rejects_contradictory_shapes(self):
        base = probe_descriptors(version_probed=())[0]
        fields = {name: getattr(base, name) for name in ProbeDescriptor.__slots__}
        for change in (
            {"credential_required": "false"},
            {"credential_required": None},
            {"probe_unsupported": ""},
            {"version_command": ("sh", "-c", "anything")},
            {"target_path": "/etc/skills"},
            {"target_path": "../skills"},
            {"host": "vim"},
            {"scope": "global"},
            {"discovery_mechanism": "model_mediated"},
        ):
            with self.subTest(change=change), self.assertRaises(DiscoveryEvidenceError):
                ProbeDescriptor(**{**fields, **change})


@requires_posix
class AgentCliVersionTests(unittest.TestCase):
    """The reused readiness probe, against fixture scripts only."""

    def _script(self, directory: str, name: str, body: str) -> None:
        path = Path(directory) / name
        path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8", newline="")
        path.chmod(path.stat().st_mode | stat.S_IEXEC)

    def test_a_cli_outside_the_readiness_set_is_never_resolved(self):
        self.assertNotIn("cursor", version_probed_agent_clis())
        with patch("omh.coding.executor_readiness.shutil.which", side_effect=AssertionError("resolved")):
            self.assertEqual(agent_cli_version("cursor"), ("no_approved_probe", None))

    def test_version_token_only_and_every_failure_status(self):
        with TemporaryDirectory() as bin_dir:
            with patch.dict(os.environ, {"PATH": bin_dir}):
                self.assertEqual(agent_cli_version("claude"), ("executable_missing", None))
                self._script(bin_dir, "claude", "echo '9.8.7 (Claude Code) and other words'")
                self.assertEqual(agent_cli_version("claude"), ("observed", "9.8.7"))
                self._script(bin_dir, "claude", "echo 'v1.2.3-beta.1'")
                self.assertEqual(agent_cli_version("claude"), ("observed", "1.2.3-beta.1"))
                self._script(bin_dir, "claude", "echo 'no version here'")
                self.assertEqual(agent_cli_version("claude"), ("output_unrecognized", None))
                self._script(bin_dir, "claude", "echo '9.8.7'; exit 3")
                self.assertEqual(agent_cli_version("claude"), ("probe_failed", None))


def valid_evidence() -> dict:
    with TemporaryDirectory() as tmp:
        project, home = Path(tmp) / "p", Path(tmp) / "h"
        project.mkdir()
        home.mkdir()
        install_agent_skills(project / ".claude/skills")
        return evidence(project, home)


class ReceiptParsingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        payload = valid_evidence()
        cls.base = receipt_of(payload, "claude", "repo")
        cls.cursor = receipt_of(payload, "cursor", "repo")

    def payload(self) -> dict:
        return copy.deepcopy(self.base)

    def assertRejected(self, payload) -> None:
        with self.assertRaises(DiscoveryEvidenceError):
            parse_receipt(payload)

    def test_round_trip_through_json(self):
        receipt = parse_receipt(json.loads(json.dumps(self.base)))
        self.assertEqual(receipt.to_json(), self.base)
        self.assertEqual(receipt.highest_observed_stage(), "installed")
        self.assertEqual(self.base["schema_version"], RECEIPT_SCHEMA_VERSION)
        self.assertEqual(self.base["host_version"], "9.8.7")
        self.assertEqual(self.base["version_command"], ["claude", "--version"])

    def test_field_set_must_be_exact(self):
        extra = self.payload()
        extra["note"] = "anything"
        self.assertRejected(extra)
        for key in self.base:
            missing = self.payload()
            del missing[key]
            with self.subTest(missing=key):
                self.assertRejected(missing)
        self.assertRejected([self.base])

    def test_enumerated_fields_reject_unknown_values(self):
        for key, value in (
            ("schema_version", "omh_agent_skills_discovery/v0"),
            ("adapter_schema_version", "omh_host_adapter/v2"),
            ("host", "vim"),
            ("scope", "global"),
            ("os", "plan9"),
            ("transform", "rewrite"),
            ("discovery_mechanism", "model_mediated"),
            ("cleanup", "removed"),
            ("host_version_status", "maybe"),
        ):
            payload = self.payload()
            payload[key] = value
            with self.subTest(key=key):
                self.assertRejected(payload)

    def test_credential_required_must_be_a_real_bool(self):
        for value in ("false", "true", 0, 1, None):
            payload = self.payload()
            payload["credential_required"] = value
            with self.subTest(value=value):
                self.assertRejected(payload)

    def test_host_version_agrees_with_its_status_and_command(self):
        cases = (
            {"host_version": None},
            {"host_version": "latest"},
            {"host_version_status": "executable_missing"},
            {"host_version_status": "no_approved_probe", "host_version": None},
            {"version_command": ["sh", "-c", "claude --version"]},
            {"version_command": []},
        )
        for change in cases:
            payload = {**self.payload(), **change}
            with self.subTest(change=change):
                self.assertRejected(payload)

    def test_a_version_probe_only_for_a_cli_the_readiness_probe_runs(self):
        self.assertNotIn("cursor", version_probed_agent_clis())
        cursor = copy.deepcopy(self.cursor)
        self.assertEqual(cursor["host_version_status"], "no_approved_probe")
        self.assertIsNone(parse_receipt(cursor).host_version)
        forged = {
            **cursor, "host_version_status": "observed", "host_version": "1.0.0", "version_command": ["cursor", "--version"],
        }
        self.assertRejected(forged)
        unprobed_claude = {**self.payload(), "host_version_status": "no_approved_probe", "host_version": None, "version_command": []}
        self.assertRejected(unprobed_claude)

    def test_exactly_the_five_stages_in_order(self):
        payload = self.payload()
        payload["stages"] = payload["stages"][:4]
        self.assertRejected(payload)
        payload = self.payload()
        payload["stages"].append(dict(payload["stages"][0]))
        self.assertRejected(payload)
        payload = self.payload()
        payload["stages"][0], payload["stages"][1] = payload["stages"][1], payload["stages"][0]
        self.assertRejected(payload)
        payload = self.payload()
        payload["stages"][1]["stage"] = "installed"
        self.assertRejected(payload)
        payload = self.payload()
        payload["stages"][0]["stage"] = "teleported"
        self.assertRejected(payload)
        payload = self.payload()
        payload["stages"][0]["outcome"] = "passed"
        self.assertRejected(payload)
        payload = self.payload()
        payload["stages"][0]["extra"] = "x"
        self.assertRejected(payload)

    def test_each_stage_reason_fits_its_outcome(self):
        for reason in ("absent", "unreadable", "teleported"):
            payload = self.payload()
            payload["stages"][0]["reason"] = reason
            with self.subTest(reason=reason):
                self.assertRejected(payload)
        payload = self.payload()
        payload["stages"][2]["reason"] = "match"
        self.assertRejected(payload)
        payload = self.payload()
        payload["stages"][0].update(outcome="hold", reason="unreadable")
        self.assertEqual(parse_receipt(payload).stage("installed").reason, "unreadable")

    def test_no_later_stage_is_observed_or_held_without_a_probe_that_observes_it(self):
        for index, stage in enumerate(STAGES[1:], start=1):
            for outcome in ("observed", "hold"):
                payload = self.payload()
                payload["stages"][index]["outcome"] = outcome
                with self.subTest(stage=stage, outcome=outcome):
                    self.assertRejected(payload)

    def test_credential_like_and_oversized_text_fails_closed(self):
        payload = self.payload()
        payload["stages"][0]["detail"] = f"copied with {AWS_ACCESS_KEY_ID}"
        self.assertRejected(payload)
        payload = self.payload()
        payload["probe_unsupported"] = f"key {AWS_ACCESS_KEY_ID}"
        self.assertRejected(payload)
        payload = self.payload()
        payload["stages"][0]["detail"] = "x" * 241
        self.assertRejected(payload)

    def test_digests_paths_and_timestamps_are_validated(self):
        for key, value in (
            ("source_digest", "not-a-digest"),
            ("catalog_revision", "A" * 64),
            ("target_path", "/home/someone/.claude/skills"),
            ("target_path", "../.claude/skills"),
            ("target_path", "C:\\skills"),
            ("started_at", "2026-10-14 03:00:00"),
            ("ended_at", "2026-13-14T03:00:00Z"),
        ):
            payload = self.payload()
            payload[key] = value
            with self.subTest(key=key, value=value):
                self.assertRejected(payload)
        payload = self.payload()
        payload["started_at"], payload["ended_at"] = "2026-10-14T03:00:09Z", "2026-10-14T03:00:01Z"
        self.assertRejected(payload)


class ObservationTests(Roots):
    def test_nothing_installed_is_not_observed_everywhere_and_nothing_is_written(self):
        payload = evidence(self.project, self.home)
        self.assertEqual(payload["schema_version"], EVIDENCE_SCHEMA_VERSION)
        self.assertEqual(payload["receipt_source"], "observed")
        self.assertEqual(len(payload["receipts"]), len(HOSTS) * len(SCOPES))
        for receipt in payload["receipts"]:
            with self.subTest(host=receipt["host"], scope=receipt["scope"]):
                self.assertEqual([stage["outcome"] for stage in receipt["stages"]], ["not_observed"] * 5)
                self.assertEqual(receipt["cleanup"], "nothing_created")
        self.assertEqual(tree(self.project), {})
        self.assertEqual(tree(self.home), {})

    def test_installed_is_observed_from_bytes_per_scan_path_and_nothing_later_is(self):
        install_agent_skills(self.project / ".claude/skills")
        before = tree(self.project)
        payload = evidence(self.project, self.home)
        self.assertEqual(tree(self.project), before)
        claude = row(payload, "claude", "repo")
        self.assertEqual(claude["evidence_class"], "observed_through_installed")
        self.assertEqual(claude["highest_observed_stage"], "installed")
        self.assertEqual(claude["freshness"], "current")
        # The `.agents/skills` hosts scan a different path: the Claude copy is
        # not their installation.
        self.assertEqual(row(payload, "codex", "repo")["installed"], "not_observed")
        self.assertEqual(row(payload, "claude", "user")["installed"], "not_observed")
        receipt = receipt_of(payload, "claude", "repo")
        self.assertEqual([stage["outcome"] for stage in receipt["stages"][1:]], ["not_observed"] * 4)
        self.assertEqual(receipt["probe_unsupported"], PROBE_UNSUPPORTED["claude"])

    def test_receipt_binds_the_inventory_digest_and_the_pack_revision(self):
        files = agent_skill_files()
        payload = evidence(self.project, self.home)
        for host in HOSTS:
            committed = json.loads((ROOT / f".{host}" / "manifest.json").read_text(encoding="utf-8"))
            with self.subTest(host=host):
                # The adapter points at the pack's one inventory; the digest a
                # receipt binds is that inventory's, identical for every host.
                inventory = json.loads((ROOT / committed["source"] / committed["inventory"]).read_bytes())
                self.assertEqual(inventory["files"], agent_skills_manifest(host_pack_files(host, files))["files"])
                for scope in SCOPES:
                    receipt = receipt_of(payload, host, scope)
                    self.assertEqual(receipt["source_digest"], source_digest(inventory["files"]))
                    self.assertEqual(receipt["transform"], committed["transform"])
                    self.assertEqual(receipt["adapter_schema_version"], committed["schema_version"])
                    self.assertEqual(receipt["target_path"], committed["targets"][scope])
                    self.assertEqual(receipt["catalog_revision"], agent_skills_manifest(files)["catalog_revision"])

    def test_user_scope_reads_the_given_home_not_the_project_or_path_home(self):
        install_agent_skills(self.home / ".agents/skills")
        with patch("pathlib.Path.home", side_effect=AssertionError("real home read")):
            payload = evidence(self.project, self.home, scopes=("user",))
        self.assertEqual({item["scope"] for item in payload["matrix"]}, {"user"})
        self.assertEqual(row(payload, "codex", "user")["installed"], "observed")
        self.assertEqual(row(payload, "claude", "user")["installed"], "not_observed")
        self.assertEqual(tree(self.project), {})

    def test_a_partial_or_modified_pack_holds(self):
        install_agent_skills(self.project / ".agents/skills")
        (self.project / ".agents/skills/omh-plan/SKILL.md").write_bytes(b"edited\n")
        payload = evidence(self.project, self.home, scopes=("repo",))
        self.assertEqual(row(payload, "codex", "repo")["evidence_class"], "hold")
        self.assertEqual(row(payload, "codex", "repo")["installed_reason"], "modified")
        self.assertIn("0 missing, 1 differ", row(payload, "codex", "repo")["installed_detail"])
        self.assertEqual(payload["unread_scan_paths"], [])
        (self.project / ".agents/skills/omh-plan/SKILL.md").unlink()
        payload = evidence(self.project, self.home, scopes=("repo",))
        self.assertEqual(row(payload, "pi", "repo")["installed_reason"], "partial")
        self.assertIn("1 missing, 0 differ", row(payload, "pi", "repo")["installed_detail"])

    @requires_posix_permissions
    def test_an_unreadable_scan_directory_or_file_holds_as_unreadable(self):
        skills = self.project / ".claude/skills"
        install_agent_skills(skills)
        skill_file = skills / "omh-plan/SKILL.md"
        skills.chmod(0)
        self.addCleanup(skills.chmod, 0o755)
        payload = evidence(self.project, self.home, scopes=("repo",))
        self.assertEqual(row(payload, "claude", "repo")["installed"], "hold")
        self.assertEqual(row(payload, "claude", "repo")["installed_reason"], "unreadable")
        self.assertEqual(payload["unread_scan_paths"], [{"host": "claude", "scope": "repo"}])
        skills.chmod(0o755)
        skill_file.chmod(0)
        self.addCleanup(skill_file.chmod, 0o644)
        payload = evidence(self.project, self.home, scopes=("repo",))
        self.assertEqual(row(payload, "claude", "repo")["installed_reason"], "unreadable")

    def test_os_name_comes_from_sys_platform(self):
        from omh.quality import agent_skills_discovery as module

        for value, expected in (("win32", "windows"), ("darwin", "darwin"), ("linux", "linux"), ("freebsd14", "other")):
            with self.subTest(platform=value), patch.object(module.sys, "platform", value):
                self.assertEqual(module._os_name(), expected)
        self.assertNotIn("import platform", Path(module.__file__).read_text(encoding="utf-8"))

    def test_a_clock_step_backwards_does_not_void_the_run(self):
        moments = iter([T0 + timedelta(seconds=5), T0] * 100)
        payload = evidence(self.project, self.home, clock=lambda: next(moments))
        receipt = receipt_of(payload, "claude", "repo")
        self.assertEqual(receipt["started_at"], receipt["ended_at"])

    @requires_symlinks
    def test_a_symlinked_scan_path_holds_instead_of_following_it(self):
        elsewhere = self.home / "elsewhere"
        install_agent_skills(elsewhere)
        (self.project / ".claude").mkdir()
        (self.project / ".claude/skills").symlink_to(elsewhere, target_is_directory=True)
        payload = evidence(self.project, self.home, scopes=("repo",))
        self.assertEqual(row(payload, "claude", "repo")["installed"], "hold")
        self.assertEqual(row(payload, "claude", "repo")["installed_reason"], "symlink")
        self.assertIn("symlink", row(payload, "claude", "repo")["installed_detail"])

    @requires_symlinks
    def test_a_relative_root_still_refuses_a_symlinked_scan_path_parent(self):
        # The parent (`.claude`) is the symlink: `_checked_path` joins a
        # relative ancestor onto the root, so only an absolute root reaches it.
        from omh.quality.agent_skills_discovery import _installed_stage

        elsewhere = self.home / "elsewhere"
        install_agent_skills(elsewhere / "skills")
        (self.project / ".claude").symlink_to(elsewhere, target_is_directory=True)
        files = agent_skills_manifest(agent_skill_files())["files"]
        with contextlib.chdir(self.project.parent):
            stage = _installed_stage(Path(self.project.name), ".claude/skills", files)
        self.assertEqual((stage.outcome, stage.reason), ("hold", "symlink"))

    def test_an_existing_scan_directory_without_the_pack_is_absent(self):
        (self.project / ".agents/skills/someone-elses-skill").mkdir(parents=True)
        (self.project / ".agents/skills/someone-elses-skill/SKILL.md").write_bytes(b"---\nname: x\n---\n")
        payload = evidence(self.project, self.home, scopes=("repo",))
        codex = row(payload, "codex", "repo")
        self.assertEqual((codex["installed"], codex["installed_reason"]), ("not_observed", "absent"))
        self.assertIn("none of the", codex["installed_detail"])

    def test_hosts_sharing_a_scan_path_share_the_window_of_the_one_read(self):
        install_agent_skills(self.project / ".agents/skills")
        payload = evidence(self.project, self.home, scopes=("repo",))
        shared = [r for r in payload["receipts"] if r["target_path"] == ".agents/skills"]
        self.assertEqual(len(shared), len(HOSTS) - 1)
        self.assertEqual({(r["started_at"], r["ended_at"]) for r in shared}, {(shared[0]["started_at"], shared[0]["ended_at"])})
        claude = receipt_of(payload, "claude", "repo")
        self.assertNotEqual((claude["started_at"], claude["ended_at"]), (shared[0]["started_at"], shared[0]["ended_at"]))
        self.assertEqual({row(payload, r["host"], "repo")["observed_at"] for r in shared}, {shared[0]["started_at"]})

    def test_the_producer_refuses_to_emit_a_receipt_the_parser_rejects(self):
        with self.assertRaises(DiscoveryEvidenceError):
            evidence(self.project, self.home, version_probe=lambda host: ("observed", "not a version"))

    def test_version_probe_runs_once_per_host_and_only_for_approved_clis(self):
        asked: list[str] = []

        def probe(host: str):
            asked.append(host)
            return ("executable_missing", None)

        payload = evidence(self.project, self.home, version_probe=probe)
        approved = sorted(set(HOSTS) & version_probed_agent_clis())
        self.assertEqual(sorted(asked), approved)
        for host in sorted(set(HOSTS) - set(approved)):
            self.assertEqual(row(payload, host, "repo")["host_version_status"], "no_approved_probe")
            self.assertEqual(receipt_of(payload, host, "repo")["version_command"], [])


class MatrixTests(Roots):
    def setUp(self) -> None:
        super().setUp()
        install_agent_skills(self.project / ".claude/skills")
        self.payload = evidence(self.project, self.home)
        self.receipts = [parse_receipt(item) for item in self.payload["receipts"]]
        files = agent_skill_files()
        self.current = CurrentPack(
            catalog_revision=agent_skills_manifest(files)["catalog_revision"],
            source_digests={host: source_digest(agent_skills_manifest(host_pack_files(host, files))["files"])
                            for host in HOSTS},
            target_paths={(d.host, d.scope): d.target_path for d in probe_descriptors(version_probed=())},
            os=self.payload["current"]["os"],
            host_versions={"claude": "9.8.7"},
        )

    def claude_repo(self, current: CurrentPack) -> dict:
        rows = summarize_receipts(self.receipts, current=current)
        return next(r.to_json() for r in rows if (r.host, r.scope) == ("claude", "repo"))

    def test_matrix_is_deterministic_and_sorted_by_host_then_scope(self):
        first = summarize_receipts(self.receipts, current=self.current)
        second = summarize_receipts(reversed(self.receipts), current=self.current)
        self.assertEqual(first, second)
        self.assertEqual([(r.host, r.scope) for r in first], [(h, s) for h in HOSTS for s in SCOPES])

    def test_a_host_and_scope_without_a_receipt_is_an_explicit_row(self):
        rows = summarize_receipts(self.receipts[2:], current=self.current)
        missing = [r for r in rows if r.evidence_class == "no_receipt"]
        self.assertEqual([(r.host, r.scope) for r in missing], [(HOSTS[0], "repo"), (HOSTS[0], "user")])
        self.assertEqual({r.freshness for r in missing}, {"no_receipt"})
        self.assertEqual(len(rows), len(HOSTS) * len(SCOPES))

    def test_duplicate_receipts_fail_closed(self):
        with self.assertRaises(DiscoveryEvidenceError):
            summarize_receipts([*self.receipts, self.receipts[0]], current=self.current)

    def test_freshness_compares_digest_revision_scan_path_os_and_host_version(self):
        self.assertEqual(self.claude_repo(self.current)["freshness"], "current")
        changes = {
            "source_digests": {**self.current.source_digests, "claude": "c" * 64},
            "catalog_revision": "d" * 64,
            "target_paths": {**self.current.target_paths, ("claude", "repo"): ".claude/skills-v2"},
            "os": "elsewhere",
            "host_versions": {"claude": "9.8.8"},
        }
        for field, value in changes.items():
            with self.subTest(field=field):
                self.assertEqual(self.claude_repo(replace(self.current, **{field: value}))["freshness"], "stale")
        unobserved_now = replace(self.current, host_versions={})
        self.assertEqual(self.claude_repo(unobserved_now)["freshness"], "version_unverified")
        self.assertEqual(row(self.payload, "cursor", "repo")["freshness"], "version_unverified")


class CommandTests(Roots):
    def args(self, *extra: str) -> list[str]:
        return [
            "quality-evidence", "agent-skills", "--project-root", str(self.project), "--user-home", str(self.home), *extra,
        ]

    def receipts_args(self, path: str) -> list[str]:
        return ["quality-evidence", "agent-skills", "--receipts", path]

    def run_patched(self, args, probe=stub_probe, **kwargs):
        with patch("omh.coding.executor_readiness.agent_cli_version", side_effect=probe):
            return run_cli(args, **kwargs)

    def test_json_and_text_output(self):
        install_agent_skills(self.project / ".claude/skills")
        before = tree(self.project)
        status, stdout, stderr = self.run_patched(self.args("--json"), output_json=False)
        text_status, text_stdout, text_stderr = self.run_patched(self.args(), output_json=False)
        self.assertEqual((status, text_status), (0, 0), stderr + text_stderr)
        self.assertEqual(tree(self.project), before)
        self.assertEqual(tree(self.home), {})
        payload = json.loads(stdout)
        self.assertEqual(payload["schema_version"], EVIDENCE_SCHEMA_VERSION)
        self.assertEqual(len(payload["matrix"]), len(HOSTS) * len(SCOPES))
        self.assertEqual(row(payload, "claude", "repo")["evidence_class"], "observed_through_installed")
        self.assertEqual(payload["claim_boundary"], OBSERVED_CLAIM_BOUNDARY)
        self.assertEqual(payload["unread_scan_paths"], [])
        self.assertNotIn(str(self.project), stdout)
        self.assertNotIn(str(self.home), stdout)
        self.assertIn("observed_through_installed", text_stdout)
        self.assertIn("Boundary:", text_stdout)
        self.assertEqual(text_stdout.strip(), format_agent_skills_evidence(payload).strip())

    def test_one_scope(self):
        status, stdout, stderr = self.run_patched(self.args("--scope", "repo"))
        self.assertEqual(status, 0, stderr)
        self.assertEqual({item["scope"] for item in json.loads(stdout)["matrix"]}, {"repo"})

    def test_stored_receipts_report_freshness_against_the_host_version_now(self):
        install_agent_skills(self.project / ".claude/skills")
        status, stdout, stderr = self.run_patched(self.args())
        self.assertEqual(status, 0, stderr)
        saved = self.home.parent / "evidence.json"
        saved.write_text(stdout, encoding="utf-8", newline="")
        self.assertEqual(len(load_evidence_receipts(saved)), len(HOSTS) * len(SCOPES))

        same_status, same_stdout, _ = self.run_patched(self.receipts_args(str(saved)))
        upgraded = lambda host: ("observed", "9.9.0") if host == "claude" else stub_probe(host)
        moved_status, moved_stdout, _ = self.run_patched(self.receipts_args(str(saved)), probe=upgraded)

        self.assertEqual((same_status, moved_status), (0, 0))
        same = json.loads(same_stdout)
        self.assertEqual(same["receipt_source"], "stored")
        self.assertEqual(same["claim_boundary"], STORED_CLAIM_BOUNDARY)
        self.assertEqual(row(same, "claude", "repo")["freshness"], "current")
        self.assertEqual(row(json.loads(moved_stdout), "claude", "repo")["freshness"], "stale")

    def test_receipts_in_utf16_or_with_a_bom_load(self):
        status, stdout, stderr = self.run_patched(self.args())
        self.assertEqual(status, 0, stderr)
        for name, encoding in (("utf16.json", "utf-16"), ("bom.json", "utf-8-sig")):
            saved = self.home.parent / name
            saved.write_bytes(stdout.encode(encoding))
            with self.subTest(encoding=encoding):
                self.assertEqual(len(load_evidence_receipts(saved)), len(HOSTS) * len(SCOPES))

    def test_receipts_refuse_scan_path_options(self):
        saved = self.home.parent / "evidence.json"
        saved.write_text("{}", encoding="utf-8", newline="")
        for option, value in (("--project-root", self.project), ("--user-home", self.home)):
            with self.subTest(option=option):
                status, stdout, stderr = self.run_patched(
                    ["quality-evidence", "agent-skills", "--receipts", str(saved), option, str(value)]
                )
                self.assertEqual(status, 2)
                self.assertIn("--receipts reads no scan path", stderr)
                self.assertEqual(stdout.strip(), "")

    def test_a_missing_root_is_refused_not_reported_absent(self):
        missing = self.home.parent / "no-such-dir"
        for args in (
            ["quality-evidence", "agent-skills", "--project-root", str(missing), "--user-home", str(self.home)],
            ["quality-evidence", "agent-skills", "--project-root", str(self.project), "--user-home", str(missing)],
        ):
            with self.subTest(args=args):
                status, stdout, stderr = self.run_patched(args)
                self.assertEqual(status, 2)
                self.assertIn("is not a directory", stderr)
                self.assertEqual(stdout.strip(), "")
        self.assertFalse(missing.exists())

    def test_a_stored_unreadable_row_is_not_an_unread_path_of_this_run(self):
        status, stdout, stderr = self.run_patched(self.args())
        self.assertEqual(status, 0, stderr)
        payload = json.loads(stdout)
        receipt = next(r for r in payload["receipts"] if (r["host"], r["scope"]) == ("claude", "repo"))
        receipt["stages"][0].update(outcome="hold", reason="unreadable", detail="scan path unreadable at .claude/skills")
        saved = self.home.parent / "unreadable.json"
        saved.write_text(json.dumps(payload), encoding="utf-8", newline="")
        stored_status, stored_stdout, stored_stderr = self.run_patched(self.receipts_args(str(saved)))
        self.assertEqual(stored_status, 0, stored_stderr)
        stored = json.loads(stored_stdout)
        self.assertEqual(row(stored, "claude", "repo")["installed_reason"], "unreadable")
        self.assertEqual(stored["unread_scan_paths"], [])

    @requires_posix_permissions
    def test_an_unreadable_scan_path_exits_three_with_the_matrix_printed(self):
        skills = self.project / ".claude/skills"
        install_agent_skills(skills)
        skills.chmod(0)
        self.addCleanup(skills.chmod, 0o755)
        status, stdout, stderr = self.run_patched(self.args())
        self.assertEqual(status, 3, stderr)
        payload = json.loads(stdout)
        self.assertEqual(payload["unread_scan_paths"], [{"host": "claude", "scope": "repo"}])
        self.assertEqual(row(payload, "claude", "repo")["installed_reason"], "unreadable")

    def test_a_tampered_or_missing_receipts_file_is_an_error_not_a_matrix(self):
        status, stdout, _ = self.run_patched(self.args())
        payload = json.loads(stdout)
        payload["receipts"][0]["stages"][1]["outcome"] = "observed"
        tampered = self.home.parent / "tampered.json"
        tampered.write_text(json.dumps(payload), encoding="utf-8", newline="")

        bad_status, bad_stdout, bad_stderr = self.run_patched(self.receipts_args(str(tampered)))
        gone_status, gone_stdout, gone_stderr = self.run_patched(self.receipts_args(str(self.home / "nope.json")))

        self.assertEqual(bad_status, 2)
        self.assertIn("cannot be observed without a probe that observes it", bad_stderr)
        self.assertEqual(bad_stdout.strip(), "")
        self.assertEqual(gone_status, 2)
        self.assertIn("Agent Skills host evidence failed", gone_stderr)
        self.assertEqual(gone_stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
