# A8 Delivery Capability Research

Research snapshot: 2026-10-03. This records the bounded A8 selection; repository
and model licenses can change and must be rechecked before redistribution.

## Decision

Use the existing managed FFmpeg build as an optional local CPU backend for the
first A8 delivery path. Do not vendor the binary, install a ComfyUI extension,
download AI weights, or change production ComfyUI. The current managed FFmpeg
7.1 build exposes `minterpolate`, `scale`, `pad`, and `libx264`.

- Frame interpolation: FFmpeg `minterpolate`, motion-compensated MCI with
  adaptive overlapped block compensation; encode an FFV1 intermediate so the
  next scale/encode stage does not add another lossy video generation.
- Scaling: Lanczos with aspect-ratio preservation and padding. The validated
  native 1344x768 canvas is 7:4, not 16:9; 1920x1080 and 2048x1152 outputs
  therefore use narrow side bars instead of distortion or cropping.
- Restoration: `NONE`. No AI-created detail is represented as verified native
  architecture detail.
- Audio: source audio is explicitly mapped into the final MP4 and encoded as
  AAC; final duration/audio presence are checked against the native source.
- Execution: CPU only, two FFmpeg threads, bounded process timeout, per-file
  and per-Job derivative storage limits, low-disk reserve, Job-specific output
  identities, staged manifests, and atomic publication.

FFmpeg documents `minterpolate` as a motion-interpolation filter with duplicate,
blend, and motion-compensated modes and exposes adaptive block-compensation
options. This is a configurable classical VFI method, not proof that all
architectural footage will remain geometrically faithful. See the
[FFmpeg filter reference](https://ffmpeg.org/ffmpeg-filters.html).

## Candidate survey

The following commits were inspected in isolated, shallow, no-checkout research
clones. No source was installed into production and no model weights were
downloaded. A repository code license does not automatically license its
weights or all bundled dependencies.

| Candidate | Inspected revision / license | Runtime, model and security notes | A8 disposition |
|---|---|---|---|
| [ComfyUI-Frame-Interpolation](https://github.com/Fannovel16/ComfyUI-Frame-Interpolation) | `26545cc2dd95bc3d27f056016300673bdeee78f5`; MIT | ComfyUI custom-node assumptions; multiple RIFE/FILM/AMT-family paths; PyTorch, OpenCV and other Python dependencies; optional weight downloads; installer scripts can invoke package managers and fetch checkpoints. | Research reference only; do not install in the frozen production runtime. |
| [FlashVSR](https://github.com/OpenImagingLab/FlashVSR) | `cf910c61a60733e610e9c6e8b607f80c3a6c202b`; Apache-2.0 code; [model card](https://huggingface.co/JunhaoZhuang/FlashVSR) separately declares Apache-2.0 | Large restoration model and specialized sparse-attention/CUDA assumptions; upstream reports testing on datacenter GPUs. Model artifacts are multi-gigabyte; the local 12-GB GPU and privacy/disk constraints make it a poor default. | Not downloaded or installed; revisit only after a separately approved hardware/model evaluation. |
| [SeedVR](https://github.com/ByteDance-Seed/SeedVR) | `e4de8c24441a67e1b7df56abea10645059bb1185`; Apache-2.0 source | Diffusion-transformer restoration with a heavyweight CUDA/Linux stack; model and VRAM requirements are substantially above the current local budget. | Not suitable for this local A8 path; no weights acquired. |
| [SeedVR2](https://github.com/IceClear/SeedVR2) | `dc248c05946b64114012ac9a0da8faf982159627`; Apache-2.0 source | Official guidance describes high-memory multi-GPU configurations for HD/2K use and warns that restoration can invent or over-sharpen detail on clean generated footage. | Keep unavailable for the current workstation profile; no weights acquired. |
| [Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN) | `a4abfb2979a7bbff3f69f58f58ae324608821e27`; BSD-3-Clause source | Separate pretrained weights and portable builds have their own provenance/distribution considerations. Per-frame restoration can alter fine facade joints, rails, mullions and thin structures unless temporally checked. | Idea only; no model used and no weights redistributed. |
| [ComfyUI-VideoHelperSuite](https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite) | `4d907bee61e92c2e65af3bd6383a4e4d356126d1`; GPL-3.0 | Useful video graph UX reference; custom-node and FFmpeg dependency surface; incorporating its code would introduce a different copyleft review. | UX/architecture reference only; no source copied. |

RIFE's upstream ncnn/Vulkan implementation advertises portable GPU/CPU execution
and frame-directory workflows, but that does not by itself establish artifact
license compatibility, architecture-line quality, or acceptable performance on
this machine. It remains a future candidate rather than an A8 dependency; see
the [RIFE ncnn/Vulkan project](https://github.com/nihui/rife-ncnn-vulkan).

## Validation and known limits

The existing A7 native file used for local validation is 1344x768, 24 fps,
4.46 s, 107 decoded frames, H.264 with AAC audio. A8 validation creates only
post-processing derivatives and does not submit to `/prompt` or invoke H3.

`minterpolate` may ghost or warp fast edges, thin columns, railings, tree limbs,
and moving water; 24→60 also uses a non-integer 2.5x temporal ratio. A generated
frame-rate label alone is not a quality pass. Each 48/60 result requires media
probe, frame-count/duration check, playback/seek check, and architectural visual
review. If 60 fps is not clean enough, keep it explicitly bounded/unavailable
rather than promoting it. AI super-resolution/restoration remains unavailable
until weights, license, VRAM, storage, and architecture-fidelity evidence pass
separate gates.

No candidate model, generated output, owner prompt, reference pixels, absolute
owner path, credential, or local runtime configuration is included here.
