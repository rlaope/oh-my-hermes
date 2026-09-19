from __future__ import annotations

import json
from importlib import resources
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from _cli_harness import run_cli
from omh.plugin_bundle.omh.runtime_reader import (
    TODO_BLOCKED_REASON_DISPLAY_CHARS,
    read_omh_hud,
)
from omh.plugin_bundle.omh.todo_store import build_todo_record, write_todo
from omh.tui_widget_pack import TuiWidgetInstallError, install_tui_widget, widget_payload

NODE = shutil.which("node")

# Renders one dock-top frame of the installed-form widget against a payload
# handed in on disk, and reports every row as its text plus the colour in force
# at each string leaf. The viewport height is an argument because the panel
# budgets its rows against it; 40 is the default so a caller that only cares
# about a row's content need not name one. The panel takes no input, so the harness needs no key
# loop: it registers the apps with a fake SDK, feeds one snapshot through the
# app's own `reduce`, and reads back the tree `render` returns.
TODO_PANEL_HARNESS = r"""
import { readFileSync } from 'node:fs'
import { pathToFileURL } from 'node:url'
const [widgetPath, payloadPath, colsArg, rowsArg] = process.argv.slice(2)
const apps = []
const sdk = {
  Box: 'Box', Dialog: 'Dialog', Overlay: 'Overlay', Text: 'Text',
  // Function components expand so their text is in the frame, as on screen.
  h: (type, props, ...children) => (typeof type === 'function' ? type({ ...(props || {}), children }) : { type, props, children }),
  defineWidgetApp: app => { apps.push(app); return app },
  openWidget() {},
  updateWidget() {},
}
const mod = await import(pathToFileURL(widgetPath).href)
mod.default(sdk)
const app = apps.find(candidate => candidate.id === 'omh-todo')
const report = (() => {
  if (!app) return { error: 'omh-todo not registered' }
  const theme = { color: { accent: 'accent', border: 'border', error: 'error', label: 'label', muted: 'muted', ok: 'ok', primary: 'primary', statusFg: 'statusFg', text: 'text', warn: 'warn' } }
  const payload = JSON.parse(readFileSync(payloadPath, 'utf8'))
  const state = app.reduce(app.init(''), { kind: 'snapshot', payload })
  const parts = (node, color) => {
    if (node === null || node === undefined || node === false) return []
    if (Array.isArray(node)) return node.flatMap(child => parts(child, color))
    if (typeof node === 'string') return node ? [{ color, text: node }] : []
    if (typeof node === 'object') return parts(node.children, node.props && node.props.color !== undefined ? node.props.color : color)
    return []
  }
  const frame = app.render({ cols: Number(colsArg), rows: Number(rowsArg || 40), state, t: theme })
  const children = frame && Array.isArray(frame.children) ? frame.children : []
  const rows = children.map(child => parts(child, '')).filter(row => row.length)
  return { rows: rows.map(row => ({ text: row.map(part => part.text).join(''), parts: row })) }
})()
// A pipe write is asynchronous; exiting before it drains truncates the report.
process.stdout.write(`${JSON.stringify(report)}\n`, () => process.exit(0))
"""

STATUS_DOCK_HARNESS = r"""
import { readFileSync } from 'node:fs'
import { pathToFileURL } from 'node:url'
const [widgetPath, payloadPath, colsArg, rowsArg] = process.argv.slice(2)
const apps = []
const sdk = {
  Box: 'Box', Dialog: 'Dialog', Overlay: 'Overlay', Text: 'Text',
  h: (type, props, ...children) => (typeof type === 'function' ? type({ ...(props || {}), children }) : { type, props, children }),
  defineWidgetApp: app => { apps.push(app); return app },
  openWidget() {},
  updateWidget() {},
}
const mod = await import(pathToFileURL(widgetPath).href)
mod.default(sdk)
const app = apps.find(candidate => candidate.id === 'omh-status')
const report = (() => {
  if (!app) return { error: 'omh-status not registered' }
  const theme = { color: { accent: 'accent', border: 'border', error: 'error', label: 'label', muted: 'muted', ok: 'ok', primary: 'primary', statusFg: 'statusFg', text: 'text', warn: 'warn' } }
  const payload = JSON.parse(readFileSync(payloadPath, 'utf8'))
  const state = app.reduce(app.init(''), { kind: 'snapshot', payload })
  const parts = (node, color) => {
    if (node === null || node === undefined || node === false) return []
    if (Array.isArray(node)) return node.flatMap(child => parts(child, color))
    if (typeof node === 'string') return node ? [{ color, text: node }] : []
    if (typeof node === 'object') return parts(node.children, node.props && node.props.color !== undefined ? node.props.color : color)
    return []
  }
  // A Box is a container, not a row: the status dock nests one (the frame)
  // inside another (the Hud), so flattening the frame whole would report
  // the header and every activity row as one string.
  const lines = node => {
    if (node === null || node === undefined || node === false) return []
    if (Array.isArray(node)) return node.flatMap(lines)
    if (typeof node === 'object' && node.type === 'Box') return lines(node.children)
    return [node]
  }
  const frame = app.render({ cols: Number(colsArg), rows: Number(rowsArg || 40), state, t: theme })
  const rows = lines(frame).map(node => parts(node, '')).filter(row => row.length)
  return { rows: rows.map(row => ({ text: row.map(part => part.text).join(''), parts: row })) }
})()
process.stdout.write(`${JSON.stringify(report)}\n`, () => process.exit(0))
"""

class TuiWidgetPackTests(unittest.TestCase):
    def test_setup_installs_byte_correct_widget_without_overwriting_unrelated_widget(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            hermes_home = root / ".hermes"
            widget_dir = hermes_home / "tui-widgets"
            widget_dir.mkdir(parents=True)
            unrelated = widget_dir / "personal-dashboard.mjs"
            unrelated_bytes = b"export default function register() {}\n"
            unrelated.write_bytes(unrelated_bytes)

            status, stdout, stderr = run_cli(
                [
                    "--omh-home",
                    str(omh_home),
                    "--hermes-home",
                    str(hermes_home),
                    "setup",
                    "--json",
                ],
                output_json=False,
            )

            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            payload = json.loads(stdout)
            expected = widget_payload(Path(sys.executable))
            self.assertEqual((widget_dir / "omh-status.mjs").read_bytes(), expected)
            self.assertEqual(unrelated.read_bytes(), unrelated_bytes)
            self.assertEqual(payload["steps"]["tui_widget"]["status"], "installed")
            config_text = (hermes_home / "config.yaml").read_text(encoding="utf-8")
            self.assertIn("  interface: tui\n", config_text)
            self.assertIn("  skin: omh\n", config_text)

    def test_setup_defaults_bare_launchers_to_the_branded_modern_tui(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            hermes_home = root / ".hermes"
            config = hermes_home / "config.yaml"
            config.parent.mkdir(parents=True)
            config.write_text("display:\n  compact: true\n", encoding="utf-8")

            status, stdout, stderr = run_cli(
                [
                    "--omh-home",
                    str(omh_home),
                    "--hermes-home",
                    str(hermes_home),
                    "setup",
                    "--json",
                ],
                output_json=False,
            )

            self.assertEqual((status, stderr), (0, ""))
            config_text = config.read_text(encoding="utf-8")
            self.assertIn("  compact: true", config_text)
            self.assertIn("  interface: tui\n", config_text)
            self.assertIn("  skin: omh\n", config_text)
            tui_interface = json.loads(stdout)["steps"]["apply"]["tui_interface"]
            self.assertTrue(tui_interface["changed"])
            self.assertEqual(tui_interface["selected"], "tui")

    def test_setup_yes_switches_stock_classic_interface_and_skin(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            hermes_home = root / ".hermes"
            config = hermes_home / "config.yaml"
            config.parent.mkdir(parents=True)
            config.write_text(
                "display:\n  interface: classic\n  skin: default\n",
                encoding="utf-8",
            )

            status, stdout, stderr = run_cli(
                [
                    "--omh-home",
                    str(omh_home),
                    "--hermes-home",
                    str(hermes_home),
                    "setup",
                    "--yes",
                    "--json",
                ],
                output_json=False,
            )

            self.assertEqual((status, stderr), (0, ""))
            config_text = config.read_text(encoding="utf-8")
            self.assertIn("  interface: tui\n", config_text)
            self.assertIn("  skin: omh\n", config_text)
            self.assertEqual(config_text.count("interface:"), 1)
            self.assertEqual(config_text.count("skin:"), 1)
            apply = json.loads(stdout)["steps"]["apply"]
            self.assertEqual(apply["tui_interface"]["selected"], "tui")
            self.assertEqual(apply["skin"]["selected"], "omh")

    def test_update_yes_restores_widget_and_switches_stock_display_defaults(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            hermes_home = root / ".hermes"
            common = [
                "--omh-home",
                str(omh_home),
                "--hermes-home",
                str(hermes_home),
            ]
            setup_status, _, setup_stderr = run_cli([*common, "setup", "--json"], output_json=False)
            self.assertEqual((setup_status, setup_stderr), (0, ""))
            widget = hermes_home / "tui-widgets" / "omh-status.mjs"
            widget.unlink()
            config = hermes_home / "config.yaml"
            config.write_text(
                config.read_text(encoding="utf-8")
                .replace("  interface: tui\n", "  interface: cli\n")
                .replace("  skin: omh\n", "  skin: default\n"),
                encoding="utf-8",
            )

            status, _, stderr = run_cli(
                [
                    *common,
                    "update",
                    "--yes",
                    "--json",
                ],
                output_json=False,
            )

            self.assertEqual((status, stderr), (0, ""))
            expected = widget_payload(Path(sys.executable))
            self.assertEqual(widget.read_bytes(), expected)
            config_text = config.read_text(encoding="utf-8")
            self.assertIn("  interface: tui\n", config_text)
            self.assertIn("  skin: omh\n", config_text)

    def test_setup_reports_config_changed_when_only_plugin_enablement_changes(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            hermes_home = root / ".hermes"
            common = ["--omh-home", str(omh_home), "--hermes-home", str(hermes_home)]
            setup_status, _, setup_stderr = run_cli([*common, "setup", "--json"], output_json=False)
            self.assertEqual((setup_status, setup_stderr), (0, ""))
            config = hermes_home / "config.yaml"
            config.write_text(
                config.read_text(encoding="utf-8").replace("plugins:\n  enabled:\n    - omh\n", ""),
                encoding="utf-8",
            )

            status, stdout, stderr = run_cli([*common, "setup", "--json"], output_json=False)

            self.assertEqual((status, stderr), (0, ""))
            apply = json.loads(stdout)["steps"]["apply"]
            self.assertTrue(apply["plugin_enabled"]["changed"])
            self.assertTrue(apply["changed"])

    def test_installer_rejects_symlinked_widget_destination_and_parent(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            hermes_home = root / ".hermes"
            widget_dir = hermes_home / "tui-widgets"
            widget_dir.mkdir(parents=True)
            victim = root / "victim.mjs"
            victim_bytes = b"do not overwrite\n"
            victim.write_bytes(victim_bytes)
            destination = widget_dir / "omh-status.mjs"
            destination.symlink_to(victim)

            with self.assertRaises(TuiWidgetInstallError):
                install_tui_widget(hermes_home)
            self.assertEqual(victim.read_bytes(), victim_bytes)

            destination.unlink()
            widget_dir.rmdir()
            external_dir = root / "external-widgets"
            external_dir.mkdir()
            widget_dir.symlink_to(external_dir, target_is_directory=True)
            with self.assertRaises(TuiWidgetInstallError):
                install_tui_widget(hermes_home)
            self.assertEqual(list(external_dir.iterdir()), [])

    def test_installer_refuses_unmanaged_existing_widget(self) -> None:
        with TemporaryDirectory() as tmp:
            hermes_home = Path(tmp) / ".hermes"
            destination = hermes_home / "tui-widgets" / "omh-status.mjs"
            destination.parent.mkdir(parents=True)
            user_bytes = b"export default function userOwned() {}\n"
            destination.write_bytes(user_bytes)

            with self.assertRaises(TuiWidgetInstallError):
                install_tui_widget(hermes_home)
            self.assertEqual(destination.read_bytes(), user_bytes)

    def test_widget_uses_setup_interpreter_not_path_python(self) -> None:
        payload = widget_payload(Path(sys.executable)).decode()

        self.assertIn(json.dumps(os.path.realpath(sys.executable)), payload)
        self.assertNotIn("spawnSync('python3'", payload)
        # `-B` is load-bearing and no environment variable can stand in for it:
        # `-I` implies `-E`, so the child ignores every PYTHON* variable and
        # would write bytecode into the managed plugins directory (issue #1550).
        self.assertIn("['-I', '-B', '-c', READER]", payload)
        self.assertIn("const READER_ENV =", payload)
        self.assertNotIn("...process.env", payload)

    def test_full_uninstall_removes_only_managed_widget(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            hermes_home = root / ".hermes"
            common = ["--omh-home", str(omh_home), "--hermes-home", str(hermes_home)]
            status, _, stderr = run_cli([*common, "setup", "--json"], output_json=False)
            self.assertEqual((status, stderr), (0, ""))
            destination = hermes_home / "tui-widgets" / "omh-status.mjs"
            unrelated = destination.parent / "personal.mjs"
            unrelated.write_text("personal\n", encoding="utf-8")

            status, stdout, stderr = run_cli(
                [*common, "uninstall", "--all", "--keep-command", "--json"],
                output_json=False,
            )

            self.assertEqual((status, stderr), (0, ""))
            self.assertFalse(destination.exists())
            self.assertEqual(unrelated.read_text(encoding="utf-8"), "personal\n")
            self.assertEqual(json.loads(stdout)["tui_widget"]["status"], "removed")

    def test_widget_names_its_own_session_on_every_poll(self) -> None:
        # Two live TUIs used to share one panel answer because the poll
        # carried no identity. The host writes this TUI's session id to the
        # file named by HERMES_TUI_ACTIVE_SESSION_FILE; the widget reads it
        # per poll (the session moves on /new and /resume) and hands it to
        # the reader as the todo scope, without widening the env allowlist.
        widget = resources.files("omh.tui_widgets").joinpath("omh-status.mjs").read_text(encoding="utf-8")

        self.assertIn("process.env.HERMES_TUI_ACTIVE_SESSION_FILE", widget)
        self.assertIn("const sessionRef = activeSessionRef()", widget)
        # The reference is attached only when there is one; the mechanism claim
        # beside it is unconditional (pinned by its own case below), so the two
        # are two statements rather than one.
        self.assertIn("if (sessionRef) env.OMH_HUD_TUI_SESSION_REF = sessionRef", widget)
        self.assertIn("tui_session_ref=os.environ.get('OMH_HUD_TUI_SESSION_REF', '')", widget)
        # A malformed value is dropped, never mutated into a different key.
        self.assertIn("SESSION_REF_SHAPE.test(sessionId) ? sessionId : ''", widget)
        self.assertNotIn("...process.env", widget)

    def test_the_widget_declares_its_mechanism_separately_from_its_value(self) -> None:
        # Having an identity mechanism and that mechanism producing a value are
        # different facts, and only the first decides whether the most-recently-
        # active TUI may answer. The widget always has one, so it always says
        # so; the reference is sent only when there is one to send. Collapsing
        # the two into an empty reference is what let a freshly opened TUI --
        # its active-session file created but not yet written -- render the
        # plan of the session beside it.
        widget = resources.files("omh.tui_widgets").joinpath("omh-status.mjs").read_text(encoding="utf-8")

        self.assertIn(
            "tui_identity_expected=os.environ.get('OMH_HUD_TUI_IDENTITY', '') == '1'", widget
        )
        # The claim is keyed on having the file, not on what it held.
        self.assertIn(
            "OMH_HUD_TUI_IDENTITY: ACTIVE_SESSION_FILE ? '1' : ''", widget
        )
        # And the reference stays conditional on actually having one.
        self.assertIn("if (sessionRef) env.OMH_HUD_TUI_SESSION_REF = sessionRef", widget)

    def test_the_widget_can_pass_no_identity_and_that_answer_is_pinned(self) -> None:
        # The widget's reference resolving to nothing is what used to put one
        # session's plan in every TUI, so the remaining way it can carry NO
        # reference is worth stating rather than assuming away. It can: every
        # guard in `activeSessionRef` returns the empty string rather than a
        # substitute, and the host launcher creates the active-session file
        # empty (`tempfile.mkstemp` then `os.close`) and writes it only on
        # session create, activate or resume -- so between TUI launch and the
        # first of those, the file exists and is empty.
        widget = resources.files("omh.tui_widgets").joinpath("omh-status.mjs").read_text(encoding="utf-8")

        for guard in (
            "if (!ACTIVE_SESSION_FILE) return ''",
            "if (!info.isFile() || info.size > ACTIVE_SESSION_FILE_MAX_BYTES) return ''",
            "    } catch {\n      return ''\n    }",
        ):
            self.assertIn(guard, widget)
        # An empty file reaches that catch: the parse is what fails, so the
        # pre-first-write window yields '' and never a partial identity.
        if shutil.which("node"):
            with TemporaryDirectory() as tmp:
                empty = Path(tmp) / "hermes-tui-active-session-test.json"
                empty.touch()
                probe = subprocess.run(
                    [
                        "node",
                        "-e",
                        "const {readFileSync}=require('node:fs');"
                        "try{JSON.parse(readFileSync(process.argv[1],'utf8'));"
                        "console.log('parsed')}catch{console.log('threw')}",
                        str(empty),
                    ],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                self.assertEqual(probe.stdout.strip(), "threw")
        # What the reader does with an empty reference is the deliberate
        # most-recently-active carve-out, pinned with its reason by
        # TodoSessionIsolationTests.
        # test_an_identity_less_read_still_answers_for_the_most_recent_tui.
        # That is NOT the removed fallback: a reference that merely fails to
        # resolve keeps its own identity and reads no other session's record.
        self.assertIn("tui_session_ref=os.environ.get('OMH_HUD_TUI_SESSION_REF', '')", widget)

    def test_widget_frames_the_composer_and_docks_the_plan_on_top(self) -> None:
        # Changed on purpose (this used to pin a single dock-bottom app and
        # forbid dock-top). The single bottom dock framed the OMH section
        # instead of the chat input ('채팅창에 선 두개가 있어야지 왜 tui에
        # 있어') and sank the plan the owner always read above the input
        # ('투두가 왜 하단에 떠 기존에는 상단에 잘 떴었는데'). The layout is
        # now: plan todo in dock-top, closed by the rule directly above the
        # input; the bottom dock opens with the rule below the input and
        # carries status and activity rows with no closing rule.
        widget = resources.files("omh.tui_widgets").joinpath("omh-status.mjs").read_text(encoding="utf-8")

        # Three apps: the two ambient docks framing the composer, plus the
        # modal chain picker (`/omh-model`), which renders no dock at all.
        self.assertEqual(widget.count("defineWidgetApp({"), 3)
        self.assertEqual(widget.count("zone: 'dock-bottom'"), 1)
        self.assertEqual(widget.count("zone: 'dock-top'"), 1)
        self.assertIn("id: 'omh-todo'", widget)
        self.assertIn("id: 'omh-status'", widget)
        # The todo panel renders only in the top dock, and every branch of it
        # (no plan, all done, established) closes with the plain frame rule
        # so the composer frame never blinks with the plan lifecycle.
        self.assertEqual(widget.count("h(TodoPanel"), 1)
        self.assertNotIn("FrameRule", widget)
        # Both apps gate on the same payload validity, so neither half of the
        # frame renders on a host where the plugin does not answer.
        self.assertEqual(
            widget.count(
                "if (!state.payload || state.payload.error || state.payload.privacy !== 'metadata_only') return null"
            ),
            2,
        )
        # One snapshot pass feeds both docks; a second poller would let the
        # two frame rules disagree about payload freshness.
        self.assertEqual(widget.count("updateWidget(todoApp, apply)"), 1)
        self.assertEqual(widget.count("openWidget(todoApp, todoApp.init(''))"), 1)

    def test_widget_renders_machine_graph_fields_without_input_capture(self) -> None:
        widget = resources.files("omh.tui_widgets").joinpath("omh-status.mjs").read_text(encoding="utf-8")

        self.assertIn("const graph = payload.graph", widget)
        self.assertIn("graph.status === 'active'", widget)
        self.assertIn("graph.nodes", widget)
        self.assertIn("graph.edges", widget)
        self.assertIn("graph.edge_count", widget)
        self.assertIn("graph.frontier", widget)
        self.assertIn("graph.hidden_nodes", widget)
        self.assertIn("node.blocked_by", widget)
        self.assertIn("node.in_frontier", widget)
        self.assertIn("Math.max(0, viewportRows - 8)", widget)
        self.assertIn("OMH_SUBAGENT_GRAPH", widget)
        self.assertIn("graph_preference=os.environ.get('OMH_SUBAGENT_GRAPH', 'auto')", widget)
        self.assertIn("const graphLine =", widget)
        self.assertIn("const truncateTextCells =", widget)
        self.assertIn("const sanitizeText =", widget)
        self.assertIn("sanitizeText(value).slice(0, 4096)", widget)
        # The route identity is shaped by parentheses -- `category:architect(
        # anthropic/claude...)`, `(codex/maestro ...)`, `turn 3 (12 tools)` --
        # so the allowlist keeps them; stripping them rendered the category
        # and model as one run-on token (`architectanthropic/c...`).
        self.assertIn("/[^\\p{L}\\p{N} .:/_·|+()\\[\\]!\\-]/gu", widget)
        self.assertNotIn("safeText(value, 4096)", widget)
        self.assertIn("'blocked_by_dependency'", widget)
        self.assertIn("'dry_run_planned'", widget)
        self.assertNotIn("useInput", widget)
        self.assertNotIn("useKeypress", widget)

    def test_fanout_dispatch_rows_render_a_warn_colored_maestro_identity(self) -> None:
        # `omh coding fanout dispatch` spawns a local CLI directly (the
        # Maestro lane by definition), and the reader tags that row
        # `dispatch_lane` so it renders in the same agent list as Hermes-
        # native delegate_task rows -- same truncation, dots, and state
        # colors -- but with `(<executor>/maestro <model>)` in place of the
        # category:model route, warn-colored to stand apart from the default
        # Hermes-native lane.
        widget = resources.files("omh.tui_widgets").joinpath("omh-status.mjs").read_text(encoding="utf-8")

        self.assertIn(
            "const MAESTRO_EXECUTOR_SHORT_NAMES = { codex: 'codex', claude_code: 'claude', omo_runtime: 'omo', hermes_local: 'hermes' }",
            widget,
        )
        self.assertIn("const dispatchLane = safeText(row.dispatch_lane)", widget)
        # The identity segment is now the row's own column rather than the
        # first droppable metadata entry, so it is bound once and rendered
        # between the title and the measured tail.
        self.assertIn(
            "return dispatchLane ? metricSegment('maestro', dispatchIdentity) : metricSegment(routeKind, route)",
            widget,
        )
        self.assertIn("layout.routeKind === 'route-fallback' || layout.routeKind === 'maestro'", widget)
        self.assertIn("|| segment.kind === 'maestro'", widget)

    def test_kanban_lane_rows_render_an_accent_colored_board_identity(self) -> None:
        # A Hermes Kanban task (reader: kanban_board_reader) is board work a
        # dispatcher runs as a detached worker, not a delegate_task child.
        # Its identity names the assignee profile in the native lane's own
        # shape -- `category:name(model:effort)` becomes
        # `kanban/miku(gpt-5.6-sol:high)` -- and the whole row (marker, scope
        # and id, title, identity, elapsed) renders in the theme's accent
        # tone, the one token the widget had no other use for, so a board
        # lane reads as one turquoise line beside the native rows. Only
        # `blocked` and `stale` keep their semantic colours. Still never a
        # literal.
        widget = resources.files("omh.tui_widgets").joinpath("omh-status.mjs").read_text(encoding="utf-8")

        self.assertIn("if (safeText(row.lane_backend) === 'kanban') {", widget)
        self.assertIn("return metricSegment('kanban', `kanban/${assignee}${detail ? `(${detail})` : ''}`)", widget)
        self.assertIn("layout.routeKind === 'kanban'", widget)
        self.assertIn("const board = safeText(row.lane_backend) === 'kanban'", widget)
        self.assertEqual(widget.count("t.color.accent"), 7)
        self.assertIn("const kindTag = row => safeText(row.lane_backend) === 'kanban'", widget)
        self.assertIn("{ color: t.color.accent, bold: true } : { color: t.color.muted, bold: true }", widget)
        # Board verdicts the reader projects: a queued task has no worker and
        # must not spin (a static dot), a stale one has a worker that stopped
        # heartbeating (a warn bang). The tail keeps the board's own status
        # word (`ready`, `review`, `archived`) rather than the verdict, and
        # only blocked/stale override the board row's accent tone.
        self.assertIn("const queued = row.state === 'queued'", widget)
        self.assertIn("const stale = row.state === 'stale'", widget)
        self.assertIn("queued ? '·' : stale ? '!'", widget)
        self.assertIn("blocked ? t.color.error : stale ? t.color.warn : board ? t.color.accent : queued ? t.color.muted : t.color.ok", widget)
        self.assertIn("board ? { color: t.color.accent, dimColor: true } : { color: t.color.muted }", widget)
        self.assertIn("? safeText(row.native_status) || safeText(row.state) || 'running'", widget)
        self.assertIn("scheduled: 'sched', archived: 'arch', review: 'rev'", widget)
        # The header keeps its count line and appends the board tally only
        # while the board has rows, plus the reader's dispatcher verdict.
        self.assertIn("const board = payload.kanban || {}", widget)
        self.assertIn("` · board ${Number(board.queued) || 0}q ${Number(board.running) || 0}r ${Number(board.blocked) || 0}b`", widget)
        self.assertIn("board.dispatcher_presence === 'not_observed'", widget)
        self.assertIn("' · dispatcher not observed'", widget)

    def test_hud_liveness_signal_drives_the_status_line_todo_and_shot_badge(self) -> None:
        # 2026-08 HUD liveness fix: exact in-flight tool-call state (paired
        # from pre_tool_call/post_tool_call by tool_call_id) replaces three
        # things that used to lie -- a lingering green active todo item, a
        # parallel-shot badge stuck at the ring ceiling, and no signal at all
        # while calls were genuinely running.
        widget = resources.files("omh.tui_widgets").joinpath("omh-status.mjs").read_text(encoding="utf-8")

        # Status line: a live segment renders only while open calls exist AND
        # this install has actually observed post_tool_call fire -- an
        # unsupported host's ledger can only expire entries, never
        # legitimately close them, so a bare `live` reading there is not
        # trustworthy (P2-1). No ambiguous-width glyph prefixes it (P3-4).
        self.assertIn(
            "payload.activity && payload.activity.live && payload.activity.post_tool_call_observed",
            widget,
        )
        self.assertIn("`${plural(Number(payload.activity.open_call_count) || 0, 'tool')}", widget)
        self.assertNotIn("⚙", widget)

        # Todo panel: the active marker is warn-colored and carries a stall
        # hint when the HUD says not-live, instead of always reading green --
        # but only once liveness is answerable; an unsupported host falls
        # back to always-live (P2-1), and the stall age itself comes from
        # the reader, not a Date.now() computed in render (P1-1).
        self.assertIn("const answerable = !!(payload.activity && payload.activity.post_tool_call_observed)", widget)
        self.assertIn(
            "const live = answerable ? !!(payload.activity && payload.activity.live) : true",
            widget,
        )
        self.assertIn("color: item.state === 'active' ? (live ? t.color.ok : t.color.warn)", widget)
        self.assertIn(
            "unchangedElapsed ? h(Text, { color: t.color.muted }, ` (unchanged ${unchangedElapsed})`)",
            widget,
        )
        self.assertIn("const seconds = todo.updated_age_seconds", widget)
        self.assertNotIn("Date.parse(safeText(todo.updated_at)", widget)

        # Shot badge: tied to open calls while live, dimmed history with age
        # once every member has closed -- never the saturated ring size, and
        # never the burst's raw dispatch size either (P1-2): the dimmed form
        # reads the group's measured peak concurrency.
        self.assertIn("const openCount = Number(shot.open_count) || 0", widget)
        self.assertIn("if (openCount > 0) {", widget)
        self.assertIn("(${age} ago)", widget)
        self.assertIn("parallel shot ×${Number(shot.peak_open_count) || 0}", widget)
        self.assertNotIn("parallel shot ×${Number(shot.size)", widget)

        # The exact in-flight age and the reader-computed todo stall age are
        # the only fields allowed to drift every poll without forcing a
        # repaint; the liveness transition itself (open_call_count, live)
        # stays out of VOLATILE_KEYS on purpose.
        self.assertIn("'oldest_open_elapsed_seconds',", widget)
        self.assertIn("'updated_age_seconds',", widget)
        self.assertNotIn("'open_call_count',", widget)
        self.assertNotIn("'live',", widget)

    def test_a_stuck_unit_never_renders_as_the_dispatch_state(self) -> None:
        # "Process alive" and "work progressing" are different states and must
        # never render the same. A graph node whose reader assessed its own
        # output and found it stuck replaces the dispatch word outright and
        # carries the reason and the stall age beside it.
        widget = resources.files("omh.tui_widgets").joinpath("omh-status.mjs").read_text(encoding="utf-8")

        self.assertIn("const stuckState = safeText(node.unit_state)", widget)
        self.assertIn("const state = stuckState || dispatchState", widget)
        self.assertIn("const stallSeconds = Number(node.stalled_for_seconds) || 0", widget)
        self.assertIn("safeText(node.state_reason)", widget)
        self.assertIn("since new output", widget)
        # Its own marker and the warn tone, so a stuck node is visible before
        # the line is read at all.
        self.assertIn("const marker = stuckState\n          ? '[~]'", widget)
        self.assertIn("color: stuckState\n              ? t.color.warn", widget)
        self.assertIn("${state}${stuckSuffix}${suffix}", widget)

    def test_widget_registers_the_chain_picker_as_a_modal_app_behind_a_guard(self) -> None:
        widget = resources.files("omh.tui_widgets").joinpath("omh-status.mjs").read_text(encoding="utf-8")

        # The host's own /model picks the session model and cannot be
        # shadowed; OMH's per-category picker lives under its own id, as a
        # modal (it owns every keypress while open) and only when the host
        # exposes the overlay primitives -- an older host keeps the docks.
        self.assertIn("id: 'omh-model'", widget)
        self.assertNotIn("id: 'model'", widget)
        self.assertEqual(widget.count("mode: 'modal'"), 1)
        self.assertIn("if (Overlay && Dialog) {", widget)
        self.assertIn("const { Box, Dialog, Overlay, Text, defineWidgetApp, h, openWidget, updateWidget } = sdk", widget)
        # Reading and saving go through the installed bundle's picker model,
        # with the same isolated interpreter spawn the HUD reader uses.
        self.assertIn("from omh.model_chain_picker import picker_rows", widget)
        self.assertIn("from omh.model_chain_picker import apply_picker_changes", widget)
        # The spawns name no store. The bundle resolves it from the Hermes
        # home -- a profile's own setting first -- so an `OMH_HOME` forced
        # here cannot send the HUD or the picker to a file the profile's
        # dispatches never read (#1679).
        self.assertEqual(widget.count("os.environ.get('OMH_HOME')"), 0)
        self.assertEqual(widget.count("read_omh_hud(None, os.environ.get('HERMES_HOME')"), 1)
        self.assertEqual(widget.count("picker_rows(None, hermes_home=os.environ.get('HERMES_HOME'))"), 1)
        self.assertEqual(widget.count("apply_picker_changes(None, json.load(sys.stdin), hermes_home=os.environ.get('HERMES_HOME'))"), 1)
        self.assertIn("['-I', '-B', '-c', script]", widget)
        self.assertIn("Mirror of model_chain_picker.step_head_model", widget)
        self.assertIn("Mirror of model_chain_picker.step_effort", widget)
        self.assertNotIn("useInput", widget)

        widget = resources.files("omh.tui_widgets").joinpath("omh-status.mjs").read_text(encoding="utf-8")

        self.assertIn("zone: 'dock-bottom'", widget)
        self.assertNotIn("zone: 'top-right'", widget)
        # Plan todo above the input, status and activity rows below it — the
        # owner's placement, restored after the single-bottom-dock interim.
        self.assertEqual(widget.count("zone: 'dock-top'"), 1)
        self.assertIn("id: 'omh-todo'", widget)
        self.assertIn("TodoPanel", widget)
        self.assertIn("truncateCells(item.text", widget)
        self.assertIn("safeText(todo.title)", widget)
        # An installed OMH stays discoverable from an idle session: only the
        # activity rows are gated on live work, never the header.
        self.assertNotIn("|| !payload.active", widget)
        self.assertIn("const active = !!payload.active", widget)
        self.assertIn("width: '100%'", widget)
        # The Rule frame replaced the marginTop spacer: the docks carry the
        # classic composer frame, rules sitting tight against the input --
        # padding was tried at one and two rows and the owner picked none.
        # Exactly five plain-rule renders: the dock-bottom opener plus the
        # four todo-panel closers (no plan, all done, the summary fallback a
        # terminal too short for a checklist gets, and established). The
        # badge that briefly dressed the top rule moved to the [Plan] header,
        # so every rule is plain, byte-stable chrome again.
        self.assertIn("const Rule = ", widget)
        self.assertNotIn("Gap", widget)
        self.assertEqual(widget.count("h(Rule, { columns, t })"), 5)
        # Text, not chrome — changed on purpose a second time, by owner
        # direction after living with the bordered card: the OMH surface reads
        # like the host's own status line, dense text in the TUI's idiom. The
        # border that briefly asserted the panel identity now marks the
        # RETIRED design, and colours still resolve only through the active
        # theme — a literal hex would freeze the surface on one palette while
        # the rest of the TUI followed the user's skin.
        self.assertNotIn("borderStyle:", widget)
        self.assertNotIn("panelProps", widget)
        self.assertNotIn("color: '#", widget)
        # The bracket tags are the shared grammar between the two docks.
        self.assertIn("'⚚ [OMH]'", widget)
        self.assertEqual(widget.count("'[Plan]'"), 2)
        self.assertIn("const SEPARATOR = ' │ '", widget)
        self.assertNotIn("metricRow", widget)
        self.assertIn("...rows.map", widget)
        self.assertNotIn("...maestroRows.map", widget)
        self.assertNotIn("latest ? h(Text", widget)
        self.assertIn("const version = safeText(payload.version)", widget)
        # Header composition, changed on purpose (this used to assert the
        # literal "`[OMH] ${version}`"). That header named the product twice
        # and then claimed "Ultra Work Ready" whether or not anything was
        # running, so it read identically at four active agents and at zero.
        # What matters now is the contract, not the wording: the version is
        # still shown, every colour still resolves through the active theme,
        # and the state segment is derived rather than fixed.
        self.assertIn("` v${version}`", widget)
        self.assertIn("hudStateLabel(active, agents)", widget)
        self.assertIn("if (!active) return 'ready'", widget)
        # Hermes-native delegation rows linger after finishing: a done row
        # carries a check mark instead of spinning forever, and a linger-only
        # block says "N done" rather than the dishonest "0 agents".
        self.assertIn("done ? '✓'", widget)
        self.assertIn("if (!running && !blocked && done) return `${done} done`", widget)
        # A phase-structured plan (todo init) shows the current phase's name
        # above its checklist and the phase count next to done/total.
        self.assertIn("safeText(todo.display_phase)", widget)
        self.assertIn("` · ${phaseCount} phases`", widget)
        # The todo panel renders the plan from todo.items: every phase is a
        # header row with its tasks indented one level beneath it — even a
        # single-task phase; the old one-line merge collapsed the structure
        # the owner reads ('[] 이거 탭한번쳐서 한개여도. 그 구조로 나오게').
        # Subtasks (depth 1..3) indent further, and past seven visible items
        # the window anchors at current work with muted
        # "... (N earlier/later tasks)" fold lines.
        self.assertIn("Array.isArray(todo.items)", widget)
        self.assertIn("last.phase === phase", widget)
        self.assertNotIn("isMerged", widget)
        self.assertNotIn("phaseColumn", widget)
        # Eight body rows matches the senpi/OMO todo widget's visible budget.
        self.assertIn("const TODO_DISPLAY_ROWS = 8", widget)
        self.assertIn("depthOf", widget)
        self.assertIn("(!phase && depthOf(item) > 0)", widget)
        self.assertIn("'  '.repeat(depthOf(item) + (group.phase ? 1 : 0))", widget)
        self.assertIn("task${count === 1 ? '' : 's'}", widget)
        self.assertIn("'todo-earlier'", widget)
        self.assertIn("'todo-later'", widget)
        self.assertNotIn("todo.display_items", widget)
        self.assertNotIn("more_count", widget)
        self.assertNotIn("more}", widget)
        # Drag-copy contract for the QUIET dock: an unchanged snapshot must
        # not repaint (repaints clear an in-progress terminal selection), and
        # metric-only drift repaints at most once per throttle window. While
        # a row is RUNNING the dock trades selection stability for liveness —
        # LiveActivityRows mounts on the shimmer clock so the spinner turns
        # and elapsed ticks (snapshot value + seconds since it arrived);
        # idle and linger-only docks render the static branch.
        self.assertIn("if (serialized === lastSnapshot) return", widget)
        self.assertIn("LiveActivityRows", widget)
        self.assertIn("row.state === 'running'", widget)
        self.assertIn("(Date.now() - receivedAt) / 1000", widget)
        self.assertIn("receivedAt: Date.now()", widget)
        self.assertIn("h(ActivityRows, { columns, extraSeconds: 0, frame: 0, mainRows", widget)
        self.assertIn("const METRICS_REPAINT_MS = 30_000", widget)
        self.assertIn(
            "if (structural === lastStructural && Date.now() - lastPaintAt < METRICS_REPAINT_MS) return",
            widget,
        )
        for volatile in (
            "'cache_hit_percentage'",
            "'context_percentage'",
            "'cost_usd'",
            "'elapsed_seconds'",
            "'observed_at'",
            "'tokens'",
            "'tokens_per_second'",
            "'tool_count'",
            "'turn_count'",
        ):
            self.assertIn(volatile, widget)
        # (bracket-tag grammar asserted above replaces the BRAND_MARK pair)
        # The old header's literal pieces ("-", "Oh My Hermes", "Ultra Work",
        # "Ready") are gone on purpose; asserting them back would re-pin the
        # wording this change exists to replace. The separator is now shared
        # between both panels instead of hand-written per segment.
        self.assertNotIn("'Ultra Work'", widget)
        # Running rows are alive again by owner direction (the static orange
        # marker with a frozen counter read as broken): spinner on the
        # shimmer clock, real-time elapsed, and cost segments render only
        # when a nonzero cost was actually observed — a subscription-billed
        # host records none, and a permanent $0.0000 read as a bug.
        self.assertIn("SPINNER_FRAMES", widget)
        self.assertIn("SPINNER_FRAMES[frame % SPINNER_FRAMES.length]", widget)
        self.assertNotIn("elapsedCoarse", widget)
        self.assertIn("row.cost_usd > 0", widget)
        # Token-derived approximations (subscription-billed hosts record no
        # per-call cost) render with a `~`; a zero renders only with the
        # recorded provenance that earns it (status first, else source —
        # whatever word the host wrote, never a vocabulary this surface
        # enumerates), and never with a `~`, because an exact zero is not an
        # approximation. Row and header apply the same rule.
        self.assertIn("row.cost_approximate ? '~' : ''", widget)
        self.assertIn("function costSegmentText(row)", widget)
        self.assertIn("$${row.cost_usd.toFixed(4)} (${provenance})", widget)
        self.assertIn("safeText(row.cost_status) || safeText(row.cost_source)", widget)
        self.assertIn("const zeroCostProvenance", widget)
        self.assertIn("$${cost.toFixed(3)} (${zeroCostProvenance})", widget)
        self.assertIn("`${approximate ? '~' : ''}$${cost.toFixed(3)}`", widget)
        # Claude Code's token-counter idiom (184.8k, 2.1m): observed subagent
        # token counts render per row and summed on the header, one decimal
        # with trailing .0 trimmed. The row segment sits BEFORE cost so the
        # narrow-terminal drop order sheds the dollar figure first and keeps
        # the token count; an unreadable value renders nothing.
        self.assertIn("const tokenCountText", widget)
        # One decimal is always kept above a thousand (`77.0k`, not `77k`):
        # trimming it made a round count change width mid-wave and broke the
        # column's decimal alignment.
        self.assertIn("`${amount.toFixed(1)}${unit}`", widget)
        self.assertNotIn(".replace(/\\.0$/, '')", widget)
        # The unit break sits where one-decimal rounding lands (999,950 reads
        # 1m, never 1000k) and sub-thousand counts render bare. A recorded
        # zero now renders `0`: the reader sends a number only once the row is
        # terminal or has reported, so zero means the run consumed nothing --
        # the shape of a dispatch that died before its first API call, which
        # the old blank made indistinguishable from an unmeasured row.
        self.assertIn("value < 999_950 ?", widget)
        self.assertIn("if (value < 1000) return", widget)
        self.assertIn("|| value < 0) return ''", widget)
        # Claude Code-style grid ('절대위치로 … 클로드코드처럼 정렬'): fixed
        # columns first, variable metadata after. The owner moved the measured
        # block beside the identity it belongs to ('category 바로옆에 두고
        # 그뒤에 캐시히트나 턴'), so the order is title, route/category, then
        # `state · elapsed · N tokens` -- each piece padded to a constant cell
        # width so the token figures still line up vertically down the list --
        # and only then rate, cache, turn and cost, which the drop loop still
        # sheds by rank without ever touching the tail.
        self.assertIn("` · ${tokenText.padStart(6)} tokens`", widget)
        # The route column is never truncated: category, model and effort are
        # the column's whole purpose ('category, modelname, effort만 잘
        # 나오면 되니까'). It takes the widest identity in the list; when the
        # full `category:name(model:effort)` shape does not fit beside the
        # prefix, the tail and an 8-cell title, the `category:` literal is
        # shed for the whole list and the action title shrinks (to 4 cells at
        # the floor). The old percentage caps cut the model mid-name.
        self.assertIn("const ROUTE_PREFIX = 'category:'", widget)
        self.assertIn("const routeCompact = text => text.startsWith(ROUTE_PREFIX) ? text.slice(ROUTE_PREFIX.length) : text", widget)
        self.assertIn("return { compact: Math.max(width.compact, cellWidth(routeCompact(text))), full: Math.max(width.full, cellWidth(text)) }", widget)
        self.assertIn("const routeShedPrefix = routeColumn.full > routeRoom", widget)
        self.assertIn("const routeCap = routeShedPrefix ? routeColumn.compact : routeColumn.full", widget)
        self.assertIn("? `${separator}${padCells(routeText, routeCap)}`", widget)
        self.assertNotIn("truncateCells(routeText", widget)
        self.assertNotIn("truncateCells(routeSegment.text", widget)
        self.assertIn("const actionWidth = Math.max(4, Math.min(actionCap, budget - cellWidth(prefix) - routeWidth - tailWidth - 2))", widget)
        self.assertNotIn("Math.floor(columns * 0.3)", widget)
        self.assertNotIn("Math.floor(columns * 0.24)", widget)
        # The label names the model, never its provider: `anthropic/` ate the
        # column and truncated to `category:architect(anthropic/`, hiding
        # whether the lane ran opus or fable. Only the segment after the last
        # slash reaches the label (both the category route and the maestro
        # dispatch identity); `row.provider` stays a separate reader field.
        self.assertIn("const modelName = safeText(row.model).split('/').pop()", widget)
        self.assertIn("const model = [modelName, safeText(row.effort)].filter(Boolean).join(':')", widget)
        self.assertIn("${modelName ? ` ${modelName}` : ''}", widget)
        self.assertNotIn("truncateCells(modelName, 20)", widget)
        self.assertNotIn("truncateCells(row.model, 20)", widget)
        # The route column reserves its width per LIST, exactly like tokens:
        # otherwise a row without a category would slide its tail left and
        # break the very alignment this ordering exists to keep.
        self.assertIn(
            "const routeColumn = routeColumnWidth([...mainRows, ...rows])",
            widget,
        )
        self.assertIn("h(Text, { color: statusColor }, layout.tailState)", widget)
        # The tail is one fixed-width block but two colours: elapsed keeps the
        # muted tint every metric shares, and the token count -- the row's one
        # plain quantity -- reads in `statusFg`, the tone the host status line
        # spends on its own token gauge ('tokens는 약간 회색'). A theme token
        # either way; no literal colour enters this widget.
        self.assertIn("h(Text, board ? { color: t.color.accent, dimColor: true } : { color: t.color.muted }, layout.tailRest)", widget)
        self.assertIn("h(Text, { color: t.color.statusFg }, layout.tailTokens)", widget)
        self.assertIn("const tailTokens = tokensColumn ? tokensPiece : ''", widget)
        # Rate reads beside the token count it is derived from ('tokens,
        # tok/s, cache, turns 순으로'), so the metric run is ordered rate,
        # cache, ctx, turn, cost on screen.
        self.assertLess(widget.index("metricSegment('rate'"), widget.index("metricSegment('cache'"))
        self.assertLess(widget.index("metricSegment('cache'"), widget.index("metricSegment('turn'"))
        self.assertLess(widget.index("metricSegment('turn'"), widget.index("metricSegment('cost'"))
        # Screen position stopped being shed priority when rate moved left, so
        # each segment carries a `drop` rank and the loop sheds the highest --
        # rate first, then cost, then turn -- exactly the order the tail's
        # comment has always promised. Popping the last segment would now shed
        # cost before rate and drop the cheapest figure last.
        self.assertIn("const metricSegment = (kind, text, drop = 0) => ({ drop, kind, text })", widget)
        self.assertIn("if (segments[index].drop > segments[shed].drop) shed = index", widget)
        self.assertIn("segments.splice(shed, 1)", widget)
        self.assertNotIn("segments.pop()", widget)
        # Cache hit rate renders in the palette's amber ('cache는 노란색'),
        # which it shares with the route/dispatch warnings; turn and rate stay
        # muted, so the run reads grey count, muted rate, amber cache, muted
        # turn.
        self.assertIn("|| segment.kind === 'cache'\n                ? t.color.warn", widget)
        # The tokens column exists per LIST: a row with no observed count
        # holds the grid with blank cells, and a wave with no counts at all
        # drops the column instead of wasting the width.
        self.assertIn("' '.repeat(tokensWidth)", widget)
        self.assertIn(
            "const tokensColumn = [...mainRows, ...rows].some(row => tokenCountText(row.tokens))",
            widget,
        )
        # The header renders a summed ZERO whenever any row carried a figure:
        # a dispatch that died before its first API call really did consume
        # nothing, and blanking that made a failed wave read exactly like an
        # unmeasured one. Only a wave where no row reports at all still hides
        # the segment.
        self.assertIn(
            "tokens: rows.some(row => Number.isFinite(row.tokens))",
            widget,
        )
        self.assertIn("if (!Number.isFinite(value) || value < 0) return ''", widget)
        # The summed count anchors the header's right edge too, and the
        # header has no drop loop, so the segment hides below 100 columns
        # instead of pushing ctx and the yolo readout past truncate-end.
        self.assertIn("columns >= 100 && metrics.tokens", widget)
        self.assertIn("` • ${metrics.tokens}`", widget)
        self.assertLess(widget.index("' • yolo mode: '"), widget.index("` • ${metrics.tokens}`"))
        # Delegate goals (row titles) are a FIXED padded column capped at
        # ~40% of the terminal, 48 cells at most, and always shrink before
        # the tail: the metadata column starts aligned and the tail block
        # keeps its right anchor even on narrow terminals.
        self.assertIn("Math.min(48, Math.floor(columns * 0.4))", widget)
        self.assertIn(
            "Math.min(actionCap, budget - cellWidth(prefix) - routeWidth - tailWidth - 2)",
            widget,
        )
        # The plan panel's liveness cues are the ONE sanctioned animation:
        # a colour wave through the active item's characters plus a walking
        # ellipsis on the [Plan] header, both mounted only while an active
        # item exists. The shimmer hook is accessed guarded (never
        # destructured), so hosts without it render a static line instead of
        # crashing the widget — and it stays out of the doctor's required
        # SDK surface for the same reason.
        self.assertIn("typeof sdk.useShimmerPhase === 'function'", widget)
        self.assertNotIn(", useShimmerPhase }", widget)
        self.assertIn("ShimmerText", widget)
        self.assertIn("PlanPulse", widget)
        # Changed on purpose (2026-08 HUD liveness fix): the wave and the
        # walking ellipsis both imply "actually running", so both now gate on
        # the HUD's exact in-flight signal too, not just an active item's
        # existence -- a stopped turn with an incomplete todo must not
        # animate as if work were still happening.
        self.assertIn("hasActive && live ? h(PlanPulse, { t }) : null", widget)
        self.assertIn(
            "const live = answerable ? !!(payload.activity && payload.activity.live) : true",
            widget,
        )
        self.assertIn("unchanged ${unchangedElapsed}", widget)
        self.assertNotIn("Number.MAX_SAFE_INTEGER", widget)
        # Changed on purpose: the parallel-shot badge moved off the bottom
        # status line onto the dock-top frame rule — the transcript's
        # "Tool calls (N)" group is host-owned rendering OMH cannot decorate.
        # Changed on purpose a second time: the badge now rides the [Plan]
        # header — the owner's chosen spot, directly under the host status
        # rule ('여기 위치 옆에 뜨게') — and the seconds-scale reader
        # freshness makes it vanish right after the batch lands. The bottom
        # dock and the frame rules render no parallel-shot text.
        self.assertIn("parallel shot ×", widget)
        self.assertIn("payload.parallel_shot", widget)
        self.assertIn("planShotBadge(payload, t)", widget)
        # Shift+Tab yolo state, as last hook-observed: ON warns in the
        # theme's yellow, OFF rests in the label blue, and an unobserved or
        # stale ledger renders nothing rather than a guessed "off".
        self.assertIn("' • yolo mode: '", widget)
        self.assertIn("payload.yolo && payload.yolo.status === 'observed'", widget)
        self.assertIn("payload.yolo.enabled ? t.color.warn : t.color.label", widget)
        self.assertNotIn("• parallel shot", widget)
        # Five-row activity budget with running AGENT lanes exempt from the
        # cap (OMO DAG-widget pattern) — the old hard `Math.min(3, …)` clamp
        # hid running lanes silently, which is the complaint that removed it.
        # The viewport still bounds the dock (chrome included), and both the
        # widget's own drop and the reader's cap surface as `+N more`.
        self.assertNotIn("Math.min(3, viewportRows", widget)
        self.assertIn("Math.max(Math.max(5 - mainRows.length, 1), runningAgents)", widget)
        self.assertIn("viewportRows - 5", widget)
        self.assertIn("const hiddenRows", widget)
        self.assertIn("Number(agents.hidden_rows) || 0", widget)
        self.assertIn("+${hiddenRows} more", widget)
        self.assertIn("hiddenRows\n        ? h(Text", widget)
        self.assertNotIn("spinnerTimerKey", widget)
        self.assertIn("ActivityRow", widget)
        self.assertIn("truncateCells", widget)
        self.assertIn("category:", widget)
        # Prepared-route provenance renders: a fallback lane carries a
        # warning-colored `fallback` token, and an exhausted chain reads
        # `category→inherit` instead of converging into plain inherit.
        self.assertIn("route_origin", widget)
        self.assertIn("route-fallback", widget)
        # One label shape for every lane: category(model tag). The category
        # names the lane and never changes; only the parenthesized model and
        # its state token (fallback / inherit) move.
        self.assertIn("routeOrigin === 'fallback' ? ['fallback', parentTag]", widget)
        self.assertIn("routeOrigin === 'exhausted_to_inherit' ? 'inherit'", widget)
        # A lane routed to the parent's own model keeps its category and
        # wears `=parent`; a child with no route record on that model is
        # the plain `inherit(model)` — inherit is not a category, so it
        # never wears the `category:` prefix.
        self.assertIn("const parentTag = row.same_as_parent === true ? '=parent' : ''", widget)
        # A fallback that landed on the parent's model keeps both tokens.
        self.assertIn("['fallback', parentTag].filter(Boolean).join(' ')", widget)
        self.assertIn("displayCategory === 'inherit'", widget)
        self.assertIn("? `inherit${model ? `(${model})` : ''}`", widget)
        self.assertNotIn("→inherit", widget)
        self.assertIn("row.route_category", widget)
        self.assertIn("tools", widget)
        self.assertIn("tok/s", widget)
        self.assertIn("cache_hit_percentage", widget)
        self.assertIn("context_percentage", widget)
        # Only observed cache/ctx values render on rows: "uncollected" was a
        # permanent label for hermes-native children (the host never records
        # a child's context percentage) and read as a fixable problem.
        self.assertNotIn("uncollected", widget)
        # The HEADER follows the same rule. `ctx --` was the last permanent
        # not-collected label, and it was permanent on EVERY session, not
        # some: `context_percentage` has a reader projection and this render
        # path but no production writer anywhere, and none can be derived --
        # the host's usage table sums input tokens across calls, which is not
        # a context size, and nothing records a model's window. The slot
        # stays wired for a future writer; the dash is gone.
        self.assertNotIn("ctx --", widget)
        self.assertIn("Number.isFinite(ctx) ? `ctx ${ctx}%` : ''", widget)
        self.assertIn("${metrics.ctx ? ` • ${metrics.ctx}` : ''}", widget)
        self.assertIn("'MAIN'", widget)
        self.assertIn("maestro.rows", widget)
        self.assertIn("fallback:", widget)
        self.assertIn("execFile(", widget)
        self.assertIn("Symbol.for(", widget)
        self.assertIn("generationKey", widget)
        self.assertIn("generation !== globalThis[generationKey]", widget)
        self.assertIn("clearTimeout(", widget)
        self.assertNotIn("payload ? { payload } : state", widget)
        # One immutable snapshot-apply helper feeds the combined dock app, and
        # both the initial read and the refresh timer go through it; each
        # applied snapshot stamps receivedAt so running rows can tick elapsed
        # live.
        self.assertEqual(
            widget.count("{ ...state, payload, receivedAt: Date.now(), tick: state.tick + 1 }"), 1
        )
        self.assertEqual(widget.count("applySnapshot(payload)"), 2)
        self.assertNotIn("friendlyWorkflow", widget)
        self.assertNotIn("'fanout-unit': 'Parallel work'", widget)
        self.assertIn("t.color.ok", widget)
        self.assertIn("t.color.error", widget)
        self.assertIn("t.color.warn", widget)
        self.assertNotIn("t.color.warning", widget)
        self.assertNotIn("spawnSync(", widget)
        self.assertNotIn("setInterval(", widget)
        for forbidden in ("payload.cwd", "payload.branch", "payload.context", "payload.cost"):
            self.assertNotIn(forbidden, widget)


class BrandedTuiSectionsConsentTests(unittest.TestCase):
    """#1700: `display.sections` rides the same consent as the other two keys.

    Consent-only, so `--yes` writes it and a plain non-interactive setup does
    not. That asymmetry with `display.interface` is deliberate: a fresh
    install that lands in the classic REPL cannot show the HUD at all, while
    collapsing somebody's transcript is a change they should be told about.
    """

    def _setup(self, config_text: str, *extra: str) -> tuple[Path, dict]:
        root = Path(self.enterContext(TemporaryDirectory()))
        hermes_home = root / ".hermes"
        config = hermes_home / "config.yaml"
        config.parent.mkdir(parents=True)
        config.write_text(config_text, encoding="utf-8")
        status, stdout, stderr = run_cli(
            [
                "--omh-home", str(root / ".omh"),
                "--hermes-home", str(hermes_home),
                "setup", "--json", *extra,
            ],
            output_json=False,
        )
        self.assertEqual((status, stderr), (0, ""))
        return config, json.loads(stdout)["steps"]["apply"]

    def test_yes_collapses_all_three_sections_on_a_fresh_canonical_config(self) -> None:
        config, apply = self._setup("display:\n  compact: true\n", "--yes")
        config_text = config.read_text(encoding="utf-8")
        for key in ("thinking", "tools", "subagents"):
            self.assertIn(f"    {key}: collapsed\n", config_text)
        self.assertIn("  compact: true", config_text)
        self.assertTrue(apply["display_sections"]["changed"])
        self.assertEqual(
            apply["display_sections"]["selected"],
            {"thinking": "collapsed", "tools": "collapsed", "subagents": "collapsed"},
        )
        self.assertEqual(apply["display_sections"]["written"], ["subagents", "thinking", "tools"])

    def test_yes_preserves_an_explicit_section_value_and_records_only_what_it_wrote(self) -> None:
        config, apply = self._setup(
            "display:\n  sections:\n    tools: expanded\n", "--yes"
        )
        config_text = config.read_text(encoding="utf-8")
        self.assertIn("    tools: expanded\n", config_text)
        self.assertIn("    thinking: collapsed\n", config_text)
        # `written` is what uninstall may reverse, so the preserved key is
        # absent from it even though the writer was asked for all three.
        self.assertEqual(apply["display_sections"]["written"], ["subagents", "thinking"])

    def test_declining_leaves_the_display_block_byte_identical(self) -> None:
        # Setup still registers the skills dir, the plugin and the memory
        # provider, so the file as a whole changes. What a declined prompt
        # must not touch is the display block, to the byte.
        original = "display:\n  interface: cli\n  skin: default\n"
        config, apply = self._setup(original, "--no-omh-tui")
        self.assertTrue(config.read_text(encoding="utf-8").startswith(original))
        self.assertNotIn("sections:", config.read_text(encoding="utf-8"))
        self.assertFalse(apply["display_sections"]["changed"])
        self.assertIn("declined", apply["display_sections"]["message"])
        self.assertEqual(apply["display_sections"]["written"], [])

    def test_a_dry_run_never_persists_the_sections(self) -> None:
        original = "display:\n  compact: true\n"
        config, apply = self._setup(original, "--yes", "--dry-run")
        self.assertEqual(config.read_text(encoding="utf-8"), original)
        self.assertNotIn("sections:", config.read_text(encoding="utf-8"))
        self.assertTrue(apply["dry_run"])
        self.assertTrue(apply["display_sections"]["changed"])

    def test_without_consent_the_sections_are_not_written(self) -> None:
        original = "display:\n  compact: true\n"
        config, apply = self._setup(original)
        config_text = config.read_text(encoding="utf-8")
        self.assertIn("  interface: tui\n", config_text)
        self.assertNotIn("sections:", config_text)
        self.assertFalse(apply["display_sections"]["changed"])
        self.assertIn("--yes", apply["display_sections"]["message"])

    def test_an_install_missing_only_the_sections_is_not_re_prompted(self) -> None:
        # A decision, pinned by behaviour. `display.sections` joined the
        # bundle this prompt consents to, but the prompt's trigger stays the
        # two keys it always was. Widening it to "is the bundle complete"
        # would be satisfied by nothing OMH writes on its own -- a plain
        # non-interactive setup writes interface and skin and never the
        # sections -- so every later interactive run would ask again about a
        # state OMH itself created. `--yes` is how this install takes the
        # third key.
        root = Path(self.enterContext(TemporaryDirectory()))
        hermes_home = root / ".hermes"
        config = hermes_home / "config.yaml"
        config.parent.mkdir(parents=True)
        config.write_text("display:\n  interface: tui\n  skin: omh\n", encoding="utf-8")
        base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(hermes_home)]

        status, _stdout, stderr = run_cli(base + ["setup", "--json"], output_json=False)
        self.assertEqual((status, stderr), (0, ""))
        with patch("omh.commands.setup._ask_yes_no") as yes_no:
            status, _stdout, stderr = run_cli(base + ["update", "--interactive"], output_json=False)
        self.assertEqual(status, 0, stderr)
        yes_no.assert_not_called()
        self.assertNotIn("sections:", config.read_text(encoding="utf-8"))

    def test_a_noncanonical_shape_is_preserved_even_under_yes(self) -> None:
        original = "display:\n  sections: {tools: expanded}\n"
        config, apply = self._setup(original, "--yes")
        self.assertIn("  sections: {tools: expanded}\n", config.read_text(encoding="utf-8"))
        self.assertFalse(apply["display_sections"]["changed"])
        self.assertIn("non-block", apply["display_sections"]["message"])



@unittest.skipUnless(NODE, "node is not installed; the widget harness needs it")
class TodoPanelWaitingRowTests(unittest.TestCase):
    """The plan panel's half of #1553: an item says it is waiting and on what.

    Driven end to end rather than pinned as a string: the plan goes through
    the store, the payload comes from `read_omh_hud`, and the installed-form
    widget renders it under node. What the assertions read is the row a person
    would see, so a clause that exists in the source but never reaches a row
    does not pass.
    """

    def _rows(self, items: list[dict], *, cols: int = 120, edit=None) -> list[dict]:
        """Render one frame and return its rows; the payload lands on `self`.

        `last_payload` is what the widget was handed, so a test can read the
        record beside the row it produced without a second reader call.
        """
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / "omh"
            hermes_home = root / "hermes"
            omh_home.mkdir()
            hermes_home.mkdir()
            write_todo(omh_home, build_todo_record("init", items, source="test"))
            payload = read_omh_hud(omh_home, hermes_home)
            if edit is not None:
                edit(payload)
            self.last_payload = payload
            payload_file = root / "payload.json"
            payload_file.write_text(json.dumps(payload), encoding="utf-8")
            widget = root / "omh-status.mjs"
            widget.write_bytes(widget_payload(Path(sys.executable)))
            harness = root / "todo-harness.mjs"
            harness.write_text(TODO_PANEL_HARNESS, encoding="utf-8")
            completed = subprocess.run(
                [NODE, str(harness), str(widget), str(payload_file), str(cols)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=120,
                env={**os.environ, "HERMES_HOME": str(hermes_home), "HOME": str(root)},
                cwd=str(root),
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads(completed.stdout.strip().splitlines()[-1])
            self.assertNotIn("error", result, result)
            return result["rows"]

    def _waiting_row(self, rows: list[dict]) -> dict:
        """The one row carrying a waiting clause, named so its absence reads."""
        waiting = [row for row in rows if "(waiting:" in row["text"]]
        self.assertEqual(len(waiting), 1, [row["text"] for row in rows])
        return waiting[0]

    def test_a_waiting_item_says_so_on_its_own_row(self) -> None:
        rows = self._rows(
            [
                {"text": "Land the fix", "state": "done"},
                {"text": "Open the PR", "state": "active", "blocked_reason": "owner approval"},
                {"text": "Announce", "state": "pending"},
            ]
        )

        texts = [row["text"] for row in rows]
        self.assertIn("[•] Open the PR (waiting: owner approval)", texts)
        # The clause carries the warn tone the widget already uses for "this
        # is not what it looks like at a glance"; the rest of the row keeps
        # the colour its state earns.
        self.assertIn(
            {"color": "warn", "text": " (waiting: owner approval)"},
            self._waiting_row(rows)["parts"],
        )
        # Rows with nothing recorded say nothing new.
        self.assertIn("[ ] Announce", texts)
        self.assertNotIn("waiting", " ".join(text for text in texts if "Announce" in text))

    def test_the_reason_renders_on_a_row_that_is_not_the_active_one(self) -> None:
        rows = self._rows(
            [
                {"text": "Ship it", "state": "active"},
                {"text": "Cut the release", "state": "pending", "blocked_reason": "SRE window"},
            ]
        )

        self.assertIn(
            "[ ] Cut the release (waiting: SRE window)",
            [row["text"] for row in rows],
        )

    def test_the_reason_reads_ahead_of_the_unchanged_hint_on_one_row(self) -> None:
        # Where a row carries both, the recorded reason is what explains the
        # age, so it reads first. The stall verdict belongs to the reader
        # (`_todo_stall`), which this is not testing: the payload is edited to
        # the shape it reports past the threshold with nothing open, and the
        # panel is what the assertion reads.
        def stalled(payload: dict) -> None:
            payload["activity"] = {
                **payload["activity"],
                "post_tool_call_observed": True,
                "live": False,
            }
            payload["todo"]["stall"] = {**payload["todo"]["stall"], "status": "unchanged"}
            payload["todo"]["updated_age_seconds"] = 900

        rows = self._rows(
            [{"text": "Cut over", "state": "active", "blocked_reason": "SRE window"}],
            edit=stalled,
        )

        self.assertIn(
            "[•] Cut over (waiting: SRE window) (unchanged 15m 0s)",
            [row["text"] for row in rows],
        )

    def test_a_long_reason_is_cut_on_the_row_and_left_whole_in_the_payload(self) -> None:
        # Truncation is a render concern on both surfaces. The widget cuts in
        # terminal cells, so the ceiling it shares with the text HUD line is
        # the row's, never the record's -- `blocked_reason` reaches the widget
        # whole and the stop criterion reads it whole.
        reason = "waiting on the owner to approve the migration plan before the cutover window opens"
        self.assertGreater(len(reason), TODO_BLOCKED_REASON_DISPLAY_CHARS)

        rows = self._rows([{"text": "Cut over", "state": "active", "blocked_reason": reason}])

        waiting = self._waiting_row(rows)
        clause = next(part["text"] for part in waiting["parts"] if part["text"].startswith(" (waiting:"))
        shown = clause[len(" (waiting: ") : -len(")")]
        self.assertTrue(shown.endswith("…"), clause)
        self.assertEqual(len(shown), TODO_BLOCKED_REASON_DISPLAY_CHARS)
        self.assertTrue(reason.startswith(shown[:-1]), clause)
        self.assertLess(len(shown), len(reason))
        self.assertEqual(self.last_payload["todo"]["items"][0]["blocked_reason"], reason)

    def test_a_narrow_terminal_keeps_both_the_item_text_and_the_waiting_clause(self) -> None:
        # The reason takes a bounded share of the row and the item text gives
        # back exactly that much. Without the give-back a long text fills the
        # row and `truncate-end` drops the clause -- which is the display the
        # field exists to fix, on precisely the items that most often carry one.
        rows = self._rows(
            [
                {
                    "text": "Verify the retry path end to end across every shard and record what each one observed",
                    "state": "active",
                    "blocked_reason": "the staging cluster is down until the maintenance window closes",
                }
            ],
            cols=80,
        )

        waiting = self._waiting_row(rows)
        self.assertIn("Verify the retry path", waiting["text"])
        self.assertLessEqual(len(waiting["text"]), 80)


@unittest.skipUnless(NODE, "node is not installed; the widget harness needs it")
class TodoPanelViewportBudgetTests(unittest.TestCase):
    """#1727: the dock caps ITEMS, so its ROWS were free of the terminal.

    Eight items with eight phases is twenty rows, and before this the panel
    drew all twenty on a terminal of any height -- above the composer, where
    the owner's own prompt was what got pushed off. Every case here reads the
    rendered frame rather than the source, because the defect was never in
    what the code said, only in how tall the result came out.
    """

    #: What the panel is allowed to draw, restated from the renderer so a
    #: change to the split fails here with the arithmetic in view rather than
    #: quietly rescoring every case: a third of the terminal, shared with the
    #: transcript and with the bottom dock plus composer.
    @staticmethod
    def budget(viewport_rows: int) -> int:
        return max(1, viewport_rows // 3)

    def _rows(
        self, items: list[dict], *, viewport_rows: int, cols: int = 120, title: str = "Plan"
    ) -> list[str]:
        """Render one frame at ``viewport_rows`` and return its row texts."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / "omh"
            hermes_home = root / "hermes"
            omh_home.mkdir()
            hermes_home.mkdir()
            write_todo(omh_home, build_todo_record(title, items, source="test"))
            payload = read_omh_hud(omh_home, hermes_home)
            self.assertEqual(payload["todo"]["status"], "established", payload["todo"])
            payload_file = root / "payload.json"
            payload_file.write_text(json.dumps(payload), encoding="utf-8")
            widget = root / "omh-status.mjs"
            widget.write_bytes(widget_payload(Path(sys.executable)))
            harness = root / "todo-harness.mjs"
            harness.write_text(TODO_PANEL_HARNESS, encoding="utf-8")
            completed = subprocess.run(
                [NODE, str(harness), str(widget), str(payload_file), str(cols), str(viewport_rows)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=120,
                env={**os.environ, "HERMES_HOME": str(hermes_home), "HOME": str(root)},
                cwd=str(root),
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads(completed.stdout.strip().splitlines()[-1])
            self.assertNotIn("error", result, result)
            return [row["text"] for row in result["rows"]]

    @staticmethod
    def phased_plan(count: int, *, phases: int, active: int) -> list[dict]:
        """``count`` items spread over ``phases`` phases, one of them active."""
        return [
            {
                "text": f"Task number {index}",
                "state": "active"
                if index == active
                else "done"
                if index < active
                else "pending",
                "phase": f"Phase {min(index, phases - 1)}",
            }
            for index in range(count)
        ]

    @staticmethod
    def folded(rows: list[str]) -> tuple[int, int]:
        """The earlier and later fold counts the frame states, 0 when absent."""
        earlier = later = 0
        for row in rows:
            if row.startswith("... (") and row.endswith("earlier tasks)"):
                earlier = int(row.split("(")[1].split(" ")[0])
            elif row.startswith("... (") and row.endswith("later tasks)"):
                later = int(row.split("(")[1].split(" ")[0])
            elif row.startswith("... (") and row.endswith("earlier task)"):
                earlier = 1
            elif row.startswith("... (") and row.endswith("later task)"):
                later = 1
        return earlier, later

    @staticmethod
    def item_rows(rows: list[str]) -> list[str]:
        """Only the checklist rows -- markers are what makes an item an item."""
        return [row for row in rows if any(mark in row for mark in ("[•]", "[✓]", "[ ]"))]

    def test_a_ten_item_eight_phase_plan_fits_its_share_at_every_height(self) -> None:
        # The acceptance case from the issue, read at three heights. What the
        # assertion protects is a relation, not three numbers: the frame is
        # within the dock's share of the terminal, the active item is on it,
        # and the folds account for every item the window left out -- so a
        # future window rule cannot pass by hiding rows silently.
        items = self.phased_plan(10, phases=8, active=3)
        for viewport_rows in (24, 40, 60):
            with self.subTest(viewport_rows=viewport_rows):
                rows = self._rows(items, viewport_rows=viewport_rows)
                self.assertLessEqual(len(rows), self.budget(viewport_rows), rows)
                self.assertTrue([row for row in rows if "[•]" in row], rows)
                self.assertIn("Task number 3", "\n".join(rows))
                earlier, later = self.folded(rows)
                self.assertEqual(earlier + len(self.item_rows(rows)) + later, 10, rows)

    def test_the_short_terminal_is_the_one_that_used_to_lose_the_prompt(self) -> None:
        # Before the clamp this exact plan drew seventeen rows here, on a
        # terminal of twenty-four. The pair is the whole finding, so both
        # halves are measured in one test rather than trusted from a comment.
        items = self.phased_plan(10, phases=8, active=3)
        self.assertEqual(len(self._rows(items, viewport_rows=24)), 8)
        self.assertEqual(len(self._rows(items, viewport_rows=60)), 17)

    def test_a_roomy_terminal_still_draws_the_tallest_frame_this_panel_has(self) -> None:
        # Twenty rows is the ceiling the renderer can reach: header, earlier
        # fold, eight phase headers, eight items, later fold, rule. Sixty is
        # where a third of the terminal first covers it, which is why the
        # split is a third -- above that height nothing is clamped at all.
        items = self.phased_plan(14, phases=14, active=3)
        self.assertEqual(len(self._rows(items, viewport_rows=60)), 20)
        self.assertEqual(len(self._rows(items, viewport_rows=90)), 20)

    def test_a_terminal_too_short_for_a_checklist_gets_the_summary_line(self) -> None:
        # One item, the phase header it needs and the two folds that account
        # for the rest do not fit in a twelve-row terminal's share. The panel
        # falls back to the form it already has for a finished plan instead of
        # drawing a checklist that drops rows without saying so: the header
        # line, which still carries done/total and the phase count, over the
        # composer-frame rule.
        rows = self._rows(self.phased_plan(10, phases=8, active=3), viewport_rows=12)

        self.assertEqual(len(rows), 2, rows)
        self.assertIn("3/10", rows[0])
        self.assertIn("8 phases", rows[0])
        self.assertEqual(self.item_rows(rows), [])

    def test_one_phase_spends_one_header_row_and_keeps_more_items(self) -> None:
        # The budget is spent on what the plan actually costs: with a single
        # phase there is one header instead of eight, so the same height shows
        # strictly more of the checklist than the eight-phase plan did.
        one_phase = self._rows(self.phased_plan(10, phases=1, active=3), viewport_rows=24)
        eight_phase = self._rows(self.phased_plan(10, phases=8, active=3), viewport_rows=24)

        self.assertLessEqual(len(one_phase), self.budget(24), one_phase)
        self.assertGreater(len(self.item_rows(one_phase)), len(self.item_rows(eight_phase)))
        self.assertEqual(len([row for row in one_phase if row.startswith("Phase ")]), 1, one_phase)

    def test_the_active_item_survives_the_shrink_at_either_end_of_the_window(self) -> None:
        # The window shrinks from whichever side is farther from the active
        # item, so an active row at the front and one at the back both stay on
        # the frame. A shrink that always took from one end would drop one of
        # these two and pass the other.
        for active in (0, 9):
            with self.subTest(active=active):
                rows = self._rows(
                    self.phased_plan(10, phases=8, active=active), viewport_rows=24
                )
                self.assertLessEqual(len(rows), self.budget(24), rows)
                marked = [row for row in rows if "[•]" in row]
                self.assertEqual(len(marked), 1, rows)
                self.assertIn(f"Task number {active}", marked[0])


@unittest.skipUnless(NODE, "node is required to render the status dock")
class StatusDockRepeatChipTests(unittest.TestCase):
    """`repeat xN` as the dock-bottom header actually renders it.

    #1687 asks for the row in both surfaces, and a source-string assertion
    cannot answer the two questions that matter here: what a person sees
    at each stage, and whether the chip survives a narrow terminal. The
    header is one `Text` with `wrap: 'truncate-end'` and no drop loop, so
    a segment's PLACE in the line is its priority.
    """

    def _payload(self, *, calls, result="out", session="session-dock", args=None):
        from omh.plugin_bundle.omh.hooks.nudge_budget import reset_nudge_budget
        from omh.plugin_bundle.omh.hooks.session_attendance import reset_session_attendance
        from omh.plugin_bundle.omh.hooks.tool_hooks import post_tool_call, pre_tool_call

        reset_session_attendance()
        reset_nudge_budget()
        self.addCleanup(reset_session_attendance)
        self.addCleanup(reset_nudge_budget)
        root = Path(self._tmp.name)
        omh_home = root / "omh"
        hermes_home = root / "hermes"
        (omh_home / "runtime").mkdir(parents=True, exist_ok=True)
        hermes_home.mkdir(exist_ok=True)
        for index in range(calls):
            payload_args = args(index) if callable(args) else {"pattern": "def render_skill", "path": "src"}
            directive = pre_tool_call(
                tool_name="search_files",
                tool_input=payload_args,
                session_id=session,
                omh_home=str(omh_home),
                tool_call_id=f"call-{index}",
            )
            blocked = directive is not None and directive.get("action") == "block"
            post_tool_call(
                tool_name="search_files",
                args=payload_args,
                result=str(directive.get("message")) if blocked else result,
                status="blocked" if blocked else "ok",
                session_id=session,
                omh_home=str(omh_home),
                tool_call_id=f"call-{index}",
            )
        return read_omh_hud(
            omh_home,
            hermes_home,
            status={"runs": [], "active_executors": []},
            session_ref=session,
        )

    def _header(self, payload: dict, *, cols: int) -> dict:
        root = Path(self._tmp.name)
        payload_file = root / f"payload-{cols}.json"
        payload_file.write_text(json.dumps(payload), encoding="utf-8")
        widget = root / "omh-status.mjs"
        widget.write_bytes(widget_payload(Path(sys.executable)))
        harness = root / "status-harness.mjs"
        harness.write_text(STATUS_DOCK_HARNESS, encoding="utf-8")
        completed = subprocess.run(
            [NODE, str(harness), str(widget), str(payload_file), str(cols)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
            env={**os.environ, "HERMES_HOME": str(root / "hermes"), "HOME": str(root)},
            cwd=str(root),
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout.strip().splitlines()[-1])
        self.assertNotIn("error", result, result)
        rows = [row for row in result["rows"] if "[OMH]" in row["text"]]
        self.assertEqual(len(rows), 1, [row["text"] for row in result["rows"]])
        return rows[0]

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def _chip(self, header: dict) -> dict:
        chips = [part for part in header["parts"] if part["text"].startswith("repeat x")]
        self.assertEqual(len(chips), 1, header["text"])
        return chips[0]

    def test_a_watched_repeat_is_counted_in_the_muted_tone(self) -> None:
        header = self._header(self._payload(calls=6), cols=120)

        chip = self._chip(header)
        self.assertEqual(chip["text"], "repeat x6")
        # Muted: the guard has noticed and has not acted, which is
        # information rather than a fault.
        self.assertEqual(chip["color"], "muted")

    def test_a_refused_repeat_warns_and_an_escalated_one_is_an_error(self) -> None:
        from omh.plugin_bundle.omh.tool_bursts import (
            REPEAT_CALL_BLOCK_THRESHOLD,
            REPEAT_CALL_ESCALATION_ATTEMPTS,
        )

        blocked = self._chip(
            self._header(self._payload(calls=REPEAT_CALL_BLOCK_THRESHOLD + 1), cols=120)
        )
        self.assertEqual(blocked["text"], f"repeat x{REPEAT_CALL_BLOCK_THRESHOLD + 1} blocked")
        self.assertEqual(blocked["color"], "warn")

        self.setUp()
        total = REPEAT_CALL_BLOCK_THRESHOLD + REPEAT_CALL_ESCALATION_ATTEMPTS
        escalated = self._chip(self._header(self._payload(calls=total), cols=120))
        self.assertEqual(escalated["text"], f"repeat x{total} approval")
        self.assertEqual(escalated["color"], "error")

    def test_different_calls_put_no_chip_on_the_header(self) -> None:
        payload = self._payload(
            calls=6, args=lambda index: {"pattern": f"p{index}", "path": "src"}
        )

        header = self._header(payload, cols=120)

        self.assertEqual(payload["repeat"]["status"], "idle")
        self.assertNotIn("repeat x", header["text"])

    def test_the_chip_outranks_every_droppable_segment_at_both_widths(self) -> None:
        """The width policy, stated as an ordering rather than a budget.

        The header truncates from the END and never drops a segment out of
        the middle, so the only way to keep a loop visible on a narrow
        terminal is to put it ahead of what may be lost. At 60 columns the
        tokens segment is already gated out by the widget's own 100-column
        rule; the chip is there at both widths and ahead of the cost, the
        board tally and the liveness segment at each.
        """
        payload = self._payload(calls=6)
        # The header's cost and token figures are summed from agent rows, so
        # the crowded line this is about needs one.
        payload["subagents"]["rows"] = [
            {"task_id": "t", "scope": "global", "state": "done", "tokens": 184_800, "cost_usd": 1.25}
        ]

        wide = self._header(payload, cols=120)
        narrow = self._header(payload, cols=60)

        for label, header in (("wide", wide), ("narrow", narrow)):
            with self.subTest(width=label):
                text = header["text"]
                self.assertIn("repeat x6", text)
                index = text.index("repeat x6")
                for later in ("$1.250", "tokens", "yolo mode"):
                    if later in text:
                        self.assertLess(index, text.index(later), text)
        # The segment the line is allowed to lose is the one the widget
        # already drops below 100 columns, and it is not the chip.
        self.assertIn("184.8k tokens", wide["text"])
        self.assertNotIn("tokens", narrow["text"])
        self.assertIn("repeat x6", narrow["text"])


if __name__ == "__main__":
    unittest.main()
