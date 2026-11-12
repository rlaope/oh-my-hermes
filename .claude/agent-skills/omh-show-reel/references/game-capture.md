# Game and simulation capture lane

Use this page when the reel is captured from a game or simulation (engine
playthrough, sandbox build, recorded gameplay) instead of authored from static
assets. The pipeline is fixed: simulate → capture → `timeline.json` → finish
edit. `timeline.json` is the single source of truth for the whole edit: every
event, SFX cue and title lives there and the finished edit is assembled from it
alone. Capture and edit decisions made outside it do not exist.

## Pin the source build

Pin and record the exact source game data version/build before capture: engine
or simulation build ID, data/content revision, capture date and session. The
edit is valid only against that pinned build; if the source build changes,
recapture rather than splicing across builds.

## timeline.json is the single source of truth

Every gameplay event that needs sound maps to a cue in `timeline.json`, and a
title card is a timeline entry like any other event. Review the timeline before
the edit: if a gameplay event needs SFX and has no corresponding cue, the edit
is HOLD until the cue is authored — never patch sound on top of the finished
edit outside the timeline.

## Shorts defaults (all overridable by the brief)

Shorts-form reels default to 1080x1920, black letterbox bars around the
captured footage, a centered white title, fade-in at open, and a tuned BGM
start offset so the music lands on the first event. These are defaults only —
the brief overrides any of them.

## Voice provenance

For any real voice (an in-game or external recording), record the source clip
URL, its sha256, and the excerpt range used. Never synthesize an impersonation
of a real voice actor or person. If a timbre-alike or synthetic voice method is
used, label the method honestly in the credits. Performer and IP permissions
stay in the existing assets-and-rights flow.
