# oh-my-hermes

<p align="center">
  <a href="README.md">English</a> |
  <a href="README.ko.md">한국어</a> |
  <a href="README.ja.md">日本語</a> |
  <a href="README.zh.md">中文</a>
</p>

<p align="center">
  <a href="https://github.com/rlaope/oh-my-hermes"><img alt="GitHub" src="https://img.shields.io/badge/github-rlaope%2Foh--my--hermes-181717?logo=github"></a>
  <img alt="Python" src="https://img.shields.io/badge/python-3.11%2B-blue">
  <img alt="License" src="https://img.shields.io/badge/license-MIT-green">
  <img alt="Status" src="https://img.shields.io/badge/status-1.0.2%20stable-blue">
</p>

<p align="center">
  <img src="assets/hermes-agent-hero.png" alt="Oh My Hermes" width="720">
</p>

<p align="center">
  <strong>一度入れたら、Hermes の流れはそのまま。OMH が次の一手を見えやすく、安全にします。</strong>
  <br>
  <em>チャット起点のスキル、ワークフロー契約、ステータスカード、handoff を既存の Hermes 環境に自然に足します。</em>
</p>

**oh-my-hermes** は Hermes を置き換えるためのものではありません。
[Hermes](https://github.com/NousResearch/hermes-agent) で普段どおり作業しながら、
OMH がスキル、契約、ステータスカード、handoff を加え、次に何をすべきかを
分かりやすくします。日本語、中国語、スペイン語、フランス語、ドイツ語、
韓国語、ヒンディー語、英語でよく使われる運用リクエストは、ローカルで決定的に
ルーティングされます。翻訳 API を呼ばずに、適切なワークフローと最初の
チャットカードまで組み立てられます。

```text
Hermes で自然文のリクエストを送る
  -> OMH が最小限で役に立つワークフロー経路をすすめる
  -> Hermes が確認、調査、計画、報告に必要な次の証拠境界を整理する
  -> コード中心の作業は、承認後に選ばれた runtime へ明示的に handoff する
```

> [!NOTE]
> **Friren Agent は Art&Engine の中で OMH を改良し続けています。**
> OMH の背景にあるスタジオの文脈は
> [Team Art & Engineering](https://rlaope.github.io/artengine-lab/) で見られます。
>
> <p align="center">
>   <img src="assets/friren-agent-omh-callout.png" alt="Friren Agent explaining OMH in Art&Engine" width="920">
> </p>
>
> <p align="center">
>   <img src="assets/artengine-friren-profile-card.png" alt="Art&Engine profile card for Hope Kim and Friren" width="920">
> </p>

<br>

## クイックスタート

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | sh
omh setup

omh doctor
```

Hermes skill tap のパス:

```sh
hermes skills tap add rlaope/oh-my-hermes
hermes skills install rlaope/oh-my-hermes/skills/oh-my-hermes --yes
```

```text
Use OMH request-to-handoff for: I want to safely add a feature to this repo.
```

[Website](https://rlaope.github.io/oh-my-hermes/) -
[Documentation](docs/README.md) -
[Installation](docs/INSTALLATION.md) -
[Capabilities](docs/CAPABILITIES.md) -
[Agent Install](INSTALL_FOR_AGENTS.md) -
[Roles](docs/ROLES.md) -
[Application Cases](docs/APPLICATION_CASES.md) -
[GitHub Pages site](site/index.html)

> [!NOTE]
> **GitHub Follow**
> OMH の更新や Hermes-native なワークフロー関連プロジェクトは
> GitHub の [@rlaope](https://github.com/rlaope) で確認できます。
> 背景にあるスタジオについては
> [Team Art & Engineering](https://rlaope.github.io/artengine-lab/) をご覧ください。

<br>

## 主なワークフロー

<p align="center">
  <img src="assets/omh-core-workflows.png" alt="OMH Core Workflows illustration" width="920">
</p>

<p align="center">
  <img src="assets/omh-skill-magic-promo.png" alt="Friren Agent controlling OMH workflow skills with magic" width="920">
</p>

---

- **Deep Interview** (`deep-interview`) - 計画に入る前に、足りない判断を
  ひとつずつ明確にします。依頼がまだ曖昧なときに使います。

- **Ralplan** (`ralplan`) - repo の事実、根拠、リスク、受け入れ条件、
  検証コマンドを、レビューできる計画にまとめます。

- **Ultragoal** (`ultragoal`) - 大きな目標を一回の回答で流さず、
  チェックポイントと完了ゲートに結びつけて追跡します。

- **Loop** (`loop`) - 調査、計画、handoff、フィードバックを繰り返し、
  実装の方向を見つけるときに使います。

- **Web Research** (`web-research`) - 市場、ドキュメント、競合、
  実装方法、best practice を、現在の出典に基づいて調べます。

- **Idea To Deploy** (`idea-to-deploy`) - Codex、Claude Code、Hermes、
  そのほかの runtime に渡すコード作業を、範囲と証拠境界まで整理します。

- **Workflow Learning** (`workflow-learning`) - 取りこぼしたルートや弱い
  ワークフローを、trace、eval、review queue、regression case、
  patch proposal に変えます。

運用、調査、資料作成、レビュー、リリース、ワークフロー支援のための
組み込みスキルが **41 個以上** あります。全体像は
[Workflow Reference](docs/WORKFLOWS.md) と [Capabilities](docs/CAPABILITIES.md)
にあります。

<br>

## できること

**すぐ使えるワークフロースキル**

- interview、planning、durable goal、loop、research、coding handoff prep、
  review、release、materials、operations 向けの Hermes スキルを導入できます。
- 各スキルには trigger guidance、completion gate、recovery note、
  evidence boundary が入っています。Hermes がキーワードだけで推測せず、
  次に使うべき経路を選べるようにするためです。

**プロファイルと役割の表面**

- Operator、researcher、planner、handoff、review、status の役割が、
  次のアクションの担当を安定して説明します。
- Profile pack は chat、wrapper、coding-agent のふるまいをそろえます。
  ただし、特定の executor を隠れた既定値にはしません。

**Subagent と executor handoff**

- コード中心の作業は、Codex、Claude Code、Hermes runtime、または選ばれた
  executor へ渡せる形で準備できます。
- Worktree と session helper により、関係ない repo 状態を混ぜずに
  subagent 作業を開き、接続し、記録し、レビューできます。

**証拠を分けて扱う運用**

- Status card は plan、handoff、dispatch、result、verification、review、
  CI、merge-readiness の証拠を分けます。
- Runtime と plugin の観測値は標準で metadata-only です。raw prompt、
  platform event、log を漏らさず、有用な報告を作れます。

**学習ループ**

- 取りこぼしたルート、弱いワークフロー、品質 gap、regression case は
  workflow-learning trace、review queue、patch proposal につなげられます。
- OMH は、準備済み handoff がもう実行済みであるかのようには扱いません。
  観測された結果をもとに改善します。

<br>

## リクエストの流れ

OMH は流れをシンプルに、見える形に保ちます。Hermes はひとつのチームモデルに
固定されず、依頼に合う最小の役割経路を選びます。

```text
plain request
  -> workflow lane を選ぶ
  -> plan、source brief、handoff を準備する
  -> evidence があるときだけ execution / review / CI を観測する
  -> Hermes chat に次のアクションを返す
```

| リクエストの形 | よくある流れ |
| --- | --- |
| 短い回答または setup repair | Hermes が説明し、OMH が local state を確認して次のコマンドをすすめます。 |
| Research または product signal | 実装前に source finder / research / brief workflow を通します。 |
| Coding task | Codex、Claude Code、Hermes、または選ばれた runtime への scoped handoff を準備します。 |
| Release または review question | 準備された主張と、実際の test、review、CI、merge evidence を分けて扱います。 |

<br>

## ドキュメント

1. ドキュメント全体の地図: [Documentation](docs/README.md)
2. インストール、更新、再適用、削除、installer flag: [Installation](docs/INSTALLATION.md)
3. AI agent に貼り付けやすいインストール手順: [Agent Install](INSTALL_FOR_AGENTS.md)
4. プロダクトの方向性と境界: [Direction](docs/DIRECTION.md)
5. アーキテクチャと module ownership: [Architecture](docs/ARCHITECTURE.md)
6. Hermes/plugin/wrapper 向け capability manifest: [Capabilities](docs/CAPABILITIES.md)
7. orchestration pattern contract: [Orchestration Patterns](docs/ORCHESTRATION_PATTERNS.md)
8. common oh-my runtime parity と gap: [Parity Matrix](docs/PARITY.md)
9. 状況別 playbook: [Playbooks](docs/PLAYBOOKS.md)
10. role surface と profile pack: [Roles](docs/ROLES.md)
11. memory/context review と handoff pack: [Memory Context Review](docs/MEMORY_CONTEXT.md)
12. Discord-style と plugin-native wrapper の例: [Chat Wrapper Examples](docs/CHAT_WRAPPER_EXAMPLES.md)
13. harness quality contract: [Harness Quality Contract](docs/HARNESS_QUALITY.md)
14. 代表的な workflow: [Application Cases](docs/APPLICATION_CASES.md)
15. public website source: [GitHub Pages site](site/index.html)

<br>

## 開発

開発、release smoke、product readiness、evidence bundle の詳細は
[Release](docs/RELEASE.md) にあります。source checkout で軽く確認するなら、
次を実行します。

```sh
PYTHONPATH=tests uv run python -m unittest discover -s tests -v
uv run python -m compileall -q src tests
uv run python -m omh.cli docs workflows --check
uv run --no-editable omh recommend "risky refactor" --limit 1 --json
```

最後のコマンドは意図的に `uv run --no-editable` を使います。source checkout が
パッケージ済みの `omh` console script を import して実行できることを確かめる
ためです。通常の利用では、curl installer が表示したインストール済みの `omh`
コマンドを使ってください。

OMH 1.0.2 は quality gate を通過した stable baseline です。より豊かな
profile activation probe と artifact-backed wrapper example は roadmap と
release docs で追跡しています。
