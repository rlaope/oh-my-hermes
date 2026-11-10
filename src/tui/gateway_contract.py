"""Everything the OMH TUI assumes about Hermes' `tui_gateway` protocol, in one place.

The gateway's own contract (`tui_gateway/contracts/`, generated into an OpenRPC
file under `apps/`) is not packaged in a Hermes wheel, so it cannot be read at
runtime. What this module declares instead is the subset the TUI uses.
Outbound: the methods it calls and the keys it sends, and how it answers each
server-to-client request. A drift in either surfaces at runtime as a param
rejection (4000) or an unknown method (-32601), which the client treats as
"this Hermes no longer speaks what the TUI was built for", except on the
calls in OPTIONAL_METHODS, where it is a notice and the session goes on. Inbound: the event
names, fields and values the TUI keys on that the OMH TUI v2 batch added (the
subagent events, `session.info`'s yolo and effort, `subagent.tail`'s result,
`session.redirect`'s and `session.steer`'s status), read from here by the app and the roster, and every
event type, split into the ones the TUI handles and the ones it reads nothing
from. An event type the TUI does not handle is ignored; a submitted turn that
brings no transcript, subagent or error event, and three of types neither set
declares, gets one notice (`App._watch_turn`), and `omh doctor` prints the
installed Hermes commit next to the one below. A renamed field still reads as
absent. The older transcript events' fields are
read where they are folded (`transcript`, `subagents`).

Declared against Hermes 6c61c3e27d (2026-10-07).
"""

from __future__ import annotations

from dataclasses import dataclass
import unicodedata

DECLARED_AGAINST_HERMES = "6c61c3e27d"

# JSON-RPC error codes the gateway uses that change what the client does.
PARAM_REJECTED = 4000  # Pydantic `extra="forbid"`: a key this Hermes does not know
METHOD_NOT_FOUND = -32601  # also the client's own answer to a request it does not support
NOT_MINE = 4018  # `slash.exec` refusing a command that `command.dispatch` owns
REDIRECT_UNSUPPORTED = 4010  # `session.redirect` to an agent without active-turn redirect: it may still take a steer

DRIFT_ERROR_CODES = frozenset({PARAM_REJECTED, METHOD_NOT_FOUND})
# Calls a session does without: on these a drift error is a notice and the session goes on. On every other call
# made during a session it ends the session (`App._on_response`). An older Hermes (0250c8bcae: SkillsReloadParams
# takes no field) rejects `skills.reload {session_id}` with 4000, which must not cost the person their session.
# `config.get` is answered after the first frame and only sets the configured effort and Vim mode, which have defaults.
# `session.list` is asked unprompted at the start of a fresh session, only to name the last one, and
# `model.options` only fills `/model`'s picker and reads Hermes' configured default model, while
# `/model <name>` still switches. `image.render` only draws a preview under the prompt: a Hermes without it answers
# METHOD_NOT_FOUND, the TUI keeps the label row, and the session goes on.
OPTIONAL_METHODS = frozenset(
    {"commands.catalog", "config.get", "image.render", "model.options", "session.list", "skills.reload"}
)

# Methods the TUI calls, with the only keys it ever sends. Sending a key outside
# this map is a bug: a Hermes that does not know it rejects the whole call.
CLIENT_METHODS: dict[str, frozenset[str]] = {
    "client.capabilities": frozenset({"server_requests"}),
    "config.get": frozenset({"key"}),
    # The session binds both to its profile and workspace, so project-local skills are listed and rescanned.
    "commands.catalog": frozenset({"session_id"}),
    "skills.reload": frozenset({"session_id"}),
    "complete.path": frozenset({"word", "session_id"}),
    "session.create": frozenset({"cols", "cwd"}),
    "session.resume": frozenset({"session_id", "cols"}),
    "session.close": frozenset({"session_id"}),
    "session.interrupt": frozenset({"session_id"}),
    # Typed text into the running turn, sent now; see STEER_STATUSES for the answer. A refusal (`rejected`, or an
    # error) puts the text in the TUI's queue while a turn runs, and sends it as a prompt only when the session is
    # idle. `session.redirect` is what the send-now key sends; `session.steer` is `/steer`'s, and the send-now key's
    # where the agent answers REDIRECT_UNSUPPORTED or a redirect is `rejected` while its turn still runs.
    "session.redirect": frozenset({"session_id", "text"}),
    "session.steer": frozenset({"session_id", "text"}),
    # See CONFIG_SET_VALUES: `scope` is deliberately not declared. `confirm_expensive_model` goes only with a model,
    # once the person picked "switch anyway" after Hermes answered `confirm_required`.
    "config.set": frozenset({"key", "value", "session_id", "confirm_expensive_model"}),
    # `title`: an exact-title lookup, which `/sessions <title>` asks after a shared gateway refused the title as an id;
    # a gateway that does not know it answers with its normal listing, which the TUI scans the same way.
    "session.list": frozenset({"limit", "title"}),
    # Bare `/model`: the providers and models Hermes offers this session, for the picker (`refresh` for
    # `/model --refresh`: Hermes asks the providers again). The pick goes back as `config.set model`. Asked
    # without a session, the answer's `model` and `provider` are the profile's configured default.
    "model.options": frozenset({"session_id", "refresh"}),
    # Read-only: the last 16 KB of one child's live transcript, for the agent log view. See `call_problem`.
    "subagent.tail": frozenset({"session_id", "subagent_id"}),
    # The two actions on one subagent, each on the person's keypress in the agent list
    # (docs/OMH-TUI-BOUNDARY.md): `x` once a second `x` confirms, and `s` with text the person then types and
    # sends. Hermes answers `found` (false when the child had already finished) and, for a steer, `status`
    # (STEER_QUEUED or STEER_REJECTED).
    "subagent.interrupt": frozenset({"session_id", "subagent_id"}),
    "subagent.steer": frozenset({"session_id", "subagent_id", "text"}),
    # A rewind (Esc Esc, /rewind) adds both truncation keys; see `call_problem`. Hermes refuses a truncation
    # without `confirm_truncate` (4029) and an ordinal one on a durable session (4004).
    "prompt.submit": frozenset({"session_id", "text", "queued", "truncate_before_row_id", "confirm_truncate"}),
    # The durable display transcript with row ids: what the rewind picker lists and redraws from.
    "session.history": frozenset({"session_id"}),
    # Attachments: the gateway resolves and stages the file the TUI names by its path; the TUI then reads the bytes
    # of the file Hermes staged and has it let go of it (`image.detach`), until a prompt stages them again below.
    "image.attach": frozenset({"session_id", "path"}),
    # The bytes the TUI keeps for an image token, staged for the one prompt that goes with it (Hermes writes its own
    # file and answers its path, which `image.detach` then names).
    "image.attach_bytes": frozenset({"session_id", "filename", "content_base64"}),
    "image.detach": frozenset({"session_id", "path"}),
    # Read-only inline preview of an image Hermes staged for the person (Hermes' `image.render`, `ImageRenderParams`
    # in `tui_gateway/contracts/config_free_tier_control.py`, added in Hermes d4ac2edd5d). The gateway caps it at
    # 64 columns by 16 rows and applies `display.inline_images`.
    "image.render": frozenset({"path", "cols", "rows", "graphics", "terminal"}),
    "clipboard.paste": frozenset({"session_id"}),
    "input.detect_drop": frozenset({"session_id", "text"}),
    "slash.exec": frozenset({"command", "session_id"}),
    # The person's own `!command` (docs/OMH-TUI-BOUNDARY.md: nothing else goes this way). Hermes runs it with a
    # 30 s limit, refuses dangerous and hardline commands (4005), keeps it out of the model's context, and redacts
    # the output.
    "shell.exec": frozenset({"command"}),
    "command.dispatch": frozenset({"name", "arg", "session_id"}),
}

# The reasoning efforts Hermes takes (`hermes_constants.VALID_REASONING_EFFORTS`), and `none` for thinking off.
REASONING_LEVELS = ("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra")

# The `config.set` keys the TUI sets, both for one session, with the only values it sends: `yolo`
# (approvals off) and `reasoning` (the effort). Hermes applies either one wider when it cannot tie
# the call to a session: with no `session_id`, yolo sets `HERMES_YOLO_MODE` in the gateway's process
# environment and reasoning rewrites config.yaml, and `scope: "global"` writes `approvals.mode` for
# good. A blank yolo value toggles whatever the state is, and `reasoning` with show, hide, on, off,
# full or clamp is a display setting Hermes writes to config.yaml. So every call carries the session
# id and one of these values, and `scope` is not a key the TUI can send at all.
CONFIG_SET_VALUES: dict[str, frozenset[str]] = {
    "yolo": frozenset({"on", "off"}),
    "reasoning": frozenset(REASONING_LEVELS),
}
CONFIG_SET_SESSION_SCOPE = "session"  # what a yolo answer's `scope` must say
# `config.set model` switches the session's model, as Ink's `/model` does; over a shared gateway the attach
# adapter sends it as the owner's `session.mutate`. Its value is only ever `model_switch_value`'s: a model and
# a provider slug, each one plain word, then `--session` unless the person typed `/model <name>` without it.
# Hermes reads `--global` as "every new session's default" and `--once` as "the next turn only", and no value
# the TUI sends can carry either. Without `--session` Hermes' stdio entry applies its own rule
# (`resolve_persist_behavior`: `model.persist_switch_by_default`), as for its own typed `/model`.
CONFIG_SET_MODEL = "model"
MODEL_PROVIDER_FLAG = "--provider"
MODEL_SESSION_FLAG = "--session"


def plain_word(value: object) -> str:
    """`value` when it is one plain word a command line carries as one argument; "" otherwise.

    It may not start with a dash of any kind (Unicode category Pd, `-` and the en and em dashes among them):
    Hermes splits `/model`'s arguments on whitespace and reads a token that starts with `--`, or with one of
    the dashes U+2012 to U+2015 before a flag word, as a flag.
    """
    if not isinstance(value, str) or not value or unicodedata.category(value[0]) == "Pd":
        return ""
    return value if all(char.isprintable() and not char.isspace() for char in value) else ""


def model_switch_value(model: object, provider: object = "", session: bool = True) -> str:
    """What `config.set model` takes to switch to `model` on `provider`: this session only with `session`.

    Without it, Hermes' own rule decides whether the switch also persists, as
    for `/model <name>` typed without `--session`. "" when the model, or a
    provider that is given, is not one plain word.
    """
    name, slug = plain_word(model), plain_word(provider)
    if not name or (provider and not slug):
        return ""
    words = [name, MODEL_PROVIDER_FLAG, slug] if slug else [name]
    return " ".join([*words, MODEL_SESSION_FLAG] if session else words)


def model_switch_parts(value: object) -> tuple[str, str] | None:
    """The model and provider of a value `model_switch_value` made; None for any other value."""
    words = value.split(" ") if isinstance(value, str) else []
    session = bool(words) and words[-1] == MODEL_SESSION_FLAG
    named = words[:-1] if session else words
    if len(named) == 1:
        parts = (named[0], "")
    elif len(named) == 3 and named[1] == MODEL_PROVIDER_FLAG:
        parts = (named[0], named[2])
    else:
        return None
    built = model_switch_value(*parts, session=session)
    return parts if built and built == value else None

# Events whose envelope `session_id` is not the live session are dropped, except
# these: they belong to the gateway, not to a session.
GATEWAY_SCOPED_EVENT_PREFIX = "gateway."

# ── inbound: what the TUI keys on in what Hermes sends ──

# The `subagent.*` events (`tui_gateway/contracts/events.py`, one `SubagentEventPayload` each, all built by
# `tool_progress._progress_subagent`). The app hands every event under the prefix to the roster, which folds
# these six; `subagent.text` is mirrored to the child's own session and never reaches the parent's.
SUBAGENT_EVENT_PREFIX = "subagent."
SUBAGENT_SPAWN_REQUESTED = "subagent.spawn_requested"
SUBAGENT_START = "subagent.start"
SUBAGENT_PROGRESS = "subagent.progress"
SUBAGENT_THINKING = "subagent.thinking"
SUBAGENT_TOOL = "subagent.tool"
SUBAGENT_COMPLETE = "subagent.complete"
SUBAGENT_EVENTS = (
    SUBAGENT_SPAWN_REQUESTED, SUBAGENT_START, SUBAGENT_PROGRESS, SUBAGENT_THINKING, SUBAGENT_TOOL, SUBAGENT_COMPLETE,
)

# The event types the TUI handles. `App._on_event` takes APP_EVENTS itself, `Transcript` folds TRANSCRIPT_EVENTS
# and the roster SUBAGENT_EVENTS; `test_tui_gateway_contract` holds each of the three to these names.
APP_EVENTS = (
    "request.cancel", "approval.cancelled", "session.info", "session.usage", "connection.request", "error",
    "notification.show", "notification.clear", "session.title", "todo.updated", "review.summary",
    "session.control.update", "background.complete", "btw.complete",
    # Newer than 6c61c3e27d: `skills.changed` (a skill root moved; Ink refetches the catalog) and
    # `session.replay_gap` (`gateway/session_events.py`, sent raw: the gateway dropped this viewer's subscription for
    # falling behind and sends nothing more for the session until it resumes; Ink resumes it).
    "skills.changed", "session.replay_gap",
)
TRANSCRIPT_EVENTS = (
    "message.start", "message.delta", "message.interim", "message.complete", "thinking.delta", "reasoning.delta",
    "reasoning.available", "tool.generating", "tool.start", "tool.complete", "status.update", "moa.reference",
    "moa.progress", "moa.phase",
)
HANDLED_EVENTS = frozenset((*APP_EVENTS, *TRANSCRIPT_EVENTS, *SUBAGENT_EVENTS))
# The rest of the 77 event types Hermes 6c61c3e27d registers (`tui_gateway.contracts.registry.EVENTS`). The event
# loop reads nothing from these; `gateway.ready` is read once, by the client at startup (`gateway.READY_EVENT`).
UNREAD_EVENTS = frozenset({
    "agent.terminal.output", "billing.step_up.verification", "bot_relay.outbox.pending",
    "browser.controller.cancel", "browser.controller.command", "browser.progress",
    "connection.update", "cron.changed", "display.install.done", "display.install.log", "display.lease",
    "display.status", "free_tier.challenge", "gateway.ready", "layout.apply", "message.reaction",
    "moa.aggregating", "notice",
    "pairing.changed", "pane.reveal", "pet.changed", "pet.generate.progress",
    "pet.hatch.progress", "platforms.changed", "preview.close", "preview.open", "preview.restart.complete",
    "preview.restart.progress", "projects.changed", "reaction",
    "session.reclaimed", "session.resume_progress", "sessions.changed", "setup.ready",
    "skin.changed", "terminal.close", "tip.show", "tool.output_risk", "voice.interrupted",
    "voice.partial", "voice.status", "voice.transcript", "wake.detected",
})

# `tool.generating` (`contracts/events.py` ToolGeneratingPayload: "The model is emitting a tool call's arguments")
# carries a name and no id, sent as soon as the stream names a call, and two kinds of them name no call that runs
# under that name. A streamed attempt whose arguments Hermes cannot repair is discarded and retried after its
# `tool.generating` (`agent/turn_truncation.py::_retry_truncated_tool_call`), and nothing follows for it. A deferred
# tool is called through the `tool_call` bridge (`tools/tool_search_catalog.py` TOOL_CALL_NAME): the stream names the
# bridge, the executor unwraps it (`agent/tool_executor.py::_unwrap_tool_search_call`), and `tool.start` and
# `tool.complete` name the tool it reached, under the bridge call's own id.
TOOL_CALL_BRIDGE = "tool_call"

# The kinds of output the gateway already writes to this client (`server._emit`), shown as Hermes' Ink TUI shows
# them (`ui-tui/src/app/createGatewayEventHandler.ts`); showing them sends nothing back.
# `review.summary` (`contracts/events.py` ReviewSummaryPayload, `server.py` background_review_callback): `text`, what
# the background review of the last turn saved to memory or skills, already worded by Hermes; a transcript line.
REVIEW_SUMMARY_TEXT = "text"
# `background.complete` / `btw.complete` (SideAgentCompletePayload, `gateway/session_tui_side.py`): the answer of a
# `/bg` or `/btw` side agent, `text` (`error: <reason>` when it failed), its `task_id`, and for /btw the `question`.
SIDE_ANSWER_EVENTS = frozenset({"background.complete", "btw.complete"})
SIDE_ANSWER_TEXT = "text"
SIDE_ANSWER_TASK = "task_id"
SIDE_ANSWER_QUESTION = "question"
# `session.control.update` (SessionControlUpdatePayload, `methods_session_control._publish_session_control_snapshot`):
# `control` holds `goal`, `contracts/config_free_tier_control.py` GoalSnapshot or None. A goal row shows while its
# `status` is one of GOAL_SHOWN_STATUSES (`ui-tui/src/app/goalStatus.ts::goalLine`), from `title`, `turns_used`,
# `max_turns`, `paused_reason` and `wait_barrier` (`type` "until" with `until_at` epoch seconds, or "session" / "pid"
# with `target`; both with `reason`). When a shown goal turns `done`, its `created_at` (set at `/goal`) and
# `updated_at` (Hermes' `last_turn_at`, the end of the judged turn), both epoch seconds, give its whole wall clock.
SESSION_CONTROL = "control"
CONTROL_GOAL = "goal"
GOAL_TITLE = "title"
GOAL_STATUS = "status"
GOAL_TURNS_USED = "turns_used"
GOAL_MAX_TURNS = "max_turns"
GOAL_PAUSED_REASON = "paused_reason"
GOAL_WAIT_BARRIER = "wait_barrier"
GOAL_CREATED_AT = "created_at"
GOAL_UPDATED_AT = "updated_at"
GOAL_ACTIVE = "active"
GOAL_PAUSED = "paused"
GOAL_DONE = "done"
GOAL_SHOWN_STATUSES = frozenset({GOAL_ACTIVE, GOAL_PAUSED})
BARRIER_TYPE = "type"
BARRIER_UNTIL = "until"
BARRIER_UNTIL_AT = "until_at"
BARRIER_TARGET = "target"
BARRIER_REASON = "reason"
# MoA (`tool_progress._progress_moa_*`, `contracts/events.py` Moa*Payload): `moa.reference` carries one reference
# model's `label` and `text` (with `index` and `count` when known), kept in the transcript as a collapsed row;
# `moa.progress` `refs_done` of `refs_total` and `moa.phase` with `phase` MOA_PHASE_AGGREGATOR are the working row's
# words for the turn. `moa.aggregating` only starts the aggregator, whose answer streams as the reply: unread.
MOA_LABEL = "label"
MOA_TEXT = "text"
MOA_INDEX = "index"
MOA_COUNT = "count"
MOA_REFS_DONE = "refs_done"
MOA_REFS_TOTAL = "refs_total"
MOA_PHASE = "phase"
MOA_PHASE_AGGREGATOR = "aggregator"

# `session.info` (and a create or resume answer's `info`), `contracts/common.py` `SessionLiveInfo`:
# `yolo` (bool) is this session's approvals off, `reasoning_effort` (str, "" when unset) its effort.
SESSION_INFO_YOLO = "yolo"
SESSION_INFO_REASONING_EFFORT = "reasoning_effort"
# `config.get {key: "full"}` answers `{"config": _load_cfg()}` (`methods_config.py` `_CONFIG_GETTERS`): the user's
# config.yaml as Hermes reads it. The effort lives at `agent.reasoning_effort` (str, `false`, or an `{enabled,
# effort}` mapping), and `agent.reasoning_overrides` maps model names to their own (`resolve_reasoning_config`).
CONFIG_AGENT = "agent"
CONFIG_REASONING_EFFORT = "reasoning_effort"
CONFIG_REASONING_OVERRIDES = "reasoning_overrides"

# `notification.show` (`contracts/events.py` NotificationShowPayload, built by `agent_callbacks._agent_notice_update`
# and the slow agent-build notice in `server._await_agent_ready`): `text` carries its own glyph, `level` is one of
# NOTIFICATION_LEVELS, `kind` sticky, ttl or agent, `ttl_ms` is honoured for kind ttl, and a later show or a
# `notification.clear` naming the same `key` replaces or withdraws it.
NOTIFICATION_TEXT = "text"
NOTIFICATION_LEVEL = "level"
NOTIFICATION_KIND = "kind"
NOTIFICATION_TTL_MS = "ttl_ms"
NOTIFICATION_KEY = "key"
NOTIFICATION_LEVELS = frozenset({"info", "warn", "error", "success"})
NOTIFICATION_TTL_KIND = "ttl"

# `session.title` (`contracts/events.py` SessionTitlePayload): auto-titling renamed the session; `title` is the new
# name (the payload's `session_id` is the stored key, and the envelope's is the live session, as for every event).
SESSION_TITLE = "title"

# `subagent.tail`'s result (`contracts/profiles_vault_complete_foreign_subagents.py` `SubagentTailResult`):
# `available` is false while the child has no live transcript; `text` is its last 16 KB, `truncated` says
# the tail was cut. `subagent_id` is echoed and not read.
TAIL_AVAILABLE = "available"
TAIL_TEXT = "text"
TAIL_TRUNCATED = "truncated"

# `session.redirect`'s and `session.steer`'s `status` (`contracts/sessions.py` `CorrectionStatus`;
# `tui_gateway/methods_session_interrupt.py`, `agent/interrupt_control.py`). `redirected` is `session.redirect`'s
# only: during a model request Hermes cancelled that request and retries it with the text as a user message, and
# during a tool batch it holds the text for that batch's results, so the turn has it now either way. `queued` from
# `session.steer` means the running turn holds the text until a tool batch ends or the next model call (when the
# model is writing its final answer, until after the turn, as the next prompt); from either, while the turn is
# still being built or Hermes compresses the context, it means Hermes queued the text as its next prompt (a stop
# clears that queue). `rejected` means the session is idle, the model's answer completed first, or the agent
# refused it.
STEER_QUEUED = "queued"
STEER_REDIRECTED = "redirected"
STEER_REJECTED = "rejected"
STEER_STATUSES = frozenset({STEER_QUEUED, STEER_REDIRECTED, STEER_REJECTED})

# Environment the TUI removes before spawning the gateway. The sidecar URL makes
# the gateway tee every event to a socket; the gateway URL is the launcher's
# attach hand-off, which the TUI refuses rather than honours.
STRIPPED_GATEWAY_ENV = ("HERMES_TUI_GATEWAY_URL", "HERMES_TUI_SIDECAR_URL")
ATTACH_ENV = "HERMES_TUI_GATEWAY_URL"


@dataclass(frozen=True)
class ServerRequestTreatment:
    """How the TUI answers one server-to-client request.

    `shown` says whether the TUI opens a slot for it (False: a notice, and the
    decline goes at once). `decline` is the frame it sends when the person
    declines or the TUI does not support the request. An ignored request is
    never an option: over stdio the gateway waits out its full deadline. When
    the gateway gives up first (its own timeout), it withdraws the request with
    `request.cancel` and nothing is sent.
    """

    method: str
    shown: bool
    decline: dict[str, object]
    masked: bool = False


_EMPTY_VALUE: dict[str, object] = {"result": {"value": ""}}
_UNSUPPORTED: dict[str, object] = {"error": {"code": METHOD_NOT_FOUND, "message": "not supported by the OMH TUI"}}

SERVER_REQUESTS: dict[str, ServerRequestTreatment] = {
    treatment.method: treatment
    for treatment in (
        # A result without `answers` is cancel-all.
        ServerRequestTreatment("clarify", shown=True, decline={"result": {}}),
        # `-32601` on an approval WITHDRAWS it instead of denying it; the deny is explicit.
        ServerRequestTreatment("approval", shown=True, decline={"result": {"choice": "deny"}}),
        ServerRequestTreatment("sudo", shown=True, decline=_EMPTY_VALUE, masked=True),
        ServerRequestTreatment("secret", shown=True, decline=_EMPTY_VALUE, masked=True),
        ServerRequestTreatment("vault.code", shown=True, decline=_EMPTY_VALUE),
        ServerRequestTreatment("vault.unlock_prompt", shown=False, decline=_EMPTY_VALUE),
        ServerRequestTreatment("vault.save_login", shown=False, decline=_EMPTY_VALUE),
        ServerRequestTreatment("terminal.read", shown=False, decline=_UNSUPPORTED),
        ServerRequestTreatment("preview.read", shown=False, decline=_UNSUPPORTED),
        ServerRequestTreatment("preview.act", shown=False, decline=_UNSUPPORTED),
        ServerRequestTreatment("window.read", shown=False, decline=_UNSUPPORTED),
        ServerRequestTreatment("tour", shown=False, decline=_UNSUPPORTED),
        ServerRequestTreatment("display.install.sudo", shown=False, decline=_UNSUPPORTED),
    )
}


def server_request_treatment(method: str) -> ServerRequestTreatment:
    """The treatment for `method`; a request the table does not know is unsupported."""
    return SERVER_REQUESTS.get(method, ServerRequestTreatment(method, shown=False, decline=_UNSUPPORTED))


def is_drift_error(error: object) -> bool:
    """Whether a JSON-RPC error means this Hermes no longer speaks the declared contract."""
    return isinstance(error, dict) and error.get("code") in DRIFT_ERROR_CODES


def undeclared_params(method: str, params: dict[str, object]) -> list[str]:
    """Keys in `params` the contract does not declare for `method` (all of them for an unknown method)."""
    allowed = CLIENT_METHODS.get(method, frozenset())
    return sorted(key for key in params if key not in allowed)


def call_problem(method: str, params: dict[str, object]) -> str:
    """Why the TUI must not send this call; "" when it may.

    An undeclared key; a `prompt.submit` that truncates without both an int
    `truncate_before_row_id` and `confirm_truncate: true` (a rewind names the
    row the person picked and says so); a `config.set` that Hermes would apply
    beyond one session (a key or a value outside `CONFIG_SET_VALUES`, a model value
    `model_switch_value` did not make, or no session id);
    or a `subagent.tail`, `subagent.interrupt` or `subagent.steer` that does
    not name both a session and a subagent (a steer, its text too).
    Hermes answers a tail without a subagent id as a rejected parameter
    (4000), which the client reads as drift and ends the session over.
    """
    undeclared = undeclared_params(method, params)
    if undeclared:
        return f"{method} does not declare {', '.join(undeclared)} in the gateway contract"
    if method == "prompt.submit" and ("truncate_before_row_id" in params or "confirm_truncate" in params):
        row_id = params.get("truncate_before_row_id")
        if not isinstance(row_id, int) or isinstance(row_id, bool) or params.get("confirm_truncate") is not True:
            return "prompt.submit truncates only with an int truncate_before_row_id and confirm_truncate true"
        return ""
    if method == "shell.exec":
        command = params.get("command")
        return "" if isinstance(command, str) and command.strip() else "shell.exec needs the command the person typed"
    if method in ("subagent.tail", "subagent.interrupt", "subagent.steer"):
        needed = ("session_id", "subagent_id", "text") if method == "subagent.steer" else ("session_id", "subagent_id")
        missing = [key for key in needed if not (isinstance(params.get(key), str) and params[key].strip())]
        return f"{method} needs {' and '.join(missing)}: Hermes rejects the call without" if missing else ""
    if method != "config.set":
        return ""
    key, value, session_id = params.get("key"), params.get("value"), params.get("session_id")
    allowed = CONFIG_SET_VALUES.get(key) if isinstance(key, str) else None
    if "confirm_expensive_model" in params and (key != CONFIG_SET_MODEL or params["confirm_expensive_model"] is not True):
        return "config.set sends confirm_expensive_model only as true, and only with a model"
    if key == CONFIG_SET_MODEL:
        if model_switch_parts(value) is None:
            return f"config.set model takes only a model_switch_value, not {value!r}"
    elif allowed is None:
        return f"config.set does not declare the key {key!r} in the gateway contract"
    elif not isinstance(value, str) or value not in allowed:
        return f"config.set does not declare the value {value!r} for {key} in the gateway contract"
    if not isinstance(session_id, str) or not session_id:
        return f"config.set {key} needs a session id: without one Hermes writes beyond the session"
    return ""
