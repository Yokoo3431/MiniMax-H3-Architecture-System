# Studio UX2 Simple Workspace Reference

Status: UX2-P1.6A research and reuse audit. This document does not start UX2-P2 and does not change production source, backend, runtime, Prompt Engine, or Golden workflows.

## Recommendation

Keep Route A: AVS remains a lightweight HTML/CSS/vanilla-JavaScript frontend over the existing APIs. The reference projects are used to answer presentation questions only. No React, Electron, Tauri, second database, second Job system, or second generation engine is justified for the current scope.

## Minimum first-time flow

1. Open or create a Study.
2. Add one reference image.
3. Describe the intended camera/action in the Intent field.
4. Choose a video type.
5. Adjust the small primary set: duration, quality, and the validated default generation profile.
6. Optionally expand Prompt Preview and run the existing prompt optimization path.
7. Generate.
8. Review the delivered output in the same Study.

The normal path should make Reference, Preview, Intent, Video Type, Duration, Quality, and Generate immediately legible. Resolution, FPS, Seed, prompt text, workflow details, Job Center, Environment, and Native Comfy remain secondary or advanced.

## Three primary references

- [InvokeAI](https://github.com/invoke-ai/InvokeAI) — local reviewed revision `4b2254bfbd631b5adcbdca482d188ef596df3cde`; study the unified visual workspace, reference/gallery thumbnails, task-oriented inspector, collapsible sections, and output/history recall. Its repository identifies the main license as Apache-2.0, with additional model/content licenses that do not enter AVS.
- [OpenScene](https://github.com/Theorvane/openscene) — local research revision `86e4be3ae2eeed51ba48abaa9df2a8bce46b6715`; study the desktop workspace composition, Program Monitor/preview relationship, compact toolbar, side-panel density, and local-first presentation. Its repository is MIT-licensed.
- [OpenCut Classic](https://github.com/OpenCut-app/opencut-classic) — local research revision `cf5e79e919144200294fb9fed22a222592a0aeea`; study the mature preview/inspector hierarchy, toolbar density, panel spacing, and desktop composition. Its repository is MIT-licensed and archived/read-only. The editor/timeline implementation is explicitly out of scope.

These projects are not product-model templates. AVS remains a Study-centered architectural video-generation workstation.

## Strongest patterns worth borrowing

- Make the video preview/viewport the visual anchor and let controls operate around it.
- Use a compact, technical topbar instead of a dashboard sidebar or marketing navbar.
- Use a right-side generation inspector with short sections and progressive disclosure.
- Keep the reference image visible as a small, meaningful thumbnail rather than a media-management system.
- Present status close to the viewport with semantic state, elapsed time, and the existing historical ETA behavior.
- Use thin dividers, compact controls, restrained status accents, and docked/collapsible panel language.

## Minimal Study workspace

```text
compact workstation topbar
  Study identity · workflow/video type · engine status

left, collapsible:   Reference
center, dominant:    Video Preview / delivered output / status strip
right, tool drawer:  Intent
                     Video Type
                     Duration
                     Quality
                     Generate
                     collapsed: Prompt Preview, Resolution, FPS, Seed
```

This is a presentation frame around existing Study/Job/Output contracts. It is not a timeline, clip editor, asset bin, or new state machine.

## Features intentionally not borrowed

No timeline editing, trimming, multi-track media, transitions, keyframes, effects, media-bin management, node editing, chat-agent workflow, plugin marketplace, model catalog, complex asset management, provider system, or reference-project database. These are either outside AVS's user goal or would introduce a competing source of truth.

## Direct reuse policy

No reference code is recommended for direct reuse in AVS. The cited implementations are framework- and product-state-bound. The small AVS equivalents should be local vanilla primitives: viewport frame, compact toolbar, collapsible inspector section, and thumbnail presentation. This is an easy port of interaction patterns, not a source-code import.

## Navigation blocker

The current audit found a concrete ownership risk: the HTML pages hardcode active navigation classes independently, while `ux2_shell.js` currently handles UX2 mode, the contextual Study link, and the legacy crumb rather than deriving one active route from the current location. This is sufficient to explain the reported “Study opens while Home remains highlighted” class of defect.

The reported later auto-navigation to Environment was not reproduced from the static source audit. `engine_status.js` refreshes engine status on a bounded interval and does not itself show a route redirect; runtime reproduction is still required before declaring it closed. Therefore navigation ownership remains a blocker for implementation work: no background health poll may take over the user's current page, and the active route must be tested across Home, Study, Jobs, Outputs, and Environment before UX2-P1.6 implementation proceeds.

## Architecture boundary

Study remains the primary product object. Job remains canonical execution truth. Studio state is a projection; Engine health remains independent. Prompt Engine, ETA semantics, output delivery, WebSocket observation, /history reconciliation, Golden workflows, models, and runtime remain unchanged.

Overall roadmap remains approximately 76%; this audit does not change that estimate. UX2-P2 is not started.
