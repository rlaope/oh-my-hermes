from __future__ import annotations

import os
import platform
import plistlib
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .command_path import inspect_omh_command_path
from .local_store import atomic_write_text
from .paths import OmhPaths
from .runtime.artifacts import update_state


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
        configureMenu(summary: "Loading OMH status", details: [])
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
            configureMenu(summary: "OMH status unavailable", details: ["Run omh doctor in Terminal."])
            return
        }
        let display = payload["display"] as? [String: Any]
        let settings = payload["settings"] as? [String: Any]
        let title = (display?["menu_title"] as? String) ?? "omh"
        let summary = (display?["summary_line"] as? String) ?? "OMH ready"
        let connection = ((settings?["omh_connection"] as? [String: Any])?["value"] as? String) ?? "unknown"
        let mark = connection == "ready" ? "✓" : "!"
        statusItem.button?.title = "\(title) \(mark)"
        statusItem.button?.toolTip = summary
        var details: [String] = []
        for key in ["omh_connection", "hermes_targets", "coding_handoff", "send_mode"] {
            if let row = settings?[key] as? [String: Any], let label = row["label"] as? String {
                details.append(label)
            }
        }
        configureMenu(summary: summary, details: details)
    }

    private func configureMenu(summary: String, details: [String]) {
        let menu = NSMenu()
        let summaryItem = NSMenuItem(title: summary, action: nil, keyEquivalent: "")
        summaryItem.isEnabled = false
        menu.addItem(summaryItem)
        if !details.isEmpty {
            menu.addItem(NSMenuItem.separator())
            for detail in details {
                let item = NSMenuItem(title: detail, action: nil, keyEquivalent: "")
                item.isEnabled = false
                menu.addItem(item)
            }
        }
        menu.addItem(NSMenuItem.separator())
        menu.addItem(NSMenuItem(title: "Refresh", action: #selector(refreshClicked(_:)), keyEquivalent: "r"))
        menu.addItem(NSMenuItem(title: "Quit OMH Menu Bar", action: #selector(quitClicked(_:)), keyEquivalent: "q"))
        statusItem.menu = menu
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
        args.append(contentsOf: ["menubar", "status"])
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
