"""Contracts for the production skills that read Hermes' native producers.

Hermes bundles document producers (`powerpoint`, `pdf`, `xlsx`, `docx`), an
image tool, browser tools, an exploratory web-QA skill (`dogfood`), monitor-mode
cron, and a meeting action-item skill. The production skills now name them, and
each one is evidence beside OMH's own gate, never the verdict. These pin:

* a producer result is judged by its own field, not its exit code: the render
  and recalculation scripts exit 0 with `"rendered": false` or
  `"recalculated": false`, and that leaves the rung not observed, while other
  observed evidence for a rung still counts;
* a portable body, which a non-Hermes host loads, scopes every Hermes-only
  name to Hermes, and the two browser skills' portable bodies name no Hermes
  browser tool;
* each rung a body names is a rung of the materials QA ladder for that format;
* a native tool a body relies on for a decision is named only in a sentence
  carrying the shared presence rule, never behind a version;
* a dogfood report, a silent monitor tick, a clean console read, and a
  meeting-notes extraction are each stated as less than a pass;
* `deliverable-package` and `ultraqa` state their own Why and Do-Not-Use.
"""

from __future__ import annotations

import unittest

from _local_package import load_local_package
from _skill_sentences import sentences

load_local_package()
from omh.plugin_bundle.omh.native_tools import native_tool_presence_clause
from omh.skills.catalog import builtin_definitions, omh_skill_display_name
from omh.skills.packaging import builtin_skill_templates
from omh.skills.render import agent_skill_templates, translate_sibling_mentions
from omh.workflows.materials import FORMAT_QA_LADDER

PRODUCTION_SKILLS = (
    "materials-package",
    "deliverable-package",
    "report-package",
    "img-summary",
    "visual-qa",
    "ultraqa",
    "deploy-and-monitor",
    "operating-rhythm",
    "meeting-brief",
)

DOCUMENT_QA_RULE = (
    "On Hermes, a rung taken from a bundled document skill is observed only from that skill's result for that "
    "exact file, judged by its field, not its exit code: `\"rendered\": false` or `\"recalculated\": false` exits 0 "
    "yet leaves that rung not observed, blocked on the missing tools it names; other observed evidence for a rung "
    "still counts."
)
# Pinned whole: every script, flag, and field in it was read at tag v2026.9.7
# and at upstream main 63d0b94120, and a one-word drift (`--meta` to `--text`)
# would point the model at a result that cannot show the rung.
DOCUMENT_RUNGS_RULE = (
    "On Hermes, the bundled document skills give these rungs when available (`powerpoint`, `xlsx`, `docx`; "
    "`microsoft-office` from v0.23; same scripts): PowerPoint gives `slide_count` (`pptx_read.py --outline`) and `render_screenshot` (`pptx_render.py` into a fresh directory, its image count "
    "matching `slide_count`, since it lists every image already in that directory); `pdf` gives `page_count` "
    "(`pdf_read.py --meta`) and `render_preview` (`pdf_page_image.py`); Excel gives `sheet_schema` (`xlsx_read.py "
    "--sheets`) and `formula_recalculation` (`xlsx_recalc.py --out <copy>`, since without `--out` it replaces the "
    "input and rungs or approvals already recorded were for other bytes, then the cached results read back with "
    "`xlsx_read.py --formulas`, where an error value or a formula with no cached value is a finding); Word gives "
    "`section_structure` and `required_clause_check` (`docx_read.py --structure` and `--text`) but no "
    "`page_count` or appearance until a converted PDF is rendered, and `docx_validate.py` checks package health, "
    "never rendering. Images that exist are not a render pass until each one has been inspected, and a "
    "producer's `\"ok\": true` is never the QA verdict."
)

# The rung each bundled document skill can show, by the ladder's own format
# key. Every rung named here must be a rung of that format's ladder.
PRODUCER_RUNGS = {
    "pptx": ("slide_count", "render_screenshot"),
    "pdf": ("page_count", "render_preview"),
    "xlsx": ("sheet_schema", "formula_recalculation"),
    "docx": ("section_structure", "required_clause_check", "page_count"),
}

NATIVE_CLAUSES = {
    "materials-package": (DOCUMENT_QA_RULE, DOCUMENT_RUNGS_RULE),
    "deliverable-package": (
        DOCUMENT_QA_RULE,
        DOCUMENT_RUNGS_RULE,
        "A file is `generated` only from the producer's read-back of the written file, `approved` only from the "
        "person's answer, and `attached` only from the destination's own read-back, never from a reply that names "
        "the file.",
    ),
    "report-package": (
        "On Hermes, that tool can be the bundled PowerPoint skill (`powerpoint`; `microsoft-office` from v0.23), "
        "and a deck it builds counts as generated from "
        "its read-back (`pptx_read.py --outline`).",
        # The shared document rule and the `powerpoint` half of the rungs rule,
        # composed from the same strings `materials-package` states.
        DOCUMENT_QA_RULE,
        "On Hermes, PowerPoint gives `slide_count` (`pptx_read.py --outline`) and `render_screenshot` "
        "(`pptx_render.py` into a fresh directory, its image count matching `slide_count`, since it lists every "
        "image already in that directory). Images that exist are not a render pass until each one has been "
        "inspected.",
    ),
    "img-summary": (
        "On Hermes, report image_generation_capability/v1 as `connected` when "
        f"{native_tool_presence_clause('image_generate', code=True)}, since Hermes offers that tool only while an "
        "image backend is configured, and as `prompt_only` otherwise; never infer it from a Hermes version, a "
        "provider key, or a model name.",
        "A supplied-image edit goes through that tool only when its own description offers to edit an existing "
        "image; when it says text-to-image only, the edit stays a prompt card.",
        "A result with `success: true` names the file or URL in `image` and backs one visual_generation_receipt/v1 "
        "attempt, with every route field the result does not state left unknown; a generated-image claim still "
        "needs visual_observation/v1, and visual QA and delivery stay separate.",
    ),
    "visual-qa": (
        f"On Hermes, when {native_tool_presence_clause('browser_vision', code=True)}, the session can take its own "
        "captures: each such render_capture_manifest/v1 entry records the `screenshot_path` it returned, the URL, "
        "the viewport width the page reported, and the target revision, and an entry missing any of the four is not "
        "evidence; captures from the wrapper, executor, or user still count.",
        "Score a round from the captured image itself, never from an auxiliary model's `analysis` text, which is "
        "what the capture tool returns when the session has no native vision.",
        "On Hermes, for the session's own captures, set each required viewport with `browser_cdp` "
        f"`Emulation.setDeviceMetricsOverride` when {native_tool_presence_clause('browser_cdp', code=True)} (Hermes "
        "offers it only with a CDP endpoint the user configured), then read the width back through `browser_console` "
        "(`window.innerWidth`) before the capture: each `browser_cdp` call opens its own connection, so the override "
        "may not hold, and a width that reads back other than the one requested is not that viewport.",
        "Without that tool, a width the browser does not already report is a named blocker for the session's own "
        "captures, and a capture of that width from the wrapper, executor, or user still counts.",
        f"On Hermes, when {native_tool_presence_clause('browser_console', code=True)}, read it after every navigation "
        "and every interaction in scope and record its errors in console_network_health/v1; a clean console read is "
        "console evidence only, never network, accessibility, or visual evidence.",
        "Exploratory bug-hunting goes to Hermes' bundled `dogfood` skill when it is available: its issues and "
        "screenshots enter this verdict only as observed findings bound to the target lineage, and a report with no "
        "issues is not a PASS.",
        # The handoff policy, which only the Hermes body renders.
        "observed evidence supplied by the wrapper, executor, or user, or taken by the session's own browser tools.",
    ),
    "ultraqa": (
        f"On a web app, when {native_tool_presence_clause('browser_vision', code=True)}, run each hostile scenario "
        "through the session's browser tools against the target the user named (local or staging unless stated), "
        "and a scenario that would submit, buy, send, or delete on a live surface waits for the user's approval; "
        "read `browser_console` after every navigation and interaction, and keep a failing scenario's "
        "`screenshot_path` and console errors as its observed evidence.",
    ),
    "deploy-and-monitor": (
        "On Hermes, a watchlist that must keep running after this turn is prepared as a native blueprint through "
        "`automation-blueprint` (a cron job whose `monitor` source, a health URL or a script whose output carries no "
        "timestamps, is the user's source, never one OMH writes), activated by the user or Hermes and never by OMH.",
        "On Hermes, the first monitor tick runs against a baseline with nothing to diff, so it is not a detected "
        "change; a silent tick says only that nothing was delivered (a no_change run, or an agent run that answered "
        "`[SILENT]`) and never that the release is healthy; a source that failed is an error, not a change; and what "
        "the job finds enters the post-deploy status only from its recorded runs (`hermes cron runs <job_id>`) and "
        "its open `hermes cron incidents`.",
    ),
    "operating-rhythm": (
        "Record each action item with its outcome, owner, due date, dependency, acceptance condition, and source "
        "reference, marking an owner or date the notes do not state as unknown, and keep a proposal that was "
        "discussed but not decided out of the decision log.",
        "On Hermes, when the bundled `meeting-action-items` skill is available, it may pull decisions, owners, and "
        "actions out of the supplied notes; its list is a reading of those notes, so every item keeps its source "
        "reference and stays unaccepted until the notes or the owner confirm it, and a ticket or message it drafts "
        "is reported as published only after the user approved it and it was read back.",
    ),
    "meeting-brief": (
        "Give the record template's action-item rows outcome, owner, due date, dependency, acceptance condition, "
        "and source columns, each marked unknown until the meeting record fills it.",
    ),
}

# The portable projection is what a non-Hermes host loads. `ultraqa` and
# `visual-qa` carry a reviewed portable quality bar, so their browser rules are
# stated there without Hermes tool names, and a viewport blocker there never
# outlaws a capture another tool supplied. `deploy-and-monitor`'s watchlist
# clause names a skill only Hermes ships, so it has a portable wording too.
# Every other clause above is shared by both projections.
PORTABLE_ONLY_CLAUSES = {
    "ultraqa": (
        "On a web app, run hostile scenarios against the target the user named (local or staging unless stated); a "
        "scenario that would submit, buy, send, or delete on a live surface waits for the user's approval.",
        "Read the browser console after every navigation and interaction, and keep a failing scenario's screenshot "
        "and console errors as its observed evidence.",
    ),
    # The Hermes watchlist clause names `automation-blueprint`, which only the
    # Hermes projection ships, so the portable body says it without the skill.
    "deploy-and-monitor": (
        "A watchlist that must keep running after this turn is prepared for a scheduler the user runs, with the "
        "user's own source (a health URL or a script whose output carries no timestamps, never one OMH writes), and "
        "is activated by the user, never by OMH.",
    ),
    "visual-qa": (
        "Bind each capture to its screenshot path, URL, the viewport width the page reported, and the target "
        "revision; an entry missing any of the four is not evidence.",
        "Score a round from the captured image itself, never from another model's text description of it.",
        "Set a viewport only through a tool that can, and read the width back before the capture; a width that reads "
        "back other than the one requested is not that viewport, and a width nothing could set is a named blocker "
        "unless a capture of it is supplied.",
        "Read the browser console after every navigation and every interaction in scope; a clean console read is "
        "console evidence only, never network, accessibility, or visual evidence.",
    ),
}
# Skills whose NATIVE_CLAUSES are stated in the Hermes body only.
HERMES_ONLY_CLAUSES = {"ultraqa", "visual-qa"}
# Single NATIVE_CLAUSES stated in the Hermes body only, each with a portable
# wording in PORTABLE_ONLY_CLAUSES.
HERMES_ONLY_CLAUSE_TEXTS = frozenset({NATIVE_CLAUSES["deploy-and-monitor"][0]})

# Hermes-only names. In a portable body a line naming one must say it holds
# on Hermes; the two browser skills carry none of the browser tool names.
HERMES_ONLY_NAMES = (
    "`pptx_",
    "`pdf_read.py",
    "`pdf_page_image.py",
    "`xlsx_",
    "`docx_",
    "`dogfood`",
    "`meeting-action-items`",
    "`hermes cron",
    "`image_generate`",
    "`browser_",
)
HERMES_SCOPE_MARKERS = ("On Hermes", "on Hermes", "Hermes'")
PORTABLE_BROWSER_SKILLS = ("ultraqa", "visual-qa")
HERMES_BROWSER_TOOLS = ("browser_console", "browser_vision", "browser_cdp", "screenshot_path")

# Native tools a body relies on for a decision. A sentence naming one carries
# the presence rule for that tool, so the decision is made on what this
# session was given, never on a version.
PRESENCE_GATED_TOOLS = ("image_generate", "browser_vision", "browser_cdp")



def _hermes() -> dict[str, str]:
    return {template.name: template.content for template in builtin_skill_templates()}


def _portable() -> dict[str, str]:
    return {template.name: template.content for template in agent_skill_templates()}


def _production_bodies() -> list[tuple[str, str]]:
    hermes, portable = _hermes(), _portable()
    return [
        *((f"hermes:{name}", hermes[name]) for name in PRODUCTION_SKILLS),
        *((f"portable:{name}", portable[omh_skill_display_name(name)]) for name in PRODUCTION_SKILLS),
    ]


class ProducerClauseTests(unittest.TestCase):
    def test_each_production_body_states_its_native_clause(self) -> None:
        hermes, portable = _hermes(), _portable()
        for name, clauses in NATIVE_CLAUSES.items():
            for clause in clauses:
                with self.subTest(skill=name, projection="hermes", clause=clause[:60]):
                    self.assertIn(translate_sibling_mentions(clause, owner=name), hermes[name])
                if name in HERMES_ONLY_CLAUSES or clause in HERMES_ONLY_CLAUSE_TEXTS:
                    continue
                with self.subTest(skill=name, projection="portable", clause=clause[:60]):
                    self.assertIn(translate_sibling_mentions(clause, owner=name), portable[omh_skill_display_name(name)])
        for name, clauses in PORTABLE_ONLY_CLAUSES.items():
            for clause in clauses:
                with self.subTest(skill=name, projection="portable", clause=clause[:60]):
                    self.assertIn(translate_sibling_mentions(clause, owner=name), portable[omh_skill_display_name(name)])
                    self.assertNotIn(translate_sibling_mentions(clause, owner=name), hermes[name])

    def test_the_portable_browser_skills_name_no_hermes_tool(self) -> None:
        portable = _portable()
        for name in PORTABLE_BROWSER_SKILLS:
            body = portable[omh_skill_display_name(name)]
            for tool in HERMES_BROWSER_TOOLS:
                with self.subTest(skill=name, tool=tool):
                    self.assertNotIn(tool, body)

    def test_a_hermes_only_name_in_a_portable_body_says_it_holds_on_hermes(self) -> None:
        # A non-Hermes host loads the portable body. A line there that names a
        # bundled Hermes script, skill, command, or tool must say it holds on
        # Hermes, so the host never reads it as a rule that blocks it.
        portable = _portable()
        naming = [
            (name, line)
            for name in PRODUCTION_SKILLS
            for line in portable[omh_skill_display_name(name)].splitlines()
            if any(marker in line for marker in HERMES_ONLY_NAMES)
        ]
        self.assertTrue(naming, "no portable production body names a Hermes-only name; the check would be vacuous")
        for name, line in naming:
            with self.subTest(skill=name, line=line[:80]):
                self.assertTrue(any(scope in line for scope in HERMES_SCOPE_MARKERS), line)

    def test_a_false_producer_result_is_never_stated_as_observed(self) -> None:
        # `pptx_render.py`, `pdf_page_image.py`, and `xlsx_recalc.py` exit 0
        # when their renderer is missing; only the field says so. Every
        # sentence that names the false field must leave the rung not observed.
        mentions = [
            (label, sentence)
            for label, content in _production_bodies()
            for sentence in sentences(content)
            if '"rendered": false' in sentence or '"recalculated": false' in sentence
        ]
        self.assertTrue(mentions, "no production body names a false producer result; the check would be vacuous")
        for label, sentence in mentions:
            with self.subTest(body=label, sentence=sentence[:80]):
                self.assertIn("exits 0", sentence)
                self.assertIn("not observed", sentence)

    def test_every_named_rung_is_a_rung_of_its_format_ladder(self) -> None:
        materials = _hermes()["materials-package"]
        for material_format, rungs in PRODUCER_RUNGS.items():
            for rung in rungs:
                with self.subTest(format=material_format, rung=rung):
                    self.assertIn(rung, FORMAT_QA_LADDER[material_format])
                    self.assertIn(f"`{rung}`", materials)


class PresenceRuleTests(unittest.TestCase):
    def test_a_presence_gated_tool_is_named_only_in_a_sentence_carrying_its_rule(self) -> None:
        bodies = [
            *((f"hermes:{name}", content) for name, content in _hermes().items()),
            *((f"portable:{name}", content) for name, content in _portable().items()),
        ]
        for tool in PRESENCE_GATED_TOOLS:
            clause = native_tool_presence_clause(tool, code=True)
            naming = [
                (label, sentence)
                for label, content in bodies
                for sentence in sentences(content)
                if f"`{tool}`" in sentence
            ]
            self.assertTrue(naming, f"no body names `{tool}`; the check below would be vacuous")
            for label, sentence in naming:
                with self.subTest(tool=tool, body=label, sentence=sentence[:80]):
                    self.assertIn(clause, sentence)


class OwnBoundaryTests(unittest.TestCase):
    def test_deliverable_package_and_ultraqa_state_their_own_why_and_do_not_use(self) -> None:
        definitions = {definition.name: definition for definition in builtin_definitions()}
        generic_lines = {
            # The feature-surface shape's generic lines.
            "The request is already handled by a narrower explicit skill with stronger evidence.",
            "The user asks OMH to secretly run external platforms, connectors, schedulers, file exports, or runtime agents.",
            "The only safe answer is to ask for missing authority, credentials, target, or observed evidence first.",
            # The catalog's fallback lines.
            "The request is casual chat, a status-only acknowledgement, or another workflow has stronger routing evidence.",
            "The user needs implementation, review, CI, merge, or external publishing evidence that has not been delegated or observed.",
        }
        for name in ("deliverable-package", "ultraqa"):
            with self.subTest(skill=name):
                definition = definitions[name]
                self.assertTrue(definition.why_this_exists.startswith(f"`{name}` exists because "))
                self.assertEqual(generic_lines & set(definition.do_not_use_when), set())


if __name__ == "__main__":
    unittest.main()
