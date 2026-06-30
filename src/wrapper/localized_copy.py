from __future__ import annotations

from dataclasses import dataclass


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


_CARD_COPY: dict[str, dict[str, ChatCopy]] = {
    "img_summary": {
        "en": ChatCopy(
            headline="I can prepare a shareable image card for this.",
            body=(
                "I will turn the source into a shareable image-card brief: audience, layout, on-image copy, "
                "generation prompt, negative prompt, and a quick QA checklist. If no image tool is connected, "
                "I will ask which tool to use instead of pretending an image was generated."
            ),
        ),
        "ko": ChatCopy(
            headline="공유용 이미지 카드 초안을 준비할 수 있습니다.",
            body=(
                "원본 내용을 청중, 레이아웃, 이미지 안 문구, 생성 프롬프트, 네거티브 프롬프트, "
                "간단한 QA 체크리스트로 정리하겠습니다. 연결된 이미지 생성 도구가 없으면 생성했다고 "
                "말하지 않고 어떤 도구를 쓸지 먼저 고릅니다."
            ),
        ),
        "ja": ChatCopy(
            headline="共有用の画像カード案を準備できます。",
            body=(
                "素材を画像カード向けの image-card brief として整理します。対象読者、レイアウト、画像内コピー、生成プロンプト、"
                "ネガティブプロンプト、簡単なQAチェックを分けます。画像ツールが未接続なら、生成済みとは言わず先に使うツールを確認します。"
            ),
        ),
        "zh": ChatCopy(
            headline="我可以先准备一张可分享的图片卡片方案。",
            body=(
                "我会把素材整理成 image-card brief：受众、版式、图片内文案、生成提示词、负面提示词和快速 QA。"
                "如果还没有连接图片工具，我会先询问要用哪个工具，不会假装图片已经生成。"
            ),
        ),
        "es": ChatCopy(
            headline="Puedo preparar una tarjeta visual compartible.",
            body=(
                "Convertiré la fuente en un image-card brief: audiencia, layout, texto dentro de la imagen, prompt de generación, "
                "negative prompt y QA rápido. Si no hay herramienta de imagen conectada, preguntaré cuál usar en vez de fingir que la imagen ya existe."
            ),
        ),
        "fr": ChatCopy(
            headline="Je peux préparer une carte image partageable.",
            body=(
                "Je vais transformer la source en image-card brief: audience, mise en page, texte dans l'image, prompt de génération, "
                "negative prompt et QA rapide. Si aucun outil image n'est connecté, je demanderai lequel utiliser au lieu de prétendre que l'image existe."
            ),
        ),
        "de": ChatCopy(
            headline="Ich kann eine teilbare Bildkarte vorbereiten.",
            body=(
                "Ich erstelle daraus ein image-card brief: Zielgruppe, Layout, Text im Bild, Generierungs-Prompt, Negative Prompt "
                "und kurze QA. Wenn kein Bildtool verbunden ist, frage ich zuerst nach dem Tool und behaupte nicht, dass ein Bild erzeugt wurde."
            ),
        ),
    },
    "paper_learning": {
        "en": ChatCopy(
            headline="I can explain this paper with the right depth.",
            body=(
                "I will prepare a paper-learning card: explanation level, source/PDF state, section coverage, "
                "key claims, figures or equations to revisit, and a coverage ledger. I will not claim full extraction, "
                "citation checking, math validation, reproduction, or peer review until those are observed."
            ),
        ),
        "ko": ChatCopy(
            headline="논문을 원하는 난이도로 풀어 설명할 수 있습니다.",
            body=(
                "paper-learning 카드로 설명 수준, PDF/출처 상태, 섹션별 커버리지, 핵심 주장, "
                "다시 봐야 할 그림/수식, 누락 범위를 정리하겠습니다. 전문 추출, 인용 검증, "
                "수학 검증, 재현, 피어 리뷰는 관측되기 전까지 완료됐다고 말하지 않습니다."
            ),
        ),
        "ja": ChatCopy(
            headline="この論文を希望する深さで解説できます。",
            body=(
                "paper-learning card として、解説レベル、PDF/出典の状態、章ごとのカバー範囲、主要主張、"
                "見直す図表や数式、未確認範囲を整理します。抽出、引用確認、数式検証、再現、査読は観測されるまで完了扱いしません。"
            ),
        ),
        "zh": ChatCopy(
            headline="我可以按需要的深度讲解这篇论文。",
            body=(
                "我会准备 paper-learning card：讲解难度、PDF/来源状态、章节覆盖、核心主张、需要回看的图表或公式、覆盖清单。"
                "全文抽取、引用核验、数学验证、复现和同行评审在被观测前不会被说成已完成。"
            ),
        ),
        "es": ChatCopy(
            headline="Puedo explicar este paper con la profundidad adecuada.",
            body=(
                "Prepararé una paper-learning card: nivel de explicación, estado del PDF/fuente, cobertura por sección, claims clave, "
                "figuras o ecuaciones a revisar y cobertura faltante. No diré que hubo extracción completa, verificación de citas, matemáticas, reproducción o revisión externa hasta observarlo."
            ),
        ),
        "fr": ChatCopy(
            headline="Je peux expliquer ce papier au bon niveau.",
            body=(
                "Je prépare une paper-learning card: niveau d'explication, état PDF/source, couverture des sections, thèses clés, "
                "figures ou équations à revoir et registre de couverture. Je ne dirai pas que l'extraction complète, les citations, les maths, la reproduction ou la revue sont validées avant observation."
            ),
        ),
        "de": ChatCopy(
            headline="Ich kann dieses Paper in der passenden Tiefe erklären.",
            body=(
                "Ich bereite eine paper-learning card vor: Erklärniveau, PDF-/Quellenstatus, Abschnittsabdeckung, Kernthesen, "
                "zu prüfende Abbildungen oder Formeln und Coverage-Ledger. Vollständige Extraktion, Zitatprüfung, mathematische Validierung, Reproduktion oder Review gelten erst nach Beobachtung."
            ),
        ),
    },
    "source_finder": {
        "en": ChatCopy(
            headline="I can turn this into a source acquisition plan.",
            body=(
                "I will prepare a source-finder plan: typed candidate categories, search/acquisition status, "
                "missing provenance, license or access checks, and the best downstream workflow. I will not claim "
                "web search, download, clone, extraction, verification, or downstream processing until observed."
            ),
        ),
        "ko": ChatCopy(
            headline="자료 탐색을 출처 확보 계획으로 정리할 수 있습니다.",
            body=(
                "source-finder 계획으로 논문, 링크, 데이터셋, 저장소, 발표자료 같은 후보 범주와 "
                "탐색/확보 상태, 출처·라이선스 확인, 다음에 넘길 workflow를 정리하겠습니다. "
                "실제 웹 검색, 다운로드, 클론, 추출, 검증, 후속 처리는 관측되기 전까지 완료됐다고 말하지 않습니다."
            ),
        ),
        "ja": ChatCopy(
            headline="探すべき資料を取得計画にできます。",
            body=(
                "source-finder plan として、論文、リンク、データセット、リポジトリ、公開スライドなどの候補カテゴリ、"
                "検索/取得状態、出典・ライセンス確認、次のworkflowを整理します。検索、ダウンロード、clone、抽出、検証は観測されるまで完了扱いしません。"
            ),
        ),
        "zh": ChatCopy(
            headline="我可以把资料查找变成来源获取计划。",
            body=(
                "我会准备 source-finder plan：论文、链接、数据集、代码库、公开演示等候选类别，搜索/获取状态，来源和许可检查，"
                "以及后续 workflow。网页搜索、下载、clone、抽取、验证和后续处理在被观测前不会被说成已完成。"
            ),
        ),
        "es": ChatCopy(
            headline="Puedo convertir esto en un plan de búsqueda de fuentes.",
            body=(
                "Prepararé un source-finder plan: categorías candidatas como papers, enlaces, datasets, repositorios o presentaciones, "
                "estado de búsqueda/adquisición, procedencia, licencia/acceso y el mejor workflow siguiente. No afirmaré búsqueda web, descarga, clone, extracción o verificación hasta observarlo."
            ),
        ),
        "fr": ChatCopy(
            headline="Je peux transformer cela en plan d'acquisition de sources.",
            body=(
                "Je prépare un source-finder plan: catégories candidates comme papiers, liens, datasets, dépôts ou présentations, "
                "état de recherche/acquisition, provenance, licence/accès et meilleur workflow suivant. Je ne dirai pas que la recherche web, le téléchargement, le clone, l'extraction ou la vérification sont faits avant observation."
            ),
        ),
        "de": ChatCopy(
            headline="Ich kann daraus einen Quellenbeschaffungsplan machen.",
            body=(
                "Ich bereite einen source-finder plan vor: Kandidaten wie Paper, Links, Datasets, Repositories oder Präsentationen, "
                "Such-/Beschaffungsstatus, Herkunft, Lizenz/Zugriff und nächster workflow. Websuche, Download, Clone, Extraktion und Verifikation gelten erst nach Beobachtung."
            ),
        ),
    },
    "web_research": {
        "en": ChatCopy(
            headline="I can gather source-backed current evidence for this.",
            body=(
                "I will keep this as Hermes-side research: define the source boundaries, freshness window, source diversity, "
                "citation confidence, and retrieval gaps before turning findings into a plan, report, or coding handoff. "
                "I will not claim sources were fetched or verified until observed."
            ),
        ),
        "ko": ChatCopy(
            headline="최신 근거 조사를 Hermes 연구 흐름으로 정리할 수 있습니다.",
            body=(
                "조사 범위, 최신성 기준, 출처 다양성, 인용 신뢰도, 검색 공백을 먼저 잡고 그 다음 "
                "계획, 리포트, 코딩 handoff로 넘기겠습니다. 실제 출처 수집이나 검증은 관측되기 전까지 완료됐다고 말하지 않습니다."
            ),
        ),
        "ja": ChatCopy(
            headline="最新根拠の調査として整理できます。",
            body=(
                "Hermes側の research として、出典範囲、鮮度、出典の多様性、引用信頼度、検索ギャップを先に定めます。"
                "出典取得や検証は観測されるまで完了扱いせず、その後に計画、レポート、coding handoffへ渡します。"
            ),
        ),
        "zh": ChatCopy(
            headline="我可以按有来源支撑的最新研究来整理。",
            body=(
                "我会把它作为 Hermes 侧 research：先定义来源边界、时效窗口、来源多样性、引用可信度和检索缺口，"
                "再把发现转成计划、报告或 coding handoff。来源抓取或验证在被观测前不会被说成已完成。"
            ),
        ),
        "es": ChatCopy(
            headline="Puedo reunir evidencia actual con fuentes.",
            body=(
                "Lo trataré como research dentro de Hermes: límites de fuente, ventana de actualidad, diversidad, confianza de citas y huecos de búsqueda "
                "antes de convertir hallazgos en plan, reporte o coding handoff. No afirmaré que las fuentes fueron obtenidas o verificadas hasta observarlo."
            ),
        ),
        "fr": ChatCopy(
            headline="Je peux rassembler des preuves actuelles sourcées.",
            body=(
                "Je garde cela comme research côté Hermes: périmètre des sources, fraîcheur, diversité, confiance des citations et trous de recherche "
                "avant de transformer les résultats en plan, rapport ou coding handoff. Je ne dirai pas que les sources sont récupérées ou vérifiées avant observation."
            ),
        ),
        "de": ChatCopy(
            headline="Ich kann aktuelle, quellenbasierte Evidenz vorbereiten.",
            body=(
                "Ich behandle das als Hermes-side research: Quellenrahmen, Aktualität, Quellenvielfalt, Zitiervertrauen und Suchlücken zuerst, "
                "danach Plan, Bericht oder coding handoff. Quellenabruf oder Verifikation gelten erst nach Beobachtung."
            ),
        ),
    },
    "agent_ops_review": {
        "en": ChatCopy(
            headline="Progress, blockers, and throughput need a manager view.",
            body=(
                "I will show quality gates, current gaps, blockers, next actions, and throughput levers "
                "without asking the user to approve shell catalog commands."
            ),
        ),
        "ko": ChatCopy(
            headline="지금 상황을 한눈에 볼 수 있게 정리하겠습니다.",
            body=(
                "현재 workflow 상태, 막힌 지점, 다음 행동, 품질 게이트, 처리량을 관리자 관점으로 보여드리겠습니다. "
                "`omh list` 같은 shell 명령 승인을 먼저 요구하지 않고, 실행·검증·CI·머지는 관측된 증거가 있을 때만 완료로 말합니다."
            ),
        ),
        "ja": ChatCopy(
            headline="現在の状況をひと目で分かる形に整理します。",
            body=(
                "workflow 状態、ブロッカー、次の action、品質ゲート、throughput を管理者視点で表示します。"
                "shell command の承認を先に求めず、実行、検証、CI、merge は観測された証拠がある時だけ完了扱いします。"
            ),
        ),
        "zh": ChatCopy(
            headline="我会把当前进展整理成一张状态视图。",
            body=(
                "我会从管理视角展示 workflow 状态、阻塞点、下一步、质量 gate 和吞吐量。"
                "不会先要求批准 shell command；执行、验证、CI 和 merge 只有在有观测证据时才会说成完成。"
            ),
        ),
        "es": ChatCopy(
            headline="Puedo ordenar el estado actual en una vista clara.",
            body=(
                "Mostraré estado del workflow, bloqueos, siguiente acción, quality gates y throughput desde una vista de operador. "
                "No pediré aprobar un shell command primero; ejecución, verificación, CI y merge solo cuentan como hechos con evidencia observada."
            ),
        ),
        "fr": ChatCopy(
            headline="Je peux résumer l'état actuel dans une vue claire.",
            body=(
                "Je montre l'état du workflow, les blocages, la prochaine action, les quality gates et le throughput côté opérateur. "
                "Je ne demande pas d'abord une validation de shell command; exécution, vérification, CI et merge ne sont confirmés qu'avec preuve observée."
            ),
        ),
        "de": ChatCopy(
            headline="Ich kann den aktuellen Stand übersichtlich darstellen.",
            body=(
                "Ich zeige workflow-Status, Blocker, nächste Aktion, Quality Gates und Durchsatz aus Operator-Sicht. "
                "Ich verlange nicht zuerst eine shell command Freigabe; Ausführung, Verifikation, CI und Merge gelten nur mit beobachteter Evidenz."
            ),
        ),
    },
    "workflow_learning_missed_route": {
        "en": ChatCopy(
            headline="I can record this missed OMH route.",
            body=(
                "I will treat this as missed-route feedback: record a metadata-only trace, create a reviewable "
                "missed-route bundle, add or request a minimized regression fixture, and keep any routing or skill "
                "change behind human review."
            ),
        ),
        "ko": ChatCopy(
            headline="놓친 OMH 라우팅을 학습 후보로 기록할 수 있습니다.",
            body=(
                "이 요청을 missed-route 피드백으로 다루겠습니다. 원문을 그대로 저장하지 않고 "
                "메타데이터 trace와 리뷰 가능한 bundle을 만들고, 최소 회귀 케이스를 추가하거나 요청합니다. "
                "라우팅/스킬 변경은 사람 리뷰 뒤에만 반영합니다."
            ),
        ),
        "ja": ChatCopy(
            headline="見逃した OMH route を改善候補として記録できます。",
            body="これは missed-route feedback として扱い、raw promptを保存せずmetadata trace、レビュー可能なbundle、最小回帰ケースを用意します。routingやskill変更は人のレビュー後だけです。",
        ),
        "zh": ChatCopy(
            headline="我可以把这次漏掉的 OMH route 记录为改进候选。",
            body="我会把它作为 missed-route feedback：不保存原始 prompt，只记录 metadata trace、可 review 的 bundle 和最小回归用例。routing 或 skill 改动仍需要人工 review。",
        ),
        "es": ChatCopy(
            headline="Puedo registrar esta ruta OMH perdida.",
            body="Lo trataré como missed-route feedback: metadata trace sin prompt crudo, bundle revisable y caso mínimo de regresión. Cualquier cambio de routing o skill queda detrás de revisión humana.",
        ),
        "fr": ChatCopy(
            headline="Je peux enregistrer cette route OMH manquée.",
            body="Je traite cela comme missed-route feedback: metadata trace sans prompt brut, bundle révisable et cas de régression minimal. Tout changement de routing ou skill reste soumis à revue humaine.",
        ),
        "de": ChatCopy(
            headline="Ich kann diese verpasste OMH route erfassen.",
            body="Ich behandle das als missed-route feedback: metadata trace ohne raw prompt, reviewbares bundle und minimaler Regressionstest. Routing- oder Skill-Änderungen bleiben hinter Human Review.",
        ),
    },
    "workflow_learning_readiness": {
        "en": ChatCopy(
            headline="I can inspect this workflow for learning readiness.",
            body=(
                "I will turn the workflow attempt into learning material without storing raw prompts: "
                "record the trace, run deterministic evals, add a regression case, audit readiness, "
                "and export a redacted review bundle when useful. Any skill or routing improvement still needs human review."
            ),
        ),
        "ko": ChatCopy(
            headline="이 workflow가 개선 가능한지 점검할 수 있습니다.",
            body=(
                "workflow 실행을 학습 재료로 정리하겠습니다. raw prompt를 저장하지 않고 trace, deterministic eval, "
                "회귀 케이스, readiness audit, redacted review bundle을 만들며, 스킬이나 라우팅 개선은 여전히 사람 리뷰가 필요합니다."
            ),
        ),
        "ja": ChatCopy(
            headline="この workflow を学習可能か点検できます。",
            body="raw promptを保存せず、trace、deterministic eval、回帰ケース、readiness audit、redacted review bundleに整理します。skillやrouting改善は人のレビューが必要です。",
        ),
        "zh": ChatCopy(
            headline="我可以检查这个 workflow 是否适合改进。",
            body="我会在不保存原始 prompt 的前提下整理 trace、deterministic eval、回归用例、readiness audit 和 redacted review bundle。skill 或 routing 改进仍需人工 review。",
        ),
        "es": ChatCopy(
            headline="Puedo revisar si este workflow está listo para aprender.",
            body="Sin guardar prompts crudos, registraré trace, deterministic eval, caso de regresión, readiness audit y redacted review bundle. Mejoras de skill o routing requieren revisión humana.",
        ),
        "fr": ChatCopy(
            headline="Je peux vérifier si ce workflow peut s'améliorer.",
            body="Sans stocker de prompt brut, je prépare trace, deterministic eval, cas de régression, readiness audit et redacted review bundle. Toute amélioration de skill ou routing exige une revue humaine.",
        ),
        "de": ChatCopy(
            headline="Ich kann prüfen, ob dieser workflow lernbereit ist.",
            body="Ohne raw prompts zu speichern, erstelle ich trace, deterministic eval, Regression Case, readiness audit und redacted review bundle. Skill- oder Routing-Verbesserungen brauchen Human Review.",
        ),
    },
    "clarify": {
        "en": ChatCopy(
            headline="I need one clarification before routing this.",
            body="Please confirm the intended workflow before I continue.",
        ),
        "ko": ChatCopy(
            headline="라우팅 전에 한 가지 확인이 필요합니다.",
            body="라우팅 전에 목표를 조금 더 확인해야 합니다. 원하는 결과, 입력 자료, 멈춰야 할 기준을 한 문장으로 알려주세요.",
        ),
        "ja": ChatCopy(headline="route 前に一つ確認が必要です。", body="続ける前に、欲しい結果、入力資料、止める条件を一文で教えてください。"),
        "zh": ChatCopy(headline="route 前我需要再确认一点。", body="继续前，请用一句话说明目标、输入材料和停止条件。"),
        "es": ChatCopy(headline="Necesito una aclaración antes de enrutar.", body="Confirma en una frase el resultado, los insumos y la condición de parada."),
        "fr": ChatCopy(headline="J'ai besoin d'une précision avant la route.", body="Indiquez en une phrase le résultat voulu, les entrées et la condition d'arrêt."),
        "de": ChatCopy(headline="Vor dem Routing brauche ich eine Klärung.", body="Bitte nenne Ergebnis, Eingaben und Stop-Bedingung in einem Satz."),
    },
    "file_lookup": {
        "en": ChatCopy(
            headline="This looks like a file or text lookup.",
            body="Answer this as a file or text lookup, or ask for the target file/path if it is missing.",
        ),
        "ko": ChatCopy(
            headline="파일이나 텍스트 확인 요청으로 보입니다.",
            body="파일/텍스트 확인으로 바로 답하거나, 대상 파일·경로가 없으면 먼저 물어보세요. OMH workflow 실행은 시작하지 않습니다.",
        ),
        "ja": ChatCopy(headline="ファイルまたはテキスト確認に見えます。", body="対象ファイル/パスがあれば直接確認し、なければ先に尋ねます。OMH workflowは開始しません。"),
        "zh": ChatCopy(headline="这看起来是文件或文本查找。", body="如果有目标文件/路径就直接回答；缺少目标时先询问。不会启动 OMH workflow。"),
        "es": ChatCopy(headline="Parece una consulta de archivo o texto.", body="Responde como lookup de archivo/texto, o pide la ruta si falta. No abras un OMH workflow."),
        "fr": ChatCopy(headline="Cela ressemble à une vérification de fichier ou texte.", body="Répondez comme lookup fichier/texte, ou demandez le chemin si absent. Ne lancez pas de workflow OMH."),
        "de": ChatCopy(headline="Das wirkt wie eine Datei- oder Textsuche.", body="Antworte als Datei-/Text-Lookup oder frage nach dem Pfad. Kein OMH workflow starten."),
    },
    "direct_answer": {
        "en": ChatCopy(
            headline="This does not need an OMH workflow.",
            body="Answer directly in the current chat; do not open an OMH workflow unless the user asks for one.",
        ),
        "ko": ChatCopy(
            headline="이건 OMH workflow 없이 바로 답하면 됩니다.",
            body="현재 채팅에서 바로 답하세요. 사용자가 직접 요청하지 않는 한 OMH workflow, picker, coding handoff를 열지 않습니다.",
        ),
        "ja": ChatCopy(headline="これは OMH workflow なしで直接答えられます。", body="このチャットで直接答えてください。ユーザーが求めない限りworkflow、picker、coding handoffは開きません。"),
        "zh": ChatCopy(headline="这个不需要 OMH workflow。", body="直接在当前聊天中回答。除非用户要求，不要打开 workflow、picker 或 coding handoff。"),
        "es": ChatCopy(headline="Esto no necesita un OMH workflow.", body="Responde directamente en el chat actual; no abras workflow, picker ni coding handoff salvo que el usuario lo pida."),
        "fr": ChatCopy(headline="Cela ne nécessite pas de workflow OMH.", body="Répondez directement dans ce chat; n'ouvrez pas de workflow, picker ou coding handoff sauf demande explicite."),
        "de": ChatCopy(headline="Dafür braucht es keinen OMH workflow.", body="Direkt im aktuellen Chat antworten; workflow, picker oder coding handoff nur öffnen, wenn der Nutzer es verlangt."),
    },
    "generic_clarify": {
        "en": ChatCopy(
            headline="I need to understand the goal before routing this.",
            body="Tell me the outcome you want, and I will choose the right workflow.",
        ),
        "ko": ChatCopy(
            headline="라우팅 전에 목표를 조금 더 알아야 합니다.",
            body="원하는 결과를 한 문장으로 알려주면, 그에 맞는 workflow를 고르겠습니다.",
        ),
        "ja": ChatCopy(headline="route 前に目標をもう少し知る必要があります。", body="望む結果を一文で教えてください。適切なworkflowを選びます。"),
        "zh": ChatCopy(headline="route 前我需要先理解目标。", body="请用一句话说明你想要的结果，我会选择合适的 workflow。"),
        "es": ChatCopy(headline="Necesito entender el objetivo antes de enrutar.", body="Dime en una frase el resultado que quieres y elegiré el workflow adecuado."),
        "fr": ChatCopy(headline="Je dois comprendre l'objectif avant la route.", body="Dites en une phrase le résultat voulu et je choisirai le bon workflow."),
        "de": ChatCopy(headline="Vor dem Routing muss ich das Ziel verstehen.", body="Sag mir das gewünschte Ergebnis in einem Satz; ich wähle den passenden workflow."),
    },
}


def chat_copy(copy_id: str, *, locale: str | None = None, korean: bool | None = None) -> ChatCopy:
    selected_locale = _normalize_locale(locale, korean=korean)
    copy = _CARD_COPY[copy_id]
    return copy.get(selected_locale) or copy["en"]


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
