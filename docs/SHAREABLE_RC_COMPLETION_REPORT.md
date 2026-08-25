# Architect Video Studio — Shareable RC Completion Report

## INSTALLER

Built a Windows self-extracting installer:

- `ArchitectVideoStudio-Setup.exe`
- native WinForms self-extracting `Setup.exe` with embedded `Setup.ps1` and `payload.zip`
- PowerShell is hidden and its scan/download log is shown inside the installer
- the install location uses a standard Windows folder picker on a dedicated
  STA thread, with a separate typed-path fallback; the main window stays
  responsive even if shell enumeration encounters a slow or offline drive
- startup detects stale development ComfyUI/Studio processes on ports 8189/8788,
  restarts only recognizable owned service shapes, and reports unknown port
  owners instead of hanging or killing unrelated applications
- resumable HTTPS runtime download
- SHA-256 verification for the pinned ComfyUI archive
- GUI path chooser with editable installation path; avoids blocking shell enumeration on offline/network drives
- the installer remembers the last selected root in the per-user `%LOCALAPPDATA%\ArchitectVideoStudio\last-install-root.txt` preference and reopens there on the next run
- updates safely close only the existing `ArchitectVideoStudioDesktop.exe` whose executable path is inside the selected install root, release the file lock, copy the new payload, and start the updated shell again; unrelated processes are not touched
- safe adoption of an existing compatible ComfyUI Runtime found beside the selected install folder
- known-location discovery and adoption of an existing shared ComfyUI model root
- persistent `models_env.path` handoff so the launcher keeps using adopted models
- existing H3/VHS nodes and archive extractor are reused when found; only missing components are acquired
- model discovery reads the release model manifest (not the legacy development baseline), preventing the post-folder-selection PowerShell crash
- Environment Center auto-adopts the same known-location Runtime/Models pair on first launch and exposes the direct Studio generation workflow
- the normal entry now starts a native WinForms desktop control center with a taskbar notification-area status icon; the browser Studio, setup page, and Native ComfyUI remain explicit backup/advanced actions
- Studio, Environment Center, and Native ComfyUI are hosted in one native WinForms window through an in-process WebView2 control; no Edge/Chrome child window is reparented or shown as the primary UI, and the system browser is only an explicit fallback
- the Architect Video Studio monogram is bundled as a high-resolution PNG and multi-size Windows ICO and is used by the installer, desktop window, and notification-area icon
- cross-drive fallback discovery is bounded and signature-based; no developer drive, username, or fixed installation path is embedded
- application-managed default install root: `%LOCALAPPDATA%\ArchitectVideoStudio`
- no system Python, Git, or manually installed ComfyUI required

The installer copies the application, starts Environment Center, and leaves model download behind an explicit user confirmation and license acknowledgement.

## ENVIRONMENT AUTO-DETECTION

Environment Center reports Windows/system memory, NVIDIA/CUDA availability, VRAM class, disk capacity, Free Commit, runtime state, PREAD, H3 support, models, prompt skill, and all five workflows. It classifies lower-than-24-GB GPUs as experimental rather than silently promising support. The bootstrap scans the selected install location, adjacent `ComfyUI` runtime folders, known shared-model locations, and relevant environment variables; it adopts the best existing match instead of downloading a duplicate. The idempotent installer plan then checks each required model and downloads only missing or invalid files.

The single **Install / Repair Everything** action is idempotent and supports existing compatible runtime/model adoption, resumable downloads, checksum failure recovery, and safe install promotion.

## COMFYUI AUTO-INSTALL

The release pins the official ComfyUI Windows NVIDIA portable archive:

- version: `0.33.1`
- embedded Python: `3.13`
- asset: `ComfyUI_windows_portable_nvidia.7z`
- SHA-256: `4a221588979b96b8244e0e50b2edca03af732acae1deba69d60aa3b4d60b9dba`
- source: [ComfyUI official releases](https://github.com/comfy-org/comfyui)

The project PREAD safe-load shim is installed through the support-layer path; the installer does not hand-edit a developer Runtime.

## MINIMAX-H3 NODE AUTO-INSTALL

The managed support plan pins `HM-RunningHub/ComfyUI_RH_MinMaxH3` at commit `d6c5f7b0d4e03936ac4a9834be63ecc6b5637dad`, with VHS provenance pinned separately. Capability checks cover T2VA, FL2VA, and Ref2VA, including FL2VA first-frame semantics. The upstream implementation documents a 24-GB-class single-GPU target and does not bundle model weights. See the [upstream H3 implementation](https://github.com/HM-RunningHub/ComfyUI_RH_MinMaxH3).

## MODEL AUTO-DOWNLOAD

Model weights are not bundled in Git or the release package. Environment Center downloads only missing required assets, resumes interrupted transfers, verifies size/hash, and reuses an explicitly selected shared Models Root where compatible.

## MODEL MANIFEST

The manifest pins MiniMax H3 revision `42ed227ee7df40d41602854ae760620d6eb651fe` and records source, target path, expected size, SHA-256, required status, and T2VA/FL2VA/Ref2VA association for:

- INT8 ConvRot DiT — 20,970,379,616 bytes
- Qwen3-VL 32B NVFP4/AWQ text encoder — 15,687,142,551 bytes
- FP16 video VAE — 5,207,808,496 bytes
- FP32 audio VAE — 605,254,808 bytes

The current manifest uses immutable Hugging Face revision URLs. Licensing remains governed by the upstream [MiniMax H3 license](https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/LICENSE); users acknowledge applicable territory, use, downstream-notice, and commercial obligations before downloading.

## ACCELERATION

Acceleration remains capability-driven. Standard generation is the safe default; velocity-cache, Cache-DiT, SDPA/xFormers, or SageAttention are not made mandatory without a compatible pinned stack. An acceleration failure must fall back to the standard path.

## OFFICIAL PROMPT SKILL

The production chain remains:

`OfficialSkillAdapter → H3PromptBridge → selected workflow → ComfyUI /prompt`

The reference skill copy and hashes are pinned in the support manifest. Reference approval remains mandatory before prompt/generation submission. The adapter records skill, bridge, profile, intent, workflow, and prompt provenance.

## FIVE WORKFLOWS

The product registry preserves the five frozen cards:

1. `01_Exterior_Hero`
2. `02_Day_Night_Transition`
3. `03_Material_Detail`
4. `04_Drone_Aerial`
5. `05_Slow_Walkthrough`

Workflow JSON, node requirements, image binding, prompt binding, parameter mapping, and output collection remain registry-driven.

## MODEL CARDS / PARAMETERS

Existing model-card contracts and user-facing parameters are preserved. The release does not expose Comfy node graphs as the normal user interface and does not add GPU tuning sliders.

## WEBUI

Architect Video Studio remains the user-facing application. It provides project creation, reference upload and approval, five workflow cards, parameters, generation state, friendly errors, output preview, and output-folder access. Raw ComfyUI remains an advanced/diagnostic surface.

## CLEAN INSTALL TEST

Validation completed without model loading or inference:

- focused installer/launcher/runtime suite: `141/141 PASS`
- canonical regression: `736 run, 698 PASS, 38 expected skips, 0 FAIL`
- inventory guard: `ADDED 0`, `REMOVED 0`, `SKIP_CHANGED 0`
- PowerShell installer parser: `PASS`
- lightweight host probe: RTX 5070, driver `591.86`, managed torch `2.13.0+cu130`, CUDA `13.0`, `torch.cuda.is_available()=true`; policy is `EXPERIMENTAL` for 12-GB-class hardware, while CUDA readiness is `READY`
- packaged desktop EXE smoke: WebView2 x64 loader, backend health, CoreWebView2 creation, Home navigation, DOM `readyState="complete"`, and taskbar-shell second-launch mutex all `PASS`; startup markers APP-01 through APP-09 are written to the local shell log
- release package audit: `241 ZIP entries` / `238 manifest payload files`, exactly five production workflows, formal Studio entry present, native WebView2 desktop shell and icon assets present, environment probe and existing-environment discovery source present, no model weights, screenshot scripts, private userdata, or developer-path hits

The clean-install tests use isolated synthetic fixtures and verify runtime adoption, resumable download behavior, checksum rejection, path safety, workflow registration, and setup-to-ready transitions. A physical clean Windows installation has not been executed in this turn because it would perform the authorized external runtime download and installation; the artifact and fixture acceptance harness are ready for owner execution.

## HARDWARE SUPPORT

- Supported baseline: NVIDIA CUDA GPU with 24 GB or more VRAM
- Recommended: 24-GB-class or larger NVIDIA GPU, 64 GB system RAM or more, and ample SSD space
- 12–23 GB: experimental, not guaranteed
- RTX 5070 12 GB is classified as experimental; CUDA hardware/runtime detection is reported independently from the product support policy. End-to-end generation remains owner validation work.

This policy follows the upstream H3 deployment target rather than delaying the product indefinitely for an unproven 12-GB path.

## GPU PRODUCT ACCEPTANCE

Not executed in this release-completion pass. No GPU authorization was consumed. One owner-authorized final product acceptance remains: clean application launch, real approved reference, `01_Exterior_Hero`, official prompt chain, real `/prompt`, ComfyUI execution, MP4 creation, ffprobe validation, and Studio preview.

## RELEASE PACKAGE

Generated artifacts:

- [ArchitectVideoStudio-Setup.exe](../release/dist/ArchitectVideoStudio-Setup.exe)
- [ArchitectVideoStudio-RC.zip](../release/dist/ArchitectVideoStudio-RC.zip)
- [SHAREABLE_RC_MANIFEST.json](../release/dist/SHAREABLE_RC_MANIFEST.json)

Final artifact SHA-256:

- Setup.exe: `9247B29F72AE7ABE7613F931D839BA5924E12FCBAAB79A2D88272FC9434977ED`
- RC.zip: `041585CE0095814D55F9ECC528B3933AF113712E37E6D50BD72DDC7877409801`

The package contains application source/configuration and installer logic, not model weights, client images, generated media, private logs, or user data.

## GITHUB STATUS

No push, tag, release, force-push, or history rewrite was performed. The existing worktree remains preserved for owner review. Public release still requires owner approval of licensing and publication metadata.

## FINAL CLASSIFICATION

`READY_FOR_OWNER_MANUAL_RC_TEST`

All non-GPU release work is complete and the downloadable package is built. The next action is owner manual RC testing; GPU product acceptance and public release remain explicitly pending owner authorization.
