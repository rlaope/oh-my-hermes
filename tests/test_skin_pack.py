"""The OMH themes: the shipped palettes, the saved choice, and removing old skin files.

The palettes are what the OMH TUI paints with, so the registry and payload
tests pin their shape. Earlier versions installed every theme file into the
Hermes home; the removal tests pin that only a file OMH can prove it wrote
goes, by manifest record (either schema) or by matching the shipped bytes,
and that a file a person wrote stays, record and all.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest

from _legacy_display import seed_legacy_skins
from _platform_support import requires_symlinks
from omh.skin_pack import (
    MANIFEST_FILENAME,
    SKIN_FILENAME,
    SKIN_NAME,
    SKIN_THEMES,
    SkinInstallError,
    available_skins,
    hex_to_rgb,
    is_omh_skin_name,
    skin_colors,
    skin_payload,
    theme_for_name,
    theme_for_skin_name,
    theme_names,
    read_theme_choice,
    theme_store_path,
    uninstall_skin,
    write_theme_choice,
)

_SKINS_DIR = Path(__file__).resolve().parents[1] / "src" / "omh" / "skins"


def _skin_key_paths(text: str) -> list[str]:
    """Top-level and one-level-nested mapping keys, in document order.

    A deliberately tiny reader rather than a YAML dependency: OMH ships with
    zero runtime dependencies and the skin documents are ours, with a fixed
    two-level block-mapping shape. It exists to compare STRUCTURE across
    themes, which is all the parity guard needs.
    """
    paths: list[str] = []
    section = ""
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith("  ") and not line.startswith("    "):
            key, separator, _ = line.strip().partition(":")
            if separator and not key.startswith("- "):
                paths.append(f"{section}.{key}")
        elif not line.startswith(" "):
            key, separator, _ = line.partition(":")
            if separator:
                section = key
                paths.append(key)
    return paths


def _logo_rows(text: str) -> list[str]:
    # No strip: the O and the closing S rows legitimately begin with a
    # space, and eating it is exactly the misalignment this catches. Only the
    # rich markup and the uniform YAML block indent go.
    return [
        re.sub(r"\[[^\]]*\]", "", line).removeprefix("  ")
        for line in text.splitlines()
        if "██" in line or "╚" in line
    ]


class SkinRegistryTests(unittest.TestCase):
    def test_the_registry_matches_the_packaged_skin_files(self) -> None:
        # The registry is the ordered source of truth for the command surface;
        # a YAML added to the package without a registry row would ship a file
        # nobody can select, and a row without a file would crash on install.
        on_disk = {path.name for path in _SKINS_DIR.glob("*.yaml")}
        self.assertEqual({theme.filename for theme in SKIN_THEMES}, on_disk)

    def test_the_shipped_set_is_the_four_named_themes(self) -> None:
        self.assertEqual(available_skins(), ("omh", "omh-amber", "omh-crimson", "omh-mono", "omh-kanagawa-wave"))
        self.assertEqual(theme_names(), ("sky", "amber", "crimson", "mono", "kanagawa-wave"))
        self.assertEqual(SKIN_THEMES[0].skin_name, SKIN_NAME)

    def test_short_names_aliases_and_full_names_all_resolve(self) -> None:
        for value in ("sky", "default", "omh", "SKY", " amber "):
            with self.subTest(value=value):
                self.assertIsNotNone(theme_for_name(value))
        self.assertEqual(theme_for_name("crimson").skin_name, "omh-crimson")
        self.assertEqual(theme_for_name("omh-mono").short_name, "mono")
        self.assertIsNone(theme_for_name("ares"))
        self.assertIsNone(theme_for_name(""))

    def test_a_config_value_resolves_only_by_skin_name(self) -> None:
        # `display.skin: amber` is somebody else's skin, not our amber theme.
        self.assertIsNone(theme_for_skin_name("amber"))
        self.assertEqual(theme_for_skin_name("omh-amber").short_name, "amber")

    def test_ownership_covers_every_shipped_skin_and_nothing_else(self) -> None:
        for name in available_skins():
            with self.subTest(name=name):
                self.assertTrue(is_omh_skin_name(name))
        for name in ("ares", "midnight", "default", "sky", "amber", ""):
            with self.subTest(name=name):
                self.assertFalse(is_omh_skin_name(name))

    def test_every_theme_has_a_payload(self) -> None:
        for theme in SKIN_THEMES:
            with self.subTest(theme=theme.short_name):
                text = skin_payload(theme.skin_name).decode("utf-8")
                self.assertIn(f"name: {theme.skin_name}", text)
        self.assertEqual(skin_payload(), skin_payload(SKIN_NAME))

    def test_an_unknown_payload_name_is_refused(self) -> None:
        with self.assertRaises(SkinInstallError):
            skin_payload("ares")


class SkinPayloadTests(unittest.TestCase):
    def test_the_shipped_skin_carries_the_identity_contract(self) -> None:
        text = skin_payload().decode("utf-8")
        self.assertIn("name: omh", text)
        # The rename is the point: Hermes' banner title and welcome line read
        # OH-MY-HERMES through skin branding alone, never through a patch.
        self.assertIn('agent_name: "OH-MY-HERMES"', text)
        self.assertIn("banner_logo:", text)
        # The palette anchors on the README badge turquoise.
        self.assertIn('"#00CED1"', text)
        # Diff underlays are dark-palette overrides: the engine's light-pastel
        # defaults render as harsh full-brightness bands on a dark terminal.
        self.assertIn('diff_removed: "#3A2027"', text)
        self.assertIn('diff_added: "#12362D"', text)
        self.assertIn("diff_removed_word:", text)
        self.assertIn("diff_added_word:", text)

    def test_every_theme_keeps_the_default_key_structure(self) -> None:
        # The parity guard. A new theme that forgets `status_bar_bg` or a diff
        # underlay renders half-stock chrome, which reads as a broken install
        # rather than a theme; comparing key paths catches it at commit time.
        expected = _skin_key_paths(skin_payload(SKIN_NAME).decode("utf-8"))
        for theme in SKIN_THEMES:
            with self.subTest(theme=theme.short_name):
                self.assertEqual(_skin_key_paths(skin_payload(theme.skin_name).decode("utf-8")), expected)

    def test_every_theme_keeps_the_identity_branding(self) -> None:
        for theme in SKIN_THEMES:
            with self.subTest(theme=theme.short_name):
                text = skin_payload(theme.skin_name).decode("utf-8")
                self.assertIn('agent_name: "OH-MY-HERMES"', text)
                self.assertIn("diff_removed_word:", text)
                self.assertIn("diff_added_word:", text)

    def test_no_theme_declares_a_background_token(self) -> None:
        # Any `background` value that differs from the terminal's own paints
        # every banner text run as a lighter selected-looking box. Omitting it
        # is the invariant, not an oversight, so it holds for every theme.
        for theme in SKIN_THEMES:
            with self.subTest(theme=theme.short_name):
                text = skin_payload(theme.skin_name).decode("utf-8")
                self.assertNotIn("\n  background:", text)

    def test_user_prompt_rows_never_share_the_banner_title_colour(self) -> None:
        # `ui_label` paints the user's own prompt rows in the transcript. When
        # it equals `banner_title` those rows read as more label-coloured
        # chrome and the eye loses the one line it scans for, so every theme
        # keeps the two apart and keeps the label clearly above the dims.
        for theme in SKIN_THEMES:
            with self.subTest(theme=theme.short_name):
                colors = skin_colors(theme.skin_name)
                label = colors["ui_label"]
                self.assertNotEqual(label, colors["banner_title"])
                for dim_token in ("banner_dim", "ui_thinking", "status_bar_dim"):
                    self.assertGreater(
                        sum(hex_to_rgb(label)),
                        sum(hex_to_rgb(colors[dim_token])),
                        f"{theme.short_name}: ui_label must outshine {dim_token}",
                    )

    def test_every_colour_token_is_a_readable_hex(self) -> None:
        for theme in SKIN_THEMES:
            for token, value in skin_colors(theme.skin_name).items():
                with self.subTest(theme=theme.short_name, token=token):
                    self.assertIsNotNone(hex_to_rgb(value))
        self.assertIsNone(hex_to_rgb("#fff"))
        self.assertIsNone(hex_to_rgb("#GGGGGG"))

    def test_the_logo_rows_are_equally_wide_in_every_theme(self) -> None:
        # A block logo with ragged rows renders as visible corruption in the
        # banner; alignment is a contract, not cosmetics. Recolouring the logo
        # by hand is exactly how a row loses a character, so every theme is
        # checked, and every theme against the same width.
        widths: set[int] = set()
        for theme in SKIN_THEMES:
            with self.subTest(theme=theme.short_name):
                rows = _logo_rows(skin_payload(theme.skin_name).decode("utf-8"))
                self.assertEqual(len(rows), 6)
                self.assertEqual(len({len(row) for row in rows}), 1)
                widths.add(len(rows[0]))
        self.assertEqual(len(widths), 1)


class SkinRemovalTests(unittest.TestCase):
    """`uninstall_skin`, which setup, update and uninstall all use on the files earlier versions installed."""

    def _stale_v1_record(self, skins: Path) -> None:
        (skins / MANIFEST_FILENAME).write_text(
            json.dumps(
                {"schema_version": "omh_skin_manifest/v1", "filename": SKIN_FILENAME, "sha256": "1420e408" + "0" * 56}
            ),
            encoding="utf-8",
        )

    def test_every_file_an_earlier_install_wrote_goes_with_its_manifest(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp).resolve()
            seed_legacy_skins(home)
            self.assertEqual(uninstall_skin(home)["status"], "removed")
            for theme in SKIN_THEMES:
                self.assertFalse((home / "skins" / theme.filename).exists())
            self.assertFalse((home / "skins" / MANIFEST_FILENAME).exists())

    def test_a_dry_run_removes_nothing(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp).resolve()
            seed_legacy_skins(home)
            self.assertEqual(uninstall_skin(home, dry_run=True)["status"], "would_remove")
            for theme in SKIN_THEMES:
                self.assertTrue((home / "skins" / theme.filename).is_file())
            self.assertTrue((home / "skins" / MANIFEST_FILENAME).is_file())

    def test_a_v1_manifest_still_proves_ownership_of_the_default_skin(self) -> None:
        # Every machine installed before themes existed carries a v1 manifest,
        # over bytes an older build shipped. Failing to read it would read
        # OMH's own omh.yaml as the person's and leave it behind.
        with TemporaryDirectory() as tmp:
            home = Path(tmp).resolve()
            skins = home / "skins"
            skins.mkdir(parents=True)
            legacy_payload = b"name: omh\n# an older shipped build\n"
            (skins / SKIN_FILENAME).write_bytes(legacy_payload)
            (skins / MANIFEST_FILENAME).write_text(
                json.dumps(
                    {
                        "schema_version": "omh_skin_manifest/v1",
                        "filename": SKIN_FILENAME,
                        "sha256": hashlib.sha256(legacy_payload).hexdigest(),
                    }
                ),
                encoding="utf-8",
            )
            entries = {entry["filename"]: entry["status"] for entry in uninstall_skin(home)["skins"]}
            self.assertEqual(entries[SKIN_FILENAME], "removed")
            self.assertFalse((skins / SKIN_FILENAME).exists())

    def test_our_own_bytes_go_even_under_a_stale_record(self) -> None:
        # Observed on the owner's machine: omh.yaml byte-identical to the
        # shipped template while the v1 manifest still recorded an older sha.
        # Record-only ownership would leave an orphan behind.
        with TemporaryDirectory() as tmp:
            home = Path(tmp).resolve()
            skins = home / "skins"
            skins.mkdir(parents=True)
            (skins / SKIN_FILENAME).write_bytes(skin_payload())
            self._stale_v1_record(skins)
            entries = {entry["filename"]: entry["status"] for entry in uninstall_skin(home)["skins"]}
            self.assertEqual(entries[SKIN_FILENAME], "removed")
            self.assertFalse((skins / SKIN_FILENAME).exists())

    def test_a_genuinely_edited_file_stays(self) -> None:
        # Matching neither the record nor the shipped bytes is what
        # user-authored means.
        with TemporaryDirectory() as tmp:
            home = Path(tmp).resolve()
            skins = home / "skins"
            skins.mkdir(parents=True)
            mine = skin_payload().replace(b"name: omh\n", b"name: omh\n# my own tweak\n")
            (skins / SKIN_FILENAME).write_bytes(mine)
            self._stale_v1_record(skins)
            entries = {entry["filename"]: entry["status"] for entry in uninstall_skin(home)["skins"]}
            self.assertEqual(entries[SKIN_FILENAME], "kept_unmanaged")
            self.assertEqual((skins / SKIN_FILENAME).read_bytes(), mine)

    def test_a_user_authored_file_stays_and_keeps_its_record(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp).resolve()
            seed_legacy_skins(home)
            mine = home / "skins" / "omh-amber.yaml"
            mine.write_text("name: omh-amber\n# mine\n", encoding="utf-8")
            entries = {entry["filename"]: entry["status"] for entry in uninstall_skin(home)["skins"]}
            self.assertEqual(entries["omh-amber.yaml"], "kept_unmanaged")
            self.assertEqual(entries[SKIN_FILENAME], "removed")
            self.assertTrue(mine.exists())
            manifest = json.loads((home / "skins" / MANIFEST_FILENAME).read_text(encoding="utf-8"))
            self.assertEqual(list(manifest["files"]), ["omh-amber.yaml"])
            # A second pass, the next update, decides the same way.
            entries = {entry["filename"]: entry["status"] for entry in uninstall_skin(home)["skins"]}
            self.assertEqual(entries["omh-amber.yaml"], "kept_unmanaged")
            self.assertEqual(entries[SKIN_FILENAME], "absent")

    def test_one_file_of_the_persons_does_not_keep_the_others(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp).resolve()
            seed_legacy_skins(home)
            mine = home / "skins" / "omh-mono.yaml"
            mine.write_text("name: omh-mono\n# mine\n", encoding="utf-8")
            entries = {entry["filename"]: entry["status"] for entry in uninstall_skin(home)["skins"]}
            self.assertEqual(entries["omh-mono.yaml"], "kept_unmanaged")
            self.assertEqual(
                {name: status for name, status in entries.items() if name != "omh-mono.yaml"},
                {theme.filename: "removed" for theme in SKIN_THEMES if theme.filename != "omh-mono.yaml"},
            )

    def test_manifest_only_leaves_our_bytes_without_a_record(self) -> None:
        # After the display release, a copy of the shipped file is the
        # person's; only a manifest record still proves a file OMH's.
        with TemporaryDirectory() as tmp:
            home = Path(tmp).resolve()
            skins = home / "skins"
            skins.mkdir(parents=True)
            (skins / SKIN_FILENAME).write_bytes(skin_payload())
            self._stale_v1_record(skins)
            entries = {entry["filename"]: entry["status"] for entry in uninstall_skin(home, manifest_only=True)["skins"]}
            self.assertEqual(entries[SKIN_FILENAME], "kept_unmanaged")
            self.assertTrue((skins / SKIN_FILENAME).is_file())
            seed_legacy_skins(home)
            entries = {entry["filename"]: entry["status"] for entry in uninstall_skin(home, manifest_only=True)["skins"]}
            self.assertEqual(set(entries.values()), {"removed"})

    def test_the_skin_the_config_still_names_stays_with_its_record(self) -> None:
        # Removing it would leave Hermes naming a skin that is not there.
        with TemporaryDirectory() as tmp:
            home = Path(tmp).resolve()
            seed_legacy_skins(home)
            entries = {
                entry["filename"]: entry["status"] for entry in uninstall_skin(home, keep=("omh-crimson",))["skins"]
            }
            self.assertEqual(entries["omh-crimson.yaml"], "kept_selected")
            self.assertTrue((home / "skins" / "omh-crimson.yaml").is_file())
            self.assertEqual(entries[SKIN_FILENAME], "removed")
            manifest = json.loads((home / "skins" / MANIFEST_FILENAME).read_text(encoding="utf-8"))
            self.assertEqual(list(manifest["files"]), ["omh-crimson.yaml"])
            # Once nothing names it, the record still proves it OMH's.
            entries = {entry["filename"]: entry["status"] for entry in uninstall_skin(home)["skins"]}
            self.assertEqual(entries["omh-crimson.yaml"], "removed")

    @requires_symlinks
    def test_a_symlinked_skins_directory_is_refused_and_its_target_left_alone(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            elsewhere = seed_legacy_skins(root / "elsewhere")
            home = root / "home"
            home.mkdir()
            (home / "skins").symlink_to(elsewhere, target_is_directory=True)
            with self.assertRaises(SkinInstallError):
                uninstall_skin(home)
            self.assertTrue((elsewhere / SKIN_FILENAME).is_file())

    @requires_symlinks
    def test_a_symlinked_skins_directory_with_nothing_of_omhs_is_absent_not_refused(self) -> None:
        # A dotfiles-managed `skins/` holding only the person's skins: there
        # is nothing to remove, so there is nothing to refuse either.
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            elsewhere = root / "dotfiles" / "skins"
            elsewhere.mkdir(parents=True)
            (elsewhere / "ares.yaml").write_text("name: ares\n", encoding="utf-8")
            home = root / "home"
            home.mkdir()
            (home / "skins").symlink_to(elsewhere, target_is_directory=True)

            self.assertEqual(uninstall_skin(home)["status"], "absent")
            self.assertEqual((elsewhere / "ares.yaml").read_text(encoding="utf-8"), "name: ares\n")

    def test_a_clean_home_is_absent(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp).resolve()
            self.assertEqual(uninstall_skin(home)["status"], "absent")


class ThemeStoreTests(unittest.TestCase):
    """The OMH TUI theme choice, saved under the OMH home rather than in Hermes' config."""

    def test_a_saved_theme_reads_back_from_the_omh_home(self) -> None:
        with TemporaryDirectory() as tmp:
            omh_home = Path(tmp) / ".omh"
            crimson = theme_for_name("crimson")
            assert crimson is not None

            path = write_theme_choice(omh_home, crimson)

            self.assertEqual(path, omh_home / "tui" / "theme.json")
            self.assertEqual(theme_store_path(omh_home), path)
            self.assertEqual(read_theme_choice(omh_home), crimson)
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")),
                {"schema_version": "omh_tui_theme/v1", "theme": "crimson"},
            )

    def test_nothing_saved_reads_as_no_choice(self) -> None:
        with TemporaryDirectory() as tmp:
            self.assertIsNone(read_theme_choice(Path(tmp) / ".omh"))

    def test_a_file_this_module_did_not_write_reads_as_no_choice(self) -> None:
        with TemporaryDirectory() as tmp:
            omh_home = Path(tmp) / ".omh"
            path = theme_store_path(omh_home)
            path.parent.mkdir(parents=True)
            for body in (
                "not json",
                json.dumps(["crimson"]),
                json.dumps({"schema_version": "omh_tui_theme/v2", "theme": "crimson"}),
                json.dumps({"schema_version": "omh_tui_theme/v1", "theme": "ares"}),
                json.dumps({"schema_version": "omh_tui_theme/v1", "theme": 7}),
            ):
                with self.subTest(body=body):
                    path.write_text(body, encoding="utf-8")
                    self.assertIsNone(read_theme_choice(omh_home))


if __name__ == "__main__":
    unittest.main()
