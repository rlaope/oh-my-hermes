# Workflow Reference

This file is generated from `src/skills/catalog.py`. Update the catalog first, then refresh this document.

The reference describes prompt-level Hermes workflow guidance and local evidence expectations. It does not claim hidden Hermes runtime behavior.

Workflow names are kept for compatibility, but each skill declares advisory wrapper guidance for whether Hermes should retain the work directly, ask the user to choose an executor, or prepare a coding handoff for coding-heavy execution.

When wrapper metadata reports `omh_target_topology/v1`, skills bind workflow state to the current Hermes target/thread, adapt only the steps that benefit from multiple targets, and fall back to single-target behavior when the active agent count is one.
`memory_review_card/v1` is separate from `status_card/v1`; `handoff_context_pack/v1` may be attached to executor handoffs only when unresolved conflicts are absent.
`goal_status_card/v1` and `goal_continuation/v1` are goal-execution payloads separate from generic `status_card/v1`; they must name the next action instead of merely summarizing work.

## Skills

### oh-my-hermes

Router guidance for using oh-my-hermes workflow skills inside Hermes Agent.

- Category: `router`
- Phase: `routing`
- Hermes role: `retained-router`
- Quality tier: `routing-gated`
- Handoff policy: Classify requests into Hermes-retained planning/research/interview lanes, executor choice, or prepared coding handoffs; do not execute code.
- Use when: Use as the top-level router when a request references oh-my-hermes, the flagship request-to-handoff path, installed workflows, or ambiguous workflow routing.
- Strong routing signals: `oh-my-hermes`, `omh`, `skill routing`, `workflow routing`, `chat routing`, `request-to-handoff`, `plain request`, `role-owned next action`, `wrapper contract`, `prepared observed`, `evidence boundary`, `상태 기록`, `증거 경계`
- Quality bar:
  - Route only from explicit invocation, strong catalog evidence, or a clear workflow-shaped request.
  - Return a clarification or fallback path instead of forcing low-confidence messages into a workflow.
  - Keep users command-agnostic by naming the next UX step rather than shell commands.
  - Use request-to-handoff as the first path when a plain request needs role, plan, handoff, or status UX.
- Required inputs:
  - user request
  - installed skill descriptions
  - Hermes skill discovery context
- Expected outputs:
  - selected workflow guidance
  - clarification question when routing is ambiguous
- Artifact expectations:
  - runtime run record when a wrapper can observe request handling
- Safety rules:
  - Prefer explicit skill invocation over weak keyword inference.
  - Ask one concise question when routing signals conflict.
  - Do not claim to override Hermes core routing.

### ralph

Hermes Ralph workflow: persistent execution with verification and review.

- Category: `execution`
- Phase: `completion`
- Hermes role: `codex-handoff-guidance`
- Quality tier: `handoff-gated`
- Handoff policy: Keep as compatibility guidance; for implementation, ask the wrapper to prepare/track the selected executor path instead of making Hermes the hidden coder.
- Use when: Use after scope is concrete and the user wants one owner to continue through implementation and verification.
- Strong routing signals: `ralph`, `$ralph`, `finish until done`, `persistent execution`, `self-referential loop`
- Quality bar:
  - Do not enter a finish-until-done loop until scope, acceptance criteria, and verification commands are concrete.
  - For coding edits, prepare and track selected executor evidence instead of implying Hermes implemented the changes.
  - Report completion only from observed execution and verification evidence.
- Required inputs:
  - concrete scope
  - acceptance criteria
  - verification commands
- Expected outputs:
  - completed work summary
  - verification evidence
  - remaining risks
- Artifact expectations:
  - goal-execution run record
  - checkpoint or final evidence when available
- Safety rules:
  - Do not imply hidden Hermes runtime behavior.
  - Use the smallest verification that can prove the claim.

### ultragoal

Hermes Ultragoal workflow: file-backed durable goal ledgers.

- Category: `execution`
- Phase: `durable-goals`
- Hermes role: `codex-handoff-guidance`
- Quality tier: `checkpoint-gated`
- Handoff policy: Use Hermes to maintain .omh/goals goal_ledger/v1 state, show goal_status_card/v1 / goal_continuation/v1 next actions, and delegate coding milestones to the selected executor with only observed runtime evidence.
- Use when: Use when work needs durable goal artifacts, checkpointed progress, and final quality gates.
- Strong routing signals: `ultragoal`, `$ultragoal`, `durable goal`, `multi-goal`, `goal ledger`
- Quality bar:
  - Keep goal state durable, inspectable, and separate from chat narration.
  - Checkpoint every success, blocker, and final quality gate with fresh evidence.
  - Reject completion with a summary-only goal_completion_gate/v1 result until required criteria, blockers, and explicitly linked runtime runs are satisfied.
  - Tell the user the next action through goal_status_card/v1 or goal_continuation/v1 instead of ending with vague follow-up copy.
  - For coding milestones, use prepared handoffs and observed executor evidence rather than hidden Hermes execution.
- Required inputs:
  - goal statement
  - acceptance criteria
  - current checkpoint or missing criteria
- Expected outputs:
  - goal_ledger/v1 updates
  - checkpoint evidence
  - goal_completion_gate/v1 result
  - completion or blocker summary
- Artifact expectations:
  - metadata-only .omh/goals ledger
  - goal_status_card/v1 or goal_continuation/v1 wrapper payload
  - runtime run record only for explicitly linked coding milestones
- Safety rules:
  - Do not imply hidden Hermes runtime behavior.
  - Use the smallest verification that can prove the claim.

### loop

Hermes Loop workflow: ambitious goal interview, research, planning, runtime ticks, handoff, feedback, and resume cycles.

- Category: `goal-loop`
- Phase: `continuous-goal-loop`
- Hermes role: `retained-cognition`
- Quality tier: `loop-gated`
- Handoff policy: Keep loop orchestration, interviews, research, planning, runtime ticks with deterministic queue shapes, feedback evaluation, status, and permission-envelope narration in Hermes; prepare selected executor/worktree/connector handoffs only when the loop produces concrete work and record completion only from linked goal/runtime evidence.
- Use when: Use when the user explicitly starts a high-level, long-horizon goal loop that should refine the goal, separate implementable work from external waiting, and keep cycling through research, planning, runtime tick queueing, handoff, feedback, and status until the authority envelope or evidence gate stops it.
- Strong routing signals: `loop`, `./loop`, `$loop`, `goal loop`, `long horizon goal`, `never stop`, `research plan ultragoal feedback`, `token exhaustion resume`, `permission profile`, `star 10k`, `10k star`, `loop engineering`, `루프`, `목표 루프`, `장기 목표`, `끝까지`, `토큰 고갈`, `피드백 루프`
- Quality bar:
  - Start with direct user intent such as `./loop` or an explicit ambitious goal loop request.
  - Reframe the north-star goal into implementable internal work without shrinking its ambition.
  - Separate research, plan, runtime tick queueing, ultragoal/handoff, feedback, waiting, and resume decisions.
  - Expose a permission profile before executor dispatch, repository mutation, PR, merge, or external publishing.
  - Keep prepared worktree/subagent/connector plans, observed executor work, linked goal completion, and external waiting as distinct evidence states.
- Required inputs:
  - north-star goal summary
  - goal reframe
  - success criteria
  - permission profile
  - feedback or wait signal
- Expected outputs:
  - loop_cycle/v1 state
  - loop_status_card/v1 next action
  - loop_runtime/v1 queued tick
  - executor-neutral handoff only when permitted
  - external-wait or checkpoint boundary
- Artifact expectations:
  - metadata-only .omh/loops loop_cycle/v1 artifact
  - loop_runtime/v1 queue entries
  - loop_status_card/v1 wrapper payload
  - linked goal_ledger/v1 only when completion evidence is required
- Safety rules:
  - Do not treat loop persistence as permission to bypass the selected permission profile.
  - Do not treat a runtime tick as worktree creation, subagent dispatch, connector I/O, implementation, review, CI, merge, publication, or completion evidence.
  - Do not claim goal completion from loop state; require linked goal_ledger/v1 completion evidence.
  - When context or token budget runs out, checkpoint or rely on resumable state instead of pretending the loop is complete.
  - External results such as market response, stars, or adoption are waiting states unless observed evidence is supplied.

### deep-interview

Hermes Deep Interview workflow: one-question-at-a-time clarification.

- Category: `clarification`
- Phase: `discovery`
- Hermes role: `retained-cognition`
- Quality tier: `clarity-gated`
- Handoff policy: Run directly in Hermes or the chat wrapper; produce a clarified brief before any coding handoff is prepared.
- Use when: Use before planning or execution when requirements are materially ambiguous.
- Strong routing signals: `deep-interview`, `$deep-interview`, `interview`, `don't assume`, `clarify`, `feature shaping`, `ambiguous product request`, `one question`, `온보딩`, `부드럽게`, `모호한 제품 요청`, `기획자`, `개발자 사이`
- Quality bar:
  - Ask exactly one blocking question per turn unless the wrapper explicitly supports a structured batch.
  - Tie each question to a missing decision that changes the plan, handoff, or stop condition.
  - Emit a clarified brief with non-goals and acceptance criteria before planning or delegation.
- Required inputs:
  - initial request
  - known repo facts
  - current ambiguity
- Expected outputs:
  - clarified brief
  - non-goals
  - decision boundaries
- Artifact expectations:
  - clarity summary or transcript when the wrapper supports it
- Safety rules:
  - Ask one question at a time.
  - Gather discoverable repo facts before asking the user.
  - Stop interviewing once ambiguity is low enough to plan.

### team

Hermes Team workflow: coordinated parallel or sequential work lanes.

- Category: `execution`
- Phase: `coordination`
- Hermes role: `codex-handoff-guidance`
- Quality tier: `coordination-gated`
- Handoff policy: Use Hermes for lane framing and status; implementation lanes should become selected executor handoff tasks unless they are research, interview, planning, or status-only.
- Use when: Use when multiple independent lanes materially improve throughput or verification.
- Strong routing signals: `team`, `$team`, `swarm`, `parallel agents`, `coordinated workers`
- Quality bar:
  - Split only independent lanes with explicit ownership and verification boundaries.
  - Keep Hermes as coordinator and status narrator while coding lanes become executor handoffs.
  - Integrate lane evidence before reporting combined progress.
- Required inputs:
  - bounded lane definitions
  - ownership boundaries
  - verification target
- Expected outputs:
  - lane results
  - integration summary
  - combined verification evidence
- Artifact expectations:
  - delegation record only when separate participants are observed
- Safety rules:
  - Use parallel lanes only when work is independent.
  - Keep shared-file edits under one owner.
  - Record unobserved delegation as not_observed.

### ultrawork

Hermes Ultrawork compatibility workflow: bounded parallel delivery guidance.

- Category: `execution`
- Phase: `parallel-delivery`
- Hermes role: `codex-handoff-guidance`
- Quality tier: `handoff-gated`
- Handoff policy: Keep the workflow name for compatibility, but convert coding lanes into explicit selected executor handoffs with disjoint scope, verification, and review evidence.
- Use when: Use when an accepted implementation plan can be split into independent, reviewable work lanes.
- Strong routing signals: `ultrawork`, `$ultrawork`, `parallel work`, `parallel implementation`, `high throughput`
- Quality bar:
  - Require disjoint lane ownership before preparing multiple coding handoffs.
  - Attach acceptance criteria, verification commands, and review expectations to each lane.
  - Keep dispatch, execution, review, CI, and merge status evidence separate.
- Required inputs:
  - accepted plan
  - lane list
  - disjoint file or responsibility scopes
  - verification commands
- Expected outputs:
  - executor handoff prompts or lane instructions
  - status summary
  - review/CI evidence requirements
- Artifact expectations:
  - prepared coding delegation record per implementation lane when wrappers can record them
- Safety rules:
  - Do not start parallel coding without disjoint ownership boundaries.
  - Keep Hermes responsible for orchestration/status, not hidden implementation.
  - Record unobserved executor work as prepared_not_observed or not_observed.

### web-research

Hermes Web Research workflow: source-backed current information gathering.

- Category: `research`
- Phase: `current-evidence`
- Hermes role: `retained-cognition`
- Quality tier: `source-gated`
- Handoff policy: Run as a Hermes-side research lane when web access is available; summarize evidence before any coding handoff and never treat research as implementation.
- Use when: Use when the user needs current web evidence, links, citations, or source comparison before planning or handoff.
- Strong routing signals: `web-research`, `web research`, `latest`, `current sources`, `source-backed research`, `investigate`, `research plan`, `조사`, `근거`, `출처`, `고객 피드백`
- Quality bar:
  - Use official or primary sources first when current or external facts matter.
  - Separate direct evidence, inference, confidence, and residual uncertainty.
  - Summarize research before any coding handoff; research is not implementation evidence.
- Required inputs:
  - research question
  - source boundaries
  - recency or jurisdiction constraints
- Expected outputs:
  - source-backed synthesis
  - links or citations
  - confidence and residual uncertainty
- Artifact expectations:
  - research notes with source URLs when the wrapper captures them
- Safety rules:
  - Prefer official or primary sources when they can answer the question.
  - Separate quoted evidence from inference.
  - State retrieval limits and dates for unstable facts.

### research-brief

Hermes Research Brief workflow: source-backed business research without pretending evidence was fetched.

- Category: `research`
- Phase: `business-brief`
- Hermes role: `retained-cognition`
- Quality tier: `source-gated`
- Handoff policy: Keep business research in Hermes; prepare a selected executor handoff only after a later accepted plan requires code changes.
- Use when: Use when Hermes should scope a business question, gather or summarize source-backed evidence, and preserve evidence/inference boundaries before strategy or handoff.
- Strong routing signals: `research-brief`, `business-research`, `business research`, `research brief`, `source-backed business research`, `customer feedback trends`, `feedback trends`, `market evidence`, `data search`, `source scan`, `자료 조사`, `데이터 서치`, `근거 조사`, `피드백 추세`, `고객 피드백 추세`
- Quality bar:
  - State the research question, source boundaries, and recency assumptions before synthesis.
  - Separate observed sources from inferred trends and unresolved uncertainty.
  - Use the brief to feed strategy or meeting work without calling it execution evidence.
- Required inputs:
  - business question
  - source boundary
  - recency or market scope
- Expected outputs:
  - evidence table
  - inference summary
  - confidence and uncertainty
- Artifact expectations:
  - research brief or source ledger when the wrapper captures observed sources
- Safety rules:
  - Do not claim sources were fetched unless Hermes or the wrapper observed them.
  - Separate evidence, inference, confidence, and missing-source gaps.
  - Route later implementation separately through an accepted plan and coding handoff.

### strategy-brief

Hermes Strategy Brief workflow: options, tradeoffs, recommendation, and decision notes.

- Category: `strategy`
- Phase: `brief`
- Hermes role: `retained-cognition`
- Quality tier: `decision-gated`
- Handoff policy: Keep strategy synthesis in Hermes; do not create implementation handoff until a decision is accepted and code work is explicit.
- Use when: Use when Hermes should turn goals and evidence into options, tradeoffs, recommendations, and a decision-ready brief.
- Strong routing signals: `strategy-brief`, `strategy brief`, `strategy memo`, `product strategy`, `strategic options`, `decision note`, `leadership strategy`, `next strategy`, `다음 전략`, `전략 정리`, `전략 메모`, `전략 옵션`, `의사결정`, `리더십 회의`
- Quality bar:
  - Name the decision, constraints, options, tradeoffs, and rejected alternatives.
  - Tie recommendations to observed evidence or mark them as assumptions.
  - Keep coding handoff disabled until strategy is accepted and code work is explicit.
- Required inputs:
  - goal
  - known evidence
  - constraints
  - decision owner
- Expected outputs:
  - options
  - tradeoffs
  - recommended direction
  - decision note
- Artifact expectations:
  - strategy brief or decision note when a wrapper captures it
- Safety rules:
  - Do not treat a draft recommendation as an accepted decision.
  - Keep unresolved assumptions visible.
  - Separate strategy from implementation planning unless the user asks for execution.

### meeting-brief

Hermes Meeting Brief workflow: agenda, prompts, decisions, and record template.

- Category: `meeting`
- Phase: `preparation`
- Hermes role: `retained-cognition`
- Quality tier: `facilitation-gated`
- Handoff policy: Run meeting preparation in Hermes; only create follow-up coding handoff from observed decisions or accepted plans.
- Use when: Use when Hermes should prepare a meeting agenda, discussion prompts, decision points, and a record template.
- Strong routing signals: `meeting-brief`, `meeting brief`, `meeting agenda`, `agenda`, `discussion prompts`, `decisions needed`, `record template`, `meeting topics`, `회의 주제`, `회의 아젠다`, `아젠다`, `회의 준비`, `논의 질문`, `결정할 것`, `기록 템플릿`
- Quality bar:
  - Turn context into agenda topics, prompts, decisions needed, and a record template.
  - Keep prep distinct from actual meeting minutes or accepted decisions.
  - Identify missing context that would change the meeting structure.
- Required inputs:
  - meeting goal
  - audience
  - known context
  - decision topics
- Expected outputs:
  - agenda
  - discussion prompts
  - decisions needed
  - action-item template
- Artifact expectations:
  - meeting brief or record template when the wrapper captures it
- Safety rules:
  - Do not claim the meeting happened from a prepared agenda.
  - Separate proposed action items from observed decisions.
  - Use a later status or decision record for actual meeting outcomes.

### feedback-triage

Hermes Feedback Triage workflow: cluster customer signals and choose the next workflow.

- Category: `triage`
- Phase: `feedback`
- Hermes role: `retained-cognition`
- Quality tier: `triage-gated`
- Handoff policy: Keep feedback triage in Hermes; recommend the next workflow and prepare a selected executor handoff only after explicit coding intent or accepted plan evidence.
- Use when: Use when Hermes should classify feedback, bug reports, and feature asks before deciding whether research, planning, or coding handoff is needed.
- Strong routing signals: `feedback-triage`, `customer-feedback-triage`, `feedback triage`, `customer feedback`, `feedback cluster`, `bug or feature`, `feature request triage`, `payment failure feedback`, `feedback trends`, `고객 피드백`, `피드백`, `피드백 분류`, `피드백을 모아서`, `결제 실패 피드백`, `버그 기능 요청`, `기능 요청`
- Quality bar:
  - Name the source boundary before clustering feedback.
  - Classify signals into bug, feature, research, or strategy follow-up without overclaiming evidence.
  - Recommend the next workflow instead of jumping straight to coding.
- Required inputs:
  - feedback items or summary
  - source boundary
  - product area
- Expected outputs:
  - clusters
  - severity or opportunity ranking
  - next workflow recommendation
- Artifact expectations:
  - feedback triage record when a wrapper captures it
- Safety rules:
  - Do not turn feedback into a roadmap, implementation plan, or coding handoff by default.
  - Separate bug signal, feature ask, severity, opportunity, and missing evidence.
  - Route code changes only after explicit user intent or accepted planning evidence.

### ops-review

Hermes Ops Review workflow: status, risks, blockers, priorities, and follow-ups.

- Category: `operations`
- Phase: `status-review`
- Hermes role: `retained-cognition`
- Quality tier: `status-gated`
- Handoff policy: Keep operating review and status narration in Hermes; delegate code fixes only from explicit accepted follow-up items.
- Use when: Use when Hermes should summarize observed status, risks, blockers, priorities, and follow-up actions for recurring operating work.
- Strong routing signals: `ops-review`, `ops review`, `weekly ops review`, `status review`, `operating review`, `release risks`, `risks and blockers`, `priorities`, `weekly status`, `운영 리뷰`, `주간 운영`, `상태 리뷰`, `리스크`, `블로커`, `우선순위`, `릴리즈 리스크`
- Quality bar:
  - Tie every status claim to observed evidence or mark it as unknown.
  - Separate risks, blockers, priorities, and follow-up owners.
  - Keep code fixes as explicit follow-up handoffs, not implicit ops-review output.
- Required inputs:
  - status evidence
  - scope
  - time window
  - known risks
- Expected outputs:
  - status summary
  - risks
  - blockers
  - priorities
  - follow-up actions
- Artifact expectations:
  - ops review record or status artifact when a wrapper captures it
- Safety rules:
  - Do not infer status from missing evidence.
  - Separate observed facts, risks, blockers, decisions, and follow-up actions.
  - Do not report review, CI, release, or merge readiness from an ops summary alone.

### idea-to-deploy

Hermes Idea-to-Deploy workflow: shape an app idea into decisions, delivery handoff, verification, release, and monitoring status.

- Category: `delivery`
- Phase: `app-delivery-loop`
- Hermes role: `retained-cognition`
- Quality tier: `delivery-gated`
- Handoff policy: Keep idea shaping, decision gates, planning, release narration, and status in Hermes; prepare selected executor handoffs only for accepted code work and record deploy/monitoring only from observed operator or wrapper evidence.
- Use when: Use when Hermes should carry a product or app idea through shaping, decision gates, plan acceptance, executor handoff, verification, release readiness, deploy, and monitoring boundaries.
- Strong routing signals: `idea-to-deploy`, `idea to deploy`, `from idea to deploy`, `plan to deploy`, `idea to launch`, `ship this idea`, `ship this feature`, `launch this feature`, `product delivery loop`, `app delivery loop`, `complete product loop`, `end-to-end app operation`, `완제품 루프`, `아이디어부터 배포`, `기획부터 배포`, `출시까지`, `앱 운영 루프`
- Quality bar:
  - Name the idea, user value, decision owner, non-goals, and success metric before planning delivery.
  - Expose idea, decision, plan, handoff, verification, release, deploy, and monitor stages as separate status steps.
  - Prepare coding handoffs only after plan acceptance and selected executor choice.
  - Mark deploy, monitoring, and rollback as unobserved until the wrapper or operator records evidence.
- Required inputs:
  - product idea
  - target user or customer signal
  - success metric
  - repo or app context
- Expected outputs:
  - stage rail
  - decision gates
  - executor handoff criteria
  - verification and deploy/monitor status boundaries
- Artifact expectations:
  - app delivery loop status record when the wrapper captures stage acceptance or observations
- Safety rules:
  - Do not claim implementation, deploy, health checks, rollback, or monitoring happened from a prepared loop.
  - Keep coding, release, and monitoring observations as separate evidence gates.
  - Ask for missing success metric, release scope, or executor choice before preparing a handoff.

### cto-loop

Hermes CTO Loop workflow: roadmap, PM, technical tradeoffs, risk, delivery, release, and follow-up operating cadence.

- Category: `leadership`
- Phase: `operating-loop`
- Hermes role: `retained-cognition`
- Quality tier: `decision-gated`
- Handoff policy: Keep CTO/PM-style synthesis, tradeoffs, risk ranking, decision notes, and status in Hermes; convert accepted implementation follow-ups into executor-neutral handoffs.
- Use when: Use when Hermes should run a leadership-style operating loop that turns signals into roadmap decisions, technical tradeoffs, delivery risk, release readiness, and explicit follow-up handoffs.
- Strong routing signals: `cto-loop`, `cto loop`, `cto`, `cto pm`, `pm dev qa security ops`, `roadmap technical tradeoffs`, `technical tradeoff`, `delivery risk`, `release readiness`, `technical leadership loop`, `leadership operating loop`, `engineering leadership`, `CTO 구조`, `PM 구조`, `로드맵`, `아키텍처 트레이드오프`, `기술 리더십`, `출시 준비`
- Quality bar:
  - Separate product priority, architecture tradeoff, delivery risk, release risk, and follow-up owner.
  - Tie recommendations to observed signals or mark assumptions.
  - Record accepted decisions separately from draft recommendations.
  - Prepare executor handoffs only for accepted implementation follow-ups.
- Required inputs:
  - operating signals
  - roadmap or release scope
  - known risks
  - decision owner
- Expected outputs:
  - priority frame
  - architecture tradeoffs
  - delivery risks
  - decision note
  - follow-up handoff candidates
- Artifact expectations:
  - leadership loop record or status summary when a wrapper captures decisions and follow-ups
- Safety rules:
  - Do not treat a CTO loop recommendation as an accepted roadmap decision.
  - Do not imply CTO, PM, QA, Security, or Ops runtime agents exist without observed wrapper evidence.
  - Separate strategy decisions from implementation handoffs and release evidence.

### deploy-and-monitor

Hermes Deploy-and-Monitor workflow: release checklist, deploy decision, health signals, rollback gate, and post-deploy status.

- Category: `monitoring`
- Phase: `release-ops`
- Hermes role: `retained-cognition`
- Quality tier: `release-gated`
- Handoff policy: Keep release checklist, health criteria, rollback gates, and status narration in Hermes; record deploy, monitor, incident, or rollback evidence only when the wrapper or operator observes it.
- Use when: Use when Hermes should prepare or narrate a release operation with deploy checklist, health signals, rollback criteria, and post-deploy status without pretending to run infrastructure.
- Strong routing signals: `deploy-and-monitor`, `deploy and monitor`, `deploy monitor`, `deployment monitoring`, `release monitor`, `post deploy`, `post-deploy`, `rollback`, `rollback gate`, `health check`, `incident watch`, `release health`, `배포 모니터링`, `배포 감시`, `롤백`, `헬스 체크`, `장애 감시`, `릴리즈 모니터링`
- Quality bar:
  - Name release scope, target environment, health signals, rollback criteria, and evidence owner.
  - Show pre-deploy, deploy decision, monitor, rollback, and post-deploy record as distinct stages.
  - Mark health and rollback status unknown until observed evidence arrives.
  - Convert fix follow-ups into separate accepted plans or executor handoffs.
- Required inputs:
  - release scope
  - environment
  - health signals
  - rollback owner
- Expected outputs:
  - pre-deploy checklist
  - deploy decision gate
  - monitoring watchlist
  - rollback criteria
  - post-deploy status boundary
- Artifact expectations:
  - release operation status record when the wrapper captures deploy or monitor observations
- Safety rules:
  - Do not claim deployment, health checks, rollback, or incident response happened from a prepared checklist.
  - Keep release readiness, deploy decision, monitor signals, and rollback as separate evidence steps.
  - Route code fixes discovered during monitoring as later executor handoffs.

### ultraqa

Hermes UltraQA workflow: adversarial QA and fix loops.

- Category: `verification`
- Phase: `qa`
- Hermes role: `hybrid-verification`
- Quality tier: `scenario-gated`
- Handoff policy: Hermes can design scenarios and report observed results; code fixes discovered by QA should become selected executor handoffs.
- Use when: Use when the task needs adversarial test scenarios, verification, and fix loops.
- Strong routing signals: `ultraqa`, `$ultraqa`, `adversarial qa`, `hostile scenarios`, `e2e qa`, `real-world qa`, `qa scenario`, `release qa`, `장애 상황`, `쿠버네티스 장애`, `적절히 진단`, `검증 체크리스트`, `릴리즈 전 gate`
- Quality bar:
  - Generate hostile scenarios from changed behavior and known risk areas.
  - Report pass/fail evidence separately from proposed fixes.
  - Delegate code mutations discovered by QA to the selected coding executor.
- Required inputs:
  - changed behavior
  - acceptance criteria
  - known risk areas
- Expected outputs:
  - adversarial scenarios
  - pass/fail evidence
  - fix recommendations
- Artifact expectations:
  - QA scenario evidence
  - runtime verification summary
- Safety rules:
  - Do not imply hidden Hermes runtime behavior.
  - Use the smallest verification that can prove the claim.

### plan

Hermes Plan workflow: structured planning before execution.

- Category: `planning`
- Phase: `plan`
- Hermes role: `retained-cognition`
- Quality tier: `acceptance-gated`
- Handoff policy: Keep planning in Hermes; if the accepted plan requires code edits, prepare a selected executor handoff after acceptance.
- Use when: Use for structured planning when implementation is not ready to start safely, including feature work that needs a safe plan before handoff.
- Strong routing signals: `plan`, `$plan`, `implementation plan`, `strategy`, `task breakdown`, `safe feature`, `safely add a feature`, `add a feature`, `feature request`, `new feature`, `product triage`, `bug triage`, `issue triage`, `reproduction plan`, `workflow hub`, `coding handoff`, `답할 차례`, `준비할 차례`, `project template`, `결제 실패`, `결제 실패 이슈`, `재현 계획`, `고객 피드백`, `기능 요청`, `요구사항 정리`, `작업 허브`, `작업 허브가 필요`, `github pr workflow`, `상태와 다음 행동`, `프로젝트별 운영`
- Quality bar:
  - Make goals, non-goals, risks, acceptance criteria, and verification shape explicit.
  - Keep draft plans unapproved until a user or wrapper accepts them.
  - Only prepare coding handoff guidance after the plan is accepted.
- Required inputs:
  - requirements
  - constraints
  - known facts
  - non-goals
- Expected outputs:
  - plan
  - acceptance criteria
  - verification strategy
- Artifact expectations:
  - plan artifact when durable execution will follow
- Safety rules:
  - Do not imply hidden Hermes runtime behavior.
  - Use the smallest verification that can prove the claim.

### ralplan

Hermes Ralplan workflow: consensus planning with review gates.

- Category: `planning`
- Phase: `reviewed-plan`
- Hermes role: `retained-cognition`
- Quality tier: `reviewed-plan-gated`
- Handoff policy: Keep consensus planning and review in Hermes; produce explicit selected executor handoff guidance only after the plan is accepted.
- Use when: Use when requirements are clear enough for planning but architecture, risks, or tests need review.
- Strong routing signals: `ralplan`, `$ralplan`, `consensus plan`, `reviewed plan`, `issue to PR`, `acceptance criteria`, `verification command`, `reviewable PR`, `PR로 만들`, `PR로 만들 수 있게`, `검증 command`, `리뷰 가능한 단위`
- Quality bar:
  - Include a planner view, risk review, and testability check before handoff.
  - Record unresolved tradeoffs and rejected options instead of flattening uncertainty.
  - Do not implement directly from consensus planning.
- Required inputs:
  - requirements
  - options
  - tradeoffs
  - test shape
- Expected outputs:
  - approved plan
  - risk review
  - handoff guidance
- Artifact expectations:
  - plan and review artifacts when a wrapper supports file-backed planning
- Safety rules:
  - Do not implement directly from the planning lane.
  - Make acceptance criteria testable.
  - Record unresolved tradeoffs explicitly.

### code-review

Hermes Code Review workflow: bug-first review with evidence.

- Category: `review`
- Phase: `critique`
- Hermes role: `hybrid-review`
- Quality tier: `finding-evidence-gated`
- Handoff policy: Hermes may frame and summarize review evidence; fixes or code mutations found during review should be delegated to the selected coding executor.
- Use when: Use for review-shaped requests; findings come first and must cite concrete evidence.
- Strong routing signals: `code-review`, `$code-review`, `review`, `audit`, `find bugs`, `release gate`, `claim audit`, `evidence audit`, `README claim`, `what actually happened`, `릴리즈 전`, `실제 코드와 맞는가`, `실제로 뭐 했는지`, `검증된 결과`
- Quality bar:
  - Lead with ranked findings grounded in file, diff, command, or artifact evidence.
  - Separate review findings from fix implementation; fixes become executor work.
  - Say clearly when no actionable issue is found and name remaining test gaps.
- Required inputs:
  - diff or files
  - expected behavior
  - test evidence
- Expected outputs:
  - ranked findings
  - open questions
  - test gaps
- Artifact expectations:
  - critic run record when review evidence is captured
- Safety rules:
  - Findings come before summaries.
  - Cite concrete evidence for every finding.
  - Say clearly when no issue is found.

### ai-slop-cleaner

Hermes AI slop cleaner workflow: behavior-preserving cleanup.

- Category: `maintenance`
- Phase: `cleanup`
- Hermes role: `codex-handoff-guidance`
- Quality tier: `regression-gated`
- Handoff policy: Use Hermes to define cleanup scope and regression checks; delegate behavior-preserving edits to the selected coding executor once tests are clear.
- Use when: Use for behavior-preserving cleanup with tests before and after edits.
- Strong routing signals: `ai-slop-cleaner`, `$ai-slop-cleaner`, `cleanup`, `deslop`, `refactor`, `risky`, `safe refactor`, `risk analysis`, `refactor workflow`, `legacy refactor`, `위험한 리팩터링`, `리팩터링`, `리팩토링`, `위험 분석`, `변경 범위 제한`, `회귀 테스트`
- Quality bar:
  - Lock current behavior with regression checks before non-trivial cleanup.
  - Prefer deletion, reuse, and boundary repair over new abstractions.
  - Rerun verification after cleanup before claiming behavior is preserved.
- Required inputs:
  - target smell
  - current behavior
  - regression checks
- Expected outputs:
  - small cleanup diff
  - before/after verification
  - residual risk
- Artifact expectations:
  - cleanup plan and regression evidence for non-trivial work
- Safety rules:
  - Lock behavior with tests before risky cleanup.
  - Prefer deletion and existing utilities over new layers.
  - Do not add dependencies for cleanup unless explicitly requested.

### best-practice-research

Hermes adaptation for bounded official/upstream best-practice research.

- Category: `research`
- Phase: `evidence`
- Hermes role: `retained-cognition`
- Quality tier: `source-gated`
- Handoff policy: Run as Hermes-side evidence gathering; hand coding to the selected executor only after source-backed guidance is summarized.
- Use when: Use when correctness depends on current official or upstream guidance.
- Strong routing signals: `best-practice-research`, `best practice`, `official docs`, `upstream guidance`
- Quality bar:
  - Use official or upstream sources first and name the version/environment assumptions.
  - Map applicability to the user's local context before recommending action.
  - Preserve residual uncertainty instead of overstating best practice.
- Required inputs:
  - chosen technology
  - question
  - version or environment constraints
- Expected outputs:
  - source-backed guidance
  - applicability notes
  - residual uncertainty
- Artifact expectations:
  - research notes or citations when the wrapper captures them
- Safety rules:
  - Do not imply hidden Hermes runtime behavior.
  - Use the smallest verification that can prove the claim.

### autoresearch-goal

Hermes adaptation for durable research-goal execution.

- Category: `research`
- Phase: `durable-research`
- Hermes role: `retained-cognition`
- Quality tier: `validator-gated`
- Handoff policy: Keep durable research in Hermes-managed artifacts; do not convert to executor handoff unless the research produces an accepted coding task.
- Use when: Use for validator-gated research that needs durable artifacts.
- Strong routing signals: `autoresearch-goal`, `research goal`, `durable research`, `critic research`
- Quality bar:
  - Define validator criteria before gathering evidence.
  - Keep durable research artifacts separate from coding execution evidence.
  - Stop with next questions or a source-backed synthesis when validation is incomplete.
- Required inputs:
  - research objective
  - validator criteria
  - source boundaries
- Expected outputs:
  - research artifact
  - validator result
  - next questions
- Artifact expectations:
  - durable research ledger or checklist
- Safety rules:
  - Do not imply hidden Hermes runtime behavior.
  - Use the smallest verification that can prove the claim.

### performance-goal

Hermes adaptation for measurable performance-goal execution.

- Category: `optimization`
- Phase: `measurement`
- Hermes role: `hybrid-measurement`
- Quality tier: `measurement-gated`
- Handoff policy: Hermes can own baselines, benchmark plans, and status; optimization code changes should be selected executor handoffs.
- Use when: Use when the goal is measurable performance improvement with evaluator evidence.
- Strong routing signals: `performance-goal`, `performance goal`, `latency`, `throughput`, `benchmark`
- Quality bar:
  - Name the metric, baseline, budget, and benchmark command before optimizing.
  - Treat code-level optimization as executor work when edits are required.
  - Report deltas only from observed benchmark evidence.
- Required inputs:
  - metric
  - baseline
  - budget
  - benchmark command
- Expected outputs:
  - measurement delta
  - implementation summary
  - benchmark evidence
- Artifact expectations:
  - baseline and final benchmark evidence
- Safety rules:
  - Do not imply hidden Hermes runtime behavior.
  - Use the smallest verification that can prove the claim.

### wiki

Hermes adaptation for maintaining a project-local markdown wiki.

- Category: `knowledge`
- Phase: `capture`
- Hermes role: `retained-knowledge`
- Quality tier: `knowledge-gated`
- Handoff policy: Run directly in Hermes as knowledge capture unless the note reveals a separate coding task.
- Use when: Use to capture durable project knowledge in markdown artifacts.
- Strong routing signals: `wiki`, `project wiki`, `memory`, `notes`
- Quality bar:
  - Capture durable facts with source evidence and retrieval hints.
  - Mark stale or uncertain knowledge instead of presenting it as permanent truth.
  - Extract separate coding tasks instead of burying them in notes.
- Required inputs:
  - project fact
  - source evidence
  - target topic
- Expected outputs:
  - markdown note
  - retrieval hint
  - staleness warning when needed
- Artifact expectations:
  - repo-local markdown knowledge artifact
- Safety rules:
  - Do not imply hidden Hermes runtime behavior.
  - Use the smallest verification that can prove the claim.

### ask

Hermes adaptation for consulting an external advisor when configured.

- Category: `review`
- Phase: `external-advice`
- Hermes role: `hybrid-review`
- Quality tier: `evidence-gated`
- Handoff policy: Use as optional advice gathering; evaluate the advice in Hermes and delegate coding changes separately.
- Use when: Use only when an external advisor is configured and would materially improve the answer.
- Strong routing signals: `ask`, `$ask`, `external advisor`, `claude`, `gemini`
- Quality bar:
  - Name the workflow target, constraints, validation evidence, and stop condition.
  - Separate Hermes guidance from executor or wrapper behavior unless evidence proves the step happened.
- Required inputs:
  - question
  - context summary
  - why external advice helps
- Expected outputs:
  - advisor summary
  - accepted/rejected advice
  - decision note
- Artifact expectations:
  - advisor transcript reference only when explicitly captured
- Safety rules:
  - Use only when configured and materially useful.
  - Treat advisor output as evidence to evaluate, not authority.
  - Do not send secrets or private prompts without explicit opt-in.

### cancel

Hermes adaptation for ending active workflow state cleanly.

- Category: `operator`
- Phase: `state-cleanup`
- Hermes role: `retained-operator`
- Quality tier: `evidence-gated`
- Handoff policy: Run directly in Hermes/runtime state; never delegate cancellation to a coding executor.
- Use when: Use to cleanly end active adapted workflow state.
- Strong routing signals: `cancel`, `$cancel`, `stop`, `abort`
- Quality bar:
  - Name the workflow target, constraints, validation evidence, and stop condition.
  - Separate Hermes guidance from executor or wrapper behavior unless evidence proves the step happened.
- Required inputs:
  - active workflow state
  - cancellation intent
- Expected outputs:
  - cleared state
  - safe stop summary
- Artifact expectations:
  - state clear record when state exists
- Safety rules:
  - Do not imply hidden Hermes runtime behavior.
  - Use the smallest verification that can prove the claim.

### skill

Hermes adaptation for managing local skills.

- Category: `operator`
- Phase: `skill-management`
- Hermes role: `retained-operator`
- Quality tier: `evidence-gated`
- Handoff policy: Use Hermes for inventory and guidance; delegate only repository code changes to the selected coding executor.
- Use when: Use for local skill listing, search, add, remove, or edit tasks.
- Strong routing signals: `skill`, `$skill`, `skills`, `manage skills`
- Quality bar:
  - Name the workflow target, constraints, validation evidence, and stop condition.
  - Separate Hermes guidance from executor or wrapper behavior unless evidence proves the step happened.
- Required inputs:
  - skill action
  - target skill name or directory
- Expected outputs:
  - skill inventory or mutation result
  - verification note
- Artifact expectations:
  - manifest update when managed skills change
- Safety rules:
  - Do not imply hidden Hermes runtime behavior.
  - Use the smallest verification that can prove the claim.

### doctor

Hermes adaptation for diagnosing oh-my-hermes installation health.

- Category: `operator`
- Phase: `diagnostics`
- Hermes role: `retained-operator`
- Quality tier: `evidence-gated`
- Handoff policy: Run directly as local health inspection; propose executor work only when a repo fix is required.
- Use when: Use to diagnose OMH installation and Hermes config registration.
- Strong routing signals: `doctor`, `$doctor`, `diagnose omh`, `installation health`
- Quality bar:
  - Name the workflow target, constraints, validation evidence, and stop condition.
  - Separate Hermes guidance from executor or wrapper behavior unless evidence proves the step happened.
- Required inputs:
  - omh home
  - Hermes home
  - observed issue
- Expected outputs:
  - health checks
  - fix guidance
  - known proof boundary
- Artifact expectations:
  - doctor state summary when runtime artifacts are writable
- Safety rules:
  - Do not imply hidden Hermes runtime behavior.
  - Use the smallest verification that can prove the claim.

## Representative Harnesses

### coding-handling

Route implementation requests through scoped context, edit discipline, tests, review, and evidence.

- Use when: Use when the user asks Hermes to write, modify, debug, refactor, or review code.
- Quality tier: `handoff-gated`
- Quality bar:
  - Clarify scope before edits when target behavior, files, or verification are missing.
  - Attach acceptance criteria, verification expectations, and review expectations to the prepared handoff.
  - Report coding progress from lifecycle evidence, not from the existence of a prepared prompt.
- Inputs:
  - task statement
  - repo context
  - constraints
  - target files or discovered touchpoints
- Outputs:
  - changed files
  - verification evidence
  - remaining risks
- Stop conditions:
  - requested behavior is implemented
  - tests or checks pass
  - known gaps are reported
- Verification:
  - run the smallest relevant tests
  - inspect generated skill output when routing changed
- Evidence ladder:
  - `coding_delegation_prepared`
  - `executor_dispatch_observed`
  - `executor_result_observed`
  - `verification_recorded`
  - `review_ci_merge_recorded_when_required`
- Wrapper actions:
  - `accept_plan`
  - `show_prompt_handoff`
  - `copy_prompt_handoff`
  - `choose_executor`
  - `send_to_executor`
  - `send_to_codex`
  - `show_status`
  - `record_result`
- Artifact events:
  - `run_started`
  - `coding_delegation_recorded`
  - `verification_recorded`
- Delegation expectation: Record prepared coding delegation with omh coding delegate; record observed execution only when Hermes exposes a separate coding, review, or verification lane.
- Privacy default: `metadata_only`
- Overclaim guards:
  - A prepared coding_delegation.json is not implementation evidence.
  - Executor completion is not review, CI, merge-readiness, or merge evidence.
- Fallback: If the request is underspecified, ask one concise clarification question before editing.

### goal-execution

Keep long-running work tied to explicit goals, checkpoints, and durable evidence.

- Use when: Use when the task has multiple milestones, durable state, or finish-until-done pressure.
- Quality tier: `checkpoint-gated`
- Quality bar:
  - Create or reference a durable goal artifact before long-running progress claims.
  - Checkpoint complete, blocked, and failed states with evidence.
  - Use summary-only rejection when a goal_completion_gate/v1 blocks completion.
  - Surface continue_goal, show_status, record_checkpoint, record_blocker, or record_completion as the next action.
  - Run final verification and review gates before reporting a goal complete.
- Inputs:
  - goal statement
  - acceptance criteria
  - current checkpoint
  - blocked or pending stories
  - linked runtime run ids when coding evidence is explicitly required
- Outputs:
  - goal_ledger/v1 updates
  - checkpoint evidence
  - goal_completion_gate/v1 result
  - goal_status_card/v1 or goal_continuation/v1 next action
- Stop conditions:
  - current goal is complete or explicitly blocked
  - checkpoint evidence is recorded
  - completion gate is ready before final completion copy
- Verification:
  - compare artifacts against acceptance criteria
  - record fresh evidence before completion
  - inspect explicitly linked runtime runs before treating coding work as observed
- Evidence ladder:
  - `goal_created`
  - `story_started`
  - `checkpoint_recorded`
  - `quality_gate_recorded`
  - `goal_closed`
- Wrapper actions:
  - `continue_goal`
  - `show_status`
  - `record_checkpoint`
  - `record_blocker`
  - `record_completion`
- Artifact events:
  - `goal_started`
  - `checkpoint_recorded`
  - `goal_completed_or_blocked`
- Delegation expectation: Record goal/delegation participants only when the active Hermes runtime exposes them.
- Privacy default: `metadata_only`
- Overclaim guards:
  - A goal ledger entry is not proof that executor work ran.
  - Prepared or unlinked runtime artifacts cannot satisfy a coding-linked goal unless the goal explicitly references that run.
  - Intermediate checkpoints cannot replace final verification and review evidence.
- Fallback: If Hermes has no goal tool, use a local checklist or file-backed ledger and still name the next action.

### planning

Turn clarified requirements into an execution-ready plan with tradeoffs and tests.

- Use when: Use before implementation when architecture, sequencing, or validation shape matters.
- Quality tier: `acceptance-gated`
- Quality bar:
  - Make goals, non-goals, decision drivers, options, risks, and test strategy explicit.
  - Record at least one rejected option and why it lost before presenting the preferred path.
  - Tie every acceptance criterion to a validation command, artifact, or explicit manual evidence gap.
  - Keep draft plans unapproved until a user or wrapper accepts them.
  - Prepare coding handoff guidance only after acceptance.
- Inputs:
  - requirements
  - constraints
  - known facts
  - non-goals
- Outputs:
  - PRD or plan
  - test strategy
  - handoff guidance
- Stop conditions:
  - plan has acceptance criteria
  - risks and alternatives are explicit
- Verification:
  - review option consistency
  - verify testability before execution
- Evidence ladder:
  - `request_clarified`
  - `plan_drafted`
  - `option_tradeoffs_recorded`
  - `test_strategy_recorded`
  - `acceptance_recorded`
  - `handoff_ready`
- Wrapper actions:
  - `accept_plan`
  - `revise_plan`
  - `cancel`
  - `prepare_handoff`
- Artifact events:
  - `plan_started`
  - `options_reviewed`
  - `handoff_recorded`
- Delegation expectation: Record planner, architect, or reviewer delegation only when observed in Hermes metadata or wrapper logs.
- Privacy default: `metadata_only`
- Overclaim guards:
  - A draft plan is not execution or review evidence.
  - Unobserved architect or critic review stays not_observed.
- Fallback: If consensus review is unavailable, do a sequential planner -> reviewer pass.

### research

Gather current or source-backed evidence before planning or coding handoff.

- Use when: Use when the request needs web/current/official source evidence or source comparison.
- Quality tier: `source-gated`
- Quality bar:
  - Scope the research question, source boundaries, recency, and jurisdiction or version assumptions before retrieval.
  - Use official or primary sources first when they can answer the question.
  - Record source quality, conflicting evidence, and retrieval gaps before synthesis.
  - Separate source evidence, inference, confidence, and retrieval limits.
  - Record dates or version boundaries for unstable facts.
- Inputs:
  - research question
  - source boundaries
  - recency or environment constraints
- Outputs:
  - source-backed synthesis
  - links or citations
  - confidence and residual uncertainty
- Stop conditions:
  - claims are source-backed
  - retrieval limits and dates are explicit
- Verification:
  - prefer official or primary sources
  - separate evidence from inference
- Evidence ladder:
  - `research_question_scoped`
  - `primary_sources_checked`
  - `conflicts_checked`
  - `evidence_synthesized`
  - `uncertainty_recorded`
- Wrapper actions:
  - `show_sources`
  - `ask_followup`
  - `prepare_plan`
- Artifact events:
  - `research_started`
  - `source_checked`
  - `synthesis_recorded`
- Delegation expectation: Record a research lane only when Hermes or the wrapper exposes source/research evidence; otherwise summarize retrieval limits explicitly.
- Privacy default: `metadata_only`
- Overclaim guards:
  - Research synthesis is not implementation evidence.
  - Unavailable web access must be reported as a retrieval gap.
- Fallback: If web access is unavailable, state the retrieval gap and fall back to best available local evidence.

### business-research

Prepare source-backed business research briefs with evidence and inference boundaries.

- Use when: Use when a business, market, customer, or operational question needs source-scoped research before strategy, meetings, or handoff.
- Quality tier: `source-gated`
- Quality bar:
  - Scope the business question and source boundary before synthesis.
  - Separate observed sources, inferred trends, confidence, and uncertainty.
  - Feed strategy or meeting work without treating the research brief as execution evidence.
- Inputs:
  - business question
  - source boundary
  - recency or market scope
- Outputs:
  - evidence table
  - inference summary
  - confidence and residual uncertainty
- Stop conditions:
  - source boundaries are explicit
  - evidence and inference are separated
  - uncertainty is recorded
- Verification:
  - check source quality
  - record missing-source gaps
  - separate observed evidence from synthesis
- Evidence ladder:
  - `business_question_scoped`
  - `source_boundary_recorded`
  - `source_evidence_recorded`
  - `business_synthesis_recorded`
  - `uncertainty_recorded`
- Wrapper actions:
  - `show_sources`
  - `ask_followup`
  - `prepare_strategy_brief`
  - `show_status`
- Artifact events:
  - `business_research_scoped`
  - `business_source_checked`
  - `business_synthesis_recorded`
- Delegation expectation: Record business research only when Hermes or the wrapper observes sources or captures a research brief.
- Privacy default: `metadata_only`
- Overclaim guards:
  - A research brief is not proof that sources were fetched unless source evidence is observed.
  - Research synthesis is not a decision, implementation, or verification result.
- Fallback: If sources are not available, label the result as a research plan or local-context synthesis rather than observed research.

### strategy-synthesis

Turn goals and evidence into strategy options, tradeoffs, and decision-ready notes.

- Use when: Use when the request asks for strategy, recommendations, decision notes, or leadership-ready synthesis.
- Quality tier: `decision-gated`
- Quality bar:
  - Name the decision, drivers, options, tradeoffs, recommendation, and assumptions.
  - Keep draft recommendations separate from accepted decisions.
  - Convert implementation follow-ups into explicit later plans or handoffs.
- Inputs:
  - goal
  - evidence summary
  - constraints
  - decision owner
- Outputs:
  - options
  - tradeoffs
  - recommendation
  - decision note
- Stop conditions:
  - decision scope is explicit
  - tradeoffs are named
  - assumptions and follow-ups are recorded
- Verification:
  - compare options
  - tie recommendation to evidence
  - record rejected alternatives
- Evidence ladder:
  - `decision_scope_recorded`
  - `options_recorded`
  - `tradeoffs_recorded`
  - `recommendation_recorded`
  - `decision_status_recorded`
- Wrapper actions:
  - `show_brief`
  - `revise_brief`
  - `record_decision`
  - `show_status`
- Artifact events:
  - `strategy_scope_recorded`
  - `options_recorded`
  - `decision_note_recorded`
- Delegation expectation: Record strategy synthesis as Hermes-retained work; record execution only after a later accepted handoff is observed.
- Privacy default: `metadata_only`
- Overclaim guards:
  - A strategy brief is not an accepted decision.
  - A recommendation is not implementation, review, CI, or merge evidence.
- Fallback: If decision authority or evidence is missing, produce assumptions and next questions instead of a final decision.

### meeting-facilitation

Prepare agendas, discussion prompts, decisions, and record templates.

- Use when: Use when the request asks Hermes to prepare a meeting, agenda, discussion guide, or follow-up record template.
- Quality tier: `facilitation-gated`
- Quality bar:
  - Prepare agenda topics, prompts, decisions needed, and a record template from available context.
  - Keep proposed agenda and action items separate from observed meeting outcomes.
  - Ask for missing context that would change participants, decisions, or timing.
- Inputs:
  - meeting goal
  - audience
  - context
  - decision topics
- Outputs:
  - agenda
  - discussion prompts
  - decisions needed
  - record template
- Stop conditions:
  - agenda is coherent
  - decisions needed are explicit
  - actual outcomes remain unobserved
- Verification:
  - check missing context
  - separate prep from outcomes
  - include record template
- Evidence ladder:
  - `meeting_goal_scoped`
  - `agenda_recorded`
  - `discussion_prompts_recorded`
  - `decisions_needed_recorded`
  - `record_template_ready`
- Wrapper actions:
  - `show_agenda`
  - `revise_brief`
  - `record_decision`
  - `show_status`
- Artifact events:
  - `meeting_context_scoped`
  - `agenda_recorded`
  - `record_template_recorded`
- Delegation expectation: Record meeting prep only as prepared content unless observed meeting notes or decisions are supplied.
- Privacy default: `metadata_only`
- Overclaim guards:
  - A prepared agenda is not evidence that a meeting happened.
  - Draft action items are not observed decisions.
- Fallback: If the meeting already happened, ask for observed notes before treating decisions as outcomes.

### customer-insight-triage

Cluster customer feedback and choose the next workflow without defaulting to coding.

- Use when: Use when feedback, bugs, feature asks, or customer signals need classification before planning or implementation.
- Quality tier: `triage-gated`
- Quality bar:
  - Scope the feedback source before clustering.
  - Separate bug signals, feature asks, severity, opportunity, and evidence gaps.
  - Recommend research, strategy, planning, or coding only as a next workflow, not as observed execution.
- Inputs:
  - feedback items or summary
  - source boundary
  - product area
- Outputs:
  - clusters
  - severity or opportunity ranking
  - next workflow recommendation
- Stop conditions:
  - source boundary is explicit
  - clusters are labeled
  - next workflow is conservative
- Verification:
  - separate bug signals from feature asks
  - rank severity and opportunity
  - avoid default coding handoff
- Evidence ladder:
  - `feedback_source_scoped`
  - `clusters_recorded`
  - `severity_opportunity_recorded`
  - `next_workflow_recommended`
- Wrapper actions:
  - `show_triage`
  - `ask_followup`
  - `prepare_plan`
  - `show_status`
- Artifact events:
  - `feedback_source_scoped`
  - `feedback_cluster_recorded`
  - `next_workflow_recorded`
- Delegation expectation: Record feedback triage as Hermes-retained analysis; record coding handoff only after explicit accepted coding intent.
- Privacy default: `metadata_only`
- Overclaim guards:
  - Feedback triage is not a roadmap, implementation plan, or coding handoff by default.
  - A bug signal is not proof that a fix was implemented or verified.
- Fallback: If feedback items are too vague, ask for source or sample items before ranking severity.

### ops-review

Summarize observed operating status, risks, blockers, priorities, and follow-up actions.

- Use when: Use when recurring work needs a weekly/status/operating review with evidence boundaries.
- Quality tier: `status-gated`
- Quality bar:
  - Tie status claims to observed evidence or mark them as unknown.
  - Separate risks, blockers, priorities, and follow-up actions.
  - Do not infer review, CI, release, or merge readiness from an ops summary alone.
- Inputs:
  - status evidence
  - scope
  - time window
  - known risks
- Outputs:
  - status summary
  - risks
  - blockers
  - priorities
  - follow-up actions
- Stop conditions:
  - status claims are evidence-bound
  - risks and blockers are separated
  - follow-ups are explicit
- Verification:
  - check evidence gaps
  - separate facts from risks
  - record follow-up ownership when known
- Evidence ladder:
  - `review_scope_recorded`
  - `status_evidence_recorded`
  - `risks_blockers_recorded`
  - `priorities_recorded`
  - `followups_recorded`
- Wrapper actions:
  - `show_status`
  - `record_blocker`
  - `record_checkpoint`
  - `prepare_plan`
- Artifact events:
  - `ops_scope_recorded`
  - `status_recorded`
  - `followups_recorded`
- Delegation expectation: Record ops review as Hermes-retained status work; execution evidence requires later observed task records.
- Privacy default: `metadata_only`
- Overclaim guards:
  - An ops review is not release, CI, review, merge, or implementation evidence.
  - Missing evidence must stay unknown, not inferred green.
- Fallback: If evidence is missing, produce a review scaffold and mark unknowns instead of claiming status.

### app-delivery-loop

Run complete app operation loops from idea through decision, handoff, release, deploy, and monitor status.

- Use when: Use when a Hermes wrapper needs a finished-product-feeling path for idea-to-deploy, CTO loops, or deploy-and-monitor work without hidden coding or infrastructure execution.
- Quality tier: `delivery-gated`
- Quality bar:
  - Name the product or release objective, user/customer value, success metric, non-goals, and owner.
  - Represent idea, decision, plan, handoff, verification, release, deploy, and monitor as separate stages.
  - Keep coding work executor-neutral until a selected executor is chosen and a handoff is accepted.
  - Keep deploy, monitoring, rollback, incident, review, CI, and merge claims unavailable until observed evidence exists.
- Inputs:
  - idea or release request
  - success metric
  - scope constraints
  - evidence sources
- Outputs:
  - stage rail
  - decision gates
  - handoff or retained-work plan
  - deploy/monitor status boundary
- Stop conditions:
  - next stage is accepted or blocked
  - unobserved deploy/monitor claims stay explicit
  - coding work has selected executor guidance when needed
- Verification:
  - check every stage has an owner
  - separate prepared from observed
  - record deploy and monitor only from evidence
- Evidence ladder:
  - `loop_scope_recorded`
  - `decision_gate_recorded`
  - `plan_or_release_gate_accepted`
  - `handoff_prepared_if_needed`
  - `verification_release_gate_recorded`
  - `deploy_monitor_observed_when_available`
- Wrapper actions:
  - `show_delivery_loop`
  - `accept_plan`
  - `choose_executor`
  - `prepare_handoff`
  - `record_deploy`
  - `record_monitor_signal`
  - `show_status`
- Artifact events:
  - `delivery_loop_scoped`
  - `decision_gate_recorded`
  - `handoff_or_release_status_recorded`
- Delegation expectation: Record app delivery loop evidence only when Hermes, a wrapper, or an operator observes stage acceptance, handoff, deploy, or monitoring events.
- Privacy default: `metadata_only`
- Overclaim guards:
  - A prepared app delivery loop is not implementation, deploy, monitor, rollback, incident, review, CI, merge-readiness, or merge evidence.
  - A CTO loop recommendation is not an accepted decision unless decision evidence is recorded.
  - A health watchlist is not observed health evidence.
- Fallback: If release scope, owner, or evidence is missing, show the loop scaffold and ask for the smallest missing decision before advancing.

### goal-loop

Run ambitious goal loops through interview, research, planning, runtime ticks with deterministic queue shapes, handoff, feedback, waiting, and resumable status without hidden execution.

- Use when: Use when a direct loop invocation or explicit long-horizon goal needs repeated cycles until evidence, authority, context, or external waiting stops the next step.
- Quality tier: `loop-gated`
- Quality bar:
  - Confirm the direct loop trigger, north-star goal, reframe, success criteria, and permission profile before cycling.
  - Separate implementable internal work from external outcomes such as stars, market reaction, adoption, or social distribution.
  - Continue automatically only inside the selected authority envelope; otherwise surface a permission action.
  - Use runtime ticks with deterministic queue shapes to prepare worktree, subagent, and connector plans, but require separate observed evidence before claiming those steps ran.
  - Treat feedback as a gate: clear internal actionable gaps continue the loop; external waiting records a wait state.
  - Never report goal completion from loop state unless linked goal_ledger/v1 completion evidence is ready.
- Inputs:
  - north-star goal summary
  - reframed implementable target
  - success criteria
  - permission profile
  - feedback or wait signal
- Outputs:
  - loop_cycle/v1 artifact
  - loop_runtime/v1 queue entry
  - loop_status_card/v1 next action
  - permission envelope
  - linked goal or runtime evidence references when available
- Stop conditions:
  - next loop step is clear
  - runtime tick queue is prepared or blocked with a reason
  - permission boundaries are explicit
  - external waiting and context exhaustion are recorded
  - goal completion claims are delegated to goal_ledger/v1
- Verification:
  - validate loop_cycle/v1
  - inspect loop_runtime/v1 queue
  - inspect loop_status_card/v1
  - check linked goal_completion_gate/v1 before completion copy
- Evidence ladder:
  - `loop_triggered`
  - `goal_reframed`
  - `permission_profile_recorded`
  - `runtime_tick_queued`
  - `research_plan_handoff_cycle_recorded`
  - `feedback_gate_evaluated`
  - `wait_or_resume_boundary_recorded`
- Wrapper actions:
  - `choose_permission_profile`
  - `start_loop`
  - `run_loop_tick`
  - `show_loop_status`
  - `prepare_handoff`
  - `choose_executor`
  - `show_status`
- Artifact events:
  - `loop_started`
  - `permission_profile_recorded`
  - `feedback_gate_recorded`
  - `loop_status_card_rendered`
- Delegation expectation: Record loop state as Hermes-retained orchestration; record executor dispatch, implementation, review, CI, merge, and external publication only when observed by a linked runtime or operator artifact.
- Privacy default: `metadata_only`
- Overclaim guards:
  - A loop_cycle/v1 artifact is not proof that coding, review, CI, merge, or external publication happened.
  - A loop_runtime/v1 tick is not proof that a worktree, subagent, connector, or executor actually ran.
  - A full-loop permission profile is still bounded by observed evidence and explicit external-production authority.
  - External outcomes stay waiting_external_observation until evidence is recorded.
- Fallback: If no wrapper or CLI artifact is available, keep a visible checklist with the same permission profile and evidence boundaries.

### deep-interview

Clarify intent and boundaries one question at a time before planning or execution.

- Use when: Use when intent, scope, non-goals, or decision authority are unclear.
- Quality tier: `clarity-gated`
- Quality bar:
  - Name the missing decision, why it matters, and the smallest answer that would unblock the next step.
  - Ask one blocking question tied to a missing decision.
  - Use discovered facts before asking the user for information already available locally.
  - Produce a clarified brief with non-goals, acceptance criteria, and remaining unknowns before planning or handoff.
- Inputs:
  - initial idea
  - current ambiguity
  - known repo facts
- Outputs:
  - clarified spec
  - non-goals
  - decision boundaries
  - acceptance criteria
- Stop conditions:
  - ambiguity is low enough
  - non-goals and decision boundaries are explicit
- Verification:
  - pressure-test assumptions
  - capture transcript or summary
- Evidence ladder:
  - `ambiguity_identified`
  - `blocking_question_asked`
  - `answer_recorded`
  - `clarified_brief_ready`
- Wrapper actions:
  - `answer:clarify`
  - `cancel`
  - `rerun_plan`
- Artifact events:
  - `interview_started`
  - `question_asked`
  - `clarity_recorded`
- Delegation expectation: Record a delegated interviewer only when Hermes exposes that lane; otherwise record sequential clarification.
- Privacy default: `metadata_only`
- Overclaim guards:
  - A clarification question is not a plan approval.
  - Do not start a handoff while the blocking decision is unanswered.
- Fallback: If structured question UI is unavailable, ask one direct question in the current surface.

### architect

Evaluate system boundaries, integration choices, and long-term maintainability.

- Use when: Use when a plan touches architecture, runtime integration, extension boundaries, or shared contracts.
- Quality tier: `boundary-gated`
- Quality bar:
  - Check the proposed change against documented product and module boundaries.
  - Name rejected alternatives and long-term maintenance tradeoffs.
  - Require clear approval or concrete requested changes before implementation.
- Inputs:
  - plan
  - context
  - constraints
  - existing architecture evidence
- Outputs:
  - architecture verdict
  - tradeoff tension
  - required changes or clear approval
- Stop conditions:
  - boundary risks are addressed
  - chosen approach fits current architecture
- Verification:
  - steelman the strongest antithesis
  - check integration claims against evidence
- Evidence ladder:
  - `architecture_context_loaded`
  - `tradeoffs_recorded`
  - `boundary_verdict_recorded`
- Wrapper actions:
  - `show_review`
  - `revise_plan`
  - `approve_plan`
- Artifact events:
  - `architecture_review_started`
  - `tradeoff_recorded`
  - `verdict_recorded`
- Delegation expectation: Record architect delegation only when Hermes exposes an architect lane or wrapper-side role result.
- Privacy default: `metadata_only`
- Overclaim guards:
  - Sequential self-review is not observed architect delegation.
  - Architecture approval does not imply implementation or test success.
- Fallback: If delegation is unavailable, run a separate self-review pass before coding.

### critic

Challenge plan consistency, quality criteria, and missing verification.

- Use when: Use after planning or before release when a bad assumption would be costly.
- Quality tier: `finding-gated`
- Quality bar:
  - Challenge plan consistency, missing verification, and weak acceptance criteria.
  - Rank concrete findings before summaries.
  - Approve only when residual risks and test gaps are explicit.
- Inputs:
  - plan
  - test spec
  - architect review
  - user constraints
- Outputs:
  - approval or requested changes
  - critical findings
  - residual risks
- Stop conditions:
  - quality criteria are testable
  - risks have mitigations
  - alternatives are fair
- Verification:
  - check principle-option consistency
  - reject vague acceptance criteria
- Evidence ladder:
  - `review_scope_loaded`
  - `findings_recorded`
  - `verdict_recorded`
  - `residual_risk_recorded`
- Wrapper actions:
  - `show_findings`
  - `request_changes`
  - `approve_plan`
- Artifact events:
  - `critic_review_started`
  - `finding_recorded`
  - `verdict_recorded`
- Delegation expectation: Record critic delegation only when Hermes exposes a critic lane or wrapper-side role result.
- Privacy default: `metadata_only`
- Overclaim guards:
  - A critic verdict is not code-review evidence unless tied to actual diff/files.
  - Approval cannot erase missing downstream verification.
- Fallback: If no critic role exists, do a bug-first checklist review and cite concrete evidence.

### qa-specialist

Design adversarial scenarios and verify user-visible behavior before completion.

- Use when: Use when changes affect workflows, installer behavior, docs examples, or routing claims.
- Quality tier: `scenario-gated`
- Quality bar:
  - Derive adversarial scenarios from user-visible behavior and changed surfaces.
  - Record pass/fail evidence for critical scenarios.
  - Turn discovered code fixes into executor handoffs.
- Inputs:
  - acceptance criteria
  - changed behavior
  - fixtures or runnable commands
- Outputs:
  - test matrix
  - hostile scenarios
  - pass/fail evidence
- Stop conditions:
  - critical scenarios pass
  - known manual gaps are listed
- Verification:
  - run targeted tests
  - cover failure modes and recovery paths
- Evidence ladder:
  - `scenario_matrix_defined`
  - `checks_run`
  - `pass_fail_recorded`
  - `fix_followup_recorded_if_needed`
- Wrapper actions:
  - `show_status`
  - `record_check`
  - `record_blocker`
- Artifact events:
  - `qa_started`
  - `scenario_recorded`
  - `pass_fail_recorded`
- Delegation expectation: Record QA delegation only when Hermes exposes a QA lane or wrapper-side QA result.
- Privacy default: `metadata_only`
- Overclaim guards:
  - A scenario list is not pass evidence.
  - Failed QA cannot be summarized as complete without a blocker or fix record.
- Fallback: If runtime automation is unavailable, use fixtures and document manual checks.

### docs-specialist

Keep public docs accurate, installable, and aligned with actual behavior.

- Use when: Use whenever user-facing commands, routing behavior, examples, or release posture change.
- Quality tier: `claim-gated`
- Quality bar:
  - Check public claims against implemented behavior and known limitations.
  - Keep examples reproducible and avoid presenting roadmap as current capability.
  - Regenerate generated references from catalog data instead of hand-editing them.
- Inputs:
  - changed behavior
  - commands
  - limitations
  - audience
- Outputs:
  - README/docs updates
  - examples
  - troubleshooting notes
- Stop conditions:
  - docs match behavior
  - claims are conservative
  - examples are reproducible
- Verification:
  - run public-content scans
  - verify commands and file references
- Evidence ladder:
  - `claims_scoped`
  - `docs_updated`
  - `generated_docs_checked`
  - `public_claims_verified`
- Wrapper actions:
  - `show_docs`
  - `record_claim_check`
  - `show_status`
- Artifact events:
  - `docs_review_started`
  - `claim_checked`
  - `docs_updated`
- Delegation expectation: Record docs delegation only when Hermes exposes a docs lane or wrapper-side docs result.
- Privacy default: `metadata_only`
- Overclaim guards:
  - Documentation of a future adapter is not proof that a transport exists.
  - Generated docs must match catalog data before release claims are made.
- Fallback: If behavior is not implemented yet, label it as roadmap instead of current capability.
