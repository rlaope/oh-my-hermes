"""One-shot report of everything a catalog change knocks out of sync.

Adding a single skill invalidates counts, budgets, and generated artifacts at
once, but the test suite reveals them a few at a time: you fix what the run
showed, rerun the whole suite, and learn about the next one. An observed
session spent twelve full-suite cycles that way -- four of them chasing the
same byte budget down 305 -> 303 -> 299 -> 264, and one hunting a limit that
lived in `src/maintenance/release.py` rather than in a test.

This module recomputes every drift-prone value from source and reports the
whole set in one pass, with the sites that hardcode each one.

The expected values here do not replace the assertions in `tests/` -- those are
deliberate contracts (see `CLAUDE.md`). This is the index that says which ones
a change just invalidated. `tests/test_drift_registry.py` keeps the index
honest by checking that every declared site still contains the value it claims.

No source parsing: every live value comes from calling the real producer, and
every site is declared data. Sites are file paths, never line numbers, because
line numbers drift.

It is also the budget ledger: every per-turn and footprint budget is measured,
held with its limit and kind (`ratchet` or `ceiling`), and judged here, and
`skill_content_smoke` reads its budget verdicts from `drift_report()` rather
than comparing on its own.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, NotRequired, TypedDict

if TYPE_CHECKING:
    from ..skills.context_cost import SkillContextCostProfile


DRIFT_REPORT_SCHEMA_VERSION = "omh_drift_report/v1"


class DriftFindingBase(TypedDict):
    name: str
    describe: str
    sites: list[str]
    fix: str


class CountDriftFinding(DriftFindingBase):
    kind: Literal["count"]
    expected: int
    live: int


class BudgetDriftFinding(DriftFindingBase):
    kind: Literal["budget"]
    limit: int
    live: int
    over_by: int
    reviewed_exception: NotRequired[int]
    exception_reason: NotRequired[str]


class GeneratedDriftFinding(DriftFindingBase):
    kind: Literal["generated"]
    state: Literal["missing", "stale", "unreadable"]
    error: NotRequired[str]


class TapSkillsDriftFinding(GeneratedDriftFinding):
    missing: list[str]
    stale: list[str]
    extra: list[str]


DriftFinding = CountDriftFinding | BudgetDriftFinding | GeneratedDriftFinding


class DriftReport(TypedDict):
    schema_version: str
    ok: bool
    checked_count: int
    drift_count: int
    checked: list[str]
    drift: list[DriftFinding]
    next_action: str
    claim_boundary: str


@dataclass(frozen=True)
class CountMetric:
    """A value that must match exactly across every site that hardcodes it."""

    name: str
    describe: str
    live: Callable[[], int]
    expected: int
    sites: tuple[str, ...]


@dataclass(frozen=True)
class BudgetMetric:
    """A rendered size that must stay under a declared ceiling.

    `reviewed_exception` is an explicit, named allowance above the limit for
    growth a PR body has recorded and reviewers have accepted (plan §1.2 for
    the ULW fold). It is never a silent limit bump: the limit keeps its
    captured baseline value, the exception names the accepted overage, and
    both live at `limit_site`.

    `kind` is the policy that sets the limit. A `ratchet` is raised to exactly
    what the producer measured, with the reason recorded beside the constant.
    A `ceiling` carries standing headroom; when it records `measured` and
    `step`, the limit is `derive_ceiling(measured, percent, step)`.
    """

    name: str
    describe: str
    live: Callable[[], int]
    limit: int
    limit_site: str
    reviewed_exception: int = 0
    exception_reason: str = ""
    kind: Literal["ratchet", "ceiling"] = "ratchet"
    measured: int | None = None
    step: int | None = None


@dataclass(frozen=True)
class Limit:
    """A budget's limit as `limits()` reports it.

    `measured` is the producer reading the limit was derived from: the limit
    itself for a ratchet, the recorded measurement for a ceiling the headroom
    rule produced, and None for a ceiling set by hand -- its comment history
    may still record a reading, but no rule turned that reading into the value.
    """

    kind: Literal["ratchet", "ceiling"]
    value: int
    measured: int | None
    step: int | None


def derive_ceiling(measured: int, percent: int, step: int) -> int:
    """The headroom rule (P5 of the 2026-09-23 skill-budget study).

    The measurement plus `percent`, rounded UP to the next multiple of `step`
    (policy and reasons in src/maintenance/release.py).
    """
    with_headroom = -(-measured * (100 + percent) // 100)
    return -(-with_headroom // step) * step


@dataclass(frozen=True)
class GeneratedArtifact:
    """A committed file that must byte-match what the catalog renders today."""

    name: str
    path: str
    render: Callable[[], str]
    regenerate: str


def _chat_card_case_count() -> int:
    from ..quality.chat_card_coverage import build_chat_card_coverage_demo

    return int(build_chat_card_coverage_demo()["summary"]["case_count"])


def _route_hint_case_count() -> int:
    from ..quality.route_hint_alignment import build_route_hint_alignment_demo

    return int(build_route_hint_alignment_demo()["summary"]["case_count"])


def _routing_precision_case_count() -> int:
    from ..quality.routing_precision import build_routing_precision_demo

    return int(build_routing_precision_demo()["summary"]["case_count"])


def _routing_precision_intervention_case_count() -> int:
    from ..quality.routing_precision import build_routing_precision_demo

    count = build_routing_precision_demo()["summary"]["intervention_case_count"]
    return count if not isinstance(count, bool) else 0


def _installable_skill_count() -> int:
    from ..skills.catalog import installable_skill_names

    return len(installable_skill_names())


def _common_request_case_count() -> int:
    from ..quality.common_request_coverage import build_common_request_coverage_demo

    return int(build_common_request_coverage_demo()["summary"]["case_count"])


def _ulw_canonical_engine_count() -> int:
    from ..skills.catalog import ulw_inventory_payload

    return len(ulw_inventory_payload()["canonical_engines"])


def _ulw_alias_engine_count() -> int:
    from ..skills.catalog import ulw_inventory_payload

    return len(ulw_inventory_payload()["alias_engines"])


def _ulw_retired_engine_count() -> int:
    from ..skills.catalog import ulw_inventory_payload

    return len(ulw_inventory_payload()["retired_engines"])


def _awareness_primer_markdown_chars() -> int:
    from ..plugin_bundle.omh.turn_budget import render

    return len(render("primer_markdown"))


def _awareness_primer_context_chars() -> int:
    from ..plugin_bundle.omh.turn_budget import render

    return len(render("primer"))


def _awareness_workflow_context_chars_max() -> int:
    from ..plugin_bundle.omh.awareness import awareness_workflow_context_markdown
    from ..skill_pack import builtin_skill_templates
    from .release import DEFAULT_HERMES_SKILL

    names = {template.name for template in builtin_skill_templates()} - {DEFAULT_HERMES_SKILL}
    return max((len(awareness_workflow_context_markdown(name)) for name in names), default=0)


def _role_context_chars_max() -> int:
    from ..catalogs.roles import role_definitions, role_file_markdown

    return max((len(role_file_markdown(role)) for role in role_definitions()), default=0)


def _full_capability_section_chars() -> int:
    from ..capabilities.skills import skill_capabilities

    return len(json.dumps(skill_capabilities(), sort_keys=True, ensure_ascii=False))


def _full_capability_item_chars_max() -> int:
    from ..capabilities.skills import skill_capabilities

    return max(
        (len(json.dumps(item, sort_keys=True, ensure_ascii=False)) for item in skill_capabilities()),
        default=0,
    )


def _standalone_capability_section_chars() -> int:
    from ..plugin_bundle.omh.tools.capability_tool import standalone_skill_capability_items

    return len(json.dumps(standalone_skill_capability_items(), sort_keys=True, ensure_ascii=False))


def _standalone_capability_item_chars_max() -> int:
    from ..plugin_bundle.omh.tools.capability_tool import standalone_skill_capability_items

    return max(
        (len(json.dumps(item, sort_keys=True, ensure_ascii=False)) for item in standalone_skill_capability_items()),
        default=0,
    )


def _skill_index_chars() -> int:
    from ..skills.skill_index import skill_index_chars

    return skill_index_chars()


def _skill_index_line_max_chars() -> int:
    from ..skills.skill_index import skill_index_line_max_chars

    return skill_index_line_max_chars()


def _plugin_tool_schema_chars() -> int:
    from .per_turn_context import plugin_tool_schema_chars

    return plugin_tool_schema_chars()


def _pre_llm_call_context_chars_max() -> int:
    from .per_turn_context import pre_llm_call_context_chars_max

    return pre_llm_call_context_chars_max()


def _pre_llm_call_context_fallback_chars_max() -> int:
    from .per_turn_context import pre_llm_call_context_fallback_chars_max

    return pre_llm_call_context_fallback_chars_max()


def _full_skill_context_cost_profile() -> SkillContextCostProfile:
    from ..skills.context_cost import skill_context_cost_payload

    for profile in skill_context_cost_payload()["profiles"]:
        if profile["profile"] == "full":
            return profile
    raise KeyError("full profile missing from skill_context_cost_payload()")


def _full_profile_skill_body_chars() -> int:
    return int(_full_skill_context_cost_profile()["skill_body"]["bytes"])


def _full_profile_skill_body_repeated_chars() -> int:
    return int(_full_skill_context_cost_profile()["repeated"]["bytes"])


def count_metrics() -> tuple[CountMetric, ...]:
    return (
        CountMetric(
            name="chat_card_case_count",
            describe="Chat card coverage cases",
            live=_chat_card_case_count,
            # show-reel adds one dedicated production card.
            expected=91,
            sites=(
                "tests/test_cli.py",
                "tests/test_hermes_ux_quality.py",
                "tests/test_release_smoke.py",
            ),
        ),
        CountMetric(
            name="route_hint_case_count",
            describe="Route hint alignment cases",
            live=_route_hint_case_count,
            # show-reel adds one coverage hint and seven fixback alignment
            # cases for operations, the static-reference owner and ko/ja/zh.
            expected=218,
            sites=(
                "tests/test_cli.py",
                "tests/test_hermes_ux_quality.py",
                "tests/test_release_smoke.py",
            ),
        ),
        CountMetric(
            name="routing_precision_case_count",
            describe="Routing precision cases",
            live=_routing_precision_case_count,
            # The public-board contract adds three negative controls: a concept
            # question, a disclosure question, and a team's own board. The
            # scroll-motion lane adds three negatives for the frontend scroll
            # triggers: two parallax (astronomy, camera optics) and the
            # terminal-emulator scroll bug that pins the `scroll` hold-back.
            # The realtime voice lane adds four negatives that mention voice or
            # a receipt without asking about connector adoption: a translation
            # input, a definition question, a voice-memo file lookup, and a
            # billing receipt.
            # Protected-reference controls remain alongside the upstream corpus;
            # merged totals are re-derived from build_routing_precision_demo().
            # The long-document lane adds negatives that use its own words
            # in another sense (eleven): writing documentation, reading a repo file,
            # processing a refund, reading the room, writing a long document
            # (en/ko/ja/zh), translating a whole document, and a site walked
            # page by page, and a page number beside a port number.
            # The router-misroute round adds seven negatives that use a repaired
            # lane's own words in another sense: a browser window resized, disk
            # space running out, a heap leak beside a list of providers, a
            # Korean question about surveillance-camera video, and one per bare
            # verb held back from the continuous-watch phrases (keeping an old
            # API, buying a monitor, watching out for a race condition).
            # The application-threat-model lane adds six negatives that use its
            # own words in another sense: what threat modeling is, what a STRIDE
            # analysis is, a trust boundary asked as a domain-modeling term,
            # hitting one's stride, modeling churn, and a scale model.
            # The live-incident-response lane adds seven of the same shape:
            # three concept questions about the discipline (what an incident
            # commander does at a wildfire, what an incident response plan is,
            # what a war room is), a military rank, severity as a bug-tracker
            # field, a manufacturing line down for maintenance, and a
            # figurative outage.
            # #1688 adds twelve for the skill-name lane: two Kubernetes
            # restart-loop sentences (English and Korean) and one past-tense
            # `asked`, where the name matched inside a longer word; two
            # hiring sentences naming `backend`, where one word was credited
            # four times over; the three survey rows that reach their wrong
            # skill through the metadata fold instead of a name; two verbs
            # carrying the phrasings `plan` gained; an organisational remark
            # naming the frontend; and a recorded interview.
            # #1689 adds three: two senses of `serve` that are not a model
            # being served (a CDN, and people), and something broken up that
            # is not code.
            # The story close adds two, both about the same loose word:
            # `finance-analysis` carried the bare `close` out of the separate
            # tokens of "month-end close" and claimed a modal and a database
            # transaction. Only these two -- the lane shipped no chat trigger
            # of its own, so it contributed no positive cases and no
            # `story` negatives.
            # The Jev skills add seven: sentences that name Jev as a model, a
            # setting, or among options, or talk about its docs, pricing page,
            # or question format, none of which addresses Jev.
            # Strict guard trust adds one: a question about what a Playwright
            # task costs, the negative half of browser-operator's own-phrase
            # intervention case.
            # #1892 adds eight: four habits told with a cadence phrase and four
            # non-code fix commands on a product noun and a defect noun.
            # The #1893 review adds three: modals said of a person (advice,
            # obligation, belief), which stay narration.
            # The #1893 re-review adds five: a modal inside a subordinate or
            # reported clause, which does not make the main clause a request.
            # #1817 adds four: three turns the route question's decline
            # predicate declines (a one-word approval, a thank-you, a Choice
            # offering only `none`) and one four-candidate non-request it must
            # keep asking.
            # #1799 adds six: human agents, a database compaction, an app's API
            # bill, and a recursive function, none of which is an agent run;
            # and six more that carry the incident phrases themselves (goal
            # drift, redoing work, looping, context lost after compaction) in a
            # human or non-agent sense.
            # The design-reference lane adds six: a migration course, an email
            # footer, wrong chart numbers, NLP text splitting, a quarterly
            # theme, and a marquee signing, none of which names frontend.
            # The quoted/relay/URL masks (#2049) add five: a block-quoted
            # invocation, a relayed report, an arrow-relayed and a
            # sender-relayed invocation, and a workflow name in a URL path.
            # The ai-slop-cleaner OMC parity work adds thirty-eight, none of
            # which may dispatch: a question about what deslop means, a
            # subagent's quoted report, a plain "review this PR", and
            # anti-virus noise called slop (4); a code noun or cleanup verb with
            # no slop word -- a module that fails to load, "clean it up later",
            # "simplify this function" -- and a function that looks clean (4);
            # docs that explain AI slop, a slop word beside a stack of code
            # nouns, and layout code beside a list of code nouns, which the
            # two-word cap keeps a clarify (3); twelve uses of `anti-slop` as a
            # stance or a quality -- policies, rules, guidelines, and checks
            # for README, docs, pull requests, changes, and code, "the README
            # is anti-slop now", "update the anti-slop docs", "is the code
            # anti-slop?", "the module is anti-slop now" -- several of which
            # dispatched while the bare word was a trigger (12); a question
            # whether an anti-slop sweep finished, which dispatched without
            # `sweep` held back (1); five remarks about AI slop with a bare
            # appearance word ("looks better", "looks interesting", "looks like
            # this", "look the same"), which dispatched the cleaner while a
            # token check opened its context words (5); AI slop to clean out
            # of an inbox, video recommendations, a photo library, and blog
            # comments, which dispatched while `ai slop` counted as phrase
            # evidence whatever the target (4); and a Slack message, song
            # lyrics, a tweet, and a profile bio called AI slop, which
            # dispatched frontend while its appearance phrases counted on any
            # target (4); and a report that AI slop on a settings page comes
            # from a module, which dispatched the cleaner when its context
            # credit did not need the appearance phrase said whole (1).
            # The websearch-setup backend trigger adds two: deploying an app
            # backend, which named the setup guide in its shortlist while the
            # bare `backend` token was credited to it, and debugging an app's
            # web search backend, a clarify that must never become a dispatch
            # of the setup guide (2).
            # Its cost and free-tier phrases add three: a bare price question,
            # which became a clarify while `much` was credited to the setup
            # guide; a vendor free-tier question, which named the setup guide
            # while `free` and `tier` were; and an API cost complaint, which
            # named it while `costs` and `too` were (3). Its review adds two:
            # profiling an app's web extract backend, which dispatched the
            # setup guide while `web extract backend` was a trigger, and
            # building a web search backend, a clarify that must never become
            # a dispatch of the setup guide (2).
            # The research citation-ledger work adds five sentences that a
            # skill Hermes bundles owns, none of which may dispatch an OMH
            # research skill (these five only; the same requests phrased with
            # a `web-research` trigger still dispatch it): rebuilding the
            # Sources block of a draft from the citation ledger, a Korean
            # request to check a draft's citation ids against the ledger, an
            # arXiv category search, one scheduled run of an existing
            # competitor watch, and a news alert on one named company (5).
            # The kanban review-lane hand-off adds one: the literal prompt
            # Hermes' dispatcher opens every kanban worker with, a clarify that
            # must never offer code-review as its workflow (1).
            # The native Hermes command work adds five, each answered
            # directly: a loop on a timer in English, in Korean, and in the
            # native `/loop 5m` syntax, which dispatched the goal loop through
            # the bare loop word (3); and the turns Hermes writes for its own
            # `/plan` and `/loop` wakeup, which dispatched the ops card and
            # fell back as a file lookup (2).
            # The rest of Hermes' session-command turns add seven, each
            # answered directly: a `/goal` continuation and one after a failed
            # quality gate, which dispatched the goal loop (2); a goal-mode
            # kanban card's continuation and finalize nudges, which dispatched
            # the image-card skill (2); and the heartbeat, `/learn`, and
            # `/initiate-setup` turns, which dispatched automation, memory, and
            # toolbelt skills (3).
            # The review of that work adds four, each answered directly: a
            # `/plan` turn behind a shared session's sender prefix and one
            # behind a reply pointer, and a `/goal` turn behind a Discord
            # trigger note, which still dispatched ultrawork and
            # github-event-ops (3); and the native `/loop 1h30m` syntax, which
            # the single-unit interval check missed (1).
            # Its second review adds two, each answered directly: a loop on a
            # timer written with a short unit (`5 min`), and a bash while loop
            # on a timer, a code question that no longer gets `/loop` advice;
            # both dispatched the goal loop before.
            # The third review adds one, answered directly: a timed loop that
            # checks an event loop, which dispatched the goal loop before and
            # for one round read as a question about that code.
            # The fourth review adds one, answered directly: a typed `/loop`
            # with its cadence whose prompt names `ulw-loop`, which dispatched
            # the goal loop before.
            # Requests a skill Hermes bundles owns, and reviews of a work-board
            # card, add eighteen: two reviews of what sits on a kanban card and
            # a Trello card created for review, which dispatched `img-summary`
            # (3); three infrastructure diagrams with no code to read, which
            # dispatched `codebase-uml` (3); an article ingested into an LLM
            # wiki and an LLM-wiki-style knowledge base from PDFs, which
            # dispatched `research-department` (2); three LLM wikis of notes or
            # in a vault, which dispatched `wiki` (3); and building an LLM wiki,
            # two runs of the `simplify-code` skill, a PDF form, a PDF merge, a
            # workbook column and a Word text edit, clarifies already that pin
            # that none of them reaches an OMH wiki, cleanup or material lane
            # (7).
            # The `data-share-review` skill adds eight: a PII acronym question
            # and a shared doc, a redacted film and a photo mask, which use its
            # held-back words in their everyday sense; two GDPR questions and a
            # logging-pipeline change, which carry its phrases and must not
            # dispatch it; and an analysis of an already pseudonymized dataset,
            # whose finished state is not one of its phrases (8). Its first
            # review adds thirty-two: thirty requests that carry its phrases
            # but no file leaving the team, each of which dispatched it while a
            # phrase counted anywhere -- messages, tickets and PR comments,
            # code and libraries, Hermes settings, storage-wide scans, a vendor
            # contract, a definition, a personal account, and a screenshot --
            # and two that pin the held-back word "pii" (32). Its second
            # review adds twelve: requests that only mention redaction and a
            # file leaving -- delivering "customer details out", merging or
            # reviewing a pull request, a Slack message, a post, a blog post, a
            # translation, a reminder, a video, a vendor comparison, a sample
            # message -- none of which leads with a data-protection verb (12).
            # Its third review adds twenty-three: requests whose lead verb
            # removes something that is not personal data (vendor, product,
            # file or column names, pricing details, a flag, a header row,
            # markers), that remove the protection itself, that review a pull
            # request, notebook or slides, or that lead with another job
            # before a later clause (23). Its fourth review adds two: a lead verb
            # that is being defined ("de-identify means what exactly ...?",
            # "de-identify is the term we use ..."), which is not a command (2).
            # The spend-gate lane adds eleven sentences that use its words and
            # move no money for the person, none of which may name the gate:
            # rent already paid, a lunch budget, a government's spending cap, a
            # photo from a wallet, tests for a wallet-transfer feature, a
            # customer's payment question, slides placed in order, a git
            # checkout, HTTP 402 returned from one's own API, a model-provider
            # cost comparison, and paying attention to a log (11).
            # Its review adds thirty-nine more, each a sentence that dispatched
            # the gate or produced its route hint while a phrase alone counted:
            # payment UI, code, tests, docs, prompts and analytics built around
            # its phrases (a place-the-order button, a buy-it-for-me string, a
            # flaky saved-card test, a 402 header), questions about how payments
            # work, procurement purchase orders and requests, someone else's
            # payment, a pricing comparison, a past card purchase, and a
            # government's spending (39); and two statements about someone
            # else's purchase that the gate must not admit: someone placing an
            # order tomorrow, and a club buying for members (2). Admission then became
            # lead-anchored (the request, not the topic, must be a spend), and
            # four topic-shaped sentences pin it: a blog post on paying with a
            # saved card, a message saying the vendor was paid, a reminder to
            # pay rent, and which card is best to pay with (4). Only the
            # sentence's first verb counts, and its object must not end in a
            # thing being built: a purchase in a second clause after a
            # transcription, a checkout flow for card payments, and a broken
            # saved-card toggle (3). Its second review adds thirty-one that
            # dispatched or got the hint while the first word alone was read:
            # a lead used as a noun or idiom ("check out this article", "pay
            # attention", "tip:", "order 5512:", "order of events", "pay
            # stubs", "pay-per-request", "buy-side"), a phrase after the request
            # clause, a question, a statement about a feature ("pay with my
            # saved card returns a 500 error"), a UI label ("buy it for me
            # buttons", "my card toggle"), and test or seed data (31). Its
            # third review adds sixteen that a list of forbidden verbs missed,
            # each a phrase followed by something no request has after it: a
            # verb of another tense ("stopped working", "broke", "went live"),
            # a modal ("would be nice", "could confuse", "might be"), "or" (a
            # comparison), a noun ("card issuer", "option"), or an idiom ("buy
            # time", "pay a visit") (16). Its fourth review adds twenty-one
            # that an allowed first word let through ("pay with my card in
            # safari is broken", "buy it for me and wishlist are the two
            # CTAs"); the gate now also needs a request marker outside its
            # phrase -- "please", "can you", "go ahead", "hermes", an amount,
            # or "for me" -- and none of these has one (21). Its fifth review
            # adds five where an amount or "for me" follows a preposition
            # ("pay with my card for $0 orders is broken"); those count as a
            # marker only as the spend's object now (5). Its sixth review adds
            # four where "for me" follows one of the gate's phrases ("book with
            # my card for me never shows up on android"); the object is read
            # after the lead's own words now, so the lead does not count as one
            # (4). Its seventh review adds two where an object word comes before
            # the phrase ("book the flight with my card for me never shows up
            # on android"); a phrase now starts the object count again (2).
            # The final review of the upstream skill audit adds four: a Hermes
            # /blueprint seed, which is a host turn (1); the pre-spend card
            # under review, which is not an image card (1); and a loop on a
            # timer that checks a ticket price or a card payment, which spends
            # nothing and stays Hermes' /loop (2). Its follow-up adds one: a
            # version question about another tool ("what version of node
            # supports fetch"), which that audit's first parallel-tools wording
            # moved from a direct answer to a clarify naming parallel-tools (1).
            # Reading only the person's words on a gateway turn adds two: a
            # concept question behind a Discord trigger note, which the note
            # sent to web-research, and a thank-you under a reply quoting a
            # skill request, which the quote turned into the catalog picker (2).
            # Admitting spend and data-share requests the same way on the
            # router and the route hint adds three, each of which got the
            # spend-gate hint while the router left the gate out: a city
            # budget's spending cap looked at (1), the gate's spaced name alone
            # (1), and the gate's name as a greyed-out label (1). Its review
            # adds three that dispatched the gate while "gate" anchored a cap
            # or wallet phrase anywhere in the message: an airport gate, a red
            # CI gate and a gate number (3).
            # Sending Korean diagram, LLM-wiki and token/cost requests to the
            # right skill adds twenty-one. Seventeen dispatched before:
            # changing how an auth token is stored, code that lowers an API
            # call's cost, asking how a token is stored, a token consumer, a
            # token-usage limit feature and its middleware, a prompt that burns
            # fewer tokens, Kafka token-consumption logic, a Kafka token
            # consumer group and its consumer count, token usage parsed, a
            # token-usage test written, a field that shows token usage added,
            # token-usage monitoring turned off, and a request not to show token
            # usage, each on ops-observability-card (15); and an LLM wiki built,
            # spaced and unspaced, on wiki (2).
            # Notes organized into an LLM wiki asked with wiki leading (1).
            # Three hold the Korean diagram fix to the English boundary: sales
            # data visualized, and a cloud architecture diagram bare and with a
            # particle, none of which names codebase-uml (3).
            # Admitting Korean spend and data-share requests to their gates
            # adds twelve whose Korean words keep their everyday sense: a
            # payment system designed, a payment flow tested, a payment made,
            # no need to pay, a document approved (결재), a restaurant booked
            # and a phone charged, with nothing of money beside them (7); and
            # a screen shared, code written to mask personal data, a customer's
            # personal data deleted, personal data masked for no recipient, and
            # a name removed before sharing, which says none of the review's
            # phrases (5). Its review adds eight that named a gate while a
            # recipient counted by containment, a negated clause or a document
            # sent beside an amount was read as the request, or a processed
            # order as a payment: personal data masked in external logs and
            # deleted from an overseas department's list, masking instead of
            # sending, and cleaned test data uploaded to staging (4); a payment
            # and an order processed (2); and two loops that send a price alert
            # and a rules document (2). Its second review adds sixteen: an
            # amount or a card that pays for nothing -- a sponsor list, a
            # price, card details, a card report, a card-game tournament, and
            # two loops that subscribe to an alert and reprice a price list
            # (7); an honorific and a "없이" negation (2); 로 on a word that
            # starts with a recipient -- per vendor, per client, a foreign key,
            # a vendor-name sort (4); and exports to a spreadsheet, a CSV and a
            # backup folder (3).
            # The owner decision that a team inside the same company is
            # internal (2026-10-16) adds fourteen: English requests that send
            # to the dev team, the marketing team, QA, the test server, a
            # coworker, another department, the in-house data team and staging
            # (11, three of them without a file and already held on main); and
            # Korean ones shared with another department and a colleague and
            # uploaded to the QA environment (3). Its round-4 review adds one:
            # a patient CSV shared with our QA team, where "patient" says
            # whose records the CSV holds (1).
            # The plural-possessive masker fix adds one: a quoted workflow
            # name after "the users'" stays a reference, where the `'` of the
            # possessive used to pair with the quote's opener (1).
            # Bounding a data-share place by its sentence adds two: an export
            # sent to the dev team then called urgent, and a patient CSV
            # shared with our QA team then a "please hurry" (2, main dispatched
            # the review on the first and named it in the clarify on the
            # second); reading a Korean "-기 전에" clause as a step adds one
            # that masks customer information before it goes to the dev team
            # (1, main named the review in the clarify).
            # The Indonesian trigger pack adds six Indonesian chat turns it
            # must not route: five that phrases dropped from the pack reached
            # (a work plan, two ask-first instructions, a medicine reminder, a
            # parent's blood pressure) and a question about what a cron request
            # means, which must not dispatch (6).
            # The Vietnamese trigger pack adds eight: five English sentences
            # whose words fold to `vi` words (`can`, `ban`, `them`, `song`,
            # `chat`) and named a pack lane while the pack rule keyed on ASCII
            # (5); and three Vietnamese chat turns that carry a phrase's words
            # without the phrase, a family trip, a marketing plan question and
            # a slide layout, two of which dispatched under that rule (3).
            # `dag-ulw` adds five that must not name it: an Airflow DAG, a file
            # called dag, a declined dag ulw, a relayed dag ulw report and a
            # block-quoted dag ulw request (5).
            # The review of `dag-ulw` adds five: four questions about it that
            # are answered rather than run (what it is, explain it, how it
            # repairs, a run's result) and a function's fan-out, which is a
            # metric and not work to fan out (5).
            # The delta review adds eleven: a stop, cancel, status, progress or
            # log word said to dag ulw, in English and Korean, is about the run
            # in progress and starts no new one (11).
            # The dag-ulw routing follow-ups add nine: a Korean cancel with a
            # verb ending after other words and one after a word for the run
            # (2, both cancelled on main too); an order cancel and an upload
            # halt with no verb, which ask whether to stop the run or build
            # the thing (2, main cancelled the run); a polite request to
            # explain dag ulw (1, main clarified); a remark that the fan out
            # across the services is too high and a split of one paragraph
            # for a translation (2, main clarified, but Hermes' hint started
            # a run); and an explain request and a question about splitting
            # work into parallel lanes (2, main dispatched dag-ulw).
            # Their review adds ten: Korean cancels said politely (취소하세요),
            # with 부탁해, as 그만 돌려, after a modified word for the run
            # (진행 중인 작업) and after a stop adverb (즉시), and an English
            # stop after "can you" (6; main started a run on the first three,
            # cancelled the next two and clarified the last); a cancel with a
            # verb ending after six words, which asks (1, main started a run);
            # two polite questions that weigh dag ulw against another way (2,
            # main clarified); and "show me how to split" work (1, main
            # dispatched dag-ulw).
            # The delta review adds seven: Korean cancels said as 취소해줘요,
            # 정지해줘 and 지금 바로 취소 (3; main started a run on the first
            # two and cancelled the third); a cancel request said as a noun
            # and an order cancel with only 요 after it (2, main started a run
            # on both; the first cancels since the fifth review, the second
            # asks); a split weighed against overkill and a
            # request to stop using dag ulw (2, main dispatched dag-ulw).
            # The third review adds four, each a run on main: a stop of the
            # work on a cancel feature, read by its last stop word, and a
            # cancel followed by a restart, which ask (2); and asking how to
            # cancel dag ulw and whether it can be stopped, answered (2).
            # The fourth review adds seven: whether dag ulw was cancelled and
            # a cancel decided later, answered (2, answered on main too); the
            # work turned off with 꺼줘 after a word for the run, which asks
            # (1, main started a run); the other run cancelled (1, cancelled
            # on main too); and a sigil before a question about dag-ulw or
            # about cancelling it, in English and in Korean, which starts no
            # run (3, main dispatched dag-ulw).
            # The fifth review adds three, each a run on main: the cancel of
            # the work processed and a halt request sent for the run, which
            # cancel (2); and a cancelled run that keeps going, which cancels
            # it again (1).
            # The sixth review adds five, each a run on main: four status
            # checks before a past stop (check, show, look over, whether it
            # ended), answered; and cancel pressed while the run still goes,
            # which cancels it again (5).
            # The seventh review adds three, answered: two status checks of a
            # run that stopped (멈춘), which main ran, and whether cancel was
            # pressed, answered on main too (3).
            # The last review patch adds six, each a run on main: 멈춤 said to
            # dag ulw, which cancels; a status check of a run that stopped and
            # of whether it was cancelled, answered; "a halt is enough", which
            # asks; and help understanding a fan out and an explanation of how
            # to split, which are asked to be told (6).
            # A complaint, a question or a stop that opens with a skill's bare
            # name, each dispatched or run on main, answered (12): dag ulw
            # broke my build, dag ulw 또 실패했어, dag ulw 때문에 빌드 깨졌어,
            # and the same for ultrawork, ralplan, maestro, ultraqa,
            # code-review and the retired ralph; how to use ultrawork; a
            # question after dag ulw; ultrawork stop. Three stop words beside
            # other words after dag ulw, each a run on main, ask which (O7):
            # 결제 취소 처리해줘, 취소 버튼 눌러줘, cancel order (3).
            # The review adds nine, each answered: a yes-or-no question
            # after ultrawork, in English and Korean (2); a stop with its
            # reason after ultrawork and after dag ulw, and one said twice
            # (3); what is going on after ralplan and a factual question
            # after it (2); what app-debugging is (1); and a build broken
            # after using ultrawork, still a report (1) (9).
            # `market-research` adds ten that must not name it: a market
            # stall, a market sizing slide sent and a TAM SAM SOM chart posted,
            # TAM SAM SOM explained, a kill/pivot call over finished market
            # work, a blog post about the method, the method after a sentence
            # break, a method in a status note, the skill's name in passing
            # and the method's letters as cat names (10).
            # Its second review adds six: a question and an acronym question
            # that open on a method verb, a sizing run by legal, a sizing of a
            # pizza count, a pricing analysis on a pull request diff, and a
            # pricing analysis set beside value-based pricing in theory (6).
            # Its third review adds two method questions opened by "hey," and
            # "please," (2).
            # show-reel adds six non-production controls across EN/KO/JA/ZH.
            # Its fixback adds ten operation/reference/translation controls.
            # Its carry adds nine controls that dispatched it under the first
            # grammar: a film inside another request, a causative, the bare
            # noun (9); a first sentence asked rather than told and a
            # causative over a definite film with a relative clause (2); two
            # more asked first sentences and a causative with `on` (3).
            # Hermes' slash-skill scaffold read as the invocation typed adds
            # four, each dispatched on main from the skill body Hermes pasted
            # in: a question and a status word after /dag-ulw, and another
            # skill's slash turn with and without an instruction (4).
            # A question after the /dag-ulw sigil adds six, each dispatched
            # dag-ulw on main: a Korean question, how to use it, what is left,
            # whether CI passed, a question after a skill stacked on it, and a
            # Korean question in Hermes' scaffold (6).
            # A stop or a question after an explicit invocation adds ten, each
            # dispatched its skill on main: /ulw-work, /ulw-loop,
            # /ulw-interview, /omh-plan, /omh-code-review and
            # /omh-app-debugging stop, /ulw-plan what does this do?, /ulw-work
            # 그만, /ulw-plan 이게 뭐야?, and /ulw-work stop in Hermes' scaffold
            # (10). The rule after an explicit sigil adds five, each
            # dispatched on main: /ulw-work 停止 and /ulw-plan 何これ (their
            # skill), /omh-code-review 这是什么 (OMH's intro card), /dag-ulw
            # 停止 (a run), and /dag-ulw show me the run in Hermes' scaffold
            # (a plan) (5). A stop of the skill's own run adds five, each
            # dispatched its skill on main: /ulw-loop stop the loop,
            # /omh-code-review 리뷰 취소, /ulw-loop 그만해 비싸 (a stop said
            # with why), /ulw-work 别做了, and /omh-code-review what is
            # omh-code-review? (a question that names the skill) (5); the
            # Chinese question case moved from /omh-code-review to /omh-plan,
            # since after code-review "what is this" asks for the review.
            # A stop of a run word the first table lacked, in Japanese or as
            # a Korean compound, and a question about using the skill add
            # four, each dispatched on main: /ulw-research stop the research,
            # /ulw-loop ループを止めて, /omh-code-review 코드 리뷰 취소 (their
            # skill), and /omh-code-review 어떻게 써? (OMH's intro card) (4).
            # A question that names the skill by its label adds one,
            # dispatched its skill on main: /ulw-loop what is ulw-loop? (1).
            # A Korean stop then only fillers, a negation or what the person
            # is in the middle of adds six, each dispatched ultrawork on main:
            # /ulw-work 멈춰 일단, 멈춰 잠깐만, 취소해 이거 아니야, 그만해 그거
            # 아니야, 그만해 지금 회의 중, 멈춰 멈춰 멈춰 제발 (6). A question
            # that names ultrawork by its short name, /ulw-work what is ulw?,
            # and an uppercase sigil's stop, /ULW-LOOP stop the loop, add two,
            # each dispatched its skill on main (2).
            # Multi-part work to dag-ulw adds three: one fault said over every
            # test with one fix, and a question whether every PR merged,
            # stay answered, as on main (2); /ulw-work 멈춰 그거 아님 is a stop,
            # which dispatched ultrawork on main (1).
            # The review of #2232 adds three: a sweep asked not to happen, the
            # status of every open PR, and every file of one PR start no
            # graph run, as on main (3). Its probes add four more: every PR
            # reviewed only to be told which are safe, every PR said to be
            # checked, and every test run as one command start no graph run,
            # as on main (3); /ulw-work 멈춰 필요 없다 is a stop, as on main (1).
            # The structural fix adds three: every PR said merged, a summary
            # of every PR, and a merge on a condition start no graph run, as on
            # main (3). Its review adds five, each a clarify as on main: one PR
            # by its number in words, by its link, and by 풀리퀘 with a number
            # (3); a login that does not work in every service, with one fix
            # (1); and a push over every branch, one command (1). Its second
            # review adds five more, each a clarify or a fallback as on main: a
            # schedule over every PR (1), the tests of one PR singled out by a
            # modifier and of the current branch (2), and one fault said as
            # 안 돌아가 and as a symptom clause (2). PR 3 without a counter
            # stays one numbered PR, a clarify as on main (1). Its third
            # review adds four, each a clarify or a fallback as on main: a
            # frequency schedule and cron with a particle (2), and a count of
            # files and a count of PRs with no breadth word (2). Its fourth
            # review adds three, each a clarify or a fallback as on main: a
            # noun with 마다, an interval, and PR 하나 (3).
            # Three domain-science vocabulary controls (+3).
            expected=1071,
            # The one reviewed test pin. Every other test compares its payload
            # against build_routing_precision_demo() rather than a literal.
            sites=("tests/test_routing_precision.py",),
        ),
        CountMetric(
            name="routing_precision_intervention_case_count",
            describe="Routing precision intervention cases",
            live=_routing_precision_intervention_case_count,
            # The public-board contract adds two LLM-build interventions and the
            # agent-board cross-lane guard. The scroll-motion lane adds three
            # more: smooth scroll, a parallax hero, and the Korean phrasing.
            # The realtime voice lane adds four: adoption, a supplied trial
            # receipt, turn integrity with barge-in, and the Korean phrasing.
            # Direct and mixed-reference interventions remain alongside the
            # upstream corpus; the merged producer determines the exact total.
            # The long-document lane adds twenty: six reading requests across
            # English, Korean, Japanese, and Chinese, plus thirteen requests that
            # share its words and stay with their owners (slides, Word action
            # items, a paper by level, contract compliance review in two
            # languages, a large-PDF upload failure in four, a viewer crash, an
            # OCR pipeline, a section added to a long style guide, and a spec
            # page dated by a year).
            # The router-misroute round adds eight: a filling context window and
            # running out of context reaching budget review, a continuous watch
            # reaching the recurring-ops lane in Korean and in English (two
            # phrase families), a memory-provider comparison reaching its
            # declared owner, and the sense each of those displaced staying
            # where it was (terminology alignment, operations telemetry).
            # The application-threat-model lane adds five: four requests that
            # model a real application (a payment service, an attacker path
            # between two components, attack scenarios on an endpoint, abuse
            # cases on a flow) and one that keeps the agent's own prompt and
            # tool surface with `security-safety-review`.
            # The live-incident-response lane adds eight: five requests that
            # command an incident still open (an outage declared now, the
            # commander and severity question, a timeline to start, a temporary
            # mitigation with recovery unverified, a severity level and a
            # bridge) and three that keep the siblings it defers to -- a closed
            # incident with `reliability-review`, one customer's outage reply
            # with `support-operations`, and a healthy release watch with
            # `deploy-and-monitor`.
            # The CJK tier lane adds four: a ja and a zh pack phrase inside a
            # sentence, each pinned at clarify/medium with its skill still
            # named, and a zh phrase pinned bare at dispatch/high beside the
            # same phrase inside a question at clarify/medium. They record the
            # tokenisation tier gap as intended so a scoring change has to
            # move them deliberately (#1607).
            # #1688 adds one: `deep-interview` traded its bare `interview`
            # trigger for "interview me", so the form the skill is actually
            # asked for is pinned beside the negative control.
            # #1689 adds four: the three shipped skills that lost their own
            # home turf (live incident, model serving, breaking up a long
            # function), plus a real page operation, because the guard
            # ordering that stops `browser-operator` pre-empting an incident
            # must not cost it its own lane.
            # The Jev skills add forty-five: each skill's phrase and a
            # paraphrase, the partner swap, free-form questions that stay on
            # jev-ask, and sentences about Jev (descriptive, negated,
            # configuration, a maintainer's mention of a skill name, an
            # explicit non-Jev invocation) that keep their ordinary owner.
            # Strict guard trust adds one: a Playwright task reaching
            # browser-operator on its own phrase, once its guard-carried case
            # became a clarify.
            # #1892 adds three: a cadence request that still dispatches, a
            # command to fix a product crash that asks with the coding lane
            # first, and a report of the same crash that still triages.
            # The #1893 review adds seven: subject-initial and passive
            # scheduling requests (a directive modal or a delivery passive on a
            # noun-phrase subject) that must keep dispatching.
            # The achievements and wiki chat cards add two: a badge-progress
            # request and a wiki-from-notes request, each answered by its own
            # card instead of the generic acknowledgement.
            # #1817 adds three: a single-candidate clarify the route question's
            # decline predicate declines, and a one-word request and a
            # four-candidate clarify it keeps.
            # #1799 adds five: looping, repeated work, goal drift, context loss
            # and unexpected cost in an agent run, each reaching agent-debug.
            # The design-reference lane adds seven: chart theming, footer
            # design, neobrutalism, split-text animation, two Korean
            # dispatches, and a Korean logo marquee that names frontend.
            # The quoted/relay/URL masks (#2049) add three: an invocation
            # beside a URL, after a block-quote line, and after a relay header
            # line, each still dispatching.
            # Their review (#2049) adds nineteen that dispatched before the
            # masks and must keep dispatching: an apostrophe touching a link
            # (two), arrows and parentheses between ordinary names (six), the
            # person's own `[summary]`/`[result]` tags (two), a pasted `> error`
            # line before a Korean request, a leading link as the target
            # (four), punctuation ending a link (two), and a `>` that is not a
            # block-quote marker (two).
            # The ai-slop-cleaner OMC parity work adds twenty-one. To the
            # cleaner, each a dispatch: AI slop in a code directory, in a repo,
            # and in a module that needs cleanup, a no-edit deslop review, a
            # module that looks like AI slop with a cleanup verb, and a module
            # called AI slop to simplify without changing behavior (6); each a
            # clarify with the cleaner leading: an anti-slop pass, a function
            # (moved here from the negative corpus), a README, an essay, a PR
            # description, a layout module, and layout code (7). To
            # `frontend`, each a dispatch: `ai slop ui`, generic AI slop on a
            # landing page, a settings page that feels like AI slop, a pricing
            # page and a hero section that scream it, a pricing card component
            # file, an onboarding flow, and a nav menu that look like it (8).
            # The websearch-setup backend trigger adds one: switching the web
            # search backend to a free tier, a clarify with the setup guide
            # leading, which dispatched a live web lookup before (1).
            # Setup and cost phrasing adds five: configuring web search, a
            # dispatch of the setup guide; a web search cost complaint and the
            # keyless free web search tier, each a clarify with the setup guide
            # leading, all three of which dispatched a live web lookup before;
            # and two lookups about costs and free tiers that stay on
            # `web-research` (5). Its review adds one: setting the web extract
            # backend, a clarify with the setup guide leading, which led with
            # the lookup lane before (1). The second review adds six:
            # configuring Hermes' web search, switching it to the free tier,
            # and asking how to configure web search in Hermes, each a clarify
            # with the setup guide leading that dispatched a live web lookup
            # before; and three that must not reach the guide -- configuring
            # search for a store's catalog, which dispatched the guide, and in
            # a Next.js app, which asked with it leading, while "configure web
            # search" matched anywhere, and a cited free-tier comparison, which
            # became a clarify while "free web search tier" was a setup-guide
            # phrase (6). The third review adds three: a courteous "please
            # configure web search", a clarify with the setup guide leading
            # that dispatched a live web lookup before; and a cited comparison
            # of Hermes' web search and a check whether it is down, which
            # became clarifies while "hermes web search" counted without a
            # setup verb (3).
            # The kanban review-lane hand-off adds one: a bug hunt over the
            # diff attached to a kanban task, which stays a code-review
            # dispatch (1).
            # The native Hermes command work adds three loop dispatches that a
            # timer must not take away: an OMH `./loop` goal, the `./loop`
            # form on a timer, and a timed loop carrying a first-run goal.
            # Its review adds four more the timer had taken away: a named goal
            # loop and a Korean keep-improving loop on a timer, and the
            # `ulw-loop` skill named or run on a timer.
            # The second review adds four the timer still took: the sentence
            # that invokes the skill on a timer, by `ulw-loop`, by the catalog
            # name `loop`, and in Korean, and OMH's `$loop` behind a shared
            # session's sender prefix.
            # The third review adds three on the edges of the one verdict: an
            # OMH form behind a reply pointer and a sender prefix, a timed
            # loop asked to improve something, and `cto-loop` on a timer,
            # which keeps its own route.
            # The fourth review, which reads only a request's opening, adds
            # six: a skill invoked beside a timed loop and an invoked plan
            # about a polling loop on a timer, each keeping its skill; the
            # spaced `cto loop` trigger on a timer; a timed loop asked to lower
            # install friction; and `ulw-loop` named after a cadence on a flaky
            # list and on build failures, which now open the goal loop where
            # app-debugging and build-failure-triage took them before.
            # The bundled-skill boundary adds twelve on the OMH side of it: an
            # image card beside a kanban card, and a dashboard card and a
            # scoreboard card for a review, still reaching `img-summary` (3); a
            # class diagram of a cloud SDK module, an architecture diagram of
            # the codebase, one of an AWS CDK app, one of a cloud app from its
            # services folder, one of a services directory, and one of AWS
            # infrastructure from the src tree still reaching `codebase-uml`
            # (6); a team wiki in Notion still reaching `wiki` (1); and a
            # research department digest into an LLM wiki and a team's paper
            # research pipeline still reaching `research-department` (2).
            # The `data-share-review` skill adds ten: seven files leaving the
            # team with personal data to take out first -- for a vendor, a
            # fine-tune corpus, a public GitHub issue, a public tracker, a
            # contractor, a model provider, and a residual scan -- four of
            # which dispatched model-finetuning, GitHub event ops, the media
            # operator, or the connector operator before; and three that keep
            # three of those owners when nothing is to be taken out: a crash
            # log for a GitHub issue, a support transcript summary, and
            # fine-tuning on tickets (10). Its first review adds nine: a vendor
            # ticket export with the customer details to take out and a CSV
            # redacted before a vendor gets it, which must dispatch it; and
            # seven its phrases reached while counted anywhere, which stay
            # with GitHub event ops (labeling, closing, reviewing, triaging,
            # a workflow, a rerun) and web research (a blog post) (9). Its
            # second review adds four: a crash log redacted before a public
            # GitHub issue, pinned then to dispatch it and since the third
            # review to GitHub event ops, which holds the issue, and three
            # requests that only mention redaction, which stay with GitHub
            # event ops, the connector operator, and the gateway intent card
            # (4). Its third review removes the skill's boost and guard
            # stand-downs, so it
            # drops the three interventions only the boost dispatched (a vendor
            # ticket export with the PII to strip, one with the customer
            # details to take out, and a CSV redacted before a vendor gets
            # it), re-pins five to what ordinary scoring now does (four stay
            # with the guard that holds the issue, transcript or send, and the
            # fine-tune corpus one asks between the two owners), replaces the
            # residual-scan one with an export de-identified for a researcher,
            # and adds six requests other skills hold, three of them opening in
            # Hangul (+6, -3).
            # The spend-gate lane adds ten: seven spends that dispatch the
            # pre-spend card, or ask with it leading, without naming it (an
            # HTTP 402 to pay, a booking paid by card, a card purchase under a
            # stated cap, a timed-out payment the agent made, a wallet
            # transfer, a payment on the person's behalf, a purchase under a
            # stated total), and three that keep their owners: a checkout URL
            # login on browser-operator, payment failure reports on
            # feedback-triage, and budget vs actual for marketing spend on
            # finance-analysis (10).
            # Its review adds nine: five spends of the person's own money that
            # ask with the pre-spend card leading (a renewal with their card,
            # tickets on their credit card, a top-up with an amount, money to a
            # friend, a buy under a stated limit with a pricing check), and
            # four that keep their owners
            # (spend-approval best practices on web-research, a checkout Cypress
            # spec on feedback-triage, purchase acceptance criteria on ralplan,
            # a saved-card settings toggle on ultrawork) (9). Lead-anchored
            # admission adds one owner: triaging issues about card payments in
            # a checkout stays on feedback-triage (1). Its second review adds
            # two more checkout failure reports that stay on feedback-triage,
            # where the noun "checkout" was read as the verb (2). Its fourth
            # review adds three that keep their base dispatch: a 3DS failure
            # report and a crash report on feedback-triage, and a feature
            # request on plan (3).
            # The final review of the upstream skill audit adds nine: a loop on
            # a timer and a typed /loop whose prompt buys with the person's
            # card (2), a renewal and a top-up paid from the person's wallet
            # (2), the gate named as a command (1), and a card payment for a
            # report (1), all reaching the pre-spend card; tickets bought with
            # the person's credit card and shared, asking with the card leading
            # rather than as an image card (1); a share card of card-game stats
            # that stays on img-summary (1); and a /blueprint seed's first line
            # typed by a person, which stays on automation-blueprint (1). Its
            # review adds a share card with the person's card collection, which
            # stays on img-summary: "with my card" before a noun pays nothing (1).
            # Reading only the person's words on a gateway turn adds a card
            # payment behind a Discord trigger note, which the note sent to
            # gateway-intent-card instead of the pre-spend card (1). Its review
            # adds three whose leading bracket is the person's own -- OMH, a
            # skill's name, and `ulw` -- each of which lost its route while
            # every leading bracket was read as a sender prefix (3).
            # Admitting spend and data-share requests the same way on the
            # router and the route hint adds six, none of which reached its gate
            # before: a card payment opened with "kindly" and a purchase
            # opened with "pls", which mark a request as "please" does (2); an
            # export de-identified for a researcher opened with "hi," and with
            # "hermes," (2); a spending loop opened with "let's" (1); and the
            # gate run by name on the person's spending limit, which the cap's
            # everyday sense withdrew before the named gate was exempted from
            # it (1).
            # Sending Korean diagram, LLM-wiki and token/cost requests to the
            # right skill adds eleven. Five reach codebase-uml, which no
            # Korean diagram request reached before: a codebase diagram, the
            # codebase visualized, a class diagram with a particle attached, a
            # class diagram of a cloud SDK module, and a codebase diagram
            # beside "클라우드의", where a Korean code word keeps the diagram
            # beside a Korean cloud word (5). One reaches ops-observability-card,
            # which main sent to live-info-operator: a weekly token-usage report
            # named as the last word (1). Twenty-three keep their base dispatch:
            # a team wiki on wiki (1); token usage monitored, token consumption
            # asked about, token burn complained of, the token-usage trend
            # asked for, API cost monitored, token usage per feature and per
            # function, this week's token usage as a bare noun phrase, cost
            # monitoring with 해줘 said apart, and one sentence for each report
            # predicate (check, compare, track, how much, how is it, a polite
            # show-me), a spaced ending before "!", 해 줘 as two words, and 보여
            # 주세요, 알려 줘 and 확인해 주세요 with the auxiliary written apart, on
            # ops-observability-card, which the dropped bare 토큰 and 비용
            # triggers carried before (20); and a token-usage API built and a
            # token-usage bug fixed, which stay on ultrawork (2).
            # Admitting Korean spend and data-share requests to their gates
            # adds nine: a card payment and a spending loop that reach the
            # pre-spend card (2); a payment and a remittance asked with only
            # the verb, which ask with the card leading (2); customer
            # information masked for a vendor, personal data removed before an
            # external share, and personal data masked before it goes to a
            # vendor, which reach the data share review (3); and a payment bug
            # fix and a shared summary, which stay on ultrawork and
            # long-document-reading (2). Its review adds four: a card payment
            # after a greeting sentence and masked customer information for a
            # vendor addressed to Hermes, which reach their gates (2); and a
            # receipt that states an amount and a quote sent instead of paying,
            # which stay on gateway-intent-card (2).
            # The owner decision that a team inside the same company is
            # internal (2026-10-16) adds eight where an outside word qualifies
            # the team or place, so the data share review still dispatches: an
            # external team, the customer's team, the client team and a
            # partner's staging server in English (4, each dispatched on main
            # too); and an external team spaced and written as one word, a
            # vendor's team, and a vendor's test server in Korean (4). Its
            # review makes an inside place one proven inside, and adds twelve
            # that keep the review: a team named by a company, a company's
            # data team, a hospital team, the Department of Health, a former
            # colleague now at another company, a company's staging server, a
            # data team at another company's office, the data team and a
            # company, an auditor copied, a forward on to a company, and the
            # customer success team (11); and a Korean send to the QA team
            # then to a public site (1). Its re-review adds three that keep
            # the review: a company that sees the export before the send, a
            # copy given to a company, and a company's data team named in
            # quotes (3).
            # The plural-possessive masker fix adds one: the users' export
            # sent to a company's team, where the `'` of the possessive used
            # to mask the send and the place (1).
            # Reading every word before a Korean place, and every sentence,
            # adds seven that keep the review, none dispatched on main: a
            # member file a partner will use, a file for a partner, a member
            # list for a partner, papers an outside auditor will see, and the
            # dev team then a vendor in a later sentence (5); and in English an
            # export sent where a company wants it, and one a company wants
            # delivered, named in the next sentence (2).
            # The Indonesian trigger pack adds eleven requests that route
            # differently without it: code review (bare phrase, request, and a
            # sentence), accessibility audit (bare and a WCAG sentence), build
            # failure (bare and a sentence), a RAG pipeline, parallel
            # implementation, verify-before-merge and a screenshot check (11).
            # The Vietnamese trigger pack adds eleven requests that route
            # differently without it: code review (bare phrase, a request, and
            # a PR sentence), accessibility audit (bare and a WCAG sentence),
            # build failure (bare and with a compile error), an implementation
            # plan, deep research, verify-before-merge and a rendered-page
            # check (11).
            # `dag-ulw` adds six that start it: the name opening a request,
            # with a Korean ending, in reverse order (`ulw dag`), as a slash
            # command and after `with`, and parallel feature work across
            # modules that never names it (6).
            # Big work by intent, measured against main: seven requests that
            # reach `dag-ulw` without naming it, four English and three Korean
            # (7), and thirteen that must not move to it: five single fixes or
            # features whose concurrency word names the subject, two Airflow
            # DAG requests that stay with data-pipelines, coordinated workers,
            # ultrawork named as `ulw`, `ulw-work` and `ultrawork`, and `ulw`
            # named mid-sentence in English and in Korean (13).
            # The review of `dag-ulw` adds three single fixes that must stay
            # on ultrawork: a Korean cache bug when two requests arrive at
            # once, a queue named for parallel work, and a slow parallel
            # implementation of one function (3).
            # The dag-ulw routing follow-ups add five: two polite requests
            # that put the name after "can you" and "could you please" (2,
            # main clarified); a Korean order-cancel feature to build, which
            # runs rather than cancels (1, dispatched on main too); a Korean
            # cache that breaks when two named modules request at once, which
            # stays one ultrawork fix (1, main dispatched dag-ulw); and failing
            # tests in two Korean modules fixed in parallel, which still reach
            # dag-ulw (1, dispatched on main too).
            # Their review adds four that still reach dag-ulw, each dispatched
            # on main too: broken tests in two Korean modules fixed 병렬로
            # 각각, a split proposed as "can we ...?", a Korean split asked
            # with 해줄 수 있어?, and a split beside a README paragraph fix (4).
            # The delta review adds two: a Korean cache that breaks when two
            # named modules process at once, which stays one ultrawork fix (1,
            # main dispatched dag-ulw); and a polite request naming two targets
            # with "or", which starts a run (1, main clarified).
            # The third review adds two that still start a run, as on main:
            # resolving a payment-cancel issue and turning off dark mode (2).
            # The fourth review adds three that still start a run, as on main:
            # checking a cancel history and registering a shutdown hook, whose
            # verbs no word list names, and a refactor that stops if it fails
            # (3).
            # The fifth review adds two: a re-run of the run cancelled earlier
            # (1, dispatched on main too); and a sigil question followed by a
            # request for work, still a command (1, dispatched on main too).
            # The sixth review adds four that start a run, each dispatched on
            # main too: a restart and a re-run of the cancelled run with no
            # comma, a redo that is not the cancelled run, and a sigil question
            # with a request after the question mark (4).
            # The seventh review adds three resume requests for a halted run
            # (이어서, 계속, 마저 해줘), each dispatched on main too (3).
            # The last review patch adds a 멈춤 button to build, which still
            # starts a run, as on main (1).
            # A failure named after a skill's bare name that is still the
            # work, or a report with a request after it, each dispatched on
            # main too: ultrawork fix the broken build, dag ulw the build that
            # broke, ralplan the failed migration, /dag-ulw broke the build,
            # ultrawork failed again then rerun it, dag ulw 또 실패했어 then
            # 다시 돌려줘, dag ulw 실패한 테스트 고쳐줘, and ultrawork the
            # build is broken (8).
            # The review adds ten, each dispatched on main too: a question
            # that deliberates the work after ralplan (1); a use clause then
            # a request, for ultrawork and dag ulw (2); credit then a
            # request for more (1); the name said again as the request (1);
            # a report then one more time, or 다시 (2); a status question
            # to app-debugging and running-work-board, whose work it is (2);
            # and a kill switch for flags with dag ulw (1) (10).
            # `market-research` adds four requests that lead with its method:
            # TAM SAM SOM sizing, a customer evidence analysis, a competitive
            # pricing analysis of named tools, and market sizing after a
            # courtesy opener (4).
            # show-reel adds nine interventions: four unnamed production
            # requests, the ko/ja/zh phrases and two adjacent owners. Six more
            # keep a film named inside another skill's request with that
            # skill (15). Five more production requests (zh courtesy, the
            # shortest request, make/cut/produce) and two chained requests
            # that keep their owner (7).
            # Hermes' slash-skill scaffold read as the invocation typed adds
            # three, each routed to ultrawork on main from the skill body
            # Hermes pasted in: /dag-ulw with a request and bare, and /ulw-plan
            # with a request (3).
            # A request after the /dag-ulw sigil that holds a question word or
            # is asked politely still dispatches: find why it broke and fix
            # it, see what is wrong and tidy the PRs, the owner's many-PR
            # turn, and a polite Korean request (4).
            # A real request after an explicit invocation still dispatches:
            # /ulw-plan with a request, /omh-code-review this PR, /ulw-loop
            # with a goal, and /ulw-work with a stop word that names the
            # work (4), and /omh-app-debugging asked to find out why a test
            # fails or why the run stopped, a diagnosis question (2).
            # The rule after an explicit sigil adds thirteen. A stop verb with
            # a task object (/ulw-work kill the zombie processes, /omh-git-
            # workflow abort the rebase, /omh-frontend stop the modal from
            # flickering, /ulw-loop 로그 폭주 멈춰줘) or a question with one
            # (/ulw-plan how should we migrate billing?, /omh-code-review is
            # it safe to merge?) runs its skill, as on main (6). A status
            # request gets OMH's status card where main ran the skill:
            # /ulw-work status, /ulw-loop 상태 보여줘, /omh-app-debugging is it
            # running? and 끝났어? (4), and /ulw-work show status in Hermes'
            # scaffold, as on main (1). A status request runs a skill whose
            # work it is: /omh-running-work-board status and
            # /omh-verification-gate is it done?, as on main (2).
            # A stop of something other than the skill's own run still runs
            # it: /ulw-loop stop the loop when tests pass and
            # /omh-data-pipelines stop the pipelines, as on main (2); so does
            # a stop after the cancel skill, its work: /omh-cancel stop, as on
            # main (1). A this/it question after a skill that explains or
            # judges what the person points at is its work: /omh-code-review
            # how is it?, and /omh-codebase-onboarding what does this do?, as
            # on main (2), and /omh-code-review 这是什么 and
            # /omh-paper-learning what is it?, which got OMH's intro card on
            # main (2).
            # A skill with no determiner or with "a", or a name after an
            # article, names a thing, so the skill runs, as on main: /omh-docs
            # what is a skill?, /omh-skill-scout what can a skill do?,
            # /omh-frontend what does the frontend do?, /ulw-research what is
            # the research about?, /ulw-context what is the context? (5). So
            # do a Korean stop verb before its object, /ulw-work 취소해 주문,
            # and an own-run word inside a domain noun, /ulw-loop 무한 루프
            # 멈춰, as on main (2). A single common word that is a skill's
            # name is its material, not the skill: /omh-rust what is rust?,
            # which got OMH's intro card on main (1). A Korean stop verb
            # before a task noun is work, /ulw-work 멈춰 서버, as on main (1),
            # and /ulw-context status gets the status card where main ran the
            # skill: aligning project terms has no status of its own (1).
            # /omh-cancel 상태 보여줘 gets the status card where main ran
            # cancel: only a skill whose job is reporting a state runs on a
            # status request (1).
            # Multi-part work to dag-ulw adds eleven. Four run as a graph on a
            # change from the allow list: the owner's sweep over upstream PRs
            # (web-research on main), 열린 PR들 전부 리베이스해줘
            # (github-event-ops on main), fix all the failing tests, and two
            # features in parallel (4). review all open PRs is offered dag-ulw
            # in a clarify, not started (1), and check all open pull requests
            # and close the stale ones stays on ultrawork, as on main (1). Three
            # single tasks stay on ultrawork, as on main: every typo in one
            # file, in Korean and English, and tests running in parallel (3).
            # /omh-agent-ops-review status runs the review, as on main (1),
            # and /ulw-work 멈춰 리뷰어 runs ultrawork, which main answered:
            # its 어 ending read the loanword as a reason (1). The review adds
            # one: fix the bug in all three services stays on ultrawork, as on
            # main (1). The structural fix adds three: update every service and
            # 모든 패키지 버전 올려줘 run as a graph on a change from the allow
            # list (a clarify on main) (2), and a hold on every PR stays on
            # github-event-ops, as on main (1). Its review adds seven. Four run
            # as a graph: a request ending said apart from its verb and a force
            # push after a change (github-event-ops on main) (2), a past in a
            # modifier that names the PRs (a fallback on main) (1), and a change
            # with a report after it (ultrawork on main) (1). Four keep the
            # skill they name, as on main: loop로, github-event-ops로, use
            # git-workflow:, and with git-workflow at the end (4). Its second
            # review adds seven. Four stay where main sends them: a morning
            # schedule on automation-blueprint, the tests on one named branch
            # and dark mode that does not apply on ultrawork, and the files of
            # the PR just opened on code-review (4). Three run as a graph: 몽땅,
            # for each of my PRs:, and upgrade해줘 (a fallback or a clarify on
            # main) (3). PR 3개 is a count of PRs and runs as a graph (a
            # fallback on main) (1). Its third review adds three: twice a day
            # stays on github-event-ops and my latest pull request on
            # ultrawork, as on main (2), and the same sweep now runs as a graph
            # (a clarify on main) (1). Its fourth review adds three: 배포마다
            # stays on toolbelt-readiness and on every push on ultrawork, as on
            # main (2), and 각 서비스마다 runs as a graph, each service and no
            # schedule (a fallback on main) (1).
            # Three unnamed domain-science interventions (+3).
            # #2221 L3: every STATUS_IS_THE_WORK member gets a status request
            # after its sigil that runs it; the seven without one before
            # (deploy-and-monitor, ops-observability-card,
            # live-incident-response, context-budget-review,
            # harness-session-inventory, skill-health, run-efficiency) (+7).
            # #2221 L4: doctor joins the set, since the status card shows no
            # install drift, and /omh-doctor status runs doctor (+1).
            # Repro-audit adds one retained-result request; combined producer measured.
            expected=1084,
            # The one reviewed test pin. Every other test compares its payload
            # against build_routing_precision_demo() rather than a literal.
            sites=("tests/test_routing_precision.py",),
        ),
        CountMetric(
            name="installable_skill_count",
            describe="Installable workflow skills quoted in reference surfaces",
            live=_installable_skill_count,
            # The current workflow additions are part of the installable catalog.
            # `data-share-review` adds one. `spend-gate` adds one. `dag-ulw` adds one.
            # `market-research` adds one.
            # show-reel adds one installable motion-production method.
            # Three optional executable science methods (+3).
            expected=151,
            sites=(
                "docs/README.md",
                # The docs index quotes the count in prose and
                # `test_first_release_trust_surfaces_are_present` asserts that
                # exact string, so the number lives in two files, not one.
                "tests/test_router_content.py",
            ),
        ),
        CountMetric(
            name="common_request_case_count",
            describe="Common request coverage cases",
            live=_common_request_case_count,
            expected=92,
            sites=(
                "tests/test_cli.py",
                "tests/test_hermes_ux_quality.py",
                "tests/test_release_smoke.py",
                "tests/test_common_request_coverage.py",
            ),
        ),
        CountMetric(
            name="ulw_canonical_engine_count",
            describe="ULW engines in the canonical lifecycle stage",
            live=_ulw_canonical_engine_count,
            # `dag-ulw` joins the canonical engines (2026-10-21).
            expected=10,
            sites=(
                "README.ko.md",
                "README.ja.md",
                "tests/test_ulw_inventory.py",
            ),
        ),
        CountMetric(
            name="ulw_alias_engine_count",
            describe="ULW engines in the alias or warning lifecycle stage",
            live=_ulw_alias_engine_count,
            expected=0,
            sites=(
                "tests/test_ulw_inventory.py",
            ),
        ),
        CountMetric(
            name="ulw_retired_engine_count",
            describe="ULW engines in the retired lifecycle stage",
            live=_ulw_retired_engine_count,
            expected=4,
            sites=(
                "tests/test_ulw_inventory.py",
            ),
        ),
    )


def _skill_density_filler_hits() -> int:
    from ..quality.skill_density import catalog_filler_hit_total

    return catalog_filler_hit_total()


def budget_metrics() -> tuple[BudgetMetric, ...]:
    from ..quality.skill_density import DENSITY_FILLER_HIT_CEILING
    from ..plugin_bundle.omh.turn_budget import (
        AWARENESS_PRIMER_CONTEXT_CHAR_LIMIT,
        AWARENESS_PRIMER_MARKDOWN_CHAR_LIMIT,
        AWARENESS_WORKFLOW_CONTEXT_CHAR_LIMIT,
        PRE_LLM_CALL_CONTEXT_CHAR_LIMIT,
        PRE_LLM_CALL_CONTEXT_FALLBACK_CHAR_LIMIT,
        ROLE_CONTEXT_CHAR_LIMIT,
    )
    from .release import (
        FULL_CAPABILITY_SKILL_ITEM_CHAR_LIMIT,
        FULL_CAPABILITY_SKILL_SECTION_CHAR_LIMIT,
        FULL_PROFILE_SKILL_BODY_CEILING_STEP_CHARS,
        FULL_PROFILE_SKILL_BODY_CHAR_LIMIT,
        FULL_PROFILE_SKILL_BODY_MEASURED_CHARS,
        FULL_PROFILE_SKILL_BODY_REPEATED_CEILING_STEP_CHARS,
        FULL_PROFILE_SKILL_BODY_REPEATED_CHAR_LIMIT,
        FULL_PROFILE_SKILL_BODY_REPEATED_MEASURED_CHARS,
        FULL_PROFILE_SKILL_BODY_REVIEWED_EXCEPTION_CHARS,
        PLUGIN_TOOL_SCHEMA_CHAR_LIMIT,
        SKILL_INDEX_CHAR_LIMIT,
        SKILL_INDEX_LINE_CHAR_LIMIT,
        STANDALONE_CAPABILITY_SKILL_ITEM_CHAR_LIMIT,
        STANDALONE_CAPABILITY_SKILL_SECTION_CHAR_LIMIT,
    )

    return (
        # The first five can reach the model on every request or turn (the tool
        # schemas only when Hermes's tool_search is off; with the default bridge
        # they are deferred behind a listing). Everything after them is paid on
        # demand (a tool call, a `skill_view` load) or is a quality signal. Read
        # this group first when a change grows context.
        BudgetMetric(
            name="skill_index_chars",
            describe="Per request: full-profile skill index lines Hermes renders (60-char descriptions)",
            live=_skill_index_chars,
            limit=SKILL_INDEX_CHAR_LIMIT,
            limit_site="src/maintenance/release.py",
            kind="ratchet",
        ),
        BudgetMetric(
            name="skill_index_line_max_chars",
            describe="Per request: longest single skill line in that index",
            live=_skill_index_line_max_chars,
            limit=SKILL_INDEX_LINE_CHAR_LIMIT,
            limit_site="src/maintenance/release.py",
            kind="ratchet",
        ),
        BudgetMetric(
            name="plugin_tool_schema_chars",
            describe="Eager ceiling, per request only if tool_search is off: plugin tool schemas as registered (JSON chars)",
            live=_plugin_tool_schema_chars,
            limit=PLUGIN_TOOL_SCHEMA_CHAR_LIMIT,
            limit_site="src/maintenance/release.py",
            kind="ratchet",
        ),
        BudgetMetric(
            name="pre_llm_call_context_chars_max",
            describe="Per turn, replayed in history: largest fenced pre_llm_call context over the named scenarios",
            live=_pre_llm_call_context_chars_max,
            limit=PRE_LLM_CALL_CONTEXT_CHAR_LIMIT,
            limit_site="src/plugin_bundle/omh/turn_budget.py",
            kind="ratchet",
        ),
        BudgetMetric(
            name="pre_llm_call_context_fallback_chars_max",
            describe="Per turn, replayed in history: that context for a session without the awareness section (primer included)",
            live=_pre_llm_call_context_fallback_chars_max,
            limit=PRE_LLM_CALL_CONTEXT_FALLBACK_CHAR_LIMIT,
            limit_site="src/plugin_bundle/omh/turn_budget.py",
            kind="ratchet",
        ),
        BudgetMetric(
            name="awareness_primer_markdown_chars",
            describe="Awareness primer markdown size",
            live=_awareness_primer_markdown_chars,
            limit=AWARENESS_PRIMER_MARKDOWN_CHAR_LIMIT,
            limit_site="src/plugin_bundle/omh/turn_budget.py",
            kind="ceiling",
        ),
        # The three below and the two capability item sizes were compared only
        # inside `skill_content_smoke`, which now reads their verdict here, so
        # `omh release drift` reports them too. Each is a hand-set ceiling with
        # standing headroom and no recorded measurement.
        BudgetMetric(
            name="awareness_primer_context_chars",
            describe="Awareness primer compact context size",
            live=_awareness_primer_context_chars,
            limit=AWARENESS_PRIMER_CONTEXT_CHAR_LIMIT,
            limit_site="src/plugin_bundle/omh/turn_budget.py",
            kind="ceiling",
        ),
        BudgetMetric(
            name="awareness_workflow_context_chars_max",
            describe="Largest per-skill awareness workflow context",
            live=_awareness_workflow_context_chars_max,
            limit=AWARENESS_WORKFLOW_CONTEXT_CHAR_LIMIT,
            limit_site="src/plugin_bundle/omh/turn_budget.py",
            kind="ceiling",
        ),
        BudgetMetric(
            name="role_context_chars_max",
            describe="Largest role context file",
            live=_role_context_chars_max,
            limit=ROLE_CONTEXT_CHAR_LIMIT,
            limit_site="src/plugin_bundle/omh/turn_budget.py",
            kind="ceiling",
        ),
        BudgetMetric(
            name="full_capability_skill_section_chars",
            describe="Full capability skill section size",
            live=_full_capability_section_chars,
            limit=FULL_CAPABILITY_SKILL_SECTION_CHAR_LIMIT,
            limit_site="src/maintenance/release.py",
            kind="ratchet",
        ),
        BudgetMetric(
            name="full_capability_skill_item_chars_max",
            describe="Largest single full capability skill item",
            live=_full_capability_item_chars_max,
            limit=FULL_CAPABILITY_SKILL_ITEM_CHAR_LIMIT,
            limit_site="src/maintenance/release.py",
            kind="ceiling",
        ),
        BudgetMetric(
            name="standalone_capability_skill_section_chars",
            describe="Standalone capability skill section size",
            live=_standalone_capability_section_chars,
            limit=STANDALONE_CAPABILITY_SKILL_SECTION_CHAR_LIMIT,
            limit_site="src/maintenance/release.py",
            kind="ratchet",
        ),
        BudgetMetric(
            name="standalone_capability_skill_item_chars_max",
            describe="Largest single standalone capability skill item",
            live=_standalone_capability_item_chars_max,
            limit=STANDALONE_CAPABILITY_SKILL_ITEM_CHAR_LIMIT,
            limit_site="src/maintenance/release.py",
            kind="ceiling",
        ),
        BudgetMetric(
            name="full_profile_skill_body_chars",
            describe="Install footprint: full-profile SKILL.md bodies, each loaded on demand (producer chars)",
            live=_full_profile_skill_body_chars,
            limit=FULL_PROFILE_SKILL_BODY_CHAR_LIMIT,
            limit_site="src/maintenance/release.py",
            reviewed_exception=FULL_PROFILE_SKILL_BODY_REVIEWED_EXCEPTION_CHARS,
            kind="ceiling",
            measured=FULL_PROFILE_SKILL_BODY_MEASURED_CHARS,
            step=FULL_PROFILE_SKILL_BODY_CEILING_STEP_CHARS,
        ),
        # Text repeated verbatim across bodies is paid on every load of each of
        # them and belongs once in a reference. A ceiling with headroom like the
        # footprint above, sized so the rail copies an ordinary new lane member
        # carries fit (policy in src/maintenance/release.py).
        BudgetMetric(
            name="full_profile_skill_body_repeated_chars",
            describe="Repeated across bodies: full-profile SKILL.md sections byte-identical to another skill's (producer chars)",
            live=_full_profile_skill_body_repeated_chars,
            limit=FULL_PROFILE_SKILL_BODY_REPEATED_CHAR_LIMIT,
            limit_site="src/maintenance/release.py",
            kind="ceiling",
            measured=FULL_PROFILE_SKILL_BODY_REPEATED_MEASURED_CHARS,
            step=FULL_PROFILE_SKILL_BODY_REPEATED_CEILING_STEP_CHARS,
        ),
        # The byte budget above says how much the pack costs; this says whether
        # the characters carry instruction. A hit is a reviewed filler phrase
        # that every load of a body pays for without changing what a reader
        # does, so the ceiling is zero on a corpus measured at zero. The other
        # two density signals are floats and stay in `tests/test_skill_density.py`.
        BudgetMetric(
            name="skill_density_filler_hits",
            describe="Reviewed filler phrases across all catalog skill bodies",
            live=_skill_density_filler_hits,
            limit=DENSITY_FILLER_HIT_CEILING,
            limit_site="src/quality/skill_density.py",
            kind="ratchet",
        ),
    )


def limits() -> dict[str, Limit]:
    """Every budget's limit and kind, by metric name. Reads no producer."""
    return {
        metric.name: Limit(
            kind=metric.kind,
            value=metric.limit,
            measured=metric.limit if metric.kind == "ratchet" else metric.measured,
            step=metric.step,
        )
        for metric in budget_metrics()
    }


def measure() -> dict[str, int]:
    """Every count and budget as its producer reads it today, by metric name."""
    return {metric.name: metric.live() for metric in (*count_metrics(), *budget_metrics())}


def generated_artifacts() -> tuple[GeneratedArtifact, ...]:
    from ..capabilities.families import standalone_capability_families_json
    from ..catalogs.roles import roles_reference_markdown
    from ..routing.skill_shortlist_sidecar import standalone_skill_shortlist_json
    from ..skills.render import workflow_reference_markdown

    return (
        GeneratedArtifact(
            name="workflows_doc",
            path="docs/WORKFLOWS.md",
            render=workflow_reference_markdown,
            regenerate="uv run python -m omh.cli docs workflows --output docs/WORKFLOWS.md",
        ),
        GeneratedArtifact(
            name="roles_doc",
            path="docs/ROLES.md",
            render=roles_reference_markdown,
            regenerate="uv run python -m omh.cli docs roles --output docs/ROLES.md",
        ),
        GeneratedArtifact(
            name="capability_families_sidecar",
            path="src/plugin_bundle/omh/tools/capability_families.json",
            render=standalone_capability_families_json,
            regenerate="uv run python -m omh.cli docs capability-families",
        ),
        GeneratedArtifact(
            name="skill_shortlist_sidecar",
            path="src/plugin_bundle/omh/tools/skill_shortlist.json",
            render=standalone_skill_shortlist_json,
            regenerate="uv run python -m omh.cli docs skill-shortlist",
        ),
    )


def _count_drift(metric: CountMetric) -> CountDriftFinding | None:
    live = metric.live()
    if live == metric.expected:
        return None
    return {
        "name": metric.name,
        "kind": "count",
        "describe": metric.describe,
        "expected": metric.expected,
        "live": live,
        "sites": list(metric.sites),
        "fix": (
            f"replace {metric.expected} with {live} in src/maintenance/drift.py "
            f"and in every site listed above"
        ),
    }


def _budget_drift(metric: BudgetMetric) -> BudgetDriftFinding | None:
    live = metric.live()
    ceiling = metric.limit + metric.reviewed_exception
    if live <= ceiling:
        return None
    finding: BudgetDriftFinding = {
        "name": metric.name,
        "kind": "budget",
        "describe": metric.describe,
        "limit": metric.limit,
        "live": live,
        "over_by": live - ceiling,
        "sites": [metric.limit_site],
        "fix": (
            f"shorten the rendered content by {live - ceiling} chars, or raise the limit "
            f"in {metric.limit_site} if the growth is genuinely warranted"
        ),
    }
    if metric.reviewed_exception:
        finding["reviewed_exception"] = metric.reviewed_exception
        finding["exception_reason"] = metric.exception_reason
    return finding


def _tap_skills_drift(repo_root: Path) -> TapSkillsDriftFinding | None:
    """Generated `skills/*/SKILL.md` and `skills/*/references/*.md`.

    These do not fit the one-file-per-artifact shape above -- there are dozens,
    and a catalog change can make some stale while adding or removing others.
    Reusing the same check `docs workflows --check` runs keeps one definition of
    stale.
    """
    from ..commands.docs import tap_skills_check_payload

    payload = tap_skills_check_payload(repo_root / "skills")
    if payload["ok"]:
        return None
    affected = list(payload["missing"]) + list(payload["stale"]) + list(payload["extra"])
    return {
        "name": "tap_skills",
        "kind": "generated",
        "describe": f"{len(affected)} generated skill file(s) out of sync",
        "state": "stale",
        "missing": payload["missing"],
        "stale": payload["stale"],
        "extra": payload["extra"],
        "sites": [f"skills/{item}" for item in affected],
        "fix": (
            "write each template's .content back under skills/ "
            "(builtin_skill_templates() and builtin_skill_reference_templates())"
        ),
    }


def _generated_drift(artifact: GeneratedArtifact, repo_root: Path) -> GeneratedDriftFinding | None:
    target = repo_root / artifact.path
    expected = artifact.render()
    try:
        current = target.read_text(encoding="utf-8")
    except FileNotFoundError:
        state = "missing"
    except OSError as exc:
        return {
            "name": artifact.name,
            "kind": "generated",
            "describe": f"{artifact.path} could not be read",
            "state": "unreadable",
            "error": str(exc),
            "sites": [artifact.path],
            "fix": artifact.regenerate,
        }
    else:
        if current == expected:
            return None
        state = "stale"
    return {
        "name": artifact.name,
        "kind": "generated",
        "describe": f"{artifact.path} is {state}",
        "state": state,
        "sites": [artifact.path],
        "fix": artifact.regenerate,
    }


def repo_root_default() -> Path:
    return Path(__file__).resolve().parents[2]


def drift_report(
    *,
    repo_root: Path | None = None,
    counts: tuple[CountMetric, ...] | None = None,
    budgets: tuple[BudgetMetric, ...] | None = None,
    artifacts: tuple[GeneratedArtifact, ...] | None = None,
    include_tap_skills: bool = True,
) -> DriftReport:
    """Check every metric and report all findings; never stop at the first.

    Stopping early is the behaviour this command exists to replace.
    """
    root = repo_root or repo_root_default()
    counts = count_metrics() if counts is None else counts
    budgets = budget_metrics() if budgets is None else budgets
    artifacts = generated_artifacts() if artifacts is None else artifacts

    drift: list[DriftFinding] = []
    checked: list[str] = []
    for metric in counts:
        checked.append(metric.name)
        found: DriftFinding | None = _count_drift(metric)
        if found:
            drift.append(found)
    for metric in budgets:
        checked.append(metric.name)
        found = _budget_drift(metric)
        if found:
            drift.append(found)
    for artifact in artifacts:
        checked.append(artifact.name)
        found = _generated_drift(artifact, root)
        if found:
            drift.append(found)
    if include_tap_skills:
        checked.append("tap_skills")
        found = _tap_skills_drift(root)
        if found:
            drift.append(found)

    return {
        "schema_version": DRIFT_REPORT_SCHEMA_VERSION,
        "ok": not drift,
        "checked_count": len(checked),
        "drift_count": len(drift),
        "checked": checked,
        "drift": drift,
        "next_action": (
            "apply every listed fix in one pass, then rerun this command"
            if drift
            else "no drift; run the full suite as the final proof"
        ),
        "claim_boundary": (
            "Drift detection is a preflight over recomputed catalog values. It is not test, "
            "review, CI, or merge evidence."
        ),
    }


verdict = drift_report


def format_drift_report(payload: DriftReport) -> str:
    drift = payload.get("drift") or []
    lines: list[str] = []
    if not drift:
        lines.append(f"No drift. {payload.get('checked_count', 0)} checks passed.")
        return "\n".join(lines)
    lines.append(f"DRIFT ({len(drift)} of {payload.get('checked_count', 0)} checks)")
    lines.append("")
    for item in drift:
        if item["kind"] == "count":
            headline = f"  {item['name']}: {item['expected']} -> {item['live']}"
        elif item["kind"] == "budget":
            headline = f"  {item['name']}: {item['live']} (over budget {item['limit']} by {item['over_by']})"
        else:
            headline = f"  {item['name']}: {item.get('state', 'stale')}"
        lines.append(headline)
        for site in item.get("sites", []):
            lines.append(f"      site: {site}")
        lines.append(f"      fix:  {item.get('fix', '')}")
        lines.append("")
    lines.append(str(payload.get("next_action", "")))
    return "\n".join(lines)
