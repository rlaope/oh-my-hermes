"""Scenario schema and structural grader for `benchmarks/automation-intent/v1`.

One scenario is a plain-language request, with any prior state, and the
automation it should produce -- or the right non-action: a clarifying
question, no automation at all, or an edit of the job that already exists.

An arm's decision names its outcome and, when it prepared or edited an
automation, the projection Hermes' own cron would receive: `schedule` and
`deliver` (the `cronjob_manage` arguments of the same names), the `target`
the job reads and the `filters` that narrow it, the silence rule, the timezone
and, for an edit, the `job_id` and the job's `state`. It may also attach the
`prepared_native_blueprint/v1` or `hermes_recurring_intent/v1` record it
prepared; the grader then checks that the record agrees with the projection
and stays prepared (never observed, never activated).

`grade_automation_intent` is a pure function from a scenario and one
observation row to a tuple of failures; no failure means the scenario passed.
It compares normalized values, never free text: schedules are compared after
cron/interval normalization against a list of accepted forms, delivery targets
and filters as case-insensitive sets.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .scenario_suite import Failure, string_list

SUITE = "automation-intent/v1"
ID_PREFIX = "ai-"
CATEGORIES = ("schedule", "github", "slack", "filters", "results-to", "ask", "no-automation", "edit")

PREPARED = "prepared_automation"
EDITED = "edited_existing"
CLARIFY = "clarifying_question"
NO_AUTOMATION = "no_automation"
OUTCOMES = (PREPARED, EDITED, CLARIFY, NO_AUTOMATION)
AUTOMATION_OUTCOMES = (PREPARED, EDITED)

CLARIFY_TOPICS = ("schedule", "timezone", "delivery", "target", "filters", "scope")
TARGET_KINDS = (
    "github_repo", "slack_channel", "discord_channel", "telegram_chat",
    "url", "rss_feed", "email_inbox", "calendar", "local_path",
)
FILTER_KEYS = ("labels", "keywords", "authors", "states", "branches", "paths", "event_types", "severities")
SILENCE_MODES = ("only_report_changes", "report_each_run")
JOB_STATES = ("active", "paused", "removed")
AUTOMATION_KEYS = ("job_id", "schedule", "timezone", "deliver", "target", "filters", "silence", "state")
# Expectation-only: filters an arm may state or leave out, because the request
# supports either reading. Never part of an arm's decision.
EXPECT_AUTOMATION_KEYS = (*AUTOMATION_KEYS, "optional_filters")
DECISION_KEYS = ("outcome", "automation", "asks_about", "artifact")
# What an arm sees. The id and category name the answer, so neither is shown.
PROMPT_KEYS = ("request", "prior_state")
SCENARIO_KEYS = frozenset({"id", "category", "request", "why", "prior_state", "expect", "skill_rule"})
# Rules a scenario's expectation depends on that the request alone does not
# carry. Only the skill text states them: the `skill-text` arm reads it, the
# `bare` arm does not, and the report keeps these scenarios in their own group.
# Each maps to the skill file and the words there that state the rule.
SKILL_RULES = {
    "spend_gate": (
        "skills/omh-automation-blueprint/SKILL.md",
        "an agent run on a schedule never spends",
    ),
}
EXPECT_KEYS = frozenset({"outcome", "automation", "clarify_about"})
PRIOR_STATE_KEYS = frozenset({"automations", "conversation", "user_timezone", "now"})

ARTIFACT_SCHEMAS = ("prepared_native_blueprint/v1", "hermes_recurring_intent/v1")
_ORIGIN_SURFACES = ("origin", "current-hermes-thread", "hermes-chat")
_UTC_ZONES = ("utc", "etc/utc", "gmt", "etc/gmt", "z", "utc+0", "utc+00:00", "+00:00")

_INTERVAL_MINUTES = {
    "m": 1, "min": 1, "mins": 1, "minute": 1, "minutes": 1,
    "h": 60, "hr": 60, "hrs": 60, "hour": 60, "hours": 60,
    "d": 1440, "day": 1440, "days": 1440,
}
_CRON_ALIASES = {
    "@hourly": "0 * * * *",
    "@daily": "0 0 * * *",
    "@midnight": "0 0 * * *",
    "@weekly": "0 0 * * 0",
    "@monthly": "0 0 1 * *",
}
_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
_WEEKDAYS = ("sun", "mon", "tue", "wed", "thu", "fri", "sat")

DECISION_CONTRACT = """\
Decision file contract (one JSON object):
{
  "outcome": "prepared_automation" | "edited_existing" | "clarifying_question" | "no_automation",
  "automation": {                       // only for prepared_automation or edited_existing
    "job_id": "<existing job id>",      // edited_existing only
    "schedule": "<Hermes cron schedule: a 5-field cron expression or 'every <n>m|h|d'>",
    "timezone": "<IANA timezone: the one the request names, else prior_state.user_timezone, else empty>",
    "deliver": ["<Hermes deliver target: 'origin' for this chat, or '<platform>:<channel>'>"],
    "target": {"kind": "<github_repo|slack_channel|discord_channel|telegram_chat|url|rss_feed|email_inbox|calendar|local_path>", "ref": "<what it reads>"} or null,
    "filters": {"<labels|keywords|authors|states|branches|paths|event_types|severities>": ["<value>"]},
    "silence": "only_report_changes" | "report_each_run",
    "state": "active" | "paused" | "removed"   // edited_existing only, when the request changes it
  },
  "asks_about": ["<schedule|timezone|delivery|target|filters|scope>"]   // clarifying_question only
}
Filter values: event_types from issues, pull_requests, releases, workflow_runs, commits, messages;
states from open, closed, merged, failed, succeeded; the other keys take the person's own words.
Several values under one key match any of them.
Name only filters the request states. "silence" is only_report_changes when the person wants nothing sent
on a run with nothing to report. For edited_existing give the job's whole projection after the edit,
unchanged fields included. Ask instead of guessing when a value the job needs is missing.
"""

SUITE_INSTRUCTIONS = """\
You are evaluating how a Hermes assistant turns a plain-language request into a recurring automation.
Read the scenario: the person's request and any prior state (existing jobs, earlier turns, their timezone).
Decide what you would do: prepare a new automation, edit the existing one, ask one clarifying question
because the request leaves a needed value open, or make no automation because the request does not ask
for recurring work. Record that decision in the structured form below; do not perform it.
"""


def prompt_keys() -> tuple[str, ...]:
    return PROMPT_KEYS


def harness_evidence_links(scenario: Mapping[str, Any]) -> list[str]:
    """Automation scenarios carry no observed evidence links."""
    return []


def arm_view(scenario: Mapping[str, Any]) -> dict[str, Any]:
    """What a live arm sees of one scenario: the request and its prior state."""
    return {key: scenario[key] for key in PROMPT_KEYS if key in scenario}


def _fold(value: object) -> str:
    return " ".join(str(value).casefold().split())


def _cron_token(token: str, names: Sequence[str], offset: int) -> str:
    if token.isdigit():
        return str(int(token))
    if token in names:
        return str(names.index(token) + offset)
    return token


def _cron_list_as_range(field: str) -> str:
    """`1,2,3,4,5` becomes `1-5`; any other field is returned unchanged."""
    items = field.split(",")
    if len(items) < 2 or not all(item.isdigit() for item in items):
        return field
    numbers = [int(item) for item in items]
    if numbers != list(range(numbers[0], numbers[0] + len(numbers))):
        return field
    return f"{numbers[0]}-{numbers[-1]}"


def _cron_field(field: str, names: Sequence[str] = (), offset: int = 0) -> str:
    pieces: list[str] = []
    token = ""
    for char in field:
        if char in ",-/":
            pieces.extend([_cron_token(token, names, offset), char])
            token = ""
        else:
            token += char
    pieces.append(_cron_token(token, names, offset))
    return "".join(pieces)


def normalize_schedule(value: object) -> str:
    """One canonical spelling of a Hermes cron schedule.

    `every 2h`, `every 2 hours` and `every 120m` all become `every 120m`; a
    five-field cron expression gets numeric fields without leading zeros,
    month and weekday names as numbers, and Sunday as 0; `@daily` and its
    siblings become their five-field form. Anything else is folded text.
    Cron and interval forms are never converted into each other: a scenario
    lists every form it accepts.
    """
    folded = _fold(value)
    if folded in _CRON_ALIASES:
        return _CRON_ALIASES[folded]
    words = folded.split()
    if len(words) >= 2 and words[0] == "every":
        rest = "".join(words[1:])
        digits = ""
        for char in rest:
            if not char.isdigit():
                break
            digits += char
        unit = rest[len(digits):]
        if unit in _INTERVAL_MINUTES:
            return f"every {int(digits or '1') * _INTERVAL_MINUTES[unit]}m"
    if len(words) == 5:
        minute, hour, day, month, weekday = words
        weekday = "0" if weekday == "7" else _cron_field(weekday, _WEEKDAYS)
        fields = [_cron_field(minute), _cron_field(hour), _cron_field(day), _cron_field(month, _MONTHS, 1), weekday]
        return " ".join(_cron_list_as_range(field) for field in fields)
    return folded


def _deliver_target(value: str) -> str:
    folded = _fold(value).replace(" ", "")
    if folded in _ORIGIN_SURFACES:
        return "origin"
    platform, separator, channel = folded.partition(":")
    # `slack:#eng` and `slack:eng`, `telegram:@brief` and `telegram:brief` name one place.
    return f"{platform}:{channel.lstrip('#@')}" if separator else platform


def normalize_deliver(value: object) -> list[str] | None:
    """Delivery targets as a sorted set; Hermes' comma-joined string is accepted too."""
    if isinstance(value, str):
        items = [item for item in value.split(",") if item.strip()]
    else:
        items = string_list(value)
        if items is None:
            return None
    return sorted({_deliver_target(item) for item in items})


def _deliver_platforms(targets: Sequence[str]) -> list[str]:
    return sorted({target.partition(":")[0] for target in targets})


def _normalize_ref(kind: str, ref: object) -> str:
    folded = _fold(ref)
    if kind == "github_repo":
        for prefix in ("https://github.com/", "http://github.com/", "github.com/", "git@github.com:"):
            if folded.startswith(prefix):
                folded = folded[len(prefix):]
        folded = folded.rstrip("/")
        if folded.endswith(".git"):
            folded = folded[: -len(".git")]
    elif kind in ("slack_channel", "discord_channel", "telegram_chat"):
        folded = folded.lstrip("#@")
    else:
        folded = folded.rstrip("/")
    return folded


# Abbreviations a request names and an arm may echo back, mapped to the IANA
# zone a scenario expects.
_ZONE_ABBREVIATIONS = {"kst": "asia/seoul", "jst": "asia/tokyo"}


def _normalize_zone(value: object) -> str:
    folded = _fold(value)
    if folded in _UTC_ZONES:
        return "utc"
    return _ZONE_ABBREVIATIONS.get(folded, folded)


def _filter_value(key: str, value: str) -> str:
    folded = _fold(value)
    if key == "paths":
        return folded.rstrip("/")
    if key == "authors":
        # `@dependabot`, `dependabot[bot]` and `dependabot` are one GitHub author.
        folded = folded.lstrip("@")
        return folded[: -len("[bot]")] if folded.endswith("[bot]") else folded
    return folded


def _normalize_target(value: object) -> tuple[str, str] | None:
    if not isinstance(value, Mapping):
        return None
    kind = _fold(value.get("kind", ""))
    return kind, _normalize_ref(kind, value.get("ref", ""))


def _normalize_filters(value: object) -> dict[str, list[str]] | None:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        return None
    normalized: dict[str, list[str]] = {}
    for key, items in value.items():
        values = string_list(items)
        if values is None:
            return None
        if values:
            normalized[str(key)] = sorted({_filter_value(str(key), item) for item in values})
    return normalized


def _expected_automation_errors(automation: object, outcome: str) -> list[str]:
    if not isinstance(automation, dict):
        return ["expect.automation must be an object for an automation outcome"]
    errors: list[str] = []
    if not set(automation) <= set(EXPECT_AUTOMATION_KEYS):
        errors.append(f"expect.automation keys must come from {', '.join(EXPECT_AUTOMATION_KEYS)}")
    schedules = string_list(automation.get("schedule"))
    if not schedules:
        errors.append("expect.automation.schedule must list at least one accepted form")
    if normalize_deliver(automation.get("deliver")) in (None, []):
        errors.append("expect.automation.deliver must list the delivery targets")
    if "timezone" in automation and not string_list(automation["timezone"]):
        errors.append("expect.automation.timezone must list accepted timezones")
    if "target" in automation and automation["target"] is not None:
        targets = automation["target"] if isinstance(automation["target"], list) else [automation["target"]]
        if not targets or not all(
            isinstance(target, dict) and set(target) == {"kind", "ref"} and target.get("kind") in TARGET_KINDS
            for target in targets
        ):
            errors.append(
                f"expect.automation.target must be null, {{kind, ref}}, or a list of accepted {{kind, ref}}, "
                f"with kind from {', '.join(TARGET_KINDS)}"
            )
    for field in ("filters", "optional_filters"):
        filters = automation.get(field, {})
        if not isinstance(filters, dict) or not set(filters) <= set(FILTER_KEYS) or _normalize_filters(filters) is None:
            errors.append(f"expect.automation.{field} must map keys from {', '.join(FILTER_KEYS)} to string lists")
    if isinstance(automation.get("optional_filters"), dict) and isinstance(automation.get("filters"), dict):
        if set(automation["optional_filters"]) & set(automation["filters"]):
            errors.append("expect.automation.optional_filters must not repeat a required filter key")
    if "silence" in automation and automation["silence"] not in SILENCE_MODES:
        errors.append(f"expect.automation.silence must be one of {', '.join(SILENCE_MODES)}")
    if "state" in automation and automation["state"] not in JOB_STATES:
        errors.append(f"expect.automation.state must be one of {', '.join(JOB_STATES)}")
    if outcome == EDITED and not isinstance(automation.get("job_id"), str):
        errors.append("expect.automation.job_id must name the existing job for an edit")
    if outcome == PREPARED and ("job_id" in automation or "state" in automation):
        errors.append("expect.automation for a new automation carries no job_id or state")
    return errors


def scenario_errors(scenario: Mapping[str, Any]) -> list[str]:
    """Why one automation-intent scenario is malformed."""
    errors: list[str] = []
    if not set(scenario) <= SCENARIO_KEYS:
        errors.append(f"keys must come from {sorted(SCENARIO_KEYS)}")
    prior = scenario.get("prior_state", {})
    if not isinstance(prior, dict) or not set(prior) <= PRIOR_STATE_KEYS:
        errors.append(f"prior_state keys must come from {sorted(PRIOR_STATE_KEYS)}")
        prior = {}
    job_ids = [job.get("job_id") for job in prior.get("automations", []) if isinstance(job, dict)]
    expect = scenario.get("expect")
    if not isinstance(expect, dict) or not set(expect) <= EXPECT_KEYS:
        return [*errors, f"expect must be an object with keys from {sorted(EXPECT_KEYS)}"]
    outcome = expect.get("outcome")
    if outcome not in OUTCOMES:
        return [*errors, f"expect.outcome must be one of {', '.join(OUTCOMES)}"]
    if outcome in AUTOMATION_OUTCOMES:
        errors.extend(_expected_automation_errors(expect.get("automation"), outcome))
        automation = expect.get("automation")
        if outcome == EDITED and isinstance(automation, dict) and automation.get("job_id") not in job_ids:
            errors.append("expect.automation.job_id must name a job in prior_state.automations")
    elif "automation" in expect:
        errors.append(f"expect.automation is only for {' or '.join(AUTOMATION_OUTCOMES)}")
    topics = expect.get("clarify_about")
    if outcome == CLARIFY:
        if not string_list(topics) or not set(topics) <= set(CLARIFY_TOPICS):
            errors.append(f"expect.clarify_about must list topics from {', '.join(CLARIFY_TOPICS)}")
    elif topics is not None:
        errors.append("expect.clarify_about is only for clarifying_question")
    if "skill_rule" in scenario and scenario["skill_rule"] not in SKILL_RULES:
        errors.append(f"skill_rule must be one of {', '.join(SKILL_RULES)}")
    category = scenario.get("category")
    if category == "ask" and outcome != CLARIFY:
        errors.append("an ask scenario expects a clarifying_question")
    if category == "no-automation" and outcome != NO_AUTOMATION:
        errors.append("a no-automation scenario expects no_automation")
    if category == "edit" and outcome not in (EDITED, CLARIFY):
        errors.append("an edit scenario expects edited_existing or a clarifying_question")
    return errors


def _prior_job(scenario: Mapping[str, Any], job_id: object) -> Mapping[str, Any]:
    for job in scenario.get("prior_state", {}).get("automations", []):
        if isinstance(job, Mapping) and job.get("job_id") == job_id:
            return job
    return {}


def _check_automation(expected: Mapping[str, Any], observed: Mapping[str, Any], outcome: str, prior_state: str = "") -> list[Failure]:
    failures: list[Failure] = []
    if outcome == EDITED and observed.get("job_id") != expected.get("job_id"):
        failures.append(Failure("automation.job_id", expected.get("job_id"), observed.get("job_id")))
    accepted = sorted({normalize_schedule(form) for form in expected["schedule"]})
    observed_schedule = observed.get("schedule")
    if not isinstance(observed_schedule, str) or normalize_schedule(observed_schedule) not in accepted:
        failures.append(Failure("automation.schedule", accepted, observed_schedule))
    if "timezone" in expected:
        zones = sorted({_normalize_zone(zone) for zone in expected["timezone"]})
        if _normalize_zone(observed.get("timezone", "")) not in zones:
            failures.append(Failure("automation.timezone", zones, observed.get("timezone")))
    want_deliver = normalize_deliver(expected["deliver"])
    got_deliver = normalize_deliver(observed.get("deliver"))
    if got_deliver != want_deliver:
        failures.append(Failure("automation.deliver", want_deliver, observed.get("deliver")))
    if "target" in expected:
        accepted_targets = expected["target"] if isinstance(expected["target"], list) else [expected["target"]]
        got_target = _normalize_target(observed.get("target"))
        if got_target not in [_normalize_target(target) for target in accepted_targets]:
            failures.append(Failure("automation.target", expected["target"], observed.get("target")))
    want_filters = _normalize_filters(expected.get("filters", {})) or {}
    optional = _normalize_filters(expected.get("optional_filters", {})) or {}
    got_filters = _normalize_filters(observed.get("filters", {}))
    if got_filters is None:
        failures.append(Failure("automation.filters", want_filters, observed.get("filters")))
    else:
        for key in sorted(set(want_filters) | set(got_filters)):
            want = want_filters.get(key)
            got = got_filters.get(key)
            if want is None and key in optional and got and set(got) <= set(optional[key]):
                continue
            if want != got:
                check = f"automation.filters.{key}" if want else f"automation.filters.{key} (not requested)"
                failures.append(Failure(check, want, got))
    for field in ("silence", "state"):
        if field in expected and observed.get(field) != expected[field]:
            failures.append(Failure(f"automation.{field}", expected[field], observed.get(field)))
    # An edit that does not change the job's state may leave `state` out, but
    # must not move it: pausing or removing a job nobody asked to stop fails.
    if outcome == EDITED and "state" not in expected and observed.get("state") not in (None, prior_state):
        failures.append(Failure("automation.state", prior_state, observed.get("state")))
    return failures


def _artifact_schedule_and_surfaces(artifact: Mapping[str, Any]) -> tuple[str, list[str], str]:
    if artifact.get("schema_version") == "prepared_native_blueprint/v1":
        native = artifact.get("native_blueprint")
        create = native.get("cronjob_manage_create") if isinstance(native, Mapping) else None
        create = create if isinstance(create, Mapping) else {}
        deliver = normalize_deliver(create.get("deliver", "")) or []
        schedule = str(create.get("schedule", ""))
    else:
        schedule_intent = artifact.get("schedule_intent")
        schedule = str(schedule_intent.get("explicit_schedule", "")) if isinstance(schedule_intent, Mapping) else ""
        delivery_intent = artifact.get("delivery_intent")
        surfaces = delivery_intent.get("surfaces") if isinstance(delivery_intent, Mapping) else []
        deliver = normalize_deliver(surfaces) or []
    silence = artifact.get("silence_policy")
    mode = str(silence.get("mode", "")) if isinstance(silence, Mapping) else ""
    return schedule, deliver, mode


def _check_artifact(artifact: object, observed: Mapping[str, Any]) -> list[Failure]:
    """The attached prepared record must agree with the projection and stay prepared."""
    if not isinstance(artifact, Mapping) or artifact.get("schema_version") not in ARTIFACT_SCHEMAS:
        schema = artifact.get("schema_version") if isinstance(artifact, Mapping) else type(artifact).__name__
        return [Failure("artifact.schema_version", list(ARTIFACT_SCHEMAS), schema)]
    failures: list[Failure] = []
    if artifact.get("observation_status") not in ("prepared", "not_observed"):
        failures.append(Failure("artifact.observation_status", ["prepared", "not_observed"], artifact.get("observation_status")))
    if artifact.get("schema_version") == "hermes_recurring_intent/v1":
        lifecycle = artifact.get("lifecycle")
        state = lifecycle.get("state") if isinstance(lifecycle, Mapping) else None
        if state != "paused":
            failures.append(Failure("artifact.lifecycle.state", "paused", state))
    schedule, artifact_targets, mode = _artifact_schedule_and_surfaces(artifact)
    platforms = _deliver_platforms(artifact_targets)
    projected = observed.get("schedule")
    if schedule.strip() and isinstance(projected, str) and normalize_schedule(schedule) != normalize_schedule(projected):
        failures.append(Failure("artifact.schedule", normalize_schedule(projected), schedule))
    projected_platforms = _deliver_platforms(normalize_deliver(observed.get("deliver")) or [])
    projected_targets = normalize_deliver(observed.get("deliver")) or []
    # A target the record names with a channel must be one the projection
    # names; a platform-only target (what the blueprint normalizer writes)
    # is checked at platform level.
    stray = [target for target in artifact_targets if ":" in target and target not in projected_targets]
    if (platforms and platforms != projected_platforms) or stray:
        failures.append(Failure("artifact.deliver", projected_targets, artifact_targets))
    if mode and observed.get("silence") and mode != observed.get("silence"):
        failures.append(Failure("artifact.silence_policy.mode", observed.get("silence"), mode))
    return failures


def grade_automation_intent(scenario: Mapping[str, Any], observation: Mapping[str, Any]) -> tuple[Failure, ...]:
    """Every structural check one observed decision fails; empty means passed."""
    expect = scenario["expect"]
    decision = observation.get("decision")
    decision = decision if isinstance(decision, Mapping) else {}
    outcome = decision.get("outcome")
    want = expect["outcome"]
    if outcome != want:
        return (Failure("outcome", want, outcome),)
    automation = decision.get("automation")
    if want in AUTOMATION_OUTCOMES:
        if not isinstance(automation, Mapping):
            return (Failure("automation", "an automation projection", automation),)
        prior = _prior_job(scenario, expect["automation"].get("job_id"))
        # A job whose record names no state is running: `active`.
        failures = _check_automation(expect["automation"], automation, want, str(prior.get("state") or "active"))
        if decision.get("artifact") is not None:
            failures.extend(_check_artifact(decision["artifact"], automation))
        return tuple(failures)
    failures = []
    if automation is not None:
        failures.append(Failure("automation", None, automation))
    if decision.get("artifact") is not None:
        failures.append(Failure("artifact", None, "a prepared record"))
    if want == CLARIFY:
        # `clarify_about` lists every topic the request leaves open. A right
        # question asks about one or more of them and about nothing else.
        asked = string_list(decision.get("asks_about")) or []
        if not asked or not set(asked) <= set(expect["clarify_about"]):
            failures.append(Failure("asks_about", list(expect["clarify_about"]), asked))
    return tuple(failures)


__all__ = [
    "CATEGORIES",
    "DECISION_CONTRACT",
    "DECISION_KEYS",
    "ID_PREFIX",
    "OUTCOMES",
    "SUITE",
    "SUITE_INSTRUCTIONS",
    "grade_automation_intent",
    "normalize_deliver",
    "normalize_schedule",
    "SKILL_RULES",
    "arm_view",
    "harness_evidence_links",
    "prompt_keys",
    "scenario_errors",
]
