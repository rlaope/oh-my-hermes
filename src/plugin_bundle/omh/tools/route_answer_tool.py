from __future__ import annotations

from .. import runtime_paths

import hashlib
import json
from typing import Any

from ..host_observation import (
    attach_public_observation,
    host_session_id,
    observe_plugin_tool_call,
)
from ..jev_ask_store import answered_ask
from ..route_question_mode import read_route_question_mode
from ..route_answer_store import (
    ANSWER_VERDICT_INVALID,
    ANSWERED_BY_OMH_JEV_ASK,
    ANSWERED_BY_VALUES,
    CLAIM_BOUNDARY,
    RouteAnswerContendedError,
    RouteAnswerStoreError,
    RouteAnswerValidationError,
    build_route_answer_record,
    write_route_answer,
)
from ..runtime_reader import default_omh_home
from .jev_ask_tool import ROUTE_CHOICE_QUESTION_ID as _ROUTE_CHOICE_ID
from .jev_ask_tool import route_question_questions_sha256

OMH_ROUTE_ANSWER_SCHEMA = {
    "name": "omh_route_answer",
    "description": (
        "Record an answer to an OMH route question. The route_question is the one OMH attached to an undecidable route "
        "(omh_interact route.route_question, or omh chat route-hint). Recording an answer "
        "changes no route and dispatches nothing: the deterministic route stays in force "
        "either way, and the record exists so the answer can be scored against OMH's own "
        "routing corpora with `omh chat route-questions score`. Answer the two question "
        "kinds separately: the Choice picks which workflow fits best among the options, "
        "the yes/no fit questions each judge one workflow on its own. A recorded answer is "
        "a routing judgment the caller declares, never execution, review, CI, or merge evidence."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "question_digest": {
                "type": "string",
                "description": (
                    "The question_digest carried by the route_question block being answered. "
                    "It joins this answer to the exact question it answers; an answer whose "
                    "digest names a different question is refused rather than recorded."
                ),
            },
            "answered_by": {
                "type": "string",
                "enum": list(ANSWERED_BY_VALUES),
                "description": (
                    "Who produced this answer. main_model means you answered it yourself "
                    "while reading the question, and the confidence recorded beside it is "
                    "self-reported. jev_plugin means an installed third-party Jev-class plugin "
                    "produced it and OMH is recording a number it did not observe; OMH never "
                    "calls such a plugin. omh_jev_ask means OMH's own omh_jev_ask call answered "
                    "it: pass that call's ask_id and Jev's route_choice, probabilities, and fits as "
                    "returned; refused unless this OMH process sent and Jev answered that ask, in "
                    "this session, for this question_digest, with that same Choice."
                ),
            },
            "route_choice": {
                "type": "string",
                "description": (
                    "The option the Choice answers with: one workflow name from the "
                    "question's options, or `none` when the request asks for no OMH workflow."
                ),
            },
            "choice_probabilities": {
                "type": "object",
                "description": (
                    "Optional per-option probability for the Choice, keyed by option name, "
                    "each between 0 and 1. Omit it when the answerer produced none; an "
                    "invented number is worse than an absent one."
                ),
            },
            "fits": {
                "type": "object",
                "description": (
                    "The yes/no fit answers, keyed by workflow name, each a probability "
                    "between 0 and 1 that the request asks for the work that workflow does. "
                    "Judge each workflow on its own: these are absolute judgments and carry "
                    "no relation to the Choice, so fitting nothing while naming a Choice is "
                    "a legal answer and is recorded as it stands. The strongest fit decides "
                    "the recorded action against the question's own thresholds."
                ),
            },
            "message": {
                "type": "string",
                "description": (
                    "Optional: the request the question was built from. It is used twice, to "
                    "re-derive the question and confirm the digest and to derive the request "
                    "hash the record is joined on, and the text itself is never stored. "
                    "Without it the record says digest_verified is false."
                ),
            },
            "message_sha256": {
                "type": "string",
                "description": (
                    "Optional: the sha256 hex of the request, when the question block carries "
                    "it and the request text is not at hand. Supply this or `message`, not "
                    "both with different values; supplying `message` is preferred because OMH "
                    "then derives the hash itself. Without either, the record identifies no "
                    "request and can only be scored by digest, which several different "
                    "requests can share."
                ),
            },
            "source": {
                "type": "string",
                "enum": ["generic", "discord", "slack", "telegram", "hermes"],
                "description": (
                    "Chat surface the request arrived on, used only to re-derive the "
                    "question when a message is supplied for digest verification."
                ),
            },
            "ask_id": {
                "type": "string",
                "description": (
                    "Required with answered_by omh_jev_ask: the ask_id that omh_jev_ask returned."
                ),
            },
            "note": {
                "type": "string",
                "description": (
                    "Optional one-line reason for the answer, stored with the record for a "
                    "human reading it later."
                ),
            },
        },
        "required": ["question_digest", "answered_by", "route_choice"],
    },
}

_RESULT_SCHEMA_VERSION = "omh_route_answer_result/v1"
_DEFAULT_SOURCE = "hermes"


def omh_route_answer_handler(args: dict[str, Any], **kwargs) -> str:
    if error := runtime_paths.tool_home_error(args):
        return json.dumps(error, sort_keys=True)
    observation = observe_plugin_tool_call(
        "omh_route_answer", _without_message(args), _without_message(kwargs)
    )
    payload: dict[str, Any] = {
        "schema_version": _RESULT_SCHEMA_VERSION,
        "claim_boundary": CLAIM_BOUNDARY,
    }
    # The write binds to the environment-configured home only. A caller-chosen
    # path would turn a metadata recorder into an arbitrary-location
    # file-create primitive, which is the same refusal `omh_todo` makes.
    if str(args.get("omh_home", "") or ""):
        return _result(
            payload,
            observation,
            status="invalid_request",
            error="omh_home override is not accepted; the record is written to the configured OMH home",
        )
    # Hermes passes its session id as a keyword on every dispatch. It keys the
    # record together with the question digest, so two questions answered in
    # one session are two records rather than one overwriting the other.
    session_ref = host_session_id(kwargs)
    try:
        message_sha256 = _resolved_message_sha256(args)
    except ValueError as error:
        return _result(payload, observation, status="invalid_request", error=str(error))
    verified, verification, mismatch, question = _verify_digest(args)
    if mismatch:
        return _result(
            payload,
            observation,
            status="digest_mismatch",
            error=(
                "question_digest does not match the route question for this message; "
                "nothing was recorded. Re-read route.route_question and answer that digest."
            ),
            digest_verification=verification,
        )
    if question is not None and str(args.get("route_choice") or "").strip() not in _choice_options(question):
        # Whoever answered, a verified digest names a question with known
        # options, and a Choice outside them answers some other question.
        return _result(
            payload,
            observation,
            status="invalid_request",
            error="route_choice is not one of the options of the question this digest names; nothing was recorded",
            digest_verification=verification,
        )
    if str(args.get("answered_by") or "").strip() == ANSWERED_BY_OMH_JEV_ASK:
        refusal = _omh_jev_ask_claim_refusal(args, session_ref, question)
        if refusal:
            return _result(payload, observation, status="invalid_request", error=refusal)
    omh_home = default_omh_home()
    try:
        record = build_route_answer_record(
            question_digest=args.get("question_digest"),
            answered_by=args.get("answered_by"),
            route_choice=args.get("route_choice"),
            fits=args.get("fits"),
            choice_probabilities=args.get("choice_probabilities"),
            note=args.get("note", ""),
            session_ref=session_ref,
            message_sha256=message_sha256,
            digest_verified=verified,
            ask_id=args.get("ask_id", ""),
            # Read from the OMH config of the home the record lands in, never
            # from an argument: the model does not get to say which mode it is in.
            mode_reading=read_route_question_mode(omh_home),
            question_options=sorted(_choice_options(question)) if question is not None else None,
        )
    except RouteAnswerValidationError as error:
        return _result(payload, observation, status="invalid_request", error=str(error))
    try:
        write_route_answer(omh_home, record)
    except RouteAnswerContendedError as error:
        # Before the generic branch: `invalid_request` tells a caller its
        # payload was wrong, and a caller that believes that rewrites an
        # answer that was simply racing another writer for a few milliseconds.
        return _result(payload, observation, status="contended", error=str(error))
    except RouteAnswerStoreError as error:
        return _result(payload, observation, status="store_unavailable", error=str(error))
    payload["record"] = record
    if record.get("answer_verdict") == ANSWER_VERDICT_INVALID:
        # Written, so the rate is countable, and refused as an opinion. The
        # wording tells the caller what a refusal means for the turn: nothing.
        return _result(
            payload,
            observation,
            status=ANSWER_VERDICT_INVALID,
            error=(
                "the answer contradicts itself ("
                + ", ".join(record.get("invalid_answer_reasons") or [])
                + ") and was recorded as no opinion; the route is unchanged, so continue the turn"
            ),
            digest_verification=verification,
        )
    return _result(payload, observation, status="recorded", digest_verification=verification)


# Probabilities are compared after a JSON round trip, so only float noise may differ.
_PROBABILITY_TOLERANCE = 1e-9


def _omh_jev_ask_claim_refusal(args: dict[str, Any], session_ref: str, question: dict[str, Any] | None) -> str:
    """Why an `answered_by: omh_jev_ask` record is refused, or "" when an answered ask backs it.

    The record of a route-question ask this process sent and Jev answered
    holds the Choice Jev made and its probabilities (`answered_ask`). The
    claim must name that same ask, from this same session, for this same
    digest, and repeat Jev's Choice and any probability it supplies.
    Otherwise the model could file its own numbers under Jev's provenance.
    The ledger file is not consulted: a model with a file tool can append a
    row to it.

    The digest alone does not bind the ask to its question: `omh_jev_ask`
    echoes whatever digest the block carries, and the block does not carry
    the request hash the digest is built from. So the claim needs `message`,
    the question is re-derived from it (`question`), and the ask must have
    sent exactly that question's projection (`questions_sha256`).
    """
    ask = answered_ask(str(args.get("ask_id") or ""))
    if ask is None:
        return (
            "answered_by omh_jev_ask needs the ask_id of an omh_jev_ask call this process sent and Jev "
            "answered; there is none, so nothing was recorded"
        )
    if str(ask.get("question_digest") or "") != str(args.get("question_digest") or "").strip():
        return "that ask answered a different question_digest; nothing was recorded"
    if question is None:
        return (
            "answered_by omh_jev_ask needs the message, so the question this digest names can be "
            "re-derived and checked against what the ask sent; nothing was recorded"
        )
    expected = route_question_questions_sha256(question)
    if not expected or str(ask.get("questions_sha256") or "") != expected:
        return "that ask sent a different question than this digest names; nothing was recorded"
    if str(ask.get("session_ref") or "") != session_ref[:160]:
        return "that ask was made in a different session; nothing was recorded"
    if str(args.get("route_choice") or "").strip() != str(ask.get("route_choice") or ""):
        return "route_choice differs from the Choice Jev returned for that ask; nothing was recorded"
    for field, ledger_field in (("choice_probabilities", "route_choice_probabilities"), ("fits", "route_fits")):
        mismatch = _numbers_mismatch(args.get(field), ask.get(ledger_field))
        if mismatch:
            return f"{field}[{mismatch!r}] differs from what Jev returned for that ask; nothing was recorded"
    return ""


def _numbers_mismatch(supplied: object, recorded: object) -> str:
    """The first supplied key whose number is not the ledger's, or "" when all match."""
    if supplied is None:
        return ""
    if not isinstance(supplied, dict) or not isinstance(recorded, dict):
        return "*"
    for key, value in supplied.items():
        expected = recorded.get(key)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or isinstance(expected, bool)
            or not isinstance(expected, (int, float))
            or abs(float(value) - float(expected)) > _PROBABILITY_TOLERANCE
        ):
            return str(key)
    return ""


def _without_message(values: dict[str, Any]) -> dict[str, Any]:
    """The same mapping with `message` withheld from the observation lane.

    `_observation_metadata` lifts `message` out of a tool's own arguments and
    the observation writer puts it verbatim into
    `runtime/plugin_host_observations.jsonl` and `runtime/state.json` whenever
    the caller also supplies `observation.host`. That is right for
    `omh_interact`, whose subject IS the message. Here the schema tells the
    model the request text is used once to confirm the digest and never
    stored, and that sentence is the argument for supplying it -- so the
    promise is kept by withholding the field rather than by softening the
    sentence. The request still reaches the record as a hash, which is what
    the record needs and all it needs.
    """
    return {key: value for key, value in values.items() if key != "message"}


def _resolved_message_sha256(args: dict[str, Any]) -> str:
    """The request hash this record is joined on, or "" when none was given.

    Derived from `message` when the caller sent one, because a hash OMH
    computed is worth more than one it was handed. A caller that has the hash
    but not the text may send `message_sha256` instead. Sending both with
    different values is refused rather than resolved in someone's favour: the
    two name different requests, and picking one would record an answer
    against a request the caller did not mean.
    """
    message = str(args.get("message") or "").strip()
    supplied = str(args.get("message_sha256") or "").strip()
    derived = hashlib.sha256(message.encode("utf-8")).hexdigest() if message else ""
    if derived and supplied and derived != supplied:
        raise ValueError(
            "message and message_sha256 describe different requests; send one of them, "
            "or send a message_sha256 that is the sha256 of the message"
        )
    return derived or supplied


def _choice_options(question: dict[str, Any]) -> set[str]:
    """The option names of a route_question/v1 block's Choice."""
    questions = question.get("questions")
    choice = questions.get(_ROUTE_CHOICE_ID) if isinstance(questions, dict) else None
    options = choice.get("options") if isinstance(choice, dict) else None
    return {str(name) for name in options} if isinstance(options, dict) else set()


def _verify_digest(args: dict[str, Any]) -> tuple[bool, str, bool, dict[str, Any] | None]:
    """(verified, verification, mismatch, the matched question block) for the supplied digest.

    Verification needs the core router, which this bundle may be running
    without -- Hermes loads this directory with its own interpreter. The
    import is therefore lazy and guarded, and its absence degrades this one
    field rather than the call: an unverified record is still a record the
    scorer can read, while a mismatch is refused because a record joined to
    the wrong question measures the wrong thing.

    One message produces more than one question, because the shortlist the
    question is built from is cut to the caller's candidate limit and the
    digest is the shortlist's. The surfaces that carry the question disagree
    on that limit already -- `omh chat route` and `omh_interact` ask for
    three candidates, `omh chat route-hint` for two -- so verifying against a
    single limit would refuse an answer to a question OMH itself handed out.
    Every reachable question is therefore re-derived, over the closed range
    the handoff's own `MAX_CANDIDATES` bounds, and a mismatch means the digest
    names a question this message cannot produce at any of them.
    """
    message = str(args.get("message") or "").strip()
    digest = str(args.get("question_digest") or "").strip()
    if not message or not digest:
        return False, "not_requested", False, None
    source = str(args.get("source") or _DEFAULT_SOURCE)
    try:
        from omh.routing.candidate_handoff import MAX_CANDIDATES
        from omh.routing.chat import route_chat_message
    except (ImportError, ModuleNotFoundError):
        # Deliberately not `exc.name != "omh"`: that name is the MISSING one,
        # which is the bare package only when the whole package is gone. A
        # missing SUBMODULE reports `omh.routing.route_question`, so the name
        # check re-raised on the one case this repo documents twice -- a
        # current bundle beside a lagging package, and the strict-editable
        # `build/` tree where a new module inside an existing package is
        # invisible to the install. `loop_bridge` catches the pair for the
        # same reason.
        return False, "unavailable_without_package_backend", False, None
    found = False
    for limit in range(1, MAX_CANDIDATES + 1):
        try:
            route = route_chat_message(message, source=source, limit=limit)
        except (ValueError, KeyError):
            # An unsupported source or a message the router refuses is the
            # caller's input, not a verdict about the digest.
            return False, "message_not_routable", False, None
        question = route.get("route_question")
        if not isinstance(question, dict):
            continue
        current = str(question.get("question_digest") or "")
        if not current:
            continue
        found = True
        # A match settles it: the remaining passes can only reach the same
        # digest again, so the common case is one router pass and not four.
        if current == digest:
            return True, "matched", False, question
    if not found:
        return False, "no_route_question_for_message", False, None
    return False, "mismatch", True, None


def _result(
    payload: dict[str, Any],
    observation: dict[str, Any] | None,
    *,
    status: str,
    error: str = "",
    digest_verification: str = "",
) -> str:
    payload["status"] = status
    if error:
        payload["error"] = error
    if digest_verification:
        payload["digest_verification"] = digest_verification
    return json.dumps(attach_public_observation(payload, observation), sort_keys=True)
