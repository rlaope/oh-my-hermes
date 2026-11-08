from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Mapping


SUPPORTED_COPY_LOCALES = ("en", "ko", "ja", "zh", "es", "fr", "de")


@dataclass(frozen=True)
class ChatCopy:
    headline: str
    body: str


def detect_copy_locale(message: str) -> str:
    """Return the best local chat-copy locale without external translation."""
    if any("\uac00" <= char <= "\ud7a3" for char in message):
        return "ko"
    if any("\u3040" <= char <= "\u30ff" for char in message):
        return "ja"
    if any("\u4e00" <= char <= "\u9fff" for char in message):
        return "zh"

    normalized = f" {message.lower()} "
    if any(hint in normalized for hint in ("¿", "¡", " qué ", " quiero ", " necesito ", " puedes ", " fallo ", " resumen ")):
        return "es"
    if any(
        hint in normalized
        for hint in (" quelle ", " quelles ", " peux-tu ", " je veux ", " trouve ", " explique ", " recherche ", " dépôt ", " résumé ")
    ):
        return "fr"
    if any(hint in normalized for hint in (" welche ", " kannst du ", " bitte ", " zusammenfassung ", " fehler ", " arbeitsablauf ")):
        return "de"
    return "en"


def prefers_korean_copy(message: str) -> bool:
    return detect_copy_locale(message) == "ko"


def is_localized_locale(locale: str) -> bool:
    return _normalize_locale(locale) != "en"


def _normalize_locale(locale: str | None, *, korean: bool | None = None) -> str:
    if korean is not None:
        return "ko" if korean else "en"
    if locale in SUPPORTED_COPY_LOCALES:
        return str(locale)
    return "en"


# Every headline and body here is rendered verbatim into a chat card, so each
# one says what the card holds, what it leaves out, and what the reader can do
# next. Two shapes are kept out on purpose: a first-person voice, which puts a
# second persona next to the host's `SOUL.md`, and OMH's record vocabulary,
# which belongs in records and tool calls rather than in a sentence a person
# reads. `card_copy_voice_violations` below re-derives both from this table.
_CARD_COPY: dict[str, dict[str, ChatCopy]] = {
    "img_summary": {
        "en": ChatCopy(
            headline="This content can become a shareable image card.",
            body=(
                "The shareable image-card brief covers audience, layout, on-image copy, generation prompt, "
                "negative prompt, and a quick QA checklist. It does not contain a generated image. "
                "If no image tool is connected, the card asks which tool to use instead of claiming an image exists."
            ),
        ),
        "ko": ChatCopy(
            headline="이 내용은 공유용 이미지 카드로 만들 수 있습니다.",
            body=(
                "카드 초안은 대상 독자, 레이아웃, 이미지 안 문구, 생성 프롬프트, 네거티브 프롬프트, "
                "간단한 QA 점검을 담습니다. 생성된 이미지는 담지 않습니다. 연결된 이미지 생성 도구가 없으면 "
                "이미지가 있다고 말하는 대신 어떤 도구를 쓸지 먼저 묻습니다."
            ),
        ),
        "ja": ChatCopy(
            headline="この内容は共有用の画像カードにできます。",
            body=(
                "画像カード向けの image-card brief は対象読者、レイアウト、画像内コピー、生成プロンプト、ネガティブプロンプト、"
                "簡単なQA点検をまとめます。生成済みの画像は含みません。画像ツールが未接続なら、画像があるとは言わず、"
                "どのツールを使うか先に尋ねます。"
            ),
        ),
        "zh": ChatCopy(
            headline="这段内容可以做成可分享的图片卡片。",
            body=(
                "image-card brief 包含受众、版式、图片内文案、生成提示词、负面提示词和快速 QA 清单。"
                "其中不含已生成的图片。若未连接图片工具，卡片会先询问要用哪个工具，而不会说图片已经存在。"
            ),
        ),
        "es": ChatCopy(
            headline="Este contenido puede convertirse en una tarjeta visual compartible.",
            body=(
                "El image-card brief cubre audiencia, layout, texto dentro de la imagen, prompt de generación, "
                "negative prompt y un QA rápido. No contiene una imagen generada. Sin herramienta de imagen conectada, "
                "la tarjeta pregunta cuál usar en vez de dar la imagen por hecha."
            ),
        ),
        "fr": ChatCopy(
            headline="Ce contenu peut devenir une carte image partageable.",
            body=(
                "L'image-card brief couvre l'audience, la mise en page, le texte dans l'image, le prompt de génération, "
                "le negative prompt et un QA rapide. Il ne contient pas d'image générée. Sans outil image connecté, "
                "la carte demande lequel utiliser au lieu de présenter l'image comme existante."
            ),
        ),
        "de": ChatCopy(
            headline="Dieser Inhalt kann eine teilbare Bildkarte werden.",
            body=(
                "Das image-card brief umfasst Zielgruppe, Layout, Text im Bild, Generierungs-Prompt, Negative Prompt "
                "und eine kurze QA-Prüfung. Ein erzeugtes Bild enthält es nicht. Ohne verbundenes Bildtool fragt die "
                "Karte zuerst nach dem Tool, statt ein Bild als vorhanden auszugeben."
            ),
        ),
    },
    "paper_learning": {
        "en": ChatCopy(
            headline="This paper can be explained at the depth you choose.",
            body=(
                "The paper-learning card sets the explanation level, the source or PDF state, section coverage, "
                "key claims, figures or equations to revisit, and what is still uncovered. It does not show full "
                "extraction, citation checking, math validation, reproduction, or peer review as done."
            ),
        ),
        "ko": ChatCopy(
            headline="논문을 원하는 난이도로 풀어 설명할 수 있습니다.",
            body=(
                "paper-learning 카드는 설명 수준, PDF·출처 상태, 섹션별 커버리지, 핵심 주장, "
                "다시 봐야 할 그림과 수식, 아직 다루지 못한 범위를 정리합니다. 전문 추출, 인용 검증, "
                "수학 검증, 재현, 동료 검토가 끝났다는 내용은 담지 않습니다."
            ),
        ),
        "ja": ChatCopy(
            headline="この論文は希望する深さで解説できます。",
            body=(
                "paper-learning card は解説レベル、PDF/出典の状態、章ごとのカバー範囲、主要主張、"
                "見直す図表や数式、まだ扱えていない範囲をまとめます。全文抽出、引用確認、数式検証、再現、"
                "査読が済んだことは示しません。"
            ),
        ),
        "zh": ChatCopy(
            headline="这篇论文可以按需要的深度讲解。",
            body=(
                "paper-learning card 给出讲解难度、PDF/来源状态、章节覆盖、核心主张、需要回看的图表或公式，"
                "以及尚未覆盖的部分。它不表示全文抽取、引用核验、数学验证、复现或同行评审已经完成。"
            ),
        ),
        "es": ChatCopy(
            headline="Este paper puede explicarse con la profundidad que elijas.",
            body=(
                "La paper-learning card fija el nivel de explicación, el estado del PDF o la fuente, la cobertura por sección, "
                "los claims clave, las figuras o ecuaciones a revisar y lo que sigue sin cubrir. No da por hechas la extracción "
                "completa, la verificación de citas, la validación matemática, la reproducción ni la revisión externa."
            ),
        ),
        "fr": ChatCopy(
            headline="Ce papier peut être expliqué au niveau que vous choisissez.",
            body=(
                "La paper-learning card fixe le niveau d'explication, l'état du PDF ou de la source, la couverture des sections, "
                "les thèses clés, les figures ou équations à revoir et ce qui reste non couvert. Elle ne présente pas comme faites "
                "l'extraction complète, la vérification des citations, la validation mathématique, la reproduction ou la revue."
            ),
        ),
        "de": ChatCopy(
            headline="Dieses Paper lässt sich in der gewünschten Tiefe erklären.",
            body=(
                "Die paper-learning card legt Erklärniveau, PDF-/Quellenstatus, Abschnittsabdeckung, Kernthesen, "
                "zu prüfende Abbildungen oder Formeln und die offenen Stellen fest. Vollständige Extraktion, Zitatprüfung, "
                "mathematische Validierung, Reproduktion oder Review gelten darin nicht als erledigt."
            ),
        ),
    },
    "source_finder": {
        "en": ChatCopy(
            headline="This can become a source acquisition plan.",
            body=(
                "The source-finder plan lists typed candidate categories, search and acquisition status, "
                "missing provenance, license or access checks, and the best next step. It does not show "
                "web search, download, clone, extraction, verification, or downstream processing as done."
            ),
        ),
        "ko": ChatCopy(
            headline="자료 탐색을 출처 확보 계획으로 정리할 수 있습니다.",
            body=(
                "source-finder 계획은 논문, 링크, 데이터셋, 저장소, 발표자료 같은 후보 범주와 "
                "탐색·확보 상태, 출처와 라이선스 확인, 다음에 밟을 단계를 정리합니다. "
                "실제 웹 검색, 다운로드, 클론, 추출, 검증, 후속 처리가 끝났다는 내용은 담지 않습니다."
            ),
        ),
        "ja": ChatCopy(
            headline="探すべき資料は取得計画にまとめられます。",
            body=(
                "source-finder plan は論文、リンク、データセット、リポジトリ、公開スライドなどの候補カテゴリ、"
                "検索/取得状態、出典・ライセンス確認、次に進む手順をまとめます。検索、ダウンロード、clone、抽出、"
                "検証が済んだことは示しません。"
            ),
        ),
        "zh": ChatCopy(
            headline="资料查找可以变成来源获取计划。",
            body=(
                "source-finder plan 列出论文、链接、数据集、代码库、公开演示等候选类别，搜索/获取状态，"
                "来源和许可检查，以及下一步该做什么。它不表示网页搜索、下载、clone、抽取、验证或后续处理已经完成。"
            ),
        ),
        "es": ChatCopy(
            headline="Esto puede convertirse en un plan de búsqueda de fuentes.",
            body=(
                "El source-finder plan reúne categorías candidatas como papers, enlaces, datasets, repositorios o presentaciones, "
                "el estado de búsqueda y adquisición, la procedencia, la licencia o el acceso, y el siguiente paso. No da por hechas "
                "la búsqueda web, la descarga, el clone, la extracción ni la verificación."
            ),
        ),
        "fr": ChatCopy(
            headline="Cela peut devenir un plan d'acquisition de sources.",
            body=(
                "Le source-finder plan réunit les catégories candidates comme papiers, liens, datasets, dépôts ou présentations, "
                "l'état de recherche et d'acquisition, la provenance, la licence ou l'accès, et l'étape suivante. Il ne présente pas "
                "comme faits la recherche web, le téléchargement, le clone, l'extraction ou la vérification."
            ),
        ),
        "de": ChatCopy(
            headline="Daraus lässt sich ein Quellenbeschaffungsplan machen.",
            body=(
                "Der source-finder plan sammelt Kandidaten wie Paper, Links, Datasets, Repositories oder Präsentationen, "
                "den Such- und Beschaffungsstand, Herkunft, Lizenz/Zugriff und den nächsten Schritt. Websuche, Download, "
                "Clone, Extraktion und Verifikation gelten darin nicht als erledigt."
            ),
        ),
    },
    # The card speaks for the whole `research` engine, not only its
    # current-evidence half: source boundaries and declared depth, cited current
    # evidence, reference-implementation study with pinned refs, and
    # contested-claim gating before anything becomes a dossier, plan, report, or
    # coding brief. The `web_research` key stays as the wire identifier.
    "web_research": {
        "en": ChatCopy(
            headline="Source-backed research can ground this.",
            body=(
                "The research stays on the Hermes side: source boundaries, freshness window, and declared depth first, "
                "then cited current evidence, a study of the most relevant reference implementations with pinned refs when "
                "the decision needs them, and a cross-check of contested claims before findings become a dossier, plan, "
                "report, or coding brief. The card does not show sources already fetched or verified."
            ),
        ),
        "ko": ChatCopy(
            headline="출처 기반 리서치로 근거를 만들 수 있습니다.",
            body=(
                "리서치는 Hermes 안에서 진행합니다. 조사 범위, 최신성 기준, 선언한 깊이를 먼저 잡고, 인용 가능한 최신 근거를 모으며, "
                "판단에 필요하면 레퍼런스 구현을 버전 고정으로 깊게 확인하고, 쟁점이 되는 주장은 교차 검증을 거친 뒤 "
                "dossier, 계획, 리포트, 코딩 의뢰로 넘깁니다. 출처를 이미 모았거나 검증했다는 내용은 담지 않습니다."
            ),
        ),
        "ja": ChatCopy(
            headline="出典に基づく research で根拠を固められます。",
            body=(
                "research は Hermes 側で進みます。出典範囲、鮮度、宣言された深さを先に定め、引用できる最新の根拠を集め、"
                "判断に必要なら最も関連する reference implementation を版を固定して読み込み、争点のある主張は交差検証を通してから "
                "dossier、計画、レポート、コーディング依頼へ渡します。出典を取得・検証済みだとは示しません。"
            ),
        ),
        "zh": ChatCopy(
            headline="有来源支撑的 research 可以为这件事打底。",
            body=(
                "research 在 Hermes 侧进行：先定义来源边界、时效窗口和声明的深度，收集可引用的最新证据，"
                "在判断需要时以锁定版本深入研读最相关的 reference implementation，并在把发现转成 dossier、计划、报告或编码委托 "
                "之前对有争议的论断做交叉验证。卡片不表示来源已经抓取或核验。"
            ),
        ),
        "es": ChatCopy(
            headline="Una research con fuentes puede fundamentar esto.",
            body=(
                "La research se queda dentro de Hermes: primero límites de fuente, ventana de actualidad y profundidad declarada; después "
                "evidencia actual citada, el estudio de las reference implementations más relevantes con refs fijadas cuando la decisión lo "
                "exige, y verificación cruzada de las afirmaciones en disputa antes de que los hallazgos pasen a dossier, plan, reporte o "
                "encargo de código. La tarjeta no da las fuentes por obtenidas ni por verificadas."
            ),
        ),
        "fr": ChatCopy(
            headline="Une research sourcée peut étayer cela.",
            body=(
                "La research reste côté Hermes: périmètre des sources, fraîcheur et profondeur déclarée d'abord, puis des preuves "
                "actuelles citées, l'étude des reference implementations les plus pertinentes avec des refs figées quand la décision l'exige, "
                "et une vérification croisée des affirmations contestées avant que les résultats deviennent dossier, plan, rapport ou "
                "commande de code. La carte ne donne pas les sources pour récupérées ou vérifiées."
            ),
        ),
        "de": ChatCopy(
            headline="Quellenbasierte research kann das fundieren.",
            body=(
                "Die research bleibt auf der Hermes-Seite: zuerst Quellenrahmen, Aktualität und deklarierte Tiefe, dann zitierte aktuelle "
                "Evidenz, das Studium der relevantesten reference implementations mit fixierten Refs, wenn die Entscheidung es verlangt, und "
                "Kreuzprüfung strittiger Aussagen, bevor Ergebnisse zu Dossier, Plan, Bericht oder Code-Auftrag werden. "
                "Bereits abgerufene oder verifizierte Quellen weist die Karte nicht aus."
            ),
        ),
    },
    "agent_ops_review": {
        "en": ChatCopy(
            headline="Progress, blockers, and throughput need a manager view.",
            body=(
                "The review shows quality gates, current gaps, blockers, next actions, and throughput levers. "
                "It asks for no shell catalog command approval first, and it does not show execution, "
                "verification, CI, or merge as done."
            ),
        ),
        "ko": ChatCopy(
            headline="지금 상황을 한눈에 볼 수 있게 정리합니다.",
            body=(
                "이 카드는 진행 상태, 막힌 지점, 다음 행동, 품질 게이트, 처리량을 관리자 관점으로 보여줍니다. "
                "`omh list` 같은 shell 명령 승인은 먼저 받지 않습니다. 실행, 검증, CI, 머지가 끝났다는 내용은 담지 않습니다."
            ),
        ),
        "ja": ChatCopy(
            headline="現在の状況をひと目で分かる形に整理します。",
            body=(
                "このカードは進行状況、ブロッカー、次の action、品質ゲート、throughput を管理者視点で示します。"
                "shell command の承認を先に求めることはありません。実行、検証、CI、merge が済んだことは示しません。"
            ),
        ),
        "zh": ChatCopy(
            headline="当前进展可以整理成一张状态视图。",
            body=(
                "这张卡片从管理视角展示进展、阻塞点、下一步、质量 gate 和吞吐量。"
                "它不会先要求批准 shell command，也不表示执行、验证、CI 或 merge 已经完成。"
            ),
        ),
        "es": ChatCopy(
            headline="El estado actual cabe en una vista clara.",
            body=(
                "La tarjeta muestra progreso, bloqueos, siguiente acción, quality gates y throughput desde una vista de operador. "
                "No exige aprobar antes un shell command, y no da por hechos la ejecución, la verificación, la CI ni el merge."
            ),
        ),
        "fr": ChatCopy(
            headline="L'état actuel tient dans une vue claire.",
            body=(
                "La carte montre l'avancement, les blocages, la prochaine action, les quality gates et le throughput côté opérateur. "
                "Elle n'exige pas de valider d'abord un shell command et ne présente pas comme faits l'exécution, la vérification, la CI ou le merge."
            ),
        ),
        "de": ChatCopy(
            headline="Der aktuelle Stand passt in eine übersichtliche Ansicht.",
            body=(
                "Die Karte zeigt Fortschritt, Blocker, nächste Aktion, Quality Gates und Durchsatz aus Operator-Sicht. "
                "Sie verlangt vorher keine Freigabe für einen shell command und weist Ausführung, Verifikation, CI oder Merge nicht als erledigt aus."
            ),
        ),
    },
    "workflow_learning_missed_route": {
        "en": ChatCopy(
            headline="This missed OMH route can be recorded.",
            body=(
                "The request becomes missed-route feedback: a metadata-only trace, a reviewable "
                "missed-route bundle, and a minimized regression fixture added or requested. Any routing "
                "or skill change stays behind human review."
            ),
        ),
        "ko": ChatCopy(
            headline="놓친 OMH 라우팅을 학습 후보로 기록할 수 있습니다.",
            body=(
                "이 요청은 missed-route 피드백으로 다룹니다. 원문을 그대로 저장하지 않고 "
                "메타데이터 trace와 리뷰 가능한 bundle을 만들며, 최소 회귀 케이스를 추가하거나 요청합니다. "
                "라우팅과 스킬 변경은 사람 리뷰를 거친 뒤에만 반영됩니다."
            ),
        ),
        "ja": ChatCopy(
            headline="見逃した OMH route は改善候補として記録できます。",
            body="これは missed-route feedback として扱い、raw promptを保存せずmetadata trace、レビュー可能なbundle、最小回帰ケースを用意します。routingやskill変更は人のレビューの後だけです。",
        ),
        "zh": ChatCopy(
            headline="这次漏掉的 OMH route 可以记录为改进候选。",
            body="它会作为 missed-route feedback 处理：不保存原始 prompt，只记录 metadata trace、可 review 的 bundle 和最小回归用例。routing 或 skill 改动仍需要人工 review。",
        ),
        "es": ChatCopy(
            headline="Esta ruta OMH perdida puede registrarse.",
            body="Se trata como missed-route feedback: metadata trace sin prompt crudo, bundle revisable y caso mínimo de regresión. Cualquier cambio de routing o skill queda detrás de revisión humana.",
        ),
        "fr": ChatCopy(
            headline="Cette route OMH manquée peut être enregistrée.",
            body="Elle est traitée comme missed-route feedback: metadata trace sans prompt brut, bundle révisable et cas de régression minimal. Tout changement de routing ou skill reste soumis à revue humaine.",
        ),
        "de": ChatCopy(
            headline="Diese verpasste OMH route lässt sich erfassen.",
            body="Sie wird als missed-route feedback behandelt: metadata trace ohne raw prompt, reviewbares bundle und minimaler Regressionstest. Routing- oder Skill-Änderungen bleiben hinter Human Review.",
        ),
    },
    "workflow_learning_readiness": {
        "en": ChatCopy(
            headline="This run can be checked for learning readiness.",
            body=(
                "The attempt becomes learning material without storing raw prompts: a recorded trace, "
                "deterministic evals, a regression case, a readiness audit, and a redacted review bundle "
                "when it helps. Any skill or routing improvement still needs human review."
            ),
        ),
        "ko": ChatCopy(
            headline="이 실행이 개선에 쓸 만한지 점검할 수 있습니다.",
            body=(
                "실행 기록을 학습 재료로 정리합니다. raw prompt는 저장하지 않고 trace, deterministic eval, "
                "회귀 케이스, readiness audit, redacted review bundle을 만들며, 스킬이나 라우팅 개선은 여전히 사람 리뷰가 필요합니다."
            ),
        ),
        "ja": ChatCopy(
            headline="この実行が改善に使えるか点検できます。",
            body="raw promptを保存せず、trace、deterministic eval、回帰ケース、readiness audit、redacted review bundleに整理します。skillやrouting改善は人のレビューが必要です。",
        ),
        "zh": ChatCopy(
            headline="这次运行可以检查是否适合改进。",
            body="在不保存原始 prompt 的前提下整理 trace、deterministic eval、回归用例、readiness audit 和 redacted review bundle。skill 或 routing 改进仍需人工 review。",
        ),
        "es": ChatCopy(
            headline="Esta ejecución puede revisarse para aprender de ella.",
            body="Sin guardar prompts crudos, reúne trace, deterministic eval, caso de regresión, readiness audit y redacted review bundle. Las mejoras de skill o routing requieren revisión humana.",
        ),
        "fr": ChatCopy(
            headline="Cette exécution peut être vérifiée pour en tirer des leçons.",
            body="Sans stocker de prompt brut, elle réunit trace, deterministic eval, cas de régression, readiness audit et redacted review bundle. Toute amélioration de skill ou routing exige une revue humaine.",
        ),
        "de": ChatCopy(
            headline="Dieser Lauf lässt sich auf Lernbereitschaft prüfen.",
            body="Ohne raw prompts zu speichern entstehen trace, deterministic eval, Regression Case, readiness audit und redacted review bundle. Skill- oder Routing-Verbesserungen brauchen Human Review.",
        ),
    },
    "clarify": {
        "en": ChatCopy(
            headline="One clarification is needed before this is routed.",
            body="In one sentence, name the outcome you want, the inputs to use, and when this should stop.",
        ),
        "ko": ChatCopy(
            headline="라우팅 전에 한 가지 확인이 필요합니다.",
            body="원하는 결과, 사용할 자료, 멈춰야 할 기준을 한 문장으로 알려주세요.",
        ),
        "ja": ChatCopy(headline="route の前に一つ確認が必要です。", body="欲しい結果、使う資料、止める条件を一文で教えてください。"),
        "zh": ChatCopy(headline="route 前还需要确认一点。", body="请用一句话说明想要的结果、要用的材料和停止条件。"),
        "es": ChatCopy(headline="Falta una aclaración antes de enrutar.", body="Indica en una frase el resultado, los insumos y la condición de parada."),
        "fr": ChatCopy(headline="Une précision est nécessaire avant la route.", body="Indiquez en une phrase le résultat voulu, les entrées et la condition d'arrêt."),
        "de": ChatCopy(headline="Vor dem Routing fehlt eine Klärung.", body="Nenne Ergebnis, Eingaben und Stop-Bedingung in einem Satz."),
    },
    "file_lookup": {
        "en": ChatCopy(
            headline="This looks like a file or text lookup.",
            body="The answer comes straight from the file or text in the request, and no other OMH step starts. Name the file or path to check when the request does not carry one.",
        ),
        "ko": ChatCopy(
            headline="파일이나 텍스트 확인 요청으로 보입니다.",
            body="요청에 적힌 파일/텍스트 확인으로 바로 답하고, 다른 OMH 단계는 시작하지 않습니다. 확인할 파일이나 경로가 요청에 없으면 먼저 물어보세요.",
        ),
        "ja": ChatCopy(headline="ファイルまたはテキスト確認に見えます。", body="要求にあるファイル/テキストの確認だけで答え、他の OMH の手順は始まりません。対象のファイルやパスが無いときは先に尋ねます。"),
        "zh": ChatCopy(headline="这看起来是文件或文本查找。", body="直接按请求里的文件或文本作答，不会启动其他 OMH 步骤。请求里没有目标文件或路径时会先询问。"),
        "es": ChatCopy(headline="Parece una consulta de archivo o texto.", body="La respuesta sale directamente del archivo o el texto indicado, sin iniciar ningún otro paso de OMH. Indica la ruta cuando la solicitud no la trae."),
        "fr": ChatCopy(headline="Cela ressemble à une vérification de fichier ou texte.", body="La réponse vient directement du fichier ou du texte indiqué, sans démarrer d'autre étape OMH. Donnez le chemin quand la demande ne le contient pas."),
        "de": ChatCopy(headline="Das wirkt wie eine Datei- oder Textsuche.", body="Die Antwort kommt direkt aus der genannten Datei oder dem Text, ohne einen weiteren OMH-Schritt. Nenne den Pfad, wenn die Anfrage ihn nicht enthält."),
    },
    "direct_answer": {
        "en": ChatCopy(
            headline="This can be answered directly in the chat.",
            body="The answer stays in this chat and no OMH step starts. Ask for an OMH skill by name to take a different route.",
        ),
        "ko": ChatCopy(
            headline="이건 OMH 없이 바로 답하면 됩니다.",
            body="현재 채팅에서 바로 답하고 OMH 단계는 시작하지 않습니다. 다른 방식이 필요하면 원하는 OMH 기능을 이름으로 요청하세요.",
        ),
        "ja": ChatCopy(headline="これは OMH なしで直接答えられます。", body="このチャットで直接答え、OMH の手順は始まりません。別の進め方が必要なら OMH の機能を名前で指定してください。"),
        "zh": ChatCopy(headline="这个可以直接在聊天里回答。", body="答案留在当前聊天，不会启动 OMH 步骤。需要别的方式时，请按名称指定 OMH 功能。"),
        "es": ChatCopy(headline="Esto se puede responder directamente en el chat.", body="La respuesta se queda en este chat y no se inicia ningún paso de OMH. Pide una función de OMH por su nombre para tomar otra ruta."),
        "fr": ChatCopy(headline="Cela peut recevoir une réponse directe dans le chat.", body="La réponse reste dans ce chat et aucune étape OMH ne démarre. Demandez une fonction OMH par son nom pour prendre une autre voie."),
        "de": ChatCopy(headline="Das lässt sich direkt im Chat beantworten.", body="Die Antwort bleibt in diesem Chat, und kein OMH-Schritt startet. Nenne eine OMH-Funktion beim Namen für einen anderen Weg."),
    },
    "generic_clarify": {
        "en": ChatCopy(
            headline="The goal needs to be clearer before this is routed.",
            body="Name the outcome you want in one sentence, and the right next step follows from it.",
        ),
        "ko": ChatCopy(
            headline="라우팅 전에 목표가 조금 더 분명해야 합니다.",
            body="원하는 결과를 한 문장으로 알려주세요. 그에 맞는 다음 단계가 정해집니다.",
        ),
        "ja": ChatCopy(headline="route の前に目標をもう少し明確にする必要があります。", body="望む結果を一文で教えてください。それに合う次の手順が決まります。"),
        "zh": ChatCopy(headline="route 前目标需要更清楚一点。", body="请用一句话说明想要的结果，合适的下一步据此确定。"),
        "es": ChatCopy(headline="El objetivo debe quedar más claro antes de enrutar.", body="Indica en una frase el resultado que quieres; el siguiente paso adecuado sale de ahí."),
        "fr": ChatCopy(headline="L'objectif doit être plus clair avant la route.", body="Dites en une phrase le résultat voulu; l'étape suivante en découle."),
        "de": ChatCopy(headline="Vor dem Routing muss das Ziel klarer sein.", body="Nenne das gewünschte Ergebnis in einem Satz; der passende nächste Schritt ergibt sich daraus."),
    },
    "goal_quality_coaching": {
        "en": ChatCopy(
            headline="This goal does not have a finish line yet.",
            body=(
                "An open-ended goal like this has no completion test, so an automated completion "
                "judge can keep going until it hits its turn ceiling (the default is 20 turns) "
                "without ever confirming it is actually done. Name what \"done\" means -- for "
                "example \"done when the tests pass\" or \"done when new users can sign up in under "
                "a minute\" -- and that becomes the success criteria."
            ),
        ),
        "ko": ChatCopy(
            headline="이 목표에는 아직 끝나는 기준이 없습니다.",
            body=(
                "이렇게 열린 목표는 완료를 판단할 기준이 없어서, 완료 여부를 자동으로 판단하는 "
                "심사가 정해진 턴 수(기본값 20턴)까지 계속 반복될 수 있습니다. "
                "\"테스트가 통과하면 완료\"처럼 \"완료\"가 무엇을 뜻하는지 알려주시면 "
                "그것이 성공 기준이 됩니다."
            ),
        ),
    },
}


def chat_copy(copy_id: str, *, locale: str | None = None, korean: bool | None = None) -> ChatCopy:
    selected_locale = _normalize_locale(locale, korean=korean)
    copy = _CARD_COPY[copy_id]
    return copy.get(selected_locale) or copy["en"]


def card_copy_locales() -> dict[str, tuple[str, ...]]:
    """Which locales each card id carries, for the parity and count pins."""
    return {copy_id: tuple(sorted(entries)) for copy_id, entries in sorted(_CARD_COPY.items())}


# OMH's own filing vocabulary. Each word names a part of the product's
# machinery, not anything the reader asked about, so a card that uses one asks
# them to learn the machinery before the sentence carries meaning. One ASCII
# list covers all seven locales because the localized bodies wrote these as
# English loanwords rather than translating them.
CARD_COPY_RECORD_TERMS: tuple[str, ...] = (
    "handoff",
    "lane",
    "observed",
    "picker",
    "prepared",
    "workflow",
    "wrapper",
)

# The first-person forms this table carried before the voice rule landed, kept
# as a regression list and not as a grammar checker. Korean, Japanese, Chinese
# and Spanish drop the subject pronoun, so what gives the speaker away is a verb
# inflection, and no short list of inflections is complete: a card written in a
# first-person form absent from here passes the check and still breaks the rule.
# What the list does guarantee is that the shapes that were here do not return.
CARD_COPY_FIRST_PERSON_MARKERS: dict[str, tuple[str, ...]] = {
    "en": ("i", "i'll", "i'm", "me", "my"),
    "ko": ("겠습니다", "제가", "저는"),
    "ja": ("私",),
    "zh": ("我",),
    "es": (
        "yo",
        "puedo",
        "prepararé",
        "mostraré",
        "diré",
        "afirmaré",
        "elegiré",
        "registraré",
        "trataré",
        "dime",
    ),
    "fr": ("je", "j'ai", "moi"),
    "de": ("ich", "mir", "mich", "meine"),
}


def _carries_marker(text: str, marker: str, *, plural: bool = False) -> bool:
    """Whether `marker` stands alone in `text`, case-folded.

    An ASCII marker is bounded by letters and apostrophes, so `lane` does not
    fire inside `planet` and `i` does not fire inside `it`. That same bound
    still finds an English loanword inside a Korean, Japanese, or Chinese body,
    because the characters around it are not ASCII letters. A non-ASCII marker
    is a plain substring instead: those scripts write without spaces, so there
    is no boundary to anchor on.

    `plural` widens the match by one trailing `s`, which the record terms need
    and the first-person markers must not have: `workflows` is the same record
    word, while `i` widened the same way would fire on `is`.
    """
    lowered = text.lower()
    if not marker.isascii():
        return marker in lowered
    tail = "s?" if plural else ""
    return re.search(rf"(?<![a-z']){re.escape(marker)}{tail}(?![a-z'])", lowered) is not None


def card_copy_voice_violations(
    table: Mapping[str, Mapping[str, ChatCopy]] | None = None,
) -> tuple[tuple[str, str, str, str, str], ...]:
    """Every `(copy_id, locale, field, rule, term)` the card table breaks.

    Derived from the table itself rather than from a list of known sentences, so
    a card added later is checked without anyone enrolling it. `table` is the
    seam the negative cases use to prove the check is not vacuous.
    """
    subject = _CARD_COPY if table is None else table
    violations: list[tuple[str, str, str, str, str]] = []
    for copy_id, entries in sorted(subject.items()):
        for locale, copy in sorted(entries.items()):
            for field in ("headline", "body"):
                text = getattr(copy, field)
                for term in CARD_COPY_RECORD_TERMS:
                    if _carries_marker(text, term, plural=True):
                        violations.append((copy_id, locale, field, "record_term", term))
                for marker in CARD_COPY_FIRST_PERSON_MARKERS.get(locale, ()):
                    if _carries_marker(text, marker):
                        violations.append((copy_id, locale, field, "first_person", marker))
    return tuple(violations)


# The sentence a clarification's body gains when its best match is in a
# capability family this OMH home turned off. A localized body replaces the
# English clarification that already says it, so without this a Korean reader
# was never told. `{skill}`, `{family}` and `{command}` are filled in; the
# family label stays its product name in every language.
CAPABILITY_NOTE_SENTENCES: dict[str, str] = {
    "en": "If you meant the work `{skill}` does, the {family} capability family is turned off in this OMH install; `{command}` turns it back on.",
    "ko": "`{skill}` 작업을 원하셨다면, 이 OMH 설치에서 {family} 기능 묶음이 꺼져 있습니다. `{command}`로 다시 켤 수 있습니다.",
    "ja": "`{skill}` の作業をお求めでしたら、この OMH では {family} の機能群がオフになっています。`{command}` で再びオンにできます。",
    "zh": "如果需要 `{skill}` 的功能，此 OMH 中的 {family} 功能组已关闭；运行 `{command}` 即可重新开启。",
    "es": "Si buscabas el trabajo de `{skill}`, la familia {family} está desactivada en este OMH; `{command}` la vuelve a activar.",
    "fr": "Si vous cherchiez le travail de `{skill}`, la famille {family} est désactivée dans cet OMH ; `{command}` la réactive.",
    "de": "Falls die Arbeit von `{skill}` gemeint war: Die Familie {family} ist in diesem OMH ausgeschaltet; `{command}` schaltet sie wieder ein.",
}


def capability_note_sentence(locale: str, *, skill: str, family: str, command: str) -> str:
    """The turned-off-family sentence in `locale`, English for an unsupported one."""
    template = CAPABILITY_NOTE_SENTENCES.get(_normalize_locale(locale), CAPABILITY_NOTE_SENTENCES["en"])
    return template.format(skill=skill, family=family, command=command)


# One line per recovery-action id, per locale, in the `_CARD_COPY` shape and
# with the same English fallback.
#
# A table of ids rather than translated corrections, on purpose. A denial's
# `correction` comes from `safety_preflight._CORRECTIONS`, which is deliberately
# constant-only and interpolation-free so no caller value can reach a terminal
# through it. Translating that string would mean either a second constant table
# keyed by the same reason codes -- a fifth explanation vocabulary -- or
# building the localized line from the denial's fields, which is exactly the
# interpolation the English side refuses. Keying off a closed recovery id keeps
# the localized surface a lookup.
_RECOVERY_ACTION_COPY: dict[str, dict[str, str]] = {
    "declare_missing_field": {
        "en": "Declare the missing field and send the request again.",
        "ko": "빠진 항목을 명시한 뒤 다시 요청해 주세요.",
        "ja": "不足している項目を明示してから、もう一度依頼してください。",
        "zh": "补上缺少的字段后再发送一次请求。",
        "es": "Declara el campo que falta y vuelve a enviar la solicitud.",
        "fr": "Déclarez le champ manquant et renvoyez la demande.",
        "de": "Deklariere das fehlende Feld und sende die Anfrage erneut.",
    },
    "remove_prohibited_content": {
        "en": "Remove the credential or prohibited content and send a reference instead.",
        "ko": "자격 증명이나 금지된 내용을 제거하고 참조값으로 대신 보내 주세요.",
        "ja": "認証情報や禁止された内容を取り除き、参照値に置き換えてください。",
        "zh": "移除凭据或禁止内容，改用引用值发送。",
        "es": "Elimina la credencial o el contenido prohibido y envía una referencia en su lugar.",
        "fr": "Retirez l'identifiant ou le contenu interdit et envoyez plutôt une référence.",
        "de": "Entferne die Zugangsdaten oder verbotenen Inhalte und sende stattdessen eine Referenz.",
    },
    "narrow_declared_scope": {
        "en": "Narrow the declared scope so it stays inside the limits and try again.",
        "ko": "선언한 범위를 한도 안으로 좁혀서 다시 시도해 주세요.",
        "ja": "宣言した範囲を上限内に狭めて、もう一度試してください。",
        "zh": "把声明的范围收窄到限制以内后重试。",
        "es": "Reduce el alcance declarado para que quede dentro de los límites e inténtalo de nuevo.",
        "fr": "Réduisez la portée déclarée pour rester dans les limites, puis réessayez.",
        "de": "Grenze den deklarierten Bereich auf die Limits ein und versuche es erneut.",
    },
    "request_approval": {
        "en": "Ask an operator to approve this action for this scope before retrying.",
        "ko": "다시 시도하기 전에 이 범위에 대한 작업 승인을 담당자에게 받아 주세요.",
        "ja": "再試行の前に、この範囲に対する操作の承認を担当者から得てください。",
        "zh": "重试前请让操作者批准此范围内的该操作。",
        "es": "Pide a un operador que apruebe esta acción para este alcance antes de reintentar.",
        "fr": "Demandez à un opérateur d'approuver cette action pour cette portée avant de réessayer.",
        "de": "Lass einen Operator diese Aktion für diesen Bereich freigeben, bevor du es erneut versuchst.",
    },
    "record_observed_evidence": {
        "en": "Record the observed evidence this claim needs, then ask again.",
        "ko": "이 주장에 필요한 관측 증거를 기록한 뒤 다시 요청해 주세요.",
        "ja": "この主張に必要な観測証跡を記録してから、もう一度依頼してください。",
        "zh": "先记录该结论所需的观测证据，然后再次请求。",
        "es": "Registra la evidencia observada que requiere esta afirmación y vuelve a preguntar.",
        "fr": "Enregistrez la preuve observée requise par cette affirmation, puis redemandez.",
        "de": "Zeichne den beobachteten Nachweis auf, den diese Aussage braucht, und frage erneut.",
    },
    "choose_executor": {
        "en": "Choose a coding agent, then send the request again.",
        "ko": "coding agent를 먼저 고른 뒤 다시 요청해 주세요.",
        "ja": "coding agent を選んでから、もう一度依頼してください。",
        "zh": "先选择一个 coding agent，然后再发送请求。",
        "es": "Elige un coding agent y vuelve a enviar la solicitud.",
        "fr": "Choisissez un coding agent, puis renvoyez la demande.",
        "de": "Wähle einen coding agent und sende die Anfrage erneut.",
    },
    "no_recovery_available": {
        "en": "No recovery is available for this decision from here.",
        "ko": "이 결정에 대해 여기서 할 수 있는 복구 조치는 없습니다.",
        "ja": "この判断について、ここから取れる復旧手段はありません。",
        "zh": "对于这个决定，这里没有可用的补救方式。",
        "es": "No hay recuperación disponible para esta decisión desde aquí.",
        "fr": "Aucune reprise n'est possible ici pour cette décision.",
        "de": "Für diese Entscheidung gibt es hier keine Wiederherstellung.",
    },
}


def recovery_action_copy(recovery_action: str, *, locale: str | None = None, korean: bool | None = None) -> str:
    """One localized line for a closed recovery-action id, English on any gap.

    An id this table does not carry renders empty rather than as itself: the id
    is an internal token, and printing `narrow_declared_scope` at an operator is
    worse than printing nothing.
    """
    entry = _RECOVERY_ACTION_COPY.get(str(recovery_action or ""))
    if not entry:
        return ""
    return entry.get(_normalize_locale(locale, korean=korean)) or entry["en"]


def recovery_action_copy_ids() -> tuple[str, ...]:
    """Every recovery-action id this table can render, for the coverage pin."""
    return tuple(sorted(_RECOVERY_ACTION_COPY))


def skill_picker_headline(*, catalog_question: bool, locale: str | None = None, korean: bool | None = None) -> str:
    selected_locale = _normalize_locale(locale, korean=korean)
    if selected_locale == "ko":
        return "OMH workflow 목록입니다." if catalog_question else "OMH workflow를 바로 고를 수 있습니다."
    if selected_locale == "ja":
        return "OMH workflow 一覧です。" if catalog_question else "OMH workflowを選べます。"
    if selected_locale == "zh":
        return "这是 OMH workflow 列表。" if catalog_question else "可以选择 OMH workflow。"
    if selected_locale == "es":
        return "Estos son los workflows de OMH." if catalog_question else "Elige un workflow de OMH."
    if selected_locale == "fr":
        return "Voici les workflows OMH." if catalog_question else "Choisissez un workflow OMH."
    if selected_locale == "de":
        return "Hier sind die OMH workflows." if catalog_question else "Wähle einen OMH workflow."
    return "Here are the OMH workflows." if catalog_question else "Choose an OMH workflow."


def skill_picker_body(
    *,
    catalog_question: bool,
    family_lines: list[str],
    locale: str | None = None,
    korean: bool | None = None,
) -> str:
    selected_locale = _normalize_locale(locale, korean=korean)
    family_heading = "Capability families:" if catalog_question else "Families:"
    if selected_locale == "ko":
        intro = (
            "`omh list` 같은 shell 명령 승인을 받지 않아도 됩니다. OMH는 계획, 운영, 자료/이미지, 코딩 위임, loop, 상태 확인 workflow를 Hermes 채팅 안에서 고를 수 있게 해줍니다."
            if catalog_question
            else "시작 방식을 고르세요. 잘 모르겠으면 Route for me를 고르면 Hermes가 요청에서 가장 안전한 다음 workflow를 고릅니다."
        )
        start_label = "먼저 이렇게 시작하세요:" if catalog_question else "추천 시작점:"
    elif selected_locale == "ja":
        intro = (
            "shell command の承認なしで使えます。OMHは計画、運用、deliverables、coding handoffs、loop、statusをHermesチャット内で選べるようにします。"
            if catalog_question
            else "開始方法を選んでください。迷ったら Route for me でHermesが安全なworkflowを選びます。"
        )
        start_label = "まずここから:"
    elif selected_locale == "zh":
        intro = (
            "不需要先批准 shell command。OMH 让 Hermes 在聊天里选择 planning、ops、deliverables、coding handoffs、loops 和 status workflow。"
            if catalog_question
            else "请选择开始方式。不确定时选 Route for me，让 Hermes 选择最安全的 workflow。"
        )
        start_label = "从这里开始:"
    elif selected_locale == "es":
        intro = (
            "No necesitas aprobar un shell command. OMH permite elegir planning, ops, deliverables, coding handoffs, loops y status desde el chat de Hermes."
            if catalog_question
            else "Elige cómo empezar. Si no estás seguro, Route for me deja que Hermes seleccione el workflow más seguro."
        )
        start_label = "Empieza aquí:"
    elif selected_locale == "fr":
        intro = (
            "Pas besoin d'approuver un shell command. OMH permet de choisir planning, ops, deliverables, coding handoffs, loops et status depuis le chat Hermes."
            if catalog_question
            else "Choisissez comment commencer. En cas de doute, Route for me laisse Hermes choisir le workflow le plus sûr."
        )
        start_label = "Commencez ici:"
    elif selected_locale == "de":
        intro = (
            "Du musst keinen shell command freigeben. OMH macht planning, ops, deliverables, coding handoffs, loops und status direkt im Hermes-Chat auswählbar."
            if catalog_question
            else "Wähle den Start. Wenn du unsicher bist, lässt Route for me Hermes den sichersten workflow wählen."
        )
        start_label = "Start hier:"
    else:
        intro = (
            "You do not need to run a shell command for this. OMH covers planning, ops, deliverables, coding handoffs, loops, and status."
            if catalog_question
            else "Pick how to start, or choose Route for me and Hermes will select the safest next step from the request."
        )
        start_label = "Start here:" if catalog_question else "Best default:"

    lines = [
        intro,
        "",
        start_label,
        "- Route for me: let Hermes choose the safest workflow from your message.",
    ]
    if catalog_question:
        lines.extend(
            [
                "- Choose workflow: pick from the OMH capability families.",
                "- Search workflows: find the exact skill when you already know the job.",
            ]
        )
    lines.extend(["", family_heading, *family_lines])
    return "\n".join(lines)


# The consolidation notice is one sentence appended to whatever card the router
# chose, and that card's copy is already in the reader's language. An English
# suffix on a Korean body reads as a glitch, so the sentence and its reason
# phrases localize through the same locale the card used.
# Two clauses, kept apart because only one of them can be wrong. The status
# clause reports a fact the reader always needs -- consolidation is pending, and
# why. The call to action asks them to request a review, which is correct on a
# card about something else and absurd on a card that is already the review: it
# told a user who just asked for a memory review to ask for a memory review.
# `consolidation_notice_line` drops the second clause when the routed card
# already satisfies it.
_CONSOLIDATION_NOTICE_STATUS = {
    "en": "Memory tidy-up is pending ({summary}).",
    "ko": "기억 정리가 밀려 있습니다 ({summary}).",
    "ja": "メモリ整理が保留中です（{summary}）。",
    "zh": "记忆整理待处理（{summary}）。",
    "es": "La consolidación de memoria está pendiente ({summary}).",
    "fr": "Le rangement de la mémoire est en attente ({summary}).",
    "de": "Das Aufräumen des Gedächtnisses steht aus ({summary}).",
}

_CONSOLIDATION_NOTICE_CALL_TO_ACTION = {
    "en": "Ask me to review and consolidate memory.",
    "ko": "기억을 검토하고 정리해 달라고 말씀해 주세요.",
    "ja": "メモリの確認と整理を依頼してください。",
    "zh": "请让我审查并整理记忆。",
    "es": "Pídeme revisar y consolidar la memoria.",
    "fr": "Demandez-moi de revoir et consolider la mémoire.",
    "de": "Bitte mich, das Gedächtnis zu prüfen und zu konsolidieren.",
}

_CONSOLIDATION_REASON_PHRASES = {
    "headroom_below_floor": {
        "en": "memory is nearly full",
        "ko": "기억이 거의 가득 참",
        "ja": "メモリがほぼ満杯",
        "zh": "记忆几乎已满",
        "es": "la memoria está casi llena",
        "fr": "la mémoire est presque pleine",
        "de": "der Speicher ist fast voll",
    },
    "turn_interval_reached": {
        "en": "several turns since the last tidy-up",
        "ko": "마지막 정리 후 여러 턴 경과",
        "ja": "前回の整理から数ターン経過",
        "zh": "距上次整理已过多轮",
        "es": "varios turnos desde la última consolidación",
        "fr": "plusieurs tours depuis le dernier rangement",
        "de": "mehrere Züge seit dem letzten Aufräumen",
    },
    "session_ending_with_unconsolidated_turns": {
        "en": "a session ended with work not yet consolidated",
        "ko": "정리되지 않은 작업을 남긴 채 세션 종료",
        "ja": "未整理の作業を残してセッションが終了",
        "zh": "会话结束时仍有未整理的内容",
        "es": "una sesión terminó con trabajo sin consolidar",
        "fr": "une session s'est terminée avec du travail non consolidé",
        "de": "eine Sitzung endete mit nicht konsolidierter Arbeit",
    },
    "context_compaction_observed": {
        "en": "context was compacted",
        "ko": "컨텍스트가 압축됨",
        "ja": "コンテキストが圧縮された",
        "zh": "上下文已压缩",
        "es": "el contexto fue compactado",
        "fr": "le contexte a été compacté",
        "de": "der Kontext wurde komprimiert",
    },
    "duplicate_records": {
        "en": "duplicate memories were detected",
        "ko": "중복 기억 발견",
        "ja": "重複した記憶を検出",
        "zh": "检测到重复记忆",
        "es": "se detectaron memorias duplicadas",
        "fr": "des souvenirs en double ont été détectés",
        "de": "doppelte Erinnerungen erkannt",
    },
    "expiring_records": {
        "en": "some memories are expiring",
        "ko": "일부 기억이 만료 예정",
        "ja": "一部の記憶が期限切れ間近",
        "zh": "部分记忆即将过期",
        "es": "algunas memorias están por expirar",
        "fr": "certains souvenirs arrivent à expiration",
        "de": "einige Erinnerungen laufen ab",
    },
}

_CONSOLIDATION_FALLBACK_SUMMARY = {
    "en": "a consolidation brief is waiting",
    "ko": "정리 안내가 대기 중",
    "ja": "整理の案内が待機中",
    "zh": "整理提示等待处理",
    "es": "hay un aviso de consolidación en espera",
    "fr": "un avis de consolidation est en attente",
    "de": "ein Konsolidierungshinweis wartet",
}


def consolidation_notice_line(
    locale: str,
    reasons: list[str],
    *,
    suppress_call_to_action: bool = False,
) -> str:
    """The pending-consolidation sentence in the card's language.

    ``reasons`` are the scheduler's own strings (``headroom_below_floor:289<=300``);
    the value suffix is detail for wrappers, so only the family selects a phrase
    and an unknown family simply contributes nothing.

    ``suppress_call_to_action`` drops the closing imperative while keeping the
    status clause. The status clause is never dropped: a card that reviews memory
    still needs to know consolidation is pending and that headroom is the reason,
    because that changes what the review has to accomplish.
    """
    resolved = _normalize_locale(locale)
    if resolved not in _CONSOLIDATION_NOTICE_STATUS:
        resolved = "en"
    phrases: list[str] = []
    for reason in reasons:
        family = reason.split(":", 1)[0]
        phrase = _CONSOLIDATION_REASON_PHRASES.get(family, {}).get(resolved)
        if phrase and phrase not in phrases:
            phrases.append(phrase)
    summary = "; ".join(phrases) if phrases else _CONSOLIDATION_FALLBACK_SUMMARY[resolved]
    status = _CONSOLIDATION_NOTICE_STATUS[resolved].format(summary=summary)
    if suppress_call_to_action:
        return status
    return f"{status} {_CONSOLIDATION_NOTICE_CALL_TO_ACTION[resolved]}"
