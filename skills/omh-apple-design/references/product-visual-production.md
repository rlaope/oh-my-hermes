# Apple Product Visual Production

## Reference record

Select concrete references for the deliverable; use the observations to direct
original work, not to copy assets or claim an Apple specification.

- Apple MacBook Pro, accessed 2026-09-05: https://www.apple.com/macbook-pro/
  — metal edge light, dark studio, and silhouette-led framing.
- Apple AirPods Pro, accessed 2026-09-05: https://www.apple.com/airpods-pro/
  — macro scale, white ceramic/plastic reading, and restrained negative space.
- Apple Vision Pro, accessed 2026-09-05: https://www.apple.com/apple-vision-pro/
  — glass, physical depth, and controlled reflection.
- Apple HIG Motion, Materials, and App icons, accessed 2026-09-05:
  https://developer.apple.com/design/human-interface-guidelines/motion,
  https://developer.apple.com/design/human-interface-guidelines/materials, and
  https://developer.apple.com/design/human-interface-guidelines/app-icons
- Apple Icon Composer, accessed 2026-09-05:
  https://developer.apple.com/icon-composer/ — a multilayer native icon-asset
  pipeline, not a marketing renderer.

## Choose the visual target before output

Choose one target and keep its rules separate:

1. **Apple marketing/product visual** — an original subject-led hero, product
   render, or landing visual. It may use the reference observations above, but
   is not native UI and must not copy Apple logos, products, photography, or SF
   assets.
2. **Native Apple application** — use the platform foundations, HIG, and
   platform asset pipeline. Marketing composition does not replace toolbars,
   navigation, controls, or input behavior.
3. **Apple-inspired web UI** — make a deliberate web adaptation with web
   semantics, accessibility, and opaque/reduced-motion fallbacks; it is not a
   native application or Liquid Glass implementation.

## Product-visual direction

For a marketing/product visual, write an original art-direction record before
making an image or scene:

- subject geometry and silhouette, including chosen bevel/radius;
- camera position, focal perspective, framing, crop, and copy-safe negative
  space;
- metal, glass, or plastic material behavior. State micro-roughness,
  transmission, and reflection values as **renderer/project choices**, never
  Apple specifications;
- key, fill, rim, and grounding-shadow decisions; constrained palette,
  backdrop, and subject scale; and
- a strong single subject, controlled large type/spacing/crop, and gallery
  variations only when the deliverable benefits from them. Do not substitute
  blue rounded SaaS cards or universal glassmorphism for the composition.

## Reference -> production -> comparison -> revision

1. Name the selected reference pages and which observable dimensions apply to
   this deliverable: silhouette, material, light, depth, composition, or type.
2. Create original object and copy direction. Preserve user-supplied assets and
   constraints; do not scrape or reuse reference assets.
3. Identify the available execution mode before claiming an artifact:
   - With an authorized connected image-generation tool, request actual output
     and label it a **generated still image** with its tool and prompt variant.
     A text-only tool can prepare paired prompt variants and a combined
     comparison; it cannot claim image-to-image editing.
   - With an authorized, confirmed available Blender or other 3D renderer,
     prepare or execute its scene/render through the selected owner. A local
     realtime shader render is an observed render mode when its renderer output
     is available, but it is not an exported mesh or validated path trace. A
     raster output alone does not verify a mesh or physical correctness.
   - With frontend execution, implement only the authorized web behavior; CSS
     depth does not prove a renderer, mesh, or native material.
   - If an image generator is unavailable but an authorized renderer or coding
     owner is available, use that actual production path. Only when no execution
     path is available, state the exact missing boundary and provide a prepared
     prompt/scene handoff. Do not call the handoff generated or rendered.
4. Compare the same subject, camera, and content where feasible. If there is no
   user original, label the baseline clearly as synthetic. Name changed
   dimensions and remaining limits; open actual files/screenshots to the user
   on request, then revise from the observed comparison.

## Motion and review

Storyboard camera path, object/material reveal, and interaction timing as
project decisions. Implement motion only through an available renderer or
coding owner with authorization; provide a reduced-motion alternative. A still
image never proves motion: require actual frames, video, or browser evidence.

Review against the selected reference dimensions: silhouette, material, light,
composition, type, and technical artifact evidence. Do not assign an arbitrary
Apple score or certification. A prepared direction, prompt, or scene is not
image generation, rendering, animation, visual QA, or implementation evidence.
