"""Human words for the internal names a coding briefing puts on screen.

A briefing used to print its own state-machine vocabulary at the reader:
``workspace_isolation``, ``executor_result``, ``merge_ready``. Those are step
ids, chosen to be stable keys, and a key is not a sentence. This module is the
one place that says what each of them is called in each language OMH renders.

Two locale sets exist in this repository and they are not the same size.
``LANGUAGE_CODES`` in ``src/commands/language.py`` is what ``--language`` and
``OMH_LANG`` accept -- four codes, and ``normalize_language`` raises on
anything else. ``SUPPORTED_COPY_LOCALES`` in ``src/wrapper/localized_copy.py``
is the chat-copy set, seven, resolved from the message itself rather than from
a flag. These tables are filled for the wider set, so the CLI surfaces keep
working on the four they can be given and the chat surfaces already have the
other three. ``tests/test_briefing_vocabulary.py`` pins the containment in that
direction, so a table that answers fewer languages than a caller can ask for
fails rather than silently falling back to English in production.

Every entry carries every locale. A partially translated row is worse than an
untranslated one: it reads as a bug in the sentence around it, and it hides
which language actually lacks the word.
"""

from __future__ import annotations

from typing import Final, Mapping

BRIEFING_VOCABULARY_LOCALES: Final[tuple[str, ...]] = ("en", "ko", "ja", "zh", "es", "fr", "de")

DEFAULT_LOCALE: Final[str] = "en"

# The ten steps `_progress_steps` returns, in ladder order. The keys are the
# step ids exactly as the briefing payload spells them, plus the one blocker id
# that is not a ladder step.
STEP_LABELS: Final[Mapping[str, Mapping[str, str]]] = {
    "plan": {
        "en": "plan", "ko": "계획", "ja": "計画", "zh": "计划",
        "es": "plan", "fr": "plan", "de": "Plan",
    },
    "handoff": {
        "en": "handoff", "ko": "작업 인계", "ja": "引き継ぎ", "zh": "任务交接",
        "es": "traspaso", "fr": "transmission", "de": "Übergabe",
    },
    "workspace_isolation": {
        "en": "workspace isolation", "ko": "작업 폴더 분리", "ja": "作業フォルダの分離", "zh": "工作目录隔离",
        "es": "aislamiento del espacio de trabajo", "fr": "isolation de l'espace de travail",
        "de": "Arbeitsbereich-Isolierung",
    },
    "dispatch": {
        "en": "dispatch", "ko": "작업 지시", "ja": "作業の発行", "zh": "任务下发",
        "es": "envío", "fr": "envoi", "de": "Beauftragung",
    },
    "executor_result": {
        "en": "executor result", "ko": "실행 결과", "ja": "実行結果", "zh": "执行结果",
        "es": "resultado del ejecutor", "fr": "résultat de l'exécuteur", "de": "Ausführungsergebnis",
    },
    "verification": {
        "en": "verification", "ko": "검증", "ja": "検証", "zh": "验证",
        "es": "verificación", "fr": "vérification", "de": "Verifikation",
    },
    "review": {
        "en": "review", "ko": "리뷰", "ja": "レビュー", "zh": "评审",
        "es": "revisión", "fr": "revue", "de": "Review",
    },
    "ci": {
        "en": "CI", "ko": "CI", "ja": "CI", "zh": "CI",
        "es": "CI", "fr": "CI", "de": "CI",
    },
    "merge_ready": {
        "en": "merge readiness", "ko": "머지 준비", "ja": "マージ準備", "zh": "合并就绪",
        "es": "preparación para la fusión", "fr": "prêt à fusionner", "de": "Merge-Bereitschaft",
    },
    "merged": {
        "en": "merged", "ko": "머지 완료", "ja": "マージ済み", "zh": "已合并",
        "es": "fusionado", "fr": "fusionné", "de": "gemergt",
    },
    "executor_session_error": {
        "en": "executor session error", "ko": "실행 세션 오류", "ja": "実行セッションのエラー", "zh": "执行会话错误",
        "es": "error de sesión del ejecutor", "fr": "erreur de session d'exécuteur",
        "de": "Fehler der Ausführungssitzung",
    },
}

# What stopped a step, from `blockers[].kind`. Distinct words on purpose: a
# reader decides whether to act from this one, and "failed" and "cancelled"
# call for different actions.
BLOCKER_KIND_LABELS: Final[Mapping[str, Mapping[str, str]]] = {
    "failed": {
        "en": "failed", "ko": "실패", "ja": "失敗", "zh": "失败",
        "es": "falló", "fr": "échec", "de": "fehlgeschlagen",
    },
    "blocked": {
        "en": "blocked", "ko": "차단됨", "ja": "ブロック", "zh": "被阻塞",
        "es": "bloqueado", "fr": "bloqué", "de": "blockiert",
    },
    "cancelled": {
        "en": "cancelled", "ko": "취소됨", "ja": "キャンセル", "zh": "已取消",
        "es": "cancelado", "fr": "annulé", "de": "abgebrochen",
    },
}


# Format strings for `omh coding status-board`. They were an `if korean:` pair
# inside the renderer, which is why five of the seven locales could never be
# rendered no matter what a caller passed. Placeholders are named, not
# positional, because the clause order differs between languages.
STATUS_BOARD_COPY: Final[Mapping[str, Mapping[str, str]]] = {
    "header": {
        "en": "Coding status board ({moving} running{stuck} of {total} observed) — observed at {observed_at}",
        "ko": "코딩 작업 현황 (실행 중 {moving}{stuck} / 전체 {total}) — 관측 시각 {observed_at}",
        "ja": "コーディング作業の状況 (実行中 {moving}{stuck} / 全 {total}) — 観測時刻 {observed_at}",
        "zh": "编码作业看板 (运行中 {moving}{stuck} / 共 {total}) — 观测时间 {observed_at}",
        "es": "Panel de trabajo de código ({moving} en curso{stuck} de {total} observados) — observado a las {observed_at}",
        "fr": "Tableau des travaux de code ({moving} en cours{stuck} sur {total} observés) — observé à {observed_at}",
        "de": "Coding-Statusboard ({moving} laufend{stuck} von {total} beobachtet) — beobachtet um {observed_at}",
    },
    "header_stuck_suffix": {
        "en": ", {stuck} stuck", "ko": ", 멈춤 {stuck}", "ja": ", 停止 {stuck}", "zh": ", 停滞 {stuck}",
        "es": ", {stuck} atascados", "fr": ", {stuck} bloqués", "de": ", {stuck} hängend",
    },
    "empty": {
        "en": "No coding work observed.",
        "ko": "관측된 코딩 작업이 없습니다.",
        "ja": "観測されたコーディング作業はありません。",
        "zh": "未观测到编码作业。",
        "es": "No se observó trabajo de código.",
        "fr": "Aucun travail de code observé.",
        "de": "Keine Coding-Arbeit beobachtet.",
    },
    "truncation": {
        "en": "Showing {shown} of {total} units; {dropped} not shown because of the display limit.",
        # The Korean line carried `shown` and `dropped` but never `total`, so a
        # reader had to add the two to learn how much work there was. Every
        # other locale states it; this one now does too.
        "ko": "전체 {total}개 중 {shown}개만 표시했습니다. {dropped}개는 표시 한도로 생략되었습니다.",
        "ja": "{total} 件のうち {shown} 件を表示しています。{dropped} 件は表示上限により省略しました。",
        "zh": "共 {total} 项，显示 {shown} 项；{dropped} 项因显示上限未列出。",
        "es": "Mostrando {shown} de {total} unidades; {dropped} no se muestran por el límite de visualización.",
        "fr": "Affichage de {shown} sur {total} unités ; {dropped} non affichées en raison de la limite d'affichage.",
        "de": "{shown} von {total} Einheiten angezeigt; {dropped} wegen des Anzeigelimits nicht gezeigt.",
    },
}


def status_board_copy(key: str, *, locale: str = DEFAULT_LOCALE) -> str:
    return _lookup(STATUS_BOARD_COPY, key, locale)


def step_label(step_id: str, *, locale: str = DEFAULT_LOCALE) -> str:
    """The human name for a step id, or the id itself when it has no entry.

    Falling back to the id keeps a briefing readable rather than raising inside
    a render, but it is not the safety net: `tests/test_briefing_vocabulary.py`
    asserts that every id `_progress_steps` can produce has a row here, so an
    unlabelled id fails in CI instead of reaching a reader.
    """
    return _lookup(STEP_LABELS, step_id, locale)


def blocker_kind_label(kind: str, *, locale: str = DEFAULT_LOCALE) -> str:
    return _lookup(BLOCKER_KIND_LABELS, kind, locale)


def _lookup(table: Mapping[str, Mapping[str, str]], key: str, locale: str) -> str:
    row = table.get(str(key))
    if not row:
        return str(key)
    return row.get(_normalized(locale)) or row[DEFAULT_LOCALE]


def _normalized(locale: str) -> str:
    """Accept the spellings both locale sets use, without importing either.

    `normalize_language` raises on an unknown value because a flag typo should
    be refused. A render is the wrong place to raise, so this maps what it can
    and lets `_lookup` fall back to English for the rest.
    """
    token = str(locale or "").strip().lower().replace("-", "_")
    base = token.split("_", 1)[0]
    return base if base in BRIEFING_VOCABULARY_LOCALES else DEFAULT_LOCALE
