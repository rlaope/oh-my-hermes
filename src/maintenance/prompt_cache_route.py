"""Read-only prompt-cache route check: does the cache TTL match what the route keeps?

Hermes picks a prompt-cache tier per send from ``prompt_caching.cache_ttl``
(``auto`` = 1h for human-paced sessions, 5m for machine-paced ones) and clamps
it with ``prompt_caching.route_ttl_ceilings.<provider>`` (see Hermes
``agent/prompt_caching.py``: ``effective_cache_ttl``, ``route_ttl_ceiling``).
Some local proxies (CLIProxyAPI-style, serving Claude on 127.0.0.1) forward
every Anthropic request with a 1h ``cache_control`` marker whatever the client
asked for, so a profile pinned to ``5m`` on such a route mis-models its own
cache clock: it treats a cache that is still warm as cold.

This module reads only ``<HERMES_HOME>/config.yaml`` and a bounded tail of
``<HERMES_HOME>/logs/agent.log``. It imports nothing from Hermes, opens no
network connection, and sends no model request. Per the fault-domain model the
findings are Hermes user-config observations: OMH prints the exact
``hermes config set`` fix and never writes it.
"""

from __future__ import annotations

import ipaddress
import re
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

PROMPT_CACHE_ROUTE_SCHEMA_VERSION = "omh_prompt_cache_route/v1"

# Providers known to keep a 1h cache entry whatever tier the client sends.
# Data, not code: a new proxy that does the same is one line here. The route's
# base_url decides; this table is consulted only when no base_url is configured,
# because a provider name can be reused for a direct first-party endpoint.
KNOWN_1H_PROXY_PROVIDERS: dict[str, str] = {
    "claude-proxy": "CLIProxyAPI (local Claude subscription proxy)",
    "cliproxyapi": "CLIProxyAPI (local Claude subscription proxy)",
    "cli-proxy-api": "CLIProxyAPI (local Claude subscription proxy)",
    "cpa": "CLIProxyAPI (local Claude subscription proxy)",
}
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "0.0.0.0"})
# The spellings Hermes' `cache_ttl_means_disabled` reads as "caching off".
_DISABLED_TTLS = frozenset({"", "off", "false", "disabled", "no", "none", "null", "~"})

# Bounded reads: config.yaml is tens of KB; agent.log rotates at ~5 MB, so the
# last 2 MiB covers a normal day of warmer lines without reading the file whole.
_MAX_CONFIG_BYTES = 512_000
_LOG_TAIL_BYTES = 2 * 1024 * 1024
WARMER_WINDOW = timedelta(hours=24)

_WARMER_LINE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})[,.]\d+ .*?"
    r"prompt cache warming stopped: (?P<reason>.+?) \(refreshes=(?P<refreshes>\d+), spent=\$(?P<spent>[0-9.]+)\)\s*$"
)

# Plain explanations of the warmer's stop reasons (Hermes
# `agent/prompt_cache_lifecycle/warmer.py`). An unknown reason is still counted.
WARMER_REASON_EXPLANATIONS: dict[str, str] = {
    "cache economics unavailable": (
        "the route has no cache prices, so no keep-alive is sent and no quota is spent "
        "(normal on subscription and proxy routes)"
    ),
    "the parent agent keeps this prefix warm": "a subagent shares its parent's prefix; the parent's traffic keeps it warm",
    "warm budget spent this turn": "the per-turn keep-alive budget ran out; the next real request writes the cache again",
    "prompt caching disabled": "prompt_caching.cache_ttl is off, so there is no cache to keep warm",
    "request carries no cache markers": "the request had no cache_control markers, so there was nothing to keep warm",
    "cache window not guaranteed warm": "the cache may already have expired, so a keep-alive would pay a full write",
    "cache entry already expired": "the cache expired before a keep-alive was due",
    "turn interrupted": "the turn was interrupted before a keep-alive was due",
    "only Anthropic Messages and Chat Completions requests are warmed": "this API mode is not warmed",
    "tool-wait refreshes would cost more than the cache write they prevent": (
        "waiting on a tool was cheaper to pay as one cache write than as repeated keep-alives"
    ),
}


def _strip_comment(value: str) -> str:
    value = value.strip()
    if value[:1] in {"'", '"'}:
        quote = value[0]
        end = value.find(quote, 1)
        return value[1:end] if end > 0 else value[1:]
    return value.split(" #", 1)[0].split("\t#", 1)[0].strip()


def _flow_mapping(value: str) -> dict[str, object] | None:
    value = value.strip()
    if not (value.startswith("{") and value.endswith("}")):
        return None
    result: dict[str, object] = {}
    for item in value[1:-1].split(","):
        key, sep, rest = item.partition(":")
        if sep and key.strip():
            result[_strip_comment(key)] = _strip_comment(rest)
    return result


def parse_block_mapping(text: str) -> dict[str, object]:
    """Nested block-mapping scalars by indentation; sequences and anchors are skipped.

    Enough for the four keys this check reads. A shape it does not follow
    yields a missing key, never a guessed value.
    """
    root: dict[str, object] = {}
    stack: list[tuple[int, dict[str, object]]] = [(-1, root)]
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith(("#", "-")) or "\t" in raw[: len(raw) - len(raw.lstrip())]:
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        key, sep, rest = raw.strip().partition(":")
        if not sep or not key or (rest and not rest[:1].isspace()):
            continue
        key = _strip_comment(key)
        while stack and stack[-1][0] >= indent:
            stack.pop()
        if not stack:
            stack = [(-1, root)]
        parent = stack[-1][1]
        value = rest.split(" #", 1)[0].strip() if not rest.strip().startswith(("'", '"')) else rest.strip()
        if not value:
            child: dict[str, object] = {}
            parent[key] = child
            stack.append((indent, child))
            continue
        flow = _flow_mapping(value)
        parent[key] = flow if flow is not None else _strip_comment(value)
    return root


def _get(mapping: object, *keys: str) -> object:
    for key in keys:
        if not isinstance(mapping, dict) or key not in mapping:
            return None
        mapping = mapping[key]
    return mapping


def _read_bounded(path: Path) -> str | None:
    try:
        if not path.is_file() or path.stat().st_size > _MAX_CONFIG_BYTES:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _read_tail(path: Path, limit: int = _LOG_TAIL_BYTES) -> str | None:
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - limit))
            data = handle.read(limit)
    except OSError:
        return None
    text = data.decode("utf-8", errors="replace")
    # A tail that starts mid-line drops that partial line.
    return text.split("\n", 1)[1] if size > limit and "\n" in text else text


def _host(base_url: str) -> str:
    try:
        return (urlsplit(base_url).hostname or "").lower()
    except ValueError:
        return ""


def _is_loopback(base_url: str) -> bool:
    host = _host(base_url)
    return host in _LOOPBACK_HOSTS or host.startswith("127.")


def _is_local_host(base_url: str) -> bool:
    """Loopback, localhost or a private-network address: where a local proxy lives."""
    host = _host(base_url)
    if not host:
        return False
    if host in _LOOPBACK_HOSTS or host.endswith(".localhost"):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or address.is_private or address.is_unspecified


def one_hour_proxy_label(provider: str, model: str, base_url: str) -> str:
    """Why this route keeps 1h cache entries whatever tier is sent, or "" when it does not.

    The base_url decides: a local host (loopback, localhost, private address)
    serving a Claude model is a CLIProxyAPI-style proxy; any other host, such as
    the first-party api.anthropic.com, is not, whatever the provider is named.
    The provider-name table is the fallback only when no base_url is configured.
    """
    if base_url:
        if _is_local_host(base_url) and "claude" in model.lower():
            return KNOWN_1H_PROXY_PROVIDERS.get(
                provider.lower(), "local proxy serving Claude (CLIProxyAPI-style, keeps 1h cache entries)"
            )
        return ""
    return KNOWN_1H_PROXY_PROVIDERS.get(provider.lower(), "")


def warmer_stop_reasons(hermes_home: Path, *, now: datetime | None = None) -> dict[str, object]:
    """Warmer stop reasons in the last 24h of `logs/agent.log`, counted, newest reason last."""
    log_path = hermes_home / "logs" / "agent.log"
    text = _read_tail(log_path) if log_path.is_file() else None
    if text is None:
        return {"log_path": str(log_path), "read": False, "counts": {}, "latest": "", "spent_usd": 0.0}
    cutoff = (now or datetime.now()) - WARMER_WINDOW
    counts: Counter[str] = Counter()
    latest = ""
    spent = 0.0
    for line in text.splitlines():
        if "warming stopped" not in line:
            continue
        match = _WARMER_LINE.match(line)
        if not match:
            continue
        try:
            stamp = datetime.strptime(match["ts"], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        if stamp < cutoff:
            continue
        counts[match["reason"]] += 1
        latest = match["reason"]
        spent += float(match["spent"])
    return {
        "log_path": str(log_path),
        "read": True,
        "counts": dict(counts.most_common()),
        "latest": latest,
        "spent_usd": round(spent, 4),
    }


def prompt_cache_route_report(hermes_home: Path, *, now: datetime | None = None) -> dict[str, object]:
    """The read-only report: route, TTL settings, findings with fixes, warmer stop reasons."""
    config_path = hermes_home / "config.yaml"
    text = _read_bounded(config_path)
    report: dict[str, object] = {
        "schema_version": PROMPT_CACHE_ROUTE_SCHEMA_VERSION,
        "config_path": str(config_path),
        "config_read": text is not None,
        "findings": [],
        "fixes": [],
    }
    findings: list[str] = []
    fixes: list[str] = []
    if text is not None:
        config = parse_block_mapping(text)
        provider = str(_get(config, "model", "provider") or "")
        model = str(_get(config, "model", "default") or _get(config, "model", "model") or "")
        base_url = str(_get(config, "providers", provider, "base_url") or _get(config, "model", "base_url") or "")
        section = _get(config, "prompt_caching")
        ttl_present = isinstance(section, dict) and "cache_ttl" in section
        raw_ttl = _get(section, "cache_ttl") if ttl_present else "auto"
        cache_ttl = raw_ttl if isinstance(raw_ttl, str) else ""
        ceilings = _get(section, "route_ttl_ceilings")
        ceiling = str(ceilings.get(provider, "")) if isinstance(ceilings, dict) and provider else ""
        proxy_label = one_hour_proxy_label(provider, model, base_url)
        disabled = cache_ttl.lower() in _DISABLED_TTLS
        report.update(
            provider=provider,
            model=model,
            base_url_loopback=bool(base_url) and _is_loopback(base_url),
            cache_ttl=cache_ttl if ttl_present else "auto (default)",
            route_ttl_ceiling=ceiling,
            one_hour_proxy=proxy_label,
            caching_disabled=disabled,
        )
        if disabled:
            findings.append(
                f"prompt caching is disabled (prompt_caching.cache_ttl: {cache_ttl or 'null'}): every turn pays "
                "full input price and nothing is kept warm"
            )
            fixes.append("hermes config set prompt_caching.cache_ttl auto")
        elif proxy_label:
            # Hermes `effective_cache_ttl` returns any non-1h request unchanged
            # before it consults the route ceiling, so a 1h ceiling never
            # upgrades a 5m pin: the pin itself is the mismatch.
            if cache_ttl.lower() == "5m":
                findings.append(
                    f"prompt_caching.cache_ttl is pinned to 5m but the main route `{provider}` is a {proxy_label} "
                    "that keeps 1h cache entries; Hermes treats a still-warm cache as cold after 5 minutes "
                    "(a 1h route ceiling does not raise a 5m pin)"
                )
                fixes.append("hermes config set prompt_caching.cache_ttl auto")
            if ceiling.lower() != "1h":
                if not findings:
                    findings.append(
                        f"the main route `{provider}` is a {proxy_label} that keeps 1h cache entries but "
                        f"prompt_caching.route_ttl_ceilings.{provider} is {ceiling or 'unset'}; Hermes' cache clock "
                        "still assumes the route's default TTL"
                    )
                fixes.append(f"hermes config set prompt_caching.route_ttl_ceilings.{provider} 1h")
    report["findings"] = findings
    report["fixes"] = fixes
    report["warmer"] = warmer_stop_reasons(hermes_home, now=now)
    report["lines"] = prompt_cache_lines(report)
    return report


def prompt_cache_hint_lines(hermes_home: Path) -> list[str]:
    """The `omh model` hint: only the TTL mismatch / disabled warning and its fixes, else nothing."""
    report = prompt_cache_route_report(hermes_home)
    lines = report.get("lines")
    return [line for line in lines if line.startswith(("warning:", "fix:"))] if isinstance(lines, list) else []


def prompt_cache_lines(report: dict[str, object]) -> list[str]:
    """Plain lines for `omh doctor` and `omh model`, absence said rather than hidden."""
    lines: list[str] = []
    if not report.get("config_read"):
        lines.append(f"Hermes config not readable at {report.get('config_path')}; cache TTL not checked")
    else:
        route = report.get("provider") or "(provider unset)"
        ceiling = report.get("route_ttl_ceiling") or "none"
        proxy = report.get("one_hour_proxy")
        lines.append(
            f"main route {route}: cache_ttl {report.get('cache_ttl')}, route ceiling {ceiling}"
            + (f"; route type: {proxy}" if proxy else "")
        )
        if not report.get("findings"):
            lines.append("cache TTL matches what the route keeps")
        findings = report.get("findings")
        fixes = report.get("fixes")
        for finding in findings if isinstance(findings, list) else []:
            lines.append(f"warning: {finding}")
        for fix in fixes if isinstance(fixes, list) else []:
            lines.append(f"fix: {fix}")
    warmer = report.get("warmer") or {}
    if isinstance(warmer, dict) and not warmer.get("read"):
        lines.append(f"warmer: no agent log at {warmer.get('log_path')}")
    elif isinstance(warmer, dict) and not warmer.get("counts"):
        lines.append("warmer: no warming-stopped lines in the last 24h of agent.log")
    elif isinstance(warmer, dict):
        counts = warmer.get("counts")
        counts = counts if isinstance(counts, dict) else {}
        lines.append(
            f"warmer stop reasons, last 24h (latest: {warmer.get('latest')}; spent ${warmer.get('spent_usd', 0.0):.4f}):"
        )
        for reason, count in counts.items():
            explanation = WARMER_REASON_EXPLANATIONS.get(str(reason), "")
            lines.append(f"  {count}x {reason}" + (f" -- {explanation}" if explanation else ""))
    return lines
