"""Own-runtime spike: open an OMH TUI session on a TUI-only Hermes home while the root gateway runs.

Run from the checkout with its interpreter (the `omh` shim resolves the tree):

    uv run python tools/qa/tui_own_runtime/run_spike.py <sandbox-root> [--prompt]

Uses the exact client the OMH TUI uses (`omh.tui.gateway.GatewayClient` over the attach child
`gateway_attach.py`), with `HERMES_HOME=<sandbox>/hermes`, so what it measures is what `omh` would do.
Never signals the root gateway. Writes <sandbox-root>/spike-result.json and prints it.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from omh.tui.gateway import Event, GatewayClient, GatewayExited, ProtocolError, ServerRequest, gateway_spawn

ROOT_HOME = Path(os.environ.get("ROOT_HERMES_HOME", "~/.hermes")).expanduser()
HERMES_AGENT = Path(os.environ.get("HERMES_AGENT", "~/.hermes/hermes-agent")).expanduser()


def hermes_python() -> str:
    found = sorted(glob.glob(str(Path("~/.hermes/tools/python-3.*/bin/python3").expanduser())))
    if not found:
        raise SystemExit("no Hermes toolchain python under ~/.hermes/tools")
    return found[-1]


def record(home: Path) -> dict:
    try:
        return json.loads((home / "gateway_state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def launchd_hermes_jobs() -> list[str]:
    done = subprocess.run(["launchctl", "list"], capture_output=True, text=True, stdin=subprocess.DEVNULL)
    return sorted(line.split("\t")[-1] for line in done.stdout.splitlines() if "hermes" in line.lower())


def writes_since(root: Path, marker: Path) -> list[str]:
    """Files under the root home newer than the marker, minus the root gateway's own housekeeping."""
    done = subprocess.run(
        ["find", str(root), "-newer", str(marker), "-type", "f",
         "-not", "-path", "*/logs/*", "-not", "-path", "*/hermes-agent/*", "-not", "-path", "*/tools/*",
         "-not", "-path", "*/installs/*", "-not", "-name", "*.db", "-not", "-name", "*.db-wal",
         "-not", "-name", "*.db-shm", "-not", "-name", "gateway_state.json", "-not", "-path", "*/__pycache__/*",
         "-not", "-path", "*/sessions/*", "-not", "-path", "*/profiles/*/sessions/*"],
        capture_output=True, text=True, stdin=subprocess.DEVNULL)
    return sorted(line for line in done.stdout.splitlines() if line)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("sandbox")
    parser.add_argument("--prompt", action="store_true", help="send one prompt and wait for message.complete")
    parser.add_argument("--idle-wait", type=float, default=120.0)
    args = parser.parse_args()
    sandbox = Path(args.sandbox).resolve()
    home, omh_home, cwd = sandbox / "hermes", sandbox / "omh", sandbox / "cwd"
    result: dict = {"sandbox": str(sandbox), "steps": []}

    def step(name: str, **facts: object) -> None:
        facts["t"] = round(time.time() - t0, 2)
        result["steps"].append({"step": name, **facts})
        print(f"[{facts['t']:>7}s] {name}: {json.dumps(facts, default=str)[:400]}", flush=True)

    t0 = time.time()
    marker = sandbox / ".marker"
    marker.touch()
    root_before = record(ROOT_HOME)
    result["root_before"] = {k: root_before.get(k) for k in ("pid", "gateway_state", "restart_requested", "served_profiles", "updated_at")}
    result["root_platforms_before"] = {k: v.get("state") for k, v in (root_before.get("platforms") or {}).items()}
    result["launchd_before"] = launchd_hermes_jobs()
    step("root recorded", pid=root_before.get("pid"), state=root_before.get("gateway_state"))

    environ = {
        "HOME": os.environ["HOME"], "PATH": os.environ.get("PATH", ""), "TERM": "xterm-256color",
        "LANG": os.environ.get("LANG", "en_US.UTF-8"),
        "HERMES_PYTHON": hermes_python(), "HERMES_PYTHON_SRC_ROOT": str(HERMES_AGENT),
        "HERMES_HOME": str(home), "OMH_HOME": str(omh_home), "HERMES_TUI_CWD": str(cwd), "HERMES_CWD": str(cwd),
    }
    client = GatewayClient(gateway_spawn(environ))
    try:
        ready = client.start(ready_timeout=240.0)
        step("gateway.ready", payload_keys=sorted(ready.payload)[:12])
        sandbox_record = record(home)
        result["sandbox_record"] = {k: sandbox_record.get(k) for k in ("pid", "gateway_state", "served_profiles", "code_version", "hermes_home")}
        result["sandbox_platforms"] = sandbox_record.get("platforms")
        step("sandbox record", pid=sandbox_record.get("pid"), platforms=list((sandbox_record.get("platforms") or {})),
             same_pid_as_root=sandbox_record.get("pid") == root_before.get("pid"))

        created = client.call("session.create", {"cols": 120, "cwd": str(cwd)}, timeout=120.0)
        sid = created.get("session_id")
        info = created.get("info") if isinstance(created.get("info"), dict) else {}
        result["session_create"] = {"session_id": sid, "subscription_id": bool(created.get("subscription_id")),
                                    "profile_name": info.get("profile_name"), "model": info.get("model"),
                                    "skills_in_create": _skill_count(info.get("skills"))}
        step("session.create", session_id=sid, profile=info.get("profile_name"), model=info.get("model"))

        skills_seen: int | None = result["session_create"]["skills_in_create"]
        events: list[str] = []
        deadline = time.time() + 12.0
        while time.time() < deadline:
            for item in client.poll(timeout=0.5):
                if isinstance(item, Event):
                    events.append(item.type)
                    if item.type == "session.info":
                        count = _skill_count(item.payload.get("skills"))
                        skills_seen = count if count is not None else skills_seen
                elif isinstance(item, ServerRequest):
                    events.append(f"request:{item.method}")
                elif isinstance(item, (ProtocolError, GatewayExited)):
                    events.append(type(item).__name__)
        result["skills_seen_by_session"] = skills_seen
        result["events_after_create"] = sorted(set(events))
        step("session.info", skills=skills_seen, events=sorted(set(events)))

        if args.prompt:
            client.call("prompt.submit", {"session_id": sid, "text": "Reply with the single word: ok"}, timeout=60.0)
            complete, deadline, seen = False, time.time() + 180.0, []
            while time.time() < deadline and not complete:
                for item in client.poll(timeout=0.5):
                    if isinstance(item, Event):
                        seen.append(item.type)
                        complete = complete or item.type == "message.complete"
                    elif isinstance(item, ServerRequest):
                        seen.append(f"request:{item.method}")
            result["prompt"] = {"message_complete": complete, "event_types": sorted(set(seen))}
            step("prompt", complete=complete)

        listed = client.call("session.list", {"limit": 5}, timeout=60.0)
        result["session_list_count"] = len(listed.get("sessions") or []) if isinstance(listed, dict) else None
        step("session.list", count=result["session_list_count"])

        root_mid = record(ROOT_HOME)
        result["root_during"] = {k: root_mid.get(k) for k in ("pid", "gateway_state", "restart_requested", "updated_at")}
        result["root_platforms_during"] = {k: v.get("state") for k, v in (root_mid.get("platforms") or {}).items()}
        result["root_writes_during"] = writes_since(ROOT_HOME, marker)
        result["launchd_during"] = launchd_hermes_jobs()
        step("root during", pid_same=root_mid.get("pid") == root_before.get("pid"), writes=len(result["root_writes_during"]))
    finally:
        code = client.close(grace=2.0, terminate_grace=5.0)
        result["attach_child_exit"] = code
        result["attach_stderr_tail"] = client.stderr_tail()[-20:]
        step("client closed", exit=code)

    pid = result.get("sandbox_record", {}).get("pid")
    deadline = time.time() + args.idle_wait
    states: list[tuple[float, str | None, bool]] = []
    while time.time() < deadline:
        current = record(home)
        alive = pid_alive(pid)
        states.append((round(time.time() - t0, 1), current.get("gateway_state"), alive))
        if not alive and current.get("gateway_state") in ("stopped", None):
            break
        time.sleep(2.0)
    result["idle_exit"] = {"observed_exit": not pid_alive(pid), "final_state": record(home).get("gateway_state"),
                           "drain_reason": record(home).get("drain_reason"), "trace": states[-6:]}
    step("idle exit", exited=not pid_alive(pid), final_state=record(home).get("gateway_state"))
    result["launchd_after"] = launchd_hermes_jobs()
    result["root_after"] = {k: record(ROOT_HOME).get(k) for k in ("pid", "gateway_state", "restart_requested", "updated_at")}
    result["root_writes_total"] = writes_since(ROOT_HOME, marker)
    result["sandbox_gateway_log_tail"] = _tail(home / "logs" / "gateway.log", 25)
    result["ambiguous_skill_warnings"] = [line for line in _tail(home / "logs" / "gateway.error.log", 400) if "Ambiguous skill name" in line]
    (sandbox / "spike-result.json").write_text(json.dumps(result, indent=1, default=str, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: result[k] for k in result if k not in ("steps", "sandbox_gateway_log_tail")}, indent=1, default=str, ensure_ascii=False))
    return 0


def _skill_count(skills: object) -> int | None:
    if isinstance(skills, dict):
        return sum(len(v) if isinstance(v, list) else 0 for v in skills.values())
    if isinstance(skills, list):
        return len(skills)
    return None


def _tail(path: Path, lines: int) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]
    except OSError:
        return []


if __name__ == "__main__":
    sys.exit(main())
