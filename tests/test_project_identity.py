"""Offline repository identity contract, exercised through real recall surfaces."""
from __future__ import annotations

from dataclasses import asdict
from contextlib import chdir
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from _local_package import load_local_package

load_local_package()


def repository(root: Path, remote: str | None = "git@EXAMPLE.test:team/project.git") -> Path:
    (root / ".git").mkdir(parents=True)
    (root / ".git" / "config").write_text(
        f'[remote "origin"]\n url = {remote}\n' if remote else "[core]\n bare = false\n", encoding="utf-8")
    return root


class ProjectIdentityTests(unittest.TestCase):
    _root: Path | None = None

    @property
    def api(self):
        from omh.plugin_bundle.omh import project_identity
        return project_identity

    @property
    def root(self) -> Path:
        assert self._root is not None
        return self._root

    def setUp(self):
        self._root = Path(self.enterContext(TemporaryDirectory()))

    def test_same_basename_and_fork_are_distinct_without_cross_recall(self):
        from omh.paths import resolve_paths
        from omh.workflows import memory
        from omh.plugin_bundle.omh.memory_provider import OmhMemoryProvider
        a = repository(self.root / "one" / "repo")
        b = repository(self.root / "two" / "repo", "https://example.test/fork/project.git")
        self.assertNotEqual(self.api.resolve_project_identity(a).identity, self.api.resolve_project_identity(b).identity)
        paths = resolve_paths(a / ".omh", self.root / "hermes")
        candidate = memory.capture_project_memory_candidate(paths, "first repository sentinel", retention_class="durable")["candidate"]
        assert isinstance(candidate, dict)
        record = memory.approve_project_memory_candidate(paths, candidate["candidate_id"])["record"]
        assert isinstance(record, dict)
        live = OmhMemoryProvider(paths.omh_home)
        live.initialize("s", platform="cli", cwd=b)
        self.assertNotIn(record["record_id"], live.prefetch("sentinel"))
        live.initialize("s", platform="cli", cwd=a)
        self.assertIn(record["record_id"], live.prefetch("sentinel"))
        self.assertEqual(candidate["scope"]["ref"], self.api.resolve_project_identity(a).identity)

    def test_local_remotes_are_anchored_and_cannot_cross_recall(self):
        from omh.paths import resolve_paths
        from omh.workflows import memory
        from omh.plugin_bundle.omh.memory_provider import OmhMemoryProvider
        a = repository(self.root / "one" / "repo", "../upstream.git")
        b = repository(self.root / "two" / "repo", "../upstream.git")
        for repo in (a, b):
            (repo.parent / "upstream.git").mkdir()
        first = self.api.resolve_project_identity(a)
        second = self.api.resolve_project_identity(b)
        self.assertEqual((first.state, second.state), ("resolved", "resolved"))
        paths = resolve_paths(self.root / "user", self.root / "hermes")
        candidate = memory.capture_project_memory_candidate(paths, "local remote sentinel", scope_ref=first.identity, retention_class="durable")["candidate"]
        assert isinstance(candidate, dict)
        record = memory.approve_project_memory_candidate(paths, candidate["candidate_id"])["record"]
        assert isinstance(record, dict)
        provider = OmhMemoryProvider(paths.omh_home)
        provider.initialize("local", platform="cli", cwd=b)
        self.assertNotIn(record["record_id"], provider.prefetch("sentinel"))
        self.assertNotEqual(first.identity, second.identity)
        provider.initialize("local", platform="cli", cwd=a)
        self.assertIn(record["record_id"], provider.prefetch("sentinel"))
        config = a / ".git" / "config"
        for remote in ((a.parent / "upstream.git").as_posix(), (a.parent / "upstream.git").as_uri()):
            config.write_text(f'[remote "origin"]\n url = {remote}\n', encoding="utf-8")
            self.assertEqual(self.api.resolve_project_identity(a).identity, first.identity)
        config.write_text('[remote "origin"]\n url = ../upstream.git\n', encoding="utf-8")
        gitdir = a / ".git" / "worktrees" / "local-linked"
        gitdir.mkdir(parents=True)
        (gitdir / "commondir").write_text("../..\n", encoding="utf-8")
        linked = self.root / "local-linked"
        linked.mkdir()
        (linked / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")
        self.assertEqual(self.api.resolve_project_identity(linked).identity, first.identity)
        renamed = a.with_name("renamed")
        a.rename(renamed)
        self.assertEqual(self.api.resolve_project_identity(renamed).identity, first.identity)
        config = renamed / ".git" / "config"
        config.write_text('[remote "origin"]\n url = ../missing.git\n', encoding="utf-8")
        missing = self.api.resolve_project_identity(renamed)
        self.assertEqual((missing.state, missing.identity), ("unresolved", ""))
        self.assertEqual(missing.diagnostics, ("git_metadata_unreadable",))

    def test_quoted_git_values_strip_credentials_and_inline_comments(self):
        repo = repository(self.root / "quoted")
        expected = "repo:" + hashlib.sha256(b"example.test/team/project").hexdigest()[:32]
        variants = ('"https://example.test/team/project.git"',
                    '"https://user:password@EXAMPLE.test/team/project.git" # origin',
                    '"https://other:rotated@EXAMPLE.test/team/project.git" ; rotated',
                    'https://example.test/team/project.git # origin',
                    '"git@example.test:team/project.git"')
        for value in variants:
            with self.subTest(value_digest=hashlib.sha256(value.encode()).hexdigest()):
                (repo / ".git" / "config").write_text(f'[remote "origin"]\n url = {value}\n', encoding="utf-8")
                resolution = self.api.resolve_project_identity(repo)
                self.assertEqual(resolution.identity, expected)
                for private in ("password", "rotated", "https", "example.test"):
                    self.assertNotIn(private, json.dumps(asdict(resolution)))
        (repo / ".git" / "config").write_text('[remote "origin"]\n url = "https://example.test/team/project.git\n', encoding="utf-8")
        self.assertEqual(self.api.resolve_project_identity(repo).state, "unresolved")

    def test_cli_uses_current_checkout_not_selected_store(self):
        from _cli_harness import run_cli
        from omh.paths import resolve_paths
        from omh.workflows import memory
        a = repository(self.root / "one" / "repo")
        b = repository(self.root / "two" / "repo", "https://example.test/other/project.git")
        paths = resolve_paths(a / ".omh", self.root / "hermes")
        candidate = memory.capture_project_memory_candidate(paths, "foreign store sentinel", retention_class="durable")["candidate"]
        assert isinstance(candidate, dict)
        memory.approve_project_memory_candidate(paths, candidate["candidate_id"])
        prefix = ["--omh-home", str(paths.omh_home), "--hermes-home", str(paths.hermes_home), "memory"]
        with chdir(b):
            status, stdout, stderr = run_cli(prefix + ["recall"])
            self.assertEqual(status, 0, stderr)
            self.assertEqual(json.loads(stdout)["included_records"], [])
            status, stdout, stderr = run_cli(prefix + ["project-identity", "show"])
            self.assertEqual(status, 0, stderr)
            self.assertEqual(json.loads(stdout)["identity"], self.api.resolve_project_identity(b).identity)
            status, stdout, stderr = run_cli(prefix + ["capture", "active checkout sentinel"])
            self.assertEqual(status, 0, stderr)
            self.assertEqual(json.loads(stdout)["candidate"]["scope"]["ref"], self.api.resolve_project_identity(b).identity)
            status, stdout, stderr = run_cli(prefix + ["recall", "--scope-kind", "project", "--scope-ref", self.api.resolve_project_identity(a).identity])
            self.assertEqual(status, 0, stderr)
            self.assertEqual(json.loads(stdout)["record_count"], 1)
        with chdir(self.root):
            status, stdout, stderr = run_cli(prefix + ["recall"])
            self.assertEqual(status, 0, stderr)
            self.assertEqual(json.loads(stdout)["included_records"], [])

    def test_incident_accepts_current_checkout_receipt_in_external_user_store(self):
        from omh.paths import resolve_paths
        from omh.workflows import memory
        from omh.workflows.memory_recall_incident import RecallIncidentRequest, build_memory_recall_incident
        from omh.plugin_bundle.omh.memory_provider import OmhMemoryProvider
        repo = repository(self.root / "active")
        identity = self.api.resolve_project_identity(repo).identity
        paths = resolve_paths(self.root / "external-user", self.root / "hermes")
        candidate = memory.capture_project_memory_candidate(paths, "external user sentinel", scope_ref=identity, retention_class="durable")["candidate"]
        assert isinstance(candidate, dict)
        record = memory.approve_project_memory_candidate(paths, candidate["candidate_id"])["record"]
        assert isinstance(record, dict)
        provider = OmhMemoryProvider(paths.omh_home)
        provider.initialize("external", platform="cli", cwd=repo)
        self.assertIn(record["record_id"], provider.prefetch("sentinel"))
        with chdir(repo):
            for reference in (identity, ""):
                incident = build_memory_recall_incident(paths, RecallIncidentRequest(record_id=record["record_id"], session_id="external", scope_ref=reference, observed="hermes"))
                self.assertEqual(incident["evidence_surfaces"]["live_prefetch_receipt"], {"status": "observed", "basis": "canonical_1452_receipt_bound"})
                self.assertEqual(incident["reason_code"], "rendered_delivery_not_observed")
        foreign = repository(self.root / "foreign", "https://example.test/foreign.git")
        with chdir(foreign):
            incident = build_memory_recall_incident(paths, RecallIncidentRequest(record_id=record["record_id"], session_id="external", scope_ref=identity))
            self.assertEqual(incident["evidence_surfaces"]["live_prefetch_receipt"]["basis"], "receipt_project_identity_mismatch")

    def test_rename_and_transport_normalization(self):
        a = repository(self.root / "before")
        identity = self.api.resolve_project_identity(a).identity
        a.rename(self.root / "after")
        a = self.root / "after"
        self.assertEqual(self.api.resolve_project_identity(a).identity, identity)
        (a / ".git" / "config").write_text('[remote "origin"]\n url = https://user:password@Example.test/team/project.git/\n', encoding="utf-8")
        result = self.api.resolve_project_identity(a)
        self.assertEqual(result.identity, identity)
        self.assertEqual(identity, "repo:" + hashlib.sha256(b"example.test/team/project").hexdigest()[:32])
        self.assertNotIn("password", json.dumps(asdict(result)))

    def test_worktree_common_directory(self):
        main = repository(self.root / "main")
        gitdir = main / ".git" / "worktrees" / "linked"
        gitdir.mkdir(parents=True)
        (gitdir / "commondir").write_text("../..\n", encoding="utf-8")
        linked = self.root / "linked"
        linked.mkdir()
        (linked / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")
        self.assertEqual(self.api.resolve_project_identity(main), self.api.resolve_project_identity(linked))

    def test_unresolved_closed_reasons(self):
        outside = self.api.resolve_project_identity(self.root)
        self.assertEqual(outside.diagnostics, ("outside_repository",))
        repo = repository(self.root / "repo", None)
        self.assertEqual(self.api.resolve_project_identity(repo).diagnostics, ("remote_absent",))
        (repo / ".git" / "config").write_text('[remote "a"]\n url = https://example.test/a\n[remote "b"]\n url = https://example.test/b\n', encoding="utf-8")
        result = self.api.resolve_project_identity(repo)
        self.assertEqual((result.state, result.identity, result.diagnostics), ("unresolved", "", ("remote_ambiguous",)))
        (repo / ".git" / "config").unlink()
        self.assertEqual(self.api.resolve_project_identity(repo).diagnostics, ("git_metadata_unreadable",))

    def test_explicit_priority_idempotency_permissions_and_invalid_file(self):
        repo = repository(self.root / "repo")
        identity = self.api.mint_explicit_project_identity(repo)
        self.assertRegex(identity, r"^prj:[0-9a-f]{64}$")
        path = repo / ".omh" / "project-identity.json"
        original = path.read_bytes()
        self.assertEqual(self.api.mint_explicit_project_identity(repo), identity)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(path.stat().st_mode & 0o777, 0o666 if os.name == "nt" else 0o600)
        result = self.api.resolve_project_identity(repo)
        self.assertEqual((result.state, result.evidence, result.identity), ("resolved", "explicit", identity))
        path.write_text('{"identity":"private/path"}', encoding="utf-8")
        result = self.api.resolve_project_identity(repo)
        self.assertEqual(result.diagnostics, ("explicit_invalid",))
        self.assertEqual(result.identity, "")
        with self.assertRaises(ValueError):
            self.api.mint_explicit_project_identity(repo)

    def test_resolution_never_writes_or_calls_external_services(self):
        repo = repository(self.root / "repo")
        with patch("subprocess.Popen", side_effect=AssertionError("subprocess")), patch("socket.socket", side_effect=AssertionError("network")), patch.object(Path, "write_text", side_effect=AssertionError("write")), patch("os.open", side_effect=AssertionError("write")):
            self.assertEqual(self.api.resolve_project_identity(repo).state, "resolved")

    def test_receipts_reject_identity_changes_and_legacy_requests_are_diagnosed(self):
        from omh.paths import resolve_paths
        from omh.workflows import memory
        from omh.workflows.memory_recall_incident import RecallIncidentRequest, build_memory_recall_incident
        from omh.plugin_bundle.omh.memory_provider import OmhMemoryProvider
        from omh.plugin_bundle.omh.memory_prefetch_receipt import validate_prefetch_receipt
        repo = repository(self.root / "repo")
        paths = resolve_paths(repo / ".omh", self.root / "hermes")
        candidate = memory.capture_project_memory_candidate(paths, "stable sentinel", retention_class="durable")["candidate"]
        assert isinstance(candidate, dict)
        record = memory.approve_project_memory_candidate(paths, candidate["candidate_id"])["record"]
        assert isinstance(record, dict)
        provider = OmhMemoryProvider(paths.omh_home)
        provider.initialize("s", platform="cli", cwd=repo)
        provider.prefetch()
        receipt = provider.latest_prefetch_receipt()
        assert receipt is not None
        self.assertEqual(validate_prefetch_receipt(receipt), [])
        legacy = build_memory_recall_incident(paths, RecallIncidentRequest(record_id=record["record_id"], session_id="s", scope_ref="repo"), invocation_cwd=repo)
        self.assertEqual(legacy["reason_code"], "legacy_basename")
        (repo / ".git" / "config").write_text('[remote "origin"]\n url = https://example.test/other\n', encoding="utf-8")
        incident = build_memory_recall_incident(paths, RecallIncidentRequest(record_id=record["record_id"], session_id="s", observed="hermes"), invocation_cwd=repo)
        self.assertEqual(incident["evidence_surfaces"]["live_prefetch_receipt"]["basis"], "receipt_project_identity_mismatch")
        provider.queue_prefetch()
        self.assertNotIn(record["record_id"], provider.prefetch())
        changed_receipt = provider.latest_prefetch_receipt()
        assert changed_receipt is not None
        self.assertNotEqual(changed_receipt["configuration_id"], receipt["configuration_id"])
        # Legacy schema remains structurally readable, but is not current evidence.
        body = {key: value for key, value in receipt.items() if key not in {"receipt_id", "state", "served_at"}}
        body["schema_version"] = "omh_memory_prefetch_receipt/v2"
        body.pop("resolver_version")
        body.pop("project_identity")
        legacy_receipt = {**body, "state": receipt["state"], "served_at": receipt["served_at"],
                          "receipt_id": hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()}
        self.assertEqual(validate_prefetch_receipt(legacy_receipt), [])

    def test_unresolved_capture_refuses_and_provider_receipt_is_bound(self):
        from omh.paths import resolve_paths
        from omh.workflows import memory
        from omh.plugin_bundle.omh.memory_provider import OmhMemoryProvider
        repo = repository(self.root / "repo", None)
        paths = resolve_paths(repo / ".omh", self.root / "hermes")
        with self.assertRaises(self.api.ProjectIdentityUnresolvedError):
            memory.capture_project_memory_candidate(paths, "must not silently widen")
        self.assertFalse(paths.memory_dir.exists())
        live = OmhMemoryProvider(paths.omh_home)
        live.initialize("s", platform="cli", cwd=repo)
        self.assertEqual(live.prefetch(), "")
        receipt = live.latest_prefetch_receipt()
        assert receipt is not None
        self.assertEqual(receipt["schema_version"], "omh_memory_prefetch_receipt/v3")
        self.assertEqual(receipt["resolver_version"], "project_identity/v2")
        self.assertEqual(receipt["project_identity"], "")
        self.assertEqual(receipt["lens"]["project_identity_state"], "unresolved")
        self.assertEqual(receipt["lens"]["project_identity_diagnostics"], ["remote_absent"])
        # A console with no resolved project reads user-global and its own
        # thread (owner decision 2026-10-13); no project label, so no project
        # record can widen into it.
        self.assertEqual(receipt["lens"]["scope_allowlist"], [{"kind": "thread", "ref": "s"}, {"kind": "user-global", "ref": "default"}])
        self.assertEqual(receipt["lens"]["scope_status"], "resolved")


if __name__ == "__main__":
    unittest.main()
