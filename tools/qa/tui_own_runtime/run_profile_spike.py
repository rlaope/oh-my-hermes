"""Profile spike: the TUI home as a standalone Hermes profile (`<root>/profiles/omh-tui`, `gateway.standalone: true`),
sharing the root's `auth.json` through Hermes' profile fallback, with a gateway of its own beside the host gateway.

    uv run python .omc/research/tui-own-runtime/spike/run_profile_spike.py <sandbox-root> [--prompt] [--keep]

Builds the profile with the current `build_tui_home` plus the two differences under test (standalone key, no
`auth.json`), moves it into place under a dot-name first, then opens a session the way `omh` would. Removes the
profile afterwards unless `--keep`. Never signals the root gateway. Never prints a credential value.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_spike as base  # noqa: E402

from omh.tui.gateway import Event, GatewayClient, GatewayExited, ProtocolError, ServerRequest, gateway_spawn  # noqa: E402
from omh.tui.own_runtime import build_tui_home  # noqa: E402

PROFILE = "omh-tui"


def with_standalone(text: str) -> str:
    lines = text.splitlines(keepends=True)
    out, in_gateway, done = [], False, False
    for line in lines:
        if line.startswith("gateway:") and not done:
            out.append(line)
            out.append("  standalone: true\n")
            out.append("  unmanaged_idle_exit_seconds: 30\n")
            in_gateway, done = True, True
            continue
        if in_gateway and line.strip() and not line.startswith((" ", "\t", "#")):
            in_gateway = False
        if in_gateway and line.strip().startswith(("standalone:", "unmanaged_idle_exit_seconds:")):
            continue
        out.append(line)
    if not done:
        out.append("gateway:\n  standalone: true\n  unmanaged_idle_exit_seconds: 30\n")
    return "".join(out)


def auth_shape(path: Path) -> dict:
    """Shape only: which providers and pool slots exist, and the file's mtime. No values."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"exists": path.exists()}
    pool = data.get("credential_pool") or {}
    return {
        "mtime_ns": path.stat().st_mtime_ns,
        "providers": sorted((data.get("providers") or {}).keys()),
        "pool": {k: len(v) if isinstance(v, list) else None for k, v in pool.items()},
        "active_provider": data.get("active_provider"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("sandbox")
    parser.add_argument("--prompt", action="store_true")
    parser.add_argument("--keep", action="store_true")
    parser.add_argument("--idle-wait", type=float, default=120.0)
    args = parser.parse_args()
    sandbox = Path(args.sandbox).resolve()
    omh_home, cwd = sandbox / "omh", sandbox / "cwd"
    for d in (omh_home, cwd):
        d.mkdir(parents=True, exist_ok=True)
    root = base.ROOT_HOME
    profiles = root / "profiles"
    staging, home = profiles / f".{PROFILE}.staging", profiles / PROFILE
    result: dict = {"steps": []}
    t0 = time.time()

    def step(name: str, **facts: object) -> None:
        facts["t"] = round(time.time() - t0, 2)
        result["steps"].append({"step": name, **facts})
        print(f"[{facts['t']:>7}s] {name}: {json.dumps(facts, default=str)[:500]}", flush=True)

    if home.exists() or staging.exists():
        raise SystemExit(f"{home} or {staging} already exists; refusing")
    marker = sandbox / ".marker"
    marker.touch()
    result["root_before"] = {k: base.record(root).get(k) for k in ("pid", "gateway_state", "served_profiles")}
    result["root_auth_before"] = auth_shape(root / "auth.json")
    step("root recorded", **result["root_before"])

    # 1. Build with the current builder into a scratch OMH home, then apply the two differences under test.
    built = build_tui_home(omh_home, root)
    scratch = built.path
    config = scratch / "config.yaml"
    config.write_text(with_standalone(config.read_text(encoding="utf-8")), encoding="utf-8")
    (scratch / "auth.json").unlink(missing_ok=True)
    step("built", skills=len(built.skills), clashes=len(built.clashes), scrubbed=list(built.scrubbed),
         has_auth=(scratch / "auth.json").exists())
    # 2. Into place under a dot name (not a profile to Hermes), then one rename.
    shutil.move(str(scratch), str(staging))
    os.rename(staging, home)
    step("profile placed", home=str(home))
    time.sleep(3.0)
    result["root_after_place"] = {k: base.record(root).get(k) for k in ("pid", "gateway_state", "served_profiles")}
    step("root after place", **result["root_after_place"])

    environ = {
        "HOME": os.environ["HOME"], "PATH": os.environ.get("PATH", ""), "TERM": "xterm-256color",
        "LANG": os.environ.get("LANG", "en_US.UTF-8"),
        "HERMES_PYTHON": base.hermes_python(), "HERMES_PYTHON_SRC_ROOT": str(base.HERMES_AGENT),
        "HERMES_HOME": str(home), "OMH_HOME": str(omh_home), "HERMES_TUI_CWD": str(cwd), "HERMES_CWD": str(cwd),
    }
    client = GatewayClient(gateway_spawn(environ))
    pid = None
    try:
        try:
            ready = client.start(ready_timeout=240.0)
            step("gateway.ready", payload_keys=sorted(ready.payload)[:12])
        except Exception as error:  # the measurement: say what the attach child said
            result["start_error"] = repr(error)
            result["attach_stderr_tail"] = client.stderr_tail()[-40:]
            step("gateway start failed", error=repr(error))
            raise
        own = base.record(home)
        pid = own.get("pid")
        result["own_record"] = {k: own.get(k) for k in ("pid", "gateway_state", "served_profiles", "hermes_home")}
        result["own_platforms"] = own.get("platforms")
        step("own record", pid=pid, same_as_root=pid == result["root_before"]["pid"], platforms=list(own.get("platforms") or {}))
        created = client.call("session.create", {"cols": 120, "cwd": str(cwd)}, timeout=120.0)
        sid = created.get("session_id")
        info = created.get("info") if isinstance(created.get("info"), dict) else {}
        result["session_create"] = {"profile_name": info.get("profile_name"), "model": info.get("model"),
                                    "skills": base._skill_count(info.get("skills"))}
        step("session.create", **result["session_create"])
        if args.prompt:
            client.call("prompt.submit", {"session_id": sid, "text": "Reply with the single word: ok"}, timeout=60.0)
            complete, deadline, seen, texts = False, time.time() + 180.0, [], []
            while time.time() < deadline and not complete:
                for item in client.poll(timeout=0.5):
                    if isinstance(item, Event):
                        seen.append(item.type)
                        if item.type in ("message.delta", "message.text", "assistant.delta"):
                            texts.append(str(item.payload.get("text") or item.payload.get("delta") or "")[:80])
                        complete = complete or item.type == "message.complete"
                    elif isinstance(item, ServerRequest):
                        seen.append(f"request:{item.method}")
                    elif isinstance(item, (ProtocolError, GatewayExited)):
                        seen.append(type(item).__name__)
            result["prompt"] = {"message_complete": complete, "event_types": sorted(set(seen)), "text_sample": texts[:3]}
            step("prompt", complete=complete, events=sorted(set(seen)))
        result["root_during"] = {k: base.record(root).get(k) for k in ("pid", "gateway_state", "served_profiles")}
        step("root during", **result["root_during"])
    finally:
        code = client.close(grace=2.0, terminate_grace=5.0)
        result["attach_child_exit"] = code
        result.setdefault("attach_stderr_tail", client.stderr_tail()[-20:])
        step("client closed", exit=code)

    deadline = time.time() + args.idle_wait
    while time.time() < deadline and pid and base.pid_alive(pid):
        time.sleep(2.0)
    result["idle_exit"] = {"exited": not base.pid_alive(pid) if pid else None, "final_state": base.record(home).get("gateway_state")}
    step("idle exit", **result["idle_exit"])
    result["profile_auth_after"] = {"exists": (home / "auth.json").exists()}
    result["root_auth_after"] = auth_shape(root / "auth.json")
    result["root_after"] = {k: base.record(root).get(k) for k in ("pid", "gateway_state", "served_profiles")}
    result["root_writes"] = base.writes_since(root, marker)
    result["own_gateway_log_tail"] = base._tail(home / "logs" / "gateway.log", 25)
    result["own_error_log_tail"] = base._tail(home / "logs" / "gateway.error.log", 15)
    result["ambiguous_skill_warnings"] = [l for l in base._tail(home / "logs" / "gateway.error.log", 400) if "Ambiguous skill name" in l]
    if not args.keep:
        os.rename(home, staging)
        shutil.rmtree(staging)
        step("profile removed")
    (sandbox / "profile-spike-result.json").write_text(json.dumps(result, indent=1, default=str, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: result[k] for k in result if k not in ("steps", "own_gateway_log_tail")}, indent=1, default=str, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
