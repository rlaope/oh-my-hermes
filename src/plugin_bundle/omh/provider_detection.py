"""Which providers Hermes itself is linked to, read from what Hermes records.

The entitlement document (`routing/providers.json`) is what the operator
SAID they hold, recorded once by the `omh setup` interview. Most machines
never answer it, and the ones that did answered before the next `hermes
auth` login or the next provider block in `config.yaml`. This module reads
the three places Hermes keeps a linked provider and turns them into the same
`provider id -> kind` shape the document uses, so the chain shaping and the
pickers can count a provider the moment Hermes can use it:

- `config.yaml`: every `providers.<id>` key and `model.provider`. An id the
  registry knows carries its vendor family. Anything else is the operator's
  own endpoint (`og`, `work-gateway`), and the block says where it points:
  a `base_url` naming a vendor's documented API host carries that vendor's
  family (`ENDPOINT_HOST_FAMILIES`, exact hosts only), and anything else
  counts as a `gateway` -- a relay the operator declared on purpose, which
  is the one case where "serves every family" is the honest default rather
  than a guess; a custom block whose `base_url` is a loopback address
  (LM Studio, a local Ollama) serves nothing the catalog names and is left
  out.
- `auth.json`: the ids under `providers`, the `credential_pool` entries
  Hermes itself would count (its explicit flows -- device code, PKCE, a
  manual add -- and an `env:`-seeded row whose variable is still in `.env`;
  never a credential borrowed from another CLI), plus `active_provider`.
  This is where a subscription login lands (`hermes auth` for Codex, Nous,
  Qwen, xAI). Only ids and the `source` label are read; no token, key, or
  timestamp is copied anywhere.
- `.env`: the variable NAMES Hermes' registry lists for its API-key
  providers. Values are never read, and the process environment is not: a
  key exported only in a shell is not something Hermes recorded, and
  reading it would make the same home answer differently per terminal
  (and every test answer differently per developer). The setup interview,
  where a person confirms each row, still offers shell-exported names.

Detection is read-only and invokes nothing. A found id is evidence that
Hermes is linked to the provider, not that the account works or has quota;
the serving rule stays fail-open around it (`alias_is_served`). Ids that
name a Hermes provider whose models the catalog never describes (MiniMax,
StepFun, LM Studio) are ignored rather than mapped to `unknown`, because
`unknown` is a multi-vendor kind and would count every model as served on
the strength of a key OMH cannot place. `CLAUDE_CODE_OAUTH_TOKEN` is
likewise not evidence: Hermes' own registry marks it implicit (Claude Code
sets it, the operator did not configure Anthropic in Hermes), and a Claude
subscription is a Maestro-lane entitlement Hermes cannot spend.

Standalone: this module is copied into `$HERMES_HOME/plugins/omh` and
imports nothing from the `omh` package. The registry tables below mirror
Hermes' `hermes_cli/auth.py` and stay in the entitlement vocabulary;
`tests/test_provider_detection.py` pins that every kind is one the
document accepts.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

from . import runtime_paths

PROVIDER_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")

LINKED_SOURCE_LOGIN = "login"
LINKED_SOURCE_CONFIG = "config"
LINKED_SOURCE_ENV = "env"
# Strongest evidence first: a login is an authenticated account, a config
# key is a selection, a variable name is a hint. One row per id; the
# strongest source names it.
LINKED_SOURCE_ORDER: tuple[str, ...] = (LINKED_SOURCE_LOGIN, LINKED_SOURCE_CONFIG, LINKED_SOURCE_ENV)

# Hermes provider id -> entitlement kind. Vendor providers carry their
# family; relays that serve models of every family are `gateway`. Hermes
# ids absent here contribute nothing (see the module docstring).
HERMES_PROVIDER_KINDS: dict[str, str] = {
    "anthropic": "anthropic",
    "openai": "openai",
    "openai-api": "openai",
    "openai-codex": "openai-codex",
    "openrouter": "openrouter",
    "opencode-zen": "opencode",
    "opencode-go": "opencode",
    "opencode-free": "opencode",
    "zai": "zai",
    "kimi-coding": "kimi-coding",
    "kimi-coding-cn": "kimi-coding",
    "deepseek": "deepseek",
    "gemini": "gemini",
    "xai": "xai",
    "xai-oauth": "xai",
    "qwen-oauth": "qwen-oauth",
    "alibaba": "qwen-oauth",
    "alibaba-coding-plan": "qwen-oauth",
    "opengateway": "gateway",
    "nous": "gateway",
    "copilot": "gateway",
    "copilot-acp": "gateway",
    "ai-gateway": "gateway",
    "kilocode": "gateway",
    "nvidia": "gateway",
    "ollama-cloud": "gateway",
    "bedrock": "gateway",
    "vertex": "gateway",
    "azure-foundry": "gateway",
    "custom": "gateway",
}

# Variable NAME -> Hermes provider id, from the registry's `api_key_env_vars`
# for the providers above, plus three names the retired setup hint table
# offered and Hermes' registry does not list -- MOONSHOT_API_KEY (Moonshot's
# own platform spelling), OPENGATEWAY_API_KEY (OMH's gateway; see
# `hermes_child_dispatch._PROVIDER_ENV`), QWEN_API_KEY -- kept so a machine
# that answered the interview by one of them keeps being offered it.
# Generic tokens Hermes also accepts (GH_TOKEN, GITHUB_TOKEN, HF_TOKEN) are
# deliberately absent: they are set for reasons that have nothing to do with
# inference, and a relay they would imply counts every model as served.
# CLAUDE_CODE_OAUTH_TOKEN is absent because Hermes' registry lists it under
# `_IMPLICIT_ENV_VARS` (see the docstring).
HERMES_ENV_KEY_PROVIDERS: dict[str, str] = {
    "ANTHROPIC_API_KEY": "anthropic",
    "ANTHROPIC_TOKEN": "anthropic",
    "OPENAI_API_KEY": "openai-api",
    "OPENROUTER_API_KEY": "openrouter",
    "OPENGATEWAY_API_KEY": "opengateway",
    "GLM_API_KEY": "zai",
    "ZAI_API_KEY": "zai",
    "Z_AI_API_KEY": "zai",
    "KIMI_API_KEY": "kimi-coding",
    "KIMI_CODING_API_KEY": "kimi-coding",
    "KIMI_CN_API_KEY": "kimi-coding-cn",
    "MOONSHOT_API_KEY": "kimi-coding",
    "DEEPSEEK_API_KEY": "deepseek",
    "GOOGLE_API_KEY": "gemini",
    "GEMINI_API_KEY": "gemini",
    "XAI_API_KEY": "xai",
    "QWEN_API_KEY": "qwen-oauth",
    "DASHSCOPE_API_KEY": "alibaba",
    "ALIBABA_CODING_PLAN_API_KEY": "alibaba-coding-plan",
    "OPENCODE_ZEN_API_KEY": "opencode-zen",
    "OPENCODE_GO_API_KEY": "opencode-go",
    "COPILOT_GITHUB_TOKEN": "copilot",
    "AI_GATEWAY_API_KEY": "ai-gateway",
    "KILOCODE_API_KEY": "kilocode",
    "NVIDIA_API_KEY": "nvidia",
    "OLLAMA_API_KEY": "ollama-cloud",
}

# `model.provider: auto` is Hermes' resolution mode, not an account.
NON_PROVIDER_IDS: frozenset[str] = frozenset({"auto"})

GATEWAY_KIND = "gateway"

# Mirror of Hermes' `_EXPLICIT_POOL_SOURCES` (hermes_cli/auth.py): the
# credential-pool rows a person created through a Hermes flow. A row from
# another CLI's store (`claude_code`, `gh_cli`, `qwen-cli`) is borrowed, not
# linked, and Hermes itself does not count it as configuring the provider.
EXPLICIT_POOL_SOURCES: frozenset[str] = frozenset({"device_code", "loopback_pkce", "hermes_pkce", "manual"})

# Hosts a custom `providers.<id>.base_url` can name that serve a local model
# under a local name, never a catalog alias.
LOCAL_HOSTS: frozenset[str] = frozenset({"localhost", "127.0.0.1", "0.0.0.0", "::1", "[::1]", "host.docker.internal"})

# Endpoint host -> vendor family, for a `providers.<id>` block whose id says
# nothing (`custom`, `work-relay`). The block already carries the one fact
# that answers "what does this serve": its `base_url`. Reading the host is
# not a guess -- it is the vendor's own documented API endpoint, and it is
# the same evidence class as a config key, never a claim about an account,
# a tier, or a quota.
#
# EXACT hosts only, and only hosts that name a family in the entitlement
# vocabulary. A substring rule would resolve `openrouter.my-company.net` to
# `openrouter` and promote models in front of a chain that cannot serve
# them; a private gateway is unknowable from its URL and stays unresolved,
# which is what `omh model-chains provider set` exists for. Relay endpoints
# (NVIDIA NIM, Nous Portal) are deliberately absent: the honest kind for a
# multi-vendor relay is `gateway`, which is exactly what the fallback below
# already records, so an entry for one would change nothing.
ENDPOINT_HOST_FAMILIES: dict[str, str] = {
    "openrouter.ai": "openrouter",
    "api.anthropic.com": "anthropic",
    "api.openai.com": "openai",
    "api.deepseek.com": "deepseek",
    "api.x.ai": "xai",
    "generativelanguage.googleapis.com": "gemini",
    "api.z.ai": "zai",
    "open.bigmodel.cn": "zai",
    "api.moonshot.ai": "kimi-coding",
    "api.moonshot.cn": "kimi-coding",
    "dashscope.aliyuncs.com": "qwen-oauth",
    "dashscope-intl.aliyuncs.com": "qwen-oauth",
}


def _read_text(path: Path) -> str:
    # `utf-8-sig`, like Hermes' own auth-store reader: a BOM is skipped, not
    # parsed as the first character of a JSON document.
    try:
        return path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return ""


def _base_url_host(value: str) -> str:
    text = value.strip().strip("\"'")
    if "://" in text:
        text = text.split("://", 1)[1]
    host = text.split("/", 1)[0].split("@")[-1]
    if host.startswith("[") and "]" in host:
        return host[: host.index("]") + 1].lower()
    return host.rsplit(":", 1)[0].lower() if host.count(":") == 1 else host.lower()


def config_provider_base_url_hosts(config_text: str) -> dict[str, str]:
    """`providers.<id>` -> the host of its `base_url`, in config order.

    Line-shaped like `configured_provider_ids`: a four-space `base_url:` line
    under a two-space provider key. The first `base_url` in a block wins, a
    block without one is absent, and the host is lowercased by
    `_base_url_host`. Both questions the host answers -- "is this a local
    model server" and "which vendor's endpoint is this" -- read this one
    mapping, so there is one parser and the two can never disagree about
    what a block points at.
    """
    hosts: dict[str, str] = {}
    in_providers = False
    current = ""
    for line in config_text.splitlines():
        stripped = line.strip()
        if not line.startswith(" ") and stripped:
            in_providers = stripped == "providers:"
            current = ""
            continue
        if not in_providers or not stripped or stripped.startswith("#"):
            continue
        if line.startswith("  ") and not line.startswith("    "):
            key, separator, _rest = stripped.partition(":")
            current = key.strip().strip("\"'") if separator else ""
            continue
        if current and line.startswith("    ") and not line.startswith("      "):
            key, separator, rest = stripped.partition(":")
            if separator and key.strip() == "base_url" and current not in hosts:
                hosts[current] = _base_url_host(rest.split("#", 1)[0])
    return hosts


def local_config_provider_ids(config_text: str) -> list[str]:
    """`providers.<id>` keys whose `base_url` names a loopback host.

    Such a block is a local model server (LM Studio, Ollama) serving a local
    model under a local name; counting it as a gateway would mark every
    catalog model served on this machine.
    """
    return [
        provider_id
        for provider_id, host in config_provider_base_url_hosts(config_text).items()
        if host in LOCAL_HOSTS
    ]


def endpoint_family_for_host(host: str) -> str:
    """The vendor family an endpoint host names, or "" when none does.

    Exact match only (see `ENDPOINT_HOST_FAMILIES`): a host the table does
    not name is unresolved, never approximated.
    """
    return ENDPOINT_HOST_FAMILIES.get(str(host or "").strip().lower(), "")


def configured_provider_ids(config_text: str) -> list[str]:
    """`providers.<id>` keys plus `model.provider`, in config order.

    Line-shaped like every other config reader in the bundle (no YAML
    dependency); `model.provider` leads when it is not already a key, the
    first non-empty value wins, quotes and a trailing comment are stripped,
    and the top-level dotted spelling `model.provider: x` is read too.
    `omh.config_adapter.configured_provider_ids` IS this function (imported
    there), so the core side and the bundle cannot read a config apart.
    """
    ids: list[str] = []
    default_provider = ""
    section = ""
    for line in config_text.splitlines():
        stripped = line.strip()
        if not line.startswith(" ") and stripped:
            section = stripped.rstrip(":") if stripped.endswith(":") else ""
            if stripped.startswith("model.provider:") and not default_provider:
                default_provider = stripped[len("model.provider:"):].split("#", 1)[0].strip().strip("\"'")
            continue
        if not stripped or stripped.startswith("#"):
            continue
        if not (line.startswith("  ") and not line.startswith("    ")):
            continue
        key, separator, rest = stripped.partition(":")
        key = key.strip().strip("\"'")
        if not separator or not key:
            continue
        if section == "providers" and key not in ids:
            ids.append(key)
        elif section == "model" and key == "provider" and not default_provider:
            value = rest.split("#", 1)[0].strip().strip("\"'")
            default_provider = value
    if default_provider and default_provider not in ids:
        ids.insert(0, default_provider)
    return ids


def env_key_names(hermes_home: Path, environ: Mapping[str, str] | None = None) -> list[str]:
    """Variable NAMES present in `<hermes_home>/.env`, plus ``environ`` when given.

    Sorted, values never read. Only names the registry table knows are
    returned, so the result can be printed beside a row. Detection passes no
    ``environ`` (see the module docstring); the setup interview passes the
    process environment because a person confirms every row it offers.
    """
    names = {name for name in (environ or {}) if name in HERMES_ENV_KEY_PROVIDERS}
    for line in _read_text(hermes_home / ".env").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[len("export "):].lstrip()
        name, separator, _value = stripped.partition("=")
        if separator and name.strip() in HERMES_ENV_KEY_PROVIDERS:
            names.add(name.strip())
    return sorted(names)


def _pool_entry_is_explicit(entry: object, env_names: frozenset[str]) -> bool:
    """Mirror of Hermes' `_pool_entry_is_explicit`, with `.env` names for the env check."""
    if not isinstance(entry, dict):
        return False
    source = str(entry.get("source") or "").strip()
    lowered = source.lower()
    if lowered.startswith("env:"):
        # A stale env-seeded row outlives the variable it was seeded from;
        # Hermes counts it only while the variable still resolves. Without
        # reading values, "still in .env" is the closest honest check.
        return source.split(":", 1)[1].strip() in env_names
    return bool(lowered) and (lowered in EXPLICIT_POOL_SOURCES or lowered.startswith("manual:"))


def auth_store_provider_ids(text: str, env_names: Iterable[str] = ()) -> list[str]:
    """Provider ids the Hermes auth store holds a credential for; keys only.

    `providers.<id>` with a non-empty state, `credential_pool.<id>` with at
    least one entry Hermes itself would count (`_pool_entry_is_explicit`),
    and `active_provider`. Beyond the `source` label of a pool row nothing
    under those keys is read, and an unreadable store is no ids, never an
    error.
    """
    try:
        raw = json.loads(text)
    except ValueError:
        return []
    if not isinstance(raw, dict):
        return []
    known_names = frozenset(str(name) for name in env_names)
    found: set[str] = set()
    providers = raw.get("providers")
    if isinstance(providers, dict):
        for provider_id, state in providers.items():
            if isinstance(provider_id, str) and isinstance(state, dict) and state:
                found.add(provider_id)
    pool = raw.get("credential_pool")
    if isinstance(pool, dict):
        for provider_id, entries in pool.items():
            if not isinstance(provider_id, str) or not isinstance(entries, list):
                continue
            if any(_pool_entry_is_explicit(entry, known_names) for entry in entries):
                found.add(provider_id)
    active = raw.get("active_provider")
    if isinstance(active, str) and active:
        found.add(active)
    return sorted(name for name in found if PROVIDER_ID_RE.fullmatch(name))


def _hermes_home(value: str | Path | None) -> Path | None:
    if value is not None:
        return Path(value).expanduser()
    try:
        return runtime_paths.default_hermes_home()
    except runtime_paths.RuntimeBindingError:
        return None


def detect_linked_providers(
    hermes_home: str | Path | None = None,
    *,
    env_names: Iterable[str] | None = None,
) -> list[dict[str, str]]:
    """Every provider Hermes is linked to on this machine, strongest source first.

    Rows are `{"id", "kind", "source", "evidence"}` where `source` is one of
    `login`, `config`, `env` and `evidence` is the place it was found (a
    section of `auth.json`, a config key, a variable NAME). One row per id,
    ordered by source strength then id; a provider found in several places
    keeps the strongest. `env_names` lets a caller supply the variable names
    it already read (the setup interview does, and includes the shell's);
    otherwise only `.env` is read. An unbound profile home yields no rows
    rather than another home's rows. A `providers.<id>` block whose id names
    no vendor family is read from its `base_url` host (`config_kind`), so a
    custom-named block pointed at a vendor's documented endpoint carries
    that vendor's family instead of the `gateway` fallback.
    """
    home = _hermes_home(hermes_home)
    if home is None:
        return []
    config_text = _read_text(home / "config.yaml")
    base_url_hosts = config_provider_base_url_hosts(config_text)
    local_ids = {provider_id for provider_id, host in base_url_hosts.items() if host in LOCAL_HOSTS}
    config_ids = [provider_id for provider_id in configured_provider_ids(config_text) if provider_id not in local_ids]
    custom_ids = {provider_id for provider_id in config_ids if provider_id not in HERMES_PROVIDER_KINDS}
    names = env_key_names(home) if env_names is None else sorted(str(name) for name in env_names)
    rows: dict[str, dict[str, str]] = {}

    def config_kind(provider_id: str) -> str:
        """What a `providers.<id>` block serves: its id, else its endpoint, else `gateway`.

        An id the registry maps to a vendor family answers on its own and
        the endpoint is not consulted -- the id is the operator naming the
        provider, which outranks the URL under it. `gateway` is not such an
        answer: it is what an id that says nothing falls back to, so for
        those the endpoint host gets to answer before the fallback stands.
        """
        kind = HERMES_PROVIDER_KINDS.get(provider_id, GATEWAY_KIND)
        if kind != GATEWAY_KIND:
            return kind
        return endpoint_family_for_host(base_url_hosts.get(provider_id, "")) or kind

    def add(provider_id: str, kind: str, source: str, evidence: str) -> None:
        if provider_id in NON_PROVIDER_IDS or not PROVIDER_ID_RE.fullmatch(provider_id):
            return
        if provider_id not in rows:
            rows[provider_id] = {"id": provider_id, "kind": kind, "source": source, "evidence": evidence}

    for provider_id in auth_store_provider_ids(_read_text(home / "auth.json"), names):
        if provider_id in HERMES_PROVIDER_KINDS:
            add(provider_id, HERMES_PROVIDER_KINDS[provider_id], LINKED_SOURCE_LOGIN, "auth.json")
        elif provider_id in custom_ids:
            add(provider_id, config_kind(provider_id), LINKED_SOURCE_LOGIN, "auth.json")
    for provider_id in config_ids:
        add(provider_id, config_kind(provider_id), LINKED_SOURCE_CONFIG, "config.yaml")
    for name in names:
        provider_id = HERMES_ENV_KEY_PROVIDERS.get(name)
        if provider_id is None:
            continue
        add(provider_id, HERMES_PROVIDER_KINDS[provider_id], LINKED_SOURCE_ENV, name)
    return sorted(rows.values(), key=lambda row: (LINKED_SOURCE_ORDER.index(row["source"]), row["id"]))


def env_row_is_covered(row: Mapping[str, Any], recorded: Mapping[str, str]) -> bool:
    """Whether an `env` row names an account the recorded document already holds.

    The setup interview once recorded `OPENAI_API_KEY` as the id `openai`
    (the family name); detection names the Hermes provider, `openai-api`.
    Both describe one key, so an env row whose kind a recorded provider
    already carries -- or whose kind IS a recorded id -- adds nothing and is
    left out rather than shown as a second account. Login and config rows
    are distinct Hermes providers in their own right and always stand.
    """
    if row.get("source") != LINKED_SOURCE_ENV:
        return False
    kind = str(row.get("kind") or "")
    return kind in recorded or kind in set(recorded.values())


def linked_provider_kinds(rows: Iterable[Mapping[str, Any]]) -> dict[str, str]:
    """The `provider id -> kind` projection of `detect_linked_providers` rows."""
    return {str(row["id"]): str(row["kind"]) for row in rows}
