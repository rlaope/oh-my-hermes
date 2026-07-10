from __future__ import annotations

from hashlib import sha256


def goal_payload(normalized_goal: str) -> dict[str, object]:
    digest = sha256(normalized_goal.encode("utf-8")).hexdigest()
    return {
        "summary": f"Dynamic coding workflow request ({len(normalized_goal)} chars, sha256:{digest[:12]})",
        "summary_kind": "digest_reference",
        "input_chars": len(normalized_goal),
        "sha256": digest,
        "raw_prompt_stored": False,
        "content_preview_stored": False,
    }
