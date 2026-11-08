"""The TUI's own Hermes runtime home (`omh.tui.own_runtime`): what `build_tui_home` makes from a root home.

The home must carry the root's model, keys and skills and nothing of the bots': copies refreshed only when the
root's file changed (auth.json only when the root's is newer), a `.env` with every messaging credential left out,
one symlink per skill at the skill's own `<category>/<skill>` path with the root winning a name clash (Hermes
refuses same-tier duplicates), links removed when their skill goes while the person's own entries stay, and a
build on an unchanged root that writes nothing. Skills live where Hermes finds them: any directory holding
`SKILL.md`, usually one level under a category.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import stat
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from omh.tui import own_runtime
from omh.tui.own_runtime import (
    MARKER_FILE,
    MARKER_SCHEMA,
    build_tui_home,
    config_platform_credentials,
    is_messaging_name,
    iter_skills,
    scrub_env_text,
    scrub_environment,
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


def _target(path: Path) -> str:
    """Where a link leads, as the file system resolves it: Windows spells a link's own target with its prefix."""
    return os.path.realpath(path)


def _skill(skills: Path, relative: str, body: str = "body") -> Path:
    directory = skills / relative
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(f"# {directory.name}\n{body}\n", encoding="utf-8")
    (directory / "scripts").mkdir()  # a support directory under the skill: never a skill of its own
    (directory / "scripts" / "run.py").write_text("print('x')\n", encoding="utf-8")
    return directory


def _root_home(tmp: Path, served: tuple[str, ...] = ("kami",)) -> Path:
    root = tmp / "hermes"
    root.mkdir()
    (root / "config.yaml").write_text("model:\n  default: claude-opus-5-5\nproviders:\n  og:\n    key: k\n", encoding="utf-8")
    (root / "auth.json").write_text('{"token": "t"}\n', encoding="utf-8")
    (root / ".env").write_text(ENV_TEXT, encoding="utf-8")
    (root / "SOUL.md").write_text("soul\n", encoding="utf-8")
    # The root: two categories and one flat skill.
    for relative in ("devops/sdlc-review", "devops/release", "media/hyperframes", "plan"):
        _skill(root / "skills", relative, "root")
    (root / "skills" / ".archive").mkdir()  # Hermes' own: never a skill
    for profile in served:
        # The profile shares a category and a skill name with the root, and brings two of its own.
        for relative in ("devops/sdlc-review", "devops/og-admin", "software/oh-my-hermes-contribution"):
            _skill(root / "profiles" / profile / "skills", relative, profile)
    (root / "plugins" / "omh").mkdir(parents=True)
    (root / "plugins" / "omh" / "__init__.py").write_text("", encoding="utf-8")
    (root / "plugins" / "homeassistant").mkdir()
    return root


class NameTests(unittest.TestCase):
    def test_messaging_names_match_by_prefix_or_exact_name_never_by_substring(self) -> None:
        for name in ("DISCORD_BOT_TOKEN", "SLACK_APP_TOKEN", "slack_home_channel", "TELEGRAM_BOT_TOKEN", "HA_TOKEN",
                     "FEISHU_APP_SECRET", "MSGRAPH_WEBHOOK_SECRET", "EMAIL_PASSWORD", "IMAP_HOST", "IRC_SERVER",
                     "BLUEBUBBLES_URL", "NTFY_TOKEN", "A2A_BEARER_TOKEN", "QQBOT_SECRET", "SMS_FROM", "API_SERVER_KEY",
                     "PHOTON_URL", "RAFT_TOKEN", "BUZZ_TOKEN", "SIMPLEX_ADDR"):
            self.assertTrue(is_messaging_name(name), name)
        for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "TERMINAL_TIMEOUT", "HERMES_HOME", "OG_API_KEY",
                     "ALPHA_TOKEN", "PIPELINE_URL", "ONLINE_MODE", "CLARK_KEY", "OTEL_SIGNAL_RATE"):
            self.assertFalse(is_messaging_name(name), name)

    def test_scrubbing_keeps_keys_comments_and_blank_lines_and_names_what_it_left_out(self) -> None:
        text, scrubbed = scrub_env_text(ENV_TEXT)
        self.assertEqual(scrubbed, ("DISCORD_BOT_TOKEN", "SLACK_APP_TOKEN", "SLACK_HOME_CHANNEL", "HA_TOKEN"))
        self.assertEqual(text, "# keys\nOPENAI_API_KEY=sk-root\nexport ANTHROPIC_API_KEY=sk-ant\nTERMINAL_TIMEOUT=30\n\n")
        self.assertEqual(scrub_env_text(""), ("", ()))

    def test_a_quoted_value_over_several_lines_goes_whole_with_its_name(self) -> None:
        text, scrubbed = scrub_env_text('A=1\nGOOGLE_CHAT_SA="{\n  \\"key\\": \\"secret\\"\n}"\nB=2\nOK_JSON="{\n}"\n')
        self.assertEqual(scrubbed, ("GOOGLE_CHAT_SA",))
        self.assertEqual(text, 'A=1\nB=2\nOK_JSON="{\n}"\n')

    def test_the_process_environment_is_scrubbed_by_the_same_names(self) -> None:
        kept, scrubbed = scrub_environment({"PATH": "/bin", "TELEGRAM_BOT_TOKEN": "t", "HA_URL": "u", "OPENAI_API_KEY": "k"})
        self.assertEqual((kept, scrubbed), ({"PATH": "/bin", "OPENAI_API_KEY": "k"}, ("HA_URL", "TELEGRAM_BOT_TOKEN")))

    def test_platform_credentials_in_a_config_are_found_without_parsing_yaml(self) -> None:
        text = ("model:\n  default: x\nplatforms:\n  telegram:\n    enabled: true\n    token: 123:abc  # bot\n"
                "  discord:\n    enabled: false\n    streaming: false\n  slack:\n    api_key: ''\n"
                "gateway:\n  token: not-a-platform\n")
        self.assertEqual(config_platform_credentials(text), ("telegram.enabled", "telegram.token"))
        self.assertEqual(config_platform_credentials("platforms: {}\nmodel: {}\n"), ())
        self.assertEqual(config_platform_credentials(""), ())
        # Other YAML shapes: four-space indentation, flow style, a credential under `extra`.
        self.assertEqual(config_platform_credentials("platforms:\n    discord:\n        token: abc\n"), ("discord.token",))
        self.assertEqual(config_platform_credentials("platforms: {discord: {token: abc}}\n"), ("platforms: {discord: {token: abc}}",))
        self.assertEqual(config_platform_credentials("platforms:\n  email:\n    extra:\n      address: a@b\n      password: p\n"),
                         ("email.address", "email.password"))
        self.assertEqual(config_platform_credentials("platforms:\n  discord: false\n  slack: {}\n"), ())


class DiscoveryTests(unittest.TestCase):
    def test_skills_are_directories_holding_skill_md_at_any_depth_without_their_support_dirs(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _root_home(Path(tmp))
            found = dict(iter_skills(root / "skills"))
            self.assertEqual(sorted(found), ["devops/release", "devops/sdlc-review", "media/hyperframes", "plan"])
            self.assertEqual(found["plan"], root / "skills" / "plan")
            self.assertEqual(list(iter_skills(root / "nowhere")), [])

    def test_served_profiles_come_from_a_live_record_else_from_the_profiles_directory(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _root_home(Path(tmp), served=("kami", "zeta"))
            self.assertEqual(served_profile_names(root), ("kami", "zeta"))
            with patch("omh.tui.bot_board.read_gateway") as read_gateway:
                read_gateway.return_value = type("G", (), {"live": True, "served": ("default", "zeta")})()
                self.assertEqual(served_profile_names(root), ("zeta",))
                read_gateway.return_value = type("G", (), {"live": True, "served": ("default",)})()
                self.assertEqual(served_profile_names(root), ())


class BuildTests(unittest.TestCase):
    def test_the_home_carries_the_root_s_files_and_the_skill_union_with_no_messaging_secret(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _root_home(Path(tmp))
            omh_home = Path(tmp) / "omh"
            omh_home.mkdir()
            built = build_tui_home(omh_home, root, served=("kami",))
            home = tui_home_path(omh_home)
            self.assertEqual(built.path, home)
            if os.name == "posix":  # Windows reports its own modes for a chmod (CLAUDE.md, platform facts)
                self.assertEqual(stat.S_IMODE(home.stat().st_mode), 0o700)
                for name in ("config.yaml", "auth.json", ".env"):
                    self.assertEqual(stat.S_IMODE((home / name).stat().st_mode), 0o600, name)
            self.assertEqual((home / "config.yaml").read_bytes(), (root / "config.yaml").read_bytes())
            self.assertEqual((home / "auth.json").read_bytes(), (root / "auth.json").read_bytes())
            env = (home / ".env").read_text(encoding="utf-8")
            self.assertIn("OPENAI_API_KEY=sk-root", env)
            for secret in ("discord-secret", "xapp-secret", "ha-secret"):
                self.assertNotIn(secret, env)
            self.assertEqual(built.scrubbed, ("DISCORD_BOT_TOKEN", "SLACK_APP_TOKEN", "SLACK_HOME_CHANNEL", "HA_TOKEN"))
            self.assertEqual(built.config_platform_credentials, ())
            self.assertTrue((home / "SOUL.md").is_symlink())
            self.assertEqual(_target(home / "plugins" / "omh"), _target(root / "plugins" / "omh"))
            self.assertFalse((home / "plugins" / "homeassistant").exists())  # a bot-side plugin is not the TUI's
            # The union by skill name, at each skill's own path: the root's four, kami's two of its own; kami's
            # copy of sdlc-review lost to the root's.
            self.assertEqual(built.skills, ("devops/og-admin", "devops/release", "devops/sdlc-review", "media/hyperframes",
                                            "plan", "software/oh-my-hermes-contribution"))
            self.assertEqual(built.clashes, (("devops/sdlc-review", "kami"),))
            self.assertFalse((home / "skills" / "devops").is_symlink())  # a category is a real directory
            self.assertEqual(_target(home / "skills" / "devops" / "sdlc-review"), _target(root / "skills" / "devops" / "sdlc-review"))
            self.assertEqual(_target(home / "skills" / "devops" / "og-admin"),
                             _target(root / "profiles" / "kami" / "skills" / "devops" / "og-admin"))
            self.assertEqual((home / "skills" / "devops" / "sdlc-review" / "SKILL.md").read_text(encoding="utf-8"),
                             "# sdlc-review\nroot\n")
            self.assertFalse((home / "skills" / ".archive").exists())
            marker = json.loads((home / MARKER_FILE).read_text(encoding="utf-8"))
            self.assertEqual(marker["schema_version"], MARKER_SCHEMA)
            self.assertEqual((marker["root"], marker["served"], marker["skills"]), (str(root), ["kami"], list(built.skills)))
            self.assertEqual(marker["clashes"], [["devops/sdlc-review", "kami"]])

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
            self.assertEqual((second.refreshed, second.overwritten), ((), ()))
            self.assertEqual({p: p.lstat().st_mtime_ns for p in home.rglob("*") if p.name != MARKER_FILE}, before)
            self.assertFalse(list(home.glob(".*.omh-tmp")))  # the whole-file writes left no temporary behind

    def test_a_changed_root_file_is_copied_again_and_a_gone_skill_s_link_is_removed_with_its_category(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _root_home(Path(tmp))
            omh_home = Path(tmp) / "omh"
            omh_home.mkdir()
            build_tui_home(omh_home, root, served=("kami",))
            home = tui_home_path(omh_home)
            (root / "config.yaml").write_text("model:\n  default: claude-sonnet-5-5\n", encoding="utf-8")
            (root / ".env").write_text("OPENAI_API_KEY=sk-new\nDISCORD_BOT_TOKEN=again\n", encoding="utf-8")
            shutil.rmtree(root / "skills" / "media")
            _skill(root / "profiles" / "kami" / "skills", "media/vg-code-reel", "kami")
            built = build_tui_home(omh_home, root, served=("kami",))
            self.assertEqual((home / "config.yaml").read_text(encoding="utf-8"), "model:\n  default: claude-sonnet-5-5\n")
            self.assertEqual((home / ".env").read_text(encoding="utf-8"), "OPENAI_API_KEY=sk-new\n")
            self.assertFalse((home / "skills" / "media" / "hyperframes").is_symlink())
            self.assertTrue((home / "skills" / "media" / "vg-code-reel").is_symlink())  # the category stays for kami's skill
            self.assertIn("skills/media/hyperframes (removed)", built.refreshed)
            self.assertIn("skills/media/vg-code-reel", built.refreshed)
            self.assertIn("config.yaml", built.refreshed)
            self.assertIn(".env", built.refreshed)
            self.assertNotIn("auth.json", built.refreshed)
            self.assertEqual(built.overwritten, ())
            shutil.rmtree(root / "profiles" / "kami" / "skills" / "software")
            built = build_tui_home(omh_home, root, served=("kami",))
            self.assertIn("skills/software/oh-my-hermes-contribution (removed)", built.refreshed)
            self.assertFalse((home / "skills" / "software").exists())  # a category left empty goes too

    def test_a_config_the_person_changed_in_the_home_is_replaced_and_said(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _root_home(Path(tmp))
            omh_home = Path(tmp) / "omh"
            omh_home.mkdir()
            build_tui_home(omh_home, root, served=())
            home = tui_home_path(omh_home)
            (home / "config.yaml").write_text("model:\n  default: mine\n", encoding="utf-8")
            os.utime(home / "config.yaml", ns=((root / "config.yaml").stat().st_mtime_ns + 5_000_000_000,) * 2)
            built = build_tui_home(omh_home, root, served=())
            self.assertEqual(built.overwritten, ("config.yaml",))
            self.assertEqual((home / "config.yaml").read_bytes(), (root / "config.yaml").read_bytes())

    def test_an_auth_store_that_moved_in_the_home_after_the_root_s_is_kept(self) -> None:
        # Hermes rotates single-use OAuth refresh tokens into the store it read: the TUI home's newer copy wins.
        with TemporaryDirectory() as tmp:
            root = _root_home(Path(tmp))
            omh_home = Path(tmp) / "omh"
            omh_home.mkdir()
            build_tui_home(omh_home, root, served=())
            home = tui_home_path(omh_home)
            (home / "auth.json").write_text('{"token": "rotated"}\n', encoding="utf-8")
            os.utime(home / "auth.json", ns=((root / "auth.json").stat().st_mtime_ns + 5_000_000_000,) * 2)
            built = build_tui_home(omh_home, root, served=())
            self.assertNotIn("auth.json", built.refreshed)
            self.assertEqual((home / "auth.json").read_text(encoding="utf-8"), '{"token": "rotated"}\n')
            # The root's store moving later wins again.
            (root / "auth.json").write_text('{"token": "root-rotated"}\n', encoding="utf-8")
            os.utime(root / "auth.json", ns=((home / "auth.json").stat().st_mtime_ns + 5_000_000_000,) * 2)
            built = build_tui_home(omh_home, root, served=())
            self.assertIn("auth.json", built.refreshed)
            self.assertEqual((home / "auth.json").read_text(encoding="utf-8"), '{"token": "root-rotated"}\n')

    def test_entries_the_person_put_in_skills_are_left_alone_and_stand_for_their_name(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _root_home(Path(tmp))
            omh_home = Path(tmp) / "omh"
            omh_home.mkdir()
            home = tui_home_path(omh_home)
            _skill(home / "skills", "mine/sdlc-review", "mine")  # a real skill of the root's name
            elsewhere = _skill(Path(tmp) / "elsewhere", "my-link", "theirs")
            (home / "skills" / "my-link").symlink_to(elsewhere, target_is_directory=True)
            built = build_tui_home(omh_home, root, served=("kami",))
            self.assertEqual(built.kept_local, ("mine/sdlc-review", "my-link"))
            self.assertFalse((home / "skills" / "devops" / "sdlc-review").exists())  # the person's copy stands for the name
            self.assertTrue((home / "skills" / "my-link").is_symlink())
            self.assertIn("mine/sdlc-review", built.skills)
            self.assertIn("my-link", built.skills)
            second = build_tui_home(omh_home, root, served=("kami",))
            self.assertEqual(second.refreshed, ())

    def test_links_into_a_profile_no_longer_served_are_removed(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _root_home(Path(tmp), served=("kami", "zeta"))
            omh_home = Path(tmp) / "omh"
            omh_home.mkdir()
            _skill(root / "profiles" / "zeta" / "skills", "devops/zeta-only", "zeta")
            first = build_tui_home(omh_home, root, served=("kami", "zeta"))
            self.assertIn("devops/zeta-only", first.skills)
            second = build_tui_home(omh_home, root, served=("kami",))
            self.assertNotIn("devops/zeta-only", second.skills)
            self.assertEqual(second.kept_local, ())
            self.assertIn("skills/devops/zeta-only (removed)", second.refreshed)

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

    def test_a_root_env_that_is_not_utf_8_raises_a_value_error_naming_it(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _root_home(Path(tmp))
            (root / ".env").write_bytes(b"OPENAI_API_KEY=k\xff\xfe\n")
            omh_home = Path(tmp) / "omh"
            omh_home.mkdir()
            with self.assertRaises(ValueError) as caught:
                build_tui_home(omh_home, root, served=())
            self.assertIn(".env", str(caught.exception))

    def test_a_root_config_that_connects_a_platform_is_reported(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _root_home(Path(tmp))
            (root / "config.yaml").write_text("platforms:\n  telegram:\n    token: 1:a\n", encoding="utf-8")
            omh_home = Path(tmp) / "omh"
            omh_home.mkdir()
            built = build_tui_home(omh_home, root, served=())
            self.assertEqual(built.config_platform_credentials, ("telegram.token",))
            self.assertFalse((tui_home_path(omh_home) / "config.yaml").exists())  # never copied into the home
            marker = json.loads((tui_home_path(omh_home) / MARKER_FILE).read_text(encoding="utf-8"))
            self.assertEqual(marker["config_platform_credentials"], ["telegram.token"])

    def test_the_home_sits_under_the_omh_home(self) -> None:
        self.assertEqual(tui_home_path(Path("/o")), Path("/o") / own_runtime.TUI_HOME_DIR)


if __name__ == "__main__":
    unittest.main()
