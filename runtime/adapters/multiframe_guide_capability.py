"""Explicit runtime capability gate for native H3 timeline guides."""

from __future__ import annotations

from typing import Any, Mapping


NODE_ID = "MiniMaxH3AddGuide"


def capability_from_object_info(object_info: Mapping[str, Any] | None, *,
                                runtime_name: str, version: str = "",
                                port: int | None = None) -> dict[str, Any]:
    info = object_info if isinstance(object_info, Mapping) else {}
    node = info.get(NODE_ID)
    available = isinstance(node, Mapping)
    required = set(((node or {}).get("input") or {}).get("required", {}))
    optional = set(((node or {}).get("input") or {}).get("optional", {}))
    schema_ready = available and {"positive", "latent", "frame_idx"}.issubset(required) \
        and {"image", "vae"}.issubset(optional)
    if not available:
        reason = f"native {NODE_ID} is not registered"
    elif not schema_ready:
        reason = f"native {NODE_ID} schema is incompatible"
    else:
        reason = ""
    return {
        "runtime": str(runtime_name),
        "version": str(version or "unknown"),
        "port": int(port) if port is not None else None,
        "node": NODE_ID,
        "available": bool(schema_ready),
        "status": "AVAILABLE" if schema_ready else "UNAVAILABLE",
        "reason": reason,
        "input_contract": {
            "required": sorted(required),
            "optional": sorted(optional),
        } if available else {},
        "routing": "EXPLICIT_ONLY",
    }


class MultiFrameGuideCapabilityAdapter:
    """Queries exactly the supplied Comfy client; never selects a fallback."""

    def __init__(self, client: Any, *, runtime_name: str,
                 version: str = "", port: int | None = None) -> None:
        self.client = client
        self.runtime_name = runtime_name
        self.version = version
        self.port = port

    def inspect(self) -> dict[str, Any]:
        object_info = self.client.object_info()
        return capability_from_object_info(
            object_info, runtime_name=self.runtime_name,
            version=self.version, port=self.port)

    def require(self) -> dict[str, Any]:
        result = self.inspect()
        if not result["available"]:
            raise RuntimeError(
                "GUIDE_RUNTIME_UNAVAILABLE: " + str(result["reason"]))
        return result


__all__ = ["NODE_ID", "MultiFrameGuideCapabilityAdapter", "capability_from_object_info"]
