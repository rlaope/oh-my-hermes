/*!
 * Oh My Hermes - Start Guide copy in en / ko / ja / zh.
 * Loaded after i18n.js and before app.js; adds the guide.* keys to window.OMH_I18N.strings.
 */
(function (strings) {
  var target = (window.OMH_I18N = window.OMH_I18N || { meta: {}, strings: {} }).strings;
  Object.keys(strings).forEach(function (key) { target[key] = strings[key]; });
})({
  "guide.toc.what": {
    en: "What it does",
    ko: "하는 일",
    ja: "できること",
    zh: "能做什么"
  },
  "guide.toc.install": {
    en: "Install",
    ko: "설치",
    ja: "インストール",
    zh: "安装"
  },
  "guide.toc.routing": {
    en: "Categories",
    ko: "카테고리",
    ja: "カテゴリ",
    zh: "类别"
  },
  "guide.toc.dag": {
    en: "plan · dag-ulw",
    ko: "plan · dag-ulw",
    ja: "plan · dag-ulw",
    zh: "plan · dag-ulw"
  },
  "guide.toc.fresh": {
    en: "Always current",
    ko: "늘 최신",
    ja: "いつも最新",
    zh: "始终最新"
  },
  "guide.toc.tui": {
    en: "omh TUI",
    ko: "omh TUI",
    ja: "omh TUI",
    zh: "omh TUI"
  },
  "guide.toc.omher": {
    en: "omher desktop",
    ko: "omher desktop",
    ja: "omher desktop",
    zh: "omher desktop"
  },
  "guide.toc.more": {
    en: "More",
    ko: "더 보기",
    ja: "もっと",
    zh: "更多"
  },
  "guide.title": {
    en: "<span class=\"nw\">Oh My Hermes</span> Start Guide",
    ko: "<span class=\"nw\">Oh My Hermes</span> 시작 가이드",
    ja: "<span class=\"nw\">Oh My Hermes</span> スタートガイド",
    zh: "<span class=\"nw\">Oh My Hermes</span> 入门指南"
  },
  "guide.lede": {
    en: "OMH is a layer on top of <a href=\"https://github.com/NousResearch/hermes-agent\">Hermes Agent</a>. You keep talking to Hermes; OMH splits the work into lanes and runs each one on the model that suits it, at the same time.",
    ko: "OMH는 <a href=\"https://github.com/NousResearch/hermes-agent\">Hermes Agent</a> 위에 얹는 운영층입니다. 대화는 그대로 Hermes와 하고, OMH가 일을 여러 줄(lane)로 나눠 줄마다 맞는 모델로 동시에 돌립니다.",
    ja: "OMH は <a href=\"https://github.com/NousResearch/hermes-agent\">Hermes Agent</a> の上に載る運用レイヤーです。会話はこれまでどおり Hermes と。OMH が仕事をいくつかのレーンに分け、それぞれに合ったモデルで同時に走らせます。",
    zh: "OMH 是架在 <a href=\"https://github.com/NousResearch/hermes-agent\">Hermes Agent</a> 之上的运行层。你照常和 Hermes 对话；OMH 把工作拆成几条 lane，让每条用最合适的模型同时运行。"
  },
  "guide.lede.note": {
    en: "It never patches Hermes, and it never calls planned work done.",
    ko: "Hermes를 고치지 않고, 계획만 된 일을 완료라고 하지 않습니다.",
    ja: "Hermes を書き換えることはなく、計画しただけの仕事を完了とは言いません。",
    zh: "它从不修改 Hermes，也从不把只是计划好的工作称为完成。"
  },
  "guide.hero.start": {
    en: "Install",
    ko: "설치하기",
    ja: "インストール",
    zh: "安装"
  },
  "guide.what.title": {
    en: "What OMH does",
    ko: "OMH가 하는 일",
    ja: "OMH でできること",
    zh: "OMH 能做什么"
  },
  "guide.what.c1.t": {
    en: "Models by category",
    ko: "카테고리별 모델",
    ja: "カテゴリ別のモデル",
    zh: "按类别选模型"
  },
  "guide.what.c1.d": {
    en: "Every lane gets a category, like <code>quick</code> or <code>deep</code>. The category picks the model and how hard it thinks.",
    ko: "lane마다 <code>quick</code>, <code>deep</code> 같은 카테고리가 붙고, 카테고리가 모델과 생각의 깊이(effort)를 정합니다.",
    ja: "レーンごとに <code>quick</code> や <code>deep</code> などのカテゴリが付き、カテゴリがモデルと考える深さ（effort）を決めます。",
    zh: "每条 lane 都带一个类别，比如 <code>quick</code> 或 <code>deep</code>；类别决定用哪个模型、想得多深（effort）。"
  },
  "guide.what.c2.t": {
    en: "Parallel runs with dag-ulw",
    ko: "dag-ulw 병렬 실행",
    ja: "dag-ulw の並列実行",
    zh: "dag-ulw 并行运行"
  },
  "guide.what.c2.d": {
    en: "Type <code>/dag-ulw</code> and a goal. It becomes small steps, the ready ones run in parallel, and a separate step checks the result.",
    ko: "<code>/dag-ulw</code>에 목표를 적으면 작은 단계로 쪼개지고, 준비된 단계부터 동시에 돌며, 마지막에 별도 단계가 결과를 확인합니다.",
    ja: "<code>/dag-ulw</code> と目標を書くと小さなステップに分かれ、準備できたものから並行して動き、最後に別のステップが結果を確かめます。",
    zh: "输入 <code>/dag-ulw</code> 加上目标，它会拆成小步骤，就绪的并行运行，最后由单独一步检查结果。"
  },
  "guide.what.c3.t": {
    en: "Expert skills",
    ko: "전문 스킬",
    ja: "専門スキル",
    zh: "专家技能"
  },
  "guide.what.c3.d": {
    en: "A hundred-plus specialists: frontend, backend, Rust, security review. You never call them; the router brings the right ones in.",
    ko: "프론트엔드, 백엔드, Rust, 보안 리뷰 등 100개가 넘는 전문 스킬. 부를 필요 없이 라우터가 맞는 스킬을 붙입니다.",
    ja: "フロントエンド、バックエンド、Rust、セキュリティレビューなど 100 を超える専門スキル。呼ばなくても、ルーターが合うものを取り込みます。",
    zh: "前端、后端、Rust、安全审查等 100 多个专家技能。不用你点名，路由器会把合适的带进来。"
  },
  "guide.what.c4.t": {
    en: "Long-term memory",
    ko: "장기 메모리",
    ja: "長期記憶",
    zh: "长期记忆"
  },
  "guide.what.c4.d": {
    en: "Nothing is remembered silently: each candidate is kept, refused or deferred with a written reason. The next session gets the memories that fit its task, cut to a token budget.",
    ko: "조용히 기억하지 않습니다. 기억할 후보마다 남기기·거절·보류를 이유와 함께 적습니다. 다음 세션은 그 작업에 맞는 기억만 토큰 예산 안에서 받습니다.",
    ja: "黙って覚えることはありません。候補ごとに記憶・拒否・保留を理由とともに残します。次のセッションには、その作業に合う記憶だけがトークン予算の範囲で渡ります。",
    zh: "不会悄悄记住任何东西：每个候选都会写明理由，记住、拒绝或暂缓。下一个会话只拿到与任务相关的记忆，并控制在 token 预算内。"
  },
  "guide.install.title": {
    en: "Install",
    ko: "설치",
    ja: "インストール",
    zh: "安装"
  },
  "guide.install.s1.t": {
    en: "Install omh",
    ko: "omh 설치",
    ja: "omh をインストール",
    zh: "安装 omh"
  },
  "guide.install.s1.d": {
    en: "macOS and Linux. It finds Python 3.11+ on its own.",
    ko: "macOS·Linux용입니다. Python 3.11+는 알아서 찾습니다.",
    ja: "macOS と Linux 向け。Python 3.11+ は自分で探します。",
    zh: "适用于 macOS 和 Linux，会自己找到 Python 3.11+。"
  },
  "guide.install.s2.t": {
    en: "Connect it to Hermes",
    ko: "Hermes에 연결",
    ja: "Hermes につなぐ",
    zh: "接入 Hermes"
  },
  "guide.install.s2.d": {
    en: "Installs the skills and registers OMH with Hermes.",
    ko: "스킬을 설치하고 OMH를 Hermes에 등록합니다.",
    ja: "スキルを入れて、OMH を Hermes に登録します。",
    zh: "安装技能，并把 OMH 注册到 Hermes。"
  },
  "guide.install.s3.t": {
    en: "Pick your models",
    ko: "모델 고르기",
    ja: "モデルを選ぶ",
    zh: "选择模型"
  },
  "guide.install.s3.d": {
    en: "Opens the picker, one row per category. The arrow keys change the model and the effort.",
    ko: "카테고리마다 한 줄씩 나오는 피커가 열립니다. 화살표 키로 모델과 effort를 바꿉니다.",
    ja: "カテゴリごとに一行のピッカーが開きます。矢印キーでモデルと effort を変えます。",
    zh: "打开选择器，每个类别一行，用方向键切换模型和 effort。"
  },
  "guide.install.more": {
    en: "Windows, or Hermes + OMH + the desktop app in one go",
    ko: "Windows, 또는 Hermes·OMH·데스크톱 앱 한 번에",
    ja: "Windows、または Hermes・OMH・デスクトップアプリを一度に",
    zh: "Windows，或一次装好 Hermes、OMH 和桌面应用"
  },
  "guide.install.win": {
    en: "Windows (PowerShell)",
    ko: "Windows (PowerShell)",
    ja: "Windows（PowerShell）",
    zh: "Windows（PowerShell）"
  },
  "guide.install.all": {
    en: "Hermes if it is missing, then OMH, then the omher app (beta)",
    ko: "Hermes(없을 때), OMH, omher 앱까지 한 번에 (beta)",
    ja: "Hermes（なければ）、OMH、omher アプリまで一度に（beta）",
    zh: "一次装好 Hermes（若没有）、OMH 和 omher 应用（beta）"
  },
  "guide.install.docs": {
    en: "Every install option",
    ko: "모든 설치 방법",
    ja: "すべてのインストール方法",
    zh: "全部安装方式"
  },
  "guide.route.title": {
    en: "Categories and model routing",
    ko: "카테고리와 모델 라우팅",
    ja: "カテゴリとモデルルーティング",
    zh: "类别与模型路由"
  },
  "guide.route.body": {
    en: "A category is a kind of work. Each one keeps its models in order: first choice, then the next.",
    ko: "카테고리는 일의 종류입니다. 카테고리마다 모델 순서가 정해져 있습니다. 1순위, 그다음 2순위.",
    ja: "カテゴリは仕事の種類です。カテゴリごとにモデルの順番があります。第一候補、その次。",
    zh: "类别就是工作的种类。每个类别都排好了模型顺序：首选，然后是下一个。"
  },
  "guide.route.cat.quick": {
    en: "Short tasks",
    ko: "짧은 일",
    ja: "短い仕事",
    zh: "短任务"
  },
  "guide.route.cat.deep": {
    en: "Strong default",
    ko: "기본 주력",
    ja: "主力の標準",
    zh: "主力默认"
  },
  "guide.route.cat.visual": {
    en: "Screens and frontend",
    ko: "화면·프론트엔드",
    ja: "画面とフロントエンド",
    zh: "界面与前端"
  },
  "guide.route.no": {
    en: "Provider said no",
    ko: "provider가 거절",
    ja: "プロバイダーが拒否",
    zh: "提供方拒绝"
  },
  "guide.route.runs": {
    en: "Next in line runs",
    ko: "다음 순위가 실행",
    ja: "次の候補が実行",
    zh: "顺位下一个运行"
  },
  "guide.route.rule": {
    en: "If a provider refuses a model, the next one in the list takes over. OMH never quietly swaps in something weaker.",
    ko: "provider가 모델을 거절하면 목록의 다음 모델이 이어받습니다. 몰래 더 약한 모델로 바꾸지 않습니다.",
    ja: "プロバイダーがモデルを断ると、リストの次のモデルが引き継ぎます。こっそり弱いモデルに替えることはしません。",
    zh: "如果提供方拒绝某个模型，列表里的下一个接手。OMH 不会悄悄换成更弱的模型。"
  },
  "guide.route.note": {
    en: "The models shown are today's defaults. Run <code>omh model</code> to see yours; every list is yours to edit.",
    ko: "보이는 모델은 지금 기본값입니다. 내 설정은 <code>omh model</code>에서 확인하고, 목록은 모두 직접 바꿀 수 있습니다.",
    ja: "表示しているのは今の既定値です。自分の設定は <code>omh model</code> で確認でき、どのリストも自由に編集できます。",
    zh: "这里显示的是当前默认值。运行 <code>omh model</code> 查看你的设置，每份列表都可以自己改。"
  },
  "guide.route.docs": {
    en: "Model routing in detail",
    ko: "모델 라우팅 자세히",
    ja: "モデルルーティングの詳細",
    zh: "模型路由详解"
  },
  "guide.dag.title": {
    en: "plan and dag-ulw",
    ko: "plan과 dag-ulw",
    ja: "plan と dag-ulw",
    zh: "plan 与 dag-ulw"
  },
  "guide.dag.plan.t": {
    en: "plan",
    ko: "plan",
    ja: "plan",
    zh: "plan"
  },
  "guide.dag.plan.d": {
    en: "<code>ulw-plan</code> writes the list and gets it agreed. <code>ulw-work</code> then works through it.",
    ko: "<code>ulw-plan</code>이 목록을 만들어 합의하고, <code>ulw-work</code>가 그 목록대로 진행합니다.",
    ja: "<code>ulw-plan</code> がリストを作って合意を取り、<code>ulw-work</code> がそのとおりに進めます。",
    zh: "<code>ulw-plan</code> 写出清单并确认，<code>ulw-work</code> 照着清单去做。"
  },
  "guide.dag.dag.t": {
    en: "dag-ulw",
    ko: "dag-ulw",
    ja: "dag-ulw",
    zh: "dag-ulw"
  },
  "guide.dag.dag.d": {
    en: "<code>dag-ulw</code> turns the list into a flowchart. Only a step that needs an earlier one waits; the rest run at the same time. A separate step checks the goal, and anything that failed is fixed before you get the report.",
    ko: "<code>dag-ulw</code>는 목록을 순서도로 바꿉니다. 앞 단계가 필요한 것만 기다리고 나머지는 동시에 실행됩니다. 마지막에 별도 단계가 목표를 확인하고, 실패한 단계는 고친 뒤 보고합니다.",
    ja: "<code>dag-ulw</code> はリストをフローチャートに変えます。前のステップが必要なものだけ待ち、残りは同時に動きます。最後に別のステップが目標を確かめ、失敗したものは直してから報告します。",
    zh: "<code>dag-ulw</code> 把清单变成流程图。只有依赖前一步的步骤要等，其余同时运行。最后由单独一步核对目标，失败的步骤修好之后才给你报告。"
  },
  "guide.dag.n.read": {
    en: "Read the code",
    ko: "코드 읽기",
    ja: "コードを読む",
    zh: "阅读代码"
  },
  "guide.dag.n.repro": {
    en: "Reproduce",
    ko: "재현하기",
    ja: "再現する",
    zh: "复现问题"
  },
  "guide.dag.n.fix": {
    en: "Fix",
    ko: "고치기",
    ja: "直す",
    zh: "修复"
  },
  "guide.dag.n.test": {
    en: "Write a test",
    ko: "테스트 쓰기",
    ja: "テストを書く",
    zh: "写测试"
  },
  "guide.dag.n.verify": {
    en: "Check the goal",
    ko: "목표 확인",
    ja: "目標を確かめる",
    zh: "核对目标"
  },
  "guide.dag.prompt": {
    en: "fix the login bug",
    ko: "로그인 버그 고쳐줘",
    ja: "ログインのバグを直して",
    zh: "修复登录 bug"
  },
  "guide.dag.same": {
    en: "same time",
    ko: "동시에",
    ja: "同時に",
    zh: "同时"
  },
  "guide.dag.back": {
    en: "if the check fails, fix again",
    ko: "확인이 실패하면 다시 고침",
    ja: "確認に失敗したら直し直す",
    zh: "检查失败就再修一次"
  },
  "guide.dag.wait": {
    en: "waiting",
    ko: "대기",
    ja: "待機",
    zh: "等待"
  },
  "guide.dag.run": {
    en: "running",
    ko: "실행 중",
    ja: "実行中",
    zh: "运行中"
  },
  "guide.dag.done": {
    en: "done",
    ko: "완료",
    ja: "完了",
    zh: "完成"
  },
  "guide.dag.tip": {
    en: "Not sure which one? Type <code>/dag-ulw</code> and what you want.",
    ko: "뭘 써야 할지 모르겠으면 <code>/dag-ulw</code> 뒤에 하고 싶은 말만 적으세요.",
    ja: "迷ったら <code>/dag-ulw</code> のあとにやりたいことを書くだけ。",
    zh: "拿不准用哪个？输入 <code>/dag-ulw</code>，后面写上你想做的事就行。"
  },
  "guide.fresh.title": {
    en: "Updates and compatibility checks",
    ko: "업데이트와 호환성 검사",
    ja: "アップデートと互換性チェック",
    zh: "更新与兼容性检查"
  },
  "guide.fresh.body": {
    en: "When a new model or a new Hermes ships, OMH does not just follow. It checks that things still work, then updates.",
    ko: "새 모델이나 새 Hermes가 나오면 그냥 따라가지 않습니다. 돌아가는지 확인한 다음에 바꿉니다.",
    ja: "新しいモデルや新しい Hermes が出ても、ただ追いかけはしません。動くことを確かめてから更新します。",
    zh: "新模型或新版 Hermes 发布时，OMH 不会直接跟上，而是先确认一切照常工作，再更新。"
  },
  "guide.fresh.c1.t": {
    en: "New model",
    ko: "새 모델",
    ja: "新しいモデル",
    zh: "新模型"
  },
  "guide.fresh.c1.d": {
    en: "OMH first checks that its router recognizes the model and which effort levels the provider accepts. Only then does it take a place in the category lists.",
    ko: "먼저 라우터가 그 모델을 알아보는지, provider가 어떤 effort 단계를 받아 주는지 확인합니다. 그다음에야 카테고리 목록에 들어갑니다.",
    ja: "まずルーターがそのモデルを認識できるか、プロバイダーがどの effort 段階を受け付けるかを確かめます。そのあとで初めてカテゴリのリストに入ります。",
    zh: "先确认路由器能识别这个模型、提供方接受哪些 effort 档位，然后它才进入类别列表。"
  },
  "guide.fresh.c2.t": {
    en: "New Hermes",
    ko: "새 Hermes",
    ja: "新しい Hermes",
    zh: "新版 Hermes"
  },
  "guide.fresh.c2.d": {
    en: "Every night the OMH plugin is loaded into a real Hermes, both the stable release and main. If any check is missing, the run fails.",
    ko: "매일 밤 OMH 플러그인을 실제 Hermes(stable 릴리스와 main 둘 다)에 올려 봅니다. 확인이 하나라도 빠지면 실패로 처리합니다.",
    ja: "毎晩、OMH プラグインを本物の Hermes（安定版と main の両方）に読み込ませます。確認が一つでも欠ければ失敗です。",
    zh: "每晚把 OMH 插件加载进真实的 Hermes（稳定版和 main 都测），缺任何一项检查就算失败。"
  },
  "guide.fresh.c3.t": {
    en: "Skill sources",
    ko: "스킬 출처",
    ja: "スキルの出典",
    zh: "技能来源"
  },
  "guide.fresh.c3.d": {
    en: "A skill shaped by outside work records the upstream commit it was reviewed against. When upstream changes, the change is folded in or turned down, and the decision is written down; CI blocks a record without it.",
    ko: "외부 작업을 참고한 스킬은 어느 커밋을 보고 검토했는지 기록합니다. 원본이 바뀌면 반영하거나 거절하고 그 결정을 남기며, 결정 기록이 빠지면 CI가 막습니다.",
    ja: "外部の成果を参考にしたスキルは、どのコミットを見て検討したかを記録します。元が変わったら取り込むか見送るかを決めて記録に残し、記録が欠けていれば CI が止めます。",
    zh: "参考外部成果的技能会记下它审阅时对照的上游提交。上游变动时，决定采纳还是不采纳并写下来；缺少记录，CI 会拦下。"
  },
  "guide.fresh.how": {
    en: "How it is done",
    ko: "절차 보기",
    ja: "手順を見る",
    zh: "查看流程"
  },
  "guide.fresh.how2": {
    en: "The nightly check",
    ko: "매일 밤 검사 보기",
    ja: "毎晩のチェック",
    zh: "每晚的检查"
  },
  "guide.fresh.how3": {
    en: "The source registry",
    ko: "출처 기록 보기",
    ja: "出典の記録",
    zh: "来源登记"
  },
  "guide.fresh.you": {
    en: "All you run is <code>omh update</code>.",
    ko: "사용자는 <code>omh update</code>만 실행하면 됩니다.",
    ja: "あなたは <code>omh update</code> を実行するだけ。",
    zh: "你只需要运行 <code>omh update</code>。"
  },
  "guide.tui.title": {
    en: "The <code>omh</code> TUI",
    ko: "<code>omh</code> TUI",
    ja: "<code>omh</code> TUI",
    zh: "<code>omh</code> TUI"
  },
  "guide.tui.body": {
    en: "Bare <code>omh</code> opens OMH's own terminal on your Hermes. Every model call and approval is still Hermes'; the screen is OMH's. <code>/dag-ulw</code> draws the graph, then a live tree with each lane's model, effort and tokens.",
    ko: "<code>omh</code>만 치면 내 Hermes 위에서 OMH 전용 터미널이 열립니다. 모델 호출과 승인은 그대로 Hermes가 하고, 화면만 OMH 것입니다. <code>/dag-ulw</code>는 그래프를 그린 뒤 lane마다 모델·effort·토큰이 보이는 실시간 트리를 띄웁니다.",
    ja: "<code>omh</code> だけで、手元の Hermes の上に OMH 専用のターミナルが開きます。モデル呼び出しと承認はこれまでどおり Hermes が行い、画面だけが OMH のものです。<code>/dag-ulw</code> はグラフを描いたあと、レーンごとのモデル・effort・トークンが見えるライブツリーを表示します。",
    zh: "只输入 <code>omh</code>，就会在你的 Hermes 上打开 OMH 自己的终端。模型调用和审批仍由 Hermes 负责，只有界面是 OMH 的。<code>/dag-ulw</code> 先画出图，再显示一棵实时树，每条 lane 的模型、effort 和 token 一目了然。"
  },
  "guide.tui.k.theme": {
    en: "Change the launch look",
    ko: "시작 화면 스타일 바꾸기",
    ja: "起動画面の見た目を変える",
    zh: "切换启动界面风格"
  },
  "guide.tui.k.shell": {
    en: "Run one shell line",
    ko: "셸 명령 한 줄 실행",
    ja: "シェルを一行実行",
    zh: "运行一行 shell 命令"
  },
  "guide.tui.k.rewind": {
    en: "Rewind",
    ko: "되감기",
    ja: "巻き戻す",
    zh: "回退"
  },
  "guide.tui.k.resume": {
    en: "Come back to a session",
    ko: "이전 세션으로 돌아오기",
    ja: "前のセッションに戻る",
    zh: "回到之前的会话"
  },
  "guide.omher.title": {
    en: "omher desktop (beta)",
    ko: "omher desktop (beta)",
    ja: "omher desktop (beta)",
    zh: "omher desktop (beta)"
  },
  "guide.omher.body": {
    en: "ADE means agent development environment. Your Hermes bots sit on the left, each with its work threads; the chat is in the middle; terminals open in a panel at the bottom with <kbd>Ctrl</kbd> <kbd>`</kbd>, as in VS Code.",
    ko: "ADE는 에이전트 개발 환경입니다. 왼쪽엔 Hermes 봇과 봇별 작업 스레드, 가운데엔 채팅이 있고, 터미널은 VS Code처럼 <kbd>Ctrl</kbd> <kbd>`</kbd>로 아래 패널에 엽니다.",
    ja: "ADE はエージェント開発環境のこと。左に Hermes のボットとボットごとの作業スレッド、中央にチャット。ターミナルは VS Code のように <kbd>Ctrl</kbd> <kbd>`</kbd> で下のパネルに開きます。",
    zh: "ADE 就是智能体开发环境。左边是 Hermes 机器人和各自的工作线程，中间是聊天；终端像 VS Code 一样，用 <kbd>Ctrl</kbd> <kbd>`</kbd> 在底部面板打开。"
  },
  "guide.omher.one": {
    en: "One command installs Hermes if it is missing, OMH, and the app.",
    ko: "명령 한 줄로 Hermes(없을 때), OMH, 앱까지 설치합니다.",
    ja: "コマンド一つで Hermes（なければ）、OMH、アプリまで入ります。",
    zh: "一条命令装好 Hermes（若没有）、OMH 和应用。"
  },
  "guide.more.title": {
    en: "More features",
    ko: "그 밖의 기능",
    ja: "その他の機能",
    zh: "其他功能"
  },
  "guide.more.maestro.t": {
    en: "ulw-maestro",
    ko: "ulw-maestro",
    ja: "ulw-maestro",
    zh: "ulw-maestro"
  },
  "guide.more.maestro": {
    en: "Hands a coding task to Claude Code or Codex, and lets you steer it while it runs.",
    ko: "코딩 작업을 Claude Code나 Codex에 넘기고, 도는 동안 방향을 바꿀 수 있습니다.",
    ja: "コーディング作業を Claude Code や Codex に渡し、動いている間も舵を切れます。",
    zh: "把编码任务交给 Claude Code 或 Codex，运行中也能随时调整方向。"
  },
  "guide.more.evidence.t": {
    en: "Verification status",
    ko: "검증 상태 표시",
    ja: "検証ステータス",
    zh: "验证状态"
  },
  "guide.more.evidence": {
    en: "A run counts as verified only when a test, a review or CI actually passed.",
    ko: "테스트·리뷰·CI가 실제로 통과해야 verified가 됩니다.",
    ja: "テスト、レビュー、CI が実際に通ったときだけ verified になります。",
    zh: "只有测试、评审或 CI 真正通过，才算 verified。"
  },
  "guide.more.lsp.t": {
    en: "LSP integration",
    ko: "LSP 연동",
    ja: "LSP 連携",
    zh: "LSP 集成"
  },
  "guide.more.lsp": {
    en: "Definitions, references and renames come from the language server, not text search. Off by default.",
    ko: "정의·참조·이름 바꾸기를 텍스트 검색이 아니라 language server로 합니다. 기본은 꺼져 있습니다.",
    ja: "定義・参照・リネームをテキスト検索ではなく language server で行います。既定ではオフです。",
    zh: "定义、引用和重命名都来自 language server，而不是文本搜索。默认关闭。"
  },
  "guide.more.docs": {
    en: "All the docs",
    ko: "전체 문서",
    ja: "ドキュメント一覧",
    zh: "全部文档"
  },
  "guide.more.discord": {
    en: "Ask the community",
    ko: "커뮤니티에 묻기",
    ja: "コミュニティに聞く",
    zh: "向社区提问"
  },
  "guide.more.github": {
    en: "Source and releases",
    ko: "소스와 릴리스",
    ja: "ソースとリリース",
    zh: "源码与发布"
  }
});
