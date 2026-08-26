from __future__ import annotations

import json
from importlib import resources
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _cli_harness import run_cli
from omh.tui_widget_pack import TuiWidgetInstallError, install_tui_widget, widget_payload


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
        self.assertIn("['-I', '-c', READER]", payload)
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

    def test_widget_frames_the_composer_and_docks_the_plan_on_top(self) -> None:
        # Changed on purpose (this used to pin a single dock-bottom app and
        # forbid dock-top). The single bottom dock framed the OMH section
        # instead of the chat input ('채팅창에 선 두개가 있어야지 왜 tui에
        # 있어') and sank the plan the owner always read above the input
        # ('투두가 왜 하단에 떠 기존에는 상단에 잘 떴었는데'). The layout is
        # now: plan todo in dock-top, closed by the FrameRule directly above
        # the input; the bottom dock opens with the rule below the input and
        # carries status and activity rows with no closing rule.
        widget = resources.files("omh.tui_widgets").joinpath("omh-status.mjs").read_text(encoding="utf-8")

        self.assertEqual(widget.count("defineWidgetApp({"), 2)
        self.assertEqual(widget.count("zone: 'dock-bottom'"), 1)
        self.assertEqual(widget.count("zone: 'dock-top'"), 1)
        self.assertIn("id: 'omh-todo'", widget)
        self.assertIn("id: 'omh-status'", widget)
        # The todo panel renders only in the top dock, and every branch of it
        # (no plan, all done, established) closes with the frame rule so the
        # composer frame never blinks with the plan lifecycle.
        self.assertEqual(widget.count("h(TodoPanel"), 1)
        self.assertEqual(widget.count("h(FrameRule, { columns, payload, t })"), 3)
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

    def test_widget_is_bottom_docked_and_omits_host_status_fields(self) -> None:
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
        # Exactly two plain-rule renders remain (the dock-bottom opener and
        # the frame app's idle fallback): the closing rules that used to
        # follow the plan panel framed the OMH section instead of the input
        # and were removed on owner direction.
        self.assertIn("const Rule = ", widget)
        self.assertNotIn("Gap", widget)
        self.assertEqual(widget.count("h(Rule, { columns, t })"), 2)
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
        # per-call cost) render with a `~`; true zeros render nothing.
        self.assertIn("row.cost_approximate ? '~' : ''", widget)
        self.assertIn("cost > 0 ? `${approximate ? '~' : ''}$${cost.toFixed(3)}` : ''", widget)
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
        self.assertIn("hasActive ? h(PlanPulse, { t }) : null", widget)
        self.assertNotIn("Number.MAX_SAFE_INTEGER", widget)
        # Changed on purpose: the parallel-shot badge moved off the bottom
        # status line onto the dock-top frame rule — the transcript's
        # "Tool calls (N)" group is host-owned rendering OMH cannot decorate,
        # and the rule directly under the newest transcript lines is the
        # closest OMH-owned surface ('tool calling 옆에서 떠야지 하단에
        # 뜨면 의미가없지'). The bottom dock renders no parallel-shot text.
        self.assertIn("parallel shot ×", widget)
        self.assertIn("payload.parallel_shot", widget)
        # Shift+Tab yolo state, as last hook-observed: ON warns in the
        # theme's yellow, OFF rests in the label blue, and an unobserved or
        # stale ledger renders nothing rather than a guessed "off".
        self.assertIn("' • yolo mode: '", widget)
        self.assertIn("payload.yolo && payload.yolo.status === 'observed'", widget)
        self.assertIn("payload.yolo.enabled ? t.color.warn : t.color.label", widget)
        self.assertNotIn("• parallel shot", widget)
        self.assertIn("shot.status !== 'observed'", widget)
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
        self.assertIn("tools", widget)
        self.assertIn("tok/s", widget)
        self.assertIn("cache_hit_percentage", widget)
        self.assertIn("context_percentage", widget)
        # Only observed cache/ctx values render on rows: "uncollected" was a
        # permanent label for hermes-native children (the host never records
        # a child's context percentage) and read as a fixable problem.
        self.assertNotIn("uncollected", widget)
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


if __name__ == "__main__":
    unittest.main()
