# OMH Workflow Registry

This generated reference is loaded only when exact workflow routing detail matters.
The always-on `oh-my-hermes` skill keeps only the compact lane map and recovery rules.

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

- `guide`: `oh-my-hermes`, `gateway-intent-card`, `voice-operator`, `browser-operator`, `workspace-file-operator`, `command-operator`, `connector-operator`, `live-info-operator`, `external-connector-readiness`, `prompt-import-readiness`, `content-operator`, `media-input-operator`, `data-analysis`
- `handoff-guide`: `ralph`, `ultragoal`, `ultraprocess`, `team`, `ultrawork`, `ai-slop-cleaner`, `executor-runtime-readiness`
- `memory-keeper`: `rules-distill`, `wiki`, `memory-sync`
- `operator`: `strategy-brief`, `meeting-brief`, `feedback-triage`, `ops-review`, `operating-rhythm`, `report-package`, `materials-package`, `img-summary`, `design-orchestration`, `design-quality-gate`, `frontend`, `visual-qa`, `workspace-audit`, `agent-evaluation`, `automation-blueprint`, `reliability-review`, `idea-to-deploy`, `cto-loop`, `deploy-and-monitor`, `github-event-ops`, `deliverable-package`, `physical-device-readiness`, `agent-debug`, `skill-scout`, `skill-health`
- `planner`: `loop`, `deep-interview`, `codebase-onboarding`, `codegraph-refresh`, `plan`, `ralplan`
- `researcher`: `web-research`, `source-finder`, `research-brief`, `research-department`, `paper-learning`, `best-practice-research`, `autoresearch-goal`
- `reviewer`: `accessibility-audit`, `build-failure-triage`, `production-audit`, `verification-gate`, `security-safety-review`, `ultraqa`, `code-review`, `ask`, `failure-signal-audit`
- `tracker`: `context-budget-review`, `performance-goal`, `cancel`, `skill`, `doctor`, `agent-board`, `toolbelt-readiness`, `harness-session-inventory`, `ops-observability-card`, `achievements`, `agent-ops-review`, `instinct-ledger`, `workflow-learning`
- Installed workflow skill policies live in generated workflow skills; compatibility/reference-only surface policies live in `docs/WORKFLOWS.md` and are not guaranteed to have `skills/<name>/SKILL.md` files.

## Automatic Routing Registry

When Hermes exposes installed skill descriptions to the model, use this registry as the routing map:

- `ralph`: `ralph`, `$ralph`, `finish until done`, `persistent execution`, `self-referential loop`
- `ultragoal`: `ultragoal`, `$ultragoal`, `durable goal`, `multi-goal`, `goal ledger`, `long running goal`, `완료조건까지 계속`, `keep working until acceptance criteria pass`, `장기 목표`
- `loop`: `loop`, `./loop`, `$loop`, `goal loop`, `long horizon goal`, `never stop`, `research plan ultragoal feedback`, `token exhaustion resume`, `permission profile`
- `ultraprocess`: `ultraprocess`, `$ultraprocess`, `./ultraprocess`, `/ultraprocess`, `single-cycle delivery`, `one-cycle delivery`, `end-to-end process`, `delivery process`, `research plan implement review docs pr`
- `deep-interview`: `deep-interview`, `$deep-interview`, `interview`, `don't assume`, `clarify`, `feature shaping`, `ambiguous product request`, `one question`, `온보딩`
- `team`: `team`, `$team`, `swarm`, `parallel agents`, `coordinated workers`
- `ultrawork`: `ultrawork`, `$ultrawork`, `ulw`, `$ulw`, `parallel work`, `parallel implementation`, `high throughput`
- `web-research`: `web-research`, `web research`, `web search`, `search the web`, `internet search`, `latest`, `fresh sources`, `current sources`, `current web evidence`
- `source-finder`: `source-finder`, `source finder`, `source acquisition`, `source intake`, `find papers and datasets`, `find datasets and repos`, `find papers`, `find arxiv link`, `find arxiv paper`
- `research-brief`: `research-brief`, `business-research`, `business research`, `research brief`, `source-backed business research`, `customer feedback trends`, `feedback trends`, `market evidence`, `data search`
- `research-department`: `research-department`, `research department`, `research ops department`, `research operations department`, `scout analyst briefer`, `scout analyst brief`, `daily research department`, `competitor research department`, `market research department`
- `paper-learning`: `paper-learning`, `paper learning`, `paper-explainer`, `paper explainer`, `paper explanation`, `explain this paper`, `explain this arxiv paper`, `paper walkthrough`, `research paper explanation`
- `strategy-brief`: `strategy-brief`, `strategy brief`, `strategy memo`, `product strategy`, `strategic options`, `decision note`, `leadership strategy`, `next strategy`, `다음 전략`
- `meeting-brief`: `meeting-brief`, `meeting brief`, `meeting agenda`, `agenda`, `discussion prompts`, `decisions needed`, `record template`, `meeting topics`, `회의 주제`
- `feedback-triage`: `feedback-triage`, `customer-feedback-triage`, `feedback triage`, `customer feedback`, `feedback cluster`, `bug or feature`, `feature request triage`, `payment failure feedback`, `feedback trends`
- `ops-review`: `ops-review`, `ops review`, `weekly ops review`, `status review`, `operating review`, `release risks`, `risks and blockers`, `priorities`, `weekly status`
- `operating-rhythm`: `operating-rhythm`, `operating rhythm`, `meeting minutes`, `meeting history`, `scrum record`, `sprint planning`, `sprint review`, `sprint retrospective`, `retro history`
- `report-package`: `report-package`, `report package`, `weekly report`, `monthly report`, `executive report`, `exec brief`, `leadership deck`, `status package`, `ppt outline`
- `materials-package`: `materials-package`, `material package`, `materials package`, `document package`, `deck file`, `binary export`, `file export`, `render qa`, `layout qa`
- `img-summary`: `img-summary`, `img summary`, `visual prompt card`, `image card`, `image generation`, `image edit`, `edit this image`, `remove the background`, `background removal`
- `design-orchestration`: `design-orchestration`, `design orchestration`, `design ownership`, `handle this product design`, `take on the design`, `디자인 맡겨`, `디자인 맡겨줘`, `디자인 전체 맡겨`, `프로덕트 디자인 맡겨`
- `design-quality-gate`: `design-quality-gate`, `design quality gate`, `ui ux pro max`, `design pro max`, `frontend pro max`, `visual qa pro`, `premium design`, `high quality design`, `beautiful website`
- `frontend`: `frontend`, `front-end`, `front end`, `frontend skill`, `web ui`, `ui ux`, `ui/ux`, `landing page`, `web app layout`
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
- `context-budget-review`: `context-budget-review`, `context budget review`, `context budget`, `token budget review`, `token budget`, `prompt budget`, `context compaction`, `compact context`, `too much context`
- `security-safety-review`: `security-safety-review`, `security safety review`, `ai coding safety`, `agent safety review`, `prompt injection review`, `tool permission review`, `secret exposure review`, `destructive action review`, `supply chain safety`
- `automation-blueprint`: `automation-blueprint`, `scheduled ops`, `scheduled operation`, `scheduled operations`, `automation blueprint`, `cron blueprint`, `cron-ready`, `recurring ops`, `recurring workflow`
- `reliability-review`: `reliability-review`, `reliability review`, `incident review`, `incident postmortem`, `postmortem`, `post-mortem`, `slo review`, `slo`, `sla`
- `idea-to-deploy`: `idea-to-deploy`, `idea to deploy`, `from idea to deploy`, `plan to deploy`, `idea to launch`, `ship this idea`, `ship this feature`, `launch this feature`, `product delivery loop`
- `cto-loop`: `cto-loop`, `cto loop`, `cto`, `cto pm`, `pm dev qa security ops`, `roadmap technical tradeoffs`, `technical tradeoff`, `delivery risk`, `release readiness`
- `deploy-and-monitor`: `deploy-and-monitor`, `deploy and monitor`, `deploy monitor`, `deployment monitoring`, `release monitor`, `post deploy`, `post-deploy`, `rollback`, `rollback gate`
- `ultraqa`: `ultraqa`, `$ultraqa`, `adversarial qa`, `hostile scenarios`, `e2e qa`, `real-world qa`, `qa scenario`, `release qa`, `장애 상황`
- `plan`: `plan`, `$plan`, `implementation plan`, `strategy`, `task breakdown`, `safe feature`, `safely add a feature`, `add a feature`, `feature request`
- `ralplan`: `ralplan`, `$ralplan`, `consensus plan`, `reviewed plan`, `issue to PR`, `acceptance criteria`, `verification command`, `reviewable PR`, `risky planning`
- `code-review`: `code-review`, `$code-review`, `review`, `audit`, `find bugs`, `release gate`, `claim audit`, `evidence audit`, `README claim`
- `ai-slop-cleaner`: `ai-slop-cleaner`, `$ai-slop-cleaner`, `cleanup`, `deslop`, `refactor`, `risky`, `behavior-preserving refactor`, `risk analysis`, `refactor workflow`
- `best-practice-research`: `best-practice-research`, `best practice`, `official docs`, `upstream guidance`
- `autoresearch-goal`: `autoresearch-goal`, `research goal`, `durable research`, `critic research`
- `performance-goal`: `performance-goal`, `performance goal`, `latency`, `throughput`, `benchmark`
- `wiki`: `wiki`, `project wiki`, `memory`, `notes`, `external knowledge store`, `knowledge base`, `Obsidian`, `markdown vault`, `Notion knowledge base`
- `ask`: `ask`, `$ask`, `external advisor`, `claude`, `gemini`
- `cancel`: `cancel`, `$cancel`, `stop`, `abort`
- `skill`: `skill`, `$skill`, `skills`, `manage skills`
- `doctor`: `doctor`, `$doctor`, `diagnose omh`, `installation health`
- `github-event-ops`: `github-event-ops`, `github event ops`, `github ops`, `github triage`, `github pr`, `github review`, `github action`, `github actions`, `pr opened`
- `agent-board`: `agent-board`, `agent board`, `kanban`, `multi-agent`, `multi agent`, `multi agent board`, `multiple hermes agents`, `multiple hermes profiles`, `hermes profiles`
- `memory-sync`: `memory-sync`, `memory curation`, `memory review`, `memory inspect`, `memory check`, `memory update`, `context cleanup`, `curate memory`, `stale memory`
- `gateway-intent-card`: `gateway-intent-card`, `gateway intent`, `discord thread`, `slack thread`, `telegram delivery`, `discord delivery policy`, `slack delivery policy`, `telegram delivery policy`, `discord status update`
- `executor-runtime-readiness`: `executor-runtime-readiness`, `executor readiness`, `runtime readiness`, `codex readiness`, `claude code readiness`, `hermes coding readiness`, `executor tools`, `missing tools`, `missing runtime tools`
- `deliverable-package`: `deliverable-package`, `deliverable mode`, `file attachment`, `attach file`, `attachment status`, `file delivery`, `file deliverable status`, `generated file`, `자료`
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

Routing is conservative: route only on explicit invocation, strong keyword evidence, or a clear workflow-shaped request. A bare common word such as `team`, `ask`, `wiki`, or `review` is not enough when it could mean normal conversation.
