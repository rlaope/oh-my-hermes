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


# The runtime observation ladder, a different set from `STEP_LABELS`: those are
# briefing progress steps, these are the event types a Hermes coding path
# records. They overlap without matching, so they get their own table rather
# than one merged table with entries that only some callers may use.
RUNTIME_EVENT_LABELS: Final[Mapping[str, Mapping[str, str]]] = {
    "runtime_start": {
        "en": "runtime start", "ko": "런타임 시작", "ja": "ランタイム開始", "zh": "运行时启动",
        "es": "inicio del entorno", "fr": "démarrage du runtime", "de": "Runtime-Start",
    },
    "worktree_creation": {
        "en": "worktree creation", "ko": "작업 폴더 생성", "ja": "作業フォルダの作成", "zh": "工作目录创建",
        "es": "creación del worktree", "fr": "création du worktree", "de": "Worktree-Erstellung",
    },
    "worker_dispatch": {
        "en": "worker dispatch", "ko": "작업자 배정", "ja": "ワーカーの割り当て", "zh": "工作单元下发",
        "es": "envío del worker", "fr": "envoi du worker", "de": "Worker-Beauftragung",
    },
    "worker_result": {
        "en": "worker result", "ko": "작업자 결과", "ja": "ワーカーの結果", "zh": "工作单元结果",
        "es": "resultado del worker", "fr": "résultat du worker", "de": "Worker-Ergebnis",
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
    "merge_readiness": {
        "en": "merge readiness", "ko": "머지 준비", "ja": "マージ準備", "zh": "合并就绪",
        "es": "preparación para la fusión", "fr": "prêt à fusionner", "de": "Merge-Bereitschaft",
    },
    "merge": {
        "en": "merge", "ko": "머지", "ja": "マージ", "zh": "合并",
        "es": "fusión", "fr": "fusion", "de": "Merge",
    },
}

# The labels that structure a rendered briefing line. Separate from the names
# they introduce: a reader who understands "workspace isolation" still has to
# be told whether it stopped or has simply not happened.
LINE_LABELS: Final[Mapping[str, Mapping[str, str]]] = {
    "stopped": {
        "en": "Stopped", "ko": "중단", "ja": "停止", "zh": "已停止",
        "es": "Detenido", "fr": "Arrêté", "de": "Gestoppt",
    },
    "remaining": {
        "en": "Remaining", "ko": "잔여", "ja": "残り", "zh": "剩余",
        "es": "Restante", "fr": "Restant", "de": "Ausstehend",
    },
    "action": {
        "en": "Action", "ko": "조치", "ja": "対応", "zh": "处理",
        "es": "Acción", "fr": "Action", "de": "Aktion",
    },
    "action_none": {
        "en": "none", "ko": "불필요", "ja": "不要", "zh": "无需处理",
        "es": "ninguna", "fr": "aucune", "de": "keine",
    },
    # The team-path line reports the RUNTIME LADDER, which is a different set
    # from the progress steps the `Remaining:` line reports. Without a word
    # naming which one it is, the two lines read as one contradicting itself.
    "team_path": {
        "en": "Hermes team path", "ko": "Hermes 팀 경로", "ja": "Hermes チーム経路", "zh": "Hermes 团队路径",
        "es": "ruta de equipo de Hermes", "fr": "parcours d'équipe Hermes", "de": "Hermes-Teampfad",
    },
    "observations": {
        "en": "observed", "ko": "관측됨", "ja": "観測済み", "zh": "已观测",
        "es": "observado", "fr": "observé", "de": "beobachtet",
    },
}

# What the reader is being asked to do. Keyed by `next_action`, which is an OPEN
# set -- an executor supplies its own, and the runtime composes
# `surface_runtime_failure:ci` from a prefix and an event -- so `action_text`
# splits on the colon and falls back to `unknown`. That fallback is the point:
# an unrecognized token must not reach a chat bubble just because nobody
# enumerated it here, which is what happened to `show_runtime_handoff`.
ACTION_LABELS: Final[Mapping[str, Mapping[str, str]]] = {
    "unknown": {
        "en": "check the current status", "ko": "현재 상태 확인", "ja": "現在の状況を確認",
        "zh": "确认当前状态", "es": "revisar el estado actual", "fr": "vérifier l'état actuel",
        "de": "aktuellen Status prüfen",
    },
    "accept_or_revise_plan": {
        "en": "approve the plan, or ask for changes", "ko": "계획 승인, 또는 수정 요청",
        "ja": "計画を承認、または修正を依頼", "zh": "批准计划，或提出修改",
        "es": "aprobar el plan o pedir cambios", "fr": "approuver le plan ou demander des modifications",
        "de": "Plan freigeben oder Änderungen anfordern",
    },
    "choose_executor": {
        "en": "choose which coding agent runs this", "ko": "어떤 코딩 에이전트가 실행할지 선택",
        "ja": "どのコーディングエージェントが実行するかを選択", "zh": "选择由哪个编码代理执行",
        "es": "elegir qué agente de código lo ejecuta", "fr": "choisir quel agent de code exécute la tâche",
        "de": "wählen, welcher Coding-Agent das ausführt",
    },
    "prepare_handoff": {
        "en": "none — the handoff is being prepared", "ko": "불필요 — 작업 인계 준비 중",
        "ja": "不要 — 引き継ぎを準備中", "zh": "无需处理 — 正在准备任务交接",
        "es": "ninguna — se está preparando el traspaso", "fr": "aucune — la transmission est en préparation",
        "de": "keine — die Übergabe wird vorbereitet",
    },
    "show_prompt_handoff": {
        "en": "approve to start, or adjust the scope", "ko": "시작 승인, 또는 범위 조정",
        "ja": "開始を承認、または範囲を調整", "zh": "批准开始，或调整范围",
        "es": "aprobar el inicio o ajustar el alcance", "fr": "approuver le démarrage ou ajuster le périmètre",
        "de": "Start freigeben oder den Umfang anpassen",
    },
    "show_status": {
        "en": "none", "ko": "불필요", "ja": "不要", "zh": "无需处理",
        "es": "ninguna", "fr": "aucune", "de": "keine",
    },
    "report_completion_with_evidence": {
        "en": "none — the result is being reported", "ko": "불필요 — 결과 보고 중",
        "ja": "不要 — 結果を報告中", "zh": "无需处理 — 正在报告结果",
        "es": "ninguna — se está informando el resultado", "fr": "aucune — le résultat est en cours de rapport",
        "de": "keine — das Ergebnis wird berichtet",
    },
    # Runtime-composed prefixes. The event after the colon is named separately
    # through `RUNTIME_EVENT_LABELS`, so these read as a sentence with a blank.
    "surface_runtime_failure": {
        "en": "look at the failure on {event}", "ko": "{event}에서 난 실패 확인",
        "ja": "{event} の失敗を確認", "zh": "查看 {event} 的失败",
        "es": "revisar el fallo en {event}", "fr": "examiner l'échec sur {event}",
        "de": "den Fehler bei {event} ansehen",
    },
    "surface_runtime_blocker": {
        "en": "clear the blocker on {event}", "ko": "{event} 차단 해제",
        "ja": "{event} のブロックを解除", "zh": "解除 {event} 的阻塞",
        "es": "desbloquear {event}", "fr": "débloquer {event}",
        "de": "die Blockade bei {event} auflösen",
    },
    "surface_runtime_cancellation": {
        "en": "restart {event}, or drop it", "ko": "{event} 재시작, 또는 중단 확정",
        "ja": "{event} を再実行、または取りやめ", "zh": "重启 {event}，或放弃",
        "es": "reiniciar {event} o descartarlo", "fr": "relancer {event} ou l'abandonner",
        "de": "{event} neu starten oder verwerfen",
    },
    "record_runtime_observation": {
        "en": "none — waiting on {event}", "ko": "불필요 — {event} 대기 중",
        "ja": "不要 — {event} を待機中", "zh": "无需处理 — 等待 {event}",
        "es": "ninguna — a la espera de {event}", "fr": "aucune — en attente de {event}",
        "de": "keine — wartet auf {event}",
    },
    "report_runtime_observed": {
        "en": "none", "ko": "불필요", "ja": "不要", "zh": "无需处理",
        "es": "ninguna", "fr": "aucune", "de": "keine",
    },
}

# `show_runtime_handoff` means the same thing to a reader as its prompt-only
# twin; both say "a handoff is ready and nobody has started it". One entry with
# an alias rather than two rows that must be kept in step.
_ACTION_ALIASES: Final[Mapping[str, str]] = {"show_runtime_handoff": "show_prompt_handoff"}


def status_board_copy(key: str, *, locale: str = DEFAULT_LOCALE) -> str:
    return _lookup(STATUS_BOARD_COPY, key, locale)


def line_label(key: str, *, locale: str = DEFAULT_LOCALE) -> str:
    return _lookup(LINE_LABELS, key, locale)


def runtime_event_label(event_type: str, *, locale: str = DEFAULT_LOCALE) -> str:
    return _lookup(RUNTIME_EVENT_LABELS, event_type, locale)


def action_text(next_action: str, *, locale: str = DEFAULT_LOCALE) -> str:
    """What the reader should do, in words, for an open set of action tokens.

    `next_action` is composed by three different producers and one of them
    joins a prefix to an event with a colon, so this resolves the whole token
    first, then the prefix, then gives up and says to check the status. It never
    returns the token: printing `show_runtime_handoff` at a reader is the defect
    this exists to close, and doing it only for unrecognized values would make
    the defect rarer and harder to notice rather than fixing it.
    """
    token = str(next_action or "").strip()
    resolved = _ACTION_ALIASES.get(token, token)
    if resolved in ACTION_LABELS:
        return _lookup(ACTION_LABELS, resolved, locale)
    prefix, _, event = resolved.partition(":")
    if prefix in ACTION_LABELS:
        return _lookup(ACTION_LABELS, prefix, locale).format(event=runtime_event_label(event, locale=locale))
    return _lookup(ACTION_LABELS, "unknown", locale)


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
