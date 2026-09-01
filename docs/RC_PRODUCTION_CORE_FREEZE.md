# Architect Video Studio — RC Production Core Freeze

Status: production/RC foundation freeze. This document records the stable
control-plane baseline; it is not a claim that the complete product roadmap is
finished.

## Frozen architecture

Architect Video Studio is the user-facing architectural video workstation.
The primary domain object is a Study / video-generation task:

`Reference → Video Intent → Workflow Selection → Parameters → Prompt Preview → Generate → Review → Advanced ComfyUI`

The five Golden workflows remain registry-driven and unchanged:

1. `01_Exterior_Hero`
2. `02_Day_Night_Transition`
3. `03_Material_Detail`
4. `04_Drone_Aerial`
5. `05_Slow_Walkthrough`

The Native ComfyUI, model, NVFP4, DiT, VAE, and Runtime generation routes are
not redesigned by this freeze.

## Prompt Engine

- Offline H3 compilation is the guaranteed baseline.
- Antigravity is an optional external CLI enhancement path.
- The proven text path is `TEXT_REASONING_H3`.
- The pinned official Skill metadata is the reviewed local H3 prompt-writing
  bundle; provenance is recorded by hashes and manifests without storing raw
  prompts or provider output.
- Text-only execution must not be represented as image-understanding
  optimization.

## Job and Study truth

- Canonical Job records own execution state.
- Terminal states include `COMPLETED`, `FAILED`, `CANCELLED`, and
  `SUBMISSION_LOST`.
- Active/recoverable state is centrally defined; `RECONCILING` is active only
  while recoverability evidence remains valid.
- Study status, active Job ID, and last-job projection are rebuilt from Job
  records.
- Terminal records have normalized completion timestamps and messages.
- Late queue, WebSocket, or callback data cannot resurrect a terminal Job.

## Runtime and output

- Installation readiness is separate from live Engine health.
- Engine health is lightweight: managed process, port reachability, and
  `/system_stats`.
- Packaged cold start enters normal production mode and starts Managed ComfyUI
  without requiring Setup Mode when installation evidence is intact.
- Output collection and custom Study delivery verify destination, size, and
  SHA-256 consistency.

## ETA and progress

- Pre-generation ETA uses the historical total-time range when available.
- If the current H3 path emits no usable numeric `value/max` telemetry, the UI
  displays an honest unknown value (`—`) together with semantic stage, elapsed
  time, and historical ETA.
- No percentage is fabricated.

## Known non-blocking limitations

- The current H3 execution path may not emit numeric `value/max` progress.
- Native ComfyUI is an Advanced diagnostic surface, not canonical Job truth.
- Idle `/free` is best-effort; a successful API call may not produce a
  measurable Windows or driver-level memory drop.
- The complete Architect Video Studio roadmap remains separate from this
  production-core freeze.

## Validation baseline

- Focused control-plane diagnostics: PASS.
- Canonical regression: 811 tests, 38 expected skips, 0 unexpected failures.
- Python compilation and JavaScript syntax checks: PASS.
- Golden workflow files and registry: unchanged.
- GitHub synchronization is intentionally performed by the freeze task; no
  public release or tag is created by this document.
