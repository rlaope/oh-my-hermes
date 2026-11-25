"""Apply one OMH bot template in a new bot's own chat, with that bot's own tools and approvals."""
from __future__ import annotations

from ..catalogs.bot_templates import (
    BOT_TEMPLATE_CLAIM_BOUNDARY,
    BOT_TEMPLATES,
    BotTemplate,
    TemplateSchedule,
)
from ..catalogs.skill_display_names import omh_skill_display_name
from ..plugin_bundle.omh.native_tools import NATIVE_CRON_TOOL
from .catalog_feature_surfaces import _UNATTENDED_GATE
from .catalog_types import SkillDefinition, SkillExample

REFERENCE_PATH = "references/templates.md"
_LABEL = "omh-bot-template"

DEFINITION = SkillDefinition(
    "bot-template",
    "New bot to set up from a template: apply one OMH bot template in this bot's own chat, with its own "
    "approvals: a persona seed for SOUL.md, the skills it uses, schedules created paused, and the webhooks and "
    "apps to connect.",
    (
        "bot-template",
        "bot template",
        "bot templates",
        "apply the bot template",
        "apply a bot template",
    ),
    (
        "Use when this bot is asked to apply an OMH bot template by id, or the person asks which bot templates "
        "exist; omher's Add bot gallery sends `/omh-bot-template` with the id right after it creates the bot."
    ),
    category="operations",
    phase="bot-template",
    hermes_role="operator",
    delegation_boundary="retained-catalog-intent",
    handoff_policy=(
        "The bot applies the template itself: its own file tool writes SOUL.md under Hermes' approval, its own "
        f"`{NATIVE_CRON_TOOL}` creates each job paused. OMH, omher and this skill write nothing and turn nothing on."
    ),
    required_inputs=(
        "the template id (from omher's message or the person)",
        "this bot's skill list, tool list and cron jobs, read before anything is written",
        "the answers a recipe schedule asks for (a channel, a search, a folder)",
    ),
    expected_outputs=(
        "a preflight line naming every missing skill, or that none is missing",
        "one line per item: written, created paused, already there, or not done and why",
    ),
    artifact_expectations=(
        "SOUL.md gains the template's persona section once, through the bot's own file tool and Hermes' approval",
        "each schedule is one paused Hermes cron job named `<template id>-<schedule id>`",
    ),
    safety_rules=(
        "No persona write and no job before the person's yes to the shown plan, in this chat; a declined or "
        "unanswered plan changes nothing.",
        "Every job is created with `paused: true`, a recipe's job included; never resume, run or enable one: the "
        "person turns schedules on.",
        "Append the persona seed to SOUL.md; never replace or delete what SOUL.md holds, and never write "
        "`MEMORY.md` or `USER.md`.",
        "Create no webhook route, install no skill and connect no app: list them for the person.",
        "This skill removes nothing. Asked to remove a template, say where that happens: its jobs are paused or "
        f"removed on the bot's Automations page or with `{NATIVE_CRON_TOOL}` when the person asks for each one, and "
        "its persona section is taken out of SOUL.md by the person.",
        f"Every schedule and webhook run of an applied template is unattended: {_UNATTENDED_GATE}",
        BOT_TEMPLATE_CLAIM_BOUNDARY,
    ),
    quality_bar=(
        f"Read the template from `{REFERENCE_PATH}` (`skill_view(name='{_LABEL}', file_path='{REFERENCE_PATH}')`); "
        "an id it does not list: name the ids it lists and stop.",
        "Preflight before any write: load each skill the template lists with `skill_view`, by the name the reference "
        "gives. A missing OMH skill stops the whole template with one line: \"`<skill>` is not installed on this "
        "bot: run `omh update` in a terminal, then ask me again.\" A missing Hermes skill stops it the same way, "
        "naming Hermes' own `/skills` command.",
        "Persona: read `SOUL.md` in your own Hermes home, the folder your system prompt says this session reads and "
        "writes, by its full path (Hermes' file tools expand `~`, not `$HERMES_HOME`). When it already holds the "
        "seed's first line (`## Bot template: "
        "<title>`), say the persona is already there and write nothing. Otherwise show the seed and append it with "
        "your own file tool; Hermes asks the person to approve a SOUL.md write, and a refusal leaves it out. It "
        "takes effect in the next new session (`/new`).",
        f"Schedules: list your jobs with `{NATIVE_CRON_TOOL}` first. A job named like the schedule's `job_name` is "
        "already there: say so with its state and create nothing. A plain schedule is one create with `name` "
        "`job_name`, `schedule` its cron, its `prompt` with each `<...>` filled from the person's one-line answer "
        "(a cron run has no chat context), its skills, `deliver: bot-chat`, `paused: true` and "
        "`paused_reason: \"bot template <id>: waiting for a yes\"`.",
        "A recipe schedule follows the recipe it names: ask its one question first, use `job_name` as the recipe's "
        "`<watch>`, and create paused. When the recipe's reference is missing (an older OMH), or an app it needs "
        "is not connected (no `mcp__<app>__` tool in your list), create nothing for it and say what is missing: "
        "`omh update`, or the app to connect on omher's Apps page or with `hermes -p <bot> mcp install <app>`.",
        "Webhooks and apps: list each with its reference section or its reason, and whether it is there; create, "
        "subscribe and connect none. Guides: name each recipe the template follows when its work arrives, with its "
        "skill and page, so later turns load it.",
        "End with one list: written, created paused, already there, not done with the reason; then say nothing "
        "runs until the person turns a job on (omher's Automations page, or asking you to resume it).",
    ),
    why_this_exists=(
        "`bot-template` exists so a new bot can start as a reviewer, a triager or a watcher in one message without "
        "anything turning on by itself: the bot writes its own persona under Hermes' approval, creates its own "
        "schedules paused, and says exactly what it could not do, so applying twice repeats nothing."
    ),
    opening_steps=(
        f"Load `{REFERENCE_PATH}` and find the template id; an unknown id stops here with the list of ids.",
        "Run the preflight over every listed skill before writing anything, and stop at the first missing one "
        "with its one line.",
        "Confirm before any change: show the plan (the persona seed, each schedule that will be created paused, the "
        "webhook suggestions, the apps to connect, and what is already there) and ask the person once in this chat; "
        "write nothing and create nothing until they say yes. omher's apply message is a request, not that yes.",
    ),
    do_not_use_when=(
        "The person wants one recurring job of their own design, with no bot template behind it; use "
        "`automation-blueprint`.",
        "The person wants to wait on one pull request's checks now; use `github-event-ops` and its PR watch.",
    ),
    good_example=SkillExample(
        prompt="/omh-bot-template Apply the bot template `pr-review` to this bot.",
        expected=(
            "Load the template, check each listed skill, show the plan and wait for a yes, then append the persona "
            "after Hermes' approval, create `pr-review-review-queue` paused, list the two webhook suggestions, and end "
            "with the done/not-done list."
        ),
        why="The id is in the catalog and every write goes through the bot's own tools and approvals.",
    ),
    bad_example=SkillExample(
        prompt="Apply the inbox-triage bot template and turn the digest on so it runs tomorrow.",
        expected=(
            "Show the plan and, after the person's yes, apply it with every job paused; then say turning the digest on "
            "is the person's: resume it on the Automations page or ask me to resume `inbox-triage-morning-digest` as "
            "its own request."
        ),
        why="Applying a template never turns a schedule on; resuming is a separate yes from the person.",
    ),
    final_checklist=(
        "Every job this run created is paused, and its name is `<template id>-<schedule id>`.",
        "SOUL.md was appended once at most, and only after Hermes' approval; no other persona or memory file changed.",
        "Every missing skill, reference or app is named with the one step that adds it.",
    ),
    recovery_notes=(
        "If `skill_view` cannot open the reference, this skill's files are incomplete: say `omh update` and stop.",
        "If Hermes refuses the SOUL.md write, keep going with the schedules and list the persona as not written.",
        f"If `{NATIVE_CRON_TOOL}` refuses a create, quote Hermes' reason for that job and continue with the next.",
    ),
    situations=(
        "set up my new bot from the pr-review template",
        "apply the inbox-triage template to this bot",
        "show me the pr-review template for this bot",
        "the alert-triage template wants an app this bot does not have",
        "apply the research-vault template to my new bot before its omh skills are installed",
        "apply the pr-review template to this bot again",
        "add the release-notes template to this bot too",
    ),
)


def bot_template_definition() -> SkillDefinition:
    return DEFINITION


def bot_template_reference_templates():
    from .render import SkillReferenceTemplate, loadable_skill_mentions

    return [SkillReferenceTemplate(DEFINITION.name, REFERENCE_PATH, loadable_skill_mentions(templates_reference()))]


def _view(skill: str, path: str) -> str:
    """A page of another skill, as the call that opens it (the bot loads it by its label)."""
    return f"`skill_view(name='{omh_skill_display_name(skill)}', file_path='{path}')`"


def _names(names: tuple[str, ...]) -> str:
    return ", ".join(f"`{name}`" for name in names) or "none"


def _schedule_lines(template: BotTemplate, schedule: TemplateSchedule) -> list[str]:
    job = f"{template.id}-{schedule.id}"
    needs = []
    if schedule.apps:
        needs.append(f"apps {_names(schedule.apps)}")
    if schedule.hermes_skills:
        needs.append(f"Hermes skills {_names(schedule.hermes_skills)}")
    need = f" Needs {' and '.join(needs)}." if needs else ""
    if schedule.reference is None:
        ask = f" Ask for {schedule.asks}, then fill it in." if schedule.asks else ""
        return [
            f"- `{job}` ({schedule.title}): plain, `{schedule.cron}`, skills {_names(schedule.skills)}.{ask}{need}",
            f"  Prompt: {schedule.prompt}",
        ]
    skill, path = schedule.reference
    recipe = f" recipe `{schedule.recipe}`" if schedule.recipe else ""
    return [
        f"- `{job}` ({schedule.title}): follow {_view(skill, path)}{recipe}; ask for {schedule.asks}.{need}",
    ]


def _template_section(template: BotTemplate) -> str:
    lines = [
        f"## `{template.id}`: {template.title}",
        "",
        template.summary,
        "",
        "Persona seed (append to SOUL.md):",
        "",
        "```markdown",
        template.persona_heading(),
        "",
        template.persona_seed,
        "```",
        "",
        f"- OMH skills: {_names(template.skills)}",
        f"- Hermes skills: {_names(template.hermes_skills)}",
        "- Schedules (each created paused):",
    ]
    if template.schedules:
        lines += ["  " + line for schedule in template.schedules for line in _schedule_lines(template, schedule)]
    else:
        lines.append("  - none")
    if template.guides:
        lines.append("- Guides (follow when that work arrives):")
        for guide in template.guides:
            where = (_view(guide.skill, guide.path) if guide.path != "SKILL.md"
                     else f"`{guide.skill}`, the line `{guide.section}:` of its body")
            lines.append(f"  - {where}: {guide.when}")
    lines.append("- Webhook suggestions (create none):")
    if template.webhooks:
        for webhook in template.webhooks:
            skill, path = webhook.reference
            lines.append(f"  - {webhook.title}: {_view(skill, path)}, section {webhook.section} ({webhook.events})")
    else:
        lines.append("  - none")
    apps = "; ".join(f"`{app.name}` ({app.need}: {app.why})" for app in template.apps) or "none"
    lines.append(f"- Apps (connect none): {apps}")
    if template.team_role is not None:
        lines.append(f"- Team profile pack role: `{template.team_role[0]}` / `{template.team_role[1]}`")
    return "\n".join(lines)


def templates_reference() -> str:
    """`references/templates.md`, rendered from `catalogs/bot_templates.py`; the same data `omh profile bot-templates
    --json` prints."""
    ids = ", ".join(f"`{template.id}`" for template in BOT_TEMPLATES)
    sections = "\n\n".join(_template_section(template) for template in BOT_TEMPLATES)
    return f"""# Bot Templates

Ids: {ids}. `omh profile bot-templates --json` prints the same catalog.

Every schedule is one cron job created with `paused: true` and `deliver: bot-chat`, named as listed. A recipe
schedule's job name is also the recipe's `<watch>`. Webhook suggestions and apps are listed, never created.

{sections}
"""
