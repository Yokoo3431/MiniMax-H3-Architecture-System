# H3 Advanced Workflow Roadmap

> **Current governing architecture:** the user-supplied `H3_ADVANCED_DEVELOPMENT_MASTER_PLAN.md` (A4+ / 2026-09-23), SHA-256 `DA9514B1930DCF936E1B2D0F4A9D892903D2F047940287FBD4EA94B220D68651`, together with the A4.1 integration brief, SHA-256 `1EF667659286F0AC5F956396CDD2E0C32B5D4B36817913387A20A666F3B1CCE8`. The A1 material below is historical context; where its capability statuses differ from the current anchor, this dated architecture section governs. The source files remain with the user; this tracked file stores the sanitized architecture anchor and next-stage contract, not a verbatim copy of private workspace data.

## Product-layer rule

Advanced workflows are versioned additions. `GOLDEN_V1_PRODUCTION_BASELINE`
remains immutable and available as the production fallback. Advanced work must
reuse the existing Studio Job truth, native Comfy handoff, support-layer
provenance, and managed output contracts. It must not create a second engine or
second project/job state model.

## Capability families

| Family | NOW | NEXT | LATER | EXPERIMENTAL |
|---|---|---|---|---|
| Architecture fidelity | Baseline rubric, façade/edge/material constraints in V2 prompt profile | Controlled geometry-preservation experiments and objective frame review | Structural consistency across longer clips | New conditioning or specialized nodes only after provenance review |
| Camera control | Semantic slow push/orbit language where H3 accepts prompt conditioning | Compare camera-language presets with fixed graph parameters | Native path controls if a verified H3 input contract appears | External camera-control nodes pending compatibility proof |
| Reference preservation | First-frame identity and subject-lock constraints | Multi-seed adherence comparison | Multi-reference hierarchy | New reference-conditioning nodes |
| Quality profiles | Standard inherited Golden profile | Preview vs standard parameter study | High-quality / high-resolution production profiles | Hardware-specific experimental profiles |
| Multi-reference / direction | Document capability gap | Define reference priority contract | Separate material/style references | New multi-reference conditioning |
| Long-motion continuity | Short-clip rubric | Segment/stitch evaluation design | Longer duration and temporal stability | New temporal modules |
| Prompt / workflow coordination | Advanced semantic profile | Workflow-aware camera presets | Architecture-specific grammar and negative constraints | Automatic workflow synthesis |

## Current A1 prototype

`06_Advanced_Architecture_Camera_V2` is the first isolated prototype. It keeps
the 04 Golden model, sampler, scheduler, VAE pair, resolution, frame rate,
steps, seed, and graph topology unchanged. Its only execution-affecting
experiment is a stronger architecture-camera conditioning profile: controlled
slow movement, subject lock, façade/material preservation, stable horizon, and
explicit no-morph/no-addition constraints. Output identity is changed only so
results cannot be confused with Golden output.

The installed node inventory includes the proven H3, Comfy core, and
VideoHelperSuite surfaces. Although the runtime exposes other camera-related
nodes, none is currently an input of `MiniMaxH3ImageToVideo`; they are not
connected as placebo controls. New external custom-node repositories are an
optional future candidate, not an A1 dependency.

## Gates before promotion

1. Static API/UI parity, link integrity, both VAE paths, node availability, and
   deterministic SHA.
2. Owner-authorized single B-arm GPU run, reusing an existing comparable Golden
   output where possible.
3. Objective metadata and visual A/B rubric: geometry preservation, reference
   fidelity, camera smoothness, material stability, temporal stability,
   architectural hallucination, and overall quality, each scored 1–5.
4. Explicit decision: `V2_PROMISING`, `V2_NEEDS_ITERATION`, or `V2_REJECTED`.

No A1 prototype is promoted to the production selector automatically.

---

## Governing Advanced Architecture Anchor — 2026-09-23

### Durable baseline and progress rules

- Repository: `Yokoo3431/MiniMax-H3-Architecture-System`.
- Branch baseline: `feature/h3-advanced-workflows` at `1bf5b28edfc9d86eb5e154b7019a502033b0ee69`.
- Baseline roadmap: total **88.00%**, Advanced Product Layer G **22%**.
- Module weights A–F are fixed. Only G may advance; progress must follow passed evidence gates, not the amount of local code.
- Local implementation is not remote-durable progress. A remote progress claim requires commit and push; never commit, push, merge, or tag without explicit authorization.

### Non-negotiable architecture invariants

1. Keep the existing Studio Project → Study → Prompt → Job → Output model as the sole product state model. Advanced features extend its contracts; they do not introduce a competing engine or job lifecycle.
2. Keep `GOLDEN_V1_PRODUCTION_BASELINE` immutable. Bind values into registered templates; do not edit Golden templates to simulate a capability.
3. Separate **native H3 generation**, **H3 conditioning**, **delivery/post-processing**, and **experimental** capability. A delivery result must never be advertised as native H3 output.
4. Native H3 generation is 24 FPS. Camera pose/6DoF is not a stable production API. Prompt direction, reference motion, timeline guidance, control-video guidance, and explicit camera pose are distinct concepts.
5. A UI option is exposed as available only when it reaches the final execution workflow and has provenance. Unsupported options remain disabled or unavailable with a reason; never silently fall back.
6. New model weights, custom nodes, ComfyUI upgrades, ControlNet, interpolation, upscaling, and experimental runtimes require their own isolated provenance/license/compatibility gate. Research does not authorize installation.
7. Keep owner prompts, reference media, generated media, project databases, credentials, tokens, private paths, and runtime logs out of tracked artifacts and external-agent context.
8. Preserve A–F progress at the supplied values. G advances only after the relevant static, end-to-end, visual, resource, and durability gates pass.

### Advanced capability map and stage order

| Stage | Scope | Gate / target from the master plan |
|---|---|---|
| **A4.1** | Capability-aware quality tiers; native-vs-delivery properties; Day/Night dual-reference foundation; future-compatible roles/guides; trace and research registers | Static + end-to-end pass: G 27%, total 88.50%; otherwise remain G 22%, total 88.00% |
| **A4.2** | Controlled Standard vs Native High GPU evidence; optional upscale study | Owner-authorized evidence: G 30%, total 88.80% |
| **A5** | Official Add Guide timeline/keyframe layer, only if stable runtime exposes it | Static plus one GPU evidence run: G 38%, total 89.60% |
| **A6** | Generalized Ref2VA image/video/audio reference library and roles | G 48%, total 90.60% |
| **A7** | Director/shot timeline, prompt compiler, guide binding, retake semantics | G 60%, total 91.80% |
| **A8** | Delivery interpolation, 1080p/2K upscale/restoration, provenance | G 72%, total 93.00% |
| **A9** | Long-form sequence, continuity handoff, batch and assembly/export | G 85%, total 94.30% |
| **A10** | Advanced acceptance, hardware profiles, recovery, UX and release candidate | G 100%, total 95.80%; A–F remain unchanged |

The project total is not 100% when G reaches 100%; remaining C/D/E/F gaps must also close.

## Next-stage prompt contract — ADVANCED-A4.1

Use this section as the implementation prompt for the next authorized A4.1 task. It is deliberately narrower than the full A4–A10 roadmap. Do not begin A4.2 or later-stage installation work as part of A4.1.

### Objective

Replace the three-tier-only A4 model with truthful capability profiles and close the existing `02_Day_Night_Transition` FL2VA dual-reference gap end-to-end. Build the foundation for later multiframe, Director, and delivery stages without executing those later capabilities.

### Freeze and starting evidence

- Start from the supplied branch/baseline; first inspect `git status`, preserve all user changes, and verify Golden V1 zero-diff.
- The previous A4 implementation provides three profiles and static trace coverage, but **A4 is not complete**: Day/Night requires two independent approved frames while the current Studio path supplies one `current_reference_asset_id`.
- Do not duplicate the same asset, weaken FL2VA, migrate production runtime, or increase G based only on local code.
- Keep production ComfyUI 0.33.1 / port 8189, A1/A2, A3 research and isolated A3 runtime frozen.

### Capability-aware quality contract

Represent exactly these seven capability IDs and expose availability truthfully:

| ID | Initial contract | Availability rule |
|---|---|---|
| `DRAFT` | 672×384 class, 24 native FPS | Experimental until validated; must not execute by accidental Golden fallback |
| `PREVIEW` | 832×480, 24 native FPS | Ready profile, with actual supported execution binding documented |
| `BALANCED` | 1024×576, 24 native FPS | Ready only after GPU cost check |
| `STANDARD` | 1280×720, 24 native FPS | Product preset to validate; do not confuse with prior 1024×576 A4 Standard |
| `NATIVE_HIGH` | 1344×768, 24 native FPS | Highest current local H3 base-generation ceiling; preserve exact evidence/status |
| `ULTRA_1080` | 1920×1080 delivery | Post-process required; no direct base-graph 1080p claim |
| `ULTRA_2K` | Aspect-aware 2K delivery target | Must resolve explicitly to `H3_REGENERATE_2K` or `POST_UPSCALE_2K`; never bind 2K dimensions silently into the current Golden graph |

The profile catalog must carry availability and a truthful reason. Reject execution of unavailable profiles; no silent fallback. Keep quality selection separate from workflow identity, reference identity, prompt intent, and seed.

### Native and delivery FPS/provenance

- `native_generation_fps` remains **24** and cannot be selected as 30/48/60.
- Model `delivery_fps` separately: 24 Native is Ready; 30 Delivery, 48 Smooth, and 60 Smooth are `FUTURE_POSTPROCESS` until a real pipeline is implemented and validated.
- No frame-interpolation plugin installation in A4.1. RIFE/VFI may be a later research candidate only.
- Per Job/result distinguish requested quality, resolved execution profile and mode; native width/height/FPS; delivery width/height/FPS; upscale method; interpolation method; and whether post-processing actually ran. Unexecuted delivery properties must not be represented as completed output facts.

### Reference-role and Day/Night contract

- Add a forward-compatible role schema for `first_frame`, `last_frame`, `identity_reference`, `style_reference`, `material_reference`, `site_reference`, `motion_reference_video`, `camera_reference_video`, `audio_reference`, and `timeline_guide`.
- A4.1 activates only `first_frame` and `last_frame`; preserve the ability to add other roles later.
- For Day/Night require separately approved `first_reference_asset_id` and `last_reference_asset_id`. Bind first only to FL2VA first input and last only to FL2VA last input.
- Reject missing, unapproved, stale, cross-project, or role-mismatched references. Define and test the same-asset-twice policy; for the A4.1 endpoint contract, do not permit one asset to masquerade as two independent frames.
- Carry role identity and approval through Study → Prompt → Job snapshot → binder → final execution workflow → diagnostics. Normal one-reference workflows retain their simple UX; Day/Night displays separate Start frame and End frame controls.
- Preserve the Golden template bytes/topology (ZERO DIFF). Only existing value slots may be bound in the runtime payload.
- Add a future-compatible `guide_frames[]` data contract (`asset_id`, role, time, frame index, approval state); do not execute `MiniMaxH3AddGuide` in A4.1.

### Research registers (research only)

#### Reference-project register — checked 2026-09-24

This is a source-review snapshot, not a dependency lock. GitHub default branches and README activity can move; before any later install, pin a commit and re-check the exact license, model provenance, dependency resolver, and GPU budget. All candidates below are **`INSTALL_NOW=NO`**. Open model weights are not the same as unrestricted commercial-use rights: the current official Comfy H3 guide says locally generated commercial outputs require the MiniMax commercial license. No candidate grants permission to redistribute H3 weights.

| Primary source | Purpose; code/model license | Maintenance/activity snapshot | Assets, runtime and VRAM exposure | AVS compatibility; candidate stage |
|---|---|---|---|---|
| [Comfy-Org H3 guide](https://github.com/Comfy-Org/docs/blob/main/tutorials/video/minimax/minimax-h3.mdx), [official I2V template](https://github.com/Comfy-Org/workflow_templates/blob/main/templates/video_minimax_h3_i2v.json), [multiframe template](https://github.com/Comfy-Org/workflow_templates/blob/main/templates/video_minimax_h3_multiframe_reference.json) | Primary native H3 T2VA/I2VA/FL2VA/Ref2VA and Add Guide reference. ComfyUI code license and MiniMax H3 model license are separate; model page identifies MiniMax H3 Community License. | Rolling `main`; documentation crawled 2026-09-23/24. Pin a core/template commit for any later runtime proof. | H3 DiT, Qwen3-VL encoder and video/audio VAEs; multi-GB checkpoints and meaningful VRAM/host-RAM pressure. Current official guide describes native 24 FPS and ~15 s output; 2K is a separately represented capability, not proof the frozen 0.33.1 Golden graph accepts a 2K base canvas. | Reference contract only in A4.1. Any node/runtime change requires an isolated later stage (A5/A6/A3 as relevant); current production 0.33.1 untouched. |
| [HM-RunningHub/ComfyUI_RH_MinMaxH3](https://github.com/HM-RunningHub/ComfyUI_RH_MinMaxH3) | Full direct/in-process H3 runtime, including first+last FL2VA and Ref2VA. Plugin declares Apache-2.0; model weights retain their own terms. | Public `main`; README documents 0.5.0 workflow examples. Treat version as mutable until a commit is pinned. | Requires matching CUDA PyTorch, Triton, `comfy-kitchen`; `transformers` 4.57.0–5.8.1, `accelerate`, `safetensors`, `numpy`, `sentencepiece`, `einops`, Pillow; FFmpeg/ffprobe for video/audio references. Requires flat and sharded H3 asset/config files; README warns substantial host RAM/fast storage. No 12-GB owner-GPU guarantee established. | Replaces the frozen native runtime approach rather than a thin value binder. Only an isolated, license/model-provenance reviewed experiment; A6+ research, not an A4.1 install. |
| [ethanfel/ComfyUI-MiniMax-H3-Guide](https://github.com/ethanfel/ComfyUI-MiniMax-H3-Guide) | Typed prompt/reference-role planning and H3 prompt compilation. `GPL-3.0-only`; no third-party Python dependencies declared in current `pyproject.toml`; no H3 weights bundled. | 55 commits shown; package version 0.15.0; Plan v2 and tests present in the checked repository snapshot. | Uses the official Comfy H3 model/runtime when generating; planning/compilation itself does not add a model or GPU load. | Strong design reference for role semantics and native frame-grid arithmetic. GPL is a future distribution/integration gate; study concepts only. A7 candidate. |
| [imbutus/ComfyUI-MiniMaxDirector](https://github.com/imbutus/ComfyUI-MiniMaxDirector) | Timeline-to-prompt compiler and shot/camera/audio UX. MIT; package lists no runtime dependencies beyond ComfyUI; optional upscale branch is a separate dependency. | Current package metadata says 0.17.15; repository describes tests and bundled example workflow. | Official H3 checkpoints, encoder and both VAEs remain separate model assets. The plug-in itself is mainly timeline/prompt compilation; optional workflow branches may add resource cost. | Concept/UX candidate for A7 only. Its workflow and core-version requirement are not validated against the frozen Studio API or its exact packaged core. No state-model replacement. |
| [dmulxw/comfyui-minimaxh3-director](https://github.com/dmulxw/comfyui-minimaxh3-director) | H3 storyboard/timeline editor, references, retakes and chaining. Public fork of `seesee75-commits/ComfyUI-MiniMaxH3-Director`; GPL-3.0. | 22 commits shown; README's latest listed release is 0.1.5 dated 2026-08-06. This is a dated snapshot, not a maintenance guarantee. | README declares no extra pip packages and ComfyUI ≥0.30, but lists two ~21-GB FP8 DiT checkpoints, ~15-GB text encoder and two VAEs; offload still leaves high VRAM/disk/host-RAM risk. Its 16-GB statement is not an AVS 12-GB validation. | A7 interaction reference only; GPL and large model footprint require separate approval. Must not alter Golden/production workflow. |
| [Fannovel16/ComfyUI-Frame-Interpolation](https://github.com/Fannovel16/ComfyUI-Frame-Interpolation) | RIFE/FILM/AMT/GMFSS and other frame-interpolation nodes. MIT. | 159 commits shown; README labels project WIP and shows 64 issues/5 PRs at snapshot. | CUDA/PyTorch plus CuPy or selected alternate backend and per-method model files; RAM/VRAM depends on method, resolution and temporal window. Cache clearing can reduce OOM risk but increases runtime; some methods support only 2×. | Delivery-only candidate for A8. A 24→48 test is the simplest first comparison; 30/60 require explicit frame scheduling, duration/audio-sync and quality validation. Do not install in A4.1. |
| [1038lab/ComfyUI-FlashVSR](https://github.com/1038lab/ComfyUI-FlashVSR) | 2×/4× video super-resolution with tiled/low-VRAM modes and optional audio passthrough. Repository `LICENSE` is GPL-3.0; downloaded model assets have separate terms. | README's latest listed update is 2025-11-15 (1.1); 14 issues/0 PRs shown in the checked page. Re-check current maintenance before later selection. | FlashVSR weights plus Wan VAE, projection and tiny decoder; node downloads model assets from its upstream model repo. README describes tiling, but no owner-GPU VRAM guarantee; source requires at least 21 input frames. | A8 delivery-only candidate. GPL/distribution gate, Wan-derived model stack and H3 output compatibility are unproven. Keep isolated; no A4.1 install. |
| [numz/ComfyUI-SeedVR2_VideoUpscaler](https://github.com/numz/ComfyUI-SeedVR2_VideoUpscaler) | Temporal image/video upscaling and restoration. Code is Apache-2.0; model weights are separate assets with their own terms. | 423 commits shown; README contains release notes through 2.5.24 (2025-12-24) in the checked page. High activity count is not compatibility evidence. | 3B/7B model variants, VAE and FP16/FP8/GGUF paths; README claims ≤8 GB with GGUF + BlockSwap + VAE tiling, 12–16 GB with FP8/offload and 24 GB+ for FP16. These are upstream claims, not an AVS measurement. | A8 optional delivery-only candidate; independent Comfy/Python/PyTorch requirements and H3 visual/audio sync need validation. No A4.1 install. |

Primary capability references: [official H3 overview and license notice](https://github.com/Comfy-Org/docs/blob/main/tutorials/video/minimax/minimax-h3.mdx), [official H3 Image-to-Video input contract](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/MiniMaxH3ImageToVideo/en.md), [official Multiframe Reference workflow](https://github.com/Comfy-Org/workflow_templates/blob/main/templates/video_minimax_h3_multiframe_reference.json). The node contract states 24 FPS, a `17k+5` frame grid, upward snapping, and a trained-range note of approximately 124–362 frames. The local 4-second request resolves to 107 frames (4.458 s) on that grid; this is retained as the established local Golden minimum, but it is below the upstream trained-range note and is not generalized as a new quality claim.

#### Execution-parameter matrix — A4.1 static evidence

`Golden` below means the checked-in immutable `production_workflows/golden/*.json` values, before runtime binding. All candidate values are controlled product proposals, not claims that quality/VRAM has been GPU-tested in A4.1. A4.1 has no GPU execution.

| Node / field | Official or local range | Golden value | A4.1 candidate/resolved value | Effect, resource/fidelity risk, validation |
|---|---|---|---|---|
| `MiniMaxH3ImageToVideo.width/height` | Official H3 base canvas uses a 768-px short-edge class, 32-pixel alignment and an approximately 768×1344 base area; 2K is a separate regenerate/delivery mode, not silent base-graph width. | 1344×768 in all five Golden templates. | PREVIEW 832×480 and NATIVE_HIGH 1344×768 are executable; DRAFT 672×384, BALANCED 1024×576, STANDARD 1280×720, ULTRA_1080 and ULTRA_2K remain fail-closed. | Pixel count generally increases compute and memory pressure; resource slope is an estimate only. Higher canvas can expose/encourage architectural detail but can also increase hallucinated detail. Static binder/profile tests pass; no A4.1 VRAM/quality measurement. |
| `MiniMaxH3ImageToVideo.length` / requested duration | Official input accepts frame counts and snaps upward to `17k+5`; official H3 is 24 FPS, nominal 4–15 s. Grid examples: 107, 124, 243, 362. | 107 frames (4.458 s) in checked-in Golden templates. | Studio accepts requested 4–15 s; `ceil(requested_seconds×24)` then snaps upward to the next `17k+5` count. Examples: 4→107 (4.458 s), 5→124 (5.167 s), 10→243 (10.125 s), 15→362 (15.083 s). Trace records requested duration and resolved frame count/effective duration separately. | More frames increase temporal work/runtime and may increase memory pressure; longer clips raise drift/continuity risk. CPU tests verify the lattice, bound graph and trace. 107 is local-minimum evidence but below the current upstream trained-range note (~124–362); do not silently describe requested seconds as exact output seconds. |
| `BasicScheduler.steps` | H3 graph uses Comfy scheduler steps; product contract constrains 2–100. No claim that more steps are monotonically better. | 20. | PREVIEW 21; NATIVE_HIGH 50; other tiers unavailable. | More steps ordinarily increase sampling time; peak VRAM may be dominated by canvas/model and is not measured here. Architectural fidelity can improve or regress; fixed-prompt/seed A/B plus measured peak VRAM/time required before changing defaults. Static bind only. |
| `KSamplerSelect.sampler_name` | Local executable allow-list: `res_multistep`, `euler`. | `res_multistep`. | PREVIEW `res_multistep`; NATIVE_HIGH `euler`; profile fully determines it. | Changes denoising trajectory and motion/detail; no isolated sampler comparison in A4.1. Do not infer a quality ranking from profile names. |
| `BasicScheduler.scheduler` | Current local Golden contract keeps `simple`; no alternate scheduler is exposed by A4.1. | `simple`. | Fixed `simple`. | No extra graph/runtime branch. Scheduler changes can alter temporal/architecture adherence; no unsupported override accepted or recommended. Static only. |
| `RandomNoise.noise_seed` | Comfy RandomNoise seed is a non-negative integer; UI/JSON exact-integer transport is the practical boundary for reproducible input. | 777888999 on workflows 01–03; 777888904 on workflows 04–05. | Per-Job explicit seed; otherwise existing deterministic product default 42. | No meaningful model-size increase; controls stochastic variation and reproducibility, not a guaranteed fidelity gain. Every Job records seed; controlled A/B must hold it fixed. |
| `BasicScheduler.denoise` | Local node field 0–1; current AVS path intentionally fixes it to 1.0. | 1.0. | Fixed 1.0; no UI control. | Changing it alters the sampling/noise contract and may weaken endpoint/geometry adherence; no A4.1 validation or resource claim. |
| `first_frame`, `last_frame`, Ref2VA `ref_image_size` | FL2VA first/last are concrete timeline endpoints; H3 accepts two endpoint slots. Official Image-to-Video preprocessing stretches the first image and cover-crops the last. `match`/`max` is a separate Ref2VA sizing control, not active in A4.1. | I2VA: one LoadImage; Day/Night FL2VA: two LoadImage nodes, first + last. Both source templates use 1344×768 canvas, 107 frames. | Exactly one approved `first_frame` for ordinary I2VA; two distinct, approved, ordered `first_frame` + `last_frame` for Day/Night. Other eight roles are schema-only. | Two refs add endpoint encoding/I/O cost; no H3-model VRAM delta measured. Aspect-ratio stretch/crop and endpoint mismatch can distort architecture; UI warns through explicit role slots. E2E API→binder test proves role order; no GPU visual test. |
| `MiniMaxH3AddGuide` count | Official Add Guide can be chained to anchor compatible guide media at a frame index; full exact input semantics are runtime-version-specific. | 0. | `guide_frames[]` is metadata-only; executable guide count is exactly 0 in A4.1. | No current H3 GPU/memory cost because nothing is bound. Guide-to-frame mapping and conflict semantics await A5 source pin and tests. |
| Guide `time_seconds` / `frame_index` | Guide anchors refer to native timeline positions; native clock is 24 FPS. A4.1 schema validates non-negative metadata only. | Not present. | Optional metadata entries retain asset ID, role, time, frame and approval; never call Add Guide. | No current runtime effect. Off-by-one, out-of-range and overlapping anchors are deferred to A5; do not claim active keyframing. |
| Delivery width/height | Native PREVIEW 832×480 / NATIVE_HIGH 1344×768. 1920×1080 is post-upscale delivery; aspect-aware 2K needs explicit `H3_REGENERATE_2K` or `POST_UPSCALE_2K`. | Delivery follows native graph output; no independent upscale fields. | Delivery remains identical to native output; ULTRA_1080/ULTRA_2K unavailable and require explicit later pipeline. | Upscale adds memory, disk, runtime and possible detail hallucination; none is measured or executed here. Trace fields exist, methods remain null and `postprocess_applied=false`. |
| `CreateVideo.fps` / delivery FPS | Official native H3 is fixed at 24 FPS. Product delivery choices are 24/30/48/60; only 24 is ready. | 24.0. | Native 24; delivery 24. 30/48/60 marked FUTURE_POSTPROCESS and rejected at submit time. | Interpolation adds temporal work and may ghost thin façade lines, windows and railings or desync audio. VFI/24→48 is A8 research; no plugin or frame-rate conversion in A4.1. |

Research references for future stages: [HM-RunningHub](https://github.com/HM-RunningHub/ComfyUI_RH_MinMaxH3), [H3 Guide](https://github.com/ethanfel/ComfyUI-MiniMax-H3-Guide), [MiniMaxDirector](https://github.com/imbutus/ComfyUI-MiniMaxDirector), [H3 Director fork](https://github.com/dmulxw/comfyui-minimaxh3-director), [VFI](https://github.com/Fannovel16/ComfyUI-Frame-Interpolation), [FlashVSR](https://github.com/1038lab/ComfyUI-FlashVSR), and [SeedVR2](https://github.com/numz/ComfyUI-SeedVR2_VideoUpscaler).

### A4.1 forbidden scope

Do not install VFI, FlashVSR, SeedVR2, Director/custom nodes, new H3 weights, ControlNet, or a new ComfyUI core. Do not implement Add Guide, Ref2VA, 6DoF camera control, 1080p/2K processing, A4.2 GPU tests, or later stages. No GPU is required for A4.1. Do not expose owner prompts/media or credentials to tools or repository artifacts.

### Required tests and acceptance

Cover all profile IDs and availability, native/delivery separation, rejection of unavailable execution, dual-reference approval and role binding, missing-first/missing-last, cross-project/stale references, same-ID policy, Job snapshot, trace/provenance, exact workflow SHA, Prompt Engine, binder, Native reconstruction, and Golden zero-diff. Run focused and canonical regression, Python compileall, JavaScript syntax checks, and `git diff --check`.

A4.1 is complete only when the seven-tier model, native/delivery FPS split, dual-reference Study/Prompt/Job/binder/diagnostics path, future-compatible role/guide schemas, Studio integration, trace/provenance, Golden ZERO DIFF, and all required tests pass. Otherwise classify `ADVANCED_A4_BLOCKER_REMAINS`, keep G at 22% / total 88.00%, and report the exact blocker. Only full static/E2E completion may advance local progress to G 27% / total 88.50%; remote durable progress changes only after explicitly authorized commit and push.

### A4.1 local static/E2E closeout — 2026-09-24

**Status: `A4.1_LOCAL_STATIC_AND_E2E_ACCEPTED`.** The static and CPU-only
end-to-end gates pass. The seven quality tiers and availability reasons are
explicit; only PREVIEW and NATIVE_HIGH execute. Native generation/delivery are
separate, native FPS is exactly 24, and requested duration is retained alongside
the H3 17k+5 frame-grid result. The maximum 15-second request resolves to 362
frames (15.083333 seconds effective) through Prompt, Job, and Golden binding.

The approved, ordered first/last Day/Night reference path is exercised across
Study, Prompt, Job snapshot, runtime request, Golden binder, trace, and workflow
SHA. Missing, stale, unapproved, duplicated, role-mismatched, or cross-Study
references fail closed. Future guide roles remain metadata-only. The official
reference/parameter research registers are recorded above. No GPU run, plugin,
model, ComfyUI runtime, or production workflow was changed; Golden V1 is zero
diff. Full regression: 859 tests passed, 38 skipped; inventory delta: zero.
Python compileall, changed JavaScript syntax checks, and `git diff --check` pass.

Local evidence advances Advanced Product Layer G to **27%** and the weighted
product roadmap to **88.50%**; A–F remain unchanged. This freeze is a single-
commit sync gate: remote durable progress remains G 22% / total 88.00% until
the A4.1 commit is pushed and the remote branch head is verified equal to the
final local SHA. After that gate passes, remote progress is G 27% / total
88.50% with A–F unchanged.
