# Studio UX 2.0 — Reference Audit

Status: planning only. No UX2-P1 implementation is included in this pass.

## 1. Scope and source boundary

The production/RC control plane is frozen on the separate `release/v0.8.0-rc1`
branch. This UX2 planning branch starts from that synchronized freeze and may
only add research notes and planning documents until the owner reviews them.

The primary product object remains the Study / video-generation task, not a
project-management record:

`Reference → Video Intent → Workflow → Parameters → Prompt Preview → Generate → Review → Advanced ComfyUI`

The named historical `PATCH2.6A` through `PATCH2.6D2` files are not present in
this checkout. Their absence is recorded rather than reconstructed. Historical
context was therefore taken from the available `CURRENT_DEVELOPMENT_HANDOFF`,
RC completion/release reports, H3 provenance report, and
`RC_PRODUCTION_CORE_FREEZE.md`.

The local research copies are outside production source and remain covered by
the existing `_research/` ignore rule:

| Reference | Local revision | Intended use |
|---|---|---|
| InvokeAI | `4b2254bfbd631b5adcbdca482d188ef596df3cde` | interaction and information-architecture patterns |
| ComfyUI_frontend | `98fc2f1181e96e7b50771987ab32ccde5b658064` | workflow viewer and queue/history lifecycle patterns |

No reference code, assets, or license files are vendored into AVS.

## 2. Historical AVS principles retained

- Viewport first; target visual priority is approximately 70/30.
- A large dark video viewport is the dominant working surface.
- Light professional tool surfaces surround the viewport.
- Reference and controls can be docked or collapsed without losing context.
- Status belongs close to the viewport as a compact overlay/strip.
- Generation parameters are grouped by user task; advanced technical values are
  progressively disclosed.
- Typography is compact, aligned, and suitable for numeric comparison.
- Home emphasizes New Study and Recent Studies.
- Studio remains the canonical Study/Job/output surface.
- Native ComfyUI remains an Advanced diagnostic surface, not a competing source
  of Job truth.

## 3. InvokeAI patterns worth borrowing

The checked-out InvokeAI README and frontend structure identify a unified
canvas, gallery/board interaction, workflow management, event coordination,
and reusable UI panels. The useful transferable patterns are:

- canvas or preview remains the visual anchor while tools operate around it;
- generated assets are first-class reviewable items, not only rows in a job log;
- gallery/history supports recall and iteration without turning the home screen
  into an analytics dashboard;
- generation controls are task-oriented and can hide workflow complexity;
- asynchronous execution is represented by explicit event/state coordination,
  rather than a timer inferred only from a page-local flag;
- inspector-like panels provide progressive disclosure for details.

AVS will borrow the interaction principles only. AVS does not adopt InvokeAI's
image-generation product model, model catalog, node graph model, or storage
semantics.

## 4. ComfyUI frontend patterns worth borrowing

The checked-out frontend exposes separate concepts for workflow tabs/activity,
queue stores, job history, asset sidebars, result galleries, queue progress
overlays, and bottom-panel/terminal surfaces. The useful patterns are:

- explicit workflow-tab identity and loading lifecycle;
- queue/history as a secondary operational surface with clear active/terminal
  distinctions;
- compact progress overlays that do not consume the main canvas;
- sidebars and bottom panels that can be opened when needed;
- explicit output/result views and action menus;
- a clear boundary between the workflow editor and surrounding application
  chrome.

AVS will use these patterns only for Advanced Native Comfy navigation and
diagnostics. The canonical AVS Job, Study projection, ETA, terminal state, and
output delivery contracts remain unchanged.

## 5. D5 / Rhino / Enscape direction retained

The official D5 interface documentation reinforces a real-time viewport as the
primary surface, a compact top toolbar for common tools, camera controls close
to the viewport, and optional sidebars/shortcuts for secondary operations. The
official Rhino documentation reinforces viewport titles, dockable/floating
viewports, viewport maximize/restore, and a title/menu boundary for view
operations.

Applied to AVS, these imply:

- preserve spatial continuity while changing a parameter;
- keep the preview visible while opening reference, intent, or parameter tools;
- use small overlays for status and camera-like context, not large modal dialogs;
- allow a focused preview mode while retaining a discoverable return path;
- treat panel placement and collapse as part of the workstation flow.

These are visual and interaction references only; no D5/Rhino code or assets
are copied.

## 6. Patterns explicitly rejected

- KPI cards, SaaS analytics, or project-management dashboard as Home;
- chat-first prompt UI or conversational chrome as the main workflow;
- equal-width three-column layout that starves the viewport;
- exposing the raw Comfy graph as the default generation experience;
- hiding the current Study identity while navigating jobs or outputs;
- a page-local timer that can contradict canonical Job terminal truth;
- unbounded technical sliders and provider details in the primary path;
- copying a reference product's object model, visual assets, or source code;
- showing text-only Prompt Engine execution as image understanding.

## 7. Research conclusion

UX2 should be a viewport-first Study workstation with progressive disclosure:
the user sees the reference, intent, current video/output, and generation state
as one continuous task. Job Center, Environment, Output Review, and Advanced
Native Comfy are supporting surfaces. The next implementation step is the
design-token/shell stage only after owner review of the planning documents.

## Sources

- [D5 Render — Interface, Shortcuts, Camera](https://docs.d5render.com/getting-started/d5-workflow/interface-shortcuts-camera)
- [D5 Render — Camera and Views](https://docs.d5render.com/user-guide/view/camera)
- [Rhino 8 — The Rhino window](https://docs.mcneel.com/rhino/8/help/en-us/user_interface/rhino_window.htm)
- [Rhino 8 — Viewport tabs](https://docs.mcneel.com/rhino/8/help/en-us/unfurl/viewporttabs.htm)
- [InvokeAI repository](https://github.com/invoke-ai/InvokeAI)
- [ComfyUI_frontend repository](https://github.com/Comfy-Org/ComfyUI_frontend)
