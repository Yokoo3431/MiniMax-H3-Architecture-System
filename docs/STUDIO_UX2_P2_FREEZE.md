# Studio UX2 P2 Freeze

Status: P2.1–P2.6 freeze and packaged integration acceptance record.

## Scope

P2 preserves the frozen AVS architecture and makes the existing Study → Job →
Output flow observable and usable with real data. It does not add a second
database, Job system, generation engine, workflow truth, editor, timeline or
advanced product layer.

## Included contracts

- Study, project and Job context survives Home, Study, Jobs and Output links.
- Jobs expose canonical lifecycle, terminal truth, progress, elapsed time and
  historical ETA without fabricated progress.
- Completed outputs expose an authorized media URL with MP4 and byte-range
  delivery.
- ComfyUI observation is telemetry only when disconnected or stale; terminal
  history wins over stale queue state.
- Runtime recovery and production-ready gate checks remain bounded by the
  existing RC1 architecture.

## Freeze boundary

- Production ancestor: `85cfef4e48c307fd9e037b8ce3737ede9c7703ce`
- P1 freeze ancestor: `e8f7cd4bbfb85d8a5f1ec8ba89a732f1a6bb17a2`
- Branch: `feature/studio-ux-2`
- No release branch merge, tag or GitHub release is part of this freeze.

The exact P2 freeze SHA is recorded after commit. The package builder records
that SHA in `SHAREABLE_RC_MANIFEST.json` and rejects builds that are not based
on a verified Git commit.

## Validation baseline

The source validation target is 820 passing tests with 38 skipped, zero
unexpected failures, JavaScript syntax pass, Python compile pass and zero
Golden diff. Installed-product acceptance must use the packaged installation,
not a source preview or a duplicate server against the same userdata.
