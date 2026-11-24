"""Whether a person could answer a prompt raised in this session.

One question, asked by one caller: the repeat guard's stage two escalates
a looping tool call to the host's human-approval gate, and that gate is
worth reaching only where somebody is there to answer it. Everywhere
else stage one's ``block`` is the whole of what OMH can usefully do.

The cost of getting it wrong is not symmetric, and the asymmetry is
measured rather than assumed. `tools/approval.py` `_run_approval_gate`
resolves an unattended context instantly -- "never a pending approval
nobody can answer" -- in one of two ways:

* `approvals.unattended_mode` at its `deny` default returns the HOST's
  block text. The call is stopped, so nothing runs, but OMH's advice
  about what to do instead is gone and the message closes by telling the
  reader to set `unattended_mode: approve` in config.yaml -- advice that
  is right for a flagged action and wrong for a loop.
* `approvals.unattended_mode: approve` returns `_approved()`. The
  escalation RUNS the call stage one was refusing. This is the binding
  reason: stage two would be the first rung of the ladder that makes a
  loop worse instead of better.

**Which host set this mirrors, and what question that set answers.** The
approval layer's own, in `tools/approval_context.py`, because that is
the code deciding whether a card reaches a person:
`_is_unattended_platform_approval_context` ("no human can answer a
prompt"), `_is_cron_approval_context`, and
`_is_single_query_approval_context`.

An earlier version of this file copied `agent/tool_guardrails.py`'s
`_ATTENDED_PLATFORMS` instead. That set answers a DIFFERENT question --
whether tool-loop hard stops default on -- and the two disagree on eleven
platforms. The one that mattered was inverted: `api_server` is attended
to the guardrail and unattended to the approval layer, so OMH escalated
on exactly the surface where the escalation resolves through
`approvals.unattended_mode` and, at `approve`, runs the looping call --
the failure this module calls its binding reason, reached on the one
platform the wrong set got backwards. The other ten were the chat
gateways, withheld from an escalation `_await_gateway_decision` would
have put in front of a real person.

So the shape here is a DENYLIST, matching the host: a platform Hermes
adds after this was written reads as attended, because
`_is_gateway_approval_context` returns True for any bound platform that
is neither cron nor one of the three programmatic ones. An allowlist
would silently withhold the escalation on every surface added later.

**What a plugin can see, and what it cannot.** The platform arrives as a
kwarg on `pre_llm_call`, the one hook OMH registers that the host passes
one; `pre_tool_call` is passed the five identity ids and nothing else
(`hermes_cli/plugins.py`, `_get_pre_tool_call_directive_details`). Cron
and single-query are not platforms at all -- cron binds a platform for
delivery routing, and `hermes chat -q` runs as `platform == "cli"` -- so
no platform-based predicate can see either.

Single-query IS visible, because the host puts that marker in the
process environment on both of its entry paths (`cli.py`,
`hermes_cli/oneshot.py` both assign `HERMES_SINGLE_QUERY_SESSION`), and
a `-q` run is a process dedicated to one turn.

**Cron is not visible from the process environment, and this predicate
does not read it.** `HERMES_CRON_SESSION` is a ContextVar name, never a
process variable: the in-process ticker binds it through
`gateway.session_context` (`cron/scheduler.py`), the detached worker's
environment is built without it, and the host's own regression test
asserts `os.environ.get("HERMES_CRON_SESSION") is None` after a job has
run. `tools/approval_context._session_env` reads the ContextVar first
and falls back to the process environment only for standalone
entrypoints, and a plugin cannot read a host ContextVar. An earlier
version of this module read the variable anyway and claimed the
dedicated-process case worked; it was a gate frozen on a state the host
never produces, so it is gone rather than kept as a line that cannot
fire.

So **every cron turn reads as attended here and stage two escalates**.
What that costs is bounded and worth stating: at the `approvals.cron_mode`
default of `deny` the host resolves the escalation as a block, so the
loop still stops, with the host's wording instead of OMH's advice; at
`cron_mode: approve` it auto-approves the looping call, which is the
failure this module calls its binding reason. It is not a regression --
before this module existed every lane escalated -- and closing it needs
a signal the host does not give a plugin.

Correction: cron IS visible through the platform. Hermes builds every cron
agent with `platform="cron"` (`cron/scheduler.py`, `_construct_cron_agent`)
and `pre_llm_call` passes it, so `session_platform` answers `cron` there; a
delegated child's agent likewise carries `platform="subagent"`
(`tools/delegate_tool.py`). This predicate still answers True for both: its
question is whether to escalate, and changing that answer belongs with the
ask rules. The PR delivery gate (`pr_delivery_gate.nobody_can_answer`) reads
both and holds them as unattended.

**Delegation.** A delegated child runs under its own session id
(`subagent_start`'s `child_session_id`, recorded by `nudge_budget`).
Stage two is refused there too, and this half is conservative by choice
rather than by measurement: the child inherits the parent's presence
environment, so its gate may well reach the person who started the
parent, but the card it raises names a session id that person did not
start and a repeat count they cannot attribute to anything they are
watching. Being wrong costs the loop nothing -- it keeps getting blocked
-- so the cheap failure is the one taken.

Process-global, bounded, and cleared through `reset_session_attendance`,
for the reasons `nudge_budget` states at length for the maps beside it:
the host hands a plugin hook no object to hang per-session state on, a
host outlives every session it runs, and a test that reaches into the
module attribute instead of the seam is a test the next one cannot find.
"""

from __future__ import annotations

from collections import OrderedDict
import os

from .nudge_budget import MAX_TRACKED_SESSIONS, session_is_delegated

# A copy of the host's `_UNATTENDED_APPROVAL_PLATFORMS`
# (`tools/approval_context.py`): programmatic surfaces whose adapters have
# no `send_exec_approval` and no way to receive an `/approve` reply, so a
# card raised there is answered by config and never by a person. Copied
# rather than imported, because OMH never imports Hermes and the
# interpreter that loads this bundle has no `omh` package either.
UNATTENDED_APPROVAL_PLATFORMS = frozenset({"webhook", "msgraph_webhook", "api_server"})
# The one session marker the host actually exports, for the lane no
# platform string can express (`_is_single_query_approval_context`).
# Its cron sibling is deliberately absent: see the module docstring.
SINGLE_QUERY_SESSION_ENV = "HERMES_SINGLE_QUERY_SESSION"
_TRUTHY = frozenset({"1", "true", "yes", "on"})

_SESSION_PLATFORMS: "OrderedDict[str, str]" = OrderedDict()


def _session_key(session_id: object) -> str:
    return str(session_id or "").strip()


def _env_marker_set(name: str) -> bool:
    return str(os.environ.get(name, "") or "").strip().lower() in _TRUTHY


def note_session_platform(session_id: object, platform: object) -> None:
    """Remember the surface the host said this session runs on.

    An empty platform is not recorded. The host passes `""` for a session
    whose platform it does not know, and writing that would turn "never
    told" into "told nothing" -- two states the predicate answers the
    same way today, but only the first of which a later turn can fill in.
    """
    key = _session_key(session_id)
    value = str(platform or "").strip().lower()
    if not key or not value:
        return
    _ = _SESSION_PLATFORMS.pop(key, None)
    _SESSION_PLATFORMS[key] = value
    while len(_SESSION_PLATFORMS) > MAX_TRACKED_SESSIONS:
        # Oldest first, and eviction fails toward escalating: a session
        # whose platform was forgotten reads as attended again. That is
        # the pre-#1719 behaviour, not a new risk.
        _ = _SESSION_PLATFORMS.popitem(last=False)


def session_platform(session_id: object) -> str:
    """The recorded platform for this session, or "" when none was seen."""
    key = _session_key(session_id)
    return _SESSION_PLATFORMS.get(key, "") if key else ""


def escalation_can_reach_a_person(session_id: object) -> bool:
    """Whether a human-approval prompt raised here has somebody to answer it.

    False for a delegated child, for the three programmatic platforms the
    host's approval layer names, and inside a single-query process. True
    otherwise -- including for an unknown platform and for every chat
    gateway, which is the host's own answer to both, and including for
    cron, which a plugin cannot detect (see the module docstring).
    """
    if session_is_delegated(session_id):
        return False
    if _env_marker_set(SINGLE_QUERY_SESSION_ENV):
        return False
    return session_platform(session_id) not in UNATTENDED_APPROVAL_PLATFORMS


def reset_session_attendance() -> None:
    """Forget every recorded platform. A test seam.

    Paired with `reset_nudge_budget`, which owns the delegated-session
    half of the predicate above; a test that exercises both halves clears
    both, and grepping for either name finds the other through this line.
    """
    _SESSION_PLATFORMS.clear()
