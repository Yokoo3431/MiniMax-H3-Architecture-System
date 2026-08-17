# Workflow Spec — 02_Day_Night_Transition

## Purpose
Same architectural visualization moving through time from a DAY state to a NIGHT
target — lighting/environment transformation, not scene regeneration.

## Input
- 2 user-approved matched images:
  - Picture 1 = DAY first frame
  - Picture 2 = NIGHT last frame (same architecture, near-identical camera/framing).

## Skill Mode
- `FL2VA` (REQUIRED). Alignment: Picture 1 @ 0.00s; Picture 2 @ S.SS (4.46s for
  107 frames @ 24fps).

## Motion
- Static Shot, or nearly static with extremely subtle drift.

## Allowed Transformation
- sky brightness/color, ambient brightness, interior/facade/landscape/street
  lighting, shadow softness, color temperature, controlled reflections.

## Prohibited
- geometry change, camera movement, material replacement, scene regeneration.

## Principle
- `LIGHTING_TRANSFORMATION_OVER_SCENE_REGENERATION` (highest priority).

## Validated Evidence (PATCH2.4)
- `NATIVE_DIAGNOSTIC_PASS` — prompt_id `a31f13f3-5b8b-41f4-876e-8d31a8f96296`,
  FL2VA orientation verified in MP4 metadata, first-vs-DAY SSIM 0.9918 /
  last-vs-NIGHT SSIM 0.9779, human review PASS.
