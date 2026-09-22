# Advanced A1 Comparison Package

## Status

This is the A/B evidence package for `ADVANCED-A1`. The sampler-parity repair
was authorized and validated with one new V2 B-arm GPU run. The technical
fair-comparison gate now passes. No visual superiority claim is made until the
owner scores the rendered A/B outputs.

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
  4s, 1344x768, 24fps, 50 steps, seed 42; model, scheduler, sampler, and VAE
  pair remained unchanged after the repair.
- Intended changed execution variable: architecture-camera prompt conditioning
- Changed metadata variable: experimental output prefix/workflow identity

## Fair-comparison gate

The sampler-parity repair is complete. The persisted top-level Job parameters
agree on reference, duration, resolution, fps, steps, seed, quality, and
acceleration settings. The Native Comfy execution snapshots also agree on the
CLIP, UNet, VAE, and sampler assets.

| Control | A — Golden V1 | B — Advanced V2 | Gate |
|---|---|---|---|
| Native `KSamplerSelect.sampler_name` | `euler` | `euler` | PASS |
| Top-level `generation_parameters.sampler_mode` | `euler` | `euler` | PASS |

The execution graph is authoritative, and it now agrees with the persisted
metadata on both arms. The intended change remains the architecture-camera
prompt conditioning only. Visual frame checkpoints and 1–5 owner scores remain
pending an owner viewing pass.

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
- Native Comfy GPU run: PASS (one repaired B-arm submission; prior timed-out
  observation was recovered without resubmission)
- Fair A/B comparison gate: PASS (sampler parity and identity checks)

## Sanitized repaired B-arm evidence

- Job: `job-af6a7bf280ac`
- Terminal state: `COMPLETED` / `SUCCEEDED` / `DELIVERED`
- Prompt acknowledgement: received; observation exceeded the 1800-second
  client window, then the same server-side history was finalized without
  resubmission
- Snapshot: `c26030ebf1b8e76fc0199642`
- Execution/workflow SHA-256: `abfb41e4ec66b56ccfe545fe7952bfc8612895121a00d50c7ddaf768e19420d1`
- Execution snapshot: 15 nodes / 18 API links; `KSamplerSelect=euler`
- Output: available, `video/mp4`, 5,496,061 bytes
- Managed media probe: 4.46s, 1344x768, 24fps, H.264, audio present
- AVS `/result`: PASS; media Range response: `206`, MIME `video/mp4`
- Source handoff reconstruction: PASS, 15 UI nodes / 18 UI links, API identity
  verification PASS

The earlier B-arm `job-77d5a7651dd5` remains historical evidence of the
pre-repair sampler mismatch and is not used for the fair comparison.

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

`ADVANCED_A1_OWNER_VISUAL_SCORE_PENDING` — the repaired A/B artifacts pass the
technical fair-comparison gate. Owner visual scoring is still pending, and V2
remains experimental and is not promoted.
