# Motion Continuity

For animated or simulated output, a single settled frame can look correct
while the motion itself is wrong. Load this reference when the surface in
scope involves animation, simulation, or replayed sequences, and judge the
continuity of the motion itself as observed evidence, not the stillness.

## Checks

- **Entry and spawn position** — the position at which an object or character
  enters the frame matches the declared origin. An entry from a location other
  than the declared origin is a continuity defect even if the motion after it
  looks smooth.
- **No teleport** — per-frame displacement stays within the cap derived from
  the declared speed. If the declared speed implies at most N pixels (or
  units) per frame, any observed jump larger than that is a teleport: an
  object skipping intermediate positions between consecutive frames.
- **Force direction equals motion direction** — when a force is applied
  (knockback, push, impulse), the direction of the observed displacement
  equals the sign and direction of the applied force. Motion in the opposite
  direction of the declared force, or motion with no declared force, is a
  defect.
- **Monotonic resource bars** — HP and resource bars fall (or rise) only as
  declared effects allow. An unexplained jump upward or downward between
  frames — a bar that drops in one frame by more than any declared effect
  explains, or recovers without a declared cause — is a continuity defect.
- **Flow replay, not inference** — re-run the full flow (deploy, travel,
  engage) in an independent simulation or replay, and sample frames within
  each phase. Inferring that the flow ran correctly from summary numbers such
  as cost, clear time, or final score is not observation: intermediate phases
  can fail while the summary looks fine.
- **A technical pass is not visual approval** — a passing build, passing
  tests, or healthy metrics are technical results. They never substitute for
  the visual verdict on the motion itself.
- **Record evidence** — for every finding, record the frame indices or
  timestamps at which the defect is observed. A continuity claim that cannot
  be located in time cannot be re-checked.

## Boundary

OMH prepares this reference; the captures, replays, and reruns happen in
whichever executor or wrapper lane the user selected. Findings without frame
indices or timestamps are prepared claims, not observed evidence.

## Attribution

The idea of pairing a design-system contract file with taste-direction
material and an evidence-bound critique lane adapts concepts from the
`frontend` skill of `code-yeongyu/oh-my-openagent@9c62b62` (Sustainable Use
License 1.0) and its permissively licensed design upstreams:
`Leonxlnx/taste-skill` (MIT), `nextlevelbuilder/ui-ux-pro-max-skill` (MIT),
`Owl-Listener/designpowers` (MIT), and `nexu-io/open-design` (Apache-2.0).
No upstream text is reproduced; the wording here is OMH's own, and OMH keeps
its deterministic no-render boundary. Product names appear as quality
analogies only; OMH is not affiliated with, endorsed by, or sponsored by any
named company.
