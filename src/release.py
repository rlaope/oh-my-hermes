from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess
from typing import Callable, Mapping, Sequence

REPOSITORY_ARCHIVE_ROOT = "https://github.com/rlaope/oh-my-hermes/archive/refs"
RELEASE_CHANNELS = ("stable", "preview", "local")
HERMES_SMOKE_SCHEMA = "hermes_release_smoke/v1"
INSTALLED_COMMAND_SMOKE_SCHEMA = "installed_omh_command_smoke/v1"
FIRST_USE_STATUS_SMOKE_SCHEMA = "first_use_status_smoke/v1"
DEFAULT_HERMES_TAP = "rlaope/oh-my-hermes"
DEFAULT_HERMES_SKILL = "oh-my-hermes"
DEFAULT_FIRST_USE_MESSAGE = "I want to safely add a feature to this repo"
INSTALL_PATHS = ("tap", "setup")


@dataclass(frozen=True)
class ReleaseSelection:
    channel: str
    version: str
    package_url: str
    source_label: str


def package_url_for(channel: str, version: str = "", package_url: str = "") -> ReleaseSelection:
    if channel not in RELEASE_CHANNELS:
        raise ValueError(f"unsupported release channel: {channel}")
    if package_url:
        return ReleaseSelection(channel, version, package_url, "custom-url")
    if channel == "stable":
        if not version:
            raise ValueError("stable channel requires --version or OMH_VERSION")
        tag = version if version.startswith("v") else f"v{version}"
        return ReleaseSelection(channel, version, f"{REPOSITORY_ARCHIVE_ROOT}/tags/{tag}.zip", tag)
    if channel == "preview":
        return ReleaseSelection(channel, version, f"{REPOSITORY_ARCHIVE_ROOT}/heads/main.zip", "main")
    return ReleaseSelection(channel, version, "local", "local")


@dataclass(frozen=True)
class HermesSmokeStep:
    name: str
    command: tuple[str, ...]
    phase: str
    mutates_profile: bool
    required: bool = True
    proof_boundary: str = ""

    def to_payload(self) -> dict[str, object]:
        return {
            "name": self.name,
            "command": list(self.command),
            "phase": self.phase,
            "mutates_profile": self.mutates_profile,
            "required": self.required,
            "proof_boundary": self.proof_boundary,
        }


@dataclass(frozen=True)
class CommandResult:
    command: Sequence[str]
    returncode: int
    stdout: str = ""
    stderr: str = ""


Runner = Callable[[Sequence[str], int, Mapping[str, str] | None], CommandResult]


def hermes_release_smoke_steps(
    *,
    install_path: str,
    skill: str = DEFAULT_HERMES_SKILL,
    tap: str = DEFAULT_HERMES_TAP,
    omh_command: str = "omh",
    omh_home: str | Path | None = None,
    hermes_home: str | Path | None = None,
) -> list[HermesSmokeStep]:
    if install_path not in INSTALL_PATHS:
        raise ValueError(f"unsupported Hermes install path: {install_path}")
    if not skill:
        raise ValueError("Hermes smoke skill must not be empty")
    if install_path == "tap" and not tap:
        raise ValueError("Hermes smoke tap must not be empty for tap installs")
    skill_name = _skill_name_for_hermes(skill)
    tap_identifier = _tap_skill_identifier(tap=tap, skill=skill)
    setup_command = _omh_scoped_command(
        omh_command,
        "setup",
        omh_home=omh_home,
        hermes_home=hermes_home,
    )
    doctor_command = _omh_scoped_command(
        omh_command,
        "doctor",
        omh_home=omh_home,
        hermes_home=hermes_home,
    )
    install_steps = (
        [
            HermesSmokeStep(
                "tap_add",
                ("hermes", "skills", "tap", "add", tap),
                "install",
                True,
                proof_boundary="Registers the OMH GitHub tap in the current Hermes profile; this is setup evidence only.",
            ),
            HermesSmokeStep(
                "skill_install",
                ("hermes", "skills", "install", tap_identifier, "--yes"),
                "install",
                True,
                proof_boundary=(
                    "Installs the router skill by full GitHub identifier in the current Hermes profile; "
                    "this does not prove chat usage."
                ),
            ),
        ]
        if install_path == "tap"
        else [
            HermesSmokeStep(
                "omh_setup",
                setup_command,
                "install",
                True,
                proof_boundary="Bootstraps generated skills and skills.external_dirs for the current Hermes home.",
            )
        ]
    )
    check_steps = [
        HermesSmokeStep(
            "tap_list",
            ("hermes", "skills", "tap", "list"),
            "verify",
            False,
            proof_boundary="Shows configured taps; absence means tap install has not been observed.",
        ),
        HermesSmokeStep(
            "skills_list",
            ("hermes", "skills", "list", "--enabled-only"),
            "verify",
            False,
            proof_boundary="Shows enabled Hermes skills; the OMH router should be visible after install/reload.",
        ),
        HermesSmokeStep(
            "skill_check",
            ("hermes", "skills", "check", skill_name),
            "verify",
            False,
            proof_boundary="Runs Hermes skill validation for the OMH router skill.",
        ),
    ]
    if install_path == "tap":
        check_steps.append(
            HermesSmokeStep(
                "skill_inspect",
                ("hermes", "skills", "inspect", tap_identifier),
                "verify",
                False,
                proof_boundary="Prints Hermes-visible skill metadata/content for operator confirmation.",
            )
        )
    else:
        check_steps.append(
            HermesSmokeStep(
                "setup_doctor",
                doctor_command,
                "verify",
                False,
                proof_boundary=(
                    "Checks OMH-managed local skill registration. Hermes v0.15.1 does not reliably inspect "
                    "skills.external_dirs local skills by short name, so setup-path smoke uses list/check plus OMH doctor."
                ),
            )
        )
    return install_steps + check_steps


def _skill_name_for_hermes(skill: str) -> str:
    return skill.rstrip("/").split("/")[-1]


def _tap_skill_identifier(*, tap: str, skill: str) -> str:
    if "/" in skill:
        return skill
    return f"{tap.rstrip('/')}/skills/{skill}"


def hermes_release_smoke_plan(
    *,
    install_path: str = "tap",
    skill: str = DEFAULT_HERMES_SKILL,
    tap: str = DEFAULT_HERMES_TAP,
    omh_command: str = "omh",
    omh_home: str | Path | None = None,
    hermes_home: str | Path | None = None,
    installed_command_smoke: Mapping[str, object] | None = None,
) -> dict[str, object]:
    target = _target_binding(omh_home=omh_home, hermes_home=hermes_home)
    steps = hermes_release_smoke_steps(
        install_path=install_path,
        skill=skill,
        tap=tap,
        omh_command=omh_command,
        omh_home=target["omh_home"],
        hermes_home=target["hermes_home"],
    )
    command_smoke = (
        dict(installed_command_smoke)
        if installed_command_smoke is not None
        else installed_command_smoke_plan(
            omh_command=omh_command,
            omh_home=target["omh_home"],
            hermes_home=target["hermes_home"],
        )
    )
    ok = not (command_smoke.get("observed") and not command_smoke.get("ok"))
    return {
        "schema_version": HERMES_SMOKE_SCHEMA,
        "mode": "plan",
        "ok": ok,
        "observed": False,
        "install_path": install_path,
        "skill": skill,
        "tap": tap,
        "target_binding": target,
        "proof_boundary": (
            "Plan mode does not touch the current Hermes profile and is not evidence that Hermes "
            "installed, loaded, or used OMH. Run with --live against the target profile for observed smoke evidence."
        ),
        "steps": [step.to_payload() for step in steps],
        "installed_command_smoke": command_smoke,
        "first_use_status_smoke": first_use_status_smoke_plan(
            omh_command=omh_command,
            omh_home=target["omh_home"],
            hermes_home=target["hermes_home"],
        ),
        "live_command": _live_smoke_command(install_path, target),
    }


def installed_command_smoke_plan(
    *,
    omh_command: str = "omh",
    omh_home: str | Path | None = None,
    hermes_home: str | Path | None = None,
) -> dict[str, object]:
    target = _target_binding(omh_home=omh_home, hermes_home=hermes_home)
    steps = [
        HermesSmokeStep(
            "installed_omh_help",
            (omh_command, "--help"),
            "verify",
            False,
            proof_boundary="Verifies the installed OMH console script is importable and runnable from the current PATH.",
        ),
        HermesSmokeStep(
            "installed_omh_setup_plan",
            _omh_release_plan_command(
                omh_command,
                install_path="setup",
                omh_home=target["omh_home"],
                hermes_home=target["hermes_home"],
            ),
            "verify",
            False,
            proof_boundary=(
                "Verifies the installed OMH console script can render the setup-path Hermes smoke plan. "
                "This is still plan evidence, not live Hermes profile mutation."
            ),
        ),
    ]
    return {
        "schema_version": INSTALLED_COMMAND_SMOKE_SCHEMA,
        "mode": "plan",
        "ok": True,
        "observed": False,
        "command_under_test": omh_command,
        "target_binding": target,
        "proof_boundary": (
            "Plan mode lists installed-command checks only. Run release hermes-smoke with "
            "--include-command-smoke to observe the installed OMH executable."
        ),
        "steps": [step.to_payload() for step in steps],
    }


def first_use_status_smoke_plan(
    *,
    omh_command: str = "omh",
    omh_home: str | Path | None = None,
    hermes_home: str | Path | None = None,
    message: str = DEFAULT_FIRST_USE_MESSAGE,
) -> dict[str, object]:
    target = _target_binding(omh_home=omh_home, hermes_home=hermes_home)
    session_id = "<session_id>"
    return {
        "schema_version": FIRST_USE_STATUS_SMOKE_SCHEMA,
        "mode": "plan",
        "ok": True,
        "observed": False,
        "example_message": message,
        "target_binding": target,
        "proof_boundary": (
            "This first-use smoke is fixture-backed guidance for wrapper/Hermes status UX. It does not prove "
            "a live chat selected OMH unless the wrapper records that chat response."
        ),
        "steps": [
            {
                "name": "chat_session_start",
                "command": list(
                    _omh_scoped_command(
                        omh_command,
                        "chat",
                        "session",
                        "start",
                        "--source",
                        "hermes",
                        "--source-event-id",
                        "release-smoke-message",
                        "--channel-ref",
                        "release-smoke",
                        message,
                        omh_home=target["omh_home"],
                        hermes_home=target["hermes_home"],
                    )
                ),
                "phase": "verify",
                "mutates_profile": False,
                "required": True,
                "expected": "Creates or resumes a metadata-only wrapper session and returns a status card without executor open/result actions.",
                "proof_boundary": "Starting a wrapper session is routing/status evidence only; it is not execution evidence.",
            },
            {
                "name": "chat_session_accept_plan",
                "command": list(
                    _omh_scoped_command(
                        omh_command,
                        "chat",
                        "session",
                        "accept-plan",
                        session_id,
                        omh_home=target["omh_home"],
                        hermes_home=target["hermes_home"],
                    )
                ),
                "phase": "verify",
                "mutates_profile": False,
                "required": True,
                "expected": "Records explicit plan acceptance before any coding handoff can be prepared.",
                "proof_boundary": "Plan acceptance is a wrapper decision; it is still not dispatch or execution evidence.",
            },
            {
                "name": "chat_session_select_executor",
                "command": list(
                    _omh_scoped_command(
                        omh_command,
                        "chat",
                        "session",
                        "select-executor",
                        session_id,
                        "codex",
                        omh_home=target["omh_home"],
                        hermes_home=target["hermes_home"],
                    )
                ),
                "phase": "verify",
                "mutates_profile": False,
                "required": True,
                "expected": "Records the selected coding agent before backend open/attach actions become visible.",
                "proof_boundary": "Executor selection is not executor dispatch; it only chooses the handoff target.",
            },
            {
                "name": "chat_session_prepare_handoff",
                "command": list(
                    _omh_scoped_command(
                        omh_command,
                        "chat",
                        "session",
                        "prepare-handoff",
                        session_id,
                        message,
                        omh_home=target["omh_home"],
                        hermes_home=target["hermes_home"],
                    )
                ),
                "phase": "verify",
                "mutates_profile": False,
                "required": True,
                "expected": "Prepares the coding handoff while keeping dispatch/result/verification not observed.",
                "proof_boundary": "A prepared handoff is not an observed executor open, result, review, CI, or merge.",
            },
            {
                "name": "chat_session_status_after_handoff",
                "command": list(
                    _omh_scoped_command(
                        omh_command,
                        "chat",
                        "session",
                        "status",
                        session_id,
                        omh_home=target["omh_home"],
                        hermes_home=target["hermes_home"],
                    )
                ),
                "phase": "verify",
                "mutates_profile": False,
                "required": True,
                "expected": "After plan acceptance, executor selection, and handoff preparation, status shows prepared handoff without observed dispatch/result.",
                "proof_boundary": "Prepared handoff status remains prepared_not_observed until dispatch/result evidence is recorded.",
            },
        ],
        "expected_status_boundary": {
            "before_handoff": {
                "executor_actions_visible": False,
                "forbidden_action_ids": [
                    "open_executor_session",
                    "attach_executor_session",
                    "record_executor_completed",
                    "record_executor_blocked",
                    "record_executor_failed",
                    "ask_hermes_verify",
                ],
            },
            "after_handoff": {
                "handoff": "prepared",
                "dispatch": "not_observed",
                "result": "not_observed",
                "verification": "not_requested",
            },
        },
    }


def run_hermes_release_smoke(
    *,
    install_path: str = "tap",
    skill: str = DEFAULT_HERMES_SKILL,
    tap: str = DEFAULT_HERMES_TAP,
    omh_command: str = "omh",
    omh_home: str | Path | None = None,
    hermes_home: str | Path | None = None,
    timeout_seconds: int = 30,
    runner: Runner | None = None,
    include_command_smoke: bool = False,
) -> dict[str, object]:
    if timeout_seconds < 1:
        raise ValueError("Hermes smoke timeout must be at least one second")
    target = _target_binding(omh_home=omh_home, hermes_home=hermes_home)
    steps = hermes_release_smoke_steps(
        install_path=install_path,
        skill=skill,
        tap=tap,
        omh_command=omh_command,
        omh_home=target["omh_home"],
        hermes_home=target["hermes_home"],
    )
    execute = runner or _subprocess_runner
    command_smoke = (
        run_installed_command_smoke(
            omh_command=omh_command,
            omh_home=target["omh_home"],
            hermes_home=target["hermes_home"],
            timeout_seconds=timeout_seconds,
            runner=execute,
        )
        if include_command_smoke
        else installed_command_smoke_plan(
            omh_command=omh_command,
            omh_home=target["omh_home"],
            hermes_home=target["hermes_home"],
        )
    )
    hermes_path = shutil.which("hermes")
    results: list[dict[str, object]] = []
    smoke_env = {"HERMES_HOME": str(target["hermes_home"])}
    if not hermes_path:
        return {
            "schema_version": HERMES_SMOKE_SCHEMA,
            "mode": "live",
            "ok": False,
            "observed": False,
            "install_path": install_path,
            "skill": skill,
            "tap": tap,
            "target_binding": target,
            "hermes_cli": {"found": False, "path": None},
            "results": [],
            "installed_command_smoke": command_smoke,
            "first_use_status_smoke": first_use_status_smoke_plan(
                omh_command=omh_command,
                omh_home=target["omh_home"],
                hermes_home=target["hermes_home"],
            ),
            "failed_step": "hermes_cli",
            "recommended_next_action": "Install Hermes Agent CLI or run this smoke from the target Hermes profile.",
            "proof_boundary": "No Hermes CLI was observed, so no Hermes install, list, check, or inspect evidence exists.",
        }
    ok = True
    failed_step = ""
    for step in steps:
        result = execute(step.command, timeout_seconds, smoke_env)
        step_ok = result.returncode == 0
        ok = ok and step_ok
        results.append(
            {
                **step.to_payload(),
                "returncode": result.returncode,
                "ok": step_ok,
                "environment": {"HERMES_HOME": smoke_env["HERMES_HOME"]},
                "stdout_excerpt": _bounded_text(result.stdout),
                "stderr_excerpt": _bounded_text(result.stderr),
            }
        )
        if not step_ok and not failed_step:
            failed_step = step.name
            if step.required:
                break
    if include_command_smoke and not bool(command_smoke.get("ok", False)):
        ok = False
        if not failed_step:
            failed_step = "installed_command_smoke"
    return {
        "schema_version": HERMES_SMOKE_SCHEMA,
        "mode": "live",
        "ok": ok,
        "observed": bool(results),
        "install_path": install_path,
        "skill": skill,
        "tap": tap,
        "target_binding": target,
        "hermes_cli": {"found": True, "path": hermes_path},
        "results": results,
        "installed_command_smoke": command_smoke,
        "first_use_status_smoke": first_use_status_smoke_plan(
            omh_command=omh_command,
            omh_home=target["omh_home"],
            hermes_home=target["hermes_home"],
        ),
        "failed_step": failed_step,
        "recommended_next_action": _hermes_smoke_next_action(ok, failed_step),
        "proof_boundary": (
            "Live smoke observes Hermes CLI install/list/check/inspect command results only. "
            "It still does not prove a later chat session selected OMH unless that session is observed separately."
        ),
    }


def run_installed_command_smoke(
    *,
    omh_command: str = "omh",
    omh_home: str | Path | None = None,
    hermes_home: str | Path | None = None,
    timeout_seconds: int = 30,
    runner: Runner | None = None,
) -> dict[str, object]:
    if timeout_seconds < 1:
        raise ValueError("Installed command smoke timeout must be at least one second")
    plan = installed_command_smoke_plan(omh_command=omh_command, omh_home=omh_home, hermes_home=hermes_home)
    target = plan["target_binding"]
    execute = runner or _subprocess_runner
    results: list[dict[str, object]] = []
    ok = True
    failed_step = ""
    for raw_step in plan["steps"]:
        step = HermesSmokeStep(
            str(raw_step["name"]),
            tuple(str(part) for part in raw_step["command"]),
            str(raw_step["phase"]),
            bool(raw_step["mutates_profile"]),
            required=bool(raw_step["required"]),
            proof_boundary=str(raw_step["proof_boundary"]),
        )
        result = execute(step.command, timeout_seconds, None)
        step_ok = result.returncode == 0
        ok = ok and step_ok
        results.append(
            {
                **step.to_payload(),
                "returncode": result.returncode,
                "ok": step_ok,
                "stdout_excerpt": _bounded_text(result.stdout),
                "stderr_excerpt": _bounded_text(result.stderr),
            }
        )
        if not step_ok and not failed_step:
            failed_step = step.name
            if step.required:
                break
    return {
        "schema_version": INSTALLED_COMMAND_SMOKE_SCHEMA,
        "mode": "live",
        "ok": ok,
        "observed": bool(results),
        "command_under_test": omh_command,
        "target_binding": target,
        "results": results,
        "failed_step": failed_step,
        "recommended_next_action": _installed_command_smoke_next_action(ok, failed_step),
        "proof_boundary": (
            "Installed command smoke observes the OMH console script and plan rendering only. "
            "It does not mutate Hermes or prove live chat usage."
        ),
    }


def _subprocess_runner(command: Sequence[str], timeout_seconds: int, env: Mapping[str, str] | None = None) -> CommandResult:
    run_env = os.environ.copy()
    if env:
        run_env.update({key: str(value) for key, value in env.items()})
    try:
        completed = subprocess.run(
            list(command),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_seconds,
            check=False,
            env=run_env,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = _coerce_text(exc.stdout)
        stderr = _coerce_text(exc.stderr) or f"timed out after {timeout_seconds}s"
        return CommandResult(command, 124, stdout, stderr)
    except OSError as exc:
        return CommandResult(command, 127, "", str(exc))
    return CommandResult(command, completed.returncode, completed.stdout, completed.stderr)


def _coerce_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _bounded_text(value: str, limit: int = 1200) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 15].rstrip() + "\n...[truncated]"


def _target_binding(*, omh_home: str | Path | None = None, hermes_home: str | Path | None = None) -> dict[str, object]:
    omh = _expand_home(omh_home, "OMH_HOME", "~/.omh")
    hermes = _expand_home(hermes_home, "HERMES_HOME", "~/.hermes")
    return {
        "omh_home": str(omh),
        "hermes_home": str(hermes),
        "explicit_omh_home": omh_home is not None,
        "explicit_hermes_home": hermes_home is not None,
        "hermes_env_key": "HERMES_HOME",
        "proof_boundary": "Live smoke binds Hermes CLI subprocesses to this HERMES_HOME; it does not prove another profile was checked.",
    }


def _expand_home(value: str | Path | None, env_key: str, default: str) -> Path:
    source = str(value) if value is not None else os.environ.get(env_key, default)
    return Path(os.path.expandvars(source)).expanduser().resolve()


def _omh_scoped_command(
    omh_command: str,
    *command_parts: str,
    omh_home: str | Path | None = None,
    hermes_home: str | Path | None = None,
) -> tuple[str, ...]:
    command = list(_omh_base_command(omh_command, omh_home=omh_home, hermes_home=hermes_home))
    command.extend(command_parts)
    return tuple(command)


def _omh_base_command(
    omh_command: str,
    *,
    omh_home: str | Path | None = None,
    hermes_home: str | Path | None = None,
) -> tuple[str, ...]:
    command = [omh_command]
    if omh_home is not None:
        command.extend(["--omh-home", str(omh_home)])
    if hermes_home is not None:
        command.extend(["--hermes-home", str(hermes_home)])
    return tuple(command)


def _omh_release_plan_command(
    omh_command: str,
    *,
    install_path: str,
    omh_home: str | Path | None = None,
    hermes_home: str | Path | None = None,
) -> tuple[str, ...]:
    return (
        *_omh_base_command(omh_command, omh_home=omh_home, hermes_home=hermes_home),
        "release",
        "hermes-smoke",
        "--install-path",
        install_path,
        "--omh-command",
        omh_command,
    )


def _live_smoke_command(install_path: str, target: Mapping[str, object]) -> list[str]:
    command = ["omh"]
    if target["explicit_omh_home"]:
        command.extend(["--omh-home", str(target["omh_home"])])
    if target["explicit_hermes_home"]:
        command.extend(["--hermes-home", str(target["hermes_home"])])
    command.extend(["release", "hermes-smoke", "--install-path", install_path, "--live"])
    if not target["explicit_hermes_home"]:
        command.append("--target-confirmed")
    return command


def _hermes_smoke_next_action(ok: bool, failed_step: str) -> str:
    if ok:
        return "Restart or refresh Hermes Agent if required, then try the first OMH Hermes prompt and record the observed response."
    if failed_step == "tap_add":
        return "Check Hermes tap support, network access, and whether the tap is already configured; rerun the smoke after repair."
    if failed_step == "skill_install":
        return (
            "Check tap visibility and Hermes skill scan output, then rerun "
            "`hermes skills install rlaope/oh-my-hermes/skills/oh-my-hermes --yes`."
        )
    if failed_step == "omh_setup":
        return "Run `omh setup` manually and inspect `omh doctor` for blocking setup checks."
    if failed_step == "setup_doctor":
        return "Run `omh doctor` manually and repair the OMH-managed skill registration reported there."
    if failed_step == "installed_command_smoke":
        return "Repair the installed `omh` console script path, then rerun the smoke with --include-command-smoke."
    if failed_step in {"tap_list", "skills_list", "skill_check", "skill_inspect"}:
        return "Inspect the failing Hermes skills command output and confirm the target Hermes profile is the one OMH was installed into."
    return "Inspect the failed Hermes release smoke step and rerun after repair."


def _installed_command_smoke_next_action(ok: bool, failed_step: str) -> str:
    if ok:
        return "Installed `omh` command path is runnable; continue with Hermes profile smoke or release tagging."
    if failed_step == "installed_omh_help":
        return "Check PATH, package installation, and console-script importability for `omh`."
    if failed_step == "installed_omh_setup_plan":
        return "Run `omh release hermes-smoke --install-path setup` directly and inspect the console-script error."
    return "Inspect the failed installed command smoke step and rerun after repair."
