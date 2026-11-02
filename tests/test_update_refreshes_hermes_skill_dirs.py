"""`omh update` makes a running Hermes re-read OMH's skills directory, with no restart.

Hermes (`agent/skill_utils.py`, `get_external_skills_dirs`) caches the
RESOLVED path of every `skills.external_dirs` entry, keyed by config.yaml's
file signature (`utils.file_signature`: mtime_ns, size, inode, ctime_ns).
OMH registers `<root>/current/skills` and moves `current` to a new
generation on every update, so a running gateway kept the old generation's
skills -- none at all once that generation was collected -- until
`hermes gateway restart`. Moving the mtime of each config that names the
pointer changes the signature; `HermesExternalDirsCacheModel` below stands
in for Hermes' cache so this is pinned without importing Hermes.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest import mock

from _cli_harness import run_cli
from _platform_support import requires_symlinks

from omh.commands import setup as _setup_module
from omh.config_adapter import external_dirs
from omh.maintenance import hermes_gateway as _gateway_module
from omh.maintenance.hermes_gateway import refresh_skill_dir_caches

_OLD_NS = 1_700_000_000_000_000_000
_OLD_ATIME_NS = 1_600_000_000_000_000_000


def _config_naming(*dirs: str) -> str:
    items = "".join(f"    - {item}\n" for item in dirs)
    return f"model:\n  default: x\nskills:\n  external_dirs:\n{items}"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="")
    os.utime(path, ns=(_OLD_ATIME_NS, _OLD_NS))


def _layout(root: Path) -> Path:
    """`<root>/current -> generations/gen1`, each generation with one skill; returns the pointer's skills."""
    for generation, skill in (("gen1", "old-skill"), ("gen2", "new-skill")):
        skill_dir = root / "generations" / generation / "skills" / skill
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(f"---\nname: {skill}\n---\n", encoding="utf-8")
    (root / "current").symlink_to("generations/gen1")
    return root / "current" / "skills"


def _swap(root: Path, generation: str) -> None:
    (root / "current").unlink()
    (root / "current").symlink_to(f"generations/{generation}")


def _profile(hermes_home: Path, name: str) -> Path:
    profile = hermes_home / "profiles" / name
    profile.mkdir(parents=True, exist_ok=True)
    (profile / "SOUL.md").write_text("Profile identity\n", encoding="utf-8")
    return profile


class HermesExternalDirsCacheModel:
    """Hermes' `_EXTERNAL_DIRS_CACHE`: resolved entries keyed by the config's file signature."""

    def __init__(self, config: Path) -> None:
        self.config = config
        self.cache: dict[tuple[str, int, int, int, int], list[Path]] = {}

    def skills(self) -> list[str]:
        st = self.config.stat()
        key = (str(self.config), st.st_mtime_ns, st.st_size, st.st_ino, st.st_ctime_ns)
        if key not in self.cache:
            self.cache[key] = [Path(entry).resolve() for entry in external_dirs(self.config.read_text(encoding="utf-8"))]
        return sorted(skill.parent.name for directory in self.cache[key] for skill in directory.rglob("SKILL.md"))


@requires_symlinks
class RefreshSkillDirCachesTests(unittest.TestCase):
    def test_a_home_naming_the_pointer_is_touched_and_its_bytes_are_kept(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            pointer = _layout(root)
            hermes_home = root / ".hermes"
            primary = hermes_home / "config.yaml"
            _write(primary, _config_naming(pointer.as_posix()))
            kami = _profile(hermes_home, "kami")
            # A trailing slash is the same directory to Hermes and to the registration writer.
            _write(kami / "config.yaml", _config_naming(f"{pointer.as_posix()}/"))
            before = {path: path.read_bytes() for path in (primary, kami / "config.yaml")}
            _swap(root, "gen2")

            kept_atimes: list[bool] = []

            def utime(path, *args, **kwargs):
                # Reading the config may itself move atime (relatime), so the
                # contract is "the atime it has at the touch", not a fixed value.
                kept_atimes.append(kwargs["ns"][0] == os.stat(path).st_atime_ns)
                return os.utime(path, *args, **kwargs)

            with mock.patch.object(_gateway_module, "os", SimpleNamespace(**{**vars(os), "utime": utime})):
                rows = refresh_skill_dir_caches(hermes_home, pointer)

            self.assertEqual([row["status"] for row in rows], ["refreshed", "refreshed"])
            self.assertEqual(rows[1]["home"], f"profile kami ({kami / 'config.yaml'})")
            self.assertEqual(kept_atimes, [True, True])
            for path, data in before.items():
                self.assertGreater(path.stat().st_mtime_ns, _OLD_NS)
                self.assertEqual(path.read_bytes(), data)

    def test_a_home_that_does_not_name_the_pointer_is_left_alone(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            pointer = _layout(root)
            hermes_home = root / ".hermes"
            own = root / "own-skills"
            own.mkdir()
            _write(hermes_home / "config.yaml", _config_naming(own.as_posix()))
            other = _profile(hermes_home, "other")
            _write(other / "config.yaml", "model:\n  default: x\n")

            self.assertEqual(refresh_skill_dir_caches(hermes_home, pointer), [])
            for path in (hermes_home / "config.yaml", other / "config.yaml"):
                self.assertEqual(path.stat().st_mtime_ns, _OLD_NS)

    def test_a_missing_config_is_never_created(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            pointer = _layout(root)
            hermes_home = root / ".hermes"
            bare = _profile(hermes_home, "bare")

            self.assertEqual(refresh_skill_dir_caches(hermes_home, pointer), [])
            self.assertFalse((hermes_home / "config.yaml").exists())
            self.assertFalse((bare / "config.yaml").exists())

    def test_no_pointer_on_disk_touches_nothing(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            pointer = root / "current" / "skills"
            _write(root / ".hermes" / "config.yaml", _config_naming(pointer.as_posix()))

            self.assertEqual(refresh_skill_dir_caches(root / ".hermes", pointer), [])
            self.assertEqual(refresh_skill_dir_caches(root / ".hermes", None), [])
            self.assertEqual((root / ".hermes" / "config.yaml").stat().st_mtime_ns, _OLD_NS)

    def test_a_home_that_cannot_be_touched_is_reported_and_the_rest_are_refreshed(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            pointer = _layout(root)
            hermes_home = root / ".hermes"
            _write(hermes_home / "config.yaml", _config_naming(pointer.as_posix()))
            kami = _profile(hermes_home, "kami")
            _write(kami / "config.yaml", _config_naming(pointer.as_posix()))

            def utime(path, *args, **kwargs):
                if Path(path) == hermes_home / "config.yaml":
                    raise PermissionError(1, "Operation not permitted", str(path))
                return os.utime(path, *args, **kwargs)

            with mock.patch.object(_gateway_module, "os", SimpleNamespace(**{**vars(os), "utime": utime})):
                rows = refresh_skill_dir_caches(hermes_home, pointer)

            self.assertEqual([row["status"] for row in rows], ["failed", "refreshed"])
            self.assertIn("Operation not permitted", rows[0]["error"])
            self.assertEqual((hermes_home / "config.yaml").stat().st_mtime_ns, _OLD_NS)
            self.assertGreater((kami / "config.yaml").stat().st_mtime_ns, _OLD_NS)

    def test_hermes_cache_serves_the_old_generation_until_the_refresh(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            pointer = _layout(root)
            hermes_home = root / ".hermes"
            _write(hermes_home / "config.yaml", _config_naming(pointer.as_posix()))
            hermes = HermesExternalDirsCacheModel(hermes_home / "config.yaml")
            self.assertEqual(hermes.skills(), ["old-skill"])

            _swap(root, "gen2")
            # The defect: the signature did not move, so the cached resolution is gen1's.
            self.assertEqual(hermes.skills(), ["old-skill"])

            refresh_skill_dir_caches(hermes_home, pointer)
            self.assertEqual(hermes.skills(), ["new-skill"])


@requires_symlinks
class UpdateRefreshesSkillDirsTests(unittest.TestCase):
    def _base(self, root: Path) -> list[str]:
        return ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]

    def _registered(self, root: Path) -> tuple[Path, list[Path]]:
        """Set up, then name the generation pointer beside OMH's own dir in every home."""
        profile = _profile(root / ".hermes", "kami")
        status, _, stderr = run_cli(self._base(root) + ["setup"])
        self.assertEqual(status, 0, stderr)
        pointer = _layout(root / "managed")
        configs = [root / ".hermes" / "config.yaml", profile / "config.yaml"]
        own_path = (root / ".omh" / "skills").resolve().as_posix()
        for config in configs:
            text = config.read_text(encoding="utf-8")
            self.assertIn(f"    - {own_path}\n", text)
            _write(config, text.replace(f"    - {own_path}\n", f"    - {own_path}\n    - {pointer.as_posix()}\n"))
        return pointer, configs

    def test_update_touches_every_home_naming_the_pointer_and_says_so(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            pointer, configs = self._registered(root)
            before = {config: config.read_bytes() for config in configs}
            _swap(root / "managed", "gen2")

            with mock.patch.object(_setup_module, "managed_current_workflow_pack_dir", return_value=pointer):
                status, stdout, stderr = run_cli(self._base(root) + ["update"], output_json=False)

            self.assertEqual(status, 0, stderr)
            self.assertIn(
                "  Hermes skills refreshed in 2 homes: new conversations and every skill load use the new OMH skills "
                "without a restart; an open conversation keeps the skill list it started with until `/new`\n",
                stdout,
            )
            for config, data in before.items():
                self.assertEqual(config.read_bytes(), data)
                self.assertGreater(config.stat().st_mtime_ns, _OLD_NS)

    def test_a_dry_run_touches_nothing_and_says_nothing(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            pointer, configs = self._registered(root)
            _swap(root / "managed", "gen2")

            with mock.patch.object(_setup_module, "managed_current_workflow_pack_dir", return_value=pointer):
                status, stdout, stderr = run_cli(self._base(root) + ["update", "--dry-run"], output_json=False)
                json_status, json_stdout, json_stderr = run_cli(self._base(root) + ["update", "--dry-run"])

            self.assertEqual(status, 0, stderr)
            self.assertEqual(json_status, 0, json_stderr)
            self.assertNotIn("Hermes skills refreshed", stdout)
            self.assertNotIn("hermes_skill_refresh", json.loads(json_stdout))
            for config in configs:
                self.assertEqual(config.stat().st_mtime_ns, _OLD_NS)

    def test_a_touch_failure_is_reported_and_the_update_still_succeeds(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            pointer, configs = self._registered(root)
            primary = configs[0]

            def utime(path, *args, **kwargs):
                if Path(path) == primary.resolve() or Path(path) == primary:
                    raise PermissionError(1, "Operation not permitted", str(path))
                return os.utime(path, *args, **kwargs)

            with (
                mock.patch.object(_setup_module, "managed_current_workflow_pack_dir", return_value=pointer),
                mock.patch.object(_gateway_module, "os", SimpleNamespace(**{**vars(os), "utime": utime})),
            ):
                status, stdout, _ = run_cli(self._base(root) + ["update"])

            payload = json.loads(stdout)
            self.assertEqual(status, 0)
            self.assertEqual(payload["exit_code"], 0)
            rows = payload["hermes_skill_refresh"]
            self.assertEqual([row["status"] for row in rows], ["failed", "refreshed"])
            self.assertIn("Operation not permitted", rows[0]["error"])

    def test_the_plain_warning_names_the_home_that_was_missed(self) -> None:
        rows = [
            {"home": "/h/config.yaml", "config": "/h/config.yaml", "status": "failed", "error": "denied"},
            {"home": "profile kami (/h/profiles/kami/config.yaml)", "config": "/h/profiles/kami/config.yaml", "status": "refreshed"},
        ]
        self.assertEqual(
            _setup_module._skill_refresh_lines(rows),
            [
                "Hermes skills refreshed in 1 home: new conversations and every skill load use the new OMH skills "
                "without a restart; an open conversation keeps the skill list it started with until `/new`",
                "warning: /h/config.yaml: could not mark config.yaml changed (denied); "
                "a running Hermes there keeps the previous OMH skills until it restarts",
            ],
        )
        self.assertEqual(_setup_module._skill_refresh_lines([]), [])


if __name__ == "__main__":
    unittest.main()
