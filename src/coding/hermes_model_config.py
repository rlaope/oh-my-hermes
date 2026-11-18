"""Local-only Hermes model-alias configuration adapter.

The adapter delegates all configuration interpretation and writes to Hermes'
own ``config`` and ``auth`` commands. It never invokes ``hermes model``, reads
Hermes' dotenv file, or performs network I/O. For a ``providers:`` entry it
checks only whether the key variable that entry names is set, never its value.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from threading import Lock
from typing import Final, Mapping
from urllib.parse import urlsplit

from ..system.metadata_safety import is_secret_value_shaped, is_sensitive_metadata_text


_ALIAS_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_-]+$")
# `hermes auth list` heads each pool with `<id> (N credentials):`. A legacy
# `custom_providers:` entry's pool id is composed as `custom:<name>`
# (agent/credential_pool.py CUSTOM_POOL_PREFIX); only that one colon form is read.
_AUTH_PROVIDER_RE: Final[re.Pattern[str]] = re.compile(
    r"^([A-Za-z0-9_-]+|custom:[A-Za-z0-9_.-]+) \("
)
_CUSTOM_PROVIDER_NAME_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_.-]+$")
_CUSTOM_POOL_PREFIX: Final = "custom:"
# An environment variable *name* (`key_env`); never its value.
_ENV_NAME_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
# A name safe to print back: UPPER_SNAKE with at least one underscore (`MISTRAL_API_KEY`).
_ECHOABLE_ENV_NAME_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+$")
_FALSE_WORDS: Final = frozenset({"false", "0", "no", "off"})
# Hosts whose key Hermes reads from a fixed variable rather than the
# host-derived `<VENDOR>_API_KEY` (hermes_cli/runtime_provider.py
# `_host_gated_env_key_candidates`).
_HOST_GATED_KEY_ENV: Final = (
    ("openai.com", "OPENAI_API_KEY"),
    ("openai.azure.com", "OPENAI_API_KEY"),
    ("openrouter.ai", "OPENROUTER_API_KEY"),
)
_COMMAND_TIMEOUT_SECONDS: Final = 10
_APPLY_LOCK: Final = Lock()
_ALIAS_KEY_PREFIX: Final = "model.aliases."
_FALLBACK_KEY: Final = "fallback_model"
# Hermes' current fallback chain (hermes_cli/fallback_config.py `get_fallback_chain`
# reads it first, then legacy `fallback_model` entries not already present);
# Hermes' own writer (`hermes fallback`) stores only this key.
_FALLBACK_PROVIDERS_KEY: Final = "fallback_providers"
# The only entry fields OMH replays on rollback. `config get` masks
# credential-shaped values, so an entry carrying any other field cannot be
# restored from what OMH read, and the write is refused before it starts.
_RESTORABLE_FALLBACK_FIELDS: Final = frozenset({"provider", "model", "base_url", "api_mode"})
_UNRESTORABLE_FALLBACK_MESSAGE: Final = (
    "Your current fallback chain has fields OMH cannot restore safely; change it with "
    "`hermes fallback` (list / remove / clear / add) instead."
)


class HermesModelConfigError(RuntimeError):
    """Base error for deterministic Hermes model configuration operations."""


class AliasCollisionError(HermesModelConfigError):
    """Raised when a preview would replace an existing alias by default."""


class ConfirmationRequiredError(HermesModelConfigError):
    """Raised when mutation was not explicitly confirmed."""


class ConfigDigestMismatchError(HermesModelConfigError):
    """Raised when compare-and-swap detects configuration drift."""


class HermesCommandError(HermesModelConfigError):
    """Raised when a required local Hermes command fails."""


class HermesConfigUnreadableError(HermesCommandError):
    """Raised when the config file Hermes names cannot be read.

    `missing` is True only when the file does not exist; a file that exists
    but cannot be read (permissions, a directory in its place) is not
    something a later setup run creates.
    """

    def __init__(self, config_path: Path, *, missing: bool) -> None:
        super().__init__(f"cannot read Hermes config at {config_path}")
        self.config_path = config_path
        self.missing = missing


class HermesUnavailableError(HermesCommandError):
    """Raised when the Hermes executable is not found, so no command could run."""


class HermesVerificationError(HermesModelConfigError):
    """Raised when post-write inspection does not match the preview."""


@dataclass(frozen=True, slots=True)
class ProviderPresence:
    provider_id: str
    auth_present: bool
    auth_status_ok: bool
    plugin_present: bool
    # True when the id names an enabled entry under Hermes `providers:`; its
    # credential then counts toward `auth_present` when observable.
    provider_entry: bool = False
    # The environment variable *name* that entry's key is read from, if known.
    credential_env: str | None = None


@dataclass(frozen=True, slots=True)
class _ProviderEntry:
    canonical: str
    ids: frozenset[str]
    pool_ids: frozenset[str]
    credential_env: str | None


@dataclass(frozen=True, slots=True)
class HermesModelConfigInspection:
    hermes: str
    config_path: Path
    config_digest: str
    config_check_ok: bool
    model_aliases: Mapping[str, str]
    model_dot_aliases: Mapping[str, str]
    providers: tuple[ProviderPresence, ...]
    commands: tuple[tuple[str, ...], ...]
    # The configured main model as `provider/model` (the bare model id when no
    # provider is set), "" when unreadable or unsafe to echo.
    main_model: str = ""
    # Hermes' `fallback_model` and `fallback_providers` as `config get`
    # returned them: None, one `{provider, model}` dict, or a list of them.
    # Never printed or serialized whole; only `fallback_entries` /
    # `effective_fallback_entries` render them.
    fallback_model: object = dataclass_field(default=None, repr=False)
    fallback_providers: object = dataclass_field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class HermesModelConfigPreview:
    hermes: str
    config_path: Path
    config_digest: str
    before_aliases: Mapping[str, str]
    changes: Mapping[str, str | None]
    commands: tuple[tuple[str, ...], ...]
    # The one `provider/model` the preview writes as `fallback_model`, or None
    # when the run does not touch it.
    fallback: str | None = None
    before_fallback: object = dataclass_field(default=None, repr=False)
    before_fallback_providers: object = dataclass_field(default=None, repr=False)

    @property
    def alias_commands(self) -> tuple[tuple[str, ...], ...]:
        return tuple(command for command in self.commands if _is_alias_command(command))

    @property
    def fallback_commands(self) -> tuple[tuple[str, ...], ...]:
        return tuple(command for command in self.commands if not _is_alias_command(command))

    @property
    def before_fallback_chain(self) -> tuple[str, ...]:
        """The effective fallback chain before the write, in Hermes' order."""
        return effective_fallback_entries(self.before_fallback_providers, self.before_fallback)

    @property
    def fallback_replaces_chain(self) -> bool:
        """True when the write replaces a chain of several entries with one."""
        return (
            self.fallback is not None
            and bool(self.fallback_commands)
            and len(_effective_chain(self.before_fallback_providers, self.before_fallback)) > 1
        )


@dataclass(frozen=True, slots=True)
class HermesModelConfigReceipt:
    verified: bool
    before_digest: str
    after_digest: str
    commands: tuple[tuple[str, ...], ...]
    inspection: HermesModelConfigInspection


def inspect_hermes_model_config(
    *,
    hermes: str = "hermes",
    env: Mapping[str, str] | None = None,
) -> HermesModelConfigInspection:
    """Inspect aliases, auth presence/status, and provider plugins locally."""
    commands: list[tuple[str, ...]] = []
    config_path = Path(_required_output((hermes, "config", "path"), env, commands)).expanduser()
    digest = _config_digest(config_path)
    model_aliases = _optional_json_mapping(
        (hermes, "config", "get", "model_aliases", "--json"), env, commands
    )
    model_dot_aliases = _optional_json_mapping(
        (hermes, "config", "get", "model.aliases", "--json"), env, commands
    )
    provider = _optional_json_value(
        (hermes, "config", "get", "model.provider", "--json"), env, commands
    )
    main_model = _optional_json_value((hermes, "config", "get", "model", "--json"), env, commands)
    fallback_model = _optional_json_value(
        (hermes, "config", "get", _FALLBACK_KEY, "--json"), env, commands
    )
    fallback_providers = _optional_json_value(
        (hermes, "config", "get", _FALLBACK_PROVIDERS_KEY, "--json"), env, commands
    )
    plugins = _optional_json_value(
        (hermes, "config", "get", "plugins", "--json"), env, commands
    )
    custom_providers = _optional_json_value(
        (hermes, "config", "get", "custom_providers", "--json"), env, commands
    )
    provider_entries = _provider_entries(
        _optional_json_value((hermes, "config", "get", "providers", "--json"), env, commands)
    )
    check = _run((hermes, "config", "check"), env, commands)
    auth_list = _run((hermes, "auth", "list"), env, commands)

    pool_ids = _auth_provider_ids(auth_list.stdout if auth_list.returncode == 0 else "")
    auth_providers = _configured_auth_provider_ids(
        pool_ids,
        _custom_provider_names(custom_providers),
    )
    plugin_providers = _plugin_provider_ids(plugins)
    entry_by_id = {
        provider_id: entry for entry in provider_entries for provider_id in entry.ids
    }
    providers = set(auth_providers) | plugin_providers | set(entry_by_id)
    if isinstance(provider, str) and _safe_metadata(provider):
        providers.add(provider)
    providers.update(_alias_provider_ids(model_aliases))
    providers.update(_alias_provider_ids(model_dot_aliases))

    presence: list[ProviderPresence] = []
    statuses: dict[str, bool] = {}
    for provider_id in sorted(providers):
        entry = entry_by_id.get(provider_id)
        # Every spelling of one `providers:` entry resolves to the same
        # Hermes provider, so its auth status is asked once.
        status_id = provider_id if entry is None else entry.canonical
        if status_id not in statuses:
            status = _run((hermes, "auth", "status", status_id), env, commands)
            statuses[status_id] = status.returncode == 0
        entry_credential = entry is not None and (
            bool(entry.pool_ids & pool_ids) or _env_var_present(env, entry.credential_env)
        )
        presence.append(
            ProviderPresence(
                provider_id=provider_id,
                auth_present=provider_id in auth_providers or entry_credential,
                auth_status_ok=statuses[status_id],
                plugin_present=provider_id in plugin_providers,
                provider_entry=entry is not None,
                credential_env=None if entry is None else entry.credential_env,
            )
        )
    return HermesModelConfigInspection(
        hermes=hermes,
        config_path=config_path,
        config_digest=digest,
        config_check_ok=check.returncode == 0,
        model_aliases=model_aliases,
        model_dot_aliases=model_dot_aliases,
        providers=tuple(presence),
        commands=tuple(commands),
        main_model=_main_model_ref(main_model, provider),
        fallback_model=fallback_model,
        fallback_providers=fallback_providers,
    )


def preview_hermes_model_config(
    inspection: HermesModelConfigInspection,
    changes: Mapping[str, str | None],
    *,
    allow_collisions: bool = False,
    fallback: str | None = None,
) -> HermesModelConfigPreview:
    """Build exact nested-alias Hermes commands without executing them.

    `fallback` is one `provider/model` that becomes Hermes' whole fallback
    chain (`fallback_providers`, the legacy `fallback_model` dropped); it is
    previewed beside the alias changes and bound to the same config digest.
    """
    if not inspection.config_check_ok:
        raise HermesModelConfigError("Hermes config check failed; mutation preview refused")
    commands: list[tuple[str, ...]] = []
    normalized: dict[str, str | None] = {}
    for alias in sorted(changes):
        if not _ALIAS_RE.fullmatch(alias) or not _safe_metadata(alias):
            raise HermesModelConfigError(f"unsupported Hermes model alias: {alias!r}")
        target = changes[alias]
        existing = inspection.model_dot_aliases.get(alias)
        if target is not None and existing is not None and existing != target and not allow_collisions:
            raise AliasCollisionError(
                f"Hermes model alias {alias!r} already points to {existing!r}; collision refused"
            )
        if target is not None:
            _require_target_auth(inspection, target)
        normalized[alias] = target
        key = f"{_ALIAS_KEY_PREFIX}{alias}"
        if target is None:
            commands.append((inspection.hermes, "config", "unset", key))
        elif existing != target:
            commands.append((inspection.hermes, "config", "set", key, target))
    if fallback is not None:
        # The configured main model, and the `main` alias as this run leaves it.
        main_refs = (
            inspection.main_model,
            normalized.get("main", inspection.model_dot_aliases.get("main")) or "",
        )
        commands.extend(_fallback_commands(inspection, fallback, main_refs))
    return HermesModelConfigPreview(
        hermes=inspection.hermes,
        config_path=inspection.config_path,
        config_digest=inspection.config_digest,
        before_aliases=dict(inspection.model_dot_aliases),
        changes=normalized,
        commands=tuple(commands),
        fallback=fallback,
        before_fallback=inspection.fallback_model,
        before_fallback_providers=inspection.fallback_providers,
    )


def split_fallback_target(target: str) -> tuple[str, str]:
    """`provider/model` as the two `fallback_model` fields; the model may hold slashes."""
    provider, separator, model = str(target or "").partition("/")
    if (
        not separator
        or not provider
        or not model
        or any(character.isspace() for character in target)
        or not _safe_metadata(target)
    ):
        raise HermesModelConfigError(
            f"Hermes fallback model {target!r} must be a safe <provider>/<model> identifier"
        )
    return provider, model


def fallback_entries(value: object) -> tuple[str, ...]:
    """The `provider/model` of each entry in a `fallback_model` value, for display.

    Entries that are not a dict with string provider and model, or whose text is
    not safe metadata, are left out: the value is never echoed whole.
    """
    items = value if isinstance(value, list) else [value]
    entries: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        provider, model = item.get("provider"), item.get("model")
        if isinstance(provider, str) and isinstance(model, str) and provider and model:
            ref = f"{provider}/{model}"
            if _safe_metadata(ref):
                entries.append(ref)
    return tuple(entries)


def effective_fallback_entries(providers: object, legacy: object) -> tuple[str, ...]:
    """Hermes' effective fallback chain as `provider/model`, for display.

    `fallback_providers` first, then legacy `fallback_model` entries not
    already present, as Hermes' `get_fallback_chain` merges them.
    """
    return fallback_entries(_effective_chain(providers, legacy))


def _chain_items(value: object) -> list[object]:
    if value is None:
        return []
    return list(value) if isinstance(value, list) else [value]


def _effective_chain(providers: object, legacy: object) -> list[dict[str, object]]:
    chain: list[dict[str, object]] = []
    seen: set[tuple[str, str, str]] = set()
    for value in (providers, legacy):
        for item in _chain_items(value):
            if not isinstance(item, dict):
                continue
            provider = str(item.get("provider") or "").strip()
            model = str(item.get("model") or "").strip()
            if not provider or not model:
                continue
            base_url = str(item.get("base_url") or "").strip().rstrip("/")
            identity = (provider.casefold(), model.casefold(), base_url.casefold())
            if identity not in seen:
                seen.add(identity)
                chain.append({**item, "provider": provider, "model": model})
    return chain


def _fallback_restorable(value: object) -> bool:
    """Whether every entry of a fallback key can be replayed exactly from what was read."""
    for item in _chain_items(value):
        if not isinstance(item, dict) or not set(item) <= _RESTORABLE_FALLBACK_FIELDS:
            return False
        if not all(isinstance(field, str) and _safe_metadata(field) for field in item.values()):
            return False
    return value is None or isinstance(value, (dict, list))


def _fallback_literal(value: object) -> str:
    # JSON is a YAML flow literal; Hermes' `config set` parses it with yaml.safe_load.
    return json.dumps(value)


def _fallback_commands(
    inspection: HermesModelConfigInspection, target: str, main_refs: tuple[str, ...]
) -> list[tuple[str, ...]]:
    provider, model = split_fallback_target(target)
    _require_target_auth(inspection, target)
    if any(ref and ref.casefold() == target.casefold() for ref in main_refs):
        raise HermesModelConfigError(
            f"Hermes fallback model {target!r}: fallback is the same as the main model"
        )
    if not (
        _fallback_restorable(inspection.fallback_providers)
        and _fallback_restorable(inspection.fallback_model)
    ):
        raise HermesModelConfigError(_UNRESTORABLE_FALLBACK_MESSAGE)
    entry = {"provider": provider, "model": model}
    if _effective_chain(inspection.fallback_providers, inspection.fallback_model) == [entry]:
        return []
    hermes = inspection.hermes
    # One fallback replaces the whole chain in Hermes' own shape: one atomic
    # `fallback_providers` list, then the legacy key dropped. Never appends.
    commands: list[tuple[str, ...]] = [
        (hermes, "config", "set", _FALLBACK_PROVIDERS_KEY, _fallback_literal([entry]))
    ]
    if inspection.fallback_model is not None:
        commands.append((hermes, "config", "unset", _FALLBACK_KEY))
    return commands


def _is_alias_command(command: tuple[str, ...]) -> bool:
    return len(command) > 3 and command[3].startswith(_ALIAS_KEY_PREFIX)


def _main_model_ref(model: object, provider: object) -> str:
    """The main model as `provider/model`, or "" when it cannot be named safely."""
    if isinstance(model, dict):
        model_id = next(
            (
                value.strip()
                for name in ("default", "model")
                if isinstance(value := model.get(name), str) and value.strip()
            ),
            "",
        )
    elif isinstance(model, str):
        model_id = model.strip()
    else:
        model_id = ""
    if not model_id:
        return ""
    ref = f"{provider}/{model_id}" if isinstance(provider, str) and provider else model_id
    return ref if _safe_metadata(ref) else ""


def apply_hermes_model_config(
    preview: HermesModelConfigPreview,
    *,
    confirmed: bool,
    expected_config_digest: str,
    env: Mapping[str, str] | None = None,
) -> HermesModelConfigReceipt:
    """Apply a confirmed digest-bound preview and verify the resulting aliases."""
    if not confirmed:
        raise ConfirmationRequiredError("Hermes model config apply requires explicit confirmation")
    if expected_config_digest != preview.config_digest:
        raise ConfigDigestMismatchError("expected digest does not match the preview digest")
    with _APPLY_LOCK:
        inspection = _apply_locked(preview, env)
    for alias, target in preview.changes.items():
        observed = inspection.model_dot_aliases.get(alias)
        if target is None and observed is not None:
            raise HermesVerificationError(f"Hermes alias {alias!r} remained after unset")
        if target is not None and observed != target:
            raise HermesVerificationError(
                f"Hermes alias {alias!r} verification mismatch: expected {target!r}, got {observed!r}"
            )
    if preview.fallback is not None and not _fallback_matches(
        inspection.fallback_providers, inspection.fallback_model, preview.fallback
    ):
        raise HermesVerificationError(
            f"Hermes fallback_model verification mismatch: expected {preview.fallback!r}"
        )
    return HermesModelConfigReceipt(
        verified=True,
        before_digest=preview.config_digest,
        after_digest=inspection.config_digest,
        commands=preview.commands,
        inspection=inspection,
    )


def _apply_locked(
    preview: HermesModelConfigPreview,
    env: Mapping[str, str] | None,
) -> HermesModelConfigInspection:
    expected_digest = preview.config_digest
    attempted: list[str] = []
    in_fallback = False
    try:
        for command in preview.alias_commands:
            if _config_digest(preview.config_path) != expected_digest:
                raise ConfigDigestMismatchError(
                    "Hermes config changed during apply; remaining mutations refused"
                )
            alias = command[3].removeprefix(_ALIAS_KEY_PREFIX)
            result = _run(command, env)
            if result.returncode != 0:
                observed = _optional_json_mapping(
                    (preview.hermes, "config", "get", "model.aliases", "--json"),
                    env,
                    [],
                )
                target = preview.changes[alias]
                mutation_is_owned = (
                    alias not in observed
                    if target is None
                    else observed.get(alias) == target
                )
                if mutation_is_owned:
                    attempted.append(alias)
                    expected_digest = _config_digest(preview.config_path)
                raise HermesCommandError(
                    f"Hermes config command failed ({result.returncode}): {' '.join(command[1:])}"
                )
            attempted.append(alias)
            expected_digest = _config_digest(preview.config_path)
            _require_expected_alias_state(preview, attempted, env)
        if preview.fallback_commands:
            in_fallback = True
            _apply_fallback(preview, env, expected_digest)
        return inspect_hermes_model_config(hermes=preview.hermes, env=env)
    except HermesModelConfigError:
        if in_fallback:
            # `_apply_fallback` restored its own writes before re-raising, which
            # can reformat the file; the alias rollback checks against that.
            expected_digest = _config_digest(preview.config_path)
        _rollback_aliases(
            preview,
            attempted,
            env,
            expected_config_digest=expected_digest,
        )
        raise


def _apply_fallback(
    preview: HermesModelConfigPreview,
    env: Mapping[str, str] | None,
    expected_digest: str,
) -> None:
    """Run the fallback commands and verify the effective chain; on any failure restore, then re-raise."""
    try:
        for command in preview.fallback_commands:
            if _config_digest(preview.config_path) != expected_digest:
                raise ConfigDigestMismatchError(
                    "Hermes config changed during apply; remaining mutations refused"
                )
            result = _run(command, env)
            if result.returncode != 0:
                # A failed command may still have written; the rollback below
                # decides from the observed value, so the digest is re-read first.
                expected_digest = _require_owned_fallback(preview, env, expected_digest)
                raise HermesCommandError(
                    f"Hermes config command failed ({result.returncode}): {' '.join(command[1:])}"
                )
            expected_digest = _require_owned_fallback(preview, env, expected_digest)
        providers, legacy = _observed_fallback(preview, env)
        if not _fallback_matches(providers, legacy, preview.fallback or ""):
            raise HermesVerificationError(
                f"Hermes fallback chain verification mismatch: expected only {preview.fallback!r}"
            )
    except HermesModelConfigError:
        _rollback_fallback(preview, env, expected_digest)
        raise


def _observed_fallback(
    preview: HermesModelConfigPreview, env: Mapping[str, str] | None
) -> tuple[object, object]:
    """`(fallback_providers, fallback_model)` as Hermes reports them now."""
    return (
        _optional_json_value(
            (preview.hermes, "config", "get", _FALLBACK_PROVIDERS_KEY, "--json"), env, []
        ),
        _optional_json_value((preview.hermes, "config", "get", _FALLBACK_KEY, "--json"), env, []),
    )


def _providers_value(value: object) -> object:
    # Hermes reports an unset `fallback_providers` as its default `[]`.
    return [] if value is None else value


def _fallback_state_is_ours(
    preview: HermesModelConfigPreview, observed: tuple[object, object]
) -> bool:
    """Whether `observed` is the prior state or one this apply's own writes pass through."""
    providers, legacy = observed
    target: list[object] = []
    if preview.fallback:
        provider, model = split_fallback_target(preview.fallback)
        target = [{"provider": provider, "model": model}]
    return _providers_value(providers) in (
        _providers_value(preview.before_fallback_providers),
        target,
    ) and legacy in (preview.before_fallback, None)


def _require_owned_fallback(
    preview: HermesModelConfigPreview,
    env: Mapping[str, str] | None,
    expected_digest: str,
) -> str:
    if not _fallback_state_is_ours(preview, _observed_fallback(preview, env)):
        raise ConfigDigestMismatchError(
            "Hermes fallback chain changed concurrently during apply; rollback required"
        )
    return _config_digest(preview.config_path)


def _fallback_matches(providers: object, legacy: object, target: str) -> bool:
    """Whether Hermes' effective fallback chain is exactly the one `target` entry."""
    provider, model = split_fallback_target(target)
    return _effective_chain(providers, legacy) == [{"provider": provider, "model": model}]


def _rollback_fallback(
    preview: HermesModelConfigPreview,
    env: Mapping[str, str] | None,
    expected_digest: str,
) -> None:
    """Replay the exact non-secret entries read before the apply, in both keys."""
    before_providers = _providers_value(preview.before_fallback_providers)
    before_legacy = preview.before_fallback
    observed = _observed_fallback(preview, env)
    if not _fallback_state_is_ours(preview, observed):
        raise ConfigDigestMismatchError(
            "Hermes fallback chain ownership changed during apply; rollback refused"
        )
    providers, legacy = observed
    commands: list[tuple[str, ...]] = []
    if _providers_value(providers) != before_providers:
        commands.append(
            (preview.hermes, "config", "set", _FALLBACK_PROVIDERS_KEY, _fallback_literal(before_providers))
            if before_providers
            else (preview.hermes, "config", "unset", _FALLBACK_PROVIDERS_KEY)
        )
    if legacy != before_legacy and before_legacy is not None:
        commands.append(
            (preview.hermes, "config", "set", _FALLBACK_KEY, _fallback_literal(before_legacy))
        )
    for command in commands:
        if _config_digest(preview.config_path) != expected_digest:
            raise ConfigDigestMismatchError(
                "Hermes config changed during rollback; remaining rollback refused"
            )
        result = _run(command, env)
        if result.returncode != 0:
            raise HermesVerificationError(
                f"Hermes rollback command failed ({result.returncode}): {' '.join(command[1:4])}"
            )
        expected_digest = _config_digest(preview.config_path)
    providers, legacy = _observed_fallback(preview, env)
    if _providers_value(providers) != before_providers or legacy != before_legacy:
        raise HermesVerificationError("Hermes fallback chain rollback verification mismatch")


def _require_expected_alias_state(
    preview: HermesModelConfigPreview,
    attempted: list[str],
    env: Mapping[str, str] | None,
) -> None:
    observed = _optional_json_mapping(
        (preview.hermes, "config", "get", "model.aliases", "--json"),
        env,
        [],
    )
    expected = dict(preview.before_aliases)
    for alias in attempted:
        target = preview.changes[alias]
        if target is None:
            expected.pop(alias, None)
        else:
            expected[alias] = target
    if observed != expected:
        raise ConfigDigestMismatchError(
            "Hermes aliases changed concurrently during apply; rollback required"
        )


def _rollback_aliases(
    preview: HermesModelConfigPreview,
    attempted: list[str],
    env: Mapping[str, str] | None,
    *,
    expected_config_digest: str,
) -> None:
    observed = _optional_json_mapping(
        (preview.hermes, "config", "get", "model.aliases", "--json"),
        env,
        [],
    )
    if any(observed.get(alias) != preview.changes[alias] for alias in attempted):
        raise ConfigDigestMismatchError(
            "Hermes alias ownership changed during apply; rollback refused"
        )
    rollback_error: HermesModelConfigError | None = None
    for alias in reversed(attempted):
        if _config_digest(preview.config_path) != expected_config_digest:
            raise ConfigDigestMismatchError(
                "Hermes config changed during rollback; remaining rollback refused"
            )
        prior = preview.before_aliases.get(alias)
        key = f"{_ALIAS_KEY_PREFIX}{alias}"
        command = (
            (preview.hermes, "config", "unset", key)
            if prior is None
            else (preview.hermes, "config", "set", key, prior)
        )
        result = _run(command, env)
        if result.returncode != 0:
            rollback_error = HermesVerificationError(
                f"Hermes rollback command failed ({result.returncode}): {' '.join(command[1:])}"
            )
        expected_config_digest = _config_digest(preview.config_path)
    inspection = inspect_hermes_model_config(hermes=preview.hermes, env=env)
    for alias in attempted:
        if inspection.model_dot_aliases.get(alias) != preview.before_aliases.get(alias):
            rollback_error = HermesVerificationError(
                f"Hermes alias {alias!r} rollback verification mismatch"
            )
    if rollback_error is not None:
        raise rollback_error


def _run(
    command: tuple[str, ...],
    env: Mapping[str, str] | None,
    commands: list[tuple[str, ...]] | None = None,
) -> subprocess.CompletedProcess[str]:
    if commands is not None:
        commands.append(command)
    try:
        # Hermes forces its stdout to UTF-8 on every platform
        # (hermes_cli/__init__.py), and `auth list` marks the current
        # credential with `←`; the locale codec (cp1252 on Windows) cannot
        # decode those bytes.
        return subprocess.run(
            _platform_command(command),
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            env=None if env is None else dict(env),
            timeout=_COMMAND_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise HermesCommandError(
            f"Hermes command timed out after {_COMMAND_TIMEOUT_SECONDS}s: {' '.join(command[1:])}"
        ) from exc
    except FileNotFoundError as exc:
        # A machine may run OMH beside a hosted wrapper that manages Hermes,
        # with no `hermes` on PATH. That is a missing prerequisite the caller
        # reports, not a crash.
        raise HermesUnavailableError(f"Hermes command not found: {command[0]}") from exc


def _platform_command(command: tuple[str, ...]) -> tuple[str, ...]:
    if os.name == "nt" and Path(command[0]).suffix.casefold() == ".py":
        return (sys.executable, *command)
    return command


def _required_output(
    command: tuple[str, ...],
    env: Mapping[str, str] | None,
    commands: list[tuple[str, ...]],
) -> str:
    result = _run(command, env, commands)
    if result.returncode != 0:
        raise HermesCommandError(f"Hermes command failed: {' '.join(command[1:])}")
    return result.stdout.strip()


def _optional_json_value(
    command: tuple[str, ...],
    env: Mapping[str, str] | None,
    commands: list[tuple[str, ...]],
) -> str | list[str] | dict[str, str | list[str] | dict[str, str]] | None:
    result = _run(command, env, commands)
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise HermesCommandError(f"Hermes returned invalid JSON for {command[2]}") from exc
    if value is None or isinstance(value, (str, list, dict)):
        return value
    raise HermesCommandError(f"Hermes returned unsupported JSON for {command[2]}")


def _optional_json_mapping(
    command: tuple[str, ...],
    env: Mapping[str, str] | None,
    commands: list[tuple[str, ...]],
) -> dict[str, str]:
    value = _optional_json_value(command, env, commands)
    if not isinstance(value, dict):
        return {}
    return {
        str(key): item
        for key, item in value.items()
        if isinstance(item, str) and _safe_metadata(str(key)) and _safe_metadata(item)
    }


def _config_digest(path: Path) -> str:
    try:
        return sha256(path.read_bytes()).hexdigest()
    except FileNotFoundError as exc:
        raise HermesConfigUnreadableError(path, missing=True) from exc
    except OSError as exc:
        raise HermesConfigUnreadableError(path, missing=False) from exc


def _auth_provider_ids(output: str) -> set[str]:
    providers: set[str] = set()
    for line in output.splitlines():
        match = _AUTH_PROVIDER_RE.match(line.strip())
        if match and _safe_metadata(match.group(1)):
            providers.add(match.group(1))
    return providers


def _custom_provider_names(
    value: str | list[str] | dict[str, str | list[str] | dict[str, str]] | None,
) -> set[str]:
    """Configured legacy custom provider names, normalized the way Hermes keys their pools."""
    if not isinstance(value, list):
        return set()
    names: set[str] = set()
    for entry in value:
        name = entry.get("name") if isinstance(entry, dict) else None
        if not isinstance(name, str):
            continue
        normalized = name.strip().lower().replace(" ", "-")
        if _CUSTOM_PROVIDER_NAME_RE.fullmatch(normalized) and _safe_metadata(normalized):
            names.add(normalized)
    return names


def _configured_auth_provider_ids(auth_providers: set[str], custom_names: set[str]) -> set[str]:
    """Credentialed ids an alias target can name.

    Hermes resolves an alias prefix `<name>` or `custom:<name>` to a legacy
    custom provider only while `custom_providers` still configures `<name>`, so
    a `custom:<name>` pool counts for both spellings then, and for neither once
    the entry is gone.
    """
    providers = {
        provider
        for provider in auth_providers
        if not provider.startswith(_CUSTOM_POOL_PREFIX)
        or provider.removeprefix(_CUSTOM_POOL_PREFIX) in custom_names
    }
    providers.update(
        name for name in custom_names if f"{_CUSTOM_POOL_PREFIX}{name}" in auth_providers
    )
    return providers


def _plugin_provider_ids(
    value: str | list[str] | dict[str, str | list[str] | dict[str, str]] | None,
) -> set[str]:
    if not isinstance(value, dict):
        return set()
    providers: set[str] = set()
    enabled = value.get("enabled")
    if isinstance(enabled, list):
        providers.update(str(item) for item in enabled if _safe_metadata(str(item)))
    entries = value.get("entries")
    if isinstance(entries, dict):
        providers.update(str(item) for item in entries if _safe_metadata(str(item)))
    return providers


def _alias_provider_ids(aliases: Mapping[str, str]) -> set[str]:
    return {
        provider
        for target in aliases.values()
        if "/" in target and _safe_metadata(provider := target.split("/", 1)[0])
    }


def _provider_entries(
    value: str | list[str] | dict[str, str | list[str] | dict[str, str]] | None,
) -> tuple[_ProviderEntry, ...]:
    """Enabled Hermes `providers:` entries, as the ids and pools Hermes routes them by.

    Hermes resolves `<key>`, `<name>`, and their `custom:` forms to one entry
    (hermes_cli/providers.py `custom_provider_aliases`) and keeps its pool
    under `<key>` or legacy `custom:<name>`. Only non-secret fields are read:
    the env var *name* the key comes from, never an inline `api_key`.
    """
    if not isinstance(value, dict):
        return ()
    entries: list[_ProviderEntry] = []
    for key, entry in value.items():
        if not isinstance(entry, dict) or not _provider_enabled(entry.get("enabled", True)):
            continue
        base_url = next(
            (
                url.strip()
                for field in ("base_url", "url", "api", "baseUrl")
                if isinstance(url := entry.get(field), str) and url.strip()
            ),
            "",
        )
        name = entry.get("name")
        names = {
            normalized
            for raw in (str(key), name if isinstance(name, str) else "")
            if (normalized := raw.strip().lower().replace(" ", "-"))
            and _CUSTOM_PROVIDER_NAME_RE.fullmatch(normalized)
            and _safe_metadata(normalized)
        }
        canonical = str(key).strip().lower().replace(" ", "-")
        if not base_url or canonical not in names:
            continue
        pools = {f"{_CUSTOM_POOL_PREFIX}{item}" for item in names}
        entries.append(
            _ProviderEntry(
                canonical=canonical,
                ids=frozenset(names | pools),
                pool_ids=frozenset({canonical} | pools),
                credential_env=_entry_credential_env(entry, base_url),
            )
        )
    return tuple(entries)


def _provider_enabled(flag: object) -> bool:
    # hermes_cli/config_providers.py `is_provider_enabled`.
    if isinstance(flag, str):
        return flag.strip().lower() not in _FALSE_WORDS
    return bool(flag)


def _entry_credential_env(entry: Mapping[str, object], base_url: str) -> str | None:
    """The env var name Hermes reads this entry's key from, or None.

    A declared `key_env` is the only source then; an entry declaring an
    inline `api_key` or a `key_cmd` gets no implicit env key from Hermes, and
    OMH cannot observe either; otherwise Hermes reads the host's key variable.
    """
    for field in ("key_env", "api_key_env", "keyEnv", "apiKeyEnv"):
        declared = entry.get(field)
        if isinstance(declared, str) and declared.strip():
            name = declared.strip()
            if _ENV_NAME_RE.fullmatch(name) and not is_secret_value_shaped(name):
                return name
            return None
    if any(str(entry.get(field) or "").strip() for field in ("api_key", "apiKey", "key_cmd")):
        return None
    return _host_key_env(base_url)


def _host_key_env(base_url: str) -> str | None:
    """`<VENDOR>_API_KEY` for a base URL's host, as Hermes derives it.

    Mirrors hermes_cli/runtime_provider.py `_host_derived_api_key`: the
    registrable label of the host (`api.mistral.ai` -> `MISTRAL_API_KEY`),
    nothing for IPs, loopback, or single-label hosts.
    """
    try:
        hostname = urlsplit(base_url if "://" in base_url else f"//{base_url}").hostname or ""
    except ValueError:
        # A malformed base_url (`http://[bad`) names no host; Hermes derives no key from it either.
        return None
    for domain, env_name in _HOST_GATED_KEY_ENV:
        if hostname == domain or hostname.endswith(f".{domain}"):
            return env_name
    labels = [label for label in hostname.split(".") if label]
    if not labels or any(ch.isdigit() for ch in labels[-1]) or hostname == "localhost" or ":" in hostname:
        return None
    while labels and labels[0] in ("api", "www"):
        labels.pop(0)
    if len(labels) < 2:
        return None
    vendor = "".join(ch if ch.isalnum() else "_" for ch in labels[-2]).upper()
    if not vendor or not vendor[0].isalpha() or vendor in ("OPENAI", "OPENROUTER", "OLLAMA"):
        return None
    return f"{vendor}_API_KEY"


def _env_var_present(env: Mapping[str, str] | None, name: str | None) -> bool:
    """Whether `name` is set non-empty; the value is neither kept nor returned."""
    if name is None:
        return False
    source = os.environ if env is None else env
    return bool(str(source.get(name) or "").strip())


def providers_entry_remedy(presence: ProviderPresence) -> str:
    """What makes a `providers:` entry's credential observable, as one clause.

    Shared by the preview refusal and model setup's `provider_next_actions`, so
    both name the same route. The variable is echoed only in conventional
    UPPER_SNAKE shape: a key pasted into `key_env` by mistake is
    identifier-shaped too and must never reach the text.
    """
    if presence.credential_env and _ECHOABLE_ENV_NAME_RE.fullmatch(presence.credential_env):
        remedy = f"set {presence.credential_env} in the environment omh runs in"
    elif presence.credential_env:
        remedy = "set the variable its key_env names in the environment omh runs in"
    else:
        remedy = "name the variable holding its key with key_env"
    return f"{remedy}, or add a pool with `hermes auth add {presence.provider_id}`"


def _require_target_auth(inspection: HermesModelConfigInspection, target: str) -> None:
    """Refuse a `provider/model` target whose provider has no observable auth."""
    provider_id = target.split("/", 1)[0]
    if (
        _safe_metadata(target)
        and provider_id == "custom"
        and not _provider_has_auth(inspection, provider_id)
    ):
        raise HermesModelConfigError(
            f"Hermes model target {target!r} uses bare 'custom', which names no "
            "configured endpoint or credential pool; write it as '<name>/<model>' "
            "with the custom provider's configured name"
        )
    if not _safe_metadata(target) or not _provider_has_auth(inspection, provider_id):
        raise HermesModelConfigError(_missing_auth_message(inspection, target, provider_id))


def _missing_auth_message(
    inspection: HermesModelConfigInspection, target: str, provider_id: str
) -> str:
    presence = next(
        (item for item in inspection.providers if item.provider_id == provider_id), None
    )
    if _safe_metadata(target) and presence is not None and not presence.auth_present:
        if presence.provider_entry:
            return (
                f"Hermes model target {target!r} names provider {provider_id!r}, which is "
                "configured under providers: but no credential is observable: "
                f"{providers_entry_remedy(presence)}"
            )
        if presence.plugin_present:
            return (
                f"Hermes model target {target!r} names provider {provider_id!r}, a Hermes "
                "plugin whose own sign-in OMH cannot observe and that holds no credential "
                f"pool: add a pool with `hermes auth add {provider_id}`"
            )
    return f"Hermes model target {target!r} lacks safe observed provider auth"


def _provider_has_auth(inspection: HermesModelConfigInspection, provider_id: str) -> bool:
    return any(
        provider.provider_id == provider_id
        and provider.auth_present
        and provider.auth_status_ok
        for provider in inspection.providers
    )


def _safe_metadata(value: str) -> bool:
    return bool(value) and not is_sensitive_metadata_text(value)
