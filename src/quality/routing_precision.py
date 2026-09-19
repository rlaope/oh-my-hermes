from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Mapping, Sequence, TypedDict

from ..ingress import CHAT_SOURCES
from ..routing.action_copy import next_action_label
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
    # turn an operational sentence into a workflow dispatch. No
    # `forbidden_candidate` on any of the five below: the field also reads the
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
        "database-index-question-is-not-workflow-learning",
        "A missing database index is not a workflow-learning request",
        "this query seq-scans 40M rows, what index",
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
    RoutingInterventionCase(
        "apple-glass-database-stays-with-backend",
        "Apple Glass database request does not select the Apple UI specialist",
        "Design the schema for our Apple Glass database.",
        "dispatch",
        "backend",
        "prepare_backend_handoff",
        "backend_contract",
        "backend",
    ),
    RoutingInterventionCase(
        "generic-ui-stays-with-frontend",
        "Generic UI request does not select the Apple UI specialist",
        "Improve the layout of our generic SaaS dashboard.",
        "dispatch",
        "frontend",
        "prepare_frontend_handoff",
        "frontend_handoff",
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
    RoutingInterventionCase(
        "generic-gsap-stays-with-frontend",
        "Generic GSAP animation does not select Apple design",
        "Use GSAP for our existing website animation timeline.",
        "dispatch",
        "frontend",
        "prepare_frontend_handoff",
        "frontend_handoff",
        "frontend",
    ),
    RoutingInterventionCase(
        "generic-liquid-logo-stays-with-planning",
        "Generic liquid-logo implementation does not select Apple design",
        "Implement a liquid logo in our existing website header.",
        "dispatch",
        "ultrawork",
        "present_plan",
        "plan",
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
    RoutingInterventionCase(
        "websearch-setup-outranks-the-lookup-lane",
        "Configuring web search still reaches websearch-setup rather than the lookup lane",
        "set up web search",
        "dispatch",
        "websearch-setup",
        "run_setup_guide",
        "setup_guide",
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
    RoutingInterventionCase(
        "agent-surface-stays-security-safety-review",
        "The agent's own prompt and tool surface stays with the safety review, not the application model",
        "review the prompt injection and tool permission risks in this agent before we run it",
        "dispatch",
        "security-safety-review",
        "prepare_security_safety_review",
        "security_safety_review",
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
    RoutingInterventionCase(
        "closed-incident-stays-reliability-review",
        "A closed incident's notes and postmortem stay with the reliability review",
        "review the incident notes and the postmortem for last week's outage",
        "dispatch",
        "reliability-review",
        "prepare_reliability_review",
        "reliability_review",
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
    RoutingInterventionCase(
        "release-watch-stays-deploy-and-monitor",
        "Watching a healthy release stays with deploy-and-monitor, not the incident lane",
        "the deploy is healthy, monitor the error rate for an hour",
        "dispatch",
        "deploy-and-monitor",
        "prepare_deploy_monitor_plan",
        "deploy_monitor_plan",
    ),
    RoutingInterventionCase(
        "contract-compliance-review-stays-legal",
        "Reviewing a contract for compliance risk stays legal compliance review",
        "can you review this contract for compliance risk",
        "dispatch",
        "legal-compliance-review",
        "prepare_legal_compliance_review",
        "legal_compliance_review",
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
    RoutingInterventionCase(
        "large-pdf-upload-failure-stays-materials",
        "A large PDF upload failure is a file problem, not a reading request",
        "large pdf upload keeps failing in production",
        "dispatch",
        "materials-package",
        "prepare_material_package",
        "materials_package",
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
    RoutingInterventionCase(
        "huge-pdf-crash-debug-stays-materials",
        "Debugging a viewer crash on a huge PDF stays file packaging",
        "a huge pdf crashed the viewer, debug it",
        "dispatch",
        "materials-package",
        "prepare_material_package",
        "materials_package",
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
    RoutingInterventionCase(
        "style-guide-long-document-section-stays-ultrawork",
        "Adding a section to a long style guide stays a coding handoff",
        "our style guide is a long document, where do I add a section",
        "dispatch",
        "ultrawork",
        "choose_executor",
        "handoff",
        "ultrawork",
    ),
    RoutingInterventionCase(
        "spec-page-year-stays-code-review",
        "A year near the word page is not a page count",
        "review the spec page we wrote in 2024",
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
    RoutingInterventionCase(
        "loop-run-telemetry-stays-ops-observability",
        "Token, cost, and latency of operations still reach the telemetry card",
        "show token cost and latency for the last week of loop runs",
        "dispatch",
        "ops-observability-card",
        "prepare_ops_observability_card",
        "ops_observability",
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
    RoutingInterventionCase(
        "a-page-operation-still-reaches-browser-operator",
        "A real page operation still reaches the browser lane",
        "open the checkout page in staging and click through the form",
        "dispatch",
        "browser-operator",
        "prepare_browser_operator_card",
        "browser_operator",
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
    RoutingInterventionCase(
        "greenfield-build-reaches-interview",
        "An English greenfield build request reaches the interview lane whatever the product noun",
        "let's build a react todo list",
        "dispatch",
        "deep-interview",
        "answer_clarification",
        "clarification",
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
    RoutingInterventionCase(
        "jit-learn-negative-curriculum-design",
        "An explicit multi-week syllabus remains curriculum design",
        "Design a six-week curriculum with weekly lessons and assessments for new support agents.",
        "dispatch",
        "curriculum-design",
        "prepare_curriculum_design",
        "curriculum_design",
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
    RoutingInterventionCase(
        "jit-learn-negative-research",
        "An already-scoped current-source investigation reaches the web lookup lane",
        "Research the latest Kubernetes 1.35 release notes with current primary sources and citations.",
        "dispatch",
        "web-research",
        "run_hermes_research",
        "web_research",
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
    RoutingInterventionCase(
        "jit-learn-negative-postmortem-report-rollback",
        "Postmortem report rollback investigation remains reliability review",
        "review the postmortem report this week before choosing the rollback path",
        "dispatch",
        "reliability-review",
        "prepare_reliability_review",
        "reliability_review",
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
    RoutingInterventionCase(
        "dependency-topology-parallel-then-integrate",
        "Dependency-shaped parallel work reaches ultrawork's topology decision",
        "analyze API and UI in parallel, then integrate the results and verify",
        "dispatch",
        "ultrawork",
        "forward_plan_to_selected_workflow",
        "plan",
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
    RoutingInterventionCase(
        "greenfield-git-init-what-now-reaches-interview",
        "'I just ran git init, what now' reaches the interview lane instead of unrelated low-confidence guesses",
        "I just ran git init, what now",
        "dispatch",
        "deep-interview",
        "answer_clarification",
        "clarification",
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
    RoutingInterventionCase(
        "named-cadence-reaches-the-recurring-surface-comparison",
        "A named cadence reaches the same lane, where the schedule beats the other three",
        "every weekday morning check the error budget and post a digest",
        "dispatch",
        "automation-blueprint",
        "prepare_scheduled_ops_blueprint",
        "automation_blueprint",
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


def _evaluate_precision_case(case: RoutingPrecisionCase, *, source: str) -> dict[str, object]:
    interaction = build_chat_interaction_payload(case.message, source=source)
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


def _evaluate_intervention_case(case: RoutingInterventionCase, *, source: str) -> dict[str, object]:
    interaction = build_chat_interaction_payload(
        case.message,
        source=source,
        design_direction_iteration_context=case.active_design_direction_iteration,
    )
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
