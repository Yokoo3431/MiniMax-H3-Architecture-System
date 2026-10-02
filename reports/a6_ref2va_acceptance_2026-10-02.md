# A6 Ref2VA Acceptance

Date: 2026-10-02

Decision: `PASS_WITH_BOUNDED_LIMITATIONS`

## Scope and durable baseline

- Branch: `feature/h3-advanced-workflows`
- Source baseline: `958464d56294239a8a79d54e88fa5a8b0d839da2`
- Production ComfyUI remains frozen at 0.33.1 / 8189. Ref2VA remains an explicitly selected experimental capability on the isolated 0.36.0 / 8190 runtime.
- This closeout reuses the two A6 GPU submissions already consumed by the A6 limit. It submits no new Job and no new `/prompt`.

## Capability contract

The Studio extends the existing approved-reference architecture. The image-only Ref2VA path supports explicit `identity_reference`, `style_reference`, `material_reference`, and `site_reference` roles. It preserves separate `first_frame` / `last_frame` FL2VA semantics and keeps `timeline_guide` on the A5 AddGuide path.

Current official ComfyUI `MiniMaxH3ReferenceToVideo` source supports image, video, paired video-audio, and standalone audio references, with deterministic family ordering and schema-declared dynamic limits. The Studio reads limits from live `object_info`. For this A6 slice, video/audio ingest and compilation are deliberately unavailable and fail closed (`REF2VA_MEDIA_INGEST_NOT_READY`); the product does not claim mixed-media execution. No third-party node or code was installed or vendored. The H3 Guide project was used as research context only.

Sources reviewed: [official ComfyUI H3 node](https://github.com/Comfy-Org/ComfyUI/blob/master/comfy_extras/nodes_minimax_h3.py), [official multiframe-reference workflow](https://github.com/Comfy-Org/workflow_templates/blob/main/templates/video_minimax_h3_multiframe_reference.json), and [ComfyUI-MiniMax-H3-Guide](https://github.com/ethanfel/ComfyUI-MiniMax-H3-Guide).

## Real execution evidence

Two controlled A6 submissions were made in the preceding A6 work; this closeout did not add another.

- One isolated experimental Ref2VA Job completed with two approved image bindings (`identity_reference`, `site_reference`). The immutable Job retained runtime identity, execution workflow SHA, reference role/content-hash provenance, and the Ref2VA plan/count.
- Comfy history, output discovery, media probe, packaging, output delivery, and Result persistence all passed. The packaged MP4 is 832×480 at 24 FPS, 107 frames / approximately 4.458 seconds effective duration, and 1,301,640 bytes. The Studio media endpoint returned HTTP Range 206.
- Three sampled frames show broad site/building identity and massing stability, with no severe redesign apparent. This is a coarse preview review only; fine façade/material fidelity and per-reference similarity are not scored.
- The second submission terminated before sampling at Windows progress-output initialization (`stderr.flush`, `OSError: [Errno 22] Invalid argument`) and produced no Result. A CPU-only reproduction on the isolated Python environment shows that setting `TQDM_DISABLE=1` before importing tqdm avoids that initialization failure. This is not GPU evidence; no runtime workaround was silently installed and no retry was performed.

## Trace correction and historical immutability

The successful historical Job is labeled `TRACE_INCOMPLETE` with a persisted `ValueError` class because the then-current parameter resolver recognized `MiniMaxH3ImageToVideo` but not `MiniMaxH3ReferenceToVideo`. The same immutable Job nevertheless contains runtime identity, execution SHA, both approved reference bindings with content hashes, Ref2VA plan/count, and successful output/result evidence. The source now resolves either native H3 conditioning node, validates the bound Ref2VA parameters during preflight, and has CPU regression coverage. Historical Job evidence was not rewritten.

## Product, safety, and validation gates

- Image role board and fail-closed media boundaries: pass by source contract and A6 tests.
- Multi-image native execution and Studio Result lifecycle: pass on the existing completed Job.
- Mixed video/audio path: explicitly unavailable; no unsupported capability is advertised.
- Full canonical suite: 975 passed, 38 expected skipped, 0 failed.
- A6 focused suite: 31 passed.
- Regression inventory: no added/removed tests and no skip changes.
- Python compileall, JavaScript syntax, `git diff --check`: pass.
- Golden V1: zero diff (covered by the canonical regression suite).
- Installed Studio backend parity: all nine A6-relevant backend/runtime/UI files match the current source.
- Studio health: pass. Production ComfyUI 8189: 0.33.1, healthy, queue 0/0, `MiniMaxH3AddGuide` absent. Experimental 8190: offline after validation.
- Privacy: no Prompt text, reference pixels, generated media, absolute owner paths, credentials, or raw logs are included in this report.

## Independent review and bounded decision

The configured Antigravity Review could not start: the Observer executor failed before launch with a Windows `NUL` path `ENOENT`. Its failed run created no code changes; its temporary worktree was removed. No Antigravity opinion is represented.

Codex delegated product review accepts A6 for approved multi-image Ref2VA reference roles and the delivered result lifecycle, bounded to coarse architectural identity at preview resolution. Video/audio references, fine-detail fidelity, and robust tqdm progress output remain explicit limitations. They are not represented as validated capabilities.

## Progress decision

After the closeout commit is pushed and remote equality is verified:

- G Advanced Product Layer: 48% / 10% weight / 4.80% contribution.
- Total implemented/durable roadmap: 90.60%.
- A–F remain unchanged.
- A6 status: `COMPLETE_WITH_BOUNDED_LIMITATIONS`.
- Next stage: A7 Director / Shot Timeline / Retake.
