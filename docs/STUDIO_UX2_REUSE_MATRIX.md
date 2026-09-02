# Studio UX2 Reuse Matrix

Status: UX2-P1.6A. Research only; no production source or backend changes.

| Component / pattern | Reference project | Exact source path | License | Classification | Reason |
|---|---|---|---|---|---|
| Unified visual workspace / viewport anchor | InvokeAI | `invokeai/frontend/web/src/features/canvas/` | Apache-2.0 repository license; inspect file headers before any code reuse | PATTERN_ONLY | React/application state and image-generation semantics are too coupled to AVS; borrow the canvas-first hierarchy only. |
| Reference/gallery thumbnail presentation | InvokeAI | `invokeai/frontend/web/src/features/gallery/` | Apache-2.0 repository license; inspect file headers before any code reuse | PATTERN_ONLY | AVS needs one Study reference and output recall, not a gallery/board system or a second asset store. |
| Generation inspector and collapsible sections | InvokeAI | `invokeai/frontend/web/src/features/parameters/` and `invokeai/frontend/web/src/components/` | Apache-2.0 repository license; inspect file headers before any code reuse | PATTERN_ONLY | The pattern is valuable, but the component tree and state model are not self-contained AVS primitives. |
| Desktop workspace / Program Monitor relationship | OpenScene | `src/renderer/src/` (workspace, studio, and preview modules) | MIT | PATTERN_ONLY | OpenScene's Electron/React/typed-bridge architecture and editing core must not enter AVS; borrow preview priority and density. |
| Compact toolbar and side-panel density | OpenScene | `src/renderer/src/components/` and `src/renderer/src/` studio modules | MIT | PATTERN_ONLY | Useful workstation language, but not a drop-in component without importing its application state and component system. |
| Generation-studio framing around a preview | OpenScene | `src/renderer/src/` studio/preview modules | MIT | EASY_PORT | Port the information hierarchy into existing AVS HTML/CSS; do not copy video/voice/editor features or provider logic. |
| Preview / inspector hierarchy | OpenCut Classic | `apps/web/src/preview/`, `apps/web/src/panels/`, and `apps/web/src/editor/` | MIT | PATTERN_ONLY | Strong desktop composition reference, but timeline/editor state is explicitly outside AVS. |
| Compact toolbar / panel spacing | OpenCut Classic | `apps/web/src/components/`, `apps/web/src/panels/`, and `apps/web/src/editor/` | MIT | EASY_PORT | Recreate the spacing and grouping locally in vanilla CSS; copying the implementation would bring the editor framework. |
| Resizable split panes | All three | Reference-specific layout modules | Apache-2.0 / MIT | NOT_WORTH_IT | AVS needs a stable viewport-first frame and bounded collapsible drawers; a general resize system adds complexity before the simple flow is proven. |
| Timeline, media-bin, node graph, chat agent, provider/database systems | OpenScene / OpenCut Classic / InvokeAI | Reference-specific domain modules | Mixed | NOT_WORTH_IT | These are product features, not presentation primitives, and would conflict with the frozen AVS architecture. |

## Recommended AVS implementation kit

There is no justified `DIRECT_REUSE` item in this audit. Build four small local presentation primitives with existing HTML/CSS/vanilla JS when implementation begins:

1. `viewport-frame`: dominant dark preview/output surface with a compact status strip.
2. `compact-topbar`: Study identity, route tabs, and independent engine status.
3. `inspector-section`: short labeled section with optional collapsed advanced content.
4. `reference-thumb`: one reference thumbnail with clear selected/empty state.

These primitives consume existing APIs and canonical projections; they do not own Job or Study state.

## Navigation prerequisite

Before any workspace implementation, repair and test route ownership. Active navigation must derive from the current route, and health polling must never redirect to Environment. Required regression cases are Study opened directly, Study reached from Home, repeated refresh, Jobs/Outputs/Environment navigation, and engine status changes while the user remains on Study.

## Boundary and privacy

`_research/ui_reference/` is local-only and ignored. Reference repositories are not vendored, their assets are not copied, and no owner Study, prompt, media, runtime log, or userdata is included in these documents.
