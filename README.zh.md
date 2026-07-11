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
  <strong>安装一次，保留你的 Hermes 工作流。OMH 帮你把下一步看清楚、走稳。</strong>
  <br>
  <em>把聊天入口、工作流契约、状态卡片和 handoff 加到现有 Hermes 环境里，不打断原来的用法。</em>
</p>

**oh-my-hermes** 不是要替换 Hermes。你可以继续在
[Hermes](https://github.com/NousResearch/hermes-agent) 里工作，让 OMH 补上
技能、契约、状态卡片和 handoff，把下一步该做什么说清楚。常见的日语、中文、
西班牙语、法语、德语、韩语、印地语和英语操作请求会在本地做确定性路由。
它不调用翻译 API，也能把请求送到合适的工作流，并组织第一张聊天卡片。

```text
用户在 Hermes 里用自然语言提出请求
  -> OMH 推荐最小但有用的工作流路径
  -> Hermes 整理澄清、调研、计划或状态报告所需的下一层证据边界
  -> 代码量较重的工作，只有在接受后才明确 handoff 给选定的 runtime
```

> [!NOTE]
> **Friren Agent 正在 Art&Engine 中持续打磨 OMH。**
> 想了解 OMH 背后的工作室语境，可以查看
> [Team Art & Engineering](https://rlaope.github.io/artengine-lab/)。
>
> <p align="center">
>   <img src="assets/friren-agent-omh-callout.png" alt="Friren Agent explaining OMH in Art&Engine" width="920">
> </p>
>
> <p align="center">
>   <img src="assets/artengine-friren-profile-card.png" alt="Art&Engine profile card for Hope Kim and Friren" width="920">
> </p>

<br>

## 快速开始

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | sh
omh setup

omh doctor
```

Hermes skill tap 路径:

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
> 你可以在 GitHub 关注 [@rlaope](https://github.com/rlaope)，获取 OMH 和
> 相关 Hermes-native 工作流项目的更新。
> 项目背后的工作室语境见
> [Team Art & Engineering](https://rlaope.github.io/artengine-lab/)。

<br>

## 核心工作流

<p align="center">
  <img src="assets/omh-core-workflows.png" alt="OMH Core Workflows illustration" width="920">
</p>

<p align="center">
  <img src="assets/omh-skill-magic-promo.png" alt="Friren Agent controlling OMH workflow skills with magic" width="920">
</p>

---

- **Deep Interview** (`deep-interview`) - 在进入计划前，把真正缺失的决策
  一个个问清楚。适合边界还模糊的请求。

- **Ralplan** (`ralplan`) - 把 repo 事实、来源、风险、验收标准和验证命令
  整理成可审阅的计划。

- **Ultragoal** (`ultragoal`) - 把一个较大的目标绑定到 checkpoint 和完成
  gate，而不是用一次回答草草带过。

- **Loop** (`loop`) - 在调研、计划、handoff、反馈之间循环，适合需要逐步找到
  正确实现方向的任务。

- **Web Research** (`web-research`) - 为市场、文档、竞品、实现方案或
  best practice 问题收集当前且有来源支撑的证据。

- **Idea To Deploy** (`idea-to-deploy`) - 为 Codex、Claude Code、Hermes 或
  其他 runtime 准备有范围、有证据边界的代码工作。

- **Workflow Learning** (`workflow-learning`) - 把漏掉的路由或较弱的工作流
  转成 trace、eval、review queue、regression case 和 patch proposal。

除这些代表性模式外，还包含 **47 个以上** 面向运维、调研、材料制作、审查、
发布和工作流支持的内置技能。完整目录见
[Workflow Reference](docs/WORKFLOWS.md) 和 [Capabilities](docs/CAPABILITIES.md)。

<br>

## 你会得到什么

**可直接使用的工作流技能**

- 可安装 interview、planning、durable goal、loop、research、coding handoff
  prep、review、release、materials、operations 等 Hermes 技能。
- 每个技能都带有 trigger guidance、completion gate、recovery note 和
  evidence boundary。这样 Hermes 不需要只靠关键词猜测下一步。

**Profile 和角色表面**

- Operator、researcher、planner、handoff、review、status 等角色让 Hermes
  能稳定说明谁负责下一步。
- Profile pack 会协调 chat、wrapper 和 coding-agent 的行为，但不会把某一个
  executor 变成隐藏默认值。

**Subagent 与 executor handoff**

- 代码较重的工作可以先整理好，再 handoff 给 Codex、Claude Code、Hermes
  runtime 或用户选择的其他 executor。
- Worktree 和 session helper 可以帮助打开、附加、记录和审查 subagent 工作，
  同时避免混入无关的 repo 状态。

**带证据边界的运行方式**

- Status card 会区分 plan、handoff、dispatch、result、verification、review、
  CI 和 merge-readiness 证据。
- Runtime 与 plugin 观察值默认只保留 metadata，因此可以生成有用报告，而不泄露
  raw prompt、platform event 或日志。

**学习循环**

- 漏掉的路由、较弱的工作流、质量 gap 和 regression case 可以进入
  workflow-learning trace、review queue 和 patch proposal。
- OMH 通过已观察到的结果改进，而不是把准备好的 handoff 当成已经执行过。

<br>

## 请求流程

OMH 让流程保持简单、可见。Hermes 不会被锁定到某一种团队模型，而是选择最适合
当前请求的最小角色路径。

```text
plain request
  -> 选择 workflow lane
  -> 准备 plan、source brief 或 handoff
  -> 只有存在 evidence 时才观察 execution / review / CI
  -> 在 Hermes chat 里报告下一步
```

| 请求类型 | 常见流程 |
| --- | --- |
| 快速回答或 setup repair | Hermes 解释问题，OMH 检查 local state，然后建议下一条命令。 |
| Research 或 product signal | 实现前先经过 source finder / research / brief workflow。 |
| Coding task | 准备交给 Codex、Claude Code、Hermes 或其他选定 runtime 的 scoped handoff。 |
| Release 或 review question | 区分准备好的声明和实际的 test、review、CI、merge evidence。 |

<br>

## 文档

1. 完整文档地图: [Documentation](docs/README.md)
2. 安装、更新、重新应用、卸载和 installer flags: [Installation](docs/INSTALLATION.md)
3. 可粘贴给 AI agent 的安装流程: [Agent Install](INSTALL_FOR_AGENTS.md)
4. 产品方向和边界: [Direction](docs/DIRECTION.md)
5. 架构与 module ownership: [Architecture](docs/ARCHITECTURE.md)
6. Hermes/plugin/wrapper 使用的 capability manifests: [Capabilities](docs/CAPABILITIES.md)
7. 区分 routing、hook、执行可用性与结果质量的证据: [Capability Impact](docs/CAPABILITY_IMPACT.md)
8. orchestration pattern contracts: [Orchestration Patterns](docs/ORCHESTRATION_PATTERNS.md)
9. common oh-my runtime parity 和 gap: [Parity Matrix](docs/PARITY.md)
10. 场景 playbook: [Playbooks](docs/PLAYBOOKS.md)
11. role surfaces 与 profile packs: [Roles](docs/ROLES.md)
12. memory/context review 与 handoff packs: [Memory Context Review](docs/MEMORY_CONTEXT.md)
13. Discord-style 与 plugin-native wrapper 示例: [Chat Wrapper Examples](docs/CHAT_WRAPPER_EXAMPLES.md)
14. harness quality contract: [Harness Quality Contract](docs/HARNESS_QUALITY.md)
15. 代表性 workflow: [Application Cases](docs/APPLICATION_CASES.md)
16. public website source: [GitHub Pages site](site/index.html)

<br>

## 开发

开发、release smoke、product readiness 和 evidence bundle 的细节见
[Release](docs/RELEASE.md)。从 source checkout 做一次快速检查:

```sh
PYTHONPATH=tests uv run python -m unittest discover -s tests -v
uv run python -m compileall -q src tests
uv run python -m omh.cli docs workflows --check
uv run --no-editable omh recommend "risky refactor" --limit 1 --json
```

最后一条命令故意使用 `uv run --no-editable`，用于确认 source checkout 中打包后的
`omh` console script 可以 import 并运行。普通用户应使用 curl installer 输出的
已安装 `omh` 命令。

OMH 1.0.2 是通过 quality gate 的 stable baseline。更丰富的 profile activation
probe 和 artifact-backed wrapper 示例会在 roadmap 与 release 文档中继续追踪。
