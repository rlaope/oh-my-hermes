"""Cross-platform workflow skills: app-work-intake and the three extended skills.

Six workflows join Hermes' app tools. Three have no owner and are
`app-work-intake`'s recipes (spec to PR, inbox to work, alert to fix); three
extend the skill that already owns the entry point (operating-rhythm for a
meeting's issues, wiki for an Obsidian vault, frontend for a Figma frame).
These tests pin what each body must say, not that a live Hermes followed it.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from omh.skill_pack import builtin_skill_reference_templates, builtin_skill_templates
from omh.skills.catalog_feature_surfaces import _UNATTENDED_GATE

ROOT = Path(__file__).resolve().parents[1]


def _body(name: str) -> str:
    return next(template.content for template in builtin_skill_templates() if template.name == name)


def _reference(skill: str, relative: str) -> str:
    return next(
        template.content
        for template in builtin_skill_reference_templates()
        if template.skill_name == skill and template.relative_path == relative
    )


class AppWorkIntakeBodyTests(unittest.TestCase):
    def test_body_names_each_app_tool_and_stops_when_it_is_missing(self) -> None:
        body = _body("app-work-intake")
        for server in ("`notion`", "`atlassian`", "`linear`", "`sentry`", "`datadog`"):
            self.assertIn(server, body)
        for skill in ("`google-workspace`", "`himalaya`"):
            self.assertIn(skill, body)
        self.assertIn("`mcp__<server>__*`", body)
        self.assertIn("say which one is missing and stop: name `hermes mcp install <name>`", body)
        self.assertIn("never reach the app another way", body)

    def test_body_points_at_each_recipe_and_keeps_writes_behind_the_gate(self) -> None:
        body = _body("app-work-intake")
        for recipe in ("references/spec-to-pr.md", "references/inbox-to-work.md", "references/alert-to-fix.md"):
            self.assertIn(f"`{recipe}`", body)
        self.assertIn("`omh-apps`'s confirmation gate", body)
        self.assertIn("report it written only after reading it back from the app", body)
        self.assertIn("merge, force push, and a push to the default branch are always a person's", body)
        # The unattended rule is the producer's one sentence, so a change to it reaches this skill too.
        self.assertIn(_UNATTENDED_GATE, body)

    def test_body_defers_replies_to_hermes_inbox_triage(self) -> None:
        body = _body("app-work-intake")
        self.assertIn("load Hermes' bundled `email-inbox-triage` skill instead of this one", body)
        self.assertIn("email-inbox-triage]", body.split("---", 2)[1])

    def test_the_skill_ships_in_the_hermes_projection_only(self) -> None:
        self.assertTrue((ROOT / "skills/omh-app-work-intake/SKILL.md").is_file())
        self.assertFalse((ROOT / "agent-skills/omh-app-work-intake").exists())


class AppWorkIntakeRecipeTests(unittest.TestCase):
    def test_spec_to_pr_hands_each_middle_step_to_its_owner(self) -> None:
        recipe = _reference("app-work-intake", "references/spec-to-pr.md")
        for owner in ("`omh-plan`", "`ulw-work`", "`omh-commit-pr-authoring`", "`omh-apps`"):
            self.assertIn(owner, recipe)
        self.assertIn("There is\n  no default owner.", recipe)
        self.assertIn("Never invent criteria\n  from the title.", recipe)
        self.assertIn("the bot's own write is not a\nnew request", recipe)

    def test_inbox_to_work_never_replies(self) -> None:
        recipe = _reference("app-work-intake", "references/inbox-to-work.md")
        self.assertIn("never\na reply", recipe)
        self.assertIn("`email-inbox-triage`", recipe)
        self.assertIn("Hermes' `clarify` tool", recipe)
        self.assertIn("This page never sends, forwards, deletes, or unsubscribes.", recipe)

    def test_alert_to_fix_points_at_the_pr_watch_guards_instead_of_restating_them(self) -> None:
        recipe = _reference("app-work-intake", "references/alert-to-fix.md")
        self.assertIn("skill_view(name='omh-github-event-ops', file_path='references/pr-watch.md')", recipe)
        self.assertIn("sections 1-4", recipe)
        self.assertIn("section 5", recipe)
        # The cap values live in the PR watch page; this recipe must not carry a second copy.
        for restated in ("5 per 15", "two fix rounds", "2 rounds", "15 minutes"):
            self.assertNotIn(restated, recipe)
        self.assertIn("never\n  install it on a Sentry or Datadog route", recipe)
        self.assertIn("`omh-live-incident-response`", recipe)
        # The page it points at exists and still holds the sections it names.
        watch = _reference("github-event-ops", "references/pr-watch.md")
        self.assertIn("## 4. The fix-round cap", watch)
        self.assertIn("## 5. The own-PR guard and the burst cap", watch)


class ExtendedSkillTests(unittest.TestCase):
    def test_operating_rhythm_turns_a_meeting_into_issues_through_meeting_action_items(self) -> None:
        body = _body("operating-rhythm")
        line = next(line for line in body.splitlines() if line.startswith("- Meeting to issues:"))
        for name in ("`google-workspace`", "`teams-meeting-pipeline`", "`fireflies`", "`meeting-action-items`"):
            self.assertIn(name, line)
        self.assertIn("`hermes mcp install <name>`", line)
        self.assertIn("read back from the tracker", line)

    def test_wiki_vault_recipe_keeps_hermes_memory_and_review_first_records_intact(self) -> None:
        body = _body("wiki")
        self.assertIn("`references/vault-knowledge.md`", body)
        recipe = _reference("wiki", "references/vault-knowledge.md")
        self.assertIn("Hermes' `MEMORY.md` and `USER.md` are never copied, mirrored, or written", recipe)
        self.assertIn("A pending candidate, a refused one, or a retired\n  record never goes to the vault.", recipe)
        self.assertIn("never write to a path they did not\nconfirm", recipe)
        self.assertIn("never by import", recipe)

    def test_frontend_reads_a_figma_frame_and_the_portable_copy_drops_the_hermes_entry(self) -> None:
        body = _body("frontend")
        self.assertIn("`hermes mcp install figma`", body)
        hermes = _reference("frontend", "references/reference-token-extraction.md")
        self.assertIn("## Figma frame", hermes)
        self.assertIn("the frame is read, never\n  edited", hermes)
        portable = (ROOT / "agent-skills/omh-frontend/references/reference-token-extraction.md").read_text(encoding="utf-8")
        self.assertIn("## Figma frame", portable)
        self.assertNotIn("hermes mcp", portable)
        portable_body = (ROOT / "agent-skills/omh-frontend/SKILL.md").read_text(encoding="utf-8")
        portable_details = (ROOT / "agent-skills/omh-frontend/references/details.md").read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"hermes mcp install figma", portable_body + portable_details))


if __name__ == "__main__":
    unittest.main()
