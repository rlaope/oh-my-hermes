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
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from _standalone_bundle import bundle_dir
from omh.install.plugin_pack import install_plugin_bundle
from omh.maintenance.doctor import DESKTOP_HALF_FILES, doctor_ok, run_doctor
from omh.paths import resolve_paths
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
export const Badge = ({ children }) => children
export const PanelEmpty = ({ title, description }) => [title, description]
export const StatusDot = () => null
export const Skeleton = () => null
export const GlyphSpinner = () => '⠋'
export const host = {
  state: {
    gateway: { get: () => globalThis.__omh.gateway },
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
  query: { data: undefined, error: null }, lastQuery: null, revealed: [], notified: [], tips: []
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
// The route identity is drawn as nowrap fragments with break opportunities
// between them; the report joins them back into the one string it names.
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
const findClick = node => {
  if (!node || typeof node !== 'object') return null
  if (Array.isArray(node)) { for (const child of node) { const hit = findClick(child); if (hit) return hit } return null }
  if (node.props && typeof node.props.onClick === 'function') return node.props.onClick
  return findClick(node.props && node.props.children)
}
const scenarios = JSON.parse(readFileSync(scenariosPath, 'utf8'))
const renders = {}
for (const [name, scenario] of Object.entries(scenarios)) {
  globalThis.__omh.gateway = scenario.gateway
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
  restCalls.length = 0
  const byId = {}
  let clicked = []
  let alternates = []
  let strikeLeaks = []
  for (const c of contributions) {
    const tree = c.render()
    byId[c.id] = text(tree)
    if (c.id === 'hud') {
      alternates = collect(tree, props => props['data-alt'] === 'true')
      strikeLeaks = notesUnderLabel(tree)
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
    statusDetail: (mod.statusItem({ gateway: scenario.gateway, data: scenario.data, error: globalThis.__omh.query.error }) || {}).detail || ''
  }
}
const formatterCases = JSON.parse(readFileSync(formatterCasesPath, 'utf8'))
const formatters = {}
for (const [name, cases] of Object.entries(formatterCases)) {
  formatters[name] = cases.map(args => {
    const answer = mod[name](...args)
    return answer && typeof answer === 'object' ? answer.text : answer
  })
}
for (const dispose of disposers) dispose()
const report = {
  plugin: { id: plugin.id, name: plugin.name, description: plugin.description, defaultEnabled: plugin.defaultEnabled },
  contributions: contributions.map(c => ({ id: c.id, area: c.area, title: c.title, order: c.order, data: c.data })),
  renders,
  formatters,
  style: { afterRegister: styleEventsAfterRegister, afterDispose: [...styleEvents], css: styleCss }
}
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
    "reader_error": {
        "gateway": "open",
        "stored": None,
        "data": {"error": "RuntimeBindingError: OMH home is not configured", "schema_version": "omh_desktop_hud/v1"},
    },
    "transport_error": {"gateway": "open", "stored": None, "data": None, "errorMessage": "HTTP 404: Plugin not found"},
    "loading": {"gateway": "open", "stored": "20260924_101010_abc123", "data": None},
    "gateway_closed": {"gateway": "connecting", "stored": None, "data": None},
}

# The TUI examples from the widget's own grammar, one call each; the report
# carries the answers in this order.
FORMATTER_CASES = {
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
            scenarios.write_text(json.dumps(SCENARIOS), encoding="utf-8")
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
        self.assertEqual(
            pane,
            [
                "⚚ OMH",
                "v2.0.5",
                "2 agents · 1 running · 1 done",
                "deepseek-v4.1-flash-ultrafast",
                "ctx 12%",
                "45.2k tok",
                "$0.012",
                "2 tools · 4m 2s",
                "yolo off",
                "89.3k tokens",
                "PLAN",
                "Desktop check",
                "1/3",
                "Research",
                "1/1",
                "✓",
                "Read the pane spec",
                "Build",
                "0/2",
                "●",
                "Draw the structured pane",
                "○",
                "Screenshot the result",
                "waiting: needs the app",
                "AGENTS",
                "2",
                "kind",
                "id",
                "task",
                "route",
                "state",
                "elapsed",
                "tokens",
                "cost",
                "⠋",
                "sub",
                "a1b2c3d4",
                "Implement the parser at …/utils/duration.py",
                "inherit(claude-opus-5:high)",
                "running",
                "4m 2s",
                "12.3k tok",
                "~$0.0431",
                "✓",
                "sub",
                "e5f6a7b8",
                "Write tests for parse_duration",
                "category:architect(claude-fable-5-1:xhigh)",
                "done",
                "2h 01m",
                "77.0k tok",
                "$0.0123",
            ],
        )
        # The legacy text lines are never on screen: the pane is built from
        # the structured blocks, so their wording cannot leak through.
        for line in ESTABLISHED_PAYLOAD["display"]["widget_lines"] + ESTABLISHED_PAYLOAD["display"]["todo_lines"]:
            self.assertNotIn(line, pane)

    def test_agent_rows_keep_the_secondary_figures_in_the_tooltip(self) -> None:
        render = self._drive()["renders"]["open_with_payload"]
        pane = render["byId"]["hud"]
        # Rate, cache and turn are never drawn on the row; the tooltip on the
        # title carries the full sentence, the route and those figures.
        for figure in ("85 tok/s", "cache 72%", "turn 3 (12 tools)", "turn 2 (5 tools)"):
            self.assertNotIn(figure, pane)
        self.assertIn(
            "Implement the parser at /Users/dev/projects/oh-my-hermes/src/utils/duration.py · inherit(claude-opus-5:high) · 85 tok/s · cache 72% · turn 3 (12 tools)",
            render["tips"],
        )
        self.assertIn("Write tests for parse_duration · category:architect(claude-fable-5-1:xhigh) · turn 2 (5 tools)", render["tips"])
        # Every second row is marked for the wide grid's alternating band.
        self.assertEqual(
            render["alternates"],
            ["✓sube5f6a7b8Write tests for parse_durationcategory:architect(claude-fable-5-1:xhigh)done2h 01m77.0k tok$0.0123"],
        )

    def test_the_pane_draws_maestro_board_dag_and_a_finished_plan(self) -> None:
        pane = self._pane("maestro_and_board")
        self.assertEqual(
            pane,
            [
                "⚚ OMH",
                "v2.0.5",
                "[global]",
                "1 agent · 1 blocked",
                "gpt-5.6",
                "repeat x3 blocked",
                "board 2q 1r 0b",
                "dispatcher not observed",
                "yolo on",
                "PLAN",
                "Ship the pane",
                "✓ 1/2 (1 skipped)",
                "✓",
                "Build it",
                "✓",
                "Benchmark it",
                "skipped: no bench harness",
                "AGENTS",
                "4",
                "kind",
                "id",
                "task",
                "route",
                "state",
                "elapsed",
                "tokens",
                "cost",
                "⠋",
                "main",
                "run-42",
                "Refactor the router",
                "(codex/maestro gpt-5.6)",
                "running",
                "30s",
                "0 tok",
                "$0.0000 (included)",
                "▲",
                "bot",
                "kb-7",
                "Triage the flaky suite",
                "kanban/unassigned(gpt-5.6:medium)",
                "review",
                "1m 1s",
                "+2 more",
                "[global] DAG · 1 ready · 1 edges",
                "[+]",
                "a · completed",
                "[R]",
                "b · running",
                "[!]",
                "c · blocked_by_dependency · blocked_by b",
            ],
        )

    def test_a_skipped_note_under_a_finished_item_is_not_struck_through(self) -> None:
        render = self._drive()["renders"]["maestro_and_board"]
        self.assertIn("skipped: no bench harness", render["byId"]["hud"])
        # The note is a sibling of the struck label, never its descendant.
        self.assertEqual(render["strikeLeaks"], [])

    def test_the_status_item_is_compact_and_reveals_the_pane_on_click(self) -> None:
        report = self._drive()["renders"]
        self.assertEqual(report["open_with_payload"]["byId"]["status"], ["⚚", "2 agents", "1 running", "1/3"])
        self.assertEqual(report["open_with_payload"]["revealed"], ["omh:hud"])
        self.assertEqual(
            report["open_with_payload"]["statusDetail"],
            "2 agents · 1 running · 1 done · plan Desktop check 1/3 · [omh] v2.0.5 | plugin:ready | target:single",
        )
        self.assertEqual(report["maestro_and_board"]["byId"]["status"], ["⚚", "1 agent", "1 blocked", "✓ 1/2"])
        self.assertEqual(report["no_todo_declared"]["byId"]["status"], ["⚚", "ready"])
        # Nothing in the bar before the first answer, like the Kanban count.
        self.assertEqual(report["loading"]["byId"]["status"], [])
        self.assertEqual(report["gateway_closed"]["byId"]["status"], [])

    def test_an_undeclared_todo_is_said_rather_than_invented(self) -> None:
        pane = self._pane("no_todo_declared")
        self.assertEqual(
            pane,
            ["⚚ OMH", "v2.0.5", "ready", "gpt-5.6", "PLAN", "No plan for this session", "omh_todo declares one when a workflow starts."],
        )

    def test_a_reader_error_record_is_shown_as_a_quiet_notice(self) -> None:
        render = self._drive()["renders"]["reader_error"]
        self.assertEqual(render["byId"]["status"], ["⚚", "omh error"])
        self.assertEqual(
            render["byId"]["hud"],
            ["⚚ OMH", "reader error", "no focused session", "omh backend: RuntimeBindingError: OMH home is not configured"],
        )
        self.assertEqual(render["restCalls"], ["/hud"])

    def test_a_transport_error_degrades_to_backend_unavailable(self) -> None:
        render = self._drive()["renders"]["transport_error"]
        self.assertEqual(render["byId"]["status"], ["⚚", "omh unavailable"])
        self.assertEqual(
            render["byId"]["hud"],
            ["⚚ OMH", "unavailable", "no focused session", "omh backend: HTTP 404: Plugin not found"],
        )

    def test_the_first_poll_renders_no_loading_text(self) -> None:
        # DESIGN.md: never the literal "Loading…"; the body is skeletons,
        # which carry no text, under the brand line.
        self.assertEqual(self._pane("loading"), ["⚚ OMH", "model unknown"])

    def test_polling_waits_for_an_open_gateway(self) -> None:
        render = self._drive()["renders"]["gateway_closed"]
        self.assertFalse(render["enabled"])
        self.assertEqual(render["byId"]["hud"], ["⚚ OMH", "gateway connecting", "no focused session"])

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
            ["ready", "3 agents · 2 running · 1 blocked", "2 done", "4 agents · 3 running · 1 blocked · 1 done"],
        )


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
