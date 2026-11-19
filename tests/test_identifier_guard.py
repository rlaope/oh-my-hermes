"""The private identifier guard flags hashed names, and refuses to pass when it cannot look."""
from __future__ import annotations

import contextlib
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/qa"))

import identifier_guard as guard  # noqa: E402

# Invented names: the test must not carry a real private identifier either.
NAME = "quartz heron"
THREE = "amber quartz heron"
OTHER = "marble finch"


class GuardCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / "tools/qa").mkdir(parents=True)
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)

    def denylist(self, *names: str, raw: str | None = None) -> None:
        body = raw if raw is not None else "# comment\n" + "".join(guard.hash_line(n) + "\n" for n in names)
        (self.root / guard.DENYLIST).write_text(body, encoding="utf-8")

    def track(self, name: str, content: bytes | str) -> None:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if isinstance(content, bytes) else content.encode())
        subprocess.run(["git", "add", name], cwd=self.root, check=True)

    def scan(self, **kwargs: object) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = guard.run(self.root, **kwargs)  # type: ignore[arg-type]
        return code, out.getvalue(), err.getvalue()


class ScanTests(GuardCase):
    def test_hit_reports_path_line_and_hash(self) -> None:
        self.denylist(NAME)
        self.track("doc.md", f"first\nsecond mentions {NAME} here\n")
        code, out, _ = self.scan()
        self.assertEqual(code, 1)
        self.assertIn(f"doc.md:2: private identifier hash {guard.hash_line(NAME)}", out)

    def test_miss_is_clean(self) -> None:
        self.denylist(NAME)
        self.track("doc.md", f"nothing about {OTHER} or quartz alone\n")
        self.assertEqual(self.scan()[0], 0)

    def test_hyphen_space_and_joined_forms_match_one_entry(self) -> None:
        self.denylist(NAME)
        for form in ("quartz-heron", "Quartz  Heron", "QUARTZHERON", "quartz_heron"):
            with self.subTest(form=form):
                self.track("doc.md", f"x {form} y\n")
                self.assertEqual(self.scan()[0], 1)

    def test_three_word_shingle(self) -> None:
        self.denylist(THREE)
        self.track("doc.md", "see Amber-Quartz-Heron now\n")
        self.assertEqual(self.scan()[0], 1)

    def test_binary_is_skipped_by_extension_and_by_nul(self) -> None:
        self.denylist(NAME)
        self.track("logo.png", NAME.encode())
        self.track("blob.dat", b"\0\0" + NAME.encode())
        code, out, _ = self.scan()
        self.assertEqual(code, 0, out)

    def test_staged_scans_the_index_not_the_working_tree(self) -> None:
        self.denylist(NAME)
        self.track("doc.md", f"{NAME}\n")
        (self.root / "doc.md").write_text("clean now\n", encoding="utf-8")
        self.assertEqual(self.scan(staged=True)[0], 1)
        self.assertEqual(self.scan()[0], 0)

    def test_explicit_paths(self) -> None:
        self.denylist(NAME)
        self.track("a.md", "clean\n")
        self.track("b.md", f"{NAME}\n")
        self.assertEqual(self.scan(paths=["a.md"])[0], 0)
        self.assertEqual(self.scan(paths=["b.md"])[0], 1)
        self.assertEqual(self.scan(paths=["missing.md"])[0], 2)

    def test_local_override_is_hashed_at_runtime(self) -> None:
        self.denylist(OTHER)
        (self.root / guard.LOCAL_OVERRIDE).write_text(f"# mine\n{NAME}\n", encoding="utf-8")
        self.track("doc.md", f"{NAME}\n")
        self.assertEqual(self.scan()[0], 1)

    def test_output_never_contains_plaintext(self) -> None:
        self.denylist(NAME)
        (self.root / guard.LOCAL_OVERRIDE).write_text(f"{OTHER}\n", encoding="utf-8")
        self.track("doc.md", f"{NAME} and {OTHER}\n")
        code, out, err = self.scan()
        self.assertEqual(code, 1)
        for text in (out, err):
            for name in (NAME, OTHER, "quartz", "heron", "marble", "finch"):
                self.assertNotIn(name, text.lower())

    def assert_no_plaintext(self, *texts: str) -> None:
        for text in texts:
            for word in ("quartz", "heron"):
                self.assertNotIn(word, text.lower())

    def test_path_and_content_hit_never_prints_the_path(self) -> None:
        self.denylist(NAME)
        self.track("notes/quartz-heron.md", f"{NAME}\n")
        code, out, err = self.scan()
        self.assertEqual(code, 1)
        self.assert_no_plaintext(out, err)
        self.assertIn("<redacted path #1>", out)
        self.assertIn(f"<redacted path #1>:1: private identifier hash {guard.hash_line(NAME)}", out)

    def test_path_only_hit_fails(self) -> None:
        self.denylist(NAME)
        self.track("a.md", "clean\n")
        self.track("b/Quartz_Heron.md", "clean\n")
        code, out, err = self.scan()
        self.assertEqual(code, 1)
        self.assert_no_plaintext(out, err)
        self.assertIn(f"<redacted path #2> (hash {guard.hash_line(NAME)})", out)

    def test_path_hit_in_binary_file_fails(self) -> None:
        self.denylist(NAME)
        self.track("quartzheron.png", b"\0")
        code, out, err = self.scan()
        self.assertEqual(code, 1)
        self.assert_no_plaintext(out, err)

    def test_staged_and_explicit_modes_check_paths(self) -> None:
        self.denylist(NAME)
        self.track("quartz-heron.md", "clean\n")
        for kwargs in ({"staged": True}, {"paths": ["quartz-heron.md"]}):
            with self.subTest(**kwargs):
                code, out, err = self.scan(**kwargs)
                self.assertEqual(code, 1)
                self.assert_no_plaintext(out, err)

    def test_unreadable_explicit_path_is_redacted(self) -> None:
        self.denylist(NAME)
        code, out, err = self.scan(paths=["quartz-heron.md"])
        self.assertEqual(code, 2)
        self.assert_no_plaintext(out, err)


class FailClosedTests(GuardCase):
    def test_missing_denylist_exits_2(self) -> None:
        self.track("doc.md", "clean\n")
        code, _, err = self.scan()
        self.assertEqual(code, 2)
        self.assertIn("denylist missing", err)

    def test_empty_denylist_exits_2(self) -> None:
        self.denylist(raw="# only a comment\n\n")
        code, _, err = self.scan()
        self.assertEqual(code, 2)
        self.assertIn("denylist empty", err)

    def test_malformed_line_exits_2(self) -> None:
        self.denylist(raw="not-a-hash\n")
        self.assertEqual(self.scan()[0], 2)

    def test_local_override_alone_does_not_replace_the_committed_list(self) -> None:
        (self.root / guard.LOCAL_OVERRIDE).write_text(f"{NAME}\n", encoding="utf-8")
        self.assertEqual(self.scan()[0], 2)

    def test_empty_committed_list_fails_even_with_a_local_override(self) -> None:
        self.denylist(raw="# only a comment\n")
        (self.root / guard.LOCAL_OVERRIDE).write_text(f"{NAME}\n", encoding="utf-8")
        self.track("doc.md", "clean\n")
        code, _, err = self.scan()
        self.assertEqual(code, 2)
        self.assertIn("denylist empty", err)

    def test_not_a_git_repo_exits_2(self) -> None:
        with tempfile.TemporaryDirectory() as bare:
            (Path(bare) / "tools/qa").mkdir(parents=True)
            (Path(bare) / guard.DENYLIST).write_text(guard.hash_line(NAME) + "\n", encoding="utf-8")
            code, _, err = self.scan_in(Path(bare))
        self.assertEqual(code, 2)
        self.assertIn("git ls-files failed", err)

    def scan_in(self, root: Path) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = guard.run(root)
        return code, out.getvalue(), err.getvalue()


class CliTests(unittest.TestCase):
    def test_hash_helper_matches_digest(self) -> None:
        done = subprocess.run(
            [sys.executable, str(ROOT / "tools/qa/identifier_guard.py"), "--hash", "  Quartz-Heron "],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(done.returncode, 0)
        self.assertEqual(done.stdout.strip(), guard.digest("quartzheron"))

    def test_hash_helper_rejects_an_entry_the_scanner_cannot_match(self) -> None:
        self.assertEqual(guard.main(["--hash", "a b c d"]), 2)
        self.assertEqual(guard.main(["--hash", "foo.bar"]), 2)

    def test_committed_denylist_is_well_formed(self) -> None:
        self.assertTrue(guard.load_hashes(ROOT))


if __name__ == "__main__":
    unittest.main()
