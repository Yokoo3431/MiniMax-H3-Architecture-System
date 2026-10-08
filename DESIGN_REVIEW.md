# Final E / F Closeout — UX Review Checkpoint

Date: 2026-10-05  
Review status: PARTIAL — this checkpoint does not close Final E or Final F.

## Brief and scope

The Master Development Program is the governing brief. The primary audience is an architect using the Studio rather than a ComfyUI node editor. This checkpoint visually reviewed the Home, Study, Jobs, Outputs, and Environment surfaces in the existing local Studio. Captures were approximately 1250 × 700 screen pixels; the CSS viewport was not independently measured. No project assets, prompts, or media were exported for review.

## Findings and changes in this checkpoint

- Home previously showed its empty/default state while project and environment requests were still loading. It now presents an accessible loading status, keeps unhydrated content hidden, clears the status after resolution, and shows explicit failure text instead of implying an empty Study list.
- The `?new=1` entry still opens the new-Study form after hydration and focuses its title field.
- Environment showed a successful Torch/CUDA probe message in the error color. It now uses the success color when the probe status is `READY`; the live page was reloaded and the message displayed in green.
- The existing Study hydration/loading failure state remains in place and was visually/structurally checked earlier in this closeout.
- The Environment page reports that all required components are already ready and no installation is required. No installer or ComfyUI update was run.
- The Home overflow and repeated-navigation keyboard entry point were then isolated and corrected as detailed below.

## Responsive Home overflow and keyboard entry follow-up

- Used the application’s mock server at an isolated loopback port with a fresh temporary data root and synthetic Study names only. Production Studio data, ComfyUI, user media, and model folders were not accessed.
- At a requested 1250 × 700 probe viewport (the iframe border made the app CSS viewport 1248 px wide), an empty Home had no horizontal overflow. Four synthetic Studies, including long unbroken Latin and repeated Chinese titles, reproduced it: document `scrollWidth` reached 1514 px while `clientWidth` was 1233 px. The measured overflow was caused by the Home title’s flex item retaining its automatic min-content width; the long title forced the grid track wider and pushed the status badge outside the viewport.
- The Home card now allows its title flex item to shrink and wrap anywhere, keeps the state badge from shrinking, and lays the three card actions out in equal columns on narrow viewports. Re-running the same 1250 × 700 synthetic case measured `scrollWidth == clientWidth == 1248` with no out-of-viewport elements.
- At 375 × 812, the synthetic Home initially measured `scrollWidth 372` vs `clientWidth 358`. The card action buttons occupied about 348 px in a 310 px content row. After the narrow-screen grid fix, both widths measured 358 px and there were no out-of-viewport elements. The nav retains its intentional, confined horizontal scroller (`overflow-x:auto`); it no longer expands the document.
- Additional Home checks: 768 × 1024 measured document width 766/766; 1280 × 800 measured 1263/1263. Screenshots were visually inspected through the app browser using only synthetic data. The isolated headless Chrome/CDP harness could not start because this host’s Chrome GPU process terminated during initialization, so no persistent screenshot files were produced; no browser software was installed or downloaded.
- The “跳到主要内容” link now precedes the repeated navigation on all five primary pages. A real Tab interaction on the synthetic Home confirmed it is the first focused element and becomes visible; regression assertions enforce its document order on all primary pages.

## Remaining UX work

- Responsive evidence now covers Home, Study, Jobs, Outputs, and Environment at 375 × 812, 768 × 1024, and 1280 × 800 viewports. Environment was visually inspected at all three sizes; Jobs and Outputs were visually inspected at 375 px and measured at all three sizes; Study was visually inspected at 375 px and 1280 px and geometrically checked at 768 px. The remaining accessibility and product-state review is still open.
- The shared skip-link order and initial Home Tab behavior are fixed, but keyboard traversal, visible focus, screen-reader names, and error/status announcements still need a full page-by-page accessibility pass.
- The full Final E screen/state matrix and Final F clean-install/upgrade/repair/uninstall-preservation matrix have not been closed by this checkpoint.

## Environment mobile layout follow-up

- Reproduced a narrow-screen Environment overflow using only the isolated mock Studio and synthetic data. At a requested 375 × 812 viewport (373 px CSS viewport inside the probe frame), the document measured 455 px `scrollWidth` against 358 px `clientWidth`.
- The layout cause was implicit CSS Grid track sizing in the installer plan: an install-status label's min-content width expanded its grid track to about 431 px. The fixed 196 px Environment navigation column also left an unusably narrow inspector on mobile, and the shared 48 px fixed toolbar height did not account for wrapped mobile navigation.
- The installer plan now uses a shrinkable `minmax(0, 1fr)` track; cards and their contents can shrink and wrap. Below 760 px, Environment navigation and inspector stack, with group buttons arranged in two columns. Below 640 px, the shared toolbar expands to its wrapped content height, removes its flexible spacer, and keeps horizontal navigation contained.
- Recheck: Environment document widths were 358/358 at 375 px, 751/751 at 768 px, and 1263/1263 at 1280 px (`clientWidth`/`scrollWidth`). Jobs and Outputs also had equal client/scroll widths at all three breakpoints. Study measured equal client/scroll widths at 375, 768, and 1280 px. The intentional offscreen skip link is not page overflow and becomes visible when focused.
- A Tab check confirmed Environment's first focused control is “跳到主要内容” and that it becomes visible. Accessibility-tree inspection showed Environment groups and controls have accessible names; this is targeted evidence, not a complete keyboard/screen-reader audit.
- Screenshots were visually inspected through the in-app browser using the synthetic fixture. The isolated headless screenshot exporter remains unusable, so screenshots were not persisted; no screenshots or fixture data were added to the repository. The mock Environment installer panel is not evidence of the installed ComfyUI state. No ComfyUI install, duplicate download, update, restart, or GPU action was performed.

## Verification evidence

- Live Home: initial loading state is announced; after hydration, existing Studies and system readiness appear; the `?new=1` route preserves its intended form/focus behavior.
- Live Environment: ready state, component plan, and corrected success color confirmed. The plan explicitly reports no installation required.
- Environment responsive repair is covered by a new static regression assertion; live measurements show no app-document horizontal overflow at 375, 768, or 1280 px. Shared mobile toolbar geometry and Environment grid/card wrapping are also asserted.
- Automated canonical regression after the responsive/skip-link follow-up: 1053 tests, 4 expected skips, 0 failures. UX-focused tests: 14 passed; regression inventory/source manifest synchronized and verified.
- JavaScript syntax, Python compileall, JSON parse, regression inventory/source manifest, and `git diff --check`: PASS.
- Production ComfyUI remains 0.33.1 on its existing endpoint; the experimental endpoint remains offline. No new GPU generation was submitted.

## Disposition

This checkpoint is a targeted UX reliability improvement, not a Final E/F acceptance declaration. Keep the overall roadmap progress unchanged until the remaining responsive, accessibility, packaging, and release gates are evidenced.

## Job list keyboard semantics follow-up

- Replaced the focusable-but-nonsemantic Job table row with a named link on the Job ID. The link carries the current project and Job identity, and the existing query-driven detail loader opens the requested Job. Removed the row-only Enter handler and stale click-propagation workaround.
- Added regression assertions for the link name, encoded detail route, and preservation of the deep-link behavior. UX and inventory-focused checks passed (27 tests); the canonical CPU regression passed (1053 tests, 4 expected skips).
- This is a code-level keyboard semantics correction, not proof of a complete interactive accessibility audit. No new screenshot set was captured or saved during this follow-up; page-by-page keyboard, focus, screen-reader, and error-announcement review remains open.

## Final E responsive UX durable closeout — 2026-10-08

- Re-reviewed the final responsive CSS changes in `apps/architect_video_studio/frontend/css/avs_global_theme.css` and `apps/architect_video_studio/frontend/css/studio.css`. The navigation/status toolbar now wraps at tablet/mobile widths; the Study generation section no longer overlays preceding fields after the layout stacks; the Jobs table switches to labeled cards at 900 px and gives the creation timestamp a full row.
- Visually inspected all 15 existing synthetic-only viewport screenshots after the CSS edit timestamps: Home, Study, Jobs, Output, and Environment at 375 × 812, 768 × 1024, and 1280 × 800. The synthetic fixture contains no owner project/media data and the Environment screen explicitly marks host hardware as unqueried. No horizontal overflow appears in the manifest or in the captures; mobile Jobs timestamps remain readable and tablet Study controls no longer overlap.
- All 15 PNG files exist, have valid PNG signatures, and their pixel dimensions match the requested viewport dimensions. The manifest contains no stored hashes; SHA-256 fingerprints were computed during this closeout for all captures. The screenshots remain in the existing ignored `.codex_tmp/closeout-final-ux-20261008/screenshots/` evidence directory and are not staged.
- The screenshot set is viewport-sized, not full-page; below-fold sections were not claimed as visually reviewed. This closeout is a responsive layout review, not a complete keyboard, screen-reader, or WCAG contrast audit. Small secondary labels remain compact and can be revisited in a dedicated accessibility pass.
- Focused UX/inventory checks passed (57 tests); the canonical `unittest` suite passed (1,069 tests, 13 skipped, 0 failures). Tracked Python compilation, JavaScript syntax, tracked JSON parsing, Golden workflow diff, privacy scan, and `git diff --check` were also verified. No screenshots, prompts, reference media, or runtime data were added to Git.

### Screenshots Captured / Reviewed

| Page | Mobile | Tablet | Desktop |
| --- | --- | --- | --- |
| Home | `home_mobile_375x812.png` | `home_tablet_768x1024.png` | `home_desktop_1280x800.png` |
| Study | `workspace_a_completed_mobile_375x812.png` | `workspace_a_completed_tablet_768x1024.png` | `workspace_a_completed_desktop_1280x800.png` |
| Jobs | `job_center_mobile_375x812.png` | `job_center_tablet_768x1024.png` | `job_center_desktop_1280x800.png` |
| Output | `output_review_mobile_375x812.png` | `output_review_tablet_768x1024.png` | `output_review_desktop_1280x800.png` |
| Environment | `environment_mobile_375x812.png` | `environment_tablet_768x1024.png` | `environment_desktop_1280x800.png` |

Evidence directory (local, ignored): `.codex_tmp/closeout-final-ux-20261008/screenshots/`.
