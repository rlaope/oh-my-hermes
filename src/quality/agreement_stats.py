"""Agreement between two screening reviewers, as `agreement_stats/v1`.

Pure arithmetic over records both reviewers decided include/exclude. It
measures how often two reviewers agree, not whether either is right: there is
no gold set here. An empty table reports null statistics, never 0.
"""

from __future__ import annotations

from collections.abc import Iterable

from .reported_rate import reported_rate

AGREEMENT_STATS_SCHEMA_VERSION = "agreement_stats/v1"
KAPPA_PABAK_DIVERGENCE = 0.2
CLAIM_BOUNDARY = (
    "agreement between two reviewers, not correctness against a human gold set"
)


def agreement_stats(pairs: Iterable[tuple[bool, bool]]) -> dict[str, object]:
    """Summarize reviewer agreement over (a_include, b_include) pairs."""
    both_include = both_exclude = a_only_include = b_only_include = 0
    for a_include, b_include in pairs:
        if a_include and b_include:
            both_include += 1
        elif a_include:
            a_only_include += 1
        elif b_include:
            b_only_include += 1
        else:
            both_exclude += 1
    n = both_include + both_exclude + a_only_include + b_only_include

    observed = reported_rate(
        numerator=both_include + both_exclude,
        denominator=n,
        numerator_of=["both_include", "both_exclude"],
        denominator_of="records both reviewers decided",
    )

    cohen_kappa: float | None = None
    pabak: float | None = None
    kappa_undefined_reason = ""
    if n == 0:
        kappa_undefined_reason = "no_observations"
    else:
        po = (both_include + both_exclude) / n
        pabak = round(2 * po - 1, 3)
        a_rate = (both_include + a_only_include) / n
        b_rate = (both_include + b_only_include) / n
        expected = a_rate * b_rate + (1 - a_rate) * (1 - b_rate)
        if expected == 1:
            kappa_undefined_reason = "expected_agreement_is_one"
        else:
            cohen_kappa = round((po - expected) / (1 - expected), 3)

    prevalence_note = ""
    if (
        cohen_kappa is not None
        and pabak is not None
        and abs(cohen_kappa - pabak) >= KAPPA_PABAK_DIVERGENCE
    ):
        prevalence_note = "kappa_and_pabak_diverge"

    return {
        "schema_version": AGREEMENT_STATS_SCHEMA_VERSION,
        "table": {
            "both_include": both_include,
            "both_exclude": both_exclude,
            "a_only_include": a_only_include,
            "b_only_include": b_only_include,
            "n": n,
        },
        "observed_agreement": observed.to_payload(),
        "cohen_kappa": cohen_kappa,
        "kappa_undefined_reason": kappa_undefined_reason,
        "pabak": pabak,
        "prevalence_note": prevalence_note,
        "claim_boundary": CLAIM_BOUNDARY,
    }


__all__ = ["AGREEMENT_STATS_SCHEMA_VERSION", "CLAIM_BOUNDARY", "agreement_stats"]
