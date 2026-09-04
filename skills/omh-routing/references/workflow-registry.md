# OMH Workflow Registry

This generated reference is loaded only when exact workflow routing detail matters.
The always-on `oh-my-hermes` skill keeps only the compact lane map and recovery rules.
For a compact name plus one-line description shortlist of every routable skill, load `references/catalog-index.md`.

## CLI Reference Surfaces

These surfaces are generated command references, not installed Hermes workflow skills.

### dynamic-workflow

`omh coding dynamic-workflow` prepares `dynamic_coding_workflow/v1`, `workflow.json`, and `workflow-chart.svg` under `.omh/coding/dynamic-workflows/`.

- Exposure: `cli_reference`
- Install visibility: `false`
- Docs visibility: `public_cli_reference`
- Status: `prepared_not_observed`
- Expected outputs: `dynamic_coding_workflow/v1` metadata-only contract and SVG chart attachment
- Safety boundary: the generated workflow and chart are not execution, target selection, runtime dispatch, model invocation, implementation, review, CI, PR, merge-readiness, or merge evidence.
- Privacy boundary: goals are stored as digest metadata; supported source metadata is compacted through the standard source metadata allowlist.

## Role Registry

- `guide`: `oh-my-hermes`, `meta-router`, `model-setup`, `parallel-tools`, `websearch-setup`, `morning-brief`, `gateway-intent-card`, `voice-operator`, `browser-operator`, `workspace-file-operator`, `command-operator`, `connector-operator`, `live-info-operator`, `external-connector-readiness`, `prompt-import-readiness`, `content-operator`, `media-input-operator`, `data-analysis`
- `handoff-guide`: `ultrawork`, `maestro`, `frontend-refactor`, `ai-slop-cleaner`, `executor-runtime-readiness`
- `memory-keeper`: `rules-distill`, `wiki`, `memory-new`, `memory-sync`, `decision-recall`
- `operator`: `strategy-brief`, `meeting-brief`, `feedback-triage`, `finance-analysis`, `people-ops`, `support-operations`, `sales-development`, `ops-review`, `operating-rhythm`, `report-package`, `materials-package`, `img-summary`, `design-orchestration`, `design-quality-gate`, `award-bar-score`, `frontend`, `visual-qa`, `workspace-audit`, `agent-evaluation`, `automation-blueprint`, `reliability-review`, `idea-to-deploy`, `llm-app-dev`, `cto-loop`, `deploy-and-monitor`, `inference-serving`, `github-event-ops`, `deliverable-package`, `physical-device-readiness`, `agent-debug`, `skill-scout`, `skill-health`, `provider-profile-posture`
- `planner`: `loop`, `context`, `deep-interview`, `curriculum-design`, `product-brief`, `backend`, `rust`, `codebase-onboarding`, `codegraph-refresh`, `codebase-uml`, `plan`, `ralplan`, `adversarial-consensus`, `refactor-plan`
- `researcher`: `jit-learn`, `research`, `web-research`, `product-docs`, `source-finder`, `research-brief`, `research-department`, `paper-learning`, `best-practice-research`, `autoresearch-goal`
- `reviewer`: `legal-compliance-review`, `localization-review`, `native-debugging`, `accessibility-audit`, `build-failure-triage`, `production-audit`, `verification-gate`, `security-safety-review`, `ultraqa`, `code-review`, `tech-debt-audit`, `ask`, `failure-signal-audit`
- `tracker`: `context-budget-review`, `performance-goal`, `model-optimization`, `ultraperf`, `cancel`, `skill`, `doctor`, `capability-toggle`, `running-work-board`, `buzz`, `agent-board`, `toolbelt-readiness`, `harness-session-inventory`, `ops-observability-card`, `achievements`, `agent-ops-review`, `instinct-ledger`, `workflow-learning`, `run-efficiency`
- Installed workflow skill policies live in generated workflow skills; compatibility/reference-only surface policies live in `docs/WORKFLOWS.md` and are not guaranteed to have `skills/<name>/SKILL.md` files.

## Automatic Routing Registry

When Hermes exposes installed skill descriptions to the model, use this registry as the routing map:

- `meta-router`: `/omh`, `./omh`
- `loop`: `loop`, `./loop`, `$loop`, `goal loop`, `long horizon goal`, `never stop`, `research plan goal feedback`, `token exhaustion resume`, `permission profile`
- `context`: `ulw-context`, `$context`, `./context`, `project terminology alignment`, `review project terms`, `align project terminology`, `terminology this project uses`
- `deep-interview`: `deep-interview`, `$deep-interview`, `interview`, `don't assume`, `clarify`, `feature shaping`, `ambiguous product request`, `one question`, `要件を詰めて`
- `jit-learn`: `jit-learn`, `learn next`, `learn now`, `blocker-specific learning target`, `highest-leverage learning target`, `immediate learning payoff`, `immediately applicable learning brief`, `source-backed learning brief`, `학습 주제`
- `ultrawork`: `ultrawork`, `$ultrawork`, `ulw`, `$ulw`, `parallel work`, `parallel implementation`, `parallel then integrate`, `high throughput`, `coding team`
- `maestro`: `$maestro`, `ulw-maestro`, `coding handoff`, `prepare the handoff`, `prepare a coding handoff`, `hand off the coding work`, `external executor handoff`, `handoff prompt`, `delegation prompt`
- `research`: `research plan`, `literature review`, `research literature`, `review recent papers`, `deep research`, `deep-research`, `exhaustive research`, `saturation research`, `pre-spec research`
- `web-research`: `web-research`, `web research`, `web search`, `search the web`, `internet search`, `look up`, `look up sources`, `latest sources`, `fresh sources`
- `product-docs`: `product-docs`, `OMH documentation`, `oh-my-hermes documentation`, `what is OMH`, `what is oh-my-hermes`, `how does OMH work`, `OMH capability catalog`, `OMH skill catalog`, `OMH model routing`
- `source-finder`: `source-finder`, `source finder`, `source acquisition`, `source intake`, `find papers and datasets`, `find datasets and repos`, `find papers`, `find arxiv link`, `find arxiv paper`
- `research-brief`: `research-brief`, `business-research`, `business research`, `research brief`, `decision brief`, `pricing decision brief`, `decision-ready brief`, `source-backed business research`, `customer feedback trends`
- `research-department`: `research-department`, `research department`, `research ops department`, `research operations department`, `scout analyst briefer`, `scout analyst brief`, `daily research department`, `competitor research department`, `market research department`
- `paper-learning`: `paper-learning`, `paper learning`, `paper-explainer`, `paper explainer`, `paper explanation`, `explain this paper`, `explain this arxiv paper`, `paper walkthrough`, `research paper explanation`
- `strategy-brief`: `strategy-brief`, `strategy brief`, `strategy memo`, `product strategy`, `strategic options`, `decision note`, `leadership strategy`, `next strategy`, `다음 전략`
- `meeting-brief`: `meeting-brief`, `meeting brief`, `meeting agenda`, `agenda`, `discussion prompts`, `decisions needed`, `record template`, `meeting topics`, `회의 주제`
- `feedback-triage`: `feedback-triage`, `customer-feedback-triage`, `feedback triage`, `customer feedback`, `feedback cluster`, `bug or feature`, `feature request triage`, `payment failure feedback`, `feedback trends`
- `finance-analysis`: `finance analysis`, `budget variance`, `budget vs actual`, `month-end close`, `재무 분석`, `예산 대비 실적`, `월마감`
- `people-ops`: `recruiting plan`, `hiring scorecard`, `interview scorecard`, `candidate debrief`, `채용 계획`, `면접 평가표`, `후보자 비교`
- `legal-compliance-review`: `contract review`, `contract liability clause`, `regulatory analysis`, `compliance review`, `계약서 검토`, `규제 분석`, `컴플라이언스 검토`
- `support-operations`: `support escalation`, `customer support reply`, `ticket triage`, `고객 지원 에스컬레이션`, `고객 답변 초안`, `지원 티켓 분류`
- `curriculum-design`: `curriculum design`, `learning objectives`, `assessment plan`, `커리큘럼 설계`, `학습 목표`, `평가 계획`
- `localization-review`: `localization review`, `translation QA`, `locale glossary`, `현지화 검토`, `번역 QA`, `용어집`
- `sales-development`: `sales discovery`, `account plan`, `outbound messaging`, `영업 발굴`, `고객사 계획`, `아웃바운드 메시지`
- `product-brief`: `product requirements document`, `PRD`, `roadmap prioritization`, `제품 요구사항 문서`, `제품 기획서`, `로드맵 우선순위`
- `ops-review`: `ops-review`, `ops review`, `weekly ops review`, `status review`, `operating review`, `release risks`, `risks and blockers`, `priorities`, `weekly status`
- `operating-rhythm`: `operating-rhythm`, `operating rhythm`, `meeting minutes`, `meeting history`, `scrum record`, `sprint planning`, `sprint review`, `sprint retrospective`, `retro history`
- `report-package`: `report-package`, `report package`, `weekly report`, `monthly report`, `executive report`, `exec brief`, `leadership deck`, `status package`, `ppt outline`
- `materials-package`: `materials-package`, `material package`, `materials package`, `document package`, `deck file`, `binary export`, `file export`, `render qa`, `layout qa`
- `img-summary`: `img-summary`, `img summary`, `visual prompt card`, `image card`, `image generation`, `image edit`, `edit this image`, `remove the background`, `background removal`
- `design-orchestration`: `design-orchestration`, `design orchestration`, `design ownership`, `handle this product design`, `take on the design`, `デザインを任せる`, `デザイン全体を任せ`, `プロダクトデザインを任せ`, `디자인 맡겨`
- `design-quality-gate`: `design-quality-gate`, `design quality gate`, `ui ux pro max`, `design pro max`, `frontend pro max`, `visual qa pro`, `premium design`, `high quality design`, `beautiful website`
- `award-bar-score`: `award-bar-score`, `award bar score`, `award winning`, `award-winning`, `award winning website`, `award-winning website`, `award winning design`, `award ready`, `make it award winning`
- `frontend`: `frontend`, `front-end`, `front end`, `frontend skill`, `web ui`, `ui ux`, `ui/ux`, `landing page`, `web app layout`
- `frontend-refactor`: `frontend-refactor`, `front-refactor`, `frontend refactor`, `refactor this component`, `refactor the component`, `refactor my component`, `component refactor`, `react refactor`, `refactor this hook`
- `backend`: `backend`, `back-end`, `back end`, `backend skill`, `server side`, `server-side`, `api design`, `api contract`, `rest api`
- `rust`: `rust`, `rust code`, `rust skill`, `rustlang`, `borrow checker`, `lifetime error`, `ownership error`, `trait bound`, `cargo build`
- `native-debugging`: `native-debugging`, `native debugging`, `native binary`, `segfault`, `segmentation fault`, `core dump`, `stack corruption`, `memory corruption`, `heap corruption`
- `accessibility-audit`: `accessibility-audit`, `accessibility audit`, `a11y audit`, `a11y architect`, `wcag audit`, `wcag 2.2`, `wcag 2.2 aa`, `accessibility pass`, `accessibility check`
- `visual-qa`: `visual-qa`, `visual qa`, `visual QA`, `visual quality assurance`, `visual check`, `web qa`, `web visual qa`, `screenshot qa`, `screenshot check`
- `build-failure-triage`: `build-failure-triage`, `build failure triage`, `build failure`, `build-failure`, `build fix`, `build failed`, `build failing`, `compile error`, `compilation error`
- `workspace-audit`: `workspace-audit`, `workspace audit`, `repo surface audit`, `repository surface audit`, `workspace surface audit`, `repo inventory`, `surface inventory`, `skill inventory`, `prompt inventory`
- `production-audit`: `production-audit`, `production audit`, `production readiness`, `prod audit`, `prod readiness`, `ready for production`, `ready to ship`, `ship readiness`, `release readiness`
- `verification-gate`: `verification-gate`, `verification gate`, `quality gate`, `release gate`, `test gate`, `build lint test`, `lint typecheck tests`, `verify before merge`, `merge readiness gate`
- `agent-evaluation`: `agent-evaluation`, `agent evaluation`, `agent eval`, `agent benchmark`, `executor evaluation`, `executor benchmark`, `compare agents`, `compare codex claude`, `agent tournament`
- `rules-distill`: `rules-distill`, `rules distill`, `distill rules`, `rule distillation`, `principle distill`, `skill principles`, `extract agent rules`, `turn traces into rules`, `policy distill`
- `codebase-onboarding`: `codebase-onboarding`, `codebase onboarding`, `repo onboarding`, `repository onboarding`, `codebase tour`, `code tour`, `new repo orientation`, `understand this repo`, `how this repo works`
- `codegraph-refresh`: `codegraph-refresh`, `codegraph refresh`, `refresh codegraph`, `update codegraph`, `codegraph stale`, `stale codegraph`, `codegraph handoff`, `codegraph summary`, `codemap`
- `codebase-uml`: `codebase-uml`, `codebase uml`, `uml`, `plantuml`, `uml diagram`, `class diagram`, `package diagram`, `module diagram`, `architecture diagram`
- `context-budget-review`: `context-budget-review`, `context budget review`, `context budget`, `token budget review`, `token budget`, `prompt budget`, `prompt caching`, `prompt cache`, `cache hygiene`
- `security-safety-review`: `security-safety-review`, `security safety review`, `ai coding safety`, `agent safety review`, `prompt injection review`, `tool permission review`, `secret exposure review`, `destructive action review`, `supply chain safety`
- `automation-blueprint`: `automation-blueprint`, `scheduled ops`, `scheduled operation`, `scheduled operations`, `automation blueprint`, `cron blueprint`, `cron-ready`, `recurring ops`, `recurring workflow`
- `reliability-review`: `reliability-review`, `reliability review`, `incident review`, `incident postmortem`, `postmortem`, `post-mortem`, `slo review`, `slo`, `sla`
- `idea-to-deploy`: `idea-to-deploy`, `idea to deploy`, `from idea to deploy`, `plan to deploy`, `idea to launch`, `ship this idea`, `ship this feature`, `launch this feature`, `product delivery loop`
- `llm-app-dev`: `llm-app-dev`, `$llm-app-dev`, `llm app development`, `llm application development`, `build an llm app`, `build an llm feature`, `llm feature development`, `build a rag pipeline`, `rag pipeline`
- `cto-loop`: `cto-loop`, `cto loop`, `cto`, `cto pm`, `pm dev qa security ops`, `roadmap technical tradeoffs`, `technical tradeoff`, `delivery risk`, `release readiness`
- `deploy-and-monitor`: `deploy-and-monitor`, `deploy and monitor`, `deploy monitor`, `deployment monitoring`, `release monitor`, `post deploy`, `post-deploy`, `rollback`, `rollback gate`
- `ultraqa`: `ultraqa`, `$ultraqa`, `adversarial qa`, `hostile scenarios`, `e2e qa`, `real-world qa`, `qa scenario`, `release qa`, `敵対的QA`
- `plan`: `plan`, `$plan`, `implementation plan`, `task breakdown`, `safe feature`, `safely add a feature`, `add a feature`, `feature request`, `new feature`
- `ralplan`: `ralplan`, `$ralplan`, `consensus plan`, `reviewed plan`, `issue to PR`, `acceptance criteria`, `verification command`, `reviewable PR`, `risky planning`
- `adversarial-consensus`: `adversarial-consensus`, `$adversarial-consensus`, `adversarial planning`, `adversarial plan review`, `red team this plan`, `red-team this plan`, `red team the proposal`, `multi-perspective review`, `multiple perspectives`
- `code-review`: `code-review`, `$code-review`, `review`, `audit`, `find bugs`, `release gate`, `claim audit`, `evidence audit`, `README claim`
- `ai-slop-cleaner`: `ai-slop-cleaner`, `$ai-slop-cleaner`, `cleanup`, `deslop`, `refactor`, `risky`, `behavior-preserving refactor`, `risk analysis`, `refactor workflow`
- `refactor-plan`: `refactor-plan`, `refactor plan`, `plan this refactor`, `plan the refactor`, `refactor planning`, `refactor phases`, `phased refactor`, `refactor in phases`, `refactor rollback plan`
- `tech-debt-audit`: `tech-debt-audit`, `tech debt`, `tech debt audit`, `technical debt`, `technical debt audit`, `tech debt ledger`, `debt ledger`, `audit our tech debt`, `tech debt report`
- `best-practice-research`: `best-practice-research`, `best practice`, `official docs`, `upstream guidance`, `what do the docs say`, `check the docs`
- `autoresearch-goal`: `autoresearch-goal`, `research goal`, `durable research`, `critic research`
- `performance-goal`: `performance-goal`, `performance goal`, `latency`, `throughput`, `benchmark`
- `inference-serving`: `inference-serving`, `inference serving`, `serve this model`, `serve the model`, `model serving`, `serving endpoint`, `vllm`, `llama.cpp`, `llama cpp`
- `model-optimization`: `model-optimization`, `model optimization`, `optimize for model`, `onboard new model`, `calibrate new model`, `new model calibration`, `model calibration`
- `ultraperf`: `ultraperf`, `$ultraperf`, `ulw-perf`, `performance audit`, `performance bottleneck`, `find the bottleneck`, `profile the hot path`, `memory leak investigation`, `token cost hotspot`
- `wiki`: `wiki`, `project wiki`, `build a wiki`, `start a wiki`, `organize my notes`, `external knowledge store`, `knowledge base`, `Obsidian`, `markdown vault`
- `ask`: `ask`, `$ask`, `external advisor`, `ask claude`, `ask gemini`, `consult claude`, `consult gemini`, `opinion from claude`, `opinion from gemini`
- `cancel`: `cancel`, `$cancel`, `stop the workflow`, `abort the run`, `cancel the loop`
- `skill`: `skill`, `$skill`, `skills`, `manage skills`
- `doctor`: `doctor`, `$doctor`, `diagnose omh`, `installation health`
- `capability-toggle`: `capability-toggle`, `capability policy`, `disable memory`, `enable memory`, `disable coding orchestration`, `disable a capability family`, `enable a capability family`, `메모리 기능 꺼줘`, `메모리 기능 끄기`
- `running-work-board`: `running-work-board`, `running work board`, `which units are running`, `what models are running`, `지금 뭐 돌고 있어`, `뭐가 돌고 있어`, `어떤 모델로 돌고 있어`, `실행 중인 작업 보여줘`
- `model-setup`: `model-setup`, `hermes model setup`, `set up my models`, `set up my model`, `configure my models`, `configure model provider`, `connect my model provider`, `set up model role slots`, `switch my session model`
- `parallel-tools`: `parallel-tools`, `parallel tools`, `hermes parallel tools setup`, `update hermes for parallel tools`, `check parallel tool support`, `enable parallel tool calls`, `verify parallel tools capability`, `check hermes version for parallel tools`, `헤르메스 업데이트 확인해줘`
- `websearch-setup`: `websearch-setup`, `web search setup`, `make web search cheaper`, `set up web search`, `configure web search`, `reduce web search cost`, `connect scraper api key`, `set up auxiliary web-extract model`, `웹 검색 싸게 만들어줘`
- `morning-brief`: `morning-brief`, `morning brief`, `connect my email for a morning brief`, `set up morning brief`, `configure morning brief`, `connect mail for morning brief`, `connect calendar for morning brief`, `set up my morning brief`, `모닝 브리핑 설정해줘`
- `buzz`: `connect Hermes to Buzz`, `Buzz community agent`, `Buzz gateway setup`, `Buzz media attachment`, `Buzz relay self-hosting`, `Buzz connection diagnostics`, `버즈 커뮤니티 연결`, `Buzz 메시지 첨부`
- `github-event-ops`: `github-event-ops`, `github event ops`, `github ops`, `github triage`, `github pr`, `github review`, `github action`, `github actions`, `pr opened`
- `agent-board`: `agent-board`, `agent board`, `kanban`, `multi-agent`, `multi agent`, `multi agent board`, `multiple hermes agents`, `multiple hermes profiles`, `hermes profiles`
- `memory-new`: `memory-new`, `new memory`, `project memory`, `product memory`, `remember this project`, `remember this product`, `do not save`, `do not save this token`, `memory capture`
- `memory-sync`: `memory-sync`, `memory curation`, `memory review`, `memory inspect`, `memory check`, `memory update`, `context cleanup`, `curate memory`, `stale memory`
- `gateway-intent-card`: `gateway-intent-card`, `gateway intent`, `discord thread`, `slack thread`, `telegram delivery`, `discord delivery policy`, `slack delivery policy`, `telegram delivery policy`, `discord status update`
- `executor-runtime-readiness`: `executor-runtime-readiness`, `executor readiness`, `runtime readiness`, `codex readiness`, `claude code readiness`, `hermes coding readiness`, `executor tools`, `missing tools`, `missing runtime tools`
- `deliverable-package`: `deliverable-package`, `deliverable mode`, `file attachment`, `attach file`, `attachment status`, `file delivery`, `file deliverable status`, `generated file`, `첨부`
- `voice-operator`: `voice-operator`, `voice operator`, `voice-first`, `voice command`, `mobile command`, `short command`, `dictated command`, `dictated request`, `spoken request`
- `browser-operator`: `browser-operator`, `browser operator`, `browser task`, `browser operation`, `browser automation`, `browser session`, `webpage operation`, `web page operation`, `open url`
- `workspace-file-operator`: `workspace-file-operator`, `workspace file operator`, `file operator`, `file operation`, `file operations`, `filesystem task`, `filesystem operation`, `file system task`, `file system operation`
- `command-operator`: `command-operator`, `command operator`, `terminal command`, `terminal task`, `shell command`, `shell task`, `cli command`, `command execution`, `run command`
- `connector-operator`: `connector-operator`, `connector operator`, `external app action`, `external connector action`, `saas action`, `api action`, `send email`, `email customer`, `gmail draft`
- `live-info-operator`: `live-info-operator`, `live info operator`, `live information`, `real time information`, `real-time information`, `weather today`, `current weather`, `weather forecast`, `stock price`
- `external-connector-readiness`: `external-connector-readiness`, `external connector readiness`, `connector readiness matrix`, `plugin readiness matrix`, `provider readiness`, `api readiness`, `connector adoption`, `external plugin adoption`, `weather plugin readiness`
- `prompt-import-readiness`: `prompt-import-readiness`, `prompt import readiness`, `slash prompt import`, `slash prompts import`, `slash command prompt import`, `prompt library import`, `prompt folder import`, `prompt directory import`, `import CLI prompts`
- `physical-device-readiness`: `physical-device-readiness`, `physical device readiness`, `device safety readiness`, `physical device safety`, `hardware safety gate`, `3d printer readiness`, `3D printer safety`, `snapmaker printer safety`, `snapmaker readiness`
- `content-operator`: `content-operator`, `content operator`, `content workflow`, `writing workflow`, `publish-ready writing`, `publish ready writing`, `release notes`, `release note draft`, `newsletter draft`
- `media-input-operator`: `media-input-operator`, `media input operator`, `media input`, `audio transcription`, `audio transcript`, `transcribe audio`, `transcribe this audio`, `meeting recording`, `recording transcript`
- `data-analysis`: `data-analysis`, `data analysis`, `dataset analysis`, `csv analysis`, `json analysis`, `log analysis`, `table analysis`, `analyze csv`, `analyze this csv`
- `toolbelt-readiness`: `toolbelt-readiness`, `mcp readiness`, `tool readiness`, `plugin readiness`, `connector readiness`, `needed mcp`, `api credential`, `missing cli`, `missing plugin`
- `harness-session-inventory`: `harness-session-inventory`, `harness session inventory`, `session inventory`, `session adapter`, `session adapters`, `harness sessions`, `mcp inventory`, `mcp config inventory`, `mcp drift`
- `ops-observability-card`: `ops-observability-card`, `observability card`, `operations command board`, `ops command board`, `service quality board`, `service quality`, `external metric provider`, `metric provider`, `prometheus metrics`
- `achievements`: `achievements`, `achievement`, `badges`, `badge`, `my badges`, `show achievements`, `achievement summary`, `unlocked badges`, `badge progress`
- `agent-ops-review`: `agent-ops-review`, `agent ops review`, `agent productivity`, `operator productivity`, `manager view`, `quality dashboard`, `throughput review`, `agent work quality`, `coding progress quality`
- `agent-debug`: `agent-debug`, `agent debug`, `agent debugging`, `agent introspection`, `agent self-debug`, `self-debug`, `self debugging`, `looping agent`, `agent loop failure`
- `failure-signal-audit`: `failure-signal-audit`, `failure signal audit`, `silent failure`, `silent failures`, `silent failure hunter`, `swallowed error`, `swallowed errors`, `empty catch`, `ignored exception`
- `instinct-ledger`: `instinct-ledger`, `instinct ledger`, `project instincts`, `project-scoped instincts`, `project scoped instincts`, `global instincts`, `instinct review`, `instinct candidate`, `instinct candidates`
- `skill-scout`: `skill-scout`, `skill scout`, `skill candidate`, `skill candidate search`, `skill discovery`, `find a skill`, `find skills`, `top skills`, `popular skills`
- `skill-health`: `skill-health`, `skill health`, `skill portfolio health`, `skill dashboard`, `skill health dashboard`, `skill failure pattern dashboard`, `skill failure patterns`, `pending skill amendments`, `skill amendments`
- `workflow-learning`: `workflow-learning`, `workflow learning`, `route-signal`, `self-improvement store routing`, `store route review`, `memory skill wiki routing`, `learning trace`, `learning audit`, `self improvement store routing`
- `decision-recall`: `decision-recall`, `rejected decision recall`, `rejected decisions`, `why was this rejected`, `previously rejected alternative`, `거절된 결정`, `기각된 대안`
- `run-efficiency`: `run-efficiency`, `run efficiency report`, `local run efficiency`, `context utilization`, `tool duration report`, `실행 효율 리포트`, `컨텍스트 사용량`, `도구 지연 시간`
- `provider-profile-posture`: `provider-profile-posture`, `provider profile posture`, `provider profile readiness`, `secret presence confirmation`, `connector profile posture`, `공급자 프로필 상태`, `시크릿 존재 확인`, `커넥터 준비 상태`

Routing is conservative: route only on explicit invocation, strong keyword evidence, or a clear workflow-shaped request. A bare common word such as `team`, `ask`, `wiki`, or `review` is not enough when it could mean normal conversation.
