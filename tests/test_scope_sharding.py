"""Tests for tools/test_sharding/scope.py: the omher-only pull-request slice."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
PLAN_PY = REPO_ROOT / "tools" / "test_sharding" / "plan.py"

sys.path.insert(0, str(REPO_ROOT))

from tools.test_sharding import plan as plan_mod  # noqa: E402
from tools.test_sharding import scope as scope_mod  # noqa: E402

_MODULE = (
    "import unittest\n"
    "{marker}\n"
    "class Test{name}(unittest.TestCase):\n"
    "    def test_one(self):\n"
    "        pass\n"
)


def _fixture(root: Path) -> None:
    (root / "test_app.py").write_text(_MODULE.format(marker="# reads apps/omher/src", name="App"), encoding="utf-8")
    (root / "test_notes.py").write_text(_MODULE.format(marker="# reads CHANGELOG.md", name="Notes"), encoding="utf-8")
    (root / "test_walk.py").write_text(_MODULE.format(marker="# for p in REPO_ROOT.rglob('*')", name="Walk"), encoding="utf-8")
    (root / "test_core.py").write_text(_MODULE.format(marker="# routing only", name="Core"), encoding="utf-8")


def _plan(root: Path, out: Path, changed: list[str] | None, quarantine: tuple[str, ...] = ()) -> subprocess.CompletedProcess[str]:
    timings = root / "timings.json"
    timings.write_text(json.dumps({"version": 1, "durations": {}}), encoding="utf-8")
    entries = [{"match": m, "owner": "@rlaope", "reason": "fixture", "added": "2026-11-25"} for m in quarantine]
    (root / "quarantine.json").write_text(json.dumps({"version": 1, "entries": entries}), encoding="utf-8")
    args = [sys.executable, str(PLAN_PY), "--shards", "2", "--durations", str(timings),
            "--quarantine", str(root / "quarantine.json"), "--out", str(out), "--start-dir", str(root)]
    if changed is not None:
        (root / "changed.txt").write_text("\n".join(changed) + "\n", encoding="utf-8")
        args += ["--changed-paths", str(root / "changed.txt")]
    return subprocess.run(args, cwd=REPO_ROOT, capture_output=True, text=True, timeout=60, check=False)


def _modules(out: Path) -> set[str]:
    payload = json.loads(out.read_text(encoding="utf-8"))
    ids = [test_id for shard in payload["shards"].values() for test_id in shard] + payload["quarantine"]
    return {test_id.split(".", 1)[0] for test_id in ids}


class ChangeScopeTests(unittest.TestCase):
    def test_only_an_omher_only_change_is_narrowed(self) -> None:
        self.assertEqual(scope_mod.change_scope(("apps/omher/src/App.tsx",)), scope_mod.OMHER_SCOPE)
        self.assertEqual(scope_mod.change_scope(("apps/omher/a.ts", "CHANGELOG.md")), scope_mod.OMHER_SCOPE)
        for paths in (
            (),
            ("CHANGELOG.md", "src/cli.py"),
            ("apps/omher/a.ts", ".github/workflows/ci.yml"),
            ("apps/omherx/a.ts",),
            ("tools/test_sharding/scope.py",),
            ("tests/test_omher_boundary.py",),
        ):
            with self.subTest(paths=paths):
                self.assertEqual(scope_mod.change_scope(paths), scope_mod.FULL_SCOPE)

    def test_changed_paths_file_ignores_blanks_and_normalizes_separators(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "changed.txt"
            path.write_text("apps\\omher\\a.ts\n\n  CHANGELOG.md  \n", encoding="utf-8")
            self.assertEqual(scope_mod.read_changed_paths(path), ("apps/omher/a.ts", "CHANGELOG.md"))


class ScopedPlanTests(unittest.TestCase):
    def test_omher_only_change_plans_the_relevant_modules(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _fixture(root)
            result = _plan(root, root / "plan.json", ["apps/omher/src/App.tsx"])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("scope=omher", result.stdout)
            self.assertEqual(_modules(root / "plan.json"), {"test_app", "test_notes", "test_walk"})

    def test_any_other_change_and_no_change_file_plan_everything(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _fixture(root)
            everything = {"test_app", "test_notes", "test_walk", "test_core"}
            for changed in (["apps/omher/a.ts", "src/cli.py"], [], None):
                with self.subTest(changed=changed):
                    result = _plan(root, root / "plan.json", changed)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn("scope=full", result.stdout)
                    self.assertEqual(_modules(root / "plan.json"), everything)

    def test_quarantine_outside_the_slice_is_dropped_but_a_stale_entry_still_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _fixture(root)
            result = _plan(root, root / "plan.json", ["apps/omher/a.ts"], quarantine=("test_core", "test_app"))
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads((root / "plan.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["quarantine"], ["test_app.TestApp.test_one"])
            stale = _plan(root, root / "plan.json", ["apps/omher/a.ts"], quarantine=("test_gone",))
            self.assertNotEqual(stale.returncode, 0)
            self.assertIn("stale quarantine entry", stale.stderr)

    def test_the_real_slice_holds_the_omher_and_whole_tree_audits(self) -> None:
        modules = scope_mod.scoped_modules(REPO_ROOT / "tests")
        for name in ("test_omher_boundary", "test_omher_linux_build_deps", "test_release_changelog",
                     "test_identifier_guard", "test_credential_fixture_policy"):
            with self.subTest(module=name):
                self.assertIn(name, modules)
        self.assertNotIn("test_routing_precision", modules)
        self.assertIn("test_scope_sharding", modules)

    def test_scoped_inputs_fall_back_to_full_when_the_slice_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "test_core.py").write_text(_MODULE.format(marker="", name="Core"), encoding="utf-8")
            inputs = plan_mod.PlanningInputs(("test_core.TestCore.test_one",), {}, ())
            scope, scoped = plan_mod.scoped_inputs(inputs, ("apps/omher/a.ts",), root)
            self.assertEqual(scope, scope_mod.FULL_SCOPE)
            self.assertEqual(scoped, inputs)


if __name__ == "__main__":
    unittest.main()
