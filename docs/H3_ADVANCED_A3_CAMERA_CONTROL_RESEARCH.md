# MiniMax H3 Advanced A3 — Camera / Motion Control Research

## Status

`A3_RESEARCH_COMPLETE`

**Classification: `PATH B — MODEL/UPSTREAM CAPABILITY EXISTS, BUT THE CURRENT INSTALLED RUNTIME LACKS THE WRAPPER AND WEIGHTS`**

This A3 pass answers the capability question before any new workflow or GPU
run. It does not modify, replace, or promote Golden V1, A1, or A2 assets.

Research date: 2026-09-22

## Scope and safety boundary

- Inspect the live ComfyUI `/object_info` contract and the installed H3 source.
- Inspect only the already installed and locked support layers.
- Compare the result with current upstream ComfyUI documentation, templates,
  and mature H3/Wan community implementations.
- Do not install nodes, download model weights, submit a GPU job, or open user
  media, job history, credentials, or owner data.
- Do not treat a post-process crop, zoom, pan, warp, or reframe as
  generation-level camera control.

Golden V1, A1, and A2 remain frozen. No A3 workflow was created because the
current installation cannot execute the real control surface identified by the
research.

## Evidence from the current installation

### Runtime and locked support layers

The live local ComfyUI instance reports version `0.33.1`. The installed H3
support layer is locked to:

| Layer | Upstream commit | License | A3 relevance |
|---|---|---|---|
| `comfyui-rh-minimax-h3` | `d6c5f7b0d4e03936ac4a9834be63ecc6b5637dad` | Apache-2.0 | H3 custom nodes and all-in-one wrappers |
| `comfyui-videohelpersuite` | `4ee72c065db22c9d96c2427954dc69e7b908444b` | GPL-3.0-only | Video loading/combining utilities, not generation control |

The local custom-node inventory is limited to the AVS H3 bridge, the locked H3
layer, VideoHelperSuite, and the safe-load layer. The live server returned no
`MiniMaxH3FunControlNetApply` node. The installed core H3 source registers only
the H3 latent allocator, image-to-video, reference-to-video, and sigma-shift
surfaces.

The local `models/model_patches` directory does not contain the H3 Fun
ControlNet checkpoint. Therefore the current installation is missing both the
upstream wrapper and the model patch required to exercise it.

### H3 node contract inventory

| Installed surface | Real inputs | Classification | Why it is not camera control |
|---|---|---|---|
| `MiniMaxH3ImageToVideo` | `clip`, `vae`, `prompt`, `width`, `height`, `length`; optional `first_frame`, `last_frame` | `PROMPT_ONLY_CONTROL` | No camera pose, trajectory, depth, optical-flow, or motion-field input |
| `RHMiniMaxH3VideoGen` | prompt, references/frames, seed, sigma points, video/audio shifts, sampler, acceleration, dimensions | `PROMPT_ONLY_CONTROL` | The media inputs are generation references or V2A source video, not a camera path |
| `RHMiniMaxH3RefGen` | image/video/audio references plus prompt and sampler controls | `PROMPT_ONLY_CONTROL` | Reference identity/content conditioning is not a geometric camera constraint |
| `RHMiniMaxH3FL2VA*` | first/last frame, keyframe target, prompt | `PROMPT_ONLY_CONTROL` | Keyframes constrain endpoint content, not frame-by-frame camera motion |
| `RHMiniMaxH3Ref2VA*` | ordered image/video/audio references and target | `PROMPT_ONLY_CONTROL` | A reference video may describe motion, but there is no camera-pose contract |
| `RHMiniMaxH3EncodeVideoAVLatent` | existing frames, VAE, latent, seed | `PROMPT_ONLY_CONTROL` | V2A uses existing video as a clean visual condition; it does not steer new camera generation |
| `RHMiniMaxH3DualSigmaSampler` | seed, sigma points, `video_shift`, `audio_shift`, acceleration, denoise | `MODEL_CAPABILITY` (sampling) | Flow shifts and denoise change schedule/conditioning behavior, not camera geometry |
| `RHMiniMaxH3FrameRate` | frame rate, temporal RoPE and related profiles | `MODEL_CAPABILITY` (temporal) | Temporal frequency/rate controls are not a camera trajectory |
| `VHS_*` | load, slice, batch, combine and encode video | `POST_PROCESSING` | Utility/output nodes cannot inject a generation-level camera signal |

The source documentation is explicit that `video_shift` and `audio_shift` are
flow-shift scheduler controls. Guidance to raise `video_shift` for unstable
large motion is a sampling recommendation, not an exposed camera controller.

## Upstream capability found

Current upstream ComfyUI has a real H3 control path named
`MiniMaxH3FunControlNetApply`. Its contract patches the H3 model with a
compatible `MODEL_PATCH` and VAE, then accepts an optional `control_video` and
optional `mask`/`source_video`. This is execution-level conditioning, not a
prompt-only hint.

The official H3 Fun ControlNet Union template documents a single control branch
for Canny, Depth, HED, MLSD, Pose, and video inpainting. The template loads
`minimax_h3_fun_controlnet_union_pruned_int8_convrot.safetensors` and is wired
for H3 `fl2va`/`ref2va` generation. A depth or pose control sequence can carry
camera-related structure, but this is still a control-video surface rather than
an explicit six-degree-of-freedom camera-pose API.

This upstream path is not available in the installed `0.33.1` runtime. The
official documentation and source currently describe the newer core path; the
local live contract is the authority for what can actually be run today.

## Model capability vs wrapper vs prompt-only control

| Layer | Finding | Decision |
|---|---|---|
| Model capability | H3 supports a Fun ControlNet model patch in current upstream ComfyUI, with compatible H3 control weights | Capability exists upstream |
| Installed wrapper | Local `0.33.1` has no `MiniMaxH3FunControlNetApply` and no equivalent locked H3 control node | Wrapper missing locally |
| Installed weights | No H3 Fun ControlNet file is present in the local model-patch inventory | Weights missing locally |
| Current H3 workflow | Prompt, references, first/last frames, scheduler and temporal controls only | Prompt/reference conditioning only |

This rules out Path A for the current installation. It also rules out a safe
GPU test: adding a fake camera slider or changing `video_shift` would not test
the capability under investigation.

## External candidates reviewed (not installed)

| Project | Control surface | License / maintenance signal | H3 compatibility and risk | A3 decision |
|---|---|---|---|---|
| [ComfyUI core H3 Fun ControlNet](https://github.com/Comfy-Org/ComfyUI/blob/master/comfy_extras/nodes_minimax_h3.py) + [official template](https://github.com/Comfy-Org/workflow_templates/blob/main/templates/video_minimax_h3_fun_controlnet_union.json) | Model patch with control video or mask; Canny/Depth/HED/MLSD/Pose union | Official ComfyUI source/template; current upstream path | Directly H3-compatible, but requires a newer core runtime and the model patch | **Best future path; not executable in current install** |
| [ComfyUI-H3-FunControl](https://github.com/wyzborrero/ComfyUI-H3-FunControl) | H3 ControlNet over depth/Canny/pose/HED/MLSD video | Apache-2.0; small community project, 15 commits and one open PR at review time | Direct H3 path, but limited validation; README says core `0.35` now has a native path and warns about curve-form checkpoint pairing | Reference only; do not install over frozen runtime |
| [3d-Camera-control-H3-Minimax](https://github.com/NyckM/3d-Camera-control-H3-Minimax) | MoGe geometry → virtual-camera depth warp → Meridian/H3 guide | Apache-2.0 repository; explicitly non-official and multi-component | Real camera-derived guide, but adds unpinned components and separate Meridian/weight licensing; not present locally | Experimental research lead, not production-safe A3 |
| [ComfyUI-WanCameraAdvanced](https://github.com/thepororo/ComfyUI-WanCameraAdvanced) | Explicit 6DoF camera embedding and path chaining | GPL-3.0 | The target input is `WanCameraImageToVideo`; it is not an H3 adapter | Reject for H3 |
| [ComfyUI-MiniMaxDirector](https://github.com/imbutus/ComfyUI-MiniMaxDirector) | Timeline and structured H3 prompt compiler | MIT; prompt compiler with workflow example | Improves prompt authoring but does not inject geometric camera conditioning | Prompt-only; not A3 camera control |
| [ComfyUI-AnimateDiff-Evolved](https://github.com/Kosinkadink/ComfyUI-AnimateDiff-Evolved) | AnimateDiff motion modules and CameraCtrl for SD1.5/AnimateDiff | Apache-2.0; mature project | CameraCtrl is trained for AnimateDiff/SD1.5, not MiniMax H3 | Reject for H3 |

No external project was installed, copied, or added to the production support
manifest. The official core route is preferable to the community wrapper once
the runtime upgrade and weight provenance are handled in a separate,
explicitly authorized packaging task.

## Classification

### `PATH B — REAL UPSTREAM CAPABILITY, CURRENT WRAPPER/WEIGHTS MISSING`

The current installation is not Path A because no real H3 camera/control-video
node is loaded. It is not Path C because the official upstream path is the
preferred compatible implementation and the local runtime is not yet at the
required version; the community alternatives are either limited experiments or
model-family mismatches. It is not Path D because an official H3 execution
surface and compatible model patch now exist upstream.

The precise current limitation is:

> **H3 camera/motion control is unavailable in the installed production runtime;
> prompt conditioning is the only executable path today.**

The next implementation step must be an isolated runtime/packaging change that
does all of the following before any owner GPU acceptance:

1. Validate a compatible ComfyUI core version containing
   `MiniMaxH3FunControlNetApply`.
2. Acquire the exact model-patch artifact through an approved, pinned,
   checksum-verified source; do not use an unpinned “latest” download.
3. Validate H3 base / patch dtype and architecture compatibility in a disposable
   or isolated runtime.
4. Build an isolated A3 control-video workflow without touching Golden V1,
   A1, or A2.
5. Run the one authorized GPU acceptance only after static contract, provenance,
   privacy, and startup checks pass.

## GPU decision

**No A3 GPU run was performed.** A GPU run against the current runtime would be
prompt-only and could not answer the A3 question. Installing or downloading a
control patch would also change the packaged runtime and exceed this research
pass. Therefore there is no honest A3 visual score, no A3 video artifact, and
no promotion decision.

## Timeout ownership note

The A2 1800-second observation issue remains classified as
`NON-PRODUCT-BLOCKING` for the A3 capability decision: the original server-side
generation completed and was recovered without resubmission, while the local
client observation window expired. This is a separate acceptance/observability
reliability item and is not used as evidence for or against camera control.

## Freeze and privacy gates

- Golden V1, A1, and A2 workflows/evidence were not modified.
- No GPU output, user media, job database, credentials, or private runtime logs
  were copied into this repository.
- No external node or model was installed.
- No production selector, release, tag, or merge was changed by this research
  pass.
- The only intended repository change is this sanitized research document.

## A3 progress

| Gate | State |
|---|---|
| A — brief/acceptance contract | Complete from A3 handoff |
| B — installed runtime/node contract | Complete |
| C — external/official capability research | Complete |
| D — classification | Complete: Path B |
| E — isolated workflow prototype | Not started; blocked by missing runtime/weights |
| F — GPU/owner acceptance | Not applicable yet |
| G — report and evidence | Complete after this document is committed |

Progress remains **22% / 88.00%** for the current A3 research checkpoint. This
is not a completion or promotion claim; the real A3 execution gate remains
pending a separately authorized runtime capability upgrade.
