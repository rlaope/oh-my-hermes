from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
from typing import Mapping, Sequence

from ..release import (
    first_use_status_smoke_plan,
    installed_command_smoke_plan,
    run_installed_command_smoke,
)
from ..release_smoke_core import CommandResult, Runner, bounded_text, subprocess_runner_exact_env

INSTALL_SCRIPT_SMOKE_SCHEMA = "install_script_smoke/v1"


def install_script_smoke_plan(
    *,
    repo_root: str | Path | None = None,
    install_script: str | Path | None = None,
    package_url: str | Path | None = None,
    python_command: str = "",
    setup_args: Sequence[str] = (),
    run_setup: bool = False,
    run_doctor: bool = True,
    work_dir: str | Path | None = None,
) -> dict[str, object]:
    root = _resolve_repo_root(repo_root)
    script = _resolve_install_script(root, install_script)
    package = _resolve_package_url(root, package_url)
    work = _resolve_install_smoke_work_dir(work_dir)
    paths = _install_smoke_paths(work)
    command_under_test = str(paths["bin_dir"] / "omh")
    env = _install_smoke_env(
        home=paths["home"],
        venv_dir=paths["venv_dir"],
        bin_dir=paths["bin_dir"],
        package_url=package,
        python_command=python_command or sys.executable,
        setup_args=setup_args,
        run_setup=run_setup,
        run_doctor=run_doctor,
    )
    first_use_status = first_use_status_smoke_plan(
        omh_command=command_under_test,
        omh_home=paths["home"] / ".omh",
        hermes_home=paths["home"] / ".hermes",
    )
    return {
        "schema_version": INSTALL_SCRIPT_SMOKE_SCHEMA,
        "mode": "plan",
        "ok": script.is_file(),
        "observed": False,
        "repo_root": str(root),
        "install_script": str(script),
        "install_script_found": script.is_file(),
        "package_url": package,
        "work_dir": str(work),
        "retained_work_dir": work_dir is not None,
        "command_under_test": command_under_test,
        "environment": _public_install_smoke_env(env),
        "steps": [
            {
                "name": "install_script",
                "command": ["sh", str(script)],
                "phase": "install",
                "mutates_profile": False,
                "required": True,
                "proof_boundary": (
                    "Runs install.sh with isolated HOME, OMH_VENV_DIR, and OMH_BIN_DIR. The default installer path "
                    "installs the omh command only and does not run setup, doctor, or mutate the operator's real Hermes profile."
                ),
            },
            {
                "name": "installed_command_smoke",
                "command": [
                    command_under_test,
                    "release",
                    "hermes-smoke",
                    "--install-path",
                    "setup",
                    "--omh-command",
                    command_under_test,
                    "--include-command-smoke",
                ],
                "phase": "verify",
                "mutates_profile": False,
                "required": True,
                "proof_boundary": (
                    "Proves the installed command can run help and render setup-path release smoke. "
                    "This still does not prove live Hermes chat selected OMH."
                ),
            },
        ],
        "first_use_status_smoke": first_use_status,
        "recommended_next_action": (
            "Run with --live to execute install.sh in an isolated temp home, then inspect the JSON evidence before release."
            if script.is_file()
            else "Run from the OMH source checkout or pass --install-script pointing at install.sh."
        ),
        "proof_boundary": (
            "Plan mode is deterministic and local. It does not download over curl, run pip, run setup, mutate Hermes, or prove runtime chat use."
        ),
    }


def run_install_script_smoke(
    *,
    repo_root: str | Path | None = None,
    install_script: str | Path | None = None,
    package_url: str | Path | None = None,
    python_command: str = "",
    setup_args: Sequence[str] = (),
    run_setup: bool = False,
    run_doctor: bool = True,
    timeout_seconds: int = 120,
    work_dir: str | Path | None = None,
    keep_work_dir: bool = False,
    runner: Runner | None = None,
) -> dict[str, object]:
    if timeout_seconds < 1:
        raise ValueError("Install script smoke timeout must be at least one second")
    if work_dir is not None:
        return _run_install_script_smoke_in_dir(
            repo_root=repo_root,
            install_script=install_script,
            package_url=package_url,
            python_command=python_command,
            setup_args=setup_args,
            run_setup=run_setup,
            run_doctor=run_doctor,
            timeout_seconds=timeout_seconds,
            work_dir=Path(work_dir).expanduser().resolve(),
            keep_work_dir=True,
            runner=runner,
        )
    if keep_work_dir:
        tmp = Path(tempfile.mkdtemp(prefix="omh-install-smoke-")).resolve()
        return _run_install_script_smoke_in_dir(
            repo_root=repo_root,
            install_script=install_script,
            package_url=package_url,
            python_command=python_command,
            setup_args=setup_args,
            run_setup=run_setup,
            run_doctor=run_doctor,
            timeout_seconds=timeout_seconds,
            work_dir=tmp,
            keep_work_dir=True,
            runner=runner,
        )
    with tempfile.TemporaryDirectory(prefix="omh-install-smoke-") as tmp:
        return _run_install_script_smoke_in_dir(
            repo_root=repo_root,
            install_script=install_script,
            package_url=package_url,
            python_command=python_command,
            setup_args=setup_args,
            run_setup=run_setup,
            run_doctor=run_doctor,
            timeout_seconds=timeout_seconds,
            work_dir=Path(tmp).resolve(),
            keep_work_dir=keep_work_dir,
            runner=runner,
        )


def _run_install_script_smoke_in_dir(
    *,
    repo_root: str | Path | None,
    install_script: str | Path | None,
    package_url: str | Path | None,
    python_command: str,
    setup_args: Sequence[str],
    run_setup: bool,
    run_doctor: bool,
    timeout_seconds: int,
    work_dir: Path,
    keep_work_dir: bool,
    runner: Runner | None,
) -> dict[str, object]:
    plan = install_script_smoke_plan(
        repo_root=repo_root,
        install_script=install_script,
        package_url=package_url,
        python_command=python_command,
        setup_args=setup_args,
        run_setup=run_setup,
        run_doctor=run_doctor,
        work_dir=work_dir,
    )
    if not bool(plan["install_script_found"]):
        return {
            **plan,
            "mode": "live",
            "ok": False,
            "observed": False,
            "results": [],
            "failed_step": "install_script_missing",
            "recommended_next_action": "Run from the OMH source checkout or pass --install-script pointing at install.sh.",
        }
    paths = _install_smoke_paths(work_dir)
    for path in (paths["home"], paths["venv_dir"], paths["bin_dir"]):
        path.mkdir(parents=True, exist_ok=True)
    execute = runner or subprocess_runner_exact_env
    env = _install_smoke_env(
        home=paths["home"],
        venv_dir=paths["venv_dir"],
        bin_dir=paths["bin_dir"],
        package_url=str(plan["package_url"]),
        python_command=python_command or sys.executable,
        setup_args=setup_args,
        run_setup=run_setup,
        run_doctor=run_doctor,
    )
    results: list[dict[str, object]] = []
    failed_step = ""
    ok = True

    installer_step = dict(plan["steps"][0])
    installer_result = execute(installer_step["command"], timeout_seconds, env)
    installer_ok = installer_result.returncode == 0
    ok = ok and installer_ok
    results.append(_smoke_step_result(installer_step, installer_result, env))
    if not installer_ok:
        failed_step = "install_script"

    command_smoke: dict[str, object] | None = None
    if ok:
        def smoke_runner(
            command: Sequence[str],
            nested_timeout_seconds: int,
            nested_env: Mapping[str, str] | None,
        ) -> CommandResult:
            scoped_env = dict(env)
            if nested_env:
                scoped_env.update({key: str(value) for key, value in nested_env.items()})
            return execute(command, nested_timeout_seconds, scoped_env)

        command_smoke = run_installed_command_smoke(
            omh_command=str(plan["command_under_test"]),
            omh_home=paths["home"] / ".omh",
            hermes_home=paths["home"] / ".hermes",
            timeout_seconds=timeout_seconds,
            runner=smoke_runner,
        )
        ok = bool(command_smoke["ok"])
        command_step = dict(plan["steps"][1])
        results.append(
            {
                **command_step,
                "returncode": 0 if command_smoke["ok"] else 1,
                "ok": bool(command_smoke["ok"]),
                "environment": _public_install_smoke_env(env),
                "stdout_excerpt": "",
                "stderr_excerpt": "" if command_smoke["ok"] else str(command_smoke.get("recommended_next_action", "")),
            }
        )
        if not ok:
            failed_step = "installed_command_smoke"

    return {
        **plan,
        "mode": "live",
        "ok": ok,
        "observed": bool(results),
        "retained_work_dir": bool(keep_work_dir),
        "results": results,
        "installed_command_smoke": command_smoke or installed_command_smoke_plan(
            omh_command=str(plan["command_under_test"]),
            omh_home=paths["home"] / ".omh",
            hermes_home=paths["home"] / ".hermes",
        ),
        "failed_step": failed_step,
        "recommended_next_action": _install_script_smoke_next_action(ok, failed_step),
        "proof_boundary": (
            "Live install smoke observes install.sh and installed-command smoke inside an isolated temp home with an "
            "explicit smoke environment only. The default path installs the command only; it does not run setup, mutate "
            "the operator's Hermes profile, inherit operator OMH installer controls, or prove live Hermes chat selected OMH."
        ),
    }


def _resolve_repo_root(repo_root: str | Path | None) -> Path:
    if repo_root is not None:
        return Path(repo_root).expanduser().resolve()
    cwd = Path.cwd().resolve()
    if (cwd / "install.sh").is_file() and (cwd / "pyproject.toml").is_file():
        return cwd
    return Path(__file__).resolve().parents[1]


def _resolve_install_script(repo_root: Path, install_script: str | Path | None) -> Path:
    if install_script is not None:
        return Path(install_script).expanduser().resolve()
    return (repo_root / "install.sh").resolve()


def _resolve_package_url(repo_root: Path, package_url: str | Path | None) -> str:
    if package_url is None or str(package_url).strip() == "":
        return str(repo_root)
    return str(package_url)


def _resolve_install_smoke_work_dir(work_dir: str | Path | None) -> Path:
    if work_dir is not None:
        return Path(work_dir).expanduser().resolve()
    return Path("<tempdir>")


def _install_smoke_paths(work_dir: Path) -> dict[str, Path]:
    return {
        "work_dir": work_dir,
        "home": work_dir / "home",
        "venv_dir": work_dir / "venv",
        "bin_dir": work_dir / "bin",
    }


def _install_smoke_env(
    *,
    home: Path,
    venv_dir: Path,
    bin_dir: Path,
    package_url: str,
    python_command: str,
    setup_args: Sequence[str],
    run_setup: bool,
    run_doctor: bool,
) -> dict[str, str]:
    path = os.environ.get("PATH", "")
    return {
        "HOME": str(home),
        "OMH_HOME": str(home / ".omh"),
        "HERMES_HOME": str(home / ".hermes"),
        "PATH": f"{bin_dir}{os.pathsep}{path}" if path else str(bin_dir),
        "NO_COLOR": "1",
        "OMH_CHANNEL": "local",
        "OMH_SOURCE_REF": "install-smoke-local",
        "OMH_PACKAGE_URL": str(package_url),
        "OMH_PYTHON": str(python_command),
        "OMH_INSTALL_MODE": "venv",
        "OMH_VENV_DIR": str(venv_dir),
        "OMH_BIN_DIR": str(bin_dir),
        "OMH_LINK_COMMAND": "1",
        "OMH_FORCE_LINK": "1",
        "OMH_RUN_SETUP": "1" if run_setup else "0",
        "OMH_AUTO_APPLY": "1",
        "OMH_RUN_DOCTOR": "1" if run_doctor else "0",
        "OMH_LANG": "en",
        "OMH_SETUP_ARGS": " ".join(str(item) for item in setup_args),
    }


def _public_install_smoke_env(env: Mapping[str, str]) -> dict[str, str]:
    keys = (
        "HOME",
        "OMH_HOME",
        "HERMES_HOME",
        "OMH_CHANNEL",
        "OMH_SOURCE_REF",
        "OMH_PACKAGE_URL",
        "OMH_PYTHON",
        "OMH_INSTALL_MODE",
        "OMH_VENV_DIR",
        "OMH_BIN_DIR",
        "OMH_RUN_SETUP",
        "OMH_AUTO_APPLY",
        "OMH_RUN_DOCTOR",
        "OMH_SETUP_ARGS",
    )
    return {key: str(env[key]) for key in keys if key in env}


def _smoke_step_result(step: Mapping[str, object], result: CommandResult, env: Mapping[str, str]) -> dict[str, object]:
    return {
        **dict(step),
        "returncode": result.returncode,
        "ok": result.returncode == 0,
        "environment": _public_install_smoke_env(env),
        "stdout_excerpt": bounded_text(result.stdout),
        "stderr_excerpt": bounded_text(result.stderr),
    }


def _install_script_smoke_next_action(ok: bool, failed_step: str) -> str:
    if ok:
        return (
            "Run the smoke-installed `omh setup` explicitly if you want profile registration evidence, then restart or "
            "reload the target Hermes Agent and record the observed chat/status response separately."
        )
    if failed_step == "install_script_missing":
        return "Run from the OMH source checkout or pass --install-script pointing at install.sh."
    if failed_step == "install_script":
        return "Inspect the install.sh stdout/stderr excerpt, then rerun with --keep-work-dir to preserve the temp venv and homes."
    if failed_step == "installed_command_smoke":
        return "Repair the smoke-installed `omh` command path or setup-plan rendering, then rerun release install-smoke."
    return "Inspect the failed install smoke step and rerun after repair."
