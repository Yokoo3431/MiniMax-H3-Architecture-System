"""Hash contract for determining whether an optimized Prompt is current."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Mapping


def stable_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def reference_asset_hash(references: Iterable[Mapping[str, Any]]) -> str:
    values = sorted(
        str(item.get("sha256") or item.get("id") or item.get("filename") or "")
        for item in references
    )
    return stable_hash(values)


def generation_parameters_hash(parameters: Mapping[str, Any] | None) -> str:
    return stable_hash(dict(parameters or {}))


def prompt_input_hash(intent: str, workflow: str, reference_hash: str,
                     parameters: Mapping[str, Any] | None = None,
                     provider: str | None = None) -> str:
    payload = {
        "original_intent": intent,
        "workflow_id": workflow,
        "reference_asset_hash": reference_hash,
        "generation_parameters_hash": generation_parameters_hash(parameters),
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
