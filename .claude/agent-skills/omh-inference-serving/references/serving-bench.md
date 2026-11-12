# Serving Benchmark Protocol

The measurement contract for a serving endpoint. A number without its load
shape, dataset, and metadata is an anecdote, not a benchmark.

## Metric vocabulary

- **TTFT** - time to first token; the interactivity metric.
- **TPOT** - time per output token after the first; the streaming-rate metric.
- **ITL** - inter-token latency distribution; jitter the user feels.
- **E2EL** - end-to-end request latency.
- Report each as mean, median, and P99 - a mean alone hides the tail.
- **Goodput** - the fraction of requests meeting an explicit SLO, stated like
  `ttft:500 tpot:50` (milliseconds). Throughput without an SLO rewards
  batching that ruins latency.

## Load shapes

Choose the shape before running anything, and name it in the results: infinite
burst (capacity ceiling), Poisson arrival at a target rate (steady state),
burstiness below 1 (spiky traffic), linear ramp between two rates (finding the
knee), and a concurrency cap (client-side backpressure). One shape per run;
mixed shapes measure nothing.

## Prefix-cache protocol

Three acceptable designs: (A) offline A/B - the same fixed-prompt workload
with prefix caching on, then off, with the repeat count controlling expected
hit rate; (B) a real shared-prefix corpus; (C) online with a synthetic
prefix-repetition dataset, whose four knobs (prefix length, suffix length,
number of prefixes, output length) are all recorded. A cache result without
its hit-rate assumption is not comparable to anything.

## Hygiene

- Save results as files with metadata (`version`, `tp`, model, quantization,
  load shape) so two runs can be compared without archaeology.
- The chat-completions backend pairs with the chat endpoint; mixing the
  completions endpoint into a chat benchmark invalidates TTFT.
- If the benchmark started the server, the benchmark stops the server.
- Verify targets before tuning: TTFT under ~500ms on short prompts and GPU
  utilization above ~80% are the usual first bars; a run that misses them
  goes to the symptom->flag table before any deeper tuning.

## Boundary

A benchmark plan is prepared_not_observed; only saved result files from
observed runs are measurement evidence, and one run is a sample, never a
capacity guarantee, review, CI, or merge evidence.
