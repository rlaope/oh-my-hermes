# Routing quality gate

The meta-router has a deterministic golden evaluation in
`tests/test_routing_quality.py`. It is intentionally separate from individual
skill tests so catalog or scoring changes are reviewed against user-shaped
routing outcomes.

The gate currently measures:

- known-lane dispatch accuracy across representative research, planning,
  coding, memory, paper, visual, and feedback requests;
- ambiguity guardrail behavior, including bounded candidates and a high
  confidence threshold; and
- unknown-input fallback behavior, including explicit fallback metadata.

The current baseline is 100% (7/7) on the known-lane golden set. This is a
regression baseline, not a claim about production traffic. The next telemetry
step should measure the same dimensions from privacy-safe route metadata:
dispatch accuracy from operator corrections, clarification rate, fallback
rate, and confidence-margin distributions.
