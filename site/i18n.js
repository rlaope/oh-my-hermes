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
    "nav.skip": {
      en: "Skip to content",
      ko: "본문으로 건너뛰기",
      ja: "本文へスキップ",
      zh: "跳转到正文"
    },
    "nav.features": {
      en: "Features",
      ko: "기능",
      ja: "機能",
      zh: "功能"
    },
    "nav.install": {
      en: "Install",
      ko: "설치",
      ja: "インストール",
      zh: "安装"
    },
    "nav.docs": {
      en: "Docs",
      ko: "문서",
      ja: "ドキュメント",
      zh: "文档"
    },
    "hero.badge": {
      en: "For Hermes Agent · v4.0.5",
      ko: "Hermes Agent 전용 · v4.0.5",
      ja: "Hermes Agent のための · v4.0.5",
      zh: "为 Hermes Agent 打造 · v4.0.5"
    },
    "hero.tagline": {
      en: "All-in-one package for Hermes Agent. Install once, then just type <code>dag-ulw</code>.",
      ko: "Hermes Agent를 위한 올인원 패키지. 한 번 설치하고 <code>dag-ulw</code>만 입력하세요.",
      ja: "Hermes Agent のためのオールインワンパッケージ。一度インストールしたら、<code>dag-ulw</code> と入力するだけ。",
      zh: "Hermes Agent 的一站式套件。安装一次，然后只需输入 <code>dag-ulw</code>。"
    },
    "hero.lead": {
      en: "You keep talking to Hermes. OMH picks the skill and a model for each lane, and runs the work in parallel. It never patches or replaces Hermes, and it never reports planned work as done.",
      ko: "대화는 계속 Hermes와 하고, OMH가 스킬과 lane마다 모델을 골라 일을 병렬로 돌립니다. Hermes를 패치하거나 대체하지 않고, 계획만 된 일을 완료로 보고하지 않습니다.",
      ja: "話しかける相手は Hermes のまま。OMH がスキルと lane ごとのモデルを選び、作業を並列で回します。Hermes にパッチを当てたり置き換えたりせず、計画しただけの作業を完了とは報告しません。",
      zh: "你照常和 Hermes 对话，OMH 为你选技能、为每条 lane 选模型，并把工作并行跑起来。它不给 Hermes 打补丁，也不取代它，更不会把只是计划过的工作报告为完成。"
    },
    "install.tab.unix": {
      en: "macOS · Linux",
      ko: "macOS · Linux",
      ja: "macOS · Linux",
      zh: "macOS · Linux"
    },
    "hero.copy": {
      en: "Copy",
      ko: "복사",
      ja: "コピー",
      zh: "复制"
    },
    "hero.more": {
      en: "Windows and other options",
      ko: "Windows와 다른 설치 방법",
      ja: "Windows とその他の方法",
      zh: "Windows 及其他安装方式"
    },
    "hero.github": {
      en: "View on GitHub",
      ko: "GitHub에서 보기",
      ja: "GitHub で見る",
      zh: "在 GitHub 上查看"
    },
    "stat.workflows": {
      en: "ulw workflows",
      ko: "ulw 워크플로",
      ja: "ulw ワークフロー",
      zh: "ulw 工作流"
    },
    "stat.categories": {
      en: "model categories you can edit",
      ko: "편집 가능한 모델 카테고리",
      ja: "編集できるモデルカテゴリ",
      zh: "可编辑的模型类别"
    },
    "stat.skills": {
      en: "omh-* expert skills",
      ko: "omh-* 전문 스킬",
      ja: "omh-* 専門スキル",
      zh: "omh-* 专家技能"
    },
    "features.title": {
      en: "What you get",
      ko: "얻는 것",
      ja: "得られるもの",
      zh: "你能得到什么"
    },
    "feat.models.title": {
      en: "The right model for every lane.",
      ko: "lane마다 맞는 모델.",
      ja: "lane ごとに合うモデル。",
      zh: "每条 lane 用对的模型。"
    },
    "feat.models.body": {
      en: "Each lane is tagged with a work category: <code>ultrabrain</code>, <code>deep</code>, <code>visual-engineering</code>, <code>quick</code> and more. The category picks that lane's model chain and reasoning effort, and you can edit every chain. When a provider rejects a model, the chain moves to the next one instead of silently downgrading.",
      ko: "lane마다 작업 카테고리가 붙습니다: <code>ultrabrain</code>, <code>deep</code>, <code>visual-engineering</code>, <code>quick</code> 등. 카테고리가 그 lane의 모델 chain과 추론 강도를 정하고, chain은 모두 편집할 수 있습니다. provider가 모델을 거부하면 조용히 다운그레이드하지 않고 chain의 다음 모델로 넘어갑니다.",
      ja: "lane ごとに作業カテゴリが付きます: <code>ultrabrain</code>、<code>deep</code>、<code>visual-engineering</code>、<code>quick</code> など。カテゴリがその lane のモデル chain と推論強度を決め、chain はすべて編集できます。provider がモデルを拒否すると、黙ってダウングレードせず chain の次のモデルへ進みます。",
      zh: "每条 lane 都带有一个工作类别：<code>ultrabrain</code>、<code>deep</code>、<code>visual-engineering</code>、<code>quick</code> 等。类别决定该 lane 的模型 chain 和推理强度，每条 chain 都可以编辑。provider 拒绝某个模型时，不会悄悄降级，而是前进到 chain 的下一个模型。"
    },
    "feat.models.link": {
      en: "See which model runs each lane",
      ko: "lane별 모델 보기",
      ja: "lane ごとのモデル",
      zh: "每条 lane 用哪个模型"
    },
    "feat.dag.title": {
      en: "<code>/dag-ulw</code> graph runs.",
      ko: "<code>/dag-ulw</code> 그래프 실행.",
      ja: "<code>/dag-ulw</code> のグラフ実行。",
      zh: "<code>/dag-ulw</code> 图运行。"
    },
    "feat.dag.body": {
      en: "Your goal becomes a graph of small nodes, and the ready ones run in parallel. Each node runs on its category's model and effort; nodes running at once never share a write scope. A separate node checks the goal, and failed nodes are repaired before the report.",
      ko: "목표가 작은 노드의 그래프가 되고, 준비된 노드부터 병렬로 실행됩니다. 노드마다 카테고리의 모델·effort로 돌고, 동시에 도는 노드끼리 쓰기 범위를 공유하지 않습니다. 별도 노드가 목표를 확인하고, 실패한 노드는 보고 전에 복구됩니다.",
      ja: "目標は小さなノードのグラフになり、準備のできたノードから並列に走ります。各ノードはカテゴリのモデルと effort で動き、同時に走るノード同士は書き込み範囲を共有しません。別のノードが目標を確認し、失敗したノードは報告前に修復されます。",
      zh: "你的目标会变成由小节点组成的图，就绪的节点并行运行。每个节点使用其类别的模型和 effort，同时运行的节点不会共享写入范围。由单独的节点检查目标，失败的节点在报告前得到修复。"
    },
    "feat.skills.title": {
      en: "Expert skills on demand.",
      ko: "필요할 때 전문가 스킬.",
      ja: "必要なときに専門スキル。",
      zh: "按需加入的专家技能。"
    },
    "feat.skills.body": {
      en: "A hundred-plus <code>omh-*</code> specialists: frontend, backend, Rust, security review, verification gates. You never call them; the router loads the right ones into the run as tool calls.",
      ko: "프론트엔드, 백엔드, Rust, 보안 리뷰, 검증 게이트 등 100개가 넘는 <code>omh-*</code> 전문 스킬. 따로 부르지 않아도 라우터가 맞는 스킬을 툴 호출로 실행에 넣습니다.",
      ja: "フロントエンド、バックエンド、Rust、セキュリティレビュー、検証ゲートなど 100 を超える <code>omh-*</code> スキル。呼び出さなくても、ルーターが合うスキルをツール呼び出しとして実行に加えます。",
      zh: "前端、后端、Rust、安全评审、验证门禁等一百多个 <code>omh-*</code> 专业技能。你不用去调用，路由器会把合适的技能以工具调用的形式加入运行。"
    },
    "feat.memory.title": {
      en: "Long-term memory you can trust.",
      ko: "믿을 수 있는 장기 메모리.",
      ja: "信頼できる長期メモリ。",
      zh: "可以信赖的长期记忆。"
    },
    "feat.memory.body": {
      en: "Nothing is remembered silently: each candidate is kept, refused or deferred with a written reason. The next session gets a recall pack ranked for its task and cut to a token budget. Hermes' own memory is never read or patched.",
      ko: "조용히 기억하지 않습니다. 후보마다 기억·거부·보류를 이유와 함께 남깁니다. 다음 세션은 작업에 맞게 순위를 매기고 토큰 예산에 맞춘 recall pack을 받습니다. Hermes 자체 메모리는 읽지도 고치지도 않습니다.",
      ja: "黙って記憶しません。候補ごとに、記憶・却下・保留を理由とともに残します。次のセッションは、タスクに合わせて順位付けし、トークン予算に収めた recall pack を受け取ります。Hermes 自身のメモリは読みも書き換えもしません。",
      zh: "不会悄悄记忆：每个候选都带着写明的理由被记住、拒绝或推迟。下一个会话会得到按任务排序、裁剪到 token 预算内的召回包。Hermes 自己的记忆从不被读取或修改。"
    },
    "feat.native.title": {
      en: "OMH Native.",
      ko: "OMH Native.",
      ja: "OMH Native.",
      zh: "OMH Native."
    },
    "feat.native.body": {
      en: "Bare <code>omh</code> opens OMH's own TUI on Hermes' gateway; switch its launch look with <code>/theme</code>. <code>/dag-ulw</code> prints the box graph, then a live lane tree with each lane's model, effort and tokens. Steer or interrupt an agent from the agent list, run a <code>!</code> shell line, and rewind with Esc Esc.",
      ko: "<code>omh</code>는 Hermes gateway 위에서 OMH 자체 TUI를 열고, 실행 화면 스타일은 <code>/theme</code>으로 바꿉니다. <code>/dag-ulw</code>는 박스 그래프를 출력한 뒤, lane마다 모델·effort·토큰이 보이는 실시간 트리를 띄웁니다. 에이전트 목록에서 steer와 중단을 하고, <code>!</code> 셸 명령을 실행하고, Esc Esc로 되감습니다.",
      ja: "<code>omh</code> は Hermes の gateway 上で OMH 独自の TUI を開き、起動時の見た目は <code>/theme</code> で切り替えます。<code>/dag-ulw</code> はボックスグラフを出し、lane ごとのモデル・effort・トークンが見えるライブツリーを表示します。エージェント一覧から steer や中断ができ、<code>!</code> でシェルを実行し、Esc Esc で巻き戻せます。",
      zh: "<code>omh</code> 在 Hermes gateway 上打开 OMH 自己的 TUI，启动外观可用 <code>/theme</code> 切换。<code>/dag-ulw</code> 先打印方框图，再显示实时 lane 树，列出每条 lane 的模型、effort 和 token。在 agent 列表里 steer 或中断 agent，用 <code>!</code> 运行 shell 命令，按 Esc Esc 回退。"
    },
    "feat.evidence.title": {
      en: "Evidence before \"done\".",
      ko: "\"완료\" 전에 증거.",
      ja: "「完了」の前に証拠。",
      zh: "“完成”之前先有证据。"
    },
    "feat.evidence.body": {
      en: "Every status names its stage and how sure OMH is about it. A run counts as verified only when a test, review or CI gate actually passed.",
      ko: "모든 상태는 단계와 확신도를 함께 보여 줍니다. 테스트, 리뷰, CI 게이트가 실제로 통과해야 verified가 됩니다.",
      ja: "どの状態も、段階と確からしさを一緒に示します。テスト、レビュー、CI ゲートが実際に通って初めて verified になります。",
      zh: "每个状态都同时标明阶段和把握程度。只有测试、评审或 CI 门禁真正通过，才算 verified。"
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
    "dag.title": {
      en: "Just type <code>/dag-ulw</code>, and you're a graph engineering master.",
      ko: "<code>/dag-ulw</code>만 입력하세요. 그래프 엔지니어링 마스터가 됩니다.",
      ja: "<code>/dag-ulw</code> と打つだけで、あなたもグラフエンジニアリングの達人。",
      zh: "只需输入 <code>/dag-ulw</code>，你就是图工程大师。"
    },
    "dag.lead": {
      en: "Your goal becomes a graph of small nodes that run in parallel, each on its own model. A separate node verifies the goal before you get the report.",
      ko: "목표가 작은 노드의 그래프가 되고, 노드마다 자기 모델로 병렬 실행됩니다. 별도 노드가 목표를 검증한 뒤에 보고가 옵니다.",
      ja: "目標は小さなノードのグラフになり、ノードごとに自分のモデルで並列に走ります。別のノードが目標を検証してから、報告が届きます。",
      zh: "你的目标会变成由小节点组成的图，每个节点用自己的模型并行运行。由一个单独的节点验证目标之后，你才会收到报告。"
    },
    "dag.pause": {
      en: "Pause",
      ko: "일시정지",
      ja: "一時停止",
      zh: "暂停"
    },
    "dag.caption": {
      en: "A real recording of the OMH TUI: seven lanes, four layers, every lane accepted.",
      ko: "OMH TUI 실제 녹화: 레인 7개, 레이어 4개, 모든 레인 accepted.",
      ja: "OMH TUI の実際の録画: 7 レーン、4 レイヤー、すべてのレーンが accepted。",
      zh: "OMH TUI 的真实录屏：七条通道、四层，每条通道都 accepted。"
    },
    "dag.graph.caption": {
      en: "The graph from the demo run, drawn as an illustration. Hover or focus a lane to trace what it waits on and what it feeds.",
      ko: "데모 실행의 그래프를 일러스트로 그린 것입니다. lane에 마우스를 올리거나 포커스하면 무엇을 기다리고 무엇에 이어지는지 보입니다.",
      ja: "デモ実行のグラフをイラストとして描いたものです。lane にホバーまたはフォーカスすると、何を待ち、何につながるかをたどれます。",
      zh: "这是演示运行中的图，以示意图形式绘制。悬停或聚焦某条 lane，可以看到它等待什么、又连向什么。"
    },
    "dag.graph.replay": {
      en: "Replay the run",
      ko: "실행 다시 보기",
      ja: "実行を再生",
      zh: "重放这次运行"
    },
    "install.title": {
      en: "Install once. Set up once.",
      ko: "설치도 한 번, 설정도 한 번.",
      ja: "インストールも一度、セットアップも一度。",
      zh: "安装一次，设置一次。"
    },
    "install.lead": {
      en: "Pick one way to install the command, then run setup. Doctor is a separate check you can run any time.",
      ko: "명령을 설치할 방법 하나를 고르고 setup을 실행하세요. doctor는 언제든 따로 돌리는 점검입니다.",
      ja: "コマンドのインストール方法を一つ選び、setup を実行します。doctor はいつでも別に実行できる確認です。",
      zh: "选一种方式安装命令，然后运行 setup。doctor 是随时可以单独运行的检查。"
    },
    "install.availability.note": {
      en: "Homebrew, Bun, and npm package-manager installs are public as of v1.0.6.",
      ko: "Homebrew, Bun, npm 패키지 관리자 설치가 v1.0.6부터 공개되었습니다.",
      ja: "Homebrew、Bun、npm のパッケージマネージャー経由のインストールは v1.0.6 から公開されています。",
      zh: "Homebrew、Bun 与 npm 包管理器安装方式已随 v1.0.6 正式公开。"
    },
    "install.prereq.note": {
      en: "Use the macOS · Linux or Windows installer; it finds Python 3.11+ itself. Homebrew, Bun, and npm install the published release: Bun and npm also need Node 18+ and Python 3.11+ on PATH, and Homebrew brings its own Python.",
      ko: "macOS · Linux 또는 Windows 설치 스크립트를 사용하세요. Python 3.11 이상을 스스로 찾습니다. Homebrew, Bun, npm은 공개 릴리스를 설치합니다. Bun과 npm은 PATH에 Node 18 이상과 Python 3.11 이상이 더 필요하고, Homebrew는 자체 Python을 설치합니다.",
      ja: "macOS · Linux または Windows のインストーラーを使ってください。Python 3.11 以降は自動で見つけます。Homebrew、Bun、npm は公開リリースをインストールします。Bun と npm には PATH 上の Node 18 以降と Python 3.11 以降も必要で、Homebrew は独自の Python を入れます。",
      zh: "请使用 macOS · Linux 或 Windows 安装脚本，它会自行查找 Python 3.11+。Homebrew、Bun 与 npm 安装已发布的版本：Bun 和 npm 还需要 PATH 中有 Node 18+ 与 Python 3.11+，Homebrew 会自带 Python。"
    },
    "install.step1": {
      en: "Install the command",
      ko: "명령어 설치",
      ja: "コマンドをインストール",
      zh: "安装命令行"
    },
    "install.method.brew": {
      en: "Homebrew",
      ko: "Homebrew",
      ja: "Homebrew",
      zh: "Homebrew"
    },
    "install.method.bun": {
      en: "Bun",
      ko: "Bun",
      ja: "Bun",
      zh: "Bun"
    },
    "install.method.npm": {
      en: "npm",
      ko: "npm",
      ja: "npm",
      zh: "npm"
    },
    "install.method.unix": {
      en: "macOS · Linux",
      ko: "macOS · Linux",
      ja: "macOS · Linux",
      zh: "macOS · Linux"
    },
    "install.method.windows": {
      en: "Windows · PowerShell 5.1+",
      ko: "Windows · PowerShell 5.1+",
      ja: "Windows · PowerShell 5.1+",
      zh: "Windows · PowerShell 5.1+"
    },
    "install.step2": {
      en: "Set it up",
      ko: "설정하기",
      ja: "セットアップ",
      zh: "完成设置"
    },
    "install.step2.note": {
      en: "Run it after any of the installs above.",
      ko: "위의 어느 방법으로 설치했든 다음에 실행합니다.",
      ja: "上のどの方法でインストールしても、次にこれを実行します。",
      zh: "无论用上面哪种方式安装，之后都运行它。"
    },
    "install.doctor.title": {
      en: "Verify or troubleshoot",
      ko: "확인과 문제 해결",
      ja: "確認とトラブルシューティング",
      zh: "验证或排查问题"
    },
    "install.doctor.note": {
      en: "Refresh later with <code>omh update</code>: it upgrades the command through the installer that owns it, then refreshes the managed skills, the plugin bundle, and the Hermes registration.",
      ko: "나중에 <code>omh update</code>로 갱신합니다. 명령을 설치한 installer로 업그레이드한 뒤, 관리 스킬과 플러그인 번들, Hermes 등록을 새로 고칩니다.",
      ja: "あとで <code>omh update</code> で更新します。コマンドを入れた installer でアップグレードし、管理スキル、プラグインバンドル、Hermes への登録を更新します。",
      zh: "之后用 <code>omh update</code> 更新：它通过安装该命令的 installer 升级，然后刷新托管技能、插件包和 Hermes 注册。"
    },
    "install.step3": {
      en: "Or paste this into your AI agent",
      ko: "또는 AI 에이전트에 붙여넣기",
      ja: "または AI エージェントに貼り付け",
      zh: "或者粘贴给你的 AI 智能体"
    },
    "install.prompt.label": {
      en: "Prompt for your agent",
      ko: "에이전트용 프롬프트",
      ja: "エージェント用プロンプト",
      zh: "给智能体的提示词"
    },
    "community.title": {
      en: "Be with us",
      ko: "함께해요",
      ja: "一緒に参加しましょう",
      zh: "加入我们"
    },
    "community.x": {
      en: "Updates, release notes and project news.",
      ko: "업데이트, 릴리스 노트, 프로젝트 소식.",
      ja: "更新情報、リリースノート、プロジェクトのニュース。",
      zh: "更新、发布说明和项目动态。"
    },
    "community.github": {
      en: "More projects, releases, and ongoing work.",
      ko: "더 많은 프로젝트, 릴리스, 진행 중인 작업.",
      ja: "その他のプロジェクト、リリース、進行中の作業。",
      zh: "更多项目、发布和进行中的工作。"
    },
    "community.discord": {
      en: "Ask questions, share workflows, and talk with other users.",
      ko: "질문하고, 워크플로를 공유하고, 다른 사용자들과 이야기해 보세요.",
      ja: "質問したり、ワークフローを共有したり、他のユーザーと交流しましょう。",
      zh: "提问、分享工作流，并与其他用户交流。"
    },
    "community.and": {
      en: "and",
      ko: "와",
      ja: "と",
      zh: "和"
    },
    "community.agents": {
      en: "AI agents, collaborators helping ship oh-my-hermes.",
      ko: "oh-my-hermes 출시를 함께 돕는 AI 에이전트.",
      ja: "oh-my-hermes の開発を支える AI エージェント。",
      zh: "帮助交付 oh-my-hermes 的 AI 智能体协作者。"
    },
    "community.nous": {
      en: "Thank you for creating Hermes Agent.",
      ko: "Hermes Agent를 만들어 주셔서 감사합니다.",
      ja: "Hermes Agent を生み出してくれたことに感謝します。",
      zh: "感谢创造了 Hermes Agent。"
    },
    "sponsors.title": {
      en: "Sponsors",
      ko: "스폰서",
      ja: "スポンサー",
      zh: "赞助商"
    },
    "sponsors.opengateway": {
      en: "One OpenAI-compatible endpoint for many model providers, with automatic failover. Thank you for backing open source.",
      ko: "여러 모델 provider를 OpenAI 호환 엔드포인트 하나로 묶고, 자동 failover를 제공합니다. 오픈소스를 응원해 주셔서 감사합니다.",
      ja: "複数のモデル provider を OpenAI 互換のエンドポイント一つにまとめ、自動フェイルオーバーも備えています。オープンソースへのご支援に感謝します。",
      zh: "它用一个兼容 OpenAI 的端点接入多家模型 provider，并提供自动故障切换。感谢你们对开源的支持。"
    },
    "models.title": {
      en: "Every lane on its own model",
      ko: "lane마다 자기 모델로",
      ja: "lane ごとに自分のモデルで",
      zh: "每条 lane 用自己的模型"
    },
    "models.lead": {
      en: "Eighteen categories ship with an ordered chain each. <code>omh model</code> opens the picker: arrow keys pick the category, left and right change the head model, minus and plus change the effort. The same picker opens inside the OMH TUI as <code>/omh-model</code>.",
      ko: "카테고리 18개가 각자 순서 있는 chain과 함께 제공됩니다. <code>omh model</code>이 피커를 엽니다. 화살표 키로 카테고리를 고르고, 좌우로 첫 모델을, -/+로 effort를 바꿉니다. OMH TUI 안에서는 <code>/omh-model</code>이 같은 피커를 엽니다.",
      ja: "18 のカテゴリが、それぞれ順序付きの chain とともに出荷されます。<code>omh model</code> でピッカーが開きます。矢印キーでカテゴリを選び、左右で先頭モデルを、-/+ で effort を変えます。OMH TUI では <code>/omh-model</code> が同じピッカーを開きます。",
      zh: "十八个类别各自附带一条有序 chain。<code>omh model</code> 打开选择器：方向键选类别，左右切换首选模型，-/+ 调整 effort。在 OMH TUI 里，<code>/omh-model</code> 打开同一个选择器。"
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
    "chain.title": {
      en: "Shipped chains, in order",
      ko: "기본 제공 chain과 순서",
      ja: "出荷時の chain と順序",
      zh: "默认 chain 及其顺序"
    },
    "chain.head.category": {
      en: "Category",
      ko: "카테고리",
      ja: "カテゴリ",
      zh: "类别"
    },
    "chain.head.purpose": {
      en: "Purpose",
      ko: "용도",
      ja: "用途",
      zh: "用途"
    },
    "chain.head.order": {
      en: "Shipped order",
      ko: "기본 순서",
      ja: "同梱の順序",
      zh: "内置顺序"
    },
    "chain.head.effort": {
      en: "Effort",
      ko: "추론 강도",
      ja: "推論強度",
      zh: "推理强度"
    },
    "chain.ultrabrain": {
      en: "Deepest reasoning",
      ko: "가장 깊은 추론",
      ja: "最も深い推論",
      zh: "最深度的推理"
    },
    "chain.deep": {
      en: "Strong default tier",
      ko: "강력한 기본 등급",
      ja: "強力な既定ティア",
      zh: "强力默认档"
    },
    "chain.architect": {
      en: "Architecture and system design",
      ko: "아키텍처와 시스템 설계",
      ja: "アーキテクチャとシステム設計",
      zh: "架构与系统设计"
    },
    "chain.unspecified-high": {
      en: "Default working model",
      ko: "기본 작업 모델",
      ja: "既定の作業モデル",
      zh: "默认工作模型"
    },
    "chain.unspecified-low": {
      en: "Cheaper fallback",
      ko: "더 저렴한 대안",
      ja: "より安価なフォールバック",
      zh: "更省钱的回退"
    },
    "chain.quick": {
      en: "Short tasks",
      ko: "짧은 작업",
      ja: "短いタスク",
      zh: "短任务"
    },
    "chain.writing": {
      en: "Prose and docs",
      ko: "산문과 문서",
      ja: "文章とドキュメント",
      zh: "文案与文档"
    },
    "chain.visual-engineering": {
      en: "Frontend and visual",
      ko: "프런트엔드와 비주얼",
      ja: "フロントエンドとビジュアル",
      zh: "前端与视觉"
    },
    "chain.artistry": {
      en: "Unconventional work",
      ko: "관습을 벗어난 작업",
      ja: "型にはまらない作業",
      zh: "非常规工作"
    },
    "chain.capable": {
      en: "Strong general work",
      ko: "범용 고성능 작업",
      ja: "汎用の高性能作業",
      zh: "通用高能力工作"
    },
    "chain.simple-work": {
      en: "Small everyday tasks",
      ko: "간단한 일상 작업",
      ja: "簡単な日常タスク",
      zh: "简单的日常任务"
    },
    "chain.deep-work": {
      en: "Long tasks at frontier depth",
      ko: "최상위 깊이의 긴 작업",
      ja: "最高深度の長時間タスク",
      zh: "最高深度的长任务"
    },
    "chain.google-search": {
      en: "Research grounded in Google Search",
      ko: "Google 검색에 근거한 조사",
      ja: "Google 検索に基づく調査",
      zh: "以 Google 搜索为依据的调研"
    },
    "chain.x-search": {
      en: "Live search on X",
      ko: "X 실시간 검색",
      ja: "X のリアルタイム検索",
      zh: "X 上的实时搜索"
    },
    "chain.review": {
      en: "A different model tries to break the diff",
      ko: "다른 모델이 diff를 깨뜨려 보는 검토",
      ja: "別のモデルが diff を壊しにかかるレビュー",
      zh: "由另一个模型尝试攻破 diff"
    },
    "chain.swarm": {
      en: "Many parallel workers on separate slices",
      ko: "여러 병렬 작업자가 각자 나눈 조각을 처리",
      ja: "多数の並列ワーカーが別々の断片を担当",
      zh: "多个并行 worker 各自处理不同切片"
    },
    "chain.forensics": {
      en: "Root-causing a live symptom or a captured trace",
      ko: "실제 증상이나 수집한 trace의 근본 원인 추적",
      ja: "実際の症状や取得した trace の根本原因の特定",
      zh: "追查实时症状或已捕获 trace 的根因"
    },
    "chain.synthesize": {
      en: "Merging many results into one answer",
      ko: "여러 결과를 하나의 답으로 종합",
      ja: "多くの結果を一つの答えに統合",
      zh: "将多个结果合并为一个答案"
    },
    "chain.edit": {
      en: "Every chain is yours to reorder. Edit <code>~/.omh/routing/model-chains.json</code>, then run <code>omh model-chains show</code> to print what is in effect.",
      ko: "모든 chain은 직접 순서를 바꿀 수 있습니다. <code>~/.omh/routing/model-chains.json</code>을 고친 뒤 <code>omh model-chains show</code>로 적용된 내용을 출력합니다.",
      ja: "どの chain も自分で並べ替えられます。<code>~/.omh/routing/model-chains.json</code> を編集し、<code>omh model-chains show</code> で有効な内容を表示します。",
      zh: "每条 chain 都可以由你重新排序。编辑 <code>~/.omh/routing/model-chains.json</code>，再运行 <code>omh model-chains show</code> 打印当前生效的内容。"
    },
    "chain.note": {
      en: "The result is prepared routing configuration, not provider availability, credential, dispatch, or execution evidence.",
      ko: "그 결과물은 준비된 라우팅 설정일 뿐이며, 제공자 가용성·자격 증명·디스패치·실행의 증거가 아닙니다.",
      ja: "その結果は準備されたルーティング設定であり、プロバイダの可用性・認証情報・ディスパッチ・実行の証拠ではありません。",
      zh: "其结果是准备好的路由配置，而非提供方可用性、凭据、派发或执行的证据。"
    },
    "route.cta": {
      en: "Read the routing setup guide",
      ko: "라우팅 설정 가이드 읽기",
      ja: "ルーティング設定ガイドを読む",
      zh: "阅读路由设置指南"
    },
    "ulw.kicker": {
      en: "Flagship workflows",
      ko: "대표 워크플로",
      ja: "フラッグシップ",
      zh: "旗舰工作流"
    },
    "ulw.title": {
      en: "The ulw-* family.",
      ko: "ulw-* 패밀리.",
      ja: "ulw-* ファミリー。",
      zh: "ulw-* 家族。"
    },
    "ulw.lead": {
      en: "Ten long-horizon lanes. Say the trigger in normal language — Hermes routes the rest.",
      ko: "10개의 장기 레인. 평범한 말로 트리거만 말하면 나머지는 Hermes가 라우팅합니다.",
      ja: "10 の長期レーン。普通の言葉でトリガーを言えば、あとは Hermes がルーティング。",
      zh: "十条长周期车道。用日常语言说出触发词，其余交给 Hermes 路由。"
    },
    "ulw.context.tag": {
      en: "Terminology alignment",
      ko: "용어 정렬",
      ja: "用語アラインメント",
      zh: "术语对齐"
    },
    "ulw.context.title": {
      en: "Context",
      ko: "Context",
      ja: "Context",
      zh: "Context"
    },
    "ulw.context.body": {
      en: "Aligns the words a repository uses before plans and handoffs.",
      ko: "계획과 핸드오프 전에 저장소가 쓰는 용어부터 맞춥니다.",
      ja: "計画とハンドオフの前に、リポジトリが使う言葉を揃えます。",
      zh: "在计划与交接之前，先对齐仓库使用的词汇。"
    },
    "ulw.trigger": {
      en: "Say",
      ko: "이렇게 말하세요",
      ja: "こう言う",
      zh: "这样说"
    },
    "ulw.interview.tag": {
      en: "Clarification",
      ko: "명확화",
      ja: "明確化",
      zh: "澄清"
    },
    "ulw.interview.title": {
      en: "Deep Interview",
      ko: "Deep Interview",
      ja: "Deep Interview",
      zh: "Deep Interview"
    },
    "ulw.interview.body": {
      en: "One question at a time until the brief is clear. Six rounds max, clarity scored each round.",
      ko: "브리프가 명확해질 때까지 한 번에 한 질문. 최대 6라운드, 라운드마다 명확도 점수.",
      ja: "ブリーフが明確になるまで一度に一問。最大 6 ラウンド、毎回明確度をスコア。",
      zh: "一次一问，直到简报清晰。最多六轮，每轮标注清晰度。"
    },
    "ulw.research.tag": {
      en: "Decision grounding",
      ko: "의사결정 근거",
      ja: "意思決定の根拠",
      zh: "决策依据"
    },
    "ulw.research.title": {
      en: "Research",
      ko: "Research",
      ja: "Research",
      zh: "Research"
    },
    "ulw.research.body": {
      en: "Reference implementations at pinned refs, live web evidence with citations, verified claims.",
      ko: "실제 코드와 최신 웹 자료로 조사하고, 출처를 남기고, 의심스러운 주장은 검증합니다.",
      ja: "実際のコードと最新のウェブ情報で調査し、出典を残し、怪しい主張は裏取りします。",
      zh: "用真实代码和最新网页资料做调研，留下出处，可疑说法一定核实。"
    },
    "ulw.plan.tag": {
      en: "Reviewed plan",
      ko: "검토된 계획",
      ja: "レビュー済み計画",
      zh: "评审过的计划"
    },
    "ulw.plan.title": {
      en: "Ralplan",
      ko: "Ralplan",
      ja: "Ralplan",
      zh: "Ralplan"
    },
    "ulw.plan.body": {
      en: "Consensus planning with review gates: facts, options, risks, acceptance criteria, handoff.",
      ko: "리뷰 게이트가 있는 합의 계획: 사실, 선택지, 리스크, 수용 기준, 핸드오프.",
      ja: "レビューゲート付き合意プランニング：事実、選択肢、リスク、受け入れ基準、ハンドオフ。",
      zh: "带评审关卡的共识规划：事实、方案、风险、验收标准、交接。"
    },
    "ulw.work.tag": {
      en: "Parallel delivery",
      ko: "병렬 전달",
      ja: "並列デリバリー",
      zh: "并行交付"
    },
    "ulw.work.title": {
      en: "Ultrawork",
      ko: "Ultrawork",
      ja: "Ultrawork",
      zh: "Ultrawork"
    },
    "ulw.work.body": {
      en: "Splits an accepted plan into disjoint lanes — owner, criteria, and verification per lane. Two lanes never edit the same file.",
      ko: "승인된 계획을 겹치지 않는 레인으로 분할 — 레인마다 소유자, 기준, 검증. 두 레인이 같은 파일을 건드리지 않습니다.",
      ja: "承認済み計画を重ならないレーンへ分割 — レーンごとにオーナー、基準、検証。二つのレーンが同じファイルを編集しません。",
      zh: "把已确认的计划切成互不重叠的车道 —— 每条有归属、标准与验证。两条车道绝不改同一个文件。"
    },
    "ulw.dag-ulw.tag": {
      en: "Graph run",
      ko: "그래프 실행",
      ja: "グラフ実行",
      zh: "图执行"
    },
    "ulw.dag-ulw.title": {
      en: "DAG ULW",
      ko: "DAG ULW",
      ja: "DAG ULW",
      zh: "DAG ULW"
    },
    "ulw.dag-ulw.body": {
      en: "Plans a graph of small nodes, runs them in parallel, verifies and repairs.",
      ko: "작은 노드로 된 그래프를 계획하고 병렬로 실행한 뒤 검증하고 복구합니다.",
      ja: "小さなノードのグラフを計画し、並列に実行して、検証と修復まで行います。",
      zh: "把工作规划成小节点组成的图，并行运行，再验证并修复。"
    },
    "ulw.maestro.tag": {
      en: "External handoff",
      ko: "외부 핸드오프",
      ja: "外部ハンドオフ",
      zh: "外部交接"
    },
    "ulw.maestro.title": {
      en: "Maestro",
      ko: "Maestro",
      ja: "Maestro",
      zh: "Maestro"
    },
    "ulw.maestro.body": {
      en: "Runs the work on Claude Code or Codex, spawned live with a steerable session.",
      ko: "Claude Code 또는 Codex에서 작업을 실행 — 실시간으로 구동되고 세션을 조종할 수 있습니다.",
      ja: "Claude Code または Codex で作業を実行 — ライブで起動し、セッションを操作できます。",
      zh: "在 Claude Code 或 Codex 上运行任务 —— 实时启动，会话可操控。"
    },
    "ulw.loop.tag": {
      en: "Goal loop",
      ko: "목표 루프",
      ja: "ゴールループ",
      zh: "目标循环"
    },
    "ulw.loop.title": {
      en: "Loop",
      ko: "Loop",
      ja: "Loop",
      zh: "Loop"
    },
    "ulw.loop.body": {
      en: "Interview → plan → research → build → review, cycling until a real gate passes.",
      ko: "인터뷰 → 계획 → 리서치 → 빌드 → 리뷰. 진짜 게이트를 통과할 때까지 순환.",
      ja: "インタビュー → 計画 → リサーチ → ビルド → レビュー。本物のゲートを通るまで循環。",
      zh: "访谈 → 规划 → 研究 → 构建 → 评审，循环直到真正的关卡通过。"
    },
    "ulw.qa.tag": {
      en: "Adversarial QA",
      ko: "적대적 QA",
      ja: "敵対的 QA",
      zh: "对抗式 QA"
    },
    "ulw.qa.title": {
      en: "UltraQA",
      ko: "UltraQA",
      ja: "UltraQA",
      zh: "UltraQA"
    },
    "ulw.qa.body": {
      en: "Hostile scenarios, end-to-end runs, release QA, and fix loops — explicit and evidence-backed.",
      ko: "적대적 시나리오, E2E 실행, 릴리스 QA, 수정 루프 — 명시적이고 증거 기반.",
      ja: "敵対的シナリオ、E2E 実行、リリース QA、修正ループ — 明示的で証拠付き。",
      zh: "恶意场景、端到端跑通、发版 QA 与修复循环 —— 显式且有据可依。"
    },
    "ulw.perf.tag": {
      en: "Measured optimization",
      ko: "측정 기반 최적화",
      ja: "計測ベース最適化",
      zh: "以测量为准的优化"
    },
    "ulw.perf.title": {
      en: "Ultraperf",
      ko: "Ultraperf",
      ja: "Ultraperf",
      zh: "Ultraperf"
    },
    "ulw.perf.body": {
      en: "Finds where the system is actually slow, leaking, or expensive — then fixes one measured hot path at a time.",
      ko: "시스템이 실제로 느리고 새고 비싼 곳을 찾아 — 측정된 핫패스를 하나씩 고칩니다.",
      ja: "実際に遅く、漏れ、高コストな箇所を特定し — 計測済みホットパスを一つずつ修正。",
      zh: "找出系统真正慢、漏、贵的地方 —— 然后逐条修复被测量过的热路径。"
    },
    "footer.tag": {
      en: "All-in-one package for Hermes Agent.",
      ko: "Hermes Agent를 위한 올인원 패키지.",
      ja: "Hermes Agent のためのオールインワンパッケージ。",
      zh: "Hermes Agent 的一站式套件。"
    },
    "footer.resources": {
      en: "Resources",
      ko: "리소스",
      ja: "リソース",
      zh: "资源"
    },
    "footer.architecture": {
      en: "Architecture",
      ko: "아키텍처",
      ja: "アーキテクチャ",
      zh: "架构"
    },
    "footer.routing": {
      en: "Model routing",
      ko: "모델 라우팅",
      ja: "モデル・ルーティング",
      zh: "模型路由"
    },
    "footer.workflows": {
      en: "Workflow reference",
      ko: "워크플로 레퍼런스",
      ja: "ワークフロー・リファレンス",
      zh: "工作流参考"
    },
    "footer.installation": {
      en: "Installation guide",
      ko: "설치 가이드",
      ja: "インストールガイド",
      zh: "安装指南"
    },
    "footer.project": {
      en: "Project",
      ko: "프로젝트",
      ja: "プロジェクト",
      zh: "项目"
    },
    "footer.releases": {
      en: "Releases",
      ko: "릴리스",
      ja: "リリース",
      zh: "版本发布"
    },
    "footer.changelog": {
      en: "Changelog",
      ko: "변경 이력",
      ja: "変更履歴",
      zh: "更新日志"
    },
    "footer.issues": {
      en: "Issues",
      ko: "이슈",
      ja: "Issue",
      zh: "问题反馈"
    },
    "footer.contributing": {
      en: "Contributing",
      ko: "기여 가이드",
      ja: "コントリビュート",
      zh: "参与贡献"
    },
    "footer.license": {
      en: "License",
      ko: "라이선스",
      ja: "ライセンス",
      zh: "许可证"
    },
    "footer.legal": {
      en: "MIT licensed. Oh My Hermes is an independent open-source project, not affiliated with Anthropic or OpenAI. Product names and marks belong to their respective owners.",
      ko: "MIT 라이선스. Oh My Hermes는 독립 오픈소스 프로젝트이며 Anthropic·OpenAI와 무관합니다. 제품명과 마크는 각 소유자에게 귀속됩니다.",
      ja: "MIT ライセンス。Oh My Hermes は独立した OSS で、Anthropic や OpenAI とは無関係です。製品名とマークは各所有者に帰属します。",
      zh: "MIT 许可。Oh My Hermes 是独立开源项目，与 Anthropic 或 OpenAI 无关。产品名称与标识归各自所有者。"
    },
    "nav.lang": {
      en: "Change language",
      ko: "언어 변경",
      ja: "言語を変更",
      zh: "切换语言"
    },
    "nav.theme": {
      en: "Switch color theme",
      ko: "색상 테마 전환",
      ja: "カラーテーマを切り替え",
      zh: "切换配色主题"
    },
    "dag.alt": {
      en: "The OMH TUI running /dag-ulw: the prompt is typed, the box graph of seven lanes is defined, the lanes run layer by layer on Claude Opus 5.5, GPT-6.1 Sol, DeepSeek V4.1 Flash, GLM 5.3 and Kimi K3.1 Pro, and every lane ends accepted",
      ko: "/dag-ulw를 실행하는 OMH TUI: 프롬프트를 입력하면 레인 7개의 박스 그래프가 정의되고, 레인이 Claude Opus 5.5, GPT-6.1 Sol, DeepSeek V4.1 Flash, GLM 5.3, Kimi K3.1 Pro로 레이어마다 실행된 뒤 모두 accepted로 끝납니다",
      ja: "/dag-ulw を実行する OMH TUI: プロンプトを入力すると 7 レーンのボックスグラフが定義され、レーンが Claude Opus 5.5、GPT-6.1 Sol、DeepSeek V4.1 Flash、GLM 5.3、Kimi K3.1 Pro でレイヤーごとに走り、すべて accepted で終わります",
      zh: "运行 /dag-ulw 的 OMH TUI：输入提示词后定义出七条通道的方框图，通道按层在 Claude Opus 5.5、GPT-6.1 Sol、DeepSeek V4.1 Flash、GLM 5.3 和 Kimi K3.1 Pro 上运行，最后全部 accepted"
    },
    "dag.play": {
      en: "Play",
      ko: "재생",
      ja: "再生",
      zh: "播放"
    },
    "dag.graph.running": {
      en: "Layer {n} of 4 running",
      ko: "레이어 {n}/4 실행 중",
      ja: "レイヤー {n}/4 を実行中",
      zh: "第 {n}/4 层运行中"
    },
    "dag.graph.done": {
      en: "All seven lanes accepted",
      ko: "레인 7개 모두 accepted",
      ja: "7 レーンすべて accepted",
      zh: "七条通道全部 accepted"
    },
    "nav.star": {
      en: "Star",
      ko: "Star",
      ja: "Star",
      zh: "Star"
    },
    "nav.star.label": {
      en: "Star oh-my-hermes on GitHub",
      ko: "GitHub에서 oh-my-hermes에 Star 주기",
      ja: "GitHub で oh-my-hermes に Star する",
      zh: "在 GitHub 上为 oh-my-hermes 点 Star"
    },
    "nav.star.stars": {
      en: "{n} stars",
      ko: "Star {n}개",
      ja: "Star {n}",
      zh: "{n} 个 Star"
    },
    "nav.installs": {
      en: "installs",
      ko: "설치",
      ja: "インストール",
      zh: "次安装"
    },
    "nav.installs.title": {
      en: "npm downloads, all time",
      ko: "npm 누적 다운로드",
      ja: "npm の累計ダウンロード数",
      zh: "npm 累计下载量"
    }
  }
};
