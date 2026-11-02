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
from omh.plugin_bundle.omh import runtime_reader, subagent_graph
from omh.plugin_bundle.omh.dashboard import plugin_api
from _module_patch import patch_modules

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
    focusedUsage: { get: () => globalThis.__omh.usage }
  },
  revealPane: paneId => { globalThis.__omh.revealed.push(paneId) },
  notify: input => { globalThis.__omh.notified.push(input) }
}
export const useValue = atom => atom.get()
export function useQuery(options) {
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
  gateway: 'open', stored: null, model: '', usage: null,
  query: { data: undefined, error: null }, lastQuery: null, revealed: [], notified: [], tips: [], dots: [], badges: []
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
const ctx = {
  source: 'plugin:omh',
  rest: path => { restCalls.push(path); return Promise.resolve({}) },
  register: c => { contributions.push(c); return () => {} },
  registerMany: cs => { cs.forEach(c => contributions.push(c)); return () => {} },
  onDispose: fn => { disposers.push(fn) },
  onEvent: () => () => {},
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
  if (props.className) out.push({ className: props.className, text: text(node).join(''), state: props['data-state'], done: props['data-done'], style: props.style,
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
const koreanScenarios = ['catches_and_lanes', 'settled_lanes', 'maestro_and_board', 'gateway_closed', 'open_with_payload', 'failed_lane']
const renders = {}
for (const [name, scenario] of Object.entries(scenarios)) {
  globalThis.__omh.gateway = scenario.gateway
  globalThis.__omh.busy = scenario.busy === true
  globalThis.__omh.stored = scenario.stored
  globalThis.__omh.model = scenario.model || ''
  globalThis.__omh.usage = scenario.usage || null
  globalThis.__omh.query = {
    data: scenario.data,
    error: scenario.errorMessage ? new Error(scenario.errorMessage) : null
  }
  globalThis.__omh.lastQuery = null
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
  const sentinel = { previous: true }
  renders[name] = {
    byId,
    refetchInterval: query.refetchInterval,
    enabled: query.enabled,
    queryKey: query.queryKey,
    keepsPreviousData: typeof query.placeholderData === 'function' && query.placeholderData(sentinel) === sentinel,
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
const local = { koreanStates: states => states.map(state => [state, mod.stateWord(state, 'en'), mod.stateWord(state, 'ko')]) }
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
  globalThis.__omh.tips = []
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
SCENARIOS["busy"] = {**SCENARIOS["open_with_payload"], "busy": True}
# A fresh run with nothing counted yet: live, so not grey.
SCENARIOS["runtime_only"] = {
    "gateway": "open",
    "stored": None,
    "data": {"active": True, "runtime": {"recent": True, "workflow": "fanout"}, "subagents": {"rows": []}, "todo": {"status": "absent"}},
}
SCENARIOS["global_idle"] = {**SCENARIOS["no_todo_declared"], "stored": None}

# Every fanout status the reader accepts (`runtime_reader._FANOUT_GRAPH_STATUSES`)
# and every stuck unit state (`subagent_graph._STUCK_UNIT_STATES`): finite
# reader vocabulary, so each one has a word in every table.
FANOUT_AND_STUCK_STATES = {
    *runtime_reader._FANOUT_GRAPH_STATUSES,
    *subagent_graph._STUCK_UNIT_STATES,
}

# The TUI examples from the widget's own grammar, one call each; the report
# carries the answers in this order.
FORMATTER_CASES = {
    "pollInterval": [[True], [False]],
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
    "t": [["graphTitle", {"ready": 1, "edges": 1}], ["graphTitle", {"ready": 1, "edges": 2}], ["stateIdle", {}, "ko"]],
    "foldLabels": [[[{"state": "done"}] * 4, {"start": 3, "earlier": 3, "later": 1}]],
    "agentTally": [[{**SCENARIOS["graph_and_other"]["data"], "subagents": {"rows": [RUNNING_ROW], "hidden_rows": 1, "hidden_in_graph": 9}}]],
    "tokenCountText": [[77000], [184800], [999950], [999], [0], [-1]],
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
            with mock.patch.dict(os.environ, {"HERMES_HOME": ""}):
                self.assertEqual(plugin_api.resolve_hermes_home(), Path.home() / ".hermes")

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
        self.assertTrue(render["keepsPreviousData"])
        self.assertEqual(render["queryKey"], ["omh", "hud", "20260924_101010_abc123"])
        self.assertEqual(render["restCalls"], ["/hud?session=20260924_101010_abc123"])

    def test_the_pane_draws_the_plan_and_the_agent_rows_structurally(self) -> None:
        pane = self._pane("open_with_payload")
        self.assertEqual(pane, [
            "OMH", "1 running", "this session", "2 tools · 4m 2s",
            "PLAN", "Desktop check", "1/3", "Research", "1/1", "✓", "Read the pane spec",
            "Build", "0/2", "●", "Draw the structured pane", "○", "Screenshot the result",
            "waiting: needs the app", "2 subagents · 1 running",
        ])
        # Structured blocks replace both the legacy lines and Desktop's native rows.
        for line in ESTABLISHED_PAYLOAD["display"]["widget_lines"] + ESTABLISHED_PAYLOAD["display"]["todo_lines"]:
            self.assertNotIn(line, pane)
        self.assertNotIn("AGENTS", pane)
        self.assertNotIn("a1b2c3d4", pane)
        self.assertNotIn("e5f6a7b8", pane)

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
        pane = self._pane("maestro_and_board")
        self.assertEqual(pane, [
            "OMH", "1 running", "1 blocked", "this session", "repeat x3 blocked", "board 2 queued, 1 running",
            "board dispatcher not seen", "yolo on", "PLAN", "Ship the pane", "✓ 1/2 (1 skipped)",
            "✓", "Build it", "–", "Benchmark it", "skipped: no bench harness", "ROUTES", "2",
            "⠋", "Refactor the router", "run-42", "(codex/maestro gpt-5.6)", "running", "30s",
            "▲", "Triage the flaky suite", "kb-7", "kanban/unassigned(gpt-5.6:medium)", "review", "1m 1s",
            "+2 more", "DAG", "1 ready · 1 edge", "✓", "a", "completed", "●", "b", "running", "○", "c", "waiting on b",
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
        pane = self._pane("native_held_waiting")
        start = pane.index("PLAN")
        end = pane.index("2 subagents · 1 running")
        self.assertEqual(pane[start:end], ["PLAN", "in Hermes todos", "1 waiting", "○", "Screenshot the result", "waiting: needs the app"])
        self.assertNotIn("Draw the structured pane", pane)
        self.assertIn("Draw the structured pane", self._pane("open_with_payload"))
        self.assertEqual(self._status("native_held_waiting"), ["OMH", "1 running"])

    def test_a_plan_todo_list_holds_with_nothing_omh_only_has_no_plan_section(self) -> None:
        pane = self._pane("native_held_quiet")
        self.assertNotIn("PLAN", pane)
        self.assertNotIn("Read the pane spec", pane)
        self.assertIn("2 subagents · 1 running", pane)
        self.assertEqual(self._status("native_held_quiet"), ["OMH", "1 running"])

    def test_an_undeclared_todo_is_said_rather_than_invented(self) -> None:
        self.assertEqual(self._pane("no_todo_declared"), [
            "OMH", "idle", "this session", "PLAN", "No plan yet", "A workflow adds one when it starts.",
        ])

    def test_a_reader_error_record_is_shown_as_a_quiet_notice(self) -> None:
        render = self._drive()["renders"]["reader_error"]
        self.assertEqual(render["byId"]["status"], ["OMH", "reader error"])
        self.assertEqual(render["byId"]["hud"], [
            "OMH", "reader error", "all sessions", "OMH backend: RuntimeBindingError: OMH home is not configured",
        ])
        self.assertEqual(render["restCalls"], ["/hud"])

    def test_a_transport_error_degrades_to_backend_unavailable(self) -> None:
        render = self._drive()["renders"]["transport_error"]
        self.assertEqual(render["byId"]["status"], ["OMH", "unavailable"])
        self.assertEqual(render["byId"]["hud"], ["OMH", "unavailable", "all sessions", "OMH backend: HTTP 404: Plugin not found"])

    def test_the_first_poll_renders_no_loading_text(self) -> None:
        # Skeletons carry no text under the brand and scope line.
        self.assertEqual(self._pane("loading"), ["OMH", "this session"])

    def test_polling_waits_for_an_open_gateway(self) -> None:
        render = self._drive()["renders"]["gateway_closed"]
        self.assertFalse(render["enabled"])
        self.assertEqual(render["byId"]["hud"], ["OMH", "gateway connecting", "all sessions"])

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
        self.assertIn(".omh-pane-bar-fill[data-done=true]{background:var(--ui-text-quaternary)}", css)
        self.assertIn(".omh-pane-item[data-state=skipped] .omh-pane-item-label{color:var(--ui-text-quaternary)}", css)
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
        pane = self._pane("catches_and_lanes")
        self.assertLess(pane.index("CATCHES"), pane.index("PLAN"))
        self.assertLess(pane.index("PLAN"), pane.index("DELEGATION"))
        self.assertLess(pane.index("DELEGATION"), pane.index("ROUTES"))
        self.assertLess(pane.index("ROUTES"), pane.index("DAG"))
        for sentence in expected:
            self.assertIn(sentence, pane)
        self.assertNotIn("CATCHES", self._pane("open_with_payload"))

    def test_inactive_delegation_is_absent_and_settled_lanes_collapse_to_a_summary(self) -> None:
        views = self._drive()["formatters"]["delegationView"]
        self.assertEqual(views[:2], [None, None])
        self.assertTrue(views[2]["settled"])
        self.assertEqual(views[2]["summary"], "DAG · Pane refresh · done 1/2 · 1 failed")
        self.assertNotIn("DELEGATION", self._pane("inactive_lanes"))
        settled = self._pane("settled_lanes")
        self.assertIn("DELEGATION", settled)
        self.assertIn("DAG · Pane refresh · done 1/2 · 1 failed", settled)
        self.assertNotIn("Settled child", settled)
        self.assertNotIn("Failed child", settled)
        self.assertIn("Pane refresh · 1 running", self._pane("catches_and_lanes"))
        self.assertIn("Graph-drawn child", self._pane("catches_and_lanes"))

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
        self.assertEqual(report["formatters"]["t"][:2], ["1 ready · 1 edge", "1 ready · 2 edges"])
        self.assertIn("1 ready · 1 edge", self._pane("maestro_and_board"))
        self.assertIn("1 ready · 2 edges", self._pane("two_edges"))
        self.assertIn("waiting on b", self._pane("maestro_and_board"))
        self.assertNotIn("blocked_by_dependency", " ".join(self._pane("maestro_and_board")))
        self.assertEqual(report["formatters"]["wordTone"], ["accent", "warn", "error", "muted", "tertiary"])
        for token in ("--ui-cyan", "--ui-green", "--ui-success"):
            self.assertNotIn(token, report["style"]["css"])

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

    def test_a_narrow_pane_stacks_the_lane_model_under_its_title(self) -> None:
        report = self._drive()
        css = report["style"]["css"]
        self.assertIn("container-type:inline-size", css)
        narrow = css[css.index("@container (max-width: 420px)") :]
        narrow = narrow[: narrow.index("}}") + 2]
        self.assertIn(".omh-pane-lane{grid-template-columns:14px minmax(0,1fr) 64px}", narrow)
        self.assertIn(".omh-pane-lane-model{grid-column:2/-1;grid-row:2;max-width:none;padding-left:var(--omh-lane-indent,0)}", narrow)
        self.assertIn(".omh-pane-lane-state{grid-column:3;grid-row:1}", narrow)
        # The lane's indent rides a variable: the title always takes it, the model only on its own
        # line in a narrow pane, so a wide row's model cell is not narrowed by it.
        self.assertIn(".omh-pane-lane-title{min-width:0;padding-left:var(--omh-lane-indent,0);", css)
        wide_model = css[css.index(".omh-pane-lane-model{") : css.index("}", css.index(".omh-pane-lane-model{"))]
        self.assertNotIn("omh-lane-indent", wide_model)
        lanes = [node for node in report["renders"]["failed_lane"]["structure"] if node["className"] == "omh-pane-lane"]
        self.assertEqual(len(lanes), 2)
        # `broke` runs after `drawn`, one step in: its row carries the indent, the top lane none.
        self.assertEqual([node.get("style") for node in lanes], [None, {"--omh-lane-indent": "12px"}])
        model = next(node for node in report["renders"]["failed_lane"]["structure"] if "omh-pane-lane-model" in node["className"])
        self.assertEqual(model["text"], "gpt-5.6")

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
        self.assertIn("위임", lanes)
        self.assertIn("Pane refresh · 1 실행 중", lanes)
        self.assertNotIn("1 running", lanes)
        board = korean["maestro_and_board"]["byId"]["hud"]
        for english in ("running", "review", "completed", "failed"):
            self.assertNotIn(english, board)
        self.assertIn("검토", board)
        self.assertIn("실행 중", board)
        self.assertIn("완료", board)
        self.assertIn("DAG · Pane refresh · 완료 1/2 · 1 실패", korean["settled_lanes"]["byId"]["hud"])
        self.assertEqual(korean["gateway_closed"]["byId"]["hud"][:2], ["OMH", "게이트웨이 연결 중"])
        tips = " ".join(korean["maestro_and_board"]["tips"])
        self.assertIn("0 토큰", tips)
        self.assertIn("$0.0000 (포함)", tips)
        self.assertIn("kanban/미배정(gpt-5.6:medium)", tips)
        self.assertNotIn(" tok", tips)
        self.assertNotIn("included", tips)

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
