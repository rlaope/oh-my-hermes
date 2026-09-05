<p align="center">
  <img src="assets/oh-my-hermes-wordmark.png" alt="OH-MY-HERMES" width="100%" style="display:block;max-width:none;height:auto">
</p>

<table align="center">
  <tr>
    <td width="50%" align="center">
      <img src="assets/hermes-desktop.gif" alt="Hermes Desktop running an OMH workflow" width="380" height="266"><br>
      <sub><b>Hermes 桌面端，搭配 oh-my-hermes。</b><br>选一个工作流，它会先确认再构建。</sub>
    </td>
    <td width="50%" align="center">
      <img src="assets/hermes-cli.gif" alt="Hermes CLI running an OMH workflow" width="380" height="266"><br>
      <sub><b>Hermes CLI，搭配 oh-my-hermes。</b><br>在你已在用的终端里运行同样的工作流。</sub>
    </td>
  </tr>
  <tr>
    <td width="50%" align="center">
      <img src="assets/hermes-messenger.gif" alt="Hermes messenger app running an OMH workflow" width="380" height="266"><br>
      <sub><b>Hermes 消息应用，搭配 oh-my-hermes。</b><br>在话题里提出请求，结果回到同一个话题。</sub>
    </td>
    <td width="50%" align="center">
      <img src="assets/omh-setup.gif" alt="omh setup installing the OMH workflows" width="380" height="266"><br>
      <sub><b><code>omh setup</code>，一条命令。</b><br>安装工作流并连接到 Hermes。</sub>
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
  <strong>只需安装一次。保留 Hermes，再加上一层更强的工作系统。</strong>
  <em>以清晰的证据边界提供规划、研究、内容制作、编码 handoff、运维和项目记忆。</em>
</p>

<p align="center">
  <img src="assets/oh-my-hermes-agent-poster.png" alt="Oh My Hermes Agent poster" width="720">
</p>

**oh-my-hermes**（OMH）把
[Hermes Agent](https://github.com/NousResearch/hermes-agent) 中的普通请求，
转化为合适的能力、明确的下一步，以及对“已经发生”和“尚未发生”的诚实状态。
它不会取代 Hermes，也不会隐藏编码 executor，而是增强现有 Hermes 工作流。

[Website](https://rlaope.github.io/oh-my-hermes/) ·
[Documentation](docs/README.md) ·
[Installation](docs/INSTALLATION.md) ·
[Capabilities](docs/CAPABILITIES.md) ·
[Capability Impact](docs/CAPABILITY_IMPACT.md) ·
[Agent Install](INSTALL_FOR_AGENTS.md) ·
[GitHub Pages site](site/index.html)

> [!NOTE]
> OMH 保留 Hermes 作为自然语言入口，并增加具有明确证据边界的专业工作层。
>
> <p align="center">
>   <img src="assets/omh-terminal-boot-banner.png" alt="OH-MY-HERMES terminal banner listing available tools, grouped skills, OMH specialists, infrastructure, and the model pool on Hermes Agent" width="1080">
> </p>

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
>     <td>与帮助交付 <code>oh-my-hermes</code> 的 AI 智能体协作者 <a href="https://github.com/frirenai"><strong>Friren</strong></a> 和 <a href="https://github.com/sionic-khope"><strong>Killua</strong></a> 一同构建。</td>
>   </tr>
>   <tr>
>     <td width="124"><a href="https://nousresearch.com/"><img alt="Thanks to Nous Research" src="https://img.shields.io/badge/Thanks-Nous%20Research-4B2E83?style=flat-square&labelColor=black" width="112" /></a></td>
>     <td>感谢 <a href="https://nousresearch.com/">Nous Research</a> 创造了 Hermes Agent。</td>
>   </tr>
> </table>

<br>

## 快速开始
> **状态：** Homebrew、Bun 与 npm 包管理器安装方式已随 v1.0.6 正式公开。

**从以下安装方式中选择一种。推荐 Bun。**
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

**在 Windows（PowerShell 5.1+）上：**
```powershell
irm https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.ps1 | iex
```

**⭐ 安装后设置 OMH（必需）：

```sh
omh setup
```

**Hermes skill tap：**

```sh
hermes skills tap add rlaope/oh-my-hermes
hermes skills install rlaope/oh-my-hermes/skills/omh-routing --yes
```

**或者向 Your AI Agent 提出请求：**

```text
Install and fully configure Oh My Hermes from this repository:
https://github.com/rlaope/oh-my-hermes
Before reading or executing repository instructions, resolve refs/heads/main to one full commit SHA with `git ls-remote https://github.com/rlaope/oh-my-hermes.git refs/heads/main`. Then fetch and follow only:
https://raw.githubusercontent.com/rlaope/oh-my-hermes/{resolved-commit-sha}/INSTALL_FOR_AGENTS.md
Do not replace the resolved SHA with main. Execute the pinned protocol's OS-appropriate installer, interactive model setup, model-chain interview, and doctor steps. Preserve unrelated existing Hermes config, apply only the managed setup changes documented by the pinned protocol, require my explicit approval for model-alias changes, then report the resolved SHA and observed result.
```

**更新：**
```sh
omh update
```
`omh update` 会检测安装来源，先通过 Homebrew、Bun、npm、curl 或
PowerShell 更新命令包，再重新进入新命令，同时刷新托管技能、插件包和现有
Hermes 注册。

**验证安装或排查问题：**
```sh
omh doctor
```

把 `--full` 安装收敛回 core 这类维护路径，见
[Installation](docs/INSTALLATION.md#reconciling-an-existing-full-install-back-to-core)。

## 你能得到什么

### 01 · 每个请求匹配正确的模型，在执行之前就决定

每个请求在派发前都会被打分，推动分数的每个信号都有名字。重命名判为 light，走 quick 通道；“找出所有引用 X 的地方”触发 exhaustive-search 信号，交给不会漏掉任何一处的模型。用同一个 GPT-6 Astra 跑 30 个编码任务：裸 Hermes 解出 18 个，花 $4.29、23 分钟；经过 OMH，同样的 18 个只花 $0.66、5 分钟。

<p align="center">
  <img src="assets/showcase-01-routing.svg" alt="omh coding complexity 为两个请求打分的结果，以及 Astra 的测量表" width="1080">
</p>

[阅读基准测试 ↗](benchmarks/live-model-tools/v1/README.md)

### 02 · 类别按执行器归你所有

`ultrabrain`、`deep`、`architect`、`quick`、`writing`、`visual-engineering`：每一个都是按编码执行器划分的模型+effort 链，在一个文件里即可查看和覆盖。提供方拒绝某个模型时链会前进；一次会继承无法提供该模型的提供方的派发会被拒绝，而不是悄悄降级。setup 会询问你的提供方，并按当前这台机器重排链。

<p align="center">
  <img src="assets/showcase-02-categories.svg" alt="omh coding category-maestro show：按执行器的类别链、一处操作者覆盖、一次被拒绝的派发" width="1080">
</p>

[阅读路由文档 ↗](docs/FANOUT.md)

### 03 · 按模型家族调校的提示，并且经过测量

13 个模型家族，每个家族一个校准块，每一句都针对该家族有文档记载的一个特性：告诉 Claude 清单已经完整，告诉 Gemini 没有工具输出的断言不算证据，告诉 Qwen3-Coder 永远不要输出 thinking 标签，告诉 DeepSeek 版本和 thinking 模式是契约字段。GPT-6 Astra 有自己的精确模型契约和校准块。有路由的地方就测量：Astra 的初稿让它在解不出的任务上继续硬做，同样的答案多花 10% token，于是按这个数字被删掉。

<p align="center">
  <img src="assets/showcase-03-calibration.svg" alt="每个模型家族一行校准、gpt-6-astra 模型契约、经测量的修订" width="1080">
</p>

[阅读 MODEL_OPTI.md ↗](MODEL_OPTI.md)

### 04 · 只在安全的地方并行，回来时带着类型

`ulw-work` 把已批准的计划拆成互不共享文件的单元，给每个单元一个从同一个固定 SHA 分出的工作树，并允许单元在一轮里发出全部工具调用。每个单元以四状态的类型化结果返回：进程已退出、schema 有效、已观察到验证、可集成。没有证据的 exit 0 在门禁检查之前一直停在 `reported done`，验证回执只在版本、命令、环境全部一致时复用。

<p align="center">
  <img src="assets/showcase-04-parallel.svg" alt="一次 ulw-work 扇出：三个文件互不重叠的单元、每单元一个工作树、类型化状态、一轮内发出的工具调用" width="1080">
</p>

[阅读扇出契约 ↗](docs/FANOUT.md)

### 05 · 只展示能证明之事的 HUD

每条委派通道一行：模型、effort、轮次、token、成本，实时更新。成本为零只在主机确认时才显示；无法定价的调用显示 `unknown`，而不是 `$0`。进程存在之前是 `Plan · not run`，执行器自称完成时是 `Code · reported done`，只有门禁通过后才是 `Test · verified`。提示框上方的阶段待办是这次运行自己的清单，不是事后写的摘要。

<p align="center">
  <img src="assets/showcase-05-hud.svg" alt="OMH HUD：每条通道的模型、effort、轮次、token、成本来源、证据状态，以及阶段待办" width="1080">
</p>

[阅读证据规则 ↗](docs/CAPABILITY_IMPACT.md)

<br>

## OH-MY-HERMES 终端

只需输入 `omh`,即可从与 `hermes` 相同的入口,打开带有 OMH 标识的 Hermes:

```sh
omh
```

<table align="center">
  <tr>
    <td width="50%" align="center">
      <img src="assets/omh-terminal-boot-hud.png" alt="The OH-MY-HERMES boot"><br>
      <sub><b>OH-MY-HERMES 启动画面。</b></sub>
    </td>
    <td width="50%" align="center">
      <img src="assets/omh-terminal-ulw-work-session.png" alt="An ulw-work run"><br>
      <sub><b><code>ulw-work</code> 运行中。</b></sub>
    </td>
  </tr>
</table>

OMH 工作流运行时,终端会展示:

- **Mixture-of-Models Routing** — 每条委派 lane 按类别(ultrabrain、deep、
  quick、writing、visual-engineering 等)在每次 dispatch 时应用模型与推理
  强度;每个活动行都带有 `category:name(model:effort)`,路由清晰可见。被
  拒绝的路由沿类别链 fallback。
- **Parallel Tool Calling** — 批量工具调用在 Hermes 中并发执行,刚发生的
  并发批次会在 `[OMH]` 行标注为 `parallel shot ×N`。
- **Parallel Evals** — 评审与验证 lane 作为独立子代理调度,交叉核验而非
  自我批准,每条 lane 都是一个带 turn、cost、cache 指标的 HUD 行。
- **Phase-structured TODO** — 工作在开始前以 phase 和 task 声明
  (`todo init`),渲染为提示符上方的清单:单一活动项、每个 phase 标题下
  缩进的任务、子任务嵌套、超过七行后折叠。

<br>

## 推荐模型

OMH 随附以下可编辑的有序 recommendation chain。guided model setup 只会依据用户确认 active 的 candidate 来解析 chain。结果是已准备的 routing config，不是 provider availability、credential、dispatch 或 execution 证据。

| 类别 alias | 用途 | 可编辑的 recommendation 顺序 |
| --- | --- | --- |
| `ultrabrain` | 最深度推理 | GPT-6 Astra，其次 GPT-5.6 Sol (xhigh) |
| `deep` | 强力默认层 | GPT-5.6 Terra，其次 DeepSeek V3.2 (high) |
| `architect` | 架构与系统设计 | Claude Fable 5.1，其次 Claude Mythos 5.1，其次 Claude Fable 5，其次 GPT-6 Astra，其次 GPT-5.6 Sol，其次 Kimi K3 (xhigh) |
| `unspecified-high` | 默认工作模型 | Kimi K3，其次 Claude Opus 5 (medium) |
| `unspecified-low` | 低成本回退 | GLM 5.3，其次 GLM 5.2，其次 GLM 5.2 Ultrafast，其次 DeepSeek V3.2，其次 Claude Opus 5 (low) |
| `quick` | 短任务 | GLM 5.3 Flash，其次 GLM 5.2 Ultrafast，其次 Kimi K3，其次 GPT-5.6 Luna，其次 Claude Fable 5.1，其次 Claude Mythos 5.1，其次 Claude Fable 5 (low) |
| `writing` | 文章与文档 | Kimi K3，其次 Qwen3-Coder，其次 Gemini 3.1 Pro (medium) |
| `visual-engineering` | 前端与视觉 | Claude Fable 5.1，其次 Claude Mythos 5.1，其次 Claude Fable 5，其次 Kimi K3 (high) |
| `artistry` | 非常规创作 | Gemini 3.1 Pro，其次 Claude Fable 5.1，其次 Claude Mythos 5.1，其次 Claude Fable 5，其次 Kimi K3 (high) |

想试试 Ultrafast 档? Kimi K3 Ultrafast(300 TPS)与 GLM 5.2 Ultrafast(600 TPS)都在 [OpenGateway](https://opengateway.ai/) 上提供。

上面的每条 chain 都可以在不改代码的情况下编辑。chain 由一个文件管理，`omh setup` 会生成它:

```sh
$ cat ~/.omh/routing/model-chains.json
{
  "categories": {},
  "schema_version": "mixture_chain_overrides/v1"
}
```

`categories` 为空时，上面的默认 chain 全部保持生效。要修改就编辑这个文件: 写入其中的类别会在路由、fallback 与 HUD 标签中替换对应 chain —

```json
{
  "schema_version": "mixture_chain_overrides/v1",
  "categories": {
    "architect": [
      {"model": "claude-fable-5-1", "reasoning_effort": "xhigh"},
      {"model": "gpt-5.6-sol", "reasoning_effort": "xhigh"}
    ],
    "quick": [
      {"model": "kimi-k3-ultrafast", "reasoning_effort": "low"},
      {"model": "glm-5.2-ultrafast", "reasoning_effort": "low"}
    ]
  }
}
```

当前生效的 chain 可用 `omh model-chains show` 查看。不想手动编辑文件的话，也可以运行 `omh model-chains set quick "kimi-k3-ultrafast:low, glm-5.2-ultrafast:low"`，同一个文件会被直接修改。
如果 alias 需要 provider 专用的 wire ID，请在 `~/.omh/routing/model-providers.json` 中按 `model_provider_routes/v1` 映射一次。此后 `set`、`status`、fallback 和 HUD 都会显示完整的 alias/provider/wire model route。OMH 只保存 provider ID，不保存 credential。

请让 Hermes **设置我的模型**，以查看或更改这些推荐。它们是可编辑的偏好，不是 benchmark 结果。详细的设置、fallback、provider 与所有权规则见 [Guided Model Setup](docs/INSTALLATION.md#guided-model-setup)。

编码委派的 dispatch（`omh coding run` / `omh coding fanout dispatch`）读取的是与本文件分开、由 operator 自行设置的 preference：要在 Claude Code 上使用最强档位，在 `~/.omh/routing/dispatch-models.json` 中设置 `"claude-code": "opus"`，或在单次 `omh coding run` 调用中传入 `--model opus`；`codex` 在确认账号可用的 model id 后同样设置即可。完整的 schema 与优先级顺序见 `docs/FANOUT.md`（Dispatch-model preference）。

<details>
<summary><strong>也可以把以下内容粘贴给 Hermes 或其他 coding agent</strong></summary>

```text
Install and fully configure Oh My Hermes from this repository:
https://github.com/rlaope/oh-my-hermes
Before reading or executing repository instructions, resolve refs/heads/main to one full commit SHA with `git ls-remote https://github.com/rlaope/oh-my-hermes.git refs/heads/main`. Then fetch and follow only:
https://raw.githubusercontent.com/rlaope/oh-my-hermes/{resolved-commit-sha}/INSTALL_FOR_AGENTS.md
Do not replace the resolved SHA with main. Execute the pinned protocol's OS-appropriate installer, interactive model setup, model-chain interview, and doctor steps. Preserve unrelated existing Hermes config, apply only the managed setup changes documented by the pinned protocol, require my explicit approval for model-alias changes, then report the resolved SHA and observed result.
```

</details>

## Ultra 技能

<p align="center">
  <img src="assets/omh-character-badge.png" alt="Oh My Hermes character mark" width="170">
</p>

九个 `ulw-` workflow。说出触发词，其余交给 Hermes —— 完整目录见
[Workflow Reference](docs/WORKFLOWS.md)。

| Skill | 做什么 |
| --- | --- |
| ⚡ `ulw-context` | 对齐经审查的项目术语，捕获已确认的候选项，并在不赋予术语路由权的前提下追问下一个决策点。 |
| ⚡ `ulw-interview` | 一次问一个问题，直到确切知道你要什么。 |
| ⚡ `ulw-research` | 翻真实代码和网页做调研，留下出处，可疑就核实。 |
| ⚡ `ulw-plan` | 做一份评审过的计划：比过方案、点明风险、定好完成标准。 |
| ⚡ `ulw-work` | 把已确认的计划放进互不碰同一文件的并行车道执行。 |
| ⚡ `ulw-maestro` | 在 Claude Code 或 Codex 上运行委派的任务 —— 提示词由该 CLI 自身安装的技能组装而成，实时启动，附带仪表行和可操控的会话。 |
| ⚡ `ulw-loop` | 计划 → 实现 → 评审，循环到目标真正通过。 |
| ⚡ `ulw-qa` | 故意用狠场景攻击，坏哪修哪。 |
| ⚡ `ulw-perf` | 先测出真正慢和贵的地方，再逐条修热路径。 |

## OMH 提供什么

OMH 把模型选择和编码所有权作为两个独立决策，并且绝不把准备报告为执行。
容易理解的能力族仍然是入口；精确控制、runtime 边界和证据规则会在 wrapper
或 operator 需要时保持可查。完整 catalog、trigger、harness 和证据规则位于
[Workflow Reference](docs/WORKFLOWS.md)。

**亮点**

| 智能层 | OMH 提供什么 |
| --- | --- |
| 🧭 **Mixture-of-models 路由** | 每条委派 lane 按类别(模型 + 推理强度)在每次 dispatch 时应用,provider 拒绝某个模型时沿可编辑的 fallback chain 前进 — 没有做任何工作的子代理会诚实地标记为 `failed`。 |
| 🖥️ **原生 TUI 表面** | OMH HUD(带类别、轮次、成本、缓存的实时 delegation 行)、提示符上方的 phase todo 清单、`parallel shot ×N` 标注、整行 diff 色带、受管理的皮肤 — 全部安装在 Hermes 旁边,绝不修改 Hermes 本体。 |
| 📋 **Phase 结构化计划** | `todo init` 在引擎工作开始前声明 phase 和 task,让运行沿有界清单推进,而不是陷入开放式推理循环。 |
| ⚡ **可观测的并行工作** | 把独立工作拆成所有权隔离的 fanout unit,并观测进度和 verification gate。 |
| 🎼 **Maestro handoff** | 在不成为隐藏 executor、也不把准备当作执行的前提下,为明确的 coding owner 和 runtime profile 准备 handoff。 |
| 🧠 **上下文智能** | 在不虚构隐藏记忆、也不暗中改变已选 route 的前提下,投影紧凑且经过审查的仓库上下文。 |
| 📚 **JIT learning** | 为当前 blocker 选择最有价值的学习目标,并在不声称已经学会的前提下准备有来源、可立即应用的指导。 |
| 🔍 **证据约束的交付** | 在 coding、review、CI 和 merge 全程分开已准备意图、已观测 runtime 活动与已验证结果。 |
| 🔎 **结构化代码搜索** | 基于实测的 `ast-grep` 手册 — 覆盖 28 种语言的结构查询、禁止 body-capture、grep 回退 — 注入到 executor 搜索代码的场景。OMH 只检测二进制是否存在,从不亲自执行。 |
| 🗄️ **项目记忆系统** | Hermes 可加载的确定性文件型 memory provider、可审查的项目记忆命令(inspect、pack、domain capture)、consolidation 调度 brief 以及记忆审查技能 — 从不读取或修改 Hermes 不透明的内部记忆。 |
| 🛠️ **编码 harness 与护栏** | executor readiness 探测、附在已准备 handoff 上的 capability snapshot 与 owner-fit 报告、作用于 `execute_code` 结果的 code-mode discipline,以及用规则文本拦截越界 tool call 的用户自定义 toolcall rules。 |
| ♾️ **Ultra 工作流引擎** | 所有权彼此隔离的并行交付 lane、带 ledger 和真实完成 gate 的计量循环,以及在任何引擎运行前先澄清意图的 decision-frontier 访谈 — 引擎列表见下方 Ultra 技能一节。 |
| 📦 **确定性技能目录** | 120+ 可安装的 workflow 技能、逐字节校验的生成目录、包含负向用例的 routing precision 语料,以及一字符漂移即令 CI 失败的 drift gate。 |

## 证据先于声明

OMH 只报告自己观测到的事情。你看到的每个状态都由两部分组成：处于哪个阶段，
以及 OMH 对它有多确定。

| 显示 | 含义 |
| --- | --- |
| `Plan · not run` | prompt 或 plan 已就绪。**还没有任何东西运行过。** |
| `Code · running` | executor 正在运行，OMH 正在观测。 |
| `Code · reported done` | executor 说它完成了。没有人检查过结果。 |
| `Test · verified` | test、review 或 CI gate 确实通过了。 |

关键是倒数第二行：executor 说自己完成了，与结果被检查过是两回事，
而大多数工具把两者都写成「完成」。
## 文档

- [文档地图](docs/README.md)
- [安装与更新](docs/INSTALLATION.md)
- [产品方向与边界](docs/DIRECTION.md)
- [架构](docs/ARCHITECTURE.md)
- [能力 manifest](docs/CAPABILITIES.md)
- [Workflow reference](docs/WORKFLOWS.md)
- [角色](docs/ROLES.md)
- [应用案例](docs/APPLICATION_CASES.md)
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
## 贡献者

感谢每一位为 oh-my-hermes 做出贡献的人。

<a href="https://github.com/rlaope/oh-my-hermes/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=rlaope/oh-my-hermes&max=100&columns=10" alt="oh-my-hermes contributors" />
</a>
