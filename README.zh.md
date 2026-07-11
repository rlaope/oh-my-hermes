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
  <strong>只需安装一次。保留 Hermes，再加上一层更强的工作系统。</strong>
  <br>
  <em>以清晰的证据边界提供规划、研究、内容制作、编码 handoff、运维和项目记忆。</em>
</p>

**oh-my-hermes**（OMH）把
[Hermes Agent](https://github.com/NousResearch/hermes-agent) 中的普通请求，
转化为合适的能力、明确的下一步，以及对“已经发生”和“尚未发生”的诚实状态。
它不会取代 Hermes，也不会隐藏编码 executor，而是增强现有 Hermes 工作流。

```text
普通请求
  -> 从6个能力族中选择
  -> 准备计划、来源 brief、产物 contract 或编码 handoff
  -> 仅在实际观测后记录 runtime、provider、review、CI、merge 证据
```

<p align="center">
  <img src="assets/friren-agent-omh-callout.png" alt="Friren Agent explaining OMH in Art&Engine" width="720">
</p>

<p align="center">
  <img src="assets/artengine-friren-profile-card.png" alt="Art&Engine profile card for Hope Kim and Friren" width="720">
</p>

[Website](https://rlaope.github.io/oh-my-hermes/) ·
[Documentation](docs/README.md) ·
[Installation](docs/INSTALLATION.md) ·
[Capabilities](docs/CAPABILITIES.md) ·
[Capability Impact](docs/CAPABILITY_IMPACT.md)

## 快速开始

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | sh
omh setup
omh doctor
```

Hermes skill tap：

```sh
hermes skills tap add rlaope/oh-my-hermes
hermes skills install rlaope/oh-my-hermes/skills/oh-my-hermes --yes
```

普通用户通常只需要直接使用三个 OMH 命令：

- `omh setup`：连接或修复 OMH。
- `omh update`：更新 OMH 和受管理的 skill。
- `omh doctor`：检查状态并获得下一步修复建议。

其他工作从向 Hermes 提出自然语言请求开始。`omh coding`、`omh runtime`、
`omh chat`、`omh memory` 等命令主要是 Hermes Agent、wrapper、编码 agent 和
maintainer 使用的 control plane，而不是普通用户需要记忆的操作流程。

之后像往常一样向 Hermes 提出请求：

```text
Use OMH request-to-handoff for: I want to safely add a feature to this repo.
```

## OMH 提供什么

OMH 将 **82 个**可安装的 workflow skill 组织为6个容易理解的能力族。

| 能力族 | Hermes 可以做得更好的事情 |
| --- | --- |
| **规划与决策** | 澄清模糊目标，准备经过审查的计划和 durable goal loop。 |
| **学习与收集** | 查找来源、解释论文、检查数据并准备有依据的 brief。 |
| **资料与视觉制作** | 通过针对格式的质量 gate 制作网站、图像、文档、演示、PDF 和海报。 |
| **编码委派与交付** | 为 Codex、Claude Code、Hermes runtime 或选定 executor 准备明确的 handoff。 |
| **运维与观测** | 检查设置、服务质量、发布、事故、automation、session 和 workflow learning。 |
| **知识保留** | 构建经过审查的项目记忆，并通过 provider-neutral 边界连接外部知识系统。 |

<p align="center">
  <img src="assets/omh-core-workflows.png" alt="OMH Core Workflows illustration" width="720">
</p>

<p align="center">
  <img src="assets/omh-skill-magic-promo.png" alt="Friren Agent controlling OMH workflow skills with magic" width="720">
</p>

完整 catalog、trigger、harness 和证据规则位于
[Workflow Reference](docs/WORKFLOWS.md)。

## 面向真实工作的设计

**不是命令列表，而是路由器。** 英语、韩语、日语、中文、西班牙语、法语、
德语和印地语请求可在本地分类，无需翻译 API。OMH 会返回推荐能力族、skill、
owner、下一步以及仍未形成证据的部分。

**更好的编码 handoff。** 将仓库约束、已接受 scope、worktree 指南、本地
skill、验收标准、review 期望和 verification gate 交给选定 executor。
Codex、Claude Code、Hermes 和 generic executor 都不会成为隐藏默认值。

**理解质量的制作与 provider-neutral 运维。** 网站、accessibility、图像、
report、slide 和 document 请求使用专门的制作与 QA 指南。metric、wiki、
browser、image、video 和 connector 位于明确的外部 provider contract 之后；
OMH 不会声称连接或调用了实际未使用的 provider。

## 证据先于声明

| 状态 | 含义 |
| --- | --- |
| Prepared | route、plan、prompt、产物 contract 或 handoff 已准备好。 |
| Observed | wrapper 或 runtime 已记录某个操作或结果确实发生。 |
| Verified | 所需 test、review、实际页面检查或其他 gate 已通过。 |

`prepared_not_observed` 不代表执行、provider 访问、产物生成、review、CI、
deployment、merge readiness 或 merge。

## 文档

- [文档地图](docs/README.md)
- [安装与更新](docs/INSTALLATION.md)
- [产品方向与边界](docs/DIRECTION.md)
- [架构](docs/ARCHITECTURE.md)
- [能力 manifest](docs/CAPABILITIES.md)
- [Workflow reference](docs/WORKFLOWS.md)
- [发布与开发](docs/RELEASE.md)

## 开发

```sh
PYTHONPATH=tests uv run python -m unittest discover -s tests -v
uv run python -m compileall -q src tests
uv run python -m omh.cli docs workflows --check
git diff --check
```

OMH 是 [Team Art & Engineering](https://rlaope.github.io/artengine-lab/) 的
开源项目。请关注 [@rlaope](https://github.com/rlaope) 获取更新。
