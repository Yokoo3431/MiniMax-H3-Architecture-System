# Final D RC Reliability Closeout

Date: 2026-10-05
Decision: `PASS`
Starting durable SHA: `56315a05f29503b706ec2ba3463002f4d887f95a`

## Reliability campaign

The campaign used deterministic CPU-only fault injection, temporary test
stores/media, and a bounded read-only production health sample. It did not
submit Comfy `/prompt`, create a product Job, run inference, fill the disk,
restart production services, or start the experimental runtime.

| Area | Evidence | Result |
|---|---|---|
| Studio/Job restart and resume | New API/queue instances reload durable Job and long-form state; active prompt identity remains attached and is waited on rather than resubmitted | `PASS` |
| Comfy unavailable/reconnect | Observer disconnect and reconnect tests continue observing the same persisted `prompt_id`; submission method remains uncalled | `PASS` |
| Runtime unavailable / identity | Production and experimental runtime boundary, version/fingerprint/capability mismatch, and no-fallback tests | `PASS` |
| History reconciliation | Exact Job/prompt/workflow/runtime correlation recovers running/completed execution; ambiguous seed/latest matches are rejected | `PASS` |
| Observer disconnect | Observer/telemetry disconnect is kept separate from execution failure; terminal history wins over stale queue state | `PASS` |
| Packaging / media probe failures | Structured stages persist; same-runtime artifacts can be reprobed/repackaged without generation; corrupt/invalid media is rejected | `PASS` |
| Post-process failure | Delivery encode resumes from its checkpoint; low-disk reserve blocks before processing | `PASS` |
| Low disk | Disk usage is mocked as exhausted in temporary tests; assembly/delivery stop before FFmpeg and leave no partial output | `PASS` |
| Stale references / corrupt package / duplicate recovery | Existing provenance gates and idempotent recovery tests reject stale or mismatched identities and preserve one Result | `PASS` |
| Long-form partial failure | Completed shots remain durable; resume selects only the failed shot or assembly stage and retains prior lineage | `PASS` |
| Windows runtime isolation / cancellation | Launcher process identity, lock ownership, duplicate-start rejection, crash classification, and cancel-without-retry contracts | `PASS` |
| Duplicate `/prompt` prevention | Submission-unknown, observer reconnect, history recovery, cancellation, and queue-resume tests assert no second submission | `PASS` |
| Runtime identity preservation | Runtime ID/role/version/config/output fingerprints remain bound to Job and recovery selection | `PASS` |

Focused reliability suites passed `203` tests across result recovery, Comfy
reconciliation, A8 delivery, A9 queue/assembly, runtime identity, Windows
launcher/crash recovery, runtime capability/preflight, and execution-package
validation. The canonical suite remains `1047 passed`, `4 skipped`, `0 failed`.

## Bounded live stability sample

For 60 seconds, twelve GET-only samples checked Studio health, production
ComfyUI version, and queue counts at five-second intervals:

- Studio HTTP 200: `12/12`
- Production ComfyUI: `0.33.1` in `12/12` samples
- Maximum queue: `0 running / 0 pending`
- Probe failures: `0`

The production services were not intentionally restarted or taken offline
because the running Studio is user-facing. Restart, disconnect, and resume
failure modes were exercised using durable test stores and CPU fault-injection
fixtures instead. The 8190 experimental runtime remained offline. A test
fixture's simulated launcher-block PID was confirmed not running after tests.

## Safety and decision

- No new Job, `/prompt`, GPU execution, model change, or Golden workflow change.
- D: free space remained approximately `115.9 GiB`; no real low/full-disk condition was induced.
- No P0/P1 reliability defect was found in the exercised acceptance surface. This is bounded by the scenarios above, not a claim that every external Windows failure mode was exhaustively reproduced.
- Final D closes at `100%`. With C and D at 100%, the implemented roadmap is `96.85%`; E and F remain open.

Next closeout stage: Final E Studio UX 2.0.
