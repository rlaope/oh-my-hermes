// The OMH desktop half: the HUD the OMH TUI draws (src/tui/panels.py),
// redrawn for Hermes Desktop as a right-hand pane and a status-bar item. It
// is a Desktop pane with the TUI's mood, not a terminal in a window (the
// owner's call of 2026-11-04): the app's sans for words, its components,
// spacing and radii, and its theme tokens, with the TUI's calm hierarchy,
// density and colour character brought over -- the default launch look
// ('spectrum': a muted violet for frames, a rose brand, a warm label) mapped
// onto Desktop's own colour tokens, so it holds in light and dark.
//
// The pane reads top to bottom: one line of state (`OMH  2 running`), the
// scope it covers (`this session` or `all sessions`), the few findings worth
// a badge, then its sections in a fixed order, each drawn only when it has
// something to say: CATCHES (the mistakes OMH caught in this session, worded
// as the TUI words them), PLAN, DELEGATION (the delegation graph while one is
// active), ROUTES (the Maestro and Kanban lanes OMH dispatched) and the
// fanout DAG. While a delegation graph runs, DELEGATION shows it as the box
// drawing the TUI prints into its transcript, made by the backend with the
// TUI's own renderer (`delegation_view`) at the pane's width in cells, which
// the pane measures and sends as `cols`; the backend draws the tree where
// the boxes do not fit. The drawing is the one place set in monospace art:
// a preformatted block in a card, scrolling sideways and never wrapping,
// each segment coloured by the state its renderer role carries.
// Hermes Desktop lists every delegate_task child in its own
// Agents panel and in the composer's status stack, so a row per native
// subagent here was a second copy of that list; the pane keeps one summary
// line for them and names that panel in its tooltip. Maestro and Kanban rows
// stay, because nothing in Desktop draws the routes OMH chose.
//
// Each colour has one meaning, through theme tokens only: the accent for
// what is running, yellow for waiting, blocked or a warning, red for failed
// (and for yolo, shown only while it is on), and the text greys for done,
// skipped and everything neutral. Monospace is kept for ids, model and route
// names and figures, and the drawing; words are set in the app's sans. Every
// word the pane colours reads at 4.5:1 or better on Desktop's light and dark
// panes: the yellow for words is the theme's yellow mixed toward the primary
// text, and no word takes the faintest text token. No gradient, glow or band.
//
// Plain ESM, loaded uncompiled through the app's disk-plugin door: only
// '@hermes/plugin-sdk', 'react' and 'react/jsx-runtime' resolve, and JSX
// syntax is a SyntaxError there, so the tree is written with jsx()/jsxs().
// The file is checked for both angle brackets (the one JSX opens with, and
// its mirror), so every function is written with the function keyword and
// every comparison goes through `exceeds` and `reaches` below.
//
// Tailwind never scans a disk plugin, so the pane's own classes live in a
// style element this file appends on register and removes on dispose. Every
// colour resolves through the app's theme tokens (var(--ui-*)), never a
// literal.
//
// Visible words go through `t`: an English and a Korean table, registered
// with the app's plugin i18n door when the host has one (so the app's own
// language setting picks the table), and the English table otherwise.
//
// Electron copies this file from plugins/omh/desktop/ to desktop-plugins/omh/
// beside a .hermes-package.json marker, and that marker keeps the half OFF
// until the user switches it on under Capabilities, then Plugins. Every
// figure shown comes from the sibling backend (dashboard/plugin_api.py)
// through ctx.rest('/hud'), which reaches /api/plugins/omh/hud inside the
// gateway process; nothing is computed here beyond formatting and counting
// the rows the reader sent, so a number the reader did not produce is never
// displayed. The usage board at the top is the one exception: it shows the
// focused chat's own figures from what the host already holds (its streamed
// usage and its context breakdown), beside the chat's recorded row the
// reader sends, and times the wait for a turn's first token from the gateway
// events this window sees.
import {
  Badge,
  GlyphSpinner,
  host,
  PanelEmpty,
  PANES_AREA,
  Skeleton,
  STATUSBAR_AREAS,
  StatusDot,
  Tip,
  useQuery,
  useValue
} from '@hermes/plugin-sdk'
import { useEffect, useState } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'

export const PLUGIN_ID = 'omh'
export const PANE_ID = 'hud'
// The floor: an OAuth remote has no socket, so polling is the only feed.
export const POLL_MS = 5000
// While the focused chat's turn runs, the plan and the lanes move by the
// second; at rest the floor is enough.
export const BUSY_POLL_MS = 2000
export const STYLE_ID = 'omh-desktop-pane-style'
export const PANE_WIDTH = '320px'
// The TUI's plan window: eight items anchored just before the first
// unfinished one, the rest folded into earlier/later counts.
export const PLAN_WINDOW_ROWS = 8
export const GRAPH_NODE_LIMIT = 8
export const LANE_LIMIT = 8
// The drawing's width in cells before the pane has measured itself: the
// default 320 px pane, less the card's insets, in 11 px JetBrains Mono.
export const DEFAULT_DRAWING_CELLS = 41
// The px the drawing's card takes off the body's width before its first
// cell: the section block's two side paddings, then the card's two borders
// and two paddings (PANE_CSS).
export const DRAWING_INSET_PX = 46
// The longest drawing the pane keeps, in lines and in segments per line.
export const DRAWING_LINE_LIMIT = 160
const DRAWING_SEGMENT_LIMIT = 64

// Bound in register(); ctx.rest is scoped to this plugin's namespace.
let rest = null
// Bound in register() when the host offers ctx.i18n; the local table otherwise.
let pluginI18n = null

// The drawing's width in cells, measured by the pane and read by every
// `useHud`, so the status item and the pane keep asking one query.
let drawingCells = DEFAULT_DRAWING_CELLS
const cellListeners = new Set()

export function setDrawingCells(cells) {
  if (!Number.isInteger(cells) || exceeds(8, cells) || cells === drawingCells) return
  drawingCells = cells
  cellListeners.forEach(function (listener) {
    listener(cells)
  })
}

function useDrawingCells() {
  const [cells, setCells] = useState(drawingCells)
  useEffect(function () {
    cellListeners.add(setCells)
    setCells(drawingCells)
    return function () {
      cellListeners.delete(setCells)
    }
  }, [])
  return cells
}

// Every comparison in the file goes through these two, so neither angle
// bracket appears in it. NaN answers false, as the operators would.
export function exceeds(a, b) {
  return Math.sign(a - b) === 1
}

export function reaches(a, b) {
  const sign = Math.sign(a - b)
  return sign === 1 || sign === 0
}

function own(object, key) {
  return Object.prototype.hasOwnProperty.call(object, key)
}

function rows(value) {
  return Array.isArray(value)
    ? value.filter(function (row) {
        return row !== null && typeof row === 'object'
      })
    : []
}

function countOf(list, predicate) {
  return list.filter(predicate).length
}

// `cols` asks the backend to draw an active delegation graph that many
// cells wide; without it the payload carries no drawing.
export function hudPath(sessionId, cols) {
  const query = []
  if (sessionId) query.push(`session=${encodeURIComponent(sessionId)}`)
  if (Number.isInteger(cols) && exceeds(cols, 0)) query.push(`cols=${cols}`)
  return query.length ? `/hud?${query.join('&')}` : '/hud'
}

function fetchHud(sessionId, cols) {
  if (!rest) {
    return Promise.reject(new Error('omh plugin context is not registered'))
  }
  return rest(hudPath(sessionId, cols))
}

// ---------------------------------------------------------------------------
// Words. `t(key, vars)` fills `{name}` from vars; a message may also be a
// function of vars, the shape the app's plugin i18n accepts too, which is
// how a count picks its singular. A key Korean lacks reads in English.
// ---------------------------------------------------------------------------

export function plural(count, noun) {
  return `${count} ${noun}${count === 1 ? '' : 's'}`
}

export const EN = {
  brand: 'OMH',
  brandTip: 'oh-my-hermes {version}',
  stateIdle: 'idle',
  stateActive: 'active',
  stateRunning: '{count} running',
  stateBlocked: '{count} blocked',
  stateFailed: '{count} failed',
  stateDone: '{count} done',
  stateQueued: '{count} queued',
  stateGateway: 'gateway {state}',
  gatewayConnecting: 'connecting',
  gatewayClosed: 'closed',
  gatewayError: 'error',
  gatewayOffline: 'offline',
  stateReaderError: 'reader error',
  stateUnavailable: 'unavailable',
  scopeSession: 'this session',
  scopeAll: 'all sessions',
  noticeBackend: 'OMH backend: {message}',
  chipRepeat: 'repeat x{count}',
  chipRepeatCycle: 'cycle-of-{period}',
  chipRepeatBlocked: 'blocked',
  chipRepeatApproval: 'approval',
  chipBoard: 'board {detail}',
  chipBoardIdle: 'board idle',
  chipDispatcher: 'board dispatcher not seen',
  chipTools: function (vars) {
    return `${plural(vars.count, 'tool')} · ${vars.elapsed}`
  },
  chipYolo: 'yolo on',
  chipShot: 'parallel shot ×{count}',
  chipShotAgo: 'parallel shot ×{count} ({age} ago)',
  sectionCatches: 'CATCHES',
  sectionPlan: 'PLAN',
  sectionDelegation: 'DELEGATION',
  sectionRoutes: 'ROUTES',
  sectionDag: 'DAG',
  catchLoop: 'stopped a loop of {laps} identical calls',
  catchCycle: 'stopped a loop of {period} calls repeated {laps} times',
  catchReread: 'pointed the re-read at line {offset}',
  catchPlan: function (vars) {
    return `kept going, plan has ${plural(vars.count, 'open item')}`
  },
  catchWait: 'flagged a wait with nothing armed to wake it',
  planEmptyTitle: 'No plan yet',
  planEmptyDescription: 'A workflow adds one when it starts.',
  planNativeTitle: 'in Hermes todos',
  planWaiting: '{count} waiting',
  planSkipped: '({count} skipped)',
  planNoteSkipped: 'skipped: {reason}',
  planNoteWaiting: 'waiting: {reason}',
  planNoteUnchanged: 'unchanged {age}',
  planFoldDone: '✓ {count} done',
  planFoldEarlier: function (vars) {
    return `… ${plural(vars.count, 'earlier task')}`
  },
  planFoldLater: function (vars) {
    return `… ${plural(vars.count, 'later task')}`
  },
  untitled: 'untitled',
  subagentsSummary: function (vars) {
    return `${plural(vars.count, 'subagent')} · ${vars.running} running`
  },
  subagentsMore: '+{count} more',
  subagentsTip: "Each subagent is listed in Hermes Desktop's Agents panel.",
  dagDefaultName: 'delegation',
  dagDone: 'done {done}/{total}',
  dagStateCount: '{count} {state}',
  dagUnchecked: '{count} handoff not checked',
  graphTitle: function (vars) {
    return `${vars.ready} ready · ${plural(vars.edges, 'edge')}`
  },
  graphMore: '+{count} more',
  graphWaitingOn: 'waiting on {nodes}',
  graphSinceOutput: '{age} since new output',
  statusPlan: 'plan {done}/{total}',
  detailPlan: 'plan {title} {done}/{total}',
  detailPlanFinished: 'plan {title} finished',
  detailPlanNative: 'plan in Hermes todos',
  spinnerLabel: 'running',
  rowTools: function (vars) {
    return plural(vars.count, 'tool')
  },
  rowTurn: 'turn {count}',
  rowTurnTools: '{turn} ({tools})',
  rowTokens: '{count} tok',
  rowTokensPerSecond: '{count} tok/s',
  rowCache: 'cache {percent}%',
  rowContext: 'ctx {percent}%',
  rowFallback: 'fallback:{count}',
  wordRunning: 'running',
  wordStuck: 'stuck',
  wordBlocked: 'blocked',
  wordStale: 'stale',
  wordWaiting: 'waiting',
  wordInterrupted: 'interrupted',
  wordFailed: 'failed',
  wordDone: 'done',
  wordCompleted: 'completed',
  wordArchived: 'archived',
  wordSkipped: 'skipped',
  wordPlanned: 'planned',
  wordQueued: 'queued',
  wordDispatched: 'dispatched',
  wordUnknown: 'unknown',
  wordReview: 'review',
  wordTodo: 'todo',
  wordTriage: 'triage',
  wordScheduled: 'scheduled',
  wordReady: 'ready',
  wordPending: 'pending',
  wordCapabilitySnapshotInvalid: 'capability snapshot invalid',
  wordOwnerProfileRenamed: 'owner profile renamed',
  wordRouteUnresolved: 'route unresolved',
  wordModalityUnknown: 'modality unknown',
  wordModalityUnsupported: 'modality unsupported',
  wordModalityTransformationUnobserved: 'modality transformation unobserved',
  wordExecutorNotReady: 'executor not ready',
  wordUnsupportedForLocalDispatch: 'unsupported for local dispatch',
  wordWorktreeFailed: 'worktree failed',
  wordNotSelected: 'not selected',
  wordModelChoiceRequired: 'model choice required',
  wordPreparedNotObserved: 'prepared not observed',
  wordAwaitingInput: 'awaiting input',
  wordPermissionBlocked: 'permission blocked',
  wordAccountLimit: 'account limit',
  wordDataMissing: 'data missing',
  wordProgressStalled: 'progress stalled',
  reasonNoNewOutput: 'no new output',
  reasonPromptAtEnd: 'prompt at end',
  reasonRepeatedError: 'repeated error: {detail}',
  reasonAccountLimit: 'account limit: {detail}',
  reasonPermissionBlocked: 'permission blocked: {detail}',
  reasonDataMissing: 'data missing: {detail}',
  costActual: 'actual',
  costEstimated: 'estimated',
  costIncluded: 'included',
  costUnknown: 'unknown',
  costEstimatedFromListPrice: 'estimated from list price',
  costReportedByGateway: 'reported by gateway',
  routeUnassigned: 'unassigned',
  dgTokens: 'Tokens',
  dgTokensSub: '↓{out} out · {prompt} in',
  dgTokensTip: 'All nodes: uncached input + cache read + cache write + output',
  dgCacheHit: 'Cache hit',
  dgCacheHitSub: '{read} of {prompt} prompt',
  dgCacheHitTip: 'cache read ÷ (uncached input + cache read + cache write)',
  dgCost: 'Cost',
  dgCostSub: '{priced}/{counted} nodes priced',
  dgCostNone: 'no usage yet',
  dgCostTip: 'Only cost Hermes recorded; unpriced tokens are not converted',
  dgNodeTime: 'Node time',
  dgNodeTimeSub: function (vars) {
    return `sum of ${plural(vars.count, 'node')}`
  },
  dgNodeTimeTip: 'Sum of node run time; parallel lanes make it larger than the wall clock',
  dgWaitsOn: function (vars) {
    return `Waits on ${plural(vars.count, 'lane')}`
  },
  dgStart: 'Start node',
  dgAfter: '← {nodes}',
  dgClose: 'Close',
  dgLayer: 'layer {count}',
  dgNotStarted: 'model ? (not started)',
  dgNotStartedTip: 'No child has started this node; Hermes has recorded no model yet',
  dgModelTip: 'model recorded for the child session',
  dgElapsed: 'Elapsed',
  dgOutput: 'Output',
  dgUnpriced: 'unpriced',
  dgCacheRead: 'Cache read',
  dgInput: 'Uncached input',
  dgCacheWrite: 'Cache write',
  dgUsageTip: 'Percentages are of prompt tokens (uncached input + cache read + cache write); output is listed apart',
  dgDependsOn: 'Depends on',
  dgBlocks: 'Next · {count} downstream',
  dgRepair: 'repair',
  dgExtend: 'extend',
  dgSession: 'session {tail}',
  dgStats: 'Stats',
  dgModels: function (vars) {
    return plural(vars.count, 'model')
  },
  dgByModel: 'By model',
  dgNodes: '#',
  dgModelRowTip: "Click to highlight this model's nodes in the graph",
  dgCriticalPath: 'Critical path',
  dgBottlenecks: 'Bottlenecks',
  dgBlocksTitle: '{title} (blocks {count})',
  dgHighlight: 'Highlight',
  dgClearHighlight: 'Clear highlight',
  dgNote: 'Cost counts only what Hermes priced; unpriced tokens stay tokens. Cache hit = cache read ÷ prompt tokens.',
  sectionUsage: 'USAGE',
  ubCalls: function (vars) {
    return plural(vars.count, 'call')
  },
  ubTokensTip: 'This chat only: uncached input + cache read + cache write + output. Sub-agents are in the DAG block',
  ubCacheTip: 'cache read ÷ (uncached input + cache read + cache write), this chat only',
  ubCostTip: 'Only cost Hermes recorded for this chat; unpriced tokens are not converted',
  ubContext: 'Context',
  ubContextSub: '{used} of {max}',
  ubContextTip: 'Context window in use now: measured by the provider after a call, estimated before one (~)',
  ubSpeed: 'TPS',
  ubSpeedSub: 'avg call {latency}',
  ubSpeedTip: 'Output tokens per second, rolling over the last 10 calls',
  ubTtft: 'TTFT',
  ubTtftSub: 'send → first token',
  ubTtftAvg: 'avg {avg} · {count} turns',
  ubTtftTip: 'Time from send to the first streamed token of the last turn, as this window saw it; tool time before that token counts',
  ubParts: 'Prompt composition'
}

export const KO = {
  brand: 'OMH',
  brandTip: 'oh-my-hermes {version}',
  stateIdle: '유휴',
  stateActive: '활성',
  stateRunning: '{count}개 실행 중',
  stateBlocked: '{count}개 막힘',
  stateFailed: '{count}개 실패',
  stateDone: '{count}개 완료',
  stateQueued: '{count}개 대기열',
  stateGateway: '게이트웨이 {state}',
  gatewayConnecting: '연결 중',
  gatewayClosed: '닫힘',
  gatewayError: '오류',
  gatewayOffline: '오프라인',
  stateReaderError: '리더 오류',
  stateUnavailable: '사용할 수 없음',
  scopeSession: '이 세션',
  scopeAll: '모든 세션',
  noticeBackend: 'OMH 백엔드: {message}',
  chipRepeat: '반복 x{count}',
  chipRepeatCycle: '{period}개 주기',
  chipRepeatBlocked: '차단됨',
  chipRepeatApproval: '승인 필요',
  chipBoard: '보드 {detail}',
  chipBoardIdle: '보드 유휴',
  chipDispatcher: '보드 디스패처가 보이지 않음',
  chipTools: function (vars) {
    return `도구 ${vars.count}개 · ${vars.elapsed}`
  },
  chipYolo: 'yolo 켜짐',
  chipShot: '병렬 호출 ×{count}',
  chipShotAgo: '병렬 호출 ×{count} ({age} 전)',
  sectionCatches: '잡아낸 실수',
  sectionPlan: '계획',
  sectionDelegation: '위임',
  sectionRoutes: '경로',
  sectionDag: 'DAG',
  catchLoop: '같은 호출 {laps}번 반복을 멈춤',
  catchCycle: '호출 {period}개가 {laps}번 반복된 루프를 멈춤',
  catchReread: '다시 읽기를 {offset}번째 줄로 안내함',
  catchPlan: '계획에 열린 항목 {count}개가 남아 계속 진행함',
  catchWait: '깨울 장치 없는 대기를 표시함',
  planEmptyTitle: '아직 계획 없음',
  planEmptyDescription: '워크플로가 시작되면 계획을 추가합니다.',
  planNativeTitle: 'Hermes 할 일에 있음',
  planWaiting: '{count}개 대기',
  planSkipped: '({count}개 건너뜀)',
  planNoteSkipped: '건너뜀: {reason}',
  planNoteWaiting: '대기: {reason}',
  planNoteUnchanged: '{age} 동안 변화 없음',
  planFoldDone: '✓ {count}개 완료',
  planFoldEarlier: '… 이전 작업 {count}개',
  planFoldLater: '… 이후 작업 {count}개',
  untitled: '제목 없음',
  subagentsSummary: '하위 에이전트 {count}개 · {running}개 실행 중',
  subagentsMore: '+{count}개 더',
  subagentsTip: '각 하위 에이전트는 Hermes Desktop의 에이전트 패널에 표시됩니다.',
  dagDefaultName: '위임',
  dagDone: '완료 {done}/{total}',
  dagStateCount: '{count} {state}',
  dagUnchecked: '핸드오프 {count}개 확인 안 됨',
  graphTitle: '준비 {ready}개 · 간선 {edges}개',
  graphMore: '+{count}개 더',
  graphWaitingOn: '{nodes} 대기 중',
  graphSinceOutput: '새 출력 후 {age}',
  statusPlan: '계획 {done}/{total}',
  detailPlan: '계획 {title} {done}/{total}',
  detailPlanFinished: '계획 {title} 완료',
  detailPlanNative: 'Hermes 할 일의 계획',
  spinnerLabel: '실행 중',
  rowTools: '도구 {count}개',
  rowTurn: '턴 {count}',
  rowTurnTools: '{turn} ({tools})',
  rowTokens: '{count} 토큰',
  rowTokensPerSecond: '초당 {count} 토큰',
  rowCache: '캐시 {percent}%',
  rowContext: '컨텍스트 {percent}%',
  rowFallback: '대체 경로 {count}회',
  wordRunning: '실행 중',
  wordStuck: '멈춤',
  wordBlocked: '막힘',
  wordStale: '오래됨',
  wordWaiting: '대기',
  wordInterrupted: '중단됨',
  wordFailed: '실패',
  wordDone: '완료',
  wordCompleted: '완료',
  wordArchived: '보관됨',
  wordSkipped: '건너뜀',
  wordPlanned: '계획됨',
  wordQueued: '대기열',
  wordDispatched: '배정됨',
  wordUnknown: '알 수 없음',
  wordReview: '검토',
  wordTodo: '할 일',
  wordTriage: '분류',
  wordScheduled: '예약됨',
  wordReady: '준비됨',
  wordPending: '대기',
  wordCapabilitySnapshotInvalid: '기능 스냅샷 오류',
  wordOwnerProfileRenamed: '담당 프로필 이름 바뀜',
  wordRouteUnresolved: '경로 미확정',
  wordModalityUnknown: '입출력 형식 모름',
  wordModalityUnsupported: '입출력 형식 미지원',
  wordModalityTransformationUnobserved: '형식 변환 미확인',
  wordExecutorNotReady: '실행기 준비 안 됨',
  wordUnsupportedForLocalDispatch: '로컬 실행 미지원',
  wordWorktreeFailed: '워크트리 실패',
  wordNotSelected: '선택 안 됨',
  wordModelChoiceRequired: '모델 선택 필요',
  wordPreparedNotObserved: '준비됨, 실행 미확인',
  wordAwaitingInput: '입력 대기',
  wordPermissionBlocked: '권한 막힘',
  wordAccountLimit: '계정 한도',
  wordDataMissing: '데이터 없음',
  wordProgressStalled: '진행 멈춤',
  reasonNoNewOutput: '새 출력 없음',
  reasonPromptAtEnd: '끝에 입력 요청',
  reasonRepeatedError: '같은 오류 반복: {detail}',
  reasonAccountLimit: '계정 한도: {detail}',
  reasonPermissionBlocked: '권한 막힘: {detail}',
  reasonDataMissing: '데이터 없음: {detail}',
  costActual: '실제',
  costEstimated: '추정',
  costIncluded: '포함',
  costUnknown: '모름',
  costEstimatedFromListPrice: '정가 기준 추정',
  costReportedByGateway: '게이트웨이 보고',
  routeUnassigned: '미배정',
  dgTokens: '토큰',
  dgTokensSub: '↓{out} 출력 · {prompt} 입력',
  dgTokensTip: '모든 노드: 캐시 미사용 입력 + 캐시 읽기 + 캐시 쓰기 + 출력',
  dgCacheHit: '캐시 적중',
  dgCacheHitSub: '프롬프트 {prompt} 중 {read}',
  dgCacheHitTip: '캐시 읽기 ÷ (캐시 미사용 입력 + 캐시 읽기 + 캐시 쓰기)',
  dgCost: '비용',
  dgCostSub: '{counted}개 노드 중 {priced}개 과금',
  dgCostNone: '아직 사용량 없음',
  dgCostTip: 'Hermes가 기록한 비용만 표시하며, 과금되지 않은 토큰은 환산하지 않습니다',
  dgNodeTime: '노드 시간',
  dgNodeTimeSub: '노드 {count}개 합계',
  dgNodeTimeTip: '노드 실행 시간의 합계로, 병렬 레인 때문에 실제 경과 시간보다 클 수 있습니다',
  dgWaitsOn: '레인 {count}개 대기 중',
  dgStart: '시작 노드',
  dgAfter: '← {nodes}',
  dgClose: '닫기',
  dgLayer: '{count}층',
  dgNotStarted: '모델 ? (시작 전)',
  dgNotStartedTip: '아직 이 노드를 시작한 자식이 없어 Hermes가 모델을 기록하지 않았습니다',
  dgModelTip: '자식 세션에 기록된 모델',
  dgElapsed: '경과',
  dgOutput: '출력',
  dgUnpriced: '미과금',
  dgCacheRead: '캐시 읽기',
  dgInput: '캐시 미사용 입력',
  dgCacheWrite: '캐시 쓰기',
  dgUsageTip: '비율은 프롬프트 토큰(캐시 미사용 입력 + 캐시 읽기 + 캐시 쓰기) 기준이며, 출력은 따로 표시합니다',
  dgDependsOn: '선행 노드',
  dgBlocks: '다음 노드 · 하위 {count}개 대기',
  dgRepair: '복구',
  dgExtend: '확장',
  dgSession: '세션 {tail}',
  dgStats: '통계',
  dgModels: '모델 {count}개',
  dgByModel: '모델별',
  dgNodes: '노드',
  dgModelRowTip: '클릭하면 그래프에서 이 모델의 노드를 강조합니다',
  dgCriticalPath: '크리티컬 패스',
  dgBottlenecks: '병목',
  dgBlocksTitle: '{title} (후속 {count}개 대기)',
  dgHighlight: '강조',
  dgClearHighlight: '강조 해제',
  dgNote: '비용은 Hermes가 과금한 것만 집계하며, 과금되지 않은 토큰은 토큰으로 남습니다. 캐시 적중 = 캐시 읽기 ÷ 프롬프트 토큰.',
  sectionUsage: '사용량',
  ubCalls: '호출 {count}회',
  ubTokensTip: '이 채팅만: 캐시 미사용 입력 + 캐시 읽기 + 캐시 쓰기 + 출력. 서브에이전트는 DAG 블록에 있습니다',
  ubCacheTip: '캐시 읽기 ÷ (캐시 미사용 입력 + 캐시 읽기 + 캐시 쓰기), 이 채팅만',
  ubCostTip: 'Hermes가 이 채팅에 기록한 비용만 표시하며, 과금되지 않은 토큰은 환산하지 않습니다',
  ubContext: '컨텍스트',
  ubContextSub: '{max} 중 {used}',
  ubContextTip: '지금 사용 중인 컨텍스트 윈도우: 호출 이후에는 공급자가 측정한 값, 그 전에는 추정값(~)입니다',
  ubSpeed: 'TPS',
  ubSpeedSub: '호출 평균 {latency}',
  ubSpeedTip: '최근 호출 10회 기준 초당 출력 토큰',
  ubTtft: 'TTFT',
  ubTtftSub: '전송 → 첫 토큰',
  ubTtftAvg: '평균 {avg} · {count}턴',
  ubTtftTip: '전송부터 마지막 턴의 첫 스트리밍 토큰까지의 시간으로, 이 창에서 관측한 값입니다. 첫 토큰 전의 도구 시간도 포함됩니다',
  ubParts: '프롬프트 구성'
}

const TABLES = { en: EN, ko: KO }

function fill(template, vars) {
  return String(template).replace(/\{(\w+)\}/g, function (whole, name) {
    return vars && own(vars, name) ? String(vars[name]) : whole
  })
}

function renderMessage(table, key, vars) {
  if (!own(table, key)) return null
  const value = table[key]
  if (typeof value === 'function') return value(vars || {})
  return typeof value === 'string' ? fill(value, vars) : null
}

// One locale's word for `key`, English where that locale has none, the key
// itself where neither has it.
export function translate(locale, key, vars) {
  const table = own(TABLES, locale) ? TABLES[locale] : EN
  const answer = renderMessage(table, key, vars)
  if (answer !== null) return answer
  const english = renderMessage(EN, key, vars)
  return english === null ? key : english
}

// The app's translator answers a string message as written (filled here)
// and calls a function message with vars; it answers the bare key for a key
// no table has, which falls back to English. A `locale` reads the local
// tables directly, as the pane does on a host without the i18n door.
export function t(key, vars, locale) {
  if (locale) return translate(locale, key, vars)
  if (pluginI18n) {
    const answer = pluginI18n.t(key, vars || {})
    if (typeof answer === 'string' && answer !== key) return fill(answer, vars)
  }
  return translate('en', key, vars)
}

export function pollInterval(busy) {
  return busy ? BUSY_POLL_MS : POLL_MS
}

export function scopeLabel(sessionId) {
  return sessionId ? t('scopeSession') : t('scopeAll')
}

// ---------------------------------------------------------------------------
// Formatters ported from the retired Hermes status widget, as the OMH TUI
// panels' are, so the surfaces spell one figure the same way: 77.0k, 4m 2s,
// ~$0.0431, category:architect(model:effort).
// ---------------------------------------------------------------------------

// Parentheses stay in the allowlist because the row identity is SHAPED by
// them: `category:architect(claude...)` and `turn 3 (12 tools)`.
// Same rule as the OMH TUI panels: whole escape sequences out,
// then letters, digits and ordinary punctuation in (`person's` must not become `persons`).
const ESCAPE_SEQUENCE = /\x1b\[[0-?]*[ -\/]*[@-~]?|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)?|\x1b[ -\/]*[0-~]?/g
export function sanitizeText(value) {
  return String(value ?? '')
    .replace(ESCAPE_SEQUENCE, '')
    .replace(/[^\p{L}\p{N} .:/_·|+()\[\]!\-',;?"#%&=@~]/gu, '')
}
export function safeText(value) {
  return sanitizeText(value).slice(0, 96)
}
// The reader caps an action title at 140 characters; the row's tooltip is
// the one place that shows it whole, so it takes a longer cut than safeText.
export function longText(value) {
  return sanitizeText(value).slice(0, 160)
}

// One decimal always kept above a thousand, bare integers under it; a
// recorded zero renders as `0`, not as nothing.
export function tokenCountText(value) {
  if (!Number.isFinite(value) || exceeds(0, value)) return ''
  if (exceeds(1000, value)) return `${Math.floor(value)}`
  const thousands = exceeds(999_950, value)
  const amount = thousands ? value / 1000 : value / 1_000_000
  return `${amount.toFixed(1)}${thousands ? 'k' : 'm'}`
}

export function elapsedText(value) {
  if (!Number.isFinite(value)) return ''
  const seconds = Math.max(0, Math.floor(value))
  if (exceeds(60, seconds)) return `${seconds}s`
  if (exceeds(3600, seconds)) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`
  return `${Math.floor(seconds / 3600)}h ${String(Math.floor(seconds / 60) % 60).padStart(2, '0')}m`
}

// An approximation keeps its `~`, a confirmed zero shows its provenance
// marker, an unvouched zero shows nothing.
export function costSegmentText(row) {
  if (!Number.isFinite(row.cost_usd)) return ''
  if (exceeds(row.cost_usd, 0)) return `${row.cost_approximate ? '~' : ''}$${row.cost_usd.toFixed(4)}`
  if (row.cost_approximate) return ''
  const provenance = safeText(row.cost_status) || safeText(row.cost_source)
  return provenance ? `$${row.cost_usd.toFixed(4)} (${enumWord('cost', provenance)})` : ''
}

// Reader enum ids are never shown as written: the few with a plainer word
// get it, the rest lose their underscores.
const HUMAN_STATES = { blocked_by_dependency: 'waiting', already_completed: 'done', dry_run_planned: 'planned' }

export function humanState(raw) {
  const word = safeText(raw)
  return own(HUMAN_STATES, word) ? HUMAN_STATES[word] : word.replace(/_/g, ' ')
}

// The word a state is shown as, in the app's language. `humanState` keeps
// the canonical English word that colours and logic key on; this is only
// what the eye reads. A word no table knows is shown as `humanState` has it.
export function stateWord(raw, locale) {
  const word = humanState(raw)
  if (!word) return ''
  return enumWord('word', word, locale)
}

// A reader enum id through one family of table keys (`word`, `cost`):
// `executor_not_ready` asks `wordExecutorNotReady`. An id no table knows is
// shown as `humanState` has it.
function enumKey(prefix, raw) {
  return `${prefix}${safeText(raw)
    .split(/[_ ]+/)
    .filter(Boolean)
    .map(function (part) {
      return part.charAt(0).toUpperCase() + part.slice(1)
    })
    .join('')}`
}

function enumWord(prefix, raw, locale) {
  const key = enumKey(prefix, raw)
  const answer = t(key, {}, locale)
  return answer === key ? humanState(raw) : answer
}

// A stuck unit's reason (`omh.coding.unit_progress`): a fixed label, or a
// fixed prefix with the offending line after the colon, which stays as data.
const REASON_PREFIXES = {
  repeated_error: 'reasonRepeatedError',
  account_limit: 'reasonAccountLimit',
  permission_blocked: 'reasonPermissionBlocked',
  data_missing: 'reasonDataMissing'
}

export function reasonWord(raw, locale) {
  const reason = safeText(raw)
  if (!reason) return ''
  const colon = reason.indexOf(':')
  if (colon !== -1 && own(REASON_PREFIXES, reason.slice(0, colon))) {
    return t(REASON_PREFIXES[reason.slice(0, colon)], { detail: reason.slice(colon + 1).trim() }, locale)
  }
  return enumWord('reason', reason, locale)
}

function gatewayWord(state) {
  const key = `gateway${String(state).charAt(0).toUpperCase()}${String(state).slice(1)}`
  const answer = t(key)
  return answer === key ? String(state) : answer
}

// The colour a state word is drawn in: the accent for running, yellow for
// waiting or blocked, red for failed, grey for done; anything else (a board
// status such as `review` or `todo`) is neutral.
const WORD_TONES = {
  running: 'accent',
  stuck: 'warn',
  blocked: 'warn',
  stale: 'warn',
  waiting: 'warn',
  interrupted: 'warn',
  failed: 'error',
  done: 'muted',
  completed: 'muted',
  archived: 'muted',
  skipped: 'muted',
  planned: 'muted'
}

export function wordTone(word) {
  return own(WORD_TONES, word) ? WORD_TONES[word] : 'tertiary'
}

// What is live, most pressing first: running, failed, blocked, each with its
// own colour and at most two of them, the same segments the status bar
// opens with. A failed lane is its own word, not folded into blocked.
export function countSegments(agents) {
  const running = Number(agents.running) || 0
  const failed = Number(agents.failed) || 0
  const blocked = Number(agents.blocked) || 0
  return [
    running ? { text: t('stateRunning', { count: running }), tone: 'accent' } : null,
    failed ? { text: t('stateFailed', { count: failed }), tone: 'error' } : null,
    blocked ? { text: t('stateBlocked', { count: blocked }), tone: 'warn' } : null
  ]
    .filter(Boolean)
    .slice(0, 2)
}

// The header's phrase from the agent counts: the live counts, else done,
// else `active` for a live run with nothing counted yet.
export function hudStateLabel(active, agents) {
  if (!active) return t('stateIdle')
  const live = countSegments(agents)
  if (live.length) return live.map(function (segment) {
    return segment.text
  }).join(' · ')
  const done = Number(agents.completed) || 0
  if (done) return t('stateDone', { count: done })
  return t('stateActive')
}

const MAESTRO_EXECUTOR_SHORT_NAMES = { codex: 'codex', claude_code: 'claude', pi_family_runtime: 'pi', hermes_local: 'hermes' }

// The route column shows WHICH model runs, not who serves it: the label
// keeps only the segment after the last slash. Shapes, as the TUI draws
// them: `category:architect(model:effort)`, `category:quick(model fallback)`,
// `category:deep(model inherit)`, `inherit(model:effort)`, a bare
// `model:effort`, `(codex/maestro model)` and `kanban/assignee(model:effort)`.
export function routeIdentity(row) {
  const modelName = safeText(row.model).split('/').pop()
  const model = [modelName, safeText(row.effort)].filter(Boolean).join(':')
  const dispatchLane = safeText(row.dispatch_lane)
  const dispatchExecutor = safeText(row.executor_profile)
  const executorName = own(MAESTRO_EXECUTOR_SHORT_NAMES, dispatchExecutor) ? MAESTRO_EXECUTOR_SHORT_NAMES[dispatchExecutor] : dispatchExecutor
  const dispatchIdentity = dispatchLane ? `(${executorName}/${dispatchLane}${modelName ? ` ${modelName}` : ''})` : ''
  const category = safeText(row.category)
  const routeOrigin = safeText(row.route_origin)
  const routeCategory = safeText(row.route_category)
  const routeTag = routeOrigin === 'fallback' ? 'fallback' : routeOrigin === 'exhausted_to_inherit' ? 'inherit' : ''
  const routeDetail = [model, routeTag].filter(Boolean).join(' ')
  const displayCategory = routeOrigin === 'exhausted_to_inherit' && routeCategory ? routeCategory : category
  const route =
    displayCategory === 'inherit'
      ? `inherit${model ? `(${model})` : ''}`
      : displayCategory
        ? `category:${displayCategory}${routeDetail ? `(${routeDetail})` : ''}`
        : model
  const routeKind = routeOrigin === 'fallback' || routeOrigin === 'exhausted_to_inherit' ? 'route-fallback' : 'route'
  if (safeText(row.lane_backend) === 'kanban') {
    const assignee = safeText(row.assignee) || t('routeUnassigned')
    const effort = safeText(row.effort)
    const detail = modelName ? `${modelName}${effort ? `:${effort}` : ''}` : ''
    return { kind: 'kanban', text: `kanban/${assignee}${detail ? `(${detail})` : ''}` }
  }
  return dispatchLane ? { kind: 'maestro', text: dispatchIdentity } : { kind: routeKind, text: route }
}

// The identity's seams, as the TUI's grammar has them: after the `category:`
// literal and before the model parenthesis. The route cell now truncates
// with an ellipsis instead of wrapping, so the pane no longer splits on
// these; tests still read the grammar through them.
export function routeFragments(text) {
  const pieces = []
  let remainder = text
  if (remainder.startsWith('category:')) {
    pieces.push('category:')
    remainder = remainder.slice('category:'.length)
  }
  const paren = remainder.indexOf('(')
  if (exceeds(paren, 0)) {
    pieces.push(remainder.slice(0, paren))
    remainder = remainder.slice(paren)
  }
  if (remainder) pieces.push(remainder)
  return pieces
}

// The tag names what runs the row: `bot` is a board worker, `sub` a
// delegate_task child of this session, `main` the Maestro binding row; a
// dispatched executor row carries no tag, as in the TUI. A `sub` row is the
// one Hermes Desktop's Agents panel lists, so the pane only counts it.
export function kindTag(row, main) {
  if (main) return 'main'
  if (safeText(row.lane_backend) === 'kanban') return 'bot'
  return safeText(row.dispatch_lane) || safeText(row.executor_profile) ? '' : 'sub'
}

function isRunningRow(row) {
  return !row.state || row.state === 'running'
}

// A row that is neither a Maestro dispatch nor a board lane: a subagent,
// which Desktop's Agents panel lists, so the pane only counts it. ROUTES
// keeps the rows OMH dispatched, the Maestro and Kanban lanes.
function isSubagentRow(row) {
  return kindTag(row, false) === 'sub'
}

// Every count the pane shows is taken from the same rows: the header, the
// status item, the subagent line and the ROUTES rows cannot disagree,
// because they partition one list. Rows count only while the reader calls
// the session active, as the TUI's agent block does. A row the reader capped
// (`+N more`) is not counted; the reader orders running rows first before
// it caps, so the cap drops settled rows before running ones.
// The short child session ids (`session_tail`) of the native lanes an active
// delegation graph draws, as the TUI's `_graph_sessions` reads them.
function graphSessions(payload) {
  const graph = payload && payload.delegation_graph
  if (!graph || graph.status !== 'active' || graph.source !== 'native') return new Set()
  return new Set(
    rows(graph.nodes)
      .map(function (node) {
        return safeText(node.session_tail)
      })
      .filter(Boolean)
  )
}

export function agentTally(payload) {
  const active = !!(payload && payload.active)
  const main = active ? rows(payload.maestro && payload.maestro.rows).slice(0, 1) : []
  const drawn = active ? graphSessions(payload) : new Set()
  // A native row whose child the delegation graph draws is left out, so one
  // lane is not counted twice (the TUI's `_agents_view` does the same).
  const listed = (active ? rows(payload.subagents && payload.subagents.rows) : []).filter(function (row) {
    return !drawn.size || safeText(row.role) !== 'hermes-native' || !drawn.has(safeText(row.task_id))
  })
  const hiddenRows = active ? Number(payload.subagents && payload.subagents.hidden_rows) || 0 : 0
  const hiddenInGraph = drawn.size
    ? Math.min(hiddenRows, Math.max(0, Number(payload.subagents && payload.subagents.hidden_in_graph) || 0))
    : 0
  const subagents = listed.filter(isSubagentRow)
  const routes = main.concat(
    listed.filter(function (row) {
      return !isSubagentRow(row)
    })
  )
  const all = main.concat(listed)
  // The lanes an active native graph draws stand in for the rows left out
  // above, so the header and status bar still count them, each once.
  const lanes = drawn.size ? lanesOf(payload.delegation_graph) : []
  const laneCount = function (states) {
    return countOf(lanes, function (node) {
      return states.includes(node.state)
    })
  }
  return {
    routes,
    subagents,
    running: countOf(all, isRunningRow) + laneCount(['running', 'dispatched']),
    blocked:
      countOf(all, function (row) {
        return row.state === 'blocked'
      }) + laneCount(['stuck', 'interrupted']),
    failed:
      countOf(all, function (row) {
        return row.state === 'failed'
      }) + laneCount(['failed']),
    done:
      countOf(all, function (row) {
        return row.state === 'done'
      }) + laneCount(['done']),
    subagentsRunning: countOf(subagents, isRunningRow),
    hidden: hiddenRows - hiddenInGraph
  }
}

function tallyCounts(tally) {
  return { running: tally.running, failed: tally.failed, blocked: tally.blocked, completed: tally.done }
}

export function stateSummary(payload) {
  return hudStateLabel(!!(payload && payload.active), tallyCounts(agentTally(payload)))
}

// Running, or live with nothing counted yet (`active`), is the accent;
// failed is red; blocked is yellow; idle and finished stay grey.
export function stateTone(payload) {
  const tally = agentTally(payload)
  if (tally.running) return 'accent'
  if (tally.failed) return 'error'
  if (tally.blocked) return 'warn'
  return payload && payload.active && !tally.done ? 'accent' : 'tertiary'
}

// The header's segments, each in its own colour: the live counts while any
// runs, failed or is blocked, else the one phrase in the state's tone.
export function headerSegments(payload) {
  const active = !!(payload && payload.active)
  const live = active ? countSegments(tallyCounts(agentTally(payload))) : []
  return live.length ? live : [{ text: stateSummary(payload), tone: stateTone(payload) }]
}

export function headerLabel(payload) {
  return stateSummary(payload)
}

// The native subagents as one line. The reader's `+N more` (rows it capped,
// of any kind) closes ROUTES when there are routes, else this line.
export function subagentSummary(payload) {
  const tally = agentTally(payload)
  const parts = []
  if (tally.subagents.length) parts.push(t('subagentsSummary', { count: tally.subagents.length, running: tally.subagentsRunning }))
  if (tally.hidden && !tally.routes.length) parts.push(t('subagentsMore', { count: tally.hidden }))
  return parts.join(' · ')
}

// The badge row: the session-wide findings the TUI header draws, each only
// when the reader observed it. A badge is muted unless it is a waiting or
// blocked finding (warn) or a danger (yolo on, a repeat escalated to a
// person: destructive). yolo off is the default and is not drawn.
export function chipList(payload) {
  const chips = []
  const repeat = payload.repeat || {}
  const repeatCount = Number(repeat.consecutive) || 0
  const repeatPeriod = Number(repeat.period) || 1
  const repeatStage = reaches(Number(repeat.intercepted) || 0, 1) ? safeText(repeat.stage) : ''
  if (repeat.status === 'observed' && reaches(repeatCount, 2)) {
    const words = [t('chipRepeat', { count: repeatCount })]
    if (exceeds(repeatPeriod, 1)) words.push(t('chipRepeatCycle', { period: repeatPeriod }))
    if (repeatStage === 'blocking') words.push(t('chipRepeatBlocked'))
    else if (repeatStage === 'approval') words.push(t('chipRepeatApproval'))
    chips.push({
      key: 'repeat',
      text: words.join(' '),
      variant: repeatStage === 'approval' ? 'destructive' : repeatStage === 'blocking' ? 'warn' : 'muted'
    })
  }
  const board = payload.kanban || {}
  if (exceeds(Number(board.rows_total) || 0, 0)) {
    const parts = [
      ['stateQueued', board.queued],
      ['stateRunning', board.running],
      ['stateBlocked', board.blocked]
    ]
      .filter(function (part) {
        return exceeds(Number(part[1]) || 0, 0)
      })
      .map(function (part) {
        return t(part[0], { count: Number(part[1]) })
      })
    chips.push({ key: 'board', text: parts.length ? t('chipBoard', { detail: parts.join(', ') }) : t('chipBoardIdle'), variant: 'muted' })
  }
  if (board.dispatcher_presence === 'not_observed') {
    chips.push({ key: 'dispatcher', text: t('chipDispatcher'), variant: 'warn' })
  }
  const activity = payload.activity || {}
  if (activity.live && activity.post_tool_call_observed) {
    chips.push({
      key: 'tools',
      text: t('chipTools', { count: Number(activity.open_call_count) || 0, elapsed: elapsedText(activity.oldest_open_elapsed_seconds) || '0s' }),
      variant: 'muted'
    })
  }
  const yolo = payload.yolo || {}
  if (yolo.status === 'observed' && yolo.enabled) {
    chips.push({ key: 'yolo', text: t('chipYolo'), variant: 'destructive' })
  }
  const shot = payload.parallel_shot || {}
  // No chip shows a number below 2: calls that never overlapped were no parallel shot (the TUI's `_shot_badge`).
  if (shot.status === 'observed') {
    const open = Number(shot.open_count) || 0
    const peak = Number(shot.peak_open_count) || 0
    if (exceeds(open, 1)) chips.push({ key: 'shot', text: t('chipShot', { count: open }), variant: 'muted' })
    else if (exceeds(peak, 1)) {
      const observedAt = shot.observed_at ? Date.parse(shot.observed_at) : NaN
      const age = Number.isFinite(observedAt) ? elapsedText(Math.max(0, (Date.now() - observedAt) / 1000)) : ''
      chips.push({ key: 'shot', text: age ? t('chipShotAgo', { count: peak, age }) : t('chipShot', { count: peak }), variant: 'muted' })
    }
  }
  return chips
}

// ---------------------------------------------------------------------------
// Catches: the moments OMH caught a model mistake in the reading session,
// oldest first, worded as the TUI's `_catch_sentence` words them. An entry
// that cannot be worded (an unknown kind, a missing number) is left out.
// ---------------------------------------------------------------------------

export const CATCH_EMOJI = { repeat_loop: '🔁', truncated_read: '📖', plan_continued: '📋', unarmed_wait: '⏰' }

function catchNumber(entry, name) {
  return Number.isInteger(entry[name]) ? entry[name] : 0
}

export function catchSentence(entry) {
  const kind = entry.kind
  const laps = catchNumber(entry, 'laps')
  const period = catchNumber(entry, 'period')
  if (kind === 'repeat_loop' && exceeds(laps, 0) && exceeds(period, 0)) {
    return period === 1 ? t('catchLoop', { laps }) : t('catchCycle', { period, laps })
  }
  if (kind === 'truncated_read' && exceeds(catchNumber(entry, 'offset'), 0)) {
    return t('catchReread', { offset: catchNumber(entry, 'offset') })
  }
  if (kind === 'plan_continued' && exceeds(catchNumber(entry, 'open_items'), 0)) {
    return t('catchPlan', { count: catchNumber(entry, 'open_items') })
  }
  if (kind === 'unarmed_wait') return t('catchWait')
  return ''
}

export function catchRows(payload) {
  const found = []
  for (const entry of rows(payload && payload.catches)) {
    const seq = entry.seq
    if (!Number.isInteger(seq) || exceeds(0, seq)) continue
    const kind = String(entry.kind)
    const emoji = own(CATCH_EMOJI, kind) ? CATCH_EMOJI[kind] : ''
    const text = emoji ? catchSentence(entry) : ''
    if (text) found.push({ seq, emoji, text })
  }
  return found
}

// ---------------------------------------------------------------------------
// Plan
// ---------------------------------------------------------------------------

// The TUI's plan window: `limit` items anchored one before the first
// unfinished item, so current work is always on screen.
export function planWindow(items, limit = PLAN_WINDOW_ROWS) {
  const total = items.length
  const firstRemaining = items.findIndex(function (item) {
    return item.state !== 'done'
  })
  const anchor = exceeds(0, firstRemaining) ? 0 : Math.max(0, firstRemaining - 1)
  const start = exceeds(total, limit) ? Math.min(anchor, total - limit) : 0
  const end = Math.min(total, start + limit)
  return { start, end, earlier: start, later: total - end }
}

// The items above the window fold to `✓ N done` when every one of them is
// done (the TUI's `_done_fold`), else to `… N earlier tasks`.
export function foldLabels(items, window) {
  const before = items.slice(0, window.start)
  const allDone = before.every(function (item) {
    return item.state === 'done'
  })
  return {
    earlier: window.earlier ? (allDone ? t('planFoldDone', { count: window.earlier }) : t('planFoldEarlier', { count: window.earlier })) : '',
    later: window.later ? t('planFoldLater', { count: window.later }) : ''
  }
}

function depthOf(item) {
  const depth = Number(item.depth)
  return Number.isInteger(depth) && exceeds(depth, 0) ? Math.min(depth, 3) : 0
}

// Consecutive items of one phase form a group; the phase is drawn once, on
// the group's first item. A subtask with no phase continues its parent's.
export function planGroups(items) {
  const groups = []
  for (const item of items) {
    const phase = safeText(item.phase)
    const last = groups[groups.length - 1]
    if (last && (last.phase === phase || (!phase && exceeds(depthOf(item), 0)))) last.items.push(item)
    else groups.push({ phase, items: [item] })
  }
  return groups
}

const REASON_CHARS = 48 // TODO_BLOCKED_REASON_DISPLAY_CHARS, runtime_reader.py
function reasonOf(item) {
  const reason = safeText(item.blocked_reason)
  return exceeds(reason.length, REASON_CHARS) ? `${reason.slice(0, REASON_CHARS - 1)}…` : reason
}

// The reader marks a skipped step as a closed item carrying a reason
// (`counts.skipped` counts exactly those): it was closed, not worked.
export function itemState(item) {
  if (item.state === 'done') return reasonOf(item) ? 'skipped' : 'done'
  return item.state === 'active' ? 'active' : 'pending'
}

const ITEM_GLYPHS = { done: '✓', skipped: '–', active: '●', pending: '○' }

export function itemGlyph(item) {
  return ITEM_GLYPHS[itemState(item)]
}

// The bar fills by the steps WORKED: `done` less the skipped ones, which
// are a subset of `done`, so a plan that skipped half its steps never reads
// as a full bar.
export function planProgress(todo) {
  const counts = (todo && todo.counts) || {}
  const total = Math.max(0, Number(counts.total) || 0)
  const worked = Math.max(0, (Number(counts.done) || 0) - (Number(counts.skipped) || 0))
  const percent = exceeds(total, 0) ? Math.min(100, Math.round((worked / total) * 100)) : 0
  return { worked, total, percent, allDone: !!todo && todo.status === 'all_done' }
}

// The header count, worded as the TUI's `_plan_header`: `done/total` while
// open, `✓ worked/total` once finished, each with its skipped clause.
export function planCountText(todo) {
  const counts = todo.counts || {}
  const progress = planProgress(todo)
  const skipped = Number(counts.skipped) || 0
  const clause = exceeds(skipped, 0) ? ` ${t('planSkipped', { count: skipped })}` : ''
  if (progress.allDone) return `✓ ${progress.worked}/${progress.total}${clause}`
  return `${Number(counts.done) || 0}/${progress.total}${clause}`
}

// A plan whose steps Hermes' own `todo_list` holds (`native_todo`, the
// reader's `source`; `NATIVE_TODO_SOURCE` in native_todo.py). Hermes Desktop
// already draws that list in the composer's status stack -- a live Todos
// group while the turn runs, and on origin/main a "previous todos" disclosure
// after it (apps/desktop/src/app/chat/composer/status-stack/index.tsx, at
// v2026.9.7 and origin/main). Drawing the same items in this pane was the
// second checklist, so the section keeps only what Hermes cannot show: the
// open items carrying a reason omh_todo recorded, and the reader's stall
// finding. With neither, there is no PLAN section at all, and the status
// item never counts that plan either.
export const NATIVE_TODO_SOURCE = 'todo_list'

function omhHeldPlan(todo) {
  return todo.status === 'established' && todo.source !== NATIVE_TODO_SOURCE
}

// ---------------------------------------------------------------------------
// Delegation graph: the conversation's delegated lanes, while the reader
// calls the graph active. Once every lane has settled the TUI draws the run
// as one line (`dag_run_summary`), and so does the pane.
// ---------------------------------------------------------------------------

const SETTLED_LANE_STATES = new Set(['done', 'failed', 'interrupted', 'unknown'])
const LANE_STATE_ORDER = ['running', 'stuck', 'failed', 'dispatched', 'waiting', 'interrupted', 'unknown', 'done']
const LANE_GLYPHS = { running: '●', stuck: '!', failed: '▲', dispatched: '○', waiting: '○', interrupted: '▲', unknown: '?', done: '✓' }

function lanesOf(graph) {
  return rows(graph.nodes).filter(function (node) {
    return node.kind !== 'root'
  })
}

export function dagRunSummary(graph) {
  const lanes = lanesOf(graph)
  const unsettled = lanes.some(function (node) {
    return !SETTLED_LANE_STATES.has(node.state)
  })
  if (!lanes.length || exceeds(Number(graph.hidden_nodes) || 0, 0) || graph.dag_open || unsettled) return ''
  const said = [
    t('dagDone', {
      done: countOf(lanes, function (node) {
        return node.state === 'done'
      }),
      total: lanes.length
    })
  ]
  for (const state of ['failed', 'interrupted', 'unknown']) {
    const count = countOf(lanes, function (node) {
      return node.state === state
    })
    if (count) said.push(t('dagStateCount', { count, state: stateWord(state) }))
  }
  // A dag-ulw node accepted while its handoff could not be read where its child wrote it (`dag_run.settle`).
  const unchecked = countOf(lanes, function (node) {
    return node.handoff_checked === false
  })
  if (unchecked) said.push(t('dagUnchecked', { count: unchecked }))
  return [t('sectionDag'), safeText(graph.name) || t('dagDefaultName')].concat(said).join(' · ')
}

// How deep a lane sits under main: the longest chain of lanes above it,
// capped at three steps of indent; a loop in the edges stops the walk.
function laneDepth(id, parents, roots, memo, seen) {
  if (memo.has(id)) return memo.get(id)
  let depth = 0
  for (const up of parents.get(id) || []) {
    if (roots.has(up) || seen.has(up)) continue
    depth = Math.max(depth, 1 + laneDepth(up, parents, roots, memo, new Set(seen).add(up)))
  }
  memo.set(id, Math.min(depth, 3))
  return memo.get(id)
}

export function laneMark(state) {
  return { glyph: own(LANE_GLYPHS, state) ? LANE_GLYPHS[state] : '○', tone: wordTone(state) }
}

export function delegationView(payload) {
  const graph = payload && payload.delegation_graph
  if (!graph || graph.status !== 'active') return null
  const lanes = lanesOf(graph)
  if (!lanes.length) return null
  const roots = new Set(
    rows(graph.nodes)
      .filter(function (node) {
        return node.kind === 'root'
      })
      .map(function (node) {
        return safeText(node.id)
      })
  )
  const parents = new Map()
  for (const edge of rows(graph.edges)) {
    const to = safeText(edge.to)
    parents.set(to, (parents.get(to) || []).concat([safeText(edge.from)]))
  }
  const memo = new Map()
  const settled = dagRunSummary(graph)
  const tally = LANE_STATE_ORDER.map(function (state) {
    return [
      state,
      countOf(lanes, function (node) {
        return node.state === state
      })
    ]
  })
    .filter(function (entry) {
      return entry[1]
    })
    .map(function (entry) {
      return t('dagStateCount', { count: entry[1], state: stateWord(entry[0]) })
    })
  return {
    summary: settled || [safeText(graph.name) || t('dagDefaultName')].concat(tally).join(' · '),
    settled: !!settled,
    lanes: lanes.slice(0, LANE_LIMIT).map(function (node) {
      const id = safeText(node.id)
      const model = safeText(node.model).split('/').pop()
      const state = humanState(node.state) || 'unknown'
      const mark = laneMark(state)
      return {
        title: safeText(node.title) || id,
        model: model === '?' ? '' : model,
        state: stateWord(state),
        depth: laneDepth(id, parents, roots, memo, new Set([id])),
        glyph: mark.glyph,
        tone: mark.tone
      }
    }),
    hidden: Math.max(0, lanes.length - LANE_LIMIT) + (Number(graph.hidden_nodes) || 0)
  }
}

// ---------------------------------------------------------------------------
// The drawing: the backend's `delegation_drawing`, the TUI's own boxes or
// tree as lines of `{text, role}` segments. The pane never lays a cell out
// again; it only colours each segment by the state its role carries, with
// the TUI's meaning (`panels.dag_style`): a box's border, glyph, title and
// status words in its node's state colour, edges and the frontier label as
// quiet marks, an edge into a running frontier in the accent.
// ---------------------------------------------------------------------------

const DRAWING_STATE_TONES = {
  root: 'accent',
  selected: 'accent',
  running: 'accent',
  stuck: 'warn',
  failed: 'error',
  interrupted: 'error',
  done: 'tertiary',
  dispatched: 'tertiary',
  waiting: 'muted',
  unknown: 'muted'
}
const DRAWING_KIND_TONES = {
  header: 'secondary',
  title: 'primary',
  category: 'tertiary',
  model: 'tertiary',
  group: 'tertiary',
  parents: 'tertiary',
  dependency: 'tertiary',
  more: 'tertiary',
  unknown: 'muted',
  frontier: 'mark',
  edge: 'mark'
}
const DRAWING_STATE_KINDS = new Set(['node', 'node-title', 'node-word', 'glyph', 'status'])

// The tone a drawing segment is painted in, from its renderer role
// (`node:running`, `edge`, `header`); a role the pane does not know is plain.
export function segmentTone(role) {
  const text = String(role || '')
  const colon = text.indexOf(':')
  const kind = colon === -1 ? text : text.slice(0, colon)
  const state = colon === -1 ? '' : text.slice(colon + 1)
  if (DRAWING_STATE_KINDS.has(kind)) {
    const tone = own(DRAWING_STATE_TONES, state) ? DRAWING_STATE_TONES[state] : 'muted'
    // A border is a mark: a settled or waiting box is drawn in the mark's grey, never the word's.
    return kind === 'node' && (tone === 'tertiary' || tone === 'muted') ? 'mark' : tone
  }
  if (kind === 'connector') return state === 'running' ? 'accent' : 'mark'
  return own(DRAWING_KIND_TONES, kind) ? DRAWING_KIND_TONES[kind] : ''
}

// The drawing's text keeps every box-drawing cell; only escapes and control
// characters are taken out, as `sanitizeText` takes them.
function drawingText(value) {
  return String(value ?? '')
    .replace(ESCAPE_SEQUENCE, '')
    .replace(/\p{Cc}/gu, '')
}

// The lines to show, or null where the backend sent no usable drawing (no
// `cols` asked, an error record, a payload from before the drawing).
export function drawingLines(payload) {
  const drawing = payload && payload.delegation_drawing
  if (!drawing || drawing.error || !Array.isArray(drawing.lines) || !drawing.lines.length) return null
  return drawing.lines.slice(0, DRAWING_LINE_LIMIT).map(function (line) {
    return rows(line)
      .slice(0, DRAWING_SEGMENT_LIMIT)
      .map(function (segment) {
        const role = safeText(segment.role)
        // The renderer's width for a segment holding a wide character: the pane holds it to that many cells.
        const cells = Number.isInteger(segment.cells) && exceeds(segment.cells, 0) ? Math.min(segment.cells, 4 * DRAWING_SEGMENT_LIMIT) : 0
        return { text: drawingText(segment.text), role, tone: segmentTone(role), title: role.startsWith('node-title') || role === 'title', cells }
      })
      .filter(function (segment) {
        return segment.text
      })
  })
}

// ---------------------------------------------------------------------------
// The DAG view. A dag-ulw run's graph (the one carrying `dag_topology`) is
// drawn as cards a pointer or a finger can open, in place of the backend's
// box drawing: a card per lane in the row of its layer, an edge per
// dependency, a strip of figures, the open lane's detail and the run's stats.
// Every figure is one the reader sent: tokens and cost are added up here, and
// the critical path and the bottlenecks are the backend's. Past DAG_CARD_LIMIT
// lanes the cards give way to the drawing, which has a tree for a big run;
// the figures and the stats stay.
// ---------------------------------------------------------------------------

export const DAG_CARD_LIMIT = 16

function positive(value) {
  return Number.isFinite(value) && exceeds(value, 0) ? value : 0
}

// What one lane counted, from its `usage` (its auxiliary calls included), output from `output_tokens` where the
// usage names none. `reported` is whether the input and cache counts were read at all; a cost Hermes recorded,
// a reported zero too, is `cost`.
export function laneUsage(record) {
  const usage = record && record.usage && typeof record.usage === 'object' ? record.usage : null
  const output = positive(usage && Number.isFinite(usage.output) ? usage.output : record && record.output_tokens)
  const cost = usage && Number.isFinite(usage.cost_usd) && reaches(usage.cost_usd, 0) ? usage.cost_usd : null
  return {
    seen: !!usage || exceeds(output, 0),
    reported: !!usage,
    input: usage ? positive(usage.input) : 0,
    read: usage ? positive(usage.cache_read) : 0,
    write: usage ? positive(usage.cache_write) : 0,
    output,
    cost,
    estimated: !!(usage && usage.cost_estimated)
  }
}

// Lanes' usage added up. `lanes` counts those that counted anything, `priced` those Hermes priced.
export function sumUsage(list) {
  const total = { lanes: 0, priced: 0, input: 0, read: 0, write: 0, output: 0, cost: null, estimated: false }
  list.forEach(function (usage) {
    if (!usage.seen) return
    total.lanes += 1
    total.input += usage.input
    total.read += usage.read
    total.write += usage.write
    total.output += usage.output
    if (usage.cost !== null) {
      total.cost = (total.cost || 0) + usage.cost
      total.priced += 1
      total.estimated = total.estimated || usage.estimated
    }
  })
  return total
}

// The prompt side: what the model was sent, whether or not the cache answered it.
export function promptTokens(usage) {
  return usage.input + usage.read + usage.write
}

export function allTokens(usage) {
  return promptTokens(usage) + usage.output
}

// Cache read over the prompt, or null where nothing was sent: no hit rate is not a zero one.
export function cacheHit(usage) {
  const prompt = promptTokens(usage)
  return exceeds(prompt, 0) ? usage.read / prompt : null
}

export function tokensText(count) {
  return exceeds(count, 0) ? tokenCountText(count) : '—'
}

export function percentText(ratio) {
  return ratio === null ? '—' : `${(ratio * 100).toFixed(1)}%`
}

// A recorded cost, a recorded zero as one; a dash where none was recorded.
export function costText(cost, estimated) {
  if (cost === null || !Number.isFinite(cost)) return '—'
  return exceeds(cost, 0) ? costSegmentText({ cost_usd: cost, cost_approximate: estimated }) : `$${(0).toFixed(4)}`
}

// Lanes' cost added up, marked `≥` while a lane that counted tokens has no cost: the priced lanes' floor, not the
// run's total. A dash where no lane was priced.
export function sumCostText(total) {
  const text = costText(total.cost, total.estimated)
  return total.cost !== null && exceeds(total.lanes, total.priced) ? `≥${text}` : text
}

// ---------------------------------------------------------------------------
// The usage board: this chat's own figures, apart from the DAG's. The host's
// stream and its context breakdown fill it; Hermes' recorded row (the HUD's
// `session_usage`) adds the cost and the cache counts the stream lacks; the
// wait for a first token is timed here, from the gateway events this window
// sees. A figure nothing reported is a dash, never a zero.
// ---------------------------------------------------------------------------

export const TTFT_KEEP = 10
const FIRST_TOKEN_EVENTS = ['message.delta', 'reasoning.delta', 'thinking.delta']
// What ends a turn on Hermes' stream, an interrupted or failed one included (`message.complete` carries its status).
const TURN_END_EVENTS = ['message.complete', 'error']
const PART_TONES = 8

export function newTurnClock() {
  return { started: Object.create(null), turns: Object.create(null) }
}

// Folds one gateway event into the clock: one pending start per chat. A turn
// starts at `message.start`; a start re-sent with the same `turn_id` keeps the
// first time, and any other start, one without a `turn_id` included (an older
// Hermes, or the bare start before a follow-up turn), replaces it. Its wait
// ends at the first streamed text of that turn; a turn's end, or an error,
// drops a start no text followed, so a dead turn never times the next one.
// True where a wait just ended.
export function noteTurnEvent(clock, type, sessionId, text, now, turnId) {
  if (!sessionId) return false
  if (TURN_END_EVENTS.includes(type)) {
    delete clock.started[sessionId]
    return false
  }
  if (!Number.isFinite(now)) return false
  const turn = typeof turnId === 'string' ? turnId : ''
  const pending = clock.started[sessionId]
  if (type === 'message.start') {
    if (!(pending && turn && pending.turn === turn)) clock.started[sessionId] = { at: now, turn }
    return false
  }
  if (!FIRST_TOKEN_EVENTS.includes(type) || !pending || typeof text !== 'string' || !text) return false
  if (pending.turn && turn && pending.turn !== turn) return false
  delete clock.started[sessionId]
  clock.turns[sessionId] = (clock.turns[sessionId] || []).concat([Math.max(0, now - pending.at)]).slice(-TTFT_KEEP)
  return true
}

const turnClock = newTurnClock()
const turnListeners = new Set()

export function latencyText(ms) {
  if (!Number.isFinite(ms) || exceeds(0, ms)) return ''
  return exceeds(1000, ms) ? `${Math.round(ms)}ms` : `${(ms / 1000).toFixed(1)}s`
}

export function speedText(tps) {
  return exceeds(tps, 0) ? `${tps.toFixed(exceeds(10, tps) ? 1 : 0)} t/s` : '—'
}

// `live` is the host's streamed usage of the focused chat, `saved` the chat's
// recorded row as the reader sent it, `stored` the focused chat's stored id,
// `breakdown` the host's context breakdown and `turns` the first-token waits
// (ms) this window timed. Recorded counts win where there are any (they are
// exact and carry the cache split); the stream stands in before the first row
// is written. The row counts only for the chat it was read for: across a chat
// switch the last poll's answer stays on screen until the next lands, and a
// failed read (`error`) is no row. Null where nothing is known.
export function usageBoard(input) {
  const live = input.live && typeof input.live === 'object' ? input.live : {}
  const sent = input.saved && typeof input.saved === 'object' ? input.saved : null
  const saved = sent && !sent.error && !!input.stored && sent.session_id === input.stored ? sent : {}
  const crumbs = input.breakdown && typeof input.breakdown === 'object' ? input.breakdown : {}
  const turns = Array.isArray(input.turns) ? input.turns : []
  const recorded = {
    input: positive(saved.input),
    read: positive(saved.cache_read),
    write: positive(saved.cache_write),
    output: positive(saved.output)
  }
  const hasRecord = exceeds(allTokens(recorded), 0)
  const prompt = hasRecord ? promptTokens(recorded) : positive(live.prompt) || positive(live.input)
  const output = hasRecord ? recorded.output : positive(live.output)
  const hit = hasRecord ? cacheHit(recorded) : Number.isFinite(live.cache_hit_pct) ? live.cache_hit_pct / 100 : null
  // The stream may carry a cost, but does not say whether Hermes priced it, so it keeps the approximate mark.
  const recordedCost = Number.isFinite(saved.cost_usd)
  const streamedCost = !recordedCost && exceeds(positive(live.cost_usd), 0)
  const cost = recordedCost ? saved.cost_usd : streamedCost ? live.cost_usd : null
  const counted = prompt + output
  const used = positive(live.context_used) || positive(crumbs.context_used)
  const max = positive(live.context_max) || positive(crumbs.context_max)
  const guess = positive(live.context_used) ? live.context_estimated === true : crumbs.context_estimated === true
  const percent = exceeds(max, 0) && exceeds(used, 0) ? Math.min(100, Math.round((used / max) * 100)) : null
  const tps = positive(live.avg_tps)
  const latency = positive(live.avg_latency_s)
  const last = turns.length ? turns[turns.length - 1] : null
  const mean = turns.length
    ? turns.reduce(function (total, ms) {
        return total + ms
      }, 0) / turns.length
    : 0
  const listed = (Array.isArray(crumbs.categories) ? crumbs.categories : []).filter(function (entry) {
    return entry && exceeds(positive(entry.tokens), 0)
  })
  const sum = listed.reduce(function (total, entry) {
    return total + entry.tokens
  }, 0)
  const parts = listed.map(function (entry, index) {
    return { id: String(entry.id || index), label: String(entry.label || entry.id || ''), tokens: entry.tokens, share: entry.tokens / sum }
  })
  if (!(exceeds(counted, 0) || exceeds(used, 0) || parts.length || turns.length || exceeds(tps, 0))) return null
  const marked = guess ? '~' : ''
  return {
    model: String(live.model || saved.model || crumbs.model || ''),
    calls: positive(live.calls),
    sum,
    parts,
    cells: [
      {
        label: t('dgTokens'),
        value: tokensText(counted),
        sub: exceeds(counted, 0) ? t('dgTokensSub', { out: tokenCountText(output), prompt: tokenCountText(prompt) }) : '',
        tip: t('ubTokensTip')
      },
      {
        label: t('dgCacheHit'),
        value: percentText(hit),
        sub: hasRecord && exceeds(prompt, 0) ? t('dgCacheHitSub', { read: tokenCountText(recorded.read), prompt: tokenCountText(prompt) }) : '',
        tip: t('ubCacheTip'),
        ring: hasRecord && exceeds(prompt, 0) ? recorded : null
      },
      {
        label: t('dgCost'),
        value: costText(cost, streamedCost || saved.cost_estimated === true),
        sub: cost === null ? (exceeds(counted, 0) ? t('dgUnpriced') : t('dgCostNone')) : '',
        tip: t('ubCostTip')
      },
      {
        label: t('ubContext'),
        value: percent === null ? (exceeds(used, 0) ? `${marked}${tokenCountText(used)}` : '—') : `${marked}${percent}%`,
        sub: percent === null ? '' : t('ubContextSub', { used: tokenCountText(used), max: tokenCountText(max) }),
        tip: t('ubContextTip')
      },
      {
        label: t('ubSpeed'),
        value: speedText(tps),
        sub: exceeds(latency, 0) ? t('ubSpeedSub', { latency: latencyText(latency * 1000) }) : '',
        tip: t('ubSpeedTip')
      },
      {
        label: t('ubTtft'),
        value: last === null ? '—' : latencyText(last),
        sub: exceeds(turns.length, 1) ? t('ubTtftAvg', { avg: latencyText(mean), count: turns.length }) : t('ubTtftSub'),
        tip: t('ubTtftTip')
      }
    ]
  }
}

// How many layers sit above a lane: the longest chain of lanes it waits on. A loop in the edges stops the walk.
function dagLayer(id, parents, memo, trail) {
  if (memo.has(id)) return memo.get(id)
  let depth = 0
  for (const up of parents.get(id) || []) {
    if (trail.has(up)) continue
    depth = Math.max(depth, 1 + dagLayer(up, parents, memo, new Set(trail).add(up)))
  }
  memo.set(id, depth)
  return depth
}

// Every lane below this one, however far down.
function below(id, children) {
  const seen = new Set()
  const walk = function (at) {
    for (const next of children.get(at) || []) {
      if (seen.has(next)) continue
      seen.add(next)
      walk(next)
    }
  }
  walk(id)
  return seen
}

// The lane ids a list of titles names (the backend names a topology's lanes by title); a title two lanes share goes
// to the first lane, then the next.
function idsForTitles(lanes, titles) {
  const used = new Map()
  return titles
    .map(function (title) {
      const key = safeText(title)
      const taken = used.get(key) || 0
      used.set(key, taken + 1)
      const same = lanes.filter(function (lane) {
        return lane.title === key
      })
      return same[taken] ? same[taken].id : ''
    })
    .filter(Boolean)
}

// The model of a DAG or verified fanout graph. Native/team graphs keep their drawing;
// fanout has no backend critical-path record, so its path and bottlenecks stay empty.
export function dagModel(graph) {
  const fanout = !!graph && graph.source === 'fanout'
  const topology = graph && graph.dag_topology
  if (!graph || graph.status !== 'active' || (!fanout && (!topology || typeof topology !== 'object'))) return null
  const records = lanesOf(graph)
  if (!records.length) return null
  const ids = new Set(
    records.map(function (record) {
      return safeText(record.id)
    })
  )
  const edges = []
  const taken = new Set()
  const parents = new Map()
  const children = new Map()
  for (const edge of rows(graph.edges)) {
    const from = safeText(edge.from)
    const to = safeText(edge.to)
    const key = `${from}|${to}`
    if (!ids.has(from) || !ids.has(to) || from === to || taken.has(key)) continue
    taken.add(key)
    edges.push({ from, to })
    parents.set(to, (parents.get(to) || []).concat([from]))
    children.set(from, (children.get(from) || []).concat([to]))
  }
  const memo = new Map()
  const lanes = records.map(function (record) {
    const id = safeText(record.id)
    const state = humanState(record.state) || 'unknown'
    const model = safeText(record.model).split('/').pop()
    const category = safeText(record.category)
    const origin = safeText(record.dag_origin).split(':')[0]
    return {
      id,
      title: safeText(record.title) || id,
      state,
      glyph: laneMark(state).glyph,
      word: stateWord(state),
      status: safeText(record.status),
      tone: segmentTone(`status:${state}`),
      border: segmentTone(`node:${state}`),
      category: category === '?' ? '' : category,
      model: model === '?' ? '' : model,
      effort: safeText(record.effort),
      role: safeText(record.role),
      origin: origin === 'repair' || origin === 'extend' ? origin : '',
      waits: Number.isInteger(record.waits_on) ? record.waits_on : 0,
      elapsed: Number.isFinite(record.elapsed_seconds) ? record.elapsed_seconds : null,
      session: safeText(record.session_tail),
      summary: longText(record.summary),
      unchecked: record.handoff_checked === false,
      usage: laneUsage(record),
      layer: dagLayer(id, parents, memo, new Set([id])),
      parents: parents.get(id) || [],
      children: children.get(id) || [],
      blocks: below(id, children).size
    }
  })
  const index = {}
  lanes.forEach(function (lane) {
    index[lane.id] = lane
  })
  const depth = lanes.reduce(function (most, lane) {
    return Math.max(most, lane.layer)
  }, 0)
  const layers = []
  for (let at = 0; reaches(depth, at); at += 1) {
    layers.push(
      lanes
        .filter(function (lane) {
          return lane.layer === at
        })
        .map(function (lane) {
          return lane.id
        })
    )
  }
  const byModel = new Map()
  lanes.forEach(function (lane) {
    if (lane.model) byModel.set(lane.model, (byModel.get(lane.model) || []).concat([lane]))
  })
  const models = Array.from(byModel, function (entry) {
    return {
      model: entry[0],
      count: entry[1].length,
      total: sumUsage(
        entry[1].map(function (lane) {
          return lane.usage
        })
      )
    }
  }).sort(function (a, b) {
    return allTokens(b.total) - allTokens(a.total)
  })
  const bottlenecks = []
  rows(topology && topology.bottlenecks).forEach(function (row) {
    const id = idsForTitles(lanes, [row[0]])[0]
    if (id) bottlenecks.push({ id, blocks: Number(row[1]) || 0 })
  })
  return {
    name: safeText(graph.name),
    lanes,
    index,
    layers,
    edges,
    models,
    bottlenecks,
    path: idsForTitles(lanes, topology && Array.isArray(topology.critical_path) ? topology.critical_path : []),
    total: sumUsage(
      lanes.map(function (lane) {
        return lane.usage
      })
    ),
    seconds: lanes.reduce(function (sum, lane) {
      return sum + (lane.elapsed || 0)
    }, 0),
    timed: countOf(lanes, function (lane) {
      return lane.elapsed !== null
    }),
    hidden: Number(graph.hidden_nodes) || 0,
    cards: !exceeds(lanes.length, DAG_CARD_LIMIT)
  }
}

// What the card line under a lane's route says: a waiting lane the lanes it waits on, any other its state, time and output.
export function laneStatus(lane) {
  if (lane.state === 'waiting' && exceeds(lane.waits, 0)) return `${lane.glyph} ${t('dgWaitsOn', { count: lane.waits })}`
  const time = lane.elapsed === null ? '' : ` ${elapsedText(lane.elapsed)}`
  const output = exceeds(lane.usage.output, 0) ? ` · ↓${tokensText(lane.usage.output)}` : ''
  return `${lane.glyph} ${lane.word}${time}${output}`
}

// The lane ids a highlight keeps lit: a model's lanes, or the critical path; null where nothing is highlighted.
export function markedLanes(dag, mark) {
  if (!mark) return null
  if (mark.kind === 'path') return dag.path
  return dag.lanes
    .filter(function (lane) {
      return lane.model === mark.value
    })
    .map(function (lane) {
      return lane.id
    })
}

// ---------------------------------------------------------------------------
// What the pane and the status item render from one poll: the payload when
// the reader answered, otherwise the one state the surface must say. A
// transport failure keeps the last payload on screen under a quiet notice.
// ---------------------------------------------------------------------------

function errorText(error) {
  return error.message || String(error)
}

export function paneModel({ gateway, data, error }) {
  if (gateway !== 'open') {
    return { payload: null, status: t('stateGateway', { state: gatewayWord(gateway) }), notice: '', loading: false }
  }
  if (data && data.error) {
    return { payload: null, status: t('stateReaderError'), notice: t('noticeBackend', { message: data.error }), loading: false }
  }
  if (error) {
    return { payload: data || null, status: data ? '' : t('stateUnavailable'), notice: t('noticeBackend', { message: errorText(error) }), loading: false }
  }
  if (!data) {
    return { payload: null, status: '', notice: '', loading: true }
  }
  return { payload: data, status: '', notice: '', loading: false }
}

export function paneVersion(payload) {
  const version = safeText(payload.version)
  if (version && version !== 'unknown') return version
  const bundle = payload.plugin && safeText(payload.plugin.version)
  return bundle && bundle !== 'unknown' ? bundle : 'dev'
}

// At most two self-describing segments after the `OMH` brand: what runs,
// what is blocked, then an OMH-held plan's `plan d/t`; `idle` (or the
// header's phrase) when none applies. A plan Hermes' todo_list holds is
// never counted here: Desktop's composer already counts it.
export function statusSegments(payload) {
  const segments = countSegments(tallyCounts(agentTally(payload)))
  const todo = payload.todo || {}
  if (omhHeldPlan(todo)) {
    const counts = todo.counts || {}
    segments.push({ text: t('statusPlan', { done: Number(counts.done) || 0, total: Number(counts.total) || 0 }), tone: 'tertiary' })
  }
  if (!segments.length) segments.push({ text: stateSummary(payload), tone: stateTone(payload) === 'accent' ? 'accent' : 'muted' })
  return segments.slice(0, 2)
}

function statusDetail(payload) {
  const tally = agentTally(payload)
  const counts = [
    tally.running ? t('stateRunning', { count: tally.running }) : '',
    tally.failed ? t('stateFailed', { count: tally.failed }) : '',
    tally.blocked ? t('stateBlocked', { count: tally.blocked }) : '',
    tally.done ? t('stateDone', { count: tally.done }) : ''
  ].filter(Boolean)
  const parts = [`${t('brand')} ${paneVersion(payload)}`, counts.length ? counts.join(' · ') : stateSummary(payload)]
  const todo = payload.todo || {}
  const title = safeText(todo.title) || t('untitled')
  const planCounts = todo.counts || {}
  if (todo.source === NATIVE_TODO_SOURCE && (todo.status === 'established' || todo.status === 'all_done')) {
    parts.push(t('detailPlanNative'))
  } else if (todo.status === 'established') {
    parts.push(t('detailPlan', { title, done: Number(planCounts.done) || 0, total: Number(planCounts.total) || 0 }))
  } else if (todo.status === 'all_done') {
    parts.push(t('detailPlanFinished', { title }))
  }
  return parts.join(' · ')
}

// The status-bar item: the brand and its segments; the detail rides the
// tooltip. Nothing at all while the reader has not answered and nothing
// failed, the way the Kanban count stays out of the bar when idle.
export function statusItem({ gateway, data, error }) {
  if (gateway !== 'open') return null
  if (data && data.error) {
    return { segments: [{ text: t('stateReaderError'), tone: 'muted' }], detail: t('noticeBackend', { message: data.error }) }
  }
  if (!data) {
    return error ? { segments: [{ text: t('stateUnavailable'), tone: 'muted' }], detail: t('noticeBackend', { message: errorText(error) }) } : null
  }
  return { segments: statusSegments(data), detail: statusDetail(data) }
}

// ---------------------------------------------------------------------------
// Rows: ROUTES and the fanout DAG.
// ---------------------------------------------------------------------------

// An absolute path in an action title spends the whole line on directories
// nobody reads; the title keeps the path's last two segments behind `…/`,
// and the tooltip keeps the full sentence.
export function collapsePaths(text) {
  return String(text)
    .split(' ')
    .map(function (token) {
      if (!token.startsWith('/') || exceeds(25, token.length)) return token
      const segments = token.split('/').filter(Boolean)
      return exceeds(segments.length, 1) ? `…/${segments.slice(-2).join('/')}` : token
    })
    .join(' ')
}

// The figures a row draws -- state, elapsed -- and the ones it keeps for the
// tooltip (tokens, cost, fallback, rate, cache, ctx, turn), from the same
// row fields the TUI reads. A board row shows the board's own status word,
// coloured by that word rather than by the row's verdict.
export function rowFigures(row, extraSeconds) {
  const board = safeText(row.lane_backend) === 'kanban'
  const verdict = safeText(row.state) || 'running'
  const state = humanState(board ? safeText(row.native_status) || verdict : verdict)
  const running = isRunningRow(row)
  const elapsedSeconds = running ? (row.elapsed_seconds || 0) + extraSeconds : row.elapsed_seconds
  const elapsed = verdict === 'queued' ? '' : elapsedText(elapsedSeconds) || '0s'
  const tokens = tokenCountText(row.tokens)
  const extras = []
  if (Number.isFinite(row.fallback_count) && exceeds(row.fallback_count, 0)) extras.push(t('rowFallback', { count: row.fallback_count }))
  if (Number.isFinite(row.tokens_per_second)) extras.push(t('rowTokensPerSecond', { count: Math.round(row.tokens_per_second) }))
  if (Number.isFinite(row.cache_hit_percentage)) extras.push(t('rowCache', { percent: row.cache_hit_percentage }))
  if (Number.isFinite(row.context_percentage)) extras.push(t('rowContext', { percent: row.context_percentage }))
  const turn = Number.isFinite(row.turn_count) ? t('rowTurn', { count: row.turn_count }) : ''
  const tools = Number.isFinite(row.tool_count) ? t('rowTools', { count: row.tool_count }) : ''
  const turnTools = turn && tools ? t('rowTurnTools', { turn, tools }) : turn || tools
  if (turnTools) extras.push(turnTools)
  return { state: stateWord(state), stateTone: wordTone(state), elapsed, tokens: tokens ? t('rowTokens', { count: tokens }) : '', cost: costSegmentText(row), extras }
}

// The row's glyph follows its verdict: a spinner in the accent while it
// runs, yellow when blocked or stale, red when failed, grey when done.
export function rowMark(row) {
  const state = safeText(row.state) || 'running'
  if (state === 'failed') return { glyph: '▲', tone: 'error', spinning: false }
  if (state === 'blocked') return { glyph: '▲', tone: 'warn', spinning: false }
  if (state === 'stale') return { glyph: '!', tone: 'warn', spinning: false }
  if (state === 'done') return { glyph: '✓', tone: 'muted', spinning: false }
  if (state === 'queued') return { glyph: '·', tone: 'muted', spinning: false }
  return { glyph: '', tone: 'accent', spinning: true }
}

const GRAPH_SUCCESS = new Set(['completed', 'already_completed', 'dry_run_planned'])
const GRAPH_FAILED = new Set([
  'capability_snapshot_invalid',
  'modality_unknown',
  'modality_unsupported',
  'modality_transformation_unobserved',
  'failed',
  'executor_not_ready',
  'unsupported_for_local_dispatch',
  'worktree_failed',
  'not_selected',
  'interrupted',
  'model_choice_required'
])

export function graphNodeView(nodeRecord) {
  const blockedBy = Array.isArray(nodeRecord.blocked_by) ? nodeRecord.blocked_by.map(safeText).filter(Boolean) : []
  const dispatchState = safeText(nodeRecord.state) || 'unknown'
  const stuckState = safeText(nodeRecord.unit_state)
  const state = stuckState || dispatchState
  const stallSeconds = Number(nodeRecord.stalled_for_seconds) || 0
  const stuckReason = stuckState
    ? [reasonWord(nodeRecord.state_reason), exceeds(stallSeconds, 0) ? t('graphSinceOutput', { age: elapsedText(stallSeconds) }) : ''].filter(Boolean).join(', ')
    : ''
  const waitingOn = blockedBy.length ? t('graphWaitingOn', { nodes: blockedBy.join(' + ') }) : ''
  // A node held by its dependencies says only what it waits on.
  const word = state === 'blocked_by_dependency' && waitingOn ? '' : stateWord(state)
  const detail = [`${word}${stuckReason ? ` (${stuckReason})` : ''}`, waitingOn].filter(Boolean).join(' · ')
  // Held, not failed: yellow, like every other wait in the pane.
  const waiting = state === 'blocked_by_dependency' || state === 'blocked'
  const marker = stuckState ? '!' : nodeRecord.in_frontier ? '●' : waiting ? '○' : GRAPH_FAILED.has(state) ? '▲' : GRAPH_SUCCESS.has(state) ? '✓' : '○'
  const tone = stuckState || waiting ? 'warn' : nodeRecord.in_frontier ? 'accent' : marker === '▲' ? 'error' : marker === '✓' ? 'muted' : 'tertiary'
  const id = safeText(nodeRecord.node_id)
  return { marker, tone, id, detail, text: `${id} · ${detail}` }
}

// ---------------------------------------------------------------------------
// Styles. Prefixed classes only; tokens, not literals. Mono cells name the
// app's bundled 'JetBrains Mono' first (styles.css @font-face), then the
// theme's mono stack, and are kept for ids, model and route names, figures
// and the drawing. One compact layout serves every pane width: a row's long
// cell truncates with an ellipsis (its tooltip holds the whole text) and a
// state word keeps its own fixed cell, so nothing wraps onto a line by
// itself. The TUI's look arrives as three mixed tokens: `--omh-edge`, a
// muted violet for frames and rules; `--omh-brand`, a rose for the brand;
// `--omh-label`, a warm tone for section labels. Each is mixed from
// Desktop's own colour tokens, so a theme change carries them. Marks in the
// drawing take one opaque grey, `--omh-mark`: a translucent one doubles where
// two box-drawing cells meet and a border reads dotted.
// ---------------------------------------------------------------------------

const MONO = "'JetBrains Mono',var(--font-mono,var(--dt-font-mono,monospace))"

export const PANE_CSS = `
.omh-pane{display:flex;flex-direction:column;height:100%;min-width:0;container-type:inline-size;font-family:var(--font-sans,var(--dt-font-sans,sans-serif));font-size:12px;line-height:1.4;color:var(--ui-text-primary)}
.omh-pane,.omh-bar{--omh-text-readable:color-mix(in srgb,var(--ui-text-secondary),var(--ui-text-tertiary));--omh-warn:color-mix(in srgb,var(--ui-yellow) 72%,var(--ui-text-primary));--omh-edge:color-mix(in srgb,var(--ui-purple) 55%,var(--background));--omh-brand:color-mix(in srgb,color-mix(in srgb,var(--ui-red) 60%,var(--ui-purple)) 85%,var(--ui-text-primary));--omh-label:color-mix(in srgb,var(--ui-orange) 65%,var(--ui-text-primary));--omh-mark:color-mix(in srgb,var(--ui-base) 50%,var(--background))}
.omh-pane-mono{font-family:${MONO};font-variant-numeric:tabular-nums}
.omh-pane-head{display:flex;align-items:center;gap:8px;padding:12px 12px 0;min-width:0}
.omh-pane-brand{font-weight:700;letter-spacing:.02em;white-space:nowrap;color:var(--omh-brand)}
.omh-pane-state{display:flex;align-items:center;gap:5px;min-width:0;margin-left:auto;font-size:11px;color:var(--omh-text-readable);white-space:nowrap}
.omh-pane-state-text{min-width:0;overflow:hidden;text-overflow:ellipsis}
.omh-pane-state-seg+.omh-pane-state-seg::before{content:'·';margin:0 3px;color:var(--ui-text-quaternary)}
.omh-pane-scope{padding:2px 12px 8px;font-size:11px;color:var(--omh-text-readable)}
.omh-pane-chips{display:flex;flex-wrap:wrap;gap:4px;padding:0 12px 10px}
.omh-pane-rule{flex:none;border-top:1px solid var(--omh-edge)}
.omh-pane-body{min-height:0;flex:1;overflow-y:auto;overscroll-behavior:contain;padding-bottom:12px}
.omh-pane-section{display:flex;align-items:baseline;gap:8px;padding:16px 12px 6px;min-width:0;max-width:640px;box-sizing:border-box}
.omh-pane-section-label{font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;color:var(--omh-label);white-space:nowrap}
.omh-pane-section-title{min-width:0;flex:1;color:var(--ui-text-secondary);overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
.omh-pane-section-count{margin-left:auto;font-size:11px;color:var(--omh-text-readable);white-space:nowrap}
.omh-pane-block{padding:0 12px;min-width:0;max-width:640px;box-sizing:border-box}
.omh-pane-bar{height:2px;margin:2px 0 6px;border-radius:1px;background:var(--ui-stroke-tertiary);overflow:hidden}
.omh-pane-bar-fill{height:100%;background:var(--ui-accent)}
.omh-pane-bar-fill[data-done=true]{background:var(--omh-mark)}
.omh-pane-phase{display:flex;align-items:baseline;gap:8px;margin-top:8px;font-weight:600;color:var(--omh-text-readable);min-width:0}
.omh-pane-phase[data-current=true]{color:var(--ui-text-primary)}
.omh-pane-phase-name{min-width:0;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
.omh-pane-phase-count{margin-left:auto;font-size:11px;font-weight:400;color:var(--omh-text-readable)}
.omh-pane-phase-items{margin:2px 0 0 6px;padding-left:8px;border-left:1px solid var(--omh-edge)}
.omh-pane-plan-items{margin-top:2px}
.omh-pane-item{display:grid;grid-template-columns:14px minmax(0,1fr);gap:0 4px;align-items:baseline;min-width:0;padding:1px 0}
.omh-pane-item-glyph{text-align:center;color:var(--omh-text-readable)}
.omh-pane-item-text{min-width:0;overflow-wrap:anywhere}
.omh-pane-item-label{color:var(--ui-text-primary)}
.omh-pane-item[data-state=done] .omh-pane-item-label{color:var(--omh-text-readable);text-decoration:line-through}
.omh-pane-item[data-state=skipped] .omh-pane-item-label{color:var(--omh-text-readable)}
.omh-pane-item[data-state=active] .omh-pane-item-label{font-weight:600}
.omh-pane-item-note{display:block;margin-top:1px;font-size:11px;color:var(--omh-text-readable);overflow-wrap:anywhere}
.omh-pane-fold{padding:1px 0 1px 18px;font-size:11px;color:var(--omh-text-readable)}
.omh-pane-catch{display:grid;grid-template-columns:20px minmax(0,1fr);gap:0 4px;align-items:baseline;padding:1px 0;color:var(--ui-text-secondary)}
.omh-pane-catch-text{min-width:0;overflow-wrap:anywhere}
.omh-pane-summary{display:block;padding:10px 0 0;color:var(--omh-text-readable);overflow-wrap:anywhere}
.omh-pane-run{padding:0 0 3px;color:var(--ui-text-secondary);overflow-wrap:anywhere}
.omh-pane-dag-card{margin:2px 0 4px;padding:10px;border:1px solid var(--omh-edge);border-radius:var(--radius-md,6px);background:var(--ui-bg-card)}
.omh-pane-dag{margin:0;font-family:${MONO};font-size:11px;line-height:1.2;white-space:pre;overflow-x:auto;overflow-y:hidden;color:var(--ui-text-primary)}
.omh-pane-dag-line{display:block;min-height:1.2em}
.omh-pane-dag-title{font-weight:700}
.omh-pane-dag-wide{display:inline-block;overflow:hidden;vertical-align:top}
.omh-pane-dag-probe{position:absolute;visibility:hidden;white-space:pre;font-family:${MONO};font-size:11px}
.omh-pane-lane{display:grid;grid-template-columns:14px minmax(0,1fr) auto 64px;gap:0 6px;align-items:baseline;min-width:0;padding:1px 0}
.omh-pane-lane-glyph{text-align:center}
.omh-pane-lane-title{min-width:0;padding-left:var(--omh-lane-indent,0);overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
.omh-pane-lane-model{max-width:96px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;font-size:11px;color:var(--omh-text-readable)}
.omh-pane-lane-state{overflow:hidden;white-space:nowrap;text-overflow:ellipsis;font-size:11px;text-align:right}
@container (max-width: 420px){.omh-pane-lane{grid-template-columns:14px minmax(0,1fr) 64px}.omh-pane-lane-glyph{grid-row:1}.omh-pane-lane-title{grid-column:2;grid-row:1}.omh-pane-lane-state{grid-column:3;grid-row:1}.omh-pane-lane-model{grid-column:2/-1;grid-row:2;max-width:none;padding-left:var(--omh-lane-indent,0)}}
.omh-pane-more{padding:2px 0 0 20px;font-size:11px;color:var(--omh-text-readable)}
.omh-agent{display:grid;grid-template-columns:14px minmax(0,1fr) auto;gap:2px 6px;align-items:baseline;min-width:0;margin:0 -6px;padding:5px 6px;border-radius:var(--radius-sm,4px);transition:background-color .15s}
.omh-agent:hover{background:var(--chrome-action-hover)}
.omh-agent-glyph{text-align:center}
.omh-agent-title{min-width:0;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;color:var(--ui-text-primary)}
.omh-agent-id{font-size:11px;color:var(--omh-text-readable);white-space:nowrap}
.omh-agent-sub{grid-column:2/-1;display:grid;grid-template-columns:minmax(0,1fr) 64px 52px;gap:0 6px;align-items:baseline;min-width:0;font-size:11px;color:var(--omh-text-readable)}
.omh-agent-route{min-width:0;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
.omh-agent-state{overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
.omh-agent-figure{white-space:nowrap;text-align:right}
.omh-pane-graph{display:grid;gap:1px;padding:0 12px;font-size:11px;min-width:0;max-width:640px;box-sizing:border-box}
.omh-pane-graph-node{display:grid;grid-template-columns:14px auto minmax(0,1fr);gap:0 6px;align-items:baseline;min-width:0}
.omh-pane-graph-glyph{text-align:center}
.omh-pane-graph-detail{min-width:0;overflow-wrap:anywhere;color:var(--omh-text-readable)}
.omh-pane-notice{margin:6px 12px 8px;border-radius:6px;background:var(--chrome-action-hover);padding:6px 8px;font-size:11px;color:var(--omh-text-readable);overflow-wrap:anywhere}
.omh-pane-skeleton{height:10px;margin:6px 12px}
.omh-pane-dv{min-width:0}
.omh-pane-dv-kpis{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px;margin:6px 0 12px}
@container (min-width:520px){.omh-pane-dv-kpis{grid-template-columns:repeat(4,minmax(0,1fr))}.omh-pane-dv-facts{grid-template-columns:repeat(5,minmax(0,1fr))}}
.omh-pane-dv-kpi{position:relative;display:flex;flex-direction:column;gap:1px;min-width:0;padding:7px 9px;background:var(--ui-bg-card);border:1px solid var(--ui-stroke-tertiary);border-radius:var(--radius-sm,2px);cursor:help}
.omh-pane-dv-kpi-label{font-size:10px;text-transform:uppercase;letter-spacing:.06em;color:var(--omh-text-readable)}
.omh-pane-dv-kpi-value{font-family:${MONO};font-size:15px;font-weight:600;line-height:1.25;color:var(--ui-text-primary);font-variant-numeric:tabular-nums}
.omh-pane-dv-kpi-sub{font-family:${MONO};font-size:10.5px;line-height:1.3;color:var(--omh-text-readable);overflow-wrap:anywhere;text-wrap:balance}
.omh-pane-dv-kpi-ring{position:absolute;right:8px;top:8px;display:flex}
.omh-pane-dv-canvas{position:relative;padding:4px 18px 4px 0}
.omh-pane-dv-edges{position:absolute;left:0;top:0;z-index:0;overflow:visible;pointer-events:none}
.omh-pane-dv-row{position:relative;z-index:1;display:flex;flex-wrap:wrap;justify-content:center;gap:12px;margin-bottom:34px}
.omh-pane-dv-row:last-child{margin-bottom:0}
.omh-pane-dv-card{--dv-c:var(--omh-mark);box-sizing:border-box;flex:1 1 0;min-width:118px;max-width:300px;display:flex;flex-direction:column;gap:2px;margin:0;padding:7px 9px 8px;text-align:left;background:var(--ui-bg-card);border:1px solid var(--dv-c);border-radius:var(--radius-sm,2px);color:inherit;font:inherit;cursor:pointer;overflow:hidden;transition:opacity .15s,border-color .15s,background-color .15s}
.omh-pane-dv-card:hover{background:color-mix(in srgb,var(--ui-bg-card),var(--ui-text-primary) 6%)}
.omh-pane-dv-card:focus-visible{outline:2px solid var(--omh-brand);outline-offset:1px}
.omh-pane-dv-card[data-tone=accent]{--dv-c:var(--ui-accent)}
.omh-pane-dv-card[data-tone=warn]{--dv-c:var(--omh-warn)}
.omh-pane-dv-card[data-tone=error]{--dv-c:var(--ui-red)}
.omh-pane-dv-picked{border-color:var(--omh-brand);outline:1px solid var(--omh-brand)}
.omh-pane-dv-dim{opacity:.32}
.omh-pane-dv-title{font-size:12px;font-weight:600;line-height:1.3;color:var(--ui-text-primary);display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;overflow-wrap:anywhere}
.omh-pane-dv-line{font-family:${MONO};font-size:10.5px;line-height:1.35;color:var(--omh-text-readable);overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
.omh-pane-dv-wrap{white-space:normal;overflow:visible;overflow-wrap:anywhere;text-overflow:clip}
.omh-pane-dv-cr{--dv-k:var(--omh-brand)}
.omh-pane-dv-in{--dv-k:var(--omh-label)}
.omh-pane-dv-cw{--dv-k:var(--ui-purple)}
.omh-pane-dv-out{--dv-k:var(--omh-text-readable)}
.omh-pane-dv-stack{display:flex;height:3px;margin-top:4px;border-radius:1px;background:var(--ui-stroke-tertiary);overflow:hidden}
.omh-pane-dv-big{height:6px;margin:6px 0 8px;border-radius:2px}
.omh-pane-dv-stack i{display:block;height:100%;min-width:0;background:var(--dv-k)}
.omh-pane-dv-ring{display:block}
.omh-pane-dv-track{fill:none;stroke:var(--ui-stroke-tertiary)}
.omh-pane-dv-arc{fill:none;stroke:var(--dv-k)}
.omh-pane-dv-edge,.omh-pane-dv-tip{--dv-e:var(--omh-mark);stroke:var(--dv-e);stroke-width:1.2}
.omh-pane-dv-edge{fill:none}
.omh-pane-dv-tip{fill:var(--dv-e);stroke-width:1}
.omh-pane-dv-edge[data-tone=done],.omh-pane-dv-tip[data-tone=done]{--dv-e:var(--omh-text-readable)}
.omh-pane-dv-edge[data-tone=accent],.omh-pane-dv-tip[data-tone=accent]{--dv-e:var(--ui-accent)}
.omh-pane-dv-edge[data-tone=error],.omh-pane-dv-tip[data-tone=error]{--dv-e:var(--ui-red)}
.omh-pane-dv-edge[data-hot=true],.omh-pane-dv-tip[data-hot=true]{--dv-e:var(--omh-brand)}
.omh-pane-dv-edge[data-hot=true]{stroke-width:1.6}
.omh-pane-dv-edge[data-hollow=true]{stroke-dasharray:4 3}
.omh-pane-dv-tip[data-hollow=true]{fill:var(--background)}
.omh-pane-dv-edge[data-dim=true],.omh-pane-dv-tip[data-dim=true]{opacity:.3}
.omh-pane-dv-detail{margin-top:12px;padding:10px;min-width:0;background:var(--ui-bg-card);border:1px solid var(--omh-edge);border-radius:var(--radius-md,4px)}
.omh-pane-dv-head{display:flex;align-items:flex-start;gap:8px}
.omh-pane-dv-badge{display:inline-flex;align-items:center;gap:5px;margin-top:2px;font-family:${MONO};font-size:11px;font-weight:600;white-space:nowrap}
.omh-pane-dv-name{min-width:0;font-size:13px;font-weight:700;line-height:1.35;overflow-wrap:anywhere}
.omh-pane-dv-x{box-sizing:border-box;flex:none;margin:0 0 0 auto;padding:1px 6px;font:inherit;font-size:11px;color:var(--omh-text-readable);background:none;border:1px solid var(--ui-stroke-tertiary);border-radius:3px;cursor:pointer}
.omh-pane-dv-x:hover{color:var(--ui-text-primary);background:var(--chrome-action-hover)}
.omh-pane-dv-chips{display:flex;flex-wrap:wrap;gap:4px;margin:8px 0}
.omh-pane-dv-chip{box-sizing:border-box;display:inline-flex;align-items:center;max-width:100%;height:19px;margin:0;padding:0 7px;font-family:${MONO};font-size:10.5px;color:var(--ui-text-secondary);background:none;border:1px solid var(--ui-stroke-tertiary);border-radius:3px;white-space:nowrap}
.omh-pane-dv-chip-t{display:block;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.omh-pane-dv-chip-model{color:var(--ui-text-primary);border-color:var(--omh-edge)}
.omh-pane-dv-chip-warn{color:var(--omh-warn);border-color:var(--omh-warn)}
.omh-pane-dv-link{position:relative;cursor:pointer}
.omh-pane-dv-link:hover{color:var(--ui-text-primary);border-color:var(--omh-edge)}
.omh-pane-dv-text{margin:0 0 8px;color:var(--ui-text-secondary);overflow-wrap:anywhere}
.omh-pane-dv-facts{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px 10px;margin:10px 0}
.omh-pane-dv-fact{display:flex;flex-direction:column;min-width:0}
.omh-pane-dv-fact-l{font-size:10px;text-transform:uppercase;letter-spacing:.06em;color:var(--omh-text-readable)}
.omh-pane-dv-fact-v{font-family:${MONO};font-size:12px;color:var(--ui-text-primary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.omh-pane-dv-usage{display:flex;align-items:center;gap:12px;padding:8px 0;border-top:1px solid var(--ui-stroke-tertiary)}
.omh-pane-dv-usage-ring{display:flex;flex:none}
.omh-pane-dv-legend{flex:1;min-width:0;display:grid;grid-template-columns:minmax(0,1fr) auto auto;gap:2px 8px;align-items:baseline;font-family:${MONO};font-size:11px}
.omh-pane-dv-legend-k{display:inline-flex;align-items:center;gap:5px;min-width:0;color:var(--ui-text-secondary);white-space:nowrap}
.omh-pane-dv-swatch{display:inline-block;flex:none;width:7px;height:7px;border-radius:1px;background:var(--dv-k)}
.omh-pane-dv-legend-n{text-align:right;color:var(--ui-text-primary)}
.omh-pane-dv-legend-p{min-width:38px;text-align:right;color:var(--omh-text-readable)}
.omh-pane-dv-sec{margin-top:8px;padding-top:8px;border-top:1px solid var(--ui-stroke-tertiary)}
.omh-pane-dv-sec-l{display:block;margin-bottom:4px;font-size:10px;text-transform:uppercase;letter-spacing:.06em;color:var(--omh-text-readable)}
.omh-pane-dv-links{display:flex;flex-wrap:wrap;gap:4px}
.omh-pane-dv-stats{margin:12px 0;background:var(--ui-bg-card);border:1px solid var(--ui-stroke-tertiary);border-radius:var(--radius-md,4px)}
.omh-pane-dv-stats-h{display:flex;align-items:baseline;gap:8px;padding:8px 10px;list-style:none;cursor:pointer;font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;color:var(--omh-label)}
.omh-pane-dv-stats-h::-webkit-details-marker{display:none}
.omh-pane-dv-stats-h::before{content:'▸';color:var(--omh-text-readable)}
.omh-pane-dv-stats[open] .omh-pane-dv-stats-h::before{content:'▾'}
.omh-pane-dv-stats-c{margin-left:auto;font-size:11px;font-weight:400;text-transform:none;letter-spacing:0;color:var(--omh-text-readable)}
.omh-pane-dv-stats-body{padding:0 10px 10px}
.omh-pane-dv-mrow{box-sizing:border-box;display:grid;grid-template-columns:minmax(0,1.5fr) 28px 54px minmax(60px,1fr) 56px;gap:0 8px;align-items:center;width:100%;margin:0;padding:4px 0;font-family:${MONO};font-size:11px;text-align:left;color:inherit;background:none;border:0;border-top:1px solid var(--ui-stroke-tertiary);transition:background-color .15s}
button.omh-pane-dv-mrow{cursor:pointer}
button.omh-pane-dv-mrow:hover{background:var(--chrome-action-hover)}
.omh-pane-dv-mrow[data-on=true]{background:color-mix(in srgb,var(--omh-brand) 10%,transparent)}
.omh-pane-dv-mh{padding:0 0 3px;font-family:inherit;font-size:10px;text-transform:uppercase;letter-spacing:.06em;color:var(--omh-text-readable);border-top:0}
.omh-pane-dv-cell{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.omh-pane-dv-num{text-align:right}
.omh-pane-dv-mini{display:flex;align-items:center;gap:5px;min-width:0}
.omh-pane-dv-bar{flex:1;height:4px;border-radius:2px;background:var(--ui-stroke-tertiary);overflow:hidden}
.omh-pane-dv-bar i{display:block;height:100%;background:var(--omh-brand)}
.omh-pane-dv-mini-n{min-width:32px;text-align:right}
.omh-pane-dv-path{display:flex;flex-wrap:wrap;align-items:center;gap:4px;margin-top:6px}
.omh-pane-dv-path-l{margin-right:4px;font-size:10px;text-transform:uppercase;letter-spacing:.06em;color:var(--omh-text-readable)}
.omh-pane-dv-arrow{font-family:${MONO};color:var(--omh-text-readable)}
.omh-pane-dv-hl{margin:0 0 0 auto;padding:0;font:inherit;font-size:11px;color:var(--ui-accent);background:none;border:0;cursor:pointer}
.omh-pane-dv-note{margin-top:8px;font-size:10.5px;color:var(--omh-text-readable)}
@media (pointer:coarse),(max-width:640px){.omh-pane-dv-x,.omh-pane-dv-link,.omh-pane-dv-hl{position:relative;height:32px;padding:0 12px;-webkit-tap-highlight-color:transparent}.omh-pane-dv-hl{padding:0 6px}.omh-pane-dv-x::after,.omh-pane-dv-link::after,.omh-pane-dv-hl::after{content:'';position:absolute;inset:-7px -5px}.omh-pane-dv-chips,.omh-pane-dv-links,.omh-pane-dv-path{gap:14px 8px}.omh-pane-dv-path{margin-top:14px}.omh-pane-dv-stats-h{padding:16px 10px}.omh-pane-dv-mrow{padding:16px 0}.omh-pane-dv-mh{padding:0 0 3px}.omh-pane-dv-card{padding:9px 10px 10px;-webkit-user-select:none;user-select:none;-webkit-tap-highlight-color:transparent}}
@media (pointer:coarse){.omh-pane-dv .omh-pane-dag{overflow-x:hidden}}
@container (min-width:520px){.omh-pane-dv-kpis.omh-pane-ub-kpis{grid-template-columns:repeat(3,minmax(0,1fr))}}
.omh-pane-ub-c0{--dv-k:var(--omh-brand)}
.omh-pane-ub-c1{--dv-k:var(--ui-accent)}
.omh-pane-ub-c2{--dv-k:var(--omh-label)}
.omh-pane-ub-c3{--dv-k:var(--omh-warn)}
.omh-pane-ub-c4{--dv-k:var(--ui-blue)}
.omh-pane-ub-c5{--dv-k:var(--ui-purple)}
.omh-pane-ub-c6{--dv-k:color-mix(in srgb,var(--ui-blue) 45%,var(--ui-text-primary))}
.omh-pane-ub-c7{--dv-k:var(--omh-text-readable)}
.omh-pane-ub-parts{margin:0}
.omh-pane-ub-legend{margin-top:2px}
.omh-bar{display:inline-flex;height:100%;align-items:center;gap:4px;border-radius:0;padding:0 6px;font-size:.6875rem;color:var(--ui-text-tertiary);font-variant-numeric:tabular-nums;white-space:nowrap;transition:background-color .15s,color .15s}
.omh-bar:hover{background:var(--chrome-action-hover);color:var(--ui-text-primary)}
.omh-bar-brand{font-weight:700;color:var(--omh-brand)}
.omh-bar-seg+.omh-bar-seg::before{content:'·';margin:0 3px;color:var(--ui-text-quaternary)}
/* Tone classes last: a tone on a cell wins over the cell's own resting colour. */
.omh-pane-accent{color:var(--ui-accent)}
.omh-pane-warn{color:var(--omh-warn)}
.omh-pane-error{color:var(--ui-red)}
.omh-pane-muted{color:var(--omh-text-readable)}
.omh-pane-tertiary{color:var(--omh-text-readable)}
.omh-pane-secondary{color:var(--ui-text-secondary)}
.omh-pane-primary{color:var(--ui-text-primary)}
.omh-pane-mark{color:var(--omh-mark)}
`

// Appends the pane's stylesheet once and returns its remover. A host with no
// document (the node harness) gets a no-op.
export function injectStyle() {
  if (typeof document === 'undefined') {
    return function () {}
  }
  const existing = document.getElementById(STYLE_ID)
  if (existing) existing.remove()
  const style = document.createElement('style')
  style.id = STYLE_ID
  style.textContent = PANE_CSS
  document.head.append(style)
  return function () {
    style.remove()
  }
}

// ---------------------------------------------------------------------------
// Tree helpers. `node(type, props, children, key)` filters empty children
// and picks jsx/jsxs the way a compiler would.
// ---------------------------------------------------------------------------

function present(child) {
  return child !== null && child !== undefined && child !== false && child !== ''
}
function node(type, props, children, key) {
  const list = (Array.isArray(children) ? children : [children]).filter(present)
  if (list.length === 1) return jsx(type, { ...props, children: list[0] }, key)
  return jsxs(type, { ...props, children: list }, key)
}
function span(className, children, key) {
  return node('span', { className }, children, key)
}
function div(className, children, key) {
  return node('div', { className }, children, key)
}
function toneClass(tone) {
  return tone ? `omh-pane-${tone}` : ''
}

// How many cells of the drawing's font fit the drawing's card in `body`: the
// body's width less the card's insets, over one cell measured from a probe
// set in the drawing's own class. Zero where nothing can be measured.
export function measureCells(body) {
  if (!body || typeof document === 'undefined' || typeof body.append !== 'function') return 0
  const probe = document.createElement('span')
  probe.className = 'omh-pane-dag-probe'
  probe.textContent = '0'.repeat(40)
  body.append(probe)
  const cell = probe.getBoundingClientRect().width / 40
  probe.remove()
  return exceeds(cell, 0) ? Math.floor((body.clientWidth - DRAWING_INSET_PX) / cell) : 0
}

// Measures the pane body whenever it resizes (and once its fonts load), and
// hands the width in cells to every query through `setDrawingCells`.
function useMeasuredCells(body) {
  useEffect(
    function () {
      if (!body) return undefined
      const measure = function () {
        setDrawingCells(measureCells(body))
      }
      measure()
      let alive = true
      if (typeof document !== 'undefined' && document.fonts && document.fonts.ready) {
        document.fonts.ready.then(function () {
          if (alive) measure()
        })
      }
      const observer = typeof ResizeObserver === 'function' ? new ResizeObserver(measure) : null
      if (observer) observer.observe(body)
      return function () {
        alive = false
        if (observer) observer.disconnect()
      }
    },
    [body]
  )
}

function useHud() {
  const gateway = useValue(host.state.gateway)
  const sessionId = useValue(host.state.focusedStoredSessionId)
  // `busy` is the focused chat's turn flag, absent on an older host. A hook
  // cannot be skipped, so there the read lands on the gateway atom and its
  // value is ignored.
  const busyRead = useValue(host.state.busy || host.state.gateway)
  const busy = host.state.busy ? busyRead === true : false
  const cols = useDrawingCells()
  const query = useQuery({
    queryKey: [PLUGIN_ID, 'hud', sessionId || '', cols],
    queryFn: function () {
      return fetchHud(sessionId, cols)
    },
    refetchInterval: pollInterval(busy),
    enabled: gateway === 'open',
    // Keep the last answer on screen across a session switch and while a
    // refetch is in flight, so the pane never blanks between polls.
    placeholderData: function (previous) {
      return previous
    }
  })
  return {
    gateway,
    sessionId,
    data: query.data,
    error: query.error,
    receivedAt: Number.isFinite(query.dataUpdatedAt) ? query.dataUpdatedAt : 0
  }
}

// A one-second clock, ticking only while a running row exists so its elapsed
// time moves between polls; disposed with the component.
function useClock(running) {
  const [now, setNow] = useState(function () {
    return Date.now()
  })
  useEffect(
    function () {
      if (!running) return undefined
      const timer = setInterval(function () {
        setNow(Date.now())
      }, 1000)
      return function () {
        clearInterval(timer)
      }
    },
    [running]
  )
  return now
}

// ---------------------------------------------------------------------------
// Pane sections
// ---------------------------------------------------------------------------

// `OMH  2 running`: the brand, its version in the tooltip, and one state. An
// idle pane draws no dot; a running or blocked one draws the dot in that
// state's colour.
// The host's StatusDot tones (`good|muted|warn|bad`) for the pane's state tones.
const DOT_TONES = { accent: 'good', warn: 'warn', error: 'bad' }

function Header({ model }) {
  const payload = model.payload
  const segments = payload ? headerSegments(payload) : model.status ? [{ text: model.status, tone: 'tertiary' }] : []
  const tone = payload ? stateTone(payload) : 'tertiary'
  const brand = span('omh-pane-brand', t('brand'))
  return div('omh-pane-head', [
    payload ? jsx(Tip, { label: t('brandTip', { version: paneVersion(payload) }), children: brand }) : brand,
    segments.length
      ? div('omh-pane-state', [
          tone === 'tertiary' ? null : jsx(StatusDot, { tone: DOT_TONES[tone] || 'good' }),
          span(
            'omh-pane-state-text',
            segments.map(function (segment, index) {
              return span(`omh-pane-state-seg ${toneClass(segment.tone)}`, segment.text, `seg-${index}`)
            })
          )
        ])
      : null
  ])
}

function Chips({ payload }) {
  const chips = chipList(payload)
  if (!chips.length) return null
  return div(
    'omh-pane-chips',
    chips.map(function (chip) {
      return jsx(Badge, { variant: chip.variant, size: 'xs', children: chip.text }, chip.key)
    })
  )
}

// `PLAN  Desktop check          2/6`: the small label, an optional title,
// the count at the right edge.
function SectionHeader({ label, title, count, countClass, column }) {
  return node('div', { className: 'omh-pane-section', 'data-column': column || 'full' }, [
    span('omh-pane-section-label', label),
    title ? span('omh-pane-section-title', title) : null,
    count ? span(`omh-pane-section-count ${countClass || ''}`, count) : null
  ])
}

function CatchesSection({ payload }) {
  const found = catchRows(payload)
  if (!found.length) return null
  return [
    jsx(SectionHeader, { label: t('sectionCatches') }, 'catches-head'),
    div(
      'omh-pane-block',
      found.map(function (row) {
        return node('div', { className: 'omh-pane-catch' }, [span('', row.emoji), span('omh-pane-catch-text', row.text)], `catch-${row.seq}`)
      }),
      'catches-body'
    )
  ]
}

function PlanItem({ item, live, unchanged }) {
  const state = itemState(item)
  const glyphTone = state === 'active' ? (live ? 'accent' : 'warn') : state === 'pending' ? 'tertiary' : 'muted'
  const reason = reasonOf(item)
  const depth = depthOf(item)
  const notes = []
  // Each note is its own line under the text, and a sibling of the label: a
  // text decoration propagates to descendants and cannot be undone below,
  // so the strike lives on the label alone.
  if (reason && state === 'skipped') notes.push(div('omh-pane-item-note', t('planNoteSkipped', { reason }), 'reason'))
  else if (reason) notes.push(div('omh-pane-item-note omh-pane-warn', t('planNoteWaiting', { reason }), 'reason'))
  if (state === 'active' && !live && unchanged) notes.push(div('omh-pane-item-note', t('planNoteUnchanged', { age: unchanged }), 'unchanged'))
  return node('div', { className: 'omh-pane-item', 'data-state': state }, [
    span(`omh-pane-item-glyph ${toneClass(glyphTone)}`, itemGlyph(item)),
    node('span', { className: 'omh-pane-item-text', style: depth ? { paddingLeft: `${depth * 0.6}rem` } : undefined }, [
      span('omh-pane-item-label', safeText(item.text), 'label'),
      ...notes
    ])
  ])
}

function planLiveness(payload) {
  const activity = payload.activity || {}
  return activity.post_tool_call_observed ? !!activity.live : true
}

function NativeHeldPlanSection({ payload, todo }) {
  const items = Array.isArray(todo.items) ? todo.items : []
  const waiting = items.filter(function (item) {
    return item.state !== 'done' && reasonOf(item)
  })
  const unchanged =
    todo.status === 'established' && todo.stall && todo.stall.status === 'unchanged' && Number.isFinite(todo.updated_age_seconds)
      ? elapsedText(Math.max(0, todo.updated_age_seconds))
      : ''
  if (!waiting.length && !unchanged) return []
  const live = planLiveness(payload)
  const shown = waiting.map(function (item, index) {
    return jsx(PlanItem, { item, live, unchanged }, `native-${index}`)
  })
  const anyActive = waiting.some(function (item) {
    return item.state === 'active'
  })
  if (unchanged && !anyActive) shown.push(div('omh-pane-fold', t('planNoteUnchanged', { age: unchanged }), 'native-unchanged'))
  return [
    jsx(
      SectionHeader,
      {
        label: t('sectionPlan'),
        title: t('planNativeTitle'),
        count: waiting.length ? t('planWaiting', { count: waiting.length }) : '',
        countClass: 'omh-pane-warn',
        column: 'plan'
      },
      'plan-head'
    ),
    div('omh-pane-block', shown, 'plan-body')
  ]
}

function PlanSection({ payload }) {
  const todo = payload.todo || {}
  const declared = todo.status === 'established' || todo.status === 'all_done'
  if (!declared) {
    return [
      jsx(SectionHeader, { label: t('sectionPlan'), column: 'plan' }, 'plan-head'),
      jsx(PanelEmpty, { icon: 'checklist', title: t('planEmptyTitle'), description: t('planEmptyDescription') }, 'plan-empty')
    ]
  }
  if (todo.source === NATIVE_TODO_SOURCE) return NativeHeldPlanSection({ payload, todo })
  const progress = planProgress(todo)
  const items = Array.isArray(todo.items) ? todo.items : []
  const window = planWindow(items)
  const folds = foldLabels(items, window)
  const groups = planGroups(items.slice(window.start, window.end))
  const currentPhase = safeText(todo.display_phase)
  const live = planLiveness(payload)
  const unchanged =
    todo.stall && todo.stall.status === 'unchanged' && Number.isFinite(todo.updated_age_seconds) ? elapsedText(Math.max(0, todo.updated_age_seconds)) : ''
  const shown = []
  if (folds.earlier) shown.push(div('omh-pane-fold', folds.earlier, 'earlier'))
  groups.forEach(function (group, groupIndex) {
    const itemNodes = group.items.map(function (item, index) {
      return jsx(PlanItem, { item, live, unchanged }, `${groupIndex}-${index}`)
    })
    if (!group.phase) {
      shown.push(div('omh-pane-plan-items', itemNodes, `${groupIndex}-items`))
      return
    }
    // Every phase is its own header row with its own done/total, and its
    // items hang under it behind a left rule: the structure the TUI keeps,
    // drawn as an outline rather than a column.
    const phaseDone = countOf(group.items, function (item) {
      return item.state === 'done'
    })
    shown.push(
      node(
        'div',
        { className: 'omh-pane-phase', 'data-current': group.phase === currentPhase ? 'true' : 'false' },
        [span('omh-pane-phase-name', group.phase), span('omh-pane-phase-count omh-pane-mono', `${phaseDone}/${group.items.length}`)],
        `${groupIndex}-phase`
      )
    )
    shown.push(div('omh-pane-phase-items', itemNodes, `${groupIndex}-items`))
  })
  if (folds.later) shown.push(div('omh-pane-fold', folds.later, 'later'))
  return [
    jsx(
      SectionHeader,
      { label: t('sectionPlan'), title: safeText(todo.title), count: planCountText(todo), countClass: 'omh-pane-mono', column: 'plan' },
      'plan-head'
    ),
    div(
      'omh-pane-block',
      [
        node(
          'div',
          { className: 'omh-pane-bar' },
          node('div', {
            className: 'omh-pane-bar-fill',
            'data-done': progress.allDone ? 'true' : 'false',
            style: { width: `${progress.percent}%` }
          }),
          'plan-bar'
        ),
        ...shown
      ],
      'plan-body'
    )
  ]
}

// The drawing as one preformatted block: one line per row, each segment in
// its tone, a box's title in bold; it scrolls sideways and never wraps.
function DagDrawing({ lines }) {
  return div('omh-pane-dag-card', node(
    'pre',
    { className: 'omh-pane-dag', 'data-drawing': 'true' },
    lines.map(function (line, index) {
      return node(
        'span',
        { className: 'omh-pane-dag-line' },
        line.length
          ? line.map(function (segment, at) {
              const className = `${toneClass(segment.tone)}${segment.title ? ' omh-pane-dag-title' : ''}${segment.cells ? ' omh-pane-dag-wide' : ''}`
              // A wide character's fallback font is narrower than two cells; the segment keeps the renderer's width.
              return segment.cells
                ? node('span', { className, style: { width: `${segment.cells}ch` } }, segment.text, `s-${at}`)
                : span(className, segment.text, `s-${at}`)
            })
          : ' ',
        `l-${index}`
      )
    })
  ))
}

// ---------------------------------------------------------------------------
// The DAG view's parts: the figures strip, a card per lane with its edges, the
// open lane's detail and the run's stats. State lives in DagView alone (the
// open lane, the highlight, the stats fold); the polled payload only feeds it.
// Nothing here scrolls sideways or listens for a gesture, and no touch-action
// is set, so the host's own sideways swipe always reaches the app.
// ---------------------------------------------------------------------------

const USAGE_KEYS = [
  ['read', 'cr', 'dgCacheRead'],
  ['input', 'in', 'dgInput'],
  ['write', 'cw', 'dgCacheWrite']
]
const ARROW_PX = 7
const BEND_PX = 6

// The prompt's split as a ring: cache read, uncached input, cache write.
function UsageRing({ usage, size }) {
  const total = promptTokens(usage)
  const stroke = Math.max(3, size / 5)
  const radius = (size - stroke) / 2
  const circumference = 2 * Math.PI * radius
  const mid = size / 2
  let offset = 0
  const arcs = []
  USAGE_KEYS.forEach(function (key) {
    const count = usage[key[0]]
    if (!exceeds(count, 0) || !exceeds(total, 0)) return
    const length = (count / total) * circumference
    arcs.push(
      node(
        'circle',
        {
          className: `omh-pane-dv-arc omh-pane-dv-${key[1]}`,
          cx: mid,
          cy: mid,
          r: radius,
          strokeWidth: stroke,
          strokeDasharray: `${length.toFixed(2)} ${(circumference - length).toFixed(2)}`,
          strokeDashoffset: (-offset).toFixed(2),
          transform: `rotate(-90 ${mid} ${mid})`
        },
        [],
        key[1]
      )
    )
    offset += length
  })
  return node('svg', { className: 'omh-pane-dv-ring', width: size, height: size, viewBox: `0 0 ${size} ${size}`, 'aria-hidden': 'true' }, [
    node('circle', { className: 'omh-pane-dv-track', cx: mid, cy: mid, r: radius, strokeWidth: stroke }, [], 'track'),
    ...arcs
  ])
}

// The thin bar under a card (and over the detail): the same split, output last.
function UsageStack({ usage, big }) {
  return node(
    'div',
    { className: `omh-pane-dv-stack${big ? ' omh-pane-dv-big' : ''}` },
    [
      ['cr', usage.read],
      ['in', usage.input],
      ['cw', usage.write],
      ['out', usage.output]
    ].map(function (part) {
      return node('i', { className: `omh-pane-dv-${part[0]}`, style: { flexGrow: part[1] } }, [], part[0])
    })
  )
}

function DagKpis({ dag }) {
  const total = dag.total
  const prompt = promptTokens(total)
  const cells = [
    {
      label: t('dgTokens'),
      value: tokensText(allTokens(total)),
      sub: total.lanes ? t('dgTokensSub', { out: tokenCountText(total.output), prompt: tokenCountText(prompt) }) : '',
      tip: t('dgTokensTip')
    },
    {
      label: t('dgCacheHit'),
      value: percentText(cacheHit(total)),
      sub: exceeds(prompt, 0) ? t('dgCacheHitSub', { read: tokenCountText(total.read), prompt: tokenCountText(prompt) }) : '',
      tip: t('dgCacheHitTip'),
      ring: total
    },
    {
      label: t('dgCost'),
      value: sumCostText(total),
      sub: total.lanes ? t('dgCostSub', { priced: total.priced, counted: total.lanes }) : t('dgCostNone'),
      tip: t('dgCostTip')
    },
    {
      label: t('dgNodeTime'),
      value: dag.timed ? elapsedText(dag.seconds) : '—',
      sub: dag.timed ? t('dgNodeTimeSub', { count: dag.timed }) : '',
      tip: t('dgNodeTimeTip')
    }
  ]
  return jsx(KpiGrid, { cells })
}

// Figure cells in a grid: a label, a value, a line under it, and a ring where
// `ring` carries the usage it draws. `wide` is the usage board's three columns.
function KpiGrid({ cells, wide }) {
  return node(
    'div',
    { className: wide ? 'omh-pane-dv-kpis omh-pane-ub-kpis' : 'omh-pane-dv-kpis' },
    cells.map(function (cell) {
      return node(
        'div',
        { className: 'omh-pane-dv-kpi', title: cell.tip },
        [
          span('omh-pane-dv-kpi-label', cell.label),
          span('omh-pane-dv-kpi-value', cell.value),
          span('omh-pane-dv-kpi-sub', cell.sub),
          cell.ring ? span('omh-pane-dv-kpi-ring', jsx(UsageRing, { usage: cell.ring, size: 26 })) : null
        ],
        cell.label
      )
    })
  )
}

function routeText(lane) {
  const model = lane.model ? `${lane.model}${lane.effort ? `:${lane.effort}` : ''}` : ''
  return [lane.category, model].filter(Boolean).join(' · ') || '?'
}

function LaneCard({ dag, lane, picked, dim, onPick }) {
  const after = lane.parents.length
    ? t('dgAfter', {
        nodes: lane.parents
          .map(function (id) {
            return dag.index[id].title
          })
          .join(', ')
      })
    : t('dgStart')
  const named = lane.tone === 'accent' || lane.tone === 'error' ? toneClass(lane.tone) : lane.state === 'waiting' ? 'omh-pane-secondary' : ''
  return node(
    'button',
    {
      type: 'button',
      className: `omh-pane-dv-card${picked ? ' omh-pane-dv-picked' : ''}${dim ? ' omh-pane-dv-dim' : ''}`,
      'data-lane': lane.id,
      'data-tone': lane.border,
      'aria-pressed': picked,
      onClick: function () {
        onPick(picked ? '' : lane.id)
      }
    },
    [
      span(`omh-pane-dv-title ${named}`, lane.title),
      span('omh-pane-dv-line omh-pane-dv-wrap', routeText(lane)),
      span(`omh-pane-dv-line omh-pane-dv-wrap ${toneClass(lane.tone)}`, laneStatus(lane)),
      span('omh-pane-dv-line omh-pane-dv-wrap', after),
      jsx(UsageStack, { usage: lane.usage })
    ]
  )
}

// Where each edge runs, measured from the cards as laid out: out of a card's
// foot, along the gap, into the next card's head. An edge over a skipped layer
// takes the right-hand gutter. `tone` is the state of the pair it joins.
function edgeLines(canvas, dag, pick, lit) {
  const box = canvas.getBoundingClientRect()
  const at = {}
  canvas.querySelectorAll('[data-lane]').forEach(function (card) {
    const r = card.getBoundingClientRect()
    at[card.getAttribute('data-lane')] = { x: Math.round(r.left - box.left), y: Math.round(r.top - box.top), w: Math.round(r.width), h: Math.round(r.height) }
  })
  const gutter = Math.round(box.width) - 8
  const lines = []
  dag.edges.forEach(function (edge) {
    const a = at[edge.from]
    const b = at[edge.to]
    if (!a || !b) return
    const from = dag.index[edge.from]
    const to = dag.index[edge.to]
    const skip = exceeds(to.layer - from.layer, 1)
    const x1 = a.x + Math.round(a.w / 2)
    const y1 = a.y + a.h
    const y2 = b.y
    const x2 = b.x + Math.round(b.w / 2) + (skip ? Math.min(14, Math.round(b.w / 4)) : 0)
    const bend = y2 - (skip ? 20 : 14)
    let d
    if (skip) {
      d = `M${x1} ${y1} V${y1 + 12} H${gutter} V${bend} H${x2} V${y2 - ARROW_PX}`
    } else if (exceeds(1, Math.abs(x2 - x1))) {
      d = `M${x1} ${y1} V${y2 - ARROW_PX}`
    } else {
      const s = exceeds(x2, x1) ? 1 : -1
      d = `M${x1} ${y1} V${bend - BEND_PX} Q${x1} ${bend} ${x1 + s * BEND_PX} ${bend} H${x2 - s * BEND_PX} Q${x2} ${bend} ${x2} ${bend + BEND_PX} V${y2 - ARROW_PX}`
    }
    const bad = from.state === 'failed' || from.state === 'interrupted'
    const moving = from.state === 'done' && (to.state === 'running' || to.state === 'dispatched')
    const settled = from.state === 'done' && to.state === 'done'
    // An open lane lights its own edges; else a marked set (the path, a model) lights those between its lanes.
    const focus = pick ? edge.from === pick || edge.to === pick : lit ? lit.indexOf(edge.from) !== -1 && lit.indexOf(edge.to) !== -1 : null
    lines.push({
      d,
      tip: `M${x2 - 4} ${y2 - ARROW_PX} L${x2 + 4} ${y2 - ARROW_PX} L${x2} ${y2} Z`,
      tone: bad ? 'error' : moving ? 'accent' : settled ? 'done' : 'wait',
      hollow: !(moving || settled),
      hot: focus === true,
      dim: focus === false
    })
  })
  return { width: Math.round(box.width), height: Math.round(box.height), lines }
}

function DagCanvas({ dag, pick, lit, onPick }) {
  const [canvas, setCanvas] = useState(null)
  const [drawn, setDrawn] = useState({ width: 0, height: 0, lines: [] })
  // What decides the edges; a poll that changes none of it leaves them be, and a card that grows is the observer's.
  const shape = [
    pick,
    lit ? lit.join(',') : '',
    dag.edges
      .map(function (edge) {
        return `${edge.from}.${edge.to}`
      })
      .join(','),
    dag.lanes
      .map(function (lane) {
        return `${lane.id}:${lane.state}`
      })
      .join(',')
  ].join('|')
  useEffect(
    function () {
      if (!canvas) return undefined
      function draw() {
        setDrawn(edgeLines(canvas, dag, pick, lit))
      }
      draw()
      const observer = typeof ResizeObserver === 'function' ? new ResizeObserver(draw) : null
      if (observer) observer.observe(canvas)
      return function () {
        if (observer) observer.disconnect()
      }
    },
    [canvas, shape]
  )
  return node('div', { className: 'omh-pane-dv-canvas', ref: setCanvas }, [
    node(
      'svg',
      { className: 'omh-pane-dv-edges', width: drawn.width, height: drawn.height, 'aria-hidden': 'true' },
      drawn.lines.flatMap(function (line, index) {
        const flags = { 'data-tone': line.tone, 'data-hollow': line.hollow, 'data-hot': line.hot, 'data-dim': line.dim }
        return [
          node('path', { className: 'omh-pane-dv-edge', d: line.d, ...flags }, [], `e${index}`),
          node('path', { className: 'omh-pane-dv-tip', d: line.tip, ...flags }, [], `a${index}`)
        ]
      }),
      'edges'
    ),
    ...dag.layers.map(function (ids, at) {
      return node(
        'div',
        { className: 'omh-pane-dv-row' },
        ids.map(function (id) {
          return jsx(
            LaneCard,
            { dag, lane: dag.index[id], picked: id === pick, dim: !!lit && lit.indexOf(id) === -1, onPick },
            id
          )
        }),
        `row-${at}`
      )
    })
  ])
}

// `key` is the chip's place in its row, so two chips that read alike stay two.
function chip(key, text, title, tone) {
  return node(
    'span',
    { className: `omh-pane-dv-chip${tone ? ` omh-pane-dv-chip-${tone}` : ''}`, title: title || undefined },
    [span('omh-pane-dv-chip-t', text)],
    key
  )
}

// A chip that opens another lane.
function laneLink(dag, id, onPick, label) {
  const lane = dag.index[id]
  return node(
    'button',
    {
      type: 'button',
      className: 'omh-pane-dv-chip omh-pane-dv-link',
      title: lane.title,
      onClick: function () {
        onPick(id)
      }
    },
    [span('omh-pane-dv-chip-t', label || lane.title)],
    `${id}-${label || ''}`
  )
}

// The detail's prompt legend: each part's count and its share of the prompt. A count the lane reported reads as
// written, a 0 as 0; a dash only where the lane reported no usage at all, or no prompt to take a share of.
export function usageLegend(usage) {
  const prompt = promptTokens(usage)
  return USAGE_KEYS.map(function (key) {
    const count = usage[key[0]]
    return {
      part: key[1],
      label: t(key[2]),
      count: usage.reported ? tokenCountText(count) : '—',
      share: exceeds(prompt, 0) ? `${((count / prompt) * 100).toFixed(1)}%` : '—'
    }
  })
}

function LaneDetail({ dag, lane, onPick, seat }) {
  const usage = lane.usage
  const facts = [
    [t('dgElapsed'), lane.elapsed === null ? '—' : elapsedText(lane.elapsed)],
    [t('dgTokens'), tokensText(allTokens(usage))],
    [t('dgCacheHit'), percentText(cacheHit(usage))],
    [t('dgCost'), usage.cost !== null ? costText(usage.cost, usage.estimated) : usage.seen ? t('dgUnpriced') : '—'],
    [t('dgOutput'), exceeds(usage.output, 0) ? `↓${tokensText(usage.output)}` : '—']
  ]
  return node('div', { className: 'omh-pane-dv-detail', ref: seat, 'data-detail': lane.id }, [
    node('div', { className: 'omh-pane-dv-head' }, [
      span(`omh-pane-dv-badge ${toneClass(lane.tone)}`, `${lane.glyph} ${lane.word}`),
      span('omh-pane-dv-name', lane.title),
      node(
        'button',
        {
          type: 'button',
          className: 'omh-pane-dv-x',
          title: 'Esc',
          onClick: function () {
            onPick('')
          }
        },
        t('dgClose')
      )
    ]),
    node('div', { className: 'omh-pane-dv-chips' }, [
      lane.category ? chip('category', lane.category) : null,
      lane.model
        ? chip('model', `${lane.model}${lane.effort ? ` · ${lane.effort}` : ''}`, t('dgModelTip'), 'model')
        : chip('model', t('dgNotStarted'), t('dgNotStartedTip')),
      chip('layer', t('dgLayer', { count: lane.layer + 1 })),
      lane.role && lane.role !== 'build' ? chip('role', lane.role) : null,
      lane.origin ? chip('origin', t(lane.origin === 'repair' ? 'dgRepair' : 'dgExtend'), '', 'warn') : null,
      lane.unchecked ? chip('unchecked', t('dagUnchecked', { count: 1 }), '', 'warn') : null,
      lane.session ? chip('session', t('dgSession', { tail: lane.session }), lane.session) : null
    ]),
    lane.summary ? div('omh-pane-dv-text', lane.summary, 'summary') : null,
    node(
      'div',
      { className: 'omh-pane-dv-facts' },
      facts.map(function (fact) {
        return node('div', { className: 'omh-pane-dv-fact' }, [span('omh-pane-dv-fact-l', fact[0]), span('omh-pane-dv-fact-v', fact[1])], fact[0])
      })
    ),
    node('div', { className: 'omh-pane-dv-usage', title: t('dgUsageTip') }, [
      span('omh-pane-dv-usage-ring', jsx(UsageRing, { usage, size: 44 })),
      node(
        'div',
        { className: 'omh-pane-dv-legend' },
        usageLegend(usage).flatMap(function (row) {
          return [
            span('omh-pane-dv-legend-k', [node('i', { className: `omh-pane-dv-swatch omh-pane-dv-${row.part}` }, []), row.label], `${row.part}-k`),
            span('omh-pane-dv-legend-n', row.count, `${row.part}-n`),
            span('omh-pane-dv-legend-p', row.share, `${row.part}-p`)
          ]
        })
      )
    ]),
    jsx(UsageStack, { usage, big: true }),
    lane.parents.length
      ? node('div', { className: 'omh-pane-dv-sec' }, [
          span('omh-pane-dv-sec-l', t('dgDependsOn')),
          node(
            'div',
            { className: 'omh-pane-dv-links' },
            lane.parents.map(function (id) {
              return laneLink(dag, id, onPick)
            })
          )
        ], 'parents')
      : null,
    lane.children.length
      ? node('div', { className: 'omh-pane-dv-sec' }, [
          span('omh-pane-dv-sec-l', t('dgBlocks', { count: lane.blocks })),
          node(
            'div',
            { className: 'omh-pane-dv-links' },
            lane.children.map(function (id) {
              return laneLink(dag, id, onPick)
            })
          )
        ], 'children')
      : null
  ])
}

function DagStats({ dag, mark, onMark, onPick, open, onOpen }) {
  const on = function (kind, value) {
    return !!mark && mark.kind === kind && mark.value === value
  }
  const head = node('div', { className: 'omh-pane-dv-mrow omh-pane-dv-mh' }, [
    span('omh-pane-dv-cell', t('dgByModel'), 'm'),
    span('omh-pane-dv-cell omh-pane-dv-num', t('dgNodes'), 'n'),
    span('omh-pane-dv-cell omh-pane-dv-num', t('dgTokens'), 't'),
    span('omh-pane-dv-cell', t('dgCacheHit'), 'c'),
    span('omh-pane-dv-cell omh-pane-dv-num', t('dgCost'), 'p')
  ])
  const table = dag.models.map(function (entry) {
    const hit = cacheHit(entry.total)
    return node(
      'button',
      {
        type: 'button',
        className: 'omh-pane-dv-mrow',
        'data-on': on('model', entry.model),
        title: `${entry.model} · ${t('dgModelRowTip')}`,
        onClick: function () {
          onMark({ kind: 'model', value: entry.model })
        }
      },
      [
        span('omh-pane-dv-cell', entry.model, 'm'),
        span('omh-pane-dv-cell omh-pane-dv-num', `${entry.count}`, 'n'),
        span('omh-pane-dv-cell omh-pane-dv-num', tokensText(allTokens(entry.total)), 't'),
        span(
          'omh-pane-dv-mini',
          [
            span('omh-pane-dv-bar', node('i', { style: { width: hit === null ? '0%' : `${hit * 100}%` } }, []), 'bar'),
            span('omh-pane-dv-mini-n', percentText(hit), 'pct')
          ],
          'c'
        ),
        span(
          'omh-pane-dv-cell omh-pane-dv-num',
          entry.total.priced ? sumCostText(entry.total) : entry.total.lanes ? t('dgUnpriced') : '—',
          'p'
        )
      ],
      entry.model
    )
  })
  const path = dag.path.length
    ? node('div', { className: 'omh-pane-dv-path' }, [
        span('omh-pane-dv-path-l', t('dgCriticalPath'), 'label'),
        ...dag.path.flatMap(function (id, index) {
          return [index ? span('omh-pane-dv-arrow', '→', `ar-${index}`) : null, laneLink(dag, id, onPick)]
        }),
        node(
          'button',
          {
            type: 'button',
            className: 'omh-pane-dv-hl',
            onClick: function () {
              onMark({ kind: 'path', value: '' })
            }
          },
          on('path', '') ? t('dgClearHighlight') : t('dgHighlight'),
          'hl'
        )
      ], 'path')
    : null
  const blockers = dag.bottlenecks.length
    ? node('div', { className: 'omh-pane-dv-path' }, [
        span('omh-pane-dv-path-l', t('dgBottlenecks'), 'label'),
        ...dag.bottlenecks.map(function (item) {
          return laneLink(dag, item.id, onPick, t('dgBlocksTitle', { title: dag.index[item.id].title, count: item.blocks }))
        })
      ], 'blockers')
    : null
  return node(
    'details',
    {
      className: 'omh-pane-dv-stats',
      open,
      onToggle: function (event) {
        onOpen(event.currentTarget.open)
      }
    },
    [
      node('summary', { className: 'omh-pane-dv-stats-h' }, [span('', t('dgStats'), 'label'), span('omh-pane-dv-stats-c', t('dgModels', { count: dag.models.length }), 'count')], 'head'),
      node('div', { className: 'omh-pane-dv-stats-body' }, [dag.models.length ? head : null, ...table, path, blockers, div('omh-pane-dv-note', t('dgNote'), 'note')], 'body')
    ]
  )
}

function DagView({ dag, fallback }) {
  const [pick, setPick] = useState('')
  const [mark, setMark] = useState(null)
  const [statsOpen, setStatsOpen] = useState(true)
  const [seat, setSeat] = useState(null)
  // A lane opened below the cards is scrolled into reach once, when it opens.
  useEffect(
    function () {
      if (seat && typeof seat.scrollIntoView === 'function') seat.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
    },
    [pick, seat]
  )
  const lane = dag.index[pick] || null
  const toggle = function (next) {
    setMark(function (now) {
      return now && now.kind === next.kind && now.value === next.value ? null : next
    })
  }
  return node(
    'div',
    {
      className: 'omh-pane-dv',
      onKeyDown: function (event) {
        if (event.key === 'Escape') setPick('')
      }
    },
    [
      jsx(DagKpis, { dag }, 'kpis'),
      jsx(DagStats, { dag, mark, onMark: toggle, onPick: setPick, open: statsOpen, onOpen: setStatsOpen }, 'stats'),
      dag.cards ? jsx(DagCanvas, { dag, pick, lit: markedLanes(dag, mark), onPick: setPick }, 'canvas') : fallback,
      exceeds(dag.hidden, 0) ? div('omh-pane-more', t('graphMore', { count: dag.hidden }), 'hidden') : null,
      lane ? jsx(LaneDetail, { dag, lane, onPick: setPick, seat: setSeat }, 'detail') : null
    ]
  )
}

// While the graph runs, the TUI's drawing of it when the backend sent one,
// else a row per lane; once every lane has settled, one summary line, as the
// TUI's live block keeps. A dag-ulw run takes the DAG view instead (cards with
// their figures and stats), falling back to those only past DAG_CARD_LIMIT.
function DelegationSection({ payload }) {
  const view = delegationView(payload)
  if (!view) return null
  // A run every lane of which has settled is one summary line, cards or not, as the TUI clears its block at run end.
  const dag = view.settled ? null : dagModel(payload.delegation_graph)
  const drawing = view.settled ? null : drawingLines(payload)
  const lanes = view.settled || drawing
    ? []
    : view.lanes.map(function (lane, index) {
        return node(
          'div',
          { className: 'omh-pane-lane', style: lane.depth ? { '--omh-lane-indent': `${lane.depth * 12}px` } : undefined },
          [
            span(`omh-pane-lane-glyph ${toneClass(lane.tone)}`, lane.glyph),
            jsx(Tip, {
              label: [lane.title, lane.model].filter(Boolean).join(' · '),
              children: span('omh-pane-lane-title', lane.title)
            }),
            span('omh-pane-lane-model omh-pane-mono', lane.model),
            span(`omh-pane-lane-state ${toneClass(lane.tone)}`, lane.state)
          ],
          `lane-${index}`
        )
      })
  if (dag) {
    const beyondCards = drawing ? jsx(DagDrawing, { lines: drawing }, 'drawing') : lanes
    return [
      jsx(SectionHeader, { label: t('sectionDag') }, 'delegation-head'),
      div(
        'omh-pane-block',
        [
          // The cards name no run, so the summary line stays; a drawing past the card limit has its own header.
          dag.cards || !drawing ? div('omh-pane-run', view.summary, 'run') : null,
          jsx(DagView, { dag, fallback: dag.cards ? null : beyondCards }, 'dag')
        ],
        'delegation-body'
      )
    ]
  }
  return [
    jsx(SectionHeader, { label: t('sectionDelegation') }, 'delegation-head'),
    div(
      'omh-pane-block',
      [
        // The drawing's own header names the run and its counts; the summary line stands in only without it.
        drawing ? jsx(DagDrawing, { lines: drawing }, 'drawing') : div('omh-pane-run', view.summary, 'run'),
        ...lanes,
        !view.settled && !drawing && view.hidden ? div('omh-pane-more', t('graphMore', { count: view.hidden }), 'more') : null
      ],
      'delegation-body'
    )
  ]
}

// The native subagents as one line; Desktop's Agents panel lists each one.
function SubagentSummary({ payload }) {
  const text = subagentSummary(payload)
  if (!text) return null
  const tip = agentTally(payload).subagents.length ? t('subagentsTip') : ''
  return div('omh-pane-block', tip ? jsx(Tip, { label: tip, children: span('omh-pane-summary', text) }) : span('omh-pane-summary', text))
}

const ROUTE_TONE = { route: 'tertiary', 'route-fallback': 'warn', maestro: 'tertiary', kanban: 'tertiary' }

function RouteRow({ row, extraSeconds }) {
  const id = (safeText(row.task_id) || safeText(row.role)).slice(0, 8)
  const title = longText(row.action) || id || t('untitled')
  const route = routeIdentity(row)
  const figures = rowFigures(row, extraSeconds)
  const mark = rowMark(row)
  const tip = [title, route.text, figures.tokens, figures.cost, ...figures.extras].filter(Boolean).join(' · ')
  return node('div', { className: 'omh-agent', 'data-lane': route.kind }, [
    span(`omh-agent-glyph ${toneClass(mark.tone)}`, mark.spinning ? jsx(GlyphSpinner, { spinner: 'braille', ariaLabel: t('spinnerLabel') }) : mark.glyph),
    jsx(Tip, { label: tip, children: span('omh-agent-title', collapsePaths(title)) }),
    span('omh-agent-id omh-pane-mono', id),
    node('div', { className: 'omh-agent-sub' }, [
      route.text ? jsx(Tip, { label: route.text, children: span(`omh-agent-route omh-pane-mono ${toneClass(ROUTE_TONE[route.kind])}`, route.text) }) : span('omh-agent-route', ''),
      span(`omh-agent-state ${toneClass(figures.stateTone)}`, figures.state),
      span('omh-agent-figure omh-pane-mono', figures.elapsed)
    ])
  ])
}

function RoutesSection({ payload, receivedAt }) {
  const tally = agentTally(payload)
  const routes = tally.routes
  const now = useClock(routes.some(isRunningRow))
  if (!routes.length) return null
  const extraSeconds = receivedAt ? Math.max(0, (now - receivedAt) / 1000) : 0
  return [
    jsx(SectionHeader, { label: t('sectionRoutes'), count: `${routes.length}`, countClass: 'omh-pane-mono' }, 'routes-head'),
    div(
      'omh-pane-block',
      [
        ...routes.map(function (row, index) {
          return jsx(RouteRow, { row, extraSeconds }, `${safeText(row.task_id)}-${index}`)
        }),
        tally.hidden ? div('omh-pane-more', t('subagentsMore', { count: tally.hidden }), 'routes-more') : null
      ],
      'routes-body'
    )
  ]
}

function GraphSection({ graph }) {
  if (!graph || graph.status !== 'active') return null
  const nodes = Array.isArray(graph.nodes) ? graph.nodes : []
  const shown = nodes.slice(0, GRAPH_NODE_LIMIT)
  const frontier = Array.isArray(graph.frontier) ? graph.frontier : []
  const edges = Array.isArray(graph.edges) ? graph.edges : []
  const edgeCount = Math.max(edges.length, Number(graph.edge_count) || 0)
  const hidden = Math.max(0, nodes.length - shown.length) + (Number(graph.hidden_nodes) || 0)
  return [
    jsx(
      SectionHeader,
      { label: t('sectionDag'), title: t('graphTitle', { ready: frontier.length, edges: edgeCount }), count: hidden ? t('graphMore', { count: hidden }) : '' },
      'graph-head'
    ),
    div(
      'omh-pane-graph',
      shown.map(function (nodeRecord, index) {
        const view = graphNodeView(nodeRecord)
        return div(
          'omh-pane-graph-node',
          [
            span(`omh-pane-graph-glyph ${toneClass(view.tone)}`, view.marker),
            span('omh-pane-mono', view.id),
            span(`omh-pane-graph-detail ${view.tone === 'tertiary' || view.tone === 'muted' ? '' : toneClass(view.tone)}`, view.detail)
          ],
          `${view.id}-${index}`
        )
      }),
      'graph-nodes'
    )
  ]
}

const NO_TURNS = []

function readTurns(sessionId) {
  return turnClock.turns[sessionId] || NO_TURNS
}

// The first-token waits this window timed for one chat, kept current as turns end.
function useTurns(sessionId) {
  const [turns, setTurns] = useState(function () {
    return readTurns(sessionId)
  })
  useEffect(
    function () {
      const sync = function () {
        setTurns(readTurns(sessionId))
      }
      turnListeners.add(sync)
      sync()
      return function () {
        turnListeners.delete(sync)
      }
    },
    [sessionId]
  )
  return turns
}

// The focused chat's own figures, first in the pane. The host's atoms are read
// as the host holds them; an older host lacks some, and a hook cannot be
// skipped, so there the read lands on the gateway atom and its value is ignored.
function UsageBoard({ saved, stored }) {
  const gateway = useValue(host.state.gateway)
  const streamRead = useValue(host.state.focusedUsage || host.state.gateway)
  const runtimeRead = useValue(host.state.focusedSessionId || host.state.gateway)
  const busyRead = useValue(host.state.busy || host.state.gateway)
  const [partsOpen, setPartsOpen] = useState(true)
  const live = host.state.focusedUsage && streamRead && typeof streamRead === 'object' ? streamRead : null
  const runtime = host.state.focusedSessionId && typeof runtimeRead === 'string' ? runtimeRead : ''
  const busy = host.state.busy ? busyRead === true : false
  const turns = useTurns(runtime)
  // Read when a call or a compression has moved the prompt and no turn is
  // running, as the host's own gauge does, and never shown under another chat.
  const composition = useQuery({
    queryKey: [PLUGIN_ID, 'context', runtime, live ? live.calls : 0, live ? live.compressions : 0],
    queryFn: function () {
      return host.request('session.context_breakdown', { session_id: runtime })
    },
    enabled: gateway === 'open' && !!runtime && !busy && typeof host.request === 'function',
    retry: false,
    placeholderData: function (previous, before) {
      return before && before.queryKey[2] === runtime ? previous : undefined
    }
  })
  const board = usageBoard({ live, saved, stored, breakdown: composition.data, turns })
  if (!board) return null
  const bar = node(
    'div',
    { className: 'omh-pane-dv-stack omh-pane-dv-big' },
    board.parts.map(function (part, index) {
      return node('i', { className: `omh-pane-ub-c${index % PART_TONES}`, style: { flexGrow: part.tokens } }, [], part.id)
    })
  )
  const legend = node(
    'div',
    { className: 'omh-pane-dv-legend omh-pane-ub-legend' },
    board.parts.flatMap(function (part, index) {
      return [
        node('span', { className: `omh-pane-dv-legend-k omh-pane-ub-c${index % PART_TONES}` }, [span('omh-pane-dv-swatch', ''), span('omh-pane-dv-chip-t', part.label)], `k-${part.id}`),
        span('omh-pane-dv-legend-n', tokenCountText(part.tokens), `n-${part.id}`),
        span('omh-pane-dv-legend-p', percentText(part.share), `p-${part.id}`)
      ]
    })
  )
  const composed = board.parts.length
    ? node(
        'details',
        {
          className: 'omh-pane-dv-stats omh-pane-ub-parts',
          open: partsOpen,
          onToggle: function (event) {
            setPartsOpen(event.currentTarget.open)
          }
        },
        [
          node('summary', { className: 'omh-pane-dv-stats-h' }, [span('', t('ubParts'), 'label'), span('omh-pane-dv-stats-c', `~${tokenCountText(board.sum)}`, 'count')], 'head'),
          node('div', { className: 'omh-pane-dv-stats-body' }, [bar, legend], 'body')
        ],
        'parts'
      )
    : null
  return [
    jsx(SectionHeader, { label: t('sectionUsage'), title: board.model, count: board.calls ? t('ubCalls', { count: board.calls }) : '' }, 'usage-head'),
    div('omh-pane-block', node('div', { className: 'omh-pane-dv' }, [jsx(KpiGrid, { cells: board.cells, wide: true }, 'kpis'), composed]), 'usage-body')
  ]
}

function HudPane() {
  const hud = useHud()
  // The body element, kept through a callback ref, is what the drawing's width is measured on.
  const [body, setBody] = useState(null)
  useMeasuredCells(body)
  const model = paneModel(hud)
  const payload = model.payload
  const sections = []
  if (model.loading) {
    sections.push(jsx(Skeleton, { className: 'omh-pane-skeleton', style: { width: '70%' } }, 'skeleton-1'))
    sections.push(jsx(Skeleton, { className: 'omh-pane-skeleton', style: { width: '45%' } }, 'skeleton-2'))
  } else {
    sections.push(jsx(UsageBoard, { saved: payload ? payload.session_usage : null, stored: hud.sessionId }, 'usage'))
    if (payload) {
      sections.push(jsx(CatchesSection, { payload }, 'catches'))
      sections.push(jsx(PlanSection, { payload }, 'plan'))
      sections.push(jsx(DelegationSection, { payload }, 'delegation'))
      sections.push(jsx(SubagentSummary, { payload }, 'subagents'))
      sections.push(jsx(RoutesSection, { payload, receivedAt: hud.receivedAt }, 'routes'))
      sections.push(jsx(GraphSection, { graph: payload.graph }, 'graph'))
    }
  }
  return div('omh-pane', [
    jsx(Header, { model }),
    div('omh-pane-scope', scopeLabel(hud.sessionId)),
    payload ? jsx(Chips, { payload }) : null,
    div('omh-pane-rule', []),
    node('div', { className: 'omh-pane-body', ref: setBody }, sections),
    model.notice ? div('omh-pane-notice', model.notice) : null
  ])
}

function StatusItem() {
  const hud = useHud()
  const item = statusItem(hud)
  if (!item) return null
  const reveal = function () {
    if (typeof host.revealPane === 'function') host.revealPane(`${PLUGIN_ID}:${PANE_ID}`)
    else if (typeof host.notify === 'function') host.notify({ kind: 'info', message: item.detail })
  }
  return jsx(Tip, {
    label: item.detail,
    children: node('button', { type: 'button', className: 'omh-bar', onClick: reveal }, [
      span('omh-bar-brand', t('brand')),
      ...item.segments.map(function (segment) {
        return span(`omh-bar-seg ${toneClass(segment.tone)}`, segment.text, segment.text)
      })
    ])
  })
}

export default {
  id: PLUGIN_ID,
  name: 'oh-my-hermes',
  description: 'OMH plan, agent routes and status, read from the omh plugin backend inside the Hermes gateway.',
  defaultEnabled: false,
  register(ctx) {
    rest = ctx.rest
    // The app's plugin i18n door (`createPluginI18n`): `register` takes the
    // locale bundles, `t` answers in the app's language. Older hosts lack
    // it, and the English table answers there.
    if (ctx.i18n && typeof ctx.i18n.register === 'function' && typeof ctx.i18n.t === 'function') {
      ctx.i18n.register({ en: EN, ko: KO })
      pluginI18n = ctx.i18n
    }
    const removeStyle = injectStyle()
    // The usage board's TTFT: a turn starts at `message.start`, its wait ends
    // at the first streamed text.
    if (typeof ctx.onEvent === 'function') {
      const waits = ['message.start'].concat(FIRST_TOKEN_EVENTS, TURN_END_EVENTS)
      waits.forEach(function (type) {
        ctx.onEvent(type, function (event) {
          const payload = event && event.payload && typeof event.payload === 'object' ? event.payload : {}
          if (noteTurnEvent(turnClock, type, event && event.session_id, payload.text, Date.now(), payload.turn_id)) {
            turnListeners.forEach(function (listen) {
              listen()
            })
          }
        })
      })
    }
    ctx.onDispose(function () {
      removeStyle()
      rest = null
      pluginI18n = null
      Object.assign(turnClock, newTurnClock())
      turnListeners.clear()
    })
    ctx.registerMany([
      {
        id: 'status',
        area: STATUSBAR_AREAS.right,
        order: 130,
        render: function () {
          return jsx(StatusItem, {})
        }
      },
      {
        id: PANE_ID,
        area: PANES_AREA,
        title: 'omh',
        data: { placement: 'right', width: PANE_WIDTH },
        render: function () {
          return jsx(HudPane, {})
        }
      }
    ])
  }
}
