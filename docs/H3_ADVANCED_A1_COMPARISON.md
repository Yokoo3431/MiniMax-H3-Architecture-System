# Advanced A1 Comparison Package

## Status

This is the A/B evidence package for `ADVANCED-A1`. One owner-authorized V2 B
GPU run was completed. No visual superiority claim is made until the owner
scores the rendered A/B outputs.

## A — Golden V1

- Workflow: `04_Drone_Aerial`
- Classification: `GOLDEN_V1_PRODUCTION_BASELINE`
- Input mode: I2VA, one first-frame reference
- Graph: 15 nodes / 18 API semantic links
- Static template defaults: 1344x768, 24fps, 20 steps, seed 777888904
- Acceptance A arm reused an existing completed native `04_Drone_Aerial` Job
  at 4s, 1344x768, 24fps, 50 steps, seed 42

## B — Advanced V2

- Workflow: `06_Advanced_Architecture_Camera_V2`
- Classification: `EXPERIMENTAL_V2`
- Base reference: `04_Drone_Aerial`
- Graph: 15 nodes / 18 API semantic links
- Acceptance B used the same approved reference and runtime parameters as A:
  4s, 1344x768, 24fps, 50 steps, seed 42; model, sampler, scheduler, and VAE
  pair remained unchanged
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
- Native Comfy GPU run: PASS (one B-arm submission; no duplicate)

## Sanitized B-arm evidence

- Job: `job-77d5a7651dd5`
- Terminal state: `COMPLETED` / `SUCCEEDED` / `DELIVERED`
- Prompt acknowledgement: received; observation initially exceeded the
  1800-second client window, then the same server-side history was recovered
  without resubmission
- Snapshot: `306c58f15d978ffccfb1b608`
- Execution/workflow SHA-256: `fbc0b74119c3a825a5c69d8f37a081074c87412521329fb7fbe3e018d826f446`
- Output: available, `video/mp4`, 5,357,557 bytes
- Managed media probe: 4.46s, 1344x768, 24fps, H.264, audio present
- AVS `/result`: PASS; media Range response: `206`, MIME `video/mp4`
- Source handoff reconstruction: PASS, 15 UI nodes / 18 UI links, API identity
  verification PASS
- Installed 8788 handoff: pending packaging refresh; the currently running
  installed backend predates A1 and reports the V2 UI template is missing.
  This is an installation freshness issue, not a GPU/output failure.

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

`ADVANCED_A1_OWNER_VISUAL_SCORE_PENDING` — technical A/B evidence is ready,
but owner visual scoring and the installed DesktopShell handoff after a fresh
package install remain pending. V2 remains experimental and is not promoted.
