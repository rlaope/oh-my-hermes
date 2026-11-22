"""Session receipts and same-session repair for user-declared executors.

A person declares a headless CLI plus a `session` block:

```toml
[executors.my-agent.session]
export = ["--export", "{session_file}"]
resume = ["-r", "{session_id}"]
```

The dispatcher gives the CLI one export file inside this attempt's private
scratch, then records `fanout_executor_session/v2`: the file's name and SHA-256
and, only when the root `session_id` is canonical, that id. The transcript body
is never read into a record and never lands under `.omh`. A budgeted repair
re-enters that same session only when the immediately preceding receipt still
binds this attempt lineage; otherwise it starts fresh and records why.

No vendor CLI is installed: every executor here is a small script on a
temporary PATH.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from _local_package import load_local_package

load_local_package()

from omh.coding import fanout_executor_sessions as sessions  # noqa: E402
from omh.coding.fanout import build_fanout_contract  # noqa: E402
from omh.coding.fanout_artifacts import write_fanout_contract  # noqa: E402
from omh.coding.fanout_dispatch import build_dispatch_argv, build_user_executor_argv, dispatch_fanout  # noqa: E402
from omh.coding.user_executors import load_user_executors  # noqa: E402
from omh.system.paths import OmhPaths  # noqa: E402

_GOAL = "hand one bounded unit to a user-declared executor"
SID = "12345678-1234-4234-8234-123456789abc"
DEVIN_SID = "devin-" + "a" * 32
OTHER = "12345678-1234-4234-8234-123456789abd"
ATTEMPT = "22345678-1234-4234-8234-123456789abc"
SHA = "a" * 40
CONTRACT = "c" * 64
# The body of the export. It must never appear in anything the dispatcher keeps.
SENTINEL = "TRANSCRIPT_BODY_SENTINEL_NEVER_PERSIST"

# A fake harness CLI. `--version` answers; `run ... prompt` writes an export
# file when it was given one, commits, and returns the unit result contract.
_FAKE_SESSION_CLI = '''#!{python}
import json
import os
import pathlib
import re
import subprocess
import sys

MODE = {mode!r}
SID = {sid!r}
SENTINEL = {sentinel!r}
TRANSCRIPT = {{"session_id": SID, "transcript": SENTINEL,
              "turns": [{{"role": "user", "text": SENTINEL}}]}}
args = sys.argv[1:]
if args[:1] == ["--version"]:
    print("fake-agent 2.3.4")
    raise SystemExit(0)
prompt = args[-1]
export = pathlib.Path(args[args.index("--export") + 1]) if "--export" in args else None
resumed = "-r" in args
if export is not None:
    if MODE == "garbled":
        export.write_text("{{not json", encoding="utf-8")
    elif MODE == "no-id":
        export.write_text(json.dumps({{"transcript": SENTINEL}}), encoding="utf-8")
    elif MODE == "no-export":
        pass
    else:
        export.write_text(json.dumps(TRANSCRIPT), encoding="utf-8")
if MODE == "backup" and export is not None:
    export.with_suffix(".json.bak").write_text("fixture backup", encoding="utf-8")
if MODE == "tracked" and export is not None:
    note = export.parent / "fixture.note"
    note.write_text("ordinary test data", encoding="utf-8")
    subprocess.run(["git", "add", "-f", str(note)], check=True)
if MODE == "untracked-again":
    subprocess.run(["git", "add", "-f", str(export)], check=True)
    subprocess.run(["git", "-c", "user.name=fake-agent", "-c", "user.email=fake@example.test",
                    "commit", "-qm", "intermediate export"], check=True)
    subprocess.run(["git", "rm", "--cached", str(export)], check=True)
marker = "resumed" if resumed else "first"
# One file per attempt, numbered from what earlier attempts already committed,
# so the test can read every attempt's argv out of the worktree history.
index = len(list(pathlib.Path(".").glob("argv-*.txt"))) + 1
argv_name = "argv-%d.txt" % index
pathlib.Path(argv_name).write_text(
    json.dumps([part if part != prompt else "<prompt>" for part in args]), encoding="utf-8")
pathlib.Path("agent_output.txt").write_text("attempt " + marker + "\\n", encoding="utf-8")
changed = [argv_name, "agent_output.txt"]
# "repair" fixes on the first resumed attempt; "repair2" only on the second.
if resumed and (MODE == "repair" or (MODE == "repair2" and index >= 3)):
    pathlib.Path("repair_done.txt").write_text("fixed\\n", encoding="utf-8")
    changed.append("repair_done.txt")
subprocess.run(["git", "add", *changed], check=True)
subprocess.run(
    ["git", "-c", "user.name=fake-agent", "-c", "user.email=fake@example.test",
     "commit", "-q", "-m", "agent: " + marker],
    check=True,
)
fanout, unit = os.environ["OMH_FANOUT_LINEAGE"].rsplit("/", 1)[-1].split(":")
if prompt.endswith("/prompt.txt"):
    prompt = pathlib.Path(prompt).read_text(encoding="utf-8")
base = re.search(r"base_sha=([0-9a-f]{{40,64}})", prompt).group(1)
head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                      check=True).stdout.strip()
payload = {{"schema_version": "fanout_unit_result/v1", "unit_id": unit,
            "run_id": fanout + "-" + unit, "fanout_id": fanout,
            "base_sha": base, "head_sha": head, "process_status": "process_succeeded",
            "changed_paths": [], "checks": [], "findings": []}}
print("```json\\n" + json.dumps(payload) + "\\n```")
raise SystemExit(0)
'''

_CHECK_REPAIR = '''import pathlib
import sys

raise SystemExit(0 if pathlib.Path("repair_done.txt").exists() else 1)
'''


def _git(repo: Path, *argv: str) -> str:
    completed = subprocess.run(
        ["git", *argv], cwd=str(repo), check=True, capture_output=True, text=True
    )
    return completed.stdout.strip()


def _make_repo(root: Path) -> tuple[Path, str]:
    repo = root / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    (repo / "check_repair.py").write_text(_CHECK_REPAIR, encoding="utf-8")
    _git(repo, "add", "seed.txt", "check_repair.py")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init")
    return repo, _git(repo, "rev-parse", "HEAD")


def _bin_dir(root: Path, name: str, mode: str) -> Path:
    directory = root / f"bin-{name}"
    directory.mkdir()
    script = directory / name
    script.write_text(
        _FAKE_SESSION_CLI.format(
            python=sys.executable, mode=mode, sid=SID, sentinel=SENTINEL,
        ),
        encoding="utf-8",
    )
    script.chmod(0o755)
    return directory


def _home(root: Path, executor_id: str = "my-agent", *, resume: bool = True) -> OmhPaths:
    home = root / ".omh"
    routing = home / "routing"
    routing.mkdir(parents=True)
    lines = [
        "schema_version = 1",
        "",
        f"[executors.{executor_id}]",
        f'label = "{executor_id} fake"',
        f'argv = ["{executor_id}", "run", "--", "{{prompt}}"]',
        f'version = ["{executor_id}", "--version"]',
        "",
        f"[executors.{executor_id}.session]",
        'export = ["--export", "{session_file}"]',
    ]
    if resume:
        lines.append('resume = ["-r", "{session_id}"]')
    lines.append("")
    (routing / "executors.toml").write_text("\n".join(lines), encoding="utf-8")
    return OmhPaths(omh_home=home, hermes_home=root / ".hermes")


def _unit(owner: str = "my-agent", *, repair: bool = False,
          repair_budget: int = 1) -> dict[str, object]:
    unit: dict[str, object] = {
        "unit_id": "core",
        "title": "Core work",
        "owner": owner,
        "file_scope": ["src/"],
    }
    if repair:
        unit["verification_commands"] = [f"{sys.executable} check_repair.py"]
        unit["max_repair_attempts"] = repair_budget
    return unit


def _dispatch(
    root: Path, *, mode: str, repair: bool = False, resume: bool = True,
    dry_run: bool = False, repair_budget: int = 1, environment: dict[str, str] | None = None,
    file_prompt: bool = False,
):
    binaries = _bin_dir(root, "my-agent", mode)
    paths = _home(root, resume=resume)
    if file_prompt:
        config = paths.omh_home / "routing" / "executors.toml"
        config.write_text(config.read_text().replace("{prompt}", "{prompt_file}"))
    repo, sha = _make_repo(root)
    registry = load_user_executors(paths.omh_home)
    contract = write_fanout_contract(
        paths, build_fanout_contract(
            _GOAL, [_unit(repair=repair, repair_budget=repair_budget)], registry=registry)
    )
    env = {
        **(environment or os.environ),
        "PATH": f"{binaries}{os.pathsep}{os.environ.get('PATH', '')}",
    }
    with mock.patch.dict(os.environ, env):
        summary = dispatch_fanout(
            paths, contract, goal_text=_GOAL, repo_root=repo, base_sha=sha, env=env,
            run_verification=repair, dry_run=dry_run,
        )
    return paths, repo, sha, summary


def _worktree(repo: Path) -> Path:
    return repo.parent / "repo-fanout-core"


def _attempt_argv(worktree: Path, index: int) -> list[str]:
    """The argv one attempt recorded in its own committed file."""
    return json.loads(_git(worktree, "show", f"HEAD:argv-{index}.txt"))


class FileExportReceiptTests(unittest.TestCase):
    """The v2 record: a digest and an optional canonical id, never the body."""

    def capability(self, executor: str = "my-agent") -> object:
        return sessions.SessionCapability(
            executor, sessions.FILE_EXPORT_PROTOCOL,
            sessions.BinaryIdentity("/opt/tools/my-agent", "b" * 64), None)

    def binding(self) -> object:
        return sessions.SessionBinding(
            "fo-1", "unit-a", "fanout-0123456789ab-unit-a", ATTEMPT, CONTRACT,
            "/work/unit-a",
            sessions.WorktreeIncarnation(OTHER, "/repo/.git", "refs/heads/agent/a", 1, 200),
            SHA, SHA)

    def receipt(self, document: dict[str, object]):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / sessions.FILE_EXPORT_REF
            path.write_text(json.dumps(document), encoding="utf-8")
            observation = sessions.observe_session_export(path)
            expected = sessions.sha256(path.read_bytes()).hexdigest()
        return sessions.build_file_export_receipt(
            capability=self.capability(), binding=self.binding(), observation=observation,
            end_head=SHA, resume_reason="not_a_repair",
        ), expected

    @unittest.skipUnless(os.name == "posix", "external executor lane is POSIX only")
    def test_a_canonical_id_round_trips_with_its_digest_and_no_body(self):
        receipt, digest = self.receipt({"session_id": SID, "transcript": SENTINEL})
        record = receipt.to_dict()
        self.assertEqual(record["schema_version"], "fanout_executor_session/v2")
        self.assertEqual(record["protocol"], "user_export_json")
        self.assertEqual(record["state"], "observed")
        self.assertEqual(record["reference_kind"], "session_id")
        self.assertEqual(record["reference"], SID)
        self.assertEqual(record["export_ref"], "session.json")
        self.assertEqual(record["export_sha256"], digest)
        self.assertNotIn("event_ref", record)
        # The whole record is metadata: the transcript body never appears.
        self.assertNotIn(SENTINEL, json.dumps(record))
        read = sessions.read_session_receipt(record)
        self.assertIsNotNone(read.receipt, read.reason)
        self.assertEqual(read.receipt.to_dict(), record)

    @unittest.skipUnless(os.name == "posix", "external executor lane is POSIX only")
    def test_a_valid_file_without_an_id_is_file_only_evidence(self):
        receipt, digest = self.receipt({"transcript": SENTINEL})
        record = receipt.to_dict()
        self.assertEqual((record["state"], record["reason"]), ("observed", "export_digest_observed"))
        self.assertEqual(record["reference_kind"], "export_file")
        self.assertIsNone(record["reference"])
        self.assertEqual(record["export_sha256"], digest)

    @unittest.skipUnless(os.name == "posix", "external executor lane is POSIX only")
    def test_the_devin_id_shape_is_accepted_and_an_uppercase_uuid_is_not(self):
        receipt, _digest = self.receipt({"session_id": DEVIN_SID})
        self.assertEqual(receipt.to_dict()["reference"], DEVIN_SID)
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / sessions.FILE_EXPORT_REF
            path.write_text(json.dumps({"session_id": SID.upper()}), encoding="utf-8")
            observation = sessions.observe_session_export(path)
        self.assertEqual((observation.state, observation.reason),
                         ("not_observed", "export_invalid_id"))
        self.assertIsNone(observation.reference)
        self.assertIsNone(observation.export_sha256)

    @unittest.skipUnless(os.name == "posix", "external executor lane is POSIX only")
    def test_broken_exports_are_not_observed_with_closed_reasons(self):
        cases = {
            "export_missing": None,
            "export_invalid_json": "{not json",
            "export_not_object": '["a"]',
            "export_duplicate_keys": '{"session_id": "%s", "session_id": "%s"}' % (SID, OTHER),
            "export_invalid_utf8": b"\xff\xfe",
            "export_too_deep": '{"a": ' + "[" * 40 + "]" * 40 + "}",
        }
        for reason, payload in cases.items():
            with self.subTest(reason=reason), TemporaryDirectory() as tmp:
                path = Path(tmp) / sessions.FILE_EXPORT_REF
                if isinstance(payload, bytes):
                    path.write_bytes(payload)
                elif payload is not None:
                    path.write_text(payload, encoding="utf-8")
                observation = sessions.observe_session_export(path)
                self.assertEqual(observation.state, "not_observed")
                self.assertEqual(observation.reason, reason)
                self.assertIsNone(observation.reference)
                self.assertIsNone(observation.export_sha256)

    @unittest.skipUnless(os.name == "posix", "external executor lane is POSIX only")
    def test_an_oversized_or_symlinked_file_is_not_a_session(self):
        with TemporaryDirectory() as tmp:
            directory = Path(tmp)
            big = directory / sessions.FILE_EXPORT_REF
            big.write_bytes(b"{" + b" " * (sessions.MAX_EXPORT_BYTES + 8) + b"}")
            self.assertEqual(sessions.observe_session_export(big).reason, "export_oversized")
            target = directory / "real.json"
            target.write_text(json.dumps({"session_id": SID}), encoding="utf-8")
            link = directory / "link.json"
            if not hasattr(os, "symlink"):
                self.skipTest("no symlinks here")
            os.symlink(target, link)
            self.assertEqual(sessions.observe_session_export(link).reason, "export_unsafe")

    @unittest.skipUnless(os.name == "posix", "external executor lane is POSIX only")
    def test_cleanup_uses_the_original_directory_handle_after_rename(self):
        from omh.coding.fanout_dispatch import _prepare_executor_scratch, _remove_executor_scratch

        with TemporaryDirectory() as tmp:
            work = Path(tmp)
            handle = _prepare_executor_scratch(work, ATTEMPT, "test prompt")
            self.assertIsNotNone(handle)
            directory = work / f".omh-executor-tmp-{ATTEMPT}"
            old = work / "original"
            empty = work / "empty"
            empty.mkdir()
            directory.rename(old)
            directory.symlink_to(empty, target_is_directory=True)
            _remove_executor_scratch(handle)
            self.assertEqual(list(old.iterdir()), [])
            self.assertTrue(directory.is_symlink())
            self.assertEqual(list(empty.iterdir()), [])

    @unittest.skipUnless(os.name == "posix", "external executor lane is POSIX only")
    def test_export_refuses_a_linked_scratch_directory_without_opening_its_files(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            empty = root / "empty"
            empty.mkdir()
            directory = root / "scratch"
            directory.symlink_to(empty, target_is_directory=True)
            observed = sessions.observe_session_export(directory / sessions.FILE_EXPORT_REF)
            self.assertEqual((observed.state, observed.reason), ("not_observed", "export_unsafe"))

    def observed_receipt(self):
        # Projection and decoding only need the observation, not a POSIX file reader.
        observation = sessions.SessionExportObservation(
            "observed", sessions.FILE_EXPORT_OBSERVED_REASON, sessions.FILE_EXPORT_REF, "a" * 64, SID)
        return sessions.build_file_export_receipt(capability=self.capability(), binding=self.binding(),
                                                 observation=observation, end_head=SHA, resume_reason="same_session")

    def test_a_file_export_receipt_is_repair_only_and_renders_no_command(self):
        receipt = self.observed_receipt()
        projection = sessions.project_session_resume(
            receipt.to_dict(), binding=receipt.binding,
            workspace=sessions.WorkspaceSnapshot(
                receipt.binding.worktree_path, receipt.binding.worktree_incarnation, SHA, False, None),
            platform="posix",
        )
        self.assertFalse(projection["available"])
        self.assertEqual(projection["reason"], "repair_only")
        self.assertEqual(projection["argv"], [])
        self.assertIsNone(projection["cwd"])

    def test_a_not_observed_receipt_carries_no_reference_or_digest(self):
        with TemporaryDirectory() as tmp:
            observation = sessions.observe_session_export(Path(tmp) / sessions.FILE_EXPORT_REF)
            receipt = sessions.build_file_export_receipt(
                capability=self.capability(), binding=self.binding(), observation=observation,
                end_head=None, resume_reason="no_id")
        record = receipt.to_dict()
        self.assertEqual(record["state"], "not_observed")
        self.assertIsNone(record["reference"])
        self.assertIsNone(record["reference_kind"])
        self.assertIsNone(record["export_sha256"])
        self.assertIsNotNone(sessions.read_session_receipt(record).receipt)

    def test_a_malformed_v2_record_is_rejected_rather_than_upgraded(self):
        record = self.observed_receipt().to_dict()
        for broken in (
            {**record, "reference": OTHER, "reference_kind": "export_file"},
            {**record, "resume_reason": "made-up"},
            {**record, "export_ref": "../escape.json"},
            {key: value for key, value in record.items() if key != "export_sha256"},
        ):
            self.assertIsNone(sessions.read_session_receipt(broken).receipt)

    def test_v1_native_bytes_are_unchanged(self):
        capability = sessions.SessionCapability(
            "codex", "codex_exec_json",
            sessions.BinaryIdentity("/opt/codex", "b" * 64), "1.2.3")
        decoder = sessions.SessionDecoder(capability)
        decoder.observe({"type": "thread.started", "thread_id": SID}, event_ref="stdout:1")
        record = decoder.receipt(self.binding(), end_head=SHA).to_dict()
        self.assertEqual(record, {
            "schema_version": "fanout_executor_session/v1",
            "state": "observed", "reason": "native_event_observed",
            "executor": "codex", "protocol": "codex_exec_json",
            "reference_kind": "thread_id", "reference": SID, "event_ref": "stdout:1",
            "fanout_id": "fo-1", "unit_id": "unit-a", "run_ref": "fanout-0123456789ab-unit-a",
            "attempt_id": ATTEMPT, "contract_digest": CONTRACT,
            "worktree_path": "/work/unit-a",
            "worktree_incarnation": {
                "incarnation_id": OTHER, "common_dir": "/repo/.git",
                "branch": "refs/heads/agent/a", "device": 1, "inode": 200},
            "base_sha": SHA, "launch_head": SHA, "end_head": SHA,
            "binary_identity": {"resolved_path": "/opt/codex", "sha256": "b" * 64},
            "version": "1.2.3", "predecessor_attempt_id": None,
        })
        self.assertEqual(sessions.read_session_receipt(record).receipt.to_dict(), record)


class BuiltinSessionPins(unittest.TestCase):
    """Export/resume arguments never reach a shipped template."""

    PROMPT = "P"

    def test_builtin_argv_is_unchanged_when_session_arguments_are_supplied(self):
        # The built-in builder takes no session arguments at all, and the
        # user-executor builder never renders a built-in owner.
        self.assertIsNone(build_user_executor_argv(
            "codex", self.PROMPT, session_file=Path("/tmp/session.json"), session_id=SID, spec=None,
        ))
        codex = build_dispatch_argv(
            "codex", self.PROMPT,
            {"selected_model": "gpt-5.1-codex", "selected_reasoning_effort": "high"},
        )
        self.assertEqual(codex, [
            "codex", "exec", "--model", "gpt-5.1-codex",
            "--config", "model_reasoning_effort=high", self.PROMPT,
        ])
        claude = build_dispatch_argv("claude-code", self.PROMPT)
        self.assertEqual(claude, [
            "claude", "-p", self.PROMPT, "--permission-mode", "acceptEdits",
            "--allowedTools", "Bash(git add:*),Bash(git commit:*)",
        ])
        self.assertEqual([part.encode("utf-8") for part in claude], [
            b"claude", b"-p", b"P", b"--permission-mode", b"acceptEdits",
            b"--allowedTools", b"Bash(git add:*),Bash(git commit:*)",
        ])


@unittest.skipUnless(os.name == "posix", "external executor lane is POSIX only")
class SessionDispatchTests(unittest.TestCase):
    """Real spawns of a fake CLI that writes its export file."""

    def test_an_export_file_becomes_an_observed_receipt_and_leaves_no_body(self):
        expected = json.dumps(
            {"session_id": SID, "transcript": SENTINEL,
             "turns": [{"role": "user", "text": SENTINEL}]}
        ).encode("utf-8")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths, repo, sha, summary = _dispatch(root, mode="session")
            unit = summary["units"][0]
            worktree = _worktree(repo)
            head = _git(worktree, "rev-parse", "HEAD")
            leftovers = list(worktree.glob(".omh-executor-tmp-*"))
            persisted = {
                str(path.relative_to(paths.omh_home)): path.read_bytes()
                for path in paths.omh_home.rglob("*") if path.is_file()
            }
        self.assertEqual(unit["status"], "completed", unit)
        receipt = unit["executor_session"]
        self.assertEqual(receipt["schema_version"], "fanout_executor_session/v2")
        self.assertEqual(receipt["state"], "observed")
        self.assertEqual(receipt["reference_kind"], "session_id")
        self.assertEqual(receipt["reference"], SID)
        self.assertEqual(receipt["export_ref"], "session.json")
        self.assertEqual(receipt["export_sha256"], sessions.sha256(expected).hexdigest())
        self.assertEqual(receipt["attempt_id"], unit["attempt_id"])
        self.assertEqual(receipt["worktree_path"], str(worktree.resolve()))
        self.assertEqual(receipt["end_head"], head)
        self.assertEqual(receipt["resume_reason"], "not_a_repair")
        # The body was read for its hash and nothing else: it is in no durable
        # artifact under the OMH home and the scratch dir is gone.
        for name, content in persisted.items():
            self.assertNotIn(SENTINEL.encode("utf-8"), content, name)
        self.assertEqual(leftovers, [])
        self.assertFalse((worktree / "session.json").exists())

    def test_a_missing_or_garbled_export_is_not_observed_with_a_reason(self):
        cases = {"no-export": "export_missing", "garbled": "export_invalid_json"}
        for mode, reason in cases.items():
            with self.subTest(mode=mode), TemporaryDirectory() as tmp:
                _paths, _repo, _sha, summary = _dispatch(Path(tmp), mode=mode)
                unit = summary["units"][0]
            receipt = unit["executor_session"]
            self.assertEqual(unit["status"], "completed", unit)
            self.assertEqual(receipt["state"], "not_observed", receipt)
            self.assertEqual(receipt["reason"], reason)
            self.assertIsNone(receipt["reference"])
            self.assertIsNone(receipt["export_sha256"])

    def test_a_file_without_an_id_is_hash_only(self):
        with TemporaryDirectory() as tmp:
            _paths, _repo, _sha, summary = _dispatch(Path(tmp), mode="no-id")
            receipt = summary["units"][0]["executor_session"]
        self.assertEqual(receipt["state"], "observed")
        self.assertEqual(receipt["reference_kind"], "export_file")
        self.assertIsNone(receipt["reference"])
        self.assertEqual(len(receipt["export_sha256"]), 64)

    def test_cleanup_removes_unanticipated_backup(self):
        with TemporaryDirectory() as tmp:
            _, repo, _, summary = _dispatch(Path(tmp), mode="backup")
            self.assertEqual(summary["units"][0]["status"], "completed")
            self.assertEqual(list(_worktree(repo).glob(".omh-executor-tmp-*")), [])

    def test_intermediate_scratch_commit_fails_the_unit(self):
        self.check_scratch_refusal("untracked-again")

    def test_committed_scratch_entry_fails_the_unit(self):
        self.check_scratch_refusal("tracked")

    def check_scratch_refusal(self, mode):
        with TemporaryDirectory() as tmp:
            paths, _, _, summary = _dispatch(Path(tmp), mode=mode)
            unit = summary["units"][0]
            self.assertEqual(unit.get("reason_code"), "executor_scratch_committed")
            self.assertEqual(unit["status"], "failed")
            self.assertFalse(unit["integration_ready"])
            self.assertEqual(unit.get("executor_session_status"), "observed")
            receipt = unit["executor_session"]
            self.assertEqual(receipt["state"], "observed")
            self.assertEqual(receipt["reference"], SID)
            self.assertEqual(receipt["attempt_id"], unit["attempt_id"])
            observations = [json.loads(line) for line in paths.runtime_journal_events_path.read_text().splitlines()]
            self.assertIn(receipt, [event["executor_session"] for event in observations
                                    if event.get("event") == "executor_session_observed"])

    def test_file_prompt_repair_observes_export_and_resumes(self):
        with TemporaryDirectory() as tmp:
            _paths, repo, _sha, summary = _dispatch(Path(tmp), mode="repair", repair=True, file_prompt=True)
            unit = summary["units"][0]
            self.assertEqual(unit.get("executor_session", {}).get("state"), "observed")
            self.assertEqual(unit["executor_session"]["resume_reason"], "same_session")
            argv = _attempt_argv(_worktree(repo), 2)
            self.assertEqual(argv[argv.index("-r") + 1], SID)
            self.assertEqual(unit["status"], "completed")

    def test_a_repair_resumes_the_observed_id_in_the_same_worktree(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths, repo, sha, summary = _dispatch(root, mode="repair", repair=True)
            unit = summary["units"][0]
            worktree = _worktree(repo)
            first = _attempt_argv(worktree, 1)
            second = _attempt_argv(worktree, 2)
            journal = paths.runtime_journal_events_path.read_text(encoding="utf-8")
        self.assertEqual(unit["status"], "completed", unit)
        self.assertEqual(unit["unit_state"], "verified", unit)
        # First attempt exports; it was never asked to resume.
        self.assertIn("--export", first)
        self.assertNotIn("-r", first)
        # The repair re-enters the SAME session, in the same worktree, with the
        # dispatcher-assigned export for ITS OWN attempt.
        self.assertIn("-r", second)
        self.assertEqual(second[second.index("-r") + 1], SID)
        self.assertIn("--export", second)
        self.assertNotEqual(first[first.index("--export") + 1],
                            second[second.index("--export") + 1])
        self.assertIn(".omh-executor-tmp-", second[second.index("--export") + 1])
        receipts = [json.loads(line)["executor_session"] for line in journal.splitlines()
                    if '"executor_session"' in line]
        self.assertGreaterEqual(len(receipts), 2, receipts)
        first_receipt, repaired = receipts[-2], receipts[-1]
        self.assertEqual(first_receipt["reference"], SID)
        self.assertEqual(repaired["reference"], SID)
        self.assertEqual(repaired["resume_reason"], "same_session")
        self.assertEqual(repaired["predecessor_attempt_id"], first_receipt["attempt_id"])
        self.assertNotEqual(repaired["attempt_id"], first_receipt["attempt_id"])
        self.assertNotEqual(repaired["export_sha256"], "")
        self.assertEqual(repaired["worktree_path"], first_receipt["worktree_path"])
        self.assertEqual(repaired["worktree_incarnation"], first_receipt["worktree_incarnation"])
        self.assertNotIn(SENTINEL, journal)

    def test_a_second_repair_stays_on_the_same_single_predecessor_chain(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths, repo, _sha, summary = _dispatch(
                root, mode="repair2", repair=True, repair_budget=2)
            unit = summary["units"][0]
            worktree = _worktree(repo)
            attempts = [_attempt_argv(worktree, index) for index in (1, 2, 3)]
            journal = paths.runtime_journal_events_path.read_text(encoding="utf-8")
        self.assertEqual(unit["unit_state"], "verified", unit)
        self.assertNotIn("-r", attempts[0])
        for later in attempts[1:]:
            self.assertEqual(later[later.index("-r") + 1], SID)
        receipts = [json.loads(line)["executor_session"] for line in journal.splitlines()
                    if '"executor_session"' in line]
        chain = receipts[-3:]
        self.assertEqual([receipt["reference"] for receipt in chain], [SID, SID, SID])
        self.assertEqual([receipt["resume_reason"] for receipt in chain],
                         ["not_a_repair", "same_session", "same_session"])
        self.assertEqual(chain[2]["predecessor_attempt_id"], chain[1]["attempt_id"])
        self.assertEqual(chain[1]["predecessor_attempt_id"], chain[0]["attempt_id"])

    def test_a_repair_without_a_declared_resume_starts_fresh_and_says_so(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _paths, repo, _sha, summary = _dispatch(root, mode="repair", repair=True, resume=False)
            unit = summary["units"][0]
            worktree = _worktree(repo)
            second = _attempt_argv(worktree, 2)
        self.assertEqual(unit["status"], "completed", unit)
        self.assertNotIn("-r", second)
        self.assertEqual(unit["executor_session"]["resume_reason"], "no_resume_declared")
        self.assertEqual(unit["executor_session"]["reference"], SID)


class SessionPlanTests(unittest.TestCase):
    @mock.patch("omh.coding.user_executors.USER_EXECUTOR_LAUNCH_SUPPORTED", True)
    def test_a_dry_run_plans_the_export_flag_and_launches_nothing(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _paths, repo, _sha, summary = _dispatch(root, mode="session", dry_run=True)
            unit = summary["units"][0]
            allocated = _worktree(repo).exists()
        self.assertEqual(unit["status"], "dry_run_planned", unit)
        self.assertIn("<session export>", unit["planned_argv"])
        self.assertFalse(allocated, "a plan must not allocate or spawn the executor")


if __name__ == "__main__":
    unittest.main()
