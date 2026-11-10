"""The Hermes Desktop half of the bundle: backend route, renderer file, doctor.

Hermes Desktop loads `desktop/plugin.js` uncompiled through its disk-plugin
door and imports `dashboard/plugin_api.py` by path inside the gateway process,
so neither file is reached by the bundle's own package machinery. These tests
drive both the way the host does: the backend's pure functions without FastAPI
(the host's dependency, not OMH's), and the renderer file under node with the
SDK, React and JSX shims replaced by recording fakes, the way
`tests/test_tui_widget_pack.py` drives the TUI widget: the pane's words, the
status item's tokens, the stylesheet's lifetime and the formatters' answers.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from _standalone_bundle import bundle_dir
from omh.install.plugin_pack import install_plugin_bundle
from omh.maintenance.doctor import DESKTOP_HALF_FILES, doctor_ok, run_doctor
from omh.paths import resolve_paths
from omh.plugin_bundle.omh import runtime_paths, runtime_reader, subagent_graph
from omh.plugin_bundle.omh.dashboard import plugin_api
from _module_patch import patch_modules
from _delegation_graphs import nested, owner_mock, parallel
from _delegation_state import PARENT, homes
from omh.tui import dag_block

NODE = shutil.which("node")

BUNDLE = bundle_dir()
PLUGIN_JS = BUNDLE / "desktop" / "plugin.js"
MANIFEST = BUNDLE / "dashboard" / "manifest.json"


# The specifiers Hermes' runtime loader resolves for a disk plugin
# (`apps/desktop/src/sdk/runtime.ts::sdkImportMap`), of which this plugin
# uses three; anything else fails the loader's import fence.
ALLOWED_IMPORTS = frozenset({"@hermes/plugin-sdk", "react", "react/jsx-runtime"})

# The loader's own specifier pattern (`runtime-loader.ts::importSpecifierRe`),
# so the fence is measured with the host's reading of the file, not another.
IMPORT_SPECIFIER = re.compile(r"""(from\s*|import\s*\(\s*|import\s+)(['"])([^'"]+)\2""")

# A hex colour literal; the pane's stylesheet resolves every colour through
# the app's theme tokens and must carry none.
HEX_COLOUR = re.compile(r"#[0-9a-fA-F]{3,8}\b")

LOADER_NOT_OBSERVED = {
    "observed": False,
    "ok": False,
    "reason": "hermes_not_installed",
    "registered_tools": [],
    "registered_hooks": [],
}

# Stands in for `@hermes/plugin-sdk`: the names the plugin imports, each
# answering from `globalThis.__omh` so a scenario sets the state and a render
# reads it back. Presentational components expand to their text so the pane's
# words are in the tree, as on screen; `useQuery` records the options it was
# handed; `host.revealPane` records the pane it was asked to reveal.
SDK_SHIM = r"""
export const PANES_AREA = 'panes'
export const STATUSBAR_AREAS = { left: 'statusBar.left', right: 'statusBar.right' }
export const Tip = ({ label, children }) => { globalThis.__omh.tips.push(label); return children }
export const Badge = ({ children, variant }) => { globalThis.__omh.badges.push({ text: children, variant }); return children }
export const PanelEmpty = ({ title, description }) => [title, description]
export const StatusDot = props => { globalThis.__omh.dots.push(props); return null }
export const Skeleton = () => null
export const GlyphSpinner = () => '⠋'
export const host = {
  state: {
    gateway: { get: () => globalThis.__omh.gateway },
    busy: { get: () => globalThis.__omh.busy },
    focusedStoredSessionId: { get: () => globalThis.__omh.stored },
    model: { get: () => globalThis.__omh.model },
    focusedSessionId: { get: () => globalThis.__omh.focused },
    focusedUsage: { get: () => globalThis.__omh.usage }
  },
  request: (method, params) => { globalThis.__omh.requests.push([method, params]); return Promise.resolve(globalThis.__omh.breakdown) },
  revealPane: paneId => { globalThis.__omh.revealed.push(paneId) },
  notify: input => { globalThis.__omh.notified.push(input) }
}
export const useValue = atom => atom.get()
export function useQuery(options) {
  if (options.queryKey[1] === 'context') {
    globalThis.__omh.contextQuery = options
    return globalThis.__omh.context
  }
  if (options.queryKey[1] === 'stats') {
    globalThis.__omh.statsQuery = options
    return globalThis.__omh.stats
  }
  globalThis.__omh.lastQuery = options
  return globalThis.__omh.query
}
"""

# Stands in for `react`: the two hooks the plugin uses, inert under a
# single synchronous render.
REACT_SHIM = r"""
export const useState = initial => [typeof initial === 'function' ? initial() : initial, () => {}]
export const useEffect = () => {}
"""

# Stands in for `react/jsx-runtime`: function components expand in place so
# their text is in the tree, as on screen; host elements become plain nodes.
JSX_SHIM = r"""
const expand = (type, props, key) => (typeof type === 'function' ? type(props || {}) : { type, props: props || {}, key })
export const jsx = expand
export const jsxs = expand
"""

# Registers the rewritten plugin against a recording context and a recording
# document, renders every contribution under each scenario, then disposes the
# registration; reports the text each render produced, the query options in
# force, the REST path the query function asked for, the stylesheet events,
# the pane the status item reveals on click, and the formatters' answers.
HARNESS = r"""
import { readFileSync } from 'node:fs'
import { pathToFileURL } from 'node:url'
const [pluginPath, scenariosPath, formatterCasesPath] = process.argv.slice(2)
globalThis.__omh = {
  gateway: 'open', stored: null, model: '', usage: null, focused: '', breakdown: undefined, requests: [],
  query: { data: undefined, error: null }, lastQuery: null, context: { data: undefined, error: null }, contextQuery: null,
  stats: { data: undefined, error: null }, statsQuery: null,
  revealed: [], notified: [], tips: [], dots: [], badges: []
}
const styleEvents = []
let styleCss = ''
globalThis.document = {
  head: { append: el => { styleEvents.push(`append:${el.id}`); styleCss = el.textContent } },
  getElementById: () => null,
  createElement: tag => ({ tagName: tag.toUpperCase(), id: '', textContent: '', remove() { styleEvents.push(`remove:${this.id}`) } })
}
const mod = await import(pathToFileURL(pluginPath).href)
const plugin = mod.default
const contributions = []
const restCalls = []
const disposers = []
const eventHandlers = []
const ctx = {
  source: 'plugin:omh',
  rest: path => { restCalls.push(path); return Promise.resolve({}) },
  register: c => { contributions.push(c); return () => {} },
  registerMany: cs => { cs.forEach(c => contributions.push(c)); return () => {} },
  onDispose: fn => { disposers.push(fn) },
  onEvent: (type, fn) => { eventHandlers.push([type, fn]); return () => {} },
  socket: () => () => {}
}
plugin.register(ctx)
const styleEventsAfterRegister = [...styleEvents]
// A route is one ellipsized cell; join its children into the identity it names.
const isRoute = node => node.props && typeof node.props.className === 'string' && node.props.className.includes('omh-agent-route')
const isSeparator = node => node.props && typeof node.props.className === 'string' && node.props.className.includes('omh-agent-sep')
const text = node =>
  node === null || node === undefined || node === false
    ? []
    : Array.isArray(node)
      ? node.flatMap(text)
      : typeof node === 'string'
        ? [node]
        : typeof node === 'object'
          ? isSeparator(node)
            ? []
            : isRoute(node)
              ? [text(node.props.children).join('')]
              : text(node.props && node.props.children)
          : [String(node)]
const collect = (node, predicate, out = []) => {
  if (!node || typeof node !== 'object') return out
  if (Array.isArray(node)) { node.forEach(child => collect(child, predicate, out)); return out }
  if (node.props && predicate(node.props)) out.push(text(node).join(''))
  return collect(node.props && node.props.children, predicate, out)
}
// Notes rendered INSIDE a struck-through label would inherit the strike.
const notesUnderLabel = (node, inside = false, out = []) => {
  if (!node || typeof node !== 'object') return out
  if (Array.isArray(node)) { node.forEach(child => notesUnderLabel(child, inside, out)); return out }
  const cls = node.props && typeof node.props.className === 'string' ? node.props.className : ''
  if (inside && cls.includes('omh-pane-item-note')) out.push(text(node).join(''))
  return notesUnderLabel(node.props && node.props.children, inside || cls.includes('omh-pane-item-label'), out)
}
const structures = (node, out = []) => {
  if (!node || typeof node !== 'object') return out
  if (Array.isArray(node)) { node.forEach(child => structures(child, out)); return out }
  const props = node.props || {}
  if (props.className) out.push({ className: props.className, text: text(node).join(''), state: props['data-state'], done: props['data-done'], live: props['data-live'], style: props.style,
    cells: (Array.isArray(props.children) ? props.children : [props.children]).filter(child => child && child.props).map(child => ({ className: child.props.className, text: text(child).join('') })) })
  return structures(props.children, out)
}
const findClick = node => {
  if (!node || typeof node !== 'object') return null
  if (Array.isArray(node)) { for (const child of node) { const hit = findClick(child); if (hit) return hit } return null }
  if (node.props && typeof node.props.onClick === 'function') return node.props.onClick
  return findClick(node.props && node.props.children)
}
const scenarios = JSON.parse(readFileSync(scenariosPath, 'utf8'))
// The gateway events a scenario's chat saw, each read at the clock the scenario names.
const replay = scenario => {
  const realNow = Date.now
  try {
    for (const [type, session, text, at, turnId] of scenario.events || []) {
      Date.now = () => at
      for (const [kind, fn] of eventHandlers) if (kind === type) fn({ type, session_id: session, payload: { text, turn_id: turnId } })
    }
  } finally {
    Date.now = realNow
  }
}
const koreanScenarios = ['catches_and_lanes', 'settled_lanes', 'maestro_and_board', 'maestro_unnamed', 'gateway_closed', 'open_with_payload', 'failed_lane', 'dag_cards', 'fanout_cards', 'usage_board']
const renders = {}
for (const [name, scenario] of Object.entries(scenarios)) {
  globalThis.__omh.gateway = scenario.gateway
  globalThis.__omh.busy = scenario.busy === true
  globalThis.__omh.stored = scenario.stored
  globalThis.__omh.model = scenario.model || ''
  globalThis.__omh.usage = scenario.usage || null
  globalThis.__omh.focused = scenario.focused || ''
  globalThis.__omh.breakdown = scenario.breakdown
  globalThis.__omh.query = {
    data: scenario.data,
    error: scenario.errorMessage ? new Error(scenario.errorMessage) : null
  }
  globalThis.__omh.context = { data: scenario.breakdown, error: null }
  globalThis.__omh.stats = { data: scenario.stats, error: null }
  globalThis.__omh.lastQuery = null
  globalThis.__omh.contextQuery = null
  globalThis.__omh.statsQuery = null
  globalThis.__omh.requests = []
  replay(scenario)
  globalThis.__omh.revealed = []
  globalThis.__omh.tips = []
  globalThis.__omh.dots = []
  globalThis.__omh.badges = []
  restCalls.length = 0
  const byId = {}
  let clicked = []
  let alternates = []
  let strikeLeaks = []
  let structure = []
  for (const c of contributions) {
    const tree = c.render()
    byId[c.id] = text(tree)
    if (c.id === 'hud') {
      alternates = collect(tree, props => props['data-alt'] === 'true')
      strikeLeaks = notesUnderLabel(tree)
      structure = structures(tree)
    }
    if (c.id === 'status') {
      const onClick = findClick(tree)
      if (onClick) onClick()
      clicked = [...globalThis.__omh.revealed]
    }
  }
  const query = globalThis.__omh.lastQuery
  await query.queryFn()
  const asked = globalThis.__omh.contextQuery
  if (asked) await asked.queryFn()
  const counted = globalThis.__omh.statsQuery
  const sentinel = { previous: true }
  renders[name] = {
    byId,
    refetchInterval: query.refetchInterval,
    enabled: query.enabled,
    queryKey: query.queryKey,
    keepsPreviousData: typeof query.placeholderData === 'function' && query.placeholderData(sentinel, { queryKey: query.queryKey }) === sentinel,
    dropsOtherChat: typeof query.placeholderData === 'function' && query.placeholderData(sentinel, { queryKey: [...query.queryKey.slice(0, 2), 'other-chat', ''] }) === undefined,
    context: asked
      ? {
          enabled: asked.enabled,
          queryKey: asked.queryKey,
          requests: [...globalThis.__omh.requests],
          keepsOwnChat: asked.placeholderData(sentinel, { queryKey: asked.queryKey }) === sentinel,
          dropsOtherChat: asked.placeholderData(sentinel, { queryKey: [...asked.queryKey.slice(0, 2), 'other-chat'] }) === undefined
        }
      : null,
    stats: counted ? { enabled: counted.enabled, queryKey: counted.queryKey } : null,
    restCalls: [...restCalls],
    revealed: clicked,
    tips: [...globalThis.__omh.tips],
    alternates,
    strikeLeaks,
    structure,
    dots: [...globalThis.__omh.dots],
    badges: [...globalThis.__omh.badges],
    summary: scenario.data ? mod.stateSummary(scenario.data) : null,
    active: scenario.data && scenario.data.active,
    runtime: scenario.data && scenario.data.runtime,
    tally: scenario.data ? mod.agentTally(scenario.data) : null,
    statusDetail: (mod.statusItem({ gateway: scenario.gateway, data: scenario.data, error: globalThis.__omh.query.error }) || {}).detail || ''
  }
}
const formatterCases = JSON.parse(readFileSync(formatterCasesPath, 'utf8'))
const formatters = {}
const local = {
  // The events of one window, in order, folded into a fresh clock: which of them ended a wait, and the waits kept.
  ttftWaits: events => {
    const clock = mod.newTurnClock()
    const ended = events.map(([type, session, text, now, turnId]) => mod.noteTurnEvent(clock, type, session, text, now, turnId))
    return [ended, { ...clock.turns }]
  },
  // The same fold: the chats a start is still pending for once the events are in.
  ttftPending: events => {
    const clock = mod.newTurnClock()
    events.forEach(([type, session, text, now, turnId]) => mod.noteTurnEvent(clock, type, session, text, now, turnId))
    return Object.keys(clock.started).sort()
  },
  // A lane record as the backend sends it, read into the detail's prompt legend.
  laneLegend: record => mod.usageLegend(mod.laneUsage(record)),
  koreanStates: states => states.map(state => [state, mod.stateWord(state, 'en'), mod.stateWord(state, 'ko')]),
  // The layers a run folds under a mode, the person's own folds and an open lane.
  foldsOf: (graph, mode, overrides, pick) => [...mod.foldedLayers(mod.dagModel(graph), mode, overrides || {}, pick || '')].sort((a, b) => a - b),
  // The edges drawn once `folded` layers stand behind their chips.
  // A graph the reader cut by layer: each layer's lanes, what it holds counted whole, and what `auto` folds.
  cutLayers: graph => {
    const dag = mod.dagModel(graph)
    return {
      layers: dag.layers,
      summaries: dag.layers.map((ids, at) => {
        const summary = mod.layerSummary(dag, at)
        return [summary.count, summary.hidden, summary.state]
      }),
      folds: [...mod.foldedLayers(dag, 'auto', {}, '')].sort((a, b) => a - b)
    }
  },
  // The query key the status item and the pane each poll under once the DAG holds layers open: one key, one read.
  sharedOpenKeys: (session, layers) => {
    globalThis.__omh.gateway = 'open'
    globalThis.__omh.stored = session
    globalThis.__omh.query = { data: undefined, error: null }
    mod.setDagOpen(`${session}|`, layers)
    const keys = contributions.map(c => { c.render(); return [c.id, globalThis.__omh.lastQuery.queryKey] })
    mod.setDagOpen('', '')
    return keys
  },
  elidedEdges: graph => mod.dagModel(graph).edges,
  foldedEdges: (graph, folded) => {
    const dag = mod.dagModel(graph)
    return mod.foldedView(dag, new Set(folded), dag.edges, null).edges.map(edge => `${edge.from}>${edge.to}`)
  }
}
for (const [name, cases] of Object.entries(formatterCases)) {
  formatters[name] = cases.map(args => {
    const answer = (local[name] || mod[name])(...args)
    return answer && typeof answer === 'object' && Object.hasOwn(answer, 'text') ? answer.text : answer
  })
}
// Force one absent Korean message without inventing a production-only key.
const savedKo = mod.KO.stateRunning
delete mod.KO.stateRunning
const englishFallback = mod.t('stateRunning', { count: 2 }, 'ko')
mod.KO.stateRunning = savedKo
for (const dispose of disposers) dispose()
const report = {
  plugin: { id: plugin.id, name: plugin.name, description: plugin.description, defaultEnabled: plugin.defaultEnabled },
  contributions: contributions.map(c => ({ id: c.id, area: c.area, title: c.title, order: c.order, data: c.data })),
  renders,
  formatters,
  englishFallback,
  style: { afterRegister: styleEventsAfterRegister, afterDispose: [...styleEvents], css: styleCss }
}
// The same pane on a host whose app language is Korean: a translator shaped
// like the app's plugin i18n (`register` the bundles, `t` answers the active
// locale, English, then the key). Runs after the style report is taken.
const koContributions = []
const koDisposers = []
plugin.register({
  ...ctx,
  register: c => { koContributions.push(c); return () => {} },
  registerMany: cs => { cs.forEach(c => koContributions.push(c)); return () => {} },
  onDispose: fn => { koDisposers.push(fn) },
  i18n: {
    register(bundles) { this.bundles = bundles; return () => {} },
    t(key, vars) {
      const value = this.bundles.ko[key] ?? this.bundles.en[key] ?? key
      return typeof value === 'function' ? value(vars) : value
    },
    onLocaleChange: () => () => {}
  }
})
report.korean = {}
for (const name of koreanScenarios) {
  const scenario = scenarios[name]
  globalThis.__omh.gateway = scenario.gateway
  globalThis.__omh.busy = false
  globalThis.__omh.stored = scenario.stored
  globalThis.__omh.query = { data: scenario.data, error: null }
  globalThis.__omh.usage = scenario.usage || null
  globalThis.__omh.focused = scenario.focused || ''
  globalThis.__omh.context = { data: scenario.breakdown, error: null }
  globalThis.__omh.stats = { data: scenario.stats, error: null }
  globalThis.__omh.tips = []
  replay(scenario)
  const byId = {}
  for (const c of koContributions) byId[c.id] = text(c.render())
  report.korean[name] = { byId, tips: [...globalThis.__omh.tips] }
}
for (const dispose of koDisposers) dispose()
process.stdout.write(`${JSON.stringify(report)}\n`, () => process.exit(0))
"""

# One established plan across two phases, one running subagent on an
# inherited route with its metrics, one finished subagent on a category
# route with an exact cost; the host's own session model beside them.
RUNNING_ROW = {
    "scope": "session",
    "state": "running",
    "task_id": "a1b2c3d4",
    "role": "hermes-native",
    "action": "Implement the parser at /Users/dev/projects/oh-my-hermes/src/utils/duration.py",
    "model": "anthropic/claude-opus-5",
    "effort": "high",
    "category": "inherit",
    "tokens": 12300,
    "elapsed_seconds": 242,
    "tokens_per_second": 85,
    "cache_hit_percentage": 72,
    "turn_count": 3,
    "tool_count": 12,
    "cost_usd": 0.0431,
    "cost_approximate": True,
}
DONE_ROW = {
    "scope": "session",
    "state": "done",
    "task_id": "e5f6a7b8",
    "role": "hermes-native",
    "action": "Write tests for parse_duration",
    "model": "anthropic/claude-fable-5-1",
    "effort": "xhigh",
    "category": "architect",
    "tokens": 77000,
    "elapsed_seconds": 7260,
    "turn_count": 2,
    "tool_count": 5,
    "cost_usd": 0.0123,
}
ESTABLISHED_PAYLOAD = {
    "schema_version": "omh_hud/v1",
    "version": "2.0.5",
    "privacy": "metadata_only",
    "active": True,
    "subagents": {
        "scope": "session",
        "active": 2,
        "running": 1,
        "blocked": 0,
        "completed": 1,
        "hidden_rows": 0,
        "rows": [RUNNING_ROW, DONE_ROW],
    },
    "maestro": {"status": "idle", "rows": [], "scope": "global"},
    "kanban": {"rows_total": 0, "queued": 0, "running": 0, "blocked": 0, "dispatcher_presence": "unknown"},
    "graph": {"status": "inactive", "nodes": [], "edges": [], "frontier": []},
    "activity": {"live": True, "post_tool_call_observed": True, "open_call_count": 2, "oldest_open_elapsed_seconds": 242},
    "repeat": {"status": "idle"},
    "yolo": {"status": "observed", "enabled": False},
    "parallel_shot": {"status": "idle"},
    "todo": {
        "status": "established",
        "title": "Desktop check",
        "counts": {"total": 3, "done": 1, "active": 1, "pending": 1, "skipped": 0, "phases": 2},
        "display_phase": "Build",
        "items": [
            {"text": "Read the pane spec", "state": "done", "phase": "Research"},
            {"text": "Draw the structured pane", "state": "active", "phase": "Build"},
            {"text": "Screenshot the result", "state": "pending", "phase": "Build", "blocked_reason": "needs the app"},
        ],
        "stall": {"status": "observed", "threshold_seconds": 900},
        "updated_age_seconds": 12,
    },
    "display": {
        "line": "[omh] v2.0.5 | plugin:ready | target:single",
        "widget_lines": ["[OMH] Parallel work ready  •  agents 2  •  run 1"],
        "todo_lines": ["Todo · Desktop check   1/3", "[✓] Read the pane spec", "[•] Draw the structured pane"],
    },
}

# A Maestro executor row as MAIN, a board lane, an active DAG and a finished
# plan with one skipped phase: the other row shapes the TUI draws.
MAESTRO_PAYLOAD = {
    "version": "unknown",
    "plugin": {"version": "2.0.5"},
    "privacy": "metadata_only",
    "active": True,
    "subagents": {
        "scope": "mixed",
        "active": 1,
        "running": 0,
        "blocked": 1,
        "completed": 0,
        "hidden_rows": 2,
        "rows": [
            {
                "state": "blocked",
                "task_id": "kb-7",
                "action": "Triage the flaky suite",
                "model": "openai/gpt-5.6",
                "effort": "medium",
                "lane_backend": "kanban",
                "assignee": "",
                "native_status": "review",
                "elapsed_seconds": 61,
            }
        ],
    },
    "maestro": {
        "status": "active",
        "scope": "global",
        "rows": [
            {
                "scope": "global",
                "state": "running",
                "task_id": "run-42",
                "action": "Refactor the router",
                "model": "openai/gpt-5.6",
                "dispatch_lane": "maestro",
                "executor_profile": "codex",
                "elapsed_seconds": 30,
                "tokens": 0,
                "cost_usd": 0,
                "cost_status": "included",
            }
        ],
    },
    "kanban": {"rows_total": 3, "queued": 2, "running": 1, "blocked": 0, "dispatcher_presence": "not_observed"},
    "graph": {
        "status": "active",
        "scope": "global",
        "frontier": ["b"],
        "edges": [["a", "b"]],
        "edge_count": 1,
        "hidden_nodes": 0,
        "nodes": [
            {"node_id": "a", "state": "completed"},
            {"node_id": "b", "state": "running", "in_frontier": True},
            {"node_id": "c", "state": "blocked_by_dependency", "blocked_by": ["b"]},
        ],
    },
    "activity": {"live": False, "post_tool_call_observed": True},
    "repeat": {"status": "observed", "consecutive": 3, "period": 1, "stage": "blocking", "intercepted": 1},
    "yolo": {"status": "observed", "enabled": True},
    "parallel_shot": {"status": "idle"},
    "todo": {
        "status": "all_done",
        "title": "Ship the pane",
        "counts": {"total": 2, "done": 2, "active": 0, "pending": 0, "skipped": 1, "phases": 1},
        "display_phase": "",
        "items": [
            {"text": "Build it", "state": "done"},
            {"text": "Benchmark it", "state": "done", "blocked_reason": "no bench harness"},
        ],
        "stall": {"status": "unobserved", "threshold_seconds": 900},
    },
    "display": {"line": "[omh] vunknown | plugin:ready", "widget_lines": ["[OMH] idle"], "todo_lines": []},
}

SCENARIOS = {
    "open_with_payload": {
        "gateway": "open",
        "stored": "20260924_101010_abc123",
        "model": "deepseek/deepseek-v4.1-flash-ultrafast",
        "usage": {"calls": 9, "input": 40000, "output": 5200, "total": 45200, "context_percent": 12.4, "cost_usd": 0.012},
        "data": ESTABLISHED_PAYLOAD,
    },
    "maestro_and_board": {
        "gateway": "open",
        "stored": "20260924_101010_abc123",
        "model": "openai/gpt-5.6",
        "usage": None,
        "data": MAESTRO_PAYLOAD,
    },
    "no_todo_declared": {
        "gateway": "open",
        "stored": "20260924_101010_abc123",
        "model": "openai/gpt-5.6",
        "usage": None,
        "data": {
            "version": "2.0.5",
            "privacy": "metadata_only",
            "active": False,
            "subagents": {"scope": "session", "active": 0, "running": 0, "blocked": 0, "completed": 0, "rows": []},
            "todo": {"status": "absent"},
            "display": {"line": "[omh] v2.0.5 | plugin:ready", "widget_lines": ["[OMH] idle"], "todo_lines": []},
        },
    },
    # The plan above, held by Hermes' `todo_list` (`source: todo_list`): Hermes
    # Desktop draws those items in its own composer status stack, so the pane
    # keeps only the reason omh_todo recorded, or no PLAN section at all.
    "native_held_waiting": {
        "gateway": "open",
        "stored": "20260924_101010_abc123",
        "model": "openai/gpt-5.6",
        "usage": None,
        "data": {**ESTABLISHED_PAYLOAD, "todo": {**ESTABLISHED_PAYLOAD["todo"], "source": "todo_list"}},
    },
    "native_held_quiet": {
        "gateway": "open",
        "stored": "20260924_101010_abc123",
        "model": "openai/gpt-5.6",
        "usage": None,
        "data": {
            **ESTABLISHED_PAYLOAD,
            "todo": {
                **ESTABLISHED_PAYLOAD["todo"],
                "source": "todo_list",
                "items": [{key: value for key, value in item.items() if key != "blocked_reason"} for item in ESTABLISHED_PAYLOAD["todo"]["items"]],
            },
        },
    },
    "reader_error": {
        "gateway": "open",
        "stored": None,
        "data": {"error": "RuntimeBindingError: OMH home is not configured", "schema_version": "omh_desktop_hud/v1"},
    },
    "transport_error": {"gateway": "open", "stored": None, "data": None, "errorMessage": "HTTP 404: Plugin not found"},
    "loading": {"gateway": "open", "stored": "20260924_101010_abc123", "data": None},
    "gateway_closed": {"gateway": "connecting", "stored": None, "data": None},
}
# The plugin's last tool burst (`tool_bursts._latest_shot_from_entries`) as (open now, peak open at once): calls run
# one after another inside the grouping window, closed and with the last one still open; a real overlap, closed,
# with one call left, and with three open.
SHOTS = {"chain_closed": (0, 1), "chain_open": (1, 1), "overlap_closed": (0, 2), "overlap_last_open": (1, 2), "overlap_open": (3, 3)}
for _name, (_open, _peak) in SHOTS.items():
    SCENARIOS[f"shot_{_name}"] = {
        **SCENARIOS["open_with_payload"],
        "data": {
            **ESTABLISHED_PAYLOAD,
            "parallel_shot": {
                "status": "observed", "open_count": _open, "peak_open_count": _peak, "observed_at": "2026-10-13T00:00:00Z",
            },
        },
    }

# A graph-drawn native child is not counted again in the subagent summary.
NATIVE_GRAPH = {
    "status": "active", "source": "native", "name": "Pane refresh", "dag_open": True,
    "nodes": [
        {"id": "root", "kind": "root", "title": "main", "state": "running"},
        {"id": "drawn", "kind": "lane", "title": "Graph-drawn child", "state": "running", "session_tail": RUNNING_ROW["task_id"], "model": "openai/gpt-5.6"},
    ],
    "edges": [{"from": "root", "to": "drawn"}],
}
CATCHES = [
    {"seq": 0, "kind": "repeat_loop", "laps": 3, "period": 1},
    {"seq": 1, "kind": "repeat_loop", "laps": 4, "period": 2},
    {"seq": 2, "kind": "truncated_read", "offset": 120},
    {"seq": 3, "kind": "plan_continued", "open_items": 1},
    {"seq": 4, "kind": "plan_continued", "open_items": 2},
    {"seq": 5, "kind": "unarmed_wait"},
]
SETTLED_GRAPH = {
    **NATIVE_GRAPH, "dag_open": False,
    "nodes": [
        NATIVE_GRAPH["nodes"][0],
        {"id": "done", "kind": "lane", "title": "Settled child", "state": "done"},
        {"id": "failed", "kind": "lane", "title": "Failed child", "state": "failed"},
    ],
}
for _name, _data in {
    "graph_and_other": {
        **ESTABLISHED_PAYLOAD, "delegation_graph": NATIVE_GRAPH,
        "subagents": {"rows": [RUNNING_ROW, {**RUNNING_ROW, "task_id": "other"}], "hidden_rows": 2, "hidden_in_graph": 2},
    },
    "two_without_graph": {
        **ESTABLISHED_PAYLOAD,
        "subagents": {"rows": [RUNNING_ROW, {**RUNNING_ROW, "task_id": "other"}], "hidden_rows": 2, "hidden_in_graph": 2},
    },
    "catches_and_lanes": {**MAESTRO_PAYLOAD, "catches": CATCHES, "delegation_graph": NATIVE_GRAPH},
    "settled_lanes": {**ESTABLISHED_PAYLOAD, "delegation_graph": SETTLED_GRAPH},
    "inactive_lanes": {**ESTABLISHED_PAYLOAD, "delegation_graph": {**NATIVE_GRAPH, "status": "inactive"}},
    "two_edges": {**MAESTRO_PAYLOAD, "graph": {**MAESTRO_PAYLOAD["graph"], "edges": [["a", "b"], ["b", "c"]], "edge_count": 2}},
}.items():
    SCENARIOS[_name] = {**SCENARIOS["open_with_payload"], "data": _data}
# A live graph with a failed lane: failed is its own word, apart from blocked.
FAILED_GRAPH = {
    **NATIVE_GRAPH,
    "nodes": [
        *NATIVE_GRAPH["nodes"],
        {"id": "broke", "kind": "lane", "title": "Failed child", "state": "failed", "model": "openai/gpt-5.6", "session_tail": "broke01"},
    ],
    "edges": [*NATIVE_GRAPH["edges"], {"from": "drawn", "to": "broke"}],
}
STUCK_AND_FAILED_GRAPH = {
    **NATIVE_GRAPH,
    "nodes": [
        NATIVE_GRAPH["nodes"][0],
        {"id": "held", "kind": "lane", "title": "Stuck child", "state": "stuck", "session_tail": "held01"},
        {"id": "broke", "kind": "lane", "title": "Failed child", "state": "failed", "session_tail": "broke01"},
    ],
}
for _name, _data in {
    "failed_lane": {**ESTABLISHED_PAYLOAD, "delegation_graph": FAILED_GRAPH, "subagents": {"rows": [RUNNING_ROW]}},
    "failed_without_running": {**ESTABLISHED_PAYLOAD, "todo": {"status": "absent"}, "delegation_graph": STUCK_AND_FAILED_GRAPH, "subagents": {"rows": []}},
    "failed_row": {**ESTABLISHED_PAYLOAD, "todo": {"status": "absent"}, "subagents": {"rows": [{**RUNNING_ROW, "state": "failed"}, {**RUNNING_ROW, "task_id": "b2", "state": "blocked"}]}},
}.items():
    SCENARIOS[_name] = {**SCENARIOS["open_with_payload"], "data": _data}
# The same live graph with the drawing the backend sends for it (`plugin_api.delegation_drawing`), an error
# record in its place, and a settled graph that still carries one.
DRAWN_GRAPH = {**NATIVE_GRAPH, "nodes": [*NATIVE_GRAPH["nodes"], {"id": "held", "kind": "lane", "title": "Stuck child",
                                                                  "state": "stuck", "model": "openai/gpt-5.6"}],
               "edges": [*NATIVE_GRAPH["edges"], {"from": "root", "to": "held"}]}
DRAWING = plugin_api.delegation_drawing(DRAWN_GRAPH, 43)
WIDE_GRAPH = {**DRAWN_GRAPH, "nodes": [*DRAWN_GRAPH["nodes"][:2], {**DRAWN_GRAPH["nodes"][2], "title": "인증 모듈"}]}
WIDE_DRAWING = plugin_api.delegation_drawing(WIDE_GRAPH, 43)
for _name, _data in {
    "drawn_graph": {**ESTABLISHED_PAYLOAD, "delegation_graph": DRAWN_GRAPH, "delegation_drawing": DRAWING},
    "wide_drawn": {**ESTABLISHED_PAYLOAD, "delegation_graph": WIDE_GRAPH, "delegation_drawing": WIDE_DRAWING},
    "drawing_error": {**ESTABLISHED_PAYLOAD, "delegation_graph": DRAWN_GRAPH,
                      "delegation_drawing": {"error": "ValueError: no", "schema_version": "omh_desktop_dag/v1"}},
    "settled_drawn": {**ESTABLISHED_PAYLOAD, "delegation_graph": SETTLED_GRAPH, "delegation_drawing": DRAWING},
}.items():
    SCENARIOS[_name] = {**SCENARIOS["open_with_payload"], "data": _data}
# A dag-ulw run (`dag_topology` present) is drawn as cards with the figures the backend read from each lane's session.
def _dag_lane(node: str, title: str, **fields: object) -> dict:
    return {"id": f"d:r:{node}", "kind": "lane", "title": title, "category": "quick", "model": "?", "effort": "", "state": "waiting",
            "status": "waiting", "dag_node": node, "dag_origin": "define", "role": "build", **fields}


def _dag_graph(lanes: list[dict], edges: list[tuple[str, str]], path: list[str], bottlenecks: list[list], **extra: object) -> dict:
    heads = {f"d:r:{head}" for _, head in edges}
    return {
        "status": "active", "source": "dag", "name": "Write and sum", "dag_open": True,
        "nodes": [{"id": "root", "kind": "root", "title": "main", "state": "running"}, *lanes],
        "edges": [{"from": "root", "to": lane["id"]} for lane in lanes if lane["id"] not in heads]
        + [{"from": f"d:r:{tail}", "to": f"d:r:{head}"} for tail, head in edges],
        "dag_topology": {"critical_path": path, "bottlenecks": bottlenecks},
        **extra,
    }


DAG_GRAPH = _dag_graph(
    [
        _dag_lane("a", "Write a.txt", state="done", status="accepted", model="anthropic/claude-haiku-5-5", effort="high",
                  elapsed_seconds=47, output_tokens=410, usage={"input": 900, "cache_read": 6200, "cache_write": 600, "cost_usd": 0.0123}),
        _dag_lane("b", "Write b.txt", state="running", status="running", model="anthropic/claude-haiku-5-5", effort="high",
                  elapsed_seconds=31, output_tokens=220,
                  usage={"input": 700, "cache_read": 3100, "cache_write": 500, "cost_usd": 0.0061, "cost_estimated": True}),
        _dag_lane("sum", "Sum", waits_on=1),
        _dag_lane("chk", "Check", category="review", role="verify", waits_on=1),
    ],
    [("a", "sum"), ("b", "sum"), ("sum", "chk")],
    ["Write a.txt", "Sum", "Check"],
    [["Sum", 1]],
)
# What the reader sends for a run it cut (`delegation_graph._layered`): kept lanes carry their layer, `layer_count`
# says how many layers the run has, and a layer that lost lanes counts them. Layer 0 lost all four of its own, layer 1
# two of three; layers 2 and 3 lost none and have no row.
CUT_DAG_GRAPH = {
    **_dag_graph(
        [_dag_lane("b", "B", state="done", status="accepted",
                   usage={"input": 900, "cache_read": 6200, "cache_write": 600, "cost_usd": 0.0123}),
         _dag_lane("c", "C", state="running", status="running",
                   usage={"input": 700, "cache_read": 3100, "cache_write": 500, "cost_usd": 0.0061}),
         _dag_lane("d", "D", waits_on=1)],
        [("b", "c"), ("c", "d")],
        [],
        [],
    ),
    "hidden_nodes": 6,
    "layer_count": 4,
    "layer_hidden": [{"layer": 0, "count": 4, "states": {"done": 4}}, {"layer": 1, "count": 2, "states": {"done": 2}}],
}
for _lane, _at in zip((node for node in CUT_DAG_GRAPH["nodes"] if node.get("kind") != "root"), (1, 2, 3)):
    _lane["layer"] = _at
# The same run with layer 2 cut too: the reader hangs D from B, its nearest kept ancestor, by an `elided` edge.
ELIDED_DAG_GRAPH = {
    **CUT_DAG_GRAPH,
    "nodes": [node for node in CUT_DAG_GRAPH["nodes"] if node["id"] != "d:r:c"],
    "edges": [*(edge for edge in CUT_DAG_GRAPH["edges"] if "d:r:c" not in (edge["from"], edge["to"])),
              {"from": "d:r:b", "to": "d:r:d", "kind": "depends_on", "elided": True}],
    "hidden_nodes": 7,
    "layer_hidden": [*CUT_DAG_GRAPH["layer_hidden"], {"layer": 2, "count": 1, "states": {"running": 1}}],
}
# The same run with its last layer cut whole: the depth comes from `layer_count`, not from the lanes drawn.
TAIL_CUT_DAG_GRAPH = {
    **CUT_DAG_GRAPH,
    "nodes": [node for node in CUT_DAG_GRAPH["nodes"] if node["id"] != "d:r:d"],
    "edges": [edge for edge in CUT_DAG_GRAPH["edges"] if "d:r:d" not in (edge["from"], edge["to"])],
    "hidden_nodes": 7,
    "layer_hidden": [*CUT_DAG_GRAPH["layer_hidden"], {"layer": 3, "count": 1, "states": {"waiting": 1}}],
}
# A run too deep for the reader to send even its layer rows: its counts by state alone.
COUNTS_ONLY_GRAPH = {
    "status": "active", "source": "native", "name": "delegation", "scope": "session",
    "nodes": [{"id": "root", "kind": "root", "title": "main", "state": "running"}], "edges": [],
    "hidden_nodes": 500, "hidden_by_state": {"done": 497, "running": 2, "failed": 1}, "layer_count": 500,
    "layer_hidden": [], "counts_only": True,
}
FANOUT_GRAPH = {
    **DAG_GRAPH,
    "source": "fanout",
    "name": "fanout fanout-0123456789ab",
    "nodes": [
        {**node, "id": node["id"].replace("d:r:", "f:")}
        for node in DAG_GRAPH["nodes"]
    ],
    "edges": [
        {**edge, "from": edge["from"].replace("d:r:", "f:"), "to": edge["to"].replace("d:r:", "f:")}
        for edge in DAG_GRAPH["edges"]
    ],
}
FANOUT_GRAPH.pop("dag_topology")
# A large run under way: three layers done, the fourth running, eight more waiting.
WORKING_DAG_GRAPH = _dag_graph(
    [_dag_lane(f"n{at}", f"Step {at}", state="done", status="accepted") if at < 3
     else _dag_lane(f"n{at}", f"Step {at}", state="running", status="running") if at == 3
     else _dag_lane(f"n{at}", f"Step {at}") for at in range(12)],
    [(f"n{at}", f"n{at + 1}") for at in range(11)],
    ["Step 0"],
    [],
)
BEYOND_DAG_GRAPH = _dag_graph(
    [_dag_lane(f"n{at}", f"Step {at}") for at in range(17)],
    [(f"n{at}", f"n{at + 1}") for at in range(16)],
    ["Step 0"],
    [["Step 0", 16]],
    hidden_nodes=3,
)
SETTLED_DAG_GRAPH = _dag_graph(
    [
        _dag_lane("a", "Write a.txt", state="done", status="accepted", elapsed_seconds=47,
                  usage={"input": 900, "cache_read": 6200, "cache_write": 600, "cost_usd": 0.0123}),
        _dag_lane("sum", "Sum", state="done", status="accepted", elapsed_seconds=12),
    ],
    [("a", "sum")],
    ["Write a.txt", "Sum"],
    [],
    dag_open=False,
)
PARTIAL_COST_GRAPH = _dag_graph(
    [
        _dag_lane("a", "Write a.txt", state="done", status="accepted", model="anthropic/claude-haiku-5-5",
                  output_tokens=410, usage={"input": 900, "cache_read": 6200, "cache_write": 600, "cost_usd": 0.0123}),
        _dag_lane("b", "Write b.txt", state="running", status="running", model="anthropic/claude-haiku-5-5",
                  output_tokens=220, usage={"input": 700, "cache_read": 3100, "cache_write": 500}),
    ],
    [],
    ["Write a.txt"],
    [],
)
for _name, _data in {
    "dag_settled": {**ESTABLISHED_PAYLOAD, "delegation_graph": SETTLED_DAG_GRAPH},
    # A settled run whose lanes counted nothing: no figure to keep, so the one line alone.
    "dag_settled_uncounted": {**ESTABLISHED_PAYLOAD, "delegation_graph": {
        **SETTLED_DAG_GRAPH, "nodes": [{key: value for key, value in item.items() if key != "usage"}
                                       for item in SETTLED_DAG_GRAPH["nodes"]]}},
    "dag_partial_cost": {**ESTABLISHED_PAYLOAD, "delegation_graph": PARTIAL_COST_GRAPH},
    "dag_cards": {**ESTABLISHED_PAYLOAD, "delegation_graph": DAG_GRAPH},
    "fanout_cards": {**ESTABLISHED_PAYLOAD, "delegation_graph": FANOUT_GRAPH},
    "dag_beyond_cards": {**ESTABLISHED_PAYLOAD, "delegation_graph": BEYOND_DAG_GRAPH, "delegation_drawing": DRAWING},
    "dag_cut_cards": {**ESTABLISHED_PAYLOAD, "delegation_graph": CUT_DAG_GRAPH},
    "dag_counts_only": {**ESTABLISHED_PAYLOAD, "delegation_graph": COUNTS_ONLY_GRAPH},
}.items():
    SCENARIOS[_name] = {**SCENARIOS["open_with_payload"], "data": _data}
SCENARIOS["busy"] = {**SCENARIOS["open_with_payload"], "busy": True}
# The same board on a host that names no chat (an older Hermes Desktop): the home's runtime graph is drawn there; a
# pane that names its chat draws that chat's work alone, and the runtime graph may be another session's.
SCENARIOS["maestro_unnamed"] = {**SCENARIOS["maestro_and_board"], "stored": None}
# The usage board: a chat whose row Hermes recorded, whose stream is live, whose context breakdown the host
# answers, and which this window timed through two turns (1850 ms and 410 ms to the first token).
SCENARIOS["usage_board"] = {
    **SCENARIOS["open_with_payload"],
    "focused": "rt-1",
    "usage": {
        "model": "gpt-6-luna", "calls": 4, "input": 1200, "output": 630, "prompt": 12000, "total": 12630,
        "avg_tps": 41.6, "avg_latency_s": 3.2, "cache_hit_pct": 77,
        "context_used": 15700, "context_max": 100000, "context_percent": 16, "compressions": 1,
    },
    "breakdown": {
        "categories": [
            {"id": "system_prompt", "label": "System prompt", "tokens": 3000, "color": "x"},
            {"id": "tool_definitions", "label": "Tools", "tokens": 6000, "color": "x"},
            {"id": "memory", "label": "Memory", "tokens": 0, "color": "x"},
            {"id": "conversation", "label": "Conversation", "tokens": 6700, "color": "x"},
        ],
        "context_max": 100000, "context_used": 15700, "context_percent": 16,
    },
    "events": [
        ["message.start", "rt-1", None, 1000], ["message.delta", "rt-1", None, 1200], ["message.delta", "rt-1", "Hi", 2850],
        ["message.delta", "rt-1", "again", 2900],
        ["message.start", "rt-1", None, 5000], ["reasoning.delta", "rt-1", "hm", 5410],
    ],
    "data": {
        **ESTABLISHED_PAYLOAD,
        "session_usage": {"session_id": "20260924_101010_abc123", "model": "gpt-6-luna", "output": 630, "input": 1600,
                          "cache_read": 9300, "cache_write": 1100, "cost_usd": 0.5},
    },
}
# The chat switched and the last poll's answer, for the chat before, is still on screen.
SCENARIOS["usage_board_switched"] = {**SCENARIOS["usage_board"], "stored": "20260925_090000_def456", "events": []}
# The recorded row could not be read: the board keeps the stream.
SCENARIOS["usage_board_read_failed"] = {
    **SCENARIOS["usage_board"],
    "events": [],
    "data": {**ESTABLISHED_PAYLOAD,
             "session_usage": {"session_id": "20260924_101010_abc123", "error": "OperationalError: database is locked"}},
}
SCENARIOS["usage_board_busy"] = {**SCENARIOS["usage_board"], "busy": True, "events": []}
# No recorded row and no breakdown yet: only what the stream carries.
SCENARIOS["usage_board_stream_only"] = {
    **SCENARIOS["open_with_payload"],
    "focused": "rt-2",
    "usage": {"model": "gpt-6-luna", "calls": 2, "input": 500, "prompt": 4000, "output": 300, "cache_hit_pct": 50},
}
# The gateway's `session.stats` answer (`gateway/session_usage.py::usage_stats`) for a chat seven calls in.
GATEWAY_STATS = {
    "input_tokens": 4000, "cache_read_tokens": 36000, "cache_write_tokens": 0, "output_tokens": 2000,
    "prompt_tokens": 40000, "completion_tokens": 2000, "total_tokens": 42000, "reasoning_tokens": 0, "api_calls": 7,
    "last_prompt_tokens": 50000, "context_tokens": 50000, "context_length": 200000, "context_source": "provider_usage",
    "avg_latency_s": 2.5, "tokens_per_s": 33.3, "model": "claude-opus-5-5", "provider": "custom",
}

SCENARIOS["usage_board_unknown"] = {**SCENARIOS["open_with_payload"], "usage": None}
# A chat whose only figures are the gateway's counters: the case a recorded chat with no row yet showed nothing for.
SCENARIOS["usage_board_gateway"] = {**SCENARIOS["usage_board_unknown"], "focused": "rt-9", "stats": GATEWAY_STATS}
# A fresh run with nothing counted yet: live, so not grey.
SCENARIOS["runtime_only"] = {
    "gateway": "open",
    "stored": None,
    "data": {"active": True, "runtime": {"recent": True, "workflow": "fanout"}, "subagents": {"rows": []}, "todo": {"status": "absent"}},
}
SCENARIOS["global_idle"] = {**SCENARIOS["no_todo_declared"], "stored": None}

# A session's dag runs as the backend lists them, newest first.
DAG_RUNS = [
    {"run": "new", "name": "supplement", "state": "running", "nodes": 3, "updated_at": 20.0},
    {"run": "old", "name": "main plan", "state": "done", "nodes": 31, "updated_at": 10.0},
]

SCENARIOS["dag_two_runs"] = {
    **SCENARIOS["open_with_payload"],
    "data": {**ESTABLISHED_PAYLOAD, "delegation_graph": DAG_GRAPH, "dag_runs": DAG_RUNS},
}

# Every fanout status the reader accepts (`runtime_reader._FANOUT_GRAPH_STATUSES`)
# and every stuck unit state (`subagent_graph._STUCK_UNIT_STATES`): finite
# reader vocabulary, so each one has a word in every table.
FANOUT_AND_STUCK_STATES = {
    *runtime_reader._FANOUT_GRAPH_STATUSES,
    *subagent_graph._STUCK_UNIT_STATES,
}

IMPLIED_EDGES_GRAPH = {
    **_dag_graph([_dag_lane(name, name) for name in ("a", "b", "c", "fix")], [], [], []),
    "edges": [{"from": f"d:r:{tail}", "to": f"d:r:{head}", "kind": kind}
              for tail, head, kind in (("a", "b", "depends_on"), ("b", "c", "depends_on"), ("a", "c", "depends_on"),
                                       ("c", "fix", "repair"), ("a", "fix", "depends_on"), ("a", "b", "depends_on"))],
}

# The TUI examples from the widget's own grammar, one call each; the report
# carries the answers in this order.
FORMATTER_CASES = {
    "pollInterval": [[True], [False]],
    "hudPath": [[None, ""], ["s 1"], [None, None], ["s", "r 1"], ["s", "", "1,4"]],
    "segmentTone": [["node:running"], ["node:done"], ["node-title:done"], ["node-word:waiting"], ["glyph:failed"],
                    ["status:stuck"], ["node:interrupted"], ["edge"], ["connector"], ["connector:running"], ["header"],
                    ["frontier"], ["model"], ["something"], [""]],
    "rowFigures": [[{"state": "running", "tool_count": count}, 0] for count in (0, 1, 2)],
    "stateWord": [["running"], ["blocked_by_dependency"], ["review"], ["some_new_state"], [""], ["failed", "ko"], ["review", "ko"]],
    # Every fanout status the reader accepts and every stuck unit state, read in Korean.
    "koreanStates": [[sorted(FANOUT_AND_STUCK_STATES)]],
    "reasonWord": [["no_new_output"], ["prompt_at_end"], ["repeated_error: ENOENT x"], ["no_new_output", "ko"], ["prompt_at_end", "ko"], ["account_limit: 429 slow down", "ko"], ["something_else", "ko"]],
    "scopeLabel": [["session-id"], [None]],
    "humanState": [["blocked_by_dependency"], ["already_completed"], ["dry_run_planned"]],
    "wordTone": [["running"], ["waiting"], ["failed"], ["done"], ["review"]],
    "itemGlyph": [[{"state": "done"}], [{"state": "done", "blocked_reason": "not needed"}], [{"state": "active"}], [{"state": "pending"}]],
    "itemState": [[{"state": "done", "blocked_reason": "not needed"}]],
    "planProgress": [[MAESTRO_PAYLOAD["todo"]], [{"counts": {"total": 0}}]],
    "chipList": [[ESTABLISHED_PAYLOAD], [MAESTRO_PAYLOAD]],
    "catchSentence": [[entry] for entry in CATCHES] + [[{"kind": "repeat_loop", "laps": True, "period": 1}], [{"kind": "unknown"}]],
    "catchRows": [[{"catches": [*CATCHES, {"seq": -1, "kind": "unarmed_wait"}, {"seq": 9, "kind": "unknown"}]}]],
    "delegationView": [[{}], [{"delegation_graph": {**NATIVE_GRAPH, "status": "inactive"}}], [{"delegation_graph": SETTLED_GRAPH}]],
    "dagRunChoices": [
        [{"dag_runs": DAG_RUNS}, ""], [{"dag_runs": DAG_RUNS}, "old"], [{"dag_runs": DAG_RUNS}, "gone"],
        [{"dag_runs": DAG_RUNS[:1]}, ""], [{}, ""],
    ],
    "foldsOf": [
        [WORKING_DAG_GRAPH, "auto"], [WORKING_DAG_GRAPH, "active"], [WORKING_DAG_GRAPH, "open"], [WORKING_DAG_GRAPH, "closed"],
        # A layer the person opened stays open under the mode; the open lane's layer is never folded.
        [WORKING_DAG_GRAPH, "auto", {"1": True}], [WORKING_DAG_GRAPH, "auto", {}, "d:r:n7"],
        # A layer the person folded stays folded, although the mode would leave it open.
        [WORKING_DAG_GRAPH, "open", {"4": False}],
        # A small run reads whole; a large one with nothing started keeps its first layers open.
        [DAG_GRAPH, "auto"], [BEYOND_DAG_GRAPH, "auto"],
    ],
    "foldedEdges": [[DAG_GRAPH, [0]], [DAG_GRAPH, [1]], [DAG_GRAPH, []]],
    "cutLayers": [[CUT_DAG_GRAPH], [TAIL_CUT_DAG_GRAPH]],
    "elidedEdges": [[ELIDED_DAG_GRAPH]],
    "sharedOpenKeys": [["s1", "1,2"]],
    "dagViewOptions": [[None], [{"fold": "closed", "figures": False, "implied": True}], [{"fold": "sideways", "compact": "yes"}]],
    "dagModel": [
        [DAG_GRAPH],
        [FANOUT_GRAPH],
        # An edge to a lane that is not there and a repeated one; then two lanes that wait on each other.
        [{**DAG_GRAPH, "edges": [*DAG_GRAPH["edges"], {"from": "d:r:a", "to": "ghost"}, {"from": "d:r:a", "to": "d:r:sum"}]}],
        [{**DAG_GRAPH, "edges": [{"from": "d:r:a", "to": "d:r:b"}, {"from": "d:r:b", "to": "d:r:a"}]}],
        [{**DAG_GRAPH, "dag_topology": None}],
        [{**DAG_GRAPH, "status": "inactive"}],
        [BEYOND_DAG_GRAPH],
        # A lane whose own cost is a floor (an unpriced auxiliary call) makes the run's a floor.
        [{**DAG_GRAPH, "nodes": [{**item, "usage": {**item["usage"], "cost_partial": True}} if item["id"] == "d:r:a" else item
                                 for item in DAG_GRAPH["nodes"]]}],
        # a to b to c with a to c as well: a to c is implied. A repair edge only says where a node came from, so the
        # a to fix dependency stays although a reaches fix through c's repair; a repeated edge is one edge.
        [IMPLIED_EDGES_GRAPH],
    ],
    "t": [["dgLayerFold", {"layer": 1, "count": 1}], ["dgLayerFold", {"layer": 1, "count": 2}], ["stateIdle", {}, "ko"]],
    "foldLabels": [[[{"state": "done"}] * 4, {"start": 3, "earlier": 3, "later": 1}]],
    "agentTally": [[{**SCENARIOS["graph_and_other"]["data"], "subagents": {"rows": [RUNNING_ROW], "hidden_rows": 1, "hidden_in_graph": 9}}]],
    "tokenCountText": [[77000], [184800], [999950], [999], [0], [-1]],
    "latencyText": [[None], [0], [12], [999], [1000], [1130], [2500], [-5]],
    "speedText": [[41.6], [9.44], [0], [None], [120.4]],
    "ttftWaits": [
        [[["message.start", "s", None, 100], ["message.delta", "s", "Hi", 350], ["message.delta", "s", "more", 400]]],
        # An empty chunk is no token; reasoning is.
        [[["message.start", "s", None, 0], ["message.delta", "s", None, 50], ["message.delta", "s", "", 60], ["reasoning.delta", "s", "think", 90]]],
        [[["message.delta", "s", "x", 10]]],
        [[["message.start", "a", None, 0], ["message.start", "b", None, 5], ["message.delta", "b", "x", 25],
          ["thinking.delta", "a", "y", 40], ["tool.start", "a", "z", 50]]],
        # A start re-sent for the same turn_id keeps the original anchor; a different turn_id starts a new wait.
        [[["message.start", "s", None, 100, "t1"], ["message.start", "s", None, 900, "t1"],
          ["message.delta", "s", "x", 1200, "t1"], ["message.start", "s", None, 2000, "t2"], ["message.delta", "s", "y", 2300, "t2"]]],
        [[["message.start", "", None, 0], ["message.delta", "", "x", 5], ["message.start", "s", None, None], ["message.delta", "s", "x", 5]]],
        [[event for turn in range(12) for event in (["message.start", "s", None, turn * 100], ["message.delta", "s", "x", turn * 100 + turn])]],
        # A turn interrupted before its first token (Hermes sends `message.complete`), then a turn that streams:
        # only the second is timed, from its own start.
        [[["message.start", "s", None, 0], ["message.complete", "s", None, 500], ["message.start", "s", None, 1000],
          ["message.delta", "s", "x", 1300]]],
        # The same with turn ids, ended by an error: a late chunk of the dead turn times nothing.
        [[["message.start", "s", None, 0, "t1"], ["error", "s", None, 100], ["message.delta", "s", "late", 200, "t1"],
          ["message.start", "s", None, 1000, "t2"], ["message.delta", "s", "y", 1250, "t2"]]],
        # A start without a turn id replaces the last one (an older Hermes, or a follow-up turn's bare start), and
        # a chunk of another turn than the pending one times nothing.
        [[["message.start", "s", None, 0], ["message.start", "s", None, 1000], ["message.delta", "s", "x", 1200]]],
        [[["message.start", "s", None, 0, "t1"], ["message.delta", "s", "x", 50, "t0"], ["message.delta", "s", "x", 80, "t1"]]],
    ],
    "ttftPending": [
        # Dead turns with no end event in view, and new chats: one pending start per chat, never one per turn.
        [[["message.start", "s", None, turn * 10, f"t{turn}"] for turn in range(40)]
         + [["message.start", "s", None, 500 + turn] for turn in range(40)]
         + [["message.start", "u", None, 900], ["message.complete", "s", None, 950]]],
    ],
    "laneLegend": [
        [{"usage": {"input": 0, "cache_read": 4000, "cache_write": 0, "output": 10}}],
        [{"output_tokens": 300}],
        [{"usage": {"input": 0, "cache_read": 0, "cache_write": 0, "output": 0, "cost_usd": 0}}],
    ],
    "sumCostText": [
        [{"lanes": 2, "priced": 2, "cost": 0.0184, "estimated": True, "partial": False}],
        [{"lanes": 2, "priced": 1, "cost": 0.0123, "estimated": False, "partial": False}],
        [{"lanes": 2, "priced": 0, "cost": None, "estimated": False, "partial": False}],
        [{"lanes": 1, "priced": 1, "cost": 0, "estimated": False, "partial": False}],
        # Every lane priced, one of them a floor itself; and an estimated floor, which reads as a floor alone.
        [{"lanes": 2, "priced": 2, "cost": 0.03, "estimated": False, "partial": True}],
        [{"lanes": 2, "priced": 1, "cost": 0.01, "estimated": True, "partial": False}],
    ],
    "costText": [[0.0123, False], [0, False], [None, False], [0.0061, True], [0.0061, True, True]],
    "usageBoard": [
        # The stream alone, with a cost it does not vouch for.
        [{"live": {"prompt": 4000, "input": 500, "output": 300, "cache_hit_pct": 50, "cost_usd": 0.01}}],
        # Recorded counts win over the stream, and carry their own estimate mark.
        [{"live": {"prompt": 1, "output": 1, "cache_hit_pct": 1}, "stored": "c1", "saved": {"session_id": "c1", "input": 1600, "cache_read": 9300, "cache_write": 1100, "output": 630, "cost_usd": 0.0184, "cost_estimated": True}}],
        # A recorded zero read is a 0.0% hit, not a dash.
        [{"stored": "c1", "saved": {"session_id": "c1", "input": 12000, "output": 100}}],
        [{}],
        [{"live": {"calls": 3}}],
        [{"live": {"context_used": 5000, "context_estimated": True}}],
        [{"breakdown": {"context_used": 8000, "context_max": 32000, "categories": [
            {"id": "system_prompt", "label": "System prompt", "tokens": 3000}, {"id": "conversation", "label": "Conversation", "tokens": 5000}]}}],
        # Entries without a count are left out of the composition.
        [{"breakdown": {"context_max": 100, "categories": [
            {"id": "a", "label": "A", "tokens": 600}, {"id": "b", "label": "B", "tokens": 0}, {"label": "C", "tokens": "x"}, None]}}],
        # Another chat's row (the last poll's, across a switch), a row with no chat named, and a failed read.
        [{"live": {"prompt": 4000, "output": 300}, "stored": "c2", "saved": {"session_id": "c1", "input": 1600, "output": 630, "cost_usd": 0.5}}],
        [{"live": {"prompt": 4000, "output": 300}, "stored": "c1", "saved": {"input": 1600, "output": 630, "cost_usd": 0.5}}],
        [{"live": {"prompt": 4000, "output": 300}, "stored": "c1", "saved": {"session_id": "c1", "error": "OperationalError: locked"}}],
        # A provider-reported zero is a zero cost.
        [{"stored": "c1", "saved": {"session_id": "c1", "input": 100, "output": 10, "cost_usd": 0}}],
        # Some counted part unpriced: the priced sum, as a floor.
        [{"stored": "c1", "saved": {"session_id": "c1", "input": 100, "output": 10, "cost_usd": 0.521, "cost_estimated": True,
                                    "cost_partial": True}}],
        # The chat with its subagents' lanes (one unpriced), then the same lanes left out.
        [{"stored": "c1", "saved": {"session_id": "c1", "input": 1000, "cache_read": 500, "output": 100, "cost_usd": 0.5},
          "withSubs": True, "subs": {"lanes": 2, "priced": 1, "input": 200, "read": 300, "write": 0, "output": 50, "cost": 0.25,
                                     "estimated": False, "partial": False}}],
        [{"stored": "c1", "saved": {"session_id": "c1", "input": 1000, "cache_read": 500, "output": 100, "cost_usd": 0.5},
          "withSubs": False, "subs": {"lanes": 2, "priced": 1, "input": 200, "read": 300, "write": 0, "output": 50, "cost": 0.25,
                                      "estimated": False, "partial": False}}],
        # A chat with no row yet (the stream's counts) and no cost, beside a priced lane: the sum is the lane's, a floor.
        [{"live": {"prompt": 4000, "output": 300}, "withSubs": True,
          "subs": {"lanes": 1, "priced": 1, "input": 200, "read": 0, "write": 0, "output": 50, "cost": 0.25,
                   "estimated": False, "partial": False}}],
        # The gateway's counters run ahead of the row (they count the turn in flight): they take the tokens, the
        # window, the speed and the model, and the row's cost becomes a floor. Then the same counters behind the row.
        [{"stored": "c1", "saved": {"session_id": "c1", "input": 1000, "cache_read": 500, "output": 100, "cost_usd": 0.5},
          "stats": GATEWAY_STATS}],
        [{"stored": "c1", "saved": {"session_id": "c1", "input": 90000, "cache_read": 500, "output": 100, "cost_usd": 0.5},
          "stats": GATEWAY_STATS}],
        # Counters before the first call are no figures.
        [{"stats": {**GATEWAY_STATS, "api_calls": 0}}],
    ],
    "elapsedText": [[12], [242], [7260], [None]],
    "costSegmentText": [
        [{"cost_usd": 0.0123}],
        [{"cost_usd": 0.0431, "cost_approximate": True}],
        [{"cost_usd": 0, "cost_status": "included"}],
        [{"cost_usd": 0}],
        [{}],
    ],
    "routeIdentity": [
        [{"model": "anthropic/claude-fable-5-1", "effort": "xhigh", "category": "architect"}],
        [{"model": "claude-opus-5", "effort": "high", "category": "inherit"}],
        [{"model": "openai/gpt-5.6", "dispatch_lane": "maestro", "executor_profile": "codex"}],
        [{"model": "openai/gpt-5.6", "effort": "low", "category": "quick", "route_origin": "fallback"}],
        [{"model": "openai/gpt-5.6", "effort": "high", "category": "inherit", "route_origin": "exhausted_to_inherit", "route_category": "deep"}],
        [{"model": "openai/gpt-5.6", "effort": "medium", "lane_backend": "kanban"}],
        [{"model": "openai/gpt-5.6", "effort": "medium"}],
    ],
    "hudStateLabel": [
        [False, {}],
        [True, {"active": 3, "running": 2, "blocked": 1}],
        [True, {"active": 2, "completed": 2}],
        [True, {"active": 4, "running": 3, "blocked": 1, "completed": 1}],
    ],
}


def _rewrite_specifiers(source: str, shim_urls: dict[str, str]) -> str:
    """The loader's rewrite: only mapped specifiers change, never other text."""
    return IMPORT_SPECIFIER.sub(
        lambda m: f"{m.group(1)}{m.group(2)}{shim_urls.get(m.group(3), m.group(3))}{m.group(2)}",
        source,
    )


def _reader_scenarios(root: Path) -> dict:
    """Exercise the real store-to-REST path before sending its payload to node."""
    hermes_home = root / "reader-hermes"
    hermes_home.mkdir()
    omh_home = root / "reader-omh"
    run_dir = omh_home / "runtime" / "runs" / "reader-run"
    run_dir.mkdir(parents=True)
    scenarios = {}
    now = datetime.now(timezone.utc)
    with mock.patch.dict(os.environ, {"HERMES_HOME": str(hermes_home), "OMH_HOME": str(omh_home)}):
        for name, age in (("reader_old", timedelta(days=2)), ("reader_fresh", timedelta())):
            stamp = (now - age).isoformat()
            (run_dir / "run.json").write_text(
                json.dumps({"run_id": "reader-run", "skill": "fanout", "phase": "executing", "created_at": stamp, "updated_at": stamp}),
                encoding="utf-8",
            )
            payload = plugin_api.hud_payload(hermes_home, "")
            if "error" in payload:
                raise AssertionError(payload["error"])
            scenarios[name] = {"gateway": "open", "stored": None, "data": payload}
    return scenarios


def _plugin_yaml_name() -> str:
    for line in (BUNDLE / "plugin.yaml").read_text(encoding="utf-8").splitlines():
        if line.startswith("name:"):
            return line.split(":", 1)[1].strip()
    raise AssertionError("plugin.yaml has no name line")


class DesktopBackendTests(unittest.TestCase):
    def setUp(self) -> None:
        # The reader resolves the OMH store from the process's own Hermes
        # home (here `HERMES_HOME`, since no host answers), through that
        # home's config, then `OMH_HOME`; both point into the temp root so
        # the read never reaches ~/.hermes/config.yaml or ~/.omh.
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.hermes_home = self.root / "hermes"
        self.hermes_home.mkdir()
        patcher = mock.patch.dict(
            os.environ, {"OMH_HOME": str(self.root / "omh"), "HERMES_HOME": str(self.hermes_home)}
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_load_reader_loads_the_bundle_reader_by_path_under_a_private_package(self) -> None:
        reader = plugin_api.load_reader(BUNDLE)
        self.assertEqual(reader.__name__, "omh_desktop_bundle.runtime_reader")
        self.assertEqual(Path(reader.__file__), BUNDLE / "runtime_reader.py")
        self.assertTrue(callable(reader.read_omh_hud))
        # The reader's relative imports resolved to the bundle's own files
        # through the parent package, not to the installed `omh` package.
        self.assertEqual(sys.modules["omh_desktop_bundle"].__path__, [str(BUNDLE)])
        self.assertIn("omh_desktop_bundle.runtime_paths", sys.modules)
        self.assertIs(plugin_api.load_reader(BUNDLE), reader)

    def test_a_running_dag_ulw_run_is_drawn_as_the_boxes_the_tui_prints(self) -> None:
        """The real store-to-REST path: a defined dag-ulw run, read for its session at 60 cells.

        Mutation: draw with Dependencies (`sections=1`), or through `render_delegation_view`'s own choice.
        """
        from test_dag_tool import call, node as dag_node, slots_table
        from test_tui_panels import THEME

        nodes = [dag_node("api", scope=("src/api.py",), label="Export API"),
                 dag_node("ui", scope=("src/ui.py",), label="Export button"),
                 dag_node("verify", depends_on=("api", "ui"), label="Verify export", role="verify")]
        with homes() as home:
            slots_table(home)
            call(action="define", run="export", name="export feature", nodes=nodes)
            payload = plugin_api.hud_payload(home.hermes, PARENT, cols=60)
            bare = plugin_api.hud_payload(home.hermes, PARENT)
        self.assertNotIn("error", payload)
        self.assertEqual(payload["delegation_graph"]["status"], "active")
        drawing = payload["delegation_drawing"]
        self.assertEqual((drawing["schema_version"], drawing["layout"], drawing["cols"]), ("omh_desktop_dag/v1", "box", 60))
        printed = dag_block.rows(dag_block.DagBlock("plan", payload["delegation_graph"]), 60 + len(dag_block.INDENT), THEME)
        self.assertEqual(
            ["".join(segment["text"] for segment in line) for line in drawing["lines"]],
            ["".join(span.text for span in line)[len(dag_block.INDENT):] for line in printed[1:]],
            "the pane's drawing is the TUI's transcript print, line for line",
        )
        roles = {segment["role"] for line in drawing["lines"] for segment in line}
        self.assertTrue({"header", "node:dispatched", "node-title:dispatched"} & roles, roles)
        self.assertNotIn("dependency", roles, "no Dependencies section, as the TUI prints it")
        # Without `cols` the payload is the reader's alone.
        self.assertNotIn("delegation_drawing", bare)

    def test_the_hud_carries_the_named_chats_recorded_figures_and_only_that_chat_s(self) -> None:
        """Mutation: read `session_usage` for no session, or leave it out of the payload."""
        from test_delegation_graph import UsageTests

        with homes() as home:
            home.session(PARENT, "gpt-6-luna", started=1.0)
            UsageTests.with_columns(home)
            home.tokens(PARENT, 630)
            UsageTests.count(home, PARENT, 120, 4_000, 300, actual=0.5)
            named = plugin_api.hud_payload(home.hermes, PARENT)
            bare = plugin_api.hud_payload(home.hermes, "")
        self.assertEqual(named["session_usage"], {"session_id": PARENT, "model": "gpt-6-luna", "output": 630,
                                                  "input": 120, "cache_read": 4_000, "cache_write": 300,
                                                  "cost_usd": 0.5})
        self.assertNotIn("session_usage", bare, "no session is named, so no chat's figures are read")

    def test_a_failed_usage_read_is_a_record_beside_a_hud_that_still_reads(self) -> None:
        """Mutation: let the failure escape, drop it silently, or let it replace the reader's payload."""
        from test_delegation_graph import UsageTests

        with homes() as home:
            home.session(PARENT, "gpt-6-luna", started=1.0)
            UsageTests.with_columns(home)
            UsageTests.count(home, PARENT, 120, 4_000, 300, actual=0.5)
            read = plugin_api.hud_payload(home.hermes, PARENT)
            graph = sys.modules["omh_desktop_bundle.delegation_graph"]
            with mock.patch.object(graph, "session_usage", side_effect=RuntimeError("state.db is locked")):
                failed = plugin_api.hud_payload(home.hermes, PARENT)
        self.assertEqual(failed["session_usage"], {"session_id": PARENT, "error": "RuntimeError: state.db is locked"})
        self.assertNotIn("error", failed, "the reader's payload is not an error record")
        def reader_part(payload: dict) -> dict:
            # The open activity's age is the payload's one clock-dependent figure (null here, nothing is open).
            rest = {key: value for key, value in payload.items() if key != "session_usage"}
            rest["activity"] = {key: value for key, value in (rest.get("activity") or {}).items()
                                if key != "oldest_open_elapsed_seconds"}
            return rest

        self.assertEqual(reader_part(failed), reader_part(read))

    def test_a_big_run_or_a_narrow_pane_is_drawn_as_the_tree(self) -> None:
        self.assertEqual(plugin_api.SMALL_GRAPH_LANES, dag_block.SMALL_GRAPH_LANES)
        small = plugin_api.delegation_drawing(parallel(plugin_api.SMALL_GRAPH_LANES), 60)
        big = plugin_api.delegation_drawing(parallel(plugin_api.SMALL_GRAPH_LANES + 1), 60)
        narrow = plugin_api.delegation_drawing(owner_mock(), 20)
        self.assertEqual((small["layout"], big["layout"], narrow["layout"]), ("box", "tree", "tree"))
        self.assertTrue(all(len("".join(seg["text"] for seg in line)) <= 20 for line in narrow["lines"]))
        self.assertLessEqual(len(big["lines"]), plugin_api.TREE_MAX_LINES)
        # The width asked for is kept inside the renderer's floor and a ceiling no pane reaches.
        self.assertEqual(plugin_api.delegation_drawing(owner_mock(), 2)["cols"], plugin_api.MIN_COLS)
        self.assertEqual(plugin_api.delegation_drawing(owner_mock(), 10_000)["cols"], plugin_api.MAX_COLS)

    def test_a_wide_character_segment_carries_the_cells_the_renderer_gave_it(self) -> None:
        """Mutation: drop `cells`, or send it for every segment."""
        drawing = plugin_api.delegation_drawing(nested(), 43)
        segments = [segment for line in drawing["lines"] for segment in line]
        wide = [segment for segment in segments if "cells" in segment]
        self.assertEqual([(segment["text"], segment["cells"]) for segment in wide], [("인증 모듈 문서 정리", 19)])
        self.assertTrue(all("cells" not in segment for segment in segments if segment["text"].isascii()))

    def test_a_drawing_that_fails_is_a_record_beside_a_hud_that_still_reads(self) -> None:
        graph = {**owner_mock(), "status": "active"}
        reader = plugin_api.load_reader()
        # A fresh payload per read, as the reader answers: the route adds the drawing to the one it is handed.
        with mock.patch.object(reader, "read_omh_hud", side_effect=lambda *_a, **_k: {"active": True, "delegation_graph": graph}):
            drawn = plugin_api.hud_payload(self.hermes_home, "s", cols=44)
            with mock.patch.object(plugin_api, "delegation_drawing", side_effect=ValueError("bad graph")):
                failed = plugin_api.hud_payload(self.hermes_home, "s", cols=44)
            inactive = {"active": True, "delegation_graph": {**graph, "status": "inactive"}}
            with mock.patch.object(reader, "read_omh_hud", side_effect=lambda *_a, **_k: dict(inactive)):
                quiet = plugin_api.hud_payload(self.hermes_home, "s", cols=44)
        self.assertEqual(drawn["delegation_drawing"].get("layout"), "box", drawn["delegation_drawing"])
        self.assertEqual(failed["delegation_drawing"], {"error": "ValueError: bad graph", "schema_version": "omh_desktop_dag/v1"})
        self.assertTrue(failed["active"])
        self.assertNotIn("delegation_drawing", quiet)

    def test_hud_payload_reads_an_empty_hermes_home_without_raising_or_writing(self) -> None:
        before = sorted(str(path) for path in self.root.rglob("*"))
        payload = plugin_api.hud_payload(self.hermes_home, "")
        self.assertEqual(sorted(str(path) for path in self.root.rglob("*")), before)
        self.assertEqual(payload["schema_version"], "omh_hud/v1")
        self.assertNotIn("error", payload)
        self.assertIsInstance(payload["display"]["line"], str)
        self.assertTrue(payload["display"]["line"].startswith("[omh] "))
        self.assertIsInstance(payload["display"]["widget_lines"], list)
        self.assertIsInstance(payload["display"]["todo_lines"], list)
        self.assertEqual(payload["privacy"], "metadata_only")
        json.dumps(payload)

    def test_hud_payload_scopes_the_plan_to_the_session_the_app_names(self) -> None:
        payload = plugin_api.hud_payload(self.hermes_home, "  20260924_101010_abc123  ")
        self.assertNotIn("error", payload)
        # Naming a session makes the todo session-scoped: an empty home has
        # no record for it, which is `absent`, never a most-recent-TUI guess.
        self.assertEqual(payload["todo"]["status"], "absent")

    def test_hud_payload_answers_a_reader_failure_with_an_error_record(self) -> None:
        empty_bundle = self.root / "not-a-bundle"
        empty_bundle.mkdir()
        payload = plugin_api.hud_payload(self.hermes_home, "", bundle_root=empty_bundle)
        self.assertEqual(payload["schema_version"], "omh_desktop_hud/v1")
        self.assertTrue(payload["error"].startswith("FileNotFoundError: "))
        self.assertNotIn("display", payload)
        # A load that failed leaves no half-initialised module behind (#1623).
        self.assertNotIn("omh_desktop_bundle.runtime_reader", sys.modules)

    def test_hud_payload_answers_a_reader_exception_with_its_class_and_message(self) -> None:
        with mock.patch.object(plugin_api, "load_reader", side_effect=RuntimeError("store is unreadable")):
            payload = plugin_api.hud_payload(self.hermes_home, "")
        self.assertEqual(
            payload,
            {"error": "RuntimeError: store is unreadable", "schema_version": "omh_desktop_hud/v1"},
        )

    def test_concurrent_first_polls_share_one_load_and_answer_no_error_records(self) -> None:
        # Hermes serves the route from a thread pool: two windows polling at
        # once both find a cold cache. The module is registered before it has
        # executed, so without the load lock the second poll takes the
        # half-initialised module and answers a reader error for a healthy
        # backend.
        plugin_api._forget_reader_package()
        workers = 8
        barrier = threading.Barrier(workers)
        payloads: list[dict | None] = [None] * workers

        def poll(index: int) -> None:
            barrier.wait()
            payloads[index] = plugin_api.hud_payload(self.hermes_home, "20260924_101010_abc123")

        threads = [threading.Thread(target=poll, args=(index,)) for index in range(workers)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual([payload["error"] for payload in payloads if "error" in payload], [])
        self.assertEqual({payload["schema_version"] for payload in payloads}, {"omh_hud/v1"})
        readers = [plugin_api.load_reader(BUNDLE) for _ in range(workers)]
        self.assertEqual({id(reader) for reader in readers}, {id(readers[0])})

    def test_resolve_hermes_home_asks_the_host_first(self) -> None:
        host = types.ModuleType("hermes_constants")
        host.get_hermes_home = lambda: str(self.root / "host-home")
        with patch_modules({"hermes_constants": host}):
            with mock.patch.dict(os.environ, {"HERMES_HOME": str(self.hermes_home)}):
                self.assertEqual(plugin_api.resolve_hermes_home(), self.root / "host-home")

    def test_resolve_hermes_home_falls_back_to_the_env_then_the_default(self) -> None:
        # `None` in sys.modules makes the import raise wherever this runs, so
        # the fallback branch is pinned on a host with Hermes on its path too.
        with patch_modules({"hermes_constants": None}):
            with mock.patch.dict(os.environ, {"HERMES_HOME": str(self.hermes_home)}):
                self.assertEqual(plugin_api.resolve_hermes_home(), self.hermes_home)
            with mock.patch.dict(os.environ, {"HERMES_HOME": "", "HERMES_DATA_DIR_SUFFIX": ""}):
                expected = (
                    Path(os.environ["LOCALAPPDATA"]) / "hermes"
                    if os.name == "nt"
                    else Path.home() / ".hermes"
                )
                self.assertEqual(plugin_api.resolve_hermes_home(), expected)

    def test_resolve_hermes_home_uses_windows_default_without_host_or_env(self) -> None:
        local_appdata = self.root / "local-appdata"
        with patch_modules({"hermes_constants": None}):
            with mock.patch.dict(
                os.environ,
                {"HERMES_HOME": "", "LOCALAPPDATA": str(local_appdata), "HERMES_DATA_DIR_SUFFIX": "-test"},
            ):
                with mock.patch.object(plugin_api.sys, "platform", "win32"):
                    self.assertEqual(
                        plugin_api.resolve_hermes_home(),
                        local_appdata / "hermes-test",
                    )

    def test_resolve_hermes_home_fallback_matches_the_bundle_platform_default(self) -> None:
        # plugin_api.py is imported standalone, so its platform default is a
        # copy of runtime_paths.platform_default_hermes_home. Pin the copy to
        # the original on every branch so the two cannot drift apart.
        local_appdata = self.root / "local-appdata"
        cases = (
            ("win32", {"LOCALAPPDATA": str(local_appdata), "HERMES_DATA_DIR_SUFFIX": ""}),
            ("win32", {"LOCALAPPDATA": str(local_appdata), "HERMES_DATA_DIR_SUFFIX": "-dev"}),
            ("win32", {"LOCALAPPDATA": "", "HERMES_DATA_DIR_SUFFIX": ""}),
            ("linux", {"HERMES_DATA_DIR_SUFFIX": ""}),
            ("darwin", {"HERMES_DATA_DIR_SUFFIX": "-dev"}),
        )
        with patch_modules({"hermes_constants": None}):
            for platform, env in cases:
                with self.subTest(platform=platform, env=env), \
                        mock.patch.dict(os.environ, {"HERMES_HOME": "", **env}), \
                        mock.patch.object(plugin_api.sys, "platform", platform), \
                        mock.patch.object(runtime_paths.sys, "platform", platform):
                    self.assertEqual(
                        plugin_api.resolve_hermes_home(),
                        runtime_paths.platform_default_hermes_home(),
                    )

    def test_router_exists_exactly_when_fastapi_does(self) -> None:
        # OMH declares no dependency on FastAPI; the route is the host's
        # surface, and the pure functions above are what OMH tests.
        self.assertEqual(hasattr(plugin_api, "router"), plugin_api.APIRouter is not None)
        if plugin_api.APIRouter is not None:
            self.assertEqual([route.path for route in plugin_api.router.routes], ["/hud"])

    def test_manifest_names_the_plugin_and_its_api_file_and_hides_the_dashboard_tab(self) -> None:
        # The browser dashboard (`hermes dashboard`) reads the same manifest
        # and registers a tab at `/<name>` loading `dist/index.js` for every
        # manifest not marked hidden; OMH ships no dashboard UI, so the tab
        # is hidden rather than a broken page.
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(manifest, {"name": "omh", "api": "plugin_api.py", "tab": {"hidden": True}})
        self.assertEqual(manifest["name"], _plugin_yaml_name())
        self.assertTrue((MANIFEST.parent / manifest["api"]).is_file())


class DesktopPluginFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = PLUGIN_JS.read_text(encoding="utf-8")

    def test_default_export_carries_the_hermes_plugin_shape(self) -> None:
        self.assertIn("export const PLUGIN_ID = 'omh'", self.source)
        self.assertIn("export default {", self.source)
        for field in ("id: PLUGIN_ID", "name: 'oh-my-hermes'", "description: '", "defaultEnabled: false", "register(ctx)"):
            self.assertIn(field, self.source, field)

    def test_only_the_three_shimmed_specifiers_are_imported(self) -> None:
        specifiers = {match.group(3) for match in IMPORT_SPECIFIER.finditer(self.source)}
        self.assertEqual(specifiers, ALLOWED_IMPORTS)
        # Hooks come from the app's React, never re-exported by the SDK.
        self.assertIn("import { useEffect, useState } from 'react'", self.source)

    def test_no_jsx_syntax_in_an_uncompiled_module(self) -> None:
        # The loader blob-imports the file as-is; a `<` anywhere is the one
        # character JSX needs, and the module is written without it.
        self.assertNotIn("<", self.source)
        self.assertNotIn(">", self.source)

    def test_the_renderer_reads_the_backend_route_and_the_manifest_names_match(self) -> None:
        self.assertIn("/hud", self.source)
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertIn(f"export const PLUGIN_ID = '{manifest['name']}'", self.source)

    def test_the_file_is_ascii_utf8_text_the_bundle_copier_can_hash(self) -> None:
        PLUGIN_JS.read_bytes().decode("utf-8")
        self.assertTrue(self.source.endswith("\n"))
        self.assertNotIn("\r", self.source)

    def test_the_file_stays_under_the_older_shells_size_limit(self) -> None:
        self.assertLess(PLUGIN_JS.stat().st_size, 512 * 1024)

    def test_the_stylesheet_is_prefixed_and_resolves_colours_through_theme_tokens(self) -> None:
        # Tailwind never scans a disk plugin, so every class the pane relies
        # on is its own, and DESIGN.md's "tokens, not literals" holds for it.
        start = self.source.index("export const PANE_CSS = `")
        css = self.source[start : self.source.index("`", start + len("export const PANE_CSS = `"))]
        selectors = re.findall(r"(?m)^\.([\w-]+)", css)
        self.assertTrue(selectors)
        self.assertTrue(all(name.startswith(("omh-pane", "omh-agent", "omh-bar")) for name in selectors), selectors)
        self.assertEqual(HEX_COLOUR.findall(css), [])
        self.assertIn("var(--ui-", css)
        # The strike on a finished item is a property of its label alone; a
        # decoration set any higher would reach the notes beside it.
        struck = [rule.strip() for rule in re.findall(r"([^\n{]+)\{[^}]*line-through", css)]
        self.assertEqual(struck, [".omh-pane-item[data-state=done] .omh-pane-item-label"])


# Every pane draws these five sections, in this order, whatever the payload says (owner, 2026-11-10).
SECTION_LABELS = ("USAGE", "CATCHES", "PLAN", "DAG", "AGENTS")
KOREAN_SECTION_LABELS = ("사용량", "잡아낸 실수", "계획", "DAG", "에이전트")
UNAVAILABLE = ["Not available: the OMH backend did not answer"]


def _split_at_dag(render: dict) -> tuple[list[dict], list[dict]]:
    """The pane's nodes above the DAG block (the usage board among them) and from its `DAG` header on."""
    nodes = render["structure"]
    head = next((at for at, node in enumerate(nodes) if node["className"] == "omh-pane-section-label" and node["text"] == "DAG"), len(nodes))
    return nodes[:head], nodes[head:]


@unittest.skipUnless(NODE, "node is not installed; the widget harness needs it")
class DesktopPluginNodeTests(unittest.TestCase):
    def test_node_accepts_the_file_as_an_es_module(self) -> None:
        # `node --check` on a `.js` copy silently passes JSX (it is read as
        # CommonJS and the check is skipped); the `.mjs` copy is the real gate.
        with TemporaryDirectory() as tmp:
            copy = Path(tmp) / "plugin.mjs"
            copy.write_bytes(PLUGIN_JS.read_bytes())
            completed = subprocess.run(
                [NODE, "--check", str(copy)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=120,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    _report: dict | None = None

    @classmethod
    def _drive(cls) -> dict:
        if cls._report is not None:
            return cls._report
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "sdk.mjs").write_text(SDK_SHIM, encoding="utf-8")
            (root / "react.mjs").write_text(REACT_SHIM, encoding="utf-8")
            (root / "jsx-runtime.mjs").write_text(JSX_SHIM, encoding="utf-8")
            shim_urls = {
                "@hermes/plugin-sdk": (root / "sdk.mjs").as_uri(),
                "react": (root / "react.mjs").as_uri(),
                "react/jsx-runtime": (root / "jsx-runtime.mjs").as_uri(),
            }
            plugin = root / "plugin.mjs"
            plugin.write_text(_rewrite_specifiers(PLUGIN_JS.read_text(encoding="utf-8"), shim_urls), encoding="utf-8")
            harness = root / "harness.mjs"
            harness.write_text(HARNESS, encoding="utf-8")
            scenarios = root / "scenarios.json"
            scenarios.write_text(json.dumps({**SCENARIOS, **_reader_scenarios(root)}), encoding="utf-8")
            formatter_cases = root / "formatters.json"
            formatter_cases.write_text(json.dumps(FORMATTER_CASES), encoding="utf-8")
            completed = subprocess.run(
                [NODE, str(harness), str(plugin), str(scenarios), str(formatter_cases)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=120,
                cwd=str(root),
            )
        if completed.returncode != 0:
            raise AssertionError(completed.stderr)
        cls._report = json.loads(completed.stdout.strip().splitlines()[-1])
        return cls._report

    def _pane(self, scenario: str) -> list[str]:
        return self._drive()["renders"][scenario]["byId"]["hud"]

    def _status(self, scenario: str) -> list[str]:
        return self._drive()["renders"][scenario]["byId"]["status"]

    def _sections(self, scenario: str, korean: bool = False) -> dict[str, list[str]]:
        """The pane's text per section, keyed by label, in order; `head` is what precedes the first."""
        pane = self._drive()["korean" if korean else "renders"][scenario]["byId"]["hud"]
        labels = KOREAN_SECTION_LABELS if korean else SECTION_LABELS
        out: dict[str, list[str]] = {"head": []}
        current = "head"
        at = 0
        while at < len(pane):
            if pane[at] in ("▾", "▸") and at + 1 < len(pane) and pane[at + 1] in labels:
                current = pane[at + 1]
                out[current] = []
                at += 2
                continue
            out[current].append(pane[at])
            at += 1
        return out

    def test_register_contributes_one_status_item_and_one_pane(self) -> None:
        report = self._drive()
        self.assertEqual(
            report["plugin"],
            {
                "id": "omh",
                "name": "oh-my-hermes",
                "description": "OMH plan, agent routes and status, read from the omh plugin backend inside the Hermes gateway.",
                "defaultEnabled": False,
            },
        )
        self.assertEqual(
            report["contributions"],
            [
                {"id": "status", "area": "statusBar.right", "order": 130},
                {"id": "hud", "area": "panes", "title": "omh", "data": {"placement": "right", "width": "320px"}},
            ],
        )

    def test_the_stylesheet_is_appended_on_register_and_removed_on_dispose(self) -> None:
        style = self._drive()["style"]
        self.assertEqual(style["afterRegister"], ["append:omh-desktop-pane-style"])
        self.assertEqual(style["afterDispose"], ["append:omh-desktop-pane-style", "remove:omh-desktop-pane-style"])
        self.assertIn(".omh-pane{", style["css"])
        self.assertEqual(HEX_COLOUR.findall(style["css"]), [])

    def test_the_query_polls_every_five_seconds_and_keeps_the_previous_answer(self) -> None:
        render = self._drive()["renders"]["open_with_payload"]
        self.assertEqual(render["refetchInterval"], 5000)
        self.assertTrue(render["enabled"])
        self.assertTrue(render["keepsPreviousData"], "a refetch keeps this chat's answer on screen")
        self.assertTrue(render["dropsOtherChat"], "another chat's answer is never shown under this one")
        self.assertEqual(render["queryKey"], ["omh", "hud", "20260924_101010_abc123", "", ""])
        self.assertEqual(render["restCalls"], ["/hud?session=20260924_101010_abc123"])

    def test_the_pane_draws_the_plan_and_the_agent_rows_structurally(self) -> None:
        pane = self._pane("open_with_payload")
        sections = self._sections("open_with_payload")
        self.assertEqual(list(sections), ["head", *SECTION_LABELS])
        self.assertEqual(sections["head"], ["OMH", "1 running", "this session", "2 tools · 4m 2s"])
        # The usage board leads: the stream's counts (no recorded row here), its cost marked as unvouched.
        self.assertEqual(sections["USAGE"][:4], ["9 calls", "stream", "Main", "+ subagents (0)"])
        self.assertEqual(sections["PLAN"], [
            "Desktop check", "1/3", "Research", "1/1", "✓", "Read the pane spec",
            "Build", "0/2", "●", "Draw the structured pane", "○", "Screenshot the result", "waiting: needs the app",
        ])
        self.assertEqual(sections["CATCHES"], ["Nothing caught in this session"])
        self.assertEqual(sections["DAG"], ["No DAG in this session", "A delegated workflow draws its graph here."])
        self.assertEqual(sections["AGENTS"], ["2", "2 subagents · 1 running"])
        # Structured blocks replace both the legacy lines and Desktop's native rows.
        for line in ESTABLISHED_PAYLOAD["display"]["widget_lines"] + ESTABLISHED_PAYLOAD["display"]["todo_lines"]:
            self.assertNotIn(line, pane)
        self.assertNotIn("a1b2c3d4", pane)
        self.assertNotIn("e5f6a7b8", pane)

    def test_every_scenario_draws_the_same_five_sections_in_one_order(self) -> None:
        """Mutation: drop a section that has nothing to say, or let a payload reorder them."""
        for name in SCENARIOS:
            with self.subTest(name=name):
                self.assertEqual(list(self._sections(name))[1:], list(SECTION_LABELS))
        for name in ("catches_and_lanes", "usage_board", "gateway_closed"):
            with self.subTest(korean=name):
                self.assertEqual(list(self._sections(name, korean=True))[1:], list(KOREAN_SECTION_LABELS))
        self.assertIn("export const SECTION_ORDER = ['usage', 'catches', 'plan', 'dag', 'agents']", PLUGIN_JS.read_text(encoding="utf-8"))

    def test_every_section_folds_and_remembers_it(self) -> None:
        structure = self._drive()["renders"]["catches_and_lanes"]["structure"]
        toggles = [node for node in structure if "omh-pane-section-toggle" in node["className"].split()]
        self.assertEqual(len(toggles), len(SECTION_LABELS), "one fold control per section")
        for toggle, label in zip(toggles, SECTION_LABELS):
            self.assertTrue(toggle["text"].startswith(f"▾{label}"), toggle["text"])
        self.assertTrue(all(node["text"].startswith("▾") for node in toggles), "every section starts open")
        source = PLUGIN_JS.read_text(encoding="utf-8")
        self.assertIn("const FOLD_STORE = 'omh-pane-folds'", source)

    def test_agent_rows_keep_the_secondary_figures_in_the_tooltip(self) -> None:
        render = self._drive()["renders"]["open_with_payload"]
        self.assertIn("2 subagents · 1 running", render["byId"]["hud"])
        self.assertIn("Each subagent is listed in Hermes Desktop's Agents panel.", render["tips"])
        self.assertEqual(render["alternates"], [])
        self.assertFalse(any("omh-agent-title" in node["className"] for node in render["structure"]))
        # Native row details belong to Desktop; OMH's route rows retain their figures in a Tip.
        route = self._drive()["renders"]["maestro_and_board"]
        self.assertIn("Refactor the router · (codex/maestro gpt-5.6) · 0 tok · $0.0000 (included)", route["tips"])
        self.assertNotIn("$0.0000 (included)", route["byId"]["hud"])

    def test_the_pane_draws_maestro_board_dag_and_a_finished_plan(self) -> None:
        sections = self._sections("maestro_and_board")
        self.assertEqual(sections["head"], [
            "OMH", "1 running", "1 blocked", "this session", "repeat x3 blocked", "board 2 queued, 1 running",
            "board dispatcher not seen", "yolo on",
        ])
        self.assertEqual(sections["PLAN"], ["Ship the pane", "✓ 1/2 (1 skipped)", "✓", "Build it", "–", "Benchmark it", "skipped: no bench harness"])
        self.assertEqual(sections["AGENTS"], [
            "2", "⠋", "Refactor the router", "run-42", "(codex/maestro gpt-5.6)", "running", "30s",
            "▲", "Triage the flaky suite", "kb-7", "kanban/unassigned(gpt-5.6:medium)", "review", "1m 1s", "+2 more",
        ])
        # A pane naming its chat never draws the home's runtime graph: it may be another session's.
        self.assertEqual(sections["DAG"], ["No DAG in this session", "A delegated workflow draws its graph here."])
        # Where no chat is named, the runtime graph is drawn as the same cards as a dag-ulw run, named for what it is.
        dag = self._sections("maestro_unnamed")["DAG"]
        self.assertEqual(dag[:3], ["1/3", "View", "runtime graph · 1 running · 1 waiting · 1 done"])
        self.assertEqual(dag[dag.index("▾ layer 1"):], [
            "▾ layer 1", "a", "—", "✓ done", "Start node", "b", "—", "● running", "Start node",
            "▾ layer 2", "c", "—", "○ waiting", "← b",
        ])

    def test_the_parallel_shot_chip_shows_only_a_count_of_two_or_more(self) -> None:
        # The TUI header's rule (`panels._shot_badge`): calls that never overlapped were no parallel shot.
        def chips(scenario: str) -> list[str]:
            return [text for text in self._pane(f"shot_{scenario}") if "parallel shot" in text]

        self.assertEqual(chips("chain_closed"), [])
        self.assertEqual(chips("chain_open"), [])
        self.assertEqual(chips("overlap_open"), ["parallel shot ×3"])
        for scenario in ("overlap_closed", "overlap_last_open"):
            with self.subTest(scenario=scenario):
                (chip,) = chips(scenario)
                self.assertRegex(chip, r"^parallel shot ×2 \(.+ ago\)$")

    def test_a_skipped_note_under_a_finished_item_is_not_struck_through(self) -> None:
        render = self._drive()["renders"]["maestro_and_board"]
        self.assertIn("skipped: no bench harness", render["byId"]["hud"])
        # The note is a sibling of the struck label, never its descendant.
        self.assertEqual(render["strikeLeaks"], [])

    def test_the_status_item_is_compact_and_reveals_the_pane_on_click(self) -> None:
        report = self._drive()["renders"]
        self.assertEqual(report["open_with_payload"]["byId"]["status"], ["OMH", "1 running", "plan 1/3"])
        self.assertEqual(report["open_with_payload"]["revealed"], ["omh:hud"])
        self.assertEqual(report["open_with_payload"]["statusDetail"], "OMH 2.0.5 · 1 running · 1 done · plan Desktop check 1/3")
        self.assertEqual(report["maestro_and_board"]["byId"]["status"], ["OMH", "1 running", "1 blocked"])
        self.assertEqual(report["no_todo_declared"]["byId"]["status"], ["OMH", "idle"])
        self.assertEqual(report["loading"]["byId"]["status"], [])
        self.assertEqual(report["gateway_closed"]["byId"]["status"], [])
        for render in report.values():
            self.assertLessEqual(len(render["byId"]["status"]), 3)

    def test_a_plan_todo_list_holds_keeps_only_its_recorded_reason(self) -> None:
        self.assertEqual(self._sections("native_held_waiting")["PLAN"],
                         ["in Hermes todos", "1 waiting", "○", "Screenshot the result", "waiting: needs the app"])
        self.assertNotIn("Draw the structured pane", self._pane("native_held_waiting"))
        self.assertIn("Draw the structured pane", self._pane("open_with_payload"))
        self.assertEqual(self._status("native_held_waiting"), ["OMH", "1 running"])

    def test_a_plan_todo_list_holds_with_nothing_omh_only_says_where_the_steps_are(self) -> None:
        pane = self._pane("native_held_quiet")
        self.assertEqual(self._sections("native_held_quiet")["PLAN"], ["in Hermes todos", "Steps are in the Hermes todos above the composer"])
        self.assertNotIn("Read the pane spec", pane)
        self.assertIn("2 subagents · 1 running", pane)
        self.assertEqual(self._status("native_held_quiet"), ["OMH", "1 running"])

    def test_an_undeclared_todo_is_said_rather_than_invented(self) -> None:
        sections = self._sections("no_todo_declared")
        self.assertEqual(sections["head"], ["OMH", "idle", "this session"])
        self.assertEqual(sections["PLAN"], ["No plan yet", "A workflow adds one when it starts."])
        self.assertEqual(sections["CATCHES"], ["Nothing caught in this session"])
        self.assertEqual(sections["DAG"], ["No DAG in this session", "A delegated workflow draws its graph here."])
        self.assertEqual(sections["AGENTS"], ["No subagents or routes in this session"])

    def test_a_reader_error_record_is_shown_as_a_quiet_notice(self) -> None:
        render = self._drive()["renders"]["reader_error"]
        self.assertEqual(render["byId"]["status"], ["OMH", "reader error"])
        sections = self._sections("reader_error")
        self.assertEqual(sections["head"], ["OMH", "reader error", "all sessions"])
        # Every section the reader feeds says it could not answer; the notice under them names why.
        for label in SECTION_LABELS[1:-1]:
            self.assertEqual(sections[label], UNAVAILABLE)
        self.assertEqual(sections["AGENTS"], [*UNAVAILABLE, "OMH backend: RuntimeBindingError: OMH home is not configured"])
        self.assertEqual(render["restCalls"], ["/hud"])

    def test_a_transport_error_degrades_to_backend_unavailable(self) -> None:
        render = self._drive()["renders"]["transport_error"]
        self.assertEqual(render["byId"]["status"], ["OMH", "unavailable"])
        sections = self._sections("transport_error")
        self.assertEqual(sections["head"], ["OMH", "unavailable", "all sessions"])
        self.assertEqual(sections["PLAN"], UNAVAILABLE)
        self.assertEqual(render["byId"]["hud"][-1], "OMH backend: HTTP 404: Plugin not found")

    def test_the_first_poll_reads_as_pending_in_every_section(self) -> None:
        sections = self._sections("loading")
        self.assertEqual(sections["head"], ["OMH", "this session"])
        for label in SECTION_LABELS[1:]:
            with self.subTest(label=label):
                self.assertEqual(sections[label], ["reading…"])

    def test_polling_waits_for_an_open_gateway(self) -> None:
        render = self._drive()["renders"]["gateway_closed"]
        self.assertFalse(render["enabled"])
        sections = self._sections("gateway_closed")
        self.assertEqual(sections["head"], ["OMH", "gateway connecting", "all sessions"])
        # Nothing has been asked yet, so nothing is said to be unavailable: the sections wait.
        for label in SECTION_LABELS[1:]:
            with self.subTest(label=label):
                self.assertEqual(sections[label], ["reading…"])

    def test_the_formatters_spell_figures_the_way_the_tui_widget_does(self) -> None:
        formatters = self._drive()["formatters"]
        self.assertEqual(formatters["tokenCountText"], ["77.0k", "184.8k", "1.0m", "999", "0", ""])
        self.assertEqual(formatters["elapsedText"], ["12s", "4m 2s", "2h 01m", ""])
        self.assertEqual(formatters["costSegmentText"], ["$0.0123", "~$0.0431", "$0.0000 (included)", "", ""])
        self.assertEqual(
            formatters["routeIdentity"],
            [
                "category:architect(claude-fable-5-1:xhigh)",
                "inherit(claude-opus-5:high)",
                "(codex/maestro gpt-5.6)",
                "category:quick(gpt-5.6:low fallback)",
                "category:deep(gpt-5.6:high inherit)",
                "kanban/unassigned(gpt-5.6:medium)",
                "gpt-5.6:medium",
            ],
        )
        self.assertEqual(
            formatters["hudStateLabel"],
            ["idle", "2 running · 1 blocked", "2 done", "3 running · 1 blocked"],
        )


    def test_idle_has_no_dot_and_scope_names_the_data_it_covers(self) -> None:
        renders = self._drive()["renders"]
        for name, scope in (("no_todo_declared", "this session"), ("global_idle", "all sessions")):
            with self.subTest(name=name):
                self.assertEqual(renders[name]["summary"], "idle")
                self.assertEqual(renders[name]["dots"], [])
                self.assertEqual(renders[name]["byId"]["hud"][:3], ["OMH", "idle", scope])
        self.assertEqual(renders["open_with_payload"]["dots"], [{"tone": "good"}])
        self.assertIn("oh-my-hermes 2.0.5", renders["no_todo_declared"]["tips"])
        self.assertNotIn("v2.0.5", renders["no_todo_declared"]["byId"]["hud"])
        self.assertEqual(self._drive()["formatters"]["scopeLabel"], ["this session", "all sessions"])

    def test_real_reader_payload_keeps_historical_runs_idle_but_fresh_runs_active(self) -> None:
        renders = self._drive()["renders"]
        old = renders["reader_old"]
        fresh = renders["reader_fresh"]
        self.assertEqual(old["runtime"]["workflow"], "fanout")
        self.assertIs(old["runtime"]["recent"], False)
        self.assertIs(old["active"], False)
        self.assertEqual(old["summary"], "idle")
        self.assertEqual(old["byId"]["hud"][:3], ["OMH", "idle", "all sessions"])
        self.assertEqual(old["byId"]["status"], ["OMH", "idle"])
        self.assertEqual(old["dots"], [])
        self.assertEqual(fresh["runtime"]["workflow"], "fanout")
        self.assertIs(fresh["runtime"]["recent"], True)
        self.assertIs(fresh["active"], True)
        self.assertNotEqual(fresh["summary"], "idle")

    def test_graph_drawn_native_rows_are_excluded_from_every_count(self) -> None:
        # A row the delegation graph draws leaves the subagent line, and its
        # lane is counted once in the header and status bar instead.
        renders = self._drive()["renders"]
        drawn = renders["graph_and_other"]
        plain = renders["two_without_graph"]
        for render, listed, running in ((drawn, 1, 2), (plain, 2, 2)):
            with self.subTest(listed=listed):
                tally = render["tally"]
                self.assertEqual(len(tally["subagents"]), listed)
                self.assertEqual(tally["running"], running)
                self.assertEqual(tally["subagentsRunning"], listed)
                self.assertEqual((tally["blocked"], tally["done"], tally["routes"]), (0, 0, []))
                self.assertEqual(render["summary"], f"{running} running")
                self.assertEqual(render["byId"]["hud"][:2], ["OMH", f"{running} running"])
                self.assertEqual(render["byId"]["status"], ["OMH", f"{running} running", "plan 1/3"])
        self.assertIn("1 subagent · 1 running", drawn["byId"]["hud"])
        self.assertIn("2 subagents · 2 running · +2 more", plain["byId"]["hud"])
        self.assertEqual(drawn["tally"]["hidden"], 0)
        self.assertEqual(plain["tally"]["hidden"], 2)
        self.assertEqual(self._drive()["formatters"]["agentTally"][0]["hidden"], 0)

    def test_skipped_steps_have_their_own_glyph_state_and_worked_progress(self) -> None:
        report = self._drive()
        self.assertEqual(report["formatters"]["itemGlyph"], ["✓", "–", "●", "○"])
        self.assertEqual(report["formatters"]["itemState"], ["skipped"])
        self.assertEqual(report["formatters"]["planProgress"], [
            {"worked": 1, "total": 2, "percent": 50, "allDone": True},
            {"worked": 0, "total": 0, "percent": 0, "allDone": False},
        ])
        structure = report["renders"]["maestro_and_board"]["structure"]
        skipped = [node for node in structure if node.get("state") == "skipped"]
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0]["text"], "–Benchmark itskipped: no bench harness")
        bars = [node for node in structure if node["className"] == "omh-pane-bar-fill"]
        self.assertEqual([(node["style"], node["done"]) for node in bars], [({"width": "50%"}, "true")])
        css = report["style"]["css"]
        self.assertIn(".omh-pane-bar-fill[data-done=true]{background:var(--omh-mark)}", css)
        self.assertIn(".omh-pane-item[data-state=skipped] .omh-pane-item-label{color:var(--omh-text-readable)}", css)
        self.assertEqual(report["formatters"]["foldLabels"], [{"earlier": "✓ 3 done", "later": "… 1 later task"}])

    def test_neutral_telemetry_is_muted_and_only_yolo_on_is_destructive(self) -> None:
        chips, findings = self._drive()["formatters"]["chipList"]
        self.assertFalse(any(chip["key"] == "yolo" for chip in chips))
        self.assertEqual(next(chip for chip in chips if chip["key"] == "tools"), {
            "key": "tools", "text": "2 tools · 4m 2s", "variant": "muted",
        })
        self.assertEqual(next(chip for chip in findings if chip["key"] == "yolo"), {
            "key": "yolo", "text": "yolo on", "variant": "destructive",
        })
        self.assertEqual({chip["key"]: chip["variant"] for chip in findings}, {
            "repeat": "warn", "board": "muted", "dispatcher": "warn", "yolo": "destructive",
        })
        self.assertIn({"text": "2 tools · 4m 2s", "variant": "muted"}, self._drive()["renders"]["open_with_payload"]["badges"])
        self.assertNotIn("yolo off", self._pane("open_with_payload"))

    def test_catches_use_the_tui_sentences_and_precede_the_plan(self) -> None:
        from omh.tui.panels import CATCH_EMOJI, _catch_sentence

        report = self._drive()
        expected = [_catch_sentence(entry) for entry in CATCHES]
        self.assertEqual(expected[0], "stopped a loop of 3 identical calls")
        self.assertEqual(report["formatters"]["catchSentence"], [*expected, "", ""])
        self.assertEqual(report["formatters"]["catchRows"], [[
            {"seq": entry["seq"], "emoji": CATCH_EMOJI[entry["kind"]], "text": sentence}
            for entry, sentence in zip(CATCHES, expected)
        ]])
        sections = self._sections("catches_and_lanes")
        self.assertEqual(list(sections)[1:], list(SECTION_LABELS))
        # A history, so its header says so and counts what it keeps.
        self.assertEqual(sections["CATCHES"][:2], ["earlier in this session", "6"])
        for sentence in expected:
            self.assertIn(sentence, sections["CATCHES"])
        self.assertEqual(self._sections("open_with_payload")["CATCHES"], ["Nothing caught in this session"])

    def test_inactive_delegation_says_so_and_a_settled_run_keeps_its_cards(self) -> None:
        views = self._drive()["formatters"]["delegationView"]
        self.assertEqual(views[:2], [None, None])
        self.assertTrue(views[2]["settled"])
        # The section is labelled DAG already; its run line does not say it twice.
        self.assertEqual(views[2]["summary"], "Pane refresh · done 1/2 · 1 failed")
        self.assertEqual(self._sections("inactive_lanes")["DAG"], ["No DAG in this session", "A delegated workflow draws its graph here."])
        settled = self._sections("settled_lanes")["DAG"]
        self.assertEqual(settled[:3], ["1/2", "View", "Pane refresh · done 1/2 · 1 failed"])
        # Finished, the lanes stay inspectable rather than collapsing into the line.
        self.assertIn("Settled child", settled)
        self.assertIn("Failed child", settled)
        live = self._sections("catches_and_lanes")["DAG"]
        self.assertIn("Pane refresh · 1 running", live)
        self.assertIn("Graph-drawn child", live)

    def test_every_graph_is_drawn_as_cards_and_never_as_text(self) -> None:
        """Mutation: fall back to the backend's text drawing for a graph without topology, past a lane count, or on
        a failed drawing; or send the pane's width for one."""
        renders = self._drive()["renders"]
        for name in ("drawn_graph", "wide_drawn", "drawing_error", "settled_lanes", "settled_drawn", "graph_and_other",
                     "failed_lane", "catches_and_lanes", "dag_cards", "fanout_cards", "dag_beyond_cards", "maestro_unnamed"):
            with self.subTest(name=name):
                classes = {name for node in renders[name]["structure"] for name in node["className"].split()}
                self.assertTrue({"omh-pane-dv-canvas", "omh-pane-dv-card"} <= classes)
                self.assertFalse({"omh-pane-dag", "omh-pane-lane", "omh-pane-dag-card"} & classes)
                self.assertNotIn("cols=", " ".join(renders[name]["restCalls"]))
        source = PLUGIN_JS.read_text(encoding="utf-8")
        for gone in ("DAG_CARD_LIMIT", "measureCells", "delegation_drawing", "DEFAULT_DRAWING_CELLS"):
            self.assertNotIn(gone, source)
        css = self._drive()["style"]["css"]
        self.assertIn("container-type:inline-size", css)
        self.assertNotIn(".omh-pane-dag{", css)

    def test_a_session_with_two_dag_runs_offers_to_switch_and_follows_the_newest_by_default(self) -> None:
        choices = self._drive()["formatters"]["dagRunChoices"]
        options = [
            {"run": "new", "label": "supplement · running · 3 nodes · latest"},
            {"run": "old", "label": "main plan · done · 31 nodes"},
        ]
        self.assertEqual(choices[0], {"newest": "new", "current": "new", "options": options})
        self.assertEqual(choices[1]["current"], "old")  # a pick is the run drawn, the newest still what clears it
        self.assertEqual(choices[1]["newest"], "new")
        self.assertEqual(choices[2]["current"], "new")  # a run the backend no longer lists is the newest
        self.assertIsNone(choices[3])  # one run is nothing to choose
        self.assertIsNone(choices[4])  # a payload with no runs, as a host's older backend sends

    def test_the_dag_section_carries_the_menu_only_where_there_are_two_runs(self) -> None:
        shown = self._pane("dag_two_runs")
        self.assertIn("supplement · running · 3 nodes · latest", shown)
        # The menu is drawn in the pane's own tokens and stays shut: the run drawn is the one the button names.
        self.assertNotIn("main plan · done · 31 nodes", shown)
        self.assertFalse([line for line in self._pane("dag_cards") if "nodes · latest" in line])

    def test_the_hud_path_names_the_chat_and_the_dag_run_only(self) -> None:
        self.assertEqual(self._drive()["formatters"]["hudPath"],
                         ["/hud", "/hud?session=s%201", "/hud", "/hud?session=s&dag_run=r%201",
                          "/hud?session=s&dag_open=1%2C4"])

    def test_drawing_roles_take_the_tui_meaning_of_each_state(self) -> None:
        self.assertEqual(self._drive()["formatters"]["segmentTone"], [
            "accent", "ok", "ok", "muted", "error", "warn", "error", "mark", "mark", "accent", "secondary",
            "mark", "tertiary", "", "",
        ])

    def test_the_pane_keeps_desktops_sans_and_takes_the_tui_mood_from_tokens(self) -> None:
        """Mutation: set the pane in monospace, drop a mood token, or let a word take the faintest text token."""
        css = self._drive()["style"]["css"]
        pane = css[css.index(".omh-pane{") : css.index("}", css.index(".omh-pane{"))]
        self.assertIn("font-family:var(--font-sans", pane)
        for token in ("--omh-warn:color-mix(in srgb,var(--ui-yellow) 72%,var(--ui-text-primary))",
                      "--omh-edge:color-mix(in srgb,var(--ui-purple) 55%,var(--background))",
                      "--omh-label:color-mix(in srgb,var(--ui-orange) 65%,var(--ui-text-primary))"):
            self.assertIn(token, css)
        self.assertIn(".omh-pane-warn{color:var(--omh-warn)}", css)
        self.assertIn(".omh-pane-muted{color:var(--omh-text-readable)}", css)
        pane_rules = css[: css.index(".omh-bar{")]
        self.assertNotIn("color:var(--ui-text-quaternary)", pane_rules, "no pane word takes the faintest token")
        self.assertNotRegex(css, r"box-shadow|text-shadow|filter:")
        # The one gradient the pane has is a node card's: its wash, and the running border that flows (owner, 2026-11-09).
        rules = [rule for rule in css.split("}") if "gradient" in rule]
        self.assertTrue(rules)
        self.assertTrue(all(".omh-pane-dv-card" in rule for rule in rules), rules)

    def test_route_and_state_are_separate_fixed_grid_cells(self) -> None:
        report = self._drive()
        subrows = [node for node in report["renders"]["maestro_and_board"]["structure"] if node["className"] == "omh-agent-sub"]
        self.assertEqual(len(subrows), 2)
        for row, state in zip(subrows, ("running", "review")):
            self.assertEqual(len(row["cells"]), 3)
            self.assertIn("omh-agent-route", row["cells"][0]["className"])
            self.assertIn("omh-agent-state", row["cells"][1]["className"])
            self.assertEqual(row["cells"][1]["text"], state)
            self.assertIn("omh-agent-figure", row["cells"][2]["className"])
        self.assertIn("omh-pane-tertiary", subrows[1]["cells"][1]["className"])
        css = report["style"]["css"]
        self.assertIn("grid-template-columns:minmax(0,1fr) 64px 52px", css)
        self.assertIn(".omh-agent-route{min-width:0;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}", css)
        self.assertIn(".omh-agent-state{overflow:hidden;white-space:nowrap;text-overflow:ellipsis}", css)
        self.assertIn("kanban/unassigned(gpt-5.6:medium)", report["renders"]["maestro_and_board"]["tips"])

    def test_edges_are_pluralized_and_dependency_waits_are_humanized(self) -> None:
        report = self._drive()
        self.assertEqual(report["formatters"]["humanState"], ["waiting", "done", "planned"])
        self.assertEqual(report["formatters"]["t"][:2], ["layer 1 · 1 node", "layer 1 · 2 nodes"])
        # A card names what it waits on by the lane it follows, and never in the reader's state word.
        self.assertIn("← b", self._sections("maestro_unnamed")["DAG"])
        self.assertNotIn("blocked_by_dependency", " ".join(self._pane("maestro_unnamed")))
        self.assertEqual(report["formatters"]["wordTone"], ["accent", "warn", "error", "muted", "tertiary"])
        for token in ("--ui-cyan", "--ui-success"):
            self.assertNotIn(token, report["style"]["css"])
        # Green is kept for done DAG work alone: the card border and the folded layer's tally.
        self.assertIn("--omh-ok:var(--ui-green)", report["style"]["css"])
        self.assertIn(".omh-pane-dv-card[data-tone=ok]{--dv-c:var(--omh-ok)}", report["style"]["css"])

    def test_a_live_run_with_nothing_counted_is_drawn_in_the_accent(self) -> None:
        report = self._drive()
        live = report["renders"]["runtime_only"]
        self.assertEqual(live["byId"]["hud"][:2], ["OMH", "active"])
        self.assertEqual(live["byId"]["status"], ["OMH", "active"])
        state = next(node for node in live["structure"] if "omh-pane-state-seg" in node["className"])
        self.assertIn("omh-pane-accent", state["className"])
        self.assertEqual([dot["tone"] for dot in live["dots"]], ["good"])
        idle = report["renders"]["global_idle"]
        state = next(node for node in idle["structure"] if "omh-pane-state-seg" in node["className"])
        self.assertIn("omh-pane-tertiary", state["className"])
        self.assertEqual(idle["dots"], [])

    def test_a_failed_lane_is_its_own_word_in_the_header_and_the_status_bar(self) -> None:
        renders = self._drive()["renders"]
        failed = renders["failed_lane"]
        self.assertEqual(failed["tally"]["failed"], 1)
        self.assertEqual(failed["tally"]["blocked"], 0)
        self.assertEqual(failed["byId"]["hud"][:3], ["OMH", "1 running", "1 failed"])
        self.assertEqual(failed["byId"]["status"], ["OMH", "1 running", "1 failed"])
        segments = [node for node in failed["structure"] if "omh-pane-state-seg" in node["className"]]
        self.assertEqual([node["text"] for node in segments], ["1 running", "1 failed"])
        self.assertIn("omh-pane-accent", segments[0]["className"])
        self.assertIn("omh-pane-error", segments[1]["className"])
        self.assertEqual([dot["tone"] for dot in failed["dots"]], ["good"])
        # With nothing running, failed leads, blocked follows, and the dot is red.
        held = renders["failed_without_running"]
        self.assertEqual(held["byId"]["hud"][:3], ["OMH", "1 failed", "1 blocked"])
        self.assertEqual(held["byId"]["status"], ["OMH", "1 failed", "1 blocked"])
        self.assertEqual([dot["tone"] for dot in held["dots"]], ["bad"])
        # A failed route row counts as failed, a blocked one as blocked.
        rows = renders["failed_row"]
        self.assertEqual((rows["tally"]["failed"], rows["tally"]["blocked"]), (1, 1))
        self.assertEqual(rows["byId"]["status"], ["OMH", "1 failed", "1 blocked"])
        self.assertIn("1 failed", rows["statusDetail"])
        # The header and the status bar never disagree.
        for name, render in renders.items():
            data = SCENARIOS.get(name, {}).get("data")
            if not data or not data.get("active") or data.get("error"):
                continue
            with self.subTest(name=name):
                head = [node["text"] for node in render["structure"] if "omh-pane-state-seg" in node["className"]]
                self.assertEqual(head, render["byId"]["status"][1 : 1 + len(head)])

    def test_a_korean_host_reads_the_failed_count_in_korean(self) -> None:
        korean = self._drive()["korean"]["failed_lane"]
        self.assertEqual(korean["byId"]["hud"][:3], ["OMH", "1개 실행 중", "1개 실패"])
        self.assertEqual(korean["byId"]["status"], ["OMH", "1개 실행 중", "1개 실패"])

    def test_text_the_user_reads_is_darker_than_the_hint_role(self) -> None:
        css = self._drive()["style"]["css"]
        self.assertIn("--omh-text-readable:color-mix(in srgb,var(--ui-text-secondary),var(--ui-text-tertiary))", css)
        for rule in (".omh-pane-scope{", ".omh-pane-item-note{", ".omh-pane-summary{", ".omh-pane-notice{", ".omh-pane-tertiary{"):
            with self.subTest(rule=rule):
                body = css[css.index(rule) : css.index("}", css.index(rule))]
                self.assertIn("color:var(--omh-text-readable)", body)

    def test_row_tool_counts_use_the_right_plural(self) -> None:
        extras = [figures["extras"] for figures in self._drive()["formatters"]["rowFigures"]]
        self.assertEqual(extras, [["0 tools"], ["1 tool"], ["2 tools"]])

    def test_state_words_are_translated_but_tones_keep_the_canonical_word(self) -> None:
        words = self._drive()["formatters"]["stateWord"]
        self.assertEqual(words, ["running", "waiting", "review", "some new state", "", "실패", "검토"])

    def test_every_reader_state_and_reason_has_a_korean_word(self) -> None:
        rows = self._drive()["formatters"]["koreanStates"][0]
        self.assertEqual({row[0] for row in rows}, FANOUT_AND_STUCK_STATES)
        for state, english, korean in rows:
            with self.subTest(state=state):
                self.assertTrue(english)
                self.assertNotIn("_", english)
                self.assertNotEqual(korean, english)
                self.assertNotRegex(korean, r"[A-Za-z]{3,}")
        reasons = self._drive()["formatters"]["reasonWord"]
        self.assertEqual(reasons[:3], ["no new output", "prompt at end", "repeated error: ENOENT x"])
        self.assertEqual(reasons[3:], ["새 출력 없음", "끝에 입력 요청", "계정 한도: 429 slow down", "something else"])

    def test_a_korean_host_reads_state_words_in_korean(self) -> None:
        korean = self._drive()["korean"]
        lanes = " ".join(korean["catches_and_lanes"]["byId"]["hud"])
        self.assertIn("에이전트", lanes)
        self.assertIn("Pane refresh · 1 실행 중", lanes)
        self.assertNotIn("1 running", lanes)
        board = korean["maestro_and_board"]["byId"]["hud"]
        for english in ("running", "review", "completed", "failed"):
            self.assertNotIn(english, board)
        self.assertIn("검토", board)
        self.assertIn("실행 중", board)
        self.assertIn("✓ 완료", korean["maestro_unnamed"]["byId"]["hud"])
        self.assertIn("Pane refresh · 완료 1/2 · 1 실패", korean["settled_lanes"]["byId"]["hud"])
        self.assertEqual(korean["gateway_closed"]["byId"]["hud"][:2], ["OMH", "게이트웨이 연결 중"])
        tips = " ".join(korean["maestro_and_board"]["tips"])
        self.assertIn("0 토큰", tips)
        self.assertIn("$0.0000 (포함)", tips)
        self.assertIn("kanban/미배정(gpt-5.6:medium)", tips)
        self.assertNotIn(" tok", tips)
        self.assertNotIn("included", tips)

    @staticmethod
    def _classed(render: dict, name: str) -> list[str]:
        """The texts of one class within the DAG block; the usage board above it reuses the figure cells' classes."""
        return [node["text"] for node in _split_at_dag(render)[1] if name in node["className"].split()]

    @staticmethod
    def _board(render: dict, name: str) -> list[str]:
        """The texts of one class above the DAG block: the usage board's."""
        return [node["text"] for node in _split_at_dag(render)[0] if name in node["className"].split()]

    def test_a_dag_ulw_run_is_drawn_as_cards_with_the_figures_the_backend_read(self) -> None:
        """Mutation: count the output in the hit rate, drop a lane's estimate mark, or draw the backend text instead."""
        render = self._drive()["renders"]["dag_cards"]
        self.assertEqual(self._classed(render, "omh-pane-dv-kpi-label"), ["Tokens", "Cache hit", "Cost", "Node time"])
        # 1600 + 9300 + 1100 prompt + 630 out; 9300 / 12000 read; two priced lanes, one of them estimated; 47s + 31s.
        self.assertEqual(self._classed(render, "omh-pane-dv-kpi-value"), ["12.6k", "77.5%", "~$0.0184", "1m 18s"])
        self.assertEqual(
            self._classed(render, "omh-pane-dv-kpi-sub"),
            # Each share names the whole it is of: the run's four lanes, two of them priced and timed.
            ["↓630 out · 12.0k in", "9.3k of 12.0k prompt", "2/4 nodes priced", "2/4 nodes timed"],
        )
        self.assertEqual(self._classed(render, "omh-pane-dv-title"), ["Write a.txt", "Write b.txt", "Sum", "Check"])
        self.assertEqual(self._classed(render, "omh-pane-dv-path-l"), ["Critical path", "Bottlenecks"])
        rows = [[cell["text"] for cell in node["cells"]] for node in render["structure"] if "omh-pane-dv-mrow" in node["className"].split()]
        self.assertEqual(rows[1:], [["claude-haiku-5-5", "2", "12.6k", "77.5%", "~$0.0184"]])
        links = [node["text"] for node in render["structure"] if node["className"] == "omh-pane-dv-chip omh-pane-dv-link"]
        self.assertEqual(links, ["Write a.txt", "Sum", "Check", "Sum (blocks 1)"])
        self.assertNotIn("omh-pane-dag", {node["className"] for node in render["structure"]}, "no second drawing beside the cards")

    def test_a_fanout_run_uses_cards_without_claiming_missing_topology(self) -> None:
        render = self._drive()["renders"]["fanout_cards"]
        self.assertEqual(self._classed(render, "omh-pane-dv-title"), ["Write a.txt", "Write b.txt", "Sum", "Check"])
        self.assertEqual(self._classed(render, "omh-pane-dv-path-l"), [])
        self.assertEqual(self._classed(render, "omh-pane-dv-kpi-label"), ["Tokens", "Cache hit", "Cost", "Node time"])
        self.assertNotIn("omh-pane-dag", {node["className"] for node in render["structure"]})

    def test_a_large_run_is_cards_folded_past_its_frontier(self) -> None:
        """Mutation: fall back to text past a lane count, or draw every far-off layer open by default."""
        render = self._drive()["renders"]["dag_beyond_cards"]
        dag = self._sections("dag_beyond_cards")["DAG"]
        # Nothing started: the first layer and the two after it stay open; the fourteen beyond wait behind chips.
        self.assertEqual(self._classed(render, "omh-pane-dv-title"), ["Step 0", "Step 1", "Step 2"])
        chips = self._classed(render, "omh-pane-dv-layer-name")
        self.assertEqual((len(chips), chips[0], chips[-1]), (14, "▸ layer 4 · 1 node", "▸ layer 17 · 1 node"))
        self.assertIn("+3 more", dag)
        # Nothing counted yet: a dash and a short note, never `0 of 0 prompt` or `sum of 0 nodes`.
        self.assertEqual(self._classed(render, "omh-pane-dv-kpi-value"), ["—", "—", "—", "—"])
        self.assertEqual(self._classed(render, "omh-pane-dv-kpi-sub"), ["", "", "no usage yet", ""])
        self.assertIn("Step 0 (blocks 16)", self._classed(render, "omh-pane-dv-chip-t"))
        # The fold modes are buttons over the cards, not entries in the View menu.
        self.assertEqual(self._classed(render, "omh-pane-seg-b"), ["Auto", "Focus", "Unfold all", "Fold all"])

    def test_the_view_menu_is_drawn_opaque(self) -> None:
        """Mutation: draw the menu in the card token, which is nearly clear and lets the pane show through."""
        css = self._drive()["style"]["css"]
        menu = css[css.index(".omh-pane-pick-menu{") : css.index("}", css.index(".omh-pane-pick-menu{"))]
        self.assertIn("background:var(--ui-bg-elevated,var(--background))", menu)

    def test_layers_fold_by_the_chosen_mode_the_persons_own_folds_and_the_open_lane(self) -> None:
        """Mutation: fold the running layer, ignore a layer the person opened or folded, or fold the open lane's layer."""
        auto, active, opened, closed, kept_open, picked, kept_folded, small, untouched = self._drive()["formatters"]["foldsOf"]
        self.assertEqual(auto, [0, 1, 2, 6, 7, 8, 9, 10, 11], "finished layers, and those past the frontier and two more")
        self.assertEqual(active, [0, 1, 5, 6, 7, 8, 9, 10, 11], "focus: the running layer and the layers either side")
        self.assertEqual(opened, [])
        self.assertEqual(closed, [0, 1, 2, 4, 5, 6, 7, 8, 9, 10, 11], "fold all still leaves the running layer open")
        self.assertEqual(kept_open, [0, 2, 6, 7, 8, 9, 10, 11])
        self.assertEqual(picked, [0, 1, 2, 6, 8, 9, 10, 11])
        self.assertEqual(kept_folded, [4])
        self.assertEqual(small, [], "a small run reads whole")
        self.assertEqual(untouched, list(range(3, 17)))

    def test_a_graph_cut_by_layer_keeps_its_layers_and_counts_what_they_lost(self) -> None:
        """Mutation: lay a cut graph out from its kept edges, or count a layer by its kept lanes only."""
        cut, _ = self._drive()["formatters"]["cutLayers"]
        self.assertEqual(cut["layers"], [[], ["d:r:b"], ["d:r:c"], ["d:r:d"]], "a lane stays in the layer the reader numbered")
        self.assertEqual(cut["summaries"], [[4, 4, "done"], [3, 2, "done"], [1, 0, "running"], [1, 0, "waiting"]])
        self.assertEqual(cut["folds"], [0, 1], "nine lanes in all, so `auto` folds the settled layers")

    def test_an_edge_over_lanes_the_reader_cut_is_kept_and_drawn_as_implied(self) -> None:
        """Mutation: drop the reader's `elided` mark, so a path over cut lanes reads as one dependency step."""
        (edges,) = self._drive()["formatters"]["elidedEdges"]
        self.assertEqual(edges, [{"from": "d:r:b", "to": "d:r:d", "kind": "depends_on", "elided": True}])
        css = self._drive()["style"]["css"]
        self.assertIn(".omh-pane-dv-edge[data-elided=true]{stroke-dasharray:1 3;opacity:.55}", css)
        _, tail = self._drive()["formatters"]["cutLayers"]
        self.assertEqual(tail["layers"], [[], ["d:r:b"], ["d:r:c"], []], "`layer_count` sets the depth, not the lanes drawn")
        self.assertEqual(tail["summaries"][3], [1, 1, "waiting"])

    def test_the_status_item_and_the_pane_poll_under_one_key_with_layers_open(self) -> None:
        """Mutation: keep the open layers in each `useHud`'s own state, so two keys make two full reads per poll."""
        (keys,) = self._drive()["formatters"]["sharedOpenKeys"]
        self.assertEqual(keys, [["status", ["omh", "hud", "s1", "", "1,2"]], ["hud", ["omh", "hud", "s1", "", "1,2"]]])

    def test_a_run_too_deep_to_send_reads_as_its_counts_not_as_no_dag(self) -> None:
        """Mutation: take a graph with no lanes as no graph, so an active 500-layer run reads `No DAG in this session`."""
        dag = self._sections("dag_counts_only")["DAG"]
        self.assertNotIn("No DAG in this session", dag)
        self.assertIn("delegation · 2 running · 1 failed · 497 done", dag)
        self.assertIn("500 nodes in 500 layers: too many to draw here", dag)

    def test_a_cut_runs_shares_name_the_whole_run(self) -> None:
        """Mutation: divide by the lanes shown, so a 9-lane run with 3 drawn reads `2/3 nodes priced`."""
        render = self._drive()["renders"]["dag_cut_cards"]
        self.assertIn("2/9 nodes priced", self._classed(render, "omh-pane-dv-kpi-sub"))

    def test_a_folded_layer_takes_its_lanes_edges_once(self) -> None:
        first, middle, none = self._drive()["formatters"]["foldedEdges"]
        self.assertEqual(first, ["layer:0>d:r:sum", "d:r:sum>d:r:chk"], "two lanes into one chip are one edge")
        self.assertEqual(middle, ["d:r:a>layer:1", "d:r:b>layer:1", "layer:1>d:r:chk"])
        self.assertEqual(none, ["d:r:a>d:r:sum", "d:r:b>d:r:sum", "d:r:sum>d:r:chk"])

    def test_the_dag_view_options_default_and_survive_a_bad_store(self) -> None:
        defaults, chosen, bad = self._drive()["formatters"]["dagViewOptions"]
        self.assertEqual(defaults, {"fold": "auto", "figures": True, "stats": True, "implied": False, "compact": False})
        self.assertEqual(chosen, {"fold": "closed", "figures": False, "stats": True, "implied": True, "compact": False})
        self.assertEqual(bad, defaults, "an unknown mode or a stray value reads as the default")
        # The menu offers every mode and every switch, and the choice is kept across reloads.
        menu = " ".join(self._drive()["renders"]["dag_cards"]["byId"]["hud"])
        self.assertIn("View", menu)
        self.assertIn("const DAG_VIEW_STORE = 'omh-pane-dag-view'", PLUGIN_JS.read_text(encoding="utf-8"))

    def test_a_settled_dag_ulw_run_keeps_its_cards_under_its_run_line(self) -> None:
        """Mutation: replace a finished run's cards by its summary line (the node summaries and figures are for debugging)."""
        structure = self._drive()["renders"]["dag_settled"]["structure"]
        lines = [node["text"] for node in structure if node["className"] == "omh-pane-run"]
        self.assertEqual(lines, ["Write and sum · done 2/2"])
        self.assertTrue({"omh-pane-dv-kpis", "omh-pane-dv-canvas", "omh-pane-dv-card"}
                        <= {name for node in structure for name in node["className"].split()})
        # The same line a running run carries: finishing changes the words, not the shape.
        self.assertEqual([node for node in structure if node["className"] == "omh-pane-dv-fold"], [])

    def test_a_settled_dag_ulw_run_keeps_its_figures_under_the_line(self) -> None:
        """#2684. Keep recorded figures, and keep uncounted nodes inspectable without inventing usage."""
        render = self._drive()["renders"]["dag_settled"]
        run_kpis = [node for node in render["structure"]
                    if "omh-pane-dv-kpis" in node["className"].split() and "omh-pane-ub-kpis" not in node["className"]]
        self.assertEqual(len(run_kpis), 1)
        labels = [node["text"] for node in render["structure"] if "omh-pane-dv-kpi-label" in node["className"].split()]
        values = [node["text"] for node in render["structure"] if "omh-pane-dv-kpi-value" in node["className"].split()]
        figures = dict(zip(labels[-4:], values[-4:]))
        self.assertEqual(figures, {"Tokens": "7.7k", "Cache hit": "80.5%", "Cost": "$0.0123", "Node time": "59s"})
        uncounted = self._drive()["renders"]["dag_settled_uncounted"]["structure"]
        self.assertTrue([node for node in uncounted if node["className"] == "omh-pane-dv-card"])
        uncounted_values = [node["text"] for node in uncounted if "omh-pane-dv-kpi-value" in node["className"].split()]
        self.assertEqual(uncounted_values[-4:], ["—", "—", "—", "59s"])

    def test_a_partly_priced_run_marks_its_cost_as_a_floor(self) -> None:
        """Mutation: show the priced lanes' sum as the run's cost, in the figures or in the by-model row."""
        render = self._drive()["renders"]["dag_partial_cost"]
        costs = dict(zip(self._classed(render, "omh-pane-dv-kpi-label"), self._classed(render, "omh-pane-dv-kpi-value")))
        self.assertEqual(costs["Cost"], "≥$0.0123")
        self.assertIn("1/2 nodes priced", self._classed(render, "omh-pane-dv-kpi-sub"))
        rows = [[cell["text"] for cell in node["cells"]] for node in render["structure"] if "omh-pane-dv-mrow" in node["className"].split()]
        self.assertEqual(rows[1:], [["claude-haiku-5-5", "2", "12.6k", "77.5%", "≥$0.0123"]])
        self.assertEqual(self._drive()["formatters"]["sumCostText"],
                         ["~$0.0184", "≥$0.0123", "—", "$0.0000", "≥$0.0300", "≥$0.0100"])
        self.assertEqual(self._drive()["formatters"]["costText"], ["$0.0123", "$0.0000", "—", "~$0.0061", "≥$0.0061"],
                         "a provider-reported zero is a zero, not a dash; a floor has one form, never `≥~`")

    def test_the_lane_detail_legend_shows_a_reported_zero_as_zero(self) -> None:
        """Mutation: show a reported 0 as a dash beside its 0.0% share, or a count the lane never reported as 0."""
        read_only, output_only, all_zero = self._drive()["formatters"]["laneLegend"]
        self.assertEqual([(row["label"], row["count"], row["share"]) for row in read_only],
                         [("Cache read", "4.0k", "100.0%"), ("Uncached input", "0", "0.0%"), ("Cache write", "0", "0.0%")])
        self.assertEqual([(row["count"], row["share"]) for row in output_only], [("—", "—")] * 3,
                         "a lane with no usage reported its output alone")
        self.assertEqual([(row["count"], row["share"]) for row in all_zero], [("0", "—")] * 3)

    def test_the_dag_block_is_named_dag_and_its_stats_come_before_the_dag(self) -> None:
        """Mutation: label it `DELEGATION` again, or put the stats back under the cards."""
        renders = self._drive()["renders"]
        for name, drawn in (("dag_cards", "omh-pane-dv-canvas"), ("fanout_cards", "omh-pane-dv-canvas"), ("dag_beyond_cards", "omh-pane-dv-canvas")):
            with self.subTest(name=name):
                labels = [node["text"] for node in renders[name]["structure"] if node["className"] == "omh-pane-section-label"]
                self.assertIn("DAG", labels)
                self.assertNotIn("DELEGATION", labels)
                classes = [node["className"].split() for node in _split_at_dag(renders[name])[1]]
                at = {key: next(index for index, names in enumerate(classes) if key in names) for key in ("omh-pane-dv-kpis", "omh-pane-dv-stats", drawn)}
                self.assertLess(at["omh-pane-dv-kpis"], at["omh-pane-dv-stats"])
                self.assertLess(at["omh-pane-dv-stats"], at[drawn])
        # A run with no topology is the same DAG block, not a delegation list beside it.
        labels = [node["text"] for node in renders["settled_lanes"]["structure"] if node["className"] == "omh-pane-section-label"]
        self.assertEqual(labels, list(SECTION_LABELS))

    def test_the_usage_board_leads_the_pane_with_this_chats_figures(self) -> None:
        """Mutation: count the output in the hit rate, take the stream's counts over the recorded row, or show it below the plan."""
        render = self._drive()["renders"]["usage_board"]
        self.assertEqual(self._board(render, "omh-pane-section-label")[0], "USAGE")
        self.assertEqual(self._board(render, "omh-pane-section-title")[0], "gpt-6-luna")
        self.assertEqual(self._board(render, "omh-pane-section-count")[0], "4 calls")
        # The dial holds the tokens and the cache; the figures beside it are TPS, TTFT, cost and context.
        self.assertEqual(self._board(render, "omh-pane-ub-total"), ["12.6k"])
        # The dial's line is the hit rate whatever the source, so it never switches between a count and a share.
        self.assertEqual(self._board(render, "omh-pane-ub-cache"), ["cache 77.5%"])
        self.assertEqual(self._board(render, "omh-pane-ub-source"), ["recorded"])
        self.assertEqual(self._board(render, "omh-pane-dv-kpi-label"), ["TPS", "TTFT", "Cost", "Context"])
        # The recorded row: 1600 + 9300 + 1100 prompt + 630 out; 9300 / 12000 read; $0.5 priced. Then the stream's
        # window (15.7k of 100.0k), its rolling speed, and the two waits this window timed (1850 ms, 410 ms).
        self.assertEqual(self._board(render, "omh-pane-dv-kpi-value"), ["42 t/s", "410ms", "$0.5000", "16%"])
        self.assertEqual(
            self._board(render, "omh-pane-dv-kpi-sub"),
            ["avg call 3.2s", "avg 1.1s · 2 turns", "", "15.7k of 100.0k"],
        )
        # The composition: what the prompt is made of, as shares of the window, and the free end of it (100.0k - 15.7k).
        self.assertEqual(self._board(render, "omh-pane-dv-legend-k"), ["System prompt", "Tools", "Conversation", "Free window"])
        self.assertEqual(self._board(render, "omh-pane-dv-legend-n"), ["3.0k", "6.0k", "6.7k", "84.3k"])
        self.assertEqual(self._board(render, "omh-pane-dv-legend-p"), ["3.0%", "6.0%", "6.7%", "84.3%"])
        self.assertEqual(self._board(render, "omh-pane-dv-stats-c"), ["~15.7k / 100.0k"])
        pane = " ".join(render["byId"]["hud"])
        self.assertLess(pane.index("USAGE"), pane.index("PLAN"))

    def test_the_board_never_shows_another_chats_recorded_row_or_a_failed_read(self) -> None:
        """Mutation: show the row the last poll read for the chat before a switch, or a failed read's row as zeros."""
        renders = self._drive()["renders"]
        for name in ("usage_board_switched", "usage_board_read_failed"):
            with self.subTest(name=name):
                values = dict(zip(self._board(renders[name], "omh-pane-dv-kpi-label"),
                                  self._board(renders[name], "omh-pane-dv-kpi-value")))
                # The stream's 12000 prompt and 630 out; its hit rate; its cost unvouched (the row's $0.5000 is gone).
                self.assertEqual((self._board(renders[name], "omh-pane-ub-total"), values["Cost"]), (["12.6k"], "—"))
                self.assertEqual(self._board(renders[name], "omh-pane-ub-cache"), ["cache 77.0%"], "no row, so the rate")

    def test_a_chat_with_only_a_stream_shows_what_it_carries_and_dashes_for_the_rest(self) -> None:
        render = self._drive()["renders"]["usage_board_stream_only"]
        self.assertEqual(self._board(render, "omh-pane-ub-total"), ["4.3k"])
        self.assertEqual(self._board(render, "omh-pane-ub-cache"), ["cache 50.0%"])
        self.assertEqual(self._board(render, "omh-pane-dv-kpi-value"), ["—", "—", "—", "—"])
        self.assertEqual(self._board(render, "omh-pane-dv-kpi-sub"), ["", "send → first token", "unpriced", ""])
        self.assertEqual(self._board(render, "omh-pane-dv-legend-k"), [], "no breakdown yet, so no composition")

    def test_a_chat_nothing_has_reported_on_keeps_its_board_and_says_so(self) -> None:
        """Mutation: drop the board when nothing has reported (the block that comes and goes)."""
        usage = self._sections("usage_board_unknown")["USAGE"]
        self.assertEqual(usage[:3], ["Main", "+ subagents (0)", "—"])
        self.assertIn("Nothing recorded for this chat yet", usage)
        self.assertIn("Open a chat to see its usage", self._sections("reader_error")["USAGE"])

    def test_the_gateways_counters_fill_a_board_the_record_has_not_reached(self) -> None:
        """Mutation: read only Hermes' recorded row (a chat with no row showed nothing), or ask with no chat named."""
        renders = self._drive()["renders"]
        render = renders["usage_board_gateway"]
        self.assertEqual(render["stats"], {"enabled": True, "queryKey": ["omh", "stats", "rt-9", 0]})
        self.assertEqual(self._board(render, "omh-pane-ub-source"), ["live"], "the gateway's counters, in the person's word")
        self.assertEqual(self._board(render, "omh-pane-section-title")[0], "claude-opus-5-5")
        self.assertEqual(self._board(render, "omh-pane-section-count")[0], "7 calls")
        self.assertEqual(self._board(render, "omh-pane-ub-total"), ["42.0k"])
        self.assertEqual(self._board(render, "omh-pane-ub-cache"), ["cache 90.0%"])
        values = dict(zip(self._board(render, "omh-pane-dv-kpi-label"), self._board(render, "omh-pane-dv-kpi-value")))
        self.assertEqual(values, {"TPS": "33 t/s", "TTFT": "—", "Cost": "—", "Context": "25%"})
        self.assertFalse(renders["open_with_payload"]["stats"]["enabled"], "no chat named, so nothing is asked")

    def test_the_composition_is_asked_for_only_while_a_chat_is_idle_and_never_shown_under_another(self) -> None:
        """Mutation: ask mid-turn, ask with no chat named, or keep the last answer across a chat switch."""
        renders = self._drive()["renders"]
        idle = renders["usage_board"]["context"]
        self.assertEqual(idle["queryKey"], ["omh", "context", "rt-1", 4, 1], "a call or a compression asks again")
        self.assertTrue(idle["enabled"])
        self.assertEqual(idle["requests"], [["session.context_breakdown", {"session_id": "rt-1"}]])
        self.assertTrue(idle["keepsOwnChat"])
        self.assertTrue(idle["dropsOtherChat"])
        self.assertFalse(renders["usage_board_busy"]["context"]["enabled"], "an estimate mid-turn is stale as it lands")
        self.assertFalse(renders["open_with_payload"]["context"]["enabled"], "no chat is named, so there is nothing to ask about")

    def test_the_first_token_wait_is_timed_per_chat_and_only_from_text(self) -> None:
        """Mutation: end the wait on an empty chunk, share one clock between chats, or keep every turn."""
        latency, speed, waits = (self._drive()["formatters"][key] for key in ("latencyText", "speedText", "ttftWaits"))
        self.assertEqual(latency, ["", "0ms", "12ms", "999ms", "1.0s", "1.1s", "2.5s", ""])
        self.assertEqual(speed, ["42 t/s", "9.4 t/s", "—", "—", "120 t/s"])
        self.assertEqual(waits[0], [[False, True, False], {"s": [250]}])
        self.assertEqual(waits[1], [[False, False, False, True], {"s": [90]}])
        self.assertEqual(waits[2], [[False], {}], "a chunk with no turn start before it times nothing")
        self.assertEqual(waits[3], [[False, False, True, True, False], {"b": [20], "a": [40]}])
        # The re-sent start of t1 does not reset the wait (1100ms from the first start), then t2 times its own (300ms).
        self.assertEqual(waits[4], [[False, False, True, False, True], {"s": [1100, 300]}])
        self.assertEqual(waits[5], [[False, False, False, False], {}], "no chat id and no clock time the wait of nothing")
        self.assertEqual(waits[6][1], {"s": list(range(2, 12))}, "the last ten turns")
        self.assertTrue(all(waits[6][0][1::2]))

    def test_a_dead_turn_never_times_the_next_one(self) -> None:
        """Mutation: keep a start no text followed past the turn's end, keep a bare start over a newer one, or key
        pending starts by turn so dead ones pile up."""
        report = self._drive()["formatters"]
        waits = report["ttftWaits"]
        self.assertEqual(waits[7], [[False, False, False, True], {"s": [300]}], "interrupted, then a turn that streams")
        self.assertEqual(waits[8], [[False, False, False, False, True], {"s": [250]}], "a late chunk of a failed turn")
        self.assertEqual(waits[9], [[False, False, True], {"s": [200]}], "a bare start replaces the last one")
        self.assertEqual(waits[10], [[False, False, True], {"s": [80]}], "another turn's chunk ends no wait")
        self.assertEqual(report["ttftPending"], [["u"]], "one pending start per chat, gone at the turn's end")

    def test_the_usage_board_model_reads_each_figure_from_its_own_source(self) -> None:
        """Mutation: take the stream over the recorded row, drop the `~` from a cost the stream does not vouch for, or
        show a recorded zero read as a dash."""
        (streamed, recorded, zero_read, empty, calls_only, guessed, window, ragged,
         other_chat, unnamed, failed, free, floor, with_subs, without_subs, unpriced_chat,
         gateway_ahead, gateway_behind, gateway_idle) = self._drive()["formatters"]["usageBoard"]

        def cells(model: dict) -> dict:
            return {cell["label"]: (cell["value"], cell["sub"]) for cell in model["cells"]}

        self.assertEqual(
            cells(streamed),
            {"Tokens": ("4.3k", "↓300 out · 4.0k in"), "Cache hit": ("50.0%", "2.0k of 4.0k prompt"), "Cost": ("~$0.0100", ""),
             "Context": ("—", ""), "TPS": ("—", ""), "TTFT": ("—", "send → first token")},
        )
        self.assertEqual(
            cells(recorded)["Tokens"], ("12.6k", "↓630 out · 12.0k in"), "the recorded row, not the stream's one-token counts"
        )
        self.assertEqual((cells(recorded)["Cache hit"], cells(recorded)["Cost"]), (("77.5%", "9.3k of 12.0k prompt"), ("~$0.0184", "")))
        self.assertEqual(
            [cell["ring"] for cell in recorded["cells"] if cell.get("ring")],
            [{"input": 1600, "read": 9300, "write": 1100, "output": 630}],
        )
        self.assertEqual(cells(zero_read)["Cache hit"], ("0.0%", "0 of 12.0k prompt"))
        self.assertEqual(cells(zero_read)["Cost"], ("—", "unpriced"))
        # Never null: a board with nothing known is a board of dashes that says so.
        self.assertTrue(empty["empty"])
        self.assertEqual({label: value for label, (value, _) in cells(empty).items()},
                         {"Tokens": "—", "Cache hit": "—", "Cost": "—", "Context": "—", "TPS": "—", "TTFT": "—"})
        self.assertEqual(empty["dial"], {"split": None, "total": 0, "cache": None})
        self.assertTrue(calls_only["empty"], "a call count alone is no figure")
        self.assertEqual((streamed["source"], recorded["source"], empty["source"]), ("stream", "recorded", ""))
        self.assertEqual(cells(guessed)["Context"], ("~5.0k", ""), "an estimate keeps its mark, and no window gives no percent")
        self.assertEqual(cells(window)["Context"], ("25%", "8.0k of 32.0k"))
        self.assertEqual(
            [(part["label"], part["tokens"], part["share"]) for part in window["parts"]],
            [("System prompt", 3000, 0.09375), ("Conversation", 5000, 0.15625)],
        )
        # Subagents join the dial and the cost (a floor: one lane is unpriced); left out, the chat stands alone.
        self.assertEqual(with_subs["dial"], {"split": {"input": 1200, "read": 800, "write": 0, "output": 150}, "total": 2150, "cache": "40.0%"})
        self.assertEqual(cells(with_subs)["Cost"][0], "≥$0.7500")
        self.assertEqual(without_subs["dial"]["total"], 1600)
        self.assertEqual(cells(without_subs)["Cost"][0], "$0.5000")
        # Mutation: price a chat Hermes never priced at zero, so its subagents' cost reads as the exact total.
        self.assertEqual(cells(unpriced_chat)["Cost"][0], "≥$0.2500")
        self.assertEqual([(part["label"], part["share"]) for part in ragged["parts"]], [("A", 1.0)])
        self.assertEqual(ragged["sum"], 600)
        # A row for another chat, for no named chat, or a failed read: the stream's figures, the row's left out.
        for model in (other_chat, unnamed, failed):
            self.assertEqual((cells(model)["Tokens"], cells(model)["Cost"]), (("4.3k", "↓300 out · 4.0k in"), ("—", "unpriced")))
        self.assertEqual(cells(free)["Cost"], ("$0.0000", ""), "a provider-reported zero is a zero cost")
        self.assertEqual(cells(floor)["Cost"], ("≥$0.5210", ""), "an unpriced part makes the priced sum a floor, as in the DAG")
        # The gateway's counters ahead of the row take the tokens; the row's cost then covers less than is shown.
        self.assertEqual(gateway_ahead["source"], "gateway")
        self.assertEqual((gateway_ahead["model"], gateway_ahead["calls"]), ("claude-opus-5-5", 7))
        self.assertEqual(cells(gateway_ahead)["Tokens"], ("42.0k", "↓2.0k out · 40.0k in"))
        self.assertEqual(cells(gateway_ahead)["Cache hit"], ("90.0%", "36.0k of 40.0k prompt"))
        self.assertEqual(cells(gateway_ahead)["Cost"][0], "≥$0.5000")
        self.assertEqual(cells(gateway_ahead)["Context"], ("25%", "50.0k of 200.0k"))
        self.assertEqual(cells(gateway_ahead)["TPS"][0], "33 t/s")
        # Behind the row, the row keeps the tokens and its cost; the window is still the gateway's.
        self.assertEqual((gateway_behind["source"], cells(gateway_behind)["Cost"][0]), ("recorded", "$0.5000"))
        self.assertEqual(cells(gateway_behind)["Context"][0], "25%")
        self.assertEqual((gateway_idle["source"], cells(gateway_idle)["Tokens"][0]), ("", "—"), "counters before a call count nothing")

    def test_a_korean_host_reads_the_usage_board_in_korean(self) -> None:
        hud = " ".join(self._drive()["korean"]["usage_board"]["byId"]["hud"])
        for word in ("사용량", "호출 4회", "캐시 77.5%", "기록", "비용", "컨텍스트", "100.0k 중 15.7k", "호출 평균 3.2s", "평균 1.1s · 2턴", "프롬프트 구성"):
            with self.subTest(word=word):
                self.assertIn(word, hud)
        for english in ("USAGE", "Context", "Prompt composition", "avg call"):
            self.assertNotIn(english, hud)

    def test_dag_model_lays_out_layers_and_skips_edges_it_cannot_draw(self) -> None:
        plain, fanout, with_noise, cyclic, no_topology, inactive, beyond, floor, implied = self._drive()["formatters"]["dagModel"]
        self.assertEqual(plain["layers"], [["d:r:a", "d:r:b"], ["d:r:sum"], ["d:r:chk"]])
        self.assertEqual(plain["path"], ["d:r:a", "d:r:sum", "d:r:chk"])
        self.assertEqual(plain["bottlenecks"], [{"id": "d:r:sum", "blocks": 1}])
        self.assertEqual({lane["id"]: lane["blocks"] for lane in plain["lanes"]}, {"d:r:a": 2, "d:r:b": 2, "d:r:sum": 1, "d:r:chk": 0})
        self.assertEqual(plain["total"], {"lanes": 2, "priced": 2, "input": 1600, "read": 9300, "write": 1100, "output": 630, "cost": 0.0184, "estimated": True,
                                          "partial": False})
        self.assertEqual((plain["seconds"], plain["timed"]), (78, 2))
        self.assertEqual([(entry["model"], entry["count"]) for entry in plain["models"]], [("claude-haiku-5-5", 2)])
        self.assertEqual((fanout["path"], fanout["bottlenecks"]), ([], []))
        self.assertEqual(fanout["layers"], [["f:a", "f:b"], ["f:sum"], ["f:chk"]])
        self.assertEqual(fanout["total"], plain["total"])
        self.assertEqual((with_noise["layers"], with_noise["edges"]), (plain["layers"], plain["edges"]))
        # Two lanes waiting on each other still each get one layer; the model must not loop.
        self.assertEqual(sum(len(layer) for layer in cyclic["layers"]), 4)
        # Without the backend's topology the edges still lay the run out: the same layers, no critical path claimed.
        self.assertEqual((no_topology["layers"], no_topology["path"]), (plain["layers"], []))
        self.assertIsNone(inactive)
        self.assertEqual((len(beyond["layers"]), beyond["hidden"]), (17, 3))
        self.assertEqual(beyond["total"]["lanes"], 0)
        self.assertEqual((floor["total"]["priced"], floor["total"]["partial"]), (2, True))
        self.assertEqual(implied["implied"], ["d:r:a.d:r:c"])
        self.assertEqual(plain["implied"], [])  # edges that carry no kind are never implied
        self.assertEqual([edge["kind"] for edge in implied["edges"]], ["depends_on", "depends_on", "depends_on", "repair", "depends_on"])

    def test_the_dag_view_leaves_the_hosts_sideways_swipe_alone(self) -> None:
        """Mutation: clip every drawing (native and team graphs too), clip in a narrow mouse window, or let the cards
        scroll sideways."""
        css = self._drive()["style"]["css"]
        # Cards wrap; nothing in the view scrolls sideways, so the host's swipe stays the host's.
        view = [line for line in css.splitlines() if "omh-pane-dv" in line]
        self.assertTrue(view)
        self.assertNotIn("touch-action", css)
        for rule in [rule for line in view for rule in line.split("}") if "omh-pane-dv" in rule]:
            with self.subTest(rule=rule[:60]):
                self.assertNotIn("overflow-x", rule)
        # A control is 32px tall on touch and reaches 44px through its padding box's pseudo-element.
        coarse = next(line for line in view if line.startswith("@media (pointer:coarse),(max-width:640px)"))
        self.assertIn("height:32px", coarse)
        self.assertIn("inset:-7px -5px", coarse)

    def test_a_korean_host_reads_the_dag_view_in_korean(self) -> None:
        hud = self._drive()["korean"]["dag_cards"]["byId"]["hud"]
        for word in ("토큰", "캐시 적중", "프롬프트 12.0k 중 9.3k", "노드 4개 중 2개 시간 기록", "통계", "병목", "Sum (후속 1개 대기)"):
            with self.subTest(word=word):
                self.assertIn(word, hud)
        for english in ("Tokens", "Cache hit", "Node time", "Bottlenecks", "sum of"):
            self.assertNotIn(english, " ".join(hud))

    def test_busy_polling_uses_two_seconds_and_missing_korean_keys_fall_back(self) -> None:
        report = self._drive()
        self.assertEqual(report["formatters"]["pollInterval"], [2000, 5000])
        self.assertEqual(report["renders"]["busy"]["refetchInterval"], 2000)
        self.assertEqual(report["renders"]["open_with_payload"]["refetchInterval"], 5000)
        self.assertEqual(report["englishFallback"], "2 running")
        self.assertEqual(report["formatters"]["t"][2], "유휴")


class DoctorDesktopHalfTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.paths = resolve_paths(root / ".omh", root / ".hermes")

    def _checks(self) -> dict[str, object]:
        with mock.patch(
            "omh.maintenance.doctor.observe_real_loader_registration",
            return_value=dict(LOADER_NOT_OBSERVED),
        ):
            checks = run_doctor(self.paths)
        return {check.name: check for check in checks}

    def test_a_fresh_install_carries_the_desktop_half(self) -> None:
        install_plugin_bundle(self.paths)
        for relative in DESKTOP_HALF_FILES:
            self.assertTrue((self.paths.hermes_plugin_dir / relative).is_file(), relative)
        check = self._checks()["plugin_desktop_half"]
        self.assertTrue(check.ok)
        self.assertEqual(check.severity, "ok")
        # Enablement lives in the app's renderer storage and is not readable
        # from here, so the message names the switch and never says it is on.
        self.assertEqual(
            check.message,
            f"Hermes Desktop half present in the installed bundle ({self.paths.hermes_plugin_dir}); "
            "it ships off; switch it on in Hermes Desktop under Capabilities -> Plugins",
        )
        self.assertNotIn("is switched on", check.message)

    def test_an_older_bundle_warns_toward_omh_update_without_flipping_the_exit_code(self) -> None:
        install_plugin_bundle(self.paths)
        blocking = lambda checks: {  # noqa: E731 - a two-use predicate
            name for name, check in checks.items() if not check.ok and check.severity == "blocking"
        }
        before = blocking(self._checks())
        shutil.rmtree(self.paths.hermes_plugin_dir / "desktop")
        (self.paths.hermes_plugin_dir / "dashboard" / "manifest.json").unlink()
        (self.paths.hermes_plugin_dir / "dashboard" / "plugin_api.py").unlink()
        stale = self._checks()
        check = stale["plugin_desktop_half"]
        self.assertTrue(check.ok)
        self.assertEqual(check.severity, "warning")
        self.assertIn("missing desktop/plugin.js, dashboard/manifest.json, dashboard/plugin_api.py", check.message)
        self.assertIn("omh update", check.next_action)
        self.assertTrue(doctor_ok([check]))
        # An installed bundle without the files is also one whose manifest
        # names files that are gone and no longer matches the current package;
        # both are the manifest checks' findings. The removal adds exactly
        # those two blocking checks, never this one.
        self.assertEqual(blocking(stale) - before, {"plugin_bundle_current", "plugin_manifest"})

    def test_the_check_is_absent_when_no_bundle_is_installed(self) -> None:
        self.assertNotIn("plugin_desktop_half", self._checks())


if __name__ == "__main__":
    unittest.main()
