"""OMH notices when Hermes cannot load its skills, says so, and stops naming them.

From 27 Oct to 2 Nov 2026 the installed skills were on disk and in the
manifest, but Hermes could not load them by name: first a stale generation pack
registered beside the pointer made every name ambiguous, then a cached path to
a collected generation left none. The launch card still said "skills 89
installed", and the candidate line kept telling the model to `skill_view` names
that came back "not found".

Three surfaces, each pinned here with its healthy state unchanged:

- the per-turn hints name only skills Hermes resolves to exactly one directory
  (`installed_skills.hermes_loadable_skill_names`, read from Hermes' own cached
  resolution, faked here as the loaded `agent.skill_utils` module);
- `omh doctor` reports an ambiguous registration and a dangling entry apart
  (`hermes_skill_visibility`);
- the launch card warns when Hermes lists far fewer OMH skills than are
  installed (`launch_card.visibility_warning`).

Every fixture lives in a temporary home.
"""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import re
import shutil
import sys
from tempfile import TemporaryDirectory
import types
import unittest
from unittest import mock

from omh.installer import install_skill_pack
from omh.maintenance.doctor import run_doctor
from omh.paths import OmhPaths
from omh.plugin_bundle.omh import skill_shortlist
from omh.plugin_bundle.omh.hooks import llm_hooks
from omh.plugin_bundle.omh.installed_skills import (
    HERMES_EXTERNAL_DIRS_READER,
    HERMES_SKILL_UTILS_MODULE,
    hermes_loadable_skill_names,
    installed_skill_names,
    reset_installed_skill_cache,
    skill_labels_under,
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
    """A loaded `agent.skill_utils` whose cached resolution is `roots`, as Hermes' own reader returns it."""
    module = types.ModuleType(HERMES_SKILL_UTILS_MODULE)

    def read() -> list[Path]:
        if raises:
            raise RuntimeError("config unreadable")
        return list(roots)

    setattr(module, HERMES_EXTERNAL_DIRS_READER, read)
    return module


def _context(paths: OmhPaths, session: str, hermes: types.ModuleType | None = None) -> str:
    skill_shortlist.reset_candidate_line_state()
    patched = {HERMES_SKILL_UTILS_MODULE: hermes} if hermes is not None else {}
    with mock.patch.dict(sys.modules, patched):
        if hermes is None:
            sys.modules.pop(HERMES_SKILL_UTILS_MODULE, None)
        result = llm_hooks.pre_llm_call(
            user_message=CANDIDATE_MESSAGE,
            session_id=session,
            omh_home=str(paths.omh_home),
            hermes_home=str(paths.hermes_home),
            is_first_turn=False,
        )
    return str((result or {}).get("context", ""))


def _loadable(paths: OmhPaths, hermes: types.ModuleType) -> frozenset[str] | None:
    with mock.patch.dict(sys.modules, {HERMES_SKILL_UTILS_MODULE: hermes}):
        return hermes_loadable_skill_names(paths.omh_home)


def _candidates(context: str) -> list[str]:
    return [option.split(" (", 1)[0] for match in _CANDIDATE_LINE.findall(context) for option in match.split("; ")]


def _skill_dir(skills_dir: Path, label: str) -> Path:
    return next(entry for entry in skills_dir.glob(f"*/{label}") if (entry / "SKILL.md").is_file())


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
        healthy = _context(self.paths, "s-healthy", _hermes(self.skills))
        other_dir = self.root / "user-skills"
        (other_dir / "mine" / "notes").mkdir(parents=True)
        (other_dir / "mine" / "notes" / "SKILL.md").write_text("---\nname: notes\n---\n", encoding="utf-8")
        beside = _context(self.paths, "s-beside", _hermes(self.skills, other_dir))

        self.assertIn(FIRST_CANDIDATE, _candidates(outside))
        self.assertEqual(healthy, outside)
        self.assertEqual(beside, outside)
        self.assertEqual(_loadable(self.paths, _hermes(self.skills)), installed_skill_names(self.paths.omh_home))

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
        source = _skill_dir(self.skills, FIRST_CANDIDATE)
        shutil.copytree(source, second / source.parent.name / FIRST_CANDIDATE)

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

    def test_a_reader_that_raises_or_a_hermes_without_one_keeps_the_installed_set(self) -> None:
        installed = installed_skill_names(self.paths.omh_home)
        for module in (_hermes(raises=True), types.ModuleType(HERMES_SKILL_UTILS_MODULE)):
            with self.subTest(module=module), mock.patch.dict(sys.modules, {HERMES_SKILL_UTILS_MODULE: module}):
                reset_installed_skill_cache()
                self.assertEqual(hermes_loadable_skill_names(self.paths.omh_home), installed)

    def test_the_layout_scan_reads_both_pack_shapes(self) -> None:
        flat = self.root / "flat"
        (flat / "omh-plan").mkdir(parents=True)
        (flat / "omh-plan" / "SKILL.md").write_text("x", encoding="utf-8")
        (flat / "operator" / "omh-doctor").mkdir(parents=True)
        (flat / "operator" / "omh-doctor" / "SKILL.md").write_text("x", encoding="utf-8")
        (flat / "operator" / "empty").mkdir()

        self.assertEqual(skill_labels_under(flat), frozenset({"omh-plan", "omh-doctor"}))
        self.assertIsNone(skill_labels_under(self.root / "missing"))


class DoctorTests(_Installed):
    def _check(self, *entries: str):
        if entries:
            listed = "".join(f"    - {entry}\n" for entry in entries)
            self.paths.hermes_home.mkdir(parents=True, exist_ok=True)
            self.paths.hermes_config_path.write_text(f"skills:\n  external_dirs:\n{listed}", encoding="utf-8")
        reset_installed_skill_cache()
        return next(check for check in run_doctor(self.paths) if check.name == "hermes_skill_visibility")

    def test_one_registered_pack_passes(self) -> None:
        check = self._check(str(self.skills))
        self.assertEqual((check.ok, check.severity, check.observed), (True, "ok", True), check.message)
        self.assertIn("all", check.message)

    def test_an_ambiguous_registration_is_named_as_such(self) -> None:
        stale_pack = self.root / "generations" / "older" / "skills"
        shutil.copytree(self.skills, stale_pack)

        check = self._check(str(self.skills), str(stale_pack))

        self.assertEqual((check.ok, check.severity), (True, "warning"))
        self.assertIn("Hermes can load 0 of", check.message)
        self.assertIn("refuses a name two directories of one tier hold", check.message)
        self.assertEqual(len(check.detail["ambiguous"]), len(installed_skill_names_labels(self.paths)))
        self.assertEqual((check.detail["not_found"], check.detail["dangling_entries"]), ([], []))
        self.assertIn("remove the others", check.next_action)
        self.assertNotIn("omh update", check.next_action + check.remediation)

    def test_a_dangling_entry_is_named_as_such(self) -> None:
        gone = self.root / "generations" / "collected" / "skills"

        check = self._check(str(gone))

        self.assertEqual((check.ok, check.severity), (True, "warning"))
        self.assertIn("do not exist", check.message)
        self.assertIn(str(gone), check.message)
        self.assertEqual(check.detail["ambiguous"], [])
        self.assertEqual(len(check.detail["not_found"]), len(installed_skill_names_labels(self.paths)))
        (dangling,) = check.detail["dangling_entries"]
        self.assertTrue(dangling.startswith(str(gone)), dangling)  # then " -> <real path>" where the tmp dir is a link
        self.assertNotIn("refuses", check.message)
        self.assertIn("Point the missing entry", check.next_action)
        self.assertNotIn("omh update", check.next_action + check.remediation)

    def test_a_partial_collision_counts_only_the_shared_names(self) -> None:
        second = self.root / "second" / "skills"
        source = _skill_dir(self.skills, FIRST_CANDIDATE)
        shutil.copytree(source, second / source.parent.name / FIRST_CANDIDATE)

        check = self._check(str(self.skills), str(second))

        self.assertEqual(check.detail["ambiguous"], [FIRST_CANDIDATE])
        self.assertEqual(check.detail["not_found"], [])

    def test_no_registration_or_no_manifest_is_not_observed_here(self) -> None:
        self.assertFalse(self._check().observed)
        self.paths.manifest_path.unlink()
        self.assertFalse(self._check(str(self.skills)).observed)


def installed_skill_names_labels(paths: OmhPaths) -> list[str]:
    records = json.loads(paths.manifest_path.read_text(encoding="utf-8"))["skills"]
    return sorted({Path(record["path"]).parent.name for record in records})


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

    def test_far_fewer_than_installed_warns_in_every_look_and_still_fits(self) -> None:
        skills = replace(skill_rows(SKILLS, members=lambda: MEMBERS), omh_installed=153)
        for look in LAUNCH_PRESETS:
            for width, room in ((150, 30), (100, 18), (100, 12)):
                with self.subTest(look=look, width=width, room=room):
                    card = launch_card(look, self.FACTS, paint(look), width, room, skills)
                    self.assertLessEqual(len(card), room)
                    self.assertTrue(all(line_width(line) <= width for line in card))
                    self.assertIn("Hermes lists 7 of 153 installed OMH skills", "\n".join(texts(card)))

    def test_the_warning_names_the_cause_and_the_remedy_and_never_omh_update(self) -> None:
        empty = Skills((), 0, ("devops",), 89, omh_installed=147)
        (row,) = texts([visibility_warning(empty, paint())])
        self.assertIn("Hermes lists 0 of 147 installed OMH skills", row)
        self.assertIn("stale", row)
        self.assertIn("restart the gateway", row)
        self.assertIn("/new", row)
        self.assertNotIn("omh update", row)

    def test_a_last_known_count_never_warns(self) -> None:
        self.assertEqual(visibility_warning(Skills((), 0, (), 89, last_known=True, omh_installed=147), paint()), ())

    def test_the_app_weighs_hermes_list_against_the_manifest(self) -> None:
        for recorded, warned in ((7, False), (40, True)):
            with self.subTest(recorded=recorded):
                reset_installed_skill_cache()
                run = Launched()
                run.home.mkdir(parents=True, exist_ok=True)
                records = [{"name": f"s{i}", "path": f"omh/omh-s{i}/SKILL.md"} for i in range(recorded)]
                (run.home / "manifest.json").write_text(json.dumps({"skills": records}), encoding="utf-8")
                self.assertEqual(installed_omh_count(run.home), recorded)
                run.info()
                self.assertEqual("Hermes lists 7 of" in "\n".join(run.screen()), warned)


if __name__ == "__main__":
    unittest.main()
