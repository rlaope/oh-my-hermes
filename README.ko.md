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
  <strong>한 번 설치하세요. Hermes는 그대로 두고, 더 강한 운영층을 더하세요.</strong>
  <br>
  <em>계획, 조사, 제작, 코딩 handoff, 운영, 프로젝트 기억을 명확한 증거 경계와 함께 제공합니다.</em>
</p>

**oh-my-hermes**(OMH)는
[Hermes Agent](https://github.com/NousResearch/hermes-agent)의 평범한 요청을
알맞은 기능, 유용한 다음 단계, 그리고 실제로 일어난 일과 아직 일어나지 않은
일에 대한 정직한 상태로 바꿉니다. Hermes를 대체하거나 코딩 executor를 숨기지
않고, 이미 사용 중인 Hermes 작업 흐름을 강화합니다.

```text
일반 요청
  -> 6개 기능군 중 하나를 선택
  -> 계획, 출처 브리프, 산출물 계약, 코딩 handoff를 준비
  -> runtime, provider, review, CI, merge 증거는 관측된 경우에만 기록
```

[Website](https://rlaope.github.io/oh-my-hermes/) ·
[Documentation](docs/README.md) ·
[Installation](docs/INSTALLATION.md) ·
[Capabilities](docs/CAPABILITIES.md) ·
[Capability Impact](docs/CAPABILITY_IMPACT.md)

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

일반 사용자가 직접 사용할 OMH 명령은 보통 세 가지입니다.

- `omh setup`: OMH를 연결하거나 설정을 복구합니다.
- `omh update`: OMH와 관리형 skill을 최신화합니다.
- `omh doctor`: 상태를 점검하고 다음 복구 방법을 확인합니다.

그 밖의 작업은 Hermes에 자연어로 요청하면 됩니다. `omh coding`, `omh
runtime`, `omh chat`, `omh memory` 같은 명령은 주로 Hermes Agent, wrapper,
코딩 에이전트, 유지관리자가 내부적으로 사용하는 제어면이며, 일반 사용자가
외워야 하는 사용법이 아닙니다.

이제 Hermes에 평소처럼 요청하면 됩니다.

```text
Use OMH request-to-handoff for: I want to safely add a feature to this repo.
```

## OMH가 더하는 것

OMH는 **82개**의 설치형 workflow skill을 사람이 이해하기 쉬운 6개 기능군으로
제공합니다.

| 기능군 | Hermes가 더 잘할 수 있는 일 |
| --- | --- |
| **계획과 결정** | 모호한 목표를 명확히 하고, 검토된 계획과 durable goal loop를 준비합니다. |
| **학습과 수집** | 출처 탐색, 논문 설명, 데이터 점검, 근거 기반 브리프를 준비합니다. |
| **자료와 시각물 제작** | 웹, 이미지, 문서, 발표 자료, PDF, 포스터를 형식별 품질 게이트와 함께 만듭니다. |
| **코딩 위임과 배포** | Codex, Claude Code, Hermes runtime 또는 선택한 executor에 전달할 명확한 handoff를 준비합니다. |
| **운영과 관찰** | 설정, 서비스 품질, 릴리스, 장애, 자동화, 세션, workflow learning을 점검합니다. |
| **지식 보존** | 검토된 프로젝트 기억을 만들고 외부 지식 시스템을 provider-neutral 경계로 연결합니다. |

전체 목록과 trigger, harness, 증거 규칙은
[Workflow Reference](docs/WORKFLOWS.md)에 있습니다.

## 실제 업무를 위한 설계

**명령어 목록이 아닌 라우터.** 영어, 한국어, 일본어, 중국어, 스페인어,
프랑스어, 독일어, 힌디어 요청을 번역 API 없이 로컬에서 분류하고, 추천 기능군,
skill, 담당자, 다음 행동, 아직 증거가 아닌 항목을 함께 보여줍니다.

**더 나은 코딩 handoff.** 저장소 제약, 합의된 범위, worktree 지침, 로컬 skill,
완료 기준, 리뷰 기대치, 검증 게이트를 선택된 executor에 전달합니다. Codex,
Claude Code, Hermes, generic executor 중 누구도 숨은 기본값이 되지 않습니다.

**품질을 아는 제작과 provider-neutral 운영.** 웹, 접근성, 이미지, 보고서,
발표 자료, 문서 요청은 전용 제작·QA 지침을 사용합니다. metric, wiki, browser,
image, video, connector는 명시적인 외부 provider 계약 뒤에 두며, 연결하거나
호출하지 않은 provider를 사용했다고 주장하지 않습니다.

## 주장보다 증거

| 상태 | 의미 |
| --- | --- |
| Prepared | route, plan, prompt, 산출물 계약 또는 handoff가 준비됐습니다. |
| Observed | wrapper 또는 runtime이 행동이나 결과가 발생했다고 기록했습니다. |
| Verified | 필요한 test, review, 실제 화면 검사 또는 다른 gate가 통과했습니다. |

`prepared_not_observed`는 실행, provider 접근, 산출물 생성, review, CI, 배포,
merge readiness 또는 merge가 아닙니다.

## 문서

- [문서 지도](docs/README.md)
- [설치와 업데이트](docs/INSTALLATION.md)
- [제품 방향과 경계](docs/DIRECTION.md)
- [아키텍처](docs/ARCHITECTURE.md)
- [기능 manifest](docs/CAPABILITIES.md)
- [Workflow reference](docs/WORKFLOWS.md)
- [릴리스와 개발](docs/RELEASE.md)

## 개발

```sh
PYTHONPATH=tests uv run python -m unittest discover -s tests -v
uv run python -m compileall -q src tests
uv run python -m omh.cli docs workflows --check
git diff --check
```

OMH는 [Team Art & Engineering](https://rlaope.github.io/artengine-lab/)의
공개 프로젝트로 개발되고 있습니다. 프로젝트 소식은
[@rlaope](https://github.com/rlaope)에서 확인할 수 있습니다.
