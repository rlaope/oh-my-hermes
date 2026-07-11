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
  <strong>一度インストールするだけ。Hermes はそのまま、より強い運用レイヤーを追加します。</strong>
  <br>
  <em>計画、調査、制作、コーディング handoff、運用、プロジェクト記憶を明確な証拠境界とともに提供します。</em>
</p>

**oh-my-hermes**（OMH）は、
[Hermes Agent](https://github.com/NousResearch/hermes-agent) への通常の依頼を、
適切な機能、有用な次の行動、そして実際に起きたこと・まだ起きていないことの
正直な状態へ変換します。Hermes を置き換えたり、コーディング executor を
隠したりせず、既存の Hermes ワークフローを強化します。

```text
通常の依頼
  -> 6つの機能ファミリーから選択
  -> 計画、ソース brief、成果物 contract、コーディング handoff を準備
  -> runtime、provider、review、CI、merge の証拠は観測時のみ記録
```

[Website](https://rlaope.github.io/oh-my-hermes/) ·
[Documentation](docs/README.md) ·
[Installation](docs/INSTALLATION.md) ·
[Capabilities](docs/CAPABILITIES.md) ·
[Capability Impact](docs/CAPABILITY_IMPACT.md)

## クイックスタート

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | sh
omh setup
omh doctor
```

Hermes skill tap:

```sh
hermes skills tap add rlaope/oh-my-hermes
hermes skills install rlaope/oh-my-hermes/skills/oh-my-hermes --yes
```

通常の利用者が直接使う OMH コマンドは、基本的に3つだけです。

- `omh setup`: OMH を接続または修復します。
- `omh update`: OMH と管理対象 skill を更新します。
- `omh doctor`: 状態を確認し、次の修復手順を示します。

それ以外の作業は Hermes に自然言語で依頼します。`omh coding`、`omh
runtime`、`omh chat`、`omh memory` などは、主に Hermes Agent、wrapper、
コーディングエージェント、maintainer が使う control plane であり、通常の
利用者が覚える必要のある操作ではありません。

その後は Hermes にいつも通り依頼します。

```text
Use OMH request-to-handoff for: I want to safely add a feature to this repo.
```

## OMH が追加するもの

OMH は **82 個**のインストール可能な workflow skill を、理解しやすい6つの
機能ファミリーとして提供します。

| 機能ファミリー | Hermes ができること |
| --- | --- |
| **計画と意思決定** | 曖昧な目標を明確にし、レビュー済み計画と durable goal loop を準備します。 |
| **学習と収集** | 情報源の探索、論文説明、データ確認、根拠付き brief を準備します。 |
| **資料とビジュアル制作** | Web、画像、文書、スライド、PDF、ポスターを形式別の品質 gate とともに制作します。 |
| **コーディング委任と出荷** | Codex、Claude Code、Hermes runtime、または選択した executor 向けの handoff を準備します。 |
| **運用と観測** | セットアップ、サービス品質、リリース、障害、automation、session、workflow learning を確認します。 |
| **知識の保持** | レビュー済みプロジェクト記憶を構築し、外部知識システムを provider-neutral な境界で接続します。 |

完全な catalog、trigger、harness、証拠ルールは
[Workflow Reference](docs/WORKFLOWS.md) にあります。

## 実務向けの設計

**コマンド一覧ではなくルーター。** 英語、韓国語、日本語、中国語、
スペイン語、フランス語、ドイツ語、ヒンディー語の依頼を翻訳 API なしで
ローカル分類し、推奨ファミリー、skill、owner、次の行動、未観測の項目を返します。

**より良いコーディング handoff。** リポジトリ制約、合意済み scope、
worktree ガイド、ローカル skill、受け入れ条件、review、verification gate を
選択した executor に渡します。Codex、Claude Code、Hermes、generic executor
のどれも暗黙のデフォルトにはしません。

**品質を理解する制作と provider-neutral な運用。** Web、accessibility、
画像、report、slide、document は専用の制作・QA ガイダンスを使います。
metric、wiki、browser、image、video、connector は明示的な外部 provider
contract の背後に置き、接続・呼び出しをしていない provider を使ったとは主張しません。

## 主張より証拠

| 状態 | 意味 |
| --- | --- |
| Prepared | route、plan、prompt、成果物 contract、handoff の準備ができています。 |
| Observed | wrapper または runtime が行動や結果の発生を記録しました。 |
| Verified | 必要な test、review、実画面確認、または別の gate が通過しました。 |

`prepared_not_observed` は実行、provider access、成果物生成、review、CI、
deployment、merge readiness、merge ではありません。

## ドキュメント

- [ドキュメントマップ](docs/README.md)
- [インストールと更新](docs/INSTALLATION.md)
- [製品方針と境界](docs/DIRECTION.md)
- [アーキテクチャ](docs/ARCHITECTURE.md)
- [機能 manifest](docs/CAPABILITIES.md)
- [Workflow reference](docs/WORKFLOWS.md)
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
