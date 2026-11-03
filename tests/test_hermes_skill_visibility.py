"""OMH notices when Hermes cannot load its skills, says so, and stops naming them.

From 27 Oct to 2 Nov 2026 the installed skills were on disk and in the
manifest, but Hermes could not load them by name: first a stale generation pack
registered beside the pointer made every name ambiguous, then a cached path to
a collected generation left none. The launch card still said "skills 89
installed", and the candidate line kept telling the model to `skill_view` names
that came back "not found".

Three surfaces, each pinned here with its healthy state unchanged:

- the per-turn hints name only skills Hermes resolves to one copy
  (`installed_skills.hermes_loadable_skill_names`, read from Hermes' own cached
  resolution, faked here as the loaded `agent.skill_utils` module);
- `omh doctor` reports an ambiguous registration and a dangling entry apart,
  per Hermes home (`hermes_skill_visibility`);
- the launch card warns when a profile that registers OMH's skills sees far
  fewer of them than are installed (`launch_card.visibility_warning`).

Every fixture lives in a temporary home.
"""

from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import re
import shutil
import stat
from tempfile import TemporaryDirectory, mkdtemp
import types
import unittest

from _module_patch import patch_modules

from omh.installer import install_skill_pack
from omh.maintenance.doctor import run_doctor
from omh.paths import OmhPaths
from omh.plugin_bundle.omh import skill_shortlist
from omh.plugin_bundle.omh.hooks import llm_hooks
from omh.plugin_bundle.omh.installed_skills import (
    HERMES_EXTERNAL_DIRS_READER,
    HERMES_SEARCH_ROOTS_READER,
    HERMES_SKILL_UTILS_MODULE,
    TIER_EXTERNAL,
    TIER_LOCAL,
    hermes_loadable_skill_names,
    installed_skill_names,
    reset_installed_skill_cache,
)
from omh.tui.launch_card import (
    VISIBLE_SHARE_FLOOR,
    Facts,
    Skills,
    installed_omh_count,
    launch_card,
    skill_rows,
    visibility_warning,
)
from omh.tui.theme import LAUNCH_PRESETS
from omh.tui.width import line_width

from test_tui_launch_card import MEMBERS, SKILLS, Launched, paint, texts

# Ranks full-only skills, `omh-lifecycle-growth` first (`test_route_hint_installed_skills`).
CANDIDATE_MESSAGE = (
    "Activation fell after we changed the signup flow and new users churn in their first week. "
    "Where does retention break?"
)
FIRST_CANDIDATE = "omh-lifecycle-growth"
_CANDIDATE_LINE = re.compile(r"Skills that may fit this request: (.*?)\. If one matches")


def _paths(root: Path) -> OmhPaths:
    return OmhPaths(omh_home=root / "omh", hermes_home=root / "hermes")


def _hermes(*roots: Path, raises: bool = False) -> types.ModuleType:
    """A loaded `agent.skill_utils` with only the external-dirs reader, returning `roots` as its cache holds them."""
    module = types.ModuleType(HERMES_SKILL_UTILS_MODULE)

    def read() -> list[Path]:
        if raises:
            raise RuntimeError("config unreadable")
        return list(roots)

    module.get_external_skills_dirs = read  # type: ignore[attr-defined]
    assert hasattr(module, HERMES_EXTERNAL_DIRS_READER)  # the name the plugin reads
    return module


class _HermesFault(Exception):
    """Anything a Hermes reader might raise that is not an OSError."""


def _tiered(*roots: tuple[int, Path], raises: bool = False) -> types.ModuleType:
    """A loaded `agent.skill_utils` with the tiered reader, `get_skill_search_roots`."""
    module = types.ModuleType(HERMES_SKILL_UTILS_MODULE)

    def read() -> list[tuple[int, Path]]:
        if raises:
            raise _HermesFault("unexpected")
        return list(roots)

    module.get_skill_search_roots = read  # type: ignore[attr-defined]
    assert hasattr(module, HERMES_SEARCH_ROOTS_READER)
    return module


def _context(paths: OmhPaths, session: str, hermes: types.ModuleType | None = None) -> str:
    skill_shortlist.reset_candidate_line_state()
    # No Hermes: a module without a reader, which the plugin reads as no resolution at all.
    with patch_modules({HERMES_SKILL_UTILS_MODULE: hermes or types.ModuleType(HERMES_SKILL_UTILS_MODULE)}):
        result = llm_hooks.pre_llm_call(
            user_message=CANDIDATE_MESSAGE,
            session_id=session,
            omh_home=str(paths.omh_home),
            hermes_home=str(paths.hermes_home),
            is_first_turn=False,
        )
    return str((result or {}).get("context", ""))


def _loadable(paths: OmhPaths, hermes: types.ModuleType) -> frozenset[str] | None:
    reset_installed_skill_cache()
    with patch_modules({HERMES_SKILL_UTILS_MODULE: hermes}):
        return hermes_loadable_skill_names(paths.omh_home)


def _candidates(context: str) -> list[str]:
    return [option.split(" (", 1)[0] for match in _CANDIDATE_LINE.findall(context) for option in match.split("; ")]


def _skill_dir(skills_dir: Path, label: str) -> Path:
    return next(entry for entry in skills_dir.glob(f"*/{label}") if (entry / "SKILL.md").is_file())


def _copy_one(source_root: Path, label: str, target_root: Path) -> Path:
    source = _skill_dir(source_root, label)
    target = target_root / source.parent.name / label
    shutil.copytree(source, target)
    return target


def _manifest_labels(paths: OmhPaths) -> list[str]:
    records = json.loads(paths.manifest_path.read_text(encoding="utf-8"))["skills"]
    return sorted({Path(record["path"]).parent.name for record in records})


class _Installed(unittest.TestCase):
    """A full pack in a temporary OMH home, with the shortlist's per-session memory cleared around each test."""

    def setUp(self) -> None:
        reset_installed_skill_cache()
        skill_shortlist.reset_candidate_line_state()
        self.addCleanup(reset_installed_skill_cache)
        self.addCleanup(skill_shortlist.reset_candidate_line_state)
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.paths = _paths(self.root)
        install_skill_pack(self.paths, profile="full")
        self.skills = self.paths.skills_dir


class HintTests(_Installed):
    def test_a_healthy_hermes_renders_todays_hint_byte_for_byte(self) -> None:
        outside = _context(self.paths, "s-outside")
        other_dir = self.root / "user-skills"
        (other_dir / "mine" / "notes").mkdir(parents=True)
        (other_dir / "mine" / "notes" / "SKILL.md").write_text("---\nname: notes\n---\n", encoding="utf-8")
        local = self.root / "hermes" / "skills"

        self.assertIn(FIRST_CANDIDATE, _candidates(outside))
        for hermes in (
            _hermes(self.skills),
            _hermes(self.skills, other_dir),
            _tiered((TIER_LOCAL, local), (TIER_EXTERNAL, self.skills), (TIER_EXTERNAL, other_dir)),
        ):
            with self.subTest(hermes=hermes):
                reset_installed_skill_cache()
                self.assertEqual(_context(self.paths, "s-healthy", hermes), outside)
                self.assertEqual(_loadable(self.paths, hermes), installed_skill_names(self.paths.omh_home))

    def test_a_dangling_cached_path_names_no_skill(self) -> None:
        gone = self.root / "generations" / "collected" / "skills"

        context = _context(self.paths, "s-dangling", _hermes(gone))

        self.assertEqual(_candidates(context), [])
        self.assertNotIn("skill_view", context)
        self.assertEqual(_loadable(self.paths, _hermes(gone)), frozenset())

    def test_an_ambiguous_registration_names_no_skill(self) -> None:
        stale_pack = self.root / "generations" / "older" / "skills"
        shutil.copytree(self.skills, stale_pack)

        context = _context(self.paths, "s-ambiguous", _hermes(self.skills, stale_pack))

        self.assertEqual(_candidates(context), [])
        self.assertNotIn("skill_view", context)

    def test_a_partial_resolution_lists_only_the_skills_that_resolve(self) -> None:
        healthy = _candidates(_context(self.paths, "s-healthy"))
        self.assertEqual(healthy[0], FIRST_CANDIDATE)
        second = self.root / "second" / "skills"
        _copy_one(self.skills, FIRST_CANDIDATE, second)

        partial = _candidates(_context(self.paths, "s-partial", _hermes(self.skills, second)))

        self.assertTrue(partial)
        self.assertNotIn(FIRST_CANDIDATE, partial)
        loadable = _loadable(self.paths, _hermes(self.skills, second))
        assert loadable is not None
        self.assertNotIn(FIRST_CANDIDATE, loadable)
        self.assertEqual(sorted(set(partial) - loadable), [])
        self.assertEqual(partial[: len(healthy) - 1], healthy[1:])

    def test_a_generation_collected_under_a_running_hermes_is_seen_on_the_next_turn(self) -> None:
        generation = self.root / "generations" / "held" / "skills"
        shutil.copytree(self.skills, generation)
        hermes = _hermes(generation)  # Hermes' cache keeps this path whatever happens to it
        self.assertIn(FIRST_CANDIDATE, _candidates(_context(self.paths, "s-before", hermes)))

        shutil.rmtree(generation.parent)

        self.assertEqual(_candidates(_context(self.paths, "s-after", hermes)), [])

    def test_any_reader_failure_or_a_hermes_without_a_reader_keeps_the_installed_set(self) -> None:
        installed = installed_skill_names(self.paths.omh_home)
        for module in (_hermes(raises=True), _tiered(raises=True), types.ModuleType(HERMES_SKILL_UTILS_MODULE)):
            with self.subTest(module=module):
                self.assertEqual(_loadable(self.paths, module), installed)
        self.assertIn(FIRST_CANDIDATE, _candidates(_context(self.paths, "s-fault", _tiered(raises=True))))

    def test_the_tiered_reader_alone_decides_and_wins_when_both_readers_disagree(self) -> None:
        stale_pack = self.root / "generations" / "older" / "skills"
        shutil.copytree(self.skills, stale_pack)
        healthy = [self.skills]
        ambiguous = [(TIER_EXTERNAL, self.skills), (TIER_EXTERNAL, stale_pack)]

        alone = _loadable(self.paths, _tiered(*ambiguous))
        assert alone is not None
        self.assertNotIn(FIRST_CANDIDATE, alone)

        for tiered_roots, external_roots, loadable in (
            (ambiguous, healthy, False),
            ([(TIER_EXTERNAL, self.skills)], [self.skills, stale_pack], True),
        ):
            with self.subTest(loadable=loadable):
                both = _tiered(*tiered_roots)
                both.get_external_skills_dirs = lambda roots=external_roots: list(roots)  # type: ignore[attr-defined]
                names = _loadable(self.paths, both)
                assert names is not None
                self.assertEqual(FIRST_CANDIDATE in names, loadable)

    def test_a_copy_in_a_higher_tier_wins_over_an_external_collision(self) -> None:
        second = self.root / "second" / "skills"
        _copy_one(self.skills, FIRST_CANDIDATE, second)
        local = self.root / "hermes" / "skills"
        _copy_one(self.skills, FIRST_CANDIDATE, local)

        loadable = _loadable(
            self.paths, _tiered((TIER_LOCAL, local), (TIER_EXTERNAL, self.skills), (TIER_EXTERNAL, second))
        )

        assert loadable is not None
        self.assertIn(FIRST_CANDIDATE, loadable)

    def test_a_symlinked_copy_in_a_second_root_is_one_copy(self) -> None:
        second = self.root / "second" / "skills"
        source = _skill_dir(self.skills, FIRST_CANDIDATE)
        (second / source.parent.name).mkdir(parents=True)
        try:
            os.symlink(source, second / source.parent.name / FIRST_CANDIDATE, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"no directory symlinks here: {exc}")
        linked_root = self.root / "linked"
        try:
            os.symlink(self.skills, linked_root, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"no directory symlinks here: {exc}")

        for hermes in (_hermes(self.skills, linked_root), _tiered((TIER_EXTERNAL, self.skills), (TIER_EXTERNAL, second))):
            with self.subTest(hermes=hermes):
                loadable = _loadable(self.paths, hermes)
                assert loadable is not None
                self.assertIn(FIRST_CANDIDATE, loadable)

    @unittest.skipIf(os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0), "needs POSIX permissions")
    def test_one_unreadable_category_leaves_the_others_loadable(self) -> None:
        category = _skill_dir(self.skills, FIRST_CANDIDATE).parent
        held = {path.name for path in category.iterdir() if (path / "SKILL.md").is_file()}
        os.chmod(category, 0)
        self.addCleanup(os.chmod, category, stat.S_IRWXU)

        loadable = _loadable(self.paths, _hermes(self.skills))

        assert loadable is not None
        self.assertEqual(sorted(held & loadable), [])
        others = set(_manifest_labels(self.paths)) - held
        self.assertTrue(others)
        self.assertEqual(sorted(others - loadable), [])


class DoctorTests(_Installed):
    def _config(self, hermes_home: Path, *entries: str) -> None:
        listed = "".join(f"    - {entry}\n" for entry in entries)
        hermes_home.mkdir(parents=True, exist_ok=True)
        (hermes_home / "config.yaml").write_text(f"skills:\n  external_dirs:\n{listed}", encoding="utf-8")

    def _checks(self, paths: OmhPaths | None = None) -> dict:
        reset_installed_skill_cache()
        return {
            check.name: check
            for check in run_doctor(paths or self.paths)
            if check.name.startswith("hermes_skill_visibility")
        }

    def _check(self, *entries: str):
        if entries:
            self._config(self.paths.hermes_home, *entries)
        return self._checks()["hermes_skill_visibility"]

    def test_one_registered_pack_passes_and_says_it_reads_the_config_only(self) -> None:
        check = self._check(str(self.skills))
        self.assertEqual((check.ok, check.severity, check.observed), (True, "ok", True), check.message)
        self.assertIn("all", check.message)
        self.assertIn("config.yaml only", check.message)
        self.assertIn("gateway started earlier", check.message)

    def test_a_collision_with_a_directory_omh_does_not_manage_names_that_directory(self) -> None:
        stale_pack = self.root / "generations" / "older" / "skills"
        shutil.copytree(self.skills, stale_pack)

        check = self._check(str(self.skills), str(stale_pack))

        self.assertEqual((check.ok, check.severity), (True, "warning"))
        self.assertIn("Hermes can load 0 of", check.message)
        self.assertIn("refuses a name two directories of one tier hold", check.message)
        self.assertEqual(check.detail["ambiguous"], _manifest_labels(self.paths))
        self.assertEqual((check.detail["not_found"], check.detail["dangling_entries"]), ([], []))
        self.assertIn("which OMH does not manage", check.next_action)
        self.assertIn(os.path.realpath(stale_pack), check.next_action)
        self.assertNotIn("remove the others", check.next_action)
        self.assertNotIn("omh update", check.next_action + check.remediation)

    def test_two_omh_managed_directories_say_keep_one(self) -> None:
        generation = self.root / "generations" / "g1" / "skills"
        managed = OmhPaths(omh_home=self.root / "omh2", hermes_home=self.root / "hermes2", managed_skills_dir=generation)
        install_skill_pack(managed, profile="full")
        shutil.copytree(generation, managed.omh_home / "skills")
        self._config(managed.hermes_home, str(generation), str(managed.omh_home / "skills"))

        check = self._checks(managed)["hermes_skill_visibility"]

        self.assertEqual(check.severity, "warning")
        self.assertEqual(check.detail["ambiguous"], _manifest_labels(managed))
        self.assertIn("Keep one of the OMH skills directories", check.next_action)
        self.assertIn(str(generation), check.next_action)
        self.assertNotIn("does not manage", check.next_action)

    def test_a_dangling_omh_entry_is_named_as_such(self) -> None:
        self._config(self.paths.hermes_home, str(self.skills))
        shutil.move(str(self.skills), str(self.root / "moved-away"))

        check = self._checks()["hermes_skill_visibility"]

        self.assertEqual((check.ok, check.severity), (True, "warning"))
        self.assertIn("do not exist", check.message)
        self.assertEqual(check.detail["ambiguous"], [])
        self.assertEqual(check.detail["not_found"], _manifest_labels(self.paths))
        (dangling,) = check.detail["dangling_entries"]
        self.assertTrue(dangling.startswith(str(self.skills)), dangling)  # then " -> <real path>" via a tmp link
        self.assertNotIn("refuses", check.message)
        self.assertIn("Point the missing entry", check.next_action)
        self.assertNotIn("omh update", check.next_action + check.remediation)

    def test_a_partial_collision_counts_only_the_shared_names(self) -> None:
        second = self.root / "second" / "skills"
        _copy_one(self.skills, FIRST_CANDIDATE, second)

        check = self._check(str(self.skills), str(second))

        self.assertEqual(check.detail["ambiguous"], [FIRST_CANDIDATE])
        self.assertEqual(check.detail["not_found"], [])

    def test_a_copy_in_the_profiles_own_skills_wins_over_an_external_collision(self) -> None:
        second = self.root / "second" / "skills"
        _copy_one(self.skills, FIRST_CANDIDATE, second)
        _copy_one(self.skills, FIRST_CANDIDATE, self.paths.hermes_home / "skills")

        check = self._check(str(self.skills), str(second))

        self.assertEqual(check.severity, "ok", check.message)

    def test_an_unregistered_home_or_no_manifest_is_not_observed_here(self) -> None:
        unrelated = self.root / "user-skills"
        unrelated.mkdir()
        self.assertFalse(self._check(str(unrelated)).observed)
        self.paths.manifest_path.unlink()
        self.assertFalse(self._check(str(self.skills)).observed)

    def test_each_bot_profile_with_a_finding_gets_its_own_row(self) -> None:
        self._config(self.paths.hermes_home, str(self.skills))
        stale_pack = self.root / "generations" / "older" / "skills"
        shutil.copytree(self.skills, stale_pack)
        self._config(self.paths.hermes_home / "profiles" / "bot", str(self.skills), str(stale_pack))
        self._config(self.paths.hermes_home / "profiles" / "fine", str(self.skills))
        self._config(self.paths.hermes_home / "profiles" / "plain", str(self.root / "user-skills"))

        checks = self._checks()

        self.assertEqual(sorted(checks), ["hermes_skill_visibility", "hermes_skill_visibility:bot"])
        self.assertEqual(checks["hermes_skill_visibility"].severity, "ok")
        bot = checks["hermes_skill_visibility:bot"]
        self.assertEqual(bot.severity, "warning")
        self.assertIn("profile bot", bot.message)


class LaunchCardTests(unittest.TestCase):
    FACTS = Facts(model="openai/gpt-6.1-sol", effort="high", session="20261023_000000_aaaaaaaa",
                  last_title="Check the proactive alerts", last_id="20261022_121251_cf45f40d", last_count=14)

    def cards(self, skills: Skills | None) -> dict[str, list[str]]:
        return {f"{look}/{width}/{room}": texts(launch_card(look, self.FACTS, paint(look), width, room, skills))
                for look in LAUNCH_PRESETS for width, room in ((150, 30), (100, 18), (60, 9))}

    def test_a_healthy_or_unread_count_draws_todays_card(self) -> None:
        skills = skill_rows(SKILLS, members=lambda: MEMBERS)  # 7 OMH names
        today = self.cards(skills)
        for installed in (None, 7, 0, int(7 / VISIBLE_SHARE_FLOOR)):  # equal, unread, none recorded, at the floor
            with self.subTest(installed=installed):
                self.assertEqual(self.cards(replace(skills, omh_installed=installed)), today)

    def test_the_remedy_is_whole_on_screen_in_every_look_and_width(self) -> None:
        skills = replace(skill_rows(SKILLS, members=lambda: MEMBERS), omh_installed=153)
        for look in LAUNCH_PRESETS:
            for width in (80, 100, 150):
                with self.subTest(look=look, width=width):
                    card = launch_card(look, self.FACTS, paint(look), width, 30, skills)
                    self.assertLessEqual(len(card), 30)
                    self.assertTrue(all(line_width(line) <= width for line in card))
                    shown = "\n".join(texts(card))
                    self.assertIn("Hermes sees only 7 of 153", shown)
                    self.assertIn("restart the gateway", shown)
                    self.assertIn("/new", shown)
                    self.assertNotIn("omh doctor", shown)

    def test_the_warning_fits_short_rooms_too(self) -> None:
        skills = replace(skill_rows(SKILLS, members=lambda: MEMBERS), omh_installed=153)
        for look in LAUNCH_PRESETS:
            for width, room in ((100, 18), (100, 12)):
                with self.subTest(look=look, width=width, room=room):
                    card = launch_card(look, self.FACTS, paint(look), width, room, skills)
                    self.assertLessEqual(len(card), room)
                    self.assertTrue(all(line_width(line) <= width for line in card))

    def test_the_warning_names_the_cause_and_the_remedy_and_never_omh_update(self) -> None:
        empty = Skills((), 0, ("devops",), 89, omh_installed=147)
        counts, remedy = texts(visibility_warning(empty, paint()))
        self.assertIn("Hermes sees only 0 of 147 OMH skills", counts)
        self.assertIn("stale", counts)
        self.assertIn("restart the gateway", remedy)
        self.assertIn("/new", remedy)
        self.assertLessEqual(line_width(visibility_warning(empty, paint())[1]), 50)
        self.assertNotIn("omh update", counts + remedy)
        self.assertNotIn("omh doctor", counts + remedy)

    def test_a_last_known_count_never_warns(self) -> None:
        self.assertEqual(visibility_warning(Skills((), 0, (), 89, last_known=True, omh_installed=147), paint()), [])

    def test_the_app_weighs_hermes_list_only_where_omh_is_registered(self) -> None:
        for recorded, registered, warned in ((7, True, False), (40, True, True), (40, False, False)):
            with self.subTest(recorded=recorded, registered=registered):
                reset_installed_skill_cache()
                hermes = Path(mkdtemp(prefix="omh-visibility-hermes-"))
                self.addCleanup(shutil.rmtree, hermes, True)
                run = Launched(env={"HERMES_HOME": str(hermes)})
                run.home.mkdir(parents=True, exist_ok=True)
                records = [{"name": f"s{i}", "path": f"omh/omh-s{i}/SKILL.md"} for i in range(recorded)]
                (run.home / "manifest.json").write_text(json.dumps({"skills": records}), encoding="utf-8")
                entry = run.home / "skills" if registered else hermes / "own-skills"
                (hermes / "config.yaml").write_text(f"skills:\n  external_dirs:\n    - {entry}\n", encoding="utf-8")
                self.assertEqual(installed_omh_count(run.home, hermes), recorded if registered else None)
                run.info()
                self.assertEqual("Hermes sees only 7 of" in "\n".join(run.screen()), warned)


if __name__ == "__main__":
    unittest.main()
