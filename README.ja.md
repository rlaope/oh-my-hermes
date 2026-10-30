<div align="center">

<br>

<img src="assets/oh-my-hermes-wordmark.png?v=spectrum" alt="OH-MY-HERMES" width="70%">

<br>
<br>

<img src="assets/omh-logo.png" alt="oh-my-hermes のロゴ: 白い角丸の正方形タイルに太い黒線で描いた oh-my-hermes のキャラクター" width="200">

<br>
<br>

**Hermes Agent のためのオールインワンパッケージ。一度インストールしたら、`dag-ulw` と入力するだけ。**

[![GitHub Release](https://img.shields.io/github/v/release/rlaope/oh-my-hermes?color=58a6ff&labelColor=black&logo=github&style=flat-square)](https://github.com/rlaope/oh-my-hermes/releases) [![npm downloads](https://img.shields.io/npm/dt/oh-my-hermes?color=3fb950&labelColor=black&logo=npm&label=downloads&style=flat-square)](https://www.npmjs.com/package/oh-my-hermes) [![GitHub Contributors](https://img.shields.io/github/contributors/rlaope/oh-my-hermes?color=bc8cff&labelColor=black&style=flat-square)](https://github.com/rlaope/oh-my-hermes/graphs/contributors) [![GitHub Stars](https://img.shields.io/github/stars/rlaope/oh-my-hermes?color=e3b341&labelColor=black&style=flat-square)](https://github.com/rlaope/oh-my-hermes/stargazers) [![License](https://img.shields.io/github/license/rlaope/oh-my-hermes?color=white&labelColor=black&style=flat-square)](LICENSE) [![Docs](https://img.shields.io/badge/docs-omher.app-58a6ff?labelColor=black&logo=readthedocs&logoColor=white&style=flat-square)](https://omher.app/)

[English](README.md) | [简体中文](README.zh.md) | [日本語](README.ja.md) | [Русский](README.ru.md) | [한국어](README.ko.md) | [Español](README.es.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | [Português (Brasil)](README.pt-BR.md) | [Italiano](README.it.md)

**oh-my-hermes** は [Hermes Agent](https://github.com/NousResearch/hermes-agent) の上に載る運用レイヤーです。<br>
話しかける相手は Hermes のまま。OMH がスキルと lane ごとのモデルを選び、作業を並列で回します。<br>
Hermes にパッチを当てたり置き換えたりせず、計画しただけの作業を完了とは報告しません。

</div>

## インストール

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | sh
omh setup
```

[Windows とその他の方法 →](docs/INSTALLATION.md)

<br>

## 得られるもの

- **lane ごとに合うモデル。**<br>
  lane ごとに作業カテゴリが付きます: `ultrabrain`、`deep`、`visual-engineering`、`quick` など。<br>
  カテゴリがその lane のモデル chain と推論強度を決め、chain はすべて編集できます。<br>
  provider がモデルを拒否すると、黙ってダウングレードせず chain の次のモデルへ進みます。<br>
  `omh model` でピッカーが開きます。[lane ごとのモデル](docs/INSTALLATION.md#guided-model-setup)

- **`/dag-ulw` のグラフ実行。**<br>
  目標は小さなノードのグラフになり、準備のできたノードから並列に走ります。<br>
  各ノードはカテゴリのモデルと effort で動き、同時に走るノード同士は書き込み範囲を共有しません。<br>
  別のノードが目標を確認し、失敗したノードは報告前に修復されます。

- **必要なときに専門スキル。**<br>
  フロントエンド、バックエンド、Rust、セキュリティレビュー、検証ゲートなど 100 を超える `omh-*` スキル。<br>
  呼び出さなくても、ルーターが合うスキルをツール呼び出しとして実行に加えます。

- **信頼できる長期メモリ。**<br>
  黙って記憶しません。候補ごとに、記憶・却下・保留を理由とともに残します。<br>
  次のセッションは、タスクに合わせて順位付けし、トークン予算に収めた recall pack を受け取ります。<br>
  Hermes 自身のメモリは読みも書き換えもしません。

- **OMH Native.**<br>
  `omh` は Hermes の gateway 上で OMH 独自の TUI を開き、起動時の見た目は `/theme` で切り替えます。<br>
  `/dag-ulw` はボックスグラフを出し、lane ごとのモデル・effort・トークンが見えるライブツリーを表示します。<br>
  エージェント一覧から steer や中断ができ、`!` でシェルを実行し、Esc Esc で巻き戻せます。

- **「完了」の前に証拠。**<br>
  どの状態も、段階と確からしさを一緒に示します。<br>
  `Plan · not run` · `Code · reported done` · `Test · verified`<br>
  テスト、レビュー、CI ゲートが実際に通って初めて verified になります。

<br>

## DAG-ULW

**`/dag-ulw` と打つだけで、あなたもグラフエンジニアリングの達人。**

目標は小さなノードのグラフになり、ノードごとに自分のモデルで並列に走ります。<br>
別のノードが目標を検証してから、報告が届きます。

<p align="center">
  <img src="assets/omh-dag-ulw-tui.gif" alt="/dag-ulw を実行する OMH TUI: プロンプトを入力すると 7 レーンのボックスグラフが定義され、レーンが Claude Opus 5.5、GPT-6.1 Sol、DeepSeek V4.1 Flash、GLM 5.3、Kimi K3.1 Pro でレイヤーごとに走り、すべて accepted で終わります" width="900">
</p>

> [!TIP]
> 一緒に参加しましょう！
>
> <table>
>   <tr>
>     <td width="124"><a href="https://x.com/rlaope"><img alt="X link" src="https://img.shields.io/badge/Follow-%40rlaope-00CED1?style=flat-square&logo=x&labelColor=black" width="112" /></a></td>
>     <td><code>oh-my-hermes</code> の更新情報は、リリースノートやプロジェクトのニュースとともに X の <a href="https://x.com/rlaope">@rlaope</a> で共有されます。</td>
>   </tr>
>   <tr>
>     <td width="124"><a href="https://github.com/rlaope"><img alt="GitHub Follow" src="https://img.shields.io/github/followers/rlaope?style=flat-square&logo=github&labelColor=black&color=24292f" width="112" /></a></td>
>     <td>その他のプロジェクト、リリース、進行中の作業は GitHub で <a href="https://github.com/rlaope">@rlaope</a> をフォローしてください。</td>
>   </tr>
>   <tr>
>     <td width="124"><a href="https://discord.gg/6EjTP3cWM"><img alt="Discord invite" src="https://img.shields.io/badge/Join-Discord-5865F2?style=flat-square&logo=discord&logoColor=white&labelColor=black" width="112" /></a></td>
>     <td>Discord の <a href="https://discord.gg/6EjTP3cWM">Oh-My-Hermes Community</a> に参加して、質問したり、ワークフローを共有したり、他のユーザーと交流しましょう。</td>
>   </tr>
>   <tr>
>     <td width="124"><a href="https://github.com/rlaope/oh-my-hermes/graphs/contributors"><img alt="AI agent collaborators" src="https://img.shields.io/badge/With-AI%20agents-6f42c1?style=flat-square&labelColor=black" width="112" /></a></td>
>     <td><code>oh-my-hermes</code> の開発を支える AI エージェント <a href="https://github.com/frirenai"><strong>Friren</strong></a> と <a href="https://github.com/sionic-khope"><strong>Kami</strong></a> とともに作られています。</td>
>   </tr>
>   <tr>
>     <td width="124"><a href="https://nousresearch.com/"><img alt="Thanks to Nous Research" src="https://img.shields.io/badge/Thanks-Nous%20Research-4B2E83?style=flat-square&labelColor=black" width="112" /></a></td>
>     <td>Hermes Agent を生み出した <a href="https://nousresearch.com/">Nous Research</a> に感謝します。</td>
>   </tr>
> </table>

> **スポンサー** oh-my-hermes を支えてくださっているスポンサーです。
>
> <table>
>   <tr>
>     <td width="160" align="center"><a href="https://opengateway.ai/"><img alt="OpenGateway" src="assets/sponsors/opengateway.svg" width="140" /></a></td>
>     <td><a href="https://opengateway.ai/"><strong>OpenGateway</strong></a> が oh-my-hermes をスポンサーしています。オープンソースへのご支援に感謝します。<br>複数のモデル provider を OpenAI 互換のエンドポイント一つにまとめ、自動フェイルオーバーも備えています。</td>
>   </tr>
> </table>

<br>

## その他

[ドキュメント](docs/README.md) · [インストール](docs/INSTALLATION.md) · [Capabilities](docs/CAPABILITIES.md) · [Workflows](docs/WORKFLOWS.md) · [ウェブサイト](https://omher.app/)

<details>
<summary><b>インストールの選択肢</b></summary>

**macOS / Linux:**

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | sh
```

**Windows (PowerShell 5.1+):**

```powershell
irm https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.ps1 | iex
```

**または、次の内容を AI エージェントに貼り付けます:**

```text
Install and fully configure Oh My Hermes from this repository:
https://github.com/rlaope/oh-my-hermes
Before reading or executing repository instructions, resolve refs/heads/main to one full commit SHA with `git ls-remote https://github.com/rlaope/oh-my-hermes.git refs/heads/main`. Then fetch and follow only:
https://raw.githubusercontent.com/rlaope/oh-my-hermes/{resolved-commit-sha}/INSTALL_FOR_AGENTS.md
Do not replace the resolved SHA with main. Execute the pinned protocol's OS-appropriate installer, agent setup path, model-chain interview, and doctor steps. Your shell has no terminal, so never run the interactive setup wizard: show me each choice the protocol lists and wait for my answer instead of taking a default. Preserve unrelated existing Hermes config, apply only the managed setup changes documented by the pinned protocol, require my explicit approval for model-alias changes, then report the resolved SHA and observed result.
```

**アップデート:**

```sh
omh update
```

`omh update` はインストール経路を検出し、そのインストーラーでコマンドを更新してから、管理スキル、プラグインバンドル、Hermes 登録も更新します。

**インストールの確認またはトラブルシューティング:**

```sh
omh doctor
```

```sh
# 作業カテゴリごとのモデル設定（矢印キー: カテゴリ、←→ head モデル、-/+ effort）;
# OMH TUI(omh)では /omh-model が同じピッカーを開きます:
omh model
# 新しいモデルファミリーをオンボーディングするには、Hermes でこのスキルを使ってください:
/omh-model-setup
```

**Homebrew:**

```sh
brew install rlaope/tap/omh
```

**Bun:**

```sh
bun install -g oh-my-hermes
```

**npm:**

```sh
npm install -g oh-my-hermes
```

Bun と npm には PATH 上の Node 18 以降と Python 3.11 以降が必要です。Homebrew は独自の Python を
入れます。どの方法でインストールしても、その後に `omh setup` を実行します。

**Hermes skill tap:**

```sh
hermes skills tap add rlaope/oh-my-hermes
hermes skills install rlaope/oh-my-hermes/skills/omh-routing --yes
```

**パッケージマネージャーでの手動フォールバックまたは削除:**

| インストール元 | CLI のアップグレード | CLI の削除 |
| --- | --- | --- |
| Homebrew | `brew upgrade rlaope/tap/omh` | `brew uninstall omh` |
| Bun | `bun update -g --latest oh-my-hermes` | `bun remove -g oh-my-hermes` |
| npm | `npm update -g oh-my-hermes` | `npm uninstall -g oh-my-hermes` |

`omh update` がインストーラーを見つけられないと報告したときだけ、マネージャーのコマンドを直接使います。コマンドパッケージを削除しても OMH の状態は残ります。完全に削除するには、マネージャーの削除コマンドの前に `omh uninstall --all` を実行します。

`--full` インストールを core に戻すようなメンテナンス手順は [Installation](docs/INSTALLATION.md#reconciling-an-existing-full-install-back-to-core) にあります。

</details>

<details>
<summary><b>リファレンス</b></summary>

### ウルトラスキル

10 個の `ulw-` workflow。チャットでトリガーを言えば Hermes がルーティング — 全カタログは [Workflow Reference](docs/WORKFLOWS.md)。

| Skill | 何をするか |
| --- | --- |
| ⚡ `ulw-context` | レビュー済みのプロジェクト用語を揃え、確認済み候補を取り込み、用語にルーティング権限を与えず次の判断点を質問します。 |
| ⚡ `ulw-interview` | 何が欲しいのか正確に分かるまで、一度に一つずつ質問します。 |
| ⚡ `ulw-research` | 実際のコードとウェブを調べ、出典を残し、怪しければ裏取りします。 |
| ⚡ `ulw-plan` | 選択肢の比較、リスク、完了基準まで合意したレビュー済み計画を作ります。 |
| ⚡ `ulw-work` | 承認済み計画を、同じファイルに触れない並列レーンで実行します。 |
| ⚡ `dag-ulw` | 大きな作業を小さな並列ノードのグラフとして実行し、別ノードで目標を検証して、失敗した部分を修復します。 |
| ⚡ `ulw-maestro` | Claude Code または Codex に委任したタスクを実行 — そのCLI自身のインストール済みスキルから組み立てたプロンプトで、ライブに起動し、ドック行とスティアリング可能なセッションを持ちます。 |
| ⚡ `ulw-loop` | 計画 → 実装 → レビューを、ゴールが本当に通るまで回します。 |
| ⚡ `ulw-qa` | わざと過酷なシナリオで攻撃し、壊れた所を直します。 |
| ⚡ `ulw-perf` | 本当に遅く高コストな場所を測り、ホットパスを一つずつ修正します。 |

#### おすすめの組み合わせ

Hermes のプロンプトにこう入力します。`ulw-` の接頭辞が workflow を選び、残りは普段の言葉で書いた依頼です。

**1. 形にする。** アイデアがまだ曖昧なら `ulw-interview`、変更内容は決まっていてもリスクがあるなら `ulw-plan`。

```text
❯ ulw-interview: I want a CLI that tracks the ISS and warns me before it passes overhead
❯ ulw-plan: analyze this project's circular dependencies and plan the refactor
```

**2. 作る。** `ulw-work` が承認済みの計画を、同じファイルに触れない並列レーンで実行します。

```text
❯ ulw-work: run the accepted plan
```

**3. 仕上げる。** `ulw-loop` は指定したゲートが通るまで回り続けます。

```text
❯ ulw-loop: keep going until npm test passes
```


### Hermes との連携の仕組み

Hermes Agent はすでにループを回しています。OMH はそのループに何を入れるかを決めます。どの lane にどのモデルと推論強度を与えるか、コード変更の owner は誰か、どのスキルを適用するか、何を完了とみなすかです。どこでも二つのルールが守られます。モデル選択とコーディングの所有権は別々の決定であり、準備されたものを実行済みとして報告することは決してありません。生成カタログ、trigger、証拠ルールは [Workflow Reference](docs/WORKFLOWS.md) にあります。

### 作業の流れ

**理解 → 調査 → 判断 → 計画 → 実行 → 検証 → 運用 → 学習**

| 段階 | 行うこと |
| --- | --- |
| 理解 | 意図、制約、プロジェクト用語、停止条件を確認します。 |
| 調査 | 仮定を、情報源に裏付けられた製品・コード・運用に関する背景情報に置き換えます。 |
| 判断 | 選択肢、トレードオフ、意思決定者を明確にします。 |
| 計画 | 合意した範囲、コード変更の担当者、テスト、完了条件を実行可能な計画にまとめます。 |
| 実行 | 準備を実行とみなすことなく、選定した担当者に範囲を限定した引き継ぎを行います。 |
| 検証 | 実際に確認したテスト、レビュー、CI、および実行時の証拠に基づいて判定します。 |
| 運用 | リリースの健全性、インシデント、ロールバックの状況、後続作業を常に可視化します。 |
| 学習 | レビュー済みで適用範囲が明確な教訓だけを、プロジェクトメモリやワークフローの改善に反映します。 |

**ハイライト**

| インテリジェンス | OMH が追加するもの |
| --- | --- |
| 🧭 **Mixture-of-models ルーティング** | 委譲される lane ごとに、dispatch 時点でカテゴリ（モデル + 推論強度）が付きます。provider がモデルを拒否すれば chain を下り、仕事をしなかった子は緑の行ではなく `failed` と表示されます。 |
| 🎛️ **モデル系列ごとのキャリブレーション** | GPT-6 Astra、GPT-5.6、Claude 5.5、GLM 5.3、Kimi、Gemini、Qwen、DeepSeek など、系列と世代ごとにプロンプティングを調整し、ベンチマークのペアが効果を示す間だけ維持します。 |
| 🗂️ **自分で所有するカテゴリ** | 標準のモデルカテゴリ、`omh model-chains set` による並べ替え、マシンごとに chain を並べ替える entitlement インタビュー、実行前にリクエストがどこへルーティングされるかを示すライブビュー。 |
| 🖥️ **ネイティブ TUI サーフェス** | OMH HUD（カテゴリ・ターン・コスト・キャッシュ付きのライブ行）、プロンプト上の phase todo、`parallel shot ×N`、full-row diff バンド、自分で選ぶテーマ。`omh` が開く OMH TUI に表示され、Hermes にパッチは当てません。 |
| ⚡ **観測できる並列作業** | 独立した作業を、ファイル所有権が重ならない fanout unit に分割し、provider 負荷に応じた admission control、型付きの結果 sidecar、返ってきた結果を読む verification gate を付けます。 |
| 💸 **価格付きコストテレメトリ** | すべての HUD 行と run summary にトークン数とドル金額を表示します。出典を明記した料金表で計算し、計算できない run は `$0` ではなく `unknown` と読めます。 |
| 🧠 **長期プロジェクトメモリ** | Hermes が読み込むファイルベースの memory provider、admission と retention のポリシー、レビュアーが承認する書き込み、freshness と budget を持つ recall pack。Hermes 自身のメモリには触れません。 |
| 🔎 **構造的コード検索** | 計測に基づく `ast-grep` プレイブック（28 言語、grep フォールバック）と、リポジトリ全体のアーキテクチャ図を描く `omh codegraph uml` を、executor がコードを読む地点に注入します。`omh codegraph tests --changed` は変更が届くテストを示します（[codegraph コマンド](docs/CODEGRAPH.md)）。 |
| 🛡️ **自分で書くガードレール** | ルールを外れた tool call を自分のルール文で遮断する toolcall rules、stub やスキップされたテストを証拠と認めない completion-integrity gate、危険な操作のための approval tier。 |
| ♾️ **ウルトラワークフローエンジン** | 並列デリバリー lane、ledger と実際の完了 gate で回る計測ループ、エンジン実行前の decision-frontier インタビュー。一覧は上のウルトラスキルにあります。 |
| 📦 **決定的なカタログ** | 一つのソースから生成される 100 以上のインストール可能なスキル、ネガティブケースを含む routing precision コーパス、1 バイトのずれで CI が失敗する drift gate。 |

### 主張より証拠

OMH は自分が見たことだけを起きたと報告します。表示される状態は常に「どの段階か」と「OMH がどれだけ確信しているか」の二部構成です。

| 表示 | 意味 |
| --- | --- |
| `Plan · not run` | prompt や plan の準備ができています。**まだ何も動いていません。** |
| `Code · running` | executor が今動いており、OMH が観測しています。 |
| `Code · reported done` | executor が終わったと言いました。結果は誰も確認していません。 |
| `Test · verified` | test、review、CI gate が実際に通過しました。 |

executor が終わったと言うことと結果が確認されたことは別ですが、多くのツールは両方を「完了」と書きます。能力影響は一つのマーケティング用スコアに畳まず、独立した次元ごとに報告します。詳しくは [Capability Impact](docs/CAPABILITY_IMPACT.md)。単独の Hermes と OMH 経由の Hermes を比べる製品 A/B レーンは、コーパスとオフラインパイロットまで揃っており、測定済みの実行はまだ公開されていません: [`benchmarks/product-ab/v1/README.md`](benchmarks/product-ab/v1/README.md)。

### ドキュメント

- [ドキュメントマップ](docs/README.md)
- [インストールと更新](docs/INSTALLATION.md)
- [エージェント向けインストール手順](INSTALL_FOR_AGENTS.md)
- [製品方針と境界](docs/DIRECTION.md)
- [アーキテクチャ](docs/ARCHITECTURE.md)
- [機能 manifest](docs/CAPABILITIES.md)
- [Workflow reference](docs/WORKFLOWS.md)
- [ロール](docs/ROLES.md)
- [活用事例](docs/APPLICATION_CASES.md)
- [モデルルーティング、ファンアウト契約、リクエスト採点](docs/FANOUT.md)
- [ファンアウト executor 証拠: セッション、障害診断、容量（agent/operator 向け）](docs/FANOUT-EXECUTOR-EVIDENCE.md)
- [Agent ボードとネイティブ Kanban 連携（agent/operator 向け）](docs/AGENT-BOARD.md)
- [モデルごとのキャリブレーションマップ](MODEL_OPTI.md)
- [証拠ルールと能力影響](docs/CAPABILITY_IMPACT.md)
- [長期記憶モデル](docs/MEMORY.md)
- [Codegraph コマンド](docs/CODEGRAPH.md)
- [Show-reel ツールキット](docs/SHOW-REEL-TOOLKIT.md)
- [Hermes で超大容量 PDF を処理する](docs/LONG-DOCUMENT-READING.md)
- [ライブモデルベンチマークと測定結果](benchmarks/live-model-tools/v1/README.md)
- [リリースと開発](docs/RELEASE.md)
- [ウェブサイト](https://omher.app/)（[ソース](site/index.html)）

### コントリビューター

<a href="https://github.com/rlaope/oh-my-hermes/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=rlaope/oh-my-hermes&max=100&columns=10" alt="oh-my-hermes contributors" />
</a>

</details>

## ライセンス

MIT、[LICENSE](LICENSE) を参照。<br>
[コントリビューター](https://github.com/rlaope/oh-my-hermes/graphs/contributors)とともに、[Team Art & Engineering](https://rlaope.github.io/artengine-lab/) のオープンプロジェクトとして開発しています。
