// The OMH desktop half: the HUD the OMH TUI draws (src/tui/panels.py),
// redrawn for Hermes Desktop as a right-hand pane and a status-bar item, in
// the app's own visual language rather than the terminal's.
//
// The pane reads top to bottom: one line of state (`OMH  2 running`), the
// scope it covers (`this session` or `all sessions`), the few findings worth
// a badge, then its sections in a fixed order, each drawn only when it has
// something to say: CATCHES (the mistakes OMH caught in this session, worded
// as the TUI words them), PLAN, DELEGATION (the delegation graph while one is
// active), ROUTES (the Maestro and Kanban lanes OMH dispatched) and the
// fanout DAG. Hermes Desktop lists every delegate_task child in its own
// Agents panel and in the composer's status stack, so a row per native
// subagent here was a second copy of that list; the pane keeps one summary
// line for them and names that panel in its tooltip. Maestro and Kanban rows
// stay, because nothing in Desktop draws the routes OMH chose.
//
// Each colour has one meaning, through theme tokens only: the accent for
// what is running, yellow for waiting, blocked or a warning, red for failed
// (and for yolo, shown only while it is on), and the text greys for done,
// skipped and everything neutral. Monospace is kept for ids, model and route
// names and figures; words are set in the app's sans.
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
// displayed.
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

// Bound in register(); ctx.rest is scoped to this plugin's namespace.
let rest = null
// Bound in register() when the host offers ctx.i18n; the local table otherwise.
let pluginI18n = null

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

export function hudPath(sessionId) {
  return sessionId ? `/hud?session=${encodeURIComponent(sessionId)}` : '/hud'
}

function fetchHud(sessionId) {
  if (!rest) {
    return Promise.reject(new Error('omh plugin context is not registered'))
  }
  return rest(hudPath(sessionId))
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
  routeUnassigned: 'unassigned'
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
  routeUnassigned: '미배정'
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
// theme's mono stack, and are kept for ids, model and route names and
// figures. One compact layout serves every pane width: a row's long cell
// truncates with an ellipsis (its tooltip holds the whole text) and a state
// word keeps its own fixed cell, so nothing wraps onto a line by itself.
// ---------------------------------------------------------------------------

const MONO = "'JetBrains Mono',var(--font-mono,var(--dt-font-mono,monospace))"

export const PANE_CSS = `
.omh-pane{display:flex;flex-direction:column;height:100%;min-width:0;container-type:inline-size;font-family:var(--font-sans,var(--dt-font-sans,sans-serif));font-size:12px;line-height:1.4;color:var(--ui-text-primary)}
.omh-pane,.omh-bar{--omh-text-readable:color-mix(in srgb,var(--ui-text-secondary),var(--ui-text-tertiary))}
.omh-pane-mono{font-family:${MONO};font-variant-numeric:tabular-nums}
.omh-pane-head{display:flex;align-items:center;gap:8px;padding:10px 10px 0;min-width:0}
.omh-pane-brand{font-weight:600;white-space:nowrap;color:var(--ui-text-primary)}
.omh-pane-state{display:flex;align-items:center;gap:5px;min-width:0;margin-left:auto;font-size:11px;color:var(--ui-text-tertiary);white-space:nowrap}
.omh-pane-state-text{min-width:0;overflow:hidden;text-overflow:ellipsis}
.omh-pane-state-seg+.omh-pane-state-seg::before{content:'·';margin:0 3px;color:var(--ui-text-quaternary)}
.omh-pane-scope{padding:2px 10px 6px;font-size:11px;color:var(--omh-text-readable)}
.omh-pane-chips{display:flex;flex-wrap:wrap;gap:4px;padding:0 10px 8px}
.omh-pane-rule{flex:none;border-top:1px solid var(--ui-stroke-tertiary)}
.omh-pane-body{min-height:0;flex:1;overflow-y:auto;overscroll-behavior:contain;padding-bottom:10px}
.omh-pane-section{display:flex;align-items:baseline;gap:8px;padding:12px 10px 4px;min-width:0;max-width:640px;box-sizing:border-box}
.omh-pane-section-label{font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.06em;color:var(--ui-text-quaternary);white-space:nowrap}
.omh-pane-section-title{min-width:0;flex:1;color:var(--ui-text-secondary);overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
.omh-pane-section-count{margin-left:auto;font-size:11px;color:var(--ui-text-tertiary);white-space:nowrap}
.omh-pane-block{padding:0 10px;min-width:0;max-width:640px;box-sizing:border-box}
.omh-pane-bar{height:2px;margin:2px 0 6px;border-radius:1px;background:var(--ui-stroke-tertiary);overflow:hidden}
.omh-pane-bar-fill{height:100%;background:var(--ui-accent)}
.omh-pane-bar-fill[data-done=true]{background:var(--ui-text-quaternary)}
.omh-pane-phase{display:flex;align-items:baseline;gap:8px;margin-top:6px;font-weight:600;color:var(--ui-text-tertiary);min-width:0}
.omh-pane-phase[data-current=true]{color:var(--ui-text-primary)}
.omh-pane-phase-name{min-width:0;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
.omh-pane-phase-count{margin-left:auto;font-size:11px;font-weight:400;color:var(--ui-text-quaternary)}
.omh-pane-phase-items{margin:2px 0 0 6px;padding-left:8px;border-left:1px solid var(--ui-stroke-tertiary)}
.omh-pane-plan-items{margin-top:2px}
.omh-pane-item{display:grid;grid-template-columns:14px minmax(0,1fr);gap:0 4px;align-items:baseline;min-width:0;padding:1px 0}
.omh-pane-item-glyph{text-align:center;color:var(--ui-text-tertiary)}
.omh-pane-item-text{min-width:0;overflow-wrap:anywhere}
.omh-pane-item-label{color:var(--ui-text-primary)}
.omh-pane-item[data-state=done] .omh-pane-item-label{color:var(--ui-text-quaternary);text-decoration:line-through}
.omh-pane-item[data-state=skipped] .omh-pane-item-label{color:var(--ui-text-quaternary)}
.omh-pane-item[data-state=active] .omh-pane-item-label{font-weight:600}
.omh-pane-item-note{display:block;margin-top:1px;font-size:11px;color:var(--omh-text-readable);overflow-wrap:anywhere}
.omh-pane-fold{padding:1px 0 1px 18px;font-size:11px;color:var(--ui-text-quaternary)}
.omh-pane-catch{display:grid;grid-template-columns:20px minmax(0,1fr);gap:0 4px;align-items:baseline;padding:1px 0;color:var(--ui-text-secondary)}
.omh-pane-catch-text{min-width:0;overflow-wrap:anywhere}
.omh-pane-summary{display:block;padding:10px 0 0;color:var(--omh-text-readable);overflow-wrap:anywhere}
.omh-pane-run{padding:0 0 3px;color:var(--ui-text-secondary);overflow-wrap:anywhere}
.omh-pane-lane{display:grid;grid-template-columns:14px minmax(0,1fr) auto 64px;gap:0 6px;align-items:baseline;min-width:0;padding:1px 0}
.omh-pane-lane-glyph{text-align:center}
.omh-pane-lane-title{min-width:0;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
.omh-pane-lane-model{max-width:96px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;font-size:11px;color:var(--ui-text-quaternary)}
.omh-pane-lane-state{overflow:hidden;white-space:nowrap;text-overflow:ellipsis;font-size:11px;text-align:right}
@container (max-width: 420px){.omh-pane-lane{grid-template-columns:14px minmax(0,1fr) 64px}.omh-pane-lane-glyph{grid-row:1}.omh-pane-lane-title{grid-column:2;grid-row:1}.omh-pane-lane-state{grid-column:3;grid-row:1}.omh-pane-lane-model{grid-column:2/-1;grid-row:2;max-width:none}}
.omh-pane-more{padding:2px 0 0 20px;font-size:11px;color:var(--ui-text-quaternary)}
.omh-agent{display:grid;grid-template-columns:14px minmax(0,1fr) auto;gap:1px 6px;align-items:baseline;min-width:0;padding:3px 0}
.omh-agent-glyph{text-align:center}
.omh-agent-title{min-width:0;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;color:var(--ui-text-primary)}
.omh-agent-id{font-size:11px;color:var(--ui-text-quaternary);white-space:nowrap}
.omh-agent-sub{grid-column:2/-1;display:grid;grid-template-columns:minmax(0,1fr) 64px 52px;gap:0 6px;align-items:baseline;min-width:0;font-size:11px;color:var(--ui-text-tertiary)}
.omh-agent-route{min-width:0;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
.omh-agent-state{overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
.omh-agent-figure{white-space:nowrap;text-align:right}
.omh-pane-graph{display:grid;gap:1px;padding:0 10px;font-size:11px;min-width:0;max-width:640px;box-sizing:border-box}
.omh-pane-graph-node{display:grid;grid-template-columns:14px auto minmax(0,1fr);gap:0 6px;align-items:baseline;min-width:0}
.omh-pane-graph-glyph{text-align:center}
.omh-pane-graph-detail{min-width:0;overflow-wrap:anywhere;color:var(--omh-text-readable)}
.omh-pane-notice{margin:6px 10px 8px;border-radius:6px;background:var(--chrome-action-hover);padding:6px 8px;font-size:11px;color:var(--omh-text-readable);overflow-wrap:anywhere}
.omh-pane-skeleton{height:10px;margin:6px 10px}
.omh-bar{display:inline-flex;height:100%;align-items:center;gap:4px;border-radius:0;padding:0 6px;font-size:.6875rem;color:var(--ui-text-tertiary);font-variant-numeric:tabular-nums;white-space:nowrap;transition:background-color .15s,color .15s}
.omh-bar:hover{background:var(--chrome-action-hover);color:var(--ui-text-primary)}
.omh-bar-brand{font-weight:600;color:var(--ui-text-secondary)}
.omh-bar-seg+.omh-bar-seg::before{content:'·';margin:0 3px;color:var(--ui-text-quaternary)}
/* Tone classes last: a tone on a cell wins over the cell's own resting colour. */
.omh-pane-accent{color:var(--ui-accent)}
.omh-pane-warn{color:var(--ui-yellow)}
.omh-pane-error{color:var(--ui-red)}
.omh-pane-muted{color:var(--ui-text-quaternary)}
.omh-pane-tertiary{color:var(--omh-text-readable)}
.omh-pane-primary{color:var(--ui-text-primary)}
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

function useHud() {
  const gateway = useValue(host.state.gateway)
  const sessionId = useValue(host.state.focusedStoredSessionId)
  // `busy` is the focused chat's turn flag, absent on an older host. A hook
  // cannot be skipped, so there the read lands on the gateway atom and its
  // value is ignored.
  const busyRead = useValue(host.state.busy || host.state.gateway)
  const busy = host.state.busy ? busyRead === true : false
  const query = useQuery({
    queryKey: [PLUGIN_ID, 'hud', sessionId || ''],
    queryFn: function () {
      return fetchHud(sessionId)
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

function DelegationSection({ payload }) {
  const view = delegationView(payload)
  if (!view) return null
  const lanes = view.settled
    ? []
    : view.lanes.map(function (lane, index) {
        return node(
          'div',
          { className: 'omh-pane-lane' },
          [
            span(`omh-pane-lane-glyph ${toneClass(lane.tone)}`, lane.glyph),
            jsx(Tip, {
              label: [lane.title, lane.model].filter(Boolean).join(' · '),
              children: node('span', { className: 'omh-pane-lane-title', style: lane.depth ? { paddingLeft: `${lane.depth * 12}px` } : undefined }, lane.title)
            }),
            node('span', { className: 'omh-pane-lane-model omh-pane-mono', style: lane.depth ? { paddingLeft: `${lane.depth * 12}px` } : undefined }, lane.model),
            span(`omh-pane-lane-state ${toneClass(lane.tone)}`, lane.state)
          ],
          `lane-${index}`
        )
      })
  return [
    jsx(SectionHeader, { label: t('sectionDelegation') }, 'delegation-head'),
    div(
      'omh-pane-block',
      [
        div('omh-pane-run', view.summary, 'run'),
        ...lanes,
        !view.settled && view.hidden ? div('omh-pane-more', t('graphMore', { count: view.hidden }), 'more') : null
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

function HudPane() {
  const hud = useHud()
  const model = paneModel(hud)
  const payload = model.payload
  const body = []
  if (model.loading) {
    body.push(jsx(Skeleton, { className: 'omh-pane-skeleton', style: { width: '70%' } }, 'skeleton-1'))
    body.push(jsx(Skeleton, { className: 'omh-pane-skeleton', style: { width: '45%' } }, 'skeleton-2'))
  } else if (payload) {
    body.push(jsx(CatchesSection, { payload }, 'catches'))
    body.push(jsx(PlanSection, { payload }, 'plan'))
    body.push(jsx(DelegationSection, { payload }, 'delegation'))
    body.push(jsx(SubagentSummary, { payload }, 'subagents'))
    body.push(jsx(RoutesSection, { payload, receivedAt: hud.receivedAt }, 'routes'))
    body.push(jsx(GraphSection, { graph: payload.graph }, 'graph'))
  }
  return div('omh-pane', [
    jsx(Header, { model }),
    div('omh-pane-scope', scopeLabel(hud.sessionId)),
    payload ? jsx(Chips, { payload }) : null,
    div('omh-pane-rule', []),
    div('omh-pane-body', body),
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
    ctx.onDispose(function () {
      removeStyle()
      rest = null
      pluginI18n = null
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
