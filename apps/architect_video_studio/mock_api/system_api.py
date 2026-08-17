"""System API (PATCH2.8-I1): Environment Center backend.

Read-only environment probe + path configuration. NEVER exposes or modifies
workflow JSON, runtime contracts, prompt pipeline, or system registry.
"""

from __future__ import annotations

from typing import Any, Dict

from .environment_service import EnvironmentService


class SystemAPI:
    def __init__(self, store, env_overrides=None) -> None:
        self.service = EnvironmentService(store, env_overrides)

    def environment(self) -> Dict[str, Any]:
        return self.service.environment()

    def configure(self, body: Dict[str, Any]) -> Dict[str, Any]:
        return self.service.configure(
            native_root=body.get("native_root", ""),
            models_root=body.get("models_root", ""),
        )

    def recheck(self) -> Dict[str, Any]:
        return self.service.recheck()

    def open_comfyui(self) -> Dict[str, Any]:
        return self.service.open_comfyui()
