from __future__ import annotations

import re
from typing import Final

from .awesome_hermes_agent import AwesomeHermesCoverage, AwesomeHermesItem, CoverageRule, PLUGIN_SUBSECTION


_TOKEN_RE: Final = re.compile(r"[a-z0-9]+")
RULE_SET_VERSION: Final = "awesome_hermes_agent_rules/v1"

_RULES = (
    CoverageRule(
        ("oh-my-hermes", "omh"),
        "covered",
        "high",
        ("oh-my-hermes", "skill-scout", "workflow-learning"),
        "OMH has a first-party workflow pack surface; compare upstream only for ecosystem drift.",
        "first_party_omh",
    ),
    CoverageRule(
        ("dynamic workflow", "workflow scripts", "subagents", "swarm", "multi-agent", "parallel", "agentplane"),
        "partial",
        "high",
        ("team", "ultragoal", "ultrawork", "agent-board", "harness-session-inventory"),
        "OMH covers planning, handoff, board, and evidence boundaries, but does not import external worker runtimes.",
        "dynamic_orchestration",
    ),
    CoverageRule(
        ("discord voice", "gemini multimodal", "voice", "stt", "tts", "whatsapp", "signal", "teams", "feishu", "lark"),
        "partial",
        "high",
        (
            "voice-operator",
            "media-input-operator",
            "gateway-intent-card",
            "visual-qa",
            "web_visual_qa_message_card/v1",
            "toolbelt-readiness",
        ),
        "OMH can prepare voice, media, gateway, and web QA message cards; platform connectors remain observed external tools.",
        "live_media_gateway",
    ),
    CoverageRule(
        ("web search", "search", "scrape", "browser", "chrome profile", "cloudflare", "youtube", "transcript"),
        "partial",
        "high",
        (
            "web-research",
            "source-finder",
            "browser-operator",
            "live-info-operator",
            "web_visual_qa_message_card/v1",
            "toolbelt-readiness",
        ),
        "OMH routes source, browser, and web QA package review work, while provider credentials and live retrieval remain external observations.",
        "web_research",
    ),
    CoverageRule(
        ("memory", "recall", "engram", "context", "fts5", "pgvector", "knowledge graph", "curator"),
        "partial",
        "high",
        ("memory-curation-review", "wiki", "workflow-learning", "instinct-ledger", "skill-health"),
        "OMH reviews and packages retained context without claiming opaque Hermes memory mutation.",
        "memory_recall",
    ),
    CoverageRule(
        ("marketplace", "registry", "curator", "motif", "dedup", "evolver", "skill drift", "skill creation"),
        "partial",
        "high",
        ("skill-scout", "skill-health", "workflow-learning", "instinct-ledger"),
        "OMH can scout, compare, and queue skill improvements; copying or installing external skills requires separate review.",
        "skill_marketplace",
    ),
    CoverageRule(
        ("eval", "benchmark", "trajectory", "quality", "regression", "dangerous pattern", "approval", "pre_llm", "pre_tool"),
        "partial",
        "high",
        ("agent-evaluation", "verification-gate", "security-safety-review", "command-operator", "failure-signal-audit"),
        "OMH covers review and gate framing; host hook installation or enforcement is external runtime evidence.",
        "evaluation_safety",
    ),
    CoverageRule(
        ("cost", "usage", "analytics", "token", "x402", "payment", "usdc", "spending", "billing"),
        "partial",
        "medium",
        ("ops-observability-card", "toolbelt-readiness", "security-safety-review", "production-audit"),
        "OMH can surface cost and safety readiness; provider billing, wallets, and payment actions stay external.",
        "cost_analytics",
    ),
    CoverageRule(
        ("deploy", "docker", "nix", "server", "systemd", "cron", "monitor", "incident", "sre", "ops"),
        "partial",
        "medium",
        ("deploy-and-monitor", "reliability-review", "production-audit", "automation-blueprint", "doctor"),
        "OMH prepares operational runbooks and evidence ladders but does not become infrastructure automation.",
        "operations_readiness",
    ),
    CoverageRule(
        ("pull request", "issue", "release", "paperclip", "agent-to-agent", "message bus"),
        "partial",
        "medium",
        ("github-event-ops", "agent-board", "connector-operator", "gateway-intent-card"),
        "OMH can route events and prepare connector handoffs; external platform mutation requires observed connector evidence.",
        "platform_events",
    ),
    CoverageRule(
        ("image", "video", "forensic", "ocr", "media", "flux", "comfyui", "pdf", "deck", "html", "markdown"),
        "partial",
        "medium",
        ("img-summary", "media-input-operator", "materials-package", "deliverable-package", "visual-qa"),
        "OMH covers media and deliverable planning/QA while generated files and attachments remain observed-only.",
        "media_deliverables",
    ),
    CoverageRule(
        ("weather", "finance", "crypto", "solana", "chainlink", "stock", "sports", "spotify", "nextcloud"),
        "missing_candidate",
        "medium",
        ("skill-scout", "connector-operator", "toolbelt-readiness", "live-info-operator"),
        "This domain is best tracked as an external candidate until OMH has a dedicated local workflow or connector contract.",
        "domain_connectors",
    ),
)


def coverage_for_item(item: AwesomeHermesItem) -> AwesomeHermesCoverage:
    tokens = tuple(_TOKEN_RE.findall(_search_text(item)))
    token_set = frozenset(tokens)
    phrase_text = f" {' '.join(tokens)} "
    for rule in _RULES:
        if any(_term_matches(term, token_set, phrase_text) for term in rule.terms):
            return AwesomeHermesCoverage(
                item,
                rule.status,
                _priority_for_item(item, rule.priority),
                rule.surfaces,
                (rule.note, _boundary_note(item)),
                RULE_SET_VERSION,
                rule.rule_id,
            )
    return AwesomeHermesCoverage(
        item,
        _default_status(item),
        _priority_for_item(item, "low"),
        _default_surfaces(item),
        (
            "No precise OMH workflow surface is mapped yet; keep this as a reviewed external candidate.",
            _boundary_note(item),
        ),
        RULE_SET_VERSION,
        _default_rule_id(item),
    )


def _term_matches(term: str, item_tokens: frozenset[str], item_phrase_text: str) -> bool:
    term_tokens = tuple(_TOKEN_RE.findall(term.lower()))
    if not term_tokens:
        return False
    if len(term_tokens) == 1:
        return term_tokens[0] in item_tokens
    return f" {' '.join(term_tokens)} " in item_phrase_text


def _priority_for_item(item: AwesomeHermesItem, fallback: str) -> str:
    if item.subsection == PLUGIN_SUBSECTION:
        return "high"
    if item.maturity == "production" and fallback == "low":
        return "medium"
    return fallback


def _default_status(item: AwesomeHermesItem) -> str:
    if item.section == "Skills & Plugins":
        return "partial"
    return "missing_candidate"


def _default_surfaces(item: AwesomeHermesItem) -> tuple[str, ...]:
    if item.section == "Skills & Plugins":
        return ("skill-scout", "skill-health", "toolbelt-readiness")
    return ("skill-scout", "toolbelt-readiness")


def _default_rule_id(item: AwesomeHermesItem) -> str:
    if item.section == "Skills & Plugins":
        return "default_skills_plugins"
    return "default_external_candidate"


def _boundary_note(item: AwesomeHermesItem) -> str:
    return f"Source: {item.section} / {item.subsection}, README line {item.readme_line}."


def _search_text(item: AwesomeHermesItem) -> str:
    return " ".join(
        (
            item.id,
            item.name,
            item.url,
            item.section,
            item.subsection,
            item.summary,
        )
    ).lower()
