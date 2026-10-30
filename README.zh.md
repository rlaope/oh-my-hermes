<div align="center">

<br>

<img src="assets/oh-my-hermes-wordmark.png?v=spectrum" alt="OH-MY-HERMES" width="70%">

<br>
<br>

<img src="assets/omh-logo.png" alt="oh-my-hermes 标志：白色圆角方形图块上，用粗黑线条画出的 oh-my-hermes 角色" width="200">

<br>
<br>

**Hermes Agent 的一站式套件。安装一次，然后只需输入 `dag-ulw`。**

[![GitHub Release](https://img.shields.io/github/v/release/rlaope/oh-my-hermes?color=58a6ff&labelColor=black&logo=github&style=flat-square)](https://github.com/rlaope/oh-my-hermes/releases) [![npm downloads](https://img.shields.io/npm/dt/oh-my-hermes?color=3fb950&labelColor=black&logo=npm&label=downloads&style=flat-square)](https://www.npmjs.com/package/oh-my-hermes) [![GitHub Contributors](https://img.shields.io/github/contributors/rlaope/oh-my-hermes?color=bc8cff&labelColor=black&style=flat-square)](https://github.com/rlaope/oh-my-hermes/graphs/contributors) [![GitHub Stars](https://img.shields.io/github/stars/rlaope/oh-my-hermes?color=e3b341&labelColor=black&style=flat-square)](https://github.com/rlaope/oh-my-hermes/stargazers) [![License](https://img.shields.io/github/license/rlaope/oh-my-hermes?color=white&labelColor=black&style=flat-square)](LICENSE) [![Docs](https://img.shields.io/badge/docs-omher.app-58a6ff?labelColor=black&logo=readthedocs&logoColor=white&style=flat-square)](https://omher.app/)

[English](README.md) | [简体中文](README.zh.md) | [日本語](README.ja.md) | [Русский](README.ru.md) | [한국어](README.ko.md) | [Español](README.es.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | [Português (Brasil)](README.pt-BR.md) | [Italiano](README.it.md)

**oh-my-hermes** 是 [Hermes Agent](https://github.com/NousResearch/hermes-agent) 之上的操作层。<br>
你照常和 Hermes 对话，OMH 为你选技能、为每条 lane 选模型，并把工作并行跑起来。<br>
它不给 Hermes 打补丁，也不取代它，更不会把只是计划过的工作报告为完成。

</div>

## 安装

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | sh
omh setup
```

[Windows 及其他安装方式 →](docs/INSTALLATION.md)

<br>

## 你能得到什么

- **每条 lane 用对的模型。**<br>
  每条 lane 都带有一个工作类别：`ultrabrain`、`deep`、`visual-engineering`、`quick` 等。<br>
  类别决定该 lane 的模型 chain 和推理强度，每条 chain 都可以编辑。<br>
  provider 拒绝某个模型时，不会悄悄降级，而是前进到 chain 的下一个模型。<br>
  `omh model` 打开选择器。[每条 lane 用哪个模型](docs/INSTALLATION.md#guided-model-setup)

- **`/dag-ulw` 图运行。**<br>
  你的目标会变成由小节点组成的图，就绪的节点并行运行。<br>
  每个节点使用其类别的模型和 effort，同时运行的节点不会共享写入范围。<br>
  由单独的节点检查目标，失败的节点在报告前得到修复。

- **按需加入的专家技能。**<br>
  前端、后端、Rust、安全评审、验证门禁等一百多个 `omh-*` 专业技能。<br>
  你不用去调用，路由器会把合适的技能以工具调用的形式加入运行。

- **可以信赖的长期记忆。**<br>
  不会悄悄记忆：每个候选都带着写明的理由被记住、拒绝或推迟。<br>
  下一个会话会得到按任务排序、裁剪到 token 预算内的召回包。<br>
  Hermes 自己的记忆从不被读取或修改。

- **OMH Native.**<br>
  `omh` 在 Hermes gateway 上打开 OMH 自己的 TUI，启动外观可用 `/theme` 切换。<br>
  `/dag-ulw` 先打印方框图，再显示实时 lane 树，列出每条 lane 的模型、effort 和 token。<br>
  在 agent 列表里 steer 或中断 agent，用 `!` 运行 shell 命令，按 Esc Esc 回退。

- **“完成”之前先有证据。**<br>
  每个状态都同时标明阶段和把握程度。<br>
  `Plan · not run` · `Code · reported done` · `Test · verified`<br>
  只有测试、评审或 CI 门禁真正通过，才算 verified。

<br>

## DAG-ULW

**只需输入 `/dag-ulw`，你就是图工程大师。**

你的目标会变成由小节点组成的图，每个节点用自己的模型并行运行。<br>
由一个单独的节点验证目标之后，你才会收到报告。

<p align="center">
  <img src="assets/omh-dag-ulw-tui.gif" alt="运行 /dag-ulw 的 OMH TUI：输入提示词后定义出七条通道的方框图，通道按层在 Claude Opus 5.5、GPT-6.1 Sol、DeepSeek V4.1 Flash、GLM 5.3 和 Kimi K3.1 Pro 上运行，最后全部 accepted" width="900">
</p>

> [!TIP]
> 加入我们！
>
> <table>
>   <tr>
>     <td width="124"><a href="https://x.com/rlaope"><img alt="X link" src="https://img.shields.io/badge/Follow-%40rlaope-00CED1?style=flat-square&logo=x&labelColor=black" width="112" /></a></td>
>     <td><code>oh-my-hermes</code> 的更新会在 X 上的 <a href="https://x.com/rlaope">@rlaope</a> 分享，包括发布说明和项目动态。</td>
>   </tr>
>   <tr>
>     <td width="124"><a href="https://github.com/rlaope"><img alt="GitHub Follow" src="https://img.shields.io/github/followers/rlaope?style=flat-square&logo=github&labelColor=black&color=24292f" width="112" /></a></td>
>     <td>在 GitHub 上关注 <a href="https://github.com/rlaope">@rlaope</a>，了解更多项目、发布和进行中的工作。</td>
>   </tr>
>   <tr>
>     <td width="124"><a href="https://discord.gg/6EjTP3cWM"><img alt="Discord invite" src="https://img.shields.io/badge/Join-Discord-5865F2?style=flat-square&logo=discord&logoColor=white&labelColor=black" width="112" /></a></td>
>     <td>加入 Discord 上的 <a href="https://discord.gg/6EjTP3cWM">Oh-My-Hermes Community</a>，提问、分享工作流，并与其他用户交流。</td>
>   </tr>
>   <tr>
>     <td width="124"><a href="https://github.com/rlaope/oh-my-hermes/graphs/contributors"><img alt="AI agent collaborators" src="https://img.shields.io/badge/With-AI%20agents-6f42c1?style=flat-square&labelColor=black" width="112" /></a></td>
>     <td>与帮助交付 <code>oh-my-hermes</code> 的 AI 智能体协作者 <a href="https://github.com/frirenai"><strong>Friren</strong></a> 和 <a href="https://github.com/sionic-khope"><strong>Kami</strong></a> 一同构建。</td>
>   </tr>
>   <tr>
>     <td width="124"><a href="https://nousresearch.com/"><img alt="Thanks to Nous Research" src="https://img.shields.io/badge/Thanks-Nous%20Research-4B2E83?style=flat-square&labelColor=black" width="112" /></a></td>
>     <td>感谢 <a href="https://nousresearch.com/">Nous Research</a> 创造了 Hermes Agent。</td>
>   </tr>
> </table>

> **赞助商** 感谢赞助商对 oh-my-hermes 的支持。
>
> <table>
>   <tr>
>     <td width="160" align="center"><a href="https://opengateway.ai/"><img alt="OpenGateway" src="assets/sponsors/opengateway.svg" width="140" /></a></td>
>     <td><a href="https://opengateway.ai/"><strong>OpenGateway</strong></a> 赞助了 oh-my-hermes，感谢你们对开源的支持。<br>它用一个兼容 OpenAI 的端点接入多家模型 provider，并提供自动故障切换。</td>
>   </tr>
> </table>

<br>

## 其他

[文档](docs/README.md) · [安装](docs/INSTALLATION.md) · [Capabilities](docs/CAPABILITIES.md) · [Workflows](docs/WORKFLOWS.md) · [网站](https://omher.app/)

<details>
<summary><b>安装选项</b></summary>

**macOS / Linux：**

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | sh
```

**Windows（PowerShell 5.1+）：**

```powershell
irm https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.ps1 | iex
```

**或者把下面这段粘贴给你的 AI 代理：**

```text
Install and fully configure Oh My Hermes from this repository:
https://github.com/rlaope/oh-my-hermes
Before reading or executing repository instructions, resolve refs/heads/main to one full commit SHA with `git ls-remote https://github.com/rlaope/oh-my-hermes.git refs/heads/main`. Then fetch and follow only:
https://raw.githubusercontent.com/rlaope/oh-my-hermes/{resolved-commit-sha}/INSTALL_FOR_AGENTS.md
Do not replace the resolved SHA with main. Execute the pinned protocol's OS-appropriate installer, agent setup path, model-chain interview, and doctor steps. Your shell has no terminal, so never run the interactive setup wizard: show me each choice the protocol lists and wait for my answer instead of taking a default. Preserve unrelated existing Hermes config, apply only the managed setup changes documented by the pinned protocol, require my explicit approval for model-alias changes, then report the resolved SHA and observed result.
```

**更新：**

```sh
omh update
```

`omh update` 会检测安装来源，通过对应的安装器更新命令，再刷新托管技能、插件包和 Hermes 注册。

**验证安装或排查问题：**

```sh
omh doctor
```

```sh
# 按工作类别设置模型（方向键：类别，←→ head 模型，-/+ effort）；
# 在 OMH TUI（omh）中 /omh-model 打开同一个选择器：
omh model
# 如需接入新的模型家族，请在 Hermes 中使用此技能：
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

Bun 和 npm 还需要 PATH 中有 Node 18+ 和 Python 3.11+；Homebrew 会自带 Python。
无论用哪种方式安装，之后都运行 `omh setup`。

**Hermes skill tap：**

```sh
hermes skills tap add rlaope/oh-my-hermes
hermes skills install rlaope/oh-my-hermes/skills/omh-routing --yes
```

**包管理器手动回退或卸载：**

| 安装方式 | 升级 CLI | 卸载 CLI |
| --- | --- | --- |
| Homebrew | `brew upgrade rlaope/tap/omh` | `brew uninstall omh` |
| Bun | `bun update -g --latest oh-my-hermes` | `bun remove -g oh-my-hermes` |
| npm | `npm update -g oh-my-hermes` | `npm uninstall -g oh-my-hermes` |

只有在 `omh update` 报告找不到其安装器时才直接使用包管理器命令。删除命令包会保留 OMH 状态。要完全卸载，请先运行 `omh uninstall --all`，再执行包管理器的卸载命令。

把 `--full` 安装收敛回 core 这类维护路径，见 [Installation](docs/INSTALLATION.md#reconciling-an-existing-full-install-back-to-core)。

</details>

<details>
<summary><b>参考</b></summary>

### Ultra 技能

十个 `ulw-` workflow。说出触发词，其余交给 Hermes —— 完整目录见 [Workflow Reference](docs/WORKFLOWS.md)。

| Skill | 做什么 |
| --- | --- |
| ⚡ `ulw-context` | 对齐经审查的项目术语，捕获已确认的候选项，并在不赋予术语路由权的前提下追问下一个决策点。 |
| ⚡ `ulw-interview` | 一次问一个问题，直到确切知道你要什么。 |
| ⚡ `ulw-research` | 翻真实代码和网页做调研，留下出处，可疑就核实。 |
| ⚡ `ulw-plan` | 做一份评审过的计划：比过方案、点明风险、定好完成标准。 |
| ⚡ `ulw-work` | 把已确认的计划放进互不碰同一文件的并行车道执行。 |
| ⚡ `dag-ulw` | 把大型工作当作由小的并行节点组成的图来运行，用单独的节点验证目标，并修复失败的部分。 |
| ⚡ `ulw-maestro` | 在 Claude Code 或 Codex 上运行委派的任务 —— 提示词由该 CLI 自身安装的技能组装而成，实时启动，附带仪表行和可操控的会话。 |
| ⚡ `ulw-loop` | 计划 → 实现 → 评审，循环到目标真正通过。 |
| ⚡ `ulw-qa` | 故意用狠场景攻击，坏哪修哪。 |
| ⚡ `ulw-perf` | 先测出真正慢和贵的地方，再逐条修热路径。 |

#### 推荐组合

在 Hermes 提示符里这样输入。`ulw-` 前缀选定 workflow，其余部分就是用日常语言写的请求。

**1. 定形。** 想法还模糊时用 `ulw-interview`；要改什么已经清楚、但有风险时用 `ulw-plan`。

```text
❯ ulw-interview: I want a CLI that tracks the ISS and warns me before it passes overhead
❯ ulw-plan: analyze this project's circular dependencies and plan the refactor
```

**2. 构建。** `ulw-work` 把已确认的计划放进互不碰同一文件的并行车道执行。

```text
❯ ulw-work: run the accepted plan
```

**3. 收尾。** `ulw-loop` 会一直循环，直到你指定的关卡通过。

```text
❯ ulw-loop: keep going until npm test passes
```


### 它如何与 Hermes 协作

Hermes Agent 已经在跑循环。OMH 决定往循环里放什么：每条 lane 用哪个模型和推理强度、代码变更由谁负责、应用哪些技能、什么算完成。两条规则处处成立：模型选择与编码归属是两个独立决定，准备好的东西绝不当作已执行来报告。生成的目录、trigger 与证据规则见 [Workflow Reference](docs/WORKFLOWS.md)。

### 工作流

**理解 → 调研 → 决策 → 计划 → 执行 → 验证 → 运维 → 学习**

| 阶段 | 推进事项 |
| --- | --- |
| 理解 | 确认意图、约束、项目术语和停止条件。 |
| 调研 | 用有据可查的产品、代码或运维背景信息取代假设。 |
| 决策 | 明确选项、取舍和决策负责人。 |
| 计划 | 将已确认的范围、代码变更负责人、测试和完成标准整理成可执行计划。 |
| 执行 | 向选定负责人提供边界明确的任务交接，不把准备工作当作实际执行。 |
| 验证 | 依据实际观测到的测试结果、评审结果、CI 结果和运行时证据作出结论。 |
| 运维 | 让发布健康状态、故障事件、回滚状态和后续工作始终清晰可见。 |
| 学习 | 将经过评审、适用范围明确的经验纳入项目记忆，或用于改进工作流。 |

**亮点**

| 智能 | OMH 提供什么 |
| --- | --- |
| 🧭 **Mixture-of-models 路由** | 每条委派 lane 在 dispatch 时落到一个类别（模型 + 推理强度）。provider 拒绝模型时沿 chain 下落，没做事的子任务显示 `failed`，而不是一行绿色。 |
| 🎛️ **按模型家族校准** | 按家族和代次调校提示词：GPT-6 Astra、GPT-5.6、Claude 5.5、GLM 5.3、Kimi、Gemini、Qwen、DeepSeek 等，只在基准对照证明有效时才保留。 |
| 🗂️ **你自己掌控的类别** | 内置模型类别，`omh model-chains set` 调整顺序，按机器重排 chain 的 entitlement 访谈，以及运行前就能看到请求会路由到哪里的实时视图。 |
| 🖥️ **原生 TUI 界面** | OMH HUD（带类别、轮次、成本、缓存的实时行）、提示符上方的 phase todo、`parallel shot ×N`、整行 diff 色带与自选主题，显示在 `omh` 打开的 OMH TUI 中，绝不给 Hermes 打补丁。 |
| ⚡ **可观测的并行工作** | 把独立工作拆成文件归属互不重叠的 fanout unit，带 provider 压力下的 admission control、有类型的结果 sidecar，以及读取返回结果的 verification gate。 |
| 💸 **带价格的成本遥测** | 每一行 HUD 和 run summary 都显示 token 数与美元金额，按注明来源的价目表计算；无法计价的 run 显示 `unknown`，而不是 `$0`。 |
| 🧠 **长期项目记忆** | Hermes 可加载的文件型 memory provider、admission 与 retention 策略、审阅者把关的写入、带新鲜度与预算的 recall pack。Hermes 自身的记忆不被触碰。 |
| 🔎 **结构化代码搜索** | 经测量的 `ast-grep` 手册（28 种语言，grep 回退）和绘制整个仓库架构图的 `omh codegraph uml`，注入到 executor 读代码的位置；`omh codegraph tests --changed` 列出一次改动会触及的测试（[codegraph 命令](docs/CODEGRAPH.md)）。 |
| 🛡️ **你自己写的护栏** | 用你的规则文本拦截越界 tool call 的 toolcall rules、拒绝把 stub 和跳过的测试当证据的 completion-integrity gate，以及高风险操作的 approval tier。 |
| ♾️ **Ultra 工作流引擎** | 并行交付 lane、带 ledger 与真实完成 gate 的度量循环、引擎运行前的 decision-frontier 访谈。列表见上方 Ultra 技能。 |
| 📦 **确定性目录** | 由同一来源生成的一百多个可安装技能、含负例的 routing precision 语料，以及一个字节偏差就让 CI 失败的 drift gate。 |

### 证据先于声明

OMH 只报告自己观测到的事情。你看到的每个状态都由两部分组成：处于哪个阶段，以及 OMH 对它有多确定。

| 显示 | 含义 |
| --- | --- |
| `Plan · not run` | prompt 或 plan 已就绪。**还没有任何东西运行过。** |
| `Code · running` | executor 正在运行，OMH 正在观测。 |
| `Code · reported done` | executor 说它完成了。没有人检查过结果。 |
| `Test · verified` | test、review 或 CI gate 确实通过了。 |

executor 说自己完成了，与结果被检查过是两回事，而大多数工具把两者都写成「完成」。能力影响按独立维度报告，而不是折叠成一个营销分数，见 [Capability Impact](docs/CAPABILITY_IMPACT.md)。对比单独 Hermes 与经 OMH 的 Hermes 的产品 A/B 通道，语料和离线试点都已就位，目前还没有发布任何实测运行结果： [`benchmarks/product-ab/v1/README.md`](benchmarks/product-ab/v1/README.md)。

### 文档

- [文档地图](docs/README.md)
- [安装与更新](docs/INSTALLATION.md)
- [代理安装协议](INSTALL_FOR_AGENTS.md)
- [产品方向与边界](docs/DIRECTION.md)
- [架构](docs/ARCHITECTURE.md)
- [能力 manifest](docs/CAPABILITIES.md)
- [Workflow reference](docs/WORKFLOWS.md)
- [角色](docs/ROLES.md)
- [应用案例](docs/APPLICATION_CASES.md)
- [模型路由、扇出契约与请求打分](docs/FANOUT.md)
- [扇出 executor 证据：会话、故障诊断、容量（agent/operator 参考）](docs/FANOUT-EXECUTOR-EVIDENCE.md)
- [Agent 看板与原生 Kanban 协作（agent/operator 参考）](docs/AGENT-BOARD.md)
- [按模型的校准映射](MODEL_OPTI.md)
- [证据规则与能力影响](docs/CAPABILITY_IMPACT.md)
- [长期记忆模型](docs/MEMORY.md)
- [Codegraph 命令](docs/CODEGRAPH.md)
- [Show-reel 工具包](docs/SHOW-REEL-TOOLKIT.md)
- [用 Hermes 处理超大 PDF](docs/LONG-DOCUMENT-READING.md)
- [实时模型基准与实测结果](benchmarks/live-model-tools/v1/README.md)
- [发布与开发](docs/RELEASE.md)
- [网站](https://omher.app/)（[源码](site/index.html)）

### 贡献者

<a href="https://github.com/rlaope/oh-my-hermes/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=rlaope/oh-my-hermes&max=100&columns=10" alt="oh-my-hermes contributors" />
</a>

</details>

## 许可证

MIT，见 [LICENSE](LICENSE)。<br>
与[贡献者们](https://github.com/rlaope/oh-my-hermes/graphs/contributors)一起，作为 [Team Art & Engineering](https://rlaope.github.io/artengine-lab/) 的开源项目开发。
