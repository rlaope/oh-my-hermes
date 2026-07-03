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
  <strong>한 번 설치하고, Hermes 흐름은 그대로 두세요. OMH가 다음 행동을 더 또렷하고 안전하게 잡아줍니다.</strong>
  <br>
  <em>채팅에서 시작하는 스킬, 워크플로 계약, 상태 카드, 실행 handoff를 기존 Hermes 환경에 자연스럽게 더합니다.</em>
</p>

**oh-my-hermes**는 Hermes를 대체하려는 도구가 아닙니다. 평소처럼
[Hermes](https://github.com/NousResearch/hermes-agent)에서 일하고, OMH가
스킬, 계약, 상태 카드, handoff를 더해 다음 단계를 분명하게 만들어줍니다.
일본어, 중국어, 스페인어, 프랑스어, 독일어, 한국어, 힌디어, 영어로 자주 쓰는
운영자 요청은 로컬 deterministic 라우팅으로 처리합니다. 번역 API를 호출하지
않고도 요청을 알맞은 워크플로로 보내고 첫 채팅 카드를 구성할 수 있습니다.

```text
Hermes에서 자연어로 요청
  -> OMH가 가장 작은 유용한 워크플로 경로를 추천
  -> Hermes가 질문, 조사, 계획, 상태 보고의 다음 증거 경계를 정리
  -> 코드 작업은 사용자가 받아들인 뒤 선택된 runtime으로 명시적으로 handoff
```

> [!NOTE]
> **Friren Agent는 Art&Engine 안에서 OMH를 계속 다듬고 있습니다.**
> OMH가 나온 작업 맥락은 [Team Art & Engineering](https://rlaope.github.io/artengine-lab/)에서 볼 수 있습니다.
>
> <p align="center">
>   <img src="assets/friren-agent-omh-callout.png" alt="Friren Agent explaining OMH in Art&Engine" width="920">
> </p>
>
> <p align="center">
>   <img src="assets/artengine-friren-profile-card.png" alt="Art&Engine profile card for Hope Kim and Friren" width="920">
> </p>

<br>

## 빠른 시작

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | sh
omh setup

omh doctor
```

Hermes skill tap 경로:

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
> OMH 업데이트와 Hermes-native 워크플로 프로젝트 소식은 GitHub의
> [@rlaope](https://github.com/rlaope)에서 확인할 수 있습니다.
> 프로젝트를 만든 스튜디오 맥락은
> [Team Art & Engineering](https://rlaope.github.io/artengine-lab/)에 정리되어 있습니다.

<br>

## 핵심 워크플로

<p align="center">
  <img src="assets/omh-core-workflows.png" alt="OMH Core Workflows illustration" width="920">
</p>

<p align="center">
  <img src="assets/omh-skill-magic-promo.png" alt="Friren Agent controlling OMH workflow skills with magic" width="920">
</p>

---

- **Deep Interview** (`deep-interview`) - 계획 전에 정말 필요한 결정을
  하나씩 좁힙니다. 요청이 아직 흐릿할 때 씁니다.

- **Ralplan** (`ralplan`) - repo 사실, 근거 자료, 위험, 수락 기준,
  검증 명령을 검토 가능한 계획으로 묶습니다.

- **Ultragoal** (`ultragoal`) - 큰 목표를 한 번의 답변으로 끝내지 않고
  체크포인트와 완료 게이트에 묶어 추적합니다.

- **Loop** (`loop`) - 조사, 계획, handoff, 피드백을 반복하며 구현 방향을
  찾아야 할 때 사용합니다.

- **Web Research** (`web-research`) - 시장, 문서, 경쟁 제품, 구현 방식,
  best practice를 최신 출처 기반으로 조사합니다.

- **Idea To Deploy** (`idea-to-deploy`) - Codex, Claude Code, Hermes 또는
  다른 runtime에 넘길 코드 작업을 범위와 증거 경계까지 준비합니다.

- **Workflow Learning** (`workflow-learning`) - 놓친 라우트나 약한 워크플로를
  trace, eval, review queue, regression case, patch proposal로 바꿉니다.

운영, 조사, 자료 제작, 리뷰, 릴리스, 워크플로 지원을 위한 내장 스킬이
**41개 이상** 더 포함되어 있습니다. 전체 목록은
[Workflow Reference](docs/WORKFLOWS.md)와 [Capabilities](docs/CAPABILITIES.md)에
있습니다.

<br>

## 무엇을 얻나

**바로 쓸 수 있는 워크플로 스킬**

- 인터뷰, 계획, durable goal, loop, research, coding handoff prep, review,
  release, materials, operations용 Hermes 스킬을 설치할 수 있습니다.
- 각 스킬은 trigger guidance, completion gate, recovery note, evidence
  boundary를 포함합니다. Hermes가 키워드만 보고 추측하지 않고 다음 단계를
  고를 수 있게 하기 위해서입니다.

**프로필과 역할 표면**

- Operator, researcher, planner, handoff, review, status 역할이 다음 행동의
  소유자를 안정적으로 설명합니다.
- 프로필 팩은 chat, wrapper, coding-agent 행동을 맞추되, 특정 executor를
  숨은 기본값으로 만들지 않습니다.

**Subagent와 executor handoff**

- 코드 중심 작업은 Codex, Claude Code, Hermes runtime 또는 사용자가 고른
  executor로 넘기도록 준비할 수 있습니다.
- Worktree와 session helper는 unrelated repo state를 섞지 않고 subagent
  작업을 열고, 붙고, 기록하고, 검토하기 쉽게 합니다.

**증거를 구분하는 운영**

- Status card는 plan, handoff, dispatch, result, verification, review, CI,
  merge-readiness 증거를 분리합니다.
- Runtime과 plugin 관측값은 기본적으로 metadata-only라서 raw prompt나 platform
  event, log를 노출하지 않고도 유용한 보고를 만들 수 있습니다.

**학습 루프**

- 놓친 라우트, 약한 워크플로, 품질 gap, regression case는 workflow-learning
  trace, review queue, patch proposal로 이어질 수 있습니다.
- OMH는 준비된 handoff가 이미 실행됐다고 꾸미지 않고, 관측된 결과를 통해
  조금씩 좋아집니다.

<br>

## 요청 흐름

OMH는 흐름을 단순하고 눈에 보이게 유지합니다. Hermes는 하나의 팀 모델에
묶이지 않고, 요청에 맞는 가장 작은 역할 경로를 고릅니다.

```text
plain request
  -> workflow lane 선택
  -> plan, source brief, handoff 준비
  -> evidence가 있을 때만 execution / review / CI 관측
  -> Hermes chat에 다음 행동 보고
```

| 요청 형태 | 일반적인 흐름 |
| --- | --- |
| 빠른 답변 또는 setup repair | Hermes가 설명하고, OMH가 local state를 확인한 뒤 다음 명령을 제안합니다. |
| Research 또는 product signal | 구현 전에 source finder / research / brief workflow를 거칩니다. |
| Coding task | Codex, Claude Code, Hermes 또는 다른 선택 runtime으로 범위가 잡힌 handoff를 준비합니다. |
| Release 또는 review question | 준비된 주장과 실제 test, review, CI, merge evidence를 분리합니다. |

<br>

## 문서

1. 전체 문서 지도: [Documentation](docs/README.md)
2. 설치, 업데이트, 재적용, 제거, installer flag: [Installation](docs/INSTALLATION.md)
3. AI agent에 붙여넣기 좋은 설치 절차: [Agent Install](INSTALL_FOR_AGENTS.md)
4. 제품 방향과 경계: [Direction](docs/DIRECTION.md)
5. 아키텍처와 module ownership: [Architecture](docs/ARCHITECTURE.md)
6. Hermes/plugin/wrapper용 capability manifest: [Capabilities](docs/CAPABILITIES.md)
7. orchestration pattern contract: [Orchestration Patterns](docs/ORCHESTRATION_PATTERNS.md)
8. common oh-my runtime parity와 gap: [Parity Matrix](docs/PARITY.md)
9. 상황별 playbook: [Playbooks](docs/PLAYBOOKS.md)
10. role surface와 profile pack: [Roles](docs/ROLES.md)
11. memory/context review와 handoff pack: [Memory Context Review](docs/MEMORY_CONTEXT.md)
12. Discord-style 및 plugin-native wrapper 예시: [Chat Wrapper Examples](docs/CHAT_WRAPPER_EXAMPLES.md)
13. harness quality contract: [Harness Quality Contract](docs/HARNESS_QUALITY.md)
14. 대표 workflow: [Application Cases](docs/APPLICATION_CASES.md)
15. public website source: [GitHub Pages site](site/index.html)

<br>

## 개발

개발, release smoke, product readiness, evidence bundle은
[Release](docs/RELEASE.md)에 정리되어 있습니다. source checkout에서 빠르게
확인하려면 다음을 실행합니다.

```sh
PYTHONPATH=tests uv run python -m unittest discover -s tests -v
uv run python -m compileall -q src tests
uv run python -m omh.cli docs workflows --check
uv run --no-editable omh recommend "risky refactor" --limit 1 --json
```

마지막 명령은 의도적으로 `uv run --no-editable`을 사용합니다. source checkout이
패키지된 `omh` console script를 import하고 실행할 수 있는지 확인하기 위해서입니다.
일반 사용자는 curl installer가 안내한 설치된 `omh` 명령을 쓰면 됩니다.

OMH 1.0.2는 quality gate를 통과한 stable baseline입니다. 더 풍부한 profile
activation probe와 artifact-backed wrapper 예시는 roadmap과 release 문서에서
추적합니다.
