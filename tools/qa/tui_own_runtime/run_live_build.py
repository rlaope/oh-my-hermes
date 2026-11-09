"""Live check of the shipped builder: `build_tui_home` from this checkout against the real root, a session opened
the way `omh` opens it, then the profile removed with `remove_tui_home`. A scratch OMH home keeps the legacy
`~/.omh/tui-home` out of it. Never signals the root gateway; prints no credential value.

    uv run python .omc/research/tui-own-runtime/spike/run_live_build.py <scratch-dir> [--prompt] [--keep]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_spike as base  # noqa: E402

from omh.tui.gateway import Event, GatewayClient, ServerRequest, gateway_spawn  # noqa: E402
from omh.tui.own_runtime import build_tui_home, remove_tui_home, tui_home_path  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("scratch")
    parser.add_argument("--prompt", action="store_true")
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()
    scratch = Path(args.scratch).resolve()
    omh_home, cwd = scratch / "omh", scratch / "cwd"
    for d in (omh_home, cwd):
        d.mkdir(parents=True, exist_ok=True)
    root = base.ROOT_HOME
    home = tui_home_path(root)
    if home.exists():
        raise SystemExit(f"{home} exists; refusing")
    out: dict = {}
    t0 = time.time()
    built = build_tui_home(omh_home, root)
    out["built"] = {"path": str(built.path), "served": list(built.served), "skills": len(built.skills),
                    "clashes": len(built.clashes), "scrubbed": list(built.scrubbed), "refreshed": len(built.refreshed),
                    "platform_credentials": list(built.config_platform_credentials), "seconds": round(time.time() - t0, 2)}
    config = (home / "config.yaml").read_text(encoding="utf-8")
    out["config_has_standalone"] = "  standalone: true\n" in config
    out["config_gateway_block"] = [l for l in config.splitlines() if l.startswith("gateway:") or (l.startswith("  ") and "standalone" in l)]
    out["auth_in_profile"] = (home / "auth.json").exists()
    out["no_bundled_marker"] = (home / ".no-bundled-skills").is_file()
    out["staging_left"] = [p.name for p in (root / "profiles").iterdir() if p.name.startswith(".")]
    second = build_tui_home(omh_home, root)
    out["second_build_refreshed"] = list(second.refreshed)
    out["root_before"] = {k: base.record(root).get(k) for k in ("pid", "served_profiles")}
    print(json.dumps(out, indent=1, ensure_ascii=False), flush=True)

    environ = {
        "HOME": os.environ["HOME"], "PATH": os.environ.get("PATH", ""), "TERM": "xterm-256color",
        "LANG": os.environ.get("LANG", "en_US.UTF-8"),
        "HERMES_PYTHON": base.hermes_python(), "HERMES_PYTHON_SRC_ROOT": str(base.HERMES_AGENT),
        "HERMES_HOME": str(home), "OMH_HOME": str(omh_home), "HERMES_TUI_CWD": str(cwd), "HERMES_CWD": str(cwd),
    }
    client = GatewayClient(gateway_spawn(environ))
    pid = None
    try:
        t1 = time.time()
        client.start(ready_timeout=240.0)
        own = base.record(home)
        pid = own.get("pid")
        out["gateway"] = {"ready_seconds": round(time.time() - t1, 2), "pid": pid, "platforms": list(own.get("platforms") or {}),
                          "hermes_home": own.get("hermes_home")}
        created = client.call("session.create", {"cols": 120, "cwd": str(cwd)}, timeout=120.0)
        info = created.get("info") if isinstance(created.get("info"), dict) else {}
        out["session"] = {"profile": info.get("profile_name"), "model": info.get("model"), "skills": base._skill_count(info.get("skills"))}
        if args.prompt:
            client.call("prompt.submit", {"session_id": created.get("session_id"), "text": "Reply with the single word: ok"}, timeout=60.0)
            complete, deadline, text = False, time.time() + 180.0, []
            while time.time() < deadline and not complete:
                for item in client.poll(timeout=0.5):
                    if isinstance(item, Event):
                        if item.type == "message.delta":
                            text.append(str(item.payload.get("text") or item.payload.get("delta") or ""))
                        complete = complete or item.type == "message.complete"
                    elif isinstance(item, ServerRequest):
                        pass
            out["prompt"] = {"complete": complete, "text": "".join(text)[:40]}
        out["root_during"] = {k: base.record(root).get(k) for k in ("pid", "served_profiles")}
    finally:
        out["attach_exit"] = client.close(grace=2.0, terminate_grace=5.0)
        out["attach_stderr_tail"] = client.stderr_tail()[-10:]
    print(json.dumps({k: out[k] for k in ("gateway", "session", "prompt", "root_during", "attach_exit", "attach_stderr_tail") if k in out},
                     indent=1, ensure_ascii=False), flush=True)
    if not args.keep:
        if pid and base.pid_alive(pid):
            os.kill(pid, 15)  # the TUI profile's own gateway, started by this script
            for _ in range(20):
                if not base.pid_alive(pid):
                    break
                time.sleep(0.5)
        out["removed"] = remove_tui_home(root)
        out["profiles_after"] = sorted(p.name for p in (root / "profiles").iterdir())
        print(json.dumps({k: out[k] for k in ("removed", "profiles_after")}), flush=True)
    (scratch / "live-build-result.json").write_text(json.dumps(out, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
