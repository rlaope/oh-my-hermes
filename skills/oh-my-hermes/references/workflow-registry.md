# OMH Workflow Registry

This generated reference is loaded only when exact workflow routing detail matters.
The always-on `oh-my-hermes` skill keeps only the compact lane map and recovery rules.

## Role Registry

- `guide`: `oh-my-hermes`, `gateway-intent-card`, `voice-operator`
- `handoff-guide`: `ralph`, `ultragoal`, `ultraprocess`, `team`, `ultrawork`, `ai-slop-cleaner`, `executor-runtime-readiness`
- `memory-keeper`: `wiki`, `memory-curation-review`
- `operator`: `strategy-brief`, `meeting-brief`, `feedback-triage`, `ops-review`, `operating-rhythm`, `report-package`, `materials-package`, `img-summary`, `design-quality-gate`, `frontend`, `visual-qa`, `automation-blueprint`, `reliability-review`, `idea-to-deploy`, `cto-loop`, `deploy-and-monitor`, `github-event-ops`, `deliverable-package`
- `planner`: `loop`, `deep-interview`, `plan`, `ralplan`
- `researcher`: `web-research`, `source-finder`, `research-brief`, `research-department`, `paper-learning`, `best-practice-research`, `autoresearch-goal`
- `reviewer`: `ultraqa`, `code-review`, `ask`
- `tracker`: `performance-goal`, `cancel`, `skill`, `doctor`, `agent-board`, `toolbelt-readiness`, `ops-observability-card`, `achievements`, `agent-ops-review`, `workflow-learning`
- Installed workflow skill policies live in generated workflow skills; compatibility/reference-only surface policies live in `docs/WORKFLOWS.md` and are not guaranteed to have `skills/<name>/SKILL.md` files.

## Automatic Routing Registry

When Hermes exposes installed skill descriptions to the model, use this registry as the routing map:

- `ralph`: `ralph`, `$ralph`, `finish until done`, `persistent execution`, `self-referential loop`
- `ultragoal`: `ultragoal`, `$ultragoal`, `durable goal`, `multi-goal`, `goal ledger`
- `loop`: `loop`, `./loop`, `$loop`, `goal loop`, `long horizon goal`, `never stop`, `research plan ultragoal feedback`
- `ultraprocess`: `ultraprocess`, `$ultraprocess`, `./ultraprocess`, `/ultraprocess`, `single-cycle delivery`, `one-cycle delivery`, `end-to-end process`
- `deep-interview`: `deep-interview`, `$deep-interview`, `interview`, `don't assume`, `clarify`, `feature shaping`, `ambiguous product request`
- `team`: `team`, `$team`, `swarm`, `parallel agents`, `coordinated workers`
- `ultrawork`: `ultrawork`, `$ultrawork`, `parallel work`, `parallel implementation`, `high throughput`
- `web-research`: `web-research`, `web research`, `web search`, `search the web`, `internet search`, `latest`, `fresh sources`
- `source-finder`: `source-finder`, `source finder`, `source acquisition`, `source intake`, `find papers and datasets`, `find datasets and repos`, `find papers`
- `research-brief`: `research-brief`, `business-research`, `business research`, `research brief`, `source-backed business research`, `customer feedback trends`, `feedback trends`
- `research-department`: `research-department`, `research department`, `research ops department`, `research operations department`, `scout analyst briefer`, `scout analyst brief`, `daily research department`
- `paper-learning`: `paper-learning`, `paper learning`, `paper-explainer`, `paper explainer`, `paper explanation`, `explain this paper`, `explain this arxiv paper`
- `strategy-brief`: `strategy-brief`, `strategy brief`, `strategy memo`, `product strategy`, `strategic options`, `decision note`, `leadership strategy`
- `meeting-brief`: `meeting-brief`, `meeting brief`, `meeting agenda`, `agenda`, `discussion prompts`, `decisions needed`, `record template`
- `feedback-triage`: `feedback-triage`, `customer-feedback-triage`, `feedback triage`, `customer feedback`, `feedback cluster`, `bug or feature`, `feature request triage`
- `ops-review`: `ops-review`, `ops review`, `weekly ops review`, `status review`, `operating review`, `release risks`, `risks and blockers`
- `operating-rhythm`: `operating-rhythm`, `operating rhythm`, `meeting minutes`, `meeting history`, `scrum record`, `sprint planning`, `sprint review`
- `report-package`: `report-package`, `report package`, `weekly report`, `monthly report`, `executive report`, `exec brief`, `leadership deck`
- `materials-package`: `materials-package`, `material package`, `materials package`, `document package`, `deck file`, `binary export`, `file export`
- `img-summary`: `img-summary`, `img summary`, `visual prompt card`, `image card`, `image generation`, `image generation features`, `image generation support`
- `design-quality-gate`: `design-quality-gate`, `design quality gate`, `ui ux pro max`, `design pro max`, `frontend pro max`, `visual qa pro`, `premium design`
- `frontend`: `frontend`, `front-end`, `front end`, `frontend skill`, `web ui`, `ui ux`, `ui/ux`
- `visual-qa`: `visual-qa`, `visual qa`, `visual QA`, `visual quality assurance`, `visual check`, `screenshot qa`, `screenshot check`
- `automation-blueprint`: `automation-blueprint`, `scheduled ops`, `scheduled operation`, `scheduled operations`, `automation blueprint`, `cron blueprint`, `cron-ready`
- `reliability-review`: `reliability-review`, `reliability review`, `incident review`, `incident postmortem`, `postmortem`, `post-mortem`, `slo review`
- `idea-to-deploy`: `idea-to-deploy`, `idea to deploy`, `from idea to deploy`, `plan to deploy`, `idea to launch`, `ship this idea`, `ship this feature`
- `cto-loop`: `cto-loop`, `cto loop`, `cto`, `cto pm`, `pm dev qa security ops`, `roadmap technical tradeoffs`, `technical tradeoff`
- `deploy-and-monitor`: `deploy-and-monitor`, `deploy and monitor`, `deploy monitor`, `deployment monitoring`, `release monitor`, `post deploy`, `post-deploy`
- `ultraqa`: `ultraqa`, `$ultraqa`, `adversarial qa`, `hostile scenarios`, `e2e qa`, `real-world qa`, `qa scenario`
- `plan`: `plan`, `$plan`, `implementation plan`, `strategy`, `task breakdown`, `safe feature`, `safely add a feature`
- `ralplan`: `ralplan`, `$ralplan`, `consensus plan`, `reviewed plan`, `issue to PR`, `acceptance criteria`, `verification command`
- `code-review`: `code-review`, `$code-review`, `review`, `audit`, `find bugs`, `release gate`, `claim audit`
- `ai-slop-cleaner`: `ai-slop-cleaner`, `$ai-slop-cleaner`, `cleanup`, `deslop`, `refactor`, `risky`, `behavior-preserving refactor`
- `best-practice-research`: `best-practice-research`, `best practice`, `official docs`, `upstream guidance`
- `autoresearch-goal`: `autoresearch-goal`, `research goal`, `durable research`, `critic research`
- `performance-goal`: `performance-goal`, `performance goal`, `latency`, `throughput`, `benchmark`
- `wiki`: `wiki`, `project wiki`, `memory`, `notes`, `external knowledge store`, `knowledge base`, `Obsidian`
- `ask`: `ask`, `$ask`, `external advisor`, `claude`, `gemini`
- `cancel`: `cancel`, `$cancel`, `stop`, `abort`
- `skill`: `skill`, `$skill`, `skills`, `manage skills`
- `doctor`: `doctor`, `$doctor`, `diagnose omh`, `installation health`
- `github-event-ops`: `github-event-ops`, `github event ops`, `pr opened`, `ci failed`, `issue opened`, `pull request webhook`, `github webhook`
- `agent-board`: `agent-board`, `agent board`, `kanban`, `multi agent board`, `multiple hermes agents`, `multiple hermes profiles`, `hermes profiles`
- `memory-curation-review`: `memory-curation-review`, `memory curation`, `memory review`, `memory inspect`, `memory check`, `memory update`, `context cleanup`
- `gateway-intent-card`: `gateway-intent-card`, `gateway intent`, `discord thread`, `slack thread`, `telegram delivery`, `session delivery`, `silent update`
- `executor-runtime-readiness`: `executor-runtime-readiness`, `runtime readiness`, `codex readiness`, `claude code readiness`, `executor tools`, `missing tools`, `handoff mode`
- `deliverable-package`: `deliverable-package`, `deliverable mode`, `file attachment`, `attach file`, `attachment status`, `file delivery`, `file deliverable status`
- `voice-operator`: `voice-operator`, `voice operator`, `voice-first`, `mobile command`, `short command`, `spoken request`, `accessibility`
- `toolbelt-readiness`: `toolbelt-readiness`, `mcp readiness`, `tool readiness`, `connector readiness`, `needed mcp`, `api credential`, `missing cli`
- `ops-observability-card`: `ops-observability-card`, `observability card`, `operations command board`, `ops command board`, `service quality board`, `service quality`, `external metric provider`
- `achievements`: `achievements`, `achievement`, `badges`, `badge`, `my badges`, `show achievements`, `achievement summary`
- `agent-ops-review`: `agent-ops-review`, `agent ops review`, `agent productivity`, `operator productivity`, `manager view`, `quality dashboard`, `throughput review`
- `workflow-learning`: `workflow-learning`, `workflow learning`, `route-signal`, `self-improvement store routing`, `store route review`, `memory skill wiki routing`, `learning trace`

Routing is conservative: route only on explicit invocation, strong keyword evidence, or a clear workflow-shaped request. A bare common word such as `team`, `ask`, `wiki`, or `review` is not enough when it could mean normal conversation.
