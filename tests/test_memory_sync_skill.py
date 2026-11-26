from __future__ import annotations

import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from _local_package import load_local_package

load_local_package()

from _cli_harness import run_cli
from omh.catalogs.roles import roles_reference_markdown
from omh.routing import recommend as recommend_module
from omh.skill_pack import (
    CORE_PROFILE_SKILLS,
    CORE_SKILLS,
    builtin_definitions,
    builtin_skill_templates,
)
from omh.skills.catalog import installable_skill_names
from omh.wrapper.contract import VISIBLE_ACTIONS


def _definition(name: str):
    for definition in builtin_definitions():
        if definition.name == name:
            return definition
    raise AssertionError(f"skill definition not found: {name}")


def _template_content(name: str) -> str:
    for template in builtin_skill_templates():
        if template.name == name:
            return template.content
    raise AssertionError(f"skill template not found: {name}")


class MemorySyncSkillTests(unittest.TestCase):
    def test_capture_lane_sends_past_session_history_to_the_session_store(self) -> None:
        # A retained record is context every later turn pays for, so the lane
        # has to separate a durable fact from conversation archaeology at the
        # only moment the choice exists. The bullet names the alternative
        # rather than only refusing, and claims no tool availability.
        body = _template_content("memory-new")
        self.assertIn("**Retrieve instead**", body)
        self.assertIn("session store", body)
        self.assertIn("when that tool is available", body)
        decision_block = body.split("## Candidate Decision", 1)[1].split("##", 1)[0]
        self.assertIn("**Retrieve instead**", decision_block)

    def test_memory_new_skill_registered_for_candidate_capture(self) -> None:
        self.assertIn("memory-new", installable_skill_names())
        definition = _definition("memory-new")
        self.assertEqual(definition.category, "memory")
        self.assertEqual(definition.hermes_role, "memory-keeper")
        self.assertEqual(
            recommend_module._SKILL_POLICIES["memory-new"].next_action,
            "prepare_memory_new",
        )
        required_triggers = {
            "memory-new",
            "new memory",
            "project memory",
            "product memory",
            "remember this project",
            "프로젝트 메모리 저장",
            "새 기억",
            "memory capture",
        }
        self.assertTrue(
            required_triggers.issubset(set(definition.triggers)),
            required_triggers.difference(set(definition.triggers)),
        )

    def test_memory_sync_skill_registered(self) -> None:
        self.assertIn("memory-sync", installable_skill_names())
        definition = _definition("memory-sync")
        self.assertEqual(definition.category, "memory")
        self.assertEqual(definition.hermes_role, "memory-keeper")
        self.assertEqual(
            recommend_module._SKILL_POLICIES["memory-sync"].next_action,
            "prepare_memory_sync",
        )
        required_triggers = {
            "memory-sync",
            "기억 정리",
            "메모리 정리",
            "메모리 점검",
            "기억 점검",
            "MEMORY.md",
            "USER.md",
        }
        self.assertTrue(
            required_triggers.issubset(set(definition.triggers)),
            required_triggers.difference(set(definition.triggers)),
        )

    def test_memory_new_and_memory_sync_generated_contracts_are_distinct(self) -> None:
        memory_new = _template_content("memory-new")
        memory_sync = _template_content("memory-sync")

        self.assertIn("memory_new_candidate/v1", memory_new)
        # The model captures a clear durable fact itself; no five-question
        # interview stands between the user's statement and the write.
        self.assertIn('call `omh_memory` with `action="capture"`', memory_new)
        self.assertIn("A clear durable fact needs no interview", memory_new)
        self.assertNotIn("Ask these five questions", memory_new)
        self.assertIn('`action="capture"`', memory_sync)
        self.assertIn("**Remember**", memory_new)
        self.assertIn("**Refuse**", memory_new)
        self.assertIn("**Defer**", memory_new)
        self.assertIn("not_omh_reviewed", memory_new)
        self.assertIn("model request", memory_new)
        self.assertIn("memory_curation_review/v1", memory_sync)
        self.assertIn("English-Canonical Interview Protocol", memory_sync)
        self.assertIn("Claim extraction (추출)", memory_sync)
        self.assertIn("no OMH surface invokes, applies, or observes a `MEMORY.md`/`USER.md` write", memory_sync)
        self.assertIn("not_omh_reviewed", memory_sync)
        self.assertNotIn("memory_new_candidate/v1", memory_sync)

    def test_memory_new_routes_capture_while_memory_sync_routes_existing_memory_review(self) -> None:
        capture_queries = (
            "memory-new",
            "new memory",
            "project memory",
            "product memory",
            "remember this project",
            "프로젝트 메모리 저장",
            "새 기억",
            "memory capture",
        )
        # These deliberately include the scope vocabulary memory-new also claims
        # ("project memory", "프로젝트 기억"). A scope noun names where a fact lives, not
        # what to do with it, so pairing it with curation intent must stay curation --
        # the direction that silently overrouted to capture before the phrase split.
        review_queries = (
            "review my MEMORY.md",
            "MEMORY.md",
            "USER.md",
            "기억 정리",
            "메모리 점검",
            "clean up my stale project memory",
            "review my stale project memory entries",
            "check my project memory for stale claims",
            "audit product memory for conflicting facts",
            "프로젝트 기억 정리해줘",
            "제품 기억 점검해줘",
        )

        for query in capture_queries:
            with self.subTest(query=query):
                result = recommend_module.recommend_skills(query, limit=1)[0]
                self.assertEqual(result["skill"], "memory-new")
                self.assertEqual(result["next_action"], "prepare_memory_new")

        refusal = recommend_module.recommend_skills("do not save this token", limit=1)[0]
        self.assertEqual(refusal["skill"], "memory-new")
        self.assertIn("refuse secrets", refusal["wrapper_guidance"])

        for query in review_queries:
            with self.subTest(query=query):
                result = recommend_module.recommend_skills(query, limit=1)[0]
                self.assertEqual(result["skill"], "memory-sync")
                self.assertEqual(result["next_action"], "prepare_memory_sync")

    def test_memory_curation_review_removed(self) -> None:
        self.assertNotIn("memory-curation-review", installable_skill_names())
        self.assertFalse(Path("skills/memory-curation-review").exists())
        self.assertNotIn("prepare_memory_curation_review", VISIBLE_ACTIONS)

    def test_memory_sync_skill_uses_english_protocol_and_preserves_korean_help(self) -> None:
        content = _template_content("memory-sync")
        for anchor in (
            "English-Canonical Interview Protocol",
            "Claim extraction (추출)",
            "Provenance (출처)",
            "Target (대상)",
            "Review (검토)",
            "Diff (차이)",
            "2,200 characters",
            "1,375 characters",
            "no OMH surface invokes, applies, or observes a `MEMORY.md`/`USER.md` write",
            "Apply after approval (적용)",
            "through the Hermes-native memory tool",
            "never becomes OMH mutation evidence",
            "stale_review_required",
            "expired_volatile_records",
        ):
            self.assertIn(anchor, content, anchor)

    def test_memory_sync_skill_names_who_supplies_the_material(self) -> None:
        """The protocol said "supplied" material and never named a supplier.

        `omh_memory` with `action="status"` has shipped since PR #672 and returns
        exactly the entry inventory this review needs, but nothing told Hermes to
        call it, so the review started from nothing and the card asked the user
        to ask again. One bullet turns a registered tool into a working loop.
        """
        content = _template_content("memory-sync")
        for anchor in (
            "Inventory (목록)",
            "omh_memory",
            'action="status"',
            "never entry text",
        ):
            self.assertIn(anchor, content, anchor)

    def test_memory_sync_skill_requires_entry_by_entry_confirmation(self) -> None:
        """A summary of the whole file with one question is not a review."""
        content = _template_content("memory-sync")
        for anchor in (
            "Per-entry confirmation (확인)",
            "quote it back",
            "keep, revise, or archive it before moving on",
            "cannot correct entry by entry is not a review",
        ):
            self.assertIn(anchor, content, anchor)

    def test_memory_sync_skill_teaches_the_preview_then_apply_attention_tier_flow(self) -> None:
        """Without this guidance the tier is a CLI feature Hermes never reaches,
        and the user is back to typing a control-plane command."""
        content = _template_content("memory-sync")
        on_disk = Path("skills/omh-memory-sync/SKILL.md").read_text(encoding="utf-8")
        for anchor in (
            "Attention (주의)",
            "omh memory attention <record-id> --tier <tier>",
            "The preview writes nothing.",
            "An attention tier is not a lifecycle state",
            "omh memory recall --include-archived",
        ):
            self.assertIn(anchor, content, anchor)
            self.assertIn(anchor, on_disk, anchor)

    def test_memory_sync_skill_lists_open_records_first_with_the_three_answers(self) -> None:
        """An open record is the person's own "not settled yet", and a review
        that starts from the stale/duplicate/conflict pass walks straight past
        it. The section puts open records first, with the age recall shows and
        the three answers the reminder offers, and forbids the assistant from
        picking one; a record nobody answered stays open rather than defaulting
        to keep-open (#1528)."""
        content = _template_content("memory-sync")
        on_disk = Path("skills/omh-memory-sync/SKILL.md").read_text(encoding="utf-8")
        for anchor in (
            "## Open Records",
            "list open records first, before the stale, duplicate, and conflict review",
            "Open records first (see Open Records below)",
            "`omh memory status`",
            "`counts.unresolved`",
            "`open_records`",
            "`open · N days unresolved`",
            "(reason `unresolved`), never `stale`",
            "`omh memory confirm <record-id>`",
            "`omh memory keep-open <record-id>`",
            "`omh memory retire <record-id>`",
            "never resolve, keep open, or retire on your own judgment",
            "A record with no answer stays open",
            "do not default it to keep-open",
            "The reminder only asks and writes no record",
        ):
            self.assertIn(anchor, content, anchor)
            self.assertIn(anchor, on_disk, anchor)
        open_section = content.split("## Open Records", 1)[1].split("\n## ", 1)[0]
        self.assertLess(content.index("## Open Records"), content.index("## Memory Boundaries"))
        for verb in ("**Resolved**", "**Still open**", "**Drop it**"):
            self.assertIn(verb, open_section, verb)

    def test_memory_sync_skill_context_rail_markers(self) -> None:
        markers = (
            "Workflow Lane",
            "Shared product, routing, compatibility, and evidence rules",
            "Prepared OMH routing",
        )
        template_content = _template_content("memory-sync")
        on_disk = Path("skills/omh-memory-sync/SKILL.md").read_text(encoding="utf-8")
        for marker in markers:
            self.assertIn(marker, template_content, marker)
            self.assertIn(marker, on_disk, marker)

    def test_memory_sync_full_only(self) -> None:
        self.assertNotIn("memory-sync", CORE_PROFILE_SKILLS)
        self.assertEqual(len(CORE_SKILLS), 5)
        self.assertEqual(len(CORE_PROFILE_SKILLS), 12)


class DocsRolesCommandTests(unittest.TestCase):
    def test_docs_roles_command_check(self) -> None:
        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "ROLES.md"

            status, stdout, stderr = run_cli(["docs", "roles", "--output", str(output)])
            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            self.assertTrue(output.exists())
            self.assertIn("written", stdout)
            self.assertEqual(output.read_text(encoding="utf-8"), roles_reference_markdown())

            status, _stdout, stderr = run_cli(["docs", "roles", "--output", str(output), "--check"])
            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)

            output.write_text(output.read_text(encoding="utf-8") + "\ndrift\n", encoding="utf-8")
            status, _stdout, stderr = run_cli(["docs", "roles", "--output", str(output), "--check"])
            self.assertEqual(status, 2)
            self.assertIn("role docs are stale", stderr)


class ResidualIdentifierScanTests(unittest.TestCase):
    def test_no_residual_memory_curation_review_identifier(self) -> None:
        # Build the forbidden identifiers by concatenation so this test file's own
        # source does not self-match. The exempt layer-3 spellings (memory_curation,
        # memory_curation_review/v1, ...) use underscores and cannot match these
        # hyphenated needles.
        skill_needle = "memory-" + "curation-" + "review"
        action_needle = "prepare_" + skill_needle

        repo_root = Path(__file__).resolve().parents[1]
        # Enumerate the committed repo tree via git; this naturally excludes .git,
        # gitignored operational state (.omc, .omx), build artifacts (build/),
        # node_modules, __pycache__, and *.pyc.
        listing = subprocess.run(
            ["git", "-C", str(repo_root), "ls-files", "-z"],
            capture_output=True,
            check=True,
        )
        tracked = [rel for rel in listing.stdout.decode("utf-8").split("\0") if rel]

        # test_memory_curation_review_removed legitimately references the literal
        # identifier to assert its absence, so exclude this test file itself.
        self_rel = Path(__file__).resolve().relative_to(repo_root).as_posix()

        offenders: list[str] = []
        for rel in tracked:
            if rel == self_rel:
                continue
            path = repo_root / rel
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if skill_needle in text or action_needle in text:
                offenders.append(rel)

        self.assertEqual(offenders, [], f"residual identifiers found in: {offenders}")


if __name__ == "__main__":
    unittest.main()
