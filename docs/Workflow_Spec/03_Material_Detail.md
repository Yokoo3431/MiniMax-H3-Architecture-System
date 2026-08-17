# Workflow Spec — 03_Material_Detail

## Purpose
Animate a close/medium architectural material view while preserving fine material
identity and construction detail. NOT a camera-motion showcase.

## Input
- 1 user-approved material/detail image with visible joints/seams/texture
  (concrete, stone, metal, timber, glass curtain wall, louvers, mullions, etc.).

## Skill Mode
- `I2VA` (one first-frame image).

## Motion
- Static Shot with extremely subtle camera drift (micro motion); a very small slow
  Push In is allowed only if it helps reveal detail.
- Avoid: rack focus, large zoom, strong parallax, lateral translation, dramatic
  depth change, scene cuts.

## Preservation (highest priority)
- exact material identity, texture scale/direction, panel dimensions, joint spacing,
  seam position, shadow gaps, edge sharpness, frame/mullion proportions, reflectivity,
  color, roughness appearance, architectural geometry.
- No texture swimming/crawling, material morphing, seam disappearance, edge wobble,
  facade melting, reflection flicker.

## Principle
- `MATERIAL_FIDELITY_OVER_MOTION` (highest priority).

## Known Limitations
- `LOCAL_MATERIAL_SOFTENING_UNDER_GENERATIVE_MOTION`: local ROI sharpness decreases
  toward later frames while global edge energy stays stable (non-blocking; future:
  smaller motion, stronger workstation, multi-reference views, post-generation
  detail restoration / 2K regeneration).

## Validated Evidence (PATCH2.4)
- `NATIVE_DIAGNOSTIC_PASS` — prompt_id `7a0d27d8-0b92-4912-91db-bd85e622eb94`,
  static camera, ROI analysis recorded, human review PASS.
