from __future__ import annotations

import os
import platform
import plistlib
import shutil
import subprocess
from pathlib import Path
from typing import Any

from ..command_path import inspect_omh_command_path
from ..local_store import atomic_write_text
from ..paths import OmhPaths
from ..runtime.artifacts import update_state


MENUBAR_APP_SCHEMA_VERSION = "menubar_app/v1"
MENUBAR_LABEL = "com.rlaope.omh.menubar"
DEFAULT_REFRESH_INTERVAL_SECONDS = 8


def setup_menubar_app(
    paths: OmhPaths,
    *,
    dry_run: bool = False,
    start: bool = True,
    force: bool = False,
    command_path: str | None = None,
    platform_name: str | None = None,
) -> dict[str, Any]:
    system = platform_name or platform.system()
    app_paths = menubar_app_paths(paths)
    base_payload: dict[str, Any] = {
        "schema_version": MENUBAR_APP_SCHEMA_VERSION,
        "status": "skipped",
        "supported": False,
        "platform": system,
        "dry_run": bool(dry_run),
        "started": False,
        "installed": False,
        "label": MENUBAR_LABEL,
        **{key: str(value) for key, value in app_paths.items()},
    }
    if system != "Darwin":
        return {**base_payload, "reason": "macOS menu bar helper is only supported on Darwin."}

    swiftc = shutil.which("swiftc")
    if not swiftc:
        return {**base_payload, "reason": "swiftc is not available, so the native menu bar helper cannot be built."}

    resolved_command = command_path or _resolved_omh_command()
    if not resolved_command:
        return {**base_payload, "reason": "`omh` command path is not available yet; rerun setup after the command is on PATH."}

    payload = {
        **base_payload,
        "supported": True,
        "status": "dry_run" if dry_run else "installed",
        "reason": "",
        "swiftc": swiftc,
        "omh_command": resolved_command,
    }
    if dry_run:
        return payload

    app_paths["app_dir"].mkdir(parents=True, exist_ok=True)
    atomic_write_text(app_paths["source"], _SWIFT_SOURCE)
    _compile_swift_helper(swiftc, app_paths["source"], app_paths["executable"])
    _write_launch_agent(app_paths["launch_agent"], app_paths["executable"], resolved_command, paths)
    payload["installed"] = True

    if start:
        start_result = start_menubar_app(paths, platform_name=system)
        payload["started"] = bool(start_result.get("started", False))
        payload["start_status"] = start_result.get("status", "unknown")
        payload["start_message"] = start_result.get("message", "")
        if payload["started"]:
            payload["status"] = "running"
        else:
            payload["status"] = "installed_start_failed"
    update_state(paths, {"last_menubar_app": payload})
    return payload


def start_menubar_app(paths: OmhPaths, *, platform_name: str | None = None) -> dict[str, Any]:
    system = platform_name or platform.system()
    app_paths = menubar_app_paths(paths)
    payload = {
        "schema_version": MENUBAR_APP_SCHEMA_VERSION,
        "operation": "start",
        "platform": system,
        "label": MENUBAR_LABEL,
        "launch_agent": str(app_paths["launch_agent"]),
        "started": False,
    }
    if system != "Darwin":
        return {**payload, "status": "skipped", "message": "macOS menu bar helper is only supported on Darwin."}
    if not app_paths["launch_agent"].exists():
        return {**payload, "status": "missing", "message": "LaunchAgent is not installed; run `omh menubar install`."}

    domain = f"gui/{os.getuid()}"
    _run_launchctl(["bootout", domain, str(app_paths["launch_agent"])], check=False)
    bootstrap = _run_launchctl(["bootstrap", domain, str(app_paths["launch_agent"])], check=False)
    if bootstrap.returncode != 0 and "already bootstrapped" not in bootstrap.stderr:
        return {
            **payload,
            "status": "failed",
            "message": (bootstrap.stderr or bootstrap.stdout or "launchctl bootstrap failed").strip(),
        }
    kickstart = _run_launchctl(["kickstart", "-k", f"{domain}/{MENUBAR_LABEL}"], check=False)
    if kickstart.returncode != 0:
        return {
            **payload,
            "status": "failed",
            "message": (kickstart.stderr or kickstart.stdout or "launchctl kickstart failed").strip(),
        }
    return {**payload, "status": "running", "started": True, "message": "OMH menu bar helper started."}


def stop_menubar_app(paths: OmhPaths, *, platform_name: str | None = None) -> dict[str, Any]:
    system = platform_name or platform.system()
    app_paths = menubar_app_paths(paths)
    payload = {
        "schema_version": MENUBAR_APP_SCHEMA_VERSION,
        "operation": "stop",
        "platform": system,
        "label": MENUBAR_LABEL,
        "launch_agent": str(app_paths["launch_agent"]),
        "stopped": False,
    }
    if system != "Darwin":
        return {**payload, "status": "skipped", "message": "macOS menu bar helper is only supported on Darwin."}
    domain = f"gui/{os.getuid()}"
    result = _run_launchctl(["bootout", domain, str(app_paths["launch_agent"])], check=False)
    if result.returncode != 0 and "No such process" not in result.stderr and "No such file" not in result.stderr:
        return {**payload, "status": "failed", "message": (result.stderr or result.stdout).strip()}
    return {**payload, "status": "stopped", "stopped": True, "message": "OMH menu bar helper stopped."}


def uninstall_menubar_app(paths: OmhPaths, *, dry_run: bool = False, platform_name: str | None = None) -> dict[str, Any]:
    system = platform_name or platform.system()
    app_paths = menubar_app_paths(paths)
    candidates = [app_paths["launch_agent"], app_paths["app_dir"]]
    existing = [path for path in candidates if path.exists()]
    payload = {
        "schema_version": MENUBAR_APP_SCHEMA_VERSION,
        "operation": "uninstall",
        "platform": system,
        "label": MENUBAR_LABEL,
        "dry_run": bool(dry_run),
        "removed": [],
        "would_remove": [str(path) for path in existing] if dry_run else [],
    }
    if dry_run:
        return {**payload, "status": "dry_run"}

    stop_result = stop_menubar_app(paths, platform_name=system)
    removed: list[str] = []
    for path in existing:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        removed.append(str(path))
    payload["removed"] = removed
    payload["stop_status"] = stop_result.get("status", "unknown")
    payload["status"] = "removed" if removed else "absent"
    update_state(paths, {"last_menubar_app": payload})
    return payload


def menubar_app_paths(paths: OmhPaths) -> dict[str, Path]:
    app_dir = paths.omh_home / "menubar"
    return {
        "app_dir": app_dir,
        "source": app_dir / "OMHMenuBar.swift",
        "executable": app_dir / "omh-menubar",
        "launch_agent": Path.home() / "Library" / "LaunchAgents" / f"{MENUBAR_LABEL}.plist",
    }


def _resolved_omh_command() -> str:
    command = inspect_omh_command_path()
    if command.get("found") and command.get("path"):
        return str(command["path"])
    which = shutil.which("omh")
    return which or ""


def _compile_swift_helper(swiftc: str, source: Path, executable: Path) -> None:
    result = subprocess.run(
        [swiftc, "-framework", "AppKit", str(source), "-o", str(executable)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "swiftc failed").strip())


def _write_launch_agent(plist_path: Path, executable: Path, omh_command: str, paths: OmhPaths) -> None:
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "Label": MENUBAR_LABEL,
        "ProgramArguments": [
            str(executable),
            "--omh-command",
            omh_command,
            "--omh-home",
            str(paths.omh_home),
            "--hermes-home",
            str(paths.hermes_home),
            "--interval",
            str(DEFAULT_REFRESH_INTERVAL_SECONDS),
        ],
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(paths.runtime_dir / "menubar.out.log"),
        "StandardErrorPath": str(paths.runtime_dir / "menubar.err.log"),
    }
    paths.runtime_dir.mkdir(parents=True, exist_ok=True)
    plist_path.write_bytes(plistlib.dumps(payload))


def _run_launchctl(args: list[str], *, check: bool) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["launchctl", *args], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=check)


_SWIFT_SOURCE = r'''
import AppKit
import Foundation

final class OMHMenuBarDelegate: NSObject, NSApplicationDelegate {
    private let statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
    private var timer: Timer?
    private var omhCommand = "omh"
    private var omhHome = ""
    private var hermesHome = ""
    private var interval: TimeInterval = 8

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        parseArguments()
        configureMenu(headline: "OMH", summary: "Loading status", cards: [])
        refresh()
        timer = Timer.scheduledTimer(withTimeInterval: interval, repeats: true) { [weak self] _ in
            self?.refresh()
        }
    }

    private func parseArguments() {
        let args = CommandLine.arguments
        var index = 1
        while index < args.count {
            let key = args[index]
            let value = index + 1 < args.count ? args[index + 1] : ""
            switch key {
            case "--omh-command":
                omhCommand = value
                index += 2
            case "--omh-home":
                omhHome = value
                index += 2
            case "--hermes-home":
                hermesHome = value
                index += 2
            case "--interval":
                interval = TimeInterval(value) ?? 8
                index += 2
            default:
                index += 1
            }
        }
    }

    @objc private func refreshClicked(_ sender: Any?) {
        refresh()
    }

    @objc private func quitClicked(_ sender: Any?) {
        NSApp.terminate(nil)
    }

    private func refresh() {
        guard let payload = readStatusPayload() else {
            statusItem.button?.title = "omh !"
            configureMenu(
                headline: "OMH needs attention",
                summary: "Status unavailable",
                cards: [
                    [
                        "title": "Recovery",
                        "rows": [
                            ["label": "Next", "value": "Run omh doctor"],
                            ["label": "Then", "value": "Run omh setup if registration needs repair"]
                        ]
                    ]
                ]
            )
            return
        }
        let display = payload["display"] as? [String: Any]
        let settings = payload["settings"] as? [String: Any]
        let title = (display?["menu_title"] as? String) ?? "omh"
        let headline = (display?["headline"] as? String) ?? "OMH ready"
        let summary = (display?["summary_line"] as? String) ?? "OMH ready"
        let connection = ((settings?["omh_connection"] as? [String: Any])?["value"] as? String) ?? "unknown"
        let mark = connection == "ready" ? "✓" : "!"
        statusItem.button?.title = "\(title) \(mark)"
        statusItem.button?.toolTip = "\(headline) — \(summary)"
        configureMenu(headline: headline, summary: summary, cards: menuCards(from: payload))
    }

    private func configureMenu(headline: String, summary: String, cards: [[String: Any]]) {
        let menu = NSMenu()
        let headlineItem = disabledItem(" \(headline)")
        let font = NSFont.menuBarFont(ofSize: 0)
        headlineItem.attributedTitle = NSAttributedString(
            string: " \(headline)",
            attributes: [.font: NSFont.boldSystemFont(ofSize: font.pointSize)]
        )
        menu.addItem(headlineItem)
        menu.addItem(disabledItem(" \(summary)"))

        for card in cards {
            menu.addItem(NSMenuItem.separator())
            if let title = card["title"] as? String, !title.isEmpty {
                let item = disabledItem(" \(title)")
                item.attributedTitle = NSAttributedString(
                    string: " \(title)",
                    attributes: [.font: NSFont.boldSystemFont(ofSize: font.pointSize)]
                )
                menu.addItem(item)
            }
            if let columns = card["columns"] as? [String], !columns.isEmpty {
                let line = tableHeaderTitle(columns)
                let item = disabledItem("   \(line)")
                item.toolTip = line
                item.attributedTitle = NSAttributedString(
                    string: "   \(line)",
                    attributes: [.font: NSFont.monospacedSystemFont(ofSize: font.pointSize, weight: .medium)]
                )
                menu.addItem(item)
            }
            if let rows = card["rows"] as? [[String: Any]] {
                for row in rows.prefix(5) {
                    let line = rowTitle(row)
                    let item = disabledItem("   \(line)")
                    item.toolTip = line
                    if (row["kind"] as? String) == "agent_status" {
                        item.attributedTitle = NSAttributedString(
                            string: "   \(line)",
                            attributes: [.font: NSFont.monospacedSystemFont(ofSize: font.pointSize, weight: .regular)]
                        )
                    }
                    menu.addItem(item)
                }
            }
            if let footer = card["footer"] as? String, !footer.isEmpty {
                let item = disabledItem("   \(footer)")
                item.toolTip = footer
                menu.addItem(item)
            }
        }
        menu.addItem(NSMenuItem.separator())
        menu.addItem(NSMenuItem(title: "Refresh", action: #selector(refreshClicked(_:)), keyEquivalent: "r"))
        menu.addItem(NSMenuItem(title: "Quit OMH Menu Bar", action: #selector(quitClicked(_:)), keyEquivalent: "q"))
        statusItem.menu = menu
    }

    private func disabledItem(_ title: String) -> NSMenuItem {
        let item = NSMenuItem(title: title, action: nil, keyEquivalent: "")
        item.isEnabled = false
        return item
    }

    private func tableHeaderTitle(_ columns: [String]) -> String {
        let padded = columns.prefix(3).enumerated().map { index, value in
            if index == 0 {
                return fixedWidth(value, 18)
            }
            if index == 1 {
                return fixedWidth(value, 13)
            }
            return value
        }
        return padded.joined()
    }

    private func fixedWidth(_ value: String, _ length: Int) -> String {
        if value.count > length {
            let endIndex = value.index(value.startIndex, offsetBy: max(0, length - 1))
            return String(value[..<endIndex]) + "…"
        }
        return value.padding(toLength: length, withPad: " ", startingAt: 0)
    }

    private func rowTitle(_ row: [String: Any]) -> String {
        if (row["kind"] as? String) == "agent_status" {
            let agent = fixedWidth((row["agent"] as? String) ?? "unknown", 18)
            let pid = fixedWidth((row["pid"] as? String) ?? "not observed", 13)
            let status = (row["status"] as? String) ?? "unknown"
            return "\(agent)\(pid)\(status)"
        }
        let label = (row["label"] as? String) ?? ""
        let value = (row["value"] as? String) ?? ""
        let detail = (row["detail"] as? String) ?? ""
        var pieces: [String] = []
        if !label.isEmpty {
            pieces.append(label)
        }
        if !value.isEmpty {
            pieces.append(value)
        }
        var title = pieces.joined(separator: ": ")
        if !detail.isEmpty {
            title += " — \(detail)"
        }
        return title.isEmpty ? "Unavailable" : title
    }

    private func menuCards(from payload: [String: Any]) -> [[String: Any]] {
        if
            let display = payload["display"] as? [String: Any],
            let cards = display["menu_cards"] as? [[String: Any]],
            !cards.isEmpty
        {
            return cards
        }
        return fallbackCards(from: payload)
    }

    private func fallbackCards(from payload: [String: Any]) -> [[String: Any]] {
        let settings = payload["settings"] as? [String: Any]
        var rows: [[String: String]] = []
        for key in ["omh_connection", "hermes_targets", "coding_handoff", "send_mode"] {
            if
                let row = settings?[key] as? [String: Any],
                let label = row["label"] as? String
            {
                rows.append(["label": label, "value": ""])
            }
        }
        return [["title": "Overview", "rows": rows]]
    }

    private func readStatusPayload() -> [String: Any]? {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: omhCommand)
        var args: [String] = []
        if !omhHome.isEmpty {
            args.append(contentsOf: ["--omh-home", omhHome])
        }
        if !hermesHome.isEmpty {
            args.append(contentsOf: ["--hermes-home", hermesHome])
        }
        args.append(contentsOf: ["menubar", "status", "--observe-local-processes", "--json"])
        process.arguments = args
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = Pipe()
        do {
            try process.run()
            process.waitUntilExit()
        } catch {
            return nil
        }
        guard process.terminationStatus == 0 else {
            return nil
        }
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        guard
            let object = try? JSONSerialization.jsonObject(with: data, options: []),
            let payload = object as? [String: Any]
        else {
            return nil
        }
        return payload
    }
}

let app = NSApplication.shared
let delegate = OMHMenuBarDelegate()
app.delegate = delegate
app.run()
'''
