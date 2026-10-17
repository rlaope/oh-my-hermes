from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Mapping, Sequence, TypedDict

from ..ingress import CHAT_SOURCES
from ..routing.action_copy import next_action_label
from ..routing.chat import route_question_decline_reason
from ..wrapper.contract import build_chat_interaction_payload


ROUTING_PRECISION_SCHEMA_VERSION = "routing_precision/v1"


@dataclass(frozen=True)
class RoutingPrecisionCase:
    id: str
    title: str
    message: str
    expected_next_action: str
    expected_lookup_kind: str
    forbidden_candidate: str = ""
    # What the route question decline predicate says about this case: a
    # reason from `ROUTE_QUESTION_DECLINE_REASONS`, `ROUTE_QUESTION_ASKED`
    # when the route builds a question with something to decide, or "" to
    # leave it unchecked. Set on the cases that pin the predicate in both
    # directions; see `route_question_decline_reason`.
    expected_route_question: str = ""


# The `expected_route_question` value for a built question the predicate keeps.
ROUTE_QUESTION_ASKED = "asked"


@dataclass(frozen=True)
class RoutingInterventionCase:
    id: str
    title: str
    message: str
    expected_route_action: str
    expected_workflow: str
    expected_next_action: str
    expected_response_kind: str
    expected_candidate: str = ""
    # The confidence tier the route reached. Left unset on most cases, because
    # `expected_route_action` already implies a band: `dispatch` needs `high`.
    # Set it where the tier itself is the claim -- a case pinned at `clarify`
    # passes at any confidence below the dispatch threshold, so a phrase that
    # slid from `medium` to `low` would otherwise still pass.
    expected_confidence: str = ""
    active_design_direction_iteration: dict[str, str] | None = None
    # See `RoutingPrecisionCase.expected_route_question`.
    expected_route_question: str = ""


# Negative-control corpus. These are ordinary chat turns where OMH should stay
# helpful but should not hijack the answer into workflow selection, catalog
# pickers, coding handoffs, or generic workflow acknowledgements.
ROUTING_PRECISION_CASES: tuple[RoutingPrecisionCase, ...] = (
    # Engine-entry approvals (#1638). Accepting something is the most common
    # thing a person says in the seconds after a planning workflow finishes,
    # and the corpus had no sentence of this shape at all -- 235 negative
    # controls reporting `overroute_count: 0` over a case it never contained.
    # Each of these carries a skill name inside an approval; none of them asks
    # for that skill. The set spans the score range the survey found (`loop`
    # 45, `plan` 17, `maestro` 9), both article forms, and Korean, because the
    # leading-position form reached explicit invocation and the two halves
    # failed differently.
    #
    # No `forbidden_candidate`: that field reads `route.candidate_skill`,
    # which records what scoring found and stays set through a clarify --
    # the same reason the chain-models-concept cases below leave it unset.
    # The claim here is that the ACTION is not a dispatch, which the case
    # already fails on.
    RoutingPrecisionCase(
        'engine-entry-approval-plan-article', 'An accepted plan is not a request to plan',
        'the plan is fine, just ship it', 'answer_clarification', '',
    ),
    RoutingPrecisionCase(
        'engine-entry-approval-plan-bare', 'A leading skill name in an approval is still an approval',
        'plan looks good, go ahead', 'answer_clarification', '',
    ),
    RoutingPrecisionCase(
        'engine-entry-approval-plan-compound', 'An approval carrying a fresh request does not re-plan',
        'the plan is fine, now write the migration', 'answer_clarification', '',
    ),
    RoutingPrecisionCase(
        'engine-entry-approval-loop', 'A guard-boosted name in an approval is still an approval',
        'the loop is fine, ship it', 'answer_clarification', '',
    ),
    RoutingPrecisionCase(
        'engine-entry-approval-maestro', 'The lowest-scoring name in an approval is still an approval',
        'the maestro is fine, just ship it', 'answer_clarification', '',
    ),
    RoutingPrecisionCase(
        'engine-entry-approval-ultrawork', 'A coined name in an approval is still an approval',
        'the ultrawork is fine, ship it', 'answer_clarification', '',
    ),
    RoutingPrecisionCase(
        'engine-entry-approval-korean', 'A Korean approval naming a skill is still an approval',
        'plan 승인, 배포하자', 'answer_clarification', '',
    ),
    RoutingPrecisionCase(
        'engine-entry-approval-korean-mid', 'A Korean approval mid-sentence is still an approval',
        '이 plan 괜찮습니다, 그대로 진행', 'answer_clarification', '',
    ),
    # `todo-checklist` is assembled entirely from everyday words. These pin the
    # sentences that must NOT reach it; the guard that makes them pass is the
    # `_WHOLE_PHRASE_ONLY_TRIGGER_TOKENS` entry plus a two-word name, since a
    # one-word name would credit `name:` on every one of them.
    RoutingPrecisionCase(
        'todo-checklist-source-comment-control',
        'A TODO source comment is not a plan checklist',
        'add a TODO comment in the code', 'answer_clarification', '', 'todo-checklist',
    ),
    RoutingPrecisionCase(
        'todo-checklist-inline-marker-control',
        'A todo marker left for a later reader is not a plan checklist',
        'todo: fix this later', 'answer_clarification', '', 'todo-checklist',
    ),
    RoutingPrecisionCase(
        'todo-checklist-file-listing-control',
        'A checklist of changed files is ordinary output, not the HUD panel',
        'make a checklist of the files you changed', 'answer_clarification', '', 'todo-checklist',
    ),
    RoutingPrecisionCase(
        'todo-checklist-show-verb-control',
        'The bare verb `show` does not reach the checklist',
        'show me the diff', 'answer_clarification', '', 'todo-checklist',
    ),
    RoutingPrecisionCase(
        'todo-checklist-clear-verb-control',
        'The bare verb `clear` does not reach the checklist',
        'clear the cache', 'answer_clarification', '', 'todo-checklist',
    ),
    RoutingPrecisionCase(
        'todo-checklist-phase-word-control',
        'Asking which phase the work is in is not a checklist declaration',
        'which phase are we in', 'answer_clarification', '', 'todo-checklist',
    ),
    # `finance-analysis` carries the accounting phrase "month-end close", whose
    # separate tokens handed it the bare word `close` and made it the top
    # candidate on every sentence that merely contains it. The accounting
    # intent reaches the workflow through its `domain:` cue instead, which
    # neither of these touches.
    RoutingPrecisionCase(
        'finance-close-ui-verb-control',
        'A modal that closes is not a month-end close',
        'the modal should close when the user presses escape', 'answer_clarification', '',
        'finance-analysis',
    ),
    RoutingPrecisionCase(
        'finance-close-resource-verb-control',
        'Closing a database transaction is not a month-end close',
        'remember to close the transaction in the finally block', 'answer_clarification', '',
        'finance-analysis',
    ),
    RoutingPrecisionCase(
        'recall-apology-control', 'An apology is not a recall incident',
        'Apologize for forgetting.', 'answer_clarification', '', 'memory-sync',
    ),
    RoutingPrecisionCase(
        'recall-quoted-control', 'Quoted recall complaints remain translation input',
        'Translate "memory was not used" into French.', 'answer_directly', 'direct_answer', 'memory-sync',
    ),
    RoutingPrecisionCase(
        'reference-inline-workflow-translation',
        'Inline workflow syntax is translation input',
        'Translate `$ulw-work` to Korean.',
        'answer_clarification',
        '',
        'ultrawork',
    ),
    RoutingPrecisionCase(
        'reference-double-quoted-workflow',
        'Double-quoted workflow syntax is explanation input',
        'Explain "$ulw-work" without running it.',
        'answer_clarification',
        '',
        'ultrawork',
    ),
    RoutingPrecisionCase(
        'reference-single-quoted-workflow',
        'Single-quoted workflow syntax is explanation input',
        "Explain '$ulw-work' without running it.",
        'answer_clarification',
        '',
        'ultrawork',
    ),
    RoutingPrecisionCase(
        'reference-tagged-backtick-fence',
        'A language-tagged backtick example is inert',
        'Show this example:\n```bash\n$ulw-work fix the build\n```',
        'answer_clarification',
        '',
        'ultrawork',
    ),
    RoutingPrecisionCase(
        'reference-tagged-tilde-fence',
        'A language-tagged tilde example is inert',
        'Show this example:\n~~~shell\n$ulw-work fix the build\n~~~',
        'answer_clarification',
        '',
        'ultrawork',
    ),
    RoutingPrecisionCase(
        'reference-escaped-quote',
        'An escaped quote does not end a reference',
        'Explain "literal \\" $ulw-work execute".',
        'answer_directly',
        'direct_answer',
        'ultrawork',
    ),
    RoutingPrecisionCase(
        'reference-unfinished-fence',
        'An unfinished reference fence is shielded to EOF',
        'Show this:\n```bash\n$ulw-work execute',
        'answer_clarification',
        '',
        'ultrawork',
    ),
    RoutingPrecisionCase(
        'reference-after-a-plural-possessive',
        'A plural possessive does not pair with the quote after it and expose its workflow syntax',
        "Explain the users' '$ulw-work' snippet.",
        'answer_directly',
        'direct_answer',
        'ultrawork',
    ),
    RoutingPrecisionCase(
        'reference-cjk-surroundings',
        'CJK clauses do not expose quoted workflow triggers',
        '请解释"$ulw-work"的意思。',
        'answer_clarification',
        '',
        'ultrawork',
    ),
    RoutingPrecisionCase(
        'reference-quoted-learning-workflow',
        'Quoted learning workflow names cannot route themselves',
        '"workflow-learning"',
        'answer_directly',
        'direct_answer',
        'workflow-learning',
    ),
    RoutingPrecisionCase(
        "unbound-design-feedback-stays-clarification",
        "Direction feedback without a trusted active iteration remains clarification",
        "Can we take another pass on those layouts after my notes?",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "apple-fruit-stays-out-of-apple-design",
        "Apple fruit discussion does not select the Apple UI specialist",
        "Apple fruit nutrition is unrelated to interface design.",
        "answer_clarification",
        "",
        "apple-design",
    ),
    RoutingPrecisionCase(
        "apple-stock-stays-out-of-apple-design",
        "Apple stock discussion does not select the Apple UI specialist",
        "Apple stock is unrelated to interface design.",
        "answer_clarification",
        "",
        "apple-design",
    ),
    RoutingPrecisionCase(
        "apple-support-stays-out-of-apple-design",
        "Apple support discussion does not select the Apple UI specialist",
        "Apple Support account help is unrelated to interface design.",
        "answer_clarification",
        "",
        "apple-design",
    ),
    RoutingPrecisionCase(
        "glass-material-science-stays-out-of-apple-design",
        "Material science glass discussion does not select the Apple UI specialist",
        "Glass material science transition temperatures are unrelated to interface design.",
        "answer_clarification",
        "",
        "apple-design",
    ),
    RoutingPrecisionCase(
        "negated-omh-docs-authoring-stays-with-the-router",
        "A negated omh-docs mention does not steal generic docs authoring",
        "Don't use omh-docs; write API documentation for my library",
        "answer_clarification",
        "",
        "product-docs",
    ),
    RoutingPrecisionCase(
        "descriptive-omh-docs-mention-stays-direct",
        "A descriptive omh-docs mention is not an invocation",
        "I am discussing the omh-docs skill, not asking you to invoke it.",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "generic-docs-authoring-stays-with-the-router",
        "A generic docs authoring request stays out of OMH self-documentation",
        "use docs to write my API documentation",
        "answer_clarification",
        "",
        "product-docs",
    ),
    RoutingPrecisionCase(
        "generic-documentation-concept-stays-direct",
        "A generic documentation concept stays out of OMH self-documentation",
        "what is a documentation site?",
        "answer_directly",
        "direct_answer",
    ),
    # A trigger inside a sentence that reports rather than asks. Every one of
    # these dispatched before the narration guard: the trigger match is a
    # substring match, and nothing weighed whether the sentence wanted work.
    # They are negative controls rather than interventions because the correct
    # answer is a direct reply, not a different workflow.
    RoutingPrecisionCase(
        "reported-research-decision-stays-direct",
        "A decision the research team already made stays direct",
        "the research team already signed off on this",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "reported-research-budget-stays-direct",
        "A spent research budget stays direct",
        "our research budget is basically gone for the quarter",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "reported-web-search-cost-stays-direct",
        "A web search bill that went up stays direct",
        "our web search bill went up a lot last month",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "declined-lookup-stays-direct",
        "A lookup the user declines to delegate stays direct",
        "i will look up the answer myself, thanks",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "reported-shipped-feature-stays-direct",
        "A changelog line about a shipped web search feature stays direct",
        "the changelog says web search shipped last year",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "reported-team-move-stays-direct",
        "A person moving off the research team stays direct",
        "she moved from research to platform last month",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "reported-prior-art-outcome-stays-direct",
        "A settled prior-art outcome stays direct",
        "prior art was not an issue for that patent",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "reported-citation-check-failure-stays-direct",
        "A citation check that already failed stays direct",
        "the citation check on that PR failed",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "reported-source-diversity-cause-stays-direct",
        "Source diversity named as a cause stays direct",
        "source diversity is why the review took so long",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "explicit-no-action-stays-direct",
        "Fresh sources already in hand with no action wanted stays direct",
        "we already have fresh sources for this, no action needed",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "lookup-lane-file-question-stays-direct",
        "A repo-file question naming the lookup lane stays a file lookup",
        "show me the SKILL.md for the lookup lane",
        "answer_file_lookup",
        "file_or_text",
    ),
    RoutingPrecisionCase(
        "catalog-definition-file-question-stays-direct",
        "A question about where skill definitions live stays a file lookup",
        "which file holds the skill catalog definitions?",
        "answer_file_lookup",
        "file_or_text",
    ),
    # Five sentences a skill Hermes bundles owns, pinned as non-dispatch.
    # `web-research` and `research-department` now name `grounded-citations`,
    # `competitor-news-monitor`, and `arxiv` in their do-not-use boundaries.
    # These cases pin these five sentences and nothing wider. The router
    # still dispatches `web-research` for a ledger check phrased with its own
    # `citation check` trigger or with the Korean `출처` trigger, and for an
    # arXiv lookup phrased with `look up`; those dispatches predate the
    # boundary lines and are left to the trigger-collision work.
    #
    # No `forbidden_candidate` on the three clarify cases: that field reads the
    # clarify's candidate and its shortlist, which record what scoring found
    # and stay set through a clarify (`web-research` leads the ledger and
    # arXiv sentences, and `research-department` is on the watch run's
    # shortlist). The claim is that the action is not a dispatch, which each
    # case already fails on.
    RoutingPrecisionCase(
        "citation-ledger-bookkeeping-stays-out-of-web-research",
        "Rebuilding the Sources block of a draft from the ledger is not a web lookup",
        "rebuild the Sources block in draft.md from the citation ledger",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "korean-citation-id-check-stays-out-of-web-research",
        "A Korean request to check a draft's citation ids against the ledger is not a web lookup",
        "초안의 인용 번호가 원장과 맞는지 검증해줘",
        "answer_clarification",
        "",
        forbidden_candidate="web-research",
    ),
    RoutingPrecisionCase(
        "arxiv-search-stays-out-of-web-research",
        "An arXiv category search is not a cited web lookup",
        "search arxiv for cs.AI papers from this week",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "competitor-watch-run-stays-out-of-research-department",
        "One scheduled run of an existing competitor watch is not a research department plan",
        "run the scheduled tick for the acme competitor watch",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "named-company-news-alert-stays-direct",
        "A news alert on one named company is not a research department plan",
        "tell me when Acme raises its prices or ships something new",
        "answer_directly",
        "direct_answer",
        forbidden_candidate="research-department",
    ),
    RoutingPrecisionCase(
        "repo-file-list",
        "Repo file lookup stays direct",
        "what files are in this repo?",
        "answer_file_lookup",
        "file_or_text",
    ),
    RoutingPrecisionCase(
        "owner-default-concept",
        "Owner-default concept questions stay direct",
        "what does learned coding owner default mean?",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "markov-chain-model-concept",
        "A Markov chain model concept question stays direct, not chain setup",
        "마르코프 체인 모델이 뭔지 설명해줘",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "chain-models-ml-concept",
        "An ML chain-models concept question stays direct, not chain setup",
        "explain markov chain models to me",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "markov-chain-models-work-concept",
        "An ML concept question about how chain models work stays direct",
        "explain how markov chain models work",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "provider-pattern-concept",
        "A provider-pattern concept question stays direct, not model setup",
        "프로바이더 패턴이 뭔지 설명해줘",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "quota-report-question",
        "A quota usage question stays direct, not model setup",
        "what does quota mean in this API report?",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "readme-summary",
        "README lookup stays direct",
        "open README and summarize it",
        "answer_file_lookup",
        "file_or_text",
    ),
    RoutingPrecisionCase(
        "readme-contents",
        "README contents question stays file lookup",
        "what is in README?",
        "answer_file_lookup",
        "file_or_text",
    ),
    RoutingPrecisionCase(
        "bounded-slow-query-stays-direct",
        "One identified slow-query fix stays direct instead of opening a performance loop",
        "fix one slow query in the report page",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "general-python-help",
        "Plain Python concept stays direct",
        "what Python list comprehension means?",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "shell-path-help",
        "Shell setup question stays direct",
        "how do I set PATH in zsh?",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "stack-trace-help",
        "Missing stack trace asks for direct context",
        "please explain this stack trace",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "python-virtualenv-help",
        "Python virtualenv how-to stays direct",
        "how do I create a virtualenv in Python?",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "soft-prefix-python-help",
        "Soft-prefix Python explanation stays direct",
        "just explain Python virtualenv",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "paragraph-summary",
        "Small text transform stays direct",
        "summarize this paragraph in Korean",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "document-the-api-stays-clarify",
        "Writing documentation is not reading a document",
        "document the API",
        "answer_clarification",
        "",
        "long-document-reading",
    ),
    RoutingPrecisionCase(
        "read-the-readme-stays-file-lookup",
        "Reading a repo file stays a file lookup",
        "read the README",
        "answer_file_lookup",
        "file_or_text",
        "long-document-reading",
    ),
    RoutingPrecisionCase(
        "process-refund-stays-clarify",
        "Processing a refund is not processing a document",
        "process this refund",
        "answer_clarification",
        "",
        "long-document-reading",
    ),
    RoutingPrecisionCase(
        "read-the-room-stays-clarify",
        "Reading the room is not reading a document",
        "read the room before the meeting",
        "answer_clarification",
        "",
        "long-document-reading",
    ),
    RoutingPrecisionCase(
        "write-long-document-stays-clarify",
        "Writing a long document is not reading one",
        "write a long document explaining the migration",
        "answer_clarification",
        "",
        "long-document-reading",
    ),
    RoutingPrecisionCase(
        "korean-write-long-document-stays-clarify",
        "Korean writing request with a long document stays clarify",
        "긴 문서로 마이그레이션 설명 작성해줘",
        "answer_clarification",
        "",
        "long-document-reading",
    ),
    # `application-threat-model` is assembled from "threat", "model",
    # "stride", "trust", "boundary", "attack", "case" and "security", every
    # one of which means something else somewhere. These six pin the other
    # senses: a concept question about the method, the two words used as
    # ordinary English, statistical modeling, and a trust boundary that is a
    # DDD term rather than a security one.
    RoutingPrecisionCase(
        "threat-modeling-concept-question",
        "Asking what threat modeling is stays a direct answer",
        "what is threat modeling?",
        "answer_directly",
        "direct_answer",
        "application-threat-model",
    ),
    RoutingPrecisionCase(
        "stride-analysis-concept-question",
        "Asking what a STRIDE analysis is stays a direct answer",
        "explain what a stride analysis is",
        "answer_directly",
        "direct_answer",
        "application-threat-model",
    ),
    RoutingPrecisionCase(
        "trust-boundary-ddd-concept-question",
        "A trust boundary asked as a domain-modeling term stays a direct answer",
        "what is a trust boundary in domain-driven design?",
        "answer_directly",
        "direct_answer",
        "application-threat-model",
    ),
    RoutingPrecisionCase(
        "stride-idiom-stays-clarify",
        "Hitting one's stride is not a STRIDE analysis",
        "he hit his stride in the second half",
        "answer_clarification",
        "",
        "application-threat-model",
    ),
    RoutingPrecisionCase(
        "statistical-modeling-stays-clarify",
        "Modeling churn is statistics, not threat modeling",
        "model the churn with a logistic regression",
        "answer_clarification",
        "",
        "application-threat-model",
    ),
    RoutingPrecisionCase(
        "scale-model-stays-clarify",
        "A scale model of a bridge is not a threat model",
        "she built a scale model of the bridge",
        "answer_clarification",
        "",
        "application-threat-model",
    ),
    # `live-incident-response` is assembled from "incident", "response",
    # "commander", "severity", "outage", "production", "down", "timeline",
    # "war", "room" -- words that mean something else in ordinary English and
    # in half this catalog. These seven pin the other senses: three concept
    # questions about the discipline, a military rank, a tracker field, a
    # manufacturing line, and a figurative outage.
    RoutingPrecisionCase(
        "incident-commander-role-concept-question",
        "Asking what an incident commander does in another field stays a direct answer",
        "what does an incident commander do during a wildfire?",
        "answer_directly",
        "direct_answer",
        "live-incident-response",
    ),
    RoutingPrecisionCase(
        "incident-response-plan-concept-question",
        "Asking what an incident response plan is stays a direct answer",
        "explain what an incident response plan is",
        "answer_directly",
        "direct_answer",
        "live-incident-response",
    ),
    RoutingPrecisionCase(
        "war-room-concept-question",
        "Asking what a war room is stays a direct answer",
        "what is a war room in project management?",
        "answer_directly",
        "direct_answer",
        "live-incident-response",
    ),
    RoutingPrecisionCase(
        "commander-military-rank-stays-direct",
        "A promotion to commander is a rank, not an incident role",
        "he was promoted to commander last year",
        "answer_directly",
        "direct_answer",
        "live-incident-response",
    ),
    RoutingPrecisionCase(
        "tracker-field-severity-stays-direct",
        "Severity as a bug-tracker field is not a declared incident severity",
        "explain severity vs priority in jira",
        "answer_directly",
        "direct_answer",
        "live-incident-response",
    ),
    RoutingPrecisionCase(
        "manufacturing-line-down-stays-clarify",
        "A production line down for maintenance is not a production outage",
        "our production line is down for maintenance this week",
        "answer_clarification",
        "",
        "live-incident-response",
    ),
    RoutingPrecisionCase(
        "figurative-outage-stays-clarify",
        "An outage of creativity is a figure of speech",
        "the outage of creativity in this team is the real problem",
        "answer_clarification",
        "",
        "live-incident-response",
    ),
    RoutingPrecisionCase(
        "japanese-write-long-document-stays-clarify",
        "Japanese writing request with a long document stays clarify",
        "移行を説明する長い文書を書いて",
        "answer_clarification",
        "",
        "long-document-reading",
    ),
    RoutingPrecisionCase(
        "chinese-write-long-document-stays-clarify",
        "Chinese writing request with a long document stays clarify",
        "写一份很长的文档来解释迁移",
        "answer_clarification",
        "",
        "long-document-reading",
    ),
    RoutingPrecisionCase(
        "translate-whole-document-stays-clarify",
        "Translating a whole document is not reading it in ranges",
        "translate the whole document to Korean",
        "answer_clarification",
        "",
        "long-document-reading",
    ),
    RoutingPrecisionCase(
        "site-page-by-page-stays-clarify",
        "A site walkthrough page by page is not a document read",
        "walk me through the site page by page",
        "answer_clarification",
        "",
        "long-document-reading",
    ),
    RoutingPrecisionCase(
        "page-number-with-port-stays-clarify",
        "A page number and a port number are not a page count",
        "read the spec, page 12, port 8080",
        "answer_clarification",
        "",
        "long-document-reading",
    ),
    RoutingPrecisionCase(
        "short-translation",
        "Short translation request stays direct",
        "translate this to Korean",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "short-summary",
        "Short summary request stays direct",
        "summarize this in Korean",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "korean-sentence-translation",
        "Korean sentence translation request stays direct",
        "이 문장 영어로 번역해줘",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "korean-paragraph-summary",
        "Korean paragraph summary request stays direct",
        "이 문단 요약해줘",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "korean-image-word-translation",
        "Korean single-word translation with image term stays direct",
        "image라는 단어 한국어로 번역해줘",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "korean-photo-description",
        "Korean photo explanation stays direct",
        "이 사진 설명해줘",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "short-thanks",
        "Short thanks stays direct",
        "thanks",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "short-ok",
        "Short ok stays direct",
        "ok",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "context-what-happened",
        "Context question stays direct",
        "what happened?",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "context-what-did-i-ask",
        "Previous-message question stays direct",
        "what did I just ask?",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "korean-error-troubleshooting",
        "Korean error troubleshooting stays direct",
        "이 오류 왜 나?",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "korean-error-slang",
        "Korean short error slang stays direct",
        "이 오류 뭐임",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "korean-log-review",
        "Korean log review stays direct",
        "이 로그 봐줘",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "command-not-found-help",
        "Command-not-found help stays direct",
        "command not found: omh",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "spanish-thanks",
        "Spanish thanks stays direct",
        "gracias",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "japanese-thanks",
        "Japanese thanks stays direct",
        "ありがとう",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "spanish-concept",
        "Spanish concept question stays direct",
        "¿Qué es Kubernetes?",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "french-concept",
        "French concept question stays direct",
        "Qu’est-ce que Kubernetes ?",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "japanese-concept",
        "Japanese concept question stays direct",
        "Kubernetesとは何ですか？",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "chinese-concept",
        "Chinese concept question stays direct",
        "Kubernetes是什么？",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "hindi-thanks",
        "Hindi thanks stays direct",
        "धन्यवाद",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "hindi-concept",
        "Hindi concept question stays direct",
        "Kubernetes क्या है?",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "hindi-summary",
        "Hindi short summary request stays direct",
        "इसका सारांश दो",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "hindi-translation",
        "Hindi short translation request stays direct",
        "इसे अंग्रेज़ी में अनुवाद करो",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "spanish-explanation",
        "Spanish explanation request stays direct",
        "explícame GraphQL",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "japanese-summary",
        "Japanese summary request stays direct",
        "これを要約して",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "spanish-translation",
        "Spanish translation request stays direct",
        "traduce esto al inglés",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "localized-command-not-found",
        "Localized command-not-found help stays direct",
        "コマンドが見つかりません: omh",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "plain-concept-help",
        "Plain concept explanation stays direct",
        "what is OAuth in simple terms?",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "python-loop-concept",
        "Python loop concept stays direct",
        "what is a loop in Python?",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "strategy-pattern-concept",
        "Strategy pattern concept stays direct",
        "strategy pattern 설명해줘",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "memory-leak-concept",
        "Memory leak concept stays direct",
        "memory leak 설명해줘",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "source-control-concept",
        "Source control concept stays direct",
        "what is source control?",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "github-repo-concept",
        "GitHub repo concept stays direct",
        "what is GitHub repo?",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "kubernetes-concept",
        "Generic Kubernetes concept stays direct",
        "what is Kubernetes?",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "graphql-korean-explanation",
        "Mixed-language GraphQL explanation stays direct",
        "GraphQL 설명해줘",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "kubernetes-korean-concept",
        "Korean Kubernetes concept stays direct",
        "쿠버네티스가 뭐야?",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "korean-error-meaning",
        "Korean error meaning question stays direct",
        "이 에러 무슨 뜻이야?",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "korean-time-question-generic-noise",
        "Korean time question stays direct instead of minting an agent-ops candidate",
        "지금 몇시야?",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "quoted-sentence-translation-generic-noise",
        "Quoted-sentence translation stays direct instead of minting a frontend candidate",
        "'배포는 금요일에 하지 말자'를 영어로 자연스럽게 번역해줘",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "regex-write-generic-noise",
        "Regex request stays direct instead of minting an ultraprocess candidate",
        "write a regex that matches ISO dates",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "exclamatory-thanks-direct",
        "Exclamatory short thanks stays a direct acknowledgement",
        "오 대박 고마워!!",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "language-model-concept-direct",
        "Language model concept question stays direct instead of opening model setup",
        "what is a language model",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "macbook-update-direct",
        "Personal device update question stays direct instead of opening hermes update",
        "how do I update my macbook",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "web-crawler-concept-direct",
        "Web crawler concept question stays direct instead of opening web search setup",
        "what is a web crawler",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "daily-briefing-concept-direct",
        "Briefing concept question stays direct instead of opening morning brief setup",
        "what does a daily briefing mean",
        "answer_directly",
        "direct_answer",
    ),
    # Overroute guard for the generic single-token triggers removed from
    # `research`: `latest` and `investigate` are ordinary English words, so
    # scoring them pulled version questions and debugging requests into
    # source-backed research. The multi-word intents they were standing in for
    # ("latest sources", "look up sources") stay as phrase triggers.
    #
    # `investigate this crash` is also no longer captured by research, but it
    # settles on the clarification path rather than a direct answer, and this
    # negative-control corpus can only express cases that end in a direct-answer
    # lookup kind with a no-workflow claim boundary. It stays uncovered here
    # instead of loosening the corpus contract to fit it.
    RoutingPrecisionCase(
        "latest-version-question-direct",
        "Version question stays direct instead of opening web research",
        "what is the latest version of python",
        "answer_directly",
        "direct_answer",
    ),
    # A version question about another tool. `version` is a trigger word and
    # a routing word of parallel-tools, so this sentence scores 4 for it and
    # is answered directly; one more shared word makes it 5, a clarify. The
    # upstream skill audit's first parallel-tools wording added "supports" to
    # that skill's routing words and moved this sentence to a clarify naming
    # parallel-tools. No `forbidden_candidate`: the scored handoff of a
    # fallback still lists parallel-tools at 4, so the claim is the action.
    RoutingPrecisionCase(
        "plain-version-question-is-not-parallel-tools",
        "A version question about another tool stays a direct answer, not a parallel-tool check",
        "what version of node supports fetch",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "project-glossary-definition-only",
        "A glossary definition is content, not a workflow request",
        "What does dispatch packet mean?",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "project-glossary-say-instead-only",
        "Style guidance in a glossary stays direct",
        "What phrase should I use instead of dispatch packet?",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "project-glossary-localized-label-only",
        "A localized glossary label stays direct",
        "What does 핸드오프 mean?",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "project-glossary-distinct-from-only",
        "A distinct-from note stays direct",
        "What is release train distinct from?",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "project-terms-file-lookup",
        "Project terms file lookup stays a file lookup",
        "what is in PROJECT_TERMS.md?",
        "answer_file_lookup",
        "file_or_text",
    ),
    # Negative control for the naming-is-choosing carve-out: the same Korean
    # issue-to-PR request as `korean-codex-issue-pr-start` with the CLI name
    # removed. Without a named CLI the message must resolve no external owner
    # and no owner-choice provenance; a failure here means genuine inference
    # from message content was reintroduced.
    RoutingPrecisionCase(
        "korean-issue-pr-start-no-named-cli",
        "Unnamed-CLI issue-to-PR paraphrase resolves no external owner",
        "이 이슈 PR 만들 수 있게 작업 시작해줘",
        "answer_clarification",
        "",
    ),
    # ULW fold negative control (issue #954, PR D §8.3): a one-owner
    # one-line fix must not open the folded coordination/persistence
    # capabilities of `ultrawork` -- it stays a clarification, not a route.
    RoutingPrecisionCase(
        "one-owner-one-line-fix",
        "A one-owner one-line fix stays out of coordination and persistence engines",
        "have one person finish this one-line fix",
        "answer_clarification",
        "",
    ),
    # Negative controls for the tests-first delivery triggers on `ultrawork`
    # ("red green refactor", "red-green refactor", "red-green",
    # "failing test first"): a concept question and a why-is-it-failing
    # diagnosis must stay off the tests-first delivery engine. The concept
    # case follows the chain-models-concept shape (no forbidden_candidate:
    # the direct-answer fallback may name low-score candidates while the
    # case still fails on any dispatch, workflow card, or handoff action).
    RoutingPrecisionCase(
        "red-green-refactor-concept",
        "A red-green-refactor concept question stays direct, not a tests-first run",
        "explain what red green refactor means",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "dependency-graph-concept",
        "A dependency graph concept question stays direct, not a delivery run",
        "what is a dependency graph?",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "tests-failing-question",
        "A why-are-tests-failing question stays a clarification, not a tests-first run",
        "why are the tests failing",
        "answer_clarification",
        "",
        "ultrawork",
    ),
    RoutingPrecisionCase("o013-dso", "DSO clarification excludes visual QA", "DSO revenue cutoff", "answer_clarification", "", "visual-qa"),
    RoutingPrecisionCase("o013-asc-606", "ASC 606 clarification excludes model setup", "ASC 606 model", "answer_clarification", "", "model-setup"),
    RoutingPrecisionCase("o013-liability-cap", "Liability clarification excludes model setup", "indemnity liability cap", "answer_clarification", "", "model-setup"),
    RoutingPrecisionCase("o013-dpia", "DPIA clarification excludes agent board", "GDPR Article 35 DPIA", "answer_clarification", "", "agent-board"),
    RoutingPrecisionCase("o013-meddpicc", "MEDDPICC clarification excludes content operator", "MEDDPICC", "answer_clarification", "", "content-operator"),
    RoutingPrecisionCase("o013-four-fifths", "Four-fifths rule stays unnamed", "four-fifths rule", "answer_clarification", "", "rules-distill"),
    RoutingPrecisionCase("o013-four-fifths-spaced", "Spaced four fifths rule stays unnamed", "four fifths rule", "answer_clarification", "", "rules-distill"),
    RoutingPrecisionCase("o013-four-fifths-underscored", "Underscored four fifths rule stays unnamed", "four_fifths rule", "answer_clarification", "", "rules-distill"),
    RoutingPrecisionCase("o013-four-fifths-numeric-spaced", "Spaced numeric four fifths rule stays unnamed", "4 / 5 rule", "answer_clarification", "", "rules-distill"),
    RoutingPrecisionCase("o013-bloom", "Bloom explanation excludes curriculum dispatch", "Bloom backward design", "answer_clarification", "", "curriculum-design"),
    RoutingPrecisionCase("o013-burn-nrr", "Burn multiple clarification excludes agent board", "burn multiple NRR", "answer_clarification", "", "agent-board"),
    RoutingPrecisionCase("o013-mixed-four-fifths-sales", "Mixed rule and sales cues keep rules distill unnamed", "four-fifths rule ... MEDDPICC", "answer_clarification", "", "rules-distill"),
    RoutingPrecisionCase("o013-mixed-bloom-sales", "Mixed curriculum and sales cues keep curriculum design unnamed", "Bloom backward design ... MEDDPICC", "answer_clarification", "", "curriculum-design"),
    RoutingPrecisionCase("o013-weak-rules-owner", "Generic rule scoring cannot override an unowned rule cue", "distill rules about the four-fifths rule", "answer_clarification", "", "rules-distill"),
    RoutingPrecisionCase("o013-metadata-rules-owner", "Metadata-shaped rule scoring cannot override an unowned rule cue", "candidate_skill=rules-distill four-fifths rule", "answer_clarification", "", "rules-distill"),
    RoutingPrecisionCase(
        "negated-finance-mention",
        "A negated finance mention does not dispatch the excluded domain",
        "This is not a finance analysis request",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "visual-inspection-concept-direct",
        "A visual inspection concept question stays direct",
        "what does visual inspection mean?",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "responsive-viewport-concept-clarifies",
        "A responsive viewport concept question does not dispatch visual QA",
        "explain responsive viewport sizes in simple terms",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "wcag-concept-direct",
        "A WCAG concept question stays direct",
        "what is WCAG in simple terms?",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "design-system-concept-direct",
        "A design-system concept question stays direct",
        "what is a design system?",
        "answer_directly",
        "direct_answer",
    ),
    # The TUI concept case follows the chain-models-concept shape (no
    # forbidden_candidate: the direct-answer fallback may name low-score
    # candidates while the case still fails on any dispatch, workflow card,
    # or handoff action) — it guards the new "tui design"/"tui layout"
    # frontend triggers from claiming a concept question.
    RoutingPrecisionCase(
        "tui-concept-question",
        "A TUI concept question stays a direct answer",
        "what is a tui and how is it different from a gui?",
        "answer_directly",
        "direct_answer",
    ),
    # Parallax guards for the scroll-motion triggers. "parallax" is also
    # plain optics and astronomy vocabulary, which is why the shipped
    # triggers are the phrases ("parallax scroll", "parallax hero",
    # "parallax effect") rather than the bare word. These follow the
    # tui-concept-question shape (no forbidden_candidate: the clarify
    # fallback may still name low-score candidates, and "interface design"
    # alone already names frontend) — the case fails on any dispatch,
    # workflow card, or handoff action.
    RoutingPrecisionCase(
        "astronomy-parallax-stays-out-of-frontend",
        "Stellar parallax discussion never dispatches the frontend workflow",
        "Stellar parallax measures the distance to nearby stars and is unrelated to interface design.",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "camera-parallax-stays-out-of-frontend",
        "Viewfinder parallax error discussion never dispatches the frontend workflow",
        "Parallax error in a rangefinder camera viewfinder is unrelated to interface design.",
        "answer_clarification",
        "",
    ),
    # The loose-token half of the same guard. "scroll" is everyday
    # vocabulary, so it is held back to whole-phrase matches in
    # `_WHOLE_PHRASE_ONLY_TRIGGER_TOKENS`; without that hold-back this
    # sentence dispatched to frontend on `scroll` plus the pre-existing
    # `broken`/`terminal` triggers. Reporting a tool's scroll bug is not a
    # UI design brief.
    RoutingPrecisionCase(
        "terminal-scroll-bug-stays-out-of-frontend",
        "A terminal emulator scroll bug never dispatches the frontend workflow",
        "The mouse wheel scroll is broken in my terminal emulator.",
        "answer_clarification",
        "",
    ),
    # Everyday-word guards for the design-reference lane (2026-10-07). The
    # frontend phrases are built from "chart", "theme", "footer", "split",
    # "text", and "marquee", each held back to whole-phrase matches in
    # `_WHOLE_PHRASE_ONLY_TRIGGER_TOKENS`. These carry `forbidden_candidate`
    # because frontend is not named for any of them today, so a regression
    # that merely NAMES frontend in the shortlist fails here, not only one
    # that dispatches it.
    RoutingPrecisionCase(
        "chart-a-course-stays-out-of-frontend",
        "Charting a course for a migration never names the frontend workflow",
        "Chart a course for the migration.",
        "answer_clarification",
        "",
        forbidden_candidate="frontend",
    ),
    RoutingPrecisionCase(
        "email-footer-stays-out-of-frontend",
        "An email footer remark never names the frontend workflow",
        "The footer of the email says unsubscribe.",
        "answer_clarification",
        "",
        forbidden_candidate="frontend",
    ),
    RoutingPrecisionCase(
        "wrong-chart-numbers-stay-out-of-frontend",
        "Wrong numbers in a board-deck chart are a data question, not chart styling",
        "The sales chart in the board deck has the wrong numbers.",
        "answer_clarification",
        "",
        forbidden_candidate="frontend",
    ),
    RoutingPrecisionCase(
        "nlp-split-text-stays-out-of-frontend",
        "Splitting text into sentences never names the frontend workflow",
        "Split text into sentences before tokenizing.",
        "answer_clarification",
        "",
        forbidden_candidate="frontend",
    ),
    RoutingPrecisionCase(
        "quarterly-theme-stays-out-of-frontend",
        "A quarterly theme is planning vocabulary, not chart theming",
        "The chart theme for the quarter is cost cutting.",
        "answer_clarification",
        "",
        forbidden_candidate="frontend",
    ),
    RoutingPrecisionCase(
        "marquee-signing-stays-out-of-frontend",
        "A marquee signing in sports never names the frontend workflow",
        "A marquee signing joined the team this week.",
        "answer_clarification",
        "",
        forbidden_candidate="frontend",
    ),
    # `websearch-setup` triggers on "web search backend", the Hermes setting
    # that picks which provider serves search. `backend` is held back in
    # `_WHOLE_PHRASE_ONLY_TRIGGER_TOKENS`: measured without the hold, this
    # sentence about the user's own server named the setup guide in its
    # shortlist.
    RoutingPrecisionCase(
        "deploy-the-backend-stays-out-of-websearch-setup",
        "Deploying an app backend never names the web search setup guide",
        "deploy the backend",
        "answer_clarification",
        "",
        forbidden_candidate="websearch-setup",
    ),
    # The complete phrase also names the search service of the user's own
    # app. It may lead the shortlist there, but it must never dispatch the
    # setup guide; before the phrase joined the setup-guide list this
    # sentence dispatched a live web lookup. No `forbidden_candidate`: the
    # setup guide is the scored leader and stays the named candidate.
    # `costs`, `too`, `much`, `free`, and `tier` are held back for
    # `websearch-setup` too. Measured without the hold, the first turned from
    # a direct answer into a clarify, and the other two named the setup guide.
    RoutingPrecisionCase(
        "how-much-does-it-cost-stays-direct",
        "A bare price question stays a direct answer",
        "how much does it cost",
        "answer_directly",
        "direct_answer",
        forbidden_candidate="websearch-setup",
    ),
    RoutingPrecisionCase(
        "vendor-free-tier-question-stays-out-of-websearch-setup",
        "A question about a vendor's free tier never names the web search setup guide",
        "is there a free tier for supabase",
        "answer_clarification",
        "",
        forbidden_candidate="websearch-setup",
    ),
    RoutingPrecisionCase(
        "api-cost-complaint-stays-out-of-websearch-setup",
        "An API cost complaint never names the web search setup guide",
        "the api costs too much per call",
        "answer_clarification",
        "",
        forbidden_candidate="websearch-setup",
    ),
    # Measured with `web extract backend` as a catalog trigger, this
    # sentence about the user's own parser dispatched the setup guide.
    RoutingPrecisionCase(
        "slow-web-extract-backend-stays-out-of-websearch-setup",
        "Profiling an app's web extract backend never names the web search setup guide",
        "the web extract backend is slow, profile the parser",
        "answer_clarification",
        "",
        forbidden_candidate="websearch-setup",
    ),
    # Building a search service is the user's own code. The setup guide may
    # lead the shortlist on the phrase, but it must never dispatch; before the
    # phrase joined the setup-guide list this sentence dispatched
    # `deep-interview`, which no longer appears among the candidates.
    RoutingPrecisionCase(
        "building-a-web-search-backend-never-dispatches-the-setup-guide",
        "Building a web search backend asks rather than opening the setup guide",
        "build a web search backend with elasticsearch",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "debugging-a-web-search-backend-never-dispatches-the-setup-guide",
        "Debugging an app's web search backend asks rather than opening the setup guide",
        "our web search backend returns 500, debug the handler",
        "answer_clarification",
        "",
    ),
    # Infra-cache maintenance guards for the "prompt caching"/"prompt cache"/
    # "cache hygiene" triggers: build- and HTTP-cache work shares the word
    # "cache" but has nothing to do with prompt-prefix placement.
    RoutingPrecisionCase(
        "npm-cache-clear-direct",
        "Build-cache maintenance never dispatches context budget review",
        "clear the npm cache and rerun the build",
        "answer_clarification",
        "",
        "context-budget-review",
    ),
    RoutingPrecisionCase(
        "stale-browser-cache-direct",
        "HTTP cache debugging never dispatches context budget review",
        "the browser cache is serving a stale bundle, fix the cache headers",
        "answer_clarification",
        "",
        "context-budget-review",
    ),
    # The same guard for the overflow triggers. "window", "running out", "hand
    # off", "new", and "session" are held back from this workflow's trigger
    # tokens precisely so these two sentences keep answering the question they
    # asked instead of naming a budget review.
    RoutingPrecisionCase(
        "browser-window-resize-direct",
        "Resizing a browser window never dispatches context budget review",
        "resize the browser window to 1280 wide and rerun the screenshot",
        "answer_clarification",
        "",
        "context-budget-review",
    ),
    RoutingPrecisionCase(
        "disk-space-running-out-direct",
        "Running out of disk space never dispatches context budget review",
        "the build is running out of disk space",
        "answer_clarification",
        "",
        "context-budget-review",
    ),
    RoutingPrecisionCase(
        "new-project-file-concept-direct",
        "New-project file concept question stays a lookup, not an app delivery loop",
        "what files should a new project have",
        "answer_file_lookup",
        "file_or_text",
    ),
    # These two exercise the greenfield-bootstrap guard boundary directly: the
    # bare noun "project scaffolding" occurs naturally inside questions about
    # repos that already exist, so it must never dispatch the delivery loop.
    # Both follow the chain-models-concept shape (no forbidden_candidate: the
    # direct-answer fallback may name low-score candidates while the case
    # still fails on any dispatch, workflow card, or handoff action).
    RoutingPrecisionCase(
        "project-scaffolding-question-direct",
        "A project-scaffolding how-does-it-work question stays a direct answer",
        "how does project scaffolding work here",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "project-scaffolding-existing-direct",
        "Describing existing project scaffolding never dispatches the delivery loop",
        "explain the project scaffolding we already have",
        "answer_directly",
        "direct_answer",
    ),
    # Bootstrap-file noun guard: naming LICENSE/.gitignore/README does not by
    # itself mean "create the project" - a concept question about one of them
    # stays a direct answer with no forbidden_candidate needed (same
    # chain-models-concept shape as the pair above; only one noun is present,
    # so the >=2-noun bootstrap-file threshold never engages).
    RoutingPrecisionCase(
        "license-file-concept-direct",
        "A LICENSE-file concept question stays direct, not the bootstrap dispatch",
        "explain what a LICENSE file is",
        "answer_directly",
        "direct_answer",
    ),
    # These two name exactly one bootstrap-file noun and no add/create/set-up
    # multi-file ask, so the bootstrap-file guard must never claim them even
    # though the candidate list still surfaces other real workflows.
    RoutingPrecisionCase(
        "gitignore-troubleshooting-not-bootstrap",
        "A .gitignore troubleshooting question stays clarification, not the bootstrap dispatch",
        "why does my .gitignore not work",
        "answer_clarification",
        "",
        "idea-to-deploy",
    ),
    RoutingPrecisionCase(
        "gitignore-single-rule-edit-not-bootstrap",
        "Adding one rule to an existing .gitignore stays clarification, not the bootstrap dispatch",
        "add this rule to .gitignore",
        "answer_clarification",
        "",
        "idea-to-deploy",
    ),
    # Retired advisor filename shield: `ask` no longer owns the bare
    # `claude`/`gemini` tokens (executor detection moved to
    # `routing/coding_route_actions.named_executor_owners`, applied only when
    # Claude Code is the sole named owner), so the advisor lane is unreachable
    # from a CLAUDE.md filename. Other skills still match the token at low
    # score, which is why this case still earns its place: it pins that no
    # low-score match ever becomes a dispatch. No forbidden_candidate —
    # the clarify fallback may still name `ask` as a low-score candidate; the
    # case fails on any dispatch.
    RoutingPrecisionCase(
        "context-file-question-not-advisor",
        "A CLAUDE.md content question never dispatches the external advisor",
        "CLAUDE.md 파일 내용 설명해줘",
        "answer_clarification",
        "",
    ),
    # Claude-delegation collision guard: "클로드한테" plus a delivery postposition
    # is unambiguous executor delegation only once it co-occurs with a delegation
    # verb (see `_claude_bare_name_delegation_requested` in `routing/policy.py`).
    # An advisor-shaped ask using the same postposition must stay non-delivery.
    RoutingPrecisionCase(
        "claude-ask-not-delegation",
        "Asking Claude for input never dispatches the named coding-agent delivery lane",
        "클로드한테 물어봐줘",
        "answer_clarification",
        "",
    ),
    # Bare "해줘" collision guards: `CODING_DELIVERY_REQUEST_PHRASES` gained "해줘"
    # (see `routing/executor_cues.py`), which is safe only because every consumer
    # also requires an explicit named coding-agent phrase. Neither message below
    # names one, so neither may reach the coding-delivery dispatch lane.
    RoutingPrecisionCase(
        "bare-haejwo-no-agent-name",
        "A bare 'do it' request without a named coding agent never dispatches",
        "그거 해줘",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "urgent-haejwo-no-agent-name",
        "An urgent 'do it fast' request without a named coding agent never dispatches",
        "빨리 해줘",
        "answer_clarification",
        "",
    ),
    # Maestro shield: concept questions about maestro, prepared handoffs, or a
    # coding-agent name must stay direct answers, never a maestro dispatch.
    RoutingPrecisionCase(
        "maestro-concept-question",
        "A maestro concept question stays a direct answer",
        "maestro가 뭐야?",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "orchestra-conductor-not-maestro",
        "An orchestra-conductor question never dispatches the maestro skill",
        "what does maestro mean in an orchestra?",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "handoff-concept-question",
        "A prepared-handoff concept question stays a direct answer",
        "what does a prepared handoff mean?",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "codex-concept-keeps-shield",
        "A Codex concept question never dispatches maestro off the named CLI",
        "codex가 뭐야",
        "answer_directly",
        "direct_answer",
    ),
    # Adversarial-consensus shield: the workflow's vocabulary is borrowed from
    # security ("red team"), machine learning ("적대적 공격"), and ordinary English
    # ("perspective", "poke holes"). A question ABOUT any of those words is a
    # concept question, never a request to run three adversarial rounds.
    RoutingPrecisionCase(
        "adversarial-consensus-concept-question",
        "An adversarial-consensus concept question stays a direct answer",
        "what does adversarial consensus mean?",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "adversarial-attack-ml-concept",
        "An adversarial-attack ML question never dispatches the consensus rounds",
        "적대적 공격이 뭐야?",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "red-team-security-concept",
        "A security red-team concept question stays a direct answer",
        "what is a red team?",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "hyperplan-concept-question",
        "A hyperplan vocabulary question stays a direct answer",
        "hyperplan 뜻이 뭐야?",
        "answer_directly",
        "direct_answer",
    ),
    # llm-app-dev shield. The workflow is named out of the most generic
    # vocabulary in the catalog -- `llm`, `app`, `rag`, `prompt`, `eval` -- and
    # every one of those words also appears in a question ABOUT LLMs, which is a
    # direct answer, and in the subject matter of the agent-operations skills,
    # which are a different lane. These pin the boundary from the negative side.
    RoutingPrecisionCase(
        "llm-concept-question",
        "An LLM concept question stays a direct answer, not an app build handoff",
        "what is an llm?",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "llm-concept-question-korean",
        "A Korean LLM concept question stays a direct answer",
        "llm이 뭐야?",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "retrieval-augmented-generation-concept",
        "A retrieval-augmented-generation concept question stays a direct answer",
        "what is retrieval augmented generation?",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "rag-concept-question-korean",
        "A Korean RAG concept question stays a direct answer",
        "rag가 뭐야?",
        "answer_directly",
        "direct_answer",
    ),
    # Public-board half of the same shield. The destination phrase alone is a
    # concept question, a disclosure question, or somebody else's standup
    # board; only a destination plus the model-powered product that would
    # publish to it is an LLM build request.
    RoutingPrecisionCase(
        "public-board-concept-question",
        "A public-board concept question stays a direct answer, not an app build handoff",
        "what is a public message board?",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "public-board-disclosure-concept-question",
        "A public-disclosure question about boards stays out of the LLM app build handoff",
        "is posting to a public board considered public disclosure?",
        "answer_clarification",
        "",
        "llm-app-dev",
    ),
    RoutingPrecisionCase(
        "team-public-board-mention",
        "Mentioning the team's own public board does not open an LLM app build handoff",
        "our team uses a public board for standups",
        "answer_clarification",
        "",
        "llm-app-dev",
    ),
    # Ask bare-token retirement: "claude code가 뭐야" previously reached `ask` via
    # the now-removed bare `claude` trigger at score 9. With that token gone the
    # top catalog matches tie at score 4, so this pins the honest new
    # destination -- one clarifying question, never a dispatch to the external
    # advisor lane for a plain concept question.
    RoutingPrecisionCase(
        "claude-code-concept-question-not-advisor",
        "A Claude Code concept question never dispatches the external advisor",
        "claude code가 뭐야",
        "answer_clarification",
        "",
    ),
    # #1163 review follow-up: with `ask`'s bare `claude`/`gemini` triggers gone,
    # a bare one-word "gemini" message no longer inflates `ask`'s score high
    # enough to dispatch -- it ties with `prompt-import-readiness` at score 3
    # and asks one clarifying question instead. This was noted by review as
    # defensible but unpinned; this case locks the observed destination in.
    RoutingPrecisionCase(
        "bare-gemini-word-not-advisor-dispatch",
        "A bare one-word 'gemini' message never dispatches the external advisor",
        "gemini",
        "answer_clarification",
        "",
    ),
    # The three technical-domain lanes route on the same vocabulary people use
    # to ask what a term means. These pin the question half: a definition
    # question stays an answer instead of opening a domain workflow.
    RoutingPrecisionCase(
        "borrow-checker-concept-question",
        "A borrow-checker definition question stays a direct answer",
        "what is a borrow checker?",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "undefined-behavior-concept-question",
        "A Korean undefined-behavior definition question stays a direct answer",
        "미정의 동작이 뭐야?",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "rest-api-design-concept-question",
        "A REST API design definition question stays a direct answer",
        "what is rest api design?",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "auth-boundary-concept-question",
        "An auth-boundary definition question stays a direct answer",
        "what is an auth boundary?",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "segmentation-fault-concept-question",
        "A segmentation-fault definition question stays a direct answer",
        "what is a segmentation fault?",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "native-binary-concept-question",
        "A native-binary definition question stays a direct answer",
        "what is a native binary?",
        "answer_directly",
        "direct_answer",
    ),
    # Per-language negative controls for the shipped trigger packs. A pack
    # widens what the router recognises, which is also the way a pack goes
    # wrong: a phrase short or generic enough to sit inside an ordinary
    # sentence turns every such sentence into a dispatch. English and Korean
    # have carried these controls since the corpus began; a language whose
    # phrases ship without them is a language nobody has measured.
    #
    # The first case in each language deliberately CONTAINS a pack phrase and
    # is still not a work request. It settles on a clarification rather than a
    # direct answer -- the concept-question fast path that turns
    # "what does X mean" into a direct answer is written in English and Korean
    # markers only, and widening that surface is a different change from
    # widening trigger tables. What matters here is what it does not do:
    # no dispatch, no picker, no handoff.
    RoutingPrecisionCase(
        "japanese-frontend-concept-question",
        "A Japanese frontend definition question does not become a frontend handoff",
        "フロントエンドって何の略ですか？",
        "answer_clarification",
        "",
        "ultrawork",
    ),
    RoutingPrecisionCase(
        "japanese-parallel-processing-concept",
        "Japanese parallel-processing vocabulary alone does not reach the parallel lane",
        "並列処理とは何ですか？",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "japanese-ownership-concept-question",
        "A Japanese ownership concept question stays a direct answer, not a Rust contract",
        "所有権という考え方を簡単に説明して",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "chinese-frontend-backend-concept-question",
        "A Chinese frontend-vs-backend question does not become a frontend or backend handoff",
        "前端和后端有什么区别？",
        "answer_clarification",
        "",
        "ultrawork",
    ),
    RoutingPrecisionCase(
        "chinese-deep-learning-concept",
        "Chinese deep-learning vocabulary alone does not reach the research lane",
        "深度学习是什么意思？",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "chinese-rag-concept-question",
        "A Chinese retrieval-augmented-generation definition question stays a direct answer",
        "检索增强生成这个词是什么意思？",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "chinese-thanks",
        "A Chinese thank-you stays a direct answer",
        "谢谢",
        "answer_directly",
        "direct_answer",
    ),
    # Indonesian. The review of the contributed `id` pack (#2154) found five
    # phrases generic enough to route ordinary chat -- a team's work plan, "ask
    # me one at a time", "don't assume, ask first", a medicine reminder, a
    # parent's blood pressure -- and one whole phrase that dispatched a
    # question about what that phrase means. Those phrases did not ship. Each
    # case below is pinned to the outcome the router gave before the pack, and
    # forbids the lane the dropped phrase reached; the cron question names
    # `automation-blueprint` in its clarification either way, so it pins only
    # that it does not dispatch.
    RoutingPrecisionCase(
        "indonesian-team-work-plan-is-not-a-plan-request",
        "An Indonesian team work plan stays out of the plan lane",
        "Buat rencana kerja tim marketing untuk bulan depan.",
        "answer_clarification",
        "",
        "plan",
    ),
    RoutingPrecisionCase(
        "indonesian-ask-me-one-at-a-time-is-not-an-interview",
        "Asking to be asked one question at a time stays out of the interview lane",
        "Kalau ada yang kurang jelas, tanya saya satu per satu ya.",
        "answer_clarification",
        "",
        "deep-interview",
    ),
    RoutingPrecisionCase(
        "indonesian-ask-before-assuming-is-not-an-interview",
        "Asking to be asked before an assumption stays out of the interview lane",
        "Jangan berasumsi tanya dulu kalau kamu ragu soal data penjualan.",
        "answer_clarification",
        "",
        "deep-interview",
    ),
    RoutingPrecisionCase(
        "indonesian-medicine-reminder-is-not-an-automation",
        "A recurring medicine reminder stays out of the automation blueprint",
        "Tolong siapkan tugas berulang untuk mengingatkan saya minum obat.",
        "answer_clarification",
        "",
        "automation-blueprint",
    ),
    RoutingPrecisionCase(
        "indonesian-blood-pressure-monitoring-is-not-an-automation",
        "Watching a parent's blood pressure stays out of the automation blueprint",
        "Atur pemantauan berkala tekanan darah ibu saya.",
        "answer_clarification",
        "",
        "automation-blueprint",
    ),
    RoutingPrecisionCase(
        "indonesian-cron-meaning-question-does-not-dispatch",
        "An Indonesian question about what a cron request means does not dispatch",
        "Buat jadwal cron untuk Hermes itu apa sih artinya?",
        "answer_clarification",
        "",
    ),
    # Vagueness gate on heavy-mode routing (P2-12): a filler-only vague
    # request that does not name `ultrawork`/`maestro` stays on its existing
    # light-lane clarify path -- the new heavy-lane gate never engages.
    RoutingPrecisionCase(
        "heavy-lane-gate-vague-light-request-not-gated",
        "A vague filler-only request without a heavy-lane cue clarifies on its own light candidate, not ultrawork",
        "do this please",
        "answer_clarification",
        "",
        "ultrawork",
    ),
    RoutingPrecisionCase(
        "heavy-lane-gate-vague-light-request-not-gated-maestro",
        "A vague filler-only request without a heavy-lane cue clarifies on its own light candidate, not maestro",
        "please help with this",
        "answer_clarification",
        "",
        "maestro",
    ),
    RoutingPrecisionCase(
        "model-price-question-not-model-optimization",
        "A model price question clarifies instead of opening the model-onboarding process",
        "which model is cheapest right now",
        "answer_clarification",
        "",
        "model-optimization",
    ),
    RoutingPrecisionCase(
        "query-optimization-not-model-optimization",
        "Optimizing a query is not onboarding a model",
        "optimize this query",
        "answer_clarification",
        "",
        "model-optimization",
    ),
    RoutingPrecisionCase(
        "api-deploy-request-not-inference-serving",
        "Deploying an ordinary web API is not model serving",
        "deploy the payments api to staging",
        "answer_clarification",
        "",
        "inference-serving",
    ),
    RoutingPrecisionCase(
        "serving-size-question-not-inference-serving",
        "A recipe serving question never touches model serving",
        "how many servings does this recipe make",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "credit-card-debt-not-tech-debt-audit",
        "A personal finance debt question never opens the debt ledger",
        "how should I pay off my credit card debt faster",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "loan-domain-feature-not-tech-debt-audit",
        "A loan-domain feature request is coding work, not a debt audit",
        "add a debt payoff calculator to the loan app",
        "answer_clarification",
        "",
        "tech-debt-audit",
    ),
    RoutingPrecisionCase(
        "sales-award-not-award-bar-score",
        "A business award announcement never opens the award-bar score",
        "we won a sales award last quarter, help me draft the announcement",
        "answer_clarification",
        "",
        "award-bar-score",
    ),
    RoutingPrecisionCase(
        "awards-page-feature-not-award-bar-score",
        "Building an awards page is frontend work, not an award-bar score",
        "add an awards and press page to the marketing site",
        "answer_clarification",
        "",
        "award-bar-score",
    ),
    RoutingPrecisionCase(
        "blast-radius-question-stays-direct",
        "A blast-radius question stays a direct answer, not the phase planner",
        "how big is the blast radius here",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "refactoring-concept-question-not-refactor-plan",
        "A refactoring concept question clarifies instead of opening the phase planner",
        "explain contract-first refactoring",
        "answer_clarification",
        "",
        "refactor-plan",
    ),
    RoutingPrecisionCase(
        "module-import-question-not-codebase-uml",
        "Asking which module imports another is a code question, not a diagram request",
        "which module imports the router",
        "answer_clarification",
        "",
        "codebase-uml",
    ),
    RoutingPrecisionCase(
        "draw-release-timeline-picture-not-codebase-uml",
        "Drawing a release timeline picture shares the verbs, not the intent, with drawing the codebase",
        "can you draw the release timeline as a picture",
        "answer_clarification",
        "",
        "codebase-uml",
    ),
    RoutingPrecisionCase(
        "state-library-choice-not-frontend-refactor",
        "Choosing a state library is a clarification, not a component refactor",
        "which state management library should we pick",
        "answer_clarification",
        "",
        "frontend-refactor",
    ),
    RoutingPrecisionCase(
        "state-library-opinion-not-frontend-refactor",
        "A state-library opinion question clarifies instead of opening the UI refactor workflow",
        "is redux still worth using",
        "answer_clarification",
        "",
        "frontend-refactor",
    ),
    RoutingPrecisionCase(
        # `memory`, `provider`, `retention`, and `deletion` are the memory
        # provider lifecycle vocabulary. Asked as a concept question they are
        # an answer, not a readiness assessment of any named provider.
        "memory-retention-concept-not-connector-readiness",
        "A concept question about memory retention stays direct",
        "what does memory retention usually mean",
        "answer_directly",
        "direct_answer",
        "external-connector-readiness",
    ),
    RoutingPrecisionCase(
        "provider-deletion-concept-not-connector-readiness",
        "A concept question about provider deletion does not name the connector workflow",
        "how is provider deletion different from account deletion",
        "answer_clarification",
        "",
        "external-connector-readiness",
    ),
    RoutingPrecisionCase(
        "memories-concept-question-not-memory-sync",
        "A concept question about memories stays direct, not a memory review",
        "how do computers store memories",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        # This is the load-bearing guard for the memory-sync token hold-back:
        # with the hold-back lifted, bare `still`+`true` trigger-token credit
        # names memory-sync as the clarify candidate for this ordinary
        # follow-up sentence.
        "still-true-followup-not-memory-sync",
        "An ordinary is-that-still-true follow-up does not name the memory review",
        "is that still true",
        "answer_clarification",
        "",
        "memory-sync",
    ),
    # Sentences that name Jev as a model or name it among options, none of
    # which addresses Jev: none may name `jev-ask` as a candidate.
    RoutingPrecisionCase(
        "jev-as-coding-model-question-not-jev-ask",
        "Asking whether Jev is a good coding model is not a typed Jev ask",
        "is jev a good coding model?",
        "answer_clarification",
        "",
        "jev-ask",
    ),
    RoutingPrecisionCase(
        "jev-default-model-setting-not-jev-ask",
        "Setting Jev as the default model is model setup, not a typed Jev ask",
        "set my default model to jev",
        "answer_clarification",
        "",
        "jev-ask",
    ),
    RoutingPrecisionCase(
        "decide-between-two-options-not-jev-ask",
        "Choosing between two databases is a decision request, not a typed Jev ask",
        "help me decide between postgres and mysql",
        "answer_clarification",
        "",
        "jev-ask",
    ),
    # Sentences that talk about Jev -- a choice among options, its docs, its
    # pricing page, its question format -- without addressing it.
    RoutingPrecisionCase(
        "jev-or-gpt-choice-not-jev-ask",
        "Choosing between Jev and GPT for a classifier is not a typed Jev ask",
        "should we use jev or gpt for this classifier?",
        "answer_clarification",
        "",
        "jev-ask",
    ),
    RoutingPrecisionCase(
        "jev-docs-reading-not-jev-ask",
        "Reading through Jev's docs does not address Jev",
        "read through jev docs and summarize the API",
        "answer_clarification",
        "",
        "jev-ask",
    ),
    RoutingPrecisionCase(
        "jev-pricing-page-not-jev-ask",
        "Going through Jev's pricing page does not address Jev",
        "go through jev's pricing page and compare it with openrouter",
        "answer_clarification",
        "",
        "jev-ask",
    ),
    RoutingPrecisionCase(
        "jev-question-format-docs-not-jev-ask",
        "Complaining about the Jev question format docs is not a Jev ask",
        "the jev question format docs are confusing",
        "answer_clarification",
        "",
        "jev-ask",
    ),
    RoutingPrecisionCase(
        "feature-prototype-concept-not-decision-prototype",
        "Choosing a mockup style does not open a bounded decision experiment",
        "Help me choose a mockup style for this feature.",
        "answer_clarification",
        "",
        "decision-prototype",
    ),
    RoutingPrecisionCase(
        "onboarding-lifecycle-concept-not-lifecycle-growth",
        "A generic mobile-app improvement request does not open a growth experiment",
        "How should we improve our mobile app?",
        "answer_clarification",
        "",
        "lifecycle-growth",
    ),
    RoutingPrecisionCase(
        "customer-needs-research-not-product-discovery-validation",
        "A generic new-market learning question does not claim a discovery decision workflow",
        "What should we learn about a new market?",
        "answer_clarification",
        "",
        "product-discovery-validation",
    ),
    RoutingPrecisionCase(
        "schema-validation-concept-not-product-discovery-validation",
        "Technical schema validation does not become customer discovery",
        "What does schema validation mean?",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "sales-forecast-concept-not-sales-pipeline-review",
        "Preparing for one sales meeting does not open a portfolio review",
        "Help me prepare for a sales meeting.",
        "answer_clarification",
        "",
        "sales-pipeline-review",
    ),
    # Point-in-time web evidence (#1403). The guard needs a cutoff or capture
    # phrase *and* a web context: "as of" alone is how people report status
    # and ask what a term means, and "snapshot" or "archived" alone name
    # tests and buckets, so none of these may reach the lookup lane.
    RoutingPrecisionCase(
        "as-of-status-report-stays-out-of-web-research",
        "A status report that happens to say as-of does not open point-in-time research",
        "as of today I'm done with the migration",
        "answer_clarification",
        "",
        "web-research",
    ),
    RoutingPrecisionCase(
        "as-of-concept-question-stays-direct",
        "A definition question about the phrase as-of stays direct",
        "what does 'as of' mean in a contract?",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "jest-snapshot-failure-stays-out-of-web-research",
        "A snapshot-test failure does not open point-in-time research",
        "snapshot testing in jest keeps failing",
        "answer_clarification",
        "",
        "web-research",
    ),
    RoutingPrecisionCase(
        "archived-logs-stay-out-of-web-research",
        "Archived logs in a bucket are not an archived web capture",
        "the archived logs are in the old bucket",
        "answer_clarification",
        "",
        "web-research",
    ),
    RoutingPrecisionCase(
        "realtime-voice-phrase-translation-stays-direct",
        "Realtime voice named as translation input is not a connector adoption question",
        "translate the phrase realtime voice into korean",
        "answer_directly",
        "direct_answer",
        "external-connector-readiness",
    ),
    RoutingPrecisionCase(
        "barge-in-definition-stays-direct",
        "Asking what barge-in means is a definition, not a voice trial",
        "explain what barge-in means in plain english",
        "answer_directly",
        "direct_answer",
        "external-connector-readiness",
    ),
    RoutingPrecisionCase(
        "voice-memo-file-lookup-stays-a-file-lookup",
        "Finding a voice memo file is an ordinary file lookup",
        "where is the voice memo file in this repo",
        "answer_file_lookup",
        "file_or_text",
        "external-connector-readiness",
    ),
    RoutingPrecisionCase(
        "billing-receipt-question-stays-direct",
        "A receipt in a billing table is not a voice trial receipt",
        "what does a receipt look like in the billing table",
        "answer_directly",
        "direct_answer",
        "external-connector-readiness",
    ),
    # "memory" and "provider" both occur here in their ordinary senses -- a heap
    # leak and a list of suppliers -- and neither is a provider-posture
    # question. The match is the complete noun phrase or nothing.
    RoutingPrecisionCase(
        "memory-leak-provider-list-stays-direct",
        "A heap leak beside the word provider is not memory-provider readiness",
        "the parser leaks memory when the provider list grows",
        "answer_clarification",
        "",
        "external-connector-readiness",
    ),
    # A surveillance camera is the unrelated sense of the word the Korean
    # continuous-watch pack phrases are built from.
    RoutingPrecisionCase(
        "korean-surveillance-camera-format-stays-direct",
        "A Korean question about surveillance-camera video is not a recurring-ops request",
        "감시 카메라 영상 포맷이 뭐야",
        "answer_directly",
        "direct_answer",
        "automation-blueprint",
    ),
    # One per bare verb held back from the continuous-watch phrases: "keep",
    # "monitor", "watch". Each of these sentences is the one-off sense of that
    # verb and none of them is a recurring operation.
    RoutingPrecisionCase(
        "keep-old-api-stays-a-clarification",
        "Keeping an old API around is not a recurring operation",
        "keep the old api around for one more release",
        "answer_clarification",
        "",
        "automation-blueprint",
    ),
    RoutingPrecisionCase(
        "second-monitor-purchase-stays-a-clarification",
        "Buying a monitor is not a monitoring schedule",
        "i need to buy a second monitor for this desk",
        "answer_clarification",
        "",
        "automation-blueprint",
    ),
    RoutingPrecisionCase(
        "watch-out-warning-stays-a-clarification",
        "Watching out for a race condition is not a recurring watch",
        "watch out for the race condition in this handler",
        "answer_clarification",
        "",
        "automation-blueprint",
    ),
    RoutingPrecisionCase(
        "daily-digest-as-translation-input-stays-direct",
        "A cadence word inside translation input is not a cadence",
        "translate the phrase daily digest into french",
        "answer_directly",
        "direct_answer",
        "automation-blueprint",
    ),
    RoutingPrecisionCase(
        "protocol-heartbeat-question-stays-direct",
        "A protocol heartbeat is a concept question, not a liveness watch",
        "what does a heartbeat timeout mean in this protocol spec",
        "answer_directly",
        "direct_answer",
        "automation-blueprint",
    ),
    RoutingPrecisionCase(
        "git-rollback-question-stays-direct",
        "A rollback concept question is not a memory-provider trial",
        "what is a rollback in git",
        "answer_directly",
        "direct_answer",
        "external-connector-readiness",
    ),
    RoutingPrecisionCase(
        "database-migration-stays-a-clarification",
        "Migrating a database is not migrating a memory provider",
        "we need to migrate the old database this weekend",
        "answer_clarification",
        "",
        "external-connector-readiness",
    ),
    RoutingPrecisionCase(
        "function-output-question-stays-direct",
        "A function's output is not a generated artifact",
        "what is the output of this function",
        "answer_directly",
        "direct_answer",
        "verification-gate",
    ),
    RoutingPrecisionCase(
        "release-artifact-upload-stays-a-clarification",
        "A release artifact to upload is not a generated path in a diff",
        "upload the artifact to the release page",
        "answer_clarification",
        "",
        "verification-gate",
    ),
    RoutingPrecisionCase(
        "laptop-upgrade-stays-a-clarification",
        "Upgrading a laptop is not a dependency upgrade",
        "upgrade my laptop to the new os",
        "answer_clarification",
        "",
        "refactor-plan",
    ),
    RoutingPrecisionCase(
        "phone-version-jump-is-not-a-dependency-upgrade",
        "A phone model jump has the version-jump shape and no word of software",
        "upgrade my iphone from 14 to 16",
        "answer_clarification",
        "",
        "refactor-plan",
    ),
    RoutingPrecisionCase(
        "price-bump-is-not-a-dependency-bump",
        "A price that bumped between two numbers is not a version bump",
        "the price bumped from 10 to 12 dollars",
        "answer_clarification",
        "",
        "refactor-plan",
    ),
    RoutingPrecisionCase(
        "shipping-upgrade-is-not-a-framework-upgrade",
        "Express shipping is not the express framework",
        "upgrade to express shipping from 5 to 2 days",
        "answer_clarification",
        "",
        "refactor-plan",
    ),
    RoutingPrecisionCase(
        "dependabot-bump-for-a-cve-is-an-event-not-an-upgrade",
        "A bump that fixes a CVE is a security event, not routine upgrade work",
        "dependabot bumped lodash from 4.17.20 to 4.17.21 to fix CVE-2021-23337",
        "answer_clarification",
        "",
        "refactor-plan",
    ),
    RoutingPrecisionCase(
        "price-change-consumer-impact-stays-a-clarification",
        "A price change's effect on customers is not an API consumer impact",
        "the consumer impact of the price change on our customers",
        "answer_clarification",
        "",
        "backend",
    ),
    RoutingPrecisionCase(
        "image-rotation-stays-a-clarification",
        "Rotating an image is not rotating a credential",
        "rotate the image ninety degrees",
        "answer_clarification",
        "",
        "security-safety-review",
    ),
    RoutingPrecisionCase(
        "engine-redline-stays-a-clarification",
        "An engine at its redline is not a contract redline",
        "the engine is running at the redline",
        "answer_clarification",
        "",
        "legal-compliance-review",
    ),
    RoutingPrecisionCase(
        "salary-negotiation-remark-stays-direct",
        "A remark about a salary negotiation is not negotiation preparation",
        "the salary negotiation went well",
        "answer_directly",
        "direct_answer",
        "legal-compliance-review",
    ),
    RoutingPrecisionCase(
        "build-queue-capacity-stays-a-clarification",
        "Queue capacity is not team capacity",
        "we need more capacity in the build queue",
        "answer_clarification",
        "",
        "strategy-brief",
    ),
    RoutingPrecisionCase(
        "growing-demand-remark-stays-a-clarification",
        "Demand for a feature is not demand against capacity",
        "the demand for this feature is growing",
        "answer_clarification",
        "",
        "strategy-brief",
    ),
    # Negative controls for the three trigger tables folded into a target home
    # by #1691. Each retired skill was built out of everyday words -- a bare
    # metric noun, a best-practice question, a durability adjective -- and the
    # scorer credits a multi-word trigger as its separate tokens too, so
    # folding them onto a bigger sibling is exactly the move that can widen
    # the sibling past its intent. These three sentences use those words in
    # the sense that is not a request: a metric that is already exported, a
    # convention question about git branch names, and a changelog remark. They
    # fell back before the fold and must still fall back after it.
    #
    # No `forbidden_candidate`: that field reads `route.candidate_skill`,
    # which stays set through a fallback, and the claim here is about the
    # ACTION, which the case already fails on.
    RoutingPrecisionCase(
        "exported-throughput-metric-stays-a-direct-answer",
        "A metric the team already exports is not a performance investigation",
        "throughput of the kafka consumer is a metric we already export",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "branch-naming-best-practice-stays-a-direct-answer",
        "A convention question is not a cited web-retrieval request",
        "what is the best practice for naming git branches",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "official-docs-remark-stays-a-direct-answer",
        "Reporting what the docs said is not asking to go read them",
        "official docs say the flag was removed",
        "answer_directly",
        "direct_answer",
    ),
    # #1688. A skill NAME was matched by plain containment, so a name that is
    # an ordinary English word claimed every sentence that happened to spell
    # it -- including inside a longer word. Two mechanisms, both pinned here.
    #
    # The first three fired INSIDE another word: `loop` inside
    # `CrashLoopBackOff` and `ask` inside `asked`, each crediting the `name:`
    # phrase and the identically-spelled trigger for a word nobody typed. The
    # Kubernetes sentence is kept in both languages because the misfire
    # reproduced on three separate phrasings, which is what made it a
    # mechanism rather than an accident. No `forbidden_candidate` is needed
    # on the Korean one -- it falls back -- but it is set where the wrong
    # skill would otherwise still be the named candidate through a clarify.
    RoutingPrecisionCase(
        "crashloopbackoff-is-not-the-loop-engine",
        "A Kubernetes restart loop is not the durable goal engine",
        "pods stuck in CrashLoopBackOff after helm upgrade",
        "answer_clarification",
        "",
        "loop",
    ),
    RoutingPrecisionCase(
        "crashloopbackoff-korean-is-not-the-loop-engine",
        "A Korean Kubernetes restart loop is not the durable goal engine",
        "파드가 CrashLoopBackOff 상태인데 어떻게 디버깅하죠",
        "answer_clarification",
        "",
        "loop",
    ),
    RoutingPrecisionCase(
        "asked-is-not-the-advisor-skill",
        "The past tense of ask is not a request for an external advisor",
        "a user asked us to delete all their data (GDPR)",
        "answer_clarification",
        "",
        "ask",
    ),
    # The second mechanism needs no misspelling at all: one occurrence of a
    # one-word name was credited four times over -- `name:` at +5, the
    # identically-spelled trigger phrase at +6, that trigger's token at +3,
    # and the same token again from the metadata fold at +1. Fifteen points
    # for one word clears the high-confidence threshold alone, so a hiring
    # question dispatched to the backend coding lane. Both hiring sentences
    # keep `backend` as the named candidate through the clarify, so the claim
    # here is the ACTION: a mention is worth a question, not a dispatch.
    RoutingPrecisionCase(
        "hiring-a-backend-engineer-is-not-the-backend-lane",
        "Deciding which engineer to hire is not backend implementation work",
        "should I hire a backend engineer or a DevOps person first",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "backend-interview-questions-are-not-the-backend-lane",
        "Interview questions for a backend role are a hiring task, not a coding one",
        "interview questions for a senior backend role",
        "answer_clarification",
        "",
    ),
    # The remaining rows of the #1688 survey reach their wrong skill through
    # the metadata fold and a curation guard rather than through a name.
    # Those three already clarify; pinned so a later widening cannot quietly
    # turn an operational sentence into a workflow dispatch. The missing-index
    # row ("this query seq-scans 40M rows, what index") left this list when
    # #1692 gave it an owner: it is now an intervention dispatching to
    # `relational-db`, which still pins it away from `workflow-learning`. No
    # `forbidden_candidate` on any of the four below: the field also reads the
    # clarify's own shortlist, and a clarification that offers the skill among
    # its options is the correct outcome here, not the defect. The claim is
    # the ACTION.
    RoutingPrecisionCase(
        "node-memory-pressure-is-not-memory-curation",
        "A pod running out of memory is not a request to curate stored memories",
        "node memory climbs until the pod gets OOMKilled",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "compute-cost-estimate-is-not-the-observability-card",
        "Estimating GPU versus CPU spend is not an observability card",
        "estimate GPU vs CPU cost for this workload",
        "answer_clarification",
        "",
    ),
    # Negative controls for the phrasings added alongside the #1688 fix.
    # `plan` gained "make a plan" / "write a plan" / "write the plan", and a
    # multi-word trigger is scored as its separate tokens too: these two
    # sentences open with those verbs and ask for something else entirely.
    # `make` and `write` are held back in
    # `_WHOLE_PHRASE_ONLY_TRIGGER_TOKENS`; without that hold-back the first
    # of them moved from a data-analysis clarify to a `plan` one.
    RoutingPrecisionCase(
        "write-verb-does-not-reach-the-plan-engine",
        "Writing a migration is not writing a plan",
        "write a zero downtime migration to add a not-null column",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "make-verb-does-not-reach-the-plan-engine",
        "Making a pipeline faster is not making a plan",
        "make the ci pipeline faster",
        "answer_clarification",
        "",
        "plan",
    ),
    # `frontend` gained the locative forms "in/on/to the frontend", which say
    # the work happens there. Naming the frontend as an organisational fact
    # does not.
    RoutingPrecisionCase(
        "frontend-team-remark-is-not-frontend-work",
        "Naming the frontend team is not asking for frontend work",
        "the frontend team is hiring two more people",
        "answer_clarification",
        "",
    ),
    # `deep-interview` traded its bare `interview` trigger for "interview me".
    # The bare word is every hiring loop, user study, and recorded
    # conversation in the language; the pinned positive form lives in
    # `ROUTING_INTERVENTION_CASES`.
    RoutingPrecisionCase(
        "recorded-interview-is-not-the-interview-lane",
        "A recorded interview is not a request to be interviewed",
        "we recorded a podcast interview with the founder last week",
        "answer_clarification",
        "",
    ),
    # #1689 reached three shipped skills that their own phrasings could not.
    # Each new signal is built from an everyday word, so each gets the sense
    # that is not a request.
    #
    # `inference-serving` fires on a serving verb plus a model noun with the
    # model on the object side. `serve` has two other lives: static content,
    # and people.
    RoutingPrecisionCase(
        "serving-static-assets-is-not-model-serving",
        "A CDN serving assets is not a model being served",
        "the CDN should serve static assets from the edge",
        "answer_clarification",
        "",
        "inference-serving",
    ),
    RoutingPrecisionCase(
        "serving-customers-is-not-model-serving",
        "Choosing a model to serve people is not deploying one",
        "which model should we use to serve our support customers",
        "answer_clarification",
        "",
        "inference-serving",
    ),
    # `refactor-plan` fires on split vocabulary plus a unit of software. The
    # vocabulary alone is about anything that comes apart.
    RoutingPrecisionCase(
        "breaking-up-a-crowd-is-not-a-refactor",
        "Something broken up that is not code is not a refactor",
        "the crowd was broken up by police",
        "answer_directly",
        "direct_answer",
        "refactor-plan",
    ),
    # Shortlist-first follow-up: the negative half of each canonical request and
    # narrowed guard. Every sentence here is written for the rule, not taken
    # from a tuning probe.
    RoutingPrecisionCase(
        "review-as-a-noun-is-not-a-code-review",
        "A review on an agenda names a review; it does not ask for one",
        "the review of our hiring changes is on the agenda",
        "answer_clarification",
        "",
    ),
    # Hermes' kanban dispatcher opens every worker, the review lane's included,
    # with this literal prompt and loads its own `sdlc-review` for a review
    # card. The words name a board task and no diff, so the route asks and
    # never offers `code-review` as the workflow.
    #
    # `answer_clarification` is what the router does with this prompt today,
    # not the goal. The prompt is host-written, and a change that teaches the
    # router to leave host-written turns alone may route nothing here and move
    # the expected action. The forbidden candidate is the half that must
    # survive that move.
    RoutingPrecisionCase(
        "kanban-worker-prompt-is-not-a-code-review",
        "The dispatcher's kanban worker prompt asks for no code review",
        "work kanban task t_1a2b3c4d",
        "answer_clarification",
        "",
        "code-review",
    ),
    RoutingPrecisionCase(
        "a-building-inspection-is-not-a-build-failure",
        "A failing building inspection has no code context",
        "the office build is failing its inspection",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "a-question-about-a-past-deploy-is-not-a-deploy",
        "A question about a past deploy is not a deploy command",
        "who approved the deploy to production last week?",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "a-closed-github-bug-is-not-a-new-filing",
        "A bug already filed is not a request to file one",
        "the bug I filed on GitHub last week got closed",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "fixing-a-schedule-is-not-a-code-edit",
        "A repair verb on a non-code object is not a code edit",
        "fix the dinner schedule for the week",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "a-style-guide-question-is-not-a-frontend-change",
        "A question about a style guide is not an appearance edit",
        "what style guide does the team use for the site?",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "an-office-setup-is-not-a-missing-tool",
        "`setup` alone is not a missing tool",
        "our home office setup needs a better chair",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "plan-before-a-plain-noun-is-not-an-invocation",
        "`plan` before a plain noun is a verb, not the plan skill",
        "plan meals for the week",
        "answer_clarification",
        "",
    ),
    # Everyday sentences from the re-review of the removed dispatch shapes:
    # a shape built from vocabulary dispatched each of these.
    RoutingPrecisionCase(
        "lint-roller-is-not-a-build-failure",
        "A broken lint roller is not a build",
        "my lint roller is broken again",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "promotion-to-production-manager-is-not-a-deploy",
        "Promoting a person is not a deploy",
        "promote Sarah to production manager",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "releasing-doves-is-not-a-release",
        "Releasing doves live is not a release",
        "release the doves live at the wedding",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "app-icon-color-on-a-phone-is-not-frontend",
        "A phone's app icon color is not a UI change to build",
        "change the color of the app icon on my phone",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "an-accountants-commits-are-not-a-code-review",
        "Commits to a ledger are not a change set to review",
        "look over the commits my accountant made to the ledger",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "an-edit-noun-in-a-question-is-not-a-code-edit",
        "`change` as a noun in a question is not an edit command",
        "who approved the change to the settings button last sprint?",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "a-check-on-a-deck-is-not-a-materials-request",
        "A check verb on a document is not a request to produce one",
        "ensure the quarterly deck is uploaded to the shared drive",
        "answer_clarification",
        "",
    ),
    # Dispatch evidence. Each sentence below dispatched on origin before the
    # gate: everyday words that are also trigger tokens, a context-only guard,
    # or a guard whose object vocabulary was wider than code. Each now asks.
    # No `forbidden_candidate` where the scored leader stays the candidate --
    # that field reads `route.candidate_skill`, and the claim is the ACTION.
    RoutingPrecisionCase(
        "last-time-is-not-a-live-lookup",
        "`what` plus `time` does not make a past decision a live-information lookup",
        "what did we pick last time for the cache layer?",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "review-ran-long-is-not-a-code-review",
        "A meeting called a review is not a request for one",
        "the design review ran long last time",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "slide-title-edit-is-not-a-code-edit",
        "An imperative on a slide title is not a one-cycle code edit",
        "make the slide title shorter",
        "answer_clarification",
        "",
        "ultrawork",
    ),
    RoutingPrecisionCase(
        "memo-style-edit-is-not-a-code-edit",
        "An imperative on a memo's style is not a one-cycle code edit",
        "update the style of this memo",
        "answer_clarification",
        "",
        "ultrawork",
    ),
    RoutingPrecisionCase(
        "recurring-themes-are-not-a-schedule",
        "`recurring` describing themes does not ask for a scheduled job",
        "summarize the recurring themes in these support tickets",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "report-layout-question-is-not-feedback-triage",
        "`users` plus `report` is not a feedback report",
        "our users keep asking about the new report layout",
        "answer_clarification",
        "",
        "feedback-triage",
    ),
    # Shortlist-first fast paths. Each of these dispatched on origin through a
    # fast path or a bare-name invocation that fired on a word used in passing.
    RoutingPrecisionCase(
        "plan-as-an-object-is-not-an-invocation",
        "A sentence that ends on the word plan does not invoke it",
        "tell the team about the plan",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "remember-this-morning-is-not-a-memory-capture",
        "\"remember this morning\" recalls a time; nothing is asked to be kept",
        "remember this morning the train was late",
        "answer_directly",
        "direct_answer",
    ),
    # The negative half of `playwright-task-reaches-browser-operator`: the
    # same trigger phrase inside a question about the tool is not a request
    # to operate a page.
    RoutingPrecisionCase(
        "playwright-task-cost-question-is-not-a-browser-run",
        "A question about what a Playwright task costs does not start a browser run",
        "what does a playwright task cost in CI minutes?",
        "answer_directly",
        "direct_answer",
        "browser-operator",
    ),
    # A cadence phrase is `automation-blueprint`'s own trigger, and it used to
    # dispatch on it alone. In a report it says when something happens, not
    # what to schedule (#1892). Each opens on a subject after the cadence; the
    # positive half is `cadence-request-still-dispatches-automation`. The
    # candidate stays `automation-blueprint` (the route asks with it first),
    # so no forbidden candidate.
    RoutingPrecisionCase(
        "cadence-commute-report-is-not-a-schedule",
        "A daily habit told as a report does not open a scheduled blueprint",
        "every day the train to work is late",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "cadence-neighbor-dog-report-is-not-a-schedule",
        "What a neighbor's dog does every morning is not a scheduled job",
        "every morning my neighbor's dog barks at the mail carrier",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "cadence-lunch-habit-is-not-a-schedule",
        "Where we eat every day is not a recurring workflow",
        "every day we eat lunch at the same noodle shop",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "cadence-sunlight-report-is-not-a-schedule",
        "The morning light on a desk is not a morning digest",
        "every morning the sun hits my desk around nine",
        "answer_clarification",
        "",
    ),
    # A modal said of a person is advice or narration, not a schedule: the
    # directive-modal reading counts only on a noun-phrase subject.
    RoutingPrecisionCase(
        "cadence-self-advice-modal-is-not-a-schedule",
        "Advice to oneself with a modal is not a scheduled job",
        "every morning I should really drink less coffee, haha",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "cadence-obligation-narration-is-not-a-schedule",
        "A daily obligation told about ourselves is not a scheduled job",
        "every day we have to walk past that awful construction site",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "cadence-epistemic-modal-is-not-a-schedule",
        "An epistemic `must` about other people is not a scheduled job",
        "every morning they must think I'm crazy for jogging in the rain",
        "answer_clarification",
        "",
    ),
    # A modal past a subordinator or a reporting verb belongs to the embedded
    # clause, not to the thing the main clause is about (#1893 re-review).
    # The first three are the review's; the last two share the shape.
    RoutingPrecisionCase(
        "cadence-modal-after-complementizer-is-not-a-schedule",
        "A modal inside a `that` clause belongs to that clause",
        "every morning the team notices that karen should call the client",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "cadence-modal-after-reporting-verb-is-not-a-schedule",
        "A modal in what someone says is not a directive about the subject",
        "every day the manager says someone must fix the printer",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "cadence-modal-after-until-is-not-a-schedule",
        "A modal in an `until` clause is not a scheduled job",
        "every morning the office is quiet until someone must leave early",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "cadence-modal-after-thinks-is-not-a-schedule",
        "A modal in what someone thinks is not a scheduled job",
        "every morning the barista thinks the espresso machine should be replaced",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "cadence-modal-after-because-is-not-a-schedule",
        "A modal in a `because` clause is not a scheduled job",
        "every day the hallway smells of paint because the landlord must repaint it",
        "answer_clarification",
        "",
    ),
    # `fix` plus a product noun and a defect noun made the feedback guard read
    # a command as a customer report (#1892). None of these is code and none
    # hands over a report; the positive halves are
    # `commanded-payment-crash-fix-asks-with-coding-first` and
    # `checkout-crash-report-still-triages`.
    RoutingPrecisionCase(
        "fix-shopping-cart-wheel-is-not-feedback-triage",
        "Fixing a broken cart wheel is not a product-feedback report",
        "fix the broken wheel on my shopping cart",
        "answer_clarification",
        "",
        "feedback-triage",
    ),
    RoutingPrecisionCase(
        "fix-gym-subscription-is-not-feedback-triage",
        "Sorting out a gym subscription is not a product-feedback report",
        "fix the problem with my gym subscription renewal",
        "answer_clarification",
        "",
        "feedback-triage",
    ),
    RoutingPrecisionCase(
        "fix-crash-barrier-is-not-feedback-triage",
        "A crash barrier outside an office is not a crash report",
        "fix the crash barrier outside the payment office",
        "answer_clarification",
        "",
        "feedback-triage",
    ),
    RoutingPrecisionCase(
        "fix-garage-cart-latch-is-not-feedback-triage",
        "A broken latch on a garage cart is not a product-feedback report",
        "fix the broken latch on the cart in the garage",
        "answer_clarification",
        "",
        "feedback-triage",
    ),
    # Skill-reach negative controls (`omh demo skill-reach`). Each skill below
    # had no negative control entering its territory; each sentence uses its
    # vocabulary in an unrelated sense -- a Jev skill through a person named
    # Jev -- and must not reach it.
    RoutingPrecisionCase(
        "courtroom-adversarial-is-not-adversarial-consensus",
        "Adversarial in a courtroom is not an adversarial plan review",
        "what does adversarial mean in a courtroom",
        "answer_directly",
        "direct_answer",
        "adversarial-consensus",
    ),
    RoutingPrecisionCase(
        "cancel-culture-is-not-cancel",
        "Cancel culture is not a request to cancel a workflow",
        "what does cancel culture mean",
        "answer_directly",
        "direct_answer",
        "cancel",
    ),
    RoutingPrecisionCase(
        "song-context-is-not-project-context",
        "The context of a song is not project terminology",
        "explain the context of the song Hallelujah",
        "answer_directly",
        "direct_answer",
        "context",
    ),
    RoutingPrecisionCase(
        "phd-doctor-is-not-doctor",
        "A doctor of philosophy is not an OMH health check",
        "what does a doctor of philosophy degree involve",
        "answer_directly",
        "direct_answer",
        "doctor",
    ),
    RoutingPrecisionCase(
        "baseball-empty-catch-is-not-failure-audit",
        "An empty catch in baseball is not a swallowed exception",
        "what is an empty catch in baseball",
        "answer_directly",
        "direct_answer",
        "failure-signal-audit",
    ),
    RoutingPrecisionCase(
        "climbing-harness-is-not-session-inventory",
        "A climbing harness is not an agent harness inventory",
        "what is a harness in rock climbing",
        "answer_directly",
        "direct_answer",
        "harness-session-inventory",
    ),
    RoutingPrecisionCase(
        "classroom-learning-target-is-not-jit-learn",
        "A classroom learning target is not a just-in-time learning brief",
        "what is a learning target in a classroom lesson plan",
        "answer_directly",
        "direct_answer",
        "jit-learn",
    ),
    RoutingPrecisionCase(
        "youtube-history-is-not-media-input",
        "The history of YouTube is not a video to summarize",
        "what is the history of youtube",
        "answer_directly",
        "direct_answer",
        "media-input-operator",
    ),
    RoutingPrecisionCase(
        "city-budget-priorities-is-not-ops-review",
        "City budget priorities are not an operating review",
        "what are the priorities of the new city budget",
        "answer_directly",
        "direct_answer",
        "ops-review",
    ),
    RoutingPrecisionCase(
        "electronics-relay-is-not-device-readiness",
        "A relay in an electronics lesson is not a device safety gate",
        "what is a relay in electronics",
        "answer_directly",
        "direct_answer",
        "physical-device-readiness",
    ),
    RoutingPrecisionCase(
        "car-fuel-efficiency-is-not-run-efficiency",
        "A car's fuel efficiency is not a run-efficiency report",
        "what is the fuel efficiency of a Toyota Prius",
        "answer_directly",
        "direct_answer",
        "run-efficiency",
    ),
    RoutingPrecisionCase(
        "game-health-skill-is-not-skill-health",
        "A health skill in a video game is not skill portfolio health",
        "what is the health skill in the video game Skyrim",
        "answer_directly",
        "direct_answer",
        "skill-health",
    ),
    RoutingPrecisionCase(
        "person-named-jev-bus-route-is-not-jev-route",
        "A person named Jev taking a bus route is not a Jev workflow pick",
        "what bus route does Jev take to school",
        "answer_directly",
        "direct_answer",
        "jev-route",
    ),
    RoutingPrecisionCase(
        "person-named-jev-driving-safety-is-not-jev-action-check",
        "Whether a person named Jev may drive safely is not a Jev command check",
        "is it safe to let my cousin Jev drive my car without insurance",
        "answer_clarification",
        "",
        "jev-action-check",
    ),
    RoutingPrecisionCase(
        "person-named-jev-failed-test-is-not-jev-failure-triage",
        "A person named Jev failing a test is not Jev failure triage",
        "my friend Jev failed his driving test, is that a common failure",
        "answer_directly",
        "direct_answer",
        "jev-failure-triage",
    ),
    RoutingPrecisionCase(
        "person-named-jev-gate-review-is-not-jev-review-gate",
        "A person named Jev reviewing a gate design is not a Jev review gate",
        "my colleague Jev left a review on the gate design for the parking lot",
        "answer_clarification",
        "",
        "jev-review-gate",
    ),
    RoutingPrecisionCase(
        "person-named-jev-painting-done-is-not-jev-done-check",
        "A person named Jev saying a job is done is not a Jev done check",
        "my neighbor Jev says the fence painting is done",
        "answer_clarification",
        "",
        "jev-done-check",
    ),
    # Everyday-sense phrase controls (`EVERYDAY_SENSE_PHRASES` in
    # `routing/policy.py`). Each sentence carries a skill's own trigger phrase,
    # whole, in its ordinary English sense, and each dispatched that skill or
    # led a clarify with it. A clarify that leads with some other skill is
    # still a clarify; what these pin is that the named skill is not offered.
    RoutingPrecisionCase(
        "phone-alarm-silent-failure-is-not-failure-signal-audit",
        "A phone alarm that failed silently is not a code failure-signal audit",
        "my phone had a silent failure of the alarm this morning",
        "answer_clarification",
        "",
        "failure-signal-audit",
    ),
    RoutingPrecisionCase(
        "sled-dog-harness-sessions-is-not-session-inventory",
        "Harness sessions for a sled dog are not agent harness sessions",
        "how many harness sessions does a sled dog need before a race",
        "answer_directly",
        "direct_answer",
        "harness-session-inventory",
    ),
    RoutingPrecisionCase(
        "school-weekly-status-review-is-not-ops-review",
        "A weekly status review at a school parent meeting is not an ops review",
        "what is a weekly status review in a school parent meeting",
        "answer_clarification",
        "",
        "ops-review",
    ),
    RoutingPrecisionCase(
        "driveway-camera-gate-is-not-device-readiness",
        "A camera gate at a driveway is not a camera-gated device safety check",
        "is a camera gate at the driveway worth installing",
        "answer_clarification",
        "",
        "physical-device-readiness",
    ),
    RoutingPrecisionCase(
        "pianist-skill-health-is-not-skill-health",
        "A pianist keeping their skill health up is not the skill portfolio dashboard",
        "what are some habits that keep your skill health up as a pianist",
        "answer_clarification",
        "",
        "skill-health",
    ),
    RoutingPrecisionCase(
        "essay-independent-perspectives-is-not-adversarial-consensus",
        "Summarizing the perspectives in an essay is not an adversarial plan review",
        "summarize the independent perspectives in this essay about city parks",
        "answer_clarification",
        "",
        "adversarial-consensus",
    ),
    RoutingPrecisionCase(
        "vcr-media-input-is-not-media-input-operator",
        "The media input on a VCR is not a media input request",
        "what is media input on an old VCR",
        "answer_directly",
        "direct_answer",
        "media-input-operator",
    ),
    RoutingPrecisionCase(
        "gym-membership-cancel-is-not-cancel",
        "Cancelling a gym membership is not cancelling an OMH run",
        "how do I cancel my gym membership",
        "answer_directly",
        "direct_answer",
        "cancel",
    ),
    RoutingPrecisionCase(
        "leading-cancel-subscription-is-not-cancel",
        "A leading cancel aimed at a subscription is the verb, not the cancel skill",
        "cancel my netflix subscription",
        "answer_clarification",
        "",
        "cancel",
    ),
    RoutingPrecisionCase(
        "become-a-doctor-is-not-doctor",
        "Becoming a doctor is not the OMH install doctor",
        "how long does it take to become a doctor",
        "answer_directly",
        "direct_answer",
        "doctor",
    ),
    # `app-debugging` phrases are ordinary English beside anything that is not
    # code: a root cause of back pain, a phone update that was lost, flaky
    # snow, and a race run in the mud. Each holds a phrase or token the lane
    # triggers on.
    RoutingPrecisionCase(
        "root-cause-of-back-pain-is-not-app-debugging",
        "A root cause outside code is not an application debugging request",
        "the root cause of my back pain is bad posture",
        "answer_clarification",
        "",
        "app-debugging",
    ),
    RoutingPrecisionCase(
        "lost-phone-update-is-not-app-debugging",
        "A phone update that was lost is not a lost-update race",
        "my phone update is lost after the reset",
        "answer_clarification",
        "",
        "app-debugging",
    ),
    RoutingPrecisionCase(
        "flaky-snow-is-not-app-debugging",
        "Flaky snow is not a flaky test",
        "the snow is flaky today",
        "answer_clarification",
        "",
        "app-debugging",
    ),
    RoutingPrecisionCase(
        "marathon-race-condition-is-not-app-debugging",
        "The race conditions of a marathon are not a concurrency fault",
        "the race condition at the marathon was muddy and slow",
        "answer_directly",
        "direct_answer",
        "app-debugging",
    ),
    # `commit-pr-authoring` phrases outside a repository: a public-relations
    # description, a landlord's request, a speech, and a cover letter each carry a
    # phrase or token the lane triggers on.
    RoutingPrecisionCase(
        "press-release-pr-description-is-not-commit-pr-authoring",
        "A PR description for the press is public relations, not a pull request",
        "write a PR description of our product launch for the press release",
        "answer_clarification",
        "",
        "commit-pr-authoring",
    ),
    RoutingPrecisionCase(
        "landlord-pull-request-is-not-commit-pr-authoring",
        "Asking a landlord for more time is not a pull request",
        "write a message to my landlord about the pull request for more time",
        "answer_clarification",
        "",
        "commit-pr-authoring",
    ),
    RoutingPrecisionCase(
        "wedding-speech-message-is-not-commit-pr-authoring",
        "Committing to a speech message is not a commit message",
        "I need to commit to a message for my wedding speech",
        "answer_clarification",
        "",
        "commit-pr-authoring",
    ),
    RoutingPrecisionCase(
        "cover-letter-body-is-not-commit-pr-authoring",
        "The body of a cover letter is not a PR body",
        "draft the body of my cover letter",
        "answer_clarification",
        "",
        "commit-pr-authoring",
    ),
    # `git-workflow` phrases outside a repository: an angle bisected with a
    # compass, a car forced out of the snow, a conflict between two teams, and
    # apples picked at an orchard.
    RoutingPrecisionCase(
        "bisect-an-angle-is-not-git-workflow",
        "Bisecting an angle is geometry, not git bisect",
        "how do I bisect an angle with a compass",
        "answer_directly",
        "direct_answer",
        "git-workflow",
    ),
    RoutingPrecisionCase(
        "force-push-a-car-is-not-git-workflow",
        "Forcing a car out of the snow is not a force-push",
        "force push the car out of the snow",
        "answer_clarification",
        "",
        "git-workflow",
    ),
    RoutingPrecisionCase(
        "team-conflict-is-not-git-workflow",
        "A conflict between two teams is not a merge conflict",
        "we need to resolve the conflict between the two teams",
        "answer_clarification",
        "",
        "git-workflow",
    ),
    RoutingPrecisionCase(
        "orchard-cherry-pick-is-not-git-workflow",
        "Picking apples at an orchard is not a cherry-pick",
        "cherry-pick the best apples at the orchard",
        "answer_clarification",
        "",
        "git-workflow",
    ),
    # `relational-db` phrases outside a database: an index fund, a kitchen
    # table's partition, a dinner-party table setting, and a front-door lock.
    RoutingPrecisionCase(
        "index-fund-is-not-relational-db",
        "An index fund is investing, not a database index",
        "what index fund should I buy",
        "answer_clarification",
        "",
        "relational-db",
    ),
    RoutingPrecisionCase(
        "kitchen-table-partition-is-not-relational-db",
        "A kitchen table's partition is not table partitioning",
        "the table in the kitchen needs a new partition",
        "answer_clarification",
        "",
        "relational-db",
    ),
    RoutingPrecisionCase(
        "dinner-table-setting-is-not-relational-db",
        "Altering a dinner table setting is not ALTER TABLE",
        "alter the table setting for the dinner party",
        "answer_clarification",
        "",
        "relational-db",
    ),
    RoutingPrecisionCase(
        "front-door-lock-is-not-relational-db",
        "A broken front-door lock is not a table lock",
        "the lock on the front door is broken",
        "answer_clarification",
        "",
        "relational-db",
    ),
    # `security-event-response` phrases outside shipped code: a travel
    # advisory, a film's leaked ending, a driver's licence, and a recipe.
    RoutingPrecisionCase(
        "travel-security-advisory-is-not-security-event-response",
        "A travel security advisory is not a dependency advisory",
        "the travel security advisory for mexico",
        "answer_clarification",
        "",
        "security-event-response",
    ),
    RoutingPrecisionCase(
        "film-leaked-secret-is-not-security-event-response",
        "A film's leaked ending is not a leaked credential",
        "the leaked secret ending of the film spoiled it",
        "answer_clarification",
        "",
        "security-event-response",
    ),
    RoutingPrecisionCase(
        "drivers-license-is-not-security-event-response",
        "A driver's licence is not a dependency's license",
        "is my driver's license ok to use abroad",
        "answer_clarification",
        "",
        "security-event-response",
    ),
    RoutingPrecisionCase(
        "secret-recipe-is-not-security-event-response",
        "A secret recipe is not a committed secret",
        "my secret recipe for pancakes",
        "answer_clarification",
        "",
        "security-event-response",
    ),
    # `agent-instructions` words outside a repository: a travel agent's
    # instructions, a spy game, and a mouse cursor.
    RoutingPrecisionCase(
        "travel-agent-instructions-is-not-agent-instructions",
        "A travel agent's instructions are not an agent instruction file",
        "my travel agent sent instructions for the trip",
        "answer_clarification",
        "",
        "agent-instructions",
    ),
    RoutingPrecisionCase(
        "spy-game-agent-is-not-agent-instructions",
        "Instructions for a game's secret agent are not an agent instruction file",
        "write the instructions for the secret agent in our board game",
        "answer_clarification",
        "",
        "agent-instructions",
    ),
    RoutingPrecisionCase(
        "mouse-cursor-rules-is-not-agent-instructions",
        "A mouse cursor is not a Cursor rule",
        "the mouse cursor rules the screen in this game",
        "answer_clarification",
        "",
        "agent-instructions",
    ),
    # `release-cut` phrases outside shipping software: a band's release, a pet
    # canary, a political candidate, and a carpet. Watching a deploy that is
    # already out stays with `deploy-and-monitor`.
    RoutingPrecisionCase(
        "band-release-is-not-release-cut",
        "A band cutting a release is not a software release",
        "the band cut a release of their new album",
        "answer_clarification",
        "",
        "release-cut",
    ),
    RoutingPrecisionCase(
        "pet-canary-is-not-release-cut",
        "A pet canary is not a canary deploy",
        "my canary stopped singing",
        "answer_clarification",
        "",
        "release-cut",
    ),
    RoutingPrecisionCase(
        "release-candidate-for-mayor-is-not-release-cut",
        "A candidate for mayor is not a release candidate",
        "the release candidate for mayor spoke tonight",
        "answer_clarification",
        "",
        "release-cut",
    ),
    RoutingPrecisionCase(
        "rolled-back-carpet-is-not-release-cut",
        "Rolling back a carpet is not rolling back a deploy",
        "roll back the carpet in the hallway",
        "answer_clarification",
        "",
        "release-cut",
    ),
    RoutingPrecisionCase(
        "watching-a-deploy-is-not-release-cut",
        "Watching metrics after a deploy stays with deploy-and-monitor",
        "watch metrics after the deploy",
        "answer_clarification",
        "",
        "release-cut",
    ),
    RoutingPrecisionCase(
        "terraforming-a-planet-is-not-iac-change",
        "Terraforming a planet in a novel is not infrastructure",
        "we need to terraform mars in my sci-fi novel",
        "answer_clarification",
        "",
        "iac-change",
    ),
    RoutingPrecisionCase(
        "a-ships-helm-is-not-a-helm-chart",
        "A boat's helm is not Helm",
        "the boat drifted so take the helm",
        "answer_clarification",
        "",
        "iac-change",
    ),
    RoutingPrecisionCase(
        "a-flight-price-difference-is-not-a-cost-delta",
        "The price gap between two flights is not an infrastructure cost delta",
        "the cost delta between the two flights is 40 dollars",
        "answer_clarification",
        "",
        "iac-change",
    ),
    RoutingPrecisionCase(
        "tf-file-named-in-passing-is-not-iac-change",
        "A .tf file named in passing, beside none of the skill's words, adds nothing",
        "I saved my grocery list as main.tf, what should I cook tonight",
        "answer_clarification",
        "",
        "iac-change",
    ),
    RoutingPrecisionCase(
        "tf-file-open-in-the-editor-is-not-iac-change",
        "A .tf file open in the editor while asking about a laptop fan is not infrastructure work",
        "why is my laptop fan loud while main.tf is open in the editor",
        "answer_directly",
        "direct_answer",
        "iac-change",
    ),
    RoutingPrecisionCase(
        "family-lineage-is-not-data-lineage",
        "A family lineage is not a data lineage",
        "my family lineage goes back to scotland",
        "answer_clarification",
        "",
        "data-pipelines",
    ),
    RoutingPrecisionCase(
        "hiring-backfill-is-not-a-data-backfill",
        "Backfilling an open position on a team is not a data backfill",
        "we need to backfill the open position on the team",
        "answer_clarification",
        "",
        "data-pipelines",
    ),
    RoutingPrecisionCase(
        "calendar-duplicates-are-not-duplicate-events",
        "Duplicate calendar entries are not duplicate pipeline events",
        "I have duplicate events in my calendar",
        "answer_clarification",
        "",
        "data-pipelines",
    ),
    RoutingPrecisionCase(
        "memory-sync-stays-off-the-pipeline-lane",
        "Syncing the assistant's memory is not a data pipeline sync",
        "sync my memory with the latest notes",
        "answer_clarification",
        "",
        "data-pipelines",
    ),
    RoutingPrecisionCase(
        "email-wording-is-not-model-finetuning",
        "Fine-tuning an email's wording is not fine-tuning a model",
        "fine-tune the wording of this email",
        "answer_clarification",
        "",
        "model-finetuning",
    ),
    RoutingPrecisionCase(
        "hiring-process-is-not-model-finetuning",
        "Fine-tuning a hiring process is not fine-tuning a model",
        "we should fine tune our hiring process",
        "answer_clarification",
        "",
        "model-finetuning",
    ),
    RoutingPrecisionCase(
        "data-protection-officer-is-not-dpo-training",
        "A DPO who needs a privacy report is a data protection officer, not preference tuning",
        "our dpo needs a report on the new privacy rules",
        "answer_clarification",
        "",
        "model-finetuning",
    ),
    RoutingPrecisionCase(
        "lora-radio-is-not-a-lora-adapter",
        "A LoRa gateway for sensors is a radio, not a LoRA adapter",
        "set up a lora gateway for the soil sensors",
        "answer_clarification",
        "",
        "model-finetuning",
    ),
    RoutingPrecisionCase(
        "model-airplane-adapter-is-not-a-lora-adapter",
        "A model airplane's adapter is not a model adapter; the bare words are held back",
        "my model airplane needs a new adapter",
        "answer_clarification",
        "",
        "model-finetuning",
    ),
    RoutingPrecisionCase(
        "tuning-a-guitar-is-not-model-finetuning",
        "Tuning a guitar is not tuning a model; the bare word is held back",
        "tune the guitar before the show",
        "answer_clarification",
        "",
        "model-finetuning",
    ),
    RoutingPrecisionCase(
        "phone-store-app-is-not-a-store-release",
        "A phone's store app that will not open is not a store release",
        "the play store on my phone will not open",
        "answer_clarification",
        "",
        "mobile-release",
    ),
    RoutingPrecisionCase(
        "gift-card-is-not-a-store-release",
        "A Google Play gift card is not a Google Play release",
        "my google play gift card did not work",
        "answer_clarification",
        "",
        "mobile-release",
    ),
    RoutingPrecisionCase(
        "store-password-prompt-is-not-a-store-release",
        "An App Store password prompt is not an App Store submission",
        "the app store keeps asking for my password",
        "answer_clarification",
        "",
        "mobile-release",
    ),
    RoutingPrecisionCase(
        "server-keystore-is-not-android-signing",
        "A Kafka broker keystore is not an Android upload keystore",
        "rotate the keystore for the kafka brokers",
        "answer_clarification",
        "",
        "mobile-release",
    ),
    RoutingPrecisionCase(
        "red-sox-is-not-sox-testing",
        "The Red Sox are a baseball team, not SOX testing",
        "the red sox won last night",
        "answer_clarification",
        "",
        "internal-audit",
    ),
    RoutingPrecisionCase(
        "snacking-self-control-is-not-an-internal-control",
        "Self-control over snacking is not an internal control",
        "i have no internal control over my snacking",
        "answer_clarification",
        "",
        "internal-audit",
    ),
    RoutingPrecisionCase(
        "factory-quality-control-is-not-control-testing",
        "Quality control on an assembly line is not testing an internal control",
        "quality control testing on the assembly line found two defects",
        "answer_clarification",
        "",
        "internal-audit",
    ),
    RoutingPrecisionCase(
        "bridge-material-weakness-is-not-an-audit-finding",
        "A structural weakness in a bridge design is not a control deficiency",
        "the material weakness in this bridge design is the cable anchor",
        "answer_clarification",
        "",
        "internal-audit",
    ),
    RoutingPrecisionCase(
        "significant-improvement-is-not-a-significant-deficiency",
        "A significant performance improvement is not a significant deficiency; the bare words are held back",
        "this is a significant improvement in performance",
        "answer_clarification",
        "",
        "internal-audit",
    ),
    RoutingPrecisionCase(
        "knee-weakness-test-is-not-a-control-test",
        "A test showing a weak knee is not a control test; the bare words are held back",
        "the test showed a weakness in my left knee",
        "answer_clarification",
        "",
        "internal-audit",
    ),
    # The route question's decline predicate (#1817). Each of these builds a
    # question today; the first three are turns with nothing to decide, and the
    # last is an ordinary non-request whose four-candidate question the
    # predicate must keep -- an answerer saying `none` there is the answer the
    # shadow surface exists to measure.
    RoutingPrecisionCase(
        "route-question-declines-one-word-reply",
        "A one-word approval has nothing for the route question to decide",
        "lgtm",
        "answer_clarification",
        "",
        expected_route_question="one_word_reply",
    ),
    RoutingPrecisionCase(
        "route-question-declines-acknowledgement",
        "A thank-you has nothing for the route question to decide",
        "thanks, got it",
        "answer_directly",
        "direct_answer",
        expected_route_question="acknowledgement",
    ),
    RoutingPrecisionCase(
        "route-question-declines-no-candidate",
        "A question whose Choice offers only none has nothing to decide",
        "Apologize for being late.",
        "answer_clarification",
        "",
        expected_route_question="no_candidate",
    ),
    RoutingPrecisionCase(
        "route-question-keeps-multi-candidate-control",
        "A coding reminder with several candidates still has a question to ask",
        "remember to close the file handle in the finally block",
        "answer_clarification",
        "",
        expected_route_question=ROUTE_QUESTION_ASKED,
    ),
    # The agent-debug incident phrases (#1799) name an AI agent run: a human
    # agent, a database compaction, an app's bill, or a function that repeats
    # itself is not an agent run and must not dispatch to agent-debug. The three
    # human-agent sentences may still list agent-debug among the clarification
    # candidates (the scorer reads "agent" with "context" or "drift" that way on
    # main too), so they pin the route action only.
    RoutingPrecisionCase(
        "human-travel-agent-lost-track-stays-out-of-agent-debug",
        "A travel agent losing track of a booking is not an agent run",
        "the travel agent lost track of my booking",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "human-support-agent-drift-stays-out-of-agent-debug",
        "A support agent drifting from a call script is not goal drift in an agent run",
        "our support agent drifted from the script on the call",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "human-sales-agent-context-stays-out-of-agent-debug",
        "A sales agent losing the context of a deal is not context loss in an agent run",
        "the sales agent lost context of the deal",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "database-compaction-stays-out-of-agent-debug",
        "Rows lost after a database compaction are not agent context loss",
        "why did my database lose rows after compaction",
        "answer_clarification",
        "",
        "agent-debug",
    ),
    RoutingPrecisionCase(
        "app-api-cost-stays-out-of-agent-debug",
        "An application's API bill going up is not an agent run's unexpected cost",
        "the API costs of my app went up this month",
        "answer_directly",
        "direct_answer",
        "agent-debug",
    ),
    RoutingPrecisionCase(
        "recursive-function-repeat-stays-out-of-agent-debug",
        "A recursive function redoing a computation is application code, not repeated agent work",
        "my recursive function keeps redoing the same computation",
        "answer_clarification",
        "",
        "agent-debug",
    ),
    # Each sentence below carries one of the incident observables' words in a
    # human or non-agent sense -- "drifted from the goal", "keeps redoing
    # work", "keeps looping", "lost context after compaction". The fast path
    # once dispatched all six; the shipped phrases now need an agent-run
    # context (a tool call, turns, a compaction, "agent run"). Five of them
    # still name agent-debug among the clarification candidates, exactly as
    # they do on main without these phrases, so they pin the route action
    # only; the insurance sentence never names it and forbids it.
    RoutingPrecisionCase(
        "real-estate-agent-goal-drift-stays-out-of-agent-debug",
        "A real estate agent drifting from a negotiation goal is not goal drift in an agent run",
        "the real estate agent drifted from the goal of the negotiation",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "insurance-agent-redoing-work-stays-out-of-agent-debug",
        "An insurance agent redoing work on a claim is not repeated work in an agent run",
        "my insurance agent keeps redoing work on my claim",
        "answer_clarification",
        "",
        "agent-debug",
    ),
    RoutingPrecisionCase(
        "travel-agent-looping-menu-stays-out-of-agent-debug",
        "A travel agent looping a caller through a phone menu is not an agent run looping",
        "the travel agent keeps looping me back to the same menu",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "secret-agent-goal-drift-stays-out-of-agent-debug",
        "A film's secret agent drifting from the goal is not goal drift in an agent run",
        "the secret agent drifted from the goal in the movie",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "editor-compaction-context-stays-out-of-agent-debug",
        "An editor losing context after compaction is not an agent run's context loss",
        "my editor lost context after compaction",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "sqlite-vacuum-compaction-context-stays-out-of-agent-debug",
        "A SQLite vacuum compaction is a database operation, not an agent run's context loss",
        "the vacuum lost context after compaction in sqlite",
        "answer_clarification",
        "",
    ),
    # Quoted, relayed and linked workflow names (#2049). A `>` block-quote line,
    # a relay header line and a scheme URL carry someone else's words or an
    # address, never this person's request. The three invocation forms below
    # dispatched before the lexer masked their lines; the relay report and the
    # URL named the workflow as a candidate or a route hint.
    RoutingPrecisionCase(
        "block-quoted-invocation-does-not-dispatch",
        "A block-quoted invocation is quoted text, not a request to run it",
        "> $ulw-work fix the build",
        "answer_directly",
        "direct_answer",
        "ultrawork",
    ),
    RoutingPrecisionCase(
        "relay-report-header-does-not-name-the-workflow",
        "A relayed report that a workflow finished does not route to that workflow",
        "[REPORT] ralplan finished the rollout plan",
        "answer_directly",
        "direct_answer",
        "ralplan",
    ),
    RoutingPrecisionCase(
        "relay-arrow-header-invocation-does-not-dispatch",
        "An invocation relayed between two agents is addressed to someone else",
        "planner -> reviewer: $ulw-plan the rollout",
        "answer_directly",
        "direct_answer",
        "ralplan",
    ),
    RoutingPrecisionCase(
        "relay-sender-header-invocation-does-not-dispatch",
        "A named sender's relayed invocation is not this person's request",
        "Reviewer (agent-7) to lead: $ulw-work fix the build",
        "answer_directly",
        "direct_answer",
        "ultrawork",
    ),
    RoutingPrecisionCase(
        "workflow-name-in-url-path-stays-a-question",
        "A workflow name inside a URL path is part of an address, not a request",
        "what is https://example.com/docs/ulw-plan ?",
        "answer_directly",
        "direct_answer",
        "ralplan",
    ),
    # `ai-slop-cleaner` gained `ai slop`, `deslop review`, and the
    # multi-word `anti-slop pass`, `anti-slop review`, and `anti-slop sweep`.
    # These pin the senses of that vocabulary that ask for no cleanup: a
    # question about the word, a subagent's quoted report, and a plain review
    # request that belongs to `code-review`.
    RoutingPrecisionCase(
        "deslop-definition-question-stays-an-answer",
        "Asking what deslop means is a question, not a cleanup request",
        "what is deslop?",
        "answer_directly",
        "direct_answer",
        "ai-slop-cleaner",
    ),
    RoutingPrecisionCase(
        "relayed-deslop-report-does-not-dispatch",
        "A subagent's quoted report of a deslop pass is not a new request",
        'subagent report: "ran the anti-slop pass on src/auth and cleaned up the AI slop" - is that right?',
        "answer_clarification",
        "",
        "ai-slop-cleaner",
    ),
    RoutingPrecisionCase(
        "plain-pr-review-does-not-reach-slop-cleaner",
        "A plain review request does not credit the cleaner's review mode",
        "review this PR",
        "answer_clarification",
        "",
        "ai-slop-cleaner",
    ),
    RoutingPrecisionCase(
        "anti-virus-slop-log-does-not-name-slop-cleaner",
        "Anti-virus noise called slop in a log is not a cleanup request",
        "the anti-virus flagged slop in the logs",
        "answer_clarification",
        "",
        "ai-slop-cleaner",
    ),
    # The cleaner's code and prose nouns and cleanup verbs score only beside
    # its own slop words (`_SLOP_CLEANER_CONTEXT_TOKENS`); without one these
    # stay where they were and never name the cleaner.
    # `anti-slop` alone is not a cleaner trigger: as an adjective it names a
    # stance ("an anti-slop policy") or a quality ("the README is anti-slop
    # now") at least as often as a request, and every attempt to anchor the
    # bare word produced a new wrong dispatch. Only the request-shaped
    # phrases score, and `anti-slop` itself is held back as a token. None of
    # these may name the cleaner.
    RoutingPrecisionCase(
        "readme-anti-slop-policy-mention-does-not-name-slop-cleaner",
        "A README that mentions an anti-slop policy is not a cleanup request",
        "our README mentions an anti-slop policy",
        "answer_clarification",
        "",
        "ai-slop-cleaner",
    ),
    RoutingPrecisionCase(
        "docs-anti-slop-policy-question-does-not-name-slop-cleaner",
        "Asking whether an anti-slop policy is too strict is not a cleanup request",
        "is our docs anti-slop policy too strict?",
        "answer_clarification",
        "",
        "ai-slop-cleaner",
    ),
    # Stance talk about pull requests, changes, and code dispatched the
    # cleaner while the bare word was a trigger.
    RoutingPrecisionCase(
        "anti-slop-policy-for-pull-requests-does-not-name-slop-cleaner",
        "An anti-slop policy for pull requests is a stance, not a cleanup request",
        "our anti-slop policy for pull requests",
        "answer_clarification",
        "",
        "ai-slop-cleaner",
    ),
    RoutingPrecisionCase(
        "anti-slop-policy-changes-does-not-name-slop-cleaner",
        "An anti-slop policy that changes next week is news, not a cleanup request",
        "the anti-slop policy changes next week",
        "answer_clarification",
        "",
        "ai-slop-cleaner",
    ),
    RoutingPrecisionCase(
        "anti-slop-policy-for-code-does-not-name-slop-cleaner",
        "An anti-slop policy for code is a stance, not a cleanup request",
        "our anti-slop policy for code",
        "answer_clarification",
        "",
        "ai-slop-cleaner",
    ),
    RoutingPrecisionCase(
        "anti-slop-pull-request-check-question-does-not-name-slop-cleaner",
        "Asking whether an anti-slop pull request check is too strict is not a cleanup request",
        "is the anti-slop pull request check too strict?",
        "answer_clarification",
        "",
        "ai-slop-cleaner",
    ),
    RoutingPrecisionCase(
        "anti-slop-rule-in-pr-template-does-not-name-slop-cleaner",
        "An anti-slop rule added to a template is a report, not a cleanup request",
        "we added an anti-slop rule to the pull request template",
        "answer_clarification",
        "",
        "ai-slop-cleaner",
    ),
    RoutingPrecisionCase(
        "anti-slop-guidelines-question-does-not-name-slop-cleaner",
        "Anti-slop guidelines called too strict are a stance, not a cleanup request",
        "our anti-slop guidelines for pull requests are too strict",
        "answer_clarification",
        "",
        "ai-slop-cleaner",
    ),
    # A report of a finished anti-slop sweep is not a new request: `sweep` is
    # held back, so the phrase alone keeps it a question.
    RoutingPrecisionCase(
        "finished-anti-slop-sweep-report-stays-a-clarify",
        "Asking whether an anti-slop sweep finished does not start one",
        "did the anti-slop sweep finish?",
        "answer_clarification",
        "",
    ),
    # `anti-slop` as an adjective of quality or a topic, beside the README,
    # the docs, code, or a module.
    RoutingPrecisionCase(
        "readme-is-anti-slop-now-does-not-name-slop-cleaner",
        "A README described as anti-slop is a quality, not a cleanup request",
        "the README is anti-slop now",
        "answer_clarification",
        "",
        "ai-slop-cleaner",
    ),
    RoutingPrecisionCase(
        "update-anti-slop-docs-does-not-name-slop-cleaner",
        "Updating the anti-slop docs edits documentation, not slop",
        "update the anti-slop docs",
        "answer_clarification",
        "",
        "ai-slop-cleaner",
    ),
    RoutingPrecisionCase(
        "is-the-code-anti-slop-does-not-name-slop-cleaner",
        "Asking whether code is anti-slop is a question, not a cleanup request",
        "is the code anti-slop?",
        "answer_clarification",
        "",
        "ai-slop-cleaner",
    ),
    RoutingPrecisionCase(
        "module-is-anti-slop-now-does-not-name-slop-cleaner",
        "A module described as anti-slop is a quality, not a cleanup request",
        "the module is anti-slop now",
        "answer_clarification",
        "",
        "ai-slop-cleaner",
    ),
    # A mention of AI slop in the docs, and a slop word beside a stack of code
    # nouns, ask rather than dispatch: the context words count only beside a
    # whole appearance phrase, and at most two of them count. The cleaner may still
    # lead the question, so neither names a forbidden candidate.
    RoutingPrecisionCase(
        "docs-explain-ai-slop-stays-a-clarify",
        "Docs that explain AI slop are a mention, not a cleanup request",
        "the docs explain what ai slop is",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "slop-beside-stacked-code-nouns-stays-a-clarify",
        "A slop word beside a stack of code nouns does not run away into a dispatch",
        "pig slop: clean the files, simplify the code, tidy the docs, prune the module, dedupe the classes",
        "answer_clarification",
        "",
    ),
    # The cap itself: the context words now count only where a UI surface and
    # a code unit are both named, so frontend's phrase still competes; there a
    # list of code nouns would otherwise buy a dispatch past it, and counting
    # two keeps it a question.
    RoutingPrecisionCase(
        "layout-code-noun-list-stays-a-clarify",
        "Stacked code nouns beside layout code that looks like AI slop do not buy a dispatch",
        "the layout code looks like ai slop: the module, the files, the classes",
        "answer_clarification",
        "",
    ),
    # The context credit needs frontend's appearance phrase said whole, not
    # only a UI word beside a code unit: this report names a page and a module
    # but no appearance phrase, and it dispatched the cleaner (13) without
    # that condition.
    RoutingPrecisionCase(
        "ai-slop-on-settings-page-from-module-stays-a-clarify",
        "A report that AI slop on a page comes from a module is not a cleanup request",
        "the ai slop on the settings page comes from this module",
        "answer_clarification",
        "",
    ),
    # Frontend's appearance phrase on a non-UI target is not a restyle: song
    # lyrics, a tweet, and a profile bio called AI slop ask instead of
    # dispatching frontend (each did while the phrase counted anywhere).
    RoutingPrecisionCase(
        "song-lyrics-look-like-ai-slop-stays-a-clarify",
        "Song lyrics that look like AI slop are not a frontend restyle",
        "the song lyrics look like ai slop",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "tweet-screams-ai-slop-stays-a-clarify",
        "A tweet that screams AI slop is not a frontend restyle",
        "this tweet screams ai slop",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "linkedin-bio-looks-like-ai-slop-stays-a-clarify",
        "A profile bio that looks like AI slop is not a frontend restyle",
        "my linkedin bio looks like ai slop",
        "answer_clarification",
        "",
    ),
    # A chat message called AI slop is prose, not a UI restyle: it must not
    # dispatch frontend, and with no UI surface frontend's appearance phrase
    # earns no phrase credit. Frontend still leads the question (`polish` is
    # its word) and `message` is not a cleaner target, so the case claims
    # only that neither skill dispatches.
    RoutingPrecisionCase(
        "slack-message-feels-like-ai-slop-does-not-dispatch",
        "A Slack message that feels like AI slop asks rather than dispatching frontend",
        "this slack message feels like ai slop, polish it",
        "answer_clarification",
        "",
    ),
    # `ai slop` beside a cleanup verb but no path, code, docs, or prose target
    # is credited as the word `slop`, not as phrase evidence: these name the
    # cleaner in a question and each dispatched it while the phrase counted
    # whatever the target. `blog` is deliberately not a target (a feed someone
    # reads as often as text they wrote).
    RoutingPrecisionCase(
        "ai-slop-in-inbox-stays-a-clarify",
        "Cleaning AI slop out of an inbox names nothing the cleaner can clean",
        "clean up the ai slop in my inbox",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "ai-slop-in-youtube-recommendations-stays-a-clarify",
        "Cleaning AI slop out of video recommendations is not a code cleanup",
        "clean up the ai slop in my youtube recommendations",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "ai-slop-in-photo-library-stays-a-clarify",
        "Cleaning AI slop out of a photo library is not a code cleanup",
        "cleanup the ai slop in my photo library",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "ai-slop-comments-on-blog-stays-a-clarify",
        "Deleting AI slop comments on a blog is moderation, not a code cleanup",
        "delete the ai slop comments on my blog",
        "answer_clarification",
        "",
    ),
    # A bare appearance word is not frontend's appearance phrase: "looks
    # better", "looks interesting", "look the same" said about AI slop open no
    # context words for the cleaner, so its own `ai slop` phrase asks rather
    # than dispatching. Each of these dispatched while a token check opened
    # the context credit. The cleaner still leads the question, so none names
    # a forbidden candidate.
    RoutingPrecisionCase(
        "ai-slop-looks-better-now-stays-a-clarify",
        "AI slop that looks better now is a remark, not a cleanup request",
        "the ai slop looks better now",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "article-about-ai-slop-looks-interesting-stays-a-clarify",
        "An article about AI slop that looks interesting is a remark, not a cleanup request",
        "the article about ai slop looks interesting",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "ai-slop-looks-like-this-stays-a-clarify",
        "Describing what AI slop looks like is not a cleanup request",
        "ai slop looks like this: generic emails and blog posts",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "ai-slop-getting-better-question-stays-a-clarify",
        "Asking whether AI slop is getting better is a question, not a cleanup request",
        "is ai slop getting better? the posts all look the same",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "readme-about-ai-slop-looks-interesting-stays-a-clarify",
        "A README about AI slop that looks interesting is a remark, not a cleanup request",
        "the README about ai slop looks interesting",
        "answer_clarification",
        "",
    ),
    # An appearance word beside a code noun is not a slop request either:
    # without a whole appearance phrase the cleaner's context words earn
    # nothing.
    RoutingPrecisionCase(
        "function-looks-clean-does-not-name-slop-cleaner",
        "A function that looks clean is praise, not a cleanup request",
        "the new function looks clean",
        "answer_clarification",
        "",
        "ai-slop-cleaner",
    ),
    RoutingPrecisionCase(
        "module-load-failure-does-not-name-slop-cleaner",
        "A module that fails to load is not a cleanup request",
        "the module failed to load",
        "answer_directly",
        "direct_answer",
        "ai-slop-cleaner",
    ),
    RoutingPrecisionCase(
        "clean-it-up-later-does-not-name-slop-cleaner",
        "A deferred tidy-up with no slop word does not reach the cleaner",
        "clean it up later",
        "answer_clarification",
        "",
        "ai-slop-cleaner",
    ),
    RoutingPrecisionCase(
        "simplify-function-alone-does-not-name-slop-cleaner",
        "Simplifying a function without a slop word does not reach the cleaner",
        "simplify this function",
        "answer_clarification",
        "",
        "ai-slop-cleaner",
    ),
    # A loop on a timer is Hermes' native `/loop`, and a turn Hermes wrote from
    # its own `/plan` or `/loop` template carries the host's instruction for
    # itself; neither is OMH's to route. Before, the cadence sentences
    # dispatched the goal loop through the bare word "loop" (or "루프"), the
    # plan-mode turn dispatched the ops-observability card on its own rules,
    # and the wakeup fell back as a file lookup. The goal-shaped and
    # `./loop` forms beside these stay with the loop (intervention corpus).
    RoutingPrecisionCase(
        "loop-on-a-timer-is-native-loop",
        "A loop on a timer is Hermes' /loop, not the goal loop",
        "loop every 5 minutes and check whether CI is green",
        "answer_directly",
        "direct_answer",
        "loop",
    ),
    RoutingPrecisionCase(
        "korean-loop-on-a-timer-is-native-loop",
        "A Korean loop on a timer is Hermes' /loop, not the goal loop",
        "5분마다 CI가 초록색인지 확인하는 루프 돌려줘",
        "answer_directly",
        "direct_answer",
        "loop",
    ),
    RoutingPrecisionCase(
        "native-loop-command-syntax-is-not-the-goal-loop",
        "The native /loop interval syntax is not an OMH loop invocation",
        "/loop 5m check whether CI is green",
        "answer_directly",
        "direct_answer",
        "loop",
    ),
    RoutingPrecisionCase(
        "hermes-plan-mode-turn-is-host-owned",
        "Hermes' own /plan turn is not routed",
        "[/plan \u2014 plan mode]\n\nFor this turn, you are in PLAN MODE \u2014 planning only.\n\n"
        "- Do not implement code.\n- Do not edit project files except the plan markdown file itself.\n"
        "- Do not run mutating terminal commands, commit, push, or perform external\n  actions.\n\n"
        "Task to plan:\nadd a dark mode toggle to the settings page\n",
        "answer_directly",
        "direct_answer",
        "ops-observability-card",
    ),
    RoutingPrecisionCase(
        "hermes-loop-wakeup-turn-is-host-owned",
        "A Hermes /loop wakeup turn is not routed",
        "[/loop wakeup #3, every 5m]\nRecurring task: check whether CI is green on PR 42\n\n"
        "This is an automatic wakeup from the /loop the user set. Perform the task now against the "
        "CURRENT state. If the task is now complete, say so and end your reply with LOOP_COMPLETE "
        "on its own line \u2014 that stops the loop.",
        "answer_directly",
        "direct_answer",
        "loop",
    ),
    # The other turns Hermes writes for its own session commands, each opened
    # by its template's frame. Before, a `/goal` continuation dispatched OMH's
    # own goal loop into a permission-profile question (and, with a completion
    # contract, the wrapper read it as a catalog question), the goal-mode
    # kanban nudges dispatched the image-card skill, and the heartbeat,
    # `/learn`, and setup turns dispatched automation, memory, and toolbelt
    # skills.
    RoutingPrecisionCase(
        "hermes-goal-continuation-turn-is-host-owned",
        "A Hermes /goal continuation turn is not routed",
        "[Continuing toward your standing goal]\nGoal: ship the OMH loop docs, fix the failing CI on PR 42, "
        "and open a PR with the release notes\n\nCompletion contract:\nOutcome: docs merged\nVerify: CI green\n\n"
        "Continue working toward the outcome above. Take the next concrete step. Before claiming the goal is "
        "done, satisfy the Verification criterion and show the concrete evidence (command output, file "
        "contents, test result).",
        "answer_directly",
        "direct_answer",
        "loop",
    ),
    RoutingPrecisionCase(
        "hermes-goal-gate-failed-turn-is-host-owned",
        "A Hermes /goal turn after a failed quality gate is not routed",
        "[Continuing toward your standing goal \u2014 a quality gate failed]\nGoal: ship the OMH loop docs, fix "
        "the failing CI on PR 42, and open a PR with the release notes\n\nThe quality gate command below must "
        "pass before this goal can be declared done, and it just failed (attempt 1/3):\n  $ pytest -q\nExit code: 1",
        "answer_directly",
        "direct_answer",
        "loop",
    ),
    RoutingPrecisionCase(
        "hermes-kanban-goal-continuation-turn-is-host-owned",
        "A goal-mode kanban continuation turn is not routed",
        "[Continuing toward this kanban task \u2014 judge says it is not done yet]\nReason: tests still failing on "
        "the login flow\n\nTake the next concrete step toward completing the task. When the work is genuinely "
        "finished, call kanban_complete with a summary.",
        "answer_directly",
        "direct_answer",
        "img-summary",
    ),
    RoutingPrecisionCase(
        "hermes-kanban-goal-finalize-turn-is-host-owned",
        "A goal-mode kanban finalize turn is not routed",
        "[The work looks complete, but the task is still open]\nReason: the PR is open and CI is green\n\n"
        "If the task is genuinely done, call kanban_complete now with a short summary of what you did.",
        "answer_directly",
        "direct_answer",
        "img-summary",
    ),
    RoutingPrecisionCase(
        "hermes-heartbeat-turn-is-host-owned",
        "A Hermes /heartbeat turn is not routed",
        "[Heartbeat \u2014 recurring instruction, fires every 10m]\ncheck whether CI is green and summarize "
        "open PRs\n\nIf there is nothing meaningful to do or report for this instruction right now, reply "
        "briefly that nothing has changed and stop.",
        "answer_directly",
        "direct_answer",
        "automation-blueprint",
    ),
    RoutingPrecisionCase(
        "hermes-learn-turn-is-host-owned",
        "A Hermes /learn turn is not routed",
        "[/learn] The user wants you to learn a reusable skill from the request below, and save it.\n\n"
        "THE REQUEST:\nthe deploy workflow we just went through\n\nInventory every source the user named, "
        "then save the skill.",
        "answer_directly",
        "direct_answer",
        "memory-new",
    ),
    RoutingPrecisionCase(
        "hermes-initiate-setup-turn-is-host-owned",
        "A Hermes /initiate-setup turn is not routed",
        "[/initiate-setup]\n\n---\nname: initiate-setup\ndescription: Run the first-run setup chat.\n---\n\n"
        "Guide the user through first-run setup: pick a model provider, connect accounts, and install plugins.",
        "answer_directly",
        "direct_answer",
        "toolbelt-readiness",
    ),
    # Hermes' `/blueprint` rewrites the turn to a seed that asks for the
    # blueprint's settings and then creates the cron job itself. Before, every
    # seed in the catalog dispatched a file, toolbelt or observability skill.
    RoutingPrecisionCase(
        "hermes-blueprint-seed-turn-is-host-owned",
        "A Hermes /blueprint seed turn is not routed",
        "Set up the 'Morning check-in' automation for me (automation blueprint 'morning-checkin'). A short daily "
        "check-in with your calendar.\n\nAsk me for each of these, one at a time, offering the default in brackets "
        "if I don't have a preference:\n- What time? (time) [default: 08:00]\n- Where to deliver? (deliver) "
        "[default: origin]\n\nOnce you have my answers, create the job by calling the cronjob tool with "
        "action='create'.",
        "answer_directly",
        "direct_answer",
        "toolbelt-readiness",
    ),
    # A messaging gateway puts its own material before the frame: a shared
    # session's sender prefix, a Discord trigger note, a reply pointer. Before,
    # each of these still routed (ultrawork for the plan, github-event-ops for
    # the goal). The native `/loop` interval syntax with hours and minutes is a
    # timer too, which the single-unit check missed.
    RoutingPrecisionCase(
        "hermes-plan-turn-behind-a-sender-prefix-is-host-owned",
        "A shared-session /plan turn behind its sender prefix is not routed",
        "[alice] [/plan \u2014 plan mode]\n\nFor this turn, you are in PLAN MODE \u2014 planning only.\n\n"
        "Task to plan:\nadd a dark mode toggle to the settings page\n",
        "answer_directly",
        "direct_answer",
        "ultrawork",
    ),
    RoutingPrecisionCase(
        "hermes-goal-turn-behind-a-discord-note-is-host-owned",
        "A /goal turn behind a Discord trigger note and sender prefix is not routed",
        "[Triggering message id: `1234` \u2014 use as `message_id` for reply/react/pin via the discord tools.]\n\n"
        "[alice] [Continuing toward your standing goal]\nGoal: ship the OMH loop docs, fix the failing CI on PR 42\n\n"
        "Continue working toward this goal. Take the next concrete step.",
        "answer_directly",
        "direct_answer",
        "github-event-ops",
    ),
    RoutingPrecisionCase(
        "hermes-plan-turn-behind-a-reply-pointer-is-host-owned",
        "A /plan turn behind a reply pointer is not routed",
        "[Replying to: \"can you plan it\"]\n\n[/plan \u2014 plan mode]\n\nFor this turn, you are in PLAN MODE "
        "\u2014 planning only.\n\nTask to plan:\nadd a dark mode toggle\n",
        "answer_directly",
        "direct_answer",
        "ultrawork",
    ),
    # On a person's turn the same material is not the request either: the
    # router reads only the person's own words. Before, a Discord trigger note
    # made a concept question dispatch web-research, and a reply quoting a
    # skill name turned a thank-you into the catalog picker. A reply's quoted
    # text is context, never the request.
    RoutingPrecisionCase(
        "concept-question-behind-a-discord-note-stays-direct",
        "A concept question behind a Discord trigger note stays a direct answer",
        "[Triggering message id: `1234` \u2014 use as `message_id` for reply/react/pin via the discord tools.]\n\n"
        "what is a web crawler",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "thanks-under-a-reply-quoting-a-skill-stays-direct",
        "A thank-you under a reply that quotes a skill request stays a direct answer",
        "[Replying to: \"use omh-apple-design to review our iOS checkout\"]\n\nthanks, got it",
        "answer_directly",
        "direct_answer",
    ),
    RoutingPrecisionCase(
        "native-loop-compound-interval-is-not-the-goal-loop",
        "The native /loop syntax with a compound interval is not the goal loop",
        "/loop 1h30m check whether the nightly build passed",
        "answer_directly",
        "direct_answer",
        "loop",
    ),
    # A timer spelled with a short unit is a timer, and a code loop on a timer
    # is a question about that loop; both were the goal loop before.
    RoutingPrecisionCase(
        "loop-every-5-min-is-native-loop",
        "A loop on a timer written with a short unit is Hermes' /loop",
        "loop every 5 min check CI",
        "answer_directly",
        "direct_answer",
        "loop",
    ),
    RoutingPrecisionCase(
        "bash-while-loop-on-a-timer-is-not-the-goal-loop",
        "A bash while loop on a timer is a code question, not the goal loop",
        "write a while loop in bash that checks a URL every 10 seconds",
        "answer_directly",
        "direct_answer",
        "loop",
    ),
    # A check asked of a loop on a timer is Hermes' `/loop` even when the thing
    # checked is itself a code loop; before, it dispatched the goal loop, and
    # for one review round it was answered as a question about that code.
    RoutingPrecisionCase(
        "timed-loop-checking-a-code-loop-is-native-loop",
        "A timed loop that checks an event loop is Hermes' /loop",
        "loop every 5 minutes and check whether the event loop lag is under 100ms",
        "answer_directly",
        "direct_answer",
        "loop",
    ),
    # Typed with its cadence, `/loop` is Hermes' command whatever its prompt
    # mentions; before, OMH's skill name in the prompt dispatched the goal loop.
    RoutingPrecisionCase(
        "typed-native-loop-naming-ulw-loop-is-native-loop",
        "A typed /loop with a cadence stays Hermes' command when its prompt names ulw-loop",
        "/loop 5m check whether ulw-loop finished",
        "answer_directly",
        "direct_answer",
        "loop",
    ),
    # Requests a skill Hermes bundles owns (`llm-wiki`, `architecture-diagram`,
    # `simplify-code`, `pdf`, `docx`, `xlsx`), and a review of what sits on a
    # work-board card. OMH cannot dispatch a bundled skill, so the turn asks
    # instead of handing the request to the OMH skill whose words it shares;
    # each OMH skill's body carries the `HermesSkillLine` naming its bundled
    # owner. `forbidden_candidate` also reads the clarify's shortlist, so it
    # is set only where the OMH skill leaves that shortlist too; elsewhere the
    # claim is that the turn asks instead of dispatching.
    RoutingPrecisionCase(
        "kanban-card-pr-review-is-not-an-image-card",
        "A PR linked on a kanban card asks for a review, not an image card",
        "review the PR linked on the kanban card",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "kanban-card-diff-review-is-not-an-image-card",
        "A diff on a kanban card asks for a review, not an image card",
        "please review the diff on kanban card t_123",
        "answer_clarification",
        "",
    ),
    # Nor is the pre-spend card, which dispatched the image card before.
    RoutingPrecisionCase(
        "pre-spend-card-review-is-not-an-image-card",
        "Reviewing the pre-spend card before confirming is not an image card",
        "please review the pre-spend card before I confirm",
        "answer_clarification",
        "",
        "img-summary",
    ),
    RoutingPrecisionCase(
        "aws-architecture-svg-is-not-codebase-uml",
        "An infrastructure diagram drawn from a description is the bundled architecture-diagram skill's job",
        "draw an architecture diagram of our AWS setup as an SVG",
        "answer_clarification",
        "",
        "codebase-uml",
    ),
    RoutingPrecisionCase(
        "cloud-architecture-diagram-is-not-codebase-uml",
        "A cloud network diagram with no code to read is not a codebase picture",
        "draw a cloud architecture diagram with VPC, subnets and RDS",
        "answer_clarification",
        "",
        "codebase-uml",
    ),
    RoutingPrecisionCase(
        "llm-wiki-ingest-is-not-research-department",
        "Ingesting an article into an LLM wiki is the bundled llm-wiki skill's job",
        "use the llm-wiki skill to ingest this article into my knowledge base",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "llm-wiki-build-is-not-wiki-blueprint",
        "Building an LLM wiki from papers is the bundled llm-wiki skill's job",
        "build an llm wiki from these papers",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "llm-wiki-of-notes-is-not-wiki-blueprint",
        "Building a wiki of notes with llm-wiki is the bundled llm-wiki skill's job",
        "use llm-wiki to build a wiki of my notes",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "notes-into-llm-wiki-is-not-wiki-blueprint",
        "Organizing notes into an LLM wiki is the bundled llm-wiki skill's job",
        "organize my notes into an llm wiki",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "llm-wiki-in-markdown-vault-is-not-wiki-blueprint",
        "An LLM wiki in a markdown vault is the bundled llm-wiki skill's job",
        "llm wiki in my markdown vault",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "llm-wiki-knowledge-base-from-pdfs-is-not-research-department",
        "An LLM-wiki style knowledge base built from PDFs is the bundled llm-wiki skill's job",
        "Create an LLM-wiki style knowledge base from these PDFs",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "cloud-diagram-for-an-idea-is-not-codebase-uml",
        "A cloud architecture diagram for an idea has no code to read the structure from",
        "Draw a cloud architecture diagram for my startup idea",
        "answer_clarification",
        "",
        "codebase-uml",
    ),
    # The same boundaries said in Korean, where the weak-evidence check that
    # turns an English guard-only match into a question does not apply. On
    # main every ops case dispatched the card: a bare 토큰 or 비용 trigger, or
    # the guard reading 알려줘 as a status request, took an auth token, the
    # cost of a call, or code that touches token usage for a usage report. The
    # Korean usage phrases that replace the triggers read whole words and count
    # only under a final predicate that asks to see the usage, so a request
    # for code or for less usage does not reach the card. "LLM 위키", spaced or
    # not, dispatched the wiki blueprint or asked with it leading, and where the
    # blueprint did not claim it the greenfield interview dispatched on
    # "만들어줘" ("이 문서들 LLM 위키로 만들어줘"); both now stand down on an LLM
    # wiki. The diagram cases hold the Korean diagram fix to the
    # English boundary: data visualization, and a cloud diagram with no code
    # to read, bare or with a particle, are not a codebase picture.
    RoutingPrecisionCase(
        "korean-auth-token-storage-is-not-ops-observability",
        "Changing how an auth token is stored is not a token-usage report",
        "토큰 저장 방식 바꿔줘",
        "answer_clarification",
        "",
        "ops-observability-card",
    ),
    RoutingPrecisionCase(
        "korean-api-call-cost-code-is-not-ops-observability",
        "Writing code that lowers an API call's cost is not a cost report",
        "이 API 호출 비용 줄이는 코드 짜줘",
        "answer_clarification",
        "",
        "ops-observability-card",
    ),
    RoutingPrecisionCase(
        "korean-auth-token-question-is-not-ops-observability",
        "Asking how a token is stored is not a usage report",
        "토큰 저장 방식 알려줘",
        "answer_clarification",
        "",
        "ops-observability-card",
    ),
    RoutingPrecisionCase(
        "korean-token-consumer-code-is-not-ops-observability",
        "Writing a token consumer is code, not a usage report",
        "토큰 소비자 코드 짜줘",
        "answer_clarification",
        "",
        "ops-observability-card",
    ),
    RoutingPrecisionCase(
        "korean-token-usage-limit-feature-is-not-ops-observability",
        "Implementing a token-usage limit is code, not a usage report",
        "토큰 사용량 제한 기능 구현해줘",
        "answer_clarification",
        "",
        "ops-observability-card",
    ),
    RoutingPrecisionCase(
        "korean-token-usage-limit-middleware-is-not-ops-observability",
        "Writing middleware that limits token usage is code, not a usage report",
        "토큰 사용량 제한하는 미들웨어 짜줘",
        "answer_clarification",
        "",
        "ops-observability-card",
    ),
    RoutingPrecisionCase(
        "korean-fewer-tokens-prompt-is-not-ops-observability",
        "Rewriting a prompt to burn fewer tokens asks for less usage, not a report of it",
        "토큰 소모 줄이는 프롬프트로 바꿔줘",
        "answer_clarification",
        "",
        "ops-observability-card",
    ),
    RoutingPrecisionCase(
        "korean-kafka-token-consumption-logic-is-not-ops-observability",
        "Implementing Kafka token-consumption logic is code, not a usage report",
        "카프카 토큰 소비 로직 구현해줘",
        "answer_clarification",
        "",
        "ops-observability-card",
    ),
    RoutingPrecisionCase(
        "korean-kafka-token-consumer-group-is-not-ops-observability",
        "A token consumer group is not token consumption: 소비자 is a longer word than 소비",
        "카프카 토큰 소비자 그룹 늘려줘",
        "answer_clarification",
        "",
        "ops-observability-card",
    ),
    RoutingPrecisionCase(
        "korean-kafka-token-consumer-count-is-not-ops-observability",
        "Asking for the token-consumer count is not token consumption, even under a report predicate",
        "카프카 토큰 소비자 수 알려줘",
        "answer_clarification",
        "",
        "ops-observability-card",
    ),
    # A usage phrase counts only under a final predicate that asks to see the
    # usage; these end in work on code, whatever comes earlier ("보여주는").
    RoutingPrecisionCase(
        "korean-token-usage-parsing-is-not-ops-observability",
        "Parsing token usage is code, not a usage report",
        "토큰 사용량 파싱해줘",
        "answer_clarification",
        "",
        "ops-observability-card",
    ),
    RoutingPrecisionCase(
        "korean-token-usage-test-is-not-ops-observability",
        "Writing a token-usage test is code, not a usage report",
        "토큰 사용량 테스트 작성해줘",
        "answer_clarification",
        "",
        "ops-observability-card",
    ),
    RoutingPrecisionCase(
        "korean-token-usage-field-is-not-ops-observability",
        "A report word before the final predicate does not make adding a field a usage report",
        "토큰 사용량 보여주는 필드 추가해줘",
        "answer_clarification",
        "",
        "ops-observability-card",
    ),
    # A word that only starts like 해 or 하 is a predicate of its own, not the
    # spaced ending of the word before it.
    RoutingPrecisionCase(
        "korean-token-usage-monitoring-off-is-not-ops-observability",
        "Turning token-usage monitoring off is not a usage report",
        "토큰 사용량 모니터링 해제해줘",
        "answer_clarification",
        "",
        "ops-observability-card",
    ),
    RoutingPrecisionCase(
        "korean-dont-show-token-usage-is-not-ops-observability",
        "Asking not to show token usage is not a usage report",
        "토큰 사용량 보여달라고 하지마",
        "answer_clarification",
        "",
        "ops-observability-card",
    ),
    RoutingPrecisionCase(
        "korean-sales-data-visualization-is-not-codebase-uml",
        "Visualizing sales data is not a codebase diagram",
        "매출 데이터 시각화해줘",
        "answer_clarification",
        "",
        "codebase-uml",
    ),
    RoutingPrecisionCase(
        "korean-cloud-architecture-diagram-is-not-codebase-uml",
        "A Korean cloud architecture diagram has no code to read the structure from",
        "클라우드 아키텍처 다이어그램 그려줘",
        "answer_clarification",
        "",
        "codebase-uml",
    ),
    RoutingPrecisionCase(
        "korean-cloud-architecture-diagram-with-particle-is-not-codebase-uml",
        "A Korean cloud word with a particle attached still marks a diagram with no code to read",
        "클라우드의 아키텍처 다이어그램 그려줘",
        "answer_clarification",
        "",
        "codebase-uml",
    ),
    RoutingPrecisionCase(
        "korean-llm-wiki-build-is-not-wiki-blueprint",
        "Building an LLM wiki, said in Korean, is the bundled llm-wiki skill's job",
        "LLM 위키 만들어줘",
        "answer_clarification",
        "",
        "wiki",
    ),
    RoutingPrecisionCase(
        "korean-notes-into-llm-wiki-is-not-wiki-blueprint",
        "Organizing notes into an LLM wiki, said in Korean, is the bundled llm-wiki skill's job",
        "내 노트를 LLM 위키로 정리해줘",
        "answer_clarification",
        "",
        "wiki",
    ),
    RoutingPrecisionCase(
        "korean-unspaced-llm-wiki-build-is-not-wiki-blueprint",
        "An LLM wiki written without a space is still the bundled llm-wiki skill's job",
        "LLM위키 만들어줘",
        "answer_clarification",
        "",
        "wiki",
    ),
    RoutingPrecisionCase(
        "trello-card-review-is-not-an-image-card",
        "A Trello card is a work item, so reviewing it is not an image card",
        "Create a Trello card for the bug and review it",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "simplify-code-skill-is-not-slop-cleaner",
        "Naming the bundled simplify-code skill does not reach the slop cleaner",
        "use simplify-code on the auth module",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "simplify-code-last-commit-is-not-slop-cleaner",
        "Running simplify-code on a commit does not reach the slop cleaner",
        "run the simplify-code skill on my last commit",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "pdf-form-fill-is-not-materials-package",
        "Filling one PDF form is the bundled pdf skill's job",
        "fill out this pdf form",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "pdf-merge-does-not-dispatch-materials-package",
        "Merging two PDFs is a file operation, not a material plan",
        "merge these two pdf files",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "xlsx-cell-edit-does-not-dispatch-materials-package",
        "Adding a column to a workbook is a file operation, not a material plan",
        "open budget.xlsx and add a totals column",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "docx-text-edit-does-not-dispatch-materials-package",
        "Editing a Word document's text is a file operation, not a material plan",
        "edit the text in contract.docx",
        "answer_clarification",
        "",
    ),
    # `data-share-review`, added with the skill. "pii", "redact", "mask" and
    # "share" are held back as bare tokens; a legal question or a system change
    # withdraws the skill's phrases; and a finished state ("pseudonymized") is
    # not a phrase.
    RoutingPrecisionCase(
        "pii-acronym-question-is-not-a-data-share-review",
        "Asking what PII stands for is a definition, not a file to clean",
        "what does pii stand for",
        "answer_directly",
        "direct_answer",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "gdpr-pseudonymization-question-is-not-a-data-share-review",
        "Whether GDPR requires pseudonymization is a legal question, not a file to clean",
        "does gdpr require us to pseudonymize customer data",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "gdpr-compliance-of-a-redaction-policy-is-not-a-data-share-review",
        "Whether a redaction policy is GDPR compliant is a legal question, not a file to clean",
        "our privacy policy says we redact pii from logs, is that gdpr compliant",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "logging-pipeline-change-is-not-a-data-share-review",
        "Changing a logging pipeline is an engineering change, not a file about to leave",
        "strip pii from our logging pipeline going forward",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    # No `forbidden_candidate`: the shortlist may still list the skill below
    # `data-analysis`, which leads; the claim is that the finished state does
    # not dispatch it.
    RoutingPrecisionCase(
        "analysis-of-a-pseudonymized-dataset-is-not-a-data-share-review",
        "Analysing a dataset someone already pseudonymized is not a file to clean",
        "run churn analysis on the pseudonymized dataset",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "redacted-film-cut-is-not-a-data-share-review",
        "A redacted cut of a film is not a file to clean",
        "the movie is a redacted version of the original cut",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "sharing-a-doc-with-the-team-is-not-a-data-share-review",
        "Sharing a doc inside the team is not data leaving it",
        "share this doc with my team",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "photo-background-mask-is-not-a-data-share-review",
        "Masking a photo's background is not masking personal data",
        "mask the background in this photo",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    # `data-share-review`, review round one: each of these dispatched it while
    # a phrase counted anywhere. Its phrases also name messages, code, Hermes
    # settings, storage scans, legal questions, definitions, and account
    # cleanup; none of these has a file-shaped carrier leaving the team. The
    # cases without `forbidden_candidate` keep the skill lower in the
    # shortlist, which is allowed; the claim is that it does not dispatch.
    RoutingPrecisionCase(
        "comment-on-pr-42-that-we-should-pseudonymize-user-ids-is-not-a-data-share-review",
        "A pull-request comment acts on the PR, not on a file leaving",
        "comment on PR 42 that we should pseudonymize user ids",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "send-a-slack-message-to-the-data-team-asking-who-owns-pii-redaction-is-not-a-data-share-review",
        "A Slack message about redaction is a message, not a file leaving",
        "send a slack message to the data team asking who owns pii redaction",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "post-in-privacy-on-slack-that-the-pseudonymization-job-finished-is-not-a-data-share-review",
        "A Slack post about a finished job is a message, not a file leaving",
        "post in #privacy on slack that the pseudonymization job finished",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "email-the-vendor-that-we-will-de-identify-the-dataset-by-friday-is-not-a-data-share-review",
        "Emailing a vendor acts on the email, not on the dataset",
        "email the vendor that we will de-identify the dataset by friday",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "in-zendesk-close-tickets-that-mention-pii-redaction-is-not-a-data-share-review",
        "Closing Zendesk tickets acts on the tickets, not on a file leaving",
        "in zendesk, close tickets that mention pii redaction",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "reply-to-the-zendesk-ticket-asking-us-to-remove-personal-data-is-not-a-data-share-review",
        "Replying to a deletion request acts on the ticket, not on a file leaving",
        "reply to the zendesk ticket asking us to remove personal data",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "forward-the-customer-s-request-to-remove-personal-data-to-the-privacy-is-not-a-data-share-review",
        "Forwarding a deletion request is a message, not a file leaving",
        "forward the customer's request to remove personal data to the privacy team by email",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "write-a-python-function-to-redact-pii-from-strings-is-not-a-data-share-review",
        "Writing a redaction function is code, not a file leaving",
        "write a python function to redact pii from strings",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "add-pii-redaction-to-the-chatbot-s-responses-is-not-a-data-share-review",
        "Adding redaction to a chatbot is a product change, not a file leaving",
        "add pii redaction to the chatbot's responses",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "which-library-is-best-for-pii-redaction-presidio-or-scrubadub-is-not-a-data-share-review",
        "Choosing a redaction library is a tooling question, not a file leaving",
        "which library is best for pii redaction, presidio or scrubadub",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "benchmark-presidio-for-pii-redaction-accuracy-is-not-a-data-share-review",
        "Benchmarking a redaction library is a measurement, not a file leaving",
        "benchmark presidio for pii redaction accuracy",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "redact-pii-in-real-time-from-our-call-center-audio-stream-is-not-a-data-share-review",
        "Redacting a live audio stream is a system, not a file leaving",
        "redact pii in real-time from our call center audio stream",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "pseudonymize-the-user-ids-in-the-database-migration-is-not-a-data-share-review",
        "Pseudonymizing in a database migration is code, not a file leaving",
        "pseudonymize the user ids in the database migration",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "anonymize-the-database-for-the-staging-environment-is-not-a-data-share-review",
        "Anonymizing a staging database stays inside the team",
        "anonymize the database for the staging environment",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "anonymize-the-data-in-our-analytics-warehouse-permanently-is-not-a-data-share-review",
        "Anonymizing a warehouse in place stays inside the team",
        "anonymize the data in our analytics warehouse permanently",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "refactor-the-pseudonymize-function-to-use-hmac-is-not-a-data-share-review",
        "Refactoring a pseudonymize function is code, not a file leaving",
        "refactor the pseudonymize function to use hmac",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "our-redact-pii-regex-is-too-slow-optimize-it-is-not-a-data-share-review",
        "Speeding up a redaction regex is code, not a file leaving",
        "our redact pii regex is too slow, optimize it",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "the-remove-pii-script-crashed-with-a-unicode-error-is-not-a-data-share-review",
        "A crashing redaction script is a bug, not a file leaving",
        "the remove pii script crashed with a unicode error",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "how-do-i-enable-redact-pii-in-hermes-is-not-a-data-share-review",
        "Turning on Hermes' PII redaction is a setting, not a file leaving",
        "how do I enable redact pii in hermes",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "enable-pii-redaction-in-hermes-config-is-not-a-data-share-review",
        "Enabling redaction in the Hermes config is a setting, not a file leaving",
        "enable pii redaction in hermes config",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "does-hermes-redact-pii-in-telegram-is-not-a-data-share-review",
        "Whether Hermes redacts PII on Telegram is a setting question",
        "does hermes redact pii in telegram",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "why-is-hermes-hashing-user-ids-how-do-i-turn-off-pii-redaction-is-not-a-data-share-review",
        "Turning off Hermes' identifier hashing is a setting, not a file leaving",
        "why is hermes hashing user ids, how do I turn off pii redaction",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "configure-the-gateway-to-redact-pii-on-whatsapp-is-not-a-data-share-review",
        "Configuring the gateway's redaction is a setting, not a file leaving",
        "configure the gateway to redact pii on whatsapp",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "scan-for-pii-in-our-s3-buckets-is-not-a-data-share-review",
        "A storage-wide PII scan is data discovery, not a file leaving",
        "scan for pii in our s3 buckets",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "scan-for-pii-across-our-google-drive-is-not-a-data-share-review",
        "A drive-wide PII scan is data discovery, not a file leaving",
        "scan for pii across our google drive",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "is-there-residual-pii-risk-in-our-ml-model-s-memorization-is-not-a-data-share-review",
        "Model memorization risk is a model question, not a file leaving",
        "is there residual pii risk in our ml model's memorization",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "does-our-contract-with-the-vendor-let-us-share-direct-identifiers-is-not-a-data-share-review",
        "What a vendor contract allows is a legal question",
        "does our contract with the vendor let us share direct identifiers",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "explain-de-identify-versus-anonymize-is-not-a-data-share-review",
        "Defining two terms is a definition, not a file leaving",
        "explain de-identify versus anonymize",
        "answer_directly",
        "direct_answer",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "remove-personal-data-from-my-google-account-is-not-a-data-share-review",
        "Cleaning up a personal account is not a file leaving the team",
        "remove personal data from my google account",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "read-the-text-in-this-screenshot-of-the-pii-redaction-settings-is-not-a-data-share-review",
        "Reading a screenshot of settings is not a file leaving",
        "read the text in this screenshot of the pii redaction settings",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "is-an-ip-address-pii-is-not-a-data-share-review",
        "Whether an IP address is PII is a definition; the bare word is held back",
        "is an ip address pii",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "pii-is-not-a-data-share-review",
        "The bare word PII names nothing to clean; it is held back",
        "pii",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    # Review round two: each of these dispatched the skill while a phrase
    # and a file leaving counted anywhere in the sentence. The request is a
    # delivery, a pull request, a message, a post, a translation, a reminder,
    # a video, or a vendor comparison; none leads with a data-protection verb.
    RoutingPrecisionCase(
        "send-the-customer-details-out-to-the-vendor-in-the-export-file-is-not-a-data-share-review",
        "Sending customer details out to a vendor delivers them; nothing is taken out",
        "send the customer details out to the vendor in the export file",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "get-the-personal-details-out-to-the-contractor-in-the-spreadsheet-is-not-a-data-share-review",
        "Getting personal details out to a contractor delivers them; nothing is taken out",
        "get the personal details out to the contractor in the spreadsheet",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "go-ahead-and-merge-the-pr-that-adds-pii-redaction-to-the-export-file-b-is-not-a-data-share-review",
        "Merging a redaction pull request acts on the PR, not on a file leaving",
        "go ahead and merge the pr that adds pii redaction to the export file before sending to the vendor",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "review-the-pull-request-that-adds-pii-redaction-to-the-files-we-send-v-is-not-a-data-share-review",
        "Reviewing a redaction pull request acts on the PR, not on a file leaving",
        "review the pull request that adds pii redaction to the files we send vendors",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "tell-the-data-team-on-slack-that-we-will-strip-the-pii-from-the-export-is-not-a-data-share-review",
        "Telling the team on Slack about a redaction is a message, not the request",
        "tell the data team on slack that we will strip the pii from the export before the vendor gets it",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "post-a-message-in-privacy-that-we-pseudonymize-the-csv-before-sharing-is-not-a-data-share-review",
        "Posting about pseudonymization is a message, not the request",
        "post a message in #privacy that we pseudonymize the csv before sharing with researchers",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "write-a-blog-post-on-how-to-strip-pii-from-a-dataset-before-sharing-it-is-not-a-data-share-review",
        "A blog post about redacting before sharing is writing, not the request",
        "write a blog post on how to strip pii from a dataset before sharing it with vendors",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "translate-this-paragraph-about-how-to-redact-pii-from-export-files-sen-is-not-a-data-share-review",
        "Translating a paragraph about redaction is translation, not the request",
        "translate this paragraph about how to redact pii from export files sent to vendors into korean",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "schedule-a-calendar-reminder-to-redact-pii-from-the-monthly-export-bef-is-not-a-data-share-review",
        "A reminder to redact later is scheduling, not the request",
        "schedule a calendar reminder to redact pii from the monthly export before it goes to the vendor",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "watch-this-video-about-how-to-redact-pii-from-log-files-before-sharing-is-not-a-data-share-review",
        "Watching a video about redaction is not the request",
        "watch this video about how to redact pii from log files before sharing them",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "which-vendor-is-best-for-pseudonymization-of-datasets-shared-with-thir-is-not-a-data-share-review",
        "Choosing a pseudonymization vendor is a comparison, not the request",
        "which vendor is best for pseudonymization of datasets shared with third party processors",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "give-me-a-sample-message-to-tell-the-vendor-we-redact-pii-is-not-a-data-share-review",
        "A sample message about redaction is writing, not the request",
        "give me a sample message to tell the vendor we redact pii",
        "answer_clarification",
        "",
    ),
    # Review round three: each of these dispatched the skill under a lead-verb
    # rule that read "take ... out", "remove", "strip", "review" or a later
    # clause as protecting data. The object was a name, a flag, a script, a
    # pull request or slides, or the sentence led with another job.
    RoutingPrecisionCase(
        "take-the-vendor-names-out-of-the-export-before-sending-it-to-the-resea-is-not-a-data-share-review",
        "Round three: the lead verb removes something that is not personal data, or the sentence leads with another job",
        "take the vendor names out of the export before sending it to the researcher",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "take-the-product-names-out-of-the-export-before-we-share-it-with-the-a-is-not-a-data-share-review",
        "Round three: the lead verb removes something that is not personal data, or the sentence leads with another job",
        "take the product names out of the export before we share it with the agency",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "take-the-file-names-out-of-the-log-before-posting-it-publicly-is-not-a-data-share-review",
        "Round three: the lead verb removes something that is not personal data, or the sentence leads with another job",
        "take the file names out of the log before posting it publicly",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "take-the-column-names-out-of-the-csv-before-sending-it-to-the-vendor-is-not-a-data-share-review",
        "Round three: the lead verb removes something that is not personal data, or the sentence leads with another job",
        "take the column names out of the csv before sending it to the vendor",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "take-the-pricing-details-out-of-the-export-before-we-send-it-to-the-co-is-not-a-data-share-review",
        "Round three: the lead verb removes something that is not personal data, or the sentence leads with another job",
        "take the pricing details out of the export before we send it to the contractor",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "take-the-build-identifiers-out-of-the-log-file-before-posting-it-publi-is-not-a-data-share-review",
        "Round three: the lead verb removes something that is not personal data, or the sentence leads with another job",
        "take the build identifiers out of the log file before posting it publicly",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "take-the-test-emails-out-of-the-export-before-we-send-it-to-the-vendor-is-not-a-data-share-review",
        "Round three: the lead verb removes something that is not personal data, or the sentence leads with another job",
        "take the test emails out of the export before we send it to the vendor",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "take-the-personal-notes-out-of-the-slide-file-before-sharing-it-with-t-is-not-a-data-share-review",
        "Round three: the lead verb removes something that is not personal data, or the sentence leads with another job",
        "take the personal notes out of the slide file before sharing it with the vendor",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "take-the-shipping-details-out-of-the-spreadsheet-before-sending-it-to-is-not-a-data-share-review",
        "Round three: the lead verb removes something that is not personal data, or the sentence leads with another job",
        "take the shipping details out of the spreadsheet before sending it to the agency",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "remove-pseudonymization-from-the-export-before-sending-it-to-the-resea-is-not-a-data-share-review",
        "Round three: the lead verb removes something that is not personal data, or the sentence leads with another job",
        "remove pseudonymization from the export before sending it to the researcher, they need the real ids",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "strip-the-de-identify-flag-from-the-csv-before-uploading-it-to-the-ven-is-not-a-data-share-review",
        "Round three: the lead verb removes something that is not personal data, or the sentence leads with another job",
        "strip the de-identify flag from the csv before uploading it to the vendor",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "minimize-the-pseudonymization-overhead-in-the-export-job-before-we-sen-is-not-a-data-share-review",
        "Round three: the lead verb removes something that is not personal data, or the sentence leads with another job",
        "minimize the pseudonymization overhead in the export job before we send the file to the vendor",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "sanitize-the-html-in-the-export-before-sharing-it-with-the-vendor-the-is-not-a-data-share-review",
        "Round three: the lead verb removes something that is not personal data, or the sentence leads with another job",
        "sanitize the html in the export before sharing it with the vendor, the pii redaction ran earlier",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "strip-the-header-row-from-the-csv-before-we-send-it-to-the-vendor-our-is-not-a-data-share-review",
        "Round three: the lead verb removes something that is not personal data, or the sentence leads with another job",
        "strip the header row from the csv before we send it to the vendor, our pii redaction script expects no header",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "review-the-pii-redaction-pull-request-before-we-send-the-export-to-the-is-not-a-data-share-review",
        "Round three: the lead verb removes something that is not personal data, or the sentence leads with another job",
        "review the pii redaction pull request before we send the export to the vendor",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "review-the-pseudonymization-notebook-before-we-share-the-dataset-with-is-not-a-data-share-review",
        "Round three: the lead verb removes something that is not personal data, or the sentence leads with another job",
        "review the pseudonymization notebook before we share the dataset with the researcher",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "review-the-slides-on-pii-redaction-before-we-send-the-deck-file-to-the-is-not-a-data-share-review",
        "Round three: the lead verb removes something that is not personal data, or the sentence leads with another job",
        "review the slides on pii redaction before we send the deck file to the vendor",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "check-the-log-file-for-pii-redaction-bugs-before-sending-it-to-the-ven-is-not-a-data-share-review",
        "Round three: the lead verb removes something that is not personal data, or the sentence leads with another job",
        "check the log file for pii redaction bugs before sending it to the vendor",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "strip-the-pii-redaction-markers-from-the-export-before-sending-it-to-t-is-not-a-data-share-review",
        "Round three: the lead verb removes something that is not personal data, or the sentence leads with another job",
        "strip the pii redaction markers from the export before sending it to the vendor",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "send-the-vendor-the-export-then-remove-the-pii-from-our-copy-is-not-a-data-share-review",
        "Round three: the lead verb removes something that is not personal data, or the sentence leads with another job",
        "send the vendor the export, then remove the pii from our copy",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "write-a-blog-post-about-our-export-process-then-redact-the-pii-section-is-not-a-data-share-review",
        "Round three: the lead verb removes something that is not personal data, or the sentence leads with another job",
        "write a blog post about our export process, then redact the pii section before we share the draft file with the vendor",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "merge-the-pr-then-redact-the-pii-in-the-export-before-sending-it-to-th-is-not-a-data-share-review",
        "Round three: the lead verb removes something that is not personal data, or the sentence leads with another job",
        "merge the pr, then redact the pii in the export before sending it to the vendor",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "mixed-korean-take-the-names-out-is-not-a-data-share-review",
        "Round three: the lead verb removes something that is not personal data, or the sentence leads with another job",
        "take the names out of the export 파일 before vendor한테 보내기",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    # Review round four: a lead verb that is being defined, or a question, is
    # not a command to clean a file.
    RoutingPrecisionCase(
        "de-identify-means-what-question-is-not-a-data-share-review",
        "Asking what de-identify means is a question, not a request to clean the file",
        "de-identify means what exactly, before we send the file to the researcher?",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    # No `forbidden_candidate`: the shortlist lists the skill below
    # research-brief, which leads; the claim is that it does not dispatch.
    RoutingPrecisionCase(
        "de-identify-is-the-term-is-not-a-data-share-review",
        "Saying de-identify is the guide's term defines a word, not a request to clean a file",
        "de-identify is the term we use in the guide; write a page on how we send files to vendors",
        "answer_clarification",
        "",
    ),
    RoutingPrecisionCase(
        "paid-rent-is-not-a-spend",
        "Rent the person already paid is everyday money talk, not a spend to gate",
        "I paid the rent yesterday",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "lunch-budget-is-not-a-spend",
        "A lunch budget question is everyday money talk, not a spend to gate",
        "what's my budget for lunch",
        "answer_directly",
        "direct_answer",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "government-spending-cap-is-not-a-spend-cap",
        "A government's spending cap is not the person's cap on an agent's spend",
        "the government raised the spending cap again this year",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "photo-from-wallet-is-not-a-wallet-spend",
        "A photo falling from a wallet moves no money",
        "the photo fell out from my wallet on the bus",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "wallet-transfer-feature-tests-are-not-a-spend",
        "Testing a wallet-transfer feature someone is building moves no money",
        "our wallet transfer feature needs integration tests",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "customer-payment-question-is-not-a-spend",
        "A customer asking whether their payment went through is not the agent's spend",
        "a customer emailed asking did the payment go through",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "slide-order-is-not-an-order",
        "Placing slides in order is not placing an order",
        "place the order of the slides so the demo comes first",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "git-checkout-is-not-a-checkout",
        "Checking out a git branch is not a checkout; the bare word is held back",
        "git checkout main and pull the latest changes",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "own-api-402-is-not-a-spend",
        "Returning HTTP 402 from one's own API is building a paywall, not paying one",
        "return http 402 from our api when the trial expires",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "provider-cost-comparison-is-not-a-spend",
        "Comparing what model providers cost buys nothing",
        "which model provider costs less for this workload",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "pay-attention-is-not-a-payment",
        "Paying attention to a log is not a payment; the bare word is held back",
        "pay attention to the error log after the deploy",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "wallet-transfer-flow-design-is-not-a-spend",
        "Designing a wallet-transfer flow for an app moves no money",
        "design the wallet transfer flow for our mobile app",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "402-client-library-question-is-not-a-spend",
        "Handling a 402 challenge in a client library is code, not a payment",
        "how do I handle a 402 challenge in the client library i'm writing",
        "answer_directly",
        "direct_answer",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "place-order-button-bug-is-not-an-order",
        "A place-the-order button that does not respond is a UI bug, not an order",
        "the place the order button doesn't respond on safari",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "react-native-checkout-flow-is-not-a-checkout",
        "Completing a checkout flow in an app being built moves no money",
        "complete the checkout flow in the react native app",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "flutter-checkout-screen-is-not-a-checkout",
        "Completing a checkout screen in an app being built moves no money",
        "complete the checkout screen in my flutter app",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "payment-faq-is-not-a-spend",
        "Writing a FAQ about whether payments went through moves no money",
        "our users keep asking did the payment go through, write an FAQ",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "charge-check-function-is-not-a-spend",
        "A function that checks a charge is code, not a charge",
        "write a function that checks did the charge go through",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "wallet-transfer-screen-crash-is-not-a-spend",
        "A crashing wallet-transfer screen is a bug, not a transfer",
        "the wallet transfer screen crashes on android",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "buy-it-for-me-button-layout-is-not-a-spend",
        "A buy-it-for-me button overlapping a footer is layout, not a purchase",
        "the buy it for me button overlaps the footer on mobile",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "place-order-endpoint-rename-is-not-an-order",
        "Renaming a place-an-order endpoint is code, not an order",
        "rename the place an order endpoint to create_order",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "procurement-purchase-order-is-not-the-persons-spend",
        "A purchase order in a procurement system is not the person's own spend",
        "approve the purchase order for the new laptops in the procurement system",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "procurement-spend-request-form-is-not-a-spend",
        "A procurement team's spend request form moves no money",
        "the procurement team needs a spend request form",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "402-status-code-explanation-is-not-a-spend",
        "Explaining the 402 status code pays nothing",
        "explain the 402 payment required status code",
        "answer_directly",
        "direct_answer",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "grey-purchase-button-is-not-a-purchase",
        "A grey complete-the-purchase button is a UI state, not a purchase",
        "the complete the purchase button is grey on checkout",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "order-step-analytics-is-not-an-order",
        "Adding analytics to an order step is instrumentation, not an order",
        "add analytics to the place an order step",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "wallet-transfer-api-403-is-not-a-spend",
        "A wallet-transfer API returning 403 is an error, not a transfer",
        "the wallet transfer api returns 403",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "pay-button-event-log-is-not-a-spend",
        "Logging a user's tap on a pay button is instrumentation, not a payment",
        "log an event when the user taps pay with my card",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "buy-it-for-me-string-localization-is-not-a-spend",
        "Localizing a buy-it-for-me string is translation, not a purchase",
        "localize the buy it for me string into french",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "place-order-e2e-test-is-not-an-order",
        "An end-to-end test that clicks place the order moves no money",
        "write an e2e playwright test that clicks place the order",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "malformed-402-header-is-not-a-spend",
        "A malformed 402 challenge header is a server bug, not a payment",
        "the 402 challenge header is malformed in the server response",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "payment-status-banner-is-not-a-spend",
        "A did-the-payment-go-through banner is UI, not a payment",
        "add a did the payment go through banner",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "solana-wallet-transfer-explanation-is-not-a-spend",
        "Explaining how a wallet transfer works pays nothing",
        "explain how a wallet transfer works on solana",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "wallet-transfer-how-question-is-not-a-spend",
        "Asking how a wallet transfer works pays nothing",
        "how does a wallet transfer work",
        "answer_directly",
        "direct_answer",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "flaky-saved-card-test-is-not-a-spend",
        "A flaky test for paying with a saved card is a test, not a payment",
        "the test for pay with my saved card is flaky",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "buy-it-for-me-system-prompt-is-not-a-spend",
        "A system prompt that mentions buying is a prompt, not a purchase",
        "write a system prompt that tells the bot to buy it for me",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "place-order-user-story-is-not-an-order",
        "A user story about placing an order is a requirement, not an order",
        "user story: as a shopper I want to place an order",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "coupa-purchase-request-is-not-the-persons-spend",
        "Approving a purchase request in a procurement system is not the person's own spend",
        "approve this purchase request in coupa",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "someone-elses-payment-question-is-not-a-spend",
        "Someone else asking whether their payment went through is not the agent's spend",
        "my mom asked did the payment go through",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "admin-wallet-transfer-limit-is-not-a-spend",
        "A wallet-transfer limit on an admin dashboard is a setting being built, not a spend",
        "add a wallet transfer limit to the admin dashboard",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "slow-paid-endpoint-question-is-not-a-spend",
        "Asking why a paid endpoint is slow pays nothing",
        "why is the paid data endpoint slow",
        "answer_directly",
        "direct_answer",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "place-order-api-docs-are-not-an-order",
        "Documenting a place-the-order API is docs, not an order",
        "document the place the order api",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "checkout-page-wireframe-is-not-a-checkout",
        "A wireframe for a checkout page is design, not a checkout",
        "sketch a wireframe for the complete the checkout page",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "terms-of-service-clause-is-not-a-spend",
        "A money-on-my-behalf clause in terms of service moves no money",
        "the money on my behalf clause in the terms of service",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "blog-post-about-agent-spending-is-not-a-spend",
        "A blog post on why agents should not spend moves no money",
        "write a blog post on why agents should not spend money on my behalf",
        "answer_clarification",
        "",
        # spend-gate is offered in the shortlist after a declined dispatch, which
        # admits the lexical ranking as it stands; the pin is that it never dispatches.
        "",
    ),
    RoutingPrecisionCase(
        "purchase-hook-refactor-is-not-a-purchase",
        "Refactoring complete-the-purchase into a hook is code, not a purchase",
        "refactor complete the purchase into a hook",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "order-email-typo-is-not-an-order",
        "Fixing a typo in an order email template moves no money",
        "fix the typo in the place an order email template",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "pricing-comparison-is-not-a-spend",
        "Comparing pay-per-request with a flat plan buys nothing",
        "pay per request pricing versus a flat plan, which one is better",
        "answer_clarification",
        "",
        # spend-gate is offered in the shortlist after a declined dispatch, which
        # admits the lexical ranking as it stands; the pin is that it never dispatches.
        "",
    ),
    RoutingPrecisionCase(
        "past-card-purchase-is-not-a-spend",
        "Lunch the person already paid for with their card is everyday money talk",
        "I paid for lunch with my card",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "government-spending-is-not-a-spend",
        "A government spending money on roads is not the person's spend",
        "the government will spend up to 5 billion dollars on roads",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "third-party-future-order-is-not-a-spend",
        "Someone else placing an order tomorrow is not the person's spend; admission needs the request to lead with the spend",
        "she will place an order with the supplier tomorrow",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "club-buying-for-members-is-not-a-spend-request",
        "What a club will buy for its members is a statement, not a request to the agent to spend",
        "the club will buy it for members at cost",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "blog-post-on-paying-with-a-saved-card-is-not-a-spend",
        "A blog post about paying with a saved card asks for writing, not a spend; the phrase is only the topic",
        "write a blog post on how to pay with my saved card",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "slack-message-about-a-payment-is-not-a-spend",
        "A message saying the vendor was paid asks for a message, not a spend; the phrase is only the topic",
        "send a slack message saying I paid the vendor",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "rent-reminder-is-not-a-spend",
        "A reminder to pay rent asks for a reminder, not a spend now; the phrase is only the topic",
        "schedule a reminder to pay my rent",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "best-card-question-is-not-a-spend",
        "Asking which card is best to pay with asks for advice, not a spend; the phrase is only the topic",
        "which card is best to pay for the tickets",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "second-clause-purchase-is-not-the-request",
        "Only the sentence's first verb is the request; a purchase in a later clause does not take it from the first clause's owner",
        "transcribe this call, then buy it for me if it is cheap",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "checkout-flow-for-card-payments-is-not-a-checkout",
        "Completing a checkout flow is building one; the object ends in a thing being built",
        "complete the checkout flow for my card payments",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "broken-saved-card-toggle-is-not-a-payment",
        "A pay-with-my-saved-card toggle that is broken is a bug report; the object ends in a thing being built",
        "pay with my saved card toggle is broken",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "not-a-spend-check-out-this-article-on-why-you-should-never-pay-with-my-card-abro",
        "An article to check out is not a checkout; the phrase is only its topic",
        "Check out this article on why you should never pay with my card abroad",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "not-a-spend-check-out-this-thread-about-agents-that-buy-it-for-me-automatically",
        "A thread to check out is not a checkout; the phrase is only its topic",
        "Check out this thread about agents that buy it for me automatically",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "not-a-spend-pay-attention-when-someone-says-buy-it-for-me-in-chat",
        "Paying attention is an idiom, not a payment",
        "Pay attention when someone says buy it for me in chat",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "not-a-spend-tip-always-pay-with-my-card-abroad",
        "A tip is advice, not a tip paid; the lead is a noun before a colon",
        "Tip: always pay with my card abroad",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "not-a-spend-book-review-agents-that-spend-on-my-behalf-chapter-3",
        "A book review is not a booking; the phrase is after the colon",
        "Book review: agents that spend on my behalf, chapter 3",
        "answer_clarification",
        "",
        # The gate appears in the shortlist after a declined dispatch, which admits
        # the lexical ranking as it stands; the pin is that it never dispatches.
        "",
    ),
    RoutingPrecisionCase(
        "not-a-spend-order-5512-did-the-payment-go-through-the-customer-is-asking",
        "An order number is not an order; the lead names a ticket",
        "Order 5512: did the payment go through? the customer is asking",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "not-a-spend-order-of-events-when-you-pay-with-my-card-auth-capture-settle",
        "An order of events is not an order",
        "Order of events when you pay with my card: auth, capture, settle",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "not-a-spend-pay-with-my-card-or-paypal-which-is-safer",
        "A question about which payment is safer pays nothing",
        "Pay with my card or PayPal, which is safer?",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "not-a-spend-pay-with-my-saved-card-is-it-safe-on-public-wifi",
        "A question about paying with a saved card pays nothing",
        "Pay with my saved card, is it safe on public wifi?",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "not-a-spend-pay-per-request-apis-are-cheaper-for-low-traffic",
        "A hyphenated pay-per-request is not the verb pay",
        "Pay-per-request APIs are cheaper for low traffic",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "not-a-spend-pay-per-request-pricing-is-what-we-chose-for-the-api",
        "A statement about pricing is not a payment",
        "Pay per request pricing is what we chose for the api",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "not-a-spend-buy-side-analysts-use-my-credit-card-data-in-their-models",
        "A hyphenated buy-side is not the verb buy",
        "Buy-side analysts use my credit card data in their models",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "not-a-spend-book-the-meeting-with-finance-about-money-on-my-behalf",
        "Booking a meeting is not a spend; the phrase is after the clause",
        "Book the meeting with finance about money on my behalf",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "not-a-spend-send-the-team-a-note-about-the-money-on-my-behalf-policy",
        "Sending a note is not sending money; the phrase is after the clause",
        "Send the team a note about the money on my behalf policy",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "not-a-spend-subscribe-to-the-newsletter-about-money-on-my-behalf",
        "A newsletter subscription about spending is not a spend; the phrase is after the clause",
        "Subscribe to the newsletter about money on my behalf",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "not-a-spend-use-my-credit-card-as-the-default-in-the-seed-data",
        "A card in seed data is configuration, not a spend",
        "Use my credit card as the default in the seed data",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "not-a-spend-pay-stubs-with-my-card-number-on-them-are-a-privacy-risk",
        "Pay stubs are documents, not a payment",
        "Pay stubs with my card number on them are a privacy risk",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "not-a-spend-pay-with-my-saved-card-returns-a-500-error",
        "A feature returning an error is a statement, not a payment",
        "Pay with my saved card returns a 500 error",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "not-a-spend-pay-with-my-card-is-greyed-out-on-the-checkout-page",
        "A greyed-out pay option is a statement, not a payment",
        "Pay with my card is greyed out on the checkout page",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "not-a-spend-buy-it-for-me-doesn-t-work-on-safari",
        "A buy-it-for-me feature that does not work is a statement, not a purchase",
        "Buy it for me doesn't work on safari",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "not-a-spend-buy-it-for-me-is-the-copy-marketing-wants-on-the-cta",
        "Button copy is a statement, not a purchase",
        "Buy it for me is the copy marketing wants on the CTA",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "not-a-spend-pay-on-my-behalf-permissions-need-a-design-review",
        "Permissions needing review is a statement, not a payment",
        "Pay on my behalf permissions need a design review",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "not-a-spend-send-money-feature-needs-rate-limiting",
        "A send-money feature needing work is a statement, not a transfer",
        "Send money feature needs rate limiting",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "not-a-spend-pay-again-button-shows-twice-after-a-timeout",
        "A pay-again button is a UI element, not a payment",
        "Pay again button shows twice after a timeout",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "not-a-spend-purchase-with-my-card-is-disabled-for-minors-by-policy",
        "A disabled purchase option is a statement, not a purchase",
        "Purchase with my card is disabled for minors by policy",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "not-a-spend-check-out-the-new-pay-with-my-card-flow",
        "A new flow to check out is not a checkout",
        "Check out the new pay with my card flow",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "not-a-spend-pay-the-invoice-with-my-card-toggle",
        "A card toggle is a UI element, not the payment source",
        "Pay the invoice with my card toggle",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "not-a-spend-checkout-times-out-for-users-who-pick-pay-with-my-saved-card",
        "A checkout that times out for users is a statement, not a checkout",
        "Checkout times out for users who pick pay with my saved card",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "not-a-spend-click-pay-again-only-if-the-first-charge-is-shown-absent-that-s-our",
        "Stating a retry rule is not a retry",
        "Click pay again only if the first charge is shown absent, that's our rule",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "not-a-spend-use-my-credit-card-number-4242-in-the-checkout-test",
        "A card number in a checkout test is test data, not a spend",
        "Use my credit card number 4242 in the checkout test",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "not-a-spend-buy-it-for-me-buttons-convert-better-than-add-to-cart",
        "Buy-it-for-me buttons are UI, not a purchase",
        "Buy it for me buttons convert better than add to cart",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "not-a-spend-pay-with-my-saved-card-stopped-working-on-safari",
        "A pay-with-my-saved-card feature that stopped working is a report; a verb follows the phrase",
        "Pay with my saved card stopped working on safari",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "not-a-spend-pay-with-my-card-broke-after-the-deploy",
        "A pay-with-my-card feature that broke is a report; a verb follows the phrase",
        "Pay with my card broke after the deploy",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "not-a-spend-checkout-with-my-card-crashed-yesterday",
        "A checkout that crashed is a report; a verb follows the phrase",
        "Checkout with my card crashed yesterday",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "not-a-spend-pay-again-appeared-twice-after-a-timeout",
        "A pay-again control that appeared twice is a report; a verb follows the phrase",
        "Pay again appeared twice after a timeout",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "not-a-spend-pay-with-my-card-would-be-nice-to-have-in-v2",
        "A feature wish is not a payment; a modal follows the phrase",
        "Pay with my card would be nice to have in v2",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "not-a-spend-pay-on-my-behalf-could-confuse-people",
        "A naming concern is not a payment; a modal follows the phrase",
        "Pay on my behalf could confuse people",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "comparison-without-a-question-mark-is-not-a-spend",
        "A comparison is not a payment; or follows the phrase",
        "Pay with my card or paypal which is safer",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "not-a-spend-pay-with-my-card-or-cash-for-the-cab-what-do-you-think",
        "Asking which way to pay is not a payment; or follows the phrase",
        "Pay with my card or cash for the cab, what do you think",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "not-a-spend-buy-time-with-my-card-issuer-by-disputing-the-charge",
        "Buying time is an idiom, and a card issuer is not the payment source",
        "Buy time with my card issuer by disputing the charge",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "not-a-spend-pay-a-visit-to-the-bank-with-my-card-and-ask-about-the-fee",
        "Paying a visit is an idiom, not a payment",
        "Pay a visit to the bank with my card and ask about the fee",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "not-a-spend-check-out-a-cheaper-pay-with-my-card-option",
        "Checking out an option is looking at it; a noun follows the phrase",
        "Check out a cheaper pay with my card option",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "not-a-spend-buy-it-for-me-went-live-last-week",
        "A buy-it-for-me feature going live is a report; a verb follows the phrase",
        "Buy it for me went live last week",
        "answer_directly",
        "direct_answer",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "not-a-spend-buy-it-for-me-converts-better-than-add-to-cart",
        "Button performance is a report; a verb follows the phrase",
        "Buy it for me converts better than add to cart",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "not-a-spend-buy-it-for-me-got-3-more-clicks-in-the-experiment",
        "An experiment result is a report; a verb follows the phrase",
        "Buy it for me got 3% more clicks in the experiment",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "not-a-spend-pay-with-my-card-looks-broken-on-mobile",
        "A broken-looking control is a report; a verb follows the phrase",
        "Pay with my card looks broken on mobile",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "not-a-spend-use-my-credit-card-might-be-a-better-cta",
        "Button copy is a proposal, not a payment; a modal follows the phrase",
        "Use my credit card might be a better CTA",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "unmarked-pay-with-my-card-in-safari-is-broken",
        "A sentence that says a gate phrase with no request marker is not a request to spend",
        "Pay with my card in safari is broken",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "unmarked-pay-with-my-card-from-the-settings-page-is-greyed-out",
        "A sentence that says a gate phrase with no request marker is not a request to spend",
        "Pay with my card from the settings page is greyed out",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "unmarked-pay-with-my-card-when-logged-in-shows-a-spinner",
        "A sentence that says a gate phrase with no request marker is not a request to spend",
        "Pay with my card when logged in shows a spinner",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "unmarked-pay-with-my-card-and-paypal-are-both-supported-now",
        "A sentence that says a gate phrase with no request marker is not a request to spend",
        "Pay with my card and paypal are both supported now",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "unmarked-pay-with-my-saved-card-to-amazon-works-fine-on-desktop",
        "A sentence that says a gate phrase with no request marker is not a request to spend",
        "Pay with my saved card to amazon works fine on desktop",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "unmarked-pay-with-my-card-for-subscriptions-is-coming-in-v2",
        "A sentence that says a gate phrase with no request marker is not a request to spend",
        "Pay with my card for subscriptions is coming in v2",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "unmarked-pay-on-my-behalf-for-minors-needs-parental-consent",
        "A sentence that says a gate phrase with no request marker is not a request to spend",
        "Pay on my behalf for minors needs parental consent",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "unmarked-pay-with-my-card-on-slide-3-needs-a-bigger-font",
        "A sentence that says a gate phrase with no request marker is not a request to spend",
        "Pay with my card on slide 3 needs a bigger font",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "unmarked-pay-with-my-card-on-the-whiteboard-sketch",
        "A sentence that says a gate phrase with no request marker is not a request to spend",
        "Pay with my card on the whiteboard sketch",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "unmarked-pay-with-my-card-at-2x-speed-in-the-demo-recording",
        "A sentence that says a gate phrase with no request marker is not a request to spend",
        "Pay with my card at 2x speed in the demo recording",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "unmarked-pay-on-my-behalf-in-the-sense-of-the-policy-doc",
        "A sentence that says a gate phrase with no request marker is not a request to spend",
        "pay on my behalf in the sense of the policy doc",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "unmarked-pay-with-my-card-in-the-demo-video",
        "A sentence that says a gate phrase with no request marker is not a request to spend",
        "pay with my card in the demo video",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "unmarked-buy-it-for-me-at-the-hackathon-booth-is-our-slogan",
        "A sentence that says a gate phrase with no request marker is not a request to spend",
        "buy it for me at the hackathon booth is our slogan",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "unmarked-use-my-credit-card-for-the-screenshot",
        "A sentence that says a gate phrase with no request marker is not a request to spend",
        "use my credit card for the screenshot",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "unmarked-pay-with-my-card-on-mobile-stopped-working",
        "A sentence that says a gate phrase with no request marker is not a request to spend",
        "Pay with my card on mobile stopped working",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "unmarked-buy-it-for-me-on-the-product-page-doesn-t-render",
        "A sentence that says a gate phrase with no request marker is not a request to spend",
        "Buy it for me on the product page doesn't render",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "unmarked-buy-it-for-me-at-checkout-converts-3-better",
        "A sentence that says a gate phrase with no request marker is not a request to spend",
        "Buy it for me at checkout converts 3% better",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "unmarked-buy-it-for-me-and-wishlist-are-the-two-ctas",
        "A sentence that says a gate phrase with no request marker is not a request to spend",
        "Buy it for me and wishlist are the two CTAs",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "unmarked-buy-this-for-me-on-amazon-was-the-first-prompt-we-tested",
        "A sentence that says a gate phrase with no request marker is not a request to spend",
        "Buy this for me on amazon was the first prompt we tested",
        "answer_directly",
        "direct_answer",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "unmarked-use-my-credit-card-for-the-demo-is-what-the-script-says",
        "A sentence that says a gate phrase with no request marker is not a request to spend",
        "Use my credit card for the demo is what the script says",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "unmarked-pay-with-my-card-not-apple-pay-is-the-default",
        "A sentence that says a gate phrase with no request marker is not a request to spend",
        "Pay with my card, not apple pay, is the default",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "marker-amount-after-for-is-not-a-request",
        "An amount or \"for me\" after a preposition is not the spend's object, so it marks no request",
        "Pay with my card for $0 orders is broken",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "marker-amount-after-on-is-not-a-request",
        "An amount or \"for me\" after a preposition is not the spend's object, so it marks no request",
        "Pay with my card on $0 invoices throws an error",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "marker-for-me-after-the-phrase-is-not-a-request",
        "An amount or \"for me\" after a preposition is not the spend's object, so it marks no request",
        "Pay with my card for me never shows up on android",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "marker-for-me-after-at-is-not-a-request",
        "An amount or \"for me\" after a preposition is not the spend's object, so it marks no request",
        "Pay with my card at checkout for me is the default",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "marker-amount-after-a-phrase-and-for-is-not-a-request",
        "An amount or \"for me\" after a preposition is not the spend's object, so it marks no request",
        "Buy it for me for $5 more is our upsell copy",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "marker-for-me-after-a-with-phrase-is-not-a-request",
        "\"for me\" right after one of the gate's phrases is not the spend's object, so it marks no request",
        "Book with my card for me never shows up on android",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "marker-for-me-after-a-with-phrase-in-a-label-is-not-a-request",
        "\"for me\" right after one of the gate's phrases is not the spend's object, so it marks no request",
        "Order with my card for me is the default",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "marker-for-me-after-a-saved-card-phrase-is-not-a-request",
        "\"for me\" right after one of the gate's phrases is not the spend's object, so it marks no request",
        "Buy with my saved card for me is greyed out in safari",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "marker-for-me-after-a-phrase-that-is-the-lead-is-not-a-request",
        "\"for me\" right after one of the gate's phrases is not the spend's object, so it marks no request",
        "Use my credit card for me never shows up on android",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "marker-for-me-after-an-object-and-a-phrase-is-not-a-request",
        "A phrase starts the spend's object again, so \"for me\" right after it marks no request even after an object word",
        "Book the flight with my card for me never shows up on android",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "marker-for-me-after-an-object-and-a-phrase-in-a-bug-is-not-a-request",
        "A phrase starts the spend's object again, so \"for me\" right after it marks no request even after an object word",
        "Pay the invoice with my card for me is broken in safari",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    # A loop on a timer whose prompt checks a price or a payment spends
    # nothing: it stays Hermes' native /loop. Only a prompt that spends opens
    # the spend gate.
    RoutingPrecisionCase(
        "loop-checking-a-price-is-not-a-spend",
        "A loop that checks a ticket price on a timer is Hermes' /loop, not a spend",
        "loop every 10 minutes and check whether the concert tickets dropped under $50",
        "answer_directly",
        "direct_answer",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "typed-loop-checking-a-card-payment-is-not-a-spend",
        "A typed /loop that checks whether a card payment went through is Hermes' /loop, not a spend",
        "/loop 30m check whether the payment from my card went through",
        "answer_directly",
        "direct_answer",
        "spend-gate",
    ),
    # The router and the in-session hint admit the same requests: each of
    # these got spend-gate's route hint while the router left the gate out. `tests/test_spend_gate.py` checks every
    # negative control's hint, so these pin the hint as well as the route.
    RoutingPrecisionCase(
        "city-budget-spending-cap-look-is-not-a-spend",
        "Looking at a city budget's spending cap has no word of paying, so neither the router nor the hint offers the gate",
        "can you check out the spending cap for the city council budget",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "spend-gate-spaced-name-alone-is-not-an-invocation",
        "The gate's spaced name alone is no invocation; the router and the hint both wait for 'use' or 'run' or the hyphenated name",
        "spend gate",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "spend-gate-name-as-a-greyed-out-label-is-not-a-request",
        "Naming the gate as a label that is greyed out asks for no spend",
        "use spend gate is greyed out in settings",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    # "gate" said anywhere but in the gate's own name is no word of paying:
    # while it anchored a cap or wallet phrase, each of these dispatched the gate.
    RoutingPrecisionCase(
        "airport-gate-spending-limit-look-is-not-a-spend",
        "An airport gate beside a spending limit is no word of paying",
        "could you check out the spending limit at the airport gate",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "red-ci-gate-beside-a-budget-cap-is-not-a-spend",
        "A red CI gate beside a city budget's spending cap is no word of paying",
        "can you check out the spending cap for the city council budget, the ci gate is red",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "wallet-receipt-at-a-gate-number-is-not-a-spend",
        "A gate number beside a receipt from the person's wallet is no word of paying",
        "please check out the receipt from my wallet at gate 12",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    # Korean admission for the two safety gates (owner decision D.4): a Korean
    # request is read from its last predicate, closed by a request ending, so
    # the everyday sense of the gates' words ends on another verb, on no
    # request, or with nothing the gate needs beside it.
    RoutingPrecisionCase(
        "korean-payment-system-design-is-not-a-spend",
        "Designing a payment system ends on design, not on paying",
        "결제 시스템 설계해줘",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "korean-payment-test-is-not-a-spend",
        "Testing the payment flow ends on test, not on paying",
        "결제 테스트 해줘",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "korean-past-payment-is-not-a-spend",
        "Saying the payment was made asks for nothing",
        "결제했어",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "korean-no-need-to-pay-is-not-a-spend",
        "Saying there is no need to pay asks for no payment",
        "결제 안 해줘도 돼",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "korean-document-approval-is-not-a-payment",
        "Approving a document (결재) is not paying (결제)",
        "이 문서 결재해줘",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "korean-restaurant-booking-without-money-is-not-a-spend",
        "Booking a restaurant with no card, account or amount beside it moves no money",
        "식당 예약해줘",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "korean-phone-charging-is-not-a-spend",
        "Charging a phone is not topping up money",
        "폰 충전해줘",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "korean-screen-share-is-not-a-data-share-review",
        "Sharing the screen protects no personal data and sends no file out",
        "화면 공유해줘",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "korean-pii-masking-code-is-not-a-data-share-review",
        "Writing code that masks personal data is a coding request, not data leaving the team",
        "개인정보 마스킹하는 코드 짜줘",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "korean-deleting-customer-pii-is-not-a-data-share-review",
        "Deleting a customer's personal data sends nothing out",
        "고객 개인정보 지워줘",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "korean-masking-pii-with-no-recipient-is-not-a-data-share-review",
        "Masking personal data with nothing leaving the team is not a data share",
        "개인정보 마스킹해줘",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "korean-field-name-alone-is-not-a-data-share-review",
        "Removing a name before sharing says none of the review's phrases, so neither surface offers it",
        "이름 지우고 공유해줘",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    # Review of the Korean admission: each of these named a gate while a
    # recipient counted by containment, a negated clause or a document sent
    # beside an amount was read as the request, or a processed order as a
    # payment.
    RoutingPrecisionCase(
        "korean-pii-masked-in-external-logs-is-not-a-data-share-review",
        "Masking personal data in external logs names a kind of log, not a recipient",
        "외부 로그에서 개인정보 마스킹해줘",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "korean-pii-deleted-from-an-overseas-team-list-is-not-a-data-share-review",
        "An overseas department's list holds 외부 inside another word, and nothing leaves",
        "해외부서 명단에서 개인정보 삭제해줘",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "korean-masking-instead-of-sending-is-not-a-data-share-review",
        "Masking personal data instead of sending it to the vendor sends nothing",
        "벤더한테 보내지 말고 개인정보만 마스킹해줘",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "korean-upload-to-staging-is-not-a-data-share-review",
        "Uploading cleaned test data to staging keeps it inside the team",
        "테스트 데이터에서 고객 정보 지우고 스테이징에 올려줘",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "korean-processing-a-payment-is-not-a-spend",
        "Processing a payment is not paying, as processing an order is no spend in English",
        "결제 처리해줘",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "korean-processing-an-order-is-not-a-spend",
        "Processing an order is not paying",
        "주문 처리해줘",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "korean-loop-sending-a-price-alert-is-not-a-spend",
        "A loop that sends a price alert beside an amount sends a reminder, not money; it stays Hermes' /loop",
        "/loop 1h 3만원 이하면 알림 보내줘",
        "answer_directly",
        "direct_answer",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "korean-loop-sending-a-rule-document-is-not-a-spend",
        "A loop that sends a three-rules document holds no amount; 3원칙 is a rule",
        "/loop 30m 3원칙 문서 보내줘",
        "answer_directly",
        "direct_answer",
        "spend-gate",
    ),
    # Second review of the Korean admission: each of these named a gate while
    # an amount or a card that pays for nothing, an honorific or "없이"
    # negation, 로 on a word that starts with a recipient, or an export to a
    # file was read as the request.
    RoutingPrecisionCase(
        "korean-sponsor-list-update-is-not-a-spend",
        "Updating a list of sponsors above an amount pays for nothing",
        "5달러 이상 후원자 명단 갱신해줘",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "korean-booking-without-paying-is-not-a-spend",
        "Booking a meeting room without paying by card is no spend; the card belongs to the negated payment",
        "내 카드로 결제 없이 회의실 예약만 해줘",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "korean-honorific-no-payment-is-not-a-spend",
        "An honorific 'do not pay with my card, only book the room' asks for no payment",
        "내 카드로 결제하지 마시고 회의실만 예약해 주세요",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "korean-price-update-is-not-a-spend",
        "Setting a price to an amount is an edit, not a payment",
        "가격 5000원으로 갱신해줘",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "korean-card-details-update-is-not-a-spend",
        "Updating the person's card details names a card, not a payment",
        "제 카드 정보 갱신해 주세요",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "korean-card-report-subscription-is-not-a-spend",
        "Subscribing to a report on the person's card spending pays for nothing",
        "내 카드 실적 리포트 구독해줘",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "korean-card-game-tournament-booking-is-not-a-spend",
        "Booking a card-game tournament names a game, not a card that pays",
        "우리 카드 게임 대회 예약해줘",
        "answer_clarification",
        "",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "korean-loop-subscribing-to-a-price-alert-is-not-a-spend",
        "A loop that subscribes to an alert for items under an amount pays for nothing; it stays Hermes' /loop",
        "/loop 1h 1만원 이하 상품 알림 구독해줘",
        "answer_directly",
        "direct_answer",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "korean-loop-repricing-a-price-list-is-not-a-spend",
        "A loop that reprices a price list in units of an amount pays for nothing; it stays Hermes' /loop",
        "/loop 1h 가격표 1000원 단위로 갱신해줘",
        "answer_directly",
        "direct_answer",
        "spend-gate",
    ),
    RoutingPrecisionCase(
        "korean-masking-per-vendor-is-not-a-data-share-review",
        "Masking customer information per vendor names a grouping, not a recipient",
        "업체별로 고객 정보 마스킹해줘",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "korean-deleting-per-client-is-not-a-data-share-review",
        "Deleting phone numbers per client names a grouping, not a recipient",
        "거래처별로 전화번호 삭제해줘",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "korean-deleting-by-foreign-key-is-not-a-data-share-review",
        "Deleting customer information linked by a foreign key (외부키) sends nothing out",
        "외부키로 연결된 고객 정보 삭제해줘",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "korean-sorting-by-vendor-name-is-not-a-data-share-review",
        "Sorting by vendor name before masking names a sort key, not a recipient",
        "업체명으로 정렬해서 고객 정보 마스킹해줘",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "korean-export-to-a-spreadsheet-is-not-a-data-share-review",
        "Exporting cleaned data to a spreadsheet writes a file; nothing leaves the team",
        "개인정보 지운 다음 엑셀로 내보내줘",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "korean-export-to-csv-is-not-a-data-share-review",
        "Exporting masked data to CSV writes a file; nothing leaves the team",
        "고객 정보 마스킹해서 CSV로 내보내줘",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "korean-export-to-a-backup-folder-is-not-a-data-share-review",
        "Exporting cleaned data to a backup folder keeps it inside the team",
        "고객 정보 지우고 백업 폴더로 내보내줘",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    # Owner decision 2026-10-16: personal data sent to a team inside the same
    # company stays internal, in English as in Korean. The first three name no
    # file-shaped carrier and held on main too; the rest offered or
    # dispatched the review on main.
    RoutingPrecisionCase(
        "pii-sent-to-the-dev-team-is-not-a-data-share-review",
        "Redacting PII before sending it to the dev team keeps it inside the company",
        "redact the pii and send it to the dev team",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "customer-list-shared-with-the-marketing-team-is-not-a-data-share-review",
        "Sharing a customer list with the marketing team keeps it inside the company",
        "share the customer list with the marketing team",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "emails-masked-before-sending-to-qa-is-not-a-data-share-review",
        "Masking emails before sending them to QA keeps them inside the company",
        "mask the emails before sending to qa",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "export-sent-to-the-dev-team-is-not-a-data-share-review",
        "Redacting an export before it goes to the dev team keeps it inside the company",
        "redact pii in the export before we send it to the dev team",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "dataset-shared-with-the-marketing-team-is-not-a-data-share-review",
        "Anonymizing a dataset before sharing it with the marketing team keeps it inside the company",
        "anonymize the dataset before sharing it with the marketing team",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "csv-sent-to-qa-is-not-a-data-share-review",
        "Redacting a CSV before it goes to QA keeps it inside the company",
        "redact pii in the csv before sending it to qa",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "records-uploaded-to-the-test-server-is-not-a-data-share-review",
        "De-identifying records before uploading them to the test server keeps them inside the company",
        "de-identify the records before we upload the file to the test server",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "csv-sent-to-a-coworker-is-not-a-data-share-review",
        "Redacting a CSV before sending it to a coworker keeps it inside the company",
        "redact pii from this csv before sending it to my coworker",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "dataset-shared-with-another-department-is-not-a-data-share-review",
        "Pseudonymizing a dataset before another department gets it keeps it inside the company",
        "pseudonymize the email addresses in the dataset before sharing it with another department",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "logs-shared-with-the-in-house-data-team-is-not-a-data-share-review",
        "Anonymizing logs before the in-house data team gets them keeps them inside the company",
        "anonymize the logs before we share them with the in-house data team",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "logs-uploaded-to-staging-is-not-a-data-share-review",
        "Redacting logs before uploading them to staging keeps them inside the company",
        "redact the logs before uploading them to staging",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "korean-dataset-shared-with-another-department-is-not-a-data-share-review",
        "Pseudonymizing personal data before another department gets it keeps it inside the company",
        "개인정보 가명 처리해서 다른 부서에 공유해줘",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "korean-customer-info-shared-with-a-colleague-is-not-a-data-share-review",
        "Anonymizing customer information before a colleague gets it keeps it inside the company",
        "고객 정보 익명화해서 동료에게 공유해줘",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "korean-upload-to-the-qa-environment-is-not-a-data-share-review",
        "Anonymizing personal data before uploading it to the QA environment keeps it inside the company",
        "개인정보 익명화해서 QA 환경에 올려줘",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    # Round-4: a party word right before a data container says whose records
    # the data holds, so the most common phrasing of an inside request names
    # no review. Main led its clarify with the review.
    RoutingPrecisionCase(
        "patient-csv-shared-with-our-qa-team-is-not-a-data-share-review",
        "Pseudonymizing a patient CSV before our QA team gets it keeps it inside the company",
        "pseudonymize the patient csv and share it with our qa team",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    # A place ends with its sentence, and a "-기 전에" clause is a step, not a
    # place. Main dispatched the review on the first and named it in the
    # clarify on the other two.
    RoutingPrecisionCase(
        "export-to-the-dev-team-then-an-urgent-remark-is-not-a-data-share-review",
        "Redacting an export for the dev team and saying it is urgent keeps it inside the company",
        "redact the pii in the export and send it to the dev team. it's urgent.",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "patient-csv-to-our-qa-team-then-a-please-is-not-a-data-share-review",
        "Pseudonymizing a patient CSV for our QA team and asking to hurry keeps it inside the company",
        "pseudonymize the patient csv and share it with our qa team. please hurry.",
        "answer_clarification",
        "",
        "data-share-review",
    ),
    RoutingPrecisionCase(
        "korean-mask-before-sending-to-the-dev-team-is-not-a-data-share-review",
        "Masking customer information before it goes to the dev team keeps it inside the company",
        "개발팀에 보내기 전에 고객 정보 마스킹해줘",
        "answer_clarification",
        "",
        "data-share-review",
    ),
)


# Positive-intervention corpus. These are real OMH-shaped turns where the router
# should still step in after the direct-answer fallback was added.
ROUTING_INTERVENTION_CASES: tuple[RoutingInterventionCase, ...] = (
    # `docs/INSTALLATION.md` tells users to type `ulw work …`, and only the
    # hyphenated label routed: `ulw` alone is an `ultrawork` trigger at score
    # 12, so it took the whole request and the second word was never read.
    # `ulw plan` reached `ultrawork` and `ulw qa` did too -- the opposite of
    # what was asked, silently. One case per suffix whose target differs from
    # `ultrawork`, because a suffix that happens to agree proves nothing.
    RoutingInterventionCase(
        'ulw-spaced-plan', 'The spaced ULW form reaches the plan engine',
        'ulw plan', 'dispatch', 'ralplan', 'forward_plan_to_selected_workflow', 'plan',
    ),
    RoutingInterventionCase(
        'ulw-spaced-qa', 'The spaced ULW form reaches the QA engine',
        'ulw qa', 'dispatch', 'ultraqa', 'dispatch_to_workflow', 'qa_review',
    ),
    # The other side: joining must not widen `ulw` itself. Alone it is still
    # the delivery engine, and a second word the catalog does not render as a
    # `ulw-` label is not joined into a skill name that does not exist.
    RoutingInterventionCase(
        'ulw-bare-stays-ultrawork', 'ULW alone still means the delivery engine',
        # The sigilled spelling, which is what the installation doc tells a
        # user to type. Bare `ulw` is three characters and trips the
        # raw-message-echo check by coincidence rather than by leaking.
        '$ulw', 'dispatch', 'ultrawork', 'forward_plan_to_selected_workflow', 'plan',
    ),
    RoutingInterventionCase(
        'ulw-unknown-suffix-not-joined', 'An unrendered second word is not joined',
        'ulw something', 'dispatch', 'ultrawork', 'ask_clarification', 'clarification',
    ),
    # The other half of #1638. A guard measured only on what it suppresses is
    # "improved" until nothing routes, so the same names that must not dispatch
    # inside an approval must still dispatch when they are actually asked for
    # -- including the sigilled form, which stays outside the gate by design.
    RoutingInterventionCase(
        'engine-entry-request-plan', 'Naming plan in a request still reaches plan',
        'plan the database migration for the billing service',
        'dispatch', 'plan', 'forward_plan_to_selected_workflow', 'plan',
    ),
    RoutingInterventionCase(
        'engine-entry-request-plan-sigil', 'A sigilled invocation stays outside the approval gate',
        '$plan the rollout even though the draft looks good',
        'dispatch', 'plan', 'forward_plan_to_selected_workflow', 'plan',
    ),
    RoutingInterventionCase(
        'engine-entry-request-ultrawork', 'Naming ultrawork in a request still reaches it',
        'ultrawork the auth refactor across the service',
        'dispatch', 'ultrawork', 'present_plan', 'plan',
    ),
    RoutingInterventionCase(
        'engine-entry-request-maestro', 'Naming maestro in a request still reaches it',
        'maestro the migration with two executors',
        'dispatch', 'maestro', 'forward_plan_to_selected_workflow', 'plan',
    ),
    # The approval matcher's word boundaries, pinned where they are
    # load-bearing. Both of these contain `this approved`, which the folded
    # helper's compact arm reads as `is approved` (`th|isapproved`), and in
    # both the winner rests on its own name -- so the name-shaped condition
    # does NOT release them and the boundary is the only thing keeping them
    # routing. Without these two, reverting the matcher leaves the corpus
    # green.
    RoutingInterventionCase(
        'engine-entry-approval-boundary-plan',
        'A request mentioning an approved thing is not an approval',
        'write the plan for this approved lifecycle experiment',
        'dispatch', 'plan', 'forward_plan_to_selected_workflow', 'plan',
    ),
    RoutingInterventionCase(
        'engine-entry-approval-boundary-frontend',
        'The same boundary holds for a route-mode skill',
        'add a retry to the frontend for this approved rollout',
        'dispatch', 'frontend', 'prepare_frontend_handoff', 'frontend_handoff',
    ),
    RoutingInterventionCase(
        'engine-entry-approval-carrying-a-real-request',
        'An approval carrying work with its own evidence still routes to that work',
        'the plan is fine, now do a workspace audit of the repo',
        'dispatch', 'workspace-audit', 'prepare_workspace_audit', 'workspace_audit',
    ),
    RoutingInterventionCase(
        'recall-saved-preference-incident', 'Expected saved memory enters evidence diagnosis',
        'Why was my saved response preference not used?',
        'dispatch', 'memory-sync', 'prepare_memory_sync', 'memory_curation',
    ),
    RoutingInterventionCase(
        'recall-narrative-complaint', 'A failed recall report is actionable without a question mark',
        'Memory was not used!',
        'dispatch', 'memory-sync', 'prepare_memory_sync', 'memory_curation',
    ),
    RoutingInterventionCase(
        'reference-direct-work-control',
        'Direct work invocation keeps its route',
        'Use $ulw-work to fix the build.',
        'dispatch',
        'ultrawork',
        'present_plan',
        'plan',
    ),
    RoutingInterventionCase(
        'reference-mixed-explicit-qa',
        'The explicit QA request wins over the quoted work example',
        '$ultraqa audit the dashboard. Example: "$ulw-work execute"',
        'dispatch',
        'ultraqa',
        'dispatch_to_workflow',
        'qa_review',
    ),
    RoutingInterventionCase(
        'reference-unfinished-after-direct-work',
        'An unfinished reference does not hide earlier executable work',
        '$ulw-work fix the build; example: "$ultraqa execute',
        'dispatch',
        'ultrawork',
        'present_plan',
        'plan',
    ),
    RoutingInterventionCase(
        "bound-design-feedback-opens-revision-action",
        "Trusted active iteration context binds a direction-feedback follow-up",
        "Could we take the current direction set through another feedback round?",
        "dispatch",
        "design-quality-gate",
        "revise_design_direction_iteration",
        "design_direction_iteration",
        active_design_direction_iteration={
            "iteration_id": "design-direction-iteration-1234567890abcdef",
            "revision_digest": "a" * 64,
        },
    ),
    # Re-pinned to clarify (shortlist-first, owner decision 2026-09-26): the winner's evidence is
    # tokens or a context-only guard, so the route asks; the declined winner, backend, leads
    # the shortlist.
    RoutingInterventionCase(
        "apple-glass-database-stays-with-backend",
        "Apple Glass database request does not select the Apple UI specialist",
        "Design the schema for our Apple Glass database.",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "backend",
    ),
    # Re-pinned to clarify (shortlist-first, owner decision 2026-09-26): the winner's evidence is
    # tokens or a context-only guard, so the route asks; the declined winner, frontend, leads
    # the shortlist.
    RoutingInterventionCase(
        "generic-ui-stays-with-frontend",
        "Generic UI request does not select the Apple UI specialist",
        "Improve the layout of our generic SaaS dashboard.",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "frontend",
    ),
    RoutingInterventionCase(
        "wcag-stays-with-accessibility-audit",
        "Generic WCAG request does not select the Apple UI specialist",
        "Run a WCAG 2.2 accessibility audit for this checkout.",
        "dispatch",
        "accessibility-audit",
        "prepare_accessibility_audit",
        "accessibility_audit",
        "accessibility-audit",
    ),
    RoutingInterventionCase(
        "screenshot-qa-stays-with-visual-qa",
        "Generic screenshot QA does not select the Apple UI specialist",
        "Check this screenshot QA for mobile clipping.",
        "dispatch",
        "visual-qa",
        "prepare_visual_qa",
        "visual_qa",
        "visual-qa",
    ),
    RoutingInterventionCase(
        "smooth-scroll-reaches-frontend",
        "A smooth-scroll request reaches the frontend workflow instead of falling back",
        "Add smooth scrolling to our marketing site.",
        "dispatch",
        "frontend",
        "prepare_frontend_handoff",
        "frontend_handoff",
        "frontend",
    ),
    RoutingInterventionCase(
        "parallax-hero-reaches-frontend",
        "A parallax hero request reaches the frontend workflow",
        "Add a parallax hero section to the landing page.",
        "dispatch",
        "frontend",
        "prepare_frontend_handoff",
        "frontend_handoff",
        "frontend",
    ),
    RoutingInterventionCase(
        "korean-scroll-animation-reaches-frontend",
        "A Korean scroll-animation request reaches the frontend workflow",
        "랜딩페이지에 스크롤 애니메이션 넣어줘.",
        "dispatch",
        "frontend",
        "prepare_frontend_handoff",
        "frontend_handoff",
        "frontend",
    ),
    # The design-reference lane (2026-10-07): chart theming, footer design,
    # a named style preset, and decorative text motion. On origin/main these
    # fell to clarify with an unrelated candidate (iac-change,
    # agent-evaluation, award-bar-score) or to the plain fallback.
    RoutingInterventionCase(
        "chart-theming-reaches-frontend",
        "Theming dashboard charts reaches the frontend workflow",
        "Style the dashboard charts so axis, grid and tooltip match our theme.",
        "dispatch",
        "frontend",
        "prepare_frontend_handoff",
        "frontend_handoff",
        "frontend",
    ),
    RoutingInterventionCase(
        "footer-design-reaches-frontend",
        "A footer design request reaches the frontend workflow",
        "Design a better footer for the marketing site.",
        "dispatch",
        "frontend",
        "prepare_frontend_handoff",
        "frontend_handoff",
        "frontend",
    ),
    RoutingInterventionCase(
        "neobrutalism-style-reaches-frontend",
        "A neobrutalism style request reaches the frontend workflow",
        "Make the site neobrutalism style.",
        "dispatch",
        "frontend",
        "prepare_frontend_handoff",
        "frontend_handoff",
        "frontend",
    ),
    RoutingInterventionCase(
        "split-text-animation-reaches-frontend",
        "A split-text animation request reaches the frontend workflow",
        "Add split text animation to the hero heading.",
        "dispatch",
        "frontend",
        "prepare_frontend_handoff",
        "frontend_handoff",
        "frontend",
    ),
    RoutingInterventionCase(
        "korean-neobrutalism-reaches-frontend",
        "A Korean neobrutalism request reaches the frontend workflow",
        "네오브루탈리즘 스타일로 바꿔줘.",
        "dispatch",
        "frontend",
        "prepare_frontend_handoff",
        "frontend_handoff",
        "frontend",
    ),
    RoutingInterventionCase(
        "korean-chart-style-reaches-frontend",
        "A Korean chart-style request reaches the frontend workflow",
        "차트 스타일 우리 디자인 시스템에 맞춰줘.",
        "dispatch",
        "frontend",
        "prepare_frontend_handoff",
        "frontend_handoff",
        "frontend",
    ),
    # One phrase and nothing else: the Korean marquee request names frontend
    # as the clarify candidate instead of falling back with no candidate.
    RoutingInterventionCase(
        "korean-logo-marquee-names-frontend",
        "A Korean logo-marquee request names frontend as the clarify candidate",
        "랜딩에 로고 마키 흐르게 해줘.",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "frontend",
    ),
    RoutingInterventionCase(
        "blender-product-render-stays-with-frontend",
        "A generic Blender product render does not select Apple design",
        "Create a 3D Blender product render with studio lighting for our landing page.",
        "dispatch",
        "frontend",
        "prepare_frontend_handoff",
        "frontend_handoff",
        "frontend",
    ),
    RoutingInterventionCase(
        "apple-design-display-invocation",
        "The public Apple design display invocation resolves to the specialist",
        "use omh-apple-design to review our iOS checkout",
        "dispatch",
        "apple-design",
        "prepare_design_orchestration",
        "apple_design",
        "apple-design",
    ),
    RoutingInterventionCase(
        "apple-style-3d-hero-reaches-specialist",
        "An explicit Apple-style 3D product hero selects Apple design before generic visual lanes",
        "Create an Apple-style 3D hero with a product render and studio lighting for our landing page.",
        "dispatch",
        "apple-design",
        "prepare_design_orchestration",
        "apple_design",
        "apple-design",
    ),
    RoutingInterventionCase(
        "apple-style-gsap-product-page-reaches-specialist",
        "Apple-style product-page GSAP motion selects Apple design before generic intake",
        "Create an Apple-style product page with GSAP scroll motion.",
        "dispatch",
        "apple-design",
        "prepare_design_orchestration",
        "apple_design",
        "apple-design",
    ),
    RoutingInterventionCase(
        "apple-style-liquid-logo-chrome-reaches-specialist",
        "Apple-style liquid-logo chrome selects Apple design before generic logo intake",
        "Create an Apple-style liquid-logo chrome logo for our product page.",
        "dispatch",
        "apple-design",
        "prepare_design_orchestration",
        "apple_design",
        "apple-design",
    ),
    RoutingInterventionCase(
        "apple-style-liquid-glass-web-controls-reaches-specialist",
        "Apple-style liquid-glass-js web controls select Apple design before generic glass intake",
        "Create Apple-style liquid-glass-js web controls for our product page.",
        "dispatch",
        "apple-design",
        "prepare_design_orchestration",
        "apple_design",
        "apple-design",
    ),
    # Re-pinned to clarify (shortlist-first, owner decision 2026-09-26): the winner's evidence is
    # tokens or a context-only guard, so the route asks; the declined winner, frontend, leads
    # the shortlist.
    RoutingInterventionCase(
        "generic-gsap-stays-with-frontend",
        "Generic GSAP animation does not select Apple design",
        "Use GSAP for our existing website animation timeline.",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "frontend",
    ),
    # Re-pinned to clarify (shortlist-first, owner decision 2026-09-26): the winner's evidence is
    # tokens or a context-only guard, so the route asks; the declined winner, ultrawork, leads
    # the shortlist.
    RoutingInterventionCase(
        "generic-liquid-logo-stays-with-planning",
        "Generic liquid-logo implementation does not select Apple design",
        "Implement a liquid logo in our existing website header.",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "ultrawork",
    ),
    RoutingInterventionCase(
        "generic-liquid-glass-stays-with-handoff",
        "Generic liquid-glass controls do not select Apple design",
        "Implement liquid glass controls in our existing website settings panel.",
        "dispatch",
        "ultrawork",
        "choose_executor",
        "handoff",
        "ultrawork",
    ),
    RoutingInterventionCase(
        "apple-hig-frontend-review-reaches-specialist",
        "Apple HIG plus frontend review selects the Apple specialist",
        "Review our iOS checkout against Apple HIG and prepare the frontend remediation",
        "dispatch",
        "apple-design",
        "prepare_design_orchestration",
        "apple_design",
        "apple-design",
    ),
    RoutingInterventionCase(
        "omh-docs-capability-catalog",
        "An OMH capability-catalog question reaches OMH self-documentation",
        "Explain the OMH capability catalog",
        "dispatch",
        "product-docs",
        "run_hermes_research",
        "web_research",
        "product-docs",
    ),
    RoutingInterventionCase(
        "omh-docs-memory-system",
        "An OMH memory-system question reaches OMH self-documentation",
        "Explain the OMH memory system",
        "dispatch",
        "product-docs",
        "run_hermes_research",
        "web_research",
        "product-docs",
    ),
    RoutingInterventionCase(
        "omh-docs-local-state",
        "An OMH local-state question reaches OMH self-documentation",
        "How does OMH store local state?",
        "dispatch",
        "product-docs",
        "run_hermes_research",
        "web_research",
        "product-docs",
    ),
    RoutingInterventionCase(
        "omh-docs-public-name-invocation",
        "A polite public omh-docs invocation resolves explicitly",
        "Please use omh-docs to explain OMH",
        "dispatch",
        "product-docs",
        "run_hermes_research",
        "web_research",
        "product-docs",
    ),
    RoutingInterventionCase(
        "omh-docs-model-routing",
        "An OMH model-routing question reaches OMH self-documentation",
        "explain OMH model routing",
        "dispatch",
        "product-docs",
        "run_hermes_research",
        "web_research",
        "product-docs",
    ),
    RoutingInterventionCase(
        "finance-relevance-clarification",
        "Finance vocabulary keeps the finance candidate",
        "DSO revenue cutoff",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "finance-analysis",
    ),
    RoutingInterventionCase(
        "finance-compact-relevance-clarification",
        "Compact ASC606 vocabulary keeps the finance candidate",
        "ASC606 model",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "finance-analysis",
    ),
    RoutingInterventionCase(
        "legal-relevance-clarification",
        "Compliance vocabulary keeps the legal candidate",
        "GDPR Article 35 DPIA",
        "fallback",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "legal-compliance-review",
    ),
    RoutingInterventionCase(
        "sales-relevance-clarification",
        "Qualification vocabulary keeps the sales candidate",
        "MEDDPICC qualification",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "sales-development",
    ),
    RoutingInterventionCase(
        "mixed-four-fifths-sales-clarification",
        "Mixed rule and sales vocabulary keeps only the owned sales candidate",
        "four-fifths rule ... MEDDPICC",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "sales-development",
    ),
    RoutingInterventionCase(
        "mixed-bloom-sales-clarification",
        "Mixed curriculum and sales vocabulary keeps only the owned sales candidate",
        "Bloom backward design ... MEDDPICC",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "sales-development",
    ),
    RoutingInterventionCase(
        "contracted-finance-negation-sales-clarification",
        "Contracted finance negation keeps the positive sales candidate",
        "don't assess ASC 606; use MEDDPICC",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "sales-development",
    ),
    RoutingInterventionCase(
        "curly-contracted-finance-negation-sales-clarification",
        "Curly contracted finance negation keeps the positive sales candidate",
        "doesn’t assess ASC 606; use MEDDPICC",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "sales-development",
    ),
    RoutingInterventionCase(
        "strong-rules-distill-owner",
        "Canonical rule distillation task evidence preserves the strong owner",
        "Distill repeated lessons into AGENTS.md rule candidates about the four-fifths rule",
        "dispatch",
        "rules-distill",
        "prepare_rules_distillation",
        "rules_distill",
        "rules-distill",
    ),
    RoutingInterventionCase(
        "strong-curriculum-design-owner",
        "Canonical curriculum task evidence preserves the strong owner",
        "Design a curriculum with learning objectives and Bloom backward design",
        "dispatch",
        "curriculum-design",
        "prepare_curriculum_design",
        "curriculum_design",
        "curriculum-design",
    ),
    RoutingInterventionCase(
        "visual-qa-current-viewports",
        "Current screenshot viewport review reaches visual QA",
        "visual-qa review these current screenshots at desktop and mobile viewports",
        "dispatch",
        "visual-qa",
        "prepare_visual_qa",
        "visual_qa",
    ),
    RoutingInterventionCase(
        "design-quality-gate-reference-review",
        "Reference-backed multi-surface review reaches design quality gate",
        "design-quality-gate review this landing page and deck against the reference",
        "dispatch",
        "design-quality-gate",
        "prepare_design_quality_gate",
        "design_quality_gate",
    ),
    RoutingInterventionCase(
        "frontend-dashboard-redesign",
        "Dashboard redesign reaches frontend",
        "frontend redesign this dashboard layout and design system",
        "dispatch",
        "frontend",
        "prepare_frontend_handoff",
        "frontend_handoff",
    ),
    RoutingInterventionCase(
        "tui-design-status-dashboard",
        "A TUI design request reaches the frontend craft lane",
        "tui design pass on this status dashboard so it stops looking like default widgets",
        "dispatch",
        "frontend",
        "prepare_frontend_handoff",
        "frontend_handoff",
    ),
    RoutingInterventionCase(
        "tui-layout-short-terminal",
        "A TUI layout restructure request reaches frontend, not visual QA",
        "terminal ui design for the log pane: restructure the layout so short terminals stop crushing it",
        "dispatch",
        "frontend",
        "prepare_frontend_handoff",
        "frontend_handoff",
    ),
    RoutingInterventionCase(
        "tui-check-stays-visual-qa",
        "A TUI render check stays on the visual-qa lane",
        "tui check this screen for clipped korean text",
        "dispatch",
        "visual-qa",
        "prepare_visual_qa",
        "visual_qa",
    ),
    RoutingInterventionCase(
        "accessibility-audit-checkout",
        "Checkout accessibility review reaches accessibility audit",
        "accessibility-audit this checkout flow for WCAG keyboard and screen reader behavior",
        "dispatch",
        "accessibility-audit",
        "prepare_accessibility_audit",
        "accessibility_audit",
    ),
    RoutingInterventionCase(
        "safe-feature-plan",
        "Safe feature work routes to planning",
        "how can I safely add a feature to this repo?",
        "dispatch",
        "ralplan",
        "present_plan",
        "plan",
    ),
    RoutingInterventionCase(
        "hindi-safe-feature-plan",
        "Hindi safe feature work routes to planning",
        "मैं इस परियोजना में सुरक्षित तरीके से नई सुविधा जोड़ना चाहता हूँ",
        "dispatch",
        "ralplan",
        "forward_plan_to_selected_workflow",
        "plan",
    ),
    RoutingInterventionCase(
        "source-acquisition",
        "Source acquisition routes to source finder",
        "github oss repo 찾아서 비교해줘",
        "dispatch",
        "source-finder",
        "prepare_source_finder_plan",
        "source_finder",
    ),
    RoutingInterventionCase(
        "hindi-source-finder",
        "Hindi source acquisition routes to source-finder",
        "इस विषय के शोध पत्र PDF और डेटा सेट ढूंढो",
        "dispatch",
        "source-finder",
        "prepare_source_finder_plan",
        "source_finder",
    ),
    RoutingInterventionCase(
        "hindi-paper-learning",
        "Hindi paper explanation routes to paper-learning",
        "इस शोध पत्र PDF को आसान स्तर पर समझाओ",
        "dispatch",
        "paper-learning",
        "prepare_paper_learning",
        "paper_learning",
    ),
    RoutingInterventionCase(
        "reported-customer-signal-still-dispatches",
        "A customer signal relayed as reported speech still reaches feedback-triage",
        "Customer feedback says the checkout click path is broken.",
        "dispatch",
        "feedback-triage",
        "triage_feedback",
        "feedback_triage",
    ),
    # The split gave the lookup phrases their own lane, so both sides need a
    # case: the deep cues must stay on the engine, an English lookup must reach
    # the new skill, and `websearch-setup` must keep the requests that are about
    # configuring web search rather than using it.
    RoutingInterventionCase(
        "deep-cue-stays-on-research-after-split",
        "A prior-art request stays on the research engine after the lookup lane split off",
        "prior art research before we write the spec",
        "dispatch",
        "research",
        "run_hermes_research",
        "web_research",
    ),
    RoutingInterventionCase(
        "english-lookup-reaches-web-research",
        "An English cited-lookup request reaches the web lookup lane",
        "web search the current rate limits and cite the sources",
        "dispatch",
        "web-research",
        "run_hermes_research",
        "web_research",
    ),
    # Re-pinned to clarify (shortlist-first, owner decision 2026-09-26): the winner's evidence is
    # tokens or a context-only guard, so the route asks; the declined winner, websearch-setup, leads
    # the shortlist.
    RoutingInterventionCase(
        "websearch-setup-outranks-the-lookup-lane",
        "Configuring web search still reaches websearch-setup rather than the lookup lane",
        "set up web search",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "websearch-setup",
    ),
    # Choosing which provider serves search is Hermes' `web.search_backend`
    # setting. Before the phrase joined the setup-guide list, this sentence
    # dispatched a live web lookup; now the route asks with the setup guide
    # leading the shortlist.
    RoutingInterventionCase(
        "web-search-backend-choice-reaches-websearch-setup",
        "Switching the web search backend leads with websearch-setup rather than running a lookup",
        "switch the web search backend to the free tier",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "websearch-setup",
    ),
    RoutingInterventionCase(
        "hindi-research",
        "Hindi current-source request routes to the web lookup lane",
        "वेब पर खोजकर ताज़ा स्रोतों के साथ सारांश दो",
        "dispatch",
        "web-research",
        "run_hermes_research",
        "web_research",
    ),
    RoutingInterventionCase(
        "hindi-issue-to-pr",
        "Hindi issue-to-PR preparation routes to GitHub event ops",
        "इस issue को PR के लिए तैयार करो",
        "dispatch",
        "github-event-ops",
        "prepare_github_event_ops_card",
        "github_event_ops",
    ),
    RoutingInterventionCase(
        "korean-source-dataset-github",
        "Korean source finder with dataset and GitHub routes to source-finder",
        "자료 출처 찾아줘 데이터셋이랑 깃허브까지",
        "dispatch",
        "source-finder",
        "prepare_source_finder_plan",
        "source_finder",
    ),
    RoutingInterventionCase(
        "korean-arxiv-link-source-finder",
        "Korean arxiv link requests route to source-finder",
        "arxiv 링크 찾아서 쉽게 설명해줘",
        "dispatch",
        "source-finder",
        "prepare_source_finder_plan",
        "source_finder",
    ),
    RoutingInterventionCase(
        "korean-paper-pdf-source-finder",
        "Korean paper PDF acquisition routes to source-finder",
        "논문 pdf 찾아서 쉽게 설명해줘",
        "dispatch",
        "source-finder",
        "prepare_source_finder_plan",
        "source_finder",
    ),
    RoutingInterventionCase(
        "korean-negated-paper-learning-source-finder",
        "Negated paper-learning mention routes to source-finder",
        "paper-learning 말고 논문 pdf 어디서 찾아?",
        "dispatch",
        "source-finder",
        "prepare_source_finder_plan",
        "source_finder",
    ),
    RoutingInterventionCase(
        "korean-negated-source-finder-paper-learning",
        "Negated source-finder mention routes to paper-learning",
        "source-finder 말고 이 논문 쉽게 설명해줘",
        "dispatch",
        "paper-learning",
        "prepare_paper_learning",
        "paper_learning",
    ),
    RoutingInterventionCase(
        "korean-attached-paper-beginner-learning",
        "Attached paper explanation routes to paper-learning",
        "첨부한 논문을 초보자 수준으로 풀어줘",
        "dispatch",
        "paper-learning",
        "prepare_paper_learning",
        "paper_learning",
    ),
    RoutingInterventionCase(
        "korean-paper-link-source-finder",
        "Korean paper-link acquisition routes to source-finder",
        "초보자용으로 볼 수 있는 논문 링크를 찾아줘",
        "dispatch",
        "source-finder",
        "prepare_source_finder_plan",
        "source_finder",
    ),
    RoutingInterventionCase(
        "korean-dataset-report-source-finder",
        "Korean dataset acquisition with downstream summary routes to source-finder",
        "데이터셋 찾아서 요약 리포트로 정리해줘",
        "dispatch",
        "source-finder",
        "prepare_source_finder_plan",
        "source_finder",
    ),
    RoutingInterventionCase(
        "korean-github-oss-source-finder",
        "Korean GitHub OSS acquisition routes to source-finder",
        "깃허브 오픈소스 저장소 찾아서 구조 분석해줘",
        "dispatch",
        "source-finder",
        "prepare_source_finder_plan",
        "source_finder",
    ),
    RoutingInterventionCase(
        "korean-public-presentation-source-finder",
        "Korean public presentation acquisition routes to source-finder",
        "공개 발표자료 찾아서 요약해줘",
        "dispatch",
        "source-finder",
        "prepare_source_finder_plan",
        "source_finder",
    ),
    RoutingInterventionCase(
        "korean-public-slide-source-finder",
        "Korean public slide acquisition routes to source-finder",
        "공개 슬라이드 자료 찾아서 핵심 요약해줘",
        "dispatch",
        "source-finder",
        "prepare_source_finder_plan",
        "source_finder",
    ),
    RoutingInterventionCase(
        "visual-summary",
        "Image-card requests route to img-summary",
        "make an image card for this PR",
        "dispatch",
        "img-summary",
        "prepare_visual_prompt_card",
        "img_summary",
    ),
    RoutingInterventionCase(
        "korean-meeting-vertical-image-card",
        "Korean meeting image-card requests route to img-summary",
        "이미지 생성해줘. 회의록을 세로 카드로 요약해줘",
        "dispatch",
        "img-summary",
        "prepare_visual_prompt_card",
        "img_summary",
    ),
    RoutingInterventionCase(
        "korean-photo-meeting-vertical-image-card",
        "Korean photo requests for meeting image cards route to img-summary",
        "사진 생성해줘. 회의록을 보기 좋은 세로 이미지로 정리해줘",
        "dispatch",
        "img-summary",
        "prepare_visual_prompt_card",
        "img_summary",
    ),
    RoutingInterventionCase(
        "korean-pretty-meeting-image-card",
        "Korean pretty meeting image requests route to img-summary",
        "회의록을 예쁜 이미지로 만들어줘",
        "dispatch",
        "img-summary",
        "prepare_visual_prompt_card",
        "img_summary",
    ),
    RoutingInterventionCase(
        "korean-github-pr-reviewer-image-card",
        "Korean GitHub PR reviewer image-card requests route to img-summary",
        "이 GitHub PR을 리뷰어용 이미지 카드로 만들어줘",
        "dispatch",
        "img-summary",
        "prepare_visual_prompt_card",
        "img_summary",
    ),
    RoutingInterventionCase(
        "korean-release-announcement-card",
        "Korean release announcement card requests route to img-summary",
        "릴리즈 노트를 announcement 카드로 만들어줘",
        "dispatch",
        "img-summary",
        "prepare_visual_prompt_card",
        "img_summary",
    ),
    RoutingInterventionCase(
        "korean-thumbnail-card",
        "Korean thumbnail requests route to img-summary",
        "썸네일 만들어줘",
        "dispatch",
        "img-summary",
        "prepare_visual_prompt_card",
        "img_summary",
    ),
    RoutingInterventionCase(
        "korean-release-notes-thumbnail",
        "Korean release notes thumbnail requests route to img-summary",
        "릴리즈 노트 썸네일로 만들어줘",
        "dispatch",
        "img-summary",
        "prepare_visual_prompt_card",
        "img_summary",
    ),
    RoutingInterventionCase(
        "korean-omh-loop-feature-image",
        "Korean OMH loop feature image requests route to img-summary",
        "OMH 루프 기능 소개 이미지 만들어줘",
        "dispatch",
        "img-summary",
        "prepare_visual_prompt_card",
        "img_summary",
    ),
    RoutingInterventionCase(
        "korean-image-generator-connector-readiness",
        "Korean missing image-generator connector requests route to toolbelt readiness",
        "이미지 생성 연결체가 없으면 어떤걸로 연결할지 물어봐줘",
        "dispatch",
        "toolbelt-readiness",
        "prepare_toolbelt_readiness",
        "toolbelt_readiness",
    ),
    RoutingInterventionCase(
        "korean-pr-image-tool-readiness",
        "Korean PR image request with missing generator routes to toolbelt-readiness",
        "PR 요약 이미지 만들고 싶어 근데 GPT image 연결 안 됐어",
        "dispatch",
        "toolbelt-readiness",
        "prepare_toolbelt_readiness",
        "toolbelt_readiness",
    ),
    RoutingInterventionCase(
        "korean-fal-key-image-tool-readiness",
        "Korean image-card request with missing FAL key routes to toolbelt-readiness",
        "회의록 이미지 카드 만들고 싶은데 FAL_KEY가 없어",
        "dispatch",
        "toolbelt-readiness",
        "prepare_toolbelt_readiness",
        "toolbelt_readiness",
    ),
    RoutingInterventionCase(
        "korean-unattached-image-tool-readiness",
        "Korean image tool unattached request routes to toolbelt-readiness",
        "이미지 만들고 싶은데 도구가 안 붙어있어",
        "dispatch",
        "toolbelt-readiness",
        "prepare_toolbelt_readiness",
        "toolbelt_readiness",
    ),
    RoutingInterventionCase(
        "korean-hermes-coding-team-only",
        "Korean Hermes-only coding team requests prepare runtime handoff",
        "Hermes만으로 코딩팀처럼 작업하고 싶어",
        "dispatch",
        "ultrawork",
        "show_runtime_handoff",
        "handoff",
    ),
    RoutingInterventionCase(
        "feedback-triage",
        "Product feedback routes to triage",
        "payment failures keep coming up from customer feedback",
        "dispatch",
        "feedback-triage",
        "triage_feedback",
        "feedback_triage",
    ),
    RoutingInterventionCase(
        "catalog-picker",
        "Workflow inventory opens the OMH picker",
        "what OMH workflows are available?",
        "dispatch",
        "oh-my-hermes",
        "choose_skill",
        "skill_picker",
    ),
    RoutingInterventionCase(
        "catalog-no-shell-approval-korean",
        "Korean omh list approval question opens the picker without shell",
        "Hermes가 omh list 승인하라고 하는데 굳이 쳐야해?",
        "dispatch",
        "oh-my-hermes",
        "choose_skill",
        "skill_picker",
    ),
    RoutingInterventionCase(
        "catalog-no-shell-workflows",
        "Workflow inventory with omh list mention opens the picker without shell",
        "what OMH workflows are available without running omh list?",
        "dispatch",
        "oh-my-hermes",
        "choose_skill",
        "skill_picker",
    ),
    RoutingInterventionCase(
        "slack-omh-command-picker",
        "Slack /omh entrypoint opens the OMH picker",
        "슬랙에서 /omh 치면 뭐가 떠야해?",
        "dispatch",
        "oh-my-hermes",
        "choose_skill",
        "skill_picker",
    ),
    RoutingInterventionCase(
        "partial-omh-preview-missing",
        "Partial ./ entrypoint issue opens command preview",
        "./ 쳤는데 omh가 안 떠",
        "dispatch",
        "oh-my-hermes",
        "show_command_preview",
        "command_preview",
    ),
    RoutingInterventionCase(
        "omh-risky-refactor-context",
        "OMH usage help opens a bounded context brief",
        "how do I use OMH for a risky refactor?",
        "dispatch",
        "oh-my-hermes",
        "show_context_brief",
        "context_brief",
    ),
    RoutingInterventionCase(
        "exact-ops-review-capability",
        "Exact operations workflow questions open ops review",
        "what can OMH do for ops-review?",
        "dispatch",
        "ops-review",
        "prepare_ops_review",
        "ops_review",
    ),
    RoutingInterventionCase(
        "exact-github-event-capability",
        "Exact GitHub event workflow questions open GitHub event ops",
        "what can OMH do for github-event-ops?",
        "dispatch",
        "github-event-ops",
        "prepare_github_event_ops_card",
        "github_event_ops",
    ),
    RoutingInterventionCase(
        "korean-pr-open-ci-failed",
        "Korean PR-opened CI-failed event opens GitHub event ops",
        "PR 열렸는데 CI 실패했어 정리해줘",
        "dispatch",
        "github-event-ops",
        "prepare_github_event_ops_card",
        "github_event_ops",
    ),
    RoutingInterventionCase(
        "english-github-issue-intake",
        "Explicit public-chat issue filing opens GitHub issue intake",
        "please file this as an issue: omh setup fails on Windows",
        "dispatch",
        "github-issue-intake",
        "prepare_github_issue_intake",
        "github_issue_intake",
    ),
    RoutingInterventionCase(
        "korean-github-issue-intake",
        "Korean explicit issue filing opens GitHub issue intake",
        "이 버그를 깃허브 이슈로 올려줘",
        "dispatch",
        "github-issue-intake",
        "prepare_github_issue_intake",
        "github_issue_intake",
    ),
    RoutingInterventionCase(
        "open-issue-event-stays-event-ops",
        "An already-open issue event with failing CI stays in GitHub event ops",
        "issue opened with failing ci",
        "dispatch",
        "github-event-ops",
        "prepare_github_event_ops_card",
        "github_event_ops",
    ),
    RoutingInterventionCase(
        "classification-only-stays-feedback-triage",
        "A classification-only report stays in feedback triage",
        "cluster these customer bug reports",
        "dispatch",
        "feedback-triage",
        "triage_feedback",
        "feedback_triage",
    ),
    RoutingInterventionCase(
        "english-long-document-contract",
        "A page-counted contract summary opens long-document reading",
        "summarize this 300-page vendor contract pdf and list every obligation with a deadline",
        "dispatch",
        "long-document-reading",
        "prepare_long_document_reading",
        "long_document_reading",
    ),
    RoutingInterventionCase(
        "english-long-document-page-count",
        "A stated page count past one read opens long-document reading",
        "this pdf is 300 pages, how do I get hermes to read it all?",
        "dispatch",
        "long-document-reading",
        "prepare_long_document_reading",
        "long_document_reading",
    ),
    RoutingInterventionCase(
        "english-long-document-manual",
        "A manual reading request opens long-document reading",
        "read this manual and tell me how to configure the device",
        "dispatch",
        "long-document-reading",
        "prepare_long_document_reading",
        "long_document_reading",
    ),
    RoutingInterventionCase(
        "english-long-document-bare-summary",
        "A bare document summary is a reading request, not file packaging",
        "summarize this document",
        "dispatch",
        "long-document-reading",
        "prepare_long_document_reading",
        "long_document_reading",
    ),
    RoutingInterventionCase(
        "korean-long-document-page-count",
        "Korean page-counted PDF summary opens long-document reading",
        "이 300페이지 PDF 요약해줘",
        "dispatch",
        "long-document-reading",
        "prepare_long_document_reading",
        "long_document_reading",
    ),
    RoutingInterventionCase(
        "japanese-long-document",
        "Japanese PDF summary opens long-document reading",
        "このPDFを要約して",
        "dispatch",
        "long-document-reading",
        "prepare_long_document_reading",
        "long_document_reading",
    ),
    RoutingInterventionCase(
        "chinese-long-document-contract",
        "Chinese contract summary opens long-document reading",
        "总结这份合同",
        "dispatch",
        "long-document-reading",
        "prepare_long_document_reading",
        "long_document_reading",
    ),
    RoutingInterventionCase(
        "long-pdf-into-slides-stays-materials",
        "A page-counted PDF that must become slides stays file packaging",
        "turn this 300 page pdf into slides",
        "dispatch",
        "materials-package",
        "prepare_material_package",
        "materials_package",
        "materials-package",
    ),
    RoutingInterventionCase(
        "office-document-action-items-stays-materials",
        "A Word document with action items stays file packaging",
        "summarize this Word document and extract action items",
        "dispatch",
        "materials-package",
        "prepare_material_package",
        "materials_package",
    ),
    RoutingInterventionCase(
        "paper-explanation-stays-paper-learning",
        "A paper explanation by level stays paper learning",
        "explain this paper at a beginner level",
        "dispatch",
        "paper-learning",
        "prepare_paper_learning",
        "paper_learning",
    ),
    RoutingInterventionCase(
        "english-application-threat-model-payment",
        "A threat model for a named service opens the application threat model",
        "build a threat model for our payment service architecture",
        "dispatch",
        "application-threat-model",
        "prepare_application_threat_model",
        "application_threat_model",
    ),
    RoutingInterventionCase(
        "english-application-threat-model-attacker-path",
        "An attacker path between two application components opens the application threat model",
        "how would an attacker get from the public API to the customer database",
        "dispatch",
        "application-threat-model",
        "prepare_application_threat_model",
        "application_threat_model",
    ),
    RoutingInterventionCase(
        "english-application-threat-model-attack-scenarios",
        "Attack scenarios for an application endpoint open the application threat model",
        "list the attack scenarios for our file upload endpoint",
        "dispatch",
        "application-threat-model",
        "prepare_application_threat_model",
        "application_threat_model",
    ),
    RoutingInterventionCase(
        "english-application-threat-model-abuse-cases",
        "Abuse cases for a user-facing flow open the application threat model",
        "walk through the abuse cases for our signup flow",
        "dispatch",
        "application-threat-model",
        "prepare_application_threat_model",
        "application_threat_model",
    ),
    # Re-pinned to clarify (shortlist-first, owner decision 2026-09-26): the winner's evidence is
    # tokens or a context-only guard, so the route asks; the declined winner, security-safety-review, leads
    # the shortlist.
    RoutingInterventionCase(
        "agent-surface-stays-security-safety-review",
        "The agent's own prompt and tool surface stays with the safety review, not the application model",
        "review the prompt injection and tool permission risks in this agent before we run it",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "security-safety-review",
    ),
    RoutingInterventionCase(
        "english-live-incident-outage-declaration",
        "An outage happening now opens the live incident lane, not a postmortem",
        "we have a production outage right now, declare severity and assign an incident commander",
        "dispatch",
        "live-incident-response",
        "prepare_live_incident_record",
        "live_incident_record",
    ),
    RoutingInterventionCase(
        "english-live-incident-commander-and-severity",
        "Asking who commands an active incident opens the live incident lane",
        "we are in an active incident, who is the incident commander and what is the severity",
        "dispatch",
        "live-incident-response",
        "prepare_live_incident_record",
        "live_incident_record",
    ),
    RoutingInterventionCase(
        "english-live-incident-timeline-start",
        "A service down now with a timeline to start opens the live incident lane",
        "the checkout service is down right now, start the incident timeline",
        "dispatch",
        "live-incident-response",
        "prepare_live_incident_record",
        "live_incident_record",
    ),
    RoutingInterventionCase(
        "english-live-incident-mitigation-and-recovery",
        "A temporary mitigation with recovery still to verify opens the live incident lane",
        "we applied a temporary mitigation to stop the bleeding, record it and verify recovery",
        "dispatch",
        "live-incident-response",
        "prepare_live_incident_record",
        "live_incident_record",
    ),
    RoutingInterventionCase(
        "english-live-incident-severity-level-declaration",
        "Declaring a severity level and opening the bridge opens the live incident lane",
        "declare a sev1 and open the incident bridge",
        "dispatch",
        "live-incident-response",
        "prepare_live_incident_record",
        "live_incident_record",
    ),
    # Re-pinned to clarify (shortlist-first, owner decision 2026-09-26): the winner's evidence is
    # tokens or a context-only guard, so the route asks; the declined winner, reliability-review, leads
    # the shortlist.
    RoutingInterventionCase(
        "closed-incident-stays-reliability-review",
        "A closed incident's notes and postmortem stay with the reliability review",
        "review the incident notes and the postmortem for last week's outage",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "reliability-review",
    ),
    RoutingInterventionCase(
        "support-case-outage-stays-support-operations",
        "One customer's outage reply stays with support operations, not the incident lane",
        "draft a calm reply for this login-outage customer and tell me whether it needs an engineering escalation",
        "dispatch",
        "support-operations",
        "prepare_support_operations",
        "support_operations",
    ),
    # Re-pinned to clarify (shortlist-first, owner decision 2026-09-26): the winner's evidence is
    # tokens or a context-only guard, so the route asks; the declined winner, deploy-and-monitor, leads
    # the shortlist.
    RoutingInterventionCase(
        "release-watch-stays-deploy-and-monitor",
        "Watching a healthy release stays with deploy-and-monitor, not the incident lane",
        "the deploy is healthy, monitor the error rate for an hour",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "deploy-and-monitor",
    ),
    # Re-pinned to clarify (shortlist-first, owner decision 2026-09-26): the winner's evidence is
    # tokens or a context-only guard, so the route asks; the declined winner, legal-compliance-review, leads
    # the shortlist.
    RoutingInterventionCase(
        "contract-compliance-review-stays-legal",
        "Reviewing a contract for compliance risk stays legal compliance review",
        "can you review this contract for compliance risk",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "legal-compliance-review",
    ),
    RoutingInterventionCase(
        "korean-contract-review-stays-legal",
        "Korean contract review stays legal compliance review",
        "이 계약서 검토해줘",
        "dispatch",
        "legal-compliance-review",
        "prepare_legal_compliance_review",
        "legal_compliance_review",
    ),
    # Re-pinned to clarify (shortlist-first, owner decision 2026-09-26): the winner's evidence is
    # tokens or a context-only guard, so the route asks; the declined winner, materials-package, leads
    # the shortlist.
    RoutingInterventionCase(
        "large-pdf-upload-failure-stays-materials",
        "A large PDF upload failure is a file problem, not a reading request",
        "large pdf upload keeps failing in production",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "materials-package",
    ),
    RoutingInterventionCase(
        "korean-large-pdf-upload-failure-stays-materials",
        "Korean large PDF upload failure stays file packaging",
        "대용량 pdf 업로드가 프로덕션에서 계속 실패해",
        "dispatch",
        "materials-package",
        "prepare_material_package",
        "materials_package",
    ),
    RoutingInterventionCase(
        "japanese-large-pdf-upload-failure-stays-materials",
        "Japanese large PDF upload failure stays file packaging",
        "大きなpdfのアップロードが本番で失敗し続ける",
        "dispatch",
        "materials-package",
        "prepare_material_package",
        "materials_package",
    ),
    RoutingInterventionCase(
        "chinese-large-pdf-upload-failure-stays-materials",
        "Chinese large PDF upload failure stays file packaging",
        "大pdf上传在生产环境一直失败",
        "dispatch",
        "materials-package",
        "prepare_material_package",
        "materials_package",
    ),
    # Re-pinned to clarify (shortlist-first, owner decision 2026-09-26): the winner's evidence is
    # tokens or a context-only guard, so the route asks; the declined winner, materials-package, leads
    # the shortlist.
    RoutingInterventionCase(
        "huge-pdf-crash-debug-stays-materials",
        "Debugging a viewer crash on a huge PDF stays file packaging",
        "a huge pdf crashed the viewer, debug it",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "materials-package",
    ),
    RoutingInterventionCase(
        "ocr-pipeline-document-stays-media-input",
        "Running a document through OCR stays media input",
        "process this document through the OCR pipeline",
        "dispatch",
        "media-input-operator",
        "prepare_media_input_card",
        "media_input",
    ),
    # Re-pinned to clarify (shortlist-first). FINDING: the intended skill on main,
    # ultrawork, is not on the shortlist: nothing claims a code edit once `style`
    # stopped being a code object. The case pins content-operator, which leads,
    # and that the route asks.
    RoutingInterventionCase(
        "style-guide-long-document-section-stays-ultrawork",
        "Adding a section to a long style guide stays a coding handoff",
        "our style guide is a long document, where do I add a section",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "content-operator",
    ),
    # Re-pinned to clarify (shortlist-first, owner decision 2026-09-26): the winner's evidence is
    # tokens or a context-only guard, so the route asks; the declined winner, code-review, leads
    # the shortlist.
    RoutingInterventionCase(
        "spec-page-year-stays-code-review",
        "A year near the word page is not a page count",
        "review the spec page we wrote in 2024",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "code-review",
    ),
    # The positive half of `kanban-worker-prompt-is-not-a-code-review`: a person
    # asking for bugs in a diff still reaches code-review when the diff hangs
    # off a kanban task. The review lane's hand-off decides who moves the card,
    # not who reads the code.
    RoutingInterventionCase(
        "kanban-task-diff-bug-hunt-stays-code-review",
        "A bug hunt over a kanban task's diff is still a code review",
        "find bugs in the diff attached to kanban task t_1a2b3c4d",
        "dispatch",
        "code-review",
        "prepare_review_or_followup_handoff",
        "review_check",
    ),
    RoutingInterventionCase(
        "exact-paper-learning-capability",
        "Exact paper workflow questions open paper learning",
        "what can OMH do for paper-learning?",
        "dispatch",
        "paper-learning",
        "prepare_paper_learning",
        "paper_learning",
    ),
    RoutingInterventionCase(
        "short-korean-paper-learning",
        "Short Korean paper explanation opens paper learning",
        "논문 쉽게 설명해줘",
        "dispatch",
        "paper-learning",
        "prepare_paper_learning",
        "paper_learning",
    ),
    RoutingInterventionCase(
        "korean-agent-status-slang",
        "Korean short status slang opens agent ops review",
        "뭔일임?",
        "dispatch",
        "agent-ops-review",
        "refresh_agent_ops_status",
        "agent_ops_review",
    ),
    RoutingInterventionCase(
        "korean-agent-status-briefing",
        "Korean work-status briefing opens agent ops review",
        "작업상황 브리핑해줘",
        "dispatch",
        "agent-ops-review",
        "refresh_agent_ops_status",
        "agent_ops_review",
    ),
    RoutingInterventionCase(
        "korean-agent-progress-question",
        "Korean progress question opens agent ops review",
        "어디까지 됐어?",
        "dispatch",
        "agent-ops-review",
        "refresh_agent_ops_status",
        "agent_ops_review",
    ),
    RoutingInterventionCase(
        "english-agent-status-update",
        "English status update opens agent ops review",
        "status update please",
        "dispatch",
        "agent-ops-review",
        "refresh_agent_ops_status",
        "agent_ops_review",
    ),
    RoutingInterventionCase(
        "english-agent-current-work",
        "English current-work question opens agent ops review",
        "what are you doing?",
        "dispatch",
        "agent-ops-review",
        "refresh_agent_ops_status",
        "agent_ops_review",
    ),
    RoutingInterventionCase(
        "todo-checklist-declare-request",
        "An explicit plan-checklist request declares the HUD checklist",
        "declare a plan checklist for this migration",
        "dispatch",
        "todo-checklist",
        "declare_plan_checklist",
        "todo_checklist",
    ),
    RoutingInterventionCase(
        "todo-checklist-sigil-request",
        "The `$todo` sigil reaches the checklist workflow",
        "$todo",
        "dispatch",
        "todo-checklist",
        "declare_plan_checklist",
        "todo_checklist",
    ),
    RoutingInterventionCase(
        "todo-checklist-show-request",
        "Asking for the plan todo reads the checklist rather than replanning",
        "show the plan todo",
        "dispatch",
        "todo-checklist",
        "declare_plan_checklist",
        "todo_checklist",
    ),
    RoutingInterventionCase(
        "running-work-board-natural-request",
        "A natural work-board request opens the observed running-work board",
        "show me the work board",
        "dispatch",
        "running-work-board",
        "show_running_work_board",
        "running_work_board",
    ),
    RoutingInterventionCase(
        "running-work-board-explicit-request",
        "An explicit running-work-board request opens the observed work board",
        "show my running work board",
        "dispatch",
        "running-work-board",
        "show_running_work_board",
        "running_work_board",
    ),
    RoutingInterventionCase(
        "running-work-board-models-request",
        "A running-model inventory request opens the observed work board",
        "what models are running",
        "dispatch",
        "running-work-board",
        "show_running_work_board",
        "running_work_board",
    ),
    RoutingInterventionCase(
        "korean-agent-status-now-slang",
        "Korean compact now-status slang opens agent ops review",
        "지금 뭐함",
        "dispatch",
        "agent-ops-review",
        "refresh_agent_ops_status",
        "agent_ops_review",
    ),
    RoutingInterventionCase(
        "korean-agent-status-doing-compact",
        "Korean compact doing-status question opens agent ops review",
        "뭐하고있어",
        "dispatch",
        "agent-ops-review",
        "refresh_agent_ops_status",
        "agent_ops_review",
    ),
    RoutingInterventionCase(
        "korean-agent-status-current-work",
        "Korean current-work question opens agent ops review",
        "현재 작업 뭐야",
        "dispatch",
        "agent-ops-review",
        "refresh_agent_ops_status",
        "agent_ops_review",
    ),
    RoutingInterventionCase(
        "korean-session-status",
        "Korean session status question opens agent ops review",
        "세션 상태 보여줘",
        "dispatch",
        "agent-ops-review",
        "refresh_agent_ops_status",
        "agent_ops_review",
    ),
    RoutingInterventionCase(
        "korean-work-history-status",
        "Korean current-work history question opens agent ops review",
        "내가 뭘 하고 있었는지 알려줘",
        "dispatch",
        "agent-ops-review",
        "refresh_agent_ops_status",
        "agent_ops_review",
    ),
    RoutingInterventionCase(
        "korean-agent-status-work-report",
        "Korean work-status report question opens agent ops review",
        "작업상황 보고해줘",
        "dispatch",
        "agent-ops-review",
        "refresh_agent_ops_status",
        "agent_ops_review",
    ),
    RoutingInterventionCase(
        "english-agent-current-work-now",
        "English doing-now status question opens agent ops review",
        "what are you doing now",
        "dispatch",
        "agent-ops-review",
        "refresh_agent_ops_status",
        "agent_ops_review",
    ),
    RoutingInterventionCase(
        "english-agent-going-on-rn",
        "English going-on status question opens agent ops review",
        "what is going on rn",
        "dispatch",
        "agent-ops-review",
        "refresh_agent_ops_status",
        "agent_ops_review",
    ),
    RoutingInterventionCase(
        "korean-pr-merged-status",
        "Korean PR merged-status question opens agent ops review",
        "PR 머지됐는지 확인해줘",
        "dispatch",
        "agent-ops-review",
        "prepare_coding_lane",
        "agent_ops_review",
    ),
    RoutingInterventionCase(
        "korean-ci-pass-status",
        "Korean CI pass-status question opens agent ops review",
        "CI 통과했어?",
        "dispatch",
        "agent-ops-review",
        "prepare_review_lane",
        "agent_ops_review",
    ),
    RoutingInterventionCase(
        "korean-feature-release-readiness",
        "Korean feature release-readiness question opens agent ops review",
        "이 기능 배포 준비됐어?",
        "dispatch",
        "agent-ops-review",
        "show_agent_ops_review",
        "agent_ops_review",
    ),
    RoutingInterventionCase(
        "korean-menu-bar-monitor-status",
        "Korean menu-bar monitor request opens agent ops review",
        "메뉴바 모니터 다시 켜줘",
        "dispatch",
        "agent-ops-review",
        "show_agent_ops_review",
        "agent_ops_review",
    ),
    RoutingInterventionCase(
        "loopable-project",
        "Loopable project requests open loop",
        "run a loop to improve first-run experience until install friction is lower",
        "dispatch",
        "loop",
        "choose_permission_profile",
        "loop",
    ),
    RoutingInterventionCase(
        "korean-first-success-loopable-project",
        "Korean first-success improvement requests open loop",
        "설치 후 첫 성공까지 막히는 부분을 계속 개선해줘",
        "dispatch",
        "loop",
        "choose_permission_profile",
        "loop",
    ),
    RoutingInterventionCase(
        "korean-first-value-loopable-project",
        "Korean first-value repo improvement opens loop",
        "현재 repo 설치 후 10분 안에 가치 못 느끼는 이유를 줄여가며 개선해줘",
        "dispatch",
        "loop",
        "choose_permission_profile",
        "loop",
    ),
    RoutingInterventionCase(
        "one-cycle-delivery",
        "One-cycle delivery requests open ultrawork's delivery capability",
        "turn this vague request into one cycle: research, plan, implement, review, and docs sync",
        "dispatch",
        "ultrawork",
        "choose_executor",
        "handoff",
    ),
    RoutingInterventionCase(
        "owner-learning-ulw-delivery",
        "ULW coding delivery opens the owner-choice handoff",
        "research, plan, implement, verify, and review this coding change in one cycle",
        "dispatch",
        "ultrawork",
        "choose_executor",
        "handoff",
    ),
    RoutingInterventionCase(
        "tdd-implementation-red-green",
        "TDD implementation requests open ultrawork's tests-first delivery",
        "tdd implementation of the retry queue: write tests first, then make them pass",
        "dispatch",
        "ultrawork",
        "choose_executor",
        "handoff",
    ),
    RoutingInterventionCase(
        "red-green-refactor-delivery",
        "Red-green delivery requests open ultrawork's tests-first delivery",
        "implement the parser with a failing test first, red-green",
        "dispatch",
        "ultrawork",
        "choose_executor",
        "handoff",
    ),
    RoutingInterventionCase(
        "korean-codex-issue-pr-start",
        "Korean Codex issue-to-PR start resolves the owner-selection surface",
        "코덱스로 이 이슈 PR 만들 수 있게 작업 시작해줘",
        "dispatch",
        "executor-runtime-readiness",
        "prepare_executor_runtime_readiness",
        "executor_runtime_readiness",
    ),
    RoutingInterventionCase(
        "korean-codex-start-current-task",
        "Korean Codex current-task starts check executor readiness",
        "코덱스로 이 작업 시작해줘",
        "dispatch",
        "executor-runtime-readiness",
        "prepare_executor_runtime_readiness",
        "executor_runtime_readiness",
    ),
    RoutingInterventionCase(
        "claude-code-open-this-work-korean",
        "Korean Claude Code open-current-work requests check executor readiness",
        "Claude Code로 이거 열어서 작업하게 해줘",
        "dispatch",
        "executor-runtime-readiness",
        "prepare_executor_runtime_readiness",
        "executor_runtime_readiness",
    ),
    RoutingInterventionCase(
        "hermes-direct-coding-owner-korean",
        "Korean Hermes direct coding owner requests check executor readiness",
        "Hermes한테 직접 코딩시키고 싶어",
        "dispatch",
        "executor-runtime-readiness",
        "prepare_executor_runtime_readiness",
        "executor_runtime_readiness",
    ),
    # Claude delegation postposition + verb: bare "클로드" stays out of the named
    # coding-agent phrase table (advisor/executor ambiguity), but the ambiguity
    # disappears once the name co-occurs with the unambiguous delegation verb
    # "맡겨" (see `_claude_bare_name_delegation_requested` in `routing/policy.py`).
    RoutingInterventionCase(
        "korean-claude-delegation-verb",
        "Korean 'have Claude take it' delegation opens the named coding-agent delivery lane",
        "클로드한테 이거 맡겨줘",
        "dispatch",
        "ultrawork",
        "choose_executor",
        "handoff",
    ),
    # "해줘" joined `CODING_DELIVERY_REQUEST_PHRASES`: safe only in composition
    # with an explicit named coding-agent phrase, which "codex" already supplies.
    RoutingInterventionCase(
        "codex-generic-haejwo-delivery",
        "A named-CLI 'just do it' request opens the named coding-agent delivery lane",
        "codex로 해줘",
        "dispatch",
        "ultrawork",
        "send_to_executor",
        "handoff",
    ),
    RoutingInterventionCase(
        "scheduled-research-blueprint",
        "Scheduled research requests open automation blueprint",
        "make a daily competitor research digest blueprint every morning",
        "dispatch",
        "automation-blueprint",
        "prepare_scheduled_ops_blueprint",
        "automation_blueprint",
    ),
    RoutingInterventionCase(
        "korean-competitor-news-automation",
        "Korean competitor news automation opens automation blueprint",
        "오늘 아침 경쟁사 뉴스 요약 자동화해줘",
        "dispatch",
        "automation-blueprint",
        "prepare_scheduled_ops_blueprint",
        "automation_blueprint",
    ),
    # Every phrasing this lane recognised named a cadence ("매일", "every
    # morning") or the word automation itself. A continuous watch names neither
    # and reached nothing -- in Korean, and in English too, which is why the
    # base corpus grows here rather than only the pack.
    RoutingInterventionCase(
        "korean-continuous-watch-automation",
        "A Korean continuous-watch request opens automation blueprint",
        "계속 감시해줘",
        "dispatch",
        "automation-blueprint",
        "prepare_scheduled_ops_blueprint",
        "automation_blueprint",
    ),
    RoutingInterventionCase(
        "keep-monitoring-opens-automation-blueprint",
        "An English continuous-watch request opens automation blueprint",
        "keep monitoring the build",
        "dispatch",
        "automation-blueprint",
        "prepare_scheduled_ops_blueprint",
        "automation_blueprint",
        "automation-blueprint",
        "high",
    ),
    RoutingInterventionCase(
        "watch-continuously-opens-automation-blueprint",
        "Watching continuously opens automation blueprint",
        "watch continuously and report any change",
        "dispatch",
        "automation-blueprint",
        "prepare_scheduled_ops_blueprint",
        "automation_blueprint",
    ),
    # A ja or zh sentence is one routing token, so a pack phrase sitting inside
    # a longer sentence earns the phrase credit but not the token credit an
    # exact-message match adds, and lands one tier below the English
    # equivalent above. Measured over every shipped pack: 84 of 91 ja phrases
    # and 81 of 88 zh phrases dispatch at high bare and clarify at medium once
    # a sentence surrounds them, while ko (space-segmented, NFKD-folded) barely
    # moves -- 895 of 962 phrases dispatch bare and 899 wrapped. The four cases
    # below record that difference as intended rather than leaving it
    # unpinned: the skill is still found and named, the tier is lower, and a
    # scoring change that lifts CJK credit must move these cases on purpose.
    # See #1607 for the scoring half, which is not taken here.
    RoutingInterventionCase(
        "japanese-pack-phrase-in-sentence-clarifies",
        "A Japanese pack phrase inside a sentence clarifies with the skill named",
        "ずっと監視して",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "automation-blueprint",
        "medium",
    ),
    RoutingInterventionCase(
        "chinese-pack-phrase-in-sentence-clarifies",
        "A Chinese pack phrase inside a sentence clarifies with the skill named",
        "持续监控这个服务",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "automation-blueprint",
        "medium",
    ),
    RoutingInterventionCase(
        "chinese-bare-pack-phrase-dispatches",
        "A bare Chinese pack phrase still dispatches at high confidence",
        "构建失败",
        "dispatch",
        "build-failure-triage",
        "prepare_build_failure_triage",
        "build_failure_triage",
        "build-failure-triage",
        "high",
    ),
    RoutingInterventionCase(
        "chinese-pack-phrase-in-question-clarifies",
        "The same Chinese phrase inside a question drops a tier, not a skill",
        "构建失败了怎么办",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "build-failure-triage",
        "medium",
    ),
    RoutingInterventionCase(
        "korean-morning-market-research",
        "Korean recurring market research opens research department",
        "아침마다 시장 리서치 요약해줘",
        "dispatch",
        "research-department",
        "prepare_research_department_plan",
        "research_department",
    ),
    RoutingInterventionCase(
        "korean-memory-pile-cleanup",
        "Korean accumulated memory cleanup opens memory curation",
        "메모리가 너무 쌓였는데 정리해줘",
        "dispatch",
        "memory-sync",
        "prepare_memory_sync",
        "memory_curation",
    ),
    RoutingInterventionCase(
        "korean-memory-stored-context",
        "Korean stored memory inspection opens memory curation",
        "내 메모리 뭐가 저장되어있는지 점검해줘",
        "dispatch",
        "memory-sync",
        "prepare_memory_sync",
        "memory_curation",
    ),
    RoutingInterventionCase(
        "korean-hermes-wrong-memory",
        "Korean wrong Hermes memory report opens memory curation",
        "Hermes가 내 기억을 잘못 기억하는 것 같아",
        "dispatch",
        "memory-sync",
        "prepare_memory_sync",
        "memory_curation",
    ),
    RoutingInterventionCase(
        "korean-wrong-stored-memory",
        "Korean wrong stored-memory report opens memory curation",
        "내가 말한 memory가 잘못 저장된 것 같아 정리해줘",
        "dispatch",
        "memory-sync",
        "prepare_memory_sync",
        "memory_curation",
    ),
    # memory-new capture vs memory-sync curation, both directions. A scope noun such as
    # `project memory` names where a fact lives, not what to do with it, so pairing it
    # with curation intent must stay curation. These are the overroute guards for the
    # split: without them a scope word silently flips a cleanup request into capture.
    # Memory-provider lifecycle vs native-memory curation. A memory provider is
    # an external backend whose reversibility is unknown until its identity,
    # hooks, retention, deletion, export, and switching are named; a memory
    # review is about claims Hermes already holds. Adoption, switching,
    # deletion, portability, and failure are the five question shapes that were
    # falling to curation, a capability toggle, or a file operation, and the
    # two curation cases below are the overroute guards for the split.
    RoutingInterventionCase(
        "memory-provider-adoption-readiness",
        "Memory-provider adoption reaches connector readiness",
        "memory provider adoption for yantrikdb",
        "dispatch",
        "external-connector-readiness",
        "prepare_external_connector_readiness",
        "external_connector_readiness",
    ),
    # A sixth shape: comparing providers. It reads as telemetry word for word --
    # "retrieval quality", "latency" -- so the ops guard claimed it outright and
    # the declared owner did not place at all.
    RoutingInterventionCase(
        "memory-provider-comparison-readiness",
        "Comparing memory providers reaches their declared owner, not the telemetry card",
        "compare memory providers on my own data for retrieval quality and latency",
        "dispatch",
        "external-connector-readiness",
        "prepare_external_connector_readiness",
        "external_connector_readiness",
    ),
    # The other half of that split: telemetry about operations, not about a
    # provider choice, keeps the card it always had.
    # Re-pinned to clarify (2026-09-26): the guard that carried this dispatch
    # measured under 3 right per wrong on the tuning set, so it is context-only
    # and the route asks; the declined winner, ops-observability-card, leads the shortlist.
    RoutingInterventionCase(
        "loop-run-telemetry-stays-ops-observability",
        "Token, cost, and latency of operations still reach the telemetry card",
        "show token cost and latency for the last week of loop runs",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "ops-observability-card",
    ),
    RoutingInterventionCase(
        "memory-provider-switch-readiness",
        "Switching memory providers reaches connector readiness",
        "Is it safe to switch memory provider from mem9 to remnic?",
        "dispatch",
        "external-connector-readiness",
        "prepare_external_connector_readiness",
        "external_connector_readiness",
    ),
    RoutingInterventionCase(
        "memory-provider-deletion-readiness",
        "Provider-side memory deletion reaches connector readiness, not a file operation",
        "delete provider memory for this workspace",
        "dispatch",
        "external-connector-readiness",
        "prepare_external_connector_readiness",
        "external_connector_readiness",
    ),
    RoutingInterventionCase(
        "memory-provider-portability-readiness",
        "Memory-provider portability reaches connector readiness",
        "check memory provider portability before adoption",
        "dispatch",
        "external-connector-readiness",
        "prepare_external_connector_readiness",
        "external_connector_readiness",
    ),
    RoutingInterventionCase(
        "memory-provider-sync-failure-readiness",
        "A failed provider synchronization reaches connector readiness",
        "memory provider sync failure keeps queueing",
        "dispatch",
        "external-connector-readiness",
        "prepare_external_connector_readiness",
        "external_connector_readiness",
    ),
    RoutingInterventionCase(
        "memory-provider-disable-not-capability-toggle",
        "Disabling a memory provider is a readiness question, not an OMH capability toggle",
        "disable memory provider without losing anything",
        "dispatch",
        "external-connector-readiness",
        "prepare_external_connector_readiness",
        "external_connector_readiness",
    ),
    RoutingInterventionCase(
        "memory-md-cleanup-stays-curation",
        "An ordinary MEMORY.md cleanup is not memory-provider readiness",
        "memory-sync inspect stale MEMORY.md claims",
        "dispatch",
        "memory-sync",
        "prepare_memory_sync",
        "memory_curation",
    ),
    RoutingInterventionCase(
        "remembered-context-review-stays-curation",
        "Reviewing remembered context is not memory-provider readiness",
        "review what you remember about me",
        "dispatch",
        "memory-sync",
        "prepare_memory_sync",
        "memory_curation",
    ),
    RoutingInterventionCase(
        "scoped-project-memory-cleanup",
        "Scoped project-memory cleanup stays memory curation",
        "clean up my stale project memory",
        "dispatch",
        "memory-sync",
        "prepare_memory_sync",
        "memory_curation",
    ),
    RoutingInterventionCase(
        "scoped-project-memory-review",
        "Scoped project-memory review stays memory curation",
        "review my stale project memory entries",
        "dispatch",
        "memory-sync",
        "prepare_memory_sync",
        "memory_curation",
    ),
    RoutingInterventionCase(
        "scoped-project-memory-stale-check",
        "Scoped project-memory stale check stays memory curation",
        "check my project memory for stale claims",
        "dispatch",
        "memory-sync",
        "prepare_memory_sync",
        "memory_curation",
    ),
    RoutingInterventionCase(
        "scoped-product-memory-conflict-audit",
        "Scoped product-memory conflict audit stays memory curation",
        "audit product memory for conflicting facts",
        "dispatch",
        "memory-sync",
        "prepare_memory_sync",
        "memory_curation",
    ),
    RoutingInterventionCase(
        "korean-scoped-project-memory-cleanup",
        "Korean scoped project-memory cleanup stays memory curation",
        "프로젝트 기억 정리해줘",
        "dispatch",
        "memory-sync",
        "prepare_memory_sync",
        "memory_curation",
    ),
    RoutingInterventionCase(
        "korean-scoped-product-memory-check",
        "Korean scoped product-memory check stays memory curation",
        "제품 기억 점검해줘",
        "dispatch",
        "memory-sync",
        "prepare_memory_sync",
        "memory_curation",
    ),
    RoutingInterventionCase(
        "project-memory-capture",
        "Scoped project-memory capture still opens new-memory capture",
        "add this decision to project memory",
        "dispatch",
        "memory-new",
        "prepare_memory_new",
        "memory_candidate",
    ),
    RoutingInterventionCase(
        "korean-project-memory-capture",
        "Korean project-memory save opens new-memory capture",
        "프로젝트 메모리 저장",
        "dispatch",
        "memory-new",
        "prepare_memory_new",
        "memory_candidate",
    ),
    RoutingInterventionCase(
        "korean-memory-add-capture",
        "Korean add-memory request opens new-memory capture",
        "기억 추가",
        "dispatch",
        "memory-new",
        "prepare_memory_new",
        "memory_candidate",
    ),
    RoutingInterventionCase(
        "korean-omh-response-slow",
        "Korean OMH response slowness opens ops observability",
        "OMH가 너무 느려",
        "dispatch",
        "ops-observability-card",
        "prepare_ops_observability_card",
        "ops_observability",
    ),
    RoutingInterventionCase(
        "korean-token-usage-high",
        "Korean token usage concern opens ops observability",
        "토큰을 너무 많이 쓰는 것 같아",
        "dispatch",
        "ops-observability-card",
        "prepare_ops_observability_card",
        "ops_observability",
    ),
    RoutingInterventionCase(
        "korean-cost-check",
        "Korean cost check opens ops observability",
        "비용이 많이 나오는지 확인해줘",
        "dispatch",
        "ops-observability-card",
        "prepare_ops_observability_card",
        "ops_observability",
    ),
    # Token and cost usage said in Korean, which the bare 토큰 and 비용
    # triggers carried before they were dropped for dispatching auth-token and
    # function-cost requests.
    RoutingInterventionCase(
        "korean-token-usage-monitoring",
        "Korean token-usage monitoring opens ops observability",
        "토큰 사용량 모니터링해줘",
        "dispatch",
        "ops-observability-card",
        "prepare_ops_observability_card",
        "ops_observability",
    ),
    RoutingInterventionCase(
        "korean-token-consumption-question",
        "A Korean question about token consumption opens ops observability",
        "토큰 소비가 왜 이렇게 많아?",
        "dispatch",
        "ops-observability-card",
        "prepare_ops_observability_card",
        "ops_observability",
    ),
    RoutingInterventionCase(
        "korean-token-burn-rate",
        "A Korean complaint about token burn opens ops observability",
        "토큰 소모가 너무 빨라",
        "dispatch",
        "ops-observability-card",
        "prepare_ops_observability_card",
        "ops_observability",
    ),
    RoutingInterventionCase(
        "korean-token-usage-trend",
        "A Korean request for the token-usage trend opens ops observability",
        "토큰 사용 추이 알려줘",
        "dispatch",
        "ops-observability-card",
        "prepare_ops_observability_card",
        "ops_observability",
    ),
    RoutingInterventionCase(
        "korean-api-cost-monitoring",
        "Korean API-cost monitoring opens ops observability",
        "API 비용 모니터링해줘",
        "dispatch",
        "ops-observability-card",
        "prepare_ops_observability_card",
        "ops_observability",
    ),
    RoutingInterventionCase(
        "korean-token-usage-per-feature",
        "A modifier before the usage phrase does not stop a Korean usage question",
        "기능별 토큰 사용량 알려줘",
        "dispatch",
        "ops-observability-card",
        "prepare_ops_observability_card",
        "ops_observability",
    ),
    RoutingInterventionCase(
        "korean-token-usage-per-function",
        "Token usage per function, asked in Korean, opens ops observability",
        "함수별 토큰 사용량 알려줘",
        "dispatch",
        "ops-observability-card",
        "prepare_ops_observability_card",
        "ops_observability",
    ),
    RoutingInterventionCase(
        "korean-token-usage-noun-phrase-question",
        "A Korean sentence that ends on the usage phrase asks for it",
        "이번 주 토큰 사용량",
        "dispatch",
        "ops-observability-card",
        "prepare_ops_observability_card",
        "ops_observability",
    ),
    RoutingInterventionCase(
        "korean-cost-monitoring-with-spaced-verb",
        "해줘 said apart from its noun still ends a Korean monitoring request",
        "비용 모니터링 해줘",
        "dispatch",
        "ops-observability-card",
        "prepare_ops_observability_card",
        "ops_observability",
    ),
    # One sentence per report predicate the token arm does not also read, so
    # each stem in `_KOREAN_USAGE_REPORT_PREDICATES` is pinned on its own, plus
    # 해 줘 written as two words, trailing punctuation after a spaced ending, and
    # the auxiliary 주다 written apart after any verb, the standard spelling.
    RoutingInterventionCase(
        "korean-token-usage-check",
        "Checking token usage, asked in Korean, opens ops observability",
        "토큰 소모량 확인해줘",
        "dispatch",
        "ops-observability-card",
        "prepare_ops_observability_card",
        "ops_observability",
    ),
    RoutingInterventionCase(
        "korean-token-usage-compare-by-model",
        "Comparing token usage by model, asked in Korean, opens ops observability",
        "모델별 토큰 사용량 비교해줘",
        "dispatch",
        "ops-observability-card",
        "prepare_ops_observability_card",
        "ops_observability",
    ),
    RoutingInterventionCase(
        "korean-token-usage-track",
        "Tracking token consumption, asked in Korean, opens ops observability",
        "토큰 소비량 추적해줘",
        "dispatch",
        "ops-observability-card",
        "prepare_ops_observability_card",
        "ops_observability",
    ),
    RoutingInterventionCase(
        "korean-token-usage-how-much",
        "Asking how much token usage there is opens ops observability",
        "토큰 사용량 얼마야",
        "dispatch",
        "ops-observability-card",
        "prepare_ops_observability_card",
        "ops_observability",
    ),
    RoutingInterventionCase(
        "korean-token-usage-how-is-it",
        "Asking how token consumption looks opens ops observability",
        "이번 주 토큰 소모량 어때?",
        "dispatch",
        "ops-observability-card",
        "prepare_ops_observability_card",
        "ops_observability",
    ),
    RoutingInterventionCase(
        "korean-token-usage-report-noun",
        "A Korean token-usage report named as the last word opens ops observability",
        "토큰 사용량 주간 리포트",
        "dispatch",
        "ops-observability-card",
        "prepare_ops_observability_card",
        "ops_observability",
    ),
    RoutingInterventionCase(
        "korean-token-usage-show-polite",
        "A polite show-me ending, which the token arm does not read, still opens ops observability",
        "토큰 소비량 보여주세요",
        "dispatch",
        "ops-observability-card",
        "prepare_ops_observability_card",
        "ops_observability",
    ),
    RoutingInterventionCase(
        "korean-token-usage-compare-spaced-with-punctuation",
        "A spaced ending followed by punctuation still ends a Korean usage request",
        "토큰 소모량 비교 해줘!",
        "dispatch",
        "ops-observability-card",
        "prepare_ops_observability_card",
        "ops_observability",
    ),
    RoutingInterventionCase(
        "korean-token-usage-track-two-word-ending",
        "해 줘 written as two words still ends a Korean usage request",
        "토큰 사용량 추적 해 줘",
        "dispatch",
        "ops-observability-card",
        "prepare_ops_observability_card",
        "ops_observability",
    ),
    RoutingInterventionCase(
        "korean-token-usage-show-auxiliary-apart",
        "보여 주세요, with the auxiliary written apart, still ends a Korean usage request",
        "토큰 사용량 보여 주세요",
        "dispatch",
        "ops-observability-card",
        "prepare_ops_observability_card",
        "ops_observability",
    ),
    RoutingInterventionCase(
        "korean-token-usage-tell-auxiliary-apart",
        "알려 줘, with the auxiliary written apart, still ends a Korean usage request",
        "토큰 사용량 알려 줘",
        "dispatch",
        "ops-observability-card",
        "prepare_ops_observability_card",
        "ops_observability",
    ),
    RoutingInterventionCase(
        "korean-token-usage-check-auxiliary-apart",
        "확인해 주세요 reads its predicate from the verb before the auxiliary",
        "토큰 소모량 확인해 주세요",
        "dispatch",
        "ops-observability-card",
        "prepare_ops_observability_card",
        "ops_observability",
    ),
    # Building or fixing something that touches token usage stays a coding
    # request: the usage phrase does not count under a work predicate.
    RoutingInterventionCase(
        "korean-token-usage-api-build-stays-with-handoff",
        "Building a token-usage API stays a coding handoff",
        "토큰 사용량 API 만들어줘",
        "dispatch",
        "ultrawork",
        "choose_executor",
        "handoff",
        "ultrawork",
    ),
    RoutingInterventionCase(
        "korean-token-usage-bug-fix-stays-with-handoff",
        "Fixing a token-usage bug stays a coding handoff",
        "토큰 사용량 버그 고쳐줘",
        "dispatch",
        "ultrawork",
        "choose_executor",
        "handoff",
        "ultrawork",
    ),
    RoutingInterventionCase(
        "korean-update-version-unchanged",
        "Korean update-version confusion opens doctor",
        "update 했는데 버전이 그대로야",
        "dispatch",
        "doctor",
        "run_local_operator_check",
        "doctor_health",
    ),
    RoutingInterventionCase(
        "korean-update-health-uncertain",
        "Korean update-health uncertainty opens doctor",
        "omh update 했는데 잘 된건지 모르겠어",
        "dispatch",
        "doctor",
        "run_local_operator_check",
        "doctor_health",
    ),
    RoutingInterventionCase(
        "korean-first-run-confusing",
        "Korean first-run confusion opens quickstart",
        "설치 후 첫 실행이 헷갈려",
        "dispatch",
        "oh-my-hermes",
        "show_quickstart",
        "quickstart",
    ),
    RoutingInterventionCase(
        "korean-omh-generic-answer-fallback",
        "Korean OMH generic-answer fallback records missed route",
        "디스코드에서 OMH가 자꾸 일반 답변으로 빠져",
        "dispatch",
        "workflow-learning",
        "record_missed_route",
        "workflow_learning",
    ),
    RoutingInterventionCase(
        "korean-router-wrong-choice",
        "Korean wrong-router-choice feedback records missed route",
        "라우터가 잘못 고른 것 같아",
        "dispatch",
        "workflow-learning",
        "record_missed_route",
        "workflow_learning",
    ),
    RoutingInterventionCase(
        "korean-agent-cannot-see-omh-context",
        "Korean agent OMH context-loss feedback records missed route",
        "agent가 omh context를 못 보는 것 같아",
        "dispatch",
        "workflow-learning",
        "record_missed_route",
        "workflow_learning",
    ),
    RoutingInterventionCase(
        "korean-remembered-context-review",
        "Korean remembered-context inspection opens memory curation",
        "내 기억에 뭐 저장돼있는지 검토해줘",
        "dispatch",
        "memory-sync",
        "prepare_memory_sync",
        "memory_curation",
    ),
    RoutingInterventionCase(
        "korean-install-health-exact",
        "Korean install-health exact question opens doctor",
        "설치가 제대로 됐는지 확인해줘",
        "dispatch",
        "doctor",
        "run_local_operator_check",
        "doctor_health",
    ),
    RoutingInterventionCase(
        "korean-codex-session-liveness",
        "Korean Codex session-liveness question resolves the owner-selection surface",
        "codex 세션이 살아있는지 확인해줘",
        "dispatch",
        "executor-runtime-readiness",
        "prepare_executor_runtime_readiness",
        "executor_runtime_readiness",
    ),
    RoutingInterventionCase(
        "korean-codex-current-activity-status",
        "Korean Codex current-activity questions resolve the owner-selection surface",
        "코덱스가 지금 뭐하고있는지 알려줘",
        "dispatch",
        "executor-runtime-readiness",
        "prepare_executor_runtime_readiness",
        "executor_runtime_readiness",
    ),
    RoutingInterventionCase(
        "korean-pr-review-comment-merge-readiness",
        "Korean PR review-comment merge readiness opens coding status",
        "이 PR 리뷰어 코멘트 반영됐는지 보고 머지 준비해줘",
        "dispatch",
        "ultrawork",
        "show_coding_handoff_status",
        "handoff",
    ),
    RoutingInterventionCase(
        "workflow-learning",
        "Workflow improvement requests open workflow learning",
        "turn this failed workflow into a skill improvement proposal",
        "dispatch",
        "workflow-learning",
        "audit_learning_readiness",
        "workflow_learning",
    ),
    RoutingInterventionCase(
        "korean-workflow-trace-skill-improvement",
        "Korean workflow trace requests open workflow learning",
        "workflow trace 보고 다음에 스킬 고칠점 알려줘",
        "dispatch",
        "workflow-learning",
        "audit_learning_readiness",
        "workflow_learning",
    ),
    RoutingInterventionCase(
        "missed-workflow-future-feedback",
        "Future missed workflow feedback records a learning trace",
        "내가 방금 부탁한 이미지 생성에 OMH를 안 쓴 것 같은데 다음엔 쓰게 해줘",
        "dispatch",
        "workflow-learning",
        "record_missed_route",
        "workflow_learning",
    ),
    RoutingInterventionCase(
        "korean-test-until-pass-coding",
        "Korean test-as-stop-signal coding opens ultrawork's delivery capability",
        "테스트 통과할때까지 고쳐줘",
        "dispatch",
        "ultrawork",
        "choose_executor",
        "handoff",
    ),
    RoutingInterventionCase(
        "korean-setup-output-improvement",
        "Korean setup output improvement stays in the delivery lane",
        "setup 로그가 너무 어렵다 개선해줘",
        "dispatch",
        "ultrawork",
        "choose_executor",
        "handoff",
    ),
    RoutingInterventionCase(
        "korean-hud-menubar-restart",
        "Korean HUD menu bar restart opens agent ops review",
        "상단바 hud 다시 켜고싶어",
        "dispatch",
        "agent-ops-review",
        "show_agent_ops_review",
        "agent_ops_review",
    ),
    RoutingInterventionCase(
        "korean-menubar-monitor-reopen",
        "Korean menu bar monitor reopen opens agent ops review",
        "메뉴바 모니터링 다시 띄워줘",
        "dispatch",
        "agent-ops-review",
        "show_agent_ops_review",
        "agent_ops_review",
    ),
    RoutingInterventionCase(
        "korean-wrong-memory-review",
        "Korean 'you have me wrong, let's check' routes to memory curation",
        "네가 나에 대해 잘못 알고있는게 있는것같아, 같이 점검해보자",
        "dispatch",
        "memory-sync",
        "prepare_memory_sync",
        "memory_curation",
    ),
    RoutingInterventionCase(
        "korean-stored-profile-fix",
        "Korean 'check and fix my stored profile info' routes to memory curation",
        "너한테 저장된 내 프로필 정보 확인하고 틀린 건 고치고 싶어",
        "dispatch",
        "memory-sync",
        "prepare_memory_sync",
        "memory_curation",
    ),
    RoutingInterventionCase(
        "korean-explicit-codex-delegation-bugfix",
        "Explicit codex delegation routes to executor runtime readiness instead of feedback triage",
        "로그인 500 에러 버그 코덱스한테 시켜서 고쳐줘",
        "dispatch",
        "executor-runtime-readiness",
        "prepare_executor_runtime_readiness",
        "executor_runtime_readiness",
    ),
    RoutingInterventionCase(
        "korean-keep-running-until-done",
        "Korean 'keep running until this task is done' routes to loop",
        "이 작업 끝날 때까지 계속 돌려줘",
        "dispatch",
        "loop",
        "ask_goal_boundary",
        "loop",
    ),
    RoutingInterventionCase(
        "korean-idea-to-service-deploy",
        "Korean 'turn this idea into a service and deploy' routes to idea-to-deploy",
        "아이디어가 있는데 이거 서비스로 만들어서 배포까지 가보자",
        "dispatch",
        "idea-to-deploy",
        "present_app_delivery_loop",
        "app_delivery_loop",
    ),
    RoutingInterventionCase(
        "korean-agents-idle-status-freeform",
        "Korean freeform agent idle/status ask opens agent ops review",
        "에이전트들 지금 놀고 있는 거 아니지? 상태 좀",
        "dispatch",
        "agent-ops-review",
        "refresh_agent_ops_status",
        "agent_ops_review",
    ),
    RoutingInterventionCase(
        "english-anything-still-running-status",
        "English 'anything still running, quick status' opens agent ops review",
        "is anything still running on your side? give me a quick status",
        "dispatch",
        "agent-ops-review",
        "refresh_agent_ops_status",
        "agent_ops_review",
    ),
    RoutingInterventionCase(
        "korean-update-broken-install-check",
        "Korean 'updated but broken, check install status' opens doctor",
        "omh 업데이트했는데 뭔가 이상해, 설치 상태 좀 점검해줘",
        "dispatch",
        "doctor",
        "run_local_operator_check",
        "doctor_health",
    ),
    RoutingInterventionCase(
        "english-model-setup-guide",
        "English model setup request opens the model setup guide",
        "set up my models",
        "dispatch",
        "model-setup",
        "run_setup_guide",
        "setup_guide",
    ),
    RoutingInterventionCase(
        "english-explain-model-setup-guide",
        "An explanatory model setup request still opens the model setup guide",
        "explain how to set up my models",
        "dispatch",
        "model-setup",
        "run_setup_guide",
        "setup_guide",
    ),
    RoutingInterventionCase(
        "korean-model-setup-guide",
        "Korean model setup request opens the model setup guide",
        "모델 설정 도와줘",
        "dispatch",
        "model-setup",
        "run_setup_guide",
        "setup_guide",
    ),
    RoutingInterventionCase(
        "korean-model-chain-interview",
        "Korean per-category model setting request opens the model setup guide",
        "카테고리별 모델 세팅 바꿔줘",
        "dispatch",
        "model-setup",
        "run_setup_guide",
        "setup_guide",
    ),
    RoutingInterventionCase(
        "english-model-chain-edit",
        "English model chains edit request opens the model setup guide",
        "change my model chains for the quick category",
        "dispatch",
        "model-setup",
        "run_setup_guide",
        "setup_guide",
    ),
    RoutingInterventionCase(
        "korean-provider-switch-guide",
        "Korean provider switch request opens the model setup guide",
        "프로바이더 전환",
        "dispatch",
        "model-setup",
        "run_setup_guide",
        "setup_guide",
    ),
    RoutingInterventionCase(
        "korean-account-relogin-guide",
        "Korean quota-exhausted account relogin opens the model setup guide",
        "한도초과돼서 다른 계정으로 로그인해야 해",
        "dispatch",
        "model-setup",
        "run_setup_guide",
        "setup_guide",
    ),
    RoutingInterventionCase(
        "english-provider-quota-guide",
        "English provider quota exhaustion opens the model setup guide",
        "provider quota exceeded",
        "dispatch",
        "model-setup",
        "run_setup_guide",
        "setup_guide",
    ),
    RoutingInterventionCase(
        "english-parallel-tools-update-guide",
        "English parallel-tools update request opens the parallel tools guide",
        "update hermes for parallel tools",
        "dispatch",
        "parallel-tools",
        "run_setup_guide",
        "setup_guide",
    ),
    RoutingInterventionCase(
        "korean-hermes-update-check-guide",
        "Korean hermes update check opens the parallel tools guide",
        "헤르메스 업데이트 확인해줘",
        "dispatch",
        "parallel-tools",
        "run_setup_guide",
        "setup_guide",
    ),
    RoutingInterventionCase(
        "english-websearch-cost-guide",
        "English cheaper web search request opens the web search setup guide",
        "make web search cheaper",
        "dispatch",
        "websearch-setup",
        "run_setup_guide",
        "setup_guide",
    ),
    RoutingInterventionCase(
        "korean-websearch-cost-guide",
        "Korean cheaper web search request opens the web search setup guide",
        "웹 검색 싸게 만들어줘",
        "dispatch",
        "websearch-setup",
        "run_setup_guide",
        "setup_guide",
    ),
    # Setup and cost phrasing reaches the setup guide; before these phrases
    # joined the setup-guide list each one dispatched a live web lookup.
    # `configure web search` counts only as the whole request: said bare it
    # dispatches, and with a courtesy word or trailing punctuation around it
    # the route asks with the setup guide leading. The cost and free-tier
    # phrases are built from held-back pricing words, so they ask too.
    RoutingInterventionCase(
        "configure-web-search-opens-the-setup-guide",
        "Configuring web search opens the web search setup guide instead of a lookup",
        "configure web search",
        "dispatch",
        "websearch-setup",
        "run_setup_guide",
        "setup_guide",
    ),
    RoutingInterventionCase(
        "courteous-configure-web-search-leads-with-the-setup-guide",
        "A courteous request to configure web search leads with websearch-setup rather than running a lookup",
        "please configure web search",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "websearch-setup",
    ),
    # Naming Hermes makes the target Hermes' own setting, but only beside a
    # setup verb: a lookup or a fault report about Hermes' web search names
    # it too, and stays on its own lane.
    RoutingInterventionCase(
        "configure-hermes-web-search-leads-with-the-setup-guide",
        "Configuring Hermes' web search leads with websearch-setup rather than running a lookup",
        "configure hermes web search",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "websearch-setup",
    ),
    RoutingInterventionCase(
        "hermes-web-search-free-tier-switch-leads-with-the-setup-guide",
        "Switching Hermes' web search to the free tier leads with websearch-setup rather than running a lookup",
        "switch hermes web search to the free tier",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "websearch-setup",
    ),
    RoutingInterventionCase(
        "configure-web-search-in-hermes-leads-with-the-setup-guide",
        "Asking how to configure web search in Hermes leads with websearch-setup rather than running a lookup",
        "how do I configure web search in hermes",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "websearch-setup",
    ),
    # With an object, "configure web search" is the user's own app. Measured
    # with the phrase matched anywhere in the message, the first dispatched
    # the setup guide. These stay where origin/main sends them; the point of
    # the pin is that the setup guide is not the destination.
    RoutingInterventionCase(
        "app-catalog-search-configuration-stays-off-the-setup-guide",
        "Configuring search for a store's catalog stays on the lookup lane, not the web search setup guide",
        "configure web search for the store's product catalog",
        "dispatch",
        "web-research",
        "run_hermes_research",
        "web_research",
    ),
    RoutingInterventionCase(
        "nextjs-search-configuration-stays-off-the-setup-guide",
        "Configuring search in a Next.js app stays on the lookup lane, not the web search setup guide",
        "configure web search in our nextjs app",
        "dispatch",
        "web-research",
        "run_hermes_research",
        "web_research",
    ),
    RoutingInterventionCase(
        "web-search-cost-complaint-leads-with-the-setup-guide",
        "A web search cost complaint leads with websearch-setup rather than running a lookup",
        "web search costs too much",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "websearch-setup",
    ),
    RoutingInterventionCase(
        "keyless-web-search-tier-leads-with-the-setup-guide",
        "Choosing the keyless free web search tier leads with websearch-setup rather than running a lookup",
        "use the keyless free web search tier",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "websearch-setup",
    ),
    # `web extract backend` is a setup-guide phrase but not a trigger: as a
    # trigger it dispatched the guide on an app-performance sentence (pinned
    # in the negative corpus), so the phrase only stands down the lookup
    # guard and the route asks with the guide leading.
    RoutingInterventionCase(
        "web-extract-backend-choice-leads-with-the-setup-guide",
        "Setting the web extract backend leads with websearch-setup rather than the lookup lane",
        "set the web extract backend to firecrawl",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "websearch-setup",
    ),
    # The other side of the same phrases: a lookup ABOUT costs or free tiers
    # stays a lookup. Measured: widening the trigger and setup-guide phrases
    # to "web search costs" and "free tier" turns the cloud-GPU cost lookup
    # and the free-tier API lookup into clarifies, and "free web search tier"
    # as a setup-guide phrase does the same to the free-tier comparison, which
    # is why that setup-guide phrase is "keyless free web search".
    RoutingInterventionCase(
        "web-search-cost-lookup-stays-on-web-research",
        "A cited lookup about costs stays on the web lookup lane",
        "web search costs of cloud GPUs and cite sources",
        "dispatch",
        "web-research",
        "run_hermes_research",
        "web_research",
    ),
    # "hermes web search" without a setup verb is a lookup or a report.
    # Measured with the phrase standing down the lookup guard on its own,
    # these became clarifies.
    RoutingInterventionCase(
        "hermes-web-search-comparison-stays-on-web-research",
        "A cited comparison of Hermes' web search stays on the web lookup lane",
        "compare hermes web search with openai web search, cite sources",
        "dispatch",
        "web-research",
        "run_hermes_research",
        "web_research",
    ),
    RoutingInterventionCase(
        "hermes-web-search-outage-check-stays-on-browser-operator",
        "Checking whether Hermes' web search is down stays on the browser operator",
        "is hermes web search down right now? check the status page",
        "dispatch",
        "browser-operator",
        "prepare_browser_operator_card",
        "browser_operator",
    ),
    RoutingInterventionCase(
        "free-tier-comparison-lookup-stays-on-web-research",
        "A cited comparison of vendors' free web search tiers stays on the web lookup lane",
        "compare the free web search tier of brave and exa, cite sources",
        "dispatch",
        "web-research",
        "run_hermes_research",
        "web_research",
    ),
    RoutingInterventionCase(
        "web-search-free-tier-lookup-stays-on-web-research",
        "A lookup about which search APIs have a free tier stays on the web lookup lane",
        "web search which search APIs have a free tier",
        "dispatch",
        "web-research",
        "run_hermes_research",
        "web_research",
    ),
    RoutingInterventionCase(
        "english-morning-brief-connect-guide",
        "English mail-for-brief request opens the morning brief guide",
        "connect my email for a morning brief",
        "dispatch",
        "morning-brief",
        "run_setup_guide",
        "setup_guide",
    ),
    RoutingInterventionCase(
        "korean-morning-brief-setup-guide",
        "Korean morning brief setup request opens the morning brief guide",
        "모닝 브리핑 설정해줘",
        "dispatch",
        "morning-brief",
        "run_setup_guide",
        "setup_guide",
    ),
    RoutingInterventionCase(
        "meta-router-slash-imperative-en",
        "English /omh imperative opens the meta-router fast-path",
        "/omh add a dark mode toggle to the settings page",
        "dispatch",
        "meta-router",
        "present_meta_route",
        "meta_route",
    ),
    RoutingInterventionCase(
        "meta-router-dotslash-imperative-korean",
        "Korean ./omh imperative opens the meta-router fast-path",
        "./omh 로그인 화면 리팩터링부터 테스트까지 해줘",
        "dispatch",
        "meta-router",
        "present_meta_route",
        "meta_route",
    ),
    RoutingInterventionCase(
        "meta-router-slash-chain-imperative",
        "English /omh chained imperative opens the meta-router fast-path",
        "/omh migrate this service off the deprecated API and add regression tests",
        "dispatch",
        "meta-router",
        "present_meta_route",
        "meta_route",
    ),
    RoutingInterventionCase(
        "meta-router-bare-omh-regression-pin",
        "Bare omh one-cycle delivery stays in the delivery lane, not meta-router",
        "omh add a dark mode toggle and ship it in one cycle",
        "dispatch",
        "ultrawork",
        "choose_executor",
        "handoff",
    ),
    RoutingInterventionCase(
        "meta-router-catalog-question-remainder-picker",
        "A /omh catalog question remainder opens the picker, not meta-router",
        "/omh what workflows are available?",
        "dispatch",
        "oh-my-hermes",
        "choose_skill",
        "skill_picker",
    ),
    # The intents behind the removed generic tokens must still route: `look up`
    # stays a research phrase after `lookup` was dropped, and a strategy
    # request reaches `strategy-brief` instead of being captured by `plan`'s
    # former bare `strategy` token.
    RoutingInterventionCase(
        "look-up-phrase-still-research",
        "A look-up request still routes without the bare lookup token, now to the web lookup lane",
        "look up the pricing table",
        "dispatch",
        "web-research",
        "run_hermes_research",
        "web_research",
    ),
    # `research` absorbed the deep-grounding intent when `web-research` was
    # renamed, so the deep cues have to reach it. The rename also made the
    # catalog name an ordinary English verb, so a sentence can open with it while
    # naming a neighbour's whole job; the guards below pin every lane the bare
    # first-word form was measured stealing from, plus one positive proving an
    # otherwise-unclaimed bare form still reaches research.
    RoutingInterventionCase(
        "korean-deep-research-reaches-research",
        "A Korean pre-spec reference-implementation request reaches the research engine",
        "딥리서치로 다른 오픈소스 구현들을 깊게 보고 스펙 잡기 전에 근거를 만들어줘.",
        "dispatch",
        "research",
        "run_hermes_research",
        "web_research",
    ),
    RoutingInterventionCase(
        "prior-art-study-reaches-research",
        "An English prior-art study request reaches the research engine",
        "study existing implementations and prior art before planning this",
        "dispatch",
        "research",
        "run_hermes_research",
        "web_research",
    ),
    RoutingInterventionCase(
        "plain-web-search-still-reaches-research",
        "A plain current-source request reaches the web lookup lane after the split",
        "웹서치해서 최신 자료 정리해줘",
        "dispatch",
        "web-research",
        "run_hermes_research",
        "web_research",
    ),
    # #1689. Three shipped skills lost their own home turf, each for a
    # different reason, and each is pinned at the phrasing a person types.
    #
    # `live-incident-response` shipped for #1563 and lost the sentence it
    # exists for to `browser-operator`, whose guard fires on a context token
    # plus an action token: `checkout` names a payment page and also the
    # service, `open` opens a tab and also describes an incident that is
    # still running. A guard boost of 42 cannot be outscored, so the
    # incident declarations block that guard instead. The skill also had
    # "open incident" but not the order people say it in.
    RoutingInterventionCase(
        "an-open-incident-reaches-the-incident-lane",
        "An incident open right now reaches the incident lane, not a browser errand",
        "we have an incident open right now, the checkout API is down",
        "dispatch",
        "live-incident-response",
        "prepare_live_incident_record",
        "live_incident_record",
    ),
    # The blocker must not cost `browser-operator` its own turf.
    # Re-pinned to clarify (2026-09-26): the guard that carried this dispatch
    # measured under 3 right per wrong on the tuning set, so it is context-only
    # and the route asks; the declined winner, browser-operator, leads the shortlist.
    RoutingInterventionCase(
        "a-page-operation-still-reaches-browser-operator",
        "A real page operation still reaches the browser lane",
        "open the checkout page in staging and click through the form",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "browser-operator",
    ),
    # `inference-serving` carried "serve this model" and "serve the model".
    # A person names the size, which puts it between the two words, so no
    # trigger matched and the skill never surfaced at all.
    RoutingInterventionCase(
        "serving-a-sized-model-reaches-inference-serving",
        "Serving a model of a stated size reaches the serving lane",
        "serve a 7B model at 50 requests per second",
        "dispatch",
        "inference-serving",
        "prepare_inference_serving",
        "inference_serving",
    ),
    # `refactor-plan` offers itself only when the message carries both
    # restructuring and planning vocabulary, so a decided refactor described
    # without either word was dropped before a trigger could score.
    RoutingInterventionCase(
        "breaking-up-a-long-function-reaches-refactor-plan",
        "A long function that needs breaking up reaches the refactor planner",
        "this 900 line function needs to be broken up",
        "dispatch",
        "refactor-plan",
        "prepare_refactor_plan",
        "refactor_plan",
    ),
    # #1688 traded `deep-interview`'s bare `interview` trigger for
    # "interview me". The bare word is every hiring loop, user study, and
    # recorded conversation in the language, and at +6 it took
    # "interview questions for a senior backend role" the moment the `backend`
    # name stopped taking it first. This pins the form the skill is actually
    # asked for; the negative control is
    # `recorded-interview-is-not-the-interview-lane`.
    RoutingInterventionCase(
        "interview-me-reaches-the-interview-lane",
        "Asking to be interviewed reaches the interview lane",
        "interview me about this feature",
        "dispatch",
        "deep-interview",
        "answer_clarification",
        "clarification",
    ),
    RoutingInterventionCase(
        "deep-interview-request-stays-clarification",
        "A deep interview request keeps clarification instead of overrouting to research",
        "deep interview로 요구사항 정리해줘",
        "dispatch",
        "deep-interview",
        "answer_clarification",
        "clarification",
    ),
    # Greenfield creation reaches the interview lane. Before the greenfield
    # guard the product noun decided the outcome: `build a navbar` reached the
    # delivery cycle at 44 while `build a todo list` scored 4 and fell to the
    # picker, because `navbar` sat in a literal noun set and `todo`, `app`, and
    # `dashboard` did not.
    # Re-pinned to clarify (shortlist-first, owner decision 2026-09-26): the winner's evidence is
    # tokens or a context-only guard, so the route asks; the declined winner, deep-interview, leads
    # the shortlist.
    RoutingInterventionCase(
        "greenfield-build-reaches-interview",
        "An English greenfield build request reaches the interview lane whatever the product noun",
        "let's build a react todo list",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "deep-interview",
    ),
    RoutingInterventionCase(
        "greenfield-build-korean-reaches-interview",
        "A Korean greenfield build request reaches the interview lane",
        "웹사이트 하나 만들어줘",
        "dispatch",
        "deep-interview",
        "answer_clarification",
        "clarification",
    ),
    # CLAUDE.md is a context FILE, not an advisor mention. Before the bare-token
    # retirement, the literal string matched `ask`'s bare `claude` token and beat
    # the greenfield guard 9-to-8, dispatching the external-advisor lane at high
    # confidence for a project-bootstrap request. `ask` no longer carries a bare
    # `claude`/`gemini` trigger at all, so this case now pins the structural fix
    # rather than the filename-carve-out shield that used to guard it.
    RoutingInterventionCase(
        "greenfield-korean-context-file-reaches-interview",
        "A Korean new-project request naming CLAUDE.md reaches the interview lane, not the advisor",
        "새 프로젝트 시작하는데 README랑 CLAUDE.md 만들어줘",
        "dispatch",
        "deep-interview",
        "answer_clarification",
        "clarification",
    ),
    # Overroute guards for the greenfield shape. The creation opener is the
    # weakest signal in the message, so anything that claimed it on real
    # vocabulary keeps its lane.
    RoutingInterventionCase(
        "greenfield-shape-keeps-frontend",
        "A greenfield opener does not take a web surface request off the frontend lane",
        "make me a landing page",
        "dispatch",
        "frontend",
        "prepare_frontend_handoff",
        "frontend_handoff",
    ),
    RoutingInterventionCase(
        "greenfield-shape-keeps-delivery-for-named-surface",
        "Naming a concrete existing surface keeps the delivery cycle instead of opening an interview",
        "build a login component",
        "dispatch",
        "ultrawork",
        "choose_executor",
        "handoff",
    ),
    RoutingInterventionCase(
        "greenfield-shape-keeps-research-brief",
        "Creating a named deliverable keeps its own lane rather than the interview lane",
        "create a research brief for the auth migration",
        "dispatch",
        "research-brief",
        "run_hermes_research",
        "web_research",
    ),
    # Trigger-direction guard. A trigger fires when the message contains it,
    # never the reverse: the bare word `test` used to match `npm test`,
    # `cargo test`, `pytest`, and `python -m unittest` at +6 apiece and reached
    # `command-operator` with a score of 73 at high confidence. The bare-word
    # half of that guard lives in tests/test_routing_scoring.py - a one-word
    # message cannot be an intervention case, because this corpus also forbids
    # the raw message from appearing in the machine payload and a common word
    # always does.
    RoutingInterventionCase(
        "command-phrase-still-reaches-command-operator",
        "The trigger-direction fix keeps a message that genuinely contains the command phrase",
        "npm test",
        "dispatch",
        "command-operator",
        "prepare_command_operator_card",
        "command_operator",
    ),
    RoutingInterventionCase(
        "verb-shaped-research-keeps-paper-learning",
        "A sentence opening with the verb research keeps paper-learning for an attached paper",
        "research this attached arxiv PDF and explain it",
        "dispatch",
        "paper-learning",
        "prepare_paper_learning",
        "paper_learning",
    ),
    RoutingInterventionCase(
        "verb-shaped-research-keeps-research-department",
        "A sentence opening with the verb research keeps research-department for a source inbox",
        "research a source inbox for competitor sources",
        "dispatch",
        "research-department",
        "prepare_research_department_plan",
        "research_department",
    ),
    RoutingInterventionCase(
        "korean-verb-shaped-research-keeps-research-department",
        "A Korean research-operations request keeps research-department instead of the bare name",
        "research 부서 운영 체계를 잡아줘",
        "dispatch",
        "research-department",
        "prepare_research_department_plan",
        "research_department",
    ),
    RoutingInterventionCase(
        "verb-shaped-research-keeps-source-finder",
        "A sentence opening with the verb research keeps source-finder for typed candidate acquisition",
        "research candidates: find datasets and GitHub repos for agent memory",
        "dispatch",
        "source-finder",
        "prepare_source_finder_plan",
        "source_finder",
    ),
    RoutingInterventionCase(
        "verb-shaped-research-keeps-feedback-triage",
        "A sentence opening with the verb research keeps feedback-triage for customer signals",
        "research our customer feedback tickets and cluster the bugs",
        "dispatch",
        "feedback-triage",
        "triage_feedback",
        "feedback_triage",
    ),
    RoutingInterventionCase(
        "verb-shaped-research-keeps-research-brief",
        "A sentence opening with the verb research keeps research-brief for a decision brief",
        "research a pricing decision brief with evidence versus inference",
        "dispatch",
        "research-brief",
        "run_hermes_research",
        "web_research",
    ),
    RoutingInterventionCase(
        "research-adverb-does-not-name-research-brief",
        "An adverb after the verb research does not read as naming research-brief",
        "research briefly what the options are for vector search",
        "dispatch",
        "research-brief",
        "run_hermes_research",
        "web_research",
    ),
    # Retargeted with `best-practice-research`'s retirement into `web-research`
    # (#1691). The case still measures the same thing -- the sibling-pointer
    # words `upstream` and `guidance` in the `research` description must not
    # steal a question that names them -- but the skill that owns the phrase is
    # now the target home, which is where the trigger moved.
    RoutingInterventionCase(
        "sibling-pointer-words-stay-with-web-research",
        "The sibling-pointer words in the research description do not steal upstream guidance questions",
        "upstream guidance for pinning Python dependencies",
        "dispatch",
        "web-research",
        "run_hermes_research",
        "web_research",
    ),
    RoutingInterventionCase(
        "unclaimed-bare-research-still-reaches-research",
        "A bare research request no neighbour claims still reaches the research engine",
        "research kubernetes operator patterns for this design",
        "dispatch",
        "research",
        "run_hermes_research",
        "web_research",
    ),
    RoutingInterventionCase(
        "korean-finance-analysis",
        "Korean finance analysis routes to finance analysis",
        "2분기 실적을 예산과 비교해서 비용 차이와 현금 리스크를 경영진용으로 정리해줘.",
        "dispatch",
        "finance-analysis",
        "prepare_finance_analysis",
        "finance_analysis",
    ),
    RoutingInterventionCase(
        "korean-people-ops",
        "Korean people operations routes to people ops",
        "첫 시니어 고객지원 채용을 위한 면접 평가표와 디브리핑 절차를 만들어줘.",
        "dispatch",
        "people-ops",
        "prepare_people_ops_brief",
        "people_ops",
    ),
    RoutingInterventionCase(
        "korean-legal-compliance-review",
        "Korean legal compliance review routes to legal compliance review",
        "이 공급업체 계약서의 개인정보 처리 의무와 위험 조항, 법무팀에 물어볼 질문을 정리해줘.",
        "dispatch",
        "legal-compliance-review",
        "prepare_legal_compliance_review",
        "legal_compliance_review",
    ),
    RoutingInterventionCase(
        "korean-support-operations",
        "Korean support operations routes to support operations",
        "로그인 장애를 제보한 고객에게 보낼 답변 초안과 엔지니어링 에스컬레이션 필요 여부를 정리해줘.",
        "dispatch",
        "support-operations",
        "prepare_support_operations",
        "support_operations",
    ),
    RoutingInterventionCase(
        "korean-curriculum-design",
        "Korean curriculum design routes to curriculum design",
        "신규 고객지원 담당자를 위한 6주 온보딩 커리큘럼과 학습 목표, 실습 평가를 설계해줘.",
        "dispatch",
        "curriculum-design",
        "prepare_curriculum_design",
        "curriculum_design",
    ),
    RoutingInterventionCase(
        "korean-localization-review",
        "Korean localization review routes to localization review",
        "출시 전에 한국어 결제 화면 문구의 용어 일관성, 현지화 품질, 맥락 누락을 검토해줘.",
        "dispatch",
        "localization-review",
        "prepare_localization_review",
        "localization_review",
    ),
    RoutingInterventionCase(
        "korean-sales-development",
        "Korean sales development routes to sales development",
        "고객지원 플랫폼을 검토 중인 미드마켓 잠재 고객을 위한 발견 질문과 영업 자격 검증 계획을 만들어줘.",
        "dispatch",
        "sales-development",
        "prepare_sales_development",
        "sales_development",
    ),
    RoutingInterventionCase(
        "korean-product-brief",
        "Korean product brief routes to product brief",
        "온보딩 첫 이용자 이탈을 줄이기 위한 PRD와 로드맵 우선순위 옵션을 정리해줘.",
        "dispatch",
        "product-brief",
        "prepare_product_brief",
        "product_brief",
    ),
    RoutingInterventionCase(
        "korean-slowdown-discovery-reaches-ultraperf",
        "A Korean post-deploy slowdown discovery request opens the ultraperf loop",
        "\ubc30\ud3ec \ud6c4 \ub290\ub824\uc9c4 \uc6d0\uc778 \ucc3e\uc544\uc918",
        "dispatch",
        "ultraperf",
        "prepare_ultraperf_loop",
        "ultraperf_loop",
    ),
    RoutingInterventionCase(
        "strategy-request-reaches-strategy-brief",
        "A strategy request routes to strategy-brief instead of generic planning",
        "our pricing strategy needs work",
        "dispatch",
        "strategy-brief",
        "prepare_strategy_brief",
        "strategy_brief",
    ),
    RoutingInterventionCase(
        "context-canonical-explicit",
        "Canonical context invocation opens project terminology alignment",
        "./context align the terminology this project uses",
        "dispatch",
        "context",
        "prepare_project_terms_context",
        "project_terms_context",
    ),
    RoutingInterventionCase(
        "context-public-label-explicit",
        "Public ulw-context invocation opens project terminology alignment",
        "use ulw-context to align the terms this project uses",
        "dispatch",
        "context",
        "prepare_project_terms_context",
        "project_terms_context",
    ),
    RoutingInterventionCase(
        "context-fuzzy-project-language",
        "A fuzzy project-language alignment request reaches ulw-context",
        "align project terminology across this repository",
        "dispatch",
        "context",
        "prepare_project_terms_context",
        "project_terms_context",
    ),
    RoutingInterventionCase(
        "jit-learn-korean-immediate-payoff",
        "Korean immediate-payoff learning requests route to just-in-time learning",
        (
            "네가 나에 대해 알고 있는 승인된 맥락을 바탕으로 지금 내 문제 해결에 가장 도움 되는 학습 주제를 "
            "인터뷰로 찾아줘. 깊이 리서치해서 책, 팟캐스트, 크리에이터, 강의를 링크와 형식, 지금 나에게 "
            "필요한 구체적인 이유와 함께 마크다운 목록으로 추천해줘. 뻔한 자기계발이나 인기순 추천은 빼줘."
        ),
        "dispatch",
        "jit-learn",
        "prepare_learning_brief",
        "jit_learn",
    ),
    RoutingInterventionCase(
        "jit-learn-current-blocker",
        "Current-blocker learning requests route to just-in-time learning",
        "what should I learn next to solve my current blocker?",
        "dispatch",
        "jit-learn",
        "prepare_learning_brief",
        "jit_learn",
    ),
    RoutingInterventionCase(
        "jit-learn-well-formed-still-confirms",
        "A specific immediate-learning request still enters the confirmation-first workflow",
        (
            "I need to learn Kafka consumer-group rebalancing before Friday's incident review; I know the basics "
            "and need one book, podcast, creator, and course with links so I can diagnose our current lag spike."
        ),
        "dispatch",
        "jit-learn",
        "prepare_learning_brief",
        "jit_learn",
    ),
    RoutingInterventionCase(
        "jit-learn-negative-workflow-learning",
        "OMH self-improvement remains workflow learning",
        "turn this failed OMH workflow into a skill improvement proposal",
        "dispatch",
        "workflow-learning",
        "audit_learning_readiness",
        "workflow_learning",
    ),
    # Re-pinned to clarify (shortlist-first, owner decision 2026-09-26): the winner's evidence is
    # tokens or a context-only guard, so the route asks; the declined winner, curriculum-design, leads
    # the shortlist.
    RoutingInterventionCase(
        "jit-learn-negative-curriculum-design",
        "An explicit multi-week syllabus remains curriculum design",
        "Design a six-week curriculum with weekly lessons and assessments for new support agents.",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "curriculum-design",
    ),
    RoutingInterventionCase(
        "jit-learn-negative-korean-curriculum-learning-objective",
        "A Korean curriculum request that names a learning objective remains curriculum design",
        "학습 목표 커리큘럼을 6주로 만들어줘",
        "dispatch",
        "curriculum-design",
        "prepare_curriculum_design",
        "curriculum_design",
    ),
    RoutingInterventionCase(
        "jit-learn-negative-paper-learning",
        "Explanation of a supplied paper remains paper learning",
        "Explain the attached paper section by section at a beginner level.",
        "dispatch",
        "paper-learning",
        "prepare_paper_learning",
        "paper_learning",
    ),
    RoutingInterventionCase(
        "jit-learn-negative-source-finder",
        "A typed source inventory remains source finder",
        "Find papers, datasets, GitHub repositories, and public talks about agent memory.",
        "dispatch",
        "source-finder",
        "prepare_source_finder_plan",
        "source_finder",
    ),
    # Re-pinned to clarify (shortlist-first, owner decision 2026-09-26): the winner's evidence is
    # tokens or a context-only guard, so the route asks; the declined winner, web-research, leads
    # the shortlist.
    RoutingInterventionCase(
        "jit-learn-negative-research",
        "An already-scoped current-source investigation reaches the web lookup lane",
        "Research the latest Kubernetes 1.35 release notes with current primary sources and citations.",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "web-research",
    ),
    RoutingInterventionCase(
        "jit-learn-negative-plan",
        "Generic implementation planning remains on the plan route",
        "Plan how to implement a safe feature in this repository.",
        "dispatch",
        "plan",
        "present_plan",
        "plan",
    ),
    RoutingInterventionCase(
        "jit-learn-negative-incident-postmortem-rollback",
        "Incident postmortem rollback investigation remains reliability review",
        "review the incident postmortem this week to determine the rollback plan",
        "dispatch",
        "reliability-review",
        "prepare_reliability_review",
        "reliability_review",
    ),
    # Re-pinned to clarify (shortlist-first, owner decision 2026-09-26): the winner's evidence is
    # tokens or a context-only guard, so the route asks; the declined winner, reliability-review, leads
    # the shortlist.
    RoutingInterventionCase(
        "jit-learn-negative-postmortem-report-rollback",
        "Postmortem report rollback investigation remains reliability review",
        "review the postmortem report this week before choosing the rollback path",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "reliability-review",
    ),
    # ULW fold controls (issue #954). After stage 5 the coordination cue
    # resolves the `coordinated_scope` alias to `ultrawork`, and a
    # disjoint-lanes phrasing still reaches `ultrawork`'s existing lane path
    # rather than any new capability route.
    RoutingInterventionCase(
        "coordinated-workers-shared-task-list",
        "The coordination cue reaches ultrawork's coordinated_scope capability",
        "run three coordinated workers on one shared task list",
        "dispatch",
        "ultrawork",
        "forward_plan_to_selected_workflow",
        "plan",
    ),
    RoutingInterventionCase(
        "disjoint-lanes-reaches-existing-path",
        "Disjoint parallel lanes still reach ultrawork's existing lane path",
        "split this into parallel work lanes with disjoint ownership",
        "dispatch",
        "ultrawork",
        "forward_plan_to_selected_workflow",
        "plan",
    ),
    # Re-pinned to clarify (shortlist-first, owner decision 2026-09-26): the winner's evidence is
    # tokens or a context-only guard, so the route asks; the declined winner, ultrawork, leads
    # the shortlist.
    RoutingInterventionCase(
        "dependency-topology-parallel-then-integrate",
        "Dependency-shaped parallel work reaches ultrawork's topology decision",
        "analyze API and UI in parallel, then integrate the results and verify",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "ultrawork",
    ),
    RoutingInterventionCase(
        "negated-finance-then-product-brief",
        "A locally negated finance intent leaves the requested product brief",
        "Not a finance analysis; create a product requirements document",
        "dispatch",
        "product-brief",
        "prepare_product_brief",
        "product_brief",
    ),
    RoutingInterventionCase(
        "people-and-product-complete-intents",
        "Distinct people and product outcomes require clarification",
        "Create a hiring scorecard and a product requirements document",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
    ),
    RoutingInterventionCase(
        "finance-and-legal-complete-intents",
        "Distinct finance and legal outcomes require clarification",
        "Review the budget variance and the contract liability clause",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
    ),
    RoutingInterventionCase(
        "inclusive-negation-finance-analysis",
        "Inclusive not-only language preserves the requested finance domain",
        "Not only a finance analysis but a budget vs actual review",
        "dispatch",
        "finance-analysis",
        "prepare_finance_analysis",
        "finance_analysis",
    ),
    RoutingInterventionCase(
        "prompt-cache-hygiene-budget-review",
        "Prompt-cache hygiene reaches context budget review",
        "set up prompt caching hygiene before this long agent run",
        "dispatch",
        "context-budget-review",
        "prepare_context_budget_review",
        "context_budget_review",
        "context-budget-review",
    ),
    # The phrasing a person actually uses when the window is filling. It opens
    # with the word "context", which is the terminology workflow's whole name,
    # so it was read as an explicit invocation of that workflow and took first
    # place on +12 of name weight alone.
    RoutingInterventionCase(
        "context-window-full-budget-review",
        "A filling context window reaches budget review, not terminology alignment",
        "context window is almost full, save decisions and hand off to a new session",
        "dispatch",
        "context-budget-review",
        "prepare_context_budget_review",
        "context_budget_review",
        "context-budget-review",
    ),
    RoutingInterventionCase(
        "running-out-of-context-budget-review",
        "Running out of context reaches budget review",
        "we are running out of context on this long agent run",
        "dispatch",
        "context-budget-review",
        "prepare_context_budget_review",
        "context_budget_review",
        "context-budget-review",
    ),
    # The other sense of the same word, kept whole: this is the workflow the
    # message above was taking.
    RoutingInterventionCase(
        "project-terminology-stays-context-alignment",
        "A repository-terminology question still reaches terminology alignment",
        "align project terminology for the words this repository uses",
        "dispatch",
        "context",
        "prepare_project_terms_context",
        "project_terms_context",
        "context",
    ),
    RoutingInterventionCase(
        "greenfield-bootstrap-the-project",
        "'Bootstrap the project' reaches the app delivery loop for the greenfield bootstrap pass",
        "bootstrap the project",
        "dispatch",
        "idea-to-deploy",
        "present_app_delivery_loop",
        "app_delivery_loop",
    ),
    RoutingInterventionCase(
        "greenfield-bootstrap-a-new-repo",
        "'Bootstrap a new repo' reaches the app delivery loop instead of read-only onboarding",
        "bootstrap a new repo",
        "dispatch",
        "idea-to-deploy",
        "present_app_delivery_loop",
        "app_delivery_loop",
    ),
    RoutingInterventionCase(
        "greenfield-scaffold-a-new-project",
        "'Scaffold a new project' reaches the app delivery loop for the greenfield bootstrap pass",
        "scaffold a new project",
        "dispatch",
        "idea-to-deploy",
        "present_app_delivery_loop",
        "app_delivery_loop",
    ),
    RoutingInterventionCase(
        "greenfield-set-up-a-new-repo",
        "'Set up a new repo' reaches the app delivery loop for the greenfield bootstrap pass",
        "set up a new repo",
        "dispatch",
        "idea-to-deploy",
        "present_app_delivery_loop",
        "app_delivery_loop",
    ),
    # Wider greenfield-bootstrap reach (#1152 follow-up): the phrases above all
    # name the bootstrap action itself ("bootstrap the project"); these name
    # the bootstrap FILES instead, which is just as fully specified a request
    # and should not detour through a clarifying interview or fall to a
    # zero-score file lookup.
    RoutingInterventionCase(
        "greenfield-standard-project-files-empty-repo",
        "A generic 'standard project files' ask for an explicitly empty repo reaches the app delivery loop",
        "set up the standard project files for this empty repo",
        "dispatch",
        "idea-to-deploy",
        "present_app_delivery_loop",
        "app_delivery_loop",
    ),
    RoutingInterventionCase(
        "greenfield-add-license-and-gitignore",
        "Naming two starter files for the current project reaches the app delivery loop, not memory capture",
        "add a LICENSE and .gitignore to this project",
        "dispatch",
        "idea-to-deploy",
        "present_app_delivery_loop",
        "app_delivery_loop",
    ),
    RoutingInterventionCase(
        "greenfield-new-repo-readme-license-ci",
        "A new-repo request naming README, LICENSE, and CI reaches the app delivery loop over the interview and onboarding ties",
        "create a new repo with README, LICENSE and CI",
        "dispatch",
        "idea-to-deploy",
        "present_app_delivery_loop",
        "app_delivery_loop",
    ),
    # A fresh `git init` with no files named yet is genuinely underspecified -
    # unlike the three cases above, this stays a clarifying interview instead
    # of dispatching the delivery loop outright.
    # Re-pinned to clarify (shortlist-first, owner decision 2026-09-26): the winner's evidence is
    # tokens or a context-only guard, so the route asks; the declined winner, deep-interview, leads
    # the shortlist.
    RoutingInterventionCase(
        "greenfield-git-init-what-now-reaches-interview",
        "'I just ran git init, what now' reaches the interview lane instead of unrelated low-confidence guesses",
        "I just ran git init, what now",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "deep-interview",
    ),
    # Overroute guard for the bootstrap-file shape: fixing a typo in an
    # existing README is a one-file edit in a repo that already exists, so it
    # keeps the direct coding lane rather than being pulled into the bootstrap
    # dispatch by the bare "readme" noun.
    RoutingInterventionCase(
        "readme-typo-edit-keeps-direct-coding-task",
        "Fixing a README typo in an existing repo keeps the direct coding lane, not the bootstrap dispatch",
        "README 오타 고쳐줘",
        "dispatch",
        "ultrawork",
        "choose_executor",
        "handoff",
    ),
    RoutingInterventionCase(
        "maestro-direct-invocation",
        "Direct maestro invocation opens the coding-owner handoff",
        "$maestro",
        "dispatch",
        "maestro",
        "forward_plan_to_selected_workflow",
        "plan",
    ),
    RoutingInterventionCase(
        "coding-handoff-preparation-english",
        "An English coding-handoff preparation request opens maestro",
        "prepare the coding handoff for this work",
        "dispatch",
        "maestro",
        "present_plan",
        "plan",
    ),
    RoutingInterventionCase(
        "korean-handoff-prompt-request",
        "A Korean handoff-prompt request opens maestro",
        "이 작업 위임 프롬프트 만들어줘",
        "dispatch",
        "maestro",
        "present_plan",
        "plan",
    ),
    RoutingInterventionCase(
        "korean-coding-delegation-mechanic",
        "A Korean coding-delegation handoff request opens maestro",
        "코딩 위임 핸드오프 준비해줘",
        "dispatch",
        "maestro",
        "forward_plan_to_selected_workflow",
        "plan",
    ),
    RoutingInterventionCase(
        "adversarial-consensus-direct-invocation",
        "Direct adversarial-consensus invocation opens the consensus rounds",
        "$adversarial-consensus",
        "dispatch",
        "adversarial-consensus",
        "forward_plan_to_selected_workflow",
        "plan",
    ),
    RoutingInterventionCase(
        "red-team-plan-before-writing",
        "A red-team request on an unwritten plan opens the consensus rounds",
        "red team this plan before I write it",
        "dispatch",
        "adversarial-consensus",
        "forward_plan_to_selected_workflow",
        "plan",
    ),
    RoutingInterventionCase(
        "adversarial-planning-request",
        "An adversarial planning request opens the consensus rounds, not generic planning",
        "adversarial planning for the redis session-store move",
        "dispatch",
        "adversarial-consensus",
        "forward_plan_to_selected_workflow",
        "plan",
    ),
    RoutingInterventionCase(
        "korean-multi-perspective-attack",
        "A Korean multi-perspective attack request opens the consensus rounds",
        "다관점 검토로 이 제안 공격해줘",
        "dispatch",
        "adversarial-consensus",
        "forward_plan_to_selected_workflow",
        "plan",
    ),
    # The other half of the adversarial-consensus guard: a plain planning
    # request keeps `plan`. The workflow's triggers carry the word `plan`, so
    # without this case a trigger-token regression would look like a pass.
    RoutingInterventionCase(
        "plain-planning-request-keeps-plan",
        "A plain planning request stays with generic planning, not the consensus rounds",
        "make a plan for the onboarding rewrite",
        "dispatch",
        "plan",
        "forward_plan_to_selected_workflow",
        "plan",
    ),
    RoutingInterventionCase(
        "backend-direct-invocation",
        "Direct backend invocation opens the service contract",
        "$backend",
        "dispatch",
        "backend",
        "prepare_backend_handoff",
        "backend_contract",
    ),
    RoutingInterventionCase(
        "rest-api-with-schema-and-migrations",
        "A REST API plus schema and migration request reaches the backend contract",
        "design a rest api with postgres schema and migrations",
        "dispatch",
        "backend",
        "prepare_backend_handoff",
        "backend_contract",
    ),
    RoutingInterventionCase(
        "korean-server-api-design",
        "A Korean server-API design request reaches the backend contract",
        "포스트그레스 스키마랑 마이그레이션까지 서버 api 설계해줘",
        "dispatch",
        "backend",
        "prepare_backend_handoff",
        "backend_contract",
    ),
    RoutingInterventionCase(
        "rust-direct-invocation",
        "Direct rust invocation opens the Rust change contract",
        "$rust",
        "dispatch",
        "rust",
        "prepare_rust_handoff",
        "rust_contract",
    ),
    RoutingInterventionCase(
        "rust-parser-borrow-checker-errors",
        "A Rust rewrite with borrow-checker errors reaches the Rust change contract",
        "rewrite this parser in rust and fix the borrow checker errors",
        "dispatch",
        "rust",
        "prepare_rust_handoff",
        "rust_contract",
    ),
    RoutingInterventionCase(
        "korean-unsafe-rust-ffi",
        "A Korean unsafe-Rust FFI request reaches the Rust change contract",
        "언세이프 러스트 FFI 래퍼 정리해줘",
        "dispatch",
        "rust",
        "prepare_rust_handoff",
        "rust_contract",
    ),
    RoutingInterventionCase(
        "native-debugging-direct-invocation",
        "Direct native-debugging invocation opens the debugging plan",
        "$native-debugging",
        "dispatch",
        "native-debugging",
        "prepare_native_debug_plan",
        "native_debug_plan",
    ),
    RoutingInterventionCase(
        "segfaulting-binary-debug-request",
        "A segfaulting-binary debug request reaches the native debugging plan",
        "this binary segfaults on the third request, help me debug it",
        "dispatch",
        "native-debugging",
        "prepare_native_debug_plan",
        "native_debug_plan",
    ),
    RoutingInterventionCase(
        "korean-core-dump-native-debugging",
        "A Korean core-dump debugging request reaches the native debugging plan",
        "이 크래시 코어 덤프로 네이티브 디버깅 해줘",
        "dispatch",
        "native-debugging",
        "prepare_native_debug_plan",
        "native_debug_plan",
    ),
    # The other halves of the domain-lane guards. Each pins a neighbour that
    # shares vocabulary with a new lane, so a trigger regression cannot look
    # like a pass.
    RoutingInterventionCase(
        "cargo-shipping-word-keeps-content-operator",
        "The shipping sense of cargo keeps its own lane instead of reaching Rust",
        "cargo ship the release notes",
        "dispatch",
        "content-operator",
        "prepare_content_operator_card",
        "content_operator",
    ),
    RoutingInterventionCase(
        "web-surface-request-keeps-frontend",
        "A web surface request keeps frontend instead of reaching the backend contract",
        "make this landing page responsive",
        "dispatch",
        "frontend",
        "prepare_frontend_handoff",
        "frontend_handoff",
    ),
    RoutingInterventionCase(
        "llm-app-dev-direct-invocation",
        "Direct llm-app-dev invocation opens the LLM app build handoff",
        "$llm-app-dev",
        "dispatch",
        "llm-app-dev",
        "prepare_llm_app_build",
        "llm_app_build",
    ),
    RoutingInterventionCase(
        "rag-pipeline-build-request",
        "A RAG pipeline build request opens the LLM app build handoff",
        "build a rag pipeline",
        "dispatch",
        "llm-app-dev",
        "prepare_llm_app_build",
        "llm_app_build",
    ),
    RoutingInterventionCase(
        "prompt-versioning-request",
        "A prompt-versioning request opens the LLM app build handoff",
        "we need prompt versioning before the next model swap",
        "dispatch",
        "llm-app-dev",
        "prepare_llm_app_build",
        "llm_app_build",
    ),
    RoutingInterventionCase(
        "structured-output-schema-request",
        "A structured-output schema request opens the LLM app build handoff",
        "structured output schema for the invoice extractor",
        "dispatch",
        "llm-app-dev",
        "prepare_llm_app_build",
        "llm_app_build",
    ),
    RoutingInterventionCase(
        "korean-llm-app-development-request",
        "A Korean LLM app development request opens the LLM app build handoff",
        "llm 앱 개발 시작하자",
        "dispatch",
        "llm-app-dev",
        "prepare_llm_app_build",
        "llm_app_build",
    ),
    # Public-board communication is a build decision inside the LLM feature,
    # so the request that names a public destination and the product that
    # would publish to it belongs in the build handoff rather than in a plan
    # or a coordination board. The third case is the cross-lane guard: the
    # OMH agent board shares the word and must keep its own workflow.
    RoutingInterventionCase(
        "public-board-posting-feature-request",
        "A public-board posting feature opens the LLM app build handoff",
        "add a public board posting feature to our llm assistant",
        "dispatch",
        "llm-app-dev",
        "prepare_llm_app_build",
        "llm_app_build",
    ),
    RoutingInterventionCase(
        "public-board-read-and-reply-feature-request",
        "A public-board read-and-reply feature opens the LLM app build handoff",
        "our agent should read and reply on the public message board",
        "dispatch",
        "llm-app-dev",
        "prepare_llm_app_build",
        "llm_app_build",
    ),
    RoutingInterventionCase(
        "agent-board-request-keeps-agent-board",
        "An agent board request keeps the agent board, not the LLM app build handoff",
        "show me the agent board",
        "dispatch",
        "agent-board",
        "prepare_agent_board_card",
        "agent_board",
    ),
    # The other half of the llm-app-dev guard. Its triggers carry `eval`, and
    # comparing executors is `agent-evaluation`'s subject, not this workflow's;
    # without this case a trigger regression that swallowed the agent-operations
    # lane would look like a pass.
    RoutingInterventionCase(
        "executor-comparison-keeps-agent-evaluation",
        "An executor comparison stays with agent-evaluation, not the LLM app build handoff",
        "run an agent evaluation across codex and claude",
        "dispatch",
        "agent-evaluation",
        "prepare_agent_evaluation",
        "agent_evaluation",
    ),
    # The positive half of the shipped trigger packs: a request typed in
    # Japanese or Chinese reaches the same lane its English and Korean
    # equivalents already reach. These are the cases that fail if a pack is
    # dropped from the wheel, if the catalog merge regresses, or if a phrase is
    # edited into something the normalizer cannot see.
    RoutingInterventionCase(
        "japanese-frontend-landing-page",
        "A Japanese landing-page request reaches the frontend handoff",
        "フロントエンドのランディングページをレスポンシブ対応で作って",
        "dispatch",
        "frontend",
        "prepare_frontend_handoff",
        "frontend_handoff",
    ),
    RoutingInterventionCase(
        "japanese-borrow-checker-ownership",
        "A Japanese borrow-checker request reaches the Rust change contract",
        "ボローチェッカーの所有権エラーとライフタイムエラーを直して",
        "dispatch",
        "rust",
        "prepare_rust_handoff",
        "rust_contract",
    ),
    RoutingInterventionCase(
        "japanese-rag-pipeline-build",
        "A Japanese RAG pipeline request reaches the LLM app build handoff",
        "RAGパイプライン構築と構造化出力スキーマを設計して",
        "dispatch",
        "llm-app-dev",
        "prepare_llm_app_build",
        "llm_app_build",
    ),
    RoutingInterventionCase(
        "japanese-segfault-core-dump",
        "A Japanese segfault and core-dump request reaches the native debugging plan",
        "セグメンテーション違反とコアダンプを調べて",
        "dispatch",
        "native-debugging",
        "prepare_native_debug_plan",
        "native_debug_plan",
    ),
    RoutingInterventionCase(
        "japanese-red-team-this-plan",
        "A Japanese adversarial plan review opens the consensus rounds",
        "この計画に反論して敵対的レビューをして",
        "dispatch",
        "adversarial-consensus",
        "forward_plan_to_selected_workflow",
        "plan",
    ),
    RoutingInterventionCase(
        "chinese-frontend-landing-page",
        "A Chinese landing-page request reaches the frontend handoff",
        "前端落地页需要响应式布局",
        "dispatch",
        "frontend",
        "prepare_frontend_handoff",
        "frontend_handoff",
    ),
    RoutingInterventionCase(
        "chinese-borrow-checker-ownership",
        "A Chinese borrow-checker request reaches the Rust change contract",
        "借用检查器报所有权错误和生命周期错误",
        "dispatch",
        "rust",
        "prepare_rust_handoff",
        "rust_contract",
    ),
    RoutingInterventionCase(
        "chinese-rag-pipeline-build",
        "A Chinese retrieval-augmented-generation request reaches the LLM app build handoff",
        "大模型应用开发要做检索增强生成",
        "dispatch",
        "llm-app-dev",
        "prepare_llm_app_build",
        "llm_app_build",
    ),
    RoutingInterventionCase(
        "chinese-segfault-core-dump",
        "A Chinese segfault and core-dump request reaches the native debugging plan",
        "段错误和核心转储怎么排查",
        "dispatch",
        "native-debugging",
        "prepare_native_debug_plan",
        "native_debug_plan",
    ),
    RoutingInterventionCase(
        "chinese-red-team-this-proposal",
        "A Chinese red-team proposal review opens the consensus rounds",
        "红队评审这个方案并找出漏洞",
        "dispatch",
        "adversarial-consensus",
        "forward_plan_to_selected_workflow",
        "plan",
    ),
    # Indonesian. Every case here routed differently before the `id` pack
    # shipped. An `id` phrase is written in ASCII, so it scores as a whole
    # phrase and its words never score alone; a bare phrase or one inside a
    # sentence either dispatches or clarifies with the skill named, and the
    # clarify cases pin the tier.
    RoutingInterventionCase(
        "indonesian-bare-code-review-phrase-clarifies",
        "A bare Indonesian code-review phrase clarifies with code-review named",
        "tinjau kode",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "code-review",
        "medium",
    ),
    RoutingInterventionCase(
        "indonesian-review-this-code-dispatches",
        "An Indonesian review-this-code request reaches the review check",
        "review kode ini",
        "dispatch",
        "code-review",
        "prepare_review_or_followup_handoff",
        "review_check",
    ),
    RoutingInterventionCase(
        "indonesian-pr-review-in-sentence-clarifies",
        "An Indonesian PR review request in a sentence clarifies with code-review named",
        "Tolong tinjau kode di PR saya sebelum merge.",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "code-review",
        "medium",
    ),
    RoutingInterventionCase(
        "indonesian-accessibility-audit-dispatches",
        "An Indonesian accessibility audit request reaches the audit",
        "audit aksesibilitas",
        "dispatch",
        "accessibility-audit",
        "prepare_accessibility_audit",
        "accessibility_audit",
    ),
    RoutingInterventionCase(
        "indonesian-wcag-check-in-sentence-dispatches",
        "An Indonesian WCAG compliance check in a sentence reaches the audit",
        "Cek kepatuhan WCAG untuk situs kami.",
        "dispatch",
        "accessibility-audit",
        "prepare_accessibility_audit",
        "accessibility_audit",
    ),
    RoutingInterventionCase(
        "indonesian-build-failed-dispatches",
        "A bare Indonesian build failure reaches build triage",
        "build gagal",
        "dispatch",
        "build-failure-triage",
        "prepare_build_failure_triage",
        "build_failure_triage",
    ),
    RoutingInterventionCase(
        "indonesian-build-failed-in-sentence-dispatches",
        "An Indonesian build failure after a dependency update reaches build triage",
        "Build gagal setelah saya update dependency, bisa bantu?",
        "dispatch",
        "build-failure-triage",
        "prepare_build_failure_triage",
        "build_failure_triage",
    ),
    RoutingInterventionCase(
        "indonesian-rag-pipeline-clarifies",
        "An Indonesian RAG pipeline request clarifies with the LLM app lane named",
        "Buat pipeline RAG untuk dokumen internal perusahaan.",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "llm-app-dev",
        "medium",
    ),
    RoutingInterventionCase(
        "indonesian-parallel-implementation-clarifies",
        "An Indonesian parallel implementation request clarifies with ultrawork named",
        "implementasi paralel",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "ultrawork",
        "medium",
    ),
    RoutingInterventionCase(
        "indonesian-verify-before-merge-dispatches",
        "An Indonesian verify-before-merge request reaches the verification gate",
        "verifikasi sebelum merge",
        "dispatch",
        "verification-gate",
        "prepare_verification_gate",
        "verification_gate",
    ),
    RoutingInterventionCase(
        "indonesian-screenshot-check-dispatches",
        "An Indonesian screenshot check reaches visual QA",
        "cek tampilan dari screenshot",
        "dispatch",
        "visual-qa",
        "prepare_visual_qa",
        "visual_qa",
    ),
    # Vagueness gate on heavy-mode routing (P2-12): `ultrawork`/`maestro`
    # requests that name no concrete target clarify with a specific
    # target/scope/success-criterion question instead of dispatching on
    # guesswork; requests that do name one still dispatch unaffected.
    RoutingInterventionCase(
        "heavy-lane-ultrawork-vague-filler-clarifies",
        "A filler-only ultrawork request clarifies instead of dispatching on guesswork",
        "please fix this with ultrawork",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "ultrawork",
    ),
    RoutingInterventionCase(
        "heavy-lane-maestro-vague-filler-clarifies",
        "A filler-only maestro request clarifies instead of dispatching on guesswork",
        "just fix this with maestro",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "maestro",
    ),
    RoutingInterventionCase(
        "heavy-lane-korean-ulw-medium-confidence-specific-clarify",
        "A fused Korean ulw cue clarifies with the specific heavy-lane question, not a generic confidence notice",
        "ulw로 다 고쳐줘",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "ultrawork",
    ),
    RoutingInterventionCase(
        "heavy-lane-korean-ulw-filler-clarifies",
        "A Korean filler-only ulw request clarifies instead of dispatching on guesswork",
        "그거 ulw로 좀 해줘",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "ultrawork",
    ),
    RoutingInterventionCase(
        "heavy-lane-japanese-ultrawork-filler-clarifies",
        "A Japanese filler-only ultrawork request clarifies instead of dispatching on guesswork",
        "ultraworkやって",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "ultrawork",
    ),
    RoutingInterventionCase(
        "heavy-lane-chinese-ultrawork-filler-clarifies",
        "A Chinese filler-only ultrawork request clarifies instead of dispatching on guesswork",
        "把那个ultrawork搞定",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "ultrawork",
    ),
    RoutingInterventionCase(
        "heavy-lane-ultrawork-concrete-anchor-still-dispatches",
        "An ultrawork request naming a file path and a cased test name still dispatches",
        "ultrawork: fix the flaky SpawnStaggerTests wall-clock assertion in tests/test_fanout_dispatch.py",
        "dispatch",
        "ultrawork",
        "present_plan",
        "plan",
    ),
    RoutingInterventionCase(
        "heavy-lane-maestro-concrete-anchor-still-dispatches",
        "A maestro request naming a file path still dispatches",
        "maestro: prepare a handoff for the OAuth token refresh in src/auth/token_refresh.py",
        "dispatch",
        "maestro",
        "forward_plan_to_selected_workflow",
        "plan",
    ),
    RoutingInterventionCase(
        "new-model-onboarding-reaches-model-optimization",
        "A new-model onboarding request opens the model-onboarding process",
        "onboard new model",
        "dispatch",
        "model-optimization",
        "run_hermes_research",
        "web_research",
    ),
    RoutingInterventionCase(
        "model-optimization-by-name-dispatches",
        "Naming the model-optimization workflow dispatches it",
        "model optimization",
        "dispatch",
        "model-optimization",
        "run_hermes_research",
        "web_research",
    ),
    RoutingInterventionCase(
        "serve-this-model-reaches-inference-serving",
        "Asking to serve a model opens the serving workflow",
        "serve this model with vllm for the team",
        "dispatch",
        "inference-serving",
        "prepare_inference_serving",
        "inference_serving",
    ),
    RoutingInterventionCase(
        "serving-benchmark-reaches-inference-serving",
        "Asking for a serving benchmark opens the serving workflow",
        "prefix caching benchmark",
        "dispatch",
        "inference-serving",
        "prepare_inference_serving",
        "inference_serving",
    ),
    RoutingInterventionCase(
        "audit-our-tech-debt-reaches-tech-debt-audit",
        "Asking for a tech debt audit opens the ledger workflow",
        "audit our tech debt",
        "dispatch",
        "tech-debt-audit",
        "prepare_tech_debt_audit",
        "tech_debt_audit",
    ),
    RoutingInterventionCase(
        "debt-ledger-reaches-tech-debt-audit",
        "Asking for the debt ledger opens the ledger workflow",
        "build a tech debt ledger for this repo",
        "dispatch",
        "tech-debt-audit",
        "prepare_tech_debt_audit",
        "tech_debt_audit",
    ),
    RoutingInterventionCase(
        "homepage-score-reaches-award-bar-score",
        "Asking how a page scores against design awards opens the award-bar score",
        "how does our homepage score against design awards",
        "dispatch",
        "award-bar-score",
        "prepare_award_bar_score",
        "award_bar_score",
    ),
    RoutingInterventionCase(
        "make-it-award-winning-stays-frontend",
        "Asking to make a page award-winning is implementation, not scoring",
        "make our landing page award winning",
        "dispatch",
        "frontend",
        "prepare_frontend_handoff",
        "frontend_handoff",
    ),
    RoutingInterventionCase(
        "css-design-awards-reaches-award-bar-score",
        "Naming the award body opens the award-bar score",
        "score our landing page against the css design awards bar",
        "dispatch",
        "award-bar-score",
        "prepare_award_bar_score",
        "award_bar_score",
    ),
    RoutingInterventionCase(
        "refactor-plan-by-name-dispatches",
        "Naming the refactor-plan workflow dispatches it",
        "run the refactor-plan workflow",
        "dispatch",
        "refactor-plan",
        "prepare_refactor_plan",
        "refactor_plan",
    ),
    RoutingInterventionCase(
        "refactor-planning-reaches-refactor-plan",
        "Asking for refactor planning opens the phase planner",
        "refactor planning",
        "dispatch",
        "refactor-plan",
        "prepare_refactor_plan",
        "refactor_plan",
    ),
    RoutingInterventionCase(
        "visualize-codebase-reaches-codebase-uml",
        "Asking to visualize the codebase opens the diagram workflow",
        "visualize the codebase for the new teammate",
        "dispatch",
        "codebase-uml",
        "prepare_codebase_uml",
        "codebase_uml",
    ),
    RoutingInterventionCase(
        "architecture-diagram-reaches-codebase-uml",
        "Asking for an architecture diagram opens the diagram workflow",
        "make an architecture diagram of this repo",
        "dispatch",
        "codebase-uml",
        "prepare_codebase_uml",
        "codebase_uml",
    ),
    RoutingInterventionCase(
        "prop-drilling-reaches-frontend-refactor",
        "A prop-drilling complaint opens the UI refactor workflow",
        "prop drilling",
        "dispatch",
        "frontend-refactor",
        "forward_plan_to_selected_workflow",
        "plan",
    ),
    RoutingInterventionCase(
        "oversized-component-reaches-frontend-refactor",
        "An oversized-component complaint opens the UI refactor workflow",
        "split this component, it is way too big",
        "dispatch",
        "frontend-refactor",
        "forward_plan_to_selected_workflow",
        "plan",
    ),
    RoutingInterventionCase(
        "natural-memory-interview-reaches-memory-sync",
        "The memory interview phrased naturally reaches memory-sync, not the ask advisor",
        "pick a few of your memories and ask me if they are still true",
        "dispatch",
        "memory-sync",
        "prepare_memory_sync",
        "memory_curation",
    ),
    RoutingInterventionCase(
        # A paraphrase with different verbs pins the direct memory-interview
        # boost (possessive memory vocabulary co-occurring with an asking
        # verb), not one literal fixture sentence.
        "memory-interview-paraphrase-reaches-memory-sync",
        "A paraphrased memory interview still beats the ask advisor",
        "check your memories and ask me if they are still true",
        "dispatch",
        "memory-sync",
        "prepare_memory_sync",
        "memory_curation",
    ),
    # Jev skills (C4/C5 of the design critic). A message reaches a `jev-*`
    # skill only by addressing Jev; every skill has its own phrase and a
    # paraphrase, two cases pin the partner-to-sibling swap, and the rest pin
    # that sentences merely ABOUT Jev keep their ordinary owner. Those are
    # intervention cases rather than negative controls because each one
    # dispatches its real owner, and the negative-control evaluator counts
    # any dispatch as an overroute.
    RoutingInterventionCase(
        "jev-ask-typed-question",
        "Asking Jev a yes/no question about supplied text reaches jev-ask",
        "ask jev whether this README section covers installation",
        "dispatch",
        "jev-ask",
        "prepare_typed_ask",
        "typed_ask",
        "jev-ask",
    ),
    RoutingInterventionCase(
        "jev-ask-paraphrase",
        "Having Jev check a document reaches jev-ask ahead of the generic ask skill",
        "have jev check whether the migration notes mention rollback",
        "dispatch",
        "jev-ask",
        "prepare_typed_ask",
        "typed_ask",
        "jev-ask",
    ),
    RoutingInterventionCase(
        "jev-ask-display-name-echo",
        "The rendered display name routes back to jev-ask",
        "use omh-jev-ask on this changelog entry",
        "dispatch",
        "jev-ask",
        "prepare_typed_ask",
        "typed_ask",
        "jev-ask",
    ),
    RoutingInterventionCase(
        "jev-route-phrase",
        "Asking Jev which workflow fits reaches jev-route",
        "ask jev which workflow fits this request",
        "dispatch",
        "jev-route",
        "prepare_route_question_answer",
        "route_question_answer",
        "jev-route",
    ),
    RoutingInterventionCase(
        "jev-route-paraphrase",
        "Having Jev choose the workflow reaches jev-route",
        "have jev choose which workflow should handle this message",
        "dispatch",
        "jev-route",
        "prepare_route_question_answer",
        "route_question_answer",
        "jev-route",
    ),
    RoutingInterventionCase(
        "jev-failure-triage-phrase",
        "Asking Jev whether a failure is transient reaches jev-failure-triage",
        "ask jev if this failure is transient",
        "dispatch",
        "jev-failure-triage",
        "prepare_failure_next_move",
        "failure_next_move",
        "jev-failure-triage",
    ),
    RoutingInterventionCase(
        "jev-failure-triage-paraphrase",
        "Using Jev to triage a failing test reaches jev-failure-triage, not build-failure-triage",
        "use jev to triage this failing test",
        "dispatch",
        "jev-failure-triage",
        "prepare_failure_next_move",
        "failure_next_move",
        "jev-failure-triage",
    ),
    RoutingInterventionCase(
        "jev-failure-triage-broken-run",
        "Using Jev on a CI run that broke reaches jev-failure-triage",
        "use jev on this CI run that broke",
        "dispatch",
        "jev-failure-triage",
        "prepare_failure_next_move",
        "failure_next_move",
        "jev-failure-triage",
    ),
    RoutingInterventionCase(
        "jev-review-gate-phrase",
        "Asking Jev to review a diff reaches jev-review-gate",
        "ask jev to review this diff",
        "dispatch",
        "jev-review-gate",
        "prepare_review_flags",
        "review_flags",
        "jev-review-gate",
    ),
    RoutingInterventionCase(
        "jev-review-gate-paraphrase",
        "Running a diff through Jev reaches jev-review-gate",
        "run this diff through jev",
        "dispatch",
        "jev-review-gate",
        "prepare_review_flags",
        "review_flags",
        "jev-review-gate",
    ),
    RoutingInterventionCase(
        "jev-action-check-phrase",
        "Asking Jev whether a command is safe reaches jev-action-check",
        "ask jev if this rm -rf command is safe",
        "dispatch",
        "jev-action-check",
        "prepare_action_hold_check",
        "action_hold_check",
        "jev-action-check",
    ),
    RoutingInterventionCase(
        "jev-action-check-paraphrase",
        "Having Jev check a command before it runs reaches jev-action-check",
        "have jev check whether this command is safe to run",
        "dispatch",
        "jev-action-check",
        "prepare_action_hold_check",
        "action_hold_check",
        "jev-action-check",
    ),
    RoutingInterventionCase(
        "jev-done-check-phrase",
        "Asking Jev whether a task is done reaches jev-done-check",
        "ask jev if this task is done given the test output",
        "dispatch",
        "jev-done-check",
        "prepare_completion_objection_check",
        "completion_objection_check",
        "jev-done-check",
    ),
    RoutingInterventionCase(
        "jev-done-check-paraphrase",
        "Letting Jev check a completion claim reaches jev-done-check",
        "let jev check whether the task is finished given this test output",
        "dispatch",
        "jev-done-check",
        "prepare_completion_objection_check",
        "completion_objection_check",
        "jev-done-check",
    ),
    RoutingInterventionCase(
        "jev-done-check-partner-swap",
        "A Jev-addressed message the verification gate would own swaps to its Jev sibling",
        "have jev look at this before I merge",
        "dispatch",
        "jev-done-check",
        "prepare_completion_objection_check",
        "completion_objection_check",
        "jev-done-check",
    ),
    # Re-pinned to clarify (shortlist-first; request shapes removed 2026-09-26): `review` is a
    # token, so the route asks; code-review, the declined winner, leads the shortlist.
    RoutingInterventionCase(
        "jev-mention-review-stays-code-review",
        "Reviewing a PR about a Jev plugin stays code-review; nobody asked Jev",
        "review the jev plugin PR before merge",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "code-review",
    ),
    # Re-pinned to clarify (shortlist-first; request shapes removed 2026-09-26): `review` is a
    # token, so the route asks; code-review, the declined winner, leads the shortlist.
    RoutingInterventionCase(
        "jev-tool-name-review-stays-code-review",
        "A diff that adds omh_jev_ask stays code-review; the tool name is not an address",
        "review this diff that adds the omh_jev_ask tool",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "code-review",
    ),
    RoutingInterventionCase(
        "jev-comparison-stays-code-review",
        "Comparing Jev with GPT for code review stays code-review",
        "compare jev with gpt for code review",
        "dispatch",
        "code-review",
        "choose_executor",
        "handoff",
        "code-review",
    ),
    # Re-pinned to clarify (shortlist-first, owner decision 2026-09-26): the winner's evidence is
    # tokens or a context-only guard, so the route asks; the declined winner, agent-debug, leads
    # the shortlist.
    RoutingInterventionCase(
        "jev-plugin-debug-stays-agent-debug",
        "Debugging a looping Jev plugin stays agent-debug",
        "debug why the jev plugin keeps looping",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "agent-debug",
    ),
    # Re-pinned to clarify (shortlist-first, owner decision 2026-09-26): the winner's evidence is
    # tokens or a context-only guard, so the route asks; the declined winner, skill, leads
    # the shortlist.
    RoutingInterventionCase(
        "jev-skill-authoring-stays-skill",
        "Creating a skill that calls Jev stays with skill management",
        "create a skill that calls jev for routing",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "skill",
    ),
    # Re-pinned to clarify (shortlist-first, owner decision 2026-09-26): the winner's evidence is
    # tokens or a context-only guard, so the route asks; the declined winner, verification-gate, leads
    # the shortlist.
    RoutingInterventionCase(
        "jev-integration-verify-stays-verification-gate",
        "Verifying a Jev integration stays verification-gate",
        "verify the jev integration works before merge",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "verification-gate",
    ),
    RoutingInterventionCase(
        "ask-claude-stays-ask",
        "Asking Claude for advice stays with the ask skill",
        "ask claude to review this plan",
        "dispatch",
        "ask",
        "forward_plan_to_selected_workflow",
        "plan",
        "ask",
    ),
    # Re-pinned to clarify (2026-09-26): the guard that carried this dispatch
    # measured under 3 right per wrong on the tuning set, so it is context-only
    # and the route asks; the declined winner, research-brief, leads the shortlist.
    RoutingInterventionCase(
        "vendor-choice-naming-jev-not-jev-ask",
        "Choosing between vendors that include Jev is not a typed Jev ask",
        "help me decide between two vendors, jev or openrouter",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "research-brief",
    ),
    RoutingInterventionCase(
        "jev-skill-install-stays-router",
        "Installing a Jev skill stays with the OMH router",
        "install the jev skill from the catalog",
        "dispatch",
        "oh-my-hermes",
        "choose_skill",
        "skill_picker",
        "oh-my-hermes",
    ),
    # Review-round cases. Descriptive frames ("the jev check", "we use jev"),
    # negations ("don't ask jev"), Jev among options, maintainer mentions of a
    # Jev skill's name, and an explicit non-Jev invocation all keep their
    # ordinary owner; free-form yes/no questions stay on jev-ask instead of a
    # preset. Three configuration sentences pin today's owner only because a
    # dispatch cannot be a negative control: their claim is that no Jev skill
    # takes them, and a better owner may replace the pinned one.
    # Re-pinned to clarify (shortlist-first, owner decision 2026-09-26): the winner's evidence is
    # tokens or a context-only guard, so the route asks; the declined winner, oh-my-hermes, leads
    # the shortlist.
    RoutingInterventionCase(
        "jev-doctor-check-line-stays-router",
        "The doctor's Jev check line is a status question, not a Jev ask",
        "the jev check in omh doctor is failing",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "oh-my-hermes",
    ),
    RoutingInterventionCase(
        "jev-doctor-key-missing-stays-toolbelt",
        "Asking why the doctor's Jev check reports a missing key stays with toolbelt readiness",
        "why does the jev check in doctor say key missing",
        "dispatch",
        "toolbelt-readiness",
        "prepare_toolbelt_readiness",
        "toolbelt_readiness",
        "toolbelt-readiness",
    ),
    # Re-pinned to clarify (2026-09-26): the guard that carried this dispatch
    # measured under 3 right per wrong on the tuning set, so it is context-only
    # and the route asks; the declined winner, ops-observability-card, leads the shortlist.
    RoutingInterventionCase(
        "jev-production-latency-stays-observability",
        "Describing Jev in production is an observability question, not a Jev ask",
        "we use jev in production and latency doubled, why?",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "ops-observability-card",
    ),
    RoutingInterventionCase(
        "explicit-code-review-beats-declined-jev",
        "An explicit code-review invocation that declines Jev stays code-review",
        "use omh-code-review on this PR, and don't ask jev",
        "dispatch",
        "code-review",
        "choose_executor",
        "handoff",
        "code-review",
    ),
    RoutingInterventionCase(
        "slash-code-review-beats-later-jev",
        "A slash code-review invocation stays code-review even when Jev is mentioned for later",
        "/omh-code-review this PR; we can ask jev later",
        "dispatch",
        "code-review",
        "choose_executor",
        "handoff",
        "code-review",
    ),
    # Re-pinned to clarify (shortlist-first; request shapes removed 2026-09-26): `review` is a
    # token, so the route asks; code-review, the declined winner, leads the shortlist.
    RoutingInterventionCase(
        "jev-skill-file-review-stays-code-review",
        "Reviewing a Jev skill's SKILL.md diff is ordinary code review, like any skill file",
        "review the omh-jev-action-check SKILL.md diff",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "code-review",
    ),
    RoutingInterventionCase(
        "jev-skill-bug-fix-stays-ultrawork",
        "Fixing a bug in a Jev skill is ordinary maintenance, like any skill",
        "fix the bug in omh-jev-review-gate",
        "dispatch",
        "ultrawork",
        "choose_executor",
        "handoff",
        "ultrawork",
    ),
    # Re-pinned to clarify (shortlist-first, owner decision 2026-09-26): the winner's evidence is
    # tokens or a context-only guard, so the route asks; the declined winner, code-review, leads
    # the shortlist.
    RoutingInterventionCase(
        "decide-jev-or-claude-not-jev-skill",
        "Deciding whether to use Jev or Claude for review never reaches a Jev skill",
        "help me decide whether to use jev or claude for review",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "code-review",
    ),
    # Re-pinned to clarify (shortlist-first, owner decision 2026-09-26): the winner's evidence is
    # tokens or a context-only guard, so the route asks; the declined winner, code-review, leads
    # the shortlist.
    RoutingInterventionCase(
        "declined-jev-review-stays-code-review",
        "Declining Jev before a review keeps the review with code-review",
        "don't ask jev, just review this diff",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "code-review",
    ),
    RoutingInterventionCase(
        "declined-jev-command-stays-operator",
        "Declining Jev before a command keeps it with the command operator",
        "never ask jev about this command, just run it",
        "dispatch",
        "command-operator",
        "prepare_command_operator_card",
        "command_operator",
        "command-operator",
    ),
    RoutingInterventionCase(
        "slash-code-review-then-jev-stays-code-review",
        "A slash code-review invocation wins over a trailing Jev mention",
        "/omh-code-review this diff and ask jev too",
        "dispatch",
        "code-review",
        "choose_executor",
        "handoff",
        "code-review",
    ),
    RoutingInterventionCase(
        "use-omh-code-review-then-jev-stays-code-review",
        "A use-omh code-review invocation wins over a trailing Jev mention",
        "use omh code-review on this diff, then ask jev",
        "dispatch",
        "code-review",
        "choose_executor",
        "handoff",
        "code-review",
    ),
    RoutingInterventionCase(
        "jev-openrouter-setup-not-jev-ask",
        "Setting up the Jev route in OpenRouter is configuration; the pinned owner is today's, the claim is that no Jev skill takes it",
        "set up the jev route in openrouter",
        "dispatch",
        "ultrawork",
        "choose_executor",
        "handoff",
        "ultrawork",
    ),
    RoutingInterventionCase(
        "jev-router-model-setting-not-jev-ask",
        "Using Jev as the router model is configuration; the pinned owner is today's, the claim is that no Jev skill takes it",
        "use jev as my router model",
        "dispatch",
        "workflow-learning",
        "audit_learning_readiness",
        "workflow_learning",
        "workflow-learning",
    ),
    RoutingInterventionCase(
        "typesafe-typescript-not-jev",
        "The word typesafe in a TypeScript request is not Jev; the pinned owner is today's, the claim is that no Jev skill takes it",
        "make this API typesafe in TypeScript",
        "dispatch",
        "ultrawork",
        "choose_executor",
        "handoff",
        "ultrawork",
    ),
    RoutingInterventionCase(
        "jev-ask-patch-notes-question",
        "A yes/no question about patch notes is a free-form Jev ask, not a review preset",
        "ask jev whether the patch notes mention rollback",
        "dispatch",
        "jev-ask",
        "prepare_typed_ask",
        "typed_ask",
        "jev-ask",
    ),
    RoutingInterventionCase(
        "jev-ask-pr-description-question",
        "A question about a PR description's clarity is a free-form Jev ask, not a review preset",
        "ask jev if this PR description is clear",
        "dispatch",
        "jev-ask",
        "prepare_typed_ask",
        "typed_ask",
        "jev-ask",
    ),
    RoutingInterventionCase(
        "jev-ask-doc-section-question",
        "Whether a doc section is complete is a free-form Jev ask, not a done-check preset",
        "ask jev whether this doc section is complete",
        "dispatch",
        "jev-ask",
        "prepare_typed_ask",
        "typed_ask",
        "jev-ask",
    ),
    RoutingInterventionCase(
        "jev-ask-command-palette-docs-question",
        "A question about command palette docs is a free-form Jev ask, not an action check",
        "ask jev whether the command palette docs are clear",
        "dispatch",
        "jev-ask",
        "prepare_typed_ask",
        "typed_ask",
        "jev-ask",
    ),
    RoutingInterventionCase(
        "jev-vocative-readme-question",
        "Addressing Jev by name with a question about a README reaches jev-ask",
        "jev, is this README clear?",
        "dispatch",
        "jev-ask",
        "prepare_typed_ask",
        "typed_ask",
        "jev-ask",
    ),
    RoutingInterventionCase(
        "jev-check-imperative-command",
        "A message that opens with jev check and names a command reaches jev-action-check",
        "jev check this command before I run it",
        "dispatch",
        "jev-action-check",
        "prepare_action_hold_check",
        "action_hold_check",
        "jev-action-check",
    ),
    RoutingInterventionCase(
        "decision-prototype-natural-language",
        "A bounded pre-plan spike reaches decision prototype",
        "Before we plan the migration, run a small spike to test the risky cache assumption.",
        "dispatch",
        "decision-prototype",
        "prepare_decision_prototype",
        "decision_prototype",
        "decision-prototype",
    ),
    RoutingInterventionCase(
        "lifecycle-growth-natural-language",
        "An onboarding experiment reaches lifecycle growth",
        "Design an onboarding journey experiment to improve activation while respecting consent and frequency limits.",
        "dispatch",
        "lifecycle-growth",
        "prepare_lifecycle_growth",
        "lifecycle_growth",
        "lifecycle-growth",
    ),
    RoutingInterventionCase(
        "lifecycle-growth-korean",
        "A Korean onboarding journey reaches lifecycle growth",
        "온보딩 여정의 활성화 실험을 설계하고 싶어요.",
        "dispatch",
        "lifecycle-growth",
        "prepare_lifecycle_growth",
        "lifecycle_growth",
        "lifecycle-growth",
    ),
    RoutingInterventionCase(
        "product-discovery-validation-natural-language",
        "A pre-PRD customer-problem decision reaches product discovery validation",
        "Validate whether this early idea solves a real customer problem before we write a PRD.",
        "dispatch",
        "product-discovery-validation",
        "prepare_product_discovery_validation",
        "product_discovery_validation",
        "product-discovery-validation",
    ),
    RoutingInterventionCase(
        "customer-interviews-before-prd-reach-product-discovery-validation",
        "Active customer interviews stay in discovery before PRD creation",
        "Validate this idea with customer interviews before we write a PRD.",
        "dispatch",
        "product-discovery-validation",
        "prepare_product_discovery_validation",
        "product_discovery_validation",
        "product-discovery-validation",
    ),
    RoutingInterventionCase(
        "product-discovery-validation-korean",
        "A Korean customer-discovery decision reaches product discovery validation",
        "고객 발견 검증을 통해 이 아이디어를 계속할지 결정하고 싶어요.",
        "dispatch",
        "product-discovery-validation",
        "prepare_product_discovery_validation",
        "product_discovery_validation",
        "product-discovery-validation",
    ),
    RoutingInterventionCase(
        "validated-discovery-prd-reaches-product-brief",
        "A completed discovery result reaches the downstream PRD workflow",
        "Write a PRD from these already validated customer discovery findings.",
        "dispatch",
        "product-brief",
        "prepare_product_brief",
        "product_brief",
        "product-brief",
    ),
    RoutingInterventionCase(
        "approved-lifecycle-copy-reaches-content-operator",
        "A completed lifecycle experiment hands one-off copy to content",
        "Write only the onboarding email copy for this approved lifecycle growth experiment.",
        "dispatch",
        "content-operator",
        "prepare_content_operator_card",
        "content_operator",
        "content-operator",
    ),
    RoutingInterventionCase(
        "sales-pipeline-review-natural-language",
        "A portfolio forecast request reaches sales pipeline review",
        "Review this week's pipeline export for stale deals, slipped close dates, and forecast calibration.",
        "dispatch",
        "sales-pipeline-review",
        "prepare_sales_pipeline_review",
        "sales_pipeline_review",
        "sales-pipeline-review",
    ),
    RoutingInterventionCase(
        "sales-pipeline-review-korean",
        "A Korean pipeline review reaches sales pipeline review",
        "이번 주 파이프라인 리뷰에서 정체된 딜과 영업 예측 보정을 확인해 주세요.",
        "dispatch",
        "sales-pipeline-review",
        "prepare_sales_pipeline_review",
        "sales_pipeline_review",
        "sales-pipeline-review",
    ),
    # Point-in-time web evidence (#1403). Before the guard, a pricing noun
    # sent the as-of question to research-brief, a page noun to the browser
    # operator, and the Korean archive-capture request to the workspace file
    # operator; each would have answered from a live page.
    RoutingInterventionCase(
        "as-of-pricing-page-reaches-web-research",
        "An as-of question about a vendor page reaches the web lookup lane, not a market brief",
        "what did the vendor pricing page say as of 2026-06-01? use archived captures and cite them",
        "dispatch",
        "web-research",
        "run_hermes_research",
        "web_research",
        "web-research",
    ),
    RoutingInterventionCase(
        "then-versus-now-snapshot-reaches-web-research",
        "A then-versus-now snapshot comparison reaches the web lookup lane, not the browser operator",
        "then versus now: what changed on their pricing page since the archived capture",
        "dispatch",
        "web-research",
        "run_hermes_research",
        "web_research",
        "web-research",
    ),
    RoutingInterventionCase(
        "page-as-it-was-reaches-web-research",
        "A page-as-it-was request reaches the web lookup lane instead of clarification",
        "show me the page as it was on 2026-06-01",
        "dispatch",
        "web-research",
        "run_hermes_research",
        "web_research",
        "web-research",
    ),
    RoutingInterventionCase(
        "korean-archive-capture-reaches-web-research",
        "A Korean as-of archive-capture request reaches the web lookup lane, not the file operator",
        "2026년 6월 1일 기준으로 그 페이지에 뭐라고 써 있었는지 아카이브 캡처로 확인해줘",
        "dispatch",
        "web-research",
        "run_hermes_research",
        "web_research",
        "web-research",
    ),
    RoutingInterventionCase(
        "realtime-voice-adoption-reaches-connector-readiness",
        "Realtime voice adoption is a connector-readiness question, not a missing-tool one",
        "realtime voice connector readiness before we adopt it for support calls",
        "dispatch",
        "external-connector-readiness",
        "prepare_external_connector_readiness",
        "external_connector_readiness",
        "external-connector-readiness",
    ),
    RoutingInterventionCase(
        "voice-trial-receipt-reaches-connector-readiness",
        "A supplied voice trial receipt is judged by the connector-readiness lane",
        "voice connector trial receipt from the telephony gateway needs a verdict",
        "dispatch",
        "external-connector-readiness",
        "prepare_external_connector_readiness",
        "external_connector_readiness",
        "external-connector-readiness",
    ),
    RoutingInterventionCase(
        "voice-turn-integrity-reaches-connector-readiness",
        "Turn integrity and barge-in questions reach the connector-readiness lane",
        "check the voice turn integrity and barge-in behavior in that trial",
        "dispatch",
        "external-connector-readiness",
        "prepare_external_connector_readiness",
        "external_connector_readiness",
        "external-connector-readiness",
    ),
    RoutingInterventionCase(
        "korean-realtime-voice-readiness-reaches-connector-readiness",
        "A Korean realtime voice readiness request reaches the connector-readiness lane",
        "실시간 음성 커넥터 준비도를 도입 전에 확인해줘",
        "dispatch",
        "external-connector-readiness",
        "prepare_external_connector_readiness",
        "external_connector_readiness",
        "external-connector-readiness",
    ),
    RoutingInterventionCase(
        "continuous-watch-reaches-the-recurring-surface-comparison",
        "A watch with no cadence reaches the lane that compares the four recurring surfaces",
        "keep watching the deploy status and tell me when it changes",
        "dispatch",
        "automation-blueprint",
        "prepare_scheduled_ops_blueprint",
        "automation_blueprint",
        "automation-blueprint",
    ),
    # Re-pinned to clarify (2026-09-26): the guard that carried this dispatch
    # measured under 3 right per wrong on the tuning set, so it is context-only
    # and the route asks; the declined winner, automation-blueprint, leads the shortlist.
    RoutingInterventionCase(
        "named-cadence-reaches-the-recurring-surface-comparison",
        "A named cadence reaches the same lane, where the schedule beats the other three",
        "every weekday morning check the error budget and post a digest",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "automation-blueprint",
    ),
    RoutingInterventionCase(
        "memory-provider-migration-reaches-the-trial-lane",
        "Migrating a memory provider with a rollback reaches the connector-trial lane",
        "migrate our memory provider and roll back if it is worse",
        "dispatch",
        "external-connector-readiness",
        "prepare_external_connector_readiness",
        "external_connector_readiness",
        "external-connector-readiness",
    ),
    RoutingInterventionCase(
        "generated-path-in-a-diff-reaches-the-verification-gate",
        "Asking whether a diff touched a generated file reaches the provenance row",
        "did this diff touch a generated file",
        "dispatch",
        "verification-gate",
        "prepare_verification_gate",
        "verification_gate",
        "verification-gate",
    ),
    RoutingInterventionCase(
        "generated-file-to-attach-stays-a-deliverable",
        "The same words without a provenance cue stay in the delivery lane",
        "attach the generated file to the ticket",
        "dispatch",
        "deliverable-package",
        "prepare_deliverable_package",
        "deliverable_package",
        "deliverable-package",
    ),
    RoutingInterventionCase(
        "dependency-upgrade-reaches-the-phased-refactor-plan",
        "A major dependency upgrade reaches the phased planner, not the generic plan lane",
        "major dependency upgrade plan with rollback",
        "dispatch",
        "refactor-plan",
        "prepare_refactor_plan",
        "refactor_plan",
        "refactor-plan",
    ),
    RoutingInterventionCase(
        "framework-major-version-upgrade-reaches-the-phased-refactor-plan",
        "The framework phrasing reaches the same lane without the word refactor",
        "we need a major version upgrade of the framework, sequence it with rollback points",
        "dispatch",
        "refactor-plan",
        "prepare_refactor_plan",
        "refactor_plan",
        "refactor-plan",
    ),
    RoutingInterventionCase(
        "dependabot-version-bump-reaches-the-upgrade-plan",
        "A dependabot bump with no advisory is upgrade work, not a PR event",
        "dependabot bumped express 4.18 to 5.0, safe to merge",
        "dispatch",
        "refactor-plan",
        "prepare_refactor_plan",
        "refactor_plan",
        "refactor-plan",
    ),
    RoutingInterventionCase(
        "dependabot-opened-bump-pr-reaches-the-upgrade-plan",
        "A bump that arrives as an opened PR still reaches the upgrade plan",
        "dependabot opened a PR bumping express from 4.18 to 5.0",
        "dispatch",
        "refactor-plan",
        "prepare_refactor_plan",
        "refactor_plan",
        "refactor-plan",
    ),
    RoutingInterventionCase(
        "spoken-framework-version-jump-reaches-the-upgrade-plan",
        "A spoken version jump names no upgrade phrase and still reaches the plan",
        "upgrade react from 18 to 19",
        "dispatch",
        "refactor-plan",
        "prepare_refactor_plan",
        "refactor_plan",
        "refactor-plan",
    ),
    RoutingInterventionCase(
        "spoken-runtime-version-jump-reaches-the-upgrade-plan",
        "A runtime version jump reaches the same plan",
        "upgrade python from 3.11 to 3.13",
        "dispatch",
        "refactor-plan",
        "prepare_refactor_plan",
        "refactor_plan",
        "refactor-plan",
    ),
    RoutingInterventionCase(
        "openapi-consumer-question-reaches-the-contract-owner",
        "Who breaks when a field leaves the spec reaches the skill that owns the spec",
        "which consumers break if I remove this field from the OpenAPI spec",
        "dispatch",
        "backend",
        "prepare_backend_handoff",
        "backend_contract",
        "backend",
    ),
    RoutingInterventionCase(
        "endpoint-deprecation-reaches-the-contract-owner",
        "A deprecation with a sunset date reaches the same lane",
        "deprecate this endpoint and set a sunset date",
        "dispatch",
        "backend",
        "prepare_backend_handoff",
        "backend_contract",
        "backend",
    ),
    RoutingInterventionCase(
        "credential-rotation-reaches-the-security-review",
        "Replacing a live credential reaches the lane that carries the cutover order",
        "rotate this api key without an outage",
        "dispatch",
        "security-safety-review",
        "prepare_security_safety_review",
        "security_safety_review",
        "security-safety-review",
    ),
    RoutingInterventionCase(
        "rotation-proof-is-not-a-missing-tool",
        "An existing credential being replaced is not a readiness gap",
        "credential rotation sequence and proof the old key is dead",
        "dispatch",
        "security-safety-review",
        "prepare_security_safety_review",
        "security_safety_review",
        "security-safety-review",
    ),
    RoutingInterventionCase(
        "missing-api-key-stays-a-readiness-gap",
        "Not having a credential still reaches the missing-capability inventory",
        "i do not have an api key for this connector",
        "dispatch",
        "toolbelt-readiness",
        "prepare_toolbelt_readiness",
        "toolbelt_readiness",
        "toolbelt-readiness",
    ),
    RoutingInterventionCase(
        "contract-redline-reaches-the-legal-review",
        "Redlining a contract against a playbook reaches the counsel-hold lane",
        "redline this contract against our playbook",
        "dispatch",
        "legal-compliance-review",
        "prepare_legal_compliance_review",
        "legal_compliance_review",
        "legal-compliance-review",
    ),
    RoutingInterventionCase(
        "negotiation-preparation-reaches-the-legal-review",
        "Fallback positions and clause language reach the same lane",
        "prepare negotiation positions and fallback clause language",
        "dispatch",
        "legal-compliance-review",
        "prepare_legal_compliance_review",
        "legal_compliance_review",
        "legal-compliance-review",
    ),
    RoutingInterventionCase(
        "hire-outsource-or-cut-scope-reaches-the-decision-brief",
        "A resourcing decision reaches the options-and-tradeoffs lane",
        "do we hire, outsource, or cut scope for this quarters demand",
        "dispatch",
        "strategy-brief",
        "prepare_strategy_brief",
        "strategy_brief",
        "strategy-brief",
    ),
    # The three skills retired by #1691, typed by their own canonical name.
    # This is the promise the retirement makes -- nothing a person types stops
    # working -- stated as a case per contract, so a later trigger edit that
    # drops a folded phrase fails here instead of going quiet. Each lands on
    # the target home the exposure row names.
    RoutingInterventionCase(
        "retired-performance-goal-reaches-ultraperf",
        "The retired performance-goal name still reaches the measured optimization loop",
        "performance-goal",
        "dispatch",
        "ultraperf",
        "prepare_ultraperf_loop",
        "ultraperf_loop",
    ),
    RoutingInterventionCase(
        "retired-best-practice-research-reaches-web-research",
        "The retired best-practice-research name still reaches the cited web lookup lane",
        "best-practice-research",
        "dispatch",
        "web-research",
        "run_hermes_research",
        "web_research",
    ),
    RoutingInterventionCase(
        "retired-autoresearch-goal-reaches-research",
        "The retired autoresearch-goal name still reaches the research engine",
        "autoresearch-goal",
        "dispatch",
        "research",
        "run_hermes_research",
        "web_research",
    ),
    # Dispatch evidence, the positive half. Request shapes dispatch their own
    # skill (a review verb on a change set), and the guards tightened alongside
    # the gate still dispatch theirs: a code object under a code-edit verb, a
    # recurring check with a cadence, a named coding agent asked to deliver.
    # Re-pinned to clarify (shortlist-first; request shapes removed 2026-09-26): `review` is a
    # token, so the route asks; code-review, the declined winner, leads the shortlist.
    RoutingInterventionCase(
        "review-my-change-asks-with-code-review-first",
        "A review verb on a change set asks, with code-review first on the shortlist",
        "review my change for the export feature",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "code-review",
    ),
    RoutingInterventionCase(
        "code-object-rename-still-dispatches-delivery",
        "A code-edit verb on a function in a module is still a one-cycle code edit",
        "rename the helper function in the parser module",
        "dispatch",
        "ultrawork",
        "choose_executor",
        "handoff",
        "ultrawork",
    ),
    RoutingInterventionCase(
        "flaky-test-fix-still-dispatches-delivery",
        "A fix on a named test is still a one-cycle code edit",
        "fix the flaky checkout test",
        "dispatch",
        "ultrawork",
        "choose_executor",
        "handoff",
        "ultrawork",
    ),
    # Re-pinned to clarify (2026-09-26): the guard that carried this dispatch
    # measured under 3 right per wrong on the tuning set, so it is context-only
    # and the route asks; the declined winner, automation-blueprint, leads the shortlist.
    RoutingInterventionCase(
        "recurring-weekly-check-still-schedules",
        "`recurring` beside a cadence and a check is still a scheduled job",
        "set up a recurring weekly check of our uptime report",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "automation-blueprint",
    ),
    RoutingInterventionCase(
        "named-agent-fix-still-delivers",
        "A named coding agent asked to fix something is still a delivery handoff",
        "have codex fix the flaky checkout test",
        "dispatch",
        "ultrawork",
        "send_to_executor",
        "handoff",
        "ultrawork",
    ),
    # Moved from the negative controls: "check" plus a diff is a review
    # request with its object named, so it dispatches code-review through the
    # review-object shape -- not verification-gate on `before` and `merge`.
    # Re-pinned to clarify (shortlist-first; request shapes removed): `check`, `before`, and
    # `merge` are tokens, so the route asks; verification-gate, the declined winner, leads the
    # shortlist, with code-review allowed as the owner by the coordinator's decision.
    RoutingInterventionCase(
        "check-diff-before-merge-asks-with-a-review-lane-first",
        "A check verb on a diff asks, with verification-gate first on the shortlist",
        "check this diff before I merge it",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "verification-gate",
    ),
    # Shortlist-first follow-up, the positive half: canonical requests that
    # carry no phrase of their own ask, with the intended skill FIRST on the
    # shortlist; the cadence rule still dispatches the scheduler.
    # Shortlist-first, request shapes removed: a canonical request without a phrase of its own
    # asks, and build-failure-triage must be the FIRST candidate.
    RoutingInterventionCase(
        "failing-release-build-asks-with-triage-first",
        "A failing build on a release branch asks, with build-failure-triage first",
        "the nightly build is failing on the release branch",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "build-failure-triage",
    ),
    # Shortlist-first, request shapes removed: a canonical request without a phrase of its own
    # asks, and deploy-and-monitor must be the FIRST candidate.
    RoutingInterventionCase(
        "deploy-to-production-asks-with-deploy-and-monitor-first",
        "A deploy command to production asks, with deploy-and-monitor first",
        "ship the new checkout service to production",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "deploy-and-monitor",
    ),
    RoutingInterventionCase(
        "issue-filing-shape-dispatches-intake",
        "A filing command for a defect on GitHub dispatches issue intake",
        "open an issue on GitHub for the upload crash",
        "dispatch",
        "github-issue-intake",
        "prepare_github_issue_intake",
        "github_issue_intake",
        "github-issue-intake",
    ),
    # Shortlist-first, request shapes removed: a canonical request without a phrase of its own
    # asks, and ultrawork must be the FIRST candidate.
    RoutingInterventionCase(
        "repair-on-a-worker-asks-with-delivery-first",
        "A repair command on a running part of the system asks, with ultrawork first",
        "fix the noisy logs in the billing worker",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "ultrawork",
    ),
    # Re-pinned to clarify (2026-09-26): the guard that carried this dispatch
    # measured under 3 right per wrong on the tuning set, so it is context-only
    # and the route asks; the declined winner, automation-blueprint, leads the shortlist.
    RoutingInterventionCase(
        "recurring-issue-recap-reaches-the-scheduler",
        "A recap of new GitHub issues on a cadence is a scheduled job, not issue filing",
        "put together a recap of new GitHub issues every morning",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "automation-blueprint",
    ),
    # `browser-operator`'s natural reach had rested on one guard-carried case,
    # which asks now that the guard's measured record is under 3:1. This one
    # reaches it through its own multi-word trigger ("playwright task"), not its
    # name and not a guard; its negative half is
    # `playwright-task-cost-question-is-not-a-browser-run`.
    RoutingInterventionCase(
        "playwright-task-reaches-browser-operator",
        "A Playwright task on a live page reaches the browser lane on its own phrase",
        "run a playwright task that logs in and screenshots the dashboard",
        "dispatch",
        "browser-operator",
        "prepare_browser_operator_card",
        "browser_operator",
        "browser-operator",
    ),
    # The positive halves of the #1892 negative controls. A cadence phrase in a
    # request still dispatches on its own; a command to fix a product defect
    # asks with the coding lane first instead of triaging it as feedback; and
    # a report of the same defect, with no command, still triages.
    RoutingInterventionCase(
        "cadence-request-still-dispatches-automation",
        "A request that opens on its cadence still opens automation blueprint",
        "every morning send me the build status",
        "dispatch",
        "automation-blueprint",
        "prepare_scheduled_ops_blueprint",
        "automation_blueprint",
    ),
    # Subject-initial and passive scheduling requests (#1893 review): a clause
    # about a thing that carries a directive modal or a passive of a delivery
    # verb reads as a request, so the cadence phrase keeps its evidence.
    # The first four are the review's sentences; the last three share the shape.
    RoutingInterventionCase(
        "cadence-modal-passive-email-dispatches",
        "A thing that should be emailed every morning is a schedule",
        "every morning the sales numbers should be emailed to the team",
        "dispatch",
        "automation-blueprint",
        "prepare_scheduled_ops_blueprint",
        "automation_blueprint",
    ),
    RoutingInterventionCase(
        "cadence-get-passive-send-dispatches",
        "A snapshot that gets sent every morning is a schedule",
        "every morning our dashboard snapshot gets sent to leadership",
        "dispatch",
        "automation-blueprint",
        "prepare_scheduled_ops_blueprint",
        "automation_blueprint",
    ),
    RoutingInterventionCase(
        "cadence-modal-post-dispatches",
        "Results that should post every day are a schedule",
        "every day the CI results should post to the team channel",
        "dispatch",
        "automation-blueprint",
        "prepare_scheduled_ops_blueprint",
        "automation_blueprint",
    ),
    RoutingInterventionCase(
        "cadence-modal-go-to-dispatches",
        "A report that should go to Slack every morning is a schedule",
        "every morning the report should go to Slack",
        "dispatch",
        "automation-blueprint",
        "prepare_scheduled_ops_blueprint",
        "automation_blueprint",
    ),
    RoutingInterventionCase(
        "cadence-get-passive-post-dispatches",
        "A summary that gets posted every morning is a schedule",
        "every morning the overnight error summary gets posted to the ops channel",
        "dispatch",
        "automation-blueprint",
        "prepare_scheduled_ops_blueprint",
        "automation_blueprint",
    ),
    RoutingInterventionCase(
        "cadence-needs-to-dispatches",
        "A report that needs to go out every day is a schedule",
        "every day the backlog report needs to go to the product leads",
        "dispatch",
        "automation-blueprint",
        "prepare_scheduled_ops_blueprint",
        "automation_blueprint",
    ),
    RoutingInterventionCase(
        "cadence-must-be-shared-dispatches",
        "Numbers that must be shared every morning are a schedule",
        "every morning the uptime numbers must be shared with the on-call team",
        "dispatch",
        "automation-blueprint",
        "prepare_scheduled_ops_blueprint",
        "automation_blueprint",
    ),
    RoutingInterventionCase(
        "commanded-payment-crash-fix-asks-with-coding-first",
        "A command to fix a checkout crash asks with the coding lane first",
        "fix the checkout crash in the payment service",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "ultrawork",
    ),
    RoutingInterventionCase(
        "checkout-crash-report-still-triages",
        "A report that the checkout page crashes still routes to triage",
        "the checkout page crashes on submit",
        "dispatch",
        "feedback-triage",
        "triage_feedback",
        "feedback_triage",
    ),
    # Skill-reach natural cases (`omh demo skill-reach`). Each skill below had
    # no intervention case dispatching to it without its name; each sentence
    # is a user's request built around one of its own non-name triggers.
    RoutingInterventionCase(
        "stuck-agent-retry-loop-reaches-agent-debug",
        "An agent stuck retrying a tool reaches agent debugging",
        "the agent run is stuck in a tool retry loop again, capture what it is doing",
        "dispatch",
        "agent-debug",
        "prepare_agent_debug",
        "agent_debug",
    ),
    # The five incident observables #1799 names, each in a user's words.
    RoutingInterventionCase(
        "looping-agent-reaches-agent-debug",
        "An agent looping on one tool call reaches agent debugging",
        "why does my agent keep looping on the same tool call",
        "dispatch",
        "agent-debug",
        "prepare_agent_debug",
        "agent_debug",
    ),
    RoutingInterventionCase(
        "repeated-agent-work-reaches-agent-debug",
        "An agent redoing work across turns reaches agent debugging",
        "the agent keeps redoing work across turns",
        "dispatch",
        "agent-debug",
        "prepare_agent_debug",
        "agent_debug",
    ),
    RoutingInterventionCase(
        "agent-goal-drift-reaches-agent-debug",
        "An agent drifting from its goal reaches agent debugging",
        "the agent drifted away from the goal I gave it, find out why",
        "dispatch",
        "agent-debug",
        "prepare_agent_debug",
        "agent_debug",
    ),
    RoutingInterventionCase(
        "agent-context-loss-reaches-agent-debug",
        "An agent losing context after compaction reaches agent debugging",
        "the agent lost context after compaction and forgot the plan",
        "dispatch",
        "agent-debug",
        "prepare_agent_debug",
        "agent_debug",
    ),
    RoutingInterventionCase(
        "agent-run-unexpected-cost-reaches-agent-debug",
        "An agent run that cost unexpectedly many tokens reaches agent debugging",
        "why did that agent run cost so many tokens",
        "dispatch",
        "agent-debug",
        "prepare_agent_debug",
        "agent_debug",
    ),
    RoutingInterventionCase(
        "behavior-preserving-module-refactor-reaches-slop-cleaner",
        "A refactor that must keep outputs reaches the slop cleaner",
        "do a behavior-preserving refactor of the billing module without changing its outputs",
        "dispatch",
        "ai-slop-cleaner",
        "present_plan",
        "plan",
    ),
    # The request-shaped `anti-slop pass` names the cleaner but, without a
    # second signal, asks first (score 7, medium): the bare word no longer
    # adds a token on top of the phrase.
    RoutingInterventionCase(
        "anti-slop-pass-names-slop-cleaner",
        "An anti-slop pass on a named directory asks first with the cleaner leading",
        "anti-slop pass on src/auth",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "ai-slop-cleaner",
    ),
    RoutingInterventionCase(
        "ai-slop-in-module-needs-cleanup-reaches-slop-cleaner",
        "AI slop in a module that needs cleanup reaches the slop cleaner",
        "the ai slop in this module needs cleanup",
        "dispatch",
        "ai-slop-cleaner",
        "forward_plan_to_selected_workflow",
        "plan",
    ),
    RoutingInterventionCase(
        "ai-slop-in-repo-reaches-slop-cleaner",
        "Cleaning AI slop out of a repo reaches the slop cleaner",
        "clean up the ai slop in this repo",
        "dispatch",
        "ai-slop-cleaner",
        "forward_plan_to_selected_workflow",
        "plan",
    ),
    RoutingInterventionCase(
        "ai-slop-in-code-reaches-slop-cleaner",
        "Cleaning up AI slop in a code directory reaches the slop cleaner",
        "clean up the AI slop in src/auth",
        "dispatch",
        "ai-slop-cleaner",
        "forward_plan_to_selected_workflow",
        "plan",
    ),
    RoutingInterventionCase(
        "deslop-review-reaches-slop-cleaner",
        "A no-edit deslop review reaches the slop cleaner's review mode",
        "deslop review the diff, do not edit",
        "dispatch",
        "ai-slop-cleaner",
        "forward_plan_to_selected_workflow",
        "plan",
    ),
    RoutingInterventionCase(
        "ai-slop-ui-stays-with-frontend",
        "AI slop named as a UI stays with frontend, not the code cleaner",
        "this dashboard looks like ai slop ui, redesign it",
        "dispatch",
        "frontend",
        "prepare_frontend_handoff",
        "frontend_handoff",
    ),
    RoutingInterventionCase(
        "generic-ai-slop-landing-page-stays-with-frontend",
        "Rejecting generic AI slop on a landing page stays with frontend",
        "reject generic AI slop in this landing page UI",
        "dispatch",
        "frontend",
        "prepare_frontend_handoff",
        "frontend_handoff",
    ),
    RoutingInterventionCase(
        "settings-page-feels-like-ai-slop-reaches-frontend",
        "A page that feels like AI slop is a restyle for frontend",
        "this settings page feels like AI slop",
        "dispatch",
        "frontend",
        "prepare_frontend_handoff",
        "frontend_handoff",
    ),
    # Frontend's appearance phrases are phrase evidence only beside a UI
    # surface, so on code and prose they do not compete: the cleaner leads.
    # A statement about a function, a README, an essay, or a PR description
    # stays a clarify (its own `ai slop` phrase alone is a medium score); a
    # module with a cleanup verb, or one to simplify without changing
    # behavior, is a request and dispatches.
    RoutingInterventionCase(
        "function-feels-like-ai-slop-leads-with-slop-cleaner",
        "A function that feels like AI slop asks first, with the cleaner leading",
        "this function feels like ai slop",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "ai-slop-cleaner",
    ),
    RoutingInterventionCase(
        "module-looks-like-ai-slop-clean-it-up-reaches-slop-cleaner",
        "A module that looks like AI slop, with a cleanup verb, dispatches the cleaner",
        "this module looks like ai slop, clean it up",
        "dispatch",
        "ai-slop-cleaner",
        "forward_plan_to_selected_workflow",
        "plan",
    ),
    RoutingInterventionCase(
        "readme-looks-like-ai-slop-leads-with-slop-cleaner",
        "A README that looks like AI slop leads with the cleaner, not frontend",
        "this README looks like ai slop",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "ai-slop-cleaner",
    ),
    RoutingInterventionCase(
        "module-slop-simplify-preserving-behavior-reaches-slop-cleaner",
        "A module called AI slop, to simplify without changing behavior, dispatches the cleaner",
        "the auth module looks like ai slop, simplify it without changing behavior",
        "dispatch",
        "ai-slop-cleaner",
        "forward_plan_to_selected_workflow",
        "plan",
    ),
    # A code unit beats a UI word: the UI word then says which code.
    RoutingInterventionCase(
        "layout-module-looks-like-ai-slop-leads-with-slop-cleaner",
        "A layout module that looks like AI slop asks first with the cleaner leading",
        "the layout module looks like ai slop, clean it up",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "ai-slop-cleaner",
    ),
    # Prose called AI slop is the cleaner's (its prose lexicon), not a
    # restyle: an essay and a PR description are cleaner targets and name no
    # UI surface, so frontend's appearance phrase no longer competes.
    RoutingInterventionCase(
        "essay-looks-like-ai-slop-leads-with-slop-cleaner",
        "An essay that looks like AI slop asks first with the cleaner leading, not frontend",
        "my essay looks like ai slop, make it better",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "ai-slop-cleaner",
    ),
    RoutingInterventionCase(
        "pr-description-looks-like-ai-slop-leads-with-slop-cleaner",
        "A PR description that looks like AI slop asks first with the cleaner leading",
        "the PR description looks like ai slop, make it better",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "ai-slop-cleaner",
    ),
    RoutingInterventionCase(
        "layout-code-looks-like-ai-slop-leads-with-slop-cleaner",
        "Layout code that looks like AI slop asks first with the cleaner leading",
        "the layout code looks like ai slop",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "ai-slop-cleaner",
    ),
    RoutingInterventionCase(
        "ui-component-file-looks-like-ai-slop-stays-with-frontend",
        "A UI component file that looks like AI slop stays a frontend restyle",
        "the pricing card component file looks like ai slop, simplify it",
        "dispatch",
        "frontend",
        "prepare_frontend_handoff",
        "frontend_handoff",
    ),
    # A UI surface called AI slop names nothing the cleaner can clean, so its
    # `ai slop` is no longer phrase evidence and frontend's appearance phrase
    # dispatches the restyle (it was a clarify led by frontend while the
    # cleaner's phrase competed).
    RoutingInterventionCase(
        "hero-section-screams-ai-slop-reaches-frontend",
        "A hero section that screams AI slop is a frontend restyle",
        "our hero section screams ai slop, give it a distinctive look",
        "dispatch",
        "frontend",
        "prepare_frontend_handoff",
        "frontend_handoff",
    ),
    RoutingInterventionCase(
        "onboarding-flow-looks-like-ai-slop-reaches-frontend",
        "An onboarding flow that looks like AI slop is a frontend restyle",
        "our onboarding flow looks like ai slop",
        "dispatch",
        "frontend",
        "prepare_frontend_handoff",
        "frontend_handoff",
    ),
    RoutingInterventionCase(
        "nav-menu-looks-like-ai-slop-reaches-frontend",
        "A nav menu that looks like AI slop is a frontend restyle",
        "the nav menu looks like ai slop",
        "dispatch",
        "frontend",
        "prepare_frontend_handoff",
        "frontend_handoff",
    ),
    RoutingInterventionCase(
        "pricing-page-screams-ai-slop-reaches-frontend",
        "A pricing page that screams AI slop is a frontend restyle",
        "our pricing page screams ai slop",
        "dispatch",
        "frontend",
        "prepare_frontend_handoff",
        "frontend_handoff",
    ),
    RoutingInterventionCase(
        "gemini-second-opinion-reaches-ask",
        "A second opinion from another model reaches the external advisor",
        "get me a second opinion from gemini on this caching design",
        "dispatch",
        "ask",
        "forward_plan_to_selected_workflow",
        "plan",
    ),
    RoutingInterventionCase(
        "buzz-community-connection-reaches-buzz",
        "Connecting Hermes to a Buzz community reaches the Buzz setup",
        "help me connect Hermes to Buzz so it can post in our community server",
        "dispatch",
        "buzz",
        "forward_plan_to_selected_workflow",
        "plan",
    ),
    RoutingInterventionCase(
        "abort-wrong-direction-run-reaches-cancel",
        "Aborting a run that went the wrong way reaches cancel",
        "please abort the run, it is going in the wrong direction",
        "dispatch",
        "cancel",
        "cancel",
        "cancellation",
    ),
    RoutingInterventionCase(
        "disable-project-memory-reaches-capability-toggle",
        "Turning memory off for a project reaches the capability toggle",
        "please disable memory for this project, I do not want it storing anything",
        "dispatch",
        "capability-toggle",
        "apply_capability_toggle",
        "capability_toggle",
    ),
    RoutingInterventionCase(
        "new-joiner-code-tour-reaches-codebase-onboarding",
        "A new joiner asking how a repo works reaches codebase onboarding",
        "I am new here, give me a codebase tour so I know how this repo works",
        "dispatch",
        "codebase-onboarding",
        "prepare_codebase_onboarding",
        "codebase_onboarding",
    ),
    RoutingInterventionCase(
        "refresh-code-map-reaches-codegraph-refresh",
        "Refreshing the code map of a directory reaches codegraph refresh",
        "refresh the code map for the services directory",
        "dispatch",
        "codegraph-refresh",
        "prepare_codegraph_refresh",
        "codegraph_refresh",
    ),
    RoutingInterventionCase(
        "linear-ticket-reaches-connector-operator",
        "Filing a Linear ticket reaches the connector operator",
        "create a linear ticket for the login timeout bug",
        "dispatch",
        "connector-operator",
        "prepare_connector_operator_card",
        "connector_operator",
    ),
    RoutingInterventionCase(
        "leadership-roadmap-review-reaches-cto-loop",
        "An engineering leadership review of a roadmap reaches the CTO loop",
        "run an engineering leadership review of our roadmap and delivery risk",
        "dispatch",
        "cto-loop",
        "run_cto_loop",
        "cto_loop",
    ),
    RoutingInterventionCase(
        "csv-anomaly-summary-reaches-data-analysis",
        "Summarizing anomalies in an exported CSV reaches data analysis",
        "here is last week's export, analyze this csv and summarize anomalies",
        "dispatch",
        "data-analysis",
        "prepare_data_analysis_card",
        "data_analysis",
    ),
    RoutingInterventionCase(
        "rejected-queue-alternative-reaches-decision-recall",
        "Recalling a rejected design alternative reaches decision recall",
        "remind me of the previously rejected alternative for the queue design",
        "dispatch",
        "decision-recall",
        "show_rejected_decision_recall",
        "decision_recall",
    ),
    RoutingInterventionCase(
        "staging-deploy-with-health-watch-reaches-deploy-and-monitor",
        "A deploy that also watches release health reaches deploy and monitor",
        "deploy this service to staging and keep an eye on release health",
        "dispatch",
        "deploy-and-monitor",
        "prepare_deploy_monitor_plan",
        "deploy_monitor_plan",
    ),
    RoutingInterventionCase(
        "product-design-handover-reaches-design-orchestration",
        "Handing over a product design reaches design orchestration",
        "can you handle this product design for the new checkout",
        "dispatch",
        "design-orchestration",
        "prepare_design_orchestration",
        "design_orchestration",
    ),
    RoutingInterventionCase(
        "swallowed-errors-hunt-reaches-failure-signal-audit",
        "Hunting empty catches and swallowed errors reaches the failure-signal audit",
        "find every empty catch and swallowed error in the sync service",
        "dispatch",
        "failure-signal-audit",
        "prepare_failure_signal_audit",
        "failure_signal_audit",
    ),
    RoutingInterventionCase(
        "discord-thread-status-update-reaches-gateway-intent",
        "A status update posted to a Discord thread reaches the gateway intent card",
        "post a status update in the discord thread when the build finishes",
        "dispatch",
        "gateway-intent-card",
        "prepare_gateway_intent_card",
        "gateway_intent",
    ),
    RoutingInterventionCase(
        "mcp-config-drift-reaches-harness-session-inventory",
        "MCP config drift between harnesses reaches the session inventory",
        "check for mcp drift between my claude and codex configs",
        "dispatch",
        "harness-session-inventory",
        "prepare_harness_session_inventory",
        "harness_session_inventory",
    ),
    RoutingInterventionCase(
        "instinct-candidates-promotion-reaches-instinct-ledger",
        "Promoting this week's instinct candidates reaches the instinct ledger",
        "show me the instinct candidates from this week that are ready for promotion",
        "dispatch",
        "instinct-ledger",
        "prepare_instinct_ledger",
        "instinct_ledger",
    ),
    RoutingInterventionCase(
        "weather-forecast-reaches-live-info-operator",
        "A weather forecast question reaches the live-info operator",
        "what is the weather forecast for Seoul tomorrow",
        "dispatch",
        "live-info-operator",
        "prepare_live_info_operator_card",
        "live_info_operator",
    ),
    RoutingInterventionCase(
        "design-meeting-discussion-prompts-reach-meeting-brief",
        "Discussion prompts for a meeting reach the meeting brief",
        "draft discussion prompts for Thursday's design meeting",
        "dispatch",
        "meeting-brief",
        "prepare_meeting_brief",
        "meeting_brief",
    ),
    RoutingInterventionCase(
        "sprint-minutes-and-decision-log-reach-operating-rhythm",
        "Keeping sprint minutes and a decision log reaches the operating rhythm",
        "keep our meeting minutes and the decision log from this sprint in one place",
        "dispatch",
        "operating-rhythm",
        "prepare_operating_record",
        "operating_rhythm",
    ),
    RoutingInterventionCase(
        "printer-safety-before-print-reaches-device-readiness",
        "A printer safety check before a print reaches physical device readiness",
        "before I start this print, check 3D printer safety and the camera gate",
        "dispatch",
        "physical-device-readiness",
        "prepare_physical_device_readiness",
        "physical_device_readiness",
    ),
    RoutingInterventionCase(
        "launch-readiness-check-reaches-production-audit",
        "A launch readiness check reaches the production audit",
        "run a launch readiness check before we flip the switch on Friday",
        "dispatch",
        "production-audit",
        "prepare_production_audit",
        "production_audit",
    ),
    RoutingInterventionCase(
        "cli-prompt-folder-import-reaches-prompt-import-readiness",
        "Importing a CLI prompt folder reaches prompt import readiness",
        "I want to import CLI prompts from my OpenCode prompt folder",
        "dispatch",
        "prompt-import-readiness",
        "prepare_prompt_import_readiness",
        "prompt_import_readiness",
    ),
    RoutingInterventionCase(
        "provider-switch-readiness-reaches-provider-profile-posture",
        "Checking a provider profile before a switch reaches provider profile posture",
        "check provider profile readiness before I switch this machine to the new provider",
        "dispatch",
        "provider-profile-posture",
        "prepare_provider_profile_posture",
        "provider_profile_posture",
    ),
    RoutingInterventionCase(
        "board-executive-report-reaches-report-package",
        "An executive report with a presentation outline reaches the report package",
        "prepare an executive report and a presentation outline for the board",
        "dispatch",
        "report-package",
        "prepare_report_package",
        "report_package",
    ),
    RoutingInterventionCase(
        "context-and-tool-duration-reaches-run-efficiency",
        "Context utilization and tool durations reach the run-efficiency report",
        "show context utilization and a tool duration report for yesterday's sessions",
        "dispatch",
        "run-efficiency",
        "show_run_efficiency_report",
        "run_efficiency",
    ),
    RoutingInterventionCase(
        "manage-installed-skills-reaches-skill",
        "Managing the skills installed on a machine reaches skill management",
        "I want to manage skills on this machine and see what is installed",
        "dispatch",
        "skill",
        "run_local_operator_check",
        "doctor_health",
    ),
    RoutingInterventionCase(
        "skill-failure-patterns-reach-skill-health",
        "Asking about skill failure patterns reaches skill health",
        "how is the skill portfolio health looking, any skill failure patterns",
        "dispatch",
        "skill-health",
        "prepare_skill_health",
        "skill_health",
    ),
    RoutingInterventionCase(
        "find-changelog-skill-reaches-skill-scout",
        "Looking for a skill for a task reaches the skill scout",
        "find a skill that can help with changelog writing",
        "dispatch",
        "skill-scout",
        "prepare_skill_scout",
        "skill_scout",
    ),
    RoutingInterventionCase(
        "hostile-scenario-release-qa-reaches-ultraqa",
        "Adversarial QA with hostile scenarios before release reaches ultraqa",
        "run adversarial qa on the checkout flow with hostile scenarios before release",
        "dispatch",
        "ultraqa",
        "dispatch_to_workflow",
        "qa_review",
    ),
    RoutingInterventionCase(
        "hands-free-dictation-reaches-voice-operator",
        "Hands-free dictated requests reach the voice operator",
        "hands-free mode please, I will be giving dictated requests while driving",
        "dispatch",
        "voice-operator",
        "prepare_voice_operator_card",
        "voice_operator",
    ),
    RoutingInterventionCase(
        "large-downloads-listing-reaches-file-operator",
        "Listing large files in a folder reaches the workspace file operator",
        "list files in the downloads folder that are bigger than 1GB",
        "dispatch",
        "workspace-file-operator",
        "prepare_workspace_file_operator_card",
        "workspace_file_operator",
    ),
    RoutingInterventionCase(
        "monthly-badge-progress-reaches-achievements",
        "Asking for badge progress opens the achievements summary",
        "show my badge progress for this month",
        "dispatch",
        "achievements",
        "show_achievements_summary",
        "achievements_summary",
    ),
    RoutingInterventionCase(
        "wiki-from-project-notes-reaches-wiki",
        "Building a wiki out of scattered notes opens the wiki blueprint",
        "help me build a wiki out of my project notes",
        "dispatch",
        "wiki",
        "prepare_wiki_blueprint",
        "wiki_blueprint",
    ),
    # The lane sense of each everyday-sense phrase (`EVERYDAY_SENSE_PHRASES`
    # in `routing/policy.py`) still reaches its skill once one lane word
    # stands beside it. These are the positive half of the controls above.
    RoutingInterventionCase(
        "silent-failures-in-a-service-reach-failure-signal-audit",
        "Silent failures in a named service reach the failure-signal audit",
        "hunt for silent failures in the sync service",
        "dispatch",
        "failure-signal-audit",
        "prepare_failure_signal_audit",
        "failure_signal_audit",
    ),
    RoutingInterventionCase(
        "listing-harness-sessions-reaches-session-inventory",
        "Listing harness sessions reaches the harness session inventory",
        "list my harness sessions",
        "dispatch",
        "harness-session-inventory",
        "prepare_harness_session_inventory",
        "harness_session_inventory",
    ),
    RoutingInterventionCase(
        "team-weekly-status-review-reaches-ops-review",
        "Preparing a team's weekly status review reaches ops review",
        "prepare the weekly status review for the team",
        "dispatch",
        "ops-review",
        "prepare_ops_review",
        "ops_review",
    ),
    RoutingInterventionCase(
        "print-camera-gate-reaches-device-readiness",
        "A camera gate before a print reaches physical device readiness",
        "set up the camera gate before the print starts",
        "dispatch",
        "physical-device-readiness",
        "prepare_physical_device_readiness",
        "physical_device_readiness",
    ),
    RoutingInterventionCase(
        "check-skill-health-reaches-skill-health",
        "Checking skill health reaches the skill health dashboard",
        "check skill health",
        "dispatch",
        "skill-health",
        "prepare_skill_health",
        "skill_health",
    ),
    RoutingInterventionCase(
        "independent-perspectives-on-a-plan-reach-adversarial-consensus",
        "Independent perspectives on a plan reach adversarial consensus",
        "get independent perspectives on this migration plan",
        "dispatch",
        "adversarial-consensus",
        "forward_plan_to_selected_workflow",
        "plan",
    ),
    RoutingInterventionCase(
        "media-input-text-extraction-reaches-media-input-operator",
        "Extracting text from a media input reaches the media input operator",
        "take this media input and extract text",
        "dispatch",
        "media-input-operator",
        "prepare_media_input_card",
        "media_input",
    ),
    RoutingInterventionCase(
        "cancel-the-running-loop-reaches-cancel",
        "Cancelling the running loop reaches cancel",
        "cancel the running loop",
        "dispatch",
        "cancel",
        "cancel",
        "cancellation",
    ),
    RoutingInterventionCase(
        "doctor-my-install-reaches-doctor",
        "A leading doctor aimed at the install reaches doctor",
        "doctor my install",
        "dispatch",
        "doctor",
        "run_local_operator_check",
        "doctor_health",
    ),
    # A bare "run doctor" is shortlist-first on main as well: it names the
    # skill without a lane word, so it asks with doctor leading rather than
    # dispatching. Pinned so the everyday-sense rule cannot drop it further.
    RoutingInterventionCase(
        "run-doctor-clarifies-with-doctor",
        "A bare run doctor asks with doctor leading the shortlist",
        "run doctor",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "doctor",
    ),
    # #1709: application-code faults whose cause is unknown dispatch to the
    # root-cause lane instead of an execution lane that skips the diagnosis.
    # The first three are the issue's measured rows (command-operator, plan,
    # and ultrawork before).
    RoutingInterventionCase(
        "flaky-ci-test-reaches-app-debugging",
        "A test that fails one run in five reaches the root-cause lane",
        "a test fails one run in five in CI, how do I find out why",
        "dispatch",
        "app-debugging",
        "prepare_root_cause_investigation",
        "root_cause_investigation",
    ),
    RoutingInterventionCase(
        "print-statement-heisenbug-reaches-app-debugging",
        "A bug that moves when observed reaches the root-cause lane",
        "the bug disappears when I add a print statement",
        "dispatch",
        "app-debugging",
        "prepare_root_cause_investigation",
        "root_cause_investigation",
    ),
    RoutingInterventionCase(
        "lost-row-update-reaches-app-debugging",
        "Two writers losing an update reaches the root-cause lane",
        "two workers write the same row, one update is lost",
        "dispatch",
        "app-debugging",
        "prepare_root_cause_investigation",
        "root_cause_investigation",
    ),
    RoutingInterventionCase(
        "wrong-return-value-reaches-app-debugging",
        "A wrong return value with an unknown cause reaches the root-cause lane",
        "this function returns the wrong value for negative inputs, help me find the root cause",
        "dispatch",
        "app-debugging",
        "prepare_root_cause_investigation",
        "root_cause_investigation",
    ),
    RoutingInterventionCase(
        "locally-green-ci-red-test-reaches-app-debugging",
        "A test green locally and red in CI reaches the root-cause lane",
        "the integration test is flaky, it passes locally but fails in ci",
        "dispatch",
        "app-debugging",
        "prepare_root_cause_investigation",
        "root_cause_investigation",
    ),
    # #1711: the commit message and the PR body dispatch to the authoring lane
    # instead of `backend`, `content-operator`, or `verification-gate`.
    RoutingInterventionCase(
        "write-the-commit-message-reaches-commit-pr-authoring",
        "Writing the commit message reaches the authoring lane",
        "write the commit message",
        "dispatch",
        "commit-pr-authoring",
        "prepare_commit_pr_text",
        "commit_pr_draft",
    ),
    RoutingInterventionCase(
        "draft-the-pr-body-reaches-commit-pr-authoring",
        "Drafting the PR body reaches the authoring lane",
        "draft the PR body",
        "dispatch",
        "commit-pr-authoring",
        "prepare_commit_pr_text",
        "commit_pr_draft",
    ),
    RoutingInterventionCase(
        "pr-description-with-skipped-suite-reaches-commit-pr-authoring",
        "A PR description with a skipped suite reaches the authoring lane, not the gate",
        "fill in the pull request description for this branch, the unit tests passed but I skipped the e2e suite",
        "dispatch",
        "commit-pr-authoring",
        "prepare_commit_pr_text",
        "commit_pr_draft",
    ),
    RoutingInterventionCase(
        "refactor-commit-message-reaches-commit-pr-authoring",
        "A commit message for a refactor reaches the authoring lane",
        "what should the commit message say for this refactor",
        "dispatch",
        "commit-pr-authoring",
        "prepare_commit_pr_text",
        "commit_pr_draft",
    ),
    RoutingInterventionCase(
        "staged-changes-commit-message-reaches-commit-pr-authoring",
        "A commit message for staged changes reaches the authoring lane",
        "write a commit message for the staged changes",
        "dispatch",
        "commit-pr-authoring",
        "prepare_commit_pr_text",
        "commit_pr_draft",
    ),
    # #1695: conflict resolution, bisect, and history repair dispatch to the git
    # lane. The first three are the issue's rows (memory-sync, github-event-ops,
    # and code-review led the question before).
    RoutingInterventionCase(
        "resolve-merge-conflict-reaches-git-workflow",
        "Resolving a merge conflict reaches the git lane",
        "resolve this merge conflict",
        "dispatch",
        "git-workflow",
        "prepare_git_repair_plan",
        "git_repair_plan",
    ),
    RoutingInterventionCase(
        "bisect-breaking-commit-reaches-git-workflow",
        "Bisecting to the breaking commit reaches the git lane",
        "bisect to find which commit broke it",
        "dispatch",
        "git-workflow",
        "prepare_git_repair_plan",
        "git_repair_plan",
    ),
    RoutingInterventionCase(
        "branch-history-cleanup-reaches-git-workflow",
        "Cleaning up a branch's history reaches the git lane, not review",
        "clean up this branch's history before review",
        "dispatch",
        "git-workflow",
        "prepare_git_repair_plan",
        "git_repair_plan",
    ),
    RoutingInterventionCase(
        "lockfile-rebase-conflict-reaches-git-workflow",
        "A lockfile rebase conflict reaches the git lane",
        "I have a rebase conflict in the lockfile, how do I resolve it",
        "dispatch",
        "git-workflow",
        "prepare_git_repair_plan",
        "git_repair_plan",
    ),
    RoutingInterventionCase(
        "stacked-branch-restack-reaches-git-workflow",
        "Restacking branches after the base merged reaches the git lane",
        "rebase my stacked branches after the base merged",
        "dispatch",
        "git-workflow",
        "prepare_git_repair_plan",
        "git_repair_plan",
    ),
    # #1692: relational database work dispatches to the database lane. The first
    # four are the issue's rows; the missing-index row was a negative control
    # against `workflow-learning` while it had no owner. "ALTER TABLE took a lock
    # during deploy" is a settled report with no ask, so the narration guard
    # answers it directly; the request form is pinned instead.
    RoutingInterventionCase(
        "online-migration-large-table-reaches-relational-db",
        "An online migration on a large table reaches the database lane",
        "write an online migration for a 200M row table",
        "dispatch",
        "relational-db",
        "prepare_db_change_plan",
        "db_change_plan",
    ),
    RoutingInterventionCase(
        "seq-scan-index-question-reaches-relational-db",
        "A seq-scanning query asking for an index reaches the database lane, not workflow-learning",
        "this query seq-scans 40M rows, what index",
        "dispatch",
        "relational-db",
        "prepare_db_change_plan",
        "db_change_plan",
    ),
    RoutingInterventionCase(
        "n-plus-one-endpoint-reaches-relational-db",
        "N+1 queries from an endpoint reach the database lane",
        "N+1 in the orders endpoint",
        "dispatch",
        "relational-db",
        "prepare_db_change_plan",
        "db_change_plan",
    ),
    RoutingInterventionCase(
        "when-to-shard-reaches-relational-db",
        "When to shard reaches the database lane",
        "when do we need to shard",
        "dispatch",
        "relational-db",
        "prepare_db_change_plan",
        "db_change_plan",
    ),
    RoutingInterventionCase(
        "alter-table-lock-request-reaches-relational-db",
        "A lock taken by ALTER TABLE, asked about, reaches the database lane",
        "ALTER TABLE took a lock during deploy, help me make the migration lock-safe",
        "dispatch",
        "relational-db",
        "prepare_db_change_plan",
        "db_change_plan",
    ),
    RoutingInterventionCase(
        "explain-analyze-index-reaches-relational-db",
        "A sequential scan in EXPLAIN ANALYZE reaches the database lane",
        "explain analyze shows a sequential scan on the users table, which index should I add",
        "dispatch",
        "relational-db",
        "prepare_db_change_plan",
        "db_change_plan",
    ),
    # #1694: an event on shipped code dispatches to the security event lane.
    # The first three are the issue's rows. The issue's dependabot row is a
    # version bump with no advisory and belongs to the upgrade lane (#1712);
    # a dependabot security advisory is pinned here instead, even though it
    # arrives as an opened PR that `github-event-ops` would otherwise take.
    RoutingInterventionCase(
        "cve-in-dependency-tree-reaches-security-event-response",
        "A CVE in the dependency tree reaches the security event lane",
        "triage this CVE in our dependency tree",
        "dispatch",
        "security-event-response",
        "prepare_security_event_response",
        "security_event_response",
    ),
    RoutingInterventionCase(
        "committed-secret-reaches-security-event-response",
        "A committed secret reaches the security event lane",
        "we committed a secret, what now",
        "dispatch",
        "security-event-response",
        "prepare_security_event_response",
        "security_event_response",
    ),
    RoutingInterventionCase(
        "dependency-license-reaches-security-event-response",
        "A dependency license question reaches the security event lane",
        "is this dependency's license OK for us",
        "dispatch",
        "security-event-response",
        "prepare_security_event_response",
        "security_event_response",
    ),
    RoutingInterventionCase(
        "dependabot-security-advisory-reaches-security-event-response",
        "A dependabot security advisory PR reaches the security event lane, not the GitHub event card",
        "dependabot opened a security advisory PR for lodash",
        "dispatch",
        "security-event-response",
        "prepare_security_event_response",
        "security_event_response",
    ),
    RoutingInterventionCase(
        "leaked-aws-key-reaches-security-event-response",
        "A cloud key leaked in a public commit reaches the security event lane",
        "we leaked an AWS key in a public commit",
        "dispatch",
        "security-event-response",
        "prepare_security_event_response",
        "security_event_response",
    ),
    RoutingInterventionCase(
        "npm-audit-critical-reaches-security-event-response",
        "A critical from npm audit reaches the security event lane",
        "npm audit flagged a critical in a package we use",
        "dispatch",
        "security-event-response",
        "prepare_security_event_response",
        "security_event_response",
    ),
    # #1713: writing or keeping the repo's agent instruction file dispatches
    # here. The first two are the issue's rows. Distilling lessons into
    # AGENTS.md rule candidates stays with `rules-distill` (pinned elsewhere).
    RoutingInterventionCase(
        "set-up-agents-md-reaches-agent-instructions",
        "Setting up AGENTS.md reaches the instruction file lane",
        "set up AGENTS.md",
        "dispatch",
        "agent-instructions",
        "prepare_instruction_file_update",
        "instruction_file_update",
    ),
    RoutingInterventionCase(
        "update-claude-md-reaches-agent-instructions",
        "Updating CLAUDE.md reaches the instruction file lane",
        "update our CLAUDE.md",
        "dispatch",
        "agent-instructions",
        "prepare_instruction_file_update",
        "instruction_file_update",
    ),
    RoutingInterventionCase(
        "write-agents-md-for-repo-reaches-agent-instructions",
        "Writing an AGENTS.md for a repo reaches the instruction file lane",
        "write an AGENTS.md for this repo",
        "dispatch",
        "agent-instructions",
        "prepare_instruction_file_update",
        "instruction_file_update",
    ),
    RoutingInterventionCase(
        "cursor-rules-for-repo-reaches-agent-instructions",
        "Cursor rules for a repo reach the instruction file lane",
        "create .cursorrules for this repo with our build and test commands",
        "dispatch",
        "agent-instructions",
        "prepare_instruction_file_update",
        "instruction_file_update",
    ),
    # Pins the boost: without it this sentence dispatches to verification-gate.
    RoutingInterventionCase(
        "agents-md-generated-files-reaches-agent-instructions",
        "Updating AGENTS.md about generated files reaches the instruction file lane",
        "update AGENTS.md so the agent stops editing the generated docs",
        "dispatch",
        "agent-instructions",
        "prepare_instruction_file_update",
        "instruction_file_update",
    ),
    # #1693: deciding or undoing a release dispatches to the release lane. The
    # first three are the issue's rows.
    RoutingInterventionCase(
        "cut-and-tag-reaches-release-cut",
        "Cutting and tagging a release reaches the release lane",
        "cut a release and tag it",
        "dispatch",
        "release-cut",
        "prepare_release_plan",
        "release_plan",
    ),
    RoutingInterventionCase(
        "roll-back-last-deploy-reaches-release-cut",
        "Rolling back the last deploy reaches the release lane, not the deploy watch",
        "roll back the last deploy",
        "dispatch",
        "release-cut",
        "prepare_release_plan",
        "release_plan",
    ),
    RoutingInterventionCase(
        "service-canary-reaches-release-cut",
        "Setting up a canary for a service reaches the release lane",
        "set up a canary for this service",
        "dispatch",
        "release-cut",
        "prepare_release_plan",
        "release_plan",
    ),
    RoutingInterventionCase(
        "versioned-cut-reaches-release-cut",
        "Cutting a versioned release reaches the release lane",
        "cut the release for version 2.4 today",
        "dispatch",
        "release-cut",
        "prepare_release_plan",
        "release_plan",
    ),
    RoutingInterventionCase(
        "tag-release-for-build-reaches-release-cut",
        "Tagging a release for a build reaches the release lane",
        "tag a release for the new build",
        "dispatch",
        "release-cut",
        "prepare_release_plan",
        "release_plan",
    ),
    RoutingInterventionCase(
        "terraform-drift-and-staged-apply-reaches-iac-change",
        "A Terraform plan with drift, staged across the cluster, reaches the IaC change plan",
        "terraform plan shows drift in the kubernetes cluster, stage the apply",
        "dispatch",
        "iac-change",
        "prepare_iac_change_plan",
        "iac_change_plan",
        "iac-change",
    ),
    RoutingInterventionCase(
        "terraform-plan-review-reaches-iac-change-not-code-review",
        "Reviewing a Terraform plan before the apply is an IaC change, not a code review",
        "review this terraform plan before we apply it",
        "dispatch",
        "iac-change",
        "prepare_iac_change_plan",
        "iac_change_plan",
        "iac-change",
    ),
    RoutingInterventionCase(
        "helm-chart-values-change-reaches-iac-change",
        "A Helm chart values change asking what could break reaches the IaC change plan",
        "we are changing the helm chart values for the payments service, what could break",
        "dispatch",
        "iac-change",
        "prepare_iac_change_plan",
        "iac_change_plan",
        "iac-change",
    ),
    RoutingInterventionCase(
        "terraform-cost-delta-reaches-iac-change",
        "A cost estimate for a Terraform change reaches the IaC change plan",
        "estimate the cost delta of this terraform change",
        "dispatch",
        "iac-change",
        "prepare_iac_change_plan",
        "iac_change_plan",
        "iac-change",
    ),
    RoutingInterventionCase(
        "pulumi-replacements-reach-iac-change",
        "Pulumi replacements reach the IaC change plan",
        "pulumi preview shows 14 resources replaced",
        "dispatch",
        "iac-change",
        "prepare_iac_change_plan",
        "iac_change_plan",
        "iac-change",
    ),
    RoutingInterventionCase(
        "app-deploy-on-kubernetes-stays-deploy-and-monitor",
        "Shipping an app version to a cluster and watching it stays an application release",
        "deploy the new app version to the kubernetes cluster and watch the health checks",
        "dispatch",
        "deploy-and-monitor",
        "prepare_deploy_monitor_plan",
        "deploy_monitor_plan",
    ),
    RoutingInterventionCase(
        "terraform-path-reaches-iac-change-without-the-word",
        "A change to a .tf file reaches the IaC change plan without the word terraform",
        "review the change to infra/network/main.tf before we apply it",
        "dispatch",
        "iac-change",
        "prepare_iac_change_plan",
        "iac_change_plan",
        "iac-change",
    ),
    RoutingInterventionCase(
        "helm-chart-path-reaches-iac-change",
        "A change to a chart's values file reaches the IaC change plan",
        "apply the change in charts/payments/values.yaml to staging first",
        "dispatch",
        "iac-change",
        "prepare_iac_change_plan",
        "iac_change_plan",
        "iac-change",
    ),
    RoutingInterventionCase(
        "airflow-backfill-duplicates-reach-data-pipelines",
        "An Airflow ETL backfill producing duplicates reaches the pipeline plan, not memory-sync",
        "our airflow etl backfill is producing duplicate events",
        "dispatch",
        "data-pipelines",
        "prepare_pipeline_plan",
        "pipeline_plan",
        "data-pipelines",
    ),
    RoutingInterventionCase(
        "kafka-replay-reaches-data-pipelines",
        "Replaying Kafka events without double counting reaches the pipeline plan",
        "replay the last three days of kafka events into the warehouse without double counting",
        "dispatch",
        "data-pipelines",
        "prepare_pipeline_plan",
        "pipeline_plan",
        "data-pipelines",
    ),
    RoutingInterventionCase(
        "dbt-schema-change-downstream-reaches-data-pipelines",
        "A dbt model's schema change and its downstream readers reach the pipeline plan",
        "the dbt model changed its schema, what breaks downstream",
        "dispatch",
        "data-pipelines",
        "prepare_pipeline_plan",
        "pipeline_plan",
        "data-pipelines",
    ),
    RoutingInterventionCase(
        "idempotent-spark-rerun-reaches-data-pipelines",
        "Making a Spark job's rerun idempotent reaches the pipeline plan",
        "make this spark job idempotent so a rerun does not duplicate rows",
        "dispatch",
        "data-pipelines",
        "prepare_pipeline_plan",
        "pipeline_plan",
        "data-pipelines",
    ),
    RoutingInterventionCase(
        "dbt-model-readers-reach-data-pipelines",
        "Which dashboards read a dbt model is a lineage question for the pipeline plan",
        "which dashboards depend on this dbt model",
        "dispatch",
        "data-pipelines",
        "prepare_pipeline_plan",
        "pipeline_plan",
        "data-pipelines",
    ),
    RoutingInterventionCase(
        "data-backfill-reaches-data-pipelines",
        "A data backfill for a past window reaches the pipeline plan, not a team backfill",
        "we need a data backfill for last month",
        "dispatch",
        "data-pipelines",
        "prepare_pipeline_plan",
        "pipeline_plan",
        "data-pipelines",
    ),
    RoutingInterventionCase(
        "sft-vs-dpo-reaches-model-finetuning",
        "Choosing between SFT and DPO reaches the fine-tuning decision, not workflow-learning",
        "sft vs dpo for our summarization model",
        "dispatch",
        "model-finetuning",
        "prepare_finetune_decision",
        "finetune_plan",
        "model-finetuning",
    ),
    RoutingInterventionCase(
        "finetune-or-prompt-reaches-model-finetuning",
        "Whether to fine-tune at all reaches the fine-tuning decision, where not training is an answer",
        "should we fine-tune a model or is prompting enough",
        "dispatch",
        "model-finetuning",
        "prepare_finetune_decision",
        "finetune_plan",
        "model-finetuning",
    ),
    RoutingInterventionCase(
        "sft-then-dpo-on-tickets-reaches-model-finetuning",
        "Fine-tuning an open model on support tickets with SFT then DPO reaches the fine-tuning decision",
        "fine-tune llama on our support tickets with sft then dpo",
        "dispatch",
        "model-finetuning",
        "prepare_finetune_decision",
        "finetune_plan",
        "model-finetuning",
    ),
    RoutingInterventionCase(
        "untuned-baseline-comparison-reaches-model-finetuning",
        "Comparing a tuned model against the untuned baseline before promotion reaches the promotion gate",
        "compare the tuned model against the untuned baseline before we promote the checkpoint",
        "dispatch",
        "model-finetuning",
        "prepare_finetune_decision",
        "finetune_plan",
        "model-finetuning",
    ),
    RoutingInterventionCase(
        "rlvr-or-dpo-reaches-model-finetuning",
        "Choosing between RLVR and DPO for a checkable task reaches the fine-tuning decision",
        "should we use rlvr or dpo for the math model",
        "dispatch",
        "model-finetuning",
        "prepare_finetune_decision",
        "finetune_plan",
        "model-finetuning",
    ),
    RoutingInterventionCase(
        "lora-adapter-reaches-model-finetuning",
        "Training a LoRA adapter on internal documents reaches the fine-tuning decision",
        "train a lora adapter on our internal docs",
        "dispatch",
        "model-finetuning",
        "prepare_finetune_decision",
        "finetune_plan",
        "model-finetuning",
    ),
    RoutingInterventionCase(
        "run-learning-stays-on-workflow-learning",
        "Learning from an OMH run so the model picks the right workflow stays on workflow-learning, not fine-tuning",
        "learn from this run so the model picks the right workflow next time",
        "dispatch",
        "workflow-learning",
        "copy_learn_prompt",
        "learning_candidate",
    ),
    RoutingInterventionCase(
        "store-launch-reaches-mobile-release",
        "Shipping a version to both stores reaches the store release plan",
        "we are shipping 3.2 to the app store and google play next week",
        "dispatch",
        "mobile-release",
        "prepare_mobile_release_plan",
        "mobile_release_plan",
        "mobile-release",
    ),
    RoutingInterventionCase(
        "testflight-beta-review-reaches-mobile-release",
        "A TestFlight build waiting in beta review reaches the store release plan, not GitHub event ops",
        "our testflight build is stuck in beta review",
        "dispatch",
        "mobile-release",
        "prepare_mobile_release_plan",
        "mobile_release_plan",
        "mobile-release",
    ),
    RoutingInterventionCase(
        "play-staged-rollout-halt-reaches-mobile-release",
        "Halting a Play staged rollout on rising crashes reaches the store release plan, not release-cut",
        "the play store staged rollout is at 20% and crashes went up, halt it and plan the fix",
        "dispatch",
        "mobile-release",
        "prepare_mobile_release_plan",
        "mobile_release_plan",
        "mobile-release",
    ),
    RoutingInterventionCase(
        "ios-signing-reaches-mobile-release",
        "Code signing and provisioning profiles for an iOS release reach the store release plan",
        "set up code signing and provisioning profiles for the ios release",
        "dispatch",
        "mobile-release",
        "prepare_mobile_release_plan",
        "mobile_release_plan",
        "mobile-release",
    ),
    RoutingInterventionCase(
        "privacy-manifest-reaches-mobile-release",
        "The iOS privacy manifest's required-reason APIs reach the store release plan",
        "update the privacy manifest for the required reason apis before we submit",
        "dispatch",
        "mobile-release",
        "prepare_mobile_release_plan",
        "mobile_release_plan",
        "mobile-release",
    ),
    RoutingInterventionCase(
        "android-hotfix-reaches-mobile-release",
        "A hotfix for a crashing Android release reaches the store release plan",
        "push a hotfix for the android release, the login crashes",
        "dispatch",
        "mobile-release",
        "prepare_mobile_release_plan",
        "mobile_release_plan",
        "mobile-release",
    ),
    RoutingInterventionCase(
        "service-staged-rollout-stays-on-release-cut",
        "A staged rollout of an API release stays on release-cut, not the store release plan",
        "set up a staged rollout for the api release",
        "dispatch",
        "release-cut",
        "prepare_release_plan",
        "release_plan",
    ),
    RoutingInterventionCase(
        "ios-backend-deploy-watch-stays-on-deploy-and-monitor",
        "Deploying the API an iOS app calls and watching its health stays on deploy-and-monitor",
        "deploy the api that the ios app calls and keep an eye on release health",
        "dispatch",
        "deploy-and-monitor",
        "prepare_deploy_monitor_plan",
        "deploy_monitor_plan",
    ),
    RoutingInterventionCase(
        "sox-testing-and-grading-reaches-internal-audit",
        "SOX testing of an access review control, graded, reaches the control test plan",
        "we need to do sox testing on the quarterly access review control and grade what we find",
        "dispatch",
        "internal-audit",
        "prepare_control_test_plan",
        "control_test_plan",
        "internal-audit",
    ),
    RoutingInterventionCase(
        "icfr-sample-size-reaches-internal-audit",
        "Sizing a sample for a daily ICFR control reaches the control test plan",
        "how many samples do we need to test a daily control for icfr",
        "dispatch",
        "internal-audit",
        "prepare_control_test_plan",
        "control_test_plan",
        "internal-audit",
    ),
    RoutingInterventionCase(
        "deficiency-severity-reaches-internal-audit",
        "Significant deficiency versus material weakness reaches the criteria-derived grade",
        "is this a significant deficiency or a material weakness",
        "dispatch",
        "internal-audit",
        "prepare_control_test_plan",
        "control_test_plan",
        "internal-audit",
    ),
    RoutingInterventionCase(
        "reconciliation-reperformance-reaches-internal-audit",
        "Re-performing a bank reconciliation control reaches the control test plan",
        "reperform the bank reconciliation control for march",
        "dispatch",
        "internal-audit",
        "prepare_control_test_plan",
        "control_test_plan",
        "internal-audit",
    ),
    RoutingInterventionCase(
        "itgc-evidence-reaches-internal-audit",
        "Auditors asking for evidence an ITGC operated reaches the control test plan",
        "the auditors want evidence the itgc change management control operated all year",
        "dispatch",
        "internal-audit",
        "prepare_control_test_plan",
        "control_test_plan",
        "internal-audit",
    ),
    RoutingInterventionCase(
        "segregation-of-duties-reaches-internal-audit",
        "A clerk who sets up suppliers and approves their payments is a segregation-of-duties deficiency to grade",
        "the same clerk sets up suppliers and approves their payments, is that a segregation of duties deficiency",
        "dispatch",
        "internal-audit",
        "prepare_control_test_plan",
        "control_test_plan",
        "internal-audit",
    ),
    RoutingInterventionCase(
        "budget-variance-stays-on-finance-analysis",
        "Last month's budget variance stays on finance-analysis, not the control test plan",
        "what was our budget variance last month",
        "dispatch",
        "finance-analysis",
        "prepare_finance_analysis",
        "finance_analysis",
    ),
    RoutingInterventionCase(
        "codebase-audit-stays-on-tech-debt-audit",
        "Auditing a codebase for debt stays on tech-debt-audit, not the control test plan",
        "audit my codebase for tech debt",
        "dispatch",
        "tech-debt-audit",
        "prepare_tech_debt_audit",
        "tech_debt_audit",
    ),
    # The other half of the quoted/relayed/linked masks (#2049): an invocation
    # outside the masked line or link still dispatches, so a mask that ate the
    # whole message, or a link's scheme swallowing the words before it, fails
    # here.
    RoutingInterventionCase(
        "invocation-beside-a-url-still-dispatches",
        "A request that carries a link keeps its own invocation",
        "ultrawork this refactor until the tests pass https://github.com/rlaope/oh-my-hermes/pull/1",
        "dispatch", "ultrawork", "present_plan", "plan",
    ),
    RoutingInterventionCase(
        "invocation-after-a-block-quote-still-dispatches",
        "An invocation on the line after a block quote is the person's own request",
        "> the old note said this\n$ulw-work fix the build",
        "dispatch", "ultrawork", "present_plan", "plan",
    ),
    RoutingInterventionCase(
        "invocation-after-a-relay-header-still-dispatches",
        "An invocation on the line after a relayed report is the person's own request",
        "[REPORT] tests are red\n$ulw-work fix the build",
        "dispatch", "ultrawork", "present_plan", "plan",
    ),
    # Review of #2049's masks: each of these dispatched before the masks and
    # must keep dispatching. A possessive or apostrophe touching a link, an
    # arrow or parenthesis between ordinary names, a person's own `[summary]`
    # tag, a pasted `> error` line before a Korean request, a leading link as
    # the request's target, punctuation ending a link before a glued
    # invocation, and a `>` that is not a block-quote marker.
    RoutingInterventionCase(
        "possessive-glued-to-a-url-still-dispatches",
        "An apostrophe glued to a link is a possessive, not a quote that runs to the end",
        "Look at https://github.com/a/b/pull/1's diff and $ulw-work fix it",
        "dispatch", "ultrawork", "present_plan", "plan",
    ),
    RoutingInterventionCase(
        "apostrophe-inside-a-url-path-still-dispatches",
        "An apostrophe inside a link's path opens no quote",
        "Per https://example.com/it's-broken $ulw-work fix the build",
        "dispatch", "ultrawork", "present_plan", "plan",
    ),
    RoutingInterventionCase(
        "version-arrow-prefix-is-not-a-relay-header",
        "An arrow between two versions is the person's own scope, not a relay between agents",
        "v1 -> v2: $ulw-work the migration",
        "dispatch", "ultrawork", "forward_plan_to_selected_workflow", "plan",
    ),
    RoutingInterventionCase(
        "environment-arrow-prefix-is-not-a-relay-header",
        "An arrow between two environments is the person's own scope",
        "staging -> prod: $ulw-work the release",
        "dispatch", "ultrawork", "forward_plan_to_selected_workflow", "plan",
    ),
    RoutingInterventionCase(
        "component-arrow-prefix-is-not-a-relay-header",
        "An arrow between two components keeps the request it prefixes",
        "api->db: ultrawork the schema migration",
        "dispatch", "backend", "prepare_backend_handoff", "backend_contract",
    ),
    RoutingInterventionCase(
        "parenthesized-version-to-target-is-not-a-relay-sender",
        "A version in parentheses before `to <target>:` is not an agent id",
        "Deploy (v2) to staging: $ulw-work the rollout",
        "dispatch", "ultrawork", "forward_plan_to_selected_workflow", "plan",
    ),
    RoutingInterventionCase(
        "parenthesized-service-to-target-is-not-a-relay-sender",
        "A service name in parentheses before `to <target>:` is not an agent id",
        "Move service (auth) to k8s: $ulw-work",
        "dispatch", "ultrawork", "forward_plan_to_selected_workflow", "plan",
    ),
    RoutingInterventionCase(
        "parenthesized-batch-to-target-is-not-a-relay-sender",
        "A batch number in parentheses before `to <target>:` is not an agent id",
        "Migrate users (batch 3) to postgres: $ulw-work",
        "dispatch", "ultrawork", "forward_plan_to_selected_workflow", "plan",
    ),
    RoutingInterventionCase(
        "summary-tag-prefix-is-the-person-s-own-request",
        "A `[summary]` tag is a person's own label, not a relay header",
        "[summary] $ulw-work the release checklist",
        "dispatch", "ultrawork", "forward_plan_to_selected_workflow", "plan",
    ),
    RoutingInterventionCase(
        "result-tag-prefix-is-the-person-s-own-request",
        "A `[result]` tag is a person's own label, not a relay header",
        "[result] $ulw-work fix the failing tests",
        "dispatch", "ultrawork", "present_plan", "plan",
    ),
    RoutingInterventionCase(
        "block-quoted-error-does-not-open-the-korean-transform-path",
        "A pasted `> error` line is context, not text to transform; the invocation below it still dispatches",
        "> TypeError: x is undefined\n이 에러 $ulw-work로 고쳐서 요약해줘",
        "dispatch", "ultrawork", "present_plan", "plan",
    ),
    RoutingInterventionCase(
        "leading-url-then-please-invocation-still-dispatches",
        "A leading link still names the target of the invocation after it",
        "https://example.com/a please $ulw-work fix it",
        "dispatch", "ultrawork", "present_plan", "plan",
    ),
    RoutingInterventionCase(
        "leading-url-then-korean-deictic-invocation-still-dispatches",
        "A leading link is the target a Korean deictic invocation points at",
        "https://example.com/issues/1 이거 $ulw-work로 고쳐줘",
        "dispatch", "ultrawork", "present_plan", "plan",
    ),
    RoutingInterventionCase(
        "leading-url-then-korean-invocation-still-dispatches",
        "A leading link is the target of a Korean invocation with no other noun",
        "https://example.com/issues/1 $ulw-work로 고쳐줘",
        "dispatch", "ultrawork", "present_plan", "plan",
    ),
    RoutingInterventionCase(
        "leading-url-then-korean-workflow-name-still-dispatches",
        "A leading link is the target of a Korean request naming the workflow",
        "https://example.com/issues/1 이거 ultrawork로 고쳐줘",
        "dispatch", "ultrawork", "present_plan", "plan",
    ),
    RoutingInterventionCase(
        "url-ends-at-a-comma-before-an-invocation",
        "A comma ends the link, so the invocation glued after it is the person's own",
        "see https://example.com/x,$ulw-work fix it",
        "dispatch", "ultrawork", "present_plan", "plan",
    ),
    RoutingInterventionCase(
        "url-ends-at-a-closing-parenthesis-before-an-invocation",
        "An unbalanced closing parenthesis ends the link, so the invocation glued after it is the person's own",
        "(https://example.com/a)$ulw-work fix the build",
        "dispatch", "ultrawork", "present_plan", "plan",
    ),
    RoutingInterventionCase(
        "greater-than-number-is-a-comparison-not-a-quote",
        "`> 5` at the start of a chat line reads as a comparison, not a block quote",
        "> 5 tests fail after the merge, $ulw-work fix them",
        "dispatch", "ultrawork", "present_plan", "plan",
    ),
    RoutingInterventionCase(
        "greater-than-glued-to-an-invocation-is-not-a-quote",
        "A `>` with no space after it is not a block-quote marker",
        ">$ulw-work fix the build",
        "dispatch", "ultrawork", "present_plan", "plan",
    ),
    # The route question's decline predicate (#1817), on turns the router is
    # supposed to act on. A clarify naming its only candidate has nothing left
    # for a Choice to decide; a clarify over four candidates does.
    RoutingInterventionCase(
        "route-question-declines-single-candidate-clarify",
        "A clarify with one candidate leaves the route question nothing to decide",
        "please run doctor",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "doctor",
        expected_route_question="single_candidate",
    ),
    # One word is not the same as nothing to decide: a one-word workflow
    # request routes to several candidates and keeps its question. Only a
    # one-word approval (`lgtm` above) is declined.
    RoutingInterventionCase(
        "route-question-keeps-one-word-request",
        "A one-word refactor request still has candidates to choose between",
        "refactor",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        # No candidate pinned: the claim is that the question is kept, not
        # which workflow leads it.
        "",
        expected_route_question=ROUTE_QUESTION_ASKED,
    ),
    RoutingInterventionCase(
        "route-question-keeps-multi-candidate-clarify",
        "A review request over four candidates keeps its route question",
        "review my patch for the export feature",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "code-review",
        expected_route_question=ROUTE_QUESTION_ASKED,
    ),
    # The other side of the native-loop cases in the negative corpus: a timer
    # does not take the goal loop away from OMH's own invocation forms or from
    # a request that carries a product goal, and a plain `./loop` goal still
    # opens it.
    RoutingInterventionCase(
        "omh-loop-goal-invocation-opens-loop",
        "An OMH ./loop goal still opens the goal loop",
        "./loop make OMH a credible Hermes workflow pack with install, docs, QA, and feedback cycles.",
        "dispatch",
        "loop",
        "choose_permission_profile",
        "loop",
    ),
    RoutingInterventionCase(
        "omh-loop-invocation-on-a-timer-keeps-loop",
        "OMH's own ./loop form keeps the goal loop even with a timer",
        "./loop every 5 minutes check whether CI is green",
        "dispatch",
        "loop",
        "start_loop_cycle",
        "loop",
    ),
    RoutingInterventionCase(
        "product-goal-loop-on-a-timer-keeps-loop",
        "A timed loop that carries a product goal stays the goal loop",
        "run a loop every 30 minutes to improve first-run experience until install friction is lower",
        "dispatch",
        "loop",
        "choose_permission_profile",
        "loop",
    ),
    # A timer does not take the goal loop away from a request that names it --
    # by a goal-loop phrase or by the skill's own name -- however the timer is
    # written.
    RoutingInterventionCase(
        "goal-loop-on-a-timer-keeps-loop",
        "A named goal loop on a timer stays the goal loop",
        "start a goal loop that iterates every 2 hours until the onboarding drop-off is under 20%",
        "dispatch",
        "loop",
        "choose_permission_profile",
        "loop",
    ),
    RoutingInterventionCase(
        "korean-keep-improving-loop-on-a-timer-keeps-loop",
        "A Korean keep-improving loop on a timer stays the goal loop",
        "1시간마다 온보딩을 계속 개선하는 루프 돌려줘, 첫 실행 성공률 90% 될 때까지",
        "dispatch",
        "loop",
        "choose_permission_profile",
        "loop",
    ),
    RoutingInterventionCase(
        "ulw-loop-skill-on-a-timer-keeps-loop",
        "The ulw-loop skill named on a timer stays the goal loop",
        "use the ulw-loop skill every 2 hours to check whether CI is green",
        "dispatch",
        "loop",
        "ask_goal_boundary",
        "loop",
    ),
    RoutingInterventionCase(
        "run-ulw-loop-on-a-timer-keeps-loop",
        "Running ulw-loop on a timer stays the goal loop",
        "run ulw-loop every hour on the onboarding docs",
        "dispatch",
        "loop",
        "prepare_scheduled_ops_blueprint",
        "loop",
    ),
    # The sentence that invokes the skill keeps it on a timer, and so do OMH's
    # own forms behind a shared session's sender prefix.
    RoutingInterventionCase(
        "invoked-ulw-loop-skill-on-a-timer-keeps-loop",
        "Invoking the ulw-loop skill on a timer stays the goal loop",
        "use the ulw-loop skill every 2 hours to improve the README",
        "dispatch",
        "loop",
        "choose_permission_profile",
        "loop",
    ),
    RoutingInterventionCase(
        "invoked-loop-skill-on-a-timer-keeps-loop",
        "Invoking the loop skill by its catalog name on a timer stays the goal loop",
        "use the loop skill every 2 hours to improve the README",
        "dispatch",
        "loop",
        "choose_permission_profile",
        "loop",
    ),
    RoutingInterventionCase(
        "korean-invoked-ulw-loop-skill-on-a-timer-keeps-loop",
        "Invoking ulw-loop in Korean on a timer stays the goal loop",
        "ulw-loop 스킬로 1시간마다 README 개선해줘",
        "dispatch",
        "loop",
        "choose_permission_profile",
        "loop",
    ),
    # Behind a sender prefix (and below, a reply pointer as well) the loop card
    # now reads what the bare request reads and starts the cycle. It used to
    # read the prefix as the request's first word, so the invocation that
    # opens the message went unseen and the card asked something else.
    RoutingInterventionCase(
        "dollar-loop-behind-a-sender-prefix-keeps-loop",
        "OMH's $loop form behind a shared session's sender prefix stays the goal loop",
        "[alice] $loop every hour check CI",
        "dispatch",
        "loop",
        "start_loop_cycle",
        "loop",
    ),
    # One verdict now decides every timed loop for the router and the hint.
    # These three sat on its edges: an OMH form behind a reply pointer and a
    # sender prefix, whose block end the scorer's collapsed text no longer
    # shows; a loop asked to make something better; and another skill whose
    # name merely ends in "loop".
    RoutingInterventionCase(
        "omh-loop-behind-a-reply-pointer-and-sender-keeps-loop",
        "OMH's loop form behind a reply pointer and a sender prefix stays the goal loop",
        "[Replying to: \"is CI green?\"]\n\n[alice] omh loop every 30 minutes check CI",
        "dispatch",
        "loop",
        "start_loop_cycle",
        "loop",
    ),
    RoutingInterventionCase(
        "improving-loop-on-a-timer-keeps-loop",
        "A timed loop asked to improve something stays the goal loop",
        "loop every hour and improve the docs",
        "dispatch",
        "loop",
        "prepare_scheduled_ops_blueprint",
        "loop",
    ),
    RoutingInterventionCase(
        "cto-loop-on-a-timer-keeps-cto-loop",
        "Another skill whose name ends in loop keeps its own route on a timer",
        "run omh-cto-loop every 30 minutes on the roadmap",
        "dispatch",
        "cto-loop",
        "run_cto_loop",
        "cto_loop",
    ),
    # Only a request that opens with a loop command and its cadence is Hermes'
    # `/loop`; a skill the person invokes beside one still gets the turn, and a
    # loop word anywhere else routes as it did before. The spaced `cto loop`
    # is that skill's trigger, never the loop command.
    RoutingInterventionCase(
        "another-skill-invoked-beside-a-timed-loop-keeps-it",
        "A skill invoked by name beside a timed loop keeps the turn",
        "loop every 5 minutes and run the code-review skill on new PRs",
        "dispatch",
        "code-review",
        "choose_executor",
        "handoff",
    ),
    RoutingInterventionCase(
        "invoked-plan-over-a-timed-polling-loop-keeps-plan",
        "An invoked plan about a polling loop on a timer keeps the plan",
        "ulw-plan: replace the polling loop that hits the API every 5 minutes with webhooks",
        "dispatch",
        "ralplan",
        "forward_plan_to_selected_workflow",
        "plan",
    ),
    RoutingInterventionCase(
        "spaced-cto-loop-on-a-timer-keeps-cto-loop",
        "The spaced cto loop trigger on a timer keeps cto-loop",
        "cto loop every hour check the roadmap",
        "dispatch",
        "cto-loop",
        "run_cto_loop",
        "cto_loop",
    ),
    # A timed loop asked to move a product or star measure stays the goal loop,
    # as it was before.
    RoutingInterventionCase(
        "outcome-goal-loop-on-a-timer-keeps-loop",
        "A timed loop asked to lower install friction stays the goal loop",
        "loop every 30 minutes to lower install friction",
        "dispatch",
        "loop",
        "start_loop_cycle",
        "loop",
    ),
    # The skill's own name in the loop command's place, after a cadence, opens
    # the goal loop. Before, the name folded to the bare word and lost to the
    # rest of the sentence: app-debugging took the flaky list and
    # build-failure-triage the build failures. The person named the skill.
    RoutingInterventionCase(
        "named-ulw-loop-after-a-cadence-opens-loop",
        "ulw-loop named after a cadence opens the goal loop",
        "every 2 hours ulw-loop the flaky test list",
        "dispatch",
        "loop",
        "ask_goal_boundary",
        "loop",
    ),
    RoutingInterventionCase(
        "named-ulw-loop-on-build-failures-after-a-cadence-opens-loop",
        "ulw-loop named after a cadence on build failures opens the goal loop",
        "every hour ulw-loop the build failures on main",
        "dispatch",
        "loop",
        "prepare_scheduled_ops_blueprint",
        "loop",
    ),
    # The other side of the bundled-skill boundary above: each OMH skill still
    # takes its own request when the bundled skill's words are absent or a
    # target of its own is named.
    RoutingInterventionCase(
        "dashboard-card-for-review-still-dispatches-img-summary",
        "A dashboard card is an image card; `board card` inside `dashboard` is not a work-board card",
        "Design a dashboard card that summarizes Q3 revenue for the review",
        "dispatch",
        "img-summary",
        "prepare_visual_prompt_card",
        "img_summary",
    ),
    RoutingInterventionCase(
        "scoreboard-card-for-review-still-dispatches-img-summary",
        "A scoreboard card is an image card; `board card` inside `scoreboard` is not a work-board card",
        "Make a scoreboard card for the review of the tournament",
        "dispatch",
        "img-summary",
        "prepare_visual_prompt_card",
        "img_summary",
    ),
    RoutingInterventionCase(
        "aws-cdk-architecture-diagram-still-dispatches-codebase-uml",
        "Infrastructure defined in CDK code is still code to draw a codebase picture from",
        "Draw an architecture diagram of our AWS CDK app",
        "dispatch",
        "codebase-uml",
        "prepare_codebase_uml",
        "codebase_uml",
    ),
    RoutingInterventionCase(
        "cloud-app-services-folder-diagram-still-dispatches-codebase-uml",
        "A cloud app drawn from a folder of its code is a codebase picture",
        "Draw an architecture diagram of our cloud app from its services folder",
        "dispatch",
        "codebase-uml",
        "prepare_codebase_uml",
        "codebase_uml",
    ),
    RoutingInterventionCase(
        "cloud-services-directory-diagram-still-dispatches-codebase-uml",
        "A cloud diagram of a directory of code is a codebase picture",
        "make a cloud architecture diagram of the services directory",
        "dispatch",
        "codebase-uml",
        "prepare_codebase_uml",
        "codebase_uml",
    ),
    RoutingInterventionCase(
        "aws-infrastructure-from-src-diagram-still-dispatches-codebase-uml",
        "Infrastructure drawn from the src tree is a codebase picture; `src` is the only code word here",
        "Draw an architecture diagram of our AWS infrastructure from the src tree",
        "dispatch",
        "codebase-uml",
        "prepare_codebase_uml",
        "codebase_uml",
    ),
    RoutingInterventionCase(
        "research-department-digest-into-llm-wiki-still-dispatches-research-department",
        "A research department named outright keeps its request when the digest lands in an LLM wiki",
        "Research department weekly digest into our llm wiki",
        "dispatch",
        "research-department",
        "prepare_research_department_plan",
        "research_department",
    ),
    RoutingInterventionCase(
        "team-paper-research-pipeline-still-dispatches-research-department",
        "A team's recurring paper research pipeline is still a research department",
        "Run our team's paper research pipeline this week",
        "dispatch",
        "research-department",
        "prepare_research_department_plan",
        "research_department",
    ),
    RoutingInterventionCase(
        "image-card-from-kanban-notes-still-dispatches-img-summary",
        "An image card named outright still reaches img-summary beside a kanban card",
        "make an image card from the kanban card notes",
        "dispatch",
        "img-summary",
        "prepare_visual_prompt_card",
        "img_summary",
    ),
    RoutingInterventionCase(
        "class-diagram-of-cloud-sdk-module-still-dispatches-codebase-uml",
        "An infrastructure word beside a code target is still a codebase diagram",
        "draw a class diagram of the aws sdk wrapper module",
        "dispatch",
        "codebase-uml",
        "prepare_codebase_uml",
        "codebase_uml",
    ),
    RoutingInterventionCase(
        "codebase-architecture-diagram-still-dispatches-codebase-uml",
        "An architecture diagram of the codebase is still codebase-uml's",
        "draw an architecture diagram of the codebase",
        "dispatch",
        "codebase-uml",
        "prepare_codebase_uml",
        "codebase_uml",
    ),
    RoutingInterventionCase(
        "team-wiki-in-notion-still-dispatches-wiki",
        "A team wiki blueprint that names no LLM wiki still reaches wiki",
        "build a wiki for our team in notion",
        "dispatch",
        "wiki",
        "prepare_wiki_blueprint",
        "wiki_blueprint",
    ),
    # Korean diagram requests reach the diagram workflow once its Korean words
    # are compared in the router's folded form, the attached particle included,
    # and a Korean code word keeps a diagram that also names the cloud. A
    # Korean wiki that names no LLM wiki still reaches wiki.
    RoutingInterventionCase(
        "korean-codebase-diagram-reaches-codebase-uml",
        "A Korean codebase diagram request opens the diagram workflow",
        "코드베이스 다이어그램 그려줘",
        "dispatch",
        "codebase-uml",
        "prepare_codebase_uml",
        "codebase_uml",
    ),
    RoutingInterventionCase(
        "korean-codebase-visualize-reaches-codebase-uml",
        "Asking in Korean to visualize the codebase opens the diagram workflow",
        "코드베이스 시각화해줘",
        "dispatch",
        "codebase-uml",
        "prepare_codebase_uml",
        "codebase_uml",
    ),
    RoutingInterventionCase(
        "korean-class-diagram-with-particle-reaches-codebase-uml",
        "A Korean class diagram with a particle attached still opens the diagram workflow",
        "이 코드의 클래스 다이어그램이 필요해",
        "dispatch",
        "codebase-uml",
        "prepare_codebase_uml",
        "codebase_uml",
    ),
    RoutingInterventionCase(
        "korean-class-diagram-of-cloud-sdk-module-reaches-codebase-uml",
        "A Korean code word beside a Korean cloud word is still a codebase diagram",
        "클라우드 SDK 모듈 클래스 다이어그램 그려줘",
        "dispatch",
        "codebase-uml",
        "prepare_codebase_uml",
        "codebase_uml",
    ),
    RoutingInterventionCase(
        "korean-codebase-diagram-beside-cloud-word-with-particle-reaches-codebase-uml",
        "A Korean code word read as a prefix keeps a diagram beside a cloud word with a particle",
        "클라우드의 코드베이스 다이어그램 그려줘",
        "dispatch",
        "codebase-uml",
        "prepare_codebase_uml",
        "codebase_uml",
    ),
    RoutingInterventionCase(
        "korean-team-wiki-still-dispatches-wiki",
        "A Korean team wiki that names no LLM wiki still reaches wiki",
        "팀 위키 만들어줘",
        "dispatch",
        "wiki",
        "prepare_wiki_blueprint",
        "wiki_blueprint",
    ),
    # `data-share-review`, added with the skill. It takes nothing another
    # skill holds: no boost, no guard stands down for it. It dispatches only
    # where ordinary scoring puts it first on a sentence that leads with
    # redact, pseudonymize, anonymize or de-identify on a file leaving the team;
    # a file headed for a GitHub issue, a transcript tool or a contractor stays
    # with the guard that holds it.
    RoutingInterventionCase(
        "fine-tune-corpus-pseudonymization-asks-between-two-owners",
        "Pseudonymizing ids before a fine-tune corpus asks, naming the data share review first, instead of dispatching model-finetuning",
        "pseudonymize the customer ids in this dataset before it goes into the fine-tune corpus",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "data-share-review",
    ),
    RoutingInterventionCase(
        "logs-for-a-public-github-issue-stay-on-github-event-ops",
        "Redacting server logs before a public GitHub issue stays with GitHub event ops, which holds the issue",
        "redact personal data from these server logs before I attach them to a public github issue",
        "dispatch",
        "github-event-ops",
        "prepare_github_event_ops_card",
        "github_event_ops",
    ),
    RoutingInterventionCase(
        "transcript-excerpt-for-a-public-tracker-stays-on-media-input-operator",
        "Redacting a transcript excerpt before a public tracker stays with the media operator, which holds the transcript",
        "redact the pii in this support transcript excerpt before we post it in the public tracker",
        "dispatch",
        "media-input-operator",
        "prepare_media_input_card",
        "media_input",
    ),
    RoutingInterventionCase(
        "dataset-for-a-contractor-stays-on-connector-operator",
        "Stripping PII before a contractor gets the dataset stays with the connector operator, which holds the send",
        "strip the pii from this dataset before we send it to an external contractor",
        "dispatch",
        "connector-operator",
        "prepare_connector_operator_card",
        "connector_operator",
    ),
    RoutingInterventionCase(
        "patient-csv-for-a-model-provider-reaches-data-share-review",
        "De-identifying patient records before a model provider sees them reaches the data share review",
        "de-identify this csv of patient records before the model provider sees it",
        "dispatch",
        "data-share-review",
        "prepare_data_share_review",
        "data_share_review",
    ),
    RoutingInterventionCase(
        "export-for-a-researcher-reaches-data-share-review",
        "De-identifying an export for a researcher reaches the data share review",
        "de-identify this export for the researcher",
        "dispatch",
        "data-share-review",
        "prepare_data_share_review",
        "data_share_review",
    ),
    RoutingInterventionCase(
        "crash-log-for-a-github-issue-stays-on-github-event-ops",
        "Attaching a crash log to a GitHub issue with nothing to strip stays on GitHub event ops",
        "attach the crash log to the github issue",
        "dispatch",
        "github-event-ops",
        "prepare_github_event_ops_card",
        "github_event_ops",
    ),
    RoutingInterventionCase(
        "support-transcript-summary-stays-on-media-input-operator",
        "Summarizing a support transcript with nothing to strip stays on the media operator",
        "summarize this customer support transcript",
        "dispatch",
        "media-input-operator",
        "prepare_media_input_card",
        "media_input",
    ),
    RoutingInterventionCase(
        "fine-tuning-on-tickets-stays-on-model-finetuning",
        "Fine-tuning on support tickets with nothing to strip stays on model-finetuning",
        "fine-tune a model on our support tickets",
        "dispatch",
        "model-finetuning",
        "prepare_finetune_decision",
        "finetune_plan",
    ),
    # Review round one: these dispatched the skill while a phrase counted
    # anywhere; the issue, the pull request, the workflow and the post are
    # the objects, so their owners keep them.
    RoutingInterventionCase(
        "label-the-github-issue-about-pii-redaction-as-high-priority-stays-off-data-share-review",
        "Labeling an issue about redaction stays on GitHub event ops",
        "label the github issue about pii redaction as high priority",
        "dispatch",
        "github-event-ops",
        "prepare_github_event_ops_card",
        "github_event_ops",
    ),
    RoutingInterventionCase(
        "close-the-github-issue-titled-redact-pii-from-logs-stays-off-data-share-review",
        "Closing an issue titled with a redaction phrase stays on GitHub event ops",
        "close the github issue titled redact pii from logs",
        "dispatch",
        "github-event-ops",
        "prepare_github_event_ops_card",
        "github_event_ops",
    ),
    RoutingInterventionCase(
        "review-the-github-pull-request-that-adds-pii-redaction-stays-off-data-share-review",
        "Reviewing a redaction pull request stays on GitHub event ops",
        "review the github pull request that adds pii redaction",
        "dispatch",
        "github-event-ops",
        "prepare_github_event_ops_card",
        "github_event_ops",
    ),
    RoutingInterventionCase(
        "triage-github-issues-labeled-pii-redaction-stays-off-data-share-review",
        "Triaging redaction-labeled issues stays on GitHub event ops",
        "triage github issues labeled pii redaction",
        "dispatch",
        "github-event-ops",
        "prepare_github_event_ops_card",
        "github_event_ops",
    ),
    RoutingInterventionCase(
        "set-up-a-github-actions-workflow-that-runs-pii-redaction-on-every-push-stays-off-data-share-review",
        "A redaction workflow on every push stays on GitHub event ops",
        "set up a github actions workflow that runs pii redaction on every push",
        "dispatch",
        "github-event-ops",
        "prepare_github_event_ops_card",
        "github_event_ops",
    ),
    RoutingInterventionCase(
        "rerun-the-failing-github-action-for-the-pseudonymize-job-stays-off-data-share-review",
        "Rerunning a pseudonymize job's action stays on GitHub event ops",
        "rerun the failing github action for the pseudonymize job",
        "dispatch",
        "github-event-ops",
        "prepare_github_event_ops_card",
        "github_event_ops",
    ),
    RoutingInterventionCase(
        "write-a-blog-post-about-pii-redaction-best-practices-stays-off-data-share-review",
        "A blog post about redaction stays on web research",
        "write a blog post about pii redaction best practices",
        "dispatch",
        "web-research",
        "run_hermes_research",
        "web_research",
    ),
    # Review round three: the crash log stays with the guard that holds the
    # issue (round two pinned it to dispatch data-share-review).
    RoutingInterventionCase(
        "crash-log-for-a-public-github-issue-stays-on-github-event-ops",
        "Redacting a crash log before a public GitHub issue stays with GitHub event ops, which holds the issue",
        "redact the pii in this crash log before attaching it to the public github issue",
        "dispatch",
        "github-event-ops",
        "prepare_github_event_ops_card",
        "github_event_ops",
    ),
    # Review round two: a request that only mentions redaction keeps its owner.
    RoutingInterventionCase(
        "hey-triage-the-github-issues-about-pii-redaction-in-the-public-log-fil-stays-off-data-share-review",
        "Triaging issues about redaction in public logs stays on GitHub event ops",
        "hey, triage the github issues about pii redaction in the public log files",
        "dispatch",
        "github-event-ops",
        "prepare_github_event_ops_card",
        "github_event_ops",
    ),
    RoutingInterventionCase(
        "i-need-you-to-triage-the-issues-about-pii-redaction-in-log-files-we-po-stays-off-data-share-review",
        "Triaging issues about redaction in published logs stays on the connector operator",
        "i need you to triage the issues about pii redaction in log files we post publicly",
        "dispatch",
        "connector-operator",
        "prepare_connector_operator_card",
        "connector_operator",
    ),
    RoutingInterventionCase(
        "send-a-slack-message-saying-the-export-file-is-ready-to-share-once-we-stays-off-data-share-review",
        "A Slack message about a redacted export stays on the gateway intent card",
        "send a slack message saying the export file is ready to share once we redact pii",
        "dispatch",
        "gateway-intent-card",
        "prepare_gateway_intent_card",
        "gateway_intent",
    ),
    # Review round three: requests other skills hold keep their owners.
    RoutingInterventionCase(
        "remove-the-pii-redaction-label-from-the-github-issue-about-the-export-stays-off-data-share-review",
        "Round three: a request another skill holds stays with github-event-ops",
        "remove the pii redaction label from the github issue about the export we sent the vendor",
        "dispatch",
        "github-event-ops",
        "prepare_github_event_ops_card",
        "github_event_ops",
    ),
    RoutingInterventionCase(
        "summarize-this-transcript-then-redact-the-pii-from-the-excerpt-before-stays-off-data-share-review",
        "Round three: a request another skill holds stays with media-input-operator",
        "summarize this transcript, then redact the pii from the excerpt before we post it publicly",
        "dispatch",
        "media-input-operator",
        "prepare_media_input_card",
        "media_input",
    ),
    RoutingInterventionCase(
        "transcribe-this-call-then-redact-the-pii-in-the-transcript-excerpt-bef-stays-off-data-share-review",
        "Round three: a request another skill holds stays with media-input-operator",
        "transcribe this call, then redact the pii in the transcript excerpt before posting it publicly",
        "dispatch",
        "media-input-operator",
        "prepare_media_input_card",
        "media_input",
    ),
    RoutingInterventionCase(
        "korean-led-slack-message-about-removing-pii-stays-on-research-brief",
        "Round three: a request another skill holds stays with research-brief",
        "슬랙에 메시지 보내줘: remove pii from the export before we send it to the vendor",
        "dispatch",
        "research-brief",
        "run_hermes_research",
        "web_research",
    ),
    RoutingInterventionCase(
        "korean-led-github-label-request-stays-on-github-event-ops",
        "Round three: a request another skill holds stays with github-event-ops",
        "깃허브 이슈 라벨 달아줘, 제목: redact the pii from the export before sending to the vendor",
        "dispatch",
        "github-event-ops",
        "prepare_github_event_ops_card",
        "github_event_ops",
    ),
    RoutingInterventionCase(
        "mixed-korean-send-request-stays-on-gateway-intent-card",
        "Round three: a request another skill holds stays with gateway-intent-card",
        "redact pii 하고 vendor한테 export 파일 보내줘",
        "dispatch",
        "gateway-intent-card",
        "prepare_gateway_intent_card",
        "gateway_intent",
    ),
    RoutingInterventionCase(
        "http-402-payment-reaches-spend-gate",
        "An HTTP 402 the agent is told to pay reaches the pre-spend card",
        "go ahead and pay the 402 challenge for the dataset",
        "dispatch",
        "spend-gate",
        "prepare_pre_spend_card",
        "pre_spend_card",
        "spend-gate",
    ),
    RoutingInterventionCase(
        "booking-paid-with-card-reaches-spend-gate",
        "A booking paid with the person's card reaches the pre-spend card",
        "please pay for the hotel booking with my card",
        "dispatch",
        "spend-gate",
        "prepare_pre_spend_card",
        "pre_spend_card",
        "spend-gate",
    ),
    RoutingInterventionCase(
        "card-purchase-under-a-cap-leads-with-spend-gate",
        "A purchase on the person's card under a stated cap asks with the pre-spend card leading",
        "buy the trip supplies for me with my card, up to $200",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "spend-gate",
    ),
    RoutingInterventionCase(
        "timed-out-payment-leads-with-spend-gate",
        "A payment the agent made whose outcome nobody saw asks with the reconcile rule leading",
        "hermes, did the payment go through after you clicked pay? it timed out",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "spend-gate",
    ),
    RoutingInterventionCase(
        "wallet-transfer-reaches-spend-gate",
        "A transfer out of the person's wallet reaches the pre-spend card",
        "transfer 40 dollars from my wallet to my landlord",
        "dispatch",
        "spend-gate",
        "prepare_pre_spend_card",
        "pre_spend_card",
        "spend-gate",
    ),
    RoutingInterventionCase(
        "pay-on-my-behalf-reaches-spend-gate",
        "A payment made on the person's behalf, with the total asked for first, reaches the pre-spend card",
        "please pay on my behalf for the hotel, but show me the total and fees first",
        "dispatch",
        "spend-gate",
        "prepare_pre_spend_card",
        "pre_spend_card",
        "spend-gate",
    ),
    RoutingInterventionCase(
        "buy-it-for-me-leads-with-spend-gate",
        "A purchase the agent is asked to make under a stated total asks with the pre-spend card leading",
        "go ahead and buy it for me if the total stays under 50 dollars",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "spend-gate",
    ),
    RoutingInterventionCase(
        "checkout-url-browser-task-stays-on-browser-operator",
        "A checkout URL opened to log in and fill a form stays on browser-operator, not the pre-spend card",
        "open the staging checkout url, click login and fill the form",
        "dispatch",
        "browser-operator",
        "prepare_browser_operator_card",
        "browser_operator",
    ),
    RoutingInterventionCase(
        "payment-failure-reports-stay-on-feedback-triage",
        "Users' payment failure reports stay on feedback-triage, not the pre-spend card",
        "triage the payment failure reports from support this week",
        "dispatch",
        "feedback-triage",
        "triage_feedback",
        "feedback_triage",
    ),
    RoutingInterventionCase(
        "card-renewal-leads-with-spend-gate",
        "A subscription renewed with the person's card asks with the pre-spend card leading",
        "please renew my netflix subscription with my card",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "spend-gate",
    ),
    RoutingInterventionCase(
        "credit-card-tickets-lead-with-spend-gate",
        "Tickets bought with the person's credit card ask with the pre-spend card leading",
        "can you use my credit card to buy the concert tickets",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "spend-gate",
    ),
    RoutingInterventionCase(
        "credits-top-up-with-amount-leads-with-spend-gate",
        "A top-up with a stated amount on the person's card asks with the pre-spend card leading",
        "top up my openai credits by $50 with my card",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "spend-gate",
    ),
    RoutingInterventionCase(
        "money-to-a-friend-leads-with-spend-gate",
        "Money sent to a friend asks with the pre-spend card leading",
        "please send money to my friend on venmo",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "spend-gate",
    ),
    RoutingInterventionCase(
        "buy-under-a-limit-with-a-pricing-check-leads-with-spend-gate",
        "A purchase under a stated limit, with a pricing check after it, asks with the pre-spend card leading",
        "please buy it for me if it is under $20, check the pricing first",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "spend-gate",
    ),
    RoutingInterventionCase(
        "spend-approval-best-practices-stay-on-web-research",
        "A best-practices question about spend approval workflows stays on web-research, not the pre-spend card",
        "what are the best practices for spend approval workflows in a company",
        "dispatch",
        "web-research",
        "run_hermes_research",
        "web_research",
    ),
    RoutingInterventionCase(
        "checkout-cypress-spec-stays-on-feedback-triage",
        "A failing Cypress spec for a checkout keeps its owner, not the pre-spend card",
        "cypress spec for complete the checkout keeps failing",
        "dispatch",
        "feedback-triage",
        "triage_feedback",
        "feedback_triage",
    ),
    RoutingInterventionCase(
        "purchase-acceptance-criteria-stay-on-ralplan",
        "Acceptance criteria for a purchase step stay on ralplan, not the pre-spend card",
        "write acceptance criteria for complete the purchase",
        "dispatch",
        "ralplan",
        "forward_plan_to_selected_workflow",
        "plan",
    ),
    RoutingInterventionCase(
        "saved-card-settings-toggle-stays-on-ultrawork",
        "A settings toggle for paying with a saved card is code work on ultrawork, not the pre-spend card",
        "add a pay with my saved card toggle to settings",
        "dispatch",
        "ultrawork",
        "choose_executor",
        "handoff",
    ),
    RoutingInterventionCase(
        "checkout-issue-triage-for-card-payments-stays-on-feedback-triage",
        "Triaging issues about card payments in a checkout keeps its owner; the spend phrase is only the topic",
        "triage the issues about the checkout flow for my card payments",
        "dispatch",
        "feedback-triage",
        "triage_feedback",
        "feedback_triage",
    ),
    RoutingInterventionCase(
        "saved-card-checkout-failure-stays-on-feedback-triage",
        "A checkout failure report keeps its owner; the noun checkout is not a spend",
        "Checkout with my saved card fails on staging",
        "dispatch",
        "feedback-triage",
        "triage_feedback",
        "feedback_triage",
    ),
    RoutingInterventionCase(
        "empty-cart-card-checkout-break-stays-on-feedback-triage",
        "A checkout failure report keeps its owner; the noun checkout is not a spend",
        "Checkout with my card breaks when the cart has 0 items",
        "dispatch",
        "feedback-triage",
        "triage_feedback",
        "feedback_triage",
    ),
    RoutingInterventionCase(
        "card-3ds-failure-report-stays-on-feedback-triage",
        "A 3DS failure report keeps its owner; the phrase has no request marker",
        "Use my credit card at checkout fails with a 3DS error",
        "dispatch",
        "feedback-triage",
        "triage_feedback",
        "feedback_triage",
    ),
    RoutingInterventionCase(
        "buy-it-for-me-crash-report-stays-on-feedback-triage",
        "A crash report keeps its owner; the phrase has no request marker",
        "Buy it for me in the mobile app crashes on launch",
        "dispatch",
        "feedback-triage",
        "triage_feedback",
        "feedback_triage",
    ),
    RoutingInterventionCase(
        "pay-on-my-behalf-feature-request-stays-on-plan",
        "A feature request keeps its base dispatch to plan; the phrase has no request marker",
        "Pay on my behalf to the landlord is a feature request from Q3",
        "dispatch",
        "plan",
        "forward_plan_to_selected_workflow",
        "plan",
    ),
    RoutingInterventionCase(
        "marketing-spend-budget-vs-actual-stays-on-finance-analysis",
        "Budget vs actual for marketing spend stays on finance-analysis, not the pre-spend card",
        "budget vs actual for q3 marketing spend",
        "dispatch",
        "finance-analysis",
        "prepare_finance_analysis",
        "finance_analysis",
    ),
    # A loop on a timer whose prompt spends the person's money: no scheduled
    # run may spend, so the card, the typed yes and the cap come now. Before,
    # both were answered with Hermes' /loop.
    RoutingInterventionCase(
        "loop-that-buys-with-my-card-reaches-spend-gate",
        "A loop on a timer that buys with the person's card reaches the pre-spend card",
        "loop every hour and buy the concert tickets for me with my card if they drop under $50",
        "dispatch",
        "spend-gate",
        "prepare_pre_spend_card",
        "pre_spend_card",
    ),
    RoutingInterventionCase(
        "typed-loop-that-buys-with-my-card-reaches-spend-gate",
        "A typed /loop whose prompt buys with the person's card reaches the pre-spend card",
        "/loop 1h buy the concert tickets with my card if they drop under $50",
        "dispatch",
        "spend-gate",
        "prepare_pre_spend_card",
        "pre_spend_card",
    ),
    # Every verb a spend request opens with anchors the wallet phrase; before,
    # renewing or topping up from the person's wallet left the gate out.
    RoutingInterventionCase(
        "domain-renewal-from-my-wallet-reaches-spend-gate",
        "A renewal paid from the person's wallet reaches the pre-spend card",
        "please renew the domain from my wallet",
        "dispatch",
        "spend-gate",
        "prepare_pre_spend_card",
        "pre_spend_card",
    ),
    RoutingInterventionCase(
        "account-top-up-from-my-wallet-reaches-spend-gate",
        "A top-up paid from the person's wallet reaches the pre-spend card",
        "could you top up my account from my wallet",
        "dispatch",
        "spend-gate",
        "prepare_pre_spend_card",
        "pre_spend_card",
    ),
    # Naming the gate as a command asks for it; before, it clarified on an
    # unrelated skill while the route hint named the gate.
    RoutingInterventionCase(
        "use-spend-gate-reaches-spend-gate",
        "Naming the spend gate as a command reaches the pre-spend card",
        "use spend gate",
        "dispatch",
        "spend-gate",
        "prepare_pre_spend_card",
        "pre_spend_card",
    ),
    # Paying with the person's card is not an image card (both dispatched it
    # before), and an image card of card-game stats still is.
    RoutingInterventionCase(
        "card-payment-for-a-report-reaches-spend-gate",
        "Paying with the person's card for a report reaches the pre-spend card, not an image card",
        "please pay with my card for the summary report",
        "dispatch",
        "spend-gate",
        "prepare_pre_spend_card",
        "pre_spend_card",
    ),
    # The same spend behind a Discord trigger note: the router reads the
    # person's words, not the note, which used to send it to
    # gateway-intent-card.
    # A leading bracket is a sender prefix only on a messaging gateway, and
    # even there one that names a skill, `omh` or `ulw` is the person's own.
    # Removed as a display name, each of these lost its route.
    RoutingInterventionCase(
        "omh-in-brackets-keeps-the-status-card",
        "OMH named in brackets keeps the status card",
        "[omh] what is the status",
        "dispatch",
        "oh-my-hermes",
        "show_status",
        "status",
    ),
    RoutingInterventionCase(
        "skill-name-in-brackets-keeps-its-skill",
        "A skill named in brackets keeps its skill",
        "[deep-interview] I have a new product idea",
        "dispatch",
        "deep-interview",
        "answer_clarification",
        "clarification",
    ),
    RoutingInterventionCase(
        "ulw-in-brackets-keeps-the-debugging-route",
        "ulw in brackets keeps the debugging route",
        "[ulw] fix the flaky tests",
        "dispatch",
        "app-debugging",
        "prepare_root_cause_investigation",
        "root_cause_investigation",
    ),
    RoutingInterventionCase(
        "card-payment-behind-a-discord-note-reaches-spend-gate",
        "Paying with the person's card behind a Discord trigger note still reaches the pre-spend card",
        "[Triggering message id: `1234` \u2014 use as `message_id` for reply/react/pin via the discord tools.]\n\n"
        "please pay with my card for the summary report",
        "dispatch",
        "spend-gate",
        "prepare_pre_spend_card",
        "pre_spend_card",
    ),
    RoutingInterventionCase(
        "credit-card-tickets-to-share-lead-with-spend-gate",
        "Tickets bought with the person's credit card and shared with someone ask with the pre-spend card leading",
        "can you use my credit card to buy the concert tickets and share them with my wife",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "spend-gate",
    ),
    RoutingInterventionCase(
        "share-card-of-card-game-stats-stays-on-img-summary",
        "A share card of card-game stats is still an image card",
        "make a share card summarizing my card game stats",
        "dispatch",
        "img-summary",
        "prepare_visual_prompt_card",
        "img_summary",
    ),
    RoutingInterventionCase(
        "share-card-with-my-card-collection-stays-on-img-summary",
        "A share card with the person's card collection is still an image card; the card pays nothing",
        "create a share card with my card collection highlights",
        "dispatch",
        "img-summary",
        "prepare_visual_prompt_card",
        "img_summary",
    ),
    # Every courtesy opener reads the same way on the router and the hint
    # (`request_lead.COURTESY_OPENERS`): "pls" and "kindly" mark a spend as
    # "please" does, and "hi," and "hermes," open a data-share request as
    # "hey," does.
    RoutingInterventionCase(
        "kindly-card-payment-reaches-spend-gate",
        "A card payment asked for with 'kindly' reaches the pre-spend card, as with 'please'",
        "kindly pay with my card for the hotel",
        "dispatch",
        "spend-gate",
        "prepare_pre_spend_card",
        "pre_spend_card",
        "spend-gate",
    ),
    RoutingInterventionCase(
        "pls-buy-it-for-me-leads-with-spend-gate",
        "A purchase asked for with 'pls' asks with the pre-spend card leading, as with 'please'",
        "pls buy it for me",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "spend-gate",
    ),
    RoutingInterventionCase(
        "hi-opened-export-for-a-researcher-reaches-data-share-review",
        "De-identifying an export for a researcher after 'hi,' reaches the data share review, as after 'hey,'",
        "hi, de-identify this export for the researcher",
        "dispatch",
        "data-share-review",
        "prepare_data_share_review",
        "data_share_review",
    ),
    RoutingInterventionCase(
        "hermes-addressed-export-for-a-researcher-reaches-data-share-review",
        "De-identifying an export for a researcher, addressed to Hermes, reaches the data share review",
        "hermes, de-identify this export for the researcher",
        "dispatch",
        "data-share-review",
        "prepare_data_share_review",
        "data_share_review",
    ),
    RoutingInterventionCase(
        "lets-opened-loop-that-buys-with-my-card-reaches-spend-gate",
        "A loop on a timer that buys with the person's card, opened with 'let's', reaches the pre-spend card",
        "let's loop every hour and buy the concert tickets for me with my card if they drop under $50",
        "dispatch",
        "spend-gate",
        "prepare_pre_spend_card",
        "pre_spend_card",
    ),
    RoutingInterventionCase(
        "spend-gate-run-on-a-spending-limit-reaches-spend-gate",
        "Running the gate by name on the person's spending limit reaches the pre-spend card; the named gate skips the cap's everyday sense",
        "run spend gate on my spending limit",
        "dispatch",
        "spend-gate",
        "prepare_pre_spend_card",
        "pre_spend_card",
    ),
    # Korean admission for the two safety gates (owner decision D.4): a
    # request ending closing a spend, or a protective act on personal data
    # with its recipient, reaches the gate by ordinary scoring. One of the
    # gate's phrases asks with it leading; two dispatch it.
    RoutingInterventionCase(
        "korean-card-payment-reaches-spend-gate",
        "Asking in Korean to pay with the person's card reaches the pre-spend card",
        "내 카드로 결제해줘",
        "dispatch",
        "spend-gate",
        "prepare_pre_spend_card",
        "pre_spend_card",
    ),
    RoutingInterventionCase(
        "korean-pay-for-this-leads-with-spend-gate",
        "Asking in Korean to pay for this asks with the pre-spend card leading",
        "이거 결제해줘",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "spend-gate",
    ),
    RoutingInterventionCase(
        "korean-remittance-leads-with-spend-gate",
        "Asking in Korean to send money asks with the pre-spend card leading",
        "송금해줘",
        "clarify",
        "oh-my-hermes",
        "answer_clarification",
        "clarification",
        "spend-gate",
    ),
    RoutingInterventionCase(
        "korean-spending-loop-reaches-spend-gate",
        "A Korean loop on a timer that pays with the person's card reaches the pre-spend card",
        "/loop 1h 가격 떨어지면 내 카드로 결제해줘",
        "dispatch",
        "spend-gate",
        "prepare_pre_spend_card",
        "pre_spend_card",
    ),
    RoutingInterventionCase(
        "korean-masked-customer-info-to-a-vendor-reaches-data-share-review",
        "Masking customer information and sending it to a vendor reaches the data share review, not a gateway card",
        "고객 정보 마스킹해서 벤더한테 보내줘",
        "dispatch",
        "data-share-review",
        "prepare_data_share_review",
        "data_share_review",
    ),
    RoutingInterventionCase(
        "korean-pii-removed-before-an-external-share-reaches-data-share-review",
        "Removing personal data and sharing it outside the team reaches the data share review",
        "개인정보 지우고 외부에 공유해줘",
        "dispatch",
        "data-share-review",
        "prepare_data_share_review",
        "data_share_review",
    ),
    RoutingInterventionCase(
        "korean-masking-before-sending-to-a-vendor-reaches-data-share-review",
        "Masking personal data before it goes to a vendor reaches the data share review",
        "벤더한테 보내기 전에 개인정보 마스킹해줘",
        "dispatch",
        "data-share-review",
        "prepare_data_share_review",
        "data_share_review",
    ),
    RoutingInterventionCase(
        "korean-greeting-before-a-card-payment-reaches-spend-gate",
        "A greeting sentence before a Korean card payment is not the request; the payment reaches the pre-spend card",
        "안녕하세요. 제 카드로 결제해 주세요.",
        "dispatch",
        "spend-gate",
        "prepare_pre_spend_card",
        "pre_spend_card",
    ),
    RoutingInterventionCase(
        "korean-hermes-addressed-masked-info-to-a-vendor-reaches-data-share-review",
        "Addressing Hermes before masking customer information for a vendor reaches the data share review",
        "헤르메스, 고객 정보 마스킹해서 벤더한테 보내줘",
        "dispatch",
        "data-share-review",
        "prepare_data_share_review",
        "data_share_review",
    ),
    RoutingInterventionCase(
        "korean-receipt-with-an-amount-stays-on-gateway-intent-card",
        "Sending a receipt that states an amount sends a document; the spend gate takes nothing from it",
        "결제 금액 10,000원 영수증 이메일로 보내줘",
        "dispatch",
        "gateway-intent-card",
        "prepare_gateway_intent_card",
        "gateway_intent",
    ),
    RoutingInterventionCase(
        "korean-quote-instead-of-paying-stays-on-gateway-intent-card",
        "Sending only the quote instead of paying with the card is no spend; the negated payment is not the request",
        "카드로 결제하지 말고 견적만 보내줘",
        "dispatch",
        "gateway-intent-card",
        "prepare_gateway_intent_card",
        "gateway_intent",
    ),
    RoutingInterventionCase(
        "korean-payment-bug-fix-stays-on-ultrawork",
        "Fixing a payment bug is coding work; the spend gate takes nothing from it",
        "결제 버그 고쳐줘",
        "dispatch",
        "ultrawork",
        "choose_executor",
        "handoff",
    ),
    RoutingInterventionCase(
        "korean-summary-shared-stays-on-long-document-reading",
        "Summarizing a document and sharing it protects no personal data; the data share review takes nothing from it",
        "이 문서 요약해서 공유해줘",
        "dispatch",
        "long-document-reading",
        "prepare_long_document_reading",
        "long_document_reading",
    ),
    # Owner decision 2026-10-16: a team qualified by an outside word is outside
    # the company, in English as in Korean, so the review still fires. The
    # English four dispatched on main too; the Korean four did not, because a
    # bare 팀 after an outside word, a team compound that starts with one, and
    # a test server after a vendor read as inside.
    RoutingInterventionCase(
        "dataset-shared-with-an-external-team-reaches-data-share-review",
        "Anonymizing a dataset before an external team gets it reaches the data share review",
        "anonymize the dataset before sharing it with an external team",
        "dispatch",
        "data-share-review",
        "prepare_data_share_review",
        "data_share_review",
    ),
    RoutingInterventionCase(
        "export-shared-with-the-customers-team-reaches-data-share-review",
        "Redacting an export before the customer's team gets it reaches the data share review",
        "redact the pii in the export before sharing it with the customer's team",
        "dispatch",
        "data-share-review",
        "prepare_data_share_review",
        "data_share_review",
    ),
    RoutingInterventionCase(
        "files-shared-with-the-client-team-reach-data-share-review",
        "Redacting files before the client team gets them reaches the data share review",
        "redact the pii in the files and share them with the client team",
        "dispatch",
        "data-share-review",
        "prepare_data_share_review",
        "data_share_review",
    ),
    RoutingInterventionCase(
        "dataset-shared-with-a-partners-staging-server-reaches-data-share-review",
        "Anonymizing a dataset before it goes to a partner's staging server reaches the data share review",
        "anonymize the dataset before sharing it with the partner's staging server",
        "dispatch",
        "data-share-review",
        "prepare_data_share_review",
        "data_share_review",
    ),
    RoutingInterventionCase(
        "korean-customer-info-shared-with-an-external-team-reaches-data-share-review",
        "Anonymizing customer information before an external team gets it reaches the data share review",
        "고객 정보 익명화해서 외부 팀에 공유해줘",
        "dispatch",
        "data-share-review",
        "prepare_data_share_review",
        "data_share_review",
    ),
    RoutingInterventionCase(
        "korean-masked-pii-to-a-vendor-team-reaches-data-share-review",
        "Masking personal data before it goes to a vendor's team reaches the data share review, not a gateway card",
        "개인정보 마스킹해서 벤더 팀에 보내줘",
        "dispatch",
        "data-share-review",
        "prepare_data_share_review",
        "data_share_review",
    ),
    RoutingInterventionCase(
        "korean-pii-to-an-external-team-compound-reaches-data-share-review",
        "Removing personal data before it goes to an external team written as one word reaches the data share review",
        "개인정보 지우고 외부팀에 보내줘",
        "dispatch",
        "data-share-review",
        "prepare_data_share_review",
        "data_share_review",
    ),
    RoutingInterventionCase(
        "korean-pii-to-a-vendor-test-server-reaches-data-share-review",
        "De-identifying personal data before it goes to a vendor's test server reaches the data share review",
        "개인정보 비식별화해서 벤더 테스트 서버에 올려줘",
        "dispatch",
        "data-share-review",
        "prepare_data_share_review",
        "data_share_review",
    ),
    # The fail-safe rule (review of #2158): a place is inside only when every
    # word of it is proven inside, and every place a send names must be. A
    # company, a possessive, a relative clause, a place after "at" or "of", a
    # second place, and a later send keep the review. All eleven English
    # cases dispatched on main; all but the customer success team lost it at
    # the first head of #2158. The Korean case did not dispatch on main.
    RoutingInterventionCase(
        "export-to-a-named-companys-team-reaches-data-share-review",
        "Redacting an export before it goes to a team named by a company reaches the data share review",
        "redact pii in the export before we send it to the acme team",
        "dispatch",
        "data-share-review",
        "prepare_data_share_review",
        "data_share_review",
    ),
    RoutingInterventionCase(
        "export-to-a-companys-data-team-reaches-data-share-review",
        "Redacting an export before it goes to another company's data team reaches the data share review",
        "redact pii in the export before we send it to acme's data team",
        "dispatch",
        "data-share-review",
        "prepare_data_share_review",
        "data_share_review",
    ),
    RoutingInterventionCase(
        "dataset-to-a-hospital-team-reaches-data-share-review",
        "Anonymizing a dataset before a hospital's team gets it reaches the data share review",
        "anonymize the dataset before sharing it with the hospital team",
        "dispatch",
        "data-share-review",
        "prepare_data_share_review",
        "data_share_review",
    ),
    RoutingInterventionCase(
        "export-to-the-department-of-health-reaches-data-share-review",
        "Redacting an export before it goes to a government department reaches the data share review",
        "redact pii in the export before we send it to the department of health",
        "dispatch",
        "data-share-review",
        "prepare_data_share_review",
        "data_share_review",
    ),
    RoutingInterventionCase(
        "export-to-a-former-colleague-at-another-company-reaches-data-share-review",
        "Redacting an export before a former colleague who now works elsewhere gets it reaches the data share review",
        "redact pii in the export before we send it to a former colleague who now works at acme",
        "dispatch",
        "data-share-review",
        "prepare_data_share_review",
        "data_share_review",
    ),
    RoutingInterventionCase(
        "dataset-to-a-companys-staging-server-reaches-data-share-review",
        "Anonymizing a dataset before it goes to another company's staging server reaches the data share review",
        "anonymize the dataset before uploading it to the acme staging server",
        "dispatch",
        "data-share-review",
        "prepare_data_share_review",
        "data_share_review",
    ),
    RoutingInterventionCase(
        "export-to-a-data-team-at-another-company-reaches-data-share-review",
        "Redacting an export before it goes to a data team at another company's office reaches the data share review",
        "redact pii in the export before we send it to the data team over at acme's office",
        "dispatch",
        "data-share-review",
        "prepare_data_share_review",
        "data_share_review",
    ),
    RoutingInterventionCase(
        "export-to-the-data-team-and-a-company-reaches-data-share-review",
        "Redacting an export before it goes to the data team and a company reaches the data share review",
        "redact pii in the export and send it to the data team and acme",
        "dispatch",
        "data-share-review",
        "prepare_data_share_review",
        "data_share_review",
    ),
    RoutingInterventionCase(
        "export-to-the-data-team-with-an-auditor-copied-reaches-data-share-review",
        "Redacting an export before it goes to the data team with an auditor copied reaches the data share review",
        "redact pii in the export and send it to the data team, cc the auditor",
        "dispatch",
        "data-share-review",
        "prepare_data_share_review",
        "data_share_review",
    ),
    RoutingInterventionCase(
        "export-forwarded-on-to-a-company-reaches-data-share-review",
        "Redacting an export the data team will forward to a company reaches the data share review",
        "redact pii in the export and send it to the data team so they can forward it to acme",
        "dispatch",
        "data-share-review",
        "prepare_data_share_review",
        "data_share_review",
    ),
    RoutingInterventionCase(
        "dataset-to-the-customer-success-team-reaches-data-share-review",
        "Anonymizing a dataset before the customer success team gets it keeps the review, since nothing proves that team is inside",
        "anonymize the dataset before sharing it with the customer success team",
        "dispatch",
        "data-share-review",
        "prepare_data_share_review",
        "data_share_review",
    ),
    RoutingInterventionCase(
        "korean-pii-to-qa-then-a-public-site-reaches-data-share-review",
        "Anonymizing personal data sent to the QA team and then uploaded to a public site reaches the data share review",
        "개인정보 익명화해서 QA팀에 보내고 캐글에 올려줘",
        "dispatch",
        "data-share-review",
        "prepare_data_share_review",
        "data_share_review",
    ),
    # Review of #2158 at 79e8f5218: words before the first send, a first
    # object of "give", and a quoted name masked out before the rule reads
    # the place. All three dispatched on main and lost it at 79e8f5218.
    RoutingInterventionCase(
        "export-an-outside-party-sees-first-reaches-data-share-review",
        "Redacting an export before a company sees it, then sending it to the dev team, reaches the data share review",
        "redact the pii in the export before acme sees it, and send it to the dev team",
        "dispatch",
        "data-share-review",
        "prepare_data_share_review",
        "data_share_review",
    ),
    RoutingInterventionCase(
        "export-copied-to-a-company-reaches-data-share-review",
        "Redacting an export and giving a company a copy before sending it to the dev team reaches the data share review",
        "redact the pii in the export, give acme a copy and send it to the dev team",
        "dispatch",
        "data-share-review",
        "prepare_data_share_review",
        "data_share_review",
    ),
    RoutingInterventionCase(
        "export-to-a-quoted-companys-data-team-reaches-data-share-review",
        "Redacting an export before it goes to a data team named by a quoted company reaches the data share review",
        "redact the pii in the export and send it to the \"acme\" data team",
        "dispatch",
        "data-share-review",
        "prepare_data_share_review",
        "data_share_review",
    ),
    # The masker read the `'` of a plural possessive as an opening quote that
    # never closed, so the send and the place after it went unread.
    RoutingInterventionCase(
        "export-after-a-plural-possessive-reaches-data-share-review",
        "Redacting the users' export before it goes to a company's team reaches the data share review",
        "redact pii in the users' export and send it to the acme team",
        "dispatch",
        "data-share-review",
        "prepare_data_share_review",
        "data_share_review",
    ),
    # A Korean request names any party before the place, so every word there
    # must be a closed word: one acting, a purpose, "for", and an outside word
    # with no particle keep the review. A later sentence that sends counts
    # too, and so do an English party between a send and its "to" and a
    # place in the next sentence. None of the seven dispatched on main.
    RoutingInterventionCase(
        "korean-member-file-a-partner-will-use-reaches-data-share-review",
        "Pseudonymizing a member file a partner will use, then handing it to the dev team, reaches the data share review",
        "협력사가 쓸 회원 파일 가명 처리해서 개발팀에 넘겨줘",
        "dispatch",
        "data-share-review",
        "prepare_data_share_review",
        "data_share_review",
    ),
    RoutingInterventionCase(
        "korean-file-for-a-partner-reaches-data-share-review",
        "De-identifying a file meant for a partner, then uploading it for the QA team, reaches the data share review",
        "협력사용 파일 비식별화해서 QA팀에 올려줘",
        "dispatch",
        "data-share-review",
        "prepare_data_share_review",
        "data_share_review",
    ),
    RoutingInterventionCase(
        "korean-member-list-for-a-partner-reaches-data-share-review",
        "Pseudonymizing a member list for a partner, then sending it to the dev team, reaches the data share review",
        "협력사를 위한 회원 리스트 가명 처리해서 개발팀에 보내줘",
        "dispatch",
        "data-share-review",
        "prepare_data_share_review",
        "data_share_review",
    ),
    RoutingInterventionCase(
        "korean-papers-an-outside-auditor-will-see-reach-data-share-review",
        "Masking papers an outside auditor will see, then sending them to the finance team, reaches the data share review",
        "외부 감사인이 볼 자료 개인정보 마스킹해서 재무팀에 보내줘",
        "dispatch",
        "data-share-review",
        "prepare_data_share_review",
        "data_share_review",
    ),
    RoutingInterventionCase(
        "korean-send-to-the-dev-team-then-a-vendor-reaches-data-share-review",
        "Masking customer information for the dev team and sending it to a vendor next reaches the data share review",
        "고객 정보 마스킹해서 개발팀에 보내줘. 벤더한테도 보내줘.",
        "dispatch",
        "data-share-review",
        "prepare_data_share_review",
        "data_share_review",
    ),
    RoutingInterventionCase(
        "export-sent-where-a-company-wants-it-reaches-data-share-review",
        "Redacting an export and sending it where a company wants it reaches the data share review",
        "redact pii in the export and send it where acme wants it, to the dev team",
        "dispatch",
        "data-share-review",
        "prepare_data_share_review",
        "data_share_review",
    ),
    RoutingInterventionCase(
        "export-a-company-wants-delivered-reaches-data-share-review",
        "Redacting an export a company wants delivered to the dev team reaches the data share review",
        "redact the pii in the export and send it. acme wants it delivered to the dev team.",
        "dispatch",
        "data-share-review",
        "prepare_data_share_review",
        "data_share_review",
    ),
    # A person typing a blueprint seed's first line, without the fixed line
    # Hermes writes after it, still routes to the blueprint skill.
    RoutingInterventionCase(
        "typed-blueprint-seed-line-stays-on-automation-blueprint",
        "A person typing a /blueprint seed's first line alone still opens automation blueprint",
        "Set up the 'Morning briefing' automation for me (automation blueprint 'morning-brief'). A short daily briefing.",
        "dispatch",
        "automation-blueprint",
        "prepare_scheduled_ops_blueprint",
        "automation_blueprint",
    ),
)


class RoutingPrecisionSummary(TypedDict):
    case_count: int
    passing_count: int
    negative_case_count: int
    negative_passing_count: int
    direct_answer_count: int
    file_lookup_count: int
    overroute_count: int
    catalog_picker_count: int
    generic_ack_count: int
    intervention_case_count: int
    intervention_passing_count: int
    missed_intervention_count: int
    intervention_generic_ack_count: int
    total_case_count: int
    total_passing_count: int
    all_passing: bool


class RoutingPrecisionPayload(TypedDict):
    schema_version: str
    source: str
    summary: RoutingPrecisionSummary
    check_basis: list[str]
    cases: list[dict[str, object]]
    intervention_cases: list[dict[str, object]]
    claim_boundary: str


def build_routing_precision_demo(*, source: str = "discord") -> RoutingPrecisionPayload:
    if source not in CHAT_SOURCES:
        raise ValueError(f"unsupported demo source: {source}")
    rows = [_evaluate_precision_case(case, source=source) for case in ROUTING_PRECISION_CASES]
    intervention_rows = [
        _evaluate_intervention_case(case, source=source)
        for case in ROUTING_INTERVENTION_CASES
    ]
    passing_count = sum(1 for row in rows if bool(row["passed"]))
    intervention_passing_count = sum(1 for row in intervention_rows if bool(row["passed"]))
    direct_count = sum(1 for row in rows if _nested(row, "observed").get("next_action") == "answer_directly")
    file_lookup_count = sum(1 for row in rows if _nested(row, "observed").get("next_action") == "answer_file_lookup")
    overroute_count = sum(1 for row in rows if bool(_nested(row, "observed").get("overrouted")))
    catalog_picker_count = sum(1 for row in rows if bool(_nested(row, "observed").get("catalog_picker_opened")))
    generic_ack_count = sum(1 for row in rows if _nested(row, "observed").get("response_kind") == "ack")
    missed_intervention_count = sum(1 for row in intervention_rows if not bool(row["passed"]))
    intervention_generic_ack_count = sum(
        1 for row in intervention_rows if _nested(row, "observed").get("response_kind") == "ack"
    )
    all_passing = (
        bool(rows)
        and bool(intervention_rows)
        and passing_count == len(rows)
        and intervention_passing_count == len(intervention_rows)
    )
    return {
        "schema_version": ROUTING_PRECISION_SCHEMA_VERSION,
        "source": source,
        "summary": {
            "case_count": len(rows),
            "passing_count": passing_count,
            "negative_case_count": len(rows),
            "negative_passing_count": passing_count,
            "direct_answer_count": direct_count,
            "file_lookup_count": file_lookup_count,
            "overroute_count": overroute_count,
            "catalog_picker_count": catalog_picker_count,
            "generic_ack_count": generic_ack_count,
            "intervention_case_count": len(intervention_rows),
            "intervention_passing_count": intervention_passing_count,
            "missed_intervention_count": missed_intervention_count,
            "intervention_generic_ack_count": intervention_generic_ack_count,
            "total_case_count": len(rows) + len(intervention_rows),
            "total_passing_count": passing_count + intervention_passing_count,
            "all_passing": all_passing,
        },
        "check_basis": [
            "Ordinary file and text lookup requests stay in answer_file_lookup.",
            "Plain general-help questions stay in answer_directly.",
            "Negative-control prompts do not open the OMH workflow picker.",
            "Negative-control prompts do not produce generic workflow acknowledgements.",
            "Negative-control prompts do not expose coding handoff or executor actions.",
            "Expected OMH requests still route to their workflow, picker, or context brief.",
            "Expected OMH requests do not collapse into generic acknowledgement cards.",
            "This gate checks deterministic local routing boundaries only; it does not prove live Hermes rendering or execution.",
        ],
        "cases": rows,
        "intervention_cases": intervention_rows,
        "claim_boundary": (
            "Routing precision proves deterministic local over-intervention and missed-intervention guards only. "
            "It does not prove live Hermes chat rendering, platform delivery, source retrieval, file inspection, "
            "executor dispatch, implementation, verification, review, CI, merge, or plugin-load evidence."
        ),
    }


def format_routing_precision_summary(payload: Mapping[str, object]) -> str:
    summary = _nested(payload, "summary")
    rows = _mapping_rows(payload.get("cases"))
    intervention_rows = _mapping_rows(payload.get("intervention_cases"))
    total = int(summary.get("case_count", len(rows)) or 0)
    passing = int(summary.get("passing_count", 0) or 0)
    intervention_total = int(summary.get("intervention_case_count", len(intervention_rows)) or 0)
    intervention_passing = int(summary.get("intervention_passing_count", 0) or 0)
    all_passing = bool(summary.get("all_passing", False))
    lines = [
        "OMH routing precision",
        f"Source: {payload.get('source', 'unknown')}",
        f"Result: {passing}/{total} negative-control cases passing" + (" (all passing)" if all_passing else ""),
        f"Interventions: {intervention_passing}/{intervention_total} expected workflow cases passing",
        (
            f"Direct answers: {summary.get('direct_answer_count', 0)}; "
            f"file lookups: {summary.get('file_lookup_count', 0)}; "
            f"overroutes: {summary.get('overroute_count', 0)}; "
            f"catalog pickers: {summary.get('catalog_picker_count', 0)}; "
            f"generic ack: {summary.get('generic_ack_count', 0)}; "
            f"missed interventions: {summary.get('missed_intervention_count', 0)}"
        ),
        "",
        "What this proves:",
    ]
    for basis in _string_items(payload.get("check_basis")):
        lines.append(f"- {basis}")
    lines.extend(["", "Precision rollup:"])
    for row in rows:
        observed = _nested(row, "observed")
        status = "ok" if row.get("passed") else "needs attention"
        next_action = next_action_label(str(observed.get("next_action", "unknown")))
        lines.append(
            f"- {row.get('title', 'Untitled precision case')}: {status}; "
            f"route={observed.get('route_action', 'unknown')} -> {next_action}"
        )
    if intervention_rows:
        lines.extend(["", "Intervention rollup:"])
        for row in intervention_rows:
            observed = _nested(row, "observed")
            status = "ok" if row.get("passed") else "needs attention"
            next_action = next_action_label(str(observed.get("next_action", "unknown")))
            lines.append(
                f"- {row.get('title', 'Untitled intervention case')}: {status}; "
                f"{observed.get('route_workflow', 'unknown')} -> {next_action}"
            )
    failed = [row for row in rows + intervention_rows if not row.get("passed")]
    if failed:
        lines.extend(["", "Failures:"])
        for row in failed:
            lines.append(f"- {row.get('id', 'unknown')}: {', '.join(_string_items(row.get('issues'))) or 'unknown issue'}")
    lines.extend(
        [
            "",
            f"Boundary: {payload.get('claim_boundary', '')}",
            "Use --json for the full machine-readable payload.",
        ]
    )
    return "\n".join(lines)


def routing_precision_errors(payload: Mapping[str, object]) -> list[str]:
    errors: list[str] = []
    if payload.get("schema_version") != ROUTING_PRECISION_SCHEMA_VERSION:
        errors.append("unexpected_schema")
    summary = _nested(payload, "summary")
    if not bool(summary.get("all_passing")):
        errors.append("not_all_precision_cases_passed")
    if int(summary.get("overroute_count", 0) or 0):
        errors.append(f"overroute_count: {summary.get('overroute_count')}")
    if int(summary.get("catalog_picker_count", 0) or 0):
        errors.append(f"catalog_picker_count: {summary.get('catalog_picker_count')}")
    if int(summary.get("generic_ack_count", 0) or 0):
        errors.append(f"generic_ack_count: {summary.get('generic_ack_count')}")
    if int(summary.get("missed_intervention_count", 0) or 0):
        errors.append(f"missed_intervention_count: {summary.get('missed_intervention_count')}")
    if int(summary.get("intervention_generic_ack_count", 0) or 0):
        errors.append(f"intervention_generic_ack_count: {summary.get('intervention_generic_ack_count')}")
    cases = payload.get("cases")
    if not isinstance(cases, Sequence) or isinstance(cases, (str, bytes)):
        errors.append("cases_not_sequence")
        return errors
    intervention_cases = payload.get("intervention_cases")
    if not isinstance(intervention_cases, Sequence) or isinstance(intervention_cases, (str, bytes)):
        errors.append("intervention_cases_not_sequence")
        return errors
    for case in cases:
        if not isinstance(case, Mapping) or bool(case.get("passed")):
            continue
        case_id = str(case.get("id") or "unknown")
        errors.append(f"{case_id}: {', '.join(_string_items(case.get('issues'))) or 'unknown precision failure'}")
    for case in intervention_cases:
        if not isinstance(case, Mapping) or bool(case.get("passed")):
            continue
        case_id = str(case.get("id") or "unknown")
        errors.append(f"{case_id}: {', '.join(_string_items(case.get('issues'))) or 'unknown intervention failure'}")
    return errors


def precision_case_interaction(case: RoutingPrecisionCase, *, source: str) -> dict[str, object]:
    """Route one negative-control case the way its evaluator does.

    The evaluator calls this too, so there is one call and not two that have to
    be kept the same.
    """
    return build_chat_interaction_payload(case.message, source=source)


def intervention_case_interaction(case: RoutingInterventionCase, *, source: str) -> dict[str, object]:
    """Route one intervention case the way its evaluator does.

    The design-direction context is part of the call, not a detail: a case that
    pins an iteration routes differently without it, so a second reader that
    built the payload itself would be measuring a different message. The
    evaluator calls this too, so the two cannot drift apart.
    """
    return build_chat_interaction_payload(
        case.message,
        source=source,
        design_direction_iteration_context=case.active_design_direction_iteration,
    )


def precision_case_verdict(
    case: RoutingPrecisionCase,
    interaction: dict[str, object],
    *,
    source: str,
) -> dict[str, bool]:
    """This corpus's own verdict on one negative-control case.

    `overrouted` is the corpus's headline failure metric and `passed` is the
    full case verdict. Both come straight from the evaluator that
    `build_routing_precision_demo` counts, so a second reader reports the same
    thing the gate reports. Re-deriving either from the route payload is how
    two OMH surfaces end up disagreeing about OMH's own router: `clarify` with
    a named candidate is a pass here -- the router asked one question instead
    of opening a workflow, picker, or handoff -- so a predicate that counts it
    as an intervention turns a large share of this corpus's passes into
    reported failures, on a corpus the gate holds at zero.
    """
    row = _evaluate_precision_case(case, source=source, interaction=interaction)
    observed = _nested(row, "observed")
    return {"passed": bool(row.get("passed")), "overrouted": bool(observed.get("overrouted"))}


def intervention_case_verdict(
    case: RoutingInterventionCase,
    interaction: dict[str, object],
    *,
    source: str,
) -> dict[str, bool]:
    """This corpus's own pass verdict on one intervention case.

    A miss here is `passed == False`; there is no separate over-route reading,
    because an intervention case is one the router is supposed to act on.
    """
    row = _evaluate_intervention_case(case, source=source, interaction=interaction)
    return {"passed": bool(row.get("passed"))}


def _evaluate_precision_case(
    case: RoutingPrecisionCase,
    *,
    source: str,
    interaction: dict[str, object] | None = None,
) -> dict[str, object]:
    # `interaction` lets a caller that already routed this message hand the
    # payload in instead of routing it a second time. It changes no verdict --
    # the evaluator below is unchanged -- and it is what keeps a second reader
    # of these corpora from routing several hundred messages twice.
    if interaction is None:
        interaction = precision_case_interaction(case, source=source)
    response = _nested(interaction, "chat_response")
    route = _nested(interaction, "route")
    response_state = _nested(response, "state")
    actions = _mapping_rows(response.get("actions"))
    action_ids = [str(action.get("id", "")) for action in actions]
    observed = {
        "schema_version": interaction.get("schema_version"),
        "source": interaction.get("source"),
        "mode": interaction.get("mode"),
        "route_action": route.get("action"),
        "route_workflow": route.get("selected_skill"),
        "route_confidence": route.get("confidence"),
        "route_reason": route.get("reason"),
        "next_action": interaction.get("next_action"),
        "response_kind": response.get("kind"),
        "plain_headline": response.get("plain_headline"),
        "lookup_kind": response_state.get("lookup_kind"),
        "catalog_picker_opened": response.get("kind") == "skill_picker" or bool(response_state.get("skill_picker")),
        "catalog_question": bool(response_state.get("catalog_question")),
        "capability_summary_opened": bool(response_state.get("capability_summary")),
        "workflow_card_opened": response.get("kind") not in {"clarification", "skill_picker"},
        "handoff_action_count": sum(1 for action_id in action_ids if _is_handoff_action(action_id)),
        "raw_message_echoed": _interaction_visible_text_contains(interaction, case.message),
        "claim_boundary": response.get("claim_boundary"),
    }
    observed["overrouted"] = (
        observed["route_action"] == "dispatch"
        or observed["workflow_card_opened"]
        or observed["catalog_picker_opened"]
        or int(observed["handoff_action_count"] or 0) > 0
    )

    issues: list[str] = []
    if observed["schema_version"] != "chat_interaction/v1":
        issues.append(f"unexpected schema {observed['schema_version']}")
    if observed["source"] != source:
        issues.append(f"unexpected source {observed['source']}")
    # `fallback` is the ordinary negative-control shape; `clarify` is equally
    # non-hijacking — the router asks one question instead of opening a
    # workflow, picker, or handoff — but it is accepted only for cases that
    # expect the clarification path, so a pre-existing fallback control that
    # drifts to `clarify` still fails on route_action alone.
    allowed_route_actions = (
        ("fallback", "clarify")
        if case.expected_next_action == "answer_clarification"
        else ("fallback",)
    )
    if observed["route_action"] not in allowed_route_actions:
        issues.append(
            f"expected {' or '.join(allowed_route_actions)} route, observed {observed['route_action']}"
        )
    if observed["route_workflow"] != "oh-my-hermes":
        issues.append(f"expected router workflow, observed {observed['route_workflow']}")
    if observed["next_action"] != case.expected_next_action:
        issues.append(f"expected next action {case.expected_next_action}, observed {observed['next_action']}")
    if str(observed["lookup_kind"] or "") != case.expected_lookup_kind:
        issues.append(f"expected lookup kind {case.expected_lookup_kind}, observed {observed['lookup_kind']}")
    if observed["response_kind"] != "clarification":
        issues.append(f"expected clarification response, observed {observed['response_kind']}")
    named_candidates = {str(route.get("candidate_skill") or "")}
    candidate_handoff = route.get("candidate_handoff")
    if isinstance(candidate_handoff, Mapping):
        named_candidates.update(
            str(candidate.get("skill") or "")
            for candidate in _mapping_rows(candidate_handoff.get("candidates"))
        )
    if case.forbidden_candidate and case.forbidden_candidate in named_candidates:
        issues.append(f"named forbidden candidate {case.forbidden_candidate}")
    if observed["catalog_picker_opened"]:
        issues.append("opened workflow picker")
    if observed["catalog_question"]:
        issues.append("marked ordinary prompt as catalog question")
    if observed["capability_summary_opened"]:
        issues.append("opened catalog capability summary")
    if observed["workflow_card_opened"]:
        issues.append(f"opened workflow card kind {observed['response_kind']}")
    if int(observed["handoff_action_count"] or 0):
        issues.append("exposed coding handoff or executor action")
    if observed["raw_message_echoed"]:
        issues.append("raw message echoed in machine payload")
    boundary = str(observed["claim_boundary"] or "")
    # A clarification-expected case can reach the clarification response through
    # either the dedicated `clarify` route action or a low-confidence `fallback`
    # that still asks one question (see the `allowed_route_actions` leniency
    # above) -- both surface the same "no execution" boundary text, so key this
    # off the expectation rather than the observed route action.
    if case.expected_next_action == "answer_clarification":
        if boundary != "No execution has started.":
            issues.append("missing no-execution claim boundary")
    elif not boundary.startswith("No OMH workflow"):
        issues.append("missing no-workflow claim boundary")
    _check_route_question(case.expected_route_question, route, case.message, observed, issues)

    return {
        "id": case.id,
        "title": case.title,
        "message_sha256": hashlib.sha256(case.message.encode("utf-8")).hexdigest(),
        "passed": not issues,
        "expected": {
            "route_action": "fallback",
            "next_action": case.expected_next_action,
            "lookup_kind": case.expected_lookup_kind,
        },
        "observed": observed,
        "issues": issues,
    }


def _evaluate_intervention_case(
    case: RoutingInterventionCase,
    *,
    source: str,
    interaction: dict[str, object] | None = None,
) -> dict[str, object]:
    # See `_evaluate_precision_case` for why `interaction` is accepted.
    if interaction is None:
        interaction = intervention_case_interaction(case, source=source)
    response = _nested(interaction, "chat_response")
    route = _nested(interaction, "route")
    response_state = _nested(response, "state")
    actions = _mapping_rows(response.get("actions"))
    action_ids = [str(action.get("id", "")) for action in actions]
    observed = {
        "schema_version": interaction.get("schema_version"),
        "source": interaction.get("source"),
        "mode": interaction.get("mode"),
        "route_action": route.get("action"),
        "route_workflow": route.get("selected_skill"),
        "route_confidence": route.get("confidence"),
        "route_reason": route.get("reason"),
        "next_action": interaction.get("next_action"),
        "response_kind": response.get("kind"),
        "plain_headline": response.get("plain_headline"),
        "lookup_kind": response_state.get("lookup_kind"),
        "catalog_picker_opened": response.get("kind") == "skill_picker" or bool(response_state.get("skill_picker")),
        "catalog_question": bool(response_state.get("catalog_question")),
        "capability_summary_opened": bool(response_state.get("capability_summary")),
        "handoff_action_count": sum(1 for action_id in action_ids if _is_handoff_action(action_id)),
        "raw_message_echoed": _interaction_visible_text_contains(interaction, case.message),
        "claim_boundary": response.get("claim_boundary"),
    }

    issues: list[str] = []
    if observed["schema_version"] != "chat_interaction/v1":
        issues.append(f"unexpected schema {observed['schema_version']}")
    if observed["source"] != source:
        issues.append(f"unexpected source {observed['source']}")
    if observed["route_action"] != case.expected_route_action:
        issues.append(f"expected route action {case.expected_route_action}, observed {observed['route_action']}")
    if observed["route_workflow"] != case.expected_workflow:
        issues.append(f"expected workflow {case.expected_workflow}, observed {observed['route_workflow']}")
    if observed["next_action"] != case.expected_next_action:
        issues.append(f"expected next action {case.expected_next_action}, observed {observed['next_action']}")
    if observed["response_kind"] != case.expected_response_kind:
        issues.append(f"expected response kind {case.expected_response_kind}, observed {observed['response_kind']}")
    observed_candidate = str(route.get("candidate_skill") or "")
    if case.expected_candidate and observed_candidate != case.expected_candidate:
        issues.append(f"expected candidate {case.expected_candidate}, observed {observed_candidate}")
    observed_confidence = str(observed["route_confidence"] or "")
    if case.expected_confidence and observed_confidence != case.expected_confidence:
        issues.append(
            f"expected confidence {case.expected_confidence}, observed {observed_confidence}"
        )
    if observed["response_kind"] == "ack":
        issues.append("generic acknowledgement replaced expected workflow surface")
    if observed["raw_message_echoed"]:
        issues.append("raw message echoed in machine payload")
    if not str(observed["claim_boundary"] or ""):
        issues.append("missing claim boundary")
    _check_route_question(case.expected_route_question, route, case.message, observed, issues)

    return {
        "id": case.id,
        "title": case.title,
        "message_sha256": hashlib.sha256(case.message.encode("utf-8")).hexdigest(),
        "passed": not issues,
        "expected": {
            "route_action": case.expected_route_action,
            "workflow": case.expected_workflow,
            "next_action": case.expected_next_action,
            "response_kind": case.expected_response_kind,
            "candidate": case.expected_candidate,
            "confidence": case.expected_confidence,
        },
        "observed": observed,
        "issues": issues,
    }


def _check_route_question(
    expected: str,
    route: Mapping[str, object],
    message: str,
    observed: dict[str, object],
    issues: list[str],
) -> None:
    """Pin the route question's decline predicate on a case that asks for it.

    Read through `route_question_decline_reason`, the one producer, over the
    route this case's own payload carries. Cases that set nothing are not
    read, so their rows stay the shape they were.
    """
    if not expected:
        return
    if not isinstance(route.get("route_question"), Mapping):
        actual = "no_question"
    else:
        actual = route_question_decline_reason(route, message) or ROUTE_QUESTION_ASKED
    observed["route_question"] = actual
    if actual != expected:
        issues.append(f"expected route question {expected}, observed {actual}")


def _is_handoff_action(action_id: str) -> bool:
    text = action_id.lower()
    return any(marker in text for marker in ("handoff", "executor", "codex", "claude", "dispatch"))


def _interaction_visible_text_contains(interaction: dict[str, object], needle: str) -> bool:
    if not needle:
        return False
    response = _nested(interaction, "chat_response")
    route = _nested(interaction, "route")
    response_state = _nested(response, "state")
    route_explanation = _nested(route, "route_explanation")
    text_fields: list[object] = [
        route.get("routing_prompt"),
        route.get("routing_instruction"),
        route.get("routing_prompt_template"),
        route.get("reason"),
        route.get("clarification"),
        route_explanation.get("recommended_reply"),
        route_explanation.get("primary_action_hint"),
        route_explanation.get("headline"),
        route_explanation.get("summary"),
        response.get("headline"),
        response.get("plain_headline"),
        response.get("body"),
        response.get("claim_boundary"),
        response_state.get("workflow_explanation_reason"),
    ]
    for action in _mapping_rows(response.get("actions")):
        text_fields.extend((action.get("label"), action.get("hint")))
    return any(needle in str(value) for value in text_fields if value)


def _nested(payload: object, key: str) -> dict[str, object]:
    if isinstance(payload, Mapping):
        value = payload.get(key)
        return value if isinstance(value, dict) else {}
    return {}


def _mapping_rows(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _string_items(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [str(item) for item in value]
