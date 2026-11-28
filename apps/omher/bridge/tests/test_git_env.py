"""BOUNDARY rule 10: the bridge's git reads answer for the folder asked, whatever git state omher inherited, and never
fetch. Git variables in the parent environment that point a read at another repository, index, object store,
namespace or config are taken out of the child's environment; a partial clone's missing objects are never fetched."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import omher_bridge as ob  # noqa: E402

ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
       "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
REDIRECTS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY",
             "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS", "GIT_NAMESPACE",
             "GIT_CONFIG_KEY_0", "GIT_CONFIG_VALUE_0", "GIT_CONFIG_KEY_12", "GIT_CONFIG_VALUE_12")


def make_repo(root: Path, name: str, subject: str) -> Path:
    repo = root / name
    repo.mkdir()
    env = {**os.environ, **ENV}
    run = lambda *a: subprocess.run(["git", *a], cwd=repo, check=True, env=env, capture_output=True)
    run("init", "-q", "-b", name)
    (repo / "a.txt").write_text(f"{name}\n", encoding="utf-8")
    run("add", "a.txt")
    run("commit", "-q", "-m", subject)
    return repo


class ChildEnvironment(unittest.TestCase):
    """What `_git` hands its child, without running git."""

    def test_redirecting_keys_are_dropped_and_no_fetch_keys_set(self):
        seen = {}

        def fake_run(argv, **kw):
            seen.update(kw["env"])
            return subprocess.CompletedProcess(argv, 0, stdout="git version 2.55.0\n", stderr="")

        planted = {k: "/elsewhere" for k in REDIRECTS}
        planted.update({"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.fsmonitor", "GIT_CONFIG_VALUE_0": "/x",
                        "GIT_AUTHOR_NAME": "kept", "PATH": os.environ.get("PATH", "")})
        with mock.patch.dict(os.environ, planted), mock.patch.object(ob.subprocess, "run", fake_run):
            ob._git(["version"], ".")
        # a list, not assertNotIn: a failure must not print the whole environment
        self.assertEqual([k for k in REDIRECTS if k in seen], [])
        self.assertEqual(seen["GIT_NO_LAZY_FETCH"], "1")
        self.assertEqual(seen["GIT_ALLOW_PROTOCOL"], "")
        # what _git set before stays, and the rest of the environment is passed on
        self.assertEqual((seen["GIT_OPTIONAL_LOCKS"], seen["GIT_TERMINAL_PROMPT"], seen["GIT_ATTR_NOSYSTEM"]),
                         ("0", "0", "1"))
        self.assertEqual(seen["GIT_AUTHOR_NAME"], "kept")
        self.assertEqual(seen["PATH"], os.environ.get("PATH", ""))

    def test_names_that_only_look_alike_are_kept(self):
        seen = {}

        def fake_run(argv, **kw):
            seen.update(kw["env"])
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

        alike = {"GIT_DIRTY": "1", "MY_GIT_DIR": "1", "GIT_CONFIG_KEY_X": "1", "GIT_CONFIG_GLOBAL": os.devnull}
        with mock.patch.dict(os.environ, alike), mock.patch.object(ob.subprocess, "run", fake_run):
            ob._git(["version"], ".")
        self.assertEqual([k for k in alike if k not in seen], [])


@unittest.skipUnless(shutil.which("git"), "git not installed")
class RealGit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_inherited_git_dir_does_not_redirect_a_read(self):
        asked = make_repo(self.root, "asked", "the asked folder")
        other = make_repo(self.root, "other", "another repository")
        (asked / "a.txt").write_text("changed\n", encoding="utf-8")
        planted = {"GIT_DIR": str(other / ".git"), "GIT_WORK_TREE": str(other),
                   "GIT_INDEX_FILE": str(other / ".git" / "index"), "GIT_CONFIG_COUNT": "1",
                   "GIT_CONFIG_KEY_0": "core.worktree", "GIT_CONFIG_VALUE_0": str(other)}
        with mock.patch.dict(os.environ, planted):
            # the threat is real: a plain git under that environment answers for the other repository
            plain = subprocess.run(["git", "log", "-1", "--format=%s"], cwd=asked, capture_output=True, text=True)
            self.assertEqual(plain.stdout.strip(), "another repository")
            log = ob._git(["log", "-1", "--format=%s"], asked)
            status = ob._git(["status", "--porcelain", "-z", "--ignore-submodules=all"], asked)
            top = ob._git(["rev-parse", "--show-toplevel"], asked)
        self.assertEqual((log or "").strip(), "the asked folder")
        self.assertEqual(ob._status_entries(status or ""), [(" M", "a.txt")])
        self.assertEqual(Path((top or "").strip()).resolve(), asked.resolve())

    def test_partial_clone_read_never_fetches(self):
        """A blob-less clone: `log --patch` needs blobs it does not have. omher's read fails instead of fetching them;
        a plain git, run afterwards, does fetch (so the check would see a fetch)."""
        src = make_repo(self.root, "src", "first")
        env = {**os.environ, **ENV}
        subprocess.run(["git", "config", "uploadpack.allowFilter", "true"], cwd=src, check=True, env=env)
        clone = self.root / "clone"
        subprocess.run(["git", "clone", "-q", "--filter=blob:none", "--no-checkout", src.resolve().as_uri(), str(clone)],
                       check=True, env=env, capture_output=True)
        packs = lambda: sorted(p.name for p in (clone / ".git" / "objects" / "pack").iterdir())
        before = packs()
        self.assertIsNone(ob._git(["log", "-1", "--format=%h", "--patch", "--no-color"], clone))
        self.assertEqual(packs(), before, "omher's read fetched objects")
        plain = subprocess.run(["git", "log", "-1", "--patch", "--no-color"], cwd=clone, env=env, capture_output=True,
                               text=True)
        self.assertIn("+src", plain.stdout)
        self.assertNotEqual(packs(), before)

    def test_transport_refused_even_where_lazy_fetch_is_not_known(self):
        """On a git older than 2.44 GIT_NO_LAZY_FETCH means nothing; the empty protocol allow-list still refuses the
        fetch. Shown here by a plain git with only that one variable."""
        src = make_repo(self.root, "src", "first")
        env = {**os.environ, **ENV}
        subprocess.run(["git", "config", "uploadpack.allowFilter", "true"], cwd=src, check=True, env=env)
        clone = self.root / "clone"
        subprocess.run(["git", "clone", "-q", "--filter=blob:none", "--no-checkout", src.resolve().as_uri(), str(clone)],
                       check=True, env=env, capture_output=True)
        packs = lambda: sorted(p.name for p in (clone / ".git" / "objects" / "pack").iterdir())
        before = packs()
        only = {**env, "GIT_ALLOW_PROTOCOL": ""}
        only.pop("GIT_NO_LAZY_FETCH", None)
        r = subprocess.run(["git", "log", "-1", "--patch", "--no-color"], cwd=clone, env=only, capture_output=True,
                           text=True, stdin=subprocess.DEVNULL)
        self.assertNotIn("+src", r.stdout)
        self.assertEqual(packs(), before)

    def test_every_read_omher_makes_answers_the_same_with_the_scrub(self):
        """The no-fetch keys change no local read: each GIT_READS command omher sends gives the same output with and
        without them, in a plain repository, in a linked worktree (its objects and refs in the main one's .git) and in
        a `git clone --shared` (its objects reached through `objects/info/alternates`, a path, not a transport)."""
        env = {**os.environ, **ENV}
        run = lambda cwd, *a: subprocess.run(["git", *a], cwd=cwd, check=True, env=env, capture_output=True)
        main = make_repo(self.root, "main", "first")
        linked = self.root / "linked"
        run(main, "worktree", "add", "-q", "-b", "side", str(linked))
        shared = self.root / "shared"
        run(self.root, "clone", "-q", "--shared", str(main), str(shared))
        self.assertTrue((shared / ".git" / "objects" / "info" / "alternates").is_file())
        self.assertEqual(sorted(p.name for p in (shared / ".git" / "objects").iterdir() if p.name not in ("info", "pack")), [],
                         "the shared clone holds no objects of its own")
        real_run = subprocess.run

        def without_no_fetch(argv, **kw):
            env = {k: v for k, v in kw["env"].items() if k not in ("GIT_NO_LAZY_FETCH", "GIT_ALLOW_PROTOCOL")}
            return real_run(argv, **{**kw, "env": env})

        reads = [["worktree", "list", "--porcelain"], ["rev-parse", "--path-format=absolute", "--git-common-dir"],
                 ["status", "--porcelain", "-z", "--ignore-submodules=all"], ["diff", "HEAD", *ob._DIFF_FLAGS],
                 ["log", "-1", "--format=%h %s", "--patch", *ob._DIFF_FLAGS], ["version"], ob._FILTER_QUERY]
        for repo in (main, linked, shared):
            (repo / "a.txt").write_text("two\n", encoding="utf-8")
            (repo / "new.txt").write_text("n\n", encoding="utf-8")
            hard = ob._hardened(repo, ob.GIT_TIMEOUT)
            self.assertIsNotNone(hard, repo.name)
            for args in reads:
                with_keys = ob._git(args, repo, ob.GIT_TIMEOUT, hard)
                with mock.patch.object(ob.subprocess, "run", without_no_fetch):
                    without = ob._git(args, repo, ob.GIT_TIMEOUT, hard)
                self.assertIsNotNone(with_keys, (repo.name, args))
                self.assertEqual(with_keys, without, (repo.name, args))
            # and the reads see that repository's own content through its shared objects
            self.assertIn("-main", ob._git(["diff", "HEAD", *ob._DIFF_FLAGS], repo, ob.GIT_TIMEOUT, hard) or "", repo.name)


if __name__ == "__main__":
    unittest.main()
