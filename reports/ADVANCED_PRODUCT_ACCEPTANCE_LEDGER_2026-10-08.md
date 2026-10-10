# Advanced Product Acceptance Ledger

Date: 2026-10-08
Decision: `PARTIAL_WITH_BOUNDED_LIMITATIONS`
Purpose: consolidate durable A5–A10 capability evidence and the final app-only
upgrade acceptance without rewriting historical Jobs or Results.

## Executive outcome

The advanced product path has real execution, Result, delivery, and assembly
evidence across A5–A10. The app-only release identity drift is corrected, and
an isolated Windows upgrade from the existing RC1 package to RC3.3 completed
successfully. This is not a blanket quality guarantee or Owner sign-off:
native 2K generation, AI super-resolution/restoration, deterministic camera
paths, exact guide timing, and broad visual-quality acceptance remain
unvalidated or bounded as noted below.

No H3 inference or Comfy `/prompt` was submitted during this final closeout.
Existing Jobs and Results were reused. No ComfyUI or model was downloaded,
installed, upgraded, or copied by the app-only installer test.

## Capability ledger

| Capability | Implementation / static contract | Execution / delivery evidence | Visual / product decision |
|---|---|---|---|
| A5 multi-frame storyboard | Typed guide provenance, deterministic frame resolution, AddGuide compiler and explicit experimental-runtime routing. Boundary references remain distinct from timeline guides. | Completed Job `job-bacd936c9285`; two guides resolved to frames 36/72; native AddGuide; 832×480, 24 FPS, 107 frames; Result/media SHA-256 `04a5c90739e0930f42cb19331d21276a60874bb0069b8c2a08a037369ff1426a`. | `PASS_WITH_BOUNDED_LIMITATIONS`: broad building/site identity retained; guide 2 timing response weak; transitions are editorial cuts, not camera motion. Fine detail not rated. The earlier failed forensic Job remains unchanged and its ambiguous media was not adopted. |
| A6 Ref2VA image roles | Existing approved-reference architecture extended for image roles; video/audio ingest fails closed. | Completed Job `job-ad5ecf91beee`; `identity_reference` + `site_reference`; 832×480, 24 FPS, 107 frames; Result/media SHA-256 `da7e3bdd4295fd6295076ba7ad29ffcad9834313b765c6de077875cd7744d0e6`; HTTP Range 206. | `PASS_WITH_BOUNDED_LIMITATIONS`: coarse identity/massing only; no fine-detail score. Video/audio references remain unavailable. A second historical attempt failed before sampling and was not retried. |
| A7 Director / Retake | Shot, retake, lineage, and Result contracts are present. | Existing completed source/retake chain: `job-af6a7bf280ac` → `job-307b93d23953`; persisted Results and lineage. | `PASS_WITH_BOUNDED_LIMITATIONS`: camera intent is prompt guidance, not XYZ/6DoF control; observed shot differentiation was weak/partial. |
| A8 1080p / 2K delivery | CPU FFmpeg delivery path; Lanczos resize/padding and MCI interpolation are explicitly distinguished from native H3 detail. AI restoration is not implemented. | Existing 1080p24, 2K24, 48 FPS and 60 FPS derivatives have decoded-frame evidence. This closeout additionally verified an existing native 1344×768 source delivered at 2048×1152/48 FPS: 214 decoded frames, 4.458333 s, H.264 with audio, 12,325,152 bytes; independent ffprobe passed; Range 206; delivery SHA-256 `fa37876bba65f7566b601f835a09cf482b273ee7380c3c2956994043ea48d0b2`. CPU FFmpeg only; no H3 inference. | `PASS_WITH_BOUNDED_LIMITATIONS` for tested CPU delivery. These outputs do not prove native 2K generation or added AI detail. Visual inspection was sample-bounded. `NATIVE_2K_NOT_VALIDATED`; AI SR/restoration unavailable. |
| A9 long-form queue / assembly | Multi-shot queue, restart reconciliation, assembly, and output-hash validation are implemented. | Existing five-shot queue had 5/5 `RESULT_READY`; assembled 1344×768/24 FPS, H.264 with audio, 22.3 s, 24,905,915 bytes; SHA-256 `580ed50e211f57355ec2b34f842b90c250afeb0751f2907c48802ba21ff31e9b`; HTTP Range 206. | `PASS_WITH_BOUNDED_LIMITATIONS`: some shot similarity and weak camera narrative. Historical assembled frame count was not available, so none is claimed. |
| A10 advanced productization | Cross-stage contracts and fail-closed incompatibility boundaries are covered by source and regression tests. | Existing A10 record and real A5–A9 Job/Result evidence; final CPU regression in this closeout passed 1089 tests, 15 skipped, 0 failed. | `COMPLETE_WITH_BOUNDED_LIMITATIONS` as recorded in the A10 report; not a claim that every advanced control was composed in one H3 execution. |
| Final F app-only upgrade | Tracked release identity is the single candidate source; app registration version derives from the packaged runtime manifest. | Existing RC1 app-only package installed in a task-isolated folder, started healthy on a non-production port, then upgraded with the RC3.3 app-only installer (exit 0). RC3.3 restarted healthy in setup mode. Synthetic install-data and separate-data-root SHA-256 markers were unchanged. The package manifest states 577 payload files, `runtime_bundled=false`, `models_bundled=false`; install contains no ComfyUI or models directory. | `PASS` for this isolated app-only upgrade path. Existing ComfyUI/model/runtime state was not installed, copied, or changed. Prior F3P3 clean-install/repair/restart/uninstall/data-preservation evidence remains in its original record. |

## Runtime, privacy, and reliability boundaries

- Production Studio remained healthy on 8788; production ComfyUI remained
  ComfyUI 0.33.1 on 8189 with queue 0 running / 0 pending.
- Experimental 8190 remained offline; the isolated installer acceptance used
  app-only setup mode and did not start ComfyUI.
- Golden workflow regression remained zero-diff. No production model or
  historical Job/Result was modified.
- The full canonical suite passed: 1089 tests, 15 skipped, 0 failed. The
  regression inventory check reported `ADDED 0 / REMOVED 0 / SKIP_CHANGED 0`.
- Python compile, JavaScript syntax checks, JSON parsing, manifest validation,
  and `git diff --check` passed for this closeout.
- No Prompt contents, reference/generated media, credentials, tokens, private
  absolute paths, or raw runtime logs are included in this ledger.
- Independent external review did not return: Observer run
  `20261008114135-agy-670d64ab` failed at AGY eligibility with service
  unavailable (503); the one permitted CLI Bridge fallback failed before
  `agy.exe` launch with a Windows argument-length error. No external Review
  opinion is claimed.

## Overall acceptance

`PARTIAL_WITH_BOUNDED_LIMITATIONS` — A5–A10 execution/product paths and the
RC1→RC3.3 app-only upgrade have evidence, but the limitations above prevent a
broader claim of deterministic camera control, exact storyboard timing, native
2K/AI restoration, universal visual quality, or Owner-approved final product
acceptance. This ledger does not change roadmap weights or progress values and
does not create a public Release or tag.

## Supplemental read-only verification (2026-10-10)

### A8 2K derivative detail check

The existing A8 source/result pair was decoded locally without changing either
artifact. The 1344×768 native source is 107 frames at 24 FPS (4.458 s); its
2048×1152 2K24 derivative is also 107 frames at 24 FPS (4.48 s). The derivative
uses CPU FFmpeg Lanczos resampling with aspect-preserving scale and centered
padding, H.264 High/yuv420p, and no restoration stage. Its larger bitrate and
file size are encoding/resolution facts, not evidence of newly recovered
architectural detail.

For diagnostic comparison only, frames 16, 53, and 90 of the 2K derivative
were cropped to remove the centered side padding, downscaled to the native
canvas, and compared with the corresponding native frames. PSNR was
38.390, 41.060, and 39.989 dB. Laplacian variance did not show a consistent
detail gain across the three samples. These measurements are not a perceptual
quality score and the manual architectural-detail review remains incomplete.
Classification remains `NATIVE_2K_NOT_VALIDATED`; AI super-resolution and
restoration remain unavailable.

### Local AI restoration capability check

Production 8189 remains ComfyUI 0.33.1 with an idle queue. Live `/object_info`
shows SeedVR2 preprocessing, conditioning, temporal chunk/merge, and
postprocessing nodes, but the model listing contains only the existing H3
diffusion model and H3 VAEs. `UNETLoader` has no SeedVR2 model choice, the
generic upscale-model list is empty, and the configured `upscale_models` and
`latent_upscale_models` buckets are empty. Therefore node registration alone
does not make a local AI restoration workflow executable. No model was
downloaded or installed.

The official Comfy-Org SeedVR2 model repository identifies its repackaged
weights as Apache-2.0 and documents a 3B INT8 video-upscale template requiring
both a diffusion checkpoint and a separate VAE; the referenced files are
approximately 3.46 GB and 478 MB, and the runtime does not have those files
installed. This is not promoted as a
ready local option without a separately approved, isolated resource/quality
evaluation. See the [official model card](https://huggingface.co/Comfy-Org/SeedVR2),
[official video workflow](https://github.com/Comfy-Org/workflow_templates/blob/main/templates/utility_seedvr2_3b_int8_upscale_video.json),
and [ComfyUI SeedVR2 documentation](https://docs.comfy.org/tutorials/utility/seedvr2).

The registered `WavespeedFlashVSRNode` is marked `api_node=true` and exposes a
partner 2K option with hidden API credential inputs. It is not evidence of
local processing and was not invoked; using it for owner architecture media
would require separate privacy, account, and cost approval.

### Safety and scope

- The supplemental regression run completed with 1102 tests, 15 skipped, and 0
  failures; the A9 UI copy tests also passed (16/16).
- No `/prompt`, GPU inference, external media API, model download, runtime
  restart, or production configuration change occurred.
- Production 8189 stayed at 0.33.1 with its queue idle; experimental 8190
  remained offline.
- A9 remains a separate Sequence/Assembly result, not a Job-list row. The
  existing five-shot assembly remains `READY`; the Studio Outputs page exposes
  it under “长片成果 · Sequence / Assembly”.
- The A9 app-managed Assembly and its dated owner-export copy were matched by
  exact byte length and SHA-256. The source Assembly completed on 2026-10-03;
  the owner-export manifest and copied MP4 were created on 2026-10-10. These
  are distinct source-completion and export-copy timestamps, not a mismatch in
  the generated media. The export is under the dated `Owner_Export` package;
  the app-managed Results location remains the Studio playback source.
- No progress value or acceptance classification was increased by this
  supplemental check.
