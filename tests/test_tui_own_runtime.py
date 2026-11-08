"""The TUI's own Hermes runtime home (`omh.tui.own_runtime`): what `build_tui_home` makes from a root home.

The home must carry the root's model, keys and skills and nothing of the bots': copies refreshed only when the
root's file changed, a `.env` with every messaging credential left out, one symlink per skill with the root
winning a name clash (Hermes refuses same-tier duplicates), links removed when their skill goes, and a build on an
unchanged root that writes nothing.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
import unittest

from omh.tui import own_runtime
from omh.tui.own_runtime import (
    MARKER_FILE,
    MARKER_SCHEMA,
    build_tui_home,
    is_messaging_name,
    scrub_env_text,
    served_profile_names,
    tui_home_path,
)

ENV_TEXT = (
    "# keys\n"
    "OPENAI_API_KEY=sk-root\n"
    "export ANTHROPIC_API_KEY=sk-ant\n"
    "DISCORD_BOT_TOKEN=discord-secret\n"
    "SLACK_APP_TOKEN=xapp-secret\n"
    "SLACK_HOME_CHANNEL=C1\n"
    "TERMINAL_TIMEOUT=30\n"
    "\n"
    "HA_TOKEN=ha-secret\n"
)


def _skill(root: Path, name: str, body: str = "body") -> Path:
    directory = root / name
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(f"# {name}\n{body}\n", encoding="utf-8")
    return directory


def _root_home(tmp: Path, served: tuple[str, ...] = ("kami",)) -> Path:
    root = tmp / "hermes"
    root.mkdir()
    (root / "config.yaml").write_text("model:\n  default: claude-opus-5-5\nproviders:\n  og:\n    key: k\n", encoding="utf-8")
    (root / "auth.json").write_text('{"token": "t"}\n', encoding="utf-8")
    (root / ".env").write_text(ENV_TEXT, encoding="utf-8")
    (root / "SOUL.md").write_text("soul\n", encoding="utf-8")
    for name in ("apple", "web", "hyperframes"):
        _skill(root / "skills", name, "root")
    for profile in served:
        for name in ("apple", "web", "sionic-onprem-gpu"):
            _skill(root / "profiles" / profile / "skills", name, profile)
    (root / "plugins" / "omh").mkdir(parents=True)
    (root / "plugins" / "omh" / "__init__.py").write_text("", encoding="utf-8")
    (root / "plugins" / "homeassistant").mkdir()
    return root


class ScrubTests(unittest.TestCase):
    def test_messaging_names_are_recognised_by_their_parts(self) -> None:
        for name in ("DISCORD_BOT_TOKEN", "SLACK_APP_TOKEN", "slack_home_channel", "TELEGRAM_BOT_TOKEN", "HA_TOKEN",
                     "FEISHU_APP_SECRET", "MSGRAPH_WEBHOOK_SECRET"):
            self.assertTrue(is_messaging_name(name), name)
        for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "TERMINAL_TIMEOUT", "HERMES_HOME", "OG_API_KEY"):
            self.assertFalse(is_messaging_name(name), name)

    def test_scrubbing_keeps_keys_comments_and_blank_lines_and_names_what_it_left_out(self) -> None:
        text, scrubbed = scrub_env_text(ENV_TEXT)
        self.assertEqual(scrubbed, ("DISCORD_BOT_TOKEN", "SLACK_APP_TOKEN", "SLACK_HOME_CHANNEL", "HA_TOKEN"))
        self.assertEqual(text, "# keys\nOPENAI_API_KEY=sk-root\nexport ANTHROPIC_API_KEY=sk-ant\nTERMINAL_TIMEOUT=30\n\n")
        self.assertEqual(scrub_env_text(""), ("", ()))


class BuildTests(unittest.TestCase):
    def test_the_home_carries_the_root_s_files_and_skills_with_no_messaging_secret(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _root_home(Path(tmp))
            omh_home = Path(tmp) / "omh"
            omh_home.mkdir()
            built = build_tui_home(omh_home, root, served=("kami",))
            home = tui_home_path(omh_home)
            self.assertEqual(built.path, home)
            if os.name == "posix":  # Windows reports its own modes for a chmod (CLAUDE.md, platform facts)
                self.assertEqual(stat.S_IMODE(home.stat().st_mode), 0o700)
            self.assertEqual((home / "config.yaml").read_text(encoding="utf-8"), (root / "config.yaml").read_text(encoding="utf-8"))
            self.assertEqual((home / "auth.json").read_text(encoding="utf-8"), (root / "auth.json").read_text(encoding="utf-8"))
            for name in ("config.yaml", "auth.json", ".env"):
                if os.name == "posix":
                    self.assertEqual(stat.S_IMODE((home / name).stat().st_mode), 0o600, name)
            env = (home / ".env").read_text(encoding="utf-8")
            self.assertIn("OPENAI_API_KEY=sk-root", env)
            self.assertNotIn("discord-secret", env)
            self.assertNotIn("xapp-secret", env)
            self.assertNotIn("ha-secret", env)
            self.assertEqual(built.scrubbed, ("DISCORD_BOT_TOKEN", "SLACK_APP_TOKEN", "SLACK_HOME_CHANNEL", "HA_TOKEN"))
            self.assertTrue((home / "SOUL.md").is_symlink())
            self.assertEqual(os.readlink(home / "plugins" / "omh"), str(root / "plugins" / "omh"))
            self.assertFalse((home / "plugins" / "homeassistant").exists())  # a bot-side plugin is not the TUI's
            # The union: the root's three, kami's one of its own; the two shared names are the root's copies.
            self.assertEqual(built.skills, ("apple", "hyperframes", "sionic-onprem-gpu", "web"))
            self.assertEqual(built.clashes, (("apple", "kami"), ("web", "kami")))
            self.assertEqual(os.readlink(home / "skills" / "apple"), str(root / "skills" / "apple"))
            self.assertEqual(os.readlink(home / "skills" / "sionic-onprem-gpu"),
                             str(root / "profiles" / "kami" / "skills" / "sionic-onprem-gpu"))
            self.assertEqual((home / "skills" / "apple" / "SKILL.md").read_text(encoding="utf-8"), "# apple\nroot\n")
            marker = json.loads((home / MARKER_FILE).read_text(encoding="utf-8"))
            self.assertEqual(marker["schema_version"], MARKER_SCHEMA)
            self.assertEqual((marker["root"], marker["served"], marker["skills"]),
                             (str(root), ["kami"], list(built.skills)))
            self.assertEqual(marker["clashes"], [["apple", "kami"], ["web", "kami"]])

    def test_a_second_build_on_an_unchanged_root_writes_nothing(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _root_home(Path(tmp))
            omh_home = Path(tmp) / "omh"
            omh_home.mkdir()
            first = build_tui_home(omh_home, root, served=("kami",))
            self.assertEqual(set(first.refreshed), {"config.yaml", "auth.json", ".env", "SOUL.md", "plugins/omh",
                                                    *(f"skills/{name}" for name in first.skills)})
            home = tui_home_path(omh_home)
            before = {p: p.lstat().st_mtime_ns for p in home.rglob("*") if p.name != MARKER_FILE}
            second = build_tui_home(omh_home, root, served=("kami",))
            self.assertEqual(second.refreshed, ())
            self.assertEqual({p: p.lstat().st_mtime_ns for p in home.rglob("*") if p.name != MARKER_FILE}, before)

    def test_a_changed_root_file_is_copied_again_and_a_gone_skill_s_link_is_removed(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _root_home(Path(tmp))
            omh_home = Path(tmp) / "omh"
            omh_home.mkdir()
            build_tui_home(omh_home, root, served=("kami",))
            home = tui_home_path(omh_home)
            (root / "config.yaml").write_text("model:\n  default: claude-sonnet-5-5\n", encoding="utf-8")
            os.utime(root / "config.yaml", ns=(1, 2_000_000_000))  # any different stamp: the size changed too
            (root / ".env").write_text("OPENAI_API_KEY=sk-new\nDISCORD_BOT_TOKEN=again\n", encoding="utf-8")
            import shutil
            shutil.rmtree(root / "skills" / "hyperframes")
            _skill(root / "profiles" / "kami" / "skills", "new-bot-skill", "kami")
            built = build_tui_home(omh_home, root, served=("kami",))
            self.assertEqual((home / "config.yaml").read_text(encoding="utf-8"), "model:\n  default: claude-sonnet-5-5\n")
            self.assertEqual((home / ".env").read_text(encoding="utf-8"), "OPENAI_API_KEY=sk-new\n")
            self.assertFalse((home / "skills" / "hyperframes").exists())
            self.assertFalse((home / "skills" / "hyperframes").is_symlink())
            self.assertTrue((home / "skills" / "new-bot-skill").is_symlink())
            self.assertIn("skills/hyperframes (removed)", built.refreshed)
            self.assertIn("skills/new-bot-skill", built.refreshed)
            self.assertIn("config.yaml", built.refreshed)
            self.assertIn(".env", built.refreshed)
            self.assertNotIn("auth.json", built.refreshed)

    def test_a_real_directory_the_person_put_in_skills_is_left_alone_and_keeps_its_name(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _root_home(Path(tmp))
            omh_home = Path(tmp) / "omh"
            omh_home.mkdir()
            home = tui_home_path(omh_home)
            _skill(home / "skills", "apple", "mine")
            built = build_tui_home(omh_home, root, served=("kami",))
            self.assertFalse((home / "skills" / "apple").is_symlink())
            self.assertEqual((home / "skills" / "apple" / "SKILL.md").read_text(encoding="utf-8"), "# apple\nmine\n")
            self.assertEqual(built.kept_local, ("apple",))
            self.assertIn("apple", built.skills)

    def test_served_profiles_come_from_the_gateway_record_else_from_the_profiles_directory(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _root_home(Path(tmp), served=("kami", "zeta"))
            self.assertEqual(served_profile_names(root), ("kami", "zeta"))
            (root / "gateway_state.json").write_text(json.dumps({
                "pid": 1, "gateway_state": "running", "served_profiles": ["default", "zeta"],
            }), encoding="utf-8")
            self.assertEqual(served_profile_names(root), ("zeta",))

    def test_a_root_without_the_optional_files_still_builds(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "hermes"
            (root / "skills").mkdir(parents=True)
            (root / "config.yaml").write_text("model: {}\n", encoding="utf-8")
            omh_home = Path(tmp) / "omh"
            omh_home.mkdir()
            built = build_tui_home(omh_home, root, served=())
            home = tui_home_path(omh_home)
            self.assertTrue((home / "config.yaml").is_file())
            for name in (".env", "auth.json", "SOUL.md"):
                self.assertFalse((home / name).exists(), name)
            self.assertFalse((home / "plugins" / "omh").exists())
            self.assertEqual((built.skills, built.scrubbed, built.served), ((), (), ()))

    def test_the_home_sits_under_the_omh_home(self) -> None:
        self.assertEqual(tui_home_path(Path("/o")), Path("/o") / own_runtime.TUI_HOME_DIR)


if __name__ == "__main__":
    unittest.main()
