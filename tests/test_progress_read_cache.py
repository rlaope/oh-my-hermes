"""The per-turn executor-progress read reuses what it read last turn, and only that.

`pre_llm_call` runs `read_omh_activity` on every turn. It used to open every
run's executor-progress binding, and then the survivors' event and report
logs, every time, so a turn cost grew with the number of runs ever recorded.
The read now remembers each file by its identity (inode, mtime, ctime, size)
and opens only files that changed. These tests pin that it gives exactly the
answer a read that remembers nothing gives, through each kind of change.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from _local_package import load_local_package

load_local_package()

from omh.coding.executor_progress import (  # noqa: E402
    append_progress_event,
    build_progress_binding,
    build_progress_event,
    write_progress_binding,
)
from omh.plugin_bundle.omh import runtime_reader  # noqa: E402
from omh.system.paths import OmhPaths  # noqa: E402


def _strip_clock(payload: dict[str, object]) -> dict[str, object]:
    """The activity payload without `elapsed_seconds`, which is wall-clock time and moves between two reads."""
    def rows(name: str) -> list[dict[str, object]]:
        value = payload[name]
        assert isinstance(value, list)
        return [{k: v for k, v in row.items() if k != "elapsed_seconds"} for row in value]

    return {name: rows(name) for name in ("active_executors", "stale_executors", "latest_progress_events")}


class ProgressReadCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        runtime_reader._progress_read_cache.clear()
        self.addCleanup(runtime_reader._progress_read_cache.clear)
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
        self.now = datetime.now(timezone.utc)
        self.bindings = {}
        for index in range(6):
            self._write(index, age=10 + index)

    def _stamp(self, age: int) -> str:
        return (self.now - timedelta(seconds=age)).isoformat().replace("+00:00", "Z")

    def _write(self, index: int, *, age: int, event: bool = True) -> None:
        binding = build_progress_binding(
            target_type="run", target_id=f"run-{index}", executor_profile="codex", now=self._stamp(age)
        )
        write_progress_binding(self.paths, binding)
        self.bindings[index] = binding
        if event:
            append_progress_event(
                self.paths,
                binding,
                build_progress_event(binding, event_type="executor_dispatched", observed_at=self._stamp(age)),
            )

    def _cached(self) -> dict[str, object]:
        return _strip_clock(runtime_reader.read_omh_activity(self.paths.omh_home, limit=3))

    def _fresh(self) -> dict[str, object]:
        saved = dict(runtime_reader._progress_read_cache)
        runtime_reader._progress_read_cache.clear()
        try:
            return self._cached()
        finally:
            runtime_reader._progress_read_cache.clear()
            runtime_reader._progress_read_cache.update(saved)

    def _opened_binding_files(self) -> int:
        with patch.object(runtime_reader, "_read_json", wraps=runtime_reader._read_json) as reader:
            runtime_reader.read_omh_activity(self.paths.omh_home, limit=3)
        return sum(1 for call in reader.call_args_list if call.args[0].name == "binding.json")

    def test_a_second_read_opens_no_unchanged_binding_or_log(self) -> None:
        first = self._cached()
        with (
            patch.object(runtime_reader, "_read_json", wraps=runtime_reader._read_json) as json_reader,
            patch.object(runtime_reader, "_read_jsonl", wraps=runtime_reader._read_jsonl) as jsonl_reader,
        ):
            second = self._cached()
        self.assertEqual(second, first)
        self.assertEqual([c for c in json_reader.call_args_list if c.args[0].name == "binding.json"], [])
        self.assertEqual(jsonl_reader.call_count, 0)

    def test_every_change_reads_what_a_read_that_remembers_nothing_reads(self) -> None:
        self._cached()
        changes = {
            "a binding rewritten newer": lambda: self._write(4, age=0),
            "an event appended": lambda: append_progress_event(
                self.paths,
                self.bindings[0],
                build_progress_event(self.bindings[0], event_type="progress_observed", observed_at=self._stamp(1)),
            ),
            "a binding removed": lambda: next(self.paths.omh_home.rglob("run-1/executor_progress/binding.json")).unlink(),
            "a new run": lambda: self._write(9, age=2),
            "a binding replaced with junk": lambda: next(
                self.paths.omh_home.rglob("run-2/executor_progress/binding.json")
            ).write_text("{}", encoding="utf-8"),
        }
        for label, change in changes.items():
            with self.subTest(change=label):
                change()
                self.assertEqual(self._cached(), self._fresh())

    def test_a_rewrite_with_the_same_size_and_time_is_still_seen(self) -> None:
        self._cached()
        path = next(self.paths.omh_home.rglob("run-0/executor_progress/binding.json"))
        record = json.loads(path.read_text(encoding="utf-8"))
        before = os.stat(path)
        # The writer replaces the file atomically, so a new version is a new inode even when size and mtime match.
        record["state"] = "closed" if record["state"] != "closed" else "active"
        replacement = path.with_name("binding.json.tmp")
        text = json.dumps(record)
        replacement.write_text(text, encoding="utf-8")
        os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
        os.replace(replacement, path)
        self.assertEqual(self._cached(), self._fresh())

    def test_only_changed_binding_files_are_opened_again(self) -> None:
        self.assertEqual(self._opened_binding_files(), 6)
        self.assertEqual(self._opened_binding_files(), 0)
        self._write(3, age=0, event=False)
        self.assertEqual(self._opened_binding_files(), 1)

    def test_each_runtime_directory_keeps_its_own_memory(self) -> None:
        other = TemporaryDirectory()
        self.addCleanup(other.cleanup)
        other_paths = OmhPaths(omh_home=Path(other.name) / ".omh", hermes_home=Path(other.name) / ".hermes")
        write_progress_binding(
            other_paths, build_progress_binding(target_type="run", target_id="elsewhere", executor_profile="codex",
                                                now=self._stamp(0))
        )
        mine = self._cached()
        theirs = _strip_clock(runtime_reader.read_omh_activity(other_paths.omh_home, limit=3))
        self.assertNotEqual(mine, theirs)
        self.assertEqual(self._cached(), mine)
        self.assertLessEqual(len(runtime_reader._progress_read_cache), runtime_reader._PROGRESS_READ_CACHE_DIRS)

    def test_a_caller_that_rebinds_an_item_key_does_not_reach_the_remembered_item(self) -> None:
        # The projection swaps each item's `binding` for a projected copy. Items handed out are shallow
        # copies, so a key rebound on one -- by the projection or a later reader -- leaves the item the
        # next turn reuses as the files hold it.
        runtime_dir = (self.paths.omh_home / "runtime").resolve()
        for read in range(2):  # the first read stores the items, the second hands out the stored ones
            with self.subTest(read=read):
                handed = runtime_reader._progress_bindings(runtime_dir, limit=3)
                for item in handed:
                    item["binding"] = {"rebound": True}
                    item["latest_event"] = {"rebound": True}
                _bindings, items = runtime_reader._progress_read_cache[runtime_dir]
                self.assertEqual(len(items), 3)
                for progress_dir, (_key, item) in items.items():
                    on_disk = json.loads((progress_dir / "binding.json").read_text(encoding="utf-8"))
                    self.assertEqual(item["binding"], on_disk)
                    self.assertNotIn("rebound", item["latest_event"])


class ChildFilesTests(unittest.TestCase):
    """`_child_files` refuses exactly what a per-candidate `_contains_symlink` check refuses."""

    def test_the_same_files_as_the_per_candidate_check(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "runs"
            for name in ("a", "b", "c", "d"):
                (root / name / "executor_progress").mkdir(parents=True)
                (root / name / "executor_progress" / "binding.json").write_text("{}", encoding="utf-8")
            (root / "e").mkdir()  # no file
            (root / "f" / "executor_progress" / "binding.json").mkdir(parents=True)  # a directory, not a file
            try:
                (root / "b" / "executor_progress" / "binding.json").unlink()
                (root / "b" / "executor_progress" / "binding.json").symlink_to(root / "a" / "executor_progress" / "binding.json")
                (root / "c" / "executor_progress").rename(root / "c" / "real")
                (root / "c" / "executor_progress").symlink_to(root / "c" / "real", target_is_directory=True)
            except OSError:  # no symlink privilege (Windows): the plain cases still run
                pass
            expected = [
                candidate
                for candidate in (root.joinpath(name, "executor_progress", "binding.json") for name in runtime_reader._child_names(root))
                if not runtime_reader._contains_symlink(candidate, root=root) and candidate.is_file()
            ]
            self.assertEqual(runtime_reader._child_files(root, "executor_progress", "binding.json"), expected)

    def test_a_symlinked_root_yields_nothing(self) -> None:
        with TemporaryDirectory() as tmp:
            real = Path(tmp) / "real"
            (real / "a").mkdir(parents=True)
            (real / "a" / "run.json").write_text("{}", encoding="utf-8")
            link = Path(tmp) / "link"
            try:
                link.symlink_to(real, target_is_directory=True)
            except OSError:
                self.skipTest("no symlink privilege")
            self.assertEqual(runtime_reader._child_files(link, "run.json"), [])
            self.assertEqual(runtime_reader._child_files(real, "run.json"), [real / "a" / "run.json"])


if __name__ == "__main__":
    unittest.main()
