# H3 Advanced Workflow Baseline

## Scope

This document records the immutable `GOLDEN_V1_PRODUCTION_BASELINE`. The
five production workflows remain the fallback and comparison arm for Advanced
Product Layer work. No Golden JSON is edited by A1.

## Capability matrix

| Workflow | Use case | Input / reference role | Camera behavior | Video profile | Sampling / VAE | Strengths | Known limitation | Historical evidence |
|---|---|---|---|---|---|---|---|---|
| `01_Exterior_Hero` | Exterior presentation | I2VA, first frame | Slow push/pull/pan/arc | 1344x768 or 1280x720, 24fps | Native sampler, 20-step baseline, video + audio VAE decode | Clean façade reveal and conservative motion | Single-frame geometry limits large perspective change | Native diagnostic pass |
| `02_Day_Night_Transition` | Day-to-night transition | FL2VA, first + last frame | Static transition | 1344x768 or 1280x720, 24fps | Native sampler, 20-step baseline, video + audio VAE decode | Explicit endpoint conditioning and lighting transition | Does not provide free camera trajectory | Native diagnostic pass |
| `03_Material_Detail` | Material and façade detail | I2VA, first frame | Static / close detail | 1344x768 or 1280x720, 24fps | Native sampler, 20-step baseline, video + audio VAE decode | Texture and material emphasis | Local material softening during motion | Native diagnostic pass |
| `04_Drone_Aerial` | Masterplan / campus aerial reveal | I2VA, first frame | Small-amplitude aerial reveal / slow arc | 1344x768 or 1280x720, 24fps | Native sampler, 20-step baseline, video + audio VAE decode | Best validated aerial baseline; geometry-safe conservative motion | Large orbit and 360-degree rotation are not reliable | Native Golden validated; real output and CURRENT binding verified |
| `05_Slow_Walkthrough` | Interior / courtyard walkthrough | I2VA, first frame | Very slow forward push / tracking | 1344x768 or 1280x720, 24fps | Native sampler, 20-step baseline, video + audio VAE decode | Stable, restrained walkthrough language | Single-frame deep walkthrough drift; no segmented stitching | Native diagnostic pass |

## Shared topology

The Golden API graphs use the same native H3 execution family: reference image
and CLIP conditioning feed `MiniMaxH3ImageToVideo`, then native sampling,
video VAE decode, audio VAE decode, video/audio mux, and MP4 save. The video
decode must remain connected to the video VAE and the audio decode to the audio
VAE. The UI handoff reconstructs those links from the API snapshot.

## Baseline hashes

The five Golden API files are guarded by `tests/test_advanced_workflows.py`.
The expected SHA-256 values are intentionally kept in the test as a zero-diff
gate; A1 assets live under a separate `production_workflows/advanced/` folder.

## A1 boundary

`06_Advanced_Architecture_Camera_V2` is an isolated `EXPERIMENTAL_V2` graph.
It is not part of `runtime/contracts/workflow_mapping.yaml`, the production
selector, or the default Job routing. No quality claim is made until a future
owner-authorized A/B run produces real output evidence.
