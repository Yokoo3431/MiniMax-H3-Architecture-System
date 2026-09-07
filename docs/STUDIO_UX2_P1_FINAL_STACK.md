# Studio UX2 P1 Final Frontend Stack

Status: freeze candidate for `feature/studio-ux-2`.

## Ownership

- Product state remains in the existing Study, Job, Engine and Output code.
- `ux2_shell.js` owns shared route highlighting and contextual query propagation.
- `theme.js` owns presentation-only dark/light preference handling (`avs-theme`).
- `avs_global_theme.css` is the final shared token and control-normalization layer.
- `ux2_p112_master.css` owns Study-specific layout geometry and compatibility rules.
- `studio.css` remains the legacy/shared layout foundation; it is not allowed to
  introduce a competing Study control system.
- Existing JavaScript handlers and DOM IDs remain the business integration
  boundary.

## Load order

### Study

1. `css/studio.css` — existing layout foundation
2. `vendor/spectrum/spectrum-dark.css` — locally packaged Spectrum CSS tokens and
   component references
3. `css/ux2_p112_master.css` — Study workspace composition and geometry
4. `css/avs_global_theme.css` — final AVS theme, typography, control and status
   normalization
5. `js/theme.js` — applies the persisted presentation theme without reloading
   product data
6. `js/ux2_shell.js` — route and Study-context navigation

Study uses native HTML controls styled by the AVS/Spectrum layers. Shoelace is
not loaded on `workspace.html`.

### Home, Jobs, Outputs and Environment

These pages retain their existing Shoelace runtime where their DOM still uses
Shoelace components. They load `studio.css`, local Shoelace assets,
`avs_global_theme.css`, `theme.js` and `ux2_shell.js`. This is a compatibility
boundary, not a second product state or API layer.

## Retained dependencies

- Adobe Spectrum CSS v2.13.0, Apache-2.0, local file:
  `apps/architect_video_studio/frontend/vendor/spectrum/spectrum-dark.css`.
- Shoelace v2.20.1, MIT, retained only for legacy non-Study surfaces that still
  use its elements.
- Existing selected Tabler SVGs, MIT, retained for navigation/action scanning.

No framework migration, runtime dependency, database, Job system or generation
dependency was added. No unused production dependency was removed in this
freeze; the Study surface simply no longer loads Shoelace.

## Final visual contract

One AVS token family controls dark/light surfaces, typography, spacing, control
heights, radii, focus, status semantics and restrained accent use. The Study
composition remains the approved three-column workspace: Reference dock,
dominant Preview, and Generation inspector. The other pages retain their
existing information architecture and receive shared visual normalization only.

## Intentionally excluded

The local Impeccable installation under `.github/skills/impeccable` is a
development tool/cache and is not part of the product runtime freeze. `_research`
and local screenshot evidence remain ignored. No owner data or media is vendored.
