# Final C Prompt Intelligence Closeout

Date: 2026-10-05
Decision: `PASS`
Starting branch: `feature/h3-advanced-workflows`
Starting durable SHA: `5f31c4f6db20382e63903444c3e4200aea5def00`

## Scope

Close the remaining Prompt Intelligence acceptance gates without GPU work,
Comfy submissions, external prompt-provider calls, model downloads, or changes
to production workflows/runtime. The audit found and fixed a local-path privacy
leak in the explicitly selected CLI-provider path and added a legacy Prompt
schema regression.

## Acceptance evidence

| Requirement | Evidence | Result |
|---|---|---|
| Five Golden workflow families | Deterministic corpus compilation, architecture profile application, and final prompt binding to the execution graph | `PASS` |
| Director prompt compiler | Shot compile, prompt/execution equality, lineage, and camera-intent type tests | `PASS` |
| Reference roles and multi-reference semantics | Ref2VA role, ordering, provenance, and fail-closed tests | `PASS` |
| Timeline guide semantics | Deterministic guide prompt compilation, frame indexes, preview hash, and execution binding tests | `PASS` |
| Long-form prompt inheritance | Director shot settings inherit verified Prompt quality and duration; queue/continuity regression passes | `PASS` |
| Preservation vs. camera intent | Separate preservation clause and `PROMPT_CAMERA_INTENT` classification; no geometric camera-control claim | `PASS` |
| Default privacy boundary | `AUTO` remains `OFFLINE_COMPILER`; text-only requests omit local reference paths | `PASS` |
| Optional external/VLM path | Explicit provider selection and image-consent checks remain required | `PASS` |
| Determinism and provenance | Golden and guide compilers are deterministic; skill/profile/compiler versions and hashes are recorded | `PASS` |
| Stale Prompt detection and migration | Changed or missing skill/profile identity marks Prompt stale; legacy records block Job submission until regeneration | `PASS` |
| Preview matches execution contract | Golden binding, Director compile result, and guide execution preview/hash agree with the compiled execution prompt | `PASS` |

## Privacy defect fixed

`CLIReasoningProvider._request_text()` already removed image paths without
explicit multimodal consent, but the non-Antigravity CLI stdin JSON serialized
the original `request.__dict__`, bypassing that sanitizer. A selected text CLI
could therefore receive a local reference path even though it received no
image bytes.

Both printed and stdin CLI protocols now use one consent-gated request-data
builder. Unless the provider is multimodal-capable **and** the user explicitly
consents, both single-image and multi-image path fields are removed. A mocked
subprocess test inspects the exact stdin payload; no provider or network was
invoked.

## Validation and safety

- Full CPU regression: `1047 passed`, `4 skipped`, `0 failed`.
- Prompt corpus and runtime-binding focused suites: `8 passed` and `18 passed`.
- Frozen inventory/source-manifest tests: `13 passed`; inventory guard: `0 added / 0 removed / 0 skip changes`.
- Python compile, relevant JavaScript syntax, JSON parsing, and `git diff --check`: `PASS`.
- Golden workflow source files: `ZERO DIFF`.
- Studio health: `PASS`. Production ComfyUI: `0.33.1`, port `8189`, queue `0 running / 0 pending`.
- The production `MiniMaxH3AddGuide` lookup returned an empty node definition; capability remains `UNAVAILABLE`. The earlier HTTP-success-only probe was not valid registration evidence.
- No `/prompt`, GPU execution, external provider call, model download/copy, or runtime restart occurred. Experimental `8190` was not started.
- A test emitted its expected simulated “another launcher running” block message; the reported fixture PID was not running afterward.
- D: free space after validation was approximately `115.9 GiB`; no software or model assets were downloaded or duplicated.
- Privacy review of the changed diff: no owner prompt, media, credential, token, or private absolute path.

## External review

Antigravity review was unavailable. The Observer invocation failed before the
agent started because the Windows executor resolved `NUL` as a path. The single
CLI Bridge fallback returned `ANTIGRAVITY_UNAVAILABLE` because the installed
`agy.exe` rejected the required model/effort combination. It reported
`side_effect=false`; no external review result is claimed. Local tests and code
inspection remain the acceptance evidence.

## Roadmap

Final C closes at `100%`. With A–F and G weights unchanged, the implemented
roadmap moves from `95.80%` to `96.55%`. This does not complete the overall
product plan. Final D, E, and F remain open.

Next closeout stage: Final D RC Reliability.
