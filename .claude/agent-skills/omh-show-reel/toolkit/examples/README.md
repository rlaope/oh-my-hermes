# Worked local examples

`new_project.py` copies upstream's API example to `reel/_example_scenes.js`
(not loaded). It shows the engine calls; do not start a film from its screens.
`timing.json` demonstrates explicit multilingual cue IDs without narration;
`music-spec.json` is a local authored synthesis example for `synth_music.py`
(and `music_tools.py plan`).

Example mix-spec (save beside a rights-cleared `score.wav`):

```json
{"duration":4,"sample_rate":48000,"mode":"music-only","music":{"file":"score.wav","gain_db":-3,"automation":[[0,-6],[1,0],[3,0],[4,-12]]},"sfx":[]}
```

Sound creation/metrics are not hearing or artistic review. These are teaching
fixtures, not completed product execution footage, audience results, or a film.
