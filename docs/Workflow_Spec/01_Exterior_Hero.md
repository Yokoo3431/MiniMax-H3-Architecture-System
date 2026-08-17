# Workflow Spec — 01_Exterior_Hero

## Purpose
Architectural presentation video revealing a building facade with a subtle
cinematic hero animation while retaining facade fidelity.

## Input
- 1 user-approved exterior hero image (single main building, clear facade/roof
  edges, high resolution, stable perspective, minimal foreground obstruction).

## Skill Mode
- `I2VA` (one first-frame image), official MiniMax H3 h3-prompt-writing structure.

## Motion
- Preferred: slow cinematic reveal / small-amplitude slow Push In, or very small
  slow Arc Shot.
- Avoid: dramatic orbit, large perspective change, fast zoom, scene cuts.

## Preservation (highest priority)
- massing, facade, roof, opening rhythm, material identity, perspective, landscape
  composition.

## Known Limitations
- Single-frame geometry limitation: large viewpoint reconstruction is not supported
  by one I2VA image.

## Validated Evidence (PATCH2.4)
- `NATIVE_DIAGNOSTIC_PASS` — prompt_id `58080294-1045-40d8-a781-510ffc582dc6`,
  1344×768 / 24fps / 107 frames / 4.458s, PREAD safe load, human review PASS.
