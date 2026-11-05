"""What OMH's research skills say about the skills Hermes bundles.

Hermes ships `grounded-citations` (a source ledger with a `verify` command),
`blocked-page-recovery`, `competitor-news-monitor`, `llm-wiki`, `arxiv`, and
`pdf`. The research skills used to restate what those do as prose rules
("cite the source behind each claim"), which nothing could observe. They now
route to the bundled skill when it is present and keep the evidence boundary
OMH adds: a citation check is reported from a run or as `not_observed`, and it
is never called fact verification.

These pin the sentences that carry that boundary, because the digest fixture
only says that a body moved and a `docs ... --check` gate cannot see a body
change at all. Each assertion names a whole clause on purpose: every body's
Runtime Evidence footer already contains the bare word `not_observed`, so an
assertion on the word alone passes with the rule deleted.
"""

from __future__ import annotations

import unittest

from omh.capabilities.skills import skill_capabilities
from omh.skills.catalog import installable_skill_definitions
from omh.skills.catalog_types import _CATEGORY_FINAL_CHECKLISTS
from omh.skills.render import agent_skill_templates, builtin_skill_templates
from omh.workflows.paper_learning import PAPER_LEARNING_SOURCE_STATES
from omh.workflows.source_finder import (
    SOURCE_FINDER_ACQUISITION_STATES,
    SOURCE_FINDER_OBSERVATION_PROVENANCE,
    SOURCE_FINDER_SOURCE_KINDS,
)

CITATION_SKILLS = ("web-research", "research-brief", "research")
TOUCHED_SKILLS = (*CITATION_SKILLS, "research-department", "source-finder", "paper-learning")
BUNDLED_SKILLS_NAMED_AS_OWNERS = ("grounded-citations", "competitor-news-monitor", "arxiv")
PORTABLE_BODIES = ("omh-web-research", "omh-research-brief", "ulw-research", "omh-source-finder", "omh-paper-learning")
CITATION_PORTABLE = ("omh-web-research", "omh-research-brief", "ulw-research")
# The field of the script's `info: stats:` line that shows a run checked nothing.
EMPTY_CHECK_FIELD = "`0 distinct source(s) cited`"


def _section(body: str, heading: str) -> str:
    """The text under one `## ` heading, up to the next one."""
    start = body.index(f"\n## {heading}\n")
    end = body.find("\n## ", start + 1)
    return body[start:end if end != -1 else len(body)]


class ResearchCitationLedgerTests(unittest.TestCase):
    hermes: dict[str, str]
    portable: dict[str, str]

    @classmethod
    def setUpClass(cls) -> None:
        cls.hermes = {template.name: template.content for template in builtin_skill_templates()}
        cls.portable = {template.name: template.content for template in agent_skill_templates()}
        cls.definitions = {definition.name: definition for definition in installable_skill_definitions()}

    def test_sources_are_registered_at_retrieval_time_in_the_runs_own_ledger(self) -> None:
        for name in CITATION_SKILLS:
            with self.subTest(skill=name):
                body = self.hermes[name]
                self.assertIn("When Hermes' bundled `grounded-citations` skill is available", body)
                self.assertIn("in its ledger when it is retrieved (`scripts/sources.py add`)", body)
                # The default ledger is profile-wide, and the flag is only
                # accepted ahead of the subcommand.
                self.assertIn("passed as `--ledger <path>` before the subcommand on every call", body)
                self.assertIn("Without the skill,", body)

    def test_the_citation_check_is_a_run_or_not_observed(self) -> None:
        clauses = {
            "web-research": (
                "When that ledger is in use, report the citation check from a run, or as `not_observed`:",
                "Without the ledger the citation check is `not_observed`.",
            ),
            "research-brief": (
                "and report the citation check from that run, or as `not_observed`:",
                "report the citation check as `not_observed`.",
            ),
            "research": (
                "When a human briefing is written, report the citation check from a run, or as `not_observed`:",
                "report the citation check as `not_observed`.",
            ),
        }
        for name in CITATION_SKILLS:
            with self.subTest(skill=name):
                body = self.hermes[name]
                self.assertIn("the exit status of `sources.py verify <draft>", body)
                self.assertIn("`0` is a pass and any other status is not", body)
                self.assertIn("carries no verbatim quote", body)
                for clause in clauses[name]:
                    self.assertIn(clause, body)

    def test_an_exit_zero_that_cited_no_source_is_not_observed(self) -> None:
        """`verify` exits 0 on a draft with no `[n]` in it, having checked nothing.

        One sentence in all three bodies: the verify rule is one shared string.
        """
        for name in CITATION_SKILLS:
            with self.subTest(skill=name):
                self.assertIn(
                    f"An exit `0` whose `info: stats:` line reads {EMPTY_CHECK_FIELD} checked nothing and is reported "
                    "as `not_observed`",
                    self.hermes[name],
                )

    def test_the_receipts_verify_follows_the_ledger_verify(self) -> None:
        """A receipt proves the page was opened, never that it supports the claim."""
        clause = (
            "After that verify, run `omh research receipts verify --citations <ledger> --draft <draft>` and report its "
            "fetched coverage from the run, or as `not_observed`; a receipt proves only that the page was opened in "
            "this session tree, never that it supports the claim"
        )
        bodies = {name: self.hermes[name] for name in CITATION_SKILLS}
        bodies.update({name: self.portable[name] for name in PORTABLE_BODIES if name in CITATION_PORTABLE})
        for name, body in bodies.items():
            with self.subTest(skill=name):
                self.assertIn(clause, body)
                self.assertLess(body.index("sources.py verify <draft>"), body.index(clause))
        for name in set(PORTABLE_BODIES) - set(CITATION_PORTABLE):
            with self.subTest(skill=name, absent=True):
                self.assertNotIn("omh research receipts verify", self.portable[name])

    def test_a_chat_only_answer_is_not_observed(self) -> None:
        self.assertIn(
            "and so is an answer given only in chat: `verify` reads a draft file and exits `2` without one, "
            "so write the answer to a file first when the check matters",
            self.hermes["web-research"],
        )

    def test_a_citation_check_is_never_called_fact_verification(self) -> None:
        self.assertIn(
            "it does not test whether a claim is true, so a passing citation check is never reported as fact verification",
            self.hermes["web-research"],
        )
        self.assertIn("it is a citation check, not fact verification", self.hermes["research-brief"])
        self.assertIn(
            "It is a citation check, not fact verification, and it never stands in for the contested-claim gate",
            self.hermes["research"],
        )

    def test_the_unverified_marker_never_carries_the_answer(self) -> None:
        body = self.hermes["web-research"]
        self.assertIn(
            "Mark background that rests on model knowledge `[unverified]` instead of citing it: the marker is for "
            "background the answer does not rest on and never carries the answer, and a contested claim with a "
            "single source keeps its citation and is stated as uncorroborated.",
            body,
        )
        # The rule it must not weaken is still in the same body.
        self.assertIn("a current-facts question is never answered from model recall", body)
        self.assertIn(
            "a claim that rests on model knowledge is marked `[unverified]` and listed as unresolved, never entered as evidence",
            self.hermes["research-brief"],
        )

    def test_research_brief_rows_carry_the_ledger_id_as_a_citation_and_the_quote(self) -> None:
        body = self.hermes["research-brief"]
        self.assertIn(
            "carry two more fields on every evidence row: the ledger id written as `[n]` - a bare number in a cell "
            "is not a citation to `verify`, so that row would go unchecked - and the verbatim quote",
            body,
        )
        self.assertIn("`sources.py quote <id> --text <quote> --from <page text file>`", body)
        self.assertIn("`sources.py verify <draft> --evidence`", body)

    def test_research_keeps_every_lane_on_one_run_ledger(self) -> None:
        body = self.hermes["research"]
        for name in CITATION_SKILLS:
            with self.subTest(skill=name):
                self.assertIn(
                    "Keep the run's ledger in a file of its own, passed as `--ledger <path>` before the subcommand on "
                    "every call: the default ledger is shared by the whole profile, and another run's reset rebinds "
                    "its ids.",
                    self.hermes[name],
                )
        self.assertIn(
            "Use parent-only serialized writes: lanes return observed source entries and quote refs; "
            "the parent registers URLs, attaches quotes, and remaps lane ids before drafting.",
            body,
        )
        self.assertIn(
            "Lanes never write the shared ledger.",
            body,
        )

    def test_research_sets_the_ledger_up_in_its_first_steps(self) -> None:
        # A lane briefed without the ledger path has already registered into
        # the profile-wide default by the time the quality bar is read.
        steps = self.definitions["research"].opening_steps
        self.assertEqual(len(steps), 1)
        self.assertIn("set the citation ledger up before the first retrieval", steps[0])
        self.assertIn("`sources.py --ledger <path> reset`", steps[0])
        self.assertIn("No lane resets it.", steps[0])
        body = self.hermes["research"]
        self.assertIn(steps[0], _section(body, "First Steps"))
        self.assertLess(body.index("\n## First Steps\n"), body.index("\n## Catalog Metadata\n"))

    def test_the_completion_checklist_names_the_citation_check(self) -> None:
        for name in CITATION_SKILLS:
            with self.subTest(skill=name):
                checklist = self.definitions[name].final_checklist
                self.assertEqual(checklist[:-1], _CATEGORY_FINAL_CHECKLISTS["research"])
                self.assertIn("an observed ledger verify run that cited at least one source, or as `not_observed`", checklist[-1])
                self.assertIn(checklist[-1], _section(self.hermes[name], "Completion Checklist"))
        self.assertIn(
            "Each evidence row that cites a ledger source carries the id as `[n]` and its quote",
            self.definitions["research-brief"].final_checklist[-1],
        )

    def test_what_omh_adds_is_still_in_the_web_research_bar(self) -> None:
        # The ledger sits beside OMH's own rules; it replaces none of them.
        body = self.hermes["web-research"]
        for kept in (
            "Name the question, freshness window, and version or jurisdiction scope before retrieving.",
            "Cite the source behind each claim and mark it official, practitioner, or unattributed.",
            "Bind every as-of claim to an eligible temporal_source_receipt/v1",
            "Stop at the answer: one retrieval round settles a lookup",
            "The ledger id sits beside the source class and the retrieval date and replaces neither.",
        ):
            self.assertIn(kept, body)

    def test_web_research_tries_blocked_page_recovery_once_and_only_hermes_names_the_skill(self) -> None:
        rule = (
            "If a source fails with HTTP 403, HTTP 429, a paywall, or a WAF or bot wall, "
            "load Hermes' `blocked-page-recovery` skill once for that source when it is available"
        )
        self.assertIn(rule, self.hermes["web-research"])
        self.assertIn("never as the live page", self.hermes["web-research"])
        portable = self.portable["omh-web-research"]
        self.assertNotIn("blocked-page-recovery", portable)
        self.assertIn("use the host's blocked-page recovery capability once for that source", portable)
        self.assertIn("never as the live page", portable)

    def test_research_department_carries_the_recurring_watch_rules(self) -> None:
        body = self.hermes["research-department"]
        for rule in (
            "write the watchlist and the materiality threshold down once, before the first run, and reuse them unchanged",
            "A source the run could not read is unknown coverage for that period and is named as a gap; "
            "it is never reported as a quiet period or as nothing new.",
            "Keep one cutoff per source and move it only for a source the run covered.",
            "Count by the underlying event, not by article or URL",
        ):
            self.assertIn(rule, body)

    def test_research_department_routes_to_bundled_skills_and_keeps_cron_observed_only(self) -> None:
        body = self.hermes["research-department"]
        self.assertIn(
            "when the watch area is a set of named companies and Hermes' bundled `competitor-news-monitor` skill "
            "is available, run the watch through that skill",
            body,
        )
        self.assertIn("the bundled `llm-wiki` skill is available, offer it as the store", body)
        self.assertIn(
            "A schedule stays a prepared job description in the plan and OMH creates no job. In a Hermes session "
            "the job is created with the `cronjob_manage` tool, and it counts as created only from that tool's "
            "observed result or a cron listing.",
            body,
        )
        # The existing boundary stays: a prepared plan is never cron creation.
        self.assertIn("Do not claim web retrieval, synthesis-tool query, knowledge-store write, cron creation", body)

    def test_source_finder_records_an_arxiv_result_as_an_observed_link(self) -> None:
        body = self.hermes["source-finder"]
        self.assertIn("For `paper` candidates, when Hermes' bundled `arxiv` skill is available", body)
        self.assertIn("record each entry it returns as `link_observed` with `hermes_tool` provenance", body)
        self.assertIn("a paper candidate stays `candidate_prepared` until a link is observed another way", body)
        # The states the line names are the workflow's own vocabulary.
        self.assertIn("paper", SOURCE_FINDER_SOURCE_KINDS)
        self.assertIn("link_observed", SOURCE_FINDER_ACQUISITION_STATES)
        self.assertIn("candidate_prepared", SOURCE_FINDER_ACQUISITION_STATES)
        self.assertIn("hermes_tool", SOURCE_FINDER_OBSERVATION_PROVENANCE)

    def test_paper_learning_maps_acquisition_to_source_state(self) -> None:
        body = self.hermes["paper-learning"]
        self.assertIn(
            "An entry that Hermes' bundled `arxiv` skill returned (search or id lookup) is `metadata_only` "
            "until paper text is read.",
            body,
        )
        self.assertIn(
            "Text that the bundled `pdf` skill's `pdf_read.py <file> --text` run returned is "
            "`file_text_extraction_observed` for the pages that came back with text",
            body,
        )
        self.assertIn(
            "when the `long-document-reading` skill is available, take the chunks from its page ranges",
            body,
        )
        self.assertIn("without it, plan numbered page ranges before reading", body)
        self.assertIn("metadata_only", PAPER_LEARNING_SOURCE_STATES)
        self.assertIn("file_text_extraction_observed", PAPER_LEARNING_SOURCE_STATES)

    def test_a_bundled_skill_declines_a_request_only_where_it_is_present(self) -> None:
        """A do-not-use line that names a bundled skill is conditional on it.

        The portable projection carries the same lines to hosts that ship none
        of these skills, where an unconditional line would decline a request
        and point at nothing.
        """
        named = [
            (name, skill, statement)
            for name in TOUCHED_SKILLS
            for statement in self.definitions[name].do_not_use_when
            for skill in BUNDLED_SKILLS_NAMED_AS_OWNERS
            if f"`{skill}`" in statement
        ]
        self.assertEqual(
            sorted({(owner, skill) for owner, skill, _ in named}),
            [
                ("research-department", "arxiv"),
                ("research-department", "competitor-news-monitor"),
                ("web-research", "arxiv"),
                ("web-research", "grounded-citations"),
            ],
        )
        for owner, _, statement in named:
            with self.subTest(skill=owner, statement=statement[:60]):
                self.assertTrue(statement.endswith("skill is available; load that skill."), statement)

    def test_every_hermes_side_line_in_a_portable_body_carries_its_condition(self) -> None:
        """The portable bodies keep these lines, so each must say when it applies.

        A host that ships no ledger script, no `arxiv` skill, and no
        `long-document-reading` reads the same body. A line that names one of
        them without a condition tells that host to run something it does not
        have.
        """
        hermes_side = ("sources.py", "`grounded-citations`", "`arxiv`", "pdf_read.py", "`long-document-reading`")
        conditions = ("is available", "When that ledger is in use", "returned")
        for name in PORTABLE_BODIES:
            lines = [line for line in self.portable[name].splitlines() if any(token in line for token in hermes_side)]
            with self.subTest(skill=name):
                self.assertTrue(lines, "no Hermes-side line in this body; the check below would be vacuous")
                for line in lines:
                    self.assertTrue(any(condition in line for condition in conditions), line[:160])

    def test_the_capability_rows_do_not_carry_the_bundled_skill_detail(self) -> None:
        """The capability payload shows the head of each quality bar, not this detail.

        Every bundled-skill line sits past the lines a capability row carries,
        so the per-request payload did not grow with the bodies.
        """
        rows = {str(row.get("id")): row for row in skill_capabilities()}
        for name in TOUCHED_SKILLS:
            with self.subTest(skill=name):
                row = rows[name]
                shown = " ".join([*row["quality_bar"], str(row["handoff_policy"]), *row["do_not_use_when"]])
                self.assertNotIn("bundled", shown)
                self.assertIn("bundled", self.hermes[name])


if __name__ == "__main__":
    unittest.main()
