"""Which account one coding owner's CLI is logged in as, as a redacted tag.

A limit-shaped failure is an account fact. Without knowing WHICH account hit
the limit, the only recovery omh can offer is "wait", and the operator who has
already switched accounts is told to wait for a window that no longer applies
to them. The 2026-09-11 incident ended on `session limit · resets 6:10pm` with
nothing recorded about whose session it was.

What is read, and only this:

- `claude-code`: `~/.claude.json` -> `oauthAccount.emailAddress`, falling back
  to `oauthAccount.accountUuid`, falling back to the presence of the single
  `claudeAiOauth` slot in `~/.claude/.credentials.json`. That file holds one
  OAuth slot and nothing else, so its presence says an account is logged in
  without saying which.
- `codex`: `~/.codex/auth.json` -> `tokens.account_id`, falling back to whether
  an `OPENAI_API_KEY` is configured there.

What is never read: any token, key, or secret value. `accessToken`,
`refreshToken`, `id_token`, and the API key's own value are never opened, never
hashed, and never persisted. The only inputs to a tag are an email address, an
account uuid, and an account id — identifiers, not credentials.

Redaction. An email becomes the first two characters of its local part, an
ellipsis, and its domain (`de...@example.org`): stable across runs, enough for an
operator to recognise their own account, and not the address itself. Every
other identifier becomes the first 8 hex characters of its SHA-256, which is
one-way and stable. The tag is prefixed with the owner's family (`claude:` /
`codex:`) so two owners' tags can never compare equal by accident.

Two tags being EQUAL is the claim this module is for: it is what says a limit
was hit under the account that is still configured. Two tags being equal is
never a claim that the accounts are the same person, and an empty tag is never
a claim that nobody is logged in -- it says only that nothing readable named an
account. `cause_recovery` treats an empty tag as "cannot be shown to have
changed", which is the conservative direction.

Reads only. Nothing here writes to the operator's home directory, and no
failure propagates: an unreadable, absent, or unparseable file is an empty tag.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Final

ACCOUNT_TAG_CLAIM_BOUNDARY: Final[str] = (
    "An account tag is a redacted, one-way label for the account a local agent CLI is configured "
    "with, read from that CLI's own config file. It is not login truth, not entitlement, not "
    "identity, and no token, key, or secret value is read to produce it. An empty tag means "
    "nothing readable named an account, never that no account exists."
)

# Same relative paths `executor_auth_signals` probes for presence markers,
# restated here rather than imported: that module owns "is a marker present",
# this one owns "which account", and one of them narrowing its probe must not
# silently narrow the other.
_CLAUDE_CONFIG_RELATIVE: Final[str] = ".claude.json"
_CLAUDE_CREDENTIALS_RELATIVE: Final[str] = ".claude/.credentials.json"
_CLAUDE_OAUTH_SLOT_KEY: Final[str] = "claudeAiOauth"
_CODEX_AUTH_RELATIVE: Final[str] = ".codex/auth.json"

# Owners whose account a local config file can name. Everything else -- the
# runtime profiles, hermes, generic -- has no local credential store to read,
# and gets an empty tag rather than a guess.
ACCOUNT_TAG_OWNERS: Final[tuple[str, ...]] = ("claude-code", "codex")

_OWNER_PREFIXES: Final[dict[str, str]] = {"claude-code": "claude", "codex": "codex"}

# Enough of the local part to recognise an account, not enough to be the
# address. Two characters is the same amount `de...@example.org` shows.
_EMAIL_VISIBLE_CHARS: Final[int] = 2
_DIGEST_CHARS: Final[int] = 8
_MAX_TAG_CHARS: Final[int] = 96


def observed_account_tag(owner: str, *, home: Path | None = None) -> str:
    """The redacted account tag for one owner's CLI, or an empty string.

    Never raises. `home` is resolved at call time rather than defaulted to
    `Path.home()` in the signature, matching `executor_auth_signals`: a default
    evaluated at import time would freeze the home directory a test overrides.
    """
    normalized = str(owner or "").strip().casefold()
    if normalized not in ACCOUNT_TAG_OWNERS:
        return ""
    base = home if home is not None else Path.home()
    identifier = (
        _claude_identifier(base) if normalized == "claude-code" else _codex_identifier(base)
    )
    if not identifier:
        return ""
    return f"{_OWNER_PREFIXES[normalized]}:{identifier}"[:_MAX_TAG_CHARS]


def _claude_identifier(home: Path) -> str:
    account = _read_json_object(home / _CLAUDE_CONFIG_RELATIVE).get("oauthAccount")
    if isinstance(account, dict):
        email = str(account.get("emailAddress", "") or "").strip()
        if email:
            return redacted_email(email)
        uuid = str(account.get("accountUuid", "") or "").strip()
        if uuid:
            return short_digest(uuid)
    # No profile to name the account, but the single OAuth slot either holds a
    # login or it does not. Recording that much lets a later tag comparison say
    # "the slot was empty then and is filled now" instead of saying nothing.
    slot = _read_json_object(home / _CLAUDE_CREDENTIALS_RELATIVE).get(_CLAUDE_OAUTH_SLOT_KEY)
    return "oauth-slot" if isinstance(slot, dict) and slot else ""


def _codex_identifier(home: Path) -> str:
    payload = _read_json_object(home / _CODEX_AUTH_RELATIVE)
    tokens = payload.get("tokens")
    if isinstance(tokens, dict):
        account_id = str(tokens.get("account_id", "") or "").strip()
        if account_id:
            return short_digest(account_id)
    # An API-key install names no account anywhere in the file. `api-key` is
    # deliberately NOT derived from the key's value: two different keys tag the
    # same, which makes "the account changed" unprovable for them, and the
    # conservative answer -- wait for the reset -- is the one that follows.
    key = payload.get("OPENAI_API_KEY")
    return "api-key" if isinstance(key, str) and key.strip() else ""


def redacted_email(email: str) -> str:
    """`demo@example.org` -> `de...@example.org`; a value with no `@` is digested."""
    local, separator, domain = str(email).partition("@")
    if not separator or not domain:
        return short_digest(email)
    visible = local[:_EMAIL_VISIBLE_CHARS]
    if len(local) <= _EMAIL_VISIBLE_CHARS:
        return f"{visible}@{domain}"
    return f"{visible}...@{domain}"


def short_digest(value: str) -> str:
    """The first 8 hex characters of SHA-256: stable, one-way, not the input."""
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:_DIGEST_CHARS]


def _read_json_object(path: Path) -> dict[str, Any]:
    """One JSON object from the operator's home, or an empty dict. Never raises."""
    try:
        if not path.is_file():
            return {}
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        # `json.JSONDecodeError` is a `ValueError`. A config file omh cannot
        # read is an unknown account, never a dispatch failure: this is read on
        # the spawn path, where raising would abort the work the tag describes.
        return {}
    return parsed if isinstance(parsed, dict) else {}
