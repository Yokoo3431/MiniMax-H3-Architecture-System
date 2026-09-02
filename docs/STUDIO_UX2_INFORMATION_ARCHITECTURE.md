# Studio UX 2.0 — Information Architecture

Status: planning only. This document defines surfaces and ownership; it does
not implement UX2-P1 or change backend contracts.

## 1. Product object and truth model

The primary object is a Study, representing one architectural video task.
Projects are optional organizational metadata. A Study owns the user journey,
while canonical Job records own execution truth.

The product flow is:

`Reference → Video Intent → Workflow Selection → Generation Parameters → Prompt Preview → Generate → Review → Advanced ComfyUI`

The following boundaries remain fixed:

- Study status is a projection of canonical Jobs.
- Engine health is independent of selected Study/Job state.
- Prompt provenance and validator result are explicit metadata.
- ETA uses the existing historical range and honest unknown-progress fallback.
- terminal Job state cannot be resurrected by late polling or WebSocket data;
- output delivery remains an explicit, hash-verified result path.
- Advanced Native ComfyUI is diagnostic/workflow inspection, not canonical Job
  truth.

## 2. Surface map

### Home

Purpose: choose or start a video task quickly.

Primary content:

- New Study / New Video action;
- Recent Studies ordered by last modification;
- Study card with reference thumbnail, name, workflow/video type, current
  status, output preview when available, and last modified time;
- clear empty state when no Study exists.

Home must not become a KPI dashboard, project-management table, or provider
configuration screen.

### Study Workspace

Purpose: complete and review one video task.

Recommended hierarchy, without forcing equal columns:

- left/collapsible: approved reference and reference metadata;
- center/dominant: dark Video Viewport or delivered output preview;
- right/tool panel: intent, workflow, generation parameters, and prompt
  assistance;
- viewport status strip: preparing/loading/sampling/decoding/finalizing/
  completed, elapsed time, ETA range, and numeric progress only when real
  telemetry exists;
- compact actions: save, generate, open Job Center, review output, and open
  Advanced Native ComfyUI.

The viewport should remain visible during ordinary edits. Prompt Preview is
collapsed by default and must show whether the result is Offline or AI
optimized, the provider, and H3 Skill status.

### Job Center

Purpose: operational history and diagnosis across a Study or project.

Content:

- canonical Job ID, workflow, status, timestamps, progress/unknown marker,
  output link, and failure/reconciliation summary;
- filters by Study and terminal/active state;
- links back to the owning Study and output review.

Job Center must project backend truth; it must not maintain a second active-job
state model.

### Output Review

Purpose: inspect delivered video results and compare iterations.

Content:

- playable output preview;
- Study and Job identity;
- workflow/parameter summary;
- delivered path state and integrity outcome;
- open-folder/export actions where permitted;
- prior completed outputs as review history.

Output Review does not alter the Job lifecycle or replace the Study's canonical
state projection.

### Environment

Purpose: show installation readiness and engine health separately.

Content:

- installation/provisioning readiness and repair guidance only when required;
- Engine STOPPED/STARTING/READY/DEGRADED/CRASHED/RESTARTING;
- managed process/port/system-health summary;
- model/support-layer readiness;
- optional idle model-memory policy status.

Environment must not infer installation failure merely because ComfyUI is
temporarily offline, and must not derive Engine health from a selected Job.

### Advanced Native Comfy

Purpose: inspect or operate the native workflow surface for advanced users.

Entry is explicit from a Study/Job and carries the exact Job workflow snapshot
and identity. The surface may expose workflow tabs, node graph, queue/history,
and native diagnostics. Return Studio is one compact, non-obstructive control.

Native Comfy state is never allowed to overwrite the canonical AVS Job or Study
projection merely because a draft, tab, or local browser state differs.

## 3. Navigation and state transitions

The normal path is:

1. Home → New Study.
2. Study Workspace → reference approval and intent.
3. Workflow/parameters → prompt preview.
4. Generate → viewport status strip and Job Center link.
5. Completion → Output Review.
6. Optional → Advanced Native Comfy diagnostics.

Every surface preserves Study identity in the header or breadcrumb. Back/return
actions preserve the current Study and do not create a new draft implicitly.

## 4. Responsive and accessibility rules

- viewport remains the largest region at desktop sizes;
- panels collapse before the viewport is squeezed below a usable preview size;
- every collapsed panel has a visible label and keyboard-accessible toggle;
- status is conveyed by text as well as color;
- active, terminal, degraded, and unknown-progress states have distinct labels;
- progress `—` is meaningful unknown, never a disguised `0%`;
- focus order follows Reference → Intent → Workflow → Parameters → Prompt →
  Generate → status/output actions;
- destructive Study deletion is separated from output retention choice;
- empty, loading, failed, reconciled, and completed states retain a usable
  route back to the owning Study.

## 5. Backend contract boundary

UX2 may consume existing APIs and persisted fields. It must not change:

- Golden workflow topology or exact workflow binding;
- Native Runtime, H3 models, NVFP4, DiT, VAE, or support-layer contracts;
- official H3 Skill source/provenance contract;
- canonical Job terminal truth, Study projection, output delivery, or ETA
  semantics.

Any backend change later requires a separately documented contract gap and
focused regression evidence.
