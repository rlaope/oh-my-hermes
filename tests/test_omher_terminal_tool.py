"""Contracts for `omh_omher_terminal`: read an omher terminal's status from its link, and ask omher to type a prompt.

The tool reads one file omher writes (``<terminals>/<link id>.json``) and writes one request file into that
session's inbox. It never types: omher shows the person a card. These tests pin the refusals that keep the tool
inside ``~/.omher/terminals``: a link id that is not 10 base32 characters, a status file or inbox that is a link,
a prompt with control characters.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _local_package import load_local_package

load_local_package()
from omh.plugin_bundle.omh.metadata import PROVIDED_TOOLS, TOOL_FILE_STEMS  # noqa: E402
from omh.plugin_bundle.omh.tools import BUILTIN_TOOL_NAMES  # noqa: E402
from omh.plugin_bundle.omh.tools.omher_terminal_tool import (  # noqa: E402
    OMH_OMHER_TERMINAL_SCHEMA,
    PROMPT_MAX,
    TERMINALS_ENV,
    clean_prompt,
    link_id,
    omh_omher_terminal_handler,
    omher_present,
)

LID = "abcdefgh23"
# The tool answers `unavailable` on Windows before it reads or writes anything (omher does not share terminals there),
# so the tests of what it reads and writes run off Windows only; the faked-win32 test below runs everywhere.
UNIX_ONLY = unittest.skipIf(sys.platform == "win32", "terminal sharing is off on Windows: the tool answers unavailable")
STATUS = {
    "link": f"omher://terminal/{LID}",
    "title": "fix the login redirect",
    "agent": "claude",
    "folder": "~/code/web-app",
    "state": "waiting",
    "started": 1700000000,
    "last_line": "All 42 tests passed",
    "updated_at": 1700000100,
}


class _Home(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="omh-omher-terminal-"))
        self.root = self.tmp / ".omher" / "terminals"
        self.root.mkdir(parents=True)
        patcher = mock.patch.dict(os.environ, {TERMINALS_ENV: str(self.root)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def session(self, lid: str = LID, extra: dict | None = None) -> Path:
        body = dict(STATUS, **(extra or {}))
        with open(self.root / f"{lid}.json", "w", encoding="utf-8", newline="") as handle:
            json.dump(body, handle)
        inbox = self.root / f"{lid}.inbox"
        inbox.mkdir(exist_ok=True)
        return inbox

    def call(self, **args: object) -> dict:
        return json.loads(omh_omher_terminal_handler(dict(args), session_id="sess-1"))


class RegistrationTests(unittest.TestCase):
    def test_the_tool_is_registered_under_its_file_stem(self) -> None:
        self.assertIn("omh_omher_terminal", PROVIDED_TOOLS)
        self.assertIn("omh_omher_terminal", BUILTIN_TOOL_NAMES)
        self.assertEqual(TOOL_FILE_STEMS["omh_omher_terminal"], "omher_terminal_tool")
        self.assertEqual(OMH_OMHER_TERMINAL_SCHEMA["name"], "omh_omher_terminal")
        self.assertEqual(OMH_OMHER_TERMINAL_SCHEMA["parameters"]["properties"]["action"]["enum"], ["status", "send"])

    def test_the_bundle_never_imports_omher(self) -> None:
        src = Path(__file__).resolve().parents[1] / "src" / "plugin_bundle" / "omh" / "tools" / "omher_terminal_tool.py"
        text = src.read_text(encoding="utf-8")
        self.assertNotIn("import omher", text)
        self.assertNotIn("subprocess", text)
        self.assertNotIn("socket", text)


class LinkTests(unittest.TestCase):
    def test_takes_the_link_or_the_bare_id_only(self) -> None:
        self.assertEqual(link_id(f"omher://terminal/{LID}"), LID)
        self.assertEqual(link_id(f" omher://terminal/{LID}/ "), LID)
        self.assertEqual(link_id(LID), LID)
        for bad in (
            "", "abc", "abcdefgh2", "abcdefgh234", "ABCDEFGH23", "abcdefgh01", "../abcdefg", f"{LID}/../x",
            f"omher://terminal/{LID}?x", f"omher://bot/{LID}", f"/tmp/{LID}", "..", None, 12, ["x"],
        ):
            with self.subTest(bad=bad):
                self.assertIsNone(link_id(bad))

    def test_control_characters_go_and_newlines_stay(self) -> None:
        self.assertEqual(clean_prompt("a\x1b[2J b\r\nc\x07\x7f\x9bd\te"), "a[2J b\ncde")


class StatusTests(_Home):
    @UNIX_ONLY
    def test_status_reads_the_listed_fields(self) -> None:
        self.session(extra={"secret": "never shown"})
        got = self.call(action="status", link=f"omher://terminal/{LID}")
        self.assertTrue(got["ok"])
        self.assertEqual(got["status"], STATUS)

    @UNIX_ONLY
    def test_an_unknown_or_malformed_link_reads_nothing(self) -> None:
        self.assertEqual(self.call(action="status", link=LID)["reason"], "not_found")
        self.assertEqual(self.call(action="status", link="../../etc/passwd")["reason"], "bad_link")
        self.assertEqual(self.call(action="status", link="abcdefgh0x")["reason"], "bad_link")

    @unittest.skipIf(os.name == "nt", "symlinks need privileges on Windows")
    def test_a_status_file_that_is_a_link_is_not_followed(self) -> None:
        outside = self.tmp / "outside.json"
        outside.write_text(json.dumps(STATUS), encoding="utf-8")
        os.symlink(outside, self.root / f"{LID}.json")
        self.assertEqual(self.call(action="status", link=LID)["reason"], "not_found")

    def test_the_tool_is_offered_only_where_omher_keeps_its_folder(self) -> None:
        self.assertTrue(omher_present())
        with mock.patch.dict(os.environ, {TERMINALS_ENV: str(self.tmp / "none" / "terminals")}):
            self.assertFalse(omher_present())


class SendTests(_Home):
    @UNIX_ONLY
    def test_send_writes_one_owner_only_request_and_says_it_waits_for_the_person(self) -> None:
        inbox = self.session()
        got = self.call(action="send", link=f"omher://terminal/{LID}", prompt="run the tests\x1b[2J\r\nthen stop")
        self.assertTrue(got["ok"])
        self.assertIn("only if they allow it", got["text"])
        files = sorted(p.name for p in inbox.iterdir())
        self.assertEqual(files, [got["requested"]])
        self.assertTrue(files[0].endswith(".json"))
        body = json.loads((inbox / files[0]).read_text(encoding="utf-8"))
        self.assertEqual(body["prompt"], "run the tests[2J\nthen stop")
        self.assertEqual(body["session"], "sess-1")
        self.assertEqual(sorted(body), ["from", "prompt", "session"])
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE((inbox / files[0]).stat().st_mode), 0o600)

    @UNIX_ONLY
    def test_send_refuses_without_a_session_an_empty_prompt_or_a_long_one(self) -> None:
        self.assertEqual(self.call(action="send", link=LID, prompt="hi")["reason"], "not_found")
        inbox = self.session()
        self.assertEqual(self.call(action="send", link=LID, prompt="\x07\x1b ")["reason"], "no_prompt")
        self.assertEqual(self.call(action="send", link=LID)["reason"], "no_prompt")
        self.assertEqual(self.call(action="send", link=LID, prompt="x" * (PROMPT_MAX + 1))["reason"], "too_long")
        self.assertEqual(self.call(action="type", link=LID, prompt="x")["reason"], "bad_action")
        self.assertEqual(list(inbox.iterdir()), [])

    @unittest.skipIf(os.name == "nt", "symlinks need privileges on Windows")
    def test_send_never_writes_through_a_linked_inbox(self) -> None:
        self.session()
        inbox = self.root / f"{LID}.inbox"
        inbox.rmdir()
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        os.symlink(elsewhere, inbox)
        self.assertEqual(self.call(action="send", link=LID, prompt="x")["reason"], "not_sent")
        self.assertEqual(list(elsewhere.iterdir()), [])

    def test_on_windows_the_tool_reads_and_writes_nothing(self) -> None:
        inbox = self.session()
        with mock.patch("sys.platform", "win32"):
            status = json.loads(omh_omher_terminal_handler({"action": "status", "link": LID}))
            sent = json.loads(omh_omher_terminal_handler({"action": "send", "link": LID, "prompt": "hi"}))
        self.assertEqual(status, {"ok": False, "reason": "unavailable", "text": "not available"})
        self.assertEqual(sent, {"ok": False, "reason": "unavailable", "text": "terminal sharing is not available on Windows"})
        self.assertEqual(list(inbox.iterdir()), [])

    def test_send_never_writes_outside_the_terminals_folder(self) -> None:
        self.session()
        before = sorted(str(p.relative_to(self.tmp)) for p in self.tmp.rglob("*"))
        for bad in ("../x", "../../abcdefgh23", "/abcdefgh23", "abcdefgh23/../../x"):
            self.assertEqual(self.call(action="send", link=bad, prompt="x")["reason"], "bad_link")
        self.assertEqual(sorted(str(p.relative_to(self.tmp)) for p in self.tmp.rglob("*")), before)


if __name__ == "__main__":
    unittest.main()
