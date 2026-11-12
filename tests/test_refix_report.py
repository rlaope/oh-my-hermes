"""`tools/refix_report.py` classifies fix commits against a throwaway git history."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools import refix_report

HOUR = 3600
T0 = 1_800_000_000


def _lines(*names: str) -> str:
    return "".join(f"{name}\n" for name in names)


class RefixReportTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name)
        self.clock = T0
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "t@example.invalid")
        self.git("config", "user.name", "t")
        self.git("config", "commit.gpgsign", "false")

    def git(self, *args: str) -> str:
        stamp = f"{self.clock} +0000"
        env = {
            **os.environ,
            "GIT_AUTHOR_DATE": stamp,
            "GIT_COMMITTER_DATE": stamp,
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
        }
        done = subprocess.run(
            ["git", "-C", str(self.repo), *args], check=True, capture_output=True, text=True, env=env
        )
        return done.stdout.strip()

    def commit(self, name: str, text: str, message: str, hours_later: float = 0) -> str:
        self.clock += int(hours_later * HOUR)
        (self.repo / name).write_text(text, encoding="utf-8")
        self.git("add", name)
        self.git("commit", "-q", "-m", message)
        return self.git("rev-parse", "HEAD")

    def merge_branch(self, branch: str, hours_later: float = 0) -> None:
        self.clock += int(hours_later * HOUR)
        self.git("merge", "--no-ff", "-q", "-m", f"Merge {branch}", branch)

    def land(self, branch: str, steps: list[tuple[str, str, str]], hours_later: float) -> list[str]:
        """Branch off main, commit each (file, text, message), merge it `hours_later` on."""
        self.git("checkout", "-q", "-b", branch, "main")
        shas = [self.commit(name, text, message) for name, text, message in steps]
        self.git("checkout", "-q", "main")
        self.merge_branch(branch, hours_later)
        return shas

    def report(self, days: int = 30, window_hours: float = 48) -> refix_report.Report:
        return refix_report.build_report(self.repo, "main", days, window_hours)

    def fixes(self, report: refix_report.Report, verdict_pairs: bool = True) -> list[str]:
        return [pair.fix.subject for pair in report.pairs]

    def seed(self) -> None:
        self.commit("base.txt", "base\n", "seed")
        self.clock += 10 * 24 * HOUR  # keep the seed far outside every window

    def test_three_classes(self) -> None:
        self.seed()
        # Pull request A lands app.py, and a fixup to its own line inside the same merge.
        self.land(
            "feature-a",
            [
                ("app.py", _lines("one", "two", "three"), "add app"),
                ("app.py", _lines("one", "TWO", "three"), "fix: typo in app"),
            ],
            hours_later=1,
        )
        # Pull request B lands a long way later and replaces a line pull request A wrote 10 h before.
        self.land("fix-b", [("app.py", _lines("one", "TWO", "THREE"), "fix: three was wrong")], hours_later=10)
        # Pull request C replaces a line B wrote, but 60 h later: outside the 48 h window.
        self.land("fix-c", [("app.py", _lines("ONE", "TWO", "THREE"), "fix: one was wrong")], hours_later=60)
        # Pull request D fixes a line nobody wrote recently.
        self.land("fix-d", [("base.txt", "BASE\n", "fix: base")], hours_later=1)

        report = self.report()
        self.assertEqual(report.fix_commits, 4)
        self.assertEqual(
            report.counts,
            {refix_report.CLASS_NONE: 2, refix_report.CLASS_SAME: 1, refix_report.CLASS_ANOTHER: 1},
        )
        self.assertEqual(self.fixes(report), ["fix: three was wrong"])
        pair = report.pairs[0]
        self.assertEqual(pair.earlier.subject, "add app")
        self.assertEqual(pair.files, (("app.py", 1),))
        self.assertEqual(pair.age_hours, 10.0)

    def test_window_decides_another(self) -> None:
        self.seed()
        self.land("feature", [("a.txt", "x\n", "add a")], hours_later=1)
        self.land("fix-late", [("a.txt", "y\n", "hotfix: a")], hours_later=30)
        self.assertEqual(self.report(window_hours=48).counts[refix_report.CLASS_ANOTHER], 1)
        self.assertEqual(self.report(window_hours=12).counts[refix_report.CLASS_ANOTHER], 0)

    def test_non_fix_subjects_are_not_counted(self) -> None:
        self.seed()
        self.land("feature", [("a.txt", "x\n", "add a")], hours_later=1)
        self.land("next", [("a.txt", "y\n", "feat: change a"), ("b.txt", "b\n", "prefix: b")], hours_later=1)
        report = self.report()
        self.assertEqual(report.fix_commits, 0)
        self.assertEqual(report.pairs, [])

    def test_added_only_fix_replaces_nothing(self) -> None:
        self.seed()
        self.land("feature", [("a.txt", "x\n", "add a")], hours_later=1)
        self.git("checkout", "-q", "-b", "fix-add", "main")
        self.commit("a.txt", "x\ny\n", "fix: append a line", hours_later=1)
        self.git("checkout", "-q", "main")
        self.merge_branch("fix-add", 1)
        self.assertEqual(self.report().counts[refix_report.CLASS_NONE], 1)

    def test_unusual_filenames_are_kept(self) -> None:
        # git C-quotes or tab-pads these in a plain diff header; each must classify like a plain name.
        for name in ("normal.py", "a b.py", "café.py", 'a"b.py', "star*[x].py"):
            with self.subTest(name=name):
                self.setUp()
                self.seed()
                self.land("feature", [(name, "old\n", "feat: add source")], hours_later=1)
                self.land("repair", [(name, "new\n", "fix: repair source")], hours_later=1)
                report = self.report()
                self.assertEqual(report.counts[refix_report.CLASS_ANOTHER], 1)
                self.assertEqual([pair.files for pair in report.pairs], [((name, 1),)])
                self.assertEqual(report.blame_failed, 0)

    def test_failed_blame_is_counted(self) -> None:
        self.seed()
        self.land("feature", [("a.txt", "x\n", "add a")], hours_later=1)
        self.land("fix-it", [("a.txt", "y\n", "fix: a")], hours_later=1)
        real = refix_report._blame
        refix_report._blame = lambda *args: None
        self.addCleanup(setattr, refix_report, "_blame", real)
        report = self.report()
        self.assertEqual(report.blame_failed, 1)
        self.assertEqual(report.counts[refix_report.CLASS_NONE], 1)
        self.assertIn("blame failed: 1 file(s)", refix_report.render_text(report))
        self.assertEqual(json.loads(refix_report.render_json(report))["totals"]["blame_failed"], 1)

    def test_classifier_unit(self) -> None:
        mine = refix_report.Commit("a" * 40, "x", 0, "m1")
        other = refix_report.Commit("b" * 40, "y", 0, "m2")
        self.assertEqual(refix_report.classify("m1", []), refix_report.CLASS_NONE)
        self.assertEqual(refix_report.classify("m1", [mine]), refix_report.CLASS_SAME)
        self.assertEqual(refix_report.classify("m1", [mine, other]), refix_report.CLASS_ANOTHER)

    def test_subject_prefix(self) -> None:
        for subject in ("fix: a", "Fix(core): a", "hotfix: a", "fix a"):
            self.assertTrue(refix_report.is_fix_subject(subject), subject)
        for subject in ("fixture: a", "prefix: a", "feat: fix a", "fixup! a"):
            self.assertFalse(refix_report.is_fix_subject(subject), subject)

    def test_cli_json_and_footer(self) -> None:
        self.seed()
        self.land("feature", [("a.txt", "x\n", "add a")], hours_later=1)
        self.land("fix-it", [("a.txt", "y\n", "fix: a")], hours_later=2)
        env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull}
        script = Path(refix_report.__file__)
        text = subprocess.run(
            [sys.executable, str(script), "main", "--repo", str(self.repo)],
            check=True, capture_output=True, text=True, env=env,
        ).stdout
        self.assertIn("upper bound", text)
        data = json.loads(
            subprocess.run(
                [sys.executable, str(script), "main", "--repo", str(self.repo), "--json"],
                check=True, capture_output=True, text=True, env=env,
            ).stdout
        )
        self.assertEqual(data["totals"]["another_pull_request"], 1)
        self.assertEqual(data["pairs"][0]["earlier_subject"], "add a")
        helped = subprocess.run(
            [sys.executable, str(script), "--help"], check=True, capture_output=True, text=True
        ).stdout
        self.assertIn("upper bound", " ".join(helped.split()))


if __name__ == "__main__":
    unittest.main()
