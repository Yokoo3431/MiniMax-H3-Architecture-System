"""Hash contract for determining whether an optimized Prompt is current."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Mapping


def stable_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def reference_asset_hash(references: Iterable[Mapping[str, Any]]) -> str:
    values = [{
        "asset_id": str(item.get("id") or item.get("asset_id") or ""),
        "role": str(item.get("role") or "first_frame"),
        "sha256": str(item.get("sha256") or item.get("filename") or ""),
        "approval_state": str(item.get("state") or item.get("approval_state") or ""),
    } for item in references]
    values.sort(key=lambda item: (item["role"], item["asset_id"], item["sha256"]))
    return stable_hash(values)


def generation_parameters_hash(parameters: Mapping[str, Any] | None) -> str:
    return stable_hash(dict(parameters or {}))


def a4_profile_identity(workflow: str,
                        parameters: Mapping[str, Any] | None = None) -> dict[str, str]:
    """Return the versioned automatic profiles that condition an A4 prompt."""
    from runtime.a4_profiles import resolve_execution_profile

    values = dict(parameters or {})
    try:
        profile = resolve_execution_profile(
            workflow,
            values.get("quality", "NATIVE_HIGH"),
            duration=values.get("duration", 4.0),
            fps=values.get("fps", 24),
            seed=values.get("seed", 42),
        )
    except (TypeError, ValueError):
        # Legacy non-A4 fixtures remain hashable without inventing a profile.
        return {}
    return {
        "contract_version": profile["contract_version"],
        "quality_profile": profile["quality_profile"],
        "architecture_profile": profile["architecture_profile"],
        "architecture_profile_version": profile["architecture_profile_version"],
        "quality_profile_version": profile["quality_profile_version"],
        "prompt_profile_version": profile["prompt_profile_version"],
    }


def prompt_input_hash(intent: str, workflow: str, reference_hash: str,
                     parameters: Mapping[str, Any] | None = None,
                     provider: str | None = None) -> str:
    payload = {
        "original_intent": intent,
        "workflow_id": workflow,
        "reference_asset_hash": reference_hash,
        "generation_parameters_hash": generation_parameters_hash(parameters),
        "a4_profile_identity": a4_profile_identity(workflow, parameters),
    }
    if provider:
        payload["prompt_engine_provider"] = provider
    return stable_hash(payload)


def is_current_prompt(prompt: Mapping[str, Any] | None, *, intent: str,
                      workflow: str, reference_hash: str,
                      parameters: Mapping[str, Any] | None = None,
                      provider: str | None = None) -> bool:
    if not prompt or not prompt.get("verified", {}).get("pass"):
        return False
    effective_provider = provider or prompt.get("prompt_engine_provider")
    expected = prompt_input_hash(intent, workflow, reference_hash, parameters, effective_provider)
    return (
        prompt.get("status", "CURRENT") == "CURRENT"
        and prompt.get("workflow") == workflow
        and prompt.get("input_hash") == expected
    )
