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

The encoder implementation is CPU `libx264` (`preset=fast`, `CRF=18`,
`yuv420p`) with AAC audio at 192 kb/s; it performs Lanczos scale plus centered
padding, with no restoration or detail-reconstruction stage. The Results page
sets the preview video to `max-height: 520px` and uses the same-origin media
URL, so a 1152-pixel-high 2K file is further downscaled in the on-page preview.
This is a display constraint, not a change to the downloaded file. The UI now
states that preview scaling and file resolution are distinct, and that larger
pixel dimensions do not imply increased detail.

The preview explanation was synchronized into the existing RC installation
after a rollback copy; the live Results page continues to show the source
resolution and the explicit Lanczos/non-AI label. No media was regenerated or
downloaded during this UI check.

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
- The live cross-Project Jobs table returned 24 records, including the expected
  A5–A8 acceptance Jobs. One older record remains `SUBMISSION_LOST` after
  `COMFY_COMMUNICATION_TIMEOUT`; its persisted snapshot has no `prompt_id`,
  final workflow SHA, or runtime identity. The UI correctly presents it as
  unconfirmed and does not automatically resubmit it. Its historical state was
  not changed, and no ambiguous Comfy output was attached.
- At the time of this audit, the running 8788 backend lacked the global
  `/api/jobs/search` route; the frontend's per-Project fallback still returned
  all 24 Jobs and exact-ID filtering worked. The deployment was subsequently
  aligned with the tracked source; see the dated follow-up below.
- During the initial read-only audit, no `/prompt`, GPU inference, external
  media API, model download, runtime restart, or production configuration
  change occurred.
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

### Live deployment follow-up — 2026-10-10

- The three scoped files (`mock_api/server.py`, `mock_api/job_api.py`, and
  `frontend/workspace.html`) were copied into the existing RC TEST installation
  after making a local rollback copy. No software, models, Job data, Golden
  workflows, or media were downloaded or replaced.
- The existing managed launcher restarted the Studio/production Comfy pair.
  Studio health passed, production Comfy remained 0.33.1 with an idle queue,
  and experimental 8190 remained offline. The deployed file fingerprints
  matched the source files.
- The live global Jobs endpoint now returns the exact requested Job, all 24
  records, and the retained `SUBMISSION_LOST` record. This corrects the earlier
  deployment-drift observation; the historical lost submission remains
  unmodified and is not retried or associated with media.
- A cross-project UI check showed why a historical ID appeared absent: opening
  Jobs from Test 4 preselects that project, so an A6 ID correctly returns no
  match in that scope; selecting “全部项目” shows the A6 Job. The page's prior
  hint overstated cross-project scope and its button label implied a global
  search despite the active project filter. The source now displays the active
  search scope and labels the action “按当前范围搜索”.
- The two Jobs UI files were backed up and synchronized to the same existing
  installation. After reload, the scope hint correctly names Test 4; switching
  to “全部项目” lists all 24 Jobs, and exact search finds the A6 Job. No Job,
  Result, or media record was changed by this check.
- The A9 Assembly media route still returns HTTP 206 for a byte-range request.
  No `/prompt` call or GPU execution occurred during this deployment check.
- Final regression after the Jobs scope clarification: 1102 tests passed, 15
  skipped, 0 failed. Focused Jobs/UX tests passed (27), JavaScript syntax and
  `git diff --check` passed.

### Owner export and active-instance reconciliation — 2026-10-10

- Rechecked the existing `Advanced_Acceptance/Owner_Export_20261010_01`
  package without changing its contents. All 11 manifest-listed artifacts
  exist under the package, and every file's length and SHA-256 match the
  manifest. The manifest's total (86,946,996 bytes) matches the sum of the
  files. Each artifact was also streamed from its Studio media endpoint
  directly into an in-memory SHA-256 calculation; all 11 returned HTTP 200
  with the same length and digest. No video was written to a temporary file.
- The package records source Job/Sequence completion times separately from
  the package's `export_created_at`. The source Jobs and Assembly completed
  between 2026-09-30 and 2026-10-03; this export package was created on
  2026-10-10. Persisted timestamps carry explicit offsets (`+08:00`) or
  explicit UTC `Z` markers. File modification dates are not used to rewrite or
  infer source completion dates.
- The current Study model is Project-scoped: `study_state.json` deliberately
  sets `study_id` equal to its owning `project_id`; Job records carry the
  Project ID and do not have a separate Study primary key. The export
  manifest repeats that identifier in its `study_id` field as a schema alias.
  This is a model limitation, not evidence of cross-Project data mixing.
- The running Studio and Comfy processes are the existing managed RC TEST
  installation and its production runtime. Studio health is `PASS`; production
  ComfyUI remains 0.33.1 on 8189 with an empty queue and no native AddGuide.
  Experimental 8190 is offline. The live runtime registry reports the A5 route
  as explicitly enabled, but the experimental runtime is unhealthy/unreachable
  and the fallback policy is `FORBIDDEN`; this does not make an A5 Job
  executable and must fail closed. Source and installed SHA-256 values match
  for the backend route/job files and the Jobs, Outputs, and Workspace UI
  files checked in this pass.
- The installed Studio data root contains four Project directories and 207
  files (about 1.43 GB). This is the existing indexed application data, not a
  newly downloaded runtime/model or a duplicate ComfyUI installation. No
  cleanup was performed. D: had about 125.70 GiB free after this audit.
- Final verification for this pass: full regression 1102 passed / 15 skipped /
  0 failed; A4–A9/runtime/Jobs/UX focused suite 181 passed; Golden workflow
  zero-diff tests 5 passed; Python compile, frontend JavaScript syntax,
  regression inventory (`ADDED 0 / REMOVED 0 / SKIP_CHANGED 0`), and
  `git diff --check` passed. No `/prompt`, GPU inference, model/software
  download, or historical Job/Result mutation occurred.
- Independent text-only Antigravity review completed successfully
  (`20261010062323-agy-063adbbe`, Gemini 3.8 Flash High). It agreed that the
  bounded classification is accurate and highlighted the already-recorded
  limits: A8 Lanczos is not AI restoration, A7 intent is not 6DoF camera
  control, A9 source-completion and export dates differ by design, and A10 is
  cross-stage evidence rather than one composite execution DAG. No code was
  changed by the reviewer.

## Full system reconciliation and product calibration — 2026-10-10

### Four owner-reported issues

1. **Jobs history visibility — resolved for the named Jobs.** Read-only live
   global Job search found exactly one record for each requested A5/A6/A7/A8
   identity, plus the A7 source/retake pair. The global index contains 24 Jobs
   across four Projects. The earlier apparent absence is a scope issue: Jobs
   opened from a Project starts with that Project selected; an A6 Job belongs
   to a different Project. Selecting “全部项目” makes it searchable. The
   retained legacy `SUBMISSION_LOST` entry remains visible but unconfirmed; it
   still lacks a prompt identity and was not rewritten or retried.
2. **Weak 2K detail — resolution is not enhancement.** The checked source is
   native 1344×768; the 2048×1152 derivative uses CPU Lanczos scaling/padding
   and H.264 `libx264` fast/CRF 18/yuv420p. It has no restoration or AI detail
   reconstruction. The Results preview is capped at 520 CSS pixels high, so it
   displays the 2K file downscaled. Sampled objective metrics do not show a
   consistent detail gain and are not a perceptual pass. Input-reference
   quality was not newly scored in this pass and is not ruled out as a
   contributing factor. Classification remains: 2K resolution PASS, tested
   encoding PASS, AI enhancement NOT PASSED, broad visual quality NOT TESTED.
   No model weights were installed or downloaded.
3. **Output-root/date difference — roles and event times differ.** The Owner
   Acceptance directory is an export destination, not the canonical Comfy or
   Studio Result root. The A9 source Assembly completed at
   `2026-10-03T15:46:43+08:00`; the manifest export was created on
   `2026-10-10T12:14:02+08:00`. Its A9 MP4 has 24,905,915 bytes and SHA-256
   `580ed50e211f57355ec2b34f842b90c250afeb0751f2907c48802ba21ff31e9b`,
   matching the Assembly index. The file modification time aligns with the
   export copy, not the original assembly event. No timestamp was rewritten.
4. **A9 long-form discoverability — the item is a Sequence/Assembly, not a
   Job row.** The live record is a READY five-shot queue with all five shots
   `RESULT_READY`, a persisted Sequence ID and Assembly ID, and a byte-range
   media endpoint. A live request returned `206 Partial Content` with the
   expected 24,905,915-byte total. In Studio, use **Outputs → Results · 已保存
   成果 → 长片 / Sequence / Assembly**; the card has separate Preview and
   Download actions. The copied owner deliverable is relative to the selected
   Owner Export root at
   `Advanced_Acceptance/Owner_Export_20261010_01/A9/`.

### Responsive and Environment interaction follow-up

- The three-viewport synthetic-only audit captured Home, Study, Jobs, Output,
  and Environment at 375×812, 768×1024, and 1280×800. It initially found a
  tablet-only Jobs filter overflow (document width 1012px at 768px). A scoped
  761–900px two-column rule fixes the toolbar; the regenerated manifest shows
  no horizontal overflow in all 15 captures. The regression assertion and
  captured images are outside the user-media/export directories.
- Environment group tabs, recheck, runtime-update status, plan refresh,
  desktop-setting feedback, restart feedback, model-path-repair feedback, and
  the advanced ComfyUI unavailable state were exercised with synthetic data.
  All system API requests were intercepted by Playwright; no request reached
  a real runtime. Install controls remained disabled in the all-ready fixture.
- The temporary loopback fixture was stopped; its 266,665-byte synthetic data
  directory was removed after path validation. The small screenshots/manifest
  were retained as audit evidence. No real Project, Job, Result, or media was
  changed.

### Acceptance state after reconciliation

| Dimension | Status | Evidence boundary |
|---|---|---|
| `ENGINEERING_IMPLEMENTATION` | `PASS` | Current source regressions and the tablet overflow fix pass. |
| `DATA_CONSISTENCY` | `PARTIAL` | Named records and A9 artifact match; one legacy lost submission remains unconfirmed. |
| `JOBS_VISIBILITY` | `PASS` | All named acceptance Jobs are found by exact global search; Project scoping is explicit. |
| `RESULTS_VISIBILITY` | `PASS` | Export manifest artifacts and Studio media endpoints match; no ambiguous media was attached. |
| `A9_LONG_FORM_VISIBILITY` | `PASS` | READY Assembly, UI section, download endpoint, SHA and Range 206 verified. |
| `OUTPUT_PATH_CONTRACT` | `PASS` | Owner Export is a separately indexed copy; it does not replace internal Result storage. |
| `DATE_TIME_CONSISTENCY` | `PASS` | Source completion and later export timestamps are separate, offset-bearing events. |
| `2K_RESOLUTION` | `PASS` | Existing file probes at 2048×1152. |
| `2K_QUALITY_ENHANCEMENT` | `BLOCKED` | Current file is Lanczos only; local AI weights are absent and no download was authorized. |
| `ADVANCED_PARAMETER_CORRECTNESS` | `PARTIAL` | Capabilities are bounded; camera intent is not deterministic 6DoF and AI 2K is unavailable. |
| `FULL_UI_INTERACTION` | `PARTIAL` | Responsive pages and Environment controls were exercised; the full multi-page action matrix is not complete. |
| `END_TO_END_USER_WORKFLOW` | `PARTIAL` | Existing evidence is reusable; no new single composed A5–A10 execution was run. |
| `ADVANCED_PRODUCT_QUALITY` | `PARTIAL` | Existing visual reviews are bounded; final Owner visual acceptance is not recorded. |
| `RELEASE_READINESS` | `BLOCKED` | AI enhancement and final Owner acceptance remain open; no Release or tag was created. |

Separate gates: `USER_WORKFLOW_ACCEPTANCE=PARTIAL`,
`DATA_CONSISTENCY_ACCEPTANCE=PARTIAL`,
`ADVANCED_QUALITY_ACCEPTANCE=BLOCKED`, `RELEASE_READINESS=BLOCKED`.
Therefore this work does **not** claim `READY_FOR_OWNER_FINAL_ACCEPTANCE` or
`OWNER_ACCEPTED`.

### Final checks and safety

- Current branch `feature/h3-advanced-workflows` is a descendant of the
  supplied `a123e468…` SHA; the current source baseline is later. Production
  Studio 8788 is healthy. Production ComfyUI remains 0.33.1/8189, queue 0/0,
  with no native AddGuide; experimental 8190 is offline.
- Full standard-library regression discovery: 1,102 tests, 15 skipped, 0
  failures. Focused UX: 16/16. Python compile, 10 frontend JavaScript syntax
  checks, 93 tracked JSON files, regression inventory, and `git diff --check`
  pass. Existing Python environments did not contain pytest; no test package
  was installed.
- No new Project/Job, `/prompt`, GPU execution, Comfy update, software/model
  download, model change, historical Job/Result mutation, or Release occurred.
  D: had 134,876,348,416 bytes free at the final read-only check.
- Targeted Antigravity review run `20261010091525-agy-d884b103` timed out after
  60 seconds and produced no review conclusion; it changed zero files. The
  earlier successful overall review is recorded above and is not presented as
  a review of this CSS patch.
