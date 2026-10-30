"""`omh theme` -- the user-facing switch for the OMH TUI's shipped palettes.

Themes only matter if a person can pick one without editing a file, so these
tests pin the command surface end to end: what `list` reports, that `use`
saves the choice under the OMH home and writes nothing into the Hermes home,
that `--dry-run` writes nothing, that an invalid name fails loudly with the
valid ones named, and which theme the report says the TUI opens with when
nothing is saved.
"""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from _cli_harness import run_cli

from omh.skin_pack import THEME_STORE_SCHEMA, theme_store_path


class ThemeCommandTests(unittest.TestCase):
    def _homes(self, tmp: str) -> list[str]:
        root = Path(tmp)
        (root / "hermes").mkdir()
        (root / "omh").mkdir()
        return ["--omh-home", str(root / "omh"), "--hermes-home", str(root / "hermes")]

    def _store(self, tmp: str) -> Path:
        # Resolved, as the resolver hands every command its homes (the
        # /private form of a macOS temp directory).
        return theme_store_path((Path(tmp) / "omh").resolve())

    def _hermes_home_entries(self, tmp: str) -> list[str]:
        return sorted(path.name for path in (Path(tmp) / "hermes").iterdir())

    def test_bare_theme_lists_every_shipped_palette(self) -> None:
        with TemporaryDirectory() as tmp:
            status, out, _ = run_cli([*self._homes(tmp), "theme"], output_json=False)
            self.assertEqual(status, 0)
            for name in ("sky", "amber", "crimson", "mono", "kanagawa-wave"):
                self.assertIn(name, out)
            self.assertIn("(default)", out)

    def test_list_json_marks_the_active_theme_and_where_it_came_from(self) -> None:
        with TemporaryDirectory() as tmp:
            homes = self._homes(tmp)
            status, out, _ = run_cli([*homes, "theme", "list"])
            self.assertEqual(status, 0)
            payload = json.loads(out)
            self.assertEqual(payload["schema_version"], "omh_theme_list/v2")
            self.assertEqual(payload["active_theme"], "sky")
            self.assertEqual(payload["active_source"], "default")
            self.assertEqual(payload["store_path"], str(self._store(tmp)))
            self.assertEqual([theme["name"] for theme in payload["themes"]], ["sky", "amber", "crimson", "mono", "kanagawa-wave"])
            run_cli([*homes, "theme", "use", "amber"])
            payload = json.loads(run_cli([*homes, "theme", "list"])[1])
            active = [theme for theme in payload["themes"] if theme["active"]]
            self.assertEqual([theme["name"] for theme in active], ["amber"])
            self.assertEqual(payload["active_source"], "saved")

    def test_the_group_level_json_flag_survives_the_subcommand(self) -> None:
        # argparse resets a group flag from a subparser default unless the
        # subparser suppresses it; `omh theme --json list` must not silently
        # print the human summary to a wrapper expecting JSON.
        with TemporaryDirectory() as tmp:
            status, out, _ = run_cli([*self._homes(tmp), "theme", "--json", "list"], output_json=False)
            self.assertEqual(status, 0)
            self.assertEqual(json.loads(out)["schema_version"], "omh_theme_list/v2")

    def test_use_saves_under_the_omh_home_and_writes_nothing_into_hermes(self) -> None:
        with TemporaryDirectory() as tmp:
            homes = self._homes(tmp)
            status, out, _ = run_cli([*homes, "theme", "use", "crimson"])
            self.assertEqual(status, 0)
            payload = json.loads(out)
            self.assertEqual(payload["schema_version"], "omh_theme_change/v2")
            self.assertEqual(payload["theme"], "crimson")
            self.assertTrue(payload["changed"])
            self.assertEqual(payload["store_path"], str(self._store(tmp)))
            self.assertEqual(
                json.loads(self._store(tmp).read_text(encoding="utf-8")),
                {"schema_version": THEME_STORE_SCHEMA, "theme": "crimson"},
            )
            # No config, no skin files: bare `hermes` keeps its own skin.
            self.assertEqual(self._hermes_home_entries(tmp), [])

    def test_use_accepts_the_full_skin_name_and_the_default_alias(self) -> None:
        with TemporaryDirectory() as tmp:
            homes = self._homes(tmp)
            self.assertEqual(json.loads(run_cli([*homes, "theme", "use", "omh-mono"])[1])["theme"], "mono")
            payload = json.loads(run_cli([*homes, "theme", "use", "default"])[1])
            self.assertEqual(payload["theme"], "sky")
            self.assertEqual(payload["previous_theme"], "mono")
            self.assertEqual(payload["reverse_command"], "omh theme use mono")

    def test_reselecting_the_active_theme_reports_no_change(self) -> None:
        with TemporaryDirectory() as tmp:
            homes = self._homes(tmp)
            run_cli([*homes, "theme", "use", "amber"])
            payload = json.loads(run_cli([*homes, "theme", "use", "amber"])[1])
            self.assertTrue(payload["already_active"])
            self.assertFalse(payload["changed"])

    def test_dry_run_saves_nothing(self) -> None:
        with TemporaryDirectory() as tmp:
            homes = self._homes(tmp)
            payload = json.loads(run_cli([*homes, "theme", "use", "crimson", "--dry-run"])[1])
            self.assertTrue(payload["dry_run"])
            self.assertFalse(payload["changed"])
            self.assertFalse(self._store(tmp).exists())
            self.assertEqual(self._hermes_home_entries(tmp), [])

    def test_glow_off_is_saved_beside_the_theme_and_bare_glow_reports_it(self) -> None:
        with TemporaryDirectory() as tmp:
            homes = self._homes(tmp)
            payload = json.loads(run_cli([*homes, "theme", "glow"])[1])
            self.assertEqual((payload["glow"], payload["source"], payload["changed"]), ("on", "default", False))
            run_cli([*homes, "theme", "use", "amber"])
            status, out, _ = run_cli([*homes, "theme", "glow", "off"])
            self.assertEqual(status, 0)
            payload = json.loads(out)
            self.assertEqual(payload["schema_version"], "omh_theme_glow/v1")
            self.assertEqual((payload["glow"], payload["previous"], payload["changed"]), ("off", "on", True))
            self.assertEqual(
                json.loads(self._store(tmp).read_text(encoding="utf-8")),
                {"schema_version": THEME_STORE_SCHEMA, "theme": "amber", "glow": "off"},
            )
            self.assertFalse(json.loads(run_cli([*homes, "theme", "glow", "off"])[1])["changed"])
            payload = json.loads(run_cli([*homes, "theme", "glow"])[1])
            self.assertEqual((payload["glow"], payload["source"]), ("off", "saved"))
            self.assertEqual(json.loads(run_cli([*homes, "theme", "glow", "on"])[1])["glow"], "on")
            self.assertEqual(self._hermes_home_entries(tmp), [])

    def test_glow_takes_only_on_or_off(self) -> None:
        with TemporaryDirectory() as tmp:
            status, _out, _err = run_cli([*self._homes(tmp), "theme", "glow", "maybe"])
            self.assertNotEqual(status, 0)
            self.assertFalse(self._store(tmp).exists())

    def test_wallpaper_off_is_saved_beside_the_theme_and_glow_and_bare_wallpaper_reports_it(self) -> None:
        with TemporaryDirectory() as tmp:
            homes = self._homes(tmp)
            payload = json.loads(run_cli([*homes, "theme", "wallpaper"])[1])
            self.assertEqual((payload["wallpaper"], payload["source"], payload["changed"]), ("on", "default", False))
            run_cli([*homes, "theme", "use", "amber"])
            run_cli([*homes, "theme", "glow", "off"])
            status, out, _ = run_cli([*homes, "theme", "wallpaper", "off"])
            self.assertEqual(status, 0)
            payload = json.loads(out)
            self.assertEqual(payload["schema_version"], "omh_theme_wallpaper/v1")
            self.assertEqual((payload["wallpaper"], payload["previous"], payload["changed"]), ("off", "on", True))
            self.assertEqual(
                json.loads(self._store(tmp).read_text(encoding="utf-8")),
                {"schema_version": THEME_STORE_SCHEMA, "theme": "amber", "glow": "off", "wallpaper": "off"},
            )
            self.assertFalse(json.loads(run_cli([*homes, "theme", "wallpaper", "off"])[1])["changed"])
            run_cli([*homes, "theme", "glow", "on"])  # a write of another key keeps this one
            payload = json.loads(run_cli([*homes, "theme", "wallpaper"])[1])
            self.assertEqual((payload["wallpaper"], payload["source"]), ("off", "saved"))
            self.assertEqual(json.loads(run_cli([*homes, "theme", "wallpaper", "on"])[1])["wallpaper"], "on")
            self.assertEqual(self._hermes_home_entries(tmp), [])

    def test_bare_wallpaper_in_plain_text_says_it_changes_the_terminals_background(self) -> None:
        with TemporaryDirectory() as tmp:
            status, out, _ = run_cli([*self._homes(tmp), "theme", "wallpaper"], output_json=False)
            self.assertEqual(status, 0)
            self.assertIn("OMH TUI living wallpaper: on", out)
            self.assertIn("Nothing saved; on by default", out)
            self.assertIn("puts the terminal's own back when it exits", out)

    def test_wallpaper_takes_only_on_or_off(self) -> None:
        with TemporaryDirectory() as tmp:
            status, _out, _err = run_cli([*self._homes(tmp), "theme", "wallpaper", "maybe"])
            self.assertNotEqual(status, 0)
            self.assertFalse(self._store(tmp).exists())

    def test_repair_is_retired_and_still_exits_zero(self) -> None:
        with TemporaryDirectory() as tmp:
            homes = self._homes(tmp)
            for argv in (["theme", "repair"], ["theme", "repair", "crimson", "--dry-run"], ["theme", "repair", "--all"]):
                with self.subTest(argv=argv):
                    status, out, err = run_cli([*homes, *argv], output_json=False)
                    self.assertEqual((status, out), (0, ""))
                    self.assertIn("`omh theme repair` is retired", err)
            status, out, _err = run_cli([*homes, "theme", "repair", "--json"])
            self.assertEqual(status, 0)
            payload = json.loads(out)
            self.assertEqual(payload["schema_version"], "omh_theme_repair/v2")
            self.assertTrue(payload["retired"])
            self.assertFalse(payload["changed"])
            self.assertEqual(self._hermes_home_entries(tmp), [])

    def test_an_invalid_name_fails_and_names_the_valid_ones(self) -> None:
        with TemporaryDirectory() as tmp:
            status, out, _ = run_cli([*self._homes(tmp), "theme", "use", "ultraviolet"], output_json=False)
            self.assertEqual(status, 2)
            self.assertIn("ultraviolet", out)
            for name in ("sky", "amber", "crimson", "mono", "kanagawa-wave"):
                self.assertIn(name, out)
            self.assertFalse(self._store(tmp).exists())

    def test_status_reports_the_saved_theme_and_where_it_lives(self) -> None:
        with TemporaryDirectory() as tmp:
            homes = self._homes(tmp)
            run_cli([*homes, "theme", "use", "amber"])
            payload = json.loads(run_cli([*homes, "theme", "status"])[1])
            self.assertEqual(payload["schema_version"], "omh_theme_status/v2")
            self.assertEqual(payload["active_theme"], "amber")
            self.assertEqual(payload["active_source"], "saved")
            self.assertEqual(payload["store_path"], str(self._store(tmp)))
            self.assertIn("`omh`", payload["restart_note"])
            _, out, _ = run_cli([*homes, "theme", "status"], output_json=False)
            self.assertIn(f"Saved in: {self._store(tmp)}", out)

    def test_with_nothing_saved_an_omh_skin_in_hermes_still_decides(self) -> None:
        # The OMH TUI's fallback: an install the display release has not
        # reached yet still names its theme in `display.skin`.
        with TemporaryDirectory() as tmp:
            homes = self._homes(tmp)
            (Path(tmp) / "hermes" / "config.yaml").write_text("display:\n  skin: omh-crimson\n", encoding="utf-8")
            payload = json.loads(run_cli([*homes, "theme", "status"])[1])
            self.assertEqual(payload["active_theme"], "crimson")
            self.assertEqual(payload["active_source"], "hermes_skin")
            _, out, _ = run_cli([*homes, "theme", "status"], output_json=False)
            self.assertIn("no theme saved; Hermes' display.skin names omh-crimson", out)

    def test_a_foreign_skin_is_not_read_as_a_theme_and_is_never_written(self) -> None:
        with TemporaryDirectory() as tmp:
            homes = self._homes(tmp)
            config = Path(tmp) / "hermes" / "config.yaml"
            config.write_text("display:\n  skin: ares\n", encoding="utf-8")
            payload = json.loads(run_cli([*homes, "theme", "status"])[1])
            self.assertEqual(payload["active_theme"], "sky")
            self.assertEqual(payload["active_source"], "default")
            run_cli([*homes, "theme", "use", "mono"])
            self.assertEqual(config.read_text(encoding="utf-8"), "display:\n  skin: ares\n")

    def test_a_profile_that_names_its_own_store_keeps_its_own_theme(self) -> None:
        # #1680: with no `--omh-home`, a Hermes home's own
        # `plugins.entries.omh.settings.omh_home` names its store, so the
        # theme lands there and the primary's store is left alone.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile = root / "hermes" / "profiles" / "bot"
            profile.mkdir(parents=True)
            split = root / "bot-store"
            (profile / "config.yaml").write_text(
                f"plugins:\n  entries:\n    omh:\n      settings:\n        omh_home: {split.as_posix()}\n",
                encoding="utf-8",
            )
            status, out, _ = run_cli(["--hermes-home", str(profile), "theme", "use", "mono"])
            self.assertEqual(status, 0)
            self.assertEqual(Path(json.loads(out)["store_path"]), theme_store_path(split.resolve()))
            self.assertTrue(theme_store_path(split).is_file())
            self.assertFalse(theme_store_path(root / "omh").exists())


if __name__ == "__main__":
    unittest.main()
