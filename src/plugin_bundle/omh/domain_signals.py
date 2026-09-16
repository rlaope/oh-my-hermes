from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata


@dataclass(frozen=True)
class DomainRouteSignal:
    skill: str
    matched_cues: tuple[str, ...]


@dataclass(frozen=True)
class DomainOperatorOverride:
    skill: str
    matched_cues: tuple[str, ...]


SPECIALIST_DOMAIN_TRIGGERS: dict[str, tuple[str, ...]] = {
    "finance-analysis": (
        "finance analysis",
        "budget variance",
        "budget vs actual",
        "month-end close",
        "재무 분석",
        "예산 대비 실적",
        "월마감",
    ),
    "people-ops": (
        "recruiting plan",
        "hiring scorecard",
        "interview scorecard",
        "candidate debrief",
        "채용 계획",
        "면접 평가표",
        "후보자 비교",
    ),
    "legal-compliance-review": (
        "contract review",
        "contract liability clause",
        "regulatory analysis",
        "compliance review",
        "contract redline",
        "redline the contract",
        "negotiation preparation",
        "negotiation strategy",
        "clause language",
        "counterparty position",
        "계약서 검토",
        "규제 분석",
        "컴플라이언스 검토",
    ),
    "support-operations": (
        "support escalation",
        "customer support reply",
        "ticket triage",
        "고객 지원 에스컬레이션",
        "고객 답변 초안",
        "지원 티켓 분류",
    ),
    "curriculum-design": (
        "curriculum design",
        "learning objectives",
        "assessment plan",
        "커리큘럼 설계",
        "학습 목표",
        "평가 계획",
    ),
    "localization-review": (
        "localization review",
        "translation QA",
        "locale glossary",
        "현지화 검토",
        "번역 QA",
        "용어집",
    ),
    "sales-development": (
        "sales discovery",
        "account plan",
        "outbound messaging",
        "영업 발굴",
        "고객사 계획",
        "아웃바운드 메시지",
    ),
    "decision-prototype": (
        "prototype before planning",
        "run a small spike",
        "test the risky assumption",
    ),
    "lifecycle-growth": (
        "lifecycle growth",
        "lifecycle marketing",
        "onboarding journey",
        "growth experiment",
    ),
    "product-discovery-validation": (
        "product discovery validation",
        "product discovery",
        "customer discovery",
        "kill pivot persevere",
        "is this idea worth building",
    ),
    "sales-pipeline-review": (
        "pipeline review",
        "pipeline health",
        "forecast calibration",
        "deal review",
        "stale deals",
    ),
    "product-brief": (
        "product requirements document",
        "PRD",
        "roadmap prioritization",
        "제품 요구사항 문서",
        "제품 기획서",
        "로드맵 우선순위",
    ),
}

_DOMAIN_ROUTE_CUE_GROUPS: tuple[tuple[str, tuple[tuple[str, ...], ...]], ...] = (
    ("finance-analysis", (("actuals", "budget"), ("실적", "예산"))),
    ("people-ops", (("interview scorecard", "debrief"), ("면접 평가표", "디브리핑"))),
    ("legal-compliance-review", (("dpa", "data-processing"), ("계약서", "개인정보 처리"))),
    ("support-operations", (("customer", "engineering escalation"), ("로그인 장애", "에스컬레이션"))),
    ("curriculum-design", (("curriculum", "learning objectives"), ("커리큘럼", "학습 목표"))),
    ("localization-review", (("terminology consistency", "cultural fit"), ("한국어 결제", "현지화"))),
    ("sales-development", (("discovery plan", "qualification questions"), ("미드마켓", "발견 질문"))),
    ("lifecycle-growth", (("activation", "consent"),)),
    ("product-discovery-validation", (("customer problem", "write a prd"),)),
    ("sales-pipeline-review", (("pipeline", "slipped deals"),)),
    ("product-brief", (("prd", "prioritization"), ("prd", "로드맵 우선순위"))),
)

_DOMAIN_OPERATOR_CUES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "external-connector-readiness",
        (
            "use these api credentials",
            "with api credentials",
            "configure credentials",
            "use this oauth token",
            "use this api key",
        ),
    ),
    (
        "memory-sync",
        ("clean up hermes memory", "memory cleanup", "clean up memory", "sync memory", "메모리 정리"),
    ),
    (
        "ultrawork",
        ("implement", "translate into code", "open a pr", "pull request", "구현", "코드로", "pr 열"),
    ),
    (
        "automation-blueprint",
        (
            "schedule this",
            "recurring send",
            "recurring update",
            "every monday",
            "every week",
            "cron",
            "예약 실행",
            "정기 전송",
            "매주 보내",
        ),
    ),
    (
        "browser-operator",
        (
            "open the customer portal",
            "open in the browser",
            "use the browser",
            "click refund",
            "click submit",
            "submit the form",
            "포털에서 열",
            "클릭해",
        ),
    ),
    (
        "workspace-file-operator",
        ("save this", "write this to", "edit the locale file", "update the locale file", "파일에 저장", "파일로 저장"),
    ),
    (
        "security-safety-review",
        ("audit oauth", "secret risk", "permission risk", "권한 위험", "비밀키 위험"),
    ),
    (
        "live-info-operator",
        ("right now", "current quote", "exchange rate", "live price", "현재 시세", "환율"),
    ),
    (
        "feedback-triage",
        ("cluster these", "cluster ticket", "cluster support backlog", "피드백 군집", "티켓 묶"),
    ),
    (
        "reliability-review",
        ("active incident", "incident review", "postmortem", "장애 회고"),
    ),
    (
        "materials-package",
        ("export this curriculum", "create a deck", "create a workbook", "export to pdf", "학습 자료로 내보"),
    ),
    (
        "visual-qa",
        ("rendered ui", "clipping check", "visual qa", "화면 잘림", "렌더링 검증"),
    ),
    (
        "content-operator",
        (
            "write a linkedin post",
            "write a social post",
            "write a newsletter",
            "rewrite this job ad",
            "rewrite this rejection email",
            "rewrite this interview email",
            "rewrite this marketing email",
            "rewrite this sentence",
            "rewrite this worksheet prompt",
            "plain-language rewrite",
        ),
    ),
    (
        "connector-operator",
        (
            "update crm",
            "update the crm",
            "create crm",
            "update salesforce",
            "update hubspot",
            "create a hubspot opportunity",
            "create opportunity",
            "approve payment",
            "post journal",
            "reconcile account",
            "reconcile accounts",
            "submit tax filing",
            "configure accounting",
            "sign this",
            "sign contract",
            "accept contract",
            "submit this",
            "submit filing",
            "file with",
            "publish policy",
            "change policy",
            "change contract",
            "email this",
            "send email",
            "send reply",
            "issue a refund",
            "change ticket priority",
            "change ticket status",
            "modify account",
            "update helpdesk",
            "create an ats record",
            "update our ats",
            "update ats",
            "modify hris",
            "send invitation",
            "book interview",
            "book interviews",
            "publish an lms course",
            "create an lms course",
            "enroll student",
            "enroll students",
            "grade work",
            "change course setting",
            "push a tms",
            "publish string",
            "publish strings",
            "configure localization",
            "send outreach",
            "book a meeting",
            "create jira",
            "update jira",
            "create linear",
            "update linear",
            "create an aha",
            "update aha",
            "roadmap system directly",
            "to the regulator",
            "결제 승인",
            "제출",
            "이메일",
            "환불",
            "전송",
        ),
    ),
)

_NON_EXECUTING_ACTION_CUES = (
    "do not",
    "don't",
    "draft only",
    "review only",
    "analysis only",
    "without sending",
    "without submitting",
    "without approving",
    "no external action",
    "보내지 마",
    "제출하지 마",
    "승인하지 마",
    "실행하지 마",
)

_NEGATION_SENSITIVE_OPERATOR_SKILLS = {
    "automation-blueprint",
    "browser-operator",
    "connector-operator",
    "ultrawork",
    "workspace-file-operator",
}

_DOMAIN_NEGATORS = frozenset(
    {"avoid", "except", "exclude", "excluded", "excluding", "never", "no", "not", "without"}
)
_INCLUSIVE_NEGATION_FOLLOWERS = frozenset({"just", "only"})
_LOCAL_NEGATION_TOKEN_RANGE = 4
_CLAUSE_SEPARATOR_PATTERN = re.compile(r"[,;.!?\n]+|\band\b")
_ENGLISH_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
_PROSE_ONLY_DOMAIN_REFERENCE_PATTERN = re.compile(
    r"^(?:say|call|term|phrase|use)\s+.+?\s*,?\s+not\s+",
)


def _is_prose_only_domain_reference(message: str) -> bool:
    """Keep terminology contrast prose out of specialist dispatch lanes."""
    return _PROSE_ONLY_DOMAIN_REFERENCE_PATTERN.search(_fold_for_match(message).strip()) is not None


_STRUCTURED_OPERATOR_ACTIONS: tuple[
    tuple[str, dict[str, tuple[str, ...]]],
    ...,
] = (
    (
        "workspace-file-operator",
        {
            "edit": ("locale file",),
            "save": ("brief", "file", "prd"),
            "write": ("file",),
        },
    ),
    (
        "content-operator",
        {
            "rewrite": (
                "interview email",
                "job ad",
                "marketing email",
                "plain language",
                "rejection email",
                "sentence",
                "worksheet prompt",
            ),
            "write": (
                "interview email",
                "job ad",
                "linkedin post",
                "marketing email",
                "newsletter",
                "rejection email",
                "social post",
                "worksheet prompt",
            ),
        },
    ),
    (
        "connector-operator",
        {
            "accept": ("contract", "dpa"),
            "approve": ("payment",),
            "book": ("interview", "meeting"),
            "change": (
                "contract",
                "course setting",
                "employment status",
                "policy",
                "ticket priority",
                "ticket status",
            ),
            "configure": ("accounting", "course setting", "localization"),
            "create": (
                "aha item",
                "ats record",
                "hubspot opportunity",
                "jira item",
                "linear issue",
                "lms course",
                "opportunity",
            ),
            "enroll": ("student",),
            "file": ("contract", "dpa", "filing", "tax"),
            "grade": ("work",),
            "issue": ("refund",),
            "modify": ("account", "hris"),
            "post": ("journal entry",),
            "publish": ("contract", "lms course", "policy", "string"),
            "push": ("tms job", "translation"),
            "reconcile": ("account",),
            "send": ("email", "invitation", "outreach", "reply"),
            "sign": ("contract", "dpa"),
            "submit": ("contract", "filing", "tax"),
            "update": (
                "aha",
                "ats",
                "crm",
                "helpdesk",
                "hris",
                "hubspot",
                "jira",
                "linear",
                "roadmap system",
                "salesforce",
                "ticket",
            ),
            "upload": ("translation",),
        },
    ),
)

def canonical_domain_token(token: str) -> str:
    """Project English n't contractions onto the canonical `not` token."""
    normalized = token.replace("’", "'")
    if re.fullmatch(r"[a-z]+n't", normalized):
        return "not"
    return normalized


def canonical_domain_tokens(value: str) -> tuple[str, ...]:
    """Return canonical English tokens for shared local-negation consumers."""
    return tuple(
        canonical_domain_token(token)
        for token in re.findall(r"[a-z]+n['’]t|[a-z0-9]+", value)
    )


def domain_tokens_are_locally_negated(tokens: tuple[str, ...], start: int) -> bool:
    """Apply the one canonical domain-negation window to a token position."""
    lower = max(0, start - _LOCAL_NEGATION_TOKEN_RANGE)
    for index in range(lower, start):
        if tokens[index] not in _DOMAIN_NEGATORS:
            continue
        if (
            tokens[index] == "not"
            and index + 1 < len(tokens)
            and tokens[index + 1] in _INCLUSIVE_NEGATION_FOLLOWERS
        ):
            continue
        return True
    return False


def normalized_domain_cue_is_positive(
    normalized_message: str,
    cue_pattern: re.Pattern[str],
) -> bool:
    """Apply canonical local-negation semantics to an already-folded request."""
    for clause in _CLAUSE_SEPARATOR_PATTERN.split(normalized_message):
        tokens = canonical_domain_tokens(clause)
        for match in cue_pattern.finditer(clause):
            start = len(canonical_domain_tokens(clause[: match.start()]))
            if not domain_tokens_are_locally_negated(tokens, start):
                return True
    return False


def specialist_domain_route_signal(message: str) -> DomainRouteSignal | None:
    """Return one catalog-domain cue pair without retaining the raw prompt."""
    signals = specialist_domain_route_signals(message)
    return signals[0] if signals else None


def specialist_domain_route_signals(message: str) -> tuple[DomainRouteSignal, ...]:
    """Return every positive catalog-domain signal in declaration order."""
    if _is_prose_only_domain_reference(message):
        return ()
    matched_by_skill: dict[str, list[str]] = {}
    for skill, triggers in SPECIALIST_DOMAIN_TRIGGERS.items():
        matched = tuple(trigger for trigger in triggers if _contains_positive_cue_phrase(message, trigger))
        if matched:
            matched_by_skill.setdefault(skill, []).extend(matched)
    for skill, cue_groups in _DOMAIN_ROUTE_CUE_GROUPS:
        for cues in cue_groups:
            if all(_contains_positive_cue_phrase(message, cue) for cue in cues):
                matched_by_skill.setdefault(skill, []).extend(cues)
    if "product-discovery-validation" in matched_by_skill:
        matched_by_skill.pop("product-brief", None)
    return tuple(
        DomainRouteSignal(skill=skill, matched_cues=tuple(dict.fromkeys(cues)))
        for skill, cues in matched_by_skill.items()
    )


def excluded_specialist_domain_skills(message: str) -> frozenset[str]:
    """Return domain skills whose only matching cues are locally negated."""
    positive_skills = {signal.skill for signal in specialist_domain_route_signals(message)}
    matched_skills = {
        skill
        for skill, triggers in SPECIALIST_DOMAIN_TRIGGERS.items()
        if any(_contains_cue_phrase(message, trigger) for trigger in triggers)
    }
    matched_skills.update(
        skill
        for skill, cue_groups in _DOMAIN_ROUTE_CUE_GROUPS
        if any(all(_contains_cue_phrase(message, cue) for cue in cues) for cues in cue_groups)
    )
    if _is_prose_only_domain_reference(message):
        return frozenset(matched_skills)
    return frozenset(matched_skills - positive_skills)


def specialist_domain_operator_override(
    message: str,
    signal: DomainRouteSignal | None = None,
) -> DomainOperatorOverride | None:
    """Return the narrow operator that owns an action-bearing domain request."""
    if signal is None:
        signal = specialist_domain_route_signal(message)
    if signal is None:
        return None
    non_executing = any(_contains_cue_phrase(message, cue) for cue in _NON_EXECUTING_ACTION_CUES)
    for skill, cues in _DOMAIN_OPERATOR_CUES:
        matched = tuple(cue for cue in cues if _contains_cue_phrase(message, cue))
        if matched and not (non_executing and skill in _NEGATION_SENSITIVE_OPERATOR_SKILLS):
            return DomainOperatorOverride(skill=skill, matched_cues=matched)
    if not non_executing:
        tokens = _word_tokens(message)
        for skill, actions in _STRUCTURED_OPERATOR_ACTIONS:
            for verb, objects in actions.items():
                if verb not in tokens:
                    continue
                for object_phrase in objects:
                    if _word_tokens(object_phrase) <= tokens:
                        return DomainOperatorOverride(
                            skill=skill,
                            matched_cues=(f"{verb} {object_phrase}",),
                        )
    return None


def _contains_cue_phrase(message: str, cue: str) -> bool:
    text = _fold_for_match(message)
    phrase = _fold_for_match(cue)
    if re.fullmatch(r"[a-z0-9 '’]+", phrase):
        pattern = re.escape(phrase).replace(r"\ ", r"[\s_-]+")
        return re.search(rf"(?<![a-z0-9]){pattern}(?![a-z0-9])", text) is not None
    return phrase in text or _compact(phrase) in _compact(text)


def _contains_positive_cue_phrase(message: str, cue: str) -> bool:
    if not _contains_cue_phrase(message, cue):
        return False
    cue_tokens = _english_tokens(cue)
    if not cue_tokens:
        return True
    for clause in _CLAUSE_SEPARATOR_PATTERN.split(_fold_for_match(message)):
        tokens = _english_tokens(clause)
        for start in range(len(tokens) - len(cue_tokens) + 1):
            if tokens[start : start + len(cue_tokens)] != cue_tokens:
                continue
            if not _locally_negated(tokens, start):
                return True
    return False


def _english_tokens(value: str) -> tuple[str, ...]:
    return canonical_domain_tokens(_fold_for_match(value))


def _locally_negated(tokens: tuple[str, ...], start: int) -> bool:
    return domain_tokens_are_locally_negated(tokens, start)


def _fold_for_match(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    decomposed = unicodedata.normalize("NFKD", normalized)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _compact(value: str) -> str:
    return "".join(character for character in value if character.isalnum())


def _word_tokens(value: str) -> set[str]:
    tokens: set[str] = set()
    raw_tokens: list[str] = re.findall(r"[a-z0-9]+", _fold_for_match(value))
    for token in raw_tokens:
        tokens.add(token)
        if token.endswith("ies") and len(token) > 4:
            tokens.add(f"{token[:-3]}y")
        elif token.endswith("es") and len(token) > 4:
            tokens.add(token[:-1])
            tokens.add(token[:-2])
        elif token.endswith("s") and len(token) > 3:
            tokens.add(token[:-1])
    return tokens
