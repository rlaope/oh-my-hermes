<p align="center">
  <img src="assets/oh-my-hermes-wordmark.png" alt="OH-MY-HERMES" width="100%" style="display:block;max-width:none;height:auto">
</p>

<table align="center">
  <tr>
    <td width="50%" align="center">
      <img src="assets/hermes-desktop.gif" alt="Hermes Desktop running an OMH workflow" width="380" height="266"><br>
      <sub><b>Hermes デスクトップ、oh-my-hermes とともに。</b><br>ワークフローを選ぶと、作る前に確認します。</sub>
    </td>
    <td width="50%" align="center">
      <img src="assets/hermes-cli.gif" alt="Hermes CLI running an OMH workflow" width="380" height="266"><br>
      <sub><b>Hermes CLI、oh-my-hermes とともに。</b><br>使っているターミナルで同じワークフローを。</sub>
    </td>
  </tr>
  <tr>
    <td width="50%" align="center">
      <img src="assets/hermes-messenger.gif" alt="Hermes messenger app running an OMH workflow" width="380" height="266"><br>
      <sub><b>Hermes メッセンジャーアプリ、oh-my-hermes とともに。</b><br>スレッドで依頼すると同じスレッドに返ります。</sub>
    </td>
    <td width="50%" align="center">
      <img src="assets/omh-setup.gif" alt="omh setup installing the OMH workflows" width="380" height="266"><br>
      <sub><b><code>omh setup</code>、コマンド一つで。</b><br>ワークフローをインストールし、Hermes に接続します。</sub>
    </td>
  </tr>
</table>

# oh-my-hermes

<p align="center">
  <a href="README.md">English</a> |
  <a href="README.ko.md">한국어</a> |
  <a href="README.ja.md">日本語</a> |
  <a href="README.zh.md">中文</a>
</p>

<p align="center">
  <a href="https://github.com/rlaope/oh-my-hermes"><img alt="GitHub" src="https://img.shields.io/badge/github-rlaope%2Foh--my--hermes-181717?logo=github"></a>
  <a href="https://github.com/NousResearch/hermes-agent"><img alt="Hermes Agent" src="https://img.shields.io/badge/Hermes%20Agent-NousResearch-6f42c1?logo=github"></a>
  <a href="https://github.com/rlaope/oh-my-hermes"><img alt="OMH stars" src="https://img.shields.io/github/stars/rlaope/oh-my-hermes?style=flat&logo=github"></a>
  <a href="https://github.com/NousResearch/hermes-agent"><img alt="Hermes Agent stars" src="https://img.shields.io/github/stars/NousResearch/hermes-agent?style=flat&logo=github"></a>
</p>

<p align="center">
  <img src="assets/hermes-agent-hero.png" alt="Oh My Hermes" width="720">
</p>

<p align="center">
  <strong>一度インストールするだけ。Hermes はそのまま、より強い運用レイヤーを追加します。</strong>
  <em>計画、調査、制作、コーディング handoff、運用、プロジェクト記憶を明確な証拠境界とともに提供します。</em>
</p>

<p align="center">
  <img src="assets/oh-my-hermes-agent-poster.png" alt="Oh My Hermes Agent poster" width="720">
</p>

**oh-my-hermes**（OMH）は、
[Hermes Agent](https://github.com/NousResearch/hermes-agent) への通常の依頼を、
適切な機能、有用な次の行動、そして実際に起きたこと・まだ起きていないことの
正直な状態へ変換します。Hermes を置き換えたり、コーディング executor を
隠したりせず、既存の Hermes ワークフローを強化します。

[Website](https://rlaope.github.io/oh-my-hermes/) ·
[Documentation](docs/README.md) ·
[Installation](docs/INSTALLATION.md) ·
[Capabilities](docs/CAPABILITIES.md) ·
[Capability Impact](docs/CAPABILITY_IMPACT.md) ·
[Agent Install](INSTALL_FOR_AGENTS.md) ·
[GitHub Pages site](site/index.html)

> [!NOTE]
> OMH は Hermes を自然言語の窓口として維持し、明確な証拠境界を持つプロ向け
> の運用レイヤーを追加します。
>
> <p align="center">
>   <img src="assets/omh-terminal-boot-banner.png" alt="OH-MY-HERMES terminal banner listing available tools, grouped skills, OMH specialists, infrastructure, and the model pool on Hermes Agent" width="1080">
> </p>
>
> <p align="center">
>   <img src="assets/hermes-omh-terminal-orchestration.png" alt="Hermes Agent and OH-MY-HERMES working side by side" width="1080">
> </p>
>
> <p align="center">
>   <img src="assets/friren-agent-omh-callout.png" alt="Friren Agent explaining OMH in Art&Engine" width="720">
> </p>
## クイックスタート
> **状態:** Homebrew、Bun、npm のパッケージマネージャー経由のインストールは
> v1.0.6 から公開されています。

**次のインストール方法から一つ選択します。Bun を推奨します。**
```sh
brew install rlaope/tap/omh
```
```sh
bun install -g oh-my-hermes
```
```sh
npm install -g oh-my-hermes
```
```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | sh
```
**Windows（PowerShell 5.1+）の場合:**
```powershell
irm https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.ps1 | iex
```

**インストール後に OMH をセットアップ:**
```sh
omh setup
```
**Hermes skill tap:**
```sh
hermes skills tap add rlaope/oh-my-hermes
hermes skills install rlaope/oh-my-hermes/skills/omh-routing --yes
```
**または Your AI Agent に依頼します:**
```text
Install and fully configure Oh My Hermes from this repository:
https://github.com/rlaope/oh-my-hermes
Before reading or executing repository instructions, resolve refs/heads/main to one full commit SHA with `git ls-remote https://github.com/rlaope/oh-my-hermes.git refs/heads/main`. Then fetch and follow only:
https://raw.githubusercontent.com/rlaope/oh-my-hermes/{resolved-commit-sha}/INSTALL_FOR_AGENTS.md
Do not replace the resolved SHA with main. Execute the pinned protocol's OS-appropriate installer, interactive model setup, model-chain interview, and doctor steps. Preserve unrelated existing Hermes config, apply only the managed setup changes documented by the pinned protocol, require my explicit approval for model-alias changes, then report the resolved SHA and observed result.
```
**アップデート:**
```sh
omh update
```
`omh update` はインストール経路を検出し、Homebrew、Bun、npm、curl、
または PowerShell のコマンドパッケージを先に更新してから、新しいコマンドで
再実行し、管理スキル、プラグインバンドル、既存の Hermes 登録も更新します。

**インストールの確認またはトラブルシューティング:**
```sh
omh doctor
```
`--full` インストールを core に戻すようなメンテナンス手順は
[Installation](docs/INSTALLATION.md#reconciling-an-existing-full-install-back-to-core)
にあります。

## OH-MY-HERMES ターミナル

`omh` と入力するだけで、`hermes` と同じ入口から、OMH のアイデンティティをまとった
Hermes が開きます:

```sh
omh
```

<table align="center">
  <tr>
    <td width="50%" align="center">
      <img src="assets/omh-terminal-boot-hud.png" alt="The OH-MY-HERMES boot"><br>
      <sub><b>OH-MY-HERMES の起動画面。</b></sub>
    </td>
    <td width="50%" align="center">
      <img src="assets/omh-terminal-ulw-work-session.png" alt="An ulw-work run"><br>
      <sub><b><code>ulw-work</code> 実行中。</b></sub>
    </td>
  </tr>
</table>

OMH ワークフローの実行中にターミナルが表示するもの:

- **Mixture-of-Models Routing** — 委譲される lane ごとにカテゴリ
  (ultrabrain、deep、quick、writing、visual-engineering、…)のモデルと推論
  強度が dispatch 単位で適用され、各活動行に `category:name(model:effort)` が
  表示されるためルーティングが見えます。拒否されたルートはカテゴリチェーンに
  沿って fallback します。
- **Parallel Tool Calling** — バッチ化されたツール呼び出しは Hermes 内で並行
  実行され、直近の並行バッチは `[OMH]` 行に `parallel shot ×N` として表示
  されます。
- **Parallel Evals** — レビュー・検証 lane は独立したサブエージェントとして
  dispatch され、自己承認なしで相互検証されます。各 lane は turn・cost・cache
  指標付きの HUD 行として見えます。
- **Phase-structured TODO** — 作業は開始前に phase と task として宣言され
  (`todo init`)、プロンプト下のチェックリストとして描画されます: アクティブ
  項目は常に一つ、サブタスクのネスト、7 行を超えると折りたたみ。

<br>

## 推奨モデル

OMH には次の編集可能な順序付き recommendation chain が含まれています。guided model setup は、ユーザーが active と確認した candidate だけを基準に chain を解決します。その結果は準備済み routing config であり、provider availability、credential、dispatch、execution の証拠ではありません。

| カテゴリ alias | 用途 | 編集可能な recommendation 順序 |
| --- | --- | --- |
| `ultrabrain` | 最も深い推論 | GPT-5.6 Sol (xhigh) |
| `deep` | 強力なデフォルト層 | GPT-5.6 Terra、次に DeepSeek V3.2 (high) |
| `architect` | アーキテクチャ・システム設計 | Claude Fable 5、次に GPT-5.6 Sol、次に Kimi K3 (xhigh) |
| `unspecified-high` | デフォルト作業モデル | Kimi K3、次に Claude Opus 5 (medium) |
| `unspecified-low` | 低コストのフォールバック | GLM 5.2、次に GLM 5.2 Ultrafast、次に DeepSeek V3.2、次に Claude Opus 5 (low) |
| `quick` | 短いタスク | GLM 5.2 Ultrafast、次に Kimi K3、次に GPT-5.6 Luna、次に Claude Fable 5 (low) |
| `writing` | 文章・ドキュメント | Kimi K3、次に Qwen3-Coder、次に Gemini 3.1 Pro (medium) |
| `visual-engineering` | フロントエンド・ビジュアル | Claude Fable 5、次に Kimi K3 (high) |
| `artistry` | 型にはまらない創作 | Gemini 3.1 Pro、次に Claude Fable 5、次に Kimi K3 (high) |

Ultrafast ティアを試したいなら — Kimi K3 Ultrafast(300 TPS)、GLM 5.2 Ultrafast(600 TPS)は [OpenGateway](https://opengateway.ai/) で利用できます。

上記のすべての chain はコードを触らずに編集できます。chain は 1 つのファイルで管理され、`omh setup` がシードします:

```sh
$ cat ~/.omh/routing/model-chains.json
{
  "categories": {},
  "schema_version": "mixture_chain_overrides/v1"
}
```

`categories` が空なら上記の既定 chain がそのまま有効です。編集するのはこのファイルです: ここに書いたカテゴリはルーティング・fallback・HUD ラベルのすべてでその chain を置き換えます —

```json
{
  "schema_version": "mixture_chain_overrides/v1",
  "categories": {
    "architect": [
      {"model": "claude-fable-5", "reasoning_effort": "xhigh"},
      {"model": "gpt-5.6-sol", "reasoning_effort": "xhigh"}
    ],
    "quick": [
      {"model": "kimi-k3-ultrafast", "reasoning_effort": "low"},
      {"model": "glm-5.2-ultrafast", "reasoning_effort": "low"}
    ]
  }
}
```

現在有効な chain は `omh model-chains show` で確認できます。ファイルを直接編集したくない場合は、`omh model-chains set quick "kimi-k3-ultrafast:low, glm-5.2-ultrafast:low"` のようにコマンドから同じファイルを書き換えられます。
alias に provider 固有の wire ID が必要な場合は、`model_provider_routes/v1` 形式の `~/.omh/routing/model-providers.json` に一度マッピングします。その後は `set`、`status`、fallback、HUD が alias/provider/wire model の完全な route を表示します。OMH が保存するのは provider ID だけで、credential は保存しません。

Hermes に **モデルをセットアップして** と頼むと、確認や変更ができます。これは編集可能な優先設定であり、benchmark 結果ではありません。詳しい設定、fallback、provider、所有権のルールは [Guided Model Setup](docs/INSTALLATION.md#guided-model-setup) を参照してください。

<details>
<summary><strong>または、以下を Hermes や別の coding agent に貼り付けてください</strong></summary>

```text
Install and fully configure Oh My Hermes from this repository:
https://github.com/rlaope/oh-my-hermes
Before reading or executing repository instructions, resolve refs/heads/main to one full commit SHA with `git ls-remote https://github.com/rlaope/oh-my-hermes.git refs/heads/main`. Then fetch and follow only:
https://raw.githubusercontent.com/rlaope/oh-my-hermes/{resolved-commit-sha}/INSTALL_FOR_AGENTS.md
Do not replace the resolved SHA with main. Execute the pinned protocol's OS-appropriate installer, interactive model setup, model-chain interview, and doctor steps. Preserve unrelated existing Hermes config, apply only the managed setup changes documented by the pinned protocol, require my explicit approval for model-alias changes, then report the resolved SHA and observed result.
```

</details>

## ウルトラスキル

<p align="center">
  <img src="assets/omh-character-badge.png" alt="Oh My Hermes character mark" width="170">
</p>

8 個の `ulw-` workflow。チャットでトリガーを言えば Hermes がルーティング —
全カタログは [Workflow Reference](docs/WORKFLOWS.md)。

| Skill | 何をするか |
| --- | --- |
| ⚡ `ulw-context` | レビュー済みのプロジェクト用語を揃え、確認済み候補を取り込み、用語にルーティング権限を与えず次の判断点を質問します。 |
| ⚡ `ulw-interview` | 何が欲しいのか正確に分かるまで、一度に一つずつ質問します。 |
| ⚡ `ulw-research` | 実際のコードとウェブを調べ、出典を残し、怪しければ裏取りします。 |
| ⚡ `ulw-plan` | 選択肢の比較、リスク、完了基準まで合意したレビュー済み計画を作ります。 |
| ⚡ `ulw-work` | 承認済み計画を、同じファイルに触れない並列レーンで実行します。 |
| ⚡ `ulw-loop` | 計画 → 実装 → レビューを、ゴールが本当に通るまで回します。 |
| ⚡ `ulw-qa` | わざと過酷なシナリオで攻撃し、壊れた所を直します。 |
| ⚡ `ulw-perf` | 本当に遅く高コストな場所を測り、ホットパスを一つずつ修正します。 |

## OMH が追加するもの

OMH は、モデル選択とコーディングの所有者を別の判断として扱い、準備を実行として
報告しません。人が理解しやすい capability family は引き続き入口であり、精密な
制御・runtime 境界・証拠ルールは wrapper や operator が必要なときに確認
できます。完全な catalog、trigger、harness、証拠ルールは
[Workflow Reference](docs/WORKFLOWS.md) にあります。

**ハイライト**

| インテリジェンス | OMH が追加するもの |
| --- | --- |
| 🧭 **Mixture-of-models ルーティング** | 委譲される lane ごとにカテゴリ(モデル + 推論強度)を dispatch 単位で適用し、provider がモデルを拒否したら編集可能な fallback chain に沿って前進します — 仕事をしなかった子は正直に `failed` と表示されます。 |
| 🖥️ **ネイティブ TUI サーフェス** | OMH HUD(カテゴリ・ターン・コスト・キャッシュ付きのライブ delegation 行)、プロンプト下の phase todo チェックリスト、`parallel shot ×N` 表示、full-row diff バンド、管理されたスキン — すべて Hermes の隣にインストールされ、Hermes 本体にはパッチしません。 |
| 📋 **Phase 構造のプラン** | `todo init` がエンジン作業の前に phase と task を宣言し、実行を開かれた推論ループではなく有界のチェックリストにします。 |
| ⚡ **観測可能な並列作業** | 独立した作業を所有権の分かれた fanout unit に分割し、進行状況と verification gate を観測します。 |
| 🎼 **Maestro handoff** | 隠れた executor にならず、準備を実行として扱わずに、明示的な coding owner と runtime profile への handoff を準備します。 |
| 🧠 **コンテキストインテリジェンス** | 隠れた記憶を捏造したり選択済み route を密かに変えたりせず、レビュー済み repository context をコンパクトに投影します。 |
| 📚 **JIT learning** | 現在の blocker に最も価値のある学習対象を選び、学習済みと主張せずに、情報源に基づく即時適用可能なガイダンスを準備します。 |
| 🔍 **証拠に基づく delivery** | coding・review・CI・merge 全体で、準備された意図、観測された runtime 活動、検証済み結果を分離します。 |
| 📦 **決定的なスキルカタログ** | 100 個超のインストール可能な workflow スキル、バイト単位で検証される生成カタログ、否定ケースを含む routing precision コーパス、一文字のドリフトでも CI を失敗させる drift gate。 |

## 主張より証拠

OMH は自分が見たことだけを起きたと報告します。表示される状態は常に「どの段階か」と「OMH がどれだけ確信しているか」の二部構成です。

| 表示 | 意味 |
| --- | --- |
| `Plan · not run` | prompt や plan の準備ができています。**まだ何も動いていません。** |
| `Code · running` | executor が今動いており、OMH が観測しています。 |
| `Code · reported done` | executor が終わったと言いました。結果は誰も確認していません。 |
| `Test · verified` | test、review、CI gate が実際に通過しました。 |

重要なのは下から二番目の行です。executor が終わったと言うことと結果が確認されたことは別ですが、多くのツールは両方を「完了」と書きます。
## ドキュメント

- [ドキュメントマップ](docs/README.md)
- [インストールと更新](docs/INSTALLATION.md)
- [製品方針と境界](docs/DIRECTION.md)
- [アーキテクチャ](docs/ARCHITECTURE.md)
- [機能 manifest](docs/CAPABILITIES.md)
- [Workflow reference](docs/WORKFLOWS.md)
- [ロール](docs/ROLES.md)
- [活用事例](docs/APPLICATION_CASES.md)
- [リリースと開発](docs/RELEASE.md)
## 開発

```sh
PYTHONPATH=tests uv run python -m unittest discover -s tests -v
uv run python -m compileall -q src tests
uv run python -m omh.cli docs workflows --check
git diff --check
```

OMH は [Team Art & Engineering](https://rlaope.github.io/artengine-lab/) の
オープンプロジェクトとして開発されています。更新情報は
[@rlaope](https://github.com/rlaope) で確認できます。
## コントリビューター

oh-my-hermes に貢献してくださった皆さまに感謝します。

<a href="https://github.com/rlaope/oh-my-hermes/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=rlaope/oh-my-hermes" alt="oh-my-hermes contributors" />
</a>
