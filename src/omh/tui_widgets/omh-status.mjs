import { execFile } from 'node:child_process'

export default function register(sdk) {
  const { Box, Text, defineWidgetApp, h, openWidget, updateWidget } = sdk
  const SPINNER_FRAMES = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']
  const HOME = process.env.OMH_HOME || `${process.env.HOME}/.omh`
  const HERMES_HOME = process.env.HERMES_HOME || `${process.env.HOME}/.hermes`
  const READER_ENV = {
    HOME: process.env.HOME || '',
    HERMES_HOME,
    OMH_HOME: HOME,
  }
  for (const key of ['LANG', 'LC_ALL', 'LC_CTYPE', 'SYSTEMROOT', 'WINDIR']) {
    if (process.env[key]) READER_ENV[key] = process.env[key]
  }
  const READER = [
    'import json,os,sys',
    "sys.path.insert(0, os.path.join(os.environ['HERMES_HOME'], 'plugins'))",
    'from omh.runtime_reader import read_omh_hud',
    "print(json.dumps(read_omh_hud(os.environ.get('OMH_HOME'), os.environ.get('HERMES_HOME'))))",
  ].join(';')

  const safeText = value => String(value ?? '').replace(/[^\p{L}\p{N} .:/_·|+\-]/gu, '').slice(0, 96)

  // Text, not chrome. The owner's direction after living with the bordered
  // cards: the OMH surface should read like the host's own status line
  // (` ─ ready │ gpt 5.6 sol │ … `) and like oh-my-claudecode's HUD -- dense
  // text in the TUI's idiom, not a boxed widget that announces itself.
  // Colours still resolve only through the active theme, never literals.
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
    const approximate = rows.some(row => row.cost_approximate)
    const main = Array.isArray(payload.maestro?.rows) ? payload.maestro.rows[0] : null
    const ctx = main && Number.isFinite(main.context_percentage)
      ? main.context_percentage
      : rows.map(row => row.context_percentage).filter(Number.isFinite)[0]
    return {
      // Subscription-billed hosts record no per-call cost; the reader's
      // token-derived approximation carries a `~`, and a true zero with no
      // approximation renders nothing (a constant $0.000 read as broken).
      cost: cost > 0 ? `${approximate ? '~' : ''}$${cost.toFixed(3)}` : '',
      ctx: Number.isFinite(ctx) ? `ctx ${ctx}%` : 'ctx --',
    }
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
    execFile(
      __OMH_PYTHON_EXECUTABLE__,
      ['-I', '-c', READER],
      {
        encoding: 'utf8',
        env: READER_ENV,
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

  const truncateCells = (value, limit) => {
    const text = safeText(value)
    if (cellWidth(text) <= limit) return text
    let output = ''
    for (const char of Array.from(text)) {
      if (cellWidth(output + char) > Math.max(0, limit - 1)) break
      output += char
    }
    return `${output}…`
  }

  const elapsedText = value => {
    if (!Number.isFinite(value)) return ''
    const seconds = Math.max(0, Math.floor(value))
    if (seconds < 60) return `${seconds}s`
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`
    return `${Math.floor(seconds / 3600)}h ${String(Math.floor(seconds / 60) % 60).padStart(2, '0')}m`
  }

  const metricSegment = (kind, text) => ({ kind, text })
  // Only observed values render. The old permanent not-collected labels on
  // cache/ctx were honest but unresolvable for Hermes-native children — the
  // host never records a child's context percentage — and read as a fixable
  // problem ('서브에이전트 트리거는 다시 해야하나?'). Absence of a claim is
  // just as honest, and the header's `ctx --` still marks the session gap.
  const observedPercent = (label, value) =>
    Number.isFinite(value) ? `${label} ${value}%` : ''

  const activityLayout = (row, columns, main, extraSeconds) => {
    const state = safeText(row.state) || 'running'
    const stateText = columns < 100 ? ({ running: 'run', blocked: 'block', failed: 'fail' })[state] || state : state
    const taskId = truncateCells(safeText(row.task_id) || safeText(row.role) || 'agent', 8).padEnd(8)
    const model = [safeText(row.model), safeText(row.effort)].filter(Boolean).join(':')
    const category = safeText(row.category)
    const route = category ? `category:${category}${model ? `(${model})` : ''}` : model
    const turn = Number.isFinite(row.turn_count) ? `turn ${row.turn_count}` : ''
    const tools = Number.isFinite(row.tool_count) ? `${row.tool_count} tools` : ''
    const turnTools = turn && tools ? `${turn} (${tools})` : turn || tools
    const optional = [
      metricSegment('route', route),
      metricSegment('fallback', Number.isFinite(row.fallback_count) && row.fallback_count > 0 ? `fallback:${row.fallback_count}` : ''),
      metricSegment('turn', turnTools),
      // A subscription-billed host records no per-call cost, so the reader
      // supplies a token-derived approximation flagged cost_approximate —
      // rendered with a `~` so it never reads as billing truth. A true zero
      // with no approximation renders nothing (the old permanent $0.0000
      // read as broken).
      metricSegment(
        'cost',
        Number.isFinite(row.cost_usd) && row.cost_usd > 0
          ? `${row.cost_approximate ? '~' : ''}$${row.cost_usd.toFixed(4)}`
          : '',
      ),
      metricSegment('rate', Number.isFinite(row.tokens_per_second) ? `${Math.round(row.tokens_per_second)} tok/s` : ''),
      metricSegment('cache', observedPercent('cache', row.cache_hit_percentage)),
      metricSegment('context', observedPercent('ctx', row.context_percentage)),
    ].filter(segment => segment.text)
    const running = !row.state || row.state === 'running'
    // A running row's elapsed ticks in real time: the snapshot's value plus
    // the seconds since it arrived, re-rendered by the animation clock.
    // Finished rows keep the frozen precise value.
    const elapsed = running ? (row.elapsed_seconds || 0) + extraSeconds : row.elapsed_seconds
    const required = [
      metricSegment('cache', observedPercent('cache', row.cache_hit_percentage)),
      metricSegment('context', observedPercent('ctx', row.context_percentage)),
      metricSegment('state', stateText),
      metricSegment('elapsed', elapsedText(elapsed)),
    ].filter(segment => segment.text)
    optional.splice(-2)
    const prefix = `${taskId} `
    const separator = '  ·  '
    const budget = Math.max(24, columns - 4)
    const minimumAction = columns >= 120 ? 26 : columns >= 90 ? 18 : 10
    const segments = [...optional, ...required]
    while (segments.length > required.length) {
      const metadata = segments.map(item => item.text).join(separator)
      if (cellWidth(prefix) + minimumAction + cellWidth(separator) + cellWidth(metadata) <= budget) break
      segments.splice(segments.length - required.length - 1, 1)
    }
    const metadata = segments.map(segment => segment.text).join(separator)
    const actionBudget = Math.max(
      8,
      budget - cellWidth(prefix) - cellWidth(metadata) - (metadata ? cellWidth(separator) : 0),
    )
    return {
      action: truncateCells(row.action, actionBudget),
      metadata,
      segments,
      taskId: main ? 'MAIN'.padEnd(8) : taskId,
    }
  }

  function ActivityRow({ columns, extraSeconds, frame, main, row, t }) {
    const layout = activityLayout(row, columns, main, extraSeconds)
    const blocked = row.state === 'blocked' || row.state === 'failed'
    const done = row.state === 'done'
    const marker = blocked ? '▲' : done ? '✓' : SPINNER_FRAMES[frame % SPINNER_FRAMES.length]
    const statusColor = blocked ? t.color.error : t.color.ok
    return h(
      Text,
      { wrap: 'truncate-end' },
      h(Text, { color: blocked ? t.color.error : done ? t.color.ok : t.color.warn }, `${marker} `),
      h(Text, { color: t.color.muted }, `${layout.taskId} `),
      h(Text, { color: t.color.text }, layout.action),
      layout.metadata ? h(Text, { color: t.color.muted }, '  ·  ') : null,
      ...layout.segments.map((segment, index) =>
        h(
          Text,
          {
            color: segment.kind === 'state'
              ? statusColor
              : segment.kind === 'route'
                ? t.color.label
                : t.color.muted,
            key: `${segment.kind}-${index}`,
          },
          `${index ? '  ·  ' : ''}${segment.text}`,
        )
      ),
    )
  }

  function ActivityRows({ columns, extraSeconds, frame, mainRows, rows, t }) {
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
          row,
          t,
        })
      ),
      ...rows.map((row, index) =>
        h(ActivityRow, {
          columns,
          extraSeconds,
          frame,
          key: `${safeText(row.task_id)}-${index}`,
          row,
          t,
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
    const viewportBudget = Math.max(1, viewportRows - 5)
    const agentBudget = Math.min(
      Math.max(Math.max(5 - mainRows.length, 1), runningAgents),
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
        // live session metrics on it. Cost and ctx come from sessionMetrics
        // above -- observed values or "--", never fabricated totals.
        h(Text, { bold: true, color: t.color.primary }, '⚚ [OMH]'),
        version ? h(Text, { color: t.color.muted }, ` v${version}`) : null,
        h(Text, { color: t.color.border }, SEPARATOR),
        h(Text, { color: active ? t.color.warn : t.color.ok }, hudStateLabel(active, agents)),
        h(Text, { color: t.color.muted }, `${metrics.cost ? ` • ${metrics.cost}` : ''} • ${metrics.ctx}`),
        // Shift+Tab yolo state, as last observed by the plugin's turn and
        // tool-call hooks (the host keeps the flag in process memory only).
        // ON warns in the theme's yellow; OFF rests in the label blue —
        // colours resolve through the active theme, never literals. An
        // unobserved or stale ledger renders nothing rather than a guess.
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
      ),
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

  function TodoPanel({ columns, state, t }) {
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
      return h(FrameRule, { columns, payload, t })
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
        ),
        h(FrameRule, { columns, payload, t }),
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
    const start = total > TODO_DISPLAY_ROWS ? Math.min(anchor, total - TODO_DISPLAY_ROWS) : 0
    const end = Math.min(total, start + TODO_DISPLAY_ROWS)
    const groups = []
    for (const item of shown.slice(start, end)) {
      const phase = safeText(item.phase)
      const last = groups[groups.length - 1]
      // A subtask with no phase of its own continues its parent's group.
      if (last && (last.phase === phase || (!phase && depthOf(item) > 0))) last.items.push(item)
      else groups.push({ phase, items: [item] })
    }
    const itemLabel = item =>
      `${Object.hasOwn(markers, item.state) ? markers[item.state] : '[ ]'} ${truncateCells(item.text, budget)}`
    const itemProps = item => ({
      bold: item.state === 'active',
      color: item.state === 'active' ? t.color.ok : item.state === 'done' ? t.color.muted : t.color.text,
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
    // The active item's text carries the colour wave; its marker, indent and
    // every other item stay static.
    const itemNode = (item, indent) =>
      item.state === 'active'
        ? h(
            Text,
            {},
            h(Text, itemProps(item), `${indent}${markers.active} `),
            h(ShimmerText, { color: t.color.ok, t, text: truncateCells(item.text, budget) }),
          )
        : h(Text, itemProps(item), `${indent}${itemLabel(item)}`)
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
      h(
        Text,
        { wrap: 'truncate-end' },
        h(Text, { bold: true, color: t.color.primary }, '[Plan]'),
        title ? h(Text, { color: t.color.muted }, ` ${title}`) : null,
        h(Text, { color: t.color.border }, SEPARATOR),
        h(Text, { color: t.color.warn }, `${counts.done ?? 0}/${counts.total ?? 0}`),
        phaseCount > 1 ? h(Text, { color: t.color.muted }, ` · ${phaseCount} phases`) : null,
        hasActive ? h(PlanPulse, { t }) : null,
      ),
      ...rows,
      h(FrameRule, { columns, payload, t }),
    )
  }

  // The upper half of the composer frame — the todo panel's closing line.
  // It also carries the parallel-shot badge: a fresh concurrent tool-call
  // batch (observed by the pre_tool_call hook) reads meaningfully only near
  // the transcript's collapsed "Tool calls (N)" group, and that group is
  // host-owned rendering OMH cannot decorate — this rule in the top dock is
  // the closest OMH-owned surface to it, and the badge sat unread down in
  // the bottom dock ('하단에 뜨면 의미가없지'). Idle bursts render a plain
  // rule, so the frame stays byte-stable outside the 90s freshness window.
  function FrameRule({ columns, payload, t }) {
    const width = Math.max(1, columns - 2)
    const shot = payload.parallel_shot
    if (!shot || shot.status !== 'observed') {
      return h(Rule, { columns, t })
    }
    const label = ` parallel shot ×${Number(shot.size) || 0} `
    const lead = 3
    return h(
      Text,
      { wrap: 'truncate-end' },
      h(Text, { color: t.color.border }, '─'.repeat(lead)),
      h(Text, { color: t.color.label }, label),
      h(Text, { color: t.color.border }, '─'.repeat(Math.max(1, width - lead - cellWidth(label)))),
    )
  }

  const sharedInit = () => ({ payload: null, receivedAt: 0, tick: 0 })
  const sharedReduce = (state, input) =>
    input.kind === 'snapshot'
      ? { ...state, payload: input.payload, receivedAt: Date.now(), tick: state.tick + 1 }
      : state

  // The todo panel reads above the input, where the owner always looked for
  // it; the panel itself ends with the FrameRule that tops the composer
  // frame, so the dock never renders taller than the plan plus one line.
  const todoApp = defineWidgetApp({
    id: 'omh-todo',
    help: 'OMH plan todo and the composer frame above the prompt input',
    mode: 'ambient',
    zone: 'dock-top',
    init: sharedInit,
    reduce: sharedReduce,
    render: ({ cols, state, t }) => {
      if (!state.payload || state.payload.error || state.payload.privacy !== 'metadata_only') return null
      return h(TodoPanel, { columns: Math.max(20, cols), state, t })
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
