"""Bot templates: the `bot_template/v1` catalog, its read path, the skill that applies one, and its routing."""
from __future__ import annotations

import contextlib
import io
import json
import re
import unittest

from _local_package import load_local_package

load_local_package()

from omh.catalogs.bot_templates import (  # noqa: E402
    APPLY_SKILL,
    MONITOR_RECIPES_REFERENCE,
    BOT_TEMPLATE_CATALOG_SCHEMA_VERSION,
    BOT_TEMPLATE_SCHEMA_VERSION,
    BOT_TEMPLATES,
    BotTemplateError,
    apply_message,
    bot_template,
    bot_template_ids,
    bot_templates_payload,
)
from omh.catalogs.playbooks import list_playbooks  # noqa: E402
from omh.commands.main import build_parser  # noqa: E402
from omh.core.errors import OmhError  # noqa: E402
from omh.routing.bot_template_cues import (  # noqa: E402
    bot_template_code_sense,
    bot_template_id_applied,
    bot_template_korean_match,
    bot_template_names_the_job,
)
from omh.routing import policy  # noqa: E402
from omh.routing.localization import normalized_phrase, routing_tokens  # noqa: E402
from omh.routing.policy import everyday_sense_phrase_unanchored  # noqa: E402
from omh.skills.catalog import installable_skill_names  # noqa: E402
from omh.skills.catalog_feature_surfaces import _UNATTENDED_GATE  # noqa: E402
from omh.skills.monitor_recipes import MONITOR_RECIPES  # noqa: E402
from omh.skills.packaging import builtin_skill_reference_templates, builtin_skill_templates  # noqa: E402
from omh.team_profiles import list_team_profile_packs  # noqa: E402

SKILL = "bot-template"
REFERENCE_PATH = "references/templates.md"
# Hermes' cron job name for a watch (`references/pr-watch.md`, `references/channel-watch.md`) and its profile id
# grammar (`hermes_constants.PROFILE_ID_RE`); a template's job name is also a recipe's `<watch>`.
WATCH_NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
# Hermes' MCP catalog entry names the templates use, read from `optional-mcps/` of a Hermes checkout (caafe5389a,
# 2026-11-19). The catalog is Hermes' own and is never read by core `omh`; this list only pins that a template names
# an entry that existed when it was written.
HERMES_MCP_CATALOG_NAMES = frozenset({"atlassian", "datadog", "grafana", "linear", "notion", "sentry"})
# Hermes' bundled skills the templates use, by folder name under `skills/<category>/` of the same checkout.
HERMES_BUNDLED_SKILLS = frozenset(
    {"email-inbox-triage", "github", "google-workspace", "meeting-action-items", "obsidian"}
)
# Rows of `automation-blueprint`'s `references/monitor-recipes.md`, by their config example's name: a renamed recipe
# fails here instead of leaving a dead name in a template.
MONITOR_RECIPE_IDS = frozenset(recipe.example.removesuffix(".json") for recipe in MONITOR_RECIPES)


def _reference(skill: str, path: str) -> str | None:
    return next(
        (t.content for t in builtin_skill_reference_templates() if t.skill_name == skill and t.relative_path == path),
        None,
    )


def _run(*argv: str) -> tuple[int, str]:
    args = build_parser().parse_args(["profile", "bot-templates", *argv])
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = args.func(args)
    return code, out.getvalue()


class BotTemplateCatalogTests(unittest.TestCase):
    def test_the_set_is_small_and_every_id_is_unique(self) -> None:
        ids = bot_template_ids()
        self.assertEqual(len(ids), len(set(ids)))
        self.assertGreaterEqual(len(ids), 6)
        self.assertLessEqual(len(ids), 8)
        for template_id in ids:
            self.assertRegex(template_id, WATCH_NAME)

    def test_payload_is_versioned_and_byte_stable(self) -> None:
        payload = bot_templates_payload()
        self.assertEqual(payload["schema_version"], BOT_TEMPLATE_CATALOG_SCHEMA_VERSION)
        self.assertEqual(payload["apply_skill"], APPLY_SKILL)
        self.assertEqual([t["id"] for t in payload["templates"]], list(bot_template_ids()))
        for row in payload["templates"]:
            self.assertEqual(row["schema_version"], BOT_TEMPLATE_SCHEMA_VERSION)
            self.assertEqual(row["coding_owner"], "selected")
        self.assertEqual(
            json.dumps(payload, sort_keys=True, ensure_ascii=False),
            json.dumps(bot_templates_payload(), sort_keys=True, ensure_ascii=False),
        )

    def test_every_schedule_is_paused_delivered_to_the_bot_and_named_as_a_watch(self) -> None:
        seen: set[str] = set()
        for row in bot_templates_payload()["templates"]:
            for schedule in row["schedules"]:
                self.assertIs(schedule["paused"], True)
                self.assertEqual(schedule["deliver"], "bot-chat")
                self.assertEqual(schedule["job_name"], f"{row['id']}-{schedule['id']}")
                self.assertRegex(schedule["job_name"], WATCH_NAME)
                self.assertNotIn(schedule["job_name"], seen)
                seen.add(schedule["job_name"])

    def test_a_plain_prompt_is_self_contained_and_silent_when_nothing_is_new(self) -> None:
        for template in BOT_TEMPLATES:
            for schedule in template.schedules:
                if schedule.reference is not None:
                    continue
                with self.subTest(job=f"{template.id}-{schedule.id}"):
                    self.assertEqual(len(schedule.cron.split()), 5)
                    self.assertIn("[SILENT]", schedule.prompt)
                    # A cron run has no chat context: every placeholder is filled from the person's answer.
                    if re.search(r"<[a-z]+>", schedule.prompt):
                        self.assertTrue(schedule.asks)
                    self.assertNotIn("named to you", schedule.prompt)

    def test_every_skill_reference_resolves_to_an_installable_skill(self) -> None:
        installable = set(installable_skill_names())
        for template in BOT_TEMPLATES:
            names = {*template.skills, *(s for schedule in template.schedules for s in schedule.skills)}
            with self.subTest(template=template.id):
                self.assertTrue(template.skills)
                self.assertLessEqual(names, installable)
                self.assertNotIn(SKILL, names)

    def test_hermes_skills_and_apps_are_names_hermes_ships(self) -> None:
        for template in BOT_TEMPLATES:
            hermes = {*template.hermes_skills, *(s for schedule in template.schedules for s in schedule.hermes_skills)}
            apps = {app.name for app in template.apps} | {a for schedule in template.schedules for a in schedule.apps}
            with self.subTest(template=template.id):
                self.assertLessEqual(hermes, HERMES_BUNDLED_SKILLS)
                self.assertLessEqual(apps, HERMES_MCP_CATALOG_NAMES)
                for app in template.apps:
                    self.assertIn(app.need, {"required", "optional"})
                # A schedule's app is one the template lists, so a surface can offer it.
                self.assertLessEqual({a for s in template.schedules for a in s.apps}, {app.name for app in template.apps})

    def test_team_roles_and_playbooks_are_existing_catalog_ids(self) -> None:
        packs = {pack["id"]: {role["id"] for role in pack["roles"]} for pack in list_team_profile_packs()["packs"]}
        playbooks = {playbook["id"] for playbook in list_playbooks()["playbooks"]}
        for template in BOT_TEMPLATES:
            with self.subTest(template=template.id):
                if template.team_role is not None:
                    pack, role = template.team_role
                    self.assertIn(pack, packs)
                    self.assertIn(role, packs[pack])
                self.assertTrue(template.playbooks)
                self.assertLessEqual(set(template.playbooks), playbooks)

    def test_recipe_and_webhook_references_name_shipped_reference_sections(self) -> None:
        for template in BOT_TEMPLATES:
            for webhook in template.webhooks:
                content = _reference(*webhook.reference)
                with self.subTest(webhook=webhook.id):
                    self.assertIsNotNone(content)
                    self.assertIn(f"## {webhook.section}\n", content)
            for schedule in template.schedules:
                if schedule.reference is None:
                    continue
                with self.subTest(schedule=schedule.id):
                    self.assertTrue(schedule.asks)
                    if schedule.recipe:
                        self.assertEqual(schedule.reference, MONITOR_RECIPES_REFERENCE)
                        self.assertIn(schedule.recipe, MONITOR_RECIPE_IDS)
                    else:
                        self.assertIsNotNone(_reference(*schedule.reference))

    def test_guides_name_a_shipped_recipe_page_or_body_line(self) -> None:
        bodies = {t.name: t.content for t in builtin_skill_templates()}
        guided = set()
        for template in BOT_TEMPLATES:
            for guide in template.guides:
                with self.subTest(template=template.id, guide=guide.skill):
                    self.assertIn(guide.skill, template.skills)
                    if guide.path == "SKILL.md":
                        self.assertIn(f"- {guide.section}: ", bodies[guide.skill])
                    else:
                        self.assertFalse(guide.section)
                        self.assertIsNotNone(_reference(guide.skill, guide.path))
                    guided.add((template.id, guide.skill))
        self.assertLessEqual({("inbox-triage", "app-work-intake"), ("meeting-to-issues", "operating-rhythm")}, guided)

    def test_persona_seeds_are_generic_and_never_open_a_link_or_name_a_person(self) -> None:
        for template in BOT_TEMPLATES:
            seed = template.to_dict()["persona_seed"]
            with self.subTest(template=template.id):
                self.assertTrue(seed.startswith(f"## Bot template: {template.title}\n\n"))
                self.assertNotRegex(seed, r"https?://|@|[A-Z][a-z]+ [A-Z][a-z]+ (?:Inc|LLC|Corp)")

    def test_apply_message_opens_with_the_skill_command_and_names_the_id(self) -> None:
        for template_id in bot_template_ids():
            message = apply_message(template_id)
            self.assertTrue(message.startswith("/omh-bot-template "))
            self.assertIn(f"`{template_id}`", message)
            self.assertEqual(bot_template(template_id).to_dict()["apply_message"], message)
        with self.assertRaises(BotTemplateError):
            bot_template("not-a-template")


class BotTemplateCommandTests(unittest.TestCase):
    def test_json_listing_is_the_catalog_payload(self) -> None:
        code, out = _run("--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), bot_templates_payload())

    def test_one_template_by_id(self) -> None:
        code, out = _run("pr-review", "--json")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["id"], "pr-review")
        self.assertIn("claim_boundary", payload)

    def test_an_unknown_id_is_an_error_naming_the_ids(self) -> None:
        with self.assertRaises(OmhError) as raised:
            _run("not-a-template", "--json")
        self.assertIn("pr-review", str(raised.exception))

    def test_text_listing_names_each_template_and_how_to_apply_it(self) -> None:
        code, out = _run()
        self.assertEqual(code, 0)
        for template_id in bot_template_ids():
            self.assertIn(f"{template_id}: ", out)
        self.assertIn("/omh-bot-template", out)
        # one template by id prints its own apply line
        code, out = _run("pr-review")
        self.assertEqual(code, 0)
        self.assertIn(f"Apply it in the bot's own chat: {apply_message('pr-review')}", out)
        self.assertNotIn("<id>", out)


class BotTemplateSkillTests(unittest.TestCase):
    def _body(self) -> str:
        return next(t.content for t in builtin_skill_templates() if t.name == SKILL)

    def test_reference_lists_every_template_with_its_persona_and_paused_jobs(self) -> None:
        reference = _reference(SKILL, REFERENCE_PATH)
        self.assertIsNotNone(reference)
        for template in BOT_TEMPLATES:
            self.assertIn(f"## `{template.id}`: {template.title}", reference)
            self.assertIn(template.persona_heading(), reference)
            for schedule in template.schedules:
                self.assertIn(f"`{template.id}-{schedule.id}`", reference)
        self.assertIn("`paused: true`", reference)

    def test_body_keeps_every_write_with_the_bot_and_nothing_turned_on(self) -> None:
        body = self._body()
        for required in (
            "`paused: true`",
            "Append the persona seed to SOUL.md",
            "never write `MEMORY.md` or `USER.md`",
            "`omh update`",
            "already there",
            "Create no webhook route, install no skill and connect no app",
            "`mcp__<app>__`",
            "(`/new`)",
        ):
            self.assertIn(required, body)
        # the unattended rule is the shared one, not a restatement
        self.assertIn(_UNATTENDED_GATE, body)
        # a plan and one yes before any change, omher's apply message included: what bounds a mis-route
        self.assertIn("Confirm before any change: show the plan", body)
        self.assertIn("write nothing and create nothing until they say yes", body)
        self.assertIn("omher's apply message is a request, not that yes", body)
        self.assertIn("No persona write and no job before the person's yes to the shown plan", body)
        self.assertIn("This skill removes nothing.", body)
        # no example reads as apply-immediately: each one that applies shows the plan first. Under universal
        # progressive disclosure the examples live in the skill's full contract, which the body points at.
        self.assertIn("references/full-contract.md", body)
        full_contract = _reference(SKILL, "references/full-contract.md")
        self.assertIsNotNone(full_contract)
        examples = full_contract.split("## Examples", 1)[1].split("\n## ", 1)[0]
        self.assertIn("- Expected behavior:", examples)
        for line in examples.split("\n"):
            if line.startswith("- Expected behavior:") and "apply" in line.lower():
                self.assertRegex(line, r"(?i)plan", line)
        first_steps = body.split("## First Steps", 1)[1].split("\n## ", 1)[0]
        self.assertIn("Confirm before any change", first_steps)
        # file tools expand `~`, not environment variables: the skill names the home by its full path
        self.assertNotIn("$HERMES_HOME/SOUL.md", body)

    def test_hermes_only_and_absent_from_the_portable_projection(self) -> None:
        from omh.skills.catalog_portable import PORTABILITY_HERMES_ONLY, skill_portability

        self.assertEqual(skill_portability("omh-bot-template"), PORTABILITY_HERMES_ONLY)


class BotTemplateRoutingTests(unittest.TestCase):
    def test_code_and_messenger_senses_keep_the_phrase_off(self) -> None:
        for message in (
            "create a discord bot template in python",
            "slack bot template repo on github",
            "use a bot template for my discord server",
        ):
            with self.subTest(message=message):
                self.assertTrue(everyday_sense_phrase_unanchored(SKILL, normalized_phrase(message)))
        # A template id beside a messenger is still the template; beside a language or code word it is not.
        self.assertFalse(bot_template_code_sense(normalized_phrase("apply the channel-watch bot template for slack")))
        for message in ("write a pr-review bot template in python", "pr-review 봇 템플릿 파이썬 코드 짜줘"):
            self.assertTrue(bot_template_code_sense(normalized_phrase(message)), message)

    def test_anchored_english_and_job_phrases_keep_it(self) -> None:
        for message in ("apply the pr-review bot template", "list the bot templates", "bot template"):
            with self.subTest(message=message):
                self.assertFalse(everyday_sense_phrase_unanchored(SKILL, normalized_phrase(message)))
        self.assertTrue(bot_template_names_the_job(normalized_phrase("apply the release-notes template to this bot")))
        self.assertTrue(bot_template_names_the_job(normalized_phrase("add the pr-review template to this bot")))
        # the bot sense is required: an id beside "template" alone does not say which template
        self.assertFalse(bot_template_names_the_job(normalized_phrase("apply the release-notes template")))
        self.assertFalse(bot_template_names_the_job(normalized_phrase("release notes template for the changelog")))
        # an id is also a file name: a repository's own template is edited, not applied, and a bare id is not enough
        for message in (
            "update the release-notes template in .github",
            "our pr-review template in the repo needs a checklist",
            "add a section to the pr-review template markdown",
            "the release-notes template for the changelog generator",
            "릴리즈 release-notes 템플릿 파일 수정해줘",
            "the pr-review template",
            "delete the inbox-triage bot template",
            "remove the pr-review template from this bot",
            "pr-review 봇 템플릿 삭제해줘",
            "build a bot from the release-notes template in python",
            "export the research-vault bot template as json",
        ):
            with self.subTest(message=message):
                self.assertFalse(bot_template_names_the_job(normalized_phrase(message)))

    def test_a_github_template_applied_to_a_bot_excuses_its_forge(self) -> None:
        # The forge is where the bot works, only beside a GitHub template's id, an apply verb and the word bot.
        for message in (
            "apply the pr-review template to this bot for our github prs",
            "set this bot up with the pr-review template for github pull requests",
            "apply the release-notes template to this bot for our gitlab merge requests",
            "이 봇에 깃허브 PR용 pr-review 템플릿 적용해줘",
        ):
            with self.subTest(message=message):
                self.assertTrue(bot_template_names_the_job(normalized_phrase(message)))
                self.assertTrue(bot_template_id_applied(normalized_phrase(message)))
        self.assertFalse(bot_template_code_sense(normalized_phrase("apply the pr-review bot template for our github prs")))
        for message in (
            "apply the pr-review template to our github repo",
            "apply the pr-review template to this bot in the github repo",
            "edit the pr-review template on github for this bot",
            "apply the inbox-triage template to this bot for our github issues",
            "apply the pr-review template to this bot for our github prs in python",
            "the pr-review template for this bot on github",
            "pr-review 봇 템플릿 깃허브 레포에 올려줘",
            "update the release-notes template in .github",
            "remove the pr-review template from this bot",
            # the apply must govern the template, be neither declined nor deferred, and carry no other action
            "don't apply the pr-review template to this bot, just review github PR 12",
            "이 봇에 pr-review 템플릿 적용하지 말고 깃허브 PR 12 리뷰해줘",
            "apply the label to this PR, the pr-review bot template can wait",
            "the github bot set the pr-review template label on PR 9",
            "apply the pr-review template to this bot and merge github PR 12",
            "이 봇에 pr-review 템플릿 적용하고 깃허브 PR 12에 코멘트 달아줘",
            "apply the pr-review bot template to the github action workflow",
            "apply the alert-triage template to this bot and fix the sentry alert that fired",
        ):
            with self.subTest(message=message):
                self.assertFalse(bot_template_id_applied(normalized_phrase(message)))
        self.assertTrue(bot_template_code_sense(normalized_phrase("apply a github bot template")))

    def test_the_stand_down_reads_the_apps_each_template_declares(self) -> None:
        # Pinned, so a template whose apps or Hermes skills change fails here and its stand-down is reviewed.
        from omh.catalogs.bot_templates import bot_template, bot_template_ids
        from omh.routing.bot_template_cues import _TEMPLATE_APP_NAMES

        declared = {
            template_id: {app.name for app in bot_template(template_id).apps} | set(bot_template(template_id).hermes_skills)
            for template_id in bot_template_ids()
        }
        self.assertEqual(
            declared,
            {
                "pr-review": {"github"},
                "inbox-triage": {"email-inbox-triage", "google-workspace"},
                "release-notes": {"github"},
                "alert-triage": {"sentry", "datadog", "grafana"},
                "meeting-to-issues": {"meeting-action-items", "google-workspace", "linear", "atlassian"},
                "research-vault": {"obsidian", "notion"},
                "channel-watch": set(),
            },
        )
        for template_id, names in declared.items():
            for name in names:
                self.assertIn(normalized_phrase(name), _TEMPLATE_APP_NAMES[template_id])
        self.assertNotIn("github", _TEMPLATE_APP_NAMES["inbox-triage"])

    def test_the_app_lanes_stand_down_for_a_template_applied_to_a_bot(self) -> None:
        for message, guard in (
            ("apply the pr-review template to this bot for our github prs", policy._github_event_ops_guard_applies),
            ("apply the alert-triage template to this bot for our sentry alerts", lambda q, _: policy.app_work_intake_guard_applies(q)),
            ("apply the meeting-to-issues template to this bot for our linear issues", policy._connector_operator_guard_applies),
            ("apply the research-vault template to this bot with obsidian", policy._research_department_guard_applies),
        ):
            query = normalized_phrase(message)
            with self.subTest(message=message):
                self.assertFalse(guard(query, routing_tokens(query)))
        # without the template the same lanes keep their sentences
        for message, guard in (
            ("review my github prs", policy._github_event_ops_guard_applies),
            ("apply the pr-review template to our github repo", policy._github_event_ops_guard_applies),
        ):
            query = normalized_phrase(message)
            with self.subTest(message=message):
                self.assertTrue(guard(query, routing_tokens(query)))

    def test_korean_counts_alone_or_anchored_and_never_as_code(self) -> None:
        for message, expected in (
            ("봇 템플릿", True),
            ("봇 템플릿 적용해줘", True),
            ("봇 템플릿 추천해줘", True),
            ("어떤 봇 템플릿 있어?", True),
            ("이 봇에 pr-review 봇 템플릿 적용해줘", True),
            ("봇 템플릿 만들어줘", False),
            ("디스코드 봇 템플릿 코드 짜줘", False),
            ("슬랙 봇 템플릿 레포 찾아줘", False),
        ):
            with self.subTest(message=message):
                self.assertIs(bot_template_korean_match(normalized_phrase(message)), expected)


if __name__ == "__main__":
    unittest.main()
