# Studio UX2 P2 Privacy Audit

Status: freeze-candidate audit; owner data remains local and read-only.

## Commit/package exclusions

The P2 commit and RC package must not contain:

- userdata, `jobs.json`, real Study records or owner identifiers;
- real prompts, prompt JSON, reference images, generated video or media logs;
- runtime logs, browser profiles, screenshots or `_research` material;
- API keys, tokens, credentials, AGY authentication/configuration or secrets;
- absolute personal output paths or machine-specific runtime state;
- model weights such as `.safetensors`, `.bin`, `.mp4`, `.mov` or `.avi`.

Public sample assets are permitted only when intentionally shipped by the
existing release builder. Model bodies remain external/shared and are never
bundled.

## Local-only material

`.github/agents/`, `.github/skills/`, `_research/`, local screenshots and
runtime/userdata are development or evidence material. They remain excluded
from the product freeze unless a later task explicitly approves them.

## Audit result

Candidate source changes are limited to frontend flow/presentation, the
existing mock API delivery contract, telemetry/runtime observation, tests and
release metadata needed to record the exact source commit. No owner userdata
or media is copied into the repository or package.
