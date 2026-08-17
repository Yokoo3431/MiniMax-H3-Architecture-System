# Workflow Spec — 05_Slow_Walkthrough

## Purpose
Pedestrian eye-level slow spatial walkthrough (entrance, corridor, atrium, street,
interior/exterior transition) with restrained forward motion.

## Input
- 1 user-approved perspective image with clear depth and an obvious travel
  direction (no extreme aerial viewpoint, no flat elevation-only composition).

## Skill Mode
- `I2VA` (one first-frame image).

## Motion
- Very slow forward Push In / subtle forward Tracking Shot, small amplitude, slow
  speed; nearly constant height and stable horizon/perspective.
- Prohibited: large rotation, dramatic vertical motion, fast movement, geometry
  redesign, scene cuts.

## Preservation (highest priority)
- walls, columns, openings, doors/windows, ceiling lines, floor edges, facade
  rhythm, handrails, landscape boundaries, material identity, perspective geometry.
- Principle: `SPATIAL STABILITY > CAMERA DISTANCE`.

## Known Limitation
- `SINGLE_FRAME_DEEP_WALKTHROUGH_LIMITATION`: single-image depth reconstruction
  softens at later frames (non-blocking). Future production: multiple architectural
  render angles, first+last keyframes (FL2VA), multi-reference/key frames, segmented
  clips stitched into longer walkthroughs.

## Validated Evidence (PATCH2.4)
- `NATIVE_DIAGNOSTIC_PASS` — prompt_id `875df626-bf52-4c6d-99a1-a8da3bebcd69`,
  1344×768 / 24fps / 107 frames / 4.458s, human review PASS.
