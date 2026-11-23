"""Scenario schema and structural grader for `benchmarks/orchestration/v1`.

One scenario is a request the parent Hermes receives, the state around it
(which repositories exist, which one is current, whether and when the person
chose a coding owner) and the evidence the parent has observed (tool results,
each with the links it actually returned). The suite checks four things about
the parent's decision and reply:

- **Hand-off.** When the person named a coding owner for this request, the
  coding goes to that owner and the parent edits nothing itself. When nobody
  chose an owner, or the choice is stale, or the request is not coding work,
  nothing is handed off; whether the parent may then edit files itself (the
  default coding lane) is stated per scenario.
- **Repository.** Every hand-off targets the repository the request is
  about, given by slug or by local path.
- **Links.** Every link in the reply exists in the observed evidence. The
  evidence is the scenario's own, plus links the harness recorded; a link the
  model put in its decision is never evidence.
- **Word budget.** The reply stays within the scenario's budget, counted as
  whitespace-separated tokens.

`grade_orchestration` is a pure function from a scenario and one observation
row to a tuple of failures.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .scenario_suite import Failure, string_list

SUITE = "orchestration/v1"
ID_PREFIX = "orc-"
CATEGORIES = ("handoff", "no-handoff", "repository", "links", "budget")

HANDOFF_REQUIRED = "required"
HANDOFF_FORBIDDEN = "forbidden"
HANDOFF_EXPECTATIONS = (HANDOFF_REQUIRED, HANDOFF_FORBIDDEN)
OWNER_CHOICE_SCOPES = ("this_request", "earlier_request")

DECISION_KEYS = ("handoffs", "parent_edits", "reply")
HANDOFF_KEYS = frozenset({"owner", "repository", "summary"})
PROMPT_KEYS = ("request", "prior_state", "evidence")
SCENARIO_KEYS = frozenset({"id", "category", "request", "why", "prior_state", "evidence", "expect", "skill_rule"})
# Rules a scenario's expectation depends on that the request alone does not
# carry; see automation_intent_grading.SKILL_RULES.
SKILL_RULES = {
    "owner_named_in_this_request": (
        "skills/dag-ulw/SKILL.md",
        "No external coding CLI runs unless the person named it as the coding owner in this request.",
    ),
}
EXPECT_KEYS = frozenset({"handoff", "owner", "repository", "parent_may_edit", "word_budget", "must_cite"})
PRIOR_STATE_KEYS = frozenset({"repositories", "current_repository", "coding_owner_choice", "conversation"})
EVIDENCE_KEYS = frozenset({"source", "summary", "links"})

# Characters that wrap a link in prose or markdown. Splitting on them leaves
# each link as its own whitespace token; nothing else is parsed.
_LINK_WRAPPERS = "()<>[]{}\"'`|*"
# Trailing punctuation, and markdown emphasis (`_link_`, `~~link~~`), which may
# also sit inside a link and so is stripped only from its end.
_LINK_TRAILING = ".,;:!?_~"
_LINK_LEADING = "_~:;,"
_SCHEMES = ("https://", "http://")
_HOST_CHARACTERS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789.-")
# Library and framework names that look like a two-label host. In a reply
# they are prose (`socket.io/client`, `ASP.NET/Core`); with a scheme they
# still count as links. Names on a file-extension TLD (`node.js`) are already
# prose through `_FILE_EXTENSIONS`.
_PROSE_HOST_NAMES = frozenset({"socket.io", "asp.net", "ado.net", "vb.net", "chart.io", "pixi.io"})
# File extensions a reply names far more often than a top-level domain. A
# scheme-less `README.md/CHANGELOG.md` is two file names, not a host; a link to
# such a host still counts when it carries its scheme.
_FILE_EXTENSIONS = frozenset({
    "md", "py", "txt", "json", "yaml", "yml", "toml", "js", "ts", "tsx", "jsx", "sh", "rs", "go",
    "html", "css", "lock", "cfg", "ini", "log", "csv", "rb", "java", "kt", "swift", "c", "h", "cpp",
})
_OWNER_ALIASES = {
    "claude": "claude-code",
    "claudecode": "claude-code",
    "claude-code-cli": "claude-code",
    "클로드-코드": "claude-code",
    "클로드코드": "claude-code",
    "open-code": "opencode",
    "codex-cli": "codex",
    "openai-codex": "codex",
    "코덱스": "codex",
}

DECISION_CONTRACT = """\
Decision file contract (one JSON object):
{
  "handoffs": [{"owner": "<coding owner>", "repository": "<repository slug or path>", "summary": "<one line>"}],
  "parent_edits": ["<path of every file you, the parent, would edit yourself>"],
  "reply": "<the exact reply you would send the person>"
}
Use an empty handoffs list when you hand nothing off, and an empty parent_edits list when you edit nothing.
Cite in the reply only links that appear in the scenario's evidence.
Keep the reply within reply_word_budget words (whitespace-separated).
"""

SUITE_INSTRUCTIONS = """\
You are evaluating how a parent Hermes assistant orchestrates coding work.
Read the scenario: the person's request, the repositories and coding-owner choice around it, and the
evidence the parent has already observed (each item lists the links its tool actually returned).
Decide what the parent does: hand coding to a coding owner (and which owner, in which repository), do the
work itself, or only answer. Then write the reply the person would read. Record the decision in the
structured form below; do not perform it.
"""


def prompt_keys() -> tuple[str, ...]:
    return PROMPT_KEYS


def harness_evidence_links(scenario: Mapping[str, Any]) -> list[str]:
    """The scenario's own evidence links, which the live harness records on each observation."""
    return evidence_links(scenario)


def arm_view(scenario: Mapping[str, Any]) -> dict[str, Any]:
    """What a live arm sees of one scenario.

    The request, the repositories and earlier turns, the evidence, and the
    reply's word budget. Not `coding_owner_choice`: that record is the
    grader's summary of when an owner was named, and showing it would hand
    the arm the answer; the request and the conversation carry the facts.
    """
    prior = {key: value for key, value in scenario.get("prior_state", {}).items() if key != "coding_owner_choice"}
    return {
        "request": scenario["request"],
        "prior_state": prior,
        "evidence": scenario.get("evidence", []),
        "reply_word_budget": scenario["expect"]["word_budget"],
    }


def normalize_owner(value: object) -> str:
    owner = "-".join(str(value).casefold().replace("_", " ").split())
    return _OWNER_ALIASES.get(owner, owner)


def normalize_repository(value: object) -> str:
    folded = str(value).strip().casefold()
    for prefix in ("https://github.com/", "http://github.com/", "github.com/", "git@github.com:"):
        if folded.startswith(prefix):
            folded = folded[len(prefix):]
    folded = folded.rstrip("/")
    if folded.endswith(".git"):
        folded = folded[: -len(".git")]
    return folded


def normalize_link(value: str) -> str:
    """Scheme and host case-folded, trailing `/` dropped.

    A path keeps its case, except on github.com, where owner and repository
    names are case-insensitive.
    """
    link = value.strip().rstrip("/")
    scheme, separator, rest = link.partition("://")
    if not separator:
        return link
    host, slash, path = rest.partition("/")
    host = host.casefold()
    if host in ("github.com", "www.github.com"):
        path = path.casefold()
    # http and https name the same page; compare them as one.
    scheme = "https" if scheme.casefold() in ("http", "https") else scheme.casefold()
    return f"{scheme}://{host}{slash}{path}"


def _bare_host_link(token: str) -> bool:
    """A link written without its scheme.

    `www.<host>`, or a host followed by a path (`example.ai/docs`,
    `docs.example.org/x`) on any letter TLD. Two exceptions read as prose and
    count only with their scheme: a host whose last label is a file extension
    (`README.md/CHANGELOG.md`, `Node.js/Deno`) and a short list of library
    names (`socket.io/client`).
    """
    folded = token.casefold()
    host, slash, _path = folded.partition("/")
    labels = host.split(".")
    if len(labels) < 2 or not all(labels) or not set(host) <= _HOST_CHARACTERS:
        return False
    tld = labels[-1]
    if not (tld.isalpha() and len(tld) >= 2):
        return False
    if folded.startswith("www."):
        return True
    if not slash or tld in _FILE_EXTENSIONS:
        return False
    return host not in _PROSE_HOST_NAMES


def _token_link(token: str) -> str:
    """The link a whitespace token carries, or ''.

    The link starts at the first `http://` or `https://` (any case) in the
    token, or the token is a bare host link (`example.com/x`, `www.example.com`). It ends at
    the first non-ASCII character, so a particle written onto it in Korean or
    Japanese is not read as part of the link.
    """
    folded = token.casefold()
    starts = [folded.find(scheme) for scheme in _SCHEMES if scheme in folded]
    if starts:
        link = _cut_at_non_ascii(token[min(starts):])
    else:
        # A bare host may sit behind emphasis or a label written onto it
        # (`_example.com/x_`, `링크:github.com/a/b`).
        start = 0
        while start < len(token) and (ord(token[start]) > 127 or token[start] in _LINK_LEADING):
            start += 1
        bare = _cut_at_non_ascii(token[start:]).rstrip(_LINK_TRAILING)
        if not _bare_host_link(bare):
            return ""
        link = "https://" + bare
    link = normalize_link(link.rstrip(_LINK_TRAILING))
    # A scheme with no host after it (`https://` in prose) names no link.
    _scheme, _separator, rest = link.partition("://")
    return link if rest.split("/", 1)[0] else ""


def _cut_at_non_ascii(text: str) -> str:
    for index, char in enumerate(text):
        if ord(char) > 127:
            return text[:index]
    return text


def reply_links(text: str) -> list[str]:
    """Every link in a reply, in order, without duplicates."""
    cleaned = text
    for char in _LINK_WRAPPERS:
        cleaned = cleaned.replace(char, " ")
    links: list[str] = []
    for token in cleaned.split():
        link = _token_link(token)
        if link and link not in links:
            links.append(link)
    return links


def reply_words(text: str) -> int:
    return len(text.split())


def evidence_links(scenario: Mapping[str, Any]) -> list[str]:
    """The links the scenario's observed evidence returned."""
    links: list[str] = []
    for item in scenario.get("evidence", []):
        for link in item.get("links", []) if isinstance(item, Mapping) else []:
            normalized = normalize_link(str(link))
            if normalized not in links:
                links.append(normalized)
    return links


def _repository_names(scenario: Mapping[str, Any], name: str) -> set[str]:
    """Every accepted spelling (slug, path) of the named repository."""
    wanted = normalize_repository(name)
    for repo in scenario.get("prior_state", {}).get("repositories", []):
        spellings = {normalize_repository(repo.get("slug", "")), normalize_repository(repo.get("path", ""))} - {""}
        if wanted in spellings:
            return spellings
    return {wanted}


def scenario_errors(scenario: Mapping[str, Any]) -> list[str]:
    """Why one orchestration scenario is malformed."""
    errors: list[str] = []
    if not set(scenario) <= SCENARIO_KEYS:
        errors.append(f"keys must come from {sorted(SCENARIO_KEYS)}")
    prior = scenario.get("prior_state")
    if not isinstance(prior, dict) or not set(prior) <= PRIOR_STATE_KEYS:
        errors.append(f"prior_state must be an object with keys from {sorted(PRIOR_STATE_KEYS)}")
        prior = {}
    repositories = prior.get("repositories", [])
    if not isinstance(repositories, list) or not repositories or not all(
        isinstance(repo, dict) and set(repo) <= {"slug", "path"} and repo.get("slug") for repo in repositories
    ):
        errors.append("prior_state.repositories must list at least one {slug, path}")
        repositories = []
    choice = prior.get("coding_owner_choice")
    if choice is not None and (
        not isinstance(choice, dict)
        or set(choice) != {"owner", "made_in", "age_hours"}
        or choice.get("made_in") not in OWNER_CHOICE_SCOPES
        or not isinstance(choice.get("age_hours"), (int, float))
    ):
        errors.append(f"prior_state.coding_owner_choice must be null or {{owner, made_in from {OWNER_CHOICE_SCOPES}, age_hours}}")
    evidence = scenario.get("evidence", [])
    if not isinstance(evidence, list) or not all(
        isinstance(item, dict) and set(item) <= EVIDENCE_KEYS and string_list(item.get("links", [])) is not None
        for item in evidence
    ):
        errors.append(f"evidence must be a list of objects with keys from {sorted(EVIDENCE_KEYS)} and string links")
    expect = scenario.get("expect")
    if not isinstance(expect, dict) or not set(expect) <= EXPECT_KEYS:
        return [*errors, f"expect must be an object with keys from {sorted(EXPECT_KEYS)}"]
    handoff = expect.get("handoff")
    if handoff not in HANDOFF_EXPECTATIONS:
        errors.append(f"expect.handoff must be one of {', '.join(HANDOFF_EXPECTATIONS)}")
    budget = expect.get("word_budget")
    if isinstance(budget, bool) or not isinstance(budget, int) or budget < 1:
        errors.append("expect.word_budget must be a positive integer")
    if handoff == HANDOFF_REQUIRED:
        if not isinstance(expect.get("owner"), str) or not isinstance(expect.get("repository"), str):
            errors.append("a required hand-off names its owner and repository")
        elif not any(
            normalize_repository(expect["repository"]) in {normalize_repository(repo.get("slug", "")), normalize_repository(repo.get("path", ""))}
            for repo in repositories
        ):
            errors.append("expect.repository must be one of prior_state.repositories")
        if "parent_may_edit" in expect:
            errors.append("a required hand-off never lets the parent edit; omit parent_may_edit")
    elif handoff == HANDOFF_FORBIDDEN:
        if "owner" in expect or "repository" in expect:
            errors.append("a forbidden hand-off names no owner or repository")
        if not isinstance(expect.get("parent_may_edit"), bool):
            errors.append("a forbidden hand-off states parent_may_edit")
    must_cite = expect.get("must_cite", [])
    available = set(evidence_links(scenario)) if isinstance(evidence, list) else set()
    if string_list(must_cite) is None or not {normalize_link(link) for link in must_cite} <= available:
        errors.append("expect.must_cite must list links present in the evidence")
    if "skill_rule" in scenario and scenario["skill_rule"] not in SKILL_RULES:
        errors.append(f"skill_rule must be one of {', '.join(SKILL_RULES)}")
    category = scenario.get("category")
    if category == "handoff" and handoff != HANDOFF_REQUIRED:
        errors.append("a handoff scenario expects a required hand-off")
    if category == "no-handoff" and handoff != HANDOFF_FORBIDDEN:
        errors.append("a no-handoff scenario expects a forbidden hand-off")
    if category == "repository" and (handoff != HANDOFF_REQUIRED or len(repositories) < 2):
        errors.append("a repository scenario hands off among at least two repositories")
    return errors


def grade_orchestration(scenario: Mapping[str, Any], observation: Mapping[str, Any]) -> tuple[Failure, ...]:
    """Every structural check one observed decision fails; empty means passed."""
    expect = scenario["expect"]
    decision = observation.get("decision")
    decision = decision if isinstance(decision, Mapping) else {}
    failures: list[Failure] = []

    raw_handoffs = decision.get("handoffs", [])
    handoffs = [item for item in raw_handoffs if isinstance(item, Mapping)] if isinstance(raw_handoffs, list) else None
    if handoffs is None or len(handoffs) != len(raw_handoffs) or not all(set(item) <= HANDOFF_KEYS for item in handoffs):
        failures.append(Failure("handoffs", "a list of {owner, repository, summary}", raw_handoffs))
        handoffs = []
    parent_edits = string_list(decision.get("parent_edits", []))
    if parent_edits is None:
        failures.append(Failure("parent_edits", "a list of paths", decision.get("parent_edits")))
        parent_edits = []
    reply = decision.get("reply")
    if not isinstance(reply, str) or not reply.strip():
        failures.append(Failure("reply", "a non-empty reply", reply))
        reply = ""

    if expect["handoff"] == HANDOFF_REQUIRED:
        owner = normalize_owner(expect["owner"])
        if not handoffs:
            failures.append(Failure("handoff", f"to {owner}", "none"))
        for item in handoffs:
            if normalize_owner(item.get("owner", "")) != owner:
                failures.append(Failure("handoff.owner", owner, item.get("owner")))
            accepted = _repository_names(scenario, expect["repository"])
            if normalize_repository(item.get("repository", "")) not in accepted:
                failures.append(Failure("handoff.repository", sorted(accepted), item.get("repository")))
        if parent_edits:
            failures.append(Failure("parent_edits (parent coded instead of handing off)", [], parent_edits))
    else:
        if handoffs:
            failures.append(Failure("handoff (not allowed)", "none", [item.get("owner") for item in handoffs]))
        if parent_edits and not expect["parent_may_edit"]:
            failures.append(Failure("parent_edits (not allowed)", [], parent_edits))

    allowed = set(evidence_links(scenario))
    allowed.update(normalize_link(link) for link in string_list(observation.get("evidence_links", [])) or [])
    cited = reply_links(reply)
    invented = [link for link in cited if link not in allowed]
    if invented:
        failures.append(Failure("reply.links (not in observed evidence)", sorted(allowed), invented))
    missing = [normalize_link(link) for link in expect.get("must_cite", []) if normalize_link(link) not in cited]
    if missing:
        failures.append(Failure("reply.must_cite", missing, cited))
    words = reply_words(reply)
    if words > expect["word_budget"]:
        failures.append(Failure("reply.word_budget", expect["word_budget"], words))
    return tuple(failures)


__all__ = [
    "CATEGORIES",
    "DECISION_CONTRACT",
    "DECISION_KEYS",
    "ID_PREFIX",
    "SUITE",
    "SUITE_INSTRUCTIONS",
    "evidence_links",
    "grade_orchestration",
    "normalize_owner",
    "normalize_repository",
    "SKILL_RULES",
    "arm_view",
    "harness_evidence_links",
    "prompt_keys",
    "reply_links",
    "reply_words",
    "scenario_errors",
]
