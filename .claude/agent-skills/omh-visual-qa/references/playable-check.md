# Playable Check

A game or interactive scene can have a clean layout, a fine still frame, and
still not be playable: it boots to a blank canvas, ignores the key it
advertises, or freezes after the first frame. A screenshot of one frame
cannot tell these apart, so a game gets a probe of four captures.

## The four checks

1. **Boots.** The first frame, captured exactly as booted, is not blank and
   not a single flat colour.
2. **Answers input.** Capture a frame before and a frame after the declared
   input (a key, click, or touch). The two differ in the region the input
   should move; a difference elsewhere (a clock, a particle layer) does not
   count.
3. **Keeps running.** When the game has a loop, frames taken a few seconds
   apart while idle differ. Background-only animation (drifting clouds, a
   pulsing title) does not count; the thing that should move, moves.
4. **Clean console.** The console shows zero errors across boot and the
   input. A warning is listed; an error fails the check.

## Verdicts

- All four checks backed by a capture: PASS for this lane.
- A check whose capture is missing is BLOCK, not PASS. Reading the code, or
  a description of what the code should do, never passes a check.
- A check whose captures show the failure is REVISE with the smallest fix.
- A run with no WebGL context (a headless browser without GPU support) is
  recorded as `environment: no_webgl`. It is not judged as a blank frame;
  the probe is re-run where a context exists, and until then the checks it
  blocks stay unobserved.

## Record the probe

| check | capture path | verdict |
| --- | --- | --- |
| boots | `captures/boot.png` | PASS / REVISE / BLOCK |
| answers input | `captures/before-input.png`, `captures/after-input.png` | PASS / REVISE / BLOCK |
| keeps running | `captures/idle-0s.png`, `captures/idle-5s.png` | PASS / REVISE / BLOCK |
| clean console | `captures/console.txt` | PASS / REVISE / BLOCK |

## Boundary

A probe plan is not a probe. The table is observed evidence only for rows
whose capture paths exist from the target revision; the rest stay
`prepared_not_observed`.
