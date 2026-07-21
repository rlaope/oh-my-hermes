from __future__ import annotations

import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _local_package import load_local_package

load_local_package()
from omh.local_store import (
    FileLockTimeout,
    atomic_write_text,
    file_lock,
    locked_json_update,
    read_json_object,
)

try:
    import fcntl as _fcntl

    HAS_FCNTL = True
except ImportError:
    HAS_FCNTL = False


class LocalStoreLockingTests(unittest.TestCase):
    def test_concurrent_locked_updates_do_not_lose_writes(self) -> None:
        worker_count = 24
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            barrier = threading.Barrier(worker_count)

            def worker(index: int) -> None:
                barrier.wait()
                locked_json_update(path, lambda current: {**current, f"key-{index}": index}, default={})

            threads = [threading.Thread(target=worker, args=(index,)) for index in range(worker_count)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            final = read_json_object(path)
            self.assertIsNotNone(final)
            assert final is not None
            for index in range(worker_count):
                self.assertEqual(final.get(f"key-{index}"), index)

    def test_concurrent_atomic_writes_do_not_collide_on_temp_file(self) -> None:
        writer_count = 24
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "target.json"
            barrier = threading.Barrier(writer_count)
            errors: list[BaseException] = []

            def writer(index: int) -> None:
                barrier.wait()
                try:
                    atomic_write_text(path, f'{{"writer": {index}}}\n')
                except BaseException as exc:  # noqa: BLE001
                    errors.append(exc)

            threads = [threading.Thread(target=writer, args=(index,)) for index in range(writer_count)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            self.assertEqual(errors, [])
            self.assertTrue(path.exists())
            leftover = list(Path(tmp).glob(".target.json.*.tmp"))
            self.assertEqual(leftover, [])

    @unittest.skipUnless(HAS_FCNTL, "fcntl advisory locking is POSIX-only")
    def test_file_lock_times_out_when_already_held(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "contended.json"
            with file_lock(path, timeout_seconds=5.0) as acquired:
                self.assertTrue(acquired["locked"])
                with self.assertRaises(FileLockTimeout):
                    with file_lock(path, timeout_seconds=0.2, poll_interval=0.01):
                        pass

    @unittest.skipIf(HAS_FCNTL, "degraded no-op path only applies without fcntl")
    def test_file_lock_degrades_gracefully_without_fcntl(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            with file_lock(path, timeout_seconds=0.2) as acquired:
                self.assertFalse(acquired["locked"])
                self.assertEqual(acquired["reason"], "fcntl_unavailable")


if __name__ == "__main__":
    unittest.main()
