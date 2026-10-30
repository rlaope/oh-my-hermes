"""`omh_jev_ask`: the one explicit, opt-in path by which OMH itself sends data to Jev.

The call is refused before any socket opens unless every gate holds, in this
order: the person named Jev in this turn's own message (`jev_consent`), the
request is well formed and carries no credential-like text, a route resolves
(a `TYPESAFE_API_KEY`, or `OPENROUTER_API_KEY` plus the operator setting), and
no text in the request holds an 8-character window of either configured
route key, compared case-insensitively with whitespace removed. Only then does
`jev_ask_client` send it.

What leaves the machine: `state` exactly as supplied, every question id,
instruction, and option text, the model id, the key as a Bearer header, and a
User-Agent naming oh-my-hermes. OMH adds nothing beyond `state` and the
questions; whatever a skill puts in `state` -- commands, a working directory,
file paths, source diffs, test or error output, file contents -- is sent. Not sent: the Hermes session id,
`purpose`, or any other field. OMH persists no key, no `state`, no question
text, and no reply body; the ledger row is metadata only.

Every outcome is a JSON result, never an exception. Exactly one status,
`answered`, carries `ok: true` and answers; every other status carries
`ok: false` and `answers: null`.
"""

from __future__ import annotations

from .. import runtime_paths

import hashlib
import json
import re
import secrets
from collections.abc import Mapping
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from .._governance_safety import contains_credential_like_material
from ..host_observation import (
    attach_public_observation,
    host_session_id,
    observe_plugin_tool_call,
)
from ..jev_ask_client import (
    ASK_STATUSES,
    DEFAULT_MODEL,
    FIRST_PARTY_MODEL_IDS,
    OPENROUTER_ONLY_MODEL_IDS,
    PINNED_MODEL_BY_ROUTE,
    RETRYABLE_STATUSES,
    ROUTE_OPENROUTER,
    STATUS_ANSWERED,
    STATUS_CONSENT_NOT_OBSERVED,
    STATUS_INVALID_REQUEST,
    STATUS_KEY_MISSING,
    STATUS_KEY_UNRESOLVABLE,
    STATUS_MALFORMED_RESPONSE,
    AskRequestError,
    safe_served_model,
    MalformedReply,
    Transport,
    build_request_body,
    carries_key_fragment,
    cost_for,
    send_ask,
    validate_questions,
    validate_reply,
    validate_state,
)
from ..jev_ask_store import (
    LEDGER_SCHEMA_VERSION,
    ROUTE_KEY_NAMES,
    ROUTE_NONE,
    KeyUnresolvable,
    append_ledger_record,
    read_key,
    remember_answered_ask,
    resolve_route,
    route_available,
)
from ..jev_consent import consent_observed
from ..jev_presets import PRESET_IDS, PRESETS, policy_result, preset_questions
from ..runtime_reader import default_omh_home

RESULT_SCHEMA_VERSION = "omh_jev_ask_result/v1"
# The Choice question id a route_question/v1 block carries (`routing/route_question.py`).
ROUTE_CHOICE_QUESTION_ID = "route_choice"
FIT_QUESTION_PREFIX = "fits::"
# route_question/v1 digests are sha256 hex (`route_question_digest`).
_QUESTION_DIGEST = re.compile(r"[0-9a-f]{64}")
ROUTE_CHOICES = ("auto", "typesafe", "openrouter")
MAX_PURPOSE_CHARS = 80

CLAIM_BOUNDARY = (
    "Answers are Jev's probabilities for the questions sent, not approval, review, verification, "
    "or execution evidence. A policy_result is OMH's fixed rule over those answers, and it can only "
    "add a hold, a flag, or an objection."
)
EGRESS_DISCLOSURE = (
    "Sends `state` and every question's text to the route's host and bills the user's account; OMH "
    "adds nothing beyond `state` and the questions, so whatever `state` holds (commands, a working "
    "directory, file paths, source diffs, test or error output, file contents) leaves the machine. A "
    "configured HTTPS proxy sees the destination host."
)
_NON_ANSWER_NEXT_ACTION = (
    "Report the status to the user; answer the question yourself as main_model or leave it "
    "unanswered. A non-answer is never an answer and changes nothing."
)
_NEXT_ACTIONS = {
    STATUS_ANSWERED: "Report the numbers verbatim with the served model and cost; 0.4 to 0.6 is uncertain.",
    STATUS_CONSENT_NOT_OBSERVED: (
        "Nothing was sent. The user's message in this turn did not ask for Jev; offer the ask in one line "
        "naming what would be sent, and ask the user to reply `ask jev`."
    ),
    STATUS_KEY_MISSING: (
        "Nothing was sent. No route resolves: set TYPESAFE_API_KEY, or for OpenRouter set "
        "OPENROUTER_API_KEY and `{\"openrouter_route\": true}` in <omh_home>/jev/settings.json; "
        "`omh doctor` names the route."
    ),
    STATUS_KEY_UNRESOLVABLE: "Nothing was sent. The host did not resolve the key for this profile.",
    STATUS_INVALID_REQUEST: "Nothing was sent. Fix the named field and ask again.",
}

OMH_JEV_ASK_SCHEMA = {
    "name": "omh_jev_ask",
    "description": (
        "Ask Jev typed questions about a state. Jev is TypeSafe and non-generative: noul (yes/no), choice and "
        "score questions about a `state`, with the user's own key. Call only after the user asked for Jev in this turn; "
        "otherwise it returns consent_not_observed and sends nothing. "
        + EGRESS_DISCLOSURE
        + " Returns probabilities and confidence, or a non-answer status that is never an answer."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "state": {
                "description": (
                    "The material Jev judges: a string, an object, or an array of text. It is sent "
                    "verbatim; trim it to the evidence the questions need. Text that looks like a "
                    "credential is refused, not redacted."
                ),
            },
            "questions": {
                "type": "object",
                "description": (
                    "Free-form ask: id -> {type, instructions, criteria}. noul criteria {true, false} "
                    "(optional); choice criteria {option: description} (at most 255, include an "
                    "`unknown` option); score criteria [ordered levels] (2 to 10). Ids are not seen "
                    "by the model, so each instruction must stand on its own."
                ),
            },
            "route_question": {
                "type": "object",
                "description": (
                    "A route_question/v1 block from omh_interact, passed unchanged; its options are "
                    "sent as the Choice criteria and its question_digest is echoed back."
                ),
            },
            "preset": {
                "type": "string",
                "enum": list(PRESET_IDS),
                "description": (
                    "A versioned question set with a fixed rule ladder; OMH computes policy_result "
                    "from the answers. Presets always send the pinned version. `state` is an object "
                    "with the preset's fields."
                ),
            },
            "attempts_so_far": {
                "type": "integer",
                "minimum": 0,
                "description": (
                    "failure_triage/v1 only: how many times you already retried this command. You "
                    "supply the count; Jev is never asked to count."
                ),
            },
            "model": {
                "type": "string",
                "description": (
                    "Free-form asks only; default jev-latest. Pin jev-1.13.0 when you compare the "
                    "numbers against a tuned threshold."
                ),
            },
            "route": {
                "type": "string",
                "enum": list(ROUTE_CHOICES),
                "description": (
                    "auto (default) prefers TypeSafe. openrouter works only when the operator set "
                    "openrouter_route in <omh_home>/jev/settings.json. A forced route never falls back."
                ),
            },
            "purpose": {
                "type": "string",
                "description": "Short local label stored in the ledger; never sent.",
            },
        },
        "required": ["state"],
    },
}

_WITHHELD_FROM_OBSERVATION = frozenset({"state", "questions", "route_question"})


def omh_jev_ask_handler(
    args: dict[str, Any],
    *,
    transport: Transport | None = None,
    **kwargs: Any,
) -> str:
    if error := runtime_paths.tool_home_error(args):
        return json.dumps(error, sort_keys=True)
    observation = observe_plugin_tool_call("omh_jev_ask", _withheld(args), _withheld(kwargs))
    ask = _Ask(args, kwargs)
    result = ask.run(transport)
    return json.dumps(attach_public_observation(result, observation), sort_keys=True)


def jev_ask_available() -> bool:
    """`check_fn` for the host: True only when an ask could take a route now.

    `route_available` is bound with this module's other store names, not
    imported here: Hermes can evict the bundle from `sys.modules` while this
    check stays registered, and a call-time relative import then has no parent
    package (#1979).
    """
    try:
        home = default_omh_home()
    except Exception:  # noqa: BLE001 - classified: an unbound home keeps the tool hidden rather than failing registration
        return False
    return route_available(home) != ROUTE_NONE


@lru_cache(maxsize=1)
def _plugin_version() -> str:
    """The bundle's own manifest version for the User-Agent, or `unknown`."""
    try:
        text = (Path(__file__).resolve().parent.parent / "plugin.yaml").read_text(encoding="utf-8")[:4096]
    except OSError:
        return "unknown"
    match = re.search(r'(?m)^version:\s*["\']?([A-Za-z0-9._+-]+)', text)
    return match.group(1) if match else "unknown"


def _withheld(values: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if key not in _WITHHELD_FROM_OBSERVATION}


class _Ask:
    def __init__(self, args: Mapping[str, Any], kwargs: Mapping[str, Any]) -> None:
        self.args = args
        self.session_ref = host_session_id(dict(kwargs))
        self.ask_id = secrets.token_hex(8)
        self.route = ""
        self.model = ""
        # Set only after validation: an unknown preset string never reaches
        # the ledger, the result, or `policy_result`.
        self.preset = ""
        self.attempts_so_far = 0
        self.digest = ""
        self.questions: dict[str, dict[str, Any]] = {}
        self.state_sha256 = ""
        self.questions_sha256 = ""
        self.home = Path()

    def run(self, transport: Transport | None) -> dict[str, Any]:
        self.home = default_omh_home()
        if not consent_observed(self.session_ref):
            return self._finish(STATUS_CONSENT_NOT_OBSERVED)
        try:
            body_state, requested_route = self._prepare()
        except AskRequestError as error:
            return self._finish(STATUS_INVALID_REQUEST, error=str(error))
        try:
            self.route, key_name = resolve_route(requested_route, self.home)
            key = read_key(key_name) if key_name else ""
        except KeyUnresolvable as error:
            return self._finish(STATUS_KEY_UNRESOLVABLE, error=str(error))
        if self.route == ROUTE_NONE or not key:
            self.route = ""
            return self._finish(STATUS_KEY_MISSING)
        if _carries_route_key((body_state, self.questions), key):
            # Not even a hash of the refused material is kept.
            self.state_sha256 = self.questions_sha256 = ""
            return self._finish(
                STATUS_INVALID_REQUEST,
                error="credential_like_content: state or question text holds part of a configured route key; "
                "nothing was sent",
            )
        try:
            self.model = self._model_for_route()
            body = build_request_body(self.model, body_state, self.questions)
        except AskRequestError as error:
            return self._finish(STATUS_INVALID_REQUEST, error=str(error))
        sent = send_ask(
            route=self.route,
            key=key,
            body=body,
            user_agent=f"oh-my-hermes/{_plugin_version()}",
            transport=transport,
        )
        status = str(sent.get("status"))
        extra = {
            name: sent[name]
            for name in ("api_status", "attempts", "latency_ms", "retry_after_s", "api_error")
            if name in sent
        }
        if status != STATUS_ANSWERED:
            return self._finish(status, **extra)
        try:
            validated = validate_reply(self.questions, sent.get("reply") or {})
        except MalformedReply as error:
            return self._finish(STATUS_MALFORMED_RESPONSE, error=str(error), **extra)
        validated["served_model"] = safe_served_model(validated["served_model"], key)
        return self._finish(STATUS_ANSWERED, validated=validated, **extra)

    def _prepare(self) -> tuple[Any, str]:
        args = self.args
        requested_route = str(args.get("route") or "auto")
        if requested_route not in ROUTE_CHOICES:
            raise AskRequestError(f"route must be one of {', '.join(ROUTE_CHOICES)}")
        sources = [name for name in ("questions", "route_question", "preset") if args.get(name)]
        if len(sources) != 1:
            raise AskRequestError("send exactly one of questions, route_question, or preset")
        state = args.get("state")
        validate_state(state)
        self.attempts_so_far = _attempts_so_far(args.get("attempts_so_far"))
        requested_preset = args.get("preset")
        if requested_preset:
            if not isinstance(requested_preset, str) or requested_preset not in PRESETS:
                raise AskRequestError(f"preset must be one of {', '.join(PRESET_IDS)}")
            if args.get("model"):
                raise AskRequestError("a preset always sends the pinned version; omit model")
            fields = PRESETS[requested_preset].state_fields
            if not isinstance(state, Mapping) or not set(state) <= set(fields) or not state:
                raise AskRequestError(f"{requested_preset} state is an object with fields: {', '.join(fields)}")
            self.preset = requested_preset
            questions: dict[str, dict[str, Any]] = preset_questions(self.preset)
        elif args.get("route_question"):
            questions, self.digest = _project_route_question(args.get("route_question"))
        else:
            questions = dict(args.get("questions") or {})
        self.questions = validate_questions(questions)
        if _carries_credential_like_text(state) or _carries_credential_like_text(self.questions):
            raise AskRequestError(
                "credential_like_content: state or question text looks like a credential; nothing was sent"
            )
        self.state_sha256 = _sha256_json(state)
        self.questions_sha256 = _sha256_json(self.questions)
        return state, requested_route

    def _model_for_route(self) -> str:
        if self.preset:
            return PINNED_MODEL_BY_ROUTE[self.route]
        model = str(self.args.get("model") or DEFAULT_MODEL).strip()
        accepted = set(FIRST_PARTY_MODEL_IDS)
        if self.route == ROUTE_OPENROUTER:
            accepted |= set(OPENROUTER_ONLY_MODEL_IDS)
        if model not in accepted:
            raise AskRequestError(f"model must be one of {', '.join(sorted(accepted))} on this route")
        return model

    def _finish(self, status: str, *, validated: dict[str, Any] | None = None, error: str = "", **extra: Any) -> dict[str, Any]:
        answered = status == STATUS_ANSWERED and validated is not None
        usage: dict[str, Any] | None = None
        served_model = ""
        if answered and validated is not None:
            raw_usage = validated["usage"]
            usage = {
                "input_tokens": raw_usage["input_tokens"],
                "output_tokens": raw_usage["output_tokens"],
                **cost_for(self.route, raw_usage),
            }
            served_model = validated["served_model"]
        # Filled only on an exact hit: TypeSafe serves `jev-1.13.0`. A gateway
        # spelling such as `typesafe/jev-1.13-20260917` is not declared, and
        # resolving it would be a guess.
        contract = served_model if served_model == PINNED_MODEL_BY_ROUTE["typesafe"] else ""
        result: dict[str, Any] = {
            "schema_version": RESULT_SCHEMA_VERSION,
            "status": status if status in ASK_STATUSES else STATUS_MALFORMED_RESPONSE,
            "ok": answered,
            "retryable": status in RETRYABLE_STATUSES,
            "answers": validated["answers"] if answered and validated is not None else None,
            "ask_id": self.ask_id,
            "route": self.route,
            "model_requested": self.model,
            "served_model": served_model,
            "contract_model_id": contract,
            "contract_resolution": "exact" if contract else "unresolved",
            "attempts": int(extra.get("attempts", 0) or 0),
            "latency_ms": int(extra.get("latency_ms", 0) or 0),
            "usage": usage,
            "next_action": _NEXT_ACTIONS.get(status, _NON_ANSWER_NEXT_ACTION),
            "claim_boundary": CLAIM_BOUNDARY,
            "egress": EGRESS_DISCLOSURE,
        }
        for name in ("api_status", "retry_after_s", "api_error"):
            if name in extra and extra[name] not in (None, "", 0):
                result[name] = extra[name]
        if error:
            result["error"] = error
        if self.digest:
            result["question_digest"] = self.digest
        if self.preset:
            result["policy_result"] = policy_result(
                self.preset,
                status=result["status"],
                answers=result["answers"],
                context={"attempts_so_far": self.attempts_so_far},
            )
        record = self._ledger_record(result)
        if answered:
            # What `omh_route_answer` checks a provenance claim against; the
            # ledger file is not, since anything with a file tool can write it.
            remember_answered_ask(record)
        result["ledger"] = "written" if append_ledger_record(self.home, record) else "unavailable"
        return result

    def _ledger_record(self, result: Mapping[str, Any]) -> dict[str, Any]:
        purpose = "".join(char for char in str(self.args.get("purpose") or "") if char.isprintable())
        # The label is model-supplied: key-shaped text is dropped, not stored.
        if purpose and contains_credential_like_material(purpose):
            purpose = ""
        record: dict[str, Any] = {
            "schema_version": LEDGER_SCHEMA_VERSION,
            "ask_id": self.ask_id,
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "session_ref": self.session_ref[:160],
            "route": self.route,
            "model_requested": self.model,
            "served_model": result.get("served_model", ""),
            "contract_model_id": result.get("contract_model_id", ""),
            "status": result["status"],
            "api_status": int(result.get("api_status", 0) or 0),
            "attempts": result["attempts"],
            "latency_ms": result["latency_ms"],
            "question_count": len(self.questions),
            "question_types": sorted({str(question.get("type")) for question in self.questions.values()}),
            "state_sha256": self.state_sha256,
            "questions_sha256": self.questions_sha256,
            "question_digest": self.digest,
            "preset": self.preset,
            "usage": result.get("usage"),
            "purpose": purpose[:MAX_PURPOSE_CHARS],
        }
        policy = result.get("policy_result")
        if isinstance(policy, Mapping):
            record["policy_outcome"] = policy.get("outcome", "")
        answers = result.get("answers")
        if self.digest and isinstance(answers, Mapping):
            # What `omh_route_answer` compares an `omh_jev_ask` claim against:
            # the Choice Jev made and its probabilities. Option ids are
            # workflow names, not user text.
            choice = answers.get(ROUTE_CHOICE_QUESTION_ID)
            if isinstance(choice, Mapping):
                record["route_choice"] = str(choice.get("choice", ""))
                record["route_choice_probabilities"] = dict(choice.get("probabilities") or {})
            record["route_fits"] = {
                str(question_id)[len(FIT_QUESTION_PREFIX):]: answer.get("noul")
                for question_id, answer in answers.items()
                if str(question_id).startswith(FIT_QUESTION_PREFIX) and isinstance(answer, Mapping)
            }
        return record


def _project_route_question(block: object) -> tuple[dict[str, dict[str, Any]], str]:
    """route_question/v1 -> the API's question map, plus the digest to echo.

    The block stores Choice options under `options`; the API reads `criteria`.
    That rename is the only transform: ids (`route_choice`, `fits::<skill>`)
    and text pass through unchanged.
    """
    if not isinstance(block, Mapping) or block.get("schema_version") != "route_question/v1":
        raise AskRequestError("route_question must be a route_question/v1 block")
    digest = block.get("question_digest")
    raw = block.get("questions")
    if not isinstance(digest, str) or not _QUESTION_DIGEST.fullmatch(digest) or not isinstance(raw, Mapping):
        raise AskRequestError("route_question needs a 64-hex question_digest and questions")
    projected: dict[str, dict[str, Any]] = {}
    for question_id, question in raw.items():
        if not isinstance(question, Mapping):
            raise AskRequestError(f"route_question {question_id!r} is not an object")
        entry: dict[str, Any] = {"type": question.get("type"), "instructions": question.get("instructions")}
        if question.get("type") == "choice":
            entry["criteria"] = dict(question.get("options") or {})
        projected[str(question_id)] = entry
    return projected, digest


def route_question_questions_sha256(block: object) -> str:
    """The `questions_sha256` an ask of this route_question/v1 block records.

    `omh_route_answer` compares it with an answered ask's ledger record, so a
    claim of Jev's provenance names the question Jev was actually sent. ""
    when the ask path would refuse the block, since such a block was never sent.
    """
    try:
        return _sha256_json(validate_questions(_project_route_question(block)[0]))
    except AskRequestError:
        return ""


def _attempts_so_far(value: object) -> int:
    """The model-supplied retry count, validated before any socket opens."""
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AskRequestError("attempts_so_far must be a non-negative integer")
    return value


def _carries_credential_like_text(value: object) -> bool:
    if isinstance(value, str):
        return bool(value) and contains_credential_like_material(value)
    if isinstance(value, Mapping):
        # Keys too: a model can put a pasted secret in a field name, and a key
        # is sent exactly like a value.
        return any(
            _carries_credential_like_text(name) or _carries_credential_like_text(item)
            for name, item in value.items()
        )
    if isinstance(value, list):
        return any(_carries_credential_like_text(item) for item in value)
    return False


def _carries_route_key(value: object, route_key: str) -> bool:
    """Whether any text in `value` holds a key window of any configured route key.

    The pattern heuristic misses a key whose vendor prefix was stripped or
    whose characters were spaced apart, and with both keys set an ask on one
    route could carry the other vendor's key. Every string -- keys and values
    -- is joined and compared folded with whitespace removed
    (`carries_key_fragment`). A key the host will not read for this profile
    is one the model cannot read through it either, so it is skipped.
    """
    keys = [route_key]
    for name in ROUTE_KEY_NAMES.values():
        try:
            keys.append(read_key(name))
        except KeyUnresolvable:
            continue
    text = "".join(_strings(value))
    return any(key and carries_key_fragment(text, key) for key in keys)


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        return [text for name, item in value.items() for text in (*_strings(name), *_strings(item))]
    if isinstance(value, (list, tuple)):
        return [text for item in value for text in _strings(item)]
    return []


def _sha256_json(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode("utf-8")).hexdigest()


__all__ = ["CLAIM_BOUNDARY", "EGRESS_DISCLOSURE", "OMH_JEV_ASK_SCHEMA", "jev_ask_available", "omh_jev_ask_handler"]
