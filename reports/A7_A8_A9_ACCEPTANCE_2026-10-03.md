# A7–A9 Acceptance Evidence

Date: 2026-10-03
Scope: existing Director/retake, delivery, and long-form evidence only. This
closeout adds no GPU generation and does not alter historical Jobs or Results.

## A7 — Director, Timeline, and Retake

Decision: `PASS_WITH_BOUNDED_LIMITATIONS`

- The existing Director shot and its retake are both completed, each with one
  persisted Result. The retake has explicit source lineage and a new Job; no
  historical Job was rewritten.
- Sampled start/middle/end frames show broad site and building identity
  continuity. The middle composition changes somewhat, while the ending
  compositions remain similar. Camera-intent differentiation is therefore
  weak/partial in this evidence set.
- `camera_intent` is an instruction to generation, not a deterministic 3D
  camera path, camera XYZ API, or guarantee of a distinct final composition.
- Product assessment is based on the existing bounded sample review, not an
  Owner acceptance review and not a claim about every workflow.

## A8 — Delivery Enhancement

Decision: `PASS_WITH_BOUNDED_LIMITATIONS`

The A8 work reused one already-completed native clip and performed CPU-only
post-processing. It submitted no Comfy `/prompt` request and ran no H3
inference. The delivered derivatives and probe evidence are:

| Output | Resolution | FPS | Decoded frames | Container duration |
|---|---:|---:|---:|---:|
| Native-size delivery | 1344×768 | 48 | 214 | 4.48 s |
| Native-size delivery | 1344×768 | 60 | 268 | 4.48 s |
| 1080p-class delivery | 1920×1080 | 24 | 107 | 4.48 s |
| 2K-class delivery | 2048×1152 | 24 | 107 | 4.48 s |

- All four derivatives were CPU FFmpeg outputs with H.264 video and audio.
  Frame counts come from decoded-frame evidence, not a nominal FPS label.
- The native source is 1344×768 (7:4). The 16:9 delivery sizes preserve
  aspect ratio with narrow side padding; they do not claim new native H3 detail
  or AI restoration.
- Bounded visual inspection covered one existing Director clip at three
  timeline positions and selected interpolation in-betweens. It found no
  obvious black frames, severe ghosting, or gross geometry drift in those
  samples. It is not a general quality guarantee for all scenes or motion.
- Container duration rounds to 4.48 s; decoded frame-count/FPS arithmetic is
  slightly different because of the encoded media timebase. These values are
  retained as separate measurements rather than treated as exact equivalents.
- Delivery HTTP byte serving and Range behavior were validated. The A8 media
  probe regression was fixed and pushed separately; the canonical suite then
  passed with 1025 tests, 38 expected skips, and zero failures.

## A9 — Long-Form Queue and Assembly

Decision: `PASS_WITH_BOUNDED_LIMITATIONS`

- The existing five-shot queue is `READY`; all five shots are `RESULT_READY`.
  It reuses two prior completed Results and includes three newly completed
  shot Jobs. No generation was performed during this closeout.
- A single assembled output is present with a persisted output SHA-256 and
  verified size of 24,905,915 bytes. Its recorded media contract is
  1344×768, 24 FPS, 22.3 s, H.264 with audio, with post-processing marked
  false.
- The local Studio media route currently returns `206 Partial Content` for a
  one-byte Range request and reports the expected total length. The route
  validates the assembly file against the persisted output hash before
  serving it.
- Queue restart/reconciliation was previously verified to resume at the
  assembly step without another `/prompt`. This closeout made no queue or
  Result mutation.
- The historical assembly record has no decoded `frame_count` and identifies
  its older probe as `managed_ffmpeg_compatibility`. Accordingly, no exact
  assembled frame count is claimed here. New media probes now preserve decoded
  counts; the historical record remains immutable.
- Existing bounded visual review found some shot similarity and a weakly
  differentiated camera narrative. This is a continuity/sequence-quality
  limitation, not an assembly or Result-persistence failure.

## Privacy, runtime, and durable state

- No Prompt text, reference pixels, generated media, private absolute paths,
  credentials, tokens, or raw runtime logs are included.
- Production ComfyUI remains 0.33.1 on port 8189. The isolated experimental
  runtime on port 8190 remains offline. No model, Golden workflow, or
  historical Result was changed.
- The pre-report code baseline and its origin tracking ref were identical at
  `bb8af261557b55321b7c0d2ea30978ce955e3915`.
- External agents: none for this closeout. The prior Antigravity attempt did
  not return a reviewer result; no external review is represented.

## Roadmap boundary

These records support the bounded A7–A9 acceptance claims above. They do not
close A10 or final C/D/E/F product closeout. Remaining closeout gates include
the end-to-end product acceptance scenario, final reliability/privacy/license
checks, UI/accessibility review, and clean-like packaging/install validation.

Under the master program's staged progress scale, A9 closes G at 85% of its
10% roadmap weight (8.50 percentage points), for a 94.30% implemented
roadmap total. This is not A10 completion and does not close the remaining
C/D/E/F gates.
