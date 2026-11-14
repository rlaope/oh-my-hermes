# Rendered Scene Craft

A 3D or canvas scene (WebGL or WebGPU, a three.js-style engine, a voxel world,
a generative canvas) fails differently from a page. There is no layout to
break and the console can be clean, and the scene can still ship flat: neutral
light, a toy palette, a first frame that contradicts its own title, and small
animated things that read as debris. Two builds of the same brief are judged on
the frame a person sees first, so this reference treats that frame as the
product.

## The first frame is the product

- Boot on the view the scene's own words promise. If the title or subtitle
  says golden hour, night market, or snowfall, the first rendered frame shows
  it; a time slider that boots at a position reading as flat noon contradicts
  the copy, whatever the cycle can reach later.
- Every claim the scene makes about itself (title, subtitle, HUD counters,
  README) is a check against that frame: the named landmarks are in view, the
  advertised effects are visible, and a count the HUD prints matches what the
  scene draws.
- The hero subject is framed whole at the default camera. A cropped finial or
  a landmark hidden behind the ridge is a framing defect, not a matter of
  taste.

## Light before geometry

More geometry does not fix a flat frame; light does.

- One key light with a colour temperature chosen for the time of day: low and
  warm for golden hour, high and neutral at noon, cool and dim at night. An
  ambient term alone produces the flat, shadowless look.
- A fill from the sky and ground colours (a hemisphere-style light), so faces
  turned from the key keep hue instead of going grey.
- Tone mapping set explicitly (a filmic curve) with sRGB output. Linear output
  without tone mapping reads washed out in the shadows or harsh in the
  highlights, and that is the usual difference between a scene that looks
  rendered and one that looks unfinished.
- Shadows from the key light wherever geometry stacks or overlaps; voxel faces
  of similar value merge into one mass without them.
- Atmosphere: fog or depth haze coloured from the sky gradient, so the
  foreground separates from the backdrop. Use a sky gradient matched to the
  key light rather than a flat clear colour.
- Stacked similar layers (roof tiers, terraces, cliff bands) need value
  separation, either from the light or from a step in the palette.

## Small things must read as what they are

- Every small animated object (birds, petals, insects, sparks, particles)
  reads as what it is at the default camera distance: a silhouette (a wing
  pair, a V, an elongated petal), a palette colour, and motion that fits it. A
  single dark cube reads as floating debris, even when the code calls it a bird.
- Pure black or unlit instances are a defect until the code shows they were
  intended. A near-black colour comes from the palette, under a name.
- Advertised quantities are visible quantities. If the copy promises thousands
  of petals and the first frame shows a handful, the copy or the emitter is
  wrong.

## What the scene's verdict captures

The scene's visual-QA round (`omh-visual-qa`) captures, at the target
revision:

- the first frame exactly as booted, before any input;
- each named camera preset or tour stop;
- every time of day the scene advertises, plus night when it has a cycle;
- a settled frame and a motion frame for each particle or creature layer.

Each capture is judged on the checks above. A claim that does not match its
frame, a small object that does not read, flat light with no value range, a
cropped hero, and stray dark geometry each become one `differences` entry.
A frame rate is reported only with the device class and resolution it was
measured on.

## Boundary

A lighting plan, a capture matrix, or a prepared handoff is not a rendered
frame, a frame-rate measurement, or a visual-QA PASS. Those stay
`prepared_not_observed` until the selected coding owner or wrapper supplies
captures from the target revision.
