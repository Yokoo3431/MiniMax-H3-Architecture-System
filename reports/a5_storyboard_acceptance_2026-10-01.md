# A5 Storyboard Guide Acceptance

Date: 2026-10-01  
Decision: `PASS_WITH_BOUNDED_LIMITATIONS`

## Scope and evidence

This closeout uses the already completed native multi-guide execution and its single controlled timing comparison. No new GPU job was submitted. The comparison held the workflow, reference assets, prompt intent, quality/runtime settings, and seed fixed while changing guide indexes from `36 / 72` to `24 / 84`.

- The first visible composition change moved with the first guide anchor.
- The later composition change stayed near frame 65 in both outputs; guide 2 influences the shot, but its transition time did not track the moved anchor.
- Sampled frames retain the same broad building identity, roof silhouette, shoreline, and forest context. No severe geometry redesign was observed.
- Fine facade/opening and material continuity are not rated because the evidence is limited to 832x480 previews.
- Transitions are abrupt editorial cuts, not continuous camera motion.
- The completed runs produced Studio-delivered media; the A5 native execution and result pipeline therefore have real end-to-end evidence.

## Delegated product review

Reviewer: Codex product review under the Owner's autonomous delegation. This is not an Owner review.

| Dimension | Assessment | Bounded conclusion |
|---|---:|---|
| Guide 1 influence | 4/5 | Visible transition follows the moved anchor in this controlled pair. |
| Guide 2 influence | 3/5 | The guide composition appears, but timing is weak and non-responsive in this pair. |
| Composition convergence | 3/5 | Coarse compositions converge; the exact transition point is soft. |
| Building/site identity | 4/5 | Broad identity and site context persist; no severe redesign is evident. |
| Fine facade/material continuity | Not rated | Insufficient preview detail for a reliable judgment. |
| Camera smoothness / between-guide morphing | 1/5 | Abrupt cuts; no continuous camera-path behavior. |
| Overall A5 use | Accept with limits | Suitable for coarse storyboard shot changes, not exact cut timing or direct camera control. |

The product contract and Studio copy describe requested guide times as intended cut positions and explicitly disclaim exact timing and continuous camera control. The versioned timing-prompt compiler (`a5.2-storyboard-timing-v1`) is covered by static/binding tests only; these GPU outputs predate it, so no visual improvement from that wording is claimed.

Antigravity's configured model/effort combination failed before returning an independent review. Per the master program's unavailable-review rule, Codex continued; no external opinion or score is represented here.

## Acceptance gates

- Native multi-guide execution: `PASS`.
- Technical generation-to-Studio-result pipeline: `PASS` on the existing runs.
- Visual behavior characterized: `PASS`, including guide-2 timing weakness.
- Architecture continuity: `PASS` for broad identity, with fine detail explicitly unrated.
- Transition usability: `PASS` for coarse storyboard cuts only; exact timing and camera-path claims are excluded.
- Storyboard UX: `PASS` by live desktop inspection of an existing two-guide Study and source controls. Approved-guide thumbnails, requested seconds, resolved indexes, reorder, replace/remove, validation feedback, and explicit runtime capability/routing state were visible; no native node IDs are exposed. This is an A5 usability check, not a claim of mobile/responsive certification.
- Regression: focused A5 guide, preflight, recovery, and Job/UX tests pass (63 tests); the same source commit's full suite passed 967 tests with 38 skipped and 0 failures.
- Golden V1: `ZERO DIFF`.
- Production runtime: ComfyUI 0.33.1 on 8189 remains healthy, queue idle, and without native AddGuide; experimental 0.36.0 on 8190 remains isolated with AddGuide and an empty queue.
- Privacy: no prompts, reference media, generated media, owner paths, credentials, or raw runtime logs are included in this record.
- Durable source before this record: branch `feature/h3-advanced-workflows`, commit `433437b32c93ac70b72df952a6031741ecc950c9`, equal to origin.

## Progress decision

A5 closes at its defined target: G `38%`, total product roadmap `89.60%`. The known timing and motion limitations remain part of the accepted capability boundary; this does not promote exact guide timing or continuous camera movement. The new prompt compiler's visual efficacy remains unvalidated and is not counted as evidence of improved adherence.

Next stage: A6 multi-reference role architecture.
