# Advanced A1 Comparison Package

## Status

This is the A/B evidence package for `ADVANCED-A1`. The sampler-parity repair
was authorized and validated with one new V2 B-arm GPU run. The technical
fair-comparison gate now passes. The owner-visible score is recorded below;
this does not constitute a production-promotion or superiority claim.

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

## Owner visual score

Scores below are based on the local 0% / 25% / 50% / 75% / 100% frame
checkpoints from the valid pair only: A is Golden V1 and B is the repaired
Advanced V2 Job. The historical pre-repair B Job was excluded. Higher is
better; the architecture criteria are weighted qualitatively more heavily than
camera motion.

| Criterion | A Golden | B V2 | Notes |
|---|---:|---:|---|
| Geometry preservation | 2 | 4 | B preserves the sail/roof mass and site layout more consistently |
| Reference fidelity | 2 | 4 | A drifts from the reference building form in the middle/end checkpoints |
| Camera smoothness | 4 | 3 | A has clear continuous displacement; B is stable but under-moves |
| Material stability | 3 | 4 | B keeps façade, landscape, and shoreline materials steadier |
| Temporal stability | 2 | 4 | A shows stronger form instability; B has fewer visible temporal changes |
| Architectural hallucination | 2 | 4 | A introduces visible roof/form changes; B has fewer additions/removals |
| Overall visual quality | 2 | 3 | B is the stronger architecture result but is not production-ready as motion |

## Camera tradeoff

`B = TOO STATIC` — the repaired V2 prompt conditioning improves geometry and
reference retention, but the camera displacement is too weak to count as a
successful camera-control outcome. B is not scored as automatically better:
its architectural gain is offset by insufficient useful motion.

## Final A1 decision

`V2_NEEDS_ITERATION` — keep the repaired sampler parity and the improved
architecture/reference preservation, but iterate the prompt conditioning before
considering promotion. The top A2 inputs are:

1. Increase motion-language strength while preserving the geometry lock.
2. Separate the camera phrase from the geometry-preservation constraints so
   the latter do not freeze the shot.
3. Reduce overconstraint/negative phrasing that suppresses useful displacement.

A2 is implemented as a separate experimental profile below; it does not alter
the repaired A1 graph or its historical evidence.

## Decision

`ADVANCED_A1_COMPLETE` — the repaired A/B artifacts pass the technical
fair-comparison gate, and the owner-visible review records `V2_NEEDS_ITERATION`.
V2 remains experimental and is not promoted.

## A2 — Motion / Fidelity Experiment

`07_Advanced_Architecture_Camera_V2_1` is an isolated follow-on profile from
the durable A1 baseline `79bc895f39ac0b482d1decb730296ed4f3e19d70`. It keeps the
same native 15-node / 18-link topology, model family, UNet, CLIP, video/audio
VAE pair, scheduler, `euler` sampler, 4s duration, 1344x768 resolution, 24fps,
50 steps, seed 42, and approved reference. Only the prompt-conditioning
semantics and experimental output identity changed.

The A2 prompt is divided into three explicit semantic blocks:

1. `CAMERA MOTION BLOCK` — controlled slow forward aerial push, steady speed,
   shallow oblique path, restrained parallax, stable horizon.
2. `ARCHITECTURE PRESERVATION BLOCK` — locked building massing, roof silhouette,
   façade proportions, openings, structural edges, materials, and site relation.
3. `MINIMAL NEGATIVE CONSTRAINT BLOCK` — only structural morphing, spontaneous
   additions, and disappearing major elements are prohibited.

The A2 graph remains outside the production selector and is classified as
`EXPERIMENTAL_A2`. Static validation passed for API/UI reconstruction, both
VAE decode paths, 15 nodes, 18 links, and the inherited execution controls.
Golden V1 and A1 assets remain unchanged.

## A2 GPU evidence

- Job: `job-307b93d23953`
- Workflow: `07_Advanced_Architecture_Camera_V2_1`
- Terminal state: `COMPLETED` / `SUCCEEDED` / `DELIVERED`
- Recovery: the original single submission exceeded the local 1800-second
  observation window; the same Comfy history was finalized after the original
  prompt left the queue, with no resubmission.
- Snapshot: `ca5ab0412e7fd3b14a5b6857`
- Execution/workflow SHA-256:
  `88720c16de5e0536fcc9412af2801731602f2d0e05e7d4a99975d0769cd93178`
- Execution controls: 15 nodes / 18 API links; `KSamplerSelect=euler`;
  duration 4s, 1344x768, 24fps, 50 steps, seed 42.
- Output: available, `video/mp4`, 6,044,242 bytes
- Managed media probe: 4.46s, 1344x768, 24fps, H.264, audio present

## Three-way owner visual score

Scores use local 0% / 25% / 50% / 75% / 100% checkpoints from A Golden V1,
B1 repaired A1, and B2 A2. The temporary frame files remain local and are not
part of the repository or any remote upload.

| Criterion | A Golden | B1 A1 | B2 A2 | Notes |
|---|---:|---:|---:|---|
| Geometry preservation | 2 | 4 | 4 | A2 retains the repaired A1 geometry behavior |
| Reference fidelity | 2 | 4 | 4 | No visible regression from A1 |
| Camera smoothness | 4 | 3 | 3 | A2 remains under-moved; no material motion gain over A1 |
| Material stability | 3 | 4 | 4 | Shoreline, vegetation, and façade remain stable |
| Temporal stability | 2 | 4 | 4 | No meaningful temporal regression |
| Architectural hallucination | 2 | 4 | 4 | No major new architectural additions/removals observed |
| Overall visual quality | 2 | 3 | 3 | Stable architecture, but motion objective is not met |

## A2 decision

`A2_NEEDS_ITERATION` — the separated prompt blocks preserve the A1 repair
quality, but they do not produce a materially stronger controlled camera move
than B1. The next iteration should increase camera displacement/parallax while
loosening the preservation language enough to avoid freezing the shot; it must
retain the same native topology and fair-comparison controls.

No automatic promotion, merge, tag, release change, or production selector
change was made.
