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

from omh.routing import policy
from omh.routing.localization import normalized_phrase, routing_tokens
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



# Each guard, by phrasing: True must fire it, False must not. The False rows are
# the over-capture a review measured (a phrase inside a longer word, an app name
# as a common noun, a read, a reply, a cadence, a secrets vault, a question).
GUARD_TABLE = {
    "app_work_intake_guard_applies": (
        (True, "turn Linear issue ENG-42 into a PR and link the PR back"),
        (True, "implement this Notion spec and open a PR"),
        (True, "build what this Confluence page describes and open a PR"),
        (True, "open a PR for Jira ticket PAY-118 and link it back on the ticket"),
        (True, "Jira 티켓 PAY-118 PR로 만들어줘"),
        (True, "turn this email into a task instead of replying"),
        (True, "이 메일 답장하지 말고 작업으로 만들어줘"),
        (True, "this Sentry alert fired, triage it and hand off a fix"),
        (True, "the Datadog monitor alert for checkout errors fired, investigate and fix it"),
        (True, "센트리 에러 알림 왔어 고쳐줘"),
        (True, "as soon as possible turn Linear issue ENG-3 into a PR"),
        (True, "Datadog monitor fired for high latency, investigate and fix it"),
        (True, "Sentry alert fired on checkout errors, triage and fix it"),
        (True, "Sentry alert fired for high latency, triage and fix it"),
        (True, "데이터독 지연 알림 떴어 원인 찾아서 고쳐줘"),
        (False, "open the PR linked in Jira ticket PAY-2"),
        (False, "create a private Notion page for the offsite"),
        (False, "create a pricing page in Notion"),
        (False, "move this Linear issue to project Apollo"),
        (False, "help me prioritize these Linear issues to prepare for the sprint"),
        (False, "make a presentation from this Notion page"),
        (False, "open a project in Linear for Q3"),
        (False, "implement linear interpolation for this issue"),
        (False, "build a linear regression page in my notebook"),
        (False, "I have a notion that this design is wrong, build the page differently"),
        (False, "build a Notion page for our team wiki"),
        (False, "deliver this Confluence page to the client"),
        (False, "ship the Jira ticket to QA"),
        (False, "테스트가 실패할지라도 PR 올려줘"),
        (False, "버그가 있을지라도 PR 만들어줘"),
        (False, "summarize this Notion page"),
        (False, "create a PR description for the Linear issue"),
        (False, "move this email into Workspace folder"),
        (False, "forward the email into a thread on Slack"),
        (False, "이 메일 작업으로 바빠서 못 본다고 답장해줘"),
        (False, "fix the Sentry integration error in our Next.js build"),
        (False, "debug Datadog agent errors on the staging host"),
        (False, "the Sentry SDK crashes the app on startup, fix it"),
        (False, "show me the latest Sentry alert"),
        (False, "every morning go through my inbox and turn work requests into tasks"),
        (False, "매일 아침 받은편지함 메일을 작업으로 만들어줘"),
        (False, "every weekday at 9 turn new Linear issues assigned to me into PRs"),
        (False, "tell me when a Linear issue is assigned and turn it into a PR"),
        (False, "apply the alert-triage template to this bot for our sentry alerts"),
        (False, "tell me when a Datadog monitor fires for high latency and fix it"),
        (False, "investigate high latency and fix it"),
    ),
    "meeting_to_issues_guard_applies": (
        (True, "turn the meeting transcript into Linear issues"),
        (True, "turn yesterday's meeting notes into Jira tickets"),
        (True, "make issues from the action items in today's standup notes"),
        (True, "회의록 내용으로 리니어 이슈 만들어줘"),
        (False, "which issues came up in the meeting notes"),
        (False, "translate this transcript for the support ticket"),
        (False, "회의록에서 이슈로 남은 것만 알려줘"),
        (False, "list the action items and open issues from yesterday"),
        (False, "summarize the meeting transcript"),
        (False, "file a GitHub issue for the bug mentioned in the meeting notes"),
        (False, "transcribe this voice memo and file the action items as Linear issues"),
    ),
    "vault_knowledge_guard_applies": (
        (True, "use my Obsidian vault as memory and write my daily journal there"),
        (True, "write today's daily journal in obsidian"),
        (True, "recall from my vault what we decided about pricing"),
        (True, "옵시디언 볼트에 매일 작업 일지 써줘"),
        (True, "recall what I wrote about RAG from my Obsidian vault"),
        (False, "open my vault"),
        (False, "HashiCorp Vault memory usage spiked overnight"),
        (False, "store these DNS records in Vault"),
        (False, "rotate the Vault audit records"),
        (False, "Obsidian uses too much memory, why"),
        (False, "M8 볼트 규격 기억나"),
        (False, "every morning research AI news and save a summary to my Obsidian vault daily journal"),
        (False, "every day collect papers on RAG and write them into my obsidian vault memory folder"),
    ),
}


class GuardTableTests(unittest.TestCase):
    def test_each_guard_fires_only_on_its_own_shape(self) -> None:
        for name, rows in GUARD_TABLE.items():
            guard = getattr(policy, name)
            for expected, message in rows:
                with self.subTest(guard=name, message=message):
                    self.assertIs(guard(normalized_phrase(message)), expected)

    def test_the_lanes_the_guards_stand_down_still_hold_their_own_sentences(self) -> None:
        # When a guard fires, connector-operator's guard stands down; when it does not, that lane keeps the sentence.
        for message, connector in (
            ("turn Linear issue ENG-42 into a PR and link the PR back", False),
            ("turn the meeting transcript into Linear issues", False),
            ("create a private Notion page for the offsite", True),
            ("move this Linear issue to project Apollo", True),
        ):
            query = normalized_phrase(message)
            with self.subTest(message=message):
                self.assertIs(policy._connector_operator_guard_applies(query, routing_tokens(query)), connector)

    def test_an_alert_about_latency_stands_the_status_card_down(self) -> None:
        # Latency in an alert to fix lit ops-observability's guard, which outscored app-work-intake's; a status read
        # of the same words keeps the status card.
        for message, status_card in (
            ("Datadog monitor fired for high latency, investigate and fix it", False),
            ("a Datadog monitor fired on p99 latency, fix it", False),
            ("show datadog latency status", True),
            ("Datadog latency is high, show me the monitor status", True),
        ):
            query = normalized_phrase(message)
            with self.subTest(message=message):
                self.assertIs(policy._ops_observability_guard_applies(query, routing_tokens(query)), status_card)


if __name__ == "__main__":
    unittest.main()
