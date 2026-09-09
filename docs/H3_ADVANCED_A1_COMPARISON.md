# Advanced A1 Comparison Package

## Status

This is the static A/B package for `ADVANCED-A1`. GPU execution was **not
used** in this checkpoint, so no visual superiority claim is made.

## A — Golden V1

- Workflow: `04_Drone_Aerial`
- Classification: `GOLDEN_V1_PRODUCTION_BASELINE`
- Input mode: I2VA, one first-frame reference
- Graph: 15 nodes / 18 API semantic links
- Model, sampler, scheduler, VAE pair, 1344x768, 24fps, 20 steps, and seed:
  unchanged comparison baseline

## B — Advanced V2

- Workflow: `06_Advanced_Architecture_Camera_V2`
- Classification: `EXPERIMENTAL_V2`
- Base reference: `04_Drone_Aerial`
- Graph: 15 nodes / 18 API semantic links
- Same reference, duration, resolution, fps, steps, seed, model, sampler,
  scheduler, and VAE pair as A
- Changed execution variable: architecture-camera prompt conditioning
- Changed metadata variable: experimental output prefix/workflow identity

## Why

The current H3 node contract has no camera-control, motion-strength, or
reference-strength input pins. V2 therefore uses only a real execution surface
that exists today: the official H3 prompt conditioning path. The profile asks
for controlled slow push/orbit semantics, locked building identity, façade and
material preservation, horizon stability, and no structural morphing or
spontaneous additions. No disconnected camera node or fake slider is exposed.

## Static result

- API workflow: PASS
- UI reconstruction contract: PASS
- Both video/audio VAE decode links: PASS
- Managed node inventory: PASS
- Golden V1 zero-diff gate: PASS
- Native Comfy GPU run: NOT RUN

## Visual rubric for the future owner-authorized A/B run

| Criterion | A Golden | B V2 | Notes |
|---|---:|---:|---|
| Geometry preservation | pending | pending | Score 1–5 from rendered frames |
| Reference fidelity | pending | pending | Score 1–5 |
| Camera smoothness | pending | pending | Score 1–5 |
| Material stability | pending | pending | Score 1–5 |
| Temporal stability | pending | pending | Score 1–5 |
| Architectural hallucination | pending | pending | Score 1–5; higher means fewer artifacts |
| Overall visual quality | pending | pending | Score 1–5 |

## Decision

`V2_NEEDS_ITERATION` — provisional static-only classification. This is not a
visual rejection; it records that objective GPU/visual evidence is intentionally
pending and the workflow must not be promoted yet.
