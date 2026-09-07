# Studio UX2-P1 Freeze

Status: freeze candidate; exact commit SHA is recorded by the final Git audit
and owner report because a commit cannot contain its own content hash.

## Baseline and scope

- Production ancestor: `85cfef4e48c307fd9e037b8ce3737ede9c7703ce`
- Production branch: `release/v0.8.0-rc1` (unchanged)
- Feature branch: `feature/studio-ux-2`
- Pre-freeze remote feature SHA: `4ab9fbbfe83cdae147112cf5cc2e1f9690f8b105`
- Planning baseline: total roadmap `77.55%` (approximately `78%`)
- Freeze scope: accumulated UX2-P1 presentation, navigation/context continuity,
  local component packaging, focused tests, notices and freeze documentation.

## Final frontend stack

The final stack is documented in
`docs/STUDIO_UX2_P1_FINAL_STACK.md`. In summary, Study loads the existing
layout foundation, local Spectrum CSS, the Study geometry layer and the final
AVS global theme layer. Study uses native HTML controls and does not load
Shoelace. Non-Study pages retain Shoelace only where their existing markup
requires it. `theme.js` changes presentation tokens only.

## Pages and contract coverage

P1 covers shared navigation/theme/control normalization across Home, Study,
Jobs, Outputs and Environment while preserving their existing information
architecture. Study is the visual master: Reference dock, dominant Preview,
Generation inspector, compact status strip and collapsed technical settings.
Existing API routes, Study/Job/Output identity, prompt flow, generation wiring,
Engine status and Native Comfy diagnostics remain the source of truth.

## Acceptance evidence

- Responsive checks cover desktop widths and the narrow layout contract.
- Dark is the default; light is the same geometry using alternate tokens.
- Navigation has one route owner and preserves project/job context where
  supported.
- Background engine polling does not navigate the user.
- Test totals and the Golden diff are recorded in the final freeze report.

## Privacy and limitations

`docs/UX2_P1_PRIVACY_FREEZE.md` records the candidate-file audit. No backend,
runtime, model, Prompt Engine or Golden workflow changes are part of P1. The
visual result remains pending owner review; this freeze does not authorize P2
implementation, a release merge, a tag or an installer build.

## Explicit product boundary

UX2-P1 is presentation/usability work only. It does not add product features,
new state, new storage or new generation capability.
