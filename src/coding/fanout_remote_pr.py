"""The opt-in remote PR lane, refused: a decision surface and its URL grammar.

A cloud harness returns a pull request instead of a local commit, so design
`ext-harness-specs/design.md` §6 describes a lane that launches a cloud argv,
observes a session URL and a PR URL on stdout, waits for the PR under a
deadline and imports `refs/pull/<n>/head` into the unit branch. That import
needs a dispatcher `git fetch`. INVARIANT 3 forbids the dispatcher opening a
network git command, and the scoped exception the design asks for has not been
approved, so **the lane is not implemented here** and this module exists only to
refuse it honestly:

* `decide_lane_kind` is the closed decision over the two opt-ins (the owner
  entry's `remote_pr` and the invocation's `--allow-remote-pr`). Exactly one
  combination -- both false -- is the local lane. Every combination that would
  pick the remote lane returns `remote_pr_not_available` with a claim boundary
  saying the lane is not implemented pending a policy decision; there is no
  fallback to local, because a unit that asked for a PR was not asked for a
  local edit.
* `plan_remote_pr_dispatch` applies that decision to a batch of selected units
  so the dispatcher can refuse before any probe, worktree or child.

Nothing here spawns a process, runs git, or opens a socket, and nothing here
launches a cloud argv: this module imports no `subprocess`, `socket`, or
network client, and must keep that property (`NETWORK_CLIENT_BRIDGE_IMPORTERS`
and the subprocess allowlist in `tests/test_handoff_safety_contract_enforcement.py`).

The two URL readers are deliberately here rather than absent: they are
policy-neutral, they are the exact grammar §6 step 4 specifies, and the PR that
builds the lane will need them. They are pure: a token in, a bounded canonical
string out (or `None`). They accept only the documented shape -- an absolute
`https` URL, the exact host, a matching `owner/repo`, a positive decimal PR
number, no userinfo, port, query, fragment, escape, trailing path or control
character -- so a cloud CLI's prose can never become a stored URL, and a URL
from output is never used to choose a fetch target: the target is constructed
from the operator's own repository identity.

What this module does NOT prove, and does not claim: a session was created, a
PR exists, a commit was imported, a lane ran, or a policy decision was made.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import re
from typing import Final

# Lane kinds. `remote_pr` is named here so a reader can see the lane this
# release refuses; no decision ever returns it.
LANE_LOCAL: Final = "local"
LANE_REMOTE_PR: Final = "remote_pr"
LANE_REFUSED: Final = "refused"

# The one closed reason every remote-lane combination answers with. The CLI
# already refuses `--allow-remote-pr` without naming a lane; the dispatcher
# names this code so a wrapper reads a reason, not prose.
REFUSAL_REMOTE_PR_NOT_AVAILABLE: Final = "remote_pr_not_available"

REMOTE_PR_CLAIM_BOUNDARY: Final = (
    "the opt-in remote PR lane is not implemented pending a policy decision: no "
    "cloud executor was launched, no session or pull request was observed, no "
    "remote ref was fetched, and no commit was imported; OMH opened no socket "
    "and ran no network git command"
)

# §6 step 4: absolute URL tokens of at most 512 bytes. The PR number grammar
# below also carries the "at most ten digits" bound.
MAX_URL_BYTES: Final = 512

# Exact shapes. `fullmatch` is the whole defence: it is what makes a port
# (`github.com:443`), userinfo (`user@github.com`), query (`?x=1`), fragment
# (`#y`), escape (`%2f`), trailing path (`/pull/1/files`) or an alternate host
# fail instead of being trimmed into something plausible.
_SESSION_URL = re.compile(
    r"https://app\.devin\.ai/sessions/(?:[0-9a-f]{32}|devin-[0-9a-f]{32})",
    re.ASCII,
)
_OWNER = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", re.ASCII)
_REPOSITORY = re.compile(r"[A-Za-z0-9_.-]{1,100}", re.ASCII)
_PR_URL = re.compile(
    r"https://github\.com/([A-Za-z0-9][A-Za-z0-9-]{0,38})"
    r"/([A-Za-z0-9_.-]{1,100})/pull/([1-9][0-9]{0,9})",
    re.ASCII,
)


@dataclass(frozen=True)
class LaneDecision:
    """One unit's lane answer, with the two inputs that produced it.

    `lane` is `local` or `refused`; `reason` is a closed code (`""` for local).
    `would_use_remote_pr` records what the *request* asked for -- both opt-ins
    present -- which is why a refusal can still say the remote lane was
    selected and is unavailable, rather than that nothing was asked.
    """

    lane: str
    reason: str
    claim_boundary: str
    entry_remote_pr: bool
    allow_remote_pr: bool

    @property
    def refused(self) -> bool:
        return self.lane == LANE_REFUSED

    @property
    def would_use_remote_pr(self) -> bool:
        return self.entry_remote_pr and self.allow_remote_pr


@dataclass(frozen=True)
class RemotePrRefusal:
    """A dispatch-level refusal: which selected units asked for the lane.

    `refused_unit_ids` can be empty when the invocation set the flag but no
    selected unit declares `remote_pr`; that is still an error (§6 step 1: a
    flag with zero eligible lanes is not a no-op), so the refusal does not
    depend on the list being non-empty.
    """

    reason: str
    claim_boundary: str
    refused_unit_ids: tuple[str, ...]
    remote_pr_declared_unit_ids: tuple[str, ...]
    allow_remote_pr: bool


def rendered_cloud_argv(argv: list[str]) -> bool:
    """A rendered fragment or substituted option cannot opt a local lane into cloud."""
    return "--cloud" in argv[1:] or argv[1:2] == ["cloud"]


def decide_lane_kind(*, entry_remote_pr: object, allow_remote_pr: object) -> LaneDecision:
    """The closed decision over the two opt-ins, for one unit.

    Not a boolean and not a preference: three of the four combinations are a
    refusal with the same reason, because until the lane exists none of them
    can be served, and picking the local lane instead would silently change
    what the operator asked for. Non-boolean inputs are read as the flag being
    unset rather than truthy, so a hand-edited contract cannot opt itself in.
    """
    declared = entry_remote_pr is True
    authorized = allow_remote_pr is True
    if not declared and not authorized:
        return LaneDecision(
            lane=LANE_LOCAL,
            reason="",
            claim_boundary="",
            entry_remote_pr=False,
            allow_remote_pr=False,
        )
    return LaneDecision(
        lane=LANE_REFUSED,
        reason=REFUSAL_REMOTE_PR_NOT_AVAILABLE,
        claim_boundary=REMOTE_PR_CLAIM_BOUNDARY,
        entry_remote_pr=declared,
        allow_remote_pr=authorized,
    )


def plan_remote_pr_dispatch(
    *,
    entry_remote_pr_by_unit: Mapping[str, bool],
    allow_remote_pr: object,
) -> RemotePrRefusal | None:
    """Decide a whole selected batch; `None` means every unit runs locally.

    Refuses the batch when any selected unit's entry declares `remote_pr` or
    when the invocation passed the flag -- including the flag with no declared
    entry at all, which is a caller error rather than a no-op. One refusal
    covers the batch because a partially-run batch whose remote units are
    missing would read as a completed fanout.
    """
    declared_units = tuple(
        str(unit_id)
        for unit_id, declared in entry_remote_pr_by_unit.items()
        if declared is True
    )
    authorized = allow_remote_pr is True
    if not declared_units and not authorized:
        return None
    return RemotePrRefusal(
        reason=REFUSAL_REMOTE_PR_NOT_AVAILABLE,
        claim_boundary=REMOTE_PR_CLAIM_BOUNDARY,
        refused_unit_ids=tuple(
            str(unit_id) for unit_id in entry_remote_pr_by_unit
        ),
        remote_pr_declared_unit_ids=declared_units,
        allow_remote_pr=authorized,
    )


def parse_session_url(token: object) -> str | None:
    """The canonical Devin session URL a token names, or `None`.

    Returns the URL rebuilt from the matched session id, never the input
    object, so a caller stores a bounded canonical string or nothing.
    """
    if not isinstance(token, str):
        return None
    if len(token.encode("utf-8", errors="replace")) > MAX_URL_BYTES:
        return None
    if _SESSION_URL.fullmatch(token) is None:
        return None
    return f"https://app.devin.ai/sessions/{token.rsplit('/', 1)[-1]}"


def parse_pull_request_url(
    token: object, *, owner: object, repository: object
) -> tuple[int, str] | None:
    """`(number, canonical URL)` for a PR in the trusted repository, or `None`.

    The operator's own `owner`/`repository` identity is the authority: a token
    that names a different repository is refused, and the URL returned is built
    from the trusted identity, not from the token. Owner and repository compare
    case-insensitively because GitHub's namespace does, and the canonical URL
    keeps the operator's spelling.
    """
    if not isinstance(token, str) or not isinstance(owner, str) or not isinstance(repository, str):
        return None
    if not owner or not repository:
        return None
    if _OWNER.fullmatch(owner) is None or _REPOSITORY.fullmatch(repository) is None:
        return None
    if len(token.encode("utf-8", errors="replace")) > MAX_URL_BYTES:
        return None
    match = _PR_URL.fullmatch(token)
    if match is None:
        return None
    seen_owner, seen_repository, number = match.groups()
    if seen_owner.lower() != owner.lower() or seen_repository.lower() != repository.lower():
        return None
    return int(number), f"https://github.com/{owner}/{repository}/pull/{int(number)}"
