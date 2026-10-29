"""Contracts for the outline appended to a truncated read of a large Python file.

Both directions are pinned. The outline must reach a truncated read of a large
Python file the hook can verify on disk, and it must leave every other result
byte-identical: a small read, an untruncated read, another language, a file
that does not parse, and a file whose disk copy disagrees with the result.

The host's result is never re-serialised: the outlined result is the handed
string with one key spliced in before the closing brace, so the assertions
compare prefixes, not re-parsed objects.

``reset_read_outline_records`` clears module-global state in ``setUp`` because
the shard planner reorders tests run to run.
"""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from _local_package import load_local_package

load_local_package()
from omh.plugin_bundle.omh.hooks.result_transforms import transform_tool_result
from omh.plugin_bundle.omh.read_outline import (
    READ_OUTLINE_KEY,
    READ_OUTLINE_MAX_ENTRIES,
    READ_OUTLINE_MIN_LINES,
    annotate_read_outline,
    python_outline,
    read_outline_enabled,
    reset_read_outline_records,
)

SESSION = "20261030_120000_outline"


def _module(functions: int, *, body_lines: int = 8, methods: int = 0) -> str:
    """A parseable module: a docstring, a constant, optional class with methods, then functions."""
    parts = ['"""Synthetic module."""', "", "LIMIT_TABLE = {", "    'a': 1,", "    'b': 2,", "}", ""]
    if methods:
        parts.append("class Ledger:")
        for index in range(methods):
            parts.append(f"    def method_{index}(self, value):")
            parts.extend(f"        value = value + {line}" for line in range(body_lines))
            parts.append("        return value")
            parts.append("")
    for index in range(functions):
        parts.append("")
        parts.append(f"def step_{index}(value):")
        parts.extend(f"    value = value * {line + 2}" for line in range(body_lines))
        parts.append("    return value")
    return "\n".join(parts) + "\n"


def _window(text: str, start: int, count: int) -> str:
    lines = text.removesuffix("\n").split("\n")
    return "\n".join(f"{number}|{lines[number - 1]}" for number in range(start, min(start + count, len(lines) + 1)))


def _read_result(text: str, *, start: int = 1, count: int = 2000, **extra: object) -> str:
    total = text.count("\n") + (0 if text.endswith("\n") else 1)
    body = {
        "content": _window(text, start, count),
        "total_lines": total,
        "file_size": len(text.encode("utf-8")),
        "truncated": total > start + count - 1,
        "hint": f"Use offset={start + count} to continue reading (showing {start}-{start + count - 1} of {total} lines)",
        "is_binary": False,
        "is_image": False,
    }
    body.update(extra)
    return json.dumps(body, ensure_ascii=False)


class ReadOutlineTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_read_outline_records()
        self.addCleanup(reset_read_outline_records)
        patcher = mock.patch.dict(os.environ, {"OMH_READ_OUTLINE": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def _write(self, name: str, text: str) -> str:
        path = self.root / name
        path.write_bytes(text.encode("utf-8"))
        return str(path)

    def _transform(self, path: str, result: str, *, session: str = SESSION, offset: int = 1) -> str | None:
        return transform_tool_result(
            tool_name="read_file",
            args={"path": path, "offset": offset},
            result=result,
            session_id=session,
            task_id="default",
        )

    def test_truncated_read_of_a_large_python_file_gains_the_outline_and_keeps_every_host_byte(self) -> None:
        text = _module(400)
        path = self._write("engine.py", text)
        result = _read_result(text, count=200)

        outlined = self._transform(path, result)

        self.assertIsNotNone(outlined)
        assert outlined is not None
        self.assertTrue(outlined.startswith(result[:-1] + ", "))
        parsed = json.loads(outlined)
        outline = parsed.pop(READ_OUTLINE_KEY)
        self.assertEqual(parsed, json.loads(result))
        self.assertIn("this read returned lines 1-200", outline)
        self.assertIn("offset=<first line>", outline)
        # The last definition's range is on the outline even though it is far past the window.
        last_def = text.removesuffix("\n").split("\n").index("def step_399(value):") + 1
        self.assertIn(f"-{last_def + 9} ", outline + " ")

    def test_small_and_untruncated_reads_are_byte_identical(self) -> None:
        small = _module(5)
        small_path = self._write("small.py", small)
        small_result = _read_result(small)
        self.assertFalse(json.loads(small_result)["truncated"])
        self.assertEqual(annotate_read_outline(tool_name="read_file", args={"path": small_path}, result=small_result), None)
        self.assertIsNone(self._transform(small_path, small_result))

        # Large but read whole: not truncated, so nothing is added.
        whole = _module(150)
        whole_path = self._write("whole.py", whole)
        whole_result = _read_result(whole)
        self.assertGreaterEqual(json.loads(whole_result)["total_lines"], READ_OUTLINE_MIN_LINES)
        self.assertIsNone(self._transform(whole_path, whole_result))

        # Truncated but under the size floor: the rest is one read away.
        short = _module(30)
        short_path = self._write("short.py", short)
        short_result = _read_result(short, count=50)
        self.assertTrue(json.loads(short_result)["truncated"])
        self.assertLess(json.loads(short_result)["total_lines"], READ_OUTLINE_MIN_LINES)
        self.assertIsNone(self._transform(short_path, short_result))

    def test_once_per_file_version_per_session(self) -> None:
        text = _module(400)
        path = self._write("engine.py", text)
        self.assertIsNotNone(self._transform(path, _read_result(text, count=200)))
        self.assertIsNone(self._transform(path, _read_result(text, start=201, count=200), offset=201))
        self.assertIsNotNone(self._transform(path, _read_result(text, count=200), session="other-session"))

        edited = text.replace("def step_10(value):", "def step_10(value, extra=None):")
        Path(path).write_bytes(edited.encode("utf-8"))
        self.assertIsNotNone(self._transform(path, _read_result(edited, count=200)))

    def test_disk_must_agree_with_the_result(self) -> None:
        text = _module(400)
        path = self._write("engine.py", text)
        # A different line count: the file the host read is not this one.
        other = _read_result(text + "extra = 1\n", count=200)
        self.assertIsNone(self._transform(path, other))
        # Same count, but the first returned line differs.
        shifted = text.replace('"""Synthetic module."""', '"""Another module."""')
        self.assertIsNone(self._transform(path, _read_result(shifted, count=200)))
        # A host-clipped long first line still matches by prefix.
        long_line = "# " + "x" * 3000
        clipped_text = long_line + "\n" + text
        clipped_path = self._write("clipped.py", clipped_text)
        result = json.loads(_read_result(clipped_text, count=200))
        result["content"] = result["content"].replace(long_line, long_line[:2000] + "... [truncated]", 1)
        self.assertIsNotNone(self._transform(clipped_path, json.dumps(result, ensure_ascii=False)))

    def test_no_outline_without_a_parser_or_a_resolvable_path(self) -> None:
        text = _module(400)
        go_path = self._write("engine.go", text)
        self.assertIsNone(self._transform(go_path, _read_result(text, count=200)))

        broken = text.replace("def step_3(value):", "def step_3(value:")
        broken_path = self._write("broken.py", broken)
        self.assertIsNone(self._transform(broken_path, _read_result(broken, count=200)))

        # Outside Hermes only an absolute path is unambiguous.
        self.assertIsNone(self._transform("engine.py", _read_result(text, count=200)))
        self.assertIsNone(self._transform(str(self.root / "missing.py"), _read_result(text, count=200)))

    def test_errors_refusals_and_other_tools_pass_through(self) -> None:
        text = _module(400)
        path = self._write("engine.py", text)
        result = _read_result(text, count=200)
        self.assertIsNone(transform_tool_result(tool_name="search_files", args={"path": path}, result=result,
                                                session_id=SESSION))
        refusal = json.dumps({"error": "BLOCKED: already read", "already_read": 4, "truncated": True,
                              "total_lines": 1000, "content": "1|x"})
        self.assertIsNone(self._transform(path, refusal))
        self.assertIsNone(self._transform(path, "not json"))
        with_key = json.dumps({**json.loads(result), READ_OUTLINE_KEY: "earlier"})
        self.assertIsNone(self._transform(path, with_key))

    def test_setting_off_leaves_the_result_alone(self) -> None:
        text = _module(400)
        path = self._write("engine.py", text)
        with mock.patch.dict(os.environ, {"OMH_READ_OUTLINE": "off"}):
            self.assertFalse(read_outline_enabled())
            self.assertIsNone(self._transform(path, _read_result(text, count=200)))

    def test_profile_setting_is_read_when_the_env_is_unset(self) -> None:
        with TemporaryDirectory() as home:
            config = Path(home) / "config.yaml"
            env = {key: value for key, value in os.environ.items() if key != "OMH_READ_OUTLINE"}
            env["HERMES_HOME"] = home
            with mock.patch.dict(os.environ, env, clear=True):
                config.write_text("plugins:\n  entries:\n    omh:\n      settings:\n        read_outline: false\n",
                                  encoding="utf-8")
                self.assertFalse(read_outline_enabled())
                config.write_text("plugins:\n  entries:\n    omh:\n      settings:\n        read_outline: true\n",
                                  encoding="utf-8")
                self.assertTrue(read_outline_enabled())
                config.unlink()
                self.assertTrue(read_outline_enabled())

    def test_cap_keeps_the_whole_file_in_view(self) -> None:
        text = _module(500)
        entries = python_outline(text)
        assert entries is not None
        path = self._write("wide.py", text)
        outlined = self._transform(path, _read_result(text, count=200))
        assert outlined is not None
        outline = json.loads(outlined)[READ_OUTLINE_KEY]
        body = outline.split("\n")[1:]
        self.assertLessEqual(len(body), READ_OUTLINE_MAX_ENTRIES)
        self.assertTrue(all(len(line) <= 100 for line in body))
        # Grouped, the last group still ends on the last definition's last line.
        last_end = max(entry.end for entry in entries)
        self.assertTrue(any(line.split(" ", 1)[0].endswith(f"-{last_end}") for line in body))

    def test_methods_are_listed_under_their_class_until_the_cap(self) -> None:
        text = _module(20, methods=50)
        entries = python_outline(text)
        assert entries is not None
        self.assertEqual(entries[1].label, "class Ledger")
        self.assertEqual(entries[2].label, "def method_0")
        self.assertEqual(entries[2].depth, 1)
        path = self._write("ledger.py", text)
        outlined = self._transform(path, _read_result(text, count=100))
        assert outlined is not None
        outline = json.loads(outlined)[READ_OUTLINE_KEY]
        body = outline.split("\n")[1:]
        self.assertLessEqual(len(body), READ_OUTLINE_MAX_ENTRIES)
        self.assertIn("def step_19", outline)
        self.assertIn("  ", body[2][:2])
        self.assertTrue(body[-1].startswith("("))

    def test_outline_lists_decorated_async_and_constant_definitions(self) -> None:
        text = (
            "import functools\n\nMAX_RETRIES = 3\n__all__ = ['run']\nlower = 1\n\n"
            "@functools.cache\ndef run():\n    return 1\n\n\nasync def fetch():\n    return 2\n"
        )
        entries = python_outline(text)
        assert entries is not None
        labels = [(entry.start, entry.end, entry.label) for entry in entries]
        self.assertEqual(labels, [(3, 3, "MAX_RETRIES"), (4, 4, "__all__"), (7, 9, "def run"), (12, 13, "async def fetch")])
        self.assertIsNone(python_outline("def broken(:\n"))

    def test_splice_keeps_an_earlier_pass_bytes(self) -> None:
        text = _module(400)
        path = self._write("engine.py", text)
        # An earlier pass's key and non-ASCII text, written with ensure_ascii=False.
        earlier = json.loads(_read_result(text, count=200))
        earlier["omh_engagement"] = "plan first — then edit"
        handed = json.dumps(earlier, ensure_ascii=False)
        outlined = annotate_read_outline(tool_name="read_file", args={"path": path}, result=handed, session_id=SESSION)
        assert outlined is not None
        self.assertTrue(outlined.startswith(handed[:-1]))
        self.assertIn("—", outlined)


if __name__ == "__main__":
    unittest.main()
