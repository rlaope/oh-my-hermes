"""Disposable per-arm Hermes homes for confirmed paired-run evaluation.

`omh coding paired-run dispatch --confirm-dispatch` is the only caller. Each
arm gets its own home under a fresh temporary root outside any Hermes
`profiles/` tree (Hermes reads a home below `profiles/` as a named profile):

- `config.yaml` names the model and provider. A custom provider is declared
  by base URL, API mode and the NAME of the environment variable that holds
  its key; the key itself only travels in process environments.
- The variant arm also gets the packaged OMH plugin, enabled in that config
  with its own disposable OMH home, and exactly its frozen `exposed_skills`.
  The baseline arm gets neither.
- A harness-owned `hermes gateway run --quiet` serves the home in its own
  process group, so Hermes never starts a service-manager job for it, and one
  untimed warm-up chat absorbs the home's first-start work before any cell's
  clock starts. Closing stops the whole group and removes the root.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import subprocess
import tempfile
import time
from importlib import resources
from typing import Final
from urllib.parse import urlsplit

from ._hermes_child_process import terminate_process_group
from .hermes_child_arm_setup import ArmSetup, PairedRunArmHome, observe_arm_setup
from .hermes_child_dispatch import (
    HermesChildDispatchError,
    HermesChildRequest,
    arm_gateway_env,
    dispatch_hermes_child,
    provider_env_names,
)

API_MODES: Final = ("chat_completions", "anthropic_messages", "codex_responses")
WARMUP_PROMPT: Final = "Reply with the single word READY."
_PROVIDER_NAME: Final = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_ENV_NAME: Final = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_LOOPBACK_NAMES: Final = frozenset({"localhost"})


class PairedRunArmHomeError(RuntimeError):
    """An arm home could not be prepared, warmed, or proven clean."""


@dataclass(frozen=True, slots=True)
class PairedRunProviderConfig:
    """A custom Hermes provider declared without its secret."""

    name: str
    base_url: str
    api_mode: str
    key_env: str


def validate_provider_config(
    name: str,
    base_url: str,
    api_mode: str,
    key_env: str,
    *,
    env: Mapping[str, str] | None = None,
) -> PairedRunProviderConfig | None:
    """Return the declared custom provider, or None when none was declared.

    Refuses a partial declaration, a URL carrying credentials or a query, plain
    HTTP to anything but a loopback host, an unknown API mode, and a key
    "name" that is not an environment-variable name (an inline key).
    """
    given = [bool(value.strip()) for value in (base_url, api_mode, key_env)]
    if not any(given):
        return None
    if not all(given):
        raise PairedRunArmHomeError(
            "a custom provider needs --provider-base-url, --provider-api-mode and --provider-key-env together"
        )
    if _PROVIDER_NAME.fullmatch(name) is None:
        raise PairedRunArmHomeError("--provider must be a plain provider name for a custom provider")
    if _ENV_NAME.fullmatch(key_env) is None:
        raise PairedRunArmHomeError(
            "--provider-key-env must name an environment variable (A-Z, 0-9, _), never hold a key"
        )
    source = os.environ if env is None else env
    if not source.get(key_env):
        raise PairedRunArmHomeError(f"--provider-key-env {key_env} is not set in this environment; export it first")
    if api_mode not in API_MODES:
        raise PairedRunArmHomeError("--provider-api-mode must be one of " + ", ".join(API_MODES))
    parts = urlsplit(base_url)
    if parts.username is not None or parts.password is not None or parts.query or parts.fragment:
        raise PairedRunArmHomeError("--provider-base-url must not carry credentials, a query, or a fragment")
    host = parts.hostname or ""
    if parts.scheme == "https" and host:
        return PairedRunProviderConfig(name, base_url, api_mode, key_env)
    if parts.scheme == "http" and _is_loopback(host):
        return PairedRunProviderConfig(name, base_url, api_mode, key_env)
    raise PairedRunArmHomeError("--provider-base-url must be https, or http only to a loopback host")


def _is_loopback(host: str) -> bool:
    if host.lower() in _LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def arm_root_parent(candidates: tuple[str, ...] | None = None) -> Path:
    """The first temporary directory with no `profiles` ancestor."""
    for raw in candidates or (tempfile.gettempdir(), "/private/tmp", "/tmp"):
        path = Path(raw)
        try:
            resolved = path.resolve(strict=True)
        except OSError:
            continue
        if resolved.is_dir() and "profiles" not in resolved.parts:
            return resolved
    raise PairedRunArmHomeError("no temporary directory outside a Hermes profiles tree is available")


@dataclass(slots=True)
class ArmHomeRun:
    """A prepared, warmed arm home and the gateway this invocation owns."""

    arm_home: PairedRunArmHome
    process: subprocess.Popen[bytes] | None
    gateway_ready_seconds: float = 0.0
    warmup_seconds: float = 0.0
    setup: ArmSetup | None = None
    closed: bool = field(default=False)

    def record(self) -> dict[str, object]:
        setup = self.setup.to_record() if self.setup is not None else None
        return {
            "gateway_ready_seconds": round(self.gateway_ready_seconds, 3),
            "warmup_seconds": round(self.warmup_seconds, 3),
            "arm_setup": setup,
        }

    def close(self, grace: float = 5.0) -> bool:
        """Stop the gateway's whole process group, then remove the root."""
        if self.closed:
            return True
        stopped = True
        if self.process is not None:
            _sent, stopped = terminate_process_group(self.process, grace, _SIGTERM)
        shutil.rmtree(self.arm_home.root, ignore_errors=True)
        self.closed = True
        return stopped and not self.arm_home.root.exists()


_SIGTERM: Final = 15


def prepare_arm_home(
    role: str,
    *,
    provider: str,
    model: str,
    reasoning: str,
    hermes: str,
    provider_config: PairedRunProviderConfig | None,
    exposed_skills: tuple[str, ...],
    omh_plugin: bool,
    parent: Path | None = None,
    ready_seconds: float = 300.0,
    warmup_timeout_seconds: float = 900.0,
    env: Mapping[str, str] | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> ArmHomeRun:
    """Materialize, start, and warm one arm home; the caller must close it."""
    root = Path(tempfile.mkdtemp(prefix=f"omh-paired-{role}-", dir=parent or arm_root_parent()))
    os.chmod(root, 0o700)
    hermes_home, home, omh_home, tmp = root / "hermes", root / "home", root / "omh", root / "tmp"
    for directory in (hermes_home, home, omh_home, tmp):
        directory.mkdir(mode=0o700)
    run = ArmHomeRun(
        PairedRunArmHome(root, hermes_home, home, (), ()),
        None,
    )
    prepared = False
    try:
        labels = _materialize(hermes_home, omh_home, provider, model, provider_config, exposed_skills, omh_plugin)
        key_names = (provider_config.key_env,) if provider_config else provider_env_names(provider)
        source = os.environ if env is None else env
        gateway_env = arm_gateway_env(source, hermes_home, home, tmp, key_names)
        started = clock()
        process = subprocess.Popen(
            (hermes, "gateway", "run", "--quiet"),
            cwd=root,
            env=gateway_env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            **_process_group_options(),
        )
        run.process = process
        arm_home = PairedRunArmHome(root, hermes_home, home, key_names, labels)
        run.arm_home = arm_home
        _await_ready(process, hermes_home / "gateway.pid", ready_seconds, clock)
        run.gateway_ready_seconds = clock() - started
        warm_started = clock()
        result = dispatch_hermes_child(
            HermesChildRequest(
                prompt=WARMUP_PROMPT,
                model=model,
                provider=provider,
                reasoning=reasoning,
                parent_run_id=f"paired-warmup-{role}",
                run_id=f"paired-warmup-{role}-{secrets.token_hex(4)}",
                timeout_seconds=warmup_timeout_seconds,
                hermes=hermes,
                cwd=root,
                env=source,
                allow_parallel=True,
                arm_home=arm_home,
            ),
            dispatch_policy="ask_before_dispatch",
            confirmed=True,
        )
        run.warmup_seconds = clock() - warm_started
        if result.status != "completed":
            tail = result.stderr.strip()[-300:] or result.stdout.strip()[-300:]
            raise PairedRunArmHomeError(
                f"{role} arm warm-up chat {result.status} (exit {result.exit_code}): {tail}"
            )
        run.setup = observe_arm_setup(arm_home)
        prepared = True
        return run
    except (HermesChildDispatchError, OSError, ValueError) as exc:
        raise PairedRunArmHomeError(f"{role} arm home could not be prepared ({type(exc).__name__}: {exc})") from exc
    finally:
        # Any failure, an interrupt included, stops the gateway group and
        # removes the root before the error leaves.
        if not prepared:
            run.close()


def _await_ready(
    process: subprocess.Popen[bytes],
    pid_file: Path,
    bound: float,
    clock: Callable[[], float],
) -> None:
    deadline = clock() + bound
    while not pid_file.is_file():
        if process.poll() is not None:
            raise PairedRunArmHomeError(f"arm gateway exited with status {process.returncode} before it was ready")
        if clock() >= deadline:
            raise PairedRunArmHomeError(f"arm gateway was not ready within {bound:g}s")
        time.sleep(0.1)


def _process_group_options() -> dict[str, object]:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _materialize(
    hermes_home: Path,
    omh_home: Path,
    provider: str,
    model: str,
    provider_config: PairedRunProviderConfig | None,
    exposed_skills: tuple[str, ...],
    omh_plugin: bool,
) -> tuple[tuple[str, str], ...]:
    config: dict[str, object] = {"model": {"default": model, "provider": provider}}
    if provider_config is not None:
        config["providers"] = {
            provider_config.name: {
                "base_url": provider_config.base_url,
                "api_mode": provider_config.api_mode,
                "key_env": provider_config.key_env,
                "models": {model: {}},
            }
        }
    if omh_plugin:
        config["plugins"] = {
            "enabled": ["omh"],
            "entries": {"omh": {"settings": {"omh_home": str(omh_home)}}},
        }
        _copy_plugin(resources.files("omh.plugin_bundle.omh"), hermes_home / "plugins" / "omh")
    # JSON is valid YAML; Hermes reads it as its config.yaml.
    (hermes_home / "config.yaml").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return _write_skills(hermes_home / "skills", exposed_skills)


def _copy_plugin(source: object, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():  # type: ignore[attr-defined]
        if item.name == "__pycache__" or item.name.endswith(".pyc"):
            continue
        if item.is_dir():
            _copy_plugin(item, target / item.name)
        elif item.is_file():
            (target / item.name).write_bytes(item.read_bytes())


def _write_skills(skills_dir: Path, names: tuple[str, ...]) -> tuple[tuple[str, str], ...]:
    from ..catalogs.skill_display_names import omh_skill_display_name
    from ..skills.packaging import builtin_skill_reference_templates, builtin_skill_templates
    from ..skills.support_files import builtin_skill_support_templates

    templates = {template.name: template for template in builtin_skill_templates()}
    unknown = sorted(set(names) - set(templates))
    if unknown:
        raise PairedRunArmHomeError("exposed_skills are not packaged OMH skills: " + ", ".join(unknown))
    skills_dir.mkdir(parents=True, exist_ok=True)
    labels: list[tuple[str, str]] = []
    wanted = set(names)
    for name in sorted(wanted):
        label = omh_skill_display_name(name)
        (skills_dir / label).mkdir()
        (skills_dir / label / "SKILL.md").write_text(templates[name].content, encoding="utf-8")
        labels.append((label, name))
    extras = [
        *(item for item in builtin_skill_reference_templates() if item.skill_name in wanted),
        *(item for item in builtin_skill_support_templates() if item.skill_name in wanted),
    ]
    for item in extras:
        relative = PurePosixPath(item.relative_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise PairedRunArmHomeError(f"unsafe packaged skill path: {item.relative_path}")
        target = skills_dir / omh_skill_display_name(item.skill_name) / Path(*relative.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(item.content, encoding="utf-8")
    return tuple(labels)
