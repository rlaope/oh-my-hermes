"""`omh theme runtime own|shared`: where bare `omh` opens its sessions, saved beside the theme.

Pins the command surface: the default report (shared, nothing saved), saving `own` and `shared`, the JSON
payload, a value that is neither, and that the other theme choices survive the write.
"""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from _cli_harness import run_cli
from omh.skin_pack import (
    RUNTIME_OWN,
    RUNTIME_SHARED,
    read_runtime_choice,
    read_update_check_choice,
    theme_store_path,
    write_update_check_choice,
    write_runtime_choice,
)


class ThemeRuntimeCommandTests(unittest.TestCase):
    def _homes(self, tmp: str) -> list[str]:
        root = Path(tmp)
        (root / "hermes").mkdir()
        (root / "omh").mkdir()
        return ["--omh-home", str(root / "omh"), "--hermes-home", str(root / "hermes")]

    def test_nothing_saved_reports_shared_by_default(self) -> None:
        with TemporaryDirectory() as tmp:
            code, out, _ = run_cli([*self._homes(tmp), "theme", "runtime", "--json"])
            payload = json.loads(out)
            self.assertEqual(code, 0)
            self.assertEqual((payload["runtime"], payload["source"], payload["changed"]), (RUNTIME_SHARED, "default", False))
            self.assertEqual(payload["tui_home"], str((Path(tmp) / "omh").resolve() / "tui-home"))
            self.assertFalse(theme_store_path((Path(tmp) / "omh").resolve()).exists())

    def test_own_is_saved_beside_the_other_choices_and_reported_back(self) -> None:
        with TemporaryDirectory() as tmp:
            omh_home = (Path(tmp) / "omh").resolve()
            homes = self._homes(tmp)
            write_update_check_choice(omh_home, False)
            code, out, _ = run_cli([*homes, "theme", "runtime", "own", "--json"])
            payload = json.loads(out)
            self.assertEqual(code, 0)
            self.assertEqual((payload["runtime"], payload["previous"], payload["changed"]), (RUNTIME_OWN, RUNTIME_SHARED, True))
            self.assertEqual(read_runtime_choice(omh_home), RUNTIME_OWN)
            self.assertIs(read_update_check_choice(omh_home), False)  # the other choice survived the write
            code, out, _ = run_cli([*homes, "theme", "runtime", "own", "--json"])
            self.assertEqual((code, json.loads(out)["changed"]), (0, False))
            code, out, _ = run_cli([*homes, "theme", "runtime", "shared", "--json"])
            self.assertEqual((code, json.loads(out)["changed"], read_runtime_choice(omh_home)), (0, True, RUNTIME_SHARED))

    def test_plain_text_names_the_home_and_the_way_back(self) -> None:
        with TemporaryDirectory() as tmp:
            homes = self._homes(tmp)
            code, out, _ = run_cli([*homes, "theme", "runtime", "own"], output_json=False)
            self.assertEqual(code, 0, out)
            self.assertIn("OMH TUI runtime: own", out)
            self.assertIn("tui-home", out)
            self.assertIn("omh theme runtime shared", out)
            code, out, _ = run_cli([*homes, "theme", "runtime"], output_json=False)
            self.assertIn("Saved in", out)

    def test_a_value_that_is_neither_fails_naming_both(self) -> None:
        with TemporaryDirectory() as tmp:
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code, out, _ = run_cli([*self._homes(tmp), "theme", "runtime", "sometimes"], output_json=False)
            self.assertEqual(code, 2)
            said = out + stdout.getvalue()
            self.assertIn("omh theme runtime own", said)
            self.assertIn("omh theme runtime shared", said)
            self.assertIsNone(read_runtime_choice((Path(tmp) / "omh").resolve()))

    def test_the_store_refuses_a_value_it_does_not_know(self) -> None:
        with TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                write_runtime_choice(Path(tmp), "sometimes")


if __name__ == "__main__":
    unittest.main()
