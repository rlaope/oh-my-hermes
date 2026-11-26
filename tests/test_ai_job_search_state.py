"""Explicit subprocess contract tests for the inert, standalone offline helper."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from _platform_support import requires_secure_dir_io


ROOT = Path(__file__).resolve().parents[1]
TOOLKIT = ROOT / "src/skills/ai_job_search_toolkit"
SCRIPT = TOOLKIT / "scripts/job_state.py"
SCRATCH = ROOT.parent


def capture():
    return {
        "schema": "ai_job_search_captures/v1",
        "jobs": [{
            "source_namespace": "careers.example.invalid", "posting_id": "REQ-101",
            "original_url": "https://careers.example.invalid/jobs?req=REQ-101&utm_source=demo#details",
            "canonical_url": "https://careers.example.invalid/jobs?req=REQ-101#details",
            "title": "Synthetic Library Coordinator", "company": "Synthetic Example Library",
            "location": "Synthetic City", "remote_scope": None, "posted_at": None,
            "deadline": None, "application_url": None, "availability": "unknown",
            "receipt_ids": ["synthetic-posting-1"],
        }],
        "sources": [{
            "receipt_id": "synthetic-posting-1", "kind": "user_provided", "source_url": None,
            "retrieved_at": "2026-10-23T02:00:00Z", "status": "ok", "freshness": "unverified",
            "evidence_ref": "captures/synthetic-posting-1.md", "error": None,
        }],
    }


class UnsupportedPlatformTests(unittest.TestCase):
    def test_missing_safe_io_primitives_refuse_before_paths_without_writes(self):
        runner = ("import os, runpy, sys\n"
                  "primitive = sys.argv.pop(1)\n"
                  "if primitive == 'dir_fd': os.supports_dir_fd = set()\n"
                  "else: setattr(os, primitive, 0)\n"
                  "sys.argv = sys.argv[1:]\n"
                  "runpy.run_path(sys.argv[0], run_name='__main__')\n")
        with tempfile.TemporaryDirectory(dir=SCRATCH) as temporary:
            root = Path(temporary)
            for key in ('home', 'tmp', 'hermes', 'omh'):
                directory = root / key
                directory.mkdir()
                (directory / '.git').write_text('invalid git barrier\n', encoding='utf-8')
            env = {'PATH': os.defpath, 'HOME': str(root / 'home'), 'TMPDIR': str(root / 'tmp'),
                   'HERMES_HOME': str(root / 'hermes'), 'OMH_HOME': str(root / 'omh')}
            before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}
            for primitive in ('O_NOFOLLOW', 'O_DIRECTORY', 'dir_fd'):
                for command in ('validate', 'merge', 'summary', 'transition'):
                    with self.subTest(primitive=primitive, command=command):
                        args = [command]
                        if command in ('validate', 'merge'):
                            args += ['--input', r'C:\private\captures.json']
                        if command != 'validate':
                            args += ['--workspace', str(root / 'new-workspace')]
                        if command == 'transition':
                            args += ['--job-id', 'job-' + '0' * 64, '--state', 'draft',
                                     '--evidence-type', 'draft_artifact', '--evidence-ref', 'drafts/resume.md',
                                     '--occurred-at', '2026-10-23T03:00:00Z']
                        result = subprocess.run([sys.executable, '-I', '-B', '-c', runner, primitive,
                                                 str(SCRIPT), *args], cwd=root, env=env,
                                                capture_output=True, text=True, timeout=15)
                        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                        self.assertEqual(result.stdout, '')
                        payload = json.loads(result.stderr)
                        self.assertEqual(payload['schema'], 'ai_job_search_error/v1')
                        self.assertFalse(payload['ok'])
                        self.assertEqual(payload['error']['code'], 'unsupported_platform')
                        self.assertIn('no-follow/dir-fd', payload['error']['message'])
                        self.assertEqual({str(p.relative_to(root)): p.read_bytes()
                                          for p in root.rglob('*') if p.is_file()}, before)
                        self.assertFalse((root / 'new-workspace').exists())


@requires_secure_dir_io
class JobStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="job-state-test-", dir=SCRATCH)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / "private-tracker"
        self.input = self.root / "captures.json"
        home = self.root / "home"
        home.mkdir()
        (home / ".git").write_text("invalid isolated test barrier\n", encoding="utf-8")
        self.env = {"PATH": os.defpath, "HOME": str(home), "HERMES_HOME": str(home / "hermes"),
                    "OMH_HOME": str(home / "omh"), "TMPDIR": str(self.root),
                    "PYTHONDONTWRITEBYTECODE": "1", "LC_ALL": "C.UTF-8"}
        git = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=home,
                             env=self.env, capture_output=True, timeout=10)
        self.assertNotEqual(git.returncode, 0, "test HOME must not resolve ancestor repository")

    def write_capture(self, value=None):
        self.input.write_text(json.dumps(capture() if value is None else value), encoding="utf-8")
        return str(self.input)

    def cli(self, *args, exit=0, runner=None, timeout=15):
        cmd = [sys.executable, "-I", "-B"]
        cmd += [str(SCRIPT)] if runner is None else ["-c", runner, str(SCRIPT)]
        result = subprocess.run([*cmd, *map(str, args)], cwd=self.root,
                                env=self.env, capture_output=True, text=True, timeout=timeout)
        self.assertEqual(result.returncode, exit, result.stdout + result.stderr)
        stream = result.stdout if exit == 0 else result.stderr
        try:
            payload = json.loads(stream)
        except ValueError:
            self.fail("expected one JSON object, got " + repr(stream[:500]))
        self.assertEqual(payload["ok"], exit == 0)
        self.assertEqual(payload["schema"], "ai_job_search_result/v1" if exit == 0
                         else "ai_job_search_error/v1")
        self.assertEqual(result.stderr if exit == 0 else result.stdout, "")
        return payload

    def merge(self, value=None, **kwargs):
        return self.cli("merge", "--workspace", self.workspace,
                        "--input", self.write_capture(value), **kwargs)

    def state(self):
        return json.loads((self.workspace / "state.json").read_bytes())

    def transition(self, job_id, target, kind, ref="confirmations/synthetic.md", time="2026-10-23T03:00:00Z", **kwargs):
        return self.cli("transition", "--workspace", self.workspace, "--job-id", job_id,
                        "--state", target, "--evidence-type", kind, "--evidence-ref", ref,
                        "--occurred-at", time, **kwargs)

    def test_source_outcome_classes(self):
        value = capture()
        result = self.cli("validate", "--input", self.write_capture(value))
        self.assertEqual(result, {"schema": "ai_job_search_result/v1", "command": "validate",
                                 "ok": True, "job_count": 1, "source_count": 1,
                                 "verified_job_count": 0, "source_outcome": "results"})
        self.assertFalse(self.workspace.exists())

    def test_identity_and_dedup(self):
        first = self.merge()
        expected = "job-" + hashlib.sha256(b"id:careers.example.invalid:REQ-101").hexdigest()
        self.assertEqual(first["inserted_job_ids"], [expected])
        self.assertEqual(first["revision"], 1)
        before = (self.workspace / "state.json").read_bytes()
        replay = self.merge()
        self.assertEqual(replay["revision"], 1)
        self.assertEqual(replay["inserted_job_ids"], [])
        self.assertEqual(replay["updated_job_ids"], [])
        self.assertEqual((self.workspace / "state.json").read_bytes(), before)
        value = capture()
        newer = copy.deepcopy(value["jobs"][0])
        newer["original_url"] = newer["original_url"].replace("demo", "second")
        value["jobs"].append(newer)
        result = self.merge(value)
        self.assertEqual(result["job_count"], 1)
        self.assertEqual(len(self.state()["jobs"][expected]["original_urls"]), 2)
        self.assertEqual(len(self.state()["jobs"][expected]["observations"]), 2)
        self.assertEqual(self.state()["jobs"][expected]["application_state"], "none")

    def test_identity_parameters_and_fragments(self):
        value = capture()
        value["jobs"] = []
        urls = ["HTTPS://Careers.Example.Invalid:443/jobs/?req=A&ref=x&gh_jid=1#first",
                "https://careers.example.invalid/jobs/?req=B&ref=x&gh_jid=1#first",
                "https://careers.example.invalid/jobs/?req=A&ref=x&gh_jid=1#second",
                "https://careers.example.invalid/jobs/?req=A&ref=x&gh_jid=1#first"]
        for url in urls:
            job = capture()["jobs"][0]
            job.update(posting_id=None, original_url=url + ("" if "#" in url else ""), canonical_url=None)
            value["jobs"].append(job)
        result = self.merge(value)
        self.assertEqual(result["job_count"], 3)
        expected = "job-" + hashlib.sha256(("url:" + urls[-1]).encode()).hexdigest()
        self.assertIn(expected, self.state()["jobs"])
        self.assertEqual(self.state()["jobs"][expected]["original_urls"], [urls[0], urls[-1]])

    def test_ambiguous_company_title_not_merged(self):
        value = capture()
        for posting_id in ("REQ-102", "req-101", None):
            job = copy.deepcopy(value["jobs"][0])
            job["posting_id"] = posting_id
            value["jobs"].append(job)
        result = self.merge(value)
        ids = sorted(self.state()["jobs"])
        self.assertEqual(result["job_count"], 4)
        self.assertEqual(result["possible_duplicates"], [[a, b] for i, a in enumerate(ids) for b in ids[i+1:]])

    def test_later_invalid_record_preserves_state(self):
        self.merge()
        old = (self.workspace / "state.json").read_bytes()
        value = capture()
        value["jobs"].append({**value["jobs"][0], "posting_id": "REQ-102", "posted_at": "2026-02-30"})
        self.merge(value, exit=2)
        self.assertEqual((self.workspace / "state.json").read_bytes(), old)
        value = capture()
        value["sources"].append({**value["sources"][0], "receipt_id": "later", "freshness": None})
        self.merge(value, exit=2)
        self.assertEqual((self.workspace / "state.json").read_bytes(), old)
        value = capture()
        value["sources"][0]["evidence_ref"] = "captures/different.md"
        self.merge(value, exit=2)
        self.assertEqual((self.workspace / "state.json").read_bytes(), old)

    def test_merge_observation_order_and_conflicts(self):
        self.merge()
        value = capture()
        value["sources"][0].update(receipt_id="new", retrieved_at="2026-10-24T02:00:00Z", kind="employer",
                                    source_url="https://careers.example.invalid/jobs", freshness="verified")
        value["jobs"][0].update(receipt_ids=["new"], title="Synthetic Updated Title", availability="closed")
        result = self.merge(value)
        job_id = result["updated_job_ids"][0]
        self.assertEqual(self.state()["jobs"][job_id]["job"]["availability"], "closed")
        older = capture()
        older["sources"][0].update(receipt_id="old", retrieved_at="2026-10-22T02:00:00Z")
        older["jobs"][0].update(receipt_ids=["old"], title="Synthetic Old Title")
        self.merge(older)
        self.assertEqual(self.state()["jobs"][job_id]["job"]["title"], "Synthetic Updated Title")
        self.assertEqual(len(self.state()["jobs"][job_id]["observations"]), 3)
        old = (self.workspace / "state.json").read_bytes()
        value["jobs"][0]["title"] = "Conflicting Equal Time"
        self.merge(value, exit=2)
        self.assertEqual((self.workspace / "state.json").read_bytes(), old)

    def test_invalid_wire_timestamps_refuse_before_any_write(self):
        job_id = self.merge()["inserted_job_ids"][0]
        old = (self.workspace / "state.json").read_bytes()
        # A refusal must precede even lock/temp/workspace creation, not just replace.
        no_writes = '''
import os, runpy, sys
script = sys.argv.pop(1)
def audit(event, args):
    if event == 'open' and args[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC):
        raise AssertionError('timestamp validation attempted a write')
    if event in {'os.mkdir', 'os.remove', 'os.rename', 'os.chmod', 'os.rmdir'}:
        raise AssertionError('timestamp validation attempted a mutation: ' + event)
sys.addaudithook(audit)
runpy.run_path(script, run_name='__main__')
'''
        malformed = (
            "2026-10-24T02:00:00+00:60", "2026-10-24T02:00:00+00:99",
            "2026-10-24T02:00:00-01:60", "2026-10-24T02:00:00+24:00",
            "2026-10-24T02:00:00-24:00", "2026-10-24T02:00:00+99:00",
            "2026-02-29T02:00:00Z", "2026-04-31T02:00:00Z",
            "0000-01-01T00:00:00Z", "2026-10-24T24:00:00Z",
            "2026-10-24T02:60:00Z", "2026-10-24T02:00:60Z",
        )
        for instant in malformed:
            value = capture()
            value["sources"][0].update(receipt_id="invalid-later", retrieved_at=instant)
            value["jobs"][0].update(receipt_ids=["invalid-later"], title="Invalid later observation")
            for command in ("validate", "merge"):
                with self.subTest(instant=instant, command=command):
                    args = [command, "--input", self.write_capture(value)]
                    if command == "merge":
                        args += ["--workspace", self.workspace]
                    result = self.cli(*args, exit=2, runner=no_writes)
                    self.assertEqual(result["error"]["code"], "invalid_timestamp")
                    self.assertEqual((self.workspace / "state.json").read_bytes(), old)
            with self.subTest(instant=instant, command="transition"):
                result = self.transition(job_id, "draft", "draft_artifact", time=instant,
                                         exit=2, runner=no_writes)
                self.assertEqual(result["error"]["code"], "invalid_timestamp")
                self.assertEqual((self.workspace / "state.json").read_bytes(), old)

    def test_hour_24_refused_on_every_interpreter(self):
        # CPython 3.14 parses T24:00:00 as the next midnight; 3.11-3.13 refuse it.
        # This runner gives older interpreters the 3.14 reading, so CI on 3.11
        # and 3.13 exercises the same guard a 3.14 venv depends on.
        lenient = '''
import datetime, runpy, sys
script = sys.argv.pop(1)
strict = datetime.datetime
class Lenient(strict):
    @classmethod
    def fromisoformat(cls, value):
        if value[10:] == 'T24:00:00':
            midnight = strict.fromisoformat(value[:10] + 'T00:00:00')
            try:
                return midnight + datetime.timedelta(days=1)
            except OverflowError:  # 3.14 refuses 9999-12-31T24:00:00 with ValueError
                raise ValueError('year must be in 1..9999, not 10000') from None
        return strict.fromisoformat(value)
datetime.datetime = Lenient
runpy.run_path(script, run_name='__main__')
'''
        job_id = self.merge()["inserted_job_ids"][0]
        for runner in (None, lenient):
            for day in ("2026-02-28", "2026-10-23", "2026-10-24", "2026-12-31", "9999-12-31"):
                instant = day + "T24:00:00Z"
                value = capture()
                value["sources"][0]["retrieved_at"] = instant
                with self.subTest(instant=instant, lenient=runner is not None, command="validate"):
                    result = self.cli("validate", "--input", self.write_capture(value),
                                      exit=2, runner=runner)
                    self.assertEqual(result["error"]["code"], "invalid_timestamp")
                with self.subTest(instant=instant, lenient=runner is not None, command="transition"):
                    result = self.transition(job_id, "draft", "draft_artifact", time=instant,
                                             exit=2, runner=runner)
                    self.assertEqual(result["error"]["code"], "invalid_timestamp")
            # The midnight that hour 24 would have meant stays valid.
            value = capture()
            value["sources"][0]["retrieved_at"] = "2026-10-25T00:00:00Z"
            self.cli("validate", "--input", self.write_capture(value), runner=runner)

    def test_exact_fractional_timestamp_order_and_offset_equality(self):
        prefix = "2026-10-23T02:00:00."
        long_fraction = "1" + "0" * (4096 - len(prefix) - len("1Z") - 1)
        ordered_pairs = (
            (prefix + "0000001Z", prefix + "0000002Z"),
            (prefix + "1234567890123456789012345678901Z", prefix + "1234567890123456789012345678902Z"),
            (prefix + long_fraction + "1Z", prefix + long_fraction + "2Z"),
            ("2026-12-31T23:59:59.999999999Z", "2027-01-01T00:00:00Z"),
            ("2026-10-23T02:00:00.999999999Z", "2026-10-23T02:00:01Z"),
            ("2026-10-24T01:59:00.0000001+23:59", prefix + "0000002Z"),
            ("2026-10-22T02:01:00.0000001-23:59", prefix + "0000002Z"),
            ("0001-01-01T00:00:00+23:59", "0001-01-01T00:00:00Z"),
            ("9999-12-31T23:59:59Z", "9999-12-31T23:59:59-23:59"),
        )
        equal_pairs = (
            (prefix + "1000000Z", "2026-10-23T11:00:00.1+09:00"),
            ("2026-10-23T02:00:00Z", "2026-10-23T02:00:00.000000000-00:00"),
            ("2027-01-01T00:00:00.123456789Z", "2026-12-31T23:00:00.123456789000-01:00"),
            (prefix + long_fraction + "0Z", prefix + "1Z"),
        )
        for index, (earlier, later) in enumerate(ordered_pairs + equal_pairs):
            with self.subTest(earlier=earlier, later=later):
                self.workspace = self.root / ("timestamp-tracker-" + str(index))
                value = capture()
                value["sources"][0]["retrieved_at"] = earlier
                job_id = self.merge(value)["inserted_job_ids"][0]
                newer = copy.deepcopy(value)
                newer["sources"][0].update(receipt_id="later", retrieved_at=later)
                newer["jobs"][0].update(receipt_ids=["later"], title="Newer exact instant")
                if index < len(ordered_pairs):
                    self.merge(newer)
                    entry = self.state()["jobs"][job_id]
                    self.assertEqual(entry["job"]["title"], "Newer exact instant")
                    self.assertEqual(self.state()["sources"]["later"]["retrieved_at"], later)
                    # Older observations stay recorded but never replace the latest.
                    value["sources"][0]["receipt_id"] = "older-repeat"
                    value["jobs"][0]["receipt_ids"] = ["older-repeat"]
                    self.merge(value)
                    self.assertEqual(self.state()["jobs"][job_id]["job"]["title"], "Newer exact instant")
                    self.transition(job_id, "draft", "draft_artifact", time=later)
                    self.assertEqual(self.state()["jobs"][job_id]["history"][-1]["occurred_at"], later)
                else:
                    old = (self.workspace / "state.json").read_bytes()
                    self.merge(newer, exit=2)
                    self.assertEqual((self.workspace / "state.json").read_bytes(), old)
                    # Equal instants with unchanged descriptions remain acceptable.
                    newer["jobs"][0]["title"] = value["jobs"][0]["title"]
                    self.merge(newer)
                    self.assertEqual(self.state()["sources"]["later"]["retrieved_at"], later)

    def test_evidence_bound_transitions(self):
        job_id = self.merge()["inserted_job_ids"][0]
        old = (self.workspace / "state.json").read_bytes()
        for target in ("submitted", "interviewing", "offered", "accepted"):
            self.transition(job_id, target, "draft_artifact", ref="draft/resume.md", exit=2)
            self.assertEqual((self.workspace / "state.json").read_bytes(), old)
        draft = self.transition(job_id, "draft", "draft_artifact", ref="draft/resume.md")
        self.assertEqual(draft["event_id"], "event-000001")
        self.assertEqual(draft["application_state"], "draft")
        saved = (self.workspace / "state.json").read_bytes()
        repeated = self.transition(job_id, "draft", "draft_artifact", ref="draft/resume.md")
        self.assertFalse(repeated["changed"])
        self.assertEqual((self.workspace / "state.json").read_bytes(), saved)
        self.transition(job_id, "draft", "draft_artifact", ref="draft/other.md", exit=2)
        self.transition(job_id, "submitted", "submission_receipt")
        self.transition(job_id, "accepted", "user_decision", exit=2)
        self.transition(job_id, "interviewing", "employer_notice")
        self.transition(job_id, "offered", "employer_notice")
        self.transition(job_id, "accepted", "user_report", exit=2)
        accepted = self.transition(job_id, "accepted", "user_decision")
        self.assertEqual(accepted["revision"], 6)
        state = self.state()["jobs"][job_id]
        self.assertEqual(state["job"]["availability"], "unknown")
        self.assertEqual([e["to_state"] for e in state["history"]],
                         ["draft", "submitted", "interviewing", "offered", "accepted"])
        self.transition(job_id, "withdrawn", "user_decision", exit=2)

    def test_correction_preserves_history(self):
        job_id = self.merge()["inserted_job_ids"][0]
        self.transition(job_id, "submitted", "user_report")
        previous = copy.deepcopy(self.state()["jobs"][job_id]["history"])
        args = ["transition", "--workspace", self.workspace, "--job-id", job_id, "--state", "none",
                "--evidence-type", "user_correction", "--evidence-ref", "corrections/explicit.md",
                "--occurred-at", "2026-10-20T03:00:00+09:00", "--corrects-event", "event-000001"]
        result = self.cli(*args)
        self.assertTrue(result["changed"])
        self.assertEqual(self.state()["jobs"][job_id]["history"][:1], previous)
        self.assertEqual(self.state()["jobs"][job_id]["history"][-1]["event_id"], "event-000002")
        old = (self.workspace / "state.json").read_bytes()
        self.assertFalse(self.cli(*args)["changed"])
        self.assertEqual((self.workspace / "state.json").read_bytes(), old)
        args[-1] = "event-999999"
        self.cli(*args, exit=2)
        args[-1] = "event-000001"
        args[args.index("corrections/explicit.md")] = "confirmations/synthetic.md"
        self.cli(*args, exit=2)
        self.assertEqual((self.workspace / "state.json").read_bytes(), old)
        self.transition(job_id, "submitted", "user_report")
        self.assertEqual(self.state()["jobs"][job_id]["history"][-1]["event_id"], "event-000003")

    def test_summary_counts_from_state(self):
        empty = self.cli("summary", "--workspace", self.workspace)
        self.assertEqual(empty["revision"], 0)
        self.assertEqual(empty["source_outcome"], "not_observed")
        self.assertFalse(self.workspace.exists())
        value = capture()
        for index in range(1, 8):
            job = copy.deepcopy(value["jobs"][0])
            job.update(posting_id=f"REQ-{index}", company=f"Synthetic {index}")
            value["jobs"].append(job)
        self.merge(value)
        ids = sorted(self.state()["jobs"])
        routes = [[("draft", "draft_artifact")], [("submitted", "user_report")],
                  [("submitted", "user_report"), ("interviewing", "user_report")],
                  [("submitted", "user_report"), ("offered", "user_report")],
                  [("submitted", "user_report"), ("offered", "user_report"), ("accepted", "user_decision")],
                  [("submitted", "user_report"), ("rejected", "user_report")],
                  [("draft", "draft_artifact"), ("withdrawn", "user_decision")]]
        for job_id, route in zip(ids, routes):
            for target, kind in route:
                self.transition(job_id, target, kind)
        old = (self.workspace / "state.json").read_bytes()
        result = self.cli("summary", "--workspace", self.workspace)
        self.assertEqual(result["application_counts"], dict.fromkeys(
            ("none", "draft", "submitted", "interviewing", "offered", "accepted", "rejected", "withdrawn"), 1))
        self.assertEqual(result["availability_counts"], {"unknown": 8, "open": 0, "closed": 0})
        self.assertEqual(result["job_count"], 8)
        self.assertEqual(result["source_count"], 1)
        self.assertEqual(result["verified_job_count"], 0)
        expected = sorted(k for k, v in self.state()["jobs"].items()
                          if v["application_state"] in {"none", "draft", "submitted", "interviewing", "offered"})
        self.assertEqual(result["next_action_job_ids"], expected)
        self.assertEqual((self.workspace / "state.json").read_bytes(), old)

    def test_bounds_and_types(self):
        self.merge()
        old = (self.workspace / "state.json").read_bytes()
        # Every supplied job/source field: missing, null when nonnullable, and collections.
        nullable_jobs = {"posting_id", "canonical_url", "location", "remote_scope", "posted_at", "deadline", "application_url"}
        nullable_sources = {"source_url", "error"}
        for section, nullable in (("jobs", nullable_jobs), ("sources", nullable_sources)):
            for field in capture()[section][0]:
                for bad in ("missing", "collection", "null"):
                    if bad == "null" and field in nullable:
                        continue
                    value = capture()
                    if bad == "missing":
                        del value[section][0][field]
                    else:
                        value[section][0][field] = {} if bad == "collection" else None
                    with self.subTest(section=section, field=field, bad=bad):
                        self.merge(value, exit=2)
                        self.assertEqual((self.workspace / "state.json").read_bytes(), old)
        for field, wrong in (("posting_id", True), ("location", 5), ("deadline", "2026-13-01"),
                             ("posted_at", "today"), ("remote_scope", "x" * 513),
                             ("posting_id", "x" * 257), ("title", "x\x00y"), ("company", "bad\nline")):
            value = capture()
            value["jobs"][0][field] = wrong
            self.merge(value, exit=2)
        for count, section in ((101, "jobs"), (201, "sources")):
            value = capture()
            value[section] *= count
            result = self.merge(value, exit=2)
            self.assertEqual(result["error"]["code"], "limit_exceeded")
        value = capture()
        value["jobs"][0]["receipt_ids"] *= 21
        self.assertEqual(self.merge(value, exit=2)["error"]["code"], "limit_exceeded")
        value = capture()
        value["jobs"][0]["extra"] = "not ignored"
        self.merge(value, exit=2)
        # Raw parser attacks are refused without echoing private content.
        for raw in (b'{"schema":1,"schema":2}', b'{"secret":NaN}', b'{"secret":Infinity}',
                    b'{"secret":' + b'[' * 13 + b'0' + b']' * 13 + b'}',
                    b'{}' + b' ' * (2 * 1024 * 1024), b'\xff',
                    json.dumps({"secret": "x" * 4097}).encode()):
            self.input.write_bytes(raw)
            result = self.cli("merge", "--workspace", self.workspace, "--input", self.input, exit=2)
            self.assertNotIn("secret", result["error"]["message"])
        self.assertEqual((self.workspace / "state.json").read_bytes(), old)

    def test_unsafe_paths_and_symlinks(self):
        self.merge()
        old = (self.workspace / "state.json").read_bytes()
        for path in (str(self.root / ".." / self.root.name / "bad"), str(self.root / "CON"),
                     str(self.root / "trailing."), str(self.root / "C:bad"), str(self.root / "bad\\path")):
            self.cli("merge", "--workspace", path, "--input", self.write_capture(), exit=2)
        linked = self.root / "linked-input"
        linked.symlink_to(self.input)
        self.cli("validate", "--input", linked, exit=2)
        parent = self.root / "linked-parent"
        parent.symlink_to(self.root, target_is_directory=True)
        self.cli("summary", "--workspace", parent / "private-tracker", exit=2)
        for name in ("state.json", ".job-state.lock"):
            path = self.workspace / name
            if path.exists():
                path.unlink()
            path.symlink_to(self.input)
            self.merge(exit=2)
            path.unlink()
            if name == "state.json":
                path.write_bytes(old)
        self.assertEqual((self.workspace / "state.json").read_bytes(), old)
        (self.workspace / "state.json").unlink()
        (self.workspace / "state.json").mkdir()
        self.cli("summary", "--workspace", self.workspace, exit=2)
        self.merge(exit=2)
        fifo = self.root / "fifo"
        os.mkfifo(fifo)
        self.cli("validate", "--input", fifo, exit=2)
        self.cli("validate", "--input", self.root, exit=2)

    def test_atomic_failure_preserves_state(self):
        self.merge()
        old = (self.workspace / "state.json").read_bytes()
        value = capture()
        value["jobs"][0]["posting_id"] = "new-job"
        for operation in ("fsync", "replace", "write"):
            setup = "import os, runpy, sys\n"
            if operation == "write":
                setup += ("original = os.fdopen\n"
                          "def fail(fd, mode, *a, **kw):\n"
                          "    if mode == 'wb': raise OSError('injected write failure')\n"
                          "    return original(fd, mode, *a, **kw)\n"
                          "os.fdopen = fail\n")
            else:
                setup += f"def fail(*a, **kw): raise OSError('injected {operation} failure')\nos.{operation} = fail\n"
            runner = setup + "sys.argv = sys.argv[1:]\nrunpy.run_path(sys.argv[0], run_name='__main__')\n"
            with self.subTest(operation=operation):
                self.merge(value, exit=4, runner=runner)
                self.assertEqual((self.workspace / "state.json").read_bytes(), old)
                self.assertEqual(sorted(p.name for p in self.workspace.iterdir()), ["state.json"])

    def test_concurrent_writer_refused(self):
        self.merge()
        old = (self.workspace / "state.json").read_bytes()
        lock = self.workspace / ".job-state.lock"
        lock.write_text("another writer", encoding="utf-8")
        self.merge(exit=3)
        self.assertEqual(lock.read_text(), "another writer")
        self.assertEqual((self.workspace / "state.json").read_bytes(), old)
        lock.unlink()
        # A non-cooperating write during the file fsync must not be overwritten.
        runner = ("import os, runpy, sys\nfrom pathlib import Path\n"
                  "original = os.fsync\n"
                  "def conflict(fd):\n"
                  "    p = Path(sys.argv[sys.argv.index('--workspace') + 1]) / 'state.json'\n"
                  "    p.write_bytes(p.read_bytes() + b' ')\n"
                  "    original(fd)\n"
                  "os.fsync = conflict\nsys.argv = sys.argv[1:]\nrunpy.run_path(sys.argv[0], run_name='__main__')\n")
        value = capture()
        value["jobs"][0]["posting_id"] = "new"
        self.merge(value, exit=3, runner=runner)
        self.assertEqual((self.workspace / "state.json").read_bytes(), old + b" ")
        self.assertEqual(sorted(p.name for p in self.workspace.iterdir()), ["state.json"])

    def test_offline_no_process(self):
        runner = ("import runpy, sys\n"
                  "def audit(event, args):\n"
                  "    if event.startswith(('socket.', 'subprocess.', 'os.exec', 'os.spawn', 'os.posix_spawn')) or event in {'os.system', 'os.fork', 'pty.spawn'}:\n"
                  "        raise AssertionError('unexpected network/process side effect: ' + event)\n"
                  "sys.addaudithook(audit)\nsys.argv = sys.argv[1:]\nrunpy.run_path(sys.argv[0], run_name='__main__')\n")
        self.cli("validate", "--input", self.write_capture(), runner=runner)
        job_id = self.merge(runner=runner)["inserted_job_ids"][0]
        self.transition(job_id, "draft", "draft_artifact", runner=runner)
        self.cli("summary", "--workspace", self.workspace, runner=runner)

    def test_corrupted_state_is_never_reset(self):
        job_id = self.merge()["inserted_job_ids"][0]
        self.transition(job_id, "submitted", "user_report")
        good = self.state()
        variants = []
        for revision in (None, True, 1.0, "2", -1, 2147483648):
            value = copy.deepcopy(good)
            value["revision"] = revision
            variants.append(value)
        for path, bad in ((("schema",), "unknown/v1"), (("jobs", job_id, "history", 0, "from_state"), "draft"),
                          (("jobs", job_id, "application_state"), "draft"),
                          (("jobs", job_id, "job", "unknown"), "not lost"),
                          (("jobs", job_id, "job", "posted_at"), "2026-02-30"),
                          (("jobs", job_id, "observations"), []),
                          (("jobs", job_id, "receipt_ids"), [])):
            value = copy.deepcopy(good)
            target = value
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = bad
            variants.append(value)
        for value in variants:
            raw = json.dumps(value).encode()
            (self.workspace / "state.json").write_bytes(raw)
            self.cli("summary", "--workspace", self.workspace, exit=2)
            self.merge(exit=2)
            self.assertEqual((self.workspace / "state.json").read_bytes(), raw)

    def test_validate_rejects_conflicting_identity(self):
        value = capture()
        value["jobs"].append({**value["jobs"][0], "title": "Contradictory Equal-time Title"})
        self.cli("validate", "--input", self.write_capture(value), exit=2)

    def test_source_status_and_receipt_authority(self):
        fixtures = []
        blank = {"schema": "ai_job_search_captures/v1", "jobs": [], "sources": []}
        fixtures.append((blank, "not_observed", 0))
        blocked = copy.deepcopy(blank)
        source = capture()["sources"][0]
        source.update(kind="search", source_url="https://search.example.invalid/", status="blocked", error="Synthetic blocked")
        blocked["sources"] = [source]
        fixtures.append((blocked, "blocked", 0))
        empty = copy.deepcopy(blocked)
        empty["sources"][0].update(status="empty", error=None)
        fixtures.append((empty, "empty", 0))
        partial = capture()
        partial["sources"].append(source)
        partial["sources"][-1]["receipt_id"] = "blocked"
        fixtures.append((partial, "partial", 0))
        live = capture()
        live["sources"][0].update(kind="original", source_url="https://careers.example.invalid/jobs", freshness="verified")
        live["jobs"][0]["availability"] = "open"
        fixtures.append((live, "results", 1))
        for value, expected, count in fixtures:
            with self.subTest(expected=expected):
                result = self.cli("validate", "--input", self.write_capture(value))
                self.assertEqual(result["source_outcome"], expected)
                self.assertEqual(result["verified_job_count"], count)
        # One successful nonempty search is not an empty-search result.
        ambiguous_empty = copy.deepcopy(empty)
        ambiguous_empty["sources"].append({**empty["sources"][0], "receipt_id": "nonempty", "status": "ok"})
        result = self.cli("validate", "--input", self.write_capture(ambiguous_empty))
        self.assertEqual(result["source_outcome"], "not_observed")
        for change in ({"freshness": "verified"}, {"status": "blocked", "error": None},
                       {"status": "empty"}, {"retrieved_at": "2026-10-23T02:00:00"},
                       {"error": "unexpected"}, {"source_url": []}):
            value = capture()
            value["sources"][0].update(change)
            self.cli("validate", "--input", self.write_capture(value), exit=2)
        for status in ("empty", "blocked", "error"):
            value = capture()
            value["sources"][0].update(kind="search", source_url="https://search.example.invalid/", status=status,
                                        error="Synthetic failure" if status != "empty" else None)
            self.cli("validate", "--input", self.write_capture(value), exit=2)
        value = capture()
        value["jobs"][0]["availability"] = "open"
        self.cli("validate", "--input", self.write_capture(value), exit=2)
        self.merge(live)
        # Later failed retrieval adds a receipt, never closes/expunges the old job.
        only_blocked = copy.deepcopy(blocked)
        only_blocked["sources"][0]["receipt_id"] = "later-blocked"
        self.assertEqual(self.merge(only_blocked)["source_outcome"], "blocked")
        summary = self.cli("summary", "--workspace", self.workspace)
        self.assertEqual(summary["source_outcome"], "partial")
        self.assertEqual(summary["availability_counts"]["open"], 1)

    def test_raw_url_identity_and_invalid_urls(self):
        url = "HTTP://Careers.Example.Invalid:80/Jobs/%2f/?ref=X&req=01&req=02&%75TM_SOURCE=gone&x=%2B+%20&job=7#A%2fb"
        normalized = "http://careers.example.invalid/Jobs/%2f/?ref=X&req=01&req=02&x=%2B+%20&job=7#A%2fb"
        value = capture()
        value["jobs"][0].update(posting_id=None, original_url=url, canonical_url=normalized)
        job_id = self.merge(value)["inserted_job_ids"][0]
        self.assertEqual(job_id, "job-" + hashlib.sha256(("url:" + normalized).encode()).hexdigest())
        for url in ("ftp://example.invalid/jobs", "https://user:pass@example.invalid/", "https:///missing", "https://host.invalid:99999/",
                    "https://bad_host.invalid/", "https://host.invalid/%GG", "https://host.invalid/with space", "https://host.invalid:/",
                    "https://[broken/", "https://host.invalid/a\n", "https://127.0.0.999/"):
            with self.subTest(url=url):
                bad = capture()
                bad["jobs"][0].update(original_url=url, canonical_url=None)
                self.cli("validate", "--input", self.write_capture(bad), exit=2)
        bad = capture()
        bad["jobs"][0]["canonical_url"] = "https://different.example.invalid/"
        self.cli("validate", "--input", self.write_capture(bad), exit=2)

    def test_real_competing_writer(self):
        import select
        self.merge()
        old = (self.workspace / "state.json").read_bytes()
        value = capture()
        value["jobs"][0]["posting_id"] = "concurrent-first"
        runner = ("import os, runpy, sys\noriginal = os.fsync\n"
                  "def pause(fd):\n    original(fd)\n    print('READY', flush=True)\n    sys.stdin.readline()\n"
                  "os.fsync = pause\nsys.argv = sys.argv[1:]\nrunpy.run_path(sys.argv[0], run_name='__main__')\n")
        args = [sys.executable, "-I", "-B", "-c", runner, str(SCRIPT), "merge", "--workspace", str(self.workspace),
                "--input", self.write_capture(value)]
        child = subprocess.Popen(args, cwd=self.root, env=self.env, stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            ready, _, _ = select.select([child.stdout], [], [], 10)
            self.assertTrue(ready, "writer did not reach commit boundary")
            self.assertEqual(child.stdout.readline(), "READY\n")
            self.merge(exit=3)
            self.assertEqual((self.workspace / "state.json").read_bytes(), old)
            output, errors = child.communicate("release\n", timeout=10)
            self.assertEqual(child.returncode, 0, errors)
            self.assertEqual(json.loads(output)["job_count"], 2)
        finally:
            if child.poll() is None:
                child.kill()
                child.communicate(timeout=10)
        self.assertEqual(self.cli("summary", "--workspace", self.workspace)["job_count"], 2)
        self.assertEqual(sorted(p.name for p in self.workspace.iterdir()), ["state.json"])

    def test_cli_arguments_and_help(self):
        for args in ([], ["unknown"], ["validate"], ["summary"], ["summary", "--workspace", str(self.workspace), "--network"],
                     ["validate", "--inp", self.write_capture()]):
            self.cli(*args, exit=2)
        help_run = subprocess.run([sys.executable, "-I", "-B", str(SCRIPT), "--help"],
                                  env=self.env, cwd=self.root, text=True, capture_output=True, timeout=10)
        self.assertEqual(help_run.returncode, 0)
        self.assertIn("transition", help_run.stdout)
        self.assertEqual(help_run.stderr, "")
        self.assertFalse(self.workspace.exists())

    def test_stored_limits_and_revision_overflow(self):
        job_id = self.merge()["inserted_job_ids"][0]
        good = self.state()
        variants = []
        value = copy.deepcopy(good)
        value["jobs"] = {"job-" + f"{i:064x}": value["jobs"][job_id] for i in range(2001)}
        variants.append(value)
        value = copy.deepcopy(good)
        value["sources"] = {f"source-{i}": value["sources"]["synthetic-posting-1"] for i in range(4001)}
        variants.append(value)
        for field, count in (("original_urls", 101), ("receipt_ids", 201), ("observations", 10001), ("history", 101)):
            value = copy.deepcopy(good)
            entry = value["jobs"][job_id]
            if field == "original_urls":
                entry[field] = [f"https://careers.example.invalid/{i}" for i in range(count)]
            elif field == "receipt_ids":
                entry[field] = [f"r-{i}" for i in range(count)]
            elif field == "observations":
                entry[field] *= count
            else:
                entry[field] = [{} for _ in range(count)]
            variants.append(value)
        for value in variants:
            raw = json.dumps(value).encode()
            (self.workspace / "state.json").write_bytes(raw)
            result = self.cli("summary", "--workspace", self.workspace, exit=2)
            self.assertEqual(result["error"]["code"], "limit_exceeded")
            self.assertEqual((self.workspace / "state.json").read_bytes(), raw)
        raw = b"{}" + b" " * (16 * 1024 * 1024)
        (self.workspace / "state.json").write_bytes(raw)
        self.assertEqual(self.cli("summary", "--workspace", self.workspace, exit=2)["error"]["code"], "limit_exceeded")
        good["revision"] = 2147483647
        raw = json.dumps(good).encode()
        (self.workspace / "state.json").write_bytes(raw)
        self.assertEqual(self.merge()["revision"], 2147483647)  # Idempotent reads at boundary remain valid.
        value = capture()
        value["jobs"][0]["posting_id"] = "new"
        self.assertEqual(self.merge(value, exit=2)["error"]["code"], "limit_exceeded")
        self.assertEqual((self.workspace / "state.json").read_bytes(), raw)

    def test_aggregate_proposed_state_size_preserves_bytes(self):
        job_id = self.merge()["inserted_job_ids"][0]
        state = self.state()
        base = state["jobs"].pop(job_id)
        jobs = []
        # Full real limit: expand independent synthetic entries near 16 MiB, not a patched budget.
        for i in range(1200):
            job = copy.deepcopy(base["job"])
            job.update(posting_id=f"large-{i}", canonical_url=None,
                       original_url="https://careers.example.invalid/" + "x" * 3400,
                       title=(f"Synthetic {i} " + "t" * 512)[:512], company="c" * 512,
                       location="l" * 512, remote_scope="r" * 512)
            jobs.append(job)
        for job in jobs[:1100]:
            key = "job-" + hashlib.sha256(("id:careers.example.invalid:" + job["posting_id"]).encode()).hexdigest()
            entry = copy.deepcopy(base)
            entry.update(job=job, observations=[job], original_urls=[job["original_url"]])
            state["jobs"][key] = entry
        # Compact prior state is legal; formatted replacement crosses the hard limit.
        raw = json.dumps(state, separators=(",", ":")).encode()
        self.assertLess(len(raw), 16 * 1024 * 1024)
        (self.workspace / "state.json").write_bytes(raw)
        value = capture()
        value["jobs"] = jobs[1100:]
        # The child reads, merges and re-serialises ~16 MiB; on a shared CI runner that has
        # taken longer than the 15 s every other call gets (runs 45631420644, 45658444150, 45795499259).
        self.assertEqual(self.merge(value, exit=2, timeout=90)["error"]["code"], "limit_exceeded")
        self.assertEqual((self.workspace / "state.json").read_bytes(), raw)
        self.assertEqual(sorted(p.name for p in self.workspace.iterdir()), ["state.json"])

    def test_lock_ownership_conflict_preserves_other_lock(self):
        self.merge()
        old = (self.workspace / "state.json").read_bytes()
        runner = ("import os, runpy, sys\nfrom pathlib import Path\noriginal = os.fsync\n"
                  "def conflict(fd):\n"
                  "    p = Path(sys.argv[sys.argv.index('--workspace') + 1]) / '.job-state.lock'\n"
                  "    p.unlink()\n    p.write_text('other owner')\n    original(fd)\n"
                  "os.fsync = conflict\nsys.argv = sys.argv[1:]\nrunpy.run_path(sys.argv[0], run_name='__main__')\n")
        value = capture()
        value["jobs"][0]["posting_id"] = "new"
        self.merge(value, exit=3, runner=runner)
        self.assertEqual((self.workspace / "state.json").read_bytes(), old)
        self.assertEqual((self.workspace / ".job-state.lock").read_text(), "other owner")

    def test_unicode_literals_and_unknowns_preserved(self):
        value = capture()
        value["jobs"][0].update(posting_id="Req:한글 Ω", title=" Synthetic École ", company="Synthetic Café")
        other = copy.deepcopy(value["jobs"][0])
        other.update(posting_id="Req:한글 ω", title="synthetic E\u0301COLE", company=" synthetic CAFE\u0301 ")
        value["jobs"].append(other)
        result = self.merge(value)
        self.assertEqual(result["job_count"], 2)
        self.assertEqual(len(result["possible_duplicates"]), 1)
        for entry in self.state()["jobs"].values():
            original = next(job for job in value["jobs"] if job["posting_id"] == entry["job"]["posting_id"])
            self.assertEqual(entry["job"], original)
            self.assertIsNone(entry["job"]["deadline"])
            self.assertIsNone(entry["job"]["posted_at"])
        self.assertEqual(self.workspace.stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.workspace / "state.json").stat().st_mode & 0o777, 0o600)

    def test_nondefault_port_and_empty_fragment_retention(self):
        value = capture()
        original = "HTTPS://Careers.Example.Invalid:00081/jobs?req=X#"
        normalized = "https://careers.example.invalid:00081/jobs?req=X#"
        value["jobs"][0].update(posting_id=None, original_url=original, canonical_url=normalized)
        result = self.cli("validate", "--input", self.write_capture(value))
        self.assertEqual(result["job_count"], 1)

    def test_linked_lock_and_unsafe_evidence_refs(self):
        job_id = self.merge()["inserted_job_ids"][0]
        old = (self.workspace / "state.json").read_bytes()
        for ref in ("/absolute", "a/../b", "a//b", "a/./b", "C:drive", "a\\b", "a/CON.md", "a/LPT1.txt", "a/end.", "a/", "x" * 241):
            self.transition(job_id, "draft", "draft_artifact", ref=ref, exit=2)
            self.assertEqual((self.workspace / "state.json").read_bytes(), old)
        lock = self.workspace / ".job-state.lock"
        os.link(self.input, lock)
        result = self.merge(exit=2)
        self.assertEqual(result["error"]["code"], "unsafe_path")
        self.assertEqual((self.workspace / "state.json").read_bytes(), old)

    def test_postcommit_cleanup_retains_committed_result(self):
        self.merge()
        runner = ("import os, runpy, sys\noriginal = os.unlink\n"
                  "def fail(path, *a, **kw):\n"
                  "    if str(path) == '.job-state.lock': raise OSError('injected cleanup failure')\n"
                  "    return original(path, *a, **kw)\n"
                  "os.unlink = fail\nos.supports_dir_fd.add(fail)\n"
                  "sys.argv = sys.argv[1:]\nrunpy.run_path(sys.argv[0], run_name='__main__')\n")
        value = capture()
        value["jobs"][0]["posting_id"] = "committed-before-cleanup"
        result = self.merge(value, runner=runner)
        self.assertEqual(result["job_count"], 2)
        self.assertEqual(len(self.state()["jobs"]), 2)
        self.assertTrue((self.workspace / ".job-state.lock").exists())
        self.merge(value, exit=3)  # No unsafe automatic stale-lock break.

    def test_shipped_example_and_provenance(self):
        self.assertTrue((TOOLKIT / "upstream-manifest.json").is_file(), "shipped provenance manifest is missing")
        manifest = json.loads((TOOLKIT / "upstream-manifest.json").read_bytes())
        self.assertEqual(set(manifest), {"schema", "upstream", "files"})
        self.assertEqual(manifest["schema"], "omh_ai_job_search_provenance/v1")
        expected = {"README.md", "scripts/job_state.py", "examples/synthetic-captures.json", "LICENSE.upstream"}
        self.assertEqual(set(manifest["files"]), expected)
        for relative, entry in manifest["files"].items():
            self.assertEqual(set(entry), {"local_sha256", "origin", "license"})
            self.assertEqual(entry["local_sha256"], hashlib.sha256((TOOLKIT / relative).read_bytes()).hexdigest())
            self.assertEqual(entry["origin"], "notice" if relative == "LICENSE.upstream" else "original")
            self.assertEqual(entry["license"], "MIT")
        for source in manifest["upstream"]:
            self.assertEqual(set(source), {"repository", "revision", "paths", "relationship"})
            self.assertRegex(source["revision"], r"^[0-9a-f]{40}$")
            self.assertTrue(source["paths"])
        result = self.cli("validate", "--input", TOOLKIT / "examples/synthetic-captures.json")
        self.assertEqual(result["job_count"], 1)
        self.assertEqual(result["source_count"], 2)
        self.assertEqual(result["verified_job_count"], 0)
        self.assertEqual(result["source_outcome"], "partial")


if __name__ == "__main__":
    unittest.main()
