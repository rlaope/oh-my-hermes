import { execFile } from 'node:child_process'
import { readFileSync, statSync } from 'node:fs'

export default function register(sdk) {
  const { Box, Dialog, Overlay, Text, defineWidgetApp, h, openWidget, updateWidget } = sdk
  const SPINNER_FRAMES = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']
  const HERMES_HOME = process.env.HERMES_HOME || `${process.env.HOME}/.hermes`
  // The OMH store is the bundle's to resolve, not this file's. A profile
  // names its own under `plugins.entries.omh.settings.omh_home`, and the
  // plugin that dispatches from this TUI reads that setting before any
  // environment value; the readers below get the same answer by asking the
  // bundle with no store named. An `OMH_HOME` this process was launched
  // with passes through for the rest of the standalone precedence, where it
  // loses to the setting -- forcing it here is what had the picker editing
  // `~/.omh` in a profile whose dispatches never read it (#1679).
  const READER_ENV = {
    HOME: process.env.HOME || '',
    HERMES_HOME,
  }
  for (const key of ['OMH_HOME', 'LANG', 'LC_ALL', 'LC_CTYPE', 'SYSTEMROOT', 'WINDIR']) {
    if (process.env[key]) READER_ENV[key] = process.env[key]
  }
  if (['on', 'off'].includes(process.env.OMH_SUBAGENT_GRAPH)) {
    READER_ENV.OMH_SUBAGENT_GRAPH = process.env.OMH_SUBAGENT_GRAPH
  }
  const READER = [
    'import json,os,sys',
    "sys.path.insert(0, os.path.join(os.environ['HERMES_HOME'], 'plugins'))",
    'from omh.runtime_reader import read_omh_hud',
    "print(json.dumps(read_omh_hud(None, os.environ.get('HERMES_HOME'), graph_preference=os.environ.get('OMH_SUBAGENT_GRAPH', 'auto'), tui_session_ref=os.environ.get('OMH_HUD_TUI_SESSION_REF', ''), session_scoped=True, tui_identity_expected=os.environ.get('OMH_HUD_TUI_IDENTITY', '') == '1')))",
  ].join(';')
  // This TUI's own session id. The host writes it to the file named by
  // HERMES_TUI_ACTIVE_SESSION_FILE whenever it creates, resumes, or switches
  // a session, and this widget runs inside that same TUI process, so the
  // file is the one identity the poll can carry that no other TUI shares.
  // A mapped durable id scopes native rows and their derived metrics.
  // Otherwise native activity remains visibly global, as does the OMH lane.
  // The reader preserves the separate existing todo fallback policy.
  // A missing, unreadable, or malformed value is passed as nothing rather
  // than as a mutated string that would select the wrong record.
  const ACTIVE_SESSION_FILE = process.env.HERMES_TUI_ACTIVE_SESSION_FILE || ''
  const SESSION_REF_SHAPE = /^[\p{L}\p{N}_.:@-]{1,160}$/u
  const ACTIVE_SESSION_FILE_MAX_BYTES = 4096
  const activeSessionRef = () => {
    if (!ACTIVE_SESSION_FILE) return ''
    try {
      // A regular, tiny file only: this runs on the TUI loop every poll, so
      // a FIFO or a large file behind the env var must not stall it.
      const info = statSync(ACTIVE_SESSION_FILE)
      if (!info.isFile() || info.size > ACTIVE_SESSION_FILE_MAX_BYTES) return ''
      const parsed = JSON.parse(readFileSync(ACTIVE_SESSION_FILE, 'utf8'))
      const sessionId = typeof parsed?.session_id === 'string' ? parsed.session_id : ''
      return SESSION_REF_SHAPE.test(sessionId) ? sessionId : ''
    } catch {
      return ''
    }
  }

  // Parentheses are in the allowlist because the row identity is SHAPED by
  // them: `category:architect(anthropic/claude...)`, `(codex/maestro ...)`,
  // and `turn 3 (12 tools)` all lost their brackets here and rendered as
  // one run-on token (`architectanthropic/c...`, the owner's report).
  const sanitizeText = value => String(value ?? '')
    .replace(/[^\p{L}\p{N} .:/_·|+()\[\]!\-]/gu, '')
  const safeText = value => sanitizeText(value).slice(0, 96)

  // Text, not chrome. The owner's direction after living with the bordered
  // cards: the OMH surface should read like the host's own status line
  // (` ─ ready │ gpt 5.6 sol │ … `) and like oh-my-claudecode's HUD -- dense
  // text in the TUI's idiom, not a boxed widget that announces itself.
  // Colours still resolve only through the active theme, never literals.
  // `omh coding fanout dispatch` spawns these local CLIs directly (executor
  // profile names from executor_progress.ALLOWED_EXECUTOR_PROFILES); the
  // short forms match how the rest of the row grammar already abbreviates —
  // one bare word, lower case, no provider suffix.
  const MAESTRO_EXECUTOR_SHORT_NAMES = { codex: 'codex', claude_code: 'claude', omo_runtime: 'omo', hermes_local: 'hermes' }
  const SEPARATOR = ' │ '
  // The classic REPL frames the composer with horizontal rules; the modern
  // TUI draws none. An interim single-dock design put both rules AND the
  // plan below the input, which framed the OMH section instead of the chat
  // input and sank the todo the owner was used to reading up top ('투두가 왜
  // 하단에 떠 기존에는 상단에 잘 떴었는데'). The frame is therefore split
  // across the two composer-adjacent zones: the dock-top app renders the
  // plan todo and closes with the rule above the input, the bottom dock
  // opens with the rule below the input and renders status and activity
  // with no closing rule of its own (the host's own status rule already
  // bounds the screen edge).
  // Host cols include the dock's side margins, so a full-cols rule wraps by
  // two cells. The rules sit tight against the composer, exactly like the
  // classic REPL's frame -- padding was tried at one and two rows against
  // live renders and the owner removed it entirely.
  const Rule = ({ columns, t }) => h(Text, { color: t.color.border }, '─'.repeat(Math.max(1, columns - 2)))

  const plural = (count, noun) => `${count} ${noun}${count === 1 ? '' : 's'}`

  // Session metrics OMH can honestly source: cost sums observed per-agent
  // cost_usd across live bindings, ctx is the MAIN row's observed context
  // percentage. The host's own token gauge (36.4k/272k) is hermes session
  // state the reader cannot reach -- the host statusline above the composer
  // already shows it, so absent data renders as "--", never a fabricated
  // zero-of-total.
  function sessionMetrics(payload) {
    const rows = []
      .concat(Array.isArray(payload.maestro?.rows) ? payload.maestro.rows : [])
      .concat(Array.isArray(payload.subagents?.rows) ? payload.subagents.rows : [])
    const cost = rows.reduce((sum, row) => sum + (Number.isFinite(row.cost_usd) ? row.cost_usd : 0), 0)
    const tokens = rows.reduce((sum, row) => sum + (Number.isFinite(row.tokens) ? row.tokens : 0), 0)
    const approximate = rows.some(row => row.cost_approximate)
    // A zero sum earns a figure only when a row vouched for its own zero
    // with recorded provenance (status first, else source -- whatever word
    // the host recorded; this surface does not enumerate a status
    // vocabulary). Same rule the row segment applies, so header and row
    // never disagree about whether a zero may show.
    const zeroCostProvenance = rows
      .map(row => (Number.isFinite(row.cost_usd) && row.cost_usd === 0 && !row.cost_approximate
        ? safeText(row.cost_status) || safeText(row.cost_source)
        : ''))
      .find(Boolean) || ''
    const main = Array.isArray(payload.maestro?.rows) ? payload.maestro.rows[0] : null
    const ctx = main && Number.isFinite(main.context_percentage)
      ? main.context_percentage
      : rows.map(row => row.context_percentage).filter(Number.isFinite)[0]
    return {
      // A positive sum speaks for itself; token-derived approximations
      // (subscription-billed hosts record no per-call cost) carry a `~`. A
      // confirmed zero renders with its provenance marker and never a `~` --
      // an exact zero is not an approximation. A zero no row vouches for
      // renders nothing (a constant $0.000 read as broken).
      cost: cost > 0
        ? `${approximate ? '~' : ''}$${cost.toFixed(3)}`
        : zeroCostProvenance
          ? `$${cost.toFixed(3)} (${zeroCostProvenance})`
          : '',
      // Summed observed subagent tokens in the host gauge's own idiom
      // (184.8k tokens). A summed zero still renders (`0 tokens`) whenever any
      // row carried a figure: that zero is observed agent consumption, and
      // hiding it left a header that read identically whether the agents did
      // nothing or the reader knew nothing. Absence of every figure still
      // renders nothing -- this is agent consumption, not the session gauge
      // the host statusline already owns.
      // Like cost, the sum covers the rows the reader projects (live and
      // lingering bindings), so it is a live figure that can shrink as rows
      // age out or fall past the reader's cap — never a monotonic session
      // total, which the metadata-only projection has no state to carry.
      tokens: rows.some(row => Number.isFinite(row.tokens))
        ? `${tokenCountText(tokens)} tokens`
        : '',
      // `ctx N%` when a row reports a context reading, and NOTHING when none
      // does. It used to render a permanent not-collected dash, which read
      // as a broken
      // feature rather than an absent number -- and it is absent on every
      // session, not just some: `context_percentage` has a schema slot, a
      // reader projection, and this render path, but no production writer
      // anywhere in the tree (`grep -rn "context_percentage=" src/` outside
      // tests finds none). Nor can one be derived from what OMH can reach:
      // the host's usage table sums input tokens ACROSS calls, which is not
      // the size of a context, and nothing records a model's window. The
      // slot stays wired so a future writer lights it up; the dash goes.
      ctx: Number.isFinite(ctx) ? `ctx ${ctx}%` : '',
    }
  }

  // The row's cost figure: a positive observed cost renders bare, a
  // token-derived approximation carries a `~` so it never reads as billing
  // truth, and a confirmed zero renders with the provenance that earns it
  // (`$0.0000 (included)`) -- status first, else source, whatever word the
  // host recorded. A zero with no provenance renders nothing: the reader
  // only sends a bare zero it can vouch for, but the check stays so this
  // surface never states a billing fact the row does not carry.
  //
  // A child the host could not price (a custom gateway provider, where
  // Hermes' pricing produces no amount and stamps its `unknown` no-figure
  // status -- `agent/usage_pricing.py:549`, persisted into the usage table
  // by `agent/turn_usage.py:236,257`) reaches this function one of two
  // ways, and the reader decides which. When OMH knows a rate for the
  // model it sends the token-derived figure with the approximate flag, so
  // the row reads `~$0.0431`. When it does not, the recorded zero and the
  // host's own word arrive untouched and the row still reads
  // `$0.0000 (unknown)`. Nothing here matches on that word -- the rule is
  // the one above, and only a successful approximation changes what
  // renders.
  function costSegmentText(row) {
    if (!Number.isFinite(row.cost_usd)) return ''
    if (row.cost_usd > 0) return `${row.cost_approximate ? '~' : ''}$${row.cost_usd.toFixed(4)}`
    if (row.cost_approximate) return ''
    const provenance = safeText(row.cost_status) || safeText(row.cost_source)
    return provenance ? `$${row.cost_usd.toFixed(4)} (${provenance})` : ''
  }

  function hudStateLabel(active, agents) {
    // Idle says "ready" and nothing more. Claiming work that is not running is
    // what made the old fixed "Ultra Work Ready" header meaningless -- it read
    // identically whether four agents were running or none were.
    if (!active) return 'ready'
    const running = Number(agents.running) || 0
    const blocked = Number(agents.blocked) || 0
    const done = Number(agents.completed) || 0
    // Lingering just-finished subagents keep the block alive without live
    // work; "2 done" is the honest label there, not "0 agents".
    if (!running && !blocked && done) return `${done} done`
    const parts = [plural(Number(agents.active) || 0, 'agent')]
    if (running) parts.push(`${running} running`)
    if (blocked) parts.push(`${blocked} blocked`)
    if (done) parts.push(`${done} done`)
    return parts.join(' · ')
  }
  const readHud = () => new Promise(resolve => {
    // Re-read per poll: /new and /resume move this TUI to another session
    // without restarting the widget, and the todo must follow.
    const sessionRef = activeSessionRef()
    // Two different conditions the reader must not confuse. `OMH_HUD_TUI_IDENTITY`
    // says this caller HAS a per-TUI identity mechanism; the ref says what it
    // produced. An empty ref from a widget means the host has not written the
    // active-session file yet (the launcher creates it empty), not that nobody
    // can say who is reading -- and only the second may fall back to the most
    // recently active TUI. Collapsing them let a freshly opened TUI render the
    // plan of the session beside it.
    const env = { ...READER_ENV, OMH_HUD_TUI_IDENTITY: ACTIVE_SESSION_FILE ? '1' : '' }
    if (sessionRef) env.OMH_HUD_TUI_SESSION_REF = sessionRef
    execFile(
      __OMH_PYTHON_EXECUTABLE__,
      // `-B`, not PYTHONDONTWRITEBYTECODE: `-I` implies `-E`, so this child
      // ignores every PYTHON* variable and only the flag reaches it. Without
      // it the spawn writes `__pycache__` into the Hermes plugins directory,
      // which is manifest-managed install content, and into the temp copy the
      // widget tests drive, where it raced their teardown (issue #1550).
      ['-I', '-B', '-c', READER],
      {
        encoding: 'utf8',
        env,
        // Headroom over the payload's worst case (todo panel included) so an
        // oversized snapshot degrades to null instead of blanking the HUD.
        maxBuffer: 65536,
        timeout: 1500,
      },
      (error, stdout) => {
        if (error || !stdout || stdout.length > 65536) return resolve(null)
        try {
          resolve(JSON.parse(stdout))
        } catch {
          resolve(null)
        }
      }
    )
  })

  const cellWidth = value => Array.from(value).reduce((width, char) => {
    const code = char.codePointAt(0) || 0
    const wide = code >= 0x1100 && (
      code <= 0x115f ||
      code === 0x2329 ||
      code === 0x232a ||
      (code >= 0x2e80 && code <= 0xa4cf) ||
      (code >= 0xac00 && code <= 0xd7a3) ||
      (code >= 0xf900 && code <= 0xfaff) ||
      (code >= 0xfe10 && code <= 0xfe6f) ||
      (code >= 0xff00 && code <= 0xff60) ||
      (code >= 0xffe0 && code <= 0xffe6)
    )
    return width + (wide ? 2 : 1)
  }, 0)

  const truncateTextCells = (text, limit) => {
    if (cellWidth(text) <= limit) return text
    let output = ''
    for (const char of Array.from(text)) {
      if (cellWidth(output + char) > Math.max(0, limit - 1)) break
      output += char
    }
    return `${output}…`
  }
  const truncateCells = (value, limit) => truncateTextCells(safeText(value), limit)

  // The host's own gauge idiom (36.4k/272k) and Claude Code's token counter
  // (184.8k, 2.1m): one decimal ALWAYS kept above a thousand, bare integers
  // under it. The trailing .0 used to be trimmed, which made a round count
  // change width mid-wave (77k beside 77.4k) and cost the column its decimal
  // alignment; the owner asked for `77.0k`. Subagent tokens are observed usage sums (input+output), so the
  // count stays exact even on subscription-billed hosts where only the COST
  // is a token-derived approximation — the owner asked for tokens '근사값으로
  // 라도' there, and the honest answer is better: the real count.
  const tokenCountText = value => {
    // A recorded zero renders as `0`, not as nothing. The reader only sends a
    // number once the row is terminal or has reported usage, so zero here
    // means the run consumed nothing -- which is exactly what a dispatch that
    // died before its first API call did. Blanking it made a failed run look
    // like an unmeasured one.
    if (!Number.isFinite(value) || value < 0) return ''
    if (value < 1000) return `${Math.floor(value)}`
    // Unit break sits where one-decimal rounding lands, so 999,950 reads
    // 1m, never 1000k.
    const [amount, unit] = value < 999_950 ? [value / 1000, 'k'] : [value / 1_000_000, 'm']
    return `${amount.toFixed(1)}${unit}`
  }

  const elapsedText = value => {
    if (!Number.isFinite(value)) return ''
    const seconds = Math.max(0, Math.floor(value))
    if (seconds < 60) return `${seconds}s`
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`
    return `${Math.floor(seconds / 3600)}h ${String(Math.floor(seconds / 60) % 60).padStart(2, '0')}m`
  }

  // `drop` is shed priority, not screen position. The metadata now reads in
  // the order the figures explain each other -- rate beside the token count
  // it is derived from, then cache, then turn -- while a narrowing terminal
  // still sheds the least valuable figure first (rate, then cost, then
  // turn), exactly as it did when position and priority were the same list.
  // Two orders, because the figure that reads first is not the figure that
  // should go first.
  const metricSegment = (kind, text, drop = 0) => ({ drop, kind, text })
  // Only observed values render. The old permanent not-collected labels on
  // cache/ctx were honest but unresolvable for Hermes-native children — the
  // host never records a child's context percentage — and read as a fixable
  // problem ('서브에이전트 트리거는 다시 해야하나?'). Absence of a claim is
  // just as honest -- and the header follows the same rule now, rendering a
  // context reading only when a row carries one.
  const observedPercent = (label, value) =>
    Number.isFinite(value) ? `${label} ${value}%` : ''

  const routeIdentity = row => {
    // The route column shows WHICH model runs, not who serves it: a
    // provider-prefixed id (`anthropic/claude-opus-5`) spent the whole
    // column on the prefix and truncated to `category:architect(anthropic/`,
    // so opus and fable were indistinguishable (the owner's report). The
    // reader still carries `provider` as its own field for anything that
    // needs it; the label keeps only the segment after the last slash.
    const modelName = safeText(row.model).split('/').pop()
    const model = [modelName, safeText(row.effort)].filter(Boolean).join(':')
    // A row `omh coding fanout dispatch` opened (the Maestro lane spawning an
    // external CLI directly, not a Hermes-native delegate_task child) carries
    // `dispatch_lane` from the reader. It renders like every other row in
    // this list — same truncation, dots, and state colors — except its
    // identity segment reads `(<executor>/maestro <model>)` instead of the
    // category:model route, so the dispatched executor and lane are visible
    // at a glance and warn-colored to stand apart from Hermes-native rows.
    const dispatchLane = safeText(row.dispatch_lane)
    const dispatchExecutor = safeText(row.executor_profile)
    const dispatchIdentity = dispatchLane
      ? `(${MAESTRO_EXECUTOR_SHORT_NAMES[dispatchExecutor] || dispatchExecutor}/${dispatchLane}${modelName ? ` ${modelName}` : ''})`
      : ''
    const category = safeText(row.category)
    // Prepared-route provenance from the reader, rendered as one shape:
    // `category(model tag)`. The category names the LANE and never changes;
    // only the parenthesized model (and its state token) moves — a fallback
    // lane reads `category(model fallback)`, an exhausted chain running the
    // parent's model reads `category(model inherit)`, and a lane the tool
    // routed to the model the parent itself runs reads
    // `category(model =parent)` — its category survives, and the token says
    // the dispatch cost what the parent costs. A child with no route record
    // at all on the parent's model is the one plain `inherit(model)`: inherit
    // is not a category, so it never wears the `category:` prefix.
    const routeOrigin = safeText(row.route_origin)
    const routeCategory = safeText(row.route_category)
    // A fallback that landed on the parent's own model keeps both tokens:
    // the fallback is what happened, `=parent` is what it cost.
    const parentTag = row.same_as_parent === true ? '=parent' : ''
    const routeTag = routeOrigin === 'fallback' ? ['fallback', parentTag].filter(Boolean).join(' ')
      : routeOrigin === 'exhausted_to_inherit' ? 'inherit'
        : parentTag
    const routeDetail = [model, routeTag].filter(Boolean).join(' ')
    const displayCategory = routeOrigin === 'exhausted_to_inherit' && routeCategory ? routeCategory : category
    const route = displayCategory === 'inherit'
      ? `inherit${model ? `(${model})` : ''}`
      : displayCategory
        ? `category:${displayCategory}${routeDetail ? `(${routeDetail})` : ''}`
        : model
    const routeKind = routeOrigin === 'fallback' || routeOrigin === 'exhausted_to_inherit' ? 'route-fallback' : 'route'
    // A Hermes Kanban lane (reader: kanban_board_reader) is board work a
    // dispatcher runs as a detached worker profile, not a delegate_task
    // child, so its identity names the ASSIGNEE profile where the native
    // lane names a mixture category, in the same shape the native lane
    // uses -- `category:name(model:effort)` becomes
    // `kanban/miku(model:effort)` -- so the two kinds of row read as one
    // column. Its own segment kind renders in the theme's accent tone.
    if (safeText(row.lane_backend) === 'kanban') {
      const assignee = safeText(row.assignee) || 'unassigned'
      const effort = safeText(row.effort)
      const detail = modelName ? `${modelName}${effort ? `:${effort}` : ''}` : ''
      return metricSegment('kanban', `kanban/${assignee}${detail ? `(${detail})` : ''}`)
    }
    return dispatchLane ? metricSegment('maestro', dispatchIdentity) : metricSegment(routeKind, route)
  }

  // The route column takes the widest identity in the list (0 = no column)
  // and the label is NEVER truncated: category, model and effort are what
  // the column is for ('category, modelname, effort만 잘 나오면 되니까'),
  // so the action title yields the width instead. `full` measures the
  // documented `category:name(model:effort)` shape; `compact` the same list
  // with the `category:` literal shed, the fallback for a terminal that
  // cannot hold the full shape.
  const ROUTE_PREFIX = 'category:'
  const routeCompact = text => text.startsWith(ROUTE_PREFIX) ? text.slice(ROUTE_PREFIX.length) : text
  const routeColumnWidth = rows => rows.reduce((width, row) => {
    const text = routeIdentity(row).text
    return { compact: Math.max(width.compact, cellWidth(routeCompact(text))), full: Math.max(width.full, cellWidth(text)) }
  }, { compact: 0, full: 0 })

  // The tag in front of the id names what runs the row, in three cells
  // either way so the ids stay aligned: `[bot]` is a board worker (a
  // profile the dispatcher runs as its own process), `[sub]` is a
  // delegate_task child of this session. Whether this chat created the
  // row is no longer a per-row word (it read `[global]` / `[this chat]`);
  // the header line still says the scope. A Maestro or fanout executor
  // row is neither kind and carries no tag.
  const kindTag = row => safeText(row.lane_backend) === 'kanban'
    ? '[bot] '
    : safeText(row.dispatch_lane) || safeText(row.executor_profile) ? '' : '[sub] '
  const scopeLabel = kindTag
  const activityLayout = (row, columns, main, extraSeconds, tokensColumn, routeColumn, scopeWidth) => {
    // A board lane's tail shows the native status word (`ready`, `review`,
    // `archived`), never the reader's projected state: `queued` and `stale`
    // are HUD verdicts carried by the marker, and the board's own vocabulary
    // is what the operator sees in `hermes kanban`.
    const state = safeText(row.lane_backend) === 'kanban'
      ? safeText(row.native_status) || safeText(row.state) || 'running'
      : safeText(row.state) || 'running'
    const stateAbbreviations = { running: 'run', blocked: 'block', failed: 'fail', scheduled: 'sched', archived: 'arch', review: 'rev' }
    const stateText = columns < 100 ? stateAbbreviations[state] || state : state
    const taskId = truncateCells(safeText(row.task_id) || safeText(row.role) || 'agent', 8).padEnd(8)
    const turn = Number.isFinite(row.turn_count) ? `turn ${row.turn_count}` : ''
    const tools = Number.isFinite(row.tool_count) ? `${row.tool_count} tools` : ''
    const turnTools = turn && tools ? `${turn} (${tools})` : turn || tools
    const tokenText = tokenCountText(row.tokens)
    // The route/category is the row's identity, so it is a COLUMN, not one
    // of the droppable middle segments: it sits immediately left of the
    // state/elapsed/tokens block the owner asked to move beside it, padded
    // to a constant width so the token figures still line up vertically
    // from row to row.
    const routeSegment = routeIdentity(row)
    const optional = [
      metricSegment('fallback', Number.isFinite(row.fallback_count) && row.fallback_count > 0 ? `fallback:${row.fallback_count}` : '', 1),
      // Rate reads immediately after the tail's token count ('tokens, tok/s,
      // cache, turns 순으로'): one number is the other's derivative, so the
      // pair belongs together on the line. Its drop rank keeps it the first
      // figure a narrow terminal sheds all the same.
      metricSegment('rate', Number.isFinite(row.tokens_per_second) ? `${Math.round(row.tokens_per_second)} tok/s` : '', 6),
      metricSegment('cache', observedPercent('cache', row.cache_hit_percentage), 2),
      metricSegment('context', observedPercent('ctx', row.context_percentage), 3),
      metricSegment('turn', turnTools, 4),
      // The figure's honesty rules live in costSegmentText: approximation
      // keeps its `~`, a confirmed zero shows its provenance marker, an
      // unvouched zero shows nothing (the old permanent $0.0000 read as
      // broken).
      metricSegment('cost', costSegmentText(row), 5),
    ].filter(segment => segment.text)
    const running = !row.state || row.state === 'running'
    // A running row's elapsed ticks in real time: the snapshot's value plus
    // the seconds since it arrived, re-rendered by the animation clock.
    // Finished rows keep the frozen precise value.
    const elapsed = running ? (row.elapsed_seconds || 0) + extraSeconds : row.elapsed_seconds
    // Claude Code's task list is the reference the owner pointed at
    // ('절대위치로 … 클로드코드처럼 정렬', '이런느낌으로'): a grid, not a
    // sentence. The title is a FIXED column (padded, ~40% of the terminal,
    // 48 cells at most — '서브에이전트 세션 제목을 좀 축약'), variable
    // metadata fills the middle, and a fixed-width tail sits flush against
    // the right edge on every row: `state · elapsed · N tokens`, each piece
    // padded to a constant cell width so the dots and the tokens column line
    // up vertically across rows. Tokens anchor the right edge ('tokens로
    // 해주고 맨 오른쪽에') and are never shed — the middle metadata drops
    // rate, then cost, then turn before the tail loses anything ('달러
    // 이런거 나와있긴 한데 … 소모한 토큰도 나왔으면'). A row with no
    // observed tokens keeps the column as blank cells (only while some row
    // has tokens to align with), never a fabricated zero.
    const padCells = (text, width) => `${text}${' '.repeat(Math.max(0, width - cellWidth(text)))}`
    const stateWidth = columns < 100 ? 5 : 7
    const tokensWidth = tokensColumn ? 16 : 0
    const tailWidth = stateWidth + 3 + 7 + tokensWidth
    const tokensPiece = tokenText
      ? ` · ${tokenText.padStart(6)} tokens`
      : ' '.repeat(tokensWidth)
    const tailState = padCells(truncateTextCells(stateText, stateWidth), stateWidth)
    // Elapsed and the token count are one fixed-width tail but two colours,
    // so they render as two pieces: same cells as before, split at the dot.
    // A queued board lane has not started, so it has no elapsed time to
    // show: the cells stay blank instead of a misleading `0s`.
    const elapsedCell = safeText(row.state) === 'queued' ? padCells('', 7) : padCells(elapsedText(elapsed) || '0s', 7)
    const tailRest = ` · ${elapsedCell}`
    const tailTokens = tokensColumn ? tokensPiece : ''
    const scope = padCells(scopeLabel(row), scopeWidth)
    const prefix = `${scope}${taskId} `
    const separator = '  ·  '
    const budget = Math.max(24, columns - 4)
    // The route column exists per LIST, exactly like the tokens column: a
    // row without a route holds the grid with blank cells so the tail after
    // it stays on the same screen column, and a wave with no routes at all
    // spends none of the width.
    // The full `category:name(model:effort)` shape renders whenever it fits
    // beside the prefix, the tail and an 8-cell action title; otherwise the
    // `category:` literal is shed for the WHOLE list (one column shape per
    // wave) and the label is still padded, never truncated — the action
    // title is what shrinks. `architect(claude-fable-5-1:xhigh)` still says
    // which lane, model and effort ran; `category:architect(claude-` does not.
    const routeRoom = budget - cellWidth(prefix) - tailWidth - cellWidth(separator) - 8 - 2
    // If even the compact identity cannot fit beside a four-cell title,
    // omit the whole shared route column rather than clipping the token tail.
    if (routeColumn.compact > routeRoom + 4) routeColumn = { compact: 0, full: 0 }
    const routeShedPrefix = routeColumn.full > routeRoom
    const routeCap = routeShedPrefix ? routeColumn.compact : routeColumn.full
    const routeWidth = routeCap ? cellWidth(separator) + routeCap : 0
    const routeText = routeShedPrefix ? routeCompact(routeSegment.text) : routeSegment.text
    const routeCell = routeCap
      ? `${separator}${padCells(routeText, routeCap)}`
      : ''
    const actionCap = Math.max(10, Math.min(48, Math.floor(columns * 0.4)))
    const actionWidth = Math.max(4, Math.min(actionCap, budget - cellWidth(prefix) - routeWidth - tailWidth - 2))
    const fixedWidth = cellWidth(prefix) + actionWidth + routeWidth + tailWidth
    const segments = [...optional]
    while (segments.length) {
      const metadata = segments.map(item => item.text).join(separator)
      if (fixedWidth + cellWidth(separator) + cellWidth(metadata) + 2 <= budget) break
      let shed = 0
      for (let index = 1; index < segments.length; index += 1) {
        if (segments[index].drop > segments[shed].drop) shed = index
      }
      segments.splice(shed, 1)
    }
    const metadata = segments.map(segment => segment.text).join(separator)
    return {
      action: padCells(truncateCells(row.action, actionWidth), actionWidth),
      metadata,
      routeCell,
      routeKind: routeSegment.kind,
      segments,
      tailRest,
      tailState,
      tailTokens,
      scope,
      taskId: main ? 'MAIN'.padEnd(8) : taskId,
    }
  }

  function ActivityRow({ columns, extraSeconds, frame, main, row, routeColumn, scopeWidth, t, tokensColumn }) {
    const layout = activityLayout(row, columns, main, extraSeconds, tokensColumn, routeColumn, scopeWidth)
    const blocked = row.state === 'blocked' || row.state === 'failed'
    const done = row.state === 'done'
    // Board-lane verdicts from kanban_board_reader: a queued task has no
    // worker yet, so it must not spin (a static dot in the muted tone), and a
    // stale one has a recorded worker that stopped heartbeating (a warn
    // bang). Both keep the native status word in the tail.
    const queued = row.state === 'queued'
    const stale = row.state === 'stale'
    // A board lane is a different kind of row, and the whole row says so:
    // every piece that is not a semantic verdict -- marker, scope and id,
    // title, identity, elapsed -- renders in the accent tone, the
    // secondary pieces dimmed, so a kanban row reads as one turquoise line
    // beside the native rows. Only `blocked` (error) and `stale` (warn)
    // keep their own colour, because a lane that is stuck must never hide
    // inside the lane colour.
    const board = safeText(row.lane_backend) === 'kanban'
    const marker = blocked ? '▲' : done ? '✓' : queued ? '·' : stale ? '!' : SPINNER_FRAMES[frame % SPINNER_FRAMES.length]
    const statusColor = blocked ? t.color.error : stale ? t.color.warn : board ? t.color.accent : queued ? t.color.muted : t.color.ok
    const markerColor = blocked ? t.color.error : stale ? t.color.warn : board ? t.color.accent : done ? t.color.ok : queued ? t.color.muted : t.color.warn
    return h(
      Text,
      { wrap: 'truncate-end' },
      h(Text, { color: markerColor }, `${marker} `),
      // The kind tag is the one bold piece on the row, the way the header's
      // `⚚ [OMH]` is bold: a glyph would cost cells, bold costs none.
      h(Text, board ? { color: t.color.accent, bold: true } : { color: t.color.muted, bold: true }, layout.scope),
      h(Text, board ? { color: t.color.accent, dimColor: true } : { color: t.color.muted }, `${layout.taskId} `),
      h(Text, { color: board ? t.color.accent : t.color.text }, layout.action),
      // Identity, then the measured block, then the rest. The route column
      // and the state/elapsed/tokens tail are fixed widths, so those figures
      // line up vertically down the list; everything after them is variable
      // and sheds from the right when the terminal narrows.
      h(
        Text,
        {
          color: layout.routeKind === 'route'
            ? t.color.label
            : layout.routeKind === 'route-fallback' || layout.routeKind === 'maestro'
              ? t.color.warn
              // The board lane's own tone: `accent` has no other use on this
              // surface, so a kanban identity is told apart from the native
              // (label) and Maestro (warn) lanes by colour alone.
              : layout.routeKind === 'kanban'
                ? t.color.accent
                : t.color.muted,
        },
        layout.routeCell,
      ),
      h(Text, {}, '  '),
      h(Text, { color: statusColor }, layout.tailState),
      h(Text, board ? { color: t.color.accent, dimColor: true } : { color: t.color.muted }, layout.tailRest),
      // The token count is the one figure on the row that is a plain
      // quantity, so it reads in `statusFg` -- the tone the host's own status
      // line spends on its token gauge -- instead of the muted tint every
      // other metric shares ('tokens는 약간 회색'). The palette derives that
      // tone as a literal grey (grayOf) and a skin may retune it to its own
      // status-bar text, so it stays neutral against the muted run either
      // way. Still a theme token, never a literal.
      h(Text, { color: t.color.statusFg }, layout.tailTokens),
      ...layout.segments.map((segment, index) =>
        h(
          Text,
          {
            color: segment.kind === 'route'
              ? t.color.label
              // A fallback or exhausted route is a warning-grade fact: the
              // lane is NOT running the chain head the category names.
              : segment.kind === 'route-fallback'
                // A dispatched-executor identity is warn-colored for the
                // same reason as a fallback route: it marks the row as
                // something other than the plain Hermes-native default,
                // here the Maestro lane's own spawned CLI.
                || segment.kind === 'maestro'
                // Cache hit rate is the figure the owner reads first on a
                // long run, and asked for in yellow. `warn` is the palette's
                // only amber, so the cache figure shares a colour with the
                // route warnings above -- it is told apart by its `cache`
                // label and by sitting in the metric run, not the route
                // column. No literal enters this file for it.
                || segment.kind === 'cache'
                ? t.color.warn
                : t.color.muted,
            key: `${segment.kind}-${index}`,
          },
          `  ·  ${segment.text}`,
        )
      ),
    )
  }

  function ActivityRows({ columns, extraSeconds, frame, mainRows, rows, t }) {
    // The tokens column exists for the LIST, not per row: one row with an
    // observed count gives every row the column (blank where unobserved) so
    // the grid holds; a wave with no counts at all drops the column instead
    // of wasting sixteen blank cells on every row.
    const tokensColumn = [...mainRows, ...rows].some(row => tokenCountText(row.tokens))
    // Same rule for the route/category column, which now carries the grid:
    // it is what the fixed tail is anchored against, so every row reserves
    // it as soon as one row has a route to show.
    const routeColumn = routeColumnWidth([...mainRows, ...rows])
    // Scope is a shared column too: mixed ownership must not shift the tail.
    const scopeWidth = Math.max(0, ...[...mainRows, ...rows].map(row => cellWidth(scopeLabel(row))))
    return h(
      Box,
      { flexDirection: 'column', width: '100%' },
      ...mainRows.map((row, index) =>
        h(ActivityRow, {
          columns,
          extraSeconds,
          frame,
          key: `main-${index}`,
          main: true,
          routeColumn,
          scopeWidth,
          row,
          t,
          tokensColumn,
        })
      ),
      ...rows.map((row, index) =>
        h(ActivityRow, {
          columns,
          extraSeconds,
          frame,
          key: `${safeText(row.task_id)}-${index}`,
          routeColumn,
          scopeWidth,
          row,
          t,
          tokensColumn,
        })
      ),
    )
  }

  // Mounted only while a RUNNING row exists: the spinner turns and the
  // elapsed counter ticks on the shimmer clock (smooth, unlike the earlier
  // one-frame-per-snapshot attempt, which lurched under repaint throttling
  // and shipped as a frozen orange marker the owner rejected). While work
  // runs, liveness beats drag-copy in the bottom dock — the owner's explicit
  // priority; an idle or linger-only dock stays static and selectable.
  function LiveActivityRows({ columns, mainRows, receivedAt, rows, t }) {
    const frame = shimmerFrame()
    const extraSeconds = receivedAt ? Math.max(0, (Date.now() - receivedAt) / 1000) : 0
    return h(ActivityRows, { columns, extraSeconds, frame, mainRows, rows, t })
  }

  function GraphRows({ columns, graph, nodes, t }) {
    const frontier = Array.isArray(graph.frontier) ? graph.frontier : []
    const edges = Array.isArray(graph.edges) ? graph.edges : []
    const edgeCount = Math.max(edges.length, Number(graph.edge_count) || 0)
    const hidden = Math.max(0, Number(graph.hidden_nodes) || 0)
    const successStates = new Set(['completed', 'already_completed', 'dry_run_planned'])
    const failedStates = new Set([
      'capability_snapshot_invalid',
      'modality_unknown',
      'modality_unsupported',
      'modality_transformation_unobserved',
      'failed',
      'blocked',
      'blocked_by_dependency',
      'executor_not_ready',
      'unsupported_for_local_dispatch',
      'worktree_failed',
      'not_selected',
      'interrupted',
      'model_choice_required',
    ])
    const graphLine = value => {
      const text = truncateTextCells(sanitizeText(value).slice(0, 4096), columns - 2)
      return `${text}${' '.repeat(Math.max(0, columns - 2 - cellWidth(text)))}`
    }
    return h(
      Box,
      { flexDirection: 'column', width: '100%' },
      h(
        Text,
        { color: t.color.label, key: 'graph-header', wrap: 'truncate-end' },
        graphLine(`  ${graph.scope === 'global' ? '[global] ' : ''}DAG · ${frontier.length} ready · ${edgeCount} edges${hidden ? ` · +${hidden} more` : ''}`),
      ),
      ...nodes.map((node, index) => {
        const blockedBy = Array.isArray(node.blocked_by) ? node.blocked_by : []
        // `node.state` is the DISPATCH word: `running` means a marker exists,
        // not that the work is moving. When the reader has assessed the
        // unit's own output and found it stuck, that word REPLACES `running`
        // on this line and carries its reason and stall age -- a supervisor
        // reading `running` over a unit that has repeated one error for half
        // an hour is the whole failure this surface exists to stop.
        const dispatchState = safeText(node.state) || 'unknown'
        const stuckState = safeText(node.unit_state)
        const state = stuckState || dispatchState
        const stallSeconds = Number(node.stalled_for_seconds) || 0
        const stuckReason = stuckState
          ? [safeText(node.state_reason), stallSeconds > 0 ? `${elapsedText(stallSeconds)} since new output` : '']
              .filter(Boolean)
              .join(', ')
          : ''
        const stuckSuffix = stuckReason ? ` (${stuckReason})` : ''
        const marker = stuckState
          ? '[~]'
          : node.in_frontier
            ? '[R]'
            : failedStates.has(state)
              ? '[!]'
              : successStates.has(state)
                ? '[+]'
                : '[.]'
        const suffix = blockedBy.length ? ` · blocked_by ${blockedBy.map(safeText).join(' + ')}` : ''
        return h(
          Text,
          {
            color: stuckState
              ? t.color.warn
              : node.in_frontier
                ? t.color.ok
                : marker === '[!]'
                  ? t.color.error
                  : marker === '[+]'
                    ? t.color.muted
                    : t.color.text,
            key: `${safeText(node.node_id)}-${index}`,
            wrap: 'truncate-end',
          },
          graphLine(`  ${marker} ${safeText(node.node_id)} · ${state}${stuckSuffix}${suffix}`),
        )
      }),
    )
  }

  function Hud({ columns, state, t, viewportRows }) {
    const payload = state.payload
    if (!payload || payload.error || payload.privacy !== 'metadata_only') return null

    // The header stays visible whenever the plugin answers, so an installed
    // OMH is discoverable from an idle session; activity rows are the only
    // part gated on live work.
    const active = !!payload.active
    const agents = payload.subagents || {}
    const version = safeText(payload.version)
    const metrics = sessionMetrics(payload)
    const maestro = payload.maestro || {}
    const board = payload.kanban || {}
    const boardTotal = Number(board.rows_total) || 0
    // Repeat guard: "the same call N times" as opposed to "N calls", which
    // the liveness segment below cannot distinguish (#1687). Rendered only
    // for a repeat the reader actually observed -- the projection answers
    // `idle` for a session that made N DIFFERENT calls, so there is nothing
    // to gate on here beyond its own verdict and the count it carries.
    const repeat = payload.repeat || {}
    const repeatCount = Number(repeat.consecutive) || 0
    const repeatPeriod = Number(repeat.period) || 1
    // The stage is reached one call before the guard uses it -- the gate
    // reads the history before appending the call it is deciding -- so the
    // suffix waits for a call this guard actually refused. Until then the
    // chip is a count, because `blocked` about a call that ran is a claim
    // the payload does not support. Mirrors `repeat_stage_label`.
    const repeatStage = (Number(repeat.intercepted) || 0) >= 1 ? safeText(repeat.stage) : ''
    const repeatChip =
      repeat.status === 'observed' && repeatCount >= 2
        ? `repeat x${repeatCount}${repeatPeriod > 1 ? ` cycle-of-${repeatPeriod}` : ''}${repeatStage === 'blocking' ? ' blocked' : repeatStage === 'approval' ? ' approval' : ''}`
        : ''
    const graph = payload.graph || {}
    const graphActive = graph.status === 'active'
    const graphNodes = graphActive && Array.isArray(graph.nodes) ? graph.nodes : []
    const graphNodeBudget = Math.min(graphNodes.length, Math.max(0, viewportRows - 8))
    const visibleGraphNodes = graphNodes.slice(0, graphNodeBudget)
    const graphHiddenRows =
      Math.max(0, graphNodes.length - visibleGraphNodes.length) + (Number(graph.hidden_nodes) || 0)
    const boundedGraph = graphActive ? { ...graph, hidden_nodes: graphHiddenRows } : graph
    const graphHeight = graphActive ? 1 + visibleGraphNodes.length : 0
    const mainRows = active && Array.isArray(maestro.rows) ? maestro.rows.slice(0, 1) : []
    // Row budget learned from OMO's DAG status widget: five rows by default,
    // but a RUNNING agent lane is never hidden by the cap — with many lanes
    // executing at once the dock must tell that story. The viewport still
    // wins: the dock keeps its chrome (Rule + header) plus prompt margin out
    // of the budget, the `+N more` overflow line pays for a row of its own,
    // and anything hidden — here or by the reader's own cap — is named by
    // that line instead of vanishing.
    const allAgentRows = active && Array.isArray(agents.rows) ? agents.rows : []
    const runningAgents = allAgentRows
      .filter(row => !row.state || row.state === 'running').length
    const viewportBudget = Math.max(1, viewportRows - 5 - graphHeight)
    // The `+N more` line pays for a row of its own (the slice below), so
    // when lanes overflow the budget grows by that one line; otherwise
    // five running lanes and two lingering done ones showed four lanes
    // and hid a running one behind `+3 more` on a 63-row terminal.
    const wantedRows = Math.max(Math.max(5 - mainRows.length, 1), runningAgents)
    const overflowLine = allAgentRows.length > wantedRows ? 1 : 0
    const agentBudget = Math.min(
      wantedRows + overflowLine,
      Math.max(0, viewportBudget - mainRows.length),
    )
    let rows = allAgentRows.slice(0, agentBudget)
    if (allAgentRows.length > rows.length && rows.length > 1) rows = rows.slice(0, rows.length - 1)
    const hiddenRows =
      Math.max(0, allAgentRows.length - rows.length) + (active ? Number(agents.hidden_rows) || 0 : 0)
    return h(
      Box,
      { flexDirection: 'column', width: '100%' },
      h(
        Text,
        { wrap: 'truncate-end' },
        // Always visible: the owner kept the branded status row and asked for
        // live session metrics on it. Tokens, cost and ctx come from
        // sessionMetrics above -- observed values or "--", never fabricated
        // totals.
        h(Text, { bold: true, color: t.color.primary }, '⚚ [OMH]'),
        version ? h(Text, { color: t.color.muted }, ` v${version}`) : null,
        h(Text, { color: t.color.border }, SEPARATOR),
        h(Text, { color: active ? t.color.warn : t.color.ok }, `${agents.scope === 'global' ? '[global] ' : agents.scope === 'mixed' || maestro.rows?.some(row => row.scope === 'global') ? '[this chat + global] ' : agents.scope === 'session' ? '[this chat] ' : ''}${hudStateLabel(active, agents)}`),
        // The session repeating itself, immediately after the state label
        // and before everything optional. Position is the width policy: this
        // line has no drop loop, only `truncate-end`, so a segment's place
        // in the order IS its priority, and a loop must not be the fact that
        // falls off a narrow terminal while a cost estimate survives. The
        // chip is ~10 cells and what it pushes right is what already
        // truncates there -- the tokens segment, which is gated on 100
        // columns for exactly this reason.
        //
        // Metadata only. The reader hands over a count, a cycle length and
        // the guard's stage; it is given no tool name and no arguments, so
        // this says that a call repeated and never what it was (#1687).
        repeatChip
          ? h(
              Text,
              {},
              h(Text, { color: t.color.muted }, ' · '),
              h(
                Text,
                // Three tones for three different facts. Muted while the
                // guard is only watching: a repeat it has not acted on is
                // information, not a fault. Warn once it is refusing the
                // call, error once it has given up on the model and is
                // asking a person. The stage comes from the reader, which
                // takes it from the answer the GATE recorded -- a surface
                // never renders an escalation the gate is withholding.
                { bold: repeatStage !== 'watching', color: repeatStage === 'approval' ? t.color.error : repeatStage === 'blocking' ? t.color.warn : t.color.muted },
                repeatChip,
              ),
            )
          : null,
        // Board lanes are counted beside the agent count only while the
        // board has any: queued/running/blocked as the reader tallied them.
        // `dispatcher not observed` is the reader's verdict that ready tasks
        // have waited past the dispatch window with no worker or claim
        // anywhere on the board -- the one board fault the HUD can see.
        boardTotal > 0
          ? h(Text, { color: t.color.muted }, ` · board ${Number(board.queued) || 0}q ${Number(board.running) || 0}r ${Number(board.blocked) || 0}b`)
          : null,
        board.dispatcher_presence === 'not_observed'
          ? h(Text, { color: t.color.warn }, ' · dispatcher not observed')
          : null,
        h(Text, { color: t.color.muted }, `${metrics.cost ? ` • ${metrics.cost}` : ''}${metrics.ctx ? ` • ${metrics.ctx}` : ''}`),
        // Exact in-flight liveness, paired from pre_tool_call/post_tool_call
        // by tool_call_id: the only honest answer to "is something actually
        // running right now", as opposed to a lingering active todo item or
        // a ring-saturated parallel-shot count. Renders only while at least
        // one call is genuinely open AND this install has actually observed
        // post_tool_call fire at least once (`post_tool_call_observed`) --
        // on a host `_host_supports_hook` never registered post_tool_call
        // for, open entries can only expire, never legitimately close, so a
        // `live` reading there cannot be trusted either way and the segment
        // stays hidden rather than asserting liveness it cannot back.
        payload.activity && payload.activity.live && payload.activity.post_tool_call_observed
          ? h(
              Text,
              {},
              h(Text, { color: t.color.muted }, ' • '),
              h(
                Text,
                { color: t.color.warn },
                `${plural(Number(payload.activity.open_call_count) || 0, 'tool')} · ${
                  elapsedText(payload.activity.oldest_open_elapsed_seconds) || '0s'
                }`,
              ),
            )
          : null,
        // Shift+Tab yolo state: the reader projects the host's persisted
        // surfaces first (the live TUI session row's /yolo flag where the
        // host persists it, config.yaml approvals.mode) so a toggle shows
        // on the next 2s poll, and falls back to the turn/tool-call hook
        // ledger when neither surface speaks. ON warns in the theme's
        // yellow; OFF rests in the label blue — colours resolve through
        // the active theme, never literals. An unobserved or stale state
        // renders nothing rather than a guess.
        payload.yolo && payload.yolo.status === 'observed'
          ? h(
              Text,
              {},
              h(Text, { color: t.color.muted }, ' • yolo mode: '),
              h(
                Text,
                { bold: true, color: payload.yolo.enabled ? t.color.warn : t.color.label },
                payload.yolo.enabled ? 'on' : 'off',
              ),
            )
          : null,
        // The summed token count anchors the header's right edge, matching
        // the rows' rightmost tokens column ('맨 오른쪽에 두는게'). The line
        // has no drop loop, only truncate-end, so below 100 columns it hides
        // rather than being the segment that pushes everything else off.
        columns >= 100 && metrics.tokens
          ? h(Text, { color: t.color.muted }, ` • ${metrics.tokens}`)
          : null,
      ),
      graphActive
        ? h(GraphRows, { columns, graph: boundedGraph, nodes: visibleGraphNodes, t })
        : null,
      mainRows.length || rows.length
        ? ([...mainRows, ...rows].some(row => !row.state || row.state === 'running')
            ? h(LiveActivityRows, { columns, mainRows, receivedAt: state.receivedAt, rows, t })
            : h(ActivityRows, { columns, extraSeconds: 0, frame: 0, mainRows, rows, t }))
        : null,
      hiddenRows
        ? h(Text, { color: t.color.muted, wrap: 'truncate-end' }, `  +${hiddenRows} more`)
        : null,
    )
  }

  // The one sanctioned animation: the plan panel must read as ALIVE while a
  // task is active — the owner asked for motion twice over the quiescence
  // default ('ui적으로 멈추어있는 기분이 들어서'). Two cues, both mounted
  // only while an active item exists: a colour wave that travels through the
  // ACTIVE item's characters (the text itself never moves — each character
  // dims as the wave passes and brightens back), and a walking ellipsis on
  // the [Plan] header. An idle or all-done plan stays byte-stable and
  // drag-copyable; while active, the plan rows in the combined bottom dock
  // deliberately trade selection stability for the motion cue. The SDK
  // shimmer clock is mount-bounded, so thirty minutes caps one continuous
  // wave; guarded access keeps hosts without the hook rendering a static
  // line instead of crashing the widget.
  const shimmerFrame = () =>
    typeof sdk.useShimmerPhase === 'function' ? sdk.useShimmerPhase(1_800_000) : 0

  function PlanPulse({ t }) {
    const frame = shimmerFrame()
    return h(Text, { color: t.color.muted }, ` ${'.'.repeat(1 + (Math.floor(frame / 3) % 3))}`)
  }

  function ShimmerText({ color, t, text }) {
    const frame = shimmerFrame()
    const chars = Array.from(text)
    if (!chars.length) return null
    const cycle = Math.max(8, chars.length + 4)
    const head = frame % cycle
    const segments = []
    for (const [index, char] of chars.entries()) {
      const dim = ((index - head) % cycle + cycle) % cycle < 3
      const last = segments[segments.length - 1]
      if (last && last.dim === dim) last.text += char
      else segments.push({ dim, text: char })
    }
    return h(
      Text,
      {},
      ...segments.map((segment, index) =>
        h(
          Text,
          { bold: true, color: segment.dim ? t.color.muted : color, key: `shimmer-${index}` },
          segment.text,
        )
      ),
    )
  }

  function TodoPanel({ columns, state, t, viewportRows }) {
    const payload = state.payload
    if (!payload || payload.error || payload.privacy !== 'metadata_only') return null
    // Deliberately not gated on payload.active: a declared plan outlives
    // subagent activity, and the reader's 24h staleness rule bounds it. The
    // READER always projects the focused preset, which display_items encode.
    const todo = payload.todo || {}
    // With no plan the panel is only the constant frame chrome: the rule
    // above the input renders unconditionally so the composer frame never
    // blinks with the plan lifecycle.
    if (todo.status !== 'established' && todo.status !== 'all_done') {
      return h(Rule, { columns, t })
    }
    const counts = todo.counts || {}
    const title = safeText(todo.title)
    if (todo.status === 'all_done') {
      return h(
        Box,
        { flexDirection: 'column', width: '100%' },
        h(
          Text,
          { wrap: 'truncate-end' },
          // Same grammar as the status line above it in the combined dock, so
          // the two surfaces read as one product.
          h(Text, { bold: true, color: t.color.primary }, '[Plan]'),
          title ? h(Text, { color: t.color.muted }, ` ${title}`) : null,
          h(Text, { color: t.color.border }, SEPARATOR),
          h(Text, { color: t.color.ok }, `✓ ${counts.done ?? 0}/${counts.total ?? 0}`),
          planShotBadge(payload, t),
        ),
        h(Rule, { columns, t }),
      )
    }
    // The whole plan by default, bounded at eight visible item rows. Every
    // phase renders its name as a header row with one indented item per row
    // beneath it — even a phase with a single task. The old space-saving
    // merge (`Research [•] task`) collapsed exactly the structure the owner
    // wants to read ('[] 이거 탭한번쳐서 한개여도. 그 구조로 나오게'), so a
    // lone task indents under its header like any other. When the plan
    // exceeds eight items the window anchors just before the first
    // remaining item so current work is always on screen, and hidden
    // neighbours fold into muted `... (N earlier/later tasks)` lines.
    const shown = Array.isArray(todo.items) ? todo.items : []
    const hasActive = shown.some(item => item.state === 'active')
    // Truth, not chrome: the active item reads green and animates ONLY while
    // the HUD's exact in-flight signal says something is actually running.
    // Stopped-with-incomplete-todo used to look identical to genuinely
    // working -- both showed the same green [•] -- which is the exact
    // complaint this fixes ('todo에 초록색 진행중 텍스트가 있는게 더 문제').
    // When this install has never observed post_tool_call fire, liveness is
    // unanswerable rather than false -- an unsupported host's ledger can
    // only expire entries, never legitimately close them, so treating that
    // silence as "not live" would brand a genuinely working agent stalled
    // forever. The fallback there is the pre-liveness shape: always live,
    // no stall hint, same as before this signal existed.
    const answerable = !!(payload.activity && payload.activity.post_tool_call_observed)
    const live = answerable ? !!(payload.activity && payload.activity.live) : true
    // Colour and motion above answer "is anything running right now", which
    // is an instantaneous reading and rightly flips the moment a call opens
    // or closes. The elapsed hint below answers a different question -- has
    // this checklist visibly stopped moving -- and that verdict is the
    // READER's (`todo.stall` in runtime_reader.py's `_todo_stall`), so the
    // TUI panel, the text HUD line and the per-turn reminder all state the
    // same finding under the same rule instead of this renderer owning one
    // copy of it. It fires only past the tool-call in-flight TTL, so a gap a
    // single running call could still explain says nothing at all. The word
    // is "unchanged", not "stalled": a plan waiting on the person is
    // unchanged, and the payload's claim_boundary says so too.
    // The age itself the reader computes fresh on every read_omh_hud call
    // (see `updated_age_seconds`), so it stays honest even when
    // applySnapshot's byte-identical-payload check skips a repaint; a
    // Date.now() computed here in render would freeze at whatever second it
    // last actually rendered on an idle snapshot.
    const unchangedElapsed = (() => {
      if (!todo.stall || todo.stall.status !== 'unchanged') return ''
      const seconds = todo.updated_age_seconds
      return Number.isFinite(seconds) ? elapsedText(Math.max(0, seconds)) : ''
    })()
    const markers = { active: '[•]', done: '[✓]', pending: '[ ]' }
    const budget = Math.max(16, columns - 10)
    const currentPhase = safeText(todo.display_phase)
    const phaseCount = Number.isFinite(counts.phases) ? counts.phases : 0
    const depthOf = item => {
      const depth = Number(item.depth)
      return Number.isInteger(depth) && depth > 0 ? Math.min(depth, 3) : 0
    }
    const TODO_DISPLAY_ROWS = 8
    const total = shown.length
    const firstRemaining = shown.findIndex(item => item.state !== 'done')
    const anchor = firstRemaining < 0 ? 0 : Math.max(0, firstRemaining - 1)
    let start = total > TODO_DISPLAY_ROWS ? Math.min(anchor, total - TODO_DISPLAY_ROWS) : 0
    let end = Math.min(total, start + TODO_DISPLAY_ROWS)
    const groupsBetween = (from, to) => {
      const built = []
      for (const item of shown.slice(from, to)) {
        const phase = safeText(item.phase)
        const last = built[built.length - 1]
        // A subtask with no phase of its own continues its parent's group.
        if (last && (last.phase === phase || (!phase && depthOf(item) > 0))) last.items.push(item)
        else built.push({ phase, items: [item] })
      }
      return built
    }
    // Rows a window actually occupies, which the item cap on its own never
    // answered: every group carrying a phase spends a header row, and each
    // side that hides anything spends a fold line. Eight items are therefore
    // up to eighteen rows, which is the whole of #1727.
    const windowRows = (from, to) =>
      to - from +
      groupsBetween(from, to).filter(group => group.phase).length +
      (from > 0 ? 1 : 0) +
      (to < total ? 1 : 0)
    // This dock's share of the terminal. `viewportRows` is the FULL terminal
    // height -- the host builds one RenderCtx from `stdout.rows` and hands
    // the same object to every zone, so it is not a per-zone allotment -- and
    // three claimants sit on it: this dock above the composer, the
    // transcript, and the bottom dock together with the composer frame (the
    // bottom dock already keeps five rows out of its own budget for chrome
    // and prompt margin, `viewportBudget` in Hud above). A third each is the
    // split, and it is chosen so the clamp only ever bites on a short
    // terminal: the tallest frame this renderer can produce is 20 rows
    // (header + earlier fold + eight phase headers + eight items + later
    // fold + rule), so from 60 rows up the budget already covers it and the
    // frame is byte-identical to what it was before the clamp existed. A
    // host that answers with no height makes every comparison below
    // NaN-false, which leaves that same unclamped frame rather than an empty
    // one.
    const dockRowBudget = Math.max(1, Math.floor(viewportRows / 3))
    // The header line and the composer-frame rule are not negotiable: the
    // header IS the summary form, and the rule is what tops the input frame.
    const bodyRowBudget = dockRowBudget - 2
    // Shrink outward from the row the panel exists to show. An item and the
    // phase header it introduces leave together -- an item whose header was
    // dropped would read as belonging to the phase above it -- which
    // `windowRows` accounts for on its own, because a header exists only
    // while its first item does. Fold counts follow the window, so whatever
    // leaves is counted on the `... (N earlier/later tasks)` line it leaves
    // through.
    const activeIndex = shown.findIndex(item => item.state === 'active')
    const focus = Math.min(
      Math.max(activeIndex >= 0 ? activeIndex : Math.max(firstRemaining, 0), start),
      end - 1,
    )
    while (end - start > 1 && windowRows(start, end) > bodyRowBudget) {
      if (end - 1 - focus >= focus - start) end -= 1
      else start += 1
    }
    const groups = groupsBetween(start, end)
    const planHeader = h(
      Text,
      { wrap: 'truncate-end' },
      h(Text, { bold: true, color: t.color.primary }, '[Plan]'),
      title ? h(Text, { color: t.color.muted }, ` ${title}`) : null,
      h(Text, { color: t.color.border }, SEPARATOR),
      h(Text, { color: t.color.warn }, `${counts.done ?? 0}/${counts.total ?? 0}`),
      phaseCount > 1 ? h(Text, { color: t.color.muted }, ` · ${phaseCount} phases`) : null,
      planShotBadge(payload, t),
      hasActive && live ? h(PlanPulse, { t }) : null,
    )
    // Below the minimum -- one item, the phase header it needs, and the folds
    // that account for everything else -- there is no honest checklist left
    // to draw, so the dock falls back to the form it already has for a
    // finished plan: the header line, which carries done/total and the phase
    // count, over the rule. A checklist that dropped rows without saying so
    // would be worse than the summary.
    if (windowRows(start, end) > bodyRowBudget) {
      return h(Box, { flexDirection: 'column', width: '100%' }, planHeader, h(Rule, { columns, t }))
    }
    // The reason an item records for not proceeding, rendered on the row that
    // carries it. Without this an item sits in `active` with nothing saying it
    // is waiting on anything, and the row reads the same as one that has
    // simply stopped (#1553). The row splits its width instead of just
    // appending: the reason takes a bounded share at the end and the item text
    // gives back exactly that much, so a long text cannot push the clause off
    // a `truncate-end` row -- which would leave the display the field exists
    // to fix, on precisely the items that most often carry one. Cutting it is
    // this renderer's job alone: the stop criterion reads the stored field
    // whole, and the ceiling here is the text HUD line's
    // (`TODO_BLOCKED_REASON_DISPLAY_CHARS`, runtime_reader.py).
    const WAITING_CHROME_CELLS = 12 // ` (waiting: ` plus the closing `)`
    const MIN_ITEM_TEXT_CELLS = 24
    const REASON_CELLS_CEILING = 48 // TODO_BLOCKED_REASON_DISPLAY_CHARS, runtime_reader.py
    const reasonCells = Math.max(
      8,
      Math.min(REASON_CELLS_CEILING, budget - WAITING_CHROME_CELLS - MIN_ITEM_TEXT_CELLS),
    )
    const reasonOf = item => truncateCells(item.blocked_reason, reasonCells)
    const textCells = reason => (reason ? Math.max(8, budget - reasonCells - WAITING_CHROME_CELLS) : budget)
    // Warn, not muted: a waiting item is the same "this is not what it looks
    // like at a glance" fact the not-live marker is. It states what the plan
    // recorded and stops there; the payload's evidence boundary already says a
    // todo item is a declaration, never execution evidence.
    const waitingNode = reason => (reason ? h(Text, { color: t.color.warn }, ` (waiting: ${reason})`) : null)
    const itemLabel = (item, reason) =>
      `${Object.hasOwn(markers, item.state) ? markers[item.state] : '[ ]'} ${truncateCells(item.text, textCells(reason))}`
    const itemProps = item => ({
      bold: item.state === 'active',
      // A stalled active item (HUD says not-live) is a warning-grade fact,
      // not progress: the same warn color the route-fallback segment uses
      // for "this is not what it looks like at a glance" (#1145).
      color: item.state === 'active' ? (live ? t.color.ok : t.color.warn) : item.state === 'done' ? t.color.muted : t.color.text,
      strikethrough: item.state === 'done',
    })
    const phaseProps = phase => ({
      bold: true,
      color: phase === currentPhase ? t.color.label : t.color.muted,
    })
    const foldLine = (key, count, side) =>
      h(
        Text,
        { key, wrap: 'truncate-end' },
        h(Text, { color: t.color.muted }, `... (${count} ${side} task${count === 1 ? '' : 's'})`),
      )
    // The active item's text carries the colour wave ONLY while live; motion
    // implies "actually running", so a not-live item renders as static warn
    // text instead, plus the reader's elapsed hint once the checklist has
    // been unchanged long enough to be a finding -- the marker and indent
    // stay the same shape either way, only the state they claim changes.
    const itemNode = (item, indent) => {
      const reason = reasonOf(item)
      const waiting = waitingNode(reason)
      // The reason rides ahead of the unchanged hint: where a row carries
      // both, the reason is what explains the age.
      if (item.state !== 'active') {
        return waiting
          ? h(
              Text,
              { wrap: 'truncate-end' },
              h(Text, itemProps(item), `${indent}${itemLabel(item, reason)}`),
              waiting,
            )
          : h(Text, itemProps(item), `${indent}${itemLabel(item)}`)
      }
      return live
        ? h(
            Text,
            {},
            h(Text, itemProps(item), `${indent}${markers.active} `),
            h(ShimmerText, { color: t.color.ok, t, text: truncateCells(item.text, textCells(reason)) }),
            waiting,
          )
        : h(
            Text,
            { wrap: 'truncate-end' },
            h(Text, itemProps(item), `${indent}${markers.active} ${truncateCells(item.text, textCells(reason))}`),
            waiting,
            unchangedElapsed ? h(Text, { color: t.color.muted }, ` (unchanged ${unchangedElapsed})`) : null,
          )
    }
    const rows = []
    if (start > 0) rows.push(foldLine('todo-earlier', start, 'earlier'))
    groups.forEach((group, groupIndex) => {
      if (group.phase) {
        rows.push(
          h(
            Text,
            { key: `todo-${groupIndex}-phase`, wrap: 'truncate-end' },
            h(Text, phaseProps(group.phase), truncateCells(group.phase, budget)),
          ),
        )
      }
      for (const [index, item] of group.items.entries()) {
        rows.push(
          h(
            Text,
            { key: `todo-${groupIndex}-${index}`, wrap: 'truncate-end' },
            itemNode(item, '  '.repeat(depthOf(item) + (group.phase ? 1 : 0))),
          ),
        )
      }
    })
    if (end < total) rows.push(foldLine('todo-later', total - end, 'later'))
    return h(
      Box,
      { flexDirection: 'column', width: '100%' },
      planHeader,
      ...rows,
      h(Rule, { columns, t }),
    )
  }

  // The parallel-shot badge rides the [Plan] header — the owner moved it
  // here from the frame rule ('parallel shot을 지금 위치에 두지말고 여기
  // 위치 옆에 뜨게'), the line sitting directly under the host status rule.
  // Its lifetime now ties to open calls, not the ring buffer: while any
  // member of the batch is still open, the badge shows the TRUE live count
  // (open_count on the latest shot) instead of the ring-saturated size that
  // used to read "×40" for as long as the ceiling stayed full regardless of
  // whether the batch was still running. Once every member has closed, the
  // badge either drops (idle) or -- while the shot is still fresh -- renders
  // dimmed as history with its age. The history form reads `peak_open_count`
  // (the most calls this shot's own members were ever observed open at
  // once), not `size` (the burst's total member count): Hermes caps
  // concurrent tool workers well under most burst sizes, so a long chain of
  // strictly SEQUENTIAL fast calls -- which the 1.5s grouping window still
  // chains into one burst -- has a `size` that overclaims parallelism the
  // ledger never actually observed.
  const planShotBadge = (payload, t) => {
    const shot = payload.parallel_shot
    if (!shot || shot.status !== 'observed') return null
    const openCount = Number(shot.open_count) || 0
    if (openCount > 0) {
      return h(Text, { color: t.color.label }, ` · parallel shot ×${openCount}`)
    }
    const observedAt = shot.observed_at ? Date.parse(shot.observed_at) : NaN
    const age = Number.isFinite(observedAt) ? elapsedText(Math.max(0, (Date.now() - observedAt) / 1000)) : ''
    return h(
      Text,
      { color: t.color.muted },
      ` · parallel shot ×${Number(shot.peak_open_count) || 0}${age ? ` (${age} ago)` : ''}`,
    )
  }

  const sharedInit = () => ({ payload: null, receivedAt: 0, tick: 0 })
  const sharedReduce = (state, input) =>
    input.kind === 'snapshot'
      ? { ...state, payload: input.payload, receivedAt: Date.now(), tick: state.tick + 1 }
      : state

  // The todo panel reads above the input, where the owner always looked for
  // it; the panel itself ends with the rule that tops the composer frame,
  // so the dock never renders taller than the plan plus one line.
  const todoApp = defineWidgetApp({
    id: 'omh-todo',
    help: 'OMH plan todo and the composer frame above the prompt input',
    mode: 'ambient',
    zone: 'dock-top',
    init: sharedInit,
    reduce: sharedReduce,
    render: ({ cols, rows, state, t }) => {
      if (!state.payload || state.payload.error || state.payload.privacy !== 'metadata_only') return null
      // `rows` reaches a dock-top render the same way it reaches dock-bottom:
      // the host builds one RenderCtx (`useRenderCtx`, ui-tui/src/sdk/host.tsx)
      // from `stdout.rows` and hands the same object to every zone. It is the
      // terminal's height, not this zone's allotment, so the panel has to
      // budget its own share of it -- see TodoPanel.
      return h(TodoPanel, { columns: Math.max(20, cols), state, t, viewportRows: Math.max(1, rows) })
    },
  })

  const app = defineWidgetApp({
    id: 'omh-status',
    help: 'OMH workflow and subagent status below the prompt input',
    mode: 'ambient',
    zone: 'dock-bottom',
    init: sharedInit,
    reduce: sharedReduce,
    render: ({ cols, rows, state, t }) => {
      if (!state.payload || state.payload.error || state.payload.privacy !== 'metadata_only') return null
      const columns = Math.max(20, cols)
      return h(
        Box,
        { flexDirection: 'column', width: '100%' },
        h(Rule, { columns, t }),
        h(Hud, {
          columns,
          state,
          t,
          viewportRows: Math.max(1, rows),
        }),
      )
    },
  })

  // ── /omh-model: the per-category chain picker as a modal app ──────────
  // Hermes' own `/model` picks the SESSION model and cannot be shadowed by
  // a widget, so OMH's picker registers under its own id and edits the
  // per-category mixture chains that bare `omh model-chains` walks on a
  // terminal. Reading and saving go through the installed plugin bundle's
  // `model_chain_picker` — the same rows, the same validated document —
  // and the two step functions below mirror its `step_head_model` and
  // `step_effort` so a keypress never waits on a python spawn;
  // tests/test_tui_model_widget.py drives this app end to end against the
  // python original so the mirror cannot drift. Registered only when the
  // host exposes the overlay primitives; an older host keeps the docks and
  // the CLI picker.
  const PICKER_READER = [
    'import json,os,sys',
    "sys.path.insert(0, os.path.join(os.environ['HERMES_HOME'], 'plugins'))",
    'from omh.model_chain_picker import picker_rows',
    "print(json.dumps(picker_rows(None, hermes_home=os.environ.get('HERMES_HOME'))))",
  ].join(';')
  const PICKER_WRITER = [
    'import json,os,sys',
    "sys.path.insert(0, os.path.join(os.environ['HERMES_HOME'], 'plugins'))",
    'from omh.model_chain_picker import apply_picker_changes',
    "print(json.dumps(apply_picker_changes(None, json.load(sys.stdin), hermes_home=os.environ.get('HERMES_HOME'))))",
  ].join(';')
  const PICKER_EFFORT_LADDER = ['off', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max']
  const runPickerScript = (script, stdinText) => new Promise(resolve => {
    const child = execFile(
      __OMH_PYTHON_EXECUTABLE__,
      // `-B` for the same reason as the HUD reader above: `-I` implies `-E`,
      // so no environment variable can stop this child writing bytecode.
      ['-I', '-B', '-c', script],
      { encoding: 'utf8', env: READER_ENV, maxBuffer: 262144, timeout: 8000 },
      (error, stdout, stderr) => {
        if (error) return resolve({ error: sanitizeText(stderr).trim().slice(-160) || 'omh picker script failed' })
        try {
          resolve(JSON.parse(stdout))
        } catch {
          resolve({ error: 'unreadable picker payload' })
        }
      },
    )
    if (stdinText !== undefined && child.stdin) child.stdin.end(stdinText)
  })
  const chainPairs = entries => entries.map(entry => [String(entry.model), String(entry.reasoning_effort || '')])
  const chainText = chain => chain.map(([model, effort]) => (effort ? `${model}:${effort}` : model)).join(', ')
  const sameChain = (left, right) => JSON.stringify(left) === JSON.stringify(right)
  // Mirror of model_chain_picker.step_head_model: the ring neighbour keeps
  // the head's effort, the tail loses any entry now equal to the new head,
  // and a head the ring does not know is one step from either end.
  const stepHeadModel = (chain, aliases, direction) => {
    if (!chain.length || !aliases.length) return chain
    const [headModel, headEffort] = chain[0]
    const index = aliases.indexOf(headModel)
    const newHead = index >= 0
      ? aliases[(index + direction + aliases.length) % aliases.length]
      : (direction > 0 ? aliases[0] : aliases[aliases.length - 1])
    return [[newHead, headEffort], ...chain.slice(1).filter(([model]) => model !== newHead)]
  }
  // Mirror of model_chain_picker.step_effort: one rung along the ring,
  // clamped; below the ring or absent enters at its low end, `max` holds on
  // + and re-enters at the ring's high end on -.
  const stepEffort = (chain, ring, direction) => {
    if (!chain.length || !ring.length) return chain
    const [headModel, current] = chain[0]
    const low = PICKER_EFFORT_LADDER.indexOf(ring[0])
    const high = PICKER_EFFORT_LADDER.indexOf(ring[ring.length - 1])
    const index = PICKER_EFFORT_LADDER.includes(current) ? PICKER_EFFORT_LADDER.indexOf(current) : low - 1
    let next
    if (index < low) next = low
    else if (index > high) next = direction < 0 ? high : index
    else next = Math.min(Math.max(index + direction, low), high)
    return [[headModel, PICKER_EFFORT_LADDER[next]], ...chain.slice(1)]
  }
  const effortCells = (effort, ring) => {
    const filled = effort === 'max' ? ring.length : ring.indexOf(effort) + 1
    return '■'.repeat(Math.max(0, filled)) + '□'.repeat(Math.max(0, ring.length - Math.max(0, filled)))
  }
  const pickerPayloadIsSound = payload =>
    !!payload && !payload.error &&
    Array.isArray(payload.categories) && payload.categories.length > 0 &&
    Array.isArray(payload.models) && Array.isArray(payload.efforts) &&
    payload.categories.every(row => Array.isArray(row.chain) && row.chain.length > 0 && Array.isArray(row.default_chain))
  const changedChains = state => Object.fromEntries(
    Object.entries(state.chains).filter(([name, chain]) => !sameChain(chain, state.original[name])),
  )
  // A path is shown as written (control characters aside): the host-text
  // allowlist above would strip the `@` and `~` a home directory may carry.
  const pathText = value => String(value ?? '').replace(/\p{C}/gu, '').slice(0, 200)
  const ctrlKey = (key, ch, target) => !!key.ctrl && String(ch || '').toLowerCase() === target
  const padCells = (text, width) => {
    const value = String(text)
    return value.length >= width ? `${value.slice(0, Math.max(0, width - 2))}… ` : value.padEnd(width)
  }
  const pickerDefaultState = () => ({ phase: 'loading', payload: null, chains: {}, original: {}, cursor: 0, message: '' })
  let modelApp = null
  const loadPicker = () => {
    runPickerScript(PICKER_READER).then(payload => updateWidget(modelApp, state => {
      if (!pickerPayloadIsSound(payload)) {
        return { ...state, phase: 'error', message: safeText(payload && payload.error) || 'OMH could not read the model chains' }
      }
      const chains = Object.fromEntries(payload.categories.map(row => [row.category, chainPairs(row.chain)]))
      return { ...state, phase: 'ready', payload, chains, original: { ...chains }, cursor: 0, message: '' }
    }))
  }
  const savePicker = changes => {
    const body = JSON.stringify(Object.fromEntries(
      Object.entries(changes).map(([name, chain]) => [name, chain.map(([model, effort]) => ({ model, reasoning_effort: effort }))]),
    ))
    runPickerScript(PICKER_WRITER, body).then(result => updateWidget(modelApp, state => {
      if (!result || result.error) {
        return { ...state, phase: 'error', message: safeText(result && result.error) || 'OMH could not write the model chains' }
      }
      const count = Array.isArray(result.changed) ? result.changed.length : 0
      return {
        ...state,
        phase: 'saved',
        message: `Saved ${count} categor${count === 1 ? 'y' : 'ies'} to ${homeText(result.path)}`,
      }
    }))
  }
  // The picker's design vocabulary, shared with the CLI picker frame: the
  // cursor row sits on the theme's selection background with `◂ model ▸` and
  // `− effort +` markers showing which keys act on which cell, effort bars
  // are toned by rung, and a row's state is a glyph plus a word.
  const EFFORT_TONE = { low: 'muted', medium: 'ok', high: 'warn', xhigh: 'primary', max: 'label' }
  const STATE_GLYPH = { edited: '●', override: '◆', default: '·' }
  const STATE_TONE = { edited: 'warn', override: 'primary', default: 'muted' }
  const PICKER_KEYS = [['↑↓', 'category'], ['←→', 'head model'], ['−/+', 'effort'], ['d', 'default'], ['⏎', 'save'], ['esc', 'close']]
  const homeText = value => {
    const text = pathText(value)
    const home = process.env.HOME || ''
    return home && text.startsWith(home) ? `~${text.slice(home.length)}` : text
  }
  const clipCells = (text, width) => (text.length <= width ? text : `${text.slice(0, Math.max(0, width - 1))}…`)
  const PickerRule = ({ t, width }) => h(Text, { color: t.color.border }, '─'.repeat(Math.max(1, width)))
  const PickerHint = ({ t }) => h(
    Text,
    { wrap: 'truncate-end' },
    ...PICKER_KEYS.flatMap(([keys, what], index) => [
      h(Text, { bold: true, color: t.color.primary }, `${index ? '   ' : ''}${keys}`),
      h(Text, { color: t.color.muted }, ` ${what}`),
    ]),
  )
  const ModelPickerBody = ({ cols, rows, state, t, width }) => {
    if (state.phase === 'loading') return [h(Text, { color: t.color.muted }, 'reading model chains…')]
    if (state.phase === 'error') {
      return [
        h(Text, { color: t.color.error }, state.message),
        h(Text, { color: t.color.muted }, 'esc closes · `omh model-chains` on a terminal is the same editor'),
      ]
    }
    if (state.phase === 'saved') {
      return [
        h(Text, { color: t.color.ok }, `✓ ${state.message}`),
        h(Text, { color: t.color.muted }, 'New delegations use this order; running children keep theirs.'),
        h(Text, { color: t.color.muted }, '⏎ or esc closes'),
      ]
    }
    const payload = state.payload
    const categories = payload.categories
    const ring = payload.efforts
    const served = Object.fromEntries(payload.models.map(row => [row.alias, !!row.served]))
    const labels = Object.fromEntries(payload.models.map(row => [row.alias, safeText(row.label || row.alias)]))
    const inner = Math.max(40, width - 6)
    // An invalid providers.json yields no document at all: its recorded
    // kinds are dropped and a linked row it excluded counts again, so the
    // providers line is missing the operator's own corrections. One
    // conditional row says so; a valid or absent record adds none.
    const entitlementsStatus = String(payload.entitlements_status || '')
    const ignoredRecord = entitlementsStatus.startsWith('invalid:') ? entitlementsStatus.slice('invalid:'.length).trim() : ''
    // An override document the reader rejects is ignored whole, so every
    // row below reads `default` -- the exact picture of a chain that was
    // never set. One conditional row says the file is there and why it is
    // not in effect; a valid or absent document adds none.
    const documentStatus = String(payload.document_status || '')
    const ignoredDocument = documentStatus.startsWith('invalid:') ? documentStatus.slice('invalid:'.length).trim() : ''
    // Dialog chrome, the providers line, the header, the detail block and
    // the hint take fifteen rows (one more per ignored-file row); the
    // category list gets the rest and windows around the cursor when the
    // terminal is shorter than the twelve categories need.
    const visible = Math.max(3, Math.min(categories.length, rows - 15 - (ignoredRecord ? 1 : 0) - (ignoredDocument ? 1 : 0)))
    const start = Math.max(0, Math.min(state.cursor - Math.floor(visible / 2), categories.length - visible))
    const lines = []
    // The providers the served marks are judged against, each with where it
    // was found (a `hermes auth` login, a config key, a key name, the setup
    // record), so a `!` on a row has its reason one glance up.
    const providers = Array.isArray(payload.providers) ? payload.providers : []
    const providerText = providers.length
      ? providers.map(row => `${safeText(row.id)} (${safeText(row.source)})`).join(' · ')
      : 'none linked to Hermes yet · every model counts as served'
    lines.push(h(
      Text,
      { wrap: 'truncate-end' },
      h(Text, { color: t.color.muted }, `   ${padCells('providers', 11)}`),
      h(Text, { color: providers.length ? t.color.text : t.color.muted }, providerText),
    ))
    if (ignoredRecord) {
      lines.push(h(Text, { color: t.color.warn, wrap: 'truncate-end' }, `   ! providers.json ignored: ${safeText(ignoredRecord)} · any providers it excluded count again`))
    }
    if (ignoredDocument) {
      lines.push(h(Text, { color: t.color.warn, wrap: 'truncate-end' }, `   ! model-chains.json ignored: ${safeText(ignoredDocument)} · every category shows its shipped default`))
    }
    lines.push(h(Text, { color: t.color.muted, wrap: 'truncate-end' }, `   ${padCells('CATEGORY', 19)}${padCells('  HEAD MODEL', 26)}${padCells('  EFFORT', 16)}STATE`))
    if (start > 0) lines.push(h(Text, { color: t.color.muted }, `   ↑ ${start} more`))
    categories.slice(start, start + visible).forEach((row, offset) => {
      const index = start + offset
      const chain = state.chains[row.category]
      const [headModel, headEffort] = chain[0]
      const isCursor = index === state.cursor
      const status = sameChain(chain, state.original[row.category]) ? row.origin : 'edited'
      const unserved = served[headModel] === false
      const label = clipCells(`${labels[headModel] || safeText(headModel)}${unserved ? ' !' : ''}`, 21)
      const tone = t.color[EFFORT_TONE[headEffort] || 'muted']
      const cell = (text, color, extra) => h(Text, { color, ...(isCursor ? { backgroundColor: t.color.selectionBg, bold: true } : {}), ...(extra || {}) }, text)
      lines.push(h(
        Text,
        { wrap: 'truncate-end' },
        cell(isCursor ? ' ▍ ' : '   ', t.color.primary),
        cell(padCells(safeText(row.category), 19), t.color.label),
        cell(isCursor ? '◂ ' : '  ', t.color.primary),
        cell(label, unserved ? t.color.error : t.color.text),
        cell(isCursor ? ' ▸' : '  ', t.color.primary),
        cell(' '.repeat(Math.max(0, 22 - label.length)), t.color.text),
        cell(isCursor ? '− ' : '  ', t.color.primary),
        cell(effortCells(headEffort, ring), isCursor ? t.color.primary : tone),
        cell(isCursor ? ' +' : '  ', t.color.primary),
        cell(` ${padCells(headEffort || '-', 7)}`, tone),
        cell(`${STATE_GLYPH[status] || '·'} ${status}`, t.color[STATE_TONE[status] || 'muted']),
        // The selection bar runs to the dialog's edge, not to the last word.
        // 3 margin + 19 category + 26 model + 16 effort + 2 glyph-and-space.
        cell(' '.repeat(Math.max(0, inner - 66 - status.length)), t.color.text),
      ))
    })
    const hidden = categories.length - start - visible
    if (hidden > 0) lines.push(h(Text, { color: t.color.muted }, `   ↓ ${hidden} more`))
    const current = categories[state.cursor]
    const chain = state.chains[current.category]
    const defaultChain = chainPairs(current.default_chain)
    const changed = Object.keys(changedChains(state)).length
    const headModel = chain[0][0]
    lines.push(h(PickerRule, { t, width: inner }))
    lines.push(h(Text, { wrap: 'truncate-end' }, h(Text, { bold: true, color: t.color.label }, `   ${safeText(current.category)}`), current.purpose ? h(Text, { color: t.color.muted }, ` · ${safeText(current.purpose)}`) : ''))
    lines.push(h(Text, { wrap: 'truncate-end' }, h(Text, { color: t.color.muted }, `   ${padCells('chain', 18)}`), h(Text, { color: t.color.text }, chainText(chain))))
    lines.push(h(Text, { color: t.color.muted, wrap: 'truncate-end' }, `   ${padCells('shipped default', 18)}${sameChain(chain, defaultChain) ? '✓ same as shipped' : chainText(defaultChain)}`))
    lines.push(h(
      Text,
      { color: changed ? t.color.warn : t.color.muted, wrap: 'truncate-end' },
      // The path shows in both states: which store this picker edits is the
      // question a person opens it with when a chain set elsewhere seems
      // not to have taken.
      changed ? `   ${plural(changed, 'unsaved change')} · ⏎ writes ${homeText(payload.path)}` : `   no unsaved changes · ${homeText(payload.path)}`,
    ))
    if (served[headModel] === false) {
      lines.push(h(Text, { color: t.color.error, wrap: 'truncate-end' }, `   ! ${labels[headModel] || safeText(headModel)} is not served by this machine's providers`))
    }
    return lines
  }
  if (Overlay && Dialog) {
    modelApp = defineWidgetApp({
      id: 'omh-model',
      help: 'edit the OMH per-category model chains (the omh model-chains picker)',
      mode: 'modal',
      usage: 'usage: /omh-model',
      init: arg => {
        if (String(arg || '').trim()) return null
        loadPicker()
        return pickerDefaultState()
      },
      reduce: (state, { ch, key }) => {
        const closing = key.escape || ch === 'q' || ch === 'Q' || ctrlKey(key, ch, 'c')
        if (state.phase !== 'ready') {
          if (closing) return null
          return (state.phase === 'saved' || state.phase === 'error') && key.return ? null : state
        }
        if (closing) return null
        const categories = state.payload.categories
        const name = categories[state.cursor].category
        if (key.upArrow || ch === 'k') return { ...state, cursor: (state.cursor - 1 + categories.length) % categories.length }
        if (key.downArrow || ch === 'j') return { ...state, cursor: (state.cursor + 1) % categories.length }
        if (key.return) {
          const changes = changedChains(state)
          if (!Object.keys(changes).length) return null
          savePicker(changes)
          return { ...state, phase: 'saving' }
        }
        const aliases = state.payload.models.map(row => row.alias)
        const chain = state.chains[name]
        let next = chain
        if (key.leftArrow || ch === 'h') next = stepHeadModel(chain, aliases, -1)
        else if (key.rightArrow || ch === 'l') next = stepHeadModel(chain, aliases, 1)
        else if (ch === '-' || ch === '_') next = stepEffort(chain, state.payload.efforts, -1)
        else if (ch === '+' || ch === '=') next = stepEffort(chain, state.payload.efforts, 1)
        else if (ch === 'd' || ch === 'D') next = chainPairs(categories[state.cursor].default_chain)
        else return state
        return { ...state, chains: { ...state.chains, [name]: next } }
      },
      render: ({ cols, rows, state, t }) => {
        const width = Math.min(100, Math.max(56, cols - 4))
        return h(
          Overlay,
          { backdrop: true },
          h(
            Dialog,
            {
              hint: state.phase === 'ready'
                ? h(PickerHint, { t })
                : (state.phase === 'saving' ? 'writing…' : undefined),
              title: '⚚ OMH · Model chains',
              width,
            },
            ...ModelPickerBody({ cols, rows, state, t, width }),
          ),
        )
      },
    })
  }

  openWidget(todoApp, todoApp.init(''))
  openWidget(app, app.init(''))
  // Render quiescence is what makes the docks drag-copyable: every repaint of
  // these lines clears an in-progress terminal selection over them, so an
  // unchanged snapshot must produce NO updateWidget call at all. The reader
  // freezes per-row elapsed for finished subagents precisely so a lingering
  // done state serializes identically poll after poll.
  //
  // A RUNNING delegation defeats a plain byte-compare, though: elapsed,
  // tok/s, cache% and cost drift on nearly every 2s poll, so the dock would
  // still repaint every poll for the whole wave. The compare is therefore
  // two-tier. Structural changes — a row appearing, a state transition, the
  // action text, the todo checklist — repaint immediately. Metric-only drift
  // repaints at most once per METRICS_REPAINT_MS, leaving long byte-stable
  // windows in which the dock behaves like plain text under a drag.
  const METRICS_REPAINT_MS = 30_000
  const VOLATILE_KEYS = new Set([
    'cache_hit_percentage',
    'context_percentage',
    'cost_usd',
    'elapsed_seconds',
    'observed_at',
    'tokens',
    'tokens_per_second',
    'tool_count',
    'turn_count',
    // The exact in-flight age ticks on every poll while live; the liveness
    // transition itself (open_call_count, live) stays OUT of this set on
    // purpose -- that boolean flip and count change are structural, and must
    // repaint promptly rather than wait out the metrics throttle.
    'oldest_open_elapsed_seconds',
    // The reader-computed todo stall age ticks every poll while a plan sits
    // idle; same reasoning as oldest_open_elapsed_seconds above -- it must
    // not force a repaint every 2s, only advance on the metrics cadence.
    'updated_age_seconds',
  ])
  const structuralKey = payload =>
    JSON.stringify(payload, (key, value) => (VOLATILE_KEYS.has(key) ? undefined : value))
  let lastSnapshot = ''
  let lastStructural = ''
  let lastPaintAt = 0
  const applySnapshot = payload => {
    if (!payload) return
    const serialized = JSON.stringify(payload)
    if (serialized === lastSnapshot) return
    const structural = structuralKey(payload)
    if (structural === lastStructural && Date.now() - lastPaintAt < METRICS_REPAINT_MS) return
    lastSnapshot = serialized
    lastStructural = structural
    lastPaintAt = Date.now()
    // Both docks paint from the one snapshot pass, so the quiet-dock
    // compare above gates them together and the two frame rules never
    // disagree about payload freshness.
    const apply = state => ({ ...state, payload, receivedAt: Date.now(), tick: state.tick + 1 })
    updateWidget(todoApp, apply)
    updateWidget(app, apply)
  }
  const timerKey = Symbol.for('omh.hermes-tui-widget.refresh')
  const generationKey = Symbol.for('omh.hermes-tui-widget.generation')
  const generation = (globalThis[generationKey] || 0) + 1
  globalThis[generationKey] = generation
  const schedule = () => {
    if (generation !== globalThis[generationKey]) return
    globalThis[timerKey] = setTimeout(async () => {
      const payload = await readHud()
      if (generation !== globalThis[generationKey]) return
      applySnapshot(payload)
      schedule()
    }, 2000)
    globalThis[timerKey].unref?.()
  }
  clearTimeout(globalThis[timerKey])
  void readHud().then(payload => {
    if (generation !== globalThis[generationKey]) return
    applySnapshot(payload)
  })
  schedule()
}
