"""The `pre_gateway_dispatch` hook: the messenger chat gate (`messenger_gate`)."""

from __future__ import annotations

import logging

from .. import runtime_paths
from ..messenger_gate import gate_event

_LOG = logging.getLogger(__name__)


async def pre_gateway_dispatch(event=None, gateway=None, session_store=None, **_kwargs):
    """Skip a Slack or Discord group message that is not for the bot, or arrives in a muted thread.

    Fails open: any error lets Hermes dispatch the message as it would without OMH.
    """
    try:
        result, ack = gate_event(
            event, gateway,
            hermes_home=runtime_paths.default_hermes_home(),
            omh_home=runtime_paths.default_omh_home(),
        )
    except Exception as exc:  # health: allow BLE001 -- the gate must never stop dispatch; fail open and log
        _LOG.warning("omh messenger gate failed open: %s", type(exc).__name__)
        return None
    if ack is not None:
        await _acknowledge(ack)
    return result


async def _acknowledge(ack) -> None:
    """Await the 🫡 reaction; a failure loses only the reaction, never the skip."""
    try:
        await ack
    except Exception as exc:  # health: allow BLE001 -- a lost reaction must not undo a skip that already stood
        _LOG.info("omh messenger gate reaction failed: %s", type(exc).__name__)
