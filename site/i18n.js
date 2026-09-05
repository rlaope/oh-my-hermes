/*!
 * Oh My Hermes - site copy in en / ko / ja / zh.
 * Keys map 1:1 to [data-i18n] / [data-i18n-html] / [data-i18n-attr] in the markup.
 */
window.OMH_I18N = {
  meta: {
    en: { label: "English", short: "EN", htmlLang: "en" },
    ko: { label: "한국어", short: "KO", htmlLang: "ko" },
    ja: { label: "日本語", short: "JA", htmlLang: "ja" },
    zh: { label: "中文", short: "ZH", htmlLang: "zh" }
  },

  strings: {
    /* ---------------------------------------------------------------- nav */
    "nav.workflows": { en: "Workflows", ko: "워크플로", ja: "ワークフロー", zh: "工作流" },
    "nav.executors": { en: "Executors", ko: "실행 주체", ja: "実行エージェント", zh: "执行方" },
    "nav.capabilities": { en: "Capabilities", ko: "역량", ja: "ケイパビリティ", zh: "能力" },
    "nav.routing": { en: "Routing", ko: "라우팅", ja: "ルーティング", zh: "路由" },
    "nav.memory": { en: "Memory", ko: "메모리", ja: "メモリ", zh: "记忆" },
    "nav.install": { en: "Install", ko: "설치", ja: "インストール", zh: "安装" },
    "nav.docs": { en: "Docs", ko: "문서", ja: "ドキュメント", zh: "文档" },
    "nav.lang": { en: "Change language", ko: "언어 변경", ja: "言語を変更", zh: "切换语言" },
    "nav.skip": { en: "Skip to content", ko: "본문으로 건너뛰기", ja: "本文へスキップ", zh: "跳转到正文" },

    /* --------------------------------------------------------------- hero */
    "hero.badge": {
      en: "For Hermes Agent · v2.0.1",
      ko: "Hermes Agent 전용 · v2.0.1",
      ja: "Hermes Agent のための · v2.0.1",
      zh: "为 Hermes Agent 打造 · v2.0.1"
    },
    "hero.tagline": {
      en: 'Power intelligence and <em>agentic memory</em> for Hermes Agent.',
      ko: 'Hermes Agent의 파워 인텔리전스, 그리고 <em>에이전틱 메모리</em>.',
      ja: 'Hermes Agent のパワー・インテリジェンスと<em>エージェンティック・メモリ</em>。',
      zh: 'Hermes Agent 的强力智能与<em>智能体记忆</em>。'
    },
    "hero.lead": {
      en: "One install. Anyone runs Hermes Agent professionally.",
      ko: "설치 한 번. 누구나 Hermes Agent를 프로페셔널하게.",
      ja: "インストール一回。誰でも Hermes Agent をプロフェッショナルに。",
      zh: "安装一次，任何人都能专业地驾驭 Hermes Agent。"
    },
    "hero.cta.primary": { en: "Get started", ko: "시작하기", ja: "はじめる", zh: "开始使用" },
    "hero.cta.github": { en: "View on GitHub", ko: "GitHub에서 보기", ja: "GitHub で見る", zh: "在 GitHub 上查看" },
    "hero.copy": { en: "Copy", ko: "복사", ja: "コピー", zh: "复制" },
    "hero.copied": { en: "Copied", ko: "복사됨", ja: "コピー済み", zh: "已复制" },

    "stat.skills": { en: "installable skills", ko: "설치형 스킬", ja: "スキル", zh: "可安装技能" },
    "stat.workflows": { en: "ulw workflows", ko: "ulw 워크플로", ja: "ulw ワークフロー", zh: "ulw 工作流" },
    "stat.families": { en: "capability families", ko: "역량 패밀리", ja: "ファミリー", zh: "能力家族" },
    "stat.langs": { en: "languages routed", ko: "라우팅 언어", ja: "対応言語", zh: "路由语言" },

    /* ------------------------------------------------------------ marquee */
    "marquee.a": { en: "Evidence has a boundary", ko: "증거에는 경계가 있다", ja: "エビデンスには境界がある", zh: "证据自有边界" },
    "marquee.b": { en: "Executor neutral", ko: "실행 주체 중립", ja: "実行主体に中立", zh: "执行方中立" },
    "marquee.c": { en: "Local contracts", ko: "로컬 계약", ja: "ローカル契約", zh: "本地契约" },
    "marquee.d": { en: "Never patches Hermes", ko: "Hermes를 패치하지 않음", ja: "Hermes にパッチしない", zh: "绝不修改 Hermes" },

    /* ---------------------------------------------------------- executors */
    "exec.kicker": { en: "Orchestration", ko: "오케스트레이션", ja: "オーケストレーション", zh: "编排" },
    "exec.title": {
      en: "Hermes conducts. Your coding agent plays.",
      ko: "Hermes가 지휘하고, 코딩 에이전트가 연주합니다.",
      ja: "Hermes が指揮し、コーディングエージェントが演奏する。",
      zh: "Hermes 指挥，你的编码智能体演奏。"
    },
    "exec.lead": {
      en: "OMH routes the request, prepares the work, and names who runs it.",
      ko: "OMH가 요청을 라우팅하고, 작업을 준비하고, 누가 실행할지 명시합니다.",
      ja: "OMH がリクエストをルーティングし、作業を用意し、実行者を明示します。",
      zh: "OMH 负责路由请求、准备工作，并指明由谁执行。"
    },
    "exec.hermes.name": { en: "Hermes Agent", ko: "Hermes Agent", ja: "Hermes Agent", zh: "Hermes Agent" },
    "exec.hermes.role": { en: "Host runtime", ko: "호스트 런타임", ja: "ホストランタイム", zh: "宿主运行时" },
    "exec.hermes.body": {
      en: "Chat, clarification, research, planning, status.",
      ko: "채팅, 명확화, 리서치, 계획, 상태.",
      ja: "チャット、明確化、リサーチ、計画、ステータス。",
      zh: "对话、澄清、研究、规划、状态。"
    },
    "exec.claude.name": { en: "Claude Code", ko: "Claude Code", ja: "Claude Code", zh: "Claude Code" },
    "exec.claude.role": { en: "Coding owner", ko: "코딩 소유자", ja: "コーディング・オーナー", zh: "编码归属方" },
    "exec.claude.body": {
      en: "Gets a prepared handoff with repo rules and the command that must pass.",
      ko: "저장소 규칙과 통과해야 할 명령이 담긴 핸드오프를 받습니다.",
      ja: "リポジトリ規則と通過必須コマンド入りのハンドオフを受け取ります。",
      zh: "拿到含仓库规则与必须通过命令的交接单。"
    },
    "exec.codex.name": { en: "Codex", ko: "Codex", ja: "Codex", zh: "Codex" },
    "exec.codex.role": { en: "Coding owner", ko: "코딩 소유자", ja: "コーディング・オーナー", zh: "编码归属方" },
    "exec.codex.body": {
      en: "Same contract, different runtime. No vendor is the default.",
      ko: "같은 계약, 다른 런타임. 기본값인 벤더는 없습니다.",
      ja: "同じ契約、異なるランタイム。デフォルトのベンダーはありません。",
      zh: "同一契约，不同运行时。没有默认厂商。"
    },
    "exec.pi.name": { en: "pi", ko: "pi", ja: "pi", zh: "pi" },
    "exec.pi.role": { en: "Coding owner", ko: "코딩 소유자", ja: "コーディング・オーナー", zh: "编码归属方" },
    "exec.pi.body": {
      en: "Discovered at setup. Routing follows what is actually installed.",
      ko: "설치 시점에 탐지. 라우팅은 실제 설치된 것을 따릅니다.",
      ja: "セットアップ時に検出。ルーティングは実際に入っているものに従います。",
      zh: "安装时被探测，路由依据真实安装清单。"
    },

    /* ------------------------------------------------------------- models */
    "models.kicker": { en: "Model pool", ko: "모델 풀", ja: "モデルプール", zh: "模型池" },
    "models.title": {
      en: "Bring the models you already pay for.",
      ko: "이미 쓰고 있는 모델을 그대로.",
      ja: "すでに使っているモデルをそのまま。",
      zh: "把你已经在用的模型直接接进来。"
    },
    "models.lead": {
      en: "Setup records what is reachable on this machine. Routing follows that inventory.",
      ko: "설치가 이 머신에서 닿는 모델을 기록하고, 라우팅은 그 인벤토리를 따릅니다.",
      ja: "セットアップが到達可能なモデルを記録し、ルーティングはそのインベントリに従います。",
      zh: "安装时记录本机可达的模型，路由随后依据这份清单。"
    },

    /* ---------------------------------------------------------- platforms */
    "plat.kicker": { en: "Surfaces", ko: "표면", ja: "サーフェス", zh: "触达面" },
    "plat.title": {
      en: "Wherever Hermes already talks.",
      ko: "Hermes가 이미 말하는 모든 곳에서.",
      ja: "Hermes がすでに話しているすべての場所で。",
      zh: "Hermes 已经在说话的每一个地方。"
    },
    "plat.cli": { en: "CLI", ko: "CLI", ja: "CLI", zh: "CLI" },
    "plat.desktop": { en: "Desktop", ko: "데스크톱", ja: "デスクトップ", zh: "桌面端" },
    "surf.cli.body": {
      en: "The control plane.",
      ko: "컨트롤 플레인.",
      ja: "コントロールプレーン。",
      zh: "控制面。"
    },
    "surf.desktop.body": {
      en: "Same catalog, same evidence rules.",
      ko: "같은 카탈로그, 같은 증거 규칙.",
      ja: "同じカタログ、同じエビデンス規則。",
      zh: "同一份目录，同一套证据规则。"
    },
    "surf.messenger.name": { en: "Messenger", ko: "메신저", ja: "メッセンジャー", zh: "即时通讯" },
    "surf.messenger.body": {
      en: "Cards stay readable where formatting is limited.",
      ko: "서식이 제한된 곳에서도 카드는 읽힙니다.",
      ja: "書式が限られる場所でもカードは読める。",
      zh: "排版受限处卡片依然可读。"
    },

    /* ---------------------------------------------------------------- ulw */
    "ulw.kicker": { en: "Flagship workflows", ko: "대표 워크플로", ja: "フラッグシップ", zh: "旗舰工作流" },
    "ulw.title": { en: "The ulw-* family.", ko: "ulw-* 패밀리.", ja: "ulw-* ファミリー。", zh: "ulw-* 家族。" },
    "ulw.lead": {
      en: "Nine long-horizon lanes. Say the trigger in normal language — Hermes routes the rest.",
      ko: "9개의 장기 레인. 평범한 말로 트리거만 말하면 나머지는 Hermes가 라우팅합니다.",
      ja: "9 の長期レーン。普通の言葉でトリガーを言えば、あとは Hermes がルーティング。",
      zh: "九条长周期车道。用日常语言说出触发词，其余交给 Hermes 路由。"
    },
    "ulw.trigger": { en: "Say", ko: "이렇게 말하세요", ja: "こう言う", zh: "这样说" },

    "ulw.context.title": { en: "Context", ko: "Context", ja: "Context", zh: "Context" },
    "ulw.context.tag": { en: "Terminology alignment", ko: "용어 정렬", ja: "用語アラインメント", zh: "术语对齐" },
    "ulw.context.body": {
      en: "Aligns the words a repository uses before plans and handoffs.",
      ko: "계획과 핸드오프 전에 저장소가 쓰는 용어부터 맞춥니다.",
      ja: "計画とハンドオフの前に、リポジトリが使う言葉を揃えます。",
      zh: "在计划与交接之前，先对齐仓库使用的词汇。"
    },
    "ulw.work.title": { en: "Ultrawork", ko: "Ultrawork", ja: "Ultrawork", zh: "Ultrawork" },
    "ulw.work.tag": { en: "Parallel delivery", ko: "병렬 전달", ja: "並列デリバリー", zh: "并行交付" },
    "ulw.work.body": {
      en: "Splits an accepted plan into disjoint lanes — owner, criteria, and verification per lane. Two lanes never edit the same file.",
      ko: "승인된 계획을 겹치지 않는 레인으로 분할 — 레인마다 소유자, 기준, 검증. 두 레인이 같은 파일을 건드리지 않습니다.",
      ja: "承認済み計画を重ならないレーンへ分割 — レーンごとにオーナー、基準、検証。二つのレーンが同じファイルを編集しません。",
      zh: "把已确认的计划切成互不重叠的车道 —— 每条有归属、标准与验证。两条车道绝不改同一个文件。"
    },
    "ulw.maestro.title": { en: "Maestro", ko: "Maestro", ja: "Maestro", zh: "Maestro" },
    "ulw.maestro.tag": { en: "External handoff", ko: "외부 핸드오프", ja: "外部ハンドオフ", zh: "外部交接" },
    "ulw.maestro.body": {
      en: "Runs the work on Claude Code or Codex, spawned live with a steerable session.",
      ko: "Claude Code 또는 Codex에서 작업을 실행 — 실시간으로 구동되고 세션을 조종할 수 있습니다.",
      ja: "Claude Code または Codex で作業を実行 — ライブで起動し、セッションを操作できます。",
      zh: "在 Claude Code 或 Codex 上运行任务 —— 实时启动，会话可操控。"
    },
    "ulw.plan.title": { en: "Ralplan", ko: "Ralplan", ja: "Ralplan", zh: "Ralplan" },
    "ulw.plan.tag": { en: "Reviewed plan", ko: "검토된 계획", ja: "レビュー済み計画", zh: "评审过的计划" },
    "ulw.plan.body": {
      en: "Consensus planning with review gates: facts, options, risks, acceptance criteria, handoff.",
      ko: "리뷰 게이트가 있는 합의 계획: 사실, 선택지, 리스크, 수용 기준, 핸드오프.",
      ja: "レビューゲート付き合意プランニング：事実、選択肢、リスク、受け入れ基準、ハンドオフ。",
      zh: "带评审关卡的共识规划：事实、方案、风险、验收标准、交接。"
    },
    "ulw.interview.title": { en: "Deep Interview", ko: "Deep Interview", ja: "Deep Interview", zh: "Deep Interview" },
    "ulw.interview.tag": { en: "Clarification", ko: "명확화", ja: "明確化", zh: "澄清" },
    "ulw.interview.body": {
      en: "One question at a time until the brief is clear. Six rounds max, clarity scored each round.",
      ko: "브리프가 명확해질 때까지 한 번에 한 질문. 최대 6라운드, 라운드마다 명확도 점수.",
      ja: "ブリーフが明確になるまで一度に一問。最大 6 ラウンド、毎回明確度をスコア。",
      zh: "一次一问，直到简报清晰。最多六轮，每轮标注清晰度。"
    },
    "ulw.loop.title": { en: "Loop", ko: "Loop", ja: "Loop", zh: "Loop" },
    "ulw.loop.tag": { en: "Goal loop", ko: "목표 루프", ja: "ゴールループ", zh: "目标循环" },
    "ulw.loop.body": {
      en: "Interview → plan → research → build → review, cycling until a real gate passes.",
      ko: "인터뷰 → 계획 → 리서치 → 빌드 → 리뷰. 진짜 게이트를 통과할 때까지 순환.",
      ja: "インタビュー → 計画 → リサーチ → ビルド → レビュー。本物のゲートを通るまで循環。",
      zh: "访谈 → 规划 → 研究 → 构建 → 评审，循环直到真正的关卡通过。"
    },
    "ulw.qa.title": { en: "UltraQA", ko: "UltraQA", ja: "UltraQA", zh: "UltraQA" },
    "ulw.qa.tag": { en: "Adversarial QA", ko: "적대적 QA", ja: "敵対的 QA", zh: "对抗式 QA" },
    "ulw.qa.body": {
      en: "Hostile scenarios, end-to-end runs, release QA, and fix loops — explicit and evidence-backed.",
      ko: "적대적 시나리오, E2E 실행, 릴리스 QA, 수정 루프 — 명시적이고 증거 기반.",
      ja: "敵対的シナリオ、E2E 実行、リリース QA、修正ループ — 明示的で証拠付き。",
      zh: "恶意场景、端到端跑通、发版 QA 与修复循环 —— 显式且有据可依。"
    },
    "ulw.research.title": { en: "Research", ko: "Research", ja: "Research", zh: "Research" },
    "ulw.research.tag": { en: "Decision grounding", ko: "의사결정 근거", ja: "意思決定の根拠", zh: "决策依据" },
    "ulw.research.body": {
      en: "Reference implementations at pinned refs, live web evidence with citations, verified claims.",
      ko: "실제 코드와 최신 웹 자료로 조사하고, 출처를 남기고, 의심스러운 주장은 검증합니다.",
      ja: "実際のコードと最新のウェブ情報で調査し、出典を残し、怪しい主張は裏取りします。",
      zh: "用真实代码和最新网页资料做调研，留下出处，可疑说法一定核实。"
    },
    "ulw.perf.title": { en: "Ultraperf", ko: "Ultraperf", ja: "Ultraperf", zh: "Ultraperf" },
    "ulw.perf.tag": { en: "Measured optimization", ko: "측정 기반 최적화", ja: "計測ベース最適化", zh: "以测量为准的优化" },
    "ulw.perf.body": {
      en: "Finds where the system is actually slow, leaking, or expensive — then fixes one measured hot path at a time.",
      ko: "시스템이 실제로 느리고 새고 비싼 곳을 찾아 — 측정된 핫패스를 하나씩 고칩니다.",
      ja: "実際に遅く、漏れ、高コストな箇所を特定し — 計測済みホットパスを一つずつ修正。",
      zh: "找出系统真正慢、漏、贵的地方 —— 然后逐条修复被测量过的热路径。"
    },

    /* ----------------------------------------------------------- families */
    "fam.kicker": { en: "Capability families", ko: "역량 패밀리", ja: "ファミリー", zh: "能力家族" },
    "fam.title": { en: "Start with the job.", ko: "할 일에서 시작합니다.", ja: "仕事から始める。", zh: "从要办的事开始。" },
    "fam.lead": {
      en: "116 skills behind seven human-readable families. The family is the front door.",
      ko: "사람이 읽는 7개 패밀리 뒤의 116개 스킬. 패밀리가 정문입니다.",
      ja: "人が読める 7 ファミリーの背後に 116 スキル。ファミリーが正面玄関。",
      zh: "七个人类可读的家族背后是 116 个技能。家族就是正门。"
    },
    "fam.head.cap": { en: "Capability", ko: "역량", ja: "ケイパビリティ", zh: "能力" },
    "fam.head.try": { en: "Try it with", ko: "이렇게 써보세요", ja: "使うスキル", zh: "试用技能" },
    "fam.head.what": { en: "What it does", ko: "무엇을 하나", ja: "何をするか", zh: "做什么" },
    "fam.clarify.name": { en: "Clarify and plan", ko: "명확화와 계획", ja: "明確化と計画", zh: "澄清与规划" },
    "fam.clarify.body": {
      en: "Ambiguous request → explicit goals, constraints, acceptance criteria, and a plan.",
      ko: "모호한 요청 → 명시적 목표, 제약, 수용 기준, 그리고 계획.",
      ja: "曖昧なリクエスト → 明示的な目標・制約・受け入れ基準・計画。",
      zh: "模糊请求 → 明确目标、约束、验收标准与计划。"
    },
    "fam.build.name": { en: "Build with leverage", ko: "레버리지 있는 실행", ja: "レバレッジのある実行", zh: "有杠杆地构建" },
    "fam.build.body": {
      en: "Fast parallel work through durable multi-step execution, ownership always visible.",
      ko: "빠른 병렬 작업부터 지속 실행까지, 소유권은 항상 보이게.",
      ja: "高速な並列作業から永続実行まで、オーナーシップは常に可視。",
      zh: "从快速并行到持久执行，归属始终可见。"
    },
    "fam.research.name": { en: "Research and learn", ko: "리서치와 학습", ja: "リサーチと学習", zh: "研究与学习" },
    "fam.research.body": {
      en: "Source-backed evidence with freshness and source-quality boundaries.",
      ko: "신선도와 출처 품질 경계를 지키는 출처 기반 증거.",
      ja: "鮮度と出典品質の境界を守る、出典付き証拠。",
      zh: "在新鲜度与来源质量边界内的有据证据。"
    },
    "fam.ship.name": { en: "Code and ship safely", ko: "안전한 코딩과 배포", ja: "安全にコードし出荷", zh: "安全地编码与发布" },
    "fam.ship.body": {
      en: "Executor-neutral coding work; review, QA, CI, and merge claims depend on observed evidence.",
      ko: "실행 주체 중립 코딩. 리뷰·QA·CI·머지 주장은 관측된 증거에 의존.",
      ja: "実行主体に中立なコーディング。レビュー・QA・CI・マージの主張は観測済み証拠に依存。",
      zh: "与执行方无关的编码；评审、QA、CI 与合并的结论都依赖被观测的证据。"
    },
    "fam.create.name": { en: "Create polished deliverables", ko: "완성도 높은 산출물", ja: "洗練された成果物", zh: "打磨成品交付物" },
    "fam.create.body": {
      en: "Websites, visuals, reports, decks, PDFs, posters — behind taste and render-quality gates.",
      ko: "웹사이트, 비주얼, 리포트, 덱, PDF, 포스터 — 취향과 렌더 품질 게이트 뒤에서.",
      ja: "ウェブ、ビジュアル、レポート、デッキ、PDF、ポスター — 美意識とレンダー品質のゲート付き。",
      zh: "网站、视觉、报告、演示、PDF、海报 —— 都要过审美与渲染质量关。"
    },
    "fam.memory.name": { en: "Remember and operate", ko: "기억하고 운영", ja: "記憶し運用する", zh: "记忆与运维" },
    "fam.memory.body": {
      en: "Review-first project memory, operational readiness, and the next repair action.",
      ko: "리뷰 우선 프로젝트 메모리, 운영 준비 상태, 다음 수리 행동.",
      ja: "レビュー優先のプロジェクトメモリ、運用準備状態、次の修復アクション。",
      zh: "评审优先的项目记忆、运维就绪度、下一步修复动作。"
    },
    "fam.connect.name": { en: "Connect with clear boundaries", ko: "경계가 분명한 연결", ja: "境界の明確な接続", zh: "边界清晰的连接" },
    "fam.connect.body": {
      en: "Checks a tool or connector is really available before work depends on it.",
      ko: "작업이 의존하기 전에 도구와 커넥터가 정말 되는지 확인.",
      ja: "作業が依存する前に、ツールやコネクタが本当に使えるか確認。",
      zh: "在工作依赖之前，先确认工具或连接器真的可用。"
    },

    /* ------------------------------------------------------------- memory */
    "mem.kicker": { en: "Agentic memory", ko: "에이전틱 메모리", ja: "エージェンティック・メモリ", zh: "智能体记忆" },
    "mem.title": { en: "Four layers, one café shift.", ko: "네 개의 층, 카페 한 타임.", ja: "四つの層、カフェの一シフト。", zh: "四个层级，一个咖啡馆班次。" },
    "mem.lead": {
      en: "Four layers, like a well-run café. Nothing important sits in one place.",
      ko: "잘 돌아가는 카페처럼 네 개의 층. 중요한 건 한 곳에만 있지 않습니다.",
      ja: "よく回るカフェのような四つの層。大事なものは一か所に置かない。",
      zh: "像一家运转良好的咖啡馆，分成四层。重要的东西不会只放一处。"
    },
    "mem.stack.label": { en: "Stack", ko: "스택", ja: "スタック", zh: "技术栈" },

    "mem.l0.meta": { en: "owner-written · always loaded", ko: "주인이 씀 · 항상 로드", ja: "オーナーが書く · 常時ロード", zh: "老板写 · 始终加载" },
    "mem.l0.title": { en: "House rules on the wall", ko: "벽에 붙은 가게 규칙", ja: "壁の店ルール", zh: "墙上的店规" },
    "mem.l0.metaphor": {
      en: "The owner writes it. Agents only read it.",
      ko: "주인이 씁니다. 에이전트는 읽기만.",
      ja: "オーナーが書く。エージェントは読むだけ。",
      zh: "老板来写，智能体只读。"
    },
    "mem.l0.stack": { en: "markdown context files", ko: "마크다운 컨텍스트 파일", ja: "Markdown コンテキスト", zh: "Markdown 上下文文件" },

    "mem.l1.meta": { en: "capped · fails loud", ko: "상한 있음 · 시끄럽게 실패", ja: "上限あり · 大声で失敗", zh: "有上限 · 大声失败" },
    "mem.l1.title": { en: "Laminated A4 by the register", ko: "계산대 옆 코팅 A4", ja: "レジ横のラミネート A4", zh: "收银台旁的过塑 A4" },
    "mem.l1.metaphor": {
      en: "One page. Full means the write is refused.",
      ko: "딱 한 장. 꽉 차면 쓰기 거부.",
      ja: "たった一枚。満杯なら書き込み拒否。",
      zh: "就一页。满了就拒绝写入。"
    },
    "mem.l1.stack": { en: "capped core memory (Letta / MemGPT)", ko: "상한형 코어 메모리 (Letta / MemGPT)", ja: "上限付きコアメモリ (Letta / MemGPT)", zh: "有上限的核心记忆 (Letta / MemGPT)" },

    "mem.l2.badge": { en: "The slot OMH fills", ko: "OMH가 채우는 자리", ja: "OMH のスロット", zh: "OMH 填的这一格" },
    "mem.l2.meta": { en: "review-first · TTL · budgeted", ko: "리뷰 우선 · TTL · 예산", ja: "レビュー優先 · TTL · 予算", zh: "评审优先 · TTL · 有预算" },
    "mem.l2.title": { en: "Labelled binder in the back room", ko: "뒷방의 라벨 바인더", ja: "奥のラベル付きバインダー", zh: "里屋贴标签的活页夹" },
    "mem.l2.metaphor": {
      en: "Hold the index. Open only the section you need.",
      ko: "목차만 외웁니다. 필요한 섹션만 펼칩니다.",
      ja: "索引だけ覚える。必要な節だけ開く。",
      zh: "只记索引，需要哪节翻哪节。"
    },
    "mem.l2.stack": { en: "Mem0 · Graphiti · Cognee · Letta archival", ko: "Mem0 · Graphiti · Cognee · Letta 아카이브", ja: "Mem0 · Graphiti · Cognee · Letta アーカイブ", zh: "Mem0 · Graphiti · Cognee · Letta 归档" },

    "mem.l3.meta": { en: "zero tokens until queried", ko: "검색 전까지 토큰 0", ja: "検索までトークン 0", zh: "不检索就不花 Token" },
    "mem.l3.title": { en: "Receipts in the storage room", ko: "창고의 영수증", ja: "倉庫のレシート", zh: "储藏室的小票" },
    "mem.l3.metaphor": {
      en: "Every message ever. Free until you search.",
      ko: "지금까지의 모든 메시지. 검색 전까진 공짜.",
      ja: "これまでの全メッセージ。検索するまで無料。",
      zh: "有史以来的每条消息。不搜就不花钱。"
    },
    "mem.l3.stack": { en: "FTS5 · BM25 + vector hybrid", ko: "FTS5 · BM25 + 벡터 하이브리드", ja: "FTS5 · BM25 + ベクトル", zh: "FTS5 · BM25 + 向量混合" },

    "mem.quote": {
      en: "A better binder beats a bigger page.",
      ko: "더 큰 종이보다 더 나은 바인더.",
      ja: "大きな紙より、良いバインダー。",
      zh: "更好的活页夹，胜过更大的纸。"
    },
    "mem.rules.title": {
      en: "Two rules keep a ten-hour loop alive.",
      ko: "10시간 루프를 살리는 두 규칙.",
      ja: "10 時間ループを生かす二つの規則。",
      zh: "两条规则，撑住十小时循环。"
    },
    "mem.rule1": {
      en: "Evict on provable redundancy only — the oldest entry is usually the architecture decision that still holds.",
      ko: "증명된 중복만 제거 — 가장 오래된 항목은 대개 아직 유효한 아키텍처 결정입니다.",
      ja: "証明済みの冗長のみ退避 — 最古のエントリは大抵まだ有効なアーキテクチャ決定。",
      zh: "只淘汰可证明的冗余 —— 最老的一条往往是仍然成立的架构决策。"
    },
    "mem.rule2": {
      en: "Consolidate on observed compaction, not turn count.",
      ko: "통합은 턴 수가 아니라 관측된 컴팩션에서.",
      ja: "統合はターン数ではなく、観測されたコンパクションで。",
      zh: "整合看观测到的压缩，不看轮次。"
    },
    "mem.wrap.title": { en: "OMH wraps all four layers.", ko: "OMH는 네 층 전부를 감쌉니다.", ja: "OMH は四層すべてをラップ。", zh: "OMH 把四层全部包住。" },
    "mem.wrap.a": {
      en: "Recall arrives on prefetch.",
      ko: "리콜은 프리페치로 도착.",
      ja: "リコールはプリフェッチで届く。",
      zh: "召回通过预取送达。"
    },
    "mem.wrap.b": {
      en: "Subagents read, never write.",
      ko: "서브에이전트는 읽기만, 쓰기 금지.",
      ja: "サブエージェントは読むだけ。",
      zh: "子智能体只读，绝不写。"
    },
    "mem.wrap.c": {
      en: "prepared ≠ observed, at the schema level.",
      ko: "prepared ≠ observed, 스키마 수준에서.",
      ja: "prepared ≠ observed、スキーマレベルで。",
      zh: "prepared ≠ observed，落在模式层。"
    },

    /* ----------------------------------------------------------- evidence */
    "ev.kicker": { en: "Evidence boundary", ko: "증거 경계", ja: "エビデンス境界", zh: "证据边界" },
    "ev.title": { en: "Measure each claim at its own boundary.", ko: "각 주장은 그 경계에서 측정합니다.", ja: "各主張はその境界で測る。", zh: "每个断言都在自己的边界上度量。" },
    "ev.lead": {
      en: "OMH never reports that work happened unless it watched it happen. Every status has two parts: the stage, and how sure OMH is.",
      ko: "OMH는 직접 지켜본 일이 아니면 일어났다고 보고하지 않습니다. 모든 상태는 두 부분입니다: 단계, 그리고 OMH의 확신.",
      ja: "OMH は自分で見届けていない作業を「起きた」と報告しません。すべてのステータスは、段階と確信度の二つで構成されます。",
      zh: "OMH 从不报告它没亲眼看到的工作。每个状态都有两部分：阶段，以及 OMH 的把握程度。"
    },
    "ev.plan.body": {
      en: "A prompt or plan is ready. Nothing has run yet.",
      ko: "프롬프트나 계획이 준비됨. 아직 아무것도 실행 안 됨.",
      ja: "プロンプトや計画が準備済み。まだ何も実行されていない。",
      zh: "提示词或计划已就绪。还什么都没跑。"
    },
    "ev.running.body": {
      en: "An executor is running now, and OMH is watching it.",
      ko: "실행자가 지금 돌고 있고, OMH가 지켜보는 중.",
      ja: "実行者がいま動いていて、OMH が監視中。",
      zh: "执行者正在运行，OMH 正在盯着。"
    },
    "ev.reported.body": {
      en: "The executor said it finished. Nobody checked the result.",
      ko: "실행자가 끝났다고 말했을 뿐. 아무도 결과를 확인 안 함.",
      ja: "実行者が終わったと言っただけ。誰も結果を確認していない。",
      zh: "执行者说做完了。没人核对过结果。"
    },
    "ev.verified.body": {
      en: "A test, review, or CI gate actually passed.",
      ko: "테스트, 리뷰, CI 게이트가 실제로 통과됨.",
      ja: "テスト・レビュー・CI ゲートが実際に通過。",
      zh: "测试、评审或 CI 关卡真正通过了。"
    },
    "ev.note": {
      en: "\"Reported done\" is not \"verified\" — most tools spell both \"complete\".",
      ko: "\"끝났다고 말함\"과 \"검증됨\"은 다릅니다 — 대부분의 도구는 둘 다 \"완료\"라고 씁니다.",
      ja: "「終わったと言った」と「検証済み」は別物 — 多くのツールは両方を「完了」と表記します。",
      zh: "\"说做完了\"不等于\"已验证\" —— 多数工具把两者都写成\"完成\"。"
    },

    /* ------------------------------------------------------------ install */
    "install.kicker": { en: "Install", ko: "설치", ja: "インストール", zh: "安装" },
    "install.title": {
      en: "Install your way. Set up once.",
      ko: "원하는 방식으로 설치하고, 설정은 한 번.",
      ja: "好きな方法でインストール。セットアップは一度だけ。",
      zh: "按你的方式安装，只需设置一次。"
    },
    "install.lead": {
      en: "Choose a package manager or platform installer. Doctor stays a separate check.",
      ko: "패키지 관리자나 플랫폼 설치 프로그램을 고르세요. Doctor는 별도 확인 단계입니다.",
      ja: "パッケージマネージャーか OS 用インストーラーを選択。Doctor は別の確認手順です。",
      zh: "选择包管理器或平台安装程序。Doctor 是单独的验证步骤。"
    },
    "install.availability.note": {
      en: "Homebrew, Bun, and npm package-manager installs are public as of v1.0.6.",
      ko: "Homebrew, Bun, npm 패키지 관리자 설치가 v1.0.6부터 공개되었습니다.",
      ja: "Homebrew、Bun、npm のパッケージマネージャー経由のインストールは v1.0.6 から公開されています。",
      zh: "Homebrew、Bun 与 npm 包管理器安装方式已随 v1.0.6 正式公开。"
    },
    "install.step1": { en: "Install the command", ko: "명령어 설치", ja: "コマンドをインストール", zh: "安装命令行" },
    "install.method.brew": { en: "Homebrew", ko: "Homebrew", ja: "Homebrew", zh: "Homebrew" },
    "install.method.bun": { en: "Bun · recommended", ko: "Bun · 권장", ja: "Bun · 推奨", zh: "Bun · 推荐" },
    "install.method.npm": { en: "npm", ko: "npm", ja: "npm", zh: "npm" },
    "install.method.unix": { en: "macOS · Linux", ko: "macOS · Linux", ja: "macOS · Linux", zh: "macOS · Linux" },
    "install.method.windows": { en: "Windows", ko: "Windows", ja: "Windows", zh: "Windows" },
    "install.step1.note": {
      en: "Pick one installation method.",
      ko: "설치 방법 하나를 고르세요.",
      ja: "インストール方法を一つ選択。",
      zh: "选择一种安装方式。"
    },
    "install.step2": { en: "Set it up", ko: "설정하기", ja: "セットアップ", zh: "完成设置" },
    "install.step2.note": {
      en: "The whole setup. It records which coding agents and models are actually installed.",
      ko: "설정은 이게 전부. 실제 설치된 코딩 에이전트와 모델을 기록합니다.",
      ja: "セットアップはこれで全部。実際に入っているエージェントとモデルを記録。",
      zh: "设置到此为止。它会记录真实装好的编码智能体与模型。"
    },
    "install.doctor.title": {
      en: "Verify separately",
      ko: "별도로 확인",
      ja: "別の手順で確認",
      zh: "单独验证"
    },
    "install.doctor.note": {
      en: "Run doctor after setup to verify or troubleshoot.",
      ko: "설정 후 doctor로 설치를 확인하거나 문제를 해결하세요.",
      ja: "セットアップ後に doctor で確認またはトラブルシューティング。",
      zh: "设置后运行 doctor 进行验证或故障排查。"
    },
    "install.update.note": {
      en: "Refresh later with",
      ko: "나중에 다음 명령으로 갱신:",
      ja: "後で次のコマンドで更新:",
      zh: "之后使用此命令更新："
    },
    "install.step3": { en: "Or ask your agent", ko: "아니면 에이전트에게", ja: "またはエージェントに頼む", zh: "或者交给你的智能体" },
    "install.step3.note": {
      en: "Paste into Claude Code, Codex, or any agent CLI. It installs, verifies, and reports back.",
      ko: "Claude Code, Codex, 아무 에이전트 CLI에 붙여넣으세요. 설치하고, 검증하고, 보고합니다.",
      ja: "Claude Code、Codex、任意のエージェント CLI に貼り付け。インストールし、検証し、報告。",
      zh: "粘贴进 Claude Code、Codex 或任意智能体 CLI。它会安装、验证并回报。"
    },
    "install.tab.unix": { en: "macOS · Linux", ko: "macOS · Linux", ja: "macOS · Linux", zh: "macOS · Linux" },
    "install.tab.win": { en: "Windows", ko: "Windows", ja: "Windows", zh: "Windows" },
    "install.prompt.label": { en: "prompt for your agent", ko: "에이전트용 프롬프트", ja: "エージェント用プロンプト", zh: "给智能体的提示词" },

    /* -------------------------------------------------------------- routing */
    "route.kicker": { en: "Model routing", ko: "모델 라우팅", ja: "モデル・ルーティング", zh: "模型路由" },
    "route.title": {
      en: "Set the model per kind of work.",
      ko: "작업 종류마다 모델을 지정합니다.",
      ja: "作業の種類ごとにモデルを指定します。",
      zh: "按工作类型指定模型。"
    },
    "route.lead": {
      en: "Nine editable categories. Missing models are skipped, not fatal.",
      ko: "편집 가능한 9개 카테고리. 없는 모델은 건너뛸 뿐, 설치를 막지 않습니다.",
      ja: "編集可能な 9 カテゴリ。持っていないモデルはスキップされ、失敗にはなりません。",
      zh: "九个可编辑类别。缺少的模型只会被跳过，不会导致失败。"
    },
    "route.edit.tag": { en: "Editable", ko: "편집 가능", ja: "編集可能", zh: "可编辑" },
    "route.edit.title": {
      en: "Your order, not ours.",
      ko: "우선순위는 사용자가 정합니다.",
      ja: "優先順位は利用者が決めます。",
      zh: "顺序由你决定。"
    },
    "route.edit.body": {
      en: "Each category is an ordered candidate chain. Your override replaces the chains it names and leaves the rest alone.",
      ko: "각 카테고리는 순서가 있는 후보 목록입니다. 오버라이드는 지정한 목록만 교체하고 나머지는 그대로 둡니다.",
      ja: "各カテゴリは順序付きの候補チェーンです。オーバーライドは指定したチェーンだけを置き換え、他はそのまま残します。",
      zh: "每个类别都是有序候选链。覆盖文件只替换它指名的链，其余保持不变。"
    },
    "route.flex.tag": { en: "Flexible", ko: "유연함", ja: "柔軟", zh: "灵活" },
    "route.flex.title": {
      en: "You do not need every model.",
      ko: "모든 모델을 갖출 필요는 없습니다.",
      ja: "すべてのモデルを揃える必要はありません。",
      zh: "你不需要拥有全部模型。"
    },
    "route.flex.body": {
      en: "A candidate you have not configured is skipped and the next eligible one is selected. No eligible candidate is recorded plainly and never blocks the install.",
      ko: "설정하지 않은 후보는 건너뛰고 다음 후보를 선택합니다. 적합한 후보가 없으면 그대로 기록될 뿐, 설치를 막지 않습니다.",
      ja: "未設定の候補はスキップされ、次の候補が選ばれます。該当候補がない場合はそのまま記録され、インストールを妨げません。",
      zh: "未配置的候选会被跳过并选择下一个。若没有可用候选，会如实记录，且不会阻断安装。"
    },
    "route.state.resolved": {
      en: "A confirmed model was selected.",
      ko: "확인된 모델이 선택되었습니다.",
      ja: "確認済みのモデルが選択されました。",
      zh: "已选中一个确认可用的模型。"
    },
    "route.state.choice": {
      en: "The model you named explicitly is unavailable. Nothing is substituted.",
      ko: "직접 지정한 모델을 쓸 수 없습니다. 임의로 대체하지 않습니다.",
      ja: "明示指定したモデルが利用できません。勝手な代替は行いません。",
      zh: "你明确指定的模型不可用，不会自动替换。"
    },
    "route.state.owner_default": {
      en: "No eligible candidate. The selected owner keeps its default model.",
      ko: "적합한 후보가 없습니다. 선택한 owner의 기본 모델을 유지합니다.",
      ja: "該当する候補がありません。選択した owner のデフォルトモデルを維持します。",
      zh: "没有符合条件的候选。保留所选 owner 的默认模型。"
    },
    "route.owner.tag": { en: "Owners", ko: "소유 주체", ja: "担当", zh: "归属" },
    "route.owner.title": {
      en: "Hermes native, or external Maestro.",
      ko: "Hermes 네이티브 또는 외부 Maestro.",
      ja: "Hermes ネイティブか、外部の Maestro か。",
      zh: "Hermes 原生，或外部 Maestro。"
    },
    "route.owner.body": {
      en: "Hermes-native work stays with Hermes and its own config and auth commands. External owners are coordinated by Maestro, which prepares and reports but never executes.",
      ko: "Hermes 네이티브 작업은 Hermes와 그 자체의 config·auth 명령이 담당합니다. 외부 소유 주체는 Maestro가 조율하며, Maestro는 준비와 보고만 하고 실행하지 않습니다.",
      ja: "Hermes ネイティブの作業は Hermes 自身の config・auth コマンドが担います。外部の担当は Maestro が調整し、Maestro は準備と報告のみで実行はしません。",
      zh: "Hermes 原生工作交由 Hermes 及其自身的 config、auth 命令处理。外部归属由 Maestro 协调，Maestro 只负责准备与汇报，从不执行。"
    },
    "route.owner.hermes": { en: "hermes native", ko: "hermes 네이티브", ja: "hermes ネイティブ", zh: "hermes 原生" },
    "route.owner.maestro": { en: "maestro external", ko: "maestro 외부", ja: "maestro 外部", zh: "maestro 外部" },
    "route.family.tag": { en: "Families", ko: "모델 계열", ja: "モデル系統", zh: "模型系列" },
    "route.family.title": {
      en: "Qwen, Gemini, Grok, Kimi.",
      ko: "Qwen, Gemini, Grok, Kimi.",
      ja: "Qwen、Gemini、Grok、Kimi。",
      zh: "Qwen、Gemini、Grok、Kimi。"
    },
    "route.family.body": {
      en: "Chains name model families, never a single vendor. Declaring the X-platform domain notes the Grok family advisorily, and your explicit choice always wins.",
      ko: "후보 목록은 특정 벤더가 아니라 모델 계열을 가리킵니다. X 플랫폼 도메인을 선언하면 Grok 계열을 참고용으로 안내할 뿐이며, 사용자의 명시적 선택이 언제나 우선합니다.",
      ja: "チェーンは単一ベンダーではなくモデル系統を指します。X プラットフォーム領域を宣言すると Grok 系統が参考として示されますが、明示的な選択が常に優先されます。",
      zh: "候选链指向模型系列，而非单一厂商。声明 X 平台领域只会以参考方式提示 Grok 系列，你的明确选择始终优先。"
    },
    "route.note": {
      en: "Shipped order is editorial, not a benchmark. OMH prepares routing metadata and never invokes a model.",
      ko: "기본 순서는 편집상의 선택일 뿐 벤치마크가 아닙니다. OMH는 라우팅 메타데이터만 준비하고 모델을 직접 호출하지 않습니다.",
      ja: "同梱の順序は編集上の選択であり、ベンチマークではありません。OMH はルーティング・メタデータを準備するだけで、モデルを呼び出しません。",
      zh: "内置顺序是编辑判断，不是基准测试。OMH 只准备路由元数据，从不调用模型。"
    },
    "route.cta": {
      en: "Read the routing setup guide",
      ko: "라우팅 설정 가이드 읽기",
      ja: "ルーティング設定ガイドを読む",
      zh: "阅读路由设置指南"
    },
    /* --------------------------------------------------------------- chains */
    "chain.kicker": { en: "Recommended chains", ko: "추천 체인", ja: "推奨チェーン", zh: "推荐候选链" },
    "chain.title": {
      en: "Nine categories, in the order we ship.",
      ko: "9개 카테고리, 기본 제공 순서 그대로.",
      ja: "9 つのカテゴリを、同梱の順序のまま。",
      zh: "九个类别，按内置顺序呈现。"
    },
    "chain.lead": {
      en: "OMH ships with these editable, ordered recommendation chains. Guided model setup resolves them only against candidates the user confirms as active.",
      ko: "OMH는 편집 가능한 순서형 추천 체인을 이렇게 기본 제공합니다. 가이드형 모델 설정은 사용자가 활성으로 확인한 후보에 대해서만 이 체인을 해석합니다.",
      ja: "OMH はこれらの編集可能な順序付き推奨チェーンを同梱します。ガイド付きモデル設定は、利用者が有効と確認した候補に対してのみチェーンを解決します。",
      zh: "OMH 内置这些可编辑的有序推荐链。引导式模型设置只会针对用户确认为活跃的候选来解析它们。"
    },
    "chain.head.category": { en: "Category", ko: "카테고리", ja: "カテゴリ", zh: "类别" },
    "chain.head.purpose": { en: "Purpose", ko: "용도", ja: "用途", zh: "用途" },
    "chain.head.order": { en: "Shipped order", ko: "기본 순서", ja: "同梱の順序", zh: "内置顺序" },
    "chain.head.effort": { en: "Effort", ko: "추론 강도", ja: "推論強度", zh: "推理强度" },
    "chain.ultrabrain": { en: "Deepest reasoning", ko: "가장 깊은 추론", ja: "最も深い推論", zh: "最深度的推理" },
    "chain.deep": { en: "Strong default tier", ko: "강력한 기본 등급", ja: "強力な既定ティア", zh: "强力默认档" },
    "chain.architect": {
      en: "Architecture and system design",
      ko: "아키텍처와 시스템 설계",
      ja: "アーキテクチャとシステム設計",
      zh: "架构与系统设计"
    },
    "chain.unspecified-high": { en: "Default working model", ko: "기본 작업 모델", ja: "既定の作業モデル", zh: "默认工作模型" },
    "chain.unspecified-low": { en: "Cheaper fallback", ko: "더 저렴한 대안", ja: "より安価なフォールバック", zh: "更省钱的回退" },
    "chain.quick": { en: "Short tasks", ko: "짧은 작업", ja: "短いタスク", zh: "短任务" },
    "chain.writing": { en: "Prose and docs", ko: "산문과 문서", ja: "文章とドキュメント", zh: "文案与文档" },
    "chain.visual-engineering": { en: "Frontend and visual", ko: "프런트엔드와 비주얼", ja: "フロントエンドとビジュアル", zh: "前端与视觉" },
    "chain.artistry": { en: "Unconventional work", ko: "관습을 벗어난 작업", ja: "型にはまらない作業", zh: "非常规工作" },
    "chain.note": {
      en: "The result is prepared routing configuration, not provider availability, credential, dispatch, or execution evidence.",
      ko: "그 결과물은 준비된 라우팅 설정일 뿐이며, 제공자 가용성·자격 증명·디스패치·실행의 증거가 아닙니다.",
      ja: "その結果は準備されたルーティング設定であり、プロバイダの可用性・認証情報・ディスパッチ・実行の証拠ではありません。",
      zh: "其结果是准备好的路由配置，而非提供方可用性、凭据、派发或执行的证据。"
    },
    "chain.edit": {
      en: 'Every chain is yours to reorder. Edit <code>~/.omh/routing/model-chains.json</code>, then run <code>omh model-chains show</code> to print what is in effect. The Maestro lane — dispatched Claude Code and Codex units — has the same dial: <code>omh coding category-maestro interview</code>.',
      ko: '모든 체인은 직접 순서를 바꿀 수 있습니다. <code>~/.omh/routing/model-chains.json</code>을 편집한 뒤 <code>omh model-chains show</code>로 현재 적용된 내용을 출력하세요. Maestro 레인 — 디스패치되는 Claude Code·Codex 유닛 — 에도 같은 다이얼이 있습니다: <code>omh coding category-maestro interview</code>.',
      ja: 'どのチェーンも自分で並べ替えられます。<code>~/.omh/routing/model-chains.json</code> を編集し、<code>omh model-chains show</code> で現在有効な内容を出力してください。Maestro レーン — ディスパッチされる Claude Code・Codex ユニット — にも同じダイヤルがあります: <code>omh coding category-maestro interview</code>。',
      zh: '每条链都可以由你重新排序。编辑 <code>~/.omh/routing/model-chains.json</code>，再运行 <code>omh model-chains show</code> 打印当前生效的配置。Maestro 通道——被派发的 Claude Code 与 Codex 单元——也有同样的旋钮：<code>omh coding category-maestro interview</code>。'
    },

    "install.routing.note": {
      en: "Setup records which models are reachable here. Routing order stays editable afterwards.",
      ko: "설치 과정에서 이 컴퓨터에서 쓸 수 있는 모델이 기록됩니다. 라우팅 순서는 그 뒤에도 계속 편집할 수 있습니다.",
      ja: "セットアップはこの環境で利用できるモデルを記録します。ルーティング順序はその後も編集できます。",
      zh: "安装会记录本机可用的模型。路由顺序之后仍可编辑。"
    },
    "install.routing.link": {
      en: "Model routing setup",
      ko: "모델 라우팅 설정",
      ja: "モデル・ルーティング設定",
      zh: "模型路由设置"
    },

    /* ------------------------------------------------------------- footer */
    "footer.product": { en: "Product", ko: "제품", ja: "プロダクト", zh: "产品" },
    "footer.resources": { en: "Resources", ko: "리소스", ja: "リソース", zh: "资源" },
    "footer.community": { en: "Community", ko: "커뮤니티", ja: "コミュニティ", zh: "社区" },
    "footer.workflows": { en: "Workflow reference", ko: "워크플로 레퍼런스", ja: "ワークフロー・リファレンス", zh: "工作流参考" },
    "footer.architecture": { en: "Architecture", ko: "아키텍처", ja: "アーキテクチャ", zh: "架构" },
    "footer.routing": { en: "Model routing", ko: "모델 라우팅", ja: "モデル・ルーティング", zh: "模型路由" },
    "footer.changelog": { en: "Changelog", ko: "변경 이력", ja: "変更履歴", zh: "更新日志" },
    "footer.issues": { en: "Issues", ko: "이슈", ja: "Issue", zh: "问题反馈" },
    "footer.releases": { en: "Releases", ko: "릴리스", ja: "リリース", zh: "版本发布" },
    "footer.discussions": { en: "Discussions", ko: "디스커션", ja: "ディスカッション", zh: "讨论区" },
    "footer.contributing": { en: "Contributing", ko: "기여 가이드", ja: "コントリビュート", zh: "参与贡献" },
    "footer.license": { en: "License", ko: "라이선스", ja: "ライセンス", zh: "许可证" },
    "footer.tag": {
      en: "Power intelligence and agentic memory for Hermes Agent.",
      ko: "Hermes Agent의 파워 인텔리전스와 에이전틱 메모리.",
      ja: "Hermes Agent のパワー・インテリジェンスとエージェンティック・メモリ。",
      zh: "Hermes Agent 的强力智能与智能体记忆。"
    },
    "footer.legal": {
      en: "MIT licensed. Oh My Hermes is an independent open-source project, not affiliated with Anthropic or OpenAI. Product names and marks belong to their respective owners.",
      ko: "MIT 라이선스. Oh My Hermes는 독립 오픈소스 프로젝트이며 Anthropic·OpenAI와 무관합니다. 제품명과 마크는 각 소유자에게 귀속됩니다.",
      ja: "MIT ライセンス。Oh My Hermes は独立した OSS で、Anthropic や OpenAI とは無関係です。製品名とマークは各所有者に帰属します。",
      zh: "MIT 许可。Oh My Hermes 是独立开源项目，与 Anthropic 或 OpenAI 无关。产品名称与标识归各自所有者。"
    }
  }
};
