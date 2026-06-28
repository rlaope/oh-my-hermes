from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata


_TOKEN_RE = re.compile(r"[^\W_][^\W_'-]*(?:-[^\W_][^\W_'-]*)?", re.UNICODE)
_STOPWORDS = {
    "the",
    "and",
    "are",
    "as",
    "for",
    "in",
    "is",
    "of",
    "or",
    "to",
    "with",
    "that",
    "this",
    "when",
    "use",
    "user",
    "task",
    "request",
    "workflow",
    "skill",
    "agent",
    "hermes",
}
_CANONICAL_PAYMENT_FAILURE = (
    "payment failure payment failure issue payment failure feedback "
    "customer feedback feedback triage bug reports reproduce"
)
_CANONICAL_RISKY_REFACTOR = (
    "dangerous refactor risky refactor unsafe refactor reviewed plan consensus planning acceptance criteria"
)
_CANONICAL_SAFE_FEATURE = (
    "safely add feature safe feature change reviewed consensus acceptance criteria "
    "risk verification command before executor handoff"
)
_CANONICAL_ISSUE_TO_PR = "issue to pr pr-ready issue plan acceptance criteria coding handoff request-to-handoff"
_CANONICAL_WEB_RESEARCH = (
    "web research web search search the web current sources source-backed research "
    "citations links freshness source diversity retrieval gap"
)


@dataclass(frozen=True)
class LocaleAlias:
    locale: str
    label: str
    phrases: tuple[str, ...]
    canonical: str


@dataclass(frozen=True)
class RoutingText:
    original: str
    scoring_text: str
    locale_matches: tuple[str, ...]


_ALIASES: tuple[LocaleAlias, ...] = (
    LocaleAlias(
        "ja",
        "payment_failure",
        (
            "支払い失敗",
            "支払いエラー",
            "支払いの失敗",
            "決済失敗",
            "決済エラー",
            "決済の失敗",
        ),
        _CANONICAL_PAYMENT_FAILURE,
    ),
    LocaleAlias(
        "zh",
        "payment_failure",
        (
            "支付失败",
            "支付失敗",
            "付款失败",
            "付款失敗",
            "支付错误",
            "支付錯誤",
            "支付故障",
        ),
        _CANONICAL_PAYMENT_FAILURE,
    ),
    LocaleAlias(
        "es",
        "payment_failure",
        ("fallo de pago", "fallos de pago", "problema de pago", "pagos fallan", "error de pago"),
        _CANONICAL_PAYMENT_FAILURE,
    ),
    LocaleAlias(
        "fr",
        "payment_failure",
        (
            "échec de paiement",
            "echec de paiement",
            "problème de paiement",
            "paiement échoue",
            "erreur de paiement",
        ),
        _CANONICAL_PAYMENT_FAILURE,
    ),
    LocaleAlias(
        "de",
        "payment_failure",
        ("zahlungsfehler", "zahlung fehlgeschlagen", "problem mit der zahlung", "zahlungsausfall"),
        _CANONICAL_PAYMENT_FAILURE,
    ),
    LocaleAlias(
        "ja",
        "risky_refactor",
        (
            "危険なリファクタリング",
            "危ないリファクタリング",
            "リファクタリングが危険",
            "リファクタリングは危険",
        ),
        _CANONICAL_RISKY_REFACTOR,
    ),
    LocaleAlias(
        "zh",
        "risky_refactor",
        (
            "危险的重构",
            "危險的重構",
            "重构风险",
            "重構風險",
            "这个重构很危险",
            "這個重構很危險",
        ),
        _CANONICAL_RISKY_REFACTOR,
    ),
    LocaleAlias(
        "es",
        "risky_refactor",
        ("refactorización peligrosa", "refactorizacion peligrosa", "refactorización riesgosa", "refactor inseguro"),
        _CANONICAL_RISKY_REFACTOR,
    ),
    LocaleAlias(
        "fr",
        "risky_refactor",
        ("refactorisation risquée", "refactorisation risquee", "refactorisation dangereuse"),
        _CANONICAL_RISKY_REFACTOR,
    ),
    LocaleAlias(
        "de",
        "risky_refactor",
        ("riskantes refactoring", "gefährliches refactoring", "gefaehrliches refactoring", "riskante refaktorierung"),
        _CANONICAL_RISKY_REFACTOR,
    ),
    LocaleAlias(
        "ko",
        "safe_feature",
        (
            "안전하게 기능 추가",
            "기능 안전하게 추가",
            "기능 추가를 안전하게",
            "새 기능 안전하게 넣",
            "안전하게 새 기능",
        ),
        _CANONICAL_SAFE_FEATURE,
    ),
    LocaleAlias(
        "ja",
        "safe_feature",
        (
            "機能を安全に追加",
            "安全に機能追加",
            "機能追加を安全に",
        ),
        _CANONICAL_SAFE_FEATURE,
    ),
    LocaleAlias(
        "zh",
        "safe_feature",
        (
            "安全地添加功能",
            "安全地新增功能",
            "安全地给这个仓库添加功能",
            "安全地給這個倉庫新增功能",
        ),
        _CANONICAL_SAFE_FEATURE,
    ),
    LocaleAlias(
        "es",
        "safe_feature",
        (
            "añadir una función de forma segura",
            "anadir una funcion de forma segura",
            "agregar una función de forma segura",
            "agregar una funcion de forma segura",
            "añadir una característica de forma segura",
            "anadir una caracteristica de forma segura",
        ),
        _CANONICAL_SAFE_FEATURE,
    ),
    LocaleAlias(
        "fr",
        "safe_feature",
        (
            "ajouter une fonctionnalité en toute sécurité",
            "ajouter une fonctionnalite en toute securite",
            "fonctionnalité en toute sécurité",
            "fonctionnalite en toute securite",
        ),
        _CANONICAL_SAFE_FEATURE,
    ),
    LocaleAlias(
        "de",
        "safe_feature",
        ("sicher eine funktion hinzufügen", "sicher eine funktion hinzufuegen"),
        _CANONICAL_SAFE_FEATURE,
    ),
    LocaleAlias(
        "ja",
        "issue_to_pr",
        ("issueをpr", "issueからpr", "イシューをpr", "prにできるよう", "プルリクにできるよう"),
        _CANONICAL_ISSUE_TO_PR,
    ),
    LocaleAlias(
        "zh",
        "issue_to_pr",
        (
            "issue 变成 pr",
            "issue 變成 pr",
            "把这个 issue 整理成 pr",
            "把這個 issue 整理成 pr",
            "转成 pr",
            "轉成 pr",
        ),
        _CANONICAL_ISSUE_TO_PR,
    ),
    LocaleAlias(
        "es",
        "issue_to_pr",
        ("convertir este issue en un pr", "convertir este issue a pr", "preparar este issue para un pr"),
        _CANONICAL_ISSUE_TO_PR,
    ),
    LocaleAlias(
        "fr",
        "issue_to_pr",
        ("transformer cette issue en pr", "préparer cette issue pour une pr", "preparer cette issue pour une pr"),
        _CANONICAL_ISSUE_TO_PR,
    ),
    LocaleAlias(
        "de",
        "issue_to_pr",
        ("issue in einen pr", "dieses issue für einen pr vorbereiten", "dieses issue fuer einen pr vorbereiten"),
        _CANONICAL_ISSUE_TO_PR,
    ),
    LocaleAlias(
        "ja",
        "web_research",
        (
            "ウェブ検索",
            "web検索",
            "ネット検索",
            "検索して",
            "最新の出典",
            "出典をまとめ",
            "情報源を探",
        ),
        _CANONICAL_WEB_RESEARCH,
    ),
    LocaleAlias(
        "zh",
        "web_research",
        (
            "网页搜索",
            "網頁搜尋",
            "网络搜索",
            "網路搜尋",
            "网上搜索",
            "網上搜尋",
            "查一下",
            "找资料",
            "找資料",
            "最新来源",
            "最新來源",
        ),
        _CANONICAL_WEB_RESEARCH,
    ),
    LocaleAlias(
        "es",
        "web_research",
        (
            "buscar en la web",
            "busca en la web",
            "investigar en internet",
            "fuentes actuales",
            "fuentes recientes",
            "citas actuales",
        ),
        _CANONICAL_WEB_RESEARCH,
    ),
    LocaleAlias(
        "fr",
        "web_research",
        (
            "rechercher sur le web",
            "cherche sur le web",
            "recherche internet",
            "sources actuelles",
            "sources recentes",
            "sources récentes",
        ),
        _CANONICAL_WEB_RESEARCH,
    ),
    LocaleAlias(
        "de",
        "web_research",
        (
            "im web suchen",
            "websuche",
            "internetrecherche",
            "aktuelle quellen",
            "neueste quellen",
        ),
        _CANONICAL_WEB_RESEARCH,
    ),
)


def locale_aliases() -> tuple[LocaleAlias, ...]:
    return _ALIASES


def prepare_routing_text(value: str) -> RoutingText:
    original = value.strip()
    folded = _fold_for_match(original)
    additions: list[str] = []
    matches: list[str] = []
    for alias in _ALIASES:
        if any(_fold_for_match(phrase) in folded for phrase in alias.phrases):
            additions.append(alias.canonical)
            matches.append(f"{alias.locale}:{alias.label}")
    scoring_text = " ".join((original, *additions)).strip()
    return RoutingText(original=original, scoring_text=scoring_text, locale_matches=tuple(sorted(set(matches))))


def routing_tokens(value: str, *, stopwords: set[str] | None = None) -> set[str]:
    stopwords = _STOPWORDS if stopwords is None else stopwords
    tokens: set[str] = set()
    for raw_token in routing_terms(value):
        for token in (raw_token, *raw_token.split("-")):
            if len(token) >= 3 and token not in stopwords:
                tokens.add(token)
    return tokens


def routing_terms(value: str) -> set[str]:
    folded = _fold_for_match(value)
    terms: set[str] = set()
    for raw_token in _TOKEN_RE.findall(folded):
        token = raw_token.strip("-")
        if token:
            terms.add(token)
            terms.update(part for part in token.split("-") if part)
    return terms


def normalized_phrase(value: str) -> str:
    return _fold_for_match(value)


def _fold_for_match(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    decomposed = unicodedata.normalize("NFKD", normalized)
    return "".join(char for char in decomposed if not unicodedata.combining(char))
