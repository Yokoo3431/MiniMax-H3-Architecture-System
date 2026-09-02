# Studio UX 2.0 — Migration Plan

Status: planning only. Owner review is required before UX2-P1 implementation.

## 1. Migration principles

Studio UX2 is an incremental shell/workspace evolution over the frozen
production control plane. It is not a runtime rewrite and not a new generation
architecture.

The migration must preserve:

- the five Golden workflows;
- exact workflow binding and prompt-to-Job hash chain;
- H3 Prompt Engine and official Skill provenance;
- canonical Job/Study state convergence;
- ETA and honest unknown-progress behavior;
- output collection and custom delivery;
- independent Engine health and installation readiness;
- Advanced Native Comfy as a secondary diagnostic boundary.

The feature branch is intentionally separate from the production freeze branch.
`_research/ui_reference` is local-only and ignored. No reference project is
vendored.

## 2. Staged implementation

### UX2-P0 — Reference audit and information architecture

Deliverables:

- reference audit;
- surface/data ownership map;
- migration acceptance criteria;
- owner review decision.

Acceptance: planning documents are complete; no production UI code changes.

Non-goal: no design-token implementation or route rewrite.

### UX2-P1 — Tokens, shell, navigation, viewport hierarchy

Deliverables:

- AVS-specific tokens for light professional surfaces, dark viewport, spacing,
  typography, status colors, and focus states;
- shell/navigation that preserves Study identity;
- viewport-first responsive frame;
- feature-flagged or route-isolated entry point where practical.

Acceptance: existing production route remains usable and the new shell can be
disabled without touching backend behavior.

Non-goal: no change to Golden workflow payloads, Job APIs, or prompt logic.

### UX2-P2 — Home and Recent Studies

Deliverables:

- New Study action;
- Recent Studies cards;
- empty/loading/error/terminal card states;
- direct continuation into the correct Study.

Acceptance: Home is task-oriented and contains no KPI/project-dashboard layer.

### UX2-P3 — Study Workspace viewport-first reconstruction

Deliverables:

- dominant video viewport/output surface;
- collapsible reference drawer;
- compact viewport status strip;
- preserved links to Job Center and Output Review.

Acceptance: viewport remains usable at supported packaged window sizes and all
existing Study state labels remain canonical.

### UX2-P4 — Reference, Intent, and Generation Controls

Deliverables:

- reference approval/metadata surface;
- natural-language intent field;
- workflow/video type and primary parameters;
- advanced resolution/FPS/seed/technical controls collapsed by default.

Acceptance: changing inputs invalidates stale prompt state through existing
contracts and does not alter workflow topology.

### UX2-P5 — Job, ETA, status, and output overlays

Deliverables:

- status strip bound to canonical Job state;
- historical ETA range before numeric telemetry;
- real numeric progress only when emitted;
- truthful `—` fallback with stage and elapsed time;
- terminal normalization and output-delivered indicator.

Acceptance: no frontend-only active list, timer, or terminal state can override
backend truth.

### UX2-P6 — Output Review, history, and comparison

Deliverables:

- delivered output review;
- prior Study Job history;
- safe comparison of completed outputs;
- keep/delete-output choices consistent with existing delete contract.

Acceptance: review actions do not create active Jobs or block deletion of
terminal Studies.

### UX2-P7 — Advanced Native Comfy boundary

Deliverables:

- explicit open-with-Job-snapshot action;
- one compact Return Studio control;
- repeated navigation identity checks;
- no stale localStorage/sessionStorage draft override.

Acceptance: Native Comfy remains diagnostic/advanced; AVS remains canonical.

### UX2-P8 — Accessibility, scaling, and packaged acceptance

Deliverables:

- keyboard/focus review;
- window scaling and panel collapse review;
- packaged cold-start and normal production-mode acceptance;
- state/output/delete regression across all five workflows.

Acceptance: zero unexpected regression failures and no architecture-boundary
diff.

## 3. Execution and rollback strategy

Each stage should be a small reviewable change set. Prefer additive components,
route flags, and adapters over replacing the existing workspace in one rewrite.
Keep the existing production route available until the corresponding packaged
acceptance gate passes.

Rollback means disabling the UX2 entry point or reverting the stage-specific UI
change; it must not require restoring models, runtimes, workflows, or owner
userdata. Research clones remain disposable and outside source control.

## 4. Required gates before implementation

Before UX2-P1:

1. owner reviews this planning set;
2. product surface names and navigation are approved;
3. tokens and viewport breakpoints are specified;
4. backend contracts consumed by the shell are listed;
5. acceptance screenshots/tests are defined;
6. Golden workflow and runtime freeze checks remain green.

No new backend feature is implied by this plan. A backend change is allowed
only when an existing UI contract is proven insufficient and the change is
approved as a separate bounded task.

## 5. Current decision

Phase B is `STUDIO_UX2_PLANNING_READY`. The next authorized action is owner
review. UX2-P1 must not start automatically from this document.
